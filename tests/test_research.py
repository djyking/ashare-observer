import copy
import json
import math
import unittest
from datetime import date, timedelta

from ashare_monitor.analysis import analyze_stock, ema
from ashare_monitor.research import _buy_quantity, normalize_research_config, run_research
from ashare_monitor.rules import is_trading_day
from ashare_monitor.strategies import normalize_strategy_config, strategy_catalog


def stock(count=130, code="600036", board="main"):
    rows, day = [], date(2025, 1, 2)
    while len(rows) < count:
        if is_trading_day(day):
            price = round(10 + len(rows) * 0.015 + math.sin(len(rows) / 5) * 0.04, 2)
            rows.append({"date": day.isoformat(), "open": price, "close": price + 0.01,
                         "high": price + 0.2, "low": price - 0.2, "volume": 1000000, "amount": price * 1000000})
        day += timedelta(days=1)
    return {"code": code, "name": "研究示例", "status": "ok", "board": board, "mode": "csv",
            "metadata_verified": False, "candles": rows, "raw_candles": copy.deepcopy(rows)}


def config_for(item, **overrides):
    config = {"start_date": item["candles"][59]["date"], "end_date": item["candles"][-1]["date"],
              "strategies": {"teaching": {"min_score": 0, "max_rsi": 100, "max_distance_pct": 30}},
              "max_holding_days": 1, "initial_cash": 100000, "position_pct": 30}
    return {**config, **overrides}


class StrategyTests(unittest.TestCase):
    def test_catalog_parameters_and_validation(self):
        catalog = strategy_catalog()
        self.assertEqual({item["id"] for item in catalog["strategies"]}, {"teaching", "pullback", "breakout"})
        for invalid in [{"unknown": {}}, {"teaching": {"enabled": 1}}, {"breakout": {"lookback": 2}},
                        {"pullback": {"min_rsi": 90, "max_rsi": 20}}, {"teaching": {"min_score": math.nan}}]:
            with self.subTest(config=invalid), self.assertRaises(ValueError):
                normalize_strategy_config(invalid)

    def test_chart_and_scores_use_identical_indicator_series(self):
        item = stock()
        result = analyze_stock(item)
        expected = ema([bar["close"] for bar in item["candles"]], 20)
        self.assertEqual(len(result["chart_series"]), len(item["candles"]))
        self.assertEqual([row["ema20"] for row in result["chart_series"]], [round(value, 6) if value is not None else None for value in expected])
        self.assertEqual(result["chart_series"][-1]["ema60"], result["indicators"]["ema60"])
        self.assertEqual(sum(item["score"] for item in result["score_components"]), result["score"])
        self.assertTrue(all(item["max_score"] == 20 for item in result["score_components"]))

    def test_disabled_strategies_remove_watch_without_changing_indicator_score(self):
        item = stock()
        before = analyze_stock(item)
        after = analyze_stock(item, {key: {"enabled": False} for key in ("teaching", "pullback", "breakout")})
        self.assertEqual(after["status"], "wait")
        self.assertEqual(after["score"], before["score"])
        self.assertFalse(any(result["matched"] for result in after["strategy_results"]))

    def test_historical_strategy_events_do_not_change_with_future_bars(self):
        item = stock()
        early = {**item, "candles": item["candles"][:90], "raw_candles": item["raw_candles"][:90]}
        end = early["candles"][-1]["date"]
        self.assertEqual(analyze_stock(early)["strategy_history"], [event for event in analyze_stock(item)["strategy_history"] if event["date"] <= end])


