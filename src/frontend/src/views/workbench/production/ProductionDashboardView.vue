<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { Box, Calendar, Clock, Document } from '@element-plus/icons-vue'
import { fetchProductionDashboard } from '@/api/productionDashboard'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import type {
  ProductionDashboardCategory, ProductionDashboardFocus, ProductionDashboardPayload,
  ProductionDashboardQuery, ProductionDashboardRole, ProductionDashboardSection,
  ProductionDashboardStatus, ProductionDashboardTask, ProductionDashboardTasks,
} from '@/types/productionDashboard'
import ProductionModuleLayout from './ProductionModuleLayout.vue'
import ProductionOverview from './ProductionOverview.vue'
import ProductionProgress from './ProductionProgress.vue'
import type { OverviewModuleKey } from './useModuleFocus'

const props = defineProps<{ role: ProductionDashboardRole }>()
const root = ref<HTMLElement>()
const ownerLayout = ref<InstanceType<typeof ProductionModuleLayout>>()
const data = ref<ProductionDashboardPayload | null>(null)
const loading = ref(false)
const requestError = ref('')
const forbidden = ref(false)
const fullscreen = ref(false)
const showOverviewFilters = ref(false)
const fullscreenError = ref('')
const now = ref(Date.now())
const selectedDate = ref('')
const dateDialog = ref(false)
const dateData = ref<ProductionDashboardTasks | null>(null)
const dateLoading = ref(false)
const dateError = ref('')
const dateForbidden = ref(false)
const datePage = ref(1)
const today = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
const form = reactive({ q: '', days: 7 as 3 | 7, status: 'ALL' as ProductionDashboardStatus, production_date: today() })
const category = ref<ProductionDashboardCategory>('METAL')
const focus = ref<ProductionDashboardFocus>('ALL')
let activeQuery: ProductionDashboardQuery = {}
let controller: AbortController | undefined
let dateController: AbortController | undefined
let dateRequestSequence = 0
let dateQuery: ProductionDashboardQuery = {}
let requestSequence = 0
let clock: ReturnType<typeof setInterval> | undefined
const staleAfterMs = 300_000

