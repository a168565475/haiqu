<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { assignInquiry, attachInquiryContact, confirmInquiryRequirements, downloadInquiryFile, fetchInquiry, fetchInquiryOptions, fetchInquiryTasks, fetchInquiryTimeline, followUpInquiry, inquiryProductImageUrl, markInquiryInvalid, markInquiryLost, respondToInquiry } from '@/api/inquiries'
import { fetchCustomerContacts } from '@/api/contacts'
import { useAuthStore } from '@/stores/auth'
import InquiryWangEditor from '@/components/InquiryWangEditor.vue'
import InquiryStatusSteps from '@/components/inquiries/InquiryStatusSteps.vue'
import InquiryActionDialog from '@/components/inquiries/InquiryActionDialog.vue'
import ProductImage from '@/components/products/ProductImage.vue'
import InquiryNotice from '@/components/inquiries/InquiryNotice.vue'
import QuotationFromInquiryDialog from '@/components/quotations/QuotationFromInquiryDialog.vue'
import TaskCreateDialog from '@/components/tasks/TaskCreateDialog.vue'
import StatusTag from '@/components/customers/CustomerActivityTag.vue'
import ownerIcon from '@/assets/inquiries/owner.svg'
import taskIcon from '@/assets/inquiries/task.svg'
import type { ContactListItem } from '@/types/contact'
import type { InquiryCommunicationInput, InquiryDetail, InquiryFile, InquiryOptions, InquiryRow, InquiryTimelineEvent } from '@/types/inquiry'
import type { TaskSummary } from '@/types/task'
import { formatEstimatedAmount, priorityTone, statusTone } from './inquiryListState'
import { formatInquiryNumber, formatInquiryTime, inquiryNextActionCopy, safeWebsite, slaPresentation } from './inquiryDetailState'
import { currentHandlingRecords, handlingStageLabel, handlingStatusLabel, handlingTargetLabel, workCalendarDescription } from './inquiryWorktime'
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const inquiryId = computed(() => String(route.params.inquiryId || ''))
const detail = ref<InquiryDetail | null>(null)
const etag = ref<string | null>(null)
const loading = ref(true)
const acting = ref(false)
const errorMessage = ref('')
const options = ref<InquiryOptions | null>(null)
const contacts = ref<ContactListItem[]>([])
const timeline = ref<InquiryTimelineEvent[]>([])
const timelineError = ref('')
const timelineLoading = ref(false)
const timelinePage = ref(0)
const timelineTotal = ref(0)
const tasks = ref<TaskSummary[]>([])
const tasksError = ref('')
const optionsError = ref('')
const contactsError = ref('')
const contactsLoading = ref(false)
const tasksLoading = ref(false)
const now = ref(Date.now())
let generation = 0
let timelineRequest = 0
let tasksRequest = 0
let timer: ReturnType<typeof setInterval> | undefined
const lifecycleVisible = ref(false)
const contactVisible = ref(false)
const assignVisible = ref(false)
const invalidVisible = ref(false)
const quoteVisible = ref(false)
const taskVisible = ref(false)
const slaVisible = ref(false)
const historyVisible = ref(false)
const downloading = ref('')
const dialogError = ref('')
const assignForm = reactive({ ownerId: '', reason: '' })
const contactForm = reactive({ contactId: '' })
const invalidForm = reactive({ reasonCode: '', reasonDetail: '' })
const lifecycleForm = reactive({ action: '', communicationType: 'EMAIL' as InquiryCommunicationInput['communication_type'], content: '', occurredAt: '' })
const invalidReasons: Record<string, string> = { DUPLICATE: '重复询盘', SPAM: '垃圾询盘', UNPROCESSABLE: '无法处理', OTHER: '其他' }
const canFiles = computed(() => auth.canFor('inquiries.view_inquiryfilelink', detail.value))
const canTasks = computed(() => auth.hasPermission('workflow.view_businesstask'))
const canCreateTask = computed(() => auth.hasPermission('workflow.add_businesstask'))
const currentSlas = computed(() => currentHandlingRecords(detail.value?.sla || []))
const currentSla = computed(() => currentSlas.value[0])
const handlingHistory = computed(() => [...(detail.value?.sla || [])].sort((a,b)=>Date.parse(b.started_at)-Date.parse(a.started_at)))
const handlingRule = computed(() => detail.value?.handling_time_rule)
const handlingRuleRows = computed(() => {
  const rule = handlingRule.value
  if (!rule) return []
  const targets: Record<string, number> = {...(rule.stage_minutes || {}), FIRST_RESPONSE:rule.response_minutes || 0, REQUIREMENT_CONFIRMATION:rule.confirmation_minutes || 0}
  return ['ASSIGNMENT','FIRST_RESPONSE','REQUIREMENT_CONFIRMATION','QUOTE_CREATION','QUOTE_DELIVERY','CUSTOMER_FOLLOW_UP','POST_ACCEPTANCE','SAMPLE_FOLLOW_UP'].map(stage=>({stage,minutes:targets[stage] || 0}))
})
const activeOrders = computed(() => (detail.value?.linked_sales_orders || []).filter(order=>order.status !== 'CANCELLED'))
const sla = computed(() => !currentSla.value && activeOrders.value.length ? {label:'已移交销售订单',percentage:null,overdue:false} : slaPresentation(currentSla.value, now.value, detail.value?.status || 'DRAFT'))
const acceptedQuotation = computed(() => detail.value?.linked_quotations.find(item => item.outcome_status === 'WON' && item.accepted_version_id))
const nextStepCopy = computed(() => {
  if (!detail.value) return {title:'',description:''}
  if (activeOrders.value.length) return {title:'在销售订单中继续处理',description:'询盘计时已结束，订单确认及后续履约按销售订单流程处理。'}
  const stage=currentSla.value?.stage_code
  const descriptions: Record<string,string> = {QUOTE_CREATION:'需求已经确认，请创建关联报价。',QUOTE_DELIVERY:'完善报价内容并正式发送给客户。',CUSTOMER_FOLLOW_UP:'记录实际客户跟进，完成后开始下一轮跟进计时。',POST_ACCEPTANCE:'客户已接受报价，请提交样品申请或创建销售订单。',SAMPLE_FOLLOW_UP:'跟踪关联样品进度，并记录本次实际跟进。'}
  return stage && descriptions[stage] ? {title:handlingStageLabel(stage),description:descriptions[stage]} : inquiryNextActionCopy(detail.value)
})
const canMarkLost = computed(() => (auth.user?.sales_access_enabled ? auth.canFor('access_control.marklost_inquiry', detail.value) : allowed('lifecycle')) && ['NEW', 'ANALYZING', 'READY_FOR_QUOTE', 'QUOTING', 'QUOTED', 'FOLLOW_UP'].includes(detail.value?.status || ''))
const primaryAction = computed(() => {
  if (!detail.value) return null
  if (activeOrders.value.length) return {code:'ORDER',label:'查看订单'}
  if (!detail.value.owner && allowed('assign') && detail.value.status !== 'DRAFT') return { code: 'ASSIGN', label: '立即分配' }
  if (currentSla.value?.stage_code==='QUOTE_DELIVERY' && detail.value.linked_quotations.length) return {code:'OPEN_QUOTE',label:'继续完成报价'}
  if (currentSla.value?.stage_code==='POST_ACCEPTANCE' && allowed('create_sales_order') && acceptedQuotation.value?.accepted_version_id) return {code:'SALES_ORDER',label:'创建销售订单'}
  if (detail.value.status === 'CONVERTED') return detail.value.linked_sales_orders.length ? { code: 'ORDER', label: '查看订单' } : null
  if (detail.value.status === 'DRAFT') return auth.canFor('inquiries.change_inquiry', detail.value) ? { code: 'EDIT', label: '继续编辑' } : null
  if (!detail.value.owner && allowed('assign')) return { code: 'ASSIGN', label: '立即分配' }
  if (allowed('attach_contact')) return { code: 'CONTACT', label: '补充联系人' }
  if (allowed('respond')) return { code: 'RESPOND', label: '记录首响' }
  if (allowed('confirm_requirements')) return { code: 'CONFIRM', label: '确认需求' }
  if (allowed('create_quotation')) return { code: 'QUOTE', label: '创建报价' }
  if (allowed('follow_up')) return { code: 'FOLLOW_UP', label: '记录跟进' }
  return null
})
function runPrimaryAction() {
  if (acting.value) return
  switch (primaryAction.value?.code) {
    case 'ASSIGN': openAssign(); break
    case 'CONTACT': openContact(); break
    case 'EDIT': goEdit(); break
    case 'QUOTE': quoteVisible.value = true; break
    case 'OPEN_QUOTE': {
      const quote=detail.value?.linked_quotations.find(item=>item.id===currentSla.value?.progress_context?.quotation_id) || detail.value?.linked_quotations[0]
      if (quote) quoteCreated(quote.id)
      break
    }
    case 'SALES_ORDER': createSalesOrder(); break
    case 'ORDER': {
      const order = activeOrders.value[0] || detail.value?.linked_sales_orders[0]
      if (order) void router.push({ name: 'sales-order-detail', params: { orderId: order.id } })
      break
    }
    case 'RESPOND': case 'CONFIRM': case 'FOLLOW_UP': openLifecycle(primaryAction.value.code); break
  }
}
const website = computed(() => safeWebsite(detail.value?.customer_snapshot?.website))
const activeTasks = computed(() => tasks.value.filter(item => !['COMPLETED', 'CANCELLED'].includes(item.status)))
const lifecycleTitle = computed(() => ({ RESPOND: '记录首响', FOLLOW_UP: '记录客户跟进', CONFIRM: '确认客户需求', LOST: '标记为丢失' }[lifecycleForm.action] || '业务操作'))
const communicationAction = computed(() => ['RESPOND', 'FOLLOW_UP'].includes(lifecycleForm.action))
const imageUploadUrl = computed(() => allowed('follow_up') || allowed('respond') ? `/api/v1/inquiries/${encodeURIComponent(inquiryId.value)}/images/` : '')
const summary = computed(() => {
  if (!detail.value) return ''
  const trade = [detail.value.trade_term_code, detail.value.trade_term_place].filter(Boolean).join(' ')
  return [trade && `贸易条款：${trade}`, detail.value.delivery_requirement && `目标交期：${detail.value.delivery_requirement}`, `预计订单金额：${formatEstimatedAmount(detail.value)}`].filter(Boolean).join(' · ')
})
function allowed(action: keyof InquiryRow['allowed_actions']) {
  if (!detail.value?.allowed_actions[action]) return false
  if (auth.user?.sales_access_enabled) return true
  const permissions: Partial<Record<keyof InquiryRow['allowed_actions'], string>> = { assign: 'inquiries.assign_inquiry', create_quotation: 'quotations.add_quotation' }
  if (['create_sample', 'create_sales_order'].includes(action)) return true
  return auth.hasPermission(permissions[action] || 'inquiries.change_inquiry')
}
function errorText(error: any) {
  const status = error?.response?.status
  if (status === 401) return '登录状态已失效，请重新登录。'
  if (status === 403) return '当前账号没有此操作权限。'
  if (status === 404) return '记录不存在或不在当前可见范围内。'
  if (status === 412) return '记录已被其他人修改，请关闭窗口并刷新后重试。'
  if (status === 428) return '缺少记录版本，请刷新后重试。'
  const body = error?.response?.data
  const fields = body?.error?.field_errors
  return (fields && Object.values(fields).flat()[0]) || body?.error?.message || body?.detail || '请求失败，请稍后重试。'
}
function usableFileStatus(status: string) { return status === 'CLEAN' || status === 'SKIPPED' }
function fileStatusLabel(status: string) { return status === 'SKIPPED' ? '内部上传，未扫描' : status === 'CLEAN' ? '已上传' : '暂不可下载' }
function plainText(value: string) { return new DOMParser().parseFromString(value || '', 'text/html').body.textContent?.trim() || '' }
function formatMoney(value: string | number | null, currency: string) { return value === null || value === '' ? '待确认' : `${currency || ''} ${formatInquiryNumber(value, 2)}`.trim() }
function fileType(file: InquiryFile) { return (file.original_name.split('.').pop() || 'FILE').slice(0, 5).toUpperCase() }
function fileSize(bytes: number) { return !Number.isFinite(bytes) || bytes < 0 ? '—' : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }
function actorName(event: InquiryTimelineEvent) {
  const name = event.event_data?.actor_display_name || event.event_data?.actor_name
  if (typeof name === 'string') return name
  const actorId = event.event_data?.actor_employee_id
  if (actorId && actorId === detail.value?.owner?.id) return detail.value?.owner?.display_name || '业务员'
  return actorId ? '业务员' : '系统'
}
async function loadTimeline(append = false, version = generation) {
  if (append && timelineLoading.value) return
  const requestId = ++timelineRequest
  timelineLoading.value = true; timelineError.value = ''
  try {
    const page = append ? timelinePage.value + 1 : 1
    const result = await fetchInquiryTimeline(inquiryId.value, { page, page_size: 20 })
    if (version !== generation || requestId !== timelineRequest) return
    timeline.value = append ? [...timeline.value, ...result.data] : result.data
    timelinePage.value = page; timelineTotal.value = result.meta.total
  } catch (error) { if (version === generation && requestId === timelineRequest) timelineError.value = errorText(error) }
  finally { if (version === generation && requestId === timelineRequest) timelineLoading.value = false }
}
async function loadTasks(version = generation) {
  if (!canTasks.value) return
  const requestId = ++tasksRequest
  tasksError.value = ''; tasksLoading.value = true
  try { const result = await fetchInquiryTasks(inquiryId.value); if (version === generation && requestId === tasksRequest) tasks.value = result }
  catch (error) { if (version === generation && requestId === tasksRequest) tasksError.value = errorText(error) }
  finally { if (version === generation && requestId === tasksRequest) tasksLoading.value = false }
}
async function load() {
  if (acting.value) return
  const version = ++generation
  loading.value = true; errorMessage.value = ''; detail.value = null; etag.value = null
  timeline.value = []; timelinePage.value = 0; timelineTotal.value = 0; timelineLoading.value = false
  tasks.value = []; contacts.value = []; options.value = null
  tasksLoading.value = false; contactsLoading.value = false
  optionsError.value = ''; contactsError.value = ''; timelineError.value = ''; tasksError.value = ''
  try {
    // 打开页面只读取业务数据，不因地址栏参数创建原型示例记录。
    const result = await fetchInquiry(inquiryId.value)
    if (version !== generation) return
    detail.value = result.data; etag.value = result.etag
    // 正文已就绪；时间轴、任务与操作选项在各自区域继续加载。
    loading.value = false
    const jobs: Promise<unknown>[] = [loadTimeline(false, version), loadTasks(version)]
    if (allowed('assign') || allowed('mark_invalid')) jobs.push(fetchInquiryOptions().then(value => { if (version === generation) options.value = value }).catch(error => { if (version === generation) optionsError.value = errorText(error) }))
    if (allowed('attach_contact')) jobs.push(loadContacts(version))
    await Promise.all(jobs)
  } catch (error) { if (version === generation) errorMessage.value = errorText(error) }
  finally { if (version === generation) loading.value = false }
}
async function loadContacts(version = generation) {
  if (!detail.value) return
  const customerId = detail.value.customer.id
  contactsError.value = ''; contactsLoading.value = true
  try {
    const items: ContactListItem[] = []
    let page = 1
    while (true) {
      const result = await fetchCustomerContacts(customerId, { status: 'ACTIVE', page, page_size: 100 })
      if (version !== generation) return
      items.push(...result.data)
      if (items.length >= result.meta.total || !result.data.length) break
      page++
    }
    contacts.value = items
  } catch (error) { if (version === generation) contactsError.value = errorText(error) }
  finally { if (version === generation) contactsLoading.value = false }
}
function openLifecycle(action: string) {
  const actions: Record<string, keyof InquiryRow['allowed_actions']> = { RESPOND: 'respond', FOLLOW_UP: 'follow_up', CONFIRM: 'confirm_requirements', LOST: 'lifecycle' }
  if (acting.value || !actions[action] || !allowed(actions[action]) || (action === 'LOST' && !canMarkLost.value)) return
  Object.assign(lifecycleForm, { action, communicationType: 'EMAIL', content: '', occurredAt: new Date().toISOString() })
  dialogError.value = ''; lifecycleVisible.value = true
}
async function submitLifecycle() {
  if (acting.value || !detail.value || !etag.value) return
  if ((communicationAction.value || lifecycleForm.action === 'LOST') && !plainText(lifecycleForm.content)) { dialogError.value = '请填写实际沟通内容或原因。'; return }
  if (communicationAction.value && !Number.isFinite(Date.parse(lifecycleForm.occurredAt))) { dialogError.value = '请填写有效的发生时间。'; return }
  acting.value = true; dialogError.value = ''
  try {
    const payload: InquiryCommunicationInput = { communication_type: lifecycleForm.communicationType, content: lifecycleForm.content, occurred_at: lifecycleForm.occurredAt }
    let result
    if (lifecycleForm.action === 'RESPOND' && allowed('respond')) result = await respondToInquiry(inquiryId.value, etag.value, payload)
    else if (lifecycleForm.action === 'FOLLOW_UP' && allowed('follow_up')) result = await followUpInquiry(inquiryId.value, etag.value, payload)
    else if (lifecycleForm.action === 'CONFIRM' && allowed('confirm_requirements')) result = await confirmInquiryRequirements(detail.value.id, etag.value)
    else if (lifecycleForm.action === 'LOST' && canMarkLost.value) result = await markInquiryLost(inquiryId.value, etag.value, plainText(lifecycleForm.content))
    else return
    detail.value = result.data; etag.value = result.etag; lifecycleVisible.value = false
    await Promise.all([loadTimeline(), loadTasks()]); ElMessage.success('询盘记录已更新。')
  } catch (error) { dialogError.value = errorText(error) }
  finally { acting.value = false }
}
function openAssign() {
  if (acting.value || !allowed('assign')) return
  assignForm.ownerId = ''; assignForm.reason = ''; dialogError.value = ''; assignVisible.value = true
}
function openContact() {
  if (acting.value || contactsLoading.value || !allowed('attach_contact')) return
  contactForm.contactId = contacts.value.find(item => item.is_primary_contact)?.id || ''; dialogError.value = ''; contactVisible.value = true
}
function openInvalid() {
  if (acting.value || !allowed('mark_invalid')) return
  invalidForm.reasonCode = ''; invalidForm.reasonDetail = ''; dialogError.value = ''; invalidVisible.value = true
}
async function submitAction(action: 'assign' | 'contact' | 'invalid') {
  if (acting.value || !detail.value || !etag.value) return
  if (action === 'assign' && (!allowed('assign') || !options.value?.owners.some(owner => owner.id === assignForm.ownerId && owner.id !== detail.value?.owner?.id))) { dialogError.value = '请选择有效的新负责人。'; return }
  if (action === 'contact' && (!allowed('attach_contact') || !contacts.value.some(contact => contact.id === contactForm.contactId))) { dialogError.value = '请选择当前客户的有效联系人。'; return }
  if (action === 'invalid' && (!allowed('mark_invalid') || !options.value?.invalid_reason_codes.includes(invalidForm.reasonCode))) { dialogError.value = '请选择无效原因。'; return }
  acting.value = true; dialogError.value = ''
  try {
    if (action === 'assign') await assignInquiry(inquiryId.value, etag.value, assignForm.ownerId, assignForm.reason)
    else if (action === 'contact') await attachInquiryContact(inquiryId.value, etag.value, contactForm.contactId)
    else await markInquiryInvalid(inquiryId.value, etag.value, invalidForm.reasonCode, invalidForm.reasonDetail)
    assignVisible.value = false; contactVisible.value = false; invalidVisible.value = false
    acting.value = false; await load(); ElMessage.success('询盘已更新。')
  } catch (error) { dialogError.value = errorText(error) }
  finally { acting.value = false }
}
async function download(file?: InquiryFile) {
  if (downloading.value || !canFiles.value || !detail.value) return
  if (file && !usableFileStatus(file.scan_status)) return ElMessage.warning('附件尚未通过安全扫描。')
  downloading.value = file?.file_id || 'all'
  try {
    const blob = await downloadInquiryFile(inquiryId.value, file?.file_id)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = file?.original_name || `${detail.value.inquiry_number}_附件.zip`
    document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error: any) {
    if (error?.response?.data instanceof Blob) { try { error.response.data = JSON.parse(await error.response.data.text()) } catch { /* 使用通用错误提示 */ } }
    ElMessage.error(errorText(error))
  } finally { downloading.value = '' }
}
function goList() { void router.push({ name: 'inquiries' }) }
function goEdit() { void router.push({ name: 'inquiry-edit', params: { inquiryId: inquiryId.value } }) }
function quoteCreated(quotationId: string) { void router.push({ name: 'quotation-edit', params: { quotationId } }) }
function createSample() { if (allowed('create_sample')) void router.push({ name: 'sample-new', query: { sourceType: 'inquiry', sourceId: inquiryId.value } }) }
function createSalesOrder() {
  if (!allowed('create_sales_order') || !acceptedQuotation.value?.accepted_version_id) return ElMessage.warning('没有可用的已接受报价版本。')
  void router.push({ name: 'sales-order-create', query: { source: 'QUOTATION', quotationVersionId: acceptedQuotation.value.accepted_version_id } })
}
onMounted(() => { void load(); timer = setInterval(() => { now.value = Date.now() }, 30000) })
watch(inquiryId, () => {
  lifecycleVisible.value = false; contactVisible.value = false; assignVisible.value = false; invalidVisible.value = false
  quoteVisible.value = false; taskVisible.value = false; slaVisible.value = false; historyVisible.value = false
  void load()
})
onBeforeRouteLeave(() => !acting.value)
onBeforeRouteUpdate(() => !acting.value)
onBeforeUnmount(() => { generation++; if (timer) clearInterval(timer) })
</script>
<template>
  <section v-loading="loading" class="inquiry-detail-page" :aria-busy="loading">
    <template v-if="detail">
      <header class="detail-header">
        <div class="heading-row"><div class="heading-copy"><h1 :title="detail.inquiry_number">询盘 {{ detail.inquiry_number }}</h1><p>{{ detail.customer.name }} · {{ detail.customer.country_code || '—' }} · {{ detail.source.display_name || '—' }} · 接收于 {{ formatInquiryTime(detail.received_at) }}</p></div>
          <div class="header-actions"><el-button v-if="allowed('assign')" :disabled="acting || !options" @click="openAssign">转交</el-button><el-button v-if="allowed('mark_invalid')" :disabled="acting || !options" @click="openInvalid">标记无效</el-button><el-button v-if="allowed('create_sample')" :disabled="acting" @click="createSample">创建样品</el-button><el-button v-if="primaryAction" type="primary" :disabled="acting || (primaryAction.code === 'ASSIGN' && !options) || (primaryAction.code === 'CONTACT' && contactsLoading)" @click="runPrimaryAction">{{ primaryAction.label }}</el-button></div>
        </div>
      </header>
      <InquiryStatusSteps :status="detail.status" :status-label="detail.status_display" :has-owner="!!detail.owner"/>
      <el-alert v-if="optionsError || contactsError" :title="optionsError || contactsError" type="warning" :closable="false" show-icon class="section-error"><template #default><el-button link @click="load">重新加载操作选项</el-button></template></el-alert>
      <div class="content-grid">
        <article class="dossier panel">
          <section class="dossier-section summary-section"><div class="section-heading"><h2>客户需求摘要</h2><div class="summary-tags"><StatusTag :label="detail.status_display" :tone="statusTone(detail.status)"/><StatusTag v-if="detail.priority" :label="`${detail.priority_display}优先级`" :tone="priorityTone(detail.priority)"/></div></div><div class="demand-box"><p>{{ plainText(detail.description) || '暂无客户需求备注' }}</p><small>{{ summary }}</small></div></section>
          <section class="dossier-section products-section"><h2>产品需求明细</h2><div class="products-scroll"><table class="products-table"><colgroup><col style="width:9%"/><col style="width:15%"/><col style="width:15%"/><col style="width:9%"/><col style="width:9%"/><col style="width:10%"/><col style="width:10%"/><col style="width:10%"/><col style="width:5%"/><col style="width:8%"/></colgroup><thead><tr><th scope="col">类别</th><th scope="col">品名</th><th scope="col">规格</th><th scope="col">颜色</th><th scope="col">材质</th><th scope="col">数量 / 单位</th><th scope="col">目标价</th><th scope="col">期望日期</th><th scope="col">图片</th><th scope="col">备注</th></tr></thead><tbody><tr v-for="(item, index) in detail.items" :key="item.id || index"><td>{{ item.product_category_name || '—' }}</td><th scope="row" :title="`${item.product_description} · ${item.product_number_snapshot || '手填定制产品'}`">{{ item.product_description || '—' }}</th><td :title="item.specification || '—'">{{ item.specification || '—' }}</td><td :title="item.color || '—'">{{ item.color || '—' }}</td><td :title="item.material || '—'">{{ item.material || '—' }}</td><td>{{ formatInquiryNumber(item.quantity) }} {{ item.unit_code }}</td><td :class="{ pending: item.target_unit_price === null }">{{ formatMoney(item.target_unit_price, item.target_currency_code) }}</td><td>{{ item.expected_date || '—' }}</td><td><ProductImage v-if="item.id && item.product_image_id" :src="`${inquiryProductImageUrl(item.id)}?v=${item.product_image_id}`" :name="`${item.product_description}产品图片`"/><span v-else>无图</span></td><td :title="item.notes || '—'">{{ item.notes || '—' }}</td></tr><tr v-if="!detail.items.length"><td colspan="10" class="empty-line">暂无产品需求明细</td></tr></tbody></table></div></section>
          <section class="dossier-section attachments-section"><div class="section-heading"><h2>附件 ({{ detail.files.length }})</h2><el-button v-if="canFiles && detail.files.length" :loading="downloading === 'all'" :disabled="!!downloading" @click="download()">全部下载</el-button></div><div v-if="detail.files.length" class="attachment-grid"><button v-for="file in detail.files" :key="file.id" class="attachment" :disabled="!canFiles || !!downloading || !usableFileStatus(file.scan_status)" :title="!usableFileStatus(file.scan_status) ? '附件尚未通过安全扫描' : !canFiles ? '无附件下载权限' : `下载 ${file.original_name}`" @click="download(file)"><span class="file-badge" :class="{ document: ['PDF', 'DOC', 'DOCX'].includes(fileType(file)) }">{{ fileType(file) }}</span><span class="file-caption"><strong>{{ file.original_name }}</strong><small>{{ usableFileStatus(file.scan_status) ? `${fileStatusLabel(file.scan_status)} · ${fileSize(file.size_bytes)}` : '暂不可下载' }}</small></span></button></div><p v-else class="empty-line">暂无附件</p></section>
          <section class="dossier-section communication-section"><h2>最近沟通</h2><div class="timeline-scroll"><div v-for="event in timeline" :key="event.id" class="timeline-row"><span class="timeline-dot" :class="{ communication: event.source_type === 'CUSTOMER_COMMUNICATION' }"/><strong>{{ event.title }}</strong><span>{{ actorName(event) }}</span><p :title="plainText(event.summary)">{{ plainText(event.summary) || '—' }}</p><time>{{ formatInquiryTime(event.occurred_at) }}</time></div><p v-if="!timeline.length && !timelineError" class="empty-line">{{ timelineLoading ? '正在加载沟通记录…' : '暂无沟通记录' }}</p></div><div v-if="timelineError" class="inline-error" role="alert">{{ timelineError }}<button class="text-link" @click="loadTimeline()">重试</button></div><div class="communication-actions"><el-button v-if="allowed('respond') || allowed('follow_up')" :disabled="acting" @click="openLifecycle(allowed('respond') ? 'RESPOND' : 'FOLLOW_UP')">添加沟通记录</el-button><el-button v-if="timeline.length < timelineTotal" :loading="timelineLoading" @click="loadTimeline(true)">加载更多记录</el-button></div></section>
        </article>
        <aside class="work-rail">
          <section class="panel sla-panel"><div class="section-heading"><h2>处理时限与进度</h2><button class="text-link" @click="slaVisible = true">查看规则与记录</button></div><div class="sla-summary" :class="{ overdue: sla.overdue }"><div class="sla-head"><strong>{{ sla.label }}</strong><span>{{ currentSla ? handlingStageLabel(currentSla.stage_code) : handlingRule ? '新开始的阶段按规则计时' : '未配置处理时限' }}</span></div><el-progress v-if="sla.percentage !== null" :percentage="sla.percentage" :show-text="false" :stroke-width="6"/><p v-if="currentSla?.work_calendar" class="working-time-note">按工作时间计算 · 午休及休息时间不计时</p><div class="sla-foot"><span>开始：{{ formatInquiryTime(currentSla?.started_at) }}</span><span>截止：{{ formatInquiryTime(currentSla?.next_deadline_at) }}</span></div></div><div v-for="record in currentSlas.slice(1)" :key="record.id" class="sla-parallel"><strong>{{ handlingStageLabel(record.stage_code) }}</strong><span>{{ slaPresentation(record, now, detail.status).label }}</span><small>同时计时 · 截止 {{ formatInquiryTime(record.next_deadline_at) }}</small></div></section>
          <section class="panel owner-panel"><h2>当前负责人</h2><div class="owner-row"><span class="owner-avatar"><img :src="ownerIcon" alt=""/></span><span>{{ detail.owner?.display_name || '未分配' }}</span><el-button v-if="allowed('assign')" :disabled="acting || !options" @click="openAssign">{{ detail.owner ? '转交负责人' : '分配负责人' }}</el-button><el-button v-else :aria-expanded="historyVisible" @click="historyVisible = !historyVisible">{{ historyVisible ? '收起历史' : '查看历史' }}</el-button></div><div v-if="historyVisible" class="assignment-history"><p v-if="!detail.assignment_history.length" class="empty-line">暂无分配历史</p><article v-for="record in detail.assignment_history" :key="record.id"><strong>{{ record.previous_owner?.display_name || '未分配' }} → {{ record.new_owner?.display_name || '未分配' }}</strong><time>{{ formatInquiryTime(record.assigned_at) }}</time><p v-if="record.assignment_reason">{{ record.assignment_reason }}</p></article></div></section>
          <section class="panel next-panel"><div class="section-heading"><h2>下一步行动</h2><el-dropdown popper-class="inquiry-v4-select" v-if="canMarkLost || canCreateTask || allowed('create_sales_order')" trigger="click"><button class="text-link" :disabled="acting">更多操作</button><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="canMarkLost" @click="openLifecycle('LOST')">标记丢失</el-dropdown-item><el-dropdown-item v-if="canCreateTask" @click="taskVisible = true">添加任务</el-dropdown-item><el-dropdown-item v-if="allowed('create_sales_order')" @click="createSalesOrder">创建销售订单</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div><div class="next-action"><span class="task-icon"><img :src="taskIcon" alt=""/></span><div><strong>{{ nextStepCopy.title }}</strong><p>{{ nextStepCopy.description }}</p><small v-if="currentSla?.next_deadline_at && sla.percentage !== null">截止时间：{{ formatInquiryTime(currentSla.next_deadline_at) }}</small></div></div><div class="action-buttons"><el-button v-if="primaryAction" :disabled="acting || (primaryAction.code === 'ASSIGN' && !options) || (primaryAction.code === 'CONTACT' && contactsLoading)" @click="runPrimaryAction">{{ primaryAction.code === 'ASSIGN' ? '分配负责人' : primaryAction.label }}</el-button></div><p v-if="tasksLoading" role="status" class="empty-line">正在加载相关任务…</p><div v-if="tasksError" class="inline-error" role="alert">{{ tasksError }}<button class="text-link" @click="loadTasks()">重试</button></div><div v-if="canTasks && activeTasks.length" class="related-tasks"><button v-for="task in activeTasks" :key="task.id" class="related-link" @click="router.push({ name: 'task-detail', params: { taskId: task.id } })">{{ task.title }}<small>{{ task.status_display }} · {{ formatInquiryTime(task.due_at) }}</small></button></div></section>
          <section class="panel info-panel"><h2>相关信息</h2><dl><dt>客户</dt><dd>{{ detail.customer.name }}<button class="text-link" @click="router.push({ name: 'customer-detail', params: { customerId: detail.customer.id } })">查看客户 →</button></dd><dt>国家/地区</dt><dd>{{ detail.customer.country_code || '—' }}</dd><dt>来源</dt><dd>{{ detail.source.display_name || '—' }}</dd><dt>客户网站</dt><dd><a v-if="website" :href="website" target="_blank" rel="noopener noreferrer">{{ website }}</a><span v-else>—</span></dd><dt>询盘编号</dt><dd>{{ detail.inquiry_number }}</dd><dt>接收时间</dt><dd>{{ formatInquiryTime(detail.received_at) }}</dd><dt>联系人</dt><dd>{{ detail.customer_contact_summary?.display_name || '未填写' }}</dd></dl><div v-if="detail.linked_quotations.length || detail.linked_samples.length || detail.linked_sales_orders.length" class="relations"><h3>关联单据</h3><button v-for="quote in detail.linked_quotations" :key="quote.id" class="related-link" @click="quoteCreated(quote.id)">报价 {{ quote.quotation_number }}<small v-if="quote.accepted_version_id && quote.outcome_status === 'WON'">客户已接受</small></button><button v-for="sample in detail.linked_samples" :key="sample.id" class="related-link" @click="router.push({ name: 'sample-detail', params: { sampleId: sample.id } })">样品 {{ sample.request_number }}<small>{{ sample.status_display }}</small></button><button v-for="order in detail.linked_sales_orders" :key="order.id" class="related-link" @click="router.push({ name: 'sales-order-detail', params: { orderId: order.id } })">销售订单 {{ order.order_number }}<small>{{ order.status_display }}</small></button></div></section>
        </aside>
      </div>
    </template>
    <div v-else-if="!loading" class="page-failure" role="alert"><p>{{ errorMessage || '未找到可访问的询盘' }}</p><el-button @click="load">重新加载</el-button><el-button @click="goList">返回询盘列表</el-button></div>
    <InquiryActionDialog v-model="lifecycleVisible" :title="lifecycleTitle"
      :subtitle="lifecycleForm.action === 'RESPOND' ? '已分配 → 已首响' : lifecycleForm.action === 'CONFIRM' ? '已首响 → 需求确认' : lifecycleForm.action === 'LOST' ? '终止询盘主流程' : `${detail?.status_display || ''} · 新增沟通记录`"
      :width="communicationAction ? 760 : 520" :height="communicationAction ? 600 : lifecycleForm.action === 'CONFIRM' ? 372 : 492"
      :confirm-label="lifecycleForm.action === 'RESPOND' ? '确认记录首响' : lifecycleForm.action === 'CONFIRM' ? '确认需求' : lifecycleForm.action === 'LOST' ? '确认标记丢失' : '确认记录'"
      :confirm-width="['RESPOND', 'LOST'].includes(lifecycleForm.action) ? 126 : 96" :cancel-width="lifecycleForm.action === 'CONFIRM' ? 96 : 92" :cancel-label="lifecycleForm.action === 'CONFIRM' ? '返回检查' : '取消'" :danger="lifecycleForm.action === 'LOST'" :busy="acting" :error="dialogError" @confirm="submitLifecycle">
      <template v-if="lifecycleForm.action === 'CONFIRM'">
        <InquiryNotice tone="warning" title="确认后直接进入待报价">当前流程不增加主管审核；如信息不足，请先返回详情补充。</InquiryNotice>
        <ul class="inquiry-check-list"><li><b>✓</b>已确认 {{ detail?.items.length || 0 }} 条产品需求与数量</li><li :class="{ incomplete: !detail?.trade_term_code }"><b>{{ detail?.trade_term_code ? '✓' : '—' }}</b>贸易条款：{{ [detail?.trade_term_code, detail?.trade_term_place].filter(Boolean).join(' ') || '未填写' }}</li><li :class="{ incomplete: !detail?.delivery_requirement }"><b>{{ detail?.delivery_requirement ? '✓' : '—' }}</b>{{ detail?.delivery_requirement ? `目标交期：${detail.delivery_requirement}` : '目标交期未填写，请核对客户需求' }}</li></ul>
      </template>
      <template v-else>
        <InquiryNotice v-if="lifecycleForm.action === 'RESPOND'" title="首次回复计时将在确认后结束">系统同时记录沟通方式、发生时间、操作者与实际内容。</InquiryNotice>
        <InquiryNotice v-else-if="communicationAction" title="报价状态不会被沟通记录覆盖">本次记录进入询盘时间轴；报价状态继续由报价模块维护。</InquiryNotice>
        <InquiryNotice v-else tone="danger" title="此操作会停止当前询盘流程">不会删除沟通、报价与附件；丢失原因将进入审计和分析报表。</InquiryNotice>
        <el-form label-position="top" :disabled="acting">
          <div v-if="communicationAction" class="inquiry-form-grid">
            <el-form-item label="沟通方式" required><el-select v-model="lifecycleForm.communicationType" popper-class="inquiry-v4-select"><el-option v-for="item in [{ code: 'EMAIL', label: '邮件' }, { code: 'PHONE', label: '电话' }, { code: 'MEETING', label: '会议' }, { code: 'VIDEO', label: '视频' }, { code: 'WECHAT', label: '微信' }, { code: 'WHATSAPP', label: 'WhatsApp' }, { code: 'OTHER', label: '其他' }]" :key="item.code" :value="item.code" :label="item.label"/></el-select></el-form-item>
            <el-form-item label="发生时间" required><el-date-picker popper-class="inquiry-v4-select" v-model="lifecycleForm.occurredAt" type="datetime" format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DDTHH:mm:ssZ"/></el-form-item>
          </div>
          <el-form-item :label="lifecycleForm.action === 'RESPOND' ? '沟通内容' : communicationAction ? '客户反馈' : '丢失原因'" required>
            <InquiryWangEditor v-if="communicationAction" v-model="lifecycleForm.content" compact :show-upload-notice="false" :upload-url="imageUploadUrl" :upload-etag="etag || ''" :maxlength="2000" :inert="acting" placeholder="记录已发生的沟通内容、客户反馈和后续安排。" @update:upload-etag="etag = $event"/>
            <el-input v-else v-model="lifecycleForm.content" type="textarea" :rows="5" maxlength="500" :input-style="{ height: '132px' }" placeholder="请填写实际丢失原因"/>
          </el-form-item>
        </el-form>
        <p class="inquiry-dialog-hint">{{ lifecycleForm.action === 'RESPOND' ? '支持粘贴或上传沟通图片 · 最多 2000 字' : communicationAction ? '请记录已经发生的事实，不要填写尚未发送给客户的内部判断。' : '如仍需继续跟进，请取消并使用“记录客户跟进”。' }}</p>
      </template>
    </InquiryActionDialog>
    <InquiryActionDialog v-model="assignVisible" :title="detail?.owner ? '转交负责人' : '分配负责人'" :subtitle="detail?.owner ? `负责人：${detail.owner.display_name} → 新负责人` : '新询盘 → 已分配'" :width="500" :height="detail?.owner ? 472 : 450" :confirm-label="detail?.owner ? '确认转交' : '确认分配'" :busy="acting" :disabled="!options" :error="dialogError" @confirm="submitAction('assign')">
      <InquiryNotice :tone="detail?.owner ? 'info' : 'warning'" :title="detail?.owner ? '转交不会重置询盘进度' : '该询盘尚未分配'">{{ detail?.owner ? '原负责人和转交原因会保留在分配历史中。' : '建议结合国家、客户等级和业务员负载选择负责人。' }}</InquiryNotice>
      <el-form label-position="top" :disabled="acting"><el-form-item :label="detail?.owner ? '新负责人' : '负责人'" required><el-select popper-class="inquiry-v4-select" v-model="assignForm.ownerId" filterable placeholder="请选择负责人"><el-option v-for="owner in options?.owners" :key="owner.id" :value="owner.id" :label="`${owner.display_name}（${owner.employee_code}）`" :disabled="owner.id === detail?.owner?.id"/></el-select></el-form-item><el-form-item :label="detail?.owner ? '转交说明' : '分配说明'"><el-input v-model="assignForm.reason" type="textarea" maxlength="500" :input-style="{ height: detail?.owner ? '88px' : '72px' }"/></el-form-item></el-form>
      <p class="inquiry-dialog-hint">{{ detail?.owner ? '询盘负责人会更新；已有任务仍按任务记录处理。' : '确认后记录分配人、原负责人、新负责人和分配时间。' }}</p>
    </InquiryActionDialog>
    <InquiryActionDialog v-model="contactVisible" title="补充联系人" subtitle="为当前询盘关联有效联系人" :width="480" :height="408" confirm-label="确认补充" :busy="acting" :disabled="contactsLoading || !!contactsError" :error="dialogError || contactsError" @confirm="submitAction('contact')">
      <InquiryNotice title="只补充联系人事实">已提交询盘的客户、来源和产品需求不会在此窗口修改。</InquiryNotice>
      <el-form label-position="top" :disabled="acting"><el-form-item label="联系人" required><el-select popper-class="inquiry-v4-select" v-model="contactForm.contactId" filterable placeholder="请选择当前客户联系人" no-data-text="当前客户暂无有效联系人"><el-option v-for="contact in contacts" :key="contact.id" :value="contact.id" :label="contact.display_name"/></el-select></el-form-item></el-form>
      <p class="inquiry-dialog-hint">列表仅显示当前客户名下的有效联系人；敏感邮箱继续按权限脱敏。</p>
      <el-button v-if="contactsError" :disabled="acting" @click="loadContacts()">重新加载联系人</el-button>
    </InquiryActionDialog>
    <InquiryActionDialog v-model="invalidVisible" title="标记无效" subtitle="关闭无业务价值的询盘" :width="500" :height="482" confirm-label="确认标记" danger :busy="acting" :disabled="!options" :error="dialogError" @confirm="submitAction('invalid')">
      <InquiryNotice tone="warning" title="关闭后仍保留完整记录">无效询盘不计入转化率，但可通过筛选查看并保留审计证据。</InquiryNotice>
      <el-form label-position="top" :disabled="acting"><el-form-item label="无效原因" required><el-select popper-class="inquiry-v4-select" v-model="invalidForm.reasonCode" placeholder="请选择原因"><el-option v-for="code in options?.invalid_reason_codes" :key="code" :value="code" :label="invalidReasons[code] || code"/></el-select></el-form-item><el-form-item label="说明"><el-input v-model="invalidForm.reasonDetail" type="textarea" maxlength="1000" :input-style="{ height: '88px' }"/></el-form-item></el-form>
    </InquiryActionDialog>
    <InquiryActionDialog v-model="slaVisible" title="处理时限规则与记录" subtitle="北京时间 · 当前规则和各阶段实际计时记录" :width="680" :height="640" confirm-label="知道了" cancel-label="关闭" @confirm="slaVisible = false">
      <section v-if="handlingRule" class="handling-rule">
        <h3>{{ handlingRule.name }}</h3>
        <dl><template v-for="rule in handlingRuleRows" :key="rule.stage"><dt>{{ handlingStageLabel(rule.stage) }}</dt><dd>{{ handlingTargetLabel(rule.minutes) }}</dd></template></dl>
        <template v-if="handlingRule.work_calendar">
          <p>{{ workCalendarDescription(handlingRule.work_calendar) }}</p>
          <p>大小周交替，周日固定休息；{{ handlingRule.work_calendar.rest_saturday }} 为休息的周六基准。</p>
          <p>午休、下班和休息日不计时，截止时间自动顺延。</p>
        </template>
        <p v-else>本规则按连续时间计算。</p>
        <p class="working-time-note">首次回复从提交开始，需求确认从首次回复完成后开始。分配与首次回复同时计时；转交和草稿修改不重置当前计时。规则修改仅影响新开始的环节，已有记录保留原截止时间。</p>
      </section>
      <InquiryNotice v-else title="暂未配置处理时限">当前没有启用的询盘时限规则。</InquiryNotice>
      <h3 class="handling-history-title">阶段处理记录</h3>
      <p v-if="!detail?.sla.length" class="inquiry-dialog-hint">暂无计时记录。历史询盘不会追溯计算超时。</p>
      <section v-for="record in handlingHistory" :key="record.id" class="sla-record">
        <strong>{{ handlingStageLabel(record.stage_code) }} · {{ handlingStatusLabel(record.status, record.completed_at, record.next_deadline_at, now) }}</strong>
        <p v-if="record.progress_context?.round_number">第 {{ record.progress_context.round_number }} 轮<span v-if="record.progress_context.source_label"> · {{ record.progress_context.source_label }}</span></p>
        <p v-if="record.progress_context?.entry_reason" class="working-time-note">{{ record.progress_context.entry_reason }}</p>
        <p v-if="record.progress_context?.completion_reason">{{ record.progress_context.completion_reason }}<span v-if="record.status==='CANCELLED' && record.breached_at">（结束前已超时）</span></p>
        <p>{{ record.work_calendar ? '按工作时间' : '按原连续时间规则' }}计算<span v-if="record.target_minutes"> · 目标 {{ record.target_minutes / 60 }} 小时</span></p>
        <p>开始：{{ formatInquiryTime(record.started_at) }} · 截止：{{ formatInquiryTime(record.next_deadline_at) }}</p>
        <p>完成：{{ formatInquiryTime(record.completed_at) }}</p>
      </section>
    </InquiryActionDialog>
    <QuotationFromInquiryDialog v-if="detail && allowed('create_quotation')" v-model="quoteVisible" :inquiry-id="inquiryId" :inquiry-etag="etag || ''" @created="quoteCreated"/>
    <TaskCreateDialog v-if="detail && canCreateTask" v-model="taskVisible" :fixed-inquiry-id="detail.id" :fixed-inquiry-number="detail.inquiry_number" :fixed-customer-id="detail.customer.id" :fixed-customer-name="detail.customer.name" :default-assignee-id="detail.owner?.id || ''" @created="loadTasks()"/>
  </section>
