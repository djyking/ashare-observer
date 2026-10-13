"""Small, SDK-independent contract for account adapters.

An adapter translates its provider's models into the public fields documented in
docs/BROKER_ADAPTER.md. Credentials belong inside the adapter, never in its DTOs.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


OPERATIONS = ("account", "positions", "orders", "trades", "place_order", "cancel_order")

ERRORS = {
    "unknown_provider": (404, "没有这个账户提供方。"),
    "broker_unconfigured": (409, "尚未接入券商，不能查询证券账户或提交实盘委托。"),
    "broker_unavailable": (503, "账户连接暂不可用，请稍后检查连接状态。"),
    "trading_disabled": (409, "该账户的下单与撤单功能未启用。"),
    "operation_unsupported": (409, "该账户暂不支持此操作。"),
    "broker_busy": (409, "数据更新中，暂不能修改模拟委托，请稍后重试。"),
    "invalid_request": (400, "委托参数不符合账户规则，请检查代码、股数、交易方向和请求编号。"),
    "broker_failure": (502, "账户接口请求失败；未向页面返回接口内部信息。"),
}


class BrokerError(Exception):
    """Only fixed public messages cross the HTTP boundary, never SDK errors."""

    def __init__(self, code="broker_failure"):
        self.code = code if isinstance(code, str) and code in ERRORS else "broker_failure"
        self.status_code, self.public_message = ERRORS[self.code]
        super().__init__(self.public_message)


class PaperValidationError(BrokerError):
    """Application-owned validation text, never created from a broker SDK."""

    def __init__(self, message):
        super().__init__("invalid_request")
        self.public_message = str(message)[:300]
        self.args = (self.public_message,)


@dataclass(frozen=True)
class BrokerStatus:
    connected: bool
    capabilities: dict[str, bool] = field(default_factory=dict)
    # A closed set of keys lets the gateway provide its own public wording.
    message_key: str = "connected"


class BrokerAdapter(ABC):
    """Implement this in a local package to integrate a verified provider.

    Methods must be synchronous and bounded by provider SDK timeouts. Preserve
    provider order IDs and implement request_id idempotency in the adapter.
    """

    @abstractmethod
    def status(self) -> BrokerStatus: ...

    @abstractmethod
    def account(self) -> dict[str, Any]: ...

    @abstractmethod
    def positions(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def orders(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def trades(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def cancel_order(self, payload: dict[str, Any]) -> dict[str, Any]: ...
