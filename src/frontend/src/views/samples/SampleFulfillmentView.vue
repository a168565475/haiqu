<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { CircleCheckFilled, Promotion, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  createSampleShipment,
  createSampleFeedback,
  deliverSampleShipment,
  fetchSample,
  fetchSampleShipment,
  markSampleShipmentException,
  recordSampleShipmentProgress,
  shipSampleShipment,
  transitionSample,
} from '@/api/samples'
import { fetchCustomerContacts } from '@/api/contacts'
import { fetchCustomerEntities, fetchEntityAddresses } from '@/api/customers'
import { useAuthStore } from '@/stores/auth'
import SampleFeedbackRequotationDialog from '@/components/samples/SampleFeedbackRequotationDialog.vue'
import SampleStatusTag from '@/components/samples/SampleStatusTag.vue'
import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'
import type { ContactListItem } from '@/types/contact'
import type { CustomerAddress } from '@/types/customer'
import type { SampleDetail, SampleFeedback, SampleFeedbackCreateInput, SampleShipment, SampleShipmentEvent } from '@/types/sample'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const sample = ref<SampleDetail | null>(null)
const sampleEtag = ref('')
const shipment = ref<SampleShipment | null>(null)
const shipmentEtag = ref('')
const contacts = ref<ContactListItem[]>([])
const addresses = ref<CustomerAddress[]>([])
const loading = ref(true)
const actionLoading = ref(false)
const errorMessage = ref('')
const recipientError = ref('')
const busy = computed(() => loading.value || actionLoading.value)
const actionsDisabled = computed(() => busy.value || Boolean(errorMessage.value))
const feedbackVisible = ref(false)
const deliveryVisible = ref(false)
const exceptionVisible = ref(false)
const progressVisible = ref(false)
const createShipmentVisible = ref(false)
const shipVisible = ref(false)
const requotationVisible = ref(false)
const requotationFeedback = ref<SampleFeedback | null>(null)
const deliveryNote = ref('')
const exceptionReason = ref('')
const progressForm = reactive<{ occurredAt: Date | null; materialStatus: string }>({ occurredAt: null, materialStatus: '' })
const shipmentCreateNotes = ref('')
const shipmentCreateItems = ref<Array<{ sampleItemId: string; description: string; unitCode: string; quantity: number; maximum: number }>>([])
const shipForm = reactive({
  contactId: '', addressId: '', carrierCode: '', trackingNumber: '',
  feeWarningAcknowledged: false, feeWarningReason: '', notes: '',
})
const sampleId = computed(() => String(route.params.sampleId || ''))
const canChange = computed(() => authStore.moduleCan('samples.change_samplerequest', undefined, sample.value))
const canCreateShipment = computed(() => authStore.moduleCan('samples.add_sampleshipment', undefined, sample.value) && authStore.moduleCan('samples.view_sampleshipment', undefined, sample.value))
const canShipShipment = computed(() => authStore.moduleCan('samples.ship_sample', undefined, sample.value))
const canChangeShipment = computed(() => authStore.moduleCan('samples.change_sampleshipment', undefined, sample.value))
const canAddFeedback = computed(() => authStore.moduleCan('samples.add_samplefeedback', undefined, sample.value)
  && ['DELIVERED', 'FEEDBACK_PENDING', 'CONFIRMED', 'COMPLETED'].includes(sample.value?.status || ''))
const canOpenShipment = computed(() => canCreateShipment.value && ['PREPARING', 'SHIPPED'].includes(sample.value?.status || ''))
const canDeliver = computed(() => canChangeShipment.value && shipment.value?.status === 'SHIPPED')
const canRecordException = computed(() => canChangeShipment.value && ['PREPARING', 'SHIPPED', 'EXCEPTION'].includes(shipment.value?.status || ''))
const canViewRequotation = computed(() => [
  'quotations.view_quotation', 'quotations.view_quotationversion',
].every((permission) => authStore.hasPermission(permission)))
const canCreateRequotation = computed(() => canViewRequotation.value && [
  'samples.view_samplefeedback',
  'samples.change_samplefeedback',
  'quotations.add_quotationversion',
].every((permission) => authStore.hasPermission(permission)))

const feedbackForm = reactive<SampleFeedbackCreateInput>({
  feedback_type: 'POSITIVE',
  feedback_content: '',
  occurred_at: new Date().toISOString(),
  confirmation_result: 'PASSED',
  confirmation_source: 'CUSTOMER',
  source_object_version: 1,
  rejection_reason: '',
  corrective_action_request: '',
})

