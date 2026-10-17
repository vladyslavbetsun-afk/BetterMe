"""Import the artifact-database exports (spec 05 §7, Step B) and the October tracker data.

Usage (after the first deploy has created the schema; DATABASE_URL must point at the app's database):

    python scripts/import_exports.py import/                       # files <artifact>__<collection>.json
    python scripts/import_exports.py --october legacy/october-updates-tracker/october-updates-weekly.json

Safe to re-run: every insert is an upsert or ON CONFLICT DO NOTHING. Rows that can't be matched are written to
import_issues and listed on /admin/import-report. Exports are untrusted data: values are only ever bound as SQL
parameters, never interpolated.
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import config  # noqa: E402
import db  # noqa: E402
from core import outbound  # noqa: E402

ARTIFACTS = {"review": ("review", "bp-review-flow", "DhWg"), "publishing": ("publishing", "batches", "CKoa"),
             "slipped": ("slipped", "8ZdW"), "spend": ("spend", "WhNY")}


def issue(source: str, ref: str | None, problem: str, detail: dict | None = None) -> None:
    db.execute("insert into import_issues (source, ref, problem, detail) values (%s, %s, %s, %s)",
               (source, ref, problem, db.jsonb(detail or {})))


def docs(path: Path) -> list[tuple[str, dict]]:
    """[(doc_id, data)] from whatever shape ArtifactData list produced."""
    raw = json.loads(path.read_text())
    if isinstance(raw, dict):
        for k in ("documents", "docs", "items", "results", "data"):
            if isinstance(raw.get(k), list):
                raw = raw[k]
                break
        else:
            return [(k, v) for k, v in raw.items() if isinstance(v, dict)]
    out = []
    for d in raw:
        if not isinstance(d, dict):
            continue
        did = d.get("doc_id") or d.get("id") or d.get("docId") or d.get("key")
        data = d.get("data") if isinstance(d.get("data"), dict) else {k: v for k, v in d.items()
                                                                       if k not in ("doc_id", "id", "docId")}
        out.append((str(did) if did is not None else None, data))
    return out


def ts(v) -> datetime | None:
    """epoch ms, epoch s or ISO string → aware datetime."""
    if v in (None, ""):
        return None
    if isinstance(v, int | float):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, config.TZ)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=config.TZ)
    except ValueError:
        return None


def find(folder: Path, artifact: str, collection: str) -> Path | None:
    hints = ARTIFACTS[artifact]
    for f in sorted(folder.glob("*.json")):
        name = f.stem.lower()
        if "__" not in name:
            continue
        art, coll = name.split("__", 1)
        if coll.lower() == collection.lower() and any(h.lower() in art for h in hints):
            return f
    return None


# --- BP Review Flow ------------------------------------------------------------------------------------

def import_review(folder: Path) -> dict:
    n = {}
    f = find(folder, "review", "settings")
    if f:
        for did, d in docs(f):
            if did == "main":
                db.set_setting("review.windowDays", d.get("windowDays", 14))
                db.set_setting("review.noteMode", d.get("noteMode", "internal"))
                db.set_setting("review.autoSlackSince", d.get("autoSlackSince"))
                db.set_setting("review_automation_enabled", False)  # always off at first (spec 05 §7)
                n["settings"] = 1
    f = find(folder, "review", "exclusions")
    if f:
        n["exclusions"] = 0
        for did, d in docs(f):
            db.execute("insert into exclusions (jira_key, title, at, by) values (%s, %s, coalesce(%s, now()), 'import') "
                       "on conflict do nothing", (did, d.get("title"), ts(d.get("at"))))
            n["exclusions"] += 1
    f = find(folder, "review", "overrides")
    if f:
        n["overrides"] = 0
        for did, d in docs(f):
            cat = d.get("category") if d.get("category") in ("fitness", "nutrition") else None
            db.execute("insert into overrides (jira_key, category, expert_id, auto_slack) values (%s, %s, %s, %s) "
                       "on conflict (jira_key) do update set category = excluded.category, expert_id = excluded.expert_id, "
                       "auto_slack = excluded.auto_slack", (did, cat, d.get("expertId"), d.get("autoSlack")))
            n["overrides"] += 1
    f = find(folder, "review", "expertAsks")
    if f:
        n["expert_asks"] = 0
        for did, d in docs(f):
            at = ts(d.get("at"))
            if at:
                db.execute("insert into expert_asks (jira_key, at) values (%s, %s) on conflict (jira_key) do update "
                           "set at = greatest(expert_asks.at, excluded.at)", (did, at))
                n["expert_asks"] += 1
    f = find(folder, "review", "slackLinks")
    if f:
        n["slack_links"] = 0
        for did, d in docs(f):
            sid = d.get("slackId")
            if not sid:
                continue
            if db.execute("update people set slack_id = coalesce(slack_id, %s) where jira_account_id = %s", (sid, did)):
                n["slack_links"] += 1
            else:
                issue("review/slackLinks", did, "no person with this Jira accountId", d)
    f = find(folder, "review", "slackSent")
    if f:
        n["slack_sent"] = 0
        for wid, d in docs(f):
            groups: dict[int, list[str]] = {}
            for key, at in (d.get("tickets") or {}).items():
                groups.setdefault(int(at), []).append(key)
            if not db.scalar("select 1 from people where jira_account_id = %s", (wid,)):
                issue("review/slackSent", wid, "no person with this Jira accountId", {"name": d.get("name")})
            for at_ms, keys in groups.items():
                at = ts(at_ms)
                idem = outbound.idempotency_key("nudge", wid, keys, at.date(), "writer_followup")
                db.execute("insert into outbound_messages (channel, recipient, template, body, ticket_keys, "
                           "idempotency_key, state, created_at, created_by, sent_at) values ('slack_dm', %s, "
                           "'writer_followup', %s, %s, %s, 'sent', %s, 'import', %s) on conflict do nothing",
                           (wid, "(imported from BP Review Flow; text not kept)", sorted(keys), idem, at, at))
                n["slack_sent"] += 1
    n["review_log"] = import_log(folder, "review", "log")
    return n


def import_log(folder: Path, artifact: str, collection: str) -> int:
    f = find(folder, artifact, collection)
    if not f:
        return 0
    cutoff = datetime.now(config.TZ) - timedelta(days=90)
    k = 0
    for did, d in docs(f):
        at = ts(d.get("at"))
        if not at or at < cutoff:
            continue
        db.execute("insert into audit_log (at, actor, action, target, detail) values (%s, 'legacy', %s, %s, %s)",
                   (at, f"legacy.{artifact}.{d.get('kind', 'log')}", d.get("key"), db.jsonb({"text": d.get("text"),
                                                                                             "doc": did})))
        k += 1
    return k


# --- BP Publishing Batches ------------------------------------------------------------------------------

def import_publishing(folder: Path) -> dict:
    n = {"batches": 0, "batch_items": 0}
    f = find(folder, "publishing", "batches")
    if f:
        for did, d in docs(f):
            bid = d.get("id") or did
            keys = d.get("keys") or []
            db.execute("insert into batches (id, n, created_at, sent_at, post_at, archived) values "
                       "(%s, %s, coalesce(%s, now()), %s, %s, %s) on conflict (id) do nothing",
                       (bid, d.get("n") or 0, ts(d.get("createdAt")), ts(d.get("sentAt")), ts(d.get("postAt")),
                        bool(d.get("archived"))))
            n["batches"] += 1
            for i, k in enumerate(keys):
                db.execute("insert into batch_items (batch_id, jira_key, position) values (%s, %s, %s) "
                           "on conflict do nothing", (bid, k, i))
                n["batch_items"] += 1
    n["publishing_log"] = import_log(folder, "publishing", "log")
    return n


# --- Slipped Pages Tracker → spec 01 tables --------------------------------------------------------------

def article_url(slug: str, d: dict) -> str:
    return d.get("url") or f"https://betterme.world/articles/{slug.strip('/')}/"


def import_slipped(folder: Path) -> dict:
    n = {"articles": 0, "events": 0}
    f = find(folder, "slipped", "pages")
    if f:
        for slug, d in docs(f):
            slug = slug or d.get("slug")
            if not slug:
                issue("slipped/pages", None, "page without slug", d)
                continue
            db.execute("insert into articles (url, slug, title, cohort, slipped_level, main_keyword, main_keyword_volume) "
                       "values (%s, %s, %s, 'slipped', %s, %s, %s) on conflict (url) do update set "
                       "slipped_level = excluded.slipped_level, title = coalesce(articles.title, excluded.title)",
                       (article_url(slug, d), slug, d.get("title"), d.get("level"),
                        d.get("keyword") or d.get("mainKeyword"), d.get("volume")))
            n["articles"] += 1
    for coll, kind in (("progress", "progress"), ("checks", "position_check")):
        f = find(folder, "slipped", coll)
        if not f:
            continue
        for slug, d in docs(f):
            url = db.scalar("select url from articles where slug = %s", (slug,)) or article_url(slug or "", d)
            entries = d.get("history") if isinstance(d.get("history"), list) else [d]
            for e in entries:
                at = ts(e.get("at") or e.get("updatedAt") or e.get("date") or e.get("checkedAt")) or datetime.now(config.TZ)
                db.execute("insert into article_events (url, kind, at, payload) values (%s, %s, %s, %s) "
                           "on conflict do nothing", (url, kind, at, db.jsonb(e)))
                n["events"] += 1
    f = find(folder, "slipped", "meta")
    if f:
        for did, d in docs(f):
            db.set_setting(f"slipped.meta.{did}", d)
    return n


# --- Blog Spend Dashboard -------------------------------------------------------------------------------

def import_spend(folder: Path, month: date = date(2026, 10, 1)) -> dict:
    n = {"spend_lines": 0}
    f = find(folder, "spend", "spend")
    if not f:
        return n
    db.execute("insert into spend_months (month, status) values (%s, 'open') on conflict do nothing", (month,))
    for pid, d in docs(f):
        amt = d.get("amount")
        if amt in (None, "", 0, "0"):
            continue
        if pid in ("colette", "polina"):  # already fixed monthly rates in the roster seed (spec 05 §7)
            issue("spend/spend", pid, "skipped: fixed monthly rate covers it", d)
            continue
        person = {"samuel": "nderitu", "anosha": "anoshia", "maria_rubiolo": "rubiolo", "eva_deangelis": "eva",
                  "maria_corrarello": "corrarello", "amanda_pasko": "amanda"}.get(pid, pid)
        role = db.scalar("select role from people where id = %s", (person,))
        if role is None and pid != "ecom":
            issue("spend/spend", pid, "no person with this id; imported without a person", d)
        cat = {"writer": "writing", "expert": "review", "proofreader": "proofreading", "designer": "design",
               "researcher": "research"}.get(role, "other")
        note = f"imported from Blog Spend Dashboard ({pid})" + (f": {d['note']}" if d.get("note") else "")
        if db.scalar("select 1 from spend_lines where month = %s and source = 'manual' and note = %s", (month, note)):
            continue  # already imported
        db.execute("insert into spend_lines (month, person_id, category, source, amount, amount_max, note) "
                   "values (%s, %s, %s, 'manual', %s, %s, %s)", (month, person if role else None, cat, amt, amt, note))
        n["spend_lines"] += 1
    return n


# --- October Updates Tracker ------------------------------------------------------------------------------

def import_october(path: Path) -> dict:
    rows = json.loads(path.read_text())
    n = 0
    for r in rows:
        url, week = r["url"], date.fromisoformat(r["week"])
        db.execute("insert into articles (url, slug, cohort) values (%s, %s, 'update') on conflict (url) do update "
                   "set cohort = case when articles.cohort = 'slipped' then articles.cohort else 'update' end",
                   (url, r.get("slug")))
        db.execute("insert into ahrefs_page_weekly (url, week, traffic, keywords, top3, top4_10) values (%s,%s,%s,%s,%s,%s) "
                   "on conflict (url, week) do update set traffic = excluded.traffic, keywords = excluded.keywords, "
                   "top3 = excluded.top3, top4_10 = excluded.top4_10",
                   (url, week, r.get("traffic"), r.get("keywords"), r.get("top3"), r.get("top4_10")))
        db.execute("insert into ai_citations_weekly (target, mode, week, ai_all, aio, ai_mode, chatgpt, perplexity, gemini, "
                   "copilot) values (%s, 'exact', %s, %s, %s, %s, %s, %s, %s, %s) on conflict (target, mode, week) do update "
                   "set ai_all = excluded.ai_all, aio = excluded.aio, ai_mode = excluded.ai_mode, chatgpt = excluded.chatgpt, "
                   "perplexity = excluded.perplexity, gemini = excluded.gemini, copilot = excluded.copilot",
                   (url, week, r.get("ai_all"), r.get("aio"), r.get("ai_mode"), r.get("chatgpt"), r.get("perplexity"),
                    r.get("gemini"), r.get("copilot")))
        if r.get("updated_on"):
            db.execute("insert into page_snapshots (url, checked_at, updated_on) values (%s, %s, %s) on conflict do nothing",
                       (url, datetime.combine(week, datetime.min.time(), tzinfo=config.TZ), r["updated_on"]))
        n += 1
    return {"october_rows": n}


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder", nargs="?", help="folder with <artifact>__<collection>.json exports")
    ap.add_argument("--october", help="october-updates-weekly.json")
    a = ap.parse_args(argv)
    db.migrate()
    out = {}
    if a.folder:
        folder = Path(a.folder)
        out.update(import_review(folder))
        out.update(import_publishing(folder))
        out.update(import_slipped(folder))
        out.update(import_spend(folder))
    if a.october:
        out.update(import_october(Path(a.october)))
    out["unmatched_rows"] = db.scalar("select count(*) from import_issues")
    for k, v in out.items():
        print(f"{k:>16}: {v}")
    print("Details: /admin/import-report")
    return out


if __name__ == "__main__":
    main()
