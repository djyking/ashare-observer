<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import Overview from './components/Overview.vue'
import Portfolio from './components/Portfolio.vue'
import History from './components/History.vue'
import Settings from './components/Settings.vue'
import BrokerAccess from './components/BrokerAccess.vue'
import Research from './components/Research.vue'
import { usePlatform } from './composables/usePlatform'

const platform = usePlatform()
const { snapshot, ready, loading, busy, demoReady, connectionError, feedback, feedbackError, load, mutate } = platform
const nav = [{ id: 'overview', label: '市场概览', icon: '▦' }, { id: 'portfolio', label: '模拟账本', icon: '▥' }, { id: 'research', label: '策略回放', icon: '↗' }, { id: 'history', label: '研究历史', icon: '◷' }, { id: 'settings', label: '数据与设置', icon: '⚙' }, { id: 'brokers', label: '券商接入', icon: '⇄' }]
const view = ref('overview'), clock = ref('')
const label = computed(() => nav.find(item => item.id === view.value)?.label ?? '市场概览')
const banner = computed(() => view.value === 'brokers' ? { title: '账户接入 · 只读验证', description: '示例账户明确标注虚构数据；真实券商需通过官方适配器接入，当前不提交买卖。', badge: 'CONNECT' } : view.value === 'research' ? { title: '独立历史策略研究', description: '每个实验使用自己的数据源，与观察看板、手动账本分离。请以报告标注的来源为准。', badge: 'REPLAY' } : !snapshot.value ? { title: '正在读取数据', description: '连接本地研究平台，获取最新研究快照。', badge: '—' } : snapshot.value.app.mode === 'demo' ? { title: '演示环境 · 合成行情', description: '价格不是实际股价；全部资金、委托和成交均为模拟。', badge: 'DEMO' } : { title: snapshot.value.app.mode === 'eastmoney' ? '真实行情 · 已收盘日线' : '本地 CSV · 只读研究', description: '研究结果不等于交易指令；账本保留独立演示数据，不使用当前行情计价。', badge: snapshot.value.app.mode === 'eastmoney' ? '日线' : 'CSV' })
const error = computed(() => connectionError.value || snapshot.value?.app.last_error)
let timer: ReturnType<typeof setTimeout> | undefined, clockTimer: ReturnType<typeof setInterval> | undefined
let disposed = false
function navigate() { const candidate = location.hash.replace(/^#/, '') || 'overview'; view.value = nav.some(item => item.id === candidate) ? candidate : 'overview' }
function updateClock() { clock.value = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date()) }
async function poll() {
  if (disposed) return
  if (!document.hidden || snapshot.value?.app.refreshing) await load()
  if (!disposed) timer = setTimeout(poll, snapshot.value?.app.refreshing ? 1800 : 10000)
}
function visible() { if (!document.hidden) void load() }
async function refresh() { if (!ready.value) await load(); else await mutate('/api/refresh', {}, '已请求更新，完成后将自动显示新快照。') }
onMounted(() => { navigate(); updateClock(); window.addEventListener('hashchange', navigate); document.addEventListener('visibilitychange', visible); clockTimer = setInterval(updateClock, 30000); void poll() })
onBeforeUnmount(() => { disposed = true; platform.dispose(); clearTimeout(timer); clearInterval(clockTimer); window.removeEventListener('hashchange', navigate); document.removeEventListener('visibilitychange', visible) })
</script>

<template>
  <aside class="sidebar"><a class="brand" href="#overview" aria-label="A 股量化交易研究平台首页"><span class="brand-mark"><svg viewBox="0 0 30 30" aria-hidden="true"><path d="M5 22V14m7 8V8m7 14V12m7 10V4"/></svg></span><span>A 股量化研究<small>QUANTITATIVE RESEARCH</small></span></a><div class="nav-label">工作空间</div><nav aria-label="主导航"><a v-for="item in nav" :key="item.id" class="nav-link" :class="{ active: view === item.id }" :href="`#${item.id}`" :aria-current="view === item.id ? 'page' : undefined"><span class="nav-icon">{{ item.icon }}</span>{{ item.label }}<span v-if="view === item.id" class="nav-dot"></span></a></nav><div class="sidebar-bottom"><span class="status-light"></span>独立本地工作空间<p>研究 · 观察 · 验证<br>实盘未连接</p><span class="version">Vue 3 · TypeScript<br>平台 {{ snapshot?.app.version ?? '1.2.0' }}</span></div></aside>
  <div class="workspace"><header class="topbar"><div class="breadcrumb">量化研究 <span>/</span> <strong>{{ label }}</strong></div><div class="topbar-right"><span class="session-chip">{{ snapshot?.session.label ?? (connectionError ? '连接失败' : '正在连接') }}{{ snapshot?.session.calendar_known === false ? ' · 日历未覆盖' : '' }}</span><span class="clock">{{ clock }}</span><button class="icon-button" id="refresh-top" :disabled="busy || (!ready && loading)" :class="{ busy }" title="重新采集行情" aria-label="重新采集行情" @click="refresh">↻</button></div></header>
    <main><div class="notice" :class="{ live: snapshot && snapshot.app.mode !== 'demo' }" role="status"><span class="notice-icon">i</span><div><strong>{{ banner.title }}</strong><span>{{ banner.description }}</span></div><span class="source-badge">{{ banner.badge }}</span></div><div v-if="error" class="error-banner" role="alert">{{ error }}</div>
      <Overview v-show="view === 'overview'" :snapshot="snapshot"/>
      <Portfolio v-show="view === 'portfolio'" :snapshot="snapshot" :enabled="demoReady" :active="view === 'portfolio'" :mutate="mutate"/>
      <Research v-show="view === 'research'" :snapshot="snapshot" :active="view === 'research'"/>
      <History v-show="view === 'history'" :active="view === 'history'" :revision="snapshot?.app.revision"/>
      <Settings v-show="view === 'settings'" :settings="snapshot?.settings ?? null" :busy="busy" :mutate="mutate" :csrf="snapshot?.csrf_token" :active="view === 'settings'"/>
      <BrokerAccess v-show="view === 'brokers'" :active="view === 'brokers'" :csrf="snapshot?.csrf_token"/>
      <footer class="page-footer"><span>A 股量化交易研究平台 <span class="footer-divider">/</span> 行情 · 研究 · 模拟</span><span>{{ view === 'research' ? '实验独立来源 · 详见报告' : snapshot?.app.source ?? '本地研究工具' }} · 不构成投资建议</span></footer>
    </main>
  </div>
  <div v-if="feedback" class="toast" :class="{ error: feedbackError }" role="status"><span>{{ feedback }}</span><button class="toast-close" type="button" aria-label="关闭消息" @click="feedback = ''">×</button></div>
</template>
