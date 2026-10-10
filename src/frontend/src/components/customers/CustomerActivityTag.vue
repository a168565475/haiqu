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
  border: 0;
  border-radius: token.$crm-radius-pill;
  color: #faf9f5;
  background: token.$crm-neutral;
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.customer-activity-tag.is-success {
  background: token.$crm-success;
}

.customer-activity-tag.is-info {
  background: token.$crm-info;
}

.customer-activity-tag.is-warning {
  background: token.$crm-warning;
}

.customer-activity-tag.is-danger {
  background: token.$crm-danger;
}

.customer-activity-tag.is-neutral {
  background: token.$crm-neutral;
}
</style>
