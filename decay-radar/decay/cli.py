"""`python -m decay run|review|create-cards|followup|report` (+ calibrate, override, exclude, import-suggested, settings)."""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import webbrowser
from datetime import date, timedelta
from pathlib import Path

from . import calibrate as cal
from . import report as rp
from .aggregate import normalize_url
from .ahrefs import AhrefsClient
from .audit import Fetcher
from .config import LEVEL_NAMES, ROOT, load_config
from .followup import run_followups
from .jira import JiraClient
from .level import checklist_for
from .notion import NotionClient, create_cards
from .pipeline import Clients, run
from .storage import connect

DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)")
URL_RE = re.compile(r"https?://(?:www\.)?betterme\.world/articles/[^\s)\]>\"'|]+", re.I)


def build(args):
    today = date.fromisoformat(args.today) if getattr(args, "today", None) else None
    if today is None and getattr(args, "date", None):
        today = date.fromisoformat(args.date) + timedelta(days=1)  # reproduce a past run as of its own day
    cfg = load_config(today=today)
    store = connect(cfg)
    cfg.apply_overrides(store.load_settings())
    return cfg, store


def clients(cfg, need_ahrefs=True) -> Clients:
    c = Clients()
    if cfg.ahrefs_api_key:
        c.ahrefs = AhrefsClient(cfg.ahrefs_api_key)
    elif need_ahrefs:
        sys.exit("AHREFS_API_KEY is missing. Copy .env.example to .env and fill it in (never commit .env).")
    c.fetcher = Fetcher(cfg["user_agent"], cfg["fetch_delay_sec"], cfg["http_timeout"])
    if cfg.jira_base_url and cfg.jira_email and cfg.jira_api_token:
        c.jira = JiraClient(cfg.jira_base_url, cfg.jira_email, cfg.jira_api_token, cfg["jira_project"])
    if cfg.notion_token:
        c.notion = NotionClient(cfg.notion_token, cfg["notion_data_source_id"])
    return c


def cmd_run(args):
    cfg, store = build(args)
    if args.no_cards:
        cfg.settings["auto_create"] = False
    c = clients(cfg)
    res = run(cfg, store, c, args.date, args.compare, no_cards=args.no_cards, gsc_path=args.gsc,
              countries=args.country or None)
    data = rp.collect(cfg, store, res.run_ids)
    out = Path(args.report or ROOT / "decay-report.html")
    rp.write_outputs(cfg, data, str(out), str(out.with_suffix(".csv")))
    print(rp.terminal_table(data))
    print(rp.slack_text(cfg, data))
    print(f"\nReport: {out}\nCSV:    {out.with_suffix('.csv')}")
    if args.labels:
        print("\n" + cal.format_result(cal.compare(store, res.run_ids, cal.load_labels(args.labels, args.progress))))
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 1 if res.aborted else 0


def cmd_review(args):
    cfg, store = build(args)
    data = rp.collect(cfg, store)
    if args.url:
        url = normalize_url(args.url)
        rows = [r for r in data["rows"] if r["url"] == url]
        if not rows:
            sys.exit(f"{args.url} is not in the latest run.")
        print(rp.detail_text(rows[0]))
    else:
        print(rp.terminal_table(data, limit=args.limit))
        print(rp.slack_text(cfg, data))


def cmd_override(args):
    cfg, store = build(args)
    url = normalize_url(args.url)
    item = store.item(url)
    if not item:
        sys.exit(f"Unknown page: {args.url}")
    level = args.level.upper()
    if level not in LEVEL_NAMES:
        sys.exit(f"Level must be one of {', '.join(LEVEL_NAMES)}")
    payload = rp.collect(cfg, store)
    row = next((r for r in payload["rows"] if r["url"] == url), None)
    checklist = item["checklist"]
    if row:
        from .audit import Audit
        a = Audit(**{k: v for k, v in row["audit"].items() if k in Audit.__dataclass_fields__})
        checklist = checklist_for(cfg, level, dict(row["page"], cluster=None), a, list(a.claim_flags))
    store.execute("update decay_items set level_override=?, override_reason=?, checklist=? where url=?",
                  [level, args.reason, json.dumps(checklist), url])
    store.commit()
    print(f"{url}: level {item['level']} -> {level} (reason: {args.reason})")


