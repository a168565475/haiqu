<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Plus } from '@element-plus/icons-vue'

import TaskCreateDialog from '@/components/tasks/TaskCreateDialog.vue'
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
  <section class="task-center" :class="{ 'task-center--embedded': embedded }">
    <header class="task-titlebar">
      <div class="task-titlebar__title">
        <h1>{{ embedded ? '客户任务' : '任务中心' }}</h1>
        <span>共 {{ total }} 条任务</span>
      </div>
    </header>

    <el-alert v-if="errorMessage" class="error-alert" :title="errorMessage" type="error" show-icon :closable="false">
      <template #default><el-button link type="primary" @click="loadTasks">重新加载</el-button></template>
    </el-alert>

    <section class="task-filters" aria-label="任务筛选">
      <el-input v-model="filters.q" class="search-filter" clearable placeholder="搜索任务标题 / 描述" @keydown.enter="handleSearchEnter" @clear="searchTasks">
        <template #suffix>
          <button type="button" class="task-search-button" aria-label="搜索任务" @click="searchTasks">
            <img :src="searchIcon" alt="" aria-hidden="true" />
          </button>
        </template>
      </el-input>
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
      <div v-if="canCreate" class="task-filter-actions">
        <el-button type="primary" :icon="Plus" @click="createVisible = true">新建任务</el-button>
      </div>
    </section>

    <section class="task-table">
      <el-table v-loading="loading" :data="rows" row-key="id" :height="embedded ? 620 : '100%'" empty-text="暂无符合条件的任务">
        <el-table-column label="任务标题 / 编号" min-width="232"><template #default="{ row }"><button class="task-link" @click="openDetail(row)">{{ row.title }}</button><small>{{ row.task_number }}</small></template></el-table-column>
        <el-table-column label="关联客户" width="258"><template #default="{ row }"><span class="single-line">{{ row.customer?.name || '—' }}</span></template></el-table-column>
        <el-table-column label="关联对象" width="231"><template #default="{ row }"><span class="single-line">{{ row.source ? `${row.source.code ? `${row.source.code} · ` : ''}${row.source.title}` : '—' }}</span></template></el-table-column>
        <el-table-column label="优先级" width="118"><template #default="{ row }"><span class="solid-tag solid-tag--priority" :class="`solid-tag--${row.priority.toLowerCase()}`">{{ priorityLabel(row) }}</span></template></el-table-column>
        <el-table-column label="负责人" width="121"><template #default="{ row }"><span class="single-line">{{ row.assignee.display_name }}</span></template></el-table-column>
        <el-table-column label="截止时间" width="145"><template #default="{ row }"><span class="single-line">{{ formatTaskDate(row.due_at) }}</span></template></el-table-column>
        <el-table-column label="状态" width="159"><template #default="{ row }"><span class="solid-tag solid-tag--status" :class="`solid-tag--${statusClass(row)}`">{{ statusLabel(row) }}</span></template></el-table-column>
        <el-table-column label="来源" width="146"><template #default="{ row }"><span class="single-line">{{ row.origin_type_display }}</span></template></el-table-column>
        <el-table-column label="操作" fixed="right" width="166"><template #default="{ row }"><div class="row-actions"><el-button link @click="openDetail(row)">查看</el-button><el-dropdown :persistent="false" trigger="click"><el-button link>处理</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item @click="openDetail(row)">打开任务详情</el-dropdown-item><el-dropdown-item v-if="canDelete && authStore.moduleCan('workflow.delete_businesstask', undefined, row)" divided @click="removeTask(row)">永久删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div></template></el-table-column>
      </el-table>
      <el-pagination v-if="total || !embedded" v-model:current-page="filters.page" v-model:page-size="filters.page_size" :page-sizes="PAGE_SIZES" :pager-count="5" :total="total" layout="total, sizes, prev, pager, next" class="task-pagination" @current-change="loadTasks" @size-change="changePageSize" />
    </section>

    <TaskCreateDialog v-model="createVisible" :class="{ 'customer-detail-dialog': embedded }" :scope="filters.scope" :options="options" :fixed-customer-id="customerId" :fixed-customer-name="customerName" :default-assignee-id="defaultAssigneeId" @created="loadTasks" />
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.task-center {
  $page-bg: token.$crm-color-page;
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
      min-height: 48px;
      padding: 8px 14px;
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
  .task-filters,
  .task-filter-actions,
  .row-actions {
    display: flex;
    align-items: center;
  }

  .task-titlebar {
    min-height: 50px;
    flex: none;
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

  }

  .error-alert { flex: none; margin-top: 10px; }

  .task-filters {
    min-height: 42px;
    flex: none;
    flex-wrap: wrap;
    gap: 10px 12px;
    margin-top: 16px;

    .search-filter { width: 250px; min-width: 250px; flex: none; }
    .assignee-filter { width: 160px; flex: none; }
    .type-filter { width: 176px; flex: none; }
    .status-filter { width: 160px; flex: none; }

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
      flex: none;
      margin: 0;
      border-radius: 4px;
      font-size: 15px;

      :deep(.el-icon) { margin-left: 7px; }
    }
  }

  .task-filter-actions {
    flex: none;
    margin-left: auto;

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

  .task-search-button {
    display: inline-flex;
    width: 20px;
    height: 24px;
    align-items: center;
    justify-content: center;
    margin: 0;
    padding: 0;
    border: 0;
    color: inherit;
    background: transparent;
    cursor: pointer;

    img { width: 16px; height: 16px; }
    &:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
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
    min-height: 48px;
    flex-wrap: wrap;
    justify-content: flex-end;
    padding: 8px 18px;
    gap: 8px;
    border-top: 1px solid $border;

    :deep(> *) { flex: none; }
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
    .task-filter-actions :deep(.el-button--primary) { height: 32px; }
    .task-filters { min-height: 32px; gap: 10px; margin-top: 12px; }
    .task-filters :deep(.el-input__wrapper),
    .task-filters :deep(.el-select__wrapper) { min-height: 32px; border-radius: token.$crm-radius-2; }
    .task-filters .more-filter-button { height: 32px; border-radius: token.$crm-radius-2; }
    .task-table { margin-top: 10px; }
    .task-pagination { min-height: 52px; }
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
