<script setup lang="ts">
import WorkbenchMetricCard from '@/components/workbench/WorkbenchMetricCard.vue'
import WorkbenchSection from '@/components/workbench/WorkbenchSection.vue'
import { slaDemo, teamLoadDemo, teamPerformanceDemo } from '@/data/workbenchDemoData'
import type { WorkbenchLoadState, WorkbenchMetric, WorkbenchRiskItem } from '@/types/workbench'

defineProps<{
  metrics: WorkbenchMetric[]
  risks: WorkbenchRiskItem[]
  riskState: WorkbenchLoadState
  loadingMetrics: boolean
}>()

const emit = defineEmits<{
  unavailable: [action: string]
  risk: [risk: WorkbenchRiskItem]
  retry: []
}>()

function stateForSection(state: WorkbenchLoadState): 'READY' | 'LOADING' | 'EMPTY' | 'ERROR' {
  if (state === 'LOADING') return 'LOADING'
  if (state === 'ERROR') return 'ERROR'
  if (state === 'EMPTY') return 'EMPTY'
  return 'READY'
}
</script>

<template>
  <div class="manager-workbench">
    <div class="manager-workbench__metrics">
      <WorkbenchMetricCard v-for="metric in metrics" :key="metric.key" :item="metric" :loading="loadingMetrics && metric.origin === 'LIVE'" />
    </div>

    <div class="manager-workbench__main-grid">
      <WorkbenchSection class="manager-workbench__performance" title="团队绩效" subtitle="按销售额、毛利和跟进质量综合查看" demo>
        <template #actions><span class="month-tag">本月</span></template>
        <div class="performance-table">
          <div class="performance-table__head"><span>排名</span><span>业务员</span><span>销售额</span><span>毛利率</span><span>询盘</span><span>按时跟进</span><span>状态</span></div>
          <div v-for="item in teamPerformanceDemo" :key="item.name" class="performance-row">
            <span>{{ item.rank }}</span><strong>{{ item.name }}</strong><span>{{ item.amount }}</span><span>{{ item.margin }}</span><span>{{ item.inquiries }}</span><span>{{ item.followUp }}</span>
            <span class="performance-status" :class="`is-${item.tone}`">{{ item.status }}</span>
          </div>
        </div>
      </WorkbenchSection>

      <WorkbenchSection class="manager-workbench__load" title="团队跟进负载" subtitle="未完成任务与可分配容量" demo>
        <div class="load-list">
          <div v-for="item in teamLoadDemo" :key="item.name" class="load-row">
            <div class="load-row__meta"><strong>{{ item.name }}</strong><span>任务 {{ item.current }} · 逾期 {{ item.overdue }}</span><em>{{ item.ratio }}%</em></div>
            <div class="load-row__track"><i :class="`is-${item.tone}`" :style="{ width: `${item.ratio}%` }" /></div>
          </div>
        </div>
      </WorkbenchSection>
    </div>

    <div class="manager-workbench__lower-grid">
      <WorkbenchSection class="manager-workbench__sla" title="询盘与跟进 SLA" subtitle="及时率下降时优先查看行动原因" demo>
        <div class="sla-grid">
          <article v-for="item in slaDemo" :key="item.label" class="sla-card" :class="`sla-card--${item.tone}`">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small>{{ item.note }}</small>
            <em>{{ item.badge }}</em>
          </article>
        </div>
        <div class="sla-suggestion">建议：将 4 条高价值新询盘分配给当前负载较低的业务员 D。</div>
      </WorkbenchSection>

      <WorkbenchSection
        class="manager-workbench__risk"
        title="风险与审批"
        subtitle="只展示授权范围内的敏感数据"
        demo
        :state="stateForSection(riskState)"
        error-message="客户风险数据加载失败"
        @retry="emit('retry')"
      >
        <div class="manager-risk-list">
          <div class="manager-risk-row"><strong>{{ risks[0]?.customer || '高价值客户逾期未跟进' }}</strong><span class="risk-badge is-danger">风险</span><button type="button" @click="risks[0] ? emit('risk', risks[0]) : emit('unavailable', '立即处理')">立即处理</button></div>
          <div class="manager-risk-row"><strong>询盘分配待确认</strong><span class="risk-badge is-info">待办</span><button type="button" aria-disabled="true" @click="emit('unavailable', '批量分配')">批量分配</button></div>
          <div class="manager-risk-row"><strong>报价超折扣待审批</strong><span class="risk-badge is-info">审批</span><button type="button" aria-disabled="true" @click="emit('unavailable', '查看审批')">查看审批</button></div>
          <div class="manager-risk-row"><strong>客户信用数据过期</strong><span class="risk-badge is-warning">过期</span><button type="button" aria-disabled="true" @click="emit('unavailable', '请求刷新')">请求刷新</button></div>
        </div>
      </WorkbenchSection>
    </div>
  </div>
</template>

