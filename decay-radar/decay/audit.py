"""§6 live page audit: one rate-limited fetch per page, HTML parse, optional competitor length."""
from __future__ import annotations

import json
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

from .aggregate import normalize_url

CLAIM_PATTERNS = {
    "timeline claim": re.compile(r"\bin \d+ days\b", re.I),
    "weight-loss outcome": re.compile(r"\blose \d+ (?:lbs|pounds|kg)\b", re.I),
    "spot-reduction (burn fat)": re.compile(r"\bburn (?:belly|arm|thigh) fat\b", re.I),
    "spot-reduction (slim)": re.compile(r"\bslim (?:your )?(?:thighs|arms|waist)\b", re.I),
    "guarantee": re.compile(r"\bguaranteed\b", re.I),
}
BEST_RE = re.compile(r"\bbest\b", re.I)
UPDATED_RE = re.compile(r"updated\s+on[:\s]+([A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})", re.I)
KEY_TAKEAWAYS_RE = re.compile(r"key\s+takeaways?", re.I)
FAQ_HEADING_RE = re.compile(r"\b(faq|faqs|frequently asked questions)\b", re.I)
STRIP_SELECTORS = ["nav", "footer", "header", "aside", "script", "style", "noscript", "form", "svg", "iframe"]
RELATED_CLASS_RE = re.compile(r"related|recommend|read-?more|share|breadcrumb|newsletter|comments?|sidebar|author-?bio", re.I)


@dataclass
class Audit:
    url: str
    http_status: int | None = None
    final_url: str | None = None
    merged: bool = False
    updated_on: str | None = None
    title: str | None = None
    h1: str | None = None
    meta_description: str | None = None
    word_count: int = 0
    has_key_takeaways: bool = False
    faq_count: int = 0
    question_h2_count: int = 0
    question_h2_with_direct_answer: int = 0
    question_h2_missing_answer: list = field(default_factory=list)
    table_count: int = 0
    image_count: int = 0
    images_missing_alt: int = 0
    internal_links_out: int = 0
    claim_flags: list = field(default_factory=list)
    age_days: int | None = None
    median_competitor_words: int | None = None
    competitor_check: str = "not run"
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_row(self, run_id: int, screen) -> dict:
        return {
            "url": self.url, "run_id": run_id, "http_status": self.http_status, "final_url": self.final_url,
            "updated_on": self.updated_on, "title": self.title, "h1": self.h1, "word_count": self.word_count,
            "has_key_takeaways": self.has_key_takeaways, "faq_count": self.faq_count,
            "question_h2_count": self.question_h2_count, "question_h2_answered": self.question_h2_with_direct_answer,
            "table_count": self.table_count, "images_missing_alt": self.images_missing_alt,
            "internal_links_out": self.internal_links_out, "claim_flags": self.claim_flags,
            "median_competitor_words": self.median_competitor_words, "competitor_check": self.competitor_check,
            "screen_verdict": screen.verdict if screen else None,
            "screen_categories": [m.to_dict() for m in screen.matches] if screen else [],
        }


