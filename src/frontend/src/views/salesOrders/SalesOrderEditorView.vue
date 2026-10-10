<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Delete, Picture, Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'

import {
  changeConfirmedSalesOrder,
  confirmSalesOrder,
  createSalesOrder,
  fetchQuotationOrderContext,
  fetchSalesOrder,
  fetchSalesOrderOptions,
  updateSalesOrder,
} from '@/api/salesOrders'
import { fetchAllProductionDataRecords } from '@/api/productionData'
import { useAuthStore } from '@/stores/auth'
import BuyerMasterDataDialog from '@/components/business/BuyerMasterDataDialog.vue'
import SellerProfileDialog from '@/components/business/SellerProfileDialog.vue'
import SellerSubjectCard from '@/components/business/SellerSubjectCard.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { CustomerAddress } from '@/types/customer'
import type { QuotationTemplate } from '@/types/quotation'
import type { ProductColor } from '@/types/productionData'
import type { QuotationOrderContext, SalesOrder, SalesOrderBatchInput, SalesOrderInput, SalesOrderLineInput, SalesOrderOptions, SalesOrderProduct, SalesOrderSource } from '@/types/salesOrder'

interface EditorBatch extends SalesOrderBatchInput { key: string }

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const orderId = computed(() => typeof route.params.orderId === 'string' ? route.params.orderId : '')
const isEdit = computed(() => Boolean(orderId.value))
const loading = ref(false)
const saving = ref(false)
const options = ref<SalesOrderOptions | null>(null)
const pinnedProductChoices = ref<SalesOrderProduct[]>([])
const productSearchChoices = ref<SalesOrderProduct[]>([])
const productColors = ref<ProductColor[]>([])
const etag = ref('')
const existingOrder = ref<SalesOrder | null>(null)
const batches = ref<EditorBatch[]>([])
const quoteContext = ref<QuotationOrderContext | null>(null)
const activeDetailTab = ref('base')
const selectedRequirementLineKey = ref('')
const buyerDialogVisible = ref(false)
const buyerDialogTab = ref<'entity' | 'address' | 'contact'>('address')
const sellerDialogVisible = ref(false)
const deleteBatchDialogVisible = ref(false)
const deleteBatchIndex = ref<number | null>(null)
const conflictVisible = ref(false)
const unsavedDialogVisible = ref(false)
const isDirty = ref(false)
const trackingChanges = ref(false)
const pendingRoute = ref('')
const changeForm = reactive({ change_reason: '', customer_facing_change: false, change_evidence_file_id: null as string | null, pmc_impact_confirmed: false })
const isConfirmedEdit = computed(() => Boolean(existingOrder.value && existingOrder.value.status !== 'DRAFT'))
const hasLockedStructure = computed(() => isConfirmedEdit.value)
const canSaveOrder = computed(() => !authStore.user?.sales_access_enabled || (isEdit.value
  ? authStore.canFor(isConfirmedEdit.value ? 'access_control.confirmedchange_salesorder' : 'sales_orders.change_salesorder', existingOrder.value)
  : authStore.hasPermission('sales_orders.add_salesorder')))
const canConfirmOrder = computed(() => !authStore.user?.sales_access_enabled || (isConfirmedEdit.value
  ? canSaveOrder.value
  : existingOrder.value ? authStore.canFor('access_control.confirm_salesorder', existingOrder.value) : authStore.hasPermission('access_control.confirm_salesorder')))
function stableJson(value: Record<string, unknown>): string {
  return JSON.stringify(Object.keys(value || {}).sort().reduce<Record<string, unknown>>((result, key) => {
    result[key] = value[key]
    return result
  }, {}))
}
const customerFactsChanged = computed(() => {
  const original = existingOrder.value
  if (!isConfirmedEdit.value || !original) return false
  const headerPairs: Array<[unknown, unknown]> = [
    [form.transaction_entity_id, original.transaction_entity_id], [form.customer_po_number, original.customer_po_number],
    [form.buyer_address_id, original.buyer_address_id],
    [form.contract_number, original.contract_number], [form.order_date, original.order_date], [form.currency_code, original.currency_code],
    [form.exchange_rate, original.exchange_rate], [form.incoterm_code, original.incoterm_code], [form.payment_terms, original.payment_terms],
    [form.deposit_required, original.deposit_required], [form.includes_tax, original.includes_tax], [form.tax_basis, original.tax_basis],
    [form.order_tolerance_percent, original.order_tolerance_percent], [form.preproduction_sample_required, original.preproduction_sample_required],
    [form.confirmation_method, original.confirmation_method], [form.customer_confirmer, original.customer_confirmer],
    [form.customer_confirmed_at, original.customer_confirmed_at], [form.confirmation_summary, original.confirmation_summary],
  ]
  if (headerPairs.some(([current, before]) => String(current ?? '') !== String(before ?? ''))) return true
  if (stableJson(form.buyer_snapshot) !== stableJson(original.buyer_snapshot)) return true
  if (stableJson(form.buyer_address_snapshot) !== stableJson(original.buyer_address_snapshot)) return true
  const originalLines = new Map(original.lines.map((line) => [line.id, line]))
  if (lines.value.some((line) => {
    const before = originalLines.get(line.client_key)
    return !before || [
      [line.quantity, before.quantity], [line.unit_price, before.unit_price], [line.lower_price_reason, before.lower_price_reason],
      [line.quality_requirements, before.quality_requirements], [line.packaging_requirements, before.packaging_requirements],
      [line.shipping_mark_requirements, before.shipping_mark_requirements],
    ].some(([current, old]) => String(current ?? '') !== String(old ?? ''))
  })) return true
  const originalBatches = new Map(original.delivery_batches.map((batch) => [batch.id, batch]))
  return batches.value.some((batch) => {
    const before = originalBatches.get(batch.key)
    if (!before || batch.planned_delivery_date !== before.planned_delivery_date || batch.notes !== before.notes) return true
    const oldQuantities = new Map(before.lines.map((line) => [line.sales_order_line_id, line.quantity]))
    return batch.lines.some((line) => String(line.quantity) !== String(oldQuantities.get(line.sales_order_line_client_key) ?? ''))
  })
})
let keySequence = 0
const newKey = (prefix: string) => `${prefix}-${Date.now()}-${++keySequence}`
const today = new Date().toISOString().slice(0, 10)

const form = reactive<Omit<SalesOrderInput, 'lines' | 'delivery_batches'>>({
  source_type: (route.query.source === 'QUOTATION' ? 'QUOTATION' : 'DIRECT') as SalesOrderSource,
  source_quotation_version_id: null,
  customer_account_id: '',
  transaction_entity_id: null,
  buyer_address_id: null,
  salesperson_id: authStore.user?.employee?.id || '',
  merchandiser_id: null,
  customer_po_number: '',
  contract_number: '',
  order_date: today,
  direct_order_reason: '',
  currency_code: 'USD',
  exchange_rate: '1',
  incoterm_code: '',
  payment_terms: '',
  deposit_required: false,
  includes_tax: false,
  tax_basis: '',
  order_tolerance_percent: '0',
  preproduction_sample_required: false,
  buyer_snapshot: {},
  buyer_address_snapshot: {},
  seller_snapshot: {},
  terms_snapshot: {},
  customer_requirement_snapshot: {},
  confirmation_method: '',
  customer_confirmer: '',
  customer_confirmed_at: null,
  confirmation_summary: '',
  evidence_file_ids: [],
})
const lines = ref<SalesOrderLineInput[]>([])
const customerEntities = computed(() => (options.value?.transaction_entities || []).filter((item) => item.customer_account_id === form.customer_account_id))
const buyerAddresses = computed(() => (options.value?.buyer_addresses || []).filter((item) => item.transaction_entity_id === form.transaction_entity_id))
const selectedBuyerAddress = computed(() => buyerAddresses.value.find((item) => item.id === form.buyer_address_id) || null)
const selectedBuyerEntity = computed(() => customerEntities.value.find((item) => item.id === form.transaction_entity_id) || null)
const buyerAddressDisplay = computed(() => {
  if (selectedBuyerAddress.value) return addressSummary(selectedBuyerAddress.value as unknown as Record<string, unknown>)
  return addressSummary(existingOrder.value?.buyer_address_snapshot || quoteContext.value?.buyer_address_snapshot || {})
})
const productChoices = computed(() => [...new Map([
  ...pinnedProductChoices.value,
  ...productSearchChoices.value,
].map(item => [item.id, item])).values()])
const productById = computed(() => new Map(productChoices.value.map((item) => [item.id, item])))
const productCategories = computed(() => [...new Map(productChoices.value
  .filter((item) => item.category_id && item.category_name)
  .map((item) => [item.category_id!, { id: item.category_id!, name: item.category_name! }])).values()])
