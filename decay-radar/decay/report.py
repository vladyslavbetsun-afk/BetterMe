"""§9 outputs: decay-report.html (same layout as the /decay page), CSV, Slack text, terminal table."""
from __future__ import annotations

import csv
import html
import io
import json
from datetime import date, datetime

from .config import LEVEL_NAMES
from .notion import iso_week

LEVELS = ["L0", "L1", "L2", "L3", "NOSEO"]


def runs_for_report(store, run_ids: list[int] | None = None) -> list[dict]:
    if run_ids:
        marks = ",".join("?" for _ in run_ids)
        return store.query(f"select * from decay_runs where id in ({marks}) order by id", run_ids)
    last = store.latest_run()
    if not last:
        return []
    # The latest run per country for the latest report date (re-runs replace earlier ones).
    latest = {}
    for r in store.query("select * from decay_runs where date=? order by id desc", [last["date"]]):
        latest.setdefault(r["country"], r)
    return sorted(latest.values(), key=lambda r: r["id"])


def collect(cfg, store, run_ids: list[int] | None = None) -> dict:
    runs = runs_for_report(store, run_ids)
    rows = []
    for r in runs:
        for ri in store.query("select url, payload from decay_run_items where run_id=?", [r["id"]]):
            p = ri["payload"]
            item = store.item(ri["url"]) or {}
            level = item.get("level_override") or p["level"]
            history = store.query(
                "select r.date as date, s.now as now from decay_signals s join decay_runs r on r.id=s.run_id "
                "where s.url=? and s.keyword=? order by r.id", [ri["url"], p["page"]["main_keyword"]])
            followups = store.query("select label, due_date, checked_at, outcome, results from decay_followups where url=? "
                                    "order by due_date", [ri["url"]])
            rows.append({
                "run_id": r["id"], "country": r["country"], "url": ri["url"], "level": level,
                "computed_level": p["level"], "override_reason": item.get("override_reason"),
                "state": item.get("state", p.get("state")), "why": p["why"], "checklist": p["checklist"],
                "page": p["page"], "audit": p["audit"], "screen": p["screen"], "priority": item.get("priority", p["priority"]),
                "flags": p["flags"], "notes": p["notes"], "intent": p["intent"], "open_ticket": p.get("open_ticket"),
                "recent_ticket": p.get("recent_ticket"), "open_card": p.get("open_card"),
                "notion_url": item.get("notion_url"), "history": history, "followups": followups,
                "excluded_reason": item.get("excluded_reason"),
            })
    rows.sort(key=lambda x: -(x["priority"] or 0))
    week = iso_week(cfg.today)
    created = store.one("select count(*) as n from decay_cards where iso_week=? and notion_url is not null", [week])["n"]
    counts = {lvl: sum(1 for x in rows if x["level"] == lvl) for lvl in LEVELS}
    return {
        "runs": runs, "rows": rows, "counts": counts,
        "proposed": sum(1 for x in rows if x["state"] == "proposed"),
        "cap": cfg["weekly_card_cap"], "cards_created": created,
        "traffic_at_risk": sum(x["page"]["traffic_lost"] for x in rows),
        "units": sum(r["units_used"] or 0 for r in runs),
        "aborted": [r for r in runs if r["status"] in ("aborted", "error")],
    }


def slack_text(cfg, data: dict) -> str:
    d = cfg.today.strftime("%b %-d")
    parts = [f"{data['counts'][l]} {l}" for l in LEVELS if data["counts"][l]]
    text = (f"Decay radar ({d}): {len(data['rows'])} pages lost top-3 · {', '.join(parts) or 'no pages'} · "
            f"est. {data['traffic_at_risk']:,} visits/mo at risk · {data['cards_created']} Notion cards created.")
    if data["aborted"]:
        text += " ⚠ " + "; ".join(f"{r['country'].upper()} run {r['status']}: {r['error']}" for r in data["aborted"])
    return text


def fmt_pos(p):
    return "lost" if p is None else f"#{p}"


def terminal_table(data: dict, limit: int = 60) -> str:
    out = io.StringIO()
    hdr = f"{'#':>3}  {'level':6} {'state':10} {'prio':>7} {'lost':>5} {'kws':>3}  {'was→now':10} {'main keyword':32} url"
    out.write(hdr + "\n" + "-" * len(hdr) + "\n")
    for i, r in enumerate(data["rows"][:limit], 1):
        p = r["page"]
        wn = f"{fmt_pos(p.get('main_was'))}→{fmt_pos(p.get('main_now'))}"
        out.write(f"{i:>3}  {r['level']:6} {r['state'] or '':10} {r['priority'] or 0:>7.1f} {p['traffic_lost']:>5} "
                  f"{p['lost_top3_count']:>3}  {wn:10} {p['main_keyword'][:32]:32} {r['url']}\n")
    for r in data["aborted"]:
        out.write(f"\n!! {r['country'].upper()} run {r['id']} {r['status']}: {r['error']}\n")
    return out.getvalue()


