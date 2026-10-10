<script setup lang="ts">
import { computed, ref } from 'vue'
import { Document, Refresh } from '@element-plus/icons-vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import TubeOutsourcingDetailTable from './TubeOutsourcingDetailTable.vue'
import type { TubeOrderDetail } from '@/types/tubeOutsourcing'
import type { TubeReceipt } from '@/types/tubeReceipts'
import { buildTubeEndedResult } from '@/utils/tubeEndedReceipt'
import '@/styles/tubeOutsourcingEnded.scss'

const props = defineProps<{ order: TubeOrderDetail; receipt: TubeReceipt | null }>()
const emit = defineEmits<{ refresh: [] }>()
const dialog = ref(false)
const result = computed(() => buildTubeEndedResult(props.order, props.receipt))
const rows = computed(() => result.value.rows)
const sourceLabels = { RAW_PIPE: '原材料', PUBLIC_SEMI: '未喷塑半成品', METAL: '未入库半成品' }
const receivedAny = computed(() => result.value.received !== null ? Number(result.value.received) > 0 : null)
const warehouse = computed(() => receivedAny.value === false ? '未入库' : props.receipt?.warehouse_name || '—')
const sourcePosition = computed(() => props.order.source_kind === 'METAL' ? '金工车间 · 已报工未入库' : [props.order.warehouse_name, props.order.zone_name].filter(Boolean).join(' / ') || '—')
const info = computed<[string, string | null | undefined][]>(() => [
  ['生产任务单', props.order.task_number], ['订单号', props.order.task_order_number], ['排产单号', props.order.schedule_number],
  ['当前订单量', `${format(props.order.quantity)} ${props.order.unit || ''}`], ['计划发出日', props.order.planned_dispatch_date], ['预计回货日', props.order.expected_return_date],
  ['产品名称', props.order.product_name], ['品号', props.order.product_number], ['货号', props.order.item_number],
  ['订单颜色', props.order.color], ['建单日期', dateText(props.order.created_at)], ['建单人', props.order.created_by_name],
])
const meta = computed<[string, string | null | undefined][]>(() => [
  ['实际发出日', props.order.actual_dispatch_date], ['发出经办人', props.order.dispatched_by_name], ['发出来源位置', sourcePosition.value], ['入库状态', receivedAny.value === null ? '待核对' : receivedAny.value ? '已喷塑' : '未新增库存'],
  ['收货日期', props.receipt?.receipt_date], ['入库经办人', props.receipt?.actor_name], ['入库仓库', warehouse.value], ['入库凭证号', props.receipt?.receipt_number],
])
const receiptInfo = computed<[string, string | null | undefined][]>(() => [
  ['入库凭证号', props.receipt?.receipt_number], ['外发单号', props.receipt?.order_number], ['生产任务单', props.order.task_number], ['材料来源', sourceLabels[props.order.source_kind]],
  ['收货日期', props.receipt?.receipt_date], ['确认时间', dateTime(props.receipt?.confirmed_at)], ['入库经办人', props.receipt?.actor_name], ['入库仓库', receivedAny.value ? warehouse.value : '无实收，无需仓库'],
])
const columns = computed(() => {
  const raw = props.order.source_kind === 'RAW_PIPE'
  const widths = raw ? [85, 60, 100, 65, 90, 65, 65, 100, 115, 115, 85, 75, 85, 85, 85, 170, 105] : [95, 65, 125, 75, 100, 85, 85, 120, 100, 100, 95, 230, 150]
  const definitions: [string, string, boolean?][] = [
    ['part_name', '部位'], ['material', '材质'], ['specification', '规格'], ['thickness', '厚度 mm'], ['cutting_length_mm', '切割长度 mm'], ['raw_color', '原料颜色'], ['spray_color', '喷塑颜色'], ['factory_name', '加工厂'],
    ...(raw ? [['pieces_per_bar', '切割支数 支/根', true], ['raw_bar_length_m', '原材料长度 米/根', true]] as [string, string, boolean][] : []),
    ['dispatched_quantity', '实发（支）', true], ...(raw ? [['stock_quantity', '发出扣根', true], ['meters', '发出扣米', true]] as [string, string, boolean][] : []),
    ['received_quantity', '实收（支）', true], ['shortage_quantity', '差额（支）', true], ['shortage_reason', '差额原因'], ['zone_name', '入库库区'],
  ]
  return definitions.map(([key, label, num], index) => ({ key, label, num: Boolean(num), width: widths[index]! }))
})
const statusNote = computed(() => receivedAny.value === null ? '已结束 · 最终凭证待核对' : receivedAny.value ? '已结束 · 实收已入已喷塑公共库存' : '已结束 · 整单实收0支，未新增库存')
function format(value: unknown): string {
  return value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}
