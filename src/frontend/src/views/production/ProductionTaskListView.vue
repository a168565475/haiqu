<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ArrowDown, Plus, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  cancelProductionTask,
  deleteProductionTask,
  exportProductionTasks,
  fetchProductionTask,
  fetchProductionTaskFilterOptions,
  fetchProductionTasks,
  finishProductionTask,
} from '@/api/productionTasks'
import searchIcon from '@/assets/crm-v2/search.svg'
import ProductionTaskScheduleDialog from '@/components/productionScheduling/ProductionTaskScheduleDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  ProductionDeliveryMethod,
  ProductionOrderSource,
  ProductionTask,
  ProductionTaskFilterOptions,
  ProductionTaskQuery,
  ProductionTaskStatus,
} from '@/types/productionTask'

import { productLabels, productSpecifications, quantityWithUnits, localAmountTotal, isTaskReadyForScheduling } from './productionTaskDisplay'

type StatusTabKey = 'all' | 'pending' | 'draft' | 'ready' | 'production' | 'completed' | 'paused' | 'cancelled'
type LifecycleAction = 'cancel' | 'finish'

interface AdvancedFilters {
  contract_number: string
  product_id: string
  salesperson_id: string
  follower_id: string
  order_source: ProductionOrderSource | ''
  delivery_method: ProductionDeliveryMethod | ''
}

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const exportLoading = ref(false)
let latestRowsRequest = 0
let latestOptionsRequest = 0
const optionsLoading = ref(false)
const optionsError = ref('')
const rows = ref<ProductionTask[]>([])
const options = ref<ProductionTaskFilterOptions | null>(null)
const errorMessage = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const searchText = ref('')
const activeStatusTab = ref<StatusTabKey>('all')
const quantityPending = ref(false)
const dueSoon = ref(false)
const advancedVisible = ref(false)
const deliveryRange = ref<[string, string] | []>([])
const lifecycleDialogVisible = ref(false)
const lifecycleLoading = ref(false)
const lifecycleAction = ref<LifecycleAction>('cancel')
const lifecycleTarget = ref<ProductionTask | null>(null)
const lifecycleReason = ref('')
const completionActualQuantity = ref('0')
const completionGoodQuantity = ref('0')
const completionBatches = ref<Array<{ batch_number: string; planned_quantity: string; actual_quantity: string; good_quantity: string; note: string }>>([])
const scheduleDialogVisible = ref(false)
const scheduleTarget = ref<ProductionTask | null>(null)


const advancedFilters = reactive<AdvancedFilters>({
  contract_number: '', product_id: '', salesperson_id: '', follower_id: '', order_source: '', delivery_method: '',
})

const canDelete = computed(() => authStore.hasPermission('production_tasks.delete_productiontask'))
const deletingId = ref('')
const hoveredProductElement = ref<HTMLElement>()
const hoveredProductDetails = ref('')
const rowTooltipVisible = ref(false)
function showRowProducts(row: ProductionTask, _column: unknown, cell: HTMLElement) {
  hoveredProductElement.value = cell.parentElement?.querySelector<HTMLElement>('.production-product-cell') || undefined
  hoveredProductDetails.value = productSpecifications(row.products)
  rowTooltipVisible.value = Boolean(hoveredProductElement.value) && row.products.length > 0
}
const canEdit = computed(() => authStore.hasPermission('production_tasks.change_productiontask'))
const canCreate = computed(() => authStore.hasPermission('production_tasks.add_productiontask'))
const canConfirm = computed(() => authStore.hasPermission('production_tasks.confirm_productiontask'))
const canSchedule = computed(() => (
  authStore.hasPermission('production_scheduling.view_productionschedule')
  && authStore.hasPermission('production_scheduling.add_productionschedule')
))
const lifecycleTitle = computed(() => lifecycleAction.value === 'cancel' ? '取消订单' : '结束订单')
const lifecycleReasonLabel = computed(() => lifecycleAction.value === 'cancel' ? '取消原因' : '结束原因')
const lifecycleConfirmText = computed(() => lifecycleAction.value === 'cancel' ? '确认取消' : '确认结束')
const advancedFilterCount = computed(() => [
  advancedFilters.contract_number, advancedFilters.product_id,
  advancedFilters.salesperson_id, advancedFilters.follower_id, advancedFilters.order_source,
  advancedFilters.delivery_method, deliveryRange.value.length ? 'range' : '',
].filter(Boolean).length)
const statusOptions = [
  { key: 'all', label: '全部' },
  { key: 'draft', label: '草稿' },
  { key: 'pending', label: '待 PMC 确认' },
  { key: 'ready', label: '已接单' },
  { key: 'production', label: '生产中' },
  { key: 'completed', label: '已完成' },
]

