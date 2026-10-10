<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Plus, Refresh, Setting, Sort } from '@element-plus/icons-vue'

import TaskBulkCompleteDialog from '@/components/tasks/TaskBulkCompleteDialog.vue'
import TaskBulkReassignDialog from '@/components/tasks/TaskBulkReassignDialog.vue'
import TaskCreateDialog from '@/components/tasks/TaskCreateDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { deleteTask, fetchTask, fetchTaskMetrics, fetchTaskOptions, fetchTasks } from '@/api/tasks'
import { createSavedView, fetchSavedViews } from '@/api/savedViews'
import { useAuthStore } from '@/stores/auth'
import { formatTaskDate, taskRequestMessage } from '@/utils/taskFeedback'
import type { SavedView } from '@/types/savedView'
import type { TaskFilters, TaskMetrics, TaskOptions, TaskScope, TaskSummary } from '@/types/task'

const props = withDefaults(defineProps<{
  embedded?: boolean
  customerId?: string
  customerName?: string
  defaultScope?: TaskScope
  defaultAssigneeId?: string
}>(), {
  embedded: false,
  customerId: '',
  customerName: '',
  defaultScope: 'ME',
  defaultAssigneeId: '',
})

const PAGE_SIZES = [20, 50, 100]
const storedSize = Number(localStorage.getItem('haiqu.tasks.page-size'))
const initialPageSize = PAGE_SIZES.includes(storedSize) ? storedSize : 50
const defaultColumns = { source: true, origin: true, creator: false }
const sortOptions = [
  { value: 'due_at', label: '截止时间升序' },
  { value: '-due_at', label: '截止时间降序' },
  { value: '-created_at', label: '最新创建' },
  { value: 'created_at', label: '最早创建' },
]

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const metricsLoading = ref(false)
const errorMessage = ref('')
const rows = ref<TaskSummary[]>([])
const total = ref(0)
const metrics = ref<TaskMetrics | null>(null)
const options = ref<TaskOptions | null>(null)
const selectedRows = ref<TaskSummary[]>([])
const savedViews = ref<SavedView[]>([])
const savedViewId = ref('')
const createVisible = ref(false)
const saveViewVisible = ref(false)
const savedViewName = ref('')
const savingView = ref(false)
const batchDialog = ref<'complete' | 'reassign' | null>(null)
const columns = reactive<Record<keyof typeof defaultColumns, boolean>>({ ...defaultColumns, ...readColumns() })
const filters = reactive<TaskFilters>({
  scope: props.defaultScope,
  q: '',
  assignee_employee_id: '',
  task_type: '',
  status: '',
  priority: '',
  due_window: '',
  source_type: '',
  customer_id: props.customerId,
  ordering: 'due_at',
  page: 1,
  page_size: initialPageSize,
})
let listRequestId = 0
let metricsRequestId = 0
let optionsRequestId = 0

const canCreate = computed(() => authStore.hasPermission('workflow.add_businesstask'))
const canBulkChange = computed(() => authStore.hasPermission('workflow.bulk_change_businesstask'))
const canBulkComplete = computed(() => canBulkChange.value && authStore.moduleCan('access_control.complete_businesstask', 'workflow.bulk_change_businesstask'))
const canBulkReassign = computed(() => canBulkChange.value && authStore.moduleCan('workflow.reassign_businesstask', 'workflow.bulk_change_businesstask'))
const canDelete = computed(() => authStore.hasPermission('workflow.delete_businesstask'))
const canReadViews = computed(() => authStore.hasPermission('preferences.view_savedview'))
const canSaveView = computed(() => authStore.hasPermission('preferences.add_savedview'))
const scopeOptions = computed(() => options.value?.scopes || [])
const cards = computed(() => [
  { label: '全部待办', value: metrics.value?.open_count ?? '—', hint: '', tone: 'neutral' },
  { label: '今日到期', value: metrics.value?.due_today_count ?? '—', hint: '', tone: 'danger' },
  { label: '已逾期', value: metrics.value?.overdue_count ?? '—', hint: '', tone: 'danger' },
  { label: '未来 7 天', value: metrics.value?.next_7_days_count ?? '—', hint: '', tone: 'neutral' },
  { label: '本月完成', value: metrics.value?.month_completed_count ?? '—', hint: metrics.value?.on_time_rate == null ? '按时率 —' : `按时率 ${metrics.value.on_time_rate}%`, tone: 'success' },
])

