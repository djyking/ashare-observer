"""Persistent-JSON-compatible, pure-function educational A-share ledger.

Money is stored as decimal strings; browser views use JSON numbers. Decisions
after a completed daily bar become pending limit orders for a subsequent open.
Orders are valid only on that next trading day and are expired if its opening
cannot be filled conservatively. The model omits intraday re-submission,
tick-level queues, post-close fixed-price trading and corporate actions. Its
commission assumptions are not a quotation for any particular broker.
"""

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

from .rules import (decimal_number, ensure_ordinary_stock, is_trading_day,
                    limit_prices, next_trading_day, parse_date,
                    validate_quantity, valid_raw_candles)

CENT = Decimal("0.01")
FEE_ASSUMPTIONS = {
    "commission_rate": "0.0003", "minimum_commission": "5.00",
    "transfer_rate": "0.00001", "sell_stamp_rate": "0.0005",
    "description": "教学假设：佣金万分之三、单笔最低 5 元；过户费十万分之一双向；卖出印花税万分之五。佣金视为包含经手费用，实际以券商账单为准。",
}


def money(value):
    return decimal_number(value).quantize(CENT, rounding=ROUND_HALF_UP)


def _stored(value):
    return format(money(value), ".2f")


def fee_breakdown(notional, side):
    value = decimal_number(notional, "成交金额", positive=True)
    if side not in ("buy", "sell"):
        raise ValueError("方向必须为 buy 或 sell")
    commission = money(max(Decimal(FEE_ASSUMPTIONS["minimum_commission"]),
                           value * Decimal(FEE_ASSUMPTIONS["commission_rate"])))
    transfer = money(value * Decimal(FEE_ASSUMPTIONS["transfer_rate"]))
    stamp = money(value * Decimal(FEE_ASSUMPTIONS["sell_stamp_rate"])) if side == "sell" else Decimal("0.00")
    return {"commission": commission, "transfer": transfer, "stamp": stamp,
            "total": commission + transfer + stamp}


def new_ledger(initial_cash=100000):
    cash = money(decimal_number(initial_cash, "初始资金", positive=True))
    if cash <= 0 or cash > Decimal("1000000000"):
        raise ValueError("初始模拟资金须大于 0 且不超过 10 亿元")
    return {"schema_version": 1, "mode": "demo", "initial_cash": _stored(cash),
            "cash": _stored(cash), "fees": "0.00", "realized_pnl": "0.00",
            "as_of": None, "positions": {}, "orders": [], "trades": [],
            "fee_assumptions": deepcopy(FEE_ASSUMPTIONS)}


def _check_ledger(ledger):
    if ledger.get("schema_version") != 1 or ledger.get("mode") != "demo":
        raise ValueError("不支持的模拟账本版本或模式")
    if decimal_number(ledger["cash"]) < 0:
        raise ValueError("模拟账本现金异常")


def _index(stocks):
    result = {}
    for stock in stocks:
        code = stock.get("code")
        if code in result:
            raise ValueError("股票列表含重复代码")
        result[code] = stock
    return result


def _frozen_cash(ledger, exclude=None):
    return sum((Decimal(order.get("reserved_cash", "0")) for order in ledger["orders"]
                if order["status"] == "pending" and order["side"] == "buy" and order["id"] != exclude), Decimal(0))


def _frozen_shares(ledger, code, exclude=None):
    return sum(order["quantity"] for order in ledger["orders"] if order["status"] == "pending"
               and order["side"] == "sell" and order["code"] == code and order["id"] != exclude)


def _quantity(position):
    return sum(lot["quantity"] for lot in position.get("lots", []))


def _sellable(position, day):
    return sum(lot["quantity"] for lot in position.get("lots", []) if lot["acquired_date"] < day)


def _validate_date(ledger, value):
    day = parse_date(value).isoformat()
    if not is_trading_day(day):
        raise ValueError("必须使用已核实的交易日")
    if ledger.get("as_of") and day < ledger["as_of"]:
        raise ValueError("模拟账本不允许回到过去")
    return day


