<script setup lang="tsx">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { NButton, NTag } from 'naive-ui';
import { fetchInquiries, fetchInquiryExport, fetchInquiryOptions } from '@/service/api/inquiries';
import { fetchErpSession } from '@/service/api/customers';
import { useAppStore } from '@/store/modules/app';
import { useAuthStore } from '@/store/modules/auth';
import { useRouteStore } from '@/store/modules/route';
import { useNaivePaginatedTable } from '@/hooks/common/table';
import type { InquiryListItem, InquiryOptions, InquiryPage, InquiryQuery } from '@/typings/inquiry';
import {
  formatInquiryAmount,
  formatInquiryReceived,
  inquiryHandlingStage,
  inquiryPageSizes,
  inquiryRouteQuery,
  inquirySlaOptions,
  inquirySlaPresentation,
  inquiryStatusType,
  normalizeInquiryQuery,
  parseInquiryAmountFilter
} from './shared';

defineOptions({ name: 'InquiryList' });

const appStore = useAppStore();
const authStore = useAuthStore();
const routeStore = useRouteStore();
const route = useRoute();
const router = useRouter();

const controller = new AbortController();
const initialQuery = normalizeInquiryQuery(route.query);
const filters = ref({
  q: initialQuery.q ?? '',
  status: initialQuery.status ?? null,
  source_code: initialQuery.source_code ?? null,
  country_code: initialQuery.country_code ?? null,
  owner_employee_id: initialQuery.owner_employee_id ?? null,
  priority: initialQuery.priority ?? null,
  sla_state: initialQuery.sla_state ?? null,
  product_q: initialQuery.product_q ?? '',
  received_from: initialQuery.received_from ?? '',
  received_to: initialQuery.received_to ?? '',
  assignment_status: initialQuery.assignment_status ?? '',
  has_quotation: initialQuery.has_quotation ?? ''
});
const amountInput = ref(initialQuery.amount_min ? `${initialQuery.amount_currency} ${initialQuery.amount_min}` : '');
const filterError = ref('');
const appliedFilters = shallowRef<InquiryQuery>(initialQuery);
const query = shallowRef<InquiryQuery>({
  page: initialQuery.page,
  page_size: initialQuery.page_size,
  ordering: initialQuery.ordering
});
const options = shallowRef<InquiryOptions | null>(null);
const optionsLoading = ref(false);
const optionsError = ref('');
const errorMessage = ref('');
const requiresLogin = ref(false);
const forbidden = ref(false);
const pageUnavailable = ref(false);
const refreshing = ref(false);
const exporting = ref(false);

const statusOptions = computed(
  () =>
    options.value?.statuses.map(item => ({
      label: item.display_name,
      value: item.code
    })) ?? []
);
const sourceOptions = computed(
  () =>
    options.value?.sources.map(item => ({
      label: item.display_name,
      value: item.item_code
    })) ?? []
);
const countryOptions = computed(() => options.value?.countries.map(value => ({ label: value, value })) ?? []);
const ownerOptions = computed(
  () =>
    options.value?.owners.map(item => ({
      label: item.display_name,
      value: item.id
    })) ?? []
);
const priorityOptions = computed(() => [
  ...(options.value?.priorities.map(item => ({
    label: item.display_name,
    value: item.code
  })) ?? []),
  { label: '未设置', value: 'UNSET' }
]);

function openDetail(row: InquiryListItem) {
  void router.push({
    path: `/inquiries/${row.id}`,
    query: { returnTo: route.fullPath }
  });
}

function identityCell(row: InquiryListItem) {
  return (
    <div class="flex-col">
      <span class="truncate" title={row.customer.name}>
        {row.customer.name || '—'}
      </span>
      <NButton
        text
        type="primary"
        class="self-start text-12px"
        onClick={() => openDetail(row)}
      >
        {row.inquiry_number}
      </NButton>
    </div>
  );
}

function productCell(row: InquiryListItem) {
  return (
    <div class="flex-col">
      <span class="truncate" title={row.product_summary.first_description}>
        {row.product_summary.first_description || '—'}
      </span>
      {row.product_summary.item_count > 1 && (
        <span class="text-12px opacity-60">等 {row.product_summary.item_count} 项</span>
      )}
    </div>
  );
}

function receivedCell(row: InquiryListItem) {
  const received = formatInquiryReceived(row.received_at);
  return (
    <div class="flex-col">
      <span>{received.date}</span>
      <span class="text-12px opacity-60">{received.time}</span>
    </div>
  );
}

