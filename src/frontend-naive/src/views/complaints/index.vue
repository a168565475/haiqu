<script setup lang="tsx">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { NTag } from 'naive-ui';
import { fetchComplaints, fetchComplaintOptions } from '@/service/api/complaints';
import { fetchErpSession } from '@/service/api/customers';
import { useAppStore } from '@/store/modules/app';
import { useAuthStore } from '@/store/modules/auth';
import { useRouteStore } from '@/store/modules/route';
import { useNaivePaginatedTable } from '@/hooks/common/table';
import type { ComplaintListItem, ComplaintOptions, ComplaintPage, ComplaintQuery } from '@/typings/complaint';
import {
  complaintCsv,
  complaintPageSizes,
  complaintRouteQuery,
  complaintSlaOptions,
  formatComplaintDate,
  getComplaintSlaText,
  normalizeComplaintQuery
} from './shared';

defineOptions({ name: 'ComplaintList' });

const appStore = useAppStore();
const authStore = useAuthStore();
const routeStore = useRouteStore();
const route = useRoute();
const router = useRouter();

const controller = new AbortController();
const initialQuery = normalizeComplaintQuery(route.query);
const filters = ref({
  q: initialQuery.q ?? '',
  complaint_type_item_id: initialQuery.complaint_type_item_id ?? null,
  severity_item_id: initialQuery.severity_item_id ?? null,
  status: initialQuery.status ?? null,
  owner_employee_id: initialQuery.owner_employee_id ?? null,
  sla_status: initialQuery.sla_status ?? null
});
const appliedFilters = shallowRef({ ...filters.value });
const query = shallowRef<ComplaintQuery>({
  page: initialQuery.page,
  page_size: initialQuery.page_size
});
const options = shallowRef<ComplaintOptions | null>(null);
const optionsLoading = ref(false);
const optionsError = ref('');
const errorMessage = ref('');
const requiresLogin = ref(false);
const forbidden = ref(false);
const pageUnavailable = ref(false);
const refreshing = ref(false);

const typeOptions = computed(
  () =>
    options.value?.complaint_types.map(item => ({
      label: item.display_name,
      value: item.id
    })) ?? []
);
const severityOptions = computed(
  () =>
    options.value?.severities.map(item => ({
      label: item.display_name,
      value: item.id
    })) ?? []
);
const statusOptions = computed(() => options.value?.statuses ?? []);
const ownerOptions = computed(
  () =>
    options.value?.employees.map(item => ({
      label: item.display_name,
      value: item.id
    })) ?? []
);

function severityTag(row: ComplaintListItem) {
  const code = row.severity.item_code;
  const type = ['CRITICAL', 'SERIOUS'].includes(code)
    ? 'error'
    : ['IMPORTANT', 'HIGH'].includes(code)
      ? 'warning'
      : 'info';
  return (
    <NTag size="small" bordered={false} type={type}>
      {row.severity.display_name}
    </NTag>
  );
}

function statusTag(row: ComplaintListItem) {
  const type =
    row.status === 'CLOSED'
      ? 'success'
      : row.status === 'CANCELLED'
        ? 'default'
        : row.status === 'CUSTOMER_CONFIRMATION'
          ? 'warning'
          : 'info';
  return (
    <NTag size="small" bordered={false} type={type}>
      {row.status_label}
    </NTag>
  );
}

