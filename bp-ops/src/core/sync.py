"""Jira → Postgres mirror (spec 05 §5). Every screen reads these tables; page loads never call Jira."""

from datetime import datetime, timedelta

import config
import db
from core import jira, rules
from core.jira import account_id, account_ids, adf_parse, parse_time

DEFAULT_FULL_SINCE = "2026-06-01"


def _live_url(comments: list[dict]) -> str | None:
    """Yuliia's latest betterme.world link, else the latest other non-Google link she posted (00 §6.5)."""
    lives = [(c["created_at"], u) for c in comments if c["author_account_id"] == config.YULIIA_K_ACCOUNT_ID
             for u in c["links"] if "google.com" not in u and "atlassian.net" not in u]
    lives.sort()
    site = [u for _, u in lives if rules.LIVE_RE.match(u)]
    return site[-1] if site else (lives[-1][1] if lives else None)


def _doc_url(comments: list[dict]) -> str | None:
    docs = sorted((c["created_at"], u) for c in comments for u in c["links"] if rules.DOC_RE.match(u))
    return docs[-1][1] if docs else None


def normalize(issue: dict, histories: list[dict]) -> dict:
    f = issue.get("fields") or {}
    key = issue["key"]
    comments = []
    for c in ((f.get("comment") or {}).get("comments") or []):
        text, links, mentions = adf_parse(c.get("body"))
        author = c.get("author") or {}
        comments.append({"id": str(c["id"]), "jira_key": key, "author_account_id": author.get("accountId"),
                         "author_name": author.get("displayName"), "created_at": parse_time(c.get("created")),
                         "body_md": text, "links": links, "mentions": mentions})
    transitions, changes = [], []
    for h in histories:
        at = parse_time(h.get("created"))
        by = (h.get("author") or {}).get("accountId")
        for it in h.get("items") or []:
            fid = it.get("fieldId") or it.get("field")
            if fid == "status":
                transitions.append({"jira_key": key, "at": at, "from_status": it.get("fromString"),
                                    "to_status": it.get("toString"), "by_account_id": by})
            elif fid in config.PEOPLE_FIELDS:
                changes.append({"jira_key": key, "at": at, "field_id": fid,
                                "from_value": it.get("from") or it.get("fromString"),
                                "to_value": it.get("to") or it.get("toString")})
    summary = f.get("summary") or ""
    words = rules.word_count(summary)
    last_into = {}
    for t in sorted(transitions, key=lambda t: t["at"]):
        last_into[t["to_status"]] = t["at"]
    ticket = {
        "jira_key": key, "key_num": int(key.split("-")[1]) if "-" in key else None, "summary": summary,
        "status": (f.get("status") or {}).get("name"), "issue_type": (f.get("issuetype") or {}).get("name"),
        "type": "update" if rules.is_update(summary) else "new",
        "created_at": parse_time(f.get("created")), "updated_at": parse_time(f.get("updated")),
        "author_id": account_id(f.get(config.F_AUTHOR)), "expert_id": account_id(f.get(config.F_EXPERT)),
        "proofreader_id": account_id(f.get(config.F_PROOFREADER)),
        "managers": account_ids(f.get(config.F_MANAGERS)), "participants": account_ids(f.get(config.F_PARTICIPANTS)),
        "word_min": words[0] if words else None, "word_max": words[1] if words else None,
        "category_detected": rules.detect_category(summary),
        "doc_url": _doc_url(comments), "live_url": _live_url(comments),
        "entered_ready_at": last_into.get("Ready"), "entered_published_at": last_into.get("Published"),
        # keep the raw fields (minus comments) for debugging; comments live in their own table
        "raw": {k: v for k, v in f.items() if k != "comment"},
    }
    return {"ticket": ticket, "comments": comments, "transitions": transitions, "changes": changes}


TICKET_COLS = ["jira_key", "key_num", "summary", "status", "issue_type", "type", "created_at", "updated_at",
               "author_id", "expert_id", "proofreader_id", "managers", "participants", "word_min", "word_max",
               "category_detected", "doc_url", "live_url", "entered_ready_at", "entered_published_at", "raw"]


def store(n: dict, c) -> None:
    t = dict(n["ticket"])
    t["raw"] = db.jsonb(t["raw"])
    cols = ", ".join(TICKET_COLS)
    vals = ", ".join(f"%({k})s" for k in TICKET_COLS)
    upd = ", ".join(f"{k} = excluded.{k}" for k in TICKET_COLS[1:])
    c.execute(f"insert into tickets ({cols}, synced_at) values ({vals}, now()) "  # nosec B608
              f"on conflict (jira_key) do update set {upd}, synced_at = now()", t)
    key = t["jira_key"]
    ids = [x["id"] for x in n["comments"]]
    c.execute("delete from comments where jira_key = %s and not (id = any(%s))", (key, ids))
    for cm in n["comments"]:
        c.execute("insert into comments (id, jira_key, author_account_id, author_name, created_at, body_md, links, "
                  "mentions) values (%(id)s, %(jira_key)s, %(author_account_id)s, %(author_name)s, %(created_at)s, "
                  "%(body_md)s, %(links)s, %(mentions)s) on conflict (id) do update set body_md = excluded.body_md, "
                  "links = excluded.links, mentions = excluded.mentions, author_name = excluded.author_name", cm)
    for tr in n["transitions"]:
        c.execute("insert into status_transitions (jira_key, at, from_status, to_status, by_account_id) "
                  "values (%(jira_key)s, %(at)s, %(from_status)s, %(to_status)s, %(by_account_id)s) "
                  "on conflict do nothing", tr)
    for ch in n["changes"]:
        c.execute("insert into field_changes (jira_key, at, field_id, from_value, to_value) "
                  "values (%(jira_key)s, %(at)s, %(field_id)s, %(from_value)s, %(to_value)s) on conflict do nothing",
                  ch)


def fetch_and_store(client: jira.JiraClient, jql: str) -> list[str]:
    issues = client.search(jql, config.SYNC_FIELDS, expand="changelog")
    keys = []
    for issue in issues:
        cl = issue.get("changelog") or {}
        histories = cl.get("histories") or []
        if cl.get("total", 0) > len(histories):
            histories = client.changelog(issue["key"])
        n = normalize(issue, histories)
        with db.conn() as c:
            store(n, c)
        keys.append(issue["key"])
    return keys


def _last_ok(job: str) -> datetime | None:
    return db.scalar("select max(started_at) from job_runs where job = %s and status = 'ok'", (job,))


def sync_incremental(client: jira.JiraClient | None = None) -> int:
    """`updated >= -Nm` where N covers the time since the last good run plus 5 minutes of overlap."""
    from modules.flow import metrics

    client = client or jira.JiraClient()
    last = _last_ok("sync_jira_incremental") or _last_ok("sync_jira_full")
    if last is None:
        return sync_full(client)
    minutes = int((datetime.now(last.tzinfo) - last) / timedelta(minutes=1)) + 5
    keys = fetch_and_store(client, f"project = {config.PROJECT} AND updated >= -{minutes}m")
    metrics.rebuild(keys)
    return len(keys)


def sync_full(client: jira.JiraClient | None = None) -> int:
    from modules.flow import metrics

    client = client or jira.JiraClient()
    since = db.get_setting("sync.full_since", DEFAULT_FULL_SINCE)
    keys = fetch_and_store(client, f'project = {config.PROJECT} AND (status != Published OR updated >= "{since}") '
                                   "ORDER BY key DESC")
    metrics.rebuild(None)
    return len(keys)
