"""Weekly run (§13 decay_run): detect -> aggregate -> audit -> screen -> level -> priority -> proposals.

Clients are injected so tests can run the whole pipeline offline.
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import ahrefs as ah
from .aggregate import aggregate
from .audit import Audit, audit_page, competitor_words
from .detect import detect
from .followup import note_update
from .level import Context, LevelResult, assign_level, checklist_for
from .notion import infer_category, iso_week, open_card_for
from .priority import confidence, install_intent, priority
from .screen import screen_page

log = logging.getLogger(__name__)

OPEN_STATES = ("proposed", "carded", "in_progress")
STICKY_STATES = ("carded", "in_progress", "updated")


@dataclass
class Clients:
    ahrefs: object = None
    fetcher: object = None
    jira: object = None
    notion: object = None


@dataclass
class RunResult:
    run_ids: list = field(default_factory=list)
    aborted: list = field(default_factory=list)  # (country, message)
    pages: int = 0
    proposed: int = 0


def load_gsc(path: str | None) -> dict:
    """Optional GSC cross-check (§4): CSV with url, clicks_last_28, clicks_prev_28 (spec 01 export)."""
    if not path:
        return {}
    out = {}
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                last, prev = float(row["clicks_last_28"]), float(row["clicks_prev_28"])
            except (KeyError, ValueError):
                continue
            if prev > 0:
                out[row["url"].strip()] = round((last - prev) / prev * 100, 1)
    return out


def run_week(report_date: date) -> str:
    """ISO week of the day the run happens (report date + 1), so a Tuesday re-run shares Monday's week."""
    return iso_week(report_date + timedelta(days=1))


def week_chain(store, country: str, run_id: int, run_date: date) -> list[int]:
    """Latest ok run per ISO week, newest first, with the current run at the head."""
    rows = store.query("select id, date from decay_runs where country=? and status='ok' and id < ? order by id desc",
                       [country, run_id])
    chain, weeks = [run_id], {run_week(run_date)}
    for r in rows:
        wk = run_week(date.fromisoformat(r["date"]))
        if wk in weeks:
            continue
        weeks.add(wk)
        chain.append(r["id"])
    return chain


def confirmations(store, url: str, chain: list[int]) -> int:
    n = 0
    for rid in chain:
        if rid == chain[0] or store.one("select 1 as x from decay_signals where run_id=? and url=? limit 1", [rid, url]):
            n += 1
        else:
            break
    return n


def run(cfg, store, clients: Clients, date_str: str | None = None, compare_str: str | None = None,
        no_cards: bool = False, gsc_path: str | None = None, countries: list[str] | None = None) -> RunResult:
    report_date = cfg.report_date(date_str)
    compare_date = cfg.compare_date(report_date, compare_str)
    gsc = load_gsc(gsc_path)
    result = RunResult()
    countries = countries or cfg["countries"]

    estimate = ah.estimate_units(cfg, calls=len(countries))
    for country in countries:
        run_id = store.new_run(country, report_date.isoformat(), compare_date.isoformat())
        result.run_ids.append(run_id)
        try:
            ah.guard_units(estimate, cfg["max_units_per_run"])
        except ah.UnitBudgetExceeded as exc:
            store.finish_run(run_id, "aborted", error=str(exc))
            result.aborted.append((country, str(exc)))
            continue
        try:
            _run_country(cfg, store, clients, run_id, country, report_date, compare_date, gsc, result)
        except Exception as exc:  # noqa: BLE001 - keep the error on the run row for the report
            log.exception("run %s failed", run_id)
            store.finish_run(run_id, "error", error=f"{type(exc).__name__}: {exc}")
            raise

    if cfg["auto_create"] and not no_cards and clients.notion is not None:
        from .notion import create_cards
        create_cards(cfg, store, clients.notion, dry_run=False)
    return result


