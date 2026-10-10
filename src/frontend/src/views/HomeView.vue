<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { ElMessage } from 'element-plus'

import { fetchCustomer, fetchCustomers, fetchCustomerStats } from '@/api/customers'
import { fetchWorkbenchDashboard, fetchWorkbenchTask, fetchWorkbenchTasks, transitionWorkbenchTask } from '@/api/workbench'
import ResizableDrawerHandle from '@/components/ResizableDrawerHandle.vue'
import WorkbenchQuickDrawer from '@/components/workbench/WorkbenchQuickDrawer.vue'
import { managerDemoMetrics, salesDemoCounts, workbenchReferenceDate } from '@/data/workbenchDemoData'
import { useAuthStore } from '@/stores/auth'
import type { WorkbenchLoadState, WorkbenchMetric, WorkbenchRiskItem, WorkbenchTask } from '@/types/workbench'
import {
  isTaskDueToday,
  isTaskOverdue,
  isUnauthorizedWorkbenchError,
  mergeWorkbenchTasks,
  resolveWorkbenchMode,
  workbenchErrorMessage,
} from '@/utils/workbench'
import ManagerWorkbench from '@/views/workbench/ManagerWorkbench.vue'
import SalesWorkbench from '@/views/workbench/SalesWorkbench.vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { user } = storeToRefs(authStore)
const referenceDate = workbenchReferenceDate()
const mode = computed(() => resolveWorkbenchMode(user.value))
const conciseDateText = computed(() => {
  const weekday = new Intl.DateTimeFormat('zh-CN', { weekday: 'short' }).format(referenceDate)
  return `${referenceDate.getFullYear()} 年 ${referenceDate.getMonth() + 1} 月 ${referenceDate.getDate()} 日 · ${weekday}`
})
const employeeId = computed(() => user.value?.employee?.id || null)

const dashboardState = ref<WorkbenchLoadState>('LOADING')
const taskState = ref<WorkbenchLoadState>('LOADING')
const riskState = ref<WorkbenchLoadState>('LOADING')
const dashboardError = ref('')
const tasks = ref<WorkbenchTask[]>([])
const risks = ref<WorkbenchRiskItem[]>([])
const managerRiskCount = ref<number | null>(null)
const lastSuccessfulAt = ref<Date | null>(null)
const communicationDrawerVisible = ref(false)
const inquiryDrawerVisible = ref(false)
const taskDrawerVisible = ref(false)
const taskDrawerLoading = ref(false)
const taskActionLoading = ref(false)
const selectedTask = ref<(WorkbenchTask & { description?: string }) | null>(null)
const selectedTaskEtag = ref<string | null>(null)
const customerNameCache = new Map<string, string>()

const canAddCommunication = computed(() => authStore.hasPermission('crm.add_customercommunication'))
const canAddInquiry = computed(() => authStore.hasPermission('inquiries.add_inquiry'))
const canChangeTask = computed(() => authStore.hasPermission('workflow.change_businesstask'))
const todayTaskCount = computed(() => tasks.value.filter((task) => isTaskDueToday(task, referenceDate)).length)
const overdueTaskCount = computed(() => tasks.value.filter((task) => isTaskOverdue(task, referenceDate)).length)

const salesMetrics = computed<WorkbenchMetric[]>(() => [
  { key: 'today', label: '今日待办', value: String(todayTaskCount.value), note: '来自任务中心', tone: 'neutral', origin: 'LIVE' },
  { key: 'overdue', label: '逾期任务', value: String(overdueTaskCount.value), note: '请优先处理', tone: 'neutral', origin: 'LIVE' },
  { key: 'inquiry-reply', label: '待回复询盘', value: String(salesDemoCounts.pendingInquiryReplies), note: '当前无准确接口口径', tone: 'neutral', origin: 'DEMO' },
  { key: 'quotation-feedback', label: '报价待反馈', value: String(salesDemoCounts.pendingQuotationFeedback), note: '当前无准确接口口径', tone: 'warning', origin: 'DEMO' },
  { key: 'sample-feedback', label: '样品待反馈', value: String(salesDemoCounts.pendingSampleFeedback), note: '当前无准确接口口径', tone: 'neutral', origin: 'DEMO' },
])