function apiError(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (error.response.status === 403) return data.error?.message || data.detail || '当前账号没有执行此操作的权限。'
  return data.error?.message || data.detail || '生产任务单加载失败。'
}

function statusQuery(): Pick<ProductionTaskQuery, 'status' | 'delivery_method'> {
  if (activeStatusTab.value === 'pending') return { status: 'PENDING_VALIDATION' }
  if (activeStatusTab.value === 'draft') return { status: 'DRAFT' }
  if (activeStatusTab.value === 'ready') return { status: 'READY' }
  if (activeStatusTab.value === 'production') return { status: 'IN_PRODUCTION' }
  if (activeStatusTab.value === 'completed') return { status: 'COMPLETED' }
  if (activeStatusTab.value === 'paused') return { status: 'PAUSED' }
  if (activeStatusTab.value === 'cancelled') return { status: 'CANCELLED' }
  return {}
}

function buildQuery(): ProductionTaskQuery {
  const query: ProductionTaskQuery = {
    page: page.value, page_size: pageSize.value, ordering: '-created_at',
    search: searchText.value.trim() || undefined, ...statusQuery(),
  }
  if (advancedFilters.contract_number.trim()) query.contract_number = advancedFilters.contract_number.trim()
  if (advancedFilters.product_id) query.product_id = advancedFilters.product_id
  if (advancedFilters.salesperson_id) query.salesperson_id = advancedFilters.salesperson_id
  if (advancedFilters.follower_id) query.follower_id = advancedFilters.follower_id
  if (advancedFilters.order_source) query.order_source = advancedFilters.order_source
  if (advancedFilters.delivery_method) query.delivery_method = advancedFilters.delivery_method
  if (deliveryRange.value.length === 2) {
    query.delivery_from = deliveryRange.value[0]
    query.delivery_to = deliveryRange.value[1]
  }
  if (quantityPending.value) query.quantity_pending = true
  if (dueSoon.value) query.due_within_days = 30
  return query
}

async function loadRows(): Promise<boolean> {
  const requestId = ++latestRowsRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchProductionTasks(buildQuery())
    if (requestId !== latestRowsRequest) return true
    rows.value = result.data
    total.value = result.meta.total
    if (page.value > result.meta.total_pages && result.meta.total_pages > 0) {
      page.value = result.meta.total_pages
      return loadRows()
    }
    return true
  } catch (error) {
    if (requestId !== latestRowsRequest) return true
    rows.value = []
    total.value = 0
    errorMessage.value = apiError(error)
    return false
  } finally {
    if (requestId === latestRowsRequest) loading.value = false
  }
}

async function loadFilterOptions(): Promise<boolean> {
  const requestId = ++latestOptionsRequest
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const result = await fetchProductionTaskFilterOptions()
    if (requestId === latestOptionsRequest) options.value = result
    return true
  } catch (error) {
    if (requestId !== latestOptionsRequest) return true
    optionsError.value = apiError(error)
    return false
  } finally {
    if (requestId === latestOptionsRequest) optionsLoading.value = false
  }
}

