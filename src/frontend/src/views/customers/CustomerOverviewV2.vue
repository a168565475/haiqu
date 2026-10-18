<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, type RouteLocationRaw } from 'vue-router'

import CustomerContactsPanel from '@/components/customers/CustomerContactsPanel.vue'
import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'
import {
  buildCustomerHealthSummary,
  calculateCreditUsage,
  formatOverviewDateTime,
  formatOverviewMoney,
  formatTimelineDate,
  timelineCategory,
} from './customerOverview'
import type { ContactListItem } from '@/types/contact'
import type { CustomerDetail, CustomerSummary, CustomerTimelineEvent } from '@/types/customer'
import type { TaskSummary } from '@/types/task'

const props = withDefaults(defineProps<{
  customer: CustomerDetail
  summary: CustomerSummary | null
  contacts: ContactListItem[]
  contactsLoading?: boolean
  contactsError?: string
  canEditCustomer?: boolean
  timeline: CustomerTimelineEvent[]
  timelineLoading: boolean
  tasks: TaskSummary[]
  tasksLoading: boolean
  tasksError: string
  canViewTasks: boolean
  canCreateTask: boolean
  completingTaskId: string
}>(), { canEditCustomer: true })

const emit = defineEmits<{
  completeTask: [task: TaskSummary]
  createTask: []
  editCustomer: []
  openContacts: []
  retryContacts: []
  contactsChanged: []
  refresh: []
  retryTasks: []
}>()

const router = useRouter()
const timelineTypeDraft = ref('')
const timelineRelationDraft = ref('')
const timelineType = ref('')
const timelineRelation = ref('')

const snapshot = computed(() => props.customer.business_snapshot)
const snapshotCurrency = computed(() => snapshot.value?.currency_code || 'USD')
const creditUsage = computed(() => calculateCreditUsage(props.customer))
const primaryContact = computed(() => (
  props.contacts.find((item) => item.is_primary_contact)
  || props.contacts.find((item) => item.is_key_contact)
  || props.contacts[0]
  || null
))
const latestInteractionAt = computed(() => props.timeline[0]?.occurred_at || props.customer.last_contact_at)
const health = computed(() => buildCustomerHealthSummary(
  props.customer,
  props.summary,
  latestInteractionAt.value,
))

const timelineTypeOptions = computed(() => {
  const values = new Map<string, string>()
  for (const item of props.timeline) {
    const category = timelineCategory(item)
    values.set(category.label, category.label)
  }
  return [...values.values()]
})
const filteredTimeline = computed(() => props.timeline.filter((item) => {
  const category = timelineCategory(item)
  if (timelineType.value && category.label !== timelineType.value) return false
  const hasRelatedBusiness = !['CUSTOMER', 'COMMUNICATION', 'CUSTOMER_COMMUNICATION'].includes(item.source_type) && Boolean(item.source_id)
  if (timelineRelation.value === 'RELATED' && !hasRelatedBusiness) return false
  if (timelineRelation.value === 'UNRELATED' && hasRelatedBusiness) return false
  return true
}))
const visibleTimeline = computed(() => filteredTimeline.value.slice(0, 10))
const visibleTasks = computed(() => props.tasks.slice(0, 3))

function formatMetricMoney(value: string | number | null | undefined): string {
  const formatted = formatOverviewMoney(value, snapshotCurrency.value)
  return formatted === '—' ? `${snapshotCurrency.value} 0` : formatted
}

function formatSalesMoney(value: string | number | null | undefined): string {
  const formatted = formatOverviewMoney(value, 'CNY')
  return formatted === '—' ? 'CNY 0' : formatted
}

const countryLabel = computed(() => (
  props.customer.secondary_region?.region_name
  || props.customer.primary_region?.region_name
  || props.customer.primary_country_code
  || '—'
))
const customerSource = computed(() => props.customer.latest_source?.display_name || '—')
const customerTags = computed(() => {
  const labels = props.customer.customer_tags.map((item) => item.tag_name)
  if (!labels.length) labels.push(...props.customer.customer_types.map((item) => item.display_name))
  return labels.length ? labels.join('  ·  ') : '—'
})

function timelineOwner(item: CustomerTimelineEvent): string {
  const data = item.event_data || {}
  const directName = ['actor_name', 'actor_employee_name', 'owner_name', 'employee_name']
    .map((key) => data[key])
    .find((value) => typeof value === 'string' && value.trim())
  if (typeof directName === 'string') return directName
  const actorId = typeof data.actor_employee_id === 'string' ? data.actor_employee_id : ''
  return props.customer.current_assignments.find((assignment) => assignment.employee.id === actorId)?.employee.display_name || '—'
}

