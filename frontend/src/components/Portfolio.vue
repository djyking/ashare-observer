<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Pagination from './Pagination.vue'
import type { Mutate, Snapshot } from '../types'
import { fmt, money, color, signed, orderStatuses } from '../format'
const props = defineProps<{ snapshot: Snapshot | null; enabled: boolean; mutate: Mutate }>()
const code = ref(''), side = ref('buy'), quantity = ref(100), message = ref(''), submitting = ref(false)
const orderPage = ref(1), tradePage = ref(1)
const portfolio = computed(() => props.snapshot?.portfolio)
const orders = computed(() => [...(portfolio.value?.orders ?? [])].reverse())
const trades = computed(() => [...(portfolio.value?.trades ?? [])].reverse())
const orderPages = computed(() => Math.max(1, Math.ceil(orders.value.length / 30)))
const tradePages = computed(() => Math.max(1, Math.ceil(trades.value.length / 30)))
const orderSlice = computed(() => orders.value.slice((orderPage.value - 1) * 30, orderPage.value * 30))
const tradeSlice = computed(() => trades.value.slice((tradePage.value - 1) * 30, tradePage.value * 30))
const name = (value: string) => props.snapshot?.stocks.find(stock => stock.code === value)?.name ?? value
watch(() => props.snapshot?.stocks, stocks => { if (stocks && !stocks.some(stock => stock.code === code.value)) code.value = stocks[0]?.code ?? '' }, { immediate: true })
watch(orderPages, pages => { orderPage.value = Math.min(orderPage.value, pages) })
watch(tradePages, pages => { tradePage.value = Math.min(tradePage.value, pages) })
// Retain an id after an ambiguous network failure, so retrying cannot duplicate an order.
let requestId = '', intent = ''
async function submit() {
  if (!props.enabled || submitting.value) return
  if (!Number.isInteger(quantity.value) || quantity.value < 1 || !code.value) { message.value = '请输入有效股票和整数股数。'; return }
  const currentIntent = JSON.stringify([side.value, code.value, quantity.value, props.snapshot?.app.demo_date ?? props.snapshot?.app.as_of])
  if (!requestId || currentIntent !== intent) { requestId = `web-${crypto.randomUUID()}`; intent = currentIntent }
  submitting.value = true
  message.value = ''
  try {
    if (await props.mutate('/api/brokers/paper/orders', { side: side.value, code: code.value, quantity: quantity.value, request_id: requestId }, '模拟委托已记录，推进演示日期后尝试撮合。')) {
      message.value = '模拟委托已记录，尚未成交。推进演示日期后尝试撮合。'
      requestId = ''
    }
  } finally { submitting.value = false }
}
</script>