function meters(value: unknown): string {
  return value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(2)
}
function dateText(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
function dateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : `${dateText(value)} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
</script>

<template>
  <template v-if="result.available">
    <div class="panel d4-ended-context"><div class="info-grid"><div v-for="[label, value] in info" :key="label" class="info-cell"><span>{{ label }}</span><strong :title="value || '—'">{{ value || '—' }}</strong></div></div></div>
    <div class="panel workspace d4-ended-workspace">
      <div class="section-heading"><div><h2>整单回货结果</h2><span class="muted">{{ receivedAny === null ? '历史结果待核对' : receivedAny ? '已喷塑 · 全部部位保留' : '实收0支 · 未新增库存' }}</span></div><ElButton :icon="Refresh" @click="emit('refresh')">刷新</ElButton></div>
      <div class="d4-ended-meta info-grid"><div v-for="[label, value] in meta" :key="label" class="info-cell"><span>{{ label }}</span><strong :title="value || '—'">{{ value || '—' }}</strong></div></div>
      <ElAlert v-if="!result.complete" type="warning" :closable="false" show-icon :title="result.issues.join('；')" />
      <TubeOutsourcingDetailTable :columns="columns" :rows="rows" class="d4-ended-lines">
        <template #cell-part_name="{ row }"><strong>{{ row.part_name }}</strong></template>
        <template #cell-pieces_per_bar="{ row }">{{ format(row.pieces_per_bar) }}</template>
        <template #cell-raw_bar_length_m="{ row }">{{ meters(row.raw_bar_length_m) }}</template>
        <template #cell-stock_quantity="{ row }">{{ format(row.stock_quantity) }}</template>
        <template #cell-meters="{ row }">{{ meters(row.meters) }}</template>
        <template #cell-dispatched_quantity="{ row }">{{ format(row.dispatched_quantity) }}</template>
        <template #cell-received_quantity="{ row }"><strong class="brand">{{ format(row.received_quantity) }}</strong></template>
        <template #cell-shortage_quantity="{ row }"><strong :class="{ brand: Number(row.shortage_quantity) > 0 }">{{ format(row.shortage_quantity) }}</strong></template>
        <template #cell-shortage_reason="{ row }"><span class="cell-text" :title="row.shortage_reason || '—'">{{ row.shortage_reason || '—' }}</span></template>
        <template #cell-zone_name="{ row }"><span :class="{ muted: row.received_quantity === '0' }">{{ row.received_quantity === '' ? '—' : Number(row.received_quantity) === 0 ? '未入库' : row.zone_name || '—' }}</span></template>
      </TubeOutsourcingDetailTable>
      <div class="d4-ended-remarks"><div><span class="muted">原单备注</span><p>{{ order.remark || '—' }}</p></div><div><span class="muted">入库备注</span><p>{{ receipt?.remark || '—' }}</p></div></div>
    </div>
  </template>
  <div v-else class="panel d4-ended-fallback"><ElEmpty :description="result.issues.join('；')" /><ElButton :icon="Refresh" @click="emit('refresh')">重新加载</ElButton></div>
  <footer class="footer-bar d4-ended-footer"><div class="totals"><span>实发 <strong>{{ format(result.dispatched) }}</strong> 支</span><span>实收 <strong>{{ format(result.received) }}</strong> 支</span><span>差额 <strong>{{ format(result.shortage) }}</strong> 支</span><small>{{ statusNote }}</small></div><ElButton type="primary" :icon="Document" :disabled="!result.complete" @click="dialog = true">查看入库凭证</ElButton></footer>

  <AppWindowDialog :model-value="dialog && result.complete" title="喷塑入库凭证 · 只读" :width="1640" class="tube-outsourcing-detail-dialog d4-ended-dialog" @update:model-value="dialog = $event">
    <div class="d4-ended-receipt"><div class="info-grid d4-ended-receipt-context"><div v-for="[label, value] in receiptInfo" :key="label" class="info-cell"><span>{{ label }}</span><strong :title="value || '—'">{{ value || '—' }}</strong></div></div>
      <div class="d4-ended-receipt-heading"><h2>全部部位入库结果</h2><span class="muted">{{ receivedAny ? '已喷塑' : '实收0支 · 未新增库存' }}</span></div>
      <TubeOutsourcingDetailTable :columns="columns" :rows="rows" class="d4-ended-receipt-lines">
        <template #cell-pieces_per_bar="{ row }">{{ format(row.pieces_per_bar) }}</template>
        <template #cell-raw_bar_length_m="{ row }">{{ meters(row.raw_bar_length_m) }}</template>
        <template #cell-stock_quantity="{ row }">{{ format(row.stock_quantity) }}</template>
        <template #cell-meters="{ row }">{{ meters(row.meters) }}</template>
        <template #cell-dispatched_quantity="{ row }">{{ format(row.dispatched_quantity) }}</template>
        <template #cell-received_quantity="{ row }"><strong class="brand">{{ format(row.received_quantity) }}</strong></template>
        <template #cell-shortage_quantity="{ row }"><strong :class="{ brand: Number(row.shortage_quantity) > 0 }">{{ format(row.shortage_quantity) }}</strong></template>
        <template #cell-shortage_reason="{ row }"><span class="cell-text" :title="row.shortage_reason || '—'">{{ row.shortage_reason || '—' }}</span></template>
        <template #cell-zone_name="{ row }"><span :class="{ muted: Number(row.received_quantity) === 0 }">{{ Number(row.received_quantity) === 0 ? '未入库' : row.zone_name }}</span></template>
      </TubeOutsourcingDetailTable>
      <div class="d4-ended-receipt-remark"><span class="muted">入库备注</span><p>{{ receipt?.remark || '—' }}</p></div>
    </div>
    <template #footer><div class="d4-ended-receipt-footer"><span>实发 <strong>{{ format(result.dispatched) }}</strong> 支</span><span>实收 <strong>{{ format(result.received) }}</strong> 支</span><span>差额 <strong>{{ format(result.shortage) }}</strong> 支</span><ElButton type="primary" @click="dialog = false">关闭</ElButton></div></template>
  </AppWindowDialog>
</template>
