<script setup lang="ts">
import { computed, onUnmounted, reactive, ref, shallowRef, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  fetchCustomerDetail,
  fetchCustomerSummary,
  fetchCustomerContacts,
  fetchCustomerTimeline,
  fetchCustomerRecords,
  fetchCustomerEntities,
  fetchCustomerEntityAddresses
} from '@/service/api/customer-detail';
import type {
  CustomerDetail,
  CustomerSummary,
  CustomerContact,
  CustomerTimelineEvent,
  CustomerTask,
  CustomerAddress,
  CustomerRecordKind
} from '@/typings/customer-detail';
import { useAuthStore } from '@/store/modules/auth';
import { useRouteStore } from '@/store/modules/route';
import { formatInquiryTime } from '../inquiry-detail/shared';
import { customerTab, customerTabs, customerListReturnPath } from './navigation';
import type { CustomerTab } from './navigation';
import CustomerOverview from './modules/customer-overview.vue';
import CustomerContacts from './modules/customer-contacts.vue';
import CustomerTimeline from './modules/customer-timeline.vue';
import CustomerRecords from './modules/customer-records.vue';

defineOptions({ name: 'CustomerDetail' });
const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const routes = useRouteStore();
const customerId = computed(() => String(route.params.id || ''));
const tab = computed(() => customerTab(route.query.tab));
const labels: Record<CustomerTab, string> = {
  overview: '概览',
  contacts: '联系人',
  timeline: '时间轴',
  tasks: '任务',
  inquiries: '询盘',
  quotations: '报价',
  samples: '样品',
  orders: '订单',
  complaints: '客诉'
};
const customer = shallowRef<CustomerDetail | null>(null);
const summary = shallowRef<CustomerSummary | null>(null);
const contacts = shallowRef<CustomerContact[]>([]);
const timeline = shallowRef<CustomerTimelineEvent[]>([]);
const tasks = shallowRef<CustomerTask[]>([]);
const addresses = shallowRef<CustomerAddress[]>([]);
const errors = reactive<Record<string, string>>({});
const loading = ref(false);
const overviewLoading = ref(false);
const overviewLoaded = ref(false);
const addressReady = ref(false);
const error = ref('');
const requiresLogin = ref(false);
const refreshVersion = ref(0);
let controller = new AbortController();
let overviewController = new AbortController();
let overviewGeneration = 0;
let loadedIdentity = '';
const permissionMap: Record<CustomerTab, string> = {
  overview: 'customers.view_customeraccount',
  contacts: 'customers.view_customercontact',
  timeline: 'crm.view_customertimelineevent',
  tasks: 'workflow.view_businesstask',
  inquiries: 'inquiries.view_inquiry',
  quotations: 'quotations.view_quotation',
  samples: 'samples.view_samplerequest',
  orders: 'sales_orders.view_salesorder',
  complaints: 'customers.view_customercomplaint'
};
function canRead(permission: string) {
  return auth.isStaticSuper || (customer.value?.allowed_permissions ?? auth.userInfo.buttons).includes(permission);
}
// 任务的数据范围由任务模块的全局权限决定，最终仍由后端校验。
const canTasks = computed(() => auth.isStaticSuper || auth.userInfo.buttons.includes('workflow.view_businesstask'));
const scope = computed<'ALL' | 'TEAM' | 'ME'>(() =>
  auth.isStaticSuper || auth.userInfo.buttons.includes('workflow.view_all_businesstask')
    ? 'ALL'
    : auth.userInfo.buttons.includes('workflow.view_team_businesstask')
      ? 'TEAM'
      : 'ME'
);
const recordKind = computed(() =>
  ['tasks', 'inquiries', 'quotations', 'samples', 'orders', 'complaints'].includes(tab.value)
    ? (tab.value as CustomerRecordKind)
    : null
);
const currentCanRead = computed(() => (tab.value === 'tasks' ? canTasks.value : canRead(permissionMap[tab.value])));
const profileCompleteness = computed(() => {
  const row = customer.value;
  if (!row || !addressReady.value) return null;
  const values = [
    row.account_name,
    row.english_name,
    row.short_name,
    row.primary_country_code,
    row.primary_website_url,
    row.customer_grade?.id,
    row.latest_source?.id,
    row.customer_types.length,
    row.customer_tags.length,
    addresses.value[0]?.address_line1,
    addresses.value[0]?.city
  ];
  return Math.round((values.filter(Boolean).length / values.length) * 100);
});
const activityType = computed(() =>
  customer.value?.activity?.activity_status === 'HIGH_RISK'
    ? 'error'
    : customer.value?.activity?.activity_status === 'FOLLOW_UP'
      ? 'warning'
      : customer.value?.activity?.activity_status === 'ACTIVE'
        ? 'success'
        : 'default'
);