const initialPagination = {
  page: initialQuery.page,
  pageSize: initialQuery.page_size,
  pageSizes: complaintPageSizes
};
const { columns, columnChecks, data, loading, mobilePagination, scrollX, getData, getDataByPage } =
  useNaivePaginatedTable({
    api: loadComplaintPage,
    immediate: false,
    transform: (response: ComplaintPage | null) => ({
      data: response?.data ?? [],
      total: response?.meta.total ?? 0,
      pageNum: response?.meta.page ?? query.value.page ?? 1,
      pageSize: response?.meta.page_size ?? query.value.page_size ?? 50
    }),
    onPaginationParamsChange: params => {
      query.value = { page: params.page, page_size: params.pageSize };
    },
    paginationProps: initialPagination,
    // 编号不出现在可隐藏列清单中，保持表格始终显示编号。
    getColumnVisible: column => !('key' in column && column.key === 'complaint_code'),
    columns: () => [
      {
        key: 'complaint_code',
        title: '客诉编号',
        width: 170,
        fixed: 'left',
        ellipsis: { tooltip: true }
      },
      {
        key: 'customer',
        title: '客户',
        width: 220,
        ellipsis: { tooltip: true },
        render: row => row.customer.account_name
      },
      {
        key: 'source_order_reference',
        title: '关联订单',
        width: 160,
        ellipsis: { tooltip: true },
        render: row => row.source_order_reference || '—'
      },
      {
        key: 'complaint_type',
        title: '类型',
        width: 130,
        ellipsis: { tooltip: true },
        render: row => row.complaint_type.display_name
      },
      {
        key: 'severity',
        title: '等级',
        width: 100,
        align: 'center',
        render: severityTag
      },
      {
        key: 'status',
        title: '状态',
        width: 130,
        align: 'center',
        render: statusTag
      },
      {
        key: 'owner',
        title: '负责人',
        width: 120,
        ellipsis: { tooltip: true },
        render: row => row.owner.display_name
      },
      {
        key: 'sla_status',
        title: 'SLA',
        width: 270,
        render: row => (
          <span class={row.sla_status === 'OVERDUE' ? 'text-error' : undefined}>{getComplaintSlaText(row)}</span>
        )
      },
      {
        key: 'updated_at',
        title: '最近更新',
        width: 180,
        render: row => formatComplaintDate(row.updated_at)
      }
    ]
  });

const busy = computed(() => loading.value || refreshing.value);
const tablePagination = computed(() => ({
  ...mobilePagination.value,
  disabled: busy.value
}));

async function loadComplaintPage(): Promise<ComplaintPage | null> {
  errorMessage.value = '';
  requiresLogin.value = false;
  forbidden.value = false;
  pageUnavailable.value = false;
  const requestQuery = normalizeComplaintQuery({
    ...appliedFilters.value,
    ...query.value
  });
  try {
    await router.replace({
      path: route.path,
      query: complaintRouteQuery(requestQuery),
      hash: route.hash
    });
    if (controller.signal.aborted) return null;
    return await fetchComplaints(requestQuery, controller.signal);
  } catch (error) {
    if (controller.signal.aborted) return null;
    errorMessage.value = error instanceof Error ? error.message : '加载客诉列表失败，请重试。';
    const status = error && typeof error === 'object' && 'status' in error ? error.status : 0;
    pageUnavailable.value = status === 404 && requestQuery.page > 1;
    if (status === 401) requiresLogin.value = true;
    if (status === 403) {
      forbidden.value = true;
      try {
        const session = await fetchErpSession(controller.signal);
        requiresLogin.value = !session.authenticated;
      } catch (sessionError) {
        if (!controller.signal.aborted) console.error('无法确认客诉列表登录状态', sessionError);
      }
    }
    return null;
  }
}

async function loadOptions() {
  optionsLoading.value = true;
  optionsError.value = '';
  try {
    options.value = await fetchComplaintOptions(controller.signal);
  } catch (error) {
    if (!controller.signal.aborted) {
      options.value = null;
      optionsError.value = error instanceof Error ? error.message : '筛选选项加载失败，请刷新重试。';
    }
  } finally {
    optionsLoading.value = false;
  }
}

function searchComplaints() {
  if (busy.value) return;
  appliedFilters.value = { ...filters.value };
  void getDataByPage(1);
}

function resetFilters() {
  if (busy.value) return;
  filters.value = {
    q: '',
    complaint_type_item_id: null,
    severity_item_id: null,
    status: null,
    owner_employee_id: null,
    sla_status: null
  };
  searchComplaints();
}

