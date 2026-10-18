<script setup lang="ts">
import { computed } from 'vue'

import calendarIcon from '@/assets/workbench-icons/calendar.svg'
import tasksIcon from '@/assets/workbench-icons/tasks.svg'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import type { WorkbenchMetric } from '@/types/workbench'

const props = defineProps<{
  item: WorkbenchMetric
  loading?: boolean
}>()

const liveIcon = computed(() => {
  if (props.item.origin !== 'LIVE') return ''
  if (props.item.key === 'today') return calendarIcon
  if (props.item.key === 'overdue') return tasksIcon
  return ''
})
const liveIconStyle = computed(() => ({ maskImage: `url("${liveIcon.value}")` }))
</script>

<template>
  <article v-glass-spotlight.tilt class="metric-card" :class="`metric-card--${item.tone}`" :aria-busy="loading">
    <template v-if="loading">
      <div class="metric-card__skeleton metric-card__skeleton--label" />
      <div class="metric-card__skeleton metric-card__skeleton--value" />
      <div class="metric-card__skeleton metric-card__skeleton--note" />
    </template>
    <template v-else>
      <div class="metric-card__heading">
        <span>{{ item.label }}</span>
        <span v-if="item.origin === 'DEMO'" class="demo-badge">演示数据</span>
        <span v-else-if="liveIcon" class="metric-card__icon" aria-hidden="true"><span :style="liveIconStyle" /></span>
      </div>
      <strong>{{ item.value }}</strong>
      <p>{{ item.note }}</p>
    </template>
  </article>
</template>

<style scoped lang="scss">
@use '@/styles/workbench' as workbench;

.metric-card {
  @include workbench.glass-card;
  position: relative;
  height: 106px;
  min-width: 0;
  padding: 14px 16px;
}

.metric-card__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--erp-color-text-secondary);
  font-size: 13px;
  line-height: 18px;
}

.metric-card strong {
  display: block;
  margin-top: 4px;
  color: var(--erp-color-text-primary);
  font-size: 28px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 34px;
}

.metric-card p {
  margin: 1px 0 0;
  overflow: hidden;
  color: var(--erp-color-text-muted);
  font-size: 12px;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-card--danger strong { color: var(--erp-color-danger); }
.metric-card--warning strong { color: var(--erp-color-warning); }
.metric-card--success strong { color: var(--erp-color-success); }

.demo-badge {
  flex: none;
  padding: 1px 6px;
  border-radius: 999px;
  color: var(--erp-tag-extension-2-text);
  background: var(--erp-tag-extension-2-background);
  font-size: 10px;
  line-height: 16px;
}

.metric-card__icon {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 9px;
  background: var(--erp-color-selected);
}

.metric-card__icon > span { width: 20px; height: 20px; background: var(--erp-color-brand); mask-size: contain; mask-position: center; mask-repeat: no-repeat; }

.metric-card__skeleton {
  border-radius: 4px;
  background: linear-gradient(90deg, var(--erp-color-subtle) 25%, var(--erp-glass-inner-background) 37%, var(--erp-color-subtle) 63%);
  background-size: 400% 100%;
  animation: metric-loading 1.4s ease infinite;
}

.metric-card__skeleton--label { width: 72px; height: 14px; }
.metric-card__skeleton--value { width: 92px; height: 30px; margin-top: 9px; }
.metric-card__skeleton--note { width: 120px; height: 12px; margin-top: 8px; }

@keyframes metric-loading {
  0% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}

@media (prefers-reduced-motion: reduce), print {
  .metric-card__skeleton { animation: none; }
}
</style>
