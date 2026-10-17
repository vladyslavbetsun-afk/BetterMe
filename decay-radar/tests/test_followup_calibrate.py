import json
from datetime import timedelta

from decay import calibrate as cal
from decay.followup import evaluate, run_followups
from decay.notion import create_cards
from decay.pipeline import Clients, run

from .conftest import BASE, TODAY, FakeAhrefs, FakeFetcher, FakeNotion, page_html, row

BASE_KWS = [{"kw": "wall pilates", "vol": 5000, "was": 2, "now": 9, "traffic_prev": 1000, "traffic_now": 200, "kind": "dropped"},
            {"kw": "wall pilates plan", "vol": 900, "was": 1, "now": None, "traffic_prev": 100, "traffic_now": 0, "kind": "lost"}]


def test_evaluate_outcomes(cfg):
    assert evaluate(cfg, BASE_KWS, "wall pilates", {"wall pilates": {"position": 3, "traffic": 300}}) == "recovered"
    assert evaluate(cfg, BASE_KWS, "wall pilates", {"wall pilates": {"position": 5, "traffic": 900}}) == "recovered"  # 700/900
    assert evaluate(cfg, BASE_KWS, "wall pilates", {"wall pilates": {"position": 6, "traffic": 300}}) == "partial"
    assert evaluate(cfg, BASE_KWS, "wall pilates", {"wall pilates": {"position": 12, "traffic": 150}}) == "not_recovered"


def test_update_detected_then_not_recovered_escalates(cfg, store):
    url = BASE + "wall-pilates/"
    rows = [row("wall pilates routine", "wall-pilates", was=2, now=None, t_prev=400, t_now=0)]
    fetch = FakeFetcher({url: page_html(updated="March 3, 2025", key_takeaways=False)})
    run(cfg, store, Clients(ahrefs=FakeAhrefs(rows), fetcher=fetch), "2026-10-11", None)
    notion = FakeNotion()
    create_cards(cfg, store, notion, dry_run=False)
    level_before = store.item(url)["level"]
    assert store.item(url)["state"] == "carded"

    # The writer updates the page; next weekly run notices the new byline.
    fetch.pages[url] = page_html(updated="October 15, 2026")
    run(cfg, store, Clients(ahrefs=FakeAhrefs(rows), fetcher=fetch), "2026-10-18", None)
    it = store.item(url)
    assert it["state"] == "updated" and it["updated_on_new"] == "2026-10-15"
    due = store.query("select label, due_date from decay_followups where url=? order by due_date", [url])
    assert [(d["label"], d["due_date"]) for d in due] == [("+14d", "2026-10-29"), ("+28d", "2026-11-12")]

    ahrefs = FakeAhrefs()
    ahrefs.followup_rows = []  # still not ranking
    cfg.today = TODAY + timedelta(days=30)
    done = run_followups(cfg, store, ahrefs, notion, None, cfg.today)
    assert [d["label"] for d in done] == ["+14d", "+28d"]
    it = store.item(url)
    assert it["state"] == "not_recovered"
    assert it["level"] == {"L1": "L2", "L2": "L3", "L3": "L3"}[level_before]
    assert any("Escalated" in c[1] for c in notion.comments)


def test_calibration_matrix(cfg, store, tmp_path):
    rows = [row("kw a", "a", now=None), row("kw b", "b", now=None)]
    res = run(cfg, store, Clients(ahrefs=FakeAhrefs(rows), fetcher=FakeFetcher()), "2026-10-08", "2026-08-12")
    labels = tmp_path / "slipped__pages.json"
    labels.write_text(json.dumps({"pages": [
        {"url": BASE + "a/", "level": store.item(BASE + "a/")["level"], "why": "same"},
        {"url": BASE + "b", "level": "NOSEO", "why": "tracker said no"},
        {"url": BASE + "c/", "level": "L1", "why": "missing"},
    ]}))
    out = cal.compare(store, res.run_ids, cal.load_labels(str(labels)))
    assert out["overlap"] == 2 and out["overlap_pct"] == 66.7
    assert out["agreement_pct"] == 50.0 and len(out["disagreements"]) == 1
    assert out["missing"] == [BASE + "c/"]
    text = cal.format_result(out)
    assert "Confusion matrix" in text and "tracker said no" in text


def test_norm_level():
    assert cal.norm_level("L2 Standard refresh") == "L2"
    assert cal.norm_level("no-seo") == "NOSEO"
    assert cal.norm_level(3) == "L3"


def test_not_recovered_page_is_reproposed_inside_hold_window(cfg, store):
    test_update_detected_then_not_recovered_escalates(cfg, store)
    url = BASE + "wall-pilates/"
    escalated = store.item(url)["level"]
    rows = [row("wall pilates routine", "wall-pilates", was=2, now=None, t_prev=400, t_now=0)]
    fetch = FakeFetcher({url: page_html(updated="October 15, 2026")})  # 35 days old: inside the 42-day hold
    run(cfg, store, Clients(ahrefs=FakeAhrefs(rows), fetcher=fetch), "2026-11-18", None)
    it = store.item(url)
    assert it["level"] == escalated and it["state"] == "proposed"
    assert it["why"].startswith(f"Not recovered 4 weeks after the update; escalated to {escalated}.")
