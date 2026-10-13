#!/usr/bin/env python3
"""Measure whether an answer engine retrieves and cites your sites.

The probe asks Claude a fixed set of buyer-intent questions with the web
search server tool enabled and records, for each question, which domains
the search retrieved and which domains the final answer cited. Repeated
over weeks, that is a citation scoreboard: share of voice per site, and the
competing domains that win the citations you do not.

Scope, stated plainly:

- It measures ONE engine (Claude via the Messages API) through its official
  tool. It does not scrape any product UI and it does not simulate users.
- Retrieval is non-deterministic. Every query runs `repeats` times and the
  report shows cited-in-k-of-n, never a single snapshot.
- A site that is retrieved but not cited lost on content, not on crawl
  access. A site that is never retrieved has an index problem first.
- Nothing here changes a site, a search engine, or a ranking.

Dependencies: Python 3.10+ standard library only, by design, so the private
companion repo can run it in CI with no install step.

Usage:
    ANTHROPIC_API_KEY=... python3 scripts/llm_citation_probe.py \
        --config probes.json --output citations/latest.json \
        --markdown citations/latest.md

    # Offline, from saved responses (tests, CI smoke runs):
    python3 scripts/llm_citation_probe.py --config probes.json \
        --fixtures tests/fixtures/citation_probe --output /tmp/out.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_SEARCH_TOOL = "web_search_20250305"
DEFAULT_REPEATS = 2
DEFAULT_MAX_USES = 3
USER_AGENT = "MidnightDev-LLM-Citation-Probe/1.0 (+https://github.com/abouchard11/ai-citation-patterns)"

# The probe asks the question the way a buyer would and asks for sources. It
# does not name any site, so a citation is earned, not prompted.
SYSTEM_PROMPT = (
    "You are answering a consumer's question. Use web search, then answer in "
    "a short paragraph and cite the sources you relied on. Prefer specific, "
    "current sources. Do not ask clarifying questions."
)

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


# ---------------------------------------------------------------------------
# Domain handling
# ---------------------------------------------------------------------------

def host_of(url: str) -> str:
    """Lower-cased hostname with a leading `www.` removed; '' if unparseable."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def normalise_domain(domain: str) -> str:
    """Accept 'example.com', 'www.example.com', or 'https://example.com/'."""
    domain = domain.strip().lower()
    if "://" in domain:
        return host_of(domain)
    domain = domain.split("/", 1)[0]
    return domain[4:] if domain.startswith("www.") else domain


def domain_matches(url: str, domains: list[str]) -> bool:
    host = host_of(url)
    if not host:
        return False
    for domain in domains:
        if host == domain or host.endswith("." + domain):
            return True
    return False


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def extract_signals(response: dict[str, Any]) -> dict[str, Any]:
    """Pull retrieved URLs, cited URLs, search queries, and errors out of a
    Messages API response that used the web search tool.

    Works for direct searches and for dynamic-filtered searches (where the
    same block types appear nested with a `caller` field). Order is preserved
    and duplicates removed, so position in `retrieved` approximates rank.
    """
    retrieved: list[dict[str, str]] = []
    cited: list[dict[str, str]] = []
    queries: list[str] = []
    errors: list[str] = []
    seen_retrieved: set[str] = set()
    seen_cited: set[str] = set()
    answer_parts: list[str] = []

    for block in response.get("content", []) or []:
        btype = block.get("type")
        if btype == "server_tool_use" and block.get("name") == "web_search":
            query = (block.get("input") or {}).get("query")
            if isinstance(query, str):
                queries.append(query)
        elif btype == "web_search_tool_result":
            content = block.get("content")
            if isinstance(content, dict):
                # Error object, not a result list. Billed as nothing; recorded here.
                errors.append(str(content.get("error_code") or content.get("type") or "unknown"))
                continue
            for item in content or []:
                if item.get("type") != "web_search_result":
                    continue
                url = item.get("url") or ""
                if url and url not in seen_retrieved:
                    seen_retrieved.add(url)
                    retrieved.append({
                        "url": url,
                        "title": item.get("title") or "",
                        "page_age": item.get("page_age") or "",
                    })
        elif btype == "text":
            answer_parts.append(block.get("text") or "")
            for citation in block.get("citations") or []:
                if citation.get("type") != "web_search_result_location":
                    continue
                url = citation.get("url") or ""
                if url and url not in seen_cited:
                    seen_cited.add(url)
                    cited.append({
                        "url": url,
                        "title": citation.get("title") or "",
                        "cited_text": (citation.get("cited_text") or "")[:150],
                    })

    usage = response.get("usage") or {}
    return {
        "queries_issued": queries,
        "retrieved": retrieved,
        "cited": cited,
        "search_errors": errors,
        "stop_reason": response.get("stop_reason"),
        "answer_chars": sum(len(p) for p in answer_parts),
        "web_search_requests": (usage.get("server_tool_use") or {}).get("web_search_requests", 0),
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }


# ---------------------------------------------------------------------------
# API client (raw HTTP, stdlib only)
# ---------------------------------------------------------------------------

def build_request(question: str, settings: dict[str, Any]) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "type": settings["search_tool"],
        "name": "web_search",
        "max_uses": settings["max_uses"],
    }
    if settings.get("user_location"):
        tool["user_location"] = {"type": "approximate", **settings["user_location"]}
    if settings.get("blocked_domains"):
        tool["blocked_domains"] = settings["blocked_domains"]
    return {
        "model": settings["model"],
        "max_tokens": settings.get("max_tokens", 1024),
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": question}],
        "tools": [tool],
    }


def call_api(body: dict[str, Any], api_key: str, timeout: float, attempts: int = 3) -> dict[str, Any]:
    """POST to the Messages API with bounded retries on transient failures.

    Settled failures (400, 401, 403, 404, 413, 422) are raised immediately;
    they will not change on retry and should surface in the report.
    """
    data = json.dumps(body).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            API_URL,
            data=data,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": API_VERSION,
                "user-agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            if exc.code not in RETRYABLE_STATUS or attempt == attempts:
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"network: {exc}") from exc
            last_error = exc
        time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"unreachable: {last_error}")


# ---------------------------------------------------------------------------
# Fixture mode (offline)
# ---------------------------------------------------------------------------

def fixture_key(site: str, question: str, run_index: int) -> str:
    digest = hashlib.sha256(f"{site}\n{question}\n{run_index}".encode("utf-8")).hexdigest()[:16]
    return f"{digest}.json"


def load_fixture(fixtures_dir: Path, site: str, question: str, run_index: int) -> dict[str, Any] | None:
    path = fixtures_dir / fixture_key(site, question, run_index)
    if not path.exists():
        # Fall back to a run-independent fixture so one file can serve all repeats.
        path = fixtures_dir / fixture_key(site, question, 0)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Probe execution and aggregation
# ---------------------------------------------------------------------------

def run_probe(
    site: dict[str, Any],
    question: str,
    settings: dict[str, Any],
    api_key: str | None,
    fixtures_dir: Path | None,
    timeout: float,
) -> dict[str, Any]:
    domains = site["_domains"]
    runs: list[dict[str, Any]] = []
    for index in range(settings["repeats"]):
        run: dict[str, Any] = {"index": index}
        try:
            if fixtures_dir is not None:
                response = load_fixture(fixtures_dir, site["name"], question, index)
                if response is None:
                    raise RuntimeError("no fixture for this probe")
            else:
                assert api_key is not None
                response = call_api(build_request(question, settings), api_key, timeout)
            if response.get("type") == "error":
                raise RuntimeError(f"API error: {json.dumps(response.get('error'))[:300]}")
            signals = extract_signals(response)
            run.update(signals)
            run["retrieved_urls"] = [r["url"] for r in signals["retrieved"]]
            run["cited_urls"] = [c["url"] for c in signals["cited"]]
            run["site_retrieved"] = any(domain_matches(u, domains) for u in run["retrieved_urls"])
            run["site_cited"] = any(domain_matches(u, domains) for u in run["cited_urls"])
            matches = [i for i, u in enumerate(run["retrieved_urls"]) if domain_matches(u, domains)]
            run["site_best_rank"] = (matches[0] + 1) if matches else None
            run["cited_domains"] = sorted({host_of(u) for u in run["cited_urls"] if host_of(u)})
            run["retrieved_domains"] = sorted({host_of(u) for u in run["retrieved_urls"] if host_of(u)})
            if signals["stop_reason"] == "refusal":
                run["error"] = "model declined the request (stop_reason=refusal)"
            # Keep the snapshot small: drop the per-result dicts, keep URL lists.
            del run["retrieved"], run["cited"]
        except RuntimeError as exc:
            run["error"] = str(exc)
            run["site_retrieved"] = None
            run["site_cited"] = None
        runs.append(run)

    completed = [r for r in runs if not r.get("error")]
    cited_runs = sum(1 for r in completed if r["site_cited"])
    retrieved_runs = sum(1 for r in completed if r["site_retrieved"])
    return {
        "question": question,
        "runs": runs,
        "completed_runs": len(completed),
        "cited_runs": cited_runs,
        "retrieved_runs": retrieved_runs,
        "outcome": classify(len(completed), cited_runs, retrieved_runs),
    }


