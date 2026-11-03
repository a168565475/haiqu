<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { isAxiosError, isCancel } from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import ProcessingMaterialDetails from '@/components/inventory/ProcessingMaterialDetails.vue'
import TubeOutsourcingDetailTable from './TubeOutsourcingDetailTable.vue'
import { fetchTubeOrder } from '@/api/tubeOutsourcing'
import { useIdentityOwnedStorage } from '@/composables/useIdentityOwnedStorage'
import type { TubeOrderDetail, TubePlanDispatchRecord, TubePlanReceiptRecord, TubePlanRecordCorrectionDraft } from '@/types/tubeOutsourcing'
import { isCuttingSource, tubeMaterialColumn, tubeSourceLabels, wholeTubeQuantity } from '@/utils/tubeOutsourcing'
import { formatOutsourcingMoney } from '@/utils/outsourcingPrices'

const props = defineProps<{ order: TubeOrderDetail; warehouse: boolean; blocked?: boolean; busy?: boolean; pending?: boolean; writeBlocked?: boolean; message?: string; refreshRequired?: boolean; requestConflict?: boolean }>()
const emit = defineEmits<{ correct: [payload: TubePlanRecordCorrectionDraft, etag: string]; prepared: [order: TubeOrderDetail]; active: [value: boolean]; check: []; retry: [] }>()
const owned = useIdentityOwnedStorage({ storage: 'local', key: 'tube-outsourcing-plan-records' })
const identityBlocked = computed(() => !owned.isCurrent())
const unavailable = computed(() => identityBlocked.value || props.blocked === true)
const mode = ref<'' | 'dispatch' | 'receipt'>('')
const dispatchRecord = ref<TubePlanDispatchRecord | null>(null)
const receiptRecord = ref<TubePlanReceiptRecord | null>(null)
const batch = ref<TubeOrderDetail | null>(null)
const loading = ref(false), error = ref('')
const editing = ref<'' | 'UPDATE' | 'DELETE'>(''), correctionError = ref(''), preparedEtag = ref('')
const editDate = ref('')
const editQuantities = ref<Record<string, string>>({})
const correctionLocked = computed(() => unavailable.value || props.busy || props.pending || props.writeBlocked || loading.value)
const canCorrect = computed(() => props.warehouse && props.order.is_plan && props.order.status !== 'CANCELLED'
  && (mode.value === 'dispatch' ? props.order.permissions.can_dispatch && props.order.permissions.can_correct_dispatch === true
    : props.order.permissions.can_receive === true && props.order.permissions.can_correct_receive === true))
const activeRecordId = computed(() => mode.value === 'dispatch' ? dispatchRecord.value?.id : receiptRecord.value?.id)
const activeRecordNumber = computed(() => mode.value === 'dispatch' ? dispatchRecord.value?.order_number : receiptRecord.value?.receipt_number)
const activeRecordQuantity = computed(() => mode.value === 'dispatch' ? batch.value?.total_quantity : receiptRecord.value?.total_received_quantity)
let requestSequence = 0

const cutting = computed(() => isCuttingSource(props.order.source_kind) || props.order.category === 'cutting')
const unit = computed(() => cutting.value ? '套' : '支')
const detailCutting = computed(() => mode.value === 'dispatch' && batch.value
  ? isCuttingSource(batch.value.source_kind) || batch.value.category === 'cutting' : cutting.value)
