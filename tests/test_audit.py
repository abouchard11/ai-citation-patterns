import importlib.util
import pathlib
import unittest


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


if __name__ == "__main__":
    unittest.main()
