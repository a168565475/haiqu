<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchReportingContext, fetchWorkReportProductOptions, fetchWorkReports, fetchWorkReportTaskOptions, fetchWorkReportWorkshops } from '@/api/workshopReporting'
import { useAuthStore } from '@/stores/auth'
import type { ReportingContext, ReportingOption, WorkReport, WorkReportFilters, WorkReportLine, WorkReportProductOption, WorkReportTaskOption } from '@/types/workshopReporting'
import { formatWageMoney } from '@/utils/wageMoney'
import { workReportWorkshopChoices } from '@/utils/workReportWorkshopChoices'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const context = ref<ReportingContext | null>(null)
const workshops = ref<ReportingOption[]>([])
const selectedWorkshopKey = ref('')
const selectedTasks = ref<WorkReportTaskOption[]>([])
const selectedProducts = ref<WorkReportProductOption[]>([])
const foundTasks = ref<WorkReportTaskOption[]>([])
const foundProducts = ref<WorkReportProductOption[]>([])
const optionsLoading = ref({ tasks: false, products: false })
const optionsError = ref('')
const activeFilters = ref<WorkReportFilters | null>(null)
const reports = ref<WorkReport[]>([])
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
const routePlanCategory = computed(() => {
  const value = route.query.plan_category
  return value === 'CUTTING' || value === 'SEWING' ? value : ''
})
const invalidScopeQuery = computed(() => ['schedule_product_id', 'production_task_id', 'workshop_id', 'craft_id'].some(key => {
  const value = route.query[key]
  return value !== undefined && (typeof value !== 'string' || !value.trim())
}) || Boolean(scheduleProductId.value && productionTaskId.value)
  || (route.query.plan_category !== undefined && !routePlanCategory.value))