const detailUnit = computed(() => detailCutting.value ? '套' : '支')
const dispatchColumns = computed(() => [
  { key: 'order_number', label: '外发单号', width: 190 },
  { key: 'actual_dispatch_date', label: '外发日期', width: 120 },
  { key: 'source_kind', label: '材料来源', width: 170 },
  { key: 'zone_name', label: '来源库区', width: 150 },
  { key: 'total_quantity', label: `外发数量（${unit.value}）`, width: 120, num: true },
  { key: 'actor_name', label: '经办人', width: 100 },
  { key: 'action', label: '操作', width: 100 },
])
const receiptColumns = computed(() => [
  { key: 'receipt_number', label: '入库单号', width: 190 },
  { key: 'receipt_date', label: '入库日期', width: 120 },
  { key: 'warehouse_name', label: '入库仓库', width: 180 },
  { key: 'total_received_quantity', label: `入库数量（${unit.value}）`, width: 120, num: true },
  { key: 'actor_name', label: '经办人', width: 100 },
  { key: 'action', label: '操作', width: 100 },
])
const detailColumns = computed(() => [
  { key: 'part_name', label: '部位', width: 140 },
  { key: 'material', label: '材质', width: 100 },
  { key: 'specification', label: '规格', width: 150 },
  ...(detailCutting.value ? [
    { key: 'fabric_color', label: '颜色', width: 90 },
    { key: 'pieces_per_set', label: '每套片数', width: 90, num: true },
  ] : [
    { key: 'shape', label: '形状', width: 70 },
    { key: 'thickness', label: '厚度 mm', width: 85, num: true },
    { key: 'spray_color', label: '喷塑颜色', width: 95 },
    { key: 'cutting_length_mm', label: '切割长度 mm', width: 110, num: true },
  ]),
  ...(mode.value === 'dispatch' ? [
    { key: 'factory_name', label: '加工厂', width: 150 },
    { key: 'quantity', label: `实际外发（${detailUnit.value}）`, width: 120, num: true },
    ...(!props.warehouse ? [{ key: 'unit_price', label: `单价（元/${detailUnit.value}）`, width: 120, num: true }] : []),
  ] : [
    { key: 'received_quantity', label: `实际入库（${detailUnit.value}）`, width: 120, num: true },
    { key: 'zone_name', label: '入库库区', width: 150 },
  ]),
])
const materialColumns = [
  { key: 'material_number', label: '材料编号', width: 120 },
  { key: 'name', label: '辅料名称', width: 150 },
  { key: 'material', label: '材质', width: 100 },
  { key: 'specification', label: '规格', width: 150 },
  { key: 'color', label: '颜色', width: 90 },
  { key: 'quantity', label: '实际外发数量', width: 110, num: true },
  { key: 'unit', label: '单位', width: 70 },
  { key: 'factory_name', label: '加工厂', width: 140 },
  { key: 'warehouse_name', label: '来源仓库', width: 150 },
  { key: 'zone_name', label: '来源库区', width: 150 },
]
const receiptLines = computed(() => (receiptRecord.value?.lines || []).map((line, index) => {
  const saved = props.order.lines.find(item => item.id === line.order_line_id)
  return {
    ...saved,
    id: `${receiptRecord.value!.id}:${index}`,
    component_identity: line.component_identity,
    part_name: saved?.part_name || '历史部件资料未找到',
    received_quantity: line.received_quantity,
    zone_name: line.zone_name,
  }
}))
const number = (value: unknown) => value == null || value === '' || !Number.isFinite(Number(value))
  ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
