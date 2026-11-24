<script setup lang="ts">
import { computed, h } from 'vue';
import { NButton, NTag } from 'naive-ui';
import type { DataTableColumns } from 'naive-ui';
import type {
  CustomerContact,
  CustomerDetail,
  CustomerSummary,
  CustomerTask,
  CustomerTimelineEvent
} from '@/typings/customer-detail';
import { formatInquiryTime, safeWebsite } from '../../inquiry-detail/shared';
import {
  buildCustomerHealthSummary,
  calculateCreditUsage,
  contactMethod,
  formatOverviewMoney,
  previewContacts,
  previewTasks,
  timelineCategory
} from '../shared';

defineOptions({ name: 'CustomerOverview' });

const props = defineProps<{
  customer: CustomerDetail;
  summary: CustomerSummary | null;
  contacts: CustomerContact[];
  timeline: CustomerTimelineEvent[];
  tasks: CustomerTask[];
  loading: boolean;
  errors: Record<string, string>;
  canViewTasks: boolean;
}>();

const emit = defineEmits<{
  openTab: [tab: string];
  refresh: [];
  openInquiry: [id: string];
}>();

const snapshot = computed(() => props.customer.business_snapshot);
const creditUsage = computed(() => calculateCreditUsage(snapshot.value?.credit_limit, snapshot.value?.credit_used));
const creditCurrency = computed(() => snapshot.value?.currency_code || '');
const contactPreview = computed(() => previewContacts(props.contacts));
const visibleContacts = computed(() =>
  [contactPreview.value.primary, ...contactPreview.value.others].filter((item): item is CustomerContact =>
    Boolean(item)
  )
);
const visibleTimeline = computed(() => props.timeline.slice(0, 10));
const visibleTasks = computed(() => previewTasks(props.tasks));
const website = computed(() => safeWebsite(props.customer.primary_website_url));
const country = computed(
  () =>
    props.customer.secondary_region?.region_name ||
    props.customer.primary_region?.region_name ||
    props.customer.primary_country_code ||
    '—'
);
const health = computed(() =>
  buildCustomerHealthSummary(props.errors.summary ? null : props.summary, creditUsage.value, formatInteractionTime())
);

function formatInteractionTime(): string | null {
  const value = formatInquiryTime(props.timeline[0]?.occurred_at || props.customer.last_contact_at);
  return value === '—' ? null : value;
}

function openContacts() {
  emit('openTab', 'contacts');
}

function openTimeline() {
  emit('openTab', 'timeline');
}

function openTasks() {
  emit('openTab', 'tasks');
}

function refresh() {
  emit('refresh');
}

function contactRole(contact: CustomerContact): string {
  return (
    contact.position_title ||
    contact.department_name ||
    contact.active_roles.map(item => item.role_type_display).join('、') ||
    '职位未填写'
  );
}

function timelineOwner(event: CustomerTimelineEvent): string {
  const data = event.event_data;
  const name = ['actor_name', 'actor_employee_name', 'owner_name', 'employee_name']
    .map(key => data[key])
    .find(value => typeof value === 'string' && value.trim());
  if (typeof name === 'string') return name;
  return (
    props.customer.current_assignments.find(item => item.employee.id === data.actor_employee_id)?.employee
      .display_name || '—'
  );
}

function renderRelated(event: CustomerTimelineEvent) {
  if (!event.source_id) return '—';
  if (event.source_type === 'INQUIRY') {
    return h(
      NButton,
      { text: true, type: 'primary', onClick: () => emit('openInquiry', event.source_id) },
      { default: () => '查看询盘' }
    );
  }
  const tabs: Record<string, { key: string; label: string }> = {
    QUOTATION: { key: 'quotations', label: '报价列表' },
    QUOTATION_VERSION: { key: 'quotations', label: '报价列表' },
    SAMPLE_REQUEST: { key: 'samples', label: '样品列表' },
    SALES_ORDER: { key: 'orders', label: '订单列表' },
    TASK: { key: 'tasks', label: '任务列表' },
    BUSINESS_TASK: { key: 'tasks', label: '任务列表' },
    CUSTOMER_CONTACT: { key: 'contacts', label: '联系人列表' }
  };
  const target = tabs[event.source_type];
  return target
    ? h(
        NButton,
        { text: true, type: 'primary', onClick: () => emit('openTab', target.key) },
        { default: () => target.label }
      )
    : '—';
}

