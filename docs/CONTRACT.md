# A 股量化交易研究平台：模块契约

Python 3.12 后端仅使用标准库，前端使用 Vue 3、TypeScript 和 Vite。入口 `python -m ashare_monitor --port 18766`，默认离线演示，未连接证券账户。前端源码位于 `frontend/`，生产资源位于 `ashare_monitor/web/`，由同一个 Python 服务提供。

## 数据

`data.py`: `DEFAULT_WATCHLIST` 为代码列表；`load_market(mode, codes, as_of, csv_dir=None)` 返回 `{mode,source,fetched_at,as_of,stocks,errors}`。mode 为 `demo/eastmoney/csv`。as_of 是 YYYY-MM-DD，仅包含已收盘日线；真实模式不得以演示数据填充失败。

股票结构 `{code,name,exchange,board,sector,status,error,data_date,candles,raw_candles,adjustment,risk_warning,listing_date,metadata_verified}`。board 为 `main/growth/star/beijing`。candles 为分析日线（真实模式前复权），raw_candles 为同日期不复权日线；演示模式均为 none。日线 `{date,open,high,low,close,volume,amount}`，金额人民币元、数量股。无可靠不复权数据不得模拟成交。需验证日期、价格、非有限数、重复、OHLC及成交量。listing_date 未知则 None，禁止据此断言非新股。

`analysis.py`: `analyze_stock(stock, config=None)` 返回 `{code,name,score,status,route,reasons,indicators,plan,history,chart_series,score_components,strategy_results,strategy_history,strategy_version}`。status 为 `watch/wait/insufficient/unavailable`，不是买入授权或盈利概率。plan 可空，否则 `{reference_price,stop_price,target_price,expected_gain_pct,risk_pct}` 必须明确仅研究情景，真实 qfq 不能作为当前可成交原价。图表直接使用后端 chart_series，与评分共用 EMA 初始化和指标序列。历史信号只使用该日及之前资料。

`strategies.py`: `strategy_catalog()` 返回三类公开策略、参数说明、范围和 defaults；`normalize_strategy_config()` 校验并补全 `teaching/pullback/breakout` 配置。策略启用与否决定候选分类，不伪装为盈利概率。

## 日历与模拟账本

`rules.py`: `is_trading_day(date_str)`, `next_trading_day(date_str)`, `last_closed_day(now=None)`（返回 YYYY-MM-DD），`market_session(now=None)`（返回 `{label,is_open,calendar_known}`），年份未覆盖必须显式拒绝交易。

`portfolio.py`: `new_ledger(initial_cash=100000)`, `place_order(ledger, side, code, quantity, trade_date, stocks, request_id)` 返回新账本，`advance_ledger(ledger, stocks, trade_date)` 返回新账本，`portfolio_view(ledger, stocks, trade_date)` 返回视图。stocks 为上述股票对象列表。纯函数、deepcopy、金额用 Decimal 算，存储JSON可序列化；失败 raise ValueError。订单在后续可用交易日开盘模拟撮合（收盘信号不在同根收盘成交）。买入T+1可卖、数量规则、费用、涨跌停、停牌/缺数据处理。只演示模式开放下单/推进时钟；真实行情与CSV只用于只读研究。账本状态由主程序持久化，与数据模式隔离。

账本视图字段：`initial_cash,cash,equity,realized_pnl,unrealized_pnl,fees,positions,orders,trades`。持仓含 `code,name,quantity,sellable,avg_cost,last_price,market_value,unrealized_pnl`。委托含 `id,side,code,quantity,status,created_date,reason`；成交含 `date,side,code,quantity,price,fee,pnl`。空持仓允许。订单 request_id 去重。订单上限/资金检查由该层执行。

## HTTP 与界面

`GET /api/state` => `{app:{name,version,mode,as_of,source,fetched_at,refreshing,last_error,notice},session,stats,stocks,analyses,portfolio,settings,csrf_token}`。

stats 为 `{stock_count,valid_count,watch_count,wait_count}`。

settings 为 `{mode,watchlist,refresh_seconds,initial_cash,auto_refresh}`。

`GET /api/history?page=1&page_size=30` => `{items,total,page,page_size,pages}`。

`POST /api/refresh` 空JSON：后台扫描，立即返回202。

`POST /api/settings` => `{mode,watchlist:[code],refresh_seconds,auto_refresh}`；不允许通过更改设置清空账本。

`POST /api/paper/order` => `{side:'buy'/'sell',code,quantity,request_id}`；仅离线演示。

`POST /api/paper/cancel` => `{order_id}`；取消待成交模拟委托。

`POST /api/demo/advance` 空JSON：推进下个交易日、扫描及撮合；后台更新，立即返回202。

所有POST要求 `X-CSRF-Token`，从state读取。固定loopback访问，Origin/Host检查；未接通可执行真实下单的通道。前端不得并发刷新覆写较新的快照。统一错误 `{error}`。

## 券商适配接口

`ashare_monitor.brokers` 定义 `BrokerAdapter` 抽象基类、`BrokerGateway` 及 `BrokerError`。`paper` 对接现有模拟账本，`live` 为未连接的实盘适配器；接口形式存在不表示已经接通券商。具体扩展流程见 [券商适配指南](BROKER_ADAPTER.md)。

`GET /api/brokers` 返回 `{providers:[{id,name,environment,connected,capabilities:{account,positions,orders,trades,place_order,cancel_order},message}],live_enabled:false}`。

`GET /api/brokers/{provider}/{account|positions|orders|trades}` 读取相应资源。

