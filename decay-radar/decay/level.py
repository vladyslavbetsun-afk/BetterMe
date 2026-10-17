"""§7 deterministic decision table -> level + why + checklist.

Rules are evaluated top to bottom and the first match wins. Every number comes
from config; calibration may tune thresholds, never the rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import LEVEL_NAMES, LEVEL_SCOPE

LOST = 101  # sort key for "lost entirely" when comparing positions


@dataclass
class Context:
    """Everything the table looks at for one page."""
    page: dict  # aggregate.Page.summary()
    audit: object  # audit.Audit
    screen: object  # screen.ScreenResult
    today: date
    confirmed: bool = False
    open_ticket: str | None = None  # BP key
    open_card: str | None = None  # Notion URL
    recent_ticket: str | None = None  # BP key published within recent_ticket_days
    recent_ticket_days_ago: int | None = None
    cluster: str | None = None  # category leaf / core topic for the internal-link item


@dataclass
class LevelResult:
    level: str
    rule: int
    tag: str | None
    why: str
    checklist: list = field(default_factory=list)

    @property
    def name(self) -> str:
        return LEVEL_NAMES[self.level]


def pos(p: int | None) -> str:
    return "lost (out of the top 100)" if p is None else f"#{p}"


def _p(p: int | None) -> int:
    return LOST if p is None else p


def numeric_terms(cfg, page: dict) -> list[str]:
    kws = " ".join(k["kw"].lower() for k in page["lost_keywords"])
    return [t for t in cfg["numeric_terms"] if t in kws.split() or f" {t}" in f" {kws}"]


def missing_structure(cfg, a) -> list[str]:
    missing = []
    if not a.has_key_takeaways:
        missing.append("Key Takeaways")
    if a.faq_count < cfg["l1_min_faq"]:
        missing.append(f"{cfg['l1_min_faq']}+ FAQs (has {a.faq_count})")
    if a.question_h2_count > a.question_h2_with_direct_answer:
        missing.append("direct answers under question H2s")
    return missing


def assign_level(cfg, ctx: Context) -> LevelResult:
    p, a, s = ctx.page, ctx.audit, ctx.screen
    kw = p["main_keyword"]

    # 1. NOSEO: rejection pattern, redirect/merge, or the page is gone
    reject = s.reject if s else None
    if reject:
        why = f"Topic hits rejection pattern #{reject.category} ({reject.name}). Touch only for a Legal compliance fix."
        return LevelResult("NOSEO", 1, "rejected", why, _checklist_noseo(a, reject))
    if a.http_status and (a.http_status in (404, 410) or a.merged):
        target = a.final_url if a.merged else f"HTTP {a.http_status}"
        why = (f"Page redirects to {target} (merged; rejection category n/a, redirect). Check the redirect. "
               "Touch only for a Legal compliance fix.") if a.merged else \
              f"Page returns {target} (rejection category n/a, page gone). Check the redirect. Touch only for a Legal compliance fix."
        return LevelResult("NOSEO", 1, "merged", why, _checklist_noseo(a, None))

    # 2. Already in the pipeline
    if ctx.open_ticket or ctx.open_card:
        ref = " / ".join(x for x in (ctx.open_ticket, ctx.open_card and f"Notion card {ctx.open_card}") if x)
        why = f"Already in the pipeline: {ref}. Recheck after it's published."
        return LevelResult("L0", 2, "in_pipeline", why, [LEVEL_SCOPE["L0"], f"Recheck after {ref} is published."])

    # 3. Recently updated
    recheck = (ctx.today + timedelta(days=28)).isoformat()
    if a.age_days is not None and a.age_days < cfg["hold_recent_days"]:
        why = f"Updated {a.age_days} days ago. Rankings need 4–6 weeks to settle. Recheck on {recheck}."
        return LevelResult("L0", 3, "recent", why, [LEVEL_SCOPE["L0"], f"Recheck on {recheck}."])
    if ctx.recent_ticket:
        why = (f"{ctx.recent_ticket} was published {ctx.recent_ticket_days_ago} days ago. "
               f"Rankings need 4–6 weeks to settle. Recheck on {recheck}.")
        return LevelResult("L0", 3, "recent", why, [LEVEL_SCOPE["L0"], f"Recheck on {recheck}."])

    # 4. Not confirmed yet
    if not ctx.confirmed:
        why = "First-week drop. Waiting for a second weekly confirmation."
        return LevelResult("L0", 4, "watch", why, [LEVEL_SCOPE["L0"], "Recheck after next Monday's run."])

    # 5. Cannibalization
    if p.get("swapped_to") and p.get("swapped_rank") is not None and p["swapped_rank"] <= cfg["cannibalization_max_rank"]:
        skw = p.get("swapped_keyword") or kw
        why = (f"Another BetterMe page ({p['swapped_to']}) now holds the top 3. "
               f"Decide which page owns '{skw}' before editing.")
        return LevelResult("L0", 5, "cannibalization", why, [
            LEVEL_SCOPE["L0"], f"Human decision: which page owns '{skw}' ({p['url']} or {p['swapped_to']}).",
        ])

    # 6. Claim risk
    claim_cats = [m for m in s.matches if m.verdict == "CAUTION" and m.category in cfg["claim_caution_categories"]] if s else []
    if a.claim_flags or claim_cats:
        flags = list(a.claim_flags) + [f"pattern #{m.category} {m.note}" for m in claim_cats]
        why = f"Contains claim risk ({', '.join(flags)}). Needs writer + expert + Legal and a rebuild to the model shape."
        return LevelResult("L3", 6, "claims", why, _checklist_l3(flags))

    # 7. Main keyword collapsed, or many top-3 losses
    main_now = p.get("main_now")
    if main_now is None or main_now > cfg["l3_main_now"] or p["lost_top3_count"] >= cfg["l3_lost_top3"]:
        why = (f"Main keyword fell from #{p.get('main_was')} to {pos(main_now)}. "
               "Multiple top-3 losses suggest the page no longer matches intent.") if p["lost_top3_count"] > 1 else \
              f"Main keyword fell from #{p.get('main_was')} to {pos(main_now)}. The page no longer matches intent."
        return LevelResult("L3", 7, "collapsed", why, _checklist_l3([]))

    # 8. Stale, thin, missing tables, or several keywords slipping far
    worst = p.get("worst_now")
    parts = []
    if a.age_days is not None and a.age_days > cfg["l2_age_days"]:
        parts.append(f"Last updated {a.age_days // 30} months ago")
    if a.median_competitor_words and a.word_count < cfg["l2_competitor_ratio"] * a.median_competitor_words:
        parts.append(f"{a.word_count} words vs competitor median {a.median_competitor_words}")
    nums = numeric_terms(cfg, p)
    if a.table_count == 0 and nums:
        parts.append(f"no table for a numeric topic ({', '.join(nums)})")
    if p["lost_top3_count"] >= cfg["l2_lost_top3"] and _p(worst) >= cfg["l2_worst_now"]:
        parts.append(f"{p['lost_top3_count']} keywords slipped to {pos(worst)}")
    if parts:
        why = f"{' / '.join(parts)}. Needs facts, sources, structure."
        return LevelResult("L2", 8, "stale", why, _checklist_l2(cfg, p, a, nums))

    # 9. Close to the top and missing answer-first structure, or AI Overview shift
    missing = missing_structure(cfg, a)
    aio = p.get("aio_appeared") or p.get("aio_citation_lost")
    if (worst is not None and worst <= cfg["l1_worst_now"] and missing) or aio:
        bits = [f"Slipped to {pos(worst)}"]
        if missing:
            bits.append(f"page missing {', '.join(missing)}")
        why = ", ".join(bits) + "."
        if aio:
            what = " and ".join(x for x, on in (("appeared", p.get("aio_appeared")),
                                                 ("citation lost", p.get("aio_citation_lost"))) if on)
            why += f" AI Overview {what}."
        why += " Quick answer-first fixes should recover it."
        return LevelResult("L1", 9, "answer_first", why, _checklist_l1(cfg, p, a))

    # 10. Structure complete but still slipping
    lo, hi = cfg["l10_range"]
    if worst is not None and lo <= worst <= hi:
        why = f"Slipped to {pos(worst)} despite a complete structure. Refresh content depth and freshness."
        return LevelResult("L2", 10, "depth", why, _checklist_l2(cfg, p, a, nums))

    # Fallback (not in §7; unreachable with the §3 filter in practice): treat as a standard refresh.
    why = f"Slipped to {pos(worst)}. Refresh content depth and freshness."
    return LevelResult("L2", 11, "fallback", why, _checklist_l2(cfg, p, a, nums))


# -- checklists --------------------------------------------------------------

def _l1_items(cfg, p, a) -> list[str]:
    kw = p["main_keyword"]
    items = []
    if not a.has_key_takeaways:
        items.append("Add Key Takeaways after the intro")
    if a.question_h2_missing_answer:
        lo, hi = cfg["direct_answer_min_words"], cfg["direct_answer_max_words"]
        items.append(f"Add a {lo}–{hi} word direct answer under: " + "; ".join(f"'{q}'" for q in a.question_h2_missing_answer))
    if a.faq_count < cfg["target_faq"]:
        items.append(f"Add {cfg['target_faq'] - a.faq_count} FAQs from live People Also Ask for '{kw}'")
    if a.images_missing_alt:
        items.append(f"Add alt text to {a.images_missing_alt} images")
    if p.get("aio_appeared") or p.get("aio_citation_lost"):
        items.append(f"Open the section on '{kw}' with a self-contained answer an AI Overview can cite")
    cluster = p.get("cluster") or p.get("core_topic") or "the same topic cluster"
    items.append(f"1 internal link to/from {cluster}")
    items.append("Change 'Updated on' only if answers changed")
    return items


def _checklist_l1(cfg, p, a) -> list[str]:
    return [LEVEL_SCOPE["L1"]] + _l1_items(cfg, p, a)


def _checklist_l2(cfg, p, a, nums) -> list[str]:
    kw = p["main_keyword"]
    items = [LEVEL_SCOPE["L2"]] + _l1_items(cfg, p, a)
    in_title = kw.lower() in (a.title or "").lower() and kw.lower() in (a.h1 or "").lower()
    if not in_title:
        items.append(f"Put '{kw}' in title/H1/first sentence (currently: {a.title or a.h1 or 'unknown'})")
    if a.median_competitor_words and a.word_count < a.median_competitor_words:
        items.append(f"Target ~{a.median_competitor_words} words (now {a.word_count})")
    if a.table_count == 0 and nums:
        items.append(f"Add a table for {', '.join(nums)}")
    items.append("Refresh sources older than 2 years")
    return items


def _checklist_l3(flags) -> list[str]:
    items = [LEVEL_SCOPE["L3"], "Writer + expert + Legal"]
    if flags:
        items.append(f"Remove claims: {', '.join(flags)}")
    items += ["Rebuild to model shape: Key Takeaways, PAA headings, 5 FAQs, tables, current sources",
              "Same URL, never a new slug"]
    return items


def _checklist_noseo(a, reject) -> list[str]:
    items = [LEVEL_SCOPE["NOSEO"]]
    if reject:
        items.append(f"Legal compliance check against pattern #{reject.category} ({reject.name})")
    if a.merged or a.http_status in (404, 410):
        items.append(f"Check redirect (final URL: {a.final_url})")
    return items


def checklist_for(cfg, level: str, p: dict, a, flags: list) -> list[str]:
    """Checklist for a level chosen outside the table (escalation, manual override)."""
    if level == "L1":
        return _checklist_l1(cfg, p, a)
    if level == "L2":
        return _checklist_l2(cfg, p, a, numeric_terms(cfg, p))
    if level == "L3":
        return _checklist_l3(flags)
    if level == "NOSEO":
        return _checklist_noseo(a, None)
    return [LEVEL_SCOPE["L0"]]


def escalate(level: str) -> str:
    return {"L1": "L2", "L2": "L3"}.get(level, level)
