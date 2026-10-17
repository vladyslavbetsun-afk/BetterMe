"""Assign (spec 05 §8.2), ported from legacy/assignment-desk.html. Rates and earnings come from people/rates."""

from collections import defaultdict
from datetime import date

import config
import db
from core import business_days as bd
from core import outbound, people, rules
from modules.spend import compute


def fits(niche: str | None, category: str | None) -> bool:
    if not category or niche in ("any", "both", None):
        return True
    return (category == "fitness" and niche == "exercise") or (category == "nutrition" and niche == "nutrition")


def view(selected: str | None = None) -> dict:
    roster = people.load()
    today = bd.local_today()
    open_q = db.query("select * from tickets where status = 'Open' order by created_at")
    for t in open_q:
        t["words"] = (t["word_min"], t["word_max"]) if t["word_min"] else None
    load = defaultdict(lambda: defaultdict(int))
    for r in db.query("select author_id, status, count(*) n from tickets where status = any(%s) "
                      "and author_id is not null group by 1, 2", (config.ACTIVE,)):
        load[r["author_id"]][r["status"]] = r["n"]
    month = today.replace(day=1)
    mtd = {ln["person_id"]: ln for ln in compute.compute_lines(month, roster) if ln["category"] == "writing"}
    sel = next((t for t in open_q if t["jira_key"] == selected), None)
    writers = []
    for w in roster.with_role("writer"):
        if not w.jira_account_id:
            continue
        rate = w.rate_at(today)
        price = None
        if sel:
            p = rules.writer_price(rate, sel["words"])
            if p:
                price = p + rules.open_ticket_expert_estimate(sel["category_detected"], w.skip_expert_review)
        writers.append({"p": w, "rate": rate, "load": dict(load[w.jira_account_id]),
                        "in_text": load[w.jira_account_id].get("Text", 0),
                        "fit": fits(w.niche, sel["category_detected"]) if sel else True,
                        "price": price, "mtd": mtd.get(w.id)})
    writers.sort(key=lambda x: (not x["fit"], x["in_text"], x["p"].display_name))
    return {"open": open_q, "selected": sel, "writers": writers, "month": month}


def assign_ops(ticket: dict, writer: people.Person) -> tuple[list[dict], str]:
    fields, did = {}, []
    if ticket["author_id"] != writer.jira_account_id:
        fields[config.F_AUTHOR] = {"accountId": writer.jira_account_id}
        did.append(f"set Author = {writer.display_name}")
    if writer.jira_account_id not in (ticket["participants"] or []):
        fields[config.F_PARTICIPANTS] = [{"accountId": a} for a in
                                         dict.fromkeys([*(ticket["participants"] or []), writer.jira_account_id])]
        did.append("add them to Request participants")
    ops = ([{"op": "edit", "fields": fields}] if fields else []) + [{"op": "transition", "to": "Text"}]
    return ops, ", ".join([*did, "move to Text"])


def propose_assign(key: str, writer_id: str, actor: str, day: date | None = None) -> tuple[dict, str]:
    t = db.one("select * from tickets where jira_key = %s", (key,))
    if not t or t["status"] != "Open":
        raise ValueError(f"{key} is not Open")
    w = people.load().by_id.get(writer_id)
    if not w or not w.jira_account_id:
        raise ValueError("Unknown writer")
    ops, desc = assign_ops(t, w)
    idem = outbound.idempotency_key("assign", key, [key], day or bd.local_today(), w.id)
    return outbound.propose("jira.assign", key, {"ops": ops, "writer": w.id, "description": desc}, actor, idem), desc
