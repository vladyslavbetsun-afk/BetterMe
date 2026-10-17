"""§11 follow-up loop: detect the update, check at +14 / +28 days, mark recovered / partial / escalate."""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from .audit import audit_page
from .level import escalate
from .storage import now_iso

log = logging.getLogger(__name__)

WATCHED_STATES = ("proposed", "carded", "in_progress")


def labels(cfg) -> list[tuple[str, int]]:
    return [(f"+{d}d", d) for d in cfg["followup_days"]]


def final_label(cfg) -> str:
    return f"+{max(cfg['followup_days'])}d"


def note_update(cfg, store, url: str, item: dict, new_updated_on: str | None, state: str, today: date):
    """If `updated_on` moved forward on a page with an open item, schedule the checks. Returns (state, updated_on_new)."""
    current = item.get("updated_on_new")
    if not item or item.get("state") not in WATCHED_STATES or not new_updated_on:
        return state, current
    prev = store.latest_audit(url)
    baseline = (prev or {}).get("updated_on")
    if not baseline or new_updated_on <= baseline or new_updated_on == current:
        return state, current
    start = date.fromisoformat(new_updated_on)
    for label, days in labels(cfg):
        store.upsert("decay_followups", {"url": url, "label": label, "due_date": (start + timedelta(days=days)).isoformat(),
                                         "checked_at": None, "results": None, "outcome": None}, ["url", "label"])
    store.commit()
    log.info("%s updated on %s (was %s): follow-ups scheduled", url, new_updated_on, baseline)
    return "updated", new_updated_on


def scan_updates(cfg, store, fetcher, today: date) -> list[str]:
    """Re-fetch open items that may have dropped out of the weekly signals (spec 01 `check_live_pages` does the same)."""
    changed = []
    for item in store.query("select * from decay_items where state in ('proposed','carded','in_progress')"):
        a = audit_page(fetcher, item["url"], cfg, today)
        state, upd = note_update(cfg, store, item["url"], item, a.updated_on, item["state"], today)
        if state != item["state"]:
            store.execute("update decay_items set state=?, updated_on_new=? where url=?", [state, upd, item["url"]])
            store.commit()
            changed.append(item["url"])
    return changed


def latest_payload(store, url: str) -> dict | None:
    row = store.one("select payload from decay_run_items where url=? order by run_id desc limit 1", [url])
    return row["payload"] if row else None


def evaluate(cfg, base_keywords: list[dict], main_keyword: str, results: dict) -> str:
    """recovered: main keyword back in the top 3, or >= 70% of the lost traffic back. partial: any improvement."""
    lost = sum(max((k["traffic_prev"] or 0) - (k["traffic_now"] or 0), 0) for k in base_keywords)
    base_now = sum(k["traffic_now"] or 0 for k in base_keywords)
    now = sum((results.get(k["kw"]) or {}).get("traffic") or 0 for k in base_keywords)
    regained = now - base_now
    main_pos = (results.get(main_keyword) or {}).get("position")
    if (main_pos is not None and main_pos <= cfg["recovered_position"]) or \
            (lost > 0 and regained / lost * 100 >= cfg["recovered_traffic_pct"]):
        return "recovered"
    improved = regained > 0
    for k in base_keywords:
        p = (results.get(k["kw"]) or {}).get("position")
        if p is not None and (k["now"] is None or p < k["now"]):
            improved = True
    return "partial" if improved else "not_recovered"


def page_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"([0-9a-f]{32})(?:\?|$)", url.replace("-", ""))
    return m.group(1) if m else None


def run_followups(cfg, store, ahrefs, notion=None, fetcher=None, today: date | None = None) -> list[dict]:
    today = today or cfg.today
    if fetcher is not None:
        scan_updates(cfg, store, fetcher, today)
    due = store.query("select * from decay_followups where due_date <= ? and checked_at is null order by due_date",
                      [today.isoformat()])
    country = cfg["countries"][0]
    done = []
    for f in due:
        item = store.item(f["url"])
        payload = latest_payload(store, f["url"])
        if not item or not payload:
            continue
        base = payload["page"]["lost_keywords"]
        kws = [k["kw"] for k in base]
        rows = ahrefs.url_keywords(f["url"], country, (today - timedelta(days=1)).isoformat(), kws)
        results = {r["keyword"]: {"position": r.get("best_position"), "traffic": r.get("sum_traffic") or 0,
                                  "aio": "ai_overview" in (r.get("serp_features") or [])}
                   for r in rows}
        outcome = evaluate(cfg, base, item["main_keyword"], results)
        store.execute("update decay_followups set checked_at=?, results=?, outcome=? where url=? and label=?",
                      [now_iso(), results, outcome, f["url"], f["label"]])
        msg = f"Decay radar follow-up {f['label']} ({today.isoformat()}): {outcome.replace('_', ' ')}."
        if f["label"] == final_label(cfg):
            if outcome == "not_recovered":
                card = store.one("select payload from decay_cards where url=? and notion_url is not null "
                                 "order by created_at desc limit 1", [f["url"]])
                carded_level = ((card or {}).get("payload") or {}).get("level")
                new_level = escalate(carded_level or item.get("level_override") or item["level"])
                msg += f" Escalated to {new_level}; re-proposed next week."
                store.execute("update decay_items set state='not_recovered', level=?, level_override=null where url=?",
                              [new_level, f["url"]])
            else:
                store.execute("update decay_items set state=? where url=?", [outcome, f["url"]])
        store.commit()
        pid = page_id_from_url(item.get("notion_url"))
        if notion is not None and pid:
            try:
                notion.comment(pid, msg)
            except Exception as exc:  # noqa: BLE001
                log.warning("Notion comment failed for %s: %s", f["url"], exc)
        done.append({"url": f["url"], "label": f["label"], "outcome": outcome, "message": msg})
    return done