function searchOnEnter(event: KeyboardEvent) {
  if (event.isComposing) return;
  event.preventDefault();
  searchComplaints();
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

function rowKey(row: ComplaintListItem) {
  return row.id;
}

function returnToFirstPage() {
  if (!busy.value) void getDataByPage(1);
}

async function returnToLogin() {
  await authStore.resetStore();
}

function exportCurrentPage() {
  if (busy.value || errorMessage.value || !data.value.length) return;
  const url = URL.createObjectURL(new Blob([complaintCsv(data.value)], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `客诉列表-${formatComplaintDate(new Date().toISOString()).slice(0, 10)}.csv`;
  try {
    document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();
    URL.revokeObjectURL(url);
  }
}

onMounted(refreshList);
onUnmounted(() => controller.abort());
</script>

<template>
  <div class="min-h-500px flex-col-stretch gap-16px overflow-hidden lt-sm:overflow-auto">
    <NCard :bordered="false" size="small" class="card-wrapper">
      <NCollapse :default-expanded-names="['complaint-search']">
        <NCollapseItem title="搜索" name="complaint-search">
          <NForm :model="filters" label-placement="left" :label-width="80" :disabled="busy">
            <NGrid responsive="screen" item-responsive>
              <NFormItemGi span="24 s:12 m:6" label="关键词" path="q" class="pr-24px">
                <NInput
                  v-model:value="filters.q"
                  placeholder="客户、客诉编号、标题"
                  clearable
                  @keydown.enter="searchOnEnter"
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="客诉类型" path="complaint_type_item_id" class="pr-24px">
                <NSelect
                  v-model:value="filters.complaint_type_item_id"
                  placeholder="请选择客诉类型"
                  :options="typeOptions"
                  :loading="optionsLoading"
                  :disabled="!options || busy"
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="严重程度" path="severity_item_id" class="pr-24px">
                <NSelect
                  v-model:value="filters.severity_item_id"
                  placeholder="请选择严重程度"
                  :options="severityOptions"
                  :loading="optionsLoading"
                  :disabled="!options || busy"
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi span="24 s:12 m:6" label="处理状态" path="status" class="pr-24px">
                <NSelect
                  v-model:value="filters.status"
                  placeholder="请选择处理状态"
                  :options="statusOptions"
                  :loading="optionsLoading"
                  :disabled="!options || busy"
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
              <NFormItemGi span="24 s:12 m:6" label="SLA" path="sla_status" class="pr-24px">
                <NSelect
                  v-model:value="filters.sla_status"
                  placeholder="请选择SLA状态"
                  :options="complaintSlaOptions"
                  clearable
                />
              </NFormItemGi>
              <NFormItemGi span="24 m:12" :show-feedback="false" class="pr-24px">
                <NSpace class="w-full" justify="end">
                  <NButton :disabled="busy" @click="resetFilters">
                    <template #icon><icon-ic-round-refresh class="text-icon" /></template>
                    重置
                  </NButton>
                  <NButton type="primary" ghost :loading="busy" @click="searchComplaints">
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
    <NCard title="客诉列表" :bordered="false" size="small" class="card-wrapper sm:flex-1-hidden">
      <template #header-extra>
        <NSpace wrap justify="end" class="lt-sm:w-200px">
          <NButton
            size="small"
            ghost
            type="primary"
            :disabled="busy || !!errorMessage || !data.length"
            @click="exportCurrentPage"
          >
            <template #icon><icon-mdi-download class="text-icon" /></template>
            导出当前页
          </NButton>
          <NButton size="small" :disabled="busy" @click="refreshList">
            <template #icon><icon-mdi-refresh class="text-icon" :class="{ 'animate-spin': busy }" /></template>
            刷新
          </NButton>
          <TableColumnSetting v-model:columns="columnChecks" />
        </NSpace>
      </template>
      <NResult
        v-if="errorMessage"
        :status="forbidden || requiresLogin ? '403' : '500'"
        :title="requiresLogin ? '登录已失效' : forbidden ? '暂无客诉查看权限' : '客诉列表加载失败'"
        :description="requiresLogin ? '请重新登录，登录后将自动返回客诉列表。' : errorMessage"
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
        :columns="columns"
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
        <template #empty><NEmpty description="暂无匹配的客诉" /></template>
      </NDataTable>
    </NCard>
  </div>
</template>
