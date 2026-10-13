#!/usr/bin/env python3
"""Render the citation scoreboard snapshots as one self-contained HTML page.

Input: a directory of snapshots written by llm_citation_probe.py
(`citations/YYYY-MM-DD.json` plus `latest.json`). Output: a single HTML file
with no external requests, readable by someone who has never seen the JSON.

Both snapshot schemas are accepted: the original single-model shape
(`sites[].probes`) and the per-model shape (`sites[].models[].probes`).

Usage:
    python3 scripts/render_dashboard.py --snapshots citations --output citations/dashboard.html

Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

STATUS_WORD = {
    "CITED": "Cited",
    "RETRIEVED": "Found, not cited",
    "ABSENT": "Not found",
    "ERROR": "No data",
}
STATUS_EXPLAIN = {
    "CITED": "At least one answer pointed readers to this site.",
    "RETRIEVED": "Search surfaced the site but the answer cited someone else. A content gap, not a crawl problem.",
    "ABSENT": "Search never surfaced the site for these questions. Fix discoverability first.",
    "ERROR": "The probe did not complete for this site.",
}
MODEL_LABEL = {
    "openai/gpt-5.5": "OpenAI GPT-5.5",
    "perplexity/sonar": "Perplexity Sonar",
    "google/gemini-3.5-flash": "Google Gemini 3.5 Flash",
    "anthropic/claude-sonnet-5.5": "Claude Sonnet 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
}


def esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


def model_label(slug: str) -> str:
    return MODEL_LABEL.get(slug, slug)


# ---------------------------------------------------------------------------
# Loading and normalising
# ---------------------------------------------------------------------------

def normalise(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return {date, generated_at, engine, models, spend, searches, stopped,
    sites: [{name, domains, status, cited_rate, models: [{model, status,
    cited_rate, retrieved_rate, completed_runs, cited_runs, probes, competitors, skipped}]}]}"""
    models = snapshot.get("models") or [snapshot.get("model") or "unknown"]
    sites_out = []
    for site in snapshot.get("sites", []):
        rows = site.get("models")
        if not rows:
            rows = [{**site, "model": models[0]}]
        per_model = []
        for m in rows:
            per_model.append({
                "model": m.get("model", models[0]),
                "status": m.get("status", "ERROR"),
                "cited_rate": m.get("cited_rate"),
                "retrieved_rate": m.get("retrieved_rate"),
                "completed_runs": m.get("completed_runs", 0),
                "cited_runs": m.get("cited_runs", 0),
                "probes": m.get("probes", []),
                "competitors": m.get("competing_cited_domains", []),
                "skipped": m.get("skipped"),
            })
        completed = sum(m["completed_runs"] for m in per_model)
        cited = sum(m["cited_runs"] for m in per_model)
        statuses = [m["status"] for m in per_model]
        status = next((s for s in ("CITED", "RETRIEVED", "ABSENT") if s in statuses), "ERROR")
        sites_out.append({
            "name": site["name"],
            "domains": site.get("domains", []),
            "status": status,
            "cited_rate": (cited / completed) if completed else None,
            "models": per_model,
        })
    generated = snapshot.get("generated_at", "")
    return {
        "generated_at": generated,
        "date": generated[:10],
        "engine": snapshot.get("engine", "anthropic"),
        "models": models,
        "spend": snapshot.get("spend_usd"),
        "searches": snapshot.get("total_searches", 0),
        "stopped": snapshot.get("stopped_early"),
        "retrieved_exposed": snapshot.get("retrieved_exposed", True),
        "sites": sites_out,
    }


