# Blog Article Tracker

Source of the Blog Article Tracker dashboard, a claude.ai artifact (Dashboard type) that tracks the organic performance of blog articles published or updated since Aug 17, 2026.

- Live page: https://claude.ai/artifact/J8LKqrK4GsrBr6q7cz1AZu (private to its owner until shared)
- Connectors: Atlassian (newsiteam Jira, project BP) and Ahrefs (Site Explorer)
- `index.html` is the page stored as `files/index.html` in the dashboard's store; the datasets (`jira_articles`, `ahrefs_pages`) and params live in the store too.
- `articles-since-2026-08-17.csv` is a snapshot of the 85 articles taken on Oct 17, 2026.

## How the article list is built

1. Jira query: `project = BP AND (status changed to "Published" after "2026-08-17" OR labels = "perf-track")`.
2. Each ticket's live URL is the latest comment that holds only a `betterme.world/articles/...` link (the publisher posts it on publishing). The comment date is the article's "live since" date.
3. Tickets whose link was posted before Aug 17 are dropped (369 tickets were moved to Published after Aug 17, mostly in bulk on Aug 18 and Aug 21, but only 85 went live after it), unless they carry the `perf-track` label.
4. Type is "Update" when the ticket summary says "update", otherwise "New".

## Adding an article

- New articles join automatically once their BP ticket is Published and has the live-link comment.
- Any other article: add the Jira label `perf-track` to its BP ticket (it needs the live-link comment).

## Performance data

Ahrefs Site Explorer estimates (monthly organic visits, keywords, top keyword and its position), now vs a comparison date (default Aug 16, 2026). The Google Search Console data connected to the Ahrefs Betterme project stops on Aug 3, 2026, so real clicks and impressions aren't available until that sync is fixed. Each page load costs about 26 Ahrefs API units per ranking article.
