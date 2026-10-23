<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Plus } from '@element-plus/icons-vue'

import TaskCreateDialog from '@/components/tasks/TaskCreateDialog.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { deleteTask, fetchTask, fetchTaskOptions, fetchTasks } from '@/api/tasks'
import searchIcon from '@/assets/crm-v2/search.svg'
import { useAuthStore } from '@/stores/auth'
import { formatTaskDate, taskRequestMessage } from '@/utils/taskFeedback'
import type { TaskFilters, TaskOptions, TaskScope, TaskSummary } from '@/types/task'

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
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const errorMessage = ref('')
const rows = ref<TaskSummary[]>([])
const total = ref(0)
const options = ref<TaskOptions | null>(null)
const createVisible = ref(false)
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
let optionsRequestId = 0

const canCreate = computed(() => authStore.hasPermission('workflow.add_businesstask'))
const canDelete = computed(() => authStore.hasPermission('workflow.delete_businesstask'))
const scopeOptions = computed(() => options.value?.scopes || [])

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
  await Promise.all([loadOptions(scope), loadTasks()])
}

async function applyFilters() {
  filters.page = 1
  await loadTasks()
}

function searchTasks() {
  filters.q = filters.q.trim()
  return applyFilters()
}

function handleSearchEnter(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  void searchTasks()
}

async function resetFilters() {
  Object.assign(filters, {
    q: '', assignee_employee_id: '', task_type: '', status: '', priority: '',
    due_window: '', source_type: '', customer_id: props.customerId, page: 1,
  })
  await loadTasks()
}

async function changePageSize() {
  localStorage.setItem('haiqu.tasks.page-size', String(filters.page_size))
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
    await loadTasks()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(taskRequestMessage(error))
  }
}

onBeforeUnmount(() => { listRequestId++; optionsRequestId++ })
onMounted(async () => {
  await Promise.all([
    loadOptions(filters.scope),
    loadTasks(),
  ])
})

watch(() => [props.customerId, props.defaultScope] as const, async ([customerId, scope]) => {
  filters.customer_id = customerId
  filters.scope = scope
  filters.page = 1
  await Promise.all([loadOptions(scope), loadTasks()])
})
</script>

