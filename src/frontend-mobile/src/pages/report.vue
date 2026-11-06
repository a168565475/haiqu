<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import type { RouteLocationNormalized } from 'vue-router'
import { showConfirmDialog, showDialog } from 'vant'
import type { PickerConfirmEventParams, PickerOption } from 'vant'
import WorkPage from '@/components/WorkPage.vue'
import { createWorkReport, fetchReportingContext, fetchReportingScheme } from '@/api/reporting'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { createRequestId } from '@/utils/requestId'
import { loadReportEmployees, saveReportEmployees } from '@/utils/reportEmployeeMemory'
import {
  estimatedLineAmount, needsCompletionConfirmation, prepareReportAttempt, quantityText,
  remainingQuantity, reportingScope, shanghaiToday, uncertainSubmission,
  validateReportEntries, validProductionDate,
} from '@/utils/reporting'
import type { ReportAttempt, ReportValidation } from '@/utils/reporting'
import type { ReportEntry, ReportingContext, ReportingScheme, WorkReport } from '@/types/reporting'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const scope = computed(() => reportingScope(route.query))
const context = ref<ReportingContext | null>(null)
const scheme = ref<ReportingScheme | null>(null)
const productionDate = ref(shanghaiToday())
const showReportDate = ref(false)
const changingDate = ref(false)
const pickerDate = ref<string[]>([])
const entries = ref<ReportEntry[]>([])
const rememberedEmployees = ref<Record<string, string>>({})
const prefilledEmployees = ref<Record<number, string>>({})
const employeeMemoryNotice = ref('')
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const submitError = ref('')
const uncertain = ref(false)
const completed = ref<WorkReport | null>(null)
const validation = ref<ReportValidation>({ error: '', rows: {}, completesPlan: false })
const picker = reactive({ open: false, rowKey: 0, search: '' })
let nextRowKey = 0
let attempt: ReportAttempt | null = null
let requestSequence = 0
let controller: AbortController | null = null

const product = computed(() => context.value?.schedule_product)
const workshop = computed(() => context.value?.workshops.find(item => item.id === scope.value?.workshop_id))
const craft = computed(() => context.value?.crafts.find(item => item.id === scope.value?.craft_id))
const assembly = computed(() => workshop.value?.name === '装配车间')
const employees = computed(() => context.value?.employees.filter(item => item.workshop_id === scope.value?.workshop_id) ?? [])
const operations = computed(() => scheme.value?.lines.filter(item => item.status === 'ACTIVE') ?? [])
const canCreate = computed(() => auth.hasPermission('workshop_reporting.add_workreport') && auth.hasPermission('workshop_reporting.view_workreport'))
const locked = computed(() => saving.value || uncertain.value || completed.value !== null)
watch([locked, loading], ([isLocked, isLoading]) => { if (isLocked || isLoading) showReportDate.value = false })
const pickerYear = computed(() => Number(productionDate.value.slice(0, 4)))
const minPickerDate = computed(() => new Date(Math.min(Number(shanghaiToday().slice(0, 4)) - 10, pickerYear.value), 0, 1))
const maxPickerDate = computed(() => new Date(Math.max(Number(shanghaiToday().slice(0, 4)) + 10, pickerYear.value), 11, 31))
// 记忆带入的员工不算本次填写，避免未填次数的其他工序被一并提交或提示必填。
const filledEntries = computed(() => entries.value.filter(row => row.quantity !== '' || row.production_line !== null
  || row.workshop_employee_id !== '' && row.workshop_employee_id !== prefilledEmployees.value[row.key]))
const hasInput = computed(() => filledEntries.value.length > 0)
const pickerHasInput = computed(() => entries.value.some(row => row.key === picker.rowKey
  && (row.workshop_employee_id !== '' || row.quantity !== '' || row.production_line !== null)))
