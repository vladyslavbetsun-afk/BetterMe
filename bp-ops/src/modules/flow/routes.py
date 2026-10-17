from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import PlainTextResponse

from modules.flow import metrics, qa
from web import STAFF, User, back, render, require

router = APIRouter()


@router.get("/flow")
def flow(request: Request, u: User = Depends(require(*STAFF))):
    s = metrics.summary()
    return render(request, "flow.html", u, s=s, slack=metrics.slack_summary(s))


@router.get("/flow/summary.txt")
def summary_txt(u: User = Depends(require(*STAFF))):
    return PlainTextResponse(metrics.slack_summary(metrics.summary()))


@router.post("/flow/qa/recheck")
def recheck(key: str = Form(...), u: User = Depends(require("owner"))):
    qa.check([key])
    return back("/flow#qa", f"Rechecked {key}")