function readColumns() {
  try {
    const value = JSON.parse(localStorage.getItem('haiqu.tasks.columns.v1') || '{}')
    return value && typeof value === 'object' ? value : {}
  } catch {
    return {}
  }
}

function persistColumns() {
  localStorage.setItem('haiqu.tasks.columns.v1', JSON.stringify(columns))
}

function statusLabel(row: TaskSummary) {
  const labels: Record<string, string> = { BLOCKED: '阻塞', OVERDUE: '已逾期', WAITING_CUSTOMER: '待反馈' }
  return labels[row.display_status] || row.status_display
}

function statusClass(row: TaskSummary) {
  if (['OVERDUE', 'BLOCKED'].includes(row.display_status)) return 'danger'
  if (row.display_status === 'WAITING_CUSTOMER') return 'warning'
  if (row.status === 'COMPLETED') return 'success'
  if (row.status === 'CANCELLED') return 'neutral'
  return 'info'
}

function priorityLabel(row: TaskSummary) {
  return row.priority === 'NORMAL' ? '中' : row.priority_display
}

async function loadTasks() {
  const requestId = ++listRequestId
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchTasks(filters)
    if (requestId !== listRequestId) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (requestId !== listRequestId) return
    rows.value = []
    total.value = 0
    errorMessage.value = taskRequestMessage(error)
  } finally {
    if (requestId === listRequestId) loading.value = false
  }
}

async function loadMetrics() {
  const requestId = ++metricsRequestId
  metricsLoading.value = true
  try {
    const result = await fetchTaskMetrics(filters.scope)
    if (requestId === metricsRequestId) metrics.value = result
  } catch (error) {
    if (requestId === metricsRequestId) errorMessage.value = taskRequestMessage(error)
  } finally {
    if (requestId === metricsRequestId) metricsLoading.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadTasks(), loadMetrics()])
}

async function loadOptions(scope: TaskScope) {
  const requestId = ++optionsRequestId
  try {
    const result = await fetchTaskOptions(scope)
    if (requestId === optionsRequestId) options.value = result
  } catch (error) {
    if (requestId === optionsRequestId) errorMessage.value = taskRequestMessage(error)
  }
}

async function changeScopeFromFilter(scope: TaskScope) {
  filters.scope = scope
  filters.page = 1
  selectedRows.value = []
  await Promise.all([loadOptions(scope), refreshAll()])
}

async function applyFilters() {
  filters.page = 1
  selectedRows.value = []
  await loadTasks()
}

async function resetFilters() {
  Object.assign(filters, {
    q: '', assignee_employee_id: '', task_type: '', status: '', priority: '',
    due_window: '', source_type: '', customer_id: props.customerId, page: 1,
  })
  savedViewId.value = ''
  selectedRows.value = []
  await loadTasks()
}

async function changePageSize() {
  localStorage.setItem('haiqu.tasks.page-size', String(filters.page_size))
  filters.page = 1
  await loadTasks()
}

async function changeOrdering(ordering: string) {
  filters.ordering = ordering
  filters.page = 1
  await loadTasks()
}

function openDetail(row: TaskSummary) {
  router.push({
    name: 'task-detail',
    params: { taskId: row.id },
    query: props.embedded && props.customerId ? { return_to: 'customer', customer_id: props.customerId } : undefined,
  })
}

async function removeTask(row: TaskSummary) {
  try {
    const current = await fetchTask(row.id)
    await ElMessageBox.confirm(
      `确定永久删除任务“${current.data.title}”吗？提醒、清单、协同人与关联记录会一并删除，且无法恢复。`,
      '永久删除任务',
      { type: 'error', confirmButtonText: '确认永久删除', cancelButtonText: '取消', customClass: props.embedded ? 'customer-detail-message-box' : '' },
    )
    const result = await deleteTask(row.id, current.etag || '')
    ElMessage.success(`任务已删除，同时清理 ${result.deleted_count} 条关联数据。`)
    await refreshAll()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(taskRequestMessage(error))
  }
}

