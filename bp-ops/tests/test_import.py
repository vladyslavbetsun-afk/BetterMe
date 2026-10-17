import json
import sys
from pathlib import Path

import db

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_exports  # noqa: E402

EVE = "712020:51b52722-9eb1-4aa8-8b6d-527b045f3913"
ROOT = Path(__file__).resolve().parents[1]


def write(folder, name, data):
    (folder / name).write_text(json.dumps(data))


def test_import_exports(tmp_path):
    write(tmp_path, "bp-review-flow__settings.json", [{"doc_id": "main", "data": {"automation": True, "windowDays": 3,
                                                                                    "noteMode": "internal"}}])
    write(tmp_path, "bp-review-flow__exclusions.json", [{"doc_id": "BP-9", "data": {"title": "old", "at": 1760000000000}}])
    write(tmp_path, "bp-review-flow__overrides.json", [{"doc_id": "BP-8", "data": {"category": "nutrition",
                                                                                     "expertId": "x"}}])
    write(tmp_path, "bp-review-flow__slackLinks.json", [{"doc_id": "nobody", "data": {"slackId": "U1"}}])
    # Eve was nudged twice within a second on Oct 15 (the known bug): same set → one row
    write(tmp_path, "bp-review-flow__slackSent.json", [{"doc_id": EVE, "data": {
        "name": "Eve", "at": 1760530000000, "tickets": {"BP-1": 1760530000000, "BP-2": 1760530000000}}}])
    write(tmp_path, "bp-publishing-batches__batches.json", [{"doc_id": "b1", "data": {
        "id": "b1", "n": 7, "keys": ["BP-1", "BP-2"], "createdAt": 1760530000000}}])
    write(tmp_path, "blog-spend-dashboard__spend.json", [{"doc_id": "colette", "data": {"amount": 2500}},
                                                          {"doc_id": "oksana", "data": {"amount": 320, "note": "inv 4"}}])
    out = import_exports.main([str(tmp_path), "--october", str(ROOT / "legacy/october-updates-tracker/october-updates-weekly.json")])
    out2 = import_exports.main([str(tmp_path)])  # re-run: no duplicates for idempotent tables
    assert db.get_setting("review.windowDays") == 3 and db.get_setting("review_automation_enabled") is False
    assert db.scalar("select count(*) from exclusions") == 1
    assert db.scalar("select count(*) from outbound_messages where state = 'sent'") == 1
    assert db.scalar("select count(*) from batch_items where batch_id = 'b1'") == 2
    assert out["october_rows"] == 74 and db.scalar("select count(*) from ahrefs_page_weekly") == 74
    assert db.scalar("select count(*) from articles where cohort = 'update'") == 74
    assert db.scalar("select count(*) from import_issues where source = 'review/slackLinks'") >= 1
    assert db.scalar("select count(*) from spend_lines where person_id = 'oksana' and category = 'design'") == 1
    assert out2["unmatched_rows"] >= out["unmatched_rows"]
