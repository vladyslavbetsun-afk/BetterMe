"""BP Review Flow, ported from legacy/bp-review-flow.html (analyze/derive) and the scheduled task prompt
(legacy/review-flow-scheduled-task.md). Pure functions over mirrored rows so they can be unit-tested.

Timing rules: 00 §6.4. Business days use core.business_days (Europe/Brussels, Mon–Fri, holidays).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import config
from core import business_days as bd
from core import rules
from core.people import Person, Roster

ACTIVE = config.ACTIVE
FLOW = ["Text", "Review", "Proofreading", "Ready"]


@dataclass
class Comment:
    id: str
    aid: str | None
    name: str
    role: str  # me | writer | tim | expert | other
    at: datetime
    text: str
    link: bool
    mentions: list[str]


@dataclass
class Action:
    kind: str  # assign | toProof | note | addTim | toReady
    label: str
    disabled: bool = False


@dataclass
class Ticket:
    key: str
    title: str
    status: str
    url: str
    writer: Person | None
    writer_id: str | None
    expert_id: str | None
    proof_id: str | None
    participants: list[str]
    mine: bool
    cs: list[Comment]
    created: datetime | None
    category: str | None = None
    cat_auto: bool = True
    actions: list[Action] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trigger: Comment | None = None
    stage: str = ""
    waiting_on: str | None = None
    since: datetime | None = None
    plan_expert: Person | None = None
    link_c: Comment | None = None
    assigned_at: datetime | None = None
    writing_late: bool = False
    expert_silent: bool = False
    manual_only: bool = False
    auto: bool = False
    auto_why: str = ""
    my_last: Comment | None = None
    msg_no: int = 0
    target_id: str | None = None
    target_is_expert: bool = False
    to_writer: bool = False
    bd_since_last: float = 0.0
    auto_slack: bool = True
    can_ready: bool = False

    @property
    def short(self) -> str:
        return rules.short_title(self.title)


@dataclass
class Context:
    roster: Roster
    me: str
    now: datetime
    review_counts: dict[str, int]
    overrides: dict[str, dict]
    expert_asks: dict[str, datetime]
    window_days: float
    holidays: list


def assigned_from(changes: list[dict], wid: str) -> datetime | None:
    """Latest time the current Author was set as Author or added to Request participants (the later of the two)."""
    author_at = parts_at = None
    for ch in changes:
        if ch["field_id"] == config.F_AUTHOR and (ch["to_value"] or "") == wid:
            author_at = max(filter(None, [author_at, ch["at"]]))
        if (ch["field_id"] == config.F_PARTICIPANTS and wid in (ch["to_value"] or "")
                and wid not in (ch["from_value"] or "")):
            parts_at = max(filter(None, [parts_at, ch["at"]]))
    cands = [x for x in (author_at, parts_at) if x]
    return max(cands) if cands else None


def _days(ctx: Context, t: datetime) -> float:
    return (ctx.now - t).total_seconds() / 86400


def _expert_ids(ctx: Context) -> set[str]:
    return {p.jira_account_id for p in ctx.roster.with_role("expert", active_only=False) if p.jira_account_id}


def expert_category(ctx: Context, account: str | None) -> str | None:
    p = ctx.roster.get(account)
    return p.niche if p and p.role == "expert" and p.niche in ("fitness", "nutrition") else None


def pick_expert(ctx: Context, category: str | None) -> Person | None:
    """The category's expert with the fewest tickets in Review (00 §6.1)."""
    if category not in ("fitness", "nutrition"):
        return None
    lst = ctx.roster.experts(category)
    if not lst:
        return None
    return sorted(lst, key=lambda e: ctx.review_counts.get(e.jira_account_id, 0))[0]


