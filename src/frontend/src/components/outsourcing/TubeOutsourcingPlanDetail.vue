<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isAxiosError, isCancel } from 'axios'
import { useIdentityOwnedStorage } from '@/composables/useIdentityOwnedStorage'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import TubeOutsourcingDetailTable from './TubeOutsourcingDetailTable.vue'
import TubeOutsourcingPlanRecords from './TubeOutsourcingPlanRecords.vue'
import ProcessingMaterialDetails from '@/components/inventory/ProcessingMaterialDetails.vue'
import ComponentSourceMaterials from './ComponentSourceMaterials.vue'
import { correctTubePlanRecord, dispatchTubePlan, fetchTubeOrder, fetchTubeSource, findTubePlanRecordCorrection, receiveTubePlan, updateTubePlanQuantity } from '@/api/tubeOutsourcing'
import { fetchTubeReceiptPreview } from '@/api/tubeReceipts'
import type { TubeDetailLine, TubeOrderDetail, TubePieceSource, TubePlanPendingAction, TubePlanRecordCorrectionDraft, TubeSourceContext, TubeSourceKind, TubeSourceRow } from '@/types/tubeOutsourcing'
import type { TubeReceiptPreview } from '@/types/tubeReceipts'
import { defaultOutsourcingReceiptWarehouse, isCuttingSource, isDirectSource, tubeMaterialColumn, tubeQuantityError, wholeTubeQuantity } from '@/utils/tubeOutsourcing'
import { formatOutsourcingMoney, outsourcingLineAmount, outsourcingPriceError } from '@/utils/outsourcingPrices'
import { createClientUuid } from '@/utils/clientUuid'
import { componentSourceColumns, materialSpecificationValue, plannedMaterialSpecification } from '@/utils/componentSourceColumns'
import '@/styles/tubeOutsourcingDetail.scss'

const props = withDefaults(defineProps<{ order: TubeOrderDetail; warehouse: boolean; entryAction?: string; blocked?: boolean; actionOnly?: boolean; readOnly?: boolean }>(), { actionOnly: false })
const emit = defineEmits<{ updated: [order: TubeOrderDetail]; refresh: []; cancel: []; closed: [] }>()
const mode = ref<'' | 'DISPATCH' | 'RECEIPT'>('')
const loading = ref(false), saving = ref(false), message = ref(''), storageError = ref(false)
const checkingPending = ref(false)
const pending = ref<TubePlanPendingAction | null>(null)
const records = ref<InstanceType<typeof TubeOutsourcingPlanRecords> | null>(null)
const correctionActive = ref(false), correctionRefreshRequired = ref(false)
const correctionOrder = ref<TubeOrderDetail | null>(null)
const quantityEditing = ref(false), quantityRefreshRequired = ref(false), quantityError = ref('')
const quantityOrder = ref<TubeOrderDetail | null>(null), quantityValues = ref<Record<string, string>>({})
const priceValues = ref<Record<string, string>>({})
const source = ref<TubeSourceKind>(props.order.source_kind)
const sourceFactory = ref('')
const zone = ref(props.order.zone_id || ''), warehouseId = ref(''), remark = ref('')
const date = ref('')
const context = ref<TubeSourceContext | null>(null)
const receiptPreview = ref<TubeReceiptPreview | null>(null)
const dispatchTable = ref<HTMLTableElement | null>(null)
const quantityIssueRow = ref('')
const entries = ref<Array<{ id: string; component: string; name: string; quantity: string; factory: string; zone: string }>>([])
const materialEntries = ref<Array<{ id: string; name: string; quantity: string; factory: string; zone: string; externalSupply: boolean }>>([])
const ownedOrderId = props.order.id
const ownedWarehouse = props.warehouse
let requestSequence = 0, disposed = false
const owned = useIdentityOwnedStorage({ storage: 'local', key: uid => `tube-outsourcing-plan-action:v1:${uid}:${ownedOrderId}`, legacyKeys: [`tube-outsourcing-plan-action:v1:unknown:${ownedOrderId}`] })
const isCurrent = () => !disposed && owned.isCurrent() && props.order.id === ownedOrderId && props.warehouse === ownedWarehouse
const identityBlocked = computed(() => !isCurrent())
const storageReason = ref('本地请求记录无法安全读取或清理，已暂停新操作，请先核对原请求结果。')
let pendingRaw: string | null = null
function storageAvailable(): boolean {
  if (!owned.isCurrent() || props.order.id !== ownedOrderId) return false
  try {
    if (!owned.legacyExists()) return true
    storageReason.value = '发现身份不明的历史待核对请求，已原样隔离并暂停提交。请人工核对原业务结果，不能将其归入当前账号。'
  } catch (cause) {
    if (isCancel(cause) || !owned.isCurrent()) return false
    storageReason.value = '浏览器本地存储不可用，已暂停提交。请恢复存储后核对原请求。'
  }
  storageError.value = true
  return false
}
const cutting = computed(() => isCuttingSource(props.order.source_kind))
const partFlow = computed(() => props.order.part_flow === true)
const printPieces = computed(() => props.order.screen_print_pieces === true)
const inputMode = computed(() => mode.value === 'DISPATCH' && props.order.sewing_inputs === true)
const processorDispatch = computed(() => inputMode.value && source.value === 'PROCESSOR')
const processorSources = computed(() => new Map(context.value?.inputs
  ?.filter(piece => piece.processor_source && Number(piece.processor_source.available_quantity) > 0)
  .map(piece => [piece.component_identity, piece.processor_source!] as const)))
const processorFactories = computed(() => [...new Map([...processorSources.value.values()]
  .map(item => [item.factory_id, item.factory_name])).entries()])
const entryRows = computed(() => processorDispatch.value
  ? entries.value.filter(row => processorSources.value.get(row.component)?.factory_id === sourceFactory.value)
  : entries.value)
