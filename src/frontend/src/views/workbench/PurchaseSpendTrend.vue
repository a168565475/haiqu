<script setup lang="ts">
import { computed } from 'vue'
import type { PurchaseSpendCurrency } from '@/types/purchaseWorkbench'

const props = defineProps<{ trend: PurchaseSpendCurrency['trend']; asOf: string; divisor: number; unit: string }>()
const series = computed(() => props.trend.filter(row => row.month <= Number(props.asOf.slice(5, 7))).map(row => ({
  ...row, value: row.line_count > 0 && row.line_count === row.unpriced_count ? null : Number(row.amount) / props.divisor,
})))
const highest = computed(() => series.value.filter(row => row.line_count > row.unpriced_count)
  .sort((a, b) => Number(b.amount) - Number(a.amount))[0])
const step = computed(() => {
  const target = (highest.value?.value ?? 0) / 3 || 1
  const base = 10 ** Math.floor(Math.log10(target))
  return ([1, 1.5, 2, 2.5, 5, 10].find(value => value * base >= target) ?? 10) * base
})
const left = 46, right = 572, bottom = 170, top = 25
const points = computed(() => series.value.map((row, i) => ({
  ...row, x: left + i * (right - left) / Math.max(1, series.value.length - 1),
  y: row.value === null ? null : bottom - row.value / (3 * step.value) * (bottom - top),
})))
const segments = computed(() => {
  const groups: { x: number; y: number }[][] = []
  let current: { x: number; y: number }[] = []
  for (const point of points.value) {
    if (point.y === null) { current = []; continue }
    if (!current.length) groups.push(current)
    current.push({ x: point.x, y: point.y })
  }
  return groups.map(group => {
    const first = group[0]!, end = group[group.length - 1]!
    const line = group.map((p, i) => `${i ? 'L' : 'M'}${p.x},${p.y}`).join(' ')
    return { first, line, area: `${line} L${end.x},${bottom} L${first.x},${bottom} Z`, single: group.length === 1 }
  })
})
const last = computed(() => points.value[points.value.length - 1])
const display = (n: number) => n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
</script>

<template>
  <div v-if="last">
    <svg viewBox="0 0 620 218" role="img" :aria-label="`每月采购金额，单位${unit}，截至 ${asOf}`">
      <text x="7" y="13">{{ unit }}</text>
      <g v-for="i in 4" :key="i" :transform="`translate(0,${bottom - (i - 1) * (bottom - top) / 3})`">
        <line :x1="left" :x2="right" stroke="var(--erp-color-border-subtle)" />
        <text :x="left - 8" dy=".32em" text-anchor="end">{{ Number(((i - 1) * step).toPrecision(3)) }}</text>
      </g>
      <g v-for="s in segments" :key="s.first.x" class="trend-segment">
        <path :d="s.area" fill="#267f90" fill-opacity=".08" />
        <path :d="s.line" stroke="#17677b" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round" />
        <circle v-if="s.single && s.first.x !== last.x" :cx="s.first.x" :cy="s.first.y" r="2.4" fill="#17677b" />
      </g>
      <template v-if="last.y !== null && last.value !== null">
        <circle :cx="last.x" :cy="last.y" r="4" fill="var(--erp-color-surface)" stroke="#17677b" stroke-width="2" />
        <text :x="last.x" :y="last.y - 11" text-anchor="middle" fill="#17677b" font-weight="600">{{ display(last.value) }}</text>
      </template>
      <text v-for="p in points" :key="p.month" :x="p.x" y="192" text-anchor="middle"><title v-if="p.unpriced_count">{{ p.unpriced_count }} 项待计价</title>{{ p.month }}月</text>
      <text :x="last.x" y="211" text-anchor="middle" font-size="11">截至{{ Number(asOf.slice(8)) }}日</text>
    </svg>
    <div class="trend-notes">
      <div><span>{{ series.some(row => row.unpriced_count) ? '已计价最高月' : '本年最高月' }}</span><b>{{ highest?.value != null ? highest.month + ' 月 · ' + display(highest.value) + ' ' + unit : '—' }}</b></div>
      <div><span>{{ Number(asOf.slice(5, 7)) }} 月截至 {{ Number(asOf.slice(8)) }} 日</span><b>{{ last.value === null ? '待计价' : (last.unpriced_count ? '已计价 ' : '') + display(last.value) + ' ' + unit }}</b></div>
    </div>
  </div>
  <p v-else class="empty-trend">暂无采购走势</p>
</template>

<style scoped>
svg { display: block; width: 100%; max-height: 260px; margin-top: 14px; fill: var(--erp-color-text-secondary); font: 12px var(--erp-font-body); }
.trend-notes { display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding-top: 12px; border-top: 1px solid var(--erp-color-border-subtle); }
.trend-notes > div { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px; }
.trend-notes span,.empty-trend { color: var(--erp-color-text-secondary); font-size: 12px; }
.trend-notes b { font-weight: 600; font-size: 14px; }
</style>
