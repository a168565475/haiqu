<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch, onBeforeUnmount } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ArrowRight, Lock, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import InquiryProductDialog from '@/components/inquiries/InquiryProductDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import ProductImage from '@/components/products/ProductImage.vue'
import type { InquiryItem, InquiryProductCandidate, InquiryProductSelectionOptions } from '@/types/inquiry'
import InquiryWangEditor from '@/components/InquiryWangEditor.vue'
import { multiplyAmount4, sumAmounts4 } from '@/utils/salesCny'
import {
  productionTaskBusinessFileUrl,
  fetchProductionTask,
  fetchProductionTaskOptions,
  updateProductionTask,
} from '@/api/productionTasks'
import type {
  ProductionTask,
  ProductionTaskOptions,
  ProductionTaskPatchInput,
  ProductionTaskProduct,
  ProductionTaskProductInput,
} from '@/types/productionTask'

interface EditableProduct {
  id: string
  productName: string
  productCode: string
  specification: string
  colorLabel: string
  quantity: string
  originalQuantity: string
  unitName: string
  sourceLocked: boolean
  unitPriceCny: string
  lineAmountCny: string
  payload: ProductionTaskProductInput
  originalPayload: string
  maxQuantity?: number | null
  deletionReason: string
  isCny: boolean
}

const route = useRoute()
const router = useRouter()
const taskId = computed(() => typeof route.params.taskId === 'string' ? route.params.taskId : '')
const task = ref<ProductionTask | null>(null)
const options = ref<ProductionTaskOptions | null>(null)
const etag = ref('')
const loading = ref(true)
const saving = ref(false)
const loadError = ref('')
const allowLeave = ref(false)
const originalRequirementsHtml = ref('')
const bomSyncMode = ref<'SYNC' | 'KEEP'>('SYNC')
const products = ref<EditableProduct[]>([])
const expandedProductIds = ref<string[]>([])
function syncProductExpansion(id: string, event: Event) {
  const open = (event.currentTarget as HTMLDetailsElement).open
  expandedProductIds.value = open
    ? [...new Set([...expandedProductIds.value, id])]
    : expandedProductIds.value.filter(value => value !== id)
}
const form = reactive({
  salesperson_id: '', order_date: '', includes_tax: false, tax_rate: null as 3 | 5 | 7 | null,
  order_tolerance_percent: '0', is_repeat_order: false, preproduction_sample_required: false,
  delivery_method: 'SINGLE' as 'SINGLE' | 'SPLIT', planner_id: null as string | null,
  planned_start_date: '', planned_end_date: '', production_priority: 'NORMAL' as 'URGENT' | 'HIGH' | 'NORMAL' | 'LOW', production_batch_number: '',
  delivery_date: '',
  follower_ids: [] as string[],
  special_requirements_html: '',
})

