"""Transparent daily-bar teaching indicators; scores are not win probabilities."""
from __future__ import annotations

import math

from .data import validate_candles
from .strategies import STRATEGY_VERSION, evaluate_strategies, normalize_strategy_config


def ema(values: list[float], period: int) -> list[float | None]:
    if period < 1:
        raise ValueError("EMA 周期必须为正整数")
    output = [None] * len(values)
    if len(values) < period:
        return output
    value = sum(values[:period]) / period
    output[period - 1] = value
    alpha = 2 / (period + 1)
    for i in range(period, len(values)):
        value += alpha * (values[i] - value)
        output[i] = value
    return output


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    output = [None] * len(values)
    if len(values) <= period:
        return output
    gains = [max(values[i] - values[i - 1], 0) for i in range(1, len(values))]
    losses = [max(values[i - 1] - values[i], 0) for i in range(1, len(values))]
    gain, loss = sum(gains[:period]) / period, sum(losses[:period]) / period
    def convert(g, l):
        return 50.0 if g == 0 and l == 0 else (100.0 if l == 0 else 100 - 100 / (1 + g / l))
    output[period] = convert(gain, loss)
    for i in range(period + 1, len(values)):
        gain = (gain * (period - 1) + gains[i - 1]) / period
        loss = (loss * (period - 1) + losses[i - 1]) / period
        output[i] = convert(gain, loss)
    return output


def atr(candles: list[dict], period: int = 14) -> list[float | None]:
    output = [None] * len(candles)
    if len(candles) < period:
        return output
    ranges = []
    for i, row in enumerate(candles):
        prev = candles[i - 1]["close"] if i else row["close"]
        ranges.append(max(row["high"] - row["low"], abs(row["high"] - prev), abs(row["low"] - prev)))
    value = sum(ranges[:period]) / period
    output[period - 1] = value
    for i in range(period, len(candles)):
        value = (value * (period - 1) + ranges[i]) / period
        output[i] = value
    return output


def _series(candles: list[dict]) -> dict:
    closes = [r["close"] for r in candles]
    fast, slow = ema(closes, 12), ema(closes, 26)
    macd = [f - s if f is not None and s is not None else None for f, s in zip(fast, slow)]
    valid = [value for value in macd if value is not None]
    signal = [None] * (len(candles) - len(valid)) + ema(valid, 9)
    return {"ema20": ema(closes, 20), "ema60": ema(closes, 60), "rsi14": rsi(closes),
            "atr14": atr(candles), "macd": macd, "macd_signal": signal,
            # Histogram uses DIF - DEA, without an extra scale factor.
            "macd_hist": [m - s if m is not None and s is not None else None for m, s in zip(macd, signal)]}


def _at(candles: list[dict], series: dict, i: int) -> tuple[dict, int, str, str, list[str]]:
    row = candles[i]
    values = {name: entries[i] for name, entries in series.items()}
    base_volumes = [r["volume"] for r in candles[max(0, i - 20):i]]
    baseline = sum(base_volumes) / len(base_volumes) if base_volumes else 0
    values["volume_ratio"] = row["volume"] / baseline if baseline > 0 else None
    values["close"] = row["close"]
    values["change_pct"] = (row["close"] / candles[i - 1]["close"] - 1) * 100 if i else 0
    values["ema20_distance_pct"] = (row["close"] / values["ema20"] - 1) * 100 if values["ema20"] else None
    components, reasons = {}, []
    if i < 59 or any(values[k] is None for k in ("ema20", "ema60", "rsi14", "atr14", "macd_hist")):
        return values, 0, "insufficient", "数据不足", ["至少需要 60 根已收盘日线才能形成完整教学指标"]
    components["price_trend"] = 20 if row["close"] >= values["ema20"] else 0
    components["medium_trend"] = 20 if values["ema20"] >= values["ema60"] else 0
    components["momentum"] = 20 if values["macd_hist"] >= 0 else 0
    rv = values["rsi14"]
    components["rsi_balance"] = 20 if 45 <= rv <= 65 else (10 if 35 <= rv <= 75 else 0)
    vr = values["volume_ratio"]
    components["volume"] = 20 if vr is not None and 0.8 <= vr <= 2 else (5 if vr is not None and vr > 0 else 0)
    score = sum(components.values())
    values["score_components"] = components
    reasons.append("收盘价在 EMA20 上方" if components["price_trend"] else "收盘价仍在 EMA20 下方")
    reasons.append("EMA20 不低于 EMA60" if components["medium_trend"] else "中期均线趋势尚未转强")
    reasons.append("MACD 动量非负" if components["momentum"] else "MACD 动量偏弱")
    reasons.append(f"RSI14 为 {rv:.1f}，成交量为前 20 日均量的 {vr:.2f} 倍" if vr is not None else "成交量基准不足")
    extended = rv > 75 or values["ema20_distance_pct"] > 8
    if extended:
        reasons.append("短期偏离较大，观察回落后再研究，不把高分作为追涨理由")
    status = "watch" if score >= 70 and not extended and row["volume"] > 0 else "wait"
    if row["volume"] == 0:
        reasons.append("最近日线没有成交量，不能推断存在可成交机会")
    route = "趋势观察" if components["medium_trend"] else "趋势待确认"
    return values, score, status, route, reasons


