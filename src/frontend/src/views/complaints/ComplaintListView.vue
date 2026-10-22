<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { DataAnalysis, Download, Plus, Refresh, Search, Setting } from '@element-plus/icons-vue'

import ComplaintCreateDialog from '@/components/complaints/ComplaintCreateDialog.vue'
import { fetchComplaintOptions, fetchComplaints, fetchComplaintStats } from '@/api/complaints'
import { useOptions } from '@/composables/useOptions'
import { useAuthStore } from '@/stores/auth'
import type { Complaint, ComplaintDictionaryItem, ComplaintOptions, ComplaintQuery, ComplaintSlaStatus, ComplaintStats, ComplaintStatus } from '@/types/complaint'
import { complaintDate, complaintRequestMessage } from '@/utils/complaintFeedback'

const props = withDefaults(defineProps<{ embedded?: boolean; customerId?: string; customerName?: string }>(), {
  embedded: false, customerId: '', customerName: '',
})
const PAGE_SIZES = [20, 50, 100]
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const complaintTypeSource = useOptions('COMPLAINT_TYPE')
const severitySource = useOptions('COMPLAINT_SEVERITY')
const loading = ref(false)
const errorMessage = ref('')
const rows = ref<Complaint[]>([])
const stats = ref<ComplaintStats | null>(null)
const options = ref<ComplaintOptions | null>(null)
const total = ref(0)
const selectedRows = ref<Complaint[]>([])
const createVisible = ref(false)
const showAnalysis = ref(true)
const routePageSize = Number(route.query.page_size)
const page = ref(Math.max(1, Number(route.query.page) || 1))
const pageSize = ref(PAGE_SIZES.includes(routePageSize) ? routePageSize : 50)
const visibleColumns = reactive({ customer: true, order: true, type: true, severity: true, status: true, owner: true, sla: true, updated: true })
const filters = reactive({
  q: String(route.query.q || ''),
  complaint_type_item_id: String(route.query.complaint_type_item_id || ''),
  severity_item_id: String(route.query.severity_item_id || ''),
  status: String(route.query.status || '') as ComplaintStatus | '',
  owner_employee_id: String(route.query.owner_employee_id || ''),
  sla_status: String(route.query.sla_status || '') as ComplaintSlaStatus | '',
})
let requestId = 0
let statsRequestId = 0
const statsLoading = ref(false)
const statsError = ref('')
const optionsError = ref('')

function publishedItems(source: typeof complaintTypeSource, fallback: ComplaintDictionaryItem[] = []) {
  if (!source.options.value.length) return fallback
  return source.options.value.map(item => ({
    id: item.id, item_code: item.code, display_name: item.label,
    description: typeof item.extra.description === 'string' ? item.extra.description : '',
    sort_order: item.sort_order, extra_data: item.extra as Record<string, string | number>, disabled: item.status !== 'ACTIVE',
  }))
}

const complaintTypes = computed(() => publishedItems(complaintTypeSource, options.value?.complaint_types))
const severities = computed(() => publishedItems(severitySource, options.value?.severities))
const canView = computed(() => authStore.hasPermission('customers.view_customercomplaint'))
const canCreate = computed(() => authStore.hasPermission('customers.add_customercomplaint'))
const canEdit = computed(() => authStore.hasPermission('customers.change_customercomplaint'))
const canProcess = computed(() => authStore.hasPermission('customers.process_customer_complaint'))
const maxTypeCount = computed(() => Math.max(...(stats.value?.by_type.map(item => item.count) || [1]), 1))
const metricCards = computed(() => [
  { label: '处理中', value: stats.value?.open ?? '—', note: '不含已关闭与已取消', tone: 'info' },
  { label: '已超时', value: stats.value?.sla.overdue ?? '—', note: '需优先介入', tone: 'danger' },
  { label: '待客户反馈', value: stats.value?.waiting_customer_feedback ?? '—', note: '等待客户确认', tone: 'warning' },
  { label: '本月已关闭', value: stats.value?.closed_this_month ?? '—', note: '按关闭时间统计', tone: 'success' },
])

