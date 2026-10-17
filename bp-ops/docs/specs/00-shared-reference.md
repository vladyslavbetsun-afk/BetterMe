# 00 — Shared reference (constants, roster, rules)

Every other spec in this folder depends on this file. Put it at `docs/specs/00-shared-reference.md` in the repo and tell Claude Code to read it first.

The values were pulled from the live artifacts on 2026-10-17. Their source code is in `legacy-artifacts/`. When this file and the legacy code disagree, this file wins. Values marked **VERIFY** were never confirmed and must be checked against the live system before they are used.

---

## 1. Jira (BP project)

| Constant | Value |
|---|---|
| Site | `https://newsiteam.atlassian.net` (ticket URL `https://newsiteam.atlassian.net/browse/<KEY>`) |
| cloudId | `657e24cd-f643-4482-aba5-7e848607df28` |
| Project key | `BP` ("Blog Project", service-desk type) |
| Issue type | `Article` (id `10596`) |
| Request type field | `customfield_11100` = `"110"` (Article). Set it on create |
| Status order | `Open` → `Text` → `Review` → `Proofreading` → `Ready` → `Published` |

### Transition IDs

| To status | ID | Note |
|---|---|---|
| Text | `"11"` | fallback. Look the ID up with `getTransitionsForJiraIssue` first |
| Review | `"21"` | |
| Proofreading | `"31"` | |
| Ready | `"41"` | |
| Published | none fixed | look up each time and match `/^published$/i` |

### Custom fields

| Field | ID | Type / notes |
|---|---|---|
| Managers | `customfield_11709` | user picker. JQL `cf[11709]` |
| Author (writer) | `customfield_11710` | user picker. JQL `cf[11710]` |
| Expert | `customfield_11711` | user picker |
| Proofreader | `customfield_11712` | user picker |
| Request participants | `customfield_11208` | **must be an array** of `{accountId}`, even for one person |
| Subheadings | `customfield_11717` | ADF textarea, one item per line (`hardBreak`) |
| Additional Keywords | `customfield_11718` | ADF textarea |
| Linked Articles | `customfield_11719` | ADF textarea: 3 links with anchor text |
| FAQs | `customfield_11720` | ADF textarea |
| Topic tags | `customfield_11726` | cascading select `{"value": parent, "child": {"value": child}}` |
| Word count | — | **not a field**. It is parsed from the summary (see §6.2) |
| Deadline | — | **do not use**. Contractors can't see it |

Summary convention: `{primary keyword}, {N} words`. Updates add `, update` (e.g. `BP-1595 best muscle group combinations, 1800 words, update`). Some tickets use `12k` / `15k` for traffic instead of a word count, e.g. `BP-670 active recovery day workout, 12k`. **VERIFY** what `12k` means. Assignment Desk reads it as a word count (×1000), which is probably wrong. It is more likely monthly search volume.

### JQL library

```text
# Open queue (Assignment Desk)
project = BP AND status = "Open" ORDER BY created ASC

# Active writing/review/proofreading with a writer
project = BP AND status in ("Text","Review","Proofreading") AND cf[11710] is not EMPTY

# Month-to-date earnings basis (article counts in the month it LEFT Text)
project = BP AND cf[11710] is not EMPTY AND status CHANGED FROM "Text" DURING (startOfMonth(), now())

# My pipeline (Review Flow)
project = BP AND status in ("Open","Text","Review","Proofreading","Ready") AND customfield_11709 = currentUser() ORDER BY updated DESC

# Expert load
project = BP AND status = "Review"          -- fields: customfield_11711

# Publishing queue
project = BP AND status = "Ready" ORDER BY updated DESC

# Pipeline sync window (Notion ↔ Jira)
project = BP AND (status != Published OR updated >= -30d) ORDER BY key DESC

# Published in a window (performance cohorts)
project = BP AND status CHANGED TO "Published" DURING ("2026-08-01", now())
```

Search mechanics: `maxResults: 100`. Paginate with `nextPageToken` = `issues.pageInfo.endCursor`. Results come back under `issues.nodes`. Use `responseContentFormat: "markdown"` for comments. Changelog needs `expand: "changelog"` (the old Byline Board capped this at 80 tickets per load because it is slow).

