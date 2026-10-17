# 01 — Live Performance Dashboard

> **Build target:** a module of the BP Ops app (`/performance`, see spec 05). It can also ship first as a standalone slop app with the same schema and be merged later.
> **Read first:** `00-shared-reference.md` §1, §5, §8.
> **Replaces:** "Two-Month Results: Traffic and AI Visibility Since Aug 20", "Article Progression Report", "October Updates Tracker", and the data half of "Slipped Pages Tracker". Each of these is a hand-built snapshot or has stalled.

## 1. Goal

One link that always answers **"is the content we publish and update working?"** The figures must be current, with no hand-assembled reports. Vladyslav uses it daily. Volodymyr and management open it weekly, and it replaces the report links in the daily DM.

Questions it must answer in under 10 seconds:

1. How much organic traffic and AI visibility does `/articles/` have now, compared with 4 weeks ago and with the Aug 20 baseline?
2. Did the articles we **published** and **updated** improve, compared with their own "before"?
3. Which updated pages are gaining and which are still slipping? What should go into the next update batch?
4. How often do AI assistants (Google AIO, AI Mode, ChatGPT, Perplexity, Gemini, Copilot) cite us, compared with competitors?

## 2. Users and access

| User | Needs | Access |
|---|---|---|
| Vladyslav (owner) | everything, triage actions | owner |
| Volodymyr (SEO/GEO lead) | overview, cohorts, AI visibility | named-people |
| Management (ad hoc) | the Overview tab, read-only | named-people. Add emails as needed |

## 3. Data sources and jobs

All pulls are **server-side scheduled jobs** that write to the database. The UI reads only from the database and never calls Ahrefs or GSC per page view, which protects API units.

| Job | Schedule (Europe/Brussels) | Source | Writes |
|---|---|---|---|
| `sync_cohorts` | daily 06:00 | Jira (`status CHANGED TO "Published"`), the comment holding the live link, Notion `New/Upd` | `articles`, `article_events` |
| `pull_gsc_pages` | daily 06:30 | GSC Search Analytics API (`dimensions=[page,date]`, `/articles/` filter, last 5 days re-pulled because GSC lags 2–3 days) | `gsc_page_daily` |
| `pull_gsc_queries` | weekly Mon 07:00 | GSC (`dimensions=[page,query]`, last 28 days, top 50 queries per tracked page) | `gsc_page_query_28d` |
| `pull_ahrefs_pages` | weekly Mon 07:30 | Ahrefs `batch-analysis` on exact URLs (traffic, keywords, top3, top4_10) | `ahrefs_page_weekly` |
| `pull_ai_citations` | weekly Mon 08:00 | Ahrefs `site-explorer-ai-responses-count`: `mode=exact` per tracked URL, `mode=prefix` for `/articles/`, `mode=subdomains` for betterme.world and each peer | `ai_citations_weekly` |
| `pull_aio_gap` | monthly, 1st, 08:30 | Ahrefs organic keywords with the AIO-gap filter (00 §5) | `aio_gap_monthly` (count + top 200 rows) |
| `check_live_pages` | daily 07:00, only for pages in an active window | fetch the live URL and parse "Updated on", H1, Key Takeaways present, word count | `page_snapshots` |
| `position_checks` | daily 08:00 | for pages whose `updated_on` changed 14 or 28 days ago: Ahrefs keywords-history for the page's main keyword | `position_checks` |

**Resilience rules**

- Every job writes a row to `job_runs(job, started_at, finished_at, status, rows, error)`. The UI shows a **data health strip** (see §6.1). A failure must be visible, never silent. This is the exact problem that left the two trackers stale.
- Jobs are idempotent: upsert on natural keys such as `(url, date)` or `(url, week)`.
- Ahrefs unit guard: before each run, estimate units (number of rows × cost per endpoint). If it exceeds `settings.ahrefs_max_units_per_run` (default 20,000), skip the run and log `status = skipped_budget`. Show the units used on the health strip.
- GSC data for the most recent 2–3 days is provisional. Flag it in charts with a hatched or lighter final segment.

**Credentials (stored as app secrets, never in code)**

- `AHREFS_API_KEY`: egress to `api.ahrefs.com`
- GSC: `GOOGLE_SERVICE_ACCOUNT_JSON` (the service account email must be added as a user on the Search Console property), with egress to `searchconsole.googleapis.com` and `oauth2.googleapis.com`. **Alternative:** if the GSC property is connected in Ahrefs, use the Ahrefs `gsc-*` endpoints and skip Google credentials entirely. Decide which in Phase 0 and record the decision in `docs/decisions.md`.