function listQuery(): ComplaintQuery {
  const query: ComplaintQuery = { page: page.value, page_size: pageSize.value }
  if (props.embedded && props.customerId) query.customer_id = props.customerId
  if (filters.q.trim()) query.q = filters.q.trim()
  if (filters.complaint_type_item_id) query.complaint_type_item_id = filters.complaint_type_item_id
  if (filters.severity_item_id) query.severity_item_id = filters.severity_item_id
  if (filters.status) query.status = filters.status
  if (filters.owner_employee_id) query.owner_employee_id = filters.owner_employee_id
  if (filters.sla_status) query.sla_status = filters.sla_status
  return query
}

function syncUrl() {
  if (!props.embedded) void router.replace({ query: listQuery() as Record<string, string | number> })
}

async function loadRows() {
  if (!canView.value) return
  const currentRequest = ++requestId
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchComplaints(listQuery())
    if (currentRequest !== requestId) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (currentRequest !== requestId) return
    rows.value = []; total.value = 0
    errorMessage.value = complaintRequestMessage(error)
  } finally {
    if (currentRequest === requestId) loading.value = false
  }
}

async function loadStats() {
  if (!canView.value) return
  const currentRequest = ++statsRequestId
  statsLoading.value = true; statsError.value = ''; stats.value = null
  try {
    const result = await fetchComplaintStats({ ...listQuery(), page: undefined, page_size: undefined })
    if (currentRequest === statsRequestId) stats.value = result
  } catch (error) {
    if (currentRequest === statsRequestId) statsError.value = complaintRequestMessage(error)
  } finally {
    if (currentRequest === statsRequestId) statsLoading.value = false
  }
}

async function refresh() { await Promise.all([loadRows(), loadStats()]) }

function applyFilters() { page.value = 1; selectedRows.value = []; syncUrl(); void refresh() }
function resetFilters() {
  Object.assign(filters, { q: '', complaint_type_item_id: '', severity_item_id: '', status: '', owner_employee_id: '', sla_status: '' })
  applyFilters()
}
function changePage() { syncUrl(); void refresh() }

function openDetail(row: Complaint, action?: 'edit' | 'progress') {
  const query: Record<string, string> = {}
  if (props.embedded) Object.assign(query, { return_to: 'customer', customer_id: props.customerId })
  if (action) query.action = action
  void router.push({ name: 'complaint-detail', params: { complaintId: row.id }, query })
}

function slaText(row: Complaint) {
  if (row.sla_status === 'OVERDUE') return `已超时 · ${complaintDate(row.target_completion_at)}`
  if (row.sla_status === 'AT_RISK') return `即将到期 · ${complaintDate(row.target_completion_at)}`
  if (row.sla_status === 'COMPLETED') return '已结束'
  return complaintDate(row.target_completion_at)
}
function statusClass(row: Complaint) {
  if (row.status === 'CLOSED') return 'success'
  if (row.status === 'CANCELLED') return 'neutral'
  if (row.status === 'CUSTOMER_CONFIRMATION') return 'warning'
  return 'info'
}
function severityClass(code: string) {
  if (['CRITICAL', 'SERIOUS'].includes(code)) return 'danger'
  if (['IMPORTANT', 'HIGH'].includes(code)) return 'warning'
  return 'info'
}