### Comment conventions (ADF)

All comments start with a mention of the writer or expert. In `noteMode = "internal"` they carry `commentVisibility: {"type":"role","value":"Service Desk Team"}`.

| Purpose | Text after the mention | Detection regex |
|---|---|---|
| Ask writer to address expert notes | ` Hi. Please address the comments. Thanks.` | `/please address/i` |
| Chase writer | `Hi. Any news on the edits?` | `/any news on the edits/i` |
| Chase expert | `Hi. Any news on the ticket?` | `/any news on the ticket/i` |
| Generic status | `Hi. What's the status on this one?` | — |

Ignore all comments from Oksana Pidlisna and Yuliia Koreniuk when deciding workflow steps. Their comments are images and live links.

---

## 2. People (canonical roster)

**Today this roster is copied into 6+ artifacts, and the copies have drifted apart.** In the new app it lives in ONE table (`people` plus `rates`) and every module reads from there. Seed it from this table.

| id (slug) | Display name | Jira display name(s) | Jira accountId | Slack ID | Role | Niche | Rate | Expert review? |
|---|---|---|---|---|---|---|---|---|
| zindzy | Zindzy Gracia | ZINDZY GRACIA | `70121:064c601e-cbf1-4550-8d17-8fea2b338118` | `U02A60PF739` | writer | exercise | $0.03/word | yes |
| eve | Eve Chalicha | Evelyn Chalicha | `712020:51b52722-9eb1-4aa8-8b6d-527b045f3913` | `U02BABJ64DN` | writer | exercise | $0.035/word | yes |
| jeremy | Jeremy Mukhwana | Jeremy Mukhwana | `712020:4e42fbfd-ec2b-414f-99d4-41dfb6faa417` | `U02ALU6SQSF` | writer | both (**VERIFY**: Byline says exercise) | $0.03/word | yes |
| nderitu | Samuel Nderitu Munuhe | Nderitu Munuhe | `712020:4e7281a8-604f-46bd-9f0e-61aa6a42030b` | `U02AZB589JM` | writer | any | $0.04/word | yes |
| eva | Eva De Angelis | Carla Eva De Angelis (Viard) | `6348b6fe94b0b260830778d6` | — | writer | nutrition | $0.11/word (invoice) | **no** |
| rubiolo | Maria Lourdes Rubiolo | lic.rubiolo.nutri | `712020:44ae3ce5-c8c9-43b3-b106-63585b9a2edf` | — | writer | nutrition | $0.10/word (invoice) | **no** |
| anoshia | Anoshia Riaz | Anoshia Riaz | `70121:fb24c986-30fc-4274-b096-e53d17aad7a4` | `U058J380M40` | writer | any | $0.04/word | yes |
| srijoni | Srijoni Gupta Roy ("Sri R") | srijoni.guptaroy | `712020:cd6750f8-c67c-425d-a302-5df85069691b` | `U05RXE73VPX` | writer | any | $0.08/word | yes |
| stephanie | Stephanie Wright | bluegrassnursewright | `712020:502524c1-2ded-482c-92d0-19f23c66eb0a` | — | writer | any | $200/article (invoice) | **no** |
| giulia | Giulia Ralph | Giulia Ralph | `712020:49c3c2b9-1390-4df0-a4c9-6461502d6d74` | — | writer | both | $0.12/word (invoice) | **no** |
| brenda | Brenda Peralta | Brenda Peralta | `612fcdbd9976c30069467dad` | — | writer | both | $100–120/article (invoice) | **no** |
| natalia | Nataliia Lutsiv | Наталі Луців | `628756b3bd640f0068afa6a9` | — | writer | any | $0.06/word | yes |
| clare | Clare Kamau | Clare Kamau | `712020:bff933c8-cc5b-49af-8cd5-adc27df2c921` | `U02AE0M1VPY` | writer | any | $32.50/article | yes |
| carter | Carter Lee | Carter Lee | `712020:78a486c4-c1e4-4bc0-bba9-4676513ecb28` | — | expert | fitness | $50/article (**VERIFY**: Experts board says $40/h; invoice) | — |
| garett | Garett Reid | Garett Reid | `5de4fe878389de0cd335416b` | — | expert | fitness | $50/article (**VERIFY**: $50/h, Upwork) | — |
| angelica | Angelica Galvan | Angelica Galvan | `712020:43ac8bef-1645-465e-9909-5bbb7ee20fa5` | — | expert | nutrition | $50/article (**VERIFY**: $45/h, invoice) | — |
| corrarello | Maria Eugenia Corrarello | maria.eugenia.coaching | `712020:87a66480-0c2d-4444-be68-26bb3afbbd60` | — | expert | nutrition | $20/article (**VERIFY**: "$40–45/h proposed") | — |
| kelsey | Kelsey Butler | kelseykingbutler | **VERIFY** | — | expert | nutrition | $45/article | — (on the Experts board only; **VERIFY** she is active) |
| colette | Z. Colette Edwards | — | **VERIFY** | — | expert | — | $2,500/month retainer (fixed) | — |
| amanda | Amanda Pasko | — | **VERIFY** | — | expert | — | $0.07/word (**VERIFY** active) | — |
| tim | Tim Jones | Tim Jones | `70121:f5089ddd-2808-4286-a217-02dd8bda85e9` | — | proofreader | — | Upwork (**VERIFY** rate) | — |
| yuliia_k | Yuliia Koreniuk | — | `712020:b345726f-fe25-4239-a7dc-7322d7dbc2ae` | `U0AHVPJ0QKA` | publisher | — | internal | — |
| oksana | Oksana Pidlisna | — | `712020:7cf474f8-6ae6-439f-8d54-f6a1e3143066` | — | designer | — | invoice | — |
| karina | Karina Sorvachova | — | `712020:3584bb79-f831-407e-a40a-02e8084953d5` | — | designer (image links) | — | internal? **VERIFY** | — |
| polina | Polina Klieshcheva | — | **VERIFY** | `U07AN6WBZ0F` | researcher (keywords) | — | $600/month (fixed) | — |
| vladyslav | Vladyslav Betsun | — | `712020:0d312ff6-23a7-4fa4-b5a1-b57be36d9f75` | `U0BNYBLCD63` | manager (owner) | — | internal | — |
| volodymyr | Volodymyr (SEO/GEO lead) | — | **VERIFY** | `U017H7SSK24` | stakeholder (gets daily report) | — | internal | — |
| yuliia_h | Yuliia Horetska | — | — | `U07A90HSQ5A` | finance/ops (gets monthly budget) | — | internal | — |

