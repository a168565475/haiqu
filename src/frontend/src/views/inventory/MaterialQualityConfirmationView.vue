<script setup lang="ts">
import { hardwareReferenceCount } from '@/views/procurement/purchaseWeight'
import { pipeMeters, pipeRootsFromMeters, weighedProductionPipe } from '@/utils/pipeQuantities'
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isCancel } from 'axios'
import { useRouter } from 'vue-router'
import { useIdentityOwnedStorage } from '@/composables/useIdentityOwnedStorage'
import { Calendar, Refresh, WarningFilled } from '@element-plus/icons-vue'
import { confirmMaterialQuality, fetchMaterialQualityBatch, fetchMaterialQualityBatches } from '@/api/inventory'
import { useAuthStore } from '@/stores/auth'
import type { MaterialInbound, MaterialInboundLine } from '@/types/inventory'
import { receiptMaterialAttributeColumnWidth, receiptMaterialLeadingColumnWidths, receiptMaterialTables, receiptMaterialTableWidth } from '@/utils/receiptMaterialTables'

interface QualityRow { line: MaterialInboundLine; included: boolean; returnQuantity: string; quantityInputUnit: string; qualityRemark: string }
const auth = useAuthStore()
const router = useRouter()
const canConfirm = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.quality_confirm_material'))
const recordsQuery = computed(() => router.currentRoute?.value.query)
const recordId = computed(() => typeof recordsQuery.value?.receipt === 'string' ? recordsQuery.value.receipt : '')
const batches = ref<MaterialInbound[]>([])
const selectedBatchId = ref('')
const owned = useIdentityOwnedStorage({ storage: 'local', key: uid => `material-quality-draft:v2:${selectedBatchId.value}:user:${uid}`, legacyKeys: () => [`material-quality-draft:v2:${selectedBatchId.value}`] })
let draftRaw: string | null = null
const batch = ref<MaterialInbound | null>(null)
const taskNumber = computed(() => batch.value?.lines.find(line => line.production_task_number_snapshot)?.production_task_number_snapshot)
const rows = ref<QualityRow[]>([])
const materialTables = computed(() => receiptMaterialTables(rows.value))
const leadingColumnWidths = receiptMaterialLeadingColumnWidths
const trailingColumnWidths = [120, 178, 130, 150, 126, 192, 100]
const tableWidth = computed(() => receiptMaterialTableWidth(materialTables.value, [...leadingColumnWidths, ...trailingColumnWidths]))
const loading = ref(false)
const confirming = ref(false)
const confirmed = ref(false)
const loadError = ref('')
const bulk = reactive({ returnQuantity: '0', remark: '' })
let requestVersion = 0
let disposed = false
let dialogOpen = false
function openReceiptRecords() {
  return router.push({ name: 'purchase-receipt-records' })
}
const qualityDate = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
const locked = computed(() => !owned.isCurrent() || loading.value || confirming.value || confirmed.value || !canConfirm.value)
const selectedRows = computed(() => rows.value.filter(row => row.included))
const bulkUnit = computed(() => {
  const unit = selectedRows.value[0]?.quantityInputUnit
  return unit && selectedRows.value.every(row => row.quantityInputUnit === unit) ? unit : '按行单位'
})
const allSelected = computed({
  get: () => rows.value.length > 0 && selectedRows.value.length === rows.value.length,
  set: (value: boolean) => { if (!locked.value) rows.value.forEach(row => { row.included = value }) },
})
function setTableSelected(table: (typeof materialTables.value)[number], selected: boolean) {
  if (!locked.value) table.rows.forEach(({ row }) => { row.included = selected })
}
// 用整数单位表示万分之一，保持接口支持的 4 位小数精度。
function scaled(value: string): bigint | null {
  if (!/^\d{1,14}(\.\d{1,4})?$/.test(value)) return null
  const [whole = '0', fraction = ''] = value.split('.')
  return BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
}
function inspectByRoots(line: MaterialInboundLine): boolean {
  return line.calculation_snapshot?.receipt_quantity_mode === 'ROOTS' || weighedProductionPipe(line)
}
function isWeightPipe(line: MaterialInboundLine): boolean {
  return !inspectByRoots(line) && line.measurement_kind === 'PIPE' && (String(line.source_unit_text_snapshot || '').toUpperCase() === 'KG' || line.received_weight_kg != null || line.bar_weight_kg != null)
}
function isHardware(line: MaterialInboundLine): boolean { return line.measurement_kind === 'HARDWARE_WEIGHT' }
function hardwarePieces(line: MaterialInboundLine): boolean { return isHardware(line) && !['KG', '千克', '公斤'].includes(String(line.quantity_unit || line.piece_unit || '').toUpperCase()) }
function receivedPieces(line: MaterialInboundLine): string { return String(line.received_piece_count ?? line.received_quantity) }
function receivedInput(row: QualityRow): string {
  if (inspectByRoots(row.line)) return String(row.line.received_bar_count ?? '')
  if (isWeightPipe(row.line) || isHardware(row.line)) return String(row.line.received_weight_kg ?? '')
  return row.line.received_quantity
}
function returnRoots(row: QualityRow, quantity = row.returnQuantity): string {
  if (inspectByRoots(row.line)) return /^\d{1,14}$/.test(quantity) ? quantity : ''
  return pipeRootsFromMeters(quantity, row.line.raw_bar_length_m)
}
function acceptedPieces(row: QualityRow): bigint | null {
  const received = scaled(receivedInput(row)), returned = scaled(row.returnQuantity)
  if (received === null || returned === null || returned > received) return null
  if (returned === received) return 0n
  if (returned === 0n) {
    const count = scaled(receivedPieces(row.line))
    return count !== null && count % 10000n === 0n ? count / 10000n : null
  }
  const remaining = received - returned
  return hardwareReferenceCount(`${remaining / 10000n}.${(remaining % 10000n).toString().padStart(4, '0')}`,
    row.line.calculation_snapshot?.hardware_unit_weight_kg)
}
function partialReturnLeavesLessThanOneBar(row: QualityRow): boolean {
  if (!isWeightPipe(row.line) || row.line.calculation_snapshot?.receipt_root_rounding !== 'FLOOR') return false
  const received = scaled(receivedInput(row)), returned = scaled(row.returnQuantity)
  const barWeight = scaled(String(row.line.bar_weight_kg ?? ''))
  return received !== null && returned !== null && barWeight !== null && returned > 0n
    && returned < received && received - returned < barWeight
}
function validRow(row: QualityRow): boolean {
  if (isWeightPipe(row.line) && !/^\d{1,14}(?:\.\d{1,4})?$/.test(row.returnQuantity)) return false
  if (row.line.measurement_kind === 'PIPE' && !isWeightPipe(row.line) && returnRoots(row) === '') return false
  const returned = scaled(row.returnQuantity), received = scaled(receivedInput(row))
  if (hardwarePieces(row.line)) {
    const count = acceptedPieces(row), receivedCount = scaled(receivedPieces(row.line))
    if (count === null || receivedCount === null || receivedCount % 10000n !== 0n
      || hardwareReferenceCount(receivedInput(row), row.line.calculation_snapshot?.hardware_unit_weight_kg) !== receivedCount / 10000n
      || count > receivedCount / 10000n) return false
  }
  if (isWeightPipe(row.line)) {
    const weight = scaled(String(row.line.bar_weight_kg ?? ''))
    if (weight === null || weight <= 0n || !Number.isInteger(row.line.received_bar_count) || Number(row.line.received_bar_count) <= 0
      || partialReturnLeavesLessThanOneBar(row)) return false
  }
  if (row.line.material_catalog_id && ['根', '支', '套'].includes(row.line.source_unit_text_snapshot) && returned !== null && returned % 10000n !== 0n) return false
  return returned !== null && received !== null && received > 0n && returned <= received && row.qualityRemark.length <= 3000
}
const completeCount = computed(() => rows.value.filter(validRow).length)
const returnCount = computed(() => rows.value.filter(row => validRow(row) && scaled(row.returnQuantity)! > 0n).length)
const allComplete = computed(() => rows.value.length > 0 && rows.value.length <= 100 && completeCount.value === rows.value.length)
const canSubmit = computed(() => !locked.value && !loadError.value && batch.value?.status === 'PENDING_QUALITY' && allComplete.value)
function formatScaled(value: bigint): string {
  const whole = (value / 10000n).toLocaleString('zh-CN')
  const fraction = (value % 10000n).toString().padStart(4, '0').replace(/0+$/, '')
  return whole + (fraction ? '.' + fraction : '')
}
function formatQuantity(value: string): string { const number = scaled(value); return number === null ? '—' : formatScaled(number) }
function accepted(row: QualityRow): string { return validRow(row) ? formatScaled(scaled(receivedInput(row))! - scaled(row.returnQuantity)!) : '—' }
function receivedQuantityText(line: MaterialInboundLine): string {
  if (inspectByRoots(line)) return `${formatQuantity(String(line.received_bar_count))} 根`
  if (isHardware(line) || isWeightPipe(line)) return line.received_weight_kg == null ? '重量未记录' : `${formatQuantity(line.received_weight_kg)} kg`
  return `${formatQuantity(line.received_quantity)} ${line.source_unit_text_snapshot}`
}
function acceptedQuantityText(row: QualityRow): string {
  const quantity = accepted(row)
  return quantity === '—' ? quantity : `${quantity} ${row.quantityInputUnit || ''}`.trim()
}
function quantityInputTitle(row: QualityRow): string {
  if (inspectByRoots(row.line)) return `请填写退货整根数，最多 ${row.line.received_bar_count} 根。`
  if (partialReturnLeavesLessThanOneBar(row)) return '剩余合格重量不足一整根，请核对退货重量。'
  if (hardwarePieces(row.line) && hardwareReferenceCount('1', row.line.calculation_snapshot?.hardware_unit_weight_kg) === null) return '采购单件重量未记录或无效，无法折算'
  if (isWeightPipe(row.line) && (scaled(String(row.line.bar_weight_kg ?? '')) ?? 0n) <= 0n) return '采购单根重量未记录或无效，无法折算'
  if (row.line.measurement_kind === 'PIPE' && !isWeightPipe(row.line)) return `按原长${row.line.raw_bar_length_m}米的整数倍填写，不能超过到货数量。`
  return '不能超过到货数量，最多4位小数。'
}
function status(row: QualityRow): string {
  if (!validRow(row)) return '待完善'
  if (scaled(row.returnQuantity) === 0n) return '合格'
  return scaled(row.returnQuantity) === scaled(receivedInput(row)) ? '全部退货' : '部分退货'
}
function materialTitle(line: MaterialInboundLine): string { return line.part_name_snapshot || line.material_snapshot || '未命名物料' }
function apiMessage(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { error?: { message?: string }; detail?: string } } })?.response?.data
  return data?.error?.message || data?.detail || fallback
}
function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {} }
function readDraft(): Record<string, unknown> {
  // 无主历史草稿不读取、不迁移、不删除；损坏的 owned 普通草稿也保持原文。
  draftRaw = owned.read()
  try { return record(JSON.parse(draftRaw || '{}')) } catch { return {} }
}
async function loadBatches() {
  if (!owned.isCurrent()) { loadError.value = '身份尚未核验或已变化，请核验身份后重新打开本页。'; return }
  if (confirming.value || confirmed.value) return
  const version = ++requestVersion
  loading.value = true
  loadError.value = ''
  try {
    owned.assertCurrent()
    if (recordId.value) {
      selectedBatchId.value = recordId.value
      await selectBatch(selectedBatchId.value === batch.value?.id)
      return
    }
    const data = await fetchMaterialQualityBatches()
    owned.assertCurrent()
    if (disposed || version !== requestVersion) return
    batches.value = data.filter(item => item.status === 'PENDING_QUALITY')
    const id = batches.value.some(item => item.id === selectedBatchId.value) ? selectedBatchId.value : batches.value[0]?.id || ''
    const preserve = id === batch.value?.id
    selectedBatchId.value = id
    // 列表已经返回完整批次，直接使用本次响应，省去首个批次的重复读取。
    await selectBatch(preserve, batches.value.find(item => item.id === id))
  } catch (error) {
    if (!isCancel(error) && owned.isCurrent() && !disposed && version === requestVersion) { loadError.value = apiMessage(error, '待质检批次加载失败，请刷新重试。'); loading.value = false }
  }
}
async function selectBatch(preserve = false, loadedBatch?: MaterialInbound) {
  if (!owned.isCurrent()) return
  if (confirming.value || confirmed.value) return
  const version = ++requestVersion, id = selectedBatchId.value
  const previous = preserve ? new Map(rows.value.map(row => [row.line.id, row])) : new Map<string, QualityRow>()
  if (!preserve) { batch.value = null; rows.value = [] }
  loadError.value = ''
  loading.value = Boolean(id)
  if (!id) return
  try {
    owned.assertCurrent()
    const data = loadedBatch?.id === id ? loadedBatch : await fetchMaterialQualityBatch(id)
    owned.assertCurrent()
    if (disposed || version !== requestVersion) return
    const draft = readDraft()
    batch.value = data
    rows.value = data.lines.map(line => {
      const saved = previous.get(line.id) || record(draft[line.id])
      const hasSavedQuantity = typeof saved.returnQuantity === 'string' || typeof saved.returnQuantity === 'number'
      const savedQuantity = hasSavedQuantity ? String(saved.returnQuantity) : ''
      const byRoots = inspectByRoots(line)
      const oldWeightDraft = weighedProductionPipe(line) && hasSavedQuantity && saved.quantityInputUnit !== '根'
      const oldWeight = oldWeightDraft ? scaled(savedQuantity) : null
      // 旧草稿只记录退货公斤。部分退货的根数由质检员核对。
      const savedRoots = oldWeightDraft
        ? oldWeight === 0n ? '0' : oldWeight !== null && oldWeight === scaled(line.received_weight_kg!) ? String(line.received_bar_count) : ''
        : hasSavedQuantity && saved.quantityInputUnit === '根' ? savedQuantity : String(line.return_bar_count ?? 0)
      return { line, included: typeof saved.included === 'boolean' ? saved.included : true,
        quantityInputUnit: byRoots ? '根' : isWeightPipe(line) || isHardware(line) ? 'kg' : line.source_unit_text_snapshot,
        returnQuantity: byRoots ? savedRoots
          : hasSavedQuantity ? line.measurement_kind === 'PIPE' && !isWeightPipe(line) && saved.quantityInputUnit === undefined ? pipeMeters(savedQuantity, line.raw_bar_length_m) : savedQuantity
          : isWeightPipe(line) || isHardware(line) ? String(line.return_weight_kg ?? 0) : line.return_quantity || '0.00',
        qualityRemark: typeof saved.qualityRemark === 'string' ? saved.qualityRemark : line.quality_remark || '' }
    })
    if (data.status !== 'PENDING_QUALITY') loadError.value = '此批次已完成品质确认，请刷新选择其他批次。'
  } catch (error) {
    if (!isCancel(error) && owned.isCurrent() && !disposed && version === requestVersion) loadError.value = apiMessage(error, '待质检明细或当前用户草稿无法读取，请刷新重试。')
  } finally { if (owned.isCurrent() && !disposed && version === requestVersion) loading.value = false }
}
function applyBulk() {
  if (locked.value || loadError.value) return
  if (!selectedRows.value.length) return ElMessage.warning('请先勾选需要批量设置的明细。')
  const quantity = scaled(bulk.returnQuantity)
  if (quantity === null || selectedRows.value.some(row => row.line.measurement_kind === 'PIPE' && !isWeightPipe(row.line) && returnRoots(row, bulk.returnQuantity) === '') || bulk.remark.length > 3000 || selectedRows.value.some(row => { const received = scaled(receivedInput(row)); return received === null || quantity > received })) return ElMessage.warning('请按各行单位填写退货数量，不能超过到货数量。管材按整根退货。')
  selectedRows.value.forEach(row => { row.returnQuantity = bulk.returnQuantity; if (bulk.remark) row.qualityRemark = bulk.remark })
}
function saveDraft() {
  if (!batch.value || locked.value) return
  try {
    const raw = JSON.stringify(Object.fromEntries(rows.value.map(row => [row.line.id, { returnQuantity: row.returnQuantity, quantityInputUnit: row.quantityInputUnit, qualityRemark: row.qualityRemark }])))
    owned.write(raw); draftRaw = raw
    ElMessage.success('质检草稿已保存在当前浏览器。')
  } catch { ElMessage.error('浏览器无法保存草稿，填写内容仍保留在页面中。') }
}
function qualityPayload(row: QualityRow) {
  const common = { line_id: row.line.id, expected_received_quantity: receivedInput(row), quality_remark: row.qualityRemark }
  if (weighedProductionPipe(row.line)) {
    return { ...common, expected_received_quantity: row.line.received_weight_kg, return_bar_count: row.returnQuantity }
  }
  if (isHardware(row.line) || isWeightPipe(row.line)) return { ...common, return_weight_kg: row.returnQuantity }
  if (row.line.measurement_kind === 'PIPE') return { ...common, return_bar_count: returnRoots(row) }
  return { ...common, return_quantity: row.returnQuantity }
}
async function confirmInbound() {
  if (!owned.isCurrent() || !canSubmit.value || !batch.value) return
  const id = batch.value.id, consumedDraftRaw = draftRaw
  // 勾选只控制批量设置；接口要求提交整个批次，并冻结确认框打开前的内容。
  const payload = { items: rows.value.map(qualityPayload) }
  confirming.value = true
  try {
    dialogOpen = true
    try {
      await ElMessageBox.confirm(`确认本批次全部 ${payload.items.length} 项质检结果？系统会根据质检结果更新库存和应付，有退货时生成退货单。`, '确认质检', {
        type: 'warning',
        confirmButtonText: '确认质检',
        cancelButtonText: '取消',
        customClass: 'quality-confirm-dialog',
        confirmButtonClass: 'quality-confirm-dialog__confirm',
        cancelButtonClass: 'quality-confirm-dialog__cancel',
      })
    } catch { return } finally { dialogOpen = false }
    owned.assertCurrent()
    if (disposed || !canConfirm.value || selectedBatchId.value !== id) return
    await confirmMaterialQuality(id, payload)
    owned.assertCurrent()
    if (selectedBatchId.value !== id) return
    confirmed.value = true
    try { if (consumedDraftRaw !== null && !owned.removeIfUnchanged(consumedDraftRaw)) ElMessage.warning('入库已成功，但当前用户草稿已变化，已保留后写入内容。') } catch { if (!owned.isCurrent()) return; ElMessage.warning('入库已成功，但当前用户草稿未能清除。') }
    if (disposed) return
    ElMessage.success('品质确认完成，库存和采购应付已按质检结果更新。')
    try {
      await openReceiptRecords()
    }
    catch { if (owned.isCurrent()) ElMessage.warning('入库已成功，请从采购入库列表继续。') }
  } catch (error) {
    if (!isCancel(error) && owned.isCurrent() && !disposed) {
      ElMessage.error(apiMessage(error, '品质确认失败，填写内容已保留。'))
      if ((error as { response?: { status?: number } })?.response?.status === 409) loadError.value = '批次数据已变化，请刷新后重新核对。'
    }
  } finally { if (owned.isCurrent()) confirming.value = false }
}
onMounted(() => { if (canConfirm.value) void loadBatches() })
onBeforeUnmount(() => { disposed = true; requestVersion++; if (dialogOpen) ElMessageBox.close() })
</script>

