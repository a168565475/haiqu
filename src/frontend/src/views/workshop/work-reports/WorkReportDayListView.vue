<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchReportingContext, fetchWorkReports, fetchWorkReportTasks } from '@/api/workshopReporting'
import { useAuthStore } from '@/stores/auth'
import type { ReportingContext, ReportingOption, WorkReport, WorkReportLine, WorkReportTask } from '@/types/workshopReporting'
import { formatWageMoney } from '@/utils/wageMoney'
import WorkReportTaskSelectDialog from './WorkReportTaskSelectDialog.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const context = ref<ReportingContext | null>(null)
const selectedTask = ref<WorkReportTask | null>(null)
const taskSelectorVisible = ref(false)
const selectionSubmitting = ref(false)
const selectionError = ref('')
const reports = ref<WorkReport[]>([])
const selectedWorkshopId = ref('')
const selectedReportId = ref('')
const reportPage = ref(1)
const reportPageSize = ref(20)
const reportTotal = ref(0)
const contextLoading = ref(false)
const reportLoading = ref(false)
const errorMessage = ref('')

const scheduleProductId = computed(() => typeof route.query.schedule_product_id === 'string' ? route.query.schedule_product_id : '')
const productionTaskId = computed(() => typeof route.query.production_task_id === 'string' ? route.query.production_task_id : '')
const routeWorkshopId = computed(() => typeof route.query.workshop_id === 'string' ? route.query.workshop_id : '')
const routeCraftId = computed(() => typeof route.query.craft_id === 'string' ? route.query.craft_id : '')
const invalidScopeQuery = computed(() => ['schedule_product_id', 'production_task_id', 'workshop_id', 'craft_id'].some(key => {
  const value = route.query[key]
  return value !== undefined && (typeof value !== 'string' || !value.trim())
}) || Boolean(scheduleProductId.value && productionTaskId.value)
  || Boolean(!scheduleProductId.value && !productionTaskId.value && routeWorkshopId.value))
const scheduleProduct = computed(() => context.value?.schedule_product || null)
const hasSelection = computed(() => Boolean((scheduleProduct.value || selectedTask.value) && selectedWorkshop.value))
const canCreate = computed(() => Boolean(scheduleProduct.value) && (auth.user?.is_superuser || (
  auth.hasPermission('workshop_reporting.add_workreport')
  && auth.hasPermission('workshop_reporting.view_workreport')
)))
const canEdit = computed(() => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.change_workreport'))

const workshops = computed<ReportingOption[]>(() => {
  if (productionTaskId.value) return selectedTask.value?.workshops || []
  const source = context.value?.workshops || []
  if (!scheduleProductId.value) return source
  const linkedIds = new Set((context.value?.crafts || []).map(item => item.workshop_id).filter(Boolean))
  return linkedIds.size ? source.filter(item => linkedIds.has(item.id)) : source
})
const selectedWorkshop = computed(() => workshops.value.find(item => item.id === selectedWorkshopId.value) || null)
const selectedCraftId = computed(() => {
  const crafts = (context.value?.crafts || []).filter(item => item.workshop_id === selectedWorkshopId.value)
  if (crafts.some(item => item.id === routeCraftId.value)) return routeCraftId.value
  return crafts.length === 1 ? crafts[0]!.id : ''
})
const selectedReport = computed(() => reports.value.find(item => item.id === selectedReportId.value) || null)
const newReportQuery = computed(() => ({
  ...(scheduleProductId.value ? { schedule_product_id: scheduleProductId.value } : {}),
  ...(selectedWorkshopId.value ? { workshop_id: selectedWorkshopId.value } : {}),
  ...(selectedCraftId.value ? { craft_id: selectedCraftId.value } : {}),
}))

let contextRequest = 0
let reportRequest = 0

function apiError(error: unknown) {
  return (error as { response?: { data?: { error?: { message?: string } } } })
    ?.response?.data?.error?.message || '报工记录加载失败，请重试。'
}

function quantityText(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed)
    ? parsed.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
    : '—'
}

