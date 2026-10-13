# 券商适配接口

本项目已提供可扩展的 Python 账户接口和受保护的 HTTP 入口，尚未安装或验证任何具体券商 SDK。接口费用、资产门槛、开户条件和运行环境由所选券商确认，不能据此认定接口收费或免费。

当前页面可读取现有模拟账本，并通过同一接口登记、撤销模拟委托。`live` 是未连接的券商占位；不能靠页面、HTTP 请求、环境变量或配置文件开启实盘交易。本轮提供的是接入扩展边界，不是已完成的证券账户连接。

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
| `trades()` | 成交列表；保留成交价格、数量、费用和委托编号 |
| `place_order(payload)` | 校验业务规则、持久化请求幂等信息，再提交委托；成功返回 `{"ok": true}` |
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

默认 `provider` 只有 `paper` 和 `live`。未知名称返回 404，绝不回落到模拟账户。写请求沿用页面的同源和 `X-CSRF-Token` 校验。旧 `/api/paper/order`、`/api/paper/cancel` 仍兼容。

`paper` 桥接原 `Runtime`，不复制资金状态，也不创建新账本：资金冻结、T+1、整手约束、观察列表、合成行情来源限制、扫描互斥和持久化都由已有逻辑处理。切到公开日线或 CSV 研究模式后，模拟账户可读、模拟写入被拒绝。

## 公开数据与错误边界

- 网关仅输出显式白名单字段，丢弃 `account_id`、原始 SDK 回包、自由格式内部错误等字段；浏览器无需账户身份或密钥。
- SDK 返回字段映射由适配器负责。不要把账号、密钥或原始异常塞进 `name`、委托编号等合法公开字段。
- `BrokerError` 只输出固定的中文公开文案和错误码；SDK 异常字符串不回传浏览器。
- 读账户数据本身仍有隐私，服务默认仅监听本机；不要直接公开发布运行实例。

| 错误码 | HTTP |
|---|---:|
| `unknown_provider` | 404 |
| `broker_unconfigured` / `trading_disabled` / `operation_unsupported` / `broker_busy` | 409 |
| `invalid_request` | 400 |
| `broker_unavailable` | 503 |
| `broker_failure` | 502 |

将来对接需要：券商名称和官方文档、账户的程序化权限、模拟或测试环境、支持的操作系统/客户端、费率与规则、成交回报和对账方式。账户、密码、私钥和令牌只在本机私有存储中配置，不能写入源码、示例、日志或 Git 历史；提交前仍须检查暂存区，不应只依赖 `.gitignore`。
