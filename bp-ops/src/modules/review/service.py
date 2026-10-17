"""Loads Review Flow state from the mirror and runs its actions through core/outbound.py."""

from datetime import datetime

import config
import db
from core import jira, outbound, people, rules, sync
from modules.review import logic

STATUSES = ["Open", "Text", "Review", "Proofreading", "Ready"]


def context(now: datetime | None = None) -> logic.Context:
    rc = {r["expert_id"]: r["n"] for r in db.query(
        "select expert_id, count(*) n from tickets where status = 'Review' and expert_id is not null group by 1")}
    ov = {r["jira_key"]: r for r in db.query("select * from overrides")}
    asks = {r["jira_key"]: r["at"] for r in db.query("select * from expert_asks")}
    return logic.Context(roster=people.load(), me=config.OWNER_ACCOUNT_ID, now=now or datetime.now(config.TZ),
                         review_counts=rc, overrides=ov, expert_asks=asks,
                         window_days=float(db.get_setting("review.windowDays", 3)),
                         holidays=db.get_setting("holidays", []) or [])


def tickets(ctx: logic.Context, scope: str = "mine", keys: list[str] | None = None) -> list[logic.Ticket]:
    if keys:
        rows = db.query("select * from tickets where jira_key = any(%s)", (keys,))
    elif scope == "mine":
        rows = db.query("select * from tickets where status = any(%s) and %s = any(managers) "
                        "order by updated_at desc", (STATUSES, ctx.me))
    else:
        rows = db.query("select * from tickets where status = any(%s) order by updated_at desc", (STATUSES,))
    ks = [r["jira_key"] for r in rows]
    cm: dict[str, list] = {}
    for c in db.query("select * from comments where jira_key = any(%s) order by created_at", (ks,)):
        cm.setdefault(c["jira_key"], []).append(c)
    ch: dict[str, list] = {}
    for c in db.query("select * from field_changes where jira_key = any(%s) and field_id = any(%s)",
                      (ks, [config.F_AUTHOR, config.F_PARTICIPANTS])):
        ch.setdefault(c["jira_key"], []).append(c)
    return [logic.analyze(r, cm.get(r["jira_key"], []), ch.get(r["jira_key"], []), ctx) for r in rows]


def sent_map() -> dict[str, dict[str, datetime]]:
    """{writer accountId: {ticket key: last sent_at}} from follow-up DMs marked sent."""
    out: dict[str, dict[str, datetime]] = {}
    for r in db.query("select recipient, ticket_keys, sent_at from outbound_messages where state = 'sent' "
                      "and channel = 'slack_dm' and template like 'writer_followup%%'"):
        for k in r["ticket_keys"]:
            cur = out.setdefault(r["recipient"], {}).get(k)
            if cur is None or r["sent_at"] > cur:
                out[r["recipient"]][k] = r["sent_at"]
    return out


def state(scope: str = "mine") -> tuple[dict, logic.Context]:
    ctx = context()
    ts = tickets(ctx, scope)
    excluded = {r["jira_key"] for r in db.query("select jira_key from exclusions")}
    return logic.derive(ts, excluded, sent_map(), ctx), ctx


# --- nudges ------------------------------------------------------------------------------------

def draft_followup(writer_id: str, D: dict, ctx: logic.Context, actor: str, extra: list[logic.Ticket] = ()):
    """Draft (once per writer, ticket set and day) the follow-up DM. Returns (row, created)."""
    tl = logic.attention_for(writer_id, D)
    for t in extra:
        if all(x.key != t.key for x in tl):
            tl.insert(0, t)
    if not tl:
        return None, False
    w = ctx.roster.get(writer_id)
    earliest = min(t.my_last.at for t in tl if t.my_last) if any(t.my_last for t in tl) else ctx.now
    last_sent = db.scalar("select max(sent_at) from outbound_messages where recipient = %s and state = 'sent' "
                          "and template like 'writer_followup%%'", (writer_id,))
    again = bool(last_sent and last_sent > earliest)
    body = logic.followup_text(rules.first_name(w.display_name if w else ""), tl, again)
    return outbound.draft_message(kind="nudge", channel="slack_dm", recipient=writer_id,
                                  template="writer_followup_repeat" if again else "writer_followup",
                                  body=body, ticket_keys=[t.key for t in tl], created_by=actor)


