from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request

import db
from core import people, scheduler
from web import User, actor, back, render, require

router = APIRouter()
FLAGS = ["jira_writes_enabled", "slack_send_enabled", "notion_writes_enabled", "review_automation_enabled",
         "review_automation_dry_run", "pipeline.auto_close"]


@router.get("/admin")
def admin(request: Request, u: User = Depends(require("owner"))):
    settings = {r["key"]: r["value"] for r in db.query("select * from settings order by key")}
    runs = db.query("select * from job_runs order by started_at desc limit 40")
    return render(request, "admin.html", u, settings=settings, flag_names=FLAGS, jobs=scheduler.health(), runs=runs)


@router.post("/admin/settings")
async def save_settings(request: Request, u: User = Depends(require("owner"))):
    form = await request.form()
    for f in FLAGS:
        db.set_setting(f, form.get(f) == "on")
    if form.get("holidays") is not None:
        hol = [h.strip() for h in str(form["holidays"]).replace(",", "\n").splitlines() if h.strip()]
        try:
            [date.fromisoformat(h) for h in hol]
        except ValueError:
            return back("/admin", "Holidays must be dates like 2026-12-25")
        db.set_setting("holidays", hol)
    if form.get("batch_size"):
        db.set_setting("publish.batch_size", int(form["batch_size"]))
    db.audit(actor(u), "settings.saved", None, {k: form.get(k) for k in FLAGS})
    return back("/admin", "Settings saved")


@router.post("/admin/jobs/{name}/run")
def run_job(name: str, u: User = Depends(require("owner"))):
    if name not in scheduler.JOBS:
        return back("/admin", "Unknown job")
    r = scheduler.run(name)
    db.audit(actor(u), "job.run_now", name, {"status": r["status"]})
    return back("/admin#jobs", f"{name}: {r['status']} {(r.get('error') or '')[:200]}")


@router.get("/admin/roster")
def roster(request: Request, u: User = Depends(require("owner"))):
    ros = people.load()
    aliases = db.query("select * from person_aliases order by person_id, alias")
    return render(request, "roster.html", u, roster=ros, aliases=aliases, today=date.today())


@router.post("/admin/person")
def save_person(id: str = Form(...), display_name: str = Form(...), email: str = Form(""), jira_account_id: str = Form(""),
                slack_id: str = Form(""), role: str = Form(...), niche: str = Form(""), app_role: str = Form(""),
                skip_expert_review: str = Form(""), active: str = Form(""), notes: str = Form(""),
                u: User = Depends(require("owner"))):
    pid = id.strip().lower().replace(" ", "_")
    db.execute("insert into people (id, display_name, email, jira_account_id, slack_id, role, niche, app_role, "
               "skip_expert_review, active, notes) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (id) do update "
               "set display_name = excluded.display_name, email = excluded.email, jira_account_id = excluded.jira_account_id, "
               "slack_id = excluded.slack_id, role = excluded.role, niche = excluded.niche, app_role = excluded.app_role, "
               "skip_expert_review = excluded.skip_expert_review, active = excluded.active, notes = excluded.notes",
               (pid, display_name.strip(), email.strip() or None, jira_account_id.strip() or None,
                slack_id.strip() or None, role, niche or None, app_role or None, skip_expert_review == "on",
                active == "on", notes or None))
    db.audit(actor(u), "roster.person_saved", pid)
    return back("/admin/roster", f"Saved {display_name}")


@router.post("/admin/rate")
def add_rate(person_id: str = Form(...), amount: str = Form(...), amount_max: str = Form(""), unit: str = Form(...),
             billing: str = Form(""), effective_from: str = Form(...), kind: str = Form("base"), note: str = Form(""),
             u: User = Depends(require("owner"))):
    try:
        amt = Decimal(amount)
        mx = Decimal(amount_max) if amount_max else None
        eff = date.fromisoformat(effective_from)
    except (InvalidOperation, ValueError):
        return back("/admin/roster", "Check the amount and the date")
    people.set_rate(person_id, amt, unit, eff, billing or None, mx, kind, note or None)
    db.audit(actor(u), "roster.rate_added", person_id, {"amount": amount, "unit": unit, "from": effective_from})
    return back("/admin/roster", "Rate added; earlier months keep the old rate")


@router.post("/admin/alias")
def add_alias(alias: str = Form(...), person_id: str = Form(...), u: User = Depends(require("owner"))):
    db.execute("insert into person_aliases (alias, person_id) values (lower(%s), %s) on conflict (alias) do update "
               "set person_id = excluded.person_id", (alias.strip(), person_id))
    return back("/admin/roster", "Alias saved")


@router.get("/admin/log")
def log(request: Request, q: str = "", u: User = Depends(require("owner"))):
    like = f"%{q}%"
    actions = db.query("select * from actions where %s = '' or jira_key ilike %s or kind ilike %s or payload::text ilike %s "
                       "order by id desc limit 200", (q, like, like, like))
    msgs = db.query("select * from outbound_messages where %s = '' or body ilike %s or recipient ilike %s or "
                    "array_to_string(ticket_keys, ',') ilike %s order by id desc limit 200", (q, like, like, like))
    audit = db.query("select * from audit_log where %s = '' or action ilike %s or target ilike %s or detail::text ilike %s "
                     "order by at desc limit 300", (q, like, like, like))
    return render(request, "log.html", u, actions=actions, msgs=msgs, audit=audit, q=q)


@router.get("/admin/import-report")
def import_report(request: Request, u: User = Depends(require("owner"))):
    issues = db.query("select * from import_issues order by at desc, id limit 500")
    counts = {t: db.scalar(f"select count(*) from {t}") for t in  # nosec B608
              ("people", "rates", "settings", "exclusions", "overrides", "expert_asks", "outbound_messages",
               "audit_log", "batches", "batch_items", "spend_lines", "articles", "article_events",
               "ahrefs_page_weekly", "ai_citations_weekly", "tickets", "comments", "status_transitions")}
    return render(request, "import_report.html", u, issues=issues, counts=counts)
