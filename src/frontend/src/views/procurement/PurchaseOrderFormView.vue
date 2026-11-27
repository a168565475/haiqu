<script setup lang="ts">
import { compactDecimal } from '@/utils/compactDecimal'
import { createClientUuid } from '@/utils/clientUuid'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import PurchaseGridCell from './PurchaseGridCell.vue'
import { pipeMeters, pipeRootsFromMeters, samplePipeSuggestedWeight } from '@/utils/pipeQuantities'
import { computed, h, markRaw, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import backIcon from '@/assets/procurement/create-back.svg'
import refreshIcon from '@/assets/procurement/create-refresh.svg'
import calendarIcon from '@/assets/procurement/create-calendar.svg'
import expandIcon from '@/assets/procurement/create-expand.svg'
import rightIcon from '@/assets/procurement/create-right.svg'
import { ArrowDown } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { isAxiosError } from 'axios'
import { useRoute, useRouter } from 'vue-router'

import {
  createPurchaseOrder,
  fetchPurchaseOrderOptions,
  fetchPurchaseOrderSource,
  fetchSamplePurchaseOrderSource,
  fetchVersionedPurchaseOrder,
} from '@/api/purchaseOrders'
import { confirmPurchaseBatchPage, createPurchaseBatch, createPurchaseGroup, fetchPurchaseGroups, fetchVersionedPurchaseGroup, submitPurchaseSupplierBatch } from '@/api/purchaseGroups'
import { fetchPackagingPurchaseOptions, fetchPackagingPurchasePage, fetchPackagingPurchaseSources, preparePackagingPurchase, writePackagingPurchasePage } from '@/api/purchaseGroups'
import type { PackagingPurchaseSource, PurchaseBatchInput, PurchaseBatchPageConfirmationInput, PurchaseGroup, PurchaseGroupProgressLine } from '@/types/purchaseGroup'
import type { SupplierCategory } from '@/types/supplier'
import { useAuthStore } from '@/stores/auth'
import type {
  PurchaseOrderSourceBlocker,
  PurchaseOrderBomOption,
  PurchaseOrderInput,
  PurchaseOrderOptions,
  PurchaseOrderProductSource,
  PurchaseOrderProductionTaskOption,
  PurchaseOrderSource,
  PurchaseOrderSourceLine,
  PurchaseOrderSupplierOption,
  PurchaseBatchType,
  PurchaseSetPricing,
} from '@/types/purchaseOrder'
import { materialAttributeFields, materialSpecificationValue } from '@/utils/materialAttributes'
import { isHardwareWeightLine, isWeightPurchaseLine as isWeightSourceLine } from './purchaseWeight'
import { decimalParts, formatScaled, scaledProduct } from './purchaseAmounts'
import { formatMoney } from './purchaseOrderDetailDisplay'
import PurchaseSetPriceCell from './PurchaseSetPriceCell.vue'
import PurchaseSetPricingDialog from './PurchaseSetPricingDialog.vue'
import PurchaseQuantitySources from './PurchaseQuantitySources.vue'
import { applySetPricing, isExplicitZeroPrice, orderSetQuantity, setPriceText, syncSetTerm, type SetPricingChange } from './purchaseSetPricing'

interface PurchaseLineDraft extends PurchaseOrderSourceLine {
  batch_source?: PurchaseGroupProgressLine
  material_color?: string
  set_pricing?: PurchaseSetPricing | null
  purchase_group_line_id?: string
  supplier_id: string | null
  delivery_date: string
  actual_bar_count: string
  actual_purchase_quantity: string
  unit_price: string
}

interface PendingSupplierBatch {
  groupId: string
  groupEtag: string
  supplierName: string
  payload: PurchaseBatchInput
}

interface SupplierBatchReview {
  groupId: string
  groupEtag: string
  supplierName: string
  lines: PurchaseLineDraft[]
  error: string
}

interface FinalBatchReview {
  groupId: string
  etag: string
  payload: PurchaseBatchPageConfirmationInput
  additionalSummary: { suppliers: string; amount: string } | null
  error: string
  uncertain: boolean
}

const CalendarIcon = () => h('img', { src: calendarIcon, width: 16, height: 16, alt: '' })
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const isSuperuser = computed(() => authStore.user?.is_superuser === true)
const isPackaging = computed(() => route.name === 'packaging-purchase-create' || route.name === 'packaging-purchase-batch')
const canAdd = computed(() => isSuperuser.value || authStore.hasPermission(isPackaging.value ? 'procurement.manage_packagingpurchase' : 'procurement.add_purchaseorder'))
const isBatchMode = computed(() => route.name === 'purchase-batch-create' || route.name === 'packaging-purchase-batch')
const packagingSources = ref<PackagingPurchaseSource[]>([])
let packagingNoticeApplied = false
const selectedPackagingGroupIds = computed(() => [route.query.group_ids].flat().filter((id): id is string => typeof id === 'string'))
const packagingGroups = ref<PurchaseGroup[]>([])
const packagingGroupIds = computed(() => selectedPackagingGroupIds.value.length ? selectedPackagingGroupIds.value : packagingGroups.value.map(item => item.id))
const packagingLineGroup = computed(() => new Map(packagingGroups.value.flatMap(item => item.progress.lines.map(line => [line.id, item] as const))))
const packagingDraftGroup = computed(() => new Map(packagingGroups.value.flatMap(item => (item.batch_page?.draft_orders ?? []).map(order => [order.id, item] as const))))
const isMultiTask = computed(() => packagingGroupIds.value.length > 1)
const group = ref<PurchaseGroup | null>(null)
const groupEtag = ref('')
const batchSessionId = computed(() => typeof route.query.batch_session_id === 'string' ? route.query.batch_session_id : undefined)
const currentBatchNumber = ref<number | null>(null)
const displayedBatchNumber = computed(() => currentBatchNumber.value ?? group.value?.batch_page?.next_batch_number)
const batchType = ref<PurchaseBatchType>('NORMAL')
const batchRequestId = ref('')
let batchContentSignature = ''
const batchConflict = ref('')
const supplierBatchReview = ref<SupplierBatchReview | null>(null)
const pendingSupplierBatch = ref<PendingSupplierBatch | null>(null)
const lastSupplierBatch = ref<{ number: number; supplierName: string; lineCount: number } | null>(null)
const finalBatchReview = ref<FinalBatchReview | null>(null)
const savedSupplierOrders = computed(() => group.value?.batch_page?.draft_orders ?? [])
const packagingPageConfirmed = computed(() => isPackaging.value && !savedSupplierOrders.value.length &&
  group.value?.batches.some(batch => batch.batch_session_id === batchSessionId.value && batch.status !== 'DRAFT'))
const canReadSupplierSheets = computed(() => isSuperuser.value || (isPackaging.value
  ? canAdd.value : authStore.moduleCan('procurement.view_supplierpurchasesheet', 'procurement.view_purchaseorder')))
const fulfilledSupplierLineIds = new Set<string>()
const selectedLines = computed(() => isBatchMode.value
  ? lines.value.filter(line => isPositiveDecimal(line.required_quantity || '') && isPositiveDecimal(effectivePurchaseQuantity(line))
    && (line.set_pricing || !isExplicitZeroPrice(line.unit_price)))
  : lines.value)
const confirmationLines = computed(() => isBatchMode.value ? selectedLines.value.filter(hasPurchasePrice) : selectedLines.value)
const canWriteLines = computed(() => isBatchMode.value ? Boolean(group.value && !group.value.combined_into_group_id && group.value.progress.status !== 'UNKNOWN' && !saving.value && !pendingSupplierBatch.value && !packagingPageConfirmed.value) : Boolean(source.value?.can_create))
const canSubmitSupplierBatch = computed(() => isBatchMode.value && (isSuperuser.value || (isPackaging.value ? canAdd.value : (
  canAdd.value && authStore.hasPermission('procurement.submit_purchaseorder')
  && authStore.hasPermission('procurement.view_purchaseorder')
  && authStore.moduleCan('access_control.generate_purchasesheets', 'procurement.add_purchaseorder')
))))

const options = ref<PurchaseOrderOptions>({
  production_tasks: [], suppliers: [], currencies: [], default_currency_id: null,
})
const source = ref<PurchaseOrderSource | null>(null)
const lines = ref<PurchaseLineDraft[]>([])
// 表格只需观察行的增减和顺序，格内仍绑定原来的响应式明细。
const gridRows = computed(() => markRaw(lines.value.slice()))
const editingSetId = ref('')
const setCandidates = computed(() => editingSetId.value ? lines.value.filter(line =>
  !isPackaging.value || packagingLineGroup.value.get(line.purchase_group_line_id!) === packagingLineGroup.value.get(editingSetId.value),
).map(line => ({
  ...line, quantityText: effectivePurchaseQuantity(line),
  eligible: isPositiveDecimal(effectivePurchaseQuantity(line)) && isPositiveDecimal(line.required_quantity || ''),
})) : [])
const setSource = computed(() => setCandidates.value.find(line => line.purchase_group_line_id === editingSetId.value))
function saveSet(change: SetPricingChange) {
  applySetPricing(lines.value, change)
  editingSetId.value = ''
  refreshBulkSupplier()
  refreshBulkDeliveryDate()
}
const batchRemainingQuantities = computed(() => new Map((group.value?.progress.lines || []).map(line => {
  const snapshot = line.source_snapshot
  const isPipe = snapshot.section_type_snapshot === 'PROFILE'
  const isWeight = isWeightSourceLine({
    section_type: snapshot.section_type_snapshot,
    section_title: snapshot.section_title_snapshot,
    source_unit_text: line.source_unit_text || snapshot.source_unit_text,
    suggested_purchase_weight_kg: snapshot.suggested_purchase_weight_kg,
    calculation_snapshot: snapshot.calculation_snapshot,
  })
  const quantity = remainingForBatch(line, isWeight ? snapshot.suggested_purchase_weight_kg || line.required_quantity : isPipe ? snapshot.suggested_purchase_meters : line.required_quantity)
  return [line.id, {
    primary: isWeight ? quantity === null ? '重量待核对' : `${quantity} kg` : isPipe ? quantity === null ? '米数待核对' : `${quantity} 米` : quantity ?? '待核对',
    detail: isWeight || isPipe ? '' : line.source_unit_text || '单位未识别',
  }]
})))
const selectedTaskId = ref('')
const selectedBomIds = ref<string[]>([])
const selectedBomId = computed(() => selectedBomIds.value.length === 1 ? selectedBomIds.value[0]! : '')
const selectedBomSources = computed(() => selectedBomIds.value.map(bom_id => {
  const option = source.value?.bom_options.find(item => item.bom_id === bom_id)
  return { bom_id, source_revision: option?.combine_source_revision || option?.source_revision
    || (source.value?.selected_bom_id === bom_id ? source.value.source_revision : '') }
}))
const sourceTypeFilter = ref<'ALL' | 'PRODUCTION' | 'SAMPLE'>('ALL')
const detailFullscreen = ref(false)
const bulkSupplierCategory = ref<string | null>(null)
const bulkSupplierId = ref<string | null>(null)
const bulkDeliveryDate = ref('')
const optionsLoading = ref(true)
const sourceLoading = ref(false)
const saving = ref(false)
const loadError = ref('')
const sourceError = ref('')
const preselectionError = ref('')
const formPage = ref<HTMLElement | null>(null)
const hoveredLineKey = ref('')
let sourceRequestId = 0

const form = reactive({
  currencyId: '',
})

const sourceOptions = computed<PurchaseOrderProductionTaskOption[]>(() => [
  ...options.value.production_tasks.map(item => ({ ...item, source_type: 'PRODUCTION' as const, source_number: item.task_number })),
  ...(options.value.sample_requests || []).map(item => ({ ...item, source_id: item.id, id: `sample:${item.id}`, task_number: item.source_number, order_number: '' })),
].sort((left, right) => Number(right.can_create) - Number(left.can_create)))
const visibleSourceOptions = computed(() => sourceOptions.value.filter(item => (item.can_create || (item.source_type !== 'SAMPLE' && item.blockers?.some(blocker => ['PURCHASE_GROUP_EXISTS', 'PURCHASE_ORDER_EXISTS'].includes(blocker.code))))
  && (sourceTypeFilter.value === 'ALL' || item.source_type === sourceTypeFilter.value)))
const isDetailStep = computed(() => route.name === 'purchase-order-create-details' || isBatchMode.value)
const isSampleSource = computed(() => selectedTask.value?.source_type === 'SAMPLE')
const sourceTypeLabel = computed(() => isSampleSource.value ? '打样单' : '生产订单')
const selectedTask = computed(() => sourceOptions.value.find((item) => item.id === selectedTaskId.value) || null)
const selectedProducts = computed(() => source.value?.production_task?.products || [])
const productRows = computed(() => {
  const options = new Map(source.value?.bom_options.map(option => [option.product_line_id, option]))
  return selectedProducts.value.map(product => {
    const option = options.get(product.id)
    return { product, option, available: selectableProduct(option),
      checked: selectedBomIds.value.includes(option?.bom_id || '') }
  })
})
const existingSourceBlocker = computed(() => source.value?.blockers.find(blocker => ['PURCHASE_GROUP_EXISTS', 'PURCHASE_ORDER_EXISTS'].includes(blocker.code)))
const existingGroupLinks = computed(() => {
  const links = new Map<string, { id: string; label: string; blocker: PurchaseOrderSourceBlocker }>()
  for (const option of source.value?.bom_options || []) {
    const blocker = option.existing_purchase_group_id
      ? { code: 'PURCHASE_GROUP_EXISTS', message: '', existing_purchase_group_id: option.existing_purchase_group_id }
      : option.blockers?.find(item => item.existing_purchase_group_id || item.existing_purchase_order_id)
    if (!blocker) continue
    const id = blocker.existing_purchase_group_id || blocker.existing_purchase_order_id!
    if (!links.has(id)) links.set(id, { id, label: `进入已有采购需求 · ${option.product_color || option.product_name}`, blocker })
  }
  if (links.size || !existingSourceBlocker.value) return [...links.values()]
  return [{ id: 'existing', label: '进入已有采购需求', blocker: existingSourceBlocker.value }]
})
const sourceBlockerMessage = computed(() => [...new Set(source.value?.blockers.map(blocker => blocker.message))].join(' '))
const selectedBom = computed(() => source.value?.bom_options.find((item) => item.bom_id === selectedBomId.value) || null)
const selectedProduct = computed(() => selectedProducts.value.find((item) => item.id === selectedBom.value?.product_line_id) || null)
const selectedSupplierCount = computed(() => new Set(selectedLines.value.map((line) => line.supplier_id).filter(Boolean)).size)
const supplierBatchOptions = computed(() => {
  const counts = new Map<string, number>()
  for (const line of selectedLines.value) {
    if (line.supplier_id) counts.set(line.supplier_id, (counts.get(line.supplier_id) ?? 0) + 1)
  }
  return options.value.suppliers.filter(supplier => counts.has(supplier.id))
    .map(supplier => ({ id: supplier.id, name: supplier.supplier_name, count: counts.get(supplier.id)! }))
})
const reviewedPurchaseLines = computed(() => (supplierBatchReview.value?.lines ?? []).filter(hasPurchasePrice))
const reviewedPurchaseTotal = computed(() => formatScaled(
  reviewedPurchaseLines.value.reduce((total, line) => total + (pricedAmount(line) ?? 0n), 0n),
))
const supplierCategories = computed(() => [...new Set(lines.value.map((line) => line.category || '未分类'))])
const suppliersByCategory = computed(() => {
  const grouped = new Map<SupplierCategory, PurchaseOrderSupplierOption[]>()
  for (const supplier of options.value.suppliers) {
    for (const category of supplier.supplier_categories) {
      const suppliers = grouped.get(category)
      if (suppliers) suppliers.push(supplier)
      else grouped.set(category, [supplier])
    }
  }
  return grouped
})
const noMatchingSupplierText = '暂无匹配供应商，请在供应商信息中维护对应类别'
const bulkSupplierLines = computed(() => {
  if (!bulkSupplierCategory.value) return []
  return bulkSupplierCategory.value === '__all__'
    ? lines.value
    : lines.value.filter((line) => (line.category || '未分类') === bulkSupplierCategory.value)
})
const bulkSupplierOptions = computed(() => {
  if (bulkSupplierCategory.value === '__all__') return options.value.suppliers
  if (!bulkSupplierLines.value.length) return []
  return options.value.suppliers.filter((supplier) => bulkSupplierLines.value.every((line) =>
    line.suggested_supplier_category && supplier.supplier_categories.includes(line.suggested_supplier_category),
  ))
})
const bulkSupplierEmptyText = computed(() => bulkSupplierLines.value.some((line) => !line.suggested_supplier_category)
  ? '当前物料分类尚未对应供应商类别，请逐行选择供应商'
  : noMatchingSupplierText)
const completeLineCount = computed(() => selectedLines.value.filter(isLineComplete).length)
const isPreviewMode = computed(() => Boolean(source.value && !source.value.can_create && lines.value.length))
const detailTableHeight = computed(() => detailFullscreen.value ? 'calc(100dvh - 108px)'
  : isSampleSource.value && !lines.value.some(line => isPipePurchaseLine(line)) && lines.value.length <= 4 ? `${40 + lines.value.length * 40}px` : '100%')
const canContinueToDetails = computed(() => isPackaging.value ? selectedBomIds.value.length > 0 : Boolean(selectedTaskId.value && (isSampleSource.value
  ? source.value?.can_create && lines.value.length
  : selectedBom.value?.existing_purchase_group_id || selectedBomSources.value.length && selectedBomSources.value.every(item => item.source_revision))))

function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as {
    response?: {
      status?: number
      data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string }
    }
  })?.response
  const fields = response?.data?.error?.field_errors
  const taskNumber = fields?.production_task_number?.[0]
  const firstFieldError = fields
    ? Object.entries(fields).find(([field]) => field !== 'production_task_number')?.[1]?.[0]
    : ''
  if (response?.status === 401) return '登录状态已失效，请刷新页面或重新登录。'
  if (response?.status === 403) return '当前账号没有新建采购订单的权限。'
  if (response?.status === 412) return '采购需求已有更新，输入已保留。请重新读取采购需求版本后核对并重试。'
  if (response?.status === 409) return response.data?.error?.message || response.data?.detail || '采购来源已变化，请重新读取采购需求。'
  const message = firstFieldError || response?.data?.error?.message || response?.data?.detail || fallback
  return taskNumber ? `${taskNumber} · ${message}` : message
}

