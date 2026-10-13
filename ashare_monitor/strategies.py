"""Versioned, public educational strategies. Scores are not probabilities."""
from __future__ import annotations

from copy import deepcopy
import math

STRATEGY_VERSION = "public-v2"
DEFAULT_STRATEGIES = {
    "teaching": {"enabled": True, "min_score": 70, "max_distance_pct": 8, "max_rsi": 75},
    "pullback": {"enabled": True, "min_score": 60, "max_distance_pct": 3, "min_rsi": 40, "max_rsi": 65},
    "breakout": {"enabled": True, "min_score": 60, "lookback": 20, "min_volume_ratio": 1.5, "max_distance_pct": 8},
}
_SPECS = {
    "min_score": ("最低教学评分", 0, 100, 5),
    "max_distance_pct": ("距 EMA20 最大涨幅 %", 0, 30, 0.5),
    "min_rsi": ("RSI 下限", 0, 100, 1),
    "max_rsi": ("RSI 上限", 0, 100, 1),
    "lookback": ("突破前期最高价周期", 5, 60, 1),
    "min_volume_ratio": ("最低量比", 0.1, 10, 0.1),
}
_INFO = {
    "teaching": ("教学综合评分", "用趋势、动量、RSI 与成交量五项各 20 分描述日线状态。",
                 ["达到最低评分", "RSI 与距 EMA20 涨幅未超过配置上限", "当日有成交量"]),
    "pullback": ("上升趋势回调", "在 EMA20 高于 EMA60 的趋势中，等待价格靠近 EMA20 并收在其上方。",
                 ["EMA20 不低于 EMA60", "收盘价在 EMA20 上方且距离不超过上限", "RSI 在指定范围", "达到最低评分且有成交量"]),
    "breakout": ("放量突破", "收盘价超过此前 N 日最高价，同时成交量放大；不把突破等同必然上涨。",
                 ["突破范围不包含信号当天", "收盘价超过此前 N 日最高价", "成交量超过前 20 日均量的指定倍数", "趋势向上且距 EMA20 涨幅有限"]),
}


def strategy_catalog() -> dict:
    return {"version": STRATEGY_VERSION, "defaults": deepcopy(DEFAULT_STRATEGIES), "strategies": [
        {"id": key, "name": _INFO[key][0], "description": _INFO[key][1], "rules": _INFO[key][2],
         "parameters": [{"key": name, "label": _SPECS[name][0], "default": value,
                         "min": _SPECS[name][1], "max": _SPECS[name][2], "step": _SPECS[name][3]}
                        for name, value in params.items() if name != "enabled"]}
        for key, params in DEFAULT_STRATEGIES.items()]}


def normalize_strategy_config(config=None) -> dict:
    if config is None:
        return deepcopy(DEFAULT_STRATEGIES)
    if not isinstance(config, dict) or set(config) - set(DEFAULT_STRATEGIES):
        raise ValueError("策略配置必须使用已知策略标识")
    result = deepcopy(DEFAULT_STRATEGIES)
    for key, supplied in config.items():
        if not isinstance(supplied, dict) or set(supplied) - set(result[key]):
            raise ValueError(f"{key} 包含未知参数")
        for name, value in supplied.items():
            if name == "enabled":
                if not isinstance(value, bool):
                    raise ValueError("策略启用状态必须为布尔值")
            else:
                low, high = _SPECS[name][1:3]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(f"{_SPECS[name][0]}必须在 {low}～{high} 之间")
                if name == "lookback" and value != int(value):
                    raise ValueError("突破周期必须是整数")
            result[key][name] = value
        if "min_rsi" in result[key] and result[key]["min_rsi"] > result[key]["max_rsi"]:
            raise ValueError("RSI 下限不能高于上限")
    return result


def evaluate_strategies(candles, values, score, index, config=None) -> list[dict]:
    config = normalize_strategy_config(config)
    complete = index >= 59 and all(values.get(key) is not None for key in ("ema20", "ema60", "rsi14", "volume_ratio"))
    result = []
    for key, params in config.items():
        checks = []
        def check(label, passed):
            checks.append({"label": label, "passed": bool(passed)})
        check("至少 60 根有效日线", complete)
        if complete:
            check(f"评分不低于 {params['min_score']} 分", score >= params["min_score"])
            check("当日有成交量", candles[index]["volume"] > 0)
            distance = values["ema20_distance_pct"]
            check(f"距 EMA20 涨幅不超过 {params['max_distance_pct']}%", distance <= params["max_distance_pct"])
            if key == "teaching":
                check(f"RSI 不超过 {params['max_rsi']}", values["rsi14"] <= params["max_rsi"])
            else:
                check("EMA20 不低于 EMA60", values["ema20"] >= values["ema60"])
                if key == "pullback":
                    check("收盘价不低于 EMA20", distance >= 0)
                    check(f"RSI 位于 {params['min_rsi']}～{params['max_rsi']}", params["min_rsi"] <= values["rsi14"] <= params["max_rsi"])
                else:
                    window = int(params["lookback"])
                    previous = candles[max(0, index - window):index]
                    check(f"收盘价突破此前 {window} 日最高价", len(previous) == window and candles[index]["close"] > max(row["high"] for row in previous))
                    check(f"量比不低于 {params['min_volume_ratio']}", values["volume_ratio"] >= params["min_volume_ratio"])
        matched = params["enabled"] and all(item["passed"] for item in checks)
        result.append({"id": key, "name": _INFO[key][0], "enabled": params["enabled"], "matched": matched,
                       "score": score if complete else None, "checks": checks,
                       "reasons": [item["label"] for item in checks if not item["passed"]] if not matched else ["所有已启用条件满足；仅形成收盘研究信号"]})
    return result
