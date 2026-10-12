"""Предварительный пакет по выгрузке 12 октября."""

from __future__ import annotations

import unittest

from engine.preview import build_preview


class PreviewPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_preview()

    def test_alfa_tuesday_and_two_longest_ofz(self):
        report = self.report
        self.assertEqual(report["tuesday"], "2026-10-13")
        self.assertEqual(report["broker"]["agreement"], "5737728")
        self.assertEqual(report["budget"]["contribution"], 170_000)
        names = [item["shortname"] for item in report["package"]]
        self.assertEqual(names, ["ОФЗ 26238", "ОФЗ 26230"])
        self.assertGreaterEqual(report["weights"]["ytm"], 16)
        self.assertIsNone(report["weights"]["ytm_after_tax"])
        self.assertGreater(report["cash"]["remainder"] / 170_000, 0.10)
        self.assertEqual(report["cash"]["positions"], 2)
        debit = sum(item["debit"] for item in report["package"])
        self.assertAlmostEqual(debit + report["cash"]["remainder"], 170_000, places=2)

    def test_corporate_slot_stays_empty(self):
        report = self.report
        self.assertTrue(all(item["slot_id"] == "ofz" for item in report["package"]))
        self.assertEqual(len(report["waitlist"]), 2)
        self.assertEqual({item["shortname"] for item in report["waitlist"]}, {"Атомэнпр09", "Атомэнпр10"})
        self.assertTrue(all(item["score"] < 5 for item in report["waitlist"]))
        self.assertEqual(report["review"], [])

    def test_equal_terms_exceptions_and_bans(self):
        report = self.report
        exceptions = {item["isin"]: item for item in report["exceptions"]}
        self.assertIn("RU000A10ER66", exceptions)
        self.assertLess(exceptions["RU000A10ER66"]["years"], 4)
        rejected = {item["shortname"]: item["reason"] for item in report["rejected"]}
        self.assertIn("ПГК3Р01", rejected)
        self.assertIn("РЖД 1Р-44R", rejected)
        self.assertIn("ПКТ 2P2", rejected)
        self.assertIn("нет оборота", rejected["ПКТ 2P2"])
        self.assertTrue(any("досрочное" in reason for reason in rejected.values()))
        fpk = next(item for item in report["exceptions"] if item["shortname"] == "ФПК2Р01")
        self.assertTrue(fpk["flags"])

    def test_median_is_not_called_a_passed_average(self):
        text = " ".join(self.report["caveats"])
        self.assertIn("медиана", text.lower())
        self.assertTrue(all(item["median_mln"] > 20 for item in self.report["package"]))
        self.assertTrue(all(item["g_spread_clamped"] for item in self.report["exceptions"]))


if __name__ == "__main__":
    unittest.main()
