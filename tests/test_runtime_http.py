import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from ashare_monitor.runtime import Runtime
from ashare_monitor.server import DashboardServer
from ashare_monitor.storage import Store


def wait_idle(runtime):
    deadline = time.monotonic() + 15
    while runtime.refreshing and time.monotonic() < deadline:
        time.sleep(0.01)
    if runtime.refreshing:
        raise AssertionError("background worker did not finish")
    if runtime.last_error:
        raise AssertionError(runtime.last_error)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Runtime(self.tmp.name)
        self.runtime.state["settings"]["auto_refresh"] = False
        self.runtime.start()
        wait_idle(self.runtime)

    def tearDown(self):
        self.runtime.close()
        self.tmp.cleanup()

    def test_initial_snapshot_and_persistence(self):
        state = self.runtime.snapshot("test")
        self.assertEqual(state["app"]["mode"], "demo")
        self.assertEqual(state["stats"]["valid_count"], 8)
        self.assertEqual(state["portfolio"]["positions"], [])
        restored = Runtime(self.tmp.name)
        self.assertEqual(restored.state, self.runtime.state)
        self.assertEqual(self.runtime.store.history()["total"], 1)

    def test_complete_paper_order_cycle_with_t_plus_one(self):
        order = {"side": "buy", "code": "600036", "quantity": 100, "request_id": "test-buy-001"}
        self.runtime.paper_order(order)
        self.runtime.paper_order(order)
        self.assertEqual(len(self.runtime.snapshot("x")["portfolio"]["orders"]), 1)
        self.runtime.request_refresh(advance=True)
        wait_idle(self.runtime)
        view = self.runtime.snapshot("x")["portfolio"]
        self.assertEqual(view["positions"][0]["quantity"], 100)
        self.assertEqual(view["positions"][0]["sellable"], 0)
        with self.assertRaises(ValueError):
            self.runtime.paper_order({**order, "side": "sell", "request_id": "test-sell-day0"})
        self.runtime.request_refresh(advance=True)
        wait_idle(self.runtime)
        self.assertEqual(self.runtime.snapshot("x")["portfolio"]["positions"][0]["sellable"], 100)
        self.runtime.paper_order({**order, "side": "sell", "request_id": "test-sell-day1"})
        self.runtime.request_refresh(advance=True)
        wait_idle(self.runtime)
        view = self.runtime.snapshot("x")["portfolio"]
        self.assertEqual(view["positions"], [])
        self.assertEqual(len(view["trades"]), 2)
        self.assertAlmostEqual(view["cash"] - view["initial_cash"], view["realized_pnl"], places=2)
        restored = Runtime(self.tmp.name)
        self.assertEqual(restored.snapshot("x")["portfolio"]["trades"], view["trades"])

    def test_pending_symbol_cannot_disappear(self):
        self.runtime.paper_order({"side": "buy", "code": "600036", "quantity": 100, "request_id": "retention-001"})
        with self.assertRaises(ValueError):
            self.runtime.settings({"watchlist": ["601318"]})
        self.runtime.cancel({"order_id": "paper-1"})
        self.runtime.settings({"watchlist": ["601318"]})
        wait_idle(self.runtime)
        self.assertEqual(self.runtime.snapshot("x")["stats"]["stock_count"], 1)

    def test_invalid_settings_do_not_mutate(self):
        before = self.runtime.store.load()
        for payload in ({"refresh_seconds": True}, {"auto_refresh": "yes"}, {"watchlist": ["../../x"]},
                        {"mode": "real_order"}, {"initial_cash": 9}, {"watchlist": ["999999"]},
                        {"watchlist": ["600036", "600036"]}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.runtime.settings(payload)
                self.assertEqual(before, self.runtime.store.load())

    def test_mode_switch_isolates_account_and_does_not_fake_data(self):
        with patch("ashare_monitor.runtime.load_market", return_value={"mode": "eastmoney", "source": "test public source",
                   "as_of": "2026-10-12", "stocks": [], "errors": ["network unavailable"]}):
            self.runtime.settings({"mode": "eastmoney"})
            if self.runtime.worker:
                self.runtime.worker.join(5)
        state = self.runtime.snapshot("x")
        self.assertEqual(state["stocks"], [])
        self.assertEqual(state["app"]["mode"], "eastmoney")
        self.assertTrue(state["app"]["last_error"])
        self.assertEqual(state["portfolio"]["cash"], 100000)
        with self.assertRaises(ValueError):
            self.runtime.paper_order({"side": "buy", "code": "600036", "quantity": 100, "request_id": "not-demo-001"})
        with self.assertRaises(ValueError):
            self.runtime.request_refresh(advance=True)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Runtime(self.tmp.name)
        self.runtime.state["settings"]["auto_refresh"] = False
        self.runtime.start()
        wait_idle(self.runtime)
        self.server = DashboardServer(("127.0.0.1", 0), self.runtime)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.runtime.close()
        self.tmp.cleanup()

    def call(self, path, method="GET", payload=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        request_headers = {"Content-Type": "application/json", "X-CSRF-Token": self.server.token}
        request_headers.update(headers or {})
        body = raw if raw is not None else json.dumps(payload).encode() if payload is not None else None
        conn.request(method, path, body, request_headers)
        response = conn.getresponse()
        content = response.read()
        status = response.status
        conn.close()
        return status, content

    def test_state_and_history(self):
        status, body = self.call("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["csrf_token"], self.server.token)
        status, body = self.call("/api/history?page=1&page_size=999")
        self.assertEqual(json.loads(body)["page_size"], 30)
        self.assertEqual(self.call("/api/history?page=bad")[0], 400)

    def test_csrf_origin_and_host(self):
        self.assertEqual(self.call("/api/refresh", "POST", {}, {"X-CSRF-Token": "bad"})[0], 403)
        self.assertEqual(self.call("/api/refresh", "POST", {}, {"X-CSRF-Token": "é"})[0], 403)
        self.assertEqual(self.call("/api/refresh", "POST", {}, {"Origin": "https://foreign.example"})[0], 403)
        self.assertEqual(self.call("/api/state", headers={"Host": "foreign.example"})[0], 403)
        self.assertEqual(self.call("/api/paper/order", "POST", {}, {"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_malformed_and_unknown_operations(self):
        self.assertEqual(self.call("/api/settings", "POST", raw=b'{"mode":"demo","mode":"csv"}')[0], 400)
        self.assertEqual(self.call("/api/settings", "POST", raw=b'{"refresh_seconds":NaN}')[0], 400)
        self.assertEqual(self.call("/api/refresh", "POST", {"extra": 1})[0], 400)
        self.assertEqual(self.call("/api/orders/live", "POST", {})[0], 404)
        self.assertEqual(self.call("/../../README.md")[0], 404)

    def test_order_roundtrip(self):
        status, _body = self.call("/api/paper/order", "POST", {"side": "buy", "code": "600036", "quantity": 100, "request_id": "http-buy-001"})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("/api/paper/cancel", "POST", {"order_id": "paper-1"})[0], 200)
        self.assertEqual(self.runtime.snapshot("x")["portfolio"]["orders"][0]["status"], "cancelled")

    def test_broker_catalog_and_shared_paper_ledger(self):
        status, body = self.call("/api/brokers")
        self.assertEqual(status, 200)
        catalog = json.loads(body)
        self.assertFalse(catalog["live_enabled"])
        self.assertEqual([p["id"] for p in catalog["providers"]], ["paper", "live"])
        self.assertEqual(self.call("/api/brokers/paper/orders", "POST", {
            "side": "buy", "code": "600036", "quantity": 100, "request_id": "broker-http-buy"})[0], 200)
        status, body = self.call("/api/brokers/paper/orders")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["orders"][0]["id"], "paper-1")
        status, body = self.call("/api/brokers/paper/account")
        self.assertEqual(status, 200)
        self.assertGreater(json.loads(body)["account"]["frozen_cash"], 0)
        self.assertEqual(self.call("/api/brokers/paper/cancel", "POST", {"order_id": "paper-1"})[0], 200)
        self.assertEqual(self.runtime.snapshot("x")["portfolio"]["orders"][0]["status"], "cancelled")

    def test_broker_live_and_unsafe_requests_do_not_mutate(self):
        before = self.runtime.store.load()
        for operation in ("account", "positions", "orders", "trades"):
            status, body = self.call(f"/api/brokers/live/{operation}")
            self.assertEqual(status, 409)
            self.assertEqual(json.loads(body)["code"], "broker_unconfigured")
        for operation in ("orders", "cancel"):
            self.assertEqual(self.call(f"/api/brokers/live/{operation}", "POST", {})[0], 409)
            self.assertEqual(self.call(f"/api/brokers/paper/{operation}", "POST", {}, {"X-CSRF-Token": "bad"})[0], 403)
        self.assertEqual(self.call("/api/brokers/unknown/account")[0], 404)
        self.assertEqual(self.call("/api/brokers/live/enable", "POST", {})[0], 404)
        self.assertEqual(self.call("/api/brokers/live/credentials", "POST", {})[0], 404)
        self.assertEqual(self.runtime.store.load(), before)

    def test_frontend_asset_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "assets").mkdir()
            (root / "assets" / "test.js").write_text("export const ok = true", encoding="utf-8")
            (root / "private.txt").write_text("must not leak", encoding="utf-8")
            with patch("ashare_monitor.server.WEB", root):
                self.assertEqual(self.call("/assets/test.js")[0], 200)
                for path in ("/assets/../private.txt", "/assets/%2e%2e/private.txt",
                             "/assets/%2e%2e%5cprivate.txt", "/assets/C:/private.js",
                             "/assets/missing.js", "/assets/test.js.map", "/api/missing"):
                    self.assertEqual(self.call(path)[0], 404, path)
                self.assertEqual(self.call("/")[0], 503)
                (root / "index.html").write_text("<!doctype html><title>Vue</title>", encoding="utf-8")
                self.assertEqual(self.call("/")[0], 200)


if __name__ == "__main__":
    unittest.main()