const timelineColumns: DataTableColumns<CustomerTimelineEvent> = [
  { key: 'occurred_at', title: '日期', width: 150, render: row => formatInquiryTime(row.occurred_at) },
  {
    key: 'event_type',
    title: '类型',
    width: 80,
    render: row => {
      const category = timelineCategory(row);
      return h(NTag, { type: category.tone, size: 'small', bordered: false }, { default: () => category.label });
    }
  },
  {
    key: 'summary',
    title: '内容摘要',
    minWidth: 200,
    ellipsis: { tooltip: true },
    render: row => row.summary || row.title
  },
  { key: 'owner', title: '负责人', width: 100, ellipsis: { tooltip: true }, render: timelineOwner },
  { key: 'related', title: '相关业务', width: 100, render: renderRelated }
];

function rowKey(row: { id: string }): string {
  return row.id;
}
</script>

<template>
  <div class="flex flex-col gap-16px" data-testid="customer-overview">
    <div class="overview-metrics">
      <NCard size="small" :bordered="false" class="card-wrapper">
        <NStatistic label="累计销售额" :value="formatOverviewMoney(customer.lifetime_sales_amount, 'CNY')" />
      </NCard>
      <NCard size="small" :bordered="false" class="card-wrapper">
        <NStatistic label="近12个月销售额" :value="formatOverviewMoney(customer.last_12m_sales_amount, 'CNY')" />
      </NCard>
      <NCard size="small" :bordered="false" class="card-wrapper">
        <NStatistic label="订单" :value="customer.lifetime_sales_order_count ?? '—'" />
      </NCard>
      <NCard size="small" :bordered="false" class="card-wrapper">
        <NStatistic
          label="报价转化率"
          :value="customer.quotation_conversion_rate == null ? '—' : `${customer.quotation_conversion_rate}%`"
        />
      </NCard>
      <NCard size="small" :bordered="false" class="card-wrapper">
        <NStatistic label="毛利率" value="—" />
        <NText depth="3">未接入</NText>
      </NCard>
      <NCard size="small" :bordered="false" class="card-wrapper">
        <NStatistic label="信用额度" :value="formatOverviewMoney(snapshot?.credit_limit, creditCurrency)" />
        <NText depth="3">已用 {{ creditUsage === null ? '—' : `${creditUsage}%` }}</NText>
        <NProgress
          v-if="creditUsage !== null"
          type="line"
          :percentage="Math.min(100, creditUsage)"
          :show-indicator="false"
          :status="creditUsage > 100 ? 'warning' : 'default'"
        />
      </NCard>
      <NCard size="small" :bordered="false" class="card-wrapper">
        <NStatistic label="应收余额" value="—" />
        <NText depth="3">未接入</NText>
      </NCard>
    </div>

    <NCard size="small" :bordered="false" class="card-wrapper">
      <NDescriptions :column="2" label-placement="left">
        <NDescriptionsItem label="最近联系">{{ formatInquiryTime(customer.last_contact_at) }}</NDescriptionsItem>
        <NDescriptionsItem label="下次跟进">{{ formatInquiryTime(customer.next_follow_up_at) }}</NDescriptionsItem>
        <NDescriptionsItem label="当前阶段">{{ customer.lifecycle_stage_display || '—' }}</NDescriptionsItem>
        <NDescriptionsItem label="客户来源">{{ customer.latest_source?.display_name || '—' }}</NDescriptionsItem>
      </NDescriptions>
    </NCard>

    <div class="overview-layout">
      <NCard
        title="客户名片"
        size="small"
        :bordered="false"
        class="card-wrapper min-w-0"
        data-testid="customer-overview-contacts"
      >
        <template #header-extra><NButton text type="primary" @click="openContacts">查看全部</NButton></template>
        <NAlert v-if="errors.contacts" type="error" :show-icon="true">{{ errors.contacts }}</NAlert>
        <NSpin v-else :show="loading">
          <NList v-if="visibleContacts.length" :show-divider="true">
            <NListItem v-for="contact in visibleContacts" :key="contact.id">
              <div class="flex flex-col gap-6px break-words">
                <NSpace align="center">
                  <NText strong>{{ contact.display_name }}</NText>
                  <NTag v-if="contact.is_primary_contact" size="small" :bordered="false" type="info">主要联系人</NTag>
                  <NTag v-else-if="contact.is_key_contact" size="small" :bordered="false" type="info">关键联系人</NTag>
                </NSpace>
                <NText depth="3">{{ contactRole(contact) }}</NText>
                <NText>邮箱：{{ contactMethod(contact, ['EMAIL']) }}</NText>
                <NText>电话：{{ contactMethod(contact, ['MOBILE', 'PHONE']) }}</NText>
              </div>
            </NListItem>
          </NList>
          <NEmpty v-else description="暂无联系人" class="py-16px" />
        </NSpin>
        <NDivider />
        <NDescriptions :column="1" label-placement="left">
          <NDescriptionsItem label="国家/地区">{{ country }}</NDescriptionsItem>
          <NDescriptionsItem label="时区">{{ contactPreview.primary?.timezone_code || '—' }}</NDescriptionsItem>
          <NDescriptionsItem label="客户来源">{{ customer.latest_source?.display_name || '—' }}</NDescriptionsItem>
          <NDescriptionsItem label="网站">
            <NButton
              v-if="website"
              tag="a"
              :href="website"
              target="_blank"
              rel="noopener noreferrer"
              text
              type="primary"
              class="max-w-full break-all"
              >{{ customer.primary_website_url }}</NButton
            >
            <span v-else>{{ customer.primary_website_url || '—' }}</span>
          </NDescriptionsItem>
          <NDescriptionsItem label="客户标签">
            <NSpace v-if="customer.customer_tags.length" :size="4">
              <NTag v-for="tag in customer.customer_tags" :key="tag.id" size="small" :bordered="false">{{
                tag.tag_name
              }}</NTag>
            </NSpace>
            <NSpace v-else-if="customer.customer_types.length" :size="4">
              <NTag v-for="type in customer.customer_types" :key="type.id" size="small" :bordered="false">{{
                type.display_name
              }}</NTag>
            </NSpace>
            <span v-else>—</span>
          </NDescriptionsItem>
          <NDescriptionsItem label="备注"
            ><span class="whitespace-pre-wrap break-words">{{ customer.notes || '暂无备注' }}</span></NDescriptionsItem
          >
        </NDescriptions>
      </NCard>

      <NCard
        title="互动时间轴"
        size="small"
        :bordered="false"
        class="card-wrapper min-w-0"
        data-testid="customer-overview-timeline"
      >
        <template #header-extra><NButton text type="primary" @click="openTimeline">查看全部</NButton></template>
        <NAlert v-if="errors.timeline" type="error" :show-icon="true">{{ errors.timeline }}</NAlert>
        <NDataTable
          v-else
          :columns="timelineColumns"
          :data="visibleTimeline"
          :row-key="rowKey"
          :loading="loading"
          :scroll-x="630"
          size="small"
        >
          <template #empty><NEmpty description="暂无互动记录" /></template>
        </NDataTable>
        <NText depth="3" class="mt-12px block">概览最多展示最近 10 条，完整记录见时间轴页签。</NText>
      </NCard>

      <div class="overview-rail flex flex-col gap-16px min-w-0">
        <NCard
          title="下一步动作"
          size="small"
          :bordered="false"
          class="card-wrapper"
          data-testid="customer-overview-tasks"
        >
          <template #header-extra
            ><NButton text type="primary" :disabled="!canViewTasks" @click="openTasks">查看全部</NButton></template
          >
          <NEmpty v-if="!canViewTasks" description="当前账号无权查看客户任务" />
          <NAlert v-else-if="errors.tasks" type="error" :show-icon="true">{{ errors.tasks }}</NAlert>
          <NSpin v-else :show="loading">
            <NList v-if="visibleTasks.length">
              <NListItem v-for="task in visibleTasks" :key="task.id">
                <div class="flex flex-col gap-6px break-words">
                  <NText strong>{{ task.title }}</NText>
                  <NText depth="3">计划时间：{{ task.due_at ? formatInquiryTime(task.due_at) : '未安排' }}</NText>
                  <NSpace align="center" justify="space-between">
                    <NText>{{ task.assignee?.display_name || '未分配' }}</NText>
                    <NTag :type="task.status === 'PENDING' ? 'warning' : 'info'" size="small" :bordered="false">{{
                      task.status_display || task.status
                    }}</NTag>
                  </NSpace>
                </div>
              </NListItem>
            </NList>
            <NEmpty v-else description="当前客户暂无未完成任务" class="py-16px" />
          </NSpin>
          <NText depth="3" class="mt-12px block">按计划时间预览前 3 项未完成任务。</NText>
        </NCard>

        <NCard
          title="客户健康"
          size="small"
          :bordered="false"
          class="card-wrapper"
          data-testid="customer-overview-health"
        >
          <template #header-extra
            ><NTag :type="health.tone" size="small" :bordered="false">{{ health.label }}</NTag></template
          >
          <NAlert v-if="errors.summary" type="error" :show-icon="true" class="mb-12px">{{ errors.summary }}</NAlert>
          <NList>
            <NListItem v-for="fact in health.facts" :key="fact.label">
              <div class="flex flex-col gap-6px">
                <NText :type="fact.tone === 'default' ? undefined : fact.tone">{{ fact.label }}</NText>
                <NText depth="3">{{ fact.meta }}</NText>
              </div>
            </NListItem>
          </NList>
          <NDescriptions :column="1" label-placement="left" class="mt-12px">
            <NDescriptionsItem label="信用已用">{{
              formatOverviewMoney(snapshot?.credit_used, creditCurrency)
            }}</NDescriptionsItem>
            <NDescriptionsItem label="信用来源">{{ snapshot?.source_type_display || '未提供' }}</NDescriptionsItem>
            <NDescriptionsItem label="来源编号">{{ snapshot?.source_reference || '—' }}</NDescriptionsItem>
            <NDescriptionsItem label="快照截至">{{ formatInquiryTime(snapshot?.as_of_at) }}</NDescriptionsItem>
          </NDescriptions>
          <template #footer>
            <div class="flex flex-wrap items-center justify-between gap-8px">
              <NText depth="3">仅汇总已接入的业务事实</NText>
              <NButton size="small" :loading="loading" @click="refresh">刷新评估</NButton>
            </div>
          </template>
        </NCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overview-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 16px;
}

.overview-metrics :deep(.n-statistic-value__content) {
  overflow-wrap: anywhere;
}

.overview-layout {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(0, 2fr) minmax(270px, 1.15fr);
  gap: 16px;
  align-items: start;
}

@media (max-width: 1440px) {
  .overview-layout {
    grid-template-columns: minmax(220px, 1fr) minmax(0, 2fr);
  }

  .overview-rail {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-column: 1 / -1;
  }
}

@media (max-width: 900px) {
  .overview-layout,
  .overview-rail {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
