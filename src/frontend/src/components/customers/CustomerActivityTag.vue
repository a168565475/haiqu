<script setup lang="ts">
import { computed } from 'vue'

import type { CustomerActivitySummary } from '@/types/customer'

type CustomerTagTone = 'success' | 'info' | 'warning' | 'danger' | 'neutral'

const props = defineProps<{
  activity?: CustomerActivitySummary | null
  label?: string
  tone?: CustomerTagTone
  title?: string
}>()

const resolvedLabel = computed(() => props.label || props.activity?.display_name || '数据不足')
const resolvedTone = computed<CustomerTagTone>(() => {
  if (props.tone) return props.tone
  if (props.activity?.activity_status === 'ACTIVE') return 'success'
  if (props.activity?.activity_status === 'FOLLOW_UP') return 'info'
  if (props.activity?.activity_status === 'HIGH_RISK') return 'danger'
  return 'neutral'
})
const resolvedTitle = computed(() => props.title || props.activity?.reason || resolvedLabel.value)
</script>

<template>
  <span class="customer-activity-tag" :class="`is-${resolvedTone}`" :title="resolvedTitle">
    {{ resolvedLabel }}
  </span>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.customer-activity-tag {
  display: inline-flex;
  min-width: 56px;
  max-width: 100%;
  height: 24px;
  box-sizing: border-box;
  align-items: center;
  justify-content: center;
  padding: 0 8px;
  overflow: hidden;
  border: 1px solid var(--erp-tag-neutral-border);
  border-radius: token.$crm-radius-pill;
  color: var(--erp-tag-neutral-text);
  background: var(--erp-tag-neutral-background);
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.customer-activity-tag.is-success {
  border-color: var(--erp-tag-success-border);
  color: var(--erp-tag-success-text);
  background: var(--erp-tag-success-background);
}

.customer-activity-tag.is-info {
  border-color: var(--erp-tag-info-border);
  color: var(--erp-tag-info-text);
  background: var(--erp-tag-info-background);
}

.customer-activity-tag.is-warning {
  border-color: var(--erp-tag-warning-border);
  color: var(--erp-tag-warning-text);
  background: var(--erp-tag-warning-background);
}

.customer-activity-tag.is-danger {
  border-color: var(--erp-tag-danger-border);
  color: var(--erp-tag-danger-text);
  background: var(--erp-tag-danger-background);
}

.customer-activity-tag.is-neutral {
  border-color: var(--erp-tag-neutral-border);
  color: var(--erp-tag-neutral-text);
  background: var(--erp-tag-neutral-background);
}
</style>