<template>
  <section class="task-center erp-glass-list" :class="{ 'task-center--embedded': embedded }">
    <section v-glass-spotlight class="task-filter-card erp-list-filter">
    <header class="task-titlebar" :class="{ 'erp-list-heading': !embedded }">
      <div class="task-titlebar__title">
        <h2 v-if="embedded">客户任务</h2>
        <h1 v-else>任务中心</h1>
        <span>共 {{ total }} 条任务</span>
      </div>
    </header>

    <el-alert v-if="errorMessage" class="error-alert" :title="errorMessage" type="error" show-icon :closable="false">
      <template #default><el-button link type="primary" @click="loadTasks">重新加载</el-button></template>
    </el-alert>

    <section class="task-filters erp-list-filters" aria-label="任务筛选">
      <el-input v-model="filters.q" class="search-filter" clearable placeholder="搜索任务标题 / 描述" @keydown.enter="handleSearchEnter" @clear="searchTasks">
        <template #suffix>
          <button type="button" class="task-search-button" aria-label="搜索任务" @click="searchTasks">
            <img :src="searchIcon" alt="" aria-hidden="true" />
          </button>
        </template>
      </el-input>
      <el-select v-model="filters.assignee_employee_id" class="assignee-filter" clearable filterable placeholder="负责人：全部" @change="applyFilters">
        <el-option v-for="item in (options?.assignee_filters || options?.assignees)" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" />
      </el-select>
      <el-select v-model="filters.task_type" class="type-filter" clearable placeholder="任务类型：全部" @change="applyFilters">
        <el-option v-for="item in options?.task_types" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-select v-model="filters.status" class="status-filter" clearable placeholder="状态：全部" @change="applyFilters">
        <el-option v-for="item in options?.statuses" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-popover placement="bottom-end" :width="620" trigger="click" popper-class="erp-list-filter-popover">
        <template #reference><el-button class="more-filter-button erp-button-motion">更多筛选<el-icon><ArrowDown /></el-icon></el-button></template>
        <div class="more-filters more-filters--glass">
          <label>任务范围<el-select v-model="filters.scope" @change="changeScopeFromFilter"><el-option v-for="item in scopeOptions" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
          <label>优先级<el-select v-model="filters.priority" clearable><el-option v-for="item in options?.priorities" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
          <label>截止时间<el-select v-model="filters.due_window" clearable><el-option label="今日到期" value="TODAY" /><el-option label="已逾期" value="OVERDUE" /><el-option label="未来 7 天" value="NEXT_7_DAYS" /><el-option label="未设置" value="NO_DUE_DATE" /></el-select></label>
          <label>关联对象<el-select v-model="filters.source_type" clearable><el-option label="客户" value="CUSTOMER" /><el-option label="沟通" value="COMMUNICATION" /><el-option label="询盘" value="INQUIRY" /><el-option label="报价" value="QUOTATION" /><el-option label="样品" value="SAMPLE" /></el-select></label>
          <div class="more-filters__actions"><el-button class="erp-button-motion" @click="resetFilters">重置</el-button><el-button type="primary" class="erp-button-motion" @click="applyFilters">应用筛选</el-button></div>
        </div>
      </el-popover>
      <div class="erp-list-filter-actions"><el-button class="erp-button-motion" @click="resetFilters">重置</el-button><el-button class="erp-button-motion" type="primary" @click="searchTasks">应用筛选</el-button></div>
      <div v-if="embedded && canCreate" class="task-filter-actions">
        <el-button class="erp-button-motion" type="primary" :icon="Plus" @click="createVisible = true">新建任务</el-button>
      </div>
    </section>
    </section>

    <section class="task-table erp-list-data">
      <div v-if="!embedded && canCreate" class="task-toolbar erp-list-toolbar">
        <el-button class="erp-button-motion" type="primary" :icon="Plus" @click="createVisible = true">新建任务</el-button>
      </div>
      <div class="task-table-frame erp-list-table-frame">
      <el-table v-loading="loading" :data="rows" row-key="id" :height="embedded ? undefined : '100%'" :max-height="embedded ? 'min(520px, 56vh)' : undefined" empty-text="暂无符合条件的任务">
        <el-table-column prop="task_number" label="任务编号" width="180" show-overflow-tooltip />
        <el-table-column label="任务标题" min-width="232"><template #default="{ row }"><button class="task-link" @click="openDetail(row)">{{ row.title }}</button></template></el-table-column>
        <el-table-column label="关联客户" width="258"><template #default="{ row }"><span class="single-line">{{ row.customer?.name || '—' }}</span></template></el-table-column>
        <el-table-column label="关联对象" width="231"><template #default="{ row }"><span class="single-line">{{ row.source ? `${row.source.code ? `${row.source.code} · ` : ''}${row.source.title}` : '—' }}</span></template></el-table-column>
        <el-table-column label="优先级" width="118"><template #default="{ row }"><span class="solid-tag solid-tag--priority" :class="`solid-tag--${row.priority.toLowerCase()}`">{{ priorityLabel(row) }}</span></template></el-table-column>
        <el-table-column label="负责人" width="121"><template #default="{ row }"><span class="single-line">{{ row.assignee.display_name }}</span></template></el-table-column>
        <el-table-column label="截止时间" width="145"><template #default="{ row }"><span class="single-line">{{ formatTaskDate(row.due_at) }}</span></template></el-table-column>
        <el-table-column label="状态" width="159"><template #default="{ row }"><span class="solid-tag solid-tag--status" :class="`solid-tag--${statusClass(row)}`">{{ statusLabel(row) }}</span></template></el-table-column>
        <el-table-column label="来源" width="146"><template #default="{ row }"><span class="single-line">{{ row.origin_type_display }}</span></template></el-table-column>
        <el-table-column label="操作" fixed="right" width="166"><template #default="{ row }"><div class="row-actions"><el-button link @click="openDetail(row)">查看</el-button><el-dropdown :persistent="false" trigger="click"><el-button link>处理</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item @click="openDetail(row)">打开任务详情</el-dropdown-item><el-dropdown-item v-if="canDelete && authStore.moduleCan('workflow.delete_businesstask', undefined, row)" divided @click="removeTask(row)">永久删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div></template></el-table-column>
      </el-table>
      </div>
      <footer class="task-pagination-shell erp-list-footer">
      <el-pagination v-if="total || !embedded" v-model:current-page="filters.page" v-model:page-size="filters.page_size" :page-sizes="PAGE_SIZES" :pager-count="5" :total="total" layout="total, sizes, prev, pager, next" class="task-pagination" @current-change="loadTasks" @size-change="changePageSize" />
      </footer>
    </section>

    <TaskCreateDialog v-model="createVisible" :embedded="embedded" :scope="filters.scope" :options="options" :fixed-customer-id="customerId" :fixed-customer-name="customerName" :default-assignee-id="defaultAssigneeId" @created="loadTasks" />
  </section>
