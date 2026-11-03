<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { materialFieldOptions, materialFieldSelectionOnly, validateSampleMaterials } from '@/utils/sampleMaterial'
import { sampleMaterialCategories, type SampleMaterialLine, type SampleMaterialReferences, type SampleMaterialUnit } from '@/types/sampleMaterial'
import SampleCatalogSelection from './SampleCatalogSelection.vue'
import SampleMaterialFieldInput from './SampleMaterialFieldInput.vue'

const props = defineProps<{ modelValue: boolean; line: SampleMaterialLine; units: SampleMaterialUnit[]; references: SampleMaterialReferences | null; hasNext: boolean; canAddNext?: boolean; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; apply: [line: SampleMaterialLine, next: boolean]; 'dirty-change': [value: boolean] }>()
const draft = ref<SampleMaterialLine>({ ...props.line })
const initial = ref(''), error = ref(''), applying = ref(false)
let lastNext = 0
const fields = [{ key: 'name', label: '材料名称', required: true, max: 300 }, { key: 'specification', label: '规格', required: true, max: 500 }, { key: 'material', label: '材质', max: 500 }, { key: 'color', label: '颜色 / 色号', max: 500 }] as const
const dirty = computed(() => props.modelValue && JSON.stringify(draft.value) !== initial.value)
watch(() => [props.modelValue, props.line] as const, () => {
  if (!props.modelValue) return
  draft.value = JSON.parse(JSON.stringify(props.line)); initial.value = JSON.stringify(draft.value); error.value = ''
}, { immediate: true })
watch(dirty, value => emit('dirty-change', value), { immediate: true })
async function close() {
  if (applying.value) return
  if (dirty.value) {
    try { await ElMessageBox.confirm('本次放大编辑尚未应用到表格，关闭将放弃这些修改。', '放弃本次编辑？', { confirmButtonText: '放弃修改', cancelButtonText: '继续填写', type: 'warning' }) }
    catch { return }
  }
  emit('update:modelValue', false)
}
async function apply(next: boolean) {
  if (props.disabled || applying.value || (next && Date.now() - lastNext < 500)) return
  error.value = validateSampleMaterials({ lines: [draft.value], notes: '' }, props.units)
  if (error.value) return
  applying.value = true
  if (next) lastNext = Date.now()
  emit('apply', { ...draft.value }, next)
  await nextTick()
  applying.value = false
}
</script>
<template>
  <AppWindowDialog :model-value="modelValue" class="sample-material-line-dialog" :title="`${sampleMaterialCategories.find(item => item.key === line.category)?.label} · 放大编辑`" :width="draft.material_catalog_id ? 1100 : 600" destroy-on-close :close-on-click-modal="false" :before-close="close">
    <div class="material-line-drawer">
      <p class="drawer-help">核对材料和本次需求数量。应用后，填写完成再提交仓库。</p>
      <ElForm label-position="top" @submit.prevent>
        <div class="drawer-fields">
          <div v-if="draft.material_catalog_id" class="catalog-field"><SampleCatalogSelection :key="draft.key" v-model="draft" source="sample" :disabled="disabled || applying" /></div>
          <template v-else><ElFormItem v-for="field in fields" :key="field.key" :label="field.label" :required="'required' in field && field.required"><SampleMaterialFieldInput v-model="draft[field.key]" :options="materialFieldOptions(references, draft, field.key)" :selection-only="materialFieldSelectionOnly(draft, field.key)" :tube-specification="draft.category === 'tube' && field.key === 'specification'" :references="references" :label="`放大编辑${field.label}`" :placeholder="`填写${field.label}`" :maxlength="field.max" :disabled="disabled || applying || (!!draft.rawMaterialId && field.key !== 'color')" /></ElFormItem></template>
          <ElFormItem :label="draft.category === 'tube' ? '总需求米数' : '需求数量'" required><ElInput v-model="draft.quantity" aria-label="放大编辑需求数量" inputmode="decimal" maxlength="19" :disabled="disabled || applying"><template #append>{{ draft.category === 'tube' && draft.pipeInputMode === 'TOTAL_METERS' ? '米' : draft.unitLabel || '单位' }}</template></ElInput></ElFormItem>
          <ElFormItem v-if="!draft.material_catalog_id && draft.category !== 'tube'" label="单位" required><ElSelect v-model="draft.unitId" aria-label="放大编辑单位" filterable :disabled="disabled || applying"><ElOption v-for="unit in units" :key="unit.id" :label="unit.label" :value="unit.id" /></ElSelect></ElFormItem>
        </div>
        <ElFormItem label="备注"><ElInput v-model="draft.notes" aria-label="放大编辑备注" type="textarea" :rows="3" maxlength="2000" :disabled="disabled || applying" /></ElFormItem>
      </ElForm>
      <p v-if="error" role="alert" class="drawer-error">{{ error }}</p>
    </div>
    <template #footer><ElButton :disabled="applying" @click="close">取消</ElButton><ElButton :disabled="disabled || applying" @click="apply(false)">应用修改</ElButton><ElButton v-if="hasNext || canAddNext !== false" type="primary" :disabled="disabled || applying" @click="apply(true)">{{ hasNext ? '保存编辑下一条' : '保存新增下一条' }}</ElButton></template>
  </AppWindowDialog>
</template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.drawer-help { margin: 0 0 24px; color: token.$crm-text-secondary; font-size: 13px; line-height: 22px; }
.drawer-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.drawer-fields :deep(.el-select), .drawer-fields :deep(.el-input), .drawer-fields :deep(.el-cascader) { width: 250px; max-width: 100%; }
.drawer-error { color: token.$crm-danger; font-size: 13px; }
</style>


<style scoped>.catalog-field { grid-column: 1 / -1; min-width: 0; }</style>
