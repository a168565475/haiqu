<script setup lang="ts">
import { pipeMeters, pipeRootError } from '@/utils/pipeQuantities'
import { computed, h, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import backIcon from '@/assets/procurement/create-back.svg'
import refreshIcon from '@/assets/procurement/create-refresh.svg'
import calendarIcon from '@/assets/procurement/create-calendar.svg'
import expandIcon from '@/assets/procurement/create-expand.svg'
import rightIcon from '@/assets/procurement/create-right.svg'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import {
  createPurchaseOrder,
  fetchPurchaseOrderOptions,
  fetchPurchaseOrderSource,
  fetchSamplePurchaseOrderSource,
} from '@/api/purchaseOrders'
import { useAuthStore } from '@/stores/auth'
import type {
  PurchaseOrderInput,
  PurchaseOrderOptions,
  PurchaseOrderProductSource,
  PurchaseOrderProductionTaskOption,
  PurchaseOrderSource,
  PurchaseOrderSourceLine,
} from '@/types/purchaseOrder'
import { materialAttributeFields, materialSpecificationValue } from '@/utils/materialAttributes'

interface PurchaseLineDraft extends PurchaseOrderSourceLine {
  supplier_id: string | null
  delivery_date: string
  actual_bar_count: string
  actual_purchase_quantity: string
  unit_price: string
}

const CalendarIcon = () => h('img', { src: calendarIcon, width: 16, height: 16, alt: '' })
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const isSuperuser = computed(() => authStore.user?.is_superuser === true)
const canAdd = computed(() => isSuperuser.value || authStore.hasPermission('procurement.add_purchaseorder'))

const options = ref<PurchaseOrderOptions>({
  production_tasks: [], suppliers: [], currencies: [], default_currency_id: null,
})
const source = ref<PurchaseOrderSource | null>(null)
const lines = ref<PurchaseLineDraft[]>([])
const selectedTaskId = ref('')
const selectedBomId = ref('')
const sourceTypeFilter = ref<'ALL' | 'PRODUCTION' | 'SAMPLE'>('ALL')
const detailFullscreen = ref(false)
const bulkSupplierId = ref<string | null>(null)
const bulkDeliveryDate = ref('')
const optionsLoading = ref(true)
const sourceLoading = ref(false)
const saving = ref(false)
const loadError = ref('')
const sourceError = ref('')
const formPage = ref<HTMLElement | null>(null)
const hoveredLineKey = ref('')
let sourceRequestId = 0

const form = reactive({
  currencyId: '',
  isMailed: null as boolean | null,
})

const sourceOptions = computed<PurchaseOrderProductionTaskOption[]>(() => [
  ...options.value.production_tasks.map(item => ({ ...item, source_type: 'PRODUCTION' as const, source_number: item.task_number })),
  ...(options.value.sample_requests || []).map(item => ({ ...item, source_id: item.id, id: `sample:${item.id}`, task_number: item.source_number, order_number: '' })),
].sort((left, right) => Number(right.can_create) - Number(left.can_create)))
const visibleSourceOptions = computed(() => sourceTypeFilter.value === 'ALL'
  ? sourceOptions.value
  : sourceOptions.value.filter(item => item.source_type === sourceTypeFilter.value))
const isDetailStep = computed(() => route.name === 'purchase-order-create-details')
const isSampleSource = computed(() => selectedTask.value?.source_type === 'SAMPLE')
const sourceTypeLabel = computed(() => isSampleSource.value ? '打样单' : '生产订单')
const selectedTask = computed(() => sourceOptions.value.find((item) => item.id === selectedTaskId.value) || null)
const selectedProducts = computed(() => source.value?.production_task?.products || [])
const selectedBom = computed(() => source.value?.bom_options.find((item) => item.bom_id === selectedBomId.value) || null)
const selectedProduct = computed(() => selectedProducts.value.find((item) => item.id === selectedBom.value?.product_line_id) || null)
const selectedSupplierCount = computed(() => new Set(lines.value.map((line) => line.supplier_id).filter(Boolean)).size)
const completeLineCount = computed(() => lines.value.filter(isLineComplete).length)
const isPreviewMode = computed(() => Boolean(source.value && !source.value.can_create && lines.value.length))
const detailTableHeight = computed(() => detailFullscreen.value ? 'calc(100dvh - 108px)'
  : isSampleSource.value && !lines.value.some(line => isPipePurchaseLine(line)) && lines.value.length <= 4 ? `${40 + lines.value.length * 40}px` : '100%')
const canContinueToDetails = computed(() => Boolean(
  source.value?.can_create
  && lines.value.length
  && selectedTaskId.value
  && (isSampleSource.value || selectedBomId.value),
))

function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as {
    response?: {
      status?: number
      data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string }
    }
  })?.response
  const firstFieldError = response?.data?.error?.field_errors
    ? Object.values(response.data.error.field_errors).flat()[0]
    : ''
  if (response?.status === 401) return '登录状态已失效，请刷新页面或重新登录。'
  if (response?.status === 403) return '当前账号没有新建采购订单的权限。'
  if (response?.status === 409) return response.data?.error?.message || response.data?.detail || '采购来源已变化，请重新读取采购需求。'
  return firstFieldError || response?.data?.error?.message || response?.data?.detail || fallback
}

