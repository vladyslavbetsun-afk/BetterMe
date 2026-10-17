"""BP Ops: one app for the BetterMe blog pipeline (docs/specs/05-bp-ops-slop-machine-migration.md)."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import db
import jobs  # noqa: F401 - registers the jobs
from core import jira, outbound, scheduler
from modules.admin.routes import router as admin_router
from modules.assign.routes import router as assign_router
from modules.flow.routes import router as flow_router
from modules.images.routes import router as images_router
from modules.load.routes import router as load_router
from modules.phase4.routes import router as phase4_router
from modules.pipeline.routes import router as pipeline_router
from modules.publish.routes import router as publish_router
from modules.report.routes import router as report_router
from modules.review.routes import router as review_router
from modules.spend.routes import router as spend_router
from web import STAFF, User, actor, back, current_user, require

logging.basicConfig(level=logging.INFO)
_started = {"ok": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.migrate()
    scheduler.start()
    _started["ok"] = True
    yield
    scheduler.stop()
    db.close()


app = FastAPI(title="BP Ops", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
for r in (flow_router, pipeline_router, assign_router, review_router, load_router, publish_router, report_router,
          spend_router, admin_router, images_router, phase4_router):
    app.include_router(r)


@app.exception_handler(403)
async def forbidden(request: Request, exc):
    return HTMLResponse(f"<h1>No access</h1><p>{getattr(exc, 'detail', '')}</p><p>Ask Vladyslav to add you in "
                        "BP Ops → Admin → Roster.</p>", status_code=403)


# --- platform health paths -----------------------------------------------------------------------

@app.get("/ping")
def ping():
    return PlainTextResponse("pong")


@app.get("/startup")
def startup():
    return JSONResponse({"ok": _started["ok"]}, status_code=200 if _started["ok"] else 503)


@app.get("/selftest")
def selftest():
    """Database reachable, schema present, roster seeded, rules sane. Secrets are reported, never required."""
    checks = {}
    try:
        checks["db"] = db.scalar("select 1") == 1
        checks["schema"] = db.scalar("select count(*) from information_schema.tables where table_name in "
                                     "('tickets','people','outbound_messages','actions','job_runs')") == 5
        checks["roster"] = (db.scalar("select count(*) from people where role = 'writer' and active") or 0) > 0
        checks["idempotency_unique"] = bool(db.scalar(
            "select count(*) from pg_indexes where tablename = 'outbound_messages' and indexdef ilike '%unique%"
            "idempotency_key%'"))
    except Exception as e:  # report, don't crash the probe
        checks["error"] = str(e)
    from core import rules

    checks["rules"] = rules.word_count("x, 1,800 words") == (1800, 1800) and rules.word_count("x, 12k") is None
    ok = all(v is True for k, v in checks.items() if k != "error") and "error" not in checks
    return JSONResponse({"ok": ok, "checks": checks, "configured": {
        "jira": jira.auth_headers() is not None, "jira_write": jira.auth_headers(write=True) is not None,
        "notion": bool(__import__("config").NOTION_TOKEN), "ahrefs": bool(__import__("config").AHREFS_API_KEY)}},
        status_code=200 if ok else 500)


@app.get("/")
def home(request: Request):
    u = current_user(request)
    if u.role in STAFF:
        return RedirectResponse("/flow")
    if u.role == "finance":
        return RedirectResponse("/spend")
    if u.role == "designer":
        return RedirectResponse("/images?me=1")
    return HTMLResponse("<h1>BP Ops</h1><p>You're signed in as " + (u.email or "nobody") +
                        ", which isn't on the BP Ops roster. Ask Vladyslav for access.</p>", status_code=403)


# --- shared action / message endpoints (everything goes through core/outbound.py) --------------------

@app.post("/actions/{action_id}/execute")
def action_execute(action_id: int, next: str = Form("/"), u: User = Depends(require("owner"))):
    try:
        a = outbound.execute(action_id, actor(u))
    except PermissionError as e:
        return back(next, str(e))
    return back(next, f"Done: {a['payload'].get('description', a['kind'])}" if a["state"] == "sent"
                else f"Not done ({a['state']}): {a.get('error') or ''}")


@app.post("/actions/{action_id}/cancel")
def action_cancel(action_id: int, next: str = Form("/"), u: User = Depends(require("owner"))):
    outbound.cancel(action_id, actor(u))
    return back(next, "Dismissed")


@app.post("/messages/{message_id}/sent")
def message_sent(message_id: int, next: str = Form("/"), u: User = Depends(require("owner"))):
    m = db.one("select * from outbound_messages where id = %s", (message_id,))
    ok = outbound.mark_sent(message_id, actor(u))
    if ok and m and m["template"] == "publishing_batch":
        db.execute("update batches set sent_at = coalesce(sent_at, now()) where message_id = %s", (message_id,))
    return back(next, "Marked as sent" if ok else "Already marked")


@app.post("/messages/{message_id}/cancel")
def message_cancel(message_id: int, next: str = Form("/"), u: User = Depends(require("owner"))):
    outbound.cancel_message(message_id, actor(u))
    return back(next, "Draft discarded")


@app.post("/messages/{message_id}/post")
def message_post(message_id: int, next: str = Form("/"), u: User = Depends(require("owner"))):
    try:
        ok = outbound.send_via_bot(message_id, actor(u))
    except Exception as e:
        return back(next, f"Not posted: {e}")
    if ok:
        db.execute("update batches set sent_at = coalesce(sent_at, now()) where message_id = %s", (message_id,))
    return back(next, "Posted" if ok else "Already posted")
