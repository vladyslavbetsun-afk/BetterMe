# BP Ops

One internal app for the BetterMe blog pipeline (BP), replacing the separate Claude artifacts: one database, one
roster, scheduled jobs and one URL. Build spec: `docs/specs/05-bp-ops-slop-machine-migration.md` (read
`docs/specs/00-shared-reference.md` first). Open questions and judgement calls: `docs/decisions.md`.

## What's in this build (Phases 1–3, Jira read-only)

| Route | Module | Replaces |
|---|---|---|
| `/flow` | Publishing capacity & flow (spec 04): WIP, throughput, clearance date, what-if, cumulative flow, lead times, publishing QA | new |
| `/pipeline` | Notion Articles ↔ Jira, status mismatches, missing cards | Blog Pipeline Editor + Board |
| `/assign` | Open queue, writer picker (niche, load), price estimate, month-to-date | Assignment Desk |
| `/review` | Review Flow steps 1–4, Straight to Ready, follow-ups, idempotent nudge drafts, server-side automation (off, dry run) | BP Review Flow (DhWg) + its Cowork task |
| `/load` | Who has which tickets, ticket-level ages and flags, no rankings | Byline Boards + Editorial Load |
| `/publish` | Ready queue by image status, batches of 4, batch message, → Published | BP Publishing Batches |
| `/spend` | Monthly spend computed from Jira + fixed + manual lines, close month, budget message, XLSX | Blog Spend Dashboard |
| `/report` | Daily report for Volodymyr | new |
| `/admin` | Roster and effective-dated rates, settings flags, jobs (run now), action log, import report | new |
| `/performance`, `/intake`, `/images` | Phase 4 placeholders (Performance shows the imported October data) | specs 01–03 |

Every message, Jira comment, transition and field edit goes through `src/core/outbound.py`. Messages carry a
UNIQUE idempotency key, so the same nudge can't be created twice (the 2026-10-15 duplicate-DM bug). All write
flags start off: until the platform approves a Jira write path, each step shows exactly what to do in Jira.

## Run it locally

```bash
pip install -r requirements-dev.txt
createdb bpops && createdb bpops_test            # any Postgres 14+
export DATABASE_URL=postgresql://localhost/bpops
export DEV_USER_EMAIL=you@betterme.world OWNER_EMAILS=you@betterme.world   # local only: stands in for the login header
uvicorn app:app --app-dir src --reload
```

Without Jira credentials the pages are empty and the status strip shows "Jira sync · not configured". To mirror
Jira locally, set `JIRA_EMAIL` + `JIRA_API_TOKEN` (or what the platform provides, see `src/core/jira.py`) and use
Admin → Jobs → "Jira full sync" → Run now.

Checks (what a contributor runs before pushing):

```bash
ruff check src tests scripts
TEST_DATABASE_URL=postgresql://localhost/bpops_test pytest -q   # wiped on every run; must end in _test
bandit -q -r src -ll
```

## Import the artifact data (Phase 3)

1. In Cowork, run the export prompt from spec 05 §7 Step A and put the files in `import/`.
2. `python scripts/import_exports.py import/ --october legacy/october-updates-tracker/october-updates-weekly.json`
3. Check `/admin/import-report` for unmatched rows.

## Layout

```
src/app.py            routes, /ping /startup /selftest, shared action + message endpoints
src/config.py         Jira fields, transitions, statuses, accountIds (00 §1–4)
src/core/             rules, business_days, people, jira, sync, outbound, scheduler, notion, slack
src/modules/<name>/   service.py (logic) + routes.py per module
src/db/               migrations/*.sql and seed/*.sql, run at every boot (idempotent)
src/jobs.py           every background job (status strip + Admin → Jobs)
tests/                rules, sync, review steps, idempotency, flow, spend, import, routes
legacy/               the old artifacts, reference only
```
