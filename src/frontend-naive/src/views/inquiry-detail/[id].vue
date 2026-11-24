<script setup lang="tsx">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { NImage, useThemeVars } from 'naive-ui';
import type { DataTableColumns } from 'naive-ui';
import {
  fetchInquiryDetail,
  fetchInquiryTimeline,
  fetchInquiryTasks,
  fetchInquiryFile,
  inquiryProductImageUrl
} from '@/service/api/inquiry-detail';
import type {
  InquiryDetail,
  InquiryFile,
  InquiryItem,
  InquiryTimelineEvent,
  InquiryTask
} from '@/typings/inquiry-detail';
import { useAuthStore } from '@/store/modules/auth';
import { useRouteStore } from '@/store/modules/route';
import { inquiryStatusType } from '../inquiries/shared';
import {
  inquirySteps,
  inquiryStepIndex,
  safeWebsite,
  formatInquiryTime,
  formatInquiryNumber,
  formatEstimatedAmount,
  currentHandlingRecords,
  handlingStageLabel,
  handlingTargetLabel,
  handlingStatusLabel,
  workCalendarDescription,
  slaPresentation,
  nextStepCopy
} from './shared';
import { inquiryListReturnPath } from './navigation';

defineOptions({ name: 'InquiryDetail' });

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const routeStore = useRouteStore();
const theme = useThemeVars();
const inquiryId = computed(() => String(route.params.id || ''));
const detail = shallowRef<InquiryDetail | null>(null);
const loading = ref(false);
const errorMessage = ref('');
const requiresLogin = ref(false);
const timeline = shallowRef<InquiryTimelineEvent[]>([]);
const timelineLoading = ref(false);
const timelineError = ref('');
const timelinePage = ref(0);
const timelineTotal = ref(0);
const tasks = shallowRef<InquiryTask[]>([]);
const tasksLoading = ref(false);
const tasksError = ref('');
const rulesVisible = ref(false);
const historyVisible = ref(false);
const downloading = ref('');
const downloadError = ref('');
const now = ref(Date.now());
let controller = new AbortController();
let timelineRequest = 0;
let tasksRequest = 0;
const timer = setInterval(() => {
  now.value = Date.now();
}, 30000);

