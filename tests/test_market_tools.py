import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ashare_monitor.data import _csv_stock
from ashare_monitor.market_tools import (commit_csv_import, csv_template,
                                        search_securities, validate_csv_import,
                                        watchlist_templates)


class CSVImportTests(unittest.TestCase):
    def test_template_preview_commit_read_same_folder(self):
        text = csv_template()
        preview = validate_csv_import("600036", text)
        self.assertTrue(preview["valid"])
        self.assertEqual(preview["row_count"], 2)
        self.assertEqual(preview["first_date"], "2026-10-08")
        self.assertEqual(preview["last_date"], "2026-10-09")
        self.assertIn("不足", preview["warnings"][0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "imports")
            self.assertFalse(root.exists())
            result = commit_csv_import(root, "600036", text)
            self.assertTrue(result["saved"])
            self.assertNotIn(str(root), json.dumps(result))
            self.assertEqual(_csv_stock("600036", "2026-10-12", root)["raw_candles"][-1]["close"], 10.2)
            self.assertTrue(commit_csv_import(root, "600036", text)["unchanged"])

    def test_failed_validation_never_overwrites_and_overwrite_is_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            commit_csv_import(root, "600036", csv_template())
            path = Path(root, "600036.csv")
            original = path.read_bytes()
            with self.assertRaisesRegex(ValueError, "休市"):
                commit_csv_import(root, "600036", csv_template().replace("2026-10-08", "2026-10-01"), overwrite=True)
            self.assertEqual(path.read_bytes(), original)
            changed = csv_template().replace("10.20,120000", "10.25,120000")
            with self.assertRaisesRegex(ValueError, "确认覆盖"):
                commit_csv_import(root, "600036", changed)
            self.assertEqual(path.read_bytes(), original)
            commit_csv_import(root, "600036", changed, overwrite=True)
            self.assertNotEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(root).glob("*.tmp")), [])

    def test_bad_fields_rows_duplicates_and_holidays_report_line(self):
        examples = [
            (csv_template().replace("volume", "vol"), 1, "header"),
            (csv_template().replace("2026-10-08", "2026-10-01"), 2, "date"),
            (csv_template().replace("2026-10-09", "2026-10-08"), 3, "date"),
            (csv_template().replace("10.00,10.20", "nan,10.20"), 2, "open"),
            (csv_template().replace("100000,1005000", "100000,1005000,extra"), 2, "row"),
        ]
        for text, line, field in examples:
            with self.subTest(line=line, field=field):
                result = validate_csv_import("600036", text)
                self.assertFalse(result["valid"])
                self.assertTrue(any(e["line"] == line and e["field"] == field for e in result["errors"]))

    def test_unknown_calendar_and_adjustment_disclosed(self):
        text = "date,open,high,low,close,volume\n2024-10-01,10,11,9,10,100\n"
        result = validate_csv_import("600036", text)
        self.assertTrue(result["valid"])
        self.assertEqual(result["calendar_unverified_years"], [2024])
        self.assertTrue(any("未声明" in warning for warning in result["warnings"]))
        self.assertTrue(any("未覆盖 2024" in warning for warning in result["warnings"]))
        result = validate_csv_import("600036", csv_template(), as_of="2026-10-08")
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["line"], 3)

    def test_raw_columns_and_oversize_are_validated(self):
        text = "date,open,high,low,close,volume,adjustment,raw_open\n2026-10-08,10,11,9,10,100,qfq,20\n"
        result = validate_csv_import("600036", text)
        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["field"], "raw_OHLC")
        for text in (None, "x" * 1_000_001, "bad\0csv"):
            self.assertFalse(validate_csv_import("600036", text)["valid"])
        self.assertFalse(validate_csv_import("../secret", csv_template())["valid"])
        self.assertFalse(validate_csv_import("600036", csv_template(), as_of="tomorrow")["valid"])

    def test_links_do_not_read_or_replace_outside_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "imports")
            root.mkdir()
            outside = Path(directory, "outside.csv")
            outside.write_text("private", encoding="utf-8")
            try:
                Path(root, "600036.csv").symlink_to(outside)
            except OSError:
                self.skipTest("symlink creation unavailable on this host")
            with self.assertRaisesRegex(ValueError, "链接"):
                commit_csv_import(root, "600036", csv_template(), overwrite=True)
            self.assertEqual(outside.read_text(encoding="utf-8"), "private")


class DiscoveryTests(unittest.TestCase):
    def test_local_name_code_group_do_not_require_network(self):
        with patch("ashare_monitor.market_tools.urlopen", side_effect=AssertionError("local matching must be offline")):
            self.assertEqual(search_securities("茅台")["items"][0]["code"], "600519")
            item = search_securities("601398")["items"][0]
            self.assertEqual(item["name"], "工商银行")
            self.assertFalse(item["demo_tradable"])
            self.assertTrue(item["research_only"])
            self.assertFalse(item["metadata_verified"])
            self.assertIsNone(item["listing_date"])
            self.assertTrue(search_securities("600036")["items"][0]["demo_tradable"])
            self.assertGreater(len(search_securities("")["items"]), 8)
        self.assertEqual(len(watchlist_templates()), 3)

    def test_remote_result_is_filtered_and_never_trading_verified(self):
        with patch("ashare_monitor.market_tools._remote_search", return_value=[
            {"Code": "600900", "Name": "长江电力"}, {"Code": "510300", "Name": "非普通股"},
            {"Code": "../../x", "Name": "无效"}]):
            result = search_securities("remote-query")
        self.assertEqual([item["code"] for item in result["items"]], ["600900"])
        self.assertFalse(result["items"][0]["metadata_verified"])
        self.assertFalse(result["items"][0]["demo_tradable"])

    def test_remote_failure_does_not_invent_stock_identity(self):
        with patch("ashare_monitor.market_tools._remote_search", side_effect=TimeoutError):
            result = search_securities("600999")
        self.assertEqual(result["items"][0]["name"], "600999")
        self.assertIn("未确认", result["warning"])
        self.assertIn("未确认", result["items"][0]["source"])
        self.assertIsNone(result["items"][0]["listing_date"])
        for query in (None, "a" * 33, "bad\nquery"):
            with self.assertRaises(ValueError):
                search_securities(query)


if __name__ == "__main__":
    unittest.main()