function timelineRelated(item: CustomerTimelineEvent): string {
  if (!item.source_id || ['CUSTOMER', 'COMMUNICATION', 'CUSTOMER_COMMUNICATION'].includes(item.source_type)) return '—'
  const labelBySource: Record<string, string> = {
    INQUIRY: '询盘',
    QUOTATION: '报价',
    QUOTATION_VERSION: '报价',
    SAMPLE_REQUEST: '样品',
    TASK: '任务',
    BUSINESS_TASK: '任务',
    CUSTOMER_CONTACT: '联系人',
  }
  const label = labelBySource[item.source_type] || '业务记录'
  const code = item.title.match(/[A-Z]{1,6}-[A-Z0-9-]*\d+/i)?.[0]
  return code ? `${label} ${code}` : label
}

function timelineRelatedRoute(item: CustomerTimelineEvent): RouteLocationRaw | null {
  if (!item.source_id) return null
  if (item.source_type === 'INQUIRY') {
    return { name: 'inquiry-detail', params: { inquiryId: item.source_id } }
  }
  if (item.source_type === 'QUOTATION') {
    return { name: 'quotation-edit', params: { quotationId: item.source_id } }
  }
  if (item.source_type === 'SAMPLE_REQUEST') {
    return { name: 'sample-detail', params: { sampleId: item.source_id } }
  }
  if (['TASK', 'BUSINESS_TASK'].includes(item.source_type)) {
    return { name: 'task-detail', params: { taskId: item.source_id } }
  }
  if (item.source_type === 'CUSTOMER_CONTACT') {
    return { name: 'customer-contacts', params: { customerId: props.customer.id } }
  }
  if (item.source_type === 'QUOTATION_VERSION') {
    return { name: 'customer-quotations', params: { customerId: props.customer.id } }
  }
  return null
}

function openTimelineRelated(item: CustomerTimelineEvent) {
  const target = timelineRelatedRoute(item)
  if (target) void router.push(target)
}

function taskTime(task: TaskSummary): string {
  if (!task.due_at) return '未安排'
  const formatted = formatOverviewDateTime(task.due_at)
  return formatted === '—' ? '时间异常' : formatted.slice(5)
}

function taskTone(task: TaskSummary): 'warning' | 'info' | 'neutral' {
  if (task.status === 'PENDING') return 'warning'
  if (task.status === 'IN_PROGRESS') return 'info'
  return 'neutral'
}

function applyTimelineFilters() {
  timelineType.value = timelineTypeDraft.value
  timelineRelation.value = timelineRelationDraft.value
}

function openTask(task: TaskSummary) {
  void router.push({ name: 'task-detail', params: { taskId: task.id } })
}
</script>