## 4. Cohort definitions (the core logic; get this exactly right)

An **article** is a `/articles/<slug>/` URL. It joins the tracked set by any of these routes:

| Cohort | Rule |
|---|---|
| `new` | A Jira BP ticket WITHOUT `update` in its summary reached Published. `go_live_date` = the date Yuliia's betterme.world link was posted (fallback: the date of the transition to Published) |
| `update` | A Jira BP ticket WITH `update` in its summary reached Published. `go_live_date` = the same rule |
| `refresh_detected` | The live "Updated on" date changed without a matching Jira ticket. This is the old **group C**, the bulk re-save of 2026-09-08. Report it separately and keep it out of the update cohort |
| `slipped` | Imported from Slipped Pages Tracker: top-3 on 2026-08-12, positions 4–10 on 2026-10-08. Keep the `level` (L0–L3, NOSEO) |
| `manual` | Added by hand (paste URL) |

**Publishing QA flag (old group D):** the Jira status is Published, but the live page's H1 and "Updated on" haven't changed within 3 days of `go_live_date`. Show it as a red badge "Published in Jira, page unchanged". Spec 04 shows the same list.

**Before/after windows** (keep identical to the Article Progression method so numbers stay comparable):

- GSC: `pre` = the 28 days before `go_live_date`, `post` = the 28 days after; the go-live day is excluded from both. Until 28 post days exist, show `post` as "n days so far", normalized per day, with an "early" badge.
- Ahrefs: `pre` = the average of the 4 weekly snapshots before go-live, `post` = the average of the latest 4.
- AI citations: the value at the week of go-live compared with the latest week.

**Baseline:** a global baseline date setting (default `2026-08-20`) powers the "since baseline" comparisons on the Overview.

## 5. Data model (Postgres)

```sql
articles(
  url text primary key, slug text, title text, category text,
  cohort text check (cohort in ('new','update','refresh_detected','slipped','manual')),
  jira_key text, go_live_date date, slipped_level text,
  main_keyword text, main_keyword_volume int,
  active bool default true, created_at timestamptz, updated_at timestamptz)

article_events(id bigserial, url text, kind text, at timestamptz, payload jsonb)
  -- kinds: published, updated_on_changed, qa_flag, level_changed, note

gsc_page_daily(url text, date date, clicks int, impressions int, ctr real, position real,
  primary key(url,date))
gsc_page_query_28d(url text, query text, window_end date, clicks int, impressions int, position real,
  primary key(url,query,window_end))
ahrefs_page_weekly(url text, week date, traffic int, keywords int, top3 int, top4_10 int,
  primary key(url,week))
ai_citations_weekly(target text, mode text, week date,
  ai_all int, aio int, ai_mode int, chatgpt int, perplexity int, gemini int, copilot int,
  primary key(target,mode,week))
aio_gap_monthly(month date, total int, top_rows jsonb, primary key(month))
page_snapshots(url text, checked_at timestamptz, updated_on date, h1 text,
  has_key_takeaways bool, word_count int, http_status int)
position_checks(url text, label text, check_date date, keyword text, position real,
  in_aio bool, traffic int, primary key(url,label))
job_runs(id bigserial, job text, started_at timestamptz, finished_at timestamptz,
  status text, rows int, units_used int, error text)
settings(key text primary key, value jsonb)
```

**Backfill on first deploy**

1. Import `legacy-artifacts/october-updates-tracker/october-updates-weekly.json` (74 rows, week 2026-10-13) into `ahrefs_page_weekly` and `ai_citations_weekly` (mode `exact`), and set those pages' cohort to `update`.
2. Import Slipped Pages Tracker's `pages` and `progress` collections (exported from the artifact database; see spec 05 §7) into `articles` (cohort `slipped`) and `article_events`.
3. Run `sync_cohorts` over Jira from `2026-07-01` onward.
4. GSC backfill: 16 months is possible, but pull from `2026-06-01` onward to keep the run fast.
5. Ahrefs backfill: use `keywords-history` / `metrics-history` to fill weekly points from `2026-08-01`. Check the units estimate first.

## 6. UI

Follow the `dataviz` skill rules: one accent color per series family, accessible in light and dark, no 3D, no pie charts for more than 3 parts. Use one chart library (Chart.js or Recharts via CDN is fine; pin the version).

### 6.1 Global chrome

- Top bar: date-range picker (presets: 28d, 90d, since baseline, custom); cohort filter (all / new / update / slipped); category filter.
- **Data health strip** (always visible): one chip per job showing its last success time. It turns amber after 1.5× the expected interval and red after a failure. Also shows Ahrefs units used this month and the GSC freshness date.