</template>
<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;
@use '@/styles/crm/tokens' as token;
.working-time-note { margin-top: 8px; color: token.$crm-text-muted; font-size: 12px; line-height: 20px; }
.handling-rule { padding: 14px; border: 1px solid token.$crm-border-default; border-radius: 6px; h3 { margin: 0 0 12px; font-size: 15px; } dl { display: grid; grid-template-columns: 132px 1fr; gap: 8px; margin: 0 0 12px; } dd { margin: 0; } p { margin: 6px 0; line-height: 22px; } }
.sla-parallel { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px; margin-top: 10px; padding: 10px 13px; border: 1px solid token.$crm-border-default; font-size: 12px; small { width: 100%; color: token.$crm-text-muted; } }
.handling-history-title { margin: 20px 0 12px; font-size: 15px; }
.inquiry-detail-page {
  --el-color-primary: #{token.$crm-primary}; --el-color-primary-light-9: #{token.$crm-color-selected}; --el-border-color: #{token.$crm-border-default}; --el-border-radius-base: 8px;
  height: auto; overflow-y: visible; padding: 0; background: transparent; color: token.$crm-text-primary; font: 13px/20px var(--erp-font-body);
  :deep(.el-button) { margin-left: 0; height: 32px; border-radius: 8px; font-family: inherit; }
  :deep(.el-button--primary) { background: var(--erp-button-primary-surface); border-color: var(--erp-button-primary-border); color: token.$crm-text-inverse; }
  :deep(.el-button--danger) { background: token.$crm-danger; color: var(--erp-color-text-inverse); }
  :deep(.el-button.is-disabled) { opacity: .6; }
  :deep(.el-progress-bar__inner) { background: token.$crm-primary; }
  button:focus-visible, a:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 3px; }
  min-width: 0
}
h1,h2,h3,p { margin: 0; } h2 { font-size: 16px; line-height: 24px; font-weight: 700; } h3 { font-size: 14px; }
button { font: inherit; cursor: pointer; } button:disabled { cursor: not-allowed; }
.text-link { border: 0; padding: 0; background: none; color: token.$crm-info; font-size: 12px; text-decoration: none; } .back-link { font-size: 14px; height: 22px; }
.detail-header { min-height: 0; margin-bottom: 14px; }.heading-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-top: 0; }.heading-copy { min-width: 0; }.heading-copy h1 { font: 700 36px/44px var(--erp-font-body); overflow-wrap: anywhere; }.heading-copy p { color: token.$crm-text-muted; line-height: 22px; overflow-wrap: anywhere; }.header-actions { display: flex; justify-content: flex-end; gap: 8px; flex-shrink: 0; }.header-actions :deep(.el-button) { height: 32px; min-width: 92px; font-size: 13px; } .header-actions :deep(.el-button:nth-child(2)) { min-width: 116px; } .header-actions :deep(.el-button--primary) { min-width: 122px; }
.content-grid { display: grid; grid-template-columns: minmax(0,1fr) minmax(280px,30%); align-items: start; gap: 14px; }.panel {
 @include detail.surface; }.section-heading { display: flex; justify-content: space-between; align-items: center; gap: 12px; }.dossier-section { padding: 16px; }.dossier-section + .dossier-section { border-top: 1px solid token.$crm-border-subtle; }.summary-section { min-height: 142px; padding-bottom: 11px; }.summary-tags { display: flex; gap: 6px; }.demand-box { @include detail.inset; margin-top: 17px; padding: 12px 16px; font-size: 12px; line-height: 22px; overflow-wrap: anywhere; }.demand-box p { white-space: pre-wrap; }.demand-box small { display: block; color: token.$crm-text-secondary; font-size: 12px; margin-top: 4px; }.products-section { min-height: 210px; }.products-scroll { overflow: auto; margin-top: 7px; border: 1px solid token.$crm-border-default; border-radius: 8px; }.products-table { width: 100%; border-collapse: collapse; table-layout: fixed; text-align: left; font-size: 12px; }.products-table th,.products-table td { padding: 10px 8px; line-height: 20px; vertical-align: top; overflow-wrap: anywhere; border-bottom: 1px solid token.$crm-border-subtle; }.products-table thead { position: sticky; top: 0; background: token.$crm-color-subtle; color: token.$crm-text-secondary; }.products-table thead th { padding-top: 7px; padding-bottom: 7px; font-weight: 400; }.products-table tr:last-child > * { border-bottom: 0; }.pending { color: token.$crm-primary; }
