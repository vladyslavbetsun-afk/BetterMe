# Decay Radar (claude.ai artifact)

Source of the Decay Radar page, a claude.ai artifact that runs spec 06 in the browser through the viewer's connectors.

- Live page: https://claude.ai/artifact/DyW4ZB7fwZFzVzoUuWyryS (private to its owner until shared)
- Connectors: Ahrefs (organic keywords; Site Audit project 3897375 for page audits; SERP People Also Ask and related terms for card drafts), Atlassian (BP ticket checks; Article tickets created after confirmation), Notion (Articles data source: open-card check, card creation, JIRA link, comments), Google Sheets (quiz-link sheet "2 Wordpress Guide"), and Claude (`sample`) for the title and meta drafts
- State: the artifact's shared database. It holds `items` (one per page), `runs`, `cards` (per page and ISO week), `tickets` (per page), `suggestions` and `settings/main`.

## Cards and Jira tickets

Select L1–L3 pages and press **Cards & Jira tickets**. Choose Notion cards, Jira tickets or both, then **Prepare drafts**. For each page the radar drafts:

- **Additional keywords:** the page's lost keywords plus Ahrefs "also rank for".
- **LSIs:** Ahrefs "also talk about".
- **FAQs:** live People Also Ask.
- **Subheadings and Linked Articles:** the current H2s and internal links from the Site Audit crawl.
- **Quiz/topic:** picked from the quiz sheet.
- **Title, meta title and meta description:** written by Claude. The length counters show the 50–60 and 150–160 character targets.

Every field can be edited before you press Create. Drafting costs about 650 Ahrefs units per page.

**Existing tickets.** BP is searched both by the article URL (the `Article:` / `Original article:` line) and by the main keyword (a ticket summary whose keyword equals the page's main keyword). The weekly run holds a page as L0 when an open ticket matches either way, and the create step re-checks just before writing. A page with an open ticket, or one published within the last 60 days, never gets a second ticket. The card links to the existing ticket instead.

**What gets created.**

The Jira ticket follows `blog-jira-ticket-creation`:
- Summary: `{kw}, {N} words, update`, where N is the median of recent BP update tickets.
- Request Type Article, with Managers set to you.
- Description with bolded labels, in this order: Title, Meta Title, Meta Description, Original article, Main keyword, LSIs, Quiz/topic, Category, Update scope (the level, its reason and the checklist), and Expert left blank.
- Subheadings, Additional Keywords, Linked Articles and FAQs set as ADF fields.
- The ticket is re-read afterwards to verify the fields.

The Notion card:
- Name: the Jira summary, when a ticket exists.
- JIRA property: the ticket URL.
- Body: the original article link, the Jira link, the decay table, the checklist, Additional keywords, LSIs, FAQs and the audit facts.

## How it differs from the Python CLI

- **Page audit.** It reads the Ahrefs Site Audit crawl (`site-audit-page-content`, 50 units/page) instead of fetching betterme.world live, because an artifact can't fetch other sites. Pages missing from the crawl (it is capped at about 10k URLs) are levelled without age, structure or claim checks and flagged "no audit". The crawl can lag the live page by up to a week.
- **Competitor length check.** Not run, the same as Option B.
- **Detection rows.** Default `max_rows` is 300, because the unit guard also covers the audit: 300×55 + 100×18 + 60×50 + 100 = 21,400 units.
- **Image alt text.** Not checked, because the crawl's page text drops images.

To update the page, edit `index.html` and republish it to the same artifact URL.
