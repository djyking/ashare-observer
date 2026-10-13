<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import StockChart from './StockChart.vue'
import type { Analysis, Snapshot } from '../types'
import { fmt, money, pct, signed, color, statusNames, routeNames, exchangeName, timeText, numeric } from '../format'
const props = defineProps<{ snapshot: Snapshot | null }>()
const filter = ref('all'), sort = ref('score'), selected = ref('')
const rows = computed(() => (props.snapshot?.stocks ?? []).map(stock => {
  const analysis: Analysis = props.snapshot?.analyses.find(a => a.code === stock.code) ?? { code: stock.code, status: 'insufficient', score: null, reasons: [] }
  const current = stock.candles.at(-1), prior = stock.candles.at(-2)
  return { stock, analysis, price: current?.close, change: current && prior && prior.close > 0 ? (current.close / prior.close - 1) * 100 : null }
}))
const visible = computed(() => rows.value.filter(row => filter.value === 'all' || row.analysis.status === filter.value).sort((a, b) => {
  if (sort.value === 'code') return a.stock.code.localeCompare(b.stock.code)
  return (sort.value === 'change' ? (b.change ?? -Infinity) - (a.change ?? -Infinity) : (b.analysis.score ?? -Infinity) - (a.analysis.score ?? -Infinity)) || a.stock.code.localeCompare(b.stock.code)
}))
watch(rows, value => { if (!value.some(row => row.stock.code === selected.value)) selected.value = value.find(row => row.stock.candles.length)?.stock.code ?? value[0]?.stock.code ?? '' }, { immediate: true })
const detail = computed(() => rows.value.find(row => row.stock.code === selected.value))
const indicators = computed(() => detail.value?.analysis.indicators ?? {})
const plan = computed(() => detail.value?.analysis.plan)
const totalPnl = computed(() => {
  const equity = numeric(props.snapshot?.portfolio.equity), initial = numeric(props.snapshot?.portfolio.initial_cash)
  return equity === null || initial === null ? null : equity - initial
})
</script>

