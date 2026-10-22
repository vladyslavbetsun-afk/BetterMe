# BP Review Flow: Dashboard Guide

A live dashboard for the Jira **Blog Project (BP)** that tracks every article ticket by its **comments** (not by status changes), tells you what needs your attention, runs the routine Jira steps for you with one click, and handles follow-ups with writers and experts in Jira and Slack.

- **Dashboard:** https://claude.ai/artifact/DhWgTXa9SMjqE5w82KkzdK (private to you until you share it)
- **Data sources:** Jira (Atlassian connector, site **newsiteam**) and your Slack DMs from the Jira Cloud app
- **Source code:** `bp-review-flow/index.html` in the BetterMe repository

---

## 1. Before you start

1. Open the dashboard in claude.ai while signed in.
2. When asked, **allow Atlassian and Slack** for the page. You can change this later from the page's **Permissions** menu.
3. The Atlassian connector must have access to the **newsiteam** Jira site. If Jira shows an access error, see [Troubleshooting](#14-troubleshooting).

The page refreshes itself every 10 minutes while it's open. Each section fills in as soon as its data arrives, so a slow connector doesn't block the rest.

---

## 2. The workflow the dashboard follows

The ticket statuses go in this order: **Open → Text → Review → Proofreading → Ready**. The dashboard tracks tickets from **Text** onwards; tickets in Open are not shown.

The dashboard reads the comments to work out where every ticket is:

| # | What happens in the ticket | What the dashboard offers |
|---|---|---|
| 1 | Ticket is in **Text** and the **writer** posts a comment with the article link | Sets the **Expert** field, adds the expert to **Request participants**, moves the ticket to **Review** |
| 2 | Ticket is in **Review** and the **expert** comments | Moves the ticket to **Proofreading** and posts an internal note: "@Writer Hi. Please address the comments. Thanks." |
| 2b | Expert commented and you already posted your note, but the ticket is still in Review | Moves the ticket to **Proofreading** |
| 3 | Ticket is in **Proofreading** and the writer replies after your note | Sets **Proofreader = Tim Jones** and adds him to **Request participants** |
| 4 | **Tim Jones** comments after your note (proofreading done) | Moves the ticket to **Ready** |

### How your notes are recognised

The dashboard doesn't look for exact wording.
- **Your note:** the first comment you post after the expert's comment counts as your note, whatever it says ("Please address comments/edits", "Please address the edits offered by Garett", and so on).
- **Follow-up notes:** your comments after that, with no reply from the writer in between, count as your **2nd, 3rd and later notes**.

### Skipping fields that are already set

If you've already set the Expert or Proofreader in Jira by hand, the dashboard skips that field and only does what's left. For example, the button reads "Move to Review (Carter Lee already set)".

---

## 3. Experts and categories

| Category | Experts |
|---|---|
| Fitness / Exercise | Carter Lee, Garett Reid |
| Nutrition / Diet | Angelica Galvan, Maria Eugenia Corrarello (maria.eugenia.coaching) |

- The **category is read from the ticket title** using keywords. For example, "workout", "yoga", "squat", "pilates" → Fitness; "diet", "meal", "snack", "drink", "good for you" → Nutrition.
- When both experts in a category fit, the one with **fewer tickets in Review** is picked.
- If the title is unclear, the ticket is marked **Category?** and waits for you to choose Fitness or Nutrition from the dropdown.
- You can also pick the expert yourself from the **Expert** dropdown. Both choices are remembered.

---

## 4. Whose comments are ignored, and which tickets are hidden

- Comments and Slack notifications from **Oksana Pidlisna** and **Yuliia Koreniuk** are ignored everywhere: they don't count as activity, replies or triggers.
- Tickets in **Open** are not shown anywhere on the dashboard (no lists, counts or flags), whatever their comments. A ticket appears as soon as it moves to **Text**.
- **Excluded** tickets are hidden everywhere (see [section 12](#12-excluding-tickets)).

---

## 5. Page layout

From top to bottom:

1. **Top bar:** ticket scope (**My tickets** = Managers is you, or **All BP**), the **Refresh** button and the last update time. While loading it shows which source is still pending, for example "Loading Slack…".
2. **Automation strip:** time window, note type and **Run automation now** (see [section 7](#7-run-automation-now)).
3. **Count tiles:** Your move, Writing (Text), With expert, Writer fixing, With proofreader, No reply 3+ business days, Follow-ups flagged, Expert silent 7d+, No document 5+ business days. Click a tile to jump to that section.
4. **Left column:**
   - **Your move:** tickets waiting on you, with action buttons
   - **No reply to your comment (3+ business days)**
   - **Follow-ups counting down**
   - **Flagged follow-ups**
   - **No document 5+ business days after assigning**
   - **Experts with no update (7+ days)**
   - **Waiting on others:** everything else, with how long it has been waiting
5. **Right column:**
   - **Jira → Slack today:** your Jira DMs from today
   - **Action log**
   - **Excluded tickets**

---

## 6. "Your move": the action queue

Each card shows:
- the ticket key (click to open it in Jira) and title
- category, status and stage
- the writer, expert and proofreader
- the comment that triggered the step
- any warnings

**Buttons on a card:**

- **One button per step**, for example **Move to Review + add Carter Lee**, **Move to Proofreading**, **Post note tagging Nderitu Munuhe**, **Add Tim Jones as proofreader**, **Move to Ready**
- **Do all steps:** runs every step for that ticket in order
- **Category** and **Expert** dropdowns (tickets in Text)
- **Straight to Ready** (see [section 8](#8-straight-to-ready))
- **Exclude:** stop tracking the ticket

**Labels:**

- **Auto:** **Run automation now** will do this ticket
- **Manual:** it waits for your click. The reason is shown next to the label, for example "Trigger older than 14 days", "Has a warning" or "You aren't in Managers".

**Safety:** before any step runs, the dashboard re-reads the ticket from Jira. If something changed since the last refresh, it does nothing and logs why, for example "status is now Ready (was Proofreading)".

**Warnings you may see:**

- "Pick a category or expert": the title doesn't clearly read as Fitness or Nutrition
- "No Author on ticket": the note can't tag a writer until the Author field is set
- "Expert's last comment looks like a question": reply manually
- "Ticket is in Proofreading but has no expert comment": check it manually

A Proofreading ticket where your note is missing shows **Post note tagging [writer]**. That's always manual.

---

## 7. Run automation now

| Setting | What it does |
|---|---|
| **Act on comments newer than** | 3, 7, 14 or 30 days. Tickets with older triggers are Manual. |
| **Note to writer** | **Internal (Service Desk Team)** = visible to agents only, or **Standard comment** |
| **Run automation now** | Refreshes from Jira, then runs every step on the tickets marked **Auto**, one ticket at a time |

**What it will do:** only the routine workflow steps from [section 2](#2-the-workflow-the-dashboard-follows), and only on tickets where **all** of these are true:

- you are in the ticket's **Managers** field
- the triggering comment is inside the time window
- the ticket has no warnings and isn't excluded
- for expert assignment, the category or expert is clear

**What it never does:** send follow-up notes, Slack messages or **Straight to Ready**. Those are always your click (automatic Slack after a 2nd or 3rd note is a separate per-ticket option, see [section 9](#9-follow-ups-with-writers)).

**Nothing runs in the background:** there is no on/off switch. The workflow steps run only when you click a step button or **Run automation now**.

Every action appears in the **Action log**.

---

## 8. Straight to Ready

An extra, **manual-only** button for skipping the review steps.

- **Where it appears:** on every ticket in **Text, Review or Proofreading** once the writer has posted a comment with the document link.
- **What it does:** moves the ticket through each status in order, **Text → Review → Proofreading → Ready**. A ticket already in Review or Proofreading starts from where it is.
- **Confirmation:** it asks "Send BP-xxxx to Ready? Yes, to Ready / Cancel" first.
- **Safety:** it re-reads the ticket first and stops if the ticket is no longer in Text, Review or Proofreading.
- **Action log:** the full path is recorded, for example "BP-1607: sent straight to Ready (Text → Review → Proofreading → Ready)". If Jira refuses a step, the log says where it stopped.
- **Automation:** **Run automation now** never presses it.

---

## 9. Follow-ups with writers

All "business days" below count **Monday to Friday only**. Weekends don't count.

### Step 1: "No reply to your comment (3+ business days)"

Lists tickets where **your 1st comment** is still the latest one and has had no reply for **3 or more business days**.

- **Post 2nd note to [writer] (Jira + Slack):** posts the internal note "@Writer Hi. Any news on the edits?" tagging the person you tagged last time (or the Author). If Auto-Slack is on for the ticket, it also sends the writer a Slack message.
- **Ask [expert] for news (Jira):** shown instead when the person you tagged last time was an expert. The note says "Hi. Any news on the ticket?" and no Slack message is sent.
- A small "Slacked X ago" note shows when the writer was last messaged.

### Step 2: "Follow-ups counting down"

Tickets with your **2nd or later note** to the writer, grouped by writer.

- Each ticket shows which note it is ("2nd note", "3rd note") and a countdown: **flags in 2 business days**, then **flags in 1 business day**.
- The count runs **from your latest note**. Posting a 3rd note restarts it.
- After you Slack a writer about a ticket, it pauses for **3 business days** ("Slacked X ago · back in N business days").
- Any reply from the writer in Jira removes the ticket.

### Step 3: "Flagged follow-ups"

Tickets where the writer hasn't replied **3 business days after your 2nd or later note**, or **3 business days after your Slack message**. One card per writer:

- **Slack [name] only:** shows a preview first; nothing is sent until you click **Send**.
- **Post next note on all N (+ one Slack):** posts "@Writer Hi. Any news on the edits?" on each flagged ticket. If any of them just got its 2nd or 3rd note with Auto-Slack on, one Slack message covers all of them.

### Auto-Slack on the 2nd and 3rd note

Every ticket in the follow-up lists has an **Auto-Slack writer on 2nd & 3rd note** checkbox. It's **on by default** and you can untick it per ticket.

- **Posted from the dashboard:** when you post a 2nd or 3rd note, the Slack message goes out right away.
- **Posted by hand in Jira:** the dashboard sends the Slack message at its next refresh, while the page is open. If several of the writer's tickets need it, they go in one message.
- **Older notes:** notes posted before this feature was switched on (Oct 11) never trigger a Slack message.
- **4th and later notes:** never send Slack automatically. The buttons still work.
- Automatic messages appear in the Action log marked "automatic".

### What the follow-up Slack messages look like

Every message lists all of the writer's tickets that need attention, with links:

> Hi Nderitu, hope you're doing well! Just following up on the edits for these tickets:
> - BP-1575 calisthenics for women
> - BP-1574 free 28 day chair yoga for seniors
>
> Could you share an update on where they stand when you get a chance? Thank you!

If you already messaged the writer since the follow-up, it says "Just checking in again on the edits for these tickets" instead.

---

## 10. Writers who haven't delivered: "No document 5+ business days after assigning"

A ticket is flagged when **all** of these are true:

- it is in **Text**
- the writer is set as **Author** and added to **Request participants**. The dashboard reads both times from the ticket's history and counts from the later one.
- the writer hasn't posted their document link within **5 business days** of that
- you haven't commented on the ticket since

The section is grouped by writer, and each ticket shows the date you assigned it and how many business days have passed.

- **Ask for status (Jira + Slack):** posts the internal note "@Writer Hi. What's the status on this one?" and sends the writer the same message on Slack, with the ticket link:
  > Hi Jeremy. What's the status on this one?
  > BP-1618 7 min workout calories (link)
- **Ask on all N in Jira + one Slack:** for a writer with several late tickets. It posts the note on each one and sends one Slack message listing them all.

After you ask, the ticket moves into the normal follow-up flow ([section 9](#9-follow-ups-with-writers)).

---

## 11. Follow-ups with experts: "Experts with no update (7+ days)"

Lists tickets in **Review** where the writer's article link is more than 7 days old, the expert hasn't commented, and you haven't commented in the last 7 days.

- **Ask [expert] for news:** posts the internal note "@Expert Hi. Any news on the ticket?" in Jira only; no Slack message is sent.
- After you send it, the ticket leaves the list for 7 days.

---

## 12. Excluding tickets

Every ticket has an **Exclude** button (or ×). An excluded ticket is:

- hidden from every section, count and the Slack feed
- never touched by **Run automation now** or any automatic Slack message

The **Excluded tickets** panel lists them, with **Track again** to bring one back.

---

## 13. Jira → Slack today, the Action log and Slack links

### Jira → Slack today

Shows only the notifications the **Jira Cloud** app sent to your Slack DMs **today** (since midnight), newest first. Each one shows the ticket key, who did what, the comment text and the ticket's current stage.

- **Delete** removes a notification from the dashboard only. It stays in Slack and nothing changes in Jira, and it stays hidden after a refresh.
- The header shows how many came in today and how many you removed.
- Notifications from Oksana and Yuliia, and for excluded tickets, are not shown.

### Action log

Records everything done from the dashboard: clicks, **Run automation now** steps, Jira notes, Slack messages (including automatic ones) and failures (in red, with the reason).

- **Clear log** deletes all entries after a confirmation. Slack links, the record of Slack messages sent, exclusions and settings are kept.
- When a writer has flagged follow-ups, a **Slack [name] about N tickets** button appears under the latest log line about them.

### Linking writers to Slack

Writers are matched to their Slack accounts once and remembered. Already linked:

| Jira name | Slack name |
|---|---|
| ZINDZY GRACIA | Zindzy Gracia |
| Evelyn Chalicha | Eve Chalicha |
| srijoni.guptaroy | Srijoni |
| Anoshia Riaz | Anoshia Riaz |
| Nderitu Munuhe | Nderitu Munuhe |
| Jeremy Mukhwana | Jeremy Mukhwana |
| Clare Kamau | Clare |

For a new writer, click **Find on Slack**. It searches by surname and shows the matches with their email, so you can pick the right person; **Change** fixes a wrong match. Until a writer is linked, the Jira note still goes out, but the Slack message is skipped and the log says so.

---

## 14. Troubleshooting

| What you see | What to do |
|---|---|
| A 403 "The app is not installed on this instance" in the log, or Jira refusing field changes | In claude.ai go to **Settings → Connectors → Atlassian**, disconnect and connect again, and choose the **newsiteam** site. Then reload the dashboard. If it still fails, a Jira admin must allow the Atlassian MCP app on the site (Atlassian admin console → connected apps). |
| "Reconnect Atlassian (or Slack) in claude.ai Settings → Connectors" | The connector sign-in expired. Reconnect it, then reload or click Refresh. |
| "Ticket changed since the last refresh (…), nothing was done" | Not an error: the ticket changed in Jira (for example someone already moved it). Review it and click again if needed. |
| Stuck on "Loading Slack…" or "Loading Jira…" | Wait up to 60–90 seconds; the request then stops with a message. Click **Refresh**. If it keeps happening, open the page's **Permissions** menu and allow Atlassian and Slack. |
| A writer didn't get a Slack message | Check the writer is linked (**Find on Slack**) and that **Auto-Slack** is ticked on that ticket. |
| A ticket you expected isn't shown | Check the scope (**My tickets** vs **All BP**), the **Excluded tickets** panel, whether the latest comment is from Oksana or Yuliia (ignored), and whether the ticket is still in **Open** (not shown). |
| The internal note isn't visible to the writer | Switch **Note to writer** to **Standard comment**. The connector can't tick Jira's own "Internal note" box; "Internal" restricts the comment to the Service Desk Team role. |

### Known limits

- Jira **emoji reactions** can't be read, so only reply comments count as answers.
- Comments can't be deleted in Jira from the dashboard; **Delete** in the Slack feed only hides the notification on the dashboard.
- Automatic Slack messages after a note posted by hand in Jira are only sent **while the dashboard is open**.
- Business days are counted in your computer's local time zone.
- The dashboard reads up to 600 tickets per scope.
- The dashboard is private to you. Others can't open it until you share it from the page's Share menu, and they would need their own Atlassian and Slack connectors.
- The scheduled task "BP Review Flow automation" still exists, but it does nothing: it has no Jira access, and it only acts when an automation switch is on, which the dashboard no longer has. It can be deleted.

---

## 15. Quick reference

### Notes and messages the dashboard sends

| When | Where | Text |
|---|---|---|
| Expert commented | Jira internal note | "@Writer Hi. Please address the comments. Thanks." |
| Your comment unanswered 3+ business days (writer) | Jira internal note (+ Slack if Auto-Slack is on) | "@Writer Hi. Any news on the edits?" + Slack message listing all their tickets |
| Follow-up flagged | Jira internal note and/or Slack | "@Writer Hi. Any news on the edits?" / Slack message listing all their tickets |
| No document 5+ business days after assigning | Jira internal note + Slack | "@Writer Hi. What's the status on this one?" + "Hi [Name]. What's the status on this one?" with the ticket link |
| Expert silent 7+ days | Jira internal note | "@Expert Hi. Any news on the ticket?" |

### Time thresholds

| Rule | Threshold |
|---|---|
| Your 1st comment counts as unanswered | 3 business days |
| Follow-up (2nd or later note) is flagged | 3 business days after your latest note |
| Ticket paused after you Slack the writer | 3 business days |
| Writer counts as late on the document | 5 business days after being set as Author and added to Request participants |
| Expert counts as silent | 7 days after the writer's article link |
| Run automation now acts on triggers no older than | 14 days (adjustable: 3, 7, 14, 30) |

### Jira fields used

| Field | ID |
|---|---|
| Author (writer) | customfield_11710 |
| Expert | customfield_11711 |
| Proofreader | customfield_11712 |
| Request participants | customfield_11208 |
| Managers | customfield_11709 |

### Status moves

| Move | Transition ID |
|---|---|
| Text → Review ("to review") | 21 |
| Review → Proofreading ("to proofreading") | 31 |
| Proofreading → Ready ("to ready") | 41 |

People: Tim Jones is the proofreader. The Jira Cloud app's DMs to you arrive in your Slack DM with the Jira bot.
