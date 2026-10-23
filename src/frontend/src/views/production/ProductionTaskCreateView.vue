<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { createProductionTask, reserveProductionTaskContractNumber, createProductionOrderFromSalesOrder, fetchProductionTaskOptions, submitProductionTask, fetchProductionSalesOrderSources, fetchProductionSalesOrderSource, productionSalesOrderSourceImageUrl } from '@/api/productionTasks'
import InquiryProductDialog from '@/components/inquiries/InquiryProductDialog.vue'
import type { InquiryItem, InquiryProductCandidate, InquiryProductSelectionOptions } from '@/types/inquiry'
import type { ProductCategoryOption, ProductionUnitOption } from '@/types/product'
import type { ColorOption } from '@/types/productionTask'
import type { ProductionTaskDetailInput, ProductionTaskInput } from '@/types/productionTask'
import ProductImage from '@/components/products/ProductImage.vue'
import type { ProductionTaskOptions, ProductionSalesOrderSource, ProductionSalesOrderSourceSummary, ProductionSalesOrderSourceBatch } from '@/types/productionTask'
import type { SalesOrderBatchLine } from '@/types/salesOrder'
import { multiplyAmount4, sumAmounts4 } from '@/utils/salesCny'

interface ColorProductionLine {
  key: string
  sourceLineId: string
  productColorId: string
  quantity: number
  specialRequirements: string
  packagingMethod: string
}

const route = useRoute()
const router = useRouter()
const manualMode = computed(() => route.name === 'production-task-manual-create')
const hasSalesContext = computed(() => route.query.sales_order_id !== undefined)
const sourceOrderId = computed(() => typeof route.query.sales_order_id === 'string' ? route.query.sales_order_id.trim() : '')
const sourceLoadError = ref('')
const loading = ref(false)
const orderLoading = ref(false)
const submitting = ref(false)
const activeStep = ref(1)
const sourceSearchKeyword = ref('')
const orderChoices = ref<ProductionSalesOrderSourceSummary[]>([])
const selectedOrderId = ref('')
const selectedBatchId = ref('')
const order = ref<ProductionSalesOrderSource | null>(null)
const options = ref<ProductionTaskOptions | null>(null)
const colorLines = ref<ColorProductionLine[]>([])
const requestKey = crypto.randomUUID()
const taskNumberSuffix = ref('')
let latestOrderRequest = 0
const stepItems = [
  { title: '选择销售来源', description: '订单及交付来源' },
  { title: '产品与价格', description: '本次数量与人民币金额' },
  { title: '生产安排', description: '任务编号、人员与要求' },
  { title: '核对并提交', description: '保存草稿或提交 PMC' },
]
const plan = reactive({
  plannedStartDate: '',
  plannedEndDate: '',
  productionPriority: 'NORMAL' as 'URGENT' | 'HIGH' | 'NORMAL' | 'LOW',
  productionBatchNumber: '',
  plannerId: null as string | null,
  followerIds: [] as string[], deliveryDate: '', salespersonId: '', orderDate: '',
  preproductionSample: false, includesTax: false, taxRate: null as 3 | 5 | 7 | null, tolerance: '0', isRepeat: false, deliveryMethod: 'SINGLE' as 'SINGLE' | 'SPLIT',
})

const activeBatches = computed(() => order.value?.delivery_batches.filter((batch) => batch.status === 'ACTIVE') || [])
const selectedBatch = computed(() => activeBatches.value.find((batch) => batch.id === selectedBatchId.value) || null)
const sourceById = computed(() => new Map((selectedBatch.value?.lines || []).map((line) => [line.id, line])))
function key() {
  return crypto.randomUUID()
}

function apiError(error: unknown): string {
  const response = (error as { response?: { data?: { detail?: string; error?: { message?: string; field_errors?: Record<string, string[]> } } } })?.response?.data
  const fieldError = response?.error?.field_errors ? Object.values(response.error.field_errors).flat()[0] : ''
  return fieldError || response?.error?.message || response?.detail || '操作失败，请稍后重试。'
}