const newestShipment = computed(() => {
  if (!sample.value?.shipments.length) return null
  return [...sample.value.shipments].sort((left, right) => {
    const leftTime = new Date(left.shipped_at || left.created_at).getTime()
    const rightTime = new Date(right.shipped_at || right.created_at).getTime()
    return rightTime - leftTime
  })[0]
})
const hasFeedback = computed(() => Boolean(sample.value?.feedback.length))
const hasFormalPass = computed(() => sample.value?.feedback.some((item) => item.confirmation_result === 'PASSED') || false)
const hasFormalReject = computed(() => sample.value?.feedback.some((item) => item.confirmation_result === 'REJECTED') || false)
const feeReady = computed(() => Boolean(sample.value?.current_fee && sample.value.current_fee.fee_decision !== 'PENDING'))
const feeWarningRequired = computed(() => sample.value?.current_fee?.fee_decision === 'PAID' && sample.value.current_fee.verification_status !== 'MANUALLY_CONFIRMED')
const shipBlockers = computed(() => {
  const blockers: string[] = []
  if (recipientError.value) blockers.push(recipientError.value)
  if (!feeReady.value) blockers.push('请先完成样品费用处理')
  if (!contacts.value.length) blockers.push('请先维护一个有效客户联系人')
  if (!addresses.value.length) blockers.push('请先在客户档案维护收货地址')
  return blockers
})
const isDelivered = computed(() => shipment.value?.status === 'DELIVERED' || [
  'DELIVERED', 'FEEDBACK_PENDING', 'CONFIRMED', 'COMPLETED', 'REJECTED',
].includes(sample.value?.status || ''))
const canRecordShipmentProgress = computed(() => (
  Boolean(shipment.value && ['SHIPPED', 'EXCEPTION'].includes(shipment.value.status) && canChangeShipment.value)
))
const orderChecks = computed(() => [
  { label: '样品已签收', passed: isDelivered.value, pending: '未满足' },
  { label: '客户反馈已记录', passed: hasFeedback.value, pending: '未满足' },
  {
    label: '产前样已确认',
    passed: sample.value?.sample_type === 'PRE_PRODUCTION' && sample.value?.status === 'CONFIRMED',
    pending: sample.value?.sample_type === 'PRE_PRODUCTION' ? '未满足' : '不适用',
  },
  { label: '确认记录含来源与版本', passed: Boolean(sample.value?.feedback.some((item) => item.confirmation_result !== 'PENDING' && item.confirmation_source && item.source_object_version > 0)), pending: '未满足' },
])
const flowSteps = computed(() => [
  { label: '已寄出', done: Boolean(shipment.value?.shipped_at), active: !shipment.value?.shipped_at && ['PREPARING', 'SHIPPED'].includes(sample.value?.status || '') },
  { label: '已签收', done: isDelivered.value, active: Boolean(shipment.value?.shipped_at) && !isDelivered.value },
  { label: '待反馈', done: hasFeedback.value, active: isDelivered.value && !hasFeedback.value },
  { label: '客户确认', done: ['CONFIRMED', 'COMPLETED'].includes(sample.value?.status || ''), active: hasFeedback.value && ['DELIVERED', 'FEEDBACK_PENDING'].includes(sample.value?.status || '') },
  // TODO: 订单关联状态接口接入前，不能把样品前置条件通过当作订单解除阻塞。
  { label: '订单解除阻塞', done: false, active: false },
])
const shipmentEvents = computed<SampleShipmentEvent[]>(() => {
  if (shipment.value?.events?.length) return shipment.value.events
  if (!shipment.value) return []
  const rows: SampleShipmentEvent[] = []
  if (shipment.value.delivered_at) rows.push({
    id: 'fallback-delivered', event_type: 'DELIVERED', event_type_display: '已签收', source: 'MANUAL', source_display: '人工录入',
    event_identifier: '', source_object_version: 1, occurred_at: shipment.value.delivered_at, synchronized_at: shipment.value.delivered_at,
    payload_snapshot: { note: shipment.value.notes }, recorded_by: null, created_at: shipment.value.delivered_at,
  })
  if (shipment.value.shipped_at) rows.push({
    id: 'fallback-shipped', event_type: 'SHIPPED', event_type_display: '已寄出', source: 'MANUAL', source_display: '人工录入',
    event_identifier: '', source_object_version: 1, occurred_at: shipment.value.shipped_at, synchronized_at: shipment.value.shipped_at,
    payload_snapshot: { carrier_code: shipment.value.carrier_code, tracking_number: shipment.value.tracking_number }, recorded_by: shipment.value.shipped_by, created_at: shipment.value.shipped_at,
  })
  return rows
})
const logisticsEvents = computed(() => shipmentEvents.value.filter((event) => event.event_type !== 'PROGRESS'))
const materialProgressEvents = computed(() => shipmentEvents.value
  .filter((event) => event.event_type === 'PROGRESS')
  .sort((left, right) => new Date(right.occurred_at).getTime() - new Date(left.occurred_at).getTime()))
const shipmentSummaryItems = computed(() => {
  if (!shipment.value) return []
  const items: Array<{ label: string; value: string }> = []
  if (shipment.value.shipped_at) items.push({ label: '实际寄出', value: formatDateTime(shipment.value.shipped_at) })
  if (shipment.value.recipient_summary.location && shipment.value.recipient_summary.location !== '未维护') {
    items.push({ label: '收货地区', value: shipment.value.recipient_summary.location })
  }
  if (shipment.value.recipient_summary.recipient_name && shipment.value.recipient_summary.recipient_name !== '未维护') {
    items.push({ label: '收件人', value: shipment.value.recipient_summary.recipient_name })
  }
  if (shipment.value.delivered_at) items.push({ label: '实际签收', value: formatDateTime(shipment.value.delivered_at) })
  if (shipment.value.items.length) {
    const materials = shipment.value.items.map((item) => {
      const unitCode = sample.value?.items.find((sampleItem) => sampleItem.id === item.sample_item_id)?.unit_code
      return `${item.product_description} × ${item.shipped_quantity}${unitCode ? ` ${unitCode}` : ''}`
    }).join('；')
    items.push({ label: '本次寄送物料', value: materials })
  }
  return items
})

