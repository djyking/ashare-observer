# A 股量化交易研究平台：模块契约

Python 3.12 后端仅使用标准库，前端使用 Vue 3、TypeScript 和 Vite。入口 `python -m ashare_monitor --port 18766`，默认离线演示，未连接证券账户。前端源码位于 `frontend/`，生产资源位于 `ashare_monitor/web/`，由同一个 Python 服务提供。

## 数据

`data.py`: `DEFAULT_WATCHLIST` 为代码列表；`load_market(mode, codes, as_of, csv_dir=None)` 返回 `{mode,source,fetched_at,as_of,stocks,errors}`。mode 为 `demo/eastmoney/csv`。as_of 是 YYYY-MM-DD，仅包含已收盘日线；真实模式不得以演示数据填充失败。

股票结构 `{code,name,exchange,board,sector,status,error,data_date,candles,raw_candles,adjustment,risk_warning,listing_date,metadata_verified}`。board 为 `main/growth/star/beijing`。candles 为分析日线（真实模式前复权），raw_candles 为同日期不复权日线；演示模式均为 none。日线 `{date,open,high,low,close,volume,amount}`，金额人民币元、数量股。无可靠不复权数据不得模拟成交。需验证日期、价格、非有限数、重复、OHLC及成交量。listing_date 未知则 None，禁止据此断言非新股。

`analysis.py`: `analyze_stock(stock)` 返回 `{code,name,score,status,route,reasons,indicators,plan,history}`，status 为 `watch/wait/insufficient/unavailable`，不是买入授权或盈利概率。plan 可空，否则 `{reference_price,stop_price,target_price,expected_gain_pct,risk_pct}` 必须明确仅研究情景，真实qfq不能作为当前可成交原价。history 可列观察信号；先不做真实账户或宣称获利。指标使用闭合日线。

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

页面有概览/观察列表、单股K线与指标、模拟持仓/委托/成交、研究历史分页、设置与规则说明。演示数据与真实行情显著区分，红涨绿跌。筛选排序不能扰乱输入编辑。