<template>
  <section class="inventory-workflow quality-page erp-glass-form" data-testid="material-quality-confirmation-page">
    <div v-if="!canConfirm" class="empty-state"><h1>无权进行品质确认</h1><p>请联系管理员开通材料品质确认权限。</p></div>
    <template v-else>
      <header class="page-title-row"><div><h1>品质确认</h1><p>核对仓库到货，填写退货数量并确认合格入库数量。</p></div><div><ElButton :disabled="confirming" @click="openReceiptRecords">返回品质检验</ElButton><ElButton :icon="Refresh" :disabled="locked" @click="loadBatches">刷新</ElButton></div></header>
      <div v-if="loadError" class="load-error" role="alert">{{ loadError }}</div>
      <section class="surface bulk-card erp-flat-form">
        <div class="bulk-row"><h2>本次质检设置</h2><div class="date-field"><label>质检日期</label><ElInput :model-value="qualityDate" :prefix-icon="Calendar" disabled aria-label="质检日期" /></div><div class="bulk-controls"><label for="bulk-return">退货数量</label><ElInput id="bulk-return" v-model="bulk.returnQuantity" class="quantity-input" :disabled="locked" maxlength="19" inputmode="decimal" aria-label="批量退货数量"><template #append>{{ bulkUnit }}</template></ElInput><ElInput v-model="bulk.remark" :disabled="locked" maxlength="3000" placeholder="批量质检说明（可选）" aria-label="批量质检说明" /><ElButton :disabled="locked || !!loadError" @click="applyBulk">应用到已勾选</ElButton></div></div>
      </section>
      <section class="surface table-card">
        <div class="table-head">
          <div><h2>品质确认明细</h2><div class="table-order-meta">
            <template v-if="batch">
              <span v-if="batch.sample_number">打样单号 <strong>{{ batch.sample_number }}</strong></span>
              <span v-else-if="taskNumber">生产任务单号 <strong>{{ taskNumber }}</strong></span>
              <span>入库单号 {{ batch.inbound_number }}</span>
              <span>采购单号 {{ batch.purchase_order_number || '—' }}</span>
              <span>状态 <ElTag type="warning" round>待质检</ElTag></span>
            </template>
            <span v-if="!recordId" class="batch-selector"><label>批次</label><ElSelect v-model="selectedBatchId" aria-label="选择待质检批次" filterable :disabled="locked" :loading="loading" placeholder="入库单号 / 采购单号 / 供应商" @change="selectBatch()"><ElOption v-for="item in batches" :key="item.id" :value="item.id" :label="`${item.inbound_number} · ${item.purchase_order_number || '—'} · ${item.lines[0]?.supplier_name_snapshot || '—'}`" /></ElSelect></span>
          </div></div>
          <div class="table-summary">
            <ElCheckbox v-if="materialTables.length > 1" v-model="allSelected" :indeterminate="selectedRows.length > 0 && !allSelected" :disabled="locked">全选明细</ElCheckbox>
            <strong>共 {{ rows.length }} 项</strong>
          </div>
        </div>
        <div v-loading="loading" class="quality-table-scroll">
          <section v-for="table in materialTables" :key="table.key" class="receipt-material-group" :data-material-category="table.key">
          <h3 v-if="materialTables.length > 1 || !['ALL', 'TUBE', 'OTHER'].includes(table.key)">{{ table.label }}</h3>
          <table class="erp-table-editor quality-table" :aria-label="table.label || '品质确认明细'" :style="{ minWidth: `${tableWidth}px` }">
            <colgroup>
              <col v-for="(width, index) in leadingColumnWidths" :key="`leading-${index}`" :style="{ width: `${width}px` }" />
              <col v-for="(label, index) in table.columns" :key="label" :style="{ width: index < table.columns.length - 1 ? `${receiptMaterialAttributeColumnWidth(label)}px` : undefined }" />
              <col v-for="(width, index) in trailingColumnWidths" :key="`trailing-${index}`" :style="{ width: table.columns.length || index < trailingColumnWidths.length - 1 ? `${width}px` : undefined }" />
            </colgroup>
            <thead><tr>
              <th><ElCheckbox :model-value="table.rows.length > 0 && table.selected === table.rows.length" :aria-label="materialTables.length > 1 ? `全选${table.label}` : '全选明细'" :disabled="locked || !table.rows.length" :indeterminate="table.selected > 0 && table.selected < table.rows.length" @update:model-value="setTableSelected(table, $event === true)" /></th><th scope="col">序号</th><th scope="col">物料信息</th>
              <th scope="col">供应商</th>
              <th v-for="label in table.columns" :key="label" scope="col">{{ label }}</th>
              <th v-for="title in ['到货数量', '退货数量', '合格入库数量', '材料仓', '库区', '退货/质检说明', '状态']" :key="title" scope="col">{{ title }}</th>
            </tr></thead>
            <tbody>
              <tr v-for="({ row, number, attributes }) in table.rows" :key="row.line.id">
                <td><ElCheckbox v-model="row.included" :aria-label="`勾选第 ${number} 项`" :disabled="locked" /></td><td class="muted">{{ number }}</td>
                <td class="material-cell"><strong>{{ materialTitle(row.line) }}</strong></td>
                <ElTooltip :content="row.line.supplier_name_snapshot" placement="top" :show-after="150" :disabled="!row.line.supplier_name_snapshot" :teleported="true">
                  <td class="supplier-cell">{{ row.line.supplier_name_snapshot || '—' }}</td>
                </ElTooltip>
                <td v-for="label in table.columns" :key="label">{{ attributes.get(label) ?? '—' }}</td>
                <td class="quantity-cell" :title="receivedQuantityText(row.line)">{{ receivedQuantityText(row.line) }}</td>
                <td class="return-quantity-cell"><ElInput v-model="row.returnQuantity" class="quantity-input" :aria-label="`第 ${number} 项退货${isWeightPipe(row.line) || isHardware(row.line) ? '重量' : '数量'}`" :aria-invalid="!validRow(row)" :class="{ 'invalid-field': !validRow(row) }" :disabled="locked" maxlength="19" inputmode="decimal" :title="quantityInputTitle(row)"><template #append>{{ row.quantityInputUnit || '单位未识别' }}</template></ElInput>
                </td>
                <td class="quantity-cell success-text" :title="acceptedQuantityText(row)"><b>{{ acceptedQuantityText(row) }}</b></td>
                <td class="muted">{{ row.line.warehouse_name }}</td><td class="muted">{{ row.line.zone_name }}</td>
                <td class="remark-cell"><ElInput v-model="row.qualityRemark" :aria-label="`第 ${number} 项质检说明`" :disabled="locked" maxlength="3000" placeholder="有退货时填写原因" /></td>
                <td><ElTag :type="!validRow(row) ? 'warning' : status(row) === '合格' ? 'success' : 'danger'" round>{{ status(row) }}</ElTag></td>
              </tr>
              <tr v-if="!table.rows.length"><td :colspan="leadingColumnWidths.length + trailingColumnWidths.length" class="table-empty">{{ loadError || (loading ? '正在加载…' : '暂无待质检明细') }}</td></tr>
            </tbody>
          </table>
          </section>
        </div>
        <footer><span>已勾选 {{ selectedRows.length }} 项 · {{ returnCount }} 项有退货</span><strong :class="{ complete: allComplete }">{{ allComplete ? `全部 ${rows.length} 项填写完整` : `已完成 ${completeCount} / ${rows.length} 项，请检查退货数量` }}</strong></footer>
      </section>
      <footer class="submit-bar"><div class="submit-notice"><ElIcon><WarningFilled /></ElIcon><span>有退货时填写数量和原因。确认质检后生成退货单，并同步调整库存和应付。</span></div><ElButton :disabled="locked || !batch" @click="saveDraft">保存质检草稿</ElButton><ElButton type="primary" :loading="confirming" :disabled="!canSubmit" @click="confirmInbound">确认质检</ElButton></footer>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;