function showActionError(message: string): void {
  ElMessage.warning(message)
}

function resetSource(): void {
  source.value = null
  sourceLoading.value = false
  lines.value = []
  selectedBomId.value = ''
  bulkSupplierId.value = null
  bulkDeliveryDate.value = ''
  sourceError.value = ''
}

function applySource(result: PurchaseOrderSource): void {
  source.value = result
  selectedBomId.value = result.selected_bom_id || ''
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
  sourceError.value = result.requires_bom_selection
    ? '该生产订单包含多个产品，请先选择本次要采购的 BOM。'
    : (!result.can_create ? result.blockers?.[0]?.message || '当前采购来源暂无可采购的明细。' : '')
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
    if (isDetailStep.value) {
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
    applySource(result)
  } catch (error) {
    if (currentRequestId !== sourceRequestId) return
    const message = apiErrorMessage(error, '采购来源读取失败，请稍后重试。')
    sourceError.value = message
    showActionError(message)
  } finally {
    if (currentRequestId === sourceRequestId) sourceLoading.value = false
  }
}

async function handleBomSelection(bomId: string): Promise<void> {
  if (!selectedTaskId.value || !bomId) return
  const currentRequestId = ++sourceRequestId
  sourceLoading.value = true
  sourceError.value = ''
  lines.value = []
  try {
    const result = await fetchPurchaseOrderSource(selectedTaskId.value, bomId)
    if (currentRequestId !== sourceRequestId) return
    applySource(result)
  } catch (error) {
    if (currentRequestId !== sourceRequestId) return
    selectedBomId.value = ''
    const message = apiErrorMessage(error, '所选 BOM 读取失败，请稍后重试。')
    sourceError.value = message
    showActionError(message)
  } finally {
    if (currentRequestId === sourceRequestId) sourceLoading.value = false
  }
}

function productBomOption(productId: string): PurchaseOrderSource['bom_options'][number] | null {
  return source.value?.bom_options.find((item) => item.product_line_id === productId) || null
}

