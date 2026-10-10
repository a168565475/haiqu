<script setup lang="ts">
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
  <section class="complaint-page" :class="{ embedded }">
    <el-empty v-if="!canView" description="当前账号无权查看客诉" :image-size="72" />
    <template v-else>
      <el-alert v-if="optionsError" type="warning" :title="`筛选选项加载失败：${optionsError}`" :closable="false" />
      <el-alert v-if="statsError" type="warning" :title="`统计加载失败：${statsError}`" :closable="false"><template #default><el-button link @click="loadStats">重试统计</el-button></template></el-alert>
      <header v-if="!embedded" class="page-heading">
        <div><p class="eyebrow">SERVICE RECOVERY</p><h1>{{ embedded ? '客户客诉' : '客诉管理' }}</h1><p>{{ embedded ? '当前客户的客诉受理、责任协同与处理进度' : '跟踪受理、责任协同、处理进度与客户确认；赔付由财务模块执行' }}</p></div>
        <div class="heading-actions"><el-button v-if="!embedded" :icon="DataAnalysis" @click="showAnalysis = !showAnalysis">{{ showAnalysis ? '收起分析' : '展开分析' }}</el-button><el-button v-if="canCreate" type="primary" :icon="Plus" @click="createVisible = true">新建客诉</el-button></div>
      </header>
      <div v-else class="embedded-toolbar">
        <span>当前客户的客诉受理、责任协同与处理进度</span>
        <el-button v-if="canCreate" type="primary" :icon="Plus" @click="createVisible = true">新建客诉</el-button>
      </div>

      <section class="metric-strip" :aria-busy="statsLoading" :aria-label="statsLoading ? '正在加载客诉统计' : '客诉统计'"><article v-for="card in metricCards" :key="card.label" :class="`metric--${card.tone}`"><span>{{ card.label }}</span><strong>{{ statsLoading ? '…' : card.value }}</strong><small>{{ card.note }}</small></article></section>
      <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" class="error"><template #default><el-button link type="primary" @click="refresh">重试</el-button></template></el-alert>

      <section class="filter-panel">
        <el-input v-model="filters.q" :prefix-icon="Search" clearable placeholder="搜索客户 / 客诉编号 / 标题" @keyup.enter="applyFilters" />
        <el-select v-model="filters.complaint_type_item_id" clearable placeholder="客诉类型：全部"><el-option v-for="item in complaintTypes" :key="item.id" :label="item.display_name" :value="item.id" /></el-select>
        <el-select v-model="filters.severity_item_id" clearable placeholder="严重程度：全部"><el-option v-for="item in severities" :key="item.id" :label="item.display_name" :value="item.id" /></el-select>
        <el-select v-model="filters.status" clearable placeholder="处理状态：全部"><el-option v-for="item in options?.statuses" :key="item.value" :label="item.label" :value="item.value" /></el-select>
        <el-select v-model="filters.owner_employee_id" clearable placeholder="负责人：全部"><el-option v-for="item in options?.employees" :key="item.id" :label="item.display_name" :value="item.id" /></el-select>
        <el-select v-model="filters.sla_status" clearable placeholder="SLA：全部"><el-option label="正常" value="NORMAL" /><el-option label="即将到期" value="AT_RISK" /><el-option label="已超时" value="OVERDUE" /><el-option label="已结束" value="COMPLETED" /></el-select>
        <el-button type="primary" @click="applyFilters">查询</el-button><el-button @click="resetFilters">重置</el-button>
      </section>

      <section v-if="showAnalysis && !embedded" class="analysis-grid">
        <article><h2>客诉类型分布</h2><div v-if="stats?.by_type.length" class="bars"><p v-for="item in stats.by_type.slice(0, 5)" :key="item.complaint_type_item_id"><span>{{ item.complaint_type_item__display_name }}</span><i><b :style="{ width: `${Math.max(item.count / maxTypeCount * 100, 6)}%` }" /></i><strong>{{ item.count }}</strong></p></div><div v-else class="empty">暂无数据</div></article>
        <article><h2>SLA 处理状态</h2><div class="sla-grid"><p><span>正常处理中</span><strong>{{ stats?.sla.normal ?? '—' }}</strong></p><p class="risk"><span>24 小时内到期</span><strong>{{ stats?.sla.at_risk ?? '—' }}</strong></p><p class="overdue"><span>已超时</span><strong>{{ stats?.sla.overdue ?? '—' }}</strong></p><p class="done"><span>已结束</span><strong>{{ stats ? stats.closed + stats.cancelled : '—' }}</strong></p></div></article>
        <article><h2>责任协同概览</h2><div v-if="stats?.by_owner.length" class="owners"><p v-for="item in stats.by_owner.slice(0, 5)" :key="item.owner_employee_id"><span>{{ item.owner_employee__display_name }}</span><strong>{{ item.count }} 条</strong></p></div><div v-else class="empty">暂无数据</div></article>
      </section>

      <section class="table-card">
        <div class="table-toolbar"><span>共 {{ total }} 条，已选择 {{ selectedRows.length }} 条</span><div><el-dropdown><el-button :icon="Setting">列设置</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-for="(_, key) in visibleColumns" :key="key"><el-checkbox v-model="visibleColumns[key]">{{ ({ customer: '客户', order: '关联订单', type: '类型', severity: '等级', status: '状态', owner: '负责人', sla: 'SLA', updated: '最近更新' } as Record<string, string>)[key] }}</el-checkbox></el-dropdown-item></el-dropdown-menu></template></el-dropdown><el-button :icon="Download" @click="exportCurrentPage">导出当前页</el-button><el-button :icon="Refresh" :loading="loading" @click="refresh">刷新</el-button></div></div>
        <el-table v-loading="loading" :data="rows" row-key="id" empty-text="暂无符合条件的真实客诉" @selection-change="selectedRows = $event">
          <el-table-column v-if="embedded" type="selection" width="48" />
          <el-table-column label="客诉编号" min-width="150"><template #default="{ row }"><button class="code-link" @click="openDetail(row)">{{ row.complaint_code }}</button></template></el-table-column>
          <el-table-column v-if="visibleColumns.customer" label="客户" min-width="210" show-overflow-tooltip><template #default="{ row }">{{ row.customer.account_name }}</template></el-table-column>
          <el-table-column v-if="visibleColumns.order" label="关联订单" min-width="150"><template #default="{ row }">{{ row.source_order_reference || '—' }}</template></el-table-column>
          <el-table-column v-if="visibleColumns.type" label="类型" min-width="116"><template #default="{ row }">{{ row.complaint_type.display_name }}</template></el-table-column>
          <el-table-column v-if="visibleColumns.severity" label="等级" width="96"><template #default="{ row }"><span class="solid-tag" :class="`solid-tag--${severityClass(row.severity.item_code)}`">{{ row.severity.display_name }}</span></template></el-table-column>
          <el-table-column v-if="visibleColumns.status" label="状态" min-width="120"><template #default="{ row }"><span class="solid-tag" :class="`solid-tag--${statusClass(row)}`">{{ row.status_label }}</span></template></el-table-column>
          <el-table-column v-if="visibleColumns.owner" label="负责人" min-width="116"><template #default="{ row }">{{ row.owner.display_name }}</template></el-table-column>
          <el-table-column v-if="visibleColumns.sla" label="SLA" min-width="188"><template #default="{ row }"><span :class="{ overdue: row.sla_status === 'OVERDUE' }">{{ slaText(row) }}</span></template></el-table-column>
          <el-table-column v-if="visibleColumns.updated" label="最近更新" min-width="170"><template #default="{ row }">{{ complaintDate(row.updated_at) }}</template></el-table-column>
          <el-table-column label="操作" width="142" fixed="right"><template #default="{ row }"><el-button link @click="openDetail(row)">查看</el-button><el-dropdown v-if="canEdit || canProcess" trigger="click"><el-button link>更多</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="canEdit" @click="openDetail(row, 'edit')">编辑客诉信息</el-dropdown-item><el-dropdown-item v-if="canProcess && !['CLOSED', 'CANCELLED'].includes(row.status)" @click="openDetail(row, 'progress')">更新处理进展</el-dropdown-item></el-dropdown-menu></template></el-dropdown></template></el-table-column>
        </el-table>
        <el-pagination v-if="total" v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="PAGE_SIZES" :total="total" layout="total, sizes, prev, pager, next" class="pagination" @change="changePage" />
      </section>

      <ComplaintCreateDialog v-model="createVisible" :options="options" :complaint-types="complaintTypes" :severities="severities" :fixed-customer-id="embedded ? customerId : ''" :fixed-customer-name="customerName" @created="refresh" />
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.complaint-page { min-width: 0; min-height: calc(100vh - 112px); margin: 0; padding: 26px 30px 34px; color: #292624; background: token.$crm-color-page; font-family: token.$crm-font-body; }.complaint-page.embedded { min-height: 0; margin: 0; padding: 20px 26px 28px; }
.complaint-page:not(.embedded) { box-sizing: border-box; height: 100%; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.page-heading, .heading-actions, .filter-panel, .table-toolbar, .table-toolbar > div { display: flex; align-items: center; }.page-heading { min-height: 88px; justify-content: space-between; }.eyebrow { margin: 0 !important; color: #a04b34 !important; font-size: 11px !important; font-weight: 700; letter-spacing: 1.8px; }.page-heading h1 { margin: 2px 0 3px; font-family: token.$crm-font-display; font-size: 38px; font-weight: 600; line-height: 45px; }.page-heading p { margin: 0; color: #77716b; font-size: 14px; }.heading-actions { gap: 10px; }.heading-actions :deep(.el-button) { height: 42px; margin: 0; border-radius: 4px; font-size: 16px; }.heading-actions :deep(.el-button--primary), .filter-panel :deep(.el-button--primary) { border-color: #c7441d; background: #c7441d; }
.metric-strip { height: 88px; display: grid; grid-template-columns: repeat(4, 1fr); overflow: hidden; margin: 16px 0; border: 1px solid #ded9d1; border-radius: 5px; background: #fcfbf8; }.metric-strip article { position: relative; display: grid; grid-template-columns: auto 1fr; grid-template-rows: 26px 26px; align-content: center; padding: 0 28px; border-right: 1px solid #e5e0d8; }.metric-strip article:last-child { border-right: 0; }.metric-strip article::before { position: absolute; top: 20px; bottom: 20px; left: 0; width: 3px; content: ''; background: #3898ec; }.metric-strip .metric--danger::before { background: #b53333; }.metric-strip .metric--warning::before { background: #b8781e; }.metric-strip .metric--success::before { background: #4f7d4b; }.metric-strip span { grid-column: 1 / 3; color: #746f69; font-size: 13px; }.metric-strip strong { font-family: token.$crm-font-display; font-size: 27px; }.metric-strip small { align-self: end; margin: 0 0 2px 12px; color: #8a847e; font-size: 12px; }
.error { margin-bottom: 14px; }.filter-panel { gap: 10px; overflow-x: auto; margin-bottom: 14px; padding: 14px 16px; border: 1px solid #ded9d1; border-radius: 5px; background: #fcfbf8; }.filter-panel > :deep(.el-input) { width: 286px; min-width: 286px; }.filter-panel > :deep(.el-select) { width: 160px; min-width: 145px; }.filter-panel :deep(.el-input__wrapper), .filter-panel :deep(.el-select__wrapper) { min-height: 42px; border-radius: 4px; background: #fffefb; box-shadow: 0 0 0 1px #d8d3cc inset; }.filter-panel :deep(.el-button) { height: 42px; margin: 0; border-radius: 4px; font-size: 15px; }
.analysis-grid { display: grid; grid-template-columns: 1.2fr .9fr 1fr; gap: 14px; margin-bottom: 14px; }.analysis-grid > article { min-height: 226px; padding: 20px 22px; border: 1px solid #ded9d1; border-radius: 5px; background: #fffefb; }.analysis-grid h2 { margin: 0 0 18px; font-family: token.$crm-font-display; font-size: 20px; }.bars p { display: grid; grid-template-columns: 110px 1fr 38px; align-items: center; gap: 10px; margin: 14px 0; font-size: 13px; }.bars i { height: 9px; overflow: hidden; background: #ebe7df; }.bars b { height: 100%; display: block; background: #c7441d; }.bars strong { color: #8f3b24; text-align: right; }.sla-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }.sla-grid p { min-height: 58px; display: flex; align-items: center; justify-content: space-between; margin: 0; padding: 0 14px; color: #276e75; background: #e3eff0; font-size: 13px; }.sla-grid p.risk { color: #8c5c16; background: #f3ead8; }.sla-grid p.overdue { color: #9c2f2f; background: #f3dddd; }.sla-grid p.done { color: #416b3e; background: #e5eee2; }.sla-grid strong { font-size: 19px; }.owners p { display: flex; justify-content: space-between; margin: 0; padding: 11px 0; border-bottom: 1px solid #e8e3db; font-size: 14px; }.owners strong { color: #8f3b24; }.empty { min-height: 140px; display: grid; place-items: center; color: #918b84; }
.table-card { overflow: hidden; border: 1px solid #ded9d1; border-radius: 5px; background: #fffefb; }.complaint-page:not(.embedded) .table-card { min-height: 0; flex: 1 1 auto; display: flex; flex-direction: column; }.table-toolbar { height: 56px; justify-content: space-between; padding: 0 16px; color: #746f69; font-size: 14px; }.table-toolbar > div { gap: 10px; }.table-toolbar :deep(.el-button) { height: 36px; margin: 0; border-radius: 4px; font-size: 14px; }.table-card :deep(.el-table) { min-width: 1480px; flex: 1 1 auto; min-height: 0; height: 100%; --el-table-header-bg-color: #ebe7df; --el-table-border-color: #e4dfd7; --el-table-row-hover-bg-color: #f7f4ee; color: #413d39; font-size: 15px; }.table-card :deep(.el-table th.el-table__cell) { height: 48px; padding: 0; color: #514c47; font-size: 15px; }.table-card :deep(.el-table td.el-table__cell) { height: 57px; padding: 0; }.code-link { padding: 0; border: 0; color: #8f3b24; background: none; cursor: pointer; font-size: 15px; font-weight: 600; }.solid-tag { min-width: 62px; height: 28px; display: inline-flex; align-items: center; justify-content: center; padding: 0 9px; border-radius: 3px; color: #faf9f5; background: #5e5d59; font-size: 13px; }.solid-tag--danger { background: #b53333; }.solid-tag--warning { background: #b8781e; }.solid-tag--success { background: #4f7d4b; }.solid-tag--info { background: #3898ec; }.solid-tag--neutral { background: #5e5d59; }.overdue { color: #b53333; font-weight: 600; }.pagination { height: 58px; justify-content: flex-end; padding: 0 16px; border-top: 1px solid #e4dfd7; }.pagination :deep(.el-pagination__total) { margin-right: auto; }
.embedded .eyebrow, .embedded .analysis-grid { display: none; }.embedded-toolbar { min-height: 54px; display: flex; align-items: center; justify-content: space-between; color: #77716b; font-size: 13px; }.embedded-toolbar :deep(.el-button--primary) { height: 38px; border-color: #c7441d; border-radius: 4px; background: #c7441d; }.embedded .metric-strip { height: 72px; margin-top: 6px; }.embedded .metric-strip article { padding-inline: 18px; }
@media (max-width: 1450px) { .complaint-page { padding-inline: 22px; }.table-card { overflow-x: auto; }.analysis-grid { grid-template-columns: 1fr 1fr; }.analysis-grid > article:last-child { grid-column: 1 / 3; } }
@media (max-height: 800px) and (min-width: 769px) {
  .complaint-page:not(.embedded) .page-heading { height: 64px; min-height: 64px; }
  .complaint-page:not(.embedded) .metric-strip { height: 64px; min-height: 64px; flex: 0 0 64px; margin-block: 8px; }
  .complaint-page:not(.embedded) .filter-panel { height: 42px; min-height: 42px; flex: 0 0 42px; margin-bottom: 8px; }
  .complaint-page:not(.embedded) .analysis-grid { max-height: 150px; flex: 0 0 150px; overflow-y: auto; margin-bottom: 8px; }
  .complaint-page:not(.embedded) .table-card { min-height: 180px; flex: 1 1 180px; }
}
</style>
