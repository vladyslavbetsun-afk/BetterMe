from datetime import timedelta

import config
import db
from conftest import NOW, ago
from factory import ANGELICA, CARTER, EVE, GARETT, JEREMY, MARIA, ME, OKSANA, TIM, comment, field_item, history, issue, load
from modules.review import logic, service

DOC = "https://docs.google.com/document/d/doc1"


def analyze(key, **kw):
    ctx = service.context(now=NOW)
    for k, v in kw.items():
        setattr(ctx, k, v)
    return service.tickets(ctx, keys=[key])[0], ctx


def test_step1_text_with_link_picks_least_loaded_expert():
    # Carter has 2 tickets in Review, Garett 1 → Garett
    load(issue("BP-1", "wall pilates workout, 1800 words", "Text", ago(10), author=EVE, participants=[EVE],
               comments=[comment(EVE, ago(1), "Here it is", DOC)]),
         issue("BP-2", "x squats", "Review", ago(30), expert=CARTER), issue("BP-3", "y squats", "Review", ago(30), expert=CARTER),
         issue("BP-4", "z squats", "Review", ago(30), expert=GARETT))
    T, _ = analyze("BP-1")
    assert [a.kind for a in T.actions] == ["assign"] and T.plan_expert.id == "garett"
    assert T.auto and T.stage == "Article link posted"
    ops, desc = logic.ops_for(T, "assign", True)
    assert ops[0]["fields"][config.F_EXPERT] == {"accountId": GARETT}
    assert ops[0]["fields"][config.F_PARTICIPANTS] == [{"accountId": EVE}, {"accountId": GARETT}]
    assert ops[-1] == {"op": "transition", "to": "Review"}


def test_step1_unclear_category_needs_a_human():
    load(issue("BP-1", "how to lose weight, 1800 words", "Text", ago(10), author=EVE,
               comments=[comment(EVE, ago(1), "", DOC)]))
    T, _ = analyze("BP-1")
    assert T.actions[0].disabled and "Pick a category or expert" in T.warnings and not T.auto
    db.execute("insert into overrides (jira_key, category) values ('BP-1', 'nutrition')")
    T, _ = analyze("BP-1")
    assert T.plan_expert.niche == "nutrition" and T.auto


def test_step2_expert_commented_then_note():
    base = dict(author=EVE, expert=ANGELICA, participants=[EVE, ANGELICA])
    load(issue("BP-5", "keto snacks, 1600 words", "Review", ago(10), **base,
               comments=[comment(EVE, ago(5), "", DOC), comment(ANGELICA, ago(2), "Left my comments in the doc.")]))
    T, _ = analyze("BP-5")
    assert [a.kind for a in T.actions] == ["toProof", "note"] and T.stage == "Expert commented" and T.auto
    ops, _ = logic.ops_for(T, "note", True)
    assert ops[0]["op"] == "comment" and ops[0]["internal"] is True
    assert ops[0]["adf"]["content"][0]["content"][0]["attrs"]["id"] == EVE
    # 2b: a note already exists after the expert comment → only the move
    load(issue("BP-5", "keto snacks, 1600 words", "Review", ago(10), **base,
               comments=[comment(EVE, ago(5), "", DOC), comment(ANGELICA, ago(2), "Done."),
                         comment(ME, ago(1), " Hi. Please address the comments. Thanks.", mention=EVE)]))
    T, _ = analyze("BP-5")
    assert [a.kind for a in T.actions] == ["toProof"] and T.stage == "Note sent, still in Review"


def test_step2_question_from_expert_is_a_warning():
    load(issue("BP-5", "keto snacks", "Review", ago(10), author=EVE, expert=MARIA,
               comments=[comment(EVE, ago(5), "", DOC), comment(MARIA, ago(2), "Is the 2nd source right?")]))
    T, _ = analyze("BP-5")
    assert "Expert's last comment looks like a question" in T.warnings and not T.auto


def test_step3_and_step4_proofreading():
    c = [comment(EVE, ago(9), "", DOC), comment(CARTER, ago(6), "comments"),
         comment(ME, ago(5), " Hi. Please address the comments. Thanks.", mention=EVE)]
    load(issue("BP-6", "squat guide", "Proofreading", ago(20), author=EVE, expert=CARTER, comments=c + [
        comment(EVE, ago(1), "Fixed")]))
    T, _ = analyze("BP-6")
    assert [a.kind for a in T.actions] == ["addTim"] and T.auto
    load(issue("BP-6", "squat guide", "Proofreading", ago(20), author=EVE, expert=CARTER, proof=TIM,
               comments=c + [comment(EVE, ago(2), "Fixed"), comment(TIM, ago(1), "Proofread, all good")]))
    T, _ = analyze("BP-6")
    assert [a.kind for a in T.actions] == ["toReady"]
    load(issue("BP-6", "squat guide", "Proofreading", ago(20), author=EVE, expert=CARTER, proof=TIM,
               comments=c + [comment(EVE, ago(2), "Fixed")]))
    T, _ = analyze("BP-6")
    assert not T.actions and T.stage == "With proofreader"