const title = computed(() => ({ owner: '生产负责人工作台', executive: '生产总览', workshop: '车间主管工作台' })[props.role])
const subtitle = computed(() => ({ owner: '从交期风险开始，找到今天需要协调的任务。', executive: '查看任务交期与风险分布，聚焦需要介入的事项。', workshop: '当前工序任务与当日报工，逐单掌握现场节奏。' })[props.role])
function readable<T>(section: ProductionDashboardSection<T> | undefined): T | null {
  return section && ['READY', 'EMPTY'].includes(section.state) ? section.data : null
}
const tasks = computed(() => readable(data.value?.sections.tasks))
const outsourcing = computed(() => readable(data.value?.sections.outsourcing))
const receipts = computed(() => readable(data.value?.sections.receipts))
const workshop = computed(() => readable(data.value?.sections.workshop))
const reports = computed(() => readable(data.value?.sections.reports))
const taskRows = computed(() => tasks.value?.items.slice(0, 5) ?? [])
const jobRows = computed(() => workshop.value?.items.slice(0, 3) ?? [])
const attention = computed(() => tasks.value?.items.filter(task => task.status === 'PAUSED' || (task.days_to_due !== null && task.days_to_due < 0 && !['COMPLETED', 'CANCELLED'].includes(task.status))).slice(0, 3) ?? [])
const isAssembly = computed(() => category.value === 'ASSEMBLY')
const stale = computed(() => Boolean(data.value && (requestError.value || now.value - Date.parse(data.value.generated_at) >= staleAfterMs)))
const pageState = computed(() => {
  if (forbidden.value || (data.value && Object.values(data.value.sections).every(section => section.state === 'FORBIDDEN'))) return 'forbidden'
  if (!data.value) return loading.value ? 'loading' : requestError.value ? 'error' : 'loading'
  if (stale.value) return 'stale'
  if (Object.values(data.value.sections).every(section => section.state === 'EMPTY')) return 'empty'
  return 'ready'
})
const updated = computed(() => {
  if (!data.value) return ''
  const date = new Date(data.value.generated_at)
  return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date)
})
const metrics = computed(() => [
  { key: 'overdue', label: '交期已过', value: tasks.value?.counts.overdue, note: '未完成任务，优先协调', filter: 'OVERDUE' as const, icon: Clock, danger: true },
  { key: 'due-soon', label: '未来 3 天到期', value: tasks.value?.counts.due_soon, note: '今天起 3 个自然日', filter: 'DUE_SOON' as const, icon: Calendar },
  { key: 'unscheduled', label: '待排产', value: tasks.value?.counts.unscheduled, note: '尚无有效排产计划', filter: 'UNSCHEDULED' as const, icon: Document },
  { key: 'outsourcing', label: '委外待回货', value: outsourcing.value?.pending_count, note: '按外发单独立统计', filter: null, icon: Box },
])
const ownerModules = computed(() => [
  { key: 'production' as OverviewModuleKey, title: '优先处理的生产任务', subtitle: '从交期和当前状态查看任务', summary: tasks.value ? `${quantity(tasks.value.total)} 单任务` : sectionMessage(data.value?.sections.tasks, '暂无任务') },
  { key: 'delivery' as OverviewModuleKey, title: '近期交期', subtitle: '查看当前范围的交期节点', summary: tasks.value ? `${quantity(tasks.value.counts.due_soon)} 单未来 3 天到期` : sectionMessage(data.value?.sections.tasks, '暂无交期节点') },
  { key: 'outsourcing' as OverviewModuleKey, title: '委外待回货', subtitle: '预计回货日期与客户交期分别跟进', summary: outsourcing.value ? `${quantity(outsourcing.value.pending_count)} 单待回货` : sectionMessage(data.value?.sections.outsourcing, '暂无待回货外发单') },
  { key: 'todo' as OverviewModuleKey, title: '今日协调重点', subtitle: '将关注点落到具体任务', summary: tasks.value ? `当前展示 ${attention.value.length} 项重点` : sectionMessage(data.value?.sections.tasks, '暂无协调事项') },
])
const workshopModules = computed(() => [
  { key: 'production' as OverviewModuleKey, title: '当前工序任务', subtitle: '逐项查看计划与累计进度', summary: workshop.value ? `${quantity(workshop.value.total)} 项工序任务` : sectionMessage(data.value?.sections.workshop, '暂无车间任务') },
  { key: 'output' as OverviewModuleKey, title: isAssembly.value ? '当日成品入库记录' : '当日报工记录', subtitle: isAssembly.value ? '按入库业务日期查看凭证' : '全部可查看车间 · 按生产业务日期', summary: (isAssembly.value ? receipts.value : reports.value) ? `${quantity(isAssembly.value ? receipts.value?.total : reports.value?.total)} 笔记录` : sectionMessage(isAssembly.value ? data.value?.sections.receipts : data.value?.sections.reports, '暂无记录') },
  { key: 'todo' as OverviewModuleKey, title: '现场关注', subtitle: '查看交期已过或暂停的事项', summary: tasks.value ? `当前展示 ${attention.value.length} 项重点` : sectionMessage(data.value?.sections.tasks, '暂无关注事项') },
])
const selectedDayRows = computed(() => dateData.value?.items ?? [])
const dateState = computed(() => dateLoading.value ? 'loading' : dateForbidden.value ? 'forbidden' : dateError.value ? 'error' : selectedDayRows.value.length ? 'ready' : 'empty')