Former contributors in Editorial Load (seed them as `active = false`): Alexis Schofield, Sachini Akuretiya, Kristen Fleming, Kaye Smith, Micky Lal, Jared Meacham, Troy Hurst.

**Matching rule:** always match people by Jira `accountId`, never by display name. The old boards matched by display name and broke on aliases like "Наталі Луців" and "lic.rubiolo.nutri". Keep a `person_aliases` table only for parsing free text.

**Rates need effective dates.** Model them as `rates(person_id, kind, amount, unit, currency, effective_from, effective_to, billing: upwork|invoice|retainer|internal)` so changing a rate doesn't rewrite past months.

---

## 3. Slack

| Thing | Value |
|---|---|
| Vladyslav | `U0BNYBLCD63` |
| Publishing batches go to | Yuliia Koreniuk `U0AHVPJ0QKA` |
| Daily report goes to | DM with Volodymyr (`U017H7SSK24`), at about 17:30 Brussels time |
| Monthly budget goes to | Yuliia Horetska `U07A90HSQ5A` |
| Jira→Slack notification feed (Review Flow read this) | DM channel `D0BU742R27L`. In the new app, poll Jira directly instead |

### Message templates (keep verbatim; people are used to them)

```text
# Writer follow-up DM (first / repeat)
Hi {first_name}, hope you're doing well! Just following up on the edits for these tickets:
• <{url}|{KEY} {short_title}>
...
Could you share an update on where they stand when you get a chance? Thank you!

# repeat variant replaces line 1 with:
Hi {first_name}, hope you're doing well! Just checking in again on the edits for these tickets:

# Publishing batch DM (sent 09:00 local on weekdays)
Hi. Here are articles for publishing:
• <{url}|{KEY} {short_title}>
```

