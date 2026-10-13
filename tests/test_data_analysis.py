import csv
import math
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from ashare_monitor.analysis import analyze_stock, atr, ema, rsi
from ashare_monitor.data import (DEFAULT_WATCHLIST, _csv_stock, _eastmoney_stock,
                                 load_market, security_info, validate_candles)


def candle(day="2026-10-12", price=10):
    return {"date": day, "open": price, "high": price + 1, "low": price - 1,
            "close": price, "volume": 10000, "amount": price * 10000}


def series(count=120):
    result, day = [], date(2025, 1, 2)
    while len(result) < count:
        if day.weekday() < 5:
            result.append(candle(day.isoformat(), 20 + len(result) * 0.05 + math.sin(len(result) / 5) * 0.5))
        day += timedelta(days=1)
    return result


class ValidationTests(unittest.TestCase):
    def test_default_universe_contains_eight_ordinary_shares(self):
        self.assertEqual(len(DEFAULT_WATCHLIST), 8)
        self.assertEqual(security_info("600519")["exchange"], "SSE")
        self.assertEqual(security_info("300750")["board"], "growth")
        self.assertEqual(security_info("688981")["board"], "star")
        for invalid in ["../../secret", "A600519", "510300", "60051", 600519]:
            with self.subTest(code=invalid), self.assertRaises(ValueError):
                security_info(invalid)

    def test_bad_rows_are_rejected_not_repaired(self):
        examples = []
        for field in ["open", "high", "low", "close", "volume", "amount"]:
            for invalid in [float("nan"), float("inf"), -1]:
                examples.append([{**candle(), field: invalid}])
        examples.extend([
            [candle("2026-02-30")], [candle("2026-10-11")],
            [{**candle(), "high": 9}], [{**candle(), "low": 11}],
            [candle(), candle()], [candle("2026-10-13"), candle("2026-10-12")],
        ])
        for rows in examples:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                validate_candles(rows)

    def test_future_bar_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_candles([candle("2026-10-13")], "2026-10-12")

    def test_zero_volume_valid_but_price_zero_invalid(self):
        self.assertEqual(validate_candles([{**candle(), "volume": 0}])[0]["volume"], 0)
        with self.assertRaises(ValueError):
            validate_candles([{**candle(), "close": 0}])


class DemoTests(unittest.TestCase):
    def test_demo_is_offline_reproducible_and_forward_consistent(self):
        with patch("ashare_monitor.data.urlopen", side_effect=AssertionError("must remain offline")):
            earlier = load_market("demo", DEFAULT_WATCHLIST, "2026-10-09")
            later = load_market("demo", DEFAULT_WATCHLIST, "2026-10-12")
            repeat = load_market("demo", DEFAULT_WATCHLIST, "2026-10-09")
        self.assertEqual(earlier["errors"], [])
        self.assertIn("合成", earlier["source"])
        for left, right, again in zip(earlier["stocks"], later["stocks"], repeat["stocks"]):
            self.assertEqual(left["candles"], again["candles"])
            self.assertEqual(left["candles"], right["candles"][:len(left["candles"])])
            self.assertEqual(len(right["candles"]), len(left["candles"]) + 1)
            self.assertEqual(left["candles"], left["raw_candles"])
            self.assertTrue(left["metadata_verified"])
            self.assertEqual(left["mode"], "demo")

    def test_demo_holidays_are_excluded(self):
        market = load_market("demo", ["600519"], "2026-10-09")
        dates = {r["date"] for r in market["stocks"][0]["candles"]}
        for holiday in ("2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"):
            self.assertNotIn(holiday, dates)

    def test_invalid_request_rejected(self):
        for mode, codes in [("fake", ["600519"]), ("demo", []), ("demo", ["600519", "600519"])]:
            with self.assertRaises(ValueError):
                load_market(mode, codes, "2026-10-12")

    def test_custom_code_does_not_invent_listing_metadata(self):
        stock = load_market("demo", ["600000"], "2026-10-12")["stocks"][0]
        self.assertFalse(stock["metadata_verified"])
        self.assertIsNone(stock["listing_date"])
        self.assertIsNone(stock["risk_warning"])