function expired() {
  controller.abort();
  overviewController.abort();
  ++overviewGeneration;
  customer.value = null;
  summary.value = null;
  contacts.value = [];
  timeline.value = [];
  tasks.value = [];
  loading.value = false;
  overviewLoading.value = false;
  requiresLogin.value = true;
  error.value = 'ERP 登录已失效，请重新登录。';
}
function message(value: unknown) {
  if (value instanceof Error && 'status' in value && value.status === 401) expired();
  return value instanceof Error ? value.message : '读取客户资料失败，请重试。';
}
function identity() {
  return JSON.stringify([auth.userInfo.userId, [...auth.userInfo.roles].sort(), [...auth.userInfo.buttons].sort()]);
}
async function beforeRead(signal: AbortSignal) {
  await auth.initUserInfo(true);
  if (auth.loginError) {
    if (signal.aborted) return false;
    throw new Error(auth.loginError);
  }
  if (!auth.isLogin) {
    expired();
    return false;
  }
  // 两个前端共享Cookie，换账号或权限后不能拼接旧身份的数据。
  if (identity() !== loadedIdentity) {
    void load();
    return false;
  }
  // 权限变化可能先触发子组件取消请求，身份失效仍须清空父页。
  return !signal.aborted;
}
async function loadOverview() {
  if (!customer.value || overviewLoading.value) return;
  overviewController.abort();
  overviewController = new AbortController();
  const signal = overviewController.signal;
  const id = customerId.value;
  const generation = ++overviewGeneration;
  overviewLoading.value = true;
  summary.value = null;
  contacts.value = [];
  timeline.value = [];
  tasks.value = [];
  for (const key of ['summary', 'contacts', 'timeline', 'tasks']) errors[key] = '';
  async function read<T>(key: string, request: () => Promise<T>, apply: (value: T) => void) {
    try {
      if (!(await beforeRead(signal))) return;
      const value = await request();
      if (!signal.aborted) apply(value);
    } catch (value) {
      if (!signal.aborted) errors[key] = message(value);
    }
  }
  const reads: Promise<void>[] = [
    read(
      'summary',
      () => fetchCustomerSummary(id, signal),
      (value) => {
        summary.value = value;
        if (!canTasks.value || !canRead(permissionMap.complaints))
          errors.summary = '部分任务或客诉数据无查看权限，无法作完整健康判断。';
      }
    )
  ];
  if (canRead(permissionMap.contacts))
    reads.push(
      read(
        'contacts',
        () => fetchCustomerContacts(id, { page: 1, page_size: 100 }, signal),
        (value) => {
          contacts.value = value.data;
        }
      )
    );
  else errors.contacts = '当前账号无权查看联系人。';
  if (canRead(permissionMap.timeline))
    reads.push(
      read(
        'timeline',
        () => fetchCustomerTimeline(id, {}, signal),
        (value) => {
          timeline.value = value.data;
        }
      )
    );
  else errors.timeline = '当前账号无权查看客户时间轴。';
  if (canTasks.value)
    reads.push(
      read(
        'tasks',
        () =>
          Promise.all(
            ['PENDING', 'IN_PROGRESS'].map((status) =>
              fetchCustomerRecords('tasks', id, { status, page: 1, page_size: 100, scope: scope.value }, signal)
            )
          ),
        (results) => {
          tasks.value = results.flatMap((value) => value.data);
        }
      )
    );
  await Promise.all(reads);
  if (!signal.aborted) overviewLoaded.value = true;
  if (generation === overviewGeneration) overviewLoading.value = false;
}
async function loadAddresses(signal: AbortSignal) {
  addressReady.value = false;
  addresses.value = [];
  errors.addresses = '';
  try {
    if (!(await beforeRead(signal))) return;
    const entities = await fetchCustomerEntities(customerId.value, signal);
    if (signal.aborted) return;
    const first = entities[0];
    const result = first ? await fetchCustomerEntityAddresses(first.id, signal) : [];
    if (!signal.aborted) {
      addresses.value = result;
      addressReady.value = true;
    }
  } catch (value) {
    if (!signal.aborted) errors.addresses = message(value);
  }
}
async function load() {
  controller.abort();
  overviewController.abort();
  ++overviewGeneration;
  controller = new AbortController();
  const signal = controller.signal;
  loading.value = true;
  error.value = '';
  requiresLogin.value = false;
  customer.value = null;
  summary.value = null;
  contacts.value = [];
  timeline.value = [];
  tasks.value = [];
  addresses.value = [];
  overviewLoaded.value = false;
  overviewLoading.value = false;
  addressReady.value = false;
  for (const key of Object.keys(errors)) delete errors[key];
  ++refreshVersion.value;
  try {
    await auth.initUserInfo(true);
    if (signal.aborted) return;
    if (auth.loginError) throw new Error(auth.loginError);
    if (!auth.isLogin) {
      expired();
      return;
    }
    loadedIdentity = identity();
    if (!routes.isInitAuthRoute) await routes.initAuthRoute();
    if (signal.aborted) return;
    const result = await fetchCustomerDetail(customerId.value, signal);
    if (signal.aborted) return;
    customer.value = result.data;
    void loadAddresses(signal);
    if (tab.value === 'overview') void loadOverview();
  } catch (value) {
    if (!signal.aborted) error.value = message(value);
  } finally {
    if (signal === controller.signal) loading.value = false;
  }
}
function openTab(value: string) {
  const selected = customerTab(value);
  void router.replace({ path: route.path, query: { ...route.query, tab: selected } });
}
function openInquiry(id: string) {
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) void router.push(`/inquiries/${id}`);
}
function goList() {
  void router.push(customerListReturnPath(route.query.returnTo));
}
watch(customerId, load, { immediate: true });
watch(tab, (value) => {
  if (value === 'overview' && customer.value && !overviewLoaded.value) void loadOverview();
});
onUnmounted(() => {
  controller.abort();
  overviewController.abort();
});
</script>

