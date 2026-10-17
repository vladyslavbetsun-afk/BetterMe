# 06 — Content Decay Radar

> **Build target:** a module of the BP Ops app (`/decay`, see spec 05) with a weekly job. The core is a plain Python package (`decay/`) with a CLI, so you can **run it locally from Claude Code first** (Option A) and mount the same code in BP Ops later (Option B).
> **Read first:** `00-shared-reference.md` §4 (Notion), §5 (Ahrefs), §6.6 (levels), §6.7 (editorial rules), §7 (skills). Port the rules from the user's skills `betterme-article-update-finder`, `blog-notion-ticket-creation` and `betterme-keyword-rejection-screen`.
> **Replaces:** the one-off Slipped Pages Tracker (a single Aug 12 → Oct 8 comparison whose checks stopped on Oct 13) and the manual "articles for update" hunts.

## 1. Goal

Every Monday, automatically:

1. Find `/articles/` pages that **lost top-3 Google positions** (US) for keywords that matter.
2. **Confirm** that the drop is real (it persists, and traffic is actually lost), not ranking noise.
3. **Audit** each page and assign a level: **L0 Hold / L1 Targeted fix / L2 Standard refresh / L3 Full rewrite / NOSEO**, with a written "why" and a "what to do" checklist.
4. **Prioritize** the pages by recoverable traffic and install potential.
5. **Create Notion cards** in the Articles database for the ones to work on, following the `blog-notion-ticket-creation` conventions, after a confirmation step.
6. **Follow up** at +2 and +4 weeks after a page is updated, marking it recovered or escalating its level.

## 2. Two ways to run it

| | Option A: local CLI (start here) | Option B: BP Ops module |
|---|---|---|
| Where | your machine, run by Claude Code or a Cowork scheduled task | slop machine, weekly in-process job |
| Storage | SQLite file `decay.db` (same schema as Postgres) | Postgres (BP Ops) |
| Ahrefs | `AHREFS_API_KEY` in a local `.env` (never committed) | portal secret + egress `custom: api.ahrefs.com` |
| Live page fetch | direct | egress `custom: betterme.world` (+ `www.betterme.world`) |
| Competitor length check | allowed (fetches the top-5 SERP pages) | **off**: the slop machine blocks undeclared outbound hosts, so this check is local-only |
| Notion | `NOTION_TOKEN` in `.env`, or skip and export CSV | portal secret + egress `custom: api.notion.com` |
| UI | an HTML report file plus a terminal table | `/decay` page (§9) |

Build the package so both modes share 100% of the logic. Only `storage.py` and `config.py` differ.

```
decay/
  __init__.py
  config.py        # thresholds (§4), dates, caps; env loading
  ahrefs.py        # organic-keywords compare, serp-overview, keywords-history; unit guard
  detect.py        # §3 query + noise filters → decay_keywords
  aggregate.py     # keyword → page rollup (§5)
  audit.py         # live page parse (§6), optional competitor length
  screen.py        # rejection-pattern screen of the page topic (NOSEO)
  level.py         # §7 decision table → level + why + checklist
  priority.py      # §8 score
  notion.py        # §10 card creation, dedupe
  jira.py          # read-only: existing update ticket check
  followup.py      # §11 +2w/+4w checks
  storage.py       # SQLite | Postgres
  report.py        # HTML/CSV/Slack-text outputs
  cli.py           # `python -m decay run|review|create-cards|followup|report`
tests/
```

## 3. Detection (the Ahrefs query)

One call per run (paginate if needed) to **`site-explorer-organic-keywords`**:

| Param | Value |
|---|---|
| `target` | `betterme.world/articles/` |
| `mode` | `prefix` |
| `country` | `us` (configurable list; run once per country) |
| `date` | the latest complete day (today − 1) |
| `date_compared` | `date − compare_days` (default **28**). Also supports a fixed baseline date, e.g. `2026-08-12`, to reproduce the old tracker |
| `select` | `keyword,volume,keyword_difficulty,best_position,best_position_prev,best_position_diff,best_position_url,best_position_url_prev,sum_traffic,sum_traffic_prev,serp_features,serp_features_prev,positions_kinds,positions_kinds_prev,status,is_informational,is_commercial,is_transactional` |
| `where` | see below |
| `order_by` | `sum_traffic_prev:desc` |
| `limit` | `settings.max_rows` (default 1000) |

