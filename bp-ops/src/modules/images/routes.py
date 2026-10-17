import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

import db
from modules.images import service
from web import ALL, User, current_user, render, require

router = APIRouter()


@router.get("/api/images/status")
def status(request: Request, keys: str = ""):
    """Ticket badge API (spec 03 §7.3). Behind the same login as the rest of the app."""
    if current_user(request).role not in ALL:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    t = time.perf_counter()
    ks = [k.strip() for k in keys.split(",") if k.strip()][:200]
    out = service.status_for(ks)
    return JSONResponse(out, headers={"Server-Timing": f"db;dur={(time.perf_counter() - t) * 1000:.1f}"})


@router.get("/images")
def images(request: Request, u: User = Depends(require(*ALL))):
    ready = db.query("select jira_key, summary, entered_ready_at from tickets where status = 'Ready' order by jira_key")
    st = service.status_for([r["jira_key"] for r in ready])
    missing = [r for r in ready if st[r["jira_key"]] == "missing"]
    return render(request, "images.html", u, missing=missing, n_ready=len(ready))
