<script setup lang="ts">
import { ref, shallowRef, watch, onBeforeUnmount } from 'vue'
import { latestRequest, request } from '../api'
const props = defineProps<{ active: boolean }>()
interface Provider {
  id: 'paper' | 'live'; name: string; environment: 'paper' | 'live'; connected: boolean;
  capabilities: { account: boolean; positions: boolean; orders: boolean; trades: boolean; place_order: boolean; cancel_order: boolean };
  message: string;
}
interface Brokers { providers: Provider[]; live_enabled: boolean }
const data = shallowRef<Brokers | null>(null), busy = ref(false), error = ref('')
const latest = latestRequest()
const capabilityNames: Record<keyof Provider['capabilities'], string> = { account: '资金查询', positions: '持仓查询', orders: '委托查询', trades: '成交查询', place_order: '提交委托', cancel_order: '取消委托' }
async function load() {
  const id = latest.next(); busy.value = true
  try { const result = await request<Brokers>('/api/brokers'); if (latest.current(id)) { data.value = result; error.value = '' } }
  catch (cause) { if (latest.current(id)) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (latest.current(id)) busy.value = false }
}
watch(() => props.active, active => { if (active) void load() }, { immediate: true })
onBeforeUnmount(() => latest.invalidate())
</script>

<template>
  <section class="view" aria-label="券商接入"><div class="page-heading"><div><div class="eyebrow">BROKER ADAPTERS</div><h1>统一接口，清楚连接状态<span class="heading-dot">.</span></h1><p>以模拟适配器验证调用流程，为后续具体券商实现保留接入边界。</p></div><button class="button secondary" :disabled="busy" @click="load">{{ busy ? '正在检查…' : '刷新接入状态' }}</button></div>
    <div v-if="error" class="error-banner" role="alert">{{ error }}</div>
    <div class="broker-status notice"><span class="notice-icon">i</span><div><strong>{{ data?.live_enabled ? '检测到实盘启用标志' : '券商实盘未连接' }}</strong><span>当前不提供实盘操作控件。是否收费、资产门槛和运行环境，需由所选券商确认；本页面不收集账户凭据。</span></div></div>
    <div class="broker-grid"><article v-for="provider in data?.providers ?? []" :key="provider.id" class="panel broker-card"><div class="panel-heading"><div><div class="eyebrow">{{ provider.environment === 'paper' ? 'PAPER ADAPTER' : 'LIVE ADAPTER' }}</div><h2>{{ provider.name }}</h2></div><span class="badge" :class="provider.connected ? 'watch' : 'neutral'">{{ provider.connected ? (provider.environment === 'paper' ? '模拟可用' : '已连接') : '未连接' }}</span></div><div class="broker-card-content"><p>{{ provider.message }}</p><ul class="capability-list"><li v-for="(label, capability) in capabilityNames" :key="capability"><span>{{ label }}</span><strong :class="provider.capabilities[capability] ? 'teal' : 'muted'">{{ provider.capabilities[capability] ? '支持' : '未启用' }}</strong></li></ul><a v-if="provider.id === 'paper'" href="#portfolio" class="button secondary">打开模拟账本 →</a><div v-else class="mode-description">尚无已接入的具体券商。编写适配器并完成权限、对账与故障验证后，才能考虑启用实盘。</div></div></article><article v-if="!data" class="panel empty">{{ busy ? '正在读取接口状态…' : '暂未取得接口状态。' }}</article></div>
    <section class="panel block-panel"><div class="panel-heading"><h2>后续接入需要什么</h2><span class="muted">扩展接口已提供，具体厂商尚未适配</span></div><dl class="rule-list broker-rules"><div><dt>券商与官方权限</dt><dd>先确定券商和官方接口产品，再确认外部程序权限、费用、资产要求及模拟测试环境。并非所有证券账户都默认开放接口。</dd></div><div><dt>账户与成交一致性</dt><dd>适配器需要实现资金、持仓、委托、成交查询，处理订单状态、撤单、部分成交与对账。不能只实现一个“下单”请求。</dd></div><div><dt>凭据只留本地</dt><dd>账号、密码、密钥及证书应由本地私有配置或系统安全存储提供。仓库仅保留空白示例，页面与状态接口不返回凭据。</dd></div><div><dt>开发者接入文档</dt><dd>参见仓库 <a href="https://github.com/djyking/ashare-observer/blob/main/docs/BROKER_ADAPTER.md" target="_blank" rel="noopener noreferrer">docs/BROKER_ADAPTER.md</a>。模拟委托通过统一接口转交现有模拟账本，保持资金限制、T+1 和后续交易日撮合规则。</dd></div></dl></section>
  </section>
</template>
