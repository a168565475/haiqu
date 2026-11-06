<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import type { RouteLocationNormalized } from 'vue-router'
import { Button as VanButton, Field as VanField, Loading as VanLoading, Icon as VanIcon, Popup as VanPopup, Picker as VanPicker, PickerGroup as VanPickerGroup, DatePicker as VanDatePicker, TimePicker as VanTimePicker, showDialog } from 'vant'
import type { PickerConfirmEventParams, PickerOption } from 'vant'
import 'vant/es/popup/style'
import 'vant/es/field/style'
import 'vant/es/picker-group/style'
import 'vant/es/date-picker/style'
import 'vant/es/time-picker/style'
import WorkPage from '@/components/WorkPage.vue'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { createRequestId } from '@/utils/requestId'
import { buildIssueLines, materialAttributes, omittedQuantity, pipePlan, quantityText, restoreIssueQuantities, selectedQuantityError } from '@/utils/materialQuantities'
import { createMaterialIssue, fetchMaterialIssue, fetchMaterialIssueOptions, fetchMaterialIssueProducts, fetchMaterialRequirements, submitMaterialIssue, updateMaterialIssue } from '@/api/materialIssues'
import type { IssueWritePayload, MaterialIssue, MaterialIssueOptions, MaterialIssueProduct, MaterialRequirement, MaterialRequirementResponse, VersionedIssue } from '@/types/materialIssue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const query = (key: string) => typeof route.query[key] === 'string' ? route.query[key] as string : ''
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const actionError = ref('')
const success = ref('')
const ready = ref(false)
const issue = ref<MaterialIssue | null>(null)
const persistedId = ref('')
const etag = ref('')
const options = ref<MaterialIssueOptions>({ production_tasks: [], workshops: [], recipients: [] })
const product = ref<MaterialIssueProduct | null>(null)
const requirements = ref<MaterialRequirement[]>([])
const blockers = ref<MaterialRequirementResponse['blockers']>([])
const selected = reactive<Record<string, string>>({})
const context = reactive({ production_task_id: '', product_line_id: '', workshop_id: '' })
const recipientId = ref('')
const remark = ref('')
const issueAt = ref('')
const showIssueTime = ref(false)
const showRecipient = ref(false)
const pickerRecipient = ref<string[]>([])
const pickerTab = ref(0)
const pickerDate = ref<string[]>([])
const pickerTime = ref<string[]>([])
const createAttempt = ref<IssueWritePayload | null>(null)
const createUncertain = ref(false)
const needsReload = ref(false)
let requestId = createRequestId()
let savedContent = ''
let generation = 0
let active = true
let keepingDraftRoute = false
const submitted = computed(() => issue.value && ['PENDING_REVIEW', 'ISSUED'].includes(issue.value.status))
const canChange = computed(() => auth.hasPermission('material_issues.change_materialissue'))
const canSubmit = computed(() => auth.hasPermission('material_issues.submit_materialissue'))
const canCreate = computed(() => auth.hasPermission('material_issues.add_materialissue'))
const fieldsLocked = computed(() => saving.value || createUncertain.value || Boolean(persistedId.value && !canChange.value))
watch(fieldsLocked, locked => { if (locked) { showIssueTime.value = false; showRecipient.value = false } })
const recipients = computed(() => options.value.recipients.filter(item => item.workshop_id === context.workshop_id))
const recipientColumns = computed(() => recipients.value.map(person => ({ text: person.name, value: person.id })))
const recipientName = computed(() => recipients.value.find(person => person.id === recipientId.value)?.name || '请选择领料人')
const taskNumber = computed(() => issue.value?.production_task?.task_number
  || options.value.production_tasks.find(item => item.id === context.production_task_id)?.task_number || '')
const workshopName = computed(() => issue.value?.workshop?.name
  || options.value.workshops.find(item => item.id === context.workshop_id)?.name || '')
