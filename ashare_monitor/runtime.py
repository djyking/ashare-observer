"""Independent market collection, research publication and paper-account orchestration."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import threading
import time

from . import __version__
from .analysis import analyze_stock
from .data import DEFAULT_WATCHLIST, load_market, security_info
from .models import utcnow
from .portfolio import new_ledger, place_order, advance_ledger, portfolio_view, cancel_order
from .rules import next_trading_day, last_closed_day, market_session
from .storage import Store

CN = timezone(timedelta(hours=8))


class BusyError(ValueError):
    pass


class Runtime:
    def __init__(self, root):
        self.store = Store(root)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.refreshing = False
        self.last_error = None
        self.last_scan = 0.0
        self.worker = None
        self.scheduler = None
        default_codes = [v["code"] if isinstance(v, dict) else v for v in DEFAULT_WATCHLIST]
        self.state = self.store.load() or {
            "settings": {"mode": "demo", "watchlist": default_codes,
                         "refresh_seconds": 300, "initial_cash": 100000, "auto_refresh": True},
            "demo_date": "2026-10-12", "ledger": new_ledger(100000),
            "market": None, "demo_market": None, "analyses": [], "revision": 0}
        self.csv_dir = self.store.root / "imports"
        self.csv_dir.mkdir(exist_ok=True)

    def start(self):
        # Offline startup is deterministic; public requests always run in a worker.
        if self.state["market"] is None and self.state["settings"]["mode"] == "demo":
            self.refreshing = True
            self._scan(False)
        else:
            self.request_refresh()
        self.scheduler = threading.Thread(target=self._schedule, daemon=True, name="daily-scheduler")
        self.scheduler.start()

    def close(self):
        self.stop_event.set()
        if self.scheduler:
            self.scheduler.join(timeout=2)
        if self.worker:
            self.worker.join(timeout=2)

    def _schedule(self):
        while not self.stop_event.wait(2):
            with self.lock:
                cfg = dict(self.state["settings"])
                market = self.state.get("market") or {}
                busy = self.refreshing
            if busy or not cfg["auto_refresh"] or time.monotonic() - self.last_scan < cfg["refresh_seconds"]:
                continue
            # A daily feed has nothing newly confirmed during the session. A failed
            # feed may retry, but successful daily data only refreshes after closure.
            if cfg["mode"] != "demo":
                try:
                    if market.get("as_of") == last_closed_day() and not market.get("errors"):
                        continue
                except ValueError:
                    continue
            try:
                self.request_refresh()
            except BusyError:
                pass

    def request_refresh(self, advance=False):
        with self.lock:
            if self.refreshing:
                raise BusyError("本轮扫描正在进行，请等待完成。")
            if advance and self.state["settings"]["mode"] != "demo":
                raise ValueError("只有演示模式可以推进模拟交易日。")
            self.refreshing = True
            self.last_error = None
            self.worker = threading.Thread(target=self._scan, args=(advance,), daemon=True, name="market-scan")
            self.worker.start()
        return {"accepted": True, "message": "正在推进演示交易日" if advance else "已提交后台扫描"}

    def _scan(self, advance):
        try:
            with self.lock:
                cfg = deepcopy(self.state["settings"])
                demo_date = self.state["demo_date"]
            as_of = (next_trading_day(demo_date) if advance else demo_date) if cfg["mode"] == "demo" else last_closed_day()
            market = load_market(cfg["mode"], cfg["watchlist"], as_of, csv_dir=self.csv_dir)
            stocks = market.get("stocks", [])
            analyses = [analyze_stock(stock) for stock in stocks]
            analyses.sort(key=lambda x: (-(x.get("score") or 0), x.get("code", "")))
            with self.lock:
                updated = deepcopy(self.state)
                if advance:
                    if market.get("errors"):
                        raise ValueError("演示行情不完整，未推进账本。")
                    updated["ledger"] = advance_ledger(updated["ledger"], stocks, as_of)
                    updated["demo_date"] = as_of
                updated["market"] = market
                updated["analyses"] = analyses
                if cfg["mode"] == "demo":
                    updated["demo_market"] = market
                updated["revision"] += 1
                top = analyses[0] if analyses else {}
                valid = sum(stock.get("status") == "ok" for stock in stocks)
                history = {"created_at": utcnow(), "as_of": as_of, "mode": cfg["mode"],
                           "source": market.get("source", ""), "stock_count": len(stocks),
                           "valid_count": valid,
                           "watch_count": sum(a.get("status") == "watch" for a in analyses),
                           "wait_count": sum(a.get("status") == "wait" for a in analyses),
                           "top_code": top.get("code"), "top_name": top.get("name"),
                           "top_score": top.get("score"),
                           "summary": f"{valid}/{len(stocks)} 只数据有效；日线教学规则观察，无自动实盘操作"}
                self.store.save(updated, history)
                self.state = updated
                self.last_error = "; ".join(
                    (f"{v.get('code', '')}：{v.get('error', '')}" if isinstance(v, dict) else str(v))[:180]
                    for v in market.get("errors", [])) or None
        except Exception as exc:
            with self.lock:
                self.last_error = f"扫描未完成：{type(exc).__name__}：{str(exc)[:240]}"
        finally:
            with self.lock:
                self.last_scan = time.monotonic()
                self.refreshing = False

    def settings(self, payload):
        if not isinstance(payload, dict) or set(payload) - {"mode", "watchlist", "refresh_seconds", "auto_refresh"}:
            raise ValueError("配置字段不受支持。")
        with self.lock:
            if self.refreshing:
                raise BusyError("扫描中暂不能切换数据设置。")
            cfg = {**self.state["settings"], **payload}
            if cfg["mode"] not in {"demo", "eastmoney", "csv"}:
                raise ValueError("请选择有效数据模式。")
            codes = cfg["watchlist"]
            if not isinstance(codes, list) or not 1 <= len(codes) <= 12:
                raise ValueError("观察列表需要 1～12 个股票代码。")
            if any(not isinstance(c, str) or not re.fullmatch(r"\d{6}", c) for c in codes):
                raise ValueError("股票代码必须是六位数字。")
            if len(set(codes)) != len(codes):
                raise ValueError("股票代码不能重复。")
            for code in codes:
                security_info(code)
            interval = cfg["refresh_seconds"]
            if isinstance(interval, bool) or not isinstance(interval, int) or not 300 <= interval <= 86400:
                raise ValueError("扫描间隔应为 300～86400 秒的整数。")
            if not isinstance(cfg["auto_refresh"], bool):
                raise ValueError("自动扫描必须是布尔值。")
            # Do not allow removing a symbol while it has an open lot or order.
            retained = set()
            view = self._portfolio_view()
            for p in view.get("positions", []):
                if p.get("quantity", 0):
                    retained.add(p["code"])
            for order in view.get("orders", []):
                if order.get("status") in {"pending", "open", "queued"}:
                    retained.add(order["code"])
            if not retained.issubset(set(codes)):
                raise ValueError("观察列表需保留仍有模拟持仓或待成交委托的股票。")
            updated = deepcopy(self.state)
            updated["settings"] = cfg
            # A mode switch must never display the previous source as the new one.
            updated["market"] = None
            updated["analyses"] = []
            updated["revision"] += 1
            self.store.save(updated)
            self.state = updated
            # Reserve the worker before releasing the same lock as the source
            # switch; no order may see new settings with old market data.
            return self.request_refresh()

    def _portfolio_view(self):
        demo_stocks = (self.state.get("demo_market") or {}).get("stocks", [])
        return portfolio_view(self.state["ledger"], demo_stocks, self.state["demo_date"])

    def paper_order(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"side", "code", "quantity", "request_id"}:
            raise ValueError("请提交方向、股票代码、股数及唯一请求编号。")
        if not isinstance(payload["request_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", payload["request_id"]):
            raise ValueError("请求编号无效。")
        with self.lock:
            if self.refreshing:
                raise BusyError("扫描中暂不能提交模拟委托。")
            if self.state["settings"]["mode"] != "demo":
                raise ValueError("真实行情和 CSV 模式只提供研究，不能提交模拟委托。")
            if payload["code"] not in self.state["settings"]["watchlist"]:
                raise ValueError("股票不在当前观察列表。")
            market = self.state.get("demo_market") or {}
            ledger = place_order(self.state["ledger"], payload["side"], payload["code"],
                                 payload["quantity"], self.state["demo_date"],
                                 market.get("stocks", []), payload["request_id"])
            self._save_ledger(ledger)
            return {"ok": True, "message": "模拟委托已登记，等待后续交易日开盘；不连接证券账户。"}

    def cancel(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"order_id"}:
            raise ValueError("缺少委托编号。")
        with self.lock:
            if self.refreshing:
                raise BusyError("扫描中暂不能撤销模拟委托。")
            if self.state["settings"]["mode"] != "demo":
                raise ValueError("请切回演示模式再管理模拟委托。")
            self._save_ledger(cancel_order(self.state["ledger"], payload["order_id"]))
        return {"ok": True, "message": "模拟委托已撤销。"}

    def _save_ledger(self, ledger):
        updated = deepcopy(self.state)
        updated["ledger"] = ledger
        updated["revision"] += 1
        self.store.save(updated)
        self.state = updated

    def snapshot(self, token):
        with self.lock:
            market = self.state.get("market") or {}
            cfg = deepcopy(self.state["settings"])
            analyses = deepcopy(self.state["analyses"])
            stocks = deepcopy(market.get("stocks", []))
            mode = cfg["mode"]
            notice = ("当前为合成日线演示，股价与收益均不代表真实市场。推进交易日会撮合模拟委托。"
                      if mode == "demo" else "日线研究：仅使用已收盘资料，非实时行情；尚未接入券商实盘，已提供账户适配扩展点。")
            return {"app": {"name": "A 股量化交易研究平台", "version": __version__, "mode": mode,
                            "as_of": market.get("as_of"), "source": market.get("source", "等待扫描"),
                            "fetched_at": market.get("fetched_at"), "refreshing": self.refreshing,
                            "last_error": self.last_error, "notice": notice,
                            "revision": self.state["revision"], "demo_date": self.state["demo_date"]},
                    "session": market_session(),
                    "stats": {"stock_count": len(stocks),
                              "valid_count": sum(s.get("status") == "ok" for s in stocks),
                              "watch_count": sum(a.get("status") == "watch" for a in analyses),
                              "wait_count": sum(a.get("status") == "wait" for a in analyses)},
                    "stocks": stocks, "analyses": analyses, "portfolio": self._portfolio_view(),
                    "portfolio_mode": "demo", "settings": cfg, "csrf_token": token}
