<script setup lang="ts">
import { computed } from 'vue'
import type { BomAttributeField } from '@/types/bomAttributes'

const props = withDefaults(defineProps<{
  fields?: BomAttributeField[] | null
  hideKeys?: string[]
}>(), { fields: () => [], hideKeys: () => [] })

const visibleFields = computed(() => (props.fields || []).filter(field => {
  const value = String(field?.value || '').trim()
  return value && !props.hideKeys.includes(field.key)
}))
</script>

<template>
  <ElTooltip v-if="visibleFields.length" placement="top-start" effect="light" :show-after="180" :teleported="true" popper-class="bom-attributes-tooltip">
    <template #content>
      <div class="bom-attribute-list">
        <div v-for="field in visibleFields" :key="field.key" class="bom-attribute-line"><span>{{ field.label }}：</span><b>{{ field.value }}</b></div>
      </div>
    </template>
    <span class="bom-attributes-anchor"><slot /></span>
  </ElTooltip>
  <span v-else><slot /></span>
</template>

<style scoped>
.bom-attributes-anchor { display: inline-flex; min-width: 0; max-width: 100%; }
.bom-attribute-line { display: flex; gap: 3px; line-height: 20px; white-space: nowrap; }
.bom-attribute-line span { color: var(--erp-color-text-secondary); }
.bom-attribute-line b { color: var(--erp-color-text-primary); font-weight: 500; }
</style>
