"""Offline adapter contract example. No SDK, credentials, or real orders.

Run from the repository root:
    python -m examples.demo_broker_adapter
"""
from ashare_monitor.brokers import BrokerAdapter, BrokerError, BrokerStatus, OPERATIONS


class ContractDemoAdapter(BrokerAdapter):
    """Fixed test fixtures used to illustrate integration, not an account feed."""

    def status(self):
        return BrokerStatus(True, {key: True for key in OPERATIONS})

    def account(self):
        return {"currency": "CNY", "cash": 1000.0, "available_cash": 1000.0,
                "frozen_cash": 0.0, "equity": 1000.0, "valuation_complete": True}

    def positions(self):
        return []

    def orders(self):
        return []

    def trades(self):
        return []

    def place_order(self, payload):
        raise BrokerError("trading_disabled")

    def cancel_order(self, payload):
        raise BrokerError("trading_disabled")


def register_contract_demo(gateway):
    """Explicit developer-only hook; not imported by the application server."""
    gateway.register("contract_demo", ContractDemoAdapter(), name="离线接口测试样本", environment="live")


if __name__ == "__main__":
    import json
    print("离线接口样本：以下均为固定测试数据，不是券商账户。")
    print(json.dumps(ContractDemoAdapter().account(), ensure_ascii=False, indent=2))
