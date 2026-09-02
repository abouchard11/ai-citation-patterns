#!/usr/bin/env python3
"""Run a repeatable, evidence-first GEO/AEO technical audit.

The runner intentionally checks observable facts only. It does not claim to
measure rankings, citation share, E-E-A-T, or whether a business assertion is
true. Configured high-risk phrases are surfaced for human evidence review.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse


USER_AGENT = (
    "MidnightDev-GEO-AEO-Audit/1.0 "
    "(+https://github.com/abouchard11/ai-citation-patterns)"
)
SEARCH_BOTS = ("Googlebot", "bingbot", "OAI-SearchBot", "Claude-SearchBot", "PerplexityBot")
TRAINING_BOTS = ("GPTBot", "ClaudeBot", "CCBot", "Google-Extended", "Applebot-Extended")

# Published user-agent strings for the retrieval bots that matter for citation.
# Used for ACTIVE probing: robots.txt states policy, but edge bot-management
# (Cloudflare, Vercel, WAFs) blocks independently of it. Reading robots.txt alone
# cannot tell you whether a bot is actually served.
BOT_USER_AGENTS = {
    "Googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "bingbot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "OAI-SearchBot": "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)",
    "PerplexityBot": "Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)",
    "Claude-SearchBot": "Mozilla/5.0 (compatible; Claude-SearchBot/1.0; +https://www.anthropic.com/claude-searchbot)",
}

# What an active probe can and cannot establish. Kept next to the code that
# produces it so the caveat travels with the finding.
PROBE_CAVEAT = (
    "Requests were sent with each bot's published user-agent from this runner's IP. "
    "A 200 means that user-agent was not refused at the edge from this IP; it does NOT "
    "prove the verified bot (which origins identify by reverse DNS or published IP ranges) "
    "is allowed, nor that identical content is served to it. A block, however, is conclusive."
)

# Status codes that mean "do not retry" — the answer will not change.
NO_RETRY_STATUSES = frozenset({400, 401, 403, 404, 405, 410, 451})


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.canonical = ""
        self.h1: list[str] = []
        self.h2: list[str] = []
        self.jsonld: list[str] = []
        self.text: list[str] = []
        self.preferred_source = False
        self._capture: str | None = None
        self._buffer: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag in {"style", "noscript"}:
            self._skip_depth += 1
        if tag == "title":
            self._capture, self._buffer = "title", []
        elif tag in {"h1", "h2"}:
            self._capture, self._buffer = tag, []
        elif tag == "script":
            if values.get("type", "").lower() == "application/ld+json":
                self._capture, self._buffer = "jsonld", []
            else:
                self._skip_depth += 1
            if "news.google.com/swg/js/v1/publisher" in values.get("src", ""):
                self.preferred_source = True
        elif tag == "meta" and values.get("name", "").lower() == "description":
            self.description = values.get("content", "").strip()
        elif tag == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical = values.get("href", "").strip()
        if "google-add-preferred-source-btn" in values:
            self.preferred_source = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._capture == tag or (tag == "script" and self._capture == "jsonld"):
            value = " ".join(" ".join(self._buffer).split())
            if self._capture == "title":
                self.title = value
            elif self._capture == "h1" and value:
                self.h1.append(value)
            elif self._capture == "h2" and value:
                self.h2.append(value)
            elif self._capture == "jsonld" and value:
                self.jsonld.append(value)
            self._capture, self._buffer = None, []
        elif tag in {"style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "script" and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)
        if not self._skip_depth and not self._capture:
            value = " ".join(data.split())
            if value:
                self.text.append(value)


def fetch_text(
    url: str,
    timeout: float,
    attempts: int = 2,
    user_agent: str = USER_AGENT,
) -> tuple[str, int, str]:
    """Fetch a URL, retrying only on errors that a retry could plausibly fix.

    A 404 or 403 is a settled answer — retrying it burns the time budget for
    nothing. Only transport errors, timeouts, 429 and 5xx are retried.
    """
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xml,text/plain;q=0.9,*/*;q=0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(5_000_000)
                charset = response.headers.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace"), response.status, response.geturl()
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in NO_RETRY_STATUSES:
                raise
            if attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def probe_bot_access(url: str, timeout: float) -> dict[str, Any]:
    """Request the page as each retrieval bot and record what the edge does.

    robots.txt is a stated policy; this is an observation. The two disagree
    whenever bot management sits in front of the origin, which is exactly the
    case this audit exists to catch.
    """
    results: dict[str, Any] = {}
    for bot, agent in BOT_USER_AGENTS.items():
        try:
            _, status, _ = fetch_text(url, timeout, attempts=1, user_agent=agent)
            results[bot] = {"status": status, "blocked": False}
        except urllib.error.HTTPError as exc:
            # 401/403/429 and 5xx served only to bot UAs are the signal.
            results[bot] = {"status": exc.code, "blocked": exc.code in {401, 403, 429} or exc.code >= 500}
        except (urllib.error.URLError, TimeoutError) as exc:
            results[bot] = {"status": None, "blocked": None, "error": str(exc)}
    return {"caveat": PROBE_CAVEAT, "results": results}


def schema_types(blocks: list[str]) -> list[str]:
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            item_type = value.get("@type")
            if isinstance(item_type, str):
                found.add(item_type)
            elif isinstance(item_type, list):
                found.update(str(item) for item in item_type)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for block in blocks:
        try:
            walk(json.loads(block))
        except json.JSONDecodeError:
            found.add("INVALID_JSON_LD")
    return sorted(found)


def inspect_robots(text: str, page_url: str) -> dict[str, bool]:
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    return {bot: parser.can_fetch(bot, page_url) for bot in (*SEARCH_BOTS, *TRAINING_BOTS)}


def inspect_sitemap(text: str) -> dict[str, Any]:
    root = ET.fromstring(text)
    locs = [node.text.strip() for node in root.iter() if node.tag.endswith("loc") and node.text]
    lastmods = [node.text.strip() for node in root.iter() if node.tag.endswith("lastmod") and node.text]
    root_type = root.tag.rsplit("}", 1)[-1]
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    normalized_dates = {value[:10] for value in lastmods}
    return {
        "kind": root_type,
        "entry_count": len(locs),
        "lastmod_count": len(lastmods),
        "all_lastmods_identical": bool(lastmods) and len(set(lastmods)) == 1,
        "all_lastmods_today": bool(lastmods) and normalized_dates == {today},
    }


def claim_flags(text: str, patterns: list[str]) -> list[str]:
    """Return the configured patterns present in the page text.

    An unparseable pattern is reported rather than raised — one bad regex in a
    config file should not take down the whole portfolio run.
    """
    found: list[str] = []
    for pattern in patterns:
        try:
            if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL):
                found.append(pattern)
        except re.error as exc:
            found.append(f"INVALID_PATTERN:{pattern}:{exc}")
    return found


def load_substantiation(path: str | None) -> dict[tuple[str, str], dict[str, Any]]:
    """Index the evidence ledger by (site, claim).

    Absent ledger means every configured claim stays flagged, which is the safe
    default: no record is not the same as no problem.
    """
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {(r["site"], r["claim"]): r for r in data.get("records", [])}


def apply_substantiation(
    site_name: str,
    flags: list[str],
    ledger: dict[tuple[str, str], dict[str, Any]],
    today: dt.date,
) -> dict[str, list[str]]:
    """Sort raw claim flags against the evidence ledger.

    This is what stops a permanent WARN from becoming an ignored WARN. A claim
    with unexpired evidence on file is resolved and goes quiet. A claim recorded
    as REMOVED that is still on the page is an error, not a warning — the record
    and the site disagree.
    """
    outcome: dict[str, list[str]] = {
        "substantiated": [],
        "unsubstantiated": [],
        "expired": [],
        "removed_but_present": [],
    }
    for claim in flags:
        record = ledger.get((site_name, claim))
        if record is None or record.get("status") == "OPEN":
            outcome["unsubstantiated"].append(claim)
            continue
        if record.get("status") == "REMOVED":
            outcome["removed_but_present"].append(claim)
            continue
        expires = record.get("expires_on")
        if not expires or dt.date.fromisoformat(expires) < today:
            outcome["expired"].append(claim)
        else:
            outcome["substantiated"].append(claim)
    return outcome


def audit_site(
    site: dict[str, Any],
    timeout: float,
    ledger: dict[tuple[str, str], dict[str, Any]] | None = None,
    probe_bots: bool = True,
) -> dict[str, Any]:
    name, url = site["name"], site["url"]
    ledger = ledger or {}
    today = dt.datetime.now(dt.timezone.utc).date()
    origin = f"{urlparse(url).scheme}://{urlparse(url).netloc}/"
    result: dict[str, Any] = {"name": name, "url": url, "errors": [], "warnings": []}

    try:
        html, status, final_url = fetch_text(url, timeout)
        page = PageParser()
        page.feed(html)
        text = " ".join(page.text)
        result["page"] = {
            "status": status,
            "final_url": final_url,
            "title": page.title,
            "description": page.description,
            "canonical": page.canonical,
            "h1": page.h1,
            "h2_count": len(page.h2),
            "word_count": len(re.findall(r"\b[\w'-]+\b", text)),
            "schema_types": schema_types(page.jsonld),
            "preferred_source": page.preferred_source,
            "claim_flags": claim_flags(text, site.get("claim_patterns", [])),
        }
        if not page.canonical:
            result["errors"].append("missing canonical URL")
        if len(page.h1) != 1:
            result["errors"].append(f"expected one H1; found {len(page.h1)}")
        if not page.description:
            result["warnings"].append("missing meta description")
        types = result["page"]["schema_types"]
        if not types:
            result["warnings"].append(
                "no JSON-LD in the raw HTML "
                "(schema injected client-side is invisible to non-rendering crawlers)"
            )
        elif types == ["INVALID_JSON_LD"]:
            # Previously silent: the sentinel is truthy, so a page whose only
            # JSON-LD was malformed passed the "has schema" check.
            result["errors"].append("JSON-LD present but unparseable")
        elif "INVALID_JSON_LD" in types:
            result["warnings"].append("at least one JSON-LD block is unparseable")
        if result["page"]["word_count"] < site.get("minimum_words", 250):
            result["warnings"].append(
                f"thin answer surface: {result['page']['word_count']} words"
            )
        if site.get("preferred_source_candidate") and not page.preferred_source:
            result["warnings"].append("eligible publisher candidate has no Preferred Sources control")
        claims = apply_substantiation(name, result["page"]["claim_flags"], ledger, today)
        result["page"]["claims"] = claims
        if claims["unsubstantiated"]:
            result["warnings"].append(
                f"{len(claims['unsubstantiated'])} claim(s) on the page have no evidence record: "
                + ", ".join(claims["unsubstantiated"])
            )
        if claims["expired"]:
            result["warnings"].append(
                f"{len(claims['expired'])} claim(s) have expired substantiation: "
                + ", ".join(claims["expired"])
            )
        if claims["removed_but_present"]:
            result["errors"].append(
                "claim(s) recorded as REMOVED are still live on the page: "
                + ", ".join(claims["removed_but_present"])
            )
        if probe_bots:
            probe = probe_bot_access(url, timeout)
            result["bot_probe"] = probe
            edge_blocked = [
                bot for bot, outcome in probe["results"].items() if outcome.get("blocked")
            ]
            if edge_blocked:
                result["errors"].append(
                    "edge refused retrieval bot user-agents (robots.txt does not cover this): "
                    + ", ".join(edge_blocked)
                )
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        result["errors"].append(f"homepage fetch failed: {exc}")

    robots_url = urljoin(origin, "robots.txt")
    try:
        robots, _, _ = fetch_text(robots_url, timeout)
        permissions = inspect_robots(robots, url)
        result["robots"] = {"url": robots_url, "allowed": permissions}
        blocked = [bot for bot in SEARCH_BOTS if not permissions[bot]]
        if blocked:
            result["errors"].append(f"search/retrieval bots blocked: {', '.join(blocked)}")
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 410}:
            # RFC 9309 §2.3.1.3: an unavailable robots.txt means unrestricted
            # crawling. Treating it as a fetch failure produced false FAILs on
            # every site that simply does not publish one.
            permissions = {bot: True for bot in (*SEARCH_BOTS, *TRAINING_BOTS)}
            result["robots"] = {
                "url": robots_url,
                "status": exc.code,
                "present": False,
                "allowed": permissions,
                "note": "no robots.txt published; all crawling is permitted by default (RFC 9309)",
            }
        else:
            result["robots"] = {"url": robots_url, "status": exc.code, "error": str(exc)}
            result["errors"].append(f"robots.txt fetch failed: {exc}")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        result["robots"] = {"url": robots_url, "error": str(exc)}
        result["errors"].append(f"robots.txt fetch failed: {exc}")

    sitemap_url = urljoin(origin, "sitemap.xml")
    try:
        sitemap, _, _ = fetch_text(sitemap_url, timeout)
        details = inspect_sitemap(sitemap)
        result["sitemap"] = {"url": sitemap_url, **details}
        if details["entry_count"] == 0:
            result["errors"].append("sitemap contains no URL or child-sitemap entries")
        if details["all_lastmods_today"] and details["entry_count"] > 1:
            result["warnings"].append("every sitemap URL claims today's last-modified date")
        elif details["all_lastmods_identical"] and details["entry_count"] > 5:
            result["warnings"].append("all sitemap last-modified values are identical; verify provenance")
    except (urllib.error.URLError, TimeoutError, ValueError, ET.ParseError) as exc:
        result["sitemap"] = {"url": sitemap_url, "error": str(exc)}
        result["errors"].append(f"sitemap fetch/parse failed: {exc}")

    result["status"] = "FAIL" if result["errors"] else ("WARN" if result["warnings"] else "PASS")
    return result


def markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# GEO/AEO portfolio audit",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "> Technical readiness only. WARN means human review is required; it is not a ranking penalty.",
        "",
        "| Site | Status | H1 | Words | Schema | Sitemap entries | Preferred Source | Bot probe |",
        "| --- | --- | ---: | ---: | --- | ---: | --- | --- |",
    ]
    for item in payload["sites"]:
        page = item.get("page", {})
        sitemap = item.get("sitemap", {})
        probe = item.get("bot_probe", {}).get("results", {})
        if not probe:
            bot_cell = "not probed"
        else:
            refused = [b for b, o in probe.items() if o.get("blocked")]
            bot_cell = f"blocked: {', '.join(refused)}" if refused else f"{len(probe)}/{len(probe)} served"
        lines.append(
            "| {name} | {status} | {h1} | {words} | {schema} | {urls} | {preferred} | {bots} |".format(
                name=item["name"],
                status=item["status"],
                h1=len(page.get("h1", [])),
                words=page.get("word_count", "—"),
                schema=", ".join(page.get("schema_types", [])[:4]) or "—",
                urls=sitemap.get("entry_count", "—"),
                preferred="yes" if page.get("preferred_source") else "no",
                bots=bot_cell,
            )
        )
    for item in payload["sites"]:
        lines.extend(["", f"## {item['name']}", ""])
        for error in item["errors"]:
            lines.append(f"- ERROR: {error}")
        for warning in item["warnings"]:
            lines.append(f"- WARN: {warning}")
        if not item["errors"] and not item["warnings"]:
            lines.append("- No configured technical findings.")
    lines.extend([
        "",
        "## Interpretation",
        "",
        "Passing this audit does not prove indexation, ranking, citation share, factual accuracy, or conversion performance. Combine it with Search Console, server logs, source-level claim verification, and repeated answer-engine prompt tests.",
        "",
        "### What the bot probe does and does not show",
        "",
        PROBE_CAVEAT,
        "",
        "Concretely: a **block is conclusive** — the edge refused that user-agent and the bot will not get the page. A **pass is not** — it means only that this runner's IP was not refused while presenting that user-agent. Real crawlers are identified by reverse DNS and published IP ranges, which this cannot simulate. Do not write \"not blocked\" in a report on the strength of a pass alone.",
        "",
        "### Claim flags",
        "",
        "A flagged claim means the configured phrase appears on the page and no unexpired evidence record exists for it. It is not an assertion that the claim is false. Resolve it by attaching evidence to the substantiation ledger, or by taking the claim off the page — both are complete resolutions.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="portfolio.json")
    parser.add_argument("--output", default="audit/latest.json")
    parser.add_argument("--markdown", default="audit/latest.md")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--substantiation",
        default=None,
        help="Evidence ledger. Claims with unexpired records stop being flagged.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Sites audited in parallel. Fetches within a site stay serial.",
    )
    parser.add_argument(
        "--no-bot-probe",
        action="store_true",
        help="Skip active bot user-agent probing (robots.txt policy only).",
    )
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    ledger = load_substantiation(args.substantiation)
    probe = not args.no_bot_probe

    # Serial execution made the worst case 8 sites x 3 fetches x 2 attempts x
    # timeout, which overran the job limit and cancelled artifact upload.
    with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        sites = list(
            pool.map(lambda s: audit_site(s, args.timeout, ledger, probe), config["sites"])
        )

    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "method": "observable technical checks, active bot user-agent probing, and claim flags checked against an evidence ledger",
        "substantiation_ledger": args.substantiation or None,
        "bot_probe_enabled": probe,
        "sites": sites,
    }
    output = Path(args.output)
    markdown = Path(args.markdown)
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown.write_text(markdown_report(payload), encoding="utf-8")
    print(markdown_report(payload))
    return 2 if any(site["errors"] for site in sites) else 0


if __name__ == "__main__":
    sys.exit(main())