async function applySavedView(value: string) {
  const view = savedViews.value.find(item => item.id === value)
  if (!view) return
  const definition = view.filter_definition as Partial<TaskFilters>
  Object.assign(filters, definition, {
    customer_id: props.customerId || definition.customer_id || '',
    scope: definition.scope || filters.scope,
    page: 1,
    page_size: PAGE_SIZES.includes(Number(definition.page_size)) ? Number(definition.page_size) : filters.page_size,
    ordering: String(definition.ordering || view.sort_definition[0] || 'due_at'),
  })
  const visibleColumns = new Set(view.column_definition)
  Object.keys(columns).forEach(key => { columns[key as keyof typeof columns] = visibleColumns.has(key) })
  persistColumns()
  await Promise.all([loadOptions(filters.scope), refreshAll()])
}

async function handleSavedViewCommand(command: string) {
  if (command === '__save__') {
    if (!canSaveView.value) return
    saveViewVisible.value = true
    return
  }
  savedViewId.value = command
  await applySavedView(command)
}

async function saveCurrentView() {
  if (savingView.value || !canSaveView.value) return
  const name = savedViewName.value.trim()
  if (!name) return ElMessage.warning('请填写视图名称。')
  savingView.value = true
  try {
    const filterDefinition = Object.fromEntries(Object.entries(filters).filter(([key, value]) => key !== 'page' && value !== ''))
    const saved = await createSavedView({
      module_code: 'TASK',
      view_name: name,
      filter_definition: filterDefinition,
      column_definition: Object.entries(columns).filter(([, visible]) => visible).map(([key]) => key),
      sort_definition: [filters.ordering],
    })
    savedViews.value.push(saved)
    savedViewId.value = saved.id
    savedViewName.value = ''
    saveViewVisible.value = false
    ElMessage.success('任务视图已保存。')
  } catch (error) {
    ElMessage.error(taskRequestMessage(error))
  } finally {
    savingView.value = false
  }
}

async function finishBatch(_count: number) {
  batchDialog.value = null
  selectedRows.value = []
  await refreshAll()
}

onBeforeUnmount(() => { listRequestId++; metricsRequestId++; optionsRequestId++ })
onMounted(async () => {
  await Promise.all([
    loadOptions(filters.scope),
    canReadViews.value ? fetchSavedViews('TASK').then(value => { savedViews.value = value }).catch(error => {
      errorMessage.value = taskRequestMessage(error)
      return []
    }) : Promise.resolve(),
    refreshAll(),
  ])
})

watch(() => [props.customerId, props.defaultScope] as const, async ([customerId, scope]) => {
  filters.customer_id = customerId
  filters.scope = scope
  filters.page = 1
  await Promise.all([loadOptions(scope), refreshAll()])
})
</script>