def order_preview(ledger, side, code, quantity, day, stocks):
    """Validate a next-open order without mutating the ledger or reserving cash.

    Today's acquired lots can be reserved for the next session; actual fills
    independently recheck T+1. Estimates use the signal close, while buys freeze
    the upper-limit amount to cover the possible next opening price.
    """
    result = {"allowed": False, "message": "", "error_code": None, "side": side,
              "code": code, "quantity": quantity, "board": None, "min_quantity": None,
              "step": None, "reference_price": None, "estimated_notional": None,
              "fees": None, "reserved_cash": 0, "available_cash": None,
              "sellable_now": 0, "sellable_on_execution": 0, "execute_after": None,
              "limit_price": None, "slippage_bps": 0,
              "quantity_rule": "买入按板块最低股数与申报步长；卖出需满足可卖余额及零股一次卖出规则。",
              "notice": "按本日收盘估算金额与费用；次日开盘撮合，开盘价可能不同；滑点假设为 0。"}
    try:
        _check_ledger(ledger)
        day = _validate_date(ledger, day)
        result["available_cash"] = float(Decimal(ledger["cash"]) - _frozen_cash(ledger))
        if side not in ("buy", "sell"):
            raise ValueError("方向必须为 buy 或 sell")
        stock = _index(stocks).get(code)
        if stock is None:
            raise ValueError("股票不在当前观察列表")
        result.update(board=stock.get("board"), min_quantity=200 if stock.get("board") == "star" else 100,
                      step=100 if stock.get("board") in ("main", "growth") else 1)
        ensure_ordinary_stock(stock, day)
        if stock.get("status") in ("suspended", "unavailable", "error", "delisted"):
            raise ValueError("股票停牌或行情不可用，不接受新模拟委托")
        bars = valid_raw_candles(stock)
        if day not in bars or bars[day]["volume"] <= 0:
            raise ValueError("缺少信号日期的有效不复权日线")
        execute_after = next_trading_day(day)
        position = ledger["positions"].get(code, {"lots": []})
        frozen = _frozen_shares(ledger, code)
        available = max(0, _sellable(position, execute_after) - frozen)
        result.update(execute_after=execute_after,
                      sellable_now=max(0, _sellable(position, day) - frozen),
                      sellable_on_execution=available, reference_price=float(bars[day]["close"]))
        if side == "sell":
            minimum = 200 if stock["board"] == "star" else 100
            result["step"] = 1
            result["min_quantity"] = (min(100, available % 100 or 100) if stock["board"] in ("main", "growth")
                                      else min(minimum, available)) if available else None
        quantity = validate_quantity(stock["board"], side, quantity, available)
        result["quantity"] = quantity
        upper, lower = limit_prices(bars[day]["close"], stock["board"])
        notional = money(bars[day]["close"] * quantity)
        result.update(estimated_notional=float(notional),
                      fees={key: float(value) for key, value in fee_breakdown(notional, side).items()},
                      limit_price=float(upper if side == "buy" else lower))
        if side == "buy":
            reserved = money(upper * quantity) + fee_breakdown(upper * quantity, "buy")["total"]
            result["reserved_cash"] = float(reserved)
            if reserved > Decimal(ledger["cash"]) - _frozen_cash(ledger):
                raise ValueError(f"可用资金不足，含费用需冻结 {reserved:.2f} 元")
        if sum(order["status"] == "pending" for order in ledger["orders"]) >= 100:
            raise ValueError("最多同时保留 100 笔待成交模拟委托")
        result.update(allowed=True, message="预检查通过，委托将在下一交易日开盘尝试撮合。")
    except (ValueError, TypeError, KeyError) as exc:
        result.update(error_code="invalid_order", message=str(exc) if isinstance(exc, ValueError) else "委托或账本字段无效")
    return result


def place_order(ledger, side, code, quantity, trade_date, stocks, request_id):
    _check_ledger(ledger)
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
        raise ValueError("request_id 必须为 1 至 128 字符")
    # A retry must not submit a second order, including after cancellation/fill.
    for order in ledger["orders"]:
        if order["request_id"] == request_id:
            if (order["side"], order["code"], str(order["quantity"]), order["created_date"]) != (side, code, str(quantity), trade_date):
                raise ValueError("request_id 已用于不同委托")
            return deepcopy(ledger)
    preview = order_preview(ledger, side, code, quantity, trade_date, stocks)
    if not preview["allowed"]:
        raise ValueError(preview["message"])
    day = parse_date(trade_date).isoformat()
    stock = _index(stocks)[code]
    execute_after, quantity = preview["execute_after"], preview["quantity"]
    result = deepcopy(ledger)
    result["as_of"] = day
    result["orders"].append({
        "id": f"paper-{len(result['orders']) + 1}", "request_id": request_id,
        "side": side, "code": code, "name": stock.get("name", code), "quantity": quantity,
        "status": "pending", "created_date": day, "execute_after": execute_after,
        "limit_price": _stored(preview["limit_price"]),
        "reserved_cash": _stored(preview["reserved_cash"]), "last_checked_date": None,
        "reason": "等待下一交易日开盘；仅当日有效；停牌、缺数据或涨跌停不假定成交",
    })
    return result


