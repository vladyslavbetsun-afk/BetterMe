"""Image status for tickets (spec 03 §7.3).

Until the Image Queue module ships (Phase 4) this uses the legacy rule from BP Publishing Batches: a ticket has images
when Oksana or Karina (by accountId) posted a link that isn't a live betterme.world page, a Google Doc or Jira.
"""

import config
import db
from core import rules


def image_links(keys: list[str]) -> dict[str, list[dict]]:
    if not keys:
        return {}
    rows = db.query("select jira_key, author_name, created_at, links from comments "
                    "where jira_key = any(%s) and author_account_id = any(%s) order by created_at",
                    (keys, list(config.IMAGE_POSTERS)))
    out: dict[str, list[dict]] = {k: [] for k in keys}
    for r in rows:
        for u in r["links"]:
            if rules.is_image_link(u):
                out[r["jira_key"]].append({"url": u, "by": r["author_name"], "at": r["created_at"]})
    return out


def status_for(keys: list[str]) -> dict[str, str]:
    """{key: "complete" | "pending" | "missing" | "not_needed"} — the fallback only knows complete/missing."""
    links = image_links(keys)
    return {k: "complete" if links.get(k) else "missing" for k in keys}
