"""Ahrefs API v3 client: organic-keywords compare, serp-overview, follow-up checks, unit guard (spec §3).

Field names were checked against the v3 OpenAPI schema (via the Ahrefs `doc` tool)
on 2026-10-17. `site-explorer-keywords-history` only returns per-bucket counts
(top3 / top4_10 / ...), not per-keyword positions, so follow-ups use
organic-keywords with mode=exact on the URL instead (docs/decisions.md D-03).
"""
from __future__ import annotations

import json
import logging

import requests

log = logging.getLogger(__name__)

API = "https://api.ahrefs.com/v3"

# §3 select, corrected against live responses on 2026-10-17 (docs/decisions.md D-03, D-04):
# - keyword/volume are null on rows lost entirely (status "right"); keyword_prev/volume_prev carry them.
# - positions_kinds(_prev) can be filtered on but not selected, so AI Overview citation loss is a
#   second, filter-only query (aio_params) instead of a column.
# - keyword_difficulty adds ~10 units/row and no rule uses it, so it is not selected.
# - is_navigational is added because §4 drops navigational rows.
DETECT_SELECT = [
    "keyword", "keyword_prev", "volume", "volume_prev", "best_position", "best_position_prev", "best_position_diff",
    "best_position_url", "best_position_url_prev", "sum_traffic", "sum_traffic_prev", "serp_features",
    "serp_features_prev", "status", "is_informational", "is_commercial", "is_transactional", "is_navigational",
]
AIO_SELECT = ["keyword", "keyword_prev", "best_position_url_prev"]
FOLLOWUP_SELECT = ["keyword", "best_position", "best_position_url", "sum_traffic", "serp_features"]

MIN_UNITS_PER_REQUEST = 50


class UnitBudgetExceeded(RuntimeError):
    pass


class AhrefsError(RuntimeError):
    pass


def estimate_units(cfg, calls: int = 1) -> int:
    """Upper bound for one run: detection rows + AI Overview rows, per country (observed per-row costs in settings)."""
    detect = max(MIN_UNITS_PER_REQUEST, cfg["max_rows"] * cfg["units_per_row"])
    aio = max(MIN_UNITS_PER_REQUEST, cfg["aio_max_rows"] * cfg["aio_units_per_row"])
    return calls * (detect + aio)


def guard_units(estimate: int, budget: int) -> None:
    if estimate > budget:
        raise UnitBudgetExceeded(
            f"Unit guard: this run would cost up to {estimate:,} Ahrefs units, above max_units_per_run={budget:,}. "
            "Lower max_rows or the country list, or raise max_units_per_run."
        )


def detect_where(volume_floor: int) -> dict:
    return {"and": [
        {"field": "is_best_position_set_top_3_prev", "is": ["eq", True]},
        {"field": "is_main_position_prev", "is": ["eq", True]},
        {"or": [
            {"field": "best_position", "is": ["gt", 3]},
            {"field": "best_position", "is": "is_null"},
        ]},
        {"field": "volume", "is": ["gte", volume_floor]},
    ]}


def aio_where(volume_floor: int) -> dict:
    """Rows whose page was cited in the AI Overview on the comparison date and is not cited now."""
    base = detect_where(volume_floor)
    base["and"] += [
        {"field": "positions_kinds_prev", "list_is": {"any": ["eq", "ai_overview_found"]}},
        {"not": {"field": "positions_kinds", "list_is": {"any": ["eq", "ai_overview_found"]}}},
    ]
    return base


def aio_params(cfg, country: str, date: str, date_compared: str) -> dict:
    p = detect_params(cfg, country, date, date_compared)
    p.update({"select": ",".join(AIO_SELECT), "where": json.dumps(aio_where(cfg["api_volume_floor"])),
              "limit": cfg["aio_max_rows"]})
    p.pop("order_by")
    return p


def detect_params(cfg, country: str, date: str, date_compared: str) -> dict:
    return {
        "target": cfg["target"],
        "mode": "prefix",
        "country": country,
        "date": date,
        "date_compared": date_compared,
        "select": ",".join(DETECT_SELECT),
        "where": json.dumps(detect_where(cfg["api_volume_floor"])),
        "order_by": "sum_traffic_prev:desc",
        "limit": cfg["max_rows"],
        "output": "json",
    }


class AhrefsClient:
    def __init__(self, api_key: str, session: requests.Session | None = None, timeout: int = 60):
        if not api_key:
            raise AhrefsError("AHREFS_API_KEY is not set (put it in .env; never commit it).")
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
        self.timeout = timeout
        self.units_reported = 0

    def _get(self, path: str, params: dict) -> dict:
        resp = self.session.get(f"{API}/{path}", params=params, timeout=self.timeout)
        headers = {k.lower(): v for k, v in resp.headers.items()}
        cost = headers.get("x-api-units-cost-total-actual") or headers.get("x-api-units-cost-total")
        if cost:
            try:
                self.units_reported += int(float(cost))
            except ValueError:
                pass
        if resp.status_code != 200:
            raise AhrefsError(f"Ahrefs {path} -> HTTP {resp.status_code}: {resp.text[:400]}")
        return resp.json()

    def organic_keywords(self, params: dict) -> list[dict]:
        return self._get("site-explorer/organic-keywords", params).get("keywords", [])

    def serp_overview(self, keyword: str, country: str, top: int) -> list[dict]:
        data = self._get("serp-overview/serp-overview", {
            "keyword": keyword, "country": country, "top_positions": top,
            "select": "position,url,type,title", "output": "json",
        })
        return data.get("positions", [])

    def url_keywords(self, url: str, country: str, date: str, keywords: list[str]) -> list[dict]:
        """Follow-up check (§11): current positions of the lost keywords on one URL."""
        where = {"or": [{"field": "keyword", "is": ["eq", k]} for k in keywords]}
        return self.organic_keywords({
            "target": url, "mode": "exact", "country": country, "date": date,
            "select": ",".join(FOLLOWUP_SELECT), "where": json.dumps(where),
            "limit": max(len(keywords), 1), "output": "json",
        })

    def units_usage(self) -> dict | None:
        try:
            return self._get("subscription-info/limits-and-usage", {})
        except AhrefsError as exc:  # informational only
            log.warning("limits-and-usage unavailable: %s", exc)
            return None


def units_used_between(before: dict | None, after: dict | None) -> int | None:
    """Diff of `units_usage_api_key` from subscription-info/limits-and-usage."""
    def pick(d):
        if not d:
            return None
        body = d.get("limits_and_usage", d)
        for key in ("units_usage_api_key", "units_usage_workspace"):
            if isinstance(body.get(key), (int, float)):
                return body[key]
        return None

    b, a = pick(before), pick(after)
    if b is None or a is None:
        return None
    return int(a - b)