def auto_drafts(actor: str) -> int:
    """After your 2nd or 3rd note, prepare the Slack draft automatically (the legacy auto-Slack, in draft mode)."""
    D, ctx = state("mine")
    since = db.get_setting("review.autoSlackSince")
    since_dt = datetime.fromtimestamp(since / 1000, config.TZ) if isinstance(since, int | float) else (
        datetime.fromisoformat(since) if isinstance(since, str) else None)
    pend = logic.pending_auto_slack(D, sent_map(), since_dt)
    n = 0
    for wid in dict.fromkeys(t.writer_id for t in pend):
        _, created = draft_followup(wid, D, ctx, actor, extra=[t for t in pend if t.writer_id == wid])
        n += int(created)
    return n


def status_draft(writer_id: str, keys: list[str], actor: str):
    ctx = context()
    w = ctx.roster.get(writer_id)
    lines = "\n".join(f"• <{config.ticket_url(k)}|{k}>" for k in keys)
    body = f"Hi {rules.first_name(w.display_name if w else '')}. {rules.STATUS_TEXT}\n{lines}"
    return outbound.draft_message(kind="status", channel="slack_dm", recipient=writer_id, template="status",
                                  body=body, ticket_keys=keys, created_by=actor)


# --- workflow steps ----------------------------------------------------------------------------

def plan(key: str, kinds: list[str], actor: str) -> tuple[logic.Ticket, dict | None, str]:
    """Build the Jira ops for the steps; record them as one proposed action. Returns (ticket, action, description)."""
    ctx = context()
    found = tickets(ctx, keys=[key])
    if not found:
        raise LookupError(f"{key} isn't in the mirror")
    T = found[0]
    ops, desc = [], []
    for k in kinds:
        o, d = logic.ops_for(T, k, outbound.note_mode_internal())
        ops += o
        desc.append(d)
    trig = T.trigger.id if T.trigger else "none"
    idem = outbound.idempotency_key("review", key, [key], ctx.now.date(), "+".join(kinds) + ":" + trig)
    a = outbound.propose("jira.review", key, {"ops": ops, "kinds": kinds, "trigger": trig,
                                             "description": "; ".join(desc)}, actor, idem)
    return T, a, "; ".join(desc)


def run_steps(key: str, kinds: list[str], actor: str, client: jira.JiraClient | None = None,
              dry_run: bool = False) -> str:
    """Re-read the ticket from Jira, confirm the same steps still apply, then execute (scheduled task steps 5–7)."""
    ctx = context()
    old = tickets(ctx, keys=[key])
    if not old:
        return f"{key}: not in the mirror"
    old = old[0]
    if db.one("select 1 from exclusions where jira_key = %s", (key,)):
        return f"{key}: excluded"
    reader = client or jira.JiraClient()
    sync.fetch_and_store(reader, f"key = {key}")
    fresh = tickets(context(), keys=[key])[0]
    why = logic.same_step(old, fresh, kinds)
    if why:
        db.audit(actor, "review.changed", key, {"why": why})
        return f"{key}: ticket changed since the last refresh ({why}); nothing was done"
    if dry_run:  # nothing is proposed, so a later real run on the same day isn't blocked by the idempotency key
        desc = "; ".join(logic.ops_for(fresh, k, outbound.note_mode_internal())[1] for k in kinds)
        db.audit(actor, "review.dry_run", key, {"would": desc, "kinds": kinds})
        return f"{key}: would {desc} (dry run)"
    T, a, desc = plan(key, kinds, actor)
    res = outbound.execute(a["id"], actor, client=jira.JiraClient(write=True) if client is None else client)
    sync.fetch_and_store(reader, f"key = {key}")
    return f"{key}: {desc}" if res["state"] == "sent" else f"{key}: failed — {res.get('error')}"


def run_automation(actor: str, client: jira.JiraClient | None = None) -> int:
    """Server-side review automation. Runs only with review_automation_enabled AND jira_writes_enabled,
    and logs intended actions instead of acting while review_automation_dry_run is on."""
    from core.scheduler import Skip

    dry = bool(db.get_setting("review_automation_dry_run", True))
    if not dry and not db.flag("jira_writes_enabled"):
        raise Skip("jira_writes_enabled is off")
    D, _ = state("mine")
    n = 0
    for t in D["move"]:
        if t.auto:
            run_steps(t.key, [a.kind for a in t.actions], actor, client=client, dry_run=dry)
            n += 1
    return n