function formatQuantity(value: string | number) {
  return Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

function sourceLine(draft: ColorProductionLine) {
  return sourceById.value.get(draft.sourceLineId)
}

function salesOrderLine(draft: ColorProductionLine) {
  const batchLine = sourceLine(draft)
  return order.value?.lines?.find((line) => line.id === batchLine?.sales_order_line_id)
}

function sourceColorText(draft: ColorProductionLine) {
  const line = salesOrderLine(draft)
  return line?.customer_color_snapshot?.trim() || options.value?.colors.find(color => color.id === line?.product_color_id)?.color_name || '—'
}

function priorityLabel(value: string) {
  return ({ URGENT: '紧急', HIGH: '高', NORMAL: '普通', LOW: '低' } as Record<string, string>)[value] || value
}

function draftQuantity(line: SalesOrderBatchLine) {
  const nominalRemaining = Math.max(Number(line.quantity) - Number(line.allocated_quantity || 0), 0)
  return Math.max(0, Math.floor(Math.min(nominalRemaining, Number(line.remaining_quantity || nominalRemaining))))
}

function resetLines(batch: ProductionSalesOrderSourceBatch | null) {
  colorLines.value = (batch?.lines || [])
    .map((line) => {
      const orderLine = order.value?.lines?.find((item) => item.id === line.sales_order_line_id)
      return {
        key: key(),
        sourceLineId: line.id,
        productColorId: '',
        quantity: draftQuantity(line),
        specialRequirements: orderLine?.quality_requirements || '',
        packagingMethod: orderLine?.packaging_requirements || '',
      }
    })
    .filter((line) => line.quantity > 0)
  plan.productionBatchNumber = batch?.batch_number || ''
  plan.plannedStartDate = ''
  plan.plannedEndDate = ''
}

async function loadOrders(keyword = '') {
  if (hasSalesContext.value) {
    orderChoices.value = []
    selectedOrderId.value = sourceOrderId.value
    if (!sourceOrderId.value) {
      sourceLoadError.value = '来源销售订单参数无效，请返回销售订单重新进入。'
      return
    }
    await loadOrder(sourceOrderId.value, typeof route.query.delivery_batch_id === 'string' ? route.query.delivery_batch_id : '')
    if (order.value) orderChoices.value = [order.value]
    return
  }
  orderLoading.value = true
  try {
    const query = keyword.trim() || undefined
    const result = await fetchProductionSalesOrderSources(query)
    orderChoices.value = result.data.filter((item) => item.has_remaining_production_capacity !== false)
  } finally {
    orderLoading.value = false
  }
}

async function searchSourceOrders() {
  try {
    await loadOrders(sourceSearchKeyword.value)
  } catch (error) {
    ElMessage.error(apiError(error))
  }
}

async function loadOrder(orderId: string, preferredBatchId = '') {
  const requestId = ++latestOrderRequest
  sourceLoadError.value = ''
  if (!orderId) {
    order.value = null
    selectedBatchId.value = ''
    colorLines.value = []
    return
  }
  loading.value = true
  try {
    const result = await fetchProductionSalesOrderSource(orderId)
    if (requestId !== latestOrderRequest || selectedOrderId.value !== orderId) return
    if (!['CONFIRMED', 'FULFILLING'].includes(result.data.status) || result.data.has_remaining_production_capacity === false) {
      order.value = null
      selectedBatchId.value = ''
      colorLines.value = []
      sourceLoadError.value = '该销售订单尚未确认、已结束或已分配完成，不能创建生产任务单。'
      return
    }
    order.value = result.data
    const batch = result.data.delivery_batches.find((item) => item.id === preferredBatchId && item.status === 'ACTIVE')
      || (!preferredBatchId ? result.data.delivery_batches.find((item) => item.status === 'ACTIVE' && item.lines.some(line => draftQuantity(line) > 0)) : null)
      || null
    selectedBatchId.value = batch?.id || ''
    if (preferredBatchId && (!batch || !batch.lines.some(line => draftQuantity(line) > 0))) sourceLoadError.value = '当前交付批次已取消或已分配完成，请返回销售订单核对。'
    resetLines(batch)
    plan.deliveryDate = batch?.planned_delivery_date || ''
    plan.salespersonId = result.data.salesperson?.id || ''
    plan.orderDate = result.data.order_date || ''
    plan.tolerance = result.data.order_tolerance_percent || '0'
  } catch (error) {
    if (requestId !== latestOrderRequest) return
    order.value = null
    selectedBatchId.value = ''
    colorLines.value = []
    sourceLoadError.value = `无法读取来源销售订单：${apiError(error)}`
  } finally {
    if (requestId === latestOrderRequest) loading.value = false
  }
}

async function changeOrder() {
  activeStep.value = 1
  await loadOrder(selectedOrderId.value)
}

async function selectSourceOrder(orderId: string) {
  if (hasSalesContext.value && sourceOrderId.value !== orderId) return
  if (selectedOrderId.value === orderId && order.value) return
  selectedOrderId.value = orderId
  await changeOrder()
}

function sourceProductText(item: ProductionSalesOrderSourceSummary) {
  return item.product_names?.join('、') || '—'
}

function sourceBatchText(item: ProductionSalesOrderSourceSummary) {
  if (order.value?.id === item.id && selectedBatch.value) return selectedBatch.value.batch_number
  return `共 ${item.delivery_batch_count} 批`
}

function changeBatch() {
  activeStep.value = 1
  resetLines(selectedBatch.value)
  sourceLoadError.value = colorLines.value.length ? '' : '当前交付批次已取消或已分配完成，请返回销售订单核对。'
  plan.deliveryDate = selectedBatch.value?.planned_delivery_date || ''
}

function validateStepOne() {
  if (manualMode.value) {
    if (!manualProducts.value.length) { ElMessage.warning('请先录入至少一条产品。'); return false }
    return true
  }
  if (sourceLoadError.value) { ElMessage.warning(sourceLoadError.value); return false }
  if (!order.value || !selectedBatch.value) { ElMessage.warning('请选择已确认的销售订单和有效交付批次。'); return false }
  return true
}

function validateLines() {
  if (manualMode.value) return validateManualProducts()
  if (!sourceAmountsReady.value) { ElMessage.warning('来源销售订单尚未保存人民币金额，请先完善销售订单。'); return false }
  if (!colorLines.value.length) {
    ElMessage.warning('当前批次没有可安排的产品，请检查已分配数量。')
    return false
  }
  const totals = new Map<string, number>()
  const pairs = new Set<string>()
  for (const [index, line] of colorLines.value.entries()) {
    if (!sourceById.value.has(line.sourceLineId)) {
      ElMessage.warning(`第 ${index + 1} 行的来源产品无效。`)
      return false
    }
    if (!Number.isInteger(line.quantity) || line.quantity < 1) {
      ElMessage.warning(`第 ${index + 1} 行生产数量必须是大于 0 的整数。`)
      return false
    }
    const pair = `${line.sourceLineId}:${line.productColorId}`
    if (pairs.has(pair)) {
      ElMessage.warning(`第 ${index + 1} 行与已有产品颜色重复。`)
      return false
    }
    pairs.add(pair)
    totals.set(line.sourceLineId, (totals.get(line.sourceLineId) || 0) + line.quantity)
  }
  for (const [sourceId, quantity] of totals) {
    const source = sourceById.value.get(sourceId)
    if (source && quantity > Number(source.remaining_quantity)) {
      ElMessage.warning(`${source.product_name} 本次合计不能超过可安排数量 ${formatQuantity(source.remaining_quantity)} ${source.unit_code}。`)
      return false
    }
  }
  return true
}

function validatePlan() {
  if (manualMode.value && manualProducts.value.some(row => !row.details.length || row.details.some(detail => !detail.detail_type.trim()))) { ElMessage.warning('请补齐各产品的生产任务单明细类型。'); return false }
  if (!/^[0-9]+(?:-[0-9]+)*$/.test(taskNumberSuffix.value) || taskNumberSuffix.value.length > 48) { ElMessage.warning('请填写有效生产任务单号，例如 26199 或 26199-1。'); return false }
  if (!plan.followerIds.length) { ElMessage.warning('请选择生产跟单员。'); return false }
  if (!plan.orderDate || !plan.deliveryDate || plan.deliveryDate < plan.orderDate) { ElMessage.warning('请填写下单日期及不早于下单日期的交期。'); return false }
  if (!plan.salespersonId) { ElMessage.warning('请选择业务员。'); return false }
  if (plan.includesTax && ![3,5,7].includes(Number(plan.taxRate))) { ElMessage.warning('含税时请选择税率。'); return false }
  if (!plan.tolerance.trim() || !Number.isFinite(Number(plan.tolerance)) || Number(plan.tolerance) < 0 || Number(plan.tolerance) > 100) { ElMessage.warning('订单误差必须是0到100的百分比。'); return false }
  if (Boolean(plan.plannedStartDate) !== Boolean(plan.plannedEndDate)) {
    ElMessage.warning('计划开始和计划完工日期需同时填写或同时留空。')
    return false
  }
  if (plan.plannedStartDate && plan.plannedEndDate < plan.plannedStartDate) {
    ElMessage.warning('计划完工日期不能早于计划开始日期。')
    return false
  }
  return true
}

function nextStep() {
  if (activeStep.value === 1 && !validateStepOne()) return
  if (activeStep.value === 2 && !validateLines()) return
  if (activeStep.value === 3 && !validatePlan()) return
  activeStep.value = Math.min(4, activeStep.value + 1)
}

async function save(submitToPmc: boolean) {
  if (!validateStepOne() || !validateLines() || !validatePlan() ) return
  submitting.value = true
  let createdId = ''
  try {
    const created = manualMode.value ? await saveManual() : await createProductionOrderFromSalesOrder({
      request_key: requestKey,
      task_number: `HT${taskNumberSuffix.value}`,
      delivery_batch_id: selectedBatch.value!.id,
      follower_ids: [...plan.followerIds], delivery_date: plan.deliveryDate, includes_tax: plan.includesTax, tax_rate: plan.includesTax ? plan.taxRate : null,
      order_tolerance_percent: plan.tolerance, is_repeat_order: plan.isRepeat, delivery_method: plan.deliveryMethod,
      lines: colorLines.value.map((line) => {
        const orderLine = salesOrderLine(line)
        return {
          delivery_batch_line_id: line.sourceLineId,
          quantity: line.quantity,
          special_requirements: line.specialRequirements.trim() || orderLine?.quality_requirements || '',
          packaging_method: line.packagingMethod.trim() || orderLine?.packaging_requirements || '',
        }
      }),
      planned_start_date: plan.plannedStartDate || null,
      planned_end_date: plan.plannedEndDate || null,
      production_priority: plan.productionPriority,
      production_batch_number: plan.productionBatchNumber.trim(),
      planner_id: plan.plannerId,
    })
    createdId = created.data.id
    if (submitToPmc) {
      try {
        const submitted = await submitProductionTask(created.data.id, created.etag)
        ElMessage.success(`生产任务单 ${submitted.data.task_number} 已提交 PMC。`)
      } catch (error) {
        ElMessage.warning(`生产任务单已保存为草稿，但提交 PMC 失败：${apiError(error)}`)
      }
    } else {
      ElMessage.success(`生产任务单 ${created.data.task_number} 已保存为草稿。`)
    }
    await router.replace({ name: 'production-task-detail', params: { taskId: created.data.id } })
  } catch (error) {
    if (!createdId) ElMessage.error(apiError(error))
  } finally {
    submitting.value = false
  }
}

watch(manualMode, async value => {
  activeStep.value = 1
  if (value && !categories.value.length) await loadCatalog()
  if (!value) {
    if (order.value) { plan.salespersonId = order.value.salesperson?.id || ''; plan.orderDate = order.value.order_date || ''; plan.deliveryDate = selectedBatch.value?.planned_delivery_date || ''; plan.tolerance = order.value.order_tolerance_percent || '0' }
    if (!orderChoices.value.length) { try { await loadOrders() } catch (error) { ElMessage.error(apiError(error)) } }
  }
})

onMounted(async () => {
  loading.value = true
  try {
    const [taskOptions] = await Promise.all([fetchProductionTaskOptions(), manualMode.value ? Promise.resolve() : loadOrders()])
    options.value = taskOptions
    if (manualMode.value) { await loadCatalog(); return }
    if (hasSalesContext.value) return
    const queryOrderId = typeof route.query.sales_order_id === 'string' ? route.query.sales_order_id : ''
    const queryBatchId = typeof route.query.delivery_batch_id === 'string' ? route.query.delivery_batch_id : ''
    selectedOrderId.value = queryOrderId || orderChoices.value[0]?.id || ''
    if (selectedOrderId.value) await loadOrder(selectedOrderId.value, queryBatchId)
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
})

watch(() => [route.query.sales_order_id, route.query.delivery_batch_id], async () => {
  if (!options.value || manualMode.value) return
  activeStep.value = 1
  order.value = null
  colorLines.value = []
  try {
    await loadOrders()
    if (!hasSalesContext.value) {
      selectedOrderId.value = orderChoices.value[0]?.id || ''
      await loadOrder(selectedOrderId.value)
    }
  } catch (error) { sourceLoadError.value = apiError(error) }
})

const categories = ref<ProductCategoryOption[]>([])
const catalogUnits = ref<ProductionUnitOption[]>([])
const catalogColors = ref<ColorOption[]>([])
const catalogError = ref('')
const editorVisible = ref(true)
const editorRevision = ref(0)
const editingKey = ref('')
const manualProducts = ref<Array<{ key: string; item: InquiryItem; file: File | null; preview: string; packagingMethod: string; details: ProductionTaskDetailInput[] }>>([])
const editorItem = ref<InquiryItem>(emptyItem())
function emptyItem(): InquiryItem { return { product_id: null, product_category_id: null, product_unit_id: null, product_color_id: null, product_description: '', specification: '', color: '', material: '', quantity: '1', unit_code: '', target_unit_price: '', target_currency_code: 'CNY', expected_date: null, product_match_status: 'PENDING', notes: '' } }
async function loadCatalog() {
  categories.value = options.value?.categories || []
  catalogUnits.value = options.value?.units || []
  catalogColors.value = options.value?.colors || []
  catalogError.value = options.value?.categories ? '' : '生产建单产品分类未加载，请刷新后重试。'
}
async function loadProductionCandidates(categoryId: string): Promise<InquiryProductSelectionOptions> {
  const category = categories.value.find(row => row.id === categoryId)
  if (!category) throw new Error('产品类别不存在或不可用。')
  const grouped = new Map<string, Map<string, InquiryProductCandidate[]>>()
  for (const product of options.value?.products || []) {
    if (product.category_id !== categoryId) continue
    const unit = catalogUnits.value.find(row => row.id === product.default_unit_id)
    const candidate: InquiryProductCandidate = { id: product.id, product_number: product.product_number, product_code: product.product_code, item_number: product.item_number, product_name: product.product_name, specification: product.specification, unit_id: product.default_unit_id, unit_code: product.unit_code || unit?.unit_code || '', unit_name: product.unit_name || unit?.unit_name || '', category_id: category.id, category_name: category.category_name }
    if (!grouped.has(product.product_name)) grouped.set(product.product_name, new Map())
    const specs = grouped.get(product.product_name)!
    if (!specs.has(product.specification)) specs.set(product.specification, [])
    specs.get(product.specification)!.push(candidate)
  }
  return { category, groups: [...grouped].map(([product_name, specs]) => ({ product_name, specifications: [...specs].map(([specification, products]) => ({ specification, products })) })) }
}
function editManual(row?: typeof manualProducts.value[number]) {
  editingKey.value = row?.key || ''; editorItem.value = row ? { ...row.item } : emptyItem(); editorRevision.value++; editorVisible.value = true
}
function confirmManual(value: { item: InquiryItem; imageChanged: boolean; imageFile: File | null; removeImage: boolean }) {
  const unit = catalogUnits.value.find(row => row.id === value.item.product_unit_id || row.unit_code === value.item.unit_code)
  if (!unit) { ElMessage.warning('请选择系统已维护的真实单位，未维护单位请先补全基础资料。'); return }
  if (!/^[1-9]\d*$/.test(String(value.item.quantity))) { ElMessage.warning('生产数量必须是大于0的整数。'); return }
  const old = manualProducts.value.find(row => row.key === editingKey.value)
  const file = value.imageChanged ? value.imageFile : old?.file || null
  if (old?.preview.startsWith('blob:')) URL.revokeObjectURL(old.preview)
  const template = options.value?.detail_template || []
  const details = old?.details || (template.length ? template.map(item => ({ client_key: key(), template_key: item.key, detail_type: item.type, category_label: item.category, is_selected: false, description: '' })) : [{ client_key: key(), template_key: '', detail_type: '', category_label: '', is_selected: false, description: '' }])
  const row = { details, packagingMethod: old?.packagingMethod || '', key: old?.key || key(), item: { ...value.item, product_unit_id: unit.id, target_currency_code: 'CNY' }, file, preview: file ? URL.createObjectURL(file) : '' }
  if (old) manualProducts.value.splice(manualProducts.value.indexOf(old), 1, row)
  else manualProducts.value.push(row)
  editManual()
}
function removeManual(index: number) { const row = manualProducts.value[index]; if (row?.preview.startsWith('blob:')) URL.revokeObjectURL(row.preview); manualProducts.value.splice(index, 1) }
function validateManualProducts() {
  if (!manualProducts.value.length) { ElMessage.warning('请录入产品。'); return false }
  if (!options.value?.currencies.some(row => row.code === 'CNY')) { ElMessage.warning('基础资料缺少人民币币种。'); return false }
  for (const row of manualProducts.value) {
    if (!/^[1-9]\d*$/.test(String(row.item.quantity)) || !row.item.product_unit_id || String(row.item.target_unit_price).trim() === '' || !Number.isFinite(Number(row.item.target_unit_price)) || Number(row.item.target_unit_price) < 0) { ElMessage.warning('请检查产品数量、真实单位和人民币单价。'); return false }
  }
  return true
}
async function saveManual() {
  const reserved = await reserveProductionTaskContractNumber(plan.orderDate)
  const currencyId = options.value!.currencies.find(row => row.code === 'CNY')!.id
  const payload: ProductionTaskInput = {
    task_number: `HT${taskNumberSuffix.value}`, contract_number: reserved.contract_number, contract_number_token: reserved.token,
    order_source: plan.isRepeat ? 'REPEAT' : 'NEW', order_number: `HT${taskNumberSuffix.value}`, order_date: plan.orderDate, delivery_date: plan.deliveryDate,
    salesperson_id: plan.salespersonId, follower_ids: [...plan.followerIds], currency_id: currencyId, includes_tax: plan.includesTax, tax_rate: plan.includesTax ? plan.taxRate : null,
    order_tolerance_percent: plan.tolerance, is_repeat_order: plan.isRepeat, preproduction_sample_required: plan.preproductionSample, delivery_method: plan.deliveryMethod,
    special_requirements_html: '', freight_amount: '0', other_fee_amount: '0', delivery_batches: [],
    planned_start_date: plan.plannedStartDate || null, planned_end_date: plan.plannedEndDate || null, production_priority: plan.productionPriority, production_batch_number: plan.productionBatchNumber, planner_id: plan.plannerId,
    products: manualProducts.value.map(row => ({ client_key: row.key, product_id: row.item.product_id || null, product_category_id: row.item.product_category_id ?? null, product_color_id: row.item.product_color_id || null, color_code: catalogColors.value.find(color => color.id === row.item.product_color_id)?.color_code || '', customer_product_name: row.item.product_description, customer_specification: row.item.specification, customer_color: row.item.color, material: row.item.material,
      quantity: String(row.item.quantity), unit_id: row.item.product_unit_id!, currency_id: currencyId, unit_price: String(row.item.target_unit_price), exchange_rate: '1.00000000', retained_image_ids: [], details: row.details, special_requirements: row.item.notes, packaging_method: row.packagingMethod })),
  }
  return createProductionTask(payload, Object.fromEntries(manualProducts.value.filter(row => row.file).map(row => [row.key, [row.file!]])), {})
}
const sourceAmountsReady = computed(() => Boolean(order.value && order.value.total_amount_cny != null && colorLines.value.every(row => salesOrderLine(row)?.unit_price_cny != null)))
function money(value: string | number | null | undefined) { if (value === undefined || value === null || value === '') return '—'; return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 }) }
function unitName(line: ColorProductionLine) { const source = salesOrderLine(line); const batch = sourceLine(line); return source?.unit_name || options.value?.units.find(unit => unit.id === source?.unit_id || unit.unit_code === batch?.unit_code)?.unit_name || '单位未维护' }
function quantitySummary(kind: 'quantity' | 'remaining_quantity' | 'allocated_quantity' | 'production') {
  const totals = new Map<string, number>()
  for (const line of colorLines.value) { const unit = unitName(line); const amount = kind === 'production' ? line.quantity : Number(sourceLine(line)?.[kind] || 0); totals.set(unit, (totals.get(unit) || 0) + amount) }
  return [...totals].map(([unit, amount]) => `${formatQuantity(amount)} ${unit}`).join(' / ') || '—'
}
const currentAmount = computed(() => sumAmounts4(manualMode.value
  ? manualProducts.value.map(row => multiplyAmount4(row.item.quantity, row.item.target_unit_price))
  : colorLines.value.map(row => multiplyAmount4(row.quantity, salesOrderLine(row)?.unit_price_cny))))
