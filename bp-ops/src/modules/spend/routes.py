import io
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import StreamingResponse

import config
import db
from core import business_days as bd
from core import outbound, people, slack
from modules.spend import compute
from web import MONEY, User, actor, back, render, require

router = APIRouter()
FIRST_MONTH = date(2026, 7, 1)


def _month(s: str | None) -> date:
    if s:
        return date.fromisoformat(s + "-01" if len(s) == 7 else s).replace(day=1)
    return bd.local_today().replace(day=1)


def _months() -> list[date]:
    out, d, end = [], FIRST_MONTH, bd.local_today().replace(day=1)
    while d <= end:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return list(reversed(out))


@router.get("/spend")
def spend(request: Request, month: str | None = None, u: User = Depends(require(*MONEY))):
    m = _month(month)
    v = compute.month_view(m)
    return render(request, "spend.html", u, v=v, m=m, months=_months(), cats=compute.CAT_ORDER,
                  labels=compute.CAT_LABEL, src=compute.SOURCE_LABEL, message=compute.budget_message(v),
                  roster=people.load(), dm=slack.dm_link(config.SLACK_YULIIA_H))


@router.post("/spend/recompute")
def recompute(month: str = Form(...), u: User = Depends(require("owner"))):
    n = compute.recompute(_month(month))
    return back(f"/spend?month={month}", f"Recomputed {n} lines" if n else "Month is closed: numbers are frozen")


@router.post("/spend/line")
def add_line(month: str = Form(...), person_id: str = Form(""), category: str = Form(...), amount: str = Form(...),
             note: str = Form(""), u: User = Depends(require(*MONEY))):
    m = _month(month)
    if compute.ensure_month(m)["status"] == "closed":
        return back(f"/spend?month={month}", "Month is closed")
    try:
        amt = Decimal(amount.replace(",", "").replace("$", ""))
    except InvalidOperation:
        return back(f"/spend?month={month}", "Amount must be a number")
    db.execute("insert into spend_lines (month, person_id, category, source, amount, amount_max, note) "
               "values (%s, %s, %s, 'manual', %s, %s, %s)", (m, person_id or None, category, amt, amt, note or None))
    db.audit(actor(u), "spend.line_added", month, {"person": person_id, "amount": str(amt), "note": note})
    return back(f"/spend?month={month}", "Line added")


@router.post("/spend/line/{line_id}/delete")
def del_line(line_id: int, month: str = Form(...), u: User = Depends(require(*MONEY))):
    n = db.execute("delete from spend_lines sl using spend_months sm where sl.id = %s and sl.source = 'manual' "
                   "and sm.month = sl.month and sm.status = 'open'", (line_id,))
    return back(f"/spend?month={month}", "Deleted" if n else "Only manual lines in an open month can be deleted")


@router.post("/spend/close")
def close(month: str = Form(...), u: User = Depends(require(*MONEY))):
    m = _month(month)
    compute.recompute(m)
    db.execute("update spend_months set status = 'closed', closed_at = now(), closed_by = %s where month = %s",
               (actor(u), m))
    db.audit(actor(u), "spend.closed", month)
    return back(f"/spend?month={month}", "Month closed: numbers are frozen")


@router.post("/spend/reopen")
def reopen(month: str = Form(...), u: User = Depends(require("owner"))):
    db.execute("update spend_months set status = 'open', closed_at = null, closed_by = null where month = %s",
               (_month(month),))
    db.audit(actor(u), "spend.reopened", month)
    return back(f"/spend?month={month}", "Month reopened")


@router.post("/spend/draft")
def draft(month: str = Form(...), u: User = Depends(require(*MONEY))):
    v = compute.month_view(_month(month))
    outbound.draft_message(kind="budget", channel="slack_dm", recipient=config.SLACK_YULIIA_H, template="budget",
                           body=compute.budget_message(v), ticket_keys=[], created_by=actor(u))
    return back(f"/spend?month={month}", "Slack draft saved (see Admin → Log)")


@router.get("/spend/{month}.xlsx")
def xlsx(month: str, u: User = Depends(require(*MONEY))):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    v = compute.month_view(_month(month))
    wb = Workbook()
    ws = wb.active
    ws.title = month
    ws.append(["Category", "Name", "Amount (min)", "Amount (max)", "Source", "Articles", "Unpriced", "Jira keys", "Note"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for cat in compute.CAT_ORDER:
        for r in v["cats"].get(cat, []):
            ws.append([compute.CAT_LABEL[cat], r["name"], float(r["amount"]), float(r["hi"]),
                       compute.SOURCE_LABEL[r["source"]], len(r["jira_keys"]), r["unpriced"],
                       ", ".join(r["jira_keys"]), r["note"]])
    ws.append([])
    ws.append(["Total", "", float(v["grand"][0]), float(v["grand"][1])])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="bp-spend-{month}.xlsx"'})
