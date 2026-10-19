<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { Delete, Picture, Plus, UploadFilled, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'

import InquiryWangEditor from '@/components/InquiryWangEditor.vue'
import ProductCreateDialog from '@/components/products/ProductCreateDialog.vue'
import ProductPickerDialog from '@/components/products/ProductPickerDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { ProductInformation } from '@/types/product'
import {
  createProductionTask,
  fetchProductionTask,
  fetchProductionTaskOptions,
  productionTaskBusinessFileUrl,
  reserveProductionTaskContractNumber,
  submitProductionTask,
  updateProductionTask,
} from '@/api/productionTasks'
import type {
  ProductOption,
  ProductionDeliveryMethod,
  ProductionTask,
  ProductionTaskDetailInput,
  ProductionTaskInput,
  ProductionTaskOptions,
  ProductionTaskPatchInput,
  ProductionTaskProduct,
  ProductionTaskProductInput,
  ProductionTaskProductImage,
} from '@/types/productionTask'

interface DetailDraft extends ProductionTaskDetailInput {
  imageFile: File | null
  imageName: string | null
}

interface PendingProductImage {
  key: string
  file: File
  previewUrl: string
}

interface ProductDraft {
  clientKey: string
  sourceLocked: boolean
  product_id: string | null
  product_code: string
  item_number: string
  product_name: string
  specification: string
  customer_product_name: string
  customer_specification: string
  customer_color: string
  material: string
  unit_label: string
  color_card: string
  color_name: string
  product_color_id: string
  color_code: string
  quantity: string
  unit_id: string
  currency_id: string
  unit_price: string
  exchange_rate: string
  existingImages: ProductionTaskProductImage[]
  newImages: PendingProductImage[]
}

interface ProductTaskDraft {
  special_requirements: string
  packaging_method: string
  details: DetailDraft[]
}

interface ProductGroup {
  key: string
  productId: string | null
  rows: ProductDraft[]
}

interface BomSyncAffectedLine {
  product_line_id: string
  product_name: string
  old_product_name?: string
  new_product_name?: string
  color_name: string
  old_color_name?: string
  new_color_name?: string
  old_quantity: string
  new_quantity: string
  bom_quantity: string
  bom_number: string
  change_types?: Array<'PRODUCT' | 'COLOR' | 'QUANTITY'>
}

interface BomSyncMeta {
  affected_bom_count: number
  affected_lines: BomSyncAffectedLine[]
  confirmation_token: string
}

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const saving = ref(false)
const workflowLoading = ref(false)
const errorMessage = ref('')
const options = ref<ProductionTaskOptions | null>(null)
const existing = ref<ProductionTask | null>(null)
const etag = ref('')
const productDialogVisible = ref(false)
const productCreateDialogVisible = ref(false)
const dialogProductId = ref('')
const productDialogTargetKey = ref('')
const taskDetailDialogVisible = ref(false)
const taskDetailRowKey = ref('')
const imageDialogVisible = ref(false)
const imageManagerKey = ref('')
const previewDialogVisible = ref(false)
const previewImageUrl = ref('')
const previewImageName = ref('')
const contractNumber = ref('')
const contractNumberToken = ref('')
const taskId = computed(() => typeof route.params.taskId === 'string' ? route.params.taskId : '')
const isEditing = computed(() => Boolean(taskId.value))
const isReadOnly = computed(() => route.name === 'production-task-detail')
const canEditTask = computed(() => authStore.hasPermission('production_tasks.change_productiontask'))
const hasSubmitPermission = computed(() => authStore.hasPermission('production_tasks.submit_productiontask'))
const canConfirmTask = computed(() => authStore.hasPermission('production_tasks.confirm_productiontask'))
const isTerminalTask = computed(() => existing.value?.status === 'COMPLETED' || existing.value?.status === 'CANCELLED')
const canSubmitTask = computed(() => hasSubmitPermission.value && (
  !isEditing.value || existing.value?.status === 'DRAFT' || existing.value?.status === 'PENDING_VALIDATION'
))
const canSubmitFromDetail = computed(() => isReadOnly.value && existing.value?.status === 'DRAFT' && hasSubmitPermission.value)
const canConfirmFromDetail = computed(() => isReadOnly.value && existing.value?.status === 'PENDING_VALIDATION' && canConfirmTask.value)
const workflowNotice = computed(() => {
  if (!isReadOnly.value || !existing.value) return null
  if (existing.value.status === 'DRAFT') {
    return {
      title: '当前生产任务单为草稿，BOM 暂时不能提交',
      description: '新建任务或已由 PMC 确认后再次修改，都会进入草稿状态。内容完善后，请点击“提交 PMC”重新进入确认流程。',
    }
  }
  if (existing.value.status === 'PENDING_VALIDATION') {
    return {
      title: '生产任务单正在等待 PMC 确认',
      description: canConfirmTask.value
        ? '请核对本次完善后的内容，再点击“PMC 确认”。确认后即可继续提交 BOM。'
        : 'PMC 确认后即可继续提交 BOM。',
    }
  }
  return null
})
const today = new Date().toISOString().slice(0, 10)
const form = reactive({
  task_number_suffix: '', order_date: today, delivery_date: '', salesperson_id: '',
  follower_ids: [] as string[], currency_id: '', includes_tax: false, tax_rate: null as 3 | 5 | 7 | null, order_tolerance_percent: '0',
  is_repeat_order: false, preproduction_sample_required: false, delivery_method: '' as ProductionDeliveryMethod | '',
  special_requirements_html: '', freight_amount: '0', other_fee_amount: '0',
})
watch(() => form.includes_tax, (includesTax) => { if (!includesTax) form.tax_rate = null })
const products = ref<ProductDraft[]>([])
const hasSourceLockedProducts = computed(() => products.value.some((row) => row.sourceLocked))
const sourceHeaderLocked = computed(() => isEditing.value && hasSourceLockedProducts.value)
const lineTaskDrafts = reactive<Record<string, ProductTaskDraft>>({})

const canCreateProduct = computed(() => Boolean(
  authStore.user?.is_superuser
  || (
    authStore.hasPermission('products.view_productinformation')
    && authStore.hasPermission('products.add_productinformation')
  )
))
const productGroups = computed<ProductGroup[]>(() => {
  const groups: ProductGroup[] = []
  const byKey = new Map<string, ProductGroup>()
  products.value.forEach((row) => {
    const groupKey = row.product_id || row.clientKey
    let group = byKey.get(groupKey)
    if (!group) {
      group = { key: groupKey, productId: row.product_id, rows: [] }
      byKey.set(groupKey, group)
      groups.push(group)
    }
    group.rows.push(row)
  })
  return groups
})
const imageManagerRow = computed(() => products.value.find((item) => item.clientKey === imageManagerKey.value) || null)
const taskDetailRow = computed(() => products.value.find((item) => item.clientKey === taskDetailRowKey.value) || null)
const taskDetailDraft = computed(() => lineTaskDrafts[taskDetailRowKey.value] || null)
const taskDetailDialogTitle = computed(() => {
  const row = taskDetailRow.value
  if (!row) return '生产任务单明细'
  const color = [row.color_name, row.color_code].filter(Boolean).join(' / ') || '未选择颜色'
  return `生产任务单明细 · ${row.customer_product_name || row.product_name} · ${color}`
})
const colorCards = computed(() => Array.from(new Set((options.value?.colors || []).map((item) => item.color_card))).filter(Boolean))

function key() { return crypto.randomUUID() }
function blankDetail(seed?: { key?: string; type?: string; category?: string }): DetailDraft {
  return {
    client_key: key(), template_key: seed?.key || '', detail_type: seed?.type || '',
    category_label: seed?.category || '', is_selected: false, description: '', imageFile: null, imageName: null,
  }
}
function templateDetails() {
  const template = options.value?.detail_template || []
  return template.length ? template.map((item) => blankDetail(item)) : [blankDetail()]
}
function productUnitLabel(unitId: string) {
  const unit = options.value?.units.find((item) => item.id === unitId)
  return unit ? `${unit.unit_code} · ${unit.unit_name}` : '未设置'
}
function blankProduct(product?: ProductOption): ProductDraft {
  return {
    clientKey: key(),
    sourceLocked: false,
    product_id: product?.id || '',
    product_code: product?.product_code || '',
    item_number: product?.item_number || '',
    product_name: product?.product_name || '',
    specification: product?.specification || '',
    customer_product_name: product?.product_name || '',
    customer_specification: product?.specification || '',
    customer_color: '',
    material: '',
    unit_label: product ? productUnitLabel(product.default_unit_id) : '',
    color_card: '', color_name: '', product_color_id: '', color_code: '', quantity: '',
    unit_id: product?.default_unit_id || '', currency_id: form.currency_id, unit_price: '',
    exchange_rate: isCnyCurrency(form.currency_id) ? '1.000' : '',
    existingImages: [], newImages: [],
  }
}
function bindProduct(row: ProductDraft, product: ProductOption) {
  row.product_id = product.id
  row.product_code = product.product_code
  row.item_number = product.item_number
  row.product_name = product.product_name
  row.specification = product.specification
  row.customer_product_name = product.product_name
  row.customer_specification = product.specification
  row.unit_id = product.default_unit_id
  row.unit_label = productUnitLabel(product.default_unit_id)
}
function currencyCode(currencyId: string) {
  return options.value?.currencies.find((item) => item.id === currencyId)?.code || ''
}
function isCnyCurrency(currencyId: string) { return currencyCode(currencyId) === 'CNY' }
function numberValue(value: string) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}
function total(row: ProductDraft) { return (numberValue(row.quantity) * numberValue(row.unit_price)).toFixed(4) }
function localUnitPrice(row: ProductDraft) { return (numberValue(row.unit_price) * numberValue(row.exchange_rate)).toFixed(4) }
function localTotal(row: ProductDraft) { return (numberValue(row.quantity) * numberValue(row.unit_price) * numberValue(row.exchange_rate)).toFixed(4) }
const totalQuantity = computed(() => String(products.value.reduce((sum, row) => sum + numberValue(row.quantity), 0)))
const productTotalAmount = computed(() => products.value.reduce(
  (sum, row) => sum + numberValue(row.quantity) * numberValue(row.unit_price),
  0,
))
const orderTotalAmount = computed(() => (
  productTotalAmount.value + numberValue(form.freight_amount) + numberValue(form.other_fee_amount)
).toFixed(4))
function colorNames(row: ProductDraft) {
  return Array.from(new Set((options.value?.colors || [])
    .filter((item) => item.color_card === row.color_card)
    .map((item) => item.color_name))).filter(Boolean)
}
function colorCodes(row: ProductDraft) {
  return (options.value?.colors || []).filter((item) => item.color_card === row.color_card && item.color_name === row.color_name)
}
function changeColorCard(row: ProductDraft) {
  row.color_name = ''
  row.product_color_id = ''
  row.color_code = ''
}
function changeColorName(row: ProductDraft) {
  row.product_color_id = ''
  row.color_code = ''
}
function selectColorCode(row: ProductDraft) {
  row.color_code = options.value?.colors.find((item) => item.id === row.product_color_id)?.color_code || ''
}
function changeCurrency(row: ProductDraft) {
  if (isCnyCurrency(row.currency_id)) row.exchange_rate = '1.000'
  else if (Number(row.exchange_rate) === 1) row.exchange_rate = ''
}
function normalizeIntegerQuantity(row: ProductDraft) {
  row.quantity = (row.quantity.match(/^\d+/)?.[0] || '').replace(/^0+(?=\d)/, '')
}
function formatExchangeRate(row: ProductDraft) {
  const value = Number(row.exchange_rate)
  if (Number.isFinite(value) && value > 0) row.exchange_rate = value.toFixed(8)
}
function rowImageCount(row: ProductDraft) { return row.existingImages.length + row.newImages.length }
function firstImageUrl(row: ProductDraft) {
  if (row.newImages[0]) return row.newImages[0].previewUrl
  if (row.existingImages[0] && taskId.value) return productionTaskBusinessFileUrl(taskId.value, row.existingImages[0].id)
  return ''
}

