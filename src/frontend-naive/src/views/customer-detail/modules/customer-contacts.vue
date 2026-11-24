<script setup lang="tsx">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue';
import { NTag } from 'naive-ui';
import type { DataTableColumns } from 'naive-ui';
import { fetchCustomerContacts } from '@/service/api/customer-detail';
import type { CustomerContact } from '@/typings/customer-detail';
import { formatInquiryTime } from '../../inquiry-detail/shared';

const props = defineProps<{
  customerId: string;
  canRead: boolean;
  beforeRead: (signal: AbortSignal) => Promise<boolean>;
}>();
const emit = defineEmits<{ expired: [] }>();
const rows = shallowRef<CustomerContact[]>([]);
const q = ref('');
const status = ref<CustomerContact['status'] | null>(null);
let applied = { q: '', status: null as CustomerContact['status'] | null };
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const loading = ref(false);
const error = ref('');
let controller = new AbortController();
const columns: DataTableColumns<CustomerContact> = [
  { key: 'display_name', title: '联系人', width: 160, ellipsis: { tooltip: true } },
  {
    key: 'english_name',
    title: '英文名',
    width: 140,
    ellipsis: { tooltip: true },
    render: (row) => row.english_name || '—'
  },
  {
    key: 'position_title',
    title: '职务 / 部门',
    width: 160,
    ellipsis: { tooltip: true },
    render: (row) => [row.position_title, row.department_name].filter(Boolean).join(' / ') || '—'
  },
  {
    key: 'roles',
    title: '角色',
    width: 150,
    ellipsis: { tooltip: true },
    render: (row) => row.active_roles.map((role) => role.role_type_display).join('、') || '—'
  },
  {
    key: 'methods',
    title: '联系方式',
    width: 260,
    render: (row) =>
      row.methods.length ? (
        <div class="flex-col gap-4px">
          {row.methods.map((method) => (
            <span>
              {method.method_type_display}：{method.display_value || method.masked_value || '—'}
            </span>
          ))}
        </div>
      ) : (
        '—'
      )
  },
  {
    key: 'primary',
    title: '主要 / 关键',
    width: 140,
    render: (row) => (
      <div class="flex gap-4px">
        {row.is_primary_contact && (
          <NTag size="small" type="primary" bordered={false}>
            主要
          </NTag>
        )}
        {row.is_key_contact && (
          <NTag size="small" type="warning" bordered={false}>
            关键
          </NTag>
        )}
        {!row.is_primary_contact && !row.is_key_contact ? '—' : null}
      </div>
    )
  },
  {
    key: 'status',
    title: '状态',
    width: 100,
    render: (row) => (
      <NTag size="small" bordered={false} type={row.status === 'ACTIVE' ? 'success' : 'default'}>
        {row.status_display}
      </NTag>
    )
  },
  {
    key: 'language',
    title: '语言 / 时区',
    width: 180,
    render: (row) => [row.preferred_language_code, row.timezone_code].filter(Boolean).join(' / ') || '—'
  },
  {
    key: 'last_interaction',
    title: '最近互动',
    width: 170,
    render: (row) => formatInquiryTime(row.last_interaction?.occurred_at)
  },
  { key: 'open_task_count', title: '未完成任务', width: 110 }
];
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
async function load() {
  controller.abort();
  controller = new AbortController();
  const signal = controller.signal;
  rows.value = [];
  error.value = '';
  total.value = 0;
  if (!props.canRead) return;
  loading.value = true;
  try {
    if (!(await props.beforeRead(signal))) return;
    const result = await fetchCustomerContacts(
      props.customerId,
      { page: page.value, page_size: pageSize.value, q: applied.q || undefined, status: applied.status || undefined },
      signal
    );
    if (!signal.aborted) {
      rows.value = result.data;
      total.value = result.meta.total;
    }
  } catch (value) {
    if (!signal.aborted) {
      if (value instanceof Error && 'status' in value && value.status === 401) emit('expired');
      error.value = value instanceof Error ? value.message : '联系人读取失败，请重试。';
    }
  } finally {
    if (signal === controller.signal) loading.value = false;
  }
}
function search() {
  applied = { q: q.value.trim(), status: status.value };
  page.value = 1;
  void load();
}
function reset() {
  q.value = '';
  status.value = null;
  search();
}
watch(() => [props.customerId, props.canRead], reset, { immediate: true });
onUnmounted(() => controller.abort());
</script>

<template>
  <NCard title="客户联系人" :bordered="false" class="card-wrapper" data-testid="customer-contacts">
    <template #header-extra
      ><NButton size="small" :loading="loading" :disabled="!canRead" @click="load">刷新</NButton></template
    >
    <NResult v-if="!canRead" status="403" title="暂无联系人查看权限" />
    <template v-else>
      <div class="contact-search">
        <NInput v-model:value="q" clearable placeholder="搜索联系人" :disabled="loading" @keydown.enter="search" />
        <NSelect
          v-model:value="status"
          clearable
          placeholder="全部状态"
          :options="[
            { label: '在职', value: 'ACTIVE' },
            { label: '停用', value: 'INACTIVE' },
            { label: '离职', value: 'LEFT' }
          ]"
          :disabled="loading"
        />
        <NSpace
          ><NButton type="primary" ghost :disabled="loading" @click="search">查询</NButton
          ><NButton :disabled="loading" @click="reset">重置</NButton></NSpace
        >
      </div>
      <NAlert v-if="error" type="error" title="联系人加载失败"
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
        :pagination="pagination"
        :scroll-x="1670"
        :row-key="(row) => row.id"
        remote
        size="small"
      >
        <template #empty><NEmpty description="暂无符合条件的联系人" /></template>
      </NDataTable>
      <NText depth="3" class="mt-12px block">共 {{ total }} 位联系人；新建、编辑及联系人详情待接入。</NText>
    </template>
  </NCard>
</template>

<style scoped>
.contact-search {
  display: grid;
  grid-template-columns: minmax(180px, 320px) minmax(140px, 200px) auto;
  gap: 12px;
  margin-bottom: 16px;
}
@media (max-width: 639px) {
  .contact-search {
    grid-template-columns: 1fr;
  }
}
</style>