const isTerminal = computed(() => ['COMPLETED', 'CANCELLED'].includes(task.value?.status || ''))
const followerOptions = computed(() => options.value?.employees || [])
const employeeName = (id: string) => options.value?.employees.find((item) => item.id === id)?.display_name || id
const followerSummary = (ids: string[]) => ids.map(employeeName).join('、') || '未设置'
const sourceLocked = computed(() => Boolean(task.value?.sales_order_id || task.value?.products.some(row => row.source_delivery_batch_line_id)))
const returnsToDraft = computed(() => ['PENDING_VALIDATION', 'READY'].includes(task.value?.status || ''))
const originalForm = ref<Record<string, unknown>>({})
const fieldLabels: Record<string, string> = { salesperson_id: '业务员', order_date: '下单日期', includes_tax: '含税', tax_rate: '税率', order_tolerance_percent: '订单误差', is_repeat_order: '返单', preproduction_sample_required: '产前样', delivery_method: '交货方式', planner_id: '计划员', planned_start_date: '计划开工', planned_end_date: '计划完工', production_priority: '优先级', production_batch_number: '生产批号' }
const productFiles = ref<Record<string, File[]>>({})
const detailFiles = ref<Record<string, File | null>>({})
const productPreviews = ref<Record<string, string>>({})
onBeforeUnmount(() => Object.values(productPreviews.value).forEach(url => URL.revokeObjectURL(url)))
const editorVisible = ref(false)
const productEditor = ref<InstanceType<typeof InquiryProductDialog> | null>(null)
const editingId = ref('')
const editorItem = ref<InquiryItem>(emptyItem())
const editorDetails = ref<ProductionTaskProductInput['details']>([])
const editorDetailFiles = ref<Record<string, File | null>>({})
const editingProduct = computed(() => products.value.find(row => row.id === editingId.value))
function emptyItem(): InquiryItem { return { product_id: null, product_category_id: null, product_unit_id: null, product_color_id: null, product_description: '', specification: '', color: '', material: '', quantity: '1', unit_code: '', target_unit_price: '', target_currency_code: 'CNY', expected_date: null, product_match_status: 'PENDING', notes: '' } }
function productAmountCny(row: EditableProduct) {
  if (row.quantity === row.originalQuantity && row.unitPriceCny === task.value?.products.find(item => item.id === row.id)?.local_unit_price) return row.lineAmountCny
  // 金额预览只使用已冻结的人民币单价，不重新获取汇率或改写原币快照。
  return multiplyAmount4(row.unitPriceCny, row.quantity) ?? '—'
}
const totalAmountCny = computed(() => sumAmounts4(products.value.map(row => { const amount = productAmountCny(row); return /^\d+\.\d{4}$/.test(amount) ? amount : null })) || '—')
const quantitySummary = computed(() => {
  const totals = new Map<string, number>()
  products.value.forEach(row => totals.set(row.unitName, (totals.get(row.unitName) || 0) + Number(row.quantity || 0)))
  return [...totals].map(([unit, quantity]) => `${quantity.toLocaleString('zh-CN')} ${unit}`).join(' / ')
})
function hasDetailFiles(row: EditableProduct) { return row.payload.details.some(detail => Boolean(detailFiles.value[detail.client_key])) }
function changedProduct(row: EditableProduct) { return hasDetailFiles(row) || row.quantity !== row.originalQuantity || JSON.stringify(row.payload) !== row.originalPayload || Boolean(productFiles.value[row.id]?.length) || row.unitPriceCny !== task.value?.products.find(item => item.id === row.id)?.local_unit_price }
async function loadProductionCandidates(categoryId: string): Promise<InquiryProductSelectionOptions> {
  const category = options.value?.categories?.find(row => row.id === categoryId)
  if (!category) throw new Error('产品类别不存在或不可用。')
  const grouped = new Map<string, Map<string, InquiryProductCandidate[]>>()
  for (const product of options.value?.products || []) {
    if (product.category_id !== categoryId) continue
    const unit = options.value?.units.find(row => row.id === product.default_unit_id)
    const candidate: InquiryProductCandidate = { ...product, unit_id: product.default_unit_id, unit_code: unit?.unit_code || '', unit_name: unit?.unit_name || '', category_id: category.id, category_name: category.category_name }
    if (!grouped.has(product.product_name)) grouped.set(product.product_name, new Map())
    const specs = grouped.get(product.product_name)!
    if (!specs.has(product.specification)) specs.set(product.specification, [])
    specs.get(product.specification)!.push(candidate)
  }
  return { category, groups: [...grouped].map(([product_name, specs]) => ({ product_name, specifications: [...specs].map(([specification, products]) => ({ specification, products })) })) }
}
function editProduct(row?: EditableProduct) {
  if (isTerminal.value || sourceLocked.value) return
  if (row && !row.isCny) { ElMessage.warning('历史外币产品保留冻结价格，仅支持在产品档案调整数量和要求。'); return }
  editingId.value = row?.id || ''
  editorDetails.value = row ? JSON.parse(JSON.stringify(row.payload.details)) : (options.value?.detail_template || []).map(detail => ({ client_key: crypto.randomUUID(), template_key: detail.key, detail_type: detail.type, category_label: detail.category, is_selected: false, description: '' }))
  editorDetailFiles.value = { ...detailFiles.value }
  editorItem.value = row ? { ...emptyItem(), id: row.id, product_id: row.payload.product_id, product_category_id: row.payload.product_category_id, product_unit_id: row.payload.unit_id, product_color_id: row.payload.product_color_id, product_image_id: row.payload.retained_image_ids[0] || null, product_description: row.productName, specification: row.specification, color: row.payload.customer_color || '', material: row.payload.material || '', quantity: row.quantity, unit_code: options.value?.units.find(unit => unit.id === row.payload.unit_id)?.unit_code || '', target_unit_price: row.unitPriceCny, notes: row.payload.special_requirements } : emptyItem()
  if (row) editorItem.value.product_number_snapshot = options.value?.products.find(product => product.id === row.payload.product_id)?.product_number || task.value?.products.find(product => product.id === row.id)?.product_number || ''
  editorVisible.value = true
}
function confirmProduct(value: { item: InquiryItem; imageChanged: boolean; imageFile: File | null; removeImage: boolean }) {
  const item = value.item
  const unit = options.value?.units.find(row => row.id === item.product_unit_id || row.unit_code === item.unit_code)
  const currency = options.value?.currencies.find(row => row.code === 'CNY')
  if (!unit || !currency) { ElMessage.warning('请选择已维护的真实单位，并检查人民币币种。'); return }
  if (!/^[1-9]\d*$/.test(String(item.quantity))) { ElMessage.warning('生产数量必须是大于0的整数。'); return }
  if (item.target_unit_price == null || String(item.target_unit_price).trim() === '' || !Number.isFinite(Number(item.target_unit_price)) || Number(item.target_unit_price) < 0) { ElMessage.warning('请填写正确的人民币单价。'); return }
  const old = editingProduct.value
  const id = old?.id || crypto.randomUUID()
  const retainedImages = old?.payload.retained_image_ids || []
  // 已有待上传主图时，只替换待上传文件，不能再次移除保留的附图。
  const retainedImageIds = value.imageChanged && !productFiles.value[id]?.length ? retainedImages.slice(1) : retainedImages
  const payload: ProductionTaskProductInput = { ...(old?.payload || {}), ...(value.imageChanged ? { replace_primary_image: Boolean(old && value.imageFile) } : {}), client_key: id, product_id: item.product_id || null, product_category_id: item.product_category_id || null, product_color_id: item.product_color_id || null, color_code: options.value?.colors.find(row => row.id === item.product_color_id)?.color_code || '', customer_product_name: item.product_description, customer_specification: item.specification, customer_color: item.color, material: item.material, quantity: String(item.quantity), unit_id: unit.id, currency_id: currency.id, unit_price: String(item.target_unit_price), exchange_rate: '1.00000000', special_requirements: item.notes, packaging_method: old?.payload.packaging_method || '', retained_image_ids: [...retainedImageIds], details: JSON.parse(JSON.stringify(editorDetails.value)) }
  const product = options.value?.products.find(row => row.id === item.product_id)
  const row: EditableProduct = { id, productName: item.product_description, productCode: product?.item_number || '', specification: item.specification, colorLabel: item.color, quantity: String(item.quantity), originalQuantity: old?.originalQuantity || '', unitName: unit.unit_name, sourceLocked: false, unitPriceCny: String(item.target_unit_price), lineAmountCny: old?.lineAmountCny || '', isCny: true, payload, originalPayload: old?.originalPayload || '', deletionReason: old?.deletionReason || '' }
  if (old) products.value.splice(products.value.indexOf(old), 1, row)
  else products.value.push(row)
  if (!expandedProductIds.value.includes(id)) expandedProductIds.value.push(id)
  if (value.imageChanged) {
    productFiles.value[id] = value.imageFile ? [value.imageFile] : []
    if (productPreviews.value[id]) URL.revokeObjectURL(productPreviews.value[id])
    if (value.imageFile) productPreviews.value[id] = URL.createObjectURL(value.imageFile)
    else delete productPreviews.value[id]
  }
  Object.assign(detailFiles.value, editorDetailFiles.value)
  editorVisible.value = false
}
function removeProduct(row: EditableProduct) {
  if (sourceLocked.value || isTerminal.value || row.deletionReason) return
  products.value = products.value.filter(item => item.id !== row.id)
  expandedProductIds.value = expandedProductIds.value.filter(id => id !== row.id)
  row.payload.details.forEach(detail => delete detailFiles.value[detail.client_key])
  delete productFiles.value[row.id]
  if (productPreviews.value[row.id]) URL.revokeObjectURL(productPreviews.value[row.id])
  delete productPreviews.value[row.id]
}
function chooseDetailImage(key: string, event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 10 * 1024 * 1024) { ElMessage.warning('明细图片需为 JPG、PNG 或 WebP，且不超过10 MB。'); return }
  editorDetailFiles.value[key] = file
}
function imageUrl(row: EditableProduct) { if (productPreviews.value[row.id]) return productPreviews.value[row.id]; return row.payload.retained_image_ids[0] ? productionTaskBusinessFileUrl(taskId.value, row.payload.retained_image_ids[0]) : '' }
watch(() => form.includes_tax, value => { if (!value) form.tax_rate = null })

function normalizedRequirementsHtml(value: string): string {
  const html = value.trim()
  if (!html) return ''
  const element = document.createElement('div')
  element.innerHTML = html
  const text = (element.textContent || '').replace(/[\u00a0\u200b\ufeff]/g, '').trim()
  return text || element.querySelector('img, video, audio, iframe, hr, input, table') ? html : ''
}