const scheduleProduct = computed(() => context.value?.schedule_product || null)
const canCreate = computed(() => Boolean(activeFilters.value?.schedule_product_id) && (auth.user?.is_superuser || (
  auth.hasPermission('workshop_reporting.add_workreport')
  && auth.hasPermission('workshop_reporting.view_workreport')
)))
const canEdit = computed(() => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.change_workreport'))

const workshopChoices = computed(() => workReportWorkshopChoices(workshops.value))
const selectedWorkshop = computed(() => workshopChoices.value.find(item => item.key === selectedWorkshopKey.value))
const fixedWorkshop = computed(() => {
  const option = workshopChoices.value[0]
  const roles = auth.user?.effective_access?.roles
  return !auth.user?.is_superuser && workshopChoices.value.length === 1 && (
    (option?.name === '金工车间' && roles?.some(role => role.code === 'METAL_DIRECTOR'))
    || (option?.name === '装配车间' && roles?.some(role => role.code === 'ASSEMBLY_DIRECTOR'))
  )
})
const draftWorkshop = computed(() => ({
  workshop_id: selectedWorkshop.value?.workshopId,
  plan_category: selectedWorkshop.value?.planCategory,
}))
const activeWorkshopName = computed(() => workshopChoices.value.find(item =>
  item.workshopId === activeFilters.value?.workshop_id && item.planCategory === activeFilters.value?.plan_category,
)?.name || workshops.value.find(item => item.id === activeFilters.value?.workshop_id)?.name)
const taskOptions = computed(() => withSelected(foundTasks.value, selectedTasks.value))
const productOptions = computed(() => withSelected(foundProducts.value, selectedProducts.value))
const selectedReport = computed(() => reports.value.find(item => item.id === selectedReportId.value) || null)
const showCuttingLength = computed(() => selectedReport.value?.workshop.name === '金工车间')
const newReportQuery = computed(() => ({
  schedule_product_id: activeFilters.value?.schedule_product_id,
  workshop_id: activeFilters.value?.workshop_id,
  craft_id: activeFilters.value?.craft_id,
  plan_category: activeFilters.value?.plan_category,
}))

let contextRequest = 0
let reportRequest = 0
const optionRequests = { tasks: 0, products: 0 }

function withSelected<T extends { id: string }>(matches: T[], selected: T[]) {
  return [...new Map([...selected, ...matches].map(item => [item.id, item])).values()]
}

function productLabel(product: WorkReportProductOption) {
  const code = product.code || (product.number ? `编号 ${product.number}` : '无编码')
  return `${code} · ${product.name} · ${product.task_number}`
}

function apiError(error: unknown, fallback = '报工记录加载失败，请重试。') {
  return (error as { response?: { data?: { error?: { message?: string } } } })
    ?.response?.data?.error?.message || fallback
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
  if (!activeFilters.value) return
  reportLoading.value = true
  try {
    const result = await fetchWorkReports({
      page: reportPage.value,
      page_size: reportPageSize.value,
      ...activeFilters.value,
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

type OptionKind = 'tasks' | 'products'

function clearOptions(kind: OptionKind) {
  optionRequests[kind] += 1
  optionsLoading.value[kind] = false
  if (kind === 'tasks') foundTasks.value = []
  else foundProducts.value = []
  optionsError.value = ''
}

async function searchOptions(kind: OptionKind, query = '') {
  const requestId = ++optionRequests[kind]
  optionsLoading.value[kind] = true
  optionsError.value = ''
  const params = { ...draftWorkshop.value, q: query.trim() || undefined }
  try {
    if (kind === 'tasks') {
      const options = await fetchWorkReportTaskOptions(params)
      if (requestId === optionRequests.tasks) foundTasks.value = options
    } else {
      const options = await fetchWorkReportProductOptions({
        ...params, production_task_ids: selectedTasks.value.map(item => item.id),
      })
      if (requestId === optionRequests.products) foundProducts.value = options
    }
  } catch (error) {
    if (requestId !== optionRequests[kind]) return
    clearOptions(kind)
    optionsError.value = apiError(error, '筛选选项加载失败，请重试。')
  } finally {
    if (requestId === optionRequests[kind]) optionsLoading.value[kind] = false
  }
}

function changeTasks() {
  if (selectedTasks.value.length) {
    const ids = new Set(selectedTasks.value.map(item => item.id))
    selectedProducts.value = selectedProducts.value.filter(item => ids.has(item.production_task_id))
  }
  clearOptions('products')
}

function defaultWorkshopKey() {
  return (workshopChoices.value.length === 2 && workshopChoices.value[0]?.workshopId === workshopChoices.value[1]?.workshopId
    ? workshopChoices.value.find(item => item.planCategory === 'SEWING')
    : workshopChoices.value[0])?.key || ''
}

async function initialize() {
  const requestId = ++contextRequest
  clearReports()
  clearOptions('tasks')
  clearOptions('products')
  context.value = null
  activeFilters.value = null
  workshops.value = []
  selectedWorkshopKey.value = ''
  selectedTasks.value = []
  selectedProducts.value = []
  errorMessage.value = ''
  contextLoading.value = true
  try {
    const [workshopsResult, contextResult] = await Promise.allSettled([
      fetchWorkReportWorkshops(),
      scheduleProductId.value && !invalidScopeQuery.value
        ? fetchReportingContext(scheduleProductId.value, 'work_report') : Promise.resolve(null),
    ])
    if (requestId !== contextRequest) return
    if (workshopsResult.status === 'rejected') throw workshopsResult.reason
    workshops.value = workshopsResult.value
    selectedWorkshopKey.value = defaultWorkshopKey()
    if (invalidScopeQuery.value) {
      errorMessage.value = '报工记录地址中的任务或车间参数无效，请重新筛选。'
      return
    }
    if (contextResult.status === 'rejected') throw contextResult.reason
    const sourceContext = contextResult.value
    context.value = sourceContext
    if (scheduleProductId.value && scheduleProduct.value?.id !== scheduleProductId.value) {
      errorMessage.value = '排产产品不存在或无查看权限，请重新筛选。'
      return
    }
    const sourceCrafts = sourceContext?.crafts || []
    const requestedCraft = sourceCrafts.find(item => item.id === routeCraftId.value)
    const workshopId = routeWorkshopId.value || requestedCraft?.workshop_id || sourceCrafts[0]?.workshop_id
    const category = routePlanCategory.value || requestedCraft?.plan_category
    if (workshopId || routePlanCategory.value) {
      const choice = workshopChoices.value.find(item => (!workshopId || item.workshopId === workshopId)
        && (routePlanCategory.value ? item.planCategory === routePlanCategory.value
          : !['CUTTING', 'SEWING'].includes(category || '') || item.planCategory === category))
      if (!choice || (sourceCrafts.length && !sourceCrafts.some(item => item.workshop_id === choice.workshopId))) {
        errorMessage.value = '该车间或计划分类不在当前查看范围，请重新筛选。'
        return
      }
      selectedWorkshopKey.value = choice.key
    }
    if (!selectedWorkshop.value) return
    const source = scheduleProduct.value
    if (source) {
      selectedTasks.value = [{ id: source.production_task_id, task_number: source.task_number }]
      selectedProducts.value = [{
        id: source.product_line_id, production_task_id: source.production_task_id, task_number: source.task_number,
        code: source.product_code || '', name: source.product_name, number: source.product_number,
      }]
    } else if (productionTaskId.value) {
      const tasks = await fetchWorkReportTaskOptions({
        ...(routeWorkshopId.value || routePlanCategory.value ? draftWorkshop.value : {}),
        production_task_ids: [productionTaskId.value],
      })
      if (requestId !== contextRequest) return
      const task = tasks.find(item => item.id === productionTaskId.value)
      if (!task) {
        errorMessage.value = '生产任务单不存在或无查看权限，请重新筛选。'
        return
      }
      selectedTasks.value = [task]
    }
    const matchingCrafts = sourceCrafts.filter(item => item.workshop_id === draftWorkshop.value.workshop_id
      && (!draftWorkshop.value.plan_category || item.plan_category === draftWorkshop.value.plan_category))
    activeFilters.value = {
      ...draftWorkshop.value,
      production_task_id: productionTaskId.value || undefined,
      schedule_product_id: source?.id,
      craft_id: (matchingCrafts.find(item => item.id === routeCraftId.value)
        || (matchingCrafts.length === 1 ? matchingCrafts[0] : undefined))?.id
        || (!source ? routeCraftId.value || undefined : undefined),
    }
    reportPage.value = 1
    await loadReports(true)
  } catch (error) {
    if (requestId === contextRequest) errorMessage.value = apiError(error)
  } finally {
    if (requestId === contextRequest) contextLoading.value = false
  }
}

function changeWorkshop() {
  clearOptions('tasks')
  clearOptions('products')
}

function applyFilters() {
  if (!selectedWorkshop.value) return
  const filters: WorkReportFilters = {
    ...draftWorkshop.value,
    production_task_ids: selectedTasks.value.map(item => item.id),
    product_line_ids: selectedProducts.value.map(item => item.id),
  }
  const source = scheduleProduct.value
  if (source && selectedTasks.value.length === 1 && selectedTasks.value[0]?.id === source.production_task_id
    && selectedProducts.value.length === 1 && selectedProducts.value[0]?.id === source.product_line_id) {
    const crafts = (context.value?.crafts || []).filter(item => item.workshop_id === filters.workshop_id
      && (!filters.plan_category || item.plan_category === filters.plan_category))
    if (crafts.length) {
      filters.schedule_product_id = source.id
      filters.craft_id = (crafts.find(item => item.id === routeCraftId.value) || (crafts.length === 1 ? crafts[0] : undefined))?.id
    }
  }
  activeFilters.value = filters
  reportPage.value = 1
  void loadReports(true)
}

function resetFilters() {
  selectedTasks.value = []
  selectedProducts.value = []
  selectedWorkshopKey.value = defaultWorkshopKey()
  changeWorkshop()
  applyFilters()
}

function selectReport(row: WorkReport) {
  selectedReportId.value = row.id
}

function editReport(report: WorkReport) {
  const filters = activeFilters.value
  const taskId = filters?.production_task_id || (filters?.production_task_ids?.length === 1 ? report.production_task.id : undefined)
  const category = filters?.plan_category
  void router.push({
    name: 'work-report-edit', params: { reportId: report.id },
    ...(taskId || category ? { query: {
      ...(taskId ? { production_task_id: taskId } : {}), ...(category ? { plan_category: category } : {}),
    } } : {}),
  })
}

function changeReportPage() {
  void loadReports(true)
}

function refresh() {
  if (activeFilters.value) void loadReports(false)
  else void initialize()
}

watch([scheduleProductId, productionTaskId, routeWorkshopId, routeCraftId, routePlanCategory, invalidScopeQuery], initialize, { immediate: true })
onBeforeUnmount(() => {
  contextRequest += 1
  reportRequest += 1
  optionRequests.tasks += 1
  optionRequests.products += 1
})
</script>

<template>
  <section class="wr-page wr-report-records-page erp-glass-list" data-testid="work-report-days">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="wr-report-records__heading erp-list-heading">
      <h1>报工记录</h1>
      <ElButton
        v-if="canCreate"
        class="erp-button-motion wr-report-records__create"
        type="primary"
        :icon="Plus"
        @click="router.push({ name: 'work-report-new', query: newReportQuery })"
      >新增报工</ElButton>
    </header>

    <section class="wr-report-context erp-list-filters" aria-label="报工记录筛选">
      <div class="wr-report-context__items">
        <label class="wr-report-context__field">
          <b>生产任务单</b>
          <ElSelect
            v-model="selectedTasks" value-key="id" multiple filterable remote clearable collapse-tags collapse-tags-tooltip
            data-testid="work-report-task-filter" aria-label="生产任务单" placeholder="搜索任务单号"
            :disabled="contextLoading || !selectedWorkshop" :loading="optionsLoading.tasks"
            :remote-method="(query: string) => searchOptions('tasks', query)"
            @visible-change="(visible: boolean) => visible && searchOptions('tasks')" @change="changeTasks"
          >
            <ElOption v-for="item in taskOptions" :key="item.id" :label="item.task_number" :value="item" />
          </ElSelect>
        </label>
        <label class="wr-report-context__field wr-report-context__product">
          <b>订单产品</b>
          <ElSelect
            v-model="selectedProducts" value-key="id" multiple filterable remote clearable collapse-tags collapse-tags-tooltip
            data-testid="work-report-product-filter" aria-label="订单产品" placeholder="搜索产品编码或名称"
            :disabled="contextLoading || !selectedWorkshop" :loading="optionsLoading.products"
            :remote-method="(query: string) => searchOptions('products', query)"
            @visible-change="(visible: boolean) => visible && searchOptions('products')"
          >
            <ElOption v-for="item in productOptions" :key="item.id" :label="productLabel(item)" :value="item" />
          </ElSelect>
        </label>
        <label class="wr-report-context__field wr-report-context__workshop">
          <b>车间</b>
          <ElSelect
            v-if="workshopChoices.length && !fixedWorkshop"
            v-model="selectedWorkshopKey"
            data-testid="work-report-workshop-filter" aria-label="车间"
            :disabled="contextLoading"
            placeholder="选择车间"
            @change="changeWorkshop"
          >
            <ElOption v-for="item in workshopChoices" :key="item.key" :label="item.name" :value="item.key" />
          </ElSelect>
          <span v-else>{{ selectedWorkshop?.name || '—' }}</span>
        </label>
      </div>
      <div class="erp-list-filter-actions">
        <ElButton class="erp-button-motion" :icon="Refresh" :loading="reportLoading" :disabled="contextLoading" @click="refresh">刷新</ElButton>
        <ElButton class="erp-button-motion" :disabled="contextLoading || !selectedWorkshop" @click="resetFilters">重置</ElButton>
        <ElButton class="erp-button-motion" type="primary" :disabled="contextLoading || !selectedWorkshop" @click="applyFilters">应用筛选</ElButton>
      </div>
    </section>

    </section>
    <ElAlert v-if="optionsError" type="warning" :closable="false" show-icon :title="optionsError" />
    <ElAlert v-if="errorMessage" class="wr-report-records__error" type="error" :closable="false" show-icon :title="errorMessage">
      <template #default><ElButton link type="primary" @click="refresh">重新加载</ElButton></template>
    </ElAlert>

    <ElEmpty v-else-if="!activeFilters" v-loading="contextLoading" :description="contextLoading ? '正在读取报工记录' : '当前账号没有可查看的车间报工'" />

    <div v-else class="wr-report-records__layout">
      <section class="wr-report-days-panel wr-report-list-panel erp-list-data" aria-label="每次报工记录列表">
        <header class="wr-report-days-panel__header erp-list-toolbar">
          <h2>报工列表</h2>
          <span>当前车间：{{ activeWorkshopName || '—' }}</span>
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
            <ElTableColumn label="生产任务单号" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">
                <b class="wr-report-number" :title="row.production_task.task_number">{{ row.production_task.task_number }}</b>
              </template>
            </ElTableColumn>
            <ElTableColumn label="生产日期" min-width="160" show-overflow-tooltip>
              <template #default="{ row }"><span class="wr-report-date">{{ row.production_date }}</span></template>
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
            <h2>报工详情<template v-if="activeWorkshopName"> · {{ activeWorkshopName }}</template></h2>
            <span v-if="selectedReport">{{ selectedReport.line_count }} 条工序</span>
          </div>
          <div>本次金额 <strong>{{ formatWageMoney(selectedReport?.total_amount) }}</strong></div>
        </header>

        <div class="wr-report-details-panel__body" v-loading="reportLoading">
          <article v-if="selectedReport" :key="selectedReport.id" class="wr-report-group">
            <header class="wr-report-group__header">
              <div>
                <template v-if="selectedReport.product.code"><b>{{ selectedReport.product.code }}</b><i aria-hidden="true" /></template>
                <span>生产日期：{{ selectedReport.production_date }}</span>
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
                @click="editReport(selectedReport)"
              >编辑</ElButton>
            </header>
            <div class="erp-list-table-frame"><ElTable :data="selectedReport.lines" border>
              <ElTableColumn prop="employee_name" label="员工" width="76" />
              <ElTableColumn label="生产线" width="80" align="center"><template #default="{ row }">{{ row.production_line ? `${row.production_line}线` : '—' }}</template></ElTableColumn>
              <ElTableColumn prop="operation_name" label="工序" width="96" show-overflow-tooltip />
              <ElTableColumn prop="display_name" label="名称 / 部位" min-width="160" show-overflow-tooltip />
              <ElTableColumn v-if="showCuttingLength" label="切割长度" width="92" align="right">
                <template #default="{ row }">{{ row.cutting_length_mm == null ? '—' : `${row.cutting_length_mm} mm` }}</template>
              </ElTableColumn>
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
  </section>
</template>

<style lang="scss">@use '@/styles/workshopReporting.scss';</style>

<style scoped lang="scss">
.wr-report-number { font-size: 12px; font-weight: 500; white-space: nowrap; }
.wr-report-date { color: var(--erp-color-text-secondary); font-size: 12px; white-space: nowrap; }

.wr-report-list-panel {
  .erp-list-footer { flex-wrap: wrap; gap: 8px; }
  :deep(.el-table__header .cell) { white-space: nowrap; }
  :deep(.el-table__body tr.is-current-work-report > td.el-table__cell) { background: var(--erp-table-selected); }
  :deep(.el-table__body tr.is-current-work-report > td.el-table__cell:first-child) { box-shadow: 3px 0 0 var(--erp-color-brand) inset; }
}
</style>
