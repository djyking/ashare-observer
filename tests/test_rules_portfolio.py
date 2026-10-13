import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from ashare_monitor.rules import (is_trading_day, last_closed_day, limit_prices,
                                  market_session, next_trading_day, validate_quantity)
from ashare_monitor.portfolio import (advance_ledger, cancel_order, fee_breakdown,
                                     new_ledger, order_preview, place_order, portfolio_view)


def bar(day, opening=10, close=None, volume=1000000):
    close = opening if close is None else close
    return {"date": day, "open": opening, "high": max(opening, close),
            "low": min(opening, close), "close": close,
            "volume": volume, "amount": opening * volume}


def stock(code="600000", board="main", bars=None):
    return {"code": code, "name": "教学样本", "exchange": "SSE", "board": board,
            "status": "ok", "metadata_verified": True, "listing_date": "2010-01-01",
            "risk_warning": False, "mode": "demo", "adjustment": "none",
            "raw_candles": bars or [bar("2026-10-09"), bar("2026-10-12", 10.1), bar("2026-10-13", 10.2), bar("2026-10-14", 10.3)]}


def buy(ledger=None, item=None, quantity=100, request_id="buy-1", day="2026-10-09"):
    return place_order(ledger or new_ledger(), "buy", (item or stock())["code"], quantity,
                       day, [item or stock()], request_id)


class CalendarTests(unittest.TestCase):
    def test_holidays_and_makeup_weekends(self):
        for day in ("2025-01-01", "2025-02-04", "2025-02-08", "2025-06-02",
                    "2025-10-08", "2026-01-02", "2026-02-23", "2026-02-28",
                    "2026-04-06", "2026-05-05", "2026-06-19", "2026-09-25",
                    "2026-10-07", "2026-10-10"):
            with self.subTest(day=day):
                self.assertFalse(is_trading_day(day))

    def test_next_day_crosses_holiday_and_weekend(self):
        self.assertEqual(next_trading_day("2026-02-13"), "2026-02-24")
        self.assertEqual(next_trading_day("2026-09-30"), "2026-10-08")
        self.assertEqual(next_trading_day("2026-10-09"), "2026-10-12")
        self.assertEqual(next_trading_day("2025-12-31"), "2026-01-05")

    def test_unknown_year_fails_closed(self):
        for value in ("2024-12-31", "2027-01-04"):
            with self.assertRaisesRegex(ValueError, "日历"):
                is_trading_day(value)
        with self.assertRaises(ValueError):
            next_trading_day("2026-12-31")
        self.assertFalse(market_session(datetime(2027, 1, 4, 10))["calendar_known"])

    def test_close_buffer_and_timezone(self):
        self.assertEqual(last_closed_day(datetime(2026, 10, 13, 15, 4)), "2026-10-12")
        self.assertEqual(last_closed_day(datetime(2026, 10, 13, 15, 5)), "2026-10-13")
        self.assertEqual(last_closed_day(datetime(2026, 10, 13, 7, 5, tzinfo=timezone.utc)), "2026-10-13")
        self.assertEqual(last_closed_day(datetime(2026, 10, 11, 20)), "2026-10-09")

    def test_session_boundaries(self):
        cases = [(9, 14, False, "盘前"), (9, 15, True, "可撤单"),
                 (9, 20, True, "不可撤单"), (9, 25, False, "等待"),
                 (9, 30, True, "上午"), (11, 30, False, "午间"),
                 (13, 0, True, "下午"), (14, 57, True, "收盘集合"),
                 (15, 0, False, "等待日线"), (15, 5, False, "盘后固定价格"),
                 (15, 30, False, "已收盘")]
        for hour, minute, opened, label in cases:
            with self.subTest(hour=hour, minute=minute):
                session = market_session(datetime(2026, 10, 13, hour, minute))
                self.assertEqual(session["is_open"], opened)
                self.assertIn(label, session["label"])

    def test_quantity_rules_and_odd_lot(self):
        for board in ("main", "growth"):
            self.assertEqual(validate_quantity(board, "buy", 100), 100)
            with self.assertRaises(ValueError):
                validate_quantity(board, "buy", 101)
            for amount in (99, 100, 199, 200, 299):
                self.assertEqual(validate_quantity(board, "sell", amount, 299), amount)
            for amount in (1, 98, 198, 298):
                with self.assertRaises(ValueError):
                    validate_quantity(board, "sell", amount, 299)
        self.assertEqual(validate_quantity("star", "buy", 201), 201)
        self.assertEqual(validate_quantity("star", "sell", 199, 199), 199)
        with self.assertRaises(ValueError):
            validate_quantity("star", "sell", 199, 300)
        self.assertEqual(validate_quantity("beijing", "buy", 101), 101)
        self.assertEqual(validate_quantity("beijing", "sell", 99, 99), 99)
        with self.assertRaises(ValueError):
            validate_quantity("beijing", "sell", 99, 200)

    def test_board_limits_round_half_up(self):
        self.assertEqual(limit_prices("10.05", "main"), (Decimal("11.06"), Decimal("9.05")))
        self.assertEqual(limit_prices(10, "growth"), (Decimal("12.00"), Decimal("8.00")))
        self.assertEqual(limit_prices(10, "star"), (Decimal("12.00"), Decimal("8.00")))
        self.assertEqual(limit_prices(10, "beijing"), (Decimal("13.00"), Decimal("7.00")))