<template>
  <main class="customer-overview-v2 erp-glass-list" data-customer-overview-v2>
    <section class="overview-metrics erp-list-surface" aria-label="客户业务概览">
      <div class="overview-metric overview-metric--wide">
        <span>累计销售额</span>
        <strong>{{ formatSalesMoney(customer.lifetime_sales_amount) }}</strong>
      </div>
      <div class="overview-metric overview-metric--wide">
        <span>近12个月销售额</span>
        <strong>{{ formatSalesMoney(customer.last_12m_sales_amount) }}</strong>
      </div>
      <div class="overview-metric">
        <span>订单</span>
        <strong>{{ customer.lifetime_sales_order_count ?? 0 }}</strong>
      </div>
      <div class="overview-metric">
        <span>报价转化率</span>
        <strong>{{ customer.quotation_conversion_rate != null ? `${customer.quotation_conversion_rate}%` : '—' }}</strong>
      </div>
      <div class="overview-metric">
        <span>毛利率</span>
        <strong>—</strong>
      </div>
      <div class="overview-metric overview-metric--credit">
        <span>信用额度</span>
        <strong>{{ formatMetricMoney(snapshot?.credit_limit) }}</strong>
        <small>已用 {{ creditUsage ?? 0 }}%</small>
        <i class="credit-track"><b :style="{ width: `${creditUsage || 0}%` }" /></i>
      </div>
      <div class="overview-metric">
        <span>应收余额</span>
        <strong>—</strong>
      </div>
      <div class="overview-snapshot">
        <p>最近联系 <b>{{ formatOverviewDateTime(customer.last_contact_at) }}</b></p>
        <p class="is-accent">下次跟进 <b>{{ formatOverviewDateTime(customer.next_follow_up_at) }}</b></p>
        <p>当前阶段 <b>{{ customer.lifecycle_stage_display || '—' }}</b></p>
        <p>客户来源 <b>{{ customerSource }}</b></p>
      </div>
    </section>

    <section class="overview-layout">
      <article class="overview-panel erp-list-surface customer-card">
        <header class="panel-title">
          <h2>基本资料</h2>
          <ElButton class="erp-button-motion" text type="primary" aria-label="编辑客户" :disabled="!canEditCustomer" @click="emit('editCustomer')">编辑</ElButton>
        </header>

        <dl class="customer-profile">
          <div><dt>国家/地区</dt><dd>{{ countryLabel }}</dd></div>
          <div><dt>时区</dt><dd>{{ primaryContact?.timezone_code || '—' }}</dd></div>
          <div><dt>客户来源</dt><dd>{{ customerSource }}</dd></div>
          <div><dt>客户标签</dt><dd class="is-accent" :title="customerTags">{{ customerTags }}</dd></div>
          <div><dt>备注</dt><dd :title="customer.notes || '暂无备注'">{{ customer.notes || '暂无备注' }}</dd></div>
        </dl>
        <CustomerContactsPanel :customer-id="customer.id" :contacts="contacts" :loading="contactsLoading" :error="contactsError" @retry="emit('retryContacts')" @changed="emit('contactsChanged')" />
      </article>

      <article class="overview-panel erp-list-surface timeline-panel">
        <header class="timeline-toolbar erp-list-filters">
          <h2>互动时间轴</h2>
          <ElSelect v-model="timelineTypeDraft" class="timeline-type-select" aria-label="互动类型" placeholder="全部类型" clearable>
            <ElOption v-for="item in timelineTypeOptions" :key="item" :label="item" :value="item" />
          </ElSelect>
          <ElSelect v-model="timelineRelationDraft" class="timeline-relation-select" aria-label="关联业务" placeholder="全部" clearable>
            <ElOption label="有相关业务" value="RELATED" />
            <ElOption label="无相关业务" value="UNRELATED" />
          </ElSelect>
          <ElButton class="erp-button-motion" @click="applyTimelineFilters">筛选</ElButton>
        </header>
        <div class="timeline-table-head" role="row">
          <span>日期</span><span>类型</span><span>内容摘要</span><span>负责人</span><span>相关业务</span>
        </div>
        <div v-loading="timelineLoading" class="timeline-table-body">
          <div v-for="item in visibleTimeline" :key="item.id" class="timeline-row" role="row">
            <time><span>{{ formatTimelineDate(item.occurred_at).date }}</span><span>{{ formatTimelineDate(item.occurred_at).time }}</span></time>
            <span class="timeline-type-cell">
              <CustomerActivityTag
                :label="timelineCategory(item).label"
                :tone="timelineCategory(item).tone"
                :title="timelineCategory(item).label"
              />
            </span>
            <ElTooltip :content="item.summary || item.title" placement="top" :show-after="250">
              <strong class="timeline-summary">{{ item.summary || item.title }}</strong>
            </ElTooltip>
            <span class="timeline-owner" :title="timelineOwner(item)">{{ timelineOwner(item) }}</span>
            <ElTooltip v-if="timelineRelatedRoute(item)" :content="timelineRelated(item)" placement="top" :show-after="250">
              <button class="timeline-related-link" type="button" @click="openTimelineRelated(item)">{{ timelineRelated(item) }}</button>
            </ElTooltip>
            <span v-else class="timeline-related-empty" :title="timelineRelated(item)">{{ timelineRelated(item) }}</span>
          </div>
          <div v-if="!timelineLoading && !visibleTimeline.length" class="panel-empty">当前筛选暂无互动记录</div>
        </div>
        <footer class="timeline-footer">
          <span>显示 {{ visibleTimeline.length }} / {{ filteredTimeline.length }} 条</span>
          <ElButton class="erp-button-motion" text type="primary" @click="router.push({ name: 'customer-timeline', params: { customerId: customer.id } })">查看全部互动</ElButton>
        </footer>
      </article>

      <div class="overview-right-rail">
        <article class="overview-panel erp-list-surface next-actions-panel">
          <header class="panel-title">
            <h2>下一步动作</h2>
            <ElButton class="erp-button-motion" :disabled="!canCreateTask" @click="emit('createTask')">新建任务</ElButton>
          </header>
          <div class="action-table-head" role="row">
            <span>计划时间</span><span>任务内容</span><span>负责人</span><span>状态</span>
          </div>
          <div v-loading="tasksLoading" class="action-table-body">
            <div
              v-for="task in visibleTasks"
              :key="task.id"
              class="action-row"
              role="button"
              tabindex="0"
              @click="openTask(task)"
              @keyup.enter="openTask(task)"
            >
              <ElCheckbox
                :model-value="false"
                :disabled="completingTaskId === task.id"
                aria-label="完成任务"
                @click.stop.prevent="emit('completeTask', task)"
              />
              <time>{{ taskTime(task) }}</time>
              <strong :title="task.title">{{ task.title }}</strong>
              <span :title="task.assignee?.display_name || '—'">{{ task.assignee?.display_name || '—' }}</span>
              <CustomerActivityTag :label="task.status_display || task.display_status || '待处理'" :tone="taskTone(task)" />
            </div>
            <div v-if="tasksError" class="panel-empty panel-empty--error">
              <span>{{ tasksError }}</span><button type="button" @click="emit('retryTasks')">重试</button>
            </div>
            <div v-else-if="!canViewTasks" class="panel-empty">当前账号无权查看客户任务</div>
            <div v-else-if="!tasksLoading && !visibleTasks.length" class="panel-empty">当前客户暂无未完成任务</div>
          </div>
        </article>

        <article class="overview-panel erp-list-surface customer-health-panel">
          <header class="panel-title">
            <h2>客户健康</h2>
            <CustomerActivityTag :label="health.label" :tone="health.tone" />
          </header>
          <div class="health-list">
            <div v-for="fact in health.facts" :key="fact.label" class="health-row">
              <i class="health-dot" :class="`is-${fact.tone}`" />
              <strong>{{ fact.label }}</strong>
              <span :title="fact.meta">{{ fact.meta }}</span>
            </div>
          </div>
          <footer class="health-footer">
            <span>数据更新&nbsp; {{ formatOverviewDateTime(snapshot?.as_of_at || customer.updated_at).slice(0, 10) }}</span>
            <ElButton class="erp-button-motion" @click="emit('refresh')">刷新评估</ElButton>
          </footer>
        </article>
      </div>
    </section>
  </main>
