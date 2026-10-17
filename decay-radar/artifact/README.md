# Decay Radar (claude.ai artifact)

Source of the Decay Radar page, a claude.ai artifact that runs spec 06 in the browser through the viewer's connectors.

- Live page: https://claude.ai/artifact/DyW4ZB7fwZFzVzoUuWyryS (private to its owner until shared)
- Connectors: Ahrefs (organic keywords; Site Audit project 3897375 for page audits), Atlassian (read-only BP ticket check), Notion (Articles data source: open-card check, card creation after confirmation, comments)
- State: the artifact's shared database. It holds `items` (one per page), `runs`, `cards` (per page and ISO week), `suggestions` and `settings/main`.

## How it differs from the Python CLI

- **Page audit.** It reads the Ahrefs Site Audit crawl (`site-audit-page-content`, 50 units/page) instead of fetching betterme.world live, because an artifact can't fetch other sites. Pages missing from the crawl (it is capped at about 10k URLs) are levelled without age, structure or claim checks and flagged "no audit". The crawl can lag the live page by up to a week.
- **Competitor length check.** Not run, the same as Option B.
- **Detection rows.** Default `max_rows` is 300, because the unit guard also covers the audit: 300×55 + 100×18 + 60×50 + 100 = 21,400 units.
- **Image alt text.** Not checked, because the crawl's page text drops images.

To update the page, edit `index.html` and republish it to the same artifact URL.