function resetListFilters() { searchText.value = ''; activeStatusTab.value = 'all'; quantityPending.value = false; dueSoon.value = false; resetAdvancedFilters(); search() }
function search() { page.value = 1; void loadRows() }
function handleSearchEnter(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  search()
}
function applyStatusTab(key: StatusTabKey) { activeStatusTab.value = key; page.value = 1; void loadRows() }
function applyAdvancedFilters() { advancedVisible.value = false; search() }
function resetAdvancedFilters() {
  Object.assign(advancedFilters, { contract_number: '', product_id: '', salesperson_id: '', follower_id: '', order_source: '', delivery_method: '' })
  deliveryRange.value = []
}

function statusClass(status: ProductionTaskStatus) {
  if (status === 'DRAFT' || status === 'PAUSED') return 'neutral'
  if (status === 'PENDING_VALIDATION') return 'warning'
  if (status === 'COMPLETED' || status === 'READY') return 'success'
  if (status === 'CANCELLED') return 'danger'
  if (status === 'IN_PRODUCTION') return 'info'
  return 'brand'
}
function progressStatusClass(status?: string) {
  if (!status || status === 'NOT_CREATED' || status === 'NOT_STARTED' || status.endsWith('_DRAFT')) return 'neutral'
  if (status === 'REQUEST_CANCELLED') return 'danger'
  if (status === 'VERIFIED' || status === 'ORDER_COMPLETED') return 'success'
  if (status === 'ORDER_PURCHASING') return 'info'
  return 'warning'
}
function openCreate() { void router.push({ name: 'production-task-create' }) }
function openTask(row: ProductionTask, edit = false) { void router.push({ name: edit ? 'production-task-edit' : 'production-task-detail', params: { taskId: row.id } }) }
function canChangeLifecycle(row: ProductionTask) { return canEdit.value && row.status !== 'CANCELLED' && row.status !== 'COMPLETED' }
function handleRowAction(command: string, row: ProductionTask) {
  if (command === 'delete') { void deleteTask(row); return }
  if (command === 'view') { openTask(row); return }
  if (command === 'edit') { openTask(row, true); return }
  if (command === 'confirm') { void openPmcConfirm(row); return }
  if (command === 'schedule') {
    if (!canSchedule.value || !isTaskReadyForScheduling(row)) return
    scheduleTarget.value = row
    scheduleDialogVisible.value = true
    return
  }
  if ((command !== 'cancel' && command !== 'finish') || !canChangeLifecycle(row)) return
  if (command === 'finish' && row.sales_order_id) {
    void prepareLinkedFinish(row)
    return
  }
  lifecycleAction.value = command
  lifecycleTarget.value = row
  lifecycleReason.value = ''
  lifecycleDialogVisible.value = true
}
async function deleteTask(row: ProductionTask) {
  if (!canDelete.value || row.status !== 'CANCELLED' || deletingId.value) return
  deletingId.value = row.id
  try {
    const current = await fetchProductionTask(row.id)
    if (current.data.status !== 'CANCELLED') { ElMessage.warning('任务状态已变化，请刷新后重试。'); return }
    if (!current.etag) { ElMessage.error('未取得任务版本，请刷新后重试。'); return }
    await ElMessageBox.confirm(`确定删除任务单 ${row.task_number}？删除后不可恢复。存在 BOM、排产、采购等下游记录时将无法删除。`, '删除生产任务单', { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' })
    await deleteProductionTask(row.id, current.etag)
    ElMessage.success('生产任务单已删除。')
    await loadRows()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    if (error instanceof AxiosError && [409, 412, 428].includes(error.response?.status || 0)) ElMessage.error(`${apiError(error)} 请刷新列表后重试。`)
    else ElMessage.error(apiError(error))
  } finally { deletingId.value = '' }
}
async function prepareLinkedFinish(row: ProductionTask) {
  lifecycleLoading.value = true
  try {
    const current = await fetchProductionTask(row.id)
    lifecycleAction.value = 'finish'
    lifecycleTarget.value = current.data
    lifecycleReason.value = ''
    completionActualQuantity.value = current.data.total_quantity
    completionGoodQuantity.value = current.data.total_quantity
    completionBatches.value = (current.data.run_batches || []).filter((item) => item.status !== 'CANCELLED').map((item) => ({
      batch_number: item.batch_number,
      planned_quantity: item.planned_quantity,
      actual_quantity: item.actual_quantity === '0.0000' ? item.planned_quantity : item.actual_quantity,
      good_quantity: item.good_quantity === '0.0000' ? item.planned_quantity : item.good_quantity,
      note: item.note,
    }))
    lifecycleDialogVisible.value = true
  } catch (error) { ElMessage.error(apiError(error)) } finally { lifecycleLoading.value = false }
}
async function openPmcConfirm(row: ProductionTask) {
  if (row.status !== 'PENDING_VALIDATION' || !canConfirm.value) return
  await router.push({ name: 'production-task-detail', params: { taskId: row.id }, query: { pmc: 'confirm' } })
}

async function handleScheduleSaved() {
  await loadRows()
}
async function confirmLifecycleAction() {
  const row = lifecycleTarget.value
  const reason = lifecycleReason.value.trim()
  if (!row || lifecycleLoading.value) return
  const linkedFinish = lifecycleAction.value === 'finish' && Boolean(row.sales_order_id)
  if (!reason && (!linkedFinish || Number(completionGoodQuantity.value) < Number(row.total_quantity))) {
    ElMessage.warning(linkedFinish ? '合格数量不足时必须填写异常完结原因（责任提示：PMC）。' : `请填写${lifecycleReasonLabel.value}。`)
    return
  }
  lifecycleLoading.value = true
  try {
    const current = await fetchProductionTask(row.id)
    if (lifecycleAction.value === 'cancel') await cancelProductionTask(row.id, reason, current.etag)
    else if (current.data.sales_order_id) {
      await finishProductionTask(row.id, reason, current.etag, {
        actual_quantity: completionActualQuantity.value,
        actual_good_quantity: completionGoodQuantity.value,
        run_batches: completionBatches.value.map((item) => ({ ...item, status: 'COMPLETED' as const })),
      })
    } else await finishProductionTask(row.id, reason, current.etag)
    lifecycleDialogVisible.value = false
    lifecycleTarget.value = null
    lifecycleReason.value = ''
    ElMessage.success(`${lifecycleTitle.value}成功。`)
    await loadRows()
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    lifecycleLoading.value = false
  }
}
async function exportList() {
  if (!total.value) { ElMessage.warning('当前筛选没有可导出的生产任务单。'); return }
  exportLoading.value = true
  try {
    const result = await exportProductionTasks(buildQuery())
    const url = URL.createObjectURL(result.blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `生产任务单_${new Date().toISOString().slice(0, 10)}.csv`
    anchor.click()
    URL.revokeObjectURL(url)
    const count = result.count ?? total.value
    ElMessage.success(`已导出当前筛选的全部 ${count} 条生产任务单。`)
  } catch (error) {
    let message = apiError(error)
    if (error instanceof AxiosError && error.response?.data instanceof Blob) {
      try {
        const payload = JSON.parse(await error.response.data.text()) as { error?: { message?: string }; detail?: string }
        message = payload.error?.message || payload.detail || message
      } catch { /* 非 JSON 下载错误沿用通用提示。 */ }
    }
    ElMessage.error(message)
  } finally {
    exportLoading.value = false
  }
}

onMounted(() => { void loadRows(); void loadFilterOptions() })
onBeforeUnmount(() => {
  ++latestRowsRequest
  ++latestOptionsRequest
})
</script>

<template>
  <section class="production-list-page erp-glass-list" aria-label="生产任务单列表">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="page-heading erp-list-heading">
      <div class="page-heading__title"><h1>生产任务单</h1><span>{{ total }} 条</span></div>
    </header>

    <ElAlert v-if="optionsError" type="warning" :title="`筛选选项加载失败：${optionsError}`" :closable="false"><ElButton class="erp-button-motion" size="small" @click="loadFilterOptions">重试选项</ElButton></ElAlert>

    <section class="list-filters erp-list-filters" aria-label="生产任务单筛选">
        <ElInput v-model="searchText" class="search-filter" clearable placeholder="搜索任务 / 订单 / 客户 / 产品" @keydown.enter="handleSearchEnter" @clear="search">
          <template #suffix><button type="button" class="production-search-button erp-list-search-button" aria-label="搜索生产任务单" @click="search"><img :src="searchIcon" alt="" aria-hidden="true" /></button></template>
        </ElInput>
        <ElSelect v-model="activeStatusTab" aria-label="状态筛选" @change="() => applyStatusTab(activeStatusTab)">
          <ElOption v-for="item in statusOptions" :key="item.key" :label="`状态：${item.label}`" :value="item.key" />
          <ElOption label="状态：已暂停" value="paused" />
          <ElOption label="状态：已取消" value="cancelled" />
        </ElSelect>
        <ElSelect v-model="advancedFilters.salesperson_id" :loading="optionsLoading" clearable placeholder="业务员：全部" @change="search">
          <ElOption v-for="item in options?.salespeople || []" :key="item.id" :label="item.display_name" :value="item.id" />
        </ElSelect>
        <ElSelect v-model="dueSoon" aria-label="交期筛选" @change="search">
          <ElOption label="交期：全部" :value="false" />
          <ElOption label="交期：近 30 天" :value="true" />
        </ElSelect>
        <ElPopover v-model:visible="advancedVisible" placement="bottom-start" :width="760" trigger="click" popper-class="production-filter-popper erp-list-filter-popover">
          <template #reference><ElButton class="erp-button-motion" :class="{ 'is-filter-active': advancedFilterCount > 0 }">更多筛选<template v-if="advancedFilterCount">（{{ advancedFilterCount }}）</template><ElIcon><ArrowDown /></ElIcon></ElButton></template>
          <section v-if="advancedVisible" class="advanced-filter-panel" v-loading="optionsLoading">
            <header><strong>更多筛选</strong><span>按业务字段组合筛选生产任务单</span></header>
            <div class="advanced-filter-grid">
              <label><span>合同编号</span><ElInput v-model="advancedFilters.contract_number" clearable placeholder="输入合同编号" /></label>
              <label><span>产品</span><ElSelect v-model="advancedFilters.product_id" filterable clearable placeholder="全部产品"><ElOption v-for="item in options?.products || []" :key="item.id" :label="`${item.product_code} · ${item.item_number} · ${item.product_name}`" :value="item.id" /></ElSelect></label>
              <label><span>业务员</span><ElSelect v-model="advancedFilters.salesperson_id" filterable clearable placeholder="全部业务员"><ElOption v-for="item in options?.salespeople || []" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></label>
              <label><span>跟单员</span><ElSelect v-model="advancedFilters.follower_id" filterable clearable placeholder="全部跟单员"><ElOption v-for="item in options?.employees || []" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></label>
              <label class="delivery-range"><span>交期范围</span><ElDatePicker v-model="deliveryRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" /></label>
              <label><span>订单来源</span><ElSelect v-model="advancedFilters.order_source" clearable placeholder="全部来源"><ElOption v-for="item in options?.order_sources || []" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></label>
              <label><span>交货方式</span><ElSelect v-model="advancedFilters.delivery_method" clearable placeholder="全部方式"><ElOption v-for="item in options?.delivery_methods || []" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></label>
              <label><span>数量校验</span><ElCheckbox v-model="quantityPending">仅看数量待确认</ElCheckbox></label>
            </div>
            <footer><ElButton class="erp-button-motion" @click="resetAdvancedFilters">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="applyAdvancedFilters">应用筛选</ElButton></footer>
          </section>
        </ElPopover>
      <div class="list-filter-actions erp-list-filter-actions"><ElButton class="erp-button-motion" @click="resetListFilters">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="search">应用筛选</ElButton></div>
    </section>

    </section>
    <section class="table-card erp-list-data">
      <div class="list-filter-actions erp-list-toolbar">
        <ElButton class="erp-button-motion" :icon="Upload" :loading="exportLoading" :disabled="!total" @click="exportList">导出</ElButton>
        <ElButton class="erp-button-motion" v-if="canCreate" type="primary" :icon="Plus" @click="openCreate">新建生产任务单</ElButton>
      </div>
      <ElAlert v-if="errorMessage" class="list-error" type="error" :title="errorMessage" show-icon :closable="false"><ElButton class="erp-button-motion" size="small" @click="loadRows">重试</ElButton></ElAlert>
      <div v-else class="erp-list-table-frame"><ElTable height="100%" v-loading="loading" :data="rows" row-key="id" empty-text="暂无生产任务单" @cell-mouse-enter="showRowProducts" @cell-mouse-leave="rowTooltipVisible = false">
        <ElTableColumn
          prop="task_number"
          label="任务编号"
          min-width="110"
        ><template #default="{ row }"><button class="link-button" type="button" @click="openTask(row)">{{ row.task_number }}</button></template></ElTableColumn>
        <ElTableColumn label="销售订单" min-width="128" show-overflow-tooltip><template #default="{ row }">{{ row.source_sales_order_number || '手动创建' }}</template></ElTableColumn>
        <ElTableColumn label="产品" class-name="production-product-cell" min-width="178"><template #default="{ row }"><ElTooltip trigger="focus" :content="productSpecifications(row.products)" placement="right" popper-class="production-product-tooltip"><div class="product-summary" tabindex="0"><div v-for="(label, index) in productLabels(row.products)" :key="index">{{ label }}</div><span v-if="!row.products.length">未添加产品</span></div></ElTooltip></template></ElTableColumn>
        <ElTableColumn label="规格" min-width="150"><template #default="{ row }"><div class="product-summary"><div v-for="product in row.products" :key="product.id">{{ product.specification_display || product.customer_specification || product.specification || '—' }}</div><span v-if="!row.products.length">—</span></div></template></ElTableColumn>
        <ElTableColumn label="材质" min-width="110"><template #default="{ row }"><div class="product-summary"><div v-for="product in row.products" :key="product.id">{{ product.material || '—' }}</div><span v-if="!row.products.length">—</span></div></template></ElTableColumn>
        <ElTableColumn label="颜色" min-width="110"><template #default="{ row }"><div class="product-summary"><div v-for="product in row.products" :key="product.id">{{ product.customer_color || product.color_name || product.color_code || '—' }}</div><span v-if="!row.products.length">—</span></div></template></ElTableColumn>
        <ElTableColumn label="数量" min-width="88" show-overflow-tooltip align="right"><template #default="{ row }">{{ quantityWithUnits(row.products) }}</template></ElTableColumn>
        <ElTableColumn label="人民币金额合计" min-width="125" show-overflow-tooltip align="right"><template #default="{ row }">¥ {{ localAmountTotal(row.products) }}</template></ElTableColumn>
        <ElTableColumn prop="delivery_date" label="交期" min-width="102"><template #default="{ row }">{{ row.delivery_date || '—' }}</template></ElTableColumn>
        <ElTableColumn label="业务员" min-width="78" show-overflow-tooltip><template #default="{ row }">{{ row.salesperson.display_name }}</template></ElTableColumn>
        <ElTableColumn label="跟单员" min-width="78" show-overflow-tooltip><template #default="{ row }">{{ row.followers.map((item: { display_name: string }) => item.display_name).join('、') || '待选择' }}</template></ElTableColumn>
        <ElTableColumn label="状态" width="110" align="center"><template #default="{ row }"><ElTag class="status-tag erp-list-tag" :class="`erp-list-tag--${statusClass(row.status)}`" effect="dark">{{ row.status_display }}</ElTag></template></ElTableColumn>
        <ElTableColumn label="BOM状态" width="120" align="center"><template #default="{ row }"><ElTag class="status-tag erp-list-tag progress-status-tag" :class="`erp-list-tag--${progressStatusClass(row.bom_status)}`" effect="dark">{{ row.bom_status_display || '未建立' }}</ElTag></template></ElTableColumn>
        <ElTableColumn label="采购状态" width="130" align="center"><template #default="{ row }"><ElTag class="status-tag erp-list-tag progress-status-tag" :class="`erp-list-tag--${progressStatusClass(row.purchase_status)}`" effect="dark">{{ row.purchase_status_display || '未发起' }}</ElTag></template></ElTableColumn>
        <ElTableColumn label="操作" width="80" align="center" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <ElDropdown :persistent="false" trigger="click" placement="bottom-end" @command="handleRowAction($event, row)">
                <button class="row-action-trigger" type="button" :aria-label="`打开生产任务 ${row.task_number} 操作菜单`">
                  <span class="row-action-dots" aria-hidden="true"><i /><i /><i /></span>
                </button>
                <template #dropdown>
                  <ElDropdownMenu>
                    <ElDropdownItem command="view">查看</ElDropdownItem>
                    <ElDropdownItem v-if="canEdit && row.status !== 'CANCELLED' && row.status !== 'COMPLETED'" command="edit">编辑</ElDropdownItem>
                    <ElDropdownItem v-if="row.status === 'PENDING_VALIDATION' && canConfirm" command="confirm">PMC 确认</ElDropdownItem>
                    <ElDropdownItem v-if="canSchedule && isTaskReadyForScheduling(row)" command="schedule">计划排产</ElDropdownItem>
                    <ElDropdownItem v-if="canChangeLifecycle(row) && row.status === 'IN_PRODUCTION'" command="finish">完结生产</ElDropdownItem>
                    <ElDropdownItem v-if="canChangeLifecycle(row)" command="cancel" class="danger-menu-item" divided>取消订单</ElDropdownItem>
                    <ElDropdownItem v-if="canDelete" command="delete" :disabled="row.status !== 'CANCELLED' || !!deletingId" class="danger-menu-item">删除</ElDropdownItem>
                  </ElDropdownMenu>
                </template>
              </ElDropdown>
            </div>
          </template>
        </ElTableColumn>
      </ElTable></div>
      <ElTooltip virtual-triggering :virtual-ref="hoveredProductElement" :visible="rowTooltipVisible" :content="hoveredProductDetails" popper-class="production-product-tooltip" placement="right" />
      <footer class="table-footer erp-list-footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" :pager-count="5" layout="sizes, prev, pager, next" @current-change="loadRows" @size-change="search" /></footer>
    </section>



    <ProductionTaskScheduleDialog v-model="scheduleDialogVisible" :task="scheduleTarget" @saved="handleScheduleSaved" />

    <ElDialog v-model="lifecycleDialogVisible" :title="lifecycleTitle" width="480px" :close-on-click-modal="!lifecycleLoading" :close-on-press-escape="!lifecycleLoading">
      <div class="lifecycle-dialog__summary">任务单：<strong>{{ lifecycleTarget?.task_number }}</strong></div>
      <ElForm label-position="top" @submit.prevent>
        <template v-if="lifecycleAction === 'finish' && lifecycleTarget?.sales_order_id">
          <div class="finish-quantities"><ElFormItem label="实际生产数量"><ElInput v-model="completionActualQuantity" /></ElFormItem><ElFormItem label="合格数量"><ElInput v-model="completionGoodQuantity" /></ElFormItem></div>
          <ElTable :data="completionBatches" size="small" border><ElTableColumn prop="batch_number" label="生产批次" /><ElTableColumn label="实际数量"><template #default="{ row }"><ElInput v-model="row.actual_quantity" /></template></ElTableColumn><ElTableColumn label="合格数量"><template #default="{ row }"><ElInput v-model="row.good_quantity" /></template></ElTableColumn></ElTable>
        </template>
        <ElFormItem :label="lifecycleAction === 'finish' && lifecycleTarget?.sales_order_id ? '异常完结原因（正常足量可不填）' : lifecycleReasonLabel" :required="!(lifecycleAction === 'finish' && lifecycleTarget?.sales_order_id)">
          <ElInput v-model="lifecycleReason" type="textarea" :rows="3" maxlength="500" show-word-limit :placeholder="lifecycleAction === 'finish' && lifecycleTarget?.sales_order_id ? '短交或提前关闭时必须填写' : `请填写${lifecycleReasonLabel}`" />
        </ElFormItem>
      </ElForm>
      <template #footer><ElButton :disabled="lifecycleLoading" @click="lifecycleDialogVisible = false">暂不操作</ElButton><ElButton :type="lifecycleAction === 'cancel' ? 'danger' : 'primary'" :loading="lifecycleLoading" @click="confirmLifecycleAction">{{ lifecycleConfirmText }}</ElButton></template>
    </ElDialog>
  </section>
</template>

<style scoped lang="scss">
.page-heading__title { display: flex; align-items: baseline; gap: 14px; }
.page-heading__title > span { color: var(--erp-color-text-secondary); font-size: 13px; }
.list-filters .search-filter { width: min(100%, 250px); flex: none; }
.list-filters > :deep(.el-select) { width: 142px; flex: none; }
.product-summary:focus-visible, .row-action-trigger:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.product-summary { padding: 0; line-height: 20px; }
.product-summary > div { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.link-button { max-width: 100%; overflow: hidden; padding: 0; border: 0; color: var(--erp-table-text); background: transparent; font: inherit; font-weight: 500; text-align: left; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.link-button:hover { text-decoration: underline; }
.row-actions { display: flex; justify-content: center; align-items: center; }
.row-action-trigger { display: grid; width: 32px; height: 32px; place-items: center; padding: 0; border: 0; border-radius: var(--erp-radius-control); color: var(--erp-table-text); background: transparent; cursor: pointer; }
.row-action-trigger:hover { background: var(--erp-table-hover); }
.row-action-dots { display: inline-flex; align-items: center; gap: 3px; }
.row-action-dots i { width: 3px; height: 3px; border-radius: 50%; background: currentColor; }
.lifecycle-dialog__summary { margin-bottom: 18px; color: var(--erp-color-text-regular); font-size: 14px; }
.lifecycle-dialog__summary strong { color: var(--erp-color-text-primary); }
.finish-quantities { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.pmc-confirm-note { margin: 0 0 18px; padding: 10px 12px; color: var(--erp-color-text-secondary); background: var(--erp-color-subtle); font-size: 13px; line-height: 20px; }
.pmc-confirm-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.pmc-confirm-grid label { min-width: 0; display: flex; flex-direction: column; gap: 7px; color: var(--erp-color-text-regular); font-size: 13px; }
.pmc-confirm-grid :deep(.el-date-editor) { width: 100%; height: 32px; }
</style>


<style lang="scss">
.production-product-tooltip { white-space: pre-line; max-width: min(560px, calc(100vw - 32px)); }
.production-filter-popper .advanced-filter-panel { padding: 0; }
.advanced-filter-panel { padding: 18px; }
.advanced-filter-panel header { display: flex; flex-direction: column; gap: 3px; margin-bottom: 16px; }
.advanced-filter-panel header strong { color: var(--erp-color-text-primary); font-size: 16px; }
.advanced-filter-panel header span { color: var(--erp-color-text-secondary); font-size: 12px; }
.advanced-filter-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px 12px; }
.advanced-filter-grid label { min-width: 0; display: flex; flex-direction: column; gap: 6px; color: var(--erp-color-text-primary); font-size: 12px; }
.advanced-filter-grid .delivery-range { grid-column: span 2; }
.advanced-filter-grid .el-input, .advanced-filter-grid .el-select, .advanced-filter-grid .el-date-editor { width: 100%; }
.advanced-filter-panel footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--erp-color-border); }
.danger-menu-item { color: var(--erp-color-danger) !important; }
</style>
