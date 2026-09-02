#!/usr/bin/env python3
"""Run a repeatable, evidence-first GEO/AEO technical audit.

The runner intentionally checks observable facts only. It does not claim to
measure rankings, citation share, E-E-A-T, or whether a business assertion is
true. Configured high-risk phrases are surfaced for human evidence review.
"""

from __future__ import annotations

import argparse
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


def fetch_text(url: str, timeout: float, attempts: int = 2) -> tuple[str, int, str]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml,text/plain;q=0.9,*/*;q=0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read(5_000_000)
                charset = response.headers.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace"), response.status, response.geturl()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


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
    return [pattern for pattern in patterns if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)]


def audit_site(site: dict[str, Any], timeout: float) -> dict[str, Any]:
    name, url = site["name"], site["url"]
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
        if not result["page"]["schema_types"]:
            result["warnings"].append("no valid JSON-LD types found")
        if result["page"]["word_count"] < site.get("minimum_words", 250):
            result["warnings"].append(
                f"thin answer surface: {result['page']['word_count']} words"
            )
        if site.get("preferred_source_candidate") and not page.preferred_source:
            result["warnings"].append("eligible publisher candidate has no Preferred Sources control")
        if result["page"]["claim_flags"]:
            result["warnings"].append("configured high-risk claims require evidence review")
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
        "| Site | Status | H1 | Words | Schema | Sitemap entries | Preferred Source |",
        "| --- | --- | ---: | ---: | --- | ---: | --- |",
    ]
    for item in payload["sites"]:
        page = item.get("page", {})
        sitemap = item.get("sitemap", {})
        lines.append(
            "| {name} | {status} | {h1} | {words} | {schema} | {urls} | {preferred} |".format(
                name=item["name"],
                status=item["status"],
                h1=len(page.get("h1", [])),
                words=page.get("word_count", "—"),
                schema=", ".join(page.get("schema_types", [])[:4]) or "—",
                urls=sitemap.get("entry_count", "—"),
                preferred="yes" if page.get("preferred_source") else "no",
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
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="portfolio.json")
    parser.add_argument("--output", default="audit/latest.json")
    parser.add_argument("--markdown", default="audit/latest.md")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    sites = [audit_site(site, args.timeout) for site in config["sites"]]
    payload = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "method": "observable technical checks plus configured claim-review flags",
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
