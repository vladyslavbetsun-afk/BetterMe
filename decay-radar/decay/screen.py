"""Rejection-pattern screen of a page's topic (title, H1, main keyword) -> PASS / CAUTION / REJECT.

Ported from the `betterme-keyword-rejection-screen` skill (22 categories, rules
version 2026-08-28). Pass A is deterministic regex. Spec 02 §5.5 holds the
canonical Pass A list; until it is pasted in, PASS_A below is our port of the
skill text (docs/decisions.md D-06). Categories that need data (2 volume,
7 duplicate, 10 SERP DR, 19 competitor brand) are left to the data checks and
to the optional LLM Pass B.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field

import requests

log = logging.getLogger(__name__)

CATEGORIES = {
    1: "No matching product/flow/equipment",
    2: "Low search volume",
    3: "Medical/psychological/clinical topic",
    4: "Too broad/vague/off-topic",
    5: "Too advanced/extreme/elite",
    6: "Extreme/radical diet",
    7: "Duplicate",
    8: "Therapy/rehab/healing modality not offered",
    9: "Legal sign-off required",
    10: "High SERP competition",
    11: "Deprioritized/seasonal/not current focus",
    12: "Unproven superlative claim",
    13: "'Food item + weight loss' formula minimized",
    14: "Zero-click/pure-information query",
    15: "Equipment-tied topic",
    16: "Bulking/muscle-gain mismatch",
    17: "Dangerous practice/safety risk",
    18: "False/unprovable claim risk (FTC/spot-reduction)",
    19: "Competing/third-party brand terms",
    20: "Alcohol/period-specific fasting",
    21: "Single-meal-skipping framed as a practice",
    22: "Clinical/rehab-adjacent terminology",
}

# (category, verdict, regex, note)
PASS_A: list[tuple[int, str, str, str]] = [
    (1, "CAUTION", r"\btai ?chi\b", "Tai Chi in-app support is an open team decision"),
    (1, "CAUTION", r"\breformer\b(?!.*\bmini\b)", "reformer equipment not offered (Mini Reformer is fine)"),
    (3, "REJECT", r"\bchildhood trauma\b", "childhood trauma"),
    (3, "REJECT", r"\bautophagy\b", "autophagy fasting"),
    (3, "REJECT", r"\bbad knees?\b", "'bad knees' qualifier"),
    (3, "CAUTION", r"\bsomatic\b", "'somatic' topic; Somatic Exercises is also a live blog category (D-06)"),
    (3, "CAUTION", r"\b(peri)?menopaus\w*|\bpcos\b|\bthyroid\b|\bhypothyroid\w*|\bhashimoto\w*",
     "hormonal/life-stage condition needs FTC-grade substantiation"),
    (5, "CAUTION", r"\bnavy seals?\b|\bmilitary\b|\bpowerlifting\b|\bprogressive overload\b", "advanced/elite framing"),
    (6, "REJECT", r"\bcarnivore\b|\bzero[- ]carb\b|\bprotein[- ]only\b|\bdetox\b|\bcleanse\b|\b(cucumber|tuna|egg|cabbage soup|grapefruit) diet\b",
     "extreme or fad diet"),
    (6, "REJECT", r"\b[1-7]\d{2}[- ]?(calorie|kcal)s?\b", "sub-800-calorie plan"),
    (8, "REJECT", r"\bgong\b|\bsound (healing|bath|therapy)\b|\bcore rehab\b", "therapy modality not offered"),
    (9, "CAUTION", r"\bpregnan\w*|\bprenatal\b|\btrimester\b", "pregnancy needs Legal sign-off"),
    (11, "CAUTION", r"\brecipes?\b|\bmeal prep\b|\bdesserts?\b|\bsmoothie\b", "recipe format: standing low priority"),
    (12, "CAUTION", r"\bbest\b|\bguarantee[ds]?\b|#1\b|\bnumber one\b", "unproven superlative"),
    (14, "CAUTION", r"\bwhich muscles?\b|\bwhat muscles?\b|\bhow many calories (does|do|in)\b|\bcalories in\b",
     "zero-click single-fact query"),
    (15, "CAUTION", r"\bkettlebell\b|\bresistance bands?\b|\browing machine\b|\belliptical\b|\bstair ?master\b|\bvibration plate\b",
     "equipment-tied; may belong to Store content"),
    (16, "CAUTION", r"\bbulk(ing)?\b|\bmass gain\b|\bgain (muscle )?mass\b|\bweight gain\b|\bgain weight\b", "bulking off-ICP"),
    (17, "REJECT", r"\bdry fast\w*|\brefeed\w*", "dangerous fasting practice"),
    (17, "CAUTION", r"\bfix (your )?(spine|back|posture)\b|\bspine fix\b", "'fix' promise about the spine"),
    (18, "CAUTION", r"\binner thighs?\b|\bslim(mer)?( down)? (your )?(thighs|arms|waist|legs)\b|\barm fat\b|\bbelly fat\b|\bface fat\b|\bchubby cheeks\b"
     r"|\blove handles\b|\bbubble butt\b|\bv[- ]shaped\b|\bfat fingers\b|\bcardio for glutes\b|\bhip dips\b|\blose (belly|arm|thigh|face|back) fat\b",
     "spot-reduction/shape-change claim"),
    (20, "REJECT", r"\balcohol\b.*\bfast\w*|\bfast\w*.*\balcohol\b|\bperiod fasting\b|\bfasting (on|during) (your )?period\b|\bmenstrual\b.*\bfast\w*",
     "alcohol/period fasting policy"),
    (21, "REJECT", r"\bskipp?(ing)? (breakfast|lunch|dinner|meals?)\b", "single-meal skipping as a practice"),
    (22, "REJECT", r"\bbed mobility\b|\bgait training\b|\brom exercises\b|\brange of motion exercises\b|\bpost[- ]?op\b|\bafter surgery\b|\bpost[- ]surgery\b",
     "clinical/rehab audience"),
]
_COMPILED = [(c, v, re.compile(rx, re.I), note) for c, v, rx, note in PASS_A]
RANK = {"PASS": 0, "CAUTION": 1, "REJECT": 2}


@dataclass
class Match:
    category: int
    name: str
    verdict: str
    note: str
    source: str = "A"

    def to_dict(self):
        return asdict(self)


@dataclass
class ScreenResult:
    verdict: str = "PASS"
    matches: list = field(default_factory=list)

    @property
    def reject(self) -> Match | None:
        return next((m for m in self.matches if m.verdict == "REJECT"), None)

    def categories(self, verdict: str | None = None) -> list[int]:
        return [m.category for m in self.matches if verdict is None or m.verdict == verdict]

    def reasons(self) -> str:
        return "; ".join(f"#{m.category} {m.name} ({m.note})" for m in self.matches)


def screen_text(*texts: str) -> ScreenResult:
    hay = " | ".join(t for t in texts if t)
    res = ScreenResult()
    seen = set()
    for cat, verdict, rx, note in _COMPILED:
        if rx.search(hay) and (cat, verdict) not in seen:
            seen.add((cat, verdict))
            res.matches.append(Match(cat, CATEGORIES[cat], verdict, note))
    res.matches.sort(key=lambda m: (-RANK[m.verdict], m.category))
    res.verdict = max((m.verdict for m in res.matches), key=RANK.get, default="PASS")
    return res


LLM_PROMPT = """You screen BetterMe blog article topics against rejection categories.
Categories: {cats}
Topic: title="{title}" h1="{h1}" main_keyword="{kw}"
Return only JSON: {{"verdict":"PASS|CAUTION|REJECT","categories":[{{"n":<int>,"verdict":"CAUTION|REJECT","note":"<short reason>"}}]}}
REJECT only for a clear match with no workaround; CAUTION when a wording change or Legal/team sign-off could fix it."""


def llm_screen(cfg, store, url: str, title: str, h1: str, kw: str) -> list[Match]:
    """Optional Pass B (claude-haiku), cached per URL until rules_version changes."""
    if not (cfg["llm_screen"] and cfg.anthropic_api_key):
        return []
    cached = store.one("select verdict from screen_cache where url=? and rules_version=?", [url, cfg["rules_version"]])
    if cached:
        data = cached["verdict"]
    else:
        prompt = LLM_PROMPT.format(cats="; ".join(f"{n}. {c}" for n, c in CATEGORIES.items()), title=title or "",
                                   h1=h1 or "", kw=kw or "")
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": cfg.anthropic_api_key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": cfg["llm_model"], "max_tokens": 400, "messages": [{"role": "user", "content": prompt}]},
                timeout=60,
            )
            resp.raise_for_status()
            text = "".join(b.get("text", "") for b in resp.json().get("content", []))
            data = json.loads(text[text.index("{"): text.rindex("}") + 1])
        except Exception as exc:  # noqa: BLE001 - Pass B is advisory
            log.warning("LLM screen failed for %s: %s", url, exc)
            return []
        store.upsert("screen_cache", {"url": url, "rules_version": cfg["rules_version"], "verdict": data},
                     ["url", "rules_version"])
        store.commit()
    out = []
    for c in data.get("categories", []):
        n = int(c.get("n", 0))
        if n in CATEGORIES and c.get("verdict") in ("CAUTION", "REJECT"):
            out.append(Match(n, CATEGORIES[n], c["verdict"], c.get("note", ""), source="B"))
    return out


def screen_page(cfg, store, url: str, title: str | None, h1: str | None, main_keyword: str, slug: str = "") -> ScreenResult:
    res = screen_text(title or "", h1 or "", main_keyword, slug.replace("-", " "))
    extra = llm_screen(cfg, store, url, title or "", h1 or "", main_keyword)
    known = {(m.category, m.verdict) for m in res.matches}
    for m in extra:
        if (m.category, m.verdict) not in known:
            res.matches.append(m)
    res.matches.sort(key=lambda m: (-RANK[m.verdict], m.category))
    res.verdict = max((m.verdict for m in res.matches), key=RANK.get, default="PASS")
    return res