function sameRequirementsHtml(currentValue: string, originalValue: string): boolean {
  const current = normalizedRequirementsHtml(currentValue)
  const original = normalizedRequirementsHtml(originalValue)
  if (current === original) return true
  if (!original) return false

  // 旧数据可能是纯文本，富文本编辑器初始化时会自动包成一个普通段落。
  const originalContainer = document.createElement('div')
  originalContainer.innerHTML = original
  if (originalContainer.childElementCount > 0) return false
  const currentContainer = document.createElement('div')
  currentContainer.innerHTML = current
  const paragraph = currentContainer.firstElementChild
  return currentContainer.childNodes.length === 1
    && paragraph?.tagName === 'P'
    && paragraph.attributes.length === 0
    && paragraph.childNodes.length === 1
    && paragraph.firstChild?.nodeType === Node.TEXT_NODE
    && paragraph.textContent === original
}

const requirementsChanged = computed(() => !sameRequirementsHtml(form.special_requirements_html, originalRequirementsHtml.value))

const changes = computed(() => {
  if (!task.value) return []
  const result: Array<{ key: string; label: string; before: string; after: string; bomImpact: boolean }> = []
  if (form.delivery_date !== task.value.delivery_date) {
    result.push({ key: 'delivery', label: '预计交期', before: task.value.delivery_date, after: form.delivery_date, bomImpact: false })
  }
  const beforeFollowers = task.value.followers.map((item) => item.id).sort()
  const afterFollowers = [...form.follower_ids].sort()
  if (JSON.stringify(beforeFollowers) !== JSON.stringify(afterFollowers)) {
    result.push({
      key: 'followers', label: '跟单员',
      before: task.value.followers.map((item) => item.display_name).join('、') || '未设置',
      after: followerSummary(form.follower_ids), bomImpact: false,
    })
  }
  if (requirementsChanged.value) {
    result.push({ key: 'requirements', label: '生产要求', before: '原要求', after: '已修改', bomImpact: false })
  }
  products.value.forEach((row) => {
    if (row.quantity !== row.originalQuantity) {
      result.push({
        key: `quantity-${row.id}`,
        label: `${row.productName} / ${row.colorLabel}`,
        before: `${row.originalQuantity} ${row.unitName}`,
        after: `${row.quantity} ${row.unitName}`,
        bomImpact: Boolean(task.value?.current_boms?.some((bom) => bom.product_line_id === row.id)),
      })
    }
  })
  for (const [key, label] of Object.entries(fieldLabels)) {
    if (sourceLocked.value && ['salesperson_id', 'order_date', 'preproduction_sample_required'].includes(key)) continue
    const value = form[key as keyof typeof form]
    if (value !== originalForm.value[key]) result.push({ key, label, before: String(originalForm.value[key] ?? '—'), after: String(value ?? '—'), bomImpact: false })
  }
  for (const row of products.value) if (hasDetailFiles(row) || JSON.stringify(row.payload) !== row.originalPayload || row.unitPriceCny !== task.value.products.find(item => item.id === row.id)?.local_unit_price || productFiles.value[row.id]?.length) result.push({ key: `product-${row.id}`, label: row.productName, before: row.originalPayload ? '原产品资料' : '无', after: '产品资料已修改', bomImpact: Boolean(task.value.current_boms?.some(bom => bom.product_line_id === row.id)) })
  for (const row of task.value.products) if (!products.value.some(item => item.id === row.id)) result.push({ key: `removed-${row.id}`, label: row.product_name, before: '原产品', after: '已移除', bomImpact: Boolean(task.value.current_boms?.some(bom => bom.product_line_id === row.id)) })
  return result
})

const dirty = computed(() => changes.value.length > 0)
const bomAffectedChanges = computed(() => changes.value.filter((item) => item.bomImpact))

function apiError(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查服务。'
  if (error.response.status === 412) return '数据已被其他人修改，请重新加载后再保存。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  return data.error?.message || data.detail || '保存失败，请检查填写内容。'
}

function productPayload(row: ProductionTaskProduct, quantity: string): ProductionTaskProductInput {
  return {
    client_key: row.id,
    product_id: row.product_id,
    product_color_id: row.product_color_id ?? null,
    product_category_id: row.product_category_id ?? null,
    color_code: row.color_code,
    quantity,
    unit_id: row.unit_id,
    currency_id: row.currency_id,
    unit_price: row.unit_price,
    exchange_rate: row.exchange_rate,
    exchange_rate_record_id: row.exchange_rate_record_id,
    customer_product_name: row.customer_product_name || row.product_name,
    customer_specification: row.customer_specification || row.specification,
    customer_color: row.customer_color ?? row.color_name,
    material: row.material || '',
    special_requirements: row.special_requirements || '',
    packaging_method: row.packaging_method || '',
    retained_image_ids: (row.images || []).map((item) => item.id),
    details: row.details.map((detail) => ({
      client_key: detail.id,
      template_key: detail.template_key,
      detail_type: detail.detail_type,
      category_label: detail.category_label,
      is_selected: detail.is_selected,
      description: detail.description,
    })),
  }
}

function buildPatch(): ProductionTaskPatchInput {
  if (!task.value) return {}
  const patch: ProductionTaskPatchInput = {}
  if (form.delivery_date !== task.value.delivery_date) patch.delivery_date = form.delivery_date
  const originalFollowers = task.value.followers.map((item) => item.id).sort()
  if (JSON.stringify([...form.follower_ids].sort()) !== JSON.stringify(originalFollowers)) {
    patch.follower_ids = [...form.follower_ids]
  }
  if (requirementsChanged.value) {
    patch.special_requirements_html = normalizedRequirementsHtml(form.special_requirements_html)
  }
  for (const key of Object.keys(fieldLabels)) {
    if (sourceLocked.value && ['salesperson_id', 'order_date', 'preproduction_sample_required'].includes(key)) continue
    const value = form[key as keyof typeof form]
    if (value !== originalForm.value[key]) Object.assign(patch, { [key]: ['planned_start_date', 'planned_end_date', 'planner_id'].includes(key) ? value || null : value })
  }
  if (products.value.some(changedProduct) || products.value.length !== task.value.products.length) patch.products = products.value.map(row => row.sourceLocked ? productPayload(task.value!.products.find(item => item.id === row.id)!, row.quantity) : { ...row.payload, quantity: row.quantity, unit_price: row.isCny ? row.unitPriceCny : row.payload.unit_price })
  return patch
}

