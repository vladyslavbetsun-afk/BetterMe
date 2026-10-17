"""End-to-end runs with offline fakes: confirmation, holds, unit guard, Notion dedupe and crash recovery."""
from datetime import date, timedelta

import pytest

from decay import report as rp
from decay.notion import SchemaError, create_cards, iso_week
from decay.pipeline import Clients, run

from .conftest import BASE, TODAY, FakeAhrefs, FakeFetcher, FakeJira, FakeNotion, page_html, row


def do_run(cfg, store, rows, run_date="2026-10-18", fetcher=None, **clients):
    c = Clients(ahrefs=FakeAhrefs(rows), fetcher=fetcher or FakeFetcher(), **clients)
    return run(cfg, store, c, run_date, None)


def item(store, slug):
    return store.item(BASE + slug + "/")


def test_first_week_minor_drop_is_watch_then_confirmed(cfg, store):
    rows = [row("wall pilates routine", "wall-pilates", was=2, now=6, t_prev=200, t_now=120)]
    do_run(cfg, store, rows, "2026-10-11")
    it = item(store, "wall-pilates")
    assert it["state"] == "watch" and it["level"] == "L0" and it["confirmations"] == 1
    assert "second weekly confirmation" in it["why"]

    do_run(cfg, store, rows, "2026-10-12")  # re-run in the same ISO week does not count
    assert item(store, "wall-pilates")["state"] == "watch"

    do_run(cfg, store, rows, "2026-10-18")
    it = item(store, "wall-pilates")
    assert it["confirmations"] == 2 and it["state"] == "proposed" and it["level"] in ("L1", "L2", "L3")


def test_severe_loss_confirms_on_first_run(cfg, store):
    do_run(cfg, store, [row("chair yoga for seniors", "chair-yoga", was=1, now=None, t_prev=150, t_now=0)])
    assert item(store, "chair-yoga")["state"] == "proposed"
    do_run(cfg, store, [row("calisthenics plan", "calisthenics", was=1, now=7, t_prev=500, t_now=250)])
    assert item(store, "calisthenics")["state"] == "proposed"  # traffic lost >= 200


def test_unit_guard_aborts_and_is_visible(cfg, store):
    cfg.settings["max_units_per_run"] = 1000
    ahrefs = FakeAhrefs([row("kw", "a", now=None)])
    res = run(cfg, store, Clients(ahrefs=ahrefs, fetcher=FakeFetcher()), "2026-10-18", None)
    assert res.aborted and not ahrefs.calls
    data = rp.collect(cfg, store, res.run_ids)
    assert data["aborted"][0]["status"] == "aborted"
    assert "Unit guard" in rp.slack_text(cfg, data)
    assert "Unit guard" in rp.to_html(cfg, data)


def test_recently_updated_page_is_never_carded(cfg, store):
    recent = (TODAY - timedelta(days=10)).strftime("%B %d, %Y")
    url = BASE + "wall-pilates/"
    do_run(cfg, store, [row("wall pilates routine", "wall-pilates", now=None)],
           fetcher=FakeFetcher({url: page_html(updated=recent)}))
    it = item(store, "wall-pilates")
    assert it["level"] == "L0" and it["state"] == "confirmed" and "Updated 10 days ago" in it["why"]
    cards, _ = create_cards(cfg, store, None, dry_run=True)
    assert cards == []
    cards, _ = create_cards(cfg, store, None, dry_run=True, urls=[url])
    assert cards == []


def test_open_ticket_or_card_holds_page(cfg, store):
    a, b = BASE + "a/", BASE + "b/"
    notion = FakeNotion()
    notion.add_existing(b)
    do_run(cfg, store, [row("kw a", "a", now=None), row("kw b", "b", now=None)],
           jira=FakeJira(open_for={a: "BP-77"}), notion=notion)
    assert store.item(a)["level"] == "L0" and "BP-77" in store.item(a)["why"]
    assert store.item(b)["level"] == "L0" and "Notion card" in store.item(b)["why"]
    assert create_cards(cfg, store, None, dry_run=True)[0] == []


def test_noseo_names_category_and_every_item_has_why(cfg, store):
    url = BASE + "dry-fasting/"
    do_run(cfg, store, [row("dry fasting benefits", "dry-fasting", now=None), row("wall pilates", "wall-pilates", now=9)],
           fetcher=FakeFetcher({url: page_html(title="Dry Fasting Benefits")}))
    it = store.item(url)
    assert it["level"] == "NOSEO" and it["state"] == "noseo" and "#17" in it["why"]
    for r in store.items():
        assert r["why"] and r["checklist"]