`short_title` = summary up to the first comma, keeping the word count / `update` suffix as it appears today (e.g. `BP-1595 best muscle group combinations, 1800 words, update`).

**Known bug to fix:** on 2026-10-15, writers Eve and Jeremy each got the same follow-up DM **twice within one second**. Every outbound message must carry an idempotency key `(recipient, ticket_set_hash, yyyy-mm-dd, template)` with a UNIQUE constraint in the database. Send only after the insert succeeds.

---

## 4. Notion (Articles database)

| Constant | Value |
|---|---|
| Database | `https://app.notion.com/p/betterme-team/1e997cc22a8080a5bef9c9da6dd8d43f` |
| Data source | `collection://1e997cc2-2a80-8086-a8ea-000bcc1073a4` |

| Property | Type | Notes |
|---|---|---|
| `Number` | number/unique id | card number |
| `Name` | title | = Jira summary |
| `Status` | status | `Not started` / `In progress` / `Done` |
| `Choose Primary` | text/select | priority. Counts as a priority if it matches `/\((Week|October)\)\s*$/` |
| `Blog Category` / `Primary category` | text | **VERIFY** which name is current (the skill says `Primary category`, the Editor says `Blog Category`) |
| `New/Upd` | text | `New` or `Update` |
| `URL 1` | url | live article URL. Always filled |
| `JIRA` | url | Jira ticket URL. Extract the key with `/BP-\d+/` |
| `Date` | date | creation day |
| `Brand/App` | text | usually blank |

Jira → Notion status map: `Open` → `Not started`; `Text`, `Review`, `Proofreading`, `Ready` → `In progress`; `Published` → `Done`.

---

## 5. SEO data sources

| Source | Use | Details |
|---|---|---|
| Ahrefs API v3 | traffic, keywords, positions, AI citations, SERP, keyword metrics | Endpoints used before: `batch-analysis` (exact URL), `site-explorer-organic-keywords`, `site-explorer-keywords-history`, `site-explorer-ai-responses-count` (`mode=exact` URL / `prefix` `/articles/` / `subdomains` domain), `keywords-explorer-overview`, `serp-overview`. Brand Radar returned "Missing addon" on 2026-09-04 (**VERIFY** before relying on it). Money values come back in **USD cents** |
| Google Search Console | clicks, impressions, CTR, avg position per page and query | Property `https://betterme.world/articles/` (URL-prefix). **VERIFY** API access: either a Google service account added to the property, or Ahrefs' GSC endpoints (`gsc-pages`, `gsc-page-history`, `gsc-keywords`) if the property is connected in Ahrefs |
| Semrush | cross-check only | has run out of API units before. Never block on it |
| Live page | "Updated on" date, H1, Key Takeaways present | fetch `https://betterme.world/articles/<slug>/`. Individual article URLs work, but `/articles/` index pages redirect |

**AI visibility peer sets**

- Citation Audit (12): healthline.com, everydayhealth.com, verywellfit.com, eatthis.com, onepeloton.com, muscleandstrength.com, bodyspec.com, marathonhandbook.com, loseit.com, noom.com, fitbod.me, nourishmovelove.com
- Article Progression (5): noom.com, verywellfit.com, myfitnesspal.com, healthline.com, livestrong.com

