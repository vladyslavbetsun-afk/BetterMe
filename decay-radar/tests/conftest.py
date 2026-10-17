"""Offline fakes for Ahrefs, page fetches, Jira and Notion, plus a fresh SQLite store per test."""
from __future__ import annotations

import copy
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from decay.config import DEFAULTS, Config
from decay.storage import connect

TODAY = date(2026, 10, 20)
BASE = "https://betterme.world/articles/"


@pytest.fixture
def cfg(tmp_path):
    c = Config(settings=copy.deepcopy(DEFAULTS), today=TODAY, db_path=tmp_path / "decay.db")
    c.settings["competitor_check"] = False
    return c


@pytest.fixture
def store(cfg):
    return connect(cfg)


def row(keyword, slug, was=2, now=8, vol=1000, t_prev=300, t_now=60, url_now=None, status="both", **kw):
    url_prev = BASE + slug + "/"
    r = {
        "keyword": keyword, "volume": vol, "keyword_difficulty": 20, "best_position": now, "best_position_prev": was,
        "best_position_diff": None if now is None else now - was,
        "best_position_url": None if now is None else (url_now or url_prev), "best_position_url_prev": url_prev,
        "sum_traffic": t_now, "sum_traffic_prev": t_prev, "serp_features": [], "serp_features_prev": [],
        "positions_kinds": [], "positions_kinds_prev": [], "status": "right" if now is None else status,
        "is_informational": True, "is_commercial": False, "is_transactional": False, "is_navigational": False,
    }
    if now is None:  # mirror Ahrefs: lost rows only carry the *_prev values
        r.update({"keyword": None, "keyword_prev": keyword, "volume": None, "volume_prev": vol, "sum_traffic": None})
    r.update(kw)
    return r


def page_html(title="Wall Pilates for Beginners", h1=None, updated="March 3, 2025", words=1500, key_takeaways=True,
              faqs=6, question_h2s=(), table=True, imgs_no_alt=0, extra=""):
    filler = " ".join(["word"] * max(words - 50, 0))
    qa = "".join(f"<h2>{q}</h2><p>{' '.join(['answer'] * a)}</p>" for q, a in question_h2s)
    faq = "<h2>FAQs</h2>" + "".join(f"<h3>Question {i}?</h3><p>Answer {i}.</p>" for i in range(faqs)) if faqs else ""
    kt = "<h2>Key Takeaways</h2><ul><li>One</li></ul>" if key_takeaways else ""
    tbl = "<table><tr><td>a</td></tr></table>" if table else ""
    imgs = "".join('<img src="x.png">' for _ in range(imgs_no_alt))
    return f"""<html><head><title>{title}</title><meta name="description" content="d"></head><body>
<nav>menu menu menu</nav><article><h1>{h1 or title}</h1><p>Updated on {updated}</p>{kt}<p>{filler}</p>{qa}{tbl}{imgs}
<p>See <a href="/articles/other-page/">other</a>.</p>{extra}{faq}</article><footer>footer</footer></body></html>"""


class FakeResponse:
    def __init__(self, text="", status=200, url=""):
        self.text, self.status_code, self.url = text, status, url


class FakeFetcher:
    def __init__(self, pages=None):
        self.pages = pages or {}
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if url in self.pages:
            spec = self.pages[url]
            if isinstance(spec, str):
                return FakeResponse(spec, 200, url)
            return FakeResponse(spec.get("html", ""), spec.get("status", 200), spec.get("final_url", url))
        return FakeResponse(page_html(), 200, url)


class FakeAhrefs:
    def __init__(self, rows=None, aio_rows=None):
        self.rows = rows or []
        self.aio_rows = aio_rows or []
        self.calls = []
        self.followup_rows = []
        self.units_reported = 0

    def organic_keywords(self, params):
        self.calls.append(params)
        if "positions_kinds_prev" in params.get("where", ""):
            return copy.deepcopy(self.aio_rows)
        return copy.deepcopy(self.rows)

    def serp_overview(self, keyword, country, top):
        return []

    def url_keywords(self, url, country, date, keywords):
        return copy.deepcopy(self.followup_rows)

    def units_usage(self):
        return None


class FakeJira:
    def __init__(self, open_for=None, recent_for=None):
        self.open_for, self.recent_for = open_for or {}, recent_for or {}

    def check(self, url, slug, today, published, recent_days):
        o = SimpleNamespace(key=self.open_for[url]) if url in self.open_for else None
        r = SimpleNamespace(key=self.recent_for[url][0], published_days_ago=self.recent_for[url][1]) \
            if url in self.recent_for else None
        return o, r


class FakeNotion:
    SCHEMA = {"Name": "title", "New/Upd": "rich_text", "Status": "status", "URL 1": "url", "JIRA": "url",
              "Date": "date", "Primary category": "rich_text", "Brand/App": "rich_text", "Choose Primary": "select"}

    def __init__(self, schema=None):
        self.schema_props = dict(schema or self.SCHEMA)
        self.pages = {}
        self.comments = []

    def schema(self):
        return dict(self.schema_props)

    def _plain(self, props):
        out = {}
        for name, v in props.items():
            t = self.schema_props[name]
            if t in ("title", "rich_text"):
                out[name] = {"type": t, t: [{"plain_text": "".join(x["text"]["content"] for x in v[t])}]}
            else:
                out[name] = {"type": t, t: v[t]}
        return out

    def create_page(self, properties, children):
        pid = uuid.uuid4().hex
        page = {"id": pid, "url": f"https://www.notion.so/{pid}", "properties": self._plain(properties), "children": children}
        self.pages[pid] = page
        return page

    def get_page(self, pid):
        return self.pages[pid]

    def find_cards(self, url):
        return [p for p in self.pages.values() if (p["properties"].get("URL 1") or {}).get("url") == url]

    def comment(self, pid, text):
        self.comments.append((pid, text))

    def add_existing(self, url, status="In progress"):
        pid = uuid.uuid4().hex
        self.pages[pid] = {"id": pid, "url": f"https://www.notion.so/{pid}", "properties": {
            "URL 1": {"type": "url", "url": url}, "Status": {"type": "status", "status": {"name": status}}}}
        return pid
