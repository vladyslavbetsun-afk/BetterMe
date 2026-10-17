"""§8 priority score and install-intent rating (rules from `betterme-keyword-research` §4)."""
from __future__ import annotations

import re

HIGH_PATTERNS = re.compile(
    r"\b(workout plan|workout program|program|plan|challenge|meal plan|for beginners|beginner|app|routine|schedule|"
    r"how to start|day \d+|\d+[- ]day)\b", re.I)
LOW_PATTERNS = re.compile(
    r"^(what is|what are|what does|does|do|is it true|can you)\b|\bdoes .+ work\b|\bhow many calories\b|\bcalories in\b|"
    r"\bwhich muscles?\b|\bwhat muscles?\b|\bmeaning\b|\bdefinition\b", re.I)
MEDIUM_PATTERNS = re.compile(r"\bbenefits?\b|^is .+ (safe|good|bad|healthy)\b|\bpros and cons\b|\bvs\b|\bside effects\b", re.I)


def install_intent(keyword: str, commercial: bool = False, transactional: bool = False) -> str:
    kw = keyword.strip().lower()
    if LOW_PATTERNS.search(kw) and not HIGH_PATTERNS.search(kw):
        return "LOW"
    if HIGH_PATTERNS.search(kw) or commercial or transactional:
        return "HIGH"
    if MEDIUM_PATTERNS.search(kw):
        return "MEDIUM"
    return "MEDIUM"


def confidence(cfg, confirmed: bool, gsc_change_pct: float | None) -> tuple[float, str | None]:
    c = cfg["confidence"]
    value = c["confirmed"] if confirmed else c["watch"]
    note = None
    if gsc_change_pct is not None:
        if gsc_change_pct <= -cfg["gsc_drop_pct"]:
            value *= c["gsc_down"]
        elif gsc_change_pct >= 0 or gsc_change_pct > -cfg["gsc_drop_pct"] / 3:
            value *= c["gsc_flat"]
            note = "Ahrefs shows a drop, GSC clicks stable"
    return value, note


def priority(cfg, traffic_lost: int, intent: str, core: bool, conf: float, level: str) -> float:
    return round(
        traffic_lost
        * cfg["install_weights"][intent]
        * (cfg["core_topic_weight"] if core else 1.0)
        * conf
        * cfg["effort_factor"].get(level, 1.0),
        2,
    )
