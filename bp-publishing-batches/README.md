# BP Publishing Batches

Source of the BP Publishing Batches dashboard, a claude.ai artifact for moving Jira Blog Project tickets from Ready to Published.

- Live page: https://claude.ai/artifact/CKoawJVQ14TN4s9GyRu7qN (private to its owner)
- Connectors: Atlassian (newsiteam Jira) and Slack

What it does:
- Lists BP tickets in Ready, split into those with an image link in the comments (posted by Oksana Pidlisna or Karina Sorvachova) and those without. Each ticket shows the latest Google Doc link from its comments.
- Tick up to 4 tickets and create a batch. "Add Yuliia & send Slack" adds Yuliia Koreniuk to Request participants on each ticket, then DMs her "Hi. Here are articles for publishing:" with a bullet list of the ticket links. Choose "Send now" or "Schedule" to have Slack deliver the DM at a set date and time (your local time, 3 minutes to 120 days ahead). "Change time" on a scheduled batch schedules a new message (or sends it now) and reminds you to delete the old scheduled one in Slack, since the Slack connector cannot edit or cancel scheduled messages.
- When Yuliia posts the live article link (betterme.world) in a ticket's comments, the ticket gets a "Move to Published" button.

Batches and the action log are kept in the artifact's database.

To update the page, edit `index.html` and republish it to the same artifact URL.