class RealAdapterTests(unittest.TestCase):
    def test_online_failure_is_not_replaced_by_demo(self):
        with patch("ashare_monitor.rules.last_closed_day", return_value="2026-10-12"), \
             patch("ashare_monitor.data._request_json", side_effect=TimeoutError):
            market = load_market("eastmoney", ["600519"], "2026-10-12")
        stock = market["stocks"][0]
        self.assertEqual(stock["status"], "unavailable")
        self.assertEqual(stock["candles"], [])
        self.assertEqual(stock["mode"], "eastmoney")
        self.assertTrue(market["errors"])

    def test_units_and_raw_price_are_kept_separate(self):
        adjusted = {"data": {"name": "示例股票", "code": "600519", "klines": ["2026-10-12,10,11,12,9,200,220000"]}}
        raw = {"data": {"name": "示例股票", "code": "600519", "klines": ["2026-10-12,20,22,24,18,200,440000"]}}
        with patch("ashare_monitor.data._request_json", side_effect=[adjusted, raw]):
            stock = _eastmoney_stock("600519", "2026-10-12")
        self.assertEqual(stock["candles"][0]["volume"], 20000)
        self.assertEqual(stock["candles"][0]["close"], 11)
        self.assertEqual(stock["raw_candles"][0]["close"], 22)
        self.assertFalse(stock["metadata_verified"])
        self.assertIsNone(stock["listing_date"])

    def test_raw_failure_keeps_analysis_but_no_execution_reference(self):
        adjusted = {"data": {"code": "600519", "klines": ["2026-10-12,10,11,12,9,200,220000"]}}
        with patch("ashare_monitor.data._request_json", side_effect=[adjusted, TimeoutError()]):
            stock = _eastmoney_stock("600519", "2026-10-12")
        self.assertEqual(stock["status"], "ok")
        self.assertEqual(stock["raw_candles"], [])
        self.assertIn("原价", stock["error"])

    def test_future_request_rejected_before_network(self):
        with patch("ashare_monitor.rules.last_closed_day", return_value="2026-10-12"), \
             patch("ashare_monitor.data._request_json") as request:
            with self.assertRaises(ValueError):
                load_market("eastmoney", ["600519"], "2026-10-13")
        request.assert_not_called()

    def test_delayed_source_is_marked_stale_and_retryable(self):
        response = {"data": {"code": "600519", "klines": ["2026-10-09,10,11,12,9,200,220000"]}}
        with patch("ashare_monitor.rules.last_closed_day", return_value="2026-10-12"), \
             patch("ashare_monitor.data._request_json", return_value=response):
            market = load_market("eastmoney", ["600519"], "2026-10-12")
        stock = market["stocks"][0]
        self.assertEqual(stock["status"], "ok")
        self.assertEqual(stock["as_of"], "2026-10-12")
        self.assertEqual(stock["stale_as_of"], "2026-10-12")
        self.assertTrue(stock["stale"])
        self.assertTrue(market["errors"])
        self.assertIn("停牌", stock["error"])
        self.assertEqual(stock["data_date"], "2026-10-09")