function progressPercent(line: WorkReportLine) {
  const required = Number(line.required_quantity)
  const reported = Number(line.cumulative_quantity)
  if (!Number.isFinite(required) || required <= 0 || !Number.isFinite(reported)) return 0
  return Math.min(100, Math.max(0, Math.round((reported / required) * 100)))
}

function progressBarPercent(line: WorkReportLine) {
  return Math.min(100, progressPercent(line))
}

function progressText(line: WorkReportLine) {
  if (line.required_quantity === null) return '待配置'
  return `已报 ${quantityText(line.cumulative_quantity)} / 总需 ${quantityText(line.required_quantity)}`
}

function reportTimeText(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '—'
    : date.toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    })
}

function reportRowClassName({ row }: { row: WorkReport }) {
  return row.id === selectedReportId.value ? 'is-current-work-report' : ''
}

function clearReports(resetTotal = true) {
  reportRequest += 1
  reportLoading.value = false
  selectedReportId.value = ''
  reports.value = []
  if (resetTotal) reportTotal.value = 0
}

async function loadReports(resetSelection = false) {
  const previousReportId = resetSelection ? '' : selectedReportId.value
  clearReports(false)
  const requestId = reportRequest
  if (!hasSelection.value) return
  reportLoading.value = true
  try {
    const result = await fetchWorkReports({
      page: reportPage.value,
      page_size: reportPageSize.value,
      schedule_product_id: scheduleProductId.value || undefined,
      production_task_id: productionTaskId.value || undefined,
      workshop_id: selectedWorkshopId.value,
      craft_id: (productionTaskId.value ? routeCraftId.value : selectedCraftId.value) || undefined,
    })
    if (requestId !== reportRequest) return
    reports.value = result.data
    reportTotal.value = result.meta.total
    selectedReportId.value = result.data.some(item => item.id === previousReportId)
      ? previousReportId : result.data[0]?.id || ''
    errorMessage.value = ''
  } catch (error) {
    if (requestId !== reportRequest) return
    reports.value = []
    selectedReportId.value = ''
    reportTotal.value = 0
    errorMessage.value = apiError(error)
  } finally {
    if (requestId === reportRequest) reportLoading.value = false
  }
}

async function initialize() {
  const requestId = ++contextRequest
  clearReports()
  contextLoading.value = false
  context.value = null
  selectedTask.value = null
  selectedWorkshopId.value = ''
  errorMessage.value = ''
  taskSelectorVisible.value = false
  if (invalidScopeQuery.value) {
    errorMessage.value = '报工记录地址中的任务或车间参数无效，请重新选择。'
    return
  }
  if (!scheduleProductId.value && !productionTaskId.value) {
    openTaskSelector()
    return
  }
  contextLoading.value = true
  try {
    if (productionTaskId.value) {
      const taskId = productionTaskId.value
      const result = await fetchWorkReportTasks({ production_task_id: taskId, page: 1, page_size: 20 })
      if (requestId !== contextRequest) return
      selectedTask.value = result.data.find(item => item.id === taskId) || null
      if (!selectedTask.value) {
        errorMessage.value = '生产任务单不存在或无查看权限，请重新选择。'
        return
      }
      if (!routeWorkshopId.value) {
        openTaskSelector()
        return
      }
    } else {
      const result = await fetchReportingContext(scheduleProductId.value, 'work_report')
      if (requestId !== contextRequest) return
      if (result.schedule_product?.id !== scheduleProductId.value) {
        errorMessage.value = '排产产品不存在或无查看权限，请重新选择。'
        return
      }
      context.value = result
    }
    const requestedWorkshop = workshops.value.find(item => item.id === routeWorkshopId.value)
    if (routeWorkshopId.value && !requestedWorkshop) {
      errorMessage.value = '该车间不属于当前任务或无查看权限，请重新选择。'
      return
    }
    selectedWorkshopId.value = requestedWorkshop?.id || workshops.value[0]?.id || ''
    reportPage.value = 1
    await loadReports(true)
  } catch (error) {
    if (requestId !== contextRequest) return
    context.value = null
    selectedTask.value = null
    reports.value = []
    errorMessage.value = apiError(error)
  } finally {
    if (requestId === contextRequest) contextLoading.value = false
  }
}