def analyze(row: dict, comments: list[dict], changes: list[dict], ctx: Context) -> Ticket:
    roster = ctx.roster
    wid = row.get("author_id")
    writer = roster.get(wid)
    exp_ids = _expert_ids(ctx)
    if row.get("expert_id"):
        exp_ids.add(row["expert_id"])

    def role(aid):
        if aid and aid == ctx.me:
            return "me"
        if wid and aid == wid:
            return "writer"
        if aid == config.TIM_ACCOUNT_ID:
            return "tim"
        if aid in exp_ids:
            return "expert"
        return "other"

    cs = sorted((Comment(id=c["id"], aid=c["author_account_id"],
                         name=roster.name(c["author_account_id"], c.get("author_name") or "?"),
                         role=role(c["author_account_id"]), at=c["created_at"], text=c["body_md"] or "",
                         link=bool(c["links"]), mentions=list(c.get("mentions") or []))
                 for c in comments if c["author_account_id"] not in config.IGNORED_COMMENTERS),
                key=lambda c: c.at)
    status = row.get("status") or "?"
    T = Ticket(key=row["jira_key"], title=row.get("summary") or "", status=status, url=config.ticket_url(row["jira_key"]),
               writer=writer, writer_id=wid, expert_id=row.get("expert_id"), proof_id=row.get("proofreader_id"),
               participants=list(row.get("participants") or []), mine=ctx.me in (row.get("managers") or []), cs=cs,
               created=row.get("created_at"))
    ov = ctx.overrides.get(T.key, {})
    T.category = ov.get("category") or expert_category(ctx, T.expert_id) or rules.detect_category(T.title)
    T.cat_auto = not ov.get("category")

    def last(xs):
        return xs[-1] if xs else None

    writer_links = [c for c in cs if c.role == "writer" and c.link]
    link_c = last(writer_links) or (None if wid else last([c for c in cs if c.role == "other" and c.link]))
    T.link_c = link_c
    after_link = [c for c in cs if c.at > link_c.at] if link_c else cs
    exp_c = [c for c in after_link if c.role == "expert"]
    last_exp, first_exp = last(exp_c), (exp_c[0] if exp_c else None)
    writer_name = writer.display_name if writer else "writer"

    if status == "Text":
        if link_c:
            target = None
            if ov.get("expert_id"):
                target = roster.get(ov["expert_id"])
            elif T.expert_id:
                target = roster.get(T.expert_id)
            elif T.category:
                target = pick_expert(ctx, T.category)
            if not target:
                T.warnings.append("Pick a category or expert")
            if not wid:
                T.warnings.append("No Author on ticket")
            T.plan_expert = target
            ready = bool(target and T.expert_id == target.jira_account_id and target.jira_account_id in T.participants)
            label = ("Move to Review + add expert" if not target
                     else f"Move to Review ({target.display_name} already set)" if ready
                     else f"Move to Review + add {target.display_name}")
            T.actions.append(Action("assign", label, disabled=not target))
            T.trigger, T.stage = link_c, "Article link posted"
        else:
            T.stage, T.waiting_on = "Writing", writer_name
            T.assigned_at = assigned_from(changes, wid) if wid else None
            T.since = T.assigned_at or (cs[-1].at if cs else T.created)
            if (T.assigned_at and bd.elapsed(T.assigned_at, ctx.now, ctx.holidays) >= 5
                    and not any(c.role == "me" and c.at > T.assigned_at for c in cs)):
                T.writing_late = True
    elif status == "Review":
        if last_exp:
            note = next((c for c in cs if c.role == "me" and c.at > first_exp.at), None)
            T.actions.append(Action("toProof", "Move to Proofreading"))
            if note:
                T.trigger, T.stage = note, "Note sent, still in Review"
            else:
                T.actions.append(Action("note", f"Post note tagging {writer_name}" if writer else "Post note to writer",
                                        disabled=not writer))
                if not wid:
                    T.warnings.append("No Author on ticket")
                if "?" in last_exp.text:
                    T.warnings.append("Expert's last comment looks like a question")
                T.trigger, T.stage = last_exp, "Expert commented"
        else:
            T.stage = "With expert"
            T.waiting_on = roster.name(T.expert_id, "expert") if T.expert_id else "expert"
            T.since = link_c.at if link_c else (cs[-1].at if cs else T.created)
            if link_c and _days(ctx, link_c.at) > 7:
                recent_ask = any(c.role == "me" and c.at > link_c.at and _days(ctx, c.at) < 7 for c in cs)
                db_ask = T.key in ctx.expert_asks and _days(ctx, ctx.expert_asks[T.key]) < 7
                if not recent_ask and not db_ask:
                    T.expert_silent = True
    elif status == "Proofreading":
        any_exp = [c for c in cs if c.role == "expert"]
        last_any = last(any_exp)
        if last_any:
            note = next((c for c in cs if c.role == "me" and c.at > last_any.at), None)
        else:
            note = last([c for c in cs if c.role == "me" and rules.NOTE_RE.search(c.text)])
        if not any_exp:
            T.warnings.append("Ticket is in Proofreading but has no expert comment")
        base = note.at if note else (last_any.at if last_any else None)
        tim_c = last([c for c in cs if c.role == "tim" and (base is None or c.at > base)])
        if tim_c:
            T.actions.append(Action("toReady", "Move to Ready"))
            T.trigger, T.stage = tim_c, "Proofreading done"
        elif not note:
            if any_exp:
                T.actions.append(Action("note", f"Post note tagging {writer_name}" if writer else "Post note to writer",
                                        disabled=not writer))
                if not wid:
                    T.warnings.append("No Author on ticket")
                T.trigger, T.stage, T.manual_only = last_any, "Note to writer missing", True
            else:
                T.stage, T.waiting_on = "Check manually", "you"
                T.since = cs[-1].at if cs else T.created
        elif T.proof_id == config.TIM_ACCOUNT_ID:
            T.stage, T.waiting_on = "With proofreader", "Tim Jones"
            reply = next((c for c in cs if c.role == "writer" and c.at > note.at), None)
            T.since = (reply or note).at
        else:
            reply = next((c for c in cs if c.role == "writer" and c.at > note.at), None)
            if reply:
                T.actions.append(Action("addTim", "Add Tim Jones as proofreader"))
                T.trigger, T.stage = reply, "Writer addressed comments"
            else:
                T.stage, T.waiting_on, T.since = "Writer fixing", writer_name, note.at

    age = _days(ctx, T.trigger.at) if T.trigger else float("inf")
    T.auto = (not T.manual_only and T.mine and bool(T.actions) and not T.warnings and age <= ctx.window_days
              and all(not a.disabled for a in T.actions))
    T.auto_why = ("" if not T.actions else "Not one of the four routine steps" if T.manual_only
                  else "You aren't in Managers" if not T.mine else "Has a warning" if T.warnings
                  else f"Trigger older than {ctx.window_days:g} days" if age > ctx.window_days else "")

    # follow-up facts: the run of my comments at the end of the thread
    run = []
    for c in reversed(cs):
        if c.role != "me":
            break
        run.insert(0, c)
    if run:
        T.my_last, T.msg_no = run[-1], len(run)
        tagged = next((m for c in reversed(run) for m in c.mentions), None)
        T.target_id = tagged or wid
        T.target_is_expert = bool(T.target_id and (T.target_id in exp_ids))
        T.to_writer = bool(T.target_id and wid and T.target_id == wid)
        T.bd_since_last = bd.elapsed(T.my_last.at, ctx.now, ctx.holidays)
    T.auto_slack = ov.get("auto_slack") is not False
    T.can_ready = bool(link_c) and status in ACTIVE
    return T


