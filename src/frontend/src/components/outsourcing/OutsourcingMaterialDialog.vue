<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import BomAttributesTooltip from '@/components/common/BomAttributesTooltip.vue'
import type {
  OutsourcingFactoryOption,
  OutsourcingMaterialCandidate,
  OutsourcingSourceBomContext,
  OutsourcingSourceProduct,
  SelectedOutsourcingMaterialRow,
  SelectedOutsourcingProcessingRow,
} from '@/types/outsourcing'

const props = defineProps<{
  modelValue: boolean
  product: OutsourcingSourceProduct | null
  context: OutsourcingSourceBomContext | null
  processingRows: SelectedOutsourcingProcessingRow[]
  selectedRows: SelectedOutsourcingMaterialRow[]
  factories: OutsourcingFactoryOption[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [rows: SelectedOutsourcingMaterialRow[]]
}>()

const activeCategory = ref('ALL')
const pendingIds = ref<string[]>([])
const quantities = ref<Record<string, number | string | null>>({})
const categories = computed(() => [{ value: 'ALL', label: '全部' }, ...(props.context?.material_categories || [])])
const filteredRows = computed(() => (props.context?.material_items || []).filter(
  row => ['HARDWARE', 'AUXILIARY'].includes(row.category) && (activeCategory.value === 'ALL' || row.category === activeCategory.value),
))
const selectedCount = computed(() => pendingIds.value.length)
const processingNames = computed(() => props.processingRows.map(row => row.part_name).filter(Boolean).join('、') || '待选择加工明细')
const factoryNames = computed(() => {
  const ids = [...new Set(props.processingRows.map(row => row.factory_id).filter(Boolean))]
  return ids.map(id => props.factories.find(factory => factory.id === id)?.name || '').filter(Boolean).join('、') || '待选择加工厂'
})
const tooltipKeys = ['part_name', 'material', 'specification', 'hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color']
const materialValue = (row: OutsourcingMaterialCandidate) => {
  const field = (row.bom_attributes || []).find(item => item.key === 'material' && item.value)
  return field?.value || '—'
}
const colorValue = (row: OutsourcingMaterialCandidate) => {
  const field = (row.bom_attributes || []).find(item => ['hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color'].includes(item.key) && item.value)
  return field?.value || '—'
}
const allocatedQuantityText = computed(() => {
  const totals = new Map<string, number>()
  props.processingRows.forEach(row => {
    const unit = row.unit || '未标单位'
    totals.set(unit, (totals.get(unit) || 0) + Number(row.allocated_quantity || 0))
  })
  if (!totals.size) return '—'
  return [...totals.entries()]
    .map(([unit, quantity]) => `${quantity.toLocaleString('zh-CN', { maximumFractionDigits: 4 })} ${unit}`)
    .join('、')
})

watch(() => props.modelValue, visible => {
  if (!visible) return
  activeCategory.value = 'ALL'
  pendingIds.value = props.selectedRows.map(row => row.id)
  quantities.value = Object.fromEntries(props.selectedRows.map(row => [row.id, row.planned_issue_quantity]))
})

function checked(id: string): boolean {
  return pendingIds.value.includes(id)
}

function toggle(row: OutsourcingMaterialCandidate): void {
  if (row.quantity_error) {
    ElMessage.warning(row.quantity_error)
    return
  }
  if (checked(row.id)) {
    pendingIds.value = pendingIds.value.filter(id => id !== row.id)
    return
  }
  pendingIds.value = [...pendingIds.value, row.id]
  if (quantities.value[row.id] == null) quantities.value[row.id] = row.default_issue_quantity
}

function confirm(): void {
  const selected = new Set(pendingIds.value)
  const existingById = new Map(props.selectedRows.map(row => [row.id, row]))
  const defaultProcessing = props.processingRows.find(row => row.factory_id)
  const rows = (props.context?.material_items || [])
    .filter(row => selected.has(row.id))
    .map(row => {
      const existing = existingById.get(row.id)
      return {
        ...row,
        planned_issue_quantity: quantities.value[row.id] ?? null,
        factory_id: existing?.factory_id || defaultProcessing?.factory_id || '',
        processing_bom_line_id: existing?.processing_bom_line_id || defaultProcessing?.id || '',
      }
    })
  if (rows.some(row => row.planned_issue_quantity == null || Number(row.planned_issue_quantity) <= 0)) {
    ElMessage.warning('请为已选材料填写大于 0 的本次发料数量。')
    return
  }
  emit('confirm', rows)
  emit('update:modelValue', false)
}
</script>

<template>
  <AppWindowDialog
    :model-value="modelValue"
    title="选择材料明细"
    width="1260px"
    height="730px"
    :min-width="820"
    :min-height="560"
    :close-on-click-modal="false"
    class="outsourcing-picker-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="material-picker-layout">
      <aside class="material-source-panel">
        <h3>来源信息</h3>
        <dl>
          <div class="material-product-summary"><dt>产品信息</dt><dd><strong>{{ product?.product_number || product?.item_number || '—' }}<small>{{ product?.product_name || '—' }}<br>{{ product?.specification || '—' }} / {{ product?.color_name || '—' }}</small></strong></dd></div>
          <div><dt>BOM编号</dt><dd>{{ context?.bom?.bom_number || '暂无可用BOM' }}</dd></div>
          <div><dt>外协工艺</dt><dd><span class="material-craft-tag">{{ context?.craft.name || '—' }}</span></dd></div>
          <div><dt>加工明细</dt><dd>{{ processingNames }}</dd></div>
          <div><dt>接收加工厂</dt><dd>{{ factoryNames }}</dd></div>
          <div><dt>加工数量</dt><dd>{{ allocatedQuantityText }}</dd></div>
        </dl>
      </aside>

      <section class="material-table-panel">
        <div class="material-tabs" role="tablist">
          <button v-for="item in categories" :key="item.value" type="button" :class="{ 'is-active': activeCategory === item.value }" @click="activeCategory = item.value">{{ item.label }}</button>
        </div>
        <div class="material-table-wrap">
          <table class="material-picker-table">
             <colgroup><col class="col-select"><col class="col-number"><col class="col-name"><col class="col-material"><col class="col-specification"><col class="col-color"><col class="col-consumption"><col class="col-required"><col class="col-procurement"><col class="col-issue"></colgroup>
             <thead><tr><th>选择</th><th>物料编号</th><th>名称</th><th>材质</th><th>规格</th><th>颜色</th><th>单个用量</th><th>外发总需求</th><th>采购换算量</th><th>本次发料</th></tr></thead>
            <tbody>
              <tr v-for="row in filteredRows" :key="row.id" :class="{ 'is-selected': checked(row.id), 'is-disabled': Boolean(row.quantity_error) }" @click="toggle(row)">
                <td><ElCheckbox :model-value="checked(row.id)" :disabled="Boolean(row.quantity_error)" @click.stop @change="toggle(row)" /></td>
                <td>{{ row.material_number || '—' }}</td>
                 <td><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys"><strong>{{ row.name || '—' }}</strong></BomAttributesTooltip></td>
                 <td>{{ materialValue(row) }}</td>
                <td>{{ row.specification || '—' }}</td>
                 <td>{{ colorValue(row) }}</td>
                <td>{{ row.unit_consumption || '—' }}<small v-if="row.unit_consumption"> {{ row.unit }}/{{ context?.product.unit_name || '订单单位' }}</small></td>
                <td><strong>{{ row.reference_required_quantity ?? '待核对' }} {{ row.unit }}</strong><small class="quantity-basis">{{ row.quantity_error || row.quantity_source_text || '—' }}</small></td>
                <td><strong>{{ row.procurement_required_quantity ?? '待核对' }} {{ row.procurement_unit }}</strong><small class="quantity-basis">{{ row.procurement_source_text || '—' }}</small></td>
                <td @click.stop><div class="issue-input-with-unit"><ElInputNumber v-model="quantities[row.id]" :disabled="Boolean(row.quantity_error)" :min="0.0001" :precision="4" :controls="false" placeholder="请输入" /><span>{{ row.unit }}</span></div></td>
              </tr>
               <tr v-if="!filteredRows.length" class="material-empty-row"><td colspan="10">当前分类暂无可选材料</td></tr>
            </tbody>
          </table>
        </div>
        <p class="material-footnote">{{ context?.stock_mode === 'PUBLIC_V2' ? '“外发总需求”按 BOM 用量与订单数量计算；发料按库区扣公共库存，同时检查订单剩余数量。管材按支填写并换算为整根和米数。' : '“外发总需求”按 BOM 单个用量 × 订单数量计算并自动带入本次发料；“采购换算量”用于仓库选择批次和扣减原料库存。' }}</p>
      </section>
    </div>
    <template #footer>
      <div class="material-dialog-footer"><span>已选 {{ selectedCount }} 项材料</span><div><ElButton @click="emit('update:modelValue', false)">取消</ElButton><ElButton type="primary" :disabled="!selectedCount" @click="confirm">确认选择</ElButton></div></div>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '../../styles/crm/tokens' as token;

.material-picker-layout { display: grid; min-height: 0; height: 100%; grid-template-columns: 240px minmax(0, 1fr); gap: 16px; }
.material-source-panel, .material-table-panel { min-width: 0; overflow: hidden; border: 1px solid token.$crm-border-default; border-radius: 5px; background: token.$crm-color-surface; }
.material-source-panel h3 { height: 44px; margin: 0; padding: 0 16px; border-bottom: 1px solid token.$crm-border-default; background: #f1eadf; font-size: 16px; line-height: 44px; }
.material-source-panel dl { display: grid; gap: 18px; margin: 0; padding: 18px 16px; }
.material-source-panel dl > div { display: grid; grid-template-columns: 78px minmax(0, 1fr); gap: 8px; }
.material-source-panel dt { color: token.$crm-text-secondary; }
.material-source-panel dd { min-width: 0; margin: 0; color: token.$crm-text-primary; line-height: 22px; word-break: break-word; }
.material-source-panel .material-product-summary { align-items: start; }
.material-product-summary dd { display: flex; flex-direction: column; align-items: flex-start; }
.material-product-summary strong { font-weight: 600; }
.material-product-summary small { display: block; margin-top: 3px; color: token.$crm-text-secondary; font-size: 12px; font-weight: 400; line-height: 19px; }
.material-craft-tag { display: inline-flex; height: 24px; align-items: center; padding: 0 12px; border-radius: 999px; color: #fff; background: #bf6d19; font-size: 12px; }
.material-table-panel { display: flex; flex-direction: column; }
.material-tabs { display: flex; height: 44px; align-items: flex-end; gap: 22px; padding: 0 16px; border-bottom: 1px solid token.$crm-border-default; }
.material-tabs button { position: relative; height: 44px; padding: 0; border: 0; color: token.$crm-text-secondary; background: transparent; cursor: pointer; font: inherit; }
.material-tabs button.is-active { color: #c94b27; font-weight: 600; }
.material-tabs button.is-active::after { position: absolute; right: 0; bottom: 0; left: 0; height: 2px; background: #c94b27; content: ''; }
.material-table-wrap { min-height: 0; flex: 1; overflow: auto; }
.material-picker-table { width: 100%; min-width: 900px; table-layout: fixed; border-spacing: 0; border-collapse: separate; color: token.$crm-text-regular; font-size: 12px; line-height: 18px; }
.material-picker-table th { position: sticky; z-index: 1; top: 0; height: 44px; padding: 0 16px; border-bottom: 1px solid token.$crm-border-default; color: token.$crm-text-primary; background: #f1eadf; font-size: 11px; font-weight: 600; line-height: 16px; text-align: left; white-space: nowrap; }
.material-picker-table td { height: 40px; padding: 0 16px; overflow: hidden; border-bottom: 1px solid token.$crm-border-subtle; background: token.$crm-color-surface; text-overflow: ellipsis; white-space: nowrap; }
.material-picker-table .col-select { width: 56px; }
.material-picker-table .col-number { width: 110px; }
.material-picker-table .col-name { width: 128px; }
.material-picker-table .col-material { width: 100px; }
.material-picker-table .col-specification { width: 112px; }
.material-picker-table .col-color { width: 90px; }
.material-picker-table .col-consumption { width: 118px; }
.material-picker-table .col-required { width: 145px; }
.material-picker-table .col-procurement { width: 145px; }
.material-picker-table .col-issue { width: 156px; }
.material-picker-table tbody tr:not(.material-empty-row) { cursor: pointer; }
.material-picker-table tbody tr.is-selected td { background: #fff7f1; }
.material-picker-table tbody tr.is-disabled { cursor: not-allowed; opacity: .64; }
.material-picker-table strong { display: block; overflow: hidden; color: token.$crm-text-primary; font-size: 13px; font-weight: 600; line-height: 20px; text-overflow: ellipsis; }
.material-picker-table small { color: token.$crm-text-secondary; font-size: 11px; }
.material-picker-table .quantity-basis { display: block; overflow: hidden; text-overflow: ellipsis; }
.material-picker-table .el-input-number { width: 104px; }
.issue-input-with-unit { display: flex; align-items: center; gap: 6px; }
.issue-input-with-unit span { color: token.$crm-text-secondary; }
.material-empty-row td { height: 270px; color: token.$crm-text-secondary; text-align: center; }
.material-footnote { flex: none; margin: 0; padding: 10px 16px; border-top: 1px solid token.$crm-border-subtle; color: token.$crm-text-secondary; font-size: 12px; }
.material-dialog-footer { display: flex; align-items: center; justify-content: space-between; color: token.$crm-text-secondary; }
.material-dialog-footer > div { display: flex; gap: 12px; }

@media (max-width: 900px) {
  .material-picker-layout { grid-template-columns: 200px minmax(0, 1fr); }
}
</style>