def cmd_exclude(args):
    cfg, store = build(args)
    url = normalize_url(args.url)
    if not store.item(url):
        sys.exit(f"Unknown page: {args.url}")
    store.execute("update decay_items set state='excluded', excluded_reason=? where url=?", [args.reason, url])
    store.commit()
    print(f"{url}: excluded ({args.reason}). It will not be suggested again until `include`.")


def cmd_include(args):
    cfg, store = build(args)
    url = normalize_url(args.url)
    store.execute("update decay_items set state='confirmed', excluded_reason=null where url=? and state='excluded'", [url])
    store.commit()
    print(f"{url}: un-excluded; next run re-evaluates it.")


def cmd_create_cards(args):
    cfg, store = build(args)
    urls = [normalize_url(u) for u in args.url] if args.url else None
    notion = NotionClient(cfg.notion_token, cfg["notion_data_source_id"]) if cfg.notion_token else None
    cards, _ = create_cards(cfg, store, None, dry_run=True, urls=urls)
    if not cards:
        print("No proposed L1–L3 pages. Run `python -m decay run` first, or pass --url.")
        return 0
    print(f"{'DRY RUN: ' if not args.apply else ''}{len(cards)} card(s) for the Articles data source "
          f"collection://{cfg['notion_data_source_id']}\n")
    for i, c in enumerate(cards, 1):
        props = {k: v for k, v in c.properties.items() if v is not None}
        if props.get("category"):
            props["category"] += " (inferred)"
        print(f"── Card {i}: {c.url}  [{c.level}, priority {c.priority:.1f}]")
        print(json.dumps(props, indent=2, ensure_ascii=False))
        print(c.body_markdown + "\n")
    if not args.apply:
        print("Nothing was written. Re-run with --apply to create these cards.")
        return 0
    if notion is None:
        sys.exit("NOTION_TOKEN is missing; cannot apply. Use `report` for a CSV instead.")
    if not args.yes:
        if input(f"Create {len(cards)} Notion card(s)? Type 'yes' to confirm: ").strip().lower() != "yes":
            print("Cancelled; nothing written.")
            return 0
    _, outcomes = create_cards(cfg, store, notion, dry_run=False, urls=urls)
    for o in outcomes:
        status = {True: "verified", False: "VERIFY FAILED", None: ""}[o.verified]
        print(f"{o.action:9} {o.url} {o.notion_url or ''} {status} {o.reason}")
        for m in o.mismatches:
            print(f"          {m}")
        if o.action == "created" and o.category_inferred:
            print(f"          category inferred: {o.category}")
    return 0 if all(o.verified is not False for o in outcomes) else 2


def cmd_followup(args):
    cfg, store = build(args)
    c = clients(cfg)
    done = run_followups(cfg, store, c.ahrefs, c.notion, c.fetcher, cfg.today)
    for d in done:
        print(f"{d['label']:5} {d['outcome']:14} {d['url']}")
    if not done:
        print("No follow-up checks due.")


def cmd_report(args):
    cfg, store = build(args)
    data = rp.collect(cfg, store, args.run or None)
    out = Path(args.html or ROOT / "decay-report.html")
    rp.write_outputs(cfg, data, str(out), args.csv)
    print(rp.slack_text(cfg, data) if args.slack else f"Report: {out}")


def cmd_calibrate(args):
    cfg, store = build(args)
    run_ids = args.run or [r["id"] for r in rp.runs_for_report(store)]
    print(cal.format_result(cal.compare(store, run_ids, cal.load_labels(args.labels, args.progress))))


def cmd_import_suggested(args):
    cfg, store = build(args)
    current = cfg.today.isoformat()
    added = 0
    for line in Path(args.path).read_text(encoding="utf-8").splitlines():
        m = DATE_RE.search(line)
        if m and line.lstrip().startswith("#"):
            current = m.group(1)
        for u in URL_RE.findall(line):
            url = normalize_url(u)
            if url and not store.one("select url from decay_suggestions where url=?", [url]):
                store.upsert("decay_suggestions", {"url": url, "first_suggested": current, "source": "tracking-doc"}, ["url"])
                added += 1
    store.commit()
    print(f"Imported {added} URL(s) from {args.path}.")


