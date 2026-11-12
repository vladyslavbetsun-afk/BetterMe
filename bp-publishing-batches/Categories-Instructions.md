# Main categories for BP Jira tickets: instructions

How the BP Publishing Batches dashboard shows each Jira ticket's **main blog category**, and how to add the same feature to another dashboard.

---

## 1. What it does

- Reads the category from each ticket's **Jira description**, from a line like:
  ```
  **Category:** Leg Workouts
  **Category:** Pilates; Somatic Exercises
  ```
- Maps that subcategory to one of the **six main categories** of the blog home page.
  - For example, Leg Workouts becomes **Workouts** and Wall Pilates becomes **Pilates**.
- Shows only the **main category** as a chip right after the ticket title. Hovering over the chip shows the original subcategory.
- **Shows categories only for tickets in the six main categories.** Tickets in other categories (Weight Loss and the rest) get no main-category chip and are hidden, with a "N outside the six categories hidden · Show them" switch.
- **Category filter:** a dropdown next to the search box lists the six, with counts.
- **Duplicate warning when building a batch:**
  - Two selected tickets with the same main category turn red, with a warning: "2 tickets in Workouts: BP-1, BP-2. Swap one for a different category."
  - When all selected tickets differ, the page says "All different categories".
  - In the ticket lists, a ticket whose main category is already selected says so, naming the ticket it clashes with.
- Batches show each ticket's main category. Each batch saves its tickets' subcategories, so it keeps showing them after archiving.

---

## 2. The six main categories and their subcategories

| Main category | Jira subcategories that count under it |
|---|---|
| **Diets** | Diets, Keto, Low Carb, Gluten Free, Vegan, Meal Plans, Meal Ideas, Healthy Eating, Food For Weight Loss, Recipes |
| **Fasting** | Fasting, Intermittent Fasting |
| **Pilates** | Pilates, Wall Pilates, Home Pilates, Somatic Pilates, Reformer Pilates |
| **Chair Yoga** | Chair Yoga, Yoga |
| **Workouts** | Workouts, Leg Workouts, Abs Workouts, Core Workouts, Back Workouts, Arm Workouts, Chest Workouts, Butt Workouts, Glute Workouts, Shoulder Workouts, Strength Training, HIIT Training, Cardio Workouts, Cardio, Walking, Running, Workout Plans, Workout Plans For Men, Stretching |
| **Calisthenics Workout** | Calisthenics, Calisthenics Workout, Calisthenics For Women, Calisthenics For Men, Bodyweight Training |

**Outside the six (no main category, hidden):** Weight Management, Weight Loss Tips, Somatic Exercises, Meditation, Health, Activewear, Therapy, Corporate Wellness, and tickets with no `Category` line. Today only BP-1760 and BP-1721 have no `Category` line.

**Rules**
- Matching is case-insensitive.
- A ticket with two subcategories in different main categories shows both. For example, "Calisthenics; Pilates" shows Calisthenics Workout and Pilates.
- To move a subcategory, edit the `MAIN_CATS` list (section 3, step 2). No Jira change is needed.

---

## 3. How to add it to another dashboard

### Step 1. Load the description from Jira
Add `description` to the fields you request, and ask for markdown:
```js
callTool("Atlassian", "searchJiraIssuesUsingJql", {
  cloudId: "657e24cd-f643-4482-aba5-7e848607df28",
  jql: 'project = BP AND status = "Ready"',
  fields: ["summary", "status", "comment", "description" /* , ...your other fields */],
  maxResults: 50,
  responseContentFormat: "markdown"
});
```

### Step 2. Paste these helpers
```js
// Plain text of a Jira rich-text (ADF) description, in case it doesn't come back as markdown
function adfText(n){
  if (!n || typeof n !== "object") return "";
  if (n.type === "text") return n.text || "";
  const inner = (n.content || []).map(adfText).join("");
  return ["paragraph","heading","listItem"].includes(n.type) ? inner + "\n" : inner;
}
// Subcategories from the "**Category:** ..." line of the description
function categoriesOf(desc){
  const d = typeof desc === "string" ? desc : adfText(desc);
  const m = d.match(/\*\*\s*Categor(?:y|ies)\s*:?\s*\*\*\s*:?\s*([^\n]*)/i) || d.match(/^\s*Categor(?:y|ies)\s*:\s*([^\n]*)/im);
  if (!m) return [];
  return m[1].replace(/\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/[*_`]/g, "").split(/[;,|]/).map(x => x.trim()).filter(Boolean);
}

