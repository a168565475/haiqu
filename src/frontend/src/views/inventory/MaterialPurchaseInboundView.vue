<script setup lang="ts">
import { hardwareReferenceCount } from '@/views/procurement/purchaseWeight'
import { compactDecimal } from '@/utils/compactDecimal'
import { pipeMeters, pipeRootError, pipeRootsFromMeters, pipeRootsFromWeight } from '@/utils/pipeQuantities'
import { computed, onBeforeUnmount, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { isCancel } from 'axios'
import { useIdentityOwnedStorage } from '@/composables/useIdentityOwnedStorage'
import { Calendar, Refresh, Tickets, WarningFilled } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { createMaterialReceiving, createSampleMaterialReceiving, fetchEligibleMaterialLinesWithVersion, fetchEligibleMaterialPurchaseOrders, fetchMaterialReceivingOptions } from '@/api/inventory'
import { useAuthStore } from '@/stores/auth'
import type { EligibleMaterialLine, EligibleMaterialPurchaseOrder, MaterialReceivingOptions, SampleMaterialReceivingPayload } from '@/types/inventory'
import { materialAttributeFields, materialSpecificationValue } from '@/utils/materialAttributes'
import { receiptMaterialAttributeColumnWidth, receiptMaterialLeadingColumnWidths, receiptMaterialTables, receiptMaterialTableWidth } from '@/utils/receiptMaterialTables'
import { createClientUuid } from '@/utils/clientUuid'
import PurchaseInboundHistory from '@/components/procurement/PurchaseInboundHistory.vue'

interface ReceivingRow {
  line: EligibleMaterialLine
  included: boolean
  receivedQuantity: string
  quantityInputUnit: string
  warehouseId: string
  zoneId: string
  remark: string
}
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const materialSection = computed(() => typeof route.query?.material_section === 'string' ? route.query.material_section : undefined)
const materialSectionLabel = ref('')
function fetchReceivingLines(orderId: string) {
  return materialSection.value
    ? fetchEligibleMaterialLinesWithVersion(orderId, materialSection.value)
    : fetchEligibleMaterialLinesWithVersion(orderId)
}
const canReceive = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.receive_material'))
const canQuality = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.quality_confirm_material'))
const baseLoading = ref(false)
const linesLoading = ref(false)
const loading = computed(() => baseLoading.value || linesLoading.value)
const submitting = ref(false)
const receiptCreated = ref(false)
const historyRefreshKey = ref(0)
const locked = computed(() => !owned.isCurrent() || loading.value || submitting.value || receiptCreated.value)
const loadError = ref('')
const purchaseOrders = ref<EligibleMaterialPurchaseOrder[]>([])
const selectedPurchaseOrderId = ref('')
const options = ref<MaterialReceivingOptions>({ warehouses: [], zones: [] })
const rows = ref<ReceivingRow[]>([])
const allRowsByRoots = computed(() => rows.value.length > 0 && rows.value.every(row => row.line.receipt_quantity_mode === 'ROOTS'))
const hoveredRowId = ref('')
const hoveredSupplierRowId = ref('')
const focusedQuantity = shallowRef<{ row: ReceivingRow; input: HTMLElement }>()
const bulk = reactive({ category: '', warehouseId: '', zoneId: '' })
function localToday() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
}
const form = reactive({ inboundDate: localToday(), remark: '' })
const receivingDraftKey = computed(() => `material-receiving-draft:v2:${selectedPurchaseOrderId.value}${materialSection.value ? ':' + materialSection.value : ''}`)
const owned = useIdentityOwnedStorage({ storage: 'local', key: uid => `${receivingDraftKey.value}:user:${uid}`, legacyKeys: () => [receivingDraftKey.value] })
let draftRaw: string | null = null
let linesRequest = 0
let disposed = false
const selectedOrder = computed(() => purchaseOrders.value.find((item) => item.id === selectedPurchaseOrderId.value))
const isSample = computed(() => selectedOrder.value?.source_type === 'SAMPLE')
const materialTables = computed(() => receiptMaterialTables(rows.value, !isSample.value))
const sampleColumnWidths = [56, 58, 230, 190, 234, 160, 106, 200, 182, 164, 214, 124]
const leadingColumnWidths = receiptMaterialLeadingColumnWidths
const trailingColumnWidths = [120, 118, 112, 178, 160, 144, 192, 100]
const tableWidth = computed(() => receiptMaterialTableWidth(materialTables.value, [...leadingColumnWidths, ...trailingColumnWidths]))
const receivingVersion = ref('')
let sampleAttempt: { fingerprint: string; payload: SampleMaterialReceivingPayload } | null = null
const selectedRows = computed(() => isSample.value ? rows.value : rows.value.filter((row) => row.included))
const bulkCategories = computed(() => [...new Set(rows.value.map((row) => row.line.category?.trim() || '未分类'))])
const bulkSelectedRows = computed(() => selectedRows.value.filter((row) => !bulk.category || (row.line.category?.trim() || '未分类') === bulk.category))
const bulkApplyLabel = computed(() => isSample.value ? (bulk.category ? '应用到当前分类' : '应用到全部') : '应用到已勾选')
const warehouseZones = (warehouseId: string) => options.value.zones.filter((zone) => zone.warehouse === warehouseId)
const rowWarehouses = (line: EligibleMaterialLine) => options.value.warehouses.filter(warehouse =>
  !warehouse.warehouse_type || warehouse.warehouse_type === (line.material_selection_snapshot?.processing_state === 'PROCESSED' ? 'SEMI_FINISHED' : 'MATERIAL'))
const validRowZone = (row: ReceivingRow) => hasZone(row) && rowWarehouses(row.line).some(warehouse => warehouse.id === row.warehouseId)
const bulkWarehouses = computed(() => bulkSelectedRows.value.length ? options.value.warehouses.filter(warehouse =>
  bulkSelectedRows.value.every(row => rowWarehouses(row.line).some(allowed => allowed.id === warehouse.id))) : [])
