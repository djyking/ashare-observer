"""Connection lifecycle and credential boundaries, without network or accounts."""
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch

from ashare_monitor.brokers import (BrokerError, BrokerGateway, BrokerStatus, ConnectionDriver,
                                    ConnectionField, ConnectionManager, ConnectionSession, OPERATIONS)
from examples.demo_broker_adapter import ContractDemoAdapter


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.gateway = BrokerGateway(Mock())
        self.manager = ConnectionManager(self.temp.name, self.gateway)

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def demo(self):
        return self.manager.save({"driver": "demo", "fields": {"account_id": "demo"},
                                  "secrets": {"password": "demo123"}})

    def error(self, code, function, *args):
        with self.assertRaises(BrokerError) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def driver(self, factory, name="local_sdk"):
        driver = ConnectionDriver(name, "测试只读接口", "仅测试", (
            ConnectionField("account_id", "账号", masked=True),
            ConnectionField("password", "密码", secret=True),
            ConnectionField("client_path", "官方客户端目录", required=False)), factory)
        self.manager.register_driver(driver)
        self.manager.save({"driver": name, "fields": {"account_id": "sensitive-account-098765"},
                           "secrets": {"password": "sensitive-password-777"}})
        return driver

    def test_save_masks_account_and_never_persists_credentials(self):
        self.manager.save({"driver": "unconfigured", "fields": {"broker_name": "示例券商", "account_id": "private-account-123456"},
                           "secrets": {"password": "private-password-abcdef"}})
        snapshot = self.manager.snapshot()
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn("private-account", serialized)
        self.assertNotIn("private-password", serialized)
        self.assertEqual(snapshot["profile"]["masked_fields"]["account_id"], "****3456")
        self.assertEqual(snapshot["profile"]["fields"], {"broker_name": "示例券商"})
        self.assertEqual(snapshot["profile"]["secret_fields_ready"], ["password"])
        self.assertEqual(snapshot["profile"]["memory_only_fields"], ["account_id", "password"])
        self.assertFalse(snapshot["secrets_persisted"])
        for path in Path(self.temp.name).rglob("*"):
            if path.is_file():
                content = path.read_text(encoding="utf-8")
                self.assertNotIn("private-account", content)
                self.assertNotIn("private-password", content)
        self.assertEqual(json.loads(self.manager.path.read_text(encoding="utf-8")),
                         {"driver": "unconfigured", "fields": {"broker_name": "示例券商"}})

    def test_restart_requires_account_and_password(self):
        self.demo()
        self.manager.connect()
        restarted = ConnectionManager(self.temp.name, BrokerGateway(Mock()))
        self.assertEqual(restarted.snapshot()["state"]["status"], "disconnected")
        self.assertEqual(restarted.snapshot()["profile"]["saved_fields"], [])
        self.assertEqual(restarted.snapshot()["profile"]["secret_fields_ready"], [])
        self.error("connection_credentials_missing", restarted.connect)
        restarted.close()

    def test_custom_driver_registered_at_startup_restores_public_profile_only(self):
        driver = self.driver(lambda fields, secrets: ConnectionSession(ContractDemoAdapter(), Mock()))
        self.manager.save({"fields": {"client_path": "C:/OfficialClient"}})
        restarted = ConnectionManager(self.temp.name, BrokerGateway(Mock()), drivers=(driver,))
        profile = restarted.snapshot()["profile"]
        self.assertEqual(profile["driver"], "local_sdk")
        self.assertEqual(profile["fields"], {"client_path": "C:/OfficialClient"})
        self.assertEqual(profile["masked_fields"], {})
        self.assertEqual(profile["secret_fields_ready"], [])
        self.assertEqual(restarted.snapshot()["state"]["status"], "disconnected")
        self.error("connection_credentials_missing", restarted.connect)
        restarted.close()

    def test_demo_connection_reads_all_four_types_but_never_trades(self):
        self.assertEqual([p["id"] for p in self.gateway.catalog()["providers"]], ["paper", "live"])
        self.assertEqual(self.demo()["state"]["status"], "disconnected")
        result = self.manager.connect()
        self.assertEqual(result["state"]["provider_id"], "broker_demo")
        self.assertEqual(result["state"]["status"], "connected")
        self.assertIn("虚构", result["state"]["message"])
        self.assertEqual(self.gateway.account("broker_demo")["account"]["equity"], 100000)
        for operation in ("positions", "orders", "trades"):
            self.assertEqual(len(getattr(self.gateway, operation)("broker_demo")[operation]), 1)
        self.error("trading_disabled", self.gateway.place_order, "broker_demo", {})
        self.error("trading_disabled", self.gateway.cancel_order, "broker_demo", {})
        self.assertFalse(self.gateway.catalog()["live_enabled"])

    def test_disconnect_clears_credentials_and_revokes_old_reference(self):
        self.demo()
        self.manager.connect()
        adapter = self.gateway._provider("broker_demo").adapter
        result = self.manager.disconnect()
        self.assertEqual(result["profile"]["masked_fields"], {})
        self.assertEqual(result["profile"]["secret_fields_ready"], [])
        self.assertEqual(result["state"]["status"], "disconnected")
        self.assertFalse(adapter.status().connected)
        self.error("broker_unavailable", adapter.account)
        self.error("broker_unavailable", self.gateway.account, "broker_demo")
        self.error("connection_credentials_missing", self.manager.connect)

    def test_partial_save_retains_in_memory_fields_and_explicit_blank_clears(self):
        self.demo()
        self.manager.save({"fields": {}})
        self.assertEqual(self.manager.connect()["state"]["status"], "connected")
        saved = self.manager.save({"secrets": {"password": ""}})
        self.assertEqual(saved["state"]["status"], "disconnected")
        self.assertEqual(saved["profile"]["masked_fields"], {"account_id": "****"})
        self.error("broker_unavailable", self.gateway.account, "broker_demo")
        self.error("connection_credentials_missing", self.manager.connect)

    def test_driver_switch_drops_old_sensitive_values(self):
        self.demo()
        result = self.manager.save({"driver": "unconfigured", "fields": {"broker_name": "示例券商"}})
        self.assertEqual(result["profile"]["masked_fields"], {})
        self.assertEqual(result["profile"]["secret_fields_ready"], [])
        self.error("broker_unconfigured", self.manager.connect)
        self.assertEqual(self.manager.snapshot()["state"]["status"], "error")
        self.assertFalse(self.gateway.catalog()["providers"][1]["connected"])

    def test_wrong_demo_credentials_are_not_false_success(self):
        self.manager.save({"fields": {"account_id": "not-demo"}, "secrets": {"password": "nope-secret"}})
        exc = self.error("connection_auth_failed", self.manager.connect)
        self.assertNotIn("nope-secret", str(exc))
        self.assertEqual(self.manager.snapshot()["state"]["status"], "error")
        self.assertEqual([p["id"] for p in self.gateway.catalog()["providers"]], ["paper", "live"])

    def test_unknown_fields_paths_and_oversized_values_fail_closed(self):
        for payload in ([], {"module": "os"}, {"driver": "https://localhost"},
                        {"driver": []}, {"fields": {"url": "http://example.invalid"}},
                        {"fields": {"password": "secret"}}, {"secrets": {"account_id": "secret"}},
                        {"fields": {"account_id": 123}}, {"secrets": {"password": "x" * 4097}},
                        {"fields": {"account_id": "bad\x00value"}}):
            with self.subTest(payload=str(payload)[:40]):
                self.error("invalid_connection_config", self.manager.save, payload)
        self.assertFalse(self.manager.path.exists())

    def test_disk_failure_does_not_mutate_existing_connection(self):
        self.demo()
        self.manager.connect()
        with patch("ashare_monitor.brokers.connections.os.replace", side_effect=OSError("private-path")):
            exc = self.error("broker_failure", self.manager.save, {"fields": {"account_id": "another"}})
        self.assertNotIn("private-path", str(exc))
        self.assertEqual(self.manager.snapshot()["state"]["status"], "connected")
        self.assertEqual(list(Path(self.temp.name).glob("*.tmp")), [])

    def test_third_party_exception_text_and_status_message_are_sanitized(self):
        def failure(fields, secrets):
            raise RuntimeError("sensitive-password-777 sensitive-account-098765")
        self.driver(failure)
        exc = self.error("broker_failure", self.manager.connect)
        self.assertNotIn("sensitive-", str(exc))
        self.assertNotIn("sensitive-", json.dumps(self.manager.snapshot()))

    def test_verified_custom_driver_remains_read_only_and_closes_once(self):
        adapter = ContractDemoAdapter()
        adapter.place_order = Mock()
        adapter.cancel_order = Mock()
        close = Mock()
        captured = []
        def factory(fields, secrets):
            captured.append((dict(fields), dict(secrets)))
            return ConnectionSession(adapter, close)
        self.driver(factory)
        self.assertEqual(self.manager.connect()["state"]["provider_id"], "live")
        self.assertEqual(captured[0][1]["password"], "sensitive-password-777")
        self.assertEqual(self.gateway.account("live")["account"]["cash"], 1000)
        self.error("trading_disabled", self.gateway.place_order, "live", {})
        self.error("trading_disabled", self.gateway.cancel_order, "live", {})
        adapter.place_order.assert_not_called()
        adapter.cancel_order.assert_not_called()
        self.manager.disconnect()
        self.manager.disconnect()
        close.assert_called_once()

    def test_sdk_drop_is_reflected_in_connection_state(self):
        adapter, close = ContractDemoAdapter(), Mock()
        self.driver(lambda fields, secrets: ConnectionSession(adapter, close))
        self.manager.connect()
        adapter.status = lambda: BrokerStatus(False, {}, "secret-status-message")
        result = self.manager.snapshot()
        self.assertEqual(result["state"]["status"], "error")
        self.assertNotIn("secret-status-message", json.dumps(result))
        close.assert_called_once()
        self.error("broker_unavailable", self.gateway.account, "live")

    def test_in_flight_connect_cannot_restore_after_disconnect_or_save(self):
        for action in ("disconnect", "save"):
            with self.subTest(action=action):
                entered, release, closed, errors = Event(), Event(), Mock(), []
                def factory(fields, secrets):
                    entered.set()
                    self.assertTrue(release.wait(5))
                    return ConnectionSession(ContractDemoAdapter(), closed)
                self.driver(factory, "sdk_" + action)
                def connect():
                    try:
                        self.manager.connect()
                    except BrokerError as exc:
                        errors.append(exc.code)
                worker = Thread(target=connect)
                worker.start()
                self.assertTrue(entered.wait(5))
                self.error("connection_busy", self.manager.connect)
                if action == "disconnect":
                    self.manager.disconnect()
                else:
                    self.manager.save({"fields": {"account_id": "changed-account"}})
                release.set()
                worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(errors, ["connection_superseded"])
                self.assertEqual(self.manager.snapshot()["state"]["status"], "disconnected")
                self.assertFalse(self.gateway.catalog()["providers"][1]["connected"])
                closed.assert_called_once()

    def test_disconnect_waits_for_current_read_and_blocks_later_reads(self):
        adapter, close = ContractDemoAdapter(), Mock()
        self.driver(lambda fields, secrets: ConnectionSession(adapter, close))
        self.manager.connect()
        wrapped = self.gateway._provider("live").adapter
        entered, release, disconnected = Event(), Event(), Event()
        def account():
            entered.set()
            self.assertTrue(release.wait(5))
            return {"cash": 1}
        adapter.account = account
        reader = Thread(target=wrapped.account)
        reader.start()
        self.assertTrue(entered.wait(5))
        def disconnect():
            self.manager.disconnect()
            disconnected.set()
        worker = Thread(target=disconnect)
        worker.start()
        self.assertFalse(disconnected.wait(0.03))
        close.assert_not_called()
        release.set()
        reader.join(5)
        worker.join(5)
        self.assertTrue(disconnected.is_set())
        close.assert_called_once()
        self.error("broker_unavailable", wrapped.account)

    def test_profile_with_credential_keys_is_not_loaded(self):
        self.manager.path.write_text(json.dumps({"driver": "demo", "fields": {"account_id": "should-not-load"}}), encoding="utf-8")
        loaded = ConnectionManager(self.temp.name, BrokerGateway(Mock()))
        self.assertEqual(loaded.snapshot()["state"]["status"], "error")
        self.assertEqual(loaded.snapshot()["profile"]["masked_fields"], {})
        self.assertNotIn("should-not-load", json.dumps(loaded.snapshot()))

    def test_unusable_or_failed_handshake_never_registers_provider(self):
        close = Mock()
        adapter = ContractDemoAdapter()
        adapter.account = lambda: {"cash": float("nan"), "secret": "private"}
        self.driver(lambda fields, secrets: ConnectionSession(adapter, close))
        self.error("broker_failure", self.manager.connect)
        self.assertEqual(self.manager.snapshot()["state"]["status"], "error")
        self.assertFalse(self.gateway.catalog()["providers"][1]["connected"])
        close.assert_called_once()

    def test_account_handshake_requires_currency_and_usable_numeric_balances(self):
        adapter = ContractDemoAdapter()
        close = Mock()
        self.driver(lambda fields, secrets: ConnectionSession(adapter, close))
        invalid = ({}, {"cash": 100}, {"currency": "CNY"}, {"currency": " ", "cash": 100},
                   {"currency": "CNY", "cash": "error"}, {"currency": "CNY", "cash": True},
                   {"currency": "CNY", "cash": None}, {"currency": "CNY", "cash": -1},
                   {"currency": "CNY", "available_cash": 1, "equity": float("inf")},
                   {"currency": "CNY", "cash": 1, "fees": "5"},
                   {"currency": "CNY", "cash": 1, "unrealized_pnl": "error"})
        for account in invalid:
            with self.subTest(account=account):
                adapter.account = lambda value=account: value
                self.error("broker_failure", self.manager.connect)
                self.assertEqual(self.manager.snapshot()["state"]["status"], "error")
                self.assertFalse(self.gateway.catalog()["providers"][1]["connected"])
        self.assertEqual(close.call_count, len(invalid))
        adapter.account = lambda: {"currency": "CNY", "available_cash": 0, "unrealized_pnl": -1.5}
        self.assertEqual(self.manager.connect()["state"]["status"], "connected")


if __name__ == "__main__":
    unittest.main()