function ensureLineTaskDraft(rowKey: string, source?: Partial<ProductTaskDraft>) {
  if (!lineTaskDrafts[rowKey]) {
    lineTaskDrafts[rowKey] = {
      special_requirements: source?.special_requirements || '',
      packaging_method: source?.packaging_method || '',
      details: source?.details?.length ? source.details : templateDetails(),
    }
  }
  return lineTaskDrafts[rowKey]
}
function openProductDialog(targetKey = '') {
  if (isReadOnly.value) return
  if (products.value.find((item) => item.clientKey === targetKey)?.sourceLocked) {
    ElMessage.warning('销售订单来源产品已锁定，请回到销售订单交付批次调整。')
    return
  }
  productDialogTargetKey.value = targetKey
  dialogProductId.value = products.value.find((item) => item.clientKey === targetKey)?.product_id || ''
  productDialogVisible.value = true
}
function openProductCreateDialog() {
  if (!canCreateProduct.value) return
  productCreateDialogVisible.value = true
}
async function handleProductCreated(product: ProductInformation) {
  if (!options.value) return
  const fallback: ProductOption = {
    id: product.id,
    product_number: product.product_number,
    product_code: product.product_code,
    item_number: product.item_number,
    product_name: product.product_name,
    specification: product.specification,
    default_unit_id: product.unit,
  }
  let candidate = fallback
  try {
    const refreshed = await fetchProductionTaskOptions()
    options.value = refreshed
    candidate = refreshed.products.find((item) => item.id === product.id) || fallback
  } catch {
    options.value.products = [fallback, ...options.value.products.filter((item) => item.id !== fallback.id)]
  }
  await selectProductCandidate(candidate)
}
async function selectProductCandidate(product: ProductOption) {
  dialogProductId.value = product.id
  const targetRow = products.value.find((item) => item.clientKey === productDialogTargetKey.value)
  if (targetRow?.sourceLocked) {
    ElMessage.warning('销售订单来源产品已锁定，不能在生产任务中更换。')
    return
  }
  const oldProductId = targetRow?.product_id || ''
  if (products.value.some((item) => item.product_id === product.id && item.product_id !== oldProductId)) {
    ElMessage.warning('该产品已经在任务单中，请直接增加颜色明细。')
    return
  }
  if (oldProductId && oldProductId !== product.id) {
    try {
      await ElMessageBox.confirm(
        '更换产品后将清空这个产品的颜色明细、图片和生产任务单明细。是否继续？',
        '确认更换产品',
        { type: 'warning', confirmButtonText: '确认更换', cancelButtonText: '取消' },
      )
    } catch {
      dialogProductId.value = oldProductId
      return
    }
    const firstIndex = products.value.findIndex((row) => row.product_id === oldProductId)
    products.value.filter((row) => row.product_id === oldProductId).forEach((row) => {
      revokeRowPreviews(row)
      delete lineTaskDrafts[row.clientKey]
    })
    products.value = products.value.filter((row) => row.product_id !== oldProductId)
    const replacementRow = blankProduct(product)
    products.value.splice(Math.max(firstIndex, 0), 0, replacementRow)
    ensureLineTaskDraft(replacementRow.clientKey)
  } else if (targetRow && !oldProductId) {
    bindProduct(targetRow, product)
    ensureLineTaskDraft(targetRow.clientKey)
  } else if (!oldProductId) {
    const newRow = blankProduct(product)
    products.value.push(newRow)
    ensureLineTaskDraft(newRow.clientKey)
  }
  productDialogVisible.value = false
}
function addProductLine(productId: string) {
  if (isReadOnly.value) return
  if (products.value.some((item) => item.product_id === productId && item.sourceLocked)) {
    ElMessage.warning('销售订单来源产品不能在生产任务中新增颜色行。')
    return
  }
  const selected = options.value?.products.find((item) => item.id === productId)
  if (!selected) return
  const newRow = blankProduct(selected)
  products.value.push(newRow)
  ensureLineTaskDraft(newRow.clientKey)
}
function removeProductLine(row: ProductDraft) {
  const sameProductRows = row.product_id
    ? products.value.filter((item) => item.product_id === row.product_id)
    : [row]
  if (isReadOnly.value || row.sourceLocked || sameProductRows.length <= 1) return
  revokeRowPreviews(row)
  delete lineTaskDrafts[row.clientKey]
  products.value = products.value.filter((item) => item.clientKey !== row.clientKey)
}
function openTaskDetailDialog(row: ProductDraft) {
  if (!row.customer_product_name.trim() || !row.customer_specification.trim()) {
    ElMessage.warning('请先填写产品名称和规格。')
    return
  }
  ensureLineTaskDraft(row.clientKey)
  taskDetailRowKey.value = row.clientKey
  taskDetailDialogVisible.value = true
}
function addDetail() { if (!isReadOnly.value && taskDetailDraft.value) taskDetailDraft.value.details.push(blankDetail()) }
function removeDetail(index: number) {
  if (!isReadOnly.value && taskDetailDraft.value && taskDetailDraft.value.details.length > 1) taskDetailDraft.value.details.splice(index, 1)
}
function updateDetailDescription(detail: DetailDraft, value: string) {
  detail.description = value
  detail.is_selected = Boolean(value.trim())
}
function chooseDetailImage(row: DetailDraft, file: UploadFile) { if (!isReadOnly.value) row.imageFile = file.raw || null }