const systemColorChoices = computed(() => productColors.value.map((item) => item.color_name).filter(Boolean))
const quoteLineById = computed(() => new Map((quoteContext.value?.lines || []).map((item) => [item.id, item])))
const quoteHasNoRemaining = computed(() => Boolean(
  form.source_type === 'QUOTATION'
  && quoteContext.value
  && quoteContext.value.lines.every((item) => Number(item.remaining_quantity) <= 0),
))
const orderTotal = computed(() => lines.value.reduce((sum, line) => sum + Number(line.quantity || 0) * Number(line.unit_price || 0), 0))
const orderQuantity = computed(() => lines.value.reduce((sum, line) => sum + Number(line.quantity || 0), 0))
const selectedRequirementLine = computed(() => lines.value.find((line) => line.client_key === selectedRequirementLineKey.value) || lines.value[0] || null)
const requirementLineSelection = computed({
  get: () => selectedRequirementLine.value?.client_key || '',
  set: (value: string) => { selectedRequirementLineKey.value = value },
})
const sourceQuoteLabel = computed(() => {
  const context = quoteContext.value
  return context ? `${context.quotation_number} V${context.version_number}` : '请选择客户已接受的报价'
})
const sellerLegalName = computed({
  get: () => {
    const snapshot = form.seller_snapshot as Record<string, unknown>
    const templateConfig = snapshot.template_config as Record<string, unknown> | undefined
    return String(templateConfig?.seller_company_name || snapshot.seller_company_name || snapshot.legal_name || '')
  },
  set: (value: string) => {
    form.seller_snapshot = { ...form.seller_snapshot, seller_company_name: value.trim() }
  },
})
const sellerTemplateId = computed(() => quoteContext.value?.seller_template_id || options.value?.seller_template?.id || null)
const sellerCardSnapshot = computed<Record<string, unknown>>(() => form.seller_snapshot)
const pendingDeleteBatch = computed(() => deleteBatchIndex.value === null ? null : batches.value[deleteBatchIndex.value] || null)
const pendingDeleteReleasedLines = computed(() => {
  const batch = pendingDeleteBatch.value
  if (!batch) return []
  return lines.value.map((line) => ({
    key: line.client_key,
    product: productDisplayName(line),
    quantity: batchQuantity(batch, line.client_key),
    unit: quoteLineById.value.get(line.source_quotation_line_id || '')?.unit_code || productById.value.get(line.product_id || '')?.unit_code || '-',
  })).filter((item) => item.quantity > 0)
})
const primaryDeliveryDate = computed({
  get: () => batches.value[0]?.planned_delivery_date || form.order_date,
  set: (value: string) => {
    if (!batches.value.length) addBatch()
    if (batches.value[0]) batches.value[0].planned_delivery_date = value
  },
})
const pageStatusLabel = computed(() => existingOrder.value?.status_display || '草稿')
const pageTitle = computed(() => isConfirmedEdit.value
  ? `销售订单变更 · V${existingOrder.value?.version_number || 1}`
  : isEdit.value ? '编辑销售订单' : '新建销售订单')
const sourceSelection = computed({
  get: () => form.source_type === 'QUOTATION'
    ? (form.source_quotation_version_id ? `QUOTATION:${form.source_quotation_version_id}` : '')
    : form.source_type,
  set: (value: string) => {
    if (value.startsWith('QUOTATION:')) {
      const versionId = value.slice('QUOTATION:'.length)
      form.source_type = 'QUOTATION'
      form.source_quotation_version_id = versionId
      void loadQuote(versionId)
      return
    }
    form.source_type = value as SalesOrderSource
    form.source_quotation_version_id = null
    quoteContext.value = null
    lines.value = []
    batches.value = []
    addLine()
    addBatch()
  },
})

function addLine() {
  lines.value.push({
    client_key: newKey('line'), source_quotation_line_id: null, product_id: null,
    product_category_id: '', product_name_input: '', customer_product_name_snapshot: '',
    customer_specification_snapshot: '', customer_color_snapshot: '', quantity: '1', unit_price: '0',
    lower_price_reason: '', quality_requirements: '', packaging_requirements: '', shipping_mark_requirements: '',
  })
  syncBatchLines()
}
function addBatch() {
  batches.value.push({
    key: newKey('batch'), planned_delivery_date: form.order_date, notes: '',
    lines: lines.value.map((line) => ({ sales_order_line_client_key: line.client_key, quantity: '0' })),
  })
}
function syncBatchLines() {
  const keys = new Set(lines.value.map((line) => line.client_key))
  for (const batch of batches.value) {
    batch.lines = batch.lines.filter((item) => keys.has(item.sales_order_line_client_key))
    for (const line of lines.value) {
      if (!batch.lines.some((item) => item.sales_order_line_client_key === line.client_key)) {
        batch.lines.push({ sales_order_line_client_key: line.client_key, quantity: '0' })
      }
    }
  }
}
function removeLine(index: number) {
  lines.value.splice(index, 1)
  syncBatchLines()
}
function productLabel(id: string | null | undefined) {
  if (!id) return '未映射产品'
  const item = productById.value.get(id)
  return item ? `${item.product_number} · ${item.product_name}` : '未映射产品'
}
function productNameChoices(line: SalesOrderLineInput) {
  const values = productChoices.value.filter((item) => !line.product_category_id || item.category_id === line.product_category_id)
  return [...new Map(values.map((item) => [item.product_name, item])).values()]
}
function specificationChoices(line: SalesOrderLineInput) {
  const name = String(line.product_name_input || '').trim()
  if (!name) return []
  return productChoices.value.filter((item) => (!line.product_category_id || item.category_id === line.product_category_id) && item.product_name === name)
}
function selectProductCategory(line: SalesOrderLineInput) {
  line.product_id = null
  line.product_name_input = ''
  line.customer_product_name_snapshot = ''
  line.customer_specification_snapshot = ''
}
function selectProductName(line: SalesOrderLineInput, name: string) {
  line.product_id = null
  line.product_name_input = name
  line.customer_product_name_snapshot = name
  line.customer_specification_snapshot = ''
}
function matchProductInformation(line: SalesOrderLineInput) {
  const productName = String(line.product_name_input || line.customer_product_name_snapshot || '').trim()
  const specification = String(line.customer_specification_snapshot || '').trim()
  line.product_name_input = productName
  line.customer_product_name_snapshot = productName
  line.customer_specification_snapshot = specification
  const matched = productChoices.value.find((item) => (
    item.product_name === productName
    && item.specification === specification
    && (!line.product_category_id || item.category_id === line.product_category_id)
  ))
  line.product_id = matched?.id || null
  if (matched) {
    line.customer_product_name_snapshot = matched.product_name
    line.customer_specification_snapshot = matched.specification
  }
}
function selectProductSpecification(line: SalesOrderLineInput, specification: string) {
  line.customer_specification_snapshot = specification
  matchProductInformation(line)
}
function unitDisplay(line: SalesOrderLineInput) {
  const quoteUnit = quoteLineById.value.get(line.source_quotation_line_id || '')?.unit_code
  const product = productById.value.get(line.product_id || '')
  return product?.unit_name || product?.unit_code || quoteUnit || '-'
}
function productDisplayName(line: SalesOrderLineInput) {
  return line.customer_product_name_snapshot || line.product_name_input || productLabel(line.product_id || '')
}
function allocation(batch: EditorBatch, lineKey: string) {
  return batch.lines.find((item) => item.sales_order_line_client_key === lineKey)!
}
function batchQuantity(batch: EditorBatch, lineKey: string): number {
  return Number(batch.lines.find((item) => item.sales_order_line_client_key === lineKey)?.quantity || 0)
}
function setBatchQuantity(batch: EditorBatch, lineKey: string, value: number | undefined) {
  const existing = batch.lines.find((item) => item.sales_order_line_client_key === lineKey)
  if (existing) existing.quantity = String(value || 0)
  else if (!hasLockedStructure.value && Number(value || 0) > 0) batch.lines.push({ sales_order_line_client_key: lineKey, quantity: String(value) })
}
function allocatedQuantity(lineKey: string): number {
  return batches.value.reduce((sum, batch) => sum + Number(allocation(batch, lineKey)?.quantity || 0), 0)
}
function remainingQuantity(line: SalesOrderLineInput): number {
  return Number(line.quantity || 0) - allocatedQuantity(line.client_key)
}
function lineAllocationState(line: SalesOrderLineInput): 'under' | 'over' | 'complete' {
  const difference = remainingQuantity(line)
  if (difference > 0.00001) return 'under'
  if (difference < -0.00001) return 'over'
  return 'complete'
}
function batchAllocationState(_batch: EditorBatch): 'under' | 'over' | 'complete' {
  if (lines.value.some((line) => lineAllocationState(line) === 'over')) return 'over'
  if (lines.value.some((line) => lineAllocationState(line) === 'under')) return 'under'
  return 'complete'
}
function batchStateLabel(batch: EditorBatch) {
  const state = batchAllocationState(batch)
  return state === 'over' ? '存在超分' : state === 'under' ? '尚未完全分配' : '数量完全分配'
}
function batchTotal(batch: EditorBatch) {
  return batch.lines.reduce((sum, item) => sum + Number(item.quantity || 0), 0)
}
function openDeleteBatch(index: number) {
  if (hasLockedStructure.value) return
  deleteBatchIndex.value = index
  deleteBatchDialogVisible.value = true
}
function confirmDeleteBatch() {
  if (deleteBatchIndex.value === null) return
  batches.value.splice(deleteBatchIndex.value, 1)
  deleteBatchDialogVisible.value = false
  deleteBatchIndex.value = null
  ElMessage.warning('交付批次已删除，数量没有自动重分，请检查黄色未分配提示。')
}
function openBuyerDialog(tab: 'entity' | 'address' | 'contact' = 'address') {
  if (!form.customer_account_id || !form.transaction_entity_id) {
    ElMessage.warning('请先选择客户账户和买方主体。')
    return
  }
  buyerDialogTab.value = tab
  buyerDialogVisible.value = true
}
function handleBuyerAddressSelected(address: CustomerAddress | null) {
  form.buyer_address_id = address?.id || null
  form.buyer_address_snapshot = address ? { ...address } : {}
}
function handleBuyerEntitySelected(entityId: string | null) {
  const entity = customerEntities.value.find((item) => item.id === entityId)
  form.buyer_snapshot = entity ? { ...entity } : {}
}
function handleBuyerAddressIdSelected(addressId: string | null) {
  const address = buyerAddresses.value.find((item) => item.id === addressId)
  form.buyer_address_snapshot = address ? { ...address } : {}
}
async function handleBuyerAddressSaved(address: CustomerAddress) {
  options.value = await fetchSalesOrderOptions()
  form.buyer_address_id = address.id
  form.buyer_address_snapshot = { ...address }
}
function handleBuyerEntityUpdated(entity: { id: string; entity_code: string; legal_name: string }) {
  form.buyer_snapshot = { ...form.buyer_snapshot, id: entity.id, entity_code: entity.entity_code, legal_name: entity.legal_name }
}
function handleSellerSaved(template: QuotationTemplate) {
  if (options.value) options.value.seller_template = template
  form.seller_snapshot = {
    id: template.id,
    template_code: template.template_code,
    template_name: template.template_name,
    template_version: template.template_version,
    requires_approval: template.requires_approval,
    template_config: template.template_config,
  }
}
function addressSummary(snapshot: Record<string, unknown>) {
  return [snapshot.address_line1, snapshot.address_line2, snapshot.city, snapshot.state_province, snapshot.postal_code, snapshot.country_code]
    .filter((item) => typeof item === 'string' && item.trim())
    .join('，')
}
function apiErrorCode(error: unknown): string {
  return String((error as { response?: { data?: { error?: { code?: string } } } })?.response?.data?.error?.code || '')
}
function apiStatus(error: unknown): number {
  return Number((error as { response?: { status?: number } })?.response?.status || 0)
}
function apiError(error: unknown): string {
  const response = (error as { response?: { data?: { detail?: string; error?: { message?: string; field_errors?: Record<string, string[]> } } } })?.response?.data
  const field = response?.error?.field_errors ? Object.values(response.error.field_errors).flat()[0] : ''
  return field || response?.error?.message || response?.detail || (error instanceof Error ? error.message : '') || '保存失败，请检查必填内容。'
}

