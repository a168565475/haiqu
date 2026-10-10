<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, type RouteLocationRaw } from 'vue-router'

import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'
import {
  buildCustomerHealthSummary,
  calculateCreditUsage,
  formatOverviewDateTime,
  formatOverviewMoney,
  formatTimelineDate,
  timelineCategory,
} from './customerOverview'
import type { ContactListItem, ContactMethodType } from '@/types/contact'
import type { CustomerDetail, CustomerSummary, CustomerTimelineEvent } from '@/types/customer'
import type { TaskSummary } from '@/types/task'

const props = defineProps<{
  customer: CustomerDetail
  summary: CustomerSummary | null
  contacts: ContactListItem[]
  timeline: CustomerTimelineEvent[]
  timelineLoading: boolean
  tasks: TaskSummary[]
  tasksLoading: boolean
  tasksError: string
  canViewTasks: boolean
  canCreateTask: boolean
  completingTaskId: string
}>()

const emit = defineEmits<{
  completeTask: [task: TaskSummary]
  createTask: []
  editCustomer: []
  openContacts: []
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
const otherContacts = computed(() => props.contacts
  .filter((item) => item.id !== primaryContact.value?.id)
  .slice(0, 2))
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

function contactInitials(contact: ContactListItem | null): string {
  if (!contact) return '—'
  const value = (contact.english_name || contact.display_name).trim()
  if (!value) return '—'
  const words = value.split(/\s+/).filter(Boolean)
  if (words.length >= 2) return `${words[0]?.[0] || ''}${words.at(-1)?.[0] || ''}`.toUpperCase()
  return value.slice(0, 2).toUpperCase()
}

function contactRole(contact: ContactListItem): string {
  return contact.position_title
    || contact.department_name
    || contact.active_roles.map((item) => item.role_type_display).join('、')
    || ''
}

function contactMethod(contact: ContactListItem | null, types: ContactMethodType[]): string {
  if (!contact) return ''
  const method = contact.methods.find((item) => types.includes(item.method_type) && item.is_primary)
    || contact.methods.find((item) => types.includes(item.method_type))
  return method?.display_value || method?.masked_value || ''
}

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

function taskTone(task: TaskSummary): string {
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
  <main class="customer-overview-v2" data-customer-overview-v2>
    <section class="overview-metrics" aria-label="客户业务概览">
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
      <article class="overview-panel customer-card">
        <header class="panel-title">
          <h2>客户名片</h2>
          <button type="button" aria-label="编辑客户" @click="emit('editCustomer')">✎</button>
        </header>

        <section class="primary-contact">
          <p class="section-label">主要联系人</p>
          <template v-if="primaryContact">
            <span class="contact-avatar contact-avatar--primary">{{ contactInitials(primaryContact) }}</span>
            <strong class="contact-name">{{ primaryContact.display_name }}</strong>
            <span class="soft-tag is-warning primary-badge">主要</span>
            <span v-if="contactRole(primaryContact)" class="contact-role">{{ contactRole(primaryContact) }}</span>
            <span v-if="contactMethod(primaryContact, ['EMAIL'])" class="contact-method contact-email" :title="contactMethod(primaryContact, ['EMAIL'])">✉&nbsp; {{ contactMethod(primaryContact, ['EMAIL']) }}</span>
            <span v-if="contactMethod(primaryContact, ['MOBILE', 'PHONE'])" class="contact-method contact-phone" :title="contactMethod(primaryContact, ['MOBILE', 'PHONE'])">⌕&nbsp; {{ contactMethod(primaryContact, ['MOBILE', 'PHONE']) }}</span>
            <a
              v-if="contactMethod(primaryContact, ['EMAIL'])"
              class="crm-secondary-button send-mail"
              :href="`mailto:${contactMethod(primaryContact, ['EMAIL'])}`"
            >发送邮件</a>
          </template>
          <button v-else class="empty-link" type="button" @click="emit('openContacts')">暂无主要联系人</button>
        </section>

        <section class="other-contacts">
          <p class="section-label">其他联系人</p>
          <div v-if="otherContacts[0]" class="other-contact other-contact--first">
            <span class="contact-avatar">{{ contactInitials(otherContacts[0]) }}</span>
            <strong>{{ otherContacts[0].display_name }}</strong>
            <span v-if="contactRole(otherContacts[0])" class="role">{{ contactRole(otherContacts[0]) }}</span>
            <span v-if="contactMethod(otherContacts[0], ['EMAIL'])" class="email" :title="contactMethod(otherContacts[0], ['EMAIL'])">✉&nbsp; {{ contactMethod(otherContacts[0], ['EMAIL']) }}</span>
            <span v-if="contactMethod(otherContacts[0], ['MOBILE', 'PHONE'])" class="phone" :title="contactMethod(otherContacts[0], ['MOBILE', 'PHONE'])">⌕&nbsp; {{ contactMethod(otherContacts[0], ['MOBILE', 'PHONE']) }}</span>
          </div>
          <div v-if="otherContacts[1]" class="other-contact other-contact--second">
            <span class="contact-avatar">{{ contactInitials(otherContacts[1]) }}</span>
            <strong>{{ otherContacts[1].display_name }}</strong>
            <span v-if="contactRole(otherContacts[1])" class="role">{{ contactRole(otherContacts[1]) }}</span>
            <span v-if="contactMethod(otherContacts[1], ['EMAIL'])" class="email" :title="contactMethod(otherContacts[1], ['EMAIL'])">✉&nbsp; {{ contactMethod(otherContacts[1], ['EMAIL']) }}</span>
            <span v-if="contactMethod(otherContacts[1], ['MOBILE', 'PHONE'])" class="phone" :title="contactMethod(otherContacts[1], ['MOBILE', 'PHONE'])">⌕&nbsp; {{ contactMethod(otherContacts[1], ['MOBILE', 'PHONE']) }}</span>
          </div>
          <button v-if="!otherContacts.length" class="empty-link empty-link--others" type="button" @click="emit('openContacts')">暂无其他联系人</button>
        </section>

        <dl class="customer-profile">
          <div><dt>国家/地区</dt><dd>{{ countryLabel }}</dd></div>
          <div><dt>时区</dt><dd>{{ primaryContact?.timezone_code || '—' }}</dd></div>
          <div><dt>客户来源</dt><dd>{{ customerSource }}</dd></div>
          <div><dt>客户标签</dt><dd class="is-accent" :title="customerTags">{{ customerTags }}</dd></div>
          <div><dt>备注</dt><dd :title="customer.notes || '暂无备注'">{{ customer.notes || '暂无备注' }}</dd></div>
        </dl>
      </article>

      <article class="overview-panel timeline-panel">
        <header class="timeline-toolbar">
          <h2>互动时间轴</h2>
          <ElSelect v-model="timelineTypeDraft" class="timeline-type-select" aria-label="互动类型" placeholder="全部类型" clearable>
            <ElOption v-for="item in timelineTypeOptions" :key="item" :label="item" :value="item" />
          </ElSelect>
          <ElSelect v-model="timelineRelationDraft" class="timeline-relation-select" aria-label="关联业务" placeholder="全部" clearable>
            <ElOption label="有相关业务" value="RELATED" />
            <ElOption label="无相关业务" value="UNRELATED" />
          </ElSelect>
          <ElButton @click="applyTimelineFilters">筛选</ElButton>
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
          <span>当前 {{ filteredTimeline.length }} 条</span>
          <div><span>20条/页</span><button type="button" disabled>‹</button><button type="button" class="active">1</button><button type="button" disabled>›</button></div>
        </footer>
      </article>

      <div class="overview-right-rail">
        <article class="overview-panel next-actions-panel">
          <header class="panel-title">
            <h2>下一步动作</h2>
            <ElButton :disabled="!canCreateTask" @click="emit('createTask')">新建任务</ElButton>
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
              <i class="soft-tag" :class="`is-${taskTone(task)}`">{{ task.status_display || task.display_status || '待处理' }}</i>
            </div>
            <div v-if="tasksError" class="panel-empty panel-empty--error">
              <span>{{ tasksError }}</span><button type="button" @click="emit('retryTasks')">重试</button>
            </div>
            <div v-else-if="!canViewTasks" class="panel-empty">当前账号无权查看客户任务</div>
            <div v-else-if="!tasksLoading && !visibleTasks.length" class="panel-empty">当前客户暂无未完成任务</div>
          </div>
        </article>

        <article class="overview-panel customer-health-panel">
          <header class="panel-title">
            <h2>客户健康</h2>
            <span class="soft-tag" :class="`is-${health.tone}`">{{ health.label }}</span>
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
            <ElButton @click="emit('refresh')">刷新评估</ElButton>
          </footer>
        </article>
      </div>
    </section>
  </main>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.customer-overview-v2 {
  width: 100%;
  min-width: 0;
  height: 870px;
  overflow: hidden;
  color: token.$crm-text-primary;
  background: token.$crm-color-page;
  font-family: token.$crm-font-body;
}

.overview-metrics {
  width: calc(100% - 56px);
  height: 88px;
  box-sizing: border-box;
  display: grid;
  grid-template-columns: 180px 180px 140px 140px 140px 210px 140px minmax(0, 1fr);
  overflow: hidden;
  margin: 18px 28px 0;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-3;
  background: token.$crm-color-surface;
}

.overview-metric {
  position: relative;
  min-width: 0;
  border-right: 1px solid token.$crm-border-subtle;
}

.overview-metric > span {
  position: absolute;
  top: 12px;
  left: 16px;
  color: token.$crm-text-secondary;
  font-size: 11px;
  font-weight: 500;
  line-height: 18px;
}

.overview-metric > strong {
  position: absolute;
  top: 37px;
  left: 16px;
  max-width: calc(100% - 32px);
  overflow: hidden;
  color: token.$crm-text-primary;
  font-size: 20px;
  font-weight: 700;
  line-height: 26px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.overview-metric--wide > strong,
.overview-metric--credit > strong {
  font-size: 18px;
}

.overview-metric--credit small {
  position: absolute;
  top: 64px;
  left: 16px;
  color: token.$crm-text-secondary;
  font-size: 10px;
  line-height: 16px;
}

.credit-track {
  position: absolute;
  top: 70px;
  left: 86px;
  width: 96px;
  height: 4px;
  overflow: hidden;
  border-radius: 2px;
  background: token.$crm-color-subtle;
}

.credit-track b {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: token.$crm-primary;
}

.overview-snapshot {
  min-width: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  grid-template-rows: repeat(2, 18px);
  align-content: center;
  gap: 8px 20px;
  padding: 0 16px;
}

.overview-snapshot p {
  display: flex;
  gap: 8px;
  overflow: hidden;
  margin: 0;
  color: token.$crm-text-secondary;
  font-size: 11px;
  line-height: 18px;
  white-space: nowrap;
}

.overview-snapshot b {
  overflow: hidden;
  color: inherit;
  font-weight: 400;
  text-overflow: ellipsis;
}

.overview-snapshot .is-accent {
  color: token.$crm-primary;
  font-weight: 500;
}

.overview-layout {
  width: calc(100% - 56px);
  height: 694px;
  display: grid;
  grid-template-columns: 300px 620px 690px;
  gap: 12px;
  margin: 12px 28px 28px;
}

.overview-panel {
  min-width: 0;
  overflow: hidden;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-3;
  background: token.$crm-color-surface;
}

.panel-title {
  position: relative;
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
}

.panel-title h2,
.timeline-toolbar h2 {
  margin: 0;
  color: token.$crm-text-primary;
  font-size: 16px;
  font-weight: 700;
  line-height: 24px;
}

.panel-title > button {
  padding: 0;
  border: 0;
  color: token.$crm-text-secondary;
  background: transparent;
  font-size: 14px;
  line-height: 20px;
  cursor: pointer;
}

.panel-title :deep(.el-button),
.timeline-toolbar :deep(.el-button),
.health-footer :deep(.el-button) {
  height: 32px;
  margin: 0;
  padding: 0 16px;
  border-color: token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  font-size: 13px;
  font-weight: 500;
}

.section-label {
  margin: 0;
  color: token.$crm-text-secondary;
  font-size: 11px;
  font-weight: 500;
  line-height: 18px;
}

.primary-contact {
  position: relative;
  height: 168px;
  margin: 0 18px;
  border-bottom: 1px solid token.$crm-border-subtle;
}

.primary-contact .section-label {
  position: absolute;
  top: 4px;
  left: 0;
}

.contact-avatar {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 50%;
  color: token.$crm-warning;
  background: token.$crm-color-subtle;
  font-size: 11px;
  font-weight: 500;
  line-height: 18px;
}

.contact-avatar--primary {
  position: absolute;
  top: 31px;
  left: 0;
  width: 36px;
  height: 36px;
  font-size: 12px;
}

.contact-name {
  position: absolute;
  top: 25px;
  left: 48px;
  max-width: 112px;
  overflow: hidden;
  font-size: 13px;
  line-height: 20px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.primary-badge {
  position: absolute;
  top: 24px;
  left: 164px;
}

.contact-role {
  position: absolute;
  top: 48px;
  left: 48px;
  max-width: 190px;
  overflow: hidden;
  color: token.$crm-text-secondary;
  font-size: 11px;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.contact-method {
  position: absolute;
  left: 48px;
  width: 214px;
  overflow: hidden;
  color: token.$crm-text-secondary;
  font-size: 10px;
  line-height: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.contact-email { top: 71px; }
.contact-phone { top: 92px; }

.crm-secondary-button {
  height: 32px;
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 16px;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  line-height: 20px;
  text-decoration: none;
  cursor: pointer;
}

.crm-secondary-button:disabled {
  color: token.$crm-text-disabled;
  background: token.$crm-color-disabled;
  cursor: not-allowed;
}

.send-mail {
  position: absolute;
  top: 117px;
  left: 48px;
  width: 106px;
}

.other-contacts {
  position: relative;
  height: 230px;
  margin: 0 18px;
  border-bottom: 1px solid token.$crm-border-subtle;
}

.other-contacts > .section-label {
  position: absolute;
  top: 14px;
  left: 0;
}

.other-contact {
  position: absolute;
  left: 0;
  width: 264px;
  height: 68px;
}

.other-contact--first { top: 48px; }
.other-contact--second { top: 134px; }
.other-contact .contact-avatar { position: absolute; top: 1px; left: 0; }
.other-contact strong { position: absolute; top: -1px; left: 44px; max-width: 100px; overflow: hidden; font-size: 12px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.other-contact .role { position: absolute; top: 0; left: 150px; max-width: 104px; overflow: hidden; color: token.$crm-text-secondary; font-size: 10px; line-height: 16px; text-overflow: ellipsis; white-space: nowrap; }
.other-contact .email,
.other-contact .phone { position: absolute; left: 44px; width: 210px; overflow: hidden; color: token.$crm-text-secondary; font-size: 9px; line-height: 14px; text-overflow: ellipsis; white-space: nowrap; }
.other-contact .email { top: 22px; }
.other-contact .phone { top: 40px; }

.empty-link {
  position: absolute;
  top: 56px;
  left: 48px;
  padding: 0;
  border: 0;
  color: token.$crm-text-muted;
  background: transparent;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.empty-link--others { top: 56px; left: 0; }

.customer-profile {
  display: grid;
  grid-template-rows: repeat(5, 38px);
  margin: 15px 18px 0;
}

.customer-profile > div {
  min-width: 0;
  display: grid;
  grid-template-columns: 78px minmax(0, 1fr);
  align-items: center;
}

.customer-profile dt,
.customer-profile dd {
  overflow: hidden;
  margin: 0;
  font-size: 10px;
  line-height: 16px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.customer-profile dt { color: token.$crm-text-secondary; font-weight: 500; }
.customer-profile dd { color: token.$crm-text-primary; }
.customer-profile dd.is-accent { color: token.$crm-primary; }

.soft-tag {
  width: fit-content;
  max-width: 100%;
  height: 24px;
  box-sizing: border-box;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 9px;
  overflow: hidden;
  border-radius: 4px;
  color: token.$crm-text-secondary;
  background: token.$crm-color-subtle;
  font-size: 11px;
  font-style: normal;
  font-weight: 500;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.soft-tag.is-success { color: token.$crm-success; background: token.$crm-success-soft; }
.soft-tag.is-info { color: #4d7088; background: #e6eef2; }
.soft-tag.is-warning { color: token.$crm-warning; background: token.$crm-warning-soft; }
.soft-tag.is-danger { color: token.$crm-danger; background: token.$crm-danger-soft; }
.soft-tag.is-neutral { color: token.$crm-text-secondary; background: token.$crm-color-subtle; }

.timeline-toolbar {
  height: 48px;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
}

.timeline-toolbar h2 {
  margin-right: auto;
}

.timeline-toolbar :deep(.el-select) {
  flex: 0 0 auto;
}

.timeline-toolbar :deep(.timeline-type-select) { width: 112px; }
.timeline-toolbar :deep(.timeline-relation-select) { width: 82px; }
.timeline-toolbar :deep(.el-button) { width: 56px; height: 32px; padding: 0 12px; }
.timeline-toolbar :deep(.el-select__wrapper) { min-height: 32px; padding: 0 10px; border-radius: token.$crm-radius-2; box-shadow: inset 0 0 0 1px token.$crm-border-default; background: token.$crm-color-surface; }
.timeline-toolbar :deep(.el-select__placeholder),
.timeline-toolbar :deep(.el-select__selected-item) { color: token.$crm-text-primary; font-size: 11px; }

.timeline-table-head,
.timeline-row {
  box-sizing: border-box;
  display: grid;
  grid-template-columns: 92px 66px 230px 80px minmax(0, 1fr);
  padding-left: 16px;
}

.timeline-table-head {
  height: 40px;
  align-items: center;
  color: token.$crm-text-secondary;
  background: token.$crm-color-subtle;
  font-size: 10px;
  font-weight: 500;
  line-height: 16px;
}

.timeline-table-body {
  position: relative;
  height: 546px;
}

.timeline-row {
  height: 54px;
  box-sizing: border-box;
  align-items: center;
  border-bottom: 1px solid token.$crm-border-subtle;
}

.timeline-row > * { min-width: 0; }
.timeline-row time { display: flex; flex-direction: column; justify-content: center; color: token.$crm-text-secondary; font-size: 10px; font-style: normal; line-height: 15px; }
.timeline-type-cell { display: flex; align-items: center; }
.timeline-type-cell :deep(.customer-activity-tag) { font-size: 11px; }
.timeline-summary { display: block; overflow: hidden; padding-right: 12px; color: token.$crm-text-primary; font-size: 11px; font-weight: 500; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.timeline-owner { overflow: hidden; padding-right: 10px; color: token.$crm-text-secondary; font-size: 10px; line-height: 16px; text-overflow: ellipsis; white-space: nowrap; }
.timeline-related-link,
.timeline-related-empty { min-width: 0; overflow: hidden; padding-right: 8px; color: token.$crm-text-muted; font-size: 10px; font-weight: 500; line-height: 16px; text-overflow: ellipsis; white-space: nowrap; }
.timeline-related-link { width: fit-content; max-width: calc(100% - 8px); padding-left: 0; border: 0; color: token.$crm-primary; background: transparent; font-family: inherit; text-align: left; cursor: pointer; }
.timeline-related-link:hover { text-decoration: underline; }
.timeline-related-link:focus-visible { border-radius: 2px; outline: 2px solid token.$crm-primary; outline-offset: 2px; }

.timeline-footer {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  color: token.$crm-text-secondary;
  font-size: 11px;
  line-height: 18px;
}

.timeline-footer > div { display: flex; align-items: center; gap: 8px; font-size: 10px; font-weight: 500; }
.timeline-footer button { width: 24px; height: 24px; padding: 0; border: 1px solid transparent; border-radius: 4px; color: token.$crm-text-secondary; background: transparent; font: inherit; }
.timeline-footer button.active { border-color: token.$crm-primary; color: token.$crm-primary; }

.overview-right-rail {
  height: 694px;
  display: grid;
  grid-template-rows: 320px 360px;
  gap: 14px;
}

.action-table-head,
.action-row {
  display: grid;
  grid-template-columns: 26px 142px 302px 100px 104px;
  padding-left: 16px;
}

.action-table-head {
  height: 40px;
  align-items: center;
  color: token.$crm-text-secondary;
  background: token.$crm-color-subtle;
  font-size: 10px;
  font-weight: 500;
  line-height: 16px;
}

.action-table-head span:nth-child(1) { grid-column: 2; }
.action-table-head span:nth-child(2) { grid-column: 3; }
.action-table-head span:nth-child(3) { grid-column: 4; }
.action-table-head span:nth-child(4) { grid-column: 5; }
.action-table-body { position: relative; height: 228px; }

.action-row {
  height: 68px;
  box-sizing: border-box;
  align-items: center;
  border-bottom: 1px solid token.$crm-border-subtle;
  cursor: pointer;
}

.action-row > * { min-width: 0; }
.action-row :deep(.el-checkbox) { width: 14px; height: 14px; margin: 0; }
.action-row :deep(.el-checkbox__inner) { width: 14px; height: 14px; border-color: token.$crm-border-default; border-radius: 2px; }
.action-row time,
.action-row > span { overflow: hidden; color: token.$crm-text-secondary; font-size: 10px; line-height: 16px; text-overflow: ellipsis; white-space: nowrap; }
.action-row > strong { overflow: hidden; padding-right: 12px; color: token.$crm-text-primary; font-size: 11px; font-weight: 500; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.action-row > .soft-tag { justify-self: start; }

.customer-health-panel .panel-title > .soft-tag { margin-right: 25px; }
.health-list { height: 256px; padding: 0 16px; }
.health-row { height: 64px; display: grid; grid-template-columns: 26px 374px minmax(0, 1fr); align-items: center; border-bottom: 1px solid token.$crm-border-subtle; }
.health-row:last-child { border-bottom: 0; }
.health-dot { width: 12px; height: 12px; border-radius: 50%; background: token.$crm-neutral; }
.health-dot.is-success { background: token.$crm-success; }
.health-dot.is-info { background: #4d7088; }
.health-dot.is-warning { background: token.$crm-warning; }
.health-dot.is-danger { background: token.$crm-danger; }
.health-row strong { overflow: hidden; color: token.$crm-text-primary; font-size: 11px; font-weight: 500; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.health-row > span { overflow: hidden; color: token.$crm-text-secondary; font-size: 10px; line-height: 16px; text-overflow: ellipsis; white-space: nowrap; }
.health-footer { height: 48px; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; color: token.$crm-text-secondary; font-size: 10px; line-height: 16px; }
.health-footer :deep(.el-button) { width: 110px; }

.panel-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: token.$crm-text-muted;
  font-size: 11px;
}

.panel-empty--error { color: token.$crm-danger; }
.panel-empty button { padding: 0; border: 0; color: token.$crm-primary; background: transparent; font: inherit; cursor: pointer; }

@media (max-width: 1599px) {
  .customer-overview-v2 { height: 1242px; }

  .overview-metrics {
    width: calc(100% - 48px);
    grid-template-columns: 160px 160px 120px 120px 120px 190px 120px minmax(0, 1fr);
    margin-inline: 24px;
  }

  .overview-layout {
    width: calc(100% - 48px);
    height: 1066px;
    grid-template-columns: 300px minmax(0, 1fr);
    grid-template-rows: 694px 360px;
    margin-inline: 24px;
  }

  .overview-right-rail {
    height: 360px;
    grid-column: 1 / -1;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-template-rows: 360px;
    gap: 12px;
  }

  .action-table-head,
  .action-row { grid-template-columns: 26px 130px minmax(220px, 1fr) 90px 90px; }

  .health-row { grid-template-columns: 26px minmax(250px, 1fr) 180px; }
}

</style>