const canTasks = computed(() => auth.isStaticSuper || auth.userInfo.buttons.includes('workflow.view_businesstask'));
const canFiles = computed(
  () =>
    auth.isStaticSuper ||
    (detail.value?.allowed_permissions ?? auth.userInfo.buttons).includes('inquiries.view_inquiryfilelink')
);
const canImages = computed(
  () =>
    auth.isStaticSuper ||
    (detail.value?.allowed_permissions ?? auth.userInfo.buttons).includes('inquiries.view_inquiryitem')
);
const currentSlas = computed(() => currentHandlingRecords(detail.value?.sla || []));
const currentSla = computed(() => currentSlas.value[0]);
const activeOrders = computed(
  () => detail.value?.linked_sales_orders.filter(order => order.status !== 'CANCELLED') || []
);
const sla = computed(() =>
  !currentSla.value && activeOrders.value.length
    ? { label: '已移交销售订单', percentage: null, overdue: false }
    : slaPresentation(currentSla.value, now.value, detail.value?.status || 'DRAFT')
);
const stepIndex = computed(() =>
  detail.value ? inquiryStepIndex(detail.value.status, Boolean(detail.value.owner)) : -1
);
const website = computed(() => safeWebsite(detail.value?.customer_snapshot.website));
const nextStep = computed(() =>
  detail.value ? nextStepCopy(detail.value, currentSla.value) : { title: '', description: '' }
);
const activeTasks = computed(() => tasks.value.filter(task => !['COMPLETED', 'CANCELLED'].includes(task.status)));
const handlingHistory = computed(() =>
  [...(detail.value?.sla || [])].sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at))
);
const ruleRows = computed(() => {
  const rule = detail.value?.handling_time_rule;
  if (!rule) return [];
  const targets: Record<string, number> = {
    ...rule.stage_minutes,
    FIRST_RESPONSE: rule.response_minutes || 0,
    REQUIREMENT_CONFIRMATION: rule.confirmation_minutes || 0
  };
  return [
    'ASSIGNMENT',
    'FIRST_RESPONSE',
    'REQUIREMENT_CONFIRMATION',
    'QUOTE_CREATION',
    'QUOTE_DELIVERY',
    'CUSTOMER_FOLLOW_UP',
    'POST_ACCEPTANCE',
    'SAMPLE_FOLLOW_UP'
  ].map(stage => ({ stage, minutes: targets[stage] || 0 }));
});
const summary = computed(() => {
  const row = detail.value;
  if (!row) return '';
  const trade = [row.trade_term_code, row.trade_term_place].filter(Boolean).join(' ');
  return [
    trade && `贸易条款：${trade}`,
    row.delivery_requirement && `目标交期：${row.delivery_requirement}`,
    `预计订单金额：${formatEstimatedAmount(row)}`
  ]
    .filter(Boolean)
    .join(' · ');
});
const primaryLabel = computed(() => {
  const row = detail.value;
  if (!row) return '';
  if (activeOrders.value.length) return '查看订单';
  if (!row.owner && row.allowed_actions.assign && row.status !== 'DRAFT') return '立即分配';
  if (currentSla.value?.stage_code === 'QUOTE_DELIVERY' && row.linked_quotations.length) return '继续完成报价';
  if (
    currentSla.value?.stage_code === 'POST_ACCEPTANCE' &&
    row.allowed_actions.create_sales_order &&
    row.linked_quotations.some(quote => quote.outcome_status === 'WON' && quote.accepted_version_id)
  )
    return '创建销售订单';
  if (row.status === 'CONVERTED') return row.linked_sales_orders.length ? '查看订单' : '';
  if (row.status === 'DRAFT') return '继续编辑';
  if (row.allowed_actions.attach_contact) return '补充联系人';
  if (row.allowed_actions.respond) return '记录首响';
  if (row.allowed_actions.confirm_requirements) return '确认需求';
  if (row.allowed_actions.create_quotation) return '创建报价';
  if (row.allowed_actions.follow_up) return '记录跟进';
  return '';
});

