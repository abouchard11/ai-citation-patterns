import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).parents[1]
MODULE_PATH = ROOT / "scripts" / "render_dashboard.py"
SPEC = importlib.util.spec_from_file_location("render_dashboard", MODULE_PATH)
RD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(RD)


def old_schema(date, rate):
    return {"generated_at": f"{date}T08:00:00+00:00", "engine": "openrouter", "model": "anthropic/claude-sonnet-5.5",
            "total_searches": 4, "sites": [{"name": "A", "domains": ["a.com"], "status": "CITED" if rate else "ABSENT",
            "cited_rate": rate, "completed_runs": 2, "cited_runs": int(rate * 2),
            "competing_cited_domains": [{"domain": "rival.com", "runs": 1}],
            "probes": [{"question": "q1", "outcome": "CITED" if rate else "ABSENT", "completed_runs": 2, "cited_runs": int(rate * 2)}]}]}


def new_schema(date):
    m = lambda slug, st, r: {"model": slug, "status": st, "cited_rate": r, "retrieved_rate": r, "completed_runs": 1,
                             "cited_runs": int(r), "probes": [{"question": "q1", "outcome": st, "completed_runs": 1, "cited_runs": int(r)}],
                             "competing_cited_domains": [{"domain": "rival.com", "runs": 1}], "skipped": None}
    return {"generated_at": f"{date}T08:00:00+00:00", "engine": "openrouter", "models": ["openai/gpt-5.5", "perplexity/sonar"],
            "spend_usd": 1.23, "total_searches": 6, "retrieved_exposed": False, "stopped_early": None,
            "sites": [{"name": "A", "domains": ["a.com"], "status": "CITED", "cited_rate": 0.5,
                       "models": [m("openai/gpt-5.5", "CITED", 1.0), m("perplexity/sonar", "ABSENT", 0.0)]},
                      {"name": "B", "domains": ["b.com"], "status": "ABSENT", "cited_rate": 0.0,
                       "models": [m("openai/gpt-5.5", "ABSENT", 0.0), m("perplexity/sonar", "ABSENT", 0.0)]}]}


class RenderTests(unittest.TestCase):
    def test_both_schemas_normalise_to_models(self):
        old = RD.normalise(old_schema("2026-10-13", 0.5))
        self.assertEqual([m["model"] for m in old["sites"][0]["models"]], ["anthropic/claude-sonnet-5.5"])
        new = RD.normalise(new_schema("2026-10-20"))
        self.assertEqual(new["models"], ["openai/gpt-5.5", "perplexity/sonar"])
        self.assertEqual(new["sites"][0]["status"], "CITED")
        self.assertEqual(new["sites"][1]["status"], "ABSENT")

    def test_sparkline_needs_two_points_and_scales(self):
        self.assertEqual(RD.sparkline([0.5], ["d1"]), "")
        svg = RD.sparkline([0.0, 1.0], ["d1", "d2"])
        self.assertIn("<svg", svg)
        self.assertIn("d1: 0%, d2: 100%", svg)

    def test_cli_renders_history_and_to_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "2026-10-13.json").write_text(json.dumps(old_schema("2026-10-13", 0.5)))
            (d / "2026-10-20.json").write_text(json.dumps(new_schema("2026-10-20")))
            (d / "latest.json").write_text(json.dumps(new_schema("2026-10-20")))
            out = d / "dashboard.html"
            proc = subprocess.run([sys.executable, str(MODULE_PATH), "--snapshots", str(d), "--output", str(out)],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            page = out.read_text()
            self.assertIn("<title>Citation Scoreboard</title>", page)
            self.assertIn("OpenAI GPT-5.5", page)
            self.assertIn("<svg", page)               # A has two points of history
            self.assertIn("first run", page)          # B has one
            self.assertIn("<strong>B</strong>: not surfaced anywhere", page)
            self.assertIn("$1.23", page)
            self.assertIn("rival.com", page)
            self.assertNotIn("http", page.split("<body")[0]) if "<body" in page else None


if __name__ == "__main__":
    unittest.main()
