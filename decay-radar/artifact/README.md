# Decay Radar (claude.ai artifact)

Source of the Decay Radar page, a claude.ai artifact that runs spec 06 in the browser through the viewer's connectors.

- Live page: https://claude.ai/artifact/DyW4ZB7fwZFzVzoUuWyryS (private to its owner until shared)
- Connectors:
  - **Ahrefs:** organic keywords; Site Audit project 3897375 for page audits and related-article lookup; SERP People Also Ask and related terms for ticket drafts.
  - **Atlassian:** BP ticket checks; Article tickets created after confirmation; follow-up comments.
  - **Google Sheets:** the quiz-link sheet "2 Wordpress Guide".
  - **Claude (`sample`):** drafts the title, meta fields, subheadings and link anchors.
- State: the artifact's shared database. It holds `items` (one per page), `runs`, `tickets` (one per page), `suggestions` and `settings/main`.

## Jira tickets

Select L1–L3 pages, press **Create Jira tickets**, then **Prepare drafts**. Each page gets an editable BP Article draft:

- **Summary:** `{kw}, {N} words, update`, where N is the median of recent BP update tickets.
- **Description:** bolded labels in this order: Title, Meta Title, Meta Description, **Original article**, Main keyword, LSIs, Quiz/topic, Category, Update scope (the level, its reason and the checklist), and Expert left blank.
- **Subheadings (required):** 6–10 H2s from Claude, based on the current outline and People Also Ask.
- **Linked Articles (required, exactly 3):** a live betterme.world article URL plus anchor text for each. The URLs come only from the page's own internal links, related URLs in the Site Audit crawl, and same-category pages on the board. Claude picks the three and writes the anchors, and any URL outside those sources is rejected.
- **Additional Keywords and FAQs:** set as ADF fields.
- **Request Type, Managers and Author:** Request Type is Article; Managers is set to you; **Set me as Author** (per ticket, or "on every ticket" at the top of the drafts) also sets the Author field (`customfield_11710`) to you.
- **After creating:** the ticket is re-read to verify the summary, the Original article line, Request Type, and every custom field including all 3 links.

**Existing tickets.** BP is searched both by the article URL (the `Article:` / `Original article:` line) and by the main keyword (a ticket summary whose keyword equals the page's main keyword). This happens in the weekly run, where an open match holds the page as L0, and again just before writing. A page with an open ticket, or one published within the last 60 days, never gets a second ticket. Notion is not used at all.

## How it differs from the Python CLI

- **Page audit.** It reads the Ahrefs Site Audit crawl (`site-audit-page-content`, 50 units/page) instead of fetching betterme.world live, because an artifact can't fetch other sites. Pages missing from the crawl (it is capped at about 10k URLs) are levelled without age, structure or claim checks and flagged "no audit". The crawl can lag the live page by up to a week.
- **Competitor length check.** Not run, the same as Option B.
- **Detection rows.** Default `max_rows` is 300, because the unit guard also covers the audit: 300×55 + 100×18 + 60×50 + 100 = 21,400 units.
- **Image alt text.** Not checked, because the crawl's page text drops images.

To update the page, edit `index.html` and republish it to the same artifact URL.