async function handleProductSelection(product: PurchaseOrderProductSource): Promise<void> {
  if (sourceLoading.value) return
  const option = productBomOption(product.id)
  if (!option?.bom_id) {
    ElMessage.warning('该产品尚未建立 BOM，暂时不能选择。')
    return
  }
  if (option.bom_id === selectedBomId.value) return
  await handleBomSelection(option.bom_id)
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

function materialDetail(line: PurchaseLineDraft): string {
  return [...new Set([line.material, line.raw_material, line.specification, ...(isSampleSource.value ? [line.product_color] : [])].filter(Boolean))].join(' · ') || '规格未填写'
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
 * 样品管材按总米数提出需求，采购员在采购单中填写采购根数和每根长度。
 * 生产订单仍沿用来源快照中的 raw_bar_length_m，不进入这个分支。
 */
function isPipePurchaseLine(line: PurchaseLineDraft): boolean {
  return isSampleSource.value && line.section_type === 'PROFILE'
}

function productColorText(product: PurchaseOrderProductSource): string {
  return [product.color_card, product.color_name, product.color_code]
    .map((value) => value.trim())
    .filter((value) => value && value !== '/')
    .join(' · ') || '—'
}

function disablePastDeliveryDate(date: Date): boolean {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return date.getTime() < today.getTime()
}

function applyBulkSupplier(value: string | null): void {
  for (const line of lines.value) line.supplier_id = value || null
}

function refreshBulkSupplier(): void {
  if (!lines.value.length) {
    bulkSupplierId.value = null
    return
  }
  const firstValue = lines.value[0].supplier_id
  bulkSupplierId.value = lines.value.every((line) => line.supplier_id === firstValue)
    ? firstValue
    : null
}

function applyBulkDeliveryDate(value: string | null): void {
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

async function focusGridField(rowIndex: number, columnIndex: number): Promise<void> {
  if (rowIndex < 0 || rowIndex >= lines.value.length || columnIndex < 0 || columnIndex > 3) return
  await nextTick()
  const field = formPage.value?.querySelector<HTMLElement>(
    `[data-grid-row="${rowIndex}"][data-grid-column="${columnIndex}"]`,
  )
  const input = field?.querySelector<HTMLInputElement>('input:not([disabled])')
  if (!field || !input) return
  field.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  input.focus({ preventScroll: true })
  if (!input.readOnly) input.select()
}

function handleGridNavigation(event: KeyboardEvent, rowIndex: number, columnIndex: number): void {
  if (event.altKey || event.ctrlKey || event.metaKey) return
  const input = event.target instanceof HTMLInputElement ? event.target : null
  if (!input || input.disabled) return
  const popupExpanded = Boolean(
    input.closest('[data-grid-field]')?.querySelector('[aria-expanded="true"]'),
  )
  if (popupExpanded && !(columnIndex === 1 && ['ArrowDown', 'ArrowUp'].includes(event.key))) return

  let targetRow = rowIndex
  let targetColumn = columnIndex
  if (event.key === 'Enter') {
    targetRow += event.shiftKey ? -1 : 1
  } else if (event.key === 'ArrowDown') {
    targetRow += 1
  } else if (event.key === 'ArrowUp') {
    targetRow -= 1
  } else if (event.key === 'ArrowLeft') {
    if (input.selectionStart !== null && input.selectionStart > 0) return
    targetColumn -= 1
  } else if (event.key === 'ArrowRight') {
    if (input.selectionEnd !== null && input.selectionEnd < input.value.length) return
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
  if (line.quantity_parse_status !== 'READY' || !line.required_quantity) return ''
  const quantity = formatSuggestedQuantity(line.required_quantity)
  return isPositiveDecimal(quantity) ? quantity : ''
}

function effectivePurchaseQuantity(line: PurchaseLineDraft): string {
  if (isPipePurchaseLine(line) || line.raw_bar_length_m) return pipeMeters(line.actual_bar_count, line.raw_bar_length_m || '')
  return line.actual_purchase_quantity.trim() || defaultPurchaseQuantity(line)
}

function pipeMetersLabel(line: PurchaseLineDraft): string {
  const meters = pipeMeters(line.actual_bar_count, line.raw_bar_length_m || '')
  if (!meters) return '—'
  return `${meters} 米 · ${line.raw_bar_length_m} 米/根`
}

function decimalParts(value: string): { digits: bigint; scale: number } | null {
  const matched = /^(\d+)(?:\.(\d+))?$/.exec(value.trim())
  if (!matched) return null
  const fraction = matched[2] || ''
  return { digits: BigInt(`${matched[1] || '0'}${fraction}`), scale: fraction.length }
}

function scaledProduct(quantity: string, price: string): bigint | null {
  const left = decimalParts(quantity)
  const right = decimalParts(price)
  if (!left || !right) return null
  const raw = left.digits * right.digits
  const rawScale = left.scale + right.scale
  if (rawScale === 4) return raw
  if (rawScale < 4) return raw * 10n ** BigInt(4 - rawScale)
  const divisor = 10n ** BigInt(rawScale - 4)
  return (raw + divisor / 2n) / divisor
}

function formatScaled(value: bigint): string {
  const raw = value.toString().padStart(5, '0')
  const whole = raw.slice(0, -4).replace(/\B(?=(\d{3})+(?!\d))/g, ',') || '0'
  const fraction = raw.slice(-4).replace(/0+$/, '')
  return fraction ? `${whole}.${fraction}` : `${whole}.00`
}

function lineAmount(line: PurchaseLineDraft): string {
  const amount = scaledProduct(effectivePurchaseQuantity(line), line.unit_price)
  return amount === null ? '—' : formatScaled(amount)
}

const totalAmount = computed(() => {
  const amounts = lines.value.map((line) => scaledProduct(effectivePurchaseQuantity(line), line.unit_price))
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

function isNonNegativeDecimal(value: string): boolean {
  return /^\d+(?:\.\d{1,4})?$/.test(value.trim()) && Number(value) >= 0
}

function isLineComplete(line: PurchaseLineDraft): boolean {
  return Boolean(
    line.supplier_id
    && line.delivery_date
    && isPositiveDecimal(effectivePurchaseQuantity(line))
    && isNonNegativeDecimal(line.unit_price),
  )
}

function validateDraft(): string {
  if (!selectedTaskId.value) return '请先选择采购来源。'
  if (!isSampleSource.value && !selectedBomId.value) return '请选择本次要采购的产品 BOM。'
  if (!source.value?.can_create) {
    if (source.value?.existing_purchase_order_number) {
      return `该采购来源已存在采购单 ${source.value.existing_purchase_order_number}，不能重复创建。`
    }
    return source.value?.blockers?.[0]?.message || '所选 BOM 尚未校验、明细为空或已失效，暂不能保存采购草稿。'
  }
  if (!lines.value.length) return '当前生产订单没有可保存的采购明细。'
  for (const [index, line] of lines.value.entries()) {
    if (isPipePurchaseLine(line)) {
      if (!isPositiveDecimal(line.raw_bar_length_m || '')) return `第 ${index + 1} 行：请填写大于 0 的每根长度（米）。`
      const error = pipeRootError(line.actual_bar_count)
      if (error) return `第 ${index + 1} 行：${error}`
    } else if (line.raw_bar_length_m) {
      const error = pipeRootError(line.actual_bar_count)
      if (error) return `第 ${index + 1} 行：${error}`
    }
    if (line.actual_purchase_quantity && !isPositiveDecimal(line.actual_purchase_quantity)) {
      return `第 ${index + 1} 行实际采购数量应为大于 0、最多 4 位小数的数字。`
    }
    if (line.unit_price && !isNonNegativeDecimal(line.unit_price)) {
      return `第 ${index + 1} 行采购单价应为大于或等于 0、最多 4 位小数的数字。`
    }
  }
  return ''
}

function validateConfirmation(): string {
  const draftError = validateDraft()
  if (draftError) return draftError
  const selectedCurrency = options.value.currencies.find((item) => item.id === form.currencyId)
  if (!selectedCurrency || selectedCurrency.code !== 'CNY') return '系统未找到人民币（CNY）采购币种，请联系管理员检查基础资料。'
  for (const [index, line] of lines.value.entries()) {
    const missing: string[] = []
    if (!line.supplier_id) missing.push('供应商')
    if (!line.delivery_date) missing.push('采购交期')
    if (!isPositiveDecimal(effectivePurchaseQuantity(line))) missing.push('实际采购数量')
    if (!isNonNegativeDecimal(line.unit_price)) missing.push('采购单价')
    if (!line.source_unit_text) missing.push('单位')
    if (missing.length) return `第 ${index + 1} 行缺少或填写错误：${missing.join('、')}。`
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
    is_mailed: form.isMailed,
    lines: lines.value.map((line) => ({
      ...(isSampleSource.value ? { sample_line_key: line.sample_line_key } : { bom_line_id: line.bom_line_id }),
      supplier_id: line.supplier_id || null,
      delivery_date: line.delivery_date || null,
      actual_purchase_quantity: isPipePurchaseLine(line) || line.raw_bar_length_m ? null : effectivePurchaseQuantity(line) || null,
      ...(isPipePurchaseLine(line) || line.raw_bar_length_m ? { actual_bar_count: line.actual_bar_count } : {}),
      ...(isPipePurchaseLine(line) ? { raw_bar_length_m: line.raw_bar_length_m || null } : {}),
      unit_price: line.unit_price.trim() || null,
    })),
  }
}

async function createOrder(nextStep: 'list' | 'confirm'): Promise<void> {
  if (saving.value) return
  const validationMessage = nextStep === 'confirm' ? validateConfirmation() : validateDraft()
  if (validationMessage) {
    showActionError(validationMessage)
    return
  }
  saving.value = true
  try {
    const result = await createPurchaseOrder(buildPayload())
    if (nextStep === 'confirm') {
      ElMessage.success('采购订单已保存，请核对后确认。')
      await router.push({ name: 'purchase-order-confirm', params: { id: result.data.id } })
    } else {
      ElMessage.success('采购订单草稿已创建。')
      await router.push({ name: 'purchase-orders' })
    }
  } catch (error) {
    const message = apiErrorMessage(error, '采购订单草稿保存失败，请稍后重试。')
    ElMessage.error(message)
  } finally {
    saving.value = false
  }
}

function saveDraft(): void {
  void createOrder('list')
}

function confirmPurchase(): void {
  void createOrder('confirm')
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
      showActionError(result.blockers?.[0]?.message || '当前来源没有可填写的采购明细。')
    }
  } catch (error) {
    showActionError(apiErrorMessage(error, '所选采购来源已不存在或已发生变化，请返回重新选择。'))
  } finally {
    sourceLoading.value = false
  }
}

async function initializePage(): Promise<void> {
  await loadOptions()
  if (isDetailStep.value && canAdd.value && !loadError.value) await restoreDetailSource()
}

function goToDetails(): void {
  if (!selectedTaskId.value) {
    showActionError('请先选择采购来源。')
    return
  }
  if (!isSampleSource.value && !selectedBomId.value) {
    showActionError('请选择本次要采购的产品 BOM。')
    return
  }
  if (!canContinueToDetails.value) {
    showActionError(source.value?.blockers?.[0]?.message || sourceError.value || '当前来源没有可采购的明细。')
    return
  }
  const sourceId = isSampleSource.value ? selectedTask.value?.source_id || '' : selectedTaskId.value
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
  void router.push({ name: isDetailStep.value ? 'purchase-order-create' : 'purchase-orders' })
}

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
onBeforeUnmount(() => window.removeEventListener('keydown', handleWindowKeydown))
</script>

<template>
  <section ref="formPage" class="purchase-form-page erp-glass-form" :class="{ 'is-sample-source': isSampleSource, 'is-detail-step': isDetailStep }" data-testid="purchase-order-form-page">
    <div v-if="!canAdd" class="state-page">
      <h1>无权新建采购订单</h1>
      <p>请联系管理员开通“采购订单新增”权限后重试。</p>
      <ElButton @click="back">返回采购订单列表</ElButton>
    </div>

    <template v-else>
      <header class="page-heading">
        <div>
          
          <h1>{{ isDetailStep ? '填写采购明细' : '新建采购订单' }}</h1>
          <p>{{ isDetailStep ? '填写供应商、采购交期、数量和单价' : '先选择订单，再选择本次采购的产品 BOM' }}</p>
        </div>
        <div class="page-action-panel">
          <div class="page-actions">
            <ElButton :disabled="saving" @click="back"><img class="purchase-icon" :src="backIcon" alt="" />{{ isDetailStep ? '返回选择' : '返回列表' }}</ElButton>
            <ElButton v-if="!isDetailStep" type="primary" :disabled="!canContinueToDetails || sourceLoading" data-testid="purchase-source-next" @click="goToDetails">下一步：填写明细<img class="purchase-icon" :src="rightIcon" alt="" /></ElButton>
            <ElButton v-if="isDetailStep" type="primary" plain :loading="saving" :disabled="saving" @click="saveDraft">保存草稿</ElButton>
          </div>
        </div>
      </header>

      <ElAlert v-if="loadError" type="error" :title="loadError" :closable="false" show-icon>
        <ElButton link @click="loadOptions">重新加载</ElButton>
      </ElAlert>

      <section v-if="!isDetailStep" v-loading="optionsLoading || sourceLoading" class="task-card">
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
              :disabled="!task.can_create"
            >
              <div class="task-select-option" :data-task-id="task.id">
                <strong>{{ task.task_number }}</strong>
                <ElTag class="purchase-source-tag" :class="{ 'is-sample': task.source_type === 'SAMPLE' }" effect="dark">{{ task.source_type === 'SAMPLE' ? '打样单' : '生产订单' }}</ElTag>
                <small>{{ task.source_type === 'SAMPLE' ? `${task.demand_count || 0} 项采购需求` : `${task.product_count} 项产品` }} · 交期 {{ task.delivery_date || '—' }}</small>
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
            <div><dt>{{ isSampleSource ? '采购需求' : '产品' }}</dt><dd>{{ isSampleSource ? selectedTask.demand_count : selectedTask.product_count }} 项</dd></div>
          </dl>
          <section v-if="!isSampleSource" class="selected-product-section" data-testid="selected-production-product-list">
            <div v-if="selectedProducts.length" class="selected-product-list">
              <div class="selected-product-row selected-product-row--heading">
                <span>选择</span><span>产品编码</span><span>货号</span><span>产品名称</span><span>规格</span><span>颜色</span><span>材质</span><span>订单数量</span><span>BOM状态</span>
              </div>
              <div v-for="product in selectedProducts" :key="product.id"
                class="selected-product-row selected-product-row--option"
                :class="{ 'is-selected': selectedBom?.product_line_id === product.id, 'is-unavailable': !productBomOption(product.id)?.bom_id }"
                :data-product-line-id="product.id" :data-selected="selectedBom?.product_line_id === product.id ? 'true' : 'false'"
                role="button" :tabindex="productBomOption(product.id)?.bom_id ? 0 : -1"
                :aria-label="`选择第${product.line_number}行：${product.product_name}，${productColorText(product)}`"
                :aria-pressed="selectedBom?.product_line_id === product.id" :aria-disabled="!productBomOption(product.id)?.bom_id"
                @click="handleProductSelection(product)" @keydown.enter.prevent="handleProductSelection(product)" @keydown.space.prevent="handleProductSelection(product)">
                <span class="product-radio" aria-hidden="true" />
                <span :title="product.product_code">{{ product.product_code || '—' }}</span>
                <span :title="product.item_number">{{ product.item_number || '—' }}</span><span :title="product.product_name">{{ product.product_name || '—' }}</span>
                <span :title="product.specification_display ?? product.specification">{{ (product.specification_display ?? product.specification) || '—' }}</span>
                <span :title="productColorText(product)">{{ product.color_name || '—' }}</span>
                <span :title="product.material">{{ product.material || '—' }}</span>
                <span :title="`${product.order_quantity} ${product.unit_name || product.unit_code}`">{{ product.order_quantity }} {{ product.unit_name || product.unit_code }}</span>
                <span :title="productBomOption(product.id)?.bom_status_display || '未建立'"><span class="bom-status" :class="{ 'is-ready': productBomOption(product.id)?.bom_status === 'VERIFIED' }">{{ productBomOption(product.id)?.bom_status_display || '未建立' }}</span></span>
              </div>
            </div>
            <p v-else>该订单包含 {{ selectedTask.product_count }} 项产品，暂无可用产品明细。</p>
            <p class="product-selection-caption" :class="{ 'is-blocked': sourceError || (selectedBom && !source?.can_create) }" role="status">
              {{ sourceError || (selectedBom ? `当前选择：第 ${selectedBom.product_line_number} 行 · ${selectedBom.product_color || selectedBom.product_name}` : '请选择本次采购的产品 BOM') }}
              <template v-if="selectedBom && !source?.can_create && !sourceError"> · {{ source?.blockers?.[0]?.message || '当前仅可预览，不能采购' }}</template>
            </p>
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
            <label class="bulk-field bulk-field--supplier" data-testid="purchase-bulk-supplier">
              <span>统一供应商</span>
              <ElSelect
                v-model="bulkSupplierId"
                filterable
                clearable
                :disabled="!source?.can_create || !lines.length"
                placeholder="选择后同步全部"
                popper-class="purchase-detail-popper"
                @change="applyBulkSupplier"
              >
                <template #label="{ value, label }">{{ options.suppliers.find(supplier => supplier.id === value)?.supplier_name || label }}</template>
              <ElOption v-for="supplier in options.suppliers" :key="supplier.id" :label="supplier.supplier_name" :value="supplier.id" />
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
                :disabled="!source?.can_create || !lines.length"
                placeholder="选择后同步全部"
                popper-class="purchase-detail-popper"
                @change="applyBulkDeliveryDate"
              />
            </label>
            <ElButton plain data-testid="purchase-detail-fullscreen" @click="toggleDetailFullscreen"><img class="purchase-icon" :src="expandIcon" alt="" />{{ detailFullscreen ? '退出全屏' : '全屏' }}</ElButton>
          </div>
        </header>
        <ElTable v-loading="sourceLoading" :data="lines" :row-key="purchaseLineKey" :height="detailTableHeight" class="purchase-lines" data-testid="purchase-lines" @cell-mouse-enter="handleLineMouseEnter" @mouseleave="handleLineMouseLeave">
          <ElTableColumn type="index" label="序号" width="48" align="center" />
          <ElTableColumn prop="category" label="分类" width="106" show-overflow-tooltip />
          <ElTableColumn label="物料信息" width="208">
            <template #default="{ row }"><div class="material-cell"><strong>{{ materialTitle(row) }}</strong></div></template>
          </ElTableColumn>
          <ElTableColumn v-if="isSampleSource" label="材质规格" width="220">
            <template #default="{ row }"><ElTooltip :content="materialDetail(row)" placement="top" :show-after="200"><span class="material-detail">{{ materialDetail(row) }}</span></ElTooltip></template>
          </ElTableColumn>
          <ElTableColumn v-else label="规格" width="220">
            <template #default="{ row }"><ElTooltip placement="top" :show-after="80" :visible="hoveredLineKey === purchaseLineKey(row)" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in materialAttributeFields(row)" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div></div></template><span class="material-detail">{{ materialSpecificationValue(row) }}</span></ElTooltip></template>
          </ElTableColumn>
          <ElTableColumn v-if="isSampleSource" label="需求数量" width="104">
            <template #default="{ row }">{{ formatSuggestedQuantity(row.sample_demand_quantity) }} {{ isPipePurchaseLine(row) ? '米' : row.source_unit_text }}</template>
          </ElTableColumn>
          <ElTableColumn v-if="isSampleSource" label="仓库可供" width="100">
            <template #default="{ row }">{{ formatSuggestedQuantity(row.sample_supply_quantity) }} {{ isPipePurchaseLine(row) ? '米' : row.source_unit_text }}</template>
          </ElTableColumn>
          <ElTableColumn :label="isSampleSource ? '待采购量' : '建议采购量'" :width="isSampleSource ? 110 : 180" align="right" header-align="left">
            <template #default="{ row }"><div class="quantity-cell"><template v-if="isPipePurchaseLine(row)"><strong>{{ formatSuggestedQuantity(row.required_quantity || row.source_quantity_text) }} 米</strong><small>采购填写根数与每根米数</small></template><template v-else-if="row.raw_bar_length_m"><strong>{{ row.suggested_bar_count }} 根</strong><small>{{ row.suggested_purchase_meters }} 米</small></template><template v-else><strong>{{ formatSuggestedQuantity(row.required_quantity || row.source_quantity_text) }}</strong><small>{{ row.source_unit_text || '单位未识别' }}</small></template></div></template>
          </ElTableColumn>
          <ElTableColumn label="供应商" :width="isSampleSource ? 210 : 271">
            <template #default="{ row, $index }">
              <div class="line-field" data-grid-field :data-grid-row="$index" data-grid-column="0" data-testid="purchase-line-supplier" @keydown.capture="handleGridNavigation($event, $index, 0)">
                <ElSelect v-model="row.supplier_id" filterable clearable :disabled="!source?.can_create" :placeholder="source?.can_create ? '请选择供应商' : '当前仅预览'" popper-class="purchase-detail-popper" @change="refreshBulkSupplier">
                  <template #label="{ value, label }">{{ options.suppliers.find(supplier => supplier.id === value)?.supplier_name || label }}</template>
                <ElOption v-for="supplier in options.suppliers" :key="supplier.id" :label="supplier.supplier_name" :value="supplier.id" />
                </ElSelect>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="采购交期" :width="isSampleSource ? 170 : 195">
            <template #default="{ row, $index }"><div class="line-field" data-grid-field :data-grid-row="$index" data-grid-column="1" data-testid="purchase-line-delivery-date" @keydown.capture="handleGridNavigation($event, $index, 1)"><ElDatePicker v-model="row.delivery_date" type="date" :prefix-icon="CalendarIcon" value-format="YYYY-MM-DD" format="YYYY-MM-DD" :disabled-date="disablePastDeliveryDate" :disabled="!source?.can_create" placeholder="选择采购交期" popper-class="purchase-detail-popper" @change="refreshBulkDeliveryDate" /></div></template>
          </ElTableColumn>
          <ElTableColumn label="实际采购数量" :width="isSampleSource ? 148 : 163">
            <template #default="{ row, $index }"><div class="line-field line-field--quantity" :class="{ 'pipe-order-quantity': isPipePurchaseLine(row) || row.raw_bar_length_m }" data-grid-field :data-grid-row="$index" data-grid-column="2" data-testid="purchase-line-quantity" @keydown.capture="handleGridNavigation($event, $index, 2)"><template v-if="isPipePurchaseLine(row)"><ElInput v-model="row.actual_bar_count" aria-label="实际采购根数" inputmode="numeric" maxlength="14" :disabled="!source?.can_create" placeholder="填写根数"><template #append>根</template></ElInput><ElInput v-model="row.raw_bar_length_m" aria-label="采购每根长度（米）" inputmode="decimal" maxlength="14" :disabled="!source?.can_create" placeholder="每根米数"><template #append>米/根</template></ElInput></template><template v-else-if="row.raw_bar_length_m"><ElInput v-model="row.actual_bar_count" aria-label="实际采购根数" inputmode="numeric" maxlength="14" :disabled="!source?.can_create" placeholder="整根数"><template #append>根</template></ElInput></template><ElInput v-else v-model="row.actual_purchase_quantity" inputmode="decimal" maxlength="24" :disabled="!source?.can_create" :placeholder="defaultPurchaseQuantity(row) || '请输入'"><template #append>{{ row.source_unit_text || '单位未识别' }}</template></ElInput></div></template>
          </ElTableColumn>
          <ElTableColumn label="折算采购米数" width="180">
            <template #default="{ row }"><ElTooltip :content="pipeMetersLabel(row)" placement="top" :show-after="200"><span v-if="row.raw_bar_length_m" class="pipe-meters">{{ pipeMetersLabel(row) }}</span><span v-else>—</span></ElTooltip></template>
          </ElTableColumn>
          <ElTableColumn label="采购单价（管材元/米）" width="164">
            <template #default="{ row, $index }"><div class="line-field" data-grid-field :data-grid-row="$index" data-grid-column="3" data-testid="purchase-line-unit-price" @keydown.capture="handleGridNavigation($event, $index, 3)"><ElInput v-model="row.unit_price" inputmode="decimal" maxlength="24" :disabled="!source?.can_create" placeholder="请输入" /></div></template>
          </ElTableColumn>
          <ElTableColumn label="采购金额（元）" min-width="173" align="left">
            <template #default="{ row }"><div class="amount-preview">{{ lineAmount(row) }}</div></template>
          </ElTableColumn>
          <template #empty>
            <div class="detail-empty">
              <div>!</div>
              <strong>{{ isSampleSource ? '暂无可采购的样品需求' : selectedTaskId ? selectedBomId ? '所选 BOM 暂无明细' : '请选择本次采购的产品 BOM' : '请先选择采购来源' }}</strong>
              <p>{{ sourceError || '选择生产订单或打样单后加载对应采购需求' }}</p>
            </div>
          </template>
        </ElTable>
        <p v-if="isSampleSource && source?.notes" class="sample-warehouse-note">仓库备注：{{ source.notes }}</p>
        <footer><span>{{ isPreviewMode ? `已找到 ${lines.length} 项采购需求 · 当前仅预览` : lines.length ? `已载入 ${lines.length} 项 · 已完整填写 ${completeLineCount} 项` : '请先选择采购来源' }}</span><span>金额＝实际采购数量 × 采购单价</span></footer>
      </section>

      <section v-if="isDetailStep" class="summary-card">
        <div class="summary-counts"><span>{{ isPreviewMode ? '采购需求预览' : '采购明细' }} <strong>{{ lines.length }}</strong> 项</span><span>·</span><span>已选供应商 <strong>{{ selectedSupplierCount }}</strong> 家</span></div>
        <div class="summary-actions">
          <label class="mail-field"><span>是否邮寄</span><ElRadioGroup v-model="form.isMailed" aria-label="是否邮寄"><ElRadio :value="false">否</ElRadio><ElRadio :value="true">是</ElRadio></ElRadioGroup></label>
          <div class="summary-total"><span>采购总金额</span><strong>{{ totalAmount === '待计算' ? totalAmount : `¥ ${totalAmount}` }}</strong></div>
          <ElButton type="primary" :loading="saving" :disabled="saving" data-testid="purchase-next" @click="confirmPurchase">下一步：确认采购<img class="purchase-icon" :src="rightIcon" alt="" /></ElButton>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use "@/styles/crm/tokens" as crm;
@use '@/styles/theme/detail' as detail;
.purchase-form-page {
  box-sizing: border-box; width: 100%; min-width: 0; height: auto; min-height: 0;
  display: flex; flex-direction: column; padding: 30px 28px 0; overflow: visible;
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
.purchase-form-page :deep(.el-button > span) { display: inline-flex; align-items: center; gap: 10px; }
.purchase-form-page :deep(.el-button) { border-radius: 5px; }
.page-heading { flex: none; min-height: 50px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.page-heading > div:first-child { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; min-width: 0; }
.page-heading h1 { margin: 0; white-space: nowrap; font: 700 38px/50px crm.$crm-font-display; letter-spacing: -1px; }
.page-heading p { margin: 8px 0 0; color: crm.$crm-text-secondary; font-size: 13px; white-space: nowrap; }
.page-action-panel { display: flex; flex-direction: column; align-items: flex-end; position: relative; }
.page-actions { display: flex; gap: 18px; }
.page-actions :deep(.el-button) { width: 128px; height: 42px; margin: 0; }
.page-actions :deep(.el-button--primary) { width: 164px; white-space: nowrap; background: var(--erp-button-primary-surface); color: crm.$crm-primary; border-color: var(--erp-button-primary-border); }
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
.selected-product-row > .product-radio { position: relative; justify-self: center; width: 18px; height: 18px; padding: 0; border: 1px solid crm.$crm-text-muted; border-radius: 50%; background: crm.$crm-color-surface; }
.selected-product-row.is-selected > .product-radio { border-color: crm.$crm-primary; }
.selected-product-row.is-selected > .product-radio::after { content: ''; position: absolute; inset: 3px; border-radius: 50%; background: crm.$crm-primary; }
.bom-status { box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; width: 64px; height: 24px; padding: 0 8px; border-radius: 999px; background: crm.$crm-info; color: var(--erp-color-text-inverse); font: 500 12px/18px 'Noto Sans SC Variable', crm.$crm-font-body; }
.bom-status.is-ready { color: var(--erp-color-text-inverse); background: crm.$crm-success; }
.product-selection-caption { margin: 8px 0 0; color: crm.$crm-text-secondary; font-size: 13px; line-height: 22px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.product-selection-caption.is-blocked { color: crm.$crm-warning; }
.task-selector-hint { display: grid; min-height: 150px; place-content: center; margin: 0; color: crm.$crm-text-muted; }
.detail-card { flex: none; min-height: 220px; display: flex; flex-direction: column; overflow: hidden; margin-bottom: 14px; }
.detail-card:not(.is-fullscreen) .purchase-lines { flex: none; }
.detail-card.is-fullscreen { position: fixed; z-index: 1900; inset: 0; height: 100dvh; width: 100%; border-radius: 0; }
.detail-card > header { display: flex; flex: 0 0 52px; align-items: center; justify-content: space-between; padding: 0 12px; gap: 10px; }
.detail-card > header > div { display: flex; align-items: center; gap: 12px; }
.detail-card > header > div > span { color: crm.$crm-text-secondary; font-size: 13px; }
.detail-title-context { min-width: 0; }
.detail-title-context h2 { flex: none; white-space: nowrap; }
.selected-product-context { min-width: 0; display: flex; align-items: center; gap: 10px; padding-left: 20px; border-left: 1px solid crm.$crm-border-default; white-space: nowrap; }
.selected-product-context > span { color: crm.$crm-text-secondary; font-size: 13px; }
.selected-product-context > strong { max-width: 130px; overflow: hidden; text-overflow: ellipsis; font-size: 14px; font-weight: 500; }
.selected-product-context > small { max-width: 180px; overflow: hidden; text-overflow: ellipsis; color: crm.$crm-text-secondary; font-size: 12px; }
.detail-header-actions { margin-left: auto; gap: 10px !important; }
.detail-header-actions :deep(.el-button) { width: 92px; height: 42px; margin: 0; }
.bulk-field { display: flex; align-items: center; gap: 8px; white-space: nowrap; font-size: 13px; }
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
:global(.purchase-detail-popper) { z-index: 4000 !important; }
.material-cell, .quantity-cell { display: flex; min-width: 0; }
.material-cell { flex-direction: column; }
.material-cell strong, .quantity-cell strong { font-weight: 500; font-size: 13px; }
.material-cell small, .quantity-cell small { color: crm.$crm-text-secondary; font-size: 12px; line-height: 19px; }
.material-cell > * { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.material-detail { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: crm.$crm-text-secondary; font-size: 12px; }
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: var(--erp-color-text-secondary); min-width: 42px; }
.quantity-cell { flex-direction: row; align-items: center; justify-content: flex-end; gap: 4px; white-space: nowrap; }
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
.mail-field { display: flex; align-items: center; gap: 26px; white-space: nowrap; }
.mail-field :deep(.el-radio) { margin-right: 28px; }
.mail-field :deep(.el-radio:last-child) { margin: 0; }
.mail-field :deep(.el-radio__inner) { width: 18px; height: 18px; border-color: crm.$crm-text-muted; }
.mail-field :deep(.el-radio__input.is-checked .el-radio__inner) { border-color: crm.$crm-primary; }
.summary-total { display: flex; align-items: center; gap: 18px; padding-left: 40px; border-left: 1px solid crm.$crm-border-default; white-space: nowrap; }
.summary-total strong { min-width: 170px; font-size: 28px; color: crm.$crm-primary; font-weight: 700; }
.summary-actions > :deep(.el-button) { width: 220px; height: 42px; }
.state-page { display: grid; min-height: 520px; place-content: center; text-align: center; }
.state-page p { color: crm.$crm-text-secondary; }

@media (max-width: 980px) {
  .detail-card > header { flex: 0 0 112px; flex-direction: column; align-items: stretch; justify-content: center; gap: 10px; padding-top: 8px; padding-bottom: 8px; }
  .detail-title-context { flex: none; height: 30px; }
  .detail-header-actions { flex: none; justify-content: flex-end; margin-left: 0; }
}


.pipe-meters { white-space: nowrap; }
.pipe-order-quantity { display: flex; flex-direction: column; align-items: stretch; height: auto; min-width: 0; width: 100%; gap: 4px; padding: 6px 0; white-space: normal; }
.pipe-order-quantity small { display: block; font-size: 11px; line-height: 16px; overflow-wrap: anywhere; }
:deep(td .cell:has(.pipe-order-quantity)) { display: block !important; white-space: normal !important; text-overflow: clip; }
</style>