class PortfolioTests(unittest.TestCase):
    def test_next_open_and_t_plus_one(self):
        original = new_ledger()
        ledger = buy(original)
        self.assertEqual(original["orders"], [])
        self.assertEqual(ledger["orders"][0]["execute_after"], "2026-10-12")
        unchanged = advance_ledger(ledger, [stock()], "2026-10-09")
        self.assertEqual(unchanged["trades"], [])
        ledger = advance_ledger(ledger, [stock()], "2026-10-12")
        self.assertEqual(ledger["trades"][0]["price"], "10.10")
        view = portfolio_view(ledger, [stock()], "2026-10-12")
        self.assertEqual(view["positions"][0]["sellable"], 0)
        self.assertEqual(portfolio_view(ledger, [stock()], "2026-10-13")["positions"][0]["sellable"], 100)
        # A close-time sell can reserve today's acquired shares for T+1 open.
        ledger = place_order(ledger, "sell", "600000", 100, "2026-10-12", [stock()], "s0")
        self.assertEqual(ledger["orders"][-1]["execute_after"], "2026-10-13")
        self.assertEqual(len(advance_ledger(ledger, [stock()], "2026-10-12")["trades"]), 1)
        ledger = advance_ledger(ledger, [stock()], "2026-10-13")
        self.assertEqual(len(ledger["trades"]), 2)
        self.assertEqual(ledger["positions"], {})

    def test_preview_is_readonly_and_explains_money_quantity_and_t1(self):
        ledger = new_ledger(500)
        original = deepcopy(ledger)
        preview = order_preview(ledger, "buy", "600000", 100, "2026-10-09", [stock()])
        self.assertFalse(preview["allowed"])
        self.assertIn("1105.01", preview["message"])
        self.assertEqual(preview["estimated_notional"], 1000)
        self.assertEqual(preview["fees"]["total"], 5.01)
        self.assertEqual(preview["available_cash"], 500)
        self.assertEqual(preview["execute_after"], "2026-10-12")
        self.assertEqual(ledger, original)
        preview = order_preview(ledger, "buy", "600000", 1, "2026-10-09", [stock()])
        self.assertIn("100 股", preview["message"])
        filled = advance_ledger(buy(), [stock()], "2026-10-12")
        preview = order_preview(filled, "sell", "600000", 100, "2026-10-12", [stock()])
        self.assertTrue(preview["allowed"])
        self.assertEqual(preview["sellable_now"], 0)
        self.assertEqual(preview["sellable_on_execution"], 100)
        reserved = place_order(filled, "sell", "600000", 100, "2026-10-12", [stock()], "s1")
        self.assertFalse(order_preview(reserved, "sell", "600000", 100, "2026-10-12", [stock()])["allowed"])

    def test_actual_fill_rechecks_t_plus_one_even_with_tampered_pending_order(self):
        ledger = advance_ledger(buy(), [stock()], "2026-10-12")
        ledger = place_order(ledger, "sell", "600000", 100, "2026-10-12", [stock()], "s1")
        ledger["orders"][-1]["execute_after"] = "2026-10-12"
        advanced = advance_ledger(ledger, [stock()], "2026-10-12")
        self.assertEqual(len(advanced["trades"]), 1)
        self.assertEqual(advanced["orders"][-1]["status"], "rejected")
        self.assertIn("T+1", advanced["orders"][-1]["reason"])

    def test_compact_view_preserves_counts_without_copying_records(self):
        ledger = advance_ledger(buy(), [stock()], "2026-10-12")
        view = portfolio_view(ledger, [stock()], "2026-10-12", include_records=False)
        self.assertEqual((view["order_count"], view["trade_count"]), (1, 1))
        self.assertEqual(view["orders"], [])
        self.assertEqual(view["trades"], [])
        self.assertEqual(view["positions"][0]["sellable_on_execution"], 100)
        self.assertEqual(view["slippage_bps"], 0)

    def test_complete_roundtrip_and_fee_conservation(self):
        ledger = advance_ledger(buy(), [stock()], "2026-10-12")
        ledger = place_order(ledger, "sell", "600000", 100, "2026-10-13", [stock()], "s1")
        self.assertEqual(portfolio_view(ledger, [stock()], "2026-10-13")["positions"][0]["sellable"], 0)
        ledger = advance_ledger(ledger, [stock()], "2026-10-14")
        self.assertEqual(len(ledger["trades"]), 2)
        self.assertEqual(ledger["positions"], {})
        self.assertEqual(Decimal(ledger["cash"]) - Decimal(ledger["initial_cash"]), Decimal(ledger["realized_pnl"]))
        self.assertEqual(Decimal(ledger["realized_pnl"]), Decimal("20.00") - Decimal(ledger["fees"]))
        self.assertEqual(ledger["trades"][1]["fees"]["stamp"], "0.52")
        json.loads(json.dumps(ledger, allow_nan=False))

    def test_freeze_cash_includes_upper_limit_and_fee(self):
        ledger = buy(new_ledger(1500))
        view = portfolio_view(ledger, [stock()], "2026-10-09")
        self.assertEqual(view["cash"], 1500)
        self.assertAlmostEqual(view["frozen_cash"], 1105.01)
        self.assertAlmostEqual(view["available_cash"], 394.99)
        with self.assertRaisesRegex(ValueError, "可用资金不足"):
            buy(ledger, request_id="second")
        restored = cancel_order(ledger, "paper-1")
        self.assertEqual(portfolio_view(restored, [stock()], "2026-10-09")["available_cash"], 1500)
        self.assertEqual(ledger["orders"][0]["status"], "pending")

    def test_cancel_idempotent_and_freeze_shares(self):
        ledger = advance_ledger(buy(), [stock()], "2026-10-12")
        ledger = place_order(ledger, "sell", "600000", 100, "2026-10-13", [stock()], "s1")
        with self.assertRaises(ValueError):
            place_order(ledger, "sell", "600000", 100, "2026-10-13", [stock()], "s2")
        ledger = cancel_order(ledger, "paper-2")
        self.assertEqual(cancel_order(ledger, "paper-2"), ledger)
        self.assertEqual(portfolio_view(ledger, [stock()], "2026-10-13")["positions"][0]["sellable"], 100)
        with self.assertRaises(ValueError):
            cancel_order(ledger, "paper-1")

    def test_request_id_dedup_after_fill(self):
        ledger = buy()
        self.assertEqual(buy(ledger), ledger)
        ledger = advance_ledger(ledger, [stock()], "2026-10-12")
        self.assertEqual(buy(ledger), ledger)
        with self.assertRaisesRegex(ValueError, "不同委托"):
            buy(ledger, quantity=200)
        self.assertEqual(advance_ledger(ledger, [stock()], "2026-10-12"), ledger)

    def test_limit_up_expires_and_releases_cash_without_retry(self):
        item = stock(bars=[bar("2026-10-09", 10), bar("2026-10-12", 11), bar("2026-10-13", 10.5)])
        ledger = advance_ledger(buy(item=item), [item], "2026-10-12")
        self.assertFalse(ledger["trades"])
        self.assertIn("涨停", ledger["orders"][0]["reason"])
        self.assertEqual(ledger["orders"][0]["status"], "expired")
        self.assertEqual(portfolio_view(ledger, [item], "2026-10-12")["frozen_cash"], 0)
        ledger = advance_ledger(ledger, [item], "2026-10-13")
        self.assertEqual(ledger["trades"], [])

    def test_limit_down_sell_expires_and_releases_shares(self):
        item = stock(bars=[bar("2026-10-09", 10), bar("2026-10-12", 10), bar("2026-10-13", 10), bar("2026-10-14", 9)])
        ledger = advance_ledger(buy(item=item), [item], "2026-10-12")
        ledger = place_order(ledger, "sell", "600000", 100, "2026-10-13", [item], "s")
        ledger = advance_ledger(ledger, [item], "2026-10-14")
        self.assertEqual(len(ledger["trades"]), 1)
        self.assertIn("跌停", ledger["orders"][-1]["reason"])
        self.assertEqual(ledger["orders"][-1]["status"], "expired")
        self.assertEqual(portfolio_view(ledger, [item], "2026-10-14")["positions"][0]["sellable"], 100)

    def test_missing_bar_suspension_and_zero_volume_no_fill(self):
        for mutation in ("missing", "suspended", "zero"):
            with self.subTest(mutation=mutation):
                item = stock()
                ledger = buy(item=item)
                if mutation == "missing":
                    item["raw_candles"] = [c for c in item["raw_candles"] if c["date"] != "2026-10-12"]
                elif mutation == "suspended":
                    item["status"] = "suspended"
                else:
                    item["raw_candles"][1]["volume"] = 0
                ledger = advance_ledger(ledger, [item], "2026-10-12")
                self.assertFalse(ledger["trades"])
                self.assertEqual(ledger["orders"][0]["status"], "expired")

    def test_gap_advance_never_retries_missing_execution_day(self):
        item = stock(bars=[bar("2026-10-09"), bar("2026-10-13"), bar("2026-10-14")])
        ledger = advance_ledger(buy(item=item), [item], "2026-10-14")
        self.assertEqual(ledger["trades"], [])
        self.assertEqual(ledger["orders"][0]["expired_date"], "2026-10-12")
        item["raw_candles"].append(bar("2026-10-12"))
        ledger = advance_ledger(ledger, [item], "2026-10-14")
        self.assertEqual(ledger["trades"], [])

    def test_unverified_and_new_listing_rejected(self):
        for updates in ({"mode": "eastmoney"}, {"mode": "csv"}, {"risk_warning": True},
                        {"risk_warning": None}, {"name": "*ST样本"}, {"listing_date": None},
                        {"metadata_verified": False}, {"listing_date": "2026-10-08"},
                        {"raw_candles": []}, {"corporate_action_pending": True}):
            with self.subTest(updates=updates):
                item = stock()
                item.update(updates)
                with self.assertRaises(ValueError):
                    buy(item=item)

    def test_real_mode_cannot_advance_ledger(self):
        item = stock()
        item["mode"] = "eastmoney"
        with self.assertRaises(ValueError):
            advance_ledger(new_ledger(), [item], "2026-10-12")

    def test_invalid_amount_and_quantity(self):
        for value in (0, -1, "nan", "Infinity", True):
            with self.assertRaises(ValueError):
                new_ledger(value)
        for value in (0, -100, 1.5, True, "NaN", 1000001):
            with self.assertRaises(ValueError):
                buy(quantity=value)

    def test_invalid_raw_data_blocks_order(self):
        for mutation in ("nan", "bad_ohlc", "duplicate"):
            item = stock()
            if mutation == "nan":
                item["raw_candles"][0]["open"] = float("nan")
            elif mutation == "bad_ohlc":
                item["raw_candles"][0]["high"] = 1
            else:
                item["raw_candles"].append(item["raw_candles"][0].copy())
            with self.assertRaises(ValueError):
                buy(item=item)

    def test_backwards_advance_rejected(self):
        ledger = advance_ledger(buy(), [stock()], "2026-10-12")
        with self.assertRaises(ValueError):
            advance_ledger(ledger, [stock()], "2026-10-09")

    def test_skipped_days_fill_first_available_open(self):
        ledger = advance_ledger(buy(), [stock()], "2026-10-14")
        self.assertEqual(ledger["trades"][0]["date"], "2026-10-12")
        self.assertEqual(len(ledger["trades"]), 1)

    def test_price_snapshot_uses_only_known_day(self):
        ledger = advance_ledger(buy(), [stock()], "2026-10-12")
        view = portfolio_view(ledger, [stock()], "2026-10-12")
        self.assertEqual(view["positions"][0]["last_price"], 10.1)
        self.assertAlmostEqual(view["equity"] - view["initial_cash"], -view["fees"])
        unavailable = portfolio_view(ledger, [], "2026-10-13")
        self.assertIsNone(unavailable["equity"])
        self.assertIsNone(unavailable["positions"][0]["last_price"])

    def test_partial_sale_allocates_cost_and_fee(self):
        ledger = advance_ledger(buy(quantity=300), [stock()], "2026-10-12")
        before_cost = Decimal(ledger["positions"]["600000"]["lots"][0]["cost"])
        ledger = place_order(ledger, "sell", "600000", 100, "2026-10-13", [stock()], "s1")
        ledger = advance_ledger(ledger, [stock()], "2026-10-14")
        remaining_cost = Decimal(ledger["positions"]["600000"]["lots"][0]["cost"])
        trade = ledger["trades"][-1]
        recovered_cost = Decimal(trade["notional"]) - Decimal(trade["fee"]) - Decimal(trade["pnl"])
        self.assertEqual(before_cost, recovered_cost + remaining_cost)

    def test_fee_model_applies_minimum_and_sell_tax(self):
        self.assertEqual(fee_breakdown(1000, "buy")["total"], Decimal("5.01"))
        self.assertEqual(fee_breakdown(1000, "sell")["total"], Decimal("5.51"))
        self.assertEqual(fee_breakdown(100000, "buy")["total"], Decimal("31.00"))


if __name__ == "__main__":
    unittest.main()