const employeeIds = computed(() => new Set(employees.value.map(item => item.id)))
const configError = computed(() => scheme.value ? validateReportEntries(scheme.value, [], employeeIds.value, assembly.value).error : '')
const blockedConfiguration = computed(() => configError.value && configError.value !== '请至少填写一道工序的报工。' ? configError.value : '')
const filteredOptions = computed(() => {
  const keyword = picker.search.trim().toLocaleLowerCase()
  return employees.value.filter(item => item.name.toLocaleLowerCase().includes(keyword))
})

function lineFor(row: ReportEntry) { return operations.value.find(item => item.id === row.scheme_line_id) }
function employeeName(id: string) { return employees.value.find(item => item.id === id)?.name ?? '' }
function rowError(row: ReportEntry, field: keyof ReportValidation['rows'][number]) { return validation.value.rows[row.key]?.[field] }
function formatReportQuantity(value: string, row: ReportEntry) {
  // 小数、符号或文字整次拒绝，不能把 1.5 次静默变成 15 次。
  return /^\d{0,14}$/.test(value) ? value : row.quantity
}
function clearValidation() { validation.value = { error: '', rows: {}, completesPlan: false }; submitError.value = '' }
function openPicker(row: ReportEntry) {
  if (locked.value) return
  Object.assign(picker, { open: true, rowKey: row.key, search: '' })
}
function selectOption(id: string) {
  const row = entries.value.find(item => item.key === picker.rowKey)
  if (!row || locked.value) return
  row.workshop_employee_id = id
  picker.open = false
  clearValidation()
}
function clearPickerEntry() {
  const row = entries.value.find(item => item.key === picker.rowKey)
  if (!row || locked.value) return
  Object.assign(row, { workshop_employee_id: '', production_line: null, quantity: '' })
  picker.open = false
  clearValidation()
}

async function loadData(preserve = false) {
  controller?.abort()
  controller = new AbortController()
  const current = ++requestSequence
  const selected = scope.value
  const previousScheme = scheme.value
  loadError.value = ''
  if (!selected) {
    context.value = null; scheme.value = null; entries.value = []
    loadError.value = '缺少有效的生产任务、车间或工艺，请返回任务列表重新选择。'
    return
  }
  loading.value = true
  picker.open = false
  if (!preserve) { context.value = null; scheme.value = null; entries.value = []; prefilledEmployees.value = {} }
  try {
    const result = await fetchReportingContext(selected.schedule_product_id, controller.signal)
    if (current !== requestSequence) return
    const selectedCraft = result.crafts.find(item => item.id === selected.craft_id)
    if (result.schedule_product?.id !== selected.schedule_product_id
      || !result.workshops.some(item => item.id === selected.workshop_id)
      || selectedCraft?.workshop_id !== selected.workshop_id) {
      throw new Error('当前任务的车间或工艺已经变化，请返回任务列表重新选择。')
    }
    context.value = result
    const price = await fetchReportingScheme(selected, result.schedule_product.product_line_id, productionDate.value, controller.signal)
    if (current !== requestSequence) return
    scheme.value = price
    rememberedEmployees.value = {}
    employeeMemoryNotice.value = ''
    if (auth.user?.id) {
      try { rememberedEmployees.value = loadReportEmployees(auth.user.id, selected) }
      catch { employeeMemoryNotice.value = '无法读取上次员工，请手动选择；成功报工后会重新记住。' }
    }
    const previousEntries = new Map(entries.value.map(row => [row.scheme_line_id, row]))
    const removedInput = filledEntries.value.some(row => !operations.value.some(line => line.id === row.scheme_line_id))
    // 工序顺序及版本会更新，填写内容只能按工序行 ID 对应，不能按位置复用。
    entries.value = operations.value.map(line => {
      const previous = previousEntries.get(line.id)
      if (previous) return previous
      const employeeId = rememberedEmployees.value[line.work_item_id]
      const selectedEmployee = employeeIds.value.has(employeeId) ? employeeId : ''
      const key = ++nextRowKey
      prefilledEmployees.value[key] = selectedEmployee
      return { key, scheme_line_id: line.id, workshop_employee_id: selectedEmployee, production_line: null, quantity: '' }
    })
    prefilledEmployees.value = Object.fromEntries(entries.value.map(row => [row.key, prefilledEmployees.value[row.key] ?? '']))
    if (preserve && (removedInput || previousScheme?.id !== price.id || previousScheme.revision !== price.revision)) {
      submitError.value = removedInput
        ? '部分已填写工序已停用或移除，对应内容已清空，请重新核对后提交。'
        : '适用工价版本已更新，请重新核对工序和次数后提交。'
      attempt = null
    }
  }
  catch (error) {
    if (current === requestSequence) {
      scheme.value = null
      loadError.value = errorMessage(error, '报工信息加载失败，请重试。')
    }
  }
  finally { if (current === requestSequence) loading.value = false }
}

