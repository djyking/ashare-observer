"""A-share calendar and ordinary-stock rules for an educational simulator.

Annual closure notices:
https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml
https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml
Weekends remain closed, including government make-up working weekends.
Special listings, risk-warning securities and corporate actions are not simulated.
"""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

SHANGHAI = timezone(timedelta(hours=8), "Asia/Shanghai")
CALENDAR_YEARS = frozenset((2025, 2026))
CALENDAR_SOURCE = "上海证券交易所 2025、2026 年休市通知；年度之外拒绝模拟"


def parse_date(value):
    if isinstance(value, datetime):
        raise ValueError("请提供 YYYY-MM-DD 日期，不要传入时间")
    if isinstance(value, date):
        return value
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("日期必须为 YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise ValueError("日期必须为 YYYY-MM-DD")
    return parsed


def _days(first, last):
    current, end = date.fromisoformat(first), date.fromisoformat(last)
    result = set()
    while current <= end:
        result.add(current)
        current += timedelta(days=1)
    return result


HOLIDAYS = frozenset().union(*(
    _days(first, last) for first, last in (
        ("2025-01-01", "2025-01-01"), ("2025-01-28", "2025-02-04"),
        ("2025-04-04", "2025-04-06"), ("2025-05-01", "2025-05-05"),
        ("2025-05-31", "2025-06-02"), ("2025-10-01", "2025-10-08"),
        ("2026-01-01", "2026-01-03"), ("2026-02-15", "2026-02-23"),
        ("2026-04-04", "2026-04-06"), ("2026-05-01", "2026-05-05"),
        ("2026-06-19", "2026-06-21"), ("2026-09-25", "2026-09-27"),
        ("2026-10-01", "2026-10-07"),
    )
))


def is_trading_day(date_str):
    day = parse_date(date_str)
    if day.year not in CALENDAR_YEARS:
        raise ValueError(f"{day.year} 年交易日历尚未核实，禁止模拟成交")
    return day.weekday() < 5 and day not in HOLIDAYS


def next_trading_day(date_str):
    day = parse_date(date_str)
    is_trading_day(day)
    for _ in range(370):
        day += timedelta(days=1)
        if is_trading_day(day):
            return day.isoformat()
    raise ValueError("找不到已核实的后续交易日")


def previous_trading_day(date_str):
    day = parse_date(date_str)
    is_trading_day(day)
    for _ in range(370):
        day -= timedelta(days=1)
        if is_trading_day(day):
            return day.isoformat()
    raise ValueError("找不到已核实的上一交易日")


def local_now(now=None):
    now = now or datetime.now(SHANGHAI)
    if not isinstance(now, datetime):
        raise ValueError("时间必须是 datetime")
    # Explicitly interpret naive input as Beijing time, never host-local time.
    return now.replace(tzinfo=SHANGHAI) if now.tzinfo is None else now.astimezone(SHANGHAI)


def last_closed_day(now=None):
    now = local_now(now)
    if is_trading_day(now.date()) and now.time() >= time(15, 5):
        return now.date().isoformat()
    return previous_trading_day(now.date())


def market_session(now=None):
    now = local_now(now)
    result = {"label": "交易日历待更新", "is_open": False, "calendar_known": False}
    if now.year not in CALENDAR_YEARS:
        return result
    result["calendar_known"] = True
    if not is_trading_day(now.date()):
        result["label"] = "休市日"
        return result
    minute = now.hour * 60 + now.minute
    if 555 <= minute < 560:
        label, opened = "开盘集合竞价（可撤单）", True
    elif 560 <= minute < 565:
        label, opened = "开盘集合竞价（不可撤单）", True
    elif 565 <= minute < 570:
        label, opened = "开盘竞价结束，等待连续竞价", False
    elif 570 <= minute < 690:
        label, opened = "上午连续竞价", True
    elif 690 <= minute < 780:
        label, opened = "午间休市", False
    elif 780 <= minute < 897:
        label, opened = "下午连续竞价", True
    elif 897 <= minute < 900:
        label, opened = "收盘集合竞价（不可撤单）", True
    elif 900 <= minute < 905:
        label, opened = "已收盘，等待日线入库", False
    elif 905 <= minute < 930:
        label, opened = "盘后固定价格阶段（本模拟不支持）", False
    elif minute >= 930:
        label, opened = "已收盘", False
    else:
        label, opened = "盘前", False
    result.update(label=label, is_open=opened)
    return result


def decimal_number(value, label="数值", positive=False):
    if isinstance(value, bool):
        raise ValueError(f"{label}必须是有限数值")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label}必须是有限数值") from None
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(f"{label}必须是{'正' if positive else '有限'}数值")
    return result


