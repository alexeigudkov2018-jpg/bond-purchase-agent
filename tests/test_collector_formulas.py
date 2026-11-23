import unittest
from datetime import date
from urllib.robotparser import RobotFileParser

from scripts.collect import jobs_for, previous_trading_day
from scripts.formulas import (
    SOLAR_V1_DIVISOR,
    adj_factor_on,
    beta_from_returns,
    flow_share,
    global_drawdowns,
    instant_step,
    monthly_return_pct,
    notable,
    ofz_repricing,
    pearson,
    propose_tone,
    rolling_rai,
    seasonality,
    solar_weight_sum,
    ssn_smooth_v1,
    stop_cap,
    total_return_pct,
    valuation,
    weak_windows,
    weekday_stats,
    zigzag_episodes,
)
from scripts.parse_sources import (
    gfz_monthly,
    key_rate_events,
    parse_cbr_keyrate_html,
    parse_cbr_metals,
    parse_fred_brent,
    parse_gfz_daily,
    parse_noaa_solar,
    parse_silso_csv,
    parse_smartlab_html,
    weather_monthly,
    parse_meteostat_daily,
)


class FormulaTests(unittest.TestCase):
    def test_monthly_and_total_return_are_percent(self):
        self.assertAlmostEqual(monthly_return_pct(100, 110), 10.0)
        self.assertAlmostEqual(total_return_pct(100, 110, 5), 15.0)
        self.assertIsNone(monthly_return_pct(0, 10))

    def test_pearson_and_beta(self):
        asset = [1.0, 2.0, 3.0, 4.0]
        index = [1.0, 2.0, 3.0, 5.0]
        corr, n = pearson(asset, index)
        self.assertEqual(n, 4)
        self.assertGreater(corr, 0.9)
        beta, _ = beta_from_returns(asset, index)
        self.assertAlmostEqual(beta, corr * (asset and __import__("numpy").std(asset, ddof=1) / __import__("numpy").std(index, ddof=1)))
        self.assertEqual(notable(0.25), 1)
        self.assertEqual(notable(0.24), 0)

    def test_seasonality_marks_short_sample_and_drops_2022(self):
        rows = [("2022-01", -10.0), ("2023-01", 10.0), ("2024-01", 30.0)]
        stats = seasonality(rows)
        self.assertEqual(stats["n_years"], 3)
        self.assertEqual(stats["sample_lt_6"], 1)
        self.assertAlmostEqual(stats["avg"][0], 10.0)
        self.assertAlmostEqual(stats["ex2022"][0], 20.0)
        self.assertAlmostEqual(stats["hit"][0], 2 / 3)

    def test_weekday_uses_trading_days(self):
        dates = [date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 18)]
        closes = [100.0, 110.0, 99.0]
        stats = {row["weekday"]: row for row in weekday_stats(dates, closes)}
        self.assertAlmostEqual(stats["вт"]["mean_pct"], 10.0)
        self.assertAlmostEqual(stats["ср"]["mean_pct"], -10.0)

    def test_zigzag_and_rai_and_drawdown(self):
        dates = [date(2026, 1, d) for d in range(1, 9)]
        prices = [100, 100, 110, 104, 90, 95, 120, 113]
        episodes = zigzag_episodes(dates, prices, 5)
        done = [row for row in episodes if row["completed"] == "да"]
        self.assertEqual(len(done), 1)
        self.assertAlmostEqual(done[0]["depth_pct"], (110 - 90) / 110 * 100)
        self.assertAlmostEqual(done[0]["rebound_pct"], (120 / 90 - 1) * 100)
        self.assertEqual(done[0]["fall_days"], 2)
        self.assertEqual(done[0]["rec_days"], 2)
        self.assertAlmostEqual(done[0]["asym"], 1.0)
        rai = rolling_rai(len(prices), episodes, window=len(prices))
        self.assertAlmostEqual(rai[-1], done[0]["rec_speed"] / done[0]["fall_speed"])
        self.assertIsNone(rolling_rai(len(prices), episodes, window=126)[-1])
        drawdowns = global_drawdowns(dates + [date(2026, 1, 9)], prices + [80], 10)
        self.assertTrue(any(row["depth_pct"] >= 10 for row in drawdowns))

    def test_plan_steps_and_stop(self):
        self.assertEqual(instant_step(14, "flat", 0.5), 0)
        self.assertEqual(instant_step(13, "flat", 0.5), 1)
        self.assertEqual(instant_step(13, "up", 0.5), 0)
        self.assertEqual(instant_step(12, "flat", 0.5), 2)
        self.assertEqual(instant_step(9.5, "flat", 0.5), 3)
        self.assertIsNone(instant_step(10, "flat", 1.2))
        stop = stop_cap("flat", [1.2, 1.3], months_limit=2)
        self.assertFalse(stop["active"])
        self.assertEqual(stop["months_to_trigger"], 1)
        self.assertTrue(stop_cap("up", [], months_limit=2)["active"])
        self.assertEqual(weak_windows(date(2026, 11, 23)), [])
        self.assertIn("feb", weak_windows(date(2026, 2, 5)))

    def test_solar_weights_are_66_not_64(self):
        self.assertEqual(solar_weight_sum(), 66)
        self.assertNotEqual(solar_weight_sum(), SOLAR_V1_DIVISOR)
        smooth = ssn_smooth_v1([1.0] * 13)
        self.assertAlmostEqual(smooth[6], 66 / 64)

    def test_valuation_skips_ps_for_banks(self):
        bank = valuation(100, 10, 50, 20, 80, 5, 15, 4, "SBER")
        other = valuation(100, 10, 50, 20, 80, 5, 15, 4, "GAZP")
        self.assertEqual(bank["applicable_ps"], 0)
        self.assertIsNone(bank["ps"])
        self.assertAlmostEqual(other["ps"], 1000 / 50)
        self.assertAlmostEqual(other["div_yield_pct"], 4.0)
        self.assertAlmostEqual(flow_share(10, 0.5, 0.1), 0.3)
        self.assertAlmostEqual(ofz_repricing(5, 0.01), -0.05)

    def test_split_and_consolidation_factors(self):
        actions = [
            {"date": "2024-07-13", "type": "consolidation", "ratio": "5000:1"},
            {"date": "2024-04-01", "type": "split", "ratio": "10:1"},
        ]
        self.assertAlmostEqual(adj_factor_on("2024-01-01", actions), 10 * (1 / 5000))
        self.assertAlmostEqual(adj_factor_on("2024-08-01", actions), 1.0)

    def test_tone_lexicon_does_not_invent_neutral(self):
        self.assertEqual(propose_tone("Банк России снизил ключевую ставку"), 2)
        self.assertEqual(propose_tone("мобилизация"), -2)
        self.assertIsNone(propose_tone("биржа закрылась разнонаправленно"))

    def test_parsers_and_robots(self):
        html = "<tr><td>20.11.2026</td><td>16,50</td></tr><tr><td>23.11.2026</td><td>14,00</td></tr>"
        obs = parse_cbr_keyrate_html(html)
        events = key_rate_events(obs)
        self.assertEqual(events[0]["decision"], "cut")
        self.assertEqual(parse_fred_brent("DATE,DCOILBRENTEU\n2026-11-20,62.1\n2026-11-21,.\n")[1]["brent"], None)
        solar = parse_noaa_solar([{"time-tag": "2026-10", "ssn": 45.7, "smoothed_ssn": -1, "f10.7": 108.47}])
        self.assertIsNone(solar[0]["ssn_smooth13"])
        self.assertEqual(solar[0]["ssn"], 45.7)
        parser = RobotFileParser()
        parser.parse(["User-agent: *", "Disallow: /"])
        self.assertFalse(parser.can_fetch("*", "https://iss.moex.com/iss/securities/SMLT.json"))

    def test_modes_follow_section_42(self):
        today = date(2026, 11, 23)
        self.assertEqual(previous_trading_day(today), date(2026, 11, 20))
        daily = jobs_for("daily", today)
        self.assertEqual(daily["market_from"], date(2026, 11, 20))
        self.assertTrue(daily["iss_market"] and daily["metals"] and not daily["fundamentals"])
        weekly = jobs_for("weekly", today)
        self.assertTrue(weekly["solar"] and weekly["weather"] and weekly["iss_reference"] and weekly["weekly_digest"])
        self.assertEqual(weekly["note"], "")
        self.assertIn("не в понедельник", jobs_for("weekly", date(2026, 11, 24))["note"])
        monthly = jobs_for("monthly", today)
        self.assertTrue(monthly["monthly_digest"])
        self.assertIn("не 1-го", monthly["note"])
        quarterly = jobs_for("quarterly", date(2026, 1, 15))
        self.assertTrue(quarterly["fundamentals"])
        self.assertEqual(quarterly["note"], "")
        backfill = jobs_for("backfill", today)
        self.assertEqual(backfill["market_from"], date(2021, 1, 4))
        self.assertTrue(backfill["weather"] and backfill["solar"] and backfill["fundamentals"])

    def test_macro_parsers(self):
        xml = (
            '<?xml version="1.0" encoding="windows-1251"?>'
            '<Metall><Record Date="20.11.2026" Code="1"><Sell>9902,42</Sell></Record></Metall>'
        )
        metals = parse_cbr_metals(xml.encode("cp1251"))
        self.assertEqual(metals[0]["date"], "2026-11-20")
        self.assertAlmostEqual(metals[0]["gold"], 9902.42)
        silso = parse_silso_csv("1749;01;1749.042;  96.7; -1.0;   -1;1\n", "ssn")
        self.assertEqual(silso[0]["month"], "1749-01")
        self.assertAlmostEqual(silso[0]["ssn"], 96.7)
        line = "1932 01 01 0 0.5 1352 10 3.333 2.667 2.333 2.667 3.333 2.667 3.333 3.333 18 12 9 12 18 12 18 18 15 22 -1.0 -1.0 2"
        monthly = gfz_monthly(parse_gfz_daily(line), "1932-01")
        self.assertAlmostEqual(monthly[0]["ap"], 15)
        self.assertAlmostEqual(monthly[0]["kpmax"], 3.333)
        self.assertAlmostEqual(monthly[0]["sn_gfz"], 22)
        daily = [{"date": f"1991-01-{day:02d}", "tmean": 1.0} for day in range(1, 25)]
        daily.append({"date": "1991-01-25", "tmean": 1.0})
        short = [{"date": f"1991-02-{day:02d}", "tmean": 1.0} for day in range(1, 11)]
        months = weather_monthly(parse_meteostat_daily("\n".join(f"{row['date']},{row['tmean']}" for row in daily + short)))
        self.assertEqual([row["month"] for row in months], ["1991-01"])
        html = (
            "<tr><td>Name</td><td>&nbsp;</td><td><strong>2024</strong></td></tr>"
            "<tr><td>Выручка , млрд руб</td><td>?</td><td></td><td>10</td></tr>"
            "<tr><td>Дата отчета</td><td></td><td></td><td>02.03.2025</td></tr>"
        )
        report = parse_smartlab_html(html, "IFRS")
        self.assertEqual(report[0]["period_end"], "2024-12-31")
        self.assertAlmostEqual(report[0]["revenue"], 10_000_000_000)
        self.assertEqual(report[0]["reported_at"], "2025-03-02")


if __name__ == "__main__":
    unittest.main()