def test_cap_limits_proposals(cfg, store):
    cfg.settings["weekly_card_cap"] = 2
    rows = [row(f"kw {i}", f"page-{i}", now=None, t_prev=100 + i) for i in range(5)]
    do_run(cfg, store, rows)
    states = sorted(r["state"] for r in store.items())
    assert states.count("proposed") == 2 and states.count("confirmed") == 3
    proposed = [r["url"] for r in store.items() if r["state"] == "proposed"]
    assert set(proposed) == {BASE + "page-4/", BASE + "page-3/"}  # highest traffic lost


def test_dry_run_writes_nothing(cfg, store):
    do_run(cfg, store, [row("wall pilates routine", "wall-pilates", now=None)])
    cards, outcomes = create_cards(cfg, store, FakeNotion(), dry_run=True)
    assert len(cards) == 1 and outcomes == []
    assert store.one("select count(*) as n from decay_cards")["n"] == 0
    card = cards[0]
    assert card.properties["Name"] == "wall pilates routine, update"
    assert card.properties["New/Upd"] == "Update" and card.properties["Status"] == "Not started"
    assert card.properties["URL 1"] == BASE + "wall-pilates/" and card.properties["JIRA"] is None
    assert card.properties["Date"] == TODAY.isoformat() and card.properties["category"] == "Wall Pilates"
    assert card.body_markdown.startswith("## Decay radar — L")
    assert "Generated by Decay Radar run" in card.body_markdown


def test_apply_creates_and_verifies(cfg, store):
    do_run(cfg, store, [row("wall pilates routine", "wall-pilates", now=None)])
    notion = FakeNotion()
    _, outcomes = create_cards(cfg, store, notion, dry_run=False)
    assert [o.action for o in outcomes] == ["created"] and outcomes[0].verified
    it = item(store, "wall-pilates")
    assert it["state"] == "carded" and it["notion_url"]
    assert store.one("select iso_week from decay_cards")["iso_week"] == iso_week(TODAY)
    assert store.one("select source from decay_suggestions")["source"] == "decay-radar"
    # same week again: nothing new
    _, outcomes = create_cards(cfg, store, notion, dry_run=False, urls=[BASE + "wall-pilates/"])
    assert len(notion.pages) == 1 and outcomes[0].action == "skipped"


def test_open_card_gets_comment_instead_of_duplicate(cfg, store):
    do_run(cfg, store, [row("wall pilates routine", "wall-pilates", now=None)])
    notion = FakeNotion()
    notion.add_existing(BASE + "wall-pilates/")  # someone opened a card after the run
    _, outcomes = create_cards(cfg, store, notion, dry_run=False)
    assert outcomes[0].action == "commented" and len(notion.pages) == 1
    assert "still slipping, now lost for 'wall pilates routine'" in notion.comments[0][1]


def test_forced_failure_then_rerun_creates_no_duplicates(cfg, store):
    do_run(cfg, store, [row(f"kw {i}", f"page-{i}", now=None, t_prev=100 + i) for i in range(3)])
    notion = FakeNotion()
    with pytest.raises(RuntimeError, match="forced failure"):
        create_cards(cfg, store, notion, dry_run=False, fail_after=1)
    assert len(notion.pages) == 2  # second page created in Notion, never stored locally
    _, outcomes = create_cards(cfg, store, notion, dry_run=False)
    assert sorted(o.action for o in outcomes) == ["adopted", "created"]
    assert len(notion.pages) == 3
    urls = [p["properties"]["URL 1"]["url"] for p in notion.pages.values()]
    assert len(urls) == len(set(urls))
    assert store.one("select count(*) as n from decay_cards where notion_url is not null")["n"] == 3


def test_schema_drift_fails_loudly(cfg, store):
    do_run(cfg, store, [row("wall pilates routine", "wall-pilates", now=None)])
    schema = dict(FakeNotion.SCHEMA)
    del schema["URL 1"], schema["Primary category"]
    with pytest.raises(SchemaError, match="URL 1"):
        create_cards(cfg, store, FakeNotion(schema), dry_run=False)


def test_report_outputs(cfg, store):
    do_run(cfg, store, [row("wall pilates routine", "wall-pilates", now=None), row("kw b", "b", now=8)])
    data = rp.collect(cfg, store)
    html = rp.to_html(cfg, data)
    assert "Decay Radar" in html and "wall-pilates" in html and "Proposed this week" in html
    csv_text = rp.to_csv(data)
    assert csv_text.splitlines()[0].startswith("url,level,state")
    text = rp.slack_text(cfg, data)
    assert text.startswith("Decay radar (Oct 20): 2 pages lost top-3")
    assert "visits/mo at risk" in text
