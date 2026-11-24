<script setup lang="tsx">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue';
import { NButton, NTag } from 'naive-ui';
import type { DataTableColumns } from 'naive-ui';
import { fetchCustomerRecords, fetchCustomerRecordOptions } from '@/service/api/customer-detail';
import type {
  CustomerRecordKind,
  CustomerRecordQuery,
  CustomerRecordPage,
  CustomerRecordOptions
} from '@/typings/customer-detail';
import { formatInquiryTime, formatInquiryNumber } from '../../inquiry-detail/shared';

const props = defineProps<{
  customerId: string;
  kind: CustomerRecordKind;
  scope: 'ALL' | 'TEAM' | 'ME';
  canRead: boolean;
  beforeRead: (signal: AbortSignal) => Promise<boolean>;
}>();
const emit = defineEmits<{ expired: []; openInquiry: [id: string] }>();
type Row = CustomerRecordPage['data'][number];
const titles: Record<CustomerRecordKind, string> = {
  tasks: '客户任务',
  inquiries: '客户询盘',
  quotations: '客户报价',
  samples: '客户样品',
  orders: '客户订单',
  complaints: '客户客诉'
};
const rows = shallowRef<Row[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const error = ref('');
const optionsError = ref('');
const options = shallowRef<CustomerRecordOptions>({ statuses: [], owners: [], subtypes: [] });
const filters = ref({
  q: '',
  status: null as string | null,
  ownerId: null as string | null,
  subtype: null as string | null,
  date: null as string | null
});
let applied = { ...filters.value };
let controller = new AbortController();
let optionsController = new AbortController();

const headers: Record<CustomerRecordKind, [string, string, number][]> = {
  tasks: [
    ['code', '任务编号', 180],
    ['title', '任务内容', 260],
    ['status', '状态', 130],
    ['priority', '优先级', 90],
    ['owner', '负责人', 120],
    ['due', '截止时间', 170],
    ['updated', '更新时间', 170]
  ],
  inquiries: [
    ['code', '询盘编号', 180],
    ['title', '主题', 220],
    ['product', '产品需求', 220],
    ['status', '状态', 130],
    ['owner', '负责人', 120],
    ['received', '接收时间', 170],
    ['due', '期望回复', 170]
  ],
  quotations: [
    ['code', '报价编号', 180],
    ['title', '报价主题', 220],
    ['version', '版本', 80],
    ['amount', '报价金额', 170],
    ['status', '状态', 130],
    ['owner', '负责人', 120],
    ['updated', '更新时间', 170]
  ],
  samples: [
    ['code', '样品编号', 180],
    ['type', '样品类型', 120],
    ['title', '样品明细', 260],
    ['status', '状态', 130],
    ['shipping', '物流状态', 130],
    ['owner', '负责人', 120],
    ['received', '申请时间', 170]
  ],
  orders: [
    ['code', '订单编号', 180],
    ['title', '客户 PO', 170],
    ['status', '状态', 130],
    ['amount', '订单金额', 170],
    ['owner', '业务员', 120],
    ['due', '下次交付', 120],
    ['updated', '更新时间', 170]
  ],
  complaints: [
    ['code', '客诉编号', 180],
    ['title', '来源订单', 180],
    ['type', '客诉类型', 140],
    ['severity', '严重程度', 120],
    ['status', '状态', 140],
    ['owner', '负责人', 120],
    ['due', '处理期限', 170],
    ['updated', '更新时间', 170]
  ]
};
function money(value: string | number | null | undefined, currency: string | undefined) {
  return value === null || value === undefined ? '—' : `${currency || ''} ${formatInquiryNumber(value, 2)}`.trim();
}
function cells(row: Row): Record<string, string> {
  if ('task_number' in row)
    return {
      code: row.task_number,
      title: row.title,
      status: row.status_display,
      priority: row.priority_display,
      owner: row.assignee?.display_name || '未分配',
      due: formatInquiryTime(row.due_at),
      updated: formatInquiryTime(row.updated_at)
    };
  if ('inquiry_number' in row)
    return {
      code: row.inquiry_number,
      title: row.subject,
      product: row.product_summary.first_description,
      status: row.display_stage_label || row.status_display,
      owner: row.owner?.display_name || '未分配',
      received: formatInquiryTime(row.received_at),
      due: formatInquiryTime(row.requested_due_at)
    };
  if ('quotation_number' in row)
    return {
      code: row.quotation_number,
      title: row.subject,
      version: row.current_version ? `V${row.current_version.version_number}` : '—',
      amount: money(row.current_version?.total_amount, row.current_version?.currency_code),
      status: row.display_status_label,
      owner: row.owner?.display_name || '未分配',
      updated: formatInquiryTime(row.updated_at)
    };
  if ('request_number' in row)
    return {
      code: row.request_number,
      type: row.sample_type_display,
      title: row.item_summary.text,
      status: row.status_display,
      shipping: row.latest_shipment?.status_display || '未发货',
      owner: row.owner?.display_name || '未分配',
      received: formatInquiryTime(row.requested_at)
    };
  if ('order_number' in row)
    return {
      code: row.order_number,
      title: row.customer_po_number || '—',
      status: row.status_display,
      amount: money(row.total_amount, row.currency_code),
      owner: row.salesperson.display_name,
      due: row.next_delivery_date || '—',
      updated: formatInquiryTime(row.updated_at)
    };
  return {
    code: row.complaint_code,
    title: row.source_order_reference || '—',
    type: row.complaint_type.display_name,
    severity: row.severity.display_name,
    status: row.status_label,
    owner: row.owner.display_name,
    due: formatInquiryTime(row.target_completion_at),
    updated: formatInquiryTime(row.updated_at)
  };
}
const columns = computed<DataTableColumns<Row>>(() =>
  headers[props.kind].map(([key, title, width]) => ({
    key,
    title,
    width,
    ellipsis: { tooltip: true },
    render: (row) =>
      key === 'code' && props.kind === 'inquiries' ? (
        <NButton text type="primary" onClick={() => emit('openInquiry', row.id)}>
          {cells(row)[key]}
        </NButton>
      ) : key === 'status' ? (
        <NTag size="small" bordered={false}>
          {cells(row)[key] || '—'}
        </NTag>
      ) : (
        cells(row)[key] || '—'
      )
  }))
);
const pagination = computed(() => ({
  page: page.value,
  pageSize: pageSize.value,
  itemCount: total.value,
  pageSizes: [20, 50, 100],
  showSizePicker: true,
  pageSlot: 5,
  disabled: loading.value,
  onUpdatePage: (value: number) => {
    page.value = value;
    void load();
  },
  onUpdatePageSize: (value: number) => {
    pageSize.value = value;
    page.value = 1;
    void load();
  }
}));
function handleError(value: unknown) {
  if (value instanceof Error && 'status' in value && value.status === 401) emit('expired');
  return value instanceof Error ? value.message : '读取记录失败，请重试。';
}
async function load() {
  controller.abort();
  controller = new AbortController();
  const signal = controller.signal;
  rows.value = [];
  total.value = 0;
  error.value = '';
  if (!props.canRead) return;
  loading.value = true;
  const query: CustomerRecordQuery = {
    page: page.value,
    page_size: pageSize.value,
    scope: props.kind === 'tasks' ? props.scope : undefined,
    q: applied.q || undefined,
    status: applied.status || undefined,
    ownerId: applied.ownerId || undefined,
    subtype: applied.subtype || undefined,
    date: applied.date || undefined
  };
  try {
    if (!(await props.beforeRead(signal))) return;
    const result = await fetchCustomerRecords(props.kind, props.customerId, query, signal);
    if (!signal.aborted) {
      rows.value = result.data;
      total.value = result.meta.total;
    }
  } catch (value) {
    if (!signal.aborted) error.value = handleError(value);
  } finally {
    if (signal === controller.signal) loading.value = false;
  }
}
async function loadOptions() {
  optionsController.abort();
  optionsController = new AbortController();
  const signal = optionsController.signal;
  options.value = { statuses: [], owners: [], subtypes: [] };
  optionsError.value = '';
  if (!props.canRead) return;
  try {
    if (!(await props.beforeRead(signal))) return;
    const value = await fetchCustomerRecordOptions(props.kind, signal);
    if (!signal.aborted) options.value = value;
  } catch (value) {
    if (!signal.aborted) optionsError.value = handleError(value);
  }
}
function search() {
  applied = { ...filters.value };
  page.value = 1;
  void load();
}
function reset() {
  filters.value = { q: '', status: null, ownerId: null, subtype: null, date: null };
  search();
}
function refresh() {
  void load();
  void loadOptions();
}
watch(
  () => [props.customerId, props.kind, props.canRead, props.scope],
  () => {
    filters.value = { q: '', status: null, ownerId: null, subtype: null, date: null };
    applied = { ...filters.value };
    page.value = 1;
    refresh();
  },
  { immediate: true }
);
onUnmounted(() => {
  controller.abort();
  optionsController.abort();
});
</script>

<template>
  <NCard :title="titles[kind]" :bordered="false" class="card-wrapper" :data-testid="`customer-records-${kind}`">
    <template #header-extra
      ><NButton size="small" :loading="loading" :disabled="!canRead" @click="refresh">刷新</NButton></template
    >
    <NResult v-if="!canRead" status="403" title="暂无查看权限" description="当前账号无权查看此类客户记录。" />
    <template v-else>
      <NForm label-placement="left" :show-feedback="false" class="record-search" :disabled="loading">
        <NInput v-model:value="filters.q" clearable :placeholder="kind === 'tasks' ? '搜索任务内容' : '搜索编号或内容'" @keydown.enter="search" />
        <NSelect
          v-if="options.statuses.length"
          v-model:value="filters.status"
          clearable
          placeholder="全部状态"
          :options="options.statuses"
        />
        <NSelect
          v-if="options.owners.length"
          v-model:value="filters.ownerId"
          clearable
          filterable
          placeholder="全部负责人"
          :options="options.owners"
        />
        <NSelect
          v-if="options.subtypes.length"
          v-model:value="filters.subtype"
          clearable
          :placeholder="kind === 'quotations' ? '全部币种' : '全部类型'"
          :options="options.subtypes"
        />
        <NDatePicker
          v-if="['inquiries', 'quotations', 'samples'].includes(kind)"
          v-model:formatted-value="filters.date"
          type="date"
          value-format="yyyy-MM-dd"
          clearable
          :placeholder="kind === 'quotations' ? '有效期截止日期' : '日期'"
        />
        <NSpace
          ><NButton type="primary" ghost @click="search">查询</NButton><NButton @click="reset">重置</NButton></NSpace
        >
      </NForm>
      <NAlert v-if="optionsError" type="warning" class="mb-12px"
        >筛选选项加载失败：{{ optionsError }}<NButton text @click="loadOptions">重试筛选选项</NButton></NAlert
      >
      <NAlert v-if="error" type="error" title="记录加载失败"
        ><div>{{ error }}</div>
        <NButton @click="load">重新加载</NButton
        ><NButton
          v-if="page > 1"
          @click="
            page = 1;
            load();
          "
          >返回第一页</NButton
        ></NAlert
      >
      <NDataTable
        v-else
        :columns="columns"
        :data="rows"
        :loading="loading"
        :row-key="(row) => row.id"
        :scroll-x="headers[kind].reduce((sum, item) => sum + item[2], 0)"
        :pagination="pagination"
        remote
        size="small"
      >
        <template #empty><NEmpty description="当前客户暂无符合条件的记录" /></template>
      </NDataTable>
      <NText depth="3" class="mt-12px block"
        >共 {{ total }} 条。{{
          kind === 'inquiries' ? '点击询盘编号查看详情。' : '本页展示关联记录，详情及写操作待接入。'
        }}</NText
      >
    </template>
  </NCard>
</template>

<style scoped>
.record-search {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}
</style>
