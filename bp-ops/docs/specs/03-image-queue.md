# 03 — Image Queue

> **Build target:** a module of the BP Ops app (`/images`, see spec 05).
> **Read first:** `00-shared-reference.md` §1, §2, §6.5.
> **Problem:** design work is tracked nowhere. Publishing Batches infers "has images" only from comment links posted by Oksana or Karina, so the first time anyone notices a missing image is when a Ready ticket can't go into a batch. Pinterest pins (a weekly task in every daily report) aren't tracked at all.

## 1. Goal

Make every image need visible **before** it blocks publishing:

- Every article that will need images has a request made by the time it enters **Review**, so images are ready by **Ready**.
- Pinterest pin batches are requested and tracked weekly.
- Publishing Batches pulls only tickets whose images are delivered. The "Ready without images" count trends to zero.

## 2. Users

| User | Does |
|---|---|
| Vladyslav | creates and approves requests, sees blockers |
| Oksana Pidlisna, Karina Sorvachova (designers) | see their queue, mark delivered (or deliver by posting the link in Jira, which is detected automatically) |
| Yuliia Koreniuk | sees which Ready tickets are image-complete (read-only) |

**Legal-gate framing (important):** this module tracks **requests and tickets**, not designers. It shows how long each *request* has waited. It must **not** show per-designer speed, ranking or productivity stats. Aggregates are queue-level only. See spec 05 §4.

## 3. What counts as "needs images"

| Ticket type | Default image set | Rule |
|---|---|---|
| New article | 1 featured image + inline images (default 2) | every `new` ticket |
| Update | **VERIFY** with Vladyslav. Default: featured image only if the old one breaks the white-font or banned-word rules; otherwise none | `, update` in the summary |
| Pinterest pins | N pins per published article (default 3) | a weekly batch (Monday) built from articles published in the past 7 days |
| Banners (Personalized/Customized), ad hoc | free-form request | manual |

Keep these defaults in `settings.image_rules` so they can be edited in the UI.

## 4. Detection (from Jira, automatic)

A request counts as **delivered** when either:

1. a comment by Oksana or Karina (by accountId) contains a link that is NOT a betterme.world live link and NOT a Google Doc. Accept Figma, Google Drive, Canva and image-host links; store the URL; or
2. a designer clicks **Mark delivered** in the app and pastes the link.

Also detect **existing images** on tickets that predate this module, so the first load doesn't flag 100 false "needs image" items. For any ticket in Review, Proofreading or Ready, an image-link comment from Oksana or Karina counts as delivered, with `source = backfill`.

## 5. Request flow

```
NEEDED (auto when a ticket enters Text or Review and no request exists)
  └─▶ REQUESTED (Vladyslav clicks "Request" → brief + channel)
        └─▶ IN_PROGRESS (designer clicks "Started", optional)
              └─▶ DELIVERED (link detected or pasted)
                    └─▶ APPROVED (Vladyslav ✓) or CHANGES_REQUESTED (→ back to IN_PROGRESS with a note)
CANCELLED (ticket cancelled or images not needed)
```

**Request brief** (pre-filled, editable): ticket key and title, article Google Doc link (from the writer's latest comment), category, image set (featured / inline × n / pins × n), style notes (default text from `settings.image_style_notes`: white font on pins, no "best"/"personalized" text on images), due date (default = the date the ticket is projected to reach Ready, see §6, minus 1 business day).

**How the request reaches the designer:** **VERIFY** the current habit with Vladyslav (Jira comment? Slack DM? a sheet?). Implement two channels and choose the default in settings:

- **Jira comment:** an ADF mention of the designer plus the brief; adds the designer to Request participants. This is a write, so it needs the Jira write path (spec 05 §3). Without that path the app shows a "Copy comment" button.
- **Slack DM:** a draft message with the brief and an "Open DM" deep link. Sending happens from Vladyslav's own Slack unless an approved bot path exists (spec 05 §3).

**Weekly pin batch:** every Monday 09:00 the module builds a `pin_batch` of the past week's published articles (from the Performance module's `articles`, cohort new or update). It drafts pin titles and descriptions following the `pinterest-content-style` skill rules and UTM-tagged links following `pinterest-pin-utm-tagger`, and puts them in REQUESTED for review. The current pin sheet (`1b_-xzpFMVMp3UUw_3H3-bMf10UDkr2s5dtGVSrDx-4c`) can be exported to and imported from.

