"""Local, read-only connection lifecycle. Secrets are never persisted or returned.

Register trusted Python driver definitions at application startup. HTTP callers
choose only these definitions: they cannot import code or specify an SDK URL.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
from threading import Event, RLock
from typing import Callable
from uuid import uuid4

from .base import BrokerAdapter, BrokerError, BrokerStatus, OPERATIONS
from .gateway import ACCOUNT_FIELDS, _project


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_handshake_account(record):
    """A status flag alone is insufficient evidence of a usable account read."""
    account = _project(record, ACCOUNT_FIELDS)
    if not isinstance(account.get("currency"), str) or not account["currency"].strip():
        raise BrokerError()
    if not any(key in account for key in ("cash", "available_cash", "equity")):
        raise BrokerError()
    amounts = {"initial_cash", "cash", "available_cash", "frozen_cash", "equity",
               "realized_pnl", "unrealized_pnl", "fees"}
    nonnegative = {"initial_cash", "cash", "available_cash", "frozen_cash", "equity", "fees"}
    for key in amounts & account.keys():
        value = account[key]
        if type(value) not in (int, float) or not math.isfinite(value) or (key in nonnegative and value < 0):
            raise BrokerError()
    return account


@dataclass(frozen=True)
class ConnectionField:
    key: str
    label: str
    secret: bool = False
    masked: bool = False
    required: bool = True
    placeholder: str = ""
    max_length: int = 128

    def public(self):
        return {"key": self.key, "label": self.label, "secret": self.secret,
                "masked": self.masked, "required": self.required,
                "placeholder": self.placeholder, "max_length": self.max_length}


@dataclass(frozen=True)
class ConnectionSession:
    adapter: BrokerAdapter
    close: Callable[[], None]


@dataclass(frozen=True)
class ConnectionDriver:
    id: str
    name: str
    description: str
    fields: tuple[ConnectionField, ...]
    factory: Callable[[dict, dict], ConnectionSession] | None = None
    provider_id: str = "live"
    environment: str = "live"

    def public(self):
        return {"id": self.id, "name": self.name, "description": self.description,
                "available": self.factory is not None, "environment": self.environment,
                "fields": [field.public() for field in self.fields]}


class _ReadOnlyAdapter(BrokerAdapter):
    """Revocable capability boundary, also safe for stale gateway references."""
    def __init__(self, adapter):
        self.adapter = adapter
        self.active = Event()
        self.active.set()
        self.lock = RLock()

    def revoke(self):
        # Prevent new reads immediately, then let a bounded in-flight read finish
        # before the manager closes the SDK session.
        self.active.clear()
        with self.lock:
            pass

    def status(self):
        with self.lock:
            if not self.active.is_set():
                return BrokerStatus(False, {}, "unavailable")
            status = self.adapter.status()
            if not isinstance(status, BrokerStatus) or type(status.connected) is not bool:
                raise BrokerError()
            capabilities = {op: status.capabilities.get(op) is True for op in OPERATIONS}
            capabilities.update(place_order=False, cancel_order=False)
            return BrokerStatus(status.connected and self.active.is_set(), capabilities, status.message_key)

    def _read(self, operation):
        with self.lock:
            if not self.active.is_set():
                raise BrokerError("broker_unavailable")
            return getattr(self.adapter, operation)()

    def account(self): return self._read("account")
    def positions(self): return self._read("positions")
    def orders(self): return self._read("orders")
    def trades(self): return self._read("trades")
    def place_order(self, payload): raise BrokerError("trading_disabled")
    def cancel_order(self, payload): raise BrokerError("trading_disabled")


class _DemoConnectionAdapter(BrokerAdapter):
    """Deliberately fixed, fictitious data; no relation to the paper ledger."""
    def status(self):
        return BrokerStatus(True, {op: op not in {"place_order", "cancel_order"} for op in OPERATIONS},
                            "demo_connection")

    def account(self):
        return {"currency": "CNY", "cash": 90000, "available_cash": 85000,
                "frozen_cash": 5000, "equity": 100000, "realized_pnl": 0,
                "unrealized_pnl": 0, "fees": 5, "as_of": "2026-01-05（示例）",
                "valuation_complete": True}

    def positions(self):
        return [{"code": "600036", "name": "招商银行（示例）", "quantity": 200,
                 "sellable": 200, "frozen": 0, "avg_cost": 50, "last_price": 50,
                 "price_date": "2026-01-05", "market_value": 10000, "unrealized_pnl": 0}]

    def orders(self):
        return [{"id": "demo-order-001", "code": "600036", "name": "招商银行（示例）",
                 "side": "buy", "quantity": 100, "status": "pending",
                 "created_date": "2026-01-05", "limit_price": 49.95, "reserved_cash": 5000}]

    def trades(self):
        return [{"id": "demo-trade-001", "order_id": "demo-filled-001", "date": "2026-01-02",
                 "code": "600036", "name": "招商银行（示例）", "side": "buy", "quantity": 200,
                 "price": 50, "notional": 10000, "fee": 5, "pnl": 0}]

    def place_order(self, payload): raise BrokerError("trading_disabled")
    def cancel_order(self, payload): raise BrokerError("trading_disabled")


def _demo_factory(fields, secrets):
    if fields.get("account_id") != "demo" or secrets.get("password") != "demo123":
        raise BrokerError("connection_auth_failed")
    return ConnectionSession(_DemoConnectionAdapter(), lambda: None)


BUILTIN_DRIVERS = (
    ConnectionDriver("demo", "离线券商示例", "使用演示账号 demo、演示密码 demo123。数据均为虚构，只读；无需填写真实账号。",
                     (ConnectionField("account_id", "演示账号", masked=True, placeholder="demo"),
                      ConnectionField("password", "演示密码", secret=True, placeholder="demo123", max_length=4096)),
                     _demo_factory, "broker_demo", "paper"),
    ConnectionDriver("unconfigured", "真实券商（接入预留）", "先保存接入资料；安装并验证对应券商官方适配器后才能只读连接。账号密码是否适用取决于券商的官方接口。",
                     (ConnectionField("broker_name", "券商名称", placeholder="后续选择的券商", max_length=80),
                      ConnectionField("account_id", "资金账号／客户号", masked=True),
                      ConnectionField("password", "密码（当前无需填写）", secret=True, required=False, max_length=4096))),
)


class ConnectionManager:
    """One selected connection. Save and disconnect invalidate in-flight work.

    ``drivers`` and ``register_driver`` are Python-only extension points. Driver
    factories must set bounded SDK timeouts and never log supplied credentials.
    Public profile fields are local plaintext. Account identifiers, passwords,
    and tokens are process-memory-only, cleared on disconnect and restart.
    """
    def __init__(self, root, gateway, *, drivers=()):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "broker_profile.json"
        self.gateway = gateway
        self.lock = RLock()
        self.drivers = {}
        for driver in (*BUILTIN_DRIVERS, *drivers):
            self.register_driver(driver)
        self.profile = {"driver": "demo", "fields": {}}
        self._secrets = {}
        self._revision = 0
        self._session = None
        self._adapter = None
        self.state = self._state("disconnected", "尚未连接；可先使用离线示例验证接入流程。")
        self._load()

    def register_driver(self, driver):
        if not isinstance(driver, ConnectionDriver) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", driver.id):
            raise ValueError("invalid connection driver")
        if driver.id in self.drivers:
            raise ValueError("duplicate connection driver")
        if driver.provider_id == "paper" or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", driver.provider_id):
            raise ValueError("invalid connection provider")
        if driver.environment not in {"paper", "live"} or (driver.provider_id == "live" and driver.environment != "live"):
            raise ValueError("invalid connection environment")
        if driver.factory is not None and not callable(driver.factory):
            raise ValueError("invalid connection factory")
        keys = [field.key for field in driver.fields]
        if len(keys) != len(set(keys)) or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", key) for key in keys):
            raise ValueError("invalid connection fields")
        with self.lock:
            self.drivers[driver.id] = driver

    @staticmethod
    def _state(status, message, provider_id=None):
        return {"status": status, "message": message, "provider_id": provider_id, "last_checked_at": _now()}

    @staticmethod
    def _mask(value):
        return "****" if len(value) <= 4 else "****" + value[-4:]

    def _validate_values(self, driver, values, secret):
        if not isinstance(values, dict):
            raise BrokerError("invalid_connection_config")
        allowed = {field.key: field for field in driver.fields if field.secret is secret}
        if any(key not in allowed for key in values):
            raise BrokerError("invalid_connection_config")
        result = {}
        for key, value in values.items():
            if not isinstance(value, str) or len(value) > allowed[key].max_length or "\x00" in value:
                raise BrokerError("invalid_connection_config")
            result[key] = value if secret else value.strip()
        return result

    def _load(self):
        if not self.path.exists():
            return
        try:
            if self.path.stat().st_size > 32768:
                raise ValueError()
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or set(value) != {"driver", "fields"}:
                raise ValueError()
            driver = self.drivers[value["driver"]]
            fields = self._validate_values(driver, value["fields"], False)
            if any(field.masked and field.key in fields for field in driver.fields):
                raise ValueError()
            self.profile = {"driver": driver.id, "fields": fields}
            self.state = self._state("disconnected", "已加载本机非敏感连接配置；账号密码不保存，重新连接前请再次填写。")
        except Exception:
            self.state = self._state("error", "本机连接配置无法读取，请重新保存；没有加载任何密码。")

    def _write_profile(self, profile):
        temp = self.root / f".broker-profile-{uuid4().hex}.tmp"
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(profile, stream, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.path)
        except Exception:
            raise BrokerError("broker_failure") from None
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _detach_locked(self):
        session = self._session
        if self._adapter:
            self._adapter.revoke()
        self._session = self._adapter = None
        return session

    @staticmethod
    def _close_session(session):
        if isinstance(session, ConnectionSession):
            try:
                session.close()
            except Exception:
                # SDK errors can include authentication details; never expose them.
                pass

    def snapshot(self):
        with self.lock:
            adapter, revision = self._adapter, self._revision
        if adapter:
            try:
                connected = adapter.status().connected
            except Exception:
                connected = False
            if connected:
                with self.lock:
                    if revision == self._revision and adapter is self._adapter:
                        self.state["last_checked_at"] = _now()
            else:
                with self.lock:
                    session = None
                    if revision == self._revision and adapter is self._adapter:
                        session = self._detach_locked()
                        self.state = self._state("error", "只读账户连接已不可用，请重新验证连接。")
                self._close_session(session)
        return self._snapshot()

    def _snapshot(self):
        with self.lock:
            driver = self.drivers[self.profile["driver"]]
            masked_keys = {field.key for field in driver.fields if field.masked}
            fields = self.profile["fields"]
            return {"drivers": [item.public() for item in self.drivers.values()],
                    "profile": {"driver": driver.id,
                                "fields": {k: v for k, v in fields.items() if k not in masked_keys},
                                "masked_fields": {k: self._mask(v) for k, v in fields.items() if k in masked_keys and v},
                                "saved_fields": [k for k, v in fields.items() if v],
                                "secret_fields_ready": [k for k, v in self._secrets.items() if v],
                                "memory_only_fields": [field.key for field in driver.fields if field.secret or field.masked]},
                    "state": deepcopy(self.state), "secrets_persisted": False, "read_only": True}

    def save(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"driver", "fields", "secrets"}:
            raise BrokerError("invalid_connection_config")
        with self.lock:
            driver_id = payload.get("driver", self.profile["driver"])
            if not isinstance(driver_id, str) or driver_id not in self.drivers:
                raise BrokerError("invalid_connection_config")
            driver = self.drivers[driver_id]
            changes = self._validate_values(driver, payload.get("fields", {}), False)
            secrets = self._validate_values(driver, payload.get("secrets", {}), True)
            same = driver_id == self.profile["driver"]
            profile = {"driver": driver_id, "fields": {**(self.profile["fields"] if same else {}), **changes}}
            private_keys = {field.key for field in driver.fields if field.masked}
            self._write_profile({"driver": driver_id, "fields": {k: v for k, v in profile["fields"].items() if k not in private_keys}})
            self.profile = profile
            self._secrets = {**(self._secrets if same else {}), **secrets}
            self._revision += 1
            session = self._detach_locked()
            self.state = self._state("disconnected", "非敏感配置已保存到本机；账号密码仅保留在本次会话，尚未验证连接。")
        self._close_session(session)
        return self.snapshot()

    def connect(self):
        with self.lock:
            if self.state["status"] == "connecting":
                raise BrokerError("connection_busy")
            driver = self.drivers[self.profile["driver"]]
            if driver.factory is None:
                self.state = self._state("error", "尚未安装此券商的适配器；仅保存了接入资料，不能连接或交易。")
                raise BrokerError("broker_unconfigured")
            fields, secrets = deepcopy(self.profile["fields"]), dict(self._secrets)
            for field in driver.fields:
                if field.required and not (secrets if field.secret else fields).get(field.key):
                    raise BrokerError("connection_credentials_missing")
            self._revision += 1
            revision = self._revision
            old_session = self._detach_locked()
            self.state = self._state("connecting", "正在验证只读连接；不会下单或撤单。")
        self._close_session(old_session)
        session = None
        try:
            session = driver.factory(fields, secrets)
            if not isinstance(session, ConnectionSession) or not isinstance(session.adapter, BrokerAdapter) or not callable(session.close):
                raise BrokerError()
            adapter = _ReadOnlyAdapter(session.adapter)
            status = adapter.status()
            if not status.connected or not status.capabilities.get("account"):
                raise BrokerError("broker_unavailable")
            _validate_handshake_account(adapter.account())
            with self.lock:
                if revision != self._revision:
                    raise BrokerError("connection_superseded")
                self.gateway.register(driver.provider_id, adapter, name=("离线券商示例（虚构）" if driver.id == "demo" else driver.name),
                                      environment=driver.environment)
                self._session, self._adapter = session, adapter
                self.state = self._state("connected", ("已连接离线示例，资金与成交均为虚构数据，只读。" if driver.id == "demo"
                                                       else "只读连接验证通过；下单与撤单仍未启用。"), driver.provider_id)
            return self.snapshot()
        except Exception as exc:
            self._close_session(session)
            with self.lock:
                stale = revision != self._revision
                # Accept a fixed demo validation error only from our own factory.
                code = "connection_superseded" if stale else (
                    "connection_auth_failed" if driver.factory is _demo_factory and isinstance(exc, BrokerError)
                    and exc.code == "connection_auth_failed" else "broker_failure")
                if not stale:
                    self.state = self._state("error", BrokerError(code).public_message)
            raise BrokerError(code) from None
        finally:
            secrets.clear()

    def disconnect(self):
        with self.lock:
            self._revision += 1
            session = self._detach_locked()
            self._secrets.clear()
            private_keys = {field.key for field in self.drivers[self.profile["driver"]].fields if field.masked}
            self.profile["fields"] = {k: v for k, v in self.profile["fields"].items() if k not in private_keys}
            self.state = self._state("disconnected", "已断开并清除内存账号和密码；已保存的非敏感连接配置仍保留。")
        self._close_session(session)
        return self.snapshot()

    def close(self):
        self.disconnect()