def detail_text(r: dict) -> str:
    a, p = r["audit"], r["page"]
    lines = [r["url"], f"Level {r['level']} {LEVEL_NAMES[r['level']]} · state {r['state']} · priority {r['priority']}",
             f"Why: {r['why']}", "Checklist:"] + [f"  [ ] {c}" for c in r["checklist"]]
    lines.append("Lost keywords:")
    for k in p["lost_keywords"]:
        lines.append(f"  {k['kw']} (vol {k['vol']}) {fmt_pos(k['was'])} → {fmt_pos(k['now'])}, "
                     f"traffic {k['traffic_prev']} → {k['traffic_now']} [{k['kind']}]")
    lines.append(f"Audit: updated {a.get('updated_on')}, {a.get('word_count')} words, FAQs {a.get('faq_count')}, "
                 f"Key Takeaways {'yes' if a.get('has_key_takeaways') else 'no'}, tables {a.get('table_count')}, "
                 f"competitor median {a.get('median_competitor_words')} ({a.get('competitor_check')})")
    lines.append(f"Screen: {r['screen']['verdict']} " + "; ".join(
        f"#{m['category']} {m['name']} ({m['note']})" for m in r["screen"]["matches"]))
    lines.append(f"Jira: open {r['open_ticket'] or '-'}, recent {r['recent_ticket'] or '-'} · Notion: {r['open_card'] or r['notion_url'] or '-'}")
    if r["notes"]:
        lines.append("Notes: " + "; ".join(r["notes"]))
    return "\n".join(lines)


CSV_FIELDS = ["url", "level", "state", "priority", "main_keyword", "was", "now", "lost_top3_count", "traffic_lost",
              "updated_on", "flags", "why", "checklist", "notion_url", "jira"]


def to_csv(data: dict) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    w.writeheader()
    for r in data["rows"]:
        p = r["page"]
        w.writerow({
            "url": r["url"], "level": r["level"], "state": r["state"], "priority": r["priority"],
            "main_keyword": p["main_keyword"], "was": p.get("main_was"), "now": fmt_pos(p.get("main_now")),
            "lost_top3_count": p["lost_top3_count"], "traffic_lost": p["traffic_lost"],
            "updated_on": r["audit"].get("updated_on"), "flags": ", ".join(r["flags"]), "why": r["why"],
            "checklist": " | ".join(r["checklist"]), "notion_url": r["notion_url"] or r["open_card"] or "",
            "jira": r["open_ticket"] or r["recent_ticket"] or "",
        })
    return buf.getvalue()


def e(x) -> str:
    return html.escape("" if x is None else str(x))