function plainText(value: string) {
  return new DOMParser().parseFromString(value || '', 'text/html').body.textContent?.trim() || '';
}
function money(value: string | number | null, currency: string) {
  return value === null || value === '' ? '待确认' : `${currency} ${formatInquiryNumber(value, 2)}`.trim();
}
const productColumns: DataTableColumns<InquiryItem> = [
  {
    key: 'product_category_name',
    title: '类别',
    width: 70,
    ellipsis: { tooltip: true },
    render: row => row.product_category_name || '—'
  },
  {
    key: 'product_description',
    title: '品名',
    width: 120,
    ellipsis: { tooltip: true }
  },
  {
    key: 'specification',
    title: '规格',
    width: 120,
    ellipsis: { tooltip: true },
    render: row => row.specification || '—'
  },
  {
    key: 'color',
    title: '颜色',
    width: 70,
    ellipsis: { tooltip: true },
    render: row => row.color || '—'
  },
  {
    key: 'material',
    title: '材质',
    width: 70,
    ellipsis: { tooltip: true },
    render: row => row.material || '—'
  },
  {
    key: 'quantity',
    title: '数量 / 单位',
    width: 100,
    render: row => `${formatInquiryNumber(row.quantity)} ${row.unit_code}`
  },
  {
    key: 'target_unit_price',
    title: '目标价',
    width: 100,
    render: row => money(row.target_unit_price, row.target_currency_code)
  },
  {
    key: 'expected_date',
    title: '期望日期',
    width: 100,
    render: row => row.expected_date || '—'
  },
  {
    key: 'image',
    title: '图片',
    width: 60,
    render: row =>
      row.id && row.product_image_id ? (
        canImages.value ? (
          <NImage
            width={28}
            height={28}
            objectFit="contain"
            src={`${inquiryProductImageUrl(row.id)}?v=${row.product_image_id}`}
            alt={`${row.product_description}产品图片`}
          />
        ) : (
          '无权限'
        )
      ) : (
        '无图'
      )
  },
  {
    key: 'notes',
    title: '备注',
    width: 90,
    ellipsis: { tooltip: true },
    render: row => row.notes || '—'
  }
];

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '读取询盘失败，请稍后重试。';
}
function sessionExpired(error: unknown) {
  if (!(error instanceof Error) || !('status' in error) || error.status !== 401) return false;
  detail.value = null;
  timeline.value = [];
  tasks.value = [];
  requiresLogin.value = true;
  errorMessage.value = 'ERP 登录已失效，请登录后重试。';
  controller.abort();
  return true;
}
async function loadTimeline(append = false) {
  if (!detail.value || timelineLoading.value) return;
  const signal = controller.signal;
  const request = ++timelineRequest;
  const id = inquiryId.value;
  timelineLoading.value = true;
  timelineError.value = '';
  try {
    const result = await fetchInquiryTimeline(id, append ? timelinePage.value + 1 : 1, signal);
    if (signal.aborted || request !== timelineRequest) return;
    timeline.value = append ? [...timeline.value, ...result.data] : result.data;
    timelinePage.value = result.meta.page;
    timelineTotal.value = result.meta.total;
  } catch (error) {
    if (!signal.aborted && !sessionExpired(error)) timelineError.value = errorText(error);
  } finally {
    if (request === timelineRequest) timelineLoading.value = false;
  }
}
async function loadTasks() {
  if (!detail.value || !canTasks.value || tasksLoading.value) return;
  const signal = controller.signal;
  const request = ++tasksRequest;
  tasksLoading.value = true;
  tasksError.value = '';
  try {
    const result = await fetchInquiryTasks(inquiryId.value, signal);
    if (!signal.aborted && request === tasksRequest) tasks.value = result;
  } catch (error) {
    if (!signal.aborted && !sessionExpired(error)) tasksError.value = errorText(error);
  } finally {
    if (request === tasksRequest) tasksLoading.value = false;
  }
}
async function load() {
  controller.abort();
  controller = new AbortController();
  const signal = controller.signal;
  ++timelineRequest;
  ++tasksRequest;
  loading.value = true;
  detail.value = null;
  timeline.value = [];
  tasks.value = [];
  errorMessage.value = '';
  timelineError.value = '';
  tasksError.value = '';
  downloadError.value = '';
  requiresLogin.value = false;
  timelineLoading.value = false;
  tasksLoading.value = false;
  timelinePage.value = 0;
  timelineTotal.value = 0;
  historyVisible.value = false;
  rulesVisible.value = false;
  try {
    await auth.initUserInfo(true);
    if (signal.aborted) return;
    if (!auth.isLogin) {
      requiresLogin.value = true;
      errorMessage.value = 'ERP 登录已失效，请登录后重试。';
      return;
    }
    if (!routeStore.isInitAuthRoute) await routeStore.initAuthRoute();
    if (signal.aborted) return;
    const result = await fetchInquiryDetail(inquiryId.value, signal);
    if (signal.aborted) return;
    detail.value = result.data;
    loading.value = false;
    void loadTimeline();
    void loadTasks();
  } catch (error) {
    if (!signal.aborted && !sessionExpired(error)) errorMessage.value = errorText(error);
  } finally {
    if (signal === controller.signal) loading.value = false;
  }
}
function actorName(event: InquiryTimelineEvent) {
  const name = event.event_data.actor_display_name || event.event_data.actor_name;
  if (typeof name === 'string') return name;
  return event.event_data.actor_employee_id === detail.value?.owner?.id
    ? detail.value?.owner?.display_name || '业务员'
    : event.event_data.actor_employee_id
      ? '业务员'
      : '系统';
}
function fileSize(bytes: number) {
  return bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
}
function usableFile(file: InquiryFile) {
  return ['CLEAN', 'SKIPPED'].includes(file.scan_status);
}
async function download(file?: InquiryFile) {
  if (!detail.value || downloading.value || !canFiles.value) return;
  const signal = controller.signal;
  const row = detail.value;
  downloading.value = file?.id || 'all';
  downloadError.value = '';
  try {
    const blob = await fetchInquiryFile(row.id, file?.file_id, signal);
    if (signal.aborted) return;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = (file?.original_name || `${row.inquiry_number}-附件.zip`).replace(
      /[<>:"/\\|?*\u0000-\u001f]/g,
      '_'
    );
    try {
      document.body.appendChild(anchor);
      anchor.click();
    } finally {
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  } catch (error) {
    if (!signal.aborted && !sessionExpired(error)) downloadError.value = errorText(error);
  } finally {
    downloading.value = '';
  }
}
function goList() {
  void router.push(inquiryListReturnPath(route.query.returnTo));
}
watch(
  inquiryId,
  () => {
    void load();
  },
  { immediate: true }
);
onUnmounted(() => {
  controller.abort();
  clearInterval(timer);
});
</script>

<template>
  <div
    class="inquiry-detail"
    data-testid="inquiry-detail"
    :style="{
      '--detail-border': theme.borderColor,
      '--detail-muted': theme.textColor3
    }"
  >
    <div class="detail-toolbar">
      <NButton @click="goList">返回询盘列表</NButton><NButton :loading="loading" @click="load">刷新</NButton>
    </div>
    <NSpin :show="loading">
      <NCard v-if="!detail" :bordered="false" class="card-wrapper">
        <NSkeleton v-if="loading" text :repeat="5" />
        <NResult v-else status="error" title="无法读取询盘" :description="errorMessage">
          <template #footer
            ><NButton v-if="requiresLogin" type="primary" @click="auth.resetStore">前往登录</NButton
            ><NButton v-else @click="load">重新加载</NButton></template
          >
        </NResult>
      </NCard>
      <template v-else>
        <header class="detail-heading">
          <div class="heading-copy">
            <h1>询盘 {{ detail.inquiry_number }}</h1>
            <NText depth="3"
              >{{ detail.customer.name }} · {{ detail.customer.country_code || '—' }} ·
              {{ detail.source.display_name || '—' }} · 接收于 {{ formatInquiryTime(detail.received_at) }}</NText
            >
          </div>
          <NSpace class="header-actions" justify="end">
            <NButton v-if="detail.allowed_actions.assign" disabled title="转交操作待接入">转交</NButton>
            <NButton v-if="detail.allowed_actions.mark_invalid" disabled title="标记无效操作待接入">标记无效</NButton>
            <NButton v-if="detail.allowed_actions.create_sample" disabled title="样品流程待接入">创建样品</NButton>
            <NButton v-if="primaryLabel" disabled type="primary" title="该业务操作或关联页面待接入"
              >{{ primaryLabel }}（待接入）</NButton
            >
          </NSpace>
        </header>
        <div v-if="stepIndex >= 0" class="steps-scroll">
          <NSteps class="detail-steps" :current="stepIndex + 1" size="small">
            <NStep v-for="step in inquirySteps" :key="step.code" :title="step.label" />
          </NSteps>
        </div>
        <NAlert
          v-else
          class="detail-steps"
          :type="detail.status === 'DRAFT' ? 'info' : 'warning'"
          :title="detail.status_display"
          >{{ detail.status === 'DRAFT' ? '草稿提交后开始流转' : '当前询盘流程已终止' }}</NAlert
        >
        <div class="detail-grid">
          <NCard :bordered="false" class="detail-dossier card-wrapper" content-style="padding: 0">
            <section class="dossier-section">
              <div class="section-heading">
                <h2>客户需求摘要</h2>
                <NSpace size="small"
                  ><NTag :type="inquiryStatusType(detail.status)" size="small" :bordered="false">{{
                    detail.status_display
                  }}</NTag
                  ><NTag
                    v-if="detail.priority"
                    :type="detail.priority === 'HIGH' ? 'error' : detail.priority === 'MEDIUM' ? 'warning' : 'default'"
                    size="small"
                    :bordered="false"
                    >{{ detail.priority_display }}优先级</NTag
                  ></NSpace
                >
              </div>
              <p class="demand-text">
                {{ plainText(detail.description) || '暂无客户需求备注' }}
              </p>
              <NText depth="3">{{ summary }}</NText>
            </section>
            <section class="dossier-section products-section">
              <h2>产品需求明细</h2>
              <NDataTable
                class="products-table"
                size="small"
                :columns="productColumns"
                :data="detail.items"
                :row-key="(row: InquiryItem) => row.id || row.line_number || row.product_description"
                :scroll-x="900"
                :max-height="270"
                :single-line="false"
                :bordered="true"
              />
            </section>
            <section class="dossier-section">
              <div class="section-heading">
                <h2>附件 ({{ detail.files.length }})</h2>
                <NButton
                  v-if="detail.files.length && canFiles"
                  size="small"
                  :loading="downloading === 'all'"
                  :disabled="Boolean(downloading)"
                  @click="download()"
                  >全部下载</NButton
                >
              </div>
              <div v-if="detail.files.length" class="attachment-grid">
                <NButton
                  v-for="file in detail.files"
                  :key="file.id"
                  class="attachment-button"
                  :disabled="!canFiles || !usableFile(file) || Boolean(downloading)"
                  :loading="downloading === file.id"
                  :title="
                    !canFiles ? '无附件下载权限' : !usableFile(file) ? '附件尚未通过安全扫描' : file.original_name
                  "
                  @click="download(file)"
                  ><span class="file-caption"
                    ><strong>{{ file.original_name }}</strong
                    ><small>{{
                      usableFile(file)
                        ? `${file.scan_status === 'SKIPPED' ? '内部上传，未扫描' : '已上传'} · ${fileSize(file.size_bytes)}`
                        : '暂不可下载'
                    }}</small></span
                  ></NButton
                >
              </div>
              <NEmpty v-else size="small" description="暂无附件" class="section-empty" />
              <NAlert v-if="downloadError" type="error" class="mt-12px">{{ downloadError }}</NAlert>
            </section>
            <section class="dossier-section" data-testid="timeline-panel">
              <h2>最近沟通</h2>
              <NSpin :show="timelineLoading"
                ><div class="timeline-scroll">
                  <NTimeline v-if="timeline.length"
                    ><NTimelineItem
                      v-for="event in timeline"
                      :key="event.id"
                      :type="event.source_type === 'CUSTOMER_COMMUNICATION' ? 'info' : 'default'"
                      :title="event.title"
                      :time="`${actorName(event)} · ${formatInquiryTime(event.occurred_at)}`"
                      ><p class="communication-text">
                        {{ plainText(event.summary) || '—' }}
                      </p></NTimelineItem
                    ></NTimeline
                  ><NEmpty
                    v-else-if="!timelineLoading && !timelineError"
                    size="small"
                    description="暂无沟通记录"
                  /></div
              ></NSpin>
              <NAlert v-if="timelineError" type="error" class="mt-12px"
                >{{ timelineError }}
                <div class="mt-8px"><NButton size="small" @click="loadTimeline()">重试沟通记录</NButton></div></NAlert
              >
              <NSpace class="mt-12px"
                ><NButton
                  v-if="detail.allowed_actions.respond || detail.allowed_actions.follow_up"
                  disabled
                  title="沟通录入待接入"
                  >添加沟通记录</NButton
                ><NButton v-if="timeline.length < timelineTotal" :loading="timelineLoading" @click="loadTimeline(true)"
                  >加载更多记录</NButton
                ></NSpace
              >
            </section>
          </NCard>
          <aside class="detail-rail">
            <NCard title="处理时限与进度" size="small" :bordered="false" class="card-wrapper"
              ><template #header-extra
                ><NButton text type="primary" @click="rulesVisible = true">查看规则与记录</NButton></template
              >
              <div class="sla-heading">
                <NText strong :type="sla.overdue ? 'error' : undefined">{{ sla.label }}</NText
                ><NText depth="3">{{
                  currentSla
                    ? handlingStageLabel(currentSla.stage_code)
                    : detail.handling_time_rule
                      ? '新开始的阶段按规则计时'
                      : '未配置处理时限'
                }}</NText>
              </div>
              <NProgress
                v-if="sla.percentage !== null"
                class="mt-12px"
                type="line"
                :percentage="sla.percentage"
                :show-indicator="false"
                :status="sla.overdue ? 'error' : 'default'"
              />
              <p v-if="currentSla?.work_calendar" class="muted mt-8px">按工作时间计算 · 午休及休息时间不计时</p>
              <div class="sla-dates">
                <span>开始：{{ formatInquiryTime(currentSla?.started_at) }}</span
                ><span>截止：{{ formatInquiryTime(currentSla?.next_deadline_at) }}</span>
              </div>
              <div v-for="record in currentSlas.slice(1)" :key="record.id" class="separated">
                <NText strong>{{ handlingStageLabel(record.stage_code) }}</NText>
                <p>{{ slaPresentation(record, now, detail.status).label }}</p>
                <small class="muted">同时计时 · 截止 {{ formatInquiryTime(record.next_deadline_at) }}</small>
              </div>
            </NCard>
            <NCard title="当前负责人" size="small" :bordered="false" class="card-wrapper"
              ><div class="owner-row">
                <NAvatar round>{{ detail.owner?.display_name.slice(0, 1) || '—' }}</NAvatar
                ><NText class="owner-name">{{ detail.owner?.display_name || '未分配' }}</NText
                ><NButton size="small" :aria-expanded="historyVisible" @click="historyVisible = !historyVisible">{{
                  historyVisible ? '收起历史' : '查看历史'
                }}</NButton>
              </div>
              <div v-if="historyVisible" class="assignment-history">
                <NEmpty v-if="!detail.assignment_history.length" size="small" description="暂无分配历史" />
                <div v-for="record in detail.assignment_history" :key="record.id" class="separated">
                  <NText strong
                    >{{ record.previous_owner?.display_name || '未分配' }} →
                    {{ record.new_owner?.display_name || '未分配' }}</NText
                  >
                  <p class="muted">
                    {{ formatInquiryTime(record.assigned_at) }}
                  </p>
                  <p v-if="record.assignment_reason">
                    {{ record.assignment_reason }}
                  </p>
                </div>
              </div>
            </NCard>
            <NCard title="下一步行动" size="small" :bordered="false" class="card-wrapper" data-testid="tasks-panel"
              ><NText strong>{{ nextStep.title }}</NText>
              <p class="muted mt-8px">{{ nextStep.description }}</p>
              <small v-if="currentSla?.next_deadline_at && sla.percentage !== null"
                >截止时间：{{ formatInquiryTime(currentSla.next_deadline_at) }}</small
              >
              <div v-if="primaryLabel" class="next-action-button">
                <NButton disabled title="该业务操作或关联页面待接入">{{ primaryLabel }}（待接入）</NButton>
              </div>
              <NSpin :show="tasksLoading"
                ><div v-if="activeTasks.length" class="separated">
                  <div v-for="task in activeTasks" :key="task.id" class="related-item">
                    <NText>{{ task.title }}</NText
                    ><NTag size="small">{{ task.status_display }}</NTag
                    ><small class="muted">{{ formatInquiryTime(task.due_at) }} · 任务详情待接入</small>
                  </div>
                </div></NSpin
              >
              <NAlert v-if="tasksError" type="error" class="mt-12px"
                >{{ tasksError }}
                <div class="mt-8px"><NButton size="small" @click="loadTasks">重试相关任务</NButton></div></NAlert
              >
              <p v-if="!canTasks" class="muted mt-12px">当前账号无查看相关任务权限</p>
            </NCard>
            <NCard title="相关信息" size="small" :bordered="false" class="card-wrapper"
              ><NDescriptions :column="1" label-placement="left" label-style="width: 90px" size="small"
                ><NDescriptionsItem label="客户"
                  >{{ detail.customer.name
                  }}<NButton text type="primary" class="ml-8px" @click="router.push(`/customers/${detail.customer.id}`)">查看客户 →</NButton></NDescriptionsItem
                ><NDescriptionsItem label="国家/地区">{{ detail.customer.country_code || '—' }}</NDescriptionsItem
                ><NDescriptionsItem label="来源">{{ detail.source.display_name || '—' }}</NDescriptionsItem
                ><NDescriptionsItem label="客户网站"
                  ><a v-if="website" :href="website" target="_blank" rel="noopener noreferrer">{{ website }}</a
                  ><span v-else>—</span></NDescriptionsItem
                ><NDescriptionsItem label="询盘编号">{{ detail.inquiry_number }}</NDescriptionsItem
                ><NDescriptionsItem label="接收时间">{{ formatInquiryTime(detail.received_at) }}</NDescriptionsItem
                ><NDescriptionsItem label="联系人">{{
                  detail.customer_contact_summary?.display_name || '未填写'
                }}</NDescriptionsItem></NDescriptions
              >
              <div
                v-if="
                  detail.linked_quotations.length || detail.linked_samples.length || detail.linked_sales_orders.length
                "
                class="separated"
              >
                <h3>关联单据</h3>
                <div v-for="quote in detail.linked_quotations" :key="quote.id" class="related-item">
                  <NText>报价 {{ quote.quotation_number }}</NText
                  ><NTag v-if="quote.accepted_version_id && quote.outcome_status === 'WON'" size="small" type="success"
                    >客户已接受</NTag
                  >
                </div>
                <div v-for="sample in detail.linked_samples" :key="sample.id" class="related-item">
                  样品 {{ sample.request_number }}<NTag size="small">{{ sample.status_display }}</NTag>
                </div>
                <div v-for="order in detail.linked_sales_orders" :key="order.id" class="related-item">
                  销售订单 {{ order.order_number }}<NTag size="small">{{ order.status_display }}</NTag>
                </div>
                <small class="muted">关联单据详情待接入</small>
              </div>
            </NCard>
          </aside>
        </div>
      </template>
    </NSpin>
    <NModal
      v-model:show="rulesVisible"
      preset="card"
      title="处理时限规则与记录"
      :style="{
        width: '680px',
        maxWidth: 'calc(100vw - 32px)',
        '--detail-border': theme.borderColor,
        '--detail-muted': theme.textColor3
      }"
      :draggable="true"
    >
      <div v-if="detail" class="rules-content">
        <NAlert type="info" title="北京时间 · 当前规则和各阶段实际计时记录" class="mb-16px" />
        <template v-if="detail.handling_time_rule"
          ><h3>{{ detail.handling_time_rule.name }}</h3>
          <NDescriptions :column="1" label-placement="left" class="mt-12px"
            ><NDescriptionsItem v-for="rule in ruleRows" :key="rule.stage" :label="handlingStageLabel(rule.stage)">{{
              handlingTargetLabel(rule.minutes)
            }}</NDescriptionsItem></NDescriptions
          >
          <p class="mt-12px">
            {{
              detail.handling_time_rule.work_calendar
                ? workCalendarDescription(detail.handling_time_rule.work_calendar)
                : '本规则按连续时间计算。'
            }}
          </p>
          <p v-if="detail.handling_time_rule.work_calendar" class="muted">
            大小周交替，周日固定休息；{{ detail.handling_time_rule.work_calendar.rest_saturday }}
            为休息的周六基准。午休、下班和休息日不计时。
          </p>
          <p class="muted mt-8px">
            分配与首次回复同时计时；转交和草稿修改不重置计时。规则修改仅影响新开始的环节，已有记录保留原截止时间。
          </p></template
        >
        <NEmpty v-else size="small" description="暂未配置处理时限" />
        <h3 class="mt-20px">阶段处理记录</h3>
        <NEmpty
          v-if="!handlingHistory.length"
          size="small"
          description="暂无计时记录，历史询盘不会追溯计算超时"
          class="mt-12px"
        />
        <section v-for="record in handlingHistory" :key="record.id" class="separated">
          <NText strong
            >{{ handlingStageLabel(record.stage_code) }} ·
            {{ handlingStatusLabel(record.status, record.completed_at, record.next_deadline_at, now) }}</NText
          >
          <p v-if="record.progress_context?.round_number">
            第 {{ record.progress_context.round_number }} 轮 ·
            {{ record.progress_context.source_label }}
          </p>
          <p v-if="record.progress_context?.entry_reason" class="muted">
            {{ record.progress_context.entry_reason }}
          </p>
          <p v-if="record.progress_context?.completion_reason">
            {{ record.progress_context.completion_reason }}
          </p>
          <p class="muted">
            {{ record.work_calendar ? '按工作时间' : '按原连续时间规则' }}计算<span v-if="record.target_minutes">
              · 目标 {{ record.target_minutes / 60 }} 小时</span
            >
          </p>
          <p>
            开始：{{ formatInquiryTime(record.started_at) }} · 截止：{{ formatInquiryTime(record.next_deadline_at) }}
          </p>
          <p>完成：{{ formatInquiryTime(record.completed_at) }}</p>
        </section>
      </div>
      <template #footer
        ><div class="flex justify-end">
          <NButton @click="rulesVisible = false">知道了</NButton>
        </div></template
      >
    </NModal>
  </div>
