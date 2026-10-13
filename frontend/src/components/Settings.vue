<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import type { Mode, Mutate, Settings } from '../types'
const props = defineProps<{ settings: Settings | null; busy: boolean; mutate: Mutate }>()
const hydrated = ref(false), dirty = ref(false), saving = ref(false), feedback = ref('')
const form = reactive({ mode: 'demo' as Mode, watchlist: '', refresh_seconds: 300, auto_refresh: true })
function hydrate(settings: Settings) {
  form.mode = settings.mode; form.watchlist = settings.watchlist.join(', ')
  form.refresh_seconds = settings.refresh_seconds; form.auto_refresh = settings.auto_refresh
  hydrated.value = true
}
watch(() => props.settings, value => { if (value && (!hydrated.value || !dirty.value)) hydrate(value) }, { immediate: true })
function edited() { if (hydrated.value) { dirty.value = true; feedback.value = '' } }
async function save() {
  if (!hydrated.value || props.busy || saving.value) return
  const watchlist = [...new Set(form.watchlist.split(/[\s,，;；]+/).filter(Boolean))]
  if (watchlist.length < 1 || watchlist.length > 12 || watchlist.some(code => !/^\d{6}$/.test(code))) { feedback.value = '请填写 1–12 个六位股票代码。'; return }
  if (!Number.isInteger(form.refresh_seconds) || form.refresh_seconds < 300 || form.refresh_seconds > 86400) { feedback.value = '刷新间隔须为 300–86400 秒的整数。'; return }
  saving.value = true
  try {
    if (await props.mutate('/api/settings', { mode: form.mode, watchlist, refresh_seconds: form.refresh_seconds, auto_refresh: form.auto_refresh }, '设置已保存，正在更新研究数据。演示账本保持独立。')) {
      dirty.value = false
      feedback.value = '设置已保存，演示账本保持独立。'
    }
  } finally { saving.value = false }
}
const descriptions: Record<Mode, string> = {
  demo: '使用确定性的合成日线，价格不是任何股票的真实行情。可提交模拟委托、推进演示日期，用来观察规则与账本。',
  eastmoney: '读取公开 A 股已收盘日线，不是逐笔实时行情。数据源失败直接显示，不替换成演示数据。本模式仅用于只读研究。',
  csv: '读取私有数据目录 imports/ 中的 CSV 日线，仅用于只读研究。字段格式和导入路径见项目 docs/DATA.md。',
}
</script>

<template>
  <section class="view" aria-label="数据与设置"><div class="page-heading"><div><div class="eyebrow">DATA & PREFERENCES</div><h1>清楚数据，也清楚边界<span class="heading-dot">.</span></h1><p>设置独立保存，切换数据模式不会清空演示账本。</p></div></div>
    <div class="settings-grid"><section class="panel"><div class="panel-heading"><h2>数据源与更新</h2><span class="badge neutral">本地设置</span></div><form id="settings-form" @submit.prevent="save" @input="edited" @change="edited"><fieldset :disabled="!hydrated || busy || saving"><label>数据模式<select id="settings-mode" v-model="form.mode"><option value="demo">离线演示 · 合成行情</option><option value="eastmoney">真实 A 股行情 · 公开数据源</option><option value="csv">本地 CSV · 只读研究</option></select></label><div class="mode-description">{{ descriptions[form.mode] }}</div><label>观察股票代码<textarea id="settings-watchlist" v-model="form.watchlist" rows="4" placeholder="600519, 000333, 600036" spellcheck="false" required></textarea></label><p class="form-help">1–12 个六位代码，用逗号、空格或换行分隔。已有持仓或委托的股票不能从列表移除。</p><div class="form-row"><label>刷新间隔（秒）<input id="settings-interval" v-model.number="form.refresh_seconds" type="number" min="300" max="86400" step="1" required></label><label class="checkbox-label"><input id="settings-auto" v-model="form.auto_refresh" type="checkbox"><span>自动更新数据</span></label></div><button class="button primary" id="save-settings" type="submit">{{ saving ? '正在保存…' : '保存设置并更新' }}</button><span v-if="dirty" class="dirty-label">有未保存的修改</span></fieldset><div class="inline-feedback" role="status">{{ hydrated ? feedback : '等待首次数据加载，设置暂不可编辑。' }}</div></form></section>
      <section class="panel rules-panel"><div class="panel-heading"><h2>研究与模拟规则</h2></div><dl class="rule-list"><div><dt>已收盘日线</dt><dd>仅用完成的日线计算指标；当日未收盘时，数据日期为最近有效收盘日。</dd></div><div><dt>研究评分</dt><dd>基于可解释的示例指标排序，不是胜率，也不自动触发委托。未进行盈利验证。</dd></div><div><dt>T+1 与数量规则</dt><dd>当天买入的普通股票下个交易日才可卖。申报数量按对应板块规则验证。</dd></div><div><dt>后续交易日撮合</dt><dd>委托在下一交易日开盘尝试一次，不在信号当根收盘成交。停牌、价格限制或缺数据导致未成交时，当日失效，不延续重试。</dd></div><div><dt>复权价格</dt><dd>前复权价格用于趋势分析；研究情景需要可靠的不复权参考价，不能将复权分析价视为当前成交报价。</dd></div><div><dt>费用与市场日历</dt><dd>模拟记录佣金、税费等成本。未知日历年份拒绝模拟交易；费率及覆盖范围详见项目文档。</dd></div><div><dt>账户接入边界</dt><dd>提供可扩展的券商适配接口，目前仅模拟适配器可操作。尚未连接具体券商，真实行情与 CSV 模式只读。</dd></div></dl><a class="rules-link" href="#brokers">查看券商接入状态 →</a></section>
    </div>
  </section>
</template>