const managerMetrics = computed<WorkbenchMetric[]>(() => [
  { key: 'sales', label: '本月销售额', value: managerDemoMetrics.monthlySales, note: '较上月 +12.6%', tone: 'neutral', origin: 'DEMO' },
  { key: 'margin', label: '团队毛利率', value: managerDemoMetrics.marginRate, note: '较目标 +1.7%', tone: 'neutral', origin: 'DEMO' },
  { key: 'inquiries', label: '新增询盘', value: managerDemoMetrics.newInquiries, note: '较上月 +8.2%', tone: 'neutral', origin: 'DEMO' },
  { key: 'timeliness', label: '报价及时率', value: managerDemoMetrics.quotationTimeliness, note: '目标 90%', tone: 'neutral', origin: 'DEMO' },
  { key: 'risks', label: '风险客户', value: managerRiskCount.value === null ? '—' : String(managerRiskCount.value), note: '来自客户活跃度', tone: 'neutral', origin: 'LIVE' },
])
const taskMetricLoading = computed(() => taskState.value === 'LOADING')
const managerMetricLoading = computed(() => riskState.value === 'LOADING')

function handleWorkbenchError(error: unknown, action: string): string {
  if (isUnauthorizedWorkbenchError(error)) {
    authStore.clearAuthentication()
    void router.replace({ name: 'login', query: { redirect: route.fullPath } })
  }
  return workbenchErrorMessage(error, action)
}

async function resolveTaskSourceLabels(items: WorkbenchTask[]) {
  const directCustomerTasks = items.filter((task) => task.source?.type === 'CUSTOMER').slice(0, 5)
  await Promise.all(directCustomerTasks.map(async (task) => {
    const source = task.source
    if (!source) return
    if (!customerNameCache.has(source.id)) {
      try {
        const customer = await fetchCustomer(source.id)
        customerNameCache.set(source.id, customer.data.account_name)
      } catch {
        customerNameCache.set(source.id, '客户数据不可用')
      }
    }
    task.source_label = customerNameCache.get(source.id)
  }))
  const labels: Record<string, string> = { COMMUNICATION: '客户沟通', INQUIRY: '询盘', QUOTATION_VERSION: '报价', SAMPLE_REQUEST: '样品' }
  for (const task of items) {
    if (!task.source_label && task.source) task.source_label = labels[task.source.type] || '业务任务'
  }
}

async function loadDashboard() {
  if (!mode.value) { dashboardState.value = 'FORBIDDEN'; return }
  dashboardState.value = 'LOADING'
  dashboardError.value = ''
  try {
    await fetchWorkbenchDashboard(mode.value)
    dashboardState.value = 'READY'
    lastSuccessfulAt.value = new Date()
  } catch (error) {
    dashboardState.value = 'ERROR'
    dashboardError.value = handleWorkbenchError(error, '工作台汇总加载')
  }
}

async function loadTasks() {
  if (mode.value !== 'SALES' || !authStore.hasPermission('workflow.view_businesstask')) {
    tasks.value = []
    taskState.value = mode.value === 'SALES' ? 'EMPTY' : 'READY'
    return
  }
  taskState.value = 'LOADING'
  try {
    const [pending, inProgress] = await Promise.all([fetchWorkbenchTasks('PENDING'), fetchWorkbenchTasks('IN_PROGRESS')])
    const merged = mergeWorkbenchTasks(pending.data, inProgress.data)
    await resolveTaskSourceLabels(merged.slice(0, 5))
    tasks.value = merged
    taskState.value = merged.length ? 'READY' : 'EMPTY'
  } catch (error) {
    tasks.value = []
    taskState.value = 'ERROR'
    handleWorkbenchError(error, '任务加载')
  }
}