function openTaskSelector() {
  selectionError.value = ''
  taskSelectorVisible.value = true
}

function scopeNavigationFailed() {
  selectionError.value = '报工记录页面打开失败，请重试。'
  if (!taskSelectorVisible.value) {
    selectedWorkshopId.value = routeWorkshopId.value
    errorMessage.value = selectionError.value
  }
}

async function selectTaskScope(value: { productionTaskId: string; workshopId: string }) {
  if (selectionSubmitting.value) return
  if (productionTaskId.value === value.productionTaskId && routeWorkshopId.value === value.workshopId) {
    taskSelectorVisible.value = false
    await initialize()
    return
  }
  selectionSubmitting.value = true
  selectionError.value = ''
  try {
    const failure = await router.replace({ name: 'work-report-days', query: {
      production_task_id: value.productionTaskId,
      workshop_id: value.workshopId,
    } })
    if (failure) {
      scopeNavigationFailed()
      return
    }
    taskSelectorVisible.value = false
  } catch {
    scopeNavigationFailed()
  } finally {
    selectionSubmitting.value = false
  }
}

function selectReport(row: WorkReport) {
  selectedReportId.value = row.id
}

function resetWorkshop() {
  if (productionTaskId.value) {
    selectedWorkshopId.value = routeWorkshopId.value
    void loadReports(true)
    return
  }
  selectedWorkshopId.value = workshops.value.find(item => item.id === routeWorkshopId.value)?.id || workshops.value[0]?.id || ''
  changeWorkshop()
}
function changeWorkshop() {
  if (productionTaskId.value) {
    if (!selectedWorkshop.value) return
    clearReports()
    void selectTaskScope({ productionTaskId: productionTaskId.value, workshopId: selectedWorkshopId.value })
    return
  }
  reportPage.value = 1
  void loadReports(true)
}

function changeReportPage() {
  void loadReports(true)
}

function refresh() {
  void loadReports(false)
}

watch([scheduleProductId, productionTaskId, routeWorkshopId, routeCraftId, invalidScopeQuery], () => { void initialize() }, { immediate: true })
onBeforeUnmount(() => { contextRequest += 1; reportRequest += 1 })
</script>