function priorityTag(row: InquiryListItem) {
  if (!row.priority) return '—';
  const type = row.priority === 'HIGH' ? 'error' : row.priority === 'MEDIUM' ? 'warning' : 'default';
  return (
    <NTag size="small" bordered={false} type={type}>
      {row.priority_display || row.priority}
    </NTag>
  );
}

function statusTag(row: InquiryListItem) {
  return (
    <NTag size="small" bordered={false} type={inquiryStatusType(row.status)}>
      {row.display_stage_label || row.status_display || '—'}
    </NTag>
  );
}

function slaCell(row: InquiryListItem) {
  const sla = row.sla_summary;
  const presentation = inquirySlaPresentation(sla);
  return (
    <div class="flex-col" title={sla.working_time ? '按工作时间计算，午休及休息时间不计时' : '按原连续时间规则计算'}>
      {sla.stage_code && (
        <span class="text-12px opacity-60">
          {inquiryHandlingStage(sla.stage_code)}
          {(sla.active_count ?? 0) > 1 ? ` 等${sla.active_count}项` : ''}
        </span>
      )}
      <span class={sla.state === 'BREACHED' ? 'text-error' : undefined}>{presentation.label}</span>
    </div>
  );
}

function reminderTag(row: InquiryListItem) {
  if (row.sla_summary.state === 'NONE') return '—';
  const presentation = inquirySlaPresentation(row.sla_summary);
  return (
    <NTag size="small" bordered={false} type={presentation.type}>
      {presentation.reminder}
    </NTag>
  );
}

const initialPagination = {
  page: initialQuery.page,
  pageSize: initialQuery.page_size,
  pageSizes: inquiryPageSizes
};
const { columns, columnChecks, data, loading, mobilePagination, scrollX, getData, getDataByPage } =
  useNaivePaginatedTable({
    api: loadInquiryPage,
    immediate: false,
    transform: (response: InquiryPage | null) => ({
      data: response?.data ?? [],
      total: response?.meta.total ?? 0,
      pageNum: response?.meta.page ?? query.value.page ?? 1,
      pageSize: response?.meta.page_size ?? query.value.page_size ?? 50
    }),
    onPaginationParamsChange: params => {
      query.value = {
        ...query.value,
        page: params.page,
        page_size: params.pageSize
      };
    },
    paginationProps: initialPagination,
    getColumnVisible: column => !('key' in column && ['inquiry_number', 'operate'].includes(String(column.key))),
    columns: () => [
      {
        key: 'inquiry_number',
        title: '客户名称 / 询盘编号',
        width: 240,
        fixed: 'left',
        render: identityCell
      },
      {
        key: 'country',
        title: '国家 / 地区',
        width: 120,
        ellipsis: { tooltip: true },
        render: row => row.customer.country_code || '—'
      },
      {
        key: 'source',
        title: '来源',
        width: 120,
        ellipsis: { tooltip: true },
        render: row => row.source.display_name || '—'
      },
      {
        key: 'priority',
        title: '优先级',
        width: 100,
        align: 'center',
        render: priorityTag
      },
      {
        key: 'owner',
        title: '负责人',
        width: 120,
        ellipsis: { tooltip: true },
        render: row => row.owner?.display_name || '未分配'
      },
      {
        key: 'amount',
        title: '预估金额',
        width: 200,
        ellipsis: { tooltip: true },
        render: row => formatInquiryAmount(row.product_amount)
      },
      { key: 'product', title: '产品', width: 200, render: productCell },
      { key: 'received', title: '接收时间', width: 130, render: receivedCell },
      { key: 'sla', title: '处理时限', width: 180, render: slaCell },
      {
        key: 'status',
        title: '状态',
        width: 140,
        align: 'center',
        render: statusTag
      },
      {
        key: 'reminder',
        title: '提醒',
        width: 120,
        align: 'center',
        render: reminderTag
      },
      {
        key: 'operate',
        title: '操作',
        width: 120,
        fixed: 'right',
        align: 'center',
        render: row => (
          <NButton size="small" type="primary" ghost onClick={() => openDetail(row)}>
            查看详情
          </NButton>
        )
      }
    ]
  });

const tableColumns = computed(() =>
  columns.value.map(column =>
    appStore.isMobile && 'key' in column && column.key === 'inquiry_number'
      ? { ...column, fixed: undefined }
      : column
  )
);
const busy = computed(() => loading.value || refreshing.value || exporting.value);
const tablePagination = computed(() => ({
  ...mobilePagination.value,
  disabled: busy.value
}));

