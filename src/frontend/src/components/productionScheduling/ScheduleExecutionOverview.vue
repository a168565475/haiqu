<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { PlanCategory } from '@/types/productionScheduling'
import type { ScheduleInternalPlan, ScheduleOutsourcingOrderSummary, ScheduleProductExecution } from '@/types/scheduleExecution'
import { formatScheduleMoney, formatScheduleQuantity, formatScheduleUnitPrice, groupScheduleOutsourcingOrders, scheduleAmountReason } from '@/utils/scheduleExecution'
import WageSchemeDetailDialog from '@/views/workshop/wage-schemes/WageSchemeDetailDialog.vue'

const props = defineProps<{
  scheduleId: string
  productionTaskId: string
  productLineId: string
  summary: ScheduleProductExecution | null
  loading: boolean
  failed: boolean
  active: boolean
}>()
const router = useRouter()
const wageVisible = ref(false)
const wageSchemeId = ref<string | null>(null)
const outsourcingOrders = computed(() => groupScheduleOutsourcingOrders(props.summary?.outsourcing.allowed ? props.summary.outsourcing.records : []))
const categories: Record<PlanCategory, { label: string; path: string }> = {
  METAL: { label: '金工计划', path: '/workshop/plans/metalworking' },
  CUTTING: { label: '裁剪计划', path: '/workshop/plans/cutting' },
  SEWING: { label: '车缝计划', path: '/workshop/plans/sewing' },
  ASSEMBLY: { label: '装配计划', path: '/workshop/plans/assembly' },
}
const wageLabels: Record<string, string> = {
  APPROVED: '工价已批准', PENDING_APPROVAL: '工价待审批', DRAFT: '工价草稿',
  RETURNED: '工价已退回', NO_EFFECTIVE_VERSION: '日期无工价', CONFLICT: '工价冲突',
  FORBIDDEN: '无车间权限', UNAVAILABLE: '范围异常', NOT_CREATED: '未建工价', SUPERSEDED: '旧工价',
}
function statusTone(status: string): string {
  if (['APPROVED', 'COMPLETED', 'ISSUED', 'ENDED'].includes(status)) return 'success'
  if (['PROCESSING', 'IN_PROGRESS', 'PENDING_REVIEW'].includes(status)) return 'info'
  if (['RETURNED', 'CONFLICT', 'UNAVAILABLE', 'CANCELLED'].includes(status)) return 'danger'
  if (['PENDING_APPROVAL', 'NO_EFFECTIVE_VERSION', 'PARTIAL_RETURN', 'PENDING_DISPATCH', 'PENDING_HANDOFF'].includes(status)) return 'warning'
  return 'neutral'
}
function dateText(value: string | null): string { return value ? value.slice(0, 10) : '—' }
function timeText(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).replaceAll('/', '-')
}
function progressText(row: ScheduleInternalPlan): string {
  if (row.progress_percent !== null) return `${row.progress_percent}%`
  if (!row.can_view_reports) return '无查看权限'
  if (['NOT_CREATED', 'DRAFT', 'PENDING_APPROVAL', 'RETURNED', 'NO_EFFECTIVE_VERSION'].includes(row.wage_status)) return '待设置工价'
  return '暂不可用'
}
function openPlan(row: ScheduleInternalPlan) {
  if (!props.active || !props.summary) return
  void router.push({ path: categories[row.category].path, query: { schedule_id: props.scheduleId, schedule_product_id: props.summary.schedule_product_id } })
}
function openWage(row: ScheduleInternalPlan) {
  if (!row.can_view_wage || !row.scheme_id) return
  wageSchemeId.value = row.scheme_id
  wageVisible.value = true
}
function openReports(row: ScheduleInternalPlan) {
  if (!row.can_view_reports || !row.workshop_id || !props.summary) return
  void router.push({ name: 'work-report-days', query: { schedule_product_id: props.summary.schedule_product_id, workshop_id: row.workshop_id, craft_id: row.craft_id } })
}
function outsourcingQuantity(value: string | null, unit: string | null): string {
  return unit === '多种单位' ? '多种单位' : formatScheduleQuantity(value, unit || '')
}
function openOutsourcing(row: ScheduleOutsourcingOrderSummary) {
  const id = encodeURIComponent(row.order_id)
  if (row.order_kind === 'TUBE') void router.push(`/workshop/outsourcing/tube/${id}`)
  else if (row.order_kind === 'P4') void router.push(`/workshop/outsourcing/rework/${id}`)
  else void router.push({ path: `/workshop/outsourcing/${id}`, query: row.detail_access === 'METAL' ? { view: 'metal' } : {} })
}
function openMaterialIssues() {
  void router.push({ name: 'material-issues', query: { production_task_id: props.productionTaskId, product_line_id: props.productLineId } })
}
function openInventoryRecords(kind: 'finished-inbound' | 'finished-outbound' | 'semi-inbound' | 'semi-outbound') {
  if (!props.summary) return
  const scheduleProductId = props.summary.schedule_product_id
  if (kind === 'finished-inbound') {
    void router.push({ name: 'finished-goods-inventory', query: { tab: 'records', product_line_id: props.productLineId } })
  } else if (kind === 'finished-outbound') {
    void router.push({ name: 'finished-goods-outbounds', query: { production_task_id: props.productionTaskId, product_line_id: props.productLineId, schedule_product_id: scheduleProductId } })
  } else if (kind === 'semi-inbound') {
    void router.push({ name: 'semi-receipt-records', query: { product_line_id: props.productLineId } })
  } else {
    void router.push({ name: 'semi-outbound-records', query: { product_line_id: props.productLineId } })
  }
}
</script>