async function confirmDialog(message: string, title = '核对报工', confirmButtonText = '确认提交'): Promise<boolean> {
  try { await showConfirmDialog({ title, message, confirmButtonText, cancelButtonText: '返回修改' }); return true }
  catch (reason) { if (reason === 'cancel' || reason === 'close') return false; throw reason }
}

function openReportDate() {
  if (locked.value || loading.value || changingDate.value) return
  pickerDate.value = productionDate.value.split('-')
  showReportDate.value = true
}
function formatDateOption(type: string, option: PickerOption) {
  const labels: Record<string, string> = { year: '年', month: '月', day: '日' }
  return { ...option, text: `${option.text}${labels[type] || ''}` }
}
async function confirmReportDate({ selectedValues }: PickerConfirmEventParams) {
  const next = selectedValues.join('-')
  if (locked.value || loading.value || changingDate.value || !validProductionDate(next)) return
  showReportDate.value = false
  if (next === productionDate.value) return
  changingDate.value = true
  try {
    const current = requestSequence
    if (hasInput.value && !await confirmDialog('更换日期后需要重新匹配工价，当前填写的报工明细将清空。', '更换生产日期', '更换日期')) return
    if (locked.value || loading.value || current !== requestSequence) return
    productionDate.value = next
    attempt = null
    clearValidation()
    await loadData()
  }
  finally { changingDate.value = false }
}

async function sendAttempt() {
  if (!attempt) return
  const userId = auth.user?.id
  const selected = scope.value
  const employeesToRemember = { ...rememberedEmployees.value }
  for (const row of attempt.payload.lines) {
    const line = operations.value.find(item => item.id === row.scheme_line_id)
    if (line) employeesToRemember[line.work_item_id] = row.workshop_employee_id
  }
  saving.value = true
  submitError.value = ''
  try {
    completed.value = await createWorkReport(attempt.payload)
    uncertain.value = false
    attempt = null
  }
  catch (error) {
    uncertain.value = uncertainSubmission(error)
    if (uncertain.value) {
      submitError.value = '尚未确认这次报工是否成功。请保持本页，点击“核对并重试”；会沿用本次提交编号，避免重复报工。'
    }
    else if (needsCompletionConfirmation(error)) {
      submitError.value = '当前工序进度已更新。请刷新工价与进度，核对后确认完成生产计划。'
    }
    else submitError.value = errorMessage(error, '报工提交失败，填写内容已保留。')
  }
  finally { saving.value = false }
  // 本地偏好写入失败不能把已经成功的报工变成失败或触发重复提交。
  if (completed.value && userId && selected) {
    try {
      saveReportEmployees(userId, selected, employeesToRemember)
      rememberedEmployees.value = employeesToRemember
      employeeMemoryNotice.value = ''
    }
    catch { employeeMemoryNotice.value = '报工已成功，但未能记住员工，下次请重新选择。' }
  }
}