class ResearchTests(unittest.TestCase):
    def test_exact_minimum_commission_budget_does_not_double_count_fees(self):
        config = normalize_research_config()
        # 100 shares x 10 yuan + max(0.30, 5) commission = exactly 1005 yuan.
        self.assertEqual(_buy_quantity(1005, 10, "main", config, 1000000), 100)
        self.assertEqual(_buy_quantity(1004.99, 10, "main", config, 1000000), 0)
        # A fractional-lot board still respects its 200-share minimum.
        self.assertEqual(_buy_quantity(2005, 10, "star", config, 1000000), 200)
        self.assertEqual(_buy_quantity(2004.99, 10, "star", config, 1000000), 0)

    def test_real_research_is_isolated_next_open_t_plus_one_and_board_lots(self):
        item = stock()
        original = copy.deepcopy(item)
        report = run_research([item], config_for(item))
        self.assertEqual(item, original)
        self.assertTrue(report["trades"])
        first, second = report["trades"][:2]
        self.assertEqual(first["side"], "buy")
        self.assertEqual(first["signal_date"], item["candles"][59]["date"])
        self.assertEqual(first["date"], item["candles"][60]["date"])
        self.assertEqual(second["side"], "sell")
        self.assertEqual(second["date"], item["candles"][61]["date"])
        self.assertGreater(second["date"], first["date"])
        self.assertEqual(first["quantity"] % 100, 0)
        self.assertGreaterEqual(report["metrics"]["total_fees"], 10)
        self.assertTrue(any("未独立核实" in warning for warning in report["warnings"]))
        json.dumps(report, allow_nan=False)

    def test_future_data_cannot_change_prior_trades_or_equity(self):
        item = stock()
        earlier_end = item["candles"][90]["date"]
        short = run_research([item], config_for(item, end_date=earlier_end))
        full = run_research([item], config_for(item))
        self.assertEqual(short["trades"], [trade for trade in full["trades"] if trade["date"] <= earlier_end])
        self.assertEqual(short["equity_curve"], [point for point in full["equity_curve"] if point["date"] <= earlier_end])
        altered = copy.deepcopy(item)
        for collection in (altered["candles"], altered["raw_candles"]):
            for row in collection[91:]:
                for key in ("open", "high", "low", "close"):
                    row[key] *= 2
        short_again = run_research([altered], config_for(item, end_date=earlier_end))
        self.assertEqual(short, short_again)

    def test_fees_and_slippage_reduce_same_trade_returns(self):
        item = stock(66)
        cheap = run_research([item], config_for(item, commission_rate=0, minimum_commission=0, stamp_tax_rate=0, slippage_bps=0))
        costly = run_research([item], config_for(item, commission_rate=0.001, minimum_commission=5, stamp_tax_rate=0.001, slippage_bps=20))
        self.assertGreater(costly["trades"][0]["price"], cheap["trades"][0]["price"])
        self.assertLess(costly["trades"][1]["price"], cheap["trades"][1]["price"])
        self.assertLess(costly["metrics"]["final_equity"], cheap["metrics"]["final_equity"])
        sell = costly["trades"][1]
        buy = costly["trades"][0]
        self.assertAlmostEqual(sell["realized_pnl"], sell["notional"] - sell["fee"] - buy["notional"] - buy["fee"], places=2)

    def test_missing_next_day_expires_order_instead_of_delayed_fill(self):
        item = stock(65)
        missing_day = item["raw_candles"][60]["date"]
        item["raw_candles"] = [row for row in item["raw_candles"] if row["date"] != missing_day]
        report = run_research([item], config_for(item))
        rejection = next(row for row in report["rejections"] if row["date"] == missing_day)
        self.assertIn("缺少原价", rejection["reason"])
        self.assertFalse(any(row["signal_date"] == item["candles"][59]["date"] for row in report["trades"]))

    def test_limit_up_prevents_purchase(self):
        item = stock(65)
        yesterday = item["raw_candles"][59]["close"]
        price = round(yesterday * 1.1, 2)
        item["raw_candles"][60].update(open=price, close=price, high=price, low=price)
        item["candles"][60] = copy.deepcopy(item["raw_candles"][60])
        report = run_research([item], config_for(item, end_date=item["candles"][60]["date"]))
        self.assertEqual(report["trades"], [])
        self.assertTrue(any("涨停" in row["reason"] for row in report["rejections"]))

    def test_no_trade_is_valid_report_with_benchmark(self):
        item = stock(70)
        report = run_research([item], config_for(item, strategies={"teaching": {"min_score": 100, "max_rsi": 0}}))
        self.assertEqual(report["metrics"]["trade_count"], 0)
        self.assertIsNone(report["metrics"]["win_rate_pct"])
        self.assertEqual(report["metrics"]["final_equity"], 100000)
        self.assertNotEqual(report["metrics"]["benchmark_return_pct"], 0)
        self.assertTrue(report["warnings"])

    def test_special_stock_is_excluded_without_banning_real_sources(self):
        normal, risk = stock(), stock(code="600000")
        risk["name"] = "*ST示例"
        report = run_research([normal, risk], config_for(normal))
        self.assertEqual(report["excluded"][0]["code"], "600000")
        self.assertTrue(report["trades"])

    def test_known_listing_date_rejects_prelisting_history_even_if_unverified(self):
        normal = stock(70)
        for verified in (True, False):
            impossible = stock(70, code="600000")
            impossible["listing_date"] = impossible["candles"][62]["date"]
            impossible["metadata_verified"] = verified
            with self.subTest(metadata_verified=verified):
                report = run_research([normal, impossible], config_for(normal))
                self.assertEqual(report["excluded"][0]["code"], "600000")
                self.assertIn("上市日期", report["excluded"][0]["reason"])
                self.assertFalse(any(trade["code"] == "600000" for trade in report["trades"]))
        # A valid series beginning at listing still gets the normal 60-bar warm-up.
        normal["listing_date"] = normal["candles"][0]["date"]
        report = run_research([normal], config_for(normal))
        self.assertFalse(report["excluded"])
        self.assertEqual(report["trades"][0]["date"], normal["candles"][60]["date"])
        # Raw-only prelisting rows cannot bypass the same boundary.
        raw_only = stock(70, code="600000")
        raw_only["listing_date"] = raw_only["candles"][1]["date"]
        raw_only["candles"] = raw_only["candles"][1:]
        report = run_research([normal, raw_only], config_for(normal))
        self.assertIn("上市日期", report["excluded"][0]["reason"])

    def test_corporate_action_marks_result_unfit_as_performance(self):
        item = stock(70)
        for row in item["candles"][63:]:
            for key in ("open", "high", "low", "close"):
                row[key] *= 1.1
        report = run_research([item], config_for(item))
        self.assertEqual(report["quality"], "invalid_corporate_actions")
        self.assertTrue(any("公司行动" in warning for warning in report["warnings"]))

    def test_capital_slot_limits_and_star_minimum(self):
        one, two = stock(), stock(code="688981", board="star")
        report = run_research([one, two], config_for(one, max_positions=1, position_pct=100))
        self.assertTrue(any("同时持仓上限" in row["reason"] for row in report["rejections"]))
        star = run_research([two], config_for(two, initial_cash=100))
        self.assertEqual(star["trades"], [])
        self.assertTrue(any("最低股数" in row["reason"] for row in star["rejections"]))

    def test_invalid_ranges_and_unknown_configuration_rejected(self):
        item = stock()
        for extra in [{"initial_cash": math.inf}, {"max_positions": True}, {"typo": 1}, {"start_date": "2026-12-31", "end_date": "2025-01-02"},
                      {"start_date": "2027-01-04"}, {"strategy_id": "private"}, {"strategy_id": []}, {"max_holding_days": 1.5},
                      {"strategies": {"teaching": {"enabled": False}}}]:
            with self.subTest(config=extra), self.assertRaises(ValueError):
                normalize_research_config(extra)
        with self.assertRaisesRegex(ValueError, "区间"):
            run_research([item], config_for(item, start_date="2026-12-01", end_date="2026-12-31"))
        with self.assertRaisesRegex(ValueError, "预热"):
            run_research([stock(40)], {})

    def test_requested_coverage_gaps_and_year_boundary_are_disclosed(self):
        item = stock()
        report = run_research([item], config_for(item, start_date="2025-01-02", end_date="2025-12-31"))
        self.assertTrue(any("预热" in warning for warning in report["warnings"]))
        self.assertTrue(any("早于请求结束" in warning for warning in report["warnings"]))
        self.assertTrue(any("上一交易日日历" in warning for warning in report["warnings"]))
        self.assertEqual(report["equity_curve"][0]["cash"], 100000)

    def test_order_size_does_not_use_future_volume_to_resize(self):
        item = stock(62)
        ample = run_research([item], config_for(item))
        modest = copy.deepcopy(item)
        # Above the proposed quantity cap: changing future volume must not resize it.
        modest["raw_candles"][60]["volume"] = 500000
        report = run_research([modest], config_for(modest))
        self.assertEqual(ample["trades"][0]["quantity"], report["trades"][0]["quantity"])
        modest["raw_candles"][60]["volume"] = 100
        illiquid = run_research([modest], config_for(modest))
        self.assertFalse(any(trade["date"] == item["candles"][60]["date"] for trade in illiquid["trades"]))
        self.assertTrue(any("整笔拒绝" in row["reason"] for row in illiquid["rejections"]))

    def test_selected_strategy_produces_independent_comparable_result(self):
        item = stock()
        teaching = run_research([item], config_for(item))
        breakout = run_research([item], config_for(item, strategy_id="breakout"))
        self.assertEqual(teaching["data_fingerprint"], breakout["data_fingerprint"])
        self.assertEqual(teaching["config"]["start_date"], breakout["config"]["start_date"])
        self.assertNotEqual(teaching["metrics"]["trade_count"], breakout["metrics"]["trade_count"])


if __name__ == "__main__":
    unittest.main()
