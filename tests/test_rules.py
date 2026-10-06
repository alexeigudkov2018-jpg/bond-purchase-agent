import unittest
from datetime import date

from engine.cashflows import after_tax_ytm, naive_haircut, xirr
from engine.corpbonds import _normalize_rating, rating_group
from engine.rules import broker_for_month
from engine.scoring import (
    coverage_points,
    credit_quality_points,
    g_spread_points,
    issuer_quality_points,
    leverage_points,
    score_corporate,
)
from engine.dohod import blocker, group_from_text
from engine.select import _size, ban_reason, sector_exception


class ScoringTests(unittest.TestCase):
    def test_g_spread_boundaries(self):
        self.assertEqual(g_spread_points(79.99)[0], 0)
        self.assertEqual(g_spread_points(80)[0], 1)
        self.assertEqual(g_spread_points(129.99)[0], 1)
        self.assertEqual(g_spread_points(130)[0], 2)
        self.assertEqual(g_spread_points(199.99)[0], 2)
        self.assertEqual(g_spread_points(200)[0], 3)
        self.assertEqual(g_spread_points(600)[0], 3)
        self.assertEqual(g_spread_points(600.01)[0], 0)

    def test_leverage_boundaries(self):
        self.assertEqual(leverage_points(1.99)[0], 3)
        self.assertEqual(leverage_points(2)[0], 2)
        self.assertEqual(leverage_points(2.99)[0], 2)
        self.assertEqual(leverage_points(3)[0], 1)
        self.assertEqual(leverage_points(4)[0], 1)
        self.assertEqual(leverage_points(4.01)[0], 0)

    def test_coverage_boundaries(self):
        self.assertEqual(coverage_points(5.01)[0], 2)
        self.assertEqual(coverage_points(5)[0], 1)
        self.assertEqual(coverage_points(3)[0], 1)
        self.assertEqual(coverage_points(2.99)[0], 0)

    def test_quality_fallbacks_are_labeled(self):
        self.assertEqual(credit_quality_points(7)[0], 3)
        self.assertEqual(credit_quality_points(5.5)[0], 2)
        self.assertEqual(credit_quality_points(4)[0], 1)
        self.assertEqual(credit_quality_points(3.99)[0], 0)
        self.assertEqual(issuer_quality_points(7)[0], 2)
        self.assertEqual(issuer_quality_points(5)[0], 1)
        self.assertEqual(issuer_quality_points(4.99)[0], 0)
        scored = score_corporate(
            g_spread_bp=250,
            net_debt_ebitda=None,
            ebitda_interest=None,
            credit_quality=8,
            issuer_quality=6,
            coupon_period_days=30,
            rating_confirmed=True,
        )
        self.assertTrue(scored["passed"])
        self.assertTrue(any(part["substituted"] for part in scored["parts"]))

    def test_threshold_without_financials(self):
        tight = score_corporate(
            g_spread_bp=10,
            net_debt_ebitda=None,
            ebitda_interest=None,
            credit_quality=None,
            issuer_quality=None,
            coupon_period_days=91,
            rating_confirmed=True,
        )
        self.assertFalse(tight["passed"])
        wide = score_corporate(
            g_spread_bp=250,
            net_debt_ebitda=None,
            ebitda_interest=None,
            credit_quality=None,
            issuer_quality=None,
            coupon_period_days=30,
            rating_confirmed=True,
        )
        self.assertEqual(wide["total"], 5)
        self.assertTrue(wide["passed"])


class RuleTests(unittest.TestCase):
    def test_broker_rotation(self):
        self.assertEqual(broker_for_month(10)["id"], "alfa")
        self.assertEqual(broker_for_month(9)["id"], "sber")
        self.assertEqual(broker_for_month(10)["agreement"], "5737728")
        self.assertEqual(broker_for_month(11)["agreement"], "4225FH3")

    def test_bans_and_container_exception(self):
        self.assertIn("РЖД", ban_reason("ОАО «Российские железные дороги»", "Транспорт"))
        self.assertIn("МТС", ban_reason("ПАО МТС", "Телеком"))
        self.assertIn("лизинг", ban_reason("ВТБ Лизинг", "Лизинг"))
        self.assertIsNone(ban_reason("ПАО ТрансКонтейнер", "Транспорт"))
        self.assertTrue(sector_exception("ПКТ"))
        self.assertIsNone(ban_reason("Первая контейнерная компания", "ж/д вагоны"))

    def test_dohod_screener_gates(self):
        self.assertEqual(group_from_text("AA"), "aa")
        self.assertEqual(group_from_text("A"), "a")
        self.assertEqual(group_from_text("BBB"), "below")
        clean = {
            "currency": "RUB",
            "coupon_type": "1",
            "event": "погашение",
            "eventFlag": "SIMPLE,ONTRADE",
            "emitent_type": "корпоративные",
        }
        self.assertIsNone(blocker(clean))
        put = dict(clean, event="право продать (put)", eventFlag="PUT,ONTRADE")
        self.assertIn("погашение", blocker(put))
        floater = dict(clean, coupon_type="3", eventFlag="FLT,ONTRADE")
        self.assertIn("фиксированный", blocker(floater))

    def test_rating_scale(self):
        self.assertEqual(_normalize_rating("ruAAA"), "AAA")
        self.assertEqual(_normalize_rating("АА-"), "AA-")
        self.assertEqual(rating_group("AA-"), "aa")
        self.assertEqual(rating_group("A-"), "a")
        self.assertEqual(rating_group("BBB+"), "below")

    def test_size_respects_minimum_and_cash(self):
        sized = _size(dirty=530.5, lot=1, slot_target=55_084, cash_left=170_000, rate=0.00291)
        self.assertIsNotNone(sized)
        self.assertGreaterEqual(sized["position_sum"], 45_000)
        self.assertLessEqual(sized["debit"], 170_000)
        too_big = _size(dirty=60_000, lot=1, slot_target=55_000, cash_left=170_000, rate=0.003)
        self.assertIsNone(too_big)

    def test_after_tax_is_not_a_flat_haircut(self):
        asof = date(2026, 10, 6)
        coupons = [
            {"date": "2027-04-06", "amount": 40.0},
            {"date": "2027-10-06", "amount": 40.0},
            {"date": "2028-04-06", "amount": 40.0},
            {"date": "2028-10-06", "amount": 40.0},
        ]
        tax = after_tax_ytm(
            asof=asof,
            clean_price=900,
            nkd=10,
            face=1000,
            coupons=coupons,
            tax_rate=0.13,
            maturity=date(2028, 10, 6),
        )
        self.assertIsNotNone(tax["ytm"])
        pretax = xirr([
            (asof, -910),
            (date(2027, 4, 6), 40),
            (date(2027, 10, 6), 40),
            (date(2028, 4, 6), 40),
            (date(2028, 10, 6), 1040),
        ])
        self.assertIsNotNone(pretax)
        haircut = naive_haircut(pretax * 100, 0.13)
        self.assertNotAlmostEqual(tax["ytm"], haircut, places=2)


if __name__ == "__main__":
    unittest.main()