<template>
  <div class="customer-detail" data-testid="customer-detail">
    <div class="detail-toolbar">
      <NButton @click="goList">返回客户列表</NButton><NButton :loading="loading" @click="load">刷新</NButton>
    </div>
    <NCard v-if="!customer" :bordered="false" class="card-wrapper">
      <NSkeleton v-if="loading" text :repeat="5" />
      <NResult v-else status="error" title="无法读取客户" :description="error"
        ><template #footer
          ><NButton v-if="requiresLogin" type="primary" @click="auth.resetStore">前往登录</NButton
          ><NButton v-else @click="load">重新加载</NButton></template
        ></NResult
      >
    </NCard>
    <template v-else>
      <NCard :bordered="false" class="card-wrapper customer-heading">
        <h1>{{ customer.account_name }}</h1>
        <NSpace align="center" class="mt-8px" wrap>
          <NText depth="3">{{ customer.account_code }}</NText>
          <NText>{{
            customer.secondary_region?.region_name ||
            customer.primary_region?.region_name ||
            customer.primary_country_code ||
            '地区未录入'
          }}</NText>
          <NTag type="primary" size="small" :bordered="false">{{
            customer.customer_grade?.display_name || '未定级'
          }}</NTag>
          <NTag :type="activityType" size="small" :bordered="false">{{
            customer.activity?.display_name || '数据不足'
          }}</NTag>
          <NText>负责人：{{ customer.primary_owner?.display_name || '未分配' }}</NText>
          <NTag v-for="type in customer.customer_types" :key="type.id" size="small" :bordered="false">{{
            type.display_name
          }}</NTag>
          <NText :title="errors.addresses || ''"
            >资料完整度：{{ profileCompleteness === null ? '—' : `${profileCompleteness}%` }}</NText
          >
        </NSpace>
        <NSpace class="mt-16px" wrap>
          <NButton disabled type="primary">记录沟通（待接入）</NButton><NButton disabled>新建询盘（待接入）</NButton
          ><NButton disabled>新建报价（待接入）</NButton><NButton disabled>新建任务（待接入）</NButton
          ><NButton disabled>编辑客户（待接入）</NButton><NButton disabled>客户转移（待接入）</NButton>
        </NSpace>
        <NText depth="3" class="mt-12px block">资料更新于 {{ formatInquiryTime(customer.updated_at) }}</NText>
      </NCard>
      <NAlert v-if="errors.addresses" type="warning"
        >客户地址暂不可用，资料完整度未计算。{{ errors.addresses }}
        <NButton text @click="loadAddresses(controller.signal)">重试地址</NButton></NAlert
      >
      <NTabs :value="tab" type="line" animated :on-update:value="openTab" class="customer-tabs">
        <NTab v-for="name in customerTabs" :key="name" :name="name">{{ labels[name] }}</NTab>
      </NTabs>
      <CustomerOverview
        v-if="tab === 'overview'"
        :customer="customer"
        :summary="summary"
        :contacts="contacts"
        :timeline="timeline"
        :tasks="tasks"
        :loading="overviewLoading"
        :errors="errors"
        :can-view-tasks="canTasks"
        @open-tab="openTab"
        @refresh="loadOverview"
        @open-inquiry="openInquiry"
      />
      <CustomerContacts
        v-else-if="tab === 'contacts'"
        :key="`${customerId}:${refreshVersion}`"
        :customer-id="customerId"
        :can-read="currentCanRead"
        :before-read="beforeRead"
        @expired="expired"
      />
      <CustomerTimeline
        v-else-if="tab === 'timeline'"
        :key="`${customerId}:${refreshVersion}`"
        :customer-id="customerId"
        :can-read="currentCanRead"
        :before-read="beforeRead"
        @expired="expired"
        @open-inquiry="openInquiry"
      />
      <CustomerRecords
        v-else-if="recordKind"
        :key="`${customerId}:${recordKind}:${refreshVersion}`"
        :customer-id="customerId"
        :kind="recordKind"
        :scope="scope"
        :can-read="currentCanRead"
        :before-read="beforeRead"
        @expired="expired"
        @open-inquiry="openInquiry"
      />
    </template>
  </div>
</template>

<style scoped>
.customer-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
.detail-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.customer-heading h1 {
  margin: 0;
  font-size: 24px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.customer-tabs {
  min-width: 0;
}
@media (max-width: 639px) {
  .customer-heading h1 {
    font-size: 20px;
  }
}
</style>
