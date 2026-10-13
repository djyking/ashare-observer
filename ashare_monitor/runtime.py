"""Independent market collection, research publication and paper-account orchestration."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from . import __version__
from .analysis import analyze_stock
from .data import DEFAULT_WATCHLIST, load_market, security_info
from .models import utcnow
from .portfolio import new_ledger, place_order, advance_ledger, portfolio_view, cancel_order, order_preview
from .rules import next_trading_day, last_closed_day, market_session, is_trading_day, parse_date
from .storage import Store
from .strategies import normalize_strategy_config, strategy_catalog
from .research import normalize_research_config, run_research
from .market_tools import validate_csv_import, commit_csv_import

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
        self.research_worker = None
        self.research_busy = False
        default_codes = [v["code"] if isinstance(v, dict) else v for v in DEFAULT_WATCHLIST]
        self.state = self.store.load() or {
            "settings": {"mode": "demo", "watchlist": default_codes,
                         "refresh_seconds": 300, "initial_cash": 100000, "auto_refresh": True},
            "demo_date": "2026-10-12", "ledger": new_ledger(100000),
            "market": None, "demo_market": None, "analyses": [], "revision": 0}
        self.csv_dir = self.store.root / "imports"
        self.csv_dir.mkdir(exist_ok=True)
        self.state["settings"].setdefault("strategy_config", normalize_strategy_config(None))
        self.state["settings"].setdefault("watchlist_groups", {"默认观察": list(self.state["settings"]["watchlist"])})
        self.state.setdefault("paper_experiment", {"id": uuid4().hex, "name": "初始演示实验", "created_at": utcnow(),
                                                  "start_date": self.state["demo_date"]})

    def start(self):
        self.store.recover_research()
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
        if self.research_worker:
            self.research_worker.join(timeout=2)

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
            analyses = [analyze_stock(stock, cfg.get("strategy_config")) for stock in stocks]
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
                details = {"strategy_version": strategy_catalog()["version"], "strategy_config": cfg.get("strategy_config"),
                           "stocks": [{k: v for k, v in stock.items() if k not in {"candles", "raw_candles"}} for stock in stocks],
                           "analyses": [{k: v for k, v in analysis.items() if k not in {"chart_series", "history", "strategy_history"}}
                                        for analysis in analyses]}
                self.store.save(updated, history, details)
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
        if not isinstance(payload, dict) or set(payload) - {"mode", "watchlist", "refresh_seconds", "auto_refresh", "strategy_config", "watchlist_groups"}:
            raise ValueError("配置字段不受支持。")
        with self.lock:
            if self.refreshing:
                raise BusyError("扫描中暂不能切换数据设置。")
            cfg = {**self.state["settings"], **payload}
            if cfg["mode"] not in {"demo", "eastmoney", "csv"}:
                raise ValueError("请选择有效数据模式。")
            codes = cfg["watchlist"]
            if not isinstance(codes, list) or not 1 <= len(codes) <= 50:
                raise ValueError("观察列表需要 1～50 个股票代码。")
            if any(not isinstance(c, str) or not re.fullmatch(r"\d{6}", c) for c in codes):
                raise ValueError("股票代码必须是六位数字。")
            if len(set(codes)) != len(codes):
                raise ValueError("股票代码不能重复。")
            for code in codes:
                security_info(code)
            cfg["strategy_config"] = normalize_strategy_config(cfg.get("strategy_config"))
            groups = cfg.get("watchlist_groups", {})
            if not isinstance(groups, dict) or len(groups) > 20:
                raise ValueError("股票分组最多 20 组。")
            for name, members in groups.items():
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 30 or not isinstance(members, list):
                    raise ValueError("分组名称或代码列表无效。")
                if len(members) > 50 or any(not isinstance(c, str) or not re.fullmatch(r"\d{6}", c) for c in members):
                    raise ValueError("分组需使用不超过 50 个六位代码。")
                if len(set(members)) != len(members):
                    raise ValueError("分组内代码不能重复。")
                for code in members:
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

    def _portfolio_view(self, include_records=True):
        demo_stocks = (self.state.get("demo_market") or {}).get("stocks", [])
        return portfolio_view(self.state["ledger"], demo_stocks, self.state["demo_date"], include_records=include_records)

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

    def preview_order(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"side", "code", "quantity"}:
            raise ValueError("请填写交易方向、股票代码和股数。")
        with self.lock:
            if self.state["settings"]["mode"] != "demo" or self.refreshing:
                return {"allowed": False, "message": "仅在演示行情就绪后可预览模拟委托。"}
            return order_preview(self.state["ledger"], payload["side"], payload["code"], payload["quantity"],
                                 self.state["demo_date"], (self.state.get("demo_market") or {}).get("stocks", []))

    def paper_records(self, kind, page=1):
        if kind not in {"orders", "trades"}:
            raise ValueError("记录类型应为 orders 或 trades。")
        with self.lock:
            # Slice the ledger before converting records; polling the account
            # summary never needs to transfer its entire trading history.
            records = self.state["ledger"][kind]
            total = len(records)
            pages = max(1, (total + 29) // 30)
            page = max(1, min(pages, int(page)))
            end = total - 30 * (page - 1)
            items = records[max(0, end - 30):end][::-1]
            return {"items": deepcopy(items), "total": total, "page": page, "pages": pages, "page_size": 30}

    def new_demo_experiment(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"name", "initial_cash", "start_date"}:
            raise ValueError("新实验需填写名称、初始资金、起始日期。")
        name = self._name(payload["name"])
        day = parse_date(payload["start_date"]).isoformat()
        if day < "2025-01-02" or not is_trading_day(day):
            raise ValueError("演示起始日必须是 2025 年起已核实的交易日。")
        ledger = new_ledger(payload["initial_cash"])
        with self.lock:
            if self.refreshing:
                raise BusyError("请等待扫描完成再新建演示实验。")
            old = self.state["paper_experiment"]
            archive = {**old, "kind": "demo", "status": "completed", "archived": True, "error": None,
                       "config": {"initial_cash": self.state["ledger"]["initial_cash"], "start_date": old["start_date"],
                                  "watchlist": self.state["settings"]["watchlist"]},
                       "report": {"portfolio": self._portfolio_view(), "ledger": deepcopy(self.state["ledger"]),
                                  "demo_date": self.state["demo_date"]}}
            updated = deepcopy(self.state)
            updated.update(ledger=ledger, demo_date=day, demo_market=None, market=None, analyses=[],
                           paper_experiment={"id": uuid4().hex, "name": name, "created_at": utcnow(), "start_date": day})
            updated["settings"].update(mode="demo", initial_cash=float(ledger["initial_cash"]))
            updated["revision"] += 1
            self.store.save(updated, archive=archive)
            self.state = updated
            self.request_refresh()
            return {"accepted": True, "archived_id": archive["id"], **updated["paper_experiment"]}

    @staticmethod
    def _name(value):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 60:
            raise ValueError("实验名称需要 1～60 个字符。")
        return value.strip()

    def import_csv(self, payload, commit=False):
        allowed = {"code", "text", "overwrite"} if commit else {"code", "text"}
        if not isinstance(payload, dict) or set(payload) - allowed or not {"code", "text"} <= set(payload):
            raise ValueError("导入需要股票代码和 CSV 文本。")
        if not isinstance(payload["text"], str) or len(payload["text"].encode("utf-8")) > 1_000_000:
            raise ValueError("CSV 文件不得超过 1 MB。")
        if not commit:
            return validate_csv_import(payload["code"], payload["text"])
        if type(payload.get("overwrite", False)) is not bool:
            raise ValueError("覆盖选项必须为布尔值。")
        with self.lock:
            if self.refreshing or self.research_busy:
                raise BusyError("行情或研究正在读取数据，请完成后再导入。")
            return commit_csv_import(self.csv_dir, payload["code"], payload["text"], overwrite=payload.get("overwrite", False))

    def start_research(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("研究配置需要 JSON 对象。")
        name = self._name(payload.get("name", "历史策略研究"))
        mode = payload.get("mode", "eastmoney")
        if mode not in {"demo", "eastmoney", "csv"}:
            raise ValueError("请选择有效数据来源。")
        codes = payload.get("codes")
        if not isinstance(codes, list) or not 1 <= len(codes) <= 50 or any(not isinstance(c, str) for c in codes) or len(set(codes)) != len(codes):
            raise ValueError("研究股票池需要 1～50 个不重复股票代码。")
        for code in codes:
            security_info(code)
        config_input = {k: v for k, v in payload.items() if k not in {"name", "mode", "codes"}}
        if not config_input.get("end_date"):
            config_input["end_date"] = last_closed_day()
        config = normalize_research_config(config_input)
        if config["end_date"] > last_closed_day():
            raise ValueError("历史研究结束日期不能晚于最近已收盘交易日。")
        with self.lock:
            if self.research_busy:
                raise BusyError("已有一个研究实验运行中，请完成后再提交。")
            item = self.store.create_experiment("research", name, {**config, "mode": mode, "codes": codes}, utcnow())
            self.research_busy = True
            self.research_worker = threading.Thread(target=self._run_research, args=(item,), daemon=True, name="historical-research")
            try:
                self.research_worker.start()
            except Exception:
                self.research_busy = False
                self.research_worker = None
                self.store.update_experiment(item["id"], {"status": "failed", "error": "后台任务启动失败，请重试。"})
                raise
        return {"id": item["id"], "status": item["status"], "accepted": True}

    def _run_research(self, item):
        try:
            config = item["config"]
            market = load_market(config["mode"], config["codes"], config["end_date"], csv_dir=self.csv_dir)
            report = run_research(market.get("stocks", []), {k: v for k, v in config.items() if k not in {"mode", "codes"}})
            report.update(source=market.get("source"), mode=config["mode"], source_errors=market.get("errors", []))
            self.store.update_experiment(item["id"], {"status": "completed", "report": report, "completed_at": utcnow(),
                                                       "dataset": market, "error": None})
        except Exception as exc:
            self.store.update_experiment(item["id"], {"status": "failed", "error": str(exc)[:400], "completed_at": utcnow()})
        finally:
            with self.lock:
                self.research_busy = False

    def research_detail(self, experiment_id):
        item = self.store.experiment(experiment_id, "research")
        item.pop("dataset", None)
        return item

    def snapshot(self, token, compact=False):
        with self.lock:
            market = self.state.get("market") or {}
            cfg = deepcopy(self.state["settings"])
            analyses = deepcopy(self.state["analyses"])
            stocks = deepcopy(market.get("stocks", []))
            mode = cfg["mode"]
            if compact:
                # Raw bars are only needed by the backend execution model.
                for stock in stocks:
                    stock.pop("raw_candles", None)
            portfolio = self._portfolio_view(include_records=not compact)
            if compact:
                portfolio.pop("orders", None)
                portfolio.pop("trades", None)
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
                    "stocks": stocks, "analyses": analyses, "portfolio": portfolio,
                    "paper_experiment": deepcopy(self.state["paper_experiment"]), "research_busy": self.research_busy,
                    "portfolio_mode": "demo", "settings": cfg, "csrf_token": token}