def cancel_order(ledger, order_id):
    _check_ledger(ledger)
    result = deepcopy(ledger)
    for order in result["orders"]:
        if order["id"] == order_id:
            if order["status"] == "cancelled":
                return result
            if order["status"] != "pending":
                raise ValueError("仅可撤销待成交的模拟委托")
            order.update(status="cancelled", reserved_cash="0.00", reason="用户撤销模拟委托")
            return result
    raise ValueError("未找到模拟委托")


def _consume_lots(position, quantity, day):
    remaining, total_cost = quantity, Decimal(0)
    for lot in position["lots"]:
        if remaining == 0:
            break
        if lot["acquired_date"] >= day:
            continue
        take = min(lot["quantity"], remaining)
        if take == 0:
            continue
        cost = Decimal(lot["cost"]) if take == lot["quantity"] else money(Decimal(lot["cost"]) * take / lot["quantity"])
        lot["quantity"] -= take
        lot["cost"] = _stored(Decimal(lot["cost"]) - cost)
        total_cost += cost
        remaining -= take
    if remaining:
        raise ValueError("模拟成交可卖股份不足")
    position["lots"] = [lot for lot in position["lots"] if lot["quantity"] > 0]
    return total_cost


def _try_fill(ledger, order, stock, bars, day):
    order["last_checked_date"] = day
    if stock is None:
        order["reason"] = "股票不在本轮行情中，继续等待"
        return
    try:
        ensure_ordinary_stock(stock, day)
    except ValueError as exc:
        order["reason"] = str(exc)
        return
    if stock.get("status") in ("suspended", "delisted", "error", "unavailable"):
        order["reason"] = "停牌、退市或行情不可用，未模拟成交"
        return
    if day not in bars or bars[day]["volume"] <= 0:
        order["reason"] = "当日缺少有效原价日线或停牌，继续等待"
        return
    prior = sorted(value for value in bars if value < day)
    if not prior:
        order["reason"] = "缺少前收盘原价，无法验证涨跌停"
        return
    upper, lower = limit_prices(bars[prior[-1]]["close"], stock["board"])
    opening = bars[day]["open"]
    if opening > upper or opening < lower:
        order["reason"] = "原价超出普通涨跌幅范围，可能涉及除权或特殊规则，未模拟成交"
        return
    if order["side"] == "buy" and opening >= upper:
        order["reason"] = "涨停开盘，无法确认买入排队成交，继续等待"
        return
    if order["side"] == "sell" and opening <= lower:
        order["reason"] = "跌停开盘，无法确认卖出排队成交，继续等待"
        return
    limit = Decimal(order["limit_price"])
    if (order["side"] == "buy" and opening > limit) or (order["side"] == "sell" and opening < limit):
        order["reason"] = "开盘价超出提交时的模拟限价，继续等待"
        return
    quantity, side, code = order["quantity"], order["side"], order["code"]
    notional = money(opening * quantity)
    fees = fee_breakdown(notional, side)
    fee, pnl = fees["total"], Decimal(0)
    position = ledger["positions"].setdefault(code, {"code": code, "name": stock.get("name", code), "lots": []})
    if side == "buy":
        total = notional + fee
        if total > Decimal(ledger["cash"]) - _frozen_cash(ledger, order["id"]):
            order["reason"] = "开盘含费用金额超过可用资金，未成交"
            return
        ledger["cash"] = _stored(Decimal(ledger["cash"]) - total)
        position["lots"].append({"quantity": quantity, "acquired_date": day, "cost": _stored(total)})
    else:
        available = _sellable(position, day) - _frozen_shares(ledger, code, order["id"])
        if quantity > available:
            order.update(status="rejected", reason="股份不足或受 T+1 限制，委托已拒绝", reserved_cash="0.00")
            return
        if Decimal(ledger["cash"]) + notional - fee < _frozen_cash(ledger):
            order.update(status="rejected", reason="零股成交金额不足支付费用且可用现金不足，委托已拒绝", reserved_cash="0.00")
            return
        basis = _consume_lots(position, quantity, day)
        pnl = notional - fee - basis
        ledger["cash"] = _stored(Decimal(ledger["cash"]) + notional - fee)
        ledger["realized_pnl"] = _stored(Decimal(ledger["realized_pnl"]) + pnl)
    ledger["fees"] = _stored(Decimal(ledger["fees"]) + fee)
    order.update(status="filled", filled_date=day, filled_price=_stored(opening),
                 reserved_cash="0.00", reason="后续交易日开盘模拟成交，不代表实际可成交保证")
    ledger["trades"].append({"id": f"fill-{len(ledger['trades']) + 1}", "order_id": order["id"], "date": day, "side": side,
                             "code": code, "name": stock.get("name", code), "quantity": quantity,
                             "price": _stored(opening), "notional": _stored(notional),
                             "fee": _stored(fee), "pnl": _stored(pnl),
                             "fees": {key: _stored(value) for key, value in fees.items()}})
    if not position["lots"]:
        del ledger["positions"][code]


