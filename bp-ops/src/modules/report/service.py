"""Daily report (spec 05 §8.7): built at 17:00 Brussels from the day's data, in Vladyslav's DM format."""

from datetime import date, datetime, time, timedelta

import config
import db
from core import outbound


def _bounds(day: date) -> tuple[datetime, datetime]:
    lo = datetime.combine(day, time(0), tzinfo=config.TZ)
    return lo, lo + timedelta(days=1)


def facts(day: date) -> dict:
    lo, hi = _bounds(day)
    moved = db.query("select s.jira_key, s.to_status, t.type from status_transitions s join tickets t using (jira_key) "
                     "where s.at >= %s and s.at < %s", (lo, hi))

    def keys(status, typ=None):
        return sorted({m["jira_key"] for m in moved if m["to_status"] == status and (typ is None or m["type"] == typ)})

    tim_added = db.scalar("select count(distinct jira_key) from field_changes where field_id = %s and to_value = %s "
                          "and at >= %s and at < %s", (config.F_PROOFREADER, config.TIM_ACCOUNT_ID, lo, hi)) or 0
    images = db.scalar("select count(distinct c.jira_key) from comments c where c.author_account_id = any(%s) "
                       "and c.created_at >= %s and c.created_at < %s and cardinality(c.links) > 0",
                       (list(config.IMAGE_POSTERS), lo, hi)) or 0
    batches = db.query("select n from batches where sent_at >= %s and sent_at < %s order by n", (lo, hi))
    ready_no_img = db.scalar(
        "select count(*) from tickets t where t.status = 'Ready' and not exists (select 1 from comments c where "
        "c.jira_key = t.jira_key and c.author_account_id = any(%s) and cardinality(c.links) > 0)",
        (list(config.IMAGE_POSTERS),)) or 0
    qa = db.scalar("select count(*) from qa_checks where mismatch") or 0
    failed = [r["job"] for r in db.query("select distinct job from job_runs where status = 'failed' and started_at >= %s "
                                         "and started_at < %s", (lo, hi))]
    lines = [r["text"] for r in db.query("select text from report_lines where day = %s order by id", (day,))]
    return {"day": day, "published_new": keys("Published", "new"), "published_upd": keys("Published", "update"),
            "to_text": keys("Text"), "to_review": keys("Review"), "to_ready": keys("Ready"),
            "to_proof": keys("Proofreading"), "tim_added": tim_added, "images": images,
            "batches": [b["n"] for b in batches], "ready_no_images": ready_no_img, "qa": qa, "failed": failed,
            "lines": lines}


def text(f: dict) -> str:
    def plural(n, word):
        return f"{n} {word}{'' if n == 1 else 's'}"

    assigned = len(f["to_text"]) + len(f["to_review"]) + f["tim_added"]
    out = ["Report:",
           f"• {plural(len(f['published_new']), 'article')} published",
           f"• {plural(len(f['published_upd']), 'article')} updated",
           f"• New tasks for writers/proofreader/designer/experts ({assigned} assigned)"]
    out += [f"• {ln}" for ln in f["lines"]]
    blockers = []
    if f["ready_no_images"]:
        blockers.append(f"{f['ready_no_images']} Ready without images")
    if f["qa"]:
        blockers.append(f"{f['qa']} published in Jira but page unchanged")
    if f["failed"]:
        blockers.append("failed job: " + ", ".join(f["failed"]))
    if blockers:
        out.append("• Bottleneck: " + "; ".join(blockers))
    return "\n".join(out)


def build(day: date, created_by: str) -> dict:
    """Draft (once per day and content) the report DM to Volodymyr."""
    body = text(facts(day))
    msg, _ = outbound.draft_message(kind="report", channel="slack_dm", recipient=config.SLACK_VOLODYMYR,
                                    template="daily_report", body=body, ticket_keys=[], created_by=created_by, day=day)
    if msg["body"] != body and msg["state"] == "draft":
        db.execute("update outbound_messages set body = %s where id = %s", (body, msg["id"]))
        msg["body"] = body
    return msg