function validate() {
  if (isTerminal.value) return '已完成或已取消的任务不能编辑。'
  if (!form.follower_ids.length) return '请选择至少一名跟单员。'
  if (!form.salesperson_id || !form.order_date) return '请选择业务员和下单日期。'
  if (form.includes_tax && ![3, 5, 7].includes(Number(form.tax_rate))) return '含税时请选择税率。'
  if (!form.order_tolerance_percent.trim() || !Number.isFinite(Number(form.order_tolerance_percent)) || Number(form.order_tolerance_percent) < 0 || Number(form.order_tolerance_percent) > 100) return '订单误差必须是0到100的百分比。'
  if (Boolean(form.planned_start_date) !== Boolean(form.planned_end_date)) return '请同时填写计划开工和计划完工。'
  if (form.planned_start_date && form.planned_end_date < form.planned_start_date) return '计划完工不能早于计划开工。'
  if (!products.value.length) return '请至少保留一个产品。'
  if (products.value.some(row => !row.originalPayload && (!row.payload.details.length || row.payload.details.some(detail => !detail.detail_type.trim())))) return '请补全产品的生产明细类型。'
  if (!form.delivery_date) return '请选择预计交期。'
  if (task.value && form.delivery_date < form.order_date) return '预计交期不能早于下单日期。'
  for (const row of products.value) {
    if (!/^[1-9]\d*$/.test(row.quantity)) return `${row.productName} / ${row.colorLabel} 的数量必须是大于 0 的整数。`
    if (row.sourceLocked && row.maxQuantity != null && Number(row.quantity) > row.maxQuantity) return `${row.productName} 的本次生产量不能超过 ${row.maxQuantity}。`
    if (!row.sourceLocked && (!row.unitPriceCny.trim() || !Number.isFinite(Number(row.unitPriceCny)) || Number(row.unitPriceCny) < 0)) return '请填写正确的人民币单价。'
  }
  if (!sourceLocked.value && products.value.some((row) => row.quantity !== row.originalQuantity) && task.value?.products.some((row) => !row.product_color_id && !(row.customer_product_name?.trim() && row.customer_specification?.trim() && row.unit_id && row.details.length && row.details.every((detail) => detail.detail_type.trim())))) {
    return '存在缺少有效颜色的历史产品行，暂不能批量修改数量。'
  }
  return ''
}

function confirmationToken(error: unknown) {
  if (!(error instanceof AxiosError) || error.response?.status !== 409) return ''
  const data = error.response.data as { error?: { code?: string; meta?: { confirmation_token?: string } } }
  return data.error?.code === 'BOM_SYNC_CONFIRMATION_REQUIRED'
    ? data.error.meta?.confirmation_token || ''
    : ''
}

async function save() {
  const message = validate()
  if (message) { ElMessage.warning(message); return }
  const basePatch = buildPatch()
  if (!Object.keys(basePatch).length) { ElMessage.info('没有检测到需要保存的修改。'); return }
  try {
    await ElMessageBox.confirm(
      bomAffectedChanges.value.length
        ? `本次有 ${bomAffectedChanges.value.length} 项数量变更会影响关联 BOM。${returnsToDraft.value ? '保存后任务将回到草稿并重新走 PMC；' : '保存后保留当前生产状态；'}请选择的 BOM 处理方式为“${bomSyncMode.value === 'SYNC' ? '同步并生成必要的新版本' : '保留当前 BOM'}”。`
        : returnsToDraft.value ? '保存后，待确认或已确认的任务将回到草稿，需要重新提交 PMC。' : '确认保存本次修改？保存后保留当前生产状态。',
      '确认保存修改',
      { type: 'warning', confirmButtonText: '确认保存', cancelButtonText: '取消' },
    )
  } catch { return }

  saving.value = true
  try {
    let patch = basePatch
    let result
    try {
      result = await updateProductionTask(taskId.value, patch, productFiles.value, detailFiles.value, etag.value)
    } catch (error) {
      const token = confirmationToken(error)
      if (!token) throw error
      patch = { ...basePatch, bom_sync_mode: bomSyncMode.value, bom_sync_token: token }
      result = await updateProductionTask(taskId.value, patch, productFiles.value, detailFiles.value, etag.value)
    }
    allowLeave.value = true
    ElMessage.success('生产任务单修改已保存。')
    await router.replace({ name: 'production-task-detail', params: { taskId: result.data.id } })
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [result, optionData] = await Promise.all([
      fetchProductionTask(taskId.value),
      fetchProductionTaskOptions(),
    ])
    // Serializer 方法字段可能返回 JSON 数字，进入编辑状态前统一为四位人民币字符串。
    result.data.products = result.data.products.map(row => {
      const unitPrice = multiplyAmount4(row.local_unit_price, 1)
      const lineAmount = multiplyAmount4(row.local_total_amount, 1)
      if (unitPrice === null || lineAmount === null) throw new Error('产品人民币金额无效，请重新加载或联系管理员。')
      return { ...row, local_unit_price: unitPrice, local_total_amount: lineAmount }
    })
    task.value = result.data
    Object.assign(form, { salesperson_id: result.data.salesperson?.id || '', order_date: result.data.order_date, includes_tax: result.data.includes_tax ?? false, tax_rate: result.data.tax_rate ?? null, order_tolerance_percent: result.data.order_tolerance_percent || '0', is_repeat_order: result.data.is_repeat_order ?? false, preproduction_sample_required: result.data.preproduction_sample_required ?? false, delivery_method: result.data.delivery_method, planner_id: result.data.planner?.id || null, planned_start_date: result.data.planned_start_date || '', planned_end_date: result.data.planned_end_date || '', production_priority: result.data.production_priority || 'NORMAL', production_batch_number: result.data.production_batch_number || '' })
    etag.value = result.etag
    options.value = optionData
    form.delivery_date = result.data.delivery_date
    form.follower_ids = result.data.followers.map((item) => item.id)
    originalRequirementsHtml.value = result.data.special_requirements_html || ''
    form.special_requirements_html = originalRequirementsHtml.value
    originalForm.value = { ...form }
    products.value = result.data.products.map((row) => ({
      id: row.id,
      productName: row.customer_product_name || row.product_name,
      productCode: row.product_id ? row.item_number : '',
      specification: row.specification_display || row.customer_specification || row.specification,
      colorLabel: [row.customer_color || row.color_name, row.color_code].filter(Boolean).join(' / ') || '未设置颜色',
      quantity: String(row.quantity),
      originalQuantity: String(row.quantity),
      unitName: row.unit_name,
      sourceLocked: Boolean(row.source_delivery_batch_line_id || result.data.sales_order_id),
      unitPriceCny: row.local_unit_price,
      lineAmountCny: row.local_total_amount,
      isCny: row.currency_code === 'CNY',
      payload: productPayload(row, String(row.quantity)), originalPayload: JSON.stringify(productPayload(row, String(row.quantity))), maxQuantity: row.max_production_quantity, deletionReason: row.deletion_blocked_reason || '',
    }))
    expandedProductIds.value = products.value[0] ? [products.value[0].id] : []
  } catch (error) {
    loadError.value = apiError(error)
  } finally {
    loading.value = false
  }
}

async function back() {
  await router.push({ name: 'production-task-detail', params: { taskId: taskId.value } })
}

onBeforeRouteLeave(async () => {
  if (!dirty.value || allowLeave.value) return true
  try {
    await ElMessageBox.confirm('当前修改尚未保存，确认离开吗？', '未保存修改', {
      type: 'warning', confirmButtonText: '离开', cancelButtonText: '继续编辑',
    })
    return true
  } catch { return false }
})