const selectedCount = computed(() => requirements.value.filter(row => !omittedQuantity(selected[row.requirement_id])).length)
const returnReason = computed(() => [...(issue.value?.audit_events || [])].reverse().find(event => event.action === 'RETURNED')?.reason)
const currentDateTime = (value?: string | null) => {
  const date = value ? new Date(value) : new Date()
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date).replace(' ', 'T')
}
// 保留已有单据年份，避免组件默认十年窗口把历史时间截断；提交仍沿用北京时间。
const pickerYear = computed(() => Number((issueAt.value || currentDateTime()).slice(0, 4)))
const minPickerDate = computed(() => new Date(Math.min(Number(currentDateTime().slice(0, 4)) - 10, pickerYear.value), 0, 1))
const maxPickerDate = computed(() => new Date(Math.max(Number(currentDateTime().slice(0, 4)) + 10, pickerYear.value), 11, 31))
function openIssueTime() {
  if (fieldsLocked.value) return
  const [date, time] = (issueAt.value || currentDateTime()).split('T')
  pickerDate.value = date!.split('-')
  pickerTime.value = time!.split(':')
  pickerTab.value = 0
  showIssueTime.value = true
}
function confirmIssueTime(values: PickerConfirmEventParams[]) {
  if (fieldsLocked.value) return
  issueAt.value = `${values[0]!.selectedValues.join('-')}T${values[1]!.selectedValues.join(':')}`
  showIssueTime.value = false
}
function formatPickerOption(type: string, option: PickerOption) {
  const labels: Record<string, string> = { year: '年', month: '月', day: '日', hour: '时', minute: '分' }
  return { ...option, text: `${option.text}${labels[type] || ''}` }
}
const rowError = (row: MaterialRequirement) => selectedQuantityError(selected[row.requirement_id] || '', row, requirements.value, selected)
function formatIssueQuantity(value: string, row: MaterialRequirement) {
  // 拒绝整次非法输入，避免粘贴 1e3、负数等内容时被拼成另一个数量。
  return /^\d*(?:\.\d*)?$/.test(value) ? value.replace(/^\./, '0.') : selected[row.requirement_id] || ''
}
const hasRawBlocker = computed(() => blockers.value.some(item => item.section_code !== 'SEMI'))
const recordQuery = () => ({ ...route.query, ...context, ...(persistedId.value ? { issue_id: persistedId.value } : {}) })
function openRecords() { void router.push({ path: '/issue-records', query: recordQuery() }) }
function openRecipient() {
  if (fieldsLocked.value || !recipients.value.length) return
  pickerRecipient.value = recipientId.value ? [recipientId.value] : []
  showRecipient.value = true
}
function confirmRecipient({ selectedValues }: PickerConfirmEventParams) {
  if (fieldsLocked.value) return
  const person = recipients.value.find(item => item.id === selectedValues[0])
  if (person) recipientId.value = person.id
  else actionError.value = '该领料人已不可用，请重新选择。'
  showRecipient.value = false
}

