"""Build Jira-shaped issues (REST v3: ADF comments, changelog) and load them through the real sync code."""

from datetime import datetime

import config
import db
from core import sync

# accountIds from the seeded roster
ME = config.OWNER_ACCOUNT_ID
EVE = "712020:51b52722-9eb1-4aa8-8b6d-527b045f3913"
JEREMY = "712020:4e42fbfd-ec2b-414f-99d4-41dfb6faa417"
EVA = "6348b6fe94b0b260830778d6"  # nutrition writer, skips expert review
CARTER = "712020:78a486c4-c1e4-4bc0-bba9-4676513ecb28"
GARETT = "5de4fe878389de0cd335416b"
ANGELICA = "712020:43ac8bef-1645-465e-9909-5bbb7ee20fa5"
MARIA = "712020:87a66480-0c2d-4444-be68-26bb3afbbd60"
TIM = config.TIM_ACCOUNT_ID
OKSANA = config.OKSANA_ACCOUNT_ID
YULIIA = config.YULIIA_K_ACCOUNT_ID
NAMES = {ME: "Vladyslav Betsun", EVE: "Evelyn Chalicha", JEREMY: "Jeremy Mukhwana", EVA: "Carla Eva De Angelis",
         CARTER: "Carter Lee", GARETT: "Garett Reid", ANGELICA: "Angelica Galvan", MARIA: "maria.eugenia.coaching",
         TIM: "Tim Jones", OKSANA: "Oksana Pidlisna", YULIIA: "Yuliia Koreniuk"}


def user(aid):
    return {"accountId": aid, "displayName": NAMES.get(aid, aid)} if aid else None


def adf(text: str = "", link: str | None = None, mention: str | None = None) -> dict:
    content = []
    if mention:
        content.append({"type": "mention", "attrs": {"id": mention, "text": "@" + NAMES.get(mention, "?")}})
    if text:
        content.append({"type": "text", "text": text})
    if link:
        content.append({"type": "inlineCard", "attrs": {"url": link}})
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": content}]}


_cid = [1000]


def comment(aid: str, at: datetime, text: str = "", link: str | None = None, mention: str | None = None) -> dict:
    _cid[0] += 1
    return {"id": str(_cid[0]), "author": user(aid), "created": at.isoformat(), "body": adf(text, link, mention)}


def history(at: datetime, *items, by: str = ME) -> dict:
    return {"created": at.isoformat(), "author": user(by), "items": list(items)}


def status_item(frm: str, to: str) -> dict:
    return {"field": "status", "fieldId": "status", "fromString": frm, "toString": to}


def field_item(field_id: str, frm: str | None, to: str | None) -> dict:
    return {"field": field_id, "fieldId": field_id, "from": frm, "to": to}


def issue(key: str, summary: str, status: str, created: datetime, *, author=None, expert=None, proof=None,
          participants=(), managers=(ME,), comments=(), histories=()) -> dict:
    return {"key": key, "fields": {
        "summary": summary, "status": {"name": status}, "issuetype": {"name": "Article"},
        "created": created.isoformat(), "updated": max([created, *[h_at(h) for h in histories]]).isoformat(),
        config.F_AUTHOR: user(author), config.F_EXPERT: user(expert), config.F_PROOFREADER: user(proof),
        config.F_PARTICIPANTS: [user(a) for a in participants], config.F_MANAGERS: [user(a) for a in managers],
        "comment": {"comments": list(comments)}},
        "changelog": {"histories": list(histories), "total": len(histories)}}


def h_at(h):
    return datetime.fromisoformat(h["created"])


def load(*issues: dict) -> None:
    for i in issues:
        n = sync.normalize(i, i["changelog"]["histories"])
        with db.conn() as c:
            sync.store(n, c)
    from modules.flow import metrics

    metrics.rebuild([i["key"] for i in issues])