### 6.2 Tab: Overview

- KPI row (each tile shows the value, the change vs the previous equal period, and a sparkline):
  - `/articles/` organic clicks (GSC)
  - impressions (GSC)
  - Ahrefs organic traffic (`/articles/` prefix)
  - AI citations, all platforms (`/articles/` prefix)
  - articles published this month (new / update split)
  - updated pages "improving" (post > pre by more than 10%) as a share
- Line chart: weekly clicks for the whole of `/articles/`, with vertical markers on go-live dates (hover lists the articles).
- Stacked bar chart: AI citations by platform per week.
- "Since baseline" panel: three short sentences generated from the numbers, e.g. "Updated pages: +18% clicks vs their own pre-period (34 pages, median +9%)." Template the sentences from the data. If an LLM phrases them, it must not invent numbers: pass the computed values in and validate that every number in the output appears in the input.

### 6.3 Tab: Cohorts

- One card per cohort with: number of articles, median and mean change in clicks (pre → post), share improving / flat / declining, and the top 5 gainers and top 5 losers.
- A grouped bar per go-live month: average clicks per article in the post window, new vs update.
- A table export to CSV and a copy-to-clipboard summary for Slack.

### 6.4 Tab: Articles (the workhorse table)

Columns: title (link to the live page) · Jira key (link) · cohort · level · go-live · clicks pre/post/Δ% · impressions Δ% · avg position pre → post · Ahrefs traffic (sparkline, 8 weeks) · top3 / top4–10 · AI citations Δ · "Updated on" (live) · flags (QA, early, stale data).

- Sort by any column. Search box. Filters: cohort, level, category, flag, "declining only".
- Row click opens the **article drawer**:
  - daily clicks/impressions chart with the go-live marker
  - a table of top queries with position change
  - AI citations by platform
  - position checks at +2w and +4w
  - live-page snapshot history (dates the H1 or "Updated on" changed)
  - notes (free text, saved to `article_events`)
- Bulk action: **"Send to update queue"**. In v1 this only marks rows; with Notion write access it creates Notion cards using the `blog-notion-ticket-creation` rules, after a confirmation dialog listing exactly what will be created.

### 6.5 Tab: AI visibility

- Peer comparison: BetterMe vs the 12 peers (00 §5), latest month, a horizontal bar per platform. Toggle for the 5-peer set.
- Trend: BetterMe share of citations among the peer set over time.
- AIO gap: the monthly count plus the top 200 keywords (keyword, volume, our position, ranking URL) as a table with CSV export. This is the "monthly scorecard" the Sep 4 Citation Audit recommended.
- If Ahrefs Brand Radar is unavailable ("Missing addon"), hide the brand-mention panels and show a one-line note. Never show zeros that look like real data.

### 6.6 Tab: Slipped pages (absorbs the Slipped Pages Tracker)

- Keep the same columns, levels and editable status/notes as the old tracker (`legacy-artifacts/slipped-pages-tracker.html`).
- Position checks fill in automatically from the `position_checks` job.
- "Refresh now" actually enqueues the job and shows its result. The old button only recorded a request.

## 7. Non-functional

- Page load under 2 seconds on 500 tracked articles. Precompute the pre/post aggregates into a materialized view (`article_perf_summary`) refreshed after each job.
- Times shown in Europe/Brussels. Weeks start on Monday.
- No personal data beyond article ownership (Jira key). No per-writer performance ranking in this module (see spec 05 §4, Legal gate).
- LLM use: only for the optional overview sentences. Model `claude-haiku`, budget share ≤ $3/month.

## 8. Acceptance criteria

- [ ] All 74 October update pages and every Jira-published article since 2026-07-01 appear with the right cohort and go-live date (spot-check 10 against Jira by hand).
- [ ] Pre/post numbers for 5 sample pages match a manual GSC UI check within ±2%.
- [ ] Group D pages show the QA flag. Group C pages are cohort `refresh_detected`, not `update`.
- [ ] Disabling the Ahrefs key turns its health chip red within one scheduled cycle. The UI keeps working with the last data.
- [ ] Re-running any job twice doesn't duplicate rows.
- [ ] Volodymyr can open the Overview with his BetterMe login. Anyone not on the list can't.

## 9. Open questions (ask Vladyslav, record the answers in `docs/decisions.md`)

1. Pull GSC directly (service account) or through Ahrefs?
2. Is Brand Radar now enabled on the Ahrefs plan?
3. Does `12k` / `15k` in a ticket summary mean search volume? If so, store it as `articles.main_keyword_volume`.
4. Should management see the Articles tab, or only the Overview?
