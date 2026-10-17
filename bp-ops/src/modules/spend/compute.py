"""Monthly spend from Jira (spec 05 §8.6, rules 00 §6.3).

Recognition: a writer's article counts in the month it FIRST left Text, an expert's review in the month it first left
Review, proofreading in the month it first left Proofreading (VERIFY with Yuliia Horetska, docs/decisions.md D-09).
"First" means a ticket bounced back later is never paid twice.
"""

from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal

import config
import db
from core import people as people_mod
from core import rules

STAGE_CATEGORY = {"Text": "writing", "Review": "review", "Proofreading": "proofreading"}
PERSON_FIELD = {"Text": "author_id", "Review": "expert_id", "Proofreading": "proofreader_id"}
ROLE_CATEGORY = {"writer": "writing", "expert": "review", "proofreader": "proofreading", "researcher": "research",
                 "designer": "design"}


def month_bounds(month: date) -> tuple[datetime, datetime]:
    start = month.replace(day=1)
    nxt = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return datetime.combine(start, time(0), tzinfo=config.TZ), datetime.combine(nxt, time(0), tzinfo=config.TZ)


def first_exits(stage: str, lo: datetime, hi: datetime) -> list[dict]:
    return db.query(
        "select t.jira_key, t.summary, t.author_id, t.expert_id, t.proofreader_id, f.at from tickets t join "
        "(select jira_key, min(at) as at from status_transitions where from_status = %s group by jira_key) f "
        "using (jira_key) where f.at >= %s and f.at < %s order by t.jira_key", (stage, lo, hi))


def compute_lines(month: date, roster: people_mod.Roster | None = None) -> list[dict]:
    """jira_auto + fixed lines for a month (not saved). Each line: person_id, category, source, keys, lo, hi, unpriced."""
    roster = roster or people_mod.load()
    lo_t, hi_t = month_bounds(month)
    lines: dict[tuple, dict] = {}

    def line(pid, cat, source, note=None):
        k = (pid, cat, source, note)
        if k not in lines:
            lines[k] = {"person_id": pid, "category": cat, "source": source, "jira_keys": [], "amount": Decimal(0),
                        "amount_max": Decimal(0), "unpriced": 0, "note": note}
        return lines[k]

    for stage, cat in STAGE_CATEGORY.items():
        for t in first_exits(stage, lo_t, hi_t):
            acct = t[PERSON_FIELD[stage]]
            if not acct:
                continue
            p = roster.get(acct)
            if stage == "Review" and t["author_id"] and (w := roster.get(t["author_id"])) and w.skip_expert_review:
                continue  # writer skips expert review (00 §6.3)
            ln = line(p.id if p else None, cat, "jira_auto", None if p else f"unknown Jira account {acct}")
            ln["jira_keys"].append(t["jira_key"])
            on = t["at"].astimezone(config.TZ).date()
            rate = p.rate_at(on) if p else None
            words = rules.word_count(t["summary"])
            price = rules.writer_price(rate, words) if stage == "Text" else rules.expert_fee(rate, words)
            if price is None:
                ln["unpriced"] += 1
            else:
                ln["amount"] += price.lo
                ln["amount_max"] += price.hi

    for p in roster.people:
        if not p.active:
            continue
        r = p.rate_at(month)
        if r and r.unit == "month":
            ln = line(p.id, ROLE_CATEGORY.get(p.role, "other"), "fixed")
            ln["amount"] = ln["amount_max"] = Decimal(r.amount)
    return list(lines.values())


def ensure_month(month: date) -> dict:
    db.execute("insert into spend_months (month, status) values (%s, 'open') on conflict do nothing", (month,))
    return db.one("select * from spend_months where month = %s", (month,))


def recompute(month: date) -> int:
    """Replace jira_auto and fixed lines of an open month. Manual lines are never touched. Closed months are frozen."""
    m = ensure_month(month)
    if m["status"] == "closed":
        return 0
    lines = compute_lines(month)
    with db.conn() as c:
        c.execute("delete from spend_lines where month = %s and source in ('jira_auto', 'fixed')", (month,))
        for ln in lines:
            c.execute("insert into spend_lines (month, person_id, category, source, jira_keys, amount, amount_max, "
                      "unpriced, note) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                      (month, ln["person_id"], ln["category"], ln["source"], ln["jira_keys"], ln["amount"],
                       ln["amount_max"], ln["unpriced"], ln["note"]))
    return len(lines)


def month_view(month: date) -> dict:
    roster = people_mod.load()
    m = ensure_month(month)
    rows = db.query("select * from spend_lines where month = %s order by category, source, person_id", (month,))
    cats: dict[str, list] = defaultdict(list)
    for r in rows:
        r["name"] = roster.by_id[r["person_id"]].display_name if r["person_id"] in roster.by_id else (
            r["note"] or "—")
        r["hi"] = r["amount_max"] if r["amount_max"] is not None else r["amount"]
        cats[r["category"]].append(r)
    totals = {c: (sum(r["amount"] for r in rs), sum(r["hi"] for r in rs)) for c, rs in cats.items()}
    grand = (sum(t[0] for t in totals.values()), sum(t[1] for t in totals.values()))
    paid_ids = {r["person_id"] for r in rows if r["person_id"]}
    missing = [p for p in roster.people if p.active and p.role in ROLE_CATEGORY and p.id not in paid_ids
               and p.role != "designer"]
    return {"month": m, "cats": dict(cats), "totals": totals, "grand": grand, "missing": missing}


SOURCE_LABEL = {"jira_auto": "Jira (computed)", "fixed": "fixed monthly", "manual": "manual"}
CAT_LABEL = {"writing": "Writers", "review": "Experts / Reviewers", "proofreading": "Proofreading",
             "research": "Research", "design": "Design", "other": "E-com / other"}
CAT_ORDER = ["writing", "review", "proofreading", "research", "design", "other"]


def _amt(lo, hi) -> str:
    return f"${lo:,.2f}" if lo == hi else f"${lo:,.2f}–{hi:,.2f}"


def budget_message(v: dict) -> str:
    """Format of the betterme-blog-budgeting skill (Step 5): one table per category (Name | Amount | Source),
    a subtotal per category, a grand total, then everyone with no data — never a guessed number."""
    month = v["month"]["month"]
    out = [f"Blog budget — {month:%B %Y}" + (" (closed)" if v["month"]["status"] == "closed" else " (open, estimate)"),
           ""]
    for c in CAT_ORDER:
        rows = v["cats"].get(c)
        if not rows:
            continue
        out.append(f"*{CAT_LABEL[c]}*")
        out.append("Name | Amount | Source")
        for r in rows:
            src = SOURCE_LABEL[r["source"]]
            if r["source"] == "jira_auto":
                src += f", {len(r['jira_keys'])} article{'s' if len(r['jira_keys']) != 1 else ''}"
                if r["unpriced"]:
                    src += f", {r['unpriced']} without a price"
            if r["source"] == "fixed":
                src += " (stated retainer, not document-verified)"
            out.append(f"{r['name']} | {_amt(r['amount'], r['hi'])} | {src}")
        lo, hi = v["totals"][c]
        out.append(f"Subtotal: {_amt(lo, hi)}")
        out.append("")
    out.append(f"*Grand total: {_amt(*v['grand'])}*")
    if v["missing"]:
        out.append("")
        out.append("No data found for: " + ", ".join(p.display_name for p in v["missing"])
                   + ". Are they paid through a channel not checked yet?")
    return "\n".join(out)
