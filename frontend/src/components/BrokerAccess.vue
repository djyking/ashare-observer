<script setup lang="ts">
import { computed, ref, shallowRef, watch, onBeforeUnmount } from 'vue'
import { latestRequest, request } from '../api'
import { fmt, orderStatuses, timeText } from '../format'
import type { BrokerCatalog, BrokerConnection, BrokerField, BrokerProvider, BrokerQuery, BrokerRecord } from '../broker-types'

const props = defineProps<{active: boolean; csrf?: string}>()
const connection = shallowRef<BrokerConnection | null>(null), catalog = shallowRef<BrokerCatalog | null>(null)
const loading = ref(false), action = ref(''), error = ref(''), feedback = ref('')
const driverId = ref('demo'), values = ref<Record<string, string>>({}), touched = ref(new Set<string>())
const dirty = ref(false), queryBusy = ref(false), queryError = ref(''), queryTime = ref('')
const records = ref<Record<BrokerQuery, BrokerRecord[]>>({account: [], positions: [], orders: [], trades: []})
const selectedQuery = ref<'positions' | 'orders' | 'trades'>('positions')
const latest = latestRequest(), latestQuery = latestRequest()
const driver = computed(() => connection.value?.drivers.find(item => item.id === driverId.value))
const sameProfile = computed(() => driverId.value === connection.value?.profile.driver)
const connected = computed(() => connection.value?.state.status === 'connected')
const example = computed(() => connection.value?.state.provider_id === 'broker_demo')
const blocked = computed(() => loading.value || !!action.value)
const canConnect = computed(() => !!driver.value && sameProfile.value && !dirty.value && driver.value.fields.every(field => !field.required || (field.secret ? secretReady(field) : saved(field))))
const paper = computed(() => catalog.value?.providers.find(item => item.id === 'paper'))
const statusNames = {disconnected: '未连接', connecting: '正在连接', connected: '已连接 · 只读', error: '连接未通过'}
const queryNames: Record<BrokerQuery, string> = {account: '资金', positions: '持仓', orders: '委托', trades: '成交'}
const capabilityNames: Record<keyof BrokerProvider['capabilities'], string> = {account: '资金查询', positions: '持仓查询', orders: '委托查询', trades: '成交查询', place_order: '提交委托', cancel_order: '取消委托'}
const accountMetrics = [{key: 'equity', label: '总权益'}, {key: 'available_cash', label: '可用资金'}, {key: 'frozen_cash', label: '冻结资金'}, {key: 'cash', label: '账户现金'}]

