<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Candle } from '../types'
import { fmt } from '../format'
const props = defineProps<{ candles: Candle[] }>()
const hover = ref<number | null>(null)
const points = computed(() => {
  let ema = props.candles[0]?.close ?? 0
  return props.candles.filter(c => [c.open, c.high, c.low, c.close].every(Number.isFinite)).map((c, index) => {
    ema = index ? c.close * (2 / 21) + ema * (19 / 21) : c.close
    return { ...c, ema }
  }).slice(-50)
})
const extent = computed(() => {
  const low = Math.min(...points.value.map(c => Math.min(c.low, c.ema)))
  const high = Math.max(...points.value.map(c => Math.max(c.high, c.ema)))
  const padding = Math.max((high - low) * 0.12, high * 0.005, .001)
  return { min: low - padding, max: high + padding }
})
const x = (index: number) => 13 + 530 / points.value.length * (index + .5)
const y = (value: number) => 13 + (extent.value.max - value) / (extent.value.max - extent.value.min) * 167
const width = computed(() => Math.max(2, Math.min(8, 530 / points.value.length * .58)))
const maxVolume = computed(() => Math.max(1, ...points.value.map(c => c.volume)))
const emaPath = computed(() => points.value.map((c, i) => `${i ? 'L' : 'M'}${x(i)},${y(c.ema)}`).join(' '))
const ticks = computed(() => [...new Set([0, Math.floor(points.value.length / 3), Math.floor(points.value.length * 2 / 3), points.value.length - 1])])
const selected = computed(() => hover.value === null ? null : points.value[hover.value])
function pointer(event: PointerEvent) {
  const bounds = (event.currentTarget as SVGSVGElement).getBoundingClientRect()
  hover.value = Math.max(0, Math.min(points.value.length - 1, Math.floor(((event.clientX - bounds.left) / bounds.width * 600 - 13) / 530 * points.value.length)))
}
</script>

<template>
  <div class="chart-meta"><div><span class="chart-label">日 K</span><span class="line-key"></span>EMA 20</div><span>{{ points[0]?.date ?? '暂无行情' }} <template v-if="points.length">— {{ points.at(-1)?.date }}</template></span></div>
  <div class="chart-shell">
    <svg id="price-chart" viewBox="0 0 600 248" role="img" aria-label="股票日线蜡烛图" @pointermove="pointer" @pointerleave="hover = null">
      <title>已收盘日线：红涨绿跌，金色线为 EMA 20，底部为成交量。</title>
      <text v-if="!points.length" x="300" y="120" text-anchor="middle" fill="#78838f">暂无有效日线数据</text>
      <template v-else>
        <g v-for="i in 4" :key="`grid-${i}`"><line x1="12" x2="548" :y1="13 + (i - 1) / 3 * 167" :y2="13 + (i - 1) / 3 * 167" stroke="#edf1f0" stroke-dasharray="3 3"/><text x="555" :y="16 + (i - 1) / 3 * 167" font-size="9" fill="#98a5ac">{{ fmt(extent.max - (extent.max - extent.min) * (i - 1) / 3) }}</text></g>
        <g v-for="(c, i) in points" :key="c.date" :fill="c.close >= c.open ? '#c96c70' : '#4d9b83'" :stroke="c.close >= c.open ? '#c96c70' : '#4d9b83'">
          <line :x1="x(i)" :x2="x(i)" :y1="y(c.high)" :y2="y(c.low)" stroke-width="1"/>
          <rect :x="x(i) - width / 2" :y="Math.min(y(c.open), y(c.close))" :width="width" :height="Math.max(1.4, Math.abs(y(c.open) - y(c.close)))" rx=".5" stroke="none"/>
          <rect :x="x(i) - width / 2" :y="219 - Math.max(1, c.volume / maxVolume * 31)" :width="width" :height="Math.max(1, c.volume / maxVolume * 31)" opacity=".35" stroke="none"/>
        </g>
        <path :d="emaPath" fill="none" stroke="#c1a168" stroke-width="1.5"/>
        <text v-for="i in ticks" :key="i" :x="x(i)" y="240" :text-anchor="i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'" font-size="9" fill="#87959e">{{ points[i]?.date.slice(5) }}</text>
        <line v-if="hover !== null" :x1="x(hover)" :x2="x(hover)" y1="10" y2="220" stroke="#99b3bb" stroke-dasharray="3 3"/>
      </template>
    </svg>
    <div v-if="selected" class="chart-tooltip" :style="hover! > points.length / 2 ? { left: '15px' } : { right: '50px' }"><strong>{{ selected.date }}</strong><br>开 {{ fmt(selected.open) }} · 高 {{ fmt(selected.high) }}<br>低 {{ fmt(selected.low) }} · 收 {{ fmt(selected.close) }}<br>成交量 {{ fmt(selected.volume, 0) }} 股</div>
  </div>
</template>