.attachments-section { min-height: 116px; }.attachment-grid { display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 12px; margin-top: 10px; }.attachment { display: flex; align-items: center; text-align: left; gap: 8px; padding: 7px; min-height: 56px; min-width: 0; background: transparent; border: 1px solid token.$crm-border-default; border-radius: 8px; }.attachment:disabled { opacity: .6; }.file-badge { display: grid; flex-shrink: 0; place-items: center; width: 36px; height: 36px; border-radius: 3px; font-size: 11px; font-weight: 700; background: var(--erp-tag-success-background); color: var(--erp-tag-success-text); }.file-badge.document { background: var(--erp-tag-brand-background); color: var(--erp-tag-brand-text); }.file-caption { display: grid; gap: 5px; min-width: 0; font-size: 12px; }.file-caption strong { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 500; }.file-caption small { font-size: 12px; color: token.$crm-text-muted; }
.communication-section { min-height: 215px; }.timeline-scroll { margin-top: 12px; }.timeline-row { position: relative; display: grid; grid-template-columns: 14px 125px 60px minmax(0,1fr) 150px; gap: 10px; min-height: 40px; align-items: start; font-size: 12px; line-height: 20px; padding: 5px 0; }.timeline-row strong { font-weight: 500; overflow-wrap: anywhere; }.timeline-row > span:not(.timeline-dot),.timeline-row time { color: token.$crm-text-muted; }.timeline-row p { color: token.$crm-text-secondary; overflow-wrap: anywhere; }.timeline-row time { text-align: right; font-size: 11px; }.timeline-dot { position: relative; z-index: 1; width: 10px; height: 10px; margin: 5px 2px; border-radius: 50%; background: token.$crm-primary; }.timeline-dot.communication { background: token.$crm-info; }.timeline-row:not(:last-child)::before { position: absolute; content: ''; left: 6px; top: 15px; bottom: -15px; width: 2px; background: token.$crm-border-subtle; }.communication-actions { display: flex; gap: 8px; margin-top: 6px; }
.work-rail { display: grid; gap: 14px; min-width: 0; }.work-rail .panel { padding: 16px; }.work-rail h2 { padding-bottom: 7px; border-bottom: 1px solid token.$crm-border-subtle; }.work-rail .section-heading { border-bottom: 1px solid token.$crm-border-subtle; padding-bottom: 7px; }.work-rail .section-heading h2 { padding: 0; border: 0; }.sla-panel { min-height: 158px; }.sla-summary { @include detail.inset; margin-top: 12px; padding: 10px 13px; }.sla-head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; margin-bottom: 9px; }.sla-head strong { font-size: 18px; color: token.$crm-primary; }.sla-head span { font-size: 12px; color: token.$crm-text-muted; }.sla-foot { display: flex; justify-content: space-between; gap: 8px; margin-top: 8px; color: token.$crm-text-muted; font-size: 11px; }.overdue .sla-head strong { color: token.$crm-danger; }.owner-panel { min-height: 103px; }.owner-row { display: flex; align-items: center; gap: 12px; margin-top: 10px; }.assignment-history { margin-top: 12px; font-size: 12px; line-height: 22px; article { padding: 8px 0; border-top: 1px solid token.$crm-border-subtle; } time { display: block; color: token.$crm-text-muted; } p { overflow-wrap: anywhere; } } .owner-row > .el-button { margin-left: auto; }.owner-avatar { display: grid; place-items: center; width: 36px; height: 36px; background: token.$crm-color-subtle; border-radius: 50%; }.owner-avatar img { width: 18px; height: 18px; }.next-panel { min-height: 164px; position: relative; padding-bottom: 14px !important; }.next-action { display: flex; gap: 14px; margin-top: 14px; min-height: 90px; }.next-action strong { font-weight: 500; line-height: 22px; }.next-action > div { min-width: 0; flex: 1; }.next-action p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 4px; font-size: 12px; color: token.$crm-text-muted; line-height: 20px; }.next-action small { max-width: 290px; overflow-wrap: anywhere; display: block; margin-top: 8px; color: token.$crm-primary; font-size: 12px; }.task-icon { display: grid; place-items: center; flex-shrink: 0; width: 38px; height: 38px; border-radius: 50%; background: var(--erp-color-subtle); }.task-icon img { width: 20px; height: 20px; }.action-buttons { display: flex; justify-content: flex-end; margin-top: 0; position: absolute; right: 17px; top: 109px; } .action-buttons :deep(.el-button) { min-width: 116px; }.info-panel { min-height: 328px; }.info-panel dl { display: grid; grid-template-columns: 104px minmax(0,1fr); gap: 10px; font-size: 12px; line-height: 20px; margin: 16px 0 0; }.info-panel dt { color: token.$crm-text-muted; }.info-panel dd { margin: 0; overflow-wrap: anywhere; }.info-panel dd button { float: right; margin-left: 6px; }.info-panel a { color: token.$crm-info; }.relations,.related-tasks { margin-top: 14px; border-top: 1px solid token.$crm-border-subtle; padding-top: 10px; }.related-link { display: block; border: 0; background: none; color: token.$crm-info; font-size: 12px; padding: 7px 0; text-align: left; overflow-wrap: anywhere; }.related-link small { color: token.$crm-text-muted; margin-left: 10px; }.empty-line { color: token.$crm-text-muted; font-size: 12px; line-height: 24px; margin-top: 10px; }.inline-error { color: token.$crm-danger; font-size: 12px; margin-top: 10px; }.inline-error button { margin-left: 10px; }.section-error { margin-bottom: 12px; }.page-failure { display: grid; justify-items: center; justify-content: center; gap: 16px; padding: 100px 0; }.dialog-form { margin-top: 16px; }.dialog-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }.dialog-form :deep(.el-select),.dialog-form :deep(.el-date-editor) { width: 100%; }.sla-record { margin-top: 16px; padding-bottom: 12px; border-bottom: 1px solid token.$crm-border-subtle; }.sla-record p { margin-top: 6px; font-size: 12px; }
.inquiry-detail-page .products-scroll { border-radius: 5px; }
.inquiry-detail-page .products-table { min-width: 780px; border-collapse: separate; border-spacing: 0; }
.inquiry-detail-page .products-table :is(th, td) { padding: 0 8px !important; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; vertical-align: middle; }
.inquiry-detail-page .products-table thead th { height: 44px; border-bottom: 1px solid token.$crm-border-default; }
.inquiry-detail-page .products-table tbody :is(th, td) { height: 34px !important; border-bottom-color: token.$crm-border-default; }
.inquiry-detail-page .products-table tbody tr:hover > * { background: token.$crm-color-row-hover; }
@media (max-width:1200px) { .content-grid { grid-template-columns:minmax(0,1fr); } .work-rail { grid-template-columns:repeat(2,minmax(0,1fr)); } .heading-row { flex-wrap:wrap; gap:14px; } .header-actions { flex-wrap:wrap; } }
@media (max-width:680px) { .work-rail { grid-template-columns:minmax(0,1fr); } .attachment-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .inquiry-form-grid { grid-template-columns:minmax(0,1fr); } }
</style>
