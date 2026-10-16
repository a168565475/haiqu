<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ArrowDown, DocumentCopy, Operation, Plus, Refresh, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  cancelProductionTask,
  deleteProductionTask,
  exportProductionTasks,
  fetchProductionTask,
  fetchProductionTaskFilterOptions,
  fetchProductionTasks,
  fetchProductionTaskStats,
  finishProductionTask,
} from '@/api/productionTasks'
import { createProductionTaskSavedView, fetchProductionTaskSavedViews } from '@/api/savedViews'
import ProductionTaskScheduleDialog from '@/components/productionScheduling/ProductionTaskScheduleDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  ProductionDeliveryMethod,
  ProductionOrderSource,
  ProductionTask,
  ProductionTaskFilterOptions,
  ProductionTaskQuery,
  ProductionTaskStats,
  ProductionTaskStatus,
} from '@/types/productionTask'
import type { SavedView } from '@/types/savedView'

import { productLabels, productSpecifications, quantityWithUnits, localAmountTotal } from './productionTaskDisplay'

type StatusTabKey = 'all' | 'pending' | 'draft' | 'ready' | 'production' | 'completed' | 'paused' | 'cancelled'
type OptionalColumnKey = 'product' | 'quantity' | 'delivery' | 'salesperson' | 'followers' | 'localAmount' | 'status' | 'bomStatus' | 'purchaseStatus'
type LifecycleAction = 'cancel' | 'finish'

interface AdvancedFilters {
  contract_number: string
  product_id: string
  salesperson_id: string
  follower_id: string
  order_source: ProductionOrderSource | ''
  delivery_method: ProductionDeliveryMethod | ''
}

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const exportLoading = ref(false)
let latestRowsRequest = 0
let latestStatsRequest = 0
let latestOptionsRequest = 0
let latestSavedViewsRequest = 0
const optionsLoading = ref(false)
const statsLoading = ref(false)
const statsReady = ref(false)
const statsError = ref('')
const optionsError = ref('')
const rows = ref<ProductionTask[]>([])
const options = ref<ProductionTaskFilterOptions | null>(null)
const stats = ref<ProductionTaskStats>({ all: 0, draft: 0, pending_validation: 0, ready: 0, in_production: 0, completed: 0, paused: 0, cancelled: 0, split_delivery: 0 })
const savedViews = ref<SavedView[]>([])
const errorMessage = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const ordering = ref('-created_at')
const searchText = ref('')
const activeStatusTab = ref<StatusTabKey>('all')
const quantityPending = ref(false)
const dueSoon = ref(false)
const advancedVisible = ref(false)
const deliveryRange = ref<[string, string] | []>([])
const selectedRows = ref<ProductionTask[]>([])
const saveDialogVisible = ref(false)
const saveViewLoading = ref(false)
const savedViewName = ref('')
const lifecycleDialogVisible = ref(false)
const lifecycleLoading = ref(false)
const lifecycleAction = ref<LifecycleAction>('cancel')
const lifecycleTarget = ref<ProductionTask | null>(null)
const lifecycleReason = ref('')
const completionActualQuantity = ref('0')
const completionGoodQuantity = ref('0')
const completionBatches = ref<Array<{ batch_number: string; planned_quantity: string; actual_quantity: string; good_quantity: string; note: string }>>([])
const scheduleDialogVisible = ref(false)
const scheduleTarget = ref<ProductionTask | null>(null)


const advancedFilters = reactive<AdvancedFilters>({
  contract_number: '', product_id: '', salesperson_id: '', follower_id: '', order_source: '', delivery_method: '',
})

const optionalColumns: Array<{ key: OptionalColumnKey; label: string; width: number; align?: 'left' | 'center' }> = [
  { key: 'product', label: '产品信息', width: 178 },
  { key: 'quantity', label: '数量', width: 88 },
  { key: 'localAmount', label: '人民币金额合计', width: 105 },
  { key: 'delivery', label: '交期', width: 102 },
  { key: 'salesperson', label: '业务员', width: 78 },
  { key: 'followers', label: '跟单员', width: 78 },
  { key: 'status', label: '状态', width: 140, align: 'center' },
  { key: 'bomStatus', label: 'BOM状态', width: 120, align: 'center' },
  { key: 'purchaseStatus', label: '采购状态', width: 130, align: 'center' },
]
const columnOrder = ref<OptionalColumnKey[]>(optionalColumns.map((item) => item.key))
const visibleColumnKeys = ref<OptionalColumnKey[]>(optionalColumns.map((item) => item.key))

const canDelete = computed(() => authStore.hasPermission('production_tasks.delete_productiontask'))
const deletingId = ref('')
const hoveredRowElement = ref<HTMLElement>()
const hoveredProductDetails = ref('')
const rowTooltipVisible = ref(false)
function showRowProducts(row: ProductionTask, _column: unknown, cell: HTMLElement) {
  hoveredRowElement.value = cell.parentElement || cell
  hoveredProductDetails.value = productSpecifications(row.products)
  rowTooltipVisible.value = row.products.length > 0
}
const canEdit = computed(() => authStore.hasPermission('production_tasks.change_productiontask'))
const canCreate = computed(() => authStore.hasPermission('production_tasks.add_productiontask'))
const canConfirm = computed(() => authStore.hasPermission('production_tasks.confirm_productiontask'))
const canSchedule = computed(() => (
  authStore.hasPermission('production_scheduling.view_productionschedule')
  && authStore.hasPermission('production_scheduling.add_productionschedule')
))
const canSaveView = computed(() => authStore.hasPermission('preferences.view_savedview') && authStore.hasPermission('preferences.add_savedview'))
const canViewSavedViews = computed(() => authStore.hasPermission('preferences.view_savedview'))
const lifecycleTitle = computed(() => lifecycleAction.value === 'cancel' ? '取消订单' : '结束订单')
const lifecycleReasonLabel = computed(() => lifecycleAction.value === 'cancel' ? '取消原因' : '结束原因')
const lifecycleConfirmText = computed(() => lifecycleAction.value === 'cancel' ? '确认取消' : '确认结束')
const titleCount = computed(() => statsReady.value ? stats.value.all : total.value)
const advancedFilterCount = computed(() => [
  advancedFilters.contract_number, advancedFilters.product_id,
  advancedFilters.salesperson_id, advancedFilters.follower_id, advancedFilters.order_source,
  advancedFilters.delivery_method, deliveryRange.value.length ? 'range' : '',
].filter(Boolean).length)
const statusTabs = computed(() => [
  { key: 'all' as const, label: '全部', count: stats.value.all },
  { key: 'draft' as const, label: '草稿', count: stats.value.draft },
  { key: 'pending' as const, label: '待 PMC 确认', count: stats.value.pending_validation, warning: true },
  { key: 'ready' as const, label: '已接单', count: stats.value.ready },
  { key: 'production' as const, label: '生产中', count: stats.value.in_production },
  { key: 'completed' as const, label: '已完成', count: stats.value.completed },
])