def advance_ledger(ledger, stocks, trade_date):
    _check_ledger(ledger)
    day = _validate_date(ledger, trade_date)
    result = deepcopy(ledger)
    stock_index = _index(stocks)
    bar_index, bar_errors = {}, {}
    for code, stock in stock_index.items():
        if stock.get("mode") != "demo":
            raise ValueError("模拟账本仅允许离线演示行情推进")
        try:
            bar_index[code] = valid_raw_candles(stock)
        except ValueError as exc:
            bar_errors[code] = str(exc)
            bar_index[code] = {}
    pending = [order for order in result["orders"] if order["status"] == "pending" and order["execute_after"] <= day]
    if pending:
        cursor = min(order["execute_after"] for order in pending)
        while cursor <= day:
            for order in pending:
                if order["status"] != "pending" or cursor < order["execute_after"]:
                    continue
                if order.get("last_checked_date") and cursor <= order["last_checked_date"]:
                    continue
                if order["code"] in bar_errors:
                    order.update(reason=bar_errors[order["code"]], last_checked_date=cursor)
                else:
                    _try_fill(result, order, stock_index.get(order["code"]), bar_index.get(order["code"], {}), cursor)
                if order["status"] == "pending":
                    reason = order["reason"].replace("，继续等待", "")
                    order.update(status="expired", reserved_cash="0.00", expired_date=cursor,
                                 reason=f"{reason}；日线模拟仅尝试次日开盘，当日未成交委托失效")
            if cursor == day:
                break
            cursor = next_trading_day(cursor)
    result["as_of"] = day
    return result


def portfolio_view(ledger, stocks, trade_date, include_records=True):
    _check_ledger(ledger)
    day = parse_date(trade_date).isoformat()
    stock_index = _index(stocks)
    positions, market_value, unrealized = [], Decimal(0), Decimal(0)
    prices_complete = True
    for code, position in ledger["positions"].items():
        quantity = _quantity(position)
        if quantity <= 0:
            continue
        cost = sum((Decimal(lot["cost"]) for lot in position["lots"]), Decimal(0))
        stock = stock_index.get(code)
        price, valued_at = None, None
        if stock and stock.get("mode") == "demo":
            try:
                bars = valid_raw_candles(stock)
                dates = sorted(item for item in bars if item <= day)
                if dates:
                    valued_at = dates[-1]
                    price = bars[valued_at]["close"]
            except ValueError:
                pass
        value = money(price * quantity) if price is not None else None
        pnl = value - cost if value is not None else None
        prices_complete = prices_complete and price is not None
        if value is not None:
            market_value += value
            unrealized += pnl
        frozen = _frozen_shares(ledger, code)
        positions.append({"code": code, "name": position.get("name", code), "quantity": quantity,
                          "sellable": max(0, _sellable(position, day) - frozen), "frozen": frozen,
                          "sellable_on_execution": max(0, _quantity(position) - frozen),
                          "avg_cost": float(cost / quantity), "last_price": float(price) if price is not None else None,
                          "price_date": valued_at, "price_stale": valued_at != day,
                          "market_value": float(value) if value is not None else None,
                          "unrealized_pnl": float(pnl) if pnl is not None else None})
    frozen = _frozen_cash(ledger)
    result = {"initial_cash": float(ledger["initial_cash"]), "cash": float(ledger["cash"]),
              "available_cash": float(Decimal(ledger["cash"]) - frozen), "frozen_cash": float(frozen),
              "equity": float(Decimal(ledger["cash"]) + market_value) if prices_complete else None,
              "realized_pnl": float(ledger["realized_pnl"]),
              "unrealized_pnl": float(unrealized) if prices_complete else None,
              "fees": float(ledger["fees"]), "positions": positions,
              "orders": deepcopy(ledger["orders"]) if include_records else [],
              "trades": deepcopy(ledger["trades"]) if include_records else [],
              "order_count": len(ledger["orders"]), "trade_count": len(ledger["trades"]),
              "fee_assumptions": deepcopy(FEE_ASSUMPTIONS), "as_of": ledger.get("as_of"),
              "slippage_bps": 0,
              "valuation_complete": prices_complete,
              "notice": "仅离线演示；日线信号在下一交易日开盘模拟撮合，当日未成交委托失效；T+1；费用为教学假设，不模拟分红送转、盘后交易与逐笔排队。"}
    for trade in result["trades"]:
        for key in ("price", "notional", "fee", "pnl"):
            trade[key] = float(trade[key])
    return result