<template>
  <div class="schedule-execution" data-testid="schedule-execution-overview">
    <p v-if="loading" class="schedule-execution__state" role="status">正在加载内部作业、外发和领料信息…</p>
    <p v-else-if="failed || !summary" class="schedule-execution__state">关联信息未能加载，请使用上方“重试关联信息”。</p>
    <template v-else>
      <section class="schedule-execution__section" aria-label="内部作业计划">
        <header class="schedule-execution__heading"><h3>内部作业计划</h3><span>共 {{ summary.internal_plans.length }} 项工艺</span><div class="schedule-execution__record-links" aria-label="本产品入库出库记录"><button class="schedule-execution__link" @click="openInventoryRecords('finished-inbound')">成品入库</button><button class="schedule-execution__link" @click="openInventoryRecords('finished-outbound')">成品出库</button><button class="schedule-execution__link" @click="openInventoryRecords('semi-inbound')">半成品入库</button><button class="schedule-execution__link" @click="openInventoryRecords('semi-outbound')">半成品出库</button></div></header>
        <div v-if="summary.internal_plans.length" class="schedule-execution__scroll" tabindex="0" aria-label="内部作业计划表，可横向滚动">
          <table class="schedule-execution__table schedule-execution__table--internal" data-testid="internal-plans-table">
            <colgroup><col style="width: 96px"><col style="width: 240px"><col style="width: 100px"><col style="width: 100px"><col style="width: 116px"><col style="width: 132px"><col style="width: 160px"><col style="width: 160px"><col style="width: 124px"><col style="width: 64px"><col style="width: 64px"><col style="width: 64px"></colgroup>
            <thead><tr><th>作业计划</th><th>厂内工艺</th><th>排产数量</th><th>计划节点</th><th>计划日期</th><th>报工进度</th><th class="is-money">报工总价（预计）</th><th class="is-money">已报工金额</th><th>工价状态</th><th>计划</th><th>工价</th><th>报工</th></tr></thead>
            <tbody><tr v-for="row in summary.internal_plans" :key="row.craft_id" :data-craft-id="row.craft_id">
              <td>{{ categories[row.category]?.label || '内部计划' }}</td>
              <td :title="`${row.craft_name}${row.workshop_name ? ` · ${row.workshop_name}` : ''}`">{{ row.craft_name || '—' }}</td>
              <td>{{ formatScheduleQuantity(row.planned_quantity, row.unit_name) }}</td>
              <td :title="row.category === 'CUTTING' ? '裁剪沿用车缝回货日期' : row.milestone">{{ row.milestone.replace(/日期$/, '') || '—' }}</td>
              <td class="is-date">{{ dateText(row.plan_date) }}</td>
              <td :title="[row.plan_status_display, row.reason].filter(Boolean).join('；')"><div class="schedule-execution__progress"><span v-if="row.progress_percent !== null" class="schedule-execution__track" role="progressbar" :aria-label="`${row.craft_name}报工进度`" :aria-valuenow="row.progress_percent" :aria-valuemin="0" :aria-valuemax="100"><i :class="{ 'is-complete': row.plan_status === 'COMPLETED' }" :style="{ width: `${Math.max(0, Math.min(100, row.progress_percent))}%` }" /></span><span>{{ progressText(row) }}</span></div></td>
              <td class="is-money" data-field="estimated_wage" :title="row.estimated_wage === null ? scheduleAmountReason(row.estimated_amount_status) : ''">{{ formatScheduleMoney(row.estimated_wage) }}</td>
              <td class="is-money" data-field="reported_amount" :title="row.reported_amount === null ? scheduleAmountReason(row.reported_amount_status) : ''">{{ formatScheduleMoney(row.reported_amount) }}</td>
              <td><span class="erp-list-tag" :class="`erp-list-tag--${statusTone(row.wage_status)}`" :title="row.reason">{{ wageLabels[row.wage_status] || '暂不可用' }}</span></td>
              <td><button class="schedule-execution__link" :disabled="!active" :title="active ? `查看${row.craft_name}所属计划` : '本排产已作废，内部计划列表不再显示该排产'" @click="openPlan(row)">查看</button></td>
              <td><button class="schedule-execution__link" :disabled="!row.can_view_wage || !row.scheme_id" :title="!row.can_view_wage ? '没有工价查看权限' : !row.scheme_id ? '尚无可查看的工价方案' : `查看${row.craft_name}工价`" @click="openWage(row)">查看</button></td>
              <td><button class="schedule-execution__link" :disabled="!row.can_view_reports || !row.workshop_id" :title="!row.can_view_reports ? '没有报工记录查看权限' : `查看${row.craft_name}报工记录`" @click="openReports(row)">记录</button></td>
            </tr></tbody>
          </table>
        </div>
        <p v-else class="schedule-execution__state">本产品未选择内部计划工艺。</p>
        <p v-if="summary.internal_plans.length" class="schedule-execution__note">裁剪沿用车缝回货日期；报工进度按工序次数统计，已报工金额按历史报工金额累计，两者分别统计。</p>
        <p v-if="summary.internal_plans.length && summary.estimated_wage === null" class="schedule-execution__note" data-testid="estimated-amount-reason">预计金额：{{ scheduleAmountReason(summary.estimated_amount_status) }}</p>
        <p v-if="summary.internal_plans.length && summary.reported_amount === null" class="schedule-execution__note" data-testid="reported-amount-reason">已报工金额：{{ scheduleAmountReason(summary.reported_amount_status) }}</p>
      </section>

      <section class="schedule-execution__section" aria-label="本产品外发单">
        <header class="schedule-execution__heading"><h3>本产品外发单</h3><span v-if="summary.outsourcing.allowed">共 {{ outsourcingOrders.length }} 张</span><span>按当前生产任务及产品关联</span></header>
        <p v-if="!summary.outsourcing.allowed" class="schedule-execution__state">当前账号没有查看本产品外发记录的权限。</p>
        <div v-else-if="outsourcingOrders.length" class="schedule-execution__scroll" tabindex="0" aria-label="本产品外发单表，可横向滚动">
          <table class="schedule-execution__table schedule-execution__table--outsourcing" data-testid="outsourcing-records-table">
            <colgroup><col style="width: 192px"><col style="width: 76px"><col style="width: 132px"><col style="width: 104px"><col style="width: 96px"><col style="width: 96px"><col style="width: 96px"><col style="width: 108px"><col style="width: 108px"><col style="width: 136px"><col style="width: 116px"><col style="width: 108px"><col style="width: 64px"></colgroup>
            <thead><tr><th>外发单号</th><th>工艺</th><th>加工厂</th><th>计划加工量</th><th>实发数量</th><th>实收数量</th><th>短少数量</th><th class="is-money">加工单价</th><th>计价单位</th><th class="is-money">计划加工金额</th><th>计划回货</th><th>状态</th><th>操作</th></tr></thead>
            <tbody><tr v-for="row in outsourcingOrders" :key="row.id" :data-record-id="row.id" :data-order-id="row.order_id">
              <td :title="row.order_number">{{ row.order_number }}</td><td :title="row.craft_name">{{ row.craft_name || '—' }}</td><td :title="row.factory_name">{{ row.factory_name || '—' }}</td>
              <td data-field="planned_quantity" :title="row.quantity_notes.planned_quantity || row.reason">{{ outsourcingQuantity(row.planned_quantity, row.quantity_unit) }}</td><td data-field="dispatched_quantity" :title="row.quantity_notes.dispatched_quantity || row.reason">{{ outsourcingQuantity(row.dispatched_quantity, row.dispatched_unit) }}</td><td data-field="received_quantity" :title="row.quantity_notes.received_quantity || row.reason">{{ outsourcingQuantity(row.received_quantity, row.received_unit) }}</td><td data-field="shortage_quantity" :title="row.quantity_notes.shortage_quantity || row.reason">{{ outsourcingQuantity(row.shortage_quantity, row.shortage_unit) }}</td>
              <td class="is-money" data-field="unit_price" :title="row.unit_price_note || row.reason">{{ row.unit_price_status === 'MULTIPLE' ? '多种单价' : formatScheduleUnitPrice(row.unit_price) }}</td><td :title="row.unit_price_note || row.price_unit">{{ row.price_unit || '—' }}</td><td class="is-money" data-field="planned_amount" :title="row.planned_amount_note || row.reason">{{ formatScheduleMoney(row.planned_amount) }}</td><td class="is-date">{{ dateText(row.expected_return_date) }}</td>
              <td><span class="erp-list-tag" :class="`erp-list-tag--${statusTone(row.status)}`">{{ row.status_display }}</span></td><td><button class="schedule-execution__link" :aria-label="`查看外发单${row.order_number}`" @click="openOutsourcing(row)">查看</button></td>
            </tr></tbody>
          </table>
        </div>
        <p v-else class="schedule-execution__state">当前生产任务及产品暂无关联外发记录。</p>
        <p v-if="summary.outsourcing.allowed && outsourcingOrders.length" class="schedule-execution__note">每张外发单一行，仅合并本产品可见明细；数量按本产品单内明细同单位合计，不代表成品排产数；不同单位不混加。计划加工金额不代表结算金额，已结束不代表全部回齐。</p>
        <p v-if="summary.outsourcing.allowed && summary.outsourcing.planned_amount === null" class="schedule-execution__note">部分外发数量、单价或金额不可用，暂不显示不完整合计。</p>
      </section>

      <section class="schedule-execution__section" aria-label="本产品领料记录">
        <header class="schedule-execution__heading"><h3>本产品领料记录</h3><span>按当前生产任务及产品关联</span><button v-if="summary.material_issues.allowed" class="schedule-execution__link schedule-execution__all" @click="openMaterialIssues">查看全部</button></header>
        <p v-if="!summary.material_issues.allowed" class="schedule-execution__state">当前账号没有查看本产品领料记录的权限。</p>
        <div v-else-if="summary.material_issues.records.length" class="schedule-execution__scroll" tabindex="0" aria-label="本产品领料记录表，可横向滚动">
          <table class="schedule-execution__table schedule-execution__table--materials" data-testid="material-issue-records-table">
            <colgroup><col style="width: 216px"><col style="width: 140px"><col style="width: 120px"><col style="width: 100px"><col style="width: 150px"><col style="width: 180px"><col style="width: 120px"><col style="width: 64px"></colgroup>
            <thead><tr><th>领料单号</th><th>领料车间</th><th>领料人</th><th>材料项数</th><th>申请领料日期</th><th>实际出库时间</th><th>状态</th><th>操作</th></tr></thead>
            <tbody><tr v-for="row in summary.material_issues.records" :key="row.id" :data-issue-id="row.id">
              <td :title="row.issue_number">{{ row.issue_number }}</td><td :title="row.workshop_name">{{ row.workshop_name || '—' }}</td><td :title="row.recipient_name">{{ row.recipient_name || '—' }}</td><td>{{ row.line_count }} 项</td><td class="is-date">{{ dateText(row.issue_at) }}</td><td class="is-date">{{ timeText(row.issued_at) }}</td>
              <td><span class="erp-list-tag" :class="`erp-list-tag--${statusTone(row.status)}`">{{ row.status_display }}</span></td><td><button class="schedule-execution__link" :aria-label="`查看领料单${row.issue_number}`" @click="router.push({ name: 'material-issue-detail', params: { issueId: row.id } })">查看</button></td>
            </tr></tbody>
          </table>
        </div>
        <p v-else class="schedule-execution__state">当前生产任务及产品暂无关联领料记录。</p>
        <p v-if="summary.material_issues.allowed && summary.material_issues.records.length" class="schedule-execution__note">材料数量在明细中按各自单位展示，不混合汇总。</p>
      </section>
    </template>
    <WageSchemeDetailDialog v-model="wageVisible" :scheme-id="wageSchemeId" />
  </div>
</template>

<style lang="scss">@use '@/styles/scheduleExecution.scss';</style>