</template>

<style scoped>
.inquiry-detail {
  min-width: 0;
}
.detail-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}
.detail-heading {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 24px;
}
.heading-copy {
  min-width: 0;
  overflow-wrap: anywhere;
}
h1 {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.4;
}
h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  line-height: 24px;
}
h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}
p {
  margin: 0;
}
.header-actions {
  max-width: 55%;
  flex-shrink: 0;
}
.steps-scroll {
  overflow-x: auto;
  margin-bottom: 20px;
}
.detail-steps {
  min-width: 680px;
}
.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 524px;
  align-items: start;
  gap: 12px;
}
.detail-dossier,
.detail-rail {
  min-width: 0;
}
.detail-rail {
  display: grid;
  gap: 12px;
}
.dossier-section {
  padding: 16px;
  min-width: 0;
}
.dossier-section + .dossier-section {
  border-top: 1px solid var(--detail-border);
}
.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.demand-text {
  margin: 12px 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.products-table {
  margin-top: 12px;
}
.products-section {
  min-height: 210px;
}
.attachment-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
.attachment-button {
  width: 100%;
  height: auto;
  min-height: 60px;
}
.file-caption {
  display: flex;
  flex-direction: column;
  gap: 6px;
  white-space: normal;
  overflow-wrap: anywhere;
  text-align: left;
}
.section-empty {
  padding: 20px 0 8px;
}
.timeline-scroll {
  max-height: 255px;
  overflow: auto;
  margin-top: 16px;
  padding: 2px;
}
.communication-text {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.sla-heading,
.owner-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.sla-dates {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  font-size: 12px;
  margin-top: 12px;
  color: var(--detail-muted);
}
.owner-name {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.assignment-history {
  max-height: 280px;
  overflow: auto;
  margin-top: 12px;
}
.separated {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--detail-border);
  overflow-wrap: anywhere;
}
.next-action-button {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
.related-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 8px 0;
  overflow-wrap: anywhere;
}
.related-item small {
  width: 100%;
}
.muted {
  color: var(--detail-muted);
  font-size: 12px;
}
.detail-rail :deep(.n-descriptions-table-content) {
  overflow-wrap: anywhere;
}
.rules-content {
  max-height: min(640px, calc(100dvh - 200px));
  overflow: auto;
}
.rules-content p {
  margin-top: 6px;
}
@media (max-width: 1199px) {
  .detail-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
@media (max-width: 639px) {
  .detail-heading {
    flex-direction: column;
  }
  .header-actions {
    max-width: 100%;
  }
  h1 {
    font-size: 20px;
  }
}
</style>
