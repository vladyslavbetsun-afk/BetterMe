# 02 — Topic Intake Board

> **Build target:** a module of the BP Ops app (`/intake`, see spec 05).
> **Read first:** `00-shared-reference.md` §1, §4, §6.7, §7. Also the user's skills `betterme-keyword-research`, `betterme-keyword-rejection-screen`, `blog-jira-ticket-creation` and `blog-notion-ticket-creation`. Port their rules; don't paraphrase them from memory.
> **Covers the stage that has no tool today:** everything before a ticket reaches `Open` in Assignment Desk.

## 1. Goal

Turn a raw keyword idea into an approved, fully specified BP Jira ticket plus its Notion card, with every screening step recorded. Today this happens across Google Sheets ("Теми на ок", "New Keywords for Articles"), Slack DMs with Polina, and one-off Claude sessions.

Targets:

- **20–25 approved keywords per week**, with the install-intent mix visible (e.g. "14 HIGH / 7 MEDIUM / 2 LOW").
- At least 1 article per week in each of Nutrition, Diets, Fitness, Weight Loss and Mental Health.
- Zero duplicates of existing articles or tickets reach Jira.
- Zero banned words ("best", "personalized") in generated titles and meta.

## 2. Users

| User | Does |
|---|---|
| Vladyslav | reviews, approves, creates tickets |
| Polina K (researcher) | submits candidate keywords (form or sheet), sees verdicts and reasons |
| Volodymyr | optional final sign-off on CAUTION items |

## 3. Pipeline (state machine)

```
INBOX ──auto──▶ ENRICHED ──auto──▶ SCREENED ──human──▶ APPROVED ──human(confirm)──▶ TICKETED
                                     │                    │
                                     ├──▶ NEEDS_DECISION ─┘ (team decision: Tai Chi, reformer, Legal)
                                     ├──▶ REJECTED (with category #)
                                     └──▶ PARKED (seasonal / recipe / capacity)
DUPLICATE ◀── any stage, if a matching article or ticket is found ──▶ suggest "update instead" → spec 01 update queue
```

Every transition writes `candidate_events(candidate_id, from, to, by, at, reason)`.

## 4. Intake sources

1. **Paste box:** one keyword per line, optionally `keyword<TAB>note`.
2. **CSV/XLSX upload:** columns detected by header name (`keyword`, `topic`, `volume`, `kd`, `note`, `subheadings`, `variations`, `faqs`).
3. **Google Sheet import:** a sheet ID plus tab name, read via the Sheets API (custom secret, a service account with viewer access). **VERIFY** the sheet IDs for "New Keywords for Articles" and "Теми на ок" with Vladyslav.
4. **From the Performance module:** update candidates arrive as `kind = update`, linked to an existing URL. They skip the new-article duplicate check but run the rejection screen against the article's topic.

Normalize: lowercase, trim, collapse whitespace, strip quotes. De-duplicate within the batch.

## 5. Automatic enrichment and screening (jobs, not page-load calls)

Run as a background job per batch, with progress shown in the UI.