</template>

<style scoped lang="scss">
.customer-overview-v2.erp-glass-list { height: auto; min-width: 0; gap: 14px; padding: 0; font-size: 13px; line-height: 20px; }
.overview-metrics { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); padding: 16px; gap: 16px; }
.overview-metric { min-width: 0; display: flex; flex-direction: column; gap: 6px; }
.overview-metric > span, .overview-metric small { color: var(--erp-color-text-secondary); }
.overview-metric > strong { font-size: 20px; line-height: 28px; font-weight: 700; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.overview-metric small { font-size: 12px; line-height: 18px; }
.credit-track { display: block; height: 4px; border-radius: 2px; overflow: hidden; background: var(--erp-color-subtle); }
.credit-track b { display: block; height: 100%; max-width: 100%; border-radius: inherit; background: var(--erp-color-brand); }
.overview-snapshot { grid-column: 1 / -1; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px 16px; padding-top: 12px; border-top: 1px solid var(--erp-color-border); }
.overview-snapshot p { display: flex; gap: 8px; min-width: 0; margin: 0; flex-wrap: wrap; color: var(--erp-color-text-secondary); }
.overview-snapshot b { font-weight: 500; color: var(--erp-color-text-primary); overflow-wrap: anywhere; }
.overview-snapshot .is-accent, .customer-profile dd.is-accent { color: var(--erp-color-brand); }
.overview-layout { display: grid; grid-template-columns: minmax(260px, .8fr) minmax(0, 1.55fr) minmax(0, 1.2fr); align-items: start; gap: 14px; min-width: 0; }
.overview-panel { min-width: 0; padding: 16px; }
.panel-title { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.panel-title h2, .timeline-toolbar h2 { margin: 0; color: var(--erp-color-text-primary); font-size: 16px; font-weight: 700; line-height: 24px; }
.panel-title :deep(.el-button), .timeline-toolbar :deep(.el-button), .health-footer :deep(.el-button), .timeline-footer :deep(.el-button) { height: 32px; margin: 0; }
.customer-profile { display: grid; gap: 12px; margin: 0 0 16px; }
.customer-profile > div { display: grid; grid-template-columns: 78px minmax(0, 1fr); gap: 8px; }
.customer-profile dt, .customer-profile dd { margin: 0; overflow-wrap: anywhere; }
.customer-profile dt { color: var(--erp-color-text-secondary); }
.customer-profile dd { color: var(--erp-color-text-primary); }
.timeline-panel .timeline-toolbar { gap: 8px; margin-bottom: 12px; }
.timeline-toolbar h2 { width: 100%; margin-bottom: 4px; }
.timeline-toolbar :deep(.timeline-type-select) { width: 130px; }
.timeline-toolbar :deep(.timeline-relation-select) { width: 118px; }
.timeline-table-head, .timeline-row { display: grid; grid-template-columns: 78px 60px minmax(0, 1fr) 62px 70px; gap: 8px; align-items: center; padding: 8px; }
.timeline-table-head { min-height: 38px; box-sizing: border-box; border-radius: var(--erp-radius-control); background: var(--erp-table-header-background); color: var(--erp-table-header-text); }
.timeline-table-body, .action-table-body { position: relative; min-height: 56px; }
.timeline-row { min-height: 54px; box-sizing: border-box; border-bottom: 1px solid var(--erp-color-border); }
.timeline-row:last-child { border-bottom: 0; }
.timeline-row > * { min-width: 0; }
.timeline-row time { display: flex; flex-direction: column; font-size: 12px; line-height: 18px; font-variant-numeric: tabular-nums; color: var(--erp-color-text-secondary); }
.timeline-summary, .timeline-owner, .timeline-related-empty, .timeline-related-link { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 400; }
.timeline-related-link { padding: 0; border: 0; color: var(--erp-color-brand); background: transparent; text-align: left; font: inherit; cursor: pointer; }
.timeline-related-link:hover { text-decoration: underline; }
.timeline-footer, .health-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px; padding-top: 12px; color: var(--erp-color-text-secondary); font-size: 12px; }
.overview-right-rail { display: grid; align-items: start; gap: 14px; min-width: 0; }
.action-table-head, .action-row { display: grid; grid-template-columns: 18px 80px minmax(0, 1fr) 62px 66px; gap: 6px; align-items: center; padding: 8px 0; }
.action-table-head { min-height: 38px; box-sizing: border-box; border-radius: var(--erp-radius-control); background: var(--erp-table-header-background); color: var(--erp-table-header-text); font-size: 12px; }
.action-table-head span:nth-child(1) { grid-column: 2; }
.action-table-head span:nth-child(2) { grid-column: 3; }
.action-table-head span:nth-child(3) { grid-column: 4; }
.action-table-head span:nth-child(4) { grid-column: 5; }
.action-row { min-height: 48px; border-bottom: 1px solid var(--erp-color-border); cursor: pointer; }
.action-row:last-child { border-bottom: 0; }
.action-row:hover { background: var(--erp-table-hover); }
.action-row > * { min-width: 0; }
.action-row :deep(.el-checkbox) { margin: 0; }
.action-row time, .action-row > span, .action-row > strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; line-height: 20px; font-weight: 400; }
.health-list { display: grid; }
.health-row { display: grid; grid-template-columns: 10px minmax(0, 1fr); gap: 4px 8px; padding: 12px 0; border-bottom: 1px solid var(--erp-color-border); }
.health-row:last-child { border-bottom: 0; }
.health-dot { width: 8px; height: 8px; margin-top: 6px; border-radius: 50%; background: var(--erp-tag-neutral-background); }
.health-dot.is-success { background: var(--erp-tag-success-background); }
.health-dot.is-info { background: var(--erp-tag-info-background); }
.health-dot.is-warning { background: var(--erp-tag-warning-background); }
.health-dot.is-danger { background: var(--erp-tag-danger-background); }
.health-row strong { font-weight: 500; overflow-wrap: anywhere; }
.health-row > span { grid-column: 2; color: var(--erp-color-text-secondary); font-size: 12px; overflow-wrap: anywhere; }
.panel-empty { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 8px; padding: 20px 0; color: var(--erp-color-text-secondary); }
.panel-empty--error { color: var(--erp-color-danger); }
.panel-empty button { padding: 0; border: 0; color: var(--erp-color-brand); background: transparent; font: inherit; cursor: pointer; }
@media (max-width: 1599px) {
  .overview-metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .overview-layout { grid-template-columns: minmax(260px, .8fr) minmax(0, 1.55fr); }
  .overview-right-rail { grid-column: 1 / -1; grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .overview-layout { grid-template-columns: minmax(0, 1fr); }
  .overview-right-rail { grid-template-columns: minmax(0, 1fr); }
  .overview-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .overview-snapshot { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
