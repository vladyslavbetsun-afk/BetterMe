"""One test per §7 decision-table row, plus generated-text hygiene."""
import re

import pytest

from decay.audit import Audit
from decay.config import BANNED_WORDS
from decay.level import Context, assign_level
from decay.screen import screen_text

from .conftest import BASE, TODAY

URL = BASE + "wall-pilates/"


def page(**over):
    p = {
        "url": URL, "slug": "wall-pilates", "main_keyword": "wall pilates workout", "main_was": 2, "main_now": 5,
        "worst_now": 5, "lost_top3_count": 1, "lost_entirely_count": 0, "traffic_lost": 300,
        "lost_keywords": [{"kw": "wall pilates workout", "vol": 2000, "was": 2, "now": 5, "traffic_prev": 400,
                           "traffic_now": 100, "kind": "dropped"}],
        "aio_appeared": False, "aio_citation_lost": False, "swapped_to": None, "swapped_rank": None,
        "intent_mix": 0.0, "core_topic": "Wall Pilates", "cluster": "Wall Pilates",
    }
    p.update(over)
    return p


def audit(**over):
    a = Audit(url=URL, http_status=200, final_url=URL, title="Wall Pilates Workout Guide", h1="Wall Pilates Workout Guide",
              updated_on="2026-03-01", age_days=200, word_count=1800, has_key_takeaways=True, faq_count=6,
              question_h2_count=2, question_h2_with_direct_answer=2, table_count=1)
    for k, v in over.items():
        setattr(a, k, v)
    return a


def decide(cfg, p=None, a=None, screen_on="", **ctx):
    c = Context(page=p or page(), audit=a or audit(), screen=screen_text(screen_on), today=TODAY,
                confirmed=ctx.pop("confirmed", True), **ctx)
    return assign_level(cfg, c)


def test_rule1_reject_is_noseo(cfg):
    r = decide(cfg, screen_on="dry fasting for 3 days")
    assert (r.level, r.rule) == ("NOSEO", 1)
    assert "#17" in r.why and "Dangerous practice" in r.why


def test_rule1_redirect_is_noseo(cfg):
    r = decide(cfg, a=audit(merged=True, final_url=BASE + "other/"))
    assert (r.level, r.rule, r.tag) == ("NOSEO", 1, "merged")
    assert any("Check redirect" in c for c in r.checklist)


def test_rule2_in_pipeline(cfg):
    r = decide(cfg, open_ticket="BP-1234")
    assert (r.level, r.rule, r.tag) == ("L0", 2, "in_pipeline") and "BP-1234" in r.why
    r = decide(cfg, open_card="https://www.notion.so/abc")
    assert r.tag == "in_pipeline"


def test_rule3_recently_updated(cfg):
    r = decide(cfg, a=audit(age_days=20))
    assert (r.level, r.rule) == ("L0", 3) and "Updated 20 days ago" in r.why
    r = decide(cfg, recent_ticket="BP-99", recent_ticket_days_ago=30)
    assert (r.level, r.rule) == ("L0", 3) and "BP-99" in r.why


def test_rule4_watch(cfg):
    r = decide(cfg, confirmed=False)
    assert (r.level, r.rule, r.tag) == ("L0", 4, "watch")


def test_rule5_cannibalization(cfg):
    r = decide(cfg, p=page(swapped_to=BASE + "wall-pilates-challenge/", swapped_rank=2, swapped_keyword="wall pilates"))
    assert (r.level, r.rule, r.tag) == ("L0", 5, "cannibalization")
    r = decide(cfg, p=page(swapped_to=BASE + "x/", swapped_rank=6))
    assert r.rule != 5


def test_rule6_claims(cfg):
    r = decide(cfg, a=audit(claim_flags=["timeline claim"]))
    assert (r.level, r.rule) == ("L3", 6)
    r = decide(cfg, screen_on="how to lose belly fat with pilates")  # pattern #18 CAUTION
    assert (r.level, r.rule) == ("L3", 6) and "#18" in r.why
    assert any(c.startswith("Remove claims") for c in r.checklist)


def test_rule7_main_keyword_collapsed(cfg):
    r = decide(cfg, p=page(main_now=14, worst_now=14))
    assert (r.level, r.rule) == ("L3", 7) and "#2 to #14" in r.why
    r = decide(cfg, p=page(main_now=None, worst_now=None))
    assert (r.level, r.rule) == ("L3", 7)
    r = decide(cfg, p=page(lost_top3_count=4))
    assert (r.level, r.rule) == ("L3", 7)


