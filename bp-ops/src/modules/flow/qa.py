"""Publishing QA (spec 04 §3, old "group D"): Published in Jira, but the live page shows no update around go-live."""

import json
import re
from datetime import date, datetime, timedelta

import httpx

import config
import db

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}


def parse_page(html: str) -> dict:
    """'Updated on' date (JSON-LD dateModified first, then the visible text) and the H1."""
    updated = None
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in (data.get("@graph") or [data]) if isinstance(data, dict) else data:
            if isinstance(node, dict) and node.get("dateModified"):
                updated = date.fromisoformat(str(node["dateModified"])[:10])
                break
        if updated:
            break
    if not updated:
        m = re.search(r"Updated\s+on\s*:?\s*(?:<[^>]+>\s*)*([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", html, re.I)
        if m and m.group(1).lower() in MONTHS:
            updated = date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
    h1_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", h1.group(1))).strip() if h1 else None
    return {"updated_on": updated, "h1": h1_text}


def is_mismatch(updated_on: date | None, published_at: datetime, http_status: int) -> bool:
    """The page's 'Updated on' is more than 3 days older than the Jira publish date, or the page doesn't load."""
    if http_status != 200:
        return True
    if updated_on is None:
        return False  # can't tell; shown with a note instead
    return updated_on < (published_at.astimezone(config.TZ).date() - timedelta(days=3))


def check(keys: list[str] | None = None, client: httpx.Client | None = None) -> int:
    """Check tickets Published more than 3 days ago (and within 45 days) that have a live link."""
    now = datetime.now(config.TZ)
    if keys:
        rows = db.query("select jira_key, live_url, entered_published_at from tickets where jira_key = any(%s)",
                        (keys,))
    else:
        rows = db.query("select jira_key, live_url, entered_published_at from tickets where status = 'Published' "
                        "and entered_published_at between %s and %s",
                        (now - timedelta(days=45), now - timedelta(days=3)))
    client = client or httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "bp-ops qa-check"})
    n = 0
    for r in rows:
        if not r["live_url"] or not r["entered_published_at"]:
            db.execute("insert into qa_checks (jira_key, checked_at, mismatch, note) values (%s, now(), false, %s) "
                       "on conflict (jira_key) do update set checked_at = now(), mismatch = false, note = excluded.note",
                       (r["jira_key"], "no live link on the ticket"))
            continue
        try:
            resp = client.get(r["live_url"])
            status, page = resp.status_code, parse_page(resp.text if resp.status_code == 200 else "")
        except httpx.HTTPError as e:
            status, page = 0, {"updated_on": None, "h1": None}
            note = f"fetch failed: {e}"
        else:
            note = None if page["updated_on"] else "no 'Updated on' date found"
        mismatch = is_mismatch(page["updated_on"], r["entered_published_at"], status)
        db.execute("insert into qa_checks (jira_key, checked_at, live_updated_on, live_h1, http_status, mismatch, note) "
                   "values (%s, now(), %s, %s, %s, %s, %s) on conflict (jira_key) do update set "
                   "checked_at = now(), live_updated_on = excluded.live_updated_on, live_h1 = excluded.live_h1, "
                   "http_status = excluded.http_status, mismatch = excluded.mismatch, note = excluded.note",
                   (r["jira_key"], page["updated_on"], page["h1"], status, mismatch, note))
        db.execute("insert into page_snapshots (url, updated_on, h1, http_status) values (%s, %s, %s, %s) "
                   "on conflict do nothing", (r["live_url"], page["updated_on"], page["h1"], status))
        n += 1
    return n
