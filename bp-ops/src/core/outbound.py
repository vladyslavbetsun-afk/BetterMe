"""Every message, comment, transition and field edit the app makes goes through this module.

* Messages: inserted into outbound_messages with a UNIQUE idempotency key BEFORE anything is sent. A second
  attempt for the same (kind, recipient, tickets, local day, template) inserts nothing and sends nothing.
  This is what makes the 2026-10-15 duplicate-nudge bug impossible (00 §3).
* Jira/Notion writes: proposed as `actions` rows; executed only after a confirmation (or an explicitly enabled
  automation), only while the matching feature flag is on, and only once (proposed → confirmed is a guarded update).
"""

import hashlib
from datetime import date, datetime

import config
import db
from core import business_days, jira, slack


def idempotency_key(kind: str, recipient: str, ticket_keys: list[str], local_date: date, template: str) -> str:
    raw = "|".join([kind, recipient, ",".join(sorted(set(ticket_keys))), local_date.isoformat(), template])
    return hashlib.sha256(raw.encode()).hexdigest()


# --- messages -----------------------------------------------------------------------------------

def draft_message(*, kind: str, channel: str, recipient: str, template: str, body: str, ticket_keys: list[str],
                  created_by: str | None, day: date | None = None) -> tuple[dict, bool]:
    """Create the message once. Returns (row, created). created=False means it already existed today."""
    key = idempotency_key(kind, recipient, ticket_keys, day or business_days.local_today(), template)
    row = db.one("insert into outbound_messages (channel, recipient, template, body, ticket_keys, idempotency_key, "
                 "state, created_by) values (%s, %s, %s, %s, %s, %s, 'draft', %s) "
                 "on conflict (idempotency_key) do nothing returning *",
                 (channel, recipient, template, body, sorted(set(ticket_keys)), key, created_by))
    if row:
        db.audit(created_by, "message.drafted", recipient, {"id": row["id"], "template": template,
                                                            "tickets": row["ticket_keys"]})
        return row, True
    return db.one("select * from outbound_messages where idempotency_key = %s", (key,)), False


def mark_sent(message_id: int, actor: str | None, external_ts: str | None = None) -> bool:
    """Draft → sent (Vladyslav sent it by hand, or the bot did). Guarded: happens at most once."""
    n = db.execute("update outbound_messages set state = 'sent', sent_at = now(), external_ts = %s "
                   "where id = %s and state = 'draft'", (external_ts, message_id))
    if n:
        db.audit(actor, "message.sent", str(message_id))
    return bool(n)


def cancel_message(message_id: int, actor: str | None) -> bool:
    n = db.execute("update outbound_messages set state = 'cancelled' where id = %s and state = 'draft'",
                   (message_id,))
    if n:
        db.audit(actor, "message.cancelled", str(message_id))
    return bool(n)


def send_via_bot(message_id: int, actor: str | None) -> bool:
    """Decision (b): post a channel message as the bot. Only when slack_send_enabled is on and a bot is set up."""
    if not db.flag("slack_send_enabled"):
        raise PermissionError("Slack sending is switched off (settings: slack_send_enabled)")
    m = db.one("select * from outbound_messages where id = %s", (message_id,))
    if not m or m["state"] != "draft":
        return False
    if m["channel"] != "slack_channel":
        raise PermissionError("Only channel posts go through the bot; writer DMs are sent by hand (spec 05 §3)")
    # claim the row first so two clicks can't both post
    if not db.execute("update outbound_messages set state = 'sent', sent_at = now() where id = %s and state = 'draft'",
                      (message_id,)):
        return False
    try:
        ts = slack.post(m["recipient"], m["body"])
        db.execute("update outbound_messages set external_ts = %s where id = %s", (ts, message_id))
        db.audit(actor, "message.posted", m["recipient"], {"id": message_id, "ts": ts})
        return True
    except Exception as e:
        db.execute("update outbound_messages set state = 'failed' where id = %s", (message_id,))
        db.audit(actor, "message.failed", m["recipient"], {"id": message_id, "error": str(e)})
        raise