async function submit() {
  if (saving.value || completed.value || !canCreate.value) return
  if (uncertain.value) { await sendAttempt(); return }
  if (!scheme.value || !scope.value || !validProductionDate(productionDate.value)) return
  clearValidation()
  const submittedEntries = filledEntries.value
  validation.value = validateReportEntries(scheme.value, submittedEntries, employeeIds.value, assembly.value)
  if (validation.value.error || Object.keys(validation.value.rows).length) return
  saving.value = true
  try {
    const completes = validation.value.completesPlan
    const summary = `${productionDate.value}，${submittedEntries.length} 条报工。请核对每条员工、工序和本次次数。`
    const confirmed = await confirmDialog(
      completes ? `${summary}\n本次提交后所有工序达到需完成次数，将同时完成当前生产计划。` : summary,
      completes ? '确认完成生产计划' : '确认本次报工',
      completes ? '完成计划并提交' : '确认提交',
    )
    if (!confirmed) return
    attempt = prepareReportAttempt({
      production_date: productionDate.value, schedule_product_id: scope.value.schedule_product_id,
      scheme_id: scheme.value.id, scheme_revision: scheme.value.revision, confirm_plan_completion: completes,
      lines: submittedEntries.map(({ key: _key, ...row }) => ({ ...row, quantity: row.quantity.trim() })),
    }, attempt, createRequestId)
    await sendAttempt()
  }
  catch (error) { submitError.value = errorMessage(error, '无法提交，请重试。') }
  finally { saving.value = false }
}

function openRecords() { void router.push({ path: '/report-records', query: { ...route.query, section: 'report' } }) }