function clearSecrets() {
  for (const field of driver.value?.fields ?? []) if (field.secret) { values.value[field.key] = ''; touched.value.delete(field.key) }
}
function clearCredentials() {
  for (const field of driver.value?.fields ?? []) {
    if (field.secret || field.masked || connection.value?.profile.memory_only_fields?.includes(field.key)) { values.value[field.key] = ''; touched.value.delete(field.key) }
  }
}
function clearQueries() {
  latestQuery.invalidate(); records.value = {account: [], positions: [], orders: [], trades: []}
  queryError.value = ''; queryTime.value = ''; queryBusy.value = false
}
function hydrate() {
  driverId.value = connection.value?.profile.driver || 'demo'
  values.value = {...connection.value?.profile.fields}; touched.value = new Set(); dirty.value = false
}
function changeDriver() {
  values.value = sameProfile.value ? {...connection.value?.profile.fields} : {}
  touched.value = new Set(); dirty.value = true; feedback.value = ''; error.value = ''
}
function changed(key: string) { touched.value.add(key); dirty.value = true; feedback.value = '' }
function saved(field: BrokerField) { return sameProfile.value && connection.value?.profile.saved_fields.includes(field.key) }
function secretReady(field: BrokerField) { return sameProfile.value && connection.value?.profile.secret_fields_ready.includes(field.key) }
function required(field: BrokerField) { return field.required && !(field.secret ? secretReady(field) : saved(field)) }
function placeholder(field: BrokerField) {
  if (field.secret && secretReady(field)) return '会话中已提供；更换时重新输入'
  if (saved(field) && connection.value?.profile.masked_fields[field.key]) return `已提供 ${connection.value.profile.masked_fields[field.key]}；留空保持`
  return field.placeholder || ''
}
function fillDemo() {
  driverId.value = 'demo'; changeDriver(); values.value.account_id = 'demo'; values.value.password = 'demo123'
  touched.value = new Set(['account_id', 'password']); feedback.value = '已填入公开的虚构账号，请先保存，再测试只读连接。'
}
async function loadQueries() {
  const provider = connection.value?.state.provider_id
  if (!connected.value || !provider) { clearQueries(); return }
  const id = latestQuery.next(); queryBusy.value = true; queryError.value = ''
  const kinds: BrokerQuery[] = ['account', 'positions', 'orders', 'trades']
  const results = await Promise.allSettled(kinds.map(kind => request<Record<string, unknown>>(`/api/brokers/${encodeURIComponent(provider)}/${kind}`)))
  if (!latestQuery.current(id)) return
  const next: Record<BrokerQuery, BrokerRecord[]> = {account: [], positions: [], orders: [], trades: []}, failures: string[] = []
  results.forEach((result, index) => {
    const kind = kinds[index]
    if (result.status === 'fulfilled') {
      const data = result.value[kind]
      next[kind] = kind === 'account' ? (data ? [data as BrokerRecord] : []) : (Array.isArray(data) ? data as BrokerRecord[] : [])
    } else failures.push(`${queryNames[kind]}：${result.reason instanceof Error ? result.reason.message : '读取失败'}`)
  })
  records.value = next; queryError.value = failures.join('；'); queryBusy.value = false; queryTime.value = new Date().toISOString()
}
async function load() {
  if (action.value) return
  const id = latest.next(); loading.value = true
  try {
    const [next, providers] = await Promise.all([request<BrokerConnection>('/api/broker/connection'), request<BrokerCatalog>('/api/brokers')])
    if (!latest.current(id)) return
    connection.value = next; catalog.value = providers; error.value = ''
    if (!dirty.value) hydrate()
    if (connected.value) await loadQueries(); else clearQueries()
  } catch (cause) { if (latest.current(id)) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (latest.current(id)) loading.value = false }
}
async function perform(operation: 'save' | 'connect' | 'disconnect') {
  if (blocked.value || !connection.value || !props.csrf) return
  if (operation === 'connect' && !canConnect.value) return
  let body: Record<string, unknown> = {}
  if (operation === 'save') {
    const fields: Record<string, string> = {}, secrets: Record<string, string> = {}
    for (const field of driver.value?.fields ?? []) if (touched.value.has(field.key)) (field.secret ? secrets : fields)[field.key] = values.value[field.key] ?? ''
    body = {driver: driverId.value, fields, secrets}
  }
  const id = latest.next(); action.value = operation; error.value = ''; feedback.value = ''; clearQueries()
  // Clear even on network or validation failures. No credentials enter browser storage.
  clearSecrets()
  try {
    const next = await request<BrokerConnection>(`/api/broker/connection/${operation}`, body, props.csrf)
    if (!latest.current(id)) return
    connection.value = next; hydrate()
    feedback.value = operation === 'save' ? '配置已保存，尚未验证连接。账号和密码仅保留在服务会话中，重启或断开后需重新填写。' : operation === 'connect' ? next.state.message : '连接已断开，会话账号与密码已清除。'
    if (connected.value) await loadQueries()
    try { const providers = await request<BrokerCatalog>('/api/brokers'); if (latest.current(id)) catalog.value = providers } catch { /* Connection state is still valid. */ }
  } catch (cause) {
    if (latest.current(id)) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      try { const next = await request<BrokerConnection>('/api/broker/connection'); if (latest.current(id)) connection.value = next }
      catch { /* Keep the original request error visible. */ }
    }
  } finally { if (latest.current(id)) action.value = '' }
}
watch(() => props.active, active => { if (active) void load(); else clearCredentials() }, {immediate: true})
onBeforeUnmount(() => { latest.invalidate(); latestQuery.invalidate(); clearCredentials() })
</script>