function openImageManager(row: ProductDraft) {
  imageManagerKey.value = row.clientKey
  imageDialogVisible.value = true
}
function chooseProductImages(uploadFile: UploadFile) {
  const row = imageManagerRow.value
  const file = uploadFile.raw
  if (!row || !file || isReadOnly.value) return
  if (!file.type.startsWith('image/')) { ElMessage.warning('只能上传 JPG、PNG、GIF 或 WebP 图片。'); return }
  if (file.size > 10 * 1024 * 1024) { ElMessage.warning('单张图片不能超过 10MB。'); return }
  if (rowImageCount(row) >= 20) { ElMessage.warning('每条颜色明细最多上传 20 张图片。'); return }
  const duplicated = row.newImages.some((item) => item.file.name === file.name && item.file.size === file.size && item.file.lastModified === file.lastModified)
  if (duplicated) { ElMessage.warning('这张图片已经添加。'); return }
  row.newImages.push({ key: key(), file, previewUrl: URL.createObjectURL(file) })
}
function removeExistingImage(row: ProductDraft, imageId: string) {
  if (!isReadOnly.value) row.existingImages = row.existingImages.filter((item) => item.id !== imageId)
}
function removePendingImage(row: ProductDraft, imageKey: string) {
  if (isReadOnly.value) return
  const target = row.newImages.find((item) => item.key === imageKey)
  if (target) URL.revokeObjectURL(target.previewUrl)
  row.newImages = row.newImages.filter((item) => item.key !== imageKey)
}
function previewExistingImage(image: ProductionTaskProductImage) {
  if (!taskId.value) return
  previewImageName.value = image.name
  previewImageUrl.value = productionTaskBusinessFileUrl(taskId.value, image.id)
  previewDialogVisible.value = true
}
function previewPendingImage(image: PendingProductImage) {
  previewImageName.value = image.file.name
  previewImageUrl.value = image.previewUrl
  previewDialogVisible.value = true
}
function revokeRowPreviews(row?: ProductDraft) {
  row?.newImages.forEach((item) => URL.revokeObjectURL(item.previewUrl))
}
function revokeAllProductPreviews() { products.value.forEach(revokeRowPreviews) }

function apiError(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务。'
  const data = error.response.data as { error?: { message?: string; field_errors?: unknown }; detail?: string }
  if (error.response.status === 412) return '数据已被其他人更新，请重新加载后再提交。'
  if (error.response.status === 428) return '缺少数据版本，请重新加载。'
  return data.error?.message || data.detail || '保存失败，请检查填写内容。'
}

function bomSyncMeta(error: unknown): BomSyncMeta | null {
  if (!(error instanceof AxiosError) || error.response?.status !== 409) return null
  const apiErrorData = error.response.data as {
    error?: { code?: string; meta?: Partial<BomSyncMeta> }
  }
  if (apiErrorData.error?.code !== 'BOM_SYNC_CONFIRMATION_REQUIRED') return null
  const meta = apiErrorData.error.meta
  if (!meta || !Array.isArray(meta.affected_lines) || typeof meta.confirmation_token !== 'string') return null
  return {
    affected_bom_count: Number(meta.affected_bom_count || meta.affected_lines.length),
    affected_lines: meta.affected_lines as BomSyncAffectedLine[],
    confirmation_token: meta.confirmation_token,
  }
}

async function updateWithBomConfirmation(
  taskPayload: ProductionTaskPatchInput,
  productImages: Record<string, File[]>,
  detailImages: Record<string, File | null>,
) {
  let requestPayload = taskPayload
  while (true) {
    try {
      return await updateProductionTask(taskId.value, requestPayload, productImages, detailImages, etag.value)
    } catch (error) {
      const meta = bomSyncMeta(error)
      if (!meta) throw error
      const lineSummary = meta.affected_lines
        .slice(0, 3)
        .map((item) => {
          const changes = item.change_types || []
          const productChange = changes.includes('PRODUCT')
            ? `产品：${item.old_product_name || item.product_name} → ${item.new_product_name || item.product_name}`
            : ''
          const colorChange = changes.includes('COLOR')
            ? `颜色：${item.old_color_name || '未填写'} → ${item.new_color_name || '未填写'}`
            : ''
          const quantityChange = changes.includes('QUANTITY')
            ? `数量：${item.old_quantity} → ${item.new_quantity}`
            : ''
          const detail = [productChange, colorChange, quantityChange].filter(Boolean).join('，')
          const productLabel = `${item.product_name}${item.color_name ? `（${item.color_name}）` : ''}`
          return detail
            ? `${productLabel}（${detail}）`
            : `${productLabel}：订单 ${item.new_quantity}，BOM ${item.bom_quantity}`
        })
        .join('；')
      const remaining = Math.max(0, meta.affected_lines.length - 3)
      const message = `${lineSummary}${remaining ? `；另有 ${remaining} 条` : ''}。同步后会更新 BOM 的产品与数量快照，按订单数量重算已有正式公式；原材料明细仍需人工复核。仅保存订单会保留原 BOM，并在 BOM 页面标记“订单信息已变更”。`
      let syncMode: NonNullable<ProductionTaskPatchInput['bom_sync_mode']>
      try {
        await ElMessageBox.confirm(message, `检测到 ${meta.affected_bom_count} 份关联 BOM`, {
          type: 'warning',
          confirmButtonText: '同步 BOM 并保存',
          cancelButtonText: '仅保存订单',
          distinguishCancelAndClose: true,
          closeOnClickModal: false,
        })
        syncMode = 'SYNC'
      } catch (action) {
        if (action !== 'cancel') return null
        syncMode = 'KEEP'
      }
      requestPayload = {
        ...taskPayload,
        bom_sync_mode: syncMode,
        bom_sync_token: meta.confirmation_token,
      }
    }
  }
}