| Step | How | Output fields |
|---|---|---|
| 5.1 Metrics | Ahrefs `keywords-explorer-overview` (country `us`, select `keyword,volume,difficulty,parent_topic,parent_volume,intents,traffic_potential`), 40 keywords per call | volume, kd, intents, parent_topic, traffic_potential |
| 5.2 SERP | Ahrefs `serp-overview` (`top_positions=10`, select `position,url,domain_rating,title,type`) **only** for candidates that pass the thresholds in 5.3 (saves units) | serp_top10 jsonb, `dr_le_70_count`, `serp_flags` (youtube_dominated, aio_present, brand_app_dominated, reddit_quora_present) |
| 5.3 Thresholds | rules from `betterme-keyword-research`: volume ≥ 50 (≥ 20 for the scarce core topics), KD ≤ 60, primary keyword ≥ 2 words, at least **2 results with DR ≤ 70** in the top 10 (an independent gate that overrides KD) | `threshold_pass`, `threshold_reasons[]` |
| 5.4 Duplicate check | (a) Jira: `project = BP AND summary ~ "<keyword>"`, then confirm by exact or near match on summary or `Article:` URL; (b) live site: Ahrefs `site-explorer-organic-keywords` for `betterme.world` filtered to the keyword, with the ranking URL; (c) Notion `Name` contains; (d) **topic overlap**: an LLM compares against the titles of the top 20 ranking BetterMe URLs for the parent topic | `duplicate_of` (url or key), `duplicate_confidence` |
| 5.5 Rejection screen | Two passes. **Pass A (rules, deterministic):** regex lists for patterns that are obvious from wording (banned superlatives; "recipe/recipes/meal prep"; "pregnan*"; "menopause / perimenopause / PCOS / thyroid"; "carnivore / zero carb / detox / cleanse"; "dry fasting"; "skipping (lunch|dinner|meals)"; "bed mobility / gait training / ROM exercises / post-op"; "military / navy seal / powerlifting / progressive overload"; "bulking"; spot-reduction phrases such as "inner thigh / arm fat / v-shaped / bubble butt"; "somatic"; "autophagy"; "bad knees"). **Pass B (LLM):** all 22 categories from `betterme-keyword-rejection-screen` plus the Rejection Patterns doc text (`docs/rules/keyword-rejection-patterns.md`), with structured JSON output `{verdict: PASS\|CAUTION\|REJECT, categories: [int], reason, needs_team_decision: bool}`. Pass A hits are passed to the LLM as hints and can't be overruled to PASS | `screen_verdict`, `screen_categories[]`, `screen_reason`, `team_decision` |
| 5.6 Install intent | rules first: patterns such as `workout plan / program / challenge / meal plan / for beginners / app / how to start` → HIGH; `benefits of / is X safe` → MEDIUM; `what is / does X work / how many calories` → LOW. Ahrefs `intents` adjusts the result (commercial or transactional raises it one step; navigational → reject category 19 check). The LLM must name the **specific in-app program or feature** for a HIGH rating, otherwise cap at MEDIUM. The program list comes from `docs/rules/product-features.md` (export it from "BetterMe Product Deep Dive") | `install_intent`, `install_feature` |
| 5.7 Suggested verdict | combine: REJECT if any REJECT category or a hard threshold failure; NEEDS_DECISION if `team_decision`; CAUTION if CAUTION or LOW intent; otherwise APPROVE-suggested | `suggested_verdict` |

**LLM settings:** use `claude-haiku` for 5.5 and 5.6 (classification, high volume) and `claude-sonnet` only for brief generation (§7). Monthly budget for the module: **$10**. Cache results by `(keyword, rules_doc_version)` so re-screening only happens when the rules doc changes.

## 6. UI

### 6.1 Board

Columns are states. Cards show the keyword, volume, KD, a DR≤70 badge (`2/10 ✓`), an install-intent chip (HIGH green / MEDIUM amber / LOW grey), the suggested verdict, the category number(s) and a one-line reason.

- Header counters: **approved this week / 20–25 target**, the intent mix of the approved set, and coverage per category this week (5 chips: Nutrition, Diets, Fitness, Weight Loss, Mental Health; grey until at least 1 is approved).
- Filters: source, submitted by, verdict, intent, topic, "core topic only".
- Keyboard: `A` approve, `R` reject (asks for the category), `P` park, `D` needs decision, `J`/`K` to move between cards.

### 6.2 Card drawer

- Metrics plus a SERP table (position, domain, DR, type, title).
- Every screening category hit, with its reason text. The human can override the verdict, with a required reason saved to the event log.
- Duplicate panel: the matched URL or ticket with **"Treat as update instead"** (sends it to the Performance update queue).
- Notes / thread (who said what). Polina sees the verdict and reason, which closes the feedback loop that today happens in DMs.

### 6.3 Weekly batch view

- A table of approved and unticketed candidates, ready to export as XLSX in the team's tracker format (columns from the skill: Topic, Primary Keyword, Volume, KD, Intent, Install-Intent, DR≤70 check, Verdict, Comment), colour-coded green, yellow, red and grey by verdict.
- **"Create tickets for selected"** → §7.

## 7. Ticket and brief creation (writes; ask before doing)

For each selected APPROVED candidate, generate a **draft brief** first and show it for review and edits. Nothing is written to Jira or Notion until the user confirms.

Brief fields (rules from `blog-jira-ticket-creation`):

