"""Spec 05 §11: creating the same nudge twice (two tabs, a double click, the job plus a manual action) results in
exactly one outbound_messages row. And a confirmed action runs exactly once."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import httpx

import db
from conftest import ago
from core import jira, outbound
from factory import CARTER, EVE, ME, comment, issue, load
from modules.review import service

DOC = "https://docs.google.com/document/d/doc1"


def draft(day=date(2026, 10, 15), keys=("BP-2", "BP-1")):
    return outbound.draft_message(kind="nudge", channel="slack_dm", recipient=EVE, template="writer_followup",
                                  body="Hi Eve", ticket_keys=list(keys), created_by="t", day=day)


def test_same_nudge_twice_is_one_row():
    _, a = draft()
    _, b = draft(keys=("BP-1", "BP-2"))  # same set, other order
    assert a and not b
    assert db.scalar("select count(*) from outbound_messages") == 1


def test_concurrent_drafts_one_row():
    with ThreadPoolExecutor(12) as ex:
        results = list(ex.map(lambda _: draft()[1], range(12)))
    assert results.count(True) == 1
    assert db.scalar("select count(*) from outbound_messages") == 1


def test_new_day_or_new_tickets_is_a_new_message():
    draft()
    draft(day=date(2026, 10, 16))
    draft(keys=("BP-1",))
    assert db.scalar("select count(*) from outbound_messages") == 3


def test_mark_sent_once():
    m, _ = draft()
    assert outbound.mark_sent(m["id"], "t") is True
    assert outbound.mark_sent(m["id"], "t") is False


class FakeJira:
    """Records calls; answers transitions with the BP workflow."""

    def __init__(self, issues=None):
        self.calls = []
        self.issues = issues or []

    def handler(self, request: httpx.Request):
        body = json.loads(request.content or b"{}")
        self.calls.append((request.method, request.url.path, body))
        if request.url.path.endswith("/transitions") and request.method == "GET":
            return httpx.Response(200, json={"transitions": [
                {"id": "21", "to": {"name": "Review"}}, {"id": "31", "to": {"name": "Proofreading"}},
                {"id": "41", "to": {"name": "Ready"}}, {"id": "51", "to": {"name": "Published"}}]})
        if request.url.path.endswith("/search/jql"):
            return httpx.Response(200, json={"issues": self.issues, "isLast": True})
        return httpx.Response(204)

    def client(self):
        return jira.JiraClient(transport=httpx.MockTransport(self.handler))

    def writes(self):
        return [(m, p, b) for m, p, b in self.calls if m in ("PUT", "POST") and not p.endswith("/search/jql")]


def test_execute_respects_flag_and_runs_once():
    a = outbound.propose("jira.review", "BP-1", {"ops": [{"op": "transition", "to": "Review"}]}, "t", "idem-1")
    fake = FakeJira()
    try:
        outbound.execute(a["id"], "t", client=fake.client())
        raise AssertionError("should refuse while jira_writes_enabled is off")
    except PermissionError:
        pass
    db.set_setting("jira_writes_enabled", True)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda _: outbound.execute(a["id"], "t", client=fake.client()), range(6)))
    assert [w[1] for w in fake.writes()] == ["/rest/api/3/issue/BP-1/transitions"]
    assert fake.writes()[0][2] == {"transition": {"id": "21"}}
    assert db.scalar("select state from actions where id = %s", (a["id"],)) == "sent"
    # proposing the same thing again returns the sent row and does nothing
    again = outbound.propose("jira.review", "BP-1", {"ops": []}, "t", "idem-1")
    assert again["id"] == a["id"] and again["state"] == "sent"


def test_failed_action_can_be_retried():
    db.set_setting("jira_writes_enabled", True)
    a = outbound.propose("jira.review", "BP-1", {"ops": [{"op": "transition", "to": "Nowhere"}]}, "t", "idem-2")
    res = outbound.execute(a["id"], "t", client=FakeJira().client())
    assert res["state"] == "failed" and "no transition to Nowhere" in res["error"]
    again = outbound.propose("jira.review", "BP-1", {"ops": [{"op": "transition", "to": "Review"}]}, "t", "idem-2")
    assert again["state"] == "proposed"


def jira_issue(status, comments):
    i = issue("BP-50", "keto snacks, 1600 words", status, ago(10), author=EVE, expert=CARTER,
              participants=[EVE, CARTER], comments=comments)
    return i


def test_run_steps_rereads_and_acts(monkeypatch):
    cs = [comment(EVE, ago(5), "", DOC), comment(CARTER, ago(1), "Left comments.")]
    load(jira_issue("Review", cs))
    db.set_setting("jira_writes_enabled", True)
    fake = FakeJira([jira_issue("Review", cs)])
    msg = service.run_steps("BP-50", ["toProof", "note"], "t", client=fake.client())
    assert "move to Proofreading" in msg
    w = fake.writes()
    assert w[0][1].endswith("/transitions") and w[0][2] == {"transition": {"id": "31"}}
    assert w[1][1].endswith("/comment") and w[1][2]["visibility"] == {"type": "role", "value": "Service Desk Team"}
    assert w[1][2]["body"]["content"][0]["content"][1]["text"] == " Hi. Please address the comments. Thanks."


def test_run_steps_skips_when_ticket_changed():
    cs = [comment(EVE, ago(5), "", DOC), comment(CARTER, ago(1), "Left comments.")]
    load(jira_issue("Review", cs))
    db.set_setting("jira_writes_enabled", True)
    fake = FakeJira([jira_issue("Proofreading", cs)])  # someone moved it meanwhile
    msg = service.run_steps("BP-50", ["toProof"], "t", client=fake.client())
    assert "changed since the last refresh" in msg and fake.writes() == []


def test_automation_dry_run_writes_nothing():
    from datetime import datetime

    import config

    now = datetime.now(config.TZ)
    cs = [comment(EVE, now.replace(microsecond=0) - __import__("datetime").timedelta(hours=5), "", DOC),
          comment(CARTER, now - __import__("datetime").timedelta(hours=1), "Left comments.")]
    load(jira_issue("Review", cs))
    db.set_setting("review_automation_enabled", True)
    fake = FakeJira([jira_issue("Review", cs)])
    n = service.run_automation("schedule:test", client=fake.client())
    assert n == 1 and fake.writes() == []
    assert db.scalar("select count(*) from audit_log where action = 'review.dry_run'") == 1
    assert db.scalar("select count(*) from actions") == 0
    _ = ME