def load_snapshots(directory: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dated = sorted(p for p in directory.glob("*.json") if re.match(r"\d{4}-\d{2}-\d{2}", p.stem))
    history = [normalise(json.loads(p.read_text(encoding="utf-8"))) for p in dated]
    latest_path = directory / "latest.json"
    if latest_path.exists():
        latest = normalise(json.loads(latest_path.read_text(encoding="utf-8")))
    elif history:
        latest = history[-1]
    else:
        raise SystemExit(f"no snapshots in {directory}")
    return latest, history


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def pct(v: float | None) -> str:
    return "–" if v is None else f"{round(v * 100)}%"


def sparkline(values: list[float | None], dates: list[str]) -> str:
    """Inline SVG of cited rate over snapshots. Returns '' with fewer than 2 points."""
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return ""
    w, h, pad = 120, 28, 3
    n = len(values)
    def x(i: int) -> float:
        return pad + (w - 2 * pad) * (i / (n - 1))
    def y(v: float) -> float:
        return h - pad - (h - 2 * pad) * v
    path = " ".join(f"{'M' if k == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for k, (i, v) in enumerate(pts))
    li, lv = pts[-1]
    title = ", ".join(f"{d}: {pct(v)}" for d, v in zip(dates, values))
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{esc(title)}">'
        f'<title>{esc(title)}</title>'
        f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" class="spark-base"/>'
        f'<path d="{path}" class="spark-line"/>'
        f'<circle cx="{x(li):.1f}" cy="{y(lv):.1f}" r="3" class="spark-end"/>'
        f"</svg>"
    )


def status_pill(status: str) -> str:
    glyph = {"CITED": "●", "RETRIEVED": "◐", "ABSENT": "○", "ERROR": "–"}[status]
    return f'<span class="pill s-{status.lower()}"><span class="glyph" aria-hidden="true">{glyph}</span>{STATUS_WORD[status]}</span>'


def rate_bar(rate: float | None) -> str:
    if rate is None:
        return '<div class="bar"><div class="bar-fill" style="width:0"></div></div>'
    return f'<div class="bar" aria-hidden="true"><div class="bar-fill" style="width:{round(rate * 100)}%"></div></div>'


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

CSS = """
/* Layout: summary strip, then a site-by-model grid, then per-site detail. One column on phones. */
:root {
  --bg: #f7f6f2; --panel: #ffffff; --fg: #1b1a17; --muted: #6b6861; --line: #e2dfd6;
  --accent: #2a5db0; --accent-ink: #ffffff;
  --good: #1e7a3c; --good-bg: #e3f3e8; --warn: #9a6200; --warn-bg: #fbf0d6; --bad: #a3322b; --bad-bg: #f9e4e2; --none: #7a776f; --none-bg: #ecebe6;
  --m1: #2a78d6; --m2: #eb6834; --m3: #1baf7a;
  --display: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #15161a; --panel: #1e2026; --fg: #ecebe6; --muted: #a7a49b; --line: #33363e;
  --accent: #5f93e6; --accent-ink: #0d1117;
  --good: #5cc983; --good-bg: #16301f; --warn: #e8b04e; --warn-bg: #352a10; --bad: #f08a83; --bad-bg: #3a1e1c; --none: #9a978f; --none-bg: #2a2c32;
  --m1: #3987e5; --m2: #d95926; --m3: #199e70; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #15161a; --panel: #1e2026; --fg: #ecebe6; --muted: #a7a49b; --line: #33363e;
  --accent: #5f93e6; --accent-ink: #0d1117;
  --good: #5cc983; --good-bg: #16301f; --warn: #e8b04e; --warn-bg: #352a10; --bad: #f08a83; --bad-bg: #3a1e1c; --none: #9a978f; --none-bg: #2a2c32;
  --m1: #3987e5; --m2: #d95926; --m3: #199e70; color-scheme: dark; }
body { background: var(--bg); color: var(--fg); font-family: var(--display); line-height: 1.45; }
.wrap { max-width: 1080px; margin: 0 auto; padding-block: 24px 48px; padding-inline: 16px; }
header h1 { font-size: clamp(1.5rem, 3vw, 2.1rem); margin: 0 0 4px; letter-spacing: -0.01em; text-wrap: balance; }
header .sub { color: var(--muted); margin: 0; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 20px 0 8px; }
.kpi { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; min-width: 0; }
.kpi .label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
.kpi .value { font-size: 1.6rem; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.2; }
.kpi .note { font-size: 0.8rem; color: var(--muted); }
.legend { display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 0.85rem; color: var(--muted); margin: 10px 0 18px; }
.pill { display: inline-flex; align-items: center; gap: 6px; padding: 2px 9px; border-radius: 999px; font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
.pill .glyph { font-size: 0.7rem; }
.s-cited { color: var(--good); background: var(--good-bg); }
.s-retrieved { color: var(--warn); background: var(--warn-bg); }
.s-absent { color: var(--bad); background: var(--bad-bg); }
.s-error { color: var(--none); background: var(--none-bg); }
.gridwrap { overflow-x: auto; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; }
table.grid { border-collapse: collapse; width: 100%; min-width: 560px; }
table.grid th, table.grid td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: middle; }
table.grid th { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); font-weight: 600; }
table.grid th.model { white-space: nowrap; }
table.grid th.model::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; background: var(--swatch); }
table.grid tr:last-child td { border-bottom: 0; }
td.site { font-weight: 600; white-space: nowrap; }
td.site small { display: block; font-weight: 400; color: var(--muted); font-family: var(--mono); font-size: 0.72rem; }
td.cell { min-width: 150px; }
.cell .rate { font-variant-numeric: tabular-nums; font-size: 0.8rem; color: var(--muted); margin-left: 6px; }
.bar { height: 6px; background: var(--line); border-radius: 3px; margin-top: 6px; overflow: hidden; }
.bar-fill { height: 100%; background: var(--accent); border-radius: 3px; }
td.trend { white-space: nowrap; }
.spark-line { fill: none; stroke: var(--accent); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.spark-base { stroke: var(--line); stroke-width: 1; }
.spark-end { fill: var(--accent); stroke: var(--panel); stroke-width: 2; }
h2 { font-size: 1.15rem; margin: 32px 0 10px; }
.sites { display: grid; gap: 12px; }
details.site { background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 0; }
details.site summary { cursor: pointer; padding: 14px 16px; display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; list-style: none; }
details.site summary::-webkit-details-marker { display: none; }
details.site summary .name { font-weight: 600; font-size: 1.02rem; }
details.site summary .verdict { color: var(--muted); flex: 1 1 240px; min-width: 0; }
details.site summary .chev { color: var(--muted); transition: transform .15s; }
details.site[open] summary .chev { transform: rotate(90deg); }
@media (prefers-reduced-motion: reduce) { details.site summary .chev { transition: none; } }
.body { padding: 0 16px 16px; border-top: 1px solid var(--line); }
.model-block { margin-top: 14px; }
.model-block h3 { font-size: 0.9rem; margin: 0 0 6px; display: flex; align-items: center; gap: 8px; }
.model-block h3::before { content: ""; width: 10px; height: 10px; border-radius: 3px; background: var(--swatch); }
ul.q { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; }
ul.q li { display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: start; font-size: 0.92rem; }
ul.q li .q-text { min-width: 0; }
ul.q li .q-count { color: var(--muted); font-size: 0.8rem; font-variant-numeric: tabular-nums; }
.competitors { margin-top: 8px; font-size: 0.85rem; color: var(--muted); }
.competitors code { font-family: var(--mono); font-size: 0.8rem; color: var(--fg); background: var(--bg); padding: 1px 5px; border-radius: 4px; }
.todo { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 12px; padding: 14px 16px; }
.todo ol { margin: 6px 0 0; padding-left: 20px; }
.todo li { margin: 4px 0; }
.foot { margin-top: 28px; color: var(--muted); font-size: 0.82rem; max-width: 70ch; }
.warnbox { background: var(--warn-bg); color: var(--warn); border-radius: 10px; padding: 10px 14px; margin: 12px 0; font-weight: 600; }
a { color: var(--accent); }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
"""


def verdict_for(site: dict[str, Any]) -> str:
    rows = site["models"]
    cited = [m for m in rows if m["status"] == "CITED"]
    found = [m for m in rows if m["status"] == "RETRIEVED"]
    if cited:
        names = ", ".join(model_label(m["model"]) for m in cited)
        return f"Cited by {names}."
    if found:
        return "Found by search but never chosen as a source. Content gap."
    if all(m["status"] == "ERROR" for m in rows):
        return "No data this run."
    return "Not surfaced by any model. Discoverability first."


def todo_items(latest: dict[str, Any]) -> list[str]:
    items = []
    for site in latest["sites"]:
        rows = site["models"]
        absent = [m for m in rows if m["status"] == "ABSENT"]
        found = [m for m in rows if m["status"] == "RETRIEVED"]
        comp: dict[str, int] = {}
        for m in rows:
            for c in m["competitors"]:
                comp[c["domain"]] = comp.get(c["domain"], 0) + c["runs"]
        top = ", ".join(d for d, _ in sorted(comp.items(), key=lambda kv: (-kv[1], kv[0]))[:3])
        if site["status"] == "ABSENT" and absent:
            items.append(f"<strong>{esc(site['name'])}</strong>: not surfaced anywhere. Check the pages answer these exact questions and that search bots can fetch them. Who is cited instead: {esc(top) or 'nobody consistently'}.")
        elif site["status"] == "RETRIEVED":
            items.append(f"<strong>{esc(site['name'])}</strong>: found but not chosen. Compare the page against {esc(top) or 'the cited sources'} and close the gap in specificity.")
    return items


def render(latest: dict[str, Any], history: list[dict[str, Any]]) -> str:
    models = latest["models"]
    swatches = ["var(--m1)", "var(--m2)", "var(--m3)", "var(--accent)", "var(--muted)"]
    swatch = {m: swatches[i % len(swatches)] for i, m in enumerate(models)}
    sites = latest["sites"]
    n_cited = sum(1 for s in sites if s["status"] == "CITED")
    n_found = sum(1 for s in sites if s["status"] == "RETRIEVED")
    n_absent = sum(1 for s in sites if s["status"] == "ABSENT")
    generated = latest["generated_at"][:16].replace("T", " ") + " UTC" if latest["generated_at"] else "unknown"
    dates = [h["date"] for h in history]

    def site_history(name: str) -> list[float | None]:
        out: list[float | None] = []
        for h in history:
            match = next((s for s in h["sites"] if s["name"] == name), None)
            out.append(match["cited_rate"] if match else None)
        return out

    parts: list[str] = []
    parts.append(f"<title>Citation Scoreboard</title>\n<style>{CSS}</style>")
    parts.append('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono&display=swap">')
    parts.append('<div class="wrap">')
    parts.append("<header>")
    parts.append("<h1>Citation Scoreboard</h1>")
    model_names = ", ".join(model_label(m) for m in models)
    parts.append(f'<p class="sub">Which of our sites AI answer engines cite when a buyer asks. Last run {esc(generated)} · {esc(model_names)} · {len(history)} run(s) on record.</p>')
    parts.append("</header>")
    if latest["stopped"]:
        parts.append(f'<div class="warnbox">This run stopped early: {esc(latest["stopped"])}. Treat gaps as unknown, not as losses.</div>')

    # KPI row
    parts.append('<div class="kpis">')
    parts.append(f'<div class="kpi"><div class="label">Sites cited</div><div class="value">{n_cited} <span class="note">of {len(sites)}</span></div><div class="note">by at least one model</div></div>')
    parts.append(f'<div class="kpi"><div class="label">Found, not cited</div><div class="value">{n_found}</div><div class="note">content gaps</div></div>')
    parts.append(f'<div class="kpi"><div class="label">Not found</div><div class="value">{n_absent}</div><div class="note">discoverability gaps</div></div>')
    spend = f"${latest['spend']:.2f}" if isinstance(latest.get("spend"), (int, float)) else "–"
    parts.append(f'<div class="kpi"><div class="label">This run</div><div class="value">{latest["searches"]}</div><div class="note">web searches · spend {esc(spend)}</div></div>')
    parts.append("</div>")

    parts.append('<div class="legend">')
    for st in ("CITED", "RETRIEVED", "ABSENT"):
        parts.append(f"<span>{status_pill(st)} {esc(STATUS_EXPLAIN[st])}</span>")
    parts.append("</div>")

    # Grid
    parts.append('<div class="gridwrap"><table class="grid">')
    parts.append("<thead><tr><th>Site</th>")
    for m in models:
        parts.append(f'<th class="model" style="--swatch:{swatch[m]}">{esc(model_label(m))}</th>')
    parts.append("<th>Trend</th></tr></thead><tbody>")
    for site in sites:
        parts.append("<tr>")
        dom = site["domains"][0] if site["domains"] else ""
        parts.append(f'<td class="site">{esc(site["name"])}<small>{esc(dom)}</small></td>')
        by_model = {m["model"]: m for m in site["models"]}
        for m in models:
            row = by_model.get(m)
            if row is None:
                parts.append('<td class="cell">–</td>')
                continue
            parts.append(f'<td class="cell">{status_pill(row["status"])}<span class="rate">{pct(row["cited_rate"])}</span>{rate_bar(row["cited_rate"])}</td>')
        trend = sparkline(site_history(site["name"]), dates) or '<span class="rate">first run</span>'
        parts.append(f'<td class="trend">{trend}</td>')
        parts.append("</tr>")
    parts.append("</tbody></table></div>")

    # To-do
    todo = todo_items(latest)
    parts.append("<h2>What to do this week</h2>")
    parts.append('<div class="todo">')
    if todo:
        parts.append("<ol>" + "".join(f"<li>{t}</li>" for t in todo) + "</ol>")
    else:
        parts.append("<p>Every site was cited by at least one model. Keep the pages fresh and watch the trend column.</p>")
    parts.append("</div>")

    # Per-site detail
    parts.append("<h2>Site by site</h2>")
    parts.append('<div class="sites">')
    for site in sites:
        parts.append('<details class="site">')
        parts.append(f'<summary><span class="chev" aria-hidden="true">▸</span><span class="name">{esc(site["name"])}</span>{status_pill(site["status"])}<span class="verdict">{esc(verdict_for(site))}</span></summary>')
        parts.append('<div class="body">')
        for m in site["models"]:
            parts.append(f'<div class="model-block" style="--swatch:{swatch.get(m["model"], "var(--muted)")}">')
            parts.append(f'<h3>{esc(model_label(m["model"]))} {status_pill(m["status"])} <span class="rate">{pct(m["cited_rate"])} of runs</span></h3>')
            if m["skipped"]:
                parts.append(f'<p class="competitors">Skipped: {esc(m["skipped"])}</p>')
            parts.append('<ul class="q">')
            for p in m["probes"]:
                n = p.get("completed_runs", 0)
                parts.append(f'<li>{status_pill(p["outcome"])}<span class="q-text">{esc(p["question"])} <span class="q-count">cited {p.get("cited_runs", 0)}/{n}</span></span></li>')
            parts.append("</ul>")
            if m["competitors"]:
                comps = " ".join(f'<code>{esc(c["domain"])}</code>' for c in m["competitors"][:8])
                parts.append(f'<div class="competitors">Cited instead: {comps}</div>')
            parts.append("</div>")
        parts.append("</div></details>")
    parts.append("</div>")

    retrieved_note = "" if latest["retrieved_exposed"] else " On this engine the search's own result list is not exposed, so “found, not cited” cannot be observed and every miss shows as “not found”."
    parts.append(
        '<p class="foot">How to read this: a fixed set of buyer questions is asked of each model with its web search on, '
        'several times, and we record which sites the answers cite. These are the API models, not the consumer apps. '
        'Retrieval is noisy, so trust the trend over any single week.' + esc(retrieved_note) + "</p>"
    )
    parts.append("</div>")
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshots", default="citations")
    parser.add_argument("--output", default="citations/dashboard.html")
    args = parser.parse_args()
    latest, history = load_snapshots(Path(args.snapshots))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(latest, history), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(history)} snapshot(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
