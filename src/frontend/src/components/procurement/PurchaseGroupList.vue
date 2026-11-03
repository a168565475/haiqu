<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchPurchaseGroupFilterOptions, fetchPurchaseGroups } from '@/api/purchaseGroups'
import type { PurchaseGroup, PurchaseGroupFilterOptions, PurchaseGroupProduct, PurchaseGroupProgress } from '@/types/purchaseGroup'

defineProps<{ canAdd: boolean }>()
const router = useRouter()
const rows = ref<PurchaseGroup[]>([])
const tasks = ref<PurchaseGroupFilterOptions['production_tasks']>([])
const taskId = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const loading = ref(false)
const errorMessage = ref('')
const optionsError = ref('')
let requestVersion = 0
const statusLabels = { PENDING: '待采购', PURCHASING: '采购中', COMPLETED: '采购完成', UNKNOWN: '来源待核对' }
const displayRows = computed(() => rows.value.map(row => ({ row, totalPercent: totalPurchaseProgress(row.progress) })))

function totalPurchaseProgress(progress: PurchaseGroupProgress): number | null {
  if (progress.status === 'UNKNOWN' || !progress.lines.length || progress.lines.length !== progress.line_count) return null
  const percentages = progress.lines.map(line => line.progress_percent !== null && /^\d+(?:\.\d+)?$/.test(line.progress_percent)
    ? Number(line.progress_percent) : NaN)
  if (percentages.some(value => !Number.isFinite(value))) return null
  const satisfied = progress.lines.filter(line => line.is_satisfied).length
  if (satisfied !== progress.satisfied_line_count || (progress.status === 'COMPLETED') !== (satisfied === progress.line_count)) return null
  const average = percentages.reduce((sum, value) => sum + Math.min(value, 100), 0) / progress.line_count
  // 逐项百分比已四舍五入，只有原始数量全部达标才显示100%。
  return satisfied === progress.line_count ? 100 : Math.min(Math.round(average * 10) / 10, 99.9)
}

function productColor(product: PurchaseGroupProduct | null | undefined): string {
  return [product?.color_card, product?.color_name, product?.color_code].filter(Boolean).join(' / ') || '—'
}
function orderQuantity(product: PurchaseGroupProduct | null | undefined): string {
  return product?.order_quantity ? [product.order_quantity, product.order_unit].filter(Boolean).join(' ') : '—'
}

async function load(): Promise<void> {
  const version = ++requestVersion
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchPurchaseGroups({ page: page.value, page_size: pageSize.value, ...(taskId.value ? { production_task_id: taskId.value } : {}) })
    if (version !== requestVersion) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (version !== requestVersion) return
    rows.value = []
    total.value = 0
    errorMessage.value = (error as { response?: { data?: { error?: { message?: string } } } }).response?.data?.error?.message || '采购总单加载失败，请重试。'
  } finally {
    if (version === requestVersion) loading.value = false
  }
}
function search(): void { page.value = 1; void load() }
async function loadOptions(): Promise<void> {
  optionsError.value = ''
  try { tasks.value = (await fetchPurchaseGroupFilterOptions()).production_tasks }
  catch { optionsError.value = '生产订单筛选选项加载失败。' }
}
onMounted(() => { void load(); void loadOptions() })
onBeforeUnmount(() => { requestVersion++ })
</script>

<template>
  <section class="group-list" data-testid="purchase-group-list">
    <div class="group-toolbar">
      <ElSelect v-model="taskId" filterable clearable placeholder="全部生产订单" aria-label="总单生产订单筛选" @change="search">
        <ElOption v-for="task in tasks" :key="task.id" :value="task.id" :label="`${task.task_number} · ${task.order_number}`" />
      </ElSelect>
      <ElButton @click="load">刷新</ElButton>
      <span>共 {{ total }} 张总单</span>
      <ElButton v-if="canAdd" type="primary" @click="router.push({ name: 'purchase-order-create' })">新建采购总单</ElButton>
    </div>
    <ElAlert v-if="optionsError" type="warning" :title="optionsError" :closable="false"><ElButton link @click="loadOptions">重试选项</ElButton></ElAlert>
    <ElAlert v-if="errorMessage" type="error" :title="errorMessage" :closable="false"><ElButton link @click="load">重新加载</ElButton></ElAlert>
    <div v-loading="loading" class="group-table-frame">
      <table class="group-table">
        <colgroup>
          <col style="width: 160px"><col style="width: 150px"><col style="width: 180px"><col style="width: 160px">
          <col style="width: 170px"><col style="width: 110px"><col style="width: 100px"><col style="width: 115px">
          <col style="width: 170px"><col style="width: 130px"><col style="width: 65px"><col style="width: 110px"><col style="width: 110px">
        </colgroup>
        <thead><tr><th>采购总单</th><th>来源订单</th><th>产品</th><th>规格</th><th>颜色</th><th>材质</th><th>订单量</th><th>订单交期</th><th>总采购进度</th><th>材料进度</th><th>批次</th><th>状态</th><th>操作</th></tr></thead>
        <tbody><tr v-for="{ row, totalPercent } in displayRows" :key="row.id">
          <td><strong>{{ row.group_number }}</strong></td>
          <td>{{ row.production_task_number_snapshot }}</td>
          <td>{{ row.product?.product_name || '来源待核对' }}</td>
          <td>{{ row.product?.specification || '—' }}</td>
          <td>{{ productColor(row.product) }}</td>
          <td>{{ row.product?.material || '—' }}</td>
          <td>{{ orderQuantity(row.product) }}</td>
          <td>{{ row.order_delivery_date || '—' }}</td>
          <td data-testid="purchase-group-total-progress"><div v-if="totalPercent !== null" class="total-progress"><ElProgress :percentage="totalPercent" :show-text="false" :stroke-width="10" :status="row.progress.status === 'COMPLETED' ? 'success' : undefined" :aria-label="`总采购进度 ${totalPercent}%`" /><span>{{ totalPercent }}%</span></div><span v-else class="unknown">待核对</span></td>
          <td>{{ row.progress.satisfied_line_count }} / {{ row.progress.line_count }} 项达标</td><td>{{ row.batches.length }}</td>
            <td>{{ statusLabels[row.display_status ?? row.progress.status] }}</td>
          <td><ElButton link type="primary" @click="router.push({ name: 'purchase-group-detail', params: { id: row.id } })">查看明细</ElButton></td>
        </tr><tr v-if="!loading && !rows.length"><td colspan="13" class="empty">{{ errorMessage ? '未能加载总单' : '暂无采购总单' }}</td></tr></tbody>
      </table>
    </div>
    <ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="search" />
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/procurementGroups';
@use '@/styles/theme/detail' as detail;
.group-list { @include detail.surface; padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 14px; min-height: 0; }
.group-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.group-toolbar .el-select { width: 280px; }
.group-toolbar > span { flex: 1; color: var(--erp-color-text-secondary); font-size: 12px; }
.group-table { min-width: 1730px; width: 100%; }
.total-progress { display: grid; grid-template-columns: 80px 44px; align-items: center; gap: 8px; }
.total-progress > span { text-align: right; font-variant-numeric: tabular-nums; }
</style>