function dateTime(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}
function reset() {
  requestSequence += 1
  mode.value = ''; dispatchRecord.value = null; receiptRecord.value = null
  batch.value = null; loading.value = false; error.value = ''
  editing.value = ''; correctionError.value = ''; preparedEtag.value = ''; editQuantities.value = {}
  emit('active', false)
}
function close() { if (!props.busy) reset() }
defineExpose({ completeCorrection: reset })
async function loadDispatch() {
  const record = dispatchRecord.value
  if (unavailable.value || mode.value !== 'dispatch' || !record) return
  const sequence = ++requestSequence, orderId = props.order.id, warehouse = props.warehouse
  const current = () => owned.isCurrent() && sequence === requestSequence && !props.blocked
    && props.order.id === orderId && props.warehouse === warehouse && mode.value === 'dispatch'
    && dispatchRecord.value?.id === record.id
  batch.value = null; loading.value = true; error.value = ''
  try {
    owned.assertCurrent()
    const result = await fetchTubeOrder(record.id, warehouse)
    if (!current()) return
    if (result.id !== record.id || result.is_plan || result.plan_id !== orderId) {
      throw new Error('返回的外发批次与当前委外总单不一致，请重新加载。')
    }
    batch.value = result
  } catch (cause) {
    if (!current() || isCancel(cause)) return
    error.value = isAxiosError(cause)
      ? cause.response?.data?.error?.message || cause.response?.data?.detail || '外发明细加载失败，请重试。'
      : cause instanceof Error ? cause.message : '外发明细加载失败，请重试。'
  } finally { if (current()) loading.value = false }
}
async function openDispatch(record: TubePlanDispatchRecord) {
  if (unavailable.value || props.busy || props.pending || !props.order.dispatch_records?.some(item => item.id === record.id)) return
  close(); mode.value = 'dispatch'; dispatchRecord.value = record
  await loadDispatch()
}
function openReceipt(record: TubePlanReceiptRecord) {
  if (unavailable.value || props.busy || props.pending || !props.order.receipt_records?.some(item => item.id === record.id)) return
  close(); mode.value = 'receipt'; receiptRecord.value = record
}
async function prepareCorrection(operation: 'UPDATE' | 'DELETE', preserveDraft = false) {
  if (correctionLocked.value || !canCorrect.value || !activeRecordId.value) return
  const sequence = ++requestSequence, orderId = props.order.id, warehouse = props.warehouse
  const recordId = activeRecordId.value, recordMode = mode.value
  const current = () => owned.isCurrent() && sequence === requestSequence && !props.blocked
    && props.order.id === orderId && props.warehouse === warehouse && mode.value === recordMode && activeRecordId.value === recordId
  loading.value = true; correctionError.value = ''; preparedEtag.value = ''; emit('active', true)
  try {
    owned.assertCurrent()
    const latest = await fetchTubeOrder(orderId, warehouse)
    if (!current()) return
    if (latest.id !== orderId || !latest.is_plan || !latest.etag) throw new Error('总单核对结果不完整，请重新核对。')
    if (latest.status === 'CANCELLED' || !(recordMode === 'dispatch'
      ? latest.permissions.can_dispatch && latest.permissions.can_correct_dispatch === true
      : latest.permissions.can_receive && latest.permissions.can_correct_receive === true)) throw new Error('当前没有此记录的更正权限或功能尚未启用，请刷新核对。')
    let quantities: Record<string, string>, businessDate: string
    if (recordMode === 'dispatch') {
      const record = latest.dispatch_records?.find(item => item.id === recordId)
      if (!record) throw new Error('该外发记录已变化或已删除，请关闭后刷新总单。')
      owned.assertCurrent()
      const saved = await fetchTubeOrder(recordId, warehouse)
      if (!current()) return
      if (saved.id !== recordId || saved.is_plan || saved.plan_id !== orderId) throw new Error('返回的外发批次与当前委外总单不一致，请重新核对。')
      if (!saved.lines.length || new Set(saved.lines.map(line => line.component_identity)).size !== saved.lines.length) throw new Error('原部件资料不完整，暂不能调整。')
      quantities = Object.fromEntries(saved.lines.map(line => [line.component_identity, line.quantity]))
      businessDate = saved.actual_dispatch_date || record.actual_dispatch_date
      batch.value = saved; dispatchRecord.value = record
    } else {
      const record = latest.receipt_records?.find(item => item.id === recordId)
      if (!record) throw new Error('该入库记录已变化或已删除，请关闭后刷新总单。')
      if (!record.lines.length
        || new Set(record.lines.map(line => line.component_identity)).size !== record.lines.length) throw new Error('原入库资料不完整，暂不能调整，请重新核对。')
      quantities = Object.fromEntries(record.lines.map(line => [line.component_identity, line.received_quantity]))
      businessDate = record.receipt_date; receiptRecord.value = record
    }
    if (Object.keys(quantities).some(identity => !identity)) throw new Error('原部件身份缺失，暂不能调整。')
    if (preserveDraft && (Object.keys(quantities).length !== Object.keys(editQuantities.value).length
      || Object.keys(quantities).some(identity => !(identity in editQuantities.value)))) throw new Error('原部件集合已变化，请关闭后重新打开核对。')
    if (!preserveDraft) { editQuantities.value = quantities; editDate.value = businessDate }
    editing.value = operation; preparedEtag.value = latest.etag
    emit('prepared', latest)
  } catch (cause) {
    if (!current() || isCancel(cause)) return
    correctionError.value = isAxiosError(cause) ? cause.response?.data?.error?.message || cause.response?.data?.detail || '记录核对失败，请重试。'
      : cause instanceof Error ? cause.message : '记录核对失败，请重试。'
  } finally { if (current()) { loading.value = false; if (!editing.value) emit('active', false) } }
}
function submitCorrection() {
  if (correctionLocked.value || !canCorrect.value || !editing.value || !activeRecordId.value || !preparedEtag.value || props.refreshRequired) return
  correctionError.value = ''
  const common = { record_kind: mode.value === 'dispatch' ? 'DISPATCH' as const : 'RECEIPT' as const, record_id: activeRecordId.value }
  if (editing.value === 'DELETE') { emit('correct', { ...common, operation: 'DELETE' }, preparedEtag.value); return }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(editDate.value)) { correctionError.value = '请填写业务日期。'; return }
  const lines = Object.entries(editQuantities.value).map(([component_identity, quantity]) => ({ component_identity, quantity: quantity.trim() }))
  if (!lines.length || lines.some(line => !line.component_identity || wholeTubeQuantity(line.quantity) === null || Number(line.quantity) <= 0)) {
    correctionError.value = '原部件数量都须为正整数；删除请使用“删除整次记录”。'; return
  }
  if (mode.value === 'dispatch' && batch.value?.source_kind === 'RAW_PIPE' && batch.value.lines.some(line => {
    const pieces = Number(line.pieces_per_bar), quantity = Number(editQuantities.value[line.component_identity])
    return !(pieces > 0) || quantity % pieces !== 0
  })) { correctionError.value = '原管外发数量须按保存的每根可切支数填写整根数量。'; return }
  if (mode.value === 'dispatch' && batch.value) {
    for (const line of batch.value.lines) {
      const quantity = Number(editQuantities.value[line.component_identity])
      if (quantity <= Number(line.quantity)) continue
      const parent = props.order.lines.find(item => item.component_identity === line.component_identity)
      if (!parent) { correctionError.value = '总单部件已变化，请重新核对。'; return }
      const maximum = Math.max(Number(parent.quantity) - Number(parent.dispatched_quantity ?? '0') + Number(line.quantity), 0)
      if (quantity > maximum) { correctionError.value = `${line.part_name}：本次记录最多可调整为 ${number(maximum)} ${detailUnit.value}，累计外发不能超过总单填写数量。`; return }
    }
  }
  emit('correct', { ...common, operation: 'UPDATE', business_date: editDate.value, lines }, preparedEtag.value)
}
watch([() => props.order.id, () => props.warehouse, () => props.blocked, identityBlocked], reset, { flush: 'sync' })
onBeforeUnmount(reset)
</script>

