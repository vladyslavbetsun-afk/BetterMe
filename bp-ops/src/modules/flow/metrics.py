"""Flow metrics (spec 04 §3). Ticket- and stage-level only: nothing here is grouped by person (Legal gate, spec 05 §4).

stage_durations and flow_daily are rebuilt from status_transitions after every Jira sync.
"""

import statistics
from datetime import date, datetime, time, timedelta

import config
import db
from core import business_days as bd

STAGES = config.STATUSES
FLOW_DAYS = 90


def _holidays() -> list:
    return db.get_setting("holidays", []) or []


def visits(created_at: datetime | None, current: str | None, transitions: list[dict]) -> list[tuple[str, datetime, datetime | None]]:
    """[(stage, entered_at, exited_at)] — one row per visit, so a Review → Text → Review bounce gives two visits."""
    trs = sorted(transitions, key=lambda t: t["at"])
    out = []
    stage = trs[0]["from_status"] if trs and trs[0]["from_status"] else (current or "Open")
    entered = created_at or (trs[0]["at"] if trs else None)
    for t in trs:
        if entered is not None:
            out.append((stage, entered, t["at"]))
        stage, entered = t["to_status"], t["at"]
    if entered is not None:
        out.append((stage, entered, None))
    return out


def rebuild(keys: list[str] | None) -> None:
    hol = _holidays()
    now = datetime.now(config.TZ)
    with db.conn() as c:
        if keys is None:
            tickets = c.execute("select jira_key, created_at, status from tickets").fetchall()
        elif keys:
            tickets = c.execute("select jira_key, created_at, status from tickets where jira_key = any(%s)",
                                (keys,)).fetchall()
        else:
            tickets = []
        if tickets:
            ks = [t["jira_key"] for t in tickets]
            trs: dict[str, list] = {}
            for r in c.execute("select * from status_transitions where jira_key = any(%s)", (ks,)).fetchall():
                trs.setdefault(r["jira_key"], []).append(r)
            c.execute("delete from stage_durations where jira_key = any(%s)", (ks,))
            for t in tickets:
                for stage, ent, ex in visits(t["created_at"], t["status"], trs.get(t["jira_key"], [])):
                    c.execute("insert into stage_durations (jira_key, stage, entered_at, exited_at, business_days) "
                              "values (%s, %s, %s, %s, %s) on conflict do nothing",
                              (t["jira_key"], stage, ent, ex, bd.elapsed(ent, ex or now, hol)))
    rebuild_daily()


def _end_of(d: date) -> datetime:
    return datetime.combine(d + timedelta(days=1), time(0), tzinfo=config.TZ)


def rebuild_daily(days: int = FLOW_DAYS) -> None:
    """flow_daily: per day and stage, WIP at the end of the day, inflow and outflow during the day."""
    today = bd.local_today()
    start = today - timedelta(days=days)
    rows = db.query("select jira_key, stage, entered_at, exited_at from stage_durations where exited_at is null "
                    "or exited_at >= %s", (datetime.combine(start, time(0), tzinfo=config.TZ),))
    out: dict[tuple[date, str], list[int]] = {}
    d = start
    while d <= today:
        lo, hi = datetime.combine(d, time(0), tzinfo=config.TZ), _end_of(d)
        for s in STAGES:
            out[(d, s)] = [0, 0, 0]
        for r in rows:
            s = r["stage"]
            if s not in STAGES:
                continue
            if r["entered_at"] < hi and (r["exited_at"] is None or r["exited_at"] >= hi):
                out[(d, s)][0] += 1
            if lo <= r["entered_at"] < hi:
                out[(d, s)][1] += 1
            if r["exited_at"] is not None and lo <= r["exited_at"] < hi:
                out[(d, s)][2] += 1
        d += timedelta(days=1)
    with db.conn() as c:
        c.execute("delete from flow_daily where date >= %s", (start,))
        with c.cursor() as cur:
            cur.executemany("insert into flow_daily (date, stage, wip, inflow, outflow) values (%s, %s, %s, %s, %s)",
                            [(k[0], k[1], *v) for k, v in out.items()])


# --- read-side metrics -------------------------------------------------------------------------------