`POST /api/brokers/{provider}/orders` 接受与 `/api/paper/order` 相同的载荷；`POST /api/brokers/{provider}/cancel` 接受与 `/api/paper/cancel` 相同的载荷。它们同样需要 CSRF 与同源校验，模拟操作不得绕过模式限制。未连接或不具备能力的适配器返回明确错误，不回退为模拟订单，也不启动真实下单。

适配器业务错误返回结构化错误码与说明；通用操作错误仍使用上述 `{error}` 格式。凭据不进入状态快照或前端构建，仓库不提供可通过页面直接开启的实盘交易开关。

## 前端状态约定

首次数据到达前禁用依赖快照的输入。页面轮询需保留用户编辑中的表单，卸载后使旧响应失效并阻止新请求，拒绝旧快照覆盖新状态。历史研究每页 30 条并按需展开详情；请求失败要显示错误并允许重试，不应清空仍有效的上一份快照。网络请求另设超时，卸载失效不等于撤销后端已接受的操作。

TypeScript 类型对应 HTTP 契约，不改变 Python 对资金、数量、日历与请求参数的最终校验。Vite 开发代理转发到本机 Python 服务；生产环境直接同源请求，后端仍保留 Host、Origin 与 CSRF 校验。

页面有概览/观察列表、单股 K 线与指标、模拟持仓/委托/成交、独立历史策略研究、扫描历史、设置与规则说明。演示数据与真实行情显著区分，红涨绿跌。筛选排序不能扰乱输入编辑。

## 1.3 网页连接生命周期

`GET /api/broker/connection` 返回注册驱动及字段 schema、脱敏配置与连接状态。`POST /api/broker/connection/save` 接受 `{driver, fields, secrets}`，只允许该驱动定义的字段；保存后断开旧连接，不自动登录。`POST /api/broker/connection/connect` 与 `/disconnect` 只接受空对象，需要同源与 CSRF 校验。

字段标记为 `secret` 或 `masked` 时仅保存在进程内存中，不写配置文件。账号返回掩码，密码只返回“已提供”的状态，不返回值；断开和服务重启会清除两者。普通配置保存在私有数据目录。成功连接后使用 `state.provider_id` 查询既有 `/api/brokers/{provider}/...` 接口，连接工厂由可信 Python 启动代码注册，不能通过 HTTP 导入模块。

内置 `demo` 仅通过公开演示凭据连接虚构数据，提供方为 `broker_demo`；`unconfigured` 明确报告缺少真实券商驱动。所有连接会话强制只读，不影响原手动模拟账本。详细错误与扩展约定见 [券商适配指南](BROKER_ADAPTER.md)。

## 1.2 新增与调整

- `GET /api/state` 为精简快照：不返回股票 raw_candles 及完整账本 orders/trades；portfolio 增加 order_count/trade_count。包含当前 paper_experiment 和 research_busy。Python `snapshot(token)` 默认完整，HTTP 使用 compact=True。
- `GET /api/paper/records?kind=orders|trades&page=1` 在后端按时间倒序切片，每页 30 条，结构 `{items,total,page,pages,page_size}`。
- `POST /api/paper/preview {side,code,quantity}` 返回 allowed/message、股数规则、参考价、费用、预留资金、当前及执行日可卖数量；不修改账本。预览与提交共用校验，执行时再按实际日线复核。
- `GET /api/strategies` 返回目录。settings 增加 strategy_config、watchlist_groups；股票池 1～50 只，分组最多 20 组，每组至多 50 个代码。保存后重新后台分析。
- `GET /api/stocks/search?q=` 提供代码/名称搜索；`GET /api/stocks/templates` 返回 `{items}`。目录记录不代表交易元数据已核实。
- `GET /api/imports/template` 返回 UTF-8 CSV 示例。`POST /api/imports/validate {code,text}` 返回 valid/errors/warnings 及日期范围；`POST /api/imports/commit {code,text,overwrite?}` 校验后原子写入 `var/imports/<code>.csv`。上限 1 MB，不接受调用方文件路径；不同内容覆盖须显式请求。导入不切换当前数据源、不改变账户。
- `GET /api/history/{id}` 返回历史摘要及 `details`：当时的策略配置、股票元数据和分析结果。旧版本只有摘要时 details=null；不会拿今天的分析冒充历史快照。
- `POST /api/demo/experiments {name,initial_cash,start_date}` 原子归档旧演示账本并创建新账本，202 后后台扫描。`GET /api/demo/experiments?page=1` 返回归档摘要，`GET /api/demo/experiments/{id}` 返回 report.portfolio、report.ledger、report.demo_date。演示日期限制在已知日历内。
- `POST /api/research {name,mode,codes,...config}` 创建独立后台回放，返回 202 `{id,status,accepted}`。config 见 [研究契约](RESEARCH.md)。一次一个研究任务，运行中重复提交返回 409。研究采用自己的来源和股票池，不更改观察列表、数据模式或手动账本。
- `GET /api/research?page=1` 返回每页 30 条摘要，SQL 层裁剪完整 report/dataset；`GET /api/research/{id}` 返回配置、状态、report 或 error，不传完整输入 dataset。输入数据在本机数据库保存，报告保留 SHA-256 数据标识。
- `POST /api/research/{id}/archive {}` 只标记完成/失败实验归档，不删除结果。进程重新启动时，遗留 running 研究标记失败并说明中断，不永久显示运行中。

历史回放与手动演示账本完全独立。历史原价缺失、未知日历或公司行动无法准确处理时，必须拒绝成交或明确降低报告可信度；不得声称接入了实时券商、真实下单或证明了获利能力。
