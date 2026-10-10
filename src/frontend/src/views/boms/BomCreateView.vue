<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile, UploadFiles, UploadInstance } from 'element-plus'

import { createBom, fetchBomOptions, previewBomWorkbook } from '@/api/boms'
import ProductCreateDialog from '@/components/products/ProductCreateDialog.vue'
import ProductPickerDialog from '@/components/products/ProductPickerDialog.vue'
import ProductionTaskProductUpdateDialog from '@/components/production/ProductionTaskProductUpdateDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { ProductInformation } from '@/types/product'
import type { ProductOption, ProductionTaskOptions, ProductionTaskProductUpdateDraft } from '@/types/productionTask'
import type {
  BomCreationMethod,
  BomOptions,
  BomProductionTaskProduct,
  BomWorkbookPreview,
} from '@/types/bom'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const uploadRef = ref<UploadInstance>()
const maxWorkbookBytes = 100 * 1024 * 1024
const wizardSteps = [1, 2, 3] as const
let previewRequestId = 0

const options = ref<BomOptions | null>(null)
const optionsLoading = ref(false)
const previewLoading = ref(false)
const submitting = ref(false)
const currentStep = ref<1 | 2 | 3>(1)
const selectedProductId = ref('')
const taskSearchProductId = ref('')
const taskSearchKeyword = ref('')
const remoteTaskProducts = ref<BomProductionTaskProduct[]>([])
const selectedTaskProductSnapshot = ref<BomProductionTaskProduct | null>(null)
const taskSearchLoading = ref(false)
const requestedCreationMethod = String(route.query.method || '').toUpperCase()
const creationMethod = ref<BomCreationMethod>(
  requestedCreationMethod === 'COPY' || requestedCreationMethod === 'BLANK' ? requestedCreationMethod : 'IMPORT',
)
const selectedFile = ref<File | null>(null)
const sourceBomId = ref('')
const preview = ref<BomWorkbookPreview | null>(null)
const previewError = ref('')
const quantityDifferenceReason = ref('')
const productionOptions = ref<ProductionTaskOptions | null>(null)
const productPickerVisible = ref(false)
const productCreateVisible = ref(false)
const productUpdateVisible = ref(false)
const replacementProduct = ref<ProductOption | null>(null)
const replacementDraft = ref<ProductionTaskProductUpdateDraft | null>(null)

const canCreateProduct = computed(() => Boolean(
  authStore.user?.is_superuser
  || (
    authStore.hasPermission('products.view_productinformation')
    && authStore.hasPermission('products.add_productinformation')
  )
))

const methodCards: Array<{ value: BomCreationMethod; title: string; description: string }> = [
  { value: 'IMPORT', title: '从 Excel BOM 导入', description: '读取本地 Excel 文件，自动识别物料、分类、规格和用量等信息' },
  { value: 'COPY', title: '复制历史 BOM', description: '选择同产品的历史 BOM，复制结构后再调整' },
  { value: 'BLANK', title: '空白建立', description: '只带出任务与产品信息，手工新增物料' },
]

const selectedProduct = computed(() => (
  allTaskProducts.value.find((item) => item.id === selectedProductId.value) || null
))

const previewRows = computed(() => (
  preview.value?.sections.flatMap((section) => section.preview_rows) || []
))

const allTaskProducts = computed(() => {
  const products = new Map<string, BomProductionTaskProduct>()
  for (const item of options.value?.production_task_products || []) {
    if (!item.existing_bom_count) products.set(item.id, item)
  }
  for (const item of remoteTaskProducts.value) {
    if (!item.existing_bom_count) products.set(item.id, item)
  }
  if (selectedTaskProductSnapshot.value && !selectedTaskProductSnapshot.value.existing_bom_count) {
    products.set(selectedTaskProductSnapshot.value.id, selectedTaskProductSnapshot.value)
  }
  return Array.from(products.values())
})

function matchesTaskSearch(item: BomProductionTaskProduct, keyword: string) {
  const normalizedKeyword = keyword.trim().toLowerCase()
  if (!normalizedKeyword) return true
  return [item.task_number, item.order_number, item.product_number, item.product_code, item.product_name]
    .some((value) => String(value || '').toLowerCase().includes(normalizedKeyword))
}

const taskCandidates = computed(() => (
  allTaskProducts.value
))

const taskSearchOptions = computed(() => (
  taskCandidates.value.filter((item) => matchesTaskSearch(item, taskSearchKeyword.value)).slice(0, 50)
))

const filteredProducts = computed(() => {
  const matchedProducts = taskCandidates.value.filter((item) => matchesTaskSearch(item, taskSearchKeyword.value))
  if (taskSearchKeyword.value.trim()) return matchedProducts.slice(0, 20)
  if (taskSearchProductId.value) {
    const exactProduct = matchedProducts.find((item) => item.id === taskSearchProductId.value)
    return exactProduct ? [exactProduct] : []
  }
  const selected = matchedProducts.find((item) => item.id === selectedProductId.value)
  return selected
    ? [selected, ...matchedProducts.filter((item) => item.id !== selected.id)].slice(0, 20)
    : matchedProducts.slice(0, 20)
})

const copyCandidates = computed(() => {
  if (!selectedProduct.value) return []
  const productCode = replacementProduct.value?.product_code || selectedProduct.value.product_code
  const productNumber = replacementProduct.value?.product_number || selectedProduct.value.product_number
  return (options.value?.history_boms || []).filter((item) => (
    item.product_code_snapshot === productCode
    || (!productCode && item.product_number_snapshot === productNumber)
  ))
})

const sourceReady = computed(() => {
  if (creationMethod.value === 'IMPORT') return Boolean(preview.value && !preview.value.identity_errors.length)
  if (creationMethod.value === 'COPY') return Boolean(sourceBomId.value)
  return Boolean(selectedProduct.value)
})

const canSubmit = computed(() => {
  if (!selectedProduct.value || submitting.value || previewLoading.value) return false
  if (replacementProduct.value && !replacementDraft.value) return false
  if (creationMethod.value === 'IMPORT' && !(selectedFile.value && sourceReady.value)) return false
  if (creationMethod.value === 'COPY' && !sourceBomId.value) return false
  return !quantityRequiresReason.value || Boolean(quantityDifferenceReason.value.trim())
})

const reviewSource = computed(() => (
  creationMethod.value === 'COPY'
    ? copyCandidates.value.find((item) => item.id === sourceBomId.value) || null
    : null
))