.inventory-workflow { box-sizing: border-box; height: auto; min-height: 0; overflow: visible; padding: 0; background: transparent; color: token.$crm-text-primary; font: 13px/20px token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-text-color-primary: #{token.$crm-text-primary}; --el-text-color-regular: #{token.$crm-text-secondary}; --el-text-color-placeholder: #{token.$crm-text-muted}; --el-border-color: #{token.$crm-border-default}; --el-border-color-light: #{token.$crm-border-subtle}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-fill-color-light: #{token.$crm-color-subtle}; --el-border-radius-base: 5px;
}
.page-title-row, .table-head, .bulk-row, .date-field, .bulk-controls, .submit-bar { display: flex; align-items: center; }
h1, h2, p { margin: 0; } h2 { font-size: 16px; line-height: 22px; font-weight: 700; white-space: nowrap; }
.page-title-row { height: 54px; justify-content: space-between; margin-bottom: 10px; }
h1 { font: 700 34px/44px token.$crm-font-display; letter-spacing: -1px; }
.page-title-row p { color: token.$crm-text-secondary; line-height: 18px; }
.page-title-row > .el-button { width: 104px; height: 32px; }
.surface { @include detail.surface; }
.load-error { box-sizing: border-box; min-height: 40px; padding: 9px 16px; margin-bottom: 12px; border: 1px solid token.$crm-danger; border-radius: 5px; background: token.$crm-danger-soft; color: token.$crm-danger; }
.bulk-card { box-sizing: border-box; height: 60px; padding: 13px 21px; margin-bottom: 14px; }
.bulk-row { height: 32px; gap: 20px; }
.date-field { gap: 10px; margin-left: auto; }
.date-field label, .bulk-controls label { color: token.$crm-text-secondary; white-space: nowrap; }
.date-field > .el-input { width: 170px; }
.date-field :deep(.el-input__wrapper) { background: var(--erp-input-surface); }
.date-field :deep(.el-input__inner) { -webkit-text-fill-color: token.$crm-text-secondary; }
.bulk-controls { height: 32px; gap: 10px; }
.bulk-controls > .el-input:nth-child(2) { width: 184px; }
.bulk-controls > .el-input:nth-child(3) { width: 280px; }
.bulk-controls > .el-button { width: 140px; }
.table-card { box-sizing: border-box; height: calc(100dvh - 306px); min-height: 370px; display: flex; flex-direction: column; overflow: hidden; margin-bottom: 12px; }
.table-head { flex: 0 0 51px; justify-content: space-between; padding: 0 21px; border-bottom: 1px solid token.$crm-border-subtle; }
.table-head > div { display: flex; gap: 22px; align-items: center; min-width: 0; }
.table-order-meta { display: flex; align-items: center; gap: 24px; min-width: 0; color: token.$crm-text-secondary; font-size: 12px; }
.table-order-meta span { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.table-order-meta strong { color: token.$crm-text-primary; font-weight: 700; }
.table-order-meta .batch-selector { gap: 8px; }
.batch-selector > .el-select { width: 320px; }
.table-head .table-summary { gap: 12px; margin-right: 16px; font-size: 13px; white-space: nowrap; }
.receipt-material-group + .receipt-material-group { margin-top: 10px; }
.receipt-material-group h3 { position: sticky; left: 0; width: max-content; margin: 0; padding: 5px 16px; color: var(--erp-table-header-text); font-size: 13px; }
.quality-table-scroll { flex: 1; min-height: 0; overflow: auto; }
.quality-table { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; background: var(--erp-table-body-fill); }
.quality-table th, .quality-table td { box-sizing: border-box; padding: 4px 8px; border-right: 1px solid var(--erp-table-grid); border-bottom: 1px solid var(--erp-table-grid); text-align: center; overflow-wrap: anywhere; }
.quality-table th:nth-child(2), .quality-table td:nth-child(2) { white-space: nowrap; overflow-wrap: normal; }
.quality-table th { height: 44px; position: sticky; top: 0; z-index: 2; background: var(--erp-table-header-fill); font-size: 12px; font-weight: 500; color: var(--erp-table-header-text); }
.quality-table td { height: 58px; } .quality-table th:last-child, .quality-table td:last-child { border-right: 0; }
.quality-table .quantity-cell { white-space: nowrap; overflow: hidden; overflow-wrap: normal; text-overflow: ellipsis; }
.quality-table th:first-child, .quality-table td:first-child { padding: 0; vertical-align: middle; }
.quality-table th:first-child :deep(.el-checkbox), .quality-table td:first-child :deep(.el-checkbox) { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; margin: 0; }
.quality-table .material-cell { text-align: left; padding: 4px 18px; } .material-cell strong, .material-cell small { display: block; font-weight: 400; } .material-cell small { font-size: 13px; color: token.$crm-text-secondary; }
.quality-table .supplier-cell { font-size: 13px; color: var(--erp-table-text); white-space: nowrap; overflow: hidden; overflow-wrap: normal; text-overflow: ellipsis; } .muted { color: token.$crm-text-secondary; } .quality-table .remark-cell { padding: 4px 13px; }
.quality-table .return-quantity-cell { padding: 4px 11px; }
.quantity-input :deep(.el-input-group__append) { box-sizing: border-box; flex: 0 0 64px; width: 64px; padding: 0; font-size: 12px; white-space: nowrap; }
.success-text { color: token.$crm-success; }
.table-empty { height: 230px !important; color: token.$crm-text-secondary; }
.table-card footer { box-sizing: border-box; flex: 0 0 44px; display: flex; align-items: center; justify-content: space-between; padding: 0 21px; color: token.$crm-text-secondary; border-top: 1px solid token.$crm-border-subtle; }
.table-card footer strong { font-weight: 400; color: token.$crm-warning; } .table-card footer .complete { color: token.$crm-success; }
.submit-bar { height: 32px; gap: 20px; }
.submit-notice { display: flex; flex: 1; min-width: 0; align-items: center; gap: 10px; color: token.$crm-warning; }
.submit-notice .el-icon { flex: 0 0 auto; font-size: 18px; }
.submit-notice span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.submit-bar > .el-button { width: 140px; height: 32px; margin: 0; }
.submit-bar > .el-button--primary { width: 160px; }
.inventory-workflow :deep(.el-button) { height: 32px; font-size: 13px; border-radius: 5px; font-family: inherit; }
.inventory-workflow :deep(.el-input__wrapper), .inventory-workflow :deep(.el-select__wrapper) { box-sizing: border-box; height: 32px; min-height: 32px; border-radius: var(--erp-radius-control); font-size: 13px; background: var(--erp-input-surface); color: token.$crm-text-secondary; box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset; }
.inventory-workflow :deep(.el-input__wrapper.is-focus), .inventory-workflow :deep(.el-select__wrapper.is-focused) { box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }
.inventory-workflow :deep(.el-input__inner) { color: token.$crm-text-secondary; font-family: inherit; height: 30px; }
.inventory-workflow :deep(.el-select__selected-item) { color: token.$crm-text-secondary; }
.inventory-workflow :deep(.el-tag) { height: 24px; min-width: 64px; padding: 0 10px; border: 0; font-size: 11px; font-family: inherit; }
.inventory-workflow :deep(.el-tag--success) { background: var(--erp-tag-success-background); color: var(--erp-color-text-inverse); }
.inventory-workflow :deep(.el-tag--warning) { background: var(--erp-tag-warning-background); color: var(--erp-color-text-inverse); }
.inventory-workflow :deep(.el-checkbox__inner) { width: 14px; height: 14px; border-radius: 2px; }
.inventory-workflow :deep(.invalid-field .el-input__wrapper) { box-shadow: 0 0 0 1px token.$crm-danger inset; }
.quality-table :deep(.el-tag) { width: 80px; }
.quality-page :deep(.el-tag--danger) { color: var(--erp-color-text-inverse); background: var(--erp-tag-danger-background); }
.empty-state { padding: 80px; text-align: center; color: token.$crm-text-secondary; }
:global(.quality-confirm-dialog .el-message-box__btns) { gap: 12px; }
:global(.quality-confirm-dialog .el-message-box__btns .el-button) { min-width: 80px; height: 32px; margin: 0; border-radius: 5px; font: 500 13px/20px token.$crm-font-body; }
:global(.quality-confirm-dialog .quality-confirm-dialog__confirm) { border-color: var(--erp-button-primary-border) !important; background: var(--erp-button-primary-surface) !important; color: token.$crm-text-inverse !important; }
:global(.quality-confirm-dialog .quality-confirm-dialog__confirm:hover) { border-color: var(--erp-button-primary-border) !important; background: var(--erp-button-primary-hover-surface) !important; }

@media (max-width: 1400px) {
  .bulk-row { gap: 12px; }
  .date-field { margin-left: 0; }
  .bulk-controls > .el-input:nth-child(3) { width: 190px; }
  .table-order-meta { gap: 8px; }
  .batch-selector > .el-select { width: 200px; }
}
</style>
