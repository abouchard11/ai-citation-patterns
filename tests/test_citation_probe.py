import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest


MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "llm_citation_probe.py"
SPEC = importlib.util.spec_from_file_location("llm_citation_probe", MODULE_PATH)
PROBE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(PROBE)


def search_result(url, title="t"):
    return {"type": "web_search_result", "url": url, "title": title, "encrypted_content": "x", "page_age": "May 1, 2026"}


def direct_response(retrieved, cited, stop_reason="end_turn"):
    """A Messages API response for a direct (unfiltered) web search."""
    return {
        "type": "message",
        "role": "assistant",
        "stop_reason": stop_reason,
        "content": [
            {"type": "text", "text": "I'll search."},
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "widget suppliers texas"}},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [search_result(u) for u in retrieved]},
            {"type": "text", "text": "Based on the results, ..."},
            {
                "type": "text",
                "text": "Answer sentence.",
                "citations": [
                    {"type": "web_search_result_location", "url": u, "title": "t", "encrypted_index": "e", "cited_text": "snippet"}
                    for u in cited
                ],
            },
        ],
        "usage": {"input_tokens": 100, "output_tokens": 50, "server_tool_use": {"web_search_requests": 1}},
    }


def filtered_response(retrieved, cited):
    """Dynamic filtering nests the same blocks under a code-execution caller."""
    resp = direct_response(retrieved, cited)
    for block in resp["content"]:
        if block["type"] in ("server_tool_use", "web_search_tool_result"):
            block["caller"] = {"type": "code_execution_20260120", "tool_id": "srvtoolu_code"}
    resp["content"].insert(1, {"type": "server_tool_use", "id": "srvtoolu_code", "name": "code_execution", "input": {"code": "..."}})
    return resp


def openrouter_response(cited, finish="stop", error=None):
    """An OpenRouter chat completion with url_citation annotations."""
    if error is not None:
        return {"error": error}
    return {
        "id": "gen-1",
        "choices": [{
            "finish_reason": finish,
            "message": {
                "role": "assistant",
                "content": "Answer with [a.com](https://a.com/).",
                "annotations": [
                    {"type": "url_citation", "url_citation": {"url": u, "title": "t", "content": "snippet", "start_index": 0, "end_index": 5}}
                    for u in cited
                ],
            },
        }],
        "usage": {"prompt_tokens": 80, "completion_tokens": 40, "server_tool_use": {"web_search_requests": 2}},
    }


class DomainTests(unittest.TestCase):
    def test_host_strips_www_and_lowercases(self):
        self.assertEqual(PROBE.host_of("https://WWW.Example.com/path"), "example.com")
        self.assertEqual(PROBE.host_of("not a url"), "")

    def test_domain_match_covers_subdomains_but_not_lookalikes(self):
        domains = ["example.com"]
        self.assertTrue(PROBE.domain_matches("https://example.com/", domains))
        self.assertTrue(PROBE.domain_matches("https://blog.example.com/x", domains))
        self.assertFalse(PROBE.domain_matches("https://notexample.com/", domains))
        self.assertFalse(PROBE.domain_matches("https://example.com.evil.net/", domains))

    def test_normalise_accepts_urls_and_www(self):
        self.assertEqual(PROBE.normalise_domain("https://www.Example.com/"), "example.com")
        self.assertEqual(PROBE.normalise_domain("www.example.com"), "example.com")


