# 04 — Publishing Capacity & Flow View

> **Build target:** a module of the BP Ops app (`/flow`, see spec 05). This is the cheapest module to build: **Jira read-only**, no third-party APIs. A good first module after the roster.
> **Read first:** `00-shared-reference.md` §1, §6.5, §8 (item 7).
> **Problem:** on 2026-10-09 Vladyslav reported that publishing capacity is about 5 articles per day and that "I have more prepared." Nothing currently shows the size of the Ready backlog, how fast it grows, or how long work waits at each stage. That evidence is needed to argue for more publishing capacity or a different process.

## 1. Goal

Show the whole pipeline as a **flow system** and make the bottleneck obvious:

1. How many articles sit in each stage now, and for how long?
2. Is the Ready backlog growing or shrinking?
3. When will the current Ready backlog be cleared at the current publishing rate? What if the rate were X?
4. Which tickets are marked Published in Jira while the live page hasn't changed (publishing QA)?

**Framing rule (Legal gate, spec 05 §4):** all metrics are about **tickets and stages**, never about named people. Don't label throughput with the publisher's (or anyone's) name, and don't build per-person rate charts. "Publishing stage outflow" is fine; "Yuliia's output" is not.

## 2. Data

Everything comes from Jira BP **changelogs**:

```text
project = BP AND (status != Published OR status CHANGED TO "Published" AFTER -180d)
expand=changelog, fields: summary, status, created, customfield_11710, customfield_11711, customfield_11709
```

From each changelog, extract `status_transitions(jira_key, from_status, to_status, at, by_account_id)`. Store `by_account_id`, but never surface it in this module's UI.

Derived per ticket:

- `entered_<stage>_at`: the last entry into each stage (Open, Text, Review, Proofreading, Ready, Published)
- `stage_durations(jira_key, stage, entered_at, exited_at, business_days)`: one row per visit to a stage (a ticket can bounce Review ↔ Text)
- `type`: `new` / `update` (from the summary)
- `has_images` from spec 03's API (fallback: the Oksana/Karina comment rule)
- `live_url`: Yuliia's betterme.world link comment (00 §6.5)

**Job:** `sync_flow` every 30 minutes, 08:00–19:00 on weekdays; a full rebuild nightly at 02:00. The first backfill covers 180 days.

## 3. Metrics (exact definitions)

| Metric | Definition |
|---|---|
| WIP by stage | count of tickets currently in each status |
| Inflow to Ready (day) | tickets whose transition **into** Ready happened that day (business-day calendar) |
| Outflow (day) | transitions into Published that day |
| Net flow (week) | Σ inflow − Σ outflow over Mon–Fri |
| Ready backlog age | for tickets now in Ready: business days since entering Ready. Show p50, p90 and the max |
| Throughput (rolling) | mean and median Published per business day over the last 10 and the last 20 business days |
| Clearance forecast | `backlog_now / throughput_10d` in business days, converted to a calendar date (skip weekends; holidays from `settings.holidays`) |
| What-if forecast | the same, with a user-chosen throughput (slider from 1 to 15 per day), plus optional extra inflow per day |
| Stage lead time | median and p90 business days per stage over the last 90 days (feeds spec 03's `needed_by`) |
| End-to-end lead time | Open→Published and Text→Published, median and p90, split new / update |
| Rework rate | the share of tickets that went Review → Text (or Proofreading → Review) at least once in the last 90 days |
| Publishing QA mismatches | Published in Jira more than 3 days ago, and the live page's "Updated on" and H1 unchanged since before `entered_published_at`. Uses spec 01's `page_snapshots` if available; otherwise this module fetches the page itself |

Business days follow Europe/Brussels, Mon–Fri, minus `settings.holidays`.

## 4. UI

### 4.1 Header KPIs

- **Ready backlog**: count, split "with images / without images"
- **Publishing throughput**: 10-day median per day, with a sparkline
- **Clearance date** at the current throughput
- **Net flow this week** (+ means the backlog grew)
- **QA mismatches** (red if > 0)

### 4.2 Charts

1. **Cumulative flow diagram** (stacked area): daily count per stage over the last 60 days. A widening Ready band is the visual argument.
2. **Inflow vs outflow** bars per business day for the last 30 days, with a 5-day moving-average line for each.
3. **Stage lead-time boxes**: horizontal bars of median and p90 per stage, highlighting the longest wait.
4. **Ready age histogram**: buckets 0–1, 2–3, 4–5, 6–10 and >10 business days.

### 4.3 What-if panel

Sliders for publishing throughput per day (default = the current median), extra inflow per day (default 0) and batch size (default 4). Live outputs:

- the clearance date
- the backlog in 2 and 4 weeks
- how many more business days the oldest Ready ticket will wait

Add one plain sentence such as: "At 5/day the backlog of 37 clears on Nov 6. At 8/day it clears on Oct 27."

### 4.4 Tables

- **Ready queue**: key, title, type, days in Ready, images ✓/✗, word count, the batch it's in (from Publishing Batches data once migrated).
- **QA mismatches**: key, title, Jira published date, live "Updated on", live H1 vs ticket title, plus a "Recheck" button.
- **Oldest WIP per stage**: the top 5 tickets per stage by age. Ticket-level only.

### 4.5 Export

**"Copy summary for Slack"** produces a 5-line text block (KPIs plus the what-if sentence) in the same style as the daily report. **"Download one-pager (PNG/PDF)"** gives the header plus the CFD and the what-if panel, for sending to Volodymyr.

## 5. Data model

```sql
status_transitions(jira_key text, at timestamptz, from_status text, to_status text, by_account_id text,
  primary key (jira_key, at, to_status))
tickets(jira_key text primary key, summary text, type text, status text, created_at timestamptz,
  entered_ready_at timestamptz, entered_published_at timestamptz, live_url text, word_min int, word_max int)
stage_durations(jira_key text, stage text, entered_at timestamptz, exited_at timestamptz, business_days real,
  primary key (jira_key, stage, entered_at))
flow_daily(date date, stage text, wip int, inflow int, outflow int, primary key(date, stage))   -- materialized
qa_checks(jira_key text primary key, checked_at timestamptz, live_updated_on date, live_h1 text, mismatch bool, note text)
```

`tickets` and `status_transitions` are shared with the rest of the app (spec 05). Spec 05 owns the Jira sync. This module adds the derived tables.

## 6. Acceptance criteria

- [ ] WIP counts per stage equal a live Jira count for the same JQL at the same minute.
- [ ] Throughput for a past week, checked by hand against Jira "status changed to Published during (...)", matches exactly.
- [ ] Bounced tickets (Review → Text → Review) show two Review visits in `stage_durations`.
- [ ] The what-if panel updates in under 100 ms (client-side calculation).
- [ ] No chart, table or export names a person.
- [ ] The QA list reproduces the 14 "group D" pages from the Two-Month Results report (allowing for any fixed since Oct 14).

## 7. Open questions

1. Are there holidays or non-working days to exclude (Ukrainian public holidays)?
2. Target throughput Volodymyr wants to see (for a goal line on the charts)?
3. Should the batch size of 4 stay, or be computed from the target throughput?
