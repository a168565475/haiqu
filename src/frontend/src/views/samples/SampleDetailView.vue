<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { Document, Download, Refresh, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  approveSamplePmc,
  confirmSampleFinance,
  fetchSample,
  fetchSampleBusinessFile,
  transitionSample,
} from '@/api/samples'
import { useAuthStore } from '@/stores/auth'
import type { SampleDetail, SampleWorkflowRecord } from '@/types/sample'
import SampleStatusTag from '@/components/samples/SampleStatusTag.vue'
import SampleMaterialProgress from '@/components/samples/SampleMaterialProgress.vue'
import SampleProductionReportDialog from '@/components/samples/SampleProductionReportDialog.vue'
import SampleParameterImages from '@/components/samples/SampleParameterImages.vue'
import SampleMaterialApplicationInfo from '@/components/samples/SampleMaterialApplicationInfo.vue'
import SampleSection from '@/components/samples/SampleSection.vue'
import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'

type WorkflowDialog = 'finance'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const sample = ref<SampleDetail | null>(null)
const etag = ref('')
const reportVisible = ref(false)
const isApplication = computed(() => Boolean(sample.value?.application_actions?.is_application))
const canReportProduction = computed(() => Boolean(sample.value?.workflow_actions?.can_report_production && ['productionreport_sample','metalreport_sample','cuttingreport_sample'].some(code=>authStore.moduleCan('access_control.'+code,'samples.change_samplerequest',sample.value))))
const loading = ref(true)
const saving = ref(false)
const errorMessage = ref('')
const workflowDialog = ref<WorkflowDialog | null>(null)
const workflowNote = ref('')
const workflowFile = ref<File | null>(null)
const taskImageUrls = reactive<Record<string, string>>({})
let imageRequest = 0
let loadRequest = 0

const sampleId = computed(() => String(route.params.sampleId || ''))
const canInitiateMaterialIssue = computed(() => Boolean(sample.value && authStore.moduleCan('samples.edit_sample_materials', undefined, sample.value)))
const canConfirmMaterialIssue = computed(() => Boolean(sample.value && authStore.moduleCan('samples.review_sample_materials', undefined, sample.value)))

// 旧费用与寄送流程入口只按已有状态和权限开放；新材料状态不自动转入旧流程。
const canOpenFees = computed(() => Boolean(sample.value && authStore.moduleCan('samples.view_samplerequest', undefined, sample.value) && (
  sample.value.fee_records.length || sample.value.files?.some(file => file.file_role === 'FEE_EVIDENCE')
  || (['PENDING', 'PREPARING'].includes(sample.value.status) && authStore.moduleCan('samples.decide_sample_fee', undefined, sample.value))
)))
const canOpenFulfillment = computed(() => Boolean(sample.value && authStore.moduleCan('samples.view_samplerequest', undefined, sample.value)
  && (!sample.value.shipments.length || authStore.moduleCan('samples.view_sampleshipment', undefined, sample.value)) && (
    sample.value.shipments.length || sample.value.feedback.length
    || (['PREPARING', 'SHIPPED'].includes(sample.value.status)
      && authStore.moduleCan('samples.add_sampleshipment', undefined, sample.value) && authStore.moduleCan('samples.view_sampleshipment', undefined, sample.value))
    || (['DELIVERED', 'FEEDBACK_PENDING', 'CONFIRMED', 'COMPLETED'].includes(sample.value.status)
      && authStore.moduleCan('samples.add_samplefeedback', undefined, sample.value))
  )))

const statusSteps = computed(() => isApplication.value ? [
  { key: 'REQUEST_CREATED', label: '创建申请' },
  { key: 'DIRECTOR_APPROVED', label: '厂长确认' },
  { key: 'MATERIALS_READY', label: '用料齐备' },
  { key: 'MATERIAL_ISSUE', label: '样品领料' },
  { key: 'METALWORK_PARAMETERS', label: '金工参数' },
  { key: 'CUTTING_PARAMETERS', label: '裁剪参数' },
  { key: 'PRODUCTION_COMPLETED', label: '生产完成' },
  { key: 'WORKFLOW_FINISHED', label: '可入库' },
] : [
  { key: 'REQUEST_CREATED', label: '创建样品' },
  { key: 'REQUIREMENTS_COMPLETED', label: '完善样品' },
  { key: 'FINANCE_CONFIRMED', label: '财务确认' },
  { key: 'PMC_APPROVED', label: 'PMC 审核' },
  { key: 'METALWORK_PARAMETERS', label: '金工参数' },
  { key: 'CUTTING_PARAMETERS', label: '裁剪参数' },
  { key: 'WORKFLOW_FINISHED', label: '已结束' },
])

