<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { createClientUuid } from '@/utils/clientUuid'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { useSampleUnsavedChanges } from '@/composables/useSampleUnsavedChanges'
import { buildSampleReportingPayload } from '@/utils/sampleFormEditing'
import { useAuthStore } from '@/stores/auth'

import {
  fetchSample,
  fetchSampleFormOptions,
  patchSampleForm,
  submitSampleForm,
} from '@/api/samples'
import type {
  SampleDetail,
  SampleFormOptions,
  SampleRequestFormInput,
} from '@/types/sample'
import SampleSection from '@/components/samples/SampleSection.vue'
import SampleStatusTag from '@/components/samples/SampleStatusTag.vue'
import titleLeft from '@/assets/samples/sample-title-left.svg'
import titleRibbon from '@/assets/samples/sample-title-ribbon.svg'
import titleRight from '@/assets/samples/sample-title-right.svg'

interface DetailDraft {
  id?: string
  displayUuid: string
  color_card: string
  product_color_id: string
  color_code: string
  sample_quantity: number | null
  tolerance: string
  notes: string
  cutting_reported_quantity: number | null
  metalwork_reported_quantity: number | null
  cutting_completed: boolean
  metalwork_completed: boolean
}

interface SamplingDetailDraft {
  id?: string
  clientKey: string
  template_key: string
  detail_type: string
  category_label: string
  is_selected: boolean
  description: string
  imageFile: File | null
  existingImageName: string
}

