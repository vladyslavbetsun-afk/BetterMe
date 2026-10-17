from fastapi import APIRouter, Depends, Form, Request

import config
import db
from core import business_days as bd
from core import jira, outbound, rules, slack
from modules.review import logic, service
from web import STAFF, User, actor, back, render, require

router = APIRouter()


@router.get("/review")
def review(request: Request, scope: str = "mine", u: User = Depends(require(*STAFF))):
    D, ctx = service.state(scope)
    writers = {}
    for t in D["no_reply"] + [a.t for a in D["flagged"]]:
        if t.writer_id and (t.to_writer or t in [a.t for a in D["flagged"]]):
            writers.setdefault(t.writer_id, ctx.roster.get(t.writer_id))
    drafts = db.query("select * from outbound_messages where channel = 'slack_dm' and state = 'draft' "
                      "and template in ('writer_followup','writer_followup_repeat','status') order by id desc")
    for d in drafts:
        p = ctx.roster.get(d["recipient"])
        d["who"] = p.display_name if p else d["recipient"]
        d["dm"] = slack.dm_link(p.slack_id if p else None)
    pending = db.query("select * from actions where kind like 'jira.review%%' and state in ('proposed','failed') "
                       "order by id desc limit 100")
    log = db.query("select * from audit_log where action like 'review.%%' or action like 'action.jira%%' "
                   "or action like 'message.%%' order by at desc limit 60")
    excluded = db.query("select * from exclusions order by at desc")
    experts = [p for p in ctx.roster.with_role("expert") if p.jira_account_id]
    return render(request, "review.html", u, D=D, ctx=ctx, scope=scope, writers=writers, drafts=drafts,
                  pending=pending, log=log, excluded=excluded, experts=experts,
                  window=db.get_setting("review.windowDays", 3), note_mode=db.get_setting("review.noteMode"),
                  dm_link=slack.dm_link)


@router.post("/review/act")
def act(key: str = Form(...), kinds: str = Form(...), next: str = Form("/review"), u: User = Depends(require("owner"))):
    ks = [k for k in kinds.split(",") if k]
    if db.flag("jira_writes_enabled") and jira.auth_headers(write=True):
        msg = service.run_steps(key, ks, actor(u))
        return back(next, msg)
    try:
        _, a, desc = service.plan(key, ks, actor(u))
    except ValueError as e:
        return back(next, f"{key}: {e}")
    return back(next + "#pending", f"{key}: do this in Jira — {desc}")


@router.post("/review/exclude")
def exclude(key: str = Form(...), title: str = Form(""), u: User = Depends(require("owner"))):
    db.execute("insert into exclusions (jira_key, title, by) values (%s, %s, %s) on conflict do nothing",
               (key, title, actor(u)))
    db.audit(actor(u), "review.exclude", key)
    return back("/review", f"Excluded {key}")


@router.post("/review/include")
def include(key: str = Form(...), u: User = Depends(require("owner"))):
    db.execute("delete from exclusions where jira_key = %s", (key,))
    db.audit(actor(u), "review.include", key)
    return back("/review", f"{key} is back in the queue")


@router.post("/review/override")
def override(key: str = Form(...), category: str = Form(""), expert_id: str = Form(""), auto_slack: str = Form(""),
             u: User = Depends(require("owner"))):
    db.execute("insert into overrides (jira_key, category, expert_id, auto_slack) values (%s, %s, %s, %s) "
               "on conflict (jira_key) do update set category = excluded.category, expert_id = excluded.expert_id, "
               "auto_slack = excluded.auto_slack",
               (key, category or None, expert_id or None, None if auto_slack == "" else auto_slack == "on"))
    db.audit(actor(u), "review.override", key, {"category": category, "expert_id": expert_id})
    return back("/review", f"Saved override for {key}")


@router.post("/review/draft")
def draft(writer_id: str = Form(...), u: User = Depends(require("owner"))):
    D, ctx = service.state("mine")
    row, created = service.draft_followup(writer_id, D, ctx, actor(u))
    if not row:
        return back("/review", "Nothing to follow up for this writer")
    return back("/review#drafts", "Draft ready" if created else "This exact message was already drafted today")


@router.post("/review/status-draft")
def status_draft(writer_id: str = Form(...), keys: str = Form(...), u: User = Depends(require("owner"))):
    _, created = service.status_draft(writer_id, [k for k in keys.split(",") if k], actor(u))
    return back("/review#drafts", "Draft ready" if created else "Already drafted today")


@router.post("/review/chase")
def chase(key: str = Form(...), target: str = Form(...), expert: str = Form(""), u: User = Depends(require("owner"))):
    """Post "Any news on the edits/ticket?" tagging the writer or the expert."""
    is_expert = expert == "1"
    ctx = service.context()
    p = ctx.roster.get(target)
    name = p.display_name if p else "there"
    text = rules.CHASE_EXPERT_TEXT if is_expert else rules.CHASE_WRITER_TEXT
    a = outbound.propose("jira.review.chase", key, {"ops": [{"op": "comment", "adf": jira.mention_adf(target, name, text),
                                                             "internal": outbound.note_mode_internal()}],
                                                    "description": f'post "@{name} {text}"'}, actor(u),
                         outbound.idempotency_key("chase", target, [key], bd.local_today(), text))
    if is_expert:
        db.execute("insert into expert_asks (jira_key, at) values (%s, now()) on conflict (jira_key) do update "
                   "set at = now()", (key,))
    if db.flag("jira_writes_enabled") and a["state"] == "proposed":
        a = outbound.execute(a["id"], actor(u))
        return back("/review", f"{key}: {a['state']}")
    return back("/review#pending", f"{key}: post this in Jira — @{name} {text}")


@router.post("/review/settings")
def settings(window_days: float = Form(...), note_mode: str = Form(...), u: User = Depends(require("owner"))):
    db.set_setting("review.windowDays", window_days)
    db.set_setting("review.noteMode", "standard" if note_mode == "standard" else "internal")
    db.audit(actor(u), "review.settings", None, {"windowDays": window_days, "noteMode": note_mode})
    return back("/review", "Settings saved")


_ = (config, logic)
