"""Jira BP client.

Reads go through the platform's read-only account. Writes exist behind the `jira_writes_enabled` flag and are only
ever called from core/outbound.py. How the platform hands the app its Jira credentials is a Phase 0 question
(docs/decisions.md D-01, D-02); this module accepts any of:

  JIRA_PROXY_URL                  an authenticated proxy base URL provided by the platform (no auth header sent)
  JIRA_EMAIL + JIRA_API_TOKEN     basic auth for the read-only service account
  JIRA_BEARER_TOKEN               bearer token
Write credentials, if the platform admin approves a write path, use the JIRA_WRITE_* variants of the same names.
"""

import base64
import os
from datetime import datetime

import httpx

import config


class JiraError(RuntimeError):
    pass


class NotConfigured(JiraError):
    pass


def _env(prefix: str) -> tuple[str, dict] | None:
    proxy = os.environ.get(f"{prefix}PROXY_URL")
    if proxy:
        return proxy.rstrip("/"), {}
    email, token = os.environ.get(f"{prefix}EMAIL"), os.environ.get(f"{prefix}API_TOKEN")
    if email and token:
        raw = base64.b64encode(f"{email}:{token}".encode()).decode()
        return config.JIRA_SITE, {"Authorization": f"Basic {raw}"}
    bearer = os.environ.get(f"{prefix}BEARER_TOKEN")
    if bearer:
        return config.JIRA_SITE, {"Authorization": f"Bearer {bearer}"}
    return None


def auth_headers(write: bool = False) -> tuple[str, dict] | None:
    return _env("JIRA_WRITE_" if write else "JIRA_")


class JiraClient:
    def __init__(self, write: bool = False, transport: httpx.BaseTransport | None = None):
        cfg = auth_headers(write)
        if cfg is None and transport is None:
            raise NotConfigured("Jira write access is not configured" if write else "Jira access is not configured")
        base, headers = cfg or (config.JIRA_SITE, {})
        self.http = httpx.Client(base_url=base, headers={**headers, "Accept": "application/json"}, timeout=60,
                                 transport=transport)

    def _req(self, method: str, path: str, **kw) -> dict:
        r = self.http.request(method, path, **kw)
        if r.status_code == 404 and "search" in path:
            raise JiraError("Jira answered 404: the read-only account can't see project BP (spec 05 §3, Phase 0)")
        if r.status_code >= 400:
            raise JiraError(f"Jira {method} {path} → {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    # --- reads -----------------------------------------------------------------------------
    def search(self, jql: str, fields: list[str], expand: str | None = None, max_pages: int = 100) -> list[dict]:
        out, token = [], None
        for _ in range(max_pages):
            body = {"jql": jql, "fields": fields, "maxResults": 100}
            if expand:
                body["expand"] = expand
            if token:
                body["nextPageToken"] = token
            p = self._req("POST", "/rest/api/3/search/jql", json=body)
            out.extend(p.get("issues") or [])
            token = p.get("nextPageToken")
            if not token or p.get("isLast"):
                break
        return out

    def issue(self, key: str, fields: list[str]) -> dict:
        return self._req("GET", f"/rest/api/3/issue/{key}", params={"fields": ",".join(fields)})

    def changelog(self, key: str) -> list[dict]:
        out, start = [], 0
        while True:
            p = self._req("GET", f"/rest/api/3/issue/{key}/changelog", params={"startAt": start, "maxResults": 100})
            vals = p.get("values") or []
            out.extend(vals)
            start += len(vals)
            if not vals or p.get("isLast", True) or start >= p.get("total", 0):
                break
        return out

    def transitions(self, key: str) -> list[dict]:
        return self._req("GET", f"/rest/api/3/issue/{key}/transitions").get("transitions") or []

    def myself(self) -> dict:
        return self._req("GET", "/rest/api/3/myself")

    # --- writes (only via core/outbound.py) --------------------------------------------------------
    def transition(self, key: str, transition_id: str) -> None:
        self._req("POST", f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": str(transition_id)}})

    def edit(self, key: str, fields: dict) -> None:
        self._req("PUT", f"/rest/api/3/issue/{key}", json={"fields": fields})

    def comment(self, key: str, adf: dict, internal: bool) -> dict:
        body = {"body": adf}
        if internal:
            body["visibility"] = {"type": "role", "value": "Service Desk Team"}
        return self._req("POST", f"/rest/api/3/issue/{key}/comment", json=body)


# --- parsing -------------------------------------------------------------------------------------

def parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if len(s) > 5 and s[-5] in "+-" and s[-3] != ":":  # Jira uses +0200
        s = s[:-2] + ":" + s[-2:]
    return datetime.fromisoformat(s)


def adf_parse(body) -> tuple[str, list[str], list[str]]:
    """(plain text, links, mentioned accountIds) from an ADF document (or a plain string)."""
    from core.rules import urls_in

    if body is None:
        return "", [], []
    if isinstance(body, str):
        return body.strip(), urls_in(body), []
    parts: list[str] = []
    links: list[str] = []
    mentions: list[str] = []

    def walk(n):
        if isinstance(n, list):
            for x in n:
                walk(x)
            return
        if not isinstance(n, dict):
            return
        t = n.get("type")
        attrs = n.get("attrs") or {}
        if t == "text":
            parts.append(n.get("text", ""))
            for m in n.get("marks") or []:
                href = (m.get("attrs") or {}).get("href") if m.get("type") == "link" else None
                if href and href not in links:
                    links.append(href)
        elif t == "mention":
            parts.append(attrs.get("text") or "@?")
            if attrs.get("id"):
                mentions.append(attrs["id"])
        elif t in ("inlineCard", "blockCard", "embedCard"):
            url = attrs.get("url")
            if url:
                parts.append(url)
                if url not in links:
                    links.append(url)
        elif t == "hardBreak":
            parts.append("\n")
        walk(n.get("content") or [])
        if t in ("paragraph", "heading", "listItem"):
            parts.append("\n")

    walk(body)
    text = "".join(parts).replace("​", "").replace("‌", "")
    text = "\n".join(line.strip() for line in text.splitlines()).strip()
    for u in urls_in(text):
        if u not in links:
            links.append(u)
    return text, links, mentions


def account_id(v) -> str | None:
    return v.get("accountId") if isinstance(v, dict) else None


def account_ids(v) -> list[str]:
    if isinstance(v, dict):
        v = [v]
    return [x["accountId"] for x in (v or []) if isinstance(x, dict) and x.get("accountId")]


def mention_adf(account: str, name: str, text: str) -> dict:
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [
        {"type": "mention", "attrs": {"id": account, "text": "@" + name}},
        {"type": "text", "text": " " + text}]}]}
