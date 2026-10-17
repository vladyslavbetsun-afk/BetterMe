"""Business rules from docs/specs/00-shared-reference.md §6. Pure functions, unit-tested in tests/test_rules.py."""

import re
from dataclasses import dataclass
from decimal import Decimal

# --- 6.1 Category detection -------------------------------------------------------------------
FIT_KW = ["workout", "exercise", "exercises", "yoga", "squat", "squats", "pilates", "push up", "push-up", "pushup",
          "pull up", "pull-up", "pullup", "plank", "cardio", "abs", "stretch", "stretches", "stretching", "walking",
          "walk", "running", "run", "hiit", "calisthenics", "strength", "muscle", "muscles", "glute", "glutes",
          "lunge", "lunges", "burpee", "deadlift", "gym", "fitness", "training", "core", "dumbbell", "kettlebell",
          "jump", "steps", "posture", "mobility", "flexibility", "somatic", "barre", "tai chi", "treadmill",
          "cycling", "swimming", "body composition", "toning", "tone", "arm", "arms", "leg", "legs", "belly fat",
          "reps", "sets", "warm up", "cool down", "swings", "endurance", "miles"]
NUT_KW = ["diet", "diets", "meal", "meals", "snack", "snacks", "drink", "drinks", "food", "foods", "recipe",
          "recipes", "calorie", "calories", "protein", "carb", "carbs", "keto", "fasting", "eat", "eating",
          "nutrition", "nutrient", "vitamin", "vitamins", "fruit", "fruits", "vegetable", "vegetables", "smoothie",
          "smoothies", "juice", "tea", "coffee", "sugar", "breakfast", "lunch", "dinner", "good for you",
          "healthy fats", "fiber", "cheese", "bread", "rice", "pasta", "pepperoni", "egg", "eggs", "oatmeal",
          "yogurt", "supplement", "supplements", "hydration", "water", "alcohol", "wine", "beer", "sauce", "salad",
          "soup", "nuts", "chocolate", "milk", "grocery", "menu", "dessert", "bars", "shake", "shakes", "dieta",
          "calorias", "macronutrients", "whiskey", "banana", "bananas", "cucumber", "carrot", "broccoli"]


def _hits(title: str) -> tuple[int, int]:
    t = " " + re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s-]", " ", str(title or "").lower())) + " "
    f = sum(1 for kw in FIT_KW if f" {kw} " in t)
    n = sum(1 for kw in NUT_KW if f" {kw} " in t)
    return f, n


def detect_category(title: str) -> str | None:
    """'fitness', 'nutrition' or None (unclear: a human decides).

    Hits on one side only decide it (as the legacy Review Flow does). With hits on both sides one side must lead by
    more than one (00 §6.1). See docs/decisions.md D-07 for why one-sided hits are not "unclear".
    """
    f, n = _hits(title)
    if f and not n:
        return "fitness"
    if n and not f:
        return "nutrition"
    if f > n + 1:
        return "fitness"
    if n > f + 1:
        return "nutrition"
    return None


# --- 6.2 Word count from the summary -------------------------------------------------------------
RANGE_RE = re.compile(r"(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)\s*words?", re.I)
SINGLE_RE = re.compile(r"(\d[\d,]*)\s*words?\b", re.I)


def word_count(summary: str) -> tuple[int, int] | None:
    """(min, max) words, or None when the ticket is unpriced. '12k' is never read as words (00 §1, VERIFY)."""
    s = str(summary or "")
    m = RANGE_RE.search(s)
    if m:
        return int(m.group(1).replace(",", "")), int(m.group(2).replace(",", ""))
    m = SINGLE_RE.search(s)
    if m:
        n = int(m.group(1).replace(",", ""))
        return n, n
    return None


def is_update(summary: str) -> bool:
    return bool(re.search(r",\s*update\b", str(summary or ""), re.I))