function writePayload(): IssueWritePayload {
  if (!recipientId.value || !recipients.value.some(item => item.id === recipientId.value)) throw new Error('请选择当前车间有效的领料人。')
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(issueAt.value)) throw new Error('请填写领料时间。')
  const lines = buildIssueLines(requirements.value, selected)
  if (!lines.length) throw new Error('请至少填写一项大于 0 的申请数量。')
  if (hasRawBlocker.value && requirements.value.some(row => row.line_type === 'RAW' && !omittedQuantity(selected[row.requirement_id]))) {
    throw new Error('当前原材料需求存在未解析项，请先在 ERP 处理提示；可用半成品仍可单独申请。')
  }
  return { ...context, recipient_workshop_employee_id: recipientId.value, issue_at: `${issueAt.value}:00+08:00`, remark: remark.value, lines }
}
function remember(result: VersionedIssue) {
  persistedId.value = result.data.id
  etag.value = result.etag
  issue.value = result.data
}
async function keepDraftRoute() {
  if (query('issue_id') !== persistedId.value) {
    keepingDraftRoute = true
    try { await router.replace({ path: '/issue', query: { ...route.query, ...context, issue_id: persistedId.value } }) }
    finally { keepingDraftRoute = false }
  }
}
async function initialize() {
  const run = ++generation
  ready.value = false
  showIssueTime.value = false
  showRecipient.value = false
  loading.value = true
  loadError.value = ''; actionError.value = ''; success.value = ''
  issue.value = null; product.value = null; requirements.value = []; blockers.value = []
  persistedId.value = ''; etag.value = ''; savedContent = ''
  createAttempt.value = null; createUncertain.value = false; needsReload.value = false; requestId = createRequestId()
  Object.keys(selected).forEach(key => delete selected[key])
  try {
    const id = query('issue_id')
    let originalIssue: MaterialIssue | undefined
    if (id) {
      const result = await fetchMaterialIssue(id)
      if (!active || run !== generation) return
      remember(result)
      originalIssue = result.data
      if (!result.data.production_task || !result.data.product || !result.data.workshop) throw new Error('原申请缺少生产单、产品或车间，请在 ERP 核对。')
      Object.assign(context, { production_task_id: result.data.production_task.id, product_line_id: result.data.product.id, workshop_id: result.data.workshop.id })
      for (const key of ['production_task_id', 'product_line_id', 'workshop_id'] as const) {
        if (query(key) && query(key) !== context[key]) throw new Error('领料单与当前生产单、产品或车间不一致，请返回列表重新进入。')
      }
      product.value = result.data.product
      recipientId.value = result.data.recipient?.id || ''
      issueAt.value = currentDateTime(result.data.issue_at)
      remark.value = result.data.remark
      if (submitted.value) return
    } else {
      const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
      const keys = ['production_task_id', 'product_line_id', 'workshop_id', 'schedule_product_id']
      if (keys.some(key => !uuid.test(query(key))) || !['METAL', 'CUTTING', 'SEWING', 'ASSEMBLY'].includes(query('plan_category'))) {
        throw new Error('领料入口信息不完整，请从生产任务列表选择产品和车间后进入。')
      }
      Object.assign(context, { production_task_id: query('production_task_id'), product_line_id: query('product_line_id'), workshop_id: query('workshop_id') })
      recipientId.value = ''; issueAt.value = currentDateTime(); remark.value = ''
    }
    const [loadedOptions, products, data] = await Promise.all([
      fetchMaterialIssueOptions(context.production_task_id), fetchMaterialIssueProducts(context.production_task_id),
      fetchMaterialRequirements({ ...context, issue_id: id || undefined, plan_category: query('plan_category') || undefined }),
    ])
    if (!active || run !== generation) return
    options.value = loadedOptions
    product.value = product.value || products.find(item => item.id === context.product_line_id) || null
    if (!product.value || !loadedOptions.workshops.some(item => item.id === context.workshop_id)) throw new Error('产品或车间已不可用，请返回任务列表刷新。')
    if (!id && !loadedOptions.production_tasks.some(item => item.id === context.production_task_id)) throw new Error('生产单当前不可领料，请返回任务列表刷新。')
    requirements.value = data.items; blockers.value = data.blockers
    if (originalIssue) Object.assign(selected, restoreIssueQuantities(originalIssue.lines, data.items))
    if (!recipientId.value && recipients.value.length === 1) recipientId.value = recipients.value[0]!.id
    if (originalIssue) {
      // 旧数量可能已超出现有库存，仍须允许加载并调低，不能在这里执行提交校验。
      savedContent = JSON.stringify({ ...context, recipient_workshop_employee_id: recipientId.value, issue_at: `${issueAt.value}:00+08:00`, remark: remark.value,
        lines: originalIssue.lines.map(line => ({ requirement_id: line.requirement_id, requested_quantity: quantityText(line.requested_quantity) })) })
    }
    ready.value = true
  } catch (error) {
    if (active && run === generation) loadError.value = errorMessage(error, '领料数据加载失败，请重试。')
  } finally { if (active && run === generation) loading.value = false }
}