```json
{"and":[
  {"field":"is_best_position_set_top_3_prev","is":["eq",true]},
  {"field":"is_main_position_prev","is":["eq",true]},
  {"or":[
    {"field":"best_position","is":["gt",3]},
    {"field":"best_position","is":"is_null"}
  ]},
  {"field":"volume","is":["gte",20]}
]}
```

Notes:

- `best_position` is null (or `status = "right"`) when the keyword was **lost entirely**. Treat this as the most severe drop.
- The volume floor in the API filter is the lowest one (20, for the scarce core topics). The stricter floor of 50+ for everything else is applied in code (§4) after topic detection.
- **Unit guard:** volume, traffic and KD each cost units per row. Before calling, estimate `limit × cost_per_row` and abort if it exceeds `settings.max_units_per_run` (default 25,000). Log the units actually used from the response headers or the `subscription-info-limits-and-usage` endpoint.
- Use `doc` / the OpenAPI reference for `site-explorer-organic-keywords` to confirm field names before coding. The fields above were checked against the Ahrefs v3 schema on 2026-10-17.

## 4. Noise filters and confirmation (keyword level)

A keyword row becomes a **decay signal** only if all of these hold (all thresholds live in `config.py` / `settings`):

| Filter | Default |
|---|---|
| Volume | ≥ 50, or ≥ 20 if the page is in a scarce core topic (Wall Pilates, Chair Yoga, Calisthenics, Meal Plans, Fasting), detected from the slug or keyword |
| Traffic lost on the keyword | `sum_traffic_prev − sum_traffic ≥ 5` visits/month, **or** the keyword was lost entirely |
| Not a 3 → 4 wobble | ignore `best_position_prev = 3 AND best_position = 4` unless traffic lost ≥ 20 |
| Not branded/navigational | drop rows where `is_navigational` |
| Same-site URL swap | if `best_position_url != best_position_url_prev` and both are betterme.world URLs → flag **cannibalization** (a separate signal; see §7) rather than decay of the old URL |

**Confirmation (persistence):** a page becomes **CONFIRMED** only when its signals appear in **2 consecutive weekly runs**, or when the loss is severe on the first run (any keyword lost entirely, or page traffic lost ≥ 200/month). Until then it's **WATCH** and gets no Notion card. This keeps Ahrefs rank volatility from creating busywork.

**Optional GSC cross-check** (when spec 01 data exists): the page's GSC clicks over the last 28 days vs the previous 28 days. A drop of ≥ 15% raises confidence; flat or up clicks lowers the priority (§8) and adds the note "Ahrefs shows a drop, GSC clicks stable".

## 5. Page rollup

Group the signals by `best_position_url_prev` (the page that held the top 3). Normalize URLs: lowercase host, strip query strings and fragments, force a trailing slash, and keep only `^https://(www\.)?betterme\.world/articles/[^/]+/$`.

Per page compute:

- `lost_keywords`: list of `{kw, vol, was, now, traffic_prev, traffic_now, kind: dropped|lost|swapped}`
- `lost_top3_count`, `lost_entirely_count`
- `traffic_lost` = Σ(traffic_prev − traffic_now) over its signals
- `main_keyword` = the lost keyword with the highest `volume` (tiebreak: highest traffic_prev)
- `worst_now` = the worst current position among the top-3 losses (null = lost)
- `aio_appeared` = `ai_overview` is in `serp_features` but was not in `serp_features_prev` for any lost keyword
- `aio_citation_lost` = `ai_overview_found` (or `ai_overview`) was in `positions_kinds_prev` but not in `positions_kinds`
- `swapped_to` = a betterme.world URL that now ranks instead (cannibalization)
- `intent_mix` = the share of lost keywords that are commercial or transactional (feeds the install score)

## 6. Page audit (live fetch)

Fetch the page once per run (honour a 1 req/sec rate limit; send a descriptive User-Agent `BP-Ops-DecayRadar/1.0`). Parse:

