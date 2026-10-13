<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import Pagination from './Pagination.vue'
import PaperExperiments from './PaperExperiments.vue'
import { request, latestRequest } from '../api'
import type { Mutate, Snapshot, Page, PaperOrder, PaperTrade, OrderPreview } from '../types'
import { fmt, money, color, signed, orderStatuses } from '../format'
const props = defineProps<{ snapshot: Snapshot | null; enabled: boolean; mutate: Mutate; active?: boolean }>()
const code = ref(''), side = ref('buy'), quantity = ref(100), message = ref(''), submitting = ref(false)
const orderPage = ref(1), tradePage = ref(1)
const portfolio = computed(() => props.snapshot?.portfolio)
const orders = ref<Page<PaperOrder>>({items:[],total:0,page:1,pages:1,page_size:30}), trades = ref<Page<PaperTrade>>({items:[],total:0,page:1,pages:1,page_size:30})
const recordsBusy = ref(false), recordsError = ref(''), preview = ref<OrderPreview | null>(null), previewBusy = ref(false), previewError = ref('')
const orderPages = computed(()=>orders.value.pages), tradePages = computed(()=>trades.value.pages)
const orderSlice = computed(()=>orders.value.items), tradeSlice = computed(()=>trades.value.items)
const name = (value:string)=>props.snapshot?.stocks.find(stock=>stock.code===value)?.name??value
const recordGeneration=latestRequest(), previewGeneration=latestRequest()
let previewTimer:ReturnType<typeof setTimeout>|undefined
async function loadRecords(){
  if(!props.active)return
  const generation=recordGeneration.next();recordsBusy.value=true
  try{const result=await Promise.all([request<Page<PaperOrder>>(`/api/paper/records?kind=orders&page=${orderPage.value}`),request<Page<PaperTrade>>(`/api/paper/records?kind=trades&page=${tradePage.value}`)]);if(recordGeneration.current(generation)){[orders.value,trades.value]=result;recordsError.value=''}}catch(e){if(recordGeneration.current(generation))recordsError.value=e instanceof Error?e.message:String(e)}finally{if(recordGeneration.current(generation))recordsBusy.value=false}
}
async function loadPreview(){
  if(!props.enabled||!props.active||!code.value||!Number.isInteger(quantity.value)||quantity.value<1)return
  const generation=previewGeneration.next();previewBusy.value=true;previewError.value=''
  try{const result=await request<OrderPreview>('/api/paper/preview',{side:side.value,code:code.value,quantity:quantity.value},props.snapshot?.csrf_token);if(previewGeneration.current(generation))preview.value=result}catch(e){if(previewGeneration.current(generation))previewError.value=e instanceof Error?e.message:String(e)}finally{if(previewGeneration.current(generation))previewBusy.value=false}
}
watch(()=>props.snapshot?.stocks,stocks=>{if(stocks&&!stocks.some(stock=>stock.code===code.value))code.value=stocks[0]?.code??''},{immediate:true})
watch(()=>[props.active,props.snapshot?.app.revision,props.snapshot?.paper_experiment?.id,orderPage.value,tradePage.value],()=>{void loadRecords()},{immediate:true})
watch(()=>[props.active,props.enabled,code.value,side.value,quantity.value,props.snapshot?.app.revision],()=>{clearTimeout(previewTimer);previewGeneration.invalidate();preview.value=null;previewBusy.value=false;if(props.active)previewTimer=setTimeout(loadPreview,250)},{immediate:true})
onBeforeUnmount(()=>{clearTimeout(previewTimer);previewGeneration.invalidate();recordGeneration.invalidate()})
const totalFee=computed(()=>typeof preview.value?.fees==='object'&&preview.value.fees!==null?preview.value.fees.total??Object.values(preview.value.fees).reduce<number>((sum,v)=>sum+Number(v??0),0):preview.value?.fees)
// Retain an id after an ambiguous network failure, so retrying cannot duplicate an order.
let requestId = '', intent = ''
async function submit() {
  if (!props.enabled || submitting.value) return
  if (props.active && (!preview.value?.allowed || previewBusy.value)) { message.value = preview.value?.message || '请等待有效的委托预检查结果。'; return }
  if (!Number.isInteger(quantity.value) || quantity.value < 1 || !code.value) { message.value = '请输入有效股票和整数股数。'; return }
  const currentIntent = JSON.stringify([side.value, code.value, quantity.value, props.snapshot?.app.demo_date ?? props.snapshot?.app.as_of])
  if (!requestId || currentIntent !== intent) { requestId = `web-${crypto.randomUUID()}`; intent = currentIntent }
  submitting.value = true
  message.value = ''
  try {
    if (await props.mutate('/api/brokers/paper/orders', { side: side.value, code: code.value, quantity: quantity.value, request_id: requestId }, '模拟委托已记录，推进演示日期后尝试撮合。')) {
      message.value = '模拟委托已记录，尚未成交。推进演示日期后尝试撮合。'
      requestId = ''
      void loadRecords(); void loadPreview()
    }
  } finally { submitting.value = false }
}
</script>

