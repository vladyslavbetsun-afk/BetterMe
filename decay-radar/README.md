# Content Decay Radar

Every week, find `/articles/` pages that lost top-3 Google positions (US), confirm the drop is real, audit each page, assign a level (L0 Hold / L1 Targeted fix / L2 Standard refresh / L3 Full rewrite / NOSEO) with a written why and checklist, prioritize, and propose Notion cards. Then follow up at +2 and +4 weeks after the page is updated.

- Spec: [`docs/specs/06-content-decay-radar.md`](docs/specs/06-content-decay-radar.md)
- Decisions, departures from the spec, and open questions: [`docs/decisions.md`](docs/decisions.md). Read D-02 and D-03 first: the live Ahrefs schema differs from the spec in three places.

There is also a claude.ai artifact version that runs the same rules through your Ahrefs, Atlassian and Notion connectors: [`artifact/`](artifact/README.md), live at https://claude.ai/artifact/DyW4ZB7fwZFzVzoUuWyryS.

This is **Option A** (local CLI and SQLite). Option B (the BP Ops `/decay` module with Postgres) reuses the same package; only `config.py` and `storage.py` change.

## Setup

```bash
cd decay-radar
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in AHREFS_API_KEY; NOTION_TOKEN and JIRA_* are optional
python -m pytest -q       # 69 offline tests
```

`.env` and `decay.db` are git-ignored. Never commit them.

## Weekly use

```bash
python -m decay run --open                 # Monday: detect → audit → level → priority → decay-report.html
python -m decay review                     # terminal table of the latest run
python -m decay review --url <url>         # one page: why, checklist, lost keywords, audit, Jira/Notion
python -m decay create-cards               # DRY RUN: prints every card exactly as it would be written
python -m decay create-cards --apply       # asks "yes", writes, re-fetches and verifies each card
python -m decay followup                   # daily: +14/+28 day checks for updated pages
python -m decay report --slack             # the weekly Slack line
```

Row actions (the HTML report shows these commands for each row):

```bash
python -m decay override <url> L2 --reason "covers two intents"   # reason required
python -m decay exclude  <url> --reason "merging into X"           # never suggested again until `include`
python -m decay include  <url>
```

One-time imports and settings:

```bash
python -m decay import-suggested import/already-suggested.md    # the "Already Suggested (tracking)" doc
python -m decay settings show
python -m decay settings set weekly_card_cap 12
python -m decay settings set countries '["us","gb"]'
```

## Calibration (§7)

Put the old tracker export at `import/slipped__pages.json` (plus `import/slipped__progress.json` if you have it), then:

```bash
python -m decay run --date 2026-10-08 --compare 2026-08-12 --no-cards \
  --labels import/slipped__pages.json --progress import/slipped__progress.json
```

This prints the URL overlap (target ≥ 90%), the level confusion matrix (target ≥ 80% agreement), and every disagreement with both reasons. Tune thresholds only, never the rules, and record each change in `docs/decisions.md`.

## What each run does

| Step | Module | Notes |
|---|---|---|
| Unit guard | `ahrefs.py` | Aborts before any call when the estimate is above `max_units_per_run`; the abort appears in the report and the Slack line |
| Detect | `ahrefs.py`, `detect.py` | One `organic-keywords` compare call plus a filter-only AI Overview call per country; §4 noise filters |
| Roll up | `aggregate.py` | URL normalization, per-page lost keywords, main keyword, worst position, AIO, cannibalization |
| Confirm | `pipeline.py` | WATCH until a second weekly run, unless the loss is severe (a keyword lost entirely, or ≥ 200 visits/mo) |
| Audit | `audit.py` | One fetch per page at 1 req/sec with UA `BP-Ops-DecayRadar/1.0`; competitor median length (Option A only) |
| Screen | `screen.py` | 22 rejection categories (Pass A regex; optional Haiku Pass B) |
| Check | `jira.py`, `notion.py` | Exact-URL match on BP tickets; open card in Articles |
| Level | `level.py` | §7 decision table, first match wins, every rule writes a why and a checklist |
| Priority | `priority.py` | traffic lost × install × core topic × confidence × effort; top `weekly_card_cap` become "proposed" |
| Report | `report.py` | `decay-report.html`, `.csv`, Slack text |

## Scheduling (Option A)

Run `python -m decay run` by hand on Mondays, or create a Cowork scheduled task on your computer that runs `python -m decay run` (Mon 07:15 Europe/Brussels) and `python -m decay followup` (daily 08:15).

## Option B notes

- Set `DATABASE_URL` to use Postgres (`pip install "psycopg[binary]"`).
- Set `DECAY_MODE=bpops`, which forces `competitor_check` off because of egress (spec §2).
- Egress needs `custom: api.ahrefs.com`, `custom: betterme.world` (+ `www.betterme.world`) and `custom: api.notion.com`. Add the Jira host too if the Jira check is wanted.
