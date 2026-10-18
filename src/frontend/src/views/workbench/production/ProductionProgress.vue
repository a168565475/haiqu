<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  label: string
  percentage: number | null
  status: string
  display?: string
  receipt?: boolean
}>()

const percentage = computed(() => props.status === 'READY' && props.percentage !== null && Number.isFinite(props.percentage)
  ? Math.max(0, Math.min(100, props.percentage))
  : null)
</script>

<template>
  <div class="pd-progress" :class="{ 'pd-progress--receipt': receipt }">
    <span class="pd-progress__label">{{ label }}</span>
    <template v-if="percentage !== null">
      <span class="pd-progress__track" role="progressbar" :aria-label="label" :aria-valuenow="percentage" :aria-valuemin="0" :aria-valuemax="100">
        <span class="pd-progress__fill" :style="{ width: `${percentage}%` }" />
      </span>
      <span class="pd-progress__value">{{ display || `${percentage}%` }}</span>
    </template>
    <span v-else class="pd-progress__unknown">{{ display || '—' }}</span>
  </div>
</template>

<style scoped lang="scss">
.pd-progress { display: grid; grid-template-columns: 58px minmax(24px, 1fr) 38px; align-items: center; gap: 7px; min-height: 20px; color: var(--erp-color-text-secondary); font-size: 11px; line-height: 18px; }
.pd-progress__track { height: 5px; overflow: hidden; border-radius: 5px; background: color-mix(in srgb, var(--erp-color-brand) 12%, transparent); }
.pd-progress__fill { display: block; height: 100%; border-radius: inherit; background: var(--erp-color-brand); }
.pd-progress--receipt .pd-progress__fill { background: var(--erp-color-success); }
.pd-progress__value { text-align: right; font-variant-numeric: tabular-nums; }
.pd-progress__unknown { grid-column: 2 / -1; color: var(--erp-color-text-muted); }
</style>
