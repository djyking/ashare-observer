"""Trusted-code template for adding a future official brokerage SDK.

This file is intentionally not auto-loaded, installs no SDK, and has no working
network connection. The HTTP client cannot choose Python modules or URLs.
Replace ``build_official_session`` only after verifying the broker's documented
authentication flow. Some SDKs authenticate in their desktop client and do not
accept a web username/password: tailor this schema to that SDK's actual needs.
"""
from ashare_monitor.brokers import ConnectionDriver, ConnectionField


def build_official_session(fields, secrets):
    """Implement in private local code, returning ConnectionSession(adapter, close).

    1. Validate ``client_path`` against an administrator-configured installation;
       never execute a path or command supplied directly by a web request.
    2. Initialize the approved SDK with bounded connection/read timeouts.
    3. Authenticate using the broker's actual documented mechanism, not a guessed
       password endpoint. Keep credentials inside the SDK session, never log them.
    4. Return a BrokerAdapter and its cleanup function. ``status`` must read local
       SDK connection state without an unbounded network request.
    5. Translate account/positions/orders/trades into the public DTO fields.
       Account verification requires nonempty currency and at least one numeric
       cash/available_cash/equity field. All supplied amounts must be finite
       numbers; only realized_pnl/unrealized_pnl may be negative.

    ConnectionManager wraps the returned adapter read-only; this template cannot
    enable real orders or cancellations even if the SDK advertises that ability.
    """
    raise NotImplementedError("No official brokerage SDK has been integrated.")


OFFICIAL_DRIVER_TEMPLATE = ConnectionDriver(
    id="official_sdk_template",
    name="官方券商 SDK 模板（尚未接入）",
    description="开发接入模板，不会连接券商；安装并验证官方 SDK 后再由开发者注册可用工厂。",
    fields=(
        ConnectionField("broker_name", "券商名称"),
        ConnectionField("client_path", "已安装的官方客户端目录", required=False),
        ConnectionField("account_id", "资金账号", masked=True),
        ConnectionField("password", "密码（仅当官方 SDK 需要）", secret=True, required=False, max_length=4096),
    ),
    factory=None,  # Replace with the implemented factory only after integration tests.
)


# Supply trusted definitions before the saved profile is loaded, on every run:
#   DashboardServer(address, runtime, broker_drivers=(OFFICIAL_DRIVER_TEMPLATE,))
# Runtime registration alone is unsuitable for restoring a saved custom profile.