const bulkWarehouseHint = computed(() => bulkSelectedRows.value.length && !bulkWarehouses.value.length
  ? '勾选物料没有共同可用仓库，请逐行分配仓库和库区。' : '')
const bulkReadyToApply = computed(() => !locked.value && canReceive.value && hasZone(bulk)
  && bulkWarehouses.value.some(warehouse => warehouse.id === bulk.warehouseId))
const bulkZones = computed(() => warehouseZones(bulk.warehouseId))
watch(bulkWarehouses, warehouses => {
  if (bulk.warehouseId && !warehouses.some(warehouse => warehouse.id === bulk.warehouseId)) {
    bulk.warehouseId = ''; bulk.zoneId = ''
  }
})
function hasZone(row: Pick<ReceivingRow, 'warehouseId' | 'zoneId'>) {
  return options.value.warehouses.some((warehouse) => warehouse.id === row.warehouseId)
    && warehouseZones(row.warehouseId).some((zone) => zone.id === row.zoneId)
}
function isPipe(line: EligibleMaterialLine): line is EligibleMaterialLine & { raw_bar_length_m: string } {
  return !!line.raw_bar_length_m
}
function isWeightPipe(line: EligibleMaterialLine): boolean {
  return isPipe(line) && line.receipt_quantity_mode !== 'ROOTS' && (line.weight_unit === true || String(line.unit || '').toUpperCase() === 'KG')
}
function receivedRoots(row: ReceivingRow): string {
  if (row.line.receipt_quantity_mode === 'ROOTS') return row.receivedQuantity
  if (!isWeightPipe(row.line)) return pipeRootsFromMeters(row.receivedQuantity, row.line.raw_bar_length_m)
  if (isSample.value) return pipeRootsFromWeight(row.receivedQuantity, row.line.raw_bar_weight_kg)
  return hardwareReferenceCount(row.receivedQuantity, row.line.raw_bar_weight_kg)?.toString() ?? ''
}
function isHardware(line: EligibleMaterialLine): boolean {
  return line.measurement_kind === 'HARDWARE_WEIGHT'
}
function hardwarePieces(line: EligibleMaterialLine): boolean {
  return isHardware(line) && !['KG', '千克', '公斤'].includes(String(line.quantity_unit || line.piece_unit || '').toUpperCase())
}
function referencePieces(row: ReceivingRow): bigint | null { return hardwareReferenceCount(row.receivedQuantity, row.line.unit_weight_kg) }
const quantityPattern = /^\d{1,14}(?:\.\d{1,4})?$/
function weightConversionError(row: ReceivingRow): string {
  if (isWeightPipe(row.line)) {
    if (hardwareReferenceCount('1', row.line.raw_bar_weight_kg) === null) return '采购单根重量未记录或无效，无法折算'
    if (quantityPattern.test(row.receivedQuantity) && receivedRoots(row) === '0') return '折合 0 根，本次入库至少需要 1 根'
  }
  if (hardwarePieces(row.line) && hardwareReferenceCount('1', row.line.unit_weight_kg) === null) return '采购单件重量未记录或无效，无法折算'
  return ''
}
const focusedWeightConversion = computed(() => {
  const row = focusedQuantity.value?.row
  if (!row) return ''
  const error = weightConversionError(row)
  if (!quantityPattern.test(row.receivedQuantity)) return error
  if (isWeightPipe(row.line)) {
    const roots = receivedRoots(row)
    if (!roots) return error
    const result = error || `折合 ${roots} 根`
    return `每根 ${compactDecimal(row.line.raw_bar_weight_kg)} 公斤，${result}`
  }
  if (error || !hardwarePieces(row.line)) return error
  const count = referencePieces(row)
  const unit = row.line.quantity_unit || row.line.piece_unit
  return count !== null && unit ? `每${unit} ${compactDecimal(row.line.unit_weight_kg)} 公斤，折合 ${count} ${unit}` : ''
})
function focusQuantity(row: ReceivingRow, event: FocusEvent) {
  const input = event.target as HTMLInputElement
  focusedQuantity.value = { row, input: input.closest<HTMLElement>('.quantity-input') ?? input }
}
function validQuantity(row: ReceivingRow) {
  if (isSample.value && Number(row.receivedQuantity) > Number(row.line.remaining_weight_kg ?? row.line.remaining_quantity)) return false
  if (isHardware(row.line)) return (!hardwarePieces(row.line) || referencePieces(row) !== null)
    && quantityPattern.test(row.receivedQuantity) && Number(row.receivedQuantity) > 0
  if (row.line.material_catalog_id && ['根', '支', '套'].includes(row.line.unit) && pipeRootError(row.receivedQuantity)) return false
  if (isWeightPipe(row.line)) return quantityPattern.test(row.receivedQuantity)
    && !pipeRootError(receivedRoots(row))
    && Number(row.receivedQuantity) > 0
  if (isPipe(row.line)) return !pipeRootError(receivedRoots(row))
  return quantityPattern.test(row.receivedQuantity) && Number(row.receivedQuantity) > 0
}
function requiresOverReceiptRemark(row: ReceivingRow) {
  return !isSample.value && row.included
    && Number(row.receivedQuantity) > Number(row.line.remaining_weight_kg ?? row.line.remaining_quantity)
}
function missingOverReceiptRemark(row: ReceivingRow) {
  return requiresOverReceiptRemark(row) && !row.remark.trim()
}
function readyRow(row: ReceivingRow) {
  return validRowZone(row) && validQuantity(row) && !missingOverReceiptRemark(row)
}
function validDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(value + 'T00:00:00Z')
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value && value <= localToday()
}
const zoneReadyCount = computed(() => selectedRows.value.filter(validRowZone).length)
const readyToSubmit = computed(() => canReceive.value && !locked.value && !loadError.value && !!selectedOrder.value && validDate(form.inboundDate)
  && (!isSample.value || !!receivingVersion.value)
  && selectedRows.value.length > 0 && selectedRows.value.length <= 100
  && selectedRows.value.every(readyRow))
