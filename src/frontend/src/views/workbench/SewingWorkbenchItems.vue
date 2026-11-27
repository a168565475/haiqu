<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { getSewingItems } from '@/api/sewingOutsourcingWorkbench'
import type { SewingQueue, SewingWorkbenchOrder } from '@/types/sewingOutsourcingWorkbench'
import { workbenchErrorMessage } from '@/utils/workbench'

const props = defineProps<{ category: SewingQueue; title: string; asOf: string; date?: string }>()
const emit = defineEmits<{ close: [] }>()
const page = ref(1), total = ref(0), retry = ref(0)
const rows = ref<SewingWorkbenchOrder[]>([]), loading = ref(true), error = ref('')
const sending = computed(() => ['send', 'late_send', 'today_send', 'partial'].includes(props.category))
watch([() => props.category, () => props.date, page, retry], async ([category, date, number], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  rows.value = []
  loading.value = true
  error.value = ''
  try {
    const result = await getSewingItems(category, number, date, request.signal)
    if (!request.signal.aborted) { rows.value = result.data; total.value = result.meta.total }
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载外协单明细')
  } finally {
    if (!request.signal.aborted) loading.value = false
  }
}, { immediate: true })
const orders = computed(() => rows.value.map(order => {
  const lines = sending.value ? order.materials : order.parts
  const due = sending.value ? order.planned_dispatch_date : order.expected_return_date
  return { order, lines: lines.length ? lines : [null], due, daysLate: (Date.parse(props.asOf) - Date.parse(due)) / 86_400_000 }
}))
</script>

<template>
  <AppWindowDialog :model-value="true" :title="title" :width="1140" :min-width="300" :minimizable="false" @update:model-value="value => { if (!value) emit('close') }">
    <p v-if="error" role="alert">{{ error }} <ElButton link type="primary" @click="retry++">重试</ElButton></p>
    <p v-else-if="loading" role="status">正在加载外协单明细…</p>
    <p v-else-if="!rows.length">当前没有这类外协单。</p>
    <div v-else class="table-scroll">
      <table><thead><tr>
        <th>生产任务单号</th><th>外协单号</th><th>加工厂</th><th>{{ sending ? '投入材料' : '应回部位' }}</th>
        <th>{{ sending ? '计划发料日' : '预计回货日' }}</th><th>{{ sending ? '目标' : '应回' }}</th>
        <th>{{ sending ? '已发' : '已回' }}</th><th>{{ sending ? '待发' : '尚欠' }}</th>
        <th>{{ sending ? '总单最近发料日' : '总单最近回货日' }}</th>
      </tr></thead>
        <tbody v-for="{ order, lines, due, daysLate } in orders" :key="order.id">
          <tr v-for="(line, index) in lines" :key="index">
            <td v-if="index === 0" :rowspan="lines.length"><RouterLink :to="{ name: 'workshop-outsourcing-tube-detail', params: { id: order.id } }">{{ order.task_number }}</RouterLink><small>{{ order.product_name }}</small></td>
            <td v-if="index === 0" :rowspan="lines.length">{{ order.order_number }}</td>
            <td>{{ line?.factory_name || order.factories.join('、') || '待核对' }}</td><td>{{ line?.name || '待核对' }}</td>
            <td v-if="index === 0" :rowspan="lines.length">{{ due || '待核对' }}<small v-if="daysLate > 0" class="overdue">逾期 {{ daysLate }} 天</small></td>
            <template v-if="line"><td>{{ line.target }} {{ line.unit }}</td><td>{{ line.actual }} {{ line.unit }}</td><td><b>{{ line.remaining }} {{ line.unit }}</b></td></template>
            <template v-else><td>—</td><td>—</td><td>—</td></template>
            <td v-if="index === 0" :rowspan="lines.length">{{ (sending ? order.last_dispatch_date : order.last_receipt_date) || '尚无记录' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <footer v-if="!loading && !error">共 {{ total }} 张总单
      <ElPagination v-if="total > 20" v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next" background />
    </footer>
  </AppWindowDialog>
</template>

<style scoped>
.table-scroll { overflow:auto; max-height:60vh; }
table { width:100%; border-collapse:collapse; text-align:left; font-size:13px; }
th, td { padding:11px 10px; border-bottom:1px solid var(--erp-color-border-subtle); vertical-align:top; }
th { position:sticky; top:0; white-space:nowrap; background:var(--erp-table-header-background); color:var(--erp-color-text-secondary); }
td small { display:block; margin-top:4px; color:var(--erp-color-text-secondary); }
td a { color:var(--erp-menu-accent); font-weight:650; text-decoration:none; white-space:nowrap; }
td a:hover { text-decoration:underline; }
.overdue { color:var(--erp-color-danger); }
footer { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-top:14px; color:var(--erp-color-text-secondary); font-size:13px; }
</style>