| Field | Rule |
|---|---|
| Summary | `{primary keyword}, {N} words`. N = the median word count of the last 30 BP Article tickets in the same category, rounded to the nearest 100 (usually 1600–1900). Show the computed basis |
| Title | Title Case of the keyword or article title |
| Meta Title | 50–60 chars, keyword near the front, `| BetterMe` if it fits. Show a live char counter. **Block saving** if it contains a banned word |
| Meta Description | 150–160 chars, keyword included naturally, soft CTA. Counter plus banned-word block |
| Main keyword, LSIs, Entities | from Ahrefs related terms and SERP titles (LSIs/Entities lines are omitted if empty) |
| Quiz/topic | look up the topic in the quiz sheet `17qXKwEt2eY-e06PCREkh_mziYeEdGpRRcRo1wRjJgzs`, tab "NEW worksheet" (column A topic → column B base URL). Replace the `utm_campaign` placeholder with `Title_Case_With_Underscores` of the keyword. Prefer the gender-neutral variant |
| Category | ONE leaf value from the taxonomy (dropdown; no free text) |
| Expert | left blank (`**Expert**: `) |
| Subheadings / Additional Keywords / FAQs | ADF, one item per line. FAQs from live People Also Ask where available |
| Linked Articles | 3 real betterme.world URLs with anchor text, chosen from the Performance module's `articles` table and Ahrefs top pages in the same cluster. **Every URL must return HTTP 200 when created**, and invented URLs are never allowed |

On confirm, in this order, with each step logged and safe to retry:

1. `createJiraIssue` (project BP, issue type Article, `customfield_11100 = "110"`, Managers = Vladyslav, reporter = Vladyslav, description in markdown with **bold** labels).
2. `editJiraIssue` with ADF for `customfield_11717/11718/11719/11720`.
3. Notion `create-pages` in the Articles data source (Name = summary, New/Upd = New, Status = Not started, JIRA = url, Date = today, category).
4. Re-fetch both and verify the fields. Mark the candidate `TICKETED` with `jira_key` and `notion_url`.

If step 2, 3 or 4 fails, the candidate stays `APPROVED` with `partial_ticket = true` and a "Resume" button. Never create a second Jira ticket for the same candidate. The guard is a unique `(candidate_id)` key in the `ticket_creations` table.

> Platform note: on the slop machine, Jira **writes** need the write-access decision described in spec 05 §3. Until that decision is made, step 1–2 output is a **"Copy as Jira ticket"** bundle (markdown description plus ADF JSON per field) and a pre-filled Jira create link, so the module is still useful in read-only mode.

## 8. Data model

```sql
candidates(id bigserial primary key, keyword text, normalized text unique, kind text check (kind in ('new','update')),
  existing_url text, topic text, source text, submitted_by text, submitted_at timestamptz,
  state text, volume int, kd int, intents jsonb, parent_topic text, traffic_potential int,
  serp_top10 jsonb, dr_le_70_count int, serp_flags text[],
  threshold_pass bool, threshold_reasons text[],
  duplicate_of text, duplicate_confidence real,
  screen_verdict text, screen_categories int[], screen_reason text, team_decision bool,
  install_intent text, install_feature text, suggested_verdict text,
  final_verdict text, final_reason text, decided_by text, decided_at timestamptz,
  rules_version text, week date)
candidate_events(id bigserial, candidate_id bigint, from_state text, to_state text, by text, at timestamptz, reason text)
briefs(candidate_id bigint primary key, fields jsonb, edited_by text, edited_at timestamptz)
ticket_creations(candidate_id bigint primary key, jira_key text, notion_url text, steps jsonb, status text)
rules_docs(version text primary key, name text, body text, loaded_at timestamptz)
```

## 9. Acceptance criteria

- [ ] Pasting 40 keywords gives enriched and screened cards in under 3 minutes, with Ahrefs units used shown.
- [ ] A keyword with an existing article (e.g. "wall pilates") is flagged DUPLICATE with the URL.
- [ ] "best chair yoga for seniors" → CAUTION/REJECT with category 12. The generated meta title never contains "best".
- [ ] "bed mobility exercises for elderly" → REJECT 22. "bed pilates" → not rejected by category 22.
- [ ] Every REJECT shows a category number. Every APPROVE with HIGH intent names an in-app feature.
- [ ] Create-tickets on 3 candidates gives exactly 3 Jira tickets and 3 Notion cards, all fields verified. A retry after a forced failure in step 3 doesn't duplicate Jira tickets.
- [ ] The weekly header shows the correct approved count and category coverage.

## 10. Open questions

1. Sheet IDs and tab names for the current keyword sheets.
2. Where does the newest "Keyword Rejection Patterns" doc live, and who updates it? (The module reloads it when its version changes.)
3. Should Polina get write access (submit plus comment) or only submit?
4. Does Volodymyr need to sign off CAUTION items, or does Vladyslav decide?
