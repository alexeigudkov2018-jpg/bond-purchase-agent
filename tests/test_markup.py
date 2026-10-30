import tempfile
import unittest
from pathlib import Path

from engine.markup import (
    COST_MAX,
    COST_MIN,
    DEFAULT_REVENUE_MIX,
    TARGET_MARGIN_MAX,
    TARGET_MARGIN_MIN,
    band_for,
    build_report,
    margin_from_markup,
    markup_pct,
    money_margin,
    price_csv,
    quote,
    schedule,
    sell_price,
)


class MarkupCurveTests(unittest.TestCase):
    def test_cheap_edge_up_to_1000(self):
        self.assertEqual(markup_pct(1), 1000)
        self.assertEqual(markup_pct(5), 1000)

    def test_fifty_to_hundred_strengthened(self):
        self.assertEqual(markup_pct(50), 400)
        self.assertEqual(markup_pct(75), 350)
        self.assertEqual(markup_pct(100), 280)
        self.assertGreaterEqual(markup_pct(75), 280)
        self.assertLessEqual(markup_pct(75), 350)

    def test_expensive_edge_twenty_five_markup_is_twenty_margin(self):
        self.assertEqual(markup_pct(180_000), 25)
        self.assertAlmostEqual(margin_from_markup(25) * 100, 20.0, places=6)
        priced = quote(180_000)
        self.assertEqual(priced.price, 225_000.0)
        self.assertEqual(priced.margin_pct, 20.0)

    def test_middle_has_many_soft_steps(self):
        bands = [row for row in schedule() if row["cost_from"] >= 500 and row["cost_to"] <= 100_000]
        self.assertGreaterEqual(len(bands), 10)
        markups = [row["markup_pct"] for row in bands]
        self.assertEqual(markups, sorted(markups, reverse=True))
        self.assertLess(markups[0], 280)
        self.assertGreater(markups[-1], 25)

    def test_regressive_across_range(self):
        costs = [1, 5, 50, 100, 500, 5_000, 50_000, 180_000]
        rates = [markup_pct(cost) for cost in costs]
        self.assertEqual(rates, sorted(rates, reverse=True))

    def test_sell_price_and_band(self):
        self.assertEqual(sell_price(100), 380.0)
        low, high = band_for(90)
        self.assertEqual(low, 75)
        self.assertEqual(high, 100)

    def test_rejects_below_minimum(self):
        with self.assertRaises(ValueError):
            markup_pct(0.5)

    def test_above_max_keeps_floor(self):
        self.assertEqual(markup_pct(COST_MAX + 1), 25)

    def test_target_money_margin_on_default_mix(self):
        margin = money_margin(list(DEFAULT_REVENUE_MIX))
        self.assertGreaterEqual(margin, TARGET_MARGIN_MIN)
        self.assertLessEqual(margin, TARGET_MARGIN_MAX)

    def test_report_shape(self):
        report = build_report()
        self.assertEqual(report["cost_range"]["min"], COST_MIN)
        self.assertEqual(report["cost_range"]["max"], COST_MAX)
        self.assertEqual(len(report["schedule"]), 23)
        self.assertEqual(report["samples"][0]["markup_pct"], 1000)

    def test_price_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sku.csv"
            src.write_text("sku,cost\nA,5\nB,100\nC,180000\n", encoding="utf-8")
            out = price_csv(src)
            text = out.read_text(encoding="utf-8")
            self.assertIn("sell_price", text)
            self.assertIn("380.0", text)
            self.assertIn("225000.0", text)


if __name__ == "__main__":
    unittest.main()