onMounted(() => { void load() })
</script>

<template>
  <main class="production-edit-page production-task-edit-page" v-loading="loading" :aria-busy="loading">
    <template v-if="task && !loadError">
      <header class="page-heading">
        <div class="heading-title"><h1>编辑生产任务单</h1><strong>{{ task.task_number }}</strong><span :class="['task-status', 'status-' + task.status.toLowerCase()]">{{ task.status_display }}</span></div>
        <ElButton @click="back">返回详情</ElButton>
      </header>
      <ElAlert v-if="returnsToDraft" type="warning" show-icon :closable="false" class="review-alert" title="修改待校验或已接单任务后将回到草稿，需重新提交 PMC 确认。" />
      <ElAlert v-if="isTerminal" type="info" show-icon :closable="false" class="review-alert" title="已完成或已取消的任务不能编辑。" />
      <section class="edit-summary summary-bar" aria-label="任务汇总">
        <div><span>人民币金额合计</span><strong class="summary-money">￥{{ totalAmountCny }}</strong></div>
        <div><span>生产数量（按单位）</span><strong>{{ quantitySummary || '—' }}</strong></div>
        <div><span>交期日期</span><strong>{{ form.delivery_date || '待填写' }}</strong></div>
      </section>
      <div class="editor-layout">
        <aside class="task-sidebar">
          <section class="basic-section">
            <h2 class="side-title">任务资料</h2>
            <div class="info-grid">
              <label class="info-wide readonly-field"><span>生产任务单号</span><ElInput :model-value="task.task_number" readonly aria-label="生产任务单号" /></label>
              <label class="info-wide readonly-field"><span>来源订单</span><ElInput :model-value="task.source_sales_order_number || '手动创建（未关联销售订单）'" readonly aria-label="来源订单" /></label>
              <label><span>业务员 <i>*</i></span><ElSelect v-model="form.salesperson_id" aria-label="业务员" filterable :disabled="sourceLocked || isTerminal"><ElOption v-for="employee in followerOptions" :key="employee.id" :label="employee.display_name" :value="employee.id" /></ElSelect></label>
              <label><span>跟单员 <i>*</i></span><ElSelect v-model="form.follower_ids" aria-label="跟单员" multiple filterable collapse-tags collapse-tags-tooltip :disabled="isTerminal"><ElOption v-for="employee in followerOptions" :key="employee.id" :label="employee.display_name" :value="employee.id" /></ElSelect></label>
              <label><span>下单日期 <i>*</i></span><ElDatePicker v-model="form.order_date" aria-label="下单日期" type="date" value-format="YYYY-MM-DD" :disabled="sourceLocked || isTerminal" /></label>
              <label><span>预计交期 <i>*</i></span><ElDatePicker v-model="form.delivery_date" aria-label="预计交期" type="date" value-format="YYYY-MM-DD" :disabled="isTerminal" /></label>
              <label><span>含税</span><ElSelect v-model="form.includes_tax" aria-label="含税" :disabled="isTerminal"><ElOption label="含税" :value="true"/><ElOption label="不含税" :value="false"/></ElSelect></label>
              <label v-if="form.includes_tax"><span>税率 <i>*</i></span><ElSelect v-model="form.tax_rate" aria-label="税率" :disabled="isTerminal" placeholder="请选择税率"><ElOption v-for="rate in [3,5,7]" :key="rate" :value="rate" :label="rate + '%'"/></ElSelect></label>
              <label><span>订单误差 <i>*</i></span><ElInput v-model="form.order_tolerance_percent" aria-label="订单误差" :disabled="isTerminal"><template #append>%</template></ElInput></label>
              <label><span>返单</span><ElSelect v-model="form.is_repeat_order" aria-label="返单" :disabled="isTerminal"><ElOption label="是" :value="true"/><ElOption label="否" :value="false"/></ElSelect></label>
              <label><span>交货方式</span><ElSelect v-model="form.delivery_method" aria-label="交货方式" :disabled="isTerminal"><ElOption label="一次交付" value="SINGLE"/><ElOption label="分批交付" value="SPLIT"/></ElSelect></label>
              <label v-if="!sourceLocked"><span>产前样</span><ElSelect v-model="form.preproduction_sample_required" aria-label="产前样" :disabled="isTerminal"><ElOption label="需要" :value="true"/><ElOption label="不需要" :value="false"/></ElSelect></label>
            </div>
          </section>
          <section class="task-schedule">
            <h2>生产安排</h2>
            <div class="info-grid">
              <label><span>计划员</span><ElSelect v-model="form.planner_id" aria-label="计划员" clearable filterable :disabled="isTerminal"><ElOption v-for="employee in followerOptions" :key="employee.id" :label="employee.display_name" :value="employee.id" /></ElSelect></label>
              <label><span>生产优先级</span><ElSelect v-model="form.production_priority" aria-label="生产优先级" :disabled="isTerminal"><ElOption v-for="(label, value) in {URGENT:'紧急',HIGH:'高',NORMAL:'普通',LOW:'低'}" :key="value" :value="value" :label="label"/></ElSelect></label>
              <label><span>计划开工</span><ElDatePicker v-model="form.planned_start_date" aria-label="计划开工" type="date" value-format="YYYY-MM-DD" :disabled="isTerminal" /></label>
              <label><span>计划完工</span><ElDatePicker v-model="form.planned_end_date" aria-label="计划完工" type="date" value-format="YYYY-MM-DD" :disabled="isTerminal" /></label>
              <label class="info-wide"><span>生产批号</span><ElInput v-model="form.production_batch_number" aria-label="生产批号" maxlength="100" :disabled="isTerminal" /></label>
            </div>
          </section>
          <p class="required-legend"><i>*</i> 为必填</p>
        </aside>
        <div class="editor-main">
          <section class="edit-section products-section">
            <div class="section-title-row"><h2>生产产品档案</h2><ElButton v-if="!sourceLocked" :disabled="isTerminal" @click="editProduct()">添加产品</ElButton></div>
            <p v-if="sourceLocked" class="source-note"><ElIcon><Lock /></ElIcon> 来源产品和价格锁定，可调整本次生产量</p>
            <div class="product-files">
              <details v-for="row in products" :key="row.id" class="product-file" :data-product-id="row.id" :open="expandedProductIds.includes(row.id)" @toggle="syncProductExpansion(row.id, $event)">
                <summary class="product-summary"><ArrowRight class="file-arrow" aria-hidden="true"/><span class="file-name">{{ row.productName }}</span><span class="file-code">{{ row.productCode || '—' }}</span></summary>
                <div class="file-content">
                  <div class="product-media">
                    <div class="product-photo"><ProductImage :src="imageUrl(row)" :name="row.productName" large/></div>
                    <div v-if="imageUrl(row)" class="product-images"><ProductImage :src="imageUrl(row)" :name="row.productName"/><ProductImage v-for="imageId in row.payload.retained_image_ids.slice(productPreviews[row.id] ? 0 : 1)" :key="imageId" :src="productionTaskBusinessFileUrl(taskId, imageId)" :name="row.productName + '附图'"/></div>
                    <small class="image-hint">{{ imageUrl(row) ? '点击图片查看大图' : '暂无产品图片' }}</small>
                  </div>
                  <div class="product-editor-body">
                    <dl class="product-fields">
                      <div><dt>产品</dt><dd>{{ row.productName }}</dd></div>
                      <div><dt>货号</dt><dd>{{ row.productCode || '—' }}</dd></div>
                      <div><dt>颜色</dt><dd>{{ row.colorLabel || '—' }}</dd></div>
                      <div><dt>规格</dt><dd>{{ row.specification || '—' }}</dd></div>
                      <div><dt>材质</dt><dd>{{ row.payload.material || '—' }}</dd></div>
                      <div><dt>单位</dt><dd>{{ row.unitName }}</dd></div>
                      <div><dt>计划开工</dt><dd>{{ form.planned_start_date || '待安排' }}</dd></div>
                      <div><dt>计划完工</dt><dd>{{ form.planned_end_date || '待安排' }}</dd></div>
                    </dl>
                    <div class="price-fields">
                      <label><span>本次生产量 <i>*</i></span><ElInput v-model="row.quantity" inputmode="numeric" :aria-label="row.productName + '本次生产量'" :disabled="isTerminal"><template #append>{{ row.unitName }}</template></ElInput><small v-if="row.sourceLocked && row.maxQuantity != null">上限 {{ row.maxQuantity }} {{ row.unitName }}</small></label>
                      <label><span>人民币单价 <i v-if="!row.sourceLocked && row.isCny">*</i></span><ElInput v-if="!row.sourceLocked && row.isCny" v-model="row.unitPriceCny" inputmode="decimal" aria-label="人民币单价" :disabled="isTerminal"/><span v-else class="readonly-value">￥{{ row.unitPriceCny }}</span></label>
                      <div class="amount-field"><span>人民币金额</span><strong>￥{{ productAmountCny(row) }}</strong></div>
                    </div>
                    <div class="pack-fields">
                      <label><span>包装要求</span><ElInput v-model="row.payload.packaging_method" type="textarea" :rows="3" :disabled="sourceLocked || isTerminal" maxlength="3000" aria-label="包装要求"/></label>
                      <label><span>生产要求</span><ElInput v-model="row.payload.special_requirements" type="textarea" :rows="3" :disabled="sourceLocked || isTerminal" maxlength="3000" aria-label="产品生产要求"/></label>
                    </div>
                    <div class="product-actions">
                      <template v-if="!sourceLocked"><ElButton link type="primary" :disabled="isTerminal || !row.isCny" @click="editProduct(row)">编辑产品</ElButton><ElButton link type="danger" :disabled="isTerminal || !!row.deletionReason" @click="removeProduct(row)">删除</ElButton></template>
                      <span v-else>来源锁定</span><small v-if="row.deletionReason" class="action-reason">{{ row.deletionReason }}</small><small v-if="!row.sourceLocked && !row.isCny" class="action-reason">历史外币产品保留冻结价格，单价不可修改。</small>
                    </div>
                  </div>
                </div>
              </details>
              <p v-if="!products.length" class="empty-products">暂无产品，请添加真实产品或自定义产品。</p>
            </div>
          </section>
          <section class="edit-section requirements-section">
            <h2>生产要求</h2>
            <InquiryWangEditor v-model="form.special_requirements_html" class="requirements-field" upload-url="" upload-etag="" :toolbar-keys="['bold', 'italic', 'bulletedList']" :show-upload-notice="false" :maxlength="4000" :inert="isTerminal" placeholder="填写生产要求、质量要求和注意事项" />
          </section>
          <section class="edit-section review-section">
            <div class="bom-section"><h2>BOM 同步设置</h2><ElRadioGroup v-model="bomSyncMode" :disabled="isTerminal"><ElRadio value="SYNC">修改任务并同步 BOM（已确认 BOM 会生成新版本）</ElRadio><ElRadio value="KEEP">仅保存任务，保留当前 BOM</ElRadio></ElRadioGroup></div>
            <div class="comparison-card">
              <div class="section-title-row"><h2>变更对照</h2><span>仅显示本次修改的字段</span></div>
              <p v-if="!changes.length" class="no-changes">尚未修改任何字段</p>
              <div v-else class="product-table-wrap"><table class="comparison-table"><thead><tr><th>字段</th><th>修改前</th><th>修改后</th></tr></thead><tbody><tr v-for="item in changes" :key="item.key"><td>{{ item.label }}</td><td>{{ item.before }}</td><td class="new-value">{{ item.after }}</td></tr></tbody></table></div>
              <div class="impact-note"><ElIcon><WarningFilled/></ElIcon><p>{{ returnsToDraft ? '保存后任务回到草稿，需重新提交 PMC。' : '保存后保留当前生产状态。' }} 同步已确认 BOM 将生成新版本，需单独重新确认。</p></div>
            </div>
          </section>
        </div>
      </div>
      <footer class="edit-footer save-bar"><span aria-live="polite">{{ dirty ? '有未保存修改' : '尚未修改' }}</span><div><ElButton @click="back">取消</ElButton><ElButton type="primary" :loading="saving" :disabled="isTerminal || !dirty" @click="save">保存修改</ElButton></div></footer>
      <AppWindowDialog v-model="editorVisible" class="production-product-editor" :title="editingId ? '编辑生产产品' : '添加生产产品'" :width="1180" :height="780" :min-width="320" :close-on-click-modal="false" destroy-on-close>
        <InquiryProductDialog ref="productEditor" v-model="editorVisible" embedded hide-embedded-footer hide-summary business-title="本次生产内容" scene="sales-order" :candidate-loader="loadProductionCandidates" :item="editorItem" :categories="options?.categories || []" :units="options?.units || []" :colors="options?.colors || []" :currencies="[{code:'CNY'}]" quotation-currency="CNY" :can-upload="true" :close-on-confirm="false" :image-url="editingProduct ? imageUrl(editingProduct) : ''" :pending-image="editingId ? productFiles[editingId]?.[0] : null" @confirm="confirmProduct">
          <template #before-actions>
            <section class="product-detail-editor">
              <h3>生产明细</h3>
              <div class="product-table-wrap"><table><colgroup><col style="width:130px"><col style="width:140px"><col style="width:72px"><col style="width:280px"><col style="width:270px"></colgroup><thead><tr><th>类型</th><th>类别项</th><th>是否</th><th>描述</th><th>明细图片</th></tr></thead><tbody><tr v-for="detail in editorDetails" :key="detail.client_key"><td>{{ detail.detail_type }}</td><td>{{ detail.category_label }}</td><td><ElCheckbox v-model="detail.is_selected" :aria-label="detail.category_label + '是否需要'"/></td><td><ElInput v-model="detail.description" maxlength="2000" :aria-label="detail.category_label + '描述'"/></td><td><input type="file" accept="image/jpeg,image/png,image/webp" :aria-label="detail.category_label + '明细图片'" @change="chooseDetailImage(detail.client_key, $event)"/><small v-if="editorDetailFiles[detail.client_key]">{{ editorDetailFiles[detail.client_key]?.name }}</small><small v-else-if="task.products.find(product => product.id === editingId)?.details.find(item => item.id === detail.client_key)?.image_name">已有图片保留；选择新图后替换</small></td></tr><tr v-if="!editorDetails.length"><td colspan="5" class="empty-products">暂无生产明细</td></tr></tbody></table></div>
            </section>
          </template>
        </InquiryProductDialog>
        <template #footer><ElButton @click="editorVisible = false">取消</ElButton><ElButton type="primary" @click="productEditor?.confirm()">{{ editingId ? '保存产品信息' : '添加产品' }}</ElButton></template>
      </AppWindowDialog>
    </template>
    <ElResult v-else-if="loadError" icon="error" title="生产任务单加载失败" :sub-title="loadError"><template #extra><ElButton type="primary" @click="load">重新加载</ElButton><ElButton @click="back">返回详情</ElButton></template></ElResult>
  </main>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.production-edit-page { min-width: 0; color: token.$crm-text-primary; font: 13px/20px token.$crm-font-body; --el-color-primary: #{token.$crm-primary}; }
h1, h2, h3, p, dl { margin: 0; }
h2 { font-size: 16px; line-height: 24px; font-weight: 600; }
h3 { font-size: 13px; line-height: 20px; font-weight: 600; }
.page-heading, .heading-title { display: flex; align-items: center; flex-wrap: wrap; gap: 14px; }
.page-heading { justify-content: space-between; min-height: 46px; margin-bottom: 14px; }
.page-heading h1 { font: 600 34px/44px token.$crm-font-display; }
.heading-title > strong { font-size: 15px; font-weight: 600; overflow-wrap: anywhere; }
.task-status { display: inline-flex; align-items: center; justify-content: center; min-width: 56px; height: 24px; padding: 0 8px; border-radius: 999px; background: token.$crm-warning; color: #faf9f5; font-size: 12px; font-weight: 500; line-height: 18px; }
.status-draft { background: token.$crm-neutral; }
.status-in_production, .status-completed { background: token.$crm-success; }
.status-cancelled { background: token.$crm-danger; }
.review-alert { margin-bottom: 14px; border: 1px solid token.$crm-border-default; border-radius: 5px; }
.summary-bar, .task-sidebar, .edit-section, .save-bar { box-sizing: border-box; border: 1px solid token.$crm-border-default; border-radius: 5px; background: token.$crm-color-surface; min-width: 0; }
.summary-bar { display: grid; grid-template-columns: 1.2fr 1fr 1fr; padding: 12px 16px; margin-bottom: 14px; font-variant-numeric: tabular-nums; }
.summary-bar > div { display: flex; flex-direction: column; justify-content: center; gap: 4px; min-width: 0; }
.summary-bar > div + div { padding-left: 24px; border-left: 1px solid token.$crm-border-default; }
.summary-bar span { color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; }
.summary-bar strong { font-size: 18px; line-height: 26px; overflow-wrap: anywhere; }
.summary-bar .summary-money { font-size: 22px; line-height: 28px; }
.editor-layout { display: grid; grid-template-columns: 380px minmax(0, 1fr); gap: 14px; align-items: start; }
.editor-main { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.side-title { padding: 10px 14px; background: token.$crm-color-subtle; border-bottom: 1px solid token.$crm-border-default; border-radius: 4px 4px 0 0; }
.info-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 14px; padding: 14px; }
.info-wide { grid-column: 1 / -1; }
.info-grid label, .price-fields label, .pack-fields label { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
label > span, dt, .amount-field > span { color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; }
label i, .required-legend i { color: token.$crm-danger; font-style: normal; }
.info-grid :deep(.el-select), .info-grid :deep(.el-date-editor) { width: 100%; min-width: 0; }
.task-schedule { border-top: 1px solid token.$crm-border-default; }
.task-schedule > h2 { padding: 14px 14px 0; font-size: 13px; line-height: 20px; }
.required-legend { padding: 0 14px 12px; font-size: 11px; color: token.$crm-text-secondary; }
.edit-section { padding: 14px 16px; }
.section-title-row { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; min-height: 24px; }
.section-title-row > span, .source-note { font-size: 12px; color: token.$crm-text-secondary; }
.source-note { display: flex; align-items: center; gap: 5px; margin-bottom: 12px; }
.product-files { display: flex; flex-direction: column; gap: 10px; }
.product-file { min-width: 0; border: 1px solid token.$crm-border-default; border-radius: 5px; }
.product-summary { display: flex; align-items: center; gap: 8px; min-height: 32px; box-sizing: border-box; padding: 5px 10px; list-style: none; cursor: pointer; border-radius: 4px; }
.product-summary::-webkit-details-marker { display: none; }
.product-summary:hover { background: token.$crm-color-row-hover; }
.product-file[open] > summary { border-bottom: 1px solid token.$crm-border-default; border-radius: 4px 4px 0 0; background: #f8f5ef; }
.file-arrow { width: 16px; height: 16px; flex: 0 0 16px; color: token.$crm-text-secondary; }
.product-file[open] .file-arrow { transform: rotate(90deg); color: token.$crm-primary; }
.file-name { min-width: 0; overflow-wrap: anywhere; font-weight: 500; }
.file-code { margin-left: auto; color: token.$crm-text-secondary; overflow-wrap: anywhere; text-align: right; }
.file-content { display: grid; grid-template-columns: 118px minmax(0, 1fr); gap: 20px; padding: 12px 16px; }
.product-media, .product-editor-body { min-width: 0; }
.product-photo { width: 118px; height: 98px; }
.product-media .product-photo :deep(.product-image.large) { width: 118px; height: 98px; border: 0; background: token.$crm-color-subtle; padding: 0; }
.product-media .product-photo :deep(.product-image.large img) { width: 100%; height: 100%; object-fit: contain; border-radius: 5px; }
.product-images { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.image-hint { display: block; font-size: 11px; line-height: 16px; color: token.$crm-text-secondary; margin-top: 6px; }
.product-fields, .price-fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px 24px; margin-bottom: 12px; }
.product-fields > div, .amount-field { min-width: 0; }
dd { margin: 2px 0 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.amount-field { display: flex; flex-direction: column; gap: 4px; }
.amount-field strong, .readonly-value { display: flex; align-items: center; min-height: 32px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.amount-field strong { font-size: 15px; }
.readonly-value { color: token.$crm-text-primary; font-size: 13px; }
.pack-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 24px; }
.product-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.product-actions > span, small { font-size: 11px; line-height: 16px; color: token.$crm-text-secondary; }
.action-reason { flex-basis: 100%; text-align: right; }
.empty-products { padding: 30px 12px; text-align: center; color: token.$crm-text-secondary; }
.requirements-field { margin-top: 12px; }
.requirements-field :deep(.inquiry-wang-editor__surface) { border: 1px solid token.$crm-border-default; border-radius: 5px; }
.requirements-field :deep(.w-e-toolbar) { border-bottom-color: token.$crm-border-default; background: token.$crm-color-subtle; }
.requirements-field :deep(.w-e-bar) { min-height: 36px; background: token.$crm-color-subtle; }
.requirements-field :deep(.w-e-bar-item button) { height: 32px; }
.requirements-field :deep(.w-e-text-container) { height: 110px !important; min-height: 0; background: token.$crm-color-surface; }
.requirements-field :deep(.w-e-text-container [data-slate-editor]) { min-height: 108px; padding: 10px 12px; font-size: 13px; line-height: 20px; }
.requirements-field[inert] :deep(.w-e-text-container) { background: token.$crm-color-disabled; }
.bom-section :deep(.el-radio-group) { display: flex; flex-wrap: wrap; gap: 8px 28px; margin-top: 8px; }
.bom-section :deep(.el-radio) { height: auto; min-height: 32px; white-space: normal; margin: 0; }
.bom-section :deep(.el-radio__label) { line-height: 20px; }
.comparison-card { border-top: 1px solid token.$crm-border-default; margin-top: 12px; padding-top: 14px; }
.product-table-wrap { min-width: 0; max-width: 100%; overflow-x: auto; border: 1px solid token.$crm-border-default; border-radius: 5px; }
table { width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0; font-size: 13px; }
th, td { box-sizing: border-box; padding: 6px 16px; border-bottom: 1px solid token.$crm-border-default; text-align: left; overflow-wrap: anywhere; }
th { height: 44px; background: token.$crm-color-subtle; color: token.$crm-text-secondary; font-weight: 500; }
td { height: 34px; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover td { background: token.$crm-color-row-hover; }
.new-value { color: token.$crm-primary; background: #fffaf3; }
.no-changes { color: token.$crm-text-secondary; }
.impact-note { display: flex; align-items: flex-start; gap: 8px; margin-top: 12px; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.impact-note .el-icon { flex-shrink: 0; color: token.$crm-warning; margin-top: 2px; }
.save-bar { position: sticky; bottom: 0; z-index: 8; display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; padding: 12px 16px; }
.save-bar > span { font-size: 12px; color: token.$crm-text-secondary; }
.save-bar > div { display: flex; flex-wrap: wrap; gap: 8px; }
.production-edit-page :deep(.el-button) { height: 32px; margin: 0; border-radius: 5px; font-size: 13px; }
.production-edit-page :deep(.el-input__wrapper), .production-edit-page :deep(.el-select__wrapper) { min-height: 32px; box-sizing: border-box; border-radius: 5px; }
.production-edit-page :deep(.el-input__wrapper) { height: 32px; }
.production-edit-page :deep(.el-input__inner) { height: 30px; }
.production-edit-page :deep(.el-input-group__append) { padding: 0 9px; background: token.$crm-color-subtle; }
.production-edit-page :deep(.el-textarea__inner) { min-height: 78px !important; border-radius: 5px; font: inherit; padding: 8px 10px; }
.readonly-field :deep(.el-input__wrapper) { background: token.$crm-color-subtle; }
.production-edit-page :deep(.el-button:focus-visible), summary:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
.product-detail-editor { margin-top: 22px; }
.product-detail-editor h3 { margin-bottom: 12px; }
.product-detail-editor table { min-width: 892px; }
.product-detail-editor input[type="file"] { width: 100%; font-size: 12px; }
.product-detail-editor input[type="file"]::file-selector-button { height: 32px; padding: 0 10px; margin-right: 8px; border: 1px solid token.$crm-border-default; border-radius: 5px; color: token.$crm-text-primary; background: token.$crm-color-surface; font: inherit; cursor: pointer; }
.product-detail-editor td { padding-top: 5px; padding-bottom: 5px; }
.product-detail-editor small { display: block; }
@media (max-width: 1600px) {
  .product-fields, .price-fields { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 1100px) {
  .editor-layout { grid-template-columns: minmax(0, 1fr); }
  .task-sidebar { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: start; }
  .task-schedule { border-top: 0; border-left: 1px solid token.$crm-border-default; }
  .task-schedule > h2 { padding: 10px 14px; background: token.$crm-color-subtle; font-size: 16px; line-height: 24px; border-bottom: 1px solid token.$crm-border-default; border-radius: 0 4px 0 0; }
  .side-title { border-radius: 4px 0 0 0; }
  .required-legend { grid-column: 1 / -1; }
  .product-fields, .price-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 650px) {
  .heading-title { gap: 8px; }
  .summary-bar { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .summary-bar > div + div { border-left: 0; border-top: 1px solid token.$crm-border-default; padding: 10px 0 0; }
  .task-sidebar { display: block; }
  .info-grid, .product-fields, .price-fields, .pack-fields { grid-template-columns: minmax(0, 1fr); }
  .task-schedule { border-left: 0; border-top: 1px solid token.$crm-border-default; }
  .task-schedule > h2 { border-radius: 0; }
  .file-content { grid-template-columns: minmax(0, 1fr); gap: 12px; padding: 12px; }
  .product-media { display: flex; flex-wrap: wrap; align-items: start; gap: 8px; }
  .product-images { margin-top: 0; max-width: 118px; }
  .image-hint { flex-basis: 100%; margin-top: 0; }
  .edit-section { padding: 14px 12px; }
  .save-bar { padding: 10px; }
  .save-bar > span { max-width: 80px; }
  .save-bar :deep(.el-button) { padding: 0 10px; }
  .comparison-table th, .comparison-table td { padding-left: 8px; padding-right: 8px; }
}
</style>

<style lang="scss">
@use '@/styles/crm/tokens' as token;

// 窗口通过 Teleport 挂载到 body；使用本页专属前缀，避免影响其他业务窗口。
.production-product-editor.app-window-dialog.el-dialog {
  border-radius: 5px;
  .el-button { height: 32px; margin: 0; border-radius: 5px; font-size: 13px; }
  .entry-columns { margin-top: 0; }
  .app-window-dialog__body { padding: 16px; }
  .app-window-dialog__footer { display: flex; justify-content: flex-end; gap: 10px; padding: 12px 24px; border-top-color: token.$crm-border-default; }
  @media (max-width: 650px) {
    .identity-fields { grid-template-columns: minmax(0, 1fr); }
    .mode-bar, .mode-bar [role="tablist"] { flex-wrap: wrap; gap: 8px; }
    .candidate-table { overflow-x: auto; }
    .candidate-table table { min-width: 560px; }
  }
}
</style>