def to_html(cfg, data: dict) -> str:
    runs = data["runs"]
    window = f"{runs[0]['date_compared']} → {runs[0]['date']}" if runs else "no runs"
    countries = ", ".join(r["country"].upper() for r in runs)
    chips = "".join(
        f'<button class="chip lv-{l}" data-level="{l}"><b>{data["counts"][l]}</b> {l} · {LEVEL_NAMES[l]}</button>'
        for l in LEVELS)
    alerts = "".join(f'<div class="alert"><b>{e(r["country"].upper())} run {r["id"]} {e(r["status"])}.</b> {e(r["error"])}</div>'
                     for r in data["aborted"])
    body_rows = []
    for i, r in enumerate(data["rows"]):
        p, a = r["page"], r["audit"]
        flags = "".join(f'<span class="flag">{e(f)}</span>' for f in r["flags"])
        kw_rows = "".join(
            f"<tr><td>{e(k['kw'])}</td><td>{k['vol']}</td><td>{fmt_pos(k['was'])} → {fmt_pos(k['now'])}</td>"
            f"<td>{k['traffic_prev']} → {k['traffic_now']}</td><td>{e(k['kind'])}</td></tr>" for k in p["lost_keywords"])
        checklist = "".join(f"<li>{e(c)}</li>" for c in r["checklist"])
        screen = "; ".join(f"#{m['category']} {m['name']} — {m['note']} ({m['verdict']})" for m in r["screen"]["matches"]) or "PASS"
        history = " · ".join(f"{e(h['date'])}: {fmt_pos(h['now'])}" for h in r["history"]) or "first run"
        fups = " · ".join(f"{e(f['label'])} due {e(f['due_date'])}: {e(f['outcome'] or 'pending')}" for f in r["followups"])
        override_note = f" (override; table said {r['computed_level']}: {e(r['override_reason'])})" if r["override_reason"] else ""
        cmd_url = r["url"]
        body_rows.append(f"""
<tr class="row" data-level="{r['level']}" data-i="{i}" tabindex="0">
  <td class="page"><a href="{e(r['url'])}" target="_blank" rel="noopener">{e(p['slug'])}</a></td>
  <td><span class="pill lv-{r['level']}">{r['level']}</span></td>
  <td>{e(p['main_keyword'])}</td>
  <td class="num">{fmt_pos(p.get('main_was'))} → {fmt_pos(p.get('main_now'))}</td>
  <td class="num">{p['lost_top3_count']}</td>
  <td class="num">{p['traffic_lost']:,}</td>
  <td class="num">{(r['priority'] or 0):,.0f}</td>
  <td>{e(a.get('updated_on') or '—')}</td>
  <td>{flags}</td>
  <td>{e(r['state'])}</td>
</tr>
<tr class="drawer" data-for="{i}" hidden><td colspan="10">
  <div class="grid">
    <section><h4>Why</h4><p>{e(r['why'])}{override_note}</p>
      <h4>Checklist</h4><ul class="todo">{checklist}</ul></section>
    <section><h4>Lost keywords</h4><table class="inner"><thead><tr><th>Keyword</th><th>Vol</th><th>Was → now</th>
      <th>Traffic</th><th>Kind</th></tr></thead><tbody>{kw_rows}</tbody></table>
      <h4>Position history (main keyword)</h4><p>{history}</p>{f'<p>Follow-ups: {fups}</p>' if fups else ''}</section>
    <section><h4>Audit</h4><ul class="facts">
      <li>Updated on: {e(a.get('updated_on') or 'unknown')} ({e(a.get('age_days'))} days)</li>
      <li>Words: {e(a.get('word_count'))} · competitor median: {e(a.get('median_competitor_words') or '—')} · check: {e(a.get('competitor_check'))}</li>
      <li>Key Takeaways: {'yes' if a.get('has_key_takeaways') else 'no'} · FAQs: {e(a.get('faq_count'))} ·
          question H2s answered: {e(a.get('question_h2_with_direct_answer'))}/{e(a.get('question_h2_count'))}</li>
      <li>Tables: {e(a.get('table_count'))} · images missing alt: {e(a.get('images_missing_alt'))} · internal links: {e(a.get('internal_links_out'))}</li>
      <li>Claim flags: {e(', '.join(a.get('claim_flags') or []) or 'none')}</li>
      <li>Screen: {e(screen)}</li>
      <li>Install intent: {e(r['intent'])} · Jira: {e(r['open_ticket'] or r['recent_ticket'] or 'none')} ·
          Notion: {('<a href="' + e(r['open_card'] or r['notion_url']) + '">card</a>') if (r['open_card'] or r['notion_url']) else 'none'}</li>
      {''.join(f'<li class="note">{e(n)}</li>' for n in r['notes'])}
    </ul>
    <h4>Actions</h4>
    <pre class="cmd">python -m decay override {e(cmd_url)} L2 --reason "..."
python -m decay exclude {e(cmd_url)} --reason "..."
python -m decay create-cards --url {e(cmd_url)}</pre></section>
  </div>
</td></tr>""")
    slack = slack_text(cfg, data)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    return TEMPLATE.format(
        title="Decay Radar", window=e(window), countries=e(countries), units=f"{data['units']:,}",
        pages=len(data["rows"]), chips=chips, proposed=data["proposed"], cap=data["cap"], alerts=alerts,
        rows="".join(body_rows) or '<tr><td colspan="10" class="empty">No pages lost top-3 positions in this window.</td></tr>',
        slack=e(slack), slack_json=json.dumps(slack), generated=generated,
        risk=f"{data['traffic_at_risk']:,}",
    )