def already_sent(recipient: str, ticket_key: str, after: datetime) -> datetime | None:
    """When a sent message to this recipient last mentioned this ticket, if after `after`."""
    return db.scalar("select max(sent_at) from outbound_messages where recipient = %s and state = 'sent' "
                     "and %s = any(ticket_keys) and sent_at > %s", (recipient, ticket_key, after))


# --- actions (Jira / Notion writes) -------------------------------------------------------------------

FLAG_FOR = {"jira": "jira_writes_enabled", "notion": "notion_writes_enabled"}


def propose(kind: str, jira_key: str | None, payload: dict, by: str | None, idem: str | None = None) -> dict | None:
    """Record an action. `idem` makes re-proposing the same thing a no-op (returns the existing row); a failed or
    cancelled one goes back to 'proposed' so it can be retried. A sent one stays sent."""
    row = db.one("insert into actions (kind, jira_key, payload, state, proposed_by, idempotency_key) "
                 "values (%s, %s, %s, 'proposed', %s, %s) on conflict (idempotency_key) do update "
                 "set state = 'proposed', error = null, payload = excluded.payload "
                 "where actions.state in ('failed', 'cancelled') returning *",
                 (kind, jira_key, db.jsonb(payload), by, idem))
    if row is None and idem:
        row = db.one("select * from actions where idempotency_key = %s", (idem,))
    return row


def cancel(action_id: int, actor: str | None) -> bool:
    return bool(db.execute("update actions set state = 'cancelled', confirmed_by = %s where id = %s "
                           "and state = 'proposed'", (actor, action_id)))


def execute(action_id: int, actor: str, client: jira.JiraClient | None = None) -> dict:
    """Confirm and run one action. Raises PermissionError when the system's write flag is off."""
    a = db.one("select * from actions where id = %s", (action_id,))
    if not a:
        raise LookupError("No such action")
    system = a["kind"].split(".")[0]
    if not db.flag(FLAG_FOR.get(system, "_never_")):
        raise PermissionError(f"{system} writes are switched off (settings: {FLAG_FOR.get(system)})")
    claimed = db.one("update actions set state = 'confirmed', confirmed_by = %s where id = %s and state = 'proposed' "
                     "returning *", (actor, action_id))
    if not claimed:
        return a  # someone else already ran (or cancelled) it
    try:
        if system == "jira":
            _run_jira(claimed, client or jira.JiraClient(write=True))
        elif system == "notion":
            from core import notion

            notion.run_action(claimed)
        db.execute("update actions set state = 'sent', executed_at = now() where id = %s", (action_id,))
        db.audit(actor, f"action.{a['kind']}", a["jira_key"], {"id": action_id})
    except Exception as e:
        db.execute("update actions set state = 'failed', executed_at = now(), error = %s where id = %s",
                   (str(e)[:1000], action_id))
        db.audit(actor, "action.failed", a["jira_key"], {"id": action_id, "error": str(e)[:300]})
    return db.one("select * from actions where id = %s", (action_id,))


def _run_jira(a: dict, client: jira.JiraClient) -> None:
    """payload = {"ops": [{"op": "edit", "fields": {...}} | {"op": "transition", "to": "Review"}
                         | {"op": "comment", "adf": {...}, "internal": true}]}"""
    key = a["jira_key"]
    for op in a["payload"].get("ops", []):
        if op["op"] == "edit":
            client.edit(key, op["fields"])
        elif op["op"] == "transition":
            client.transition(key, _transition_id(client, key, op["to"]))
        elif op["op"] == "comment":
            client.comment(key, op["adf"], bool(op.get("internal")))
        else:
            raise ValueError(f"Unknown op {op['op']}")


def _transition_id(client: jira.JiraClient, key: str, to: str) -> str:
    """Look the transition up first (00 §1); fall back to the known id."""
    for t in client.transitions(key):
        if ((t.get("to") or {}).get("name") or "").lower() == to.lower():
            return str(t["id"])
    if to in config.TRANSITIONS:
        return config.TRANSITIONS[to]
    raise jira.JiraError(f"Jira offers no transition to {to} on {key}")


def note_mode_internal() -> bool:
    return db.get_setting("review.noteMode", "internal") != "standard"
