<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { AlarmClock, Bell, Calendar, Check, CircleCheck, EditPen, Link, OfficeBuilding, Tickets, User } from '@element-plus/icons-vue'

import TaskReassignDialog from '@/components/tasks/TaskReassignDialog.vue'
import TaskRescheduleDialog from '@/components/tasks/TaskRescheduleDialog.vue'
import { fetchTask, fetchTaskActivity, fetchTaskOptions, postTaskAction, toggleTaskChecklist } from '@/api/tasks'
import { useAuthStore } from '@/stores/auth'
import type { TaskDetail, TaskOptions } from '@/types/task'
import { formatTaskDate, taskRequestMessage } from '@/utils/taskFeedback'

type Activity = { kind: string; id: string; event_type: string; title: string; summary: string; occurred_at: string; actor: string | null }

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const task = ref<TaskDetail | null>(null)
const etag = ref<string | null>(null)
const options = ref<TaskOptions | null>(null)
const activities = ref<Activity[]>([])
const loading = ref(true)
const acting = ref(false)
const errorMessage = ref('')
const activityErrorMessage = ref('')
const activityLoading = ref(false)
let taskRequestId = 0
let activityRequestId = 0
const conflictMessage = ref('')
const dialog = ref<'reassign' | 'reschedule' | null>(null)
const taskId = computed(() => String(route.params.taskId || ''))
const closed = computed(() => !task.value || ['COMPLETED', 'CANCELLED'].includes(task.value.status))
const canChange = computed(() => authStore.moduleCan('workflow.change_businesstask', undefined, task.value))
const canComplete = computed(() => authStore.moduleCan('access_control.complete_businesstask', 'workflow.change_businesstask', task.value))
const canReschedule = computed(() => authStore.moduleCan('access_control.reschedule_businesstask', 'workflow.change_businesstask', task.value))
const canReassign = computed(() => authStore.moduleCan('workflow.reassign_businesstask', undefined, task.value))

function statusLabel(value: TaskDetail) {
  const labels: Record<string, string> = { BLOCKED: '阻塞', OVERDUE: '已逾期', WAITING_CUSTOMER: '待反馈' }
  return labels[value.display_status] || value.status_display
}

function priorityLabel(value: TaskDetail) {
  return value.priority === 'NORMAL' ? '中优先级' : `${value.priority_display}优先级`
}

function baseStatusClass(value: TaskDetail) {
  if (value.status === 'COMPLETED') return 'success'
  if (value.status === 'CANCELLED') return 'neutral'
  return 'info'
}

function specialStatusLabel(value: TaskDetail) {
  const labels: Record<string, string> = { BLOCKED: '阻塞', OVERDUE: '已逾期', WAITING_CUSTOMER: '待反馈' }
  return labels[value.display_status] || ''
}

function activityTitle(activity: Activity) {
  const labels: Record<string, string> = {
    CREATED: '创建任务',
    TASK_CREATED: '创建任务',
    UPDATED: '更新任务',
    CUSTOMER_CONTACTED: '联系客户',
    CHECKLIST_UPDATED: '更新检查清单',
    CHECKLIST_COMPLETED: '完成检查项',
    CHECKLIST_REOPENED: '重新打开检查项',
    FOLLOW_UP: '确认跟进计划',
    COMPLETED: '完成任务',
    CANCELLED: '取消任务',
    REASSIGNED: '转交任务',
    RESCHEDULED: '调整截止时间',
    WORK_STATE_NORMAL: '恢复正常处理',
    WORK_STATE_WAITING_CUSTOMER: '等待客户反馈',
    WORK_STATE_BLOCKED: '标记为阻塞',
  }
  return labels[activity.event_type] || activity.title
}

function statusClass(value: TaskDetail) {
  if (['OVERDUE', 'BLOCKED'].includes(value.display_status)) return 'danger'
  if (value.display_status === 'WAITING_CUSTOMER') return 'warning'
  if (value.status === 'COMPLETED') return 'success'
  if (value.status === 'CANCELLED') return 'neutral'
  return 'info'
}