| Field | How |
|---|---|
| `http_status`, `final_url` | follow redirects. A redirect to another article = "merged", which goes to NOSEO with a "check redirect" note |
| `updated_on` | the "Updated on <date>" byline (fall back to `article:modified_time` / JSON-LD `dateModified`) |
| `title`, `h1`, `meta_description` | standard tags |
| `word_count` | the main content (`<article>` or the largest text block), excluding nav, footer and related posts |
| `has_key_takeaways` | a heading or block matching `/key takeaways/i` |
| `faq_count` | the number of Q&A pairs in an FAQ section or JSON-LD `FAQPage` |
| `question_h2_count`, `question_h2_with_direct_answer` | H2s ending in "?" whose first following paragraph is 40–60 words |
| `table_count`, `image_count`, `images_missing_alt` | |
| `internal_links_out` | links to `/articles/` |
| `claim_flags` | regex hits for spot-reduction, timeline and outcome claims (`/in \d+ days/`, `/lose \d+ (lbs|pounds|kg)/`, `/burn (belly|arm|thigh) fat/`, `/slim (your )?(thighs|arms|waist)/`, `/guaranteed/`, `/\bbest\b/` in the title or H1) |
| `age_days` | today − `updated_on` |

**Competitor length (Option A only):** `serp-overview` for `main_keyword` (top 5 organic), then fetch each page and compute `median_competitor_words`. Skip silently in Option B and record `competitor_check = "skipped (egress)"`.

**Jira check (read-only):** look for an existing update ticket for this URL:
`project = BP AND text ~ "<slug>" ORDER BY created DESC`. Then **confirm the exact URL** appears in the description (`Article:` / `Original article:` line). Loose matches are a known false-positive trap (from `betterme-article-update-finder`). Record `open_ticket` (status ≠ Published) or `recent_ticket` (Published within 60 days).

**Notion check:** query the Articles data source for `"URL 1" = url` (normalized). Record `open_card` if its Status is not Done.

**Rejection screen (NOSEO):** run the page topic (title, H1, main_keyword) through the 22 rejection categories. Use the deterministic Pass A regex list from spec 02 §5.5, and optionally the LLM Pass B (`claude-haiku`, cached per URL until the rules doc version changes). A REJECT → **NOSEO**. A CAUTION is kept, but the reason is attached.

## 7. Level assignment (deterministic decision table)

Evaluate top to bottom; **the first match wins**. Every rule writes a human-readable `why` string. All numbers are settings.

| # | Condition | Level | `why` template |
|---|---|---|---|
| 1 | Rejection screen = REJECT, or redirected/merged | **NOSEO** | "Topic hits rejection pattern #{n} ({name}). Touch only for a Legal compliance fix." |
| 2 | `open_ticket` or `open_card` exists | **L0 Hold** (`in_pipeline`) | "Already in the pipeline: {BP-key / Notion card}. Recheck after it's published." |
| 3 | `age_days < 42` (updated in the last 6 weeks) or `recent_ticket` | **L0 Hold** | "Updated {n} days ago. Rankings need 4–6 weeks to settle. Recheck on {date+28}." |
| 4 | Not confirmed (WATCH) | **L0 Hold** (`watch`) | "First-week drop. Waiting for a second weekly confirmation." |
| 5 | `swapped_to` present and the swapped URL now ranks ≤ 3 | **L0 Hold** (`cannibalization`) | "Another BetterMe page ({url}) now holds the top 3. Decide which page owns '{kw}' before editing." (Flag for a human; no card) |
| 6 | `claim_flags` non-empty, or the screen = CAUTION for a medical/claims category (3, 9, 17, 18) | **L3 Full rewrite** | "Contains claim risk ({flags}). Needs writer + expert + Legal and a rebuild to the model shape." |
| 7 | `worst_now` is null or > 10 for the main keyword, or `lost_top3_count ≥ 4` | **L3 Full rewrite** | "Main keyword fell from #{was} to {now}. Multiple top-3 losses suggest the page no longer matches intent." |
| 8 | `age_days > 365`, or (`word_count < 0.7 × median_competitor_words` when known), or `table_count = 0` with a numeric topic (calories, steps, minutes, reps in the keywords), or `lost_top3_count ≥ 2` with `worst_now ≥ 7` | **L2 Standard refresh** | "Last updated {n} months ago / {wc} words vs competitor median {m} / {k} keywords slipped to #{worst}. Needs facts, sources, structure." |
| 9 | `worst_now ≤ 6` and the page lacks any of: Key Takeaways, ≥ 4 FAQs, direct answers under question H2s; **or** `aio_appeared`/`aio_citation_lost` | **L1 Targeted fix** | "Slipped to #{now}, page missing {missing_items}. AI Overview {appeared/citation lost}. Quick answer-first fixes should recover it." |
| 10 | Otherwise, `worst_now` 4–10 | **L2 Standard refresh** | "Slipped to #{now} despite a complete structure. Refresh content depth and freshness." |

