"""§5 keyword -> page rollup, plus URL normalization shared by every module."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

ARTICLE_RE = re.compile(r"^https://(www\.)?betterme\.world/articles/[^/]+/$")
BETTERME_HOST_RE = re.compile(r"^(www\.)?betterme\.world$")


def normalize_url(url: str | None, articles_only: bool = True) -> str | None:
    """Lowercase host, drop query/fragment, force a trailing slash, keep only article URLs.

    With articles_only=False any betterme.world URL is kept (used for cannibalization targets).
    """
    if not url:
        return None
    url = url.strip()
    if "://" not in url:
        url = "https://" + url.lstrip("/")
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path or "/"
    if not path.endswith("/"):
        path += "/"
    out = f"https://{host}{path}"
    if articles_only:
        return out if ARTICLE_RE.match(out) else None
    return out if BETTERME_HOST_RE.match(host) else None


def is_betterme_url(url: str | None) -> bool:
    return normalize_url(url, articles_only=False) is not None


def slug_of(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


@dataclass
class Page:
    url: str
    signals: list = field(default_factory=list)

    @property
    def slug(self) -> str:
        return slug_of(self.url)

    @property
    def lost_keywords(self) -> list[dict]:
        return [
            {"kw": s.keyword, "vol": s.volume, "was": s.was, "now": s.now, "traffic_prev": s.traffic_prev,
             "traffic_now": s.traffic_now, "kind": s.kind}
            for s in sorted(self.signals, key=lambda s: (-s.volume, -s.traffic_prev))
        ]

    @property
    def lost_top3_count(self) -> int:
        return len(self.signals)

    @property
    def lost_entirely_count(self) -> int:
        return sum(1 for s in self.signals if s.now is None)

    @property
    def traffic_lost(self) -> int:
        return sum(s.traffic_lost for s in self.signals)

    @property
    def main(self):
        return max(self.signals, key=lambda s: (s.volume, s.traffic_prev))

    @property
    def main_keyword(self) -> str:
        return self.main.keyword

    @property
    def main_now(self) -> int | None:
        return self.main.now

    @property
    def main_was(self) -> int | None:
        return self.main.was

    @property
    def worst_now(self) -> int | None:
        """Worst current position among the top-3 losses; None when any keyword was lost entirely."""
        if any(s.now is None for s in self.signals):
            return None
        return max(s.now for s in self.signals)

    @property
    def aio_appeared(self) -> bool:
        return any(s.aio_appeared for s in self.signals)

    @property
    def aio_citation_lost(self) -> bool:
        return any(s.aio_citation_lost for s in self.signals)

    @property
    def swapped_to(self) -> str | None:
        swaps = [s for s in self.signals if s.swapped_to]
        if not swaps:
            return None
        return max(swaps, key=lambda s: (s.volume, s.traffic_prev)).swapped_to

    @property
    def swapped_rank(self) -> int | None:
        swaps = [s for s in self.signals if s.swapped_to == self.swapped_to and s.now is not None]
        return min((s.now for s in swaps), default=None)

    @property
    def swapped_keyword(self) -> str | None:
        swaps = [s for s in self.signals if s.swapped_to == self.swapped_to]
        return swaps[0].keyword if swaps else None

    @property
    def intent_mix(self) -> float:
        if not self.signals:
            return 0.0
        return sum(1 for s in self.signals if s.is_commercial or s.is_transactional) / len(self.signals)

    @property
    def core_topic(self) -> str | None:
        return next((s.core_topic for s in self.signals if s.core_topic), None)

    def summary(self) -> dict:
        return {
            "url": self.url, "slug": self.slug, "lost_keywords": self.lost_keywords,
            "lost_top3_count": self.lost_top3_count, "lost_entirely_count": self.lost_entirely_count,
            "traffic_lost": self.traffic_lost, "main_keyword": self.main_keyword, "main_was": self.main_was,
            "main_now": self.main_now, "worst_now": self.worst_now, "aio_appeared": self.aio_appeared,
            "aio_citation_lost": self.aio_citation_lost, "swapped_to": self.swapped_to,
            "swapped_rank": self.swapped_rank, "intent_mix": round(self.intent_mix, 2), "core_topic": self.core_topic,
        }


def aggregate(signals) -> dict[str, Page]:
    pages: dict[str, Page] = {}
    for s in signals:
        pages.setdefault(s.url, Page(url=s.url)).signals.append(s)
    return pages