# --- derived views (legacy derive()) ---------------------------------------------------------------

@dataclass
class Ask:
    t: Ticket
    wid: str
    bd: float
    sent_at: datetime | None
    paused: bool
    returned: bool
    flagged: bool


def derive(ts: list[Ticket], excluded: set[str], sent: dict[str, dict[str, datetime]], ctx: Context) -> dict:
    """sent = {writer accountId: {ticket key: last sent_at}} from outbound_messages (state sent)."""
    ts = [t for t in ts if t.key not in excluded]
    move = [t for t in ts if t.actions]
    wait = sorted([t for t in ts if not t.actions and t.status in ACTIVE],
                  key=lambda t: t.since or datetime.min.replace(tzinfo=config.TZ))
    no_reply = [t for t in ts if t.my_last and t.msg_no == 1 and t.bd_since_last >= 3]
    asks = []
    for t in ts:
        if not (t.my_last and t.msg_no >= 2 and t.to_writer):
            continue
        s_at = sent.get(t.writer_id, {}).get(t.key)
        after = bool(s_at and s_at > t.my_last.at)
        el = bd.elapsed(s_at, ctx.now, ctx.holidays) if after else 0
        paused, returned = after and el < 3, after and el >= 3
        asks.append(Ask(t, t.writer_id, t.bd_since_last, s_at, paused, returned,
                        flagged=not paused and (t.bd_since_last >= 3 or returned)))
    counts = {
        "move": len(move),
        "text": sum(1 for t in ts if t.status == "Text" and not t.actions),
        "expert": sum(1 for t in ts if t.stage == "With expert"),
        "fixing": sum(1 for t in ts if t.stage == "Writer fixing"),
        "proof": sum(1 for t in ts if t.stage == "With proofreader"),
        "no_reply": len(no_reply),
        "flagged": sum(1 for a in asks if a.flagged),
        "silent": sum(1 for t in ts if t.expert_silent),
        "late": sum(1 for t in ts if t.writing_late),
    }
    return {"ts": ts, "move": move, "wait": wait, "no_reply": no_reply,
            "follow": [a for a in asks if not a.flagged], "flagged": [a for a in asks if a.flagged],
            "expert_silent": [t for t in ts if t.expert_silent], "writing_late": [t for t in ts if t.writing_late],
            "asks": asks, "counts": counts}


