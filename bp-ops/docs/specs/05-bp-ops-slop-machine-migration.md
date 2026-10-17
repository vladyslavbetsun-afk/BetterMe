# 05 — Move the BP pipeline onto the slop machine ("BP Ops")

> **What this is:** the plan and build spec for merging the blog-pipeline artifacts into one internal app on BetterMe's slop machine. The app gets one database, one roster, scheduled jobs, and one URL (proposed: `https://bp-ops.exdev.betterme.world`).
> **Read first:** `00-shared-reference.md` (all of it), then this file. Specs 01–04 are modules that plug into this app.
> **Reference implementations:** `legacy-artifacts/*.html` contain the current working code (Jira queries, parsing, business rules). Port logic from them; don't port their UI framework or their `window.claude.*` calls.
> **Skills to use in Claude Code:** `/slop-machine-skills:slop-migrate-app` (assessment and plan), then `slop-create-app` steps (repo, scaffold, deploy), `slop-ship` (each later change), `slop-migrate-data` (import the artifact data), `slop-share` (access), `slop-debug-app` (when something breaks). In the Claude Code desktop app, ask in plain words ("use the slop-migrate-app skill to…"), because slash commands only resolve in the terminal.

---

## 1. Why, and what "done" looks like

**Today:** 9 working artifacts plus 2 trackers, each with its own copy of the roster, its own database, and its own refresh habits. Two "scheduled" refreshes don't exist. The one real scheduled task is switched off by a settings flag. Writers got duplicate nudges. Spend data can't hold more than one month.

**Done means:**

- One URL, behind the BetterMe login, for Vladyslav and the named people who need it.
- One `people` table that every screen uses.
- Every background job visible on a status strip, with its last run time and any error.
- No duplicate outbound messages, enforced by the database.
- Monthly spend history computed from Jira, not typed in by hand.
- The old artifacts archived (§10), and the Cowork scheduled task "BP Review Flow automation" disabled.

## 2. What merges where

| Current artifact | Becomes module | Notes |
|---|---|---|
| Blog Pipeline Editor + Blog Pipeline Board | **Pipeline** (`/pipeline`) | Keep only the editor behaviour. Add auto-sync of Notion status from Jira (§8.1) |
| Assignment Desk | **Assign** (`/assign`) | rates and earnings come from `people`/`rates` |
| BP Review Flow ×3 (keep the logic of DhWg) | **Review** (`/review`) | one settings row; nudges idempotent; automation runs server-side |
| Byline Board (writers / experts / proofreading) + Editorial Load | **Load** (`/load`) | one operational "who has which tickets" view (§4: no speed rankings) |
| BP Publishing Batches | **Publish** (`/publish`) | uses the image status API from spec 03 |
| Blog Spend Dashboard | **Spend** (`/spend`) | month key; auto-computed from Jira plus fixed items; owner and finance only |
| October Updates Tracker, Slipped Pages Tracker, Two-Month Results, Article Progression | **Performance** (`/performance`) | spec 01 |
| (new) | **Intake** (`/intake`) | spec 02 |
| (new) | **Images** (`/images`) | spec 03 |
| (new) | **Flow** (`/flow`) | spec 04 |
| (new) | **Daily report** (`/report`) | §8.7 |
| (new) | **Admin** (`/admin`) | roster, rates, settings, job status, action log |

Retire without replacing: the "Untitled" empty deck and the two older BP Review Flow copies (`VdYb…`, `SLDg…`). Retire the pinned "Byline Board for Experts" and "for Proofreading" once Load ships.

## 3. Platform constraints and the decisions they force

These come from the slop machine's own rules (the `slop-help`, `slop-create-app` and `slop-migrate-app` skills). **Resolve each row in Phase 0 and record the answer in `docs/decisions.md`.**