<template>
  <section class="view" aria-label="市场概览">
    <div class="page-heading"><div><div class="eyebrow">A-SHARE QUANTITATIVE RESEARCH</div><h1>先看市场，再看机会<span class="heading-dot">.</span></h1><p>以已收盘日线观察趋势，让每个研究判断都有数据可循。</p></div><div class="snapshot-meta"><span>{{ snapshot?.app.mode === 'demo' ? '演示日期' : '收盘数据截至' }} {{ snapshot?.app.as_of ?? '—' }}</span><small>{{ snapshot?.app.refreshing ? '正在更新 · ' : '最近采集 ' }}{{ timeText(snapshot?.app.fetched_at) }}</small></div></div>
    <div class="stats-grid" aria-label="市场统计">
      <article class="stat-card"><span class="stat-label">观察股票</span><div class="stat-value">{{ fmt(snapshot?.stats.stock_count, 0) }}</div><span class="stat-foot">{{ fmt(snapshot?.stats.valid_count, 0) }} 只行情有效</span><span class="stat-symbol">▤</span></article>
      <article class="stat-card"><span class="stat-label">值得观察</span><div class="stat-value teal">{{ fmt(snapshot?.stats.watch_count, 0) }}</div><span class="stat-foot">满足示例研究条件</span><span class="stat-symbol teal">↗</span></article>
      <article class="stat-card"><span class="stat-label">等待条件</span><div class="stat-value">{{ fmt(snapshot?.stats.wait_count, 0) }}</div><span class="stat-foot">保留观察，不强制产生信号</span><span class="stat-symbol">◷</span></article>
      <article class="stat-card"><span class="stat-label">模拟总资产</span><div class="stat-value money">{{ money(snapshot?.portfolio.equity) }}</div><span class="stat-foot">累计模拟收益 {{ signed(totalPnl) }} 元</span><span class="stat-symbol">¥</span></article>
    </div>
    <div class="research-grid">
      <section class="panel watch-panel"><div class="panel-heading"><div><h2>股票观察列表 <span class="count-badge">{{ visible.length }}</span></h2><p>评分用于排序，不代表上涨概率</p></div><div class="legend"><i class="up-dot"></i>涨<i class="down-dot"></i>跌</div></div>
        <div class="toolbar"><div class="filter-group" role="group" aria-label="观察状态"><button v-for="item in [{ key: 'all', name: '全部' }, { key: 'watch', name: '值得观察' }, { key: 'wait', name: '等待条件' }]" :key="item.key" class="filter" :class="{ active: filter === item.key }" :aria-pressed="filter === item.key" @click="filter = item.key">{{ item.name }}</button></div><label class="sort-label">排序<select v-model="sort" aria-label="观察列表排序"><option value="score">研究评分 ↓</option><option value="change">日涨跌幅 ↓</option><option value="code">股票代码 ↑</option></select></label></div>
        <div class="table-wrap"><table class="watch-table"><thead><tr><th>股票 / 代码</th><th class="num">收盘价</th><th class="num">日涨跌</th><th class="num">研究评分</th><th>研究状态</th></tr></thead><tbody><tr v-for="row in visible" :key="row.stock.code" class="watch-row" :class="{ selected: row.stock.code === selected }" tabindex="0" :aria-label="`查看${row.stock.name}的研究详情`" @click="selected = row.stock.code" @keydown.enter="selected = row.stock.code" @keydown.space.prevent="selected = row.stock.code"><td><span class="stock-name">{{ row.stock.name || row.stock.code }}</span><span class="stock-code">{{ row.stock.code }} · {{ exchangeName(row.stock.exchange) }}</span></td><td class="num">{{ fmt(row.price) }}</td><td class="num" :class="color(row.change)">{{ pct(row.change) }}</td><td class="num"><span class="score">{{ fmt(row.analysis.score, 0) }}</span><span class="score-track"><i :style="{ width: `${Math.max(0, Math.min(100, row.analysis.score ?? 0))}%` }"></i></span></td><td><span class="badge" :class="row.analysis.status">{{ statusNames[row.analysis.status] }}</span></td></tr><tr v-if="!visible.length"><td colspan="5" class="empty">{{ snapshot ? '当前筛选下没有股票。没有满足条件的观察对象是正常结果。' : '正在连接本地服务，获取研究快照…' }}</td></tr></tbody></table></div>
        <div class="panel-footer"><span>{{ visible.length }} 只股票 · 点击行查看研究依据</span><span class="muted">人民币 · 日线</span></div>
      </section>
      <section class="panel detail-panel"><div class="panel-heading detail-heading"><div><div class="eyebrow">{{ detail ? `${detail.stock.code} · ${exchangeName(detail.stock.exchange)} · ${detail.stock.sector || '日线研究'}` : 'DAILY CHART' }}</div><h2>{{ detail?.stock.name ?? '暂无观察股票' }}</h2></div><div class="detail-price"><strong>{{ fmt(detail?.price) }}</strong><span :class="color(detail?.change)">{{ pct(detail?.change) }} 日涨跌</span></div></div>
        <StockChart :candles="detail?.stock.candles ?? []"/>
        <div class="chart-disclaimer">{{ snapshot?.app.mode === 'demo' ? '合成行情 · 非真实股价' : `${detail?.stock.adjustment === 'qfq' ? '前复权分析日线' : '日线行情'} · 不是盘中实时成交价` }} · 数据截至 {{ detail?.stock.data_date ?? '—' }}</div>
        <div class="indicator-grid"><div><span>EMA 20</span><strong>{{ fmt(indicators.ema20) }}</strong></div><div><span>RSI 14</span><strong>{{ fmt(indicators.rsi14, 1) }}</strong></div><div><span>MACD 柱</span><strong :class="color(indicators.macd_hist)">{{ signed(indicators.macd_hist, 3) }}</strong></div></div>
        <div class="analysis-summary"><div class="summary-label"><span>研究判断</span><span class="badge" :class="detail?.analysis.status ?? 'neutral'">{{ detail ? statusNames[detail.analysis.status] : '等待数据' }}</span></div><p>{{ detail?.analysis.route ? (routeNames[detail.analysis.route] ?? detail.analysis.route) + '：' : '' }}{{ detail?.stock.error || detail?.analysis.reasons.join('；') || '暂无可用研究判断。' }}</p></div>
        <div class="scenario"><div class="summary-label"><span>研究情景</span><span class="muted">非订单、非收益承诺</span></div><div class="scenario-grid"><div><span>参考价</span><strong>{{ fmt(plan?.reference_price) }}</strong></div><div><span>风险参考</span><strong>{{ fmt(plan?.stop_price) }}</strong></div><div><span>目标参考</span><strong>{{ fmt(plan?.target_price) }}</strong></div></div><p v-if="plan">{{ plan.note || '用于比较潜在上行与下行的研究情景，不保证触及这些价格。' }} 目标距离 {{ pct(plan.expected_gain_pct) }} · 风险距离 {{ fmt(Math.abs(plan.risk_pct)) }}%</p><p v-else>数据或条件不足，暂不生成情景价格。此处为空不代表系统会自动下单。</p></div>
      </section>
    </div>
    <div class="research-notes"><span class="note-icon">◎</span><div><strong>先验证，再决定</strong><p>示例策略只用于研究。评分、技术指标和情景目标不能保证盈利；真实成交还受交易制度、停牌、流动性和费用影响。</p></div><a href="#settings">查看规则 →</a></div>
  </section>
</template>