def _rounded(values: dict) -> dict:
    return {k: round(v, 6) if isinstance(v, float) and math.isfinite(v) else v for k, v in values.items()}


def analyze_stock(stock: dict, config: dict | None = None) -> dict:
    strategy_config = normalize_strategy_config(config)
    result = {"code": stock.get("code"), "name": stock.get("name"), "score": None,
              "status": "unavailable", "route": "无有效行情", "reasons": [],
              "indicators": {}, "plan": None, "history": [], "chart_series": [],
              "score_components": [], "strategy_results": [], "strategy_history": [],
              "strategy_version": STRATEGY_VERSION,
              "notice": "教学观察分，不是盈利概率；情景价位不是投资建议或买入授权"}
    if stock.get("status") != "ok" or not stock.get("candles"):
        result["reasons"] = [stock.get("error") or "没有可用的已收盘日线"]
        return result
    try:
        candles = validate_candles(stock["candles"], stock.get("data_date"))
    except (ValueError, TypeError) as exc:
        result["reasons"] = [f"日线校验未通过：{exc}"]
        return result
    series = _series(candles)
    values, score, status, route, reasons = _at(candles, series, len(candles) - 1)
    evaluations = evaluate_strategies(candles, values, score, len(candles) - 1, strategy_config)
    if config is not None and status != "insufficient":
        matches = [item["name"] for item in evaluations if item["matched"]]
        status = "watch" if matches else "wait"
        route = " / ".join(matches) if matches else "策略条件待满足"
    stale = bool(stock.get("stale") or (stock.get("as_of") and candles[-1]["date"] < stock["as_of"]))
    if stale:
        if status == "watch":
            status = "wait"
        route = "历史资料待更新"
        reasons.append(f"最近日线 {candles[-1]['date']} 落后于观察日 {stock.get('as_of') or stock.get('stale_as_of') or '当前日期'}；"
                       "可能停牌或数据源延迟，评分仅描述历史状态，不形成当前观察机会或价位情景")
    result.update(score=score if status != "insufficient" else None, status=status, route=route,
                  reasons=reasons, indicators=_rounded(values), data_date=candles[-1]["date"], stale=stale,
                  strategy_results=evaluations)
    component_rules = {
        "price_trend": ("价格趋势", "收盘价 ≥ EMA20 得 20 分，否则 0 分"),
        "medium_trend": ("中期趋势", "EMA20 ≥ EMA60 得 20 分，否则 0 分"),
        "momentum": ("MACD 动量", "DIF − DEA ≥ 0 得 20 分，否则 0 分"),
        "rsi_balance": ("RSI 均衡", "RSI14 在 45～65 得 20 分，在 35～75 得 10 分，否则 0 分"),
        "volume": ("成交量", "前 20 日量比在 0.8～2 得 20 分，其他正量比得 5 分，无成交量得 0 分"),
    }
    result["score_components"] = [{"key": key, "label": info[0], "score": values.get("score_components", {}).get(key, 0),
                                    "max_score": 20, "rule": info[1]} for key, info in component_rules.items()]
    raw = stock.get("raw_candles") or []
    if status != "insufficient" and raw and not stale:
        try:
            raw = validate_candles(raw, stock.get("data_date"))
        except (ValueError, TypeError):
            raw = []
        if raw and raw[-1]["date"] == candles[-1]["date"]:
            reference = raw[-1]["close"]
            unit = values["atr14"] / candles[-1]["close"] * reference
            stop, target = max(0.01, reference - 1.5 * unit), reference + 2 * unit
            result["plan"] = {"reference_price": round(reference, 4), "stop_price": round(stop, 4),
                              "target_price": round(target, 4), "expected_gain_pct": round((target / reference - 1) * 100, 3),
                              "risk_pct": round((1 - stop / reference) * 100, 3),
                              "note": "仅为收盘原价 ± ATR 的教学情景，未计费用、跳空及无法成交风险，不预测可实现收益"}
    if not result["plan"] and status != "insufficient" and not stale:
        result["reasons"].append("没有同日可靠原价，不生成可与实际价格比较的情景价位")
    # One transition event per observation episode, calculated from prefixes only.
    previous_status = None
    history = []
    previous_matches = set()
    strategy_history = []
    for i in range(len(candles)):
        historical_values, historical_score, historical_status, historical_route, _ = _at(candles, series, i)
        result["chart_series"].append(_rounded({"date": candles[i]["date"], **{key: historical_values.get(key) for key in series},
                                                 "volume_ratio": historical_values.get("volume_ratio")}))
        matches = evaluate_strategies(candles, historical_values, historical_score, i, strategy_config)
        current_matches = {item["id"] for item in matches if item["matched"]}
        for match in matches:
            if match["matched"] and match["id"] not in previous_matches:
                strategy_history.append({"date": candles[i]["date"], "strategy_id": match["id"], "name": match["name"],
                                         "score": historical_score, "close": candles[i]["close"]})
        previous_matches = current_matches
        if historical_status == "watch" and previous_status != "watch":
            history.append({"date": candles[i]["date"], "code": stock.get("code"), "name": stock.get("name"),
                            "score": historical_score, "status": historical_status, "route": historical_route,
                            "close": candles[i]["close"], "description": "教学观察条件首次满足；未模拟当根收盘成交"})
        previous_status = historical_status
    result["history"] = history[-60:]
    result["strategy_history"] = strategy_history[-180:]
    return result
