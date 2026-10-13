<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Candle, ChartPoint, Analysis } from '../types'
import { fmt } from '../format'
const props = defineProps<{ candles: Candle[]; series?: Analysis['chart_series'] }>()
const hover = ref<number | null>(null), range = ref('50')
const allPoints = computed(() => props.candles.map((c, i) => {
  const series = props.series
  const indicators = Array.isArray(series) ? series.find(row => row.date === c.date) ?? series[i] : series ? Object.fromEntries(Object.entries(series).map(([k, values]) => [k, values[i]])) as unknown as ChartPoint : undefined
  return { ...c, ema20: indicators?.ema20 ?? null, ema60: indicators?.ema60 ?? null, macd: indicators?.macd ?? null, macd_signal: indicators?.macd_signal ?? null, macd_hist: indicators?.macd_hist ?? null, rsi14: indicators?.rsi14 ?? null }
}).filter(c => [c.open, c.high, c.low, c.close].every(Number.isFinite)))
const points = computed(() => range.value === 'all' ? allPoints.value : allPoints.value.slice(-Number(range.value)))
watch(points, () => { hover.value = null })
const extent = computed(() => {
  const low = Math.min(...points.value.map(c => Math.min(c.low, c.ema20 ?? c.low, c.ema60 ?? c.low)))
  const high = Math.max(...points.value.map(c => Math.max(c.high, c.ema20 ?? c.high, c.ema60 ?? c.high)))
  const padding = Math.max((high - low) * .12, high * .005, .001)
  return { min: low - padding, max: high + padding }
})
const x = (i: number) => 13 + 530 / Math.max(1, points.value.length) * (i + .5)
const y = (value: number) => 13 + (extent.value.max - value) / (extent.value.max - extent.value.min) * 157
const width = computed(() => Math.max(.8, Math.min(8, 530 / Math.max(1,points.value.length) * .58)))
const maxVolume = computed(() => Math.max(1, ...points.value.map(c => c.volume)))
const macdMax = computed(() => Math.max(.00001, ...points.value.flatMap(c => [Math.abs(c.macd ?? 0), Math.abs(c.macd_signal ?? 0), Math.abs(c.macd_hist ?? 0)])))
const my = (n: number) => 259 - n / macdMax.value * 24
const ry = (n: number) => 355 - n * .5
function line(key: 'ema20' | 'ema60' | 'macd' | 'macd_signal' | 'rsi14', scale: (n:number)=>number) {
  let open = false
  return points.value.map((c, i) => {const v=c[key];if(v===null){open=false;return ''}const s=`${open?'L':'M'}${x(i)},${scale(v)}`;open=true;return s}).join(' ')
}
const ticks = computed(() => [...new Set([0, Math.floor(points.value.length / 2), points.value.length - 1])])
const selected = computed(() => hover.value === null ? null : points.value[hover.value])
function pointer(event: PointerEvent) { const bounds = (event.currentTarget as SVGSVGElement).getBoundingClientRect(); hover.value = Math.max(0, Math.min(points.value.length - 1, Math.floor(((event.clientX - bounds.left) / bounds.width * 600 - 13) / 530 * points.value.length))) }
</script>
<template>
  <div class="stock-chart"><div class="chart-meta"><div><span class="chart-label">日 K</span><span class="line-key"></span>EMA20 <span class="line-key purple"></span>EMA60</div><select v-model="range" aria-label="图表显示范围"><option value="50">最近 50 根</option><option value="120">最近 120 根</option><option value="all">全部日线</option></select></div>
  <div class="chart-shell"><svg id="price-chart" viewBox="0 0 600 382" role="img" aria-label="股票日线、成交量、MACD 与 RSI 图表" @pointermove="pointer" @pointerleave="hover = null"><title>红涨绿跌。所有指标与评分共用后端计算值。MACD 柱为 DIF 减 DEA。</title><text v-if="!points.length" x="300" y="120" text-anchor="middle" fill="#78838f">暂无有效日线数据</text><template v-else>
    <g v-for="i in 4" :key="i"><line x1="12" x2="548" :y1="13+(i-1)/3*157" :y2="13+(i-1)/3*157" stroke="#edf1f0" stroke-dasharray="3 3"/><text x="555" :y="16+(i-1)/3*157" font-size="9" fill="#98a5ac">{{ fmt(extent.max-(extent.max-extent.min)*(i-1)/3) }}</text></g>
    <g v-for="(c,i) in points" :key="c.date" :fill="c.close>=c.open?'#c96c70':'#4d9b83'" :stroke="c.close>=c.open?'#c96c70':'#4d9b83'"><line :x1="x(i)" :x2="x(i)" :y1="y(c.high)" :y2="y(c.low)" stroke-width="1"/><rect :x="x(i)-width/2" :y="Math.min(y(c.open),y(c.close))" :width="width" :height="Math.max(1,Math.abs(y(c.open)-y(c.close)))" stroke="none"/><rect :x="x(i)-width/2" :y="212-Math.max(1,c.volume/maxVolume*29)" :width="width" :height="Math.max(1,c.volume/maxVolume*29)" opacity=".4" stroke="none"/></g>
    <path :d="line('ema20',y)" fill="none" stroke="#c1a168" stroke-width="1.5"/><path :d="line('ema60',y)" fill="none" stroke="#9184c4" stroke-width="1.3"/>
    <text x="13" y="231" font-size="9" fill="#87959e">MACD · DIF/DEA</text><line x1="12" x2="548" y1="259" y2="259" stroke="#edf1f0"/>
    <template v-for="(c,i) in points" :key="`m${i}`"><rect v-if="c.macd_hist!==null" :x="x(i)-width/2" :y="Math.min(my(c.macd_hist),259)" :width="width" :height="Math.max(.4,Math.abs(my(c.macd_hist)-259))" :fill="c.macd_hist>=0?'#c96c70':'#4d9b83'" opacity=".7"/></template><path :d="line('macd',my)" fill="none" stroke="#629da6"/><path :d="line('macd_signal',my)" fill="none" stroke="#c1a168"/>
    <text x="13" y="303" font-size="9" fill="#87959e">RSI 14</text><g v-for="level in [30,70]" :key="level"><line x1="12" x2="548" :y1="ry(level)" :y2="ry(level)" stroke="#dfe6e3" stroke-dasharray="3 3"/><text x="555" :y="ry(level)+3" font-size="9" fill="#98a5ac">{{ level }}</text></g><path :d="line('rsi14',ry)" fill="none" stroke="#9184c4" stroke-width="1.3"/>
    <text v-for="i in ticks" :key="`t${i}`" :x="x(i)" y="377" :text-anchor="i===0?'start':i===points.length-1?'end':'middle'" font-size="9" fill="#87959e">{{ points[i]?.date }}</text><line v-if="hover!==null" :x1="x(hover)" :x2="x(hover)" y1="10" y2="356" stroke="#99b3bb" stroke-dasharray="3 3"/>
  </template></svg><div v-if="selected" class="chart-tooltip" :style="hover!>points.length/2?{left:'15px'}:{right:'50px',left:'auto'}"><strong>{{ selected.date }}</strong><br>开 {{ fmt(selected.open) }} · 高 {{ fmt(selected.high) }}<br>低 {{ fmt(selected.low) }} · 收 {{ fmt(selected.close) }}<br>EMA20 {{ fmt(selected.ema20) }} · EMA60 {{ fmt(selected.ema60) }}<br>MACD柱 {{ fmt(selected.macd_hist,3) }} · RSI {{ fmt(selected.rsi14,1) }}<br>成交量 {{ fmt(selected.volume,0) }} 股</div></div><p v-if="!series" class="form-help chart-disclaimer">指标序列尚未返回，仅显示价格与成交量。</p></div>
</template>