<template>
  <section class="wr-page wr-report-records-page erp-glass-list" data-testid="work-report-days">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="wr-report-records__heading erp-list-heading">
      <h1>报工记录</h1>
      <ElButton data-testid="work-report-select-task" class="erp-button-motion" @click="openTaskSelector">{{ selectedTask || scheduleProduct ? '切换任务' : '选择任务' }}</ElButton>
      <ElButton
        v-if="canCreate"
        class="erp-button-motion wr-report-records__create"
        type="primary"
        :icon="Plus"
        @click="router.push({ name: 'work-report-new', query: newReportQuery })"
      >新增报工</ElButton>
    </header>

    <section v-if="scheduleProduct || selectedTask" class="wr-report-context erp-list-filters" aria-label="当前生产任务信息">
      <div class="wr-report-context__items">
        <span><b>生产任务：</b>{{ selectedTask?.task_number || scheduleProduct?.task_number || '—' }}</span>
        <i aria-hidden="true" />
        <span><b>生产订单：</b>{{ selectedTask?.order_number || scheduleProduct?.order_number || '—' }}</span>
        <i aria-hidden="true" />
        <label class="wr-report-context__workshop">
          <b>车间：</b>
          <ElSelect
            v-model="selectedWorkshopId"
            :loading="contextLoading"
            placeholder="选择车间"
            @change="changeWorkshop"
          >
            <ElOption v-for="item in workshops" :key="item.id" :label="item.name" :value="item.id" />
          </ElSelect>
        </label>
        <i aria-hidden="true" />
        <span><b>产品：</b>{{ selectedTask ? '全部产品' : scheduleProduct?.product_name || '—' }}</span>
        <template v-if="!selectedTask">
        <i aria-hidden="true" />
        <span><b>产品编号：</b>{{ scheduleProduct?.product_number || '—' }}</span>
        <i aria-hidden="true" />
        <span><b>规格：</b>{{ scheduleProduct?.product_specification || '—' }}</span>
        <i aria-hidden="true" />
        <span><b>颜色：</b>{{ scheduleProduct?.product_color || '—' }}</span>
        <i aria-hidden="true" />
        <span><b>订单数量：</b>{{ quantityText(scheduleProduct?.order_quantity) }} {{ scheduleProduct?.unit_name || '' }}</span>
        </template>
      </div>
      <ElButton class="erp-button-motion wr-report-context__refresh" :icon="Refresh" :loading="reportLoading" @click="refresh">刷新</ElButton>
      <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="resetWorkshop">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="changeWorkshop">应用筛选</ElButton></div>
    </section>

    </section>
    <ElAlert v-if="errorMessage" class="wr-report-records__error" type="error" :closable="false" show-icon :title="errorMessage">
      <template #default><ElButton link type="primary" @click="initialize">重新加载</ElButton></template>
    </ElAlert>

    <ElEmpty v-else-if="!hasSelection" v-loading="contextLoading" description="请先选择生产任务单和车间" />

    <div v-else class="wr-report-records__layout">
      <section class="wr-report-days-panel wr-report-list-panel erp-list-data" aria-label="每次报工记录列表">
        <header class="wr-report-days-panel__header erp-list-toolbar">
          <h2>报工列表</h2>
          <span>当前车间：{{ selectedWorkshop?.name || '—' }}</span>
        </header>
        <div class="wr-report-days-panel__table wr-report-list-panel__table erp-list-table-frame" v-loading="reportLoading">
          <ElTable
            :data="reports"
            height="100%"
            border
            row-key="id"
            :row-class-name="reportRowClassName"
            highlight-current-row
            @row-click="selectReport"
          >
            <ElTableColumn label="报工单" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">
                <b class="wr-report-number" :title="row.report_number">{{ row.report_number }}</b>
              </template>
            </ElTableColumn>
            <ElTableColumn label="报工时间" min-width="160" show-overflow-tooltip>
              <template #default="{ row }"><span class="wr-report-time">{{ reportTimeText(row.created_at) }}</span></template>
            </ElTableColumn>
            <ElTableColumn prop="line_count" label="工序数" width="76" align="center" />
            <ElTableColumn label="金额" width="90" align="right"><template #default="{ row }"><strong>{{ formatWageMoney(row.total_amount) }}</strong></template></ElTableColumn>
            <template #empty><ElEmpty :image-size="56" description="当前车间暂无报工记录" /></template>
          </ElTable>
        </div>
        <footer class="wr-report-days-panel__pagination erp-list-footer">
          <span>共 {{ reportTotal }} 次报工</span>
          <ElPagination
            v-model:current-page="reportPage"
            v-model:page-size="reportPageSize"
            :page-sizes="[20, 50, 100]"
            :total="reportTotal"
            :pager-count="5"
            layout="sizes, prev, pager, next"
            @current-change="changeReportPage"
            @size-change="reportPage = 1; changeReportPage()"
          />
        </footer>
      </section>

      <section class="wr-report-details-panel erp-list-data" aria-label="所选报工明细">
        <header class="wr-report-details-panel__header erp-list-toolbar">
          <div>
            <h2>报工详情<template v-if="selectedWorkshop"> · {{ selectedWorkshop.name }}</template></h2>
            <span v-if="selectedReport">{{ selectedReport.line_count }} 条工序</span>
          </div>
          <div>本次金额 <strong>{{ formatWageMoney(selectedReport?.total_amount) }}</strong></div>
        </header>

        <div class="wr-report-details-panel__body" v-loading="reportLoading">
          <article v-if="selectedReport" :key="selectedReport.id" class="wr-report-group">
            <header class="wr-report-group__header">
              <div>
                <b>{{ selectedReport.report_number }}</b>
                <i aria-hidden="true" />
                <span>生产日期：{{ selectedReport.production_date }}</span>
                <i aria-hidden="true" />
                <span>报工时间：{{ reportTimeText(selectedReport.created_at) }}</span>
                <i aria-hidden="true" />
                <span>录入人：{{ selectedReport.recorder || '—' }}</span>
                <i aria-hidden="true" />
                <span>产品：{{ selectedReport.product.name }}（{{ selectedReport.product.number }}）</span>
                <i aria-hidden="true" />
                <span>工艺：{{ selectedReport.scope_craft?.name || '—' }}</span>
                <i aria-hidden="true" />
                <span>本次金额：<strong>{{ formatWageMoney(selectedReport.total_amount) }}</strong></span>
              </div>
              <ElButton
                v-if="canEdit"
                link
                type="primary"
                @click="router.push({ name: 'work-report-edit', params: { reportId: selectedReport.id }, ...(productionTaskId ? { query: { production_task_id: productionTaskId } } : {}) })"
              >编辑</ElButton>
            </header>
            <div class="erp-list-table-frame"><ElTable :data="selectedReport.lines" border>
              <ElTableColumn prop="employee_name" label="员工" width="76" />
              <ElTableColumn label="生产线" width="80" align="center"><template #default="{ row }">{{ row.production_line ? `${row.production_line}线` : '—' }}</template></ElTableColumn>
              <ElTableColumn prop="operation_name" label="工序" width="96" show-overflow-tooltip />
              <ElTableColumn prop="display_name" label="名称 / 部位" min-width="160" show-overflow-tooltip />
              <ElTableColumn label="订单数量" width="82" align="right"><template #default="{ row }">{{ quantityText(row.order_quantity_snapshot) }}</template></ElTableColumn>
              <ElTableColumn label="需完成次数" width="98" align="right"><template #default="{ row }">{{ quantityText(row.required_quantity) }}</template></ElTableColumn>
              <ElTableColumn label="本次完成" width="88" align="right"><template #default="{ row }">{{ quantityText(row.quantity) }}</template></ElTableColumn>
              <ElTableColumn label="累计进度" width="220">
                <template #default="{ row }">
                  <div v-if="row.required_quantity !== null" class="wr-report-progress">
                    <span>{{ progressText(row) }}</span>
                    <ElProgress :percentage="progressBarPercent(row)" :stroke-width="5" :show-text="false" />
                    <b>{{ progressPercent(row) }}%</b>
                  </div>
                  <span v-else class="wr-report-progress--unset">待配置</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="工价" width="80" align="right"><template #default="{ row }">{{ formatWageMoney(row.unit_price) }}</template></ElTableColumn>
              <ElTableColumn label="金额" width="88" align="right"><template #default="{ row }"><strong>{{ formatWageMoney(row.amount) }}</strong></template></ElTableColumn>
            </ElTable></div>
          </article>

          <ElEmpty
            v-if="!reportLoading && !selectedReport"
            :image-size="72"
            description="请选择一条报工记录查看明细"
          />
        </div>
      </section>
    </div>
    <WorkReportTaskSelectDialog v-model="taskSelectorVisible" :initial-task="selectedTask" :initial-workshop-id="selectedWorkshopId" :submitting="selectionSubmitting" :selection-error="selectionError" @select="selectTaskScope" />
  </section>
</template>

<style lang="scss">@use '@/styles/workshopReporting.scss';</style>

<style scoped lang="scss">
.wr-report-number { font-size: 12px; font-weight: 500; white-space: nowrap; }
.wr-report-time { color: var(--erp-color-text-secondary); font-size: 12px; white-space: nowrap; }

.wr-report-list-panel {
  .erp-list-footer { flex-wrap: wrap; gap: 8px; }
  :deep(.el-table__header .cell) { white-space: nowrap; }
  :deep(.el-table__body tr.is-current-work-report > td.el-table__cell) { background: var(--erp-table-selected); }
  :deep(.el-table__body tr.is-current-work-report > td.el-table__cell:first-child) { box-shadow: 3px 0 0 var(--erp-color-brand) inset; }
}
</style>