<template>
  <section class="task-center" :class="{ 'task-center--embedded': embedded }">
    <header class="task-titlebar">
      <div class="task-titlebar__title">
        <h1>{{ embedded ? '客户任务' : '任务中心' }}</h1>
        <span>共 {{ total }} 条任务</span>
      </div>
      <div class="task-titlebar__actions">
        <el-button v-if="canCreate" type="primary" :icon="Plus" @click="createVisible = true">新建任务</el-button>
      </div>
    </header>

    <section v-loading="metricsLoading" class="task-metrics" aria-label="任务统计">
      <article v-for="card in cards" :key="card.label" class="task-metrics__item" :class="`task-metrics__item--${card.tone}`">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small v-if="card.hint">{{ card.hint }}</small>
      </article>
    </section>

    <el-alert v-if="errorMessage" class="error-alert" :title="errorMessage" type="error" show-icon :closable="false">
      <template #default><el-button link type="primary" @click="refreshAll">重新加载</el-button></template>
    </el-alert>

    <section class="task-filters" aria-label="任务筛选">
      <el-input v-model="filters.q" class="search-filter" clearable placeholder="搜索任务标题 / 客户" @keyup.enter="applyFilters" @clear="applyFilters" />
      <el-select v-model="filters.assignee_employee_id" class="assignee-filter" clearable filterable placeholder="负责人：全部" @change="applyFilters">
        <el-option v-for="item in options?.assignees" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" />
      </el-select>
      <el-select v-model="filters.task_type" class="type-filter" clearable placeholder="任务类型：全部" @change="applyFilters">
        <el-option v-for="item in options?.task_types" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.status" class="status-filter" clearable placeholder="状态：全部" @change="applyFilters">
        <el-option v-for="item in options?.statuses" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-popover placement="bottom-end" :width="620" trigger="click">
        <template #reference><el-button class="more-filter-button">更多筛选<el-icon><ArrowDown /></el-icon></el-button></template>
        <div class="more-filters">
          <label>任务范围<el-select v-model="filters.scope" @change="changeScopeFromFilter"><el-option v-for="item in scopeOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
          <label>优先级<el-select v-model="filters.priority" clearable><el-option v-for="item in options?.priorities" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
          <label>截止时间<el-select v-model="filters.due_window" clearable><el-option label="今日到期" value="TODAY" /><el-option label="已逾期" value="OVERDUE" /><el-option label="未来 7 天" value="NEXT_7_DAYS" /><el-option label="未设置" value="NO_DUE_DATE" /></el-select></label>
          <label>关联对象<el-select v-model="filters.source_type" clearable><el-option label="客户" value="CUSTOMER" /><el-option label="沟通" value="COMMUNICATION" /><el-option label="询盘" value="INQUIRY" /><el-option label="报价" value="QUOTATION" /><el-option label="样品" value="SAMPLE" /></el-select></label>
          <div class="more-filters__actions"><el-button @click="resetFilters">重置</el-button><el-button type="primary" @click="applyFilters">应用筛选</el-button></div>
        </div>
      </el-popover>
    </section>

    <section class="task-toolbar" aria-label="任务操作">
      <div class="task-toolbar__selection">
        <span>已选择 {{ selectedRows.length }} 条</span>
        <el-button v-if="canBulkComplete" :disabled="!selectedRows.length || selectedRows.some(row => !authStore.moduleCan('access_control.complete_businesstask', 'workflow.bulk_change_businesstask', row))" @click="batchDialog = 'complete'">批量完成</el-button>
        <el-button v-if="canBulkReassign" :disabled="!selectedRows.length || selectedRows.some(row => !authStore.moduleCan('workflow.reassign_businesstask', 'workflow.bulk_change_businesstask', row))" @click="batchDialog = 'reassign'">批量转交</el-button>
      </div>
      <div class="task-toolbar__tools">
        <el-dropdown @command="changeOrdering"><el-button :icon="Sort">排序</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-for="item in sortOptions" :key="item.value" :command="item.value" :disabled="filters.ordering === item.value">{{ item.label }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
        <el-dropdown><el-button :icon="Setting">列设置</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-for="(_, key) in columns" :key="key"><el-checkbox v-model="columns[key]" @change="persistColumns">{{ key === 'source' ? '关联对象' : key === 'origin' ? '来源' : '创建人' }}</el-checkbox></el-dropdown-item></el-dropdown-menu></template></el-dropdown>
        <el-dropdown v-if="canReadViews || canSaveView" @command="handleSavedViewCommand"><el-button>保存视图</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-for="view in savedViews" :key="view.id" :command="view.id">{{ view.view_name }}</el-dropdown-item><el-dropdown-item v-if="canSaveView" command="__save__" :divided="Boolean(savedViews.length)">保存当前视图</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
        <el-button :icon="Refresh" :loading="loading" @click="refreshAll">刷新</el-button>
      </div>
    </section>

    <section class="task-table">
      <el-table v-loading="loading" :data="rows" row-key="id" :height="embedded ? 620 : '100%'" empty-text="暂无符合条件的任务" @selection-change="selectedRows = $event">
        <el-table-column type="selection" width="58" />
        <el-table-column label="任务标题 / 编号" min-width="232"><template #default="{ row }"><button class="task-link" @click="openDetail(row)">{{ row.title }}</button><small>{{ row.task_number }}</small></template></el-table-column>
        <el-table-column label="关联客户" width="258"><template #default="{ row }"><span class="single-line">{{ row.customer?.name || '—' }}</span></template></el-table-column>
        <el-table-column v-if="columns.source" label="关联对象" width="231"><template #default="{ row }"><span class="single-line">{{ row.source ? `${row.source.code ? `${row.source.code} · ` : ''}${row.source.title}` : '—' }}</span></template></el-table-column>
        <el-table-column label="优先级" width="118"><template #default="{ row }"><span class="solid-tag solid-tag--priority" :class="`solid-tag--${row.priority.toLowerCase()}`">{{ priorityLabel(row) }}</span></template></el-table-column>
        <el-table-column label="负责人" width="121"><template #default="{ row }"><span class="single-line">{{ row.assignee.display_name }}</span></template></el-table-column>
        <el-table-column label="截止时间" width="145"><template #default="{ row }"><span class="single-line">{{ formatTaskDate(row.due_at) }}</span></template></el-table-column>
        <el-table-column label="状态" width="159"><template #default="{ row }"><span class="solid-tag solid-tag--status" :class="`solid-tag--${statusClass(row)}`">{{ statusLabel(row) }}</span></template></el-table-column>
        <el-table-column v-if="columns.origin" label="来源" width="146"><template #default="{ row }"><span class="single-line">{{ row.origin_type_display }}</span></template></el-table-column>
        <el-table-column v-if="columns.creator" label="创建人" width="146"><template #default="{ row }"><span class="single-line">{{ row.created_by?.display_name || '—' }}</span></template></el-table-column>
        <el-table-column label="操作" fixed="right" width="166"><template #default="{ row }"><div class="row-actions"><el-button link @click="openDetail(row)">查看</el-button><el-dropdown :persistent="false" trigger="click"><el-button link>处理</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item @click="openDetail(row)">打开任务详情</el-dropdown-item><el-dropdown-item v-if="canDelete && authStore.moduleCan('workflow.delete_businesstask', undefined, row)" divided @click="removeTask(row)">永久删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div></template></el-table-column>
      </el-table>
      <el-pagination v-if="total || !embedded" v-model:current-page="filters.page" v-model:page-size="filters.page_size" :page-sizes="PAGE_SIZES" :total="total" layout="total, sizes, prev, pager, next" class="task-pagination" @current-change="loadTasks" @size-change="changePageSize" />
    </section>

    <TaskCreateDialog v-model="createVisible" :class="{ 'customer-detail-dialog': embedded }" :scope="filters.scope" :options="options" :fixed-customer-id="customerId" :fixed-customer-name="customerName" :default-assignee-id="defaultAssigneeId" @created="refreshAll" />
    <TaskBulkCompleteDialog :model-value="batchDialog === 'complete'" :class="{ 'customer-detail-dialog': embedded }" :tasks="selectedRows" @update:model-value="value => { if (!value) batchDialog = null }" @completed="finishBatch" />
    <TaskBulkReassignDialog :model-value="batchDialog === 'reassign'" :class="{ 'customer-detail-dialog': embedded }" :tasks="selectedRows" :options="options" @update:model-value="value => { if (!value) batchDialog = null }" @completed="finishBatch" />
    <AppWindowDialog v-model="saveViewVisible" :class="{ 'customer-detail-dialog': embedded }" title="保存任务视图" :width="420" :height="240" destroy-on-close>
      <el-form label-position="top"><el-form-item label="视图名称" required><el-input v-model="savedViewName" maxlength="100" placeholder="例如：本周高优先级" /></el-form-item></el-form>
      <template #footer><el-button :disabled="savingView" @click="saveViewVisible = false">取消</el-button><el-button type="primary" :loading="savingView" @click="saveCurrentView">保存</el-button></template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.task-center {
  $page-bg: token.$crm-color-page;
  $surface: #fcfbf7;
  $border: #e5dfd5;
  $text: #1f1d18;
  $muted: #858078;
  $accent: #c7441d;

  min-width: 0;
  min-height: calc(100vh - 64px);
  margin: 0;
  padding: 26px 28px 28px;
  color: $text;
  background: $page-bg;
  font-family: token.$crm-font-body;

  &:not(.task-center--embedded) {
    display: flex;
    height: 100%;
    min-height: 0;
    flex-direction: column;

    .task-metrics {
      grid-template-columns: repeat(5, minmax(0, 1fr));
    }

    .task-metrics__item {
      min-width: 0;
      gap: 8px;
      padding: 0 14px;
    }

    .task-metrics__item span {
      white-space: nowrap;
    }

    .task-metrics__item small {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .task-filters {
      height: auto;
      min-height: 42px;
      flex-wrap: wrap;
      gap: 10px 12px;
    }

    .task-filters .search-filter {
      min-width: 220px;
      max-width: 410px;
      flex: 1 1 220px;
    }

    .task-filters .assignee-filter,
    .task-filters .type-filter,
    .task-filters .status-filter,
    .task-filters .more-filter-button {
      flex: none;
    }

    .task-table {
      display: flex;
      min-height: 0;
      flex: 1;
      flex-direction: column;
    }

    .task-table :deep(.el-table) {
      min-height: 0;
      flex: 1;
    }

    .task-pagination {
      flex: none;
      height: 48px;
      min-height: 48px;
      padding: 0 14px;
      gap: 8px;
      color: token.$crm-text-secondary;
      background: token.$crm-color-surface;
      font-size: 12px;
      --el-pagination-button-width: 38px;
      --el-pagination-button-height: 32px;
    }

    .task-pagination :deep(.el-pagination__sizes) {
      width: 136px;
      margin-right: 16px;
    }

    .task-pagination :deep(.el-select) {
      width: 136px;
    }

    .task-pagination :deep(.el-select__wrapper) {
      min-height: 32px;
    }

    .task-pagination :deep(.btn-prev),
    .task-pagination :deep(.btn-next),
    .task-pagination :deep(.el-pager li) {
      height: 32px;
      min-height: 32px;
      line-height: 32px;
      margin: 0;
      border: 1px solid token.$crm-border-default;
      border-radius: token.$crm-radius-2;
      color: token.$crm-text-primary;
      background: token.$crm-color-surface;
      font-size: 13px;
      font-weight: 500;
    }

    .task-pagination :deep(.el-pager) {
      gap: 8px;
    }

    .task-pagination :deep(.el-pager li.is-active) {
      border-color: token.$crm-primary;
      color: token.$crm-text-primary;
    }
  }

  .task-titlebar,
  .task-titlebar__title,
  .task-titlebar__actions,
  .task-filters,
  .task-toolbar,
  .task-toolbar__selection,
  .task-toolbar__tools,
  .row-actions {
    display: flex;
    align-items: center;
  }

  .task-titlebar {
    height: 50px;
    justify-content: space-between;

    &__title {
      gap: 16px;

      h1 {
        margin: 0;
        color: $text;
        font-family: token.$crm-font-display;
        font-size: 38px;
        font-weight: 600;
        line-height: 50px;
      }

      span {
        color: $muted;
        font-size: 14px;
      }
    }

    &__actions {
      gap: 16px;

      :deep(.el-button--primary) {
        width: 140px;
        height: 42px;
        margin: 0;
        border-color: $accent;
        border-radius: 5px;
        background: $accent;
        font-size: 16px;
      }
    }
  }

  .task-metrics {
    height: 56px;
    display: grid;
    grid-template-columns: 311px 311px 311px 311px minmax(310px, 1fr);
    margin-top: 8px;
    overflow: hidden;
    border: 1px solid $border;
    border-radius: 5px;
    background: $surface;

    &__item {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 22px;
      border-right: 1px solid $border;

      &:last-child { border-right: 0; }
      span { color: #706b64; font-size: 16px; }
      strong { color: #292621; font-family: token.$crm-font-display; font-size: 24px; font-weight: 600; line-height: 30px; }
      small { color: #4f7d4b; font-size: 13px; }
      &--danger strong { color: #b53333; }
    }
  }

  .error-alert { margin-top: 10px; }

  .task-filters {
    height: 42px;
    gap: 12px;
    margin-top: 16px;

    .search-filter { width: 410px; }
    .assignee-filter { width: 160px; }
    .type-filter { width: 176px; }
    .status-filter { width: 160px; }

    :deep(.el-input__wrapper),
    :deep(.el-select__wrapper) {
      min-height: 42px;
      border-radius: 4px;
      background: #fffefb;
      box-shadow: 0 0 0 1px #d8d2c8 inset;
    }

    .more-filter-button {
      width: 130px;
      height: 42px;
      margin: 0;
      border-radius: 4px;
      font-size: 15px;

      :deep(.el-icon) { margin-left: 7px; }
    }
  }

  .task-toolbar {
    height: 42px;
    justify-content: space-between;
    margin-top: 18px;
    color: #6f6a63;
    font-size: 14px;

    &__selection,
    &__tools { gap: 10px; }

    &__selection {
      > span { width: 118px; }
      :deep(.el-button) { width: 110px; }
    }

    &__tools {
      :deep(.el-button) { width: 90px; }
      > :nth-child(3) :deep(.el-button) { width: 110px; }
      > :last-child { width: 100px; }
    }

    :deep(.el-button) {
      height: 42px;
      margin: 0;
      border-radius: 4px;
      font-size: 14px;
    }
  }

  .task-table {
    margin-top: 14px;
    overflow: hidden;
    border: 1px solid $border;
    border-radius: 5px;
    background: #fffefb;

    :deep(.el-table) {
      width: 100%;
      --el-table-header-bg-color: #ebe7df;
      --el-table-border-color: #e5dfd5;
      --el-table-row-hover-bg-color: #f7f4ee;
      color: #3e3a35;
      font-size: 16px;
    }

    :deep(.el-table th.el-table__cell) { height: 48px; padding: 0; color: #514c45; font-size: 15px; font-weight: 600; }
    :deep(.el-table td.el-table__cell) { height: 52px; padding: 0; }
    :deep(.el-table .cell) { padding: 0 12px; line-height: 21px; }

    small {
      display: block;
      color: #928c84;
      font-size: 14px;
      line-height: 18px;
    }
  }

  .task-link {
    max-width: 100%;
    overflow: hidden;
    padding: 0;
    border: 0;
    color: #282520;
    background: transparent;
    cursor: pointer;
    font-size: 16px;
    font-weight: 600;
    line-height: 21px;
    text-align: left;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .single-line { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .solid-tag {
    min-width: 56px;
    height: 24px;
    box-sizing: border-box;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0 10px;
    border-radius: 999px;
    color: #faf9f5;
    background: #5e5d59;
    font-size: 12px;

    &--priority { min-width: 56px; }
    &--status { min-width: 64px; }
    &--urgent,
    &--danger { background: #b53333; }
    &--high,
    &--warning { background: #b8781e; }
    &--low,
    &--success { background: #4f7d4b; }
    &--normal,
    &--info { background: #3898ec; }
    &--neutral { background: #5e5d59; }
  }

  .row-actions {
    gap: 16px;

    :deep(.el-button) { margin: 0; color: $accent; font-size: 16px; }
  }

  .task-pagination {
    height: 96px;
    justify-content: flex-end;
    padding: 0 18px;
    border-top: 1px solid $border;

    :deep(.el-pagination__total) { margin-right: auto; }
    :deep(.el-select) { width: 136px; }
    :deep(.btn-prev),
    :deep(.btn-next),
    :deep(.el-pager li) { width: 38px; min-width: 38px; height: 42px; line-height: 42px; }
  }

  &.task-center--embedded {
    min-height: 0;
    margin: 0;
    padding: 20px 26px 28px;

    .task-titlebar__title h1 { font-size: 30px; }
    .task-metrics { grid-template-columns: repeat(5, 1fr); }
    .task-titlebar__actions :deep(.el-button--primary) { height: 32px; }
    .task-filters { height: 32px; gap: 10px; margin-top: 12px; }
    .task-filters :deep(.el-input__wrapper),
    .task-filters :deep(.el-select__wrapper) { min-height: 32px; border-radius: token.$crm-radius-2; }
    .task-filters .more-filter-button { height: 32px; border-radius: token.$crm-radius-2; }
    .task-toolbar { height: 32px; margin-top: 10px; }
    .task-toolbar :deep(.el-button) { height: 32px; border-radius: token.$crm-radius-2; }
    .task-table { margin-top: 10px; }
    .task-pagination { height: 52px; }
    .task-pagination :deep(.el-select__wrapper),
    .task-pagination :deep(.btn-prev),
    .task-pagination :deep(.btn-next),
    .task-pagination :deep(.el-pager li) { height: 32px; min-height: 32px; line-height: 32px; border-radius: token.$crm-radius-2; }
  }
}

.more-filters {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;

  label { display: grid; gap: 7px; color: #57524d; font-size: 13px; }
  :deep(.el-select) { width: 100%; }

  &__actions {
    grid-column: 1 / -1;
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
}
</style>