<template>
  <div class="plan-records">
    <ElAlert v-if="identityBlocked" title="身份尚未核验或已变化，请核验身份后重新打开。" type="warning" :closable="false" />
    <template v-else>
      <section class="panel plan-dispatch-records">
        <div class="section-heading"><h2>实际外发记录 · {{ order.dispatch_records?.length || 0 }} 次</h2><slot name="dispatch-action" /></div>
        <TubeOutsourcingDetailTable :columns="dispatchColumns" :rows="order.dispatch_records || []" empty="尚未登记实际外发">
          <template #cell-source_kind="{ row }">{{ tubeSourceLabels[row.source_kind] || '—' }}</template>
          <template #cell-zone_name="{ value }">{{ value || '—' }}</template>
          <template #cell-total_quantity="{ value }">{{ number(value) }}</template>
          <template #cell-actor_name="{ value }">{{ value || '—' }}</template>
          <template #cell-action="{ row }"><ElButton link type="primary" :disabled="unavailable || busy || pending" :aria-label="`查看外发明细 ${row.order_number}`" @click="openDispatch(row)">查看明细</ElButton></template>
        </TubeOutsourcingDetailTable>
      </section>
      <section class="panel plan-receipt-records">
        <div class="section-heading"><h2>实际入库记录 · {{ order.receipt_records?.length || 0 }} 次</h2><slot name="receipt-action" /></div>
        <TubeOutsourcingDetailTable :columns="receiptColumns" :rows="order.receipt_records || []" empty="尚未登记入库">
          <template #cell-warehouse_name="{ value }">{{ value || '—' }}</template>
          <template #cell-total_received_quantity="{ value }">{{ number(value) }}</template>
          <template #cell-actor_name="{ value }">{{ value || '—' }}</template>
          <template #cell-action="{ row }"><ElButton link type="primary" :disabled="unavailable || busy || pending" :aria-label="`查看入库明细 ${row.receipt_number}`" @click="openReceipt(row)">查看明细</ElButton></template>
        </TubeOutsourcingDetailTable>
        <p class="muted">回货直接关联本总单，不匹配外发批次；达到 BOM 数量后仍可继续登记实际回货。</p>
      </section>
    </template>
  </div>
  <AppWindowDialog :model-value="Boolean(mode)" :title="mode === 'dispatch' ? '外发记录明细' : '入库记录明细'" :width="1800" class="tube-outsourcing-detail-dialog plan-record-dialog" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" @update:model-value="value => { if (!value) close() }">
    <ElAlert v-if="correctionError || message" :title="correctionError || message || ''" type="warning" :closable="false" />
    <ElAlert v-if="refreshRequired && editing" title="记录或库存已变化，请重新核对后检查保留的填写内容。" type="warning" :closable="false" />
    <ElAlert v-if="editing === 'DELETE'" :title="`确认删除整次${mode === 'dispatch' ? '外发' : '入库'}记录 ${activeRecordNumber}（${number(activeRecordQuantity)} ${detailUnit}）？`" type="warning" :closable="false" :description="`本次全部部件将一起撤销，并同步更正库存和总单进度；原凭证保留审计。${mode === 'dispatch' ? '外发记录附带的辅料同时退回。' : ''}`" />
    <div v-if="editing === 'UPDATE'" class="record-edit-fields">
      <label class="form-field"><span>{{ mode === 'dispatch' ? '外发日期' : '入库日期' }}</span><ElDatePicker v-model="editDate" type="date" value-format="YYYY-MM-DD" :disabled="correctionLocked" aria-label="调整业务日期" /></label>
    </div>
    <p v-if="loading" role="status">正在读取外发批次明细…</p>
    <ElAlert v-else-if="error" :title="error" type="error" :closable="false" />
    <template v-else-if="mode === 'dispatch' && batch && dispatchRecord">
      <div class="record-info">
        <span>外发单号：<strong>{{ batch.order_number }}</strong></span><span>外发日期：{{ batch.actual_dispatch_date || dispatchRecord.actual_dispatch_date || '—' }}</span>
        <span>材料来源：{{ batch.source_label || tubeSourceLabels[batch.source_kind] }}</span><span>来源仓库：{{ batch.warehouse_name || '—' }}</span><span>来源库区：{{ batch.zone_name || '—' }}</span>
        <span>外发数量：<strong>{{ number(batch.total_quantity) }} {{ detailUnit }}</strong></span><span>经办人：{{ dispatchRecord.actor_name || '—' }}</span><span>登记时间：{{ dateTime(dispatchRecord.created_at) }}</span>
      </div>
      <TubeOutsourcingDetailTable class="dispatch-record-lines" :columns="detailColumns" :rows="batch.lines" empty="此批次没有保存部件明细">
        <template #cell-part_name="{ row }"><ProcessingMaterialDetails :materials="row">{{ row.part_name }}</ProcessingMaterialDetails></template>
        <template #cell-material="{ row }">{{ (detailCutting ? row.fabric_material || row.material : row.material) || '—' }}</template>
        <template #cell-specification="{ row }">{{ row.specification || '—' }}</template>
        <template #cell-shape="{ row }">{{ tubeMaterialColumn(row, 'shape') }}</template>
        <template #cell-thickness="{ row }">{{ tubeMaterialColumn(row, 'thickness') }}</template>
        <template #cell-spray_color="{ row }">{{ tubeMaterialColumn(row, 'spray_color') }}</template>
        <template #cell-cutting_length_mm="{ value }">{{ number(value) }}</template>
        <template #cell-pieces_per_set="{ value }">{{ number(value) }}</template>
        <template #cell-quantity="{ row, value }"><ElInput v-if="editing === 'UPDATE'" v-model="editQuantities[row.component_identity]" inputmode="numeric" :disabled="correctionLocked" :aria-label="`${row.part_name}调整数量`" /><template v-else>{{ number(value) }}</template></template>
        <template #cell-unit_price="{ value }">{{ formatOutsourcingMoney(value) }}</template>
      </TubeOutsourcingDetailTable>
      <h2 class="record-subheading">本次外发辅料</h2>
      <TubeOutsourcingDetailTable class="dispatch-record-materials" :columns="materialColumns" :rows="batch.materials || []" empty="本次未外发辅料">
        <template #cell-name="{ row }"><ProcessingMaterialDetails :materials="{ input_material_selection_snapshot: row.material_selection_snapshot }">{{ row.name }}</ProcessingMaterialDetails></template>
        <template #cell-quantity="{ value }">{{ number(value) }}</template>
      </TubeOutsourcingDetailTable>
      <p v-if="editing !== 'UPDATE'" class="record-remark">备注：{{ batch.remark || '—' }}</p>
    </template>
    <template v-else-if="mode === 'receipt' && receiptRecord">
      <div class="record-info">
        <span>入库单号：<strong>{{ receiptRecord.receipt_number }}</strong></span><span>入库日期：{{ receiptRecord.receipt_date || '—' }}</span><span>入库仓库：{{ receiptRecord.warehouse_name || '—' }}</span>
        <span>入库数量：<strong>{{ number(receiptRecord.total_received_quantity) }} {{ detailUnit }}</strong></span><span>经办人：{{ receiptRecord.actor_name || '—' }}</span><span>登记时间：{{ dateTime(receiptRecord.created_at) }}</span>
      </div>
      <TubeOutsourcingDetailTable class="receipt-record-lines" :columns="detailColumns" :rows="receiptLines" empty="此入库记录没有保存部件明细">
        <template #cell-part_name="{ row }"><ProcessingMaterialDetails :materials="{ output_material_selection_snapshot: row.output_material_selection_snapshot }">{{ row.part_name }}</ProcessingMaterialDetails></template>
        <template #cell-material="{ row }">{{ (detailCutting ? row.fabric_material || row.material : row.material) || '—' }}</template>
        <template #cell-specification="{ row }">{{ row.specification || '—' }}</template>
        <template #cell-shape="{ row }">{{ tubeMaterialColumn(row, 'shape') }}</template>
        <template #cell-thickness="{ row }">{{ tubeMaterialColumn(row, 'thickness') }}</template>
        <template #cell-spray_color="{ row }">{{ tubeMaterialColumn(row, 'spray_color') }}</template>
        <template #cell-cutting_length_mm="{ value }">{{ number(value) }}</template>
        <template #cell-pieces_per_set="{ value }">{{ number(value) }}</template>
        <template #cell-received_quantity="{ row, value }"><ElInput v-if="editing === 'UPDATE'" v-model="editQuantities[row.component_identity]" inputmode="numeric" :disabled="correctionLocked" :aria-label="`${row.part_name}调整数量`" /><template v-else>{{ number(value) }}</template></template>
      </TubeOutsourcingDetailTable>
      <p v-if="editing !== 'UPDATE'" class="record-remark">备注：{{ receiptRecord.remark || '—' }}</p>
    </template>
    <template #footer>
      <ElButton :disabled="busy" @click="close">关闭</ElButton>
      <ElButton v-if="error && mode === 'dispatch'" type="primary" :disabled="unavailable || loading || busy" @click="loadDispatch">重新加载</ElButton>
      <template v-if="pending"><ElButton :loading="busy" :disabled="unavailable || writeBlocked || busy" @click="emit('check')">核对本次提交</ElButton><ElButton v-if="!requestConflict" :disabled="unavailable || writeBlocked || busy" @click="emit('retry')">按原请求重试</ElButton></template>
      <template v-else-if="canCorrect && !error && (batch || receiptRecord)">
        <template v-if="editing"><ElButton :disabled="correctionLocked" @click="prepareCorrection(editing, true)">重新核对</ElButton><ElButton :type="editing === 'DELETE' ? 'danger' : 'primary'" :disabled="correctionLocked || !preparedEtag || refreshRequired" @click="submitCorrection">{{ editing === 'DELETE' ? '确认删除整次记录' : '保存调整' }}</ElButton></template>
        <template v-else><ElButton :disabled="correctionLocked" @click="prepareCorrection('UPDATE')">调整记录</ElButton><ElButton type="danger" :disabled="correctionLocked" @click="prepareCorrection('DELETE')">删除整次记录</ElButton></template>
      </template>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.plan-records { display: flex; flex-direction: column; gap: 14px; flex-shrink: 0; min-width: 0; }
.plan-records .section-heading { margin-bottom: 12px; }
.plan-records p { margin: 12px 0 0; }
.record-info { display: flex; flex-wrap: wrap; gap: 10px 24px; margin-bottom: 16px; line-height: 22px; overflow-wrap: anywhere; }
.record-info strong { font-weight: 500; }
.record-subheading { margin: 20px 0 12px; }
.record-remark { margin: 16px 0 0; overflow-wrap: anywhere; }
.record-edit-fields { display: grid; grid-template-columns: 220px; margin: 14px 0; }
.record-edit-fields :deep(.el-date-editor) { width: 100%; }
.plan-record-dialog :deep(.num .el-input__inner) { text-align: center; }
.plan-records :deep(.tube-detail-table), .plan-record-dialog :deep(.tube-detail-table) {
  th, td { padding: 8px 10px; white-space: normal; overflow-wrap: anywhere; }
  .cell-text { white-space: normal; overflow: visible; text-overflow: clip; }
  .num { text-align: center; }
}
</style>