</template>

<style scoped lang="scss">
.task-center.erp-glass-list {
  .task-titlebar__title {
    display: flex;
    min-width: 0;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 12px;

    > span { color: var(--erp-color-text-secondary); font-size: 12px; }
  }

  .error-alert { flex: none; margin-bottom: 12px; }
  .search-filter { width: min(250px, 100%); min-width: 0; flex: none; }
  .assignee-filter { width: 160px; flex: none; }
  .type-filter { width: 176px; flex: none; }
  .status-filter { width: 160px; flex: none; }
  .more-filter-button {
    width: 130px;
    flex: none;
    :deep(.el-icon) { margin-left: 7px; }
  }

  .task-search-button {
    display: inline-flex;
    width: 24px;
    height: 30px;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: 0;
    color: var(--erp-input-placeholder);
    background: transparent;
    cursor: pointer;

    img { width: 16px; height: 16px; }
  }

  .task-search-button:focus-visible,
  .task-link:focus-visible {
    outline: 2px solid var(--erp-color-focus);
    outline-offset: 2px;
  }

  .task-link {
    max-width: 100%;
    overflow: hidden;
    padding: 0;
    border: 0;
    color: var(--erp-table-text);
    background: transparent;
    cursor: pointer;
    font-size: 13px;
    font-weight: 600;
    line-height: 20px;
    text-align: left;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .task-link:hover { text-decoration: underline; text-underline-offset: 3px; }
  .task-table small { display: block; color: var(--erp-table-text); font-size: 11px; line-height: 16px; }
  .single-line { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  .solid-tag {
    display: inline-flex;
    box-sizing: border-box;
    min-width: 56px;
    height: 24px;
    align-items: center;
    justify-content: center;
    padding: 0 10px;
    border: 1px solid transparent;
    border-radius: var(--erp-radius-pill);
    font-size: 12px;

    &--status { min-width: 64px; }

    @each $status, $tone in (urgent: danger, danger: danger, high: warning, warning: warning, low: success, success: success, normal: info, info: info, neutral: neutral) {
      &--#{$status} {
        color: var(--erp-tag-#{$tone}-text);
        border-color: var(--erp-tag-#{$tone}-border);
        background: var(--erp-tag-#{$tone}-background);
      }
    }
  }

  .row-actions {
    display: flex;
    align-items: center;
    gap: 16px;

    :deep(.el-button) { margin: 0; color: var(--erp-table-text); font-size: 12px; }
  }
}

.task-center.task-center--embedded {
  height: auto;
  overflow: visible;
  font-size: 13px;
  line-height: 20px;

  .task-titlebar { margin-bottom: 14px; }
  .task-titlebar__title h2 { margin: 0; font-size: 16px; font-weight: 600; line-height: 24px; }
  .task-titlebar__title > span { font-size: 13px; }
  .task-filter-actions { display: flex; flex: none; }
  .task-table, .task-table-frame { flex: none; }
  .task-table-frame :deep(.el-table .cell) { font-size: 13px; line-height: 20px; }
  .task-filters :deep(.el-input__inner),
  .task-filters :deep(.el-select__placeholder),
  .row-actions :deep(.el-button) { font-size: 13px; }
}

.more-filters {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;

  label { display: grid; gap: 7px; color: var(--erp-color-text-regular); font-size: 13px; }
  :deep(.el-select) { width: 100%; }

  &__actions {
    grid-column: 1 / -1;
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }

  &--glass label { color: var(--erp-color-text-primary); }
}
</style>
