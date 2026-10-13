"""Deterministic daily-bar research replay, separate from every account ledger.

Signals consume a candle prefix at the close. The resulting DAY instruction is
tried once at the next exchange session's open, never at the signal close.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import math

from .analysis import _at, _series
from .data import validate_candles
from .rules import is_trading_day, limit_prices, parse_date, previous_trading_day, validate_quantity
from .strategies import STRATEGY_VERSION, evaluate_strategies, normalize_strategy_config

RESEARCH_VERSION = "daily-replay-v1"
DEFAULT_RESEARCH_CONFIG = {
    "start_date": "", "end_date": "", "initial_cash": 100000, "max_positions": 3,
    "position_pct": 30, "commission_rate": 0.0003, "minimum_commission": 5,
    "stamp_tax_rate": 0.0005, "slippage_bps": 5, "strategy_id": "teaching",
    "stop_loss_pct": 5, "take_profit_pct": 10, "max_holding_days": 20,
}
_BOUNDS = {
    "initial_cash": (100, 100000000), "max_positions": (1, 50), "position_pct": (1, 100),
    "commission_rate": (0, 0.02), "minimum_commission": (0, 100), "stamp_tax_rate": (0, 0.02),
    "slippage_bps": (0, 200), "stop_loss_pct": (0.1, 50), "take_profit_pct": (0.1, 100),
    "max_holding_days": (1, 250),
}
ASSUMPTIONS = [
    "这是日线历史回放，不连接券商，不改动演示账本，不代表未来收益；合成行情只能验证操作流程。",
    "每天收盘生成信号，下一交易日开盘尝试一次；未成交 DAY 指令失效，后续收盘条件仍满足时可再次形成新指令。",
    "止损、目标和到期退出均按收盘确认、下一开盘执行；没有假设盘中碰价即成交，跳空可能扩大损失。",
    "执行使用不复权原价，指标使用来源指定日线。前复权数据可能事后重算，不是历史时点数据，不能视作无偏绩效。",
    "按普通股票板块数量、T+1、已知 2025～2026 年交易日历与涨跌幅规则回放；ST、退市风险和已知公司行动排除。",
    "上市与历年风险标记未独立核实时，仅假设成熟普通股；至少 60 根预热日线，不适用于新股、重新上市、特殊涨跌幅阶段。",
    "当前观察股票池存在幸存者和选择偏差，未纳入退市股票、完整历史股票池；没有处理现金分红、送配股、股本变化。",
    "报价越过当日价格区间、开盘触及买入涨停或卖出跌停、无量及缺数据时拒绝成交；缺盘口，开盘排队与真实流动性仍不可重现。",
    "委托数量按前一交易日成交量的 1% 控制；成交后再用当日成交量的 1% 作保守成交检查，检查不通过整笔拒绝，不用未来成交量调整委托数量。",
    "费用含配置的双边佣金及卖出印花税，未单列过户费；滑点作用于开盘成交价。参数不是券商报价，请按实际费率校正。",
    "区间结束不强制平仓，未实现盈亏按最后可用原价估值；缺价会陈旧估值并警示，卖出尚未发生的费用不计入。",
    "基准是起始日等权买入后持有至结束，使用同样整手、费用、滑点与成交约束；无法买入的份额留现金，不做再平衡。",
]


def normalize_research_config(config=None) -> dict:
    if config is None:
        config = {}
    if not isinstance(config, dict) or set(config) - (set(DEFAULT_RESEARCH_CONFIG) | {"strategies"}):
        raise ValueError("历史回放配置包含未知字段")
    result = {**DEFAULT_RESEARCH_CONFIG, **deepcopy(config)}
    for key, (low, high) in _BOUNDS.items():
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} 必须在 {low}～{high} 之间")
        if key in ("max_positions", "max_holding_days") and int(value) != value:
            raise ValueError(f"{key} 必须是整数")
    for key in ("start_date", "end_date"):
        if result[key]:
            parsed = parse_date(result[key])
            is_trading_day(parsed)  # A holiday boundary is allowed, an unknown year is not.
            result[key] = parsed.isoformat()
        elif result[key] != "":
            raise ValueError(f"{key} 必须为日期或空字符串")
    if result["start_date"] and result["end_date"] and result["start_date"] > result["end_date"]:
        raise ValueError("开始日期不能晚于结束日期")
    result["strategies"] = normalize_strategy_config(result.get("strategies"))
    if not isinstance(result["strategy_id"], str) or result["strategy_id"] not in result["strategies"]:
        raise ValueError("未知回放策略")
    if not result["strategies"][result["strategy_id"]]["enabled"]:
        raise ValueError("回放策略处于关闭状态，请先启用该策略")
    return result


def _money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _fee(notional, side, config):
    return _money(max(config["minimum_commission"], notional * config["commission_rate"]) +
                  (notional * config["stamp_tax_rate"] if side == "sell" else 0))


def _buy_quantity(budget, price, board, config, volume):
    minimum, step = (200, 1) if board == "star" else ((100, 1) if board == "beijing" else (100, 100))
    # Start from the gross affordable quantity, then apply the actual fee model.
    # Subtracting the minimum and also dividing by (1 + rate) double counts fees
    # when the minimum dominates, rejecting an exactly affordable board lot.
    quantity = min(int(max(0, budget) / price),
                   int(volume * 0.01), 100000 if board == "star" else 1000000)
    quantity = quantity // step * step
    while quantity >= minimum and quantity * price + _fee(quantity * price, "buy", config) > budget + 0.00001:
        quantity -= step
    return quantity if quantity >= minimum else 0


def _execution(stock, day, side, config):
    row = stock["raw_map"].get(day)
    if row is None:
        return None, "下一交易日缺少原价日线，不能跨过缺失日自动成交"
    if row["volume"] <= 0:
        return None, "无成交量或停牌"
    try:
        previous = stock["raw_map"].get(previous_trading_day(day))
    except ValueError:
        return None, "上一交易日日历尚未核实，无法验证前收原价"
    if previous is None:
        return None, "缺少上一交易日前收原价，无法检查涨跌幅"
    upper, lower = map(float, limit_prices(previous["close"], stock["board"]))
    if row["open"] > upper + 0.011 or row["open"] < lower - 0.011:
        return None, "原价跳变超过普通板块范围，可能公司行动或特殊交易规则"
    if side == "buy" and row["open"] >= upper - 0.0001:
        return None, "开盘涨停，无法确定买单可成交"
    if side == "sell" and row["open"] <= lower + 0.0001:
        return None, "开盘跌停，无法确定卖单可成交"
    price = _money(row["open"] * (1 + config["slippage_bps"] / 10000 * (1 if side == "buy" else -1)))
    if not lower <= price <= upper or not row["low"] - 0.0001 <= price <= row["high"] + 0.0001:
        return None, "含滑点成交价越过日线区间或涨跌幅边界"
    return price, None


def run_research(stocks: list[dict], config: dict | None = None) -> dict:
    config = normalize_research_config(config)
    if not isinstance(stocks, list) or not stocks or len(stocks) > 50:
        raise ValueError("历史回放需提供 1～50 只股票的数据")
    warnings, excluded, prepared = [], [], []
    seen = set()
    for original in stocks:
        if not isinstance(original, dict):
            raise ValueError("每只股票的数据必须是对象")
        code, name = original.get("code"), original.get("name", "")
        if not isinstance(code, str) or code in seen:
            raise ValueError("股票代码缺失或重复")
        seen.add(code)
        try:
            if original.get("status") != "ok":
                raise ValueError("没有有效行情")
            if original.get("risk_warning") is True or "ST" in str(name).upper() or "退" in str(name):
                raise ValueError("风险警示或退市风险股票不在普通规则回放范围")
            if original.get("board") not in ("main", "growth", "star", "beijing"):
                raise ValueError("上市板块未知")
            if original.get("corporate_action_pending"):
                raise ValueError("存在待处理公司行动，不能准确计算持仓权益")
            # Out-of-window future data do not influence eligibility or fingerprint.
            end = config["end_date"]
            candles = validate_candles([row for row in original.get("candles", []) if not end or row.get("date", "") <= end])
            raw = validate_candles([row for row in original.get("raw_candles", []) if not end or row.get("date", "") <= end])
            if original.get("listing_date") is not None:
                listing_date = parse_date(original["listing_date"]).isoformat()
                if any(row["date"] < listing_date for row in candles + raw):
                    raise ValueError(f"行情包含已知上市日期 {listing_date} 之前的数据，不能用上市前行情预热或模拟成交")
            if len(candles) < 60:
                raise ValueError("不足 60 根日线预热")
            if not raw:
                raise ValueError("缺少可靠原价日线，不能用复权价冒充成交价")
            entry = {**original, "candles": candles, "raw_candles": raw, "raw_map": {row["date"]: row for row in raw},
                     "by_date": {row["date"]: i for i, row in enumerate(candles)}, "series": _series(candles)}
            prepared.append(entry)
            if original.get("metadata_verified") is not True:
                warnings.append(f"{code}：上市与历史风险标记未独立核实，按普通成熟股票研究假设回放。")
            if original.get("mode") == "demo":
                warnings.append(f"{code}：使用合成演示数据，盈亏不具备策略有效性证据。")
        except (ValueError, TypeError, KeyError) as exc:
            excluded.append({"code": code, "name": name, "reason": str(exc)})
    if not prepared:
        raise ValueError("没有可回放的股票：" + "；".join(f"{item['code']} {item['reason']}" for item in excluded))
    start = config["start_date"] or max("2025-01-02", min(stock["candles"][59]["date"] for stock in prepared))
    end = config["end_date"] or max(stock["candles"][-1]["date"] for stock in prepared)
    config.update(start_date=start, end_date=end)
    normalize_research_config(config)
    days, cursor, finish = [], parse_date(start), parse_date(end)
    while cursor <= finish:
        if is_trading_day(cursor):
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    if not days or not any(any(start <= row["date"] <= end for row in stock["candles"][59:]) for stock in prepared):
        raise ValueError("区间内没有完成 60 根预热的可观察日线")
    for stock in prepared:
        first_observable, last_observable = stock["candles"][59]["date"], stock["candles"][-1]["date"]
        if first_observable > days[0]:
            warnings.append(f"{stock['code']}：请求开始日早于完成预热的 {first_observable}，此前保留现金，不产生策略信号；不代表全区间有效覆盖。")
        if last_observable < days[-1]:
            warnings.append(f"{stock['code']}：数据截至 {last_observable}，早于请求结束日；后续不产生信号，持仓只作陈旧估值。")
    fingerprint_payload = [{"code": stock["code"], "mode": stock.get("mode"), "board": stock["board"],
                            "adjustment": stock.get("adjustment"), "candles": stock["candles"], "raw_candles": stock["raw_candles"]}
                           for stock in sorted(prepared, key=lambda item: item["code"])]
    fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    lookup = {stock["code"]: stock for stock in prepared}
    cash = float(config["initial_cash"])
    positions, trades, rejections, signals, pending, curve = {}, [], [], [], [], []
    benchmark_positions, benchmark_cash = {}, cash
    peak = cash
    last_prices, blocked, stale_dates = {}, set(), set()
    last_ratios = {}
    for stock in prepared:
        for row in reversed(stock["candles"]):
            raw = stock["raw_map"].get(row["date"])
            if row["date"] < start and raw:
                last_ratios[stock["code"]] = row["close"] / raw["close"]
                break
    for day_index, day in enumerate(days):
        todays, pending = pending, []
        # Close positions before trying entries, deterministic score/code priority.
        for order in sorted(todays, key=lambda item: (item["side"] != "sell", -item.get("score", 0), item["code"])):
            code, side = order["code"], order["side"]
            stock = lookup[code]
            reason = None
            if code in blocked:
                reason = "疑似公司行动未处理，暂停该证券回放成交"
                price = None
            else:
                price, reason = _execution(stock, day, side, config)
            quantity, realized = 0, None
            if reason is None and side == "sell":
                position = positions.get(code)
                if position is None:
                    reason = "仓位已不存在"
                elif position["entry_date"] >= day:
                    reason = "T+1：买入当日不可卖出"
                elif position["quantity"] > stock["raw_map"][day]["volume"] * 0.01:
                    reason = "卖出数量超过日成交量 1%，无法近似成交"
                else:
                    quantity = position["quantity"]
                    validate_quantity(stock["board"], "sell", quantity, quantity)
                    notional = _money(quantity * price)
                    fee = _fee(notional, side, config)
                    realized = _money(notional - fee - position["cost_basis"])
                    cash = _money(cash + notional - fee)
                    del positions[code]
            elif reason is None:
                if code in positions:
                    reason = "已有同一股票仓位"
                elif len(positions) >= config["max_positions"]:
                    reason = "达到同时持仓上限"
                else:
                    # Position sizing uses last known close, never today's close.
                    prior_equity = cash + sum(p["quantity"] * last_prices.get(c, p["entry_price"]) for c, p in positions.items())
                    budget = min(cash, prior_equity * config["position_pct"] / 100)
                    quantity = _buy_quantity(budget, price, stock["board"], config, stock["raw_map"][previous_trading_day(day)]["volume"])
                    if not quantity:
                        reason = "可用资金或流动性不足以买入最低股数并支付费用"
                    elif quantity > stock["raw_map"][day]["volume"] * 0.01:
                        reason = "委托超过实际日成交量 1%，事后流动性检查不通过，整笔拒绝"
                    else:
                        validate_quantity(stock["board"], "buy", quantity)
                        notional = _money(quantity * price)
                        fee = _fee(notional, side, config)
                        cash = _money(cash - notional - fee)
                        positions[code] = {"code": code, "name": stock.get("name", code), "quantity": quantity,
                                           "entry_date": day, "entry_price": price, "entry_index": day_index,
                                           "cost_basis": _money(notional + fee)}
            if reason:
                rejections.append({"date": day, "signal_date": order["signal_date"], "code": code, "side": side, "reason": reason})
            else:
                trades.append({"date": day, "signal_date": order["signal_date"], "code": code, "name": stock.get("name", code),
                               "side": side, "quantity": quantity, "price": price, "notional": notional, "fee": fee,
                               "reason": order["reason"], "realized_pnl": realized})
        if day_index == 0:
            allocation = config["initial_cash"] / len(prepared)
            for stock in prepared:
                price, reason = _execution(stock, day, "buy", config)
                if reason:
                    warnings.append(f"基准 {stock['code']} 起始日未成交：{reason}；其份额留现金。")
                    continue
                quantity = _buy_quantity(min(allocation, benchmark_cash), price, stock["board"], config, stock["raw_map"][previous_trading_day(day)]["volume"])
                if quantity > stock["raw_map"][day]["volume"] * 0.01:
                    warnings.append(f"基准 {stock['code']} 起始日未成交：当日流动性检查不通过；其份额留现金。")
                    continue
                if quantity:
                    benchmark_cash = _money(benchmark_cash - quantity * price - _fee(quantity * price, "buy", config))
                    benchmark_positions[stock["code"]] = {"quantity": quantity, "entry_price": price}
        for stock in prepared:
            code, raw = stock["code"], stock["raw_map"].get(day)
            if raw:
                last_prices[code] = raw["close"]
            elif code in positions or code in benchmark_positions:
                stale_dates.add((day, code))
            index = stock["by_date"].get(day)
            # Adjustment ratios are observed at this close, after today's open orders.
            if index is not None and raw:
                ratio = stock["candles"][index]["close"] / raw["close"]
                previous_ratio = last_ratios.get(code)
                if previous_ratio is not None and abs(ratio / previous_ratio - 1) > 0.002:
                    blocked.add(code)
                    warnings.append(f"{day} {code}：复权比例发生变化，疑似公司行动；从收盘起停止新增成交，持有权益可能失真，结果不可作为有效业绩。")
                last_ratios[code] = ratio
            if code in blocked or raw is None:
                continue
            if code in positions:
                position = positions[code]
                move = (raw["close"] / position["entry_price"] - 1) * 100
                reason = ("收盘止损" if move <= -config["stop_loss_pct"] else
                          "收盘目标达到" if move >= config["take_profit_pct"] else
                          "最长持仓交易日数达到" if day_index - position["entry_index"] + 1 >= config["max_holding_days"] else None)
                if reason:
                    pending.append({"code": code, "side": "sell", "signal_date": day, "reason": reason})
            elif index is not None and index >= 59:
                values, score, _, _, _ = _at(stock["candles"], stock["series"], index)
                evaluation = next(item for item in evaluate_strategies(stock["candles"], values, score, index, config["strategies"]) if item["id"] == config["strategy_id"])
                if evaluation["matched"]:
                    signals.append({"date": day, "code": code, "strategy_id": config["strategy_id"], "score": score})
                    pending.append({"code": code, "side": "buy", "signal_date": day, "reason": evaluation["name"] + "收盘信号", "score": score})
        market_value = sum(p["quantity"] * last_prices.get(code, p["entry_price"]) for code, p in positions.items())
        equity = _money(cash + market_value)
        peak = max(peak, equity)
        benchmark = _money(benchmark_cash + sum(p["quantity"] * last_prices.get(code, p["entry_price"]) for code, p in benchmark_positions.items()))
        curve.append({"date": day, "equity": equity, "cash": cash, "market_value": _money(market_value),
                      "benchmark": benchmark, "drawdown_pct": round((peak - equity) / peak * 100, 6)})
    for order in pending:
        rejections.append({"date": end, "signal_date": order["signal_date"], "code": order["code"], "side": order["side"],
                           "reason": "已到回放区间末尾，尚无下一交易日数据，不假设成交"})
    if stale_dates:
        warnings.append(f"存在 {len(stale_dates)} 个持仓/基准证券日缺少原价，使用最后可用价估值；收益与回撤可能被低估或失真。")
    if not trades:
        warnings.append("本区间没有模拟成交；请查看信号数与拒单原因，不代表程序失效，也不证明策略无效。")
    closed = [trade for trade in trades if trade["side"] == "sell"]
    result_positions = []
    for code, position in positions.items():
        final = {key: value for key, value in position.items() if key != "entry_index"}
        final.update(last_price=last_prices.get(code, position["entry_price"]))
        final["market_value"] = _money(final["last_price"] * final["quantity"])
        final["unrealized_pnl"] = _money(final["market_value"] - final["cost_basis"])
        result_positions.append(final)
    metrics = {"initial_cash": config["initial_cash"], "final_equity": curve[-1]["equity"],
               "total_return_pct": round((curve[-1]["equity"] / config["initial_cash"] - 1) * 100, 6),
               "max_drawdown_pct": max(point["drawdown_pct"] for point in curve), "trade_count": len(trades),
               "closed_trade_count": len(closed), "win_rate_pct": round(sum(trade["realized_pnl"] > 0 for trade in closed) / len(closed) * 100, 4) if closed else None,
               "total_fees": _money(sum(trade["fee"] for trade in trades)), "benchmark_return_pct": round((curve[-1]["benchmark"] / config["initial_cash"] - 1) * 100, 6),
               "signal_count": len(signals), "rejection_count": len(rejections)}
    return {"version": RESEARCH_VERSION, "strategy_version": STRATEGY_VERSION, "config": config,
            "data_fingerprint": fingerprint, "assumptions": ASSUMPTIONS.copy(), "warnings": list(dict.fromkeys(warnings)),
            "excluded": excluded, "metrics": metrics, "equity_curve": curve, "trades": trades, "signals": signals,
            "rejections": rejections, "positions": result_positions,
            "quality": "invalid_corporate_actions" if blocked else "assumption_based_research"}
