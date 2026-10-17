# BP Ops: build specs for Claude Code

Specs for moving the BetterMe blog pipeline (BP) from separate Claude artifacts into one internal app on the slop machine, plus four new dashboards. Prepared 2026-10-17 from the live artifacts, Jira conventions, the Cowork scheduled task and the BetterMe Claude skills.

## Files

| File | What it is | Build order |
|---|---|---|
| `00-shared-reference.md` | Constants (Jira fields, transitions, JQL), canonical roster and rates, Slack and Notion IDs, business rules, **known issues** | read first, always |
| `05-bp-ops-slop-machine-migration.md` | The app itself: platform constraints, Legal-gate answers, architecture, schema, data import, migrated modules, phased plan with copy-paste prompts | **start here** (Phases 0–3) |
| `04-publishing-capacity-view.md` | Flow and bottleneck view (Jira read-only, cheapest to build) | with Phase 1 |
| `01-live-performance-dashboard.md` | GSC + Ahrefs + AI-citation dashboard; replaces the static reports and the stalled trackers | Phase 4 |
| `03-image-queue.md` | Design requests and delivery tracking; feeds Publish | Phase 4 |
| `02-topic-intake-board.md` | Keyword → screen → approve → Jira + Notion ticket | Phase 4 |
| `legacy-artifacts/` | Source HTML of the current artifacts, the October tracker data, and the scheduled-task prompt, kept **for reference only** | — |

## How to use it with Claude Code

1. Create a folder `bp-ops/`. Copy these specs into `bp-ops/docs/specs/` and `legacy-artifacts/` into `bp-ops/legacy/`.
2. Add a short `CLAUDE.md` at the repo root:
   ```
   Specs live in docs/specs/. Always read 00-shared-reference.md before coding.
   Legacy artifacts in legacy/ are reference implementations — port logic, not UI.
   Never message, comment, or transition anything without going through core/outbound.py.
   No per-person speed/ranking/performance metrics (Legal gate, spec 05 §4).
   ```
3. Start with the Phase 0 prompt in spec 05 §10.

## Fix these now (before any build)

These were found while preparing the specs. Each one affects work that is running today:

1. **The BP Review Flow automation is off.** Its scheduled task runs every hour, but the dashboard's `automation` setting is `false`, so each run does nothing. Turn it on in the dashboard if you expect it to work.
2. **Writers received duplicate nudges** (Eve and Jeremy, Oct 15, twice within a second). Until the app replaces it, keep BP Review Flow open in only one tab.
3. **Slipped Pages Tracker** (checks stopped Oct 13) and **October Updates Tracker** (baseline only) have no scheduled refresh behind them.
