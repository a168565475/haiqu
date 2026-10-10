<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { materialFieldOptions, materialFieldSelectionOnly, validateSampleMaterials } from '@/utils/sampleMaterial'
import { sampleMaterialCategories, type SampleMaterialLine, type SampleMaterialReferences, type SampleMaterialUnit } from '@/types/sampleMaterial'
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
  draft.value = { ...props.line }; initial.value = JSON.stringify(draft.value); error.value = ''
}, { immediate: true })
watch(dirty, value => emit('dirty-change', value), { immediate: true })
function selectName() {
  if (draft.value.category !== 'accessory') return
  const product = props.references?.accessories.find(item => item.label === draft.value.name)
  const unit = props.units.find(item => item.label === product?.unitLabel)
  if (unit) draft.value.unitId = unit.id
}
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
  <ElDrawer :model-value="modelValue" class="sample-material-line-drawer" :title="`${sampleMaterialCategories.find(item => item.key === line.category)?.label} · 放大编辑`" size="600px" append-to-body destroy-on-close :close-on-click-modal="false" :before-close="close">
    <div class="material-line-drawer">
      <p class="drawer-help">编辑名称、规格和本次需求数量。应用后，填写完成再提交仓库。</p>
      <ElForm label-position="top" @submit.prevent>
        <div class="drawer-fields">
          <ElFormItem v-for="field in fields" :key="field.key" :label="field.label" :required="'required' in field && field.required">
            <SampleMaterialFieldInput v-model="draft[field.key]" :options="materialFieldOptions(references, draft, field.key)" :selection-only="materialFieldSelectionOnly(draft, field.key)" :tube-specification="draft.category === 'tube' && field.key === 'specification'" :references="references" :label="`放大编辑${field.label}`" :placeholder="`填写${field.label}`" :maxlength="field.max" :disabled="disabled || applying || (!!draft.rawMaterialId && field.key !== 'color')" @update:model-value="field.key === 'name' && selectName()" />
          </ElFormItem>
          <ElFormItem :label="draft.category === 'tube' ? '总需求米数' : '需求数量'" required><ElInput v-model="draft.quantity" aria-label="放大编辑需求数量" inputmode="decimal" maxlength="19" :disabled="disabled || applying" /></ElFormItem>
          <ElFormItem label="单位" required><span v-if="draft.category === 'tube'">米</span><ElSelect v-else v-model="draft.unitId" aria-label="放大编辑单位" filterable :disabled="disabled || applying"><ElOption v-for="unit in units" :key="unit.id" :label="unit.label" :value="unit.id" /></ElSelect></ElFormItem>
        </div>
        <ElFormItem label="备注"><ElInput v-model="draft.notes" aria-label="放大编辑备注" type="textarea" :rows="3" maxlength="2000" :disabled="disabled || applying" /></ElFormItem>
      </ElForm>
      <p v-if="error" role="alert" class="drawer-error">{{ error }}</p>
    </div>
    <template #footer><ElButton :disabled="applying" @click="close">取消</ElButton><ElButton :disabled="disabled || applying" @click="apply(false)">应用修改</ElButton><ElButton v-if="hasNext || canAddNext !== false" type="primary" :disabled="disabled || applying" @click="apply(true)">{{ hasNext ? '保存编辑下一条' : '保存新增下一条' }}</ElButton></template>
  </ElDrawer>
</template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.drawer-help { margin: 0 0 24px; color: token.$crm-text-secondary; font-size: 13px; line-height: 22px; }
.drawer-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.drawer-fields :deep(.el-select) { width: 100%; }
.drawer-error { color: token.$crm-danger; font-size: 13px; }
</style>