function sectionMessage(section: ProductionDashboardSection<unknown> | undefined, emptyText: string) {
  if (!section) return '数据暂不可用'
  if (section.state === 'FORBIDDEN') return section.reason || '没有此区域的查看权限'
  if (section.state === 'UNKNOWN') return section.reason || '数据暂不可用，请稍后刷新'
  return section.reason || emptyText
}
function safeHref(href: string): string | undefined {
  return /^\/(?:production-tasks|workshop\/(?:scheduling|plans|outsourcing|work-reports)|inventory\/finished-goods)(?:[/?#]|$)/.test(href) && !/[\\\s]/.test(href) && !href.includes('..') ? href : undefined
}
function quantity(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 6 }).format(number) : '—'
}
function shortDate(value: string | null | undefined) { return value ? value.slice(5, 10).replace('-', ' / ') : '未设日期' }
function taskName(task: ProductionDashboardTask) { return task.products.map(product => product.name).join('、') || task.task_number }
function statusTone(status: string) { return status === 'COMPLETED' ? 'success' : status === 'PAUSED' ? 'warning' : ['DRAFT', 'PENDING_VALIDATION', 'READY'].includes(status) ? 'neutral' : '' }
function dueText(task: ProductionDashboardTask) {
  if (task.days_to_due === null) return '未设交期'
  if (['COMPLETED', 'CANCELLED'].includes(task.status)) return task.status_display
  return task.days_to_due < 0 ? `已过 ${Math.abs(task.days_to_due)} 天` : task.days_to_due === 0 ? '今天到期' : `剩余 ${task.days_to_due} 天`
}
function concern(task: ProductionDashboardTask) { return task.status === 'PAUSED' ? '任务已暂停，请查看任务记录。' : `${dueText(task)}，请核对任务与计划。` }
function jobPercent(value: number | null) { return value !== null && Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0 }
function jobStatus(status: string) { return ({ COMPLETED: '已完成', IN_PROGRESS: '执行中', PAUSED: '已暂停', CANCELLED: '已取消' } as Record<string, string>)[status] || '状态待核实' }
function clearProtectedData() {
  requestSequence++
  controller?.abort()
  loading.value = false
  requestError.value = ''
  data.value = null
  forbidden.value = true
  dateDialog.value = false
}
function clearRevokedSections(result: ProductionDashboardPayload) {
  if (!data.value) return
  const sections = { ...data.value.sections }
  let changed = false
  for (const key of Object.keys(sections) as (keyof typeof sections)[]) {
    const latest = result.sections[key]
    if (latest.state === 'FORBIDDEN' && sections[key].state !== 'FORBIDDEN') {
      sections[key] = { state: 'FORBIDDEN', reason: latest.reason, data: null }
      changed = true
    }
  }
  const receiptData = sections.receipts.data
  if (result.sections.receipts.data?.pending_state === 'FORBIDDEN' && receiptData && receiptData.pending_state !== 'FORBIDDEN') {
    sections.receipts = { ...sections.receipts, data: { ...receiptData, pending_state: 'FORBIDDEN', pending_products: [] } }
    changed = true
  }
  if (!changed) return
  // 日期查询只同步撤权信息，旧主请求也不能重新恢复已撤权的快照。
  requestSequence++
  controller?.abort()
  loading.value = false
  data.value = { ...data.value, sections }
}

