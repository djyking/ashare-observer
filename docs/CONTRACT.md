# A 股观察台：模块契约

独立 Python 3.12 项目，仅使用标准库。入口 `python -m ashare_monitor --port 18766`，默认离线演示，不连接证券账户。

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

所有POST要求 `X-CSRF-Token`，从state读取。固定loopback访问，Origin/Host检查；无真实下单路由。前端不得并发刷新覆写较新的快照。统一错误 `{error}`。

页面有概览/观察列表、单股K线与指标、模拟持仓/委托/成交、研究历史分页、设置与规则说明。演示数据与真实行情显著区分，红涨绿跌。筛选排序不能扰乱输入编辑。