**Checklist per level** (stored on the item, copied into the Notion card body). Use the scope text from 00 §6.6 verbatim, plus page-specific items generated from the audit, for example:

- L1: "Add Key Takeaways after the intro" (only if missing) · "Add a 40–60 word direct answer under: {list of question H2s lacking one}" · "Add {6 − faq_count} FAQs from live People Also Ask for '{main_keyword}'" · "Add alt text to {n} images" · "1 internal link to/from {cluster}" · "Change 'Updated on' only if answers changed".
- L2: all L1 items + "Put '{main_keyword}' in title/H1/first sentence (currently: {title})" · "Target ~{median} words (now {wc})" · "Add a table for {numeric terms}" · "Refresh sources older than 2 years".
- L3: "Writer + expert + Legal" · "Remove claims: {flags}" · "Rebuild to model shape: Key Takeaways, PAA headings, 5 FAQs, tables, current sources" · "Same URL, never a new slug".

**Calibration:** the old tracker's levels (Oct 8 run, `pages.level` with `why`, exported per spec 05 §7) are the labelled set. Run the decision table on those pages with the same dates (`date = 2026-10-08`, `date_compared = 2026-08-12`) and print a confusion matrix. Target **≥ 80% agreement**. List each disagreement with both reasons, and tune the thresholds (not the rules) until the target is met, recording the changes in `docs/decisions.md`.

## 8. Priority score

```
priority = traffic_lost
         × install_weight      # HIGH 1.5 · MEDIUM 1.0 · LOW 0.6 (rules from betterme-keyword-research §4)
         × core_topic_weight   # 1.3 if scarce core topic, else 1.0
         × confidence          # 1.0 confirmed · 0.5 watch · 1.2 if GSC also down ≥15% · 0.7 if GSC flat/up
         × effort_factor       # L1 1.2 · L2 1.0 · L3 0.7  (cheaper fixes first, all else equal)
```

`install_weight` comes from the page's main keyword: commercial or transactional intent, or patterns such as "workout plan / program / challenge / meal plan / for beginners" → HIGH; "benefits / is X safe" → MEDIUM; "what is / does X work / how many calories" → LOW.

Sort descending. Weekly capacity is `settings.weekly_card_cap` (default **15**, which roughly matches the current update throughput). Only the top N L1–L3 pages are proposed for cards. The rest stay on the board as "backlog".

## 9. Review UI (Option B `/decay`; Option A renders the same as `decay-report.html`)

- **Header:** run date, comparison window, units used, pages scanned, then counts per level (5 chips like the old tracker: L0 · L1 · L2 · L3 · NOSEO) and "proposed this week: N / cap".
- **Table:** page (link) · level pill · main keyword · was → now · lost top-3 count · traffic lost · priority · updated on · flags (AIO, cannibalization, claims, watch) · state.
- **Row drawer:** the lost keywords table · audit facts · the `why` · the checklist · Jira/Notion matches · position history (from §11).
- **Actions per row:** change level (reason required) · exclude (reason; never suggested again until un-excluded) · "Create Notion card".
- **Bulk:** "Create cards for selected" → a **confirmation dialog** listing each card exactly as it will be written (§10). Nothing is written without it, unless `settings.auto_create = true`, in which case the weekly job creates cards only for confirmed L1–L3 pages within the cap and logs them.
- **Weekly Slack text:** a "Copy summary" button, e.g. `Decay radar (Oct 20): 9 pages lost top-3 · 4 L1, 3 L2, 1 L3, 1 NOSEO · est. 1,240 visits/mo at risk · 8 Notion cards created.`

## 10. Notion card creation (port `blog-notion-ticket-creation`)