const reviewQuantities = computed(() => {
  const baseline = Number(selectedProduct.value?.order_quantity || 0)
  const current = Number(replacementDraft.value?.payload.quantity || selectedProduct.value?.order_quantity || 0)
  const sourceValue = creationMethod.value === 'IMPORT'
    ? preview.value?.quantity.source_quantity
    : creationMethod.value === 'COPY'
      ? reviewSource.value?.source_quantity || reviewSource.value?.order_quantity
      : null
  const batchValue = preview.value?.quantity.batch_quantity ?? selectedProduct.value?.batch_quantity ?? null
  return [
    { label: '订单依据数量', value: baseline, difference: 0 },
    { label: '当前任务数量', value: current, difference: current - baseline },
    { label: creationMethod.value === 'IMPORT' ? 'Excel原表数量' : creationMethod.value === 'COPY' ? '历史BOM数量' : '来源数据数量', value: sourceValue === null || sourceValue === undefined ? null : Number(sourceValue), difference: sourceValue === null || sourceValue === undefined ? null : Number(sourceValue) - baseline },
    { label: '生产批次数量', value: batchValue === null || batchValue === undefined ? null : Number(batchValue), difference: batchValue === null || batchValue === undefined ? null : Number(batchValue) - baseline },
  ]
})

const quantityRequiresReason = computed(() => reviewQuantities.value.some((item) => item.difference !== null && item.difference !== 0))

const expectedResult = computed(() => {
  if (preview.value) {
    return `${preview.value.section_count} 个用料分类 · ${preview.value.line_count} 行明细 · ${preview.value.calculation_summary.calculation_row_count} 行计算 / 汇总`
  }
  if (creationMethod.value === 'COPY') {
    const source = copyCandidates.value.find((item) => item.id === sourceBomId.value)
    return source ? `${source.section_count} 个用料分类 · ${source.line_count} 行明细` : '选择历史 BOM 后显示预计结果'
  }
  if (creationMethod.value === 'BLANK') return '仅生成 BOM 主记录，暂不生成用料明细'
  return '选择并解析 Excel 后显示预计结果'
})

function apiError(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (error.code === 'ECONNABORTED') return '文件上传或解析超时，请确认文件小于 100 MB 后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务。'
  const data = error.response.data as { error?: { message?: string }; detail?: string; workbook?: string[] | string }
  if (Array.isArray(data.workbook)) return data.workbook[0] || 'Excel 文件校验失败。'
  if (typeof data.workbook === 'string') return data.workbook
  return data.error?.message || data.detail || '操作失败，请检查填写内容。'
}

function number(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed)
    ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(parsed)
    : String(value)
}

async function loadOptions() {
  optionsLoading.value = true
  try {
    options.value = await fetchBomOptions()
    productionOptions.value = {
      order_sources: [], delivery_methods: [], statuses: [], boolean_options: [], customers: [], employees: [],
      products: options.value.products, currencies: options.value.currencies, units: options.value.units,
      colors: options.value.colors, detail_template: options.value.detail_template,
    }
    const requestedProductId = String(route.query.production_task_product_id || '')
    if (requestedProductId) {
      const requestedProduct = options.value.production_task_products.find((item) => item.id === requestedProductId)
      if (requestedProduct) {
        selectProduct(requestedProduct)
        currentStep.value = 2
      }
    }
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    optionsLoading.value = false
  }
}

