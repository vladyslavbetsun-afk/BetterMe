# Assignment Desk

Source of the Assignment Desk dashboard, a claude.ai artifact for assigning Open Jira Blog Project (BP) tickets to writers.

- Live page: https://claude.ai/artifact/2Ve75EqUjZgovYPMitEMxw (private to its owner)
- Connector: Atlassian (newsiteam Jira)
- Writer roster: the 12 writers, niches and rates from the Byline Board, plus Clare Kamau ($32.50/article, from the Blog Spend Dashboard)

Assigning a ticket re-reads it (it must still be Open), sets Author to the writer, adds the writer to Request participants, then moves the ticket to Text.

"Earned this month" counts articles that left Text since the 1st of the month (`status CHANGED FROM "Text" DURING (startOfMonth(), now())`), priced from the word count in the title times the writer's rate (or their flat article fee), plus the expert review fee: +$50 when the Expert is Carter Lee, Garett Reid or Angelica Galvan, +$20 for Maria Eugenia Corrarello. Open tickets show an estimate: +$50 for exercise topics, +$20–50 otherwise, nothing for writers who skip expert review. The writers & pricing panel can be hidden from the header; the choice is remembered in the browser.

To update the page, edit `index.html` and republish it to the same artifact URL.