function applyExisting(task: ProductionTask) {
  revokeAllProductPreviews()
  Object.keys(lineTaskDrafts).forEach((rowKey) => delete lineTaskDrafts[rowKey])
  existing.value = task
  contractNumber.value = task.contract_number
  Object.assign(form, {
    task_number_suffix: task.task_number.replace(/^HT/, ''),
    order_date: task.order_date, delivery_date: task.delivery_date, salesperson_id: task.salesperson.id,
    follower_ids: task.followers.map((item) => item.id), currency_id: task.currency_id || '',
    includes_tax: task.includes_tax ?? false, tax_rate: task.tax_rate ?? null, order_tolerance_percent: task.order_tolerance_percent || '0',
    is_repeat_order: task.is_repeat_order ?? false,
    preproduction_sample_required: task.preproduction_sample_required ?? false,
    delivery_method: task.delivery_method, special_requirements_html: task.special_requirements_html || '',
    freight_amount: task.freight_amount || '0', other_fee_amount: task.other_fee_amount || '0',
  })
  products.value = task.products.length ? task.products.map((item: ProductionTaskProduct) => ({
    clientKey: item.id, sourceLocked: Boolean(item.source_delivery_batch_line_id), product_id: item.product_id, product_code: item.product_code, item_number: item.item_number,
    product_name: item.product_name, specification: item.specification,
    customer_product_name: item.customer_product_name || item.product_name,
    customer_specification: item.customer_specification || item.specification,
     customer_color: item.customer_color ?? item.color_name ?? '', material: item.material || '',
    unit_label: `${item.unit_code} · ${item.unit_name}`, color_card: item.color_card || '', color_name: item.color_name || '',
    product_color_id: item.product_color_id || '', color_code: item.color_code, quantity: String(item.quantity),
    unit_id: item.unit_id, currency_id: form.currency_id, unit_price: item.unit_price,
    exchange_rate: Number(item.exchange_rate).toFixed(8),
    existingImages: item.images || [], newImages: [],
  })) : [blankProduct()]
  for (const item of task.products) {
    ensureLineTaskDraft(item.id, {
      special_requirements: item.special_requirements || '',
      packaging_method: item.packaging_method || '',
      details: item.details.map((detail, index) => ({
        client_key: 'id' in detail && typeof detail.id === 'string' ? detail.id : `existing-detail-${index}`,
        template_key: detail.template_key, detail_type: detail.detail_type, category_label: detail.category_label,
        is_selected: detail.is_selected, description: detail.description, imageFile: null,
        imageName: 'image_name' in detail && typeof detail.image_name === 'string' ? detail.image_name : null,
      })),
    })
  }
}

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    options.value = await fetchProductionTaskOptions()
    if (!isEditing.value) {
      products.value = [blankProduct()]
      const reservation = await reserveProductionTaskContractNumber(form.order_date)
      contractNumber.value = reservation.contract_number
      contractNumberToken.value = reservation.token
      return
    }
    const result = await fetchProductionTask(taskId.value)
    etag.value = result.etag
    applyExisting(result.data)
  } catch (error) {
    errorMessage.value = apiError(error)
  } finally {
    loading.value = false
  }
}

function validate() {
  if (!isEditing.value && !contractNumberToken.value) return '合同编号尚未生成，请刷新页面后重试。'
  contractNumber.value = contractNumber.value.trim().toUpperCase()
  if (!/^[A-Z0-9][A-Z0-9._-]{0,49}$/.test(contractNumber.value)) return '合同编号只能包含大写字母、数字、点、下划线和连字符。'
  if (!/^[0-9]+(?:-[0-9]+)*$/.test(form.task_number_suffix) || form.task_number_suffix.length > 48) return '请填写有效生产任务单号，例如 26199 或 26199-1。'
  if (!form.follower_ids.length) return '请选择跟单员。'
  if (!form.order_date || !form.delivery_date) return '请选择下单日期和交期日期。'
  if (form.delivery_date < form.order_date) return '交期日期不能早于下单日期。'
  if (!form.salesperson_id || !form.currency_id) return '请选择业务员和币种。'
  if (!form.delivery_method) return '请选择交货方式。'
  if (form.includes_tax && ![3, 5, 7].includes(Number(form.tax_rate))) return '含税时请选择税率。'
  const tolerance = Number(form.order_tolerance_percent)
  if (!Number.isFinite(tolerance) || tolerance < 0 || tolerance > 100) return '订单误差必须是 0 到 100 之间的百分比。'
  for (const [label, value] of [['运费', form.freight_amount], ['其他费用', form.other_fee_amount]]) {
    const amount = Number(value)
    if (!Number.isFinite(amount) || amount < 0) return `${label}必须是大于或等于 0 的金额。`
  }
  if (!products.value.length) return '请录入至少一条产品。'
  for (const [index, row] of products.value.entries()) {
    const lineNumber = index + 1
    if (!row.customer_product_name.trim() || !row.customer_specification.trim() || !row.unit_id) return `请补齐第 ${lineNumber} 条明细的名称、规格和单位。`
    if (row.product_id) {
      if (!row.color_card || !row.color_name || !row.product_color_id || !row.color_code) return `请按顺序选择第 ${lineNumber} 条明细的色卡、颜色和色号。`
    } else if (!row.customer_color.trim()) {
      return `请填写第 ${lineNumber} 条明细的客户颜色，或选择产品主档颜色。`
    }
    if (!/^[1-9]\d*$/.test(row.quantity)) return `第 ${lineNumber} 条明细的订单数量必须是大于 0 的整数。`
    if (row.currency_id !== form.currency_id) return `第 ${lineNumber} 条明细的币种与基础信息不一致。`
    if (row.unit_price === '' || !(Number(row.unit_price) >= 0)) return `第 ${lineNumber} 条明细的售价不能小于 0。`
    if (!/^\d+(\.\d{1,8})?$/.test(row.exchange_rate) || !(Number(row.exchange_rate) > 0)) return `第 ${lineNumber} 条明细的汇率必须大于 0，且最多保留 8 位小数。`
    if (isCnyCurrency(row.currency_id) && Number(row.exchange_rate) !== 1) return `第 ${lineNumber} 条明细使用 CNY 时汇率必须为 1。`
  }
  for (const [index, row] of products.value.entries()) {
    const draft = lineTaskDrafts[row.clientKey]
    const colorLabel = [row.color_name, row.color_code].filter(Boolean).join(' / ') || `第 ${index + 1} 条颜色明细`
    if (!draft || !draft.details.length || draft.details.some((item) => !item.detail_type.trim())) return `请补齐“${row.product_name} · ${colorLabel}”的生产任务单明细类型。`
  }
  return ''
}

function productPayload(): ProductionTaskProductInput[] {
  return products.value.map((row) => {
    const draft = lineTaskDrafts[row.clientKey]
    return {
      client_key: row.clientKey, product_id: row.product_id || null, product_color_id: row.product_color_id || null,
      color_code: row.color_code, customer_product_name: row.customer_product_name.trim(),
      customer_specification: row.customer_specification.trim(), customer_color: row.customer_color.trim(), material: row.material.trim(),
      quantity: row.quantity, unit_id: row.unit_id, currency_id: row.currency_id,
      unit_price: row.unit_price, exchange_rate: Number(row.exchange_rate).toFixed(8),
      special_requirements: draft?.special_requirements.trim() || '',
      packaging_method: draft?.packaging_method.trim() || '',
      retained_image_ids: row.existingImages.map((item) => item.id),
      details: (draft?.details || []).map(({ imageFile: _file, imageName: _name, ...detail }) => detail),
    }
  })
}

function originalProductPayload(task: ProductionTask): ProductionTaskProductInput[] {
  return task.products.map((row) => ({
    client_key: row.id,
    product_id: row.product_id,
    product_color_id: row.product_color_id || null,
    color_code: row.color_code,
    customer_product_name: row.customer_product_name || row.product_name,
    customer_specification: row.customer_specification || row.specification,
    customer_color: row.customer_color ?? row.color_name,
    material: row.material || '',
    quantity: String(row.quantity),
    unit_id: row.unit_id,
    currency_id: row.currency_id,
    unit_price: row.unit_price,
    exchange_rate: Number(row.exchange_rate).toFixed(8),
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
  }))
}

function payload(): ProductionTaskInput {
  const { task_number_suffix, ...fields } = form
  return {
    ...fields,
    task_number: `HT${task_number_suffix}`,
    tax_rate: form.includes_tax ? form.tax_rate : null,
    ...(!isEditing.value ? { contract_number_token: contractNumberToken.value } : {}),
    contract_number: contractNumber.value,
    order_source: form.is_repeat_order ? 'REPEAT' : 'NEW',
    delivery_method: form.delivery_method as ProductionDeliveryMethod,
    order_number: `HT${form.task_number_suffix}`,
    freight_amount: form.freight_amount || '0',
    other_fee_amount: form.other_fee_amount || '0',
    products: productPayload(),
    delivery_batches: isEditing.value
      ? (existing.value?.delivery_batches || []).map((batch) => ({
        quantity: String(batch.quantity),
        delivery_date: batch.delivery_date,
        note: batch.note || '',
      }))
      : [],
  }
}

