from decay.aggregate import aggregate, normalize_url
from decay.detect import classify_row, detect

from .conftest import BASE, row


def test_normalize_url_variants():
    want = "https://betterme.world/articles/wall-pilates/"
    assert normalize_url("https://betterme.world/articles/wall-pilates/") == want
    assert normalize_url("https://BetterMe.World/articles/wall-pilates") == want
    assert normalize_url("https://betterme.world/articles/wall-pilates/?utm=x#faq") == want
    assert normalize_url("betterme.world/articles/wall-pilates") == want
    assert normalize_url("https://www.betterme.world/articles/wall-pilates/") == "https://www.betterme.world/articles/wall-pilates/"


def test_normalize_url_rejects_non_articles():
    assert normalize_url("https://betterme.world/blog/fitness/") is None
    assert normalize_url("https://store.betterme.world/articles/x/") is None
    assert normalize_url("https://betterme.world/articles/a/b/") is None
    assert normalize_url("https://example.com/articles/x/") is None
    assert normalize_url(None) is None
    assert normalize_url("https://betterme.world/", articles_only=False) == "https://betterme.world/"


def test_wobble_3_to_4_is_ignored_unless_traffic_lost_is_large(cfg):
    sig, reason = classify_row(cfg, row("kw a", "a", was=3, now=4, t_prev=40, t_now=30))
    assert sig is None and reason == "wobble_3_to_4"
    sig, _ = classify_row(cfg, row("kw a", "a", was=3, now=4, t_prev=60, t_now=30))
    assert sig is not None and sig.kind == "dropped"
    # 2 -> 4 is not a wobble
    sig, _ = classify_row(cfg, row("kw a", "a", was=2, now=4, t_prev=40, t_now=30))
    assert sig is not None


def test_cannibalization_flag_when_another_betterme_url_ranks(cfg):
    sig, _ = classify_row(cfg, row("kw", "old-page", was=1, now=5, url_now=BASE + "new-page/"))
    assert sig.kind == "swapped" and sig.swapped_to == BASE + "new-page/"
    sig, _ = classify_row(cfg, row("kw", "old-page", was=1, now=5, url_now="https://betterme.world/"))
    assert sig.kind == "swapped" and sig.swapped_to == "https://betterme.world/"
    sig, _ = classify_row(cfg, row("kw", "old-page", was=1, now=5))
    assert sig.kind == "dropped" and sig.swapped_to is None


def test_lost_entirely_passes_even_with_tiny_traffic(cfg):
    sig, _ = classify_row(cfg, row("kw", "a", was=2, now=None, t_prev=3, t_now=0))
    assert sig.kind == "lost" and sig.now is None and sig.traffic_lost == 3


def test_volume_floor_core_topic_vs_other(cfg):
    assert classify_row(cfg, row("wall pilates for men", "wall-pilates-men", vol=25))[0] is not None
    assert classify_row(cfg, row("ab workouts", "ab-workouts", vol=25))[1] == "low_volume"
    assert classify_row(cfg, row("ab workouts", "ab-workouts", vol=50))[0] is not None


def test_noise_filters(cfg):
    assert classify_row(cfg, row("kw", "a", t_prev=10, t_now=8))[1] == "low_traffic_lost"
    assert classify_row(cfg, row("betterme app", "a", is_navigational=True))[1] == "navigational"
    r = row("kw", "a")
    r["best_position_url_prev"] = "https://betterme.world/blog/fitness/"
    assert classify_row(cfg, r)[1] == "not_article"


def test_aio_flags(cfg):
    sig, _ = classify_row(cfg, row("kw", "a", serp_features=["ai_overview"], serp_features_prev=[],
                                   positions_kinds=["organic"], positions_kinds_prev=["organic", "ai_overview_found"]))
    assert sig.aio_appeared and sig.aio_citation_lost


def test_rollup(cfg):
    signals, dropped = detect(cfg, [
        row("wall pilates", "wall-pilates", was=1, now=6, vol=5000, t_prev=900, t_now=200),
        row("wall pilates for beginners", "wall-pilates", was=2, now=None, vol=800, t_prev=100, t_now=0),
        row("kw", "other", t_prev=10, t_now=9),
    ])
    assert dropped == {"low_traffic_lost": 1}
    page = aggregate(signals)[BASE + "wall-pilates/"]
    assert page.main_keyword == "wall pilates"
    assert page.lost_top3_count == 2 and page.lost_entirely_count == 1
    assert page.traffic_lost == 800
    assert page.worst_now is None  # one keyword lost entirely
    assert page.core_topic == "Wall Pilates"


def test_aio_citation_lost_from_filter_query(cfg):
    rows = [row("wall pilates", "wall-pilates", was=2, now=6), row("chair yoga", "chair-yoga", was=1, now=None)]
    aio_rows = [{"keyword": None, "keyword_prev": "chair yoga", "best_position_url_prev": BASE + "chair-yoga/"}]
    signals, _ = detect(cfg, rows, aio_rows)
    by_kw = {s.keyword: s for s in signals}
    assert by_kw["chair yoga"].aio_citation_lost and not by_kw["wall pilates"].aio_citation_lost
    assert by_kw["chair yoga"].volume == 1000  # taken from volume_prev on a lost row


def test_unit_estimate_and_guard(cfg):
    import pytest
    from decay import ahrefs as ah
    assert ah.estimate_units(cfg) == 400 * 55 + 100 * 18 <= cfg["max_units_per_run"]
    assert ah.estimate_units(cfg, calls=2) > cfg["max_units_per_run"]
    with pytest.raises(ah.UnitBudgetExceeded):
        ah.guard_units(ah.estimate_units(cfg, calls=2), cfg["max_units_per_run"])


def test_detect_params_match_live_schema(cfg):
    from decay import ahrefs as ah
    p = ah.detect_params(cfg, "us", "2026-10-16", "2026-09-18")
    assert "positions_kinds" not in p["select"] and "keyword_prev" in p["select"] and "is_navigational" in p["select"]
    assert p["mode"] == "prefix" and p["order_by"] == "sum_traffic_prev:desc"
    a = ah.aio_params(cfg, "us", "2026-10-16", "2026-09-18")
    assert "list_is" in a["where"] and a["select"] == "keyword,keyword_prev,best_position_url_prev"
