from fastapi import APIRouter, Depends, Form, Request

import config
import db
from core import outbound, scheduler
from modules.pipeline import service
from web import STAFF, User, actor, back, render, require

router = APIRouter()


@router.get("/pipeline")
def pipeline(request: Request, f: str = "open", u: User = Depends(require(*STAFF))):
    cards = service.cards()
    shown = [c for c in cards if f == "all" or (f == "open" and c["status"] != "Done")
             or (f == "mismatch" and c["mismatch"]) or (f == "priority" and c["is_priority"])]
    pending = db.query("select * from actions where kind like 'notion.%%' and state in ('proposed','failed') "
                       "order by id desc limit 200")
    return render(request, "pipeline.html", u, cards=shown, f=f, n_mismatch=sum(c["mismatch"] for c in cards),
                  missing=service.missing_cards(), pending=pending, notion_ok=bool(config.NOTION_TOKEN),
                  synced=db.scalar("select max(synced_at) from notion_cards"), props=service.notion.PROPS)


@router.post("/pipeline/edit")
def edit(page_id: str = Form(...), prop: str = Form(...), value: str = Form(""), u: User = Depends(require("owner"))):
    a = service.propose_edit(page_id, prop, value, actor(u))
    if db.flag("notion_writes_enabled"):  # saving the field is the confirmation
        a = outbound.execute(a["id"], actor(u))
        if a["state"] == "sent":
            db.execute("update notion_cards set " + {"Name": "name",  # nosec B608
                                                     "Blog Category": "category", "New/Upd": "new_upd",
                                                     "URL 1": "url1"}[prop] + " = %s where page_id = %s",
                       (value, page_id))
        return back("/pipeline", f"Notion: {a['state']}")
    return back("/pipeline", "Saved as a proposed change: Notion writes are off (Admin → Settings)")


@router.post("/pipeline/create")
def create(key: str = Form(...), u: User = Depends(require("owner"))):
    service.propose_create(key, actor(u))
    return back("/pipeline#missing", f"Proposed a Notion card for {key}")


@router.post("/pipeline/sync")
def sync(u: User = Depends(require("owner"))):
    r = scheduler.run("sync_notion_status")
    return back("/pipeline", f"Notion sync: {r['status']} {r.get('error') or ''}")
