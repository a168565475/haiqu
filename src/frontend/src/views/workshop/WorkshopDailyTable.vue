<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { fetchWorkshopDailyReport } from '@/api/workshopDailyReport'
import type { WorkshopDailyPage, WorkshopDailyRow, WorkshopDailyTable } from '@/types/workshopDailyReport'
import { workbenchErrorMessage } from '@/utils/workbench'

const props = defineProps<{ report: WorkshopDailyTable; date: string; taskNumber: string }>()

type Column = { field: keyof WorkshopDailyRow | 'product_color'; label: string; numeric?: boolean }
const task: Column = { field: 'task_number', label: '生产任务单号' }
const product: Column = { field: 'product_name', label: '产品名称' }
const color: Column = { field: 'color', label: '颜色' }
const orderQuantity: Column = { field: 'order_quantity', label: '订单量', numeric: true }
const today: Column = { field: 'today', label: '当日完成', numeric: true }
const cumulative: Column = { field: 'cumulative', label: '累计完成', numeric: true }
const remaining: Column = { field: 'remaining', label: '还差', numeric: true }
const tables: Record<WorkshopDailyTable, { title: string; minWidth: number; widths: number[]; columns: Column[]; note?: string }> = {
  metal: { title: '管件完成进度', minWidth: 825, widths: [14, 16, 14, 17, 9, 11, 10, 9], columns: [task, product,
    { field: 'part_name', label: '管件名称' }, { field: 'specification', label: '管子规格（mm）' },
    { ...orderQuantity, label: '应做' }, today, cumulative, remaining] },
  'sewing-detail': { title: '员工工序明细', minWidth: 626, widths: [18, 20, 10, 13, 21, 18], columns: [task, product, color,
    { field: 'employee', label: '员工' }, { field: 'operation', label: '工序' },
    { ...today, label: '当日工序数量' }] },
  'sewing-orders': { title: '订单进度', minWidth: 525, widths: [22, 29, 17, 17, 15], columns: [task,
    { field: 'product_color', label: '产品 / 颜色' }, orderQuantity, cumulative, remaining],
    note: '“累计完成”和“还差”的统计方式待核对。' },
  assembly: { title: '产品装配进度', minWidth: 740, widths: [16, 23, 13, 12, 12, 12, 12],
    columns: [task, product, color, orderQuantity, today, cumulative, remaining],
    note: '按车间提交成品入库申请的日期统计。' },
}
const table = computed(() => tables[props.report])
const rows = ref<WorkshopDailyRow[]>([])
const meta = ref<WorkshopDailyPage['meta']>()
const loading = ref(false)
const errorMessage = ref('')
let controller: AbortController | undefined

async function load(page = 1) {
  controller?.abort()
  const { signal } = controller = new AbortController()
  loading.value = true
  errorMessage.value = ''
  rows.value = []
  try {
    const result = await fetchWorkshopDailyReport({
      report: props.report, date: props.date, task_number: props.taskNumber, page,
    }, signal)
    if (!signal.aborted) {
      rows.value = result.data
      meta.value = result.meta
    }
  } catch (error) {
    if (signal.aborted) return
    meta.value = undefined
    errorMessage.value = workbenchErrorMessage(error, '加载车间日报')
  } finally {
    if (!signal.aborted) loading.value = false
  }
}

function display(row: WorkshopDailyRow, column: Column) {
  if (column.field === 'product_color') return [row.product_name, row.color].filter(Boolean).join(' / ')
  const value = row[column.field]
  if (!column.numeric) return value || '—'
  if (value == null) return props.report === 'sewing-orders' ? '待定' : props.report === 'assembly' ? '无查看权限' : '—'
  const [whole = '', fraction] = value.split('.')
  const formatted = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (fraction ? `.${fraction}` : '')
  const unit = props.report === 'metal' ? '' : row.order_unit || row.unit
  return unit ? `${formatted} ${unit}` : formatted
}

watch(() => [props.report, props.date, props.taskNumber], () => void load(), { immediate: true })
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <section class="daily-table" :data-report="report" :aria-busy="loading">
    <div class="daily-table__title">
      <h2>{{ table.title }}</h2>
      <span v-if="report === 'metal'">单位：支</span>
    </div>
    <div class="erp-list-table-frame">
      <div class="erp-list-table-scroll">
        <table class="erp-list-native-table erp-list-native-table--nowrap" :aria-label="table.title"
          :style="{ minWidth: `${table.minWidth}px` }">
          <colgroup><col v-for="(column, index) in table.columns" :key="column.field" :style="{ width: `${table.widths[index]}%` }"></colgroup>
          <thead>
            <tr>
              <th v-for="column in table.columns" :key="column.field" scope="col" :class="{ num: column.numeric }">{{ column.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td v-for="column in table.columns" :key="column.field" :title="display(row, column)" :class="{
                num: column.numeric, 'daily-table__task': column.field === 'task_number',
                'daily-table__today': column.field === 'today' && row.today !== undefined,
                'daily-table__pending': column.numeric && column.field !== 'product_color' && row[column.field] == null,
              }">{{ display(row, column) }}</td>
            </tr>
            <tr v-if="rows.length === 0">
              <td class="empty" :colspan="table.columns.length">
                <div v-if="errorMessage" role="alert">{{ errorMessage }} <ElButton link type="primary" @click="load()">重试</ElButton></div>
                <template v-else-if="loading">加载中…</template>
                <template v-else>没有匹配的任务单</template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <ElPagination v-if="meta && meta.total_pages > 1" small layout="prev, pager, next" :disabled="loading"
      :total="meta.total" :page-size="meta.page_size" :current-page="meta.page" @current-change="load" />
    <p v-if="table.note" class="daily-table__note">{{ table.note }}</p>
  </section>
</template>

<style scoped>
.daily-table { min-width: 0; }
.daily-table__title { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; }
.daily-table__title h2 { margin: 0; font-size: 17px; line-height: 24px; }
.daily-table__title span, .daily-table__note { color: var(--erp-color-text-secondary); font-size: 13px; }
.daily-table__note { margin: 10px 1px 0; }
.daily-table__task { font-weight: 600; }
.daily-table__today { color: var(--erp-color-brand); font-weight: 700; }
.daily-table__pending { color: var(--erp-color-text-secondary); }
.el-pagination { justify-content: flex-end; margin-top: 8px; }
</style>
