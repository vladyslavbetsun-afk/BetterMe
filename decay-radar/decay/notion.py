"""§10 Notion card creation, ported from `blog-notion-ticket-creation`; dedupe; verification.

Flow per card (apply mode):
  1. fetch the data source schema once and fail loudly if a property is missing;
  2. skip if decay_cards already holds (url, iso_week) with a notion_url;
  3. if an open card exists for the URL, comment on it instead of creating;
  4. write a *pending* decay_cards row before calling Notion, so a crash between
     "Notion created the page" and "we stored it" is recovered on re-run by
     adopting the card instead of creating a second one;
  5. create, store, re-fetch, verify Name / URL 1 / Status / New/Upd / Date.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date

import requests

from .config import LEVEL_NAMES
from .storage import now_iso

log = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
REQUIRED_PROPERTIES = ["Name", "New/Upd", "Status", "URL 1", "JIRA", "Date", "Brand/App"]
VERIFY_PROPERTIES = ["Name", "URL 1", "Status", "New/Upd", "Date"]


class SchemaError(RuntimeError):
    pass


# -- category inference (taxonomy from `blog-jira-ticket-creation`) ----------
TAXONOMY_RULES: list[tuple[str, str]] = [
    ("Calisthenics for men", r"calisthenics.*\b(men|male|guys?)\b|\b(men|male)\b.*calisthenics"),
    ("Calisthenics for women", r"calisthenics.*\b(women|female)\b|\b(women|female)\b.*calisthenics"),
    ("Calisthenics", r"calisthenics"),
    ("Wall Pilates", r"wall pilates"),
    ("Pilates Mini Reformer", r"mini reformer"),
    ("Home Pilates", r"pilates (at|from) home|home pilates"),
    ("Chair Yoga", r"chair yoga"),
    ("Somatic Exercises", r"somatic"),
    ("Meditation", r"meditat"),
    ("Workout Plans For Men", r"workout (plan|program|routine)s?.*\bmen\b|\bmen'?s? workout (plan|program)"),
    ("Workout Plans For Women", r"workout (plan|program|routine)s?.*\bwomen\b|\bwomen'?s? workout (plan|program)"),
    ("HIIT Training", r"\bhiit\b"),
    ("Strength Training", r"strength training|weight lifting|weightlifting"),
    ("Bodyweight Training", r"bodyweight|body weight"),
    ("Indoor Walking", r"indoor walk|walk(ing)? at home|walking in place"),
    ("Treadmill", r"treadmill"),
    ("Walking", r"\bwalk(ing)?\b|steps a day"),
    ("Abs Workouts", r"\babs?\b|six pack|ab workout"),
    ("Oblique Workouts", r"oblique"),
    ("Arm Workouts", r"\barms?\b|tricep|bicep"),
    ("Back Workouts", r"\bback (workout|exercise)"),
    ("Butt Workouts", r"\bbutt\b|glute"),
    ("Chest Workouts", r"\bchest\b"),
    ("Core Workouts", r"\bcore\b"),
    ("Dumbbell Workouts", r"dumbbell"),
    ("Leg Workouts", r"\blegs?\b|\bthighs?\b|\bsquats?\b"),
    ("Cardio Workouts", r"cardio"),
    ("Keto Breakfast", r"keto breakfast"),
    ("Keto Lunch", r"keto lunch"),
    ("Keto Dinner", r"keto dinner"),
    ("Keto Recipes", r"keto recipe"),
    ("Keto", r"\bketo"),
    ("Fasting", r"fasting|\bomad\b|16:8|\bfast\b"),
    ("Gluten Free", r"gluten"),
    ("Low Carb", r"low[- ]carb"),
    ("Low Cholesterol", r"cholesterol"),
    ("Mediterranean", r"mediterranean"),
    ("Paleo", r"paleo"),
    ("Plant Based", r"plant[- ]based"),
    ("Vegan", r"\bvegan"),
    ("Vegetarian", r"vegetarian"),
    ("Meal Plans", r"meal plan"),
    ("Recipes", r"recipe"),
    ("Food For Weight Loss", r"foods? (for|to) (lose weight|weight loss)|fat[- ]burning foods?"),
    ("Weight Management", r"maintain(ing)? weight|weight management|weight maintenance"),
    ("Weight Loss Tips", r"lose weight|weight loss|losing weight|fat loss"),
    ("Meal Ideas", r"\bbreakfast|\blunch|\bdinner|\bsnacks?\b|meal ideas"),
    ("Healthy Eating", r"healthy eating|nutrition|protein|vitamin|fiber|calorie"),
    ("Therapy", r"therapy|anxiety|stress"),
    ("Pilates", r"pilates"),
    ("Yoga", r"\byoga\b"),
    ("Corporate Wellness", r"corporate|workplace|employee"),
]
_TAX = [(leaf, re.compile(rx, re.I)) for leaf, rx in TAXONOMY_RULES]


def infer_category(main_keyword: str, slug: str) -> str | None:
    for text in (main_keyword, slug.replace("-", " ")):
        for leaf, rx in _TAX:
            if rx.search(text or ""):
                return leaf
    return None


# -- card payload ---------------------------------------------------------------
@dataclass
class Card:
    url: str
    properties: dict  # plain values keyed by property name
    body_markdown: str
    blocks: list = field(default_factory=list)
    category_inferred: bool = True
    level: str = ""
    priority: float = 0.0


def fmt_pos(p):
    return "lost" if p is None else f"#{p}"


def card_name(cfg, item: dict, audit: dict | None) -> str:
    kw = item["main_keyword"]
    n = None
    if "{n}" in cfg["card_name_format"]:
        median = (audit or {}).get("median_competitor_words")
        wc = (audit or {}).get("word_count") or 0
        n = median if item.get("level") in ("L2", "L3") and median else wc
        n = int(round((n or 0) / 100.0) * 100)
    return cfg["card_name_format"].format(kw=kw, n=n)


def build_card(cfg, item: dict, audit: dict | None, run_id: int, today: date, rank: int) -> Card:
    level = item.get("level_override") or item["level"]
    category = infer_category(item["main_keyword"], item["slug"])
    props = {
        "Name": card_name(cfg, item, audit),
        "New/Upd": "Update",
        "Status": "Not started",
        "URL 1": item["url"],
        "JIRA": None,
        "Date": today.isoformat(),
        "category": category,
        "Choose Primary": "(Week)" if cfg["choose_primary_week_top"] and rank <= cfg["choose_primary_week_top"] else None,
        "Brand/App": None,
    }
    a = audit or {}
    lost = item.get("lost_keywords") or []
    lines = [
        f"## Decay radar — {level} {LEVEL_NAMES[level]}",
        "",
        item["why"],
        "",
        "| Keyword | Volume | Was → now | Traffic lost |",
        "|---|---|---|---|",
    ]
    for k in lost:
        lines.append(f"| {k['kw']} | {k['vol']} | {fmt_pos(k['was'])} → {fmt_pos(k['now'])} | "
                     f"{max((k['traffic_prev'] or 0) - (k['traffic_now'] or 0), 0)} |")
    lines.append("")
    for c in item.get("checklist") or []:
        lines.append(f"- [ ] {c}")
    lines += [
        "",
        f"- Updated on: {a.get('updated_on') or 'unknown'}",
        f"- Words: {a.get('word_count') or 'unknown'}"
        + (f" (competitor median {a['median_competitor_words']})" if a.get("median_competitor_words") else ""),
        f"- FAQs: {a.get('faq_count', 'unknown')}",
        f"- Key Takeaways: {'yes' if a.get('has_key_takeaways') else 'no'}",
        "",
        f"Generated by Decay Radar run {run_id} on {today.isoformat()}",
    ]
    return Card(url=item["url"], properties=props, body_markdown="\n".join(lines),
                blocks=_blocks(level, item, lost, a, run_id, today), category_inferred=category is not None,
                level=level, priority=item.get("priority") or 0)


def _rt(text: str) -> list:
    text = text or ""
    return [{"type": "text", "text": {"content": text[i:i + 1900]}} for i in range(0, max(len(text), 1), 1900)]


def _blocks(level, item, lost, a, run_id, today) -> list:
    blocks = [
        {"type": "heading_2", "heading_2": {"rich_text": _rt(f"Decay radar — {level} {LEVEL_NAMES[level]}")}},
        {"type": "paragraph", "paragraph": {"rich_text": _rt(item["why"])}},
    ]
    rows = [["Keyword", "Volume", "Was → now", "Traffic lost"]] + [
        [k["kw"], str(k["vol"]), f"{fmt_pos(k['was'])} → {fmt_pos(k['now'])}",
         str(max((k["traffic_prev"] or 0) - (k["traffic_now"] or 0), 0))] for k in lost
    ]
    blocks.append({"type": "table", "table": {
        "table_width": 4, "has_column_header": True, "has_row_header": False,
        "children": [{"type": "table_row", "table_row": {"cells": [_rt(c) for c in r]}} for r in rows],
    }})
    for c in item.get("checklist") or []:
        blocks.append({"type": "to_do", "to_do": {"rich_text": _rt(c), "checked": False}})
    facts = [
        f"Updated on: {a.get('updated_on') or 'unknown'}",
        f"Words: {a.get('word_count') or 'unknown'}",
        f"FAQs: {a.get('faq_count', 'unknown')}",
        f"Key Takeaways: {'yes' if a.get('has_key_takeaways') else 'no'}",
    ]
    for f_ in facts:
        blocks.append({"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rt(f_)}})
    blocks.append({"type": "paragraph", "paragraph": {"rich_text": _rt(f"Generated by Decay Radar run {run_id} on {today.isoformat()}")}})
    return blocks


# -- Notion API -------------------------------------------------------------------
def to_api_value(ptype: str, value):
    if value is None:
        return None
    return {
        "title": lambda v: {"title": _rt(v)},
        "rich_text": lambda v: {"rich_text": _rt(v)},
        "select": lambda v: {"select": {"name": v}},
        "status": lambda v: {"status": {"name": v}},
        "multi_select": lambda v: {"multi_select": [{"name": v}]},
        "url": lambda v: {"url": v},
        "date": lambda v: {"date": {"start": v}},
    }.get(ptype, lambda v: {"rich_text": _rt(str(v))})(value)


def from_api_value(prop: dict):
    t = prop.get("type")
    v = prop.get(t)
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text") or x.get("text", {}).get("content", "") for x in v or [])
    if t in ("select", "status"):
        return (v or {}).get("name")
    if t == "multi_select":
        return ", ".join(x.get("name") for x in v or [])
    if t == "date":
        return (v or {}).get("start")
    return v


class NotionClient:
    def __init__(self, token: str, data_source_id: str, session: requests.Session | None = None):
        self.ds = data_source_id
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION, "Content-Type": "application/json",
        })

    def _req(self, method: str, path: str, **kw) -> dict:
        resp = self.session.request(method, f"{API}/{path}", timeout=60, **kw)
        if resp.status_code >= 400:
            raise RuntimeError(f"Notion {method} {path} -> HTTP {resp.status_code}: {resp.text[:400]}")
        return resp.json()

    def schema(self) -> dict:
        """{property name: type}"""
        data = self._req("GET", f"data_sources/{self.ds}")
        return {name: p.get("type") for name, p in data.get("properties", {}).items()}

    def find_cards(self, url: str) -> list[dict]:
        variants = {url, url.rstrip("/"), url.replace("https://", "https://www."), url.replace("https://www.", "https://")}
        variants |= {v.rstrip("/") for v in list(variants)}
        flt = {"or": [{"property": "URL 1", "url": {"equals": v}} for v in sorted(variants)]}
        data = self._req("POST", f"data_sources/{self.ds}/query", json={"filter": flt, "page_size": 20})
        return data.get("results", [])

    def create_page(self, properties: dict, children: list) -> dict:
        return self._req("POST", "pages", json={
            "parent": {"type": "data_source_id", "data_source_id": self.ds},
            "properties": properties, "children": children[:100],
        })

    def get_page(self, page_id: str) -> dict:
        return self._req("GET", f"pages/{page_id}")

    def comment(self, page_id: str, text: str) -> dict:
        return self._req("POST", "comments", json={"parent": {"page_id": page_id}, "rich_text": _rt(text)})


def card_status(page: dict) -> str | None:
    return from_api_value(page.get("properties", {}).get("Status", {"type": "status", "status": None}))


def open_card_for(notion: NotionClient, url: str) -> dict | None:
    for page in notion.find_cards(url):
        if (card_status(page) or "").lower() != "done":
            return page
    return None


def resolve_schema(cfg, schema: dict) -> dict:
    """Maps our logical property names to the real ones; fails loudly on drift (00 §4)."""
    missing = [p for p in REQUIRED_PROPERTIES if p not in schema]
    category = next((p for p in cfg["notion_category_properties"] if p in schema), None)
    if category is None:
        missing.append(" / ".join(cfg["notion_category_properties"]))
    if missing:
        raise SchemaError(f"Notion Articles schema is missing or renamed: {', '.join(missing)}. "
                          f"Found: {', '.join(sorted(schema))}")
    mapping = {p: p for p in REQUIRED_PROPERTIES}
    mapping["category"] = category
    if "Choose Primary" in schema:
        mapping["Choose Primary"] = "Choose Primary"
    return mapping


def api_properties(card: Card, schema: dict, mapping: dict) -> dict:
    out = {}
    for logical, value in card.properties.items():
        real = mapping.get(logical)
        if real is None or value is None:
            continue
        out[real] = to_api_value(schema[real], value)
    return out


@dataclass
class CardOutcome:
    url: str
    action: str  # created | adopted | commented | skipped | failed
    reason: str = ""
    notion_url: str | None = None
    verified: bool | None = None
    mismatches: list = field(default_factory=list)
    category: str | None = None
    category_inferred: bool = False


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def apply_cards(cfg, store, notion: NotionClient, cards: list[Card], today: date, items_by_url: dict,
                fail_after: int | None = None) -> list[CardOutcome]:
    """Writes cards. `fail_after` raises after N creations (used by the crash/re-run test)."""
    schema = notion.schema()
    mapping = resolve_schema(cfg, schema)
    week = iso_week(today)
    outcomes = []
    created = 0
    for card in cards:
        item = items_by_url[card.url]
        row = store.one("select * from decay_cards where url=? and iso_week=?", [card.url, week])
        if row and row.get("notion_url"):
            outcomes.append(CardOutcome(card.url, "skipped", f"already carded this week ({row['notion_url']})",
                                        row["notion_url"]))
            continue

        existing = open_card_for(notion, card.url)
        if existing and not row:
            kw = item["main_keyword"]
            now = fmt_pos(item.get("main_now"))
            notion.comment(existing["id"], f"Decay radar {today.isoformat()}: still slipping, now {now} for '{kw}'.")
            outcomes.append(CardOutcome(card.url, "commented", "open card exists", existing.get("url")))
            continue
        if existing and row:
            # Crash recovery: we wrote the pending row, Notion created the page, we never stored it.
            _store_card(store, card, week, existing.get("url"), today)
            outcomes.append(CardOutcome(card.url, "adopted", "recovered from an interrupted run", existing.get("url")))
            continue

        if not row:
            store.upsert("decay_cards", {"url": card.url, "iso_week": week, "notion_url": None,
                                         "created_at": now_iso(), "payload": {"properties": card.properties, "level": card.level}},
                         ["url", "iso_week"])
            store.commit()
        page = notion.create_page(api_properties(card, schema, mapping), card.blocks)
        created += 1
        if fail_after is not None and created > fail_after:
            raise RuntimeError("forced failure after Notion create (test hook)")
        _store_card(store, card, week, page.get("url"), today)
        fetched = notion.get_page(page["id"])
        mismatches = verify(card, fetched, mapping)
        outcomes.append(CardOutcome(card.url, "created", "", page.get("url"), not mismatches, mismatches,
                                    card.properties.get("category"), card.category_inferred))
    return outcomes


def _store_card(store, card: Card, week: str, notion_url: str | None, today: date):
    store.upsert("decay_cards", {"url": card.url, "iso_week": week, "notion_url": notion_url, "created_at": now_iso(),
                                 "payload": {"properties": card.properties, "level": card.level}}, ["url", "iso_week"])
    store.execute("update decay_items set state='carded', notion_url=? where url=?", [notion_url, card.url])
    if not store.one("select url from decay_suggestions where url=?", [card.url]):
        store.upsert("decay_suggestions", {"url": card.url, "first_suggested": today.isoformat(), "source": "decay-radar"},
                     ["url"])
    store.commit()


def verify(card: Card, page: dict, mapping: dict) -> list[str]:
    props = page.get("properties", {})
    out = []
    for logical in VERIFY_PROPERTIES:
        want = card.properties.get(logical)
        got = from_api_value(props.get(mapping[logical], {"type": None}))
        if logical == "Date" and got:
            got = got[:10]
        if (got or None) != (want or None):
            out.append(f"{logical}: expected {want!r}, got {got!r}")
    return out


# -- high level -------------------------------------------------------------------
def select_items(store, urls: list[str] | None = None) -> list[dict]:
    if urls:
        marks = ",".join("?" for _ in urls)
        rows = store.query(f"select * from decay_items where url in ({marks})", urls)
    else:
        rows = store.query("select * from decay_items where state='proposed'")
    out = []
    for r in rows:
        lvl = r.get("level_override") or r["level"]
        if r["state"] in ("excluded", "noseo") or lvl not in ("L1", "L2", "L3"):
            log.warning("skipping %s: state=%s level=%s (only L1–L3 get cards)", r["url"], r["state"], lvl)
            continue
        out.append(r)
    return sorted(out, key=lambda r: -(r["priority"] or 0))


def build_cards(cfg, store, items: list[dict], today: date) -> list[Card]:
    cards = []
    for rank, item in enumerate(items, start=1):
        payload = store.one("select payload from decay_run_items where url=? order by run_id desc limit 1", [item["url"]])
        payload = payload["payload"] if payload else {}
        full = dict(item)
        full["lost_keywords"] = (payload.get("page") or {}).get("lost_keywords", [])
        full["main_now"] = (payload.get("page") or {}).get("main_now")
        cards.append(build_card(cfg, full, payload.get("audit"), item["last_seen_run"], today, rank))
    return cards


def create_cards(cfg, store, notion: NotionClient | None, dry_run: bool = True, urls: list[str] | None = None,
                 today: date | None = None, fail_after: int | None = None):
    """Returns (cards, outcomes). Dry run writes nothing anywhere."""
    today = today or cfg.today
    items = select_items(store, urls)
    cards = build_cards(cfg, store, items, today)
    if dry_run:
        return cards, []
    if notion is None:
        raise RuntimeError("NOTION_TOKEN is not set; run with --dry-run or export CSV with `report`.")
    by_url = {}
    for card, item in zip(cards, items):
        by_url[card.url] = dict(item, main_now=card_main_now(store, item["url"]))
    return cards, apply_cards(cfg, store, notion, cards, today, by_url, fail_after=fail_after)


def card_main_now(store, url: str):
    row = store.one("select payload from decay_run_items where url=? order by run_id desc limit 1", [url])
    return ((row or {}).get("payload") or {}).get("page", {}).get("main_now") if row else None