function pinProductChoices(items: SalesOrderProduct[]) {
  pinnedProductChoices.value = [...new Map([
    ...pinnedProductChoices.value,
    ...items,
  ].map(item => [item.id, item])).values()]
}

async function loadQuote(versionId: string) {
  if (!versionId) return
  loading.value = true
  try {
    const context = await fetchQuotationOrderContext(versionId)
    quoteContext.value = context
    pinProductChoices(context.lines.flatMap(item => item.suggested_product ? [item.suggested_product] : []))
    form.customer_account_id = context.customer_account_id
    form.transaction_entity_id = context.transaction_entity_id
    form.buyer_address_id = context.buyer_address_id
    form.salesperson_id = context.salesperson_id
    form.currency_code = context.currency_code
    form.buyer_snapshot = context.buyer_snapshot
    form.buyer_address_snapshot = context.buyer_address_snapshot
    form.seller_snapshot = context.seller_snapshot
    form.terms_snapshot = context.terms_snapshot
    form.customer_requirement_snapshot = context.customer_requirement_snapshot
    const quotationTerms = context.terms_snapshot || {}
    form.incoterm_code = String(quotationTerms.incoterm_label || quotationTerms.incoterm_code || '')
    form.payment_terms = String(quotationTerms.payment_terms || '')
    form.deposit_required = Number(quotationTerms.deposit_percent || 0) > 0
    lines.value = context.lines.filter((item) => Number(item.remaining_quantity) > 0).map((item) => ({
      client_key: newKey('quote'),
      source_quotation_line_id: item.id,
      product_id: item.suggested_product_id || null,
      product_category_id: item.suggested_product?.category_id || '',
      product_name_input: item.suggested_product?.product_name || item.product_description || '',
      customer_product_name_snapshot: item.suggested_product?.product_name || item.product_description || '',
      customer_specification_snapshot: item.suggested_product?.specification || item.specification || '',
      customer_color_snapshot: item.color || '',
      quantity: item.remaining_quantity,
      unit_price: item.quoted_unit_price || '0',
      lower_price_reason: '', quality_requirements: '', packaging_requirements: '', shipping_mark_requirements: '',
    }))
    batches.value = []
    addBatch()
    lines.value.forEach((line) => { allocation(batches.value[0]!, line.client_key).quantity = line.quantity })
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
}

function addAvailableQuoteLines() {
  if (!quoteContext.value || hasLockedStructure.value) return
  const selected = new Set(lines.value.map((line) => line.source_quotation_line_id).filter(Boolean))
  const additions = quoteContext.value.lines.filter((item) => Number(item.remaining_quantity) > 0 && !selected.has(item.id))
  if (!additions.length) {
    ElMessage.info('当前报价没有可补充的剩余产品。')
    return
  }
  for (const item of additions) {
    lines.value.push({
      client_key: newKey('quote'),
      source_quotation_line_id: item.id,
      product_id: item.suggested_product_id || null,
      product_category_id: item.suggested_product?.category_id || '',
      product_name_input: item.suggested_product?.product_name || item.product_description || '',
      customer_product_name_snapshot: item.suggested_product?.product_name || item.product_description || '',
      customer_specification_snapshot: item.suggested_product?.specification || item.specification || '',
      customer_color_snapshot: item.color || '',
      quantity: item.remaining_quantity,
      unit_price: item.quoted_unit_price || '0',
      lower_price_reason: '',
      quality_requirements: '',
      packaging_requirements: '',
      shipping_mark_requirements: '',
    })
  }
  syncBatchLines()
  const targetBatch = batches.value[0]
  if (targetBatch) {
    for (const line of lines.value) {
      const target = allocation(targetBatch, line.client_key)
      if (additions.some((item) => item.id === line.source_quotation_line_id)) target.quantity = line.quantity
    }
  }
  ElMessage.success(`已补充 ${additions.length} 条报价剩余产品。`)
}

function quoteRemainingText(line: SalesOrderLineInput): string {
  if (!line.source_quotation_line_id) return '手工添加'
  const source = quoteLineById.value.get(line.source_quotation_line_id)
  if (!source) return '来源报价'
  const currentReserved = isEdit.value ? Number(line.quantity || 0) : 0
  const available = Number(source.remaining_quantity || 0) + currentReserved
  return `报价剩余 ${available.toLocaleString('zh-CN', { maximumFractionDigits: 4 })} ${source.unit_code}`
}

function quoteProductMappingHint(line: SalesOrderLineInput): string {
  if (!line.source_quotation_line_id) return ''
  const source = quoteLineById.value.get(line.source_quotation_line_id)
  if (!source) return ''
  if (line.product_id) {
    return source.suggested_product_id === line.product_id ? '已按报价产品唯一匹配' : '已人工选择对应产品'
  }
  if (source.product_mapping_status === 'AMBIGUOUS') {
    return source.product_mapping_candidate_count === 1
      ? '找到同名产品，但报价规格不一致，请人工核对'
      : `找到 ${source.product_mapping_candidate_count} 个同名产品，请按规格选择`
  }
  return '产品主数据中没有唯一匹配项，请选择已有产品或先到产品管理建档'
}

function lineTotal(line: SalesOrderLineInput): number {
  return Number(line.quantity || 0) * Number(line.unit_price || 0)
}

function localLineTotal(line: SalesOrderLineInput): number {
  return lineTotal(line) * Number(form.exchange_rate || 0)
}
async function loadExisting() {
  const result = await fetchSalesOrder(orderId.value)
  etag.value = result.etag
  const order = result.data
  existingOrder.value = order
  pinProductChoices(order.lines.filter(line => line.product_id).map(line => ({
    id: line.product_id!,
    product_number: line.product_number_snapshot,
    product_code: line.product_code_snapshot,
    product_name: line.product_name_snapshot,
    specification: line.specification_snapshot,
    unit_code: line.unit_code_snapshot,
  })))
  Object.assign(form, {
    source_type: order.source_type,
    source_quotation_version_id: order.source_quotation_version_id,
    customer_account_id: (options.value?.customers || []).find((item) => item.account_code === order.customer_code)?.id || '',
    transaction_entity_id: order.transaction_entity_id,
    buyer_address_id: order.buyer_address_id,
    salesperson_id: order.salesperson.id,
    merchandiser_id: order.merchandiser?.id || null,
    customer_po_number: order.customer_po_number,
    contract_number: order.contract_number,
    order_date: order.order_date,
    direct_order_reason: order.direct_order_reason,
    currency_code: order.currency_code,
    exchange_rate: order.exchange_rate,
    incoterm_code: order.incoterm_code,
    payment_terms: order.payment_terms,
    deposit_required: order.deposit_required,
    includes_tax: order.includes_tax,
    tax_basis: order.tax_basis,
    order_tolerance_percent: order.order_tolerance_percent,
    preproduction_sample_required: order.preproduction_sample_required,
    buyer_snapshot: order.buyer_snapshot,
    buyer_address_snapshot: order.buyer_address_snapshot,
    seller_snapshot: order.seller_snapshot,
    terms_snapshot: order.terms_snapshot,
    customer_requirement_snapshot: order.customer_requirement_snapshot,
    confirmation_method: order.confirmation_method,
    customer_confirmer: order.customer_confirmer,
    customer_confirmed_at: order.customer_confirmed_at,
    confirmation_summary: order.confirmation_summary,
    evidence_file_ids: order.evidence.map((item) => item.file_id),
  })
  const keyById = new Map<string, string>()
  lines.value = order.lines.map((line) => {
    const key = line.id
    keyById.set(line.id, key)
    return {
      client_key: key, source_quotation_line_id: line.source_quotation_line_id, product_id: line.product_id,
      product_category_id: productById.value.get(line.product_id || '')?.category_id || '',
      product_name_input: line.customer_product_name_snapshot || line.product_name_snapshot,
      customer_product_name_snapshot: line.customer_product_name_snapshot || line.product_name_snapshot,
      customer_specification_snapshot: line.customer_specification_snapshot || line.specification_snapshot,
      customer_color_snapshot: line.customer_color_snapshot || '',
      quantity: line.quantity, unit_price: line.unit_price, lower_price_reason: line.lower_price_reason,
      quality_requirements: line.quality_requirements, packaging_requirements: line.packaging_requirements,
      shipping_mark_requirements: line.shipping_mark_requirements,
    }
  })
  batches.value = order.delivery_batches.map((batch) => ({
    key: batch.id, client_key: batch.id, planned_delivery_date: batch.planned_delivery_date, notes: batch.notes,
    lines: batch.lines.map((item) => ({ sales_order_line_client_key: keyById.get(item.sales_order_line_id) || item.sales_order_line_id, quantity: item.quantity })),
  }))
  if (order.source_quotation_version_id) {
    quoteContext.value = await fetchQuotationOrderContext(order.source_quotation_version_id)
  }
  if (order.status !== 'DRAFT') activeDetailTab.value = 'products'
}

async function reloadAfterConflict() {
  conflictVisible.value = false
  loading.value = true
  trackingChanges.value = false
  try {
    await loadExisting()
    isDirty.value = false
  } catch (error) {
    existingOrder.value = null
    lines.value = []
    batches.value = []
    if (apiStatus(error) === 403) {
      ElMessage.error('你已无权查看此销售订单，旧数据已清除。')
      await router.replace({ name: 'sales-orders' })
    } else {
      ElMessage.error(apiError(error))
    }
  } finally {
    loading.value = false
    trackingChanges.value = true
  }
}

function validate(requireConfirmation: boolean): string {
  if (form.source_type === 'QUOTATION' && !form.source_quotation_version_id) return '请选择客户已接受的报价版本。'
  if (!form.customer_account_id || !form.transaction_entity_id || !form.salesperson_id || !form.order_date || !form.currency_code) return '请完整填写客户、买方主体、业务员、订单日期和币种。'
  if (!sellerLegalName.value.trim()) return '请填写卖方法人。'
  if (requireConfirmation && !form.buyer_address_id) return '确认订单前必须选择有效的买方地址。'
  if (form.source_type !== 'QUOTATION' && !form.direct_order_reason.trim()) return '无报价或返单必须填写直接下单原因。'
  if (!form.confirmation_method || !form.customer_confirmer.trim() || !form.customer_confirmed_at || !form.confirmation_summary.trim()) return '请完整填写客户确认方式、确认人、确认时间和确认摘要。'
  if (!lines.value.length || lines.value.some((line) => (
    (!line.product_id && (!String(line.customer_product_name_snapshot || '').trim() || !String(line.customer_specification_snapshot || '').trim()))
    || Number(line.quantity) <= 0 || Number(line.unit_price) < 0
  ))) return '请填写产品名称和规格，或选择对应的产品主档；数量和价格也不能缺失。'
  if (!batches.value.length || batches.value.some((batch) => !batch.planned_delivery_date)) return '请至少填写一个交付批次和交期。'
  if (batches.value.some((batch) => !batch.lines.some((line) => Number(line.quantity) > 0))) return '每个交付批次至少需要分配一个产品数量。'
  const overAllocated = lines.value.find((line) => allocatedQuantity(line.client_key) - Number(line.quantity) > 0.00001)
  if (overAllocated) return `${productDisplayName(overAllocated)} 的批次数量不能超过订单数量。`
  const underAllocated = lines.value.find((line) => Number(line.quantity) - allocatedQuantity(line.client_key) > 0.00001)
  if (requireConfirmation && underAllocated) return `${productDisplayName(underAllocated)} 尚未完全分配，草稿可以保存，但不能确认。`
  if (isConfirmedEdit.value && !changeForm.change_reason.trim()) return '确认后订单变更必须填写变更原因。'
  if (isConfirmedEdit.value && (changeForm.customer_facing_change || customerFactsChanged.value) && !changeForm.change_evidence_file_id) return '客户可见的变更必须选择客户书面确认凭证。'
  if (isConfirmedEdit.value && existingOrder.value?.has_production_orders && !changeForm.pmc_impact_confirmed) return '订单已有生产订单，请先由 PMC 确认本次变更影响。'
  return ''
}
async function save(confirmAfterSave = false) {
  if (!canSaveOrder.value || (confirmAfterSave && !canConfirmOrder.value)) return
  if (saving.value) return
  const requireConfirmation = confirmAfterSave || isConfirmedEdit.value
  const message = validate(requireConfirmation)
  if (message) {
    ElMessage.warning(message)
    if (requireConfirmation && !form.buyer_address_id) openBuyerDialog('address')
    return
  }
  saving.value = true
  try {
    const payload: SalesOrderInput = {
      ...form,
      exchange_rate: String(form.exchange_rate),
      order_tolerance_percent: String(form.order_tolerance_percent),
      lines: lines.value.map((line) => ({
        ...line,
        product_id: line.product_id || null,
        customer_product_name_snapshot: String(line.customer_product_name_snapshot || line.product_name_input || '').trim(),
        customer_specification_snapshot: String(line.customer_specification_snapshot || '').trim(),
        customer_color_snapshot: String(line.customer_color_snapshot || '').trim(),
        quantity: String(line.quantity),
        unit_price: String(line.unit_price),
      })),
      delivery_batches: batches.value.map(({ key, ...item }) => ({
        ...item,
        client_key: key,
        lines: item.lines
          .filter((line) => Number(line.quantity) > 0)
          .map((line) => ({ ...line, quantity: String(line.quantity) })),
      })),
    }
    const result = isConfirmedEdit.value
      ? await changeConfirmedSalesOrder(orderId.value, {
          order: payload,
          ...changeForm,
          customer_facing_change: changeForm.customer_facing_change || customerFactsChanged.value,
        }, etag.value)
      : isEdit.value
        ? await updateSalesOrder(orderId.value, payload, etag.value)
        : await createSalesOrder(payload)
    etag.value = result.etag
    isDirty.value = false
    if (isConfirmedEdit.value) {
      ElMessage.success(`销售订单变更已确认，当前版本 V${result.data.version_number}。`)
    } else if (confirmAfterSave) {
      if (result.data.source_type !== 'QUOTATION' && result.data.evidence.length === 0) {
        ElMessage.warning('草稿已保存。直接订单需先上传客户确认凭证，再由详情页确认。')
      } else {
        try {
          await confirmSalesOrder(result.data.id, result.etag)
          ElMessage.success('销售订单已保存并确认。')
        } catch (error) {
          isDirty.value = false
          ElMessage.error(`草稿已保存，但确认失败：${apiError(error)}`)
          await router.replace({ name: 'sales-order-detail', params: { orderId: result.data.id } })
          return
        }
      }
    } else {
      ElMessage.success('销售订单草稿已保存。')
    }
    await router.replace({ name: 'sales-order-detail', params: { orderId: result.data.id } })
  } catch (error) {
    if (apiErrorCode(error) === 'BUYER_ADDRESS_REQUIRED') openBuyerDialog('address')
    if ([409, 412].includes(apiStatus(error)) || apiErrorCode(error) === 'CONCURRENT_UPDATE') conflictVisible.value = true
    else ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

watch(() => form.customer_account_id, () => {
  if (form.transaction_entity_id && !customerEntities.value.some((item) => item.id === form.transaction_entity_id)) form.transaction_entity_id = null
})
watch(() => form.transaction_entity_id, () => {
  if (form.buyer_address_id && buyerAddresses.value.some((item) => item.id === form.buyer_address_id)) return
  form.buyer_address_id = buyerAddresses.value.length === 1 ? buyerAddresses.value[0]!.id : null
  handleBuyerAddressIdSelected(form.buyer_address_id)
})
watch([form, lines, batches, changeForm], () => {
  if (trackingChanges.value && !saving.value) isDirty.value = true
}, { deep: true })
onBeforeRouteLeave((to) => {
  if (!isDirty.value || saving.value) return true
  pendingRoute.value = to.fullPath
  unsavedDialogVisible.value = true
  return false
})
function leaveWithoutSaving() {
  const target = pendingRoute.value || '/sales-orders'
  isDirty.value = false
  unsavedDialogVisible.value = false
  void router.push(target)
}
onMounted(async () => {
  loading.value = true
  try {
    const [salesOptions, colors] = await Promise.all([
      fetchSalesOrderOptions(),
      fetchAllProductionDataRecords<ProductColor>('product-colors').catch(() => []),
    ])
    options.value = salesOptions
    productColors.value = colors
    productSearchChoices.value = options.value.products
    if (!Object.keys(form.seller_snapshot).length && options.value.seller_template) handleSellerSaved(options.value.seller_template as QuotationTemplate)
    if (!form.salesperson_id) form.salesperson_id = authStore.user?.employee?.id || options.value.employees[0]?.id || ''
    if (isEdit.value) await loadExisting()
    else {
      const quotationVersionId = typeof route.query.quotationVersionId === 'string' ? route.query.quotationVersionId : ''
      if (form.source_type === 'QUOTATION' && quotationVersionId) {
        const available = options.value.accepted_quotation_versions.some(item => item.id === quotationVersionId)
        if (!available) throw new Error('来源报价版本不存在、未被客户接受或已无剩余可转数量。')
        form.source_quotation_version_id = quotationVersionId
        await loadQuote(quotationVersionId)
      } else {
        addLine()
        addBatch()
      }
    }
    if (route.query.section === 'buyer-address') openBuyerDialog('address')
  } catch (error) { ElMessage.error(apiError(error)) } finally { loading.value = false; trackingChanges.value = true; isDirty.value = false }
})
</script>

<template>
  <section v-loading="loading" class="editor-page sales-order-editor-page">
    <header class="editor-heading">
      <div class="heading-title">
        <div class="title-line"><h1>{{ pageTitle }}</h1><el-tag class="draft-tag" type="warning" effect="light">{{ pageStatusLabel }}</el-tag></div>
        <p class="role-hint">责任角色：业务员{{ isConfirmedEdit ? '；保存即确认新版本' : '；可保存草稿或直接确认订单' }}</p>
      </div>
      <div class="heading-actions">
        <el-button text @click="router.push({ name: isEdit ? 'sales-order-detail' : 'sales-orders', params: isEdit ? { orderId } : {} })">取消</el-button>
        <el-button v-if="!isConfirmedEdit && canSaveOrder" :loading="saving" @click="save(false)">保存草稿</el-button>
        <el-button v-if="canSaveOrder && canConfirmOrder" type="primary" :loading="saving" @click="save(true)">{{ isConfirmedEdit ? '保存并确认变更' : '确认订单' }}</el-button>
      </div>
    </header>

    <nav v-if="!isConfirmedEdit" class="editor-tabs" aria-label="销售订单编辑页签">
      <button type="button" :class="{ active: activeDetailTab === 'base' }" @click="activeDetailTab = 'base'">基础信息</button>
      <button type="button" :class="{ active: activeDetailTab === 'products' }" @click="activeDetailTab = 'products'">订单产品</button>
      <button type="button" :class="{ active: activeDetailTab === 'batches' }" @click="activeDetailTab = 'batches'">交付批次</button>
    </nav>

    <div class="editor-layout" :class="{ 'change-layout': isConfirmedEdit }">
      <main class="editor-content">

    <el-card v-if="isConfirmedEdit" shadow="never" class="section-card change-card">
      <template #header><strong>变更控制</strong><span class="card-role-hint">销售员登记；已有生产订单时由 PMC 确认计划影响</span></template>
      <el-form :disabled="!canSaveOrder" label-position="top"><div class="grid grid-4"><el-form-item label="变更原因"><el-input v-model="changeForm.change_reason" placeholder="必填：说明为什么变更" /></el-form-item><el-form-item label="是否影响客户确认内容"><el-switch v-model="changeForm.customer_facing_change" active-text="是" inactive-text="否" /><div v-if="customerFactsChanged" class="muted">系统已检测到客户约定字段变化</div></el-form-item><el-form-item v-if="changeForm.customer_facing_change || customerFactsChanged" label="客户确认凭证"><el-select v-model="changeForm.change_evidence_file_id" clearable><el-option v-for="item in existingOrder?.evidence || []" :key="item.file_id" :label="item.file_name" :value="item.file_id" /></el-select></el-form-item><el-form-item v-if="existingOrder?.has_production_orders" label="PMC 影响确认"><el-checkbox v-model="changeForm.pmc_impact_confirmed">PMC 已确认数量、交期等计划影响</el-checkbox></el-form-item></div></el-form>
    </el-card>

    <el-card v-show="activeDetailTab === 'base' || isConfirmedEdit" shadow="never" class="section-card base-card">
      <div class="section-bar"><span>订单信息</span></div>
      <el-form :disabled="!canSaveOrder" label-position="top" class="compact-form">
        <div class="grid grid-4">
          <el-form-item label="销售订单号"><el-input :model-value="existingOrder?.order_number || '保存后自动生成'" disabled /></el-form-item>
          <el-form-item label="订单来源" required>
            <el-select v-model="sourceSelection" filterable :disabled="isEdit" placeholder="选择客户已接受的报价或直接下单">
              <el-option-group label="客户已接受的报价"><el-option v-for="item in options?.accepted_quotation_versions || []" :key="item.id" :value="`QUOTATION:${item.id}`" :label="`报价 ${item.quotation_number} V${item.version_number}`" /></el-option-group>
              <el-option-group label="其他来源"><el-option value="DIRECT" label="无报价直接订单" /><el-option value="REPEAT" label="返单" /></el-option-group>
            </el-select>
          </el-form-item>
          <el-form-item label="下单日期" required><el-date-picker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
          <el-form-item label="计划交期" required><el-date-picker v-model="primaryDeliveryDate" type="date" value-format="YYYY-MM-DD" /></el-form-item>
          <el-form-item label="业务员" required><el-select v-model="form.salesperson_id"><el-option v-for="item in options?.employees || []" :key="item.id" :value="item.id" :label="item.display_name" /></el-select></el-form-item>
          <el-form-item label="跟单员"><el-select v-model="form.merchandiser_id" clearable><el-option v-for="item in options?.employees || []" :key="item.id" :value="item.id" :label="item.display_name" /></el-select></el-form-item>
        </div>
      </el-form>
    </el-card>

    <el-card v-show="activeDetailTab === 'base' || isConfirmedEdit" shadow="never" class="section-card base-card">
      <div class="section-bar"><span>商业条款与客户确认</span></div>
      <el-form :disabled="!canSaveOrder" label-position="top" class="compact-form">
        <div class="grid grid-4">
          <el-form-item label="币种" required><el-select v-model="form.currency_code" filterable allow-create><el-option v-for="item in options?.currencies || []" :key="item.id" :label="item.code" :value="item.code" /></el-select></el-form-item>
          <el-form-item label="贸易条款"><el-input v-model="form.incoterm_code" placeholder="如 FOB" /></el-form-item>
          <el-form-item label="付款条款"><el-input v-model="form.payment_terms" placeholder="如 30% 订金 + 70% 发货前" /></el-form-item>
          <el-form-item label="客户确认方式" required><el-select v-model="form.confirmation_method"><el-option v-for="item in options?.confirmation_methods || []" :key="item.value" :label="item.label" :value="item.value" /></el-select></el-form-item>
          <el-form-item label="客户确认人" required><el-input v-model="form.customer_confirmer" placeholder="客户确认人" /></el-form-item>
          <el-form-item label="确认时间" required><el-date-picker v-model="form.customer_confirmed_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="确认时间" /></el-form-item>
          <el-form-item label="确认内容摘要" required><el-input v-model="form.confirmation_summary" placeholder="客户确认产品数量、价格及交期" /></el-form-item>
          <el-form-item v-if="form.source_type !== 'QUOTATION'" label="直接下单原因" required><el-input v-model="form.direct_order_reason" maxlength="1000" placeholder="说明无报价或返单的下单依据" /></el-form-item>
        </div>
        <el-alert v-if="form.source_type !== 'QUOTATION'" type="warning" show-icon :closable="false" title="直接订单确认前至少上传 1 份客户书面凭证；首次保存后请到详情页上传。" />
      </el-form>
    </el-card>

    <el-card v-show="activeDetailTab === 'base' || isConfirmedEdit" shadow="never" class="section-card transaction-card">
      <h2>交易双方</h2>
      <div class="transaction-grid">
        <div class="transaction-side seller-side">
          <SellerSubjectCard class="sales-seller-card" :snapshot="sellerCardSnapshot" :editable="!isConfirmedEdit" title="卖方（我方）" @edit="sellerDialogVisible = true" />
        </div>
        <section class="buyer-subject-card" :class="{ missing: !form.buyer_address_id }">
          <header><div><strong>买方（客户）</strong><el-tag v-if="!form.buyer_address_id" type="danger" size="small">确认前必须补齐</el-tag></div><el-button link type="primary" @click="openBuyerDialog('address')">编辑买方资料</el-button></header>
          <div class="buyer-edit-grid">
            <span>客户名称</span><el-select v-model="form.customer_account_id" filterable :disabled="form.source_type === 'QUOTATION' || isConfirmedEdit"><el-option v-for="item in options?.customers || []" :key="item.id" :value="item.id" :label="item.account_name" /></el-select>
            <span>买方主体</span><el-select v-model="form.transaction_entity_id" filterable clearable @change="handleBuyerEntitySelected"><el-option v-for="item in customerEntities" :key="item.id" :value="item.id" :label="item.legal_name" /></el-select>
            <span>买方地址</span><el-select v-model="form.buyer_address_id" clearable placeholder="多地址时请人工选择" @change="handleBuyerAddressIdSelected"><el-option v-for="item in buyerAddresses" :key="item.id" :value="item.id" :label="`${item.label || item.address_code} · ${item.city || item.country_code}`" /></el-select>
            <span>地址摘要</span><b>{{ buyerAddressDisplay || '当前主体没有可用地址' }}</b>
          </div>
          <p v-if="buyerAddresses.length > 1 && !form.buyer_address_id">当前主体有多个有效地址，请人工选择。</p>
          <p v-else-if="!buyerAddresses.length">草稿可以暂不填写；确认订单前必须补齐。</p>
        </section>
      </div>
    </el-card>

    <el-card v-show="activeDetailTab !== 'base' || isConfirmedEdit" shadow="never" class="section-card detail-card">
      <el-tabs v-model="activeDetailTab" class="order-tabs" :class="{ 'show-both-tabs': isConfirmedEdit }">
        <el-tab-pane label="订单产品" name="products">
          <div class="detail-toolbar">
            <strong>订单产品</strong>
            <el-button v-if="!hasLockedStructure" :icon="Plus" :disabled="quoteHasNoRemaining" @click="form.source_type === 'QUOTATION' ? addAvailableQuoteLines() : addLine()">{{ quoteHasNoRemaining ? '无剩余可转' : form.source_type === 'QUOTATION' ? '从本报价添加' : '添加产品' }}</el-button>
          </div>
          <el-alert v-if="quoteHasNoRemaining" class="remaining-alert" type="info" show-icon :closable="false" title="该报价已全部转为销售订单，没有剩余可转数量。" />
          <div class="product-summary">
            <div class="product-image"><el-icon><Picture /></el-icon><span>产品主图</span></div>
            <div><strong>{{ lines.length ? `${lines.length} 个订单产品` : '尚未选择产品' }}</strong><p>订单金额 {{ form.currency_code }} {{ orderTotal.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 }) }} · 支持多产品按不同交期分批</p></div>
          </div>
          <el-table :data="lines" class="product-table" empty-text="请从报价添加产品或手工添加产品">
            <el-table-column label="产品信息（类别 / 产品 / 规格 / 颜色）" min-width="500">
              <template #default="{ row }">
                <div class="product-information-box">
                  <div v-if="quoteLineById.get(row.source_quotation_line_id || '')" class="quote-product-source">
                    <b :title="quoteLineById.get(row.source_quotation_line_id)?.product_description">{{ quoteLineById.get(row.source_quotation_line_id)?.product_description }}</b>
                    <span :title="quoteLineById.get(row.source_quotation_line_id)?.specification || '无规格'">{{ quoteLineById.get(row.source_quotation_line_id)?.specification || '无规格' }}</span>
                  </div>
                  <div class="product-cascade-grid">
                    <el-select v-model="row.product_category_id" filterable clearable :disabled="hasLockedStructure" placeholder="先选类别" @change="selectProductCategory(row)">
                      <el-option v-for="item in productCategories" :key="item.id" :value="item.id" :label="item.name" />
                    </el-select>
                    <el-select v-model="row.product_name_input" filterable allow-create clearable :disabled="hasLockedStructure" placeholder="选择或填写产品" @change="selectProductName(row, String($event || ''))" @blur="matchProductInformation(row)">
                      <el-option v-for="item in productNameChoices(row)" :key="item.product_name" :value="item.product_name" :label="item.product_name" />
                    </el-select>
                    <el-select v-model="row.customer_specification_snapshot" filterable allow-create clearable :disabled="hasLockedStructure || !row.product_name_input" placeholder="选择或填写规格" @change="selectProductSpecification(row, String($event || ''))" @blur="matchProductInformation(row)">
                      <el-option v-for="item in specificationChoices(row)" :key="item.id" :value="item.specification" :label="`${item.specification}${item.product_code ? ` · ${item.product_code}` : ''}`" />
                    </el-select>
                    <el-select v-model="row.customer_color_snapshot" filterable allow-create clearable :disabled="hasLockedStructure" placeholder="选择或填写颜色">
                      <el-option v-for="color in systemColorChoices" :key="color" :value="color" :label="color" />
                    </el-select>
                  </div>
                  <small v-if="row.product_name_input && row.customer_specification_snapshot" class="product-mapping-hint" :class="{ 'is-warning': !row.product_id }">{{ row.product_id ? '已关联产品主档' : '未匹配产品主档，按客户输入保存' }}</small>
                  <small v-if="quoteProductMappingHint(row)" class="product-mapping-hint" :class="{ 'is-warning': !row.product_id }">{{ quoteProductMappingHint(row) }}</small>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="单位" width="72"><template #default="{ row }">{{ unitDisplay(row) }}</template></el-table-column>
            <el-table-column label="报价单价" width="90"><template #default="{ row }">{{ quoteLineById.get(row.source_quotation_line_id || '')?.quoted_unit_price || '—' }}</template></el-table-column>
            <el-table-column label="订单数量" width="118"><template #default="{ row }"><el-input-number v-model="row.quantity" :min="0.0001" :precision="4" :controls="false" /></template></el-table-column>
            <el-table-column label="订单单价" width="105"><template #default="{ row }"><el-input-number v-model="row.unit_price" :min="0" :precision="4" :controls="false" /></template></el-table-column>
            <el-table-column label="行金额" width="92"><template #default="{ row }">{{ lineTotal(row).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }}</template></el-table-column>
            <el-table-column label="本币金额" width="102"><template #default="{ row }">{{ localLineTotal(row).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }}</template></el-table-column>
            <el-table-column label="价差" width="76"><template #default="{ row }">{{ row.source_quotation_line_id ? (Number(row.unit_price || 0) - Number(quoteLineById.get(row.source_quotation_line_id)?.quoted_unit_price || 0)).toFixed(2) : '—' }}</template></el-table-column>
            <el-table-column label="可转数量" width="92"><template #default="{ row }">{{ quoteRemainingText(row) }}</template></el-table-column>
            <el-table-column label="价格备注" min-width="135"><template #default="{ row }"><el-input v-model="row.lower_price_reason" placeholder="选填" /></template></el-table-column>
            <el-table-column v-if="!hasLockedStructure" label="操作" width="90"><template #default="{ $index }"><el-button link type="danger" :icon="Delete" @click="removeLine($index)">删除</el-button></template></el-table-column>
          </el-table>
          <section class="totals-panel">
            <h3>合计与汇率</h3>
            <div class="totals-grid">
              <label><span>汇率（{{ form.currency_code }}→CNY）</span><el-input-number v-model="form.exchange_rate" :min="0.000001" :precision="6" :controls="false" /></label>
              <label><span>订单总数量</span><b>{{ orderQuantity.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }}</b></label>
              <label><span>总金额（{{ form.currency_code }}）</span><b>{{ orderTotal.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 }) }}</b></label>
              <label><span>本币金额（CNY）</span><b>{{ (orderTotal * Number(form.exchange_rate || 0)).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 }) }}</b></label>
            </div>
          </section>
          <section v-if="selectedRequirementLine" class="requirements-panel">
            <h3>产品要求</h3>
            <label class="requirement-selector"><span>选中产品</span><el-select v-model="requirementLineSelection"><el-option v-for="line in lines" :key="line.client_key" :label="productDisplayName(line)" :value="line.client_key" /></el-select></label>
            <div class="requirements-grid">
              <label><span>品质要求</span><el-input v-model="selectedRequirementLine.quality_requirements" type="textarea" :rows="3" /></label>
              <label><span>包装要求</span><el-input v-model="selectedRequirementLine.packaging_requirements" type="textarea" :rows="3" /></label>
              <label><span>唛头要求</span><el-input v-model="selectedRequirementLine.shipping_mark_requirements" type="textarea" :rows="3" /></label>
            </div>
            <label><span>价格备注（选填）</span><el-input v-model="selectedRequirementLine.lower_price_reason" type="textarea" :rows="2" /></label>
          </section>
        </el-tab-pane>
        <el-tab-pane label="交付批次" name="batches">
          <div class="detail-toolbar"><strong>交付批次安排</strong></div>
          <section class="batch-matrix">
            <div class="matrix-row matrix-header" :style="{ gridTemplateColumns: `300px repeat(${Math.max(batches.length, 1)}, minmax(0, 1fr))` }">
              <span>产品信息</span>
              <label v-for="(batch, batchIndex) in batches" :key="batch.key"><span>第{{ batchIndex + 1 }}批</span><el-date-picker v-model="batch.planned_delivery_date" type="date" value-format="YYYY-MM-DD" /></label>
            </div>
            <div class="matrix-row" :style="{ gridTemplateColumns: `300px repeat(${Math.max(batches.length, 1)}, minmax(0, 1fr))` }">
              <span>批次备注</span><el-input v-for="batch in batches" :key="batch.key" v-model="batch.notes" maxlength="500" placeholder="填写本批交付要求" />
            </div>
            <div v-for="line in lines" :key="line.client_key" class="matrix-row product-allocation-row" :class="`state-${lineAllocationState(line)}`" :style="{ gridTemplateColumns: `300px repeat(${Math.max(batches.length, 1)}, minmax(0, 1fr))` }">
              <div><b>{{ productDisplayName(line) }}</b><small>订单数量 {{ Number(line.quantity || 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }}件</small></div>
              <el-input-number v-for="batch in batches" :key="batch.key" :model-value="batchQuantity(batch, line.client_key)" :min="0" :precision="4" :controls="false" :disabled="hasLockedStructure && !batch.lines.some((item) => item.sales_order_line_client_key === line.client_key)" @update:model-value="setBatchQuantity(batch, line.client_key, $event)" />
            </div>
            <div class="matrix-row matrix-total" :style="{ gridTemplateColumns: `300px repeat(${Math.max(batches.length, 1)}, minmax(0, 1fr))` }">
              <span>本批合计</span><div v-for="batch in batches" :key="batch.key"><b>{{ batchTotal(batch).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }}件</b><span> · {{ batchStateLabel(batch) }}</span></div>
            </div>
            <div v-if="!hasLockedStructure" class="matrix-row matrix-actions" :style="{ gridTemplateColumns: `300px repeat(${Math.max(batches.length, 1)}, minmax(0, 1fr))` }">
              <span>操作</span><el-button v-for="(batch, batchIndex) in batches" :key="batch.key" :disabled="batches.length <= 1" @click="openDeleteBatch(batchIndex)">删除本批</el-button>
            </div>
            <footer v-if="!hasLockedStructure"><el-button :icon="Plus" @click="addBatch">添加批次</el-button></footer>
          </section>
          <section class="allocation-validation">
            <h3>整单校验</h3>
            <div class="validation-row validation-head"><span>产品名称</span><span>订单总量</span><span>已分配总量</span><span>未分配</span></div>
            <div v-for="line in lines" :key="line.client_key" class="validation-row" :class="`state-${lineAllocationState(line)}`"><span>{{ productDisplayName(line) }}</span><span>{{ Number(line.quantity || 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }}</span><span>{{ allocatedQuantity(line.client_key).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }}</span><span>{{ remainingQuantity(line).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }}</span></div>
          </section>
        </el-tab-pane>
      </el-tabs>
    </el-card>
      </main>
      <aside v-if="!isConfirmedEdit" class="editor-summary">
        <h2>订单概览</h2>
        <dl>
          <dt>来源报价</dt><dd>{{ sourceQuoteLabel }}</dd>
          <dt>客户</dt><dd>{{ (options?.customers || []).find((item) => item.id === form.customer_account_id)?.account_name || '尚未选择' }}</dd>
          <dt>买方</dt><dd>{{ selectedBuyerEntity?.legal_name || '尚未选择' }}</dd>
          <dt>买方地址</dt><dd>{{ buyerAddressDisplay || '确认前必须选择' }}</dd>
        </dl>
        <div class="summary-divider" />
        <dl>
          <dt>订单产品</dt><dd>{{ lines.length }}种</dd>
          <dt>交付批次</dt><dd>{{ batches.length }}批</dd>
          <dt>总数量</dt><dd>{{ lines.reduce((sum, line) => sum + Number(line.quantity || 0), 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 }) }}</dd>
          <dt>总金额</dt><dd class="summary-amount">{{ form.currency_code }} {{ orderTotal.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 }) }}</dd>
        </dl>
        <div class="summary-divider" />
        <dl>
          <dt>期望交期</dt><dd>{{ primaryDeliveryDate || '—' }}</dd>
          <dt>贸易条款</dt><dd>{{ form.incoterm_code || '—' }}</dd>
          <dt>付款条款</dt><dd>{{ form.payment_terms || '—' }}</dd>
          <dt>客户确认人</dt><dd>{{ form.customer_confirmer || '—' }}</dd>
          <dt>确认时间</dt><dd>{{ form.customer_confirmed_at || '—' }}</dd>
          <dt>确认方式</dt><dd>{{ form.confirmation_method || '—' }}</dd>
          <dt>确认内容</dt><dd>{{ form.confirmation_summary || '—' }}</dd>
        </dl>
        <p class="summary-hint">产品明细与批次分配请切换上方选项卡。</p>
      </aside>
    </div>
    <SellerProfileDialog v-model="sellerDialogVisible" :template-id="sellerTemplateId" context-name="销售订单" @saved="handleSellerSaved" />
    <BuyerMasterDataDialog
      v-model="buyerDialogVisible"
      :customer-id="form.customer_account_id"
      :entity-id="form.transaction_entity_id || ''"
      :selected-address-id="form.buyer_address_id"
      :initial-tab="buyerDialogTab"
      context-name="销售订单"
      :close-on-address-save="true"
      @address-selected="handleBuyerAddressSelected"
      @address-saved="handleBuyerAddressSaved"
      @entity-updated="handleBuyerEntityUpdated"
    />
    <AppWindowDialog v-model="deleteBatchDialogVisible" class="customer-management-table-dialog" title="删除草稿交付批次" :width="680" :height="420" :close-on-click-modal="false">
      <el-alert type="warning" :closable="false" show-icon title="删除后系统不会自动把数量分配到其他批次，请回到批次卡片手工调整。" />
      <p class="delete-dialog-copy">将删除交付批次 {{ (deleteBatchIndex ?? 0) + 1 }}，以下数量会重新变为未分配：</p>
      <el-table :data="pendingDeleteReleasedLines" border size="small"><el-table-column prop="product" label="产品" min-width="260" /><el-table-column prop="quantity" label="释放数量" width="130" /><el-table-column prop="unit" label="单位" width="90" /></el-table>
      <template #footer><el-button @click="deleteBatchDialogVisible = false">取消</el-button><el-button type="danger" @click="confirmDeleteBatch">确认删除批次</el-button></template>
    </AppWindowDialog>
    <AppWindowDialog v-model="conflictVisible" title="订单已被其他人更新" :width="680" :height="280" :close-on-click-modal="false">
      <p class="dialog-warning">系统没有覆盖对方的修改，当前表单输入仍保留。请另行查看最新记录后再决定是否重新提交。</p>
      <template #footer><el-button @click="conflictVisible = false">保留当前编辑</el-button><el-button type="primary" @click="reloadAfterConflict">查看最新记录</el-button></template>
    </AppWindowDialog>
    <AppWindowDialog v-model="unsavedDialogVisible" title="尚有内容未保存" :width="620" :height="280" :close-on-click-modal="false" :show-close="false">
      <p class="dialog-warning">离开后本次修改将丢失。你可以返回继续编辑，或明确放弃本次修改。</p>
      <template #footer><el-button @click="unsavedDialogVisible = false">返回编辑</el-button><el-button type="danger" @click="leaveWithoutSaving">放弃修改并离开</el-button></template>
    </AppWindowDialog>
  </section>