interface ProductDraft {
  id?: string
  clientKey: string
  source_inquiry_item_id: string | null
  source_quotation_line_id: string | null
  category_id: string
  product_name: string
  specification: string
  taskFile: File | null
  existingTaskName: string
  length_cm: string
  armrest_width_cm: string
  seat_width_cm: string
  back_height_cm: string
  seat_height_cm: string
  details: DetailDraft[]
  samplingDetails: SamplingDetailDraft[]
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const loading = ref(true)
const submitting = ref(false)
const errorMessage = ref('')
const options = ref<SampleFormOptions | null>(null)
const existingSample = ref<SampleDetail | null>(null)
const etag = ref('')
const products = ref<ProductDraft[]>([])
const fullscreenProductKey = ref('')
const idempotencyKey = createClientUuid()
const initialSnapshot = ref('')
const saved = ref(false)
const samplingDropdownPortal = document.createElement('div')
samplingDropdownPortal.className = 'sampling-dropdown-portal'
document.body.appendChild(samplingDropdownPortal)

const sampleId = computed(() => typeof route.params.sampleId === 'string' ? route.params.sampleId : '')
const isEditing = computed(() => Boolean(sampleId.value))
const editMode = computed(() => existingSample.value?.edit_capabilities?.mode || 'READ_ONLY')
const canSave = computed(() => !isEditing.value
  ? auth.hasPermission('samples.add_samplerequest')
  : editMode.value === 'REPORT_ONLY' ? ['productionreport_sample','metalreport_sample','cuttingreport_sample'].some(code=>auth.moduleCan('access_control.'+code,'samples.change_samplerequest',existingSample.value))
  : auth.moduleCan(editMode.value === 'COMPLETE' ? 'samples.complete_sample_requirements' : 'samples.change_samplerequest', editMode.value === 'COMPLETE' ? 'samples.complete_sample_requirements' : 'samples.change_samplerequest', existingSample.value))
const fullEditable = computed(() => canSave.value && (!isEditing.value || Boolean(existingSample.value?.edit_capabilities?.can_full_edit)))
const reportingEditable = computed(() => canSave.value && (!isEditing.value || Boolean(existingSample.value?.edit_capabilities?.can_report_edit)))
const canEditStage = (stage: 'metal'|'cutting') => reportingEditable.value && (!auth.user?.module_access_enabled || ['productionreport_sample',stage+'report_sample'].some(code=>auth.moduleCan('access_control.'+code,'samples.change_samplerequest',existingSample.value ?? undefined)))
const metalFieldsEditable = computed(() => canEditStage('metal'))
const cuttingFieldsEditable = computed(() => canEditStage('cutting'))
const sourceLocked = computed(() => Boolean(existingSample.value?.source_inquiry || existingSample.value?.source_quotation_version))
const formalNumber = computed(() => {
  if (existingSample.value && editMode.value !== 'COMPLETE') return existingSample.value.request_number
  return form.manual_request_number.trim()
    ? `HTS-${form.manual_request_number.trim().toUpperCase()}`
    : 'HTS-（完善提交时生成）'
})
const isCompleting = computed(() => isEditing.value && editMode.value === 'COMPLETE')
const pageTitle = computed(() => isCompleting.value ? '完善样品需求' : isEditing.value ? '编辑打样申请' : '创建打样申请')
const editHint = computed(() => !reportingEditable.value
  ? '当前申请或账号仅可查看，不能保存修改。'
  : editMode.value === 'REPORT_ONLY'
    ? '当前环节可填写报工数量、完成情况和特殊说明。'
    : '按分区完善申请，保存后返回申请详情。')

const today = localDate(new Date())
const form = reactive({
  manual_request_number: '',
  customer_account_id: '',
  customer_contact_id: '' as string | null,
  owner_employee_id: '',
  shipping_method: '',
  order_date: '',
  sample_due_date: '',
  delivery_batch: '',
  sample_type: '',
  is_repeat_order: null as boolean | null,
  submitted_on: today,
  purpose: '',
})

function snapshot() {
  return JSON.stringify({ form, products: products.value })
}
const dirty = computed(() => !saved.value && Boolean(initialSnapshot.value) && (
  initialSnapshot.value !== snapshot() || products.value.some(product => product.taskFile || product.samplingDetails.some(detail => detail.imageFile))
))
useSampleUnsavedChanges(() => dirty.value, '离开样品编辑页')

function localDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function newDetail(): DetailDraft {
  return {
    displayUuid: createClientUuid(),
    color_card: '',
    product_color_id: '',
    color_code: '',
    sample_quantity: null,
    tolerance: 'NONE',
    notes: '',
    cutting_reported_quantity: null,
    metalwork_reported_quantity: null,
    cutting_completed: false,
    metalwork_completed: false,
  }
}

function newSamplingDetail(seed?: Partial<SamplingDetailDraft>): SamplingDetailDraft {
  return {
    clientKey: createClientUuid(),
    template_key: '',
    detail_type: '',
    category_label: '',
    is_selected: true,
    description: '',
    imageFile: null,
    existingImageName: '',
    ...seed,
  }
}

function defaultSamplingDetails(): SamplingDetailDraft[] {
  return (options.value?.sampling_detail_template || []).map((item) => newSamplingDetail({
    template_key: item.key,
    detail_type: item.type,
    category_label: item.category,
  }))
}

function newProduct(seed?: Partial<ProductDraft>): ProductDraft {
  return {
    clientKey: createClientUuid(),
    source_inquiry_item_id: null,
    source_quotation_line_id: null,
    category_id: '',
    product_name: '',
    specification: '',
    taskFile: null,
    existingTaskName: '',
    length_cm: '',
    armrest_width_cm: '',
    seat_width_cm: '',
    back_height_cm: '',
    seat_height_cm: '',
    details: [newDetail()],
    samplingDetails: isCompleting.value ? [] : defaultSamplingDetails(),
    ...seed,
  }
}

function colorOptions(detail: DetailDraft) {
  return options.value?.colors.filter((color) => color.color_card === detail.color_card) || []
}

function selectedColor(detail: DetailDraft) {
  return options.value?.colors.find((color) => color.id === detail.product_color_id) || null
}

function productTotal(product: ProductDraft) {
  return product.details.reduce((sum, detail) => sum + (Number(detail.sample_quantity) || 0), 0)
}

function resetColor(detail: DetailDraft) {
  detail.product_color_id = ''
  detail.color_code = ''
}

function setColorCode(detail: DetailDraft) {
  detail.color_code = selectedColor(detail)?.color_code || ''
}

function addProduct() {
  if (!fullEditable.value) return
  products.value.push(newProduct())
}

async function removeProduct(index: number) {
  if (!fullEditable.value || products.value.length <= 1) return
  try {
    await ElMessageBox.confirm('确定删除这个产品区块及其全部样品明细吗？', '删除产品', { type: 'warning' })
    products.value.splice(index, 1)
  } catch {
    // 用户取消删除。
  }
}

function addDetail(product: ProductDraft) {
  if (fullEditable.value) product.details.push(newDetail())
}

function removeDetail(product: ProductDraft, index: number) {
  if (fullEditable.value && product.details.length > 1) product.details.splice(index, 1)
}

function addSamplingDetail(product: ProductDraft) {
  if (fullEditable.value) product.samplingDetails.push(newSamplingDetail())
}

function removeSamplingDetail(product: ProductDraft, index: number) {
  if (fullEditable.value && product.samplingDetails.length > 1) product.samplingDetails.splice(index, 1)
}

function syncSamplingFullscreen() {
  const element = document.fullscreenElement as HTMLElement | null
  fullscreenProductKey.value = element?.dataset.samplingProductKey || ''
  if (!element && samplingDropdownPortal.parentElement !== document.body) {
    document.body.appendChild(samplingDropdownPortal)
  }
}

async function toggleSamplingFullscreen(product: ProductDraft) {
  const panel = Array.from(document.querySelectorAll<HTMLElement>('[data-sampling-product-key]'))
    .find((element) => element.dataset.samplingProductKey === product.clientKey)
  if (!panel) {
    ElMessage.error('未找到当前产品的打样信息明细。')
    return
  }
  try {
    if (document.fullscreenElement === panel) {
      await document.exitFullscreen()
      return
    }
    if (!panel.requestFullscreen) {
      ElMessage.warning('当前浏览器不支持全屏显示。')
      return
    }
    panel.appendChild(samplingDropdownPortal)
    await panel.requestFullscreen()
  } catch {
    document.body.appendChild(samplingDropdownPortal)
    ElMessage.error('无法进入全屏，请检查浏览器权限后重试。')
  }
}

function selectTaskFile(product: ProductDraft, file: File | undefined) {
  if (!fullEditable.value) return
  product.taskFile = file || null
}

function selectSamplingImage(detail: SamplingDetailDraft, file: File | undefined) {
  if (!fullEditable.value) return
  detail.imageFile = file || null
}

function flattenError(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value.flatMap(flattenError)
  if (value && typeof value === 'object') return Object.values(value).flatMap(flattenError)
  return []
}

function apiError(error: unknown): string {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务后重试。'
  if (error.response.status === 412) return '样品数据已被其他人更新，请重新加载后再提交。'
  if (error.response.status === 428) return '缺少数据版本，请重新加载后重试。'
  const data = error.response.data as { error?: { message?: string; field_errors?: unknown }; detail?: string }
  const fields = flattenError(data.error?.field_errors)
  return fields[0] || data.error?.message || data.detail || '提交失败，请检查填写内容。'
}

function applySample(sample: SampleDetail) {
  existingSample.value = sample
  Object.assign(form, {
    manual_request_number: sample.manual_request_number || '',
    customer_account_id: sample.customer_account,
    customer_contact_id: sample.customer_contact,
    owner_employee_id: sample.owner?.id || '',
    shipping_method: sample.shipping_method || '',
    order_date: sample.order_date || '',
    sample_due_date: sample.sample_due_date || '',
    delivery_batch: sample.delivery_batch || '',
    sample_type: sample.sample_type,
    is_repeat_order: sample.is_repeat_order ?? null,
    submitted_on: sample.submitted_on || '',
    purpose: sample.purpose || '',
  })
  products.value = (sample.products || []).map((product) => ({
    id: product.id,
    clientKey: product.id,
    source_inquiry_item_id: product.source_inquiry_item_id,
    source_quotation_line_id: product.source_quotation_line_id,
    category_id: product.category_id || '',
    product_name: product.product_name,
    specification: product.specification,
    taskFile: null,
    existingTaskName: product.task_sheet_file_name,
    length_cm: product.length_cm || '',
    armrest_width_cm: product.armrest_width_cm || '',
    seat_width_cm: product.seat_width_cm || '',
    back_height_cm: product.back_height_cm || '',
    seat_height_cm: product.seat_height_cm || '',
    details: product.details.map((detail) => ({
      id: detail.id,
      displayUuid: detail.id,
      color_card: detail.color_card,
      product_color_id: detail.product_color_id || '',
      color_code: detail.color_code || '',
      sample_quantity: detail.sample_quantity,
      tolerance: detail.tolerance,
      notes: detail.notes,
      cutting_reported_quantity: detail.cutting_reported_quantity,
      metalwork_reported_quantity: detail.metalwork_reported_quantity,
      cutting_completed: detail.cutting_completed,
      metalwork_completed: detail.metalwork_completed,
    })),
    samplingDetails: (product.sampling_details || []).length
      ? (product.sampling_details || []).map((detail) => newSamplingDetail({
          id: detail.id,
          clientKey: detail.id,
          template_key: detail.template_key,
          detail_type: detail.detail_type,
          category_label: detail.category_label,
          is_selected: detail.is_selected,
          description: detail.description,
          existingImageName: detail.image_file_name,
        }))
      : fullEditable.value && !isCompleting.value ? defaultSamplingDetails() : [],
  }))
}

async function loadPage() {
  const legacySourceType = route.query.sourceType
  const legacySourceId = typeof route.query.sourceId === 'string' ? route.query.sourceId : ''
  if (!isEditing.value && (legacySourceType === 'inquiry' || legacySourceType === 'quotation') && legacySourceId) {
    await router.replace({
      name: 'sample-new',
      query: { sourceType: legacySourceType, sourceId: legacySourceId },
    })
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    options.value = await fetchSampleFormOptions()
    form.owner_employee_id = options.value.current_maker.id
    if (isEditing.value) {
      const result = await fetchSample(sampleId.value)
      etag.value = result.etag
      applySample(result.data)
    } else {
      products.value = [newProduct()]
    }
    initialSnapshot.value = snapshot()
    saved.value = false
  } catch (error) {
    errorMessage.value = apiError(error)
  } finally {
    loading.value = false
  }
}

function validateForm(): string {
  if (editMode.value === 'REPORT_ONLY' && existingSample.value) {
    try { buildSampleReportingPayload(existingSample.value, products.value, form.purpose) }
    catch (error) { return apiError(error) }
    return ''
  }
  if (!form.manual_request_number.trim()) return '请填写手写打样单号。'
  if (form.manual_request_number.trim().toUpperCase().startsWith('HTS-')) return '手写打样单号不要包含 HTS- 前缀。'
  if (!form.customer_account_id || !form.owner_employee_id) return '请选择客户和业务员。'
  if (!form.shipping_method || !form.delivery_batch || !form.sample_type || form.is_repeat_order === null) {
    return '请选择寄送方式、交货批次、样品类型和是否翻单。'
  }
  if (!form.order_date || !form.sample_due_date || !form.submitted_on) return '请填写下单日期、样品交期和提交日期。'
  if (!products.value.length) return '请至少保留一个产品区块。'
  for (const [index, product] of products.value.entries()) {
    if (!product.category_id || !product.product_name.trim() || !product.specification.trim()) {
      return `请补齐产品 ${index + 1} 的类别、名称和规格。`
    }
    if (!product.taskFile && !product.existingTaskName) return `请上传产品 ${index + 1} 的任务单图片。`
    if (!product.details.length) return `产品 ${index + 1} 至少需要一条样品明细。`
    for (const detail of product.details) {
      if (!detail.color_card || !detail.product_color_id || !detail.color_code.trim()) {
        return `请补齐产品 ${index + 1} 明细的色卡、颜色和色号。`
      }
      const sampleQuantity = Number(detail.sample_quantity)
      if (!Number.isInteger(sampleQuantity) || sampleQuantity <= 0) return '打样数量必须是大于 0 的整数。'
      const cuttingReportedQuantity = detail.cutting_reported_quantity ?? 0
      const metalworkReportedQuantity = detail.metalwork_reported_quantity ?? 0
      if (!Number.isInteger(cuttingReportedQuantity) || cuttingReportedQuantity < 0 || cuttingReportedQuantity > sampleQuantity) {
        return '裁剪报工数量必须在 0 到打样数量之间。'
      }
      if (!Number.isInteger(metalworkReportedQuantity) || metalworkReportedQuantity < 0 || metalworkReportedQuantity > sampleQuantity) {
        return '金工报工数量必须在 0 到打样数量之间。'
      }
    }
    if (!isCompleting.value && !product.samplingDetails.length) return `产品 ${index + 1} 至少需要一条打样信息明细。`
    for (const detail of product.samplingDetails) {
      if (!detail.detail_type.trim()) return `请填写产品 ${index + 1} 打样信息明细的类型。`
    }
  }
  return ''
}

function payload(): SampleRequestFormInput {
  if (editMode.value === 'REPORT_ONLY' && existingSample.value) {
    return buildSampleReportingPayload(existingSample.value, products.value, form.purpose)
  }
  return {
    manual_request_number: form.manual_request_number.trim().toUpperCase(),
    customer_account_id: form.customer_account_id,
    customer_contact_id: form.customer_contact_id || null,
    owner_employee_id: form.owner_employee_id,
    shipping_method: form.shipping_method,
    order_date: form.order_date,
    sample_due_date: form.sample_due_date,
    delivery_batch: form.delivery_batch,
    sample_type: form.sample_type,
    is_repeat_order: form.is_repeat_order === true,
    submitted_on: form.submitted_on,
    purpose: form.purpose.trim(),
    idempotency_key: isEditing.value ? undefined : idempotencyKey,
    products: products.value.map((product) => ({
      id: product.id,
      client_key: product.clientKey,
      source_inquiry_item_id: product.source_inquiry_item_id,
      source_quotation_line_id: product.source_quotation_line_id,
      category_id: product.category_id,
      product_name: product.product_name.trim(),
      specification: product.specification.trim(),
      length_cm: product.length_cm || null,
      armrest_width_cm: product.armrest_width_cm || null,
      seat_width_cm: product.seat_width_cm || null,
      back_height_cm: product.back_height_cm || null,
      seat_height_cm: product.seat_height_cm || null,
      details: product.details.map((detail) => ({
        id: detail.id,
        product_color_id: detail.product_color_id,
        color_code: detail.color_code.trim(),
        sample_quantity: Number(detail.sample_quantity),
        tolerance: detail.tolerance,
        notes: detail.notes.trim(),
        cutting_reported_quantity: Number(detail.cutting_reported_quantity ?? 0),
        metalwork_reported_quantity: Number(detail.metalwork_reported_quantity ?? 0),
        cutting_completed: detail.cutting_completed,
        metalwork_completed: detail.metalwork_completed,
      })),
      sampling_details: product.samplingDetails.map((detail) => ({
        id: detail.id,
        client_key: detail.clientKey,
        template_key: detail.template_key,
        detail_type: detail.detail_type.trim(),
        category_label: detail.category_label.trim(),
        is_selected: detail.is_selected,
        description: detail.description.trim(),
      })),
    })),
  }
}

async function submit() {
  if (loading.value || submitting.value || errorMessage.value || !reportingEditable.value) return
  if (isEditing.value && !etag.value) {
    ElMessage.error('缺少版本信息，请重新加载后再保存。')
    return
  }
  const validationMessage = validateForm()
  if (validationMessage) {
    ElMessage.warning(validationMessage)
    return
  }
  const taskFiles = fullEditable.value ? Object.fromEntries(products.value.map((product) => [product.clientKey, product.taskFile])) : {}
  const samplingImageFiles = fullEditable.value ? Object.fromEntries(
    products.value.flatMap((product) => product.samplingDetails.map((detail) => [detail.clientKey, detail.imageFile])),
  ) : {}
  submitting.value = true
  try {
    const result = isEditing.value
      ? await patchSampleForm(sampleId.value, payload(), taskFiles, samplingImageFiles, etag.value)
      : await submitSampleForm(payload(), taskFiles, samplingImageFiles)
    saved.value = true
    ElMessage.success(isCompleting.value ? '样品需求已完善并提交。' : isEditing.value ? '样品需求已更新。' : '样品需求已提交。')
    await router.replace({ name: 'sample-detail', params: { sampleId: result.data.id } })
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    submitting.value = false
  }
}

function cancel() {
  void router.push(isEditing.value && sampleId.value
    ? { name: 'sample-detail', params: { sampleId: sampleId.value } }
    : { name: 'samples' })
}

onMounted(() => {
  document.addEventListener('fullscreenchange', syncSamplingFullscreen)
  void loadPage()
})
onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', syncSamplingFullscreen)
  samplingDropdownPortal.remove()
})
</script>

