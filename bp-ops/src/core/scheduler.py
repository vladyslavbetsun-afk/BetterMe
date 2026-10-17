"""In-process scheduler (spec 05 §3): APScheduler + one Postgres advisory lock per job + a job_runs row per run.

A restart or a second replica can't double-run a job: the run is skipped when the lock is held elsewhere.
"""

import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import psycopg
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

import config
import db

log = logging.getLogger("bp-ops.scheduler")


class Skip(Exception):  # noqa: N818 - raised by a job to record status 'skipped' with a reason
    def __init__(self, reason: str, status: str = "skipped"):
        super().__init__(reason)
        self.status = status


@dataclass
class Job:
    name: str
    fn: Callable[[], int | None]
    crons: list[str]           # 5-field cron expressions, Europe/Brussels
    expected_minutes: int      # used by the status strip: amber after 1.5× this without a success
    label: str
    needs: Callable[[], str | None] | None = None  # returns a reason when the job can't run (e.g. secret missing)


JOBS: dict[str, Job] = {}


def register(name: str, crons: list[str], expected_minutes: int, label: str,
             needs: Callable[[], str | None] | None = None):
    def deco(fn):
        JOBS[name] = Job(name, fn, crons, expected_minutes, label, needs)
        return fn
    return deco


def _lock_id(name: str) -> int:
    return int.from_bytes(name.encode()[:8].ljust(8, b"\0"), "big") & 0x7FFFFFFFFFFFFFFF


def run(name: str) -> dict:
    """Run a job now (scheduler or the Admin "Run now" button). Returns the job_runs row."""
    job = JOBS[name]
    with psycopg.connect(config.DATABASE_URL, autocommit=True) as lock_conn:
        got = lock_conn.execute("select pg_try_advisory_lock(%s)", (_lock_id(name),)).fetchone()[0]
        if not got:
            return {"job": name, "status": "skipped", "error": "already running"}
        try:
            run_id = db.scalar("insert into job_runs (job) values (%s) returning id", (name,))
            status, rows, error = "ok", None, None
            try:
                reason = job.needs() if job.needs else None
                if reason:
                    raise Skip(reason)
                rows = job.fn()
            except Skip as s:
                status, error = s.status, str(s)
            except Exception as e:
                status, error = "failed", f"{e}\n{traceback.format_exc(limit=3)}"[:2000]
                log.exception("job %s failed", name)
            db.execute("update job_runs set finished_at = now(), status = %s, rows = %s, error = %s where id = %s",
                       (status, rows if isinstance(rows, int) else None, error, run_id))
            return db.one("select * from job_runs where id = %s", (run_id,))
        finally:
            lock_conn.execute("select pg_advisory_unlock(%s)", (_lock_id(name),))


_sched: BackgroundScheduler | None = None


def start() -> None:
    global _sched
    if _sched or not config.SCHEDULER_ENABLED:
        return
    _sched = BackgroundScheduler(timezone=config.TZ)
    for job in JOBS.values():
        triggers = [CronTrigger.from_crontab(c, timezone=config.TZ) for c in job.crons]
        trig = triggers[0] if len(triggers) == 1 else OrTrigger(triggers)
        _sched.add_job(run, trig, args=[job.name], id=job.name, max_instances=1, coalesce=True,
                       misfire_grace_time=300)
    _sched.start()


def stop() -> None:
    global _sched
    if _sched:
        _sched.shutdown(wait=False)
        _sched = None


def health() -> list[dict]:
    """One chip per job: last success, last run status, and a colour (spec 01 §6.1)."""
    rows = {r["job"]: r for r in db.query(
        "select distinct on (job) job, started_at, finished_at, status, error from job_runs "
        "order by job, started_at desc")}
    ok = {r["job"]: r["t"] for r in db.query(
        "select job, max(finished_at) as t from job_runs where status = 'ok' group by job")}
    now = datetime.now(config.TZ)
    out = []
    for job in JOBS.values():
        last = rows.get(job.name)
        last_ok = ok.get(job.name)
        reason = job.needs() if job.needs else None
        if reason:
            colour = "grey"
        elif last and last["status"] == "failed":
            colour = "red"
        elif last_ok is None or (now - last_ok).total_seconds() > job.expected_minutes * 90:
            colour = "amber"
        else:
            colour = "green"
        out.append({"name": job.name, "label": job.label, "colour": colour, "last_ok": last_ok,
                    "last_status": last["status"] if last else None, "error": (last or {}).get("error"),
                    "not_configured": reason})
    return out
