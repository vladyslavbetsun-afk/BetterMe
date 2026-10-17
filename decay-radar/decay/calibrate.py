"""§7 calibration against the old Slipped Pages Tracker export (Oct 8 run, 2026-08-12 baseline).

Targets: >= 90% URL overlap, >= 80% level agreement. Tune thresholds, never rules,
and record every change in docs/decisions.md.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .aggregate import normalize_url
from .report import LEVELS


def norm_level(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip().upper().replace(" ", "").replace("-", "")
    if s.startswith("NOSEO") or s in ("NO", "N/A"):
        return "NOSEO"
    m = re.match(r"L?([0-3])", s)
    return f"L{m.group(1)}" if m else None


def _records(data) -> list[dict]:
    if isinstance(data, dict):
        for key in ("pages", "items", "rows", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        return [dict(v, url=k) if isinstance(v, dict) else {"url": k, "level": v} for k, v in data.items()]
    return data if isinstance(data, list) else []


def load_labels(pages_path: str, progress_path: str | None = None) -> dict[str, dict]:
    labels = {}
    for rec in _records(json.loads(Path(pages_path).read_text())):
        url = normalize_url(rec.get("url") or rec.get("page") or rec.get("URL") or rec.get("page_url"))
        if not url:
            continue
        labels[url] = {"level": norm_level(rec.get("level") or rec.get("Level")), "why": rec.get("why") or rec.get("reason") or ""}
    if progress_path and Path(progress_path).exists():
        for rec in _records(json.loads(Path(progress_path).read_text())):
            url = normalize_url(rec.get("url") or rec.get("page"))
            if url in labels and not labels[url]["level"]:
                labels[url]["level"] = norm_level(rec.get("level"))
    return labels


def compare(store, run_ids: list[int], labels: dict[str, dict]) -> dict:
    marks = ",".join("?" for _ in run_ids)
    radar = {}
    for r in store.query(f"select url, payload from decay_run_items where run_id in ({marks})", run_ids):
        radar[r["url"]] = {"level": r["payload"]["level"], "why": r["payload"]["why"], "rule": r["payload"]["rule"]}
    both = sorted(set(labels) & set(radar))
    matrix = {a: {b: 0 for b in LEVELS} for a in LEVELS}
    disagreements = []
    agree = 0
    for u in both:
        want, got = labels[u]["level"], radar[u]["level"]
        if want not in matrix:
            continue
        matrix[want][got] += 1
        if want == got:
            agree += 1
        else:
            disagreements.append({"url": u, "label": want, "label_why": labels[u]["why"], "radar": got,
                                  "radar_rule": radar[u]["rule"], "radar_why": radar[u]["why"]})
    labelled = [u for u in both if labels[u]["level"] in matrix]
    return {
        "label_urls": len(labels), "radar_urls": len(radar), "overlap": len(both),
        "overlap_pct": round(100 * len(both) / len(labels), 1) if labels else 0.0,
        "agreement_pct": round(100 * agree / len(labelled), 1) if labelled else 0.0,
        "matrix": matrix, "disagreements": disagreements,
        "missing": sorted(set(labels) - set(radar)), "extra": sorted(set(radar) - set(labels)),
    }


def format_result(res: dict) -> str:
    lines = [
        f"URL overlap: {res['overlap']}/{res['label_urls']} labelled pages = {res['overlap_pct']}% (target >= 90%)",
        f"Radar pages: {res['radar_urls']} ({len(res['extra'])} not in the old tracker)",
        f"Level agreement on the overlap: {res['agreement_pct']}% (target >= 80%)",
        "",
        "Confusion matrix (rows = old tracker, columns = radar):",
        "        " + "".join(f"{l:>7}" for l in LEVELS),
    ]
    for a in LEVELS:
        lines.append(f"{a:>7} " + "".join(f"{res['matrix'][a][b]:>7}" for b in LEVELS))
    if res["disagreements"]:
        lines += ["", "Disagreements:"]
        for d in res["disagreements"]:
            lines += [f"- {d['url']}", f"    tracker {d['label']}: {d['label_why']}",
                      f"    radar   {d['radar']} (rule {d['radar_rule']}): {d['radar_why']}"]
    if res["missing"]:
        lines += ["", f"In the tracker but not found by the radar ({len(res['missing'])}):"] + [f"- {u}" for u in res["missing"]]
    return "\n".join(lines)
