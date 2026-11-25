<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { CircleCheckFilled, Promotion, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createSampleFeedback, fetchSample, transitionSample } from '@/api/samples'
import { useAuthStore } from '@/stores/auth'
import SampleFeedbackRequotationDialog from '@/components/samples/SampleFeedbackRequotationDialog.vue'
import SampleStatusTag from '@/components/samples/SampleStatusTag.vue'
import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'
import type { SampleDetail, SampleFeedback, SampleFeedbackCreateInput, SampleShipmentEvent } from '@/types/sample'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const sample = ref<SampleDetail | null>(null)
const sampleEtag = ref('')
const loading = ref(true)
const actionLoading = ref(false)
const errorMessage = ref('')
const busy = computed(() => loading.value || actionLoading.value)
const actionsDisabled = computed(() => busy.value || Boolean(errorMessage.value))
const feedbackVisible = ref(false)
const requotationVisible = ref(false)
const requotationFeedback = ref<SampleFeedback | null>(null)
const sampleId = computed(() => String(route.params.sampleId || ''))
const canChange = computed(() => authStore.moduleCan('samples.change_samplerequest', undefined, sample.value))
const canAddFeedback = computed(() => authStore.moduleCan('samples.add_samplefeedback', undefined, sample.value)
  && ['DELIVERED', 'FEEDBACK_PENDING', 'CONFIRMED', 'COMPLETED'].includes(sample.value?.status || ''))
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

// 寄送流程已下线，本页只展示历史寄送记录（随样品详情一并返回）。
const shipment = computed(() => {
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
const isDelivered = computed(() => shipment.value?.status === 'DELIVERED' || [
  'DELIVERED', 'FEEDBACK_PENDING', 'CONFIRMED', 'COMPLETED', 'REJECTED',
].includes(sample.value?.status || ''))
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
  { label: '已寄出', done: Boolean(shipment.value?.shipped_at), active: false },
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
  if (error.response.status === 404) return '样品不存在，可能已被归档。'
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
  try {
    const result = await fetchSample(sampleId.value)
    applySample(result.data, result.etag)
  } catch (error) {
    errorMessage.value = errorText(error)
  } finally {
    loading.value = false
  }
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
        <p v-else class="summary-empty">暂无历史寄送记录。</p>
      </section>

      <section class="flow-card" aria-label="样品流程">
        <b>闭环进度</b><div class="flow-steps"><div v-for="(step, index) in flowSteps" :key="step.label" class="flow-step" :class="{ done: step.done, active: step.active }"><i>{{ step.done ? '✓' : index + 1 }}</i><span>{{ step.label }}</span></div></div>
      </section>

      <main class="fulfillment-grid">
        <div class="left-column">
          <section class="panel logistics-panel">
            <header class="panel-head"><b>物流轨迹</b></header>
            <div v-if="logisticsEvents.length" class="event-list"><article v-for="event in logisticsEvents" :key="event.id" class="event-row" :class="event.event_type.toLowerCase()"><span class="event-dot"></span><time>{{ formatDateTime(event.occurred_at) }}</time><b>{{ event.event_type_display }}</b><span>{{ event.payload_snapshot.note || event.payload_snapshot.carrier_code || '物流事实已记录' }}</span><small>{{ event.source_display }} · 版本 {{ event.source_object_version }}</small></article></div>
            <ElEmpty v-else :image-size="48" description="暂无物流轨迹。" />
            <p class="source-note"><ElIcon><Promotion /></ElIcon> 寄送流程已下线，此处仅展示历史寄送记录，物流事件保留原始来源与版本。</p>
            <section v-if="materialProgressEvents.length" class="material-progress" aria-label="物料进度"><b>物料进度</b><div class="material-progress-timeline"><article v-for="event in materialProgressEvents" :key="event.id"><span></span><div><time>{{ formatDateTime(event.occurred_at) }}</time><p>{{ event.payload_snapshot.material_status || event.payload_snapshot.note }}</p><small>{{ event.source_display }} · {{ event.recorded_by?.display_name || '未记录操作人' }}</small></div></article></div></section>
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
          <section class="panel source-panel"><header class="panel-head"><b>来源与同步</b></header><p>物流状态：{{ shipment?.events?.[0]?.source_display || '暂无同步来源' }}</p><p>客户反馈：真实样品反馈记录</p><p>订单阻塞：订单模块待接入</p></section>
        </aside>
      </main>
    </template>
    <ElResult v-else-if="errorMessage" icon="error" title="样品物流页面加载失败" :sub-title="errorMessage"><template #extra><ElButton type="primary" @click="loadPage">重新加载</ElButton><ElButton @click="router.push('/samples')">返回列表</ElButton></template></ElResult>

    <ElDialog draggable class="sample-fulfillment-dialog" :close-on-press-escape="!actionLoading" :show-close="!actionLoading" :close-on-click-modal="false" v-model="feedbackVisible" title="记录客户反馈" width="560px" destroy-on-close>
      <ElAlert title="反馈将写入客户时间线与审计记录；请如实选择确认结果和来源。" type="info" :closable="false" show-icon />
      <ElForm label-position="top" class="form-area" :disabled="actionLoading"><div class="form-grid"><ElFormItem label="反馈类型" required><ElSelect v-model="feedbackForm.feedback_type"><ElOption label="正向" value="POSITIVE" /><ElOption label="一般" value="NEUTRAL" /><ElOption label="负向" value="NEGATIVE" /><ElOption label="需继续跟进" value="FOLLOW_UP" /></ElSelect></ElFormItem><ElFormItem label="确认来源" required><ElSelect v-model="feedbackForm.confirmation_source"><ElOption label="客户确认" value="CUSTOMER" /><ElOption label="质检确认" value="QUALITY" /><ElOption label="人工录入" value="MANUAL" /></ElSelect></ElFormItem><ElFormItem label="确认结果" required><ElSelect v-model="feedbackForm.confirmation_result"><ElOption label="待确认" value="PENDING" /><ElOption label="确认通过" value="PASSED" /><ElOption label="确认未通过" value="REJECTED" /></ElSelect></ElFormItem><ElFormItem label="对象版本" required><ElInputNumber v-model="feedbackForm.source_object_version" :min="1" :controls="false" /></ElFormItem></div><ElFormItem label="反馈结论" required><ElInput v-model="feedbackForm.feedback_content" type="textarea" :rows="4" maxlength="2000" show-word-limit /></ElFormItem><ElFormItem v-if="feedbackForm.confirmation_result === 'REJECTED'" label="未通过原因" required><ElInput v-model="feedbackForm.rejection_reason" type="textarea" :rows="2" maxlength="1000" /></ElFormItem><ElFormItem label="整改要求"><ElInput v-model="feedbackForm.corrective_action_request" type="textarea" :rows="2" maxlength="1000" /></ElFormItem></ElForm>
      <template #footer><ElButton :disabled="actionLoading" @click="feedbackVisible = false">取消</ElButton><ElButton type="primary" :loading="actionLoading" :disabled="actionsDisabled" @click="saveFeedback">保存反馈</ElButton></template>
    </ElDialog>
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

