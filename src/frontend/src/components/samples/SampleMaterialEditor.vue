<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ZoomIn, Delete } from '@element-plus/icons-vue'
import { fetchSampleMaterialReferences } from '@/api/sampleMaterials'
import { materialFieldOptions, materialFieldSelectionOnly, sampleMaterialError } from '@/utils/sampleMaterial'
import { createClientUuid } from '@/utils/clientUuid'
import SampleMaterialTabs from './SampleMaterialTabs.vue'
import SampleMaterialFieldInput from './SampleMaterialFieldInput.vue'
import SampleMaterialPicker from './SampleMaterialPicker.vue'
import SampleMaterialLineDrawer from './SampleMaterialLineDrawer.vue'
import { sampleMaterialCategories, type SampleMaterialCategory, type SampleMaterialLine, type SampleMaterialUnit, type SampleMaterialReferences, type SampleMaterialCandidate } from '@/types/sampleMaterial'

const props = defineProps<{ modelValue: SampleMaterialLine[]; units: SampleMaterialUnit[]; fullscreen: boolean; unavailableMessage?: string; disabled?: boolean; layout?: 'sidebar' }>()
const emit = defineEmits<{ 'update:modelValue': [lines: SampleMaterialLine[]]; 'toggle-fullscreen': []; 'editing-change': [value: boolean]; 'dirty-change': [value: boolean] }>()
const category = ref<SampleMaterialCategory>('tube')
const table = ref<HTMLElement>()
const references = ref<SampleMaterialReferences | null>(null)
const referenceError = ref(''), referenceLoading = ref(false), pickerOpen = ref(false), drawerOpen = ref(false)
const editingLine = ref<SampleMaterialLine>()
const fields = [{ key: 'name', label: '材料名称', max: 300 }, { key: 'specification', label: '规格', max: 500 }, { key: 'material', label: '材质', max: 500 }, { key: 'color', label: '颜色', max: 500 }] as const
const pickerLabel = computed(() => ({ tube: '选择管材', fabric: '选择面料', hardware: '选择数据', plastic: '选择数据', accessory: '选择辅料', packaging: '选择包材' })[category.value as 'tube' | 'fabric' | 'hardware' | 'plastic' | 'accessory' | 'packaging'] || '')
const visibleLines = computed(() => props.modelValue.filter(line => line.category === category.value))
const counts = computed(() => Object.fromEntries(sampleMaterialCategories.map(item => [item.key, props.modelValue.filter(line => line.category === item.key).length])))
const categoryLabel = computed(() => sampleMaterialCategories.find(item => item.key === category.value)?.label || '材料需求')
const hasNext = computed(() => {
  const index = visibleLines.value.findIndex(line => line.key === editingLine.value?.key)
  return index >= 0 && index < visibleLines.value.length - 1
})
watch(() => pickerOpen.value || drawerOpen.value, value => emit('editing-change', value))
watch(() => props.disabled, disabled => { if (!disabled && !references.value) void loadReferences() }, { immediate: true })
async function loadReferences() {
  if (referenceLoading.value || props.disabled) return
  referenceLoading.value = true; referenceError.value = ''
  try { references.value = await fetchSampleMaterialReferences() }
  catch (error) { referenceError.value = `材料配置加载失败，请重试。${sampleMaterialError(error)}` }
  finally { referenceLoading.value = false }
}
function emptyLine(): SampleMaterialLine {
  return {
    key: createClientUuid(), category: category.value, name: '', specification: '', material: '', color: '', quantity: '',
    // 管材需求按总米数填写；单位仍从系统单位配置中带出，避免手工改成“根”。
    unitId: category.value === 'tube' ? (props.units.find(unit => unit.label === '米')?.id || '') : '',
    ...(category.value === 'tube' ? { unitLabel: '米', pipeInputMode: 'TOTAL_METERS' as const } : {}), notes: '',
  }
}
function updateLine(key: string, field: keyof SampleMaterialLine, value: string) {
  if (props.disabled) return
  emit('update:modelValue', props.modelValue.map(line => {
    if (line.key !== key) return line
    const updated = { ...line, [field]: value }
    if (line.category === 'accessory' && field === 'name') {
      const product = references.value?.accessories.find(item => item.label === value)
      const unit = props.units.find(item => item.label === product?.unitLabel)
      if (unit) updated.unitId = unit.id
    }
    return updated
  }))
}
async function addLine() {
  if (props.disabled || pickerLabel.value) return
  if (props.modelValue.length >= 500) { ElMessage.warning('材料需求最多 500 项。'); return }
  const line = emptyLine(), key = line.key
  emit('update:modelValue', [...props.modelValue, line])
  await nextTick()
  table.value?.querySelector<HTMLInputElement>(`[data-line-key="${key}"] input`)?.focus()
}
async function removeLine(line: SampleMaterialLine) {
  if (props.disabled) return
  if (line.name || line.specification || line.material || line.color || line.quantity || line.unitId || line.notes) {
    try { await ElMessageBox.confirm('删除后本项填写内容将被移除。', '删除材料', { confirmButtonText: '删除', cancelButtonText: '保留', type: 'warning' }) }
    catch { return }
  }
  if (!props.disabled) emit('update:modelValue', props.modelValue.filter(item => item.key !== line.key))
}
function openLine(line: SampleMaterialLine) {
  if (props.disabled) return
  editingLine.value = { ...line }; drawerOpen.value = true
}
async function applyLine(line: SampleMaterialLine, next: boolean) {
  if (props.disabled) return
  const exists = props.modelValue.some(item => item.key === line.key)
  if (!exists && props.modelValue.length >= 500) { ElMessage.warning('材料需求最多 500 项。'); return }
  const updated = exists ? props.modelValue.map(item => item.key === line.key ? line : item) : [...props.modelValue, line]
  emit('update:modelValue', updated)
  emit('dirty-change', false)
  ElMessage.success('已应用到表格，填写完成后提交仓库。')
  if (!next) { drawerOpen.value = false; return }
  await nextTick()
  const section = updated.filter(item => item.category === line.category)
  const nextLine = section[section.findIndex(item => item.key === line.key) + 1]
  // 新一条先留在抽屉内，应用时才写入表格；取消不会生成空行。
  if (!nextLine && pickerLabel.value && line.category !== 'tube') { drawerOpen.value = false; return }
  editingLine.value = nextLine ? { ...nextLine } : { ...emptyLine(), category: line.category, name: line.name, specification: line.specification, material: line.material, color: line.color, unitId: line.unitId, rawMaterialId: line.rawMaterialId }
}
function chooseMaterials(items: SampleMaterialCandidate[]) {
  if (props.disabled) return
  const lines = [...props.modelValue]
  let added = 0
  const selectedIds = new Set<string>()
  for (const item of items) {
    if (selectedIds.has(item.id)) continue
    selectedIds.add(item.id)
    if (category.value !== 'tube' && lines.some(line => line.category === category.value && line.name === item.name && line.specification === item.specification && line.material === item.material && line.color === item.color && line.unitId === item.unitId)) continue
    if (lines.length >= 500) { ElMessage.warning('材料需求最多 500 项。'); break }
    lines.push({
      ...emptyLine(), name: item.name, specification: item.specification, material: item.material, color: item.color,
      unitId: category.value === 'tube' ? (props.units.find(unit => unit.label === '米')?.id || '') : item.unitId,
      rawMaterialId: item.id,
    }); added++
  }
  emit('update:modelValue', lines)
  ElMessage.info(added ? `已添加 ${added} 项，请填写本次需求数量；已有相同材料已跳过。` : '所选材料已在当前分区中。')
}
</script>