function showActionError(message: string): void {
  ElMessage.warning(message)
}

function resetSource(): void {
  source.value = null
  sourceLoading.value = false
  lines.value = []
  selectedBomIds.value = []
  bulkSupplierCategory.value = null
  bulkSupplierId.value = null
  bulkDeliveryDate.value = ''
  sourceError.value = ''
  preselectionError.value = ''
}

function applySource(result: PurchaseOrderSource, selectAvailable = false): void {
  source.value = result
  selectedBomIds.value = selectAvailable && result.requires_bom_selection
    ? result.bom_options.flatMap(option => selectableProduct(option) && option.bom_id ? [option.bom_id] : [])
    : result.selected_bom_id && (result.can_create || result.bom_options.some(item => item.bom_id === result.selected_bom_id && item.can_combine)) ? [result.selected_bom_id] : []
  bulkSupplierCategory.value = null
  bulkSupplierId.value = null
  bulkDeliveryDate.value = ''
  if (!form.currencyId && result.default_currency_id) form.currencyId = result.default_currency_id
  const sourceLines = result.can_create ? result.lines : result.preview_lines
  lines.value = (sourceLines || []).map((line) => ({
    ...line,
    supplier_id: null,
    delivery_date: '',
    actual_bar_count: String(line.suggested_bar_count ?? ''),
    actual_purchase_quantity: '',
    unit_price: '',
  }))
  sourceError.value = !result.can_create && !selectedBomIds.value.length
    ? result.requires_bom_selection ? '本单暂无可新建采购需求的产品。' : sourceBlockerMessage.value || '当前采购来源暂无可采购的明细。'
    : ''
}

async function loadOptions(): Promise<void> {
  if (!canAdd.value) {
    optionsLoading.value = false
    return
  }
  optionsLoading.value = true
  loadError.value = ''
  try {
    let result: PurchaseOrderOptions
    if (isPackaging.value) {
      if (!isBatchMode.value) {
        packagingSources.value = await fetchPackagingPurchaseSources()
        if (!packagingNoticeApplied && typeof route.query.production_task_id === 'string') {
          const matches = packagingSources.value.filter(item => item.production_task_id === route.query.production_task_id)
          if (matches.length <= 100) selectedBomIds.value = matches.map(item => item.bom_id)
          packagingNoticeApplied = true
        }
        return
      }
      result = await fetchPackagingPurchaseOptions()
    } else if (isDetailStep.value) {
      const [detailOptions, sourceOptionsResult] = await Promise.all([
        fetchPurchaseOrderOptions('detail'),
        fetchPurchaseOrderOptions('sources'),
      ])
      result = {
        ...detailOptions,
        production_tasks: sourceOptionsResult.production_tasks || [],
        sample_requests: sourceOptionsResult.sample_requests || [],
      }
    } else {
      result = await fetchPurchaseOrderOptions('sources')
    }
    options.value = {
      production_tasks: result.production_tasks || [],
      sample_requests: result.sample_requests || [],
      suppliers: result.suppliers || [],
      currencies: result.currencies || [],
      default_currency_id: result.default_currency_id || null,
      statuses: result.statuses || [],
      created_date_presets: result.created_date_presets || [],
    }
    if (!form.currencyId && result.default_currency_id) form.currencyId = result.default_currency_id
  } catch (error) {
    options.value = { production_tasks: [], suppliers: [], currencies: [], default_currency_id: null }
    loadError.value = apiErrorMessage(error, '采购订单选项加载失败，请稍后重试。')
  } finally {
    optionsLoading.value = false
  }
}

function handleSourceTypeFilterChange(): void {
  if (selectedTaskId.value && !visibleSourceOptions.value.some(item => item.id === selectedTaskId.value)) {
    sourceRequestId += 1
    selectedTaskId.value = ''
    resetSource()
  }
}

async function selectTask(task: PurchaseOrderProductionTaskOption): Promise<void> {
  const currentRequestId = ++sourceRequestId
  selectedTaskId.value = task.id
  resetSource()
  sourceLoading.value = true
  try {
    const result = task.source_type === 'SAMPLE'
      ? await fetchSamplePurchaseOrderSource(task.source_id || '')
      : await fetchPurchaseOrderSource(task.id)
    if (currentRequestId !== sourceRequestId) return
    applySource(result, true)
  } catch (error) {
    if (currentRequestId !== sourceRequestId) return
    const message = apiErrorMessage(error, '采购来源读取失败，请稍后重试。')
    sourceError.value = message
    showActionError(message)
  } finally {
    if (currentRequestId === sourceRequestId) sourceLoading.value = false
  }
}

function selectableProduct(option?: PurchaseOrderBomOption): boolean {
  return Boolean(option?.can_combine || (option?.can_create && !option.existing_purchase_group_id))
}

function handleProductSelection(option?: PurchaseOrderBomOption): void {
  if (sourceLoading.value || saving.value || !option?.bom_id || !selectableProduct(option)) return
  if (selectedBomIds.value.includes(option.bom_id)) selectedBomIds.value = selectedBomIds.value.filter(id => id !== option.bom_id)
  else selectedBomIds.value = [...selectedBomIds.value, option.bom_id]
  sourceError.value = ''
}

async function handleTaskSelection(taskId: string): Promise<void> {
  if (!taskId) {
    sourceRequestId += 1
    resetSource()
    return
  }
  const task = sourceOptions.value.find((item) => item.id === taskId)
  if (!task) {
    selectedTaskId.value = ''
    resetSource()
    return
  }
  await selectTask(task)
}

async function refreshOptions(): Promise<void> {
  const previousTaskId = selectedTaskId.value
  await loadOptions()
  if (!previousTaskId || selectedTaskId.value !== previousTaskId) return
  const task = sourceOptions.value.find((item) => item.id === previousTaskId)
  if (task) await selectTask(task)
  else {
    selectedTaskId.value = ''
    resetSource()
  }
}

function materialTitle(line: PurchaseLineDraft): string {
  return line.part_name || line.material || line.raw_material || '未命名物料'
}

function purchaseLineKey(line: PurchaseLineDraft): string {
  return line.sample_line_key || line.bom_line_id || String(line.line_number)
}

function handleLineMouseEnter(line: PurchaseLineDraft): void {
  hoveredLineKey.value = purchaseLineKey(line)
}

function handleLineMouseLeave(): void {
  hoveredLineKey.value = ''
}

/**
 * 样品管材来源保留米需求；新采购按手填的单根参数预算 KG，旧米单保留原输入。
 */
function isPipePurchaseLine(line: PurchaseLineDraft): boolean {
  return isSampleSource.value && line.section_type === 'PROFILE'
}

function isWeightPipeLine(line: Pick<PurchaseLineDraft, 'section_type' | 'raw_bar_length_m' | 'source_unit_text' | 'suggested_purchase_weight_kg'>): boolean {
  return line.section_type === 'PROFILE' && (String(line.source_unit_text || '').toUpperCase() === 'KG' || Boolean(line.suggested_purchase_weight_kg))
}

function isWeightLine(line: PurchaseLineDraft): boolean {
  return isWeightPipeLine(line) || isHardwareWeightLine(line)
}

function weightSuggestedQuantity(line: PurchaseLineDraft): string {
  if (isPipePurchaseLine(line) && line.calculation_snapshot?.schema_version === 4) {
    return samplePipeSuggestedWeight(line.calculation_snapshot.shortage_meters, line.raw_bar_length_m, line.raw_bar_weight_kg)
  }
  return line.suggested_purchase_weight_kg || (isWeightLine(line) ? line.required_quantity || line.source_quantity_text : '') || '—'
}

function pipeActualWeight(line: PurchaseLineDraft): string {
  return line.actual_purchase_quantity.trim()
}
function purchasePriceUnit(line: PurchaseLineDraft): string {
  return isWeightLine(line) ? '元/kg' : isPipePurchaseLine(line) || line.raw_bar_length_m ? '元/米' : line.source_unit_text ? `元/${line.source_unit_text}` : '元'
}
const pipePricingText = computed(() => [
  lines.value.some(isWeightLine) ? '重量物料金额＝采购重量 × 元/kg 单价' : '',
  lines.value.some(line => !isWeightLine(line) && (isPipePurchaseLine(line) || line.raw_bar_length_m)) ? '米制管材金额＝采购米数 × 元/米 单价' : '',
  '其他物料按采购数量计价',
].filter(Boolean).join('；'))

function productColorText(product: PurchaseOrderProductSource): string {
  return [product.color_card, product.color_name, product.color_code]
    .map((value) => value.trim())
    .filter((value) => value && value !== '/')
    .join(' · ') || '—'
}

function sourceQuantityText(task: PurchaseOrderProductionTaskOption): string {
  if (task.source_type === 'SAMPLE') return `${task.demand_count || 0} 项采购需求`
  const remaining = task.remaining_product_count ?? task.product_count
  if (!task.combinable_product_count) return `${remaining} 项待采购产品`
  return [remaining ? `${remaining} 项待采购` : '', `${task.combinable_product_count} 项已有需求可合并`].filter(Boolean).join(' · ')
}

function disablePastDeliveryDate(date: Date): boolean {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return date.getTime() < today.getTime()
}

function applyBulkSupplier(value: string | null): void {
  if (!canWriteLines.value || sourceLoading.value) return
  if (value && !bulkSupplierOptions.value.some((supplier) => supplier.id === value)) {
    refreshBulkSupplier()
    showActionError('该供应商不属于当前分类，请重新选择。')
    return
  }
  for (const line of bulkSupplierLines.value) {
    line.supplier_id = value || null
    syncSetTerm(lines.value, line, 'supplier_id')
  }
}

function onLineSupplierChange(line: PurchaseLineDraft) {
  syncSetTerm(lines.value, line, 'supplier_id')
  refreshBulkSupplier()
}

function lineSupplierOptions(line: PurchaseLineDraft): PurchaseOrderSupplierOption[] {
  const category = line.suggested_supplier_category
  return category ? suppliersByCategory.value.get(category) ?? [] : options.value.suppliers
}

function onLineDeliveryChange(line: PurchaseLineDraft) {
  syncSetTerm(lines.value, line, 'delivery_date')
  refreshBulkDeliveryDate()
}

function refreshBulkSupplier(): void {
  if (!bulkSupplierLines.value.length) {
    bulkSupplierId.value = null
    return
  }
  const firstValue = bulkSupplierLines.value[0].supplier_id
  bulkSupplierId.value = bulkSupplierLines.value.every((line) => line.supplier_id === firstValue)
    ? firstValue
    : null
}

function applyBulkDeliveryDate(value: string | null): void {
  if (!canWriteLines.value || sourceLoading.value) return
  const normalizedValue = value || ''
  for (const line of lines.value) line.delivery_date = normalizedValue
}

function refreshBulkDeliveryDate(): void {
  if (!lines.value.length) {
    bulkDeliveryDate.value = ''
    return
  }
  const firstValue = lines.value[0].delivery_date
  bulkDeliveryDate.value = lines.value.every((line) => line.delivery_date === firstValue)
    ? firstValue
    : ''
}

const supplierClipboardType = 'application/x-haiqu-supplier-id'

function copyGridTerm(event: ClipboardEvent, line: PurchaseLineDraft, field: 'supplier_id' | 'delivery_date'): void {
  const data = event.clipboardData
  if (!data) return
  let text = line.delivery_date
  if (field === 'supplier_id') {
    const supplier = options.value.suppliers.find(item => item.id === line.supplier_id)
    if (!supplier) return
    text = supplier.supplier_name
    data.setData(supplierClipboardType, supplier.id)
  }
  if (!text) return
  data.setData('text/plain', text)
  event.preventDefault()
}

function pasteGridTerm(event: ClipboardEvent, line: PurchaseLineDraft, field: 'supplier_id' | 'delivery_date'): void {
  const data = event.clipboardData
  const input = event.target
  if (!data || !(input instanceof HTMLInputElement)) return
  if (!canWriteLines.value || saving.value || sourceLoading.value || input.disabled) {
    event.preventDefault()
    return
  }
  const text = data.getData('text/plain').trim()
  let value = text
  if (field === 'supplier_id') {
    const id = data.getData(supplierClipboardType)
    const matches = options.value.suppliers.filter(item => id ? item.id === id : item.supplier_name === text)
    if (matches.length !== 1) return // 交给下拉框搜索，采购员可以继续选。
    value = matches[0]!.id
  } else {
    const date = new Date(text + 'T00:00:00')
    if (!/^\d{4}-\d{2}-\d{2}$/.test(text) || date.getDate() !== Number(text.slice(-2)) || disablePastDeliveryDate(date)) {
      event.preventDefault()
      showActionError('请输入今天或以后的交期，日期格式为 YYYY-MM-DD。')
      return
    }
  }
  event.preventDefault()
  // 收起下拉面板并结束此前的搜索或日期输入，下一次回车就能按表格规则向下填。
  if (document.activeElement === input) input.blur()
  if (field === 'supplier_id') {
    line.supplier_id = value
    onLineSupplierChange(line)
  } else {
    line.delivery_date = value
    onLineDeliveryChange(line)
  }
  input.focus({ preventScroll: true })
}

function fillNextGridRow(rowIndex: number, columnIndex: number): void {
  if (!canWriteLines.value || sourceLoading.value || saving.value || rowIndex < 0 || rowIndex >= lines.value.length - 1) return
  if (columnIndex === 0) {
    const value = lines.value[rowIndex]?.supplier_id
    if (!value) return
    lines.value[rowIndex + 1]!.supplier_id = value
    onLineSupplierChange(lines.value[rowIndex + 1]!)
  } else if (columnIndex === 1) {
    const value = lines.value[rowIndex]?.delivery_date
    if (!value) return
    lines.value[rowIndex + 1]!.delivery_date = value
    onLineDeliveryChange(lines.value[rowIndex + 1]!)
  }
}

async function focusGridField(rowIndex: number, columnIndex: number): Promise<void> {
  if (rowIndex < 0 || rowIndex >= lines.value.length || columnIndex < 0 || columnIndex > 3) return
  await nextTick()
  const field = formPage.value?.querySelector<HTMLElement>(
    `[data-grid-row="${rowIndex}"][data-grid-column="${columnIndex}"]`,
  )
  const input = field?.querySelector<HTMLInputElement | HTMLButtonElement>('input:not([disabled]), button[data-pipe-quantity-trigger]:not([disabled])')
  if (!field || !input) return
  field.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  input.focus({ preventScroll: true })
  if (input instanceof HTMLInputElement && !input.readOnly) input.select()
}