class ParsingTests(unittest.TestCase):
    def test_direct_response_yields_retrieved_and_cited_in_order(self):
        signals = PROBE.extract_signals(direct_response(
            ["https://a.com/1", "https://example.com/p", "https://a.com/1"],
            ["https://example.com/p"],
        ))
        self.assertEqual([r["url"] for r in signals["retrieved"]], ["https://a.com/1", "https://example.com/p"])
        self.assertEqual([c["url"] for c in signals["cited"]], ["https://example.com/p"])
        self.assertEqual(signals["queries_issued"], ["widget suppliers texas"])
        self.assertEqual(signals["web_search_requests"], 1)
        self.assertEqual(signals["search_errors"], [])

    def test_dynamic_filtered_response_parses_the_same(self):
        signals = PROBE.extract_signals(filtered_response(["https://b.com/"], ["https://b.com/"]))
        self.assertEqual([r["url"] for r in signals["retrieved"]], ["https://b.com/"])
        self.assertEqual([c["url"] for c in signals["cited"]], ["https://b.com/"])

    def test_search_error_object_is_recorded_not_indexed(self):
        resp = direct_response([], [])
        resp["content"][2]["content"] = {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}
        signals = PROBE.extract_signals(resp)
        self.assertEqual(signals["search_errors"], ["max_uses_exceeded"])
        self.assertEqual(signals["retrieved"], [])

    def test_empty_result_list_is_no_results_not_an_error(self):
        signals = PROBE.extract_signals(direct_response([], []))
        self.assertEqual(signals["retrieved"], [])
        self.assertEqual(signals["search_errors"], [])


class RequestShapeTests(unittest.TestCase):
    def test_request_carries_tool_location_and_no_site_names(self):
        body = PROBE.build_request("How do I pick a supplier?", {
            "model": "claude-sonnet-5-5", "search_tool": "web_search_20250305", "max_uses": 3,
            "max_tokens": 512, "user_location": {"city": "Houston", "country": "US"}, "blocked_domains": [],
        })
        tool = body["tools"][0]
        self.assertEqual(tool["type"], "web_search_20250305")
        self.assertEqual(tool["max_uses"], 3)
        self.assertEqual(tool["user_location"]["type"], "approximate")
        self.assertEqual(tool["user_location"]["city"], "Houston")
        self.assertNotIn("blocked_domains", tool)
        self.assertEqual(body["messages"][0]["content"], "How do I pick a supplier?")
        self.assertNotIn("example", body["system"].lower())


class AggregationTests(unittest.TestCase):
    def site(self):
        return {"name": "Example Co", "domain": "example.com", "questions": ["q"], "_domains": ["example.com"]}

    def write_fixture(self, directory, site, question, index, response):
        path = pathlib.Path(directory) / PROBE.fixture_key(site, question, index)
        path.write_text(json.dumps(response), encoding="utf-8")

    def test_cited_in_one_of_two_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_fixture(tmp, "Example Co", "q", 0, direct_response(["https://example.com/"], ["https://example.com/"]))
            self.write_fixture(tmp, "Example Co", "q", 1, direct_response(["https://rival.com/", "https://example.com/"], ["https://rival.com/"]))
            settings = {"model": "m", "search_tool": "t", "repeats": 2, "max_uses": 1, "user_location": None}
            probe = PROBE.run_probe(self.site(), "q", settings, None, pathlib.Path(tmp), 10)
        self.assertEqual(probe["outcome"], "CITED")
        self.assertEqual(probe["cited_runs"], 1)
        self.assertEqual(probe["retrieved_runs"], 2)
        self.assertEqual(probe["runs"][1]["site_best_rank"], 2)
        self.assertEqual(probe["runs"][0]["citations"], [{"url": "https://example.com/", "cited_text": "snippet", "via": "annotation"}])
        self.assertNotIn("cited", probe["runs"][0])
        summary = PROBE.summarise_site(self.site(), [probe])
        self.assertEqual(summary["status"], "CITED")
        self.assertEqual(summary["cited_rate"], 0.5)
        self.assertEqual(summary["competing_cited_domains"], [{"domain": "rival.com", "runs": 1}])

    def test_retrieved_but_never_cited_is_a_content_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_fixture(tmp, "Example Co", "q", 0, direct_response(["https://example.com/"], ["https://rival.com/"]))
            settings = {"model": "m", "search_tool": "t", "repeats": 1, "max_uses": 1, "user_location": None}
            probe = PROBE.run_probe(self.site(), "q", settings, None, pathlib.Path(tmp), 10)
        self.assertEqual(probe["outcome"], "RETRIEVED")
        self.assertEqual(PROBE.summarise_site(self.site(), [probe])["status"], "RETRIEVED")

    def test_missing_fixture_is_an_error_run_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = {"model": "m", "search_tool": "t", "repeats": 1, "max_uses": 1, "user_location": None}
            probe = PROBE.run_probe(self.site(), "q", settings, None, pathlib.Path(tmp), 10)
        self.assertEqual(probe["outcome"], "ERROR")
        self.assertIn("no fixture", probe["runs"][0]["error"])
        self.assertEqual(PROBE.summarise_site(self.site(), [probe])["status"], "ERROR")

    def test_refusal_stop_reason_is_surfaced_as_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_fixture(tmp, "Example Co", "q", 0, direct_response([], [], stop_reason="refusal"))
            settings = {"model": "m", "search_tool": "t", "repeats": 1, "max_uses": 1, "user_location": None}
            probe = PROBE.run_probe(self.site(), "q", settings, None, pathlib.Path(tmp), 10)
        self.assertEqual(probe["outcome"], "ERROR")
        self.assertIn("refusal", probe["runs"][0]["error"])