<template>
  <section class="view" aria-label="模拟账本">
    <div class="page-heading"><div><div class="eyebrow">PAPER PORTFOLIO</div><h1>模拟账本<span class="heading-dot">.</span></h1><p>独立演示资金，委托在下一交易日开盘尝试撮合一次，不会提交真实订单。</p></div><button class="button primary" id="advance-day" :disabled="!enabled" @click="mutate('/api/demo/advance', {}, '正在推进演示交易日并尝试撮合模拟委托。')">推进一个演示交易日 →</button></div>
    <div class="stats-grid portfolio-stats"><article class="stat-card"><span class="stat-label">模拟总资产</span><div class="stat-value money">{{ money(portfolio?.equity) }}</div><span class="stat-foot">初始资金 {{ money(portfolio?.initial_cash) }}</span></article><article class="stat-card"><span class="stat-label">可用模拟资金</span><div class="stat-value money">{{ money(portfolio?.available_cash ?? portfolio?.cash) }}</div><span class="stat-foot">待成交预留 {{ money(portfolio?.frozen_cash ?? 0) }}</span></article><article class="stat-card"><span class="stat-label">已实现收益</span><div class="stat-value money" :class="color(portfolio?.realized_pnl)">¥ {{ signed(portfolio?.realized_pnl) }}</div><span class="stat-foot">已计入成交费用</span></article><article class="stat-card"><span class="stat-label">持仓浮动收益</span><div class="stat-value money" :class="color(portfolio?.unrealized_pnl)">¥ {{ signed(portfolio?.unrealized_pnl) }}</div><span class="stat-foot">累计费用 {{ money(portfolio?.fees) }}</span></article></div>
    <div class="portfolio-grid"><section class="panel"><div class="panel-heading"><div><h2>模拟持仓</h2><p>可卖数量遵循 T+1；没有持仓也是有效状态</p></div></div><div class="table-wrap"><table><thead><tr><th>股票</th><th class="num">持仓 / 可卖</th><th class="num">成本 / 现价</th><th class="num">市值</th><th class="num">浮动收益</th></tr></thead><tbody><tr v-for="p in portfolio?.positions ?? []" :key="p.code"><td><span class="stock-name">{{ p.name || p.code }}</span><span class="stock-code">{{ p.code }}</span></td><td class="num">{{ fmt(p.quantity, 0) }}<span class="stock-code">可卖 {{ fmt(p.sellable, 0) }}</span></td><td class="num">{{ fmt(p.avg_cost) }}<span class="stock-code">现价 {{ fmt(p.last_price) }}</span></td><td class="num">{{ money(p.market_value) }}</td><td class="num" :class="color(p.unrealized_pnl)">{{ signed(p.unrealized_pnl) }}</td></tr><tr v-if="!portfolio?.positions.length"><td colspan="5" class="empty">当前没有模拟持仓。提交模拟委托后，推进演示日期以尝试撮合。</td></tr></tbody></table></div></section>
      <section class="panel order-panel"><div class="panel-heading"><h2>新建模拟委托</h2><span class="badge neutral">仅演示</span></div><form id="order-form" @submit.prevent="submit"><fieldset :disabled="!enabled || submitting"><label for="order-code">股票</label><select id="order-code" v-model="code" required><option v-for="stock in snapshot?.stocks ?? []" :key="stock.code" :value="stock.code">{{ stock.name }} · {{ stock.code }}</option></select><div class="form-row"><label>方向<select id="order-side" v-model="side"><option value="buy">模拟买入</option><option value="sell">模拟卖出</option></select></label><label>数量（股）<input id="order-quantity" v-model.number="quantity" type="number" min="1" step="1" required></label></div><div v-if="enabled" class="order-preview" aria-live="polite"><p v-if="previewBusy">正在检查数量、费用与交易规则…</p><p v-else-if="previewError" class="error">{{ previewError }}</p><template v-else-if="preview"><p :class="preview.allowed ? 'teal' : 'error'">{{ preview.message || (preview.allowed ? '校验通过，可提交模拟委托' : '暂不可提交') }}</p><dl><div><dt>参考价 / 估算金额</dt><dd>{{ money(preview.reference_price) }} / {{ money(preview.estimated_notional) }}</dd></div><div><dt>预计费用 / 资金预留</dt><dd>{{ money(totalFee) }} / {{ money(preview.reserved_cash) }}</dd></div><div><dt>最小申报 / 增量</dt><dd>{{ preview.min_quantity }} / {{ preview.step }} 股</dd></div><div><dt>当前可卖 / 执行日可卖</dt><dd>{{ fmt(preview.sellable_now,0) }} / {{ fmt(preview.sellable_on_execution,0) }} 股</dd></div><div><dt>预计撮合日期</dt><dd>{{ preview.execute_after }}</dd></div></dl><p class="form-help">价格与费用为预估，模拟按下个交易日开盘价成交；此手动账本未额外计滑点。</p></template></div><p class="form-help">{{ snapshot?.app.mode === 'demo' ? '按板块校验申报数量和可用资金。下一交易日开盘尝试一次，未成交则当日失效。评分不会自动创建委托。' : '当前为只读研究模式。账本保留独立演示数据，不使用当前行情计价；切回离线演示后可操作。' }}</p><button class="button primary full" id="submit-order" type="submit" :disabled="active && (!preview?.allowed || previewBusy)">{{ submitting ? '处理中…' : '提交模拟委托' }}</button></fieldset><p class="inline-feedback" role="status">{{ message }}</p></form></section>
    </div>
    <div v-if="recordsError" class="error-banner">{{ recordsError }} <button class="cancel-order" @click="loadRecords">重试</button></div><section class="panel block-panel"><div class="panel-heading"><div><h2>模拟委托</h2><p>下一交易日开盘尝试一次；未成交则当日失效</p></div></div><div class="table-wrap"><table><thead><tr><th>日期</th><th>股票</th><th>方向</th><th class="num">数量</th><th>状态</th><th>说明</th><th></th></tr></thead><tbody><tr v-for="o in orderSlice" :key="o.id"><td>{{ o.created_date }}</td><td>{{ name(o.code) }}<span class="stock-code">{{ o.code }}</span></td><td :class="o.side === 'buy' ? 'up' : 'down'">{{ o.side === 'buy' ? '模拟买入' : '模拟卖出' }}</td><td class="num">{{ fmt(o.quantity, 0) }}</td><td><span class="badge" :class="o.status === 'pending' ? 'wait' : 'neutral'">{{ orderStatuses[o.status] ?? o.status }}</span></td><td class="order-note">{{ o.reason || '—' }}</td><td><button v-if="o.status === 'pending'" class="cancel-order" :disabled="!enabled" @click="mutate('/api/brokers/paper/cancel', { order_id: o.id }, '待成交模拟委托已取消。').then(() => loadRecords())">取消</button></td></tr><tr v-if="!orderSlice.length"><td colspan="7" class="empty">尚无模拟委托。观察评分不会自动创建委托。</td></tr></tbody></table></div><div class="panel-footer"><span>共 {{ orders.total }} 笔 · 每页 30 笔</span><Pagination :page="orderPage" :pages="orderPages" :busy="recordsBusy" label="模拟委托分页" @change="orderPage = $event"/></div></section>
    <section class="panel block-panel"><div class="panel-heading"><h2>模拟成交</h2><span class="muted">人民币 · 费用已记录</span></div><div class="table-wrap"><table><thead><tr><th>日期</th><th>股票</th><th>方向</th><th class="num">数量</th><th class="num">成交价</th><th class="num">费用</th><th class="num">已实现收益</th></tr></thead><tbody><tr v-for="(t, i) in tradeSlice" :key="t.id ?? `${t.date}-${i}`"><td>{{ t.date }}</td><td>{{ name(t.code) }}<span class="stock-code">{{ t.code }}</span></td><td :class="t.side === 'buy' ? 'up' : 'down'">{{ t.side === 'buy' ? '模拟买入' : '模拟卖出' }}</td><td class="num">{{ fmt(t.quantity, 0) }}</td><td class="num">{{ fmt(t.price) }}</td><td class="num">{{ fmt(t.fee) }}</td><td class="num" :class="color(t.pnl)">{{ signed(t.pnl) }}</td></tr><tr v-if="!tradeSlice.length"><td colspan="7" class="empty">尚无模拟成交。未成交委托不计入持仓或收益。</td></tr></tbody></table></div><div class="panel-footer"><span>共 {{ trades.total }} 笔 · 每页 30 笔</span><Pagination :page="tradePage" :pages="tradePages" :busy="recordsBusy" label="模拟成交分页" @change="tradePage = $event"/></div></section>
    <PaperExperiments :snapshot="snapshot" :active="!!active" :enabled="enabled" :mutate="mutate"/>
  </section>
</template>