function apiError(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (error.response.status === 403) return data.error?.message || data.detail || '当前账号没有执行此操作的权限。'
  return data.error?.message || data.detail || '生产任务单加载失败。'
}

function statusQuery(): Pick<ProductionTaskQuery, 'status' | 'delivery_method'> {
  if (activeStatusTab.value === 'pending') return { status: 'PENDING_VALIDATION' }
  if (activeStatusTab.value === 'draft') return { status: 'DRAFT' }
  if (activeStatusTab.value === 'ready') return { status: 'READY' }
  if (activeStatusTab.value === 'production') return { status: 'IN_PRODUCTION' }
  if (activeStatusTab.value === 'completed') return { status: 'COMPLETED' }
  if (activeStatusTab.value === 'paused') return { status: 'PAUSED' }
  if (activeStatusTab.value === 'cancelled') return { status: 'CANCELLED' }
  return {}
}

function buildQuery(): ProductionTaskQuery {
  const query: ProductionTaskQuery = {
    page: page.value, page_size: pageSize.value, ordering: ordering.value,
    search: searchText.value.trim() || undefined, ...statusQuery(),
  }
  if (advancedFilters.contract_number.trim()) query.contract_number = advancedFilters.contract_number.trim()
  if (advancedFilters.product_id) query.product_id = advancedFilters.product_id
  if (advancedFilters.salesperson_id) query.salesperson_id = advancedFilters.salesperson_id
  if (advancedFilters.follower_id) query.follower_id = advancedFilters.follower_id
  if (advancedFilters.order_source) query.order_source = advancedFilters.order_source
  if (advancedFilters.delivery_method) query.delivery_method = advancedFilters.delivery_method
  if (deliveryRange.value.length === 2) {
    query.delivery_from = deliveryRange.value[0]
    query.delivery_to = deliveryRange.value[1]
  }
  if (quantityPending.value) query.quantity_pending = true
  if (dueSoon.value) query.due_within_days = 30
  return query
}

function buildStatsQuery(): ProductionTaskQuery {
  const query = buildQuery()
  delete query.page
  delete query.page_size
  delete query.ordering
  delete query.status
  return query
}

async function loadRows(): Promise<boolean> {
  const requestId = ++latestRowsRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchProductionTasks(buildQuery())
    if (requestId !== latestRowsRequest) return true
    rows.value = result.data
    total.value = result.meta.total
    if (page.value > result.meta.total_pages && result.meta.total_pages > 0) {
      page.value = result.meta.total_pages
      return loadRows()
    }
    return true
  } catch (error) {
    if (requestId !== latestRowsRequest) return true
    rows.value = []
    total.value = 0
    errorMessage.value = apiError(error)
    return false
  } finally {
    if (requestId === latestRowsRequest) loading.value = false
  }
}

async function loadFilterOptions(): Promise<boolean> {
  const requestId = ++latestOptionsRequest
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const result = await fetchProductionTaskFilterOptions()
    if (requestId === latestOptionsRequest) options.value = result
    return true
  } catch (error) {
    if (requestId !== latestOptionsRequest) return true
    optionsError.value = apiError(error)
    return false
  } finally {
    if (requestId === latestOptionsRequest) optionsLoading.value = false
  }
}

async function loadStats(): Promise<boolean> {
  const requestId = ++latestStatsRequest
  statsLoading.value = true
  statsReady.value = false
  statsError.value = ''
  try {
    const result = await fetchProductionTaskStats(buildStatsQuery())
    if (requestId === latestStatsRequest) {
      stats.value = result
      statsReady.value = true
    }
    return true
  } catch (error) {
    if (requestId !== latestStatsRequest) return true
    statsError.value = apiError(error)
    return false
  } finally {
    if (requestId === latestStatsRequest) statsLoading.value = false
  }
}

async function loadSavedViews(): Promise<boolean> {
  const requestId = ++latestSavedViewsRequest
  try {
    const result = canViewSavedViews.value ? await fetchProductionTaskSavedViews() : []
    if (requestId === latestSavedViewsRequest) savedViews.value = result
    return true
  } catch (error) {
    if (requestId !== latestSavedViewsRequest) return true
    ElMessage.warning(apiError(error))
    return false
  }
}

async function loadSupportingData(): Promise<boolean> {
  const results = await Promise.all([loadFilterOptions(), loadStats(), loadSavedViews()])
  return results.every(Boolean)
}

function search() { page.value = 1; void Promise.all([loadRows(), loadStats()]) }
function applyStatusTab(key: StatusTabKey) { activeStatusTab.value = key; page.value = 1; void loadRows() }
function applyAdvancedFilters() { advancedVisible.value = false; search() }
function resetAdvancedFilters() {
  Object.assign(advancedFilters, { contract_number: '', product_id: '', salesperson_id: '', follower_id: '', order_source: '', delivery_method: '' })
  deliveryRange.value = []
}
async function refresh() {
  const results = await Promise.all([loadRows(), loadSupportingData()])
  if (results.every(Boolean)) ElMessage.success('生产任务单列表已刷新。')
  else ElMessage.warning('刷新未全部成功，请按页面提示重试。')
}