async function loadTask() {
  const request = ++taskRequestId
  loading.value = true
  errorMessage.value = ''
  conflictMessage.value = ''
  try {
    const result = await fetchTask(taskId.value)
    if (request !== taskRequestId) return
    task.value = result.data
    etag.value = result.etag
    void loadActivities()
  } catch (error) {
    if (request !== taskRequestId) return
    errorMessage.value = taskRequestMessage(error)
  } finally {
    if (request === taskRequestId) loading.value = false
  }
}

async function loadActivities() {
  const request = ++activityRequestId
  activityLoading.value = true
  activityErrorMessage.value = ''
  try {
    const result = await fetchTaskActivity(taskId.value)
    if (request === activityRequestId) activities.value = result
  } catch (error) {
    if (request === activityRequestId) activityErrorMessage.value = taskRequestMessage(error)
  } finally {
    if (request === activityRequestId) activityLoading.value = false
  }
}

async function reloadActivities() {
  await loadActivities()
}

function acceptUpdate(updatedTask: TaskDetail, nextEtag: string | null) {
  task.value = updatedTask
  etag.value = nextEtag
  conflictMessage.value = ''
  void reloadActivities()
}

async function completeTask() {
  if (!task.value || !etag.value || acting.value) return
  try {
    await ElMessageBox.confirm('完成后任务将进入只读状态，待执行提醒会被关闭。确认继续吗？', '完成任务', {
      confirmButtonText: '确认完成', cancelButtonText: '取消', type: 'warning',
    })
  } catch { return }
  acting.value = true
  try {
    const result = await postTaskAction(task.value.id, 'complete', { note: '' }, etag.value)
    acceptUpdate(result.data, result.etag)
    ElMessage.success('任务已完成。')
  } catch (error) {
    const message = taskRequestMessage(error)
    if (message.includes('其他人修改')) conflictMessage.value = message
    else ElMessage.error(message)
  } finally {
    acting.value = false
  }
}

async function toggleChecklist(itemId: string, isCompleted: boolean) {
  if (!task.value || !etag.value || acting.value) return
  acting.value = true
  try {
    const nextEtag = await toggleTaskChecklist(task.value.id, itemId, isCompleted, etag.value)
    const item = task.value.checklist_items.find(value => value.id === itemId)
    if (item) {
      item.is_completed = isCompleted
      item.completed_at = isCompleted ? new Date().toISOString() : null
    }
    task.value.checklist_progress.completed = task.value.checklist_items.filter(value => value.is_completed).length
    etag.value = nextEtag
    await reloadActivities()
  } catch (error) {
    const message = taskRequestMessage(error)
    if (message.includes('其他人修改')) conflictMessage.value = message
    else ElMessage.error(message)
  } finally {
    acting.value = false
  }
}

function openSource() {
  const url = task.value?.source?.open_url
  if (!url) return ElMessage.info('该来源对象暂未提供可用入口。')
  if (url.startsWith('/')) router.push(url)
  else window.open(url, '_blank', 'noopener,noreferrer')
}

onBeforeUnmount(() => { taskRequestId++; activityRequestId++ })
onMounted(async () => {
  await Promise.all([
    loadTask(),
    fetchTaskOptions('ME').then(value => { options.value = value }).catch(error => { ElMessage.warning(`任务操作选项加载失败：${taskRequestMessage(error)}`) }),
  ])
})
</script>

