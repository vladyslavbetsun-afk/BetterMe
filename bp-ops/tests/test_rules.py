from datetime import date, datetime
from decimal import Decimal

import config
from conftest import NOW
from core import business_days as bd
from core import rules
from core.rules import Price, Rate


def test_category_examples():
    assert rules.detect_category("wall pilates workout for beginners, 1800 words") == "fitness"
    assert rules.detect_category("high protein snacks for weight loss, 1600 words") == "nutrition"
    assert rules.detect_category("are bananas good for you, 1500 words") == "nutrition"
    assert rules.detect_category("how to lose weight, 1800 words") is None  # unclear: a human decides
    # both sides hit: one side must lead by more than one
    assert rules.detect_category("eating before a workout") is None
    assert rules.detect_category("best workout exercises for abs after eating") == "fitness"
    # punctuation is replaced by spaces; whole words only
    assert rules.detect_category("push-up variations") == "fitness"
    assert rules.detect_category("teacher pilates") == "fitness"  # 'tea' doesn't match inside 'teacher'


def test_word_count():
    assert rules.word_count("BP-1595 best muscle group combinations, 1800 words, update") == (1800, 1800)
    assert rules.word_count("x, 1,600–1,900 words") == (1600, 1900)
    assert rules.word_count("x, 1600-1900 words") == (1600, 1900)
    assert rules.word_count("x, 2000 word") == (2000, 2000)
    assert rules.word_count("active recovery day workout, 12k") is None  # never read 12k as words
    assert rules.word_count("no count here") is None


def test_update_and_short_title():
    assert rules.is_update("best muscle group combinations, 1800 words, update")
    assert not rules.is_update("updated guide to squats, 1800 words")
    assert rules.short_title("best muscle group combinations, 1800 words, update") == "best muscle group combinations"


def test_prices():
    eve = Rate(Decimal("0.035"), "word")
    assert rules.writer_price(eve, (1800, 1800)) == Price(Decimal(63), Decimal(63))
    assert rules.writer_price(eve, None) is None  # per-word with no count: unpriced
    brenda = Rate(Decimal(100), "article", Decimal(120))
    assert rules.writer_price(brenda, None) == Price(Decimal(100), Decimal(120))
    assert rules.open_ticket_expert_estimate("fitness", False) == Price(Decimal(50), Decimal(50))
    assert rules.open_ticket_expert_estimate("nutrition", False) == Price(Decimal(20), Decimal(50))
    assert rules.open_ticket_expert_estimate("fitness", True) == rules.ZERO
    assert rules.money(Price(Decimal(63), Decimal(63))) == "$63"
    assert rules.money(Price(Decimal(100), Decimal(120))) == "$100–120"


def test_links():
    assert rules.urls_in("see https://docs.google.com/document/d/abc/edit. thanks") == [
        "https://docs.google.com/document/d/abc/edit"]
    assert rules.is_image_link("https://www.figma.com/file/x")
    assert not rules.is_image_link("https://betterme.world/articles/x/")
    assert not rules.is_image_link("https://docs.google.com/document/d/abc")


def test_banned_words():
    assert rules.banned_words("The Best Personalized Plan") == ["best", "personalized"]
    assert rules.banned_words("Chair Yoga for Seniors") == []


def test_business_days():
    fri = NOW  # Fri 15:00
    mon = datetime(2026, 10, 19, 15, 0, tzinfo=config.TZ)
    assert abs(bd.elapsed(fri, mon) - 1.0) < 1e-9  # the weekend doesn't count
    assert bd.elapsed(mon, fri) == 0
    assert bd.add_business_days(date(2026, 10, 16), 1) == date(2026, 10, 19)
    assert bd.add_business_days(date(2026, 10, 16), 1, ["2026-10-19"]) == date(2026, 10, 20)
    assert bd.business_days_between(date(2026, 10, 16), date(2026, 10, 23)) == 5
    nxt = bd.next_weekday_at(NOW)
    assert (nxt.date(), nxt.hour) == (date(2026, 10, 19), 9)
