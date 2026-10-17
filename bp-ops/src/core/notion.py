"""Notion Articles database (00 §4). Secret NOTION_TOKEN; egress custom: api.notion.com (spec 05 §3)."""

import re

import httpx

import config
import db

API = "https://api.notion.com/v1"
VERSION = "2025-09-03"
# Editable properties (legacy Blog Pipeline Editor). VERIFY which category name is current (00 §4).
PROPS = {"name": "Name", "status": "Status", "priority": "Choose Primary", "category": "Blog Category",
         "new_upd": "New/Upd", "url1": "URL 1"}


def _client() -> httpx.Client:
    if not config.NOTION_TOKEN:
        raise RuntimeError("NOTION_TOKEN not set")
    return httpx.Client(base_url=API, timeout=60, headers={"Authorization": f"Bearer {config.NOTION_TOKEN}",
                                                           "Notion-Version": VERSION})


def _text(p: dict | None) -> str | None:
    if not p:
        return None
    t = p.get("type")
    v = p.get(t)
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in v or []) or None
    if t in ("status", "select"):
        return (v or {}).get("name")
    if t == "url":
        return v
    if t == "number":
        return v
    if t == "unique_id":
        return (v or {}).get("number")
    if t == "date":
        return (v or {}).get("start")
    if t == "formula":
        return _text({"type": v.get("type"), v.get("type"): v.get(v.get("type"))})
    return None


def parse_page(pg: dict) -> dict:
    pr = pg.get("properties") or {}
    jira_url = _text(pr.get("JIRA"))
    m = re.search(r"BP-\d+", jira_url or "")
    num = _text(pr.get("Number"))
    return {"page_id": pg["id"], "number": int(num) if num is not None else None, "name": _text(pr.get("Name")),
            "status": _text(pr.get("Status")), "priority": _text(pr.get("Choose Primary")),
            "category": _text(pr.get("Blog Category")) or _text(pr.get("Primary category")),
            "new_upd": _text(pr.get("New/Upd")), "url1": _text(pr.get("URL 1")), "jira_url": jira_url,
            "jira_key": m.group(0) if m else None, "date": (_text(pr.get("Date")) or None),
            "notion_url": pg.get("url")}


def pull() -> int:
    """Query the whole data source and upsert notion_cards."""
    n, cursor = 0, None
    with _client() as c:
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            r = c.post(f"/data_sources/{config.NOTION_DATA_SOURCE_ID}/query", json=body)
            r.raise_for_status()
            data = r.json()
            for pg in data.get("results") or []:
                card = parse_page(pg)
                if card["date"]:
                    card["date"] = card["date"][:10]
                db.execute("insert into notion_cards (page_id, number, name, status, priority, category, new_upd, url1, "
                           "jira_url, jira_key, date, notion_url, synced_at) values (%(page_id)s, %(number)s, "
                           "%(name)s, %(status)s, %(priority)s, %(category)s, %(new_upd)s, %(url1)s, %(jira_url)s, "
                           "%(jira_key)s, %(date)s, %(notion_url)s, now()) on conflict (page_id) do update set "
                           "number = excluded.number, name = excluded.name, status = excluded.status, "
                           "priority = excluded.priority, category = excluded.category, new_upd = excluded.new_upd, "
                           "url1 = excluded.url1, jira_url = excluded.jira_url, jira_key = excluded.jira_key, "
                           "date = excluded.date, notion_url = excluded.notion_url, synced_at = now()", card)
                n += 1
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
    return n


def property_value(name: str, value: str | None) -> dict:
    if name == "Name":
        return {"title": [{"text": {"content": value or ""}}]}
    if name == "Status":
        return {"status": {"name": value}}
    if name == "URL 1":
        return {"url": value or None}
    return {"rich_text": [{"text": {"content": value or ""}}]}  # VERIFY: select vs text for these properties


def run_action(a: dict) -> None:
    """Execute a proposed notion.* action. Only called from core/outbound.execute."""
    p = a["payload"]
    with _client() as c:
        if a["kind"] == "notion.update":
            props = {k: property_value(k, v) for k, v in p["properties"].items()}
            r = c.patch(f"/pages/{p['page_id']}", json={"properties": props})
        elif a["kind"] == "notion.create":
            props = {k: property_value(k, v) for k, v in p["properties"].items()}
            if p.get("jira_url"):
                props["JIRA"] = {"url": p["jira_url"]}
            r = c.post("/pages", json={"parent": {"type": "data_source_id",
                                                  "data_source_id": config.NOTION_DATA_SOURCE_ID},
                                       "properties": props})
        else:
            raise ValueError(f"Unknown notion action {a['kind']}")
        r.raise_for_status()