function handleGridNavigation(event: KeyboardEvent, rowIndex: number, columnIndex: number): void {
  if (event.isComposing || event.keyCode === 229 || event.altKey || event.ctrlKey || event.metaKey) return
  const input = event.target instanceof HTMLInputElement ? event.target : null
  const pipeTrigger = event.target instanceof HTMLButtonElement && event.target.hasAttribute('data-pipe-quantity-trigger') ? event.target : null
  if ((!input && !pipeTrigger) || input?.disabled || pipeTrigger?.disabled) return
  if (pipeTrigger && event.key === 'Enter') return
  const popupExpanded = Boolean(
    (input || pipeTrigger)?.closest('[data-grid-field]')?.querySelector('[aria-expanded="true"]'),
  )
  if (popupExpanded && !(columnIndex === 1 && ['ArrowDown', 'ArrowUp'].includes(event.key))) return

  let targetRow = rowIndex
  let targetColumn = columnIndex
  if (event.key === 'Enter') {
    if (!event.shiftKey && (columnIndex === 0 || columnIndex === 1)) {
      fillNextGridRow(rowIndex, columnIndex)
      // 末行也消费回车，避免重新展开选择框或触发表单默认动作。
      event.preventDefault()
      event.stopPropagation()
    }
    targetRow += event.shiftKey ? -1 : 1
  } else if (event.key === 'ArrowDown') {
    targetRow += 1
  } else if (event.key === 'ArrowUp') {
    targetRow -= 1
  } else if (event.key === 'ArrowLeft') {
    if (input && input.selectionStart !== null && input.selectionStart > 0) return
    targetColumn -= 1
  } else if (event.key === 'ArrowRight') {
    if (input && input.selectionEnd !== null && input.selectionEnd < input.value.length) return
    targetColumn += 1
  } else {
    return
  }

  if (targetRow < 0 || targetRow >= lines.value.length || targetColumn < 0 || targetColumn > 3) return
  event.preventDefault()
  event.stopPropagation()
  void focusGridField(targetRow, targetColumn)
}

function formatSuggestedQuantity(value: string | null | undefined): string {
  const text = (value || '').trim()
  if (!text) return '—'
  return /^\d+\.0+$/.test(text) ? text.replace(/\.0+$/, '') : text
}

function defaultPurchaseQuantity(line: PurchaseLineDraft): string {
  if (isWeightLine(line)) return weightSuggestedQuantity(line) || ''
  if (line.quantity_parse_status !== 'READY' || !line.required_quantity) return ''
  const quantity = formatSuggestedQuantity(line.required_quantity)
  return isPositiveDecimal(quantity) ? quantity : ''
}

function effectivePurchaseQuantity(line: PurchaseLineDraft): string {
  if (isWeightLine(line)) return pipeActualWeight(line)
  if (isPipePurchaseLine(line) || line.raw_bar_length_m) return line.actual_purchase_quantity.trim() || pipeMeters(line.actual_bar_count, line.raw_bar_length_m || '')
  return line.actual_purchase_quantity.trim() || (isBatchMode.value ? '' : defaultPurchaseQuantity(line))
}

function pipeQuantitySummary(line: PurchaseLineDraft): string {
  const meters = effectivePurchaseQuantity(line)
  return meters ? `${formatSuggestedQuantity(meters)}米` : '米'
}

function setPipePurchaseMeters(line: PurchaseLineDraft, value: string): void {
  line.actual_purchase_quantity = value
  line.actual_bar_count = pipeRootsFromMeters(value.trim(), line.raw_bar_length_m)
}

function setPipeLength(line: PurchaseLineDraft, value: string): void {
  const meters = effectivePurchaseQuantity(line)
  line.raw_bar_length_m = value
  setPipePurchaseMeters(line, meters)
}

function pipeMeterError(line: PurchaseLineDraft, allowZero = false): string {
  const meters = effectivePurchaseQuantity(line)
  if (!(allowZero ? isNonNegativeDecimal(meters) : isPositiveDecimal(meters))) return '实际采购米数应为大于 0、最多 4 位小数的数字。'
  if (!pipeRootsFromMeters(meters, line.raw_bar_length_m)) return '实际采购米数必须为每根长度的整数倍，请核对数量。'
  return ''
}

function focusPipeQuantity(lineKey: string): void {
  const editor = Array.from(document.querySelectorAll<HTMLElement>('[data-pipe-editor]'))
    .find(element => element.dataset.pipeEditor === lineKey)
  editor?.querySelector<HTMLInputElement>('input')?.focus()
}

function remainingPurchaseQuantity(target: string | number | null | undefined, purchased: string | null | undefined, roots = false): string | null {
  const targetText = typeof target === 'number' && roots && Number.isSafeInteger(target) ? String(target) : target
  if (typeof targetText !== 'string' || typeof purchased !== 'string') return null
  const left = decimalParts(targetText)
  const right = decimalParts(purchased)
  if (!left || !right || (roots && (left.scale !== 0 || right.scale !== 0))) return null
  const scale = Math.max(left.scale, right.scale)
  const remaining = left.digits * 10n ** BigInt(scale - left.scale) - right.digits * 10n ** BigInt(scale - right.scale)
  if (remaining <= 0n) return '0'
  const digits = remaining.toString().padStart(scale + 1, '0')
  return scale ? compactDecimal(`${digits.slice(0, -scale)}.${digits.slice(-scale)}`) : digits
}

function remainingForBatch(line: PurchaseGroupProgressLine, target: string | null | undefined): string | null {
  if (line.remaining_purchase_quantity === undefined) return remainingPurchaseQuantity(target, line.purchased_quantity)
  return line.remaining_purchase_quantity === null ? null : compactDecimal(line.remaining_purchase_quantity)
}

function lineAmount(line: PurchaseLineDraft): string {
  if (isBatchMode.value && !line.set_pricing && (isExplicitZeroPrice(line.unit_price)
    || isExplicitZeroPrice(effectivePurchaseQuantity(line)))) return '本批不买'
  if (line.set_pricing && line.set_pricing.anchor_id !== line.purchase_group_line_id) return '—'
  const amount = pricedAmount(line)
  return amount === null ? '—' : formatScaled(amount)
}

function pricedAmount(line: PurchaseLineDraft) {
  const set = line.set_pricing
  if (set) return set.anchor_id === line.purchase_group_line_id ? scaledProduct(String(set.quantity), set.unit_price) : 0n
  return scaledProduct(effectivePurchaseQuantity(line), line.unit_price)
}

const totalAmount = computed(() => {
  const amounts = selectedLines.value.map(pricedAmount)
  if (!amounts.length || amounts.some((amount) => amount === null)) return '待计算'
  let total = 0n
  for (const amount of amounts) {
    if (amount !== null) total += amount
  }
  return formatScaled(total)
})

function isPositiveDecimal(value: string): boolean {
  return /^\d+(?:\.\d{1,4})?$/.test(value.trim()) && Number(value) > 0
}

function hasPurchasePrice(line: PurchaseLineDraft): boolean {
  return Boolean(line.set_pricing || isPositiveDecimal(line.unit_price))
}

function isNonNegativeDecimal(value: string): boolean {
  return /^\d+(?:\.\d{1,4})?$/.test(value.trim()) && Number(value) >= 0
}

function isLineComplete(line: PurchaseLineDraft): boolean {
  return Boolean(
    line.supplier_id
    && line.delivery_date
    && isPositiveDecimal(effectivePurchaseQuantity(line))
    && (!isPipePurchaseLine(line) || !isWeightPipeLine(line) || Boolean(samplePipeSuggestedWeight(line.calculation_snapshot?.shortage_meters, line.raw_bar_length_m, line.raw_bar_weight_kg)))
    && (line.set_pricing || isNonNegativeDecimal(line.unit_price)),
  )
}

function validateDraft(selection = selectedLines.value, reviewLines?: PurchaseLineDraft[], allowEmpty = false): string {
  if (isBatchMode.value) {
    if (!canWriteLines.value || !groupEtag.value) return '采购需求不可用或版本信息缺失，请重新读取。'
    // 空白和零表示本批不采购；有输入但格式错误必须提示，不能过滤后漏单。
    for (const [index, line] of (reviewLines ?? lines.value).entries()) {
      const quantity = (isWeightLine(line) || !line.raw_bar_length_m ? line.actual_purchase_quantity : effectivePurchaseQuantity(line)).trim()
      if (reviewLines) {
        if (!line.set_pricing && (!quantity || isExplicitZeroPrice(quantity)
          || !line.unit_price.trim() || isExplicitZeroPrice(line.unit_price))) continue
        if (!line.set_pricing && !isPositiveDecimal(line.unit_price)) return `第 ${index + 1} 行采购单价应为大于 0、最多 4 位小数的数字。`
      }
      if (line.set_pricing && !isPositiveDecimal(quantity)) return `第 ${index + 1} 行属于套餐，请填写采购数量或从套餐中移除。`
      if (!quantity) continue
      if (!isNonNegativeDecimal(quantity)) {
        return isWeightLine(line) ? `第 ${index + 1} 行采购重量应为大于或等于 0、最多 4 位小数的数字。`
          : `第 ${index + 1} 行实际采购数量应为大于或等于 0、最多 4 位小数的数字。`
      }
      if (!isWeightLine(line) && line.raw_bar_length_m) {
        const error = pipeMeterError(line, true)
        if (error) return `第 ${index + 1} 行：${error}`
      }
    }
    if (!selection.length && !allowEmpty) return reviewLines
      ? '本批暂无采购材料。普通材料的采购数量和单价都大于 0 才计入本批。'
      : '本批没有需要采购的材料。请填写采购数量，明确填 0 的单价会跳过本行。'
  } else {
  if (!selectedTaskId.value) return '请先选择采购来源。'
  if (!isSampleSource.value && !selectedBomId.value) return '请选择本次要采购的产品 BOM。'
  if (!source.value?.can_create) {
    if (source.value?.existing_purchase_order_number) {
      return `该采购来源已存在采购单 ${source.value.existing_purchase_order_number}，不能重复创建。`
    }
    return sourceBlockerMessage.value || '所选 BOM 尚未校验、明细为空或已失效，暂不能保存采购草稿。'
  }
  }
  if (!lines.value.length && !allowEmpty) return '当前生产订单没有可保存的采购明细。'
  for (const [index, line] of selection.entries()) {
    if (isBatchMode.value && !isPositiveDecimal(effectivePurchaseQuantity(line))) return `第 ${index + 1} 项实际采购数量应大于 0。`
    if (isWeightLine(line)) {
      const samplePipe = isPipePurchaseLine(line) && isWeightPipeLine(line)
      if ((!samplePipe || pipeActualWeight(line)) && !isPositiveDecimal(pipeActualWeight(line))) return `第 ${index + 1} 行实际采购重量应为大于 0、最多 4 位小数的数字。`
      if (isWeightPipeLine(line) && (!samplePipe || line.raw_bar_weight_kg) && !isPositiveDecimal(line.raw_bar_weight_kg || '')) return `第 ${index + 1} 行请填写大于 0、最多 4 位小数的每根标准重量。`
      if (samplePipe && line.raw_bar_length_m && (!/^\d{1,14}(?:\.\d{1,3})?$/.test(line.raw_bar_length_m) || Number(line.raw_bar_length_m) <= 0)) return `第 ${index + 1} 行每根长度应大于 0，最多三位小数。`
    } else if (isPipePurchaseLine(line)) {
      if (!isPositiveDecimal(line.raw_bar_length_m || '')) return `第 ${index + 1} 行：请填写大于 0 的每根长度（米）。`
      const error = pipeMeterError(line)
      if (error) return `第 ${index + 1} 行：${error}`
    } else if (line.raw_bar_length_m) {
      const error = pipeMeterError(line)
      if (error) return `第 ${index + 1} 行：${error}`
    }
    if (line.actual_purchase_quantity && !isPositiveDecimal(line.actual_purchase_quantity)) {
      return `第 ${index + 1} 行实际采购数量应为大于 0、最多 4 位小数的数字。`
    }
    if (!line.set_pricing && line.unit_price && !isNonNegativeDecimal(line.unit_price)) {
      return `第 ${index + 1} 行采购单价应为大于或等于 0、最多 4 位小数的数字。`
    }
  }
  return ''
}

function validateConfirmation(selection = confirmationLines.value, reviewLines = isBatchMode.value ? lines.value : undefined, allowEmpty = false): string {
  const draftError = validateDraft(selection, reviewLines, allowEmpty)
  if (draftError) return draftError
  const selectedCurrency = options.value.currencies.find((item) => item.id === form.currencyId)
  if (!selectedCurrency || selectedCurrency.code !== 'CNY') return '系统未找到人民币（CNY）采购币种，请联系管理员检查基础资料。'
  for (const [index, line] of selection.entries()) {
    const missing: string[] = []
    if (!line.supplier_id) missing.push('供应商')
    if (!line.delivery_date) missing.push('采购交期')
    if (!isPositiveDecimal(effectivePurchaseQuantity(line))) missing.push(isWeightLine(line) ? '实际采购重量' : '实际采购数量')
    if (isPipePurchaseLine(line) && isWeightPipeLine(line)) {
      if (!isPositiveDecimal(line.raw_bar_weight_kg || '')) missing.push('每根标准重量')
      if (!line.raw_bar_length_m) missing.push('每根长度')
    }
    if (!line.set_pricing && !isNonNegativeDecimal(line.unit_price)) missing.push('采购单价')
    if (!line.source_unit_text) missing.push('单位')
    if (missing.length) return `第 ${(reviewLines?.indexOf(line) ?? index) + 1} 行缺少或填写错误：${missing.join('、')}。`
  }
  return ''
}

function buildPayload(): PurchaseOrderInput {
  return {
    source_type: isSampleSource.value ? 'SAMPLE' : 'PRODUCTION',
    ...(isSampleSource.value
      ? { sample_procurement_request_id: selectedTask.value?.source_id }
      : { production_task_id: selectedTaskId.value, bom_id: selectedBomId.value }),
    source_revision: source.value?.source_revision || '',
    currency_id: form.currencyId || null,
    lines: lines.value.map((line) => ({
      ...(isSampleSource.value ? { sample_line_key: line.sample_line_key } : { bom_line_id: line.bom_line_id }),
      supplier_id: line.supplier_id || null,
      delivery_date: line.delivery_date || null,
      actual_purchase_quantity: isWeightLine(line) ? effectivePurchaseQuantity(line) || null : (isPipePurchaseLine(line) || line.raw_bar_length_m ? null : effectivePurchaseQuantity(line) || null),
      ...(isWeightLine(line) ? { ...(!isSampleSource.value ? { actual_purchase_weight_kg: effectivePurchaseQuantity(line) } : {}), ...(isWeightPipeLine(line) ? { raw_bar_weight_kg: line.raw_bar_weight_kg || null } : {}) } : {}),
      ...(!isWeightLine(line) && (isPipePurchaseLine(line) || line.raw_bar_length_m) ? { actual_bar_count: line.actual_bar_count } : {}),
      ...(isPipePurchaseLine(line) ? { raw_bar_length_m: line.raw_bar_length_m || null } : {}),
      unit_price: line.unit_price.trim() || null,
    })),
  }
}

function batchContent(selection: PurchaseLineDraft[]): Omit<PurchaseBatchInput, 'request_id'> {
  return {
    ...(batchSessionId.value ? { batch_session_id: batchSessionId.value } : {}),
    batch_type: batchType.value,
    currency_id: form.currencyId,
    lines: selection.map(line => ({
      purchase_group_line_id: line.purchase_group_line_id!,
      supplier_id: line.supplier_id || null,
      delivery_date: line.delivery_date || null,
      ...(isWeightLine(line) ? { actual_purchase_quantity: effectivePurchaseQuantity(line), actual_purchase_weight_kg: effectivePurchaseQuantity(line), ...(isWeightPipeLine(line) ? { raw_bar_weight_kg: line.raw_bar_weight_kg || null } : {}) } : line.raw_bar_length_m ? { actual_bar_count: line.actual_bar_count } : { actual_purchase_quantity: effectivePurchaseQuantity(line) }),
      unit_price: line.set_pricing ? null : line.unit_price.trim() || null,
      ...(line.set_pricing ? { set_pricing: line.set_pricing } : {}),
    })),
  }
}