async function allowLeave(to: RouteLocationNormalized) {
  // 身份失效必须允许退出本业务页，不能被未保存提示拦住登录跳转。
  if (to.path === '/login') return true
  if (saving.value || uncertain.value) {
    await showDialog({ title: '请先核对本次提交', message: '本次报工结果尚未确认，请留在当前页面完成核对，避免重复报工。', confirmButtonText: '继续核对' })
    return false
  }
  return Boolean(completed.value) || !hasInput.value || await confirmDialog('当前填写尚未提交，离开后需要重新填写。', '离开报工页面', '确认离开')
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (saving.value || uncertain.value || hasInput.value && !completed.value) { event.preventDefault(); event.returnValue = '' }
}
onBeforeRouteLeave(allowLeave)
onBeforeRouteUpdate(allowLeave)
window.addEventListener('beforeunload', beforeUnload)
watch(() => route.fullPath, () => {
  completed.value = null; attempt = null; uncertain.value = false; productionDate.value = shanghaiToday(); showReportDate.value = false
  clearValidation(); void loadData()
}, { immediate: true })
onBeforeUnmount(() => { requestSequence++; controller?.abort(); window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <WorkPage class="report-work-page" title="生产报工" :subtitle="workshop && craft ? `${workshop.name} · ${craft.name}` : '班组长填写本次完成情况'" section="report" back-to="/production-report">
    <div class="page-stack report-page">
      <section v-if="completed" class="section-card report-success" role="status">
        <van-icon name="passed" size="40" />
        <h2>报工已提交</h2>
        <p>{{ completed.report_number }}</p>
        <p>{{ completed.production_date }} · {{ completed.lines.length }} 条明细</p>
        <p v-if="completed.completed_plan">本次生产计划已完成。</p>
        <p class="muted">记录已生效，提交金额 {{ quantityText(completed.total_amount) }} 元。</p>
        <p v-if="employeeMemoryNotice" role="status">{{ employeeMemoryNotice }}</p>
        <van-button type="primary" block @click="openRecords">查看报工记录</van-button>
        <van-button block plain @click="router.push('/production-report')">返回生产报工</van-button>
      </section>

      <template v-else>
        <details v-if="product" :key="product.id" class="section-card report-context">
          <summary class="report-product-summary">
            <span class="report-product-heading"><strong>{{ product.product_name }}</strong><small>{{ product.task_number }}</small></span>
            <span class="report-product-toggle">产品详情<van-icon name="arrow-down" aria-hidden="true" /></span>
          </summary>
          <div class="report-product-details">
          <p class="muted report-product-identity">{{ product.task_number }} · {{ product.product_code || product.product_number }}</p>
          <p class="report-product-specification">{{ [product.product_specification, product.product_color].filter(Boolean).join(' · ') || '未填写规格颜色' }}</p>
          <dl class="summary-grid report-product-counts">
            <div><dt>计划数量</dt><dd>{{ quantityText(product.planned_quantity) }} {{ product.unit_name }}</dd></div>
            <div><dt>订单数量</dt><dd>{{ quantityText(product.order_quantity) }} {{ product.unit_name }}</dd></div>
          </dl>
          <p class="muted report-recorder">记录人：{{ auth.user?.display_name || auth.user?.username || '当前登录员工' }}</p>
          <button class="action-link report-record-link" type="button" :disabled="locked" @click="openRecords">查看报工记录<van-icon name="arrow" aria-hidden="true" /></button>
          </div>
        </details>

        <div v-if="loading" class="report-loading" role="status"><van-loading size="26">正在读取报工信息…</van-loading></div>
        <section v-if="loadError" class="error-panel" role="alert">
          <p>{{ loadError }}</p>
          <van-button v-if="scope" block :disabled="locked || loading" @click="loadData(true)">重新加载</van-button>
          <van-button v-else block @click="router.push('/production-report')">返回生产报工</van-button>
        </section>

        <section v-if="context && !loading" class="section-card report-date">
          <button id="report-production-date" type="button" class="report-date-control" aria-label="选择生产日期" aria-description="按实际生产日期报工，默认今天。" aria-haspopup="dialog" :disabled="locked || loading || changingDate" @click="openReportDate">
            <span class="field-label">生产日期</span>
            <span class="report-date-value">{{ productionDate }}<van-icon name="calendar-o" aria-hidden="true" /></span>
          </button>
        </section>

        <template v-if="scheme && !loading">
          <p v-if="employeeMemoryNotice" class="muted" role="status">{{ employeeMemoryNotice }}</p>
          <section v-if="!canCreate" class="error-panel" role="alert">当前账号没有新增报工权限，请联系管理员核对岗位权限。</section>
          <section v-if="blockedConfiguration" class="error-panel" role="alert">{{ blockedConfiguration }}</section>
          <section v-if="!employees.length" class="error-panel" role="alert">当前车间没有可选择的有效员工，请联系主管维护员工资料。</section>

          <section v-for="row in entries" :key="row.key" class="section-card report-entry" :data-row-key="row.key">
            <div class="report-entry-header">
              <h3 class="report-operation-name">{{ lineFor(row)?.display_name }}<span> · {{ lineFor(row)?.operation_name }}</span></h3>
              <p class="report-remaining">剩余 <strong>{{ remainingQuantity(lineFor(row)) }}</strong> 次</p>
            </div>
            <van-field class="report-choice" :model-value="employeeName(row.workshop_employee_id)" label="员工" placeholder="选择实际完成的员工" readonly is-link required :disabled="locked" :error-message="rowError(row, 'workshop_employee_id')" @click="openPicker(row)" />
            <div v-if="assembly" class="report-assembly">
              <p class="field-label">装配线 <span aria-hidden="true">*</span></p>
              <van-radio-group v-model="row.production_line" direction="horizontal" :disabled="locked" @update:model-value="clearValidation">
                <van-radio v-for="line in [1, 2, 3]" :key="line" :name="line">{{ line }} 线</van-radio>
              </van-radio-group>
              <p v-if="rowError(row, 'production_line')" class="report-field-error">{{ rowError(row, 'production_line') }}</p>
            </div>
            <van-field v-model="row.quantity" class="report-quantity" label="本次次数" placeholder="请输入次数" type="text" inputmode="numeric" required :formatter="value => formatReportQuantity(value, row)" :disabled="locked" :error-message="rowError(row, 'quantity')" @update:model-value="clearValidation">
              <template #button><span class="report-quantity-unit">次</span></template>
            </van-field>
            <details v-if="lineFor(row)" class="report-line-details">
              <summary>工序要求与工价<van-icon name="arrow-down" aria-hidden="true" /></summary>
              <p>{{ lineFor(row)!.production_description || '未填写制作说明' }}</p>
              <dl class="summary-grid">
                <div><dt>需完成次数</dt><dd>{{ quantityText(lineFor(row)!.required_quantity) }}</dd></div>
                <div><dt>累计已报</dt><dd>{{ quantityText(lineFor(row)!.cumulative_quantity) }}</dd></div>
                <div><dt>工价</dt><dd>{{ quantityText(lineFor(row)!.declared_price) }} 元 / 次</dd></div>
                <div><dt>本条预计金额</dt><dd>{{ estimatedLineAmount(lineFor(row), row.quantity) }} 元</dd></div>
              </dl>
            </details>
          </section>
        </template>

        <section v-if="validation.error || Object.keys(validation.rows).length || submitError" class="error-panel" role="alert">
          <p>{{ submitError || validation.error || '请检查上方标出的报工明细。' }}</p>
          <van-button v-if="submitError && !uncertain && scope" block :disabled="saving || loading" @click="clearValidation(); loadData(true)">刷新工价与进度</van-button>
        </section>
      </template>
    </div>

    <template v-if="!completed" #footer>
      <p class="report-submit-count">本次填写 <strong>{{ filledEntries.length }}</strong> 道工序</p>
      <van-button block type="primary" :loading="saving" :disabled="!canCreate || loading || (!uncertain && (!scheme || Boolean(blockedConfiguration) || !employees.length))" @click="submit">{{ uncertain ? '核对并重试本次报工' : '提交报工' }}</van-button>
    </template>

    <van-popup v-model:show="showReportDate" position="bottom" round teleport="body" class="report-date-popup" close-on-popstate safe-area-inset-bottom>
      <van-date-picker v-model="pickerDate" title="选择生产日期" :columns-type="['year', 'month', 'day']" :min-date="minPickerDate" :max-date="maxPickerDate" :formatter="formatDateOption" @confirm="confirmReportDate" @cancel="showReportDate = false" />
    </van-popup>

    <van-popup v-model:show="picker.open" position="bottom" round closeable class="report-picker" :close-on-click-overlay="!locked">
      <h2>选择员工</h2>
      <van-search v-model="picker.search" placeholder="搜索员工姓名" />
      <div class="report-picker-options">
        <van-cell v-if="pickerHasInput" title="清空本工序" clickable @click="clearPickerEntry" />
        <van-cell v-for="option in filteredOptions" :key="option.id" :title="option.name" clickable is-link @click="selectOption(option.id)" />
        <van-empty v-if="!filteredOptions.length" description="没有找到匹配项，请更换搜索内容" />
      </div>
    </van-popup>
  </WorkPage>
</template>

<style scoped>
:global(body:has(.report-work-page)) { min-width: 0; }
.report-work-page :deep(.van-nav-bar) { --van-nav-bar-height: 48px; }
.report-work-page :deep(.work-header .van-nav-bar__title) { margin-right: 12px; }
.report-work-page :deep(.work-heading) { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.report-work-page :deep(.work-heading h1) { flex-shrink: 0; font-size: 18px; }
.report-work-page :deep(.work-heading p) { margin: 0; overflow: hidden; text-overflow: ellipsis; font-size: 12px; }
.report-work-page :deep(.work-content) { padding: 10px 12px calc(120px + env(safe-area-inset-bottom)); }
.report-page { gap: 10px; color: var(--mobile-text, #172b4d); }
.report-page p { margin: 8px 0; overflow-wrap: anywhere; }
.report-page .section-card { border-radius: 12px; }
.report-context { padding: 0 12px; }
.report-product-summary { display: flex; align-items: center; justify-content: space-between; min-height: 48px; gap: 12px; list-style: none; cursor: pointer; }
.report-product-summary::-webkit-details-marker { display: none; }
.report-product-heading { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; min-width: 0; padding-block: 8px; overflow-wrap: anywhere; }
.report-product-heading strong { font-size: 16px; }
.report-product-heading small { color: var(--mobile-muted, #64748b); font-size: 13px; }
.report-product-toggle { display: flex; align-items: center; gap: 6px; flex-shrink: 0; font-size: 13px; color: var(--mobile-primary, #2563eb); }
.report-context[open] .report-product-toggle .van-icon { transform: rotate(180deg); }
.report-product-summary:focus-visible { outline: 2px solid var(--mobile-primary, #2563eb); outline-offset: 2px; }
.report-product-details { padding-block: 4px 8px; border-top: 1px solid var(--mobile-border, #e2e8f0); }
.report-context .report-product-identity { margin: 4px 0; font-size: 13px; font-variant-numeric: tabular-nums; }
.report-context .report-product-specification { margin: 4px 0 8px; font-size: 13px; color: var(--mobile-muted, #64748b); }
.report-product-counts { margin: 0; padding-bottom: 4px; }
.report-product-counts dd { font-size: 16px; }
.report-recorder { font-size: 13px; }
.report-record-link { display: flex; align-items: center; justify-content: space-between; width: 100%; min-height: 44px; padding: 8px 0 0; border-top: 1px solid var(--mobile-border, #e2e8f0); font-size: 14px; font-weight: 500; }
.report-loading { padding: 32px 16px; text-align: center; }
.report-date { padding: 0 12px; }
.report-date-control { display: flex; align-items: center; justify-content: space-between; width: 100%; min-height: 48px; gap: 12px; padding: 0; border: 0; background: transparent; color: var(--mobile-text, #172b4d); font: inherit; text-align: left; cursor: pointer; }
.report-date .field-label { margin: 0; flex-shrink: 0; color: var(--mobile-text, #172b4d); font-size: 14px; font-weight: 500; }
.report-date-value { display: flex; align-items: center; gap: 8px; font-size: 14px; font-variant-numeric: tabular-nums; }
.report-date-value .van-icon { color: var(--mobile-primary, #2563eb); font-size: 18px; }
.report-date-control:focus-visible { outline: 2px solid var(--mobile-primary, #2563eb); outline-offset: 2px; }
.report-date-control:disabled { opacity: .6; cursor: default; }
.report-date-popup { width: min(100%, 640px); left: 0; right: 0; margin-inline: auto; }
.report-entry { padding: 0 12px; }
.report-entry-header { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 2px 10px; padding: 10px 0 6px; border-bottom: 1px solid var(--mobile-border, #e2e8f0); }
.report-operation-name { margin: 0; font-size: 18px; font-weight: 700; line-height: 1.5; overflow-wrap: anywhere; }
.report-operation-name span { font-size: 14px; font-weight: 500; }
.report-entry :deep(.van-cell) { padding: 10px 0; min-height: 44px; font-size: 14px; }
.report-entry :deep(.van-cell::after) { left: 0; right: 0; }
.report-entry :deep(.van-field__label) { width: 4em; color: var(--mobile-muted, #64748b); }
.report-entry :deep(.van-field__value) { min-width: 0; }
.report-entry :deep(.van-field__control) { font-size: 16px; color: var(--mobile-text, #172b4d); }
.report-choice :deep(.van-field__control) { font-weight: 500; }
.report-entry :deep(.van-field__control::placeholder) { color: var(--mobile-muted, #64748b); font-weight: 400; }
.report-entry .report-remaining { margin: 0; font-size: 12px; color: var(--mobile-muted, #64748b); white-space: nowrap; }
.report-remaining strong { margin-inline: 4px; color: var(--mobile-primary, #2563eb); font-size: 15px; font-variant-numeric: tabular-nums; }
.report-assembly { display: flex; flex-wrap: wrap; align-items: center; gap: 0 12px; padding: 4px 0; }
.report-assembly .field-label { margin: 0; width: 4em; font-size: 14px; }
.report-assembly :deep(.van-radio-group) { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.report-assembly :deep(.van-radio) { min-height: 44px; margin-right: 0; font-size: 14px; }
.report-field-error { color: var(--van-danger-color, #b7362d); font-size: 14px; }
.report-entry .report-quantity { margin: 4px 0 6px; padding: 0; border: 0; background: transparent; }
.report-quantity :deep(.van-field__body) { min-height: 44px; padding: 0 10px; border: 1px solid #9aafca; border-radius: 8px; background: var(--mobile-surface, #fff); }
.report-quantity :deep(.van-field__body:focus-within) { border-color: var(--mobile-primary, #2563eb); }
.report-quantity.van-field--disabled :deep(.van-field__body) { border-color: var(--mobile-border, #e2e8f0); background: var(--mobile-canvas, #edf2f7); }
.report-quantity::after { display: none; }
.report-quantity :deep(.van-field__control) { min-height: 42px; color: var(--mobile-text, #172b4d); font-size: 18px; font-weight: 600; text-align: left; font-variant-numeric: tabular-nums; caret-color: var(--mobile-primary, #2563eb); }
.report-quantity :deep(.van-field__control::placeholder) { font-size: 14px; }
.report-quantity :deep(.van-field__control:disabled) { color: var(--mobile-muted, #64748b); -webkit-text-fill-color: var(--mobile-muted, #64748b); }
.report-quantity :deep(.van-field__label) { align-self: center; width: 5em; white-space: nowrap; color: var(--mobile-text, #172b4d); }
.report-quantity-unit { white-space: nowrap; color: var(--mobile-muted, #64748b); font-size: 14px; }
.report-line-details summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 0; min-height: 36px; box-sizing: border-box; cursor: pointer; color: var(--mobile-muted, #64748b); font-size: 13px; list-style: none; }
.report-line-details summary::-webkit-details-marker { display: none; }
.report-line-details[open] summary { color: var(--mobile-primary, #2563eb); }
.report-line-details[open] summary .van-icon { transform: rotate(180deg); }
.report-line-details summary:focus-visible { outline: 2px solid var(--mobile-primary, #2563eb); outline-offset: 2px; }
.report-line-details p { font-size: 14px; line-height: 1.65; }
.report-line-details .summary-grid { margin: 12px 0; }
.report-submit-count { margin: 0 0 8px; color: var(--mobile-muted, #64748b); font-size: 13px; }
.report-submit-count strong { margin-inline: 4px; color: var(--mobile-primary, #2563eb); font-size: 16px; }
.report-success { padding-block: 32px; text-align: center; }
.report-success h2 { margin: 16px 0 8px; font-size: 20px; }
.report-success .van-icon { color: var(--mobile-primary, #2563eb); }
.report-success > p:first-of-type { font-variant-numeric: tabular-nums; font-weight: 600; }
.report-success .van-button { margin-top: 12px; }
.report-picker { width: min(100%, 640px); left: 0; right: 0; margin-inline: auto; max-height: 80dvh; padding-top: 16px; padding-bottom: env(safe-area-inset-bottom); background: var(--mobile-surface, #fff); }
.report-picker h2 { margin: 0 48px 12px 20px; font-size: 18px; color: var(--mobile-text, #172b4d); }
.report-picker-options { max-height: 58dvh; overflow-y: auto; overscroll-behavior: contain; }
.report-picker :deep(.van-search) { padding: 4px 16px 12px; }
.report-picker :deep(.van-search__content) { background: var(--mobile-canvas, #edf2f7); border-radius: 8px; }
.report-picker-options :deep(.van-cell) { min-height: 48px; padding: 12px 20px; font-size: 16px; }
</style>
