from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request

import config
import db
from core import business_days as bd
from core import slack
from modules.publish import service
from web import STAFF, User, actor, back, render, require

router = APIRouter()


@router.get("/publish")
def publish(request: Request, scope: str = "mine", u: User = Depends(require(*STAFF))):
    q = service.ready_queue(scope)
    pending = db.query("select * from actions where kind in ('jira.participants','jira.publish') and state in "
                       "('proposed','failed') order by id desc limit 100")
    return render(request, "publish.html", u, q=q, scope=scope, batches=service.batches(), live=service.live_ready(),
                  pending=pending, size=db.get_setting("publish.batch_size", 4),
                  default_when=bd.next_weekday_at(datetime.now(config.TZ)).strftime("%Y-%m-%dT%H:%M"),
                  yuliia_dm=slack.dm_link(config.SLACK_YULIIA_K), bot=slack.bot_configured())


@router.post("/publish/batch")
def create_batch(keys: list[str] = Form([]), suggest: str = Form(""), u: User = Depends(require("owner"))):
    if suggest:
        keys = service.suggest(int(db.get_setting("publish.batch_size", 4)))
    if not keys:
        return back("/publish", "Pick at least one ticket")
    b = service.create_batch(keys, actor(u))
    return back("/publish#batches", f"Batch {b['n']} created: {', '.join(keys)}")


@router.post("/publish/batch/{batch_id}/prepare")
def prepare(batch_id: str, when: str = Form(""), u: User = Depends(require("owner"))):
    post_at = None
    if when:
        post_at = datetime.fromisoformat(when).replace(tzinfo=config.TZ)
        delta = (post_at - datetime.now(config.TZ)).total_seconds()
        if delta < 180 or delta > 119 * 86400:
            return back("/publish#batches", "Pick a time between 3 minutes and 119 days from now")
    service.prepare_send(batch_id, actor(u), post_at)
    return back("/publish#batches", "Message drafted")


@router.post("/publish/batch/{batch_id}/archive")
def archive(batch_id: str, u: User = Depends(require("owner"))):
    db.execute("update batches set archived = true where id = %s", (batch_id,))
    db.audit(actor(u), "batch.archived", batch_id)
    return back("/publish#batches", "Archived")


@router.post("/publish/published")
def published(key: str = Form(...), u: User = Depends(require("owner"))):
    service.propose_published(key, actor(u))
    return back("/publish#pending", f"{key}: → Published proposed")
