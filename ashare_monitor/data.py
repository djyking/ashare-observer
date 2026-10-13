"""Read-only daily A-share data adapters and deterministic offline examples."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DEFAULT_WATCHLIST = ["600519", "601318", "600036", "000333", "000651", "002594", "300750", "688981"]
_EXAMPLES = {
    "600519": ("贵州茅台", "消费", "2001-08-27", 1380.0),
    "601318": ("中国平安", "金融", "2007-03-01", 47.0),
    "600036": ("招商银行", "银行", "2002-04-09", 34.0),
    "000333": ("美的集团", "家电", "2013-09-18", 68.0),
    "000651": ("格力电器", "家电", "1996-11-18", 37.0),
    "002594": ("比亚迪", "汽车", "2011-06-30", 92.0),
    "300750": ("宁德时代", "电池", "2018-06-11", 205.0),
    "688981": ("中芯国际", "半导体", "2020-07-16", 67.0),
}
_CODE = re.compile(r"^[0-9]{6}$")
_DEMO_START = date(2025, 1, 2)


def _parse_date(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("日期必须使用 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日期无效") from exc


def security_info(code: str) -> dict:
    """Code prefixes classify ordinary shares, never account permissions."""
    if not isinstance(code, str) or not _CODE.fullmatch(code):
        raise ValueError("股票代码必须是六位数字字符串")
    if code.startswith(("600", "601", "603", "605")):
        exchange, board = "SSE", "main"
    elif code.startswith("688"):
        exchange, board = "SSE", "star"
    elif code.startswith(("000", "001", "002", "003")):
        exchange, board = "SZSE", "main"
    elif code.startswith(("300", "301")):
        exchange, board = "SZSE", "growth"
    elif code.startswith(("43", "83", "87", "92")):
        exchange, board = "BSE", "beijing"
    else:
        raise ValueError("代码不在支持的普通 A 股范围")
    example = _EXAMPLES.get(code)
    return {
        "code": code, "name": example[0] if example else code,
        "exchange": exchange, "board": board,
        "sector": example[1] if example else "未分类",
        "status": "unavailable", "error": None, "data_date": None,
        "candles": [], "raw_candles": [], "adjustment": "none",
        "risk_warning": None, "listing_date": None, "metadata_verified": False,
    }


def validate_candles(rows: list[dict], as_of: str | None = None) -> list[dict]:
    """Reject malformed input; validate closures only in verified calendar years.

    Older history is retained for research; adapters disclose unverified years
    separately and simulation continues to reject those calendar years.
    """
    from .rules import CALENDAR_YEARS, is_trading_day
    if not isinstance(rows, list):
        raise ValueError("日线必须是记录列表")
    limit = _parse_date(as_of) if as_of is not None else None
    result, previous = [], None
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("日线记录结构错误")
        current = _parse_date(row.get("date"))
        if previous is not None and current <= previous:
            raise ValueError("日线日期必须升序且不得重复")
        previous = current
        if limit is not None and current > limit:
            raise ValueError("日线包含观察日期之后的数据")
        if current.weekday() >= 5:
            raise ValueError("普通 A 股日线不能是周末日期")
        if current.year in CALENDAR_YEARS and not is_trading_day(current):
            raise ValueError(f"{current.isoformat()} 是已核实的交易所休市日，不能包含普通 A 股日线")
        parsed = {"date": current.isoformat()}
        for field in ("open", "high", "low", "close", "volume", "amount"):
            try:
                if isinstance(row.get(field), bool):
                    raise ValueError("布尔值不是行情数字")
                value = float(row.get(field, 0) if field == "amount" else row[field])
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"日线字段 {field} 缺失或无效") from exc
            if not math.isfinite(value):
                raise ValueError(f"日线字段 {field} 不得为非有限数")
            if field in ("volume", "amount"):
                if value < 0:
                    raise ValueError(f"日线字段 {field} 不得小于零")
            elif value <= 0:
                raise ValueError("日线价格必须大于零")
            parsed[field] = value
        if parsed["high"] < max(parsed["open"], parsed["close"], parsed["low"]):
            raise ValueError("最高价小于开盘、收盘或最低价")
        if parsed["low"] > min(parsed["open"], parsed["close"], parsed["high"]):
            raise ValueError("最低价大于开盘、收盘或最高价")
        result.append(parsed)
    return result


def _demo_stock(code: str, as_of: str) -> dict:
    from .rules import is_trading_day

    stock = security_info(code)
    end = _parse_date(as_of)
    known = code in _EXAMPLES
    stock.update(mode="demo", source="离线合成行情（非真实价格）", metadata_verified=known,
                 risk_warning=False if known else None, listing_date=_EXAMPLES[code][2] if known else None)
    # Stable per-symbol RNG and fixed start: advancing a day never rewrites history.
    seed = int.from_bytes(hashlib.sha256(("ashare-demo-v1:" + code).encode()).digest()[:8], "big")
    rng = random.Random(seed)
    price = _EXAMPLES.get(code, (None, None, None, 20.0 + seed % 7000 / 100))[3]
    rows, day, index = [], _DEMO_START, 0
    while day <= end:
        if is_trading_day(day.isoformat()):
            cycle = math.sin(index / 27 + seed % 17) * 0.003
            overnight = rng.uniform(-0.009, 0.009)
            open_price = max(0.1, round(price * (1 + overnight), 2))
            close_price = max(0.1, round(open_price * (1 + cycle + rng.uniform(-0.018, 0.019)), 2))
            high_price = round(max(open_price, close_price) * (1 + rng.uniform(0.001, 0.012)), 2)
            low_price = max(0.01, round(min(open_price, close_price) * (1 - rng.uniform(0.001, 0.012)), 2))
            volume = (18000 + rng.randrange(190000)) * 100
            typical = (open_price + high_price + low_price + close_price) / 4
            rows.append({"date": day.isoformat(), "open": open_price, "high": high_price,
                         "low": low_price, "close": close_price, "volume": volume,
                         "amount": round(typical * volume, 2)})
            price, index = close_price, index + 1
        day += timedelta(days=1)
    stock["candles"] = validate_candles(rows, as_of)
    stock["raw_candles"] = [dict(row) for row in stock["candles"]]
    stock["status"] = "ok" if rows else "unavailable"
    stock["data_date"] = rows[-1]["date"] if rows else None
    stock["error"] = None if rows else "观察日期早于演示数据起点"
    stock["limitations"] = ["价格由固定随机种子生成，不对应该公司的历史走势", "不能用演示盈亏验证策略收益"]
    return stock


def _request_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "AshareObservation/1.0", "Accept": "application/json"})
    # One bounded attempt per series; retry is a user-triggered refresh.
    with urlopen(request, timeout=6) as response:
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("行情响应过大")
    result = json.loads(payload.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("行情响应结构错误")
    return result


def _eastmoney_series(code: str, as_of: str, adjustment: int) -> tuple[list[dict], str]:
    stock = security_info(code)
    if stock["exchange"] == "BSE":
        raise ValueError("当前在线适配器仅覆盖沪深普通 A 股，北交所请使用 CSV")
    params = {"secid": ("1." if stock["exchange"] == "SSE" else "0.") + code,
              "klt": 101, "fqt": adjustment, "beg": "20240101", "end": as_of.replace("-", ""),
              "lmt": 420, "fields1": "f1,f2,f3,f4,f5,f6", "fields2": "f51,f52,f53,f54,f55,f56,f57"}
    response = _request_json("https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urlencode(params))
    data = response.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("klines"), list) or not data["klines"]:
        raise ValueError("数据源未返回日线，可能为停牌、代码无效或接口不可用")
    if data.get("code") and str(data["code"]) != code:
        raise ValueError("返回的股票代码不匹配")
    rows = []
    for record in data["klines"]:
        if not isinstance(record, str):
            raise ValueError("日线记录格式无效")
        values = record.split(",")
        if len(values) < 7:
            raise ValueError("日线字段不完整")
        rows.append({"date": values[0], "open": values[1], "close": values[2], "high": values[3],
                     "low": values[4], "volume": float(values[5]) * 100, "amount": values[6]})
    return validate_candles(rows, as_of), str(data.get("name") or code)


def _eastmoney_stock(code: str, as_of: str) -> dict:
    stock = security_info(code)
    stock.update(mode="eastmoney", source="东方财富公开日线", adjustment="qfq")
    adjusted, name = _eastmoney_series(code, as_of, 1)
    stock.update(candles=adjusted, name=name, data_date=adjusted[-1]["date"], status="ok")
    try:
        raw, raw_name = _eastmoney_series(code, as_of, 0)
        if [r["date"] for r in raw] != [r["date"] for r in adjusted]:
            raise ValueError("复权与原价日线日期不一致")
        stock["raw_candles"] = raw
    except Exception as exc:
        stock["raw_candles"] = []
        stock["error"] = f"原价数据不可用：{_public_error(exc)}；仅显示复权指标，不生成原价情景"
    stock["risk_warning"] = True if "ST" in name.upper() or "退" in name else None
    stock["limitations"] = ["前复权价格用于指标，不是历史实际成交价", "复权因子可能随公司行为重算，不代表历史时点可获知的数据版本",
                             "上市日期与风险标识未完成独立核验；在线行情仅供只读研究"]
    return stock


def _csv_stock(code: str, as_of: str, csv_dir: str | Path | None) -> dict:
    stock = security_info(code)
    stock.update(mode="csv", source="本地 CSV（用户提供）")
    if csv_dir is None:
        raise ValueError("尚未配置固定 CSV 目录")
    root = Path(csv_dir).resolve()
    path = (root / (code + ".csv")).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"固定 CSV 目录中不存在 {code}.csv，或文件链接指向目录外")
    if path.stat().st_size > 5_000_000:
        raise ValueError("单股 CSV 不得超过 5 MB")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"date", "open", "high", "low", "close", "volume"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError("CSV 缺少必需列：date,open,high,low,close,volume")
        original = list(reader)
    if not original:
        raise ValueError("CSV 没有日线记录")
    adjustments = {(r.get("adjustment") or "none").strip().lower() for r in original}
    if len(adjustments) != 1 or not adjustments.issubset({"none", "qfq"}):
        raise ValueError("CSV adjustment 必须统一为 none 或 qfq")
    stock["adjustment"] = adjustments.pop()
    # Validate entire file before filtering, so malformed future rows cannot hide.
    rows = validate_candles([{**r, "amount": r.get("amount") or 0} for r in original])
    stock["candles"] = [r for r in rows if r["date"] <= as_of]
    if not stock["candles"]:
        raise ValueError("CSV 在观察日期之前没有日线")
    declared = all(bool(r.get("adjustment")) for r in original)
    stock["adjustment_verified"] = declared
    if stock["adjustment"] == "none" and declared:
        stock["raw_candles"] = [dict(r) for r in stock["candles"]]
    elif stock["adjustment"] == "qfq" and all(all(r.get("raw_" + f) for f in ("open", "high", "low", "close")) for r in original):
        raw = validate_candles([{**r, **{f: source["raw_" + f] for f in ("open", "high", "low", "close")}}
                                for r, source in zip(rows, original)])
        stock["raw_candles"] = [r for r in raw if r["date"] <= as_of]
    stock.update(status="ok", data_date=stock["candles"][-1]["date"])
    stock["limitations"] = ["CSV 的价格和复权口径由文件提供者负责核实", "未声明复权口径时标记 none（未知），不把它当成可靠原价"]
    return stock


def _public_error(exc: Exception) -> str:
    if isinstance(exc, ValueError):
        return str(exc)[:220]
    if isinstance(exc, (TimeoutError, OSError)):
        return "网络连接、数据源响应或文件读取失败，请稍后重试"
    return f"数据读取失败（{type(exc).__name__}）"


def load_market(mode: str, codes: list[str], as_of: str, csv_dir: str | Path | None = None) -> dict:
    """Load closed daily bars. No online failure ever falls back to examples."""
    if mode not in {"demo", "eastmoney", "csv"}:
        raise ValueError("不支持的数据模式")
    _parse_date(as_of)
    if not isinstance(codes, (list, tuple)) or not codes or len(codes) > 100:
        raise ValueError("观察列表需要 1 至 100 个股票代码")
    if len(set(codes)) != len(codes):
        raise ValueError("观察列表股票代码不得重复")
    for code in codes:
        security_info(code)
    if mode != "demo":
        from .rules import last_closed_day
        if as_of > last_closed_day():
            raise ValueError("真实与 CSV 模式只读取已收盘日线，不读取未来或未完成交易日")

    def read(code: str) -> dict:
        try:
            if mode == "demo":
                stock = _demo_stock(code, as_of)
            elif mode == "eastmoney":
                stock = _eastmoney_stock(code, as_of)
            else:
                stock = _csv_stock(code, as_of, csv_dir)
        except Exception as exc:
            stock = security_info(code)
            stock.update(mode=mode, error=_public_error(exc))
        stock["as_of"] = as_of
        from .rules import CALENDAR_YEARS
        unverified_years = sorted({int(row["date"][:4]) for row in stock.get("candles", [])} - CALENDAR_YEARS)
        stock["calendar_verified"] = not unverified_years
        stock["calendar_unverified_years"] = unverified_years
        if unverified_years:
            stock.setdefault("limitations", []).append(
                "以下年份交易日历未核实，只检查周末与行情格式，不能用于当前模拟撮合：" +
                "、".join(map(str, unverified_years)))
        stock["stale"] = bool(stock.get("data_date") and stock["data_date"] < as_of)
        stock["stale_as_of"] = as_of if stock["stale"] else None
        if stock["stale"]:
            warning = (f"最近日线为 {stock['data_date']}，落后于观察日 {as_of}；"
                       "可能停牌或数据源延迟，仅供历史研究，不形成当前观察机会")
            stock["error"] = "; ".join(filter(None, [stock.get("error"), warning]))
        return stock

    if mode == "eastmoney":
        with ThreadPoolExecutor(max_workers=4) as pool:
            stocks = list(pool.map(read, codes))
    else:
        stocks = [read(code) for code in codes]
    source = {"demo": "离线合成行情（非真实价格）", "eastmoney": "东方财富公开日线（只读）", "csv": "本地 CSV（只读）"}[mode]
    return {"mode": mode, "source": source,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "as_of": as_of,
            "stocks": stocks, "errors": [{"code": s["code"], "error": s["error"]} for s in stocks if s.get("error")]}
