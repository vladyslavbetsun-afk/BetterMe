from datetime import date, datetime
from decimal import Decimal

import config
import db
from core import people
from factory import CARTER, EVA, EVE, MARIA, TIM, history, issue, load, status_item
from modules.spend import compute


def at(y, m, d):
    return datetime(y, m, d, 12, tzinfo=config.TZ)


def test_october_lines():
    load(
        # Eve: 1800 words × $0.035 = $63; left Text in October; Carter reviewed in October ($50)
        issue("BP-1", "squats, 1800 words", "Published", at(2026, 9, 20), author=EVE, expert=CARTER, histories=[
            history(at(2026, 9, 21), status_item("Open", "Text")), history(at(2026, 10, 2), status_item("Text", "Review")),
            history(at(2026, 10, 5), status_item("Review", "Text")),  # bounce: not paid twice
            history(at(2026, 10, 7), status_item("Text", "Review")),
            history(at(2026, 10, 9), status_item("Review", "Proofreading")),
            history(at(2026, 10, 10), status_item("Proofreading", "Ready"))], proof=TIM),
        # left Text in September → not October
        issue("BP-2", "lunges, 1500 words", "Ready", at(2026, 9, 1), author=EVE, expert=CARTER, histories=[
            history(at(2026, 9, 2), status_item("Open", "Text")), history(at(2026, 9, 30), status_item("Text", "Review")),
            history(at(2026, 10, 3), status_item("Review", "Proofreading"))]),
        # Eva skips expert review: Maria's review isn't paid
        issue("BP-3", "keto snacks, 1000 words", "Ready", at(2026, 10, 1), author=EVA, expert=MARIA, histories=[
            history(at(2026, 10, 2), status_item("Open", "Text")), history(at(2026, 10, 6), status_item("Text", "Review")),
            history(at(2026, 10, 8), status_item("Review", "Proofreading"))]),
        # unpriced (no word count)
        issue("BP-4", "active recovery day workout, 12k", "Review", at(2026, 10, 1), author=EVE, histories=[
            history(at(2026, 10, 12), status_item("Text", "Review"))]),
    )
    lines = {(ln["person_id"], ln["category"], ln["source"]): ln for ln in compute.compute_lines(date(2026, 10, 1))}
    eve = lines[("eve", "writing", "jira_auto")]
    assert eve["jira_keys"] == ["BP-1", "BP-4"] and eve["amount"] == Decimal(63) and eve["unpriced"] == 1
    assert lines[("eva", "writing", "jira_auto")]["amount"] == Decimal(110)
    carter = lines[("carter", "review", "jira_auto")]
    assert carter["jira_keys"] == ["BP-1", "BP-2"] and carter["amount"] == Decimal(100)
    assert ("corrarello", "review", "jira_auto") not in lines
    assert lines[("tim", "proofreading", "jira_auto")]["unpriced"] == 1  # Tim's rate is VERIFY
    assert lines[("colette", "review", "fixed")]["amount"] == Decimal(2500)
    assert lines[("polina", "research", "fixed")]["amount"] == Decimal(600)


def test_future_rate_does_not_change_past_months():
    load(issue("BP-1", "squats, 1000 words", "Review", at(2026, 9, 1), author=EVE, histories=[
        history(at(2026, 9, 10), status_item("Text", "Review"))]))
    people.set_rate("eve", Decimal("0.05"), "word", date(2026, 10, 1), "upwork")
    sep = {ln["person_id"]: ln for ln in compute.compute_lines(date(2026, 9, 1)) if ln["category"] == "writing"}
    assert sep["eve"]["amount"] == Decimal(35)
    assert db.scalar("select effective_to from rates where person_id = 'eve' and amount = 0.035") == date(2026, 9, 30)


def test_closed_month_is_frozen_and_manual_lines_survive():
    m = date(2026, 10, 1)
    compute.recompute(m)
    db.execute("insert into spend_lines (month, person_id, category, source, amount, note) "
               "values (%s, 'oksana', 'design', 'manual', 300, 'invoice 12')", (m,))
    compute.recompute(m)
    assert db.scalar("select count(*) from spend_lines where source = 'manual'") == 1
    db.execute("update spend_months set status = 'closed' where month = %s", (m,))
    assert compute.recompute(m) == 0
    v = compute.month_view(m)
    msg = compute.budget_message(v)
    assert "*Design*" in msg and "Oksana Pidlisna | $300.00 | manual" in msg and "Grand total" in msg
    assert "(closed)" in msg
