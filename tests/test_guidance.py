import json
import pathlib
import unittest

CATALOG = pathlib.Path(__file__).parents[1] / "guidance" / "citation-cues.json"
FIELDS = ("cause", "cue", "title", "oneLiner", "detail", "effort", "whereItGetsHard", "check", "brief", "source", "verified")


class CitationCueCatalogTests(unittest.TestCase):
    def setUp(self):
        self.doc = json.loads(CATALOG.read_text(encoding="utf-8"))

    def test_six_causes_each_with_every_field(self):
        self.assertEqual(self.doc["order"], ["D1", "D2", "D3", "D4", "D5", "D6"])
        self.assertEqual(sorted(self.doc["cues"]), self.doc["order"])
        for code, cue in self.doc["cues"].items():
            for field in FIELDS:
                self.assertTrue(cue.get(field), f"{code} is missing {field}")

    def test_the_index_cause_names_a_step_for_each_index_it_checks(self):
        steps = self.doc["cues"]["D2"]["stepsByIndex"]
        self.assertEqual(sorted(steps), ["bing", "brave", "google"])
        self.assertTrue(all(steps.values()))

    def test_work_order_covers_the_same_codes(self):
        self.assertEqual(sorted(self.doc["work_order"]), self.doc["order"])

    def test_every_entry_points_at_a_source_and_a_verified_date(self):
        for cue in self.doc["cues"].values():
            self.assertTrue(cue["source"].startswith("https://github.com/abouchard11/"))
            self.assertRegex(cue["verified"], r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