**AIO gap query** (keywords where an AI Overview shows but doesn't cite BetterMe): organic keywords for `betterme.world/articles/` (prefix, US) where `serp_features` contains `ai_overview` AND `positions_kinds` does NOT contain `ai_overview` AND `best_position <= 20`, sorted by volume desc and grouped by URL. The count was 3,461 on 2026-09-04.

---

## 6. Business rules

### 6.1 Category detection (writer niche → expert)

Use ONE list everywhere. Below is the most complete version (BP Review Flow). Lowercase the title, replace every character outside `[a-z0-9\s-]` with a space, and match each keyword with spaces on both sides. Scoring: fitness wins if `fit_hits > nut_hits + 1`, nutrition wins if `nut_hits > fit_hits + 1`, otherwise the result is `unclear` (a human decides). An explicit override or an already-set Expert field always wins.

- **Fitness:** workout, exercise, exercises, yoga, squat, squats, pilates, push up, push-up, pushup, pull up, pull-up, pullup, plank, cardio, abs, stretch, stretches, stretching, walking, walk, running, run, hiit, calisthenics, strength, muscle, muscles, glute, glutes, lunge, lunges, burpee, deadlift, gym, fitness, training, core, dumbbell, kettlebell, jump, steps, posture, mobility, flexibility, somatic, barre, tai chi, treadmill, cycling, swimming, body composition, toning, tone, arm, arms, leg, legs, belly fat, reps, sets, warm up, cool down, swings, endurance, miles
- **Nutrition:** diet, diets, meal, meals, snack, snacks, drink, drinks, food, foods, recipe, recipes, calorie, calories, protein, carb, carbs, keto, fasting, eat, eating, nutrition, nutrient, vitamin, vitamins, fruit, fruits, vegetable, vegetables, smoothie, smoothies, juice, tea, coffee, sugar, breakfast, lunch, dinner, good for you, healthy fats, fiber, cheese, bread, rice, pasta, pepperoni, egg, eggs, oatmeal, yogurt, supplement, supplements, hydration, water, alcohol, wine, beer, sauce, salad, soup, nuts, chocolate, milk, grocery, menu, dessert, bars, shake, shakes, dieta, calorias, macronutrients, whiskey, banana, bananas, cucumber, carrot, broccoli

**Expert choice:** override → existing Expert field → the expert in that category with the **fewest tickets in Review**. Writers flagged "no expert review" skip Review entirely.

### 6.2 Word count from the summary

1. Range: `/(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)\s*words?/i` gives min and max
2. Single: `/(\d[\d,]*)\s*words?\b/i`
3. If neither matches, the ticket is **unpriced**. Do NOT treat `12k` as words (see §1, VERIFY)

### 6.3 Price

- Per-word writer: `round(min × rate)` to `round(max × rate)`
- Per-article writer: the flat fee (Brenda's is a range of $100–120)
- Plus the expert fee unless the writer skips expert review
- An Open ticket with no expert yet: fitness +$50; nutrition +$20–50 (depends on the expert)
- Monthly spend recognition: an article counts in the month **it left Text** (writer) and the month it **left Review** (expert). **VERIFY** with Yuliia Horetska that this matches how invoices are actually paid
- Fixed monthly items: Colette $2,500, Polina $600

### 6.4 Review Flow timing rules (business days = Mon–Fri, Europe/Brussels)

| Rule | Threshold |
|---|---|
| Writer has no doc link after assignment | ≥ 5 business days since Author set or writer added to participants, whichever is later |
| Expert quiet | Review, no expert comment since the article link, link > 7 calendar days old, no chase from you in the last 7 days |
| No reply to your first note | ≥ 3 business days |
| Follow-up flag | ≥ 3 business days since your latest note. After a Slack DM, pause 3 business days |
| Auto-Slack | after your 2nd or 3rd note, never twice for the same ticket set on the same day (§3 bug) |
| Automation window | only act on trigger comments newer than `windowDays` (live value: **3**; default 14) |

"Article link" = the latest writer comment containing `https?://`. If there is no Author, use the latest Google Docs link (`^https://docs\.google\.com/document/`) from anyone.

### 6.5 Publishing

- Batch size **4** (current publisher capacity is about 5/day)
- An image link counts only when posted by Oksana or Karina and it is NOT a live-site link
- Live link = Yuliia's latest comment matching `^https?://(www\.)?betterme\.world/`. When it appears, the ticket can move to Published
- Default send time: next weekday 09:00 local. Scheduled sends must be 3 minutes to 119 days ahead

### 6.6 Slipped-pages triage levels

| Level | Scope |
|---|---|
| L0 Hold | No edits. Recently updated or traffic holding. Re-check in 4 weeks |
| L1 Targeted fix | 30–60 min, no rewrite: Key Takeaways after the intro, a 40–60 word direct answer under each question H2, 4–6 FAQs from live PAA, alt text, one internal link to and from the cluster. Change "Updated on" only if the answers changed |
| L2 Standard refresh | About half a day, same URL. L1, plus keyword in title/H1/first sentence, updated facts and sources, a table where numbers exist, trim filler, length near the top-5 median. New "Updated on" |
| L3 Full rewrite | Same URL. Writer + expert + Legal. Model article shape. Remove outcome/timeline/spot-reduction claims. Key Takeaways, PAA headings, 5 FAQs, tables, current sources. Never a new slug |
| NOSEO | Hits the Rejection Patterns. Touch only for a Legal compliance fix |

Position checks run at +2 and +4 weeks after a page's "Updated on" date changes.

### 6.7 Editorial / compliance rules (apply to any generated title, meta, pin)

- Never use the words **"best"** or **"personalized"** in titles, meta, or pin text (Volodymyr's rule, Sep 2026; 90 article titles and 200+ pins were cleaned up)
- No superlatives ("guaranteed", "#1"), no spot-reduction or shape-change promises, no outcome or timeline claims
- Never mention Headspace
- Blog taxonomy: leaf-level Category only (full list in the `blog-jira-ticket-creation` skill)
- Content cadence goal: at least 1 article per week in each of Nutrition, Diets, Fitness, Weight Loss, Mental Health
- Keyword KPI: 20–25 approved keywords per week. Scarce core topics (Wall Pilates, Chair Yoga, Calisthenics, Meal Plans, Fasting) have a volume floor of 20 instead of 50

---

## 7. Claude skills that already encode logic (reuse; don't reinvent)

These exist as the user's Claude skills. They are the source of truth for each rule. When a module needs the logic, port the rules from the skill text into code or prompts and cite the skill in a comment.

| Skill | Logic it holds |
|---|---|
| `betterme-keyword-research` | thresholds, install-intent scoring (HIGH/MEDIUM/LOW), DR ≤ 70 SERP check, duplicate check |
| `betterme-keyword-rejection-screen` | the 22 rejection categories, PASS/CAUTION/REJECT |
| `blog-jira-ticket-creation` | ticket summary/description format, meta title/description rules, ADF fields, quiz-link lookup sheet `17qXKwEt2eY-e06PCREkh_mziYeEdGpRRcRo1wRjJgzs` |
| `blog-notion-ticket-creation` | Notion card fields |
| `betterme-blog-budgeting`, `bm-budgeting` | monthly budget format for Yuliia Horetska |
| `betterme-article-update-finder` | update-candidate selection |
| `ymyl-audit`, `legal-check`, `fact-pack-builder`, `seo-onpage`, `serp-research`, `geo-ai-check` | draft QA |
| `pinterest-content-style`, `pinterest-pin-utm-tagger` | pins |

The Keyword Rejection Patterns reference guide lives in a Claude project ("Keyword Research + Updates"), not in a repo. Export it to `docs/rules/keyword-rejection-patterns.md` and keep it updated, because it changes over time.

---

## 8. Known issues found on 2026-10-17 (fix or decide before building on top)

1. **BP Review Flow automation is switched off.** The scheduled task (weekdays hourly 08:52–18:52) runs, but `settings/main.automation = false` in the artifact database, so every run exits immediately.
2. **Slipped Pages Tracker** checks stopped on 2026-10-13 (`meta/info.lastRun`). No scheduled task exists for them.
3. **October Updates Tracker** has only the 2026-10-13 baseline. The "every Monday" refresh doesn't exist.
4. **Duplicate Slack nudges** (see §3).
5. **Roster drift** across artifacts (see §2).
6. **Blog Spend Dashboard** has no month key, so it can only ever hold one month.
7. Two-Month Results report, **group D**: 14 tickets marked Published in Jira while the live page was unchanged. This needs a publishing QA check (covered in spec 04).