const allSelected = computed({
  get: () => rows.value.length > 0 && selectedRows.value.length === rows.value.length,
  set: (value: boolean) => { if (!locked.value && !isSample.value) rows.value.forEach((row) => { row.included = value }) },
})
function setTableSelected(table: (typeof materialTables.value)[number], selected: boolean) {
  if (!locked.value && !isSample.value) table.rows.forEach(({ row }) => { row.included = selected })
}
function apiMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  const field = response?.data?.error?.field_errors ? Object.values(response.data.error.field_errors).flat()[0] : ''
  return field || response?.data?.error?.message || response?.data?.detail || fallback
}
function formatQuantity(value: string | number): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) : '—'
}
function purchaseQuantityText(line: EligibleMaterialLine): string {
  if (line.receipt_quantity_mode === 'ROOTS') return `${formatQuantity(String(line.actual_bar_count))} 根`
  if (isWeightPipe(line)) return `${formatQuantity(line.purchased_quantity)} kg`
  return `${formatQuantity(line.purchased_quantity)} ${line.unit}`
}
function receivedQuantityText(line: EligibleMaterialLine): string {
  if (line.receipt_quantity_mode === 'ROOTS') return `${formatQuantity(Number(line.actual_bar_count) - Number(line.remaining_quantity))} 根`
  if (isWeightPipe(line)) return `${formatQuantity(Number(line.purchased_quantity) - Number(line.remaining_weight_kg ?? line.remaining_quantity))} kg`
  return `${formatQuantity(Number(line.purchased_quantity) - Number(line.remaining_quantity))} ${line.unit}`
}
function remainingQuantityText(line: EligibleMaterialLine): string {
  if (line.receipt_quantity_mode === 'ROOTS') return `${formatQuantity(line.remaining_quantity)} 根`
  if (isWeightPipe(line)) return `${formatQuantity(line.remaining_weight_kg ?? line.remaining_quantity)} kg`
  return `${formatQuantity(line.remaining_quantity)} ${line.unit}`
}
function quantityInputTitle(row: ReceivingRow): string | undefined {
  if (row.line.receipt_quantity_mode === 'ROOTS') return '请填写实际到货的整根数。'
  if (focusedQuantity.value?.row === row && focusedWeightConversion.value) return undefined
  const error = weightConversionError(row)
  if (error) return error
  if (isPipe(row.line) && !isWeightPipe(row.line)) return `请按原长 ${row.line.raw_bar_length_m} 米的整数倍填写实际到货数量。`
  return '填写大于 0 的实际到货数量，最多 4 位小数。'
}
function initialQuantity(value: string): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('en-US', { maximumFractionDigits: 4, useGrouping: false }) : ''
}
function materialTitle(line: EligibleMaterialLine): string { return line.part_name || line.material || '未命名物料' }
function rowWarehouseChanged(row: ReceivingRow) {
  const zones = warehouseZones(row.warehouseId)
  row.zoneId = zones.length === 1 ? zones[0].id : ''
}
function rowWarehouseHint(row: ReceivingRow): string {
  if (!row.warehouseId) return '未找到匹配的默认仓库，请手动选择。'
  return rowWarehouses(row.line).some(warehouse => warehouse.id === row.warehouseId)
    ? '' : '已选仓库与物料状态不匹配，请重新选择。'
}
function bulkWarehouseChanged() { bulk.zoneId = bulkZones.value.length === 1 ? bulkZones.value[0].id : '' }
function applyBulkZone() {
  if (locked.value || !canReceive.value) return
  if (!hasZone(bulk)) return ElMessage.warning('请先完整选择材料仓和库区。')
  if (!selectedRows.value.length) return ElMessage.warning('请先勾选物料。')
  if (!bulkSelectedRows.value.length) return ElMessage.warning('当前分类没有已勾选物料。')
  if (bulkSelectedRows.value.some(row => !rowWarehouses(row.line).some(warehouse => warehouse.id === bulk.warehouseId))) return ElMessage.warning('所选仓库与勾选材料的原料或半成品状态不匹配。')
  bulkSelectedRows.value.forEach((row) => { row.warehouseId = bulk.warehouseId; row.zoneId = bulk.zoneId })
}
async function loadBase() {
  if (!owned.isCurrent()) { loadError.value = '身份尚未核验或已变化，请核验身份后重新打开本页。'; return }
  if (locked.value || !canReceive.value) return
  baseLoading.value = true
  loadError.value = ''
  try {
    const orderId = typeof route.params.purchaseOrderId === 'string' ? route.params.purchaseOrderId : ''
    if (!orderId) throw new Error('采购单编号缺失。')
    selectedPurchaseOrderId.value = orderId
    historyRefreshKey.value += 1
    owned.assertCurrent()
    const [optionData, orderData, lineData] = await Promise.all([
      fetchMaterialReceivingOptions(),
      fetchEligibleMaterialPurchaseOrders({ purchase_order_id: orderId }),
      fetchReceivingLines(orderId),
    ])
    owned.assertCurrent()
    if (disposed) return
    options.value = optionData
    purchaseOrders.value = orderData
    if (!selectedOrder.value) throw new Error('该采购单当前没有可入库明细。')
    if (!hasZone(bulk)) { bulk.warehouseId = ''; bulk.zoneId = '' }
    // 三项同时读取，全部就绪后再恢复草稿，避免有效库区被尚未到达的选项误清空。
    await selectOrder(true, lineData)
  } catch (error) {
    if (!isCancel(error) && owned.isCurrent() && !disposed) loadError.value = apiMessage(error, '采购入库数据加载失败，请刷新重试。')
  } finally { if (owned.isCurrent()) baseLoading.value = false }
}
function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
async function selectOrder(preserveCurrent = false, preloadedLines?: Awaited<ReturnType<typeof fetchEligibleMaterialLinesWithVersion>>) {
  if (!owned.isCurrent()) return
  const request = ++linesRequest
  const orderId = selectedPurchaseOrderId.value
  const currentDraft = preserveCurrent && orderId && rows.value.length ? {
    purchaseOrderId: orderId, inboundDate: form.inboundDate, remark: form.remark,
    rows: Object.fromEntries(rows.value.map((row) => [row.line.id, row])),
  } : null
  if (!currentDraft) {
    rows.value = []
    form.inboundDate = localToday()
    form.remark = ''
  }
  loadError.value = ''
  receivingVersion.value = ''
  linesLoading.value = false
  if (!orderId) return
  linesLoading.value = true
  try {
    owned.assertCurrent()
    const response = preloadedLines ?? await fetchReceivingLines(orderId)
    owned.assertCurrent()
    // 切换采购单后，迟到的旧响应不能覆盖新单据。
    if (disposed || request !== linesRequest || selectedPurchaseOrderId.value !== orderId) return
    receivingVersion.value = response.etag
    materialSectionLabel.value = response.materialSectionDisplay ?? ''
    let draft: Record<string, unknown> = currentDraft || {}
    if (!currentDraft) {
      // 历史无主草稿从不读取、迁移或删除，只恢复当前已核验 UID 的草稿。
      draftRaw = owned.read()
      try { draft = record(JSON.parse(draftRaw || '{}')) } catch { /* 当前用户普通草稿损坏时不恢复内容，原文保留。 */ }
    }
    if (draft.purchaseOrderId !== orderId) draft = {}
    if (validDate(draft.inboundDate)) form.inboundDate = draft.inboundDate
    if (typeof draft.remark === 'string') form.remark = draft.remark.slice(0, 3000)
    const savedRows = record(draft.rows)
    rows.value = response.data.map((line) => {
      const saved = record(savedRows[line.id])
      const savedQuantity = typeof saved.receivedQuantity === 'string' || typeof saved.receivedQuantity === 'number' ? String(saved.receivedQuantity) : ''
      const byRoots = line.receipt_quantity_mode === 'ROOTS'
      let receivedQuantity = initialQuantity(isWeightPipe(line) ? line.remaining_weight_kg ?? line.remaining_quantity : line.remaining_quantity)
      if (!isSample.value && saved.receivedQuantity !== undefined) {
        if (byRoots) receivedQuantity = saved.quantityInputUnit === '根' ? savedQuantity : ''
        else if (isPipe(line) && !isWeightPipe(line) && saved.quantityInputUnit === undefined) receivedQuantity = pipeMeters(savedQuantity, line.raw_bar_length_m)
        else receivedQuantity = savedQuantity
      }
      const row: ReceivingRow = {
        line, included: isSample.value || (typeof saved.included === 'boolean' ? saved.included : true),
        quantityInputUnit: byRoots ? '根' : line.unit,
        receivedQuantity,
        warehouseId: typeof saved.warehouseId === 'string' ? saved.warehouseId : '',
        zoneId: typeof saved.zoneId === 'string' ? saved.zoneId : '',
        remark: typeof saved.remark === 'string' ? saved.remark.slice(0, 3000) : '',
      }
      if (!options.value.warehouses.some((warehouse) => warehouse.id === row.warehouseId)) row.warehouseId = ''
      if (!hasZone(row)) row.zoneId = ''
      if (!row.warehouseId && line.suggested_warehouse_id
        && rowWarehouses(line).some(warehouse => warehouse.id === line.suggested_warehouse_id)
        && warehouseZones(line.suggested_warehouse_id).length) row.warehouseId = line.suggested_warehouse_id
      if (!row.zoneId && rowWarehouses(line).some(warehouse => warehouse.id === row.warehouseId)) rowWarehouseChanged(row)
      return row
    })
    if (!bulkCategories.value.includes(bulk.category)) { bulk.category = '' }
  } catch (error) {
    if (!isCancel(error) && owned.isCurrent() && !disposed && request === linesRequest) loadError.value = apiMessage(error, '采购明细或当前用户草稿无法读取，请刷新重试。')
  } finally { if (owned.isCurrent() && request === linesRequest) linesLoading.value = false }
}
function saveDraft() {
  if (locked.value || !canReceive.value) return
  if (!selectedPurchaseOrderId.value || !rows.value.length) return ElMessage.warning('请先选择有待收货明细的采购单。')
  try {
    const raw = JSON.stringify({
      purchaseOrderId: selectedPurchaseOrderId.value, inboundDate: form.inboundDate, remark: form.remark,
      rows: Object.fromEntries(rows.value.map((row) => [row.line.id, { included: row.included, receivedQuantity: row.receivedQuantity, quantityInputUnit: row.quantityInputUnit, warehouseId: row.warehouseId, zoneId: row.zoneId, remark: row.remark }])),
    })
    owned.write(raw); draftRaw = raw
    ElMessage.success('收货草稿已保存在当前浏览器。')
  } catch { ElMessage.error('浏览器无法保存草稿，请检查存储空间或浏览器设置。当前填写内容仍保留。') }
}
async function submitReceiving() {
  if (locked.value || !canReceive.value) return
  if (!readyToSubmit.value) return ElMessage.warning(isSample.value
    ? '请核对入库日期和全部明细的库区；每批最多提交 100 项。'
    : '请核对到货日期、数量和库区；每批最多提交 100 项。')
  const consumedDraftRaw = draftRaw, submittedOrderId = selectedPurchaseOrderId.value
  submitting.value = true
  try {
    owned.assertCurrent()
    if (isSample.value) {
      const content = {
        purchase_order_id: selectedPurchaseOrderId.value, inbound_date: form.inboundDate, remark: form.remark,
        items: rows.value.map((row) => ({ purchase_order_line_id: row.line.id, zone_id: row.zoneId, remark: row.remark,
          ...(isWeightPipe(row.line) ? { received_weight_kg: row.line.remaining_weight_kg ?? row.line.remaining_quantity, received_bar_count: receivedRoots(row) } : {}) })),
      }
      const fingerprint = JSON.stringify(content)
      if (!sampleAttempt || sampleAttempt.fingerprint !== fingerprint) {
        sampleAttempt = { fingerprint, payload: { ...content, client_request_id: createClientUuid() } }
      }
      await createSampleMaterialReceiving(sampleAttempt.payload, receivingVersion.value)
    } else await createMaterialReceiving({
      inbound_date: form.inboundDate, remark: form.remark,
      ...(materialSection.value ? { material_section: materialSection.value } : {}),
      items: selectedRows.value.map((row) => ({
        purchase_order_line_id: row.line.id, zone_id: row.zoneId,
        ...(isHardware(row.line) || isWeightPipe(row.line)
          ? { received_weight_kg: row.receivedQuantity, expected_remaining_quantity: row.line.remaining_weight_kg ?? row.line.remaining_quantity }
          : isPipe(row.line)
            ? { received_bar_count: receivedRoots(row), raw_bar_length_m: row.line.raw_bar_length_m, expected_remaining_quantity: row.line.remaining_quantity }
            : { received_quantity: row.receivedQuantity, expected_remaining_quantity: row.line.remaining_quantity }), remark: row.remark,
      })),
    })
    owned.assertCurrent()
    if (selectedPurchaseOrderId.value !== submittedOrderId) return
    receiptCreated.value = true
    historyRefreshKey.value += 1
  } catch (error) {
    if (isCancel(error) || !owned.isCurrent()) return
    ElMessage.error(apiMessage(error, isSample.value ? '全部入库失败，请核对入库记录后重试。' : '提交收货失败，请核对入库记录后重试。'))
    submitting.value = false
    return
  }
  // 收货成功后，草稿清理或跳转失败都不能再次提交同一批次。
  try { if (consumedDraftRaw !== null && !owned.removeIfUnchanged(consumedDraftRaw)) ElMessage.warning('收货已登记，但当前用户草稿已变化，已保留后写入的内容。') } catch { if (!owned.isCurrent()) return; ElMessage.warning('收货已登记，但当前用户草稿未能清理。') }
  ElMessage.success(isSample.value ? '样品采购材料已全部入库。' : '收货已登记，可在入库记录查看待质检状态。')
  try { await router.push({ name: !isSample.value && canQuality.value ? 'purchase-receipt-records' : 'purchase-inbounds' }) }
  catch { if (owned.isCurrent()) ElMessage.warning('收货已登记，请从采购入库列表继续处理。') }
  finally { if (owned.isCurrent()) submitting.value = false }
}
onMounted(() => { if (canReceive.value) void loadBase() })
onBeforeUnmount(() => { disposed = true; linesRequest += 1 })
</script>