def cmd_settings(args):
    cfg, store = build(args)
    if args.action == "show":
        print(json.dumps(cfg.settings, indent=2))
    else:
        store.set_setting(args.key, json.loads(args.value))
        print(f"{args.key} = {args.value}")


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="python -m decay", description="Content Decay Radar (spec 06)")
    p.add_argument("--today", help="pretend today is YYYY-MM-DD (tests, reproductions)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="weekly run: detect, audit, level, prioritize, report")
    r.add_argument("--date", help="report date (default: yesterday)")
    r.add_argument("--compare", help="comparison date (default: date - compare_days)")
    r.add_argument("--country", action="append", help="override the country list (repeatable)")
    r.add_argument("--no-cards", action="store_true", help="never create cards, even with auto_create")
    r.add_argument("--gsc", help="CSV of url, clicks_last_28, clicks_prev_28")
    r.add_argument("--labels", help="calibration labels (import/slipped__pages.json)")
    r.add_argument("--progress", help="import/slipped__progress.json")
    r.add_argument("--report", help="HTML output path (default decay-report.html)")
    r.add_argument("--open", action="store_true", help="open the report in a browser")
    r.set_defaults(fn=cmd_run)

    v = sub.add_parser("review", help="terminal table of the latest run, or one page's details")
    v.add_argument("--url")
    v.add_argument("--limit", type=int, default=60)
    v.set_defaults(fn=cmd_review)

    o = sub.add_parser("override", help="change a page's level (reason required)")
    o.add_argument("url")
    o.add_argument("level")
    o.add_argument("--reason", required=True)
    o.set_defaults(fn=cmd_override)

    x = sub.add_parser("exclude", help="never suggest a page again until `include`")
    x.add_argument("url")
    x.add_argument("--reason", required=True)
    x.set_defaults(fn=cmd_exclude)
    i = sub.add_parser("include", help="undo `exclude`")
    i.add_argument("url")
    i.set_defaults(fn=cmd_include)

    c = sub.add_parser("create-cards", help="Notion cards for proposed pages (dry run unless --apply)")
    c.add_argument("--url", action="append", help="limit to these pages (repeatable)")
    c.add_argument("--apply", action="store_true", help="actually write to Notion")
    c.add_argument("--dry-run", action="store_true", help="the default; kept for explicitness")
    c.add_argument("--yes", action="store_true", help="skip the confirmation prompt (with --apply)")
    c.set_defaults(fn=cmd_create_cards)

    f = sub.add_parser("followup", help="+14/+28 day checks for updated pages")
    f.set_defaults(fn=cmd_followup)

    rep = sub.add_parser("report", help="re-render HTML/CSV/Slack text from stored runs")
    rep.add_argument("--run", type=int, action="append")
    rep.add_argument("--html")
    rep.add_argument("--csv")
    rep.add_argument("--slack", action="store_true", help="print the weekly Slack text")
    rep.set_defaults(fn=cmd_report)

    k = sub.add_parser("calibrate", help="compare a run with the old tracker's levels")
    k.add_argument("--labels", required=True)
    k.add_argument("--progress")
    k.add_argument("--run", type=int, action="append")
    k.set_defaults(fn=cmd_calibrate)

    s = sub.add_parser("import-suggested", help="load the 'Already Suggested' tracking doc into decay_suggestions")
    s.add_argument("path", nargs="?", default=str(ROOT / "import" / "already-suggested.md"))
    s.set_defaults(fn=cmd_import_suggested)

    st = sub.add_parser("settings", help="show or set thresholds")
    st.add_argument("action", choices=["show", "set"])
    st.add_argument("key", nargs="?")
    st.add_argument("value", nargs="?", help="JSON value, e.g. 20 or '[\"us\",\"gb\"]'")
    st.set_defaults(fn=cmd_settings)

    args = p.parse_args(argv)
    return args.fn(args) or 0
