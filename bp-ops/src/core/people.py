"""The one roster (spec 00 §2). Match people by Jira accountId, never by display name."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import db
from core.rules import Rate


@dataclass
class Person:
    id: str
    display_name: str
    role: str | None
    jira_account_id: str | None = None
    slack_id: str | None = None
    email: str | None = None
    niche: str | None = None
    skip_expert_review: bool = False
    active: bool = True
    app_role: str | None = None
    notes: str | None = None
    rates: list[dict] = field(default_factory=list)

    def rate_at(self, on: date, kind: str = "base") -> Rate | None:
        best = None
        for r in self.rates:
            if r["kind"] != kind:
                continue
            if r["effective_from"] and r["effective_from"] > on:
                continue
            if r["effective_to"] and r["effective_to"] < on:
                continue
            if best is None or r["effective_from"] > best["effective_from"]:
                best = r
        if best is None:
            return None
        return Rate(Decimal(best["amount"]), best["unit"],
                    Decimal(best["amount_max"]) if best["amount_max"] is not None else None)


class Roster:
    def __init__(self, people: list[Person]):
        self.people = people
        self.by_id = {p.id: p for p in people}
        self.by_account = {p.jira_account_id: p for p in people if p.jira_account_id}

    def get(self, account_id: str | None) -> Person | None:
        return self.by_account.get(account_id) if account_id else None

    def name(self, account_id: str | None, fallback: str = "—") -> str:
        p = self.get(account_id)
        return p.display_name if p else fallback

    def with_role(self, role: str, active_only: bool = True) -> list[Person]:
        return [p for p in self.people if p.role == role and (p.active or not active_only)]

    def experts(self, category: str) -> list[Person]:
        """Active experts for a category who can be picked automatically (accountId known)."""
        return [p for p in self.with_role("expert") if p.niche == category and p.jira_account_id]


def load() -> Roster:
    rows = db.query("select * from people order by display_name")
    rates = db.query("select * from rates order by effective_from")
    by_person: dict[str, list[dict]] = {}
    for r in rates:
        by_person.setdefault(r["person_id"], []).append(r)
    people = []
    for r in rows:
        people.append(Person(id=r["id"], display_name=r["display_name"], role=r["role"],
                             jira_account_id=r["jira_account_id"], slack_id=r["slack_id"], email=r["email"],
                             niche=r["niche"], skip_expert_review=r["skip_expert_review"], active=r["active"],
                             app_role=r["app_role"], notes=r["notes"], rates=by_person.get(r["id"], [])))
    return Roster(people)


def set_rate(person_id: str, amount: Decimal, unit: str, effective_from: date, billing: str | None = None,
             amount_max: Decimal | None = None, kind: str = "base", note: str | None = None) -> None:
    """Add a new effective-dated rate and close the previous open one the day before. Past months keep old rates."""
    with db.conn() as c:
        c.execute("update rates set effective_to = %s::date - 1 where person_id = %s and kind = %s "
                  "and effective_to is null and effective_from < %s",
                  (effective_from, person_id, kind, effective_from))
        c.execute("insert into rates (person_id, kind, amount, amount_max, unit, billing, effective_from, note) "
                  "values (%s, %s, %s, %s, %s, %s, %s, %s)",
                  (person_id, kind, amount, amount_max, unit, billing, effective_from, note))
