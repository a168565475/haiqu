<script setup lang="tsx">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { NButton, NTag } from 'naive-ui';
import type { DataTableSortState } from 'naive-ui';
import { fetchCustomers, fetchCustomerOptions, fetchErpSession } from '@/service/api/customers';
import { useAppStore } from '@/store/modules/app';
import { useAuthStore } from '@/store/modules/auth';
import { useRouteStore } from '@/store/modules/route';
import { useNaivePaginatedTable } from '@/hooks/common/table';
import type { CustomerListItem, CustomerListQuery, CustomerOptions, CustomerPage } from '@/typings/customer';
import { formatDate, formatMoney, getFollowUpStatus } from './shared';
import { customerListQuery, customerListRouteQuery } from '../customer-detail/navigation';

defineOptions({ name: 'CustomerList' });

const appStore = useAppStore();
const authStore = useAuthStore();
const routeStore = useRouteStore();
const route = useRoute();
const router = useRouter();
const initialQuery = customerListQuery(route.query);
const controller = new AbortController();
const filters = ref({
  q: initialQuery.q ?? '',
  customer_grade: initialQuery.customer_grade ?? null as string | null,
  country_code: initialQuery.country_code ?? null as string | null,
  activity_status: initialQuery.activity_status ?? null as CustomerListQuery['activity_status'] | null
});
const appliedFilters = shallowRef({ ...filters.value });
const options = shallowRef<CustomerOptions | null>(null);
const optionsLoading = ref(false);
const optionsError = ref('');
const errorMessage = ref('');
const requiresLogin = ref(false);
const forbidden = ref(false);
const pageUnavailable = ref(false);
const ordering = ref<CustomerListQuery['ordering']>(initialQuery.ordering);
const query = shallowRef<CustomerListQuery>({ page: initialQuery.page, page_size: initialQuery.page_size });
const countryNames = computed(
  () => new Map(options.value?.country_options.map(item => [item.item_code, item.display_name]) ?? [])
);
const countryOptions = computed(
  () => options.value?.country_options.map(item => ({ label: item.display_name, value: item.item_code })) ?? []
);
const gradeOptions = computed(
  () =>
    options.value?.customer_grades.map(item => ({
      label: item.display_name,
      value: item.item_code,
      disabled: item.disabled
    })) ?? []
);
const activityOptions = computed(
  () => options.value?.activity_statuses.map(item => ({ label: item.display_name, value: item.item_code })) ?? []
);

function countryName(code: string): string {
  return countryNames.value.get(code) || code || '—';
}

function activityTag(row: CustomerListItem) {
  const status = row.activity?.activity_status;
  const type =
    status === 'ACTIVE' ? 'success' : status === 'HIGH_RISK' ? 'error' : status === 'FOLLOW_UP' ? 'warning' : 'default';
  return (
    <NTag size="small" bordered={false} type={type}>
      {row.activity?.display_name || '数据不足'}
    </NTag>
  );
}

function followUpTag(row: CustomerListItem) {
  const status = getFollowUpStatus(row.next_follow_up_at);
  return (
    <NTag size="small" bordered={false} type={status.type}>
      {status.label}
    </NTag>
  );
}

function openDetail(row: CustomerListItem) {
  void router.push({ path: `/customers/${row.id}`, query: { returnTo: route.fullPath } });
}

