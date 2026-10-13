<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ResearchReport } from '../research-types'
import { money, pct } from '../format'
const props=defineProps<{points:ResearchReport['equity_curve']}>()
const hover=ref<number|null>(null)
const bounds=computed(()=>{const values=props.points.flatMap(p=>[p.equity,p.benchmark]).filter(Number.isFinite);const low=Math.min(...values),high=Math.max(...values),pad=Math.max((high-low)*.08,Math.abs(high)*.002,1);return{low:low-pad,high:high+pad}})
const x=(i:number)=>35+i/Math.max(1,props.points.length-1)*690
const y=(v:number)=>15+(bounds.value.high-v)/(bounds.value.high-bounds.value.low)*210
const path=(field:'equity'|'benchmark')=>props.points.map((p,i)=>`${i?'L':'M'}${x(i)},${y(p[field])}`).join(' ')
const selected=computed(()=>hover.value===null?null:props.points[hover.value])
function pointer(e:PointerEvent){const b=(e.currentTarget as SVGSVGElement).getBoundingClientRect();hover.value=Math.max(0,Math.min(props.points.length-1,Math.round(((e.clientX-b.left)/b.width*800-35)/690*(props.points.length-1))))}
</script>
<template><div class="equity-chart"><div class="chart-meta"><span><span class="line-key teal-line"></span> 策略净资产 <span class="line-key"></span> 股票池等权持有基准</span><span>人民币 · 未平仓按收盘估值</span></div><svg viewBox="0 0 800 280" role="img" aria-label="策略净资产与股票池基准曲线" @pointermove="pointer" @pointerleave="hover=null"><text v-if="!points.length" x="400" y="135" text-anchor="middle">暂无权益曲线</text><template v-else><g v-for="i in 4" :key="i"><line x1="35" x2="725" :y1="15+(i-1)/3*210" :y2="15+(i-1)/3*210" stroke="#e7eeea"/><text x="733" :y="19+(i-1)/3*210" font-size="10" fill="#8b9b96">{{ Math.round(bounds.high-(bounds.high-bounds.low)*(i-1)/3).toLocaleString() }}</text></g><path :d="path('benchmark')" fill="none" stroke="#c1a168" stroke-width="1.5" stroke-dasharray="4 3"/><path :d="path('equity')" fill="none" stroke="#158c91" stroke-width="2"/><text x="35" y="251" font-size="11" fill="#87959e">{{ points[0]?.date }}</text><text x="725" y="251" text-anchor="end" font-size="11" fill="#87959e">{{ points.at(-1)?.date }}</text><line v-if="hover!==null" :x1="x(hover)" :x2="x(hover)" y1="15" y2="230" stroke="#99b3bb" stroke-dasharray="3 3"/></template></svg><p class="chart-readout" v-if="selected">{{ selected.date }} · 净资产 {{ money(selected.equity) }} · 现金 {{ money(selected.cash) }} · 回撤 {{ pct(selected.drawdown_pct) }} · 基准 {{ money(selected.benchmark) }}</p><p class="chart-readout" v-else>在曲线上移动指针，查看当日净资产、现金和回撤。</p></div></template>
