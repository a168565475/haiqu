<script setup lang="ts">
import { computed } from 'vue'

import type { QuotationWorkflowStateDefinition } from '../workflow/quotationWorkflow'

const props = defineProps<{
  state: QuotationWorkflowStateDefinition
  detail?: string
}>()

const alertType = computed(() => ({
  INITIAL: 'info',
  PROCESSING: 'info',
  SUCCESS: 'success',
  FAILED: 'error',
  CONFLICT: 'error',
  RECOVERY: 'warning',
  EMPTY: 'info',
}[props.state.phase] as 'success' | 'warning' | 'info' | 'error'))
</script>

<template>
  <ElAlert
    class="workflow-status"
    :data-workflow-state="state.id"
    :title="state.title"
    :description="detail || state.description"
    :type="alertType"
    :closable="false"
    show-icon
  />
</template>

<style scoped lang="scss">
.workflow-status {
  min-height: 56px;
  height: auto;
  align-self: start;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, currentColor 18%, transparent);
}
.workflow-status :deep(.el-alert__icon) { margin-right: 8px; font-size: 16px; }
.workflow-status :deep(.el-alert__title) { font-size: 12px; font-weight: 500; line-height: 18px; }
.workflow-status :deep(.el-alert__description) { margin-top: 1px; font-size: 11px; line-height: 16px; }
</style>
