from fastapi import APIRouter, Depends, Form, Request

import db
from modules.assign import service
from web import STAFF, User, actor, back, render, require

router = APIRouter()


@router.get("/assign")
def assign(request: Request, key: str | None = None, u: User = Depends(require(*STAFF))):
    v = service.view(key)
    pending = db.query("select * from actions where kind = 'jira.assign' and state in ('proposed','failed') "
                       "order by id desc limit 50")
    return render(request, "assign.html", u, v=v, pending=pending)


@router.post("/assign")
def do_assign(key: str = Form(...), writer: str = Form(...), u: User = Depends(require("owner"))):
    try:
        a, desc = service.propose_assign(key, writer, actor(u))
    except ValueError as e:
        return back(f"/assign?key={key}", str(e))
    return back(f"/assign?key={key}#pending", f"{key}: {desc} — confirm below")