const activeStepIndex = computed(() => {
  const status = sample.value?.status
  if (isApplication.value) return ({ DIRECTOR_REVIEW: 1, APPLICATION_RETURNED: 0, PENDING_COMPLETION: 2, MATERIALS_PENDING: 2, WAREHOUSE_PENDING: 2, PROCUREMENT_PENDING: 2, MATERIALS_READY: 2, MATERIAL_ISSUE_PENDING: 3, MATERIAL_ISSUE_REVIEW: 3, METALWORK_PENDING: 4, CUTTING_PENDING: 5, PRODUCTION_PENDING: 6, FINISHED: 7 } as Record<string, number>)[status || ''] ?? -1
  const indexByStatus: Record<string, number> = {
    DRAFT: 0,
    PENDING_COMPLETION: 1,
    PENDING: 2,
    PMC_REVIEW: 3,
    METALWORK_PENDING: 4,
    CUTTING_PENDING: 5,
    FINISHED: 6,
  }
  return indexByStatus[status || ''] ?? -1
})

const workflowDialogVisible = computed({
  get: () => workflowDialog.value !== null,
  set: (visible: boolean) => { if (!visible && !saving.value) workflowDialog.value = null },
})
const workflowStageSet = computed<Set<string>>(() => new Set((sample.value?.workflow_records || []).map((item) => item.stage)))
const parameterRecords = computed(() => (sample.value?.workflow_records || []).filter((item) => (
  item.stage === 'METALWORK_PARAMETERS' || item.stage === 'CUTTING_PARAMETERS'
)).sort((left, right) => Number(left.stage === 'CUTTING_PARAMETERS') - Number(right.stage === 'CUTTING_PARAMETERS')))
const financeRecord = computed(() => findWorkflowRecord('FINANCE_CONFIRMED'))
const hasReportActivity = computed(() => (sample.value?.items || []).some((item) => (
  (item.cutting_reported_quantity || 0) > 0
  || (item.metalwork_reported_quantity || 0) > 0
  || item.cutting_completed
  || item.metalwork_completed
)))

const nextAction = computed(() => {
  if (!sample.value) return null
  const actions = sample.value.workflow_actions
  if (sample.value.status === 'PENDING_COMPLETION') {
    return { type: 'complete' as const, title: '查看样品需求', description: '当前申请等待完善，现阶段仅支持查看详情。', button: '', enabled: false }
  }
  if (sample.value.status === 'MATERIAL_ISSUE_PENDING') {
    return { type: 'material-issue-start' as const, title: '发起样品领料', description: '材料已有可供数量，请由打样部发起整单领料。', button: '发起领料', enabled: canInitiateMaterialIssue.value }
  }
  if (sample.value.status === 'MATERIAL_ISSUE_REVIEW') {
    return { type: 'material-issue-confirm' as const, title: '确认样品领料', description: '打样部已发起领料，请仓库填写实际可以发出的数量。', button: '确认实际领料', enabled: canConfirmMaterialIssue.value }
  }
  if (sample.value.status === 'PENDING') {
    return { type: 'finance' as const, title: '财务确认', description: '上传财务单据图片，或填写人工确认备注。', button: '财务确认', enabled: actions?.can_finance_confirm }
  }
  if (sample.value.status === 'PMC_REVIEW') {
    return { type: 'pmc' as const, title: 'PMC 审核', description: '核对申请与样品信息，通过后进入金工参数环节。', button: '审核通过', enabled: actions?.can_pmc_approve }
  }
  if (sample.value.status === 'METALWORK_PENDING') {
    return { type: 'parameters' as const, title: '上传参数图片', description: '金工和裁剪参数图片可以任意顺序上传；请在下方对应区域操作。', button: '上传金工参数', enabled: Boolean(actions?.can_upload_metalwork || actions?.can_upload_cutting) }
  }
  if (sample.value.status === 'CUTTING_PENDING') {
    return { type: 'parameters' as const, title: '上传参数图片', description: '金工和裁剪参数图片可以任意顺序上传；请在下方对应区域操作。', button: '上传裁剪参数', enabled: Boolean(actions?.can_upload_metalwork || actions?.can_upload_cutting) }
  }
  if (sample.value.status === 'PRODUCTION_PENDING') {
    return { type: 'production' as const, title: '待生产完成', description: '参数已齐全，请根据实际生产情况确认金工和裁剪完成后入库。', button: '生产报工', enabled: canReportProduction.value }
  }
  if (sample.value.status === 'FINISHED') {
    return { type: 'finished' as const, title: '样品单已结束', description: isApplication.value ? '参数齐全且生产均已完成，可在样品库存办理入库。' : '财务、PMC、金工和裁剪步骤均已完成。', button: '', enabled: false }
  }
  return null
})