class CliTests(unittest.TestCase):
    def test_cli_runs_offline_against_the_example_config_and_fixtures(self):
        root = pathlib.Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "latest.json"
            md = pathlib.Path(tmp) / "latest.md"
            proc = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--config", str(root / "probes.example.json"),
                 "--fixtures", str(root / "tests" / "fixtures" / "citation_probe"),
                 "--output", str(out), "--markdown", str(md)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["source"], "fixtures")
            self.assertEqual(payload["sites"][0]["status"], "CITED")
            report = md.read_text(encoding="utf-8")
            self.assertIn("# LLM citation scoreboard", report)
            self.assertIn("| Example Co | `claude-sonnet-5-5` | CITED |", report)
            self.assertEqual(payload["sites"][0]["models"][0]["model"], "claude-sonnet-5-5")

    def test_cli_refuses_to_run_live_without_a_key(self):
        root = pathlib.Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--config", str(root / "probes.example.json"),
                 "--output", f"{tmp}/o.json", "--markdown", f"{tmp}/o.md"],
                capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("ANTHROPIC_API_KEY", proc.stderr)


class OpenRouterTests(unittest.TestCase):
    def settings(self, **extra):
        base = {"engine": "openrouter", "model": "anthropic/claude-sonnet-5.5", "search_tool": "ignored",
                "repeats": 1, "max_uses": 3, "max_tokens": 512, "user_location": None, "blocked_domains": []}
        base.update(extra)
        return base

    def test_request_uses_native_server_tool_and_forwards_location(self):
        body = PROBE.build_openrouter_request("q?", self.settings(user_location={"city": "Houston", "country": "US"}))
        self.assertEqual(body["model"], "anthropic/claude-sonnet-5.5")
        tool = body["tools"][0]
        self.assertEqual(tool["type"], "openrouter:web_search")
        self.assertEqual(tool["parameters"]["engine"], "native")
        self.assertEqual(tool["parameters"]["max_uses"], 3)
        self.assertEqual(tool["parameters"]["user_location"]["type"], "approximate")
        self.assertNotIn("excluded_domains", tool["parameters"])
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body["messages"][1]["content"], "q?")

    def test_annotations_become_citations_and_retrieved_mirrors_cited(self):
        signals = PROBE.extract_openrouter_signals(openrouter_response(["https://a.com/", "https://example.com/p", "https://a.com/"]))
        self.assertEqual([c["url"] for c in signals["cited"]], ["https://a.com/", "https://example.com/p"])
        self.assertEqual([r["url"] for r in signals["retrieved"]], ["https://a.com/", "https://example.com/p"])
        self.assertEqual(signals["web_search_requests"], 2)
        self.assertEqual(signals["input_tokens"], 80)
        self.assertEqual(signals["usage_raw"], {"prompt_tokens": 80, "completion_tokens": 40})

    def test_error_object_raises_runtime_error(self):
        with self.assertRaises(RuntimeError):
            PROBE.extract_openrouter_signals(openrouter_response([], error={"code": 402, "message": "insufficient credits"}))
        with self.assertRaises(RuntimeError):
            PROBE.extract_openrouter_signals({"choices": []})

    def test_content_filter_is_reported_as_refusal(self):
        signals = PROBE.extract_openrouter_signals(openrouter_response([], finish="content_filter"))
        self.assertEqual(signals["stop_reason"], "refusal")

    def test_fixture_run_end_to_end(self):
        site = {"name": "Example Co", "domain": "example.com", "questions": ["q"], "_domains": ["example.com"]}
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / PROBE.fixture_key("Example Co", "q", 0)
            path.write_text(json.dumps(openrouter_response(["https://www.example.com/"])), encoding="utf-8")
            probe = PROBE.run_probe(site, "q", self.settings(), None, pathlib.Path(tmp), 10)
        self.assertEqual(probe["outcome"], "CITED")
        self.assertEqual(probe["runs"][0]["site_best_rank"], 1)

    def test_cli_names_the_openrouter_key_when_missing(self):
        root = pathlib.Path(__file__).parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--config", str(root / "probes.example.json"), "--engine", "openrouter",
                 "--output", f"{tmp}/o.json", "--markdown", f"{tmp}/o.md"],
                capture_output=True, text=True, timeout=60, env={"PATH": "/usr/bin:/bin"},
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("OPENROUTER_API_KEY", proc.stderr)