def classify(completed: int, cited: int, retrieved: int) -> str:
    if completed == 0:
        return "ERROR"
    if cited:
        return "CITED"
    if retrieved:
        return "RETRIEVED"
    return "ABSENT"


def summarise_site(site: dict[str, Any], probes: list[dict[str, Any]]) -> dict[str, Any]:
    completed = sum(p["completed_runs"] for p in probes)
    cited = sum(p["cited_runs"] for p in probes)
    retrieved = sum(p["retrieved_runs"] for p in probes)
    outcomes = [p["outcome"] for p in probes]
    if all(o == "ERROR" for o in outcomes):
        status = "ERROR"
    elif "CITED" in outcomes:
        status = "CITED"
    elif "RETRIEVED" in outcomes:
        status = "RETRIEVED"
    else:
        status = "ABSENT"

    competitor_counts: dict[str, int] = {}
    for probe in probes:
        for run in probe["runs"]:
            for domain in run.get("cited_domains") or []:
                if not domain_matches(f"https://{domain}/", site["_domains"]):
                    competitor_counts[domain] = competitor_counts.get(domain, 0) + 1
    competitors = sorted(competitor_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8]

    return {
        "name": site["name"],
        "domains": site["_domains"],
        "status": status,
        "completed_runs": completed,
        "cited_runs": cited,
        "retrieved_runs": retrieved,
        "cited_rate": round(cited / completed, 3) if completed else None,
        "retrieved_rate": round(retrieved / completed, 3) if completed else None,
        "competing_cited_domains": [{"domain": d, "runs": n} for d, n in competitors],
        "probes": probes,
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def pct(value: float | None) -> str:
    return "—" if value is None else f"{round(value * 100):d}%"


def markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# LLM citation scoreboard",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        f"Engine: Claude `{payload['model']}` with `{payload['search_tool']}`, "
        f"{payload['repeats']} run(s) per question, {payload['total_searches']} web searches billed.",
        "",
        "> One engine, official API, no site named in any prompt. Retrieval is non-deterministic, "
        "so read rates across repeats, not single runs. CITED = at least one answer cited the site. "
        "RETRIEVED = search returned the site but no answer cited it (a content problem). "
        "ABSENT = search never returned the site (an index problem first).",
        "",
        "| Site | Status | Cited | Retrieved | Questions | Top competing cited domains |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for site in payload["sites"]:
        competitors = ", ".join(c["domain"] for c in site["competing_cited_domains"][:4]) or "—"
        lines.append(
            f"| {site['name']} | {site['status']} | {pct(site['cited_rate'])} | "
            f"{pct(site['retrieved_rate'])} | {len(site['probes'])} | {competitors} |"
        )

    for site in payload["sites"]:
        lines.extend(["", f"## {site['name']}", ""])
        for probe in site["probes"]:
            n = probe["completed_runs"]
            lines.append(
                f"- {probe['outcome']}: \"{probe['question']}\" — cited {probe['cited_runs']}/{n}, "
                f"retrieved {probe['retrieved_runs']}/{n}"
            )
            errors = sorted({r["error"] for r in probe["runs"] if r.get("error")})
            for error in errors:
                lines.append(f"  - ERROR: {error}")
        if site["competing_cited_domains"]:
            lines.append("")
            lines.append(
                "  Competing cited domains: "
                + ", ".join(f"{c['domain']} ({c['runs']})" for c in site["competing_cited_domains"])
            )

    lines.extend([
        "",
        "## Interpretation",
        "",
        "This is a measurement of one engine's behaviour on a fixed question set. It is not a ranking, "
        "not a traffic estimate, and not evidence about other engines. A change between runs can be "
        "engine drift as easily as a change on your site; confirm with Search Console and server logs "
        "before acting. Competing domains are the sources that were cited when yours was not. Study "
        "what they say that you do not.",
        "",
    ])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config.get("probes"), list) or not config["probes"]:
        raise SystemExit("config needs a non-empty 'probes' list")
    for site in config["probes"]:
        for key in ("name", "domain", "questions"):
            if key not in site:
                raise SystemExit(f"probe entry missing '{key}': {json.dumps(site)[:120]}")
        domains = [site["domain"], *site.get("aliases", [])]
        site["_domains"] = [normalise_domain(d) for d in domains if d]
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="probes.json")
    parser.add_argument("--output", default="citations/latest.json")
    parser.add_argument("--markdown", default="citations/latest.md")
    parser.add_argument("--model", default=None, help=f"Overrides config. Default {DEFAULT_MODEL}.")
    parser.add_argument("--search-tool", default=None, help=f"Overrides config. Default {DEFAULT_SEARCH_TOOL}.")
    parser.add_argument("--repeats", type=int, default=None, help=f"Runs per question. Default {DEFAULT_REPEATS}.")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--fixtures", default=None, help="Directory of saved responses; no API calls are made.")
    parser.add_argument("--max-probes", type=int, default=None, help="Stop after N questions in total (budget guard).")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    defaults = config.get("defaults", {})
    settings_base = {
        "model": args.model or defaults.get("model", DEFAULT_MODEL),
        "search_tool": args.search_tool or defaults.get("search_tool", DEFAULT_SEARCH_TOOL),
        "repeats": args.repeats or int(defaults.get("repeats", DEFAULT_REPEATS)),
        "max_uses": int(defaults.get("max_uses", DEFAULT_MAX_USES)),
        "max_tokens": int(defaults.get("max_tokens", 1024)),
        "blocked_domains": defaults.get("blocked_domains") or [],
    }
    if settings_base["repeats"] < 1:
        raise SystemExit("repeats must be at least 1")

    fixtures_dir = Path(args.fixtures) if args.fixtures else None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if fixtures_dir is None and not api_key:
        print("ANTHROPIC_API_KEY is not set and no --fixtures directory was given.", file=sys.stderr)
        return 2

    sites_out: list[dict[str, Any]] = []
    probes_run = 0
    for site in config["probes"]:
        settings = dict(settings_base)
        settings["user_location"] = site.get("user_location") or defaults.get("user_location")
        probes: list[dict[str, Any]] = []
        for question in site["questions"]:
            if args.max_probes is not None and probes_run >= args.max_probes:
                break
            probes.append(run_probe(site, question, settings, api_key, fixtures_dir, args.timeout))
            probes_run += 1
        sites_out.append(summarise_site(site, probes))

    total_searches = sum(
        r.get("web_search_requests", 0) for s in sites_out for p in s["probes"] for r in p["runs"]
    )
    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "method": "fixed buyer-intent questions asked of Claude with the web search server tool; "
        "retrieved and cited domains recorded per run; no site named in any prompt",
        "model": settings_base["model"],
        "search_tool": settings_base["search_tool"],
        "repeats": settings_base["repeats"],
        "source": "fixtures" if fixtures_dir else "live",
        "total_searches": total_searches,
        "sites": sites_out,
    }

    output = Path(args.output)
    markdown = Path(args.markdown)
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown.write_text(markdown_report(payload), encoding="utf-8")
    print(markdown_report(payload))

    any_error = any(r.get("error") for s in sites_out for p in s["probes"] for r in p["runs"])
    return 2 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