function findWorkflowRecord(stage: string): SampleWorkflowRecord | null {
  return (sample.value?.workflow_records || []).find((item) => item.stage === stage) || null
}

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络异常，请检查连接后重试。'
  const data = error.response.data as { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string }
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有执行该操作的权限。'
  if (error.response.status === 412) return '数据已被其他人更新，请刷新后再提交。'
  if (error.response.status === 428) return '缺少数据版本，请重新加载后重试。'
  if (error.response.status >= 500) return '后端服务暂时异常，请稍后重试。'
  const fields = data?.error?.field_errors
  if (fields) return Object.values(fields).flat().join('；')
  return data?.error?.message || data?.detail || '提交失败，请检查填写内容。'
}

function formatDate(value?: string | null) {
  if (!value || Number.isNaN(new Date(value).getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value))
}

function formatDateTime(value?: string | null) {
  if (!value || Number.isNaN(new Date(value).getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function formatBytes(value = 0) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function shippingMethodLabel(value?: string) {
  return value === 'MAIL' ? '邮寄' : value === 'OTHER' ? '其他' : '—'
}

function deliveryBatchLabel(value?: string) {
  return value === 'SINGLE' ? '一次交货' : value === 'PARTIAL' ? '分批交货' : '—'
}

function repeatOrderLabel(value?: boolean | null) {
  return value == null ? '—' : value ? '是' : '否'
}

function clearTaskImageUrls() {
  imageRequest++
  for (const url of Object.values(taskImageUrls)) URL.revokeObjectURL(url)
  for (const key of Object.keys(taskImageUrls)) delete taskImageUrls[key]
}

async function hydrateTaskImages() {
  clearTaskImageUrls()
  if (!sample.value) return
  const request = imageRequest
  const currentId = sample.value.id
  const products = (sample.value.products || []).filter((item) => item.task_sheet_file_id)
  const samplingDetails = (sample.value.products || [])
    .flatMap((product) => product.sampling_details || [])
    .filter((item) => item.image_file_id && item.image_content_type.startsWith('image/'))
  await Promise.all([
    ...products.map(async (product) => {
    if (!product.task_sheet_file_id || !product.task_sheet_content_type.startsWith('image/')) return
    try {
      const blob = await fetchSampleBusinessFile(currentId, product.task_sheet_file_id)
      if (request === imageRequest) taskImageUrls[product.task_sheet_file_id] = URL.createObjectURL(blob)
    } catch {
      // 单张预览失败不阻断详情页，其错误会在用户主动下载时提示。
    }
    }),
    ...samplingDetails.map(async (detail) => {
      if (!detail.image_file_id) return
      try {
        const blob = await fetchSampleBusinessFile(currentId, detail.image_file_id)
        if (request === imageRequest) taskImageUrls[detail.image_file_id] = URL.createObjectURL(blob)
      } catch {
        // 单张预览失败不阻断详情页。
      }
    }),
  ])
}

function applySample(value: SampleDetail, version: string) {
  sample.value = value
  etag.value = version || value.etag
  void hydrateTaskImages()
}

async function loadSample() {
  if (saving.value) return
  if (!sampleId.value) { errorMessage.value = '缺少申请编号，请从列表重新进入。'; loading.value = false; return }
  const request = ++loadRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchSample(sampleId.value)
    if (request === loadRequest) applySample(result.data, result.etag)
  } catch (error) {
    if (request === loadRequest) errorMessage.value = getErrorMessage(error)
  } finally {
    if (request === loadRequest) loading.value = false
  }
}

function goBack() { void router.push('/samples') }

function openWorkflowDialog(type: WorkflowDialog) {
  workflowDialog.value = type
  workflowNote.value = ''
  workflowFile.value = null
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  workflowFile.value = input.files?.[0] || null
}

async function handleNextAction() {
  if (saving.value || loading.value || errorMessage.value || !sample.value || !nextAction.value?.enabled) return
  if (nextAction.value.type === 'production') { reportVisible.value = true; return }
  if (nextAction.value.type === 'material-issue-start') {
    void router.push({ name: 'sample-material-issue', params: { sampleId: sample.value.id } })
    return
  }
  if (nextAction.value.type === 'material-issue-confirm') {
    void router.push({ name: 'sample-material-issue-confirm', params: { sampleId: sample.value.id } })
    return
  }
  if (nextAction.value.type === 'parameters') {
    document.querySelector('.sample-parameter-images')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    return
  }
  if (!etag.value) { ElMessage.error('缺少数据版本，请重新加载后重试。'); return }
  if (nextAction.value.type === 'pmc') {
    saving.value = true
    try {
      const result = await approveSamplePmc(sample.value.id, etag.value)
      applySample(result.data, result.etag)
      ElMessage.success('PMC 审核已通过。')
    } catch (error) {
      ElMessage.error(getErrorMessage(error))
    } finally {
      saving.value = false
    }
    return
  }
  if (nextAction.value.type === 'finance') {
    openWorkflowDialog(nextAction.value.type)
  }
}

async function submitWorkflowDialog() {
  if (saving.value || loading.value || errorMessage.value || !sample.value || !workflowDialog.value || !nextAction.value?.enabled) return
  if (!etag.value) { ElMessage.error('缺少数据版本，请重新加载后重试。'); return }
  const currentDialog = workflowDialog.value
  const note = workflowNote.value.trim()
  if (currentDialog === 'finance' && !workflowFile.value && !note) {
    ElMessage.warning('请上传财务凭证，或填写人工确认备注。')
    return
  }
  saving.value = true
  try {
    const result = await confirmSampleFinance(sample.value.id, note, workflowFile.value, etag.value)
    applySample(result.data, result.etag)
    workflowDialog.value = null
    ElMessage.success('财务确认完成。')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    saving.value = false
  }
}

async function cancelIntake() {
  if (saving.value || loading.value || errorMessage.value || !sample.value?.edit_capabilities?.can_cancel) return
  if (!etag.value) { ElMessage.error('缺少数据版本，请重新加载后重试。'); return }
  saving.value = true
  try {
    const result = await ElMessageBox.prompt('取消后整张需求只读，请填写取消原因。', '取消样品需求', {
      confirmButtonText: '确认取消', cancelButtonText: '返回', inputPattern: /\S+/, inputErrorMessage: '取消原因不能为空。',
    })
    const response = await transitionSample(sample.value.id, 'cancel', etag.value, result.value.trim())
    applySample(response.data, response.etag)
    ElMessage.success('样品需求已取消。')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getErrorMessage(error))
  } finally {
    saving.value = false
  }
}

async function openBusinessFile(fileId: string, fileName: string, forceDownload = false) {
  if (!sample.value) return
  try {
    const blob = await fetchSampleBusinessFile(sample.value.id, fileId)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.target = forceDownload ? '_self' : '_blank'
    anchor.rel = 'noopener'
    if (forceDownload) anchor.download = fileName
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  }
}

onMounted(() => { void loadSample() })
onBeforeUnmount(() => { loadRequest++; clearTaskImageUrls() })
</script>

<template>
  <section v-loading="loading" class="sample-detail-page" aria-label="样品流程详情" :data-visual-reference="sample?.status === 'FINISHED' ? '779:8870' : '765:8900'">
    <div class="detail-scroll">
    <template v-if="sample">
      <header class="page-header">
        <div class="identity-block">
          <div>
            <div class="title-line"><h1 class="request-number">{{ sample.request_number }}</h1><span class="sample-type-label">{{ sample.sample_type_display }}</span><SampleStatusTag :status="sample.status" :label="sample.status_display" /></div>
            <p>{{ sample.customer_name }}<span v-if="sample.customer_contact_name"> · {{ sample.customer_contact_name }}</span><span v-if="sample.owner"> · 业务员：{{ sample.owner.display_name }}</span><span v-if="sample.source_inquiry_number"> · 来源询盘 {{ sample.source_inquiry_number }}</span></p>
          </div>
        </div>
        <div class="detail-actions"><ElButton v-if="isApplication" :disabled="saving" @click="router.push({ name: 'sample-material-detail', params: { sampleId: sample.id } })">查看用料需求</ElButton><ElButton v-if="canReportProduction" :disabled="saving || loading || Boolean(errorMessage)" @click="reportVisible = true">生产报工</ElButton><ElButton :disabled="saving" @click="goBack">返回列表</ElButton><ElButton v-if="canOpenFees" :disabled="saving || loading || Boolean(errorMessage)" @click="router.push(`/samples/${sample.id}/fees`)">费用处理</ElButton><ElButton v-if="canOpenFulfillment" :disabled="saving || loading || Boolean(errorMessage)" @click="router.push(`/samples/${sample.id}/fulfillment`)">物流与反馈</ElButton><ElButton v-if="sample.status === 'PENDING_COMPLETION' && sample.edit_capabilities?.can_cancel" :disabled="saving || loading || Boolean(errorMessage)" @click="cancelIntake">取消需求</ElButton></div>
      </header>

      <ElAlert v-if="errorMessage" class="refresh-error" :title="errorMessage" type="error" :closable="false" show-icon />
      <section class="status-flow" aria-label="样品主流程"><div v-for="(step, index) in statusSteps" :key="step.key" class="status-step" :class="{ active: activeStepIndex === index && sample.status !== 'FINISHED', done: sample.status === 'FINISHED' || workflowStageSet.has(step.key) || index < activeStepIndex }"><span>{{ index + 1 }}</span><strong>{{ step.label }}</strong></div></section>

      <div class="content-grid">
        <main class="main-column">
          <SampleMaterialApplicationInfo v-if="isApplication" :sample="sample" />
          <SampleMaterialProgress v-if="isApplication" :sample-id="sample.id" :version="etag" />
          <SampleSection v-if="!isApplication" class="detail-card" title="基本信息">
            <div class="basic-grid">
              <div><label>需求编号</label><b>{{ sample.intake_number || '—' }}</b></div><div><label>手写打样单号</label><b>{{ sample.manual_request_number || '待工厂填写' }}</b></div><div><label>生成打样单号</label><b>{{ sample.manual_request_number ? sample.request_number : '待完善后生成' }}</b></div><div><label>客户</label><b>{{ sample.customer_name }}</b></div><div><label>业务员</label><b>{{ sample.owner?.display_name || '—' }}</b></div>
              <div><label>寄送方式</label><b>{{ shippingMethodLabel(sample.shipping_method) }}</b></div><div><label>下单日期</label><b>{{ formatDate(sample.order_date) }}</b></div><div><label>样品交期</label><b>{{ formatDate(sample.sample_due_date) }}</b></div><div><label>交货批次</label><b>{{ deliveryBatchLabel(sample.delivery_batch) }}</b></div><div><label>样品类型</label><b>{{ sample.sample_type_display }}</b></div>
              <div><label>是否翻单</label><b>{{ repeatOrderLabel(sample.is_repeat_order) }}</b></div><div><label>申请人</label><b>{{ sample.requested_by?.display_name || '—' }}</b></div><div><label>制单人</label><b>{{ sample.created_by?.display_name || '待工厂完善' }}</b></div><div><label>提交日期</label><b>{{ formatDate(sample.submitted_on) }}</b></div><div><label>客户联系人</label><b>{{ sample.customer_contact_name || '—' }}</b></div>
              <div><label>来源询盘</label><ElButton v-if="sample.source_inquiry" link @click="router.push({ name: 'inquiry-detail', params: { inquiryId: sample.source_inquiry } })">{{ sample.source_inquiry_number }}</ElButton><b v-else>—</b></div><div><label>来源报价</label><ElButton v-if="sample.source_quotation_id" link @click="router.push({ name: 'quotation-preview', params: { quotationId: sample.source_quotation_id }, query: { version: sample.source_quotation_version || undefined } })">{{ sample.source_quotation_number }}</ElButton><b v-else>—</b></div><div class="special-note"><label>特殊说明</label><b>{{ sample.purpose || '—' }}</b></div>
            </div>
          </SampleSection>

          <SampleSection v-if="!isApplication && sample.products?.length" class="detail-card product-card" title="样品信息"><template #actions><small>{{ sample.products.length }} 个产品 · {{ sample.products.reduce((total, product) => total + product.details.length, 0) }} 条明细</small></template>
            <article v-for="product in sample.products" :key="product.id" class="product-information">
            <div class="product-heading"><b>产品 {{ product.line_number }}</b><small>总打样数量：{{ product.total_sample_quantity }} PCS</small></div>
            <div class="product-grid"><div><label>产品类别</label><b>{{ product.category_name || '—' }}</b></div><div><label>产品名称</label><b>{{ product.product_name || '—' }}</b></div><div><label>规格</label><b>{{ product.specification || '—' }}</b></div><div><label>任务单</label><b>{{ product.task_sheet_file_name || '—' }}</b></div><div><label>总打样数量</label><b>{{ product.total_sample_quantity }} PCS</b></div><div><label>长（cm）</label><b>{{ product.length_cm ?? '—' }}</b></div><div><label>扶手宽（cm）</label><b>{{ product.armrest_width_cm ?? '—' }}</b></div><div><label>坐宽（cm）</label><b>{{ product.seat_width_cm ?? '—' }}</b></div><div><label>背高（cm）</label><b>{{ product.back_height_cm ?? '—' }}</b></div><div><label>坐高（cm）</label><b>{{ product.seat_height_cm ?? '—' }}</b></div></div>
            <div class="detail-section-title">样品明细 <span>共 {{ product.details.length }} 项</span></div>
            <div v-if="product.details.length" class="product-detail-list">
              <dl v-for="(detail, index) in product.details" :key="detail.id" class="product-detail-grid" :aria-label="`产品${product.line_number}第${index + 1}项明细`">
                <div><dt>产品类别</dt><dd>{{ product.category_name || '—' }}</dd></div><div><dt>产品名称</dt><dd>{{ product.product_name || '—' }}</dd></div><div><dt>规格</dt><dd>{{ product.specification || '—' }}</dd></div><div><dt>色卡</dt><dd>{{ detail.color_card || '—' }}</dd></div><div><dt>颜色</dt><dd>{{ detail.color_name || '—' }}</dd></div><div><dt>色号</dt><dd>{{ detail.color_code || '—' }}</dd></div>
                <div><dt>打样数量</dt><dd>{{ detail.sample_quantity == null ? '—' : `${detail.sample_quantity} PCS` }}</dd></div><div><dt>公差值</dt><dd>{{ detail.tolerance_display || '—' }}</dd></div><div><dt>备注</dt><dd>{{ detail.notes || '—' }}</dd></div><div><dt>裁剪报工</dt><dd>{{ detail.cutting_reported_quantity ?? '—' }}</dd></div><div><dt>金工报工</dt><dd>{{ detail.metalwork_reported_quantity ?? '—' }}</dd></div><div><dt>完成状态</dt><dd>裁剪{{ detail.cutting_completed ? '是' : '否' }} / 金工{{ detail.metalwork_completed ? '是' : '否' }}</dd></div>
              </dl>
            </div>
            <ElEmpty v-else :image-size="44" description="暂无样品明细" />
            <details v-if="product.sampling_details?.length" class="historical-sampling-details">
            <summary>打样信息明细 · {{ product.sampling_details.length }} 项</summary>
            <ElTable :data="product.sampling_details || []" empty-text="暂无打样信息明细" class="sampling-detail-read-table">
              <ElTableColumn prop="line_number" label="序号" width="66" />
              <ElTableColumn prop="detail_type" label="类型" min-width="150" />
              <ElTableColumn label="类别项" min-width="150"><template #default="{ row }">{{ row.category_label || '—' }}</template></ElTableColumn>
              <ElTableColumn label="是否" width="90"><template #default="{ row }"><CustomerActivityTag :tone="row.is_selected ? 'success' : 'neutral'" :label="row.is_selected ? '是' : '否'" /></template></ElTableColumn>
              <ElTableColumn label="描述" min-width="220"><template #default="{ row }">{{ row.description || '—' }}</template></ElTableColumn>
              <ElTableColumn label="图片" min-width="180"><template #default="{ row }"><button v-if="row.image_file_id" type="button" class="sampling-preview" @click="openBusinessFile(row.image_file_id, row.image_file_name)"><img v-if="taskImageUrls[row.image_file_id]" :src="taskImageUrls[row.image_file_id]" :alt="`${row.detail_type}图片`"><ElIcon v-else><Document /></ElIcon><span>{{ row.image_file_name }}</span></button><span v-else>—</span></template></ElTableColumn>
            </ElTable>
            </details>
            </article>
          </SampleSection>

          <SampleSection v-if="!(sample.products || []).length" class="detail-card" title="样品信息"><template #actions><small>历史数据</small></template><ElTable :data="sample.items" empty-text="暂无样品明细"><ElTableColumn prop="line_number" label="序号" width="70" /><ElTableColumn prop="product_description_snapshot" label="产品名称" min-width="190" /><ElTableColumn prop="specification_snapshot" label="规格" min-width="170" /><ElTableColumn prop="color_card_snapshot" label="色卡" min-width="120" /><ElTableColumn prop="color_name_snapshot" label="颜色" min-width="120" /><ElTableColumn prop="color_code_snapshot" label="色号" min-width="120" /><ElTableColumn label="打样数量" min-width="120"><template #default="{ row }">{{ row.sample_quantity || row.requested_quantity }} PCS</template></ElTableColumn></ElTable></SampleSection>

          <SampleSection v-if="sample.status !== 'FINISHED' && (financeRecord || sample.current_fee)" class="detail-card" title="费用与样品发票"><template #actions><small>{{ sample.current_fee?.fee_decision_display || '财务确认记录' }}</small></template><div class="record-grid"><div><label>确认方式</label><b>{{ financeRecord ? (financeRecord.file_id ? '上传财务凭证' : '人工备注确认') : '费用登记' }}</b></div><div><label>费用金额</label><b>{{ sample.current_fee ? `${sample.current_fee.currency_code} ${sample.current_fee.amount}` : '未单独登记费用' }}</b></div><div><label>确认人</label><b>{{ financeRecord?.operator?.display_name || sample.current_fee?.decided_by?.display_name || '—' }}</b></div><div><label>确认时间</label><b>{{ formatDateTime(financeRecord?.operated_at || sample.current_fee?.decided_at) }}</b></div><div><label>凭证</label><ElButton v-if="financeRecord?.file_id" link class="record-file" @click="openBusinessFile(financeRecord.file_id, financeRecord.file_name)">{{ financeRecord.file_name }}</ElButton><b v-else>—</b></div><div class="record-note"><label>确认备注</label><b>{{ financeRecord?.note || sample.current_fee?.decision_reason || '—' }}</b></div></div></SampleSection>

          <SampleSection v-if="isApplication || sample.parameter_images?.length" class="detail-card" title="金工与裁剪参数图片"><template #actions><small>可任意顺序上传</small></template><SampleParameterImages :sample="sample" :etag="etag" :disabled="saving || loading" @saved="applySample" /></SampleSection>
          <SampleSection v-else-if="parameterRecords.length" class="detail-card" title="金工与裁剪参数"><template #actions><small>历史参数记录</small></template><div class="parameter-list"><article v-for="record in parameterRecords" :key="record.id"><div class="parameter-copy"><b>{{ record.stage_display }}</b><p>{{ record.file_name || '未提供附件' }}</p><small>上传人：{{ record.operator?.display_name || '—' }} · 上传时间：{{ formatDateTime(record.operated_at) }}</small><span v-if="record.note">参数说明：{{ record.note }}</span></div><div v-if="record.file_id" class="parameter-actions"><ElButton @click="openBusinessFile(record.file_id, record.file_name)">查看附件</ElButton><ElButton :icon="Download" @click="openBusinessFile(record.file_id, record.file_name, true)">下载</ElButton></div></article></div></SampleSection>

          <SampleSection v-if="hasReportActivity" class="detail-card" title="报工记录"><template #actions><small>{{ isApplication ? '两个工序完成且参数齐全后可入库' : '辅助记录，不改变主流程' }}</small></template><ElTable :data="sample.items.filter((item) => (item.cutting_reported_quantity || 0) > 0 || (item.metalwork_reported_quantity || 0) > 0 || item.cutting_completed || item.metalwork_completed)"><ElTableColumn prop="product_description_snapshot" label="产品" min-width="180" /><ElTableColumn label="裁剪报工" min-width="120"><template #default="{ row }">{{ row.cutting_reported_quantity || 0 }} PCS</template></ElTableColumn><ElTableColumn label="金工报工" min-width="120"><template #default="{ row }">{{ row.metalwork_reported_quantity || 0 }} PCS</template></ElTableColumn><ElTableColumn label="裁剪完成" min-width="100"><template #default="{ row }">{{ row.cutting_completed ? '是' : '否' }}</template></ElTableColumn><ElTableColumn label="金工完成" min-width="100"><template #default="{ row }">{{ row.metalwork_completed ? '是' : '否' }}</template></ElTableColumn></ElTable></SampleSection>

          <SampleSection v-if="sample.fee_records.length || sample.shipments.length || sample.feedback.length || (sample.status === 'FINISHED' && (financeRecord || sample.current_fee))" class="detail-card auxiliary-card" title="费用、物流与客户反馈"><template #actions><small>仅显示已有记录</small></template>
            <div class="auxiliary-grid">
              <article v-if="sample.fee_records.length || sample.current_fee || financeRecord" class="auxiliary-summary"><div class="auxiliary-heading"><h3>费用与样品发票</h3><small>{{ sample.current_fee?.verification_status_display || (financeRecord ? '已确认' : '已有记录') }}</small></div><b>费用金额：{{ sample.current_fee ? `${sample.current_fee.currency_code} ${sample.current_fee.amount}` : '未单独登记费用' }}</b><p v-if="sample.current_fee">费用结论：{{ sample.current_fee.fee_decision_display }}</p><p>确认人：{{ financeRecord?.operator?.display_name || sample.current_fee?.decided_by?.display_name || '—' }}</p><p>确认时间：{{ formatDateTime(financeRecord?.operated_at || sample.current_fee?.decided_at) }}</p><p v-if="financeRecord?.note || sample.current_fee?.decision_reason">确认备注：{{ financeRecord?.note || sample.current_fee?.decision_reason }}</p><ElButton v-if="financeRecord?.file_id" link class="record-file" @click="openBusinessFile(financeRecord.file_id, financeRecord.file_name)">凭证：{{ financeRecord.file_name }}</ElButton></article>
              <article v-if="sample.shipments.length" class="auxiliary-summary"><div class="auxiliary-heading"><h3>收件与物流</h3><small>{{ sample.latest_shipment?.status_display || '已有物流记录' }}</small></div><b>物流单号：{{ sample.latest_shipment?.tracking_number || '—' }}</b><p>承运商：{{ sample.latest_shipment?.carrier_code || '—' }}</p><p>寄出时间：{{ formatDateTime(sample.latest_shipment?.shipped_at) }}</p><p>签收时间：{{ formatDateTime(sample.latest_shipment?.delivered_at) }}</p></article>
              <article v-for="record in sample.feedback" :key="record.id" class="auxiliary-summary feedback-summary"><div class="auxiliary-heading"><h3>客户反馈</h3><small>{{ record.confirmation_result_display }}</small></div><b>反馈结果：{{ record.feedback_type_display }}</b><p>{{ record.feedback_content }}</p><p>登记人：{{ record.recorded_by?.display_name || '—' }}</p><p>反馈时间：{{ formatDateTime(record.occurred_at) }}</p></article>
            </div>
          </SampleSection>
        </main>

        <aside class="side-column">
          <SampleSection class="detail-card next-card" :title="sample.status === 'FINISHED' ? '流程结果' : '下一步行动'"><template #actions><small>{{ sample.status_display }}</small></template><div v-if="nextAction" class="next-action"><p>{{ nextAction.description }}</p><ElButton v-if="nextAction.button" type="primary" class="primary-button" :loading="saving" :disabled="!nextAction.enabled || loading || Boolean(errorMessage)" @click="handleNextAction">{{ nextAction.button }}</ElButton><p v-if="nextAction.button && !nextAction.enabled" class="action-hint">当前账号没有此环节的处理权限。</p><p v-if="nextAction.type === 'parameters'" class="action-hint">图片上传区域位于左侧内容区。</p><SampleStatusTag v-if="nextAction.type === 'finished'" status="FINISHED" label="主流程已完成" /></div><ElEmpty v-else :image-size="44" description="历史状态暂无新主流程操作" /></SampleSection>

          <SampleSection class="detail-card task-card" title="需求任务单图片"><template #actions><small>{{ (sample.products || []).filter(item => item.task_sheet_file_id).length }} 张</small></template><div v-if="(sample.products || []).some((item) => item.task_sheet_file_id)" class="task-sheet-list"><article v-for="product in (sample.products || []).filter((item) => item.task_sheet_file_id)" :key="product.id"><button class="task-preview" type="button" :aria-label="`查看${product.product_name}任务单`" @click="openBusinessFile(product.task_sheet_file_id!, product.task_sheet_file_name)"><img v-if="taskImageUrls[product.task_sheet_file_id!]" :src="taskImageUrls[product.task_sheet_file_id!]" :alt="`${product.product_name}任务单`"><ElIcon v-else><Document /></ElIcon></button><div class="task-copy"><b>{{ product.task_sheet_file_name }}</b><p>产品 {{ product.line_number }} · {{ product.product_name }}</p><small>{{ product.task_sheet_content_type }} · {{ formatBytes(product.task_sheet_size_bytes) }}</small><div class="task-actions"><ElButton @click="openBusinessFile(product.task_sheet_file_id!, product.task_sheet_file_name)">查看原图</ElButton><ElButton :icon="Download" :aria-label="`下载${product.task_sheet_file_name}`" @click="openBusinessFile(product.task_sheet_file_id!, product.task_sheet_file_name, true)" /></div></div></article></div><ElEmpty v-else :image-size="44" description="暂无任务单图片" /></SampleSection>

          <SampleSection class="detail-card timeline-card" title="活动时间轴"><template #actions><ElButton link :icon="Refresh" @click="loadSample">刷新</ElButton></template><ElTimeline v-if="(sample.workflow_records || []).length"><ElTimelineItem v-for="record in sample.workflow_records || []" :key="record.id" :timestamp="formatDateTime(record.operated_at)" :type="record.stage === 'WORKFLOW_FINISHED' ? 'success' : 'primary'"><b>{{ record.stage_display }}</b><p v-if="record.operator">{{ record.operator.display_name }}</p><span v-if="record.note">{{ record.note }}</span></ElTimelineItem></ElTimeline><ElTimeline v-else><ElTimelineItem :timestamp="formatDateTime(sample.created_at)" type="primary">创建样品申请</ElTimelineItem></ElTimeline></SampleSection>
        </aside>
      </div>
    </template>

    <ElResult v-else-if="errorMessage" icon="error" title="样品详情加载失败" :sub-title="errorMessage"><template #extra><ElButton class="primary-button" @click="loadSample">重新加载</ElButton><ElButton @click="goBack">返回列表</ElButton></template></ElResult>

    </div>

    <SampleProductionReportDialog v-if="sample" v-model="reportVisible" :sample="sample" :etag="etag" @saved="applySample" />
    <ElDialog v-model="workflowDialogVisible" title="财务确认" width="560px" class="sample-workflow-dialog" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving"><ElAlert title="财务凭证和人工备注至少填写一项。" type="info" :closable="false" show-icon /><ElForm label-position="top" class="workflow-form" :disabled="saving"><ElFormItem label="财务凭证（选填）"><label class="file-picker"><input type="file" :disabled="saving" accept=".pdf,.jpg,.jpeg,.png" @change="handleFileChange"><ElIcon><UploadFilled /></ElIcon><span>{{ workflowFile?.name || '选择文件' }}</span></label></ElFormItem><ElFormItem label="人工确认备注（选填）"><ElInput v-model="workflowNote" type="textarea" :rows="4" maxlength="1000" show-word-limit placeholder="请输入说明" /></ElFormItem></ElForm><template #footer><ElButton :disabled="saving" @click="workflowDialogVisible = false">取消</ElButton><ElButton type="primary" class="primary-button" :loading="saving" @click="submitWorkflowDialog">确认提交</ElButton></template></ElDialog>
  </section>
</template>

<style scoped lang="scss" src="./sampleDetail.scss"></style>
