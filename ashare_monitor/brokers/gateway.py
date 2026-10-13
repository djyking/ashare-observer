"""Provider dispatch and an explicit, credentials-free public response boundary."""
from dataclasses import dataclass
import math
import re
from threading import RLock

from .adapters import PaperBrokerAdapter, UnconfiguredBrokerAdapter
from .base import BrokerAdapter, BrokerError, BrokerStatus, PaperValidationError, OPERATIONS


MESSAGES = {
    "connected": "账户适配器已连接。",
    "paper": "使用现有合成行情模拟账本；不连接证券账户。",
    "paper_readonly": "模拟账本只读；切回合成演示行情可管理模拟委托。",
    "unconfigured": "券商接入扩展点已预留；尚未安装并验证具体券商适配器。",
    "unavailable": "账户连接暂不可用。",
    "demo_connection": "离线券商示例：以下均为虚构固定数据，只读；与模拟账本和真实账户无关。",
}
ACCOUNT_FIELDS = {
    "currency", "initial_cash", "cash", "available_cash", "frozen_cash", "equity",
    "realized_pnl", "unrealized_pnl", "fees", "as_of", "valuation_complete",
}
POSITION_FIELDS = {
    "code", "name", "quantity", "sellable", "frozen", "avg_cost", "last_price",
    "price_date", "price_stale", "market_value", "unrealized_pnl", "sellable_on_execution",
}
ORDER_FIELDS = {
    "id", "request_id", "code", "name", "side", "quantity", "status", "created_date", "limit_price",
    "execute_after", "filled_date", "filled_price", "reserved_cash",
    "last_checked_date", "expired_date", "cancelled_date",
}
TRADE_FIELDS = {"id", "order_id", "date", "side", "code", "name", "quantity", "price", "notional", "fee", "pnl"}


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    environment: str
    adapter: BrokerAdapter


def _project(record, fields):
    if not isinstance(record, dict):
        raise BrokerError()
    output = {}
    for key in fields:
        if key not in record:
            continue
        value = record[key]
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise BrokerError()
        if isinstance(value, float) and not math.isfinite(value):
            raise BrokerError()
        if isinstance(value, str) and len(value) > 160:
            raise BrokerError()
        output[key] = value
    return output


class BrokerGateway:
    """The web app uses the safe default; registration is a Python-only hook.

    This release deliberately exposes no live-trading enable switch. A concrete
    provider may be registered for read-only integration tests. Enabling live
    mutations requires a separate reviewed execution policy, outside this app.
    """

    def __init__(self, runtime):
        self._lock = RLock()
        self._providers = {}
        self.register("paper", PaperBrokerAdapter(runtime), name="模拟账本", environment="paper")
        self.register("live", UnconfiguredBrokerAdapter(), name="券商实盘", environment="live")

    def register(self, provider_id, adapter, *, name, environment):
        """Register/replace an adapter in trusted application startup code.

        No module paths, SDK objects, credentials, or register calls are accepted
        via HTTP. Environment is fixed by the gateway, never by request payloads.
        """
        if not isinstance(provider_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", provider_id):
            raise ValueError("invalid provider id")
        if not isinstance(adapter, BrokerAdapter):
            raise TypeError("adapter must implement BrokerAdapter")
        if not isinstance(name, str) or not 1 <= len(name) <= 50 or environment not in {"paper", "live"}:
            raise ValueError("invalid provider metadata")
        if provider_id == "paper" and environment != "paper":
            raise ValueError("paper slot cannot contain a live adapter")
        if provider_id == "live" and environment != "live":
            raise ValueError("live slot cannot contain a paper adapter")
        with self._lock:
            self._providers[provider_id] = Provider(provider_id, name, environment, adapter)

    def _provider(self, provider_id):
        with self._lock:
            if not isinstance(provider_id, str) or provider_id not in self._providers:
                raise BrokerError("unknown_provider")
            return self._providers[provider_id]

    def _status(self, provider):
        try:
            status = provider.adapter.status()
            if not isinstance(status, BrokerStatus) or type(status.connected) is not bool:
                raise ValueError()
            capabilities = {key: status.connected and status.capabilities.get(key) is True for key in OPERATIONS}
            if provider.environment == "live":
                capabilities.update(place_order=False, cancel_order=False)
            return {"id": provider.id, "name": provider.name, "environment": provider.environment,
                    "connected": status.connected, "capabilities": capabilities,
                    "message": MESSAGES.get(status.message_key, MESSAGES["connected" if status.connected else "unavailable"])}
        except Exception:
            return {"id": provider.id, "name": provider.name, "environment": provider.environment,
                    "connected": False, "capabilities": {key: False for key in OPERATIONS},
                    "message": MESSAGES["unavailable"]}

    def catalog(self):
        with self._lock:
            providers = list(self._providers.values())
        return {"providers": [self._status(p) for p in providers], "live_enabled": False}

    def _invoke(self, provider_id, operation, payload=None):
        provider = self._provider(provider_id)
        status = self._status(provider)
        if isinstance(provider.adapter, UnconfiguredBrokerAdapter):
            raise BrokerError("broker_unconfigured")
        if not status["connected"]:
            raise BrokerError("broker_unavailable")
        if not status["capabilities"][operation]:
            raise BrokerError("trading_disabled" if operation in {"place_order", "cancel_order"} else "operation_unsupported")
        try:
            method = getattr(provider.adapter, operation)
            result = method(payload) if operation in {"place_order", "cancel_order"} else method()
            if operation == "account":
                value = _project(result, ACCOUNT_FIELDS)
                body = {"account": value}
            elif operation in {"positions", "orders", "trades"}:
                if not isinstance(result, list):
                    raise BrokerError()
                fields = {"positions": POSITION_FIELDS, "orders": ORDER_FIELDS, "trades": TRADE_FIELDS}[operation]
                body = {operation: [_project(row, fields) for row in result]}
            else:
                if not isinstance(result, dict) or result.get("ok") is not True:
                    raise BrokerError()
                body = {"ok": True, "message": "模拟委托已登记。" if operation == "place_order" else "模拟委托已撤销。"}
                if result.get("order") is not None:
                    body["order"] = _project(result["order"], ORDER_FIELDS)
            return {"provider": provider.id, "environment": provider.environment, **body}
        except BrokerError as exc:
            if type(provider.adapter) is PaperBrokerAdapter and isinstance(exc, PaperValidationError):
                raise PaperValidationError(exc.public_message) from None
            # Rebuild it: a third-party adapter may have modified exception text.
            raise BrokerError(exc.code) from None
        except Exception:
            raise BrokerError("broker_failure") from None

    def account(self, provider_id):
        return self._invoke(provider_id, "account")

    def positions(self, provider_id):
        return self._invoke(provider_id, "positions")

    def orders(self, provider_id):
        return self._invoke(provider_id, "orders")

    def trades(self, provider_id):
        return self._invoke(provider_id, "trades")

    def place_order(self, provider_id, payload):
        return self._invoke(provider_id, "place_order", payload)

    def cancel_order(self, provider_id, payload):
        return self._invoke(provider_id, "cancel_order", payload)
