"""Pipeline (spec 05 §8.1), from legacy/blog-pipeline-editor.html, plus Notion ↔ Jira status sync."""

import re

import config
import db
from core import business_days as bd
from core import notion, outbound

PRIORITY_RE = re.compile(r"\((Week|October)\)\s*$")


def cards() -> list[dict]:
    rows = db.query("select n.*, t.status as jira_status, t.live_url, t.summary from notion_cards n "
                    "left join tickets t on t.jira_key = n.jira_key "
                    "where n.status in ('Not started', 'In progress', 'Done') order by n.number nulls last")
    for r in rows:
        want = config.NOTION_STATUS_FOR.get(r["jira_status"]) if r["jira_status"] else None
        r["expected"] = want
        r["mismatch"] = bool(want and want != r["status"])
        r["is_priority"] = bool(PRIORITY_RE.search(r["priority"] or ""))
    return rows


def missing_cards() -> list[dict]:
    """Jira tickets in the sync window that have no Notion card."""
    return db.query("select t.* from tickets t where (t.status <> 'Published' or t.updated_at >= now() - interval "
                    "'30 days') and not exists (select 1 from notion_cards n where n.jira_key = t.jira_key) "
                    "order by t.key_num desc")


def update_props(card: dict) -> dict:
    """What the card should become: Status from Jira, plus URL 1 = live URL once Published (spec 05 §8.1)."""
    props = {"Status": card["expected"]}
    if card["jira_status"] == "Published" and card["live_url"] and card["url1"] != card["live_url"]:
        props["URL 1"] = card["live_url"]
    return props


def sync_status() -> int:
    """Hourly: pull Notion, propose a fix for every mismatch, apply automatically only with pipeline.auto_close."""
    notion.pull()
    auto = db.flag("pipeline.auto_close") and db.flag("notion_writes_enabled")
    n = 0
    for c in cards():
        if not c["mismatch"]:
            continue
        props = update_props(c)
        idem = outbound.idempotency_key("notion", c["page_id"], [c["jira_key"]], bd.local_today(),
                                        f"status:{props['Status']}")
        a = outbound.propose("notion.update", c["jira_key"], {"page_id": c["page_id"], "properties": props,
                                                             "description": f"Notion card #{c['number']}: "
                                                             + ", ".join(f"{k} → {v}" for k, v in props.items())},
                             "schedule:bp-ops", idem)
        if auto and a["state"] == "proposed":
            outbound.execute(a["id"], "schedule:bp-ops")
        n += 1
    return n


def propose_edit(page_id: str, prop: str, value: str, actor: str) -> dict:
    if prop not in notion.PROPS.values():
        raise ValueError("Not an editable property")
    card = db.one("select * from notion_cards where page_id = %s", (page_id,))
    return outbound.propose("notion.update", card["jira_key"] if card else None,
                            {"page_id": page_id, "properties": {prop: value},
                             "description": f"Notion card #{card['number'] if card else '?'}: {prop} → {value}"},
                            actor)


def propose_create(key: str, actor: str) -> dict:
    """Create a card per the blog-notion-ticket-creation rules: Name = summary, New/Upd, Status Not started."""
    t = db.one("select * from tickets where jira_key = %s", (key,))
    props = {"Name": t["summary"], "New/Upd": "Update" if t["type"] == "update" else "New",
             "Status": config.NOTION_STATUS_FOR.get(t["status"], "Not started")}
    return outbound.propose("notion.create", key, {"properties": props, "jira_url": config.ticket_url(key),
                                                   "description": f"create Notion card for {key}"}, actor,
                            outbound.idempotency_key("notion-create", key, [key], bd.local_today(), "create"))
