"""§3 query rows -> §4 noise filters -> decay signals (one per keyword/page)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .aggregate import is_betterme_url, normalize_url

AIO_FEATURE = "ai_overview"
AIO_CITED = {"ai_overview_found", "ai_overview", "ai_overview_sitelink"}


@dataclass
class Signal:
    keyword: str
    url: str
    volume: int
    kd: int | None
    was: int | None
    now: int | None  # None = lost entirely
    traffic_prev: int
    traffic_now: int
    kind: str  # dropped | lost | swapped
    aio_appeared: bool
    aio_citation_lost: bool
    swapped_to: str | None
    is_commercial: bool = False
    is_transactional: bool = False
    is_informational: bool = False
    core_topic: str | None = None

    @property
    def traffic_lost(self) -> int:
        return max(self.traffic_prev - self.traffic_now, 0)

    def to_row(self, run_id: int) -> dict:
        d = asdict(self)
        return {
            "run_id": run_id, "keyword": d["keyword"], "url": d["url"], "volume": d["volume"], "kd": d["kd"],
            "was": d["was"], "now": d["now"], "traffic_prev": d["traffic_prev"], "traffic_now": d["traffic_now"],
            "kind": d["kind"], "aio_appeared": d["aio_appeared"], "aio_citation_lost": d["aio_citation_lost"],
            "swapped_to": d["swapped_to"],
        }


def core_topic(cfg, *texts: str) -> str | None:
    hay = " ".join(t.lower() for t in texts if t)
    for topic, needles in cfg["core_topics"].items():
        if any(re.search(r"(?<![a-z])" + re.escape(n) + r"(?![a-z])", hay) for n in needles):
            return topic
    return None


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def classify_row(cfg, row: dict, aio_lost: set | None = None) -> tuple[Signal | None, str]:
    """Returns (signal, "") when the row passes §4, else (None, reason_code)."""
    url_prev = normalize_url(row.get("best_position_url_prev"))
    if not url_prev:
        return None, "not_article"
    if row.get("is_navigational"):
        return None, "navigational"

    # Lost rows (status "right") only carry the comparison-date values.
    keyword = row.get("keyword") or row.get("keyword_prev") or ""
    volume = _int(row.get("volume") if row.get("volume") is not None else row.get("volume_prev"))
    topic = core_topic(cfg, keyword, url_prev)
    floor = cfg["min_volume_core"] if topic else cfg["min_volume"]
    if volume < floor:
        return None, "low_volume"

    was = row.get("best_position_prev")
    now = row.get("best_position")
    lost = now is None or row.get("status") == "right"
    if lost:
        now = None
    t_prev, t_now = _int(row.get("sum_traffic_prev")), _int(row.get("sum_traffic"))
    if lost:
        t_now = 0
    t_lost = t_prev - t_now

    if not lost and t_lost < cfg["min_traffic_lost"]:
        return None, "low_traffic_lost"
    if was == 3 and now == 4 and t_lost < cfg["wobble_min_traffic_lost"]:
        return None, "wobble_3_to_4"

    url_now_raw = row.get("best_position_url")
    swapped_to = None
    if not lost and url_now_raw and is_betterme_url(url_now_raw):
        url_now = normalize_url(url_now_raw, articles_only=False)
        if url_now and url_now != url_prev:
            swapped_to = url_now

    serp, serp_prev = set(row.get("serp_features") or []), set(row.get("serp_features_prev") or [])
    kinds, kinds_prev = set(row.get("positions_kinds") or []), set(row.get("positions_kinds_prev") or [])
    aio_appeared = AIO_FEATURE in serp and AIO_FEATURE not in serp_prev
    aio_citation_lost = (keyword, url_prev) in (aio_lost or set()) or \
        (bool(kinds_prev & AIO_CITED) and not (kinds & AIO_CITED))

    kind = "lost" if lost else ("swapped" if swapped_to else "dropped")
    return Signal(
        keyword=keyword, url=url_prev, volume=volume, kd=row.get("keyword_difficulty"), was=was, now=now,
        traffic_prev=t_prev, traffic_now=t_now, kind=kind, aio_appeared=aio_appeared,
        aio_citation_lost=aio_citation_lost, swapped_to=swapped_to,
        is_commercial=bool(row.get("is_commercial")), is_transactional=bool(row.get("is_transactional")),
        is_informational=bool(row.get("is_informational")), core_topic=topic,
    ), ""


def aio_lost_keys(rows: list[dict]) -> set:
    """(keyword, page) pairs from the AI Overview citation-loss query (ahrefs.aio_params)."""
    return {(r.get("keyword") or r.get("keyword_prev") or "", normalize_url(r.get("best_position_url_prev"))) for r in rows}


def detect(cfg, rows: list[dict], aio_rows: list[dict] | None = None) -> tuple[list[Signal], dict]:
    signals, dropped = [], {}
    seen = set()
    aio_lost = aio_lost_keys(aio_rows or [])
    for row in rows:
        sig, reason = classify_row(cfg, row, aio_lost)
        if sig is None:
            dropped[reason] = dropped.get(reason, 0) + 1
            continue
        if (sig.keyword, sig.url) in seen:
            continue
        seen.add((sig.keyword, sig.url))
        signals.append(sig)
    return signals, dropped
