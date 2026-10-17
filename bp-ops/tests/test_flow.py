from datetime import date, datetime, timedelta

import config
import db
from conftest import ago
from factory import EVE, history, issue, load, status_item
from modules.flow import metrics, qa


def test_bounce_gives_two_review_visits():
    load(issue("BP-1", "squats", "Review", ago(30), author=EVE, histories=[
        history(ago(25), status_item("Open", "Text")), history(ago(20), status_item("Text", "Review")),
        history(ago(15), status_item("Review", "Text")), history(ago(10), status_item("Text", "Review"))]))
    rows = db.query("select stage, exited_at from stage_durations where jira_key = 'BP-1' order by entered_at")
    assert [r["stage"] for r in rows] == ["Open", "Text", "Review", "Text", "Review"]
    assert rows[-1]["exited_at"] is None
    assert metrics.rework_rate(datetime.now(config.TZ) - timedelta(days=90))["bounced"] == 1


def test_throughput_and_clearance():
    now = datetime.now(config.TZ)
    days = metrics.last_business_days(10)
    for i, d in enumerate(days[-3:]):  # 1 published on each of the last 3 business days
        at = datetime.combine(d, datetime.min.time(), tzinfo=config.TZ) + timedelta(hours=11)
        load(issue(f"BP-{100 + i}", "x", "Published", at - timedelta(days=20),
                   histories=[history(at - timedelta(days=1), status_item("Proofreading", "Ready")),
                              history(at, status_item("Ready", "Published"))]))
    t = metrics.throughput(10)
    assert sum(t["per_day"]) == 3 and t["median"] == 0 and abs(t["mean"] - 0.3) < 1e-9
    c = metrics.clearance(10, 5.0, start=date(2026, 10, 16))
    assert c["business_days"] == 2 and c["date"] == "2026-10-20"
    assert metrics.clearance(10, 2, extra_inflow=3)["date"] is None
    assert now  # silence


def test_wip_matches_tickets_and_summary_renders():
    load(issue("BP-1", "a", "Ready", ago(10), histories=[history(ago(2), status_item("Proofreading", "Ready"))]),
         issue("BP-2", "b", "Text", ago(10)), issue("BP-3", "c", "Text", ago(10)))
    s = metrics.summary()
    assert s["wip"]["Text"] == 2 and s["wip"]["Ready"] == 1 and len(s["ready"]) == 1
    assert s["ready"][0]["images"] == "missing"
    today = db.query("select * from flow_daily where date = (select max(date) from flow_daily) and stage = 'Text'")
    assert today[0]["wip"] == 2
    text = metrics.slack_summary(s)
    assert "Ready backlog: 1" in text and len(text.splitlines()) == 5


def test_no_person_names_in_flow_summary():
    load(issue("BP-1", "a", "Ready", ago(10), author=EVE))
    blob = repr(metrics.summary())
    assert "Eve" not in blob and EVE not in blob


def test_qa_parse_and_mismatch():
    html = ('<script type="application/ld+json">{"@graph":[{"@type":"Article","dateModified":"2026-09-01T10:00:00"}]}'
            '</script><h1 class="t">Squats <em>for</em> Beginners</h1>')
    p = qa.parse_page(html)
    assert p == {"updated_on": date(2026, 9, 1), "h1": "Squats for Beginners"}
    assert qa.parse_page("<p>Updated on <b>October 2, 2026</b></p>")["updated_on"] == date(2026, 10, 2)
    pub = datetime(2026, 10, 10, 12, tzinfo=config.TZ)
    assert qa.is_mismatch(date(2026, 9, 1), pub, 200)
    assert not qa.is_mismatch(date(2026, 10, 9), pub, 200)
    assert qa.is_mismatch(None, pub, 404)