def _run_country(cfg, store, clients, run_id, country, report_date, compare_date, gsc, result):
    today = cfg.today
    before = clients.ahrefs.units_usage() if hasattr(clients.ahrefs, "units_usage") else None
    d, dc = report_date.isoformat(), compare_date.isoformat()
    rows = clients.ahrefs.organic_keywords(ah.detect_params(cfg, country, d, dc))
    aio_rows = clients.ahrefs.organic_keywords(ah.aio_params(cfg, country, d, dc))
    after = clients.ahrefs.units_usage() if hasattr(clients.ahrefs, "units_usage") else None
    units = ah.units_used_between(before, after) or getattr(clients.ahrefs, "units_reported", 0) or \
        max(ah.MIN_UNITS_PER_REQUEST, len(rows) * cfg["units_per_row"]) + \
        max(ah.MIN_UNITS_PER_REQUEST, len(aio_rows) * cfg["aio_units_per_row"])

    signals, dropped = detect(cfg, rows, aio_rows)
    for s in signals:
        store.upsert("decay_signals", s.to_row(run_id), ["run_id", "keyword", "url"])
    store.commit()

    pages = aggregate(signals)
    chain = week_chain(store, country, run_id, report_date)
    seen = []
    for url, page in sorted(pages.items(), key=lambda kv: -kv[1].traffic_lost):
        _process_page(cfg, store, clients, run_id, country, page, chain, gsc, today)
        seen.append(url)
    store.commit()

    result.pages += len(seen)
    result.proposed += propose(cfg, store, seen, today)
    store.execute("update decay_runs set rows_returned=?, units_used=?, status='ok', error=? where id=?",
                  [len(rows), units, f"filtered: {dropped}" if dropped else None, run_id])
    store.commit()


def _process_page(cfg, store, clients, run_id, country, page, chain, gsc, today):
    summary = page.summary()
    item = store.item(page.url) or {}
    n_conf = confirmations(store, page.url, chain)
    severe = page.lost_entirely_count > 0 or page.traffic_lost >= cfg["severe_page_traffic_lost"]
    confirmed = n_conf >= cfg["confirm_runs"] or severe
    notes = []

    # Audit (§6)
    audit = audit_page(clients.fetcher, page.url, cfg, today) if clients.fetcher else Audit(url=page.url, error="no fetcher")
    if audit.error:
        notes.append(f"audit: {audit.error}")
    screen = screen_page(cfg, store, page.url, audit.title, audit.h1, page.main_keyword, page.slug)
    summary["cluster"] = infer_category(page.main_keyword, page.slug) or page.core_topic

    open_ticket = recent_ticket = recent_days = None
    if clients.jira is not None:
        try:
            o, r = clients.jira.check(page.url, page.slug, today, cfg["jira_published_status"], cfg["recent_ticket_days"])
            open_ticket = o.key if o else None
            if r:
                recent_ticket, recent_days = r.key, r.published_days_ago
        except Exception as exc:  # noqa: BLE001
            notes.append(f"jira check failed: {exc}")
    else:
        notes.append("jira check skipped (no credentials)")
    open_card = None
    if clients.notion is not None:
        try:
            card = open_card_for(clients.notion, page.url)
            open_card = card.get("url") if card else None
        except Exception as exc:  # noqa: BLE001
            notes.append(f"notion check failed: {exc}")
    else:
        notes.append("notion check skipped (no token)")
    if open_card is None and item.get("notion_url") and item.get("state") in ("carded", "in_progress"):
        open_card = item["notion_url"]  # our own card, when Notion is not reachable

    ctx = Context(page=summary, audit=audit, screen=screen, today=today, confirmed=confirmed,
                  open_ticket=open_ticket, open_card=open_card, recent_ticket=recent_ticket,
                  recent_ticket_days_ago=recent_days, cluster=summary["cluster"])
    res = assign_level(cfg, ctx)
    if res.rule >= 8 and audit.median_competitor_words is None:
        audit.median_competitor_words, audit.competitor_check = competitor_words(
            clients.fetcher, clients.ahrefs, page.main_keyword, country, cfg) if clients.fetcher else (None, "skipped")
        if audit.median_competitor_words:
            res = assign_level(cfg, ctx)
    elif res.rule < 8:
        audit.competitor_check = "not needed"

    # §11 escalation: a page that did not recover is re-proposed one level up, even inside the 42-day window.
    not_recovered = store.one("select 1 as x from decay_followups where url=? and label=? and outcome='not_recovered'",
                              [page.url, f"+{max(cfg['followup_days'])}d"])
    if (not_recovered and item.get("state") not in STICKY_STATES and res.level == "L0" and res.tag == "recent"
            and item.get("level") in ("L1", "L2", "L3")):
        lvl = item["level"]
        res = LevelResult(lvl, 12, "escalated",
                          f"Not recovered 4 weeks after the update; escalated to {lvl}. {res.why.split('. ')[0]}.",
                          checklist_for(cfg, lvl, summary, audit, list(audit.claim_flags)))

    gsc_change = gsc.get(page.url)
    conf, gsc_note = confidence(cfg, confirmed, gsc_change)
    if gsc_note:
        notes.append(gsc_note)
    intent = install_intent(page.main_keyword, page.main.is_commercial, page.main.is_transactional)
    effective = item.get("level_override") or res.level
    prio = priority(cfg, page.traffic_lost, intent, bool(page.core_topic), conf, effective)

    prev_state = item.get("state")
    if prev_state == "excluded":
        state = "excluded"
    elif res.level == "NOSEO":
        state = "noseo"
    elif prev_state in STICKY_STATES:
        state = prev_state
    elif not confirmed:
        state = "watch"
    else:
        state = "confirmed"

    # §11: updated_on changed on a page we carded -> schedule follow-ups.
    state, updated_on_new = note_update(cfg, store, page.url, item, audit.updated_on, state, today)

    store.save_item({
        "url": page.url, "slug": page.slug, "first_seen_run": item.get("first_seen_run") or run_id,
        "last_seen_run": run_id, "confirmations": n_conf, "state": state, "level": res.level,
        "level_override": item.get("level_override"), "override_reason": item.get("override_reason"),
        "why": res.why, "checklist": res.checklist, "priority": prio, "main_keyword": page.main_keyword,
        "lost_top3_count": page.lost_top3_count, "traffic_lost": page.traffic_lost, "worst_now": page.worst_now,
        "notion_url": item.get("notion_url") or open_card, "jira_key": open_ticket or recent_ticket or item.get("jira_key"),
        "excluded_reason": item.get("excluded_reason"), "updated_on_new": updated_on_new,
    })
    store.upsert("page_audits", audit.to_row(run_id, screen), ["url", "run_id"])
    flags = []
    if page.aio_appeared or page.aio_citation_lost:
        flags.append("AIO")
    if page.swapped_to:
        flags.append("cannibalization")
    if audit.claim_flags or res.tag == "claims":
        flags.append("claims")
    if not confirmed:
        flags.append("watch")
    store.upsert("decay_run_items", {"run_id": run_id, "url": page.url, "payload": {
        "page": summary, "audit": audit.to_dict(), "screen": {"verdict": screen.verdict,
                                                              "matches": [m.to_dict() for m in screen.matches]},
        "level": res.level, "rule": res.rule, "tag": res.tag, "why": res.why, "checklist": res.checklist,
        "confirmed": confirmed, "confirmations": n_conf, "intent": intent, "confidence": conf, "gsc_change": gsc_change,
        "open_ticket": open_ticket, "recent_ticket": recent_ticket, "open_card": open_card, "priority": prio,
        "flags": flags, "notes": notes, "state": state,
    }}, ["run_id", "url"])