class Fetcher:
    """requests wrapper honouring a 1 req/sec limit and a descriptive User-Agent."""

    def __init__(self, user_agent: str, delay: float = 1.0, timeout: int = 20, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"})
        self.delay = delay
        self.timeout = timeout
        self._last = 0.0

    def get(self, url: str):
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        try:
            return self.session.get(url, timeout=self.timeout, allow_redirects=True)
        finally:
            self._last = time.monotonic()


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9’']+", text or ""))


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    text = text.strip().replace(".", "").replace(",", ",")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        return date.fromisoformat(m.group(1))
    for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _json_ld(soup) -> list[dict]:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                out.append(node)
                if "@graph" in node:
                    stack.extend(node["@graph"] if isinstance(node["@graph"], list) else [node["@graph"]])
            elif isinstance(node, list):
                stack.extend(node)
    return out


def _types(node: dict) -> set:
    t = node.get("@type")
    return set(t if isinstance(t, list) else [t])


def find_updated_on(soup, ld: list[dict]) -> date | None:
    m = UPDATED_RE.search(soup.get_text(" ", strip=True))
    if m:
        d = parse_date(m.group(1))
        if d:
            return d
    meta = soup.find("meta", attrs={"property": "article:modified_time"})
    if meta and meta.get("content"):
        d = parse_date(meta["content"][:10])
        if d:
            return d
    for node in ld:
        if node.get("dateModified"):
            d = parse_date(str(node["dateModified"])[:10])
            if d:
                return d
    return None


def main_content(soup):
    """`<article>` when present, else the block with the most paragraph text."""
    for sel in STRIP_SELECTORS:
        for t in soup.select(sel):
            t.decompose()
    for t in soup.find_all(class_=RELATED_CLASS_RE):
        if t.name not in ("body", "html", "article", "main"):
            t.decompose()
    articles = soup.find_all("article")
    if articles:
        return max(articles, key=lambda a: _words(a.get_text(" ", strip=True)))
    best, best_words = soup.body or soup, 0
    for cand in soup.find_all(["main", "div", "section"]):
        words = sum(_words(p.get_text(" ", strip=True)) for p in cand.find_all("p", recursive=True))
        if words > best_words:
            best, best_words = cand, words
    return best


def count_faqs(content, ld: list[dict]) -> int:
    for node in ld:
        if "FAQPage" in _types(node):
            entities = node.get("mainEntity") or []
            return len(entities if isinstance(entities, list) else [entities])
    heading = next((h for h in content.find_all(["h2", "h3"]) if FAQ_HEADING_RE.search(h.get_text(" ", strip=True))), None)
    if heading is None:
        return 0
    level = int(heading.name[1])
    count = 0
    for el in heading.find_all_next():
        is_heading = el.name in ("h1", "h2", "h3", "h4")
        if is_heading and int(el.name[1]) <= level:
            break  # next section
        if is_heading or el.name in ("summary", "dt"):
            count += 1
        elif el.name in ("strong", "b") and el.parent is not None and el.parent.name == "p" \
                and el.get_text(strip=True).endswith("?"):
            count += 1
    return count


def first_paragraph_after(h):
    for el in h.find_all_next():
        if el.name in ("h1", "h2", "h3"):
            return None
        if el.name == "p" and el.get_text(strip=True):
            return el
    return None


def audit_html(url: str, html: str, cfg, today: date, final_url: str | None = None, status: int = 200) -> Audit:
    soup = BeautifulSoup(html, "lxml")
    a = Audit(url=url, http_status=status, final_url=final_url or url)
    final_norm = normalize_url(a.final_url)
    # A redirect to another article (or off /articles/ entirely) means the page was merged.
    a.merged = final_norm != url

    ld = _json_ld(soup)
    a.title = soup.title.get_text(strip=True) if soup.title else None
    md = soup.find("meta", attrs={"name": "description"})
    a.meta_description = md.get("content") if md else None
    h1 = soup.find("h1")
    a.h1 = h1.get_text(" ", strip=True) if h1 else None
    upd = find_updated_on(soup, ld)
    a.updated_on = upd.isoformat() if upd else None
    a.age_days = (today - upd).days if upd else None

    content = main_content(soup)
    text = content.get_text(" ", strip=True)
    a.word_count = _words(text)
    a.has_key_takeaways = any(
        KEY_TAKEAWAYS_RE.search(el.get_text(" ", strip=True))
        for el in content.find_all(["h2", "h3", "h4", "strong", "b", "p", "div"])
        if len(el.get_text(strip=True)) < 60
    )
    a.faq_count = count_faqs(content, ld)

    lo, hi = cfg["direct_answer_min_words"], cfg["direct_answer_max_words"]
    for h2 in content.find_all("h2"):
        q = h2.get_text(" ", strip=True)
        if not q.endswith("?") or FAQ_HEADING_RE.search(q):
            continue
        a.question_h2_count += 1
        p = first_paragraph_after(h2)
        if p is not None and lo <= _words(p.get_text(" ", strip=True)) <= hi:
            a.question_h2_with_direct_answer += 1
        else:
            a.question_h2_missing_answer.append(q)

    a.table_count = len(content.find_all("table"))
    imgs = content.find_all("img")
    a.image_count = len(imgs)
    a.images_missing_alt = sum(1 for i in imgs if not (i.get("alt") or "").strip())
    a.internal_links_out = sum(
        1 for l in content.find_all("a", href=True)
        if "/articles/" in l["href"] and ("betterme.world" in l["href"] or l["href"].startswith("/"))
        and normalize_url(l["href"] if "://" in l["href"] else "https://betterme.world" + l["href"]) != url
    )
    flags = [name for name, rx in CLAIM_PATTERNS.items() if rx.search(text) or rx.search(a.title or "")]
    if BEST_RE.search(a.title or "") or BEST_RE.search(a.h1 or ""):
        flags.append("'best' in title/H1")
    a.claim_flags = flags
    return a


def audit_page(fetcher: Fetcher, url: str, cfg, today: date) -> Audit:
    try:
        resp = fetcher.get(url)
    except requests.RequestException as exc:
        return Audit(url=url, error=f"fetch failed: {exc}")
    if resp.status_code >= 400:
        return Audit(url=url, http_status=resp.status_code, final_url=resp.url, error=f"HTTP {resp.status_code}")
    return audit_html(url, resp.text, cfg, today, final_url=resp.url, status=resp.status_code)


def competitor_words(fetcher: Fetcher, ahrefs, keyword: str, country: str, cfg) -> tuple[int | None, str]:
    """Option A only: median word count of the top-N organic results (excluding betterme.world)."""
    if not cfg["competitor_check"]:
        return None, "skipped (egress)" if cfg.mode == "bpops" else "off (competitor_check setting)"
    if ahrefs is None:
        return None, "skipped (no Ahrefs client)"
    try:
        positions = ahrefs.serp_overview(keyword, country, cfg["competitor_top_n"] + 3)
    except Exception as exc:  # noqa: BLE001 - report and move on
        return None, f"skipped (serp-overview failed: {exc})"
    urls = []
    for p in sorted(positions, key=lambda p: p.get("position") or 99):
        types = set(p.get("type") or [])
        u = p.get("url")
        if u and "organic" in types and "betterme.world" not in u:
            urls.append(u)
        if len(urls) >= cfg["competitor_top_n"]:
            break
    counts = []
    for u in urls:
        try:
            r = fetcher.get(u)
            if r.status_code < 400:
                counts.append(_words(main_content(BeautifulSoup(r.text, "lxml")).get_text(" ", strip=True)))
        except requests.RequestException:
            continue
    counts = [c for c in counts if c > 200]
    if not counts:
        return None, "no competitor pages fetched"
    return int(statistics.median(counts)), f"ok ({len(counts)} pages)"