async function loadInquiryPage(): Promise<InquiryPage | null> {
  errorMessage.value = '';
  requiresLogin.value = false;
  forbidden.value = false;
  pageUnavailable.value = false;
  const requestQuery = normalizeInquiryQuery({
    ...appliedFilters.value,
    ...query.value
  });
  try {
    await router.replace({
      path: route.path,
      query: inquiryRouteQuery(requestQuery),
      hash: route.hash
    });
    if (controller.signal.aborted) return null;
    return await fetchInquiries(requestQuery, controller.signal);
  } catch (error) {
    if (controller.signal.aborted) return null;
    errorMessage.value = error instanceof Error ? error.message : '加载询盘列表失败，请重试。';
    const status = error && typeof error === 'object' && 'status' in error ? error.status : 0;
    pageUnavailable.value = status === 404 && requestQuery.page > 1;
    if (status === 401) requiresLogin.value = true;
    if (status === 403) {
      forbidden.value = true;
      try {
        const session = await fetchErpSession(controller.signal);
        requiresLogin.value = !session.authenticated;
      } catch (sessionError) {
        if (!controller.signal.aborted) console.error('无法确认询盘列表登录状态', sessionError);
      }
    }
    return null;
  }
}

async function loadOptions() {
  optionsLoading.value = true;
  optionsError.value = '';
  try {
    options.value = await fetchInquiryOptions(controller.signal);
  } catch (error) {
    if (!controller.signal.aborted) {
      options.value = null;
      optionsError.value = error instanceof Error ? error.message : '筛选选项加载失败，请刷新重试。';
    }
  } finally {
    optionsLoading.value = false;
  }
}

function searchInquiries() {
  if (busy.value) return;
  filterError.value = '';
  try {
    appliedFilters.value = normalizeInquiryQuery({
      ...filters.value,
      ...parseInquiryAmountFilter(amountInput.value)
    });
  } catch (error) {
    filterError.value = error instanceof Error ? error.message : '请检查筛选条件。';
    return;
  }
  void getDataByPage(1);
}

function resetFilters() {
  if (busy.value) return;
  filters.value = {
    q: '',
    status: null,
    source_code: null,
    country_code: null,
    owner_employee_id: null,
    priority: null,
    sla_state: null,
    product_q: '',
    received_from: '',
    received_to: '',
    assignment_status: '',
    has_quotation: ''
  };
  amountInput.value = '';
  searchInquiries();
}

function searchOnEnter(event: KeyboardEvent) {
  if (event.isComposing) return;
  event.preventDefault();
  searchInquiries();
}

async function refreshList() {
  if (busy.value) return;
  refreshing.value = true;
  try {
    await authStore.initUserInfo(true);
    if (authStore.isLogin && !routeStore.isInitAuthRoute) await routeStore.initAuthRoute();
    if (!controller.signal.aborted) await Promise.all([loadOptions(), getData()]);
  } finally {
    refreshing.value = false;
  }
}

function rowKey(row: InquiryListItem) {
  return row.id;
}

function returnToFirstPage() {
  if (!busy.value) void getDataByPage(1);
}

async function returnToLogin() {
  await authStore.resetStore();
}

