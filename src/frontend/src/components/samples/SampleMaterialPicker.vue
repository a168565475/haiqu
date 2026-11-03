<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import SampleCatalogSelection from './SampleCatalogSelection.vue'
import type { SampleMaterialCandidate, SampleMaterialCategory, SampleMaterialLine } from '@/types/sampleMaterial'
const props = defineProps<{ modelValue: boolean; category: SampleMaterialCategory; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; choose: [items: SampleMaterialCandidate[]] }>()
function emptyDraft(): SampleMaterialLine {
  return { key: 'selection', category: props.category, name: '', specification: '', material: '', color: '', quantity: '', unitId: '', unitLabel: '', notes: '',
    ...(props.category === 'tube' ? { pipeInputMode: 'TOTAL_METERS' as const } : {}) }
}
const draft = ref<SampleMaterialLine>(emptyDraft())
function selectionError() {
  const row = draft.value, selection = row.material_selection
  if (!row.material_catalog_id || !selection?.catalog_version || !row.name.trim()) return '请先选择品名'
  const required: [string, string][] = row.category === 'tube' ? [['shape', '管材类型'], ['section_size', '规格'], ['thickness', '厚度'], ['material', '材质']]
    : row.category === 'fabric' ? [['material', '材质'], ['fabric_spec', '面料规格'], ['width', '门幅'], ['color', '颜色']] : []
  const missing = required.filter(([key]) => !selection.attributes[key]?.trim()).map(([, label]) => label)
  if (missing.length) return `请选择${missing.join('、')}`
  if (!row.specification.trim()) return '请选择规格'
  if (!row.unitLabel) return '请选择本次数量单位'
  if (row.category === 'tube' && row.unitLabel !== '根') return '管材来源单位须为根，请重新选择品名'
  return ''
}
watch(() => [props.modelValue, props.category] as const, ([visible]) => { if (visible) draft.value = emptyDraft() })
function confirm() {
  if (props.disabled) return
  const error = selectionError()
  if (error) { ElMessage.warning(error); return }
  const row = draft.value
  emit('choose', [{ id: row.material_catalog_id!, number: '', name: row.name, specification: row.specification, material: row.material, color: row.color,
    unitId: row.unitId, unitLabel: row.unitLabel!, material_catalog_id: row.material_catalog_id,
    material_selection: JSON.parse(JSON.stringify(row.material_selection)) }])
  emit('update:modelValue', false)
}
</script>
<template>
  <AppWindowDialog :model-value="modelValue" class="sample-material-picker-dialog" title="选择材料" width="1100px" height="700px" append-to-body destroy-on-close :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <div class="material-picker">
      <SampleCatalogSelection v-if="modelValue" :key="category" v-model="draft" source="sample" :disabled="disabled" />
    </div>
    <template #footer><ElButton @click="emit('update:modelValue', false)">取消</ElButton><ElButton type="primary" :disabled="disabled" @click="confirm">添加材料</ElButton></template>
  </AppWindowDialog>
</template>
<style scoped lang="scss">
.material-picker { display: grid; flex: 1; min-height: 0; grid-template-rows: minmax(0, 1fr); }
.material-picker :deep(.sample-catalog-selection) { min-height: 0; }
.material-picker :deep(.material-selection-field) { height: 100%; min-height: 0; }
.material-picker :deep(.material-selection-field > div) { height: 100%; min-height: 0; }
.material-picker :deep(.material-selection) { box-sizing: border-box; height: 100%; min-height: 0; grid-template-rows: auto minmax(0, 1fr); gap: 0; }
.material-picker :deep(.selection-error) { grid-column: 1 / -1; grid-row: 1; }
.material-picker :deep(.catalog-names) { display: flex; flex-direction: column; grid-column: 1; grid-row: 2; min-height: 0; overflow: hidden; }
.material-picker :deep(.catalog-names > header), .material-picker :deep(.catalog-pages) { flex-shrink: 0; }
.material-picker :deep(.catalog-name-list) { flex: 1; min-height: 0; overflow-y: auto; }
.material-picker :deep(.attribute-groups) { grid-column: 2; grid-row: 2; grid-template-rows: repeat(var(--material-attribute-rows, 2), minmax(0, 1fr)); min-height: 0; overflow: hidden; align-content: stretch; padding: 12px; }
.material-picker :deep(.attribute-groups--four-columns) { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.material-picker :deep(.attribute-groups--seven:not(.attribute-groups--fabric-colors) > .attribute-group:last-of-type) { grid-column: span 2; }
.material-picker :deep(.attribute-group) { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.material-picker :deep(.group-values) { flex: 1; min-height: 0; }
.material-picker :deep(.attribute-value) { flex-shrink: 0; }
.material-picker :deep(.color-table-scroll) { flex: 1; max-height: none; }
.material-picker :deep(.selection-empty) { grid-column: 2; grid-row: 2; }
</style>