const initialPagination = { page: initialQuery.page, pageSize: initialQuery.page_size, pageSizes: [10, 20, 50, 100] };
const { columns, columnChecks, data, loading, mobilePagination, scrollX, getData, getDataByPage } =
  useNaivePaginatedTable({
    api: loadCustomerPage,
    immediate: false,
    transform: (response: CustomerPage | null) => ({
      data: response?.data ?? [],
      total: response?.meta.total ?? 0,
      pageNum: response?.meta.page ?? query.value.page ?? 1,
      pageSize: response?.meta.page_size ?? query.value.page_size ?? 10
    }),
    onPaginationParamsChange: params => {
      query.value = { page: params.page, page_size: params.pageSize };
    },
    paginationProps: initialPagination,
    getColumnVisible: column => !('key' in column && ['account_name', 'operate'].includes(String(column.key))),
    columns: () => [
      {
        key: 'account_name',
        title: '客户名称',
        width: 240,
        fixed: 'left',
        ellipsis: { tooltip: true },
        sorter: true,
        sortOrder: ordering.value === 'account_name' ? 'ascend' : ordering.value === '-account_name' ? 'descend' : false,
        render: row => <NButton text type="primary" class="max-w-full" onClick={() => openDetail(row)}><span class="truncate" title={row.account_name}>{row.account_name}</span></NButton>
      },
      {
        key: 'primary_country_code',
        title: '国家/地区',
        width: 140,
        ellipsis: { tooltip: true },
        render: row => countryName(row.primary_country_code)
      },
      {
        key: 'customer_grade',
        title: '等级',
        width: 90,
        align: 'center',
        render: row =>
          row.customer_grade ? (
            <NTag size="small" bordered={false} type="primary">
              {/^[A-Z]$/.test(row.customer_grade.item_code)
                ? `${row.customer_grade.item_code}级`
                : row.customer_grade.display_name}
            </NTag>
          ) : (
            '—'
          )
      },
      { key: 'activity', title: '客户状态', width: 110, align: 'center', render: activityTag },
      {
        key: 'primary_owner',
        title: '负责人',
        width: 110,
        ellipsis: { tooltip: true },
        render: row => row.primary_owner?.display_name || '—'
      },
      {
        key: 'last_12m_sales_amount',
        title: '近12个月销售额',
        width: 180,
        align: 'right',
        render: row => formatMoney(row.last_12m_sales_amount)
      },
      {
        key: 'recent_order',
        title: '最近订单',
        width: 140,
        render: row => formatDate(row.recent_order?.order_date ?? null)
      },
      { key: 'last_contact_at', title: '最近联系', width: 140, render: row => formatDate(row.last_contact_at) },
      {
        key: 'next_follow_up_at',
        title: '下次跟进',
        width: 140,
        render: row => (row.next_follow_up_at ? formatDate(row.next_follow_up_at) : '未安排')
      },
      { key: 'follow_up_status', title: '跟进状态', width: 110, align: 'center', render: followUpTag },
      {
        key: 'risk',
        title: '风险',
        width: 100,
        align: 'center',
        render: row =>
          row.activity?.activity_status === 'HIGH_RISK' ? (
            <NTag size="small" bordered={false} type="error">
              高风险
            </NTag>
          ) : (
            '—'
          )
      },
      {
        key: 'operate', title: '操作', width: 120, fixed: 'right', align: 'center',
        render: row => <NButton size="small" type="primary" ghost onClick={() => openDetail(row)}>查看详情</NButton>
      }
    ]
  });

const tableColumns = computed(() => columns.value.map(column =>
  appStore.isMobile && 'key' in column && column.key === 'account_name' ? { ...column, fixed: undefined } : column
));
const tablePagination = computed(() => ({ ...mobilePagination.value, disabled: loading.value }));

async function loadCustomerPage(): Promise<CustomerPage | null> {
  errorMessage.value = '';
  requiresLogin.value = false;
  forbidden.value = false;
  pageUnavailable.value = false;
  const filter = appliedFilters.value;
  try {
    const requestQuery: CustomerListQuery = {
        ...query.value,
        ordering: ordering.value,
        q: filter.q.trim() || undefined,
        customer_grade: filter.customer_grade || undefined,
        country_code: filter.country_code || undefined,
        activity_status: filter.activity_status || undefined
      };
    await router.replace({ path: route.path, query: customerListRouteQuery(requestQuery), hash: route.hash });
    if (controller.signal.aborted) return null;
    return await fetchCustomers(requestQuery, controller.signal);
  } catch (error) {
    if (controller.signal.aborted) return null;
    errorMessage.value = error instanceof Error ? error.message : '加载客户列表失败，请重试。';
    const status = error && typeof error === 'object' && 'status' in error ? error.status : 0;
    pageUnavailable.value = status === 404 && (query.value.page ?? 1) > 1;
    if (status === 401) requiresLogin.value = true;
    if (status === 403) {
      forbidden.value = true;
      try {
        const session = await fetchErpSession(controller.signal);
        requiresLogin.value = !session.authenticated;
      } catch (sessionError) {
        if (!controller.signal.aborted) console.error('无法确认客户列表登录状态', sessionError);
      }
    }
    return null;
  }
}

async function loadOptions() {
  optionsLoading.value = true;
  optionsError.value = '';
  try {
    options.value = await fetchCustomerOptions(controller.signal);
  } catch (error) {
    if (!controller.signal.aborted)
      optionsError.value = error instanceof Error ? error.message : '筛选选项加载失败，请刷新重试。';
  } finally {
    optionsLoading.value = false;
  }
}

function searchCustomers() {
  if (loading.value) return;
  appliedFilters.value = { ...filters.value };
  void getDataByPage(1);
}

function resetFilters() {
  filters.value = { q: '', customer_grade: null, country_code: null, activity_status: null };
  ordering.value = '-updated_at';
  searchCustomers();
}

function searchOnEnter(event: KeyboardEvent) {
  if (event.isComposing) return;
  event.preventDefault();
  searchCustomers();
}

function updateSorter(sorter: DataTableSortState | DataTableSortState[] | null) {
  if (loading.value || Array.isArray(sorter)) return;
  ordering.value = sorter?.order ? (sorter.order === 'ascend' ? 'account_name' : '-account_name') : '-updated_at';
  void getDataByPage(1);
}

