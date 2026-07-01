"""Test offline (nessuna chiamata di rete/LLM) della logica critica:
qualificazione pre-seed, estrazione testo, parsing fonti, store con migrazione.

Esegui:  .venv/bin/python -m unittest test_pipeline -v
"""

import os
import tempfile
import unittest

import qualify
import email_finder
import store
from sources import hackernews


class TestQualify(unittest.TestCase):
    def _q(self, **record):
        return qualify.qualify_record(record)

    def test_seed_funding_type_excluded(self):
        r = self._q(company_name="X", country="United States", last_funding_type="seed")
        self.assertFalse(r["qualified"])
        self.assertIn("oltre il pre-seed", r["exclude_reason"])

    def test_series_a_excluded(self):
        r = self._q(company_name="X", country="Germany", last_funding_type="series_a")
        self.assertFalse(r["qualified"])

    def test_total_raised_over_threshold_excluded(self):
        r = self._q(company_name="X", country="US", last_funding_type="pre_seed",
                    total_raised=5_000_000)
        self.assertFalse(r["qualified"])

    def test_preseed_total_under_threshold_kept(self):
        r = self._q(company_name="X", country="US", last_funding_type="pre_seed",
                    total_raised=500_000)
        self.assertTrue(r["qualified"])

    def test_angel_bootstrapped_us_kept(self):
        r = self._q(company_name="X", country="United States", last_funding_type="angel")
        self.assertTrue(r["qualified"])

    def test_geo_outside_excluded(self):
        r = self._q(company_name="X", country="India", stage="pre-seed")
        self.assertFalse(r["qualified"])
        self.assertIn("area target", r["exclude_reason"])

    def test_geo_non_target_tld_excluded(self):
        r = self._q(company_name="X", website="https://foo.in", stage="pre-seed")
        self.assertFalse(r["qualified"])

    def test_eu_tld_unknown_country_kept(self):
        r = self._q(company_name="X", website="https://foo.de", stage="pre-seed")
        self.assertTrue(r["qualified"])

    def test_unknown_geo_kept_low_confidence(self):
        # .com ambiguo + paese sconosciuto: tenuto ma bassa confidenza.
        r = self._q(company_name="X", website="https://foo.com", stage="pre-seed",
                    source="producthunt")
        self.assertTrue(r["qualified"])
        self.assertEqual(r["preseed_confidence"], "low")

    def test_site_text_series_a_excluded(self):
        r = self._q(company_name="X", country="US",
                    _site_text="We are thrilled to announce we raised $5M in our Series A led by Acme Ventures.")
        self.assertFalse(r["qualified"])
        self.assertIn("funding sul sito", r["exclude_reason"])

    def test_site_text_preseed_kept(self):
        r = self._q(company_name="X", country="US",
                    _site_text="We are currently raising our pre-seed round to build the MVP.")
        self.assertTrue(r["qualified"])

    def test_llm_raised_beyond_flag_excluded(self):
        r = self._q(company_name="X", country="US", raised_beyond_preseed=True)
        self.assertFalse(r["qualified"])

    def test_stage_series_a_plus_excluded(self):
        r = self._q(company_name="X", country="US", stage="series-a-plus")
        self.assertFalse(r["qualified"])

    def test_show_hn_stage_kept(self):
        r = self._q(company_name="X", country="United States",
                    stage="pre-seed (Show HN launch)", source="hackernews")
        self.assertTrue(r["qualified"])

    def test_strong_source_high_confidence(self):
        r = self._q(company_name="X", country="United States", source="antler")
        self.assertEqual(r["preseed_confidence"], "high")  # geo noto + fonte forte


class TestBeyondFundingText(unittest.TestCase):
    def test_preseed_not_flagged(self):
        self.assertIsNone(qualify._beyond_funding_in_text("closing our pre-seed round now"))
        self.assertIsNone(qualify._beyond_funding_in_text("pre seed funding secured"))

    def test_seed_round_flagged(self):
        self.assertIsNotNone(qualify._beyond_funding_in_text("we closed a seed round"))

    def test_series_flagged(self):
        self.assertIsNotNone(qualify._beyond_funding_in_text("announcing our Series B"))

    def test_no_signal(self):
        self.assertIsNone(qualify._beyond_funding_in_text("we build developer tools"))


class TestExtractText(unittest.TestCase):
    def test_strips_scripts_and_collapses(self):
        html = "<html><head><style>.a{}</style></head><body><script>var x=1;</script>" \
               "<h1>Hello</h1>\n\n   <p>World  foo</p></body></html>"
        text = email_finder._extract_text(html)
        self.assertNotIn("var x", text)
        self.assertNotIn(".a{", text)
        self.assertEqual(text, "Hello World foo")

    def test_empty(self):
        self.assertEqual(email_finder._extract_text(""), "")
        self.assertEqual(email_finder._extract_text(None), "")


class TestHackerNews(unittest.TestCase):
    def test_clean_name(self):
        self.assertEqual(hackernews._clean_name("Show HN: Acme – a tool for X"), "Acme")
        self.assertEqual(hackernews._clean_name("Show HN: Acme - a tool"), "Acme")
        self.assertEqual(hackernews._clean_name("Launch HN: Beta Co: does things"), "Beta Co")
        self.assertEqual(hackernews._clean_name("Show HN: Gamma"), "Gamma")


class TestStoreMigration(unittest.TestCase):
    def test_new_columns_and_qualified_filter(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            recs = [
                {"company_name": "Good", "website": "https://good.com", "stage": "pre-seed",
                 "country": "US", "source": "antler", "qualified": 1,
                 "preseed_confidence": "high", "exclude_reason": None, "_enriched": True,
                 "stage_reason": "no funding signal"},
                {"company_name": "Bad", "website": "https://bad.com", "stage": "seed",
                 "country": "US", "source": "yc", "qualified": 0,
                 "preseed_confidence": "high", "exclude_reason": "stage 'seed' oltre il pre-seed"},
            ]
            store.upsert_records(recs, db_path=path)

            only_qualified = store.get_startups(path, {})
            names = {r["company_name"] for r in only_qualified}
            self.assertEqual(names, {"Good"})

            with_excluded = store.get_startups(path, {"show_excluded": True})
            names2 = {r["company_name"] for r in with_excluded}
            self.assertEqual(names2, {"Good", "Bad"})

            existing = store.get_existing_by_key(path)
            good = existing["good.com"]
            self.assertEqual(good["preseed_confidence"], "high")
            self.assertTrue(good["enriched_at"])  # enriched_at valorizzato
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