async function exportInquiries() {
  if (busy.value || errorMessage.value || !data.value.length) return;
  exporting.value = true;
  try {
    const blob = await fetchInquiryExport(
      normalizeInquiryQuery({ ...appliedFilters.value, ...query.value }),
      controller.signal
    );
    if (controller.signal.aborted) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `询盘列表-${formatInquiryReceived(new Date().toISOString()).date}.csv`;
    try {
      document.body.appendChild(link);
      link.click();
    } finally {
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  } catch (error) {
    if (!controller.signal.aborted)
      window.$message?.error(error instanceof Error ? error.message : '导出询盘失败，请重试。');
  } finally {
    exporting.value = false;
  }
}

onMounted(refreshList);
onUnmounted(() => controller.abort());
</script>

<template>
  <div class="min-h-500px flex-col-stretch gap-16px overflow-hidden lt-sm:overflow-auto">
    <NCard :bordered="false" size="small" class="card-wrapper">
      <NCollapse :default-expanded-names="['inquiry-search']">
        <NCollapseItem title="搜索" name="inquiry-search">
          <NForm :model="filters" label-placement="left" :label-width="80" :disabled="busy">
            <NGrid responsive="screen" item-responsive>
              <NFormItemGi span="24 s:12 m:6" label="关键词" path="q" class="pr-24px">
                <NInput
                  v-model:value="filters.q"
                  placeholder="客户、询盘编号、主题或描述"
                  clearable
                  @keydown.enter="searchOnEnter"
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="状态" path="status" class="pr-24px">
                <NSelect
                  v-model:value="filters.status"
                  placeholder="请选择状态"
                  :options="statusOptions"
                  :loading="optionsLoading"
                  :disabled="!options || busy"
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="来源" path="source_code" class="pr-24px">
                <NSelect
                  v-model:value="filters.source_code"
                  placeholder="请选择来源"
                  :options="sourceOptions"
                  :loading="optionsLoading"
                  :disabled="!options || busy"
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="国家/地区" path="country_code" class="pr-24px">
                <NSelect
                  v-model:value="filters.country_code"
                  placeholder="请选择国家/地区"
                  :options="countryOptions"
                  :loading="optionsLoading"
                  :disabled="!options || busy"
                  filterable
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="负责人" path="owner_employee_id" class="pr-24px">
                <NSelect
                  v-model:value="filters.owner_employee_id"
                  placeholder="请选择负责人"
                  :options="ownerOptions"
                  :loading="optionsLoading"
                  :disabled="!options || busy"
                  filterable
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="优先级" path="priority" class="pr-24px">
                <NSelect
                  v-model:value="filters.priority"
                  placeholder="请选择优先级"
                  :options="priorityOptions"
                  :loading="optionsLoading"
                  :disabled="!options || busy"
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="处理时限" path="sla_state" class="pr-24px">
                <NSelect
                  v-model:value="filters.sla_state"
                  placeholder="请选择处理时限状态"
                  :options="inquirySlaOptions"
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi
                span="24 s:12 m:6"
                label="预估金额"
                path="amount_min"
                class="pr-24px"
                :validation-status="filterError ? 'error' : undefined"
                :feedback="filterError"
              >
                <NInput
                  v-model:value="amountInput"
                  placeholder="USD 10,000 以上"
                  clearable
                  @keydown.enter="searchOnEnter"
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="产品关键词" path="product_q" class="pr-24px">
                <NInput
                  v-model:value="filters.product_q"
                  placeholder="请输入产品关键词"
                  clearable
                  @keydown.enter="searchOnEnter"
                />
              </NFormItemGi>
              <NFormItemGi span="24 m:12" :show-feedback="false" class="pr-24px">
                <NSpace class="w-full" justify="end">
                  <NButton :disabled="busy" @click="resetFilters"
                    ><template #icon><icon-ic-round-refresh class="text-icon" /></template>重置</NButton
                  >
                  <NButton type="primary" ghost :loading="busy" @click="searchInquiries"
                    ><template #icon><icon-ic-round-search class="text-icon" /></template>搜索</NButton
                  >
                </NSpace>
              </NFormItemGi>
            </NGrid>
          </NForm>
        </NCollapseItem>
      </NCollapse>
    </NCard>
    <NAlert v-if="optionsError && !errorMessage" type="warning" title="筛选选项暂不可用"
      >{{ optionsError }} 可点击刷新重试。</NAlert
    >
    <NCard title="询盘列表" :bordered="false" size="small" class="card-wrapper sm:flex-1-hidden">
      <template #header-extra>
        <NSpace wrap justify="end" class="lt-sm:w-200px">
          <NButton
            size="small"
            ghost
            type="primary"
            :loading="exporting"
            :disabled="busy || !!errorMessage || !data.length"
            @click="exportInquiries"
          >
            <template #icon><icon-mdi-download class="text-icon" /></template>导出
          </NButton>
          <NButton size="small" :disabled="busy" @click="refreshList">
            <template #icon><icon-mdi-refresh class="text-icon" :class="{ 'animate-spin': busy }" /></template>刷新
          </NButton>
          <TableColumnSetting v-model:columns="columnChecks" />
        </NSpace>
      </template>
      <NResult
        v-if="errorMessage"
        :status="forbidden || requiresLogin ? '403' : '500'"
        :title="requiresLogin ? '登录已失效' : forbidden ? '暂无询盘查看权限' : '询盘列表加载失败'"
        :description="requiresLogin ? '请重新登录，登录后将自动返回询盘列表。' : errorMessage"
        class="py-48px"
      >
        <template #footer>
          <NSpace justify="center">
            <NButton v-if="requiresLogin" type="primary" @click="returnToLogin">前往登录</NButton>
            <NButton v-if="pageUnavailable" :loading="busy" @click="returnToFirstPage">返回第一页</NButton>
            <NButton v-else :loading="busy" @click="refreshList">重新加载</NButton>
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
        :loading="busy"
        remote
        :row-key="rowKey"
        :pagination="tablePagination"
        class="sm:h-full"
      >
        <template #empty><NEmpty description="暂无匹配的询盘" /></template>
      </NDataTable>
    </NCard>
  </div>
</template>