def write_outputs(cfg, data: dict, html_path: str, csv_path: str | None = None) -> None:
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(to_html(cfg, data))
    if csv_path:
        with open(csv_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(to_csv(data))


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e3e3e0;--accent:#2f5bea;
  --l0:#8a8f98;--l1:#1f9d55;--l2:#d08a00;--l3:#d64545;--noseo:#6d4bd1;--alert:#fff1f0;--alert-ink:#a8071a}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#141416;--panel:#1d1d20;--ink:#ececef;--muted:#9a9aa2;
  --line:#2e2e33;--accent:#7f9cff;--alert:#3a1214;--alert-ink:#ffb3b0}}}}
:root[data-theme="dark"]{{--bg:#141416;--panel:#1d1d20;--ink:#ececef;--muted:#9a9aa2;--line:#2e2e33;--accent:#7f9cff;
  --alert:#3a1214;--alert-ink:#ffb3b0}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1320px;margin:0 auto;padding:24px 16px 64px}}
h1{{font-size:22px;margin:0 0 4px}}.meta{{color:var(--muted);margin:0 0 16px}}
.chips{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}}
.chip{{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:999px;padding:6px 12px;cursor:pointer;font:inherit}}
.chip.on{{outline:2px solid var(--accent)}}.chip b{{font-variant-numeric:tabular-nums}}
.bar{{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:8px 0 16px}}
.btn{{border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:8px;padding:7px 12px;cursor:pointer;font:inherit}}
.slack{{color:var(--muted);flex:1 1 320px}}
.alert{{background:var(--alert);color:var(--alert-ink);border-radius:8px;padding:10px 12px;margin:8px 0}}
.wrap{{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}}
table{{border-collapse:collapse;width:100%}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{font-size:12px;color:var(--muted);font-weight:600;white-space:nowrap}}
.row{{cursor:pointer}}.row:hover{{background:color-mix(in srgb,var(--accent) 6%,transparent)}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}.page a{{color:var(--accent);text-decoration:none}}
.pill{{display:inline-block;border-radius:6px;padding:1px 7px;color:#fff;font-weight:600;font-size:12px}}
.lv-L0{{--c:var(--l0)}}.lv-L1{{--c:var(--l1)}}.lv-L2{{--c:var(--l2)}}.lv-L3{{--c:var(--l3)}}.lv-NOSEO{{--c:var(--noseo)}}
.pill{{background:var(--c)}}.chip b{{color:var(--c)}}
.flag{{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:0 6px;margin:0 4px 2px 0;font-size:12px;color:var(--muted)}}
.drawer td{{background:color-mix(in srgb,var(--panel) 92%,var(--accent))}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}
h4{{margin:8px 0 4px;font-size:13px}}.inner th,.inner td{{padding:4px 6px;font-size:12px}}
.todo{{padding-left:18px}}.todo li{{list-style:"☐  "}}.facts{{padding-left:18px}}.note{{color:var(--muted)}}
pre.cmd{{white-space:pre-wrap;word-break:break-all;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:8px;font-size:12px}}
.empty{{text-align:center;color:var(--muted);padding:32px}}footer{{color:var(--muted);font-size:12px;margin-top:16px}}
</style></head><body><main>
<h1>Decay Radar</h1>
<p class="meta">Window {window} · {countries} · {units} Ahrefs units · {pages} pages lost top-3 · est. {risk} visits/mo at risk</p>
{alerts}
<div class="chips">{chips}</div>
<div class="bar"><span><b>Proposed this week: {proposed} / {cap}</b></span>
<button class="btn" id="copy">Copy summary</button><span class="slack" id="slack">{slack}</span></div>
<div class="wrap"><table><thead><tr><th>Page</th><th>Level</th><th>Main keyword</th><th>Was → now</th><th>Lost top-3</th>
<th>Traffic lost</th><th>Priority</th><th>Updated on</th><th>Flags</th><th>State</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<footer>Generated {generated}. Click a row for details. Nothing is written to Notion from this page; use
<code>python -m decay create-cards</code> (dry run by default).</footer>
</main>
<script>
const SLACK={slack_json};
document.getElementById('copy').addEventListener('click',async e=>{{try{{await navigator.clipboard.writeText(SLACK);
e.target.textContent='Copied';setTimeout(()=>e.target.textContent='Copy summary',1500)}}catch(_){{}}}});
function toggle(tr){{const d=document.querySelector('tr.drawer[data-for="'+tr.dataset.i+'"]');if(d)d.hidden=!d.hidden}}
document.querySelectorAll('tr.row').forEach(tr=>{{tr.addEventListener('click',ev=>{{if(ev.target.closest('a'))return;toggle(tr)}});
tr.addEventListener('keydown',ev=>{{if(ev.key==='Enter')toggle(tr)}})}});
let active=null;
document.querySelectorAll('.chip').forEach(c=>c.addEventListener('click',()=>{{active=active===c.dataset.level?null:c.dataset.level;
document.querySelectorAll('.chip').forEach(x=>x.classList.toggle('on',x.dataset.level===active));
document.querySelectorAll('tr.row').forEach(tr=>{{const show=!active||tr.dataset.level===active;tr.hidden=!show;
const d=document.querySelector('tr.drawer[data-for="'+tr.dataset.i+'"]');if(d&&!show)d.hidden=true}})}}));
</script></body></html>"""
