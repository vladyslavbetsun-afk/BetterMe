from datetime import date

from decay.audit import audit_html
from decay.jira import article_urls, match_tickets

from .conftest import BASE, TODAY, page_html

URL = BASE + "wall-pilates/"


def test_audit_parses_structure(cfg):
    html = page_html(title="Best Wall Pilates Workouts", updated="March 3, 2025", words=1200, key_takeaways=True,
                     faqs=5, question_h2s=[("Is wall pilates hard?", 50), ("How long?", 10)], table=False, imgs_no_alt=2,
                     extra="<p>You will lose 10 pounds in 30 days.</p>")
    a = audit_html(URL, html, cfg, TODAY)
    assert a.updated_on == "2025-03-03" and a.age_days == (TODAY - date(2025, 3, 3)).days
    assert a.title == "Best Wall Pilates Workouts" and a.h1 == a.title
    assert a.has_key_takeaways and a.faq_count == 5
    assert a.question_h2_count == 2 and a.question_h2_with_direct_answer == 1
    assert a.question_h2_missing_answer == ["How long?"]
    assert a.table_count == 0 and a.images_missing_alt == 2 and a.internal_links_out == 1
    assert "timeline claim" in a.claim_flags and "weight-loss outcome" in a.claim_flags
    assert "'best' in title/H1" in a.claim_flags
    assert 1100 < a.word_count < 1400  # nav/footer excluded
    assert not a.merged


def test_audit_jsonld_fallbacks(cfg):
    html = """<html><head><title>T</title><script type="application/ld+json">
    {"@graph":[{"@type":"Article","dateModified":"2026-01-05T10:00:00+00:00"},
    {"@type":"FAQPage","mainEntity":[{"@type":"Question"},{"@type":"Question"},{"@type":"Question"}]}]}
    </script></head><body><article><h1>T</h1><p>text</p></article></body></html>"""
    a = audit_html(URL, html, cfg, TODAY)
    assert a.updated_on == "2026-01-05" and a.faq_count == 3


def test_audit_redirect_is_merged(cfg):
    a = audit_html(URL, page_html(), cfg, TODAY, final_url=BASE + "another-article/")
    assert a.merged


def _issue(key, status, line, updated="2026-10-01T10:00:00.000+0000"):
    return {"key": key, "fields": {"status": {"name": status}, "statuscategorychangedate": updated, "description": {
        "type": "doc", "content": [{"type": "paragraph", "content": [
            {"type": "text", "text": "Title: x"}, {"type": "hardBreak"},
            {"type": "text", "text": line[0]},
            {"type": "inlineCard", "attrs": {"url": line[1]}}]}]}}}


def test_jira_requires_exact_article_url():
    similar = _issue("BP-1", "Text", ("Article: ", BASE + "wall-pilates-for-seniors/"))
    exact = _issue("BP-2", "Review", ("Original article: ", URL))
    o, r = match_tickets(URL, [similar, exact], TODAY, "Published", 60)
    assert o.key == "BP-2" and r is None
    o, r = match_tickets(URL, [similar], TODAY, "Published", 60)
    assert o is None and r is None


def test_jira_recent_published():
    pub = _issue("BP-3", "Published", ("Article: ", URL), updated="2026-09-15T10:00:00.000+0000")
    o, r = match_tickets(URL, [pub], TODAY, "Published", 60)
    assert o is None and r.key == "BP-3" and r.published_days_ago == 35
    old = _issue("BP-4", "Published", ("Article: ", URL), updated="2026-01-15T10:00:00.000+0000")
    assert match_tickets(URL, [old], TODAY, "Published", 60) == (None, None)


def test_article_urls_from_markdown_link():
    desc = {"type": "doc", "content": [{"type": "paragraph", "content": [
        {"type": "text", "text": "Article: "},
        {"type": "text", "text": "link", "marks": [{"type": "link", "attrs": {"href": URL + "?utm=1"}}]}]}]}
    assert article_urls(desc) == {URL}