| Need | What the platform gives | Decision / plan |
|---|---|---|
| **Read Jira BP** | Built-in Jira access is a **shared read-only account** (`ai-integration-ro@betterme.world`) that sees only the projects the platform team has opened to it. Jira answers **404** for anything else | Phase 0 test: does a BP search return issues? If it returns 404, ask the platform admin to grant that account browse access to **BP**. That is the normal path |
| **Write Jira** (transitions, field edits, comments: Assign, Review, Publish, Intake) | **Not supported** by the built-in access. It can't comment, transition, or act as a person | **Raise this with the platform admin in Phase 0** and describe exactly which writes are needed (§9 "permitted actions"). Don't paste a personal API token anywhere. **Until it's resolved the app is read-only toward Jira**: action buttons show "Copy comment", "Open in Jira" and pre-filled links, and the existing artifacts keep doing the writes (§10 hybrid period) |
| **Send Slack** (writer nudges, publishing batch, daily report, budget) | Apps can use Slack via a key the owner stores in the portal (custom secret) plus the `slack` egress alias. **Agents** post through the platform's shared "Slop Agents" bot into channels where it's invited. A plain app can also receive schedule envelopes and reply into a channel (`slack.delivery: workload`; **VERIFY** in the template's `docs/extending.md`) | Messages would come **from a bot, not from Vladyslav**. Writers are used to DMs from him. Options: (a) v1: the app writes drafts plus "Open DM" deep links and Vladyslav sends them; (b) the daily report and publishing batch post to a private channel (e.g. `#bp-ops`) with Volodymyr and Yuliia, where the Slop Agents bot is invited; (c) a Slack app token approved by the Slack admin. **Default: (a) for writer DMs, (b) for the daily report and batches** |
| **Read Slack** (Review Flow read a Jira→Slack DM feed) | Inbound webhooks are impossible: every request except health paths hits the BetterMe login | Drop the Slack feed. **Poll Jira directly** for comments and transitions, which is cleaner anyway |
| **Notion** (Articles database) | Not built in. It's a "new service": a custom secret plus a custom egress host with a justification (admin review). Legal review is "requested", but **deploy is not held** | Secret `NOTION_TOKEN` (an internal integration shared with the Articles database only); egress `custom: api.notion.com` |
| **Ahrefs, GSC, Google Sheets** | Ahrefs and GSC are new services, handled the same way. Google: the `gdrive` alias exists; **VERIFY** whether it covers the Sheets and Search Console APIs | `AHREFS_API_KEY` → `custom: api.ahrefs.com`. GSC per spec 01 §3. Sheets: `GOOGLE_SERVICE_ACCOUNT_JSON` |
| **LLM** (intake screening, briefs, report wording) | `needs.llm` with `LLM_BASE_URL`/`LLM_API_KEY`; every call names the person it's for | `monthly_budget_usd: 20`; `claude-haiku` by default, `claude-sonnet` for briefs. Pass the signed-in email, or `schedule:bp-ops` for jobs |
| **Scheduled jobs** | One container, no separate workers or cron containers. Use an in-process scheduler. The app **sleeps after 30 days with no real use** | APScheduler in-process, with a Postgres advisory lock per job (so a restart or a second replica can't double-run). Tier **S**, one replica. Daily use keeps the app awake |
| **State** | Postgres schema (`DATABASE_URL`), migrations at boot. Local disk is wiped on restart | All state in Postgres. Exports are generated on the fly |
| **Secrets** | Owner adds values in the portal **after the first deploy**. A declared key with no stored value fails the deploy | First deploy with **no** custom secrets (the code must start without them and show "not configured" chips). Then add the secrets one by one with `/slop-ship` |

## 4. The Legal gate: prepared answers

`slop-create-app` / `slop-migrate-app` asks these before anything is built. Answer accurately. Below is a draft for Vladyslav to confirm.

- **Q1, personal data about people outside BetterMe?** **Yes.** Freelance writers, experts and the proofreader: names, Jira/Slack IDs, per-word or per-article rates, and amounts owed per month. → This is a *warn and continue* outcome; Legal reviews it in the weekly report. Minimise it: no emails, no addresses, no bank or contract details. Rates live only in `rates`, visible to owners and finance.
- **Q2, colleagues?** **Yes, operational only.** Who owns which ticket, which stage it's in, and who has been asked to do what. **The app must not evaluate, rank, monitor speed, or inform decisions about named colleagues.** Concretely:
  - Keep: ticket-level ages ("this ticket has waited 6 business days for a doc"), queues, reminders, who-owns-what.
  - Drop or don't build: per-person speed leaderboards, the "writing time" ranking from the old Byline Board, per-person throughput (e.g. the publisher's daily output), any person-level "performance" chart.
  - Spend per person is **payment administration** (it's what Yuliia Horetska needs to pay invoices), not evaluation. Restrict it to owners and finance.
- **Q3, outside services, and does it act on its own?** New services: **Notion, Ahrefs, Google Search Console (and Sheets)**. Actions (once the write path exists): Jira transitions, field edits and comments in project BP; Slack messages. → Every action goes through an **ask-before-doing** confirmation, or an explicitly enabled automation with a visible log (§9).
- **Who can open it:** named people: Vladyslav (owner) and Volodymyr; Yuliia Horetska for `/spend` only (enforce per route); designers for `/images?me=1` only if they have BetterMe logins (**VERIFY**). Freelance writers never get access.
- **Retention:** operational logs and messages: **90 days**. Spend and performance history: **12 months**, because budgeting and year-over-year content performance need it. Implement deletion in a nightly job and record `retention.enforced: automatic`.

## 5. Architecture

- **Stack:** the slop template (Python). Keep `/ping`, `/startup`, `/selftest`, `src/slop_client.py` and the template's lint/test/security tooling. Server-rendered pages plus small JS (or HTMX). No SPA build step unless Claude Code and the template docs agree it's simpler.
- **Layout:**

```
src/
  app.py                 # routes mount modules, auth header → current user
  config.py              # JIRA field IDs, transition IDs, statuses (from 00 §1), feature flags
  db/migrations/*.sql    # run at boot, idempotent
  core/
    people.py            # roster, aliases, rates (effective-dated)
    jira.py              # read client (search, issue, changelog) + write client behind a feature flag
    notion.py  slack.py  ahrefs.py  gsc.py  llm.py
    business_days.py     # Europe/Brussels Mon–Fri + holidays
    rules.py             # category detection, word count, price (00 §6) — unit-tested
    outbound.py          # ALL messages/comments go through here: idempotency key, confirm, log
    scheduler.py         # APScheduler + pg advisory locks + job_runs
  modules/
    pipeline/ assign/ review/ load/ publish/ spend/ report/ admin/
    performance/ intake/ images/ flow/      # specs 01–04
tests/                    # rules, parsing, idempotency, migrations
docs/specs/               # this folder
docs/rules/               # rejection patterns, product features (exported)
docs/decisions.md
legacy/                   # legacy-artifacts/*.html for reference only (not served)
```

- **Auth:** read the signed-in email from `X-Auth-Request-Email`. Map it to `people.email` for role checks (owner / viewer / finance / designer). Route guards per module.
- **Jira sync (shared by every module):** `sync_jira_incremental` runs every 5 minutes on weekdays 08:00–19:00 Brussels time, otherwise hourly. JQL `project = BP AND updated >= -15m` (with overlap) upserts `tickets`, `comments`, and `status_transitions` (changelog). `sync_jira_full` runs nightly. All screens read from these tables, so page loads never call Jira.
- **Feature flags** in `settings`: `jira_writes_enabled`, `slack_send_enabled`, `notion_writes_enabled`, `review_automation_enabled`. All start `false`.

## 6. Core data model (Postgres)

```sql
-- people & money
people(id text primary key, display_name text, email text, jira_account_id text unique, slack_id text,
  role text check (role in ('writer','expert','proofreader','publisher','designer','manager','researcher','stakeholder','finance')),
  niche text, skip_expert_review bool default false, active bool default true, app_role text, notes text)
person_aliases(alias text primary key, person_id text references people)
rates(id bigserial primary key, person_id text references people, kind text, amount numeric, amount_max numeric,
  unit text check (unit in ('word','article','hour','month')), currency text default 'USD',
  billing text check (billing in ('upwork','invoice','retainer','internal')),
  effective_from date, effective_to date)

-- jira mirror
tickets(jira_key text primary key, summary text, status text, type text, created_at timestamptz, updated_at timestamptz,
  author_id text, expert_id text, proofreader_id text, managers text[], participants text[],
  word_min int, word_max int, category_detected text, doc_url text, live_url text, raw jsonb)
comments(id text primary key, jira_key text, author_account_id text, created_at timestamptz, body_md text, links text[])
status_transitions(jira_key text, at timestamptz, from_status text, to_status text, by_account_id text,
  primary key (jira_key, at, to_status))

-- workflow state (ported from artifact databases)
settings(key text primary key, value jsonb)                       -- review: windowDays, noteMode, autoSlackSince…
exclusions(jira_key text primary key, title text, at timestamptz, by text)
overrides(jira_key text primary key, category text, expert_id text, auto_slack bool)
expert_asks(jira_key text primary key, at timestamptz)

-- every action the app takes or proposes
actions(id bigserial primary key, kind text, jira_key text, payload jsonb, state text
  check (state in ('proposed','confirmed','sent','failed','cancelled')),
  proposed_by text, confirmed_by text, created_at timestamptz, executed_at timestamptz, error text,
  idempotency_key text unique)                                    -- ← kills the duplicate-nudge bug
outbound_messages(id bigserial primary key, channel text, recipient text, template text, body text,
  ticket_keys text[], idempotency_key text unique, state text, sent_at timestamptz, external_ts text)

-- publishing
batches(id text primary key, n int, created_at timestamptz, sent_at timestamptz, post_at timestamptz, archived bool)
batch_items(batch_id text references batches, jira_key text, position int, primary key(batch_id, jira_key))

-- spend
spend_months(month date primary key, status text check (status in ('open','closed')), closed_at timestamptz, closed_by text)
spend_lines(id bigserial primary key, month date references spend_months, person_id text, category text
  check (category in ('writing','review','proofreading','research','design','other')),
  source text check (source in ('jira_auto','fixed','manual')), jira_keys text[], amount numeric, note text,
  updated_at timestamptz)

-- ops
job_runs(id bigserial primary key, job text, started_at timestamptz, finished_at timestamptz, status text, rows int, error text)
audit_log(id bigserial primary key, at timestamptz, actor text, action text, target text, detail jsonb)
```

Modules 01–04 add their own tables, as listed in their specs.

**Idempotency key recipe:** `sha256(kind | recipient | sorted(ticket_keys) | local_date | template)`. Insert with `ON CONFLICT DO NOTHING`, and send only when the insert returned a row.

## 7. Moving the existing data

The artifact databases can only be read through Claude (Cowork's ArtifactData tool), not from Claude Code directly. Two-step process:

**Step A: export (run in Cowork, not Claude Code).** Paste this prompt into Cowork:

> Export these artifact databases to JSON files using ArtifactData `list` (paginate fully) and save them in a folder `bp-ops-export/` that I can download. Use one file per collection, named `<artifact>__<collection>.json`.
> • BP Review Flow `https://claude.ai/artifact/DhWgTXa9SMjqE5w82KkzdK`: settings, exclusions, overrides, slackLinks, slackSent, expertAsks, log
> • BP Publishing Batches `https://claude.ai/artifact/CKoawJVQ14TN4s9GyRu7qN`: batches, log
> • Slipped Pages Tracker `https://claude.ai/artifact/8ZdWKp6RCV6XJduQXiCWsz`: pages, progress, checks, meta
> • Blog Spend Dashboard `https://claude.ai/artifact/WhNYCedN3GRF5Nt3QR4qTr`: spend
> Then list the files with their row counts.

**Step B: import (Claude Code, `slop-migrate-data`)**, after the first deploy has created the schema.

| Export | → Table | Mapping notes |
|---|---|---|
| review `settings/main` | `settings` (`review.*` keys) | keep `windowDays` (3) and `noteMode`; set `review_automation_enabled = false` at first |
| review `exclusions`, `overrides`, `expertAsks` | same-named tables | `overrides.expertId` → `expert_id` |
| review `slackLinks` | `people.slack_id` | match on Jira accountId; report any unmatched |
| review `slackSent` | `outbound_messages` (state `sent`) | used for the "already nudged" logic; build the `idempotency_key` from the old data |
| review `log` | `audit_log` | keep 90 days |
| publishing `batches` | `batches` + `batch_items` | |
| slipped `pages`, `progress`, `checks`, `meta` | spec 01 `articles` (cohort `slipped`), `article_events`, `position_checks` | |
| spend `spend` | `spend_lines` for month `2026-10-01`, `source = manual` | only `colette` (2500) and `polina` (600) have values; convert them into `rates` rows with `unit = month` |
| `legacy-artifacts/october-updates-tracker/october-updates-weekly.json` | spec 01 `ahrefs_page_weekly`, `ai_citations_weekly` | 74 rows, week 2026-10-13 |
| roster (00 §2) | `people`, `person_aliases`, `rates` | seed SQL committed in `db/seed/` |

Verify the counts after import (the skill does this) and add a `/admin/import-report` page that lists unmatched rows.

## 8. Module specs for the migrated screens

Port the behaviour from `legacy/…html`. Below are the **changes from the artifacts** and the rules that must stay identical.

### 8.1 Pipeline (`/pipeline`), from Blog Pipeline Editor

- Notion cards (query from 00 §4) joined with `tickets` by the key in `JIRA`.
- Editable fields as before (Name, Status, Choose Primary, Blog Category, New/Upd, URL 1), written through `outbound.py` when `notion_writes_enabled` is on.
- **New:** `sync_notion_status` job, hourly. For each mismatch "Published in Jira but open in Notion" it **proposes** an action (Notion Status → Done; URL 1 = live URL). It applies the change automatically only if `settings.pipeline.auto_close = true`. Show a "N mismatches" badge.
- **New:** "Jira ticket with no Notion card" list, with "Create card" (blog-notion-ticket-creation rules).

### 8.2 Assign (`/assign`), from Assignment Desk

- Open queue, the writer picker (niche match first, then current load from `tickets`), and the price estimate (00 §6.3).
- The assign action (when writes are enabled): set Author, add to participants, transition to Text. Otherwise "Open in Jira" with copyable values.
- Month-to-date estimate per writer comes from the same calculation as Spend (§8.6), so the two can't disagree.
- **Fix:** don't parse `12k` as a word count.

### 8.3 Review (`/review`), from BP Review Flow (DhWg)

- Same queue sections, same step logic (Step 1 → expert assign + transition 21; Step 2 → transition 31 + "Please address" note; 2b; Step 3 → add Tim; Step 4 → transition 41), same timing rules (00 §6.4).
- The automation runs **server-side** as job `review_automation` (weekdays, hourly at :52, 08:52–18:52 Brussels time, matching today's cadence) only when both `review_automation_enabled` and `jira_writes_enabled` are on. It re-reads each ticket before acting, exactly like the current scheduled task prompt in `legacy/review-flow-scheduled-task.md`.
- "Straight to Ready" is kept and needs confirmation.
- Nudges: grouped per writer, and every one goes through `outbound.py`. **The duplicate-send bug can't recur** because of the UNIQUE idempotency key.
- **Drop:** the Slack DM feed reader (replaced by Jira polling).

### 8.4 Load (`/load`), from the 3 Byline Boards + Editorial Load

- One table per role (writers, experts, proofreader). Rows show the person, their current tickets (chips by stage) and their open count. Columns: ticket, stage, **ticket age in stage** (business days), last activity.
- Flags are **ticket-level** ("no doc after 5 bd", "expert quiet 7 d", "drafted but not moved": a link was posted while the ticket is still in Text).
- **Not ported:** per-person "writing time" averages, monthly averages per person, rankings (§4).
- The month-to-date amount is shown only to `owner`/`finance` roles.

### 8.5 Publish (`/publish`), from BP Publishing Batches

- Ready queue split by image status (spec 03 API; fallback: the Oksana/Karina comment rule).
- Batch builder: size 4 by default; "send now" or "schedule" (default next weekday 09:00).
- Delivery depends on the §3 Slack decision: (a) copy text plus deep link, or (b) post to `#bp-ops`. **Fix:** the old version couldn't cancel a rescheduled Slack message. With (b), the app owns the message and can edit or delete it.
- When Yuliia's live link appears, propose "→ Published" (one click when writes are enabled).

### 8.6 Spend (`/spend`), replacing Blog Spend Dashboard

- A month selector (any month since 2026-07).
- `spend_compute` job, nightly. For the open month it computes `jira_auto` lines:
  - writers: articles that **left Text** in the month × rate (00 §6.3)
  - experts: articles that **left Review** in the month × fee
  - proofreading: articles that **left Proofreading** × rate (**VERIFY** Tim's billing)
  - plus the `fixed` lines (Colette $2,500, Polina $600)
  - plus `manual` lines (designer invoices, e-com, other)
- Line drill-down shows the contributing Jira keys.
- Status open → **closed** (frozen numbers; closing records who and when).
- **"Budget message for Yuliia Horetska"**: generates the summary in the format of the `betterme-blog-budgeting` / `bm-budgeting` skills, and offers Copy or a Slack draft. Also an XLSX export.
- Access: owner and finance only.

### 8.7 Daily report (`/report`)

- Built at 17:00 Brussels time each weekday from the day's data:
  - articles published today (count + keys), updates published today
  - tickets moved to Text, Review or Ready today
  - batches sent
  - new Intake approvals
  - images delivered
  - blockers: Ready without images, QA mismatches, any failed job
  - free-text lines Vladyslav adds (Pinterest, budgeting, ad hoc)
- Format matches his current DM:

```
Report:
• 4 articles published
• 5 articles updated
• New tasks for writers/proofreader/designer/experts (6 assigned)
• <free-text lines>
• Bottleneck: <auto, if any>
```

- Delivery: Copy plus "Open DM with Volodymyr" (default), or post to `#bp-ops` (decision b).

### 8.8 Admin (`/admin`)

- Roster CRUD with effective-dated rates and aliases.
- Settings (all flags).
- Job status: `job_runs` with "Run now".
- Action log (`actions` + `outbound_messages` + `audit_log`), filterable.
- Import report.

## 9. Permitted actions (for the Legal register and for the platform-admin conversation)

| # | Action | System | Trigger | Confirmation |
|---|---|---|---|---|
| 1 | Set Author / Expert / Proofreader / Request participants | Jira BP | Assign, Review step 1, Review step 3 | click (manual) or automation flag |
| 2 | Transition Open→Text, Text→Review, Review→Proofreading, Proofreading→Ready, Ready→Published | Jira BP | Assign, Review, Publish | same |
| 3 | Add a comment (templates in 00 §1) | Jira BP | Review, Images | same |
| 4 | Create an Article issue + ADF fields | Jira BP | Intake | always a confirmation dialog |
| 5 | Create or update a card in the Articles database | Notion | Pipeline, Intake | confirmation, or the `auto_close` flag |
| 6 | Post a message | Slack | Publish, Report, Review nudges | per the §3 decision; always idempotent |

## 10. Phased plan (with Claude Code prompts)

Each phase ends with a deploy (`slop-ship`) and a check against its acceptance list.

**Phase 0: access and assessment (½ day)**

1. Confirm membership in the `Sloppers` group (`/slop-machine-skills:slop-access` if the tools are missing) and that `git` is installed.
2. Put this folder in a working directory: `bp-ops/docs/specs/` (and `legacy-artifacts/` → `bp-ops/legacy/`).
3. Prompt:
   > Use the slop-migrate-app skill. The "existing app" is the set of HTML artifacts in `./legacy/`, and the target design is in `./docs/specs/05-bp-ops-slop-machine-migration.md` (read `00-shared-reference.md` first). Run the assessment only: map every external dependency to a platform answer, list blockers, draft `slop.yaml` (name `bp-ops`, tier S, needs db + llm + atlassian, no custom secrets in the first deploy), and prepare the legal-gate answers from §4 for me to confirm. Test whether the platform's read-only Jira account can see project BP. Don't create a repo yet.
4. Platform admin: ask for (i) BP browse access for the read-only account if it returned 404; (ii) their supported path for Jira writes (§9); (iii) approval for the custom egress hosts (api.notion.com, api.ahrefs.com, Google APIs). Record the answers in `docs/decisions.md`.

**Phase 1: skeleton, roster, Jira mirror, Pipeline, Flow (2–3 days)**

> Using the slop-create-app steps, create the `bp-ops` repo from the template and build Phase 1 from `docs/specs/05…md` §5–§6 and §8.1, §8.8, plus spec 04 in full. Seed `people`, `aliases` and `rates` from `00-shared-reference.md` §2. Jira read-only. Unit-test `core/rules.py` against the examples in 00 §6. Deploy, then verify `/selftest`, the Jira sync counts against live Jira, and the Flow acceptance criteria.

**Phase 2: Load, Review (read-only), Report (2 days)**

> Implement §8.3 (read-only: queues, flags, nudge drafts through outbound.py with idempotency; no sending), §8.4 and §8.7. Port the logic from `legacy/bp-review-flow.html` and `legacy/byline-board-*.html`; follow §4 (no per-person speed metrics). Write tests proving the same nudge can't be created twice on the same day.

**Phase 3: data import, Spend, Publish (2 days)**

> Run Step A of §7 first (in Cowork) and put the exports in `./import/`. Then use the slop-migrate-data skill to import them per the §7 mapping table and build `/admin/import-report`. Implement §8.6 Spend with month history, and §8.5 Publish in copy/deep-link mode.

**Phase 4: secrets plus the new modules (spread over weeks)**

> Add the `NOTION_TOKEN` secret (portal, then the prompt it gives) and enable Pipeline Notion writes behind its flag. Add `AHREFS_API_KEY` and the GSC credentials, then implement spec 01. Then spec 03 (Images), then spec 02 (Intake).

**Phase 5: writes and automation (after the platform admin's answer)**

> Implement the Jira write client in `core/jira.py` using the approved path from `docs/decisions.md`. Route every write through `outbound.py`/`actions` with confirmation. Enable Assign, Review steps, and Publish transitions behind `jira_writes_enabled`. Then port the scheduled Review automation as job `review_automation`, off by default. Run it for 3 days with `dry_run = true`: log the intended actions and compare them with what the Cowork task would have done.

**Phase 6: cutover**

- [ ] Burn-in: 5 working days of daily use where every screen's counts match the old artifacts (or the differences are explained).
- [ ] Disable the Cowork scheduled task **"BP Review Flow automation"** (`trig_013mqoB1FWCjhUuqNra6VXuC`) **before** enabling `review_automation` in the app. Two automations on one Jira project is the duplicate-action trap.
- [ ] Unpin and archive the artifacts (Byline Board, Blog Spend Dashboard). Keep them for 30 days, then delete them only if Vladyslav asks.
- [ ] Update the daily-report link for Volodymyr to `bp-ops/performance`.
- [ ] Share with `slop-share`: named people per §4.
- [ ] Set the retention job live.

## 11. Acceptance criteria (whole app)

- [ ] One login, one URL; each route enforces its role (finance sees `/spend`; a viewer doesn't).
- [ ] The roster is defined once; changing a rate with a future `effective_from` doesn't change past months.
- [ ] The status strip shows every job. Killing the Ahrefs secret turns its chip red and nothing else breaks.
- [ ] Creating the same nudge twice (two tabs, a double click, the job plus a manual action) results in exactly one `outbound_messages` row.
- [ ] October spend computed from Jira is within 5% of the hand-made October budget. Every difference is explained by a manual line.
- [ ] Review queue sections list the same tickets as `legacy/bp-review-flow.html` on the same day.
- [ ] No screen shows per-person speed, rankings, or "performance".
- [ ] `/selftest` passes. Ruff, tests and the security scan are clean. A cold start takes under 60 s.

## 12. Risks

| Risk | Mitigation |
|---|---|
| No approved Jira write path | The app is still valuable read-only (Flow, Load, Performance, Spend, Report). Writes stay in the Cowork artifacts |
| Writers dislike bot messages | Keep DMs personal (draft plus deep link) and use the bot only in internal channels |
| Ahrefs unit burn | Server-side jobs only, with a unit guard and monthly usage on the status strip |
| The app sleeps (30 idle days) | Daily use prevents it. If it ever sleeps, waking takes 2–4 min and no data is lost |
| Rule drift between the app and the Claude skills | `docs/rules/` is the single copy. Cite the skills in code comments. Review quarterly |
