"""Load (spec 05 §8.4): who has which tickets, per role. Ticket-level ages and flags only.

Not ported on purpose (Legal gate, spec 05 §4): per-person writing-time averages, monthly averages, rankings.
"""

from datetime import datetime

import config
import db
from core import business_days as bd
from core import people
from modules.review import service as review
from modules.spend import compute

ROLES = [("writer", "Writers", "author_id", ["Text", "Review", "Proofreading"]),
         ("expert", "Experts", "expert_id", ["Review"]),
         ("proofreader", "Proofreading", "proofreader_id", ["Proofreading"])]


def view(with_money: bool) -> dict:
    roster = people.load()
    now = datetime.now(config.TZ)
    hol = db.get_setting("holidays", []) or []
    ctx = review.context(now)
    flags = {}
    for t in review.tickets(ctx, scope="all"):
        f = []
        if t.writing_late:
            f.append("no doc after 5 bd")
        if t.expert_silent:
            f.append("expert quiet 7 d")
        if t.status == "Text" and t.link_c:
            f.append("drafted but not moved")
        flags[t.key] = f
    since = {r["jira_key"]: r["entered_at"] for r in db.query(
        "select jira_key, entered_at from stage_durations where exited_at is null")}
    activity = {r["jira_key"]: r["at"] for r in db.query(
        "select jira_key, max(created_at) at from comments group by 1")}
    mtd = {}
    if with_money:
        for ln in compute.compute_lines(bd.local_today().replace(day=1), roster):
            if ln["person_id"]:
                cur = mtd.setdefault(ln["person_id"], [0, 0])
                cur[0] += ln["amount"]
                cur[1] += ln["amount_max"]
    tables = []
    for role, label, col, statuses in ROLES:
        rows = db.query(f"select jira_key, summary, status, {col} as who, updated_at from tickets "  # nosec B608
                        f"where status = any(%s) and {col} is not null order by jira_key", (statuses,))
        by: dict[str, list] = {}
        for r in rows:
            r["age"] = bd.elapsed(since[r["jira_key"]], now, hol) if r["jira_key"] in since else None
            r["last_activity"] = activity.get(r["jira_key"]) or r["updated_at"]
            r["flags"] = flags.get(r["jira_key"], [])
            by.setdefault(r["who"], []).append(r)
        people_rows = []
        for acct, ts in by.items():
            p = roster.get(acct)
            people_rows.append({"name": p.display_name if p else f"Unknown ({acct[:12]}…)", "person": p,
                                "tickets": ts, "open": len(ts), "mtd": mtd.get(p.id) if p else None})
        idle = [p for p in roster.with_role(role) if p.jira_account_id and p.jira_account_id not in by]
        people_rows.sort(key=lambda x: x["name"].lower())  # alphabetical: never ranked
        tables.append({"role": role, "label": label, "rows": people_rows, "idle": idle})
    return {"tables": tables}
