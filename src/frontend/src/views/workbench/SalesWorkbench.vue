<script setup lang="ts">
import WorkbenchMetricCard from '@/components/workbench/WorkbenchMetricCard.vue'
import WorkbenchSection from '@/components/workbench/WorkbenchSection.vue'
import { createMilestoneDemo, salesFunnelDemo, workbenchReferenceDate } from '@/data/workbenchDemoData'
import type {
  WorkbenchLoadState,
  WorkbenchMetric,
  WorkbenchRiskItem,
  WorkbenchTask,
} from '@/types/workbench'

defineProps<{
  metrics: WorkbenchMetric[]
  tasks: WorkbenchTask[]
  risks: WorkbenchRiskItem[]
  taskState: WorkbenchLoadState
  riskState: WorkbenchLoadState
  loadingMetrics: boolean
  canAddCommunication: boolean
  canAddInquiry: boolean
}>()

const emit = defineEmits<{
  communication: []
  inquiry: []
  task: [task: WorkbenchTask]
  risk: [risk: WorkbenchRiskItem]
  retry: []
}>()

const milestones = createMilestoneDemo()
const componentReferenceDate = workbenchReferenceDate()
const referenceDateKey = componentReferenceDate.toISOString().slice(0, 10)
const referenceTime = componentReferenceDate.getTime()

function stateForSection(state: WorkbenchLoadState): 'READY' | 'LOADING' | 'EMPTY' | 'ERROR' {
  if (state === 'LOADING') return 'LOADING'
  if (state === 'ERROR') return 'ERROR'
  if (state === 'EMPTY') return 'EMPTY'
  return 'READY'
}

