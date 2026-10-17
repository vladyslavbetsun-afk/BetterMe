"""Publish (spec 05 §8.5), ported from legacy/bp-publishing-batches.html."""

import os
import uuid
from datetime import datetime

import config
import db
from core import business_days as bd
from core import outbound, slack
from modules.images import service as images

YULIIA_PERSON = "yuliia_k"


def ready_queue(scope: str = "mine") -> list[dict]:
    sql = "select * from tickets where status = 'Ready'"
    params: tuple = ()
    if scope == "mine":
        sql += " and %s = any(managers)"
        params = (config.OWNER_ACCOUNT_ID,)
    rows = db.query(sql + " order by entered_ready_at nulls first", params)
    keys = [r["jira_key"] for r in rows]
    links = images.image_links(keys)
    in_batch = {r["jira_key"]: r["n"] for r in db.query(
        "select bi.jira_key, b.n from batch_items bi join batches b on b.id = bi.batch_id where not b.archived")}
    now = datetime.now(config.TZ)
    for r in rows:
        r["images"] = links.get(r["jira_key"], [])
        r["batch"] = in_batch.get(r["jira_key"])
        r["age"] = bd.elapsed(r["entered_ready_at"], now) if r["entered_ready_at"] else None
        r["yuliia"] = config.YULIIA_K_ACCOUNT_ID in (r["participants"] or [])
    return rows


def batches() -> list[dict]:
    bs = db.query("select * from batches where not archived order by n desc")
    for b in bs:
        b["items"] = db.query("select bi.position, t.* from batch_items bi left join tickets t using (jira_key) "
                              "where bi.batch_id = %s order by bi.position", (b["id"],))
        b["done"] = all(i["status"] == "Published" for i in b["items"])
        b["message"] = db.one("select * from outbound_messages where id = %s", (b["message_id"],)) \
            if b["message_id"] else None
    return bs


def live_ready() -> list[dict]:
    """Tickets with Yuliia's live link that aren't Published yet: propose → Published."""
    return db.query("select * from tickets where status = 'Ready' and live_url ~* %s order by jira_key",
                    (r"^https?://(www\.)?betterme\.world/",))


def create_batch(keys: list[str], actor: str) -> dict:
    n = (db.scalar("select coalesce(max(n), 0) from batches") or 0) + 1
    bid = "b" + uuid.uuid4().hex[:10]
    with db.conn() as c:
        c.execute("insert into batches (id, n) values (%s, %s)", (bid, n))
        for i, k in enumerate(keys):
            c.execute("insert into batch_items (batch_id, jira_key, position) values (%s, %s, %s)", (bid, k, i))
    db.audit(actor, "batch.created", bid, {"n": n, "keys": keys})
    return db.one("select * from batches where id = %s", (bid,))


def suggest(size: int) -> list[str]:
    """Oldest Ready tickets with images that aren't in a batch yet."""
    return [r["jira_key"] for r in ready_queue("mine") if r["images"] and not r["batch"]][:size]


def batch_text(keys: list[str]) -> str:
    """Publishing batch DM, verbatim template from 00 §3 (full summary, as Publishing Batches sends today)."""
    titles = {r["jira_key"]: r["summary"] for r in db.query("select jira_key, summary from tickets "
                                                            "where jira_key = any(%s)", (keys,))}
    return "Hi. Here are articles for publishing:\n" + slack.mrkdwn_list(
        [(config.ticket_url(k), f"{k} {titles.get(k, '')}".strip()) for k in keys])


def prepare_send(batch_id: str, actor: str, post_at: datetime | None = None) -> dict:
    """Draft the batch message (once per batch and day) and propose adding Yuliia to Request participants."""
    keys = [r["jira_key"] for r in db.query("select jira_key from batch_items where batch_id = %s order by position",
                                            (batch_id,))]
    channel = "slack_channel" if slack.bot_configured() else "slack_dm"
    recipient = os.environ.get("SLACK_OPS_CHANNEL") if channel == "slack_channel" else config.SLACK_YULIIA_K
    msg, _ = outbound.draft_message(kind="batch", channel=channel, recipient=recipient, template="publishing_batch",
                                    body=batch_text(keys), ticket_keys=keys, created_by=actor)
    db.execute("update batches set post_at = %s, message_id = %s where id = %s", (post_at, msg["id"], batch_id))
    for t in db.query("select jira_key, participants from tickets where jira_key = any(%s)", (keys,)):
        if config.YULIIA_K_ACCOUNT_ID not in (t["participants"] or []):
            parts = [{"accountId": a} for a in dict.fromkeys([*(t["participants"] or []), config.YULIIA_K_ACCOUNT_ID])]
            outbound.propose("jira.participants", t["jira_key"],
                             {"ops": [{"op": "edit", "fields": {config.F_PARTICIPANTS: parts}}],
                              "description": "add Yuliia Koreniuk to Request participants"}, actor,
                             outbound.idempotency_key("participants", t["jira_key"], [t["jira_key"]],
                                                      bd.local_today(), "yuliia"))
    return msg


def mark_batch_sent(batch_id: str, message_id: int, actor: str) -> None:
    outbound.mark_sent(message_id, actor)
    db.execute("update batches set sent_at = coalesce(sent_at, now()) where id = %s", (batch_id,))


def propose_published(key: str, actor: str) -> dict:
    return outbound.propose("jira.publish", key, {"ops": [{"op": "transition", "to": "Published"}],
                                                  "description": "move to Published"}, actor,
                            outbound.idempotency_key("publish", key, [key], bd.local_today(), "published"))