function preciseUpdatePayload(): ProductionTaskPatchInput {
  const task = existing.value
  if (!task) return {}
  const patch: ProductionTaskPatchInput = {}
  const assignIfChanged = <K extends keyof ProductionTaskPatchInput>(
    keyName: K,
    currentValue: ProductionTaskPatchInput[K],
    originalValue: unknown,
  ) => {
    if (JSON.stringify(currentValue) !== JSON.stringify(originalValue)) patch[keyName] = currentValue
  }

  assignIfChanged('delivery_date', form.delivery_date, task.delivery_date)
  assignIfChanged('follower_ids', [...form.follower_ids].sort(), task.followers.map((item) => item.id).sort())
  assignIfChanged('special_requirements_html', form.special_requirements_html, task.special_requirements_html || '')

  const productsPayload = productPayload()
  const hasPendingFiles = products.value.some((row) => row.newImages.length > 0)
    || Object.values(lineTaskDrafts).some((draft) => draft.details.some((detail) => Boolean(detail.imageFile)))
  if (hasPendingFiles || JSON.stringify(productsPayload) !== JSON.stringify(originalProductPayload(task))) {
    patch.products = productsPayload
  }
  return patch
}
function imageMaps() {
  return {
    productImages: Object.fromEntries(products.value.map((row) => [row.clientKey, row.newImages.map((item) => item.file)])),
    detailImages: Object.fromEntries(Object.values(lineTaskDrafts).flatMap((draft) => draft.details).map((detail) => [detail.client_key, detail.imageFile])),
  }
}

async function save(shouldSubmit = false) {
  if (isReadOnly.value) return
  const message = validate()
  if (message) { ElMessage.warning(message); return }
  saving.value = true
  try {
    const images = imageMaps()
    const taskPayload = isEditing.value ? preciseUpdatePayload() : payload()
    if (isEditing.value && Object.keys(taskPayload).length === 0) {
      ElMessage.info('没有检测到需要保存的修改。')
      return
    }
    let result = isEditing.value
      ? await updateWithBomConfirmation(taskPayload, images.productImages, images.detailImages)
      : await createProductionTask(taskPayload as ProductionTaskInput, images.productImages, images.detailImages)
    if (!result) return
    if (shouldSubmit) result = await submitProductionTask(result.data.id, result.etag)
    ElMessage.success(shouldSubmit ? '生产任务单已提交校验。' : canSubmitTask.value ? '生产任务单草稿已保存。' : '生产任务单已保存。')
    await router.replace({ name: 'production-task-detail', params: { taskId: result.data.id } })
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saving.value = false
  }
}

