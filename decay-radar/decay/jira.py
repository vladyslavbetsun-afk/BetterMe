"""Read-only check for an existing BP update ticket (spec §6, `betterme-article-update-finder` step 5).

A loose `text ~ slug` match is only a candidate. The ticket counts only when the
exact URL appears on its `Article:` / `Original article:` line, because similar
slugs ("chair pilates for seniors" vs "chair pilates workout") are a known
false-positive trap.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import requests

from .aggregate import normalize_url

URL_RE = re.compile(r"https?://[^\s)\]>\"'|]+")
ARTICLE_LINE_RE = re.compile(r"^\W*(original article|article)\W*:", re.I)


@dataclass
class TicketMatch:
    key: str
    status: str
    published_days_ago: int | None
    open: bool


def adf_text(node) -> str:
    """Flatten Atlassian Document Format to text, keeping link hrefs inline and breaks as newlines."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    if t == "text":
        out = node.get("text", "")
        for m in node.get("marks", []) or []:
            if m.get("type") == "link":
                href = (m.get("attrs") or {}).get("href")
                if href and href not in out:
                    out += f" {href}"
        return out
    if t in ("inlineCard", "blockCard", "embedCard"):
        return " " + (node.get("attrs") or {}).get("url", "") + " "
    if t == "hardBreak":
        return "\n"
    inner = adf_text(node.get("content", []))
    if t in ("paragraph", "heading", "listItem", "codeBlock"):
        return inner + "\n"
    return inner


def article_urls(description) -> set[str]:
    text = adf_text(description) if not isinstance(description, str) else description
    found = set()
    for line in text.splitlines():
        if ARTICLE_LINE_RE.match(line.strip("*_ ")) or ARTICLE_LINE_RE.match(line):
            for u in URL_RE.findall(line):
                n = normalize_url(u)
                if n:
                    found.add(n)
    return found


def match_tickets(url: str, issues: list[dict], today: date, published_status: str, recent_days: int):
    """Returns (open_ticket, recent_ticket) TicketMatch objects (or None) for issues that cite this exact URL."""
    open_t = recent_t = None
    for issue in issues:
        f = issue.get("fields", {})
        if url not in article_urls(f.get("description")):
            continue
        status = (f.get("status") or {}).get("name", "")
        if status.lower() != published_status.lower():
            if open_t is None:
                open_t = TicketMatch(issue["key"], status, None, True)
            continue
        changed = f.get("statuscategorychangedate") or f.get("resolutiondate") or f.get("updated")
        days = None
        if changed:
            try:
                days = (today - datetime.fromisoformat(changed[:19]).date()).days
            except ValueError:
                days = None
        if days is not None and days <= recent_days and recent_t is None:
            recent_t = TicketMatch(issue["key"], status, days, False)
    return open_t, recent_t


class JiraClient:
    def __init__(self, base_url: str, email: str, token: str, project: str = "BP", session: requests.Session | None = None):
        self.base = base_url.rstrip("/")
        self.project = project
        self.session = session or requests.Session()
        self.session.auth = (email, token)
        self.session.headers.update({"Accept": "application/json"})

    def search_slug(self, slug: str) -> list[dict]:
        jql = f'project = {self.project} AND text ~ "{slug}" ORDER BY created DESC'
        resp = self.session.get(f"{self.base}/rest/api/3/search/jql", params={
            "jql": jql, "maxResults": 25,
            "fields": "summary,description,status,updated,resolutiondate,statuscategorychangedate",
        }, timeout=30)
        resp.raise_for_status()
        return resp.json().get("issues", [])

    def check(self, url: str, slug: str, today: date, published_status: str, recent_days: int):
        return match_tickets(url, self.search_slug(slug), today, published_status, recent_days)
