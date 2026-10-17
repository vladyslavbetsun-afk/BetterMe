"""Thresholds, dates, caps and env loading (spec §2, §4, §7, §8).

Every number the rules use lives in DEFAULTS. A run can override any of them
through the `settings` table (key -> JSON value) or `python -m decay settings set`.
Option A and Option B differ only here and in storage.py.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict = {
    # §3 detection
    "countries": ["us"],
    "target": "betterme.world/articles/",
    "compare_days": 28,
    # Ahrefs v3 has no offset for organic-keywords, so this is one page, ordered by traffic_prev.
    # Observed 2026-10-17: 55 units/row for DETECT_SELECT, 18 units/row for the AI Overview query.
    # 400 x 55 + 100 x 18 = 23,800 < the 25,000 guard. The spec's 1000 rows would always trip it (D-02).
    "max_rows": 400,
    "aio_max_rows": 100,
    "units_per_row": 55,
    "aio_units_per_row": 18,
    "max_units_per_run": 25_000,
    "api_volume_floor": 20,
    # §4 noise filters
    "min_volume": 50,
    "min_volume_core": 20,
    "core_topics": {
        "Wall Pilates": ["wall pilates", "wall-pilates"],
        "Chair Yoga": ["chair yoga", "chair-yoga"],
        "Calisthenics": ["calisthenics"],
        "Meal Plans": ["meal plan", "meal-plan"],
        "Fasting": ["fasting", "intermittent fasting", "intermittent-fasting"],
    },
    "min_traffic_lost": 5,
    "wobble_min_traffic_lost": 20,
    # §4 confirmation
    "confirm_runs": 2,
    "severe_page_traffic_lost": 200,
    "gsc_drop_pct": 15,
    # §7 decision table
    "hold_recent_days": 42,
    "recent_ticket_days": 60,
    "cannibalization_max_rank": 3,
    "claim_caution_categories": [3, 9, 17, 18],
    "l3_main_now": 10,
    "l3_lost_top3": 4,
    "l2_age_days": 365,
    "l2_competitor_ratio": 0.7,
    "l2_lost_top3": 2,
    "l2_worst_now": 7,
    "l1_worst_now": 6,
    "l1_min_faq": 4,
    "l10_range": [4, 10],
    "direct_answer_min_words": 40,
    "direct_answer_max_words": 60,
    "target_faq": 6,
    "numeric_terms": ["calories", "calorie", "steps", "minutes", "reps", "sets", "grams", "macros", "kcal"],
    # §8 priority
    "install_weights": {"HIGH": 1.5, "MEDIUM": 1.0, "LOW": 0.6},
    "core_topic_weight": 1.3,
    "confidence": {"confirmed": 1.0, "watch": 0.5, "gsc_down": 1.2, "gsc_flat": 0.7},
    "effort_factor": {"L0": 1.0, "L1": 1.2, "L2": 1.0, "L3": 0.7, "NOSEO": 0.0},
    "weekly_card_cap": 15,
    "auto_create": False,
    "resuggest_after_days": 180,
    # §6 audit
    "competitor_check": True,
    "competitor_top_n": 5,
    "fetch_delay_sec": 1.0,
    "user_agent": "BP-Ops-DecayRadar/1.0 (+https://betterme.world)",
    "http_timeout": 20,
    "llm_screen": False,
    "llm_model": "claude-haiku-5-5",
    "rules_version": "2026-08-28",
    # §10 Notion
    "notion_data_source_id": "1e997cc2-2a80-8086-a8ea-000bcc1073a4",
    "notion_category_properties": ["Primary category", "Blog Category"],
    "card_name_format": "{kw}, update",
    "choose_primary_week_top": 0,
    # §11 follow-up
    "followup_days": [14, 28],
    "recovered_position": 3,
    "recovered_traffic_pct": 70,
    # Jira (read-only)
    "jira_project": "BP",
    "jira_published_status": "Published",
}

LEVEL_NAMES = {
    "L0": "Hold",
    "L1": "Targeted fix",
    "L2": "Standard refresh",
    "L3": "Full rewrite",
    "NOSEO": "No SEO work",
}

# Scope text per level. 00-shared-reference.md §6.6 is the source of truth; these
# lines are stand-ins until it is pasted in verbatim (docs/decisions.md D-05).
LEVEL_SCOPE = {
    "L0": "No edit this week. Recheck on the date in the reason.",
    "L1": "Targeted fix: answer-first edits to the existing text. No restructure, no new sections beyond Key Takeaways and FAQs.",
    "L2": "Standard refresh: update facts and sources, close structure gaps, align title/H1 with the main keyword. Same URL.",
    "L3": "Full rewrite: writer + expert + Legal, rebuilt to the model shape on the same URL.",
    "NOSEO": "No SEO work. Touch only for a Legal compliance fix.",
}

BANNED_WORDS = ["best", "personalized", "personalised"]


@dataclass
class Config:
    settings: dict = field(default_factory=lambda: copy.deepcopy(DEFAULTS))
    today: date = field(default_factory=date.today)
    db_path: Path = field(default_factory=lambda: ROOT / "decay.db")
    database_url: str | None = None
    ahrefs_api_key: str | None = None
    notion_token: str | None = None
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    anthropic_api_key: str | None = None
    mode: str = "local"  # "local" (Option A) or "bpops" (Option B)

    def __getitem__(self, key):
        return self.settings[key]

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def apply_overrides(self, overrides: dict) -> None:
        for k, v in overrides.items():
            self.settings[k] = v
        if self.mode == "bpops":
            # The slop machine blocks undeclared outbound hosts (spec §2).
            self.settings["competitor_check"] = False

    # Dates (§3)
    def report_date(self, explicit: str | None = None) -> date:
        return date.fromisoformat(explicit) if explicit else self.today - timedelta(days=1)

    def compare_date(self, report_date: date, explicit: str | None = None) -> date:
        return date.fromisoformat(explicit) if explicit else report_date - timedelta(days=self["compare_days"])


def load_dotenv_file(path: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is in requirements
        return
    load_dotenv(path, override=False)


def load_config(env_file: Path | None = None, today: date | None = None) -> Config:
    load_dotenv_file(env_file or ROOT / ".env")
    cfg = Config(
        today=today or date.today(),
        db_path=Path(os.environ.get("DECAY_DB", ROOT / "decay.db")),
        database_url=os.environ.get("DATABASE_URL") or None,
        ahrefs_api_key=os.environ.get("AHREFS_API_KEY") or None,
        notion_token=os.environ.get("NOTION_TOKEN") or None,
        jira_base_url=os.environ.get("JIRA_BASE_URL") or None,
        jira_email=os.environ.get("JIRA_EMAIL") or None,
        jira_api_token=os.environ.get("JIRA_API_TOKEN") or None,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        mode=os.environ.get("DECAY_MODE", "local"),
    )
    env_overrides = os.environ.get("DECAY_SETTINGS_JSON")
    if env_overrides:
        cfg.apply_overrides(json.loads(env_overrides))
    else:
        cfg.apply_overrides({})
    return cfg
