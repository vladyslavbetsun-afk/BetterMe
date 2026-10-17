# Decisions

Phase 0 answers (spec 05 §3, §10) and every judgement call made while building. **Open** items need an answer
from Vladyslav or the platform admin. Update the entry when it's answered.

## Phase 0: platform (open)

| # | Question | Status / current behaviour |
|---|---|---|
| D-01 | Can the platform's read-only Jira account (`ai-integration-ro@betterme.world`) see project BP? | **Open.** Not tested: this build was made outside the slop machine, without its tools. Test in Phase 0; if Jira answers 404, ask the platform admin for BP browse access. `core/jira.py` reports that 404 in plain words on the status strip. How the platform hands the app its Jira credentials is also unknown: the client accepts `JIRA_PROXY_URL`, `JIRA_EMAIL`+`JIRA_API_TOKEN` or `JIRA_BEARER_TOKEN`; adapt `core/jira.py:_env` to whatever `needs.atlassian` provides (see the template's docs). |
| D-02 | Supported path for Jira **writes** (spec 05 §9: transitions, field edits, comments, create issue). | **Open.** Until answered the app is read-only toward Jira: every step becomes "do this in Jira" plus the comment to copy. The write client exists (`JIRA_WRITE_*` variables, `jira_writes_enabled` flag, off). |
| D-03 | Slack delivery. | Default as the spec proposes: **(a)** writer DMs and the budget message are drafts plus an "Open DM" link that Vladyslav sends himself; **(b)** batch and daily report post to a private channel only if `SLACK_BOT_TOKEN` + `SLACK_OPS_CHANNEL` are approved and set; otherwise they are drafts too. VERIFY in the template's `docs/extending.md` whether the Slop Agents bot can be used by a plain app. |
| D-04 | Egress approval for `api.notion.com`, `api.ahrefs.com`, Google APIs. | **Open.** Nothing calls them until the matching secret exists; their jobs show grey "not configured" chips. |
| D-05 | GSC: service account or Ahrefs `gsc-*` endpoints (spec 01 §3)? | **Open** (Phase 4). |
| D-06 | Stack. | The slop template wasn't available here, so the app is plain Python: FastAPI + Jinja2 server-rendered pages + small inline JS, Postgres via psycopg 3, APScheduler. It keeps the template's contract (`/ping`, `/startup`, `/selftest`, migrations at boot, `X-Auth-Request-Email`). **When the repo is created with `slop-create-app`, move `src/`, `tests/`, `scripts/` and `docs/` into the template and keep its `slop_client.py`, Dockerfile, lint/test/security tooling.** |
| D-07 | Legal gate answers (spec 05 §4). | Drafted in `slop.yaml` → `legal:` for Vladyslav to confirm. |

## Judgement calls made while building

| # | Topic | Decision | Why |
|---|---|---|---|
| D-08 | Category detection (00 §6.1) | Hits on one side only decide it (e.g. "wall pilates for beginners" → fitness). With hits on both sides, one must lead by more than one, otherwise "unclear". | A strict reading of 00 §6.1 ("fitness wins if fit > nut + 1") would make every single-keyword title unclear, which isn't what the legacy Review Flow does and would break the acceptance check "Review sections list the same tickets as legacy". The keyword lists are the longer ones from 00 §6.1. |
| D-09 | `12k` / `15k` in summaries | Never read as a word count: such tickets are **unpriced** and counted separately on Spend and Assign. | 00 §1 and §6.2 (VERIFY whether it's search volume). |
| D-10 | Spend recognition (00 §6.3, VERIFY with Yuliia Horetska) | A writer's article counts in the month it **first** left Text; the expert's review in the month it first left Review; proofreading when it first left Proofreading. A ticket that bounces back later is never paid twice. Writers flagged "no expert review" add no expert line. | The legacy JQL `status CHANGED FROM "Text" DURING (...)` would count a bounced ticket again in a later month. |
| D-11 | Writer lines vs expert fee | Spend lists writer fees and expert fees on separate lines. Assign's "month so far" per writer is the writer line from the same calculation (the legacy desk added the expert fee into the writer's figure). | Spec 05 §8.2: the two screens must not disagree. |
| D-12 | Proofreader (Tim) and VERIFY rates | Tim has no rate row, so his articles show as unpriced. Expert rates are seeded per article as 00 §2 lists them, with a VERIFY note. Kelsey and Amanda are seeded inactive. | 00 §2 VERIFY flags. Fix in Admin → Roster (effective-dated). |
| D-13 | Nudge recipient key | Follow-up DMs are keyed by the writer's Jira accountId (always known), not the Slack ID. Imported `slackSent` rows use the same idempotency recipe, so a message already sent that day can't be drafted again. | 00 §3 idempotency key. |
| D-14 | Message titles | Writer follow-ups use the short title (summary up to the first comma), as BP Review Flow does today; publishing batches use the full summary, as BP Publishing Batches does today. | 00 §3: "keep verbatim; people are used to them". |
| D-15 | "Auto-Slack" after the 2nd/3rd note | Becomes **auto-draft**: the `review_nudge_drafts` job (weekdays :55) drafts the DM so it's waiting for Vladyslav; it never sends. | Decision D-03 (a). `review.autoSlackSince` keeps its meaning. |
| D-16 | Review automation | Job `review_automation` (weekdays 08:52–18:52) runs only with `review_automation_enabled`; with `review_automation_dry_run` on (the default) it only logs "would do X" to the audit log; for real runs it also needs `jira_writes_enabled`. It re-reads each ticket from Jira first and skips it if anything changed. | Spec 05 §8.3, Phase 5. Disable Cowork trigger `trig_013mqoB1FWCjhUuqNra6VXuC` before turning the dry run off. |
| D-17 | Publishing QA mismatch rule | Flag when the live page's "Updated on" (JSON-LD `dateModified`, else the visible "Updated on" text) is more than 3 days older than the Jira publish date, or the page doesn't return 200. The H1 is shown next to the ticket title for a human to judge. | Spec 04 §3 / spec 01 §4. A real "H1 unchanged" check needs page-snapshot history, which builds up from the daily `qa_check_live` job. |
| D-18 | Owner bootstrap | `OWNER_EMAILS` (env, set in the portal) makes those emails owners. Everyone else gets access through `people.email` + `people.app_role` in Admin → Roster. No email addresses are committed. | Spec 05 §4: minimise personal data. |
| D-19 | Image status before spec 03 | `/api/images/status` and Publish use the legacy rule (an Oksana or Karina link that isn't a live page, a Google Doc or Jira) and only answer `complete` / `missing`. | Spec 03 §7.3, Phase 4. |
| D-20 | Notion property types | Name (title), Status (status) and URL 1 (url) are written with their types; other editable properties are written as rich text. **VERIFY** whether "Choose Primary", "Blog Category" and "New/Upd" are selects, and whether the category property is "Blog Category" or "Primary category" (00 §4). | Unknown from the legacy code. |

## Not built yet (by plan)

- Phase 4: Performance (spec 01), Images queue (spec 03), Intake (spec 02). Their pages exist as placeholders; Performance already shows the imported October tracker data.
- Phase 5: Jira writes in production (needs D-02).
- Phase 6: cutover checklist (spec 05 §10).