## 6. Projected "needed by" date

`needed_by` = the date the ticket is expected to reach Ready. Use the median business days per stage over the last 90 days (computed by spec 04, table `stage_durations`):

```
needed_by = today + Σ median_remaining_stage_days(current_status → Ready)
```

Show it as a date with a small "≈" marker. Requests not delivered within 2 business days of `needed_by` turn amber; past it, red.

## 7. UI

### 7.1 Queue (default view)

- Kanban columns: Needed · Requested · In progress · Delivered (awaiting ✓) · Done this week.
- Card: ticket key/title, request type chips (Featured · Inline ×2 · Pins ×3), days waiting (business days), needed-by date with colour, assignee avatar, link to the article doc.
- Filters: assignee, type (article / pins / banner), status of the underlying ticket.
- Top bar counters (queue-level only):
  - **Ready without images** (red if > 0; links to those tickets)
  - requests due this week
  - pins requested vs delivered this week

### 7.2 Designer view (`/images?me=1`)

Shows only the signed-in designer's open requests, oldest first, with large "Started", "Mark delivered" (paste link) and "Can't do — reason" buttons. The view must work well on a laptop at 1280px, with no dense tables.

### 7.3 Ticket badge API

`GET /api/images/status?keys=BP-1,BP-2` → `{key: "complete"|"pending"|"missing"|"not_needed"}`. Publishing Batches (and spec 04) use this instead of re-implementing the comment rule.

## 8. Data model

```sql
image_requests(id bigserial primary key, jira_key text, kind text check (kind in ('featured','inline','pins','banner','other')),
  quantity int, brief jsonb, assignee_id text, state text, requested_by text, requested_at timestamptz,
  needed_by date, started_at timestamptz, delivered_at timestamptz, delivered_url text,
  approved_at timestamptz, source text check (source in ('app','jira_detect','backfill')),
  unique(jira_key, kind))
image_request_events(id bigserial, request_id bigint, from_state text, to_state text, by text, at timestamptz, note text)
pin_batches(id bigserial, week date unique, created_at timestamptz, items jsonb, state text)
```

## 9. Jobs

| Job | Schedule | Does |
|---|---|---|
| `scan_image_links` | every 15 min, 08:00–19:00 weekdays | reads comments on BP tickets in Text, Review, Proofreading and Ready (updated in the last 2 days). Detects deliveries; creates NEEDED rows for tickets entering Text or Review |
| `build_pin_batch` | Mon 09:00 | §5 |
| `image_due_digest` | weekdays 09:30 | an optional message to Vladyslav (in-app notification, or a Slack draft) listing amber and red requests |

## 10. Acceptance criteria

- [ ] On first load, tickets with existing Oksana or Karina image links show as delivered (backfill), not NEEDED.
- [ ] A new ticket entering Review with no request appears in Needed within 15 minutes.
- [ ] Posting an image link as Oksana on a ticket moves its request to Delivered on the next scan.
- [ ] The "Ready without images" counter matches what Publishing Batches shows today.
- [ ] No view shows per-designer averages, speed or rankings.
- [ ] `GET /api/images/status` responds in under 200 ms for 50 keys.

## 11. Open questions

1. How are designers asked for images today (Jira, Slack, sheet)? Who is Karina: a designer or a content manager?
2. Do updates need new images by default?
3. Pins per article, and who designs pins (Vladyslav? Oksana? Canva templates?)
4. Should designers sign in to the app at all, or only receive requests by Jira or Slack?