async function chooseReplacementProduct(product: ProductOption) {
  if (!selectedProduct.value) return
  if (product.id === (replacementProduct.value?.id || selectedProduct.value.product_id)) {
    productPickerVisible.value = false
    return
  }
  try {
    await ElMessageBox.confirm(
      '更换产品将同步更新生产任务，是否继续？',
      '确认更换产品',
      { type: 'warning', confirmButtonText: '继续填写', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  replacementProduct.value = product
  replacementDraft.value = null
  productPickerVisible.value = false
  productUpdateVisible.value = true
}

function handleReplacementDraft(draft: ProductionTaskProductUpdateDraft) {
  replacementDraft.value = draft
  clearUpload()
  sourceBomId.value = ''
}

function openProductCreate() {
  if (canCreateProduct.value) productCreateVisible.value = true
}

async function handleProductCreated(product: ProductInformation) {
  if (!productionOptions.value) return
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
    const refreshed = await fetchBomOptions()
    options.value = refreshed
    productionOptions.value.products = refreshed.products
    productionOptions.value.currencies = refreshed.currencies
    productionOptions.value.units = refreshed.units
    productionOptions.value.colors = refreshed.colors
    productionOptions.value.detail_template = refreshed.detail_template
    candidate = refreshed.products.find((item) => item.id === product.id) || fallback
  } catch {
    productionOptions.value.products = [fallback, ...productionOptions.value.products.filter((item) => item.id !== fallback.id)]
  }
  await chooseReplacementProduct(candidate)
}

function selectProduct(item: BomProductionTaskProduct) {
  selectedTaskProductSnapshot.value = item
  if (selectedProductId.value !== item.id) selectedProductId.value = item.id
}

function selectProductAndContinue(item: BomProductionTaskProduct) {
  selectProduct(item)
  currentStep.value = 2
}

function taskStatusTagClass(status: string) {
  if (status === 'READY' || status === 'IN_PRODUCTION' || status === 'COMPLETED') return 'is-success'
  if (status === 'PENDING_VALIDATION' || status === 'PAUSED') return 'is-warning'
  if (status === 'CANCELLED') return 'is-danger'
  return 'is-neutral'
}

function goNext() {
  if (currentStep.value === 1) {
    if (!selectedProduct.value) {
      ElMessage.warning('请先选择生产任务单及产品。')
      return
    }
    currentStep.value = 2
    return
  }
  if (!sourceReady.value) {
    ElMessage.warning('请先完成 BOM 建立方式与数据来源。')
    return
  }
  currentStep.value = 3
}

function goPrevious() {
  if (currentStep.value > 1) currentStep.value = (currentStep.value - 1) as 1 | 2
}

function differenceText(value: number | null) {
  if (value === null) return '—'
  if (value === 0) return '0'
  return `${value > 0 ? '+' : ''}${number(value)}`
}

function taskOptionLabel(item: BomProductionTaskProduct) {
  return `${item.task_number} · ${item.product_code || item.product_number} · ${item.product_name}`
}

let taskSearchTimer: ReturnType<typeof setTimeout> | null = null
let taskSearchRequestId = 0

function cancelPendingTaskSearch() {
  if (taskSearchTimer) clearTimeout(taskSearchTimer)
  taskSearchTimer = null
  taskSearchRequestId += 1
  taskSearchLoading.value = false
}

function filterTaskOptions(keyword: string) {
  taskSearchKeyword.value = keyword
  cancelPendingTaskSearch()
  const normalizedKeyword = keyword.trim()
  if (!normalizedKeyword) {
    remoteTaskProducts.value = []
    return
  }
  const requestId = taskSearchRequestId
  taskSearchLoading.value = true
  taskSearchTimer = setTimeout(async () => {
    try {
      const result = await fetchBomOptions(normalizedKeyword)
      if (requestId === taskSearchRequestId) remoteTaskProducts.value = result.production_task_products
    } catch (error) {
      if (requestId === taskSearchRequestId) ElMessage.error(apiError(error))
    } finally {
      if (requestId === taskSearchRequestId) taskSearchLoading.value = false
    }
  }, 250)
}

function selectTaskFromSearch(productId: string) {
  cancelPendingTaskSearch()
  taskSearchKeyword.value = ''
  const product = allTaskProducts.value.find((item) => item.id === productId)
  if (product) selectProduct(product)
}

function clearTaskSearch() {
  cancelPendingTaskSearch()
  taskSearchProductId.value = ''
  taskSearchKeyword.value = ''
  remoteTaskProducts.value = []
}

function clearUpload() {
  previewRequestId += 1
  selectedFile.value = null
  preview.value = null
  previewError.value = ''
  previewLoading.value = false
  uploadRef.value?.clearFiles()
}

function chooseWorkbook() {
  const root = (uploadRef.value as unknown as { $el?: HTMLElement } | undefined)?.$el
  root?.querySelector<HTMLInputElement>('input[type="file"]')?.click()
}

function validateFile(file: File) {
  if (file.name.startsWith('~$')) return '这是 Excel 临时锁文件，请选择原始工作簿。'
  if (!/\.xlsx?$/i.test(file.name)) return '只支持 .xls 或 .xlsx 格式。'
  if (file.size > maxWorkbookBytes) return '文件不能超过 100 MB。'
  if (file.size === 0) return '文件内容为空。'
  return ''
}

async function handleFileChange(uploadFile: UploadFile, _uploadFiles: UploadFiles) {
  const file = uploadFile.raw
  if (!file) return
  if (!selectedProduct.value) {
    ElMessage.warning('请先选择生产任务产品。')
    clearUpload()
    return
  }
  if (replacementProduct.value && !replacementDraft.value) {
    ElMessage.warning('请先完整填写更换后的生产任务信息。')
    clearUpload()
    return
  }
  const invalidMessage = validateFile(file)
  if (invalidMessage) {
    ElMessage.error(invalidMessage)
    clearUpload()
    return
  }

  selectedFile.value = file
  preview.value = null
  previewError.value = ''
  previewLoading.value = true
  const requestId = ++previewRequestId
  const productId = selectedProduct.value.id
  const productUpdate = replacementDraft.value?.payload
  try {
    const result = await previewBomWorkbook(productId, file, productUpdate)
    if (requestId !== previewRequestId || selectedFile.value !== file || selectedProductId.value !== productId) return
    preview.value = result
    if (result.identity_errors.length) {
      previewError.value = result.identity_errors.join('；')
    } else {
      ElMessage.success(`Excel 第 ${result.sheet_number} 个 Sheet 解析完成。`)
    }
  } catch (error) {
    if (requestId !== previewRequestId || selectedFile.value !== file || selectedProductId.value !== productId) return
    previewError.value = apiError(error)
    ElMessage.error(previewError.value)
  } finally {
    if (requestId === previewRequestId) previewLoading.value = false
  }
}

async function submit() {
  if (!canSubmit.value || !selectedProduct.value) {
    ElMessage.warning('请先完成必填信息和校验。')
    return
  }
  submitting.value = true
  try {
    const result = await createBom({
      productionTaskProductId: selectedProduct.value.id,
      creationMethod: creationMethod.value,
      workbook: creationMethod.value === 'IMPORT' ? selectedFile.value : null,
      sourceBomId: creationMethod.value === 'COPY' ? sourceBomId.value : undefined,
      productUpdate: replacementDraft.value?.payload,
      productImages: replacementDraft.value?.productImages,
      detailImages: replacementDraft.value?.detailImages,
      taskEtag: selectedProduct.value.task_etag,
      quantityDifferenceReason: quantityDifferenceReason.value,
    })
    ElMessage.success(`${result.bom_number} 创建成功。`)
    await router.push({ name: 'bom-edit', params: { bomId: result.id } })
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    submitting.value = false
  }
}

function cancel() {
  void router.push({ name: 'boms' })
}

watch(selectedProductId, () => {
  clearUpload()
  sourceBomId.value = ''
  quantityDifferenceReason.value = ''
  replacementProduct.value = null
  replacementDraft.value = null
})

watch(creationMethod, () => {
  if (creationMethod.value !== 'IMPORT') clearUpload()
  if (creationMethod.value !== 'COPY') sourceBomId.value = ''
  quantityDifferenceReason.value = ''
})

onMounted(() => { void loadOptions() })
onBeforeUnmount(cancelPendingTaskSearch)
</script>

<template>
  <section class="bom-create-page" aria-label="新建 BOM">
    <header class="page-heading">
      <div>
        <h1>新建BOM</h1>
        <p>根据生产任务单建立BOM，支持从Excel导入、复制历史BOM或空白建立</p>
      </div>
    </header>

    <div class="wizard-layout">
      <nav class="wizard-steps" aria-label="BOM 建立步骤">
        <button v-for="step in wizardSteps" :key="step" type="button" class="wizard-step" :class="{ 'is-active': currentStep === step, 'is-complete': currentStep > step }" :disabled="step > currentStep" @click="currentStep = step">
          <i>{{ currentStep > step ? '✓' : step }}</i>
          <b>{{ step }}</b>
          <span>
            <strong>{{ step === 1 ? '选择任务与产品' : step === 2 ? '选择建立方式' : '检查并创建' }}</strong>
            <small>{{ step === 1 ? (selectedProduct ? '已选择生产任务单和生产产品' : '选择生产任务单及产品') : step === 2 ? '选择BOM建立方式并导入或设置数据' : '核对数据并创建BOM草稿' }}</small>
          </span>
        </button>
      </nav>

      <main class="wizard-content" :class="{ 'has-aside': currentStep > 1 }">
        <section v-if="currentStep === 1" class="content-card task-selection" v-loading="optionsLoading">
          <h2>选择生产任务单及产品</h2>
          <ElSelect
            v-model="taskSearchProductId"
            class="task-search"
            clearable
            filterable
            :loading="taskSearchLoading"
            :filter-method="filterTaskOptions"
            placeholder="搜索生产任务单号 / 产品"
            @change="selectTaskFromSearch"
            @clear="clearTaskSearch"
          >
            <ElOption v-for="item in taskSearchOptions" :key="item.id" :label="taskOptionLabel(item)" :value="item.id" />
          </ElSelect>
          <ElTable :data="filteredProducts" border class="task-table" empty-text="没有可建立 BOM 的生产任务单">
            <ElTableColumn prop="task_number" label="生产任务单" min-width="150" show-overflow-tooltip />
            <ElTableColumn prop="customer_name" label="客户" min-width="130" show-overflow-tooltip><template #default="{ row }">{{ row.customer_name || '—' }}</template></ElTableColumn>
            <ElTableColumn label="产品" min-width="210" show-overflow-tooltip><template #default="{ row }">{{ row.product_code || row.product_number }} · {{ row.product_name }}</template></ElTableColumn>
            <ElTableColumn label="生产数量" width="110" align="right"><template #default="{ row }">{{ number(row.order_quantity) }} PCS</template></ElTableColumn>
            <ElTableColumn label="PMC状态" width="100" align="center"><template #default="{ row }"><span class="strong-tag" :class="taskStatusTagClass(row.task_status)">{{ row.task_status === 'READY' ? '已接单' : row.task_status_display }}</span></template></ElTableColumn>
            <ElTableColumn label="操作" width="84" align="center" class-name="task-action-column"><template #default="{ row }"><button type="button" class="task-select-action" @click="selectProductAndContinue(row)">选择</button></template></ElTableColumn>
          </ElTable>
          <div class="step-one-actions"><ElButton @click="cancel">返回列表</ElButton></div>
        </section>

        <section v-else-if="currentStep === 2" class="content-card method-content">
          <h2>选择建立方式</h2>
          <p class="section-note">请选择一种方式建立BOM</p>
          <div class="method-list">
            <button v-for="(item, index) in methodCards" :key="item.value" type="button" class="method-card" :class="{ 'is-selected': creationMethod === item.value }" @click="creationMethod = item.value">
              <span class="radio-dot" /><i>{{ index === 0 ? 'E' : index === 1 ? '▦' : 'T' }}</i><span><strong>{{ item.title }}</strong><small>{{ item.description }}</small></span>
            </button>
          </div>
          <section class="source-section">
            <h3>{{ creationMethod === 'IMPORT' ? '导入文件与预览' : creationMethod === 'COPY' ? '选择历史BOM' : '空白BOM说明' }}</h3>
            <p v-if="creationMethod === 'IMPORT' && preview">已选择Excel文件，系统识别到{{ preview.section_count }}个分区，共{{ preview.line_count }}行数据</p>
            <ElUpload v-if="creationMethod === 'IMPORT'" ref="uploadRef" class="source-upload" drag action="#" :auto-upload="false" :limit="1" :show-file-list="false" accept=".xls,.xlsx" :on-change="handleFileChange" :on-remove="clearUpload">
              <div v-if="selectedFile || previewLoading" v-loading="previewLoading" class="file-row" @click.stop>
                <span class="file-icon">E</span><div><strong>{{ preview?.file_name || selectedFile?.name }}</strong><small>第{{ preview?.sheet_number || 2 }}个工作表</small></div>
                <span v-if="preview" class="strong-tag">识别完成</span>
                <small v-if="preview">{{ preview.section_count }}个分区，{{ preview.line_count }}行明细</small>
                <ElButton @click.stop="chooseWorkbook">重新选择文件</ElButton>
              </div>
              <div v-else class="upload-empty"><strong>点击选择或拖入 BOM Excel 文件</strong><small>支持 .xls / .xlsx，最大100 MB，优先读取第2个工作表</small></div>
            </ElUpload>
            <p v-if="previewError" class="error-text">{{ previewError }}</p>
            <div v-if="creationMethod === 'IMPORT' && preview" class="preview-table">
              <div class="preview-heading"><strong>数据预览（前{{ preview.preview_limit }}行）</strong><span>已显示 {{ preview.preview_row_count }} / {{ preview.line_count }} 行</span></div>
              <ElTable :data="previewRows" border size="small" max-height="360">
                <ElTableColumn prop="line_number" label="行号" width="58" align="center" />
                <ElTableColumn prop="material_category" label="物料分类" width="92" />
                <ElTableColumn prop="material_code" label="物料编码" width="120"><template #default="{ row }">{{ row.material_code || '—' }}</template></ElTableColumn>
                <ElTableColumn prop="material_name" label="物料名称" width="115" />
                <ElTableColumn prop="specification" label="规格型号" min-width="130"><template #default="{ row }">{{ row.specification || '—' }}</template></ElTableColumn>
                <ElTableColumn prop="unit" label="单位" width="66" align="center" />
                <ElTableColumn label="单件用量" width="105" align="right"><template #default="{ row }">{{ number(row.unit_consumption) }}</template></ElTableColumn>
                <ElTableColumn prop="section" label="分区" width="105" />
                <ElTableColumn prop="notes" label="备注" min-width="110"><template #default="{ row }">{{ row.notes || '—' }}</template></ElTableColumn>
              </ElTable>
            </div>
            <div v-else-if="creationMethod === 'COPY'" class="alternative-source"><ElSelect v-model="sourceBomId" placeholder="请选择同产品历史BOM" clearable><ElOption v-for="item in copyCandidates" :key="item.id" :label="`${item.bom_number} · ${item.section_count}个分区 · ${item.line_count}行`" :value="item.id" /></ElSelect><span v-if="selectedProduct && !copyCandidates.length">当前产品没有可复制的历史BOM</span></div>
            <div v-else-if="creationMethod === 'BLANK'" class="blank-source">仅建立BOM主记录和默认分区，不生成虚构用料数据；创建后在编辑页新增物料。</div>
          </section>
        </section>

        <section v-else class="content-card review-content">
          <h2>检查并创建BOM草稿</h2>
          <dl class="review-meta">
            <div><dt>建立方式</dt><dd>{{ creationMethod === 'IMPORT' ? `Excel导入 · ${preview?.file_name || '—'} 第${preview?.sheet_number || 2}个工作表` : creationMethod === 'COPY' ? `复制历史BOM · ${reviewSource?.bom_number || '—'}` : '空白建立' }}</dd></div>
            <div><dt>识别结果</dt><dd>{{ expectedResult }}</dd></div>
            <div><dt>来源产品</dt><dd>{{ selectedProduct?.product_code || selectedProduct?.product_number }} {{ selectedProduct?.product_name }}</dd></div>
          </dl>
          <table class="quantity-table"><thead><tr><th>数量来源</th><th>数量/PCS</th><th>与当前任务差异</th></tr></thead><tbody><tr v-for="item in reviewQuantities" :key="item.label"><td>{{ item.label }}</td><td>{{ item.value === null ? '—' : number(item.value) }}</td><td :class="{ warning: item.difference }">{{ differenceText(item.difference) }}</td></tr></tbody></table>
          <label class="reason-field"><span>数量差异说明<span v-if="quantityRequiresReason"> *</span></span><ElInput v-model="quantityDifferenceReason" maxlength="500" show-word-limit :placeholder="quantityRequiresReason ? '请说明数量差异及本次执行依据' : '数量一致，可不填写'" /></label>
          <div class="info-strip">此操作只创建草稿，BOM需在编辑页单独确认。</div>
        </section>

        <aside v-if="currentStep > 1" class="source-aside">
          <h2>来源信息</h2><p>已从生产任务单带出以下信息，不可修改</p>
          <dl class="source-list">
            <div><dt>生产任务单</dt><dd>{{ selectedProduct?.task_number || '—' }}</dd></div>
            <div><dt>客户订单</dt><dd>{{ selectedProduct?.order_number || '—' }}</dd></div>
            <div><dt>客户名称</dt><dd>{{ selectedProduct?.customer_name || '—' }}</dd></div>
            <div><dt>产品编号</dt><dd>{{ replacementProduct?.product_code || replacementProduct?.product_number || selectedProduct?.product_code || selectedProduct?.product_number || '—' }}</dd></div>
            <div><dt>产品名称</dt><dd>{{ replacementProduct?.product_name || selectedProduct?.product_name || '—' }}</dd></div>
            <div><dt>生产数量</dt><dd>{{ number(replacementDraft?.payload.quantity || selectedProduct?.order_quantity) }} PCS</dd></div>
            <div><dt>任务状态</dt><dd><span class="strong-tag" :class="taskStatusTagClass(selectedProduct?.task_status || '')">{{ selectedProduct?.task_status === 'READY' ? '已接单' : selectedProduct?.task_status_display || '—' }}</span></dd></div>
            <div><dt>计划开工</dt><dd>{{ selectedProduct?.planned_start_date || '—' }}</dd></div>
            <div><dt>计划完工</dt><dd>{{ selectedProduct?.planned_end_date || selectedProduct?.delivery_date || '—' }}</dd></div>
          </dl>
          <div class="aside-divider" />
          <h2>数据校验</h2><p>系统已对导入数据进行基础校验</p>
          <div class="check-item is-ok"><i>✓</i><span><strong>来源任务单匹配</strong><small>BOM数据与生产任务单产品一致</small></span></div>
          <div class="check-item" :class="{ 'is-ok': sourceReady }"><i>{{ sourceReady ? '✓' : '!' }}</i><span><strong>字段识别成功</strong><small>{{ sourceReady ? '已识别物料编码、名称、规格、单位、用量等字段' : '等待完成数据来源设置' }}</small></span></div>
          <div class="check-item" :class="{ 'is-ok': !quantityRequiresReason }"><i>{{ quantityRequiresReason ? '!' : '✓' }}</i><span><strong>数量校验</strong><small>{{ quantityRequiresReason ? '来源数量与当前任务数量存在差异，需在下一步说明' : '各数量来源与当前任务数量一致' }}</small></span></div>
          <div class="check-item" :class="{ 'is-ok': creationMethod !== 'IMPORT' || Boolean(preview) }"><i>{{ creationMethod !== 'IMPORT' || preview ? '✓' : '!' }}</i><span><strong>数据结构完整</strong><small>{{ preview ? `共${preview.section_count}个分区，${preview.line_count}行数据` : creationMethod === 'IMPORT' ? '等待解析Excel数据' : '创建后在编辑页维护结构' }}</small></span></div>
        </aside>
      </main>
    </div>

    <footer v-if="currentStep > 1" class="wizard-actions"><ElButton @click="goPrevious">上一步</ElButton><ElButton v-if="currentStep === 2" type="primary" :disabled="!sourceReady" @click="goNext">下一步：检查并创建</ElButton><ElButton v-else type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">创建BOM草稿</ElButton></footer>
    <ProductPickerDialog
      v-model="productPickerVisible"
      :products="productionOptions?.products || []"
      :units="productionOptions?.units || []"
      :selected-id="replacementProduct?.id || selectedProduct?.product_id || ''"
      :can-create="canCreateProduct"
      @select="chooseReplacementProduct"
      @create="openProductCreate"
    />
    <ProductCreateDialog v-model="productCreateVisible" @created="handleProductCreated" />
    <ProductionTaskProductUpdateDialog
      v-model="productUpdateVisible"
      :product="replacementProduct"
      :line-id="selectedProduct?.id || ''"
      :task-currency-id="selectedProduct?.task_currency_id || ''"
      :options="productionOptions"
      @confirm="handleReplacementDraft"
    />
  </section>
</template>

<style scoped lang="scss">
.bom-create-page { min-width: 1320px; min-height: 1024px; padding: 0 32px 52px; box-sizing: border-box; background: var(--erp-page-background); color: #18181b; }
.page-heading { height: 126px; display: flex; align-items: flex-start; justify-content: space-between; box-sizing: border-box; padding-top: 18px; }
.breadcrumb { color: #63666d; font-size: 12px; line-height: 14px; }
.page-heading h1 { margin: 5px 0 0; font-size: 28px; line-height: 34px; }
.page-heading p { margin: 3px 0 0; color: #63666d; font-size: 14px; line-height: 17px; }
.page-heading__actions { display: flex; gap: 8px; padding-top: 26px; }
.step-card { height: 78px; display: grid; grid-template-columns: 1fr 152px 1fr 152px 1fr; align-items: center; padding: 0 60px; box-sizing: border-box; border: 1px solid #e5e7ea; border-radius: 10px; background: #fff; }
.step { display: flex; align-items: center; gap: 14px; color: #63666d; }
.step > span { width: 40px; height: 40px; display: grid; place-items: center; flex: none; border-radius: 50%; color: #63666d; background: #f1f2f4; font-size: 15px; font-weight: 700; }
.step div { display: flex; flex-direction: column; gap: 6px; }
.step strong { font-size: 15px; font-weight: 500; }
.step small { color: #63666d; font-size: 12px; }
.step.is-complete > span { color: #189858; background: #ecfaf1; }
.step.is-complete strong, .step.is-current strong { color: #18181b; }
.step.is-current > span { color: #2563eb; background: #eff4ff; }
.step-card > i { height: 2px; background: #e5e7ea; }
.step-card > i.is-complete { background: #189858; }
.content-grid { display: grid; grid-template-columns: minmax(0, 1064px) 536px; gap: 16px; margin-top: 16px; align-items: start; }
.main-column, .side-column { display: flex; flex-direction: column; gap: 16px; }
.panel, .side-card { position: relative; box-sizing: border-box; border: 1px solid #e5e7ea; border-radius: 10px; background: #fff; }
.panel h2, .side-card h2 { margin: 0; font-size: 16px; line-height: 19px; }
.panel-description { margin: 11px 0 0; color: #63666d; font-size: 12px; line-height: 14px; }
.task-panel { height: 238px; padding: 17px 19px; }
.task-filters { width: 600px; display: grid; grid-template-columns: 420px 168px; gap: 12px; margin-top: 16px; }
.task-card-grid { display: grid; grid-template-columns: 498px 514px; gap: 12px; margin-top: 22px; }
.task-card { position: relative; height: 84px; padding: 12px 16px; box-sizing: border-box; border: 1px solid #e5e7ea; border-radius: 8px; color: inherit; background: #fff; font-family: inherit; text-align: left; cursor: pointer; }
.task-card.is-selected { border-color: #86a7ff; background: #f3f6ff; }
.task-card__check { position: absolute; left: 16px; top: 28px; width: 28px; height: 28px; display: grid; place-items: center; border-radius: 50%; color: #fff; background: #2563eb; font-size: 14px; }
.task-card__main { position: absolute; left: 16px; top: 12px; display: flex; flex-direction: column; gap: 9px; }
.task-card.is-selected .task-card__main { left: 56px; }
.task-card__main strong { font-size: 14px; line-height: 18px; }
.task-card__main small { color: #63666d; font-size: 12px; line-height: 14px; }
.task-card__status { position: absolute; right: 18px; top: 12px; display: flex; align-items: flex-end; flex-direction: column; gap: 7px; }
.task-card__status b { min-width: 76px; height: 28px; display: grid; place-items: center; border-radius: 6px; color: #189858; background: #ecfaf1; font-size: 12px; font-weight: 500; }
.task-card.is-selected .task-card__status b { color: #2563eb; background: #eff4ff; }
.task-card__status small { color: #63666d; font-size: 11px; }
.task-empty { margin-top: 22px; color: #a1a1aa; font-size: 13px; text-align: center; }
.product-panel { height: 164px; padding: 17px 19px; }
.product-panel__tools { position: absolute; right: 19px; top: 13px; display: flex; align-items: center; gap: 10px; }
.maintenance-source-badge { height: 28px; display: inline-flex; align-items: center; padding: 0 12px; border: 1px solid #bfdbfe; border-radius: 6px; color: #2563eb; background: #eff6ff; font-size: 12px; }
.change-product-button :deep(.el-button) { height: 28px; padding: 0 4px; }
.product-fields { display: grid; grid-template-columns: 150px 160px 150px 186px 130px 188px; gap: 12px; margin-top: 15px; }
.product-fields label { min-width: 0; }
.product-fields label > span { display: block; margin-bottom: 8px; color: #63666d; font-size: 11px; }
.product-fields label > strong { height: 42px; display: flex; align-items: center; padding: 0 12px; box-sizing: border-box; overflow: hidden; border: 1px solid #86a7ff; border-radius: 6px; background: #f8faff; font-size: 13px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.product-empty { margin-top: 28px; color: #a1a1aa; font-size: 13px; text-align: center; }
.method-panel { height: 318px; padding: 17px 19px; }
.method-panel.has-preview { height: 610px; }
.method-grid { display: grid; grid-template-columns: repeat(3, 324px); gap: 16px; margin-top: 15px; }
.method-card { position: relative; height: 82px; padding: 11px 16px; box-sizing: border-box; border: 1px solid #e5e7ea; border-radius: 8px; color: inherit; background: #fff; font-family: inherit; text-align: left; cursor: pointer; }
.method-card.is-selected { border-color: #2563eb; background: #eff4ff; }
.method-card > span:nth-child(2) { position: absolute; left: 46px; top: 11px; display: flex; flex-direction: column; gap: 8px; }
.method-card strong { font-size: 14px; line-height: 17px; }
.method-card small { width: 254px; color: #63666d; font-size: 12px; line-height: 18px; }
.method-card > b { position: absolute; right: 16px; top: 9px; width: 48px; height: 26px; display: grid; place-items: center; border-radius: 6px; color: #2563eb; background: #fff; font-size: 12px; font-weight: 500; }
.radio-dot { position: absolute; left: 16px; top: 17px; width: 18px; height: 18px; box-sizing: border-box; border: 1px solid #b8bec8; border-radius: 50%; }
.method-card.is-selected .radio-dot { border: 5px solid #2563eb; background: #fff; }
.source-upload, .alternative-source-card { position: absolute; left: 19px; right: 19px; top: 175px; height: 122px; }
.source-upload :deep(.el-upload), .source-upload :deep(.el-upload-dragger) { width: 100%; height: 122px; padding: 0; border: 0; background: transparent; }
.source-file-card, .source-empty-card, .alternative-source-card { position: relative; height: 122px; padding: 13px 15px; box-sizing: border-box; border: 1px solid #e5e7ea; border-radius: 8px; background: #fafafb; text-align: left; }
.source-file-card__label, .alternative-source-card > span { display: block; color: #63666d; font-size: 12px; }
.source-file-card > strong { position: absolute; left: 15px; top: 39px; width: 430px; overflow: hidden; font-size: 14px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.source-file-card__tags { position: absolute; left: 467px; top: 35px; display: flex; gap: 10px; }
.source-file-card__tags span { height: 26px; display: grid; place-items: center; padding: 0 18px; border-radius: 6px; font-size: 12px; white-space: nowrap; }
.source-file-card__tags .is-blue { color: #2563eb; background: #eff4ff; }
.source-file-card__tags .is-green { color: #189858; background: #ecfaf1; }
.reselect-button { position: absolute; right: 20px; top: 27px; width: 148px; }
.lock-warning { position: absolute; left: 15px; right: 15px; bottom: 14px; height: 32px; display: flex; align-items: center; margin: 0; padding: 0 12px; box-sizing: border-box; border-radius: 6px; color: #d96e0a; background: #fff8e9; font-size: 12px; font-weight: 500; }
.lock-warning.is-error { color: #dc2626; background: #fff1f2; }
.source-empty-card { display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 9px; color: #63666d; text-align: center; }
.source-empty-card strong { color: #18181b; font-size: 14px; }
.source-empty-card span { font-size: 12px; }
.source-empty-card p { margin: 0; color: #dc2626; font-size: 12px; }
.preview-table { position: absolute; left: 19px; right: 19px; top: 313px; }
.preview-table__heading { height: 42px; display: flex; align-items: center; justify-content: space-between; }
.preview-table__heading strong { font-size: 14px; }
.preview-table__heading span { color: #63666d; font-size: 12px; }
.preview-table :deep(.el-table) { border-radius: 8px; --el-table-header-bg-color: #f7f8fa; --el-table-row-hover-bg-color: #f8faff; }
.preview-table :deep(.el-table th.el-table__cell) { color: #4b5563; font-size: 12px; font-weight: 600; }
.preview-table :deep(.el-table td.el-table__cell) { color: #27272a; font-size: 12px; }
.alternative-source-card { display: flex; align-items: center; gap: 16px; }
.alternative-source-card .el-select { width: 560px; }
.alternative-source-card p { margin: 0; color: #d96e0a; font-size: 12px; }
.blank-source-card { flex-direction: column; justify-content: center; align-items: flex-start; }
.blank-source-card strong { font-size: 14px; }
.side-card { width: 536px; padding: 17px 19px; }
.check-card { height: 260px; }
.check-card header { display: flex; align-items: center; justify-content: space-between; }
.check-card header > span { min-width: 112px; height: 26px; display: grid; place-items: center; border-radius: 6px; font-size: 12px; }
.check-card header .is-warning { color: #d96e0a; background: #fff8e9; }
.check-card header .is-success { color: #189858; background: #ecfaf1; }
.check-row { position: relative; height: 50px; display: grid; grid-template-columns: 22px 1fr 86px; gap: 12px; align-items: center; }
.check-row:first-of-type { margin-top: 10px; }
.check-row > i { width: 22px; height: 22px; display: grid; place-items: center; border-radius: 50%; color: #d96e0a; background: #fff8e9; font-size: 12px; font-style: normal; font-weight: 700; }
.check-row.is-ready > i { color: #189858; background: #ecfaf1; }
.check-row > div { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.check-row strong { font-size: 13px; font-weight: 500; }
.check-row small { overflow: hidden; color: #63666d; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.check-row > b { height: 26px; display: grid; place-items: center; border-radius: 6px; color: #d96e0a; background: #fff8e9; font-size: 12px; font-weight: 500; }
.check-row.is-ready > b { color: #189858; background: #ecfaf1; }
.maintenance-card { height: 198px; }
.maintenance-card > p, .result-card > p { margin: 11px 0 0; color: #63666d; font-size: 12px; }
.maintenance-tags { display: flex; flex-wrap: wrap; gap: 10px 8px; margin-top: 18px; }
.maintenance-tags span { min-height: 26px; display: grid; place-items: center; padding: 0 13px; border-radius: 6px; color: #2563eb; background: #eff4ff; font-size: 12px; }
.maintenance-note { height: 24px; display: flex; align-items: center; margin-top: 14px; padding: 0 12px; border-radius: 5px; color: #2563eb; background: #eff4ff; font-size: 11px; }
.result-card { height: 262px; }
.result-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 17px; }
.result-fields label > span, .result-preview > span { display: block; margin-bottom: 8px; color: #63666d; font-size: 11px; }
.result-fields label > strong { height: 42px; display: flex; align-items: center; padding: 0 12px; box-sizing: border-box; border: 1px solid #e5e7ea; border-radius: 6px; background: #fafafb; font-size: 13px; font-weight: 500; }
.result-preview { height: 48px; margin-top: 9px; padding: 5px 12px; box-sizing: border-box; border: 1px solid #e5e7ea; border-radius: 6px; background: #fafafb; }
.result-preview > span { display: block; margin-bottom: 2px; color: #63666d; font-size: 11px; }
.result-preview > strong { display: block; overflow: hidden; font-size: 13px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.result-actions { position: absolute; right: 19px; bottom: 15px; display: flex; gap: 8px; }
.result-actions .el-button:last-child { width: 168px; }
:deep(.el-input__wrapper), :deep(.el-select__wrapper), :deep(.el-button) { min-height: 32px; }

/* 230px 侧栏 + 64px 页面留白 + 1064px 主栏 + 16px 间距 + 536px 检查栏，
   低于 1920px 时双栏已无法完整容纳，改为上下排列，避免固定宽度子项侵入右栏。 */
@media (max-width: 1919px) and (min-width: 769px) {
  .bom-create-page { min-width: 0; }
  .content-grid { grid-template-columns: minmax(0, 1fr); }
  .side-card { width: 100%; }
}

/* BOM-V3-02：以 1920×1080 原型为基准的三步建立流程。 */
.bom-create-page { min-width: 0; min-height: max-content; padding: 0 28px 20px; background: var(--erp-page-background); color: #202124; }
.page-heading { height: 107px; padding: 15px 0 0; }
.page-heading h1 { margin: 0; font-family: "Noto Serif SC", "Songti SC", serif; font-size: 34px; line-height: 44px; letter-spacing: -.5px; }
.page-heading p { margin: 8px 0 0; color: #202124; font-size: 15px; line-height: 23px; }
.wizard-layout { display: grid; grid-template-columns: 212px minmax(0, 1fr); gap: 16px; }
.wizard-steps { min-height: 0; padding-top: 18px; }
.wizard-step { position: relative; width: 100%; min-height: 153px; display: grid; grid-template-columns: 38px 22px 1fr; align-items: start; gap: 9px; padding: 0; border: 0; color: #202124; background: transparent; font-family: inherit; text-align: left; }
.wizard-step:not(:last-child)::after { content: ""; position: absolute; left: 18px; top: 38px; width: 1px; height: 108px; background: #bab5ad; }
.wizard-step > i { width: 38px; height: 38px; display: grid; place-items: center; z-index: 1; box-sizing: border-box; border: 1px solid #bab5ad; border-radius: 50%; background: #fdfcf9; color: #202124; font-size: 14px; font-style: normal; }
.wizard-step > b { padding-top: 8px; color: #202124; font-size: 14px; font-weight: 500; }
.wizard-step > span { display: flex; flex-direction: column; gap: 9px; padding-top: 7px; }
.wizard-step strong { font-size: 16px; line-height: 25px; font-weight: 500; }
.wizard-step small { color: #68686a; font-size: 13px; line-height: 21px; }
.wizard-step.is-active > i { border-color: #d7491c; color: #fff; background: #d7491c; }
.wizard-step.is-active > b { color: #d7491c; }
.wizard-step.is-complete > i { border-color: #b7d9bd; color: #25783d; }
.wizard-step.is-complete > b { color: #25783d; }
.wizard-step:disabled { cursor: default; opacity: 1; }
.wizard-content { min-width: 0; }
.wizard-content.has-aside { display: grid; grid-template-columns: minmax(0, 1fr) 433px; gap: 12px; }
/* 为 56px 顶栏、28px 页面留白、107px 标题及 69px 底部操作区预留空间。 */
.content-card, .source-aside { box-sizing: border-box; min-width: 0; height: auto; min-height: min(814px, calc(100dvh - 260px)); overflow: visible; border: 1px solid #e3dfd7; border-radius: 5px; background: #fdfcf9; }
.content-card { padding: 18px 20px 20px; }
.content-card h2, .source-aside h2 { margin: 0; font-family: "Noto Serif SC", "Songti SC", serif; font-size: 21px; line-height: 32px; }
.section-note, .source-section > p, .source-aside > p { margin: 0; color: #68686a; font-size: 13px; line-height: 22px; }
.task-selection { position: relative; }
.task-search { width: 620px; margin-top: 20px; }
.task-table { margin-top: 12px; --el-table-header-bg-color: #f0ece3; --el-table-row-hover-bg-color: #fff8f2; --el-table-border-color: #e3dfd7; }
.task-table :deep(th.el-table__cell) { height: 40px; color: #68686a; font-size: 13px; font-weight: 500; }
.task-table :deep(td.el-table__cell) { height: 54px; color: #202124; font-size: 13px; }
.task-table :deep(td.task-action-column .cell) { padding-left: 8px !important; padding-right: 8px !important; }
.strong-tag { min-width: 56px; height: 24px; display: inline-flex; align-items: center; justify-content: center; padding: 0 8px; box-sizing: border-box; border: 0; border-radius: 999px; color: #faf9f5; background: #4f7d4b; font-family: "Noto Sans SC", sans-serif; font-size: 12px; line-height: 18px; font-weight: 500; white-space: nowrap; }
.strong-tag.is-success { background: #4f7d4b; }
.strong-tag.is-warning { background: #b8781e; }
.strong-tag.is-danger { background: #b53333; }
.strong-tag.is-neutral { background: #5e5d59; }
.task-select-action { min-width: 56px; height: 32px; padding: 0 8px; border: 0; border-radius: 5px; color: #c84e28; background: transparent; font-family: inherit; font-size: 13px; font-weight: 500; cursor: pointer; }
.task-select-action:hover, .task-select-action:focus-visible { color: #a83c1d; background: #fff4e6; outline: none; }
.info-strip { min-height: 42px; display: flex; align-items: center; margin-top: 14px; padding: 9px 14px; box-sizing: border-box; border-radius: 4px; color: #526776; background: #e5f0f5; font-size: 13px; line-height: 22px; }
.step-one-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; }
.step-one-actions .el-button { min-width: 116px; height: 36px; border-radius: 5px; color: #4d4c48; background: #fcfbf7; border-color: #ddd6c9; }
.method-content { padding-top: 16px; }
.method-list { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
.method-card { position: relative; width: 100%; height: 76px; display: grid; grid-template-columns: 18px 28px 1fr; align-items: center; gap: 15px; padding: 0 18px; box-sizing: border-box; border: 1px solid #e3dfd7; border-radius: 4px; color: #202124; background: #fdfcf9; font-family: inherit; text-align: left; cursor: pointer; }
.method-card.is-selected { border-color: #e87851; background: #fff1e8; }
.method-card .radio-dot { position: static; width: 14px; height: 14px; border: 1px solid #968f84; border-radius: 50%; }
.method-card.is-selected .radio-dot { border: 4px solid #d7491c; }
.method-card > i { width: 26px; height: 30px; display: grid; place-items: center; border: 1px solid #968f84; border-radius: 2px; color: #68686a; font-size: 13px; font-style: normal; }
.method-card > span:last-child { display: flex; flex-direction: column; gap: 6px; }
.method-card strong { font-size: 15px; line-height: 22px; font-weight: 500; }
.method-card small { color: #68686a; font-size: 12px; line-height: 19px; }
.source-section { margin-top: 18px; }
.source-section h3 { margin: 0; font-size: 18px; line-height: 28px; font-weight: 500; }
.source-upload { position: static; width: 100%; height: auto; display: block; margin-top: 10px; }
.source-upload :deep(.el-upload), .source-upload :deep(.el-upload-dragger) { width: 100%; height: auto; padding: 0; border: 0; background: transparent; }
.file-row { min-height: 64px; display: grid; grid-template-columns: 34px minmax(160px, 1fr) auto auto auto; align-items: center; gap: 14px; padding: 9px 14px; box-sizing: border-box; border: 1px solid #e3dfd7; border-radius: 4px; background: #fdfcf9; text-align: left; }
.file-row .file-icon { width: 28px; height: 34px; display: grid; place-items: center; border: 1px solid #5f9465; border-radius: 2px; color: #25783d; }
.file-row > div { min-width: 0; display: flex; flex-direction: column; gap: 5px; }
.file-row strong { overflow: hidden; font-size: 13px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.file-row small { color: #68686a; font-size: 12px; }
.upload-empty { height: 78px; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 6px; border: 1px dashed #c8c1b5; border-radius: 4px; }
.upload-empty strong { font-size: 14px; }
.upload-empty small { color: #68686a; font-size: 12px; }
.error-text { margin: 8px 0 0; color: #b42318; font-size: 12px; }
.preview-table { position: static; margin-top: 10px; }
.preview-heading { height: 32px; display: flex; align-items: center; justify-content: space-between; }
.preview-heading strong { font-size: 13px; font-weight: 500; }
.preview-heading span { color: #68686a; font-size: 12px; }
.preview-table :deep(.el-table) { --el-table-header-bg-color: #f0ece3; --el-table-border-color: #e3dfd7; }
.preview-table :deep(th.el-table__cell), .preview-table :deep(td.el-table__cell) { height: 36px; padding: 0; font-size: 12px; }
.alternative-source, .blank-source { margin-top: 10px; padding: 18px; border: 1px solid #e3dfd7; border-radius: 4px; background: #faf8f3; }
.alternative-source { display: flex; align-items: center; gap: 14px; }
.alternative-source .el-select { width: 520px; }
.alternative-source > span, .blank-source { color: #68686a; font-size: 13px; }
.review-content { padding-top: 16px; }
.review-meta { margin: 12px 0 14px; }
.review-meta > div { display: grid; grid-template-columns: 120px 1fr; min-height: 36px; align-items: center; }
.review-meta dt { color: #68686a; font-size: 13px; }
.review-meta dd { margin: 0; font-size: 13px; }
.quantity-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.quantity-table th, .quantity-table td { height: 42px; padding: 0 15px; border: 1px solid #e3dfd7; text-align: left; }
.quantity-table th { color: #68686a; background: #f0ece3; font-weight: 500; }
.quantity-table .warning { color: #b8781e; font-weight: 500; }
.reason-field { display: block; margin-top: 16px; }
.reason-field > span { display: block; margin-bottom: 8px; color: #68686a; font-size: 12px; }
.reason-field > span > span { color: #d7491c; }
.source-aside { padding: 17px 23px 20px; }
.source-list { margin: 12px 0 0; }
.source-list > div { min-height: 36px; display: grid; grid-template-columns: 148px minmax(0, 1fr); align-items: center; font-size: 14px; line-height: 22px; }
.source-list dt { color: #68686a; }
.source-list dd { min-width: 0; margin: 0; overflow: hidden; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.aside-divider { height: 1px; margin: 12px 0 13px; background: #e3dfd7; }
.check-item { min-height: 64px; display: grid; grid-template-columns: 28px 1fr; gap: 13px; align-items: start; padding-top: 9px; }
.check-item > i { width: 28px; height: 28px; display: grid; place-items: center; border-radius: 50%; color: #b8781e; background: #fae8c6; font-size: 13px; font-style: normal; font-weight: 700; }
.check-item.is-ok > i { color: #25783d; background: #dcefdc; }
.check-item > span { display: flex; flex-direction: column; gap: 3px; }
.check-item strong { font-size: 14px; line-height: 23px; font-weight: 500; }
.check-item small { color: #68686a; font-size: 12px; line-height: 20px; }
.wizard-actions { position: relative; z-index: 3; height: 64px; display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin: 5px 0 0 228px; padding: 0 18px; box-sizing: border-box; border: 1px solid #e3dfd7; border-radius: 4px; background: #fdfcf9; }
.wizard-actions .el-button:first-child { min-width: 160px; }
.wizard-actions .el-button:last-child { min-width: 240px; }
:deep(.el-button--primary:not(.is-disabled)) { --el-button-bg-color: #d7491c; --el-button-border-color: #d7491c; --el-button-hover-bg-color: #c83f14; --el-button-hover-border-color: #c83f14; color: #fff; background: #d7491c; border-color: #d7491c; }
:deep(.el-input__wrapper), :deep(.el-select__wrapper), :deep(.el-button) { min-height: 36px; border-radius: 4px; }

@media (max-width: 1500px) {
  .wizard-layout { grid-template-columns: 190px minmax(0, 1fr); }
  .wizard-content.has-aside { grid-template-columns: minmax(0, 1fr); }
  .content-card, .source-aside { height: auto; min-height: 560px; overflow: visible; }
  .source-aside { margin-top: 12px; }
  .wizard-actions { margin: 12px 0 0 206px; }
}

@media (max-width: 900px) {
  .bom-create-page { padding: 0 16px 20px; }
  .wizard-layout { display: block; }
  .wizard-steps { min-height: 0; display: grid; grid-template-columns: repeat(3, 1fr); margin-bottom: 12px; padding: 0; }
  .wizard-step { min-height: 76px; grid-template-columns: 34px 1fr; }
  .wizard-step > b { display: none; }
  .wizard-step:not(:last-child)::after { left: 34px; top: 18px; width: calc(100% - 30px); height: 1px; }
  .wizard-step > span { padding-right: 8px; }
  .wizard-step small { display: none; }
  .task-search { width: 100%; }
  .wizard-actions { margin-left: 0; }
}
</style>