def test_rule8_stale_thin_tables_spread(cfg):
    assert decide(cfg, a=audit(age_days=400)).rule == 8
    r = decide(cfg, a=audit(word_count=1000, median_competitor_words=2000))
    assert (r.level, r.rule) == ("L2", 8) and "1000 words vs competitor median 2000" in r.why
    p = page(main_keyword="how many calories does walking burn",
             lost_keywords=[{"kw": "how many calories does walking burn", "vol": 900, "was": 1, "now": 5,
                             "traffic_prev": 100, "traffic_now": 20, "kind": "dropped"}])
    r = decide(cfg, p=p, a=audit(table_count=0))
    assert r.rule == 8 and "calories" in r.why
    r = decide(cfg, p=page(lost_top3_count=2, worst_now=8))
    assert (r.level, r.rule) == ("L2", 8) and "2 keywords slipped to #8" in r.why


def test_rule9_answer_first_gaps(cfg):
    r = decide(cfg, a=audit(has_key_takeaways=False, faq_count=2))
    assert (r.level, r.rule) == ("L1", 9)
    assert "Add Key Takeaways after the intro" in r.checklist
    assert "Add 4 FAQs from live People Also Ask for 'wall pilates workout'" in r.checklist
    r = decide(cfg, p=page(aio_appeared=True, worst_now=9, main_now=9))
    assert (r.level, r.rule) == ("L1", 9) and "AI Overview appeared" in r.why


def test_rule10_complete_structure(cfg):
    r = decide(cfg)
    assert (r.level, r.rule) == ("L2", 10) and "despite a complete structure" in r.why


def test_first_match_wins(cfg):
    # rejection beats an open ticket; open ticket beats a recent update
    assert decide(cfg, screen_on="dry fasting", open_ticket="BP-1").level == "NOSEO"
    assert decide(cfg, a=audit(age_days=5), open_ticket="BP-1").rule == 2


def test_every_result_has_why_and_checklist(cfg):
    variants = [dict(screen_on="dry fasting"), dict(open_ticket="BP-1"), dict(a=audit(age_days=1)),
                dict(confirmed=False), dict(a=audit(claim_flags=["guarantee"])), dict(p=page(main_now=30)),
                dict(a=audit(age_days=500)), dict(a=audit(faq_count=0)), {}]
    for v in variants:
        r = decide(cfg, **v)
        assert r.why.strip() and r.checklist and all(c.strip() for c in r.checklist)


def test_generated_text_has_no_banned_words(cfg):
    """Templates must not say 'best' / 'personalized' (only quoted titles/keywords may)."""
    neutral_page = page(main_keyword="wall pilates routine")
    neutral_audit = audit(title="Wall Pilates Routine", h1="Wall Pilates Routine")
    variants = [dict(screen_on="dry fasting"), dict(open_ticket="BP-1"), dict(a=audit(age_days=1)),
                dict(confirmed=False), dict(a=audit(claim_flags=["guarantee"])), dict(p=page(main_now=30)),
                dict(a=audit(age_days=500, faq_count=1, has_key_takeaways=False, images_missing_alt=3,
                             question_h2_missing_answer=["Is it hard?"], title="Wall Pilates Routine")),
                dict(a=audit(faq_count=0)), {}]
    rx = re.compile(r"\b(" + "|".join(BANNED_WORDS) + r")\b", re.I)
    for v in variants:
        v.setdefault("p", neutral_page)
        v.setdefault("a", neutral_audit)
        r = decide(cfg, **v)
        for text in [r.why, *r.checklist]:
            assert not rx.search(text), text


@pytest.mark.parametrize("text,verdict,cat", [
    ("wall pilates for beginners", "PASS", None),
    ("dry fasting benefits", "REJECT", 17),
    ("pilates during pregnancy", "CAUTION", 9),
    ("menopause workout plan", "CAUTION", 3),
    ("how to slim your thighs", "CAUTION", 18),
    ("skipping dinner for weight loss", "REJECT", 21),
    ("bed mobility exercises for elderly", "REJECT", 22),
    ("bed pilates", "PASS", None),
])
def test_screen(text, verdict, cat):
    res = screen_text(text)
    assert res.verdict == verdict
    if cat:
        assert cat in res.categories()