async function createOrder(nextStep: 'list' | 'confirm'): Promise<void> {
  if (saving.value || pendingSupplierBatch.value) return
  const selection = nextStep === 'confirm' ? confirmationLines.value : selectedLines.value
  const validationMessage = nextStep === 'confirm' ? validateConfirmation(selection) : validateDraft(selection)
  if (validationMessage) {
    showActionError(validationMessage)
    return
  }
  saving.value = true
  try {
    let batchInput: PurchaseBatchInput | null = null
    if (isBatchMode.value) {
      const content = batchContent(selection)
      const signature = JSON.stringify(content)
      if (!batchRequestId.value || signature !== batchContentSignature) batchRequestId.value = createClientUuid()
      batchContentSignature = signature
      batchInput = { ...content, request_id: batchRequestId.value }
    }
    const result = batchInput && group.value
      ? await createPurchaseBatch(group.value.id, batchInput, groupEtag.value)
      : await createPurchaseOrder(buildPayload())
    if (nextStep === 'confirm') {
      ElMessage.success('采购订单已保存，请核对后确认。')
      await router.push({ name: 'purchase-order-confirm', params: { id: result.data.id } })
    } else {
      ElMessage.success('采购订单草稿已创建。')
      await router.push(isBatchMode.value && group.value ? { name: 'purchase-group-detail', params: { id: group.value.id } } : { name: 'purchase-orders', query: { view: 'orders' } })
    }
  } catch (error) {
    const message = apiErrorMessage(error, '采购订单草稿保存失败，请稍后重试。')
    if (isBatchMode.value) {
      const status = (error as { response?: { status?: number } })?.response?.status
      batchConflict.value = status ? message : '提交结果尚未确认，输入已保留。可重试相同内容；修改内容前请返回采购需求核对是否已创建批次。'
    }
    ElMessage.error(message)
  } finally {
    saving.value = false
  }
}

function openSupplierBatchReview(supplierId: string): void {
  const supplier = supplierBatchOptions.value.find(item => item.id === supplierId)
  if (!canSubmitSupplierBatch.value || !canWriteLines.value || !supplier || !group.value || sourceLoading.value) return
  supplierBatchReview.value = {
    groupId: group.value.id,
    groupEtag: groupEtag.value,
    supplierName: supplier.name,
    lines: selectedLines.value.filter(line => line.supplier_id === supplierId).map(line => ({ ...line })),
    error: '',
  }
}

function updateSupplierReviewDate(row: PurchaseLineDraft, date: string | null): void {
  const review = supplierBatchReview.value
  if (!review) return
  row.delivery_date = date ?? ''
  syncSetTerm(review.lines, row, 'delivery_date')
  review.error = ''
}

async function confirmSupplierBatch(): Promise<void> {
  const review = supplierBatchReview.value
  if (!review) return
  if (!canSubmitSupplierBatch.value || !canWriteLines.value || sourceLoading.value
    || group.value?.id !== review.groupId || groupEtag.value !== review.groupEtag) {
    review.error = '采购需求已变化，请关闭弹窗后重新打开。'
    return
  }
  const selection = reviewedPurchaseLines.value
  const error = validateConfirmation(selection, review.lines)
  if (error) {
    review.error = error
    return
  }
  const payload = { ...batchContent(selection), request_id: createClientUuid(), save_as_draft: true }
  const edited = new Map(review.lines.map(line => [line.purchase_group_line_id, line]))
  for (const line of lines.value) {
    const draft = edited.get(line.purchase_group_line_id)
    if (draft) {
      line.unit_price = draft.unit_price
      line.delivery_date = draft.delivery_date
    }
  }
  refreshBulkDeliveryDate()
  pendingSupplierBatch.value = { groupId: review.groupId, groupEtag: review.groupEtag, supplierName: review.supplierName, payload }
  supplierBatchReview.value = null
  await submitPendingSupplierBatch()
}

function hasNoRemainingPurchase(source: PurchaseGroupProgressLine): boolean {
  return compactDecimal(source.remaining_purchase_quantity, '') === '0'
}

async function submitPendingSupplierBatch(): Promise<void> {
  const submission = pendingSupplierBatch.value
  if (!submission || saving.value) return
  saving.value = true
  try {
    const result = isPackaging.value
      ? await writePackagingPurchasePage('save', packagingGroupIds.value, batchSessionId.value!, submission.groupEtag, submission.payload)
        .then(page => {
          const display = packagingDisplayGroup(page.groups)
          return { etag: page.etag, group: display, batchNumber: display.batch_page!.current_batch_number! }
        })
      : await submitPurchaseSupplierBatch(submission.groupId, submission.payload, submission.groupEtag)
        .then(({ data, etag }) => ({ etag, group: data.group, batchNumber: data.batch_number }))
    if (pendingSupplierBatch.value !== submission) return
    group.value = result.group
    groupEtag.value = result.etag
    currentBatchNumber.value = result.batchNumber
    const submitted = new Set(submission.payload.lines.map(line => line.purchase_group_line_id))
    const remaining = new Map(result.group.progress.lines.map(line => [line.id, line]))
    lines.value = lines.value.flatMap(line => {
      const id = line.purchase_group_line_id!
      if (!submitted.has(id)) return [line]
      const source = remaining.get(id)
      if (source && hasNoRemainingPurchase(source)) {
        fulfilledSupplierLineIds.add(id)
        return []
      }
      const draft = source ? groupDraft(source) : { ...line, actual_purchase_quantity: '', actual_bar_count: '' }
      return [{ ...draft, supplier_id: line.supplier_id, delivery_date: line.delivery_date, unit_price: '', set_pricing: null }]
    })
    refreshBulkSupplier()
    refreshBulkDeliveryDate()
    lastSupplierBatch.value = {
      number: result.batchNumber, supplierName: submission.supplierName, lineCount: submitted.size,
    }
    pendingSupplierBatch.value = null
    batchConflict.value = ''
  } catch (error) {
    if (pendingSupplierBatch.value !== submission) return
    const status = (error as { response?: { status?: number } })?.response?.status
    if (!status || status >= 500) {
      batchConflict.value = '保存结果尚未确认，输入已保留。请重试本次保存。'
    } else {
      pendingSupplierBatch.value = null
      batchConflict.value = apiErrorMessage(error, '采购保存失败，请核对后重试。')
    }
  } finally {
    saving.value = false
  }
}

function saveDraft(): void {
  void createOrder('list')
}

function confirmPurchase(): void {
  const currentGroup = group.value
  const sessionId = batchSessionId.value
  if (isPackaging.value && (!currentGroup || !sessionId || (!savedSupplierOrders.value.length && !confirmationLines.value.length))) {
    if (packagingPageConfirmed.value && sessionId) {
      void router.push({ name: 'supplier-purchase-sheets', query: { purchase_scope: 'PACKAGING', batch_session_id: sessionId } })
    } else {
      showActionError('请至少填写一行采购数量和单价均大于 0 的包材。')
    }
    return
  }
  if (!currentGroup || !sessionId || (!isPackaging.value && !savedSupplierOrders.value.length)) {
    if (currentGroup && currentBatchNumber.value !== null && !confirmationLines.value.length && canReadSupplierSheets.value
      && currentGroup.batches.some(batch => batch.batch_number === currentBatchNumber.value && batch.status !== 'DRAFT')) {
      void router.push({ name: 'supplier-purchase-sheets', query: { purchase_group_id: currentGroup.id } })
      return
    }
    void createOrder('confirm')
    return
  }
  if (!canWriteLines.value || !groupEtag.value || !canSubmitSupplierBatch.value || sourceLoading.value) return
  const selection = confirmationLines.value
  const error = validateConfirmation(selection, lines.value, true)
  if (error) {
    showActionError(error)
    return
  }
  const additional = selection.length ? { ...batchContent(selection), request_id: createClientUuid() } : undefined
  const supplierIds = new Set(selection.map(line => line.supplier_id))
  finalBatchReview.value = {
    groupId: currentGroup.id,
    etag: groupEtag.value,
    payload: {
      batch_session_id: sessionId,
      ...(additional ? { additional } : {}),
    },
    additionalSummary: additional ? {
      suppliers: options.value.suppliers.filter(supplier => supplierIds.has(supplier.id)).map(supplier => supplier.supplier_name).join('、'),
      amount: formatScaled(selection.reduce((total, line) => total + (pricedAmount(line) ?? 0n), 0n)),
    } : null,
    error: '',
    uncertain: false,
  }
}

async function confirmSavedSupplierOrders(): Promise<void> {
  const review = finalBatchReview.value
  if (!review || saving.value) return
  saving.value = true
  try {
    const result = isPackaging.value
      ? await writePackagingPurchasePage('confirm', packagingGroupIds.value, review.payload.batch_session_id, review.etag, review.payload.additional)
        .then(page => ({ etag: page.etag, data: packagingDisplayGroup(page.groups) }))
      : await confirmPurchaseBatchPage(review.groupId, review.payload, review.etag)
    if (finalBatchReview.value !== review) return
    group.value = result.data
    groupEtag.value = result.etag
    finalBatchReview.value = null
    lastSupplierBatch.value = null
    ElMessage.success('本批采购已确认。')
    if (isPackaging.value) await router.push({ name: 'supplier-purchase-sheets', query: { purchase_scope: 'PACKAGING', batch_session_id: review.payload.batch_session_id } })
    else if (canReadSupplierSheets.value) await router.push({ name: 'supplier-purchase-sheets', query: { purchase_group_id: review.groupId } })
    else await router.push({ name: 'purchase-group-detail', params: { id: review.groupId } })
  } catch (error) {
    if (finalBatchReview.value === review) {
      const status = (error as { response?: { status?: number } })?.response?.status
      review.uncertain = !status || status >= 500
      review.error = review.uncertain ? '确认结果尚未收到，请重试本次确认。' : apiErrorMessage(error, '本批采购确认失败，请核对后重试。')
      if (status === 412) batchConflict.value = review.error
    }
  } finally {
    saving.value = false
  }
}

function queryValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

async function restoreDetailSource(): Promise<void> {
  const sourceType = queryValue(route.query.source_type)
  const sourceId = queryValue(route.query.source_id)
  const bomId = queryValue(route.query.bom_id)
  if (!sourceId || !['PRODUCTION', 'SAMPLE'].includes(sourceType)) {
    showActionError('采购来源信息不完整，请返回重新选择订单和产品。')
    return
  }
  const optionId = sourceType === 'SAMPLE' ? `sample:${sourceId}` : sourceId
  selectedTaskId.value = optionId
  sourceLoading.value = true
  try {
    const result = sourceType === 'SAMPLE'
      ? await fetchSamplePurchaseOrderSource(sourceId)
      : await fetchPurchaseOrderSource(sourceId, bomId || undefined)
    applySource(result)
    if (!result.can_create || !lines.value.length) {
      showActionError(sourceBlockerMessage.value || '当前来源没有可填写的采购明细。')
    }
  } catch (error) {
    showActionError(apiErrorMessage(error, '所选采购来源已不存在或已发生变化，请返回重新选择。'))
  } finally {
    sourceLoading.value = false
  }
}

async function restoreTrackingSource(): Promise<void> {
  const taskId = queryValue(route.query.production_task_id)
  const bomId = queryValue(route.query.bom_id)
  if (!taskId && !bomId) return
  const requestId = ++sourceRequestId
  selectedTaskId.value = ''
  resetSource()
  sourceTypeFilter.value = 'PRODUCTION'
  if (!taskId) {
    preselectionError.value = '采购跟踪来源信息不完整，请重新选择生产订单和产品 BOM。'
    return
  }
  const task = visibleSourceOptions.value.find(item => item.id === taskId && item.source_type === 'PRODUCTION')
  if (!task) {
    preselectionError.value = '关联生产订单不在当前可选范围，可能已变更状态或权限，请重新核对来源。'
    return
  }
  if (!bomId) {
    await selectTask(task)
    return
  }
  selectedTaskId.value = task.id
  sourceLoading.value = true
  try {
    const result = await fetchPurchaseOrderSource(task.id, bomId)
    if (requestId !== sourceRequestId) return
    // 指定产品失效时不得静默接受接口返回的其他默认 BOM。
    if (result.production_task?.id !== task.id || result.selected_bom_id !== bomId
      || !result.bom_options.some(item => item.bom_id === bomId)) {
      resetSource()
      preselectionError.value = '指定产品 BOM 已不在当前可选来源中，请核对后重新选择。'
      return
    }
    applySource(result)
  } catch (error) {
    if (requestId === sourceRequestId) preselectionError.value = apiErrorMessage(error, '采购跟踪来源读取失败，请重试或重新选择。')
  } finally {
    if (requestId === sourceRequestId) sourceLoading.value = false
  }
}

async function initializePage(): Promise<void> {
  const requestId = sourceRequestId
  const initialPath = route.fullPath
  await loadOptions()
  if (!canAdd.value || loadError.value || requestId !== sourceRequestId || initialPath !== route.fullPath) return
  if (isBatchMode.value) await loadGroup()
  else if (isDetailStep.value) await restoreDetailSource()
  else if (!isPackaging.value) await restoreTrackingSource()
}

async function findCreatedGroup(taskId: string, bomIds: string[]) {
  for (let page = 1; ; page++) {
    const result = await fetchPurchaseGroups({ production_task_id: taskId, page })
    const match = result.data.find(item => {
      if (item.production_task_id !== taskId || item.combined_into_group_id) return false
      if (item.source_bom_id_snapshot) return bomIds.length === 1 && item.source_bom_id_snapshot === bomIds[0]
      const sources = new Set(item.progress.lines.flatMap(line => line.source_snapshot.source_contributions?.map(row => row.bom_id) ?? []))
      return sources.size === bomIds.length && bomIds.every(id => sources.has(id))
    })
    if (match || page >= result.meta.total_pages) return match
  }
}

function purchaseGroupResultUnknown(error: unknown): boolean {
  if (!isAxiosError(error)) return false
  const response = error.response
  if (!response) return ['ECONNABORTED', 'ETIMEDOUT', 'ERR_NETWORK'].includes(error.code ?? '')
  if (response.status === 500) return response.data == null || (typeof response.data === 'string' && !response.data.trim())
  return [408, 502, 503, 504].includes(response.status)
}

async function openStandardGroup(taskId: string) {
  const requestId = sourceRequestId
  const sources = selectedBomSources.value
  const taskNumber = selectedTask.value?.task_number || ''
  let target: PurchaseGroup | undefined
  let recovered = false
  try {
    target = (await createPurchaseGroup({ production_task_id: taskId, ...(sources.length === 1 ? sources[0]! : { sources }) })).data
  } catch (error) {
    if (requestId !== sourceRequestId) return
    if (!purchaseGroupResultUnknown(error)) {
      ElMessage.error(apiErrorMessage(error, '创建采购需求失败，请重新读取来源。'))
      return
    }
    const pendingMessage = `未能确认创建结果，请在采购需求列表按生产任务号 ${taskNumber} 核对后再操作。`
    try {
      target = await findCreatedGroup(taskId, sources.map(item => item.bom_id))
    } catch (readError) {
      if (requestId === sourceRequestId) sourceError.value = pendingMessage + apiErrorMessage(readError, '读取采购需求失败。')
      return
    }
    if (requestId !== sourceRequestId) return
    if (!target) { sourceError.value = pendingMessage; return }
    recovered = true
    ElMessage.success(`已查到采购需求 ${target.group_number}。`)
  }
  if (requestId !== sourceRequestId) return
  const navigationMessage = `采购需求 ${target.group_number} 已建立。页面未打开，请从采购需求列表进入。`
  const destination = recovered ? { name: 'purchase-group-detail', params: { id: target.id } }
    : { name: 'purchase-batch-create', params: { groupId: target.id } }
  try {
    if (await router.push(destination)) sourceError.value = navigationMessage
  } catch (error) {
    sourceError.value = navigationMessage
    console.error('打开采购需求页面失败', error)
  }
}