<template>
  <section class="view" aria-label="模拟账本">
    <div class="page-heading"><div><div class="eyebrow">PAPER PORTFOLIO</div><h1>模拟账本<span class="heading-dot">.</span></h1><p>独立演示资金，委托在下一交易日开盘尝试撮合一次，不会提交真实订单。</p></div><button class="button primary" id="advance-day" :disabled="!enabled" @click="mutate('/api/demo/advance', {}, '正在推进演示交易日并尝试撮合模拟委托。')">推进一个演示交易日 →</button></div>
    <div class="stats-grid portfolio-stats"><article class="stat-card"><span class="stat-label">模拟总资产</span><div class="stat-value money">{{ money(portfolio?.equity) }}</div><span class="stat-foot">初始资金 {{ money(portfolio?.initial_cash) }}</span></article><article class="stat-card"><span class="stat-label">可用模拟资金</span><div class="stat-value money">{{ money(portfolio?.available_cash ?? portfolio?.cash) }}</div><span class="stat-foot">待成交预留 {{ money(portfolio?.frozen_cash ?? 0) }}</span></article><article class="stat-card"><span class="stat-label">已实现收益</span><div class="stat-value money" :class="color(portfolio?.realized_pnl)">¥ {{ signed(portfolio?.realized_pnl) }}</div><span class="stat-foot">已计入成交费用</span></article><article class="stat-card"><span class="stat-label">持仓浮动收益</span><div class="stat-value money" :class="color(portfolio?.unrealized_pnl)">¥ {{ signed(portfolio?.unrealized_pnl) }}</div><span class="stat-foot">累计费用 {{ money(portfolio?.fees) }}</span></article></div>
    <div class="portfolio-grid"><section class="panel"><div class="panel-heading"><div><h2>模拟持仓</h2><p>可卖数量遵循 T+1；没有持仓也是有效状态</p></div></div><div class="table-wrap"><table><thead><tr><th>股票</th><th class="num">持仓 / 可卖</th><th class="num">成本 / 现价</th><th class="num">市值</th><th class="num">浮动收益</th></tr></thead><tbody><tr v-for="p in portfolio?.positions ?? []" :key="p.code"><td><span class="stock-name">{{ p.name || p.code }}</span><span class="stock-code">{{ p.code }}</span></td><td class="num">{{ fmt(p.quantity, 0) }}<span class="stock-code">可卖 {{ fmt(p.sellable, 0) }}</span></td><td class="num">{{ fmt(p.avg_cost) }}<span class="stock-code">现价 {{ fmt(p.last_price) }}</span></td><td class="num">{{ money(p.market_value) }}</td><td class="num" :class="color(p.unrealized_pnl)">{{ signed(p.unrealized_pnl) }}</td></tr><tr v-if="!portfolio?.positions.length"><td colspan="5" class="empty">当前没有模拟持仓。提交模拟委托后，推进演示日期以尝试撮合。</td></tr></tbody></table></div></section>
      <section class="panel order-panel"><div class="panel-heading"><h2>新建模拟委托</h2><span class="badge neutral">仅演示</span></div><form id="order-form" @submit.prevent="submit"><fieldset :disabled="!enabled || submitting"><label for="order-code">股票</label><select id="order-code" v-model="code" required><option v-for="stock in snapshot?.stocks ?? []" :key="stock.code" :value="stock.code">{{ stock.name }} · {{ stock.code }}</option></select><div class="form-row"><label>方向<select id="order-side" v-model="side"><option value="buy">模拟买入</option><option value="sell">模拟卖出</option></select></label><label>数量（股）<input id="order-quantity" v-model.number="quantity" type="number" min="1" step="1" required></label></div><p class="form-help">{{ snapshot?.app.mode === 'demo' ? '按板块校验申报数量和可用资金。下一交易日开盘尝试一次，未成交则当日失效。评分不会自动创建委托。' : '当前为只读研究模式。账本保留独立演示数据，不使用当前行情计价；切回离线演示后可操作。' }}</p><button class="button primary full" id="submit-order" type="submit">{{ submitting ? '处理中…' : '提交模拟委托' }}</button></fieldset><p class="inline-feedback" role="status">{{ message }}</p></form></section>
    </div>
    <section class="panel block-panel"><div class="panel-heading"><div><h2>模拟委托</h2><p>下一交易日开盘尝试一次；未成交则当日失效</p></div></div><div class="table-wrap"><table><thead><tr><th>日期</th><th>股票</th><th>方向</th><th class="num">数量</th><th>状态</th><th>说明</th><th></th></tr></thead><tbody><tr v-for="o in orderSlice" :key="o.id"><td>{{ o.created_date }}</td><td>{{ name(o.code) }}<span class="stock-code">{{ o.code }}</span></td><td :class="o.side === 'buy' ? 'up' : 'down'">{{ o.side === 'buy' ? '模拟买入' : '模拟卖出' }}</td><td class="num">{{ fmt(o.quantity, 0) }}</td><td><span class="badge" :class="o.status === 'pending' ? 'wait' : 'neutral'">{{ orderStatuses[o.status] ?? o.status }}</span></td><td class="order-note">{{ o.reason || '—' }}</td><td><button v-if="o.status === 'pending'" class="cancel-order" :disabled="!enabled" @click="mutate('/api/brokers/paper/cancel', { order_id: o.id }, '待成交模拟委托已取消。')">取消</button></td></tr><tr v-if="!orderSlice.length"><td colspan="7" class="empty">尚无模拟委托。观察评分不会自动创建委托。</td></tr></tbody></table></div><div class="panel-footer"><span>共 {{ orders.length }} 笔 · 每页 30 笔</span><Pagination :page="orderPage" :pages="orderPages" label="模拟委托分页" @change="orderPage = $event"/></div></section>
    <section class="panel block-panel"><div class="panel-heading"><h2>模拟成交</h2><span class="muted">人民币 · 费用已记录</span></div><div class="table-wrap"><table><thead><tr><th>日期</th><th>股票</th><th>方向</th><th class="num">数量</th><th class="num">成交价</th><th class="num">费用</th><th class="num">已实现收益</th></tr></thead><tbody><tr v-for="(t, i) in tradeSlice" :key="t.id ?? `${t.date}-${i}`"><td>{{ t.date }}</td><td>{{ name(t.code) }}<span class="stock-code">{{ t.code }}</span></td><td :class="t.side === 'buy' ? 'up' : 'down'">{{ t.side === 'buy' ? '模拟买入' : '模拟卖出' }}</td><td class="num">{{ fmt(t.quantity, 0) }}</td><td class="num">{{ fmt(t.price) }}</td><td class="num">{{ fmt(t.fee) }}</td><td class="num" :class="color(t.pnl)">{{ signed(t.pnl) }}</td></tr><tr v-if="!tradeSlice.length"><td colspan="7" class="empty">尚无模拟成交。未成交委托不计入持仓或收益。</td></tr></tbody></table></div><div class="panel-footer"><span>共 {{ trades.length }} 笔 · 每页 30 笔</span><Pagination :page="tradePage" :pages="tradePages" label="模拟成交分页" @change="tradePage = $event"/></div></section>
  </section>
</template>
