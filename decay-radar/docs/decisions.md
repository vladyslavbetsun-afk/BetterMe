# Decay Radar: decisions and open questions

Spec: [`docs/specs/06-content-decay-radar.md`](specs/06-content-decay-radar.md). Each entry says what the code does and why, where it departs from the spec or fills a gap.

## Decisions

**D-01 Layout.** The package lives in `decay-radar/` next to `bp-review-flow/`. On top of the modules in §2 there are three more: `pipeline.py` (orchestration), `calibrate.py` (§7 calibration), and `__main__.py`. Card creation (`create_cards`) lives in `notion.py`. Only `storage.py` and `config.py` know whether this is Option A or Option B.

**D-02 Unit budget and row cap.** Live calls on 2026-10-17 cost **55 units/row** for the detection select and **18 units/row** for the AI Overview query. Ahrefs v3 `organic-keywords` has no offset, so a run gets a single page of results. At the spec's `max_rows = 1000`, the estimate is 55,000 units, which is always above the 25,000 guard. Defaults are now `max_rows = 400` and `aio_max_rows = 100`, so the estimate is 400×55 + 100×18 = 23,800 per country. Rows are ordered by `sum_traffic_prev:desc`, so the cut drops the least valuable losses. The per-row costs are settings (`units_per_row`, `aio_units_per_row`). The actual cost comes from the `x-api-units-cost-total-actual` header, or from a `limits-and-usage` diff, and is stored on `decay_runs.units_used`. If you add GB/CA/AU, the guard counts each extra country as another 23,800, so raise `max_units_per_run` or lower `max_rows`.

**D-03 Live Ahrefs schema versus §3.** Three things in the spec did not hold against the live API:
- `positions_kinds` / `positions_kinds_prev` can be **filtered on but not selected**. Selecting them fails with "column not found". AI Overview citation loss therefore comes from a second, filter-only query (`ahrefs.aio_params`, `list_is any eq ai_overview_found`), which returns `(keyword, url)` pairs. `aio_appeared` still comes from `serp_features` vs `serp_features_prev`.
- On rows lost entirely (`status = "right"`), `keyword`, `volume` and `keyword_difficulty` are **null**. The code reads `keyword_prev` and `volume_prev` for those rows. Without this, every "lost entirely" keyword (the most severe signal) would fail the volume floor.
- `site-explorer-keywords-history` returns only per-bucket counts (top3, top4_10, …), not per-keyword positions. The §11 follow-ups use `organic-keywords` with `mode=exact` on the URL, filtered to the lost keywords.

**D-04 Select list.** Added `is_navigational`, because §4 drops navigational rows. Removed `keyword_difficulty`: it costs about 10 units/row, no rule uses it, and it is null on lost rows anyway. `decay_signals.kd` stays in the DDL and is null.

**D-05 Level scope text.** `config.LEVEL_SCOPE` holds stand-in scope lines. Replace them with 00 §6.6 **verbatim** when that file is added to `docs/specs/`. The checklists start with the scope line, followed by the page-specific items from §7.