async function submitCurrentTask() {
  if (!existing.value || !canSubmitFromDetail.value || workflowLoading.value) return
  try {
    await ElMessageBox.confirm(
      '提交后状态将变为“待 PMC 确认”。PMC 需要重新核对本次完善后的内容。',
      '提交 PMC',
      { type: 'warning', confirmButtonText: '确认提交', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  workflowLoading.value = true
  try {
    const result = await submitProductionTask(existing.value.id, etag.value)
    etag.value = result.etag
    applyExisting(result.data)
    ElMessage.success('生产任务单已提交，等待 PMC 确认。')
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    workflowLoading.value = false
  }
}

async function confirmCurrentTask() {
  if (!existing.value || !canConfirmTask.value) return
  await router.push({ name: 'production-task-detail', params: { taskId: existing.value.id }, query: { pmc: 'confirm' } })
}

function back() { void router.push({ name: 'production-tasks' }) }

watch(() => form.currency_id, (currencyId) => {
  products.value.forEach((row) => {
    row.currency_id = currencyId
    changeCurrency(row)
  })
})
onMounted(() => { void load() })
onBeforeUnmount(revokeAllProductPreviews)
</script>

<template>
  <section v-loading="loading" class="production-form-page" aria-label="生产任务单表单">
    <template v-if="!errorMessage">
      <header class="form-heading">
        <div><h1>{{ isReadOnly ? '生产任务单详情' : isEditing ? '编辑生产任务单' : '新增生产任务单' }}</h1><ElTag :type="existing?.status === 'PENDING_VALIDATION' ? 'warning' : 'info'">{{ existing?.status_display || '未保存' }}</ElTag></div>
        <div class="form-heading__actions">
          <ElButton @click="back">取消</ElButton>
          <template v-if="!isReadOnly">
            <ElButton :loading="saving" @click="save(false)">{{ canSubmitTask ? '保存草稿' : '保存' }}</ElButton>
            <ElButton v-if="canSubmitTask" type="primary" :loading="saving" @click="save(true)">提交</ElButton>
          </template>
          <template v-else>
            <ElButton v-if="canEditTask && !isTerminalTask" @click="router.push({ name: 'production-task-edit', params: { taskId } })">编辑</ElButton>
            <ElButton v-if="canSubmitFromDetail" type="primary" :loading="workflowLoading" @click="submitCurrentTask">提交 PMC</ElButton>
            <ElButton v-if="canConfirmFromDetail" type="primary" :loading="workflowLoading" @click="confirmCurrentTask">PMC 确认</ElButton>
          </template>
        </div>
      </header>

      <ElAlert
        v-if="workflowNotice"
        class="workflow-notice"
        type="warning"
        show-icon
        :closable="false"
        :title="workflowNotice.title"
        :description="workflowNotice.description"
      />
      <ElAlert
        v-if="sourceHeaderLocked && !isReadOnly"
        class="workflow-notice"
        type="info"
        show-icon
        :closable="false"
        title="销售订单来源字段已锁定"
        description="来源、销售产品、颜色、数量及成交价格必须回到销售订单交付批次调整；本页可维护交期、跟单员和生产要求。"
      />

      <nav v-if="!isEditing" class="creation-modes" aria-label="创建方式"><ElButton @click="router.push({ name: 'production-task-create' })">从销售订单创建</ElButton><ElButton type="primary" disabled>手动创建</ElButton></nav>
      <section class="basic-card">
        <div class="section-bar"><h2>基础信息</h2><span aria-hidden="true"></span></div>
        <ElForm label-position="top">
          <div class="field-grid">
            <ElFormItem label="合同编号" required><ElInput v-model="contractNumber" maxlength="50" placeholder="正在生成" :disabled="isReadOnly || sourceHeaderLocked" @blur="contractNumber = contractNumber.trim().toUpperCase()" /></ElFormItem>
            <ElFormItem label="生产任务单号" required><ElInput v-model="form.task_number_suffix" :disabled="isEditing" maxlength="48" placeholder="例如 26199 或 26199-1"><template #prepend>HT</template></ElInput><small>最近 5 笔：{{ options?.recent_task_numbers?.join('、') || '暂无历史编号' }}</small></ElFormItem>
            <ElFormItem label="下单日期" required><ElDatePicker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" placeholder="请选择下单日期" :disabled="isReadOnly || sourceHeaderLocked" /></ElFormItem>
            <ElFormItem label="交期日期" required><ElDatePicker v-model="form.delivery_date" type="date" value-format="YYYY-MM-DD" placeholder="请选择交期日期" :disabled="isReadOnly" /></ElFormItem>
            <ElFormItem label="业务员" required><ElSelect v-model="form.salesperson_id" filterable :disabled="isReadOnly || sourceHeaderLocked" placeholder="请选择业务员"><ElOption v-for="item in options?.employees || []" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem>
            <ElFormItem label="跟单员" required><ElSelect v-model="form.follower_ids" multiple filterable collapse-tags :disabled="isReadOnly" placeholder="请选择跟单员"><ElOption v-for="item in options?.employees || []" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem>
            <ElFormItem label="币种" required><ElSelect v-model="form.currency_id" filterable :disabled="isReadOnly || sourceHeaderLocked" placeholder="请选择币种"><ElOption v-for="item in options?.currencies || []" :key="item.id" :label="`${item.code} · ${item.name}`" :value="item.id" /></ElSelect></ElFormItem>
            <ElFormItem label="是否含税" required><ElSelect v-model="form.includes_tax" :disabled="isReadOnly || sourceHeaderLocked"><ElOption label="含税" :value="true" /><ElOption label="不含税" :value="false" /></ElSelect></ElFormItem>
            <ElFormItem v-if="form.includes_tax" label="税率" required><ElSelect v-model="form.tax_rate" :disabled="isReadOnly || sourceHeaderLocked" placeholder="请选择税率"><ElOption v-for="rate in [3, 5, 7]" :key="rate" :label="`${rate}%`" :value="rate" /></ElSelect></ElFormItem>
            <ElFormItem label="订单误差" required><ElInput v-model="form.order_tolerance_percent" :disabled="isReadOnly || sourceHeaderLocked" placeholder="例如 3"><template #append>%</template></ElInput></ElFormItem>
            <ElFormItem label="是否返单" required><ElSelect v-model="form.is_repeat_order" :disabled="isReadOnly || sourceHeaderLocked"><ElOption label="是" :value="true" /><ElOption label="否" :value="false" /></ElSelect></ElFormItem>
            <ElFormItem label="产前确认样" required><ElSelect v-model="form.preproduction_sample_required" :disabled="isReadOnly || sourceHeaderLocked"><ElOption label="是" :value="true" /><ElOption label="否" :value="false" /></ElSelect></ElFormItem>
            <ElFormItem label="交货方式" required><ElSelect v-model="form.delivery_method" :disabled="isReadOnly || sourceHeaderLocked" placeholder="请选择"><ElOption v-for="item in options?.delivery_methods || []" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
          </div>
          <ElFormItem label="订单特殊要求" class="rich-field">
            <div v-if="isReadOnly" class="rich-readonly" v-html="form.special_requirements_html || '<p>未填写</p>'" />
            <InquiryWangEditor v-else v-model="form.special_requirements_html" upload-url="" upload-etag="" :show-upload-notice="false" placeholder="填写整张订单的特殊要求、质量要求和注意事项" />
          </ElFormItem>
        </ElForm>
      </section>

      <section class="detail-card">
        <div class="product-section-heading"><strong>产品信息</strong></div>
        <article v-for="(group, groupIndex) in productGroups" :key="group.key" class="product-group">
            <div class="fixed-product-card" :class="{ 'fixed-product-card--manual': !group.productId }" :aria-label="`产品 ${groupIndex + 1}`">
              <div class="fixed-product-image">
                <img v-if="firstImageUrl(group.rows[0])" :src="firstImageUrl(group.rows[0])" alt="产品图片" />
                <template v-else><ElIcon><Picture /></ElIcon><span>产品主图</span></template>
              </div>
              <div class="fixed-product-content">
                <strong class="fixed-product-name">{{ group.rows[0].customer_product_name || group.rows[0].product_name || '请选择产品' }}</strong>
                <div v-if="!group.productId" class="manual-product-inputs">
                  <ElInput v-model="group.rows[0].customer_product_name" :disabled="isReadOnly || group.rows[0].sourceLocked" placeholder="产品名称" />
                  <ElInput v-model="group.rows[0].customer_specification" :disabled="isReadOnly || group.rows[0].sourceLocked" placeholder="产品规格" />
                </div>
                <div class="fixed-product-meta">
                  <div><span>产品编码</span><strong>{{ group.rows[0].product_code || '—' }}</strong></div>
                  <div><span>货号</span><strong>{{ group.rows[0].item_number || '—' }}</strong></div>
                  <div><span>规格</span><strong>{{ group.rows[0].customer_specification || group.rows[0].specification || '—' }}</strong></div>
                  <div><span>单位</span><strong>{{ group.rows[0].unit_label || '—' }}</strong></div>
                </div>
              </div>
              <div v-if="!isReadOnly" class="fixed-product-actions">
                <ElTag v-if="group.rows.some(row => row.sourceLocked)" type="info">销售来源已锁定</ElTag>
                <template v-if="group.productId">
                  <ElButton :icon="Plus" :disabled="group.rows.some(row => row.sourceLocked)" @click="addProductLine(group.productId)">添加</ElButton>
                  <ElButton :disabled="group.rows[0].sourceLocked" @click="openProductDialog(group.rows[0].clientKey)">选择产品</ElButton>
                </template>
                <ElButton v-else type="primary" @click="openProductDialog(group.rows[0].clientKey)">选择产品</ElButton>
              </div>
            </div>

            <div class="product-line-table">
              <table>
                <colgroup><col class="col-images"><col class="col-card"><col class="col-color"><col class="col-code"><col class="col-quantity"><col class="col-money"><col class="col-total"><col class="col-rate"><col class="col-local-price"><col class="col-local-total"><col class="col-detail"><col class="col-action"></colgroup>
                <thead><tr><th>明细图片</th><th><i>*</i> 色卡</th><th><i>*</i> 颜色</th><th><i>*</i> 色号</th><th><i>*</i> 订单数量</th><th><i>*</i> 售价</th><th>合计金额</th><th><i>*</i> 汇率</th><th>本币售价</th><th>本币合计金额</th><th>生产任务单明细</th><th>操作</th></tr></thead>
                <tbody><tr v-for="row in group.rows" :key="row.clientKey">
                  <td><ElButton size="small" :icon="Picture" aria-label="管理明细图片" @click="openImageManager(row)">图片</ElButton></td>
                  <td v-if="row.product_id"><ElSelect v-model="row.color_card" :disabled="isReadOnly || row.sourceLocked" placeholder="请选择" @change="changeColorCard(row)"><ElOption v-for="item in colorCards" :key="item" :label="item" :value="item" /></ElSelect></td>
                  <td v-else><ElInput v-model="row.customer_color" :disabled="isReadOnly || row.sourceLocked" placeholder="产品颜色" /></td>
                  <td v-if="row.product_id"><ElSelect v-model="row.color_name" :disabled="isReadOnly || row.sourceLocked || !row.color_card" placeholder="请选择" @change="changeColorName(row)"><ElOption v-for="item in colorNames(row)" :key="item" :label="item" :value="item" /></ElSelect></td>
                  <td v-else class="manual-color-note">手工颜色</td>
                  <td v-if="row.product_id"><ElSelect v-model="row.product_color_id" :disabled="isReadOnly || row.sourceLocked || !row.color_name" placeholder="请选择色号" @change="selectColorCode(row)"><ElOption v-for="item in colorCodes(row)" :key="item.id" :label="item.color_code" :value="item.id" /></ElSelect></td>
                  <td v-else class="manual-color-note">未关联主档</td>
                  <td><ElInput v-model="row.quantity" :disabled="isReadOnly || row.sourceLocked" inputmode="numeric" placeholder="整数" @input="normalizeIntegerQuantity(row)" /></td>
                  <td><ElInput v-model="row.unit_price" :disabled="isReadOnly || row.sourceLocked" placeholder="0.0000" /></td>
                  <td><ElInput :model-value="total(row)" disabled /></td>
                  <td><ElInput v-model="row.exchange_rate" :disabled="isReadOnly || row.sourceLocked || isCnyCurrency(row.currency_id)" placeholder="0.000" @blur="formatExchangeRate(row)" /></td>
                  <td><ElInput :model-value="localUnitPrice(row)" disabled /></td>
                  <td><ElInput :model-value="localTotal(row)" disabled /></td>
                  <td class="detail-trigger-cell"><ElButton class="task-detail-trigger" size="small" :disabled="!row.customer_product_name || !row.customer_specification" @click="openTaskDetailDialog(row)">明细</ElButton></td>
                  <td><ElButton link type="danger" :disabled="group.rows.length <= 1 || isReadOnly || row.sourceLocked" @click="removeProductLine(row)">删除</ElButton></td>
                </tr></tbody>
              </table>
            </div>
        </article>
            <section class="product-summary-card" aria-label="费用与汇总">
              <strong>费用与汇总</strong>
              <div class="product-summary-grid">
                <label><span>运费</span><ElInput v-model="form.freight_amount" :disabled="isReadOnly || sourceHeaderLocked" maxlength="23" placeholder="0.0000" /></label>
                <label><span>其他费用</span><ElInput v-model="form.other_fee_amount" :disabled="isReadOnly || sourceHeaderLocked" maxlength="23" placeholder="0.0000" /></label>
                <label><span>合计数量</span><ElInput :model-value="totalQuantity" disabled /></label>
                <label><span>合计金额</span><ElInput :model-value="orderTotalAmount" disabled /></label>
              </div>
            </section>
      </section>

      <ElDialog v-model="taskDetailDialogVisible" class="product-task-detail-dialog" :title="taskDetailDialogTitle" width="1120px" destroy-on-close>
        <div v-if="taskDetailDraft" class="product-task-dialog">
          <article class="task-detail-block">
            <header><strong>明细表</strong><ElButton v-if="!isReadOnly" :icon="Plus" @click="addDetail">增加一条</ElButton></header>
            <div class="detail-table-wrap"><table><thead><tr><th>序号</th><th>类型 *</th><th>类别项</th><th>是否</th><th>描述</th><th>图片</th><th v-if="!isReadOnly">操作</th></tr></thead><tbody><tr v-for="(detail, detailIndex) in taskDetailDraft.details" :key="detail.client_key"><td>{{ detailIndex + 1 }}</td><td><ElInput v-model="detail.detail_type" :disabled="isReadOnly" /></td><td><ElInput v-model="detail.category_label" :disabled="isReadOnly" /></td><td><ElSelect v-model="detail.is_selected" :disabled="isReadOnly"><ElOption label="是" :value="true" /><ElOption label="否" :value="false" /></ElSelect></td><td><ElInput :model-value="detail.description" :disabled="isReadOnly" @update:model-value="(value: string) => updateDetailDescription(detail, value)" /></td><td><ElUpload :auto-upload="false" :show-file-list="false" :limit="1" accept=".jpg,.jpeg,.png,.gif,.webp" :disabled="isReadOnly" :on-change="(file: UploadFile) => chooseDetailImage(detail, file)"><ElButton size="small" :disabled="isReadOnly">{{ detail.imageFile?.name || detail.imageName || '选择图片' }}</ElButton></ElUpload></td><td v-if="!isReadOnly"><ElButton link type="danger" @click="removeDetail(detailIndex)">删除</ElButton></td></tr></tbody></table></div>
          </article>
          <div class="product-task-requirements product-task-requirements--bottom">
            <label><span>特殊要求</span><ElInput v-model="taskDetailDraft.special_requirements" type="textarea" :rows="2" maxlength="3000" show-word-limit :disabled="isReadOnly" placeholder="填写该颜色的特殊要求、质量要求和注意事项（选填）" /></label>
            <label><span>包装方式</span><ElInput v-model="taskDetailDraft.packaging_method" type="textarea" :rows="2" maxlength="3000" show-word-limit :disabled="isReadOnly" placeholder="填写该颜色的包装方式、包装材料和装箱要求" /></label>
          </div>
        </div>
        <template #footer><ElButton type="primary" @click="taskDetailDialogVisible = false">完成</ElButton></template>
      </ElDialog>

      <ProductPickerDialog
        v-model="productDialogVisible"
        :products="options?.products || []"
        :units="options?.units || []"
        :selected-id="dialogProductId"
        :can-create="canCreateProduct"
        @select="selectProductCandidate"
        @create="openProductCreateDialog"
      />
      <ProductCreateDialog v-model="productCreateDialogVisible" @created="handleProductCreated" />

      <ElDialog v-model="imageDialogVisible" title="明细图片管理" width="960px" destroy-on-close>
        <div v-if="imageManagerRow" class="image-manager">
          <div class="image-manager__summary"><div><strong>{{ imageManagerRow.color_name || '未选择颜色' }}</strong><span>{{ imageManagerRow.color_code || '未选择色号' }}</span></div><ElTag type="info">{{ rowImageCount(imageManagerRow) }} / 20 张</ElTag></div>
          <ElUpload v-if="!isReadOnly" class="image-upload" drag multiple :auto-upload="false" :show-file-list="false" accept=".jpg,.jpeg,.png,.gif,.webp" :on-change="chooseProductImages"><ElIcon class="image-upload__icon"><UploadFilled /></ElIcon><div>点击或拖拽上传图片</div><small>支持 JPG、PNG、GIF、WebP，单张不超过 10MB</small></ElUpload>
          <div v-if="imageManagerRow.existingImages.length || imageManagerRow.newImages.length" class="image-list">
            <article v-for="image in imageManagerRow.existingImages" :key="image.id" class="image-item"><img :src="productionTaskBusinessFileUrl(taskId, image.id)" :alt="image.name" /><div><strong :title="image.name">{{ image.name }}</strong><span>已保存 · {{ (image.size_bytes / 1024 / 1024).toFixed(2) }}MB</span></div><div class="image-item__actions"><ElButton circle :icon="View" aria-label="查看图片" @click="previewExistingImage(image)" /><ElButton v-if="!isReadOnly" circle type="danger" plain :icon="Delete" aria-label="删除图片" @click="removeExistingImage(imageManagerRow, image.id)" /></div></article>
            <article v-for="image in imageManagerRow.newImages" :key="image.key" class="image-item"><img :src="image.previewUrl" :alt="image.file.name" /><div><strong :title="image.file.name">{{ image.file.name }}</strong><span>待上传 · {{ (image.file.size / 1024 / 1024).toFixed(2) }}MB</span></div><div class="image-item__actions"><ElButton circle :icon="View" aria-label="查看图片" @click="previewPendingImage(image)" /><ElButton v-if="!isReadOnly" circle type="danger" plain :icon="Delete" aria-label="删除图片" @click="removePendingImage(imageManagerRow, image.key)" /></div></article>
          </div>
          <ElEmpty v-else :image-size="72" description="暂无明细图片" />
        </div>
        <template #footer><ElButton type="primary" @click="imageDialogVisible = false">完成</ElButton></template>
      </ElDialog>

      <ElDialog v-model="previewDialogVisible" :title="previewImageName || '查看图片'" width="920px" append-to-body><div class="image-preview"><img :src="previewImageUrl" :alt="previewImageName" /></div></ElDialog>
    </template>
    <ElResult v-else icon="error" title="生产任务单加载失败" :sub-title="errorMessage"><template #extra><ElButton type="primary" @click="load">重新加载</ElButton><ElButton @click="back">返回列表</ElButton></template></ElResult>
  </section>
</template>

<style scoped lang="scss">
.creation-modes { display: flex; gap: 12px; margin-bottom: 16px; }
.production-form-page {
  min-width: 1180px;
  min-height: calc(100vh - 56px);
  padding: 24px 32px 86px;
  color: var(--erp-color-text-primary);
  background: var(--erp-page-background);
  --el-color-primary: var(--erp-color-brand);
}
.form-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.form-heading > div:first-child { display: flex; align-items: center; gap: 10px; }
.form-heading h1 { margin: 0; font-size: 24px; }
.form-heading__actions { display: flex; gap: 8px; }
.workflow-notice { margin-bottom: 16px; }
.basic-card,
.detail-card { padding: 20px; border: 1px solid var(--erp-color-border); border-radius: 10px; background: var(--erp-color-surface); }
.detail-card { margin-top: 16px; }
.section-bar { display: flex; height: 28px; align-items: flex-end; margin-bottom: 14px; }
.section-bar h2 { width: 132px; height: 26px; margin: 0; padding: 0 14px; color: var(--erp-color-text-inverse); background: var(--erp-color-brand); font-size: 14px; font-weight: 600; line-height: 26px; }
.section-bar span { flex: 1; height: 1px; background: var(--erp-color-brand); }
.field-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); column-gap: 16px; row-gap: 8px; }
.field-grid :deep(.el-form-item) { margin: 0; }
.field-grid :deep(.el-form-item__label) { height: 20px; padding: 0; line-height: 20px; }
.field-grid :deep(.el-form-item__content),
.field-grid :deep(.el-select),
.field-grid :deep(.el-date-editor) { width: 100%; }
.rich-field { display: block; margin: 12px 0 0; }
.rich-field :deep(.el-form-item__label) { display: block; height: 20px; padding: 0; float: none; line-height: 20px; text-align: left; }
.rich-field :deep(.el-form-item__content) { display: block; width: 100%; line-height: normal; }
.rich-readonly { min-height: 86px; padding: 12px 14px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-subtle); }
.rich-readonly :deep(p) { margin: 0 0 6px; }
.product-section-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; padding-bottom: 10px; border-bottom: 1px solid var(--erp-color-border-subtle); }
.product-section-heading > strong { font-size: 15px; }
.product-group + .product-group { margin-top: 16px; padding-top: 16px; border-top: 1px dashed var(--erp-color-border-subtle); }
.fixed-product-card { display: grid; grid-template-columns: var(--product-image-column-width) minmax(0, 1fr) auto; height: 64px; overflow: hidden; margin-bottom: 12px; border: 1px solid var(--erp-color-border); border-radius: 5px; background: var(--erp-color-subtle); }
.fixed-product-card--manual { height: auto; min-height: 96px; }
.fixed-product-image { display: flex; align-items: center; justify-content: center; gap: 6px; overflow: hidden; border-right: 1px solid var(--erp-color-border); color: var(--erp-color-text-muted); background: var(--erp-color-subtle); font-size: 12px; }
.fixed-product-image img { width: 100%; height: 64px; object-fit: contain; background: var(--erp-color-readonly); }
.fixed-product-image .el-icon { font-size: 18px; }
.fixed-product-content { min-width: 0; padding: 7px 12px; }
.fixed-product-name { display: block; overflow: hidden; margin-bottom: 5px; color: var(--erp-color-text-primary); font-size: 14px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.manual-product-inputs { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr); gap: 6px; margin-bottom: 6px; }
.manual-color-note { color: var(--erp-color-text-muted); font-size: 12px; text-align: center !important; }
.fixed-product-meta { display: flex; min-width: 0; align-items: center; overflow: hidden; }
.fixed-product-meta div { display: flex; min-width: 0; align-items: center; gap: 4px; padding: 0 12px; border-left: 1px solid var(--erp-color-border); }
.fixed-product-meta div:first-child { padding-left: 0; border-left: 0; }
.fixed-product-meta span,
.fixed-product-meta strong { display: inline-block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fixed-product-meta span { flex: none; color: var(--erp-color-text-muted); font-size: 11px; }
.fixed-product-meta strong { max-width: 220px; color: var(--erp-color-text-regular); font-size: 12px; font-weight: 500; }
.fixed-product-actions { display: flex; align-items: center; gap: 6px; padding: 0 10px; }
.fixed-product-actions :deep(.el-button + .el-button) { margin-left: 0; }
.detail-card { --product-image-column-width: 12%; }
.product-line-table { overflow-x: auto; border: 1px solid var(--erp-table-grid); border-radius: 8px; }
.product-line-table table { width: 100%; min-width: 1305px; border-collapse: collapse; table-layout: fixed; }
.product-line-table th,
.product-line-table td { height: 44px; padding: 6px; border-right: 1px solid var(--erp-table-grid); border-bottom: 1px solid var(--erp-table-grid); text-align: left; }
.product-line-table th:last-child,
.product-line-table td:last-child { border-right: 0; }
.product-line-table tbody tr:last-child td { border-bottom: 0; }
.product-line-table th { height: 36px; padding: 0 8px; color: var(--erp-table-header-text); background: var(--erp-table-header-fill); font-size: 12px; font-weight: 600; }
.product-line-table th i { color: var(--erp-table-header-text); font-style: normal; }
.product-line-table :deep(.el-input),
.product-line-table :deep(.el-select),
.product-line-table :deep(.el-button:not(.is-link)) { width: 100%; }
.product-line-table th:first-child,
.product-line-table td:first-child { text-align: center; }
.product-line-table .col-images { width: var(--product-image-column-width); }
.product-line-table .col-card { width: 100px; }
.product-line-table .col-color { width: 100px; }
.product-line-table .col-code { width: 110px; }
.product-line-table .col-detail { width: 120px; }
.product-line-table .col-quantity { width: 100px; }
.product-line-table .col-money { width: 100px; }
.product-line-table .col-total { width: 110px; }
.product-line-table .col-rate { width: 105px; }
.product-line-table .col-local-price { width: 105px; }
.product-line-table .col-local-total { width: 120px; }
.product-line-table .col-action { width: 65px; }
.product-line-table .detail-trigger-cell { text-align: center; }
.product-line-table :deep(.task-detail-trigger) { width: auto; height: 26px; padding: 2px 10px; font-size: 12px; }
.product-summary-card { margin-top: 12px; padding: 14px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-subtle); }
.product-summary-card > strong { display: block; margin-bottom: 12px; color: var(--erp-color-text-primary); font-size: 14px; }
.product-summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.product-summary-grid label { min-width: 0; }
.product-summary-grid label > span { display: block; margin-bottom: 6px; color: var(--erp-color-text-regular); font-size: 12px; }
.task-detail-block { overflow: hidden; padding: 10px; border: 1px solid var(--erp-color-border); border-radius: 7px; background: var(--erp-color-surface); }
.task-detail-block > header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.product-task-requirements { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.product-task-requirements--bottom { margin-top: 12px; }
.product-task-requirements label > span { display: block; margin-bottom: 6px; font-size: 13px; font-weight: 600; }
.product-task-requirements label > span i { color: var(--erp-color-danger); font-style: normal; }
:global(.product-task-detail-dialog .el-dialog__header) { padding: 14px 16px 10px; }
:global(.product-task-detail-dialog .el-dialog__title) { font-size: 16px; }
:global(.product-task-detail-dialog .el-dialog__body) { overflow-y: auto; padding: 8px 16px 12px; font-size: 12px; }
:global(.product-task-detail-dialog .el-dialog__footer) { padding: 8px 16px 12px; }
.product-dialog-toolbar { width: 420px; margin-bottom: 14px; }
.detail-table-wrap { overflow-x: auto; }
.detail-table-wrap table { width: 100%; min-width: 900px; border-collapse: collapse; table-layout: fixed; }
.detail-table-wrap th,
.detail-table-wrap td { padding: 2px 5px; border: 1px solid var(--erp-table-grid); text-align: left; }
.detail-table-wrap th { height: 29px; padding: 0 5px; color: var(--erp-table-header-text); background: var(--erp-table-header-fill); font-size: 11px; }
.detail-table-wrap td { height: 31px; font-size: 11px; }
.detail-table-wrap :deep(.el-input__wrapper),
.detail-table-wrap :deep(.el-select__wrapper) { min-height: 26px; height: 26px; padding: 0 7px; font-size: 11px; }
.detail-table-wrap :deep(.el-button--small) { height: 26px; padding: 3px 8px; font-size: 11px; }
.detail-table-wrap th:first-child,
.detail-table-wrap td:first-child { width: 44px; text-align: center; }
.detail-table-wrap th:nth-child(2) { width: 120px; }
.detail-table-wrap th:nth-child(3) { width: 120px; }
.detail-table-wrap th:nth-child(4) { width: 80px; }
.detail-table-wrap th:nth-child(5) { width: 330px; }
.detail-table-wrap th:nth-child(6) { width: 150px; }
.detail-table-wrap th:last-child { width: 58px; }
.detail-table-wrap :deep(.el-upload),
.detail-table-wrap :deep(.el-upload .el-button) { width: 100%; }
.image-manager__summary { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; padding: 10px 12px; border-radius: 6px; background: var(--erp-color-subtle); }
.image-manager__summary > div { display: flex; align-items: center; gap: 12px; }
.image-manager__summary span { color: var(--erp-color-text-secondary); font-size: 13px; }
.image-upload { margin-bottom: 16px; }
.image-upload :deep(.el-upload),
.image-upload :deep(.el-upload-dragger) { width: 100%; }
.image-upload :deep(.el-upload-dragger) { padding: 18px; }
.image-upload__icon { margin-bottom: 6px; color: var(--erp-color-text-regular); font-size: 28px; }
.image-upload small { display: block; margin-top: 5px; color: var(--erp-color-text-muted); }
.image-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; max-height: 350px; overflow-y: auto; }
.image-item { display: grid; grid-template-columns: 72px minmax(0, 1fr) auto; align-items: center; gap: 10px; min-width: 0; padding: 8px; border: 1px solid var(--erp-color-border); border-radius: 7px; }
.image-item img { width: 72px; height: 58px; object-fit: cover; border-radius: 4px; background: var(--erp-color-readonly); }
.image-item > div:nth-child(2) { min-width: 0; }
.image-item strong,
.image-item span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.image-item strong { margin-bottom: 5px; font-size: 13px; }
.image-item span { color: var(--erp-color-text-muted); font-size: 12px; }
.image-item__actions { display: flex; gap: 6px; }
.image-preview { display: flex; min-height: 280px; max-height: 660px; align-items: center; justify-content: center; overflow: auto; background: var(--erp-page-background); }
.image-preview img { max-width: 100%; max-height: 640px; object-fit: contain; }
</style>