class GuardTests(unittest.TestCase):
    def test_markdown_links_in_the_answer_count_as_citations(self):
        resp = openrouter_response([])
        resp["choices"][0]["message"]["content"] = "See [example.com](https://example.com/page) and [a](https://a.com/)."
        signals = PROBE.extract_openrouter_signals(resp)
        self.assertEqual([c["url"] for c in signals["cited"]], ["https://example.com/page", "https://a.com/"])
        self.assertEqual(signals["cited"][0]["via"], "markdown_link")
        direct = direct_response([], [])
        direct["content"][-1]["text"] = "Answer [src](https://b.com/x)."
        self.assertEqual([c["url"] for c in PROBE.extract_signals(direct)["cited"]], ["https://b.com/x"])

    def test_openrouter_cost_is_read_from_usage(self):
        resp = openrouter_response(["https://a.com/"]); resp["usage"]["cost"] = 0.0123
        self.assertEqual(PROBE.extract_openrouter_signals(resp)["cost_usd"], 0.0123)
        self.assertIsNone(PROBE.extract_openrouter_signals(openrouter_response([]))["cost_usd"])

    def test_auth_and_credit_errors_are_fatal_and_not_retried(self):
        import io, urllib.error
        calls = []
        def fake_urlopen(request, timeout=0):
            calls.append(1)
            raise urllib.error.HTTPError(request.full_url, 402, "Payment Required", {}, io.BytesIO(b'{"error":"no credit"}'))
        original = PROBE.urllib.request.urlopen
        PROBE.urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(PROBE.FatalProbeError):
                PROBE.call_api({"x": 1}, "key", 5, engine="openrouter")
        finally:
            PROBE.urllib.request.urlopen = original
        self.assertEqual(len(calls), 1)

    def test_cli_spend_guard_stops_the_run_and_marks_it_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = pathlib.Path(tmp) / "fx"; fx.mkdir()
            cfg = {"defaults": {"engine": "openrouter", "repeats": 1},
                   "probes": [{"name": "Example Co", "domain": "example.com", "questions": ["q1", "q2", "q3"]}]}
            (pathlib.Path(tmp) / "probes.json").write_text(json.dumps(cfg))
            for q in cfg["probes"][0]["questions"]:
                resp = openrouter_response(["https://example.com/"]); resp["usage"]["cost"] = 0.6
                (fx / PROBE.fixture_key("Example Co", q, 0)).write_text(json.dumps(resp))
            out = pathlib.Path(tmp) / "o.json"
            proc = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--config", f"{tmp}/probes.json", "--fixtures", str(fx),
                 "--max-spend", "1.0", "--output", str(out), "--markdown", f"{tmp}/o.md"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 2, proc.stderr)
            payload = json.loads(out.read_text())
            self.assertIn("spend guard", payload["stopped_early"])
            self.assertEqual(len(payload["sites"][0]["models"][0]["probes"]), 2)
            self.assertAlmostEqual(payload["spend_usd"], 1.2)
            self.assertIn("stopped early", (pathlib.Path(tmp) / "o.md").read_text())