**D-06 Rejection screen Pass A.** Spec 02 §5.5 (the canonical regex list) wasn't available, so `screen.PASS_A` is a port of the 22 categories in the `betterme-keyword-rejection-screen` skill (rules version 2026-08-28). Judgment calls:
- "somatic" is **CAUTION**, not REJECT. The skill says "somatic anything", but Somatic Exercises is a live leaf in the blog taxonomy (`blog-jira-ticket-creation`), and REJECT would send every somatic page to NOSEO.
- Equipment (#15), recipe format (#11), superlatives (#12) and zero-click (#14) are CAUTION. They are attached to the item as reasons and don't change the level.
- Spot reduction (#18), the hormonal/medical pairings (#3), pregnancy (#9) and the "fix your spine" claim (#17) are CAUTION. Under §7 rule 6 they lead to **L3**.
- Dry fasting/refeeding (#17), extreme diets (#6), therapy modalities (#8), alcohol or period fasting (#20), meal-skipping (#21) and clinical rehab terms (#22) are REJECT, which gives **NOSEO**.
- Categories that need data (2, 7, 10, 19) are left to the optional LLM Pass B (`llm_screen`, default off, cached per URL and `rules_version`).

**D-07 Extra tables.** `decay_run_items(run_id, url, payload)` keeps each run's full per-page snapshot: the rollup, audit, screen, rule number, flags and notes. The report and the card bodies are rendered from it. `screen_cache` caches Pass B. Both are created by the same DDL list in `storage.py`.

**D-08 Rule 5 (cannibalization) can't fire with the §3 filter.** The query requires `best_position > 3 or null`, and `best_position` covers every `/articles/` page. So a swapped-in article never ranks ≤ 3 in the rows we get back. The rule is implemented exactly as written, with the threshold in `cannibalization_max_rank` (default 3). The cannibalization flag still shows on the board. Calibration proposal, which needs your OK as a threshold change: raise `cannibalization_max_rank` to 10, so a page whose keyword moved to another article still in the top 10 is held for a human decision.

**D-09 Reading the decision table.**
- Rule 7 checks the **main keyword's** current position (`main_now`): "null or > 10 for the main keyword".
- `worst_now` is null when any lost keyword dropped out entirely. Rule 8 treats null as worse than any position; rules 9 and 10 treat it as not matching.
- If nothing matches, rule 11 (L2 fallback) applies. It's practically unreachable but keeps every page levelled.
- Rule 1 also covers a page that now returns 404/410, as well as a redirect.

**D-10 Weekly confirmation.** "Two consecutive weekly runs" means consecutive runs that fall in different ISO weeks. The week is taken from the report date + 1 (the day the job runs), so a Tuesday re-run counts as the same week as the Monday run. A skipped week does not break the chain.

**D-11 Follow-up escalation.**
- At +28 days, "not recovered" escalates the level the page had **when it was carded** (stored in `decay_cards.payload.level`). The live level can't be used because it's L0 by then: the page was updated less than 42 days ago.
- On the next run, the escalated level replaces rule 3's hold (rule "12": "Not recovered 4 weeks after the update; escalated to L…").
- An escalated page skips the "already suggested" filter, so it is re-proposed as §11 asks.
- "Partial" means any keyword ranks better than at detection, or any traffic came back.

**D-12 Crash-safe card creation.** Before calling Notion, the code writes a pending `decay_cards(url, iso_week)` row with no `notion_url`. Suppose Notion creates the page but the process dies before storing it. On the re-run, the pending row and an open card with that `URL 1` are both found, so the card is **adopted** rather than created again. The forced-failure test covers this.

**D-13 GSC cross-check.** Input is a CSV (`--gsc`) with `url, clicks_last_28, clicks_prev_28`, until spec 01 data exists. A drop of ≥ 15% multiplies confidence by 1.2. A change of −5% or better counts as "flat or up", multiplies it by 0.7 and adds the note "Ahrefs shows a drop, GSC clicks stable". Anything in between is neutral.

**D-14 Calibration reproduction.** `run --date D` treats "today" as D + 1, so page age is measured as of that run. The page HTML is still fetched live today, so a page updated after Oct 8 can disagree with the old tracker. List those as disagreements; they're not a threshold problem.

**D-15 Notion.**
- Uses API version `2025-09-03` (data sources) against `collection://1e997cc2-…`.
- The schema is fetched on every apply. A missing required property, or neither `Primary category` nor `Blog Category`, raises `SchemaError` and nothing is written.
- Property values are typed from the live schema: title, rich_text, select, status, url, date.
- `JIRA` and `Brand/App` stay empty. `Choose Primary` stays empty unless `choose_primary_week_top > 0`.
- The category is always inferred, from the taxonomy in `blog-jira-ticket-creation`, and reported as inferred.

**D-16 Jira.**
- Read-only. Calls `GET /rest/api/3/search/jql` with `project = BP AND text ~ "<slug>"`, then requires the exact normalized URL on an `Article:` / `Original article:` line of the ADF description, including smart links.
- "Recent" uses `statuscategorychangedate` (falling back to `resolutiondate`, then `updated`) within 60 days of status Published.
- With no Jira credentials the check is skipped, and a note says so on each item.

**D-17 Banned words.** Every template line (why strings, checklist items, scope text) is tested to contain neither "best" nor "personalized". Card names and checklist lines quote the keyword and the old title verbatim, which is the exception the spec allows. Note that a "best" in the title or H1 is itself a claim flag, and leads to L3 under rule 6.

**D-18 Already-suggested list.** `import-suggested` reads `import/already-suggested.md`. Lines under a dated `#` heading take that date. The radar won't propose a URL that was suggested in the last `resuggest_after_days` (180). Every card the radar creates also adds a row.

**D-19 Install intent.** The patterns come from `betterme-keyword-research` §4 and are checked in this order:
1. LOW patterns ("what is", "does X work", "how many calories", "calories in", "which muscles"), unless a HIGH pattern also matches.
2. HIGH patterns (plan, program, challenge, for beginners, app, routine, N-day) or commercial/transactional intent.
3. MEDIUM (benefits, is X safe).
4. Default MEDIUM.

## Open questions

From §16, still to answer:
1. Card name format: `{kw}, update` (current default) or `{kw}, {N} words, update`? Switch with `settings set card_name_format '"{kw}, {n} words, update"'`.
2. Should the radar set the `Choose Primary` "(Week)" marker? Default no. Set `choose_primary_week_top` to 5 to mark the top 5.
3. Is a weekly card cap of 15 right?
4. Is `auto_create` OK after calibration, or should cards always be confirmed by hand? Default: confirm by hand.
5. US only, or also GB, CA and AU? See D-02 for the unit cost.

New from the build:

6. **Merged or 404 pages and the "names a rejection category" criterion.** §14 says every NOSEO item names a rejection category, but a redirect isn't a topic rejection. The why currently says "rejection category n/a (redirect)". Should these be a separate state instead?
7. Paste 00 §6.6 (level scope text) and 02 §5.5 (Pass A regex list) into `docs/specs/`. D-05 and D-06 are stand-ins until then.
8. D-08: OK to raise `cannibalization_max_rank` to 10?
9. Rule 6 sends any page with "best" in its title or H1 to L3 (Full rewrite). That will put many otherwise healthy pages into L3. Check this during calibration.