def attention_for(wid: str, D: dict) -> list[Ticket]:
    """Every ticket for this writer that needs a nudge: unanswered 1st notes to them and flagged follow-ups."""
    keys: dict[str, Ticket] = {}
    for t in D["no_reply"]:
        if t.writer_id == wid and t.to_writer:
            keys[t.key] = t
    for a in D["flagged"]:
        if a.wid == wid:
            keys[a.t.key] = a.t
    return list(keys.values())


def pending_auto_slack(D: dict, sent: dict[str, dict[str, datetime]], since: datetime | None) -> list[Ticket]:
    """2nd/3rd notes to the writer posted after `since` that no sent message has covered yet."""
    if since is None:
        return []
    out = []
    for t in D["ts"]:
        if not (t.my_last and t.to_writer and t.auto_slack and t.msg_no in (2, 3) and t.my_last.at > since):
            continue
        s_at = sent.get(t.writer_id, {}).get(t.key)
        if s_at and s_at >= t.my_last.at:
            continue
        out.append(t)
    return out


def followup_text(first: str, tickets: list[Ticket], again: bool) -> str:
    """Writer follow-up DM, verbatim template from 00 §3."""
    lead = ("Just checking in again on the edits for these tickets:" if again
            else "Just following up on the edits for these tickets:")
    lines = "\n".join(f"• <{t.url}|{t.key} {t.short}>" for t in tickets)
    return (f"Hi {first}, hope you're doing well! {lead}\n{lines}\n\n"
            "Could you share an update on where they stand when you get a chance? Thank you!")


# --- planned Jira operations per step (spec 05 §9) ---------------------------------------------------

def ops_for(T: Ticket, kind: str, internal_notes: bool) -> tuple[list[dict], str]:
    """Jira ops for one step plus a plain description (shown when writes are off, logged when on)."""
    def parts_with(aid):
        return [{"accountId": a} for a in dict.fromkeys([*T.participants, aid])]

    if kind == "assign":
        ex = T.plan_expert
        if not ex or not ex.jira_account_id:
            raise ValueError("No expert chosen")
        fields, did = {}, []
        if T.expert_id != ex.jira_account_id:
            fields[config.F_EXPERT] = {"accountId": ex.jira_account_id}
            did.append(f"set Expert = {ex.display_name}")
        if ex.jira_account_id not in T.participants:
            fields[config.F_PARTICIPANTS] = parts_with(ex.jira_account_id)
            did.append(f"add {ex.display_name} to Request participants")
        ops = ([{"op": "edit", "fields": fields}] if fields else []) + [{"op": "transition", "to": "Review"}]
        return ops, ", ".join([*did, "move to Review"])
    if kind == "toProof":
        return [{"op": "transition", "to": "Proofreading"}], "move to Proofreading"
    if kind == "toReady":
        return [{"op": "transition", "to": "Ready"}], "move to Ready"
    if kind == "note":
        if not T.writer_id:
            raise ValueError("No Author on ticket")
        from core.jira import mention_adf

        name = T.writer.display_name if T.writer else "writer"
        return ([{"op": "comment", "adf": mention_adf(T.writer_id, name, rules.NOTE_TEXT), "internal": internal_notes}],
                f'post "@{name} {rules.NOTE_TEXT}"')
    if kind == "addTim":
        fields = {config.F_PROOFREADER: {"accountId": config.TIM_ACCOUNT_ID}}
        if config.TIM_ACCOUNT_ID not in T.participants:
            fields[config.F_PARTICIPANTS] = parts_with(config.TIM_ACCOUNT_ID)
        return [{"op": "edit", "fields": fields}], "set Proofreader = Tim Jones and add him to Request participants"
    if kind == "straightToReady":
        path = FLOW[FLOW.index(T.status) + 1:] if T.status in FLOW else []
        return [{"op": "transition", "to": s} for s in path], "move " + " → ".join([T.status, *path])
    raise ValueError(f"Unknown step {kind}")


def same_step(old: Ticket, new: Ticket, kinds: list[str]) -> str | None:
    """None when the fresh ticket still calls for the same steps; else why not (scheduled task step 6)."""
    if new.status != old.status:
        return f"status is now {new.status} (was {old.status})"
    if (new.trigger and new.trigger.id) != (old.trigger and old.trigger.id):
        return "a newer comment arrived"
    if not all(any(a.kind == k and not a.disabled for a in new.actions) for k in kinds):
        return "this step no longer applies"
    if "assign" in kinds and ((new.plan_expert and new.plan_expert.id) != (old.plan_expert and old.plan_expert.id)):
        return "the expert choice changed"
    return None


def window_ok(T: Ticket, ctx: Context) -> bool:
    return bool(T.trigger) and ctx.now - T.trigger.at <= timedelta(days=ctx.window_days)
