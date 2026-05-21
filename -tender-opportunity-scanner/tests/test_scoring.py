"""
Minimal smoke tests for the scoring engine.

Run with:
    python3 -m unittest tests.test_scoring

These tests guard against regressions in the scoring logic: a high-fit
WA subsea tender should always score well above threshold, and a clearly
wrong-industry tender should always score well below it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from scanner import scoring


ROOT = Path(__file__).resolve().parent.parent


class ScoringTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.cfg = scoring.load_config(ROOT / "config" / "keywords.yaml")

    def _score(self, tender: dict) -> scoring.Score:
        # Provide sensible defaults for fields not relevant to a test
        full = {
            "tender_id": "TEST-001",
            "title": "",
            "agency": "",
            "description": "",
            "location": "",
            "category": "",
            "value_aud_min": 0,
            "value_aud_max": 0,
            "published_date": "2026-01-01",
            "closing_date": "2027-01-01",
            "source": "test",
            "url": "",
        }
        full.update(tender)
        return scoring.score_tender(full, self.cfg)

    def test_strong_match_qualifies(self):
        s = self._score({
            "title": "Subsea Inspection — North West Shelf",
            "description": "ROV inspection and pipeline integrity, Western Australia",
            "location": "Western Australia",
            "category": "Oil and Gas",
            "value_aud_min": 3_000_000,
            "value_aud_max": 5_000_000,
        })
        self.assertTrue(s.qualified, f"Expected qualified, got score={s.raw_score}")
        self.assertGreater(s.display_score, 80)

    def test_wrong_industry_filtered(self):
        s = self._score({
            "title": "Office Furniture Supply",
            "description": "Supply and installation of office furniture",
            "category": "Office Supplies",
        })
        self.assertFalse(s.qualified)
        self.assertEqual(s.display_score, 0)

    def test_negative_keyword_penalises(self):
        # Catering on an offshore vessel — surface vocabulary matches subsea
        # work, but the negative keyword should pull the score down.
        s_with_neg = self._score({
            "title": "Catering Services — Offshore Vessel",
            "description": "Provision of catering services on offshore vessel",
        })
        s_without_neg = self._score({
            "title": "Offshore Vessel Services",
            "description": "Provision of services on offshore vessel",
        })
        self.assertLess(s_with_neg.raw_score, s_without_neg.raw_score)

    def test_wa_location_boosts_score(self):
        wa = self._score({
            "title": "ROV Inspection",
            "description": "ROV inspection services in Pilbara, Western Australia",
        })
        non_wa = self._score({
            "title": "ROV Inspection",
            "description": "ROV inspection services in coastal Queensland",
        })
        self.assertGreater(wa.raw_score, non_wa.raw_score)

    def test_negative_score_does_not_get_geographic_boost(self):
        # A tender with only negative signals shouldn't have its negative
        # score *multiplied* by being in WA — that would mislead.
        s = self._score({
            "title": "Cleaning Services — Perth",
            "description": "Cleaning services across Western Australia",
        })
        # If multiplier was applied to a negative base, raw_score would
        # be -20 * 1.3 = -26. We expect it to stay at -20 or similar.
        self.assertGreaterEqual(s.raw_score, -25)


if __name__ == "__main__":
    unittest.main()