onBeforeUnmount(() => { for (const row of manualProducts.value) if (row.preview.startsWith('blob:')) URL.revokeObjectURL(row.preview) })
watch(() => plan.includesTax, value => { if (!value) plan.taxRate = null })

</script>
<template>
  <section v-loading="loading" class="production-create-page erp-glass-form">
    <header class="page-heading"><div><h1>新增生产任务单</h1><p>选择来源、核对产品价格，再填写生产安排并提交 PMC。</p></div><span class="draft-tag">未保存</span></header>
    <div class="creation-card">
      <nav class="creation-modes" aria-label="创建方式"><button :class="{ active: !manualMode }" @click="router.push({ name: 'production-task-create', query: route.query })">从销售订单创建</button><button :class="{ active: manualMode }" @click="router.push({ name: 'production-task-manual-create', query: route.query })">手动创建</button></nav>
      <div class="creation-body">
        <ol class="steps" aria-label="新增生产任务单步骤"><li v-for="(item,index) in stepItems" :key="item.title" :class="{ active: activeStep === index + 1, done: activeStep > index + 1 }"><b>{{ activeStep > index + 1 ? '✓' : index + 1 }}</b><div><span>{{ index === 0 && manualMode ? '录入产品' : item.title }}</span><small>{{ index === 0 && manualMode ? '产品、规格与人民币价格' : item.description }}</small></div></li></ol>
        <main class="workspace" :class="{ 'erp-flat-form': activeStep === 3 }">
          <template v-if="activeStep === 1 && !manualMode">
            <div class="section-title"><h2>选择销售订单及交付来源</h2></div>
            <div v-if="!hasSalesContext" class="search-row"><el-input v-model="sourceSearchKeyword" clearable placeholder="搜索销售订单号" @keyup.enter="searchSourceOrders" @clear="searchSourceOrders"/><el-button @click="searchSourceOrders">查询</el-button></div>
            <div class="table-frame"><el-table v-loading="orderLoading" :data="orderChoices" class="erp-table-editor source-order-table" empty-text="没有可分配的销售订单"><el-table-column prop="order_number" label="销售订单号" min-width="180"/><el-table-column label="订单总金额（CNY）" min-width="160" align="right"><template #default="{row}">{{ money(row.total_amount_cny) }}</template></el-table-column><el-table-column label="产品" min-width="160"><template #default="{row}">{{ sourceProductText(row) }}</template></el-table-column><el-table-column label="交付来源" min-width="180"><template #default="{row}"><el-select v-if="order?.id === row.id && activeBatches.length > 1" v-model="selectedBatchId" @change="changeBatch"><el-option v-for="batch in activeBatches" :key="batch.id" :value="batch.id" :label="batch.batch_number"/></el-select><span v-else>{{ sourceBatchText(row) }}</span></template></el-table-column><el-table-column label="交期" width="130"><template #default="{row}">{{ order?.id === row.id ? selectedBatch?.planned_delivery_date : row.next_delivery_date }}</template></el-table-column><el-table-column label="操作" width="110" fixed="right"><template #default="{row}"><el-button link type="primary" @click="selectSourceOrder(row.id)">{{ selectedOrderId === row.id ? '已选择' : '选择' }}</el-button></template></el-table-column></el-table></div>
            <el-alert v-if="sourceLoadError" class="source-load-error" type="error" :closable="false" :title="sourceLoadError"/><h3 v-if="order">来源产品 · {{ order.order_number }}</h3>
          </template>
          <template v-if="activeStep === 1 && manualMode">
            <div class="section-title"><h2>录入本次生产产品</h2></div>
            <InquiryProductDialog :key="editorRevision" v-model="editorVisible" embedded hide-summary business-title="本次生产内容" scene="sales-order" :candidate-loader="loadProductionCandidates" :item="editorItem" :categories="categories" :units="catalogUnits" :colors="catalogColors" :currencies="[{code:'CNY'}]" quotation-currency="CNY" :can-upload="true" :close-on-confirm="false" :catalog-error="catalogError" :pending-image="manualProducts.find(row => row.key === editingKey)?.file" @confirm="confirmManual"/>
            <div class="section-title"><h3>已录入产品（{{ manualProducts.length }}）</h3></div>
          </template>
          <template v-if="(activeStep === 1 && order && !manualMode) || activeStep === 2">
          <div v-if="activeStep === 2" class="section-title"><h2>核对产品及本次数量价格</h2><p v-if="!manualMode">产品与人民币单价沿用销售订单，核对本次生产数量。</p></div>
            <div v-if="!manualMode" class="source-context"><span>来源 {{ order?.order_number }} · {{ selectedBatch?.batch_number }}</span><strong>订单总金额 CNY {{ money(order?.total_amount_cny) }}</strong><span>可分配 {{ quantitySummary('remaining_quantity') }}</span></div>
            <el-alert v-if="!manualMode && order && !sourceAmountsReady" type="error" :closable="false" title="来源销售订单尚未保存人民币金额，请先完善销售订单。"/>
            <div v-if="!manualMode" class="table-frame"><el-table :data="colorLines" class="erp-table-editor product-table"  empty-text="该来源没有可分配产品"><el-table-column label="图片" width="72"><template #default="{row}"><ProductImage :src="order && salesOrderLine(row)?.product_image_id ? productionSalesOrderSourceImageUrl(order.id, salesOrderLine(row)!.id) : ''" :name="sourceLine(row)?.product_name"/></template></el-table-column><el-table-column label="货号" width="130"><template #default="{row}">{{ salesOrderLine(row)?.product_id ? salesOrderLine(row)?.item_number_snapshot : '' }}</template></el-table-column><el-table-column label="产品名称" min-width="170"><template #default="{row}">{{ salesOrderLine(row)?.customer_product_name_snapshot || sourceLine(row)?.product_name }}</template></el-table-column><el-table-column label="颜色" width="120"><template #default="{row}">{{ sourceColorText(row) }}</template></el-table-column><el-table-column label="规格" min-width="150"><template #default="{row}">{{ salesOrderLine(row)?.specification_display || salesOrderLine(row)?.customer_specification_snapshot || salesOrderLine(row)?.specification_snapshot }}</template></el-table-column><el-table-column label="材质" width="130"><template #default="{row}">{{ salesOrderLine(row)?.material_snapshot || '—' }}</template></el-table-column><el-table-column label="可分配量" width="140" align="right"><template #default="{row}">{{ formatQuantity(sourceLine(row)?.remaining_quantity || 0) }} {{ unitName(row) }}</template></el-table-column><el-table-column v-if="activeStep === 2" label="本次生产数量" width="160" align="right" header-align="center"><template #default="{row}"><el-input-number v-model="row.quantity" :min="1" :max="Math.floor(Number(sourceLine(row)?.remaining_quantity || 0))" :precision="0" :controls="false"/></template></el-table-column><el-table-column label="人民币单价" width="145" align="right"><template #default="{row}">{{ money(salesOrderLine(row)?.unit_price_cny) }}</template></el-table-column><el-table-column label="订单行金额（CNY）" width="170" align="right"><template #default="{row}">{{ money(salesOrderLine(row)?.line_total_cny) }}</template></el-table-column><el-table-column v-if="activeStep === 2" label="本次金额（CNY）" width="170" align="right"><template #default="{row}">{{ money(multiplyAmount4(row.quantity, salesOrderLine(row)?.unit_price_cny)) }}</template></el-table-column></el-table></div>
          </template>
          <div v-if="manualMode && activeStep <= 2" class="table-frame"><el-table :data="manualProducts" empty-text="尚未录入产品"><el-table-column label="图片" width="72"><template #default="{row}"><ProductImage :src="row.preview" :name="row.item.product_description"/></template></el-table-column><el-table-column label="货号" width="120"><template #default="{row}">{{ row.item.product_id ? row.item.item_number_snapshot : '' }}</template></el-table-column><el-table-column label="名称" min-width="160"><template #default="{row}">{{ row.item.product_description }}</template></el-table-column><el-table-column label="颜色" width="110"><template #default="{row}">{{ row.item.color || '—' }}</template></el-table-column><el-table-column label="规格" min-width="140"><template #default="{row}">{{ row.item.specification }}</template></el-table-column><el-table-column label="材质" width="130"><template #default="{row}">{{ row.item.material || '—' }}</template></el-table-column><el-table-column label="数量" width="130" align="right"><template #default="{row}">{{ row.item.quantity }} {{ catalogUnits.find(unit => unit.id === row.item.product_unit_id)?.unit_name }}</template></el-table-column><el-table-column label="人民币单价" width="140" align="right"><template #default="{row}">{{ money(row.item.target_unit_price || 0) }}</template></el-table-column><el-table-column label="本次金额" width="150" align="right"><template #default="{row}">{{ money(multiplyAmount4(row.item.quantity, row.item.target_unit_price)) }}</template></el-table-column><el-table-column label="操作" width="130" fixed="right"><template #default="{row,$index}"><el-button link type="primary" @click="activeStep = 1; editManual(row)">编辑</el-button><el-button link type="danger" @click="removeManual($index)">移除</el-button></template></el-table-column></el-table></div>
          <div v-if="activeStep === 2" class="totals"><strong>本次生产 {{ manualMode ? manualProducts.map(row => `${row.item.quantity} ${catalogUnits.find(unit => unit.id === row.item.product_unit_id)?.unit_name || ''}`).join(' / ') : quantitySummary('production') }}</strong><strong>本次金额 CNY {{ money(currentAmount) }}</strong></div>
          <template v-if="activeStep === 3">
            <div class="section-title"><h2>生产安排</h2><p>人工填写 HT 编号，独立选择生产跟单员；来源业务员和下单日期只读。</p></div>
            <div class="plan-grid">
              <label><span>生产任务单号 *</span><el-popover placement="bottom-start" trigger="focus" :width="300"><template #reference><el-input v-model="taskNumberSuffix" maxlength="48" placeholder="例如 26199 或 26199-1"><template #prepend>HT</template></el-input></template><strong>最近五个真实编号</strong><ol class="recent-numbers"><li v-for="number in options?.recent_task_numbers?.slice(0,5)" :key="number">{{ number }}</li><li v-if="!options?.recent_task_numbers?.length">暂无历史编号</li></ol></el-popover></label>
              <label><span>生产跟单员 *</span><el-select v-model="plan.followerIds" multiple filterable placeholder="请选择生产跟单员"><el-option v-for="employee in options?.employees || []" :key="employee.id" :value="employee.id" :label="employee.display_name"/></el-select></label>
              <label><span>业务员 *</span><el-select v-model="plan.salespersonId" filterable :disabled="!manualMode"><el-option v-for="employee in options?.salespeople || []" :key="employee.id" :value="employee.id" :label="employee.display_name"/></el-select></label>
              <label><span>下单日期 *</span><el-date-picker v-model="plan.orderDate" type="date" value-format="YYYY-MM-DD" :disabled="!manualMode"/></label>
              <label><span>交期 *</span><el-date-picker v-model="plan.deliveryDate" type="date" value-format="YYYY-MM-DD"/></label>
              <label><span>是否含税 *</span><el-select v-model="plan.includesTax"><el-option label="含税" :value="true"/><el-option label="不含税" :value="false"/></el-select></label>
              <label v-if="plan.includesTax"><span>税率 *</span><el-select v-model="plan.taxRate" placeholder="请选择税率"><el-option v-for="rate in [3,5,7]" :key="rate" :value="rate" :label="`${rate}%`"/></el-select></label>
              <label><span>订单误差 *</span><el-input v-model="plan.tolerance"><template #append>%</template></el-input></label>
              <label><span>是否返单 *</span><el-select v-model="plan.isRepeat"><el-option label="是" :value="true"/><el-option label="否" :value="false"/></el-select></label>
              <label><span>交货方式 *</span><el-select v-model="plan.deliveryMethod"><el-option label="一次交货" value="SINGLE"/><el-option label="分批交货" value="SPLIT"/></el-select></label>
              <label v-if="manualMode"><span>产前确认样</span><el-select v-model="plan.preproductionSample"><el-option label="是" :value="true"/><el-option label="否" :value="false"/></el-select></label><label><span>计划员</span><el-select v-model="plan.plannerId" clearable filterable><el-option v-for="employee in options?.employees || []" :key="employee.id" :value="employee.id" :label="employee.display_name"/></el-select></label>
              <label><span>生产优先级</span><el-select v-model="plan.productionPriority"><el-option label="紧急" value="URGENT"/><el-option label="高" value="HIGH"/><el-option label="普通" value="NORMAL"/><el-option label="低" value="LOW"/></el-select></label>
              <label><span>计划开始</span><el-date-picker v-model="plan.plannedStartDate" type="date" value-format="YYYY-MM-DD"/></label><label><span>计划完工</span><el-date-picker v-model="plan.plannedEndDate" type="date" value-format="YYYY-MM-DD"/></label><label><span>生产批号</span><el-input v-model="plan.productionBatchNumber" maxlength="100"/></label>
            </div>
            <h3>生产要求</h3>
            <div v-if="!manualMode" v-for="line in colorLines" :key="line.key" class="requirement-row"><strong>{{ sourceLine(line)?.product_name }} · {{ sourceColorText(line) }}</strong><label><span>包装要求</span><el-input v-model="line.packagingMethod" type="textarea" :rows="2" maxlength="2000"/></label><label><span>生产要求</span><el-input v-model="line.specialRequirements" type="textarea" :rows="2" maxlength="2000"/></label></div>
            <div v-else v-for="row in manualProducts" :key="row.key" class="requirement-row"><label><span>{{ row.item.product_description }} · 生产要求</span><el-input v-model="row.item.notes" type="textarea" :rows="2" maxlength="2000"/></label><label><span>包装要求</span><el-input v-model="row.packagingMethod" type="textarea" :rows="2" maxlength="2000"/></label><div class="manual-details"><strong>生产任务单明细</strong><div v-for="detail in row.details" :key="detail.client_key" class="manual-detail-line"><el-input v-model="detail.detail_type" placeholder="明细类型（必填）"/><el-input v-model="detail.category_label" placeholder="类别项"/><el-checkbox v-model="detail.is_selected">需要</el-checkbox><el-input v-model="detail.description" placeholder="本次要求描述"/></div></div></div>
          </template>
          <template v-if="activeStep === 4"><div class="section-title"><h2>核对并提交</h2><p>保存草稿后可以继续修改，提交 PMC 后进入确认流程。</p></div><dl class="review-summary"><dt>任务编号</dt><dd>HT{{ taskNumberSuffix }}</dd><dt>来源</dt><dd>{{ manualMode ? '手动创建' : `${order?.order_number} · ${selectedBatch?.batch_number}` }}</dd><dt>生产跟单员</dt><dd>{{ plan.followerIds.map(id => options?.employees.find(row => row.id === id)?.display_name).join('、') }}</dd><dt>交期</dt><dd>{{ plan.deliveryDate }}</dd><dt>税务</dt><dd>{{ plan.includesTax ? `含税 ${plan.taxRate}%` : '不含税' }}</dd><dt>订单误差</dt><dd>{{ plan.tolerance }}%</dd><dt>本次金额</dt><dd>CNY {{ money(currentAmount) }}</dd><dt>计划安排</dt><dd>{{ priorityLabel(plan.productionPriority) }} · {{ plan.plannedStartDate || '待确认' }} 至 {{ plan.plannedEndDate || '待确认' }}</dd></dl></template>
          <footer class="form-actions"><el-button v-if="activeStep === 1" @click="router.push({ name: 'production-tasks' })">返回列表</el-button><el-button v-else :disabled="submitting" @click="activeStep--">上一步</el-button><span/><el-button v-if="activeStep < 4" type="primary" :disabled="loading || orderLoading" @click="nextStep">{{ activeStep === 1 ? '选择并继续' : '下一步' }}</el-button><template v-else><el-button :loading="submitting" @click="save(false)">保存草稿</el-button><el-button type="primary" :loading="submitting" @click="save(true)">保存并提交 PMC</el-button></template></footer>
        </main>
      </div>
    </div>
  </section>