async function goToDetails(): Promise<void> {
  if (isPackaging.value) {
    if (saving.value || !canContinueToDetails.value) return
    saving.value = true
    let groupsPrepared = false
    try {
      const sessionId = createClientUuid()
      const groups = await preparePackagingPurchase(packagingSources.value.filter(item => selectedBomIds.value.includes(item.bom_id)))
      groupsPrepared = true
      await router.push({ name: 'packaging-purchase-batch', query: { group_ids: groups.map(item => item.id), batch_session_id: sessionId } })
    } catch (error) {
      showActionError(apiErrorMessage(error, groupsPrepared
        ? '包材采购需求已就绪。请从包材采购列表继续填写。'
        : '创建包材采购需求失败，请刷新来源后重试。'))
    } finally { saving.value = false }
    return
  }
  if (!selectedTaskId.value) {
    showActionError('请先选择采购来源。')
    return
  }
  if (!isSampleSource.value && !selectedBomIds.value.length) {
    showActionError('请选择本次要采购的产品 BOM。')
    return
  }
  if (!canContinueToDetails.value) {
    showActionError(sourceBlockerMessage.value || sourceError.value || '当前来源没有可采购的明细。')
    return
  }
  const sourceId = isSampleSource.value ? selectedTask.value?.source_id || '' : selectedTaskId.value
  if (!isSampleSource.value) {
    if (selectedBom.value?.existing_purchase_group_id) {
      await router.push({ name: 'purchase-group-detail', params: { id: selectedBom.value.existing_purchase_group_id } })
      return
    }
    if (saving.value) return
    saving.value = true
    try { await openStandardGroup(sourceId) }
    finally { saving.value = false }
    return
  }
  void router.push({
    name: 'purchase-order-create-details',
    query: {
      source_type: isSampleSource.value ? 'SAMPLE' : 'PRODUCTION',
      source_id: sourceId,
      ...(isSampleSource.value ? {} : { bom_id: selectedBomId.value }),
    },
  })
}

function back(): void {
  if (isPackaging.value) {
    void router.push(packagingGroupIds.value.length === 1
      ? { name: 'packaging-purchase-detail', params: { id: packagingGroupIds.value[0] } }
      : { name: 'packaging-purchases' })
    return
  }
  void router.push(isBatchMode.value ? { name: 'purchase-group-detail', params: { id: route.params.groupId } } : { name: isDetailStep.value ? 'purchase-order-create' : 'purchase-orders' })
}

function groupSupplierCategory(snapshot: PurchaseGroupProgressLine['source_snapshot']): SupplierCategory | null {
  const catalogCategory = snapshot.material_selection_snapshot?.category_key
  if (catalogCategory) {
    const categories: Record<string, SupplierCategory> = {
      TUBE: 'TUBE', HARDWARE: 'HARDWARE', PLASTIC: 'PLASTIC_PART', PACKAGING: 'PACKAGING', FABRIC: 'FABRIC', AUXILIARY: 'AUXILIARY',
    }
    return Object.hasOwn(categories, catalogCategory) ? categories[catalogCategory]! : null
  }
  // 旧总单没有目录类别时，沿用采购来源已有的分类顺序，仅使用冻结文字。
  if (snapshot.section_type_snapshot === 'PROFILE') return 'TUBE'
  const text = [snapshot.section_title_snapshot, snapshot.category_snapshot, snapshot.material_snapshot,
    snapshot.part_name_snapshot, snapshot.raw_material_snapshot].join(' ').toLowerCase()
  const rules: [SupplierCategory, string[]][] = [
    ['PACKAGING', ['包材', '包装', '纸箱', '纸盒', '塑料袋', '编织袋']],
    ['PLASTIC_PART', ['塑料', '塑胶', '尼龙件', '注塑']],
    ['HARDWARE', ['五金', '螺丝', '螺母', '铆钉', '垫片', '铁件']],
    ['AUXILIARY', ['辅料', '织带', '松紧', '拉链', '魔术贴', '绳', '线']],
    ['FABRIC', ['面料', '布', '牛津', '涤纶', '帆布', '网布']],
  ]
  return rules.find(([, keywords]) => keywords.some(keyword => text.includes(keyword)))?.[0] || null
}

function groupDraft(line: PurchaseGroupProgressLine): PurchaseLineDraft {
  const snapshot = line.source_snapshot
  const weightLine = isWeightSourceLine({
    section_type: snapshot.section_type_snapshot,
    section_title: snapshot.section_title_snapshot,
    source_unit_text: line.source_unit_text || snapshot.source_unit_text,
    suggested_purchase_weight_kg: snapshot.suggested_purchase_weight_kg,
    calculation_snapshot: snapshot.calculation_snapshot,
  })
  const remaining = remainingForBatch(line, weightLine ? snapshot.suggested_purchase_weight_kg || line.required_quantity : line.required_quantity)
  return {
    batch_source: line,
    material_color: materialAttributeFields(snapshot).filter(field => ['色卡', '颜色', '色号'].includes(field.label))
      .map(field => field.value).join(' / '),
    purchase_group_line_id: line.id,
    material_catalog_id: snapshot.material_catalog_id, material_selection_snapshot: snapshot.material_selection_snapshot,
    bom_id: snapshot.bom_id || undefined, bom_line_id: snapshot.bom_line_id || undefined,
    bom_number: snapshot.bom_number_snapshot, bom_status: '', bom_status_display: '', line_number: line.line_number,
    section_type: snapshot.section_type_snapshot, section_title: snapshot.section_title_snapshot, category: snapshot.category_snapshot,
    product_line_id: snapshot.product_line_id_snapshot || '', product_line_number: 0,
    product_number: snapshot.product_number_snapshot, product_name: snapshot.product_name_snapshot,
    product_specification: snapshot.product_specification_snapshot, product_color: '',
    material: snapshot.material_snapshot, part_name: snapshot.part_name_snapshot, specification: snapshot.specification_snapshot,
    raw_material: snapshot.raw_material_snapshot, source_bom_line_id_snapshot: snapshot.source_bom_line_id_snapshot || '',
    required_quantity: line.required_quantity, source_quantity_field: snapshot.source_quantity_field,
    source_quantity_text: snapshot.source_quantity_text, source_unit_text: line.source_unit_text,
    quantity_parse_status: snapshot.quantity_parse_status, suggested_supplier_category: groupSupplierCategory(snapshot), category_source: 'UNKNOWN',
    material_attributes_snapshot: snapshot.material_attributes_snapshot,
    calculation_snapshot: snapshot.calculation_snapshot,
    raw_bar_length_m: snapshot.raw_bar_length_m, suggested_bar_count: snapshot.suggested_bar_count,
    suggested_purchase_meters: snapshot.suggested_purchase_meters,
    raw_bar_weight_kg: snapshot.raw_bar_weight_kg,
    suggested_purchase_weight_kg: snapshot.suggested_purchase_weight_kg,
    supplier_id: null, delivery_date: '',
    actual_bar_count: snapshot.raw_bar_length_m && !weightLine ? (line.remaining_purchase_quantity === undefined
      ? remainingPurchaseQuantity(snapshot.suggested_bar_count, line.purchased_bar_count, true)
      : pipeRootsFromMeters(remaining || '', snapshot.raw_bar_length_m)) ?? '' : '',
    actual_purchase_quantity: snapshot.raw_bar_length_m && !weightLine ? '' : remaining ?? '',
    unit_price: '',
  }
}

function packagingDisplayGroup(groups: PurchaseGroup[]): PurchaseGroup {
  packagingGroups.value = groups
  const first = groups[0]!
  if (groups.length === 1) return first
  return {
    ...first,
    production_task_number_snapshot: groups.map(item => item.production_task_number_snapshot).join('、'),
    combined_into_group_id: groups.find(item => item.combined_into_group_id)?.combined_into_group_id ?? null,
    products: groups.flatMap(item => item.products ?? []),
    progress: {
      ...first.progress,
      status: groups.some(item => item.progress.status === 'UNKNOWN') ? 'UNKNOWN' : first.progress.status,
      lines: groups.flatMap(item => item.progress.lines),
      external_supply_line_ids: groups.flatMap(item => item.progress.external_supply_line_ids ?? []),
    },
    batches: groups.flatMap(item => item.batches),
    batch_page: {
      current_batch_number: groups.find(item => item.batch_page?.current_batch_number)?.batch_page?.current_batch_number ?? null,
      next_batch_number: first.batch_page!.next_batch_number,
      submitted_line_ids: groups.flatMap(item => item.batch_page?.submitted_line_ids ?? []),
      draft_orders: groups.flatMap(item => item.batch_page?.draft_orders ?? []),
    },
  }
}

async function loadGroup(preserveInput = false): Promise<void> {
  const current = ++sourceRequestId
  sourceLoading.value = true
  try {
    const result = isPackaging.value
      ? await fetchPackagingPurchasePage(packagingGroupIds.value, batchSessionId.value!)
        .then(page => ({ etag: page.etag, data: packagingDisplayGroup(page.groups) }))
      : await fetchVersionedPurchaseGroup(String(route.params.groupId), batchSessionId.value)
    if (current !== sourceRequestId) return
    group.value = result.data
    groupEtag.value = result.etag
    currentBatchNumber.value = result.data.batch_page?.current_batch_number ?? null
    const submitted = new Set(result.data.batch_page?.submitted_line_ids)
    for (const line of result.data.progress.lines) {
      if (submitted.has(line.id) && hasNoRemainingPurchase(line)) fulfilledSupplierLineIds.add(line.id)
      else if (!hasNoRemainingPurchase(line)) fulfilledSupplierLineIds.delete(line.id)
    }
    // 首次读取失败时没有可保留的草稿；重试成功必须初始化材料。
    if (!preserveInput || (!lines.value.length && !fulfilledSupplierLineIds.size)) {
      lines.value = result.data.progress.lines.filter(line => !fulfilledSupplierLineIds.has(line.id)).map(groupDraft)
      batchRequestId.value = ''
      batchContentSignature = ''
      batchType.value = 'NORMAL'
    } else {
      const previous = new Map(lines.value.map(line => [line.purchase_group_line_id, line]))
      const external = new Set(result.data.progress.external_supply_line_ids || [])
      const changedSets = new Set(lines.value.filter(line => line.set_pricing && external.has(line.purchase_group_line_id!))
        .map(line => line.set_pricing!.anchor_id))
      lines.value = lines.value.filter(line => !external.has(line.purchase_group_line_id!) && !fulfilledSupplierLineIds.has(line.purchase_group_line_id!))
      for (const source of result.data.progress.lines) {
        const existingLine = previous.get(source.id)
        if (fulfilledSupplierLineIds.has(source.id) && hasNoRemainingPurchase(source)) continue
        fulfilledSupplierLineIds.delete(source.id)
        if (!existingLine) lines.value.push(groupDraft(source))
        else existingLine.batch_source = source
      }
      for (const anchorId of changedSets) {
        const members = lines.value.filter(line => line.set_pricing?.anchor_id === anchorId)
        if (!external.has(anchorId) && members.length >= 2) continue
        for (const line of members) {
          line.set_pricing = null
          line.unit_price = ''
        }
        if (members.length) ElMessage.warning('采购需求已变化，原套餐剩余部件请重新按套或填写单价。')
      }
    }
    batchConflict.value = ''
    sourceError.value = result.data.progress.status === 'UNKNOWN' ? '采购需求来源待核对，暂不能创建批次。' : ''
  } catch (error) {
    if (current === sourceRequestId) batchConflict.value = apiErrorMessage(error, '采购需求读取失败。')
  } finally { if (current === sourceRequestId) sourceLoading.value = false }
}

async function openExistingGroup(blocker = existingSourceBlocker.value): Promise<void> {
  if (!blocker) return
  try {
    const id = blocker.existing_purchase_group_id || (blocker.existing_purchase_order_id ? (await fetchVersionedPurchaseOrder(blocker.existing_purchase_order_id)).data.purchase_group_id : null)
    if (id) await router.push({ name: 'purchase-group-detail', params: { id } })
    else ElMessage.warning('该来源没有可读取的采购需求归属，请联系管理员核对。')
  } catch (error) { ElMessage.error(apiErrorMessage(error, '采购需求归属读取失败。')) }
}

watch(() => route.fullPath, () => {
  editingSetId.value = ''
  supplierBatchReview.value = null
  finalBatchReview.value = null
  sourceRequestId++
  resetSource()
  pendingSupplierBatch.value = null
  lastSupplierBatch.value = null
  fulfilledSupplierLineIds.clear()
  packagingGroups.value = []
  group.value = null
  groupEtag.value = ''
  currentBatchNumber.value = null
  void initializePage()
})

function toggleDetailFullscreen(): void {
  detailFullscreen.value = !detailFullscreen.value
}

function handleWindowKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && detailFullscreen.value) detailFullscreen.value = false
}

onMounted(() => {
  window.addEventListener('keydown', handleWindowKeydown)
  void initializePage()
})
onBeforeUnmount(() => { sourceRequestId++; window.removeEventListener('keydown', handleWindowKeydown) })
</script>

