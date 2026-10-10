<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import BomAttributesTooltip from '@/components/common/BomAttributesTooltip.vue'
import type {
  OutsourcingProcessingCandidate,
  OutsourcingSourceBomContext,
  OutsourcingSourcePlan,
  OutsourcingSourceProduct,
  SelectedOutsourcingProcessingRow,
} from '@/types/outsourcing'

const props = defineProps<{
  modelValue: boolean
  plan: OutsourcingSourcePlan | null
  product: OutsourcingSourceProduct | null
  context: OutsourcingSourceBomContext | null
  selectedRows: SelectedOutsourcingProcessingRow[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [rows: OutsourcingProcessingCandidate[]]
}>()

const pendingIds = ref<string[]>([])
const isSpray = computed(() => props.context?.craft.outsourcing_code === 'POWDER_COATING')
const selectedCount = computed(() => pendingIds.value.length)
const tooltipKeys = ['part_name', 'material', 'specification', 'hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color']
const fixedColor = (row: OutsourcingProcessingCandidate) => {
  const field = (row.bom_attributes || []).find(item => ['hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color'].includes(item.key) && item.value)
  return field?.value || '—'
}

function quantityText(value: number | string | null): string {
  if (value === null || value === undefined) return '—'
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

watch(() => props.modelValue, visible => {
  if (visible) pendingIds.value = props.selectedRows.filter(row => Number(row.available_quantity) > 0).map(row => row.id)
})

function checked(id: string): boolean {
  return pendingIds.value.includes(id)
}

function toggle(row: OutsourcingProcessingCandidate): void {
  if (Number(row.available_quantity) <= 0) return
  const { id } = row
  pendingIds.value = checked(id)
    ? pendingIds.value.filter(item => item !== id)
    : [...pendingIds.value, id]
}

function confirm(): void {
  const selected = new Set(pendingIds.value)
  emit('confirm', (props.context?.processing_items || []).filter(
    item => Number(item.available_quantity) > 0 && selected.has(item.id),
  ))
  emit('update:modelValue', false)
}
</script>

<template>
  <AppWindowDialog
    :model-value="modelValue"
    title="选择加工明细"
    width="1260px"
    height="730px"
    :min-width="820"
    :min-height="560"
    :close-on-click-modal="false"
    class="outsourcing-picker-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="outsourcing-picker-layout">
      <aside class="picker-source-panel">
        <h3>来源信息</h3>
        <dl>
          <div><dt>生产任务单</dt><dd>{{ plan?.production_task_number || '—' }}</dd></div>
          <div><dt>排产计划</dt><dd>{{ plan?.schedule_number || '—' }}</dd></div>
          <div class="picker-product-summary"><dt>产品</dt><dd><strong>{{ product?.product_number || product?.item_number || '—' }}<small>{{ product?.product_name || '—' }}<br>{{ product?.specification || '—' }} / {{ product?.color_name || '—' }}</small></strong></dd></div>
          <div><dt>BOM编号</dt><dd>{{ context?.bom?.bom_number || '暂无可用BOM' }}</dd></div>
          <div><dt>外协工艺</dt><dd><span class="picker-craft-tag">{{ context?.craft.name || '—' }}</span></dd></div>
          <div><dt>订单数量</dt><dd>{{ product?.source_quantity || 0 }} {{ product?.unit_name || '' }}</dd></div>
        </dl>
      </aside>

      <section class="picker-table-panel">
        <div class="picker-panel-heading"><h3>BOM {{ context?.processing_section_label || '加工' }}明细</h3></div>
        <div class="picker-table-wrap">
          <table class="picker-table processing-picker-table">
            <colgroup><col class="col-select"><col class="col-name"><col class="col-category"><col class="col-specification"><col class="col-material"><col class="col-color"><col class="col-quantity"><col class="col-outsourced"><col class="col-inbound"></colgroup>
            <thead><tr><th>选择</th><th>{{ isSpray ? '构件名称' : '裁片名称' }}</th><th>类别</th><th>规格</th><th>材质</th><th>颜色</th><th>单个用量</th><th>已外发数量</th><th>订单需求数量</th></tr></thead>
            <tbody>
              <tr v-for="row in context?.processing_items || []" :key="row.id" :class="{ 'is-selected': checked(row.id), 'is-disabled': Number(row.available_quantity) <= 0 }" @click="toggle(row)">
                <td><ElCheckbox :model-value="checked(row.id)" :disabled="Number(row.available_quantity) <= 0" @click.stop @change="toggle(row)" /></td>
                 <td :title="row.quantity_error || row.part_name"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys"><strong>{{ row.part_name || '—' }}</strong></BomAttributesTooltip><small v-if="row.quantity_error">参数不完整，无法选择</small></td>
                <td>{{ row.category || '—' }}</td>
                <td>{{ row.specification || '—' }}</td>
                <td>{{ row.material || '—' }}</td>
                <td>{{ fixedColor(row) }}</td>
                <td>{{ quantityText(row.reference_usage) }} {{ row.unit }}</td>
                <td>{{ quantityText(row.dispatched_quantity) }} {{ row.unit }}</td>
                <td>{{ row.quantity_error || `${quantityText(row.required_quantity)} ${row.unit}` }}</td>
              </tr>
              <tr v-if="!(context?.processing_items || []).length" class="picker-empty-row"><td colspan="9">当前产品的 {{ context?.processing_section_label || '加工' }}明细为空</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
    <template #footer>
      <div class="picker-dialog-footer"><span>订单需求数量 = BOM 单个用量 × 订单数量；管材按支输入、面料按米输入，回货按支/套</span><div><ElButton @click="emit('update:modelValue', false)">取消</ElButton><ElButton type="primary" :disabled="!selectedCount" @click="confirm">确认选择</ElButton></div></div>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '../../styles/crm/tokens' as token;

.outsourcing-picker-layout { display: grid; min-height: 0; height: 100%; grid-template-columns: 240px minmax(0, 1fr); gap: 16px; }
.picker-source-panel, .picker-table-panel { min-width: 0; overflow: hidden; border: 1px solid token.$crm-border-default; border-radius: 5px; background: token.$crm-color-surface; }
.picker-source-panel h3, .picker-panel-heading { margin: 0; border-bottom: 1px solid token.$crm-border-default; background: #f1eadf; }
.picker-source-panel h3 { height: 44px; padding: 0 16px; font-size: 16px; line-height: 44px; }
.picker-source-panel dl { display: grid; gap: 16px; margin: 0; padding: 18px 16px; }
.picker-source-panel dl > div { display: grid; grid-template-columns: 76px minmax(0, 1fr); gap: 10px; }
.picker-source-panel dt { color: token.$crm-text-secondary; }
.picker-source-panel dd { min-width: 0; margin: 0; color: token.$crm-text-primary; line-height: 22px; word-break: break-word; }
.picker-source-panel .picker-product-summary { align-items: start; }
.picker-product-summary dd { display: flex; flex-direction: column; align-items: flex-start; }
.picker-product-summary strong { font-weight: 600; }
.picker-product-summary small { display: block; margin-top: 3px; color: token.$crm-text-secondary; font-size: 12px; font-weight: 400; line-height: 19px; }
.picker-craft-tag { display: inline-flex; height: 24px; align-items: center; padding: 0 12px; border-radius: 999px; color: #fff; background: #bf6d19; font-size: 12px; }
.picker-table-panel { display: flex; flex-direction: column; }
.picker-panel-heading { display: flex; min-height: 44px; align-items: center; justify-content: space-between; padding: 0 16px; background: token.$crm-color-surface; }
.picker-panel-heading h3 { margin: 0; font-size: 16px; }
.picker-table-wrap { min-height: 0; flex: 1; overflow: auto; }
.picker-table { width: 100%; min-width: 1110px; table-layout: fixed; border-spacing: 0; border-collapse: separate; color: token.$crm-text-regular; font-size: 12px; line-height: 18px; }
.picker-table th { position: sticky; z-index: 1; top: 0; height: 44px; padding: 0 16px; border-bottom: 1px solid token.$crm-border-default; color: token.$crm-text-primary; background: #f1eadf; font-size: 11px; font-weight: 600; line-height: 16px; text-align: left; white-space: nowrap; }
.picker-table td { height: 40px; padding: 0 16px; overflow: hidden; border-bottom: 1px solid token.$crm-border-subtle; background: token.$crm-color-surface; text-overflow: ellipsis; white-space: nowrap; }
.picker-table .col-select { width: 64px; }
.picker-table .col-name { width: 150px; }
.picker-table .col-category { width: 124px; }
.picker-table .col-specification { width: 170px; }
.picker-table .col-material { width: 120px; }
.picker-table .col-color { width: 120px; }
.picker-table .col-quantity { width: 112px; }
.picker-table .col-outsourced { width: 116px; }
.picker-table .col-inbound { width: 150px; }
.picker-table tbody tr:not(.picker-empty-row) { cursor: pointer; }
.picker-table tbody tr.is-selected td { background: #fff7f1; }
.picker-table tbody tr.is-disabled { cursor: not-allowed; }
.picker-table tbody tr.is-disabled td { color: token.$crm-text-secondary; background: #f7f5f1; }
.picker-table strong { color: token.$crm-text-primary; font-size: 13px; font-weight: 600; line-height: 20px; }
.picker-empty-row td { height: 320px; color: token.$crm-text-secondary; text-align: center; }
.picker-dialog-footer { display: flex; align-items: center; justify-content: space-between; color: token.$crm-text-secondary; }
.picker-dialog-footer > div { display: flex; gap: 12px; }

@media (max-width: 900px) {
  .outsourcing-picker-layout { grid-template-columns: 200px minmax(0, 1fr); }
}
</style>
