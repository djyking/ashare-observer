# 券商适配接口

本项目已提供可扩展的 Python 账户接口和受保护的 HTTP 入口，尚未安装或验证任何具体券商 SDK。接口费用、资产门槛、开户条件和运行环境由所选券商确认，不能据此认定接口收费或免费。

页面提供账号、密码与连接参数输入、保存、验证连接、断开以及账户查询。`demo` 是内置的离线只读连接示例，`unconfigured` 是未安装真实券商驱动的资料预留项；不会将“已保存”当作“已连接”。`live` 默认仍是未连接的券商占位，不能靠页面、HTTP 请求、环境变量或配置文件开启实盘交易。

## 网页连接与凭据

在“券商接入”选择离线示例，账号 `demo`、密码 `demo123`，保存并验证连接后可查看虚构的账户、持仓、委托、成交。成功提供方为 `broker_demo`，它与 `paper` 手动模拟账本完全独立。此公开演示密码不是任何真实账户的凭据。

| 请求 | 用途 |
|---|---|
| `GET /api/broker/connection` | 驱动及字段定义、已填配置掩码、凭据是否已提供、连接状态 |
| `POST /api/broker/connection/save` | `{driver, fields, secrets}`；校验并保存，撤销旧连接，不自动登录 |
| `POST /api/broker/connection/connect` | `{}`；使用已填配置建立只读会话，并验证账户查询 |
| `POST /api/broker/connection/disconnect` | `{}`；撤销读取能力，关闭 SDK 会话并清除敏感字段 |

同一驱动下，省略字段表示保留，显式空字符串表示清空；切换驱动会丢弃旧字段。保存失败不覆盖原配置。账号和密码等 `masked` / `secret` 字段只在服务进程内存中保留，账号只返回掩码，密码不回传。断开或重启后必须重新填写。网页不使用 localStorage 保存凭据，离开页面清空尚未提交的敏感输入。

只有驱动名及非敏感参数写入 `var/broker_profile.json`，该目录被 Git 忽略。Python 内存中的字符串不具备可验证的安全擦除保证；本版本提供的是不落盘和不外传的边界，不承诺抵御已取得本机进程读取权限的攻击。

`state.status` 分为 `disconnected`、`connecting`、`connected`、`error`；成功后的 `state.provider_id` 用于既有账户查询接口。错误密码、缺字段、未安装驱动和连接过程中更改配置有不同的固定错误码。未知字段、动态模块名和任意 SDK URL 不作为连接配置接受。

## 可插入的连接驱动

`ConnectionManager` 位于 `ashare_monitor.brokers`。可信启动代码定义 `ConnectionDriver` 的字段和工厂；HTTP 只能选择已注册驱动。将自定义驱动传给 `DashboardServer(..., broker_drivers=(driver,))`，在读取本机配置前注册，这样重启后才能识别并恢复非敏感设置。字段示例：

```python
from ashare_monitor.brokers import ConnectionDriver, ConnectionField, ConnectionSession
from ashare_monitor.server import DashboardServer

# connect_official_sdk 由具体官方 SDK 的实现提供，需设置连接及读取超时。
# 该函数接收 fields / secrets，返回 ConnectionSession(adapter, close_callback)。
def build_server(runtime, connect_official_sdk):
    driver = ConnectionDriver(
        id="official_local", name="已验证的本地券商接口",
        description="需安装对应官方客户端并开通账户权限。",
        fields=(
            ConnectionField("account_id", "资金账号", masked=True),
            ConnectionField("client_path", "官方客户端路径"),
            ConnectionField("password", "密码", secret=True, required=False),
        ),
        factory=connect_official_sdk,
    )
    return DashboardServer(("127.0.0.1", 18766), runtime, broker_drivers=(driver,))
```

账号等身份字段必须 `masked=True`，密码、令牌必须 `secret=True`。字段名不能用来加载任意模块、执行 shell 命令或跳转到不受信任的服务。需要本地客户端的券商由驱动验证客户端路径；不能默认所有券商都接受网页账号密码认证。

工厂返回实现 `BrokerAdapter` 的对象和关闭回调。首次连接会验证 `status()` 和 `account()`；页面刷新状态时复核连接是否仍有效。`status()` 应读取 SDK 本地连接状态并快速返回；所有网络调用必须配置有限超时，不能无限挂起。保存新配置或断开会使旧的异步连接结果失效，迟到的会话被关闭，不重新挂回账户。SDK 异常只返回固定错误，不得打印凭据或原始回包。

连接管理器为任何驱动再加只读包装，即使某驱动能力声明错误也无法通过此会话下单或撤单。未来实际下单需要单独验收执行政策、授权、幂等、风控和成交对账，不能去掉包装就宣称已完成实盘系统。

账户握手至少提供非空 `currency` 和 `cash` / `available_cash` / `equity` 中的一项；所有返回的资金字段必须是有限数字，不能用字符串、布尔值或空对象冒充成功。除已实现和未实现盈亏可为负数，其余资金字段要求非负。零余额是有效账户；未提供的可选字段在页面显示“—”。后续集成 A 股账户时应明确人民币口径，并尽量提供可用资金和总权益。开发模板见 `examples/broker_connection_driver.py`，模板没有安装任何 SDK，也不会自动连接网络。

## Python 扩展边界

公共类型位于 `ashare_monitor.brokers`：

