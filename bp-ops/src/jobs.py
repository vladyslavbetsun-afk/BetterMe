"""Every background job, registered with core.scheduler. Shown on the status strip and in /admin/jobs."""

from datetime import date, datetime, timedelta

import config
import db
from core import business_days as bd
from core import jira, sync
from core.scheduler import Skip, register

WORKDAY_5MIN = "*/5 8-18 * * 1-5"
OFF_HOURS = ["7 0-7,19-23 * * 1-5", "7 * * * 0,6"]


def _jira_needed() -> str | None:
    return None if jira.auth_headers() else "Jira credentials not configured"


def _notion_needed() -> str | None:
    return None if config.NOTION_TOKEN else "NOTION_TOKEN not set"


@register("sync_jira_incremental", [WORKDAY_5MIN, *OFF_HOURS], 60, "Jira sync", _jira_needed)
def sync_jira_incremental():
    return sync.sync_incremental()


@register("sync_jira_full", ["5 2 * * *"], 26 * 60, "Jira full sync", _jira_needed)
def sync_jira_full():
    return sync.sync_full()


@register("sync_flow", ["*/30 8-18 * * 1-5", "15 2 * * *"], 24 * 60, "Flow metrics")
def sync_flow():
    from modules.flow import metrics

    metrics.rebuild(None)
    return db.scalar("select count(*) from stage_durations")


@register("qa_check_live", ["0 7 * * *"], 26 * 60, "Publishing QA")
def qa_check_live():
    from modules.flow import qa

    return qa.check()


@register("sync_notion_status", ["17 * * * *"], 2 * 60, "Notion ↔ Jira", _notion_needed)
def sync_notion_status():
    from modules.pipeline import service

    return service.sync_status()


@register("spend_compute", ["35 2 * * *"], 26 * 60, "Spend")
def spend_compute():
    from modules.spend import compute

    today = bd.local_today()
    n = compute.recompute(today.replace(day=1))
    if today.day <= 5:  # late transitions can still land in last month until it's closed
        n += compute.recompute((today.replace(day=1) - timedelta(days=1)).replace(day=1))
    return n


@register("report_build", ["0 17 * * 1-5"], 4 * 24 * 60, "Daily report")
def report_build():
    from modules.report import service

    service.build(bd.local_today(), created_by="schedule:bp-ops")
    return 1


@register("review_nudge_drafts", ["55 8-18 * * 1-5"], 4 * 24 * 60, "Nudge drafts")
def review_nudge_drafts():
    from modules.review import service

    return service.auto_drafts(actor="schedule:bp-ops")


@register("review_automation", ["52 8-18 * * 1-5"], 4 * 24 * 60, "Review automation")
def review_automation():
    if not db.flag("review_automation_enabled"):
        raise Skip("review_automation_enabled is off")
    from modules.review import service

    return service.run_automation(actor="schedule:bp-ops")


@register("retention", ["20 3 * * *"], 26 * 60, "Retention")
def retention():
    """Operational logs and messages: 90 days. Spend and performance history: 12 months (spec 05 §4)."""
    ops = datetime.now(config.TZ) - timedelta(days=90)
    year = date.today() - timedelta(days=366)
    n = 0
    n += db.execute("delete from audit_log where at < %s", (ops,))
    n += db.execute("delete from outbound_messages where created_at < %s", (ops,))
    n += db.execute("delete from actions where created_at < %s and state <> 'proposed'", (ops,))
    n += db.execute("delete from job_runs where started_at < %s", (ops,))
    n += db.execute("delete from report_lines where day < %s", (ops.date(),))
    n += db.execute("delete from spend_lines where month < %s", (year,))
    n += db.execute("delete from spend_months where month < %s", (year,))
    n += db.execute("delete from ahrefs_page_weekly where week < %s", (year,))
    n += db.execute("delete from ai_citations_weekly where week < %s", (year,))
    n += db.execute("delete from flow_daily where date < %s", (year,))
    return n
