import config
import db
from conftest import ago
from core import sync
from factory import EVE, ME, OKSANA, YULIIA, comment, field_item, history, issue, load, status_item


def test_normalize_and_store_is_idempotent():
    i = issue("BP-10", "squats for beginners, 1800 words, update", "Ready", ago(20), author=EVE, participants=[EVE],
              comments=[comment(EVE, ago(10), "Done", "https://docs.google.com/document/d/abc"),
                        comment(OKSANA, ago(3), "images", "https://www.figma.com/file/zzz"),
                        comment(YULIIA, ago(1), "", "https://betterme.world/articles/squats/"),
                        comment(ME, ago(2), " Hi. Please address the comments.", mention=EVE)],
              histories=[history(ago(19), field_item(config.F_AUTHOR, None, EVE)),
                         history(ago(19), status_item("Open", "Text")),
                         history(ago(9), status_item("Text", "Review")),
                         history(ago(4), status_item("Review", "Ready"))])
    load(i)
    load(i)  # twice: no duplicates
    t = db.one("select * from tickets where jira_key = 'BP-10'")
    assert t["type"] == "update" and (t["word_min"], t["word_max"]) == (1800, 1800)
    assert t["doc_url"] == "https://docs.google.com/document/d/abc"
    assert t["live_url"] == "https://betterme.world/articles/squats/"
    assert t["author_id"] == EVE and t["category_detected"] == "fitness"
    assert t["entered_ready_at"] is not None
    assert db.scalar("select count(*) from comments where jira_key = 'BP-10'") == 4
    assert db.scalar("select count(*) from status_transitions where jira_key = 'BP-10'") == 3
    assert db.scalar("select count(*) from field_changes where jira_key = 'BP-10'") == 1
    mine = db.one("select * from comments where author_account_id = %s", (ME,))
    assert mine["mentions"] == [EVE] and "Please address" in mine["body_md"]

    # a comment deleted in Jira disappears from the mirror
    i["fields"]["comment"]["comments"].pop(0)
    load(i)
    assert db.scalar("select count(*) from comments where jira_key = 'BP-10'") == 3


def test_adf_parse_marks_and_text():
    text, links, mentions = __import__("core.jira", fromlist=["x"]).adf_parse({"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Doc", "marks": [
            {"type": "link", "attrs": {"href": "https://docs.google.com/document/d/q"}}]},
            {"type": "text", "text": " and https://example.com/x."}]}]})
    assert "https://docs.google.com/document/d/q" in links and "https://example.com/x" in links
    assert mentions == [] and text.startswith("Doc")


def test_incremental_uses_relative_window(monkeypatch):
    seen = []

    class Fake:
        def search(self, jql, fields, expand=None):
            seen.append(jql)
            return []

        def changelog(self, key):
            return []

    db.execute("insert into job_runs (job, started_at, finished_at, status) values "
               "('sync_jira_full', now() - interval '20 minutes', now(), 'ok')")
    sync.sync_incremental(Fake())
    assert seen and "updated >= -25m" in seen[0]