async function save() {
  if (!ready.value || saving.value || submitted.value || !canSubmit.value || needsReload.value) return
  actionError.value = ''
  const run = generation
  saving.value = true
  try {
    const payload = createUncertain.value && createAttempt.value ? createAttempt.value : writePayload()
    if (!persistedId.value) {
      if (!canCreate.value) throw new Error('当前账号没有新建领料申请权限。')
      createAttempt.value ||= { ...payload, schedule_product_id: query('schedule_product_id'), plan_category: query('plan_category'), client_request_id: requestId }
      let created: VersionedIssue
      try { created = await createMaterialIssue(createAttempt.value) }
      catch (error) {
        const definiteRejection = isAxiosError(error) && [400, 401, 403, 404, 422].includes(error.response?.status || 0)
        createUncertain.value = !definiteRejection
        if (definiteRejection) { createAttempt.value = null; requestId = createRequestId() }
        throw error
      }
      if (!active || run !== generation) return
      remember(created)
      savedContent = JSON.stringify({ production_task_id: payload.production_task_id, product_line_id: payload.product_line_id, workshop_id: payload.workshop_id,
        recipient_workshop_employee_id: payload.recipient_workshop_employee_id, issue_at: payload.issue_at, remark: payload.remark, lines: payload.lines })
      createAttempt.value = null; createUncertain.value = false
      await keepDraftRoute()
    } else if (JSON.stringify(payload) !== savedContent) {
      if (!canChange.value) throw new Error('当前账号没有修改该领料申请的权限。')
      const updated = await updateMaterialIssue(persistedId.value, payload, etag.value)
      if (!active || run !== generation) return
      remember(updated); savedContent = JSON.stringify(payload)
    }
    if (submitted.value) {
      success.value = issue.value?.status === 'ISSUED' ? '这张申请已由仓库确认发料。' : '已核对，这张申请正在等待仓库发料。'
      return
    }
    const result = await submitMaterialIssue(persistedId.value, etag.value, latest => {
      if (active && run === generation) {
        if (['DRAFT', 'RETURNED'].includes(latest.data.status) && latest.etag !== etag.value) needsReload.value = true
        remember(latest)
      }
    })
    if (!active || run !== generation) return
    remember(result)
    success.value = result.data.status === 'ISSUED' ? '申请已提交，仓库已确认发料。' : '申请已提交，等待仓库发料。'
  } catch (error) {
    if (active && run === generation) {
      if (persistedId.value && isAxiosError(error) && [409, 412].includes(error.response?.status || 0)) needsReload.value = true
      actionError.value = errorMessage(error, '提交未完成，请核对后重试。')
    }
  } finally { if (active && run === generation) saving.value = false }
}

