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
.workflow-status { border:1px solid color-mix(in srgb, currentColor 18%, transparent); }
</style>
