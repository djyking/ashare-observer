<script setup lang="ts">
import { ref, shallowRef, watch, onBeforeUnmount } from 'vue'
import Pagination from './Pagination.vue'
import { latestRequest, request } from '../api'
import { fmt, timeText, modeNames } from '../format'
import type { HistoryPage } from '../types'
const props = defineProps<{ active: boolean; revision?: number }>()
const history = shallowRef<HistoryPage>({ items: [], total: 0, page: 1, pages: 1, page_size: 30 })
const busy = ref(false), error = ref('')
const latest = latestRequest()
async function load(page = history.value.page) {
  const id = latest.next(); busy.value = true
  try {
    const result = await request<HistoryPage>(`/api/history?page=${page}&page_size=30`)
    if (latest.current(id)) { history.value = result; error.value = '' }
  } catch (cause) { if (latest.current(id)) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (latest.current(id)) busy.value = false }
}
watch(() => [props.active, props.revision], () => { if (props.active) void load() }, { immediate: true })
onBeforeUnmount(() => latest.invalidate())
const summary = (value: unknown) => typeof value === 'string' ? value : Array.isArray(value) ? value.join('；') : value ? JSON.stringify(value) : '本次扫描仅记录研究结果，没有自动委托。'
</script>

<template>
  <section class="view" aria-label="研究历史"><div class="page-heading"><div><div class="eyebrow">RESEARCH JOURNAL</div><h1>每一次观察，留下依据<span class="heading-dot">.</span></h1><p>按页读取，每页 30 条。研究记录与模拟成交分别展示。</p></div><button class="button secondary" :disabled="busy" @click="load()">{{ busy ? '正在加载…' : '刷新记录' }}</button></div><div v-if="error" class="error-banner" role="alert">{{ error }} 已保留上次结果。</div>
    <section class="panel"><div class="panel-heading"><h2>历史研究结果</h2><span class="muted">共 {{ history.total }} 条研究快照</span></div><div class="table-wrap"><table><thead><tr><th>研究时间</th><th>领先观察</th><th class="num">最高评分</th><th>观察 / 等待</th><th>快照详情</th></tr></thead><tbody><tr v-for="(item, i) in history.items" :key="item.id ?? `${item.created_at}-${i}`"><td>{{ timeText(item.created_at) }}<span class="stock-code">{{ modeNames[item.mode] ?? item.mode }} · 日线截至 {{ item.as_of }}</span></td><td>{{ item.top_name || item.top_code || '无领先观察' }}<span class="stock-code">{{ item.top_code || '—' }}</span></td><td class="num">{{ fmt(item.top_score, 0) }}</td><td><span class="badge watch">观察 {{ item.watch_count }}</span> <span class="badge wait">等待 {{ item.wait_count }}</span></td><td><details class="history-detail"><summary>展开依据</summary><p>{{ summary(item.summary) }}</p><p>数据源：{{ item.source || '—' }}<br>有效 / 总数：{{ item.valid_count }} / {{ item.stock_count }}</p></details></td></tr><tr v-if="!history.items.length"><td colspan="5" class="empty">{{ busy ? '正在读取历史…' : '还没有研究历史，完成扫描后会生成记录。' }}</td></tr></tbody></table></div><div class="panel-footer"><span>历史评分不代表实际投资收益</span><Pagination :page="history.page" :pages="history.pages" :busy="busy" label="研究历史分页" @change="load"/></div></section>
  </section>
</template>