<template>
  <section ref="formPage" class="purchase-form-page erp-glass-form" :class="{ 'is-sample-source': isSampleSource, 'is-detail-step': isDetailStep, 'is-batch-page': isBatchMode }" data-testid="purchase-order-form-page">
    <div v-if="!canAdd" class="state-page">
      <h1>无权新建采购需求</h1>
      <p>请联系管理员开通“{{ isPackaging ? '办理包材采购' : '采购订单新增' }}”权限后重试。</p>
      <ElButton @click="back">返回采购需求列表</ElButton>
    </div>

    <template v-else>
      <header class="page-heading">
        <div>
          
          <h1>{{ isPackaging ? (isBatchMode ? '填写包材采购' : '新建包材采购') : isBatchMode ? '新增采购批次' : isDetailStep ? '填写采购明细' : '新建采购需求' }}</h1>
          <p v-if="!isBatchMode">{{ isPackaging ? '选择本次采购涉及的生产任务 BOM' : isDetailStep ? '填写供应商、采购交期、数量和单价' : '选择订单，勾选要一起采购的产品' }}</p>
          <strong v-else-if="group?.production_task_number_snapshot" class="production-task-number">{{ group.production_task_number_snapshot }}</strong>
          <span v-if="isBatchMode && displayedBatchNumber && !isMultiTask">第 {{ displayedBatchNumber }} 批</span>
        </div>
        <div class="page-action-panel">
          <div class="page-actions">
            <ElButton :disabled="saving" @click="back"><img class="purchase-icon" :src="backIcon" alt="" />{{ isBatchMode ? '返回采购需求' : isDetailStep ? '返回选择' : '返回列表' }}</ElButton>
            <ElButton v-if="!isDetailStep" type="primary" :loading="saving" :disabled="!canContinueToDetails || sourceLoading || saving" data-testid="purchase-source-next" @click="goToDetails">{{ selectedBom?.existing_purchase_group_id ? '进入已有采购需求' : '下一步：填写明细' }}<img class="purchase-icon" :src="rightIcon" alt="" /></ElButton>
            <ElButton v-if="isDetailStep && !isPackaging" type="primary" plain :loading="saving && !pendingSupplierBatch" :disabled="saving || !!pendingSupplierBatch" @click="saveDraft">保存草稿</ElButton>
          </div>
        </div>
      </header>

      <ElAlert v-if="loadError" type="error" :title="loadError" :closable="false" show-icon>
        <ElButton link @click="initializePage">重新加载</ElButton>
      </ElAlert>
      <ElAlert v-if="!isDetailStep && preselectionError" type="warning" :title="preselectionError" :closable="false" show-icon data-testid="purchase-tracking-source-error">
        <ElButton link :disabled="sourceLoading || optionsLoading" @click="initializePage">重新读取来源</ElButton>
      </ElAlert>
      <ElAlert v-if="isBatchMode && (batchConflict || sourceError)" type="warning" :title="batchConflict || sourceError" :closable="false" show-icon>
        <ElButton v-if="pendingSupplierBatch" link type="primary" :disabled="saving" @click="submitPendingSupplierBatch">重试本次保存</ElButton>
        <ElButton v-else link :disabled="sourceLoading" @click="loadGroup(true)">重新读取采购需求版本（保留输入）</ElButton>
        <ElButton link @click="back">查看采购需求已有批次</ElButton>
      </ElAlert>
      <ElAlert v-if="isBatchMode && group?.combined_into_group_id" type="info" title="后续批次请在合并采购需求中填写。" :closable="false">
        <ElButton link @click="router.push({ name: isPackaging ? 'packaging-purchase-detail' : 'purchase-group-detail', params: { id: group.combined_into_group_id } })">打开合并采购需求</ElButton>
      </ElAlert>
      <div v-if="isBatchMode" class="batch-type-field">
        <span>批次类型</span><ElRadioGroup v-model="batchType" :disabled="saving" aria-label="批次类型"><ElRadio value="NORMAL">正常采购</ElRadio><ElRadio value="SUPPLEMENT">补料</ElRadio></ElRadioGroup>
        <PurchaseGridCell><span>本批采购 {{ selectedLines.length }} / {{ lines.length }} 项材料</span></PurchaseGridCell>
      </div>

      <section v-if="isPackaging && !isDetailStep" v-loading="optionsLoading" class="task-card">
        <header><div><h2>采购来源</h2></div></header>
        <div class="task-selector-row">
          <ElSelect v-model="selectedBomIds" multiple filterable clearable class="task-source-filter"
            data-testid="packaging-bom-select" aria-label="选择采购 BOM" placeholder="搜索生产任务单号、产品或 BOM"
            no-data-text="没有可选的包材 BOM" :disabled="saving" :multiple-limit="100">
            <ElOption v-for="item in packagingSources" :key="item.bom_id" :value="item.bom_id"
              :label="`${item.task_number} · ${item.product_name} · ${item.bom_number}`" />
          </ElSelect>
          <ElButton :disabled="saving || optionsLoading" @click="loadOptions">刷新</ElButton>
        </div>
      </section>
      <section v-else-if="!isDetailStep" v-loading="optionsLoading || sourceLoading" class="task-card">
        <header>
          <div><h2>采购来源</h2></div>
        </header>
        <div class="task-selector-row">
          <ElSelect v-model="sourceTypeFilter" class="source-type-filter" aria-label="采购来源类型" @change="handleSourceTypeFilterChange">
            <ElOption label="全部来源" value="ALL" />
            <ElOption label="生产订单" value="PRODUCTION" />
            <ElOption label="打样单" value="SAMPLE" />
          </ElSelect>
          <ElSelect
            v-model="selectedTaskId"
            class="task-source-filter"
            filterable
            clearable
            :loading="optionsLoading"
            placeholder="搜索来源单号"
            no-data-text="没有匹配的采购来源"
            data-testid="production-task-select"
            popper-class="purchase-source-popper"
            aria-label="选择采购来源"
            @change="handleTaskSelection"
          >
            <template #label>{{ selectedTask?.source_number }} · {{ sourceTypeLabel }}</template>
            <template #header><div class="task-select-option source-option-heading"><span>来源单号</span><span>订单来源</span><span>采购信息</span><span>状态</span></div></template>
            <ElOption
              v-for="task in visibleSourceOptions"
              :key="task.id"
              :label="`${task.source_number} · ${task.source_type === 'SAMPLE' ? '打样单' : '生产订单'} · ${task.customer_name}`"
              :value="task.id"
              :disabled="!task.can_create && !task.blockers?.some(blocker => ['PURCHASE_GROUP_EXISTS', 'PURCHASE_ORDER_EXISTS'].includes(blocker.code))"
            >
              <div class="task-select-option" :data-task-id="task.id">
                <strong>{{ task.task_number }}</strong>
                <ElTag class="purchase-source-tag" :class="{ 'is-sample': task.source_type === 'SAMPLE' }" effect="dark">{{ task.source_type === 'SAMPLE' ? '打样单' : '生产订单' }}</ElTag>
                <small>{{ sourceQuantityText(task) }} · 交期 {{ task.delivery_date || '—' }}</small>
                <ElTag class="task-source-status" size="small" :type="task.can_create ? task.source_type === 'SAMPLE' ? 'warning' : 'success' : 'info'" effect="dark">{{ task.can_create ? task.source_type === 'SAMPLE' ? '待采购' : (task.source_status_display || '可采购') : (task.source_status_display || task.status_display) }}</ElTag>
              </div>
            </ElOption>
          </ElSelect>
          <ElButton @click="refreshOptions"><img class="purchase-icon" :src="refreshIcon" alt="" />刷新</ElButton>
        </div>
        <div v-if="selectedTask" class="selected-task-summary" data-testid="selected-production-task-summary">
          <dl class="selected-order-overview">
            <div><dt>订单来源</dt><dd><ElTag class="purchase-source-tag" :class="{ 'is-sample': isSampleSource }" effect="dark">{{ sourceTypeLabel }}</ElTag></dd></div>
            <div><dt>客户</dt><dd>{{ selectedTask.customer_name }}</dd></div>
            <div><dt>交期</dt><dd>{{ selectedTask.delivery_date || '—' }}</dd></div>
            <div><dt>{{ isSampleSource ? '采购需求' : '本单产品' }}</dt><dd>{{ isSampleSource ? selectedTask.demand_count : selectedProducts.length }} 项</dd></div>
          </dl>
          <section v-if="!isSampleSource" class="selected-product-section" data-testid="selected-production-product-list">
            <div v-if="selectedProducts.length" class="selected-product-list">
              <div class="selected-product-row selected-product-row--heading">
                <span>选择</span><span>产品编码</span><span>货号</span><span>产品名称</span><span>规格</span><span>颜色</span><span>材质</span><span>订单数量</span><span>BOM状态</span>
              </div>
              <div v-for="{ product, option, available, checked } in productRows" :key="product.id"
                class="selected-product-row selected-product-row--option"
                :class="{ 'is-selected': checked, 'is-unavailable': !available }"
                :data-product-line-id="product.id" :data-selected="checked"
                role="checkbox" :tabindex="available ? 0 : -1"
                :aria-label="`选择第${product.line_number}行：${product.product_name}，${productColorText(product)}`"
                :aria-checked="checked" :aria-disabled="!available"
                @click="handleProductSelection(option)" @keydown.enter.prevent="handleProductSelection(option)" @keydown.space.prevent="handleProductSelection(option)">
                <span class="product-checkbox" aria-hidden="true" />
                <span :title="product.product_code">{{ product.product_code || '—' }}</span>
                <span :title="product.item_number">{{ product.item_number || '—' }}</span><span :title="product.product_name">{{ product.product_name || '—' }}</span>
                <span :title="product.specification_display ?? product.specification">{{ (product.specification_display ?? product.specification) || '—' }}</span>
                <span :title="productColorText(product)">{{ product.color_name || '—' }}</span>
                <span :title="product.material">{{ product.material || '—' }}</span>
                <span :title="`${product.order_quantity} ${product.unit_name || product.unit_code}`">{{ product.order_quantity }} {{ product.unit_name || product.unit_code }}</span>
                <span :title="option?.blockers?.map(item => item.message).join(' ') || option?.bom_status_display || '未建立'"><span class="bom-status" :class="{ 'is-ready': available }">{{ option?.bom_status_display || '未建立' }}</span></span>
              </div>
            </div>
            <p v-else>暂无待采购产品明细。</p>
            <p class="product-selection-caption" :class="{ 'is-blocked': sourceError }" role="status">
              {{ sourceError || (selectedBomIds.length ? `已选 ${selectedBomIds.length} 个产品` : '请勾选本次采购的产品') }}
            </p>
            <ElButton v-for="link in existingGroupLinks" :key="link.id" link type="primary" @click="openExistingGroup(link.blocker)">{{ link.label }}</ElButton>
          </section>
          <div v-else class="sample-source-summary">
            <strong>{{ source?.sample_request?.summary || '打样采购需求' }}</strong>
            <p role="status" :class="{ 'is-blocked': sourceError }">{{ sourceError || '采购需求来自仓库已确认的缺料明细' }}</p>
          </div>
        </div>
        <p v-else class="task-selector-hint">选择后显示采购来源、客户、交期和采购需求</p>
      </section>

      <section v-if="isDetailStep" class="detail-card" :class="{ 'is-empty': !lines.length, 'is-fullscreen': detailFullscreen }" data-testid="purchase-detail-card">
        <header>
          <div class="detail-title-context">
            <h2>{{ isSampleSource ? '样品采购需求' : '采购明细' }}</h2>
            <span>{{ lines.length }} 项</span>
            <div v-if="!isSampleSource && selectedProduct" class="selected-product-context" data-testid="purchase-detail-product">
              <span>产品</span>
              <strong>{{ selectedProduct.product_name || '—' }}</strong>
              <small>规格：{{ selectedProduct.specification || '—' }}</small>
              <small>颜色：{{ productColorText(selectedProduct) }}</small>
            </div>
          </div>
          <div class="detail-header-actions">
            <label class="bulk-field bulk-field--category" data-testid="purchase-bulk-supplier-category">
              <span>分类</span>
              <ElSelect v-model="bulkSupplierCategory" filterable clearable :value-on-clear="null" aria-label="统一供应商分类" :disabled="!canWriteLines || sourceLoading || !lines.length" placeholder="请选择分类" popper-class="purchase-detail-popper" @change="refreshBulkSupplier">
                <ElOption label="全部分类" value="__all__" />
                <ElOption v-for="category in supplierCategories" :key="category" :label="category" :value="category" />
              </ElSelect>
            </label>
            <label class="bulk-field bulk-field--supplier" data-testid="purchase-bulk-supplier">
              <span>统一供应商</span>
              <ElSelect
                v-model="bulkSupplierId"
                filterable
                clearable
                aria-label="统一供应商"
                :disabled="!canWriteLines || sourceLoading || !bulkSupplierLines.length"
                :placeholder="!bulkSupplierCategory ? '请先选择分类' : bulkSupplierCategory === '__all__' ? '选择后同步全部' : '选择后同步本分类'"
                :no-data-text="bulkSupplierEmptyText"
                popper-class="purchase-detail-popper"
                @change="applyBulkSupplier"
              >
                <template #label="{ value, label }">{{ options.suppliers.find(supplier => supplier.id === value)?.supplier_name || label }}</template>
              <ElOption v-for="supplier in bulkSupplierOptions" :key="supplier.id" :label="supplier.supplier_name" :value="supplier.id" />
              </ElSelect>
            </label>
            <label class="bulk-field bulk-field--date" data-testid="purchase-bulk-delivery-date">
              <span>统一交期</span>
              <ElDatePicker
                v-model="bulkDeliveryDate"
                type="date" :prefix-icon="CalendarIcon"
                value-format="YYYY-MM-DD"
                format="YYYY-MM-DD"
                :disabled-date="disablePastDeliveryDate"
                :disabled="!canWriteLines || !lines.length"
                placeholder="选择后同步全部"
                popper-class="purchase-detail-popper"
                @change="applyBulkDeliveryDate"
              />
            </label>
            <ElButton plain data-testid="purchase-detail-fullscreen" @click="toggleDetailFullscreen"><img class="purchase-icon" :src="expandIcon" alt="" />{{ detailFullscreen ? '退出全屏' : '全屏' }}</ElButton>
          </div>
        </header>
        <ElTable v-loading="sourceLoading" :data="gridRows" :row-key="purchaseLineKey" :height="detailTableHeight" class="erp-table-editor purchase-lines" data-testid="purchase-lines" @cell-mouse-enter="handleLineMouseEnter" @mouseleave="handleLineMouseLeave">
          <ElTableColumn type="index" label="序号" width="48" align="center" />
          <ElTableColumn v-if="isPackaging" label="生产任务单号" width="164" show-overflow-tooltip>
            <template #default="{ row }"><strong>{{ packagingLineGroup.get(row.purchase_group_line_id)?.production_task_number_snapshot }}</strong></template>
          </ElTableColumn>
          <ElTableColumn v-if="isPackaging" label="产品 / BOM" width="230" show-overflow-tooltip>
            <template #default="{ row }">{{ row.product_name }} · {{ row.bom_number }}</template>
          </ElTableColumn>
          <ElTableColumn prop="category" label="分类" width="106" show-overflow-tooltip />
          <ElTableColumn label="物料信息" width="208">
            <template #default="{ row }"><div class="material-cell"><strong>{{ materialTitle(row) }}</strong></div></template>
          </ElTableColumn>
          <ElTableColumn v-if="isBatchMode" label="颜色" width="112" show-overflow-tooltip>
            <template #default="{ row }">{{ row.material_color || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn v-if="isSampleSource" label="材质" width="118" show-overflow-tooltip>
            <template #default="{ row }">{{ row.material || row.raw_material || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn label="规格" width="220">
            <template #default="{ row }"><ElTooltip placement="top" :show-after="80" :visible="hoveredLineKey === purchaseLineKey(row)" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in materialAttributeFields(row)" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div></div></template><span class="material-detail">{{ materialSpecificationValue(row) }}</span></ElTooltip></template>
          </ElTableColumn>
          <ElTableColumn v-if="isSampleSource" label="颜色" width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.product_color || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn v-if="isSampleSource" label="需求数量" width="104">
             <template #default="{ row }"><span v-if="isWeightLine(row)">见打样需求</span><template v-else>{{ formatSuggestedQuantity(row.sample_demand_quantity) }} {{ row.sample_demand_unit || (isPipePurchaseLine(row) ? '米' : row.source_unit_text) }}</template></template>
          </ElTableColumn>
          <ElTableColumn v-if="isSampleSource" label="仓库可供" width="100">
              <template #default="{ row }"><span v-if="isWeightLine(row)">见打样需求</span><template v-else>{{ formatSuggestedQuantity(row.sample_supply_quantity) }} {{ row.sample_demand_unit || (isPipePurchaseLine(row) ? '米' : row.source_unit_text) }}</template></template>
          </ElTableColumn>
          <ElTableColumn :label="isBatchMode ? '剩余采购量' : isSampleSource ? '待采购量' : '建议采购量'" :width="isSampleSource ? 110 : 180" align="right" header-align="left">
            <template #default="{ row }"><div class="quantity-cell" :class="{ 'quantity-cell--batch': isBatchMode }">
              <template v-if="isBatchMode">
                <div>
                  <PurchaseQuantitySources v-if="row.batch_source?.source_snapshot.source_contributions?.length"
                    :contributions="row.batch_source.source_snapshot.source_contributions">
                    {{ batchRemainingQuantities.get(row.purchase_group_line_id)?.primary ?? '待核对' }}
                  </PurchaseQuantitySources>
                  <strong v-else>{{ batchRemainingQuantities.get(row.purchase_group_line_id)?.primary ?? '待核对' }}</strong>
                  <small v-if="batchRemainingQuantities.get(row.purchase_group_line_id)?.detail"> {{ batchRemainingQuantities.get(row.purchase_group_line_id)?.detail }}</small>
                </div>
              </template>
              <template v-else-if="isWeightLine(row)"><strong>{{ weightSuggestedQuantity(row) ? `${formatSuggestedQuantity(weightSuggestedQuantity(row))} kg` : '待填写重量' }}</strong></template><template v-else-if="isPipePurchaseLine(row)"><strong>{{ formatSuggestedQuantity(row.required_quantity || row.source_quantity_text) }} 米</strong></template><template v-else-if="row.raw_bar_length_m"><strong>{{ compactDecimal(row.suggested_purchase_meters) }} 米</strong></template><template v-else><strong>{{ formatSuggestedQuantity(row.required_quantity || row.source_quantity_text) }}</strong><small>{{ row.source_unit_text || '单位未识别' }}</small></template></div></template>
          </ElTableColumn>
          <ElTableColumn label="供应商" :width="isSampleSource ? 210 : 271">
            <template #default="{ row, $index }">
              <div class="line-field" data-grid-field :data-grid-row="$index" data-grid-column="0" data-testid="purchase-line-supplier"
                @copy.capture="copyGridTerm($event, row, 'supplier_id')" @paste.capture="pasteGridTerm($event, row, 'supplier_id')"
                @keydown.capture="handleGridNavigation($event, $index, 0)">
                <ElSelect v-model="row.supplier_id" :persistent="false" filterable clearable :disabled="!canWriteLines" :placeholder="canWriteLines ? '请选择供应商' : '当前仅预览'"
                  :no-data-text="row.suggested_supplier_category ? noMatchingSupplierText : '暂无可用供应商'" popper-class="purchase-detail-popper" @change="onLineSupplierChange(row)">
                  <template #label="{ value, label }">{{ options.suppliers.find(supplier => supplier.id === value)?.supplier_name || label }}</template>
                  <ElOption v-for="supplier in lineSupplierOptions(row)" :key="supplier.id" :label="supplier.supplier_name" :value="supplier.id" />
                </ElSelect>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="采购交期" :width="isSampleSource ? 170 : 195">
            <template #default="{ row, $index }">
              <div class="line-field" data-grid-field :data-grid-row="$index" data-grid-column="1" data-testid="purchase-line-delivery-date"
                @copy.capture="copyGridTerm($event, row, 'delivery_date')" @paste.capture="pasteGridTerm($event, row, 'delivery_date')"
                @keydown.capture="handleGridNavigation($event, $index, 1)">
                <ElDatePicker v-model="row.delivery_date" type="date" :automatic-dropdown="false" :prefix-icon="CalendarIcon" value-format="YYYY-MM-DD" format="YYYY-MM-DD" :disabled-date="disablePastDeliveryDate" :disabled="!canWriteLines" placeholder="选择采购交期" popper-class="purchase-detail-popper" @change="onLineDeliveryChange(row)" />
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="实际采购数量" :width="isSampleSource ? 148 : 163">
            <template #default="{ row, $index }">
              <PurchaseGridCell>
              <div class="line-field line-field--quantity" :class="{ 'pipe-order-quantity': isWeightLine(row) || !isPipePurchaseLine(row) && row.raw_bar_length_m }" data-grid-field :data-grid-row="$index" data-grid-column="2" data-testid="purchase-line-quantity" @keydown.capture="handleGridNavigation($event, $index, 2)">
                <ElPopover v-if="isPipePurchaseLine(row) && !isWeightLine(row)" trigger="click" placement="top" :width="340" :show-arrow="false" :teleported="true" :disabled="!canWriteLines" @after-enter="focusPipeQuantity(purchaseLineKey(row))">
                  <template #reference><button type="button" class="pipe-quantity-trigger" data-pipe-quantity-trigger :aria-label="`第 ${$index + 1} 行管材采购数量`" :disabled="!canWriteLines">{{ pipeQuantitySummary(row) }}</button></template>
                  <div class="pipe-quantity-editor erp-table-editor" :data-pipe-editor="purchaseLineKey(row)">
                    <label><span>采购数量</span><ElInput :model-value="effectivePurchaseQuantity(row)" aria-label="实际采购数量（米）" inputmode="decimal" maxlength="19" :disabled="!canWriteLines" placeholder="填写米数" @update:model-value="setPipePurchaseMeters(row, $event)"><template #append>米</template></ElInput></label>
                    <label><span>每根长度</span><ElInput :model-value="row.raw_bar_length_m" aria-label="采购每根长度（米）" inputmode="decimal" maxlength="14" :disabled="!canWriteLines" placeholder="每根米数" @update:model-value="setPipeLength(row, $event)"><template #append>米/根</template></ElInput></label>
                  </div>
                </ElPopover>
                <ElInput v-else-if="row.raw_bar_length_m && !isWeightLine(row)" :model-value="effectivePurchaseQuantity(row)" aria-label="实际采购数量（米）" inputmode="decimal" maxlength="19" :disabled="!canWriteLines" placeholder="填写米数" @update:model-value="setPipePurchaseMeters(row, $event)"><template #append>米</template></ElInput>
                <ElInput v-else v-model="row.actual_purchase_quantity" :aria-label="isWeightLine(row) ? '实际采购重量（kg）' : '实际采购数量'" inputmode="decimal" maxlength="24" :disabled="!canWriteLines" :placeholder="isBatchMode ? '本批采购数量' : defaultPurchaseQuantity(row) || '请输入'"><template #append>{{ isWeightLine(row) ? 'kg' : row.source_unit_text || '单位未识别' }}</template></ElInput>
                <ElPopover v-if="isPipePurchaseLine(row) && isWeightPipeLine(row)" trigger="click" placement="top" :width="380" :teleported="true" :disabled="!canWriteLines">
                  <template #reference><ElButton link type="primary" :disabled="!canWriteLines" aria-label="填写管材单根参数">单根参数</ElButton></template>
                  <div class="pipe-quantity-editor erp-table-editor">
                    <label><span>每根长度</span><ElInput v-model="row.raw_bar_length_m" aria-label="采购每根长度（米）" inputmode="decimal" maxlength="17" :disabled="!canWriteLines"><template #append>米/根</template></ElInput></label>
                    <label><span>每根标准重量</span><ElInput v-model="row.raw_bar_weight_kg" aria-label="采购每根标准重量（kg）" inputmode="decimal" maxlength="19" :disabled="!canWriteLines"><template #append>kg/根</template></ElInput></label>
                  </div>
                </ElPopover>
              </div>
              </PurchaseGridCell>
            </template>
          </ElTableColumn>
           <ElTableColumn label="采购单价" width="164">
            <template #default="{ row, $index }"><PurchaseGridCell><div class="line-field line-field--price" data-grid-field :data-grid-row="$index" data-grid-column="3" data-testid="purchase-line-unit-price" @keydown.capture="handleGridNavigation($event, $index, 3)"><PurchaseSetPriceCell :line="row" :unit="purchasePriceUnit(row)" :allow-set="isBatchMode && Boolean(row.purchase_group_line_id)" :disabled="!canWriteLines" @input="row.unit_price = $event" @edit-set="editingSetId = row.purchase_group_line_id" /></div></PurchaseGridCell></template>
          </ElTableColumn>
          <ElTableColumn label="采购金额（元）" min-width="173" align="left">
            <template #default="{ row }"><PurchaseGridCell><div class="amount-preview">{{ lineAmount(row) }}</div></PurchaseGridCell></template>
          </ElTableColumn>
          <template #empty>
            <div class="detail-empty">
              <div>!</div>
              <strong v-if="isBatchMode && (lastSupplierBatch || savedSupplierOrders.length)">当前列表已买足</strong>
              <template v-else>
                <strong>{{ isSampleSource ? '暂无可采购的样品需求' : selectedTaskId ? selectedBomId ? '所选 BOM 暂无明细' : '请选择本次采购的产品 BOM' : '请先选择采购来源' }}</strong>
                <p>{{ sourceError || '选择生产订单或打样单后加载对应采购需求' }}</p>
              </template>
            </div>
          </template>
        </ElTable>
        <p v-if="isSampleSource && source?.notes" class="sample-warehouse-note">仓库备注：{{ source.notes }}</p>
         <PurchaseGridCell><footer><span>{{ isPreviewMode ? `已找到 ${lines.length} 项采购需求 · 当前仅预览` : lines.length ? `已载入 ${lines.length} 项 · 已完整填写 ${completeLineCount} 项` : '请先选择采购来源' }}</span><span>{{ pipePricingText }}</span></footer></PurchaseGridCell>
      </section>

      <section v-if="isDetailStep" class="summary-card">
        <PurchaseGridCell><div class="summary-counts"><span>{{ isPreviewMode ? '采购需求预览' : '采购明细' }} <strong>{{ selectedLines.length }}</strong> 项</span><span>·</span><span>已选供应商 <strong>{{ selectedSupplierCount }}</strong> 家</span></div></PurchaseGridCell>
        <div class="summary-actions">
          <PurchaseGridCell><div class="summary-total"><span>采购总金额</span><strong>{{ totalAmount === '待计算' ? totalAmount : `¥ ${totalAmount}` }}</strong></div></PurchaseGridCell>
          <ElDropdown v-if="canSubmitSupplierBatch" trigger="click" placement="top-end" @command="openSupplierBatchReview">
            <ElButton plain type="primary" data-testid="purchase-submit-supplier" :loading="saving && !!pendingSupplierBatch" :disabled="!canWriteLines || sourceLoading || !supplierBatchOptions.length">
              按供应商保存<ElIcon><ArrowDown /></ElIcon>
            </ElButton>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem v-for="supplier in supplierBatchOptions" :key="supplier.id" :command="supplier.id">
                  {{ supplier.name }} · {{ supplier.count }} 项
                </ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
          <ElButton type="primary" :loading="saving && !pendingSupplierBatch" :disabled="saving || !!pendingSupplierBatch" data-testid="purchase-next" @click="confirmPurchase">{{ packagingPageConfirmed ? '查看本批供应商采购表' : '下一步：确认采购' }}<img class="purchase-icon" :src="rightIcon" alt="" /></ElButton>
        </div>
      </section>
      <ElAlert v-if="isBatchMode && lastSupplierBatch" class="supplier-submit-result" type="success" :closable="false" show-icon
        :title="`${isMultiTask ? '本页' : `第 ${lastSupplierBatch.number} 批`}已保存 · ${lastSupplierBatch.supplierName} · ${lastSupplierBatch.lineCount} 项 · 待统一确认`" />
    </template>
    <AppWindowDialog v-if="supplierBatchReview" :model-value="true" title="保存供应商采购" :width="1000"
      :min-width="290" :minimizable="false" :close-on-click-modal="false"
      @update:model-value="value => { if (!value) supplierBatchReview = null }">
      <div class="supplier-review-heading">
        <strong>{{ supplierBatchReview.supplierName }}</strong>
        <span>单价留空或填 0 的物料会跳过</span>
      </div>
      <div class="supplier-review-scroll">
        <table class="supplier-review-table">
          <thead>
            <tr><th v-if="isPackaging" scope="col">生产任务单号</th><th scope="col">品名</th><th scope="col">规格</th><th scope="col">采购数量</th><th scope="col">单价</th><th scope="col">采购交期</th></tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in supplierBatchReview.lines" :key="row.purchase_group_line_id">
              <td v-if="isPackaging">{{ packagingLineGroup.get(row.purchase_group_line_id!)?.production_task_number_snapshot }}</td>
              <td class="supplier-review-name">{{ materialTitle(row) }}</td>
              <td>{{ materialSpecificationValue(row) }}</td>
              <td class="supplier-review-quantity">{{ effectivePurchaseQuantity(row) }} {{ isWeightLine(row) ? 'kg' : row.source_unit_text }}</td>
              <td>
                <span v-if="row.set_pricing">{{ setPriceText(row) }}</span>
                <ElInput v-else v-model="row.unit_price" inputmode="decimal" maxlength="24" placeholder="填写单价"
                  :aria-label="`第 ${index + 1} 行单价`" @input="supplierBatchReview.error = ''">
                  <template #suffix>{{ purchasePriceUnit(row) }}</template>
                </ElInput>
              </td>
              <td>
                <ElDatePicker :model-value="row.delivery_date" type="date" :prefix-icon="CalendarIcon"
                  format="YYYY-MM-DD" value-format="YYYY-MM-DD" :disabled-date="disablePastDeliveryDate"
                  placeholder="选择交期" :aria-label="`第 ${index + 1} 行采购交期`"
                  @update:model-value="updateSupplierReviewDate(row, $event)" />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="supplierBatchReview.error" class="supplier-review-error" role="alert">{{ supplierBatchReview.error }}</p>
      <template #footer>
        <div class="supplier-review-footer">
          <span>本次采购 {{ reviewedPurchaseLines.length }} 项 <strong>¥ {{ reviewedPurchaseTotal }}</strong></span>
          <ElButton @click="supplierBatchReview = null">取消</ElButton>
          <ElButton type="primary" @click="confirmSupplierBatch">保存待确认</ElButton>
        </div>
      </template>
    </AppWindowDialog>
    <AppWindowDialog v-if="finalBatchReview" :model-value="true" title="统一确认采购" :width="840"
      :min-width="290" :minimizable="false" :show-close="!saving && !finalBatchReview.uncertain"
      :close-on-click-modal="false" :close-on-press-escape="!saving && !finalBatchReview.uncertain"
      @update:model-value="value => { if (!value && !saving && !finalBatchReview?.uncertain) finalBatchReview = null }">
      <div class="supplier-review-heading"><strong>{{ isMultiTask ? '本页包材采购' : `第 ${displayedBatchNumber} 批` }}</strong><span>确认后生成各供应商的采购表草稿</span></div>
      <div class="supplier-review-scroll">
        <table class="supplier-review-table">
          <thead><tr><th v-if="isPackaging" scope="col">生产任务单号</th><th scope="col">采购单</th><th scope="col">供应商</th><th scope="col">明细</th><th scope="col">金额</th></tr></thead>
          <tbody>
            <tr v-for="order in savedSupplierOrders" :key="order.id">
              <td v-if="isPackaging">{{ packagingDraftGroup.get(order.id)?.production_task_number_snapshot }}</td>
              <td>{{ order.order_number }}</td><td>{{ order.suppliers.join('、') || '—' }}</td>
              <td class="supplier-review-quantity">{{ order.line_count }} 项</td><td>{{ formatMoney(order.total_amount) }}</td>
            </tr>
            <tr v-if="finalBatchReview.additionalSummary && finalBatchReview.payload.additional">
              <td v-if="isPackaging">{{ [...new Set(finalBatchReview.payload.additional.lines.map(line => packagingLineGroup.get(line.purchase_group_line_id)?.production_task_number_snapshot))].join('、') }}</td>
              <td>本页新增填写</td><td>{{ finalBatchReview.additionalSummary.suppliers || '—' }}</td>
              <td class="supplier-review-quantity">{{ finalBatchReview.payload.additional.lines.length }} 项</td>
              <td>{{ formatMoney(finalBatchReview.additionalSummary.amount) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="finalBatchReview.error" class="supplier-review-error" role="alert">{{ finalBatchReview.error }}</p>
      <template #footer>
        <div class="supplier-review-footer">
          <ElButton :disabled="saving || finalBatchReview.uncertain" @click="finalBatchReview = null">返回修改</ElButton>
          <ElButton type="primary" :loading="saving" @click="confirmSavedSupplierOrders">确认采购</ElButton>
        </div>
      </template>
    </AppWindowDialog>
    <PurchaseSetPricingDialog v-if="setSource" :key="editingSetId" :source="setSource" :lines="setCandidates"
      :suppliers="options.suppliers" :default-quantity="orderSetQuantity(isPackaging ? packagingLineGroup.get(editingSetId) ?? null : group)" @apply="saveSet" @close="editingSetId = ''" />
  </section>
</template>

<style scoped lang="scss">
@use "@/styles/crm/tokens" as crm;
@use '@/styles/theme/detail' as detail;
.purchase-form-page {
  box-sizing: border-box; width: 100%; min-width: 0; height: auto; min-height: 0;
  display: flex; flex-direction: column; padding: 0; overflow: visible;
  color: crm.$crm-text-primary; background: transparent; font: 14px/1.5 crm.$crm-font-body;
  --el-color-primary: #{crm.$crm-primary}; --el-color-primary-light-3: #{crm.$crm-primary-light-3};
  --el-color-primary-light-9: #{crm.$crm-color-selected}; --el-color-primary-dark-2: #{crm.$crm-primary-pressed};
  --el-text-color-primary: #{crm.$crm-text-primary}; --el-text-color-regular: #{crm.$crm-text-regular};
  --el-text-color-placeholder: #{crm.$crm-text-muted}; --el-text-color-disabled: #{crm.$crm-text-disabled};
  --el-border-color: #{crm.$crm-border-default}; --el-border-color-light: #{crm.$crm-border-subtle};
  --el-fill-color-blank: #{crm.$crm-color-surface}; --el-fill-color-light: #{crm.$crm-color-subtle};
  --el-border-radius-base: 5px;
}
.purchase-icon { width: 16px; height: 16px; flex: none; }
.batch-type-field { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; margin-bottom: 14px; font-size: 13px; }
.purchase-form-page :deep(.el-button > span) { display: inline-flex; align-items: center; gap: 10px; }
.purchase-form-page :deep(.el-button) { border-radius: 5px; }
.page-heading { flex: none; min-height: 50px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.page-heading > div:first-child { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; min-width: 0; }
.page-heading h1 { margin: 0; white-space: nowrap; font: 700 38px/50px crm.$crm-font-display; letter-spacing: -1px; }
.page-heading p { margin: 8px 0 0; color: crm.$crm-text-secondary; font-size: 13px; white-space: nowrap; }
.production-task-number { font-size: 20px; line-height: 28px; font-weight: 700; }
.page-action-panel { display: flex; flex-direction: column; align-items: flex-end; position: relative; }
.page-actions { display: flex; gap: 18px; }
.page-actions :deep(.el-button) { width: 128px; height: 42px; margin: 0; }
.page-actions :deep(.el-button--primary) { width: 164px; white-space: nowrap; }
.purchase-form-page > :deep(.el-alert) { flex: none; margin-bottom: 10px; }
.task-card, .detail-card { @include detail.surface; }
.task-card { flex: 0 0 292px; min-height: 0; margin-bottom: 14px; padding: 10px 17px 12px; overflow: hidden; }
.task-card > header { height: 33px; }
.task-card h2, .detail-card h2 { margin: 0; font-size: 20px; line-height: 28px; font-weight: 700; }
.task-selector-row { display: flex; align-items: center; gap: 14px; }
.task-selector-row > :deep(.el-select) { width: auto; }
.task-selector-row > :deep(.source-type-filter) { flex: 0 0 140px; width: 140px; }
.task-selector-row > :deep(.task-source-filter) { flex: 0 1 420px; width: 420px; min-width: 260px; }
.task-selector-row :deep(.el-select__wrapper) { height: 32px; min-height: 32px; border-radius: var(--erp-radius-control); }
.task-selector-row > :deep(.el-button) { width: 110px; height: 42px; margin: 0; }
.task-select-option { width: 100%; min-width: 0; display: grid; grid-template-columns: 170px 100px minmax(0,1fr) 64px; align-items: center; gap: 16px; }
.task-select-option strong, .task-source-description { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-select-option small { color: crm.$crm-text-secondary; }
.source-option-heading { color: crm.$crm-text-secondary; font-size: 12px; }
:global(.purchase-source-popper) { width: min(988px, calc(100vw - 48px)); }
.task-source-status.el-tag { box-sizing: border-box; width: 64px; min-width: 64px; height: 24px; padding: 0 8px; border: 0; border-radius: 999px; color: var(--erp-color-text-inverse); background: var(--erp-tag-info-background); font: 500 12px/18px 'Noto Sans SC Variable', crm.$crm-font-body; justify-self: end; }
.task-source-status.el-tag--success { background: var(--erp-tag-success-background); }
.task-source-status.el-tag--warning { background: var(--erp-tag-warning-background); }
.purchase-source-tag.el-tag { box-sizing: border-box; width: 72px; min-width: 72px; height: 24px; padding: 0 8px; border: 0; border-radius: 999px; color: var(--erp-color-text-inverse); background: var(--erp-tag-info-background); font: 500 12px/18px 'Noto Sans SC Variable', crm.$crm-font-body; }
.purchase-source-tag.el-tag.is-sample { background: var(--erp-tag-brand-background); }
.is-sample-source .task-card { flex-basis: 236px; }
.sample-source-summary { border-top: 1px solid crm.$crm-border-subtle; margin-top: 12px; padding-top: 18px; }
.sample-source-summary strong { font-size: 16px; font-weight: 500; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sample-source-summary p { margin: 8px 0 0; color: crm.$crm-text-secondary; }
.sample-source-summary .is-blocked { color: crm.$crm-warning; }
.sample-warehouse-note { flex: none; margin: 0; padding: 12px 18px; border-top: 1px solid crm.$crm-border-subtle; color: crm.$crm-text-secondary; }
.purchase-form-page.is-sample-source .purchase-lines :deep(.el-table__body td.el-table__cell) { height: 40px; }
.is-sample-source .detail-card:not(.is-fullscreen) .purchase-lines { flex: none; max-height: calc(100% - 156px); }
.is-sample-source .detail-card > footer { margin-top: auto; }
.selected-order-overview { display: flex; align-items: center; gap: 26px; height: 36px; margin: 0; }
.selected-order-overview > div { display: flex; gap: 14px; min-width: 0; }
.selected-order-overview dt, .selected-order-overview dd { margin: 0; white-space: nowrap; }
.selected-order-overview dd { max-width: 400px; overflow: hidden; text-overflow: ellipsis; }
.selected-product-list { margin: 0 -4px; max-height: 128px; overflow-y: auto; border-radius: 5px; }
.selected-product-row { display: grid; grid-template-columns: 48px minmax(90px, 1fr) minmax(80px, .85fr) minmax(140px, 1.5fr) minmax(110px, 1.15fr) minmax(80px, .85fr) minmax(64px, .7fr) 106px 82px; align-items: center; min-height: 43px; }
.selected-product-row > span { min-width: 0; padding: 0 8px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.selected-product-row--heading { min-height: 42px; background: crm.$crm-color-subtle; color: crm.$crm-text-secondary; font-size: 13px; }
.selected-product-row--heading > span:first-child { text-align: center; }
.selected-product-row--option { border-top: 1px solid crm.$crm-border-subtle; cursor: pointer; }
.selected-product-row--option.is-selected { background: var(--erp-color-selected); }
.selected-product-row--option:hover { background: crm.$crm-color-row-hover; }
.selected-product-row--option:focus-visible { outline: 2px solid crm.$crm-primary; outline-offset: -2px; }
.selected-product-row--option.is-unavailable { cursor: not-allowed; color: crm.$crm-text-disabled; }
.selected-product-row > .product-checkbox { position: relative; justify-self: center; width: 16px; height: 16px; padding: 0; border: 1px solid crm.$crm-text-muted; border-radius: 3px; background: crm.$crm-color-surface; }
.selected-product-row.is-selected > .product-checkbox { background: crm.$crm-primary; border-color: crm.$crm-primary; }
.selected-product-row.is-selected > .product-checkbox::after { content: ''; position: absolute; left: 4px; top: 1px; width: 5px; height: 9px; border: solid white; border-width: 0 2px 2px 0; transform: rotate(45deg); }
.bom-status { box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; width: 64px; height: 24px; padding: 0 8px; border-radius: 999px; background: crm.$crm-info; color: var(--erp-color-text-inverse); font: 500 12px/18px 'Noto Sans SC Variable', crm.$crm-font-body; }
.bom-status.is-ready { color: var(--erp-color-text-inverse); background: crm.$crm-success; }
.product-selection-caption { margin: 8px 0 0; color: crm.$crm-text-secondary; font-size: 13px; line-height: 22px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.product-selection-caption.is-blocked { color: crm.$crm-warning; }
.task-selector-hint { display: grid; min-height: 150px; place-content: center; margin: 0; color: crm.$crm-text-muted; }
.detail-card { flex: none; min-height: 220px; display: flex; flex-direction: column; overflow: hidden; margin-bottom: 14px; }
.detail-card:not(.is-fullscreen) .purchase-lines { flex: none; }
.is-batch-page .detail-card:not(.is-fullscreen) { flex: 1; min-height: 0; }
.is-batch-page .detail-card:not(.is-fullscreen) .purchase-lines { flex: 1 1 0; }
.is-batch-page .purchase-lines :deep(.el-scrollbar__wrap) { overscroll-behavior-y: contain; }
.detail-card.is-fullscreen { position: fixed; z-index: 1900; inset: 0; height: 100dvh; width: 100%; border-radius: 0; }
.detail-card > header { display: flex; flex: 0 0 auto; min-height: 52px; flex-wrap: wrap; align-items: center; justify-content: space-between; padding: 8px 12px; gap: 10px; }
.detail-card > header > div { display: flex; align-items: center; gap: 12px; }
.detail-card > header > div > span { color: crm.$crm-text-secondary; font-size: 13px; }
.detail-title-context { min-width: 0; }
.detail-title-context h2 { flex: none; white-space: nowrap; }
.selected-product-context { min-width: 0; display: flex; align-items: center; gap: 10px; padding-left: 20px; border-left: 1px solid crm.$crm-border-default; white-space: nowrap; }
.selected-product-context > span { color: crm.$crm-text-secondary; font-size: 13px; }
.selected-product-context > strong { max-width: 130px; overflow: hidden; text-overflow: ellipsis; font-size: 14px; font-weight: 500; }
.selected-product-context > small { max-width: 180px; overflow: hidden; text-overflow: ellipsis; color: crm.$crm-text-secondary; font-size: 12px; }
.detail-header-actions { margin-left: auto; flex-wrap: wrap; gap: 10px !important; }
.detail-header-actions :deep(.el-button) { width: 92px; height: 42px; margin: 0; }
.bulk-field { display: flex; align-items: center; gap: 8px; white-space: nowrap; font-size: 13px; }
.bulk-field--category :deep(.el-select) { width: 150px; }
.bulk-field--supplier :deep(.el-select) { width: 218px; }
.bulk-field--date :deep(.el-date-editor) { width: 220px; }
.bulk-field :deep(.el-select__wrapper), .bulk-field :deep(.el-input__wrapper) { height: 32px; min-height: 32px; border-radius: var(--erp-radius-control); }
.purchase-lines { flex: 1; width: 100%; min-height: 0; --el-table-border-color: #{crm.$crm-border-subtle}; --el-table-tr-bg-color: #{crm.$crm-color-surface}; --el-table-bg-color: #{crm.$crm-color-surface}; --el-table-header-bg-color: #{crm.$crm-color-subtle}; --el-table-row-hover-bg-color: #{crm.$crm-color-row-hover}; }
.purchase-form-page .purchase-lines :deep(.el-table__header tr),
.purchase-form-page .purchase-lines :deep(.el-table__header th.el-table__cell) { height: 40px !important; }
.purchase-form-page .purchase-lines :deep(.el-table__header th.el-table__cell) { padding: 0 !important; color: var(--erp-table-header-text); background: var(--erp-table-header-fill); border-right: 1px solid var(--erp-table-grid); font-size: 11px; font-weight: 400; }
.purchase-form-page .purchase-lines :deep(.el-table__body tr),
.purchase-form-page .purchase-lines :deep(.el-table__body td.el-table__cell) { height: 40px !important; }
.purchase-form-page .purchase-lines :deep(.el-table__body td.el-table__cell) { padding: 0 !important; border-right: 1px solid var(--erp-table-grid); color: var(--erp-table-text); }
.purchase-form-page .purchase-lines :deep(.el-table__header th:first-child),
.purchase-form-page .purchase-lines :deep(.el-table__body td:first-child) { border-left: 0; }
.purchase-form-page .purchase-lines :deep(.cell) { padding: 0 16px; font-size: 12px; line-height: 18px; }
.purchase-form-page .purchase-lines :deep(th:first-child .cell),
.purchase-form-page .purchase-lines :deep(td:first-child .cell) { padding: 0 8px !important; }
.purchase-form-page .purchase-lines :deep(th .cell) { font-size: 11px; line-height: 16px; white-space: nowrap; }
.purchase-lines :deep(.el-table__inner-wrapper::before), .purchase-lines :deep(.el-table__inner-wrapper::after) { display: none; }
.purchase-form-page .purchase-lines :deep(.el-table__header th.el-table__cell:last-child),
.purchase-form-page .purchase-lines :deep(.el-table__body td.el-table__cell:last-child) { border-right: 0; }
.purchase-lines :deep(.el-table__body tr:last-child td) { border-bottom: 0; }
.line-field { display: flex; align-items: center; width: 100%; height: 39px; }
.line-field :deep(.el-select), .line-field :deep(.el-input), .line-field :deep(.el-date-editor) { width: 100%; }
.line-field :deep(.el-select__wrapper), .line-field :deep(.el-input__wrapper) { height: 32px; min-height: 32px; border-radius: var(--erp-radius-control); font-size: 12px; }
.line-field :deep(.el-input__wrapper) { padding: 1px 13px; }
.line-field :deep(.el-input__prefix) { margin-right: 4px; }
.line-field--quantity :deep(.el-input-group__append) { box-sizing: border-box; flex: 0 0 64px; width: 64px; padding: 0; font-size: 12px; }
.line-field--price :deep(.el-input__wrapper) { padding: 1px 8px; }
.line-field--price :deep(.el-input-group__append) { padding: 0 6px; font-size: 12px; white-space: nowrap; }
:global(.purchase-detail-popper) { z-index: 4000 !important; }
.material-cell, .quantity-cell { display: flex; min-width: 0; }
.material-cell { flex-direction: column; }
.material-cell strong, .quantity-cell strong { font-weight: 500; font-size: 13px; }
.quantity-cell small { color: crm.$crm-text-secondary; font-size: 12px; line-height: 19px; }
.material-cell > * { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.material-detail { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: crm.$crm-text-secondary; font-size: 12px; }
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: var(--erp-color-text-secondary); min-width: 42px; }
.quantity-cell { flex-direction: row; align-items: center; justify-content: flex-end; gap: 4px; white-space: nowrap; }
.quantity-cell--batch { flex-direction: column; align-items: flex-end; gap: 0; white-space: normal; }
.amount-preview { font-size: 14px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.detail-card > footer { flex: 0 0 48px; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 0 18px; color: crm.$crm-text-secondary; font-size: 13px; border-top: 1px solid crm.$crm-border-subtle; }
.detail-empty { min-height: 230px; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 24px; color: crm.$crm-text-secondary; }
.detail-empty > div { display: none; }
.detail-empty strong { font-size: 18px; color: crm.$crm-text-primary; }
.detail-empty p { max-width: 900px; line-height: 24px; }
.summary-card { @include detail.surface; flex: none; min-height: 72px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 16px; }
.summary-counts, .summary-actions { display: flex; align-items: center; }
.summary-counts { gap: 14px; font-size: 16px; font-weight: 500; white-space: nowrap; }
.summary-counts strong { color: crm.$crm-primary; margin: 0 6px; font-weight: 500; }
.summary-actions { flex-wrap: wrap; gap: 14px; }
.summary-total { display: flex; align-items: center; gap: 18px; padding-left: 40px; border-left: 1px solid crm.$crm-border-default; white-space: nowrap; }
.summary-total strong { min-width: 170px; font-size: 28px; color: crm.$crm-primary; font-weight: 700; }
.summary-actions > :deep(.el-button) { width: 220px; height: 42px; }
.purchase-form-page > .supplier-submit-result { margin: 10px 0 0; }
.supplier-review-heading,
.supplier-review-footer { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 16px; }
.supplier-review-heading { margin-bottom: 12px; justify-content: space-between; }
.supplier-review-heading strong { font-size: 16px; font-weight: 600; color: crm.$crm-text-primary; }
.supplier-review-heading span { font-size: 13px; color: crm.$crm-text-secondary; }
.supplier-review-scroll { max-height: min(46vh, 460px); overflow: auto; border: 1px solid crm.$crm-border-subtle; border-radius: 6px; }
.supplier-review-table { table-layout: fixed; width: 100%; min-width: 740px; border-spacing: 0; font-size: 14px; }
.supplier-review-table th,
.supplier-review-table td { padding: 8px 12px; text-align: left; }
.supplier-review-table th { position: sticky; top: 0; z-index: 1; background: crm.$crm-color-subtle; color: crm.$crm-text-secondary; font-weight: 600; border-bottom: 1px solid crm.$crm-border-subtle; }
.supplier-review-table th:nth-child(1) { width: 26%; }
.supplier-review-table th:nth-child(2) { width: 20%; }
.supplier-review-table th:nth-child(3) { width: 13%; text-align: right; }
.supplier-review-table th:nth-child(4) { width: 20%; }
.supplier-review-table td { overflow-wrap: anywhere; }
.supplier-review-table tr:not(:last-child) td { border-bottom: 1px solid crm.$crm-border-subtle; }
.supplier-review-table .supplier-review-name { font-weight: 600; }
.supplier-review-table .supplier-review-quantity { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.supplier-review-table :deep(.el-date-editor.el-input) { width: 100%; }
.supplier-review-table :deep(.el-input__suffix) { white-space: nowrap; }
.supplier-review-error { margin: 10px 0 0; color: crm.$crm-danger; }
.supplier-review-footer { width: 100%; justify-content: flex-end; gap: 8px 12px; }
.supplier-review-footer > span { margin-right: auto; color: crm.$crm-text-secondary; }
.supplier-review-footer strong { margin-left: 12px; font-size: 17px; color: crm.$crm-text-primary; font-variant-numeric: tabular-nums; }
.supplier-review-footer :deep(.el-button + .el-button) { margin-left: 0; }
.state-page { display: grid; min-height: 520px; place-content: center; text-align: center; }
.state-page p { color: crm.$crm-text-secondary; }

@media (max-width: 980px) {
  .detail-card > header { flex: 0 0 auto; min-height: 112px; flex-direction: column; align-items: stretch; justify-content: center; gap: 10px; padding-top: 8px; padding-bottom: 8px; }
  .detail-title-context { flex: none; height: 30px; }
  .detail-header-actions { flex: none; justify-content: flex-end; margin-left: 0; }
}


.pipe-meters { white-space: nowrap; }
.pipe-quantity-trigger { width: 100%; height: 32px; padding: 0 8px; overflow: hidden; border: 1px solid var(--erp-input-border); border-radius: 5px; color: var(--erp-input-text); background: var(--erp-color-surface); font: inherit; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.pipe-quantity-trigger:hover:not(:disabled) { border-color: var(--erp-input-hover-border); }
.pipe-quantity-trigger:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.pipe-quantity-trigger:disabled { color: var(--erp-input-disabled-text); background: var(--erp-input-disabled-background); cursor: not-allowed; }
.pipe-quantity-editor { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.pipe-quantity-editor label { min-width: 0; }
.pipe-quantity-editor label > span { display: block; margin-bottom: 6px; color: var(--erp-color-text-secondary); font-size: 12px; }
.pipe-quantity-editor :deep(.el-input__wrapper) { height: 32px; min-height: 32px; padding: 0 10px; }
.pipe-quantity-editor :deep(.el-input-group__append) { padding: 0 8px; font-size: 12px; }
.pipe-order-quantity { display: flex; flex-direction: column; align-items: stretch; height: auto; min-width: 0; width: 100%; gap: 4px; padding: 6px 0; white-space: normal; }
.pipe-order-quantity small { display: block; font-size: 11px; line-height: 16px; overflow-wrap: anywhere; }
:deep(td .cell:has(.pipe-order-quantity)) { display: block !important; white-space: normal !important; text-overflow: clip; }
</style>