def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def published_per_day(days: list[date]) -> list[int]:
    if not days:
        return []
    lo = datetime.combine(days[0], time(0), tzinfo=config.TZ)
    hi = _end_of(days[-1])
    rows = db.query("select at from status_transitions where to_status = 'Published' and at >= %s and at < %s",
                    (lo, hi))
    counts = {d: 0 for d in days}
    for r in rows:
        d = r["at"].astimezone(config.TZ).date()
        if d in counts:
            counts[d] += 1
        else:  # published on a weekend/holiday: count it on the next business day in the window
            nxt = next((x for x in days if x > d), None)
            if nxt:
                counts[nxt] += 1
    return [counts[d] for d in days]


def last_business_days(n: int, until: date | None = None) -> list[date]:
    hol = _holidays()
    until = until or bd.local_today()
    out, d = [], until
    while len(out) < n:
        if bd.is_business_day(d, hol):
            out.append(d)
        d -= timedelta(days=1)
    return list(reversed(out))


def throughput(n: int) -> dict:
    days = last_business_days(n)
    per = published_per_day(days)
    return {"days": [d.isoformat() for d in days], "per_day": per,
            "mean": statistics.fmean(per) if per else 0.0, "median": statistics.median(per) if per else 0.0}


def clearance(backlog: int, rate: float, extra_inflow: float = 0.0, start: date | None = None) -> dict:
    """Business days and calendar date to clear `backlog` at `rate`/day with `extra_inflow`/day arriving."""
    net = rate - extra_inflow
    start = start or bd.local_today()
    if backlog <= 0:
        return {"business_days": 0, "date": start.isoformat()}
    if net <= 0:
        return {"business_days": None, "date": None}
    n = backlog / net
    return {"business_days": n, "date": bd.add_business_days(start, n, _holidays()).isoformat()}


def summary() -> dict:
    """Everything the /flow page needs, in one dict."""
    from modules.images import service as images

    hol = _holidays()
    now = datetime.now(config.TZ)
    wip = {s: 0 for s in STAGES}
    for r in db.query("select status, count(*) n from tickets where status = any(%s) group by status", (STAGES,)):
        wip[r["status"]] = r["n"]
    ready = db.query("select jira_key, summary, type, word_min, word_max, entered_ready_at from tickets "
                     "where status = 'Ready' order by entered_ready_at nulls first")
    img = images.status_for([r["jira_key"] for r in ready])
    batch_of = {r["jira_key"]: r["n"] for r in db.query(
        "select bi.jira_key, b.n from batch_items bi join batches b on b.id = bi.batch_id where not b.archived")}
    ages = []
    for r in ready:
        r["age"] = bd.elapsed(r["entered_ready_at"], now, hol) if r["entered_ready_at"] else None
        r["images"] = img.get(r["jira_key"], "missing")
        r["batch"] = batch_of.get(r["jira_key"])
        if r["age"] is not None:
            ages.append(r["age"])
    t10, t20 = throughput(10), throughput(20)
    rate = t10["median"] or t10["mean"]
    week_start = bd.local_today() - timedelta(days=bd.local_today().weekday())
    ws = datetime.combine(week_start, time(0), tzinfo=config.TZ)
    inflow_week = db.scalar("select count(*) from status_transitions where to_status = 'Ready' and at >= %s", (ws,))
    outflow_week = db.scalar("select count(*) from status_transitions where to_status = 'Published' and at >= %s",
                             (ws,))
    since90 = now - timedelta(days=90)
    lead = {}
    for s in STAGES[:-1]:
        xs = [r["business_days"] for r in db.query(
            "select business_days from stage_durations where stage = %s and exited_at >= %s", (s, since90))]
        lead[s] = {"median": pct(xs, 0.5), "p90": pct(xs, 0.9), "n": len(xs)}
    longest = max((s for s in lead if lead[s]["median"] is not None), key=lambda s: lead[s]["median"], default=None)
    e2e = end_to_end(since90, hol)
    rework = rework_rate(since90)
    hist = {"0–1": 0, "2–3": 0, "4–5": 0, "6–10": 0, ">10": 0}
    for a in ages:
        k = "0–1" if a < 2 else "2–3" if a < 4 else "4–5" if a < 6 else "6–10" if a <= 10 else ">10"
        hist[k] += 1
    oldest = {}
    for s in ["Open", "Text", "Review", "Proofreading", "Ready"]:
        rows = db.query("select t.jira_key, t.summary, sd.entered_at from tickets t join stage_durations sd "
                        "on sd.jira_key = t.jira_key and sd.stage = t.status and sd.exited_at is null "
                        "where t.status = %s order by sd.entered_at limit 5", (s,))
        for r in rows:
            r["age"] = bd.elapsed(r["entered_at"], now, hol)
        oldest[s] = rows
    cfd = db.query("select date, stage, wip, inflow, outflow from flow_daily where date >= %s order by date",
                   (bd.local_today() - timedelta(days=60),))
    days30 = last_business_days(30)
    ready_in = {d: 0 for d in days30}
    for r in db.query("select date, inflow from flow_daily where stage = 'Ready' and date >= %s", (days30[0],)):
        if r["date"] in ready_in:
            ready_in[r["date"]] = r["inflow"]
    qa = db.query("select q.*, t.summary, t.entered_published_at, t.live_url from qa_checks q "
                  "join tickets t using (jira_key) where q.mismatch order by t.entered_published_at desc")
    return {
        "wip": wip, "ready": ready,
        "ready_with_images": sum(1 for r in ready if r["images"] in ("complete", "not_needed")),
        "ready_age": {"p50": pct(ages, 0.5), "p90": pct(ages, 0.9), "max": max(ages) if ages else None},
        "throughput10": t10, "throughput20": t20, "rate": rate,
        "clearance": clearance(len(ready), rate),
        "net_week": (inflow_week or 0) - (outflow_week or 0), "inflow_week": inflow_week, "outflow_week": outflow_week,
        "lead": lead, "longest_stage": longest, "e2e": e2e, "rework": rework, "hist": hist, "oldest": oldest,
        "cfd": cfd, "io": {"days": [d.isoformat() for d in days30], "inflow": [ready_in[d] for d in days30],
                           "outflow": published_per_day(days30)},
        "qa": qa, "holidays": hol, "batch_size": db.get_setting("publish.batch_size", 4),
    }