<template>
  <section v-loading="loading" class="sample-form-page" :class="{ 'sample-form-page--completion': isCompleting }" :aria-label="pageTitle" :data-visual-reference="isCompleting ? '724:8929' : '676:9438'">
    <template v-if="!errorMessage">
      <div class="form-body">
        <header class="edit-heading form-title-band">
          <img :src="titleLeft" alt="" class="title-decoration">
          <div class="title-ribbon"><img :src="titleRibbon" alt=""><h1>{{ pageTitle }}</h1></div>
          <img :src="titleRight" alt="" class="title-decoration">
        </header>

        <SampleSection title="基础信息" class="edit-basic-section">
        <ElForm label-position="top">
          <div class="basic-grid">
            <ElFormItem label="手写打样单号" required><ElInput v-model="form.manual_request_number" placeholder="请输入打样单号" :disabled="(isEditing && !isCompleting) || !fullEditable" maxlength="46" @blur="form.manual_request_number = form.manual_request_number.trim().toUpperCase()" /></ElFormItem>
            <ElFormItem label="生成打样单号"><ElInput :model-value="formalNumber" placeholder="HTS-（实时生成）" disabled /></ElFormItem>
            <ElFormItem label="客户" required><ElSelect v-model="form.customer_account_id" placeholder="请选择客户" :disabled="sourceLocked || isEditing || !fullEditable" filterable><ElOption v-if="existingSample && !options?.customers.some((item) => item.id === existingSample?.customer_account)" :label="existingSample.customer_name" :value="existingSample.customer_account" /><ElOption v-for="item in options?.customers" :key="item.id" :label="item.account_name" :value="item.id" /></ElSelect></ElFormItem>
            <ElFormItem label="业务员" required><ElSelect v-model="form.owner_employee_id" placeholder="请选择业务员" :disabled="isCompleting || sourceLocked || !fullEditable" filterable><ElOption v-for="item in options?.salespeople" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem>
            <ElFormItem label="寄送方式" required><ElSelect v-model="form.shipping_method" placeholder="邮寄 / 其他" :disabled="!fullEditable"><ElOption v-for="item in options?.shipping_methods" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
            <ElFormItem label="下单日期" required><ElDatePicker v-model="form.order_date" type="date" value-format="YYYY-MM-DD" placeholder="请选择日期" :disabled="!fullEditable" /></ElFormItem>
            <ElFormItem label="样品交期" required><ElDatePicker v-model="form.sample_due_date" type="date" value-format="YYYY-MM-DD" placeholder="请选择日期" :disabled="!fullEditable" /></ElFormItem>
            <ElFormItem label="交货批次" required><ElSelect v-model="form.delivery_batch" placeholder="一次交货 / 分批交货" :disabled="!fullEditable"><ElOption v-for="item in options?.delivery_batches" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
            <ElFormItem label="样品类型" required><ElSelect v-model="form.sample_type" placeholder="请选择样品类型" :disabled="!fullEditable"><ElOption v-for="item in options?.sample_types" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
            <ElFormItem label="是否翻单" required><ElSelect v-model="form.is_repeat_order" placeholder="否 / 是" :disabled="!fullEditable"><ElOption v-for="item in options?.repeat_options" :key="String(item.value)" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
            <ElFormItem label="制单人"><ElInput :model-value="existingSample?.created_by?.display_name || options?.current_maker.display_name || ''" placeholder="当前登录用户" disabled /></ElFormItem>
            <ElFormItem label="提交日期" required><ElDatePicker v-model="form.submitted_on" type="date" value-format="YYYY-MM-DD" placeholder="请选择日期" :disabled="!fullEditable" /></ElFormItem>
          </div>
        </ElForm>
        </SampleSection>

        <SampleSection title="样品信息" class="edit-products-section">
        <section class="product-list">
          <ElEmpty v-if="!loading && !products.length" description="当前申请暂无产品信息" :image-size="72"><ElButton v-if="fullEditable" @click="addProduct">添加产品</ElButton></ElEmpty>
          <article v-for="(product, productIndex) in products" :key="product.clientKey" class="product-block">
            <header class="block-toolbar product-toolbar">
              <h3>产品 {{ productIndex + 1 }}</h3>
              <div v-if="fullEditable" class="toolbar-actions">
                <ElButton v-if="productIndex > 0" text type="danger" @click="removeProduct(productIndex)">删除产品</ElButton>
                <ElButton @click="addProduct">＋ 添加产品</ElButton>
              </div>
            </header>

            <ElForm label-position="top">
              <div class="product-grid">
                <ElFormItem label="产品类别" required><ElSelect v-model="product.category_id" placeholder="请选择产品类别" :disabled="!fullEditable" filterable><ElOption v-for="item in options?.categories" :key="item.id" :label="item.category_name" :value="item.id" /></ElSelect></ElFormItem>
                <ElFormItem label="产品名称" required><ElInput v-model="product.product_name" placeholder="请输入产品名称" :disabled="!fullEditable" maxlength="500" /></ElFormItem>
                <ElFormItem label="规格" required><ElInput v-model="product.specification" placeholder="请输入规格" :disabled="!fullEditable" maxlength="2000" /></ElFormItem>
                <ElFormItem label="任务单" required>
                  <ElUpload class="task-upload" :auto-upload="false" :show-file-list="false" :limit="1" accept=".jpg,.jpeg,.png,.gif,.webp" :disabled="!fullEditable" :on-change="(file: UploadFile) => selectTaskFile(product, file.raw)" :on-exceed="(files: File[]) => selectTaskFile(product, files[0])">
                    <button type="button" class="task-upload__trigger" :disabled="!fullEditable">＋ {{ product.taskFile?.name || product.existingTaskName || '选择图片' }}</button>
                  </ElUpload>
                </ElFormItem>
                <ElFormItem label="总打样数量"><ElInput :model-value="`${productTotal(product)} PCS`" disabled /></ElFormItem>
                <ElFormItem label="长（cm）"><ElInput v-model="product.length_cm" placeholder="请输入" :disabled="!fullEditable" /></ElFormItem>
                <ElFormItem label="扶手宽（cm）"><ElInput v-model="product.armrest_width_cm" placeholder="请输入" :disabled="!fullEditable" /></ElFormItem>
                <ElFormItem label="坐宽（cm）"><ElInput v-model="product.seat_width_cm" placeholder="请输入" :disabled="!fullEditable" /></ElFormItem>
                <ElFormItem label="背高（cm）"><ElInput v-model="product.back_height_cm" placeholder="请输入" :disabled="!fullEditable" /></ElFormItem>
                <ElFormItem label="坐高（cm）"><ElInput v-model="product.seat_height_cm" placeholder="请输入" :disabled="!fullEditable" /></ElFormItem>
              </div>
            </ElForm>

            <header class="block-toolbar detail-toolbar">
              <h3>样品明细</h3>
              <ElButton v-if="fullEditable" @click="addDetail(product)">＋ 添加明细</ElButton>
            </header>

            <div class="detail-table-wrap">
              <div class="detail-table">
                <div class="detail-table__header">
                  <span>序号</span><span>产品类别</span><span>产品名称</span><span>规格</span><span class="required">色卡</span><span class="required">颜色</span><span class="required">色号</span><span class="required">打样数量</span><span class="required">公差值</span><span>备注</span><span>裁剪报工</span><span>金工报工</span><span>裁剪完成</span><span>金工完成</span>
                </div>
                <div v-for="(detail, detailIndex) in product.details" :key="detail.displayUuid" class="detail-table__row">
                  <div class="detail-serial">
                    <span>{{ detailIndex + 1 }}</span>
                    <button v-if="fullEditable && product.details.length > 1" type="button" title="删除明细" @click="removeDetail(product, detailIndex)">×</button>
                  </div>
                  <ElSelect v-model="product.category_id" placeholder="请选择" :disabled="!fullEditable" filterable><ElOption v-for="item in options?.categories" :key="item.id" :label="item.category_name" :value="item.id" /></ElSelect>
                  <ElInput v-model="product.product_name" placeholder="请输入" :disabled="!fullEditable" maxlength="500" />
                  <ElInput v-model="product.specification" placeholder="请输入" :disabled="!fullEditable" maxlength="2000" />
                  <ElSelect v-model="detail.color_card" placeholder="请选择" :disabled="!fullEditable" filterable @change="resetColor(detail)"><ElOption v-for="card in options?.color_cards" :key="card" :label="card" :value="card" /></ElSelect>
                  <ElSelect v-model="detail.product_color_id" placeholder="请选择" :disabled="!fullEditable || !detail.color_card" filterable @change="setColorCode(detail)"><ElOption v-for="color in colorOptions(detail)" :key="color.id" :label="color.color_name" :value="color.id" /></ElSelect>
                  <ElInput v-model="detail.color_code" placeholder="请输入" :disabled="!fullEditable" maxlength="100" />
                  <ElInputNumber v-model="detail.sample_quantity" :controls="false" :disabled="!fullEditable" :min="1" :step="1" step-strictly placeholder="请输入" />
                  <ElSelect v-model="detail.tolerance" :disabled="!fullEditable"><ElOption v-for="item in options?.tolerances" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
                  <ElInput v-model="detail.notes" placeholder="请输入" :disabled="!fullEditable" maxlength="2000" />
                  <ElInputNumber v-model="detail.cutting_reported_quantity" :controls="false" :disabled="!cuttingFieldsEditable" :min="0" :max="detail.sample_quantity || 0" :step="1" step-strictly />
                  <ElInputNumber v-model="detail.metalwork_reported_quantity" :controls="false" :disabled="!metalFieldsEditable" :min="0" :max="detail.sample_quantity || 0" :step="1" step-strictly />
                  <ElSelect v-model="detail.cutting_completed" :disabled="!cuttingFieldsEditable"><ElOption label="否" :value="false" /><ElOption label="是" :value="true" /></ElSelect>
                  <ElSelect v-model="detail.metalwork_completed" :disabled="!metalFieldsEditable"><ElOption label="否" :value="false" /><ElOption label="是" :value="true" /></ElSelect>
                </div>
              </div>
            </div>

            <section v-if="!isCompleting && (fullEditable || product.samplingDetails.length)" :id="`sampling-detail-${product.clientKey}`" class="sampling-detail-panel" :data-sampling-product-key="product.clientKey">
              <header class="block-toolbar sampling-detail-toolbar">
                <div>
                  <h3>打样信息明细</h3>
                  <small>按产品填写类型、类别、描述和图片。</small>
                </div>
                <div class="sampling-detail-actions">
                  <ElButton v-if="fullEditable" @click="addSamplingDetail(product)">＋ 增加一条</ElButton>
                  <ElButton @click="toggleSamplingFullscreen(product)">{{ fullscreenProductKey === product.clientKey ? '退出全屏' : '全屏' }}</ElButton>
                </div>
              </header>

              <div class="sampling-table-wrap">
                <div class="sampling-table">
                  <div class="sampling-table__header">
                    <span>序号</span><span class="required">类型</span><span>类别项</span><span class="required">是否</span><span>描述</span><span>图片</span>
                  </div>
                  <div v-for="(detail, detailIndex) in product.samplingDetails" :key="detail.clientKey" class="sampling-table__row">
                    <div class="detail-serial">
                      <span>{{ detailIndex + 1 }}</span>
                      <button v-if="fullEditable && product.samplingDetails.length > 1" type="button" title="删除打样信息明细" @click="removeSamplingDetail(product, detailIndex)">×</button>
                    </div>
                    <ElInput v-model="detail.detail_type" placeholder="请输入类型" :disabled="!fullEditable" maxlength="100" />
                    <ElInput v-model="detail.category_label" placeholder="请输入类别项" :disabled="!fullEditable" maxlength="100" />
                    <ElSelect v-model="detail.is_selected" :append-to="samplingDropdownPortal" :disabled="!fullEditable"><ElOption label="是" :value="true" /><ElOption label="否" :value="false" /></ElSelect>
                    <ElInput v-model="detail.description" placeholder="请输入描述" :disabled="!fullEditable" maxlength="2000" />
                    <ElUpload class="sampling-image-upload" :auto-upload="false" :show-file-list="false" :limit="1" accept=".jpg,.jpeg,.png,.gif,.webp" :disabled="!fullEditable" :on-change="(file: UploadFile) => selectSamplingImage(detail, file.raw)" :on-exceed="(files: File[]) => selectSamplingImage(detail, files[0])">
                      <button type="button" class="sampling-image-trigger" :disabled="!fullEditable">{{ detail.imageFile?.name || detail.existingImageName || '＋ 选择图片' }}</button>
                    </ElUpload>
                  </div>
                  <div v-if="!product.samplingDetails.length" class="table-empty">暂无打样信息</div>
                </div>
              </div>
            </section>
          </article>
        </section>
        </SampleSection>

        <SampleSection title="特殊说明">
        <ElInput v-model="form.purpose" class="special-instructions" type="textarea" :rows="2" resize="none" maxlength="2000" :disabled="!reportingEditable" placeholder="请输入特殊说明" />
        </SampleSection>
        <p v-if="isCompleting && existingSample" class="completion-meta">需求编号 {{ existingSample.intake_number || existingSample.request_number }}<template v-if="existingSample.source_inquiry_number || existingSample.source_quotation_number"> · 来源 {{ existingSample.source_inquiry_number || existingSample.source_quotation_number }}</template> · 申请人 {{ existingSample.requested_by?.display_name || '未记录' }}<template v-if="existingSample.waiting_seconds != null"> · 已等待 {{ Math.floor(existingSample.waiting_seconds / 3600) }} 小时</template></p>
      </div>

      <footer class="form-actions"><div v-if="!loading && !isCompleting" class="form-state"><span v-if="existingSample" class="request-number">{{ existingSample.request_number }}</span><SampleStatusTag v-if="existingSample" :status="existingSample.status" :label="existingSample.status_display" /><p>{{ editHint }}</p></div><ElButton :disabled="submitting" @click="cancel">取消</ElButton><ElButton v-if="reportingEditable" type="primary" :disabled="loading" :loading="submitting" @click="submit">{{ isCompleting ? '完善并提交' : isEditing ? '保存修改' : '提交需求' }}</ElButton></footer>
    </template>
    <ElResult v-else class="load-error" icon="error" title="样品表单加载失败" :sub-title="errorMessage"><template #extra><ElButton type="primary" @click="loadPage">重新加载</ElButton><ElButton @click="cancel">返回</ElButton></template></ElResult>
  </section>
</template>

<style scoped lang="scss" src="./sampleForm.scss"></style>
