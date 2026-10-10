<script setup lang="ts">
import { computed } from 'vue'

import calendarIcon from '@/assets/workbench-icons/calendar.svg'
import tasksIcon from '@/assets/workbench-icons/tasks.svg'
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
</script>

<template>
  <article class="metric-card" :class="`metric-card--${item.tone}`" :aria-busy="loading">
    <template v-if="loading">
      <div class="metric-card__skeleton metric-card__skeleton--label" />
      <div class="metric-card__skeleton metric-card__skeleton--value" />
      <div class="metric-card__skeleton metric-card__skeleton--note" />
    </template>
    <template v-else>
      <div class="metric-card__heading">
        <span>{{ item.label }}</span>
        <span v-if="item.origin === 'DEMO'" class="demo-badge">演示数据</span>
        <span v-else-if="liveIcon" class="metric-card__icon"><img :src="liveIcon" alt="" /></span>
      </div>
      <strong>{{ item.value }}</strong>
      <p>{{ item.note }}</p>
    </template>
  </article>
</template>

<style scoped lang="scss">
.metric-card {
  position: relative;
  height: 106px;
  min-width: 0;
  padding: 14px 16px;
  overflow: hidden;
  border: 1px solid #e4e4e7;
  border-radius: 8px;
  background: #fff;
}

.metric-card__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #52525b;
  font-size: 13px;
  line-height: 18px;
}

.metric-card strong {
  display: block;
  margin-top: 4px;
  color: #18181b;
  font-size: 28px;
  font-weight: 700;
  line-height: 34px;
}

.metric-card p {
  margin: 1px 0 0;
  overflow: hidden;
  color: #71717a;
  font-size: 12px;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.metric-card--danger strong { color: #dc2626; }
.metric-card--warning strong { color: #d97706; }
.metric-card--success strong { color: #15803d; }

.demo-badge {
  flex: none;
  padding: 1px 6px;
  border-radius: 999px;
  color: #854d0e;
  background: #fef9c3;
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
  background: #eef6ff;
}

.metric-card__icon img { width: 20px; height: 20px; object-fit: contain; }

.metric-card__skeleton {
  border-radius: 4px;
  background: linear-gradient(90deg, #f4f4f5 25%, #e4e4e7 37%, #f4f4f5 63%);
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
</style>
