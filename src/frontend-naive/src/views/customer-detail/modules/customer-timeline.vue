<script setup lang="ts">
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue';
import { fetchCustomerTimeline } from '@/service/api/customer-detail';
import type { CustomerTimelineEvent, CustomerTimelineQuery } from '@/typings/customer-detail';
import { formatInquiryTime } from '../../inquiry-detail/shared';

const props = defineProps<{
  customerId: string;
  canRead: boolean;
  beforeRead: (signal: AbortSignal) => Promise<boolean>;
}>();
const emit = defineEmits<{ expired: []; openInquiry: [id: string] }>();
const rows = shallowRef<CustomerTimelineEvent[]>([]);
const cursor = ref<string | null>(null);
const loading = ref(false);
const error = ref('');
const keyword = ref('');
const eventType = ref<string | null>(null);
const from = ref<number | null>(null);
const to = ref<number | null>(null);
let applied: CustomerTimelineQuery = {};
let controller = new AbortController();
const filteredRows = computed(() =>
  rows.value.filter((row) => `${row.title} ${row.summary}`.includes(keyword.value.trim()))
);
function plainText(value: string) {
  return new DOMParser().parseFromString(value || '', 'text/html').body.textContent?.trim() || '';
}
function sourceLabel(row: CustomerTimelineEvent) {
  const labels: Record<string, string> = {
    CUSTOMER: '客户资料',
    CUSTOMER_ACCOUNT: '客户档案',
    COMMUNICATION: '沟通',
    CUSTOMER_COMMUNICATION: '沟通',
    TASK: '任务',
    BUSINESS_TASK: '任务',
    INQUIRY: '询盘',
    QUOTATION: '报价',
    QUOTATION_VERSION: '报价',
    SAMPLE_REQUEST: '样品',
    CUSTOMER_CONTACT: '联系人',
    SALES_ORDER: '订单',
    CUSTOMER_COMPLAINT: '客诉'
  };
  return labels[row.source_type] || '业务记录';
}
async function load(append = false) {
  if (loading.value && append) return;
  controller.abort();
  controller = new AbortController();
  const signal = controller.signal;
  if (!append) {
    rows.value = [];
    cursor.value = null;
  }
  error.value = '';
  if (!props.canRead) return;
  loading.value = true;
  try {
    if (!(await props.beforeRead(signal))) return;
    const result = await fetchCustomerTimeline(
      props.customerId,
      { ...applied, cursor: append ? cursor.value || undefined : undefined },
      signal
    );
    if (!signal.aborted) {
      rows.value = append ? [...rows.value, ...result.data] : result.data;
      cursor.value = result.meta.next;
    }
  } catch (value) {
    if (!signal.aborted) {
      if (value instanceof Error && 'status' in value && value.status === 401) emit('expired');
      error.value = value instanceof Error ? value.message : '时间轴读取失败，请重试。';
    }
  } finally {
    if (signal === controller.signal) loading.value = false;
  }
}
function search() {
  if (from.value !== null && to.value !== null && from.value > to.value) {
    error.value = '开始时间不能晚于结束时间。';
    return;
  }
  applied = {
    source_type: eventType.value || undefined,
    occurred_from: from.value === null ? undefined : new Date(from.value).toISOString(),
    occurred_to: to.value === null ? undefined : new Date(to.value).toISOString()
  };
  void load();
}
function reset() {
  keyword.value = '';
  eventType.value = null;
  from.value = null;
  to.value = null;
  applied = {};
  void load();
}
watch(() => [props.customerId, props.canRead], reset, { immediate: true });
onUnmounted(() => controller.abort());
</script>

<template>
  <NCard title="客户时间轴" :bordered="false" class="card-wrapper" data-testid="customer-timeline">
    <template #header-extra
      ><NButton size="small" :loading="loading" :disabled="!canRead" @click="load()">刷新</NButton></template
    >
    <NResult v-if="!canRead" status="403" title="暂无时间轴查看权限" />
    <template v-else>
      <div class="timeline-filters">
        <NInput v-model:value="keyword" clearable placeholder="筛选已加载记录" />
        <NSelect
          v-model:value="eventType"
          clearable
          placeholder="全部类型"
          :options="[
            { label: '沟通', value: 'CUSTOMER_COMMUNICATION' },
            { label: '任务', value: 'BUSINESS_TASK' },
            { label: '客户档案', value: 'CUSTOMER_ACCOUNT' }
          ]"
        />
        <NDatePicker v-model:value="from" type="datetime" clearable placeholder="开始时间" />
        <NDatePicker v-model:value="to" type="datetime" clearable placeholder="结束时间" />
        <NSpace
          ><NButton type="primary" ghost :disabled="loading" @click="search">查询</NButton
          ><NButton :disabled="loading" @click="reset">重置</NButton></NSpace
        >
      </div>
      <NAlert v-if="error" type="error" class="mb-16px"
        ><div>{{ error }}</div>
        <NButton @click="load(Boolean(cursor && rows.length))">重新加载</NButton></NAlert
      >
      <NSpin :show="loading">
        <NTimeline v-if="filteredRows.length" class="timeline-content">
          <NTimelineItem
            v-for="event in filteredRows"
            :key="event.id"
            :title="event.title"
            :time="formatInquiryTime(event.occurred_at)"
          >
            <p class="event-summary">{{ plainText(event.summary) || '无补充摘要' }}</p>
            <NSpace align="center"
              ><NTag size="small" :bordered="false">{{ sourceLabel(event) }}</NTag
              ><NButton
                v-if="event.source_type === 'INQUIRY'"
                text
                type="primary"
                @click="emit('openInquiry', event.source_id)"
                >查看询盘</NButton
              ></NSpace
            >
          </NTimelineItem>
        </NTimeline>
        <NEmpty v-else-if="!loading && !error" description="暂无符合条件的时间轴记录" class="py-32px" />
      </NSpin>
      <NSpace class="mt-16px" align="center"
        ><NText depth="3">已加载 {{ rows.length }} 条，当前显示 {{ filteredRows.length }} 条</NText
        ><NButton v-if="cursor" :loading="loading" @click="load(true)">加载更多记录</NButton></NSpace
      >
      <NText depth="3" class="mt-12px block">记录沟通及附件上传待接入。</NText>
    </template>
  </NCard>
</template>

<style scoped>
.timeline-filters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}
.timeline-content {
  padding: 8px 4px;
}
.event-summary {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  margin: 0 0 8px;
}
</style>
