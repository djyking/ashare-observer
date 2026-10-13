"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const state = { data: null, selected: null, filter: "all", sort: "score", view: "overview", settingsDirty: false, settingsHydrated: false, snapshotKey: "", requestSequence: 0, historySequence: 0, historyPage: 1, historyPages: 1, ordersPage: 1, tradesPage: 1, loading: false, loadWaiters: [], actionBusy: false, pollTimer: null, chart: [] };
  const statusNames = { watch: "值得观察", wait: "等待条件", insufficient: "数据不足", unavailable: "数据不可用" };
  const modeNames = { demo: "离线演示", eastmoney: "真实日线", csv: "本地 CSV" };
  const routeNames = { trend: "趋势观察", trend_pullback: "趋势回调", pullback: "回调观察", breakout: "突破观察", momentum: "动量观察", wait: "等待条件", insufficient: "数据不足", unavailable: "数据不可用" };
  const orderStatuses = { pending: "待成交", filled: "已成交", cancelled: "已取消", canceled: "已取消", rejected: "已拒绝", expired: "已失效", partially_filled: "部分成交" };
  const modeDescriptions = {
    demo: "使用确定性的合成日线，价格不是任何股票的真实行情。可以提交模拟委托、推进演示日期，用来观察规则与账本的完整流程。",
    eastmoney: "读取公开 A 股日线，只显示已收盘数据，不是逐笔实时行情。不保证数据源的持续可用性；本模式仅用于只读研究，模拟账本仍保持独立。",
    csv: "读取项目配置目录中的 CSV 日线文件，仅用于只读研究。字段格式和导入路径见本地项目文档；不会将缺失数据替换为合成行情。"
  };
  const number = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) ? Number(value) : null;
  const fmt = (value, digits = 2) => number(value) === null ? "—" : Number(value).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const signed = (value, digits = 2) => number(value) === null ? "—" : `${Number(value) > 0 ? "+" : ""}${fmt(value, digits)}`;
  const pct = (value) => number(value) === null ? "—" : `${signed(value)}%`;
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const color = (value) => number(value) > 0 ? "up" : number(value) < 0 ? "down" : "";
  const badge = (status) => `<span class="badge ${Object.hasOwn(statusNames, status) ? status : "neutral"}">${esc(statusNames[status] || status || "待观察")}</span>`;
  const timeText = (value, dateOnly = false) => {
    if (!value) return "—";
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
    const date = new Date(value);
    if (!Number.isFinite(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", ...(dateOnly ? {} : { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) }).format(date);
  };
  const setText = (id, value) => { const node = $(id); if (node && node.textContent !== String(value)) node.textContent = String(value); };
  const money = (value) => number(value) === null ? "—" : `¥ ${fmt(value)}`;
  const pnlText = (id, value, prefix = "") => { const node = $(id); node.textContent = `${prefix}${signed(value)}`; node.classList.remove("up", "down"); if (color(value)) node.classList.add(color(value)); };

  let toastTimer;
  function toast(message, isError = false) {
    $("toast").textContent = message;
    $("toast").className = `toast${isError ? " error" : ""}`;
    $("toast").hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { $("toast").hidden = true; }, 5500);
  }

  async function api(path, body) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);
    try {
      const options = { signal: controller.signal, cache: "no-store", headers: { "Accept": "application/json" } };
      if (body !== undefined) {
        if (!state.data?.csrf_token) throw new Error("尚未取得会话校验信息，请等待页面连接成功。");
        options.method = "POST";
        options.headers["Content-Type"] = "application/json";
        options.headers["X-CSRF-Token"] = state.data.csrf_token;
        options.body = JSON.stringify(body);
      }
      const response = await fetch(path, options);
      let data;
      try { data = await response.json(); } catch (_) { throw new Error(`服务返回了无法读取的响应（${response.status}），请检查本地服务。`); }
      if (!response.ok) throw new Error(data.error || `请求未完成（HTTP ${response.status}）`);
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("本地服务响应超时。已保留当前画面，请稍后再试。");
      if (error instanceof TypeError) throw new Error("暂时无法连接本地服务。已保留最后一次数据，请确认服务仍在运行。");
      throw error;
    } finally { clearTimeout(timeout); }
  }

  function schedulePoll(delay = 10000) {
    clearTimeout(state.pollTimer);
    state.pollTimer = setTimeout(async () => {
      if (!document.hidden || state.data?.app?.refreshing) await loadState(false);
      const interval = state.data?.app?.refreshing ? 1800 : 10000;
      schedulePoll(interval);
    }, delay);
  }

  async function loadState(showErrors = true, afterMutation = false) {
    if (state.loading) {
      if (!afterMutation) return;
      await new Promise((resolve) => state.loadWaiters.push(resolve));
      return loadState(showErrors, true);
    }
    state.loading = true;
    updateControls();
    const sequence = ++state.requestSequence;
    try {
      const data = await api("/api/state");
      if (sequence !== state.requestSequence) return;
      state.data = data;
      if (!state.settingsHydrated) {
        state.settingsDirty = false;
        renderSettings();
        state.settingsHydrated = true;
        $("settings-feedback").textContent = "";
        $("settings-feedback").className = "inline-feedback";
      } else if (!state.settingsDirty) {
        renderSettings();
      }
      renderHeader();
      const snapshotKey = JSON.stringify([data.app?.mode, data.app?.as_of, data.app?.fetched_at, data.stats, data.stocks, data.analyses, data.portfolio]);
      if (snapshotKey !== state.snapshotKey) {
        state.snapshotKey = snapshotKey;
        renderOverview();
        renderPortfolio();
        if (state.view === "history") loadHistory(state.historyPage);
      }
      showGlobalError(data.app?.last_error || "");
    } catch (error) {
      if (sequence !== state.requestSequence) return;
      showGlobalError(error.message);
      if (showErrors && state.data) toast(error.message, true);
      if (!state.data) {
        setText("session-label", "连接失败");
        $("watch-body").innerHTML = '<tr><td colspan="5" class="empty">无法读取数据，请确认本地服务已启动，再点击右上角刷新。</td></tr>';
        $("refresh-top").title = "重新连接本地服务";
        setText("settings-feedback", "尚未连接成功，设置暂不可编辑。请点击右上角刷新重试。");
        $("settings-feedback").className = "inline-feedback error";
      }
    } finally {
      state.loading = false;
      updateControls();
      state.loadWaiters.splice(0).forEach((resolve) => resolve());
    }
  }

  function updateControls() {
    const ready = Boolean(state.data && state.settingsHydrated);
    const busy = state.actionBusy || Boolean(state.data?.app?.refreshing);
    const demoReady = ready && state.data.app?.mode === "demo";
    ["settings-mode", "settings-watchlist", "settings-interval", "settings-auto", "save-settings"].forEach((id) => { $(id).disabled = !ready || busy; });
    ["order-code", "order-side", "order-quantity", "submit-order", "advance-day"].forEach((id) => { $(id).disabled = !demoReady || busy; });
    $("refresh-top").disabled = busy || (!ready && state.loading);
    document.querySelectorAll(".cancel-order").forEach((button) => { button.disabled = !demoReady || busy; });
  }

  function showGlobalError(message) {
    $("global-error").hidden = !message;
    $("global-error").textContent = message;
  }

  function renderHeader() {
    const { app = {}, session = {} } = state.data;
    const mode = app.mode || "demo";
    $("source-notice").classList.toggle("live", mode !== "demo");
    const title = mode === "demo" ? "演示环境 · 合成行情" : mode === "eastmoney" ? "真实行情 · 已收盘日线" : "本地 CSV · 只读研究";
    const description = mode === "demo" ? "价格不是实际股价；全部资金、委托和成交均为模拟。" : "研究结果不等于交易指令；账本为独立演示数据，不使用当前行情计价。";
    const content = $("source-notice").querySelector("div");
    content.innerHTML = `<strong>${title}</strong><span>${description}</span>`;
    setText("mode-badge", mode === "demo" ? "DEMO" : mode === "eastmoney" ? "日线" : "CSV");
    setText("session-label", `${session.label || "市场时段待确认"}${session.calendar_known === false ? " · 日历未覆盖" : ""}`);
    setText("data-date", `${mode === "demo" ? "演示日期" : "收盘数据截至"} ${app.as_of || "—"}`);
    setText("updated-time", `${app.refreshing ? "正在更新 · " : "最近采集 "}${timeText(app.fetched_at)}`);
    setText("app-version", `A 股专用版 ${app.version || ""}`);
    setText("footer-source", `${app.source || modeNames[mode] || "本地研究"} · 不构成投资建议`);
    $("refresh-top").classList.toggle("busy", Boolean(app.refreshing));
    $("refresh-top").title = app.refreshing ? "行情正在更新，画面保留上一快照" : "重新采集行情";
    updateControls();
  }

  function stockRows() {
    const { stocks = [], analyses = [] } = state.data || {};
    const list = Array.isArray(analyses) ? analyses : Object.values(analyses);
    return stocks.map((stock) => {
      const analysis = list.find((item) => item.code === stock.code) || { status: stock.status === "unavailable" ? "unavailable" : "insufficient" };
      const candles = stock.candles || [];
      const current = candles.at(-1);
      const prior = candles.at(-2);
      const price = number(current?.close);
      const change = prior && number(prior.close) > 0 && price !== null ? (price / Number(prior.close) - 1) * 100 : number(analysis.indicators?.change_pct);
      return { stock, analysis, candles, price, change };
    });
  }

  function renderOverview() {
    const { stats = {}, portfolio = {} } = state.data;
    const rows = stockRows();
    setText("stat-total", fmt(stats.stock_count ?? rows.length, 0));
    setText("stat-valid", `${fmt(stats.valid_count ?? rows.filter((row) => row.candles.length).length, 0)} 只行情有效`);
    setText("stat-watch", fmt(stats.watch_count ?? rows.filter((row) => row.analysis.status === "watch").length, 0));
    setText("stat-wait", fmt(stats.wait_count ?? rows.filter((row) => row.analysis.status === "wait").length, 0));
    setText("stat-equity", money(portfolio.equity));
    const totalPnl = number(portfolio.equity) !== null && number(portfolio.initial_cash) !== null ? Number(portfolio.equity) - Number(portfolio.initial_cash) : null;
    setText("stat-pnl", `${state.data.app?.mode === "demo" ? "累计模拟收益" : "独立演示账本收益"} ${signed(totalPnl)} 元`);
    if (!rows.some((row) => row.stock.code === state.selected)) state.selected = rows.find((row) => row.candles.length)?.stock.code || rows[0]?.stock.code || null;
    renderWatch();
    renderDetail();
  }

  function renderWatch() {
    let rows = stockRows();
    if (state.filter !== "all") rows = rows.filter((row) => row.analysis.status === state.filter);
    rows.sort((a, b) => state.sort === "code" ? a.stock.code.localeCompare(b.stock.code) : state.sort === "change" ? (b.change ?? -Infinity) - (a.change ?? -Infinity) || a.stock.code.localeCompare(b.stock.code) : (number(b.analysis.score) ?? -Infinity) - (number(a.analysis.score) ?? -Infinity) || a.stock.code.localeCompare(b.stock.code));
    setText("watch-count", String(rows.length));
    $("watch-body").innerHTML = rows.length ? rows.map(({ stock, analysis, price, change }) => `<tr class="watch-row${stock.code === state.selected ? " selected" : ""}" tabindex="0" data-code="${esc(stock.code)}" aria-label="查看${esc(stock.name || stock.code)}的研究详情" aria-selected="${stock.code === state.selected}"><td><span class="stock-name">${esc(stock.name || stock.code)}</span><span class="stock-code">${esc(stock.code)} · ${esc(exchangeName(stock.exchange))}</span></td><td class="num">${fmt(price)}</td><td class="num ${color(change)}">${pct(change)}</td><td class="num"><span class="score">${fmt(analysis.score, 0)}</span><span class="score-track"><i style="width:${Math.max(0, Math.min(100, number(analysis.score) || 0))}%"></i></span></td><td>${badge(analysis.status)}</td></tr>`).join("") : '<tr><td colspan="5" class="empty">当前筛选下没有股票。没有满足条件的观察对象是正常结果。</td></tr>';
    setText("watch-footer", `${rows.length} 只股票 · 点击行查看研究依据`);
  }

  function exchangeName(exchange) {
    return ({ SH: "沪市", SZ: "深市", BJ: "北交所", SSE: "沪市", SZSE: "深市", BSE: "北交所", sh: "沪市", sz: "深市", bj: "北交所" })[exchange] || exchange || "A 股";
  }

  function renderDetail() {
    const row = stockRows().find((item) => item.stock.code === state.selected);
    if (!row) {
      setText("detail-name", "暂无观察股票");
      setText("detail-code", "DAILY CHART");
      setText("detail-price", "—");
      setText("detail-change", "—");
      setText("detail-reasons", "可在数据与设置中添加观察股票。");
      setText("detail-status", "等待数据");
      $("detail-status").className = "badge neutral";
      $("indicator-grid").innerHTML = '<div><span>EMA 20</span><strong>—</strong></div><div><span>RSI 14</span><strong>—</strong></div><div><span>MACD 柱</span><strong>—</strong></div>';
      ["plan-reference", "plan-stop", "plan-target"].forEach((id) => setText(id, "—"));
      setText("plan-note", "当前没有有效行情，不生成情景价格。");
      setText("chart-range", "暂无有效数据");
      $("chart-tooltip").hidden = true;
      $("price-chart").innerHTML = '<text x="300" y="120" text-anchor="middle" fill="#92a2a9" font-size="12">暂无日线数据</text>';
      state.chart = [];
      return;
    }
    const { stock, analysis, price, change, candles } = row;
    setText("detail-code", `${stock.code} · ${exchangeName(stock.exchange)} · ${stock.sector || "日线研究"}`);
    setText("detail-name", stock.name || stock.code);
    setText("detail-price", fmt(price));
    setText("detail-change", `${pct(change)}  日涨跌`);
    $("detail-change").className = color(change);
    $("detail-status").className = `badge ${Object.hasOwn(statusNames, analysis.status) ? analysis.status : "neutral"}`;
    setText("detail-status", statusNames[analysis.status] || "待观察");
    const reasons = Array.isArray(analysis.reasons) ? analysis.reasons.join("；") : analysis.reasons || "暂无可用研究判断。";
    const route = routeNames[analysis.route] || analysis.route;
    setText("detail-reasons", `${route ? `${route}：` : ""}${stock.error || reasons}`);
    const indicators = analysis.indicators || {};
    $("indicator-grid").innerHTML = `<div><span>EMA 20</span><strong>${fmt(indicators.ema20)}</strong></div><div><span>RSI 14</span><strong>${fmt(indicators.rsi14, 1)}</strong></div><div><span>MACD 柱</span><strong class="${color(indicators.macd_hist)}">${signed(indicators.macd_hist, 3)}</strong></div>`;
    const plan = analysis.plan;
    setText("plan-reference", fmt(plan?.reference_price));
    setText("plan-stop", fmt(plan?.stop_price));
    setText("plan-target", fmt(plan?.target_price));
    setText("plan-note", plan ? `${plan.note || "用于比较潜在上行与下行的研究情景，不保证触及这些价格。"}${number(plan.expected_gain_pct) !== null ? ` 目标距离 ${pct(plan.expected_gain_pct)}` : ""}${number(plan.risk_pct) !== null ? ` · 风险距离 ${fmt(Math.abs(plan.risk_pct))}%` : ""}` : "数据或条件不足，暂不生成情景价格。此处为空不代表系统会自动下单。");
    setText("chart-adjustment", state.data.app?.mode === "demo" ? "合成行情 · 非真实股价 · 最近已完成日线" : `${stock.adjustment === "qfq" || stock.adjustment === "forward" ? "前复权分析日线" : "日线行情"} · 不是盘中实时成交价 · 数据截至 ${stock.data_date || candles.at(-1)?.date || "—"}`);
    renderChart(candles);
  }

  function renderChart(allCandles) {
    $("chart-tooltip").hidden = true;
    const candles = allCandles.filter((c) => [c.open, c.high, c.low, c.close].every((v) => number(v) !== null));
    if (!candles.length) {
      state.chart = [];
      $("price-chart").innerHTML = '<text x="300" y="120" text-anchor="middle" fill="#92a2a9" font-size="12">行情不足，无法绘制日线</text>';
      setText("chart-range", "暂无有效数据");
      return;
    }
    let ema = Number(candles[0].close);
    const points = candles.map((c, index) => { ema = index ? Number(c.close) * (2 / 21) + ema * (19 / 21) : ema; return { ...c, ema }; }).slice(-50);
    state.chart = points;
    const low = Math.min(...points.map((c) => Number(c.low)), ...points.map((c) => c.ema));
    const high = Math.max(...points.map((c) => Number(c.high)), ...points.map((c) => c.ema));
    const padding = Math.max((high - low) * 0.12, high * 0.005);
    const min = low - padding, max = high + padding;
    const y = (value) => 13 + (max - Number(value)) / (max - min) * 167;
    const step = 530 / points.length, x = (index) => 13 + step * (index + 0.5);
    const width = Math.max(2, Math.min(8, step * 0.58));
    const maxVolume = Math.max(1, ...points.map((c) => Number(c.volume) || 0));
    let markup = '<title>已收盘日线：红涨绿跌，金色线为 EMA 20，底部为成交量。</title>';
    for (let i = 0; i < 4; i++) {
      const value = max - (max - min) * i / 3, py = y(value);
      markup += `<line x1="12" x2="548" y1="${py}" y2="${py}" stroke="#edf1f0" stroke-dasharray="3 3"/><text x="555" y="${py + 3}" font-size="9" fill="#98a5ac">${fmt(value)}</text>`;
    }
    markup += points.map((c, i) => {
      const fill = Number(c.close) >= Number(c.open) ? "#c96c70" : "#4d9b83";
      const candleY = Math.min(y(c.open), y(c.close)), candleHeight = Math.max(1.4, Math.abs(y(c.open) - y(c.close)));
      const volumeHeight = Math.max(1, (Number(c.volume) || 0) / maxVolume * 31);
      return `<g><line x1="${x(i)}" x2="${x(i)}" y1="${y(c.high)}" y2="${y(c.low)}" stroke="${fill}" stroke-width="1"/><rect x="${x(i) - width / 2}" y="${candleY}" width="${width}" height="${candleHeight}" fill="${fill}" rx=".5"/><rect x="${x(i) - width / 2}" y="${219 - volumeHeight}" width="${width}" height="${volumeHeight}" fill="${fill}" opacity=".35"/></g>`;
    }).join("");
    markup += `<path d="${points.map((c, i) => `${i ? "L" : "M"}${x(i).toFixed(2)},${y(c.ema).toFixed(2)}`).join(" ")}" fill="none" stroke="#c1a168" stroke-width="1.5"/>`;
    const tickIndices = [...new Set([0, Math.floor(points.length / 3), Math.floor(points.length * 2 / 3), points.length - 1])];
    tickIndices.forEach((i) => { markup += `<text x="${x(i)}" y="240" text-anchor="${i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}" font-size="9" fill="#a0acb1">${esc(String(points[i].date).slice(5))}</text>`; });
    markup += '<line id="chart-cursor" x1="0" x2="0" y1="10" y2="220" stroke="#99b3bb" stroke-dasharray="3 3" visibility="hidden"/>';
    $("price-chart").innerHTML = markup;
    setText("chart-range", `${points[0].date} — ${points.at(-1).date}`);
  }

  function renderPortfolio() {
    const portfolio = state.data.portfolio || {}, stocks = state.data.stocks || [];
    const isDemo = state.data.app?.mode === "demo";
    setText("pf-equity", money(portfolio.equity));
    setText("pf-initial", `初始模拟资金 ${money(portfolio.initial_cash)}`);
    setText("pf-cash", money(portfolio.available_cash ?? portfolio.cash));
    pnlText("pf-realized", portfolio.realized_pnl, "¥ ");
    pnlText("pf-unrealized", portfolio.unrealized_pnl, "¥ ");
    setText("pf-fees", `累计费用 ${money(portfolio.fees)}`);
    $("pf-cash").nextElementSibling.textContent = `待成交预留 ${money(portfolio.frozen_cash ?? 0)}`;
    $("positions-body").innerHTML = (portfolio.positions || []).length ? portfolio.positions.map((p) => `<tr><td><span class="stock-name">${esc(p.name || p.code)}</span><span class="stock-code">${esc(p.code)}</span></td><td class="num">${fmt(p.quantity, 0)}<span class="stock-code">可卖 ${fmt(p.sellable, 0)}</span></td><td class="num">${fmt(p.avg_cost)}<span class="stock-code">现价 ${fmt(p.last_price)}</span></td><td class="num">${money(p.market_value)}</td><td class="num ${color(p.unrealized_pnl)}">${signed(p.unrealized_pnl)}</td></tr>`).join("") : '<tr><td colspan="5" class="empty">当前没有模拟持仓。提交模拟委托后，推进演示日期以尝试撮合。</td></tr>';
    renderOrdersAndTrades();
    const select = $("order-code");
    const optionsKey = stocks.map((s) => `${s.code}:${s.name}`).join("|");
    if (select.dataset.optionsKey !== optionsKey) {
      const previous = select.value;
      select.innerHTML = stocks.map((s) => `<option value="${esc(s.code)}">${esc(s.name || s.code)} · ${esc(s.code)}</option>`).join("");
      if (stocks.some((s) => s.code === previous)) select.value = previous;
      select.dataset.optionsKey = optionsKey;
    }
    updateControls();
    setText("order-help", isDemo ? "普通股票买入通常为 100 股的整数倍；其他板块按对应规则校验。下一交易日开盘尝试撮合一次；未成交则当日失效，不延续到更晚日期。" : "当前为只读研究模式。上方显示独立演示账本，不使用当前行情计价；切回离线演示后才可提交或取消模拟委托。");
  }

  function renderOrdersAndTrades() {
    const p = state.data.portfolio || {};
    const name = (code) => state.data.stocks?.find((s) => s.code === code)?.name || code;
    const orders = [...(p.orders || [])].reverse(), trades = [...(p.trades || [])].reverse();
    const orderPages = Math.max(1, Math.ceil(orders.length / 30)), tradePages = Math.max(1, Math.ceil(trades.length / 30));
    state.ordersPage = Math.min(state.ordersPage, orderPages); state.tradesPage = Math.min(state.tradesPage, tradePages);
    const orderSlice = orders.slice((state.ordersPage - 1) * 30, state.ordersPage * 30), tradeSlice = trades.slice((state.tradesPage - 1) * 30, state.tradesPage * 30);
    $("orders-body").innerHTML = orderSlice.length ? orderSlice.map((o) => `<tr><td>${esc(o.created_date || o.date || "—")}</td><td>${esc(name(o.code))}<span class="stock-code">${esc(o.code)}</span></td><td class="${o.side === "buy" ? "up" : "down"}">${o.side === "buy" ? "模拟买入" : "模拟卖出"}</td><td class="num">${fmt(o.quantity, 0)}</td><td><span class="badge ${o.status === "pending" ? "wait" : "neutral"}">${esc(orderStatuses[o.status] || o.status)}</span></td><td class="order-note">${esc(o.reason || "—")}</td><td>${o.status === "pending" ? `<button class="cancel-order" type="button" data-order-id="${esc(o.id)}" disabled title="仅在离线演示模式且未更新时可取消">取消</button>` : ""}</td></tr>`).join("") : '<tr><td colspan="7" class="empty">尚无模拟委托。观察评分不会自动创建委托。</td></tr>';
    $("trades-body").innerHTML = tradeSlice.length ? tradeSlice.map((t) => `<tr><td>${esc(t.date || "—")}</td><td>${esc(name(t.code))}<span class="stock-code">${esc(t.code)}</span></td><td class="${t.side === "buy" ? "up" : "down"}">${t.side === "buy" ? "模拟买入" : "模拟卖出"}</td><td class="num">${fmt(t.quantity, 0)}</td><td class="num">${fmt(t.price)}</td><td class="num">${fmt(t.fee)}</td><td class="num ${color(t.pnl)}">${signed(t.pnl)}</td></tr>`).join("") : '<tr><td colspan="7" class="empty">尚无模拟成交。未成交委托不计入持仓或收益。</td></tr>';
    setText("orders-count", `共 ${orders.length} 笔 · 每页 30 笔`); setText("trades-count", `共 ${trades.length} 笔 · 每页 30 笔`);
    setText("orders-page", `${state.ordersPage} / ${orderPages}`); setText("trades-page", `${state.tradesPage} / ${tradePages}`);
    $("orders-prev").disabled = state.ordersPage <= 1; $("orders-next").disabled = state.ordersPage >= orderPages;
    $("trades-prev").disabled = state.tradesPage <= 1; $("trades-next").disabled = state.tradesPage >= tradePages;
    updateControls();
  }

  function renderSettings() {
    const settings = state.data?.settings || {};
    $("settings-mode").value = settings.mode || state.data.app?.mode || "demo";
    $("settings-watchlist").value = (settings.watchlist || []).join(", ");
    $("settings-interval").value = settings.refresh_seconds ?? 300;
    $("settings-auto").checked = settings.auto_refresh !== false;
    setText("mode-description", modeDescriptions[$("settings-mode").value] || "");
    $("settings-dirty").hidden = true;
  }

  async function loadHistory(page = 1) {
    const sequence = ++state.historySequence;
    $("history-prev").disabled = true; $("history-next").disabled = true;
    try {
      const history = await api(`/api/history?page=${page}&page_size=30`);
      if (sequence !== state.historySequence) return;
      state.historyPage = history.page || page; state.historyPages = Math.max(1, history.pages || 1);
      setText("history-total", `共 ${history.total || 0} 条研究快照`);
      setText("history-page", `${state.historyPage} / ${state.historyPages}`);
      const items = history.items || [];
      $("history-body").innerHTML = items.length ? items.map((item) => {
        const details = typeof item.summary === "string" ? item.summary : Array.isArray(item.summary) ? item.summary.join("；") : item.summary ? JSON.stringify(item.summary) : Array.isArray(item.reasons) ? item.reasons.join("；") : "本次扫描仅记录研究结果，没有自动委托。";
        return `<tr><td>${esc(timeText(item.created_at || item.timestamp || item.as_of))}<span class="stock-code">${esc(modeNames[item.mode] || item.mode || "研究记录")} · 日线截至 ${esc(item.as_of || "—")}</span></td><td>${esc(item.top_name || item.name || item.top_code || "无领先观察")}<span class="stock-code">${esc(item.top_code || item.code || "—")}</span></td><td class="num">${fmt(item.top_score ?? item.score, 0)}</td><td>${item.status ? badge(item.status) : `<span class="badge watch">观察 ${fmt(item.watch_count, 0)}</span> <span class="badge wait">等待 ${fmt(item.wait_count, 0)}</span>`}</td><td><details class="history-detail"><summary>展开依据</summary><p>${esc(details)}</p><p>数据源：${esc(item.source || modeNames[item.mode] || "—")}<br>有效 / 总数：${fmt(item.valid_count, 0)} / ${fmt(item.stock_count, 0)}</p></details></td></tr>`;
      }).join("") : '<tr><td colspan="5" class="empty">还没有研究历史。完成行情扫描后会生成记录。</td></tr>';
      $("history-prev").disabled = state.historyPage <= 1; $("history-next").disabled = state.historyPage >= state.historyPages;
    } catch (error) {
      if (sequence !== state.historySequence) return;
      toast(`历史记录：${error.message}`, true);
      $("history-prev").disabled = state.historyPage <= 1; $("history-next").disabled = state.historyPage >= state.historyPages;
    }
  }

  function navigate() {
    const requested = location.hash.replace(/^#/, "") || "overview";
    state.view = ["overview", "portfolio", "history", "settings"].includes(requested) ? requested : "overview";
    document.querySelectorAll(".view").forEach((view) => { view.hidden = view.id !== `view-${state.view}`; });
    document.querySelectorAll(".nav-link").forEach((link) => link.classList.toggle("active", link.getAttribute("href") === `#${state.view}`));
    setText("page-label", { overview: "市场概览", portfolio: "模拟账本", history: "研究历史", settings: "数据与设置" }[state.view]);
    if (state.view === "history") loadHistory(state.historyPage);
  }

  async function mutate(button, path, body, success, feedbackId) {
    if (button.disabled || state.actionBusy || !state.settingsHydrated || state.data?.app?.refreshing) return false;
    state.actionBusy = true;
    button.disabled = true;
    updateControls();
    const original = button.textContent;
    button.textContent = "处理中…";
    if (feedbackId) { $(feedbackId).textContent = ""; $(feedbackId).className = "inline-feedback"; }
    let ok = false;
    try {
      await api(path, body);
      ok = true;
      if (feedbackId) { $(feedbackId).textContent = success; $(feedbackId).className = "inline-feedback success"; }
      toast(success);
      await loadState(false, true);
      schedulePoll(1500);
    } catch (error) {
      if (feedbackId) { $(feedbackId).textContent = error.message; $(feedbackId).className = "inline-feedback error"; }
      toast(error.message, true);
    } finally {
      state.actionBusy = false;
      button.textContent = original;
      button.disabled = false;
      if (state.data) { renderHeader(); renderPortfolio(); }
      updateControls();
    }
    return ok;
  }

  $("refresh-top").addEventListener("click", async () => {
    if (!state.data) { await loadState(); return; }
    await mutate($("refresh-top"), "/api/refresh", {}, "已请求更新，完成后将自动显示新快照。");
  });
  $("watch-body").addEventListener("click", (event) => { const row = event.target.closest("[data-code]"); if (!row) return; state.selected = row.dataset.code; renderWatch(); renderDetail(); });
  $("watch-body").addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { const row = event.target.closest("[data-code]"); if (row) { event.preventDefault(); row.click(); } } });
  document.querySelectorAll(".filter").forEach((button) => button.addEventListener("click", () => { state.filter = button.dataset.status; document.querySelectorAll(".filter").forEach((b) => b.classList.toggle("active", b === button)); renderWatch(); }));
  $("sort-select").addEventListener("change", (event) => { state.sort = event.target.value; renderWatch(); });
  $("price-chart").addEventListener("pointermove", (event) => {
    if (!state.chart.length) return;
    const bounds = $("price-chart").getBoundingClientRect(), px = (event.clientX - bounds.left) / bounds.width * 600;
    const index = Math.max(0, Math.min(state.chart.length - 1, Math.floor((px - 13) / 530 * state.chart.length))), c = state.chart[index];
    const x = 13 + 530 / state.chart.length * (index + .5);
    const cursor = $("chart-cursor");
    if (cursor) { cursor.setAttribute("x1", x); cursor.setAttribute("x2", x); cursor.setAttribute("visibility", "visible"); }
    $("chart-tooltip").innerHTML = `<strong>${esc(c.date)}</strong><br>开 ${fmt(c.open)} · 高 ${fmt(c.high)}<br>低 ${fmt(c.low)} · 收 ${fmt(c.close)}<br>成交量 ${fmt(c.volume, 0)} 股`;
    $("chart-tooltip").style.left = index > state.chart.length / 2 ? "15px" : "auto";
    $("chart-tooltip").style.right = index > state.chart.length / 2 ? "auto" : "50px";
    $("chart-tooltip").hidden = false;
  });
  $("price-chart").addEventListener("pointerleave", () => { $("chart-tooltip").hidden = true; $("chart-cursor")?.setAttribute("visibility", "hidden"); });
  $("advance-day").addEventListener("click", () => mutate($("advance-day"), "/api/demo/advance", {}, "正在推进演示交易日并尝试撮合模拟委托。"));
  $("order-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const quantity = Number($("order-quantity").value);
    if (!Number.isInteger(quantity) || quantity < 1) { toast("请输入有效的整数股数。", true); return; }
    const requestId = `web-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
    mutate($("submit-order"), "/api/paper/order", { side: $("order-side").value, code: $("order-code").value, quantity, request_id: requestId }, "模拟委托已记录。推进演示日期后，按规则尝试成交。", "order-feedback");
  });
  $("orders-body").addEventListener("click", (event) => { const button = event.target.closest(".cancel-order"); if (button) mutate(button, "/api/paper/cancel", { order_id: button.dataset.orderId }, "待成交模拟委托已取消。"); });
  $("settings-form").addEventListener("input", () => { if (!state.settingsHydrated) return; state.settingsDirty = true; $("settings-dirty").hidden = false; setText("mode-description", modeDescriptions[$("settings-mode").value] || ""); });
  $("settings-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.settingsHydrated || $("save-settings").disabled) return;
    const codes = [...new Set($("settings-watchlist").value.split(/[\s,，;；]+/).filter(Boolean))];
    if (!codes.length || codes.some((code) => !/^\d{6}$/.test(code))) { toast("请填写 6 位股票代码，用逗号或换行分隔。", true); return; }
    const success = await mutate($("save-settings"), "/api/settings", { mode: $("settings-mode").value, watchlist: codes, refresh_seconds: Number($("settings-interval").value), auto_refresh: $("settings-auto").checked }, "设置已保存，正在更新研究数据。演示账本保持独立。", "settings-feedback");
    if (success) { state.settingsDirty = false; renderSettings(); }
  });
  $("history-refresh").addEventListener("click", () => loadHistory(state.historyPage));
  $("history-prev").addEventListener("click", () => loadHistory(Math.max(1, state.historyPage - 1)));
  $("history-next").addEventListener("click", () => loadHistory(Math.min(state.historyPages, state.historyPage + 1)));
  ["orders", "trades"].forEach((kind) => {
    $(`${kind}-prev`).addEventListener("click", () => { state[`${kind}Page`] = Math.max(1, state[`${kind}Page`] - 1); renderOrdersAndTrades(); });
    $(`${kind}-next`).addEventListener("click", () => { state[`${kind}Page`]++; renderOrdersAndTrades(); });
  });
  window.addEventListener("hashchange", navigate);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { loadState(false); schedulePoll(10000); } });
  function tickClock() { setText("local-clock", new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date())); }
  tickClock(); setInterval(tickClock, 30000);
  navigate();
  loadState().then(() => schedulePoll(2000));
})();