<template>
  <section class="inventory-workflow erp-glass-form" data-testid="material-purchase-inbound-page">
    <div v-if="!canReceive" class="empty-state"><h1>无权进行采购入库</h1><p>请联系管理员开通采购入库权限。</p></div>
    <template v-else>
      <header class="page-title-row">
        <div><h1>{{ materialSectionLabel }}采购入库</h1></div>
        <div class="head-actions"><ElButton :icon="Refresh" :loading="loading" :disabled="locked" @click="loadBase">刷新</ElButton><ElButton :icon="Tickets" :disabled="submitting" @click="router.push({ name: 'purchase-inbounds' })">返回列表</ElButton></div>
      </header>
      <div v-if="loadError" class="load-error" role="alert">{{ loadError }}</div>
      <section class="surface bulk-card">
        <div class="bulk-row">
          <h2>本次到货设置</h2>
          <div class="date-field"><label>到货日期</label><ElDatePicker v-model="form.inboundDate" aria-label="到货日期" type="date" value-format="YYYY-MM-DD" :prefix-icon="Calendar" :disabled="locked" :disabled-date="(date: Date) => new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date) > localToday()" /></div>
          <div class="bulk-controls">
            <ElSelect v-model="bulk.category" aria-label="批量分类" placeholder="选择分类" clearable :disabled="locked || !rows.length"><ElOption v-for="category in bulkCategories" :key="category" :label="category" :value="category" /></ElSelect>
            <ElSelect v-model="bulk.warehouseId" aria-label="批量材料仓" placeholder="选择材料仓" :disabled="locked || !bulkWarehouses.length" @change="bulkWarehouseChanged"><ElOption v-for="item in bulkWarehouses" :key="item.id" :label="item.warehouse_name" :value="item.id" /></ElSelect>
            <ElSelect v-model="bulk.zoneId" aria-label="批量库区" placeholder="选择库区" :disabled="locked || !bulk.warehouseId"><ElOption v-for="item in bulkZones" :key="item.id" :label="item.zone_name" :value="item.id" /></ElSelect>
            <ElButton :disabled="!bulkReadyToApply" @click="applyBulkZone">{{ bulkApplyLabel }}</ElButton>
          </div>
        </div>
        <p v-if="bulkWarehouseHint" class="bulk-warehouse-hint" role="status">{{ bulkWarehouseHint }}</p>
      </section>
      <section class="surface table-card">
        <div class="table-head">
          <div><h2>采购明细</h2><div v-if="selectedOrder" class="table-order-meta"><span>采购单号 <strong>{{ selectedOrder.order_number }}</strong></span><span v-if="selectedOrder.batch_number" data-testid="receiving-purchase-batch">采购批次 <strong>第 {{ selectedOrder.batch_number }} 批</strong></span><span>生产单号 <strong>{{ selectedOrder.production_task_number || '—' }}</strong></span><span>状态 <ElTag type="warning" round>{{ receiptCreated ? isSample ? '已入库' : '已收货，待质检' : '待收货' }}</ElTag></span></div></div>
          <div class="table-summary">
            <ElCheckbox v-if="materialTables.length > 1" v-model="allSelected" :indeterminate="selectedRows.length > 0 && !allSelected" :disabled="locked">全选物料</ElCheckbox>
            <strong>共 {{ rows.length }} 项</strong>
          </div>
        </div>
        <div v-loading="loading" class="receiving-table-scroll">
          <section v-for="table in materialTables" :key="table.key" class="receipt-material-group" :data-material-category="table.key">
          <h3 v-if="materialTables.length > 1 || !['ALL', 'TUBE', 'OTHER'].includes(table.key)">{{ table.label }}</h3>
          <table class="erp-table-editor receiving-table" :aria-label="table.label || '采购明细'" :style="{ minWidth: isSample ? '1684px' : `${tableWidth}px` }">
            <colgroup v-if="isSample"><col v-for="(width, index) in sampleColumnWidths" :key="index" :style="{ width: width / 1918 * 100 + '%' }" /></colgroup>
            <colgroup v-else>
              <col v-for="(width, index) in leadingColumnWidths" :key="`leading-${index}`" :style="{ width: `${width}px` }" />
              <col v-for="(label, index) in table.columns" :key="label" :style="{ width: index < table.columns.length - 1 ? `${receiptMaterialAttributeColumnWidth(label)}px` : undefined }" />
              <col v-for="(width, index) in trailingColumnWidths" :key="`trailing-${index}`" :style="{ width: table.columns.length || index < trailingColumnWidths.length - 1 ? `${width}px` : undefined }" />
            </colgroup>
            <thead><tr>
              <th><ElCheckbox :model-value="table.rows.length > 0 && table.selected === table.rows.length" :aria-label="materialTables.length > 1 ? `全选${table.label}` : '全选物料'" :indeterminate="table.selected > 0 && table.selected < table.rows.length" :disabled="locked || isSample || !table.rows.length" @update:model-value="setTableSelected(table, $event === true)" /></th>
              <th scope="col">序号</th><th scope="col">物料信息</th>
              <th v-if="isSample" scope="col">规格</th>
              <th scope="col">供应商</th>
              <template v-if="!isSample"><th v-for="label in table.columns" :key="label" scope="col">{{ label }}</th></template>
              <th scope="col">采购数量</th><th scope="col">{{ allRowsByRoots ? '合格及待检' : '累计已收' }}</th>
              <th v-if="!isSample" scope="col">待收数量</th>
              <th scope="col">{{ isSample ? '本次入库数量' : '本次到货数量' }}</th>
              <th v-for="title in ['材料仓', '库区', '差异说明', '状态']" :key="title" scope="col">{{ title }}</th>
            </tr></thead>
            <tbody><tr v-for="({ row, number, attributes }) in table.rows" :key="row.line.id" :data-row-id="row.line.id" @mouseenter="isSample && (hoveredRowId = row.line.id)" @mouseleave="hoveredRowId = ''">
              <td><ElCheckbox v-model="row.included" :aria-label="`勾选第 ${number} 项`" :disabled="locked || isSample" /></td><td>{{ number }}</td>
              <td class="material-cell"><strong>{{ materialTitle(row.line) }}</strong></td>
              <td v-if="isSample" class="specification-cell"><ElTooltip placement="top" :show-after="80" :visible="hoveredRowId === row.line.id && hoveredSupplierRowId !== row.line.id && !focusedWeightConversion" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in materialAttributeFields(row.line)" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div></div></template><span>{{ materialSpecificationValue(row.line) }}</span></ElTooltip></td>
              <ElTooltip :content="row.line.supplier_name" placement="top" :show-after="150" :disabled="!row.line.supplier_name || !!focusedWeightConversion" :teleported="true">
                <td class="supplier-cell" @mouseenter="hoveredSupplierRowId = row.line.id" @mouseleave="hoveredSupplierRowId = ''">{{ row.line.supplier_name || '—' }}</td>
              </ElTooltip>
              <template v-if="!isSample"><td v-for="label in table.columns" :key="label">{{ attributes.get(label) ?? '—' }}</td></template>
              <td class="purchase-quantity-cell" :title="purchaseQuantityText(row.line)">{{ purchaseQuantityText(row.line) }}</td>
              <td class="muted">{{ receivedQuantityText(row.line) }}<small v-if="row.line.receipt_quantity_mode === 'ROOTS' && !allRowsByRoots" class="receipt-quantity-hint">合格及待检</small></td>
              <td v-if="!isSample" class="purchase-quantity-cell">{{ remainingQuantityText(row.line) }}</td>
              <td><span v-if="isSample" data-testid="sample-receiving-quantity">{{ remainingQuantityText(row.line) }}</span>
                <ElInput v-else v-model="row.receivedQuantity" class="quantity-input" :aria-label="`第 ${number} 项到货${isWeightPipe(row.line) || isHardware(row.line) ? '重量' : '数量'}`" inputmode="decimal" maxlength="19" :disabled="locked" :class="{ 'invalid-field': !validQuantity(row) }" :aria-invalid="!validQuantity(row)" :title="quantityInputTitle(row)" @focus="focusQuantity(row, $event)" @blur="focusedQuantity = undefined">
                  <template #append>{{ isWeightPipe(row.line) ? 'kg' : row.quantityInputUnit || '单位未识别' }}</template>
                </ElInput>
              </td>
              <td><ElSelect v-model="row.warehouseId" :aria-label="`第 ${number} 项材料仓`" placeholder="选择仓库" :disabled="locked" @change="rowWarehouseChanged(row)"><ElOption v-for="item in rowWarehouses(row.line)" :key="item.id" :label="item.warehouse_name" :value="item.id" /></ElSelect><small v-if="rowWarehouseHint(row)" class="warehouse-hint">{{ rowWarehouseHint(row) }}</small></td>
              <td><ElSelect v-model="row.zoneId" :aria-label="`第 ${number} 项库区`" placeholder="选择库区" :disabled="locked || !row.warehouseId"><ElOption v-for="item in warehouseZones(row.warehouseId)" :key="item.id" :label="item.zone_name" :value="item.id" /></ElSelect></td>
              <td class="remark-cell">
                <ElInput v-model="row.remark" :aria-label="`第 ${number} 项差异说明`" :maxlength="3000" :disabled="locked"
                  :aria-required="requiresOverReceiptRemark(row)" :aria-invalid="missingOverReceiptRemark(row)"
                  :class="{ 'invalid-field': missingOverReceiptRemark(row) }" />
                <small v-if="missingOverReceiptRemark(row)" class="over-receipt-hint">超出待收量，备注必填</small>
              </td>
              <td><ElTag :type="readyRow(row) ? 'success' : 'warning'" round>{{ readyRow(row) ? '已完善' : '待完善' }}</ElTag></td>
            </tr><tr v-if="!table.rows.length"><td :colspan="isSample ? sampleColumnWidths.length : leadingColumnWidths.length + trailingColumnWidths.length" class="table-empty">{{ loadError || (selectedOrder ? '该采购单暂无待收货明细。' : '请先选择采购单') }}</td></tr></tbody>
          </table>
          </section>
            <ElTooltip v-if="focusedQuantity && focusedWeightConversion" :key="focusedQuantity.row.line.id" virtual-triggering :virtual-ref="focusedQuantity.input" placement="bottom" :fallback-placements="[]" :enterable="false" :visible="true" :content="focusedWeightConversion" />
        </div>
        <footer><span>{{ isSample ? '全部' : '已勾选' }} {{ selectedRows.length }} 项 · {{ isSample ? '按采购剩余数量全部入库' : '到货数量按采购剩余数量带入' }}</span><strong :class="{ complete: zoneReadyCount === selectedRows.length && selectedRows.length > 0 }">{{ selectedRows.length > 100 ? '每批最多提交 100 项' : '库区完成 ' + zoneReadyCount + '/' + selectedRows.length }}</strong></footer>
      </section>
      <div class="receiving-notice"><ElIcon><WarningFilled /></ElIcon><span>{{ isSample ? '确认剩余采购材料已全部到齐后，按剩余采购量全部入库，无需品质确认。' : '提交后进入“待质检”，此时不增加可用库存；品质确认后按实收数量减退货数量入库。' }}</span></div>
      <section class="submit-bar">
        <label for="receiving-batch-remark">本批次备注（可选）</label><ElInput id="receiving-batch-remark" v-model="form.remark" placeholder="请输入备注信息…" :maxlength="3000" :disabled="locked" />
        <ElButton :disabled="locked || !rows.length" @click="saveDraft">保存草稿</ElButton>
        <ElButton type="primary" :loading="submitting" :disabled="!readyToSubmit" @click="submitReceiving">{{ isSample ? '全部入库' : '提交收货' }}</ElButton>
      </section>
      <PurchaseInboundHistory v-if="selectedPurchaseOrderId && owned.isCurrent()" :purchase-order-id="selectedPurchaseOrderId" :material-section="materialSection" :hide-material-section="isSample" :refresh-key="historyRefreshKey" />
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;
.inventory-workflow { box-sizing: border-box; height: auto; min-height: 0; overflow: visible; padding: 0; background: transparent; color: token.$crm-text-primary; font: 13px/20px token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-text-color-primary: #{token.$crm-text-primary}; --el-text-color-regular: #{token.$crm-text-secondary}; --el-text-color-placeholder: #{token.$crm-text-muted}; --el-border-color: #{token.$crm-border-default}; --el-border-color-light: #{token.$crm-border-subtle}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-fill-color-light: #{token.$crm-color-subtle}; --el-border-radius-base: 5px;
}
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: var(--erp-color-text-secondary); min-width: 42px; }
.page-title-row, .head-actions, .table-head, .bulk-row, .date-field, .bulk-controls, .submit-bar { display: flex; align-items: center; }
h1, h2, p { margin: 0; } h2 { font-size: 16px; line-height: 22px; font-weight: 700; }
.page-title-row { height: 54px; justify-content: space-between; margin-bottom: 10px; }
h1 { font: 700 34px/44px token.$crm-font-display; letter-spacing: -1px; }
.page-title-row p { color: token.$crm-text-secondary; line-height: 18px; }
.surface { @include detail.surface; }
.head-actions { gap: 10px; } .head-actions > .el-button { height: 32px; margin: 0; }
.load-error { box-sizing: border-box; min-height: 40px; padding: 9px 16px; margin-bottom: 12px; border: 1px solid token.$crm-danger; border-radius: 5px; background: token.$crm-danger-soft; color: token.$crm-danger; }
.bulk-card { box-sizing: border-box; min-height: 60px; padding: 13px 21px; margin-bottom: 14px; }
.bulk-warehouse-hint { margin-top: 8px; color: token.$crm-warning; font-size: 12px; line-height: 18px; }
.warehouse-hint { display: block; margin-top: 4px; text-align: left; color: token.$crm-warning; font-size: 12px; line-height: 16px; }
.bulk-row { height: 32px; gap: 20px; }
.date-field { gap: 10px; } .date-field label { white-space: nowrap; color: token.$crm-text-secondary; }
.date-field :deep(.el-date-editor) { width: 190px; height: 32px; }
.bulk-controls { gap: 10px; height: 32px; }
.bulk-controls > .el-select:nth-child(1) { width: 120px; }
.bulk-controls > .el-select:nth-child(2) { width: 180px; }
.bulk-controls > .el-select:nth-child(3) { width: 150px; }
.bulk-controls > .el-button { width: 140px; }
.table-card { box-sizing: border-box; height: calc(100dvh - 356px); min-height: 370px; display: flex; flex-direction: column; overflow: hidden; margin-bottom: 16px; }
.table-head { flex: 0 0 51px; justify-content: space-between; padding: 0 21px; border-bottom: 1px solid token.$crm-border-subtle; }
.table-head > div { display: flex; gap: 22px; align-items: center; min-width: 0; }
.table-order-meta { display: flex; align-items: center; gap: 24px; min-width: 0; color: token.$crm-text-secondary; font-size: 12px; }
.table-order-meta span { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.table-order-meta strong { color: token.$crm-text-primary; font-weight: 500; }
.table-head .table-summary { gap: 12px; margin-right: 16px; font-size: 13px; white-space: nowrap; }
.receipt-material-group + .receipt-material-group { margin-top: 10px; }
.receipt-material-group h3 { position: sticky; left: 0; width: max-content; margin: 0; padding: 5px 16px; color: var(--erp-table-header-text); font-size: 13px; }
.receiving-table-scroll { flex: 1; min-height: 0; overflow: auto; }
.receiving-table { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; background: var(--erp-table-body-fill); }
.receiving-table th, .receiving-table td { box-sizing: border-box; padding: 4px 8px; border-right: 1px solid var(--erp-table-grid); border-bottom: 1px solid var(--erp-table-grid); text-align: center; overflow-wrap: anywhere; }
.receiving-table th:nth-child(2), .receiving-table td:nth-child(2) { white-space: nowrap; overflow-wrap: normal; }
.receiving-table th { height: 44px; position: sticky; top: 0; z-index: 2; background: var(--erp-table-header-fill); font-size: 12px; font-weight: 500; color: var(--erp-table-header-text); }
.receiving-table td { height: 58px; } .receiving-table th:last-child, .receiving-table td:last-child { border-right: 0; }
.receiving-table .purchase-quantity-cell { white-space: nowrap; overflow: hidden; overflow-wrap: normal; text-overflow: ellipsis; }
.receipt-quantity-hint { display: block; margin-top: 3px; color: token.$crm-text-muted; font-size: 12px; line-height: 16px; }
.quantity-input :deep(.el-input-group__append) { box-sizing: border-box; flex: 0 0 64px; width: 64px; padding: 0; font-size: 12px; white-space: nowrap; }
.receiving-table th:first-child, .receiving-table td:first-child { padding: 0; vertical-align: middle; }
.receiving-table th:first-child :deep(.el-checkbox), .receiving-table td:first-child :deep(.el-checkbox) { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; margin: 0; }
.receiving-table .material-cell { text-align: left; padding: 4px 18px; } .material-cell strong, .material-cell small { display: block; font-weight: 400; } .material-cell small { font-size: 13px; color: token.$crm-text-secondary; }
.receiving-table .specification-cell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.receiving-table .specification-cell > span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.receiving-table .supplier-cell { font-size: 13px; color: var(--erp-table-text); white-space: nowrap; overflow: hidden; overflow-wrap: normal; text-overflow: ellipsis; } .muted { color: token.$crm-text-secondary; } .receiving-table .remark-cell { padding: 4px 16px; }
.table-empty { height: 230px !important; color: token.$crm-text-secondary; }
.table-card footer { box-sizing: border-box; flex: 0 0 44px; display: flex; align-items: center; justify-content: space-between; padding: 0 21px; color: token.$crm-text-secondary; border-top: 1px solid token.$crm-border-subtle; }
.table-card footer strong { font-weight: 400; color: token.$crm-warning; } .table-card footer .complete { color: token.$crm-success; }
.receiving-notice { box-sizing: border-box; display: flex; align-items: center; gap: 14px; height: 40px; padding: 0 20px; margin-bottom: 10px; border: 1px solid token.$crm-border-default; border-radius: 5px; background: token.$crm-warning-soft; color: token.$crm-warning; }
.receiving-notice .el-icon { font-size: 18px; flex-shrink: 0; }
.submit-bar { height: 32px; gap: 20px; } .submit-bar label { flex: 0 0 144px; white-space: nowrap; } .submit-bar > .el-input { flex: 1; min-width: 0; }
.submit-bar > .el-button { width: 140px; height: 32px; margin: 0; } .submit-bar > .el-button--primary { width: 160px; }
.inventory-workflow :deep(.el-button) { height: 32px; font-size: 13px; border-radius: 5px; font-family: inherit; }
.inventory-workflow :deep(.el-input__wrapper), .inventory-workflow :deep(.el-select__wrapper) { box-sizing: border-box; height: 32px; min-height: 32px; border-radius: var(--erp-radius-control); font-size: 13px; background: var(--erp-input-surface); color: token.$crm-text-secondary; box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset; }
.inventory-workflow :deep(.el-input__wrapper.is-focus), .inventory-workflow :deep(.el-select__wrapper.is-focused) { box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }
.inventory-workflow :deep(.el-input__inner) { color: token.$crm-text-secondary; font-family: inherit; height: 30px; }
.inventory-workflow :deep(.el-select__selected-item) { color: token.$crm-text-secondary; }
.submit-bar :deep(.el-input__wrapper) { min-height: 32px; }
.inventory-workflow :deep(.el-tag) { height: 24px; min-width: 64px; padding: 0 10px; border: 0; font-size: 11px; font-family: inherit; }
.inventory-workflow :deep(.el-tag--success) { background: var(--erp-tag-success-background); color: var(--erp-color-text-inverse); }
.inventory-workflow :deep(.el-tag--warning) { background: var(--erp-tag-warning-background); color: var(--erp-color-text-inverse); }
.inventory-workflow :deep(.el-checkbox__inner) { width: 14px; height: 14px; border-radius: 2px; }
.inventory-workflow :deep(.invalid-field .el-input__wrapper) { box-shadow: 0 0 0 1px token.$crm-danger inset; }
.over-receipt-hint { display: block; margin-top: 4px; color: token.$crm-danger; font-size: 12px; }
.empty-state { padding: 80px; text-align: center; color: token.$crm-text-secondary; }
@media (max-width: 1400px) {
  .bulk-row { gap: 12px; }
  .date-field { gap: 6px; }
  .date-field :deep(.el-date-editor) { width: 150px; }
  .bulk-controls { gap: 6px; }
  .bulk-controls > .el-select:nth-child(1) { width: 100px; }
  .bulk-controls > .el-select:nth-child(2) { width: 150px; }
  .bulk-controls > .el-select:nth-child(3) { width: 120px; }
  .bulk-controls > .el-button { width: 120px; }
}
</style>