<template>
  <section class="view" aria-label="券商接入">
    <div class="page-heading"><div><div class="eyebrow">BROKER CONNECTION</div><h1>从账户配置，到连接验证<span class="heading-dot">.</span></h1><p>填写账号与接口凭据，先用离线示例体验完整查询流程。</p></div><button class="button secondary" :disabled="blocked" @click="load">{{ loading ? '正在检查…' : '刷新接入状态' }}</button></div>
    <div v-if="error" class="error-banner" role="alert">{{ error }}</div>
    <div class="broker-status notice"><span class="notice-icon">i</span><div><strong>当前为只读接入</strong><span>离线示例可演示资金、持仓、委托和成交；真实券商还需安装适配器并开通权限。保存账号不代表已经连接。</span></div></div>
    <div class="broker-connect-grid">
      <section class="panel"><div class="panel-heading"><div><div class="eyebrow">01 / CONFIGURE</div><h2>配置账户</h2></div><span class="badge neutral">凭据仅当前会话</span></div>
        <form id="broker-connection-form" class="panel-body" autocomplete="off" @submit.prevent="perform('save')"><fieldset :disabled="blocked || !connection || !csrf">
          <label for="broker-driver">接入方式<select id="broker-driver" v-model="driverId" @change="changeDriver"><option v-for="item in connection?.drivers ?? []" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
          <div class="mode-description">{{ driver?.description }}<span v-if="driver && !driver.available" class="broker-unavailable">当前未安装具体 SDK／适配器；可保存接入资料，暂不能验证真实账户。</span></div>
          <button v-if="driver?.id === 'demo'" id="broker-fill-demo" type="button" class="button secondary broker-demo-fill" @click="fillDemo">填入虚构演示账号</button>
          <label v-for="field in driver?.fields ?? []" :key="`${driverId}:${field.key}`" :for="`broker-${field.key}`">{{ field.label }}
            <input :id="`broker-${field.key}`" v-model="values[field.key]" :type="field.secret ? 'password' : 'text'" :autocomplete="field.secret ? 'new-password' : 'off'" :required="required(field)" :placeholder="placeholder(field)" :maxlength="field.max_length ?? 128" spellcheck="false" autocapitalize="off" @input="changed(field.key)">
            <small v-if="saved(field) && connection?.profile.masked_fields[field.key]">会话已提供：{{ connection.profile.masked_fields[field.key] }}。不改动则保留；输入新账号会替换。</small>
            <small v-if="field.secret">{{ secretReady(field) ? '会话中已提供，不代表认证成功。重启服务后需再填写。' : '密码不写入文件或浏览器存储；断开连接后清除。' }}</small>
          </label>
          <div class="action-row"><button id="broker-save" class="button primary" type="submit">{{ action === 'save' ? '正在保存…' : '保存配置' }}</button><span v-if="dirty" class="dirty-label">尚未保存</span></div>
          <p class="form-help broker-form-note">保存会断开旧连接。账号、密码只保留本次服务会话，断开或重启后需重填；密码输入提交后立即清空。</p>
        </fieldset><div v-if="feedback" class="inline-feedback success" role="status">{{ feedback }}</div><div v-if="!csrf" class="inline-feedback">等待本地服务会话建立后可保存。</div></form>
      </section>
      <section class="panel"><div class="panel-heading"><div><div class="eyebrow">02 / VERIFY</div><h2>验证只读连接</h2></div><span id="broker-connection-status" class="badge" :class="connected ? 'watch' : connection?.state.status === 'error' ? 'unavailable' : 'neutral'">{{ connection ? statusNames[connection.state.status] : '正在读取' }}</span></div><div class="panel-body">
        <ol class="broker-steps"><li><strong>保存账户资料</strong><span>选择接入方式并填写所需字段。账号与密码是否可用，要在下一步验证。</span></li><li><strong>测试只读连接</strong><span>只查询账户，不提交买卖。离线示例接受 demo / demo123，返回固定的虚构账户。</span></li><li><strong>查看查询结果</strong><span>资金、持仓、委托和成交分别显示。真实 SDK 接入后，也使用相同界面。</span></li></ol>
        <div class="broker-connection-state"><strong>{{ connection?.state.message || '正在读取连接配置…' }}</strong><small>最近验证：{{ timeText(connection?.state.last_checked_at) }}</small><small v-if="dirty">有未保存的修改，请先保存后再连接。</small><small v-else-if="!canConnect">请先填写并保存必填的账户资料。</small></div>
        <div class="action-row"><button id="broker-connect" class="button primary" :disabled="blocked || !connection || !csrf || !canConnect" @click="perform('connect')">{{ action === 'connect' ? '正在验证…' : '测试只读连接' }}</button><button id="broker-disconnect" class="button secondary" :disabled="blocked || !connection || !csrf" @click="perform('disconnect')">断开并清除会话凭据</button></div>
        <div v-if="paper" class="broker-paper-link"><div><strong>原有模拟账本</strong><span>{{ paper.connected ? '独立可用' : '当前不可用' }} · 与本页示例账户分开</span></div><a href="#portfolio" class="button secondary">打开模拟账本 →</a></div>
      </div></section>
    </div>
    <section v-if="connected" class="panel block-panel broker-query-panel" aria-label="账户查询结果">
      <div class="panel-heading"><div><div class="eyebrow">03 / INSPECT</div><h2>{{ example ? '离线示例账户 · 全部为虚构数据' : '券商账户 · 只读查询' }}</h2><p>{{ example ? '数据不随市场变化，不代表真实资产，也不写入模拟账本。' : '来自已连接的券商适配器，当前只提供查询。' }}</p></div><button class="button secondary" :disabled="queryBusy || blocked" @click="loadQueries">{{ queryBusy ? '正在读取…' : '刷新账户数据' }}</button></div>
      <div v-if="queryError" class="error-banner broker-query-error" role="alert">{{ queryError }}</div>
      <div class="report-metrics"><article v-for="metric in accountMetrics" :key="metric.key"><span>{{ metric.label }}（元）</span><strong>{{ fmt(records.account[0]?.[metric.key]) }}</strong></article></div>
      <div class="toolbar"><div class="filter-group" aria-label="账户记录类型"><button v-for="kind in (['positions', 'orders', 'trades'] as const)" :key="kind" class="filter" :class="{active: selectedQuery === kind}" :aria-pressed="selectedQuery === kind" @click="selectedQuery = kind">{{ queryNames[kind] }} {{ records[kind].length }}</button></div><span class="muted">{{ example ? '虚构示例 · ' : '' }}读取于 {{ timeText(queryTime) }}</span></div>
      <div class="table-wrap broker-records"><table v-if="selectedQuery === 'positions'"><thead><tr><th>股票</th><th class="num">数量 / 可卖</th><th class="num">成本 / 参考价</th><th class="num">市值</th><th class="num">浮动盈亏</th></tr></thead><tbody><tr v-for="row in records.positions" :key="String(row.code)"><td><strong class="stock-name">{{ row.name || row.code }}</strong><span class="stock-code">{{ row.code }}</span></td><td class="num">{{ fmt(row.quantity, 0) }} / {{ fmt(row.sellable, 0) }}</td><td class="num">{{ fmt(row.avg_cost) }} / {{ fmt(row.last_price) }}</td><td class="num">{{ fmt(row.market_value) }}</td><td class="num">{{ fmt(row.unrealized_pnl) }}</td></tr></tbody></table>
        <table v-else-if="selectedQuery === 'orders'"><thead><tr><th>委托编号 / 日期</th><th>股票</th><th>方向 / 状态</th><th class="num">数量</th><th class="num">价格</th></tr></thead><tbody><tr v-for="row in records.orders" :key="String(row.id)"><td>{{ row.id }}<span class="stock-code">{{ row.created_date }}</span></td><td>{{ row.name || row.code }}<span class="stock-code">{{ row.code }}</span></td><td>{{ row.side === 'buy' ? '买入' : row.side === 'sell' ? '卖出' : '—' }} · {{ orderStatuses[String(row.status)] || row.status }}</td><td class="num">{{ fmt(row.quantity, 0) }}</td><td class="num">{{ fmt(row.limit_price ?? row.filled_price) }}</td></tr></tbody></table>
        <table v-else><thead><tr><th>成交编号 / 日期</th><th>股票</th><th>方向</th><th class="num">数量 / 价格</th><th class="num">成交金额</th><th class="num">费用</th></tr></thead><tbody><tr v-for="(row, index) in records.trades" :key="String(row.id ?? index)"><td>{{ row.id || '—' }}<span class="stock-code">{{ row.date }}</span></td><td>{{ row.name || row.code }}<span class="stock-code">{{ row.code }}</span></td><td>{{ row.side === 'buy' ? '买入' : row.side === 'sell' ? '卖出' : '—' }}</td><td class="num">{{ fmt(row.quantity, 0) }} / {{ fmt(row.price) }}</td><td class="num">{{ fmt(row.notional) }}</td><td class="num">{{ fmt(row.fee) }}</td></tr></tbody></table>
        <div v-if="!records[selectedQuery].length" class="empty">{{ queryBusy ? '正在查询…' : queryError ? '本次查询没有取得该类记录，请查看上方错误。' : '该账户暂无此类记录。' }}</div>
      </div>
    </section>
    <details class="panel block-panel broker-extension"><summary>接口能力与后续接入说明</summary><div class="broker-grid"><article v-for="provider in catalog?.providers ?? []" :key="provider.id" class="broker-card-content"><h2>{{ provider.name }}</h2><p>{{ provider.message }}</p><ul class="capability-list"><li v-for="(label, capability) in capabilityNames" :key="capability"><span>{{ label }}</span><strong :class="provider.capabilities[capability] ? 'teal' : 'muted'">{{ provider.capabilities[capability] ? '支持' : '未启用' }}</strong></li></ul></article></div><dl class="rule-list broker-rules"><div><dt>真正接入券商</dt><dd>选定券商和官方接口产品后，确认权限、费用、运行环境与登录方式；不是所有接口都使用账号密码。页面按适配器要求显示字段。</dd></div><div><dt>凭据与私有文件</dt><dd>账号与密码仅保留服务进程内存，页面只返回账号掩码；断开或重启后需重填。不进入 GitHub，也不写入浏览器存储。</dd></div><div><dt>扩展边界</dt><dd>已提供连接、查询、断开和统一账户模型；真实买卖尚未启用。<a href="https://github.com/djyking/ashare-quant-platform/blob/main/docs/BROKER_ADAPTER.md" target="_blank" rel="noopener noreferrer">查看开发者接入文档 →</a></dd></div></dl></details>
  </section>
</template>