// The six main categories on the blog home page and the Jira subcategories under each
const MAIN_CATS = {
  "Diets": ["Diets","Keto","Low Carb","Gluten Free","Vegan","Meal Plans","Meal Ideas","Healthy Eating","Food For Weight Loss","Recipes"],
  "Fasting": ["Fasting","Intermittent Fasting"],
  "Pilates": ["Pilates","Wall Pilates","Home Pilates","Somatic Pilates","Reformer Pilates"],
  "Chair Yoga": ["Chair Yoga","Yoga"],
  "Workouts": ["Workouts","Leg Workouts","Abs Workouts","Core Workouts","Back Workouts","Arm Workouts","Chest Workouts","Butt Workouts","Glute Workouts","Shoulder Workouts","Strength Training","HIIT Training","Cardio Workouts","Cardio","Walking","Running","Workout Plans","Workout Plans For Men","Stretching"],
  "Calisthenics Workout": ["Calisthenics","Calisthenics Workout","Calisthenics For Women","Calisthenics For Men","Bodyweight Training"]
};
const MAIN_ORDER = Object.keys(MAIN_CATS);
const SUB_TO_MAIN = {};
for (const [m, subs] of Object.entries(MAIN_CATS)) subs.forEach(x => SUB_TO_MAIN[x.toLowerCase()] = m);

// Subcategories -> main categories (deduplicated, in home-page order)
const toMains = subs => [...new Set((subs || []).map(x => SUB_TO_MAIN[String(x).toLowerCase()]).filter(Boolean))]
  .sort((a, b) => MAIN_ORDER.indexOf(a) - MAIN_ORDER.indexOf(b));
```

### Step 3. Store subcategories on each ticket
Keep the **subcategories** on the ticket, not the main category. That way a mapping change applies straight away, without reloading Jira.
```js
ticket.cats = categoriesOf(issue.fields.description);   // e.g. ["Leg Workouts"]
```
Work out the main category when you draw the page:
```js
const mainsOf = t => { const m = t && t.cats ? toMains(t.cats) : []; return m.length ? m : null; };
const inMain  = t => !t || !t.cats || !!mainsOf(t);   // true = show the ticket
```

### Step 4. Show the chip next to the title
```js
function catChips(t, dupSet){
  const cs = mainsOf(t);
  if (!t || !t.cats) return `<span class="chip">Category: click Refresh</span>`;
  if (!cs) return t.cats.length
    ? `<span class="chip warn" title="Not one of the six main categories">${esc(t.cats.join(", "))}</span>`
    : `<span class="chip warn">No category in description</span>`;
  return cs.map(c => `<span class="chip cat${dupSet && dupSet.has(c) ? " dup" : ""}" title="${esc(t.cats.join(", "))}">${esc(c)}</span>`).join("");
}
// in the ticket row, right after the title:
// `${keyLink(t)} <span class="title">${esc(t.title)}</span> ${catChips(t)}`
```
CSS (use your own color tokens):
```css
.chip.cat{background:var(--accent-soft);color:var(--accent)}
.chip.cat.dup{background:var(--bad-soft);color:var(--bad);font-weight:600}
```

### Step 5. Hide tickets outside the six categories
```js
let showOther = false;   // the "Show them" switch
const visible = tickets.filter(t => showOther || inMain(t));
const hiddenCount = tickets.filter(t => !inMain(t)).length;
// bar text: `${hiddenCount} outside the six categories hidden` + a Show them / Hide them button
```

### Step 6. Category filter
```js
// dropdown: "All categories" + one option per MAIN_ORDER entry with its count
const shown = visible.filter(t => !selectedCat || (mainsOf(t) || []).includes(selectedCat));
```

### Step 7. Duplicate warning when picking tickets
```js
// selected = array of ticket keys being grouped together
const selCats = () => {
  const m = new Map();
  selected.forEach(k => (mainsOf(tickets[k]) || []).forEach(c => m.set(c, (m.get(c) || []).concat(k))));
  return m;
};
// For each category with 2+ keys, show:
//   "2 tickets in Workouts: BP-1, BP-2. Swap one for a different category."
// If none repeat, show: "All different categories."
// In the ticket lists, for an unselected ticket whose main category is already in selCats(),
// show "<Category> already in the new batch (<key>)" and pass that category as dupSet to catChips.
```

### Step 8. Save categories with a batch (optional)
When a batch is created, save each ticket's subcategories, so archived batches still show them:
```js
batch.cats = Object.fromEntries(selected.map(k => [k, tickets[k].cats || []]));
// show later with: toMains(batch.cats[key] || tickets[key]?.cats)
```

---

## 4. Checklist

1. `description` is in the Jira fields and `responseContentFormat: "markdown"` is set.
2. `ticket.cats` is filled with `categoriesOf(...)` for every loaded ticket.
3. The main-category chip shows next to the title in every ticket list.
4. Tickets outside the six categories are hidden, with a Show them switch.
5. The category filter lists the six main categories.
6. Duplicate main categories are flagged when grouping tickets.
7. Refresh once after deploying, so tickets saved earlier get their categories.