function statusClass(status: ProductionTaskStatus) {
  if (status === 'DRAFT' || status === 'PAUSED') return 'neutral'
  if (status === 'PENDING_VALIDATION') return 'warning'
  if (status === 'COMPLETED' || status === 'READY') return 'success'
  if (status === 'CANCELLED') return 'danger'
  if (status === 'IN_PRODUCTION') return 'info'
  return 'brand'
}
function progressStatusClass(status?: string) {
  if (!status || status === 'NOT_CREATED' || status === 'NOT_STARTED' || status.endsWith('_DRAFT')) return 'neutral'
  if (status === 'REQUEST_CANCELLED') return 'danger'
  if (status === 'VERIFIED' || status === 'ORDER_COMPLETED') return 'success'
  if (status === 'ORDER_PURCHASING') return 'info'
  return 'warning'
}
function openCreate() { void router.push({ name: 'production-task-create' }) }
function openTask(row: ProductionTask, edit = false) { void router.push({ name: edit ? 'production-task-edit' : 'production-task-detail', params: { taskId: row.id } }) }
function canChangeLifecycle(row: ProductionTask) { return canEdit.value && row.status !== 'CANCELLED' && row.status !== 'COMPLETED' }
function handleRowAction(command: string, row: ProductionTask) {
  if (command === 'delete') { void deleteTask(row); return }
  if (command === 'view') { openTask(row); return }
  if (command === 'edit') { openTask(row, true); return }
  if (command === 'confirm') { void openPmcConfirm(row); return }
  if (command === 'schedule') {
    scheduleTarget.value = row
    scheduleDialogVisible.value = true
    return
  }
  if ((command !== 'cancel' && command !== 'finish') || !canChangeLifecycle(row)) return
  if (command === 'finish' && row.sales_order_id) {
    void prepareLinkedFinish(row)
    return
  }
  lifecycleAction.value = command
  lifecycleTarget.value = row
  lifecycleReason.value = ''
  lifecycleDialogVisible.value = true
}
async function deleteTask(row: ProductionTask) {
  if (!canDelete.value || row.status !== 'CANCELLED' || deletingId.value) return
  deletingId.value = row.id
  try {
    const current = await fetchProductionTask(row.id)
    if (current.data.status !== 'CANCELLED') { ElMessage.warning('任务状态已变化，请刷新后重试。'); return }
    if (!current.etag) { ElMessage.error('未取得任务版本，请刷新后重试。'); return }
    await ElMessageBox.confirm(`确定删除任务单 ${row.task_number}？删除后不可恢复。存在 BOM、排产、采购等下游记录时将无法删除。`, '删除生产任务单', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
    await deleteProductionTask(row.id, current.etag)
    selectedRows.value = selectedRows.value.filter((item) => item.id !== row.id)
    ElMessage.success('生产任务单已删除。')
    await Promise.all([loadRows(), loadStats()])
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (error instanceof AxiosError && [409, 412, 428].includes(error.response?.status || 0)) ElMessage.error(`${apiError(error)} 请刷新列表后重试。`)
    else ElMessage.error(apiError(error))
  } finally { deletingId.value = '' }
}
async function prepareLinkedFinish(row: ProductionTask) {
  lifecycleLoading.value = true
  try {
    const current = await fetchProductionTask(row.id)
    lifecycleAction.value = 'finish'
    lifecycleTarget.value = current.data
    lifecycleReason.value = ''
    completionActualQuantity.value = current.data.total_quantity
    completionGoodQuantity.value = current.data.total_quantity
    completionBatches.value = (current.data.run_batches || []).filter((item) => item.status !== 'CANCELLED').map((item) => ({
      batch_number: item.batch_number,
      planned_quantity: item.planned_quantity,
      actual_quantity: item.actual_quantity === '0.0000' ? item.planned_quantity : item.actual_quantity,
      good_quantity: item.good_quantity === '0.0000' ? item.planned_quantity : item.good_quantity,
      note: item.note,
    }))
    lifecycleDialogVisible.value = true
  } catch (error) { ElMessage.error(apiError(error)) } finally { lifecycleLoading.value = false }
}
async function openPmcConfirm(row: ProductionTask) {
  if (row.status !== 'PENDING_VALIDATION' || !canConfirm.value) return
  await router.push({ name: 'production-task-detail', params: { taskId: row.id }, query: { pmc: 'confirm' } })
}

async function handleScheduleSaved() {
  await Promise.all([loadRows(), loadStats()])
}
async function confirmLifecycleAction() {
  const row = lifecycleTarget.value
  const reason = lifecycleReason.value.trim()
  if (!row || lifecycleLoading.value) return
  const linkedFinish = lifecycleAction.value === 'finish' && Boolean(row.sales_order_id)
  if (!reason && (!linkedFinish || Number(completionGoodQuantity.value) < Number(row.total_quantity))) {
    ElMessage.warning(linkedFinish ? '合格数量不足时必须填写异常完结原因（责任提示：PMC）。' : `请填写${lifecycleReasonLabel.value}。`)
    return
  }
  lifecycleLoading.value = true
  try {
    const current = await fetchProductionTask(row.id)
    if (lifecycleAction.value === 'cancel') await cancelProductionTask(row.id, reason, current.etag)
    else if (current.data.sales_order_id) {
      await finishProductionTask(row.id, reason, current.etag, {
        actual_quantity: completionActualQuantity.value,
        actual_good_quantity: completionGoodQuantity.value,
        run_batches: completionBatches.value.map((item) => ({ ...item, status: 'COMPLETED' as const })),
      })
    } else await finishProductionTask(row.id, reason, current.etag)
    lifecycleDialogVisible.value = false
    lifecycleTarget.value = null
    lifecycleReason.value = ''
    ElMessage.success(`${lifecycleTitle.value}成功。`)
    await Promise.all([loadRows(), loadStats()])
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    lifecycleLoading.value = false
  }
}
function moveColumn(index: number, direction: -1 | 1) {
  const target = index + direction
  if (target < 0 || target >= columnOrder.value.length) return
  const next = [...columnOrder.value]
  const [moved] = next.splice(index, 1)
  next.splice(target, 0, moved)
  columnOrder.value = next
}
function handleSortChange(event: { prop: string; order: 'ascending' | 'descending' | null }) {
  const supported: Record<string, string> = { task_number: 'task_number', delivery_date: 'delivery_date' }
  const field = supported[event.prop]
  ordering.value = event.order && field ? `${event.order === 'descending' ? '-' : ''}${field}` : '-created_at'
  search()
}

async function saveCurrentView() {
  const name = savedViewName.value.trim()
  if (!name) { ElMessage.warning('请输入视图名称。'); return }
  const filterDefinition = Object.fromEntries(Object.entries(buildQuery()).filter(([key, value]) => key !== 'page' && value !== '' && value !== undefined))
  saveViewLoading.value = true
  try {
    await createProductionTaskSavedView({
      module_code: 'PRODUCTION_TASK', view_name: name, filter_definition: filterDefinition,
      column_definition: ['task', ...columnOrder.value.filter((key) => visibleColumnKeys.value.includes(key)), 'actions'],
      sort_definition: [ordering.value],
    })
    savedViews.value = await fetchProductionTaskSavedViews()
    saveDialogVisible.value = false
    savedViewName.value = ''
    ElMessage.success('视图已保存。')
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    saveViewLoading.value = false
  }
}

function applySavedView(view: SavedView) {
  const definition = view.filter_definition
  searchText.value = typeof definition.search === 'string' ? definition.search : ''
  quantityPending.value = definition.quantity_pending === true
  dueSoon.value = definition.due_within_days === 30
  Object.assign(advancedFilters, {
    contract_number: typeof definition.contract_number === 'string' ? definition.contract_number : '',
    product_id: typeof definition.product_id === 'string' ? definition.product_id : '',
    salesperson_id: typeof definition.salesperson_id === 'string' ? definition.salesperson_id : '',
    follower_id: typeof definition.follower_id === 'string' ? definition.follower_id : '',
    order_source: typeof definition.order_source === 'string' ? definition.order_source : '',
    delivery_method: typeof definition.delivery_method === 'string' ? definition.delivery_method : '',
  })
  const from = typeof definition.delivery_from === 'string' ? definition.delivery_from : ''
  const to = typeof definition.delivery_to === 'string' ? definition.delivery_to : ''
  deliveryRange.value = from && to ? [from, to] : []
  const status = typeof definition.status === 'string' ? definition.status : ''
  activeStatusTab.value = status === 'PENDING_VALIDATION' ? 'pending'
    : status === 'DRAFT' ? 'draft'
      : status === 'READY' ? 'ready'
        : status === 'IN_PRODUCTION' ? 'production'
          : status === 'COMPLETED' ? 'completed'
            : status === 'PAUSED' ? 'paused'
              : status === 'CANCELLED' ? 'cancelled' : 'all'
  if (typeof definition.page_size === 'number') pageSize.value = definition.page_size
  if (view.sort_definition[0]) ordering.value = view.sort_definition[0]
  const savedOptional = view.column_definition.flatMap((key) => key === 'business' ? ['salesperson', 'followers'] : [key]).filter((key): key is OptionalColumnKey => optionalColumns.some((column) => column.key === key))
  if (savedOptional.length) {
    columnOrder.value = [...savedOptional, ...columnOrder.value.filter((key) => !savedOptional.includes(key))]
    visibleColumnKeys.value = [...savedOptional]
  }
  saveDialogVisible.value = false
  search()
}

async function exportList() {
  const selectedIds = selectedRows.value.map((row) => row.id)
  if (!selectedIds.length && !total.value) { ElMessage.warning('当前筛选没有可导出的生产任务单。'); return }
  exportLoading.value = true
  try {
    const result = await exportProductionTasks(buildQuery(), selectedIds)
    const url = URL.createObjectURL(result.blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `生产任务单_${new Date().toISOString().slice(0, 10)}.csv`
    anchor.click()
    URL.revokeObjectURL(url)
    const count = result.count ?? (selectedIds.length || total.value)
    ElMessage.success(selectedIds.length ? `已导出选中的 ${count} 条生产任务单。` : `已导出当前筛选的全部 ${count} 条生产任务单。`)
  } catch (error) {
    let message = apiError(error)
    if (error instanceof AxiosError && error.response?.data instanceof Blob) {
      try {
        const payload = JSON.parse(await error.response.data.text()) as { error?: { message?: string }; detail?: string }
        message = payload.error?.message || payload.detail || message
      } catch { /* 非 JSON 下载错误沿用通用提示。 */ }
    }
    ElMessage.error(message)
  } finally {
    exportLoading.value = false
  }
}

onMounted(() => { void loadRows(); void loadSupportingData() })
onBeforeUnmount(() => {
  ++latestRowsRequest
  ++latestStatsRequest
  ++latestOptionsRequest
  ++latestSavedViewsRequest
})
</script>

<template>
  <section class="production-list-page" aria-label="生产任务单列表">
    <header class="page-heading">
      <div class="page-heading__title"><h1>生产任务单</h1><span>{{ titleCount }} 条</span></div>
      <div class="page-heading__actions">
        <ElButton :icon="Upload" :loading="exportLoading" :disabled="!total" @click="exportList">导出</ElButton>
        <ElButton v-if="canCreate" type="primary" :icon="Plus" @click="openCreate">新建生产任务单</ElButton>
      </div>
    </header>

    <nav class="status-tabs" aria-label="任务单状态" v-loading="statsLoading">
      <button v-for="tab in statusTabs" :key="tab.key" type="button" class="status-tab" :class="{ 'is-active': activeStatusTab === tab.key }" :aria-pressed="activeStatusTab === tab.key" @click="applyStatusTab(tab.key)">
        <span v-if="tab.warning" class="status-tab__dot" aria-hidden="true" /><span>{{ tab.label }}</span><strong>{{ statsReady ? tab.count : '—' }}</strong>
      </button>
    </nav>
    <ElAlert v-if="statsError" type="warning" :title="`统计加载失败：${statsError}`" :closable="false"><ElButton size="small" @click="loadStats">重试统计</ElButton></ElAlert>
    <ElAlert v-if="optionsError" type="warning" :title="`筛选选项加载失败：${optionsError}`" :closable="false"><ElButton size="small" @click="loadFilterOptions">重试选项</ElButton></ElAlert>

    <section class="list-toolbar" aria-label="列表筛选与视图设置">
      <div class="list-toolbar__filters">
        <ElInput v-model="searchText" clearable :prefix-icon="Search" placeholder="搜索任务单号、订单号或产品" @keyup.enter="search" @clear="search" />
        <ElSelect v-model="activeStatusTab" aria-label="状态筛选" @change="() => applyStatusTab(activeStatusTab)">
          <ElOption v-for="tab in statusTabs" :key="tab.key" :label="`状态：${tab.label}`" :value="tab.key" />
          <ElOption label="状态：已暂停" value="paused" />
          <ElOption label="状态：已取消" value="cancelled" />
        </ElSelect>
        <ElSelect v-model="advancedFilters.salesperson_id" :loading="optionsLoading" clearable placeholder="业务员：全部" @change="search">
          <ElOption v-for="item in options?.employees || []" :key="item.id" :label="item.display_name" :value="item.id" />
        </ElSelect>
        <ElSelect v-model="dueSoon" aria-label="交期筛选" @change="search">
          <ElOption label="交期：全部" :value="false" />
          <ElOption label="交期：近 30 天" :value="true" />
        </ElSelect>
        <ElPopover v-model:visible="advancedVisible" placement="bottom-start" :width="760" trigger="click" popper-class="production-filter-popper">
          <template #reference><ElButton :class="{ 'is-filter-active': advancedFilterCount > 0 }">更多筛选<template v-if="advancedFilterCount">（{{ advancedFilterCount }}）</template><ElIcon><ArrowDown /></ElIcon></ElButton></template>
          <section v-if="advancedVisible" class="advanced-filter-panel" v-loading="optionsLoading">
            <header><strong>更多筛选</strong><span>按业务字段组合筛选生产任务单</span></header>
            <div class="advanced-filter-grid">
              <label><span>合同编号</span><ElInput v-model="advancedFilters.contract_number" clearable placeholder="输入合同编号" /></label>
              <label><span>产品</span><ElSelect v-model="advancedFilters.product_id" filterable clearable placeholder="全部产品"><ElOption v-for="item in options?.products || []" :key="item.id" :label="`${item.product_code} · ${item.item_number} · ${item.product_name}`" :value="item.id" /></ElSelect></label>
              <label><span>业务员</span><ElSelect v-model="advancedFilters.salesperson_id" filterable clearable placeholder="全部业务员"><ElOption v-for="item in options?.employees || []" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></label>
              <label><span>跟单员</span><ElSelect v-model="advancedFilters.follower_id" filterable clearable placeholder="全部跟单员"><ElOption v-for="item in options?.employees || []" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></label>
              <label class="delivery-range"><span>交期范围</span><ElDatePicker v-model="deliveryRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" /></label>
              <label><span>订单来源</span><ElSelect v-model="advancedFilters.order_source" clearable placeholder="全部来源"><ElOption v-for="item in options?.order_sources || []" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></label>
              <label><span>交货方式</span><ElSelect v-model="advancedFilters.delivery_method" clearable placeholder="全部方式"><ElOption v-for="item in options?.delivery_methods || []" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></label>
              <label><span>数量校验</span><ElCheckbox v-model="quantityPending">仅看数量待确认</ElCheckbox></label>
            </div>
            <footer><ElButton @click="resetAdvancedFilters">重置</ElButton><ElButton type="primary" @click="applyAdvancedFilters">应用筛选</ElButton></footer>
          </section>
        </ElPopover>
      </div>

      <div class="list-toolbar__views">
        <span class="selected-count">已选择 {{ selectedRows.length }} 项</span>
        <ElButton :icon="DocumentCopy" :disabled="!canSaveView" @click="saveDialogVisible = true">保存视图</ElButton>
        <ElPopover placement="bottom-end" :width="286" trigger="click" popper-class="production-columns-popper">
          <template #reference><ElButton :icon="Operation">列设置</ElButton></template>
          <section class="column-settings">
            <header><strong>列设置</strong><span>勾选显示，箭头调整顺序</span></header>
            <div class="column-setting-row is-locked"><span>任务单</span><small>锁定</small></div>
            <div v-for="(key, index) in columnOrder" :key="key" class="column-setting-row">
              <ElCheckbox v-model="visibleColumnKeys" :value="key">{{ optionalColumns.find((item) => item.key === key)?.label }}</ElCheckbox>
              <span class="column-setting-row__actions"><button type="button" :disabled="index === 0" @click="moveColumn(index, -1)">↑</button><button type="button" :disabled="index === columnOrder.length - 1" @click="moveColumn(index, 1)">↓</button></span>
            </div>
            <div class="column-setting-row is-locked"><span>操作</span><small>锁定</small></div>
          </section>
        </ElPopover>
        <ElButton :icon="Refresh" :loading="loading" @click="refresh">刷新</ElButton>
      </div>
    </section>

    <section class="table-card">
      <ElAlert v-if="errorMessage" class="list-error" type="error" :title="errorMessage" show-icon :closable="false"><ElButton size="small" @click="refresh">重试</ElButton></ElAlert>
      <ElTable v-else v-loading="loading" :data="rows" row-key="id" empty-text="暂无生产任务单" @cell-mouse-enter="showRowProducts" @cell-mouse-leave="rowTooltipVisible = false" @selection-change="selectedRows = $event" @sort-change="handleSortChange">
        <ElTableColumn type="selection" width="40" align="center" />
        <ElTableColumn
          prop="task_number"
          label="任务编号"
          min-width="110"
          sortable="custom"
        ><template #default="{ row }"><button class="link-button" type="button" @click="openTask(row)">{{ row.task_number }}</button></template></ElTableColumn>
        <ElTableColumn label="销售订单" min-width="128" show-overflow-tooltip><template #default="{ row }">{{ row.source_sales_order_number || '手动创建' }}</template></ElTableColumn>
        <template v-for="key in columnOrder" :key="key">
          <ElTableColumn v-if="key === 'product' && visibleColumnKeys.includes(key)" label="产品" min-width="178"><template #default="{ row }"><ElTooltip trigger="focus" :content="productSpecifications(row.products)" placement="top" popper-class="production-product-tooltip"><div class="product-summary" tabindex="0"><div v-for="(label, index) in productLabels(row.products)" :key="index">{{ label }}</div><span v-if="!row.products.length">未添加产品</span></div></ElTooltip></template></ElTableColumn>
          <ElTableColumn v-else-if="key === 'quantity' && visibleColumnKeys.includes(key)" label="数量" min-width="88" show-overflow-tooltip align="right"><template #default="{ row }">{{ quantityWithUnits(row.products) }}</template></ElTableColumn>
          <ElTableColumn v-else-if="key === 'delivery' && visibleColumnKeys.includes(key)" prop="delivery_date" label="交期" min-width="102" sortable="custom"><template #default="{ row }">{{ row.delivery_date || '—' }}</template></ElTableColumn>
          <ElTableColumn v-else-if="key === 'localAmount' && visibleColumnKeys.includes(key)" label="人民币金额合计" min-width="125" show-overflow-tooltip align="right"><template #default="{ row }">¥ {{ localAmountTotal(row.products) }}</template></ElTableColumn>
          <ElTableColumn v-else-if="key === 'salesperson' && visibleColumnKeys.includes(key)" label="业务员" min-width="78" show-overflow-tooltip><template #default="{ row }">{{ row.salesperson.display_name }}</template></ElTableColumn>
          <ElTableColumn v-else-if="key === 'followers' && visibleColumnKeys.includes(key)" label="跟单员" min-width="78" show-overflow-tooltip><template #default="{ row }">{{ row.followers.map((item: { display_name: string }) => item.display_name).join('、') || '待选择' }}</template></ElTableColumn>
          <ElTableColumn v-else-if="key === 'status' && visibleColumnKeys.includes(key)" label="状态" width="110" align="center"><template #default="{ row }"><ElTag class="status-tag" :class="`status-tag--${statusClass(row.status)}`" effect="dark">{{ row.status_display }}</ElTag></template></ElTableColumn>
          <ElTableColumn v-else-if="key === 'bomStatus' && visibleColumnKeys.includes(key)" label="BOM状态" width="120" align="center"><template #default="{ row }"><ElTag class="status-tag progress-status-tag" :class="`status-tag--${progressStatusClass(row.bom_status)}`" effect="dark">{{ row.bom_status_display || '未建立' }}</ElTag></template></ElTableColumn>
          <ElTableColumn v-else-if="key === 'purchaseStatus' && visibleColumnKeys.includes(key)" label="采购状态" width="130" align="center"><template #default="{ row }"><ElTag class="status-tag progress-status-tag" :class="`status-tag--${progressStatusClass(row.purchase_status)}`" effect="dark">{{ row.purchase_status_display || '未发起' }}</ElTag></template></ElTableColumn>
        </template>
        <ElTableColumn label="操作" width="80" align="center" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <ElDropdown :persistent="false" trigger="click" placement="bottom-end" @command="handleRowAction($event, row)">
                <button class="row-action-trigger" type="button" :aria-label="`打开生产任务 ${row.task_number} 操作菜单`">
                  <span class="row-action-dots" aria-hidden="true"><i /><i /><i /></span>
                </button>
                <template #dropdown>
                  <ElDropdownMenu>
                    <ElDropdownItem command="view">查看</ElDropdownItem>
                    <ElDropdownItem v-if="canEdit && row.status !== 'CANCELLED' && row.status !== 'COMPLETED'" command="edit">编辑</ElDropdownItem>
                    <ElDropdownItem v-if="row.status === 'PENDING_VALIDATION' && canConfirm" command="confirm">PMC 确认</ElDropdownItem>
                    <ElDropdownItem v-if="row.status === 'READY' && canSchedule" command="schedule">计划排产</ElDropdownItem>
                    <ElDropdownItem v-if="canChangeLifecycle(row) && row.status === 'IN_PRODUCTION'" command="finish">完结生产</ElDropdownItem>
                    <ElDropdownItem v-if="canChangeLifecycle(row)" command="cancel" class="danger-menu-item" divided>取消订单</ElDropdownItem>
                    <ElDropdownItem v-if="canDelete" command="delete" :disabled="row.status !== 'CANCELLED' || !!deletingId" class="danger-menu-item">删除</ElDropdownItem>
                  </ElDropdownMenu>
                </template>
              </ElDropdown>
            </div>
          </template>
        </ElTableColumn>
      </ElTable>
      <ElTooltip virtual-triggering :virtual-ref="hoveredRowElement" :visible="rowTooltipVisible" :content="hoveredProductDetails" popper-class="production-product-tooltip" placement="top" />
      <footer class="table-footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="sizes, prev, pager, next" @current-change="loadRows" @size-change="search" /></footer>
    </section>

    <ElDialog v-model="saveDialogVisible" title="保存当前视图" width="440px" draggable>
      <ElForm label-position="top"><ElFormItem label="视图名称" required><ElInput v-model="savedViewName" maxlength="50" show-word-limit placeholder="例如：本月待校验任务" /></ElFormItem></ElForm>
      <section v-if="savedViews.length" class="saved-view-list"><span>已有视图</span><ElButton v-for="view in savedViews" :key="view.id" text type="primary" @click="applySavedView(view)">{{ view.view_name }}</ElButton></section>
      <template #footer><ElButton @click="saveDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="saveViewLoading" @click="saveCurrentView">保存</ElButton></template>
    </ElDialog>



    <ProductionTaskScheduleDialog v-model="scheduleDialogVisible" :task="scheduleTarget" @saved="handleScheduleSaved" />

    <ElDialog v-model="lifecycleDialogVisible" :title="lifecycleTitle" width="480px" :close-on-click-modal="!lifecycleLoading" :close-on-press-escape="!lifecycleLoading">
      <div class="lifecycle-dialog__summary">任务单：<strong>{{ lifecycleTarget?.task_number }}</strong></div>
      <ElForm label-position="top" @submit.prevent>
        <template v-if="lifecycleAction === 'finish' && lifecycleTarget?.sales_order_id">
          <div class="finish-quantities"><ElFormItem label="实际生产数量"><ElInput v-model="completionActualQuantity" /></ElFormItem><ElFormItem label="合格数量"><ElInput v-model="completionGoodQuantity" /></ElFormItem></div>
          <ElTable :data="completionBatches" size="small" border><ElTableColumn prop="batch_number" label="生产批次" /><ElTableColumn label="实际数量"><template #default="{ row }"><ElInput v-model="row.actual_quantity" /></template></ElTableColumn><ElTableColumn label="合格数量"><template #default="{ row }"><ElInput v-model="row.good_quantity" /></template></ElTableColumn></ElTable>
        </template>
        <ElFormItem :label="lifecycleAction === 'finish' && lifecycleTarget?.sales_order_id ? '异常完结原因（正常足量可不填）' : lifecycleReasonLabel" :required="!(lifecycleAction === 'finish' && lifecycleTarget?.sales_order_id)">
          <ElInput v-model="lifecycleReason" type="textarea" :rows="3" maxlength="500" show-word-limit :placeholder="lifecycleAction === 'finish' && lifecycleTarget?.sales_order_id ? '短交或提前关闭时必须填写' : `请填写${lifecycleReasonLabel}`" />
        </ElFormItem>
      </ElForm>
      <template #footer><ElButton :disabled="lifecycleLoading" @click="lifecycleDialogVisible = false">暂不操作</ElButton><ElButton :type="lifecycleAction === 'cancel' ? 'danger' : 'primary'" :loading="lifecycleLoading" @click="confirmLifecycleAction">{{ lifecycleConfirmText }}</ElButton></template>
    </ElDialog>
  </section>
</template>

<style scoped lang="scss">
.production-list-page { box-sizing: border-box; min-width: 0; height: 100%; min-height: 0; display: flex; flex-direction: column; padding: 0; color: #1f1d18; background: var(--erp-page-background); --el-color-primary: #c84e28; }
.page-heading, .page-heading__title, .page-heading__actions, .status-tabs, .status-tab, .list-toolbar, .list-toolbar__filters, .list-toolbar__views, .table-footer, .row-actions, .saved-view-list { display: flex; align-items: center; }
.page-heading { height: 46px; flex: none; justify-content: space-between; }
.page-heading__title { gap: 14px; }
.page-heading h1 { margin: 0; font-family: 'Noto Serif SC', serif; font-size: 34px; font-weight: 700; line-height: 46px; }
.page-heading__title > span { color: #6f6a61; font-size: 13px; }
.page-heading__actions { gap: 12px; }
.page-heading__actions :deep(.el-button) { height: 32px; margin: 0; border-radius: 5px; }
.page-heading__actions :deep(.el-button--primary) { min-width: 174px; border-color: #c84e28; background: #c84e28; }
.status-tabs { height: 53px; flex: none; margin-top: 4px; border: 1px solid #e3dfd7; border-radius: 5px; background: #efebe3; }
.status-tab { position: relative; min-width: 142px; height: 53px; justify-content: center; gap: 7px; padding: 0 18px; border: 0; color: #6f6a61; background: transparent; font: inherit; font-size: 13px; cursor: pointer; }
.status-tab strong { font-size: 12px; font-weight: 500; }
.status-tab::after { position: absolute; right: 0; bottom: 0; left: 0; height: 3px; background: transparent; content: ''; }
.status-tab:hover, .status-tab.is-active { color: #c84e28; }
.status-tab.is-active::after { background: #c84e28; }
.status-tab__dot { width: 8px; height: 8px; border-radius: 50%; background: #e6a23c; }
.production-list-page .list-toolbar { height: auto !important; min-height: 32px; flex: none; flex-wrap: wrap; justify-content: space-between; gap: 10px 20px; margin-top: 17px; }
.list-toolbar__filters, .list-toolbar__views { gap: 10px; min-width: 0; }
.list-toolbar__filters { flex-wrap: wrap; }
.list-toolbar__filters :deep(.el-input) { width: 410px; }
.list-toolbar__filters :deep(.el-select) { width: 142px; }
.list-toolbar :deep(.el-input__wrapper), .list-toolbar :deep(.el-select__wrapper), .list-toolbar :deep(.el-button) { min-height: 32px; border-radius: 5px; }
.list-toolbar :deep(.el-button) { margin: 0; padding: 0 13px; }
.list-toolbar__views { margin-left: auto; }
.selected-count { margin-right: 6px; color: #6f6a61; font-size: 12px; }
.product-summary { padding: 0; line-height: 20px; }
.product-summary > div { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.product-summary:focus-visible { outline: 2px solid #3898ec; outline-offset: 2px; }
.table-card { min-height: 0; flex: 1; display: flex; flex-direction: column; margin-top: 22px; overflow: hidden; border: 1px solid #ddd6c9; border-radius: 5px; background: #fdfcf9; }
.table-card :deep(.el-table) { min-height: 0; flex: 1; color: #1f1d18; --el-table-border-color: #ddd6c9; }
.table-card :deep(.el-table__inner-wrapper::before) { display: none; }
.table-card :deep(.el-table__body tbody tr:last-child > td) { border-bottom: 0; }
.table-card :deep(.el-table__header-wrapper th) { height: 44px; padding: 0; color: #6f6a61; background: #f0eadf; font-size: 11px; font-weight: 500; }
.production-list-page .table-card :deep(.el-table__body tr), .production-list-page .table-card :deep(.el-table__body td.el-table__cell) { height: 34px !important; font-size: 12px; }
.table-card :deep(.el-table__cell) { padding: 0; border-right: 0; }
.table-card :deep(.el-table .cell) { padding: 0 16px; }
.table-card :deep(.el-table__row:hover > td) { background: #fff6ea; }
.table-card :deep(.status-tag) { min-width: 56px; height: 24px; justify-content: center; padding: 0 8px; border: 0; border-radius: 999px; color: #faf9f5; font-size: 12px; font-weight: 500; line-height: 18px; }
.table-card :deep(.status-tag--brand) { background: #c96442; }
.table-card :deep(.status-tag--info) { background: #3898ec; }
.table-card :deep(.status-tag--success) { background: #4f7d4b; }
.table-card :deep(.status-tag--warning) { background: #b8781e; }
.table-card :deep(.status-tag--danger) { background: #b53333; }
.table-card :deep(.status-tag--neutral) { background: #5e5d59; }
.link-button { max-width: 100%; overflow: hidden; padding: 0; border: 0; color: #1f1d18; background: transparent; font: inherit; font-size: 12px; font-weight: 500; text-align: left; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.link-button:hover { text-decoration: underline; }
.row-actions { justify-content: center; }
.row-action-trigger { display: grid; width: 32px; height: 32px; place-items: center; padding: 0; border: 0; border-radius: 5px; color: #1f1d18; background: transparent; cursor: pointer; }
.row-action-trigger:hover { background: #efebe3; }
.row-action-trigger:focus-visible { outline: 2px solid #3898ec; outline-offset: 2px; }
.row-action-dots { display: inline-flex; align-items: center; gap: 3px; }
.row-action-dots i { width: 3px; height: 3px; border-radius: 50%; background: currentColor; }
.table-footer { height: 52px; flex: none; justify-content: space-between; padding: 0 16px; border-top: 1px solid #ddd6c9; color: #6f6a61; font-size: 12px; }
.table-footer :deep(.el-pagination) { --el-pagination-button-bg-color: #fdfcf9; }
.table-footer :deep(.is-active) { color: #c84e28; background: #fdfcf9; border: 1px solid #c84e28; }
.list-error { margin: 16px; }
.saved-view-list { flex-wrap: wrap; gap: 4px; margin-top: 8px; padding-top: 12px; border-top: 1px solid #e4e4e7; }
.saved-view-list > span { margin-right: 6px; color: #71717a; font-size: 13px; }
.lifecycle-dialog__summary { margin-bottom: 18px; color: #52525b; font-size: 14px; }
.lifecycle-dialog__summary strong { color: #18181b; }
.finish-quantities { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.pmc-confirm-note { margin: 0 0 18px; padding: 10px 12px; color: #6f6a61; background: #f6f3ec; font-size: 13px; line-height: 20px; }
.pmc-confirm-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.pmc-confirm-grid label { min-width: 0; display: flex; flex-direction: column; gap: 7px; color: #4d4c48; font-size: 13px; }
.pmc-confirm-grid :deep(.el-date-editor) { width: 100%; height: 32px; }
</style>

<style lang="scss">
.production-product-tooltip { white-space: pre-line; max-width: min(560px, calc(100vw - 32px)); }
.production-filter-popper, .production-columns-popper { padding: 0 !important; border-radius: 10px !important; }
.advanced-filter-panel { padding: 18px; }
.advanced-filter-panel header, .column-settings header { display: flex; flex-direction: column; gap: 3px; margin-bottom: 16px; }
.advanced-filter-panel header strong, .column-settings header strong { color: #18181b; font-size: 16px; }
.advanced-filter-panel header span, .column-settings header span { color: #71717a; font-size: 12px; }
.advanced-filter-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px 12px; }
.advanced-filter-grid label { min-width: 0; display: flex; flex-direction: column; gap: 6px; color: #3f3f46; font-size: 12px; }
.advanced-filter-grid .delivery-range { grid-column: span 2; }
.advanced-filter-grid .el-input, .advanced-filter-grid .el-select, .advanced-filter-grid .el-date-editor { width: 100%; }
.advanced-filter-panel footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; padding-top: 14px; border-top: 1px solid #e4e4e7; }
.column-settings { padding: 16px; }
.column-setting-row { height: 38px; display: flex; align-items: center; justify-content: space-between; border-top: 1px solid #f0f0f2; color: #3f3f46; font-size: 13px; }
.column-setting-row.is-locked { padding: 0 2px; color: #18181b; font-weight: 600; }
.column-setting-row.is-locked small { color: #a1a1aa; font-weight: 400; }
.column-setting-row__actions { display: flex; gap: 3px; }
.column-setting-row__actions button { width: 24px; height: 24px; border: 0; border-radius: 5px; color: #52525b; background: #f4f4f5; cursor: pointer; }
.column-setting-row__actions button:disabled { color: #d4d4d8; cursor: not-allowed; }
.danger-menu-item { color: #f56c6c !important; }
</style>