<template>
  <section class="task-detail" v-loading="loading">
    <el-alert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false"><template #default><el-button link type="primary" @click="loadTask">重试</el-button></template></el-alert>
    <template v-else-if="task">
      <header class="detail-hero">
        <div class="detail-hero__main">
          <h1>{{ task.title }}</h1>
          <div class="detail-hero__badges">
            <span class="solid-tag" :class="`solid-tag--${task.priority.toLowerCase()}`">{{ priorityLabel(task) }}</span>
            <span class="solid-tag" :class="`solid-tag--${baseStatusClass(task)}`">{{ task.status_display }}</span>
            <span v-if="specialStatusLabel(task)" class="solid-tag" :class="`solid-tag--${statusClass(task)}`">{{ specialStatusLabel(task) }}</span>
          </div>
        </div>
        <div class="actions">
          <el-button v-if="canReassign" :icon="EditPen" :disabled="closed" @click="dialog = 'reassign'">转交</el-button>
          <el-button v-if="canReschedule" :icon="Calendar" :disabled="closed" @click="dialog = 'reschedule'">改期</el-button>
          <el-button v-if="canComplete" type="primary" :icon="Check" :loading="acting" :disabled="closed || !etag" @click="completeTask">完成任务</el-button>
        </div>
      </header>
      <p class="detail-subtitle">{{ task.task_number }} · {{ task.task_type_display }} · {{ task.origin_type_display }}</p>

      <el-alert v-if="conflictMessage" class="conflict-alert" type="warning" :title="conflictMessage" :closable="false" show-icon>
        <template #default><el-button link type="primary" @click="loadTask">刷新到最新版本</el-button></template>
      </el-alert>

      <section class="task-overview" aria-label="任务概览">
        <article><el-icon><User /></el-icon><div><span>负责人</span><strong>{{ task.assignee.display_name }}</strong></div></article>
        <article><el-icon><AlarmClock /></el-icon><div><span>截止时间</span><strong :class="{ danger: task.display_status === 'OVERDUE' }">{{ formatTaskDate(task.due_at) }}</strong></div></article>
        <article><el-icon><Tickets /></el-icon><div><span>任务类型</span><strong>{{ task.task_type_display }}</strong></div></article>
        <article><el-icon><Bell /></el-icon><div><span>提醒规则</span><strong>{{ task.reminders.length ? `${task.reminders.length} 条提醒` : '未设置' }}</strong></div></article>
        <article><el-icon><OfficeBuilding /></el-icon><div><span>关联客户</span><strong>{{ task.customer?.name || '—' }}</strong></div></article>
        <article><el-icon><Link /></el-icon><div><span>来源对象</span><strong>{{ task.source ? `${task.source.code ? `${task.source.code} · ` : ''}${task.source.title}` : '—' }}</strong></div></article>
        <article><el-icon><Calendar /></el-icon><div><span>创建时间</span><strong>{{ formatTaskDate(task.created_at) }}</strong></div></article>
        <article><el-icon><CircleCheck /></el-icon><div><span>任务状态</span><strong>{{ statusLabel(task) }}</strong></div></article>
      </section>

      <main class="detail-layout">
        <section class="surface task-content">
          <section class="task-content__description">
            <div class="section-title"><h2>任务说明</h2><span>{{ task.task_type_display }}</span></div>
            <p>{{ task.description || '未填写任务说明。' }}</p>
          </section>
          <section class="task-content__checklist">
            <div class="section-title"><h2>检查清单</h2><span>{{ task.checklist_progress.completed }} / {{ task.checklist_progress.total }}</span></div>
            <div v-if="task.checklist_items.length" class="checklist">
              <label v-for="item in task.checklist_items" :key="item.id" :class="{ completed: item.is_completed }">
                <el-checkbox :model-value="item.is_completed" :disabled="closed || !canChange || acting" @change="toggleChecklist(item.id, Boolean($event))" />
                <span>{{ item.content }}</span><small>{{ item.completed_at ? formatTaskDate(item.completed_at) : '待完成' }}</small>
              </label>
            </div>
            <div v-else class="empty-state">暂无检查项</div>
          </section>
          <section class="task-content__attachments">
            <div class="section-title"><h2>来源附件</h2><span>{{ task.source_attachments.length }} 个</span></div>
            <div v-if="task.source_attachments.length" class="files"><article v-for="file in task.source_attachments" :key="file.id"><div><strong>{{ file.name }}</strong><small>{{ file.content_type }} · {{ Math.ceil(file.size_bytes / 1024) }} KB · 受控附件</small></div><div><a :href="file.preview_url" target="_blank" rel="noopener">预览</a><a :href="file.download_url">下载</a></div></article></div>
            <div v-else class="attachment-empty">当前来源对象没有可展示的附件</div>
          </section>
        </section>

        <aside class="detail-aside">
          <section class="surface activity-card">
            <div class="section-title"><h2>活动记录</h2><span>全部</span></div>
            <p v-if="activityLoading" role="status">正在加载任务动态…</p>
            <el-alert v-else-if="activityErrorMessage" class="activity-error" type="error" :title="activityErrorMessage" :closable="false"><template #default><el-button link type="primary" @click="loadActivities">重试</el-button></template></el-alert>
            <div v-else-if="activities.length" class="timeline"><article v-for="activity in activities" :key="`${activity.kind}-${activity.id}`"><i /><time>{{ formatTaskDate(activity.occurred_at) }}</time><div><strong>{{ activityTitle(activity) }}</strong><p v-if="activity.summary">{{ activity.summary }}</p><small>{{ activity.actor || '系统' }}</small></div></article></div>
            <div v-else class="empty-state">暂无真实活动记录</div>
          </section>
          <section class="surface context-card">
            <div class="section-title"><h2>关联上下文</h2><el-icon><Link /></el-icon></div>
            <dl><div><dt>客户</dt><dd>{{ task.customer?.name || '—' }}</dd></div><div><dt>来源对象</dt><dd>{{ task.source ? `${task.source.code ? `${task.source.code} · ` : ''}${task.source.title}` : '—' }}</dd></div><div><dt>下次检查</dt><dd>{{ formatTaskDate(task.next_check_at) }}</dd></div></dl>
            <el-button :disabled="!task.source?.open_url" @click="openSource">{{ task.source?.open_url ? '打开来源对象' : '来源入口暂不可用' }}</el-button>
          </section>
        </aside>
      </main>

      <TaskReassignDialog :model-value="dialog === 'reassign'" :task="task" :etag="etag" :options="options" @update:model-value="value => { if (!value) dialog = null }" @updated="acceptUpdate" />
      <TaskRescheduleDialog :model-value="dialog === 'reschedule'" :task="task" :etag="etag" @update:model-value="value => { if (!value) dialog = null }" @updated="acceptUpdate" />
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.task-detail {
  $page-bg: token.$crm-color-page;
  $surface: #fcfbf7;
  $border: #e5dfd5;
  $text: #1f1d18;
  $muted: #858078;
  $accent: #c7441d;

  min-width: 0;
  min-height: calc(100vh - 84px);
  margin: 0;
  padding: 26px 28px 28px;
  color: $text;
  background: $page-bg;
  font-family: token.$crm-font-body;

  .back-link {
    height: 21px;
    padding: 0;
    color: #746f68;
    font-size: 14px;
  }

  .detail-hero {
    height: 52px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 12px;

    &__main,
    &__badges {
      display: flex;
      align-items: center;
    }

    &__main {
      min-width: 0;
      gap: 14px;

      h1 {
        max-width: 800px;
        margin: 0;
        overflow: hidden;
        color: $text;
        font-family: token.$crm-font-display;
        font-size: 38px;
        font-weight: 600;
        line-height: 52px;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
    }

    &__badges {
      gap: 8px;
      flex: none;
    }
  }

  .actions {
    gap: 10px;
    flex: none;

    :deep(.el-button) {
      width: 100px;
      height: 42px;
      margin: 0;
      border-radius: 5px;
      font-size: 16px;
    }

    :deep(.el-button--primary) {
      width: 122px;
      border-color: $accent;
      background: $accent;
    }
  }

  .detail-subtitle {
    height: 24px;
    margin: 0;
    color: #817b74;
    font-size: 14px;
    line-height: 24px;
  }

  .conflict-alert {
    margin: 8px 0;
  }

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
    background: #65625d;
    font-size: 12px;

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

  .task-overview {
    height: 198px;
    box-sizing: border-box;
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    grid-template-rows: repeat(2, 62px);
    gap: 26px 0;
    margin-top: 18px;
    padding: 24px;
    border: 1px solid $border;
    border-radius: 5px;
    background: $surface;

    article {
      min-width: 0;
      display: grid;
      grid-template-columns: 22px minmax(0, 1fr);
      gap: 12px;
      align-items: center;
      padding-right: 20px;

      :deep(.el-icon) {
        color: #9a4a32;
        font-size: 22px;
      }

      div {
        min-width: 0;
        display: grid;
        gap: 8px;
      }

      span {
        color: $muted;
        font-size: 13px;
      }

      strong {
        overflow: hidden;
        color: #2c2924;
        font-size: 16px;
        font-weight: 600;
        text-overflow: ellipsis;
        white-space: nowrap;

        &.danger { color: #b53333; }
      }
    }
  }

  .detail-layout {
    min-height: 602px;
    display: grid;
    grid-template-columns: minmax(0, 886px) minmax(0, 728px);
    gap: 20px;
    margin-top: 20px;
  }

  .surface {
    box-sizing: border-box;
    border: 1px solid $border;
    border-radius: 5px;
    background: #fffefb;
  }

  .section-title {
    height: auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0;
    border: 0;

    h2 {
      margin: 0;
      color: #26231f;
      font-family: token.$crm-font-display;
      font-size: 20px;
      font-weight: 600;
    }

    span {
      color: $muted;
      font-size: 13px;
    }

    :deep(.el-icon) {
      color: $muted;
      font-size: 18px;
    }
  }

  .task-content {
    min-height: 602px;
    padding: 24px;
    overflow: visible;

    &__description {
      .section-title { height: 26px; }

      > p {
        min-height: 52px;
        margin: 20px 0 0;
        color: #504b44;
        font-size: 16px;
        line-height: 26px;
        white-space: pre-wrap;
      }
    }

    &__checklist {
      margin-top: 12px;

      .section-title { height: 26px; }
    }

    &__attachments {
      margin-top: 18px;
      padding-top: 18px;
      border-top: 1px solid #ece7df;

      .section-title { height: 26px; }
    }
  }

  .checklist {
    padding: 10px 0 0;

    label {
      height: 44px;
      min-height: 44px;
      display: grid;
      grid-template-columns: 28px minmax(0, 1fr) 150px;
      align-items: center;
      border-bottom: 1px solid #ece8e1;
      color: #3d3934;
      font-size: 16px;

      &.completed span {
        color: #8b857e;
        text-decoration: line-through;
      }
    }

    small {
      color: #8b857e;
      font-size: 12px;
      text-align: right;
    }
  }

  .files {
    padding: 14px 0 0;

    article {
      min-height: 74px;
      box-sizing: border-box;
      padding: 0 16px;
      border: 1px solid $border;
      border-radius: 4px;
      background: #faf8f3;
    }
  }

  .attachment-empty {
    height: 74px;
    display: grid;
    place-items: center;
    margin-top: 14px;
    border: 1px dashed #dcd6cc;
    border-radius: 4px;
    color: #918b84;
    background: #faf8f3;
    font-size: 14px;
  }

  .detail-aside {
    min-height: 602px;
    display: grid;
    grid-template-rows: auto 200px;
    align-content: start;
    gap: 20px;
  }

  .activity-card {
    min-height: 382px;
    padding: 0 24px;
    overflow: visible;

    > .section-title { height: 62px; }
  }

  .timeline {
    padding: 0;

    article {
      position: relative;
      min-height: 64px;
      display: grid;
      grid-template-columns: 10px 150px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
      padding-top: 6px;

      &:not(:last-child)::before {
        position: absolute;
        top: 16px;
        bottom: -6px;
        left: 4px;
        width: 1px;
        content: '';
        background: #dcd6ce;
      }

      i {
        z-index: 1;
        width: 10px;
        height: 10px;
        margin-top: 4px;
        border-radius: 50%;
        background: $accent;
      }

      time {
        color: #8b857e;
        font-size: 12px;
        line-height: 18px;
      }

      strong {
        font-size: 14px;
        line-height: 18px;
      }

      p {
        max-width: 100%;
        margin: 3px 0 0;
        color: #666059;
        font-size: 12px;
        line-height: 18px;
        overflow-wrap: anywhere;
        white-space: normal;
      }

      small {
        display: block;
        margin-top: 2px;
        color: #928b83;
        font-size: 11px;
      }
    }
  }

  .context-card {
    position: relative;
    height: 200px;
    padding: 0 24px;

    > .section-title { height: 56px; }

    dl {
      display: grid;
      grid-template-columns: 1.2fr 1.2fr 1fr;
      gap: 18px;
      margin: 0;
      padding: 10px 210px 0 0;

      div { min-width: 0; }
      dt { color: $muted; font-size: 12px; }
      dd { margin: 6px 0 0; overflow: hidden; color: #332f2c; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
    }

    > :deep(.el-button) {
      position: absolute;
      right: 24px;
      bottom: 24px;
      width: 180px;
      height: 42px;
      margin: 0;
      border-radius: 4px;
    }
  }

  .empty-state {
    min-height: 80px;
    display: grid;
    place-items: center;
    color: #918b84;
    font-size: 14px;
  }
}
</style>
