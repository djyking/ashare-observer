"""Contract, shared-ledger and public-boundary tests; no external accounts."""
from copy import deepcopy
import json
import tempfile
import unittest
from unittest.mock import Mock

from ashare_monitor.brokers import BrokerAdapter, BrokerError, BrokerGateway, BrokerStatus, OPERATIONS
from ashare_monitor.runtime import Runtime
from examples.demo_broker_adapter import ContractDemoAdapter, register_contract_demo


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = Runtime(self.temp.name)
        self.runtime.state["settings"]["auto_refresh"] = False
        self.runtime._scan(False)
        self.gateway = BrokerGateway(self.runtime)
        self.order = {"side": "buy", "code": "600036", "quantity": 100, "request_id": "broker-test-001"}

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def assertBrokerError(self, code, status, function, *args):
        with self.assertRaises(BrokerError) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(caught.exception.status_code, status)
        return caught.exception

    def test_default_catalog_and_read_shapes(self):
        catalog = self.gateway.catalog()
        self.assertFalse(catalog["live_enabled"])
        self.assertEqual([item["id"] for item in catalog["providers"]], ["paper", "live"])
        paper, live = catalog["providers"]
        self.assertTrue(paper["connected"])
        self.assertTrue(paper["capabilities"]["place_order"])
        self.assertFalse(live["connected"])
        self.assertFalse(any(live["capabilities"].values()))
        self.assertEqual(self.gateway.account("paper")["account"]["currency"], "CNY")
        self.assertEqual(self.gateway.account("paper")["account"]["cash"], 100000)
        self.assertEqual(self.gateway.positions("paper")["positions"], [])
        self.assertEqual(self.gateway.orders("paper")["orders"], [])
        self.assertEqual(self.gateway.trades("paper")["trades"], [])

    def test_order_and_cancel_use_existing_ledger_and_idempotency(self):
        self.gateway.place_order("paper", self.order)
        self.gateway.place_order("paper", self.order)
        view = self.runtime.snapshot("")["portfolio"]
        self.assertEqual(len(view["orders"]), 1)
        self.assertGreater(view["frozen_cash"], 0)
        self.assertEqual(self.gateway.account("paper")["account"]["frozen_cash"], view["frozen_cash"])
        order_id = view["orders"][0]["id"]
        self.gateway.cancel_order("paper", {"order_id": order_id})
        self.gateway.cancel_order("paper", {"order_id": order_id})
        self.assertEqual(self.gateway.account("paper")["account"]["frozen_cash"], 0)
        self.assertEqual(self.gateway.orders("paper")["orders"][0]["status"], "cancelled")
        self.assertEqual(len(self.runtime.state["ledger"]["orders"]), 1)
        restored = Runtime(self.temp.name)
        self.assertEqual(restored.state["ledger"], self.runtime.state["ledger"])

    def test_source_mode_and_refresh_restrictions_are_preserved(self):
        before = deepcopy(self.runtime.state["ledger"])
        self.runtime.state["settings"]["mode"] = "eastmoney"
        self.assertBrokerError("trading_disabled", 409, self.gateway.place_order, "paper", self.order)
        self.assertEqual(self.gateway.account("paper")["account"]["cash"], 100000)
        self.runtime.state["settings"]["mode"] = "demo"
        self.runtime.refreshing = True
        self.assertBrokerError("trading_disabled", 409, self.gateway.place_order, "paper", self.order)
        self.assertEqual(self.runtime.state["ledger"], before)

    def test_live_all_routes_fail_closed_and_never_mutate_paper(self):
        before = deepcopy(self.runtime.state)
        for operation in ("account", "positions", "orders", "trades"):
            self.assertBrokerError("broker_unconfigured", 409, getattr(self.gateway, operation), "live")
        self.assertBrokerError("broker_unconfigured", 409, self.gateway.place_order, "live", self.order)
        self.assertBrokerError("broker_unconfigured", 409, self.gateway.cancel_order, "live", {"order_id": "paper-1"})
        self.assertEqual(self.runtime.state, before)

    def test_invalid_provider_never_falls_back_to_paper(self):
        for provider_id in ("unknown", "LIVE", "../paper", None, []):
            self.assertBrokerError("unknown_provider", 404, self.gateway.account, provider_id)
        self.assertEqual(self.gateway.orders("paper")["orders"], [])

    def test_shared_rules_reject_invalid_quantity_and_request_reuse(self):
        self.assertBrokerError("invalid_request", 400, self.gateway.place_order, "paper", {**self.order, "quantity": 1})
        self.gateway.place_order("paper", self.order)
        self.assertBrokerError("invalid_request", 400, self.gateway.place_order, "paper", {**self.order, "quantity": 200})
        self.assertEqual(len(self.gateway.orders("paper")["orders"]), 1)

    def test_adapter_registration_is_an_actual_read_only_extension(self):
        register_contract_demo(self.gateway)
        result = self.gateway.account("contract_demo")
        self.assertEqual(result["environment"], "live")
        self.assertEqual(result["account"]["cash"], 1000)
        self.assertFalse(self.gateway.catalog()["live_enabled"])
        self.assertBrokerError("trading_disabled", 409, self.gateway.place_order, "contract_demo", self.order)
        self.assertEqual(self.gateway.account("paper")["account"]["cash"], 100000)

    def test_even_connected_adapter_cannot_execute_live_mutations(self):
        adapter = ContractDemoAdapter()
        adapter.place_order = Mock(return_value={"ok": True})
        adapter.cancel_order = Mock(return_value={"ok": True})
        self.gateway.register("live", adapter, name="接口测试", environment="live")
        self.assertBrokerError("trading_disabled", 409, self.gateway.place_order, "live", self.order)
        self.assertBrokerError("trading_disabled", 409, self.gateway.cancel_order, "live", {"order_id": "example"})
        adapter.place_order.assert_not_called()
        adapter.cancel_order.assert_not_called()

    def test_account_and_record_response_fields_are_allowlisted(self):
        adapter = ContractDemoAdapter()
        adapter.account = lambda: {"currency": "CNY", "cash": 123, "account_id": "private-value",
                                   "api_key": "private-value", "raw_sdk": {"private": "private-value"}}
        adapter.positions = lambda: [{"code": "600036", "quantity": 100, "account_id": "private-value"}]
        adapter.orders = lambda: [{"id": "example-order", "status": "pending", "reason": "private-value"}]
        adapter.trades = lambda: [{"code": "600036", "quantity": 100, "raw_sdk": "private-value"}]
        self.gateway.register("live", adapter, name="接口测试", environment="live")
        output = [getattr(self.gateway, operation)("live") for operation in ("account", "positions", "orders", "trades")]
        self.assertNotIn("private-value", json.dumps(output))
        self.assertEqual(output[0]["account"], {"currency": "CNY", "cash": 123})

    def test_sdk_error_and_custom_status_text_never_leak(self):
        adapter = ContractDemoAdapter()
        adapter.status = lambda: BrokerStatus(True, {key: True for key in OPERATIONS}, "private-value")
        def sdk_failure():
            raise RuntimeError("private-value")
        adapter.account = sdk_failure
        self.gateway.register("live", adapter, name="接口测试", environment="live")
        self.assertNotIn("private-value", json.dumps(self.gateway.catalog()))
        exc = self.assertBrokerError("broker_failure", 502, self.gateway.account, "live")
        self.assertNotIn("private-value", str(exc))
        adapter.status = sdk_failure
        self.assertNotIn("private-value", json.dumps(self.gateway.catalog()))
        self.assertBrokerError("broker_unavailable", 503, self.gateway.account, "live")

    def test_bad_public_data_fails_without_raw_adapter_output(self):
        adapter = ContractDemoAdapter()
        self.gateway.register("live", adapter, name="接口测试", environment="live")
        for account in ({"cash": float("nan")}, {"cash": {"private": "value"}}, ["private-value"]):
            adapter.account = lambda value=account: value
            self.assertBrokerError("broker_failure", 502, self.gateway.account, "live")

    def test_registration_and_abstract_contract_validation(self):
        with self.assertRaises(TypeError):
            BrokerAdapter()
        with self.assertRaises(TypeError):
            self.gateway.register("test", object(), name="test", environment="live")
        with self.assertRaises(ValueError):
            self.gateway.register("paper", ContractDemoAdapter(), name="test", environment="live")
        with self.assertRaises(ValueError):
            self.gateway.register("live", ContractDemoAdapter(), name="test", environment="paper")


if __name__ == "__main__":
    unittest.main()
