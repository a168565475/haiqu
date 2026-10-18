<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, ref, watch } from 'vue'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchReportingContext, fetchWorkReportDay, fetchWorkReportDays } from '@/api/workshopReporting'
import { useAuthStore } from '@/stores/auth'
import type { ReportingContext, ReportingOption, WorkReport, WorkReportDay, WorkReportLine } from '@/types/workshopReporting'
import { formatWageMoney } from '@/utils/wageMoney'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const context = ref<ReportingContext | null>(null)
const days = ref<WorkReportDay[]>([])
const reports = ref<WorkReport[]>([])
const selectedWorkshopId = ref('')
const selectedDate = ref('')
const dayPage = ref(1)
const dayPageSize = ref(20)
const dayTotal = ref(0)
const reportTotal = ref(0)
const contextLoading = ref(false)
const dayLoading = ref(false)
const detailLoading = ref(false)
const errorMessage = ref('')

const scheduleProductId = computed(() => String(route.query.schedule_product_id || ''))
const routeWorkshopId = computed(() => String(route.query.workshop_id || ''))
const routeCraftId = computed(() => String(route.query.craft_id || ''))
const scheduleProduct = computed(() => context.value?.schedule_product || null)
const canCreate = computed(() => auth.user?.is_superuser || (
  auth.hasPermission('workshop_reporting.add_workreport')
  && auth.hasPermission('workshop_reporting.view_workreport')
))
const canEdit = computed(() => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.change_workreport'))

const workshops = computed<ReportingOption[]>(() => {
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
const selectedDay = computed(() => days.value.find(item => item.production_date === selectedDate.value) || null)
const newReportQuery = computed(() => ({
  ...(scheduleProductId.value ? { schedule_product_id: scheduleProductId.value } : {}),
  ...(selectedWorkshopId.value ? { workshop_id: selectedWorkshopId.value } : {}),
  ...(selectedCraftId.value ? { craft_id: selectedCraftId.value } : {}),
}))

let contextRequest = 0
let dayRequest = 0
let detailRequest = 0

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

function weekdayText(value: string) {
  const date = new Date(`${value}T00:00:00`)
  return Number.isNaN(date.getTime()) ? '—' : `周${'日一二三四五六'[date.getDay()]}`
}

function timeText(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '—'
    : date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function dayRowClassName({ row }: { row: WorkReportDay }) {
  return row.production_date === selectedDate.value ? 'is-current-report-day' : ''
}

async function loadReports(retryCount = 0) {
  const requestId = ++detailRequest
  const requestedDate = selectedDate.value
  const requestedWorkshopId = selectedWorkshopId.value
  const requestedScheduleProductId = scheduleProductId.value
  if (!selectedDate.value || !selectedWorkshopId.value) {
    reports.value = []
    reportTotal.value = 0
    return
  }
  detailLoading.value = true
  try {
    const firstPage = await fetchWorkReportDay(requestedDate, {
      page: 1,
      page_size: 100,
      schedule_product_id: requestedScheduleProductId || undefined,
      workshop_id: requestedWorkshopId,
    })
    if (
      requestId !== detailRequest
      || requestedDate !== selectedDate.value
      || requestedWorkshopId !== selectedWorkshopId.value
      || requestedScheduleProductId !== scheduleProductId.value
    ) return
    const reportsById = new Map(firstPage.data.map(report => [report.id, report]))
    let totalPages = firstPage.meta.total_pages
    for (let page = 2; page <= totalPages; page += 1) {
      const nextPage = await fetchWorkReportDay(requestedDate, {
        page,
        page_size: 100,
        schedule_product_id: requestedScheduleProductId || undefined,
        workshop_id: requestedWorkshopId,
      })
      if (
        requestId !== detailRequest
        || requestedDate !== selectedDate.value
        || requestedWorkshopId !== selectedWorkshopId.value
        || requestedScheduleProductId !== scheduleProductId.value
      ) return
      nextPage.data.forEach(report => reportsById.set(report.id, report))
      totalPages = Math.max(totalPages, nextPage.meta.total_pages)
    }
    if (reportsById.size !== firstPage.meta.total && retryCount < 1) {
      await loadReports(retryCount + 1)
      return
    }
    reports.value = [...reportsById.values()]
    reportTotal.value = firstPage.meta.total
    errorMessage.value = ''
  } catch (error) {
    if (requestId !== detailRequest) return
    reports.value = []
    reportTotal.value = 0
    errorMessage.value = apiError(error)
  } finally {
    if (requestId === detailRequest) detailLoading.value = false
  }
}

async function loadDays(resetSelection = false) {
  const requestId = ++dayRequest
  detailRequest += 1
  detailLoading.value = false
  reports.value = []
  reportTotal.value = 0
  if (!selectedWorkshopId.value) {
    days.value = []
    reports.value = []
    selectedDate.value = ''
    dayTotal.value = 0
    reportTotal.value = 0
    return
  }
  dayLoading.value = true
  try {
    const result = await fetchWorkReportDays({
      page: dayPage.value,
      page_size: dayPageSize.value,
      schedule_product_id: scheduleProductId.value || undefined,
      workshop_id: selectedWorkshopId.value,
    })
    if (requestId !== dayRequest) return
    days.value = result.data
    dayTotal.value = result.meta.total
    const selectedStillVisible = result.data.some(item => item.production_date === selectedDate.value)
    if (resetSelection || !selectedStillVisible) selectedDate.value = result.data[0]?.production_date || ''
    errorMessage.value = ''
    await loadReports()
  } catch (error) {
    if (requestId !== dayRequest) return
    days.value = []
    reports.value = []
    selectedDate.value = ''
    dayTotal.value = 0
    reportTotal.value = 0
    errorMessage.value = apiError(error)
  } finally {
    if (requestId === dayRequest) dayLoading.value = false
  }
}

async function initialize() {
  if (!scheduleProductId.value) {
    if (auth.user?.is_superuser || auth.hasPermission('production_scheduling.view_productionschedule')) {
      await router.replace({ name: 'workshop-metalworking-plan' })
    } else {
      errorMessage.value = '报工记录需要从内部计划选择具体产品进入，请联系管理员补充内部计划查看权限。'
    }
    return
  }
  const requestId = ++contextRequest
  contextLoading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchReportingContext(scheduleProductId.value || undefined, 'work_report')
    if (requestId !== contextRequest) return
    context.value = result
    const requestedWorkshop = workshops.value.find(item => item.id === routeWorkshopId.value)
    selectedWorkshopId.value = requestedWorkshop?.id || workshops.value[0]?.id || ''
    dayPage.value = 1
    await loadDays(true)
  } catch (error) {
    if (requestId !== contextRequest) return
    context.value = null
    days.value = []
    reports.value = []
    errorMessage.value = apiError(error)
  } finally {
    if (requestId === contextRequest) contextLoading.value = false
  }
}

function selectDay(row: WorkReportDay) {
  if (row.production_date === selectedDate.value) return
  selectedDate.value = row.production_date
  void loadReports()
}

function resetWorkshop() {
  selectedWorkshopId.value = workshops.value.find(item => item.id === routeWorkshopId.value)?.id || workshops.value[0]?.id || ''
  changeWorkshop()
}
function changeWorkshop() {
  dayPage.value = 1
  void loadDays(true)
}

function changeDayPage() {
  void loadDays(true)
}

function refresh() {
  void loadDays(false)
}

watch([scheduleProductId, routeWorkshopId], () => { void initialize() })
onMounted(() => { void initialize() })
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

    <section class="wr-report-context erp-list-filters" aria-label="当前生产任务信息">
      <div class="wr-report-context__items">
        <span><b>生产任务：</b>{{ scheduleProduct?.task_number || '—' }}</span>
        <i aria-hidden="true" />
        <span><b>生产订单：</b>{{ scheduleProduct?.order_number || '—' }}</span>
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
        <span><b>产品：</b>{{ scheduleProduct?.product_name || '—' }}</span>
        <i aria-hidden="true" />
        <span><b>产品编号：</b>{{ scheduleProduct?.product_number || '—' }}</span>
        <i aria-hidden="true" />
        <span><b>规格：</b>{{ scheduleProduct?.product_specification || '—' }}</span>
        <i aria-hidden="true" />
        <span><b>颜色：</b>{{ scheduleProduct?.product_color || '—' }}</span>
        <i aria-hidden="true" />
        <span><b>订单数量：</b>{{ quantityText(scheduleProduct?.order_quantity) }} {{ scheduleProduct?.unit_name || '' }}</span>
      </div>
      <ElButton class="erp-button-motion wr-report-context__refresh" :icon="Refresh" :loading="dayLoading || detailLoading" @click="refresh">刷新</ElButton>
      <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="resetWorkshop">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="changeWorkshop">应用筛选</ElButton></div>
    </section>

    </section>
    <ElAlert v-if="errorMessage" class="wr-report-records__error" type="error" :closable="false" show-icon :title="errorMessage">
      <template #default><ElButton link type="primary" @click="initialize">重新加载</ElButton></template>
    </ElAlert>

    <div v-else class="wr-report-records__layout">
      <section class="wr-report-days-panel erp-list-data" aria-label="报工日期列表">
        <header class="wr-report-days-panel__header erp-list-toolbar">
          <h2>报工日期</h2>
          <span>当前车间：{{ selectedWorkshop?.name || '—' }}</span>
        </header>
        <div class="wr-report-days-panel__table erp-list-table-frame" v-loading="dayLoading">
          <ElTable
            :data="days"
            height="100%"
            border
            :row-class-name="dayRowClassName"
            highlight-current-row
            @row-click="selectDay"
          >
            <ElTableColumn prop="production_date" label="日期" width="112" />
            <ElTableColumn label="星期" width="60"><template #default="{ row }">{{ weekdayText(row.production_date) }}</template></ElTableColumn>
            <ElTableColumn prop="report_count" label="保存次数" width="78" align="center" />
            <ElTableColumn prop="line_count" label="工序条数" width="82" align="center" />
            <ElTableColumn label="当日工费" min-width="100" align="right"><template #default="{ row }"><strong>{{ formatWageMoney(row.total_amount) }}</strong></template></ElTableColumn>
            <template #empty><ElEmpty :image-size="56" description="当前车间暂无报工记录" /></template>
          </ElTable>
        </div>
        <footer class="wr-report-days-panel__pagination erp-list-footer">
          <span>共 {{ dayTotal }} 条</span>
          <ElPagination
            v-model:current-page="dayPage"
            v-model:page-size="dayPageSize"
            :page-sizes="[20, 50, 100]"
            :total="dayTotal"
            layout="sizes, prev, pager, next"
            @current-change="changeDayPage"
            @size-change="dayPage = 1; changeDayPage()"
          />
        </footer>
      </section>

      <section class="wr-report-details-panel erp-list-data" aria-label="所选日期报工明细">
        <header class="wr-report-details-panel__header erp-list-toolbar">
          <div>
            <h2>{{ selectedDate || '暂无日期' }}<template v-if="selectedWorkshop"> · {{ selectedWorkshop.name }}</template></h2>
            <span>{{ selectedDay?.report_count || 0 }} 次保存 · {{ selectedDay?.line_count || 0 }} 条工序</span>
          </div>
          <div>当日工费 <strong>{{ formatWageMoney(selectedDay?.total_amount || '0') }}</strong></div>
        </header>

        <div class="wr-report-details-panel__body" v-loading="detailLoading">
          <article v-for="report in reports" :key="report.id" class="wr-report-group">
            <header class="wr-report-group__header">
              <div>
                <b>{{ report.report_number }}</b>
                <i aria-hidden="true" />
                <span>录入人：{{ report.recorder || '—' }}</span>
                <i aria-hidden="true" />
                <span>保存时间：{{ timeText(report.updated_at) }}</span>
                <i aria-hidden="true" />
                <span>小计：<strong>{{ formatWageMoney(report.total_amount) }}</strong></span>
              </div>
              <ElButton
                v-if="canEdit"
                link
                type="primary"
                @click="router.push({ name: 'work-report-edit', params: { reportId: report.id } })"
              >编辑</ElButton>
            </header>
            <div class="erp-list-table-frame"><ElTable :data="report.lines" border>
              <ElTableColumn prop="employee_name" label="员工" width="76" />
              <ElTableColumn label="生产线" width="64" align="center"><template #default="{ row }">{{ row.production_line ? `${row.production_line}线` : '—' }}</template></ElTableColumn>
              <ElTableColumn prop="operation_name" label="工序" width="96" show-overflow-tooltip />
              <ElTableColumn prop="display_name" label="名称 / 部位" min-width="160" show-overflow-tooltip />
              <ElTableColumn label="订单数量" width="82" align="right"><template #default="{ row }">{{ quantityText(row.order_quantity_snapshot) }}</template></ElTableColumn>
              <ElTableColumn label="需完成次数" width="98" align="right"><template #default="{ row }">{{ quantityText(row.required_quantity) }}</template></ElTableColumn>
              <ElTableColumn label="本次完成" width="88" align="right"><template #default="{ row }">{{ quantityText(row.quantity) }}</template></ElTableColumn>
              <ElTableColumn label="进度" width="220">
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
            v-if="!detailLoading && !reports.length"
            :image-size="72"
            :description="selectedDate ? '当前日期暂无报工明细' : '当前车间暂无报工日期'"
          />
        </div>
      </section>
    </div>
  </section>
</template>

<style lang="scss">@use '@/styles/workshopReporting.scss';</style>