<template>
  <section class="material-editor" :class="{ 'is-fullscreen': fullscreen, 'editor-grid': layout === 'sidebar' }" aria-label="材料需求">
    <aside v-if="layout === 'sidebar'" class="section-sidebar">
      <h2>物料分类</h2><nav class="section-tabs" aria-label="材料分区"><button v-for="item in sampleMaterialCategories" :key="item.key" type="button" :aria-pressed="category === item.key" :class="{ active: category === item.key }" :disabled="pickerOpen || drawerOpen" @click="category = item.key"><span>{{ item.label }}</span><b>{{ counts[item.key] || 0 }}</b></button></nav>
    </aside>
    <div class="material-main">
    <header class="material-toolbar"><h2>{{ layout === 'sidebar' ? categoryLabel : '材料需求' }}</h2><p>按材料分类填写，本次打样需要多少就填多少。</p><ElButton v-if="pickerLabel" :disabled="disabled || (category === 'accessory' && !references)" @click="pickerOpen = true">{{ pickerLabel }}</ElButton><ElButton v-if="!pickerLabel" :disabled="disabled" @click="addLine">＋ 添加材料</ElButton><ElButton class="fullscreen-toggle" @click="emit('toggle-fullscreen')">{{ fullscreen ? '退出全屏' : '全屏填写' }}</ElButton></header>
    <div v-if="referenceError" role="alert" class="reference-error">{{ referenceError }} <ElButton link :loading="referenceLoading" @click="loadReferences">重试</ElButton></div>
    <SampleMaterialTabs v-if="layout !== 'sidebar'" v-model="category" :counts="counts" />
    <div ref="table" class="material-table">
      <div class="table-scroll" tabindex="0" aria-label="材料录入表格">
        <table><colgroup><col class="col-number"><col class="col-name"><col class="col-spec"><col class="col-material"><col class="col-color"><col class="col-quantity"><col class="col-unit"><col class="col-notes"><col class="col-actions"></colgroup>
          <thead><tr><th>序号</th><th>材料名称 *</th><th>规格 *</th><th>材质</th><th>颜色 / 色号</th><th>需求数量 *</th><th>单位 *</th><th>备注</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(line, index) in visibleLines" :key="line.key" :data-line-key="line.key"><td><div class="row-tools"><span>{{ index + 1 }}</span><ElButton class="row-expand" link :icon="ZoomIn" :disabled="disabled" aria-label="放大编辑当前行" @click="openLine(line)" /></div></td>
              <td v-for="field in fields" :key="field.key"><SampleMaterialFieldInput :model-value="line[field.key]" :options="materialFieldOptions(references, line, field.key)" :selection-only="materialFieldSelectionOnly(line, field.key)" :tube-specification="line.category === 'tube' && field.key === 'specification'" :references="references" :disabled="disabled || (!!line.rawMaterialId && field.key !== 'color')" :label="`第${index + 1}项${field.label}`" :placeholder="field.label" :maxlength="field.max" @update:model-value="updateLine(line.key, field.key, $event)" /></td>
              <td><ElInput :model-value="line.quantity" :disabled="disabled" :aria-label="`第${index + 1}项需求数量`" inputmode="decimal" placeholder="数量" @update:model-value="updateLine(line.key, 'quantity', $event)" /></td>
              <td><span v-if="line.category === 'tube'">米</span><ElSelect v-else :model-value="line.unitId" :disabled="disabled" :aria-label="`第${index + 1}项单位`" filterable placeholder="单位" @update:model-value="updateLine(line.key, 'unitId', $event)"><ElOption v-for="unit in units" :key="unit.id" :label="unit.label" :value="unit.id" /></ElSelect></td>
              <td><ElInput :model-value="line.notes" :disabled="disabled" :aria-label="`第${index + 1}项备注`" maxlength="2000" placeholder="填写备注" @update:model-value="updateLine(line.key, 'notes', $event)" /></td>
              <td class="action-cell"><ElButton class="row-delete" link :icon="Delete" :disabled="disabled" aria-label="删除当前行" @click="removeLine(line)" /></td>
            </tr>
            <tr v-if="!visibleLines.length" class="empty-row"><td colspan="9">{{ unavailableMessage || '当前分区暂无材料，请添加本次需要的材料。' }}</td></tr>
          </tbody>
        </table>
      </div>
      <ElButton v-if="!pickerLabel" class="add-row" :disabled="disabled" @click="addLine">＋ 添加一行</ElButton>
    </div>
    <div class="material-count"><span>当前分区 {{ visibleLines.length }} 项 · 全部分区 {{ modelValue.length }} 项{{ unavailableMessage ? '（本页未保存）' : '' }}</span><span>* 为必填</span></div>
    </div>
    <SampleMaterialPicker v-model="pickerOpen" :category="category" :references="references" :units="units" :disabled="disabled" @choose="chooseMaterials" />
    <SampleMaterialLineDrawer v-if="editingLine" v-model="drawerOpen" :line="editingLine" :references="references" :units="units" :has-next="hasNext" :can-add-next="!pickerLabel || category === 'tube'" :disabled="disabled" @apply="applyLine" @dirty-change="emit('dirty-change', $event)" />
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;
.material-main { display: contents; }
.material-editor { display: flex; min-width: 0; flex: none; flex-direction: column; gap: 14px; padding: 24px; border-radius: 4px; background: token.$crm-color-surface; box-shadow: inset 0 0 0 1px token.$crm-border-subtle; }
.material-toolbar { display: flex; height: 44px; flex: none; align-items: center; gap: 16px; }
h2 { width: 140px; flex: none; margin: 0; font-family: token.$crm-font-display; font-size: 22px; line-height: 30px; }
.material-toolbar p { flex: 1; min-width: 0; margin: 0; color: token.$crm-text-secondary; font-size: 14px; line-height: 22px; }
.material-editor .material-toolbar :deep(.el-button) { width: auto; min-width: 96px; height: 32px !important; min-height: 32px !important; padding: 0 12px; flex: none; border-radius: 5px; background: var(--erp-color-surface); font-size: 13px; }
.material-editor .material-toolbar :deep(.fullscreen-toggle) { min-width: 96px; }
.material-table { display: flex; min-width: 0; flex-direction: column; }
.table-scroll { min-width: 0; overflow: visible; }
table { width: 100%; min-width: 0; border-spacing: 0; table-layout: fixed; }
.col-number { width: 7%; } .col-name { width: 15%; } .col-spec { width: 17%; } .col-material { width: 13%; } .col-color { width: 14%; } .col-quantity { width: 10%; } .col-unit { width: 8%; } .col-notes { width: 11%; } .col-actions { width: 56px; }
.row-tools { display: flex; align-items: center; gap: 6px; }
.material-editor td :deep(.row-expand) { width: 28px; height: 28px; font-size: 16px; }
.reference-error { color: token.$crm-danger; font-size: 12px; }
th { height: 44px; padding: 0 16px !important; color: var(--erp-table-header-text); background: var(--erp-table-header-background); text-align: left; vertical-align: middle; font-size: 11px !important; font-weight: 500; line-height: 16px !important; white-space: nowrap; }
td { height: auto !important; min-height: 40px; padding: 4px 16px !important; border-bottom: 1px solid token.$crm-border-subtle; font-size: 12px !important; line-height: 18px !important; vertical-align: middle; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
td :deep(.el-input), td :deep(.el-select), td :deep(.el-cascader) { width: 100%; }
td :deep(.el-input__wrapper), td :deep(.el-select__wrapper), td :deep(.el-cascader .el-input__wrapper) { box-sizing: border-box; height: 32px !important; min-height: 32px !important; padding: 0 8px; border-radius: var(--erp-radius-control); background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset; font-size: 12px; }
td :deep(.el-input__wrapper:hover), td :deep(.el-input__wrapper.is-focus), td :deep(.el-select__wrapper:hover), td :deep(.el-select__wrapper.is-focused), td :deep(.el-cascader .el-input__wrapper:hover), td :deep(.el-cascader .el-input__wrapper.is-focus) { background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }
td :deep(.el-input__inner::placeholder), td :deep(.el-select__placeholder) { color: var(--erp-table-text); }
.action-cell { overflow: visible; padding: 4px 8px !important; text-align: center; text-overflow: clip; }
td.action-cell :deep(.row-delete) { width: 28px; min-width: 28px; height: 28px; min-height: 28px; padding: 0; flex: none; }
.empty-row td { height: auto !important; min-height: 0; padding: 48px 16px !important; color: token.$crm-text-secondary; text-align: center; }
.material-editor .material-table :deep(.add-row) { width: 100%; height: 32px; min-height: 32px; flex: none; border-color: token.$crm-border-subtle; background: var(--erp-table-background); font-size: 13px; }
.material-count { display: flex; height: 22px; flex: none; justify-content: space-between; color: token.$crm-text-secondary; font-size: 12px; line-height: 22px; }
.material-count span:last-child { color: token.$crm-primary; }
.is-fullscreen { min-height: 100%; }
.is-fullscreen .material-table { height: auto; flex: none; }
.material-editor.is-fullscreen .fullscreen-toggle { display: none; }
.material-editor.editor-grid { display: grid; grid-template-columns: 176px minmax(0, 1fr); gap: 14px; padding: 0; background: transparent; box-shadow: none; border-radius: 0; align-items: stretch; }
.editor-grid .section-sidebar, .editor-grid .material-main { @include detail.surface; }
.editor-grid .section-sidebar { padding: 14px 0; overflow: hidden; }
.editor-grid .section-sidebar h2 { width: auto; padding: 0 16px 12px; border-bottom: 1px solid var(--erp-color-border); font-family: inherit; font-size: 17px; line-height: 26px; }
.editor-grid .section-tabs { display: grid; }
.editor-grid .section-tabs button { display: flex; width: 100%; height: 46px; align-items: center; justify-content: space-between; padding: 0 16px; border: 0; border-left: 3px solid transparent; background: transparent; color: var(--erp-color-text-secondary); text-align: left; cursor: pointer; }
.editor-grid .section-tabs button b { color: var(--erp-color-text-muted); font-size: 12px; font-weight: 500; }
.editor-grid .section-tabs button.active { border-left-color: var(--erp-color-brand); color: var(--erp-color-brand); background: var(--erp-color-selected); }
.editor-grid .section-tabs button.active b { color: var(--erp-color-brand); }
.editor-grid .section-tabs button:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: -2px; }
.editor-grid .material-main { display: flex; min-width: 0; flex-direction: column; gap: 14px; padding: 14px 12px 12px; }
.editor-grid .material-toolbar { height: auto; min-height: 44px; flex-wrap: wrap; gap: 8px 16px; }
.editor-grid .material-toolbar h2 { width: auto; font-family: inherit; font-size: 17px; line-height: 26px; }
.editor-grid .material-toolbar p { font-size: 12px; }
.editor-grid .table-scroll { overflow: auto; }
.editor-grid table { min-width: 960px; }
@media (max-width: 900px) { .material-editor.editor-grid { grid-template-columns: 152px minmax(0, 1fr); } }
</style>

<style lang="scss" src="@/styles/crm/_sample-material-overlays.scss"></style>
