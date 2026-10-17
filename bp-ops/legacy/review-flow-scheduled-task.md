# Legacy: "BP Review Flow automation" scheduled task (Cowork)

- Trigger id: `trig_013mqoB1FWCjhUuqNra6VXuC`
- Schedule: `CRON_TZ=Europe/Brussels 52 8-18 * * 1-5` (weekdays, hourly 08:52–18:52)
- Status on 2026-10-17: enabled; last run succeeded 2026-10-16 18:52. **Every run exits at step 1** because `settings/main.automation = false` in the artifact database.
- Artifact: https://claude.ai/artifact/DhWgTXa9SMjqE5w82KkzdK

Port this logic as the server-side job `review_automation` (spec 05 §8.3). Disable this task before enabling the job.

## Prompt (verbatim)

You run the scheduled part of the "BP Review Flow" dashboard (artifact https://claude.ai/artifact/DhWgTXa9SMjqE5w82KkzdK). Work silently and do not ask questions. Use the ArtifactData tool (load it with ToolSearch "select:ArtifactData") for the dashboard's database and the Atlassian connector tools for Jira. Never send Slack messages or follow-up notes; only the four workflow steps below.

A "note" below means a comment of yours containing "Please address the comment" or "Please address the comments" (either wording, any case).

1. Read settings: ArtifactData get, collection "settings", doc_id "main". If `automation` is not true, stop immediately and do nothing else. Note `windowDays` (default 14) and `noteMode` ("internal" or "standard").
2. Read ArtifactData list of collection "exclusions" (doc ids are ticket keys to skip) and "overrides" (doc id = ticket key, fields `category` and/or `expertId`).
3. Jira cloudId is 657e24cd-f643-4482-aba5-7e848607df28. Get your own accountId with atlassianUserInfo (ME). Search with searchJiraIssuesUsingJql, responseContentFormat "markdown", maxResults 100 (follow pageInfo.endCursor as nextPageToken): `project = BP AND status in ("Text","Review","Proofreading") AND customfield_11709 = currentUser()`, fields: summary, status, comment, customfield_11710 (Author/writer), customfield_11711 (Expert), customfield_11712 (Proofreader), customfield_11208 (Request participants), customfield_11709 (Managers). Also count tickets per expert for `project = BP AND status = "Review"` (field customfield_11711). Note: both search and getJiraIssue return issues under issues.nodes.
4. Ignore every comment written by Oksana Pidlisna (712020:7cf474f8-6ae6-439f-8d54-f6a1e3143066) or Yuliia Koreniuk (712020:b345726f-fe25-4239-a7dc-7322d7dbc2ae). Experts: Fitness = Carter Lee 712020:78a486c4-c1e4-4bc0-bba9-4676513ecb28, Garett Reid 5de4fe878389de0cd335416b; Nutrition = Angelica Galvan 712020:43ac8bef-1645-465e-9909-5bbb7ee20fa5, maria.eugenia.coaching 712020:87a66480-0c2d-4444-be68-26bb3afbbd60. Proofreader Tim Jones = 70121:f5089ddd-2808-4286-a217-02dd8bda85e9. Writer = Author field. "Article link" = the latest writer comment containing an http link.
5. For each ticket not excluded, where ME is in Managers, decide at most one step:
   - Step 1 (status Text, writer posted an article link): expert = override expertId, else the existing Expert field, else by title category (keywords like workout/exercise/yoga/squat/pilates → Fitness; diet/meal/snack/drink/food/recipe/"good for you" → Nutrition; use the override category if set) picking the category's expert with fewer tickets in Review. If the category is unclear or there is no Author, skip. Action: editJiraIssue set customfield_11711 = {accountId} and customfield_11208 = existing participants plus the expert (array of {accountId}); then transitionJiraIssue id "21".
   - Step 2 (status Review, an expert commented after the article link, and no note after that expert comment): skip if there is no Author or the expert's last comment contains "?". Action: transition id "31", then addCommentToJiraIssue with contentFormat "adf" and commentBody = JSON string of {"type":"doc","version":1,"content":[{"type":"paragraph","content":[{"type":"mention","attrs":{"id":"<writer accountId>","text":"@<writer name>"}},{"type":"text","text":" Hi. Please address the comments. Thanks."}]}]}; when noteMode is "internal" add commentVisibility {"type":"role","value":"Service Desk Team"}.
   - Step 2b (status Review, expert commented and a note already exists after it): transition id "31".
   - Step 3 (status Proofreading, the writer commented after your latest note, Proofreader is not Tim, no Tim comment after the note): editJiraIssue customfield_11712 = {accountId: Tim} and customfield_11208 = existing participants plus Tim.
   - Step 4 (status Proofreading, Tim Jones commented after your latest note): transition id "41".
   Skip a ticket when the triggering comment is older than windowDays days, when it is in Proofreading with no expert comment at all, or when anything is ambiguous.
6. Before acting on a ticket, re-read it with getJiraIssue (same fields) and confirm the same step still applies; if not, skip it and log that it changed.
7. Log every action and every failure to the dashboard: ArtifactData set, collection "log", a new unique doc_id like "sched-<epoch ms>-<ticket key>", data {"at": <epoch ms>, "kind": "sched" (or "fail" for failures), "key": "<ticket key>", "text": "<KEY>: <what you did, or why it failed>"}. If nothing was eligible, write nothing.
End with a one-line summary of what you did.