class CSVTests(unittest.TestCase):
    def write_csv(self, root, rows, fields=None):
        fields = fields or list(rows[0])
        with (Path(root) / "600519.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_unknown_adjustment_is_explicit_and_not_reliable_raw(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_csv(root, [candle()])
            stock = _csv_stock("600519", "2026-10-12", root)
        self.assertEqual(stock["adjustment"], "none")
        self.assertFalse(stock["adjustment_verified"])
        self.assertEqual(stock["raw_candles"], [])

    def test_declared_raw_and_asof_filter(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_csv(root, [{**candle("2026-10-09"), "adjustment": "none"}, {**candle(), "adjustment": "none"}])
            stock = _csv_stock("600519", "2026-10-09", root)
        self.assertEqual(len(stock["candles"]), 1)
        self.assertEqual(stock["candles"], stock["raw_candles"])

    def test_invalid_rows_do_not_become_silent_empty_series(self):
        with tempfile.TemporaryDirectory() as root:
            self.write_csv(root, [candle(), candle()])
            with self.assertRaises(ValueError):
                _csv_stock("600519", "2026-10-12", root)

    def test_qfq_requires_separate_raw_columns(self):
        row = {**candle(), "adjustment": "qfq", "raw_open": 20, "raw_high": 22, "raw_low": 18, "raw_close": 21}
        with tempfile.TemporaryDirectory() as root:
            self.write_csv(root, [row])
            stock = _csv_stock("600519", "2026-10-12", root)
        self.assertEqual(stock["candles"][0]["close"], 10)
        self.assertEqual(stock["raw_candles"][0]["close"], 21)


class IndicatorTests(unittest.TestCase):
    def test_indicator_known_values(self):
        self.assertEqual(ema([1, 2, 3, 4], 3), [None, None, 2, 3])
        self.assertEqual(rsi([10] * 30)[-1], 50)
        self.assertEqual(rsi(list(range(1, 31)))[-1], 100)
        self.assertEqual(rsi(list(range(30, 0, -1)))[-1], 0)
        self.assertEqual(atr([candle()] * 20)[-1], 2)

    def test_short_and_missing_data_distinguished(self):
        missing = analyze_stock({"code": "600519", "status": "unavailable"})
        short = analyze_stock({"code": "600519", "status": "ok", "candles": series(10)})
        self.assertEqual(missing["status"], "unavailable")
        self.assertEqual(short["status"], "insufficient")
        self.assertIsNone(short["score"])
        self.assertIsNone(short["plan"])

    def test_score_is_transparent_and_plan_uses_original_prices(self):
        rows = series()
        raw = [{**r, **{field: r[field] * 2 for field in ("open", "high", "low", "close")}} for r in rows]
        result = analyze_stock({"code": "600519", "status": "ok", "candles": rows, "raw_candles": raw})
        self.assertEqual(result["score"], sum(result["indicators"]["score_components"].values()))
        self.assertAlmostEqual(result["plan"]["reference_price"], raw[-1]["close"], places=4)
        self.assertGreater(result["plan"]["target_price"], result["plan"]["reference_price"])
        self.assertLess(result["plan"]["stop_price"], result["plan"]["reference_price"])
        self.assertIn("不是盈利概率", result["notice"])

    def test_future_changes_cannot_rewrite_past_history(self):
        rows = series(150)
        early = analyze_stock({"code": "600519", "status": "ok", "candles": rows[:100]})
        later_rows = rows[:100] + [{**r, **{key: r[key] * 2 for key in ("open", "high", "low", "close")}} for r in rows[100:]]
        later = analyze_stock({"code": "600519", "status": "ok", "candles": later_rows})
        self.assertEqual(early["history"], [r for r in later["history"] if r["date"] <= rows[99]["date"]])
        full_ema = ema([r["close"] for r in later_rows], 20)
        self.assertEqual(full_ema[:100], ema([r["close"] for r in rows[:100]], 20))

    def test_absent_or_misaligned_raw_cannot_create_price_plan(self):
        rows = series()
        for raw in [[], rows[:-1]]:
            result = analyze_stock({"status": "ok", "candles": rows, "raw_candles": raw})
            self.assertIsNone(result["plan"])

    def test_stale_high_score_does_not_become_current_opportunity(self):
        rows = series()
        fresh = analyze_stock({"status": "ok", "candles": rows, "raw_candles": rows})
        stale = analyze_stock({"status": "ok", "candles": rows, "raw_candles": rows, "as_of": "2026-10-12"})
        self.assertEqual(fresh["status"], "watch")
        self.assertEqual(stale["status"], "wait")
        self.assertTrue(stale["stale"])
        self.assertIsNone(stale["plan"])
        self.assertEqual(stale["score"], fresh["score"])
        self.assertEqual(stale["history"], fresh["history"])
        self.assertTrue(any("历史状态" in r for r in stale["reasons"]))


if __name__ == "__main__":
    unittest.main()