</template>

<style lang="scss" scoped>
.editor-page{min-height:100%;padding:20px 32px 32px;background:var(--erp-page-background);color:#18181b}.editor-heading{display:flex;height:64px;align-items:center;justify-content:space-between;margin-bottom:0;padding:0;background:#fff}.heading-title{min-width:0}.title-line{display:flex;align-items:center;gap:8px}.editor-heading h1{margin:0;color:#18181b;font-size:28px;line-height:34px}.editor-heading p{margin:2px 0 0}.role-hint,.card-role-hint{color:#71717a;font-size:12px}.heading-actions{display:flex;align-items:center;gap:8px}.heading-actions .el-button{min-width:72px;margin-left:0}.draft-tag{min-width:72px;border:0}.section-card{margin-bottom:16px;border:1px solid #e4e4e7;border-radius:8px}.section-card :deep(.el-card__body){padding:16px}.base-card :deep(.el-card__body){padding:10px 16px 12px}.change-card{border-color:#bfdbfe}.change-card :deep(.el-card__header){padding:12px 16px}.card-role-hint{margin-left:12px;font-weight:400}.section-bar{position:relative;height:28px;margin-bottom:12px;border-bottom:1px solid #18181b}.section-bar span{position:absolute;top:0;left:0;width:132px;height:26px;padding-left:14px;background:#18181b;color:#fff;font-size:14px;font-weight:500;line-height:26px}.grid{display:grid;gap:0 12px}.grid-4{grid-template-columns:repeat(4,minmax(0,1fr))}.grid-2{grid-template-columns:repeat(2,minmax(0,1fr))}.compact-form :deep(.el-form-item){margin-bottom:12px}.compact-form :deep(.el-form-item__label){height:20px;padding:0 0 6px;color:#52525b;font-size:12px;line-height:14px}.compact-form :deep(.el-input__wrapper),.compact-form :deep(.el-select__wrapper),.compact-form :deep(.el-date-editor){min-height:32px;border-radius:8px}.confirmation-fields{display:grid;width:100%;grid-template-columns:minmax(0,1fr) minmax(0,1.4fr);gap:8px}.summary-field{margin-bottom:0!important}.summary-editor{width:100%;overflow:hidden;border:1px solid #d4d4d8;border-radius:8px}.summary-toolbar{height:36px;padding:0 12px;background:#f7f7f8;color:#52525b;font-size:12px;line-height:36px}.summary-editor :deep(.el-textarea__inner){min-height:84px!important;border:0;border-radius:0;box-shadow:none;resize:none}.detail-card :deep(.el-card__body){padding:0 16px 12px}.order-tabs :deep(.el-tabs__header){margin:0 0 10px}.order-tabs :deep(.el-tabs__item){height:52px;font-size:14px}.detail-toolbar,.batch-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.detail-toolbar{height:36px;margin-bottom:4px}.detail-toolbar strong{font-size:13px}.product-summary{display:flex;min-height:64px;align-items:center;margin-bottom:10px;border:1px solid #e4e4e7;background:#f7f7f8}.product-image{display:flex;width:140px;min-height:64px;align-items:center;justify-content:center;gap:8px;border-right:1px solid #e4e4e7;color:#52525b;font-size:12px}.product-summary>div:last-child{padding:8px 14px}.product-summary strong{font-size:14px}.product-summary p{margin:4px 0 0;color:#71717a;font-size:12px}.product-table{width:100%;font-size:12px}.product-table :deep(.el-table__header th){height:30px;padding:0;background:#f7f7f8;color:#27272a}.product-table :deep(.el-table__cell){padding:4px 0}.product-table :deep(.el-input__wrapper),.product-table :deep(.el-select__wrapper){min-height:28px;padding:1px 8px;border-radius:6px}.source-difference{display:flex;flex-direction:column;gap:3px}.source-difference small{color:#71717a}.stacked-fields{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:4px}.batch-block{padding:14px;border:1px solid #e4e4e7;border-radius:8px;margin-bottom:12px;background:#fafafa}.batch-head .el-input{max-width:420px}.allocation-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:14px}.allocation-grid label{display:flex;gap:8px;align-items:center;color:#4b5563}.allocation-grid span{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.allocation-check{display:flex;gap:20px;flex-wrap:wrap;color:#52525b;font-size:13px}.allocation-check .invalid{color:#f56c6c}.muted{margin-top:4px;color:#8b95a5;font-size:12px}.el-select,.el-date-editor,.el-input-number{width:100%}
.allocation-grid .el-input-number{width:220px}.remaining-alert{margin-bottom:10px}
.buyer-subject-card{margin:4px 0 12px;padding:14px 16px;border:1px solid #bfdbfe;border-radius:8px;background:#f8fbff}.buyer-subject-card.missing{border-color:#fecaca;background:#fffafa}.buyer-subject-card header{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.buyer-subject-card header>div{display:flex;align-items:center;gap:8px}.buyer-subject-grid{display:grid;grid-template-columns:1fr 1fr 1.25fr 1.75fr;gap:12px}.buyer-subject-grid>div{display:grid;min-width:0;gap:5px}.buyer-subject-grid small{color:#71717a;font-size:11px}.buyer-subject-grid b{overflow:hidden;color:#27272a;font-size:12px;font-weight:500;line-height:20px;text-overflow:ellipsis;white-space:nowrap}.buyer-subject-card p{margin:10px 0 0;color:#b45309;font-size:12px}.sales-seller-card{margin:4px 0 12px;min-height:164px}
.batch-grid{display:grid;grid-template-columns:repeat(2,minmax(0,550px));gap:20px;align-items:start}.batch-card{display:grid;width:100%;padding:16px;border:1px solid #d4d4d8;border-radius:8px;background:#fff;gap:12px}.batch-card.state-under{border-color:#f59e0b;background:#fffdf5}.batch-card.state-over{border-color:#ef4444;background:#fff8f8}.batch-card.state-complete{border-color:#22c55e;background:#f8fff9}.batch-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.batch-card-head>div{display:grid;gap:3px}.batch-card-head strong{font-size:14px}.batch-card-head small{max-width:360px;overflow:hidden;color:#8a8a93;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.batch-card :deep(.el-form-item){margin-bottom:0}.batch-product-head,.batch-product-row{display:grid;grid-template-columns:minmax(0,1.65fr) .7fr 1fr .8fr .75fr;align-items:center;gap:7px}.batch-product-head{padding:7px 8px;border-radius:5px;background:#f4f4f5;color:#71717a;font-size:10px}.batch-product-row{min-height:42px;padding:5px 8px;border-bottom:1px solid #ececf0;color:#3f3f46;font-size:11px}.batch-product-row b{overflow:hidden;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.batch-product-row.state-under span:last-child{color:#b45309;font-weight:600}.batch-product-row.state-over span:last-child{color:#dc2626;font-weight:600}.batch-product-row.state-complete span:last-child{color:#15803d;font-weight:600}.batch-product-row :deep(.el-input__wrapper){min-height:30px;padding:0 7px}.batch-card footer{display:flex;align-items:center;justify-content:space-between;padding-top:4px;border-top:1px solid #e4e4e7}.batch-card footer>div{display:flex;align-items:baseline;gap:8px}.batch-card footer small{color:#71717a;font-size:11px}.batch-card footer strong{font-size:15px}.delete-dialog-copy{margin:16px 0 10px;color:#52525b;font-size:13px}.allocation-check{margin-top:12px}.allocation-check .invalid{color:#dc2626}
/* 销售订单 2026-09-11 已选原型：仅覆盖本页面旧视觉。 */
.editor-page{height:calc(100vh - 92px);min-width:1260px;overflow:auto;padding:28px;background:var(--erp-page-background);color:#1f1d18}.editor-heading{height:64px;background:transparent}.editor-heading h1{font-family:'Noto Serif SC','Songti SC',serif;font-size:34px;font-weight:600;line-height:44px}.editor-heading p{display:none}.title-line{gap:28px}.draft-tag{display:inline-flex;min-width:56px;height:24px;align-items:center;justify-content:center;border:0;border-radius:999px!important;color:#faf9f5!important;background:#65635e!important}.heading-actions{gap:12px}.heading-actions .el-button{height:36px;min-width:90px;border-radius:5px}.heading-actions .el-button--primary{width:140px;border-color:#c84e28;background:#c84e28}.editor-tabs{display:flex;height:66px;align-items:center;gap:18px}.editor-tabs button{height:44px;padding:0 10px;border:0;border-bottom:1px solid transparent;color:#6f6a61;background:transparent;font-size:16px;cursor:pointer}.editor-tabs button.active{border-bottom-color:#c84e28;color:#c84e28}.editor-layout{display:grid;grid-template-columns:minmax(0,1fr) 410px;align-items:start;gap:18px}.editor-layout.change-layout{grid-template-columns:1fr}.editor-content{min-width:0}.section-card{margin-bottom:12px;border:1px solid #ddd6c9;border-radius:5px;background:#fcfbf7}.section-card :deep(.el-card__body){padding:14px}.section-bar{height:42px;margin-bottom:12px;border:0;background:#f0eadf}.section-bar span{position:static;display:flex;width:auto;height:42px;align-items:center;padding:0 10px;color:#1f1d18;background:transparent;font-size:17px;font-weight:600}.compact-form :deep(.el-form-item__label){height:auto;padding:0 0 6px;color:#6f6a61;font-size:13px}.compact-form :deep(.el-input__wrapper),.compact-form :deep(.el-select__wrapper),.compact-form :deep(.el-date-editor){min-height:38px;border-radius:5px;box-shadow:0 0 0 1px #e0dbd2 inset}.buyer-subject-card,.sales-seller-card{border-color:#ddd6c9;border-radius:5px;background:#fcfbf7}.detail-card :deep(.el-card__body){padding:14px}.order-tabs:not(.show-both-tabs) :deep(.el-tabs__header){display:none}.order-tabs.show-both-tabs :deep(.el-tabs__active-bar){background:#c84e28}.order-tabs.show-both-tabs :deep(.el-tabs__item.is-active){color:#c84e28}.detail-toolbar{height:40px;margin-bottom:8px}.detail-toolbar .el-button{height:32px;border-radius:4px;color:#fff;border-color:#c84e28;background:#c84e28}.product-summary{display:none}.product-table :deep(.el-table__header th){height:44px;background:#f0eadf;color:#6f6a61;font-weight:500}.product-table :deep(.el-table__cell){padding:8px 0}.product-table :deep(.el-input__wrapper),.product-table :deep(.el-select__wrapper){min-height:34px;border-radius:4px}.batch-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.batch-card{border-color:#ddd6c9;border-radius:5px}.batch-card.state-under{border-color:#d89a35;background:#fffaf0}.batch-card.state-over{border-color:#b8442c;background:#fff5f2}.batch-card.state-complete{border-color:#4e8750;background:#f7fcf7}.editor-summary{position:sticky;top:0;padding:14px;border:1px solid #ddd6c9;border-radius:5px;background:#fcfbf7}.editor-summary h2{height:42px;margin:0 0 14px;padding:0 10px;background:#f0eadf;font-size:18px;line-height:42px}.editor-summary dl{display:grid;grid-template-columns:130px minmax(0,1fr);margin:0;gap:10px 8px;font-size:14px}.editor-summary dt{color:#6f6a61}.editor-summary dd{min-width:0;margin:0;overflow-wrap:anywhere}.editor-summary .summary-amount{grid-column:1/-1;padding:4px 0 2px 138px;color:#c84e28;font-size:24px}.summary-divider{height:1px;margin:14px 0;background:#ddd6c9}.summary-hint{margin:16px 0 0;padding:12px;border-radius:5px;color:#6f6a61;background:#f0eadf;font-size:13px}.dialog-warning{margin:0;padding:14px;border-radius:5px;color:#9f351f;background:#f8e7e1;line-height:22px}.editor-page :deep(.el-dialog){border-radius:6px;background:#fcfbf7}.editor-page :deep(.el-dialog__header){margin:0;padding:22px 26px 16px;border-bottom:1px solid #ddd6c9}.editor-page :deep(.el-dialog__title){font-family:'Noto Serif SC','Songti SC',serif;font-size:22px}.editor-page :deep(.el-dialog__body){padding:20px 26px}.editor-page :deep(.el-dialog__footer){padding:14px 26px 22px}.editor-page :deep(.el-dialog .el-button--primary){border-color:#c84e28;background:#c84e28}
.transaction-card :deep(.el-card__body){padding:14px}.transaction-card h2,.totals-panel h3,.requirements-panel h3,.allocation-validation h3{margin:0 0 12px;color:#2c2923;font-family:'Noto Serif SC','Songti SC',serif;font-size:19px;font-weight:600}.transaction-grid{display:grid;grid-template-columns:1fr 1.05fr;gap:20px}.transaction-side,.buyer-subject-card{min-width:0}.sales-seller-card{height:100%;min-height:220px;margin:0}.buyer-subject-card{height:100%;margin:0;padding:14px}.buyer-edit-grid{display:grid;grid-template-columns:92px minmax(0,1fr);align-items:center;gap:8px 12px}.buyer-edit-grid>span{color:#6f6a61;font-size:13px}.buyer-edit-grid>b{font-size:13px;font-weight:500}.buyer-edit-grid :deep(.el-select__wrapper){min-height:34px;border-radius:4px}.product-table{border-top:0}.product-table :deep(.el-table__inner-wrapper::before){background:#ddd6c9}.product-table :deep(.el-table__row td){height:88px;border-bottom-color:#ddd6c9}.product-table :deep(.el-select__wrapper){box-shadow:none}.totals-panel,.requirements-panel,.allocation-validation{margin-top:12px;padding:16px;border:1px solid #ddd6c9;border-radius:5px;background:#fcfbf7}.totals-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px}.totals-grid label,.requirements-panel label{display:grid;gap:7px}.totals-grid label>span,.requirements-panel label>span{color:#6f6a61;font-size:13px}.totals-grid b{display:flex;min-height:38px;align-items:center;padding:0 12px;border-radius:4px;background:#e9e5db;font-size:14px;font-weight:500}.requirement-selector{margin-bottom:12px}.requirements-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-bottom:12px}.requirements-panel :deep(.el-textarea__inner){border-radius:4px;box-shadow:0 0 0 1px #ddd6c9 inset;resize:none}.batch-matrix{overflow:hidden;border:1px solid #ddd6c9;border-radius:5px}.matrix-row{display:grid;align-items:center;border-bottom:1px solid #ddd6c9}.matrix-row>*{min-width:0;padding:12px 14px}.matrix-header{background:#f0eadf}.matrix-header>label{display:grid;gap:6px;color:#6f6a61;font-size:12px}.matrix-header>span,.matrix-row>span{color:#6f6a61;font-size:13px}.matrix-row :deep(.el-input__wrapper){min-height:34px;border-radius:4px}.product-allocation-row>div{display:grid;gap:4px}.product-allocation-row b{font-size:14px}.product-allocation-row small{color:#6f6a61;font-size:12px}.product-allocation-row.state-over{background:#fff5f2}.product-allocation-row.state-under{background:#fffaf0}.matrix-total b{font-size:14px}.matrix-total div>span{color:#6f6a61;font-size:12px}.matrix-actions .el-button{width:calc(100% - 28px);margin:0 14px}.batch-matrix footer{padding:10px 14px}.batch-matrix footer .el-button{margin:0}.allocation-validation{padding:14px}.validation-row{display:grid;grid-template-columns:repeat(4,1fr);min-height:46px;align-items:center;border-bottom:1px solid #ddd6c9}.validation-row span{padding:0 8px;font-size:13px}.validation-head{min-height:42px;color:#6f6a61;background:#f0eadf}.validation-row.state-over span:last-child{color:#b8442c;font-weight:600}.validation-row.state-under span:last-child{color:#ad6b05;font-weight:600}.validation-row.state-complete span:last-child{color:#417b43;font-weight:600}
.compact-form .grid-4 :deep(.el-form-item),.compact-form .grid-4 :deep(.el-form-item__content),.compact-form .grid-4 :deep(.el-input),.compact-form .grid-4 :deep(.el-select),.compact-form .grid-4 :deep(.el-date-editor){width:100%;min-width:0}
.product-table :deep(.el-table__row td){height:136px}.product-information-box{display:grid;gap:5px;padding:7px;border:1px solid #ddd6c9;border-radius:5px;background:#fcfbf7}.quote-product-source{display:flex;min-width:0;align-items:center;gap:8px}.quote-product-source b{max-width:130px;overflow:hidden;color:#2c2923;font-size:13px;text-overflow:ellipsis;white-space:nowrap}.quote-product-source span{min-width:0;overflow:hidden;color:#6f6a61;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.product-cascade-grid{display:grid;grid-template-columns:1fr 1.2fr 1.2fr 1fr;gap:5px}.product-information-box :deep(.el-input__wrapper),.product-information-box :deep(.el-select__wrapper){min-height:30px;box-shadow:0 0 0 1px #d8d0c4 inset}.product-mapping-hint{color:#417b43;font-size:11px;line-height:16px}.product-mapping-hint.is-warning{color:#ad6b05}
</style>

<style lang="scss" scoped>
.editor-page { padding: 14px; }
</style>