def quantity_value(value):
    number = decimal_number(value, "股数", positive=True)
    if number != number.to_integral_value():
        raise ValueError("股数必须为正整数")
    if number > 1000000:
        raise ValueError("单笔模拟申报最多 100 万股")
    return int(number)


def validate_quantity(board, side, quantity, available=None):
    quantity = quantity_value(quantity)
    if board not in ("main", "growth", "star", "beijing"):
        raise ValueError("未知上市板块，无法验证数量规则")
    if side not in ("buy", "sell"):
        raise ValueError("方向必须为 buy 或 sell")
    if board == "star" and quantity > 100000:
        raise ValueError("科创板单笔模拟限价申报最多 10 万股")
    minimum = 200 if board == "star" else 100
    if side == "buy":
        if quantity < minimum or (board in ("main", "growth") and quantity % 100):
            raise ValueError("科创板买入至少 200 股；北交所至少 100 股；主板/创业板须为 100 股整数倍")
    else:
        if available is None or quantity > available:
            raise ValueError("可卖股份不足（包括 T+1 或已冻结的股份）")
        if board in ("main", "growth"):
            # Odd-lot remainder may be sold alone or with full lots, but not split.
            if quantity % 100 and quantity % 100 != available % 100:
                raise ValueError("不足 100 股的零股部分必须一次性卖出，不可拆分")
        elif quantity < minimum and quantity != available:
            raise ValueError(f"不足 {minimum} 股的余额须一次性全部卖出")
    return quantity


def limit_prices(previous_close, board):
    ratios = {"main": Decimal("0.10"), "growth": Decimal("0.20"),
              "star": Decimal("0.20"), "beijing": Decimal("0.30")}
    if board not in ratios:
        raise ValueError("未知板块涨跌幅规则")
    price = decimal_number(previous_close, "前收盘原价", positive=True)
    tick = Decimal("0.01")
    upper = (price * (1 + ratios[board])).quantize(tick, rounding=ROUND_HALF_UP)
    lower = (price * (1 - ratios[board])).quantize(tick, rounding=ROUND_HALF_UP)
    return max(upper, price + tick), max(tick, min(lower, price - tick))


def ensure_ordinary_stock(stock, trade_date):
    day = parse_date(trade_date)
    if not is_trading_day(day):
        raise ValueError("当日不是交易日")
    if stock.get("mode") != "demo":
        raise ValueError("模拟账本仅接受离线演示行情；真实行情和 CSV 只供研究")
    if stock.get("metadata_verified") is not True:
        raise ValueError("股票交易元数据尚未核实")
    if stock.get("risk_warning") is not False or "ST" in str(stock.get("name", "")).upper():
        raise ValueError("风险警示股票仅供观察，不进行模拟交易")
    if stock.get("board") not in ("main", "growth", "star", "beijing"):
        raise ValueError("未知上市板块")
    if not stock.get("listing_date"):
        raise ValueError("上市日期未知，无法排除新股特殊交易规则")
    listed = parse_date(stock["listing_date"])
    if listed > day:
        raise ValueError("尚未上市")
    # Old listings need no calendar beyond supported years. Recent listings do.
    if (day - listed).days <= 40:
        sessions, cursor = 0, listed
        while cursor <= day:
            sessions += int(is_trading_day(cursor))
            cursor += timedelta(days=1)
        excluded = 1 if stock["board"] == "beijing" else 5
        if sessions <= excluded:
            raise ValueError("新股无涨跌幅限制阶段不在当前模拟范围")
    if stock.get("corporate_action_pending"):
        raise ValueError("除权除息或股份变动待处理，暂停模拟")


def valid_raw_candles(stock):
    candles = stock.get("raw_candles")
    if not isinstance(candles, list) or not candles:
        raise ValueError("缺少不复权原价，禁止以复权价格模拟成交")
    result = {}
    for candle in candles:
        try:
            day = parse_date(candle["date"]).isoformat()
            if day in result:
                raise ValueError("不复权日线存在重复日期")
            values = {key: decimal_number(candle[key], key, positive=True)
                      for key in ("open", "high", "low", "close")}
            if values["low"] > min(values["open"], values["close"]) or values["high"] < max(values["open"], values["close"]):
                raise ValueError("不复权日线 OHLC 不一致")
            volume = decimal_number(candle.get("volume", 0), "成交量")
            if volume < 0:
                raise ValueError("成交量不可为负")
            result[day] = {**values, "date": day, "volume": volume}
        except (KeyError, TypeError):
            raise ValueError("不复权日线字段缺失") from None
    return result