async function load(clear = false) {
  // 总览的“今日入库”随上海业务日期刷新；车间保留手选历史日期。
  if (props.role === 'executive') activeQuery = { ...activeQuery, production_date: today() }
  controller?.abort()
  controller = new AbortController()
  const sequence = ++requestSequence
  loading.value = true
  requestError.value = ''
  forbidden.value = false
  if (clear) { dateDialog.value = false; data.value = null }
  try {
    const result = await fetchProductionDashboard(activeQuery, controller.signal)
    if (sequence !== requestSequence) return
    data.value = result
    if (result.sections.tasks.state === 'FORBIDDEN') dateDialog.value = false
    now.value = Date.now()
  } catch (error) {
    if (sequence !== requestSequence || controller.signal.aborted) return
    const status = (error as { response?: { status?: number } })?.response?.status
    if (status === 401 || status === 403) clearProtectedData()
    else requestError.value = '生产信息暂时无法加载，请稍后重试。'
  } finally {
    if (sequence === requestSequence) loading.value = false
  }
}
function applyFilters() {
  focus.value = 'ALL'
  activeQuery = { q: form.q.trim(), days: form.days, status: form.status, focus: focus.value, workshop: category.value, production_date: form.production_date }
  void load(true)
}
function reset() {
  Object.assign(form, { q: '', days: 7, status: 'ALL', production_date: today() })
  applyFilters()
}
function selectFocus(value: ProductionDashboardFocus | null) {
  if (value === null) { void ownerLayout.value?.openModule('outsourcing'); return }
  focus.value = focus.value === value ? 'ALL' : value
  activeQuery = { ...activeQuery, focus: focus.value }
  void load(true)
}
function selectCategory(value: ProductionDashboardCategory) {
  category.value = value
  activeQuery = { ...activeQuery, workshop: value }
  void load(true)
}
function openDay(date: string) {
  selectedDate.value = date
  dateQuery = { ...data.value?.filters, focus: 'ALL', task_date: date }
  dateDialog.value = true
  void loadDate(1)
}
async function loadDate(page: number) {
  dateController?.abort()
  dateController = new AbortController()
  const sequence = ++dateRequestSequence
  datePage.value = page
  dateLoading.value = true
  dateError.value = ''
  dateForbidden.value = false
  dateData.value = null
  try {
    const result = await fetchProductionDashboard({ ...dateQuery, task_page: page }, dateController.signal)
    if (sequence !== dateRequestSequence) return
    clearRevokedSections(result)
    const section = result.sections.tasks
    if (section.state === 'FORBIDDEN') dateForbidden.value = true
    else if (section.state === 'UNKNOWN') dateError.value = section.reason || '日期任务明细暂不可用，请重试。'
    else dateData.value = section.data
  } catch (error) {
    if (sequence !== dateRequestSequence || dateController.signal.aborted) return
    const status = (error as { response?: { status?: number } })?.response?.status
    if (status === 401 || status === 403) clearProtectedData()
    else dateError.value = '日期任务明细加载失败，请重试。'
  } finally {
    if (sequence === dateRequestSequence) dateLoading.value = false
  }
}
function syncFullscreen() { fullscreen.value = document.fullscreenElement === root.value }
async function toggleFullscreen() {
  fullscreenError.value = ''
  try {
    if (fullscreen.value) await document.exitFullscreen()
    else if (root.value?.requestFullscreen) await root.value.requestFullscreen()
    else fullscreenError.value = '浏览器暂不支持全屏，请使用 F11。'
  } catch { fullscreenError.value = '浏览器未允许全屏，请重试或使用 F11。' }
}
onMounted(() => {
  applyFilters()
  clock = setInterval(() => { now.value = Date.now() }, 30_000)
  document.addEventListener('fullscreenchange', syncFullscreen)
})
watch(() => props.role, () => { dateDialog.value = false; if (fullscreen.value) void toggleFullscreen(); reset() })
watch(dateDialog, visible => {
  if (!visible) {
    dateRequestSequence++
    dateController?.abort()
    dateData.value = null
    dateLoading.value = false
    dateError.value = ''
    dateForbidden.value = false
    datePage.value = 1
    dateQuery = {}
  }
}, { flush: 'sync' })
onBeforeUnmount(() => {
  requestSequence++
  dateRequestSequence++
  controller?.abort()
  dateController?.abort()
  clearInterval(clock)
  document.removeEventListener('fullscreenchange', syncFullscreen)
  if (document.fullscreenElement === root.value) void document.exitFullscreen().catch(error => console.warn('退出生产工作台全屏失败', error))
})
</script>

