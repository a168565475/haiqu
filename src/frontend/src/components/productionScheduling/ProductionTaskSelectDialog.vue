<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { Filter, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import { fetchTaskCandidate, fetchTaskCandidates } from '@/api/productionScheduling'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import ProductionTaskMoreFiltersDialog from '@/components/productionScheduling/ProductionTaskMoreFiltersDialog.vue'
import type { ScheduleTaskCandidate } from '@/types/productionScheduling'

interface ProductionTaskFilters {
  product_search: string
  delivery_dates: [string, string] | []
}

const MAX_TASK_SELECTION = 50

const props = defineProps<{
  modelValue: boolean
  selectedTasks: ScheduleTaskCandidate[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; select: [tasks: ScheduleTaskCandidate[]] }>()
const loading = ref(false)
const rows = ref<ScheduleTaskCandidate[]>([])
const search = ref('')
const page = ref(1)
const total = ref(0)
const errorMessage = ref('')
const confirming = ref(false)
const pending = ref<ScheduleTaskCandidate[]>([])
const pendingIds = computed(() => new Set(pending.value.map(item => item.id)))
const moreFiltersVisible = ref(false)
const appliedFilters = reactive<ProductionTaskFilters>({ product_search: '', delivery_dates: [] })
const hasMoreFilters = computed(() => Boolean(
  appliedFilters.product_search || appliedFilters.delivery_dates.length,
))
let latestRequest = 0

async function load() {
  const requestNumber = ++latestRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchTaskCandidates({
      page: page.value,
      page_size: 50,
      ready_only: true,
      search: search.value.trim() || undefined,
      product_search: appliedFilters.product_search || undefined,
      delivery_from: appliedFilters.delivery_dates[0] || undefined,
      delivery_to: appliedFilters.delivery_dates[1] || undefined,
    })
    if (requestNumber !== latestRequest) return
    rows.value = result.data
    total.value = result.meta.total
  } catch {
    if (requestNumber !== latestRequest) return
    rows.value = []
    total.value = 0
    errorMessage.value = '生产任务单加载失败，请稍后重试。'
  } finally {
    if (requestNumber === latestRequest) loading.value = false
  }
}

async function confirm() {
  if (!pending.value.length || confirming.value) return
  const requestedTaskIds = pending.value.map(item => item.id)
  confirming.value = true
  try {
    const results = await Promise.allSettled(requestedTaskIds.map(fetchTaskCandidate))
    if (!props.modelValue || requestedTaskIds.some(id => !pendingIds.value.has(id))) return
    const transientFailure = results.find(result => (
      result.status === 'rejected'
      && (!(result.reason instanceof AxiosError) || ![403, 404].includes(result.reason.response?.status || 0))
    ))
    if (transientFailure?.status === 'rejected') throw transientFailure.reason
    const details = results.flatMap(result => result.status === 'fulfilled' ? [result.value] : [])
    const unavailableIds = new Set([
      ...details.filter(item => !item.selectable).map(item => item.id),
      ...results.flatMap((result, index) => result.status === 'rejected' ? [requestedTaskIds[index]] : []),
    ])
    if (unavailableIds.size) {
      pending.value = details.filter(item => item.selectable)
      const reasons = [...new Set(details.filter(item => !item.selectable).map(item => item.unselectable_reason).filter(Boolean))]
      ElMessage.warning(reasons.length
        ? `无法排产：${reasons.join('；')}。`
        : '部分生产任务单已失效或不可访问，已从选择中移除，请核对后重新确认。')
      await load()
      return
    }
    emit('select', details)
    emit('update:modelValue', false)
  } catch {
    ElMessage.error('生产任务单状态校验失败，请稍后重试。')
  } finally {
    confirming.value = false
  }
}

function applyMoreFilters(filters: ProductionTaskFilters) {
  Object.assign(appliedFilters, filters)
  page.value = 1
  void load()
}

function selectRow(row: ScheduleTaskCandidate) {
  if (confirming.value || !row.selectable) return
  if (!pendingIds.value.has(row.id) && pending.value.length >= MAX_TASK_SELECTION) {
    ElMessage.warning(`单次最多选择 ${MAX_TASK_SELECTION} 张生产任务单。`)
    return
  }
  pending.value = pendingIds.value.has(row.id)
    ? pending.value.filter(item => item.id !== row.id)
    : [...pending.value, row]
}

function rowClassName({ row }: { row: ScheduleTaskCandidate }) {
  return pendingIds.value.has(row.id) ? 'is-task-selected' : ''
}

function productSummary(task: ScheduleTaskCandidate) {
  const products = task.product_summaries || []
  const quantities = new Map<string, number>()
  products.forEach(item => quantities.set(item.unit_name, (quantities.get(item.unit_name) || 0) + Number(item.quantity || 0)))
  const quantityText = [...quantities.entries()]
    .map(([unit, quantity]) => `${quantity.toLocaleString('zh-CN')} ${unit}`)
    .join(' + ')
  return `共 ${task.product_count} 个产品${quantityText ? ` · 合计 ${quantityText}` : ''}`
}

watch(() => props.modelValue, visible => {
  if (!visible) return
  pending.value = [...props.selectedTasks]
})
</script>

<template>
  <AppWindowDialog
    :model-value="modelValue"
    :width="1410"
    :height="700"
    class="schedule-task-dialog"
    title="选择生产任务单"
    destroy-on-close
    :close-on-click-modal="!confirming"
    :close-on-press-escape="!confirming"
    :show-close="!confirming"
    @open="load"
    @update:model-value="value => emit('update:modelValue', value)"
    @close="emit('update:modelValue', false)"
  >
    <div class="task-dialog-layout">
      <aside class="task-dialog-summary">
        <h3>已选择 {{ pending.length }} 张生产任务单（最多 {{ MAX_TASK_SELECTION }} 张）</h3>
        <template v-if="pending.length">
          <article v-for="task in pending" :key="task.id" class="task-dialog-summary__task">
            <strong>{{ task.task_number }}</strong>
            <small>交货：{{ task.delivery_date }}</small>
            <small>{{ productSummary(task) }}</small>
            <div class="task-dialog-summary__task-products">
              <div v-for="product in task.product_summaries.slice(0, 3)" :key="product.id">
                <p>
                  <b>{{ product.product_name || '—' }}</b>
                  <small>{{ product.item_number || '—' }} · {{ product.quantity.toLocaleString('zh-CN') }} {{ product.unit_name }}</small>
                  <small>规格：{{ product.specification || '—' }}</small>
                  <small>颜色：{{ product.color_name || '—' }}</small>
                </p>
              </div>
              <small v-if="task.product_summaries.length > 3">另有 {{ task.product_summaries.length - 3 }} 个产品</small>
            </div>
          </article>
        </template>
        <ElEmpty v-else :image-size="56" description="尚未选择任务单" />
      </aside>
      <section class="task-dialog-results">
        <div class="task-dialog-toolbar">
          <ElInput
            v-model="search"
            :prefix-icon="Search"
            clearable
            maxlength="200"
            placeholder="搜索生产任务单号、产品"
            @keyup.enter="page = 1; load()"
            @clear="page = 1; load()"
          />
          <ElSelect model-value="READY" aria-label="任务状态">
            <ElOption label="排产状态：可排产" value="READY" />
          </ElSelect>
          <ElButton :icon="Filter" :class="{ 'is-filtered': hasMoreFilters }" @click="moreFiltersVisible = true">更多筛选</ElButton>
          <ElButton :icon="Refresh" :loading="loading" @click="load">刷新</ElButton>
        </div>
        <ElAlert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />
        <ElTable
          v-loading="loading"
          :data="rows"
          border
          height="420"
          row-key="id"
          :row-class-name="rowClassName"
          @row-click="selectRow"
        >
          <ElTableColumn width="42" align="center">
            <template #default="{ row }"><ElCheckbox :model-value="pendingIds.has(row.id)" :disabled="!row.selectable" aria-label="选择任务" @click.stop="selectRow(row)" /></template>
          </ElTableColumn>
          <ElTableColumn prop="task_number" label="生产任务单号" width="138" show-overflow-tooltip />
          <ElTableColumn label="产品名称" min-width="150"><template #default="{ row }"><div class="task-product-values"><span v-for="product in row.product_summaries.slice(0, 2)" :key="`${product.id}-name`">{{ product.product_name || '—' }}</span><small v-if="row.product_summaries.length > 2">+{{ row.product_summaries.length - 2 }}</small></div></template></ElTableColumn>
          <ElTableColumn label="货号" width="108"><template #default="{ row }"><div class="task-product-values"><span v-for="product in row.product_summaries.slice(0, 2)" :key="`${product.id}-number`">{{ product.item_number || '—' }}</span><small v-if="row.product_summaries.length > 2">+{{ row.product_summaries.length - 2 }}</small></div></template></ElTableColumn>
          <ElTableColumn label="规格" min-width="170"><template #default="{ row }"><div class="task-product-values"><span v-for="product in row.product_summaries.slice(0, 2)" :key="`${product.id}-specification`">{{ product.specification || '—' }}</span><small v-if="row.product_summaries.length > 2">+{{ row.product_summaries.length - 2 }}</small></div></template></ElTableColumn>
          <ElTableColumn label="颜色" width="100"><template #default="{ row }"><div class="task-product-values"><span v-for="product in row.product_summaries.slice(0, 2)" :key="`${product.id}-color`">{{ product.color_name || '—' }}</span><small v-if="row.product_summaries.length > 2">+{{ row.product_summaries.length - 2 }}</small></div></template></ElTableColumn>
          <ElTableColumn label="订单数量" width="110"><template #default="{ row }"><div class="task-product-values"><span v-for="product in row.product_summaries.slice(0, 2)" :key="`${product.id}-quantity`">{{ product.quantity.toLocaleString('zh-CN') }} {{ product.unit_name }}</span><small v-if="row.product_summaries.length > 2">+{{ row.product_summaries.length - 2 }}</small></div></template></ElTableColumn>
          <ElTableColumn prop="delivery_date" label="交货日期" width="132" />
          <ElTableColumn label="任务状态" width="90" align="center"><template #default="{ row }"><ElTag effect="dark" type="success">{{ row.status_display }}</ElTag></template></ElTableColumn>
        </ElTable>
        <ElPagination v-model:current-page="page" :page-size="50" :total="total" layout="total, prev, pager, next" @current-change="load" />
      </section>
    </div>
    <template #footer><ElButton :disabled="confirming" @click="emit('update:modelValue', false)">取消</ElButton><ElButton type="primary" :disabled="!pending.length" :loading="confirming" @click="confirm">确认选择（{{ pending.length }}）</ElButton></template>
    <ProductionTaskMoreFiltersDialog v-model="moreFiltersVisible" :filters="appliedFilters" @apply="applyMoreFilters" />
  </AppWindowDialog>
</template>