async function refreshList() {
  if (loading.value) return;
  await authStore.initUserInfo(true);
  if (authStore.isLogin && !routeStore.isInitAuthRoute) await routeStore.initAuthRoute();
  await Promise.all([loadOptions(), getData()]);
}

function rowKey(row: CustomerListItem) {
  return row.id;
}

function returnToFirstPage() {
  void getDataByPage(1);
}

async function returnToLogin() {
  await authStore.resetStore();
}

onMounted(refreshList);
onUnmounted(() => controller.abort());
</script>

<template>
  <div class="min-h-500px flex-col-stretch gap-16px overflow-hidden lt-sm:overflow-auto">
    <NCard :bordered="false" size="small" class="card-wrapper">
      <NCollapse :default-expanded-names="['customer-search']">
        <NCollapseItem title="搜索" name="customer-search">
          <NForm :model="filters" label-placement="left" :label-width="80" :disabled="loading">
            <NGrid responsive="screen" item-responsive>
              <NFormItemGi span="24 s:12 m:6" label="客户" path="q" class="pr-24px">
                <NInput
                  v-model:value="filters.q"
                  placeholder="客户名称、编号、英文名"
                  clearable
                  :maxlength="100"
                  @keydown.enter="searchOnEnter"
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="等级" path="customer_grade" class="pr-24px">
                <NSelect
                  v-model:value="filters.customer_grade"
                  placeholder="请选择等级"
                  :options="gradeOptions"
                  :loading="optionsLoading"
                  :disabled="!options || loading"
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="国家/地区" path="country_code" class="pr-24px">
                <NSelect
                  v-model:value="filters.country_code"
                  placeholder="请选择国家/地区"
                  :options="countryOptions"
                  :loading="optionsLoading"
                  :disabled="!options || loading"
                  filterable
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="客户状态" path="activity_status" class="pr-24px">
                <NSelect
                  v-model:value="filters.activity_status"
                  placeholder="请选择客户状态"
                  :options="activityOptions"
                  :loading="optionsLoading"
                  :disabled="!options || loading"
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi span="24" :show-feedback="false" class="pr-24px">
                <NSpace class="w-full" justify="end">
                  <NButton :disabled="loading" @click="resetFilters">
                    <template #icon><icon-ic-round-refresh class="text-icon" /></template>
                    重置
                  </NButton>
                  <NButton type="primary" ghost :loading="loading" @click="searchCustomers">
                    <template #icon><icon-ic-round-search class="text-icon" /></template>
                    搜索
                  </NButton>
                </NSpace>
              </NFormItemGi>
            </NGrid>
          </NForm>
        </NCollapseItem>
      </NCollapse>
    </NCard>
    <NAlert v-if="optionsError && !errorMessage" type="warning" title="筛选选项暂不可用">
      {{ optionsError }} 可点击刷新重试。
    </NAlert>
    <NCard title="客户列表" :bordered="false" size="small" class="card-wrapper sm:flex-1-hidden">
      <template #header-extra>
        <NSpace justify="end">
          <NButton size="small" :disabled="loading" @click="refreshList">
            <template #icon><icon-mdi-refresh class="text-icon" :class="{ 'animate-spin': loading }" /></template>
            刷新
          </NButton>
          <TableColumnSetting v-model:columns="columnChecks" />
        </NSpace>
      </template>
      <NResult
        v-if="errorMessage"
        :status="forbidden || requiresLogin ? '403' : '500'"
        :title="requiresLogin ? '登录已失效' : forbidden ? '暂无客户查看权限' : '客户列表加载失败'"
        :description="requiresLogin ? '请重新登录，登录后将自动返回客户列表。' : errorMessage"
        class="py-48px"
      >
        <template #footer>
          <NSpace justify="center">
            <NButton
              v-if="requiresLogin"
              type="primary"
              @click="returnToLogin"
            >
              前往登录
            </NButton>
            <NButton v-if="pageUnavailable" :loading="loading" @click="returnToFirstPage">返回第一页</NButton>
            <NButton v-else :loading="loading" @click="refreshList">重新加载</NButton>
          </NSpace>
        </template>
      </NResult>
      <NDataTable
        v-else
        :columns="tableColumns"
        :data="data"
        size="small"
        :flex-height="!appStore.isMobile"
        :scroll-x="scrollX"
        :loading="loading"
        remote
        :row-key="rowKey"
        :pagination="tablePagination"
        class="sm:h-full"
        @update:sorter="updateSorter"
      >
        <template #empty><NEmpty description="暂无匹配的客户" /></template>
      </NDataTable>
    </NCard>
  </div>
</template>