function errorText(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络异常，已保留当前输入内容，请检查网络后重试。'
  const data = error.response.data as { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string }
  if (error.response.status === 401) return '登录状态已失效，请重新登录后继续。'
  if (error.response.status === 403) return '当前账号没有此操作权限。'
  if (error.response.status === 404) return '样品或物流记录不存在，可能已被归档。'
  if (error.response.status === 409) return data?.error?.message || data?.detail || '当前业务状态不允许此操作。'
  if (error.response.status === 412) return '数据已被其他人更新，请刷新页面后重试。'
  if (error.response.status === 428) return '缺少数据版本，请刷新页面后再提交。'
  if (error.response.status >= 500) return '后端服务暂时异常，请稍后重试。'
  const fields = data?.error?.field_errors
  return fields ? Object.values(fields).flat().join('；') : data?.error?.message || data?.detail || '提交失败，请检查输入。'
}

function formatDateTime(value?: string | null) {
  if (!value) return '暂未维护'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '暂未维护' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function requireVersion(version: string) {
  if (version) return true
  ElMessage.warning('缺少数据版本，请重新加载后重试。')
  return false
}

function applySample(value: SampleDetail, etag: string) {
  sample.value = value
  sampleEtag.value = etag || value.etag
}

async function loadPage() {
  if (!sampleId.value) return
  loading.value = true
  errorMessage.value = ''
  recipientError.value = ''
  try {
    const result = await fetchSample(sampleId.value)
    applySample(result.data, result.etag)
    try {
      const [contactResult, entities] = await Promise.all([
        fetchCustomerContacts(result.data.customer_account, { page: 1, page_size: 100 }),
        fetchCustomerEntities(result.data.customer_account),
      ])
      contacts.value = contactResult.data.filter((item) => item.status === 'ACTIVE')
      const usableEntities = result.data.transaction_entity
        ? entities.filter((item) => item.id === result.data.transaction_entity)
        : entities
      addresses.value = (await Promise.all(usableEntities.map((item) => fetchEntityAddresses(item.id)))).flat()
      shipForm.contactId ||= result.data.customer_contact || contacts.value.find((item) => item.is_primary_contact)?.id || contacts.value[0]?.id || ''
      shipForm.addressId ||= addresses.value[0]?.id || ''
    } catch {
      contacts.value = []
      addresses.value = []
      recipientError.value = '联系人或收货地址加载失败，请重新加载后重试'
    }
    if (newestShipment.value) {
      const shipmentResult = await fetchSampleShipment(newestShipment.value.id)
      shipment.value = shipmentResult.data
      shipmentEtag.value = shipmentResult.etag
    } else {
      shipment.value = null
      shipmentEtag.value = ''
    }
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    loading.value = false
  }
}

function openCreateShipment() {
  if (!sample.value || !canOpenShipment.value || actionsDisabled.value) return
  shipmentCreateItems.value = sample.value.items.map((item) => ({
    sampleItemId: item.id,
    description: item.product_description_snapshot,
    unitCode: item.unit_code,
    quantity: Number(item.requested_quantity),
    maximum: Number(item.requested_quantity),
  }))
  shipmentCreateNotes.value = ''
  createShipmentVisible.value = true
}

async function saveShipmentRecord() {
  if (!sample.value || !canOpenShipment.value || actionsDisabled.value || !requireVersion(sampleEtag.value)) return
  if (shipmentCreateItems.value.some(item => !Number.isFinite(item.quantity) || item.quantity < 0 || item.quantity > item.maximum)) {
    ElMessage.warning('寄送数量必须在 0 与申请数量之间。'); return
  }
  const items = shipmentCreateItems.value
    .filter((item) => Number(item.quantity) > 0)
    .map((item) => ({ sample_item_id: item.sampleItemId, shipped_quantity: Number(item.quantity).toFixed(4) }))
  if (!items.length) { ElMessage.warning('至少填写一条大于 0 的寄送数量。'); return }
  actionLoading.value = true
  try {
    const result = await createSampleShipment(sample.value.id, { items, notes: shipmentCreateNotes.value.trim() }, sampleEtag.value)
    shipment.value = result.data
    shipmentEtag.value = result.etag
    sampleEtag.value = result.sampleEtag || sampleEtag.value
    createShipmentVisible.value = false
    ElMessage.success('寄送记录已创建，请继续填写快递信息并确认寄出。')
    await loadPage()
    actionLoading.value = false
    openShipDialog()
  } catch (error) { ElMessage.error(errorText(error)) } finally { actionLoading.value = false }
}

function openShipDialog() {
  if (!shipment.value || shipment.value.status !== 'PREPARING' || !canShipShipment.value || actionsDisabled.value) return
  shipForm.contactId ||= sample.value?.customer_contact || contacts.value.find((item) => item.is_primary_contact)?.id || contacts.value[0]?.id || ''
  shipForm.addressId ||= addresses.value[0]?.id || ''
  shipForm.carrierCode = shipment.value.carrier_code || ''
  shipForm.trackingNumber = shipment.value.tracking_number || ''
  shipForm.feeWarningAcknowledged = false
  shipForm.feeWarningReason = ''
  shipForm.notes = ''
  shipVisible.value = true
}

async function saveShipmentDispatch() {
  if (!shipment.value || shipment.value.status !== 'PREPARING' || !canShipShipment.value || actionsDisabled.value || !requireVersion(shipmentEtag.value)) return
  if (shipBlockers.value.length) { ElMessage.warning(shipBlockers.value[0]); return }
  if (!contacts.value.some(item => item.id === shipForm.contactId) || !addresses.value.some(item => item.id === shipForm.addressId)) {
    ElMessage.warning('请选择有效的收件联系人和收货地址。'); return
  }
  if (!shipForm.carrierCode.trim() || !shipForm.trackingNumber.trim()) { ElMessage.warning('请填写快递公司代码和 Tracking Number。'); return }
  if (feeWarningRequired.value && (!shipForm.feeWarningAcknowledged || !shipForm.feeWarningReason.trim())) {
    ElMessage.warning('收费尚未人工确认，请确认风险并填写原因。')
    return
  }
  actionLoading.value = true
  try {
    const result = await shipSampleShipment(shipment.value.id, {
      address_id: shipForm.addressId,
      contact_id: shipForm.contactId,
      carrier_code: shipForm.carrierCode.trim().toUpperCase(),
      tracking_number: shipForm.trackingNumber.trim(),
      fee_warning_acknowledged: feeWarningRequired.value ? shipForm.feeWarningAcknowledged : false,
      fee_warning_reason: feeWarningRequired.value ? shipForm.feeWarningReason.trim() : '',
      notes: shipForm.notes.trim(),
    }, shipmentEtag.value)
    shipment.value = result.data
    shipmentEtag.value = result.etag
    sampleEtag.value = result.sampleEtag || sampleEtag.value
    shipVisible.value = false
    ElMessage.success('样品已确认寄出，状态已进入运输中。')
    await loadPage()
  } catch (error) { ElMessage.error(errorText(error)) } finally { actionLoading.value = false }
}

function openFeedback() {
  if (!sample.value || !canAddFeedback.value || actionsDisabled.value) return
  Object.assign(feedbackForm, {
    customer_contact_id: sample.value.customer_contact,
    feedback_type: 'POSITIVE', feedback_content: '', occurred_at: new Date().toISOString(),
    confirmation_result: 'PASSED', confirmation_source: 'CUSTOMER', source_object_version: 1,
    rejection_reason: '', corrective_action_request: '',
  })
  feedbackVisible.value = true
}

async function saveFeedback() {
  if (!canAddFeedback.value || actionsDisabled.value || !requireVersion(sampleEtag.value)) return
  if (!sample.value || !feedbackForm.feedback_content.trim()) { ElMessage.warning('请填写反馈结论。'); return }
  if (feedbackForm.confirmation_result === 'REJECTED' && !(feedbackForm.rejection_reason || '').trim()) {
    ElMessage.warning('确认未通过时必须填写原因。')
    return
  }
  if (!Number.isInteger(feedbackForm.source_object_version) || feedbackForm.source_object_version < 1) { ElMessage.warning('对象版本必须是大于 0 的整数。'); return }
  actionLoading.value = true
  try {
    const result = await createSampleFeedback(sample.value.id, {
      ...feedbackForm,
      feedback_content: feedbackForm.feedback_content.trim(),
      rejection_reason: (feedbackForm.rejection_reason || '').trim(),
      corrective_action_request: (feedbackForm.corrective_action_request || '').trim(),
    }, sampleEtag.value)
    sampleEtag.value = result.etag
    feedbackVisible.value = false
    ElMessage.success('客户反馈已保存，并已写入时间线和审计记录。')
    await loadPage()
  } catch (error) { ElMessage.error(errorText(error)) } finally { actionLoading.value = false }
}

function openRequotation(record: SampleFeedback) {
  if (record.resulting_quotation_id) {
    if (!canViewRequotation.value || !record.resulting_quotation_version) return
    void router.push({ name: 'quotation-preview', params: { quotationId: record.resulting_quotation_id }, query: { version: record.resulting_quotation_version } })
    return
  }
  if (!canCreateRequotation.value) return
  requotationFeedback.value = record
  requotationVisible.value = true
}

async function handleRequotationCreated(quotationId: string, nextSampleEtag: string, versionId: string) {
  sampleEtag.value = nextSampleEtag || sampleEtag.value
  await loadPage()
  await router.push({ name: 'quotation-preview', params: { quotationId }, query: { version: versionId } })
}

async function saveDelivery() {
  if (!shipment.value || !canDeliver.value || actionsDisabled.value || !requireVersion(shipmentEtag.value)) return
  actionLoading.value = true
  try {
    await deliverSampleShipment(shipment.value.id, deliveryNote.value.trim(), shipmentEtag.value)
    deliveryVisible.value = false
    ElMessage.success('已按人工来源记录签收，并创建一条反馈待办。')
    await loadPage()
  } catch (error) { ElMessage.error(errorText(error)) } finally { actionLoading.value = false }
}

async function saveException() {
  if (!canRecordException.value || actionsDisabled.value || !requireVersion(shipmentEtag.value)) return
  if (!shipment.value || !exceptionReason.value.trim()) { ElMessage.warning('请填写物流异常说明。'); return }
  actionLoading.value = true
  try {
    await markSampleShipmentException(shipment.value.id, exceptionReason.value.trim(), shipmentEtag.value)
    exceptionVisible.value = false
    ElMessage.success('物流异常已记录，不会覆盖已签收事实。')
    await loadPage()
  } catch (error) { ElMessage.error(errorText(error)) } finally { actionLoading.value = false }
}

function openShipmentProgress() {
  if (!canRecordShipmentProgress.value || actionsDisabled.value) return
  progressForm.occurredAt = new Date()
  progressForm.materialStatus = ''
  progressVisible.value = true
}

async function saveShipmentProgress() {
  if (!canRecordShipmentProgress.value || actionsDisabled.value || !requireVersion(shipmentEtag.value)) return
  if (!shipment.value || !progressForm.occurredAt || !progressForm.materialStatus.trim()) {
    ElMessage.warning('请填写进度时间和最新物料情况。')
    return
  }
  if (Number.isNaN(progressForm.occurredAt.getTime())) { ElMessage.warning('请选择有效的进度时间。'); return }
  actionLoading.value = true
  try {
    const result = await recordSampleShipmentProgress(shipment.value.id, {
      occurred_at: progressForm.occurredAt.toISOString(),
      material_status: progressForm.materialStatus.trim(),
    }, shipmentEtag.value)
    shipment.value = result.data
    shipmentEtag.value = result.etag
    sampleEtag.value = result.sampleEtag || sampleEtag.value
    progressVisible.value = false
    ElMessage.success('最新物料进度已记录。')
    await loadPage()
  } catch (error) { ElMessage.error(errorText(error)) } finally { actionLoading.value = false }
}

async function finishSample(action: 'confirm' | 'reject') {
  if (!sample.value || !canChange.value || !['DELIVERED', 'FEEDBACK_PENDING'].includes(sample.value.status) || actionsDisabled.value || !requireVersion(sampleEtag.value)) return
  if (action === 'confirm' && !hasFormalPass.value) { ElMessage.warning('请先记录一条“确认通过”的客户反馈。'); return }
  if (action === 'reject' && !hasFormalReject.value) { ElMessage.warning('请先记录一条“确认未通过”的客户反馈。'); return }
  try {
    const title = action === 'confirm' ? '确认样品通过' : '标记样品未通过'
    actionLoading.value = true
    await ElMessageBox.confirm('该操作将写入客户时间线与审计记录，且不能直接撤销。', title, { type: 'warning' })
    const result = await transitionSample(sample.value.id, action, sampleEtag.value, action === 'reject' ? '客户反馈确认未通过。' : '')
    applySample(result.data, result.etag)
    ElMessage.success(action === 'confirm' ? '样品已确认通过。' : '样品已标记未通过。')
    await loadPage()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(errorText(error))
  } finally { actionLoading.value = false }
}

onMounted(() => { void loadPage() })
</script>

<template>
  <section v-loading="loading" class="sample-fulfillment-page" data-visual-reference="258:5608" aria-label="样品物流、反馈及订单阻塞">
    <template v-if="sample">
      <header class="page-head">
        <div>
          <p class="eyebrow">样品管理 / 物流与反馈</p>
          <div class="title-line"><h1>物流、反馈及订单阻塞</h1><span>{{ sample.request_number }} · {{ sample.customer_name }}</span><SampleStatusTag :status="sample.status" :label="sample.status_display" /></div>
        </div>
        <div class="page-actions">
          <ElButton @click="router.push(`/samples/${sample.id}`)">返回详情</ElButton>
          <ElTooltip content="承运商同步服务暂未开放"><span><ElButton disabled>同步物流</ElButton></span></ElTooltip>
          <ElButton v-if="!shipment && ['PREPARING', 'SHIPPED'].includes(sample.status)" :disabled="!canOpenShipment || actionsDisabled" @click="openCreateShipment">创建寄送记录</ElButton>
          <ElButton v-if="shipment?.status === 'PREPARING'" type="primary" :disabled="!canShipShipment || actionsDisabled" @click="openShipDialog">确认已寄出</ElButton>
          <ElButton type="primary" :disabled="!canAddFeedback || actionsDisabled" @click="openFeedback">记录反馈</ElButton>
        </div>
      </header>

      <div v-if="errorMessage" class="fulfillment-error" role="alert"><span>{{ errorMessage }}</span><ElButton :disabled="busy" @click="loadPage">重新加载</ElButton></div>
      <section class="shipment-summary">
        <template v-if="shipment">
          <div class="summary-title"><b>{{ shipment.carrier_code || '寄送记录已创建' }}<span v-if="shipment.tracking_number"> · {{ shipment.tracking_number }}</span></b><CustomerActivityTag :tone="shipment.status === 'DELIVERED' ? 'success' : shipment.status === 'EXCEPTION' ? 'danger' : 'neutral'" :label="shipment.status_display" /><span v-if="shipment.events?.[0]?.source_display">· {{ shipment.events[0].source_display }}</span></div>
          <div v-if="shipmentSummaryItems.length" class="summary-grid"><div v-for="item in shipmentSummaryItems" :key="item.label"><span>{{ item.label }}</span><b>{{ item.value }}</b></div></div>
          <p v-else class="summary-empty">暂未记录可展示的物流摘要。</p>
        </template>
        <p v-else class="summary-empty">暂未创建寄送记录，暂无物流信息。</p>
      </section>

      <section class="flow-card" aria-label="样品流程">
        <b>闭环进度</b><div class="flow-steps"><div v-for="(step, index) in flowSteps" :key="step.label" class="flow-step" :class="{ done: step.done, active: step.active }"><i>{{ step.done ? '✓' : index + 1 }}</i><span>{{ step.label }}</span></div></div>
      </section>

      <main class="fulfillment-grid">
        <div class="left-column">
          <section class="panel logistics-panel">
            <header class="panel-head"><b>物流轨迹</b><div class="panel-actions"><ElButton :disabled="!canRecordShipmentProgress || actionsDisabled" @click="openShipmentProgress">更新最新进度</ElButton><ElButton v-if="canDeliver" :disabled="actionsDisabled" @click="deliveryNote = ''; deliveryVisible = true">手工签收</ElButton><ElButton v-if="canRecordException" :disabled="actionsDisabled" type="danger" @click="exceptionReason = ''; exceptionVisible = true">记录异常</ElButton><ElTooltip content="承运商服务待接入"><span><ElButton disabled>查看承运商</ElButton></span></ElTooltip></div></header>
            <div v-if="logisticsEvents.length" class="event-list"><article v-for="event in logisticsEvents" :key="event.id" class="event-row" :class="event.event_type.toLowerCase()"><span class="event-dot"></span><time>{{ formatDateTime(event.occurred_at) }}</time><b>{{ event.event_type_display }}</b><span>{{ event.payload_snapshot.note || event.payload_snapshot.carrier_code || '物流事实已记录' }}</span><small>{{ event.source_display }} · 版本 {{ event.source_object_version }}</small></article></div>
            <ElEmpty v-else :image-size="48" description="暂无物流轨迹；创建寄送记录后将显示真实事件。" />
            <p class="source-note"><ElIcon><Promotion /></ElIcon> 承运商同步尚未接入；人工录入的物流事件已标注来源并保留版本，历史事件不会回退后续状态。</p>
            <section v-if="materialProgressEvents.length" class="material-progress" aria-label="物料进度"><b>物料进度</b><div v-if="materialProgressEvents.length" class="material-progress-timeline"><article v-for="event in materialProgressEvents" :key="event.id"><span></span><div><time>{{ formatDateTime(event.occurred_at) }}</time><p>{{ event.payload_snapshot.material_status || event.payload_snapshot.note }}</p><small>{{ event.source_display }} · {{ event.recorded_by?.display_name || '未记录操作人' }}</small></div></article></div><p v-else class="material-progress-empty">暂无物料进度，点击“更新最新进度”后将按时间显示。</p></section>
          </section>

          <section class="panel feedback-panel">
            <header class="panel-head"><b>客户反馈与确认</b><ElButton :disabled="!canAddFeedback || actionsDisabled" @click="openFeedback">新增反馈</ElButton></header>
            <ElAlert v-if="isDelivered && !hasFeedback" title="客户已签收，尚未记录客户反馈" description="请跟进客户，并在收到反馈后记录正式确认结果。" type="warning" :closable="false" show-icon />
            <div v-if="sample.feedback.length" class="feedback-list"><article v-for="record in sample.feedback" :key="record.id"><div><b>{{ record.confirmation_result_display }}</b><CustomerActivityTag :tone="record.confirmation_result === 'PASSED' ? 'success' : record.confirmation_result === 'REJECTED' ? 'danger' : 'neutral'" :label="record.feedback_type_display" /><span>{{ formatDateTime(record.occurred_at) }}</span><ElButton v-if="record.resulting_quotation_id ? canViewRequotation && record.resulting_quotation_version : canCreateRequotation" text class="requote-button" @click="openRequotation(record)">{{ record.resulting_quotation_id ? `查看 ${record.resulting_quotation_label}` : '创建再报价' }}</ElButton></div><p>{{ record.feedback_content }}</p><small>来源：{{ record.confirmation_source_display }} · 版本 {{ record.source_object_version }}<span v-if="record.rejection_reason"> · 未通过原因：{{ record.rejection_reason }}</span></small><small v-if="record.corrective_action_request">整改要求：{{ record.corrective_action_request }}</small><small v-if="record.requotation_source_label">再报价复制来源：{{ record.requotation_source_label }} · {{ formatDateTime(record.requotation_created_at) }}</small></article></div>
            <div v-else class="feedback-empty"><span>反馈结论</span><p>暂未记录客户反馈；请在收到客户意见后新增反馈。</p></div><p class="feedback-note">内部备注：不得以聊天截图替代正式确认记录。</p>
            <div class="confirm-actions" v-if="['DELIVERED', 'FEEDBACK_PENDING'].includes(sample.status) && canChange"><ElButton type="primary" :disabled="!hasFormalPass || actionLoading" @click="finishSample('confirm')">确认通过</ElButton><ElButton :disabled="!hasFormalReject || actionLoading" @click="finishSample('reject')">确认未通过</ElButton></div>
          </section>
        </div>

        <aside class="right-column">
          <section class="panel order-panel">
            <header class="panel-head"><b>订单可推进检查</b><CustomerActivityTag label="待订单核验" tone="neutral" /></header>
            <div class="check-list"><div v-for="item in orderChecks" :key="item.label"><ElIcon :class="item.passed ? 'ok' : 'pending'"><CircleCheckFilled v-if="item.passed" /><WarningFilled v-else /></ElIcon><span>{{ item.label }}</span><b :class="item.passed ? 'ok' : 'pending'">{{ item.passed ? '已满足' : item.pending }}</b></div></div>
            <p class="order-warning">订单模块待接入：此处仅提供可追溯的前置事实检查，CRM 不会显示或执行订单解除阻塞。</p>
          </section>
          <section class="panel automation-panel"><header class="panel-head"><b>自动化提醒</b></header><div class="automation-row"><b>签收后 24 小时</b><span>签收时创建反馈待办</span></div><div class="automation-row"><b>待办到期后</b><span>任务中心自动标记超时</span></div><div class="automation-row"><b>客户确认后</b><span>订单模块待接入</span></div></section>
          <section class="panel source-panel"><header class="panel-head"><b>来源与同步</b></header><p>物流状态：{{ shipment?.events?.[0]?.source_display || '暂无同步来源' }}</p><p>客户反馈：真实样品反馈记录</p><p>订单阻塞：订单模块待接入</p><ElAlert title="承运商服务尚未接入" type="warning" :closable="false" /></section>
        </aside>
      </main>
    </template>
    <ElResult v-else-if="errorMessage" icon="error" title="样品物流页面加载失败" :sub-title="errorMessage"><template #extra><ElButton type="primary" @click="loadPage">重新加载</ElButton><ElButton @click="router.push('/samples')">返回列表</ElButton></template></ElResult>

    <ElDialog draggable class="sample-fulfillment-dialog" :close-on-press-escape="!actionLoading" :show-close="!actionLoading" v-model="createShipmentVisible" title="创建寄送记录" width="620px" :close-on-click-modal="false">
      <ElAlert title="先登记本次实际寄送数量；创建后还需要填写快递和收件信息并确认寄出。" type="info" :closable="false" show-icon />
      <ElTable :data="shipmentCreateItems" class="shipment-item-table" empty-text="样品单没有可寄送明细">
        <ElTableColumn prop="description" label="样品明细" min-width="260" show-overflow-tooltip />
        <ElTableColumn label="寄送数量" width="180"><template #default="{ row }"><ElInputNumber v-model="row.quantity" :disabled="actionLoading" :min="0" :max="row.maximum" :precision="4" :controls="false" /><span class="unit-label">{{ row.unitCode }}</span></template></ElTableColumn>
      </ElTable>
      <ElForm label-position="top" class="form-area" :disabled="actionLoading"><ElFormItem label="寄送备注"><ElInput v-model="shipmentCreateNotes" type="textarea" :rows="2" maxlength="500" /></ElFormItem></ElForm>
      <template #footer><ElButton :disabled="actionLoading" @click="createShipmentVisible = false">取消</ElButton><ElButton type="primary" :loading="actionLoading" :disabled="actionsDisabled" @click="saveShipmentRecord">创建并继续</ElButton></template>
    </ElDialog>

    <ElDialog draggable class="sample-fulfillment-dialog" :close-on-press-escape="!actionLoading" :show-close="!actionLoading" v-model="shipVisible" title="确认样品已寄出" width="620px" :close-on-click-modal="false">
      <ElAlert v-if="shipBlockers.length" :title="shipBlockers.join('；')" type="warning" :closable="false" show-icon>
        <template #default><div class="blocker-actions"><ElButton v-if="!feeReady" size="small" @click="router.push({ name: 'sample-fees', params: { sampleId } })">处理样品费用</ElButton><ElButton v-if="!contacts.length || !addresses.length" size="small" @click="router.push({ name: 'customer-edit', params: { customerId: sample?.customer_account } })">维护客户联系人和地址</ElButton></div></template>
      </ElAlert>
      <ElForm label-position="top" class="form-area" :disabled="actionLoading"><div class="form-grid">
        <ElFormItem label="收件联系人 *"><ElSelect v-model="shipForm.contactId" filterable><ElOption v-for="item in contacts" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem label="收货地址 *"><ElSelect v-model="shipForm.addressId" filterable><ElOption v-for="item in addresses" :key="item.id" :label="`${item.recipient_name || item.label || item.address_code} · ${item.city || item.country_code}`" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem label="快递公司代码 *"><ElInput v-model="shipForm.carrierCode" placeholder="例如 DHL、FEDEX、UPS" /></ElFormItem>
        <ElFormItem label="Tracking Number *"><ElInput v-model="shipForm.trackingNumber" /></ElFormItem>
      </div>
      <template v-if="feeWarningRequired"><ElCheckbox v-model="shipForm.feeWarningAcknowledged">我已确认收费尚未人工核验的寄出风险</ElCheckbox><ElFormItem label="风险确认原因 *"><ElInput v-model="shipForm.feeWarningReason" type="textarea" :rows="2" maxlength="1000" /></ElFormItem></template>
      <ElFormItem label="寄出备注"><ElInput v-model="shipForm.notes" type="textarea" :rows="2" maxlength="500" /></ElFormItem></ElForm>
      <template #footer><ElButton :disabled="actionLoading" @click="shipVisible = false">取消</ElButton><ElButton type="primary" :disabled="Boolean(shipBlockers.length) || actionsDisabled" :loading="actionLoading" @click="saveShipmentDispatch">确认已寄出</ElButton></template>
    </ElDialog>

    <ElDialog draggable class="sample-fulfillment-dialog" :close-on-press-escape="!actionLoading" :show-close="!actionLoading" :close-on-click-modal="false" v-model="feedbackVisible" title="记录客户反馈" width="560px" destroy-on-close>
      <ElAlert title="反馈将写入客户时间线与审计记录；请如实选择确认结果和来源。" type="info" :closable="false" show-icon />
      <ElForm label-position="top" class="form-area" :disabled="actionLoading"><div class="form-grid"><ElFormItem label="反馈类型" required><ElSelect v-model="feedbackForm.feedback_type"><ElOption label="正向" value="POSITIVE" /><ElOption label="一般" value="NEUTRAL" /><ElOption label="负向" value="NEGATIVE" /><ElOption label="需继续跟进" value="FOLLOW_UP" /></ElSelect></ElFormItem><ElFormItem label="确认来源" required><ElSelect v-model="feedbackForm.confirmation_source"><ElOption label="客户确认" value="CUSTOMER" /><ElOption label="质检确认" value="QUALITY" /><ElOption label="人工录入" value="MANUAL" /></ElSelect></ElFormItem><ElFormItem label="确认结果" required><ElSelect v-model="feedbackForm.confirmation_result"><ElOption label="待确认" value="PENDING" /><ElOption label="确认通过" value="PASSED" /><ElOption label="确认未通过" value="REJECTED" /></ElSelect></ElFormItem><ElFormItem label="对象版本" required><ElInputNumber v-model="feedbackForm.source_object_version" :min="1" :controls="false" /></ElFormItem></div><ElFormItem label="反馈结论" required><ElInput v-model="feedbackForm.feedback_content" type="textarea" :rows="4" maxlength="2000" show-word-limit /></ElFormItem><ElFormItem v-if="feedbackForm.confirmation_result === 'REJECTED'" label="未通过原因" required><ElInput v-model="feedbackForm.rejection_reason" type="textarea" :rows="2" maxlength="1000" /></ElFormItem><ElFormItem label="整改要求"><ElInput v-model="feedbackForm.corrective_action_request" type="textarea" :rows="2" maxlength="1000" /></ElFormItem></ElForm>
      <template #footer><ElButton :disabled="actionLoading" @click="feedbackVisible = false">取消</ElButton><ElButton type="primary" :loading="actionLoading" :disabled="actionsDisabled" @click="saveFeedback">保存反馈</ElButton></template>
    </ElDialog>
    <ElDialog draggable class="sample-fulfillment-dialog" :close-on-press-escape="!actionLoading" :show-close="!actionLoading" v-model="deliveryVisible" title="手工标记签收" width="460px" :close-on-click-modal="false"><ElAlert title="将以“人工录入”来源记录签收事实，并自动创建一条反馈待办。" type="warning" :closable="false" show-icon /><ElForm label-position="top" class="form-area" :disabled="actionLoading"><ElFormItem label="签收说明"><ElInput v-model="deliveryNote" type="textarea" :rows="3" maxlength="500" /></ElFormItem></ElForm><template #footer><ElButton :disabled="actionLoading" @click="deliveryVisible = false">取消</ElButton><ElButton type="primary" :loading="actionLoading" :disabled="actionsDisabled" @click="saveDelivery">确认签收</ElButton></template></ElDialog>
    <ElDialog draggable class="sample-fulfillment-dialog" :close-on-press-escape="!actionLoading" :show-close="!actionLoading" v-model="exceptionVisible" title="记录物流异常" width="460px" :close-on-click-modal="false"><ElAlert title="异常不会覆盖已签收或已取消的物流事实。" type="warning" :closable="false" show-icon /><ElForm label-position="top" class="form-area" :disabled="actionLoading"><ElFormItem label="异常说明" required><ElInput v-model="exceptionReason" type="textarea" :rows="3" maxlength="500" /></ElFormItem></ElForm><template #footer><ElButton :disabled="actionLoading" @click="exceptionVisible = false">取消</ElButton><ElButton type="primary" :loading="actionLoading" :disabled="actionsDisabled" @click="saveException">保存异常</ElButton></template></ElDialog>
    <ElDialog draggable class="sample-fulfillment-dialog" :close-on-press-escape="!actionLoading" :show-close="!actionLoading" v-model="progressVisible" title="更新最新物料进度" width="520px" :close-on-click-modal="false"><ElForm label-position="top" class="form-area" :disabled="actionLoading"><ElFormItem label="进度时间" required><ElDatePicker v-model="progressForm.occurredAt" type="datetime" placeholder="选择实际发生时间" /></ElFormItem><ElFormItem label="最新物料情况" required><ElInput v-model="progressForm.materialStatus" type="textarea" :rows="4" maxlength="1000" show-word-limit placeholder="例如：物料已到达曼谷转运中心，等待清关。" /></ElFormItem></ElForm><template #footer><ElButton :disabled="actionLoading" @click="progressVisible = false">取消</ElButton><ElButton type="primary" :loading="actionLoading" :disabled="actionsDisabled" @click="saveShipmentProgress">保存进度</ElButton></template></ElDialog>
    <SampleFeedbackRequotationDialog
      v-if="sample"
      v-model="requotationVisible"
      :sample-id="sample.id"
      :sample-number="sample.request_number"
      :customer-name="sample.customer_name"
      :sample-etag="sampleEtag"
      :feedback="requotationFeedback"
      :can-create-quotation="authStore.hasPermission('quotations.add_quotation')"
      @created="handleRequotationCreated"
    />
  </section>
</template>

<style scoped lang="scss" src="./sampleFulfillment.scss"></style>
<style lang="scss">
@use '@/styles/crm/sample-dialog' as dialog;
.sample-fulfillment-dialog { @include dialog.dialog; }
</style>