def end_to_end(since: datetime, hol) -> dict:
    rows = db.query("select t.jira_key, t.type, t.created_at, "
                    "(select min(at) from status_transitions s where s.jira_key = t.jira_key and to_status = 'Text') "
                    "as text_at, t.entered_published_at from tickets t where t.entered_published_at >= %s", (since,))
    out = {}
    for typ in ("new", "update"):
        sub = [r for r in rows if r["type"] == typ]
        o2p = [bd.elapsed(r["created_at"], r["entered_published_at"], hol) for r in sub if r["created_at"]]
        t2p = [bd.elapsed(r["text_at"], r["entered_published_at"], hol) for r in sub if r["text_at"]]
        out[typ] = {"open_to_pub": {"median": pct(o2p, .5), "p90": pct(o2p, .9), "n": len(o2p)},
                    "text_to_pub": {"median": pct(t2p, .5), "p90": pct(t2p, .9), "n": len(t2p)}}
    return out


def rework_rate(since: datetime) -> dict:
    """Share of tickets that entered Review in the window and bounced back (Review → Text or Proofreading → Review)."""
    total = db.scalar("select count(distinct jira_key) from status_transitions where to_status = 'Review' "
                      "and at >= %s", (since,)) or 0
    bounced = db.scalar("select count(distinct jira_key) from status_transitions where at >= %s and "
                        "((from_status = 'Review' and to_status = 'Text') or "
                        "(from_status = 'Proofreading' and to_status = 'Review'))", (since,)) or 0
    return {"total": total, "bounced": bounced, "rate": (bounced / total) if total else None}


def slack_summary(s: dict) -> str:
    rate = s["rate"]
    c = s["clearance"]
    n = len(s["ready"])
    clears = (f"At {rate:g}/day the backlog of {n} clears on {datetime.fromisoformat(c['date']):%b %-d}."
              if c["date"] else f"At {rate:g}/day the backlog of {n} doesn't clear.")
    return "\n".join([
        f"• Ready backlog: {n} ({s['ready_with_images']} with images)",
        f"• Publishing throughput: {rate:g}/day (10-day median)",
        f"• Net flow this week: {s['net_week']:+d}",
        f"• {clears}",
        f"• QA mismatches: {len(s['qa'])}",
    ])
