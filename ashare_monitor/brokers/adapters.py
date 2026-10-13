"""Default providers: the existing demo ledger and an unconfigured live slot."""
from copy import deepcopy
from typing import TYPE_CHECKING

from .base import BrokerAdapter, BrokerError, BrokerStatus, OPERATIONS

if TYPE_CHECKING:
    from ..runtime import Runtime


class PaperBrokerAdapter(BrokerAdapter):
    def __init__(self, runtime: "Runtime"):
        self.runtime = runtime

    def status(self):
        with self.runtime.lock:
            demo = self.runtime.state["settings"]["mode"] == "demo"
            idle = not self.runtime.refreshing
        capabilities = {operation: True for operation in OPERATIONS}
        capabilities.update(place_order=demo and idle, cancel_order=demo and idle)
        return BrokerStatus(True, capabilities, "paper" if demo else "paper_readonly")

    def _view(self):
        with self.runtime.lock:
            return deepcopy(self.runtime._portfolio_view())

    def account(self):
        view = self._view()
        return {**view, "currency": "CNY"}

    def positions(self):
        return self._view()["positions"]

    def orders(self):
        return self._view()["orders"]

    def trades(self):
        return self._view()["trades"]

    def _mutate(self, method, payload):
        from ..runtime import BusyError

        try:
            return method(payload)
        except BusyError:
            raise BrokerError("broker_busy") from None
        except (ValueError, TypeError, KeyError):
            raise BrokerError("invalid_request") from None

    def place_order(self, payload):
        return self._mutate(self.runtime.paper_order, payload)

    def cancel_order(self, payload):
        return self._mutate(self.runtime.cancel, payload)


class UnconfiguredBrokerAdapter(BrokerAdapter):
    """No credential loading, network calls, or fallback to the demo account."""

    def status(self):
        return BrokerStatus(False, {operation: False for operation in OPERATIONS}, "unconfigured")

    def _reject(self, *args):
        raise BrokerError("broker_unconfigured")

    account = _reject
    positions = _reject
    orders = _reject
    trades = _reject
    place_order = _reject
    cancel_order = _reject