function formatDueAt(value: string): string {
  const date = new Date(value)
  return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
</script>

<template>
  <div class="sales-workbench">
    <div class="sales-workbench__metrics">
      <WorkbenchMetricCard v-for="metric in metrics" :key="metric.key" :item="metric" :loading="loadingMetrics && metric.origin === 'LIVE'" />
    </div>

    <div class="sales-workbench__main-grid">
      <WorkbenchSection
        class="sales-workbench__tasks"
        title="今日工作清单"
        subtitle="按优先级和截止时间排序"
        :state="stateForSection(taskState)"
        error-message="任务接口加载失败，未使用演示任务替代"
        @retry="emit('retry')"
      >
        <template #actions>
          <div class="task-tabs" aria-label="任务分类">
            <span class="is-active">全部 {{ tasks.length }}</span>
            <span>逾期 {{ tasks.filter((item) => new Date(item.due_at).getTime() < referenceTime).length }}</span>
            <span>今天 {{ tasks.filter((item) => item.due_at.slice(0, 10) === referenceDateKey).length }}</span>
          </div>
        </template>
        <div class="work-table-wrap">
          <table class="work-table">
            <thead>
              <tr><th>任务</th><th>客户</th><th>截止</th><th>状态</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="task in tasks.slice(0, 5)" :key="task.id">
                <td><span class="work-table__title">{{ task.title }}</span></td>
                <td>{{ task.source_label || '一般任务' }}</td>
                <td :class="{ 'is-overdue': new Date(task.due_at).getTime() < referenceTime }">{{ formatDueAt(task.due_at) }}</td>
                <td><span class="priority-tag" :class="`priority-tag--${task.priority.toLowerCase()}`">{{ task.priority_display }}</span></td>
                <td><button type="button" class="text-button" @click="emit('task', task)">{{ task.status === 'PENDING' ? '处理' : '查看' }}</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </WorkbenchSection>

      <WorkbenchSection class="sales-workbench__funnel" title="销售漏斗" subtitle="本月金额与转化" demo>
        <template #actions><span class="currency-tag">USD</span></template>
        <div class="funnel-list">
          <div v-for="(item, index) in salesFunnelDemo" :key="item.label" class="funnel-row">
            <div class="funnel-row__meta"><span>{{ item.label }}</span><small>{{ [24, 16, 11, 6, 4][index] }} 个</small><strong>{{ item.value }}</strong></div>
            <div class="funnel-row__track"><span :style="{ width: `${item.ratio}%`, background: item.color }" /></div>
          </div>
          <div class="funnel-conversion"><span>询盘 → 预计成交转化率</span><strong>16.7%</strong></div>
        </div>
      </WorkbenchSection>
    </div>

    <div class="sales-workbench__lower-grid">
      <WorkbenchSection
        class="sales-workbench__risk"
        title="重点客户与风险"
        subtitle="优先处理高价值与异常客户"
        :state="stateForSection(riskState)"
        error-message="客户风险数据加载失败"
        @retry="emit('retry')"
      >
        <div class="risk-list">
          <button v-for="risk in risks.slice(0, 4)" :key="risk.id" type="button" class="risk-row" @click="emit('risk', risk)">
            <span class="risk-row__dot" />
            <span class="risk-row__main"><strong>{{ risk.customer }}</strong><small>{{ risk.reason }}</small></span>
            <span class="risk-row__level">{{ risk.level }}</span>
            <span class="risk-row__date">{{ risk.lastFollowUp }}</span>
          </button>
        </div>
      </WorkbenchSection>

      <WorkbenchSection class="sales-workbench__milestones" title="近期订单里程碑" subtitle="事实由订单模块确认，CRM 展示与催办" demo>
        <div class="milestone-list">
          <div v-for="item in milestones" :key="item.title" class="milestone-row">
            <span class="milestone-row__icon">{{ milestones.indexOf(item) + 1 }}</span>
            <span class="milestone-row__main"><strong>{{ item.title }}</strong><small>{{ item.customer }}</small></span>
            <span class="milestone-row__date">{{ item.date }}</span>
            <span class="milestone-row__status">{{ item.status }}</span>
          </div>
        </div>
      </WorkbenchSection>
    </div>
  </div>
</template>

<style scoped lang="scss">
.sales-workbench { display: flex; flex-direction: column; gap: 16px; }
.sales-workbench__metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.sales-workbench__main-grid,
.sales-workbench__lower-grid { display: grid; gap: 12px; }
.sales-workbench__main-grid { grid-template-columns: minmax(0, 1038fr) minmax(0, 582fr); }
.sales-workbench__lower-grid { grid-template-columns: minmax(0, 790fr) minmax(0, 830fr); }
.sales-workbench__tasks,
.sales-workbench__funnel { height: 356px; }
.sales-workbench__risk,
.sales-workbench__milestones { height: 310px; }
.task-tabs { display: flex; gap: 10px; }
.task-tabs span { min-width: 76px; padding: 5px 10px; border-radius: 6px; color: #71717a; background: #f4f4f5; font-size: 12px; text-align: center; }
.task-tabs .is-active { color: #1478db; background: #eaf4ff; }
.currency-tag { padding: 5px 16px; border-radius: 6px; color: #71717a; background: #f4f4f5; font-size: 12px; }

.work-table-wrap { height: 100%; overflow: hidden; }
.work-table { width: 100%; border-collapse: collapse; table-layout: fixed; color: #3f3f46; font-size: 13px; }
.work-table th { height: 42px; padding: 0 16px; border-bottom: 1px solid #e4e4e7; color: #71717a; background: #f4f5f7; font-weight: 500; text-align: left; }
.work-table td { height: 46px; padding: 0 16px; overflow: hidden; border-bottom: 1px solid #e4e4e7; text-overflow: ellipsis; white-space: nowrap; }
.work-table tr:last-child td { border-bottom: 0; }
.work-table th:nth-child(1) { width: 31%; }
.work-table th:nth-child(2) { width: 24%; }
.work-table th:nth-child(3) { width: 19%; }
.work-table th:nth-child(4) { width: 14%; }
.work-table th:nth-child(5) { width: 12%; }
.work-table__title { color: #18181b; font-weight: 500; }
.work-table .is-overdue { color: #dc2626; }
.priority-tag { display: inline-flex; padding: 2px 8px; border-radius: 999px; color: #52525b; background: #f4f4f5; font-size: 11px; line-height: 18px; }
.priority-tag--high, .priority-tag--urgent { color: #b91c1c; background: #fee2e2; }
.priority-tag--low { color: #52525b; background: #f4f4f5; }
.text-button { padding: 0; border: 0; color: #18181b; background: transparent; font-size: 13px; font-weight: 600; cursor: pointer; }

.funnel-list { height: 100%; display: flex; flex-direction: column; justify-content: center; gap: 10px; padding: 10px 20px 12px; }
.funnel-row__meta { display: grid; grid-template-columns: 90px 1fr auto; align-items: center; margin-bottom: 5px; color: #3f3f46; font-size: 12px; }
.funnel-row__meta small { color: #8b8f97; }
.funnel-row__meta strong { color: #18181b; font-size: 12px; }
.funnel-row__track { height: 10px; overflow: hidden; border-radius: 999px; background: #f4f4f5; }
.funnel-row__track span { display: block; height: 100%; border-radius: inherit; }
.funnel-conversion { display: flex; align-items: center; justify-content: space-between; color: #8b8f97; font-size: 11px; }
.funnel-conversion strong { color: #008a33; font-size: 18px; }

.risk-list, .milestone-list { height: 100%; padding: 6px 16px; }
.risk-row, .milestone-row { width: 100%; height: 55px; display: flex; align-items: center; gap: 12px; padding: 0; border: 0; border-bottom: 1px solid #e4e4e7; color: #3f3f46; background: transparent; text-align: left; }
.risk-row { cursor: pointer; }
.risk-row:last-child, .milestone-row:last-child { border-bottom: 0; }
.risk-row__dot { width: 8px; height: 8px; flex: none; border-radius: 50%; background: #dc2626; }
.risk-row__main, .milestone-row__main { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 3px; }
.risk-row__main strong, .milestone-row__main strong { overflow: hidden; color: #18181b; font-size: 13px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.risk-row__main small, .milestone-row__main small { overflow: hidden; color: #71717a; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.risk-row__level { flex: none; padding: 2px 8px; border-radius: 999px; color: #b91c1c; background: #fee2e2; font-size: 11px; }
.risk-row__date, .milestone-row__date { width: 72px; flex: none; color: #71717a; font-size: 11px; text-align: right; }
.milestone-row__icon { width: 28px; height: 28px; flex: none; display: grid; place-items: center; border-radius: 6px; color: #1478db; background: #eaf4ff; font-size: 12px; }
.milestone-row__status { width: 55px; flex: none; color: #52525b; font-size: 11px; text-align: right; }

@media (max-width: 1599px) and (min-width: 769px) {
  .sales-workbench__main-grid { grid-template-columns: minmax(0, 820fr) minmax(0, 496fr); }
  .sales-workbench__lower-grid { grid-template-columns: minmax(0, 650fr) minmax(0, 666fr); }
  .sales-workbench__risk, .sales-workbench__milestones { height: 270px; }
  .risk-row, .milestone-row { height: 42px; }
}

@media (max-width: 1100px) {
  .sales-workbench__metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sales-workbench__main-grid, .sales-workbench__lower-grid { grid-template-columns: 1fr; }
  .sales-workbench__tasks, .sales-workbench__funnel, .sales-workbench__risk, .sales-workbench__milestones { height: auto; min-height: 300px; }
}

@media (max-width: 600px) {
  .sales-workbench__metrics { grid-template-columns: 1fr; }
  .work-table { min-width: 760px; }
  .work-table-wrap { overflow-x: auto; }
}
</style>