def short_title(summary: str) -> str:
    """Summary up to the first comma (legacy shortTitle)."""
    return str(summary or "").split(",")[0].strip()


# --- 6.3 Price ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Rate:
    amount: Decimal
    unit: str  # word | article | hour | month
    amount_max: Decimal | None = None


@dataclass(frozen=True)
class Price:
    lo: Decimal
    hi: Decimal

    def __add__(self, other: "Price") -> "Price":
        return Price(self.lo + other.lo, self.hi + other.hi)


ZERO = Price(Decimal(0), Decimal(0))


def writer_price(rate: Rate | None, words: tuple[int, int] | None) -> Price | None:
    """Writer fee for one article. None when it can't be priced (no rate, or per-word with no word count)."""
    if rate is None:
        return None
    if rate.unit == "article":
        return Price(Decimal(rate.amount), Decimal(rate.amount_max if rate.amount_max is not None else rate.amount))
    if rate.unit == "word":
        if not words:
            return None
        a = Decimal(rate.amount)
        return Price(Decimal(round(words[0] * a)), Decimal(round(words[1] * a)))
    return None


def expert_fee(rate: Rate | None, words: tuple[int, int] | None = None) -> Price | None:
    """Expert review fee for one article (per article, or per word for word-rated experts)."""
    if rate is None:
        return None
    if rate.unit == "article":
        return Price(Decimal(rate.amount), Decimal(rate.amount))
    if rate.unit == "word" and words:
        return writer_price(rate, words)
    return None


def open_ticket_expert_estimate(category: str | None, skip_expert_review: bool) -> Price:
    """No expert yet: fitness +$50; nutrition (or unclear) +$20–50 (00 §6.3)."""
    if skip_expert_review:
        return ZERO
    if category == "fitness":
        return Price(Decimal(50), Decimal(50))
    return Price(Decimal(20), Decimal(50))


def money(p: Price | None) -> str:
    if p is None:
        return "—"

    def f(x: Decimal) -> str:
        return f"${round(x):,}"

    return f(p.lo) if round(p.lo) == round(p.hi) else f"{f(p.lo)}–{round(p.hi):,}"


# --- 6.4 Comments --------------------------------------------------------------------------------------
NOTE_RE = re.compile(r"please address", re.I)
CHASE_WRITER_RE = re.compile(r"any news on the edits", re.I)
CHASE_EXPERT_RE = re.compile(r"any news on the ticket", re.I)
DOC_RE = re.compile(r"^https://docs\.google\.com/document/", re.I)
LIVE_RE = re.compile(r"^https?://(www\.)?betterme\.world/", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"'\])|]+")

NOTE_TEXT = "Hi. Please address the comments. Thanks."
CHASE_WRITER_TEXT = "Hi. Any news on the edits?"
CHASE_EXPERT_TEXT = "Hi. Any news on the ticket?"
STATUS_TEXT = "Hi. What's the status on this one?"


def urls_in(text: str) -> list[str]:
    out: list[str] = []
    for m in URL_RE.finditer(str(text or "")):
        u = re.sub(r"[.,;:!?)]+$", "", m.group(0))
        if u not in out:
            out.append(u)
    return out


def is_image_link(url: str) -> bool:
    """An image delivery link (00 §6.5, spec 03 §4): not a live betterme.world page, not a Google Doc, not Jira."""
    return not (LIVE_RE.match(url) or DOC_RE.match(url) or re.search(r"atlassian\.net", url, re.I))


# --- 6.7 Editorial / compliance ------------------------------------------------------------------------
BANNED_WORDS_RE = re.compile(r"\b(best|personalized|personalised|guaranteed|#1|headspace)\b", re.I)


def banned_words(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in BANNED_WORDS_RE.finditer(str(text or ""))})


def first_name(name: str) -> str:
    n = re.split(r"[\s.]+", str(name or "").strip())[0]
    return n[:1].upper() + n[1:].lower() if n else "there"