Target: the Articles data source `collection://1e997cc2-2a80-8086-a8ea-000bcc1073a4`. **Fetch the schema at the start of each run** (`notion-fetch` on the collection) and fail loudly if a property is missing or renamed (00 §4 notes a `Blog Category` / `Primary category` naming question).

| Property | Value |
|---|---|
| `Name` | `{main_keyword}, update`. **VERIFY** with Vladyslav whether he wants the full Jira-style summary `{main_keyword}, {N} words, update`; if so, N = the current word count rounded to the nearest 100, or the competitor median for L2/L3 |
| `New/Upd` | `Update` |
| `Status` | `Not started` |
| `URL 1` | the live article URL (always filled) |
| `JIRA` | empty. The Jira ticket doesn't exist yet. When a BP ticket is created later, Pipeline sync (spec 05 §8.1) fills it in |
| `Date` | today |
| category | the leaf category from the URL or keyword via the taxonomy (`blog-jira-ticket-creation`); flag "inferred" in the run log |
| `Choose Primary` | **VERIFY** the convention. The old board treats values ending in `(Week)` / `(October)` as priority. Default: leave empty, and set `"(Week)"` only for the top 5 by priority if Vladyslav confirms |
| `Brand/App` | empty |
| **Page body** | `## Decay radar — {level} {level_name}` · the `why` · the lost keywords table (keyword, volume, was → now, traffic lost) · the checklist as to-dos · the audit facts (updated on, words, FAQs, Key Takeaways yes/no) · "Generated by Decay Radar run {run_id} on {date}" |

**Dedupe:** never create a card when `open_card` exists. Instead add a Notion comment on that card: "Decay radar {date}: still slipping, now #{now} for '{kw}'." Guard with a unique `(url, iso_week)` key in `decay_cards`.

**After creating:** re-fetch each page and verify `Name`, `URL 1`, `Status`, `New/Upd` and `Date`, as the skill requires. Then report the created, skipped (with reason) and inferred-category items.

**Also write to the tracking list:** the `decay_suggestions` table replaces the Claude-project doc "Article Update Pipeline — Already Suggested (tracking)". Import that doc once (paste or export it into `import/already-suggested.md`; the parser reads URLs line by line) so no page is suggested twice.

## 11. Follow-up loop

