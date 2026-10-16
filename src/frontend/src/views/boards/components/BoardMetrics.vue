<script setup lang="ts">
import { computed } from 'vue'
import metricFrame from '@/assets/boards/metric-frame.png'
import type { BoardMetric } from '@/types/board'

const props = defineProps<{ items: BoardMetric[] }>()
const metrics = computed(() => props.items.map(item => {
  const value = String(item.value)
  const unit = value.endsWith('%') ? '%' : ''
  const amount = unit ? value.slice(0, -1) : value
  return { ...item, amount, unit, compact: amount.length > 6 }
}))
</script>

<template>
  <section class="board-metrics" aria-label="关键指标，模拟数据">
    <article v-for="item in metrics" :key="item.label" class="board-metric">
      <img class="board-metric-frame" :src="metricFrame" alt="" />
      <span class="board-metric-label">{{ item.label }}</span>
      <strong class="board-metric-value" :class="[`board-tone-${item.tone}`, { 'is-compact': item.compact }]">
        {{ item.amount }}<span v-if="item.unit" class="board-metric-unit">{{ item.unit }}</span>
      </strong>
      <span v-if="item.comparison" class="board-comparison">
        <span class="board-comparison-label">较昨日</span>
        <b class="board-comparison-value" :class="item.comparison.includes('↓') ? 'board-tone-red' : 'board-tone-green'">{{ item.comparison }}</b>
      </span>
      <i class="board-metric-decoration" aria-hidden="true">
        <span class="board-metric-slash" />
        <span class="board-metric-slash" />
        <span class="board-metric-slash" />
      </i>
    </article>
  </section>
</template>