</template>
<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;
// 只隐藏本页主内容区的滚动条，保留滚轮、触控和键盘滚动。
:global(#erp-main-content:has(.production-create-page)) {
  scrollbar-width: none;
}
:global(#erp-main-content:has(.production-create-page)::-webkit-scrollbar) {
  display: none;
}
.production-create-page { box-sizing:border-box; padding:0; min-width:0; color:var(--erp-color-text-primary); background:transparent; font-family:"Microsoft YaHei","Noto Sans SC",sans-serif; font-size:13px; --el-color-primary:var(--erp-color-brand); }
.page-heading { display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }
.page-heading h1 { margin:0; font:700 34px/44px "Noto Serif SC","Songti SC",serif; }
.page-heading p { margin:4px 0 0; color:var(--erp-color-text-secondary); }
.draft-tag { padding:5px 12px; background:var(--erp-tag-warning-background); color:var(--erp-color-text-inverse); border-radius:5px; }
.creation-card { @include detail.surface; overflow:hidden; }
.creation-modes { display:flex; border-bottom:1px solid var(--erp-color-border-subtle); padding:0 20px; gap:28px; }
.creation-modes button { height:48px; padding:0 4px; border:0; border-bottom:2px solid transparent; color:var(--erp-color-text-secondary); background:transparent; font:inherit; cursor:pointer; }
.creation-modes button.active { border-bottom-color:var(--erp-color-brand); color:var(--erp-color-brand); font-weight:700; }
.creation-body { display:grid; grid-template-columns:160px minmax(0,1fr); min-height:600px; }
.steps { margin:0; padding:24px 14px; list-style:none; border-right:1px solid var(--erp-color-border); background:var(--erp-glass-inner-background); }
.steps li { display:flex; gap:10px; margin-bottom:32px; color:var(--erp-color-text-secondary); }
.steps b { display:grid; place-items:center; flex:none; width:24px; height:24px; border:1px solid var(--erp-color-border); border-radius:50%; font-size:12px; }
.steps .active { color:var(--erp-color-brand); }.steps .active b { background:var(--erp-color-brand); border-color:var(--erp-color-brand); color:var(--erp-color-text-inverse); }.steps .done b { background:var(--erp-color-subtle); }
.steps span { font-weight:600; line-height:22px; }.steps small { display:block; margin-top:5px; font-size:11px; line-height:18px; color:var(--erp-color-text-secondary); }
.workspace { min-width:0; display:flex; flex-direction:column; padding:20px; gap:14px; }
.section-title { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:6px; }.section-title h2 { margin:0; font-size:18px; }.section-title h3 { margin:0; }.section-title p { flex-basis:100%; margin:0; color:var(--erp-color-text-secondary); }
h3 { margin:4px 0; font-size:14px; }
.search-row { display:flex; gap:10px; }.search-row .el-input { max-width:480px; }
.table-frame { min-width:0; width:100%; border:1px solid var(--erp-table-grid); border-radius:var(--erp-radius-control); overflow:hidden; box-sizing:border-box; }
.table-frame :deep(.el-table) { --el-table-border-color:var(--erp-table-grid); --el-table-header-bg-color:var(--erp-table-header-fill); --el-table-tr-bg-color:var(--erp-table-body-fill); --el-table-row-hover-bg-color:var(--erp-color-hover); --el-table-header-text-color:var(--erp-table-header-text); font-size:13px; }
.table-frame :deep(.el-table__inner-wrapper::before) { display:none; }
.production-create-page .table-frame :deep(.el-table .el-table__header-wrapper th.el-table__cell) { padding:0 !important; height:44px !important; font-size:13px !important; line-height:22px !important; font-weight:600; background:var(--erp-table-header-fill); }
/* 本页34px行高覆盖全局40px，人民币价格按单行展示。 */
.production-create-page .table-frame :deep(.el-table .el-table__body tr),
.production-create-page .table-frame :deep(.el-table .el-table__body-wrapper td.el-table__cell) { padding:0 !important; height:34px !important; font-size:13px !important; line-height:22px !important; }
.production-create-page .table-frame :deep(.el-table .el-table__cell > .cell) { padding:0 16px !important; font-size:13px !important; line-height:22px !important; }
.table-frame :deep(.el-table__row:last-child td) { border-bottom:0; }
.table-frame :deep(.el-table__fixed-right-patch) { display:none; }
.table-frame :deep(.el-input-number) { width:100%; }
.table-frame :deep(.product-image) { width:32px; height:32px; }
.table-frame small { display:block; color:var(--erp-color-text-secondary); font-size:11px; }
.source-context,.totals { display:flex; flex-wrap:wrap; gap:12px 24px; align-items:center; @include detail.inset; padding:12px 16px; }.source-context strong { margin-left:auto; }.totals { justify-content:space-between; }
.plan-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; }
.plan-grid label>span,.requirement-row label>span { display:block; margin-bottom:7px; font-weight:600; }
.plan-grid :deep(.el-select), .plan-grid :deep(.el-date-editor) { width:100%; }
.production-create-page :deep(.el-input__wrapper),.production-create-page :deep(.el-select__wrapper) { min-height:32px; height:32px; box-sizing:border-box; border-radius:5px; font-size:13px; }
.production-create-page :deep(.el-button) { height:32px; margin-left:0; border-radius:5px; font-size:13px; }
.requirement-row { display:grid; grid-template-columns:1fr 1fr; gap:12px; padding:14px; @include detail.inset; }.requirement-row>strong { grid-column:1/-1; }
.manual-details { grid-column:1/-1; }.manual-detail-line { display:grid; grid-template-columns:150px 150px 80px minmax(120px,1fr); gap:12px; margin-top:10px; }
.review-summary { display:grid; grid-template-columns:140px 1fr; gap:16px; margin:8px 0 28px; }.review-summary dt { color:var(--erp-color-text-secondary); }.review-summary dd { margin:0; }
.form-actions { display:flex; align-items:center; gap:10px; border-top:1px solid var(--erp-color-border-subtle); padding-top:16px; margin-top:auto; }.form-actions>span { flex:1; }
.recent-numbers { padding-left:20px; line-height:28px; }
@media(max-width:1250px) { .plan-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } .workspace { padding:16px; } }
</style>