```python
from ashare_monitor.brokers import BrokerAdapter, BrokerStatus, BrokerGateway

class MyBrokerAdapter(BrokerAdapter):
    # 在实际实现中覆盖全部抽象方法；使用获授权的券商官方 SDK。
    pass

# 在自己维护的应用启动代码中注册，不能通过 HTTP 导入模块。
# gateway = BrokerGateway(runtime)
# gateway.register("live", my_adapter, name="已验证的券商连接", environment="live")
```

| 方法 | 约定 |
|---|---|
| `status()` | `BrokerStatus(connected, capabilities, message_key)`；不携带登录信息 |
| `account()` | 人民币资金与估值字段的字典；不含账号、用户名、凭据 |
| `positions()` | 持仓列表；包含总数量、可卖数量、冻结数量和估值 |
| `orders()` | 委托列表；保留不含账号的委托编号、状态、数量和日期 |
| `trades()` | 成交列表；保留成交 `id`、关联 `order_id`、价格、数量和费用 |
| `place_order(payload)` | 校验业务规则、持久化请求幂等信息，再提交委托；成功返回 `{"ok": true, "order": {...}}`，其中 `order` 为可选公开委托字段 |
| `cancel_order(payload)` | 查询并撤销指定委托；区分已成交、部分成交与已撤销 |

能力名依次为 `account`、`positions`、`orders`、`trades`、`place_order`、`cancel_order`。网关根据实际能力拒绝不支持的请求。当前版本对所有 `environment="live"` 的适配器统一关闭下单与撤单；即使某 SDK 声称支持交易，网关也不会调用它的这两个方法。

注册适配器后可先做只读资金、持仓与成交对账。正式实盘执行还需要独立补充并验收委托类型、价格限制、交易时段、账户权限、幂等恢复、成交回报、费用和风控，才能改变当前只读执行策略。

`examples/demo_broker_adapter.py` 是可运行的离线接口样本。它仅返回固定测试数据，不访问网络，也不自动加载到应用。运行：

```console
python -m examples.demo_broker_adapter
```

## HTTP 入口

| 请求 | 返回/用途 |
|---|---|
| `GET /api/brokers` | `providers` 列表及 `live_enabled: false` |
| `GET /api/brokers/{provider}/account` | `{provider, environment, account}` |
| `GET /api/brokers/{provider}/positions` | `{provider, environment, positions}` |
| `GET /api/brokers/{provider}/orders` | `{provider, environment, orders}` |
| `GET /api/brokers/{provider}/trades` | `{provider, environment, trades}` |
| `POST /api/brokers/{provider}/orders` | `{side, code, quantity, request_id}`；模拟委托 |
| `POST /api/brokers/{provider}/cancel` | `{order_id}`；撤销模拟委托 |
| `POST /api/paper/preview` | `{side, code, quantity}`；只读预检查，无冻结或下单副作用 |
| `GET /api/paper/records?kind=orders&page=1` | 委托分页，每页 30 条；`kind=trades` 为成交分页 |

默认 `provider` 只有 `paper` 和 `live`。未知名称返回 404，绝不回落到模拟账户。写请求沿用页面的同源和 `X-CSRF-Token` 校验。旧 `/api/paper/order`、`/api/paper/cancel` 仍兼容。

`paper` 桥接原 `Runtime`，不复制资金状态，也不创建新账本：资金冻结、T+1、整手约束、观察列表、合成行情来源限制、扫描互斥和持久化都由已有逻辑处理。切到公开日线或 CSV 研究模式后，模拟账户可读、模拟写入被拒绝。

模拟登记和撤销结果包含 `order` 的公开字段，调用方可据 `id/status/quantity/request_id` 对账，不能仅因 HTTP 200 就把“待成交”当作“已成交”。预检查显示估计费用、资金与下一交易日可卖股份；正式提交仍再次检查。在当日开盘买入后，可以预约次日卖出，实际成交日仍检查 T+1。

## 公开数据与错误边界

- 网关仅输出显式白名单字段，丢弃 `account_id`、原始 SDK 回包、自由格式内部错误等字段；页面可提交连接凭据，但读取结果不得回传其原文。
- SDK 返回字段映射由适配器负责。不要把账号、密钥或原始异常塞进 `name`、委托编号等合法公开字段。
- 第三方 `BrokerError` 只输出固定的中文公开文案和错误码；SDK 异常字符串不回传浏览器。应用自有、精确匹配的 `PaperBrokerAdapter` 可返回自己的业务校验原因（例如“含费用需冻结 1105.01 元”），使用内部 `PaperValidationError`；其他适配器即使抛同名错误，也不会获准透传自由文本。
- 读账户数据本身仍有隐私，服务默认仅监听本机；不要直接公开发布运行实例。

| 错误码 | HTTP |
|---|---:|
| `unknown_provider` | 404 |
| `broker_unconfigured` / `trading_disabled` / `operation_unsupported` / `broker_busy` | 409 |
| `invalid_request` | 400 |
| `broker_unavailable` | 503 |
| `broker_failure` | 502 |
| `invalid_connection_config` / `connection_credentials_missing` | 400 |
| `connection_auth_failed` | 401 |
| `connection_busy` / `connection_superseded` | 409 |

将来对接需要：券商名称和官方文档、账户的程序化权限、模拟或测试环境、支持的操作系统/客户端、费率与规则、成交回报和对账方式。真实账号、密码、私钥和令牌不能写入源码、示例、日志或 Git 历史；提交前仍须检查暂存区，不应只依赖 `.gitignore`。