function exportCurrentPage() {
  if (!rows.value.length) return ElMessage.info('当前没有可导出的客诉记录。')
  const headers = ['客诉编号', '客户', '关联订单', '类型', '严重程度', '状态', '负责人', '目标完成', '最近更新']
  const escape = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`
  const lines = rows.value.map(row => [row.complaint_code, row.customer.account_name, row.source_order_reference, row.complaint_type.display_name, row.severity.display_name, row.status_label, row.owner.display_name, row.target_completion_at, row.updated_at].map(escape).join(','))
  const blob = new Blob([`\ufeff${headers.map(escape).join(',')}\n${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `客诉列表-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(link.href)
}

watch(() => props.customerId, value => {
  if (!props.embedded || !value) return
  page.value = 1
  void refresh()
})

onBeforeUnmount(() => { requestId++; statsRequestId++ })
onMounted(async () => {
  if (!canView.value) return
  await Promise.all([
    fetchComplaintOptions().then(value => { options.value = value }).catch(error => { optionsError.value = complaintRequestMessage(error) }),
    complaintTypeSource.load().catch(() => []),
    severitySource.load().catch(() => []),
    refresh(),
  ])
})
</script>

<template>
  <section class="complaint-page erp-glass-list" :class="{ embedded }">
    <el-empty v-if="!canView" description="当前账号无权查看客诉" :image-size="72" />
    <template v-else>
      <el-alert v-if="optionsError" type="warning" :title="`筛选选项加载失败：${optionsError}`" :closable="false" />
      <el-alert v-if="statsError" type="warning" :title="`统计加载失败：${statsError}`" :closable="false"><template #default><el-button link @click="loadStats">重试统计</el-button></template></el-alert>
      <section v-glass-spotlight class="erp-list-filter" :class="{ 'embedded-filter-group': embedded }">
      <header v-if="!embedded" class="page-heading erp-list-heading">
        <div><p class="eyebrow">SERVICE RECOVERY</p><h1>{{ embedded ? '客户客诉' : '客诉管理' }}</h1></div>
        <div class="heading-actions"><el-button class="erp-button-motion" v-if="!embedded" :icon="DataAnalysis" @click="showAnalysis = !showAnalysis">{{ showAnalysis ? '收起分析' : '展开分析' }}</el-button><el-button class="erp-button-motion" v-if="canCreate" type="primary" :icon="Plus" @click="createVisible = true">新建客诉</el-button></div>
      </header>
      <div v-else class="embedded-toolbar erp-list-toolbar">
        <span>当前客户的客诉受理、责任协同与处理进度</span>
        <el-button class="erp-button-motion" v-if="canCreate" type="primary" :icon="Plus" @click="createVisible = true">新建客诉</el-button>
      </div>

      <section v-if="embedded" class="metric-strip" :aria-busy="statsLoading" :aria-label="statsLoading ? '正在加载客诉统计' : '客诉统计'"><article v-for="card in metricCards" :key="card.label" :class="`metric--${card.tone}`"><span>{{ card.label }}</span><strong>{{ statsLoading ? '…' : card.value }}</strong><small>{{ card.note }}</small></article></section>
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" class="error"><template #default><el-button link type="primary" @click="refresh">重试</el-button></template></el-alert>

      <section class="filter-panel erp-list-filters">
        <el-input v-model="filters.q" :prefix-icon="Search" clearable placeholder="搜索客户 / 客诉编号 / 标题" @keyup.enter="applyFilters" />
        <el-select v-model="filters.complaint_type_item_id" clearable placeholder="客诉类型：全部"><el-option v-for="item in complaintTypes" :key="item.id" :label="item.display_name" :value="item.id" /></el-select>
        <el-select v-model="filters.severity_item_id" clearable placeholder="严重程度：全部"><el-option v-for="item in severities" :key="item.id" :label="item.display_name" :value="item.id" /></el-select>
        <el-select v-model="filters.status" clearable placeholder="处理状态：全部"><el-option v-for="item in options?.statuses" :key="item.value" :label="item.label" :value="item.value" /></el-select>
        <el-select v-model="filters.owner_employee_id" clearable placeholder="负责人：全部"><el-option v-for="item in options?.employees" :key="item.id" :label="item.display_name" :value="item.id" /></el-select>
        <el-select v-model="filters.sla_status" clearable placeholder="SLA：全部"><el-option label="正常" value="NORMAL" /><el-option label="即将到期" value="AT_RISK" /><el-option label="已超时" value="OVERDUE" /><el-option label="已结束" value="COMPLETED" /></el-select>
        <div class="erp-list-filter-actions"><el-button class="erp-button-motion" @click="resetFilters">重置</el-button><el-button class="erp-button-motion" type="primary" @click="applyFilters">应用筛选</el-button></div>
      </section>

      </section>

      <section v-if="showAnalysis && !embedded" class="analysis-grid">
        <article class="erp-list-data"><h2>客诉类型分布</h2><div v-if="stats?.by_type.length" class="bars"><p v-for="item in stats.by_type.slice(0, 5)" :key="item.complaint_type_item_id"><span>{{ item.complaint_type_item__display_name }}</span><i><b :style="{ width: `${Math.max(item.count / maxTypeCount * 100, 6)}%` }" /></i><strong>{{ item.count }}</strong></p></div><div v-else class="empty">暂无数据</div></article>
        <article class="erp-list-data"><h2>SLA 处理状态</h2><div class="sla-grid"><p><span>正常处理中</span><strong>{{ stats?.sla.normal ?? '—' }}</strong></p><p class="risk"><span>24 小时内到期</span><strong>{{ stats?.sla.at_risk ?? '—' }}</strong></p><p class="overdue"><span>已超时</span><strong>{{ stats?.sla.overdue ?? '—' }}</strong></p><p class="done"><span>已结束</span><strong>{{ stats ? stats.closed + stats.cancelled : '—' }}</strong></p></div></article>
        <article class="erp-list-data"><h2>责任协同概览</h2><div v-if="stats?.by_owner.length" class="owners"><p v-for="item in stats.by_owner.slice(0, 5)" :key="item.owner_employee_id"><span>{{ item.owner_employee__display_name }}</span><strong>{{ item.count }} 条</strong></p></div><div v-else class="empty">暂无数据</div></article>
      </section>

      <section class="table-card erp-list-data">
        <div class="table-toolbar erp-list-toolbar"><span>共 {{ total }} 条，已选择 {{ selectedRows.length }} 条</span><div><el-dropdown><el-button class="erp-button-motion" :icon="Setting">列设置</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-for="(_, key) in visibleColumns" :key="key"><el-checkbox v-model="visibleColumns[key]">{{ ({ customer: '客户', order: '关联订单', type: '类型', severity: '等级', status: '状态', owner: '负责人', sla: 'SLA', updated: '最近更新' } as Record<string, string>)[key] }}</el-checkbox></el-dropdown-item></el-dropdown-menu></template></el-dropdown><el-button class="erp-button-motion" :icon="Download" @click="exportCurrentPage">导出当前页</el-button><el-button class="erp-button-motion" :icon="Refresh" :loading="loading" @click="refresh">刷新</el-button></div></div>
        <div class="erp-list-table-frame" :class="{ 'embedded-table-group': embedded }">
        <el-table :height="embedded ? undefined : '100%'" :max-height="embedded ? 'min(520px, 56vh)' : undefined" v-loading="loading" :data="rows" row-key="id" empty-text="暂无符合条件的真实客诉" @selection-change="selectedRows = $event">
          <el-table-column v-if="embedded" type="selection" width="48" />
          <el-table-column label="客诉编号" min-width="150"><template #default="{ row }"><button class="code-link" @click="openDetail(row)">{{ row.complaint_code }}</button></template></el-table-column>
          <el-table-column v-if="visibleColumns.customer" label="客户" min-width="210" show-overflow-tooltip><template #default="{ row }">{{ row.customer.account_name }}</template></el-table-column>
          <el-table-column v-if="visibleColumns.order" label="关联订单" min-width="150" show-overflow-tooltip><template #default="{ row }">{{ row.source_order_reference || '—' }}</template></el-table-column>
          <el-table-column v-if="visibleColumns.type" label="类型" min-width="116"><template #default="{ row }">{{ row.complaint_type.display_name }}</template></el-table-column>
          <el-table-column v-if="visibleColumns.severity" label="等级" width="96"><template #default="{ row }"><span class="solid-tag" :class="['erp-list-tag', `erp-list-tag--${severityClass(row.severity.item_code)}`]">{{ row.severity.display_name }}</span></template></el-table-column>
          <el-table-column v-if="visibleColumns.status" label="状态" min-width="120"><template #default="{ row }"><span class="solid-tag" :class="['erp-list-tag', `erp-list-tag--${statusClass(row)}`]">{{ row.status_label }}</span></template></el-table-column>
          <el-table-column v-if="visibleColumns.owner" label="负责人" min-width="116"><template #default="{ row }">{{ row.owner.display_name }}</template></el-table-column>
          <el-table-column v-if="visibleColumns.sla" label="SLA" min-width="188"><template #default="{ row }"><span :class="{ overdue: row.sla_status === 'OVERDUE' }">{{ slaText(row) }}</span></template></el-table-column>
          <el-table-column v-if="visibleColumns.updated" label="最近更新" min-width="170"><template #default="{ row }">{{ complaintDate(row.updated_at) }}</template></el-table-column>
          <el-table-column label="操作" width="142" fixed="right"><template #default="{ row }"><el-button link @click="openDetail(row)">查看</el-button><el-dropdown v-if="canEdit || canProcess" trigger="click"><el-button link>更多</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="canEdit" @click="openDetail(row, 'edit')">编辑客诉信息</el-dropdown-item><el-dropdown-item v-if="canProcess && !['CLOSED', 'CANCELLED'].includes(row.status)" @click="openDetail(row, 'progress')">更新处理进展</el-dropdown-item></el-dropdown-menu></template></el-dropdown></template></el-table-column>
        </el-table>
        </div>
        <footer class="erp-list-footer">
        <el-pagination v-if="total" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="PAGE_SIZES" :total="total" layout="total, sizes, prev, pager, next" class="pagination" @change="changePage" />
        </footer>
      </section>

      <ComplaintCreateDialog v-model="createVisible" :embedded="embedded" :options="options" :complaint-types="complaintTypes" :severities="severities" :fixed-customer-id="embedded ? customerId : ''" :fixed-customer-name="customerName" @created="refresh" />
    </template>
  </section>
</template>

<style scoped lang="scss">
.complaint-page.erp-glass-list {
  overflow: auto;
  > .table-card { min-height: 200px; }
  .page-heading { justify-content: space-between; }
  .page-heading p { margin: 0; font-size: 12px; color: var(--erp-color-text-secondary); }
  .page-heading .eyebrow { display: none; }
  .heading-actions, .table-toolbar > div { display: flex; align-items: center; gap: 8px; }
  .metric-strip { margin-bottom: 12px; }
  .metric-strip small { font-size: 12px; }
  .filter-panel > :deep(.el-input) { width: 286px; }
  .filter-panel > :deep(.el-select) { width: 160px; }
  .analysis-grid { display: grid; flex: none; grid-template-columns: 1.2fr .9fr 1fr; gap: 14px; }
  .analysis-grid h2 { margin: 0 0 12px; font-size: 16px; }
  .bars p { display: grid; grid-template-columns: 110px 1fr 38px; align-items: center; gap: 10px; margin: 12px 0; font-size: 12px; }
  .bars i { height: 9px; overflow: hidden; background: var(--erp-table-header-background); }
  .bars b { height: 100%; display: block; background: var(--erp-tag-info-background); }
  .bars strong { text-align: right; }
  .sla-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .sla-grid p { min-height: 48px; display: flex; align-items: center; justify-content: space-between; margin: 0; padding: 0 12px; color: var(--erp-tag-info-text); background: var(--erp-tag-info-background); font-size: 12px; border-radius: var(--erp-radius-control); }
  .sla-grid .risk { color: var(--erp-tag-warning-text); background: var(--erp-tag-warning-background); }
  .sla-grid .overdue { color: var(--erp-tag-danger-text); background: var(--erp-tag-danger-background); }
  .sla-grid .done { color: var(--erp-tag-success-text); background: var(--erp-tag-success-background); }
  .sla-grid strong { font-size: 19px; font-variant-numeric: tabular-nums; }
  .owners p { display: flex; justify-content: space-between; margin: 0; padding: 10px 0; border-bottom: 1px solid var(--erp-color-border); font-size: 12px; }
  .empty { min-height: 140px; display: grid; place-items: center; color: var(--erp-color-text-secondary); }
  .table-toolbar { justify-content: space-between; font-size: 12px; }
  .code-link { padding: 0; border: 0; color: var(--erp-table-text); background: none; cursor: pointer; font: inherit; font-weight: 600; }
  .code-link:hover { text-decoration: underline; }
  .overdue { font-weight: 600; }
  @media (max-width: 1100px) { .analysis-grid { grid-template-columns: 1fr; } }
}
.complaint-page.erp-glass-list.embedded {
  height: auto;
  overflow: visible;
  font-size: 13px;
  line-height: 20px;

  .embedded-toolbar { justify-content: space-between; color: var(--erp-color-text-secondary); margin-bottom: 14px; }
  .metric-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 0 0 14px; }
  .metric-strip article { min-width: 0; padding: 12px 14px; border-radius: var(--erp-radius-control); background: var(--erp-glass-inner-background); }
  .metric-strip span, .metric-strip small { display: block; color: var(--erp-color-text-secondary); }
  .metric-strip span { font-size: 13px; }
  .metric-strip strong { display: block; margin: 4px 0; font-size: 24px; line-height: 32px; font-variant-numeric: tabular-nums; }
  .error { margin-bottom: 14px; }
  .table-card, .embedded-table-group { flex: none; min-height: 0; }
  .table-toolbar, .embedded-table-group :deep(.el-table .cell) { font-size: 13px; line-height: 20px; }
  .filter-panel :deep(.el-input__inner), .filter-panel :deep(.el-select__placeholder) { font-size: 13px; }
  .table-toolbar > div { flex-wrap: wrap; }
  .overdue { color: var(--erp-color-danger); }

  @media (max-width: 1100px) { .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
}

</style>