class MultiModelTests(unittest.TestCase):
    def test_openrouter_runs_every_model_and_rolls_up_the_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = pathlib.Path(tmp) / "fx"; fx.mkdir()
            cfg = {"defaults": {"engine": "openrouter", "repeats": 1,
                                "openrouter_models": ["openai/gpt-5.5", "perplexity/sonar"]},
                   "probes": [{"name": "Example Co", "domain": "example.com", "questions": ["q1"]}]}
            (pathlib.Path(tmp) / "probes.json").write_text(json.dumps(cfg))
            # Fixtures are keyed by site+question+run, so both models read the same file.
            (fx / PROBE.fixture_key("Example Co", "q1", 0)).write_text(json.dumps(openrouter_response(["https://example.com/"])))
            out = pathlib.Path(tmp) / "o.json"; md = pathlib.Path(tmp) / "o.md"
            proc = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--config", f"{tmp}/probes.json", "--fixtures", str(fx),
                 "--output", str(out), "--markdown", str(md)],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(out.read_text())
            self.assertEqual(payload["models"], ["openai/gpt-5.5", "perplexity/sonar"])
            site = payload["sites"][0]
            self.assertEqual([m["model"] for m in site["models"]], ["openai/gpt-5.5", "perplexity/sonar"])
            self.assertEqual(site["status"], "CITED")
            self.assertEqual(site["completed_runs"], 2)
            report = md.read_text()
            self.assertIn("| Example Co | `openai/gpt-5.5` | CITED |", report)
            self.assertIn("| Example Co | `perplexity/sonar` | CITED |", report)

    def test_cli_model_flag_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = pathlib.Path(tmp) / "fx"; fx.mkdir()
            cfg = {"defaults": {"engine": "openrouter", "repeats": 1},
                   "probes": [{"name": "Example Co", "domain": "example.com", "questions": ["q1"]}]}
            (pathlib.Path(tmp) / "probes.json").write_text(json.dumps(cfg))
            (fx / PROBE.fixture_key("Example Co", "q1", 0)).write_text(json.dumps(openrouter_response([])))
            out = pathlib.Path(tmp) / "o.json"
            proc = subprocess.run(
                [sys.executable, str(MODULE_PATH), "--config", f"{tmp}/probes.json", "--fixtures", str(fx),
                 "--model", "a/one", "--model", "b/two", "--output", str(out), "--markdown", f"{tmp}/o.md"],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(out.read_text())
            self.assertEqual(payload["models"], ["a/one", "b/two"])
            self.assertEqual(payload["sites"][0]["status"], "ABSENT")

    def test_rollup_prefers_the_best_status_and_pools_runs(self):
        site = {"name": "S", "_domains": ["s.com"]}
        a = {"status": "ABSENT", "completed_runs": 2, "cited_runs": 0, "retrieved_runs": 0}
        b = {"status": "RETRIEVED", "completed_runs": 2, "cited_runs": 0, "retrieved_runs": 1}
        roll = PROBE.rollup_site(site, [a, b])
        self.assertEqual(roll["status"], "RETRIEVED")
        self.assertEqual(roll["retrieved_rate"], 0.25)
        self.assertEqual(PROBE.rollup_site(site, [{"status": "ERROR", "completed_runs": 0, "cited_runs": 0, "retrieved_runs": 0}])["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