When `updated_on` changes for a page with an open item (detected by the weekly audit, or by spec 01's `check_live_pages`):

- Set `item.updated_on_new` and schedule checks at **+14** and **+28** days.
- Check = `site-explorer-keywords-history` (or `organic-keywords` with `mode=exact` on the URL) for the lost keywords, recording position, AIO presence and traffic.
- At +28 days, the outcome is:
  - **recovered**: the main keyword is ≤ 3 again, or traffic lost has been recovered by ≥ 70%
  - **partial**: improved, but not recovered
  - **not recovered**: escalate the level by one (L1 → L2 → L3) and re-propose next week
- The outcome is shown on the board and appended to the Notion card as a comment.

## 12. Data model (SQLite in Option A, Postgres in Option B; same DDL)

```sql
decay_runs(id integer primary key, run_at timestamp, country text, date text, date_compared text,
  rows_returned int, units_used int, status text, error text)
decay_signals(run_id int, keyword text, url text, volume int, kd int, was int, now int,
  traffic_prev int, traffic_now int, kind text, aio_appeared bool, aio_citation_lost bool, swapped_to text,
  primary key(run_id, keyword, url))
decay_items(url text primary key, slug text, first_seen_run int, last_seen_run int, confirmations int,
  state text check (state in ('watch','confirmed','proposed','carded','in_progress','updated','recovered','partial','not_recovered','excluded','noseo')),
  level text, level_override text, override_reason text, why text, checklist json, priority real,
  main_keyword text, lost_top3_count int, traffic_lost int, worst_now int,
  notion_url text, jira_key text, excluded_reason text, updated_on_new text)
page_audits(url text, run_id int, http_status int, final_url text, updated_on text, title text, h1 text,
  word_count int, has_key_takeaways bool, faq_count int, question_h2_count int, question_h2_answered int,
  table_count int, images_missing_alt int, internal_links_out int, claim_flags json,
  median_competitor_words int, competitor_check text, screen_verdict text, screen_categories json,
  primary key(url, run_id))
decay_followups(url text, label text, due_date text, checked_at text, results json, outcome text,
  primary key(url, label))
decay_cards(url text, iso_week text, notion_url text, created_at text, payload json, primary key(url, iso_week))
decay_suggestions(url text primary key, first_suggested text, source text)   -- replaces the tracking doc
settings(key text primary key, value json)
```

## 13. Schedule

| Job | When (Europe/Brussels) | Notes |
|---|---|---|
| `decay_run` | **Monday 07:15** | detect → aggregate → audit → screen → level → priority → (auto-create if enabled) → report |
| `decay_followup` | daily 08:15 | only pages with due checks |
| `decay_report_digest` | Monday 09:00 | Slack text ready (copy, or post per spec 05 §3) |

**Option A scheduling:** run `python -m decay run` from Claude Code by hand on Mondays. To automate it, create a Cowork **scheduled task** that runs the same CLI on the linked computer, or (simpler) a task that runs the same steps through the Ahrefs and Notion connectors using this spec as its prompt.

## 14. Acceptance criteria

- [ ] `python -m decay run --date 2026-10-08 --compare 2026-08-12` reproduces the old Slipped Pages list with ≥ 90% URL overlap, and the levels agree ≥ 80% (§7 calibration).
- [ ] A page updated in the last 42 days is never carded (L0 Hold).
- [ ] A page with an open Jira update ticket or an open Notion card is never duplicated. The existing card gets a comment instead.
- [ ] A first-week minor drop stays WATCH. It becomes CONFIRMED on the second consecutive run.
- [ ] Every item has a non-empty `why` and a checklist. Every NOSEO item names a rejection category.
- [ ] Created Notion cards pass the re-fetch verification. A forced failure halfway through, followed by a re-run, creates no duplicates.
- [ ] The unit guard aborts a run that would exceed `max_units_per_run`, and the abort is visible in the report.
- [ ] No generated text (card names, checklists) contains "best" or "personalized" except when quoting the old title.
- [ ] Unit tests cover: URL normalization, the 3→4 wobble filter, the cannibalization flag, every decision-table row, the priority formula, and Notion dedupe.

## 15. Claude Code prompts

**Build (Option A):**

> Read `docs/specs/00-shared-reference.md` and `docs/specs/06-content-decay-radar.md`. Build the `decay/` package and CLI as specified for Option A (SQLite, local `.env` for `AHREFS_API_KEY` and `NOTION_TOKEN`; never commit `.env`). Before writing `ahrefs.py`, confirm the field names against the Ahrefs v3 docs for `site-explorer-organic-keywords`, `serp-overview` and `site-explorer-keywords-history`. Implement the decision table in `level.py` exactly as in §7, with every threshold in `config.py`. Write the tests from §14. Don't create any Notion cards; `create-cards` must default to `--dry-run`.

**Calibrate:**

> Import the old Slipped Pages export (`import/slipped__pages.json`, `import/slipped__progress.json`) as labels. Run `python -m decay run --date 2026-10-08 --compare 2026-08-12 --no-cards` and print the URL overlap and the level confusion matrix against the labels. Show every disagreement with both reasons, propose threshold changes only (not rule changes), and wait for my OK before applying them.

**First real run:**

> Run `python -m decay run` for this week and open `decay-report.html`. Then run `python -m decay create-cards --dry-run` and show me exactly what would be written to Notion. Only after I confirm, run it without `--dry-run` and print the verification results.

**Move into BP Ops (Option B, later):**

> Mount `decay/` as the `/decay` module in BP Ops per spec 05: Postgres storage, the weekly APScheduler job with an advisory lock, `job_runs` logging, egress `custom: api.ahrefs.com`, `custom: betterme.world`, `custom: api.notion.com`, the competitor length check disabled, and the §9 UI. Migrate `decay.db` with the slop-migrate-data skill.

## 16. Open questions (record answers in `docs/decisions.md`)

1. Card name format: `{kw}, update` or `{kw}, {N} words, update`?
2. Should the `Choose Primary` "(Week)" marker be set by the radar?
3. Weekly card cap: is 15 right?
4. Is `auto_create` OK after calibration, or always confirm by hand?
5. Countries: US only, or also GB, CA and AU?