function riskDate(value: string | null): string {
  if (!value) return '从未跟进'
  const date = new Date(value)
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

async function loadRisks() {
  if (!mode.value) { riskState.value = 'FORBIDDEN'; return }
  riskState.value = 'LOADING'
  try {
    const [customers, stats] = await Promise.all([
      fetchCustomers({ activity_status: 'HIGH_RISK', archived: 'false', ordering: '-updated_at', page: 1, page_size: 4 }),
      fetchCustomerStats(),
    ])
    risks.value = customers.data.map((customer) => ({
      id: customer.id,
      customer: customer.account_name,
      reason: customer.activity?.reason || '客户活跃度被标记为高风险',
      level: '高风险',
      lastFollowUp: riskDate(customer.last_contact_at),
      source: customer,
    }))
    managerRiskCount.value = stats.high_risk
    riskState.value = risks.value.length ? 'READY' : 'EMPTY'
  } catch (error) {
    risks.value = []
    managerRiskCount.value = null
    riskState.value = 'ERROR'
    handleWorkbenchError(error, '风险客户加载')
  }
}

async function refreshWorkbench() {
  if (!mode.value) return
  await Promise.all([loadDashboard(), loadTasks(), loadRisks()])
}

async function openTask(task: WorkbenchTask) {
  taskDrawerVisible.value = true
  taskDrawerLoading.value = true
  selectedTask.value = task
  selectedTaskEtag.value = null
  try {
    const detail = await fetchWorkbenchTask(task.id)
    selectedTask.value = detail.data
    selectedTaskEtag.value = detail.etag
  } catch (error) { ElMessage.error(handleWorkbenchError(error, '任务详情加载')) }
  finally { taskDrawerLoading.value = false }
}

async function transitionTask() {
  const task = selectedTask.value
  const etag = selectedTaskEtag.value
  if (!task || !etag || taskActionLoading.value) return
  const action = task.status === 'PENDING' ? 'start' : 'complete'
  taskActionLoading.value = true
  try {
    await transitionWorkbenchTask(task.id, action, etag)
    ElMessage.success(action === 'start' ? '任务已开始' : '任务已完成')
    taskDrawerVisible.value = false
    await loadTasks()
  } catch (error) { ElMessage.error(handleWorkbenchError(error, '任务状态更新')) }
  finally { taskActionLoading.value = false }
}

function openRisk(risk: WorkbenchRiskItem) { void router.push({ name: 'customer-detail', params: { customerId: risk.id } }) }
function showUnavailable(action: string) { ElMessage.info(`${action}模块尚未接入`) }

onMounted(() => {
  if (!mode.value) {
    dashboardState.value = 'FORBIDDEN'; taskState.value = 'FORBIDDEN'; riskState.value = 'FORBIDDEN'; return
  }
  void refreshWorkbench()
})
</script>

<template>
  <div class="workbench-page" data-workbench-page :data-workbench-mode="mode || 'FORBIDDEN'">
    <section v-if="!mode" class="workbench-forbidden" role="status">
      <div class="workbench-forbidden__icon">!</div>
      <h1>暂无工作台访问权限</h1>
      <p>当前账号缺少“查看客户”权限。系统不会回退到演示客户数据，请联系管理员配置权限。</p>
    </section>

    <template v-else>
      <header class="workbench-page__heading">
        <div>
          <h1>{{ mode === 'MANAGER' ? '主管工作台' : '业务员工作台' }}</h1>
          <p v-if="mode === 'SALES'">{{ conciseDateText }}｜聚焦今天最重要的客户动作</p>
          <p v-else>外贸一组 · {{ conciseDateText.replace(' · ', ' ') }}｜团队目标、负载、SLA 与风险</p>
        </div>
        <div class="workbench-page__actions">
          <template v-if="mode === 'SALES'">
            <button v-if="canAddCommunication" type="button" class="page-action" @click="communicationDrawerVisible = true">记录沟通</button>
            <button v-if="canAddInquiry" type="button" class="page-action page-action--primary" @click="inquiryDrawerVisible = true">新建询盘</button>
          </template>
          <template v-else>
            <button type="button" class="page-action" aria-disabled="true" @click="showUnavailable('导出日报')">导出日报</button>
            <button type="button" class="page-action page-action--primary" aria-disabled="true" @click="showUnavailable('分配询盘')">分配询盘</button>
          </template>
        </div>
      </header>
      <div v-if="dashboardState === 'ERROR'" class="workbench-inline-error" role="alert">
        <span>工作台汇总接口异常：{{ dashboardError }}。局部真实数据不会自动替换为演示值。</span>
        <small v-if="lastSuccessfulAt">上次成功更新：{{ lastSuccessfulAt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</small>
      </div>

      <SalesWorkbench
        v-if="mode === 'SALES'"
        :metrics="salesMetrics" :tasks="tasks" :risks="risks" :task-state="taskState" :risk-state="riskState"
        :loading-metrics="taskMetricLoading" :can-add-communication="canAddCommunication" :can-add-inquiry="canAddInquiry"
        @communication="communicationDrawerVisible = true" @inquiry="inquiryDrawerVisible = true" @task="openTask" @risk="openRisk" @retry="refreshWorkbench"
      />
      <ManagerWorkbench
        v-else :metrics="managerMetrics" :risks="risks" :risk-state="riskState" :loading-metrics="managerMetricLoading"
        @unavailable="showUnavailable" @risk="openRisk" @retry="refreshWorkbench"
      />
    </template>

    <WorkbenchQuickDrawer v-if="mode === 'SALES'" v-model="communicationDrawerVisible" action="COMMUNICATION" :employee-id="employeeId" @saved="refreshWorkbench" />
    <WorkbenchQuickDrawer v-if="mode === 'SALES'" v-model="inquiryDrawerVisible" action="INQUIRY" :employee-id="employeeId" @saved="refreshWorkbench" />

    <ElDrawer v-model="taskDrawerVisible" title="任务详情" size="420px" destroy-on-close append-to-body>
      <ResizableDrawerHandle />
      <div v-loading="taskDrawerLoading" class="task-detail">
        <template v-if="selectedTask">
          <h2>{{ selectedTask.title }}</h2>
          <dl>
            <div><dt>状态</dt><dd>{{ selectedTask.status_display }}</dd></div>
            <div><dt>优先级</dt><dd>{{ selectedTask.priority_display }}</dd></div>
            <div><dt>截止时间</dt><dd>{{ new Date(selectedTask.due_at).toLocaleString('zh-CN') }}</dd></div>
            <div><dt>说明</dt><dd>{{ selectedTask.description || '暂无说明' }}</dd></div>
          </dl>
        </template>
      </div>
      <template #footer>
        <ElButton @click="taskDrawerVisible = false">关闭</ElButton>
        <ElButton v-if="selectedTask && canChangeTask && ['PENDING', 'IN_PROGRESS'].includes(selectedTask.status)" type="primary" :loading="taskActionLoading" :disabled="!selectedTaskEtag" @click="transitionTask">
          {{ selectedTask.status === 'PENDING' ? '开始处理' : '标记完成' }}
        </ElButton>
      </template>
    </ElDrawer>
  </div>
</template>

<style lang="scss" scoped>
.workbench-page { min-width: 0; color: #18181b; }
.workbench-page__heading { height: 72px; display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding-top: 0; }
.workbench-page__heading h1 { margin: 0; color: #27272a; font-size: 28px; font-weight: 700; line-height: 32px; letter-spacing: -.02em; }
.workbench-page__heading p { margin: 0; color: #71717a; font-size: 13px; line-height: 20px; }
.workbench-page__actions { display: flex; gap: 12px; }
.page-action { min-width: 104px; height: 32px; padding: 0 16px; border: 1px solid #d4d4d8; border-radius: 8px; color: #3f3f46; background: #fff; font-size: 13px; font-weight: 500; cursor: pointer; }
.page-action--primary { border-color: #18181b; color: #fff; background: #18181b; }
.workbench-inline-error { min-height: 40px; display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; padding: 8px 12px; border: 1px solid #fecaca; border-radius: 8px; color: #b91c1c; background: #fef2f2; font-size: 12px; }
.workbench-inline-error small { flex: none; color: #71717a; }
.workbench-forbidden { min-height: 560px; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px; border: 1px solid #e4e4e7; border-radius: 8px; background: #fff; text-align: center; }
.workbench-forbidden__icon { width: 48px; height: 48px; display: grid; place-items: center; border-radius: 50%; color: #71717a; background: #f4f4f5; font-size: 22px; font-weight: 700; }
.workbench-forbidden h1 { margin: 18px 0 8px; font-size: 20px; }
.workbench-forbidden p { max-width: 520px; margin: 0; color: #71717a; font-size: 13px; line-height: 22px; }
.task-detail { min-height: 260px; }
.task-detail h2 { margin: 0 0 20px; font-size: 18px; }
.task-detail dl { margin: 0; }
.task-detail dl div { display: grid; grid-template-columns: 76px 1fr; gap: 12px; padding: 12px 0; border-bottom: 1px solid #f4f4f5; }
.task-detail dt { color: #71717a; }
.task-detail dd { margin: 0; color: #3f3f46; line-height: 22px; }
@media (max-width: 768px) {
  .workbench-page__heading { height: auto; margin-bottom: 16px; }
  .workbench-page__heading h1 { font-size: 20px; }
  .workbench-page__heading p { max-width: 230px; }
  .workbench-inline-error { align-items: flex-start; flex-direction: column; }
}
</style>