<template>
  <div ref="root" class="production-dashboard" :class="{ 'is-fullscreen': fullscreen, 'production-dashboard--overview': role === 'executive' }" data-testid="production-dashboard" :data-role="role" :data-state="pageState" :aria-busy="loading">
    <div class="pd-content">
    <header class="pd-heading">
      <div><h1>{{ title }}</h1><p>{{ subtitle }}</p></div>
      <div class="pd-heading__actions">
        <span v-if="updated" class="pd-updated">更新于 {{ updated }}</span>
        <button v-if="role === 'executive'" class="pd-button" type="button" :aria-expanded="showOverviewFilters" @click="showOverviewFilters = !showOverviewFilters">筛选</button>
        <button class="pd-button" type="button" data-testid="production-refresh" :disabled="loading" @click="load()">{{ loading ? '刷新中…' : '刷新' }}</button>
        <button v-if="role === 'workshop'" class="pd-button" type="button" data-testid="production-fullscreen" @click="toggleFullscreen">{{ fullscreen ? '退出全屏' : '现场全屏' }}</button>
      </div>
    </header>

    <form v-show="role !== 'executive' || showOverviewFilters" class="pd-filters pd-glass" @submit.prevent="applyFilters">
      <label class="pd-field pd-field--search">查找任务<input v-model="form.q" aria-label="查找任务" type="search" placeholder="任务编号或产品名称" autocomplete="off" /></label>
      <label class="pd-field">交期范围<select v-model.number="form.days" aria-label="交期范围"><option :value="7">未来 7 天及逾期</option><option :value="3">未来 3 天及逾期</option></select></label>
      <label class="pd-field">任务状态<select v-model="form.status" aria-label="任务状态"><option value="ALL">全部状态</option><option value="PENDING_VALIDATION">待确认</option><option value="READY">已接单</option><option value="IN_PRODUCTION">生产中</option><option value="PAUSED">已暂停</option><option value="COMPLETED">已完成</option></select></label>
      <label v-if="role === 'workshop'" class="pd-field pd-field--date">生产日期<input v-model="form.production_date" aria-label="生产日期" type="date" required /></label>
      <button class="pd-button" type="button" data-testid="production-reset" @click="reset">重置</button>
      <button class="pd-button pd-button--primary" type="submit">应用筛选</button>
      <span class="pd-filter-note">交期按任务统计，报工与成品入库分别展示。</span>
    </form>

    <div v-if="fullscreenError" class="pd-banner" role="alert">{{ fullscreenError }}</div>
    <div v-if="pageState === 'stale'" class="pd-banner" role="status" data-testid="production-stale">
      <span><strong>{{ requestError ? '刷新失败' : '数据已过期' }}</strong>　当前保留上次快照<span v-if="updated">（{{ updated }}）</span>，请刷新后再判断任务进展。</span>
      <button class="pd-button" type="button" :disabled="loading" @click="load()">重新加载</button>
    </div>

    <div v-if="pageState === 'loading'" aria-label="生产信息加载中">
      <div class="pd-loading-grid"><div v-for="item in 4" :key="item" class="pd-skeleton pd-glass"><span /><span /><span /></div></div>
      <div class="pd-skeleton pd-skeleton--panel pd-glass"><span /><span /><p class="pd-muted">正在读取生产信息…</p></div>
    </div>
    <section v-else-if="['forbidden', 'error'].includes(pageState) || (pageState === 'empty' && role !== 'executive')" class="pd-state pd-glass" role="status">
      <span class="pd-state__icon" aria-hidden="true">{{ pageState === 'forbidden' ? '!' : '—' }}</span>
      <h2>{{ pageState === 'forbidden' ? '暂无生产工作台查看权限' : pageState === 'error' ? '生产信息暂时无法加载' : '当前范围没有生产记录' }}</h2>
      <p>{{ pageState === 'forbidden' ? '当前账号没有相应生产数据的查看权限，请联系管理员。' : pageState === 'error' ? requestError : '可以调整交期、状态或关键词后重试。' }}</p>
      <button v-if="pageState !== 'forbidden'" class="pd-button pd-button--primary" type="button" data-testid="production-retry" @click="pageState === 'empty' ? reset() : load()">{{ pageState === 'empty' ? '重置筛选' : '重试加载' }}</button>
    </section>

    <template v-else-if="data">
      <template v-if="role === 'owner'">
        <div class="pd-metrics">
          <button v-for="metric in metrics" :key="metric.key" v-glass-spotlight.tilt class="pd-metric pd-glass" type="button" :data-testid="`production-metric-${metric.key}`" :aria-pressed="metric.filter ? focus === metric.filter : undefined" :disabled="metric.value == null || loading" @click="selectFocus(metric.filter)">
            <span class="pd-metric__heading">{{ metric.label }}<component :is="metric.icon" aria-hidden="true" /></span>
            <span class="pd-metric__value"><b :class="{ 'pd-danger': metric.danger }">{{ quantity(metric.value) }}</b><small>单</small></span>
            <p>{{ metric.value == null ? '暂无可用数据' : metric.note }}</p>
          </button>
        </div>
        <ProductionModuleLayout ref="ownerLayout" :modules="ownerModules" variant="owner">
          <template #production="{ expanded }">
            <div v-if="taskRows.length" class="pd-table-scroll" data-testid="production-task-list">
              <table class="pd-task-table"><thead><tr><th>生产任务</th><th>交期</th><th>阶段进度</th><th>任务状态</th><th>操作</th></tr></thead><tbody>
                <tr v-for="task in (expanded ? tasks?.items : taskRows)" :key="task.id">
                  <td><RouterLink v-if="safeHref(task.href)" :to="task.href" class="pd-link pd-task-title">{{ taskName(task) }}</RouterLink><strong v-else class="pd-task-title">{{ taskName(task) }}</strong><small>{{ task.task_number }}</small><small v-for="product in task.products" :key="product.id">{{ product.name }} · {{ quantity(product.quantity) }} {{ product.unit }}</small></td>
                  <td><strong>{{ shortDate(task.delivery_date) }}</strong><small>{{ dueText(task) }}</small></td>
                  <td><ProductionProgress label="金工汇总" :status="task.stages.metal.state" :percentage="task.stages.metal.percent" :display="task.stages.metal.label" /><ProductionProgress label="裁缝汇总" :status="task.stages.sewing.state" :percentage="task.stages.sewing.percent" :display="task.stages.sewing.label" /><ProductionProgress label="成品入库" :status="task.stages.assembly.state" :percentage="task.stages.assembly.percent" :display="task.stages.assembly.label" receipt /></td>
                  <td><span class="pd-tag" :class="`pd-tag--${statusTone(task.status)}`">{{ task.status_display }}</span></td><td><RouterLink v-if="safeHref(task.href)" :to="task.href" class="pd-link" :aria-label="`查看任务 ${task.task_number}`">查看</RouterLink></td>
                </tr>
              </tbody></table>
            </div>
            <p v-else class="pd-section-empty">{{ sectionMessage(data.sections.tasks, '当前筛选范围暂无生产任务') }}</p>
            <div class="pd-panel__note"><span>{{ tasks ? `展示 ${expanded ? tasks.items.length : taskRows.length} / ${tasks.total} 单；裁缝汇总含裁剪。` : '阶段进度按可查看范围展示。' }}</span><RouterLink v-if="tasks" class="pd-link" to="/production-tasks">查看任务列表</RouterLink></div>
          </template>
          <template #delivery>
            <div v-if="taskRows.length" class="pd-panel__body pd-timeline"><div v-for="task in taskRows" :key="task.id" class="pd-timeline__row" :class="{ 'pd-timeline__row--overdue': task.days_to_due !== null && task.days_to_due < 0 && task.status !== 'COMPLETED' }"><span class="pd-timeline__date">{{ shortDate(task.delivery_date) }}</span><span class="pd-timeline__node" /><div><RouterLink v-if="safeHref(task.href)" :to="task.href" class="pd-link"><strong>{{ taskName(task) }}</strong></RouterLink><strong v-else>{{ taskName(task) }}</strong><small>{{ task.task_number }} · {{ dueText(task) }}</small></div></div></div>
            <p v-else class="pd-section-empty">{{ sectionMessage(data.sections.tasks, '当前范围暂无交期节点') }}</p>
          </template>
          <template #outsourcing="{ expanded }">
            <div v-if="outsourcing?.items.length" class="pd-panel__body"><div v-for="item in (expanded ? outsourcing.items : outsourcing.items.slice(0, 4))" :key="item.row_key" class="pd-compact-row"><div><RouterLink v-if="safeHref(item.href)" :to="item.href" class="pd-link"><strong>{{ item.order_number }}</strong></RouterLink><strong v-else>{{ item.order_number }}</strong><small>{{ item.factory_names.join('、') || '—' }} · 预计 {{ shortDate(item.delivery_date) }}</small><small v-for="(amount, index) in item.quantities" :key="index">已回货：{{ amount.name ? `${amount.name} ` : '' }}{{ quantity(amount.quantity) }} {{ amount.unit }}</small><small v-if="item.receipt_state === 'UNKNOWN'">回货数量待核实</small></div><div><span class="pd-tag">{{ item.status_display }}</span><small v-if="item.receipt_state === 'MISSING'">回货凭证待核实</small></div></div></div>
            <p v-else class="pd-section-empty">{{ sectionMessage(data.sections.outsourcing, '当前范围暂无待回货外发单') }}</p>
            <div v-if="outsourcing" class="pd-panel__note"><span>展示 {{ expanded ? outsourcing.items.length : Math.min(outsourcing.items.length, 4) }} / {{ outsourcing.total }} 单</span><RouterLink class="pd-link" to="/workshop/outsourcing">查看委外列表</RouterLink></div>
          </template>
          <template #todo>
            <div v-if="attention.length" class="pd-panel__body"><div v-for="task in attention" :key="task.id" class="pd-compact-row"><div><strong>{{ taskName(task) }}</strong><small>{{ concern(task) }}</small><small>{{ task.task_number }}</small></div><RouterLink v-if="safeHref(task.href)" :to="task.href" class="pd-link">查看</RouterLink></div></div>
            <p v-else class="pd-section-empty">{{ sectionMessage(data.sections.tasks, '已加载任务中暂无需优先协调的事项') }}</p>
          </template>
        </ProductionModuleLayout>
      </template>

      <ProductionOverview v-else-if="role === 'executive'" :data="data" @open-day="openDay" />

      <template v-else>
        <section :key="`summary-${fullscreen}`" v-glass-spotlight.tilt="!fullscreen" class="pd-summary pd-glass">
          <div><div class="pd-process-tabs" role="group" aria-label="车间工序"><button v-for="option in ([['METAL', '金工'], ['SEWING', '缝纫'], ['ASSEMBLY', '装配']] as const)" :key="option[0]" class="pd-button" type="button" :data-testid="`production-process-${option[0]}`" :aria-pressed="category === option[0]" :disabled="loading" @click="selectCategory(option[0])">{{ option[1] }}</button></div><p>{{ isAssembly ? '按产品查看成品入库，数量与报工分别统计。' : '按产品和工序查看报工记录。' }}</p></div>
          <div class="pd-summary__stats"><div class="pd-summary__stat"><b>{{ quantity(workshop?.plan_count) }}</b><small>当前工序计划 / 项</small></div><div class="pd-summary__stat"><b>{{ quantity(isAssembly ? receipts?.today_count : reports?.report_count) }}</b><small>{{ isAssembly ? '当日入库 / 笔' : '全部车间当日报工 / 笔' }}</small></div><div class="pd-summary__stat"><b>{{ shortDate(data.filters.production_date) }}</b><small>统计日期</small></div></div>
        </section>
        <ProductionModuleLayout :modules="workshopModules" variant="workshop">
          <template #production="{ expanded }">
        <div v-if="jobRows.length" class="pd-panel__body pd-jobs" data-testid="production-job-list">
          <article v-for="job in (expanded ? workshop?.items : jobRows)" :key="job.key" class="pd-job pd-job--inner" :class="{ 'pd-job--receipt': isAssembly }">
            <div class="pd-job__head"><small>{{ isAssembly ? '成品入库' : job.craft_name }}</small><span class="pd-tag" :class="job.status === 'COMPLETED' ? 'pd-tag--success' : ''">{{ jobStatus(job.status) }}</span></div>
            <h2>{{ job.name }}</h2><p class="pd-job__meta">{{ job.task_number }} ／ 计划 {{ shortDate(job.plan_date) }}</p>
            <div class="pd-job__progress"><div><b>{{ quantity(job.cumulative) }}</b><small> / {{ quantity(job.required) }} {{ job.unit }}</small></div><small>{{ isAssembly ? '累计入库' : '本工序累计报工' }}</small></div>
            <div v-if="job.progress.state === 'READY' && job.progress.percent !== null" class="pd-job__track" role="progressbar" :aria-label="`${job.name}${isAssembly ? '入库' : '报工'}进度`" :aria-valuenow="jobPercent(job.progress.percent)" :aria-valuemin="0" :aria-valuemax="100"><span :style="{ width: `${jobPercent(job.progress.percent)}%` }" /></div>
            <p v-else class="pd-muted">{{ job.progress.label || '进度暂不可用' }}</p>
            <div class="pd-job__foot"><span>当日{{ isAssembly ? '入库' : '报工' }} <strong>{{ quantity(job.today) }} {{ job.unit }}</strong></span><span>剩余 <strong>{{ quantity(job.remaining) }} {{ job.unit }}</strong></span></div>
            <RouterLink v-if="safeHref(job.href)" :to="job.href" class="pd-button pd-job__action">查看{{ isAssembly ? '装配计划' : '工序任务' }}</RouterLink>
          </article>
        </div>
        <p v-else class="pd-section-empty">{{ sectionMessage(data.sections.workshop, '当前范围没有车间任务，可调整筛选条件。') }}</p>
        <div v-if="workshop" class="pd-panel__note"><span>展示 {{ expanded ? workshop.items.length : jobRows.length }} / {{ workshop.total }} 项工序任务</span><RouterLink class="pd-link" :to="`/workshop/plans/${category === 'METAL' ? 'metalworking' : category === 'SEWING' ? 'sewing' : 'assembly'}`">查看全部计划</RouterLink></div>
          </template>
          <template #output="{ expanded }">
            <template v-if="isAssembly"><div v-if="receipts?.items.length" class="pd-panel__body"><div v-for="item in (expanded ? receipts.items : receipts.items.slice(0, 5))" :key="item.id" class="pd-report"><time>{{ shortDate(item.date) }}</time><div><RouterLink v-if="safeHref(item.href)" :to="item.href" class="pd-link"><strong>{{ item.name }}</strong></RouterLink><strong v-else>{{ item.name }}</strong><small>{{ item.number }}</small></div><span class="pd-report__person">成品入库</span><strong>{{ quantity(item.quantity) }} {{ item.unit }}</strong></div></div><p v-else class="pd-section-empty">{{ sectionMessage(data.sections.receipts, '所选生产日期暂无成品入库记录') }}</p><div v-if="receipts" class="pd-panel__note"><span>展示 {{ expanded ? receipts.items.length : Math.min(receipts.items.length, 5) }} / {{ receipts.total }} 笔</span><RouterLink class="pd-link" to="/inventory/finished-goods?tab=records">查看入库记录</RouterLink></div></template>
            <template v-else><div v-if="reports?.items.length" class="pd-panel__body"><div v-for="item in (expanded ? reports.items : reports.items.slice(0, 5))" :key="item.id" class="pd-report"><time>{{ shortDate(item.production_date) }}</time><div><RouterLink v-if="safeHref(item.href)" :to="item.href" class="pd-link"><strong>{{ item.task_number }}</strong></RouterLink><strong v-else>{{ item.task_number }}</strong><small>{{ item.number }}</small></div><span class="pd-report__person">{{ item.workshop_name }}</span><div><strong v-for="(line, index) in item.lines" :key="index" style="display: block">{{ line.operation }} {{ quantity(line.quantity) }} {{ line.unit }}</strong></div></div></div><p v-else class="pd-section-empty">{{ sectionMessage(data.sections.reports, '所选生产日期暂无报工记录') }}</p><div v-if="reports" class="pd-panel__note"><span>展示 {{ expanded ? reports.items.length : Math.min(reports.items.length, 5) }} / {{ reports.total }} 笔</span><RouterLink class="pd-link" :to="`/workshop/work-reports/days/${data.filters.production_date}`">查看报工记录</RouterLink></div></template>
          </template>
          <template #todo><div v-if="attention.length" class="pd-panel__body"><div v-for="task in attention" :key="task.id" class="pd-alert"><strong>{{ taskName(task) }}</strong><p>{{ concern(task) }} {{ task.task_number }}</p><RouterLink v-if="safeHref(task.href)" :to="task.href" class="pd-link">查看任务</RouterLink></div></div><p v-else class="pd-section-empty">{{ sectionMessage(data.sections.tasks, '已加载任务中暂无重点关注项') }}</p></template>
        </ProductionModuleLayout>
      </template>
    </template>

    <AppWindowDialog v-model="dateDialog" :title="`${selectedDate} 到期任务`" :width="680" :height="480" modal-class="production-dashboard-dialog" destroy-on-close>
      <div class="pd-date-content" data-testid="production-due-dialog" :data-state="dateState" :aria-busy="dateLoading">
        <p v-if="dateLoading" class="pd-date-state">正在读取该日任务…</p>
        <p v-else-if="dateForbidden" class="pd-date-state">没有此日期任务明细的查看权限</p>
        <div v-else-if="dateError" class="pd-date-state"><p role="alert">{{ dateError }}</p><button class="pd-date-button" type="button" @click="loadDate(datePage)">重试加载</button></div>
        <template v-else>
          <p>共 {{ quantity(dateData?.total ?? 0) }} 单，本页 {{ selectedDayRows.length }} 单。</p>
          <div v-for="task in selectedDayRows" :key="task.id" class="pd-date-row"><div><strong>{{ taskName(task) }}</strong><small>{{ task.task_number }} · {{ task.status_display }}</small></div><RouterLink v-if="safeHref(task.href)" :to="task.href" class="pd-date-link" @click="dateDialog = false">查看任务</RouterLink></div>
          <p v-if="!selectedDayRows.length" class="pd-date-state">当前筛选条件下，该日没有到期任务。</p>
        </template>
      </div>
      <template #footer>
        <div class="pd-date-pagination"><span v-if="dateData">第 {{ datePage }} 页</span><button class="pd-date-button" type="button" :disabled="dateLoading || datePage <= 1 || dateForbidden" @click="loadDate(datePage - 1)">上一页</button><button class="pd-date-button" type="button" data-testid="production-due-next" :disabled="dateLoading || !dateData || datePage * 20 >= dateData.total" @click="loadDate(datePage + 1)">下一页</button></div>
      </template>
    </AppWindowDialog>
    </div>
  </div>
</template>

<style lang="scss" src="./productionDashboard.scss" />
