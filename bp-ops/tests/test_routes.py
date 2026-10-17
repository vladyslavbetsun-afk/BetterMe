import pytest
from fastapi.testclient import TestClient

import db
from conftest import ago
from factory import CARTER, EVE, ME, comment, issue, load


@pytest.fixture()
def client():
    import app

    with TestClient(app.app) as c:
        yield c


def as_(email):
    return {"X-Auth-Request-Email": email}


def test_role_guards(client):
    db.execute("update people set email = 'fin@example.test' where id = 'yuliia_h'")
    db.execute("update people set email = 'vol@example.test' where id = 'volodymyr'")
    owner, fin, viewer, nobody = as_("owner@example.test"), as_("fin@example.test"), as_("vol@example.test"), as_("x@y.z")
    assert client.get("/flow", headers=owner).status_code == 200
    assert client.get("/spend", headers=fin).status_code == 200
    assert client.get("/flow", headers=fin).status_code == 403
    assert client.get("/spend", headers=viewer).status_code == 403
    assert client.get("/flow", headers=viewer).status_code == 200
    assert client.get("/admin", headers=viewer).status_code == 403
    assert client.get("/flow", headers=nobody).status_code == 403
    assert client.post("/review/exclude", data={"key": "BP-1"}, headers=viewer).status_code == 403


def test_viewer_sees_no_money(client):
    db.execute("update people set email = 'vol@example.test' where id = 'volodymyr'")
    load(issue("BP-1", "squats, 1800 words", "Open", ago(3)))
    r = client.get("/assign?key=BP-1", headers=as_("vol@example.test"))
    assert r.status_code == 200 and "/word" not in r.text and "$" not in r.text
    r = client.get("/assign?key=BP-1", headers=as_("owner@example.test"))
    assert "$63" in r.text or "$" in r.text


def test_double_click_draft_one_row(client):
    for k in ("BP-20",):
        load(issue(k, "squats, 1800 words", "Review", ago(30), author=EVE, expert=CARTER,
                   comments=[comment(EVE, ago(20), "", "https://docs.google.com/document/d/x"),
                             comment(CARTER, ago(15), "done"),
                             comment(ME, ago(7), "Hi. Any news on the edits?", mention=EVE)]))
    h = as_("owner@example.test")
    for _ in range(2):
        assert client.post("/review/draft", data={"writer_id": EVE}, headers=h, follow_redirects=False).status_code == 303
    assert db.scalar("select count(*) from outbound_messages") == 1


def test_pages_render_with_data(client):
    load(issue("BP-20", "squats, 1800 words", "Review", ago(30), author=EVE, expert=CARTER,
               comments=[comment(EVE, ago(20), "", "https://docs.google.com/document/d/x"), comment(CARTER, ago(1), "ok")]),
         issue("BP-21", "keto snacks, 1500 words", "Open", ago(2)),
         issue("BP-22", "chair yoga, 1500 words", "Ready", ago(40)))
    h = as_("owner@example.test")
    for p in ["/flow", "/review", "/review?scope=all", "/assign?key=BP-21", "/load", "/publish", "/report", "/spend",
              "/pipeline", "/admin", "/admin/roster", "/admin/log", "/images", "/performance"]:
        r = client.get(p, headers=h)
        assert r.status_code == 200, p
    r = client.post("/review/act", data={"key": "BP-20", "kinds": "toProof"}, headers=h, follow_redirects=False)
    assert r.status_code == 303
    assert db.scalar("select count(*) from actions where jira_key = 'BP-20' and state = 'proposed'") == 1
    assert "move to Proofreading" in client.get("/review", headers=h).text
    r = client.post("/assign", data={"key": "BP-21", "writer": "eve"}, headers=h, follow_redirects=False)
    assert db.scalar("select payload->>'description' from actions where kind = 'jira.assign'").startswith("set Author = Eve")
    r = client.post("/publish/batch", data={"keys": ["BP-22"]}, headers=h, follow_redirects=False)
    bid = db.scalar("select id from batches")
    client.post(f"/publish/batch/{bid}/prepare", data={"when": ""}, headers=h)
    m = db.one("select * from outbound_messages where template = 'publishing_batch'")
    assert m["body"].startswith("Hi. Here are articles for publishing:\n• <https://newsiteam.atlassian.net/browse/BP-22|BP-22 chair yoga, 1500 words>")
    assert client.get("/api/images/status?keys=BP-22", headers=h).json() == {"BP-22": "missing"}