<style scoped lang="scss">
.manager-workbench { display: flex; flex-direction: column; gap: 16px; }
.manager-workbench__metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.manager-workbench__main-grid, .manager-workbench__lower-grid { display: grid; gap: 12px; }
.manager-workbench__main-grid { grid-template-columns: minmax(0, 1040fr) minmax(0, 580fr); }
.manager-workbench__lower-grid { grid-template-columns: minmax(0, 1010fr) minmax(0, 610fr); }
.manager-workbench__performance, .manager-workbench__load { height: 362px; }
.manager-workbench__sla, .manager-workbench__risk { height: 304px; }
.month-tag { min-width: 62px; padding: 5px 12px; border-radius: 6px; color: #1478db; background: #eaf4ff; font-size: 12px; text-align: center; }

.performance-table { height: 100%; color: #52525b; font-size: 12px; }
.performance-table__head, .performance-row { display: grid; grid-template-columns: 5% 20% 17% 15% 13% 15% 15%; align-items: center; padding: 0 16px; }
.performance-table__head { height: 40px; border-bottom: 1px solid #e4e4e7; color: #71717a; background: #f4f5f7; }
.performance-row { height: 47px; border-bottom: 1px solid #e4e4e7; }
.performance-row:last-child { border-bottom: 0; }
.performance-row strong { color: #18181b; font-size: 13px; }
.performance-status { width: 76px; padding: 4px 8px; border-radius: 6px; color: #52525b; background: #f4f4f5; text-align: center; }
.performance-status.is-success { color: #008a33; background: #e9f9ef; }
.performance-status.is-warning { color: #d97706; background: #fff8e7; }
.performance-status.is-danger { color: #e11d2e; background: #feecef; }

.load-list { height: 100%; display: flex; flex-direction: column; justify-content: center; gap: 17px; padding: 14px 20px 18px; }
.load-row__meta { display: grid; grid-template-columns: 95px 1fr 40px; align-items: center; margin-bottom: 8px; color: #71717a; font-size: 12px; }
.load-row__meta strong { color: #18181b; font-size: 13px; }
.load-row__meta em { color: #18181b; font-style: normal; font-weight: 600; text-align: right; }
.load-row__track { height: 9px; overflow: hidden; border-radius: 999px; background: #f4f4f5; }
.load-row__track i { display: block; height: 100%; border-radius: inherit; background: #3f3f46; }
.load-row__track i.is-warning { background: #d97706; }
.load-row__track i.is-danger { background: #dc2626; }

.sla-grid { height: calc(100% - 70px); display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; align-items: stretch; padding: 14px 20px 8px; }
.sla-card { min-width: 0; display: flex; flex-direction: column; justify-content: center; padding: 14px 16px; border: 1px solid #e4e4e7; border-radius: 8px; background: #fafafa; }
.sla-card span { color: #52525b; font-size: 12px; }
.sla-card strong { margin-top: 8px; color: #18181b; font-size: 24px; line-height: 30px; }
.sla-card small { margin-top: 6px; color: #71717a; font-size: 11px; }
.sla-card em { width: 64px; margin-top: 10px; padding: 3px 8px; border-radius: 6px; color: #d97706; background: #fff8e7; font-size: 11px; font-style: normal; text-align: center; }
.sla-card--danger em { color: #e11d2e; background: #feecef; }
.sla-suggestion { height: 54px; display: flex; align-items: center; margin: 0 20px 16px; padding: 0 14px; border: 1px solid #cfe5ff; border-radius: 6px; color: #245b91; background: #edf6ff; font-size: 12px; }
.sla-card--warning strong { color: #d97706; }
.sla-card--danger strong { color: #dc2626; }
.sla-card--success strong { color: #15803d; }

.manager-risk-list { height: 100%; padding: 4px 20px; }
.manager-risk-row { width: 100%; height: 54px; display: grid; grid-template-columns: 1fr 76px 84px; align-items: center; gap: 12px; border-bottom: 1px solid #e4e4e7; color: #3f3f46; }
.manager-risk-row:last-child { border-bottom: 0; }
.manager-risk-row strong { color: #18181b; font-size: 13px; font-weight: 500; }
.manager-risk-row button { height: 30px; border: 1px solid #d4d4d8; border-radius: 7px; color: #3f3f46; background: #fff; font-size: 12px; cursor: pointer; }
.risk-badge { padding: 4px 8px; border-radius: 6px; font-size: 11px; text-align: center; }
.risk-badge.is-danger { color: #e11d2e; background: #feecef; }
.risk-badge.is-info { color: #1478db; background: #eaf4ff; }
.risk-badge.is-warning { color: #d97706; background: #fff8e7; }

@media (max-width: 1599px) and (min-width: 769px) {
  .manager-workbench__main-grid { grid-template-columns: minmax(0, 824fr) minmax(0, 492fr); }
  .manager-workbench__lower-grid { grid-template-columns: minmax(0, 840fr) minmax(0, 476fr); }
  .manager-workbench__sla, .manager-workbench__risk { height: 254px; }
  .manager-risk-row { height: 39px; }
  .sla-grid { gap: 8px; padding: 12px; }
  .sla-card { padding: 10px 12px; }
  .sla-card strong { font-size: 21px; }
}

@media (max-width: 1100px) {
  .manager-workbench__metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .manager-workbench__main-grid, .manager-workbench__lower-grid { grid-template-columns: 1fr; }
  .manager-workbench__performance, .manager-workbench__load, .manager-workbench__sla, .manager-workbench__risk { height: auto; min-height: 300px; }
  .sla-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 600px) {
  .manager-workbench__metrics, .sla-grid { grid-template-columns: 1fr; }
  .performance-table { min-width: 700px; overflow-x: auto; }
}
</style>
