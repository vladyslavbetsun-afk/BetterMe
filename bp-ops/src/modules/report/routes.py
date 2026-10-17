from datetime import date

from fastapi import APIRouter, Depends, Form, Request

import config
import db
from core import business_days as bd
from core import slack
from modules.report import service
from web import STAFF, User, actor, back, render, require

router = APIRouter()


@router.get("/report")
def report(request: Request, day: str | None = None, u: User = Depends(require(*STAFF))):
    d = date.fromisoformat(day) if day else bd.local_today()
    f = service.facts(d)
    lines = db.query("select * from report_lines where day = %s order by id", (d,))
    msg = db.one("select * from outbound_messages where template = 'daily_report' and recipient = %s "
                 "and created_at::date = %s order by id desc limit 1", (config.SLACK_VOLODYMYR, d))
    return render(request, "report.html", u, f=f, text=service.text(f), day=d, lines=lines, msg=msg,
                  dm=slack.dm_link(config.SLACK_VOLODYMYR))


@router.post("/report/line")
def add_line(day: str = Form(...), text: str = Form(...), u: User = Depends(require("owner"))):
    if text.strip():
        db.execute("insert into report_lines (day, text, created_by) values (%s, %s, %s)", (day, text.strip(), actor(u)))
    return back(f"/report?day={day}")


@router.post("/report/line/{line_id}/delete")
def del_line(line_id: int, day: str = Form(...), u: User = Depends(require("owner"))):
    db.execute("delete from report_lines where id = %s", (line_id,))
    return back(f"/report?day={day}")


@router.post("/report/build")
def build(day: str = Form(...), u: User = Depends(require("owner"))):
    service.build(date.fromisoformat(day), actor(u))
    return back(f"/report?day={day}", "Draft ready")