async function allowLeave(to: RouteLocationNormalized) {
  // 身份失效必须允许登录跳转；内部补入草稿单号也不能被提交锁挡住。
  if (to.path === '/login' || keepingDraftRoute && to.path === '/issue' && to.query.issue_id === persistedId.value) return true
  if (saving.value || createUncertain.value) {
    await showDialog({ title: '请先核对本次申请', message: '本次领料保存结果尚未确认，请留在当前页面继续核对，避免重复申请。', confirmButtonText: '继续核对' })
    return false
  }
  return true
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (saving.value || createUncertain.value) { event.preventDefault(); event.returnValue = '' }
}
onBeforeRouteLeave(allowLeave)
onBeforeRouteUpdate(allowLeave)
window.addEventListener('beforeunload', beforeUnload)
watch(() => route.fullPath, () => {
  // 创建后仅补入已保存单号，保持本轮表单和提交状态。
  if (persistedId.value && query('issue_id') === persistedId.value
    && ['production_task_id', 'product_line_id', 'workshop_id'].every(key => query(key) === context[key as keyof typeof context])) return
  void initialize()
}, { immediate: true })
onBeforeUnmount(() => { active = false; generation += 1; window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <WorkPage class="issue-work-page" title="申请领料" :subtitle="taskNumber" section="issue" back-to="/">
    <div class="page-stack issue-page">
      <div v-if="loading" class="section-card loading-panel"><VanLoading vertical>正在读取领料材料</VanLoading></div>
      <div v-else-if="loadError" class="error-panel" role="alert"><p>{{ loadError }}</p><VanButton block @click="initialize">重新加载</VanButton></div>
      <template v-else>
        <details :key="context.product_line_id" class="section-card product-card">
          <summary class="product-summary">
            <span class="product-brief"><strong>{{ product?.product_name || '生产产品' }}</strong><span>{{ workshopName }}</span></span>
            <span class="product-toggle">产品详情<VanIcon name="arrow-down" aria-hidden="true" /></span>
          </summary>
          <div class="product-details">
            <p class="muted">{{ product?.product_number }} · {{ product?.specification_display || product?.specification || '规格未记录' }}</p>
            <div class="summary-grid product-facts"><span>生产单 <b>{{ taskNumber || '—' }}</b></span><span>领料车间 <b>{{ workshopName || '—' }}</b></span></div>
            <p v-if="product?.quantity" class="muted">生产数量 {{ quantityText(product.quantity) }} {{ product.unit }}</p>
            <button type="button" class="action-link" @click="openRecords">查看领料记录</button>
          </div>
        </details>
        <section v-if="submitted" class="section-card result-panel" role="status">
          <h2>{{ issue?.status === 'ISSUED' ? '仓库已发料' : '等待仓库发料' }}</h2>
          <p>{{ success || '该申请已提交，可查看申请内容和最新发料状态。' }}</p><p>申请单号：{{ issue?.issue_number }}</p>
          <VanButton block type="primary" @click="openRecords">查看申请</VanButton>
        </section>
        <template v-else-if="ready">
          <div v-if="returnReason" class="error-panel" role="alert"><b>仓库退回原因</b><p>{{ returnReason }}</p></div>
          <div v-if="persistedId" class="section-card muted">已有申请 {{ issue?.issue_number }}，继续操作会更新这张申请。</div>
          <div v-if="createUncertain" class="error-panel" role="alert">保存结果尚未确认，已暂时锁定本次内容。请点“核对并继续提交”重试原请求，避免重复申请。</div>
          <section class="section-card issue-fields" aria-label="领料信息">
            <button type="button" class="compact-field recipient-trigger" :disabled="fieldsLocked || !recipients.length" aria-haspopup="dialog" aria-label="选择领料人" @click="openRecipient">
              <span>领料人</span><span class="field-value">{{ recipientName }}<VanIcon name="arrow" aria-hidden="true" /></span>
            </button>
            <p v-if="!recipients.length" class="field-error">当前车间没有可用领料人，请在 ERP 核对员工配置。</p>
            <button type="button" class="compact-field time-trigger" :disabled="fieldsLocked" aria-haspopup="dialog" aria-label="选择领料时间（北京时间）" @click="openIssueTime">
              <span>领料时间</span><span class="field-value">{{ issueAt.replace('T', ' ') || '请选择' }}<VanIcon name="arrow" aria-hidden="true" /></span>
            </button>
          </section>
          <div v-if="blockers.length" class="error-panel" role="alert"><b>材料配置需要处理</b><p v-for="(blocker, index) in blockers" :key="index">{{ blocker.detail || '材料需求尚未解析，请在 ERP 核对。' }}</p></div>
          <p v-if="!requirements.length" class="section-card">当前产品、车间没有可申请的材料。</p>
          <article v-for="row in requirements" :key="row.requirement_id" class="section-card material-card">
            <div class="material-heading">
              <h2>{{ row.material_name }}<span class="material-spec">{{ [row.material_number, row.specification, row.color].filter(Boolean).join(' · ') || '规格未记录' }}</span></h2>
              <span class="material-kind" :class="{ 'material-kind--semi': row.line_type === 'SEMI' }">{{ row.line_type === 'SEMI' ? '半成品' : '原材料' }}</span>
            </div>
            <p v-if="row.completed_craft" class="muted">已完成工艺：{{ row.completed_craft }}</p>
            <div class="quantity-grid">
              <span>需求 <b>{{ quantityText(row.required_quantity) }}</b></span><span>已领 <b>{{ quantityText(row.internal_issued_quantity) }}</b></span>
              <span>待审核 <b>{{ quantityText(row.pending_issue_quantity) }}</b></span><span class="available">本次可领 <b>{{ quantityText(row.max_issue_quantity) }} {{ row.unit }}</b></span>
            </div>
            <VanField v-model="selected[row.requirement_id]" class="request-field" type="text" inputmode="decimal" label="本次申请" placeholder="请输入数量"
              :formatter="value => formatIssueQuantity(value, row)" :disabled="fieldsLocked" :error-message="rowError(row)" :aria-label="`${row.material_name}本次申请数量，单位${row.unit}`">
              <template #button><span class="request-unit">{{ row.unit }}</span></template>
            </VanField>
            <p v-if="row.line_type === 'RAW' && row.conversion_snapshot?.kind === 'PIPE' && !omittedQuantity(selected[row.requirement_id]) && !pipePlan(selected[row.requirement_id] || '', row).error" class="muted pipe-hint">
              本次折合 {{ pipePlan(selected[row.requirement_id] || '', row).bars }} 根／{{ pipePlan(selected[row.requirement_id] || '', row).meters }} 米。
            </p>
            <details class="material-details">
              <summary>材料详情</summary>
              <p v-if="row.part_names?.length || row.conversion_snapshot?.part_name">部位：{{ row.part_names?.join('、') || row.conversion_snapshot?.part_name }}</p>
              <p v-if="row.line_type === 'RAW' && row.conversion_snapshot?.kind === 'PIPE'">每根切 {{ row.conversion_snapshot.pieces_per_bar || '—' }} 支，原长 {{ row.conversion_snapshot.raw_bar_length_m || '—' }} 米。</p>
              <p v-for="field in materialAttributes(row)" :key="field.key">{{ field.label }}：{{ field.value }}</p>
              <p>库存可用 {{ quantityText(row.available_stock) }} {{ row.unit }} · 已外发 {{ quantityText(row.outsourcing_issued_quantity) }} {{ row.unit }}</p>
              <p v-if="row.warehouse_zones?.length">库区：{{ row.warehouse_zones.join('、') }}</p>
            </details>
            <p v-for="message in row.validation_errors || []" :key="message" class="field-error">{{ message }}</p>
          </article>
          <section class="section-card remark-card"><VanField v-model="remark" type="textarea" label="备注" placeholder="有特殊要求再填写" maxlength="2000" autosize :disabled="fieldsLocked" /></section>
          <div v-if="actionError" class="error-panel" role="alert"><p>{{ actionError }}</p><p v-if="persistedId">申请 {{ issue?.issue_number }} 已保留，未显示成功前请勿重复新建。</p>
            <template v-if="needsReload"><p>申请或库存版本已经变化，请重新读取并核对数量后再提交。</p><VanButton block @click="initialize">重新读取并核对</VanButton></template>
          </div>
          <p v-if="!canSubmit || (!persistedId && !canCreate)" class="error-panel">当前账号没有提交领料申请的权限，请联系管理员。</p>
        </template>
      </template>
    </div>
    <VanPopup v-model:show="showRecipient" position="bottom" round teleport="body" class="issue-picker-popup" close-on-popstate>
      <VanPicker v-model="pickerRecipient" title="选择领料人" :columns="recipientColumns" :visible-option-num="Math.min(5, recipients.length || 1)" @confirm="confirmRecipient" @cancel="showRecipient = false" />
    </VanPopup>
    <VanPopup v-model:show="showIssueTime" position="bottom" round teleport="body" class="issue-picker-popup" close-on-popstate>
      <VanPickerGroup v-model:active-tab="pickerTab" title="领料时间（北京时间）" :tabs="['日期', '时间']" next-step-text="选择时间" @confirm="confirmIssueTime" @cancel="showIssueTime = false">
        <VanDatePicker v-model="pickerDate" :min-date="minPickerDate" :max-date="maxPickerDate" :formatter="formatPickerOption" />
        <VanTimePicker v-model="pickerTime" :formatter="formatPickerOption" />
      </VanPickerGroup>
    </VanPopup>
    <template #footer>
      <div v-if="ready && !submitted" class="submit-bar"><span>本次申请 <b>{{ selectedCount }}</b> 项材料</span>
        <VanButton block type="primary" :loading="saving" :disabled="!canSubmit || (!persistedId && !canCreate) || !recipients.length || needsReload" @click="save">
          {{ createUncertain ? '核对并继续提交' : persistedId ? '继续提交此申请' : '提交领料申请' }}
        </VanButton>
      </div>
    </template>
  </WorkPage>
</template>

<style scoped>
.issue-work-page :deep(.van-nav-bar) { --van-nav-bar-height: 48px; }
.issue-work-page :deep(.work-header .van-nav-bar__title) { margin-right: 16px; }
.issue-work-page :deep(.work-heading) { display: flex; align-items: baseline; gap: 10px; }
.issue-work-page :deep(.work-heading h1) { font-size: 18px; }
.issue-work-page :deep(.work-heading p) { margin: 0; font-size: 12px; }
.issue-work-page :deep(.work-content) { padding: 10px 12px 160px; }
.issue-page { gap: 10px; color: var(--mobile-text); font-size: 16px; }
.issue-page p { margin: 8px 0; line-height: 1.6; overflow-wrap: anywhere; }
.issue-page .section-card { border-radius: 12px; background: var(--mobile-surface); }
.issue-page .muted { color: var(--mobile-muted); }
.loading-panel { padding: 36px 16px; }
.issue-page .product-card { padding: 0 12px; }
.product-summary { display: flex; align-items: center; justify-content: space-between; min-height: 48px; gap: 12px; list-style: none; cursor: pointer; }
.product-summary::-webkit-details-marker { display: none; }
.product-brief { display: flex; flex-wrap: wrap; align-items: baseline; min-width: 0; gap: 2px 10px; padding-block: 8px; }
.product-brief strong { font-size: 16px; overflow-wrap: anywhere; }
.product-brief > span { color: var(--mobile-muted); font-size: 13px; }
.product-toggle { display: flex; align-items: center; flex-shrink: 0; gap: 4px; color: var(--mobile-primary); font-size: 13px; }
.product-card[open] .product-toggle .van-icon { transform: rotate(180deg); }
.product-details { padding-block: 4px 8px; border-top: 1px solid var(--mobile-border); }
.product-facts { gap: 12px; margin-top: 12px; }
.product-facts > span { display: flex; min-width: 0; flex-direction: column; gap: 4px; color: var(--mobile-muted); font-size: 14px; }
.product-facts b { color: var(--mobile-text); font-size: 16px; font-weight: 600; overflow-wrap: anywhere; }
.product-card .action-link { margin-top: 4px; padding-left: 0; color: var(--mobile-primary); }
.issue-page .issue-fields { padding: 0 12px; }
.compact-field { display: flex; width: 100%; align-items: center; justify-content: space-between; min-height: 48px; gap: 12px; margin: 0; border: 0; background: transparent; color: var(--mobile-text); font-size: 14px; }
.compact-field > span:first-child { flex-shrink: 0; }
.recipient-trigger, .time-trigger { padding: 0; cursor: pointer; }
.time-trigger { border-top: 1px solid var(--mobile-border); }
.field-value { display: flex; align-items: center; justify-content: flex-end; min-width: 0; gap: 6px; text-align: right; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.field-value .van-icon { flex-shrink: 0; color: var(--mobile-muted); }
.compact-field:disabled { color: var(--mobile-muted); cursor: default; }
.product-summary:focus-visible, .material-details summary:focus-visible { outline: 2px solid var(--mobile-primary); outline-offset: 2px; }
.issue-picker-popup { width: min(100%, 640px); right: 0; left: 0; margin-inline: auto; }
.issue-page .material-card { padding: 10px 12px 4px; }
.issue-page .material-card > p { margin: 4px 0; line-height: 1.4; }
.material-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.material-card h2 { min-width: 0; margin: 0; font-size: 18px; font-weight: 700; line-height: 1.5; overflow-wrap: anywhere; }
.material-spec { margin-left: 8px; color: var(--mobile-muted); font-size: 13px; font-weight: 400; }
.material-card > .muted { font-size: 13px; }
.material-kind { flex-shrink: 0; padding: 1px 6px; border-radius: 4px; background: #dbeafe; color: #1e40af; font-size: 12px; font-weight: 600; line-height: 20px; }
.material-kind--semi { background: #dcfce7; color: #166534; }
.quantity-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; margin: 8px 0; padding: 6px 0; border-top: 1px solid var(--mobile-border); }
.quantity-grid span { display: flex; min-width: 0; flex-direction: column; gap: 2px; color: var(--mobile-muted); font-size: 12px; line-height: 1.5; }
.quantity-grid b { color: var(--mobile-text); font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.quantity-grid .available, .quantity-grid .available b { color: var(--mobile-primary); }
.material-card :deep(.request-field) { min-height: 44px; align-items: center; padding: 0; border: 0; background: transparent; font-size: 14px; }
.material-card :deep(.request-field::after) { border: 0; }
.material-card :deep(.request-field .van-field__body) { min-height: 44px; padding: 0 10px; border: 1px solid #9aafca; border-radius: 8px; background: var(--mobile-surface); }
.material-card :deep(.request-field .van-field__body:focus-within) { border-color: var(--mobile-primary); }
.material-card :deep(.request-field.van-field--disabled .van-field__body) { border-color: var(--mobile-border); background: var(--mobile-canvas); }
.material-card :deep(.van-field__label) { width: 4em; white-space: nowrap; color: var(--mobile-text); font-weight: 600; }
.material-card :deep(.van-field__value) { min-width: 0; }
.material-card :deep(.van-field__control) { min-height: 42px; color: var(--mobile-text); font-size: 18px; font-weight: 600; text-align: left; font-variant-numeric: tabular-nums; caret-color: var(--mobile-primary); }
.material-card :deep(.van-field__control::placeholder) { color: var(--mobile-muted); font-size: 14px; font-weight: 400; }
.material-card :deep(.van-field__control:disabled) { color: var(--mobile-muted); -webkit-text-fill-color: var(--mobile-muted); }
.request-unit { white-space: nowrap; color: var(--mobile-muted); font-size: 14px; }
.material-details { margin: 2px 0 0; font-size: 13px; color: var(--mobile-muted); }
.material-details summary { box-sizing: border-box; min-height: 36px; padding: 8px 0; cursor: pointer; color: var(--mobile-primary); }
.material-details summary::marker { color: var(--mobile-primary); }
.field-error { color: var(--van-danger-color, #b42318); font-size: 14px; }
.remark-card :deep(.van-cell) { padding: 0; background: transparent; color: var(--mobile-text); font-size: 16px; }
.remark-card :deep(.van-field__control) { min-height: 48px; }
.submit-bar { display: grid; gap: 10px; }
.submit-bar > span { color: var(--mobile-muted); font-size: 14px; }
.submit-bar > span b { margin: 0 3px; color: var(--mobile-primary); font-size: 18px; }
.result-panel h2 { margin: 0 0 8px; color: var(--mobile-primary); font-size: 18px; }
.result-panel .van-button { margin-top: 16px; }
</style>
