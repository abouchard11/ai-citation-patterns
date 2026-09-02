import importlib.util
import pathlib
import unittest
import urllib.error


MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "geo_aeo_audit.py"
SPEC = importlib.util.spec_from_file_location("geo_aeo_audit", MODULE_PATH)
AUDIT = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(AUDIT)


class AuditTests(unittest.TestCase):
    def test_page_parser_extracts_core_signals(self):
        page = AUDIT.PageParser()
        page.feed(
            """<html><head><title>Example</title>
            <meta name="description" content="An answer page">
            <link rel="canonical" href="https://example.com/">
            <script async src="https://news.google.com/swg/js/v1/publisher.js"></script>
            <script type="application/ld+json">{"@type":"Article"}</script></head>
            <body><h1>One answer</h1><h2>Evidence</h2>
            <div google-add-preferred-source-btn></div><p>Useful text.</p></body></html>"""
        )
        self.assertEqual(page.title, "Example")
        self.assertEqual(page.h1, ["One answer"])
        self.assertEqual(page.canonical, "https://example.com/")
        self.assertTrue(page.preferred_source)
        self.assertEqual(AUDIT.schema_types(page.jsonld), ["Article"])

    def test_robots_separates_search_and_training(self):
        rules = """User-agent: *
Allow: /
User-agent: GPTBot
Disallow: /
"""
        allowed = AUDIT.inspect_robots(rules, "https://example.com/")
        self.assertTrue(allowed["OAI-SearchBot"])
        self.assertFalse(allowed["GPTBot"])

    def test_sitemap_detects_fake_today_freshness(self):
        today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat()
        xml = f"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://example.com/</loc><lastmod>{today}</lastmod></url>
        <url><loc>https://example.com/a</loc><lastmod>{today}</lastmod></url>
        </urlset>"""
        result = AUDIT.inspect_sitemap(xml)
        self.assertEqual(result["kind"], "urlset")
        self.assertEqual(result["entry_count"], 2)
        self.assertTrue(result["all_lastmods_today"])

    def test_sitemap_index_does_not_mislabel_children_as_page_urls(self):
        xml = """<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap><loc>https://example.com/posts.xml</loc></sitemap>
        </sitemapindex>"""
        result = AUDIT.inspect_sitemap(xml)
        self.assertEqual(result["kind"], "sitemapindex")
        self.assertEqual(result["entry_count"], 1)

    def test_claim_flags_are_review_prompts_not_truth_judgments(self):
        flags = AUDIT.claim_flags("Example Lab Certified", ["Example Lab Certified", "example-claim"])
        self.assertEqual(flags, ["Example Lab Certified"])

    def test_claim_flags_survive_an_unparseable_pattern(self):
        # One bad regex in a config file must not abort the whole portfolio run.
        flags = AUDIT.claim_flags("anything", ["valid", "(unclosed"])
        self.assertTrue(any(f.startswith("INVALID_PATTERN:(unclosed") for f in flags))

    def test_malformed_json_ld_is_reported_not_counted_as_schema(self):
        # The INVALID_JSON_LD sentinel is truthy, so the old "if not schema_types"
        # check let a page with only broken JSON-LD pass as if it had schema.
        self.assertEqual(AUDIT.schema_types(["{not json"]), ["INVALID_JSON_LD"])


class SubstantiationTests(unittest.TestCase):
    TODAY = __import__("datetime").date(2026, 9, 2)

    def _ledger(self, **overrides):
        record = {"site": "S", "claim": "C", "status": "RESOLVED", "expires_on": "2027-01-01"}
        record.update(overrides)
        return {("S", "C"): record}

    def test_unexpired_evidence_silences_the_flag(self):
        out = AUDIT.apply_substantiation("S", ["C"], self._ledger(), self.TODAY)
        self.assertEqual(out["substantiated"], ["C"])
        self.assertEqual(out["unsubstantiated"], [])

    def test_expired_evidence_reopens_the_flag(self):
        out = AUDIT.apply_substantiation("S", ["C"], self._ledger(expires_on="2026-01-01"), self.TODAY)
        self.assertEqual(out["expired"], ["C"])
        self.assertEqual(out["substantiated"], [])

    def test_evidence_without_an_expiry_is_treated_as_expired(self):
        out = AUDIT.apply_substantiation("S", ["C"], self._ledger(expires_on=None), self.TODAY)
        self.assertEqual(out["expired"], ["C"])

    def test_missing_record_stays_flagged(self):
        out = AUDIT.apply_substantiation("S", ["C"], {}, self.TODAY)
        self.assertEqual(out["unsubstantiated"], ["C"])

    def test_open_record_stays_flagged(self):
        out = AUDIT.apply_substantiation("S", ["C"], self._ledger(status="OPEN"), self.TODAY)
        self.assertEqual(out["unsubstantiated"], ["C"])

    def test_claim_marked_removed_but_still_live_is_surfaced(self):
        out = AUDIT.apply_substantiation("S", ["C"], self._ledger(status="REMOVED"), self.TODAY)
        self.assertEqual(out["removed_but_present"], ["C"])


class FetchPolicyTests(unittest.TestCase):
    def test_settled_status_codes_are_not_retried(self):
        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append(request.get_full_url())
            raise urllib.error.HTTPError(request.get_full_url(), 404, "Not Found", {}, None)

        original = AUDIT.urllib.request.urlopen
        AUDIT.urllib.request.urlopen = fake_urlopen
        try:
            with self.assertRaises(urllib.error.HTTPError):
                AUDIT.fetch_text("https://example.com/robots.txt", 1.0, attempts=3)
        finally:
            AUDIT.urllib.request.urlopen = original
        self.assertEqual(len(calls), 1, "a 404 must not be retried")

    def test_transient_failure_is_retried(self):
        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append(1)
            raise urllib.error.HTTPError(request.get_full_url(), 503, "Unavailable", {}, None)

        original_open, original_sleep = AUDIT.urllib.request.urlopen, AUDIT.time.sleep
        AUDIT.urllib.request.urlopen = fake_urlopen
        AUDIT.time.sleep = lambda _: None
        try:
            with self.assertRaises(urllib.error.HTTPError):
                AUDIT.fetch_text("https://example.com/", 1.0, attempts=2)
        finally:
            AUDIT.urllib.request.urlopen = original_open
            AUDIT.time.sleep = original_sleep
        self.assertEqual(len(calls), 2, "a 503 should be retried")


class RobotsAbsenceTests(unittest.TestCase):
    PAGE = (
        '<html><head><title>T</title><link rel="canonical" href="https://example.com/">'
        '<meta name="description" content="d">'
        '<script type="application/ld+json">{"@type":"Article"}</script></head>'
        "<body><h1>H</h1><p>word word word</p></body></html>"
    )

    def test_missing_robots_txt_permits_crawling_and_is_not_a_failure(self):
        # RFC 9309: an unavailable robots.txt means unrestricted crawling.
        # This previously produced a FAIL on every site without one.
        def fake_fetch(url, timeout, attempts=2, user_agent=AUDIT.USER_AGENT):
            if url.endswith("robots.txt"):
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            if url.endswith("sitemap.xml"):
                return (
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<url><loc>https://example.com/</loc></url></urlset>",
                    200,
                    url,
                )
            return self.PAGE, 200, url

        original = AUDIT.fetch_text
        AUDIT.fetch_text = fake_fetch
        try:
            result = AUDIT.audit_site(
                {"name": "S", "url": "https://example.com/", "minimum_words": 1},
                1.0,
                probe_bots=False,
            )
        finally:
            AUDIT.fetch_text = original

        self.assertFalse(result["robots"]["present"])
        self.assertTrue(all(result["robots"]["allowed"].values()))
        self.assertNotIn(
            "robots.txt", " ".join(result["errors"]), "missing robots.txt must not be an error"
        )
        self.assertEqual(result["status"], "PASS")

    def test_a_real_robots_failure_is_still_an_error(self):
        def fake_fetch(url, timeout, attempts=2, user_agent=AUDIT.USER_AGENT):
            if url.endswith("robots.txt"):
                raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)
            if url.endswith("sitemap.xml"):
                return (
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    "<url><loc>https://example.com/</loc></url></urlset>",
                    200,
                    url,
                )
            return self.PAGE, 200, url

        original = AUDIT.fetch_text
        AUDIT.fetch_text = fake_fetch
        try:
            result = AUDIT.audit_site(
                {"name": "S", "url": "https://example.com/", "minimum_words": 1},
                1.0,
                probe_bots=False,
            )
        finally:
            AUDIT.fetch_text = original
        self.assertIn("robots.txt fetch failed", " ".join(result["errors"]))


class BotProbeTests(unittest.TestCase):
    def test_edge_refusal_of_a_bot_user_agent_is_recorded_as_blocked(self):
        def fake_fetch(url, timeout, attempts=2, user_agent=AUDIT.USER_AGENT):
            if "Googlebot" in user_agent:
                raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
            return "ok", 200, url

        original = AUDIT.fetch_text
        AUDIT.fetch_text = fake_fetch
        try:
            probe = AUDIT.probe_bot_access("https://example.com/", 1.0)
        finally:
            AUDIT.fetch_text = original

        self.assertTrue(probe["results"]["Googlebot"]["blocked"])
        self.assertFalse(probe["results"]["bingbot"]["blocked"])
        self.assertIn("does NOT", probe["caveat"])

    def test_every_probed_bot_has_a_published_user_agent(self):
        for bot in AUDIT.BOT_USER_AGENTS:
            self.assertIn(bot, AUDIT.SEARCH_BOTS)


if __name__ == "__main__":
    unittest.main()