def propose(cfg, store, urls: list[str], today: date) -> int:
    """§8: top N confirmed L1–L3 pages by priority become 'proposed'; the rest stay on the board as backlog."""
    if not urls:
        return 0
    marks = ",".join("?" for _ in urls)
    rows = store.query(f"select * from decay_items where url in ({marks}) and state in ('confirmed','proposed')", urls)
    recent_cut = (today - timedelta(days=cfg["resuggest_after_days"])).isoformat()
    candidates = []
    for r in rows:
        lvl = r.get("level_override") or r["level"]
        sugg = store.one("select first_suggested from decay_suggestions where url=?", [r["url"]])
        escalated = store.one("select 1 as x from decay_followups where url=? and label=? and outcome='not_recovered'",
                              [r["url"], f"+{max(cfg['followup_days'])}d"])
        already = sugg is not None and (sugg["first_suggested"] or "") >= recent_cut and not escalated
        if lvl in ("L1", "L2", "L3") and not already:
            candidates.append(r)
        elif r["state"] == "proposed":
            store.execute("update decay_items set state='confirmed' where url=?", [r["url"]])
    candidates.sort(key=lambda r: -(r["priority"] or 0))
    cap = cfg["weekly_card_cap"]
    for i, r in enumerate(candidates):
        store.execute("update decay_items set state=? where url=?", ["proposed" if i < cap else "confirmed", r["url"]])
    store.commit()
    return min(len(candidates), cap)