const unit = computed(() => partFlow.value ? props.order.output_unit || '各行单位' : cutting.value ? '套' : '支')
const summary = computed(() => props.order.plan_summary)
const locked = computed(() => !isCurrent() || props.order.id !== ownedOrderId || props.blocked || loading.value || checkingPending.value || saving.value || Boolean(pending.value) || storageError.value || correctionActive.value || quantityEditing.value)
const canEditQuantity = computed(() => !printPieces.value && !props.readOnly && !props.warehouse && props.order.permissions.can_edit_quantity === true && !locked.value && !mode.value)
const quantityLocked = computed(() => !isCurrent() || props.warehouse || props.blocked || loading.value || saving.value || checkingPending.value || Boolean(pending.value) || storageError.value || quantityRefreshRequired.value || quantityOrder.value?.permissions.can_edit_quantity !== true)
const direct = computed(() => isDirectSource(source.value))
const options = computed(() => props.order.plan_options)
const tubeDispatch = computed(() => mode.value === 'DISPATCH' && !cutting.value)
const warehouseDispatch = computed(() => tubeDispatch.value && !direct.value)
const dispatchSourceLabels: Partial<Record<TubeSourceKind, string>> = {
  METAL: '金工车间直发',
  PUBLIC_SEMI: '从仓库发（已入库、未喷塑）',
  RAW_PIPE: '从仓库发（原材料）',
}
const sourceZones = computed(() => (options.value?.zones || []).filter(item => item.warehouse_type === (source.value === 'RAW_PIPE' ? 'MATERIAL' : 'SEMI_FINISHED')))
const receiptZones = computed(() => (receiptPreview.value?.zones || []).filter(item => item.warehouse_id === warehouseId.value))
const canDispatch = computed(() => props.warehouse && props.order.permissions.can_dispatch && !locked.value)
const canReceive = computed(() => props.warehouse && props.order.permissions.can_receive === true && !locked.value)
const requestedMode = computed(() => props.entryAction === 'return' ? 'RECEIPT' : 'DISPATCH')
const dialogMode = computed(() => mode.value || pending.value?.kind || requestedMode.value)
const actionUnavailable = computed(() => {
  if (identityBlocked.value) return '身份尚未核验或已变化，请核验身份后重新打开。'
  if (storageError.value) return storageReason.value
  if (props.blocked) return '正在核对委外总单，请稍后重新加载。'
  if (checkingPending.value) return '正在核对上次提交结果，请稍候。'
  if (!props.warehouse || !(requestedMode.value === 'DISPATCH' ? props.order.permissions.can_dispatch : props.order.permissions.can_receive)) return '当前没有此委外总单的办理权限，请刷新核对。'
  return pending.value ? '请先核对上次提交结果，再办理新的收发。' : '请重新加载后办理本次收发。'
})
const columns = computed(() => partFlow.value ? [
  { key: 'part_name', label: printPieces.value ? '裁片' : '部位', width: 160 }, { key: 'specification', label: '规格', width: 160 }, { key: 'unit', label: '单位', width: 70 },
  ...componentSourceColumns,
  { key: 'factory_name', label: '计划加工厂', width: 160 },
  { key: 'bom_quantity', label: 'BOM需求', width: 120, num: true },
  { key: 'quantity', label: '目标数量', width: 120, num: true },
  ...(!props.order.sewing_inputs ? [{ key: 'dispatched_quantity', label: '累计实发', width: 120, num: true }] : []),
  { key: 'received_quantity', label: printPieces.value ? '累计回仓' : '累计入库', width: 120, num: true },
  ...(printPieces.value ? [
    { key: 'transferred_quantity', label: '直送车缝厂', width: 120, num: true },
    { key: 'receivable_quantity', label: '丝印厂待交', width: 120, num: true },
  ] : []),
  ...(!props.warehouse ? [
    { key: 'unit_price', label: printPieces.value ? '丝印单价' : '部位单价', width: 145, num: true },
    { key: 'planned_amount', label: '计划金额（元）', width: 130, num: true },
    { key: 'received_amount', label: '回货金额（元）', width: 150, num: true },
  ] : []),
] : [
  { key: 'part_name', label: '部位', width: 130 }, { key: cutting.value ? 'fabric_material' : 'material', label: '材质', width: 90 },
  ...(!cutting.value ? [{ key: 'shape', label: '形状', width: 80 }] : []),
  { key: 'specification', label: '规格', width: 150 },
  ...(cutting.value ? [{ key: 'fabric_color', label: '颜色', width: 90 }, { key: 'pieces_per_set', label: '每套片数', width: 90, num: true }] : []),
  ...(!cutting.value ? [{ key: 'thickness', label: '厚度 mm', width: 85 }, { key: 'spray_color', label: '喷塑颜色', width: 90 }] : []),
  { key: 'factory_name', label: '计划加工厂', width: 150 },
  { key: 'bom_quantity', label: `BOM数量（${unit.value}）`, width: 120, num: true },
  { key: 'purchase_reference', label: `采购入库参考（${unit.value}）`, width: 150, num: true },
  { key: 'quantity', label: `计划数量（${unit.value}）`, width: 120, num: true },
  { key: 'dispatched_quantity', label: '累计实发', width: 110, num: true },
  { key: 'received_quantity', label: '累计入库', width: 110, num: true },
  ...(!props.warehouse ? [
    ...(!cutting.value ? [
      { key: 'unit_area_sqm', label: '单支面积（㎡）', width: 120, num: true },
      { key: 'line_area_sqm', label: '计划面积（㎡）', width: 120, num: true },
      { key: 'price_unit', label: '计价方式', width: 95 },
    ] : []),
    { key: 'unit_price', label: cutting.value ? `计划单价（元/${unit.value}）` : '计划单价', width: 145, num: true },
    { key: 'planned_amount', label: '计划金额（元）', width: 130, num: true },
  ] : []),
])
const quantityColumns = computed(() => partFlow.value ? [
  { key: 'part_name', label: '部位', width: 180 }, { key: 'specification', label: '规格', width: 160 },
  ...componentSourceColumns, { key: 'unit', label: '单位', width: 80 },
  { key: 'quantity', label: '目标数量', width: 150, num: true },
  { key: 'unit_price', label: '部位单价', width: 170, num: true },
] : [
  ...columns.value.filter(column => ['part_name', 'material', 'fabric_material', 'shape', 'specification', 'fabric_color', 'pieces_per_set', 'thickness', 'spray_color'].includes(column.key)),
  ...(!cutting.value ? [{ key: 'cutting_length_mm', label: '切割长度 mm', width: 100 }] : []),
  { key: 'purchase_reference', label: `采购入库参考（${unit.value}）`, width: 150, num: true },
  { key: 'dispatched_quantity', label: `累计已发（${unit.value}）`, width: 140, num: true },
  { key: 'quantity', label: `计划数量（${unit.value}）`, width: 150, num: true },
])
const number = (value: unknown) => value == null || value === '' || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
const progress = computed(() => Math.min(100, Math.max(0, Number(summary.value?.receipt_progress) || 0)))
function errorText(cause: unknown, fallback: string) {
  if (isAxiosError(cause)) return cause.response?.data?.error?.message || cause.response?.data?.detail || fallback
  return cause instanceof Error ? cause.message : fallback
}
function today() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}` }
function received(id: string) { return props.order.lines.find(line => line.id === id)?.received_quantity ?? '0' }
function sent(id: string) { return (inputMode.value ? props.order.inputs?.find(line => line.component_identity === id)?.dispatched_quantity : props.order.lines.find(line => line.id === id)?.dispatched_quantity) ?? '0' }
function planned(id: string) { return inputMode.value ? props.order.inputs?.find(line => line.component_identity === id)?.target_quantity : props.order.lines.find(line => line.id === id)?.quantity }
function entryUnit(id: string) { return (inputMode.value ? props.order.inputs?.find(line => line.component_identity === id)?.unit : props.order.lines.find(line => line.id === id)?.unit) || unit.value }
function totalText(field: 'bom_quantity' | 'planned_quantity' | 'dispatched_quantity' | 'received_quantity' | 'transferred_quantity' | 'receivable_quantity') {
  if (field === 'dispatched_quantity' && props.order.sewing_inputs) return (summary.value?.input_totals || []).map(row => `${number(row.dispatched_quantity)} ${row.unit}`).join(' / ') || '—'
  return (summary.value?.quantity_totals || []).map(row => `${number(row[field])} ${row.unit}`).join(' / ')
}
function dispatchRemaining(id: string) { return Math.max(Number(planned(id)) - Number(sent(id)), 0) }
function quantityReferenceKnown(line: TubeDetailLine) {
  const reference = line.purchase_reference
  return reference?.quantity != null && reference.unit === unit.value && Number.isFinite(Number(reference.quantity)) && Number(reference.quantity) >= 0
}
async function openQuantityEditor() {
  if (!canEditQuantity.value || !storageAvailable()) return
  quantityEditing.value = true; quantityOrder.value = null; quantityValues.value = {}; quantityError.value = ''; quantityRefreshRequired.value = false
  priceValues.value = {}
  await loadQuantityEditor()
}
function closeQuantityEditor() {
  if (saving.value) return
  requestSequence += 1; quantityEditing.value = false; loading.value = false
  quantityOrder.value = null; quantityValues.value = {}; quantityError.value = ''; quantityRefreshRequired.value = false
  priceValues.value = {}
}
async function loadQuantityEditor() {
  if (!quantityEditing.value || !isCurrent() || props.warehouse || props.blocked || loading.value || saving.value || checkingPending.value || pending.value || storageError.value) return
  const sequence = ++requestSequence
  const current = () => isCurrent() && quantityEditing.value && sequence === requestSequence
  loading.value = true; quantityError.value = ''; quantityRefreshRequired.value = true
  try {
    owned.assertCurrent()
    const latest = await fetchTubeOrder(ownedOrderId, false)
    if (!current()) return
    if (latest.id !== ownedOrderId || !latest.is_plan || !latest.etag) throw new Error('总单核对结果不完整，请重新加载。')
    const previous = quantityValues.value
    quantityValues.value = Object.fromEntries(latest.lines.map(line => [line.id, previous[line.id] ?? line.quantity]))
    priceValues.value = Object.fromEntries(latest.lines.map(line => [line.id, priceValues.value[line.id] ?? line.unit_price ?? '']))
    quantityOrder.value = latest; quantityRefreshRequired.value = false
    if (latest.permissions.can_edit_quantity !== true) quantityError.value = '当前没有修改计划数量的权限，请关闭后刷新核对。'
    emit('updated', latest)
  } catch (cause) {
    if (current()) quantityError.value = errorText(cause, '计划数量读取失败，请重新加载。')
  } finally { if (current()) loading.value = false }
}
async function saveQuantity() {
  if (!quantityEditing.value || quantityLocked.value || !quantityOrder.value) return
  quantityError.value = ''
  const original = quantityOrder.value
  const lines = original.lines.map(line => ({ order_line_id: line.id, quantity: (quantityValues.value[line.id] ?? '').trim(),
    ...(partFlow.value && priceValues.value[line.id]?.trim() ? { unit_price: priceValues.value[line.id]!.trim() } : {}) }))
  if (!lines.length || lines.some(line => wholeTubeQuantity(line.quantity) === null || Number(line.quantity) <= 0)) { quantityError.value = '每个部件的计划数量须为正整数。'; return }
  let changed = false
  for (const line of original.lines) {
    if (partFlow.value) {
      const price = priceValues.value[line.id]?.trim() || ''
      if ((price || line.unit_price != null) && outsourcingPriceError(price)) { quantityError.value = `${line.part_name}：${outsourcingPriceError(price)}`; return }
      if (price && (line.unit_price == null || outsourcingLineAmount('1', price) !== outsourcingLineAmount('1', line.unit_price))) changed = true
    }
    const quantity = Number(quantityValues.value[line.id])
    if (quantity === Number(line.quantity)) continue
    changed = true
    if (quantity < Number(line.dispatched_quantity ?? '0')) { quantityError.value = `${line.part_name}：计划数量不能小于累计已发 ${number(line.dispatched_quantity ?? '0')} ${unit.value}。`; return }
  }
  if (!changed) { closeQuantityEditor(); return }
  const sequence = ++requestSequence
  const current = () => isCurrent() && quantityEditing.value && sequence === requestSequence
  saving.value = true
  try {
    owned.assertCurrent()
    const result = await updateTubePlanQuantity(ownedOrderId, { lines }, original.etag)
    if (!current()) return
    if (result.id !== ownedOrderId || !result.is_plan || !result.etag) throw new Error('保存结果尚未确认。')
    saving.value = false; closeQuantityEditor(); emit('updated', result)
    if (isCurrent()) ElMessage.success('计划数量已更新。')
  } catch (cause) {
    if (!current()) return
    quantityRefreshRequired.value = !isAxiosError(cause) || cause.response?.status !== 400
    quantityError.value = errorText(cause, '保存结果尚未确认。') + (quantityRefreshRequired.value ? ' 请重新加载最新总单，核对填写数量后再保存。' : '')
  } finally { if (current()) saving.value = false }
}
function entryMaterial(row: { id: string; component: string }): Partial<Pick<TubeSourceRow, 'component_source_materials' | 'component_material_selection_snapshot' | 'input_material_selection_snapshot' | 'output_material_selection_snapshot' | 'material' | 'fabric_material' | 'fabric_color' | 'pieces_per_set' | 'specification' | 'cutting_length_mm' | 'thickness' | 'spray_color'>> {
  return (mode.value === 'DISPATCH'
    ? (inputMode.value ? context.value?.inputs : context.value?.rows)?.find(item => item.component_identity === row.component)
    : props.order.lines.find(item => item.id === row.id)) || {}
}
function entryAttribute(row: { id: string; component: string }, key: 'material' | 'specification' | 'cutting_length_mm' | 'fabric_color') {
  const material = entryMaterial(row)
  return (key === 'material' && cutting.value ? material.fabric_material || material.material : material[key]) || '—'
}
function entryFactory(id: string) { return (inputMode.value ? props.order.inputs?.find(line => line.component_identity === id)?.factory_name : props.order.lines.find(line => line.id === id)?.factory_name) || '—' }
function printedPiece(component: string) {
  return inputMode.value ? context.value?.inputs?.find(item => item.component_identity === component && item.screen_print_required) : undefined
}
function processorRemaining(id: string) {
  return Number(props.order.lines.find(line => line.id === id)?.receivable_quantity ?? 0)
}
function entryAvailable(row: { id: string; component: string }) {
  const remaining = dispatchRemaining(row.id)
  if (processorDispatch.value) return Math.min(remaining, Number(processorSources.value.get(row.component)?.available_quantity) || 0)
  if (printPieces.value) return Math.min(remaining, Number(dispatchStockQuantity(row.component) || 0))
  const piece = printedPiece(row.component)
  return piece ? Math.min(remaining, Number(piece.max_quantity)) : remaining
}
async function usePrintedStock(zoneId: string) {
  if (locked.value || !options.value?.source_kinds.some(item => item.value === 'PUBLIC_PIECE')) return
  source.value = 'PUBLIC_PIECE'
  zone.value = zoneId
  await loadSource()
}
function zoneName(id: string) {
  const item = sourceZones.value.find(zone => zone.id === id)
  return item ? `${item.warehouse_name} / ${item.name}` : ''
}
function dispatchStockQuantity(component: string) {
  const row = context.value?.rows.find(item => item.component_identity === component)
  return row && !row.blockers.length ? row.max_quantity : null
}
function materialSource(id: string) { return context.value?.material_rows?.find(row => row.bom_line_id === id) }
function materialFactory(id: string) {
  const planned = (props.order.planned_materials || []).filter(row => row.bom_line_id === id)
  const ids = [...new Set(planned.map(row => row.factory_id).filter(Boolean))]
  return ids.length === 1 ? { id: ids[0]!, name: planned.find(row => row.factory_id === ids[0])?.factory_name || '—' } : null
}
async function loadSource() {
  if (!isCurrent()) return
  const sequence = ++requestSequence
  context.value = null; message.value = ''; quantityIssueRow.value = ''
  if (!direct.value && !zone.value) return
  loading.value = true
  try {
    owned.assertCurrent()
    const result = await fetchTubeSource({ schedule_product_id: props.order.schedule_product_id, source_kind: source.value, plan_id: props.order.id,
      ...(props.order.craft_id ? { craft_id: props.order.craft_id } : {}), ...(direct.value ? {} : { zone_id: zone.value }) })
    if (!isCurrent() || disposed || sequence !== requestSequence) return
    context.value = result
    if (processorDispatch.value && !processorFactories.value.some(([id]) => id === sourceFactory.value)) {
      sourceFactory.value = processorFactories.value.length === 1 ? processorFactories.value[0]![0] : ''
    }
    const previousMaterials = new Map(materialEntries.value.map(row => [row.id, row]))
    materialEntries.value = cutting.value && !processorDispatch.value ? (result.material_rows || []).map(row => {
      if (row.external_supply) return { id: row.bom_line_id, name: row.name, externalSupply: true, quantity: '', factory: '', zone: '' }
      return {
        ...(previousMaterials.get(row.bom_line_id) || { id: row.bom_line_id, name: row.name, quantity: '', zone: row.zones.length === 1 ? row.zones[0]!.zone_id : '' }),
        externalSupply: false, factory: materialFactory(row.bom_line_id)?.id || '',
      }
    }) : []
    const unavailable = result.rows.filter(row => row.processing_not_enabled_reason)
      .map(row => `${row.part_name}：${row.processing_not_enabled_reason}`).join('；')
    if (unavailable || !result.ready) message.value = unavailable || result.blockers.join('；') || '当前来源不可发出，请核对后重试。'
  } catch (cause) { if (isCancel(cause)) return; if (isCurrent() && !disposed && sequence === requestSequence) message.value = errorText(cause, '实际发货来源加载失败。') }
  finally { if (isCurrent() && !disposed && sequence === requestSequence) loading.value = false }
}
async function changeSource(kind: TubeSourceKind) {
  if (locked.value || kind === source.value) return
  if (source.value === 'PROCESSOR' || kind === 'PROCESSOR') {
    entries.value.forEach(row => { row.quantity = '' })
    sourceFactory.value = ''
  }
  source.value = kind
  zone.value = direct.value || tubeDispatch.value ? '' : sourceZones.value[0]?.id || ''
  await loadSource()
}
function changeReceiptWarehouse(id: string) {
  warehouseId.value = id
  const defaultZone = receiptZones.value.length === 1 ? receiptZones.value[0]!.id : ''
  entries.value.forEach(row => { row.zone = defaultZone })
}
async function open(kind: 'DISPATCH' | 'RECEIPT') {
  if (kind === 'DISPATCH' ? !canDispatch.value : !canReceive.value) return
  mode.value = kind; message.value = ''; quantityIssueRow.value = ''; date.value = today(); remark.value = ''; receiptPreview.value = null
  materialEntries.value = []
  entries.value = props.order.lines.map(line => ({ id: line.id, component: line.component_identity, name: line.part_name, quantity: '', factory: line.factory_id, zone: '' }))
  if (kind === 'DISPATCH' && props.order.sewing_inputs) entries.value = (props.order.inputs || []).map(line => ({ id: line.component_identity, component: line.component_identity, name: `${line.parent_name} / ${line.part_name}`, quantity: '', factory: line.factory_id, zone: '' }))
  if (kind === 'DISPATCH') {
    sourceFactory.value = ''
    const canUseMetal = options.value?.source_kinds.some(item => item.value === 'METAL')
    source.value = tubeDispatch.value && canUseMetal ? 'METAL' : props.order.source_kind
    zone.value = direct.value ? '' : props.order.zone_id || ''
    if (!direct.value && !sourceZones.value.some(item => item.id === zone.value)) {
      zone.value = tubeDispatch.value ? '' : sourceZones.value[0]?.id || ''
    }
    await loadSource()
  } else {
    const sequence = ++requestSequence
    loading.value = true
    try {
      owned.assertCurrent()
      const preview = await fetchTubeReceiptPreview(ownedOrderId, true)
      if (!isCurrent() || disposed || sequence !== requestSequence) return
      receiptPreview.value = preview
      if (preview.order.etag !== props.order.etag) emit('updated', preview.order)
      if (!isCurrent()) return
      changeReceiptWarehouse(defaultOutsourcingReceiptWarehouse(preview.order.source_kind, preview.warehouses) ?? preview.warehouses[0]?.id ?? '')
      if (!preview.can_receive) message.value = preview.blockers.join('；') || '当前不能办理入库。'
    } catch (cause) { if (isCancel(cause)) return; if (isCurrent() && !disposed && sequence === requestSequence) message.value = errorText(cause, '入库选项读取失败。') }
    finally { if (isCurrent() && !disposed && sequence === requestSequence) loading.value = false }
  }
}
function close() { if (!saving.value) { mode.value = ''; requestSequence += 1; loading.value = false; emit('closed') } }
async function reloadAction() {
  if (saving.value || loading.value || checkingPending.value) return
  if (pending.value) { await postPending(); return }
  if (identityBlocked.value || storageError.value || props.blocked) { emit('refresh'); return }
  if (!mode.value) {
    if (requestedMode.value === 'DISPATCH' ? canDispatch.value : canReceive.value) await open(requestedMode.value)
    else emit('refresh')
    return
  }
  if (mode.value === 'DISPATCH') await loadSource()
  else await open('RECEIPT')
}
function clearPending(): boolean {
  if (!isCurrent()) return false
  try {
    if (pendingRaw === null || !owned.removeIfUnchanged(pendingRaw)) {
      storageError.value = true; storageReason.value = '本地待核对记录已被其他页面更新，未清理新记录。请刷新后人工核对原请求。'
      message.value = storageReason.value; return false
    }
    pending.value = null; pendingRaw = null; return true
  } catch (cause) {
    if (isCancel(cause) || !isCurrent()) return false
    storageError.value = true; message.value = '业务结果已确认，但本地待核对记录未能清理，请恢复浏览器存储后刷新。'; return false
  }
}
function containsRequest(order: TubeOrderDetail, action: TubePlanPendingAction) {
  if (action.kind === 'CORRECTION') {
    const result = order.record_correction, input = action.payload
    return Boolean(result?.id && result.created_at && result.client_request_id === input.client_request_id
      && result.record_kind === input.record_kind && result.record_id === input.record_id && result.operation === input.operation)
  }
  return (action.kind === 'DISPATCH' ? order.dispatch_records : order.receipt_records)?.some(record => record.client_request_id === action.payload.client_request_id) === true
}
function preparedCorrection(order: TubeOrderDetail) {
  if (!isCurrent() || props.blocked || mode.value || pending.value || order.id !== ownedOrderId || !order.is_plan || !order.etag) return
  correctionOrder.value = order; correctionRefreshRequired.value = false; message.value = ''; emit('updated', order)
}
function finishCorrection(result: TubeOrderDetail, action: TubePlanPendingAction) {
  if (action.kind === 'CORRECTION' && action.request_conflict) throw new Error('此请求编号已对应其他更正内容，不能据共有回执确认本次填写内容，请人工核对。')
  if (action.kind !== 'CORRECTION' || result.id !== action.order_id || !result.is_plan || !result.etag || !containsRequest(result, action)) throw new Error('更正回执与原请求不一致，已保留请求编号，请核对本次提交。')
  if (!clearPending()) return
  message.value = ''; correctionRefreshRequired.value = false; correctionOrder.value = null
  records.value?.completeCorrection?.(); correctionActive.value = false; emit('updated', result)
  if (!isCurrent()) return
  ElMessage.success(action.payload.operation === 'DELETE' ? '整次记录已删除，库存和总单进度已更新。' : '记录已调整，库存和总单进度已更新。')
  if (props.actionOnly) emit('closed')
}
function preserveCorrectionConflict(action: Extract<TubePlanPendingAction, { kind: 'CORRECTION' }>) {
  action.request_conflict = true
  try {
    if (pendingRaw === null || owned.read() !== pendingRaw) {
      storageError.value = true; storageReason.value = '本地待核对请求已被其他页面更新，未覆盖新记录。请人工核对请求编号冲突。'; return
    }
    const raw = JSON.stringify(action); owned.write(raw); pendingRaw = raw
  } catch (cause) {
    if (isCancel(cause) || !isCurrent()) return
    storageError.value = true; storageReason.value = '请求编号存在内容冲突，但冲突标记未能写入本地存储。已停止自动核对，请保留本页并人工核对原请求。'
  }
}
async function checkCorrection() {
  const action = pending.value
  if (action?.kind !== 'CORRECTION' || !isCurrent() || props.blocked || saving.value || checkingPending.value || loading.value || storageError.value || !storageAvailable()) return
  const sequence = ++requestSequence
  const current = () => isCurrent() && !props.blocked && sequence === requestSequence
  checkingPending.value = true; message.value = ''
  try {
    owned.assertCurrent()
    const result = await findTubePlanRecordCorrection(action.order_id, action.payload.client_request_id, props.warehouse)
    if (current()) {
      if (action.request_conflict) message.value = '该请求编号已对应其他更正内容，当前填写内容不能据此确认。请人工核对；原请求编号和参数已保留，不会自动重放。'
      else finishCorrection(result, action)
    }
  } catch (cause) {
    if (!current() || isCancel(cause)) return
    message.value = `${isAxiosError(cause) && cause.response?.status === 404 ? '尚未查到本次更正回执。' : errorText(cause, '本次更正结果仍未确认。')} ${action.request_conflict ? '请求编号存在内容冲突，已保留原参数，请人工核对，不会自动重放。' : '已保留原请求编号，可再次核对或按原请求重试。'}`
  } finally { if (current()) checkingPending.value = false }
}
async function postCorrection(action: Extract<TubePlanPendingAction, { kind: 'CORRECTION' }>) {
  const sequence = ++requestSequence
  const current = () => isCurrent() && !props.blocked && sequence === requestSequence
  saving.value = true; message.value = ''
  let checkConflict = false
  try {
    owned.assertCurrent()
    const result = await correctTubePlanRecord(action.order_id, action.payload, action.etag)
    if (current()) finishCorrection(result, action)
  } catch (cause) {
    if (!current() || isCancel(cause)) return
    const status = isAxiosError(cause) ? cause.response?.status : undefined
    const idempotencyConflict = isAxiosError(cause) && cause.response?.data?.error?.code === 'IDEMPOTENCY_CONFLICT'
    if (status && [400, 409, 412, 428].includes(status) && !idempotencyConflict) {
      if (!clearPending()) return
      correctionRefreshRequired.value = true
      message.value = `${errorText(cause, '本次更正未保存。')} 已保留填写内容，请重新核对后再保存。`
    } else {
      message.value = `${errorText(cause, '本次更正结果未知。')} 已保留原请求编号，请核对本次提交或按原请求重试。`
      checkConflict = idempotencyConflict
      if (idempotencyConflict) preserveCorrectionConflict(action)
    }
  } finally { if (current()) saving.value = false }
  if (current() && checkConflict) await checkCorrection()
}
async function submitCorrection(payload: TubePlanRecordCorrectionDraft, etag: string) {
  if (!isCurrent() || props.blocked || !props.warehouse || mode.value || loading.value || saving.value || checkingPending.value || pending.value || storageError.value || !storageAvailable()) return
  const latest = correctionOrder.value
  if (!correctionActive.value || correctionRefreshRequired.value || !latest || latest.etag !== etag || latest.status === 'CANCELLED'
    || !(payload.record_kind === 'DISPATCH' ? latest.permissions.can_dispatch && latest.permissions.can_correct_dispatch === true
      : latest.permissions.can_receive && latest.permissions.can_correct_receive === true)) return
  const record = (payload.record_kind === 'DISPATCH' ? latest.dispatch_records : latest.receipt_records)?.find(item => item.id === payload.record_id)
  if (!record || !['UPDATE', 'DELETE'].includes(payload.operation)) { message.value = '原记录不完整，请重新核对。'; return }
  if (payload.operation === 'UPDATE') {
    const original = new Set(record.lines.map(line => line.component_identity))
    if (!/^\d{4}-\d{2}-\d{2}$/.test(payload.business_date)
      || !payload.lines.length || original.size !== record.lines.length || payload.lines.length !== original.size
      || new Set(payload.lines.map(line => line.component_identity)).size !== original.size
      || payload.lines.some(line => !original.has(line.component_identity) || wholeTubeQuantity(line.quantity) === null || Number(line.quantity) <= 0)) {
      message.value = '请保留全部原部件，填写正整数数量和业务日期。'; return
    }
  }
  const action: TubePlanPendingAction = { kind: 'CORRECTION', order_id: ownedOrderId, etag, payload: { ...payload, client_request_id: createClientUuid() } }
  await persistAction(action)
}
async function persistAction(action: TubePlanPendingAction) {
  try {
    if (owned.read() !== null) { message.value = '其他页面有待核对提交，请刷新后核对原请求。'; return }
    const raw = JSON.stringify(action); owned.write(raw); pendingRaw = raw
  } catch (cause) { if (isCancel(cause) || !isCurrent()) return; storageError.value = true; message.value = '无法保存请求编号，本次尚未提交。请恢复浏览器存储后重试。'; return }
  pending.value = action
  await postPending()
}
async function postPending() {
  const action = pending.value
  if (!action || !isCurrent() || props.blocked || loading.value || checkingPending.value || saving.value || storageError.value || !storageAvailable()) return
  if (action.kind === 'CORRECTION') {
    if (action.request_conflict) { message.value = '该请求编号存在内容冲突，原参数已保留，请人工核对，不能再次重放。'; return }
    await postCorrection(action); return
  }
  saving.value = true; message.value = ''
  try {
    owned.assertCurrent()
    const result = action.kind === 'DISPATCH'
      ? await dispatchTubePlan(action.order_id, action.payload, action.etag)
      : await receiveTubePlan(action.order_id, action.payload, action.etag)
    if (!isCurrent()) return
    if (result.id !== action.order_id || !result.is_plan || !result.etag || !containsRequest(result, action)) throw new Error('返回结果不完整，请核对原请求。')
    if (!clearPending()) return
    emit('updated', result)
    if (!isCurrent()) return
    mode.value = ''; ElMessage.success(action.kind === 'DISPATCH' ? '本次实际外发已登记。' : '本次入库已登记，总单进度已更新。')
    if (props.actionOnly) emit('closed')
  } catch (cause) {
    if (isCancel(cause) || !isCurrent()) return
    const status = isAxiosError(cause) ? cause.response?.status : undefined
    if (status === 403 || status === 404) {
      // 权限或入口拒绝重试不能证明前一次在途请求未写入，保留原编号继续核对。
      message.value = `${errorText(cause, '当前无权核对该总单。')} 原提交结果仍需核对，已保留请求编号。`
    } else if (status && [400, 409, 412, 428].includes(status)) {
      if (!clearPending()) return
      message.value = errorText(cause, '本次未能保存，请核对后重试。')
      if ([409, 412, 428].includes(status)) {
        try {
          owned.assertCurrent()
          const latest = await fetchTubeOrder(action.order_id, props.warehouse)
          if (!isCurrent()) return
          emit('updated', latest)
        } catch (refreshCause) {
          if (isCancel(refreshCause) || !isCurrent()) return
          message.value += ` ${errorText(refreshCause, '刷新总单失败，请稍后重试。')}`
        }
      }
    } else {
      // 结果未知时保留原payload和请求编号，不能重新生成一次收发。
      message.value = '提交结果尚未确认。请点击“核对本次提交”，使用原请求编号重试；系统不会重复扣库或入库。'
    }
  } finally { if (isCurrent()) saving.value = false }
}
function partQuantityError(basis: TubePieceSource | TubeSourceRow, name: string, requested: string) {
  if (basis.blockers.length) return basis.blockers.join('；')
  if (Number(requested) <= Number(basis.max_quantity)) return ''
  if (processorDispatch.value) return `${name}：丝印厂待交 ${number(basis.max_quantity)} ${basis.unit}。`
  if ('screen_print_required' in basis && basis.screen_print_required) {
    return source.value === 'CUTTING'
      ? `${name}须从已丝印裁片库存发出，当前已丝印可用 ${number(basis.printed_available_quantity)} ${basis.unit}。`
      : `${name}：当前库区已丝印可发 ${number(basis.max_quantity)} ${basis.unit}。`
  }
  if (source.value !== 'CUTTING' || !('parent_component_identity' in basis)) return `${name}：来源可用数量不足。`

  const remaining = dispatchRemaining(basis.component_identity)
  if (Number(requested) > remaining) {
    return `${name}：本单已发 ${number(sent(basis.component_identity))} ${basis.unit}，剩余可发 ${number(remaining)} ${basis.unit}。`
  }
  const reason = `${name}：车间可直发 ${number(basis.max_quantity)} ${basis.unit}。`
  const stock = basis.stock_zones?.find(item => Number(item.available_quantity) >= Number(requested))
  const stockZone = stock && sourceZones.value.find(item => item.id === stock.zone_id)
  if (stockZone) {
    return `${reason}请在本单改选「裁片库存」，来源库区选「${stockZone.warehouse_name} / ${stockZone.name}」（可发 ${number(stock.available_quantity)} ${basis.unit}）。`
  }
  return `${reason}本次填写 ${number(requested)} ${basis.unit}，请核对数量。`
}

function showQuantityIssue(rowId: string | undefined, detail: string) {
  message.value = detail
  if (!tubeDispatch.value || !rowId) return
  quantityIssueRow.value = rowId
  void nextTick(() => dispatchTable.value?.querySelector<HTMLInputElement>('[data-quantity-issue] input')?.focus())
}

function clearQuantityIssue() {
  if (!quantityIssueRow.value) return
  quantityIssueRow.value = ''
  message.value = ''
}

async function submit() {
  if (!storageAvailable()) return
  if (locked.value || !mode.value || (mode.value === 'DISPATCH' ? !canDispatch.value : !canReceive.value)) return
  message.value = ''; quantityIssueRow.value = ''
  const positive = entryRows.value.filter(row => Number(row.quantity) > 0)
  if (!date.value) { message.value = '请填写本次实际日期。'; return }
  if (processorDispatch.value && !sourceFactory.value) { message.value = '请选择来源丝印厂。'; return }
  const invalid = entryRows.value.find(row => row.quantity.trim() && wholeTubeQuantity(row.quantity) === null)
  if (invalid) { showQuantityIssue(invalid.id, '实际数量须为非负整数。'); return }
  if (!positive.length) {
    const first = tubeDispatch.value ? entries.value.find(row => dispatchRemaining(row.id) > 0) || entries.value[0] : undefined
    showQuantityIssue(first?.id, tubeDispatch.value ? '请在「本次外发」填写实际发出的支数。' : '请至少填写一个部件的实际数量。')
    return
  }
  let action: TubePlanPendingAction
  if (mode.value === 'DISPATCH') {
    if (!context.value?.ready || (!direct.value && !zone.value)) { message.value = '请先选择并核对实际发货来源。'; return }
    for (const row of positive) {
      const basis = (inputMode.value ? context.value.inputs : context.value.rows)?.find(item => item.component_identity === row.component)
      if (!basis) { message.value = `${row.name}：当前来源没有该部件。`; return }
      const issue = partFlow.value
        ? partQuantityError(basis, row.name, row.quantity)
        : tubeQuantityError(row.quantity, basis as TubeSourceRow, source.value === 'RAW_PIPE', unit.value)
      if (issue) {
        const stockShortage = tubeDispatch.value && source.value === 'PUBLIC_SEMI' && !basis.blockers.length && Number(row.quantity) > Number(basis.max_quantity)
        showQuantityIssue(row.id, stockShortage
          ? `${row.name}：当前库区可用 ${number(basis.max_quantity)} 支，本次填写 ${number(row.quantity)} 支。请调整数量或更换库区。`
          : issue)
        return
      }
      const remaining = dispatchRemaining(row.id)
      if (Number(row.quantity) > remaining) {
        showQuantityIssue(row.id, `${row.name}：本次最多可发 ${number(remaining)} ${entryUnit(row.id)}，累计外发不能超过总单填写数量。`)
        return
      }
      if (!context.value.factories.some(factory => factory.id === row.factory)) { message.value = `${row.name}：总单指定的加工厂当前不可用，请核对总单。`; return }
    }
    const materials = materialEntries.value.filter(row => !row.externalSupply && row.quantity.trim() && Number(row.quantity) !== 0)
    for (const row of materials) {
      const basis = context.value.material_rows?.find(item => item.bom_line_id === row.id)
      const sourceZone = basis?.zones.find(item => item.zone_id === row.zone)
      if (!partFlow.value && (!materialFactory(row.id) || materialFactory(row.id)?.id !== row.factory)) { message.value = `${row.name}：总单未指定唯一加工厂。`; return }
      if (!/^\d+(?:\.\d{1,4})?$/.test(row.quantity.trim()) || !basis || !sourceZone || Number(row.quantity) > Number(sourceZone.available_quantity)
        || !context.value.factories.some(factory => factory.id === row.factory)) { message.value = `${row.name}：请核对辅料数量、总单加工厂和来源库区库存。`; return }
    }
    action = { kind: 'DISPATCH', order_id: props.order.id, etag: props.order.etag, payload: {
      client_request_id: createClientUuid(), source_kind: source.value, zone_id: direct.value ? null : zone.value, actual_dispatch_date: date.value, remark: remark.value.trim(),
      lines: inputMode.value ? [] : positive.map(row => ({ component_identity: row.component, quantity: row.quantity.trim(), factory_id: row.factory })),
      ...(inputMode.value ? { inputs: positive.map(row => ({ component_identity: row.component, quantity: row.quantity.trim(),
        ...(processorDispatch.value ? { print_order_line_id: processorSources.value.get(row.component)!.order_line_id } : {}) })) } : {}),
      ...(materials.length ? { material_source_revision: context.value.material_source_revision, materials: materials.map(row => ({ bom_line_id: row.id, quantity: row.quantity.trim(), factory_id: row.factory, zone_id: row.zone })) } : {}),
    } }
  } else {
    if (!receiptPreview.value?.can_receive || !warehouseId.value) { message.value = '请核对入库权限并选择目标仓库。'; return }
    for (const row of positive) {
      if (printPieces.value && Number(row.quantity) > processorRemaining(row.id)) {
        message.value = `${row.name}：本次回仓不能超过丝印厂待交数量 ${number(processorRemaining(row.id))} ${entryUnit(row.id)}。`; return
      }
      if (!receiptZones.value.some(item => item.id === row.zone)) { message.value = `${row.name}：请选择入库库区。`; return }
    }
    action = { kind: 'RECEIPT', order_id: props.order.id, etag: props.order.etag, payload: {
      client_request_id: createClientUuid(), receipt_date: date.value, warehouse_id: warehouseId.value, remark: remark.value.trim(),
      lines: positive.map(row => ({ order_line_id: row.id, received_quantity: row.quantity.trim(), zone_id: row.zone })),
    } }
  }
  await persistAction(action)
}
onMounted(async () => {
  if (props.readOnly) return
  if (!storageAvailable()) return
  try {
    const raw = owned.read(); pendingRaw = raw
    if (raw === null) {
      if (props.entryAction === 'dispatch') await open('DISPATCH')
      else if (props.entryAction === 'return') await open('RECEIPT')
      return
    }
    const action = JSON.parse(raw) as TubePlanPendingAction
    if (action.order_id !== props.order.id || !['DISPATCH', 'RECEIPT', 'CORRECTION'].includes(action.kind) || typeof action.etag !== 'string' || !action.etag
      || typeof action.payload?.client_request_id !== 'string' || !action.payload.client_request_id) throw new Error('待核对记录不完整')
    if (action.kind === 'CORRECTION') {
      const input = action.payload
      if ((action.request_conflict !== undefined && typeof action.request_conflict !== 'boolean')
        || !['DISPATCH', 'RECEIPT'].includes(input.record_kind) || typeof input.record_id !== 'string' || !input.record_id || !['UPDATE', 'DELETE'].includes(input.operation)
        || (input.operation === 'UPDATE' && (typeof input.business_date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(input.business_date)
          || !Array.isArray(input.lines) || !input.lines.length
          || input.lines.some(line => typeof line.component_identity !== 'string' || !line.component_identity || typeof line.quantity !== 'string' || wholeTubeQuantity(line.quantity) === null || Number(line.quantity) <= 0)
          || new Set(input.lines.map(line => line.component_identity)).size !== input.lines.length))) throw new Error('待核对更正记录不完整')
    } else if (action.kind === 'DISPATCH' && action.payload.inputs?.length) {
      if (!Array.isArray(action.payload.inputs) || action.payload.inputs.some(row => !row.component_identity || typeof row.quantity !== 'string' || wholeTubeQuantity(row.quantity) === null || Number(row.quantity) <= 0)) throw new Error('待核对裁片投入不完整')
    } else if (!Array.isArray(action.payload.lines) || !action.payload.lines.length) throw new Error('待核对记录不完整')
    pending.value = action
    if (action.kind === 'CORRECTION') { await checkCorrection(); return }
    checkingPending.value = true
    owned.assertCurrent()
    const latest = await fetchTubeOrder(ownedOrderId, props.warehouse)
    if (!isCurrent()) return
    if (containsRequest(latest, action)) { if (!clearPending()) return }
    else message.value = '上次提交结果尚未确认，请核对本次提交。'
    emit('updated', latest)
  } catch (cause) {
    if (isCancel(cause) || !isCurrent()) return
    if (!pending.value) storageError.value = true
    message.value = errorText(cause, '待核对记录读取失败，请先核对原业务结果。')
  } finally { if (isCurrent()) checkingPending.value = false }
})
watch([identityBlocked, () => props.blocked], ([identityChanged, blocked]) => {
  if (!identityChanged && !blocked) return
  requestSequence += 1; mode.value = ''; loading.value = false; saving.value = false; checkingPending.value = false
  entries.value = []; materialEntries.value = []; context.value = null; receiptPreview.value = null; remark.value = ''
  correctionActive.value = false; correctionOrder.value = null; message.value = ''; quantityIssueRow.value = ''
  quantityEditing.value = false; quantityOrder.value = null; quantityValues.value = {}; quantityError.value = ''; quantityRefreshRequired.value = false
}, { flush: 'sync' })
onBeforeUnmount(() => { disposed = true; requestSequence += 1 })
</script>

<template>
  <div v-if="!actionOnly" class="plan-detail">
    <ElAlert v-if="identityBlocked" title="身份尚未核验或已变化，已暂停本页操作。请核验身份后重新打开本页。" type="warning" :closable="false" />
    <ElAlert v-if="storageError" :title="storageReason" type="warning" :closable="false" />
    <ElAlert v-if="message && !mode" :title="message" type="warning" :closable="false" />
    <section v-if="!warehouse && order.internal_sewing_parts?.length" class="panel">
      <h2>本厂车缝部位</h2>
      <div class="tube-detail-table-wrap"><table class="tube-detail-table">
        <thead><tr><th>部位</th><th>计划数量</th><th>部位单价（仅记录）</th></tr></thead>
        <tbody><tr v-for="part in order.internal_sewing_parts" :key="part.component_identity">
          <td>{{ part.part_name }}</td><td>{{ number(part.quantity) }} {{ part.unit }}</td>
          <td>{{ formatOutsourcingMoney(part.unit_price) }} 元/{{ part.unit }}</td>
        </tr></tbody>
      </table></div>
    </section>
    <section class="panel">
      <div class="section-heading"><h2>{{ order.product_name }} · {{ order.craft_name }}</h2><div><ElButton v-if="!readOnly && !printPieces && !warehouse && order.permissions.can_edit_quantity === true" :disabled="!canEditQuantity" @click="openQuantityEditor">{{ partFlow ? '编辑计划数量与单价' : '编辑计划数量' }}</ElButton><ElButton v-if="!readOnly && !warehouse && order.permissions.can_cancel" :disabled="locked" @click="!identityBlocked && emit('cancel')">取消委外总单</ElButton><ElButton :icon="Refresh" :disabled="locked" @click="!identityBlocked && emit('refresh')">刷新</ElButton></div></div>
      <div class="plan-context"><span>生产任务 {{ order.task_number }}</span><span>排产 {{ order.schedule_number }}</span><span>计划发出 {{ order.planned_dispatch_date }}</span><span>预计回货 {{ order.expected_return_date }}</span></div>
      <div v-if="partFlow" class="plan-summary">
        <div><span>BOM需求</span><strong>{{ totalText('bom_quantity') }}</strong></div>
        <div><span>{{ printPieces ? '应印裁片' : '目标部位' }}</span><strong>{{ totalText('planned_quantity') }}</strong></div>
        <div><span>累计实际外发</span><strong>{{ totalText('dispatched_quantity') }}</strong></div>
        <div><span>{{ printPieces ? '累计回仓' : '累计入库' }}</span><strong>{{ totalText('received_quantity') }}</strong></div>
        <template v-if="printPieces"><div><span>直送车缝厂</span><strong>{{ totalText('transferred_quantity') }}</strong></div><div><span>丝印厂待交</span><strong>{{ totalText('receivable_quantity') }}</strong></div></template>
        <div v-if="!warehouse"><span>实际回货金额</span><strong>{{ formatOutsourcingMoney(summary?.received_amount) }} 元</strong><small v-if="summary?.has_unknown_receipt_amount">另有历史回货费用未知</small><small v-else-if="order.fees_deferred">未填写单价，后续回货费用未知</small></div>
      </div>
      <div v-else class="plan-summary">
        <div><span>BOM数量</span><strong>{{ number(summary?.bom_quantity) }} {{ unit }}</strong></div>
        <div><span>计划委外</span><strong>{{ number(summary?.planned_quantity) }} {{ unit }}</strong></div>
        <div><span>累计实际外发</span><strong>{{ number(summary?.dispatched_quantity) }} {{ unit }}</strong><small>外发进度 {{ number(summary?.dispatch_progress) }}%</small></div>
        <div><span>累计入库</span><strong>{{ number(summary?.received_quantity) }} {{ unit }}</strong></div>
        <div><span>入库进度</span><strong>{{ number(summary?.receipt_progress) }}%</strong><ElProgress :percentage="progress" :show-text="false" :stroke-width="6" /></div>
        <div v-if="!warehouse && !cutting"><span>喷塑总面积</span><strong>{{ formatOutsourcingMoney(order.total_area_sqm, '—') }} ㎡</strong></div>
        <div v-if="!warehouse"><span>计划加工金额</span><strong>{{ formatOutsourcingMoney(order.planned_amount) }} 元</strong></div>
      </div>
    </section>
    <section class="panel"><div class="section-heading"><h2>{{ printPieces ? '丝印裁片' : '委外部件' }}</h2><span class="muted">按 BOM 数量计算进度，实际数量如实累计</span></div><TubeOutsourcingDetailTable class="plan-parts-table" :columns="columns" :rows="order.lines"><template #cell-purchase_reference="{ row }"><span :title="row.purchase_reference?.conversion_note">{{ quantityReferenceKnown(row) ? number(row.purchase_reference?.quantity) : '—' }}</span></template><template v-for="column in componentSourceColumns" :key="column.key" #[`cell-${column.key}`]="{ row }"><ComponentSourceMaterials :sources="row.component_source_materials" :field="column.sourceField" /></template><template #cell-part_name="{ row }"><ProcessingMaterialDetails :materials="row">{{ row.part_name }}</ProcessingMaterialDetails></template><template #cell-shape="{ row }">{{ tubeMaterialColumn(row, 'shape') }}</template><template #cell-thickness="{ row }">{{ tubeMaterialColumn(row, 'thickness') }}</template><template #cell-spray_color="{ row }">{{ tubeMaterialColumn(row, 'spray_color') }}</template><template #cell-unit_area_sqm="{ row }">{{ formatOutsourcingMoney(row.unit_area_sqm, '—') }}</template><template #cell-line_area_sqm="{ row }">{{ formatOutsourcingMoney(row.line_area_sqm, '—') }}</template><template #cell-price_unit="{ row }">{{ row.price_unit === 'SQUARE_METER' ? '按㎡' : '按支' }}</template><template #cell-unit_price="{ row }">{{ formatOutsourcingMoney(row.unit_price) }}<template v-if="partFlow"> 元/{{ row.unit }}</template><template v-else-if="!cutting"> 元/{{ row.price_unit === 'SQUARE_METER' ? '㎡' : '支' }}</template></template><template #cell-planned_amount="{ row }">{{ formatOutsourcingMoney(row.planned_amount) }}</template><template #cell-received_amount="{ row }">{{ formatOutsourcingMoney(row.received_amount) }}<small v-if="row.has_unknown_receipt_amount"> + 未知</small></template></TubeOutsourcingDetailTable><div v-if="partFlow && order.planned_materials?.length" class="planned-materials"><h3>计划附带辅料</h3><div class="tube-detail-table-wrap"><table class="tube-detail-table planned-material-table"><thead><tr><th>辅料</th><th>规格</th><th>材质</th><th>颜色</th><th>数量</th><th>单位</th><th>加工厂</th></tr></thead><tbody><tr v-for="material in order.planned_materials" :key="`${material.bom_line_id}:${material.factory_id}`"><td><ProcessingMaterialDetails :materials="{ input_material_selection_snapshot: material.material_selection_snapshot }">{{ material.name }}</ProcessingMaterialDetails></td><td>{{ plannedMaterialSpecification(material) }}</td><td>{{ material.material || material.material_selection_snapshot?.attributes?.material || '—' }}</td><td>{{ material.color || material.material_selection_snapshot?.attributes?.color || '—' }}</td><td class="num">{{ number(material.quantity) }}</td><td>{{ material.unit }}</td><td>{{ material.factory_name || '—' }}</td></tr></tbody></table></div><p class="muted">每次实际发货时填写本次数量。</p></div><p v-else-if="cutting && order.planned_materials?.length" class="muted">计划附带辅料：<template v-for="(material, index) in order.planned_materials" :key="material.bom_line_id">{{ index ? '、' : '' }}<ProcessingMaterialDetails :materials="{ input_material_selection_snapshot: material.material_selection_snapshot }">{{ material.name }}</ProcessingMaterialDetails> {{ number(material.quantity) }} {{ material.unit }}</template>；每次实际发货时填写本次数量。</p><p class="muted">{{ order.remark || '无备注' }}</p></section>
    <section v-if="order.sewing_inputs" class="panel"><h2>裁片投入</h2><p class="muted">各裁片按各行单位记录，可分批发出、补发；回货按部位记录。</p><div class="tube-detail-table-wrap"><table class="tube-detail-table plan-input-table"><thead><tr><th>部位</th><th>裁片</th><th>规格</th><th v-for="column in componentSourceColumns" :key="column.key" :style="{ width: `${column.width}px` }">{{ column.label }}</th><th>单位</th><th>每部位数量</th><th>目标对应数量</th><th>累计已发数量</th></tr></thead><tbody><tr v-for="piece in order.inputs" :key="piece.component_identity"><td>{{ piece.parent_name }}</td><td><ProcessingMaterialDetails :materials="piece">{{ piece.part_name }}</ProcessingMaterialDetails></td><td>{{ piece.specification || '—' }}</td><td v-for="column in componentSourceColumns" :key="column.key"><ComponentSourceMaterials :sources="piece.component_source_materials" :field="column.sourceField" /></td><td>{{ piece.unit }}</td><td>{{ number(piece.pieces_per_part) }}</td><td>{{ number(piece.target_quantity) }}</td><td>{{ number(piece.dispatched_quantity) }}</td></tr></tbody></table></div></section>
    <TubeOutsourcingPlanRecords ref="records" :order="order" :warehouse="warehouse" :print-tracking="readOnly" :blocked="Boolean(blocked || identityBlocked || mode || quantityEditing)"
      :busy="saving || checkingPending" :pending="pending?.kind === 'CORRECTION'" :write-blocked="Boolean(storageError || loading || (pending && pending.kind !== 'CORRECTION'))"
      :request-conflict="pending?.kind === 'CORRECTION' && pending.request_conflict"
      :message="correctionActive || pending?.kind === 'CORRECTION' ? message : ''" :refresh-required="correctionRefreshRequired"
      @active="correctionActive = $event" @prepared="preparedCorrection" @correct="submitCorrection" @check="checkCorrection" @retry="postPending">
      <template #dispatch-action><ElButton v-if="warehouse" type="primary" :disabled="!canDispatch" @click="open('DISPATCH')">材料发出</ElButton></template>
      <template #receipt-action><ElButton v-if="warehouse" type="primary" :disabled="!canReceive" @click="open('RECEIPT')">外发入库</ElButton></template>
    </TubeOutsourcingPlanRecords>
    <template v-if="pending"><ElButton type="primary" :loading="saving || checkingPending" :disabled="storageError || identityBlocked || blocked || loading || checkingPending" @click="pending.kind === 'CORRECTION' ? checkCorrection() : postPending()">核对本次提交</ElButton><ElButton v-if="pending.kind === 'CORRECTION' && !pending.request_conflict" :disabled="saving || checkingPending || storageError || identityBlocked || blocked" @click="postPending">按原请求重试</ElButton></template>
  </div>
  <AppWindowDialog :model-value="quantityEditing" :title="partFlow ? '编辑计划数量与单价' : '编辑计划数量'" :width="1500" class="tube-outsourcing-detail-dialog" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" @update:model-value="closeQuantityEditor">
    <ElAlert v-if="quantityError" :title="quantityError" type="warning" :closable="false" />
    <p class="muted">{{ partFlow ? '按各部位单位填写目标和单价；对应投入数量不能少于累计已发。修改单价仅用于后续回货，历史回货保持原价，原空价保持未知。' : '计划数量按委外需求填写，采购入库数量仅供参考；修改后的计划数量不能小于累计已发。' }}</p>
    <TubeOutsourcingDetailTable v-loading="loading" class="plan-quantity-table" :columns="quantityColumns" :rows="quantityOrder?.lines || []">
      <template v-for="column in componentSourceColumns" :key="column.key" #[`cell-${column.key}`]="{ row }"><ComponentSourceMaterials :sources="row.component_source_materials" :field="column.sourceField" /></template><template #cell-part_name="{ row }"><ProcessingMaterialDetails :materials="row">{{ row.part_name }}</ProcessingMaterialDetails></template>
      <template #cell-shape="{ row }">{{ tubeMaterialColumn(row, 'shape') }}</template>
      <template #cell-thickness="{ row }">{{ tubeMaterialColumn(row, 'thickness') }}</template>
      <template #cell-spray_color="{ row }">{{ tubeMaterialColumn(row, 'spray_color') }}</template>
      <template #cell-purchase_reference="{ row }"><span :title="row.purchase_reference?.conversion_note">{{ quantityReferenceKnown(row) ? number(row.purchase_reference?.quantity) : '—' }}</span></template>
      <template #cell-dispatched_quantity="{ row }">{{ number(row.dispatched_quantity ?? '0') }}</template>
      <template #cell-unit_price="{ row }"><ElInput v-model="priceValues[row.id]" :disabled="quantityLocked" inputmode="decimal" placeholder="历史空价可补填" :aria-label="`${row.part_name}加工单价`"><template #suffix>元/{{ row.unit }}</template></ElInput></template>
      <template #cell-quantity="{ row }"><ElInput v-model="quantityValues[row.id]" :disabled="quantityLocked" inputmode="numeric" :aria-label="`${row.part_name}计划数量`" /></template>
    </TubeOutsourcingDetailTable>
    <template #footer><ElButton :disabled="saving" @click="closeQuantityEditor">关闭</ElButton><ElButton v-if="quantityError || quantityRefreshRequired" :disabled="loading || saving || identityBlocked || blocked" @click="loadQuantityEditor">重新加载</ElButton><ElButton type="primary" :disabled="quantityLocked" :loading="saving" @click="saveQuantity">{{ partFlow ? '保存数量与单价' : '保存数量' }}</ElButton></template>
  </AppWindowDialog>
  <AppWindowDialog :model-value="actionOnly || Boolean(mode)" :title="pending?.kind === 'CORRECTION' ? '收发记录更正核对' : dialogMode === 'DISPATCH' ? '材料发出' : '外发入库'" :width="1800" class="tube-outsourcing-detail-dialog plan-action-dialog" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" @update:model-value="close">
    <p><template v-if="tubeDispatch"><strong>生产任务单号 {{ order.task_order_number || order.task_number }}</strong> · </template>{{ order.order_number }} · {{ order.product_name }} · {{ order.craft_name }}</p>
    <ElAlert v-if="identityBlocked" title="身份尚未核验或已变化，已暂停本页操作。请核验身份后重新打开本页。" type="warning" :closable="false" />
    <ElAlert v-if="storageError" :title="storageReason" type="warning" :closable="false" />
    <ElAlert v-if="blocked" title="正在核对委外总单，请稍候。" type="info" :closable="false" />
    <ElAlert v-if="message && !quantityIssueRow" :title="message" type="warning" :closable="false" />
    <p v-if="pending?.kind === 'CORRECTION'">待核对：{{ pending.payload.record_kind === 'DISPATCH' ? '外发' : '入库' }}记录{{ pending.payload.operation === 'DELETE' ? '整次删除' : '调整' }}。请先核对原请求，再办理新的收发。</p>
    <div v-if="!mode" class="plan-action-status"><p>{{ actionUnavailable }}</p></div>
    <template v-else>
      <div class="plan-fields">
        <label class="form-field"><span>{{ mode === 'DISPATCH' ? '实际发出日期' : '入库日期' }}</span><ElDatePicker v-model="date" type="date" value-format="YYYY-MM-DD" :disabled="locked" :aria-label="mode === 'DISPATCH' ? '实际发出日期' : '入库日期'" /></label>
        <template v-if="mode === 'DISPATCH'">
          <div v-if="tubeDispatch" class="form-field">
            <span>实际材料来源</span>
            <div class="plan-dispatch-source">
              <strong>{{ dispatchSourceLabels[source] || order.source_label }}</strong>
              <ElDropdown v-if="(options?.source_kinds.length || 0) > 1" trigger="click" placement="bottom-start" :disabled="locked" @command="changeSource">
                <ElButton link type="primary" :disabled="locked">更换来源</ElButton>
                <template #dropdown>
                  <ElDropdownMenu>
                    <ElDropdownItem v-for="item in options?.source_kinds || []" :key="item.value" :command="item.value" :disabled="item.value === source">{{ dispatchSourceLabels[item.value] || item.label }}</ElDropdownItem>
                  </ElDropdownMenu>
                </template>
              </ElDropdown>
            </div>
          </div>
          <label v-else class="form-field"><span>实际材料来源</span><ElSelect :model-value="source" :disabled="locked" aria-label="实际材料来源" @change="changeSource"><ElOption v-for="item in options?.source_kinds || []" :key="item.value" :value="item.value" :label="item.label" /></ElSelect></label>
          <label v-if="processorDispatch" class="form-field"><span>来源丝印厂</span><ElSelect v-model="sourceFactory" :disabled="locked" aria-label="来源丝印厂" placeholder="选择来源丝印厂" no-data-text="暂无待交裁片"><ElOption v-for="[id, name] in processorFactories" :key="id" :value="id" :label="name" /></ElSelect></label>
          <label v-if="!direct" class="form-field"><span>实际来源库区</span><ElSelect v-model="zone" :disabled="locked" aria-label="实际来源库区" :placeholder="tubeDispatch ? '请选择实际取货库区' : undefined" @change="loadSource"><ElOption v-for="item in sourceZones" :key="item.id" :value="item.id" :label="`${item.warehouse_name} / ${item.name}`" /></ElSelect></label>
        </template>
        <label v-else class="form-field"><span>入库仓库</span><ElSelect :model-value="warehouseId" :disabled="locked" aria-label="入库仓库" @update:model-value="changeReceiptWarehouse"><ElOption v-for="item in receiptPreview?.warehouses || []" :key="item.id" :value="item.id" :label="item.name" /></ElSelect></label>
      </div>
      <div v-if="partFlow" v-loading="loading" class="tube-detail-table-wrap"><table class="tube-detail-table plan-entry-table plan-entry-table--parts">
        <thead><tr><th>{{ inputMode ? '部位 / 裁片' : printPieces ? '裁片' : '部位' }}</th><th>规格</th><th v-for="column in componentSourceColumns" :key="column.key" :style="{ width: `${column.width}px` }">{{ column.label }}</th><th>单位</th><th v-if="processorDispatch">来源丝印单</th><th v-if="processorDispatch">丝印厂待交</th><th v-if="mode === 'DISPATCH'">可外发多少</th><th v-if="mode === 'DISPATCH'">已外发</th><th v-else>累计入库</th><th v-if="printPieces && mode === 'RECEIPT'">丝印厂待交</th><th>本次数量</th><th>{{ processorDispatch ? '目的车缝厂' : '加工厂' }}</th><th v-if="mode === 'RECEIPT'">入库库区</th></tr></thead>
        <tbody><tr v-for="row in entryRows" :key="row.id"><td><ProcessingMaterialDetails :materials="entryMaterial(row)">{{ row.name }}</ProcessingMaterialDetails>
          <div v-if="!processorDispatch && printedPiece(row.component)" class="printed-stock">
            <span>回仓已丝印可用 {{ number(printedPiece(row.component)?.printed_available_quantity) }} {{ entryUnit(row.id) }}</span>
            <template v-if="source === 'CUTTING'"><ElButton v-for="stock in printedPiece(row.component)?.stock_zones" :key="stock.zone_id" link type="primary" :disabled="locked" @click="usePrintedStock(stock.zone_id)">从{{ zoneName(stock.zone_id) }}发（{{ number(stock.available_quantity) }}）</ElButton></template>
          </div>
        </td><td>{{ entryAttribute(row, 'specification') }}</td><td v-for="column in componentSourceColumns" :key="column.key"><ComponentSourceMaterials :sources="entryMaterial(row).component_source_materials" :field="column.sourceField" /></td><td>{{ entryUnit(row.id) }}</td>
          <template v-if="processorDispatch"><td>{{ processorSources.get(row.component)?.order_number }}</td><td class="num">{{ number(processorSources.get(row.component)?.available_quantity) }}</td></template>
          <template v-if="mode === 'DISPATCH'"><td class="num">{{ number(entryAvailable(row)) }}</td><td class="num">{{ number(sent(row.id)) }}</td></template><td v-else class="num">{{ number(received(row.id)) }}</td>
          <td v-if="printPieces && mode === 'RECEIPT'" class="num">{{ number(processorRemaining(row.id)) }}</td>
          <td class="num"><ElInput v-model="row.quantity" :disabled="locked" inputmode="numeric" placeholder="0或空白" :aria-label="`${row.name}本次数量`" /></td><td>{{ entryFactory(row.id) }}</td>
          <td v-if="mode === 'RECEIPT'"><ElSelect v-model="row.zone" :disabled="locked || !(Number(row.quantity) > 0)" :aria-label="`${row.name}入库库区`"><ElOption v-for="item in receiptZones" :key="item.id" :value="item.id" :label="item.name" /></ElSelect></td>
        </tr><tr v-if="processorDispatch && !entryRows.length"><td colspan="16">{{ processorFactories.length ? '请选择来源丝印厂查看待交裁片。' : '当前订单没有可从丝印厂直送的裁片。' }}</td></tr></tbody>
      </table></div>
      <div v-else v-loading="loading" class="tube-detail-table-wrap"><table ref="dispatchTable" class="tube-detail-table plan-entry-table" :class="{ 'plan-entry-table--tube': !cutting }">
        <colgroup>
          <col style="width:90px" /><col style="width:70px" /><col style="width:110px" /><template v-if="cutting"><col style="width:80px" /><col style="width:75px" /></template><template v-else><col style="width:60px" /><col style="width:65px" /><col style="width:75px" /><col style="width:75px" /></template><col v-if="mode === 'DISPATCH'" style="width:90px" /><col style="width:80px" /><col style="width:80px" />
          <col v-if="tubeDispatch" style="width:110px" /><col v-if="warehouseDispatch" style="width:110px" />
          <col style="width:105px" /><col style="width:110px" /><col v-if="mode === 'RECEIPT'" style="width:130px" />
        </colgroup>
        <thead><tr>
          <th>部位</th><th>材质</th><th>规格</th><template v-if="cutting"><th>颜色</th><th class="num">每套片数</th></template><template v-else><th>形状</th><th>厚度 mm</th><th>喷塑颜色</th><th>切割长度 mm</th></template><th v-if="mode === 'DISPATCH'" class="num">需要外发（{{ unit }}）</th><th class="num">累计已发</th><th class="num">累计入库</th>
          <th v-if="tubeDispatch" class="num">本单剩余可发（支）</th><th v-if="warehouseDispatch" class="num">当前库区可用（支）</th>
          <th class="num">本次{{ mode === 'DISPATCH' ? '外发' : '入库' }}（{{ unit }}）</th><th>{{ mode === 'RECEIPT' ? '计划加工厂' : '加工厂' }}</th><th v-if="mode === 'RECEIPT'">入库库区</th>
        </tr></thead>
        <tbody><tr v-for="row in entries" :key="row.id">
          <td><ProcessingMaterialDetails :materials="mode === 'DISPATCH' ? entryMaterial(row) : { output_material_selection_snapshot: order.lines.find(item => item.id === row.id)?.output_material_selection_snapshot }">{{ row.name }}</ProcessingMaterialDetails></td>
          <td>{{ entryAttribute(row, 'material') }}</td><td>{{ entryAttribute(row, 'specification') }}</td>
          <template v-if="cutting"><td>{{ entryAttribute(row, 'fabric_color') }}</td><td class="num">{{ number(entryMaterial(row).pieces_per_set) }}</td></template><template v-else><td>{{ tubeMaterialColumn(entryMaterial(row), 'shape') }}</td><td>{{ tubeMaterialColumn(entryMaterial(row), 'thickness') }}</td><td>{{ tubeMaterialColumn(entryMaterial(row), 'spray_color') }}</td><td>{{ entryAttribute(row, 'cutting_length_mm') }}</td></template>
          <td v-if="mode === 'DISPATCH'" class="num">{{ number(planned(row.id)) }}</td><td class="num">{{ number(sent(row.id)) }}</td><td class="num">{{ number(received(row.id)) }}</td>
          <td v-if="tubeDispatch" class="num">{{ number(dispatchRemaining(row.id)) }}</td>
          <td v-if="warehouseDispatch" class="num">{{ number(dispatchStockQuantity(row.component)) }}</td>
          <td class="num" :data-quantity-issue="quantityIssueRow === row.id || undefined">
            <ElInput v-model="row.quantity" :disabled="locked" inputmode="numeric" placeholder="0或空白" :aria-label="`${row.name}本次数量`" :aria-invalid="quantityIssueRow === row.id || undefined" :aria-describedby="quantityIssueRow === row.id ? `dispatch-quantity-issue-${row.id}` : undefined" @input="clearQuantityIssue" />
            <p v-if="message && quantityIssueRow === row.id" :id="`dispatch-quantity-issue-${row.id}`" class="plan-quantity-issue" role="alert">{{ message }}</p>
          </td>
          <td>{{ entryFactory(row.id) }}</td><td v-if="mode === 'RECEIPT'"><ElSelect v-model="row.zone" :disabled="locked || !(Number(row.quantity) > 0)" :aria-label="`${row.name}入库库区`"><ElOption v-for="item in receiptZones" :key="item.id" :value="item.id" :label="item.name" /></ElSelect></td>
        </tr></tbody>
      </table></div>
      <p class="muted">{{ processorDispatch ? '按丝印厂直接交给目的车缝厂的实际数量登记。' : printPieces && mode === 'RECEIPT' ? '本次收回的裁片将标记为「已丝印」。' : mode === 'DISPATCH' ? '可外发多少 = 总单目标数量 - 已外发数量；本次外发不能超过可外发数量，库存来源还需满足实际库存。' : '按实际回货数量填写本次收到的部件，其余留空或填0。加工厂按总单计划显示，回货不匹配外发批次。' }}</p>
      <template v-if="mode === 'DISPATCH' && cutting && materialEntries.length"><h3>本次附带辅料（选填）</h3><div class="tube-detail-table-wrap"><table class="tube-detail-table plan-entry-table plan-material-table" :class="{ 'plan-material-table--parts': partFlow }"><thead><tr><th>辅料</th><template v-if="partFlow"><th>规格</th><th>材质</th><th>颜色</th><th>单位</th></template><th class="num">可外发多少</th><th class="num">已外发</th><th class="num">本次数量</th><th>加工厂</th><th>来源库区</th></tr></thead><tbody><tr v-for="row in materialEntries" :key="row.id">
        <td><ProcessingMaterialDetails :materials="{ input_material_selection_snapshot: materialSource(row.id)?.material_selection_snapshot }">{{ row.name }}</ProcessingMaterialDetails><span v-if="row.externalSupply">（外供）</span></td><template v-if="partFlow"><td>{{ materialSpecificationValue(materialSource(row.id) || {}) }}</td><td>{{ materialSource(row.id)?.material || '—' }}</td><td>{{ materialSource(row.id)?.color || '—' }}</td><td>{{ materialSource(row.id)?.unit || '—' }}</td></template>
        <td v-if="row.externalSupply" colspan="5" class="num">—</td>
        <template v-else>
        <td class="num">{{ number(materialSource(row.id)?.max_quantity ?? '0') }}</td><td class="num">{{ number(materialSource(row.id)?.outsourcing_issued_quantity ?? '0') }}</td>
        <td class="num"><ElInput v-model="row.quantity" :disabled="locked || (!partFlow && !row.factory)" inputmode="decimal" :aria-label="`${row.name}本次辅料数量`" /></td><td><ElSelect v-if="partFlow" v-model="row.factory" :disabled="locked" :aria-label="`${row.name}辅料加工厂`"><ElOption v-for="factory in context?.factories || []" :key="factory.id" :value="factory.id" :label="factory.name" /></ElSelect><template v-else>{{ materialFactory(row.id)?.name || '总单未指定唯一加工厂' }}</template></td>
        <td><ElSelect v-model="row.zone" :disabled="locked || !row.factory" :aria-label="`${row.name}辅料库区`"><ElOption v-for="item in context?.material_rows?.find(item => item.bom_line_id === row.id)?.zones || []" :key="item.zone_id" :value="item.zone_id" :label="`${item.warehouse_name} / ${item.zone_name}（${item.available_quantity}）`" /></ElSelect></td>
        </template>
      </tr></tbody></table></div></template>
      <label class="form-field"><span>备注（选填）</span><ElInput v-model="remark" type="textarea" :rows="2" :disabled="locked" maxlength="2000" aria-label="本次备注" /></label>
    </template>
    <template #footer><ElButton :disabled="saving" @click="close">关闭</ElButton><ElButton v-if="!pending && ((message && !quantityIssueRow) || !mode)" :disabled="saving || loading || checkingPending" @click="reloadAction">重新加载</ElButton><template v-if="pending"><ElButton type="primary" :loading="saving || checkingPending" :disabled="storageError || identityBlocked || blocked || loading || checkingPending" @click="pending.kind === 'CORRECTION' ? checkCorrection() : postPending()">核对本次提交</ElButton><ElButton v-if="pending.kind === 'CORRECTION' && !pending.request_conflict" :disabled="saving || checkingPending || storageError || identityBlocked || blocked" @click="postPending">按原请求重试</ElButton></template><ElButton v-else-if="mode" type="primary" :disabled="locked || (tubeDispatch && !context?.ready)" @click="submit">{{ mode === 'DISPATCH' ? '确认材料发出' : '确认入库' }}</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.plan-detail { display: flex; flex-direction: column; gap: 14px; min-height: 0; overflow: auto; }
.plan-detail > .panel { flex-shrink: 0; }
.plan-context { display: flex; flex-wrap: wrap; gap: 12px 24px; margin: 12px 0; color: var(--erp-color-text-secondary); }
.printed-stock { display: grid; justify-items: start; gap: 2px; }
.plan-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 20px; border-top: 1px solid var(--erp-color-border); padding-top: 14px; }
.plan-summary > div { display: flex; flex-direction: column; gap: 6px; }
.plan-summary span, .plan-summary small { color: var(--erp-color-text-secondary); }
.plan-summary strong { font-size: 22px; color: var(--erp-color-brand); }
.plan-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin: 14px 0; }
.plan-fields :deep(.el-date-editor) { width: 100%; }
.plan-dispatch-source { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; min-height: 28px; }
.plan-quantity-issue { margin: 4px 0 0; text-align: left; color: var(--erp-color-danger); font-size: 12px; }
.plan-entry-table [data-quantity-issue] :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px var(--erp-color-danger) inset; }
.plan-entry-table { min-width: 1040px; }
.plan-entry-table--tube { min-width: 1255px; }
.plan-entry-table--parts { min-width: 1600px; }
.plan-input-table { min-width: 1380px; }
.planned-material-table { min-width: 720px; }
.plan-entry-table th, .plan-entry-table td { padding: 8px 6px; white-space: normal; overflow-wrap: anywhere; }
.plan-entry-table .num { text-align: center; }
.plan-entry-table :deep(.el-input__inner) { text-align: center; }
.plan-quantity-table :deep(.el-input__inner) { text-align: center; }
.plan-entry-table :deep(.el-select) { width: 100%; }
.plan-material-table { min-width: 640px; }
.plan-material-table--parts { min-width: 1080px; }
.plan-action-status { min-height: 96px; padding: 16px 0; }
@media(max-width:900px) { .plan-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }.plan-fields { grid-template-columns: 1fr; } }
</style>