def test_ignored_commenters_and_window():
    load(issue("BP-7", "squat guide", "Text", ago(30), author=EVE,
               comments=[comment(EVE, ago(5), "", DOC), comment(OKSANA, ago(1), "img", "https://figma.com/x")]))
    T, ctx = analyze("BP-7")
    assert all(c.aid != OKSANA for c in T.cs)
    assert T.actions and not T.auto and "older than 3 days" in T.auto_why  # windowDays = 3


def test_writing_late_after_5_business_days():
    load(issue("BP-8", "squat guide", "Text", ago(30), author=JEREMY, participants=[JEREMY],
               histories=[history(ago(8), field_item(config.F_AUTHOR, None, JEREMY)),
                          history(ago(8), field_item(config.F_PARTICIPANTS, "[]", f"[{JEREMY}]"))]))
    T, _ = analyze("BP-8")
    assert T.writing_late and T.stage == "Writing"
    load(issue("BP-9", "squat guide", "Text", ago(30), author=JEREMY,
               histories=[history(ago(3), field_item(config.F_AUTHOR, None, JEREMY))]))
    assert not analyze("BP-9")[0].writing_late


def test_expert_silent_after_7_days():
    load(issue("BP-11", "squat guide", "Review", ago(30), author=EVE, expert=CARTER,
               comments=[comment(EVE, ago(9), "", DOC)]))
    T, _ = analyze("BP-11")
    assert T.expert_silent and T.stage == "With expert"
    db.execute("insert into expert_asks (jira_key, at) values ('BP-11', %s)", (NOW - timedelta(days=2),))
    assert not analyze("BP-11")[0].expert_silent


def test_followups_and_drafts_are_idempotent():
    # 1st note to the writer unanswered for 3+ business days, on two tickets
    for k in ("BP-20", "BP-21"):
        load(issue(k, f"{k} squats, 1800 words", "Review", ago(30), author=EVE, expert=CARTER,
                   comments=[comment(EVE, ago(20), "", DOC), comment(CARTER, ago(15), "done"),
                             comment(ME, ago(7), "Hi. Any news on the edits?", mention=EVE)]))
    ctx = service.context(now=NOW)
    D = logic.derive(service.tickets(ctx, "mine"), set(), {}, ctx)
    assert {t.key for t in D["no_reply"]} == {"BP-20", "BP-21"}
    row1, created1 = service.draft_followup(EVE, D, ctx, "test")
    row2, created2 = service.draft_followup(EVE, D, ctx, "test")
    assert created1 and not created2 and row1["id"] == row2["id"]
    assert db.scalar("select count(*) from outbound_messages") == 1
    assert row1["body"].startswith("Hi Eve, hope you're doing well! Just following up on the edits for these tickets:")
    assert "• <https://newsiteam.atlassian.net/browse/BP-20|BP-20 BP-20 squats>" in row1["body"]


def test_second_note_flag_and_pause_after_slack():
    load(issue("BP-30", "squats", "Review", ago(30), author=EVE, expert=CARTER,
               comments=[comment(EVE, ago(20), "", DOC), comment(CARTER, ago(15), "done"),
                         comment(ME, ago(12), "Hi. Please address the comments.", mention=EVE),
                         comment(ME, ago(6), "Hi. Any news on the edits?", mention=EVE)]))
    ctx = service.context(now=NOW)
    ts = service.tickets(ctx, "mine")
    D = logic.derive(ts, set(), {}, ctx)
    assert [a.t.key for a in D["flagged"]] == ["BP-30"]
    D = logic.derive(ts, set(), {EVE: {"BP-30": NOW - timedelta(days=1)}}, ctx)
    assert not D["flagged"] and D["follow"][0].paused


def test_same_step_detects_changes():
    load(issue("BP-40", "squats", "Review", ago(10), author=EVE, expert=CARTER,
               comments=[comment(EVE, ago(5), "", DOC), comment(CARTER, ago(2), "ok")]))
    old, _ = analyze("BP-40")
    load(issue("BP-40", "squats", "Proofreading", ago(10), author=EVE, expert=CARTER,
               comments=[comment(EVE, ago(5), "", DOC), comment(CARTER, ago(2), "ok")]))
    new, _ = analyze("BP-40")
    assert "status is now Proofreading" in logic.same_step(old, new, ["toProof"])
