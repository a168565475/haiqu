<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ArrowDown, Refresh, Search } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchScheduleItems } from '@/api/productionScheduling'
import { fetchPlanWageStatuses } from '@/api/workshopReporting'
import { useAuthStore } from '@/stores/auth'
import type { PlanCategory, ScheduleItem } from '@/types/productionScheduling'
import type { PlanWageStatus } from '@/types/workshopReporting'
import { formatWageMoney } from '@/utils/wageMoney'
import WageSchemeDetailDialog from '@/views/workshop/wage-schemes/WageSchemeDetailDialog.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const canReceiveFinished = computed(() => auth.hasPermission('inventory.add_finishedgoodsreceipt'))
const canReceiveSemi = computed(() => auth.user?.is_superuser || (auth.hasPermission('inventory.add_internalsemifinishedreceipt') && auth.hasPermission('inventory.view_internalsemifinishedreceipt')))
const canViewMetalProcessing = computed(() => auth.user?.is_superuser || auth.hasPermission('material_issues.view_metalprocessingsource'))
const canViewMaterialIssue = computed(() => auth.user?.is_superuser || auth.hasPermission('material_issues.view_materialissue'))
const canCreateMaterialIssue = computed(() => auth.user?.is_superuser || (
  auth.hasPermission('material_issues.add_materialissue')
  && auth.hasPermission('material_issues.view_materialissue')
))
const canManageWageScheme = computed(() => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.view_wagescheme'))
const canCreateWageScheme = computed(() => auth.user?.is_superuser || (
  auth.hasPermission('workshop_reporting.add_wagescheme')
  && auth.hasPermission('workshop_reporting.view_wagescheme')
  && auth.hasPermission('workshop_reporting.submit_wagescheme')
))
const canCreateWorkReport = computed(() => auth.user?.is_superuser || (
  auth.hasPermission('workshop_reporting.add_workreport')
  && auth.hasPermission('workshop_reporting.view_workreport')
))
const canViewWorkReport = computed(() => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.view_workreport'))
const configs: Record<string, { category: PlanCategory; title: string; date: string }> = {
  'workshop-metalworking-plan': { category: 'METAL', title: '金工计划', date: '金工回货日期' },
  'workshop-cutting-plan': { category: 'CUTTING', title: '裁剪计划', date: '车缝回货日期' },
  'workshop-sewing-plan': { category: 'SEWING', title: '车缝计划', date: '车缝回货日期' },
  'workshop-assembly-plan': { category: 'ASSEMBLY', title: '装配计划', date: '成品入库日期' },
}
const planTabs = [
  { routeName: 'workshop-metalworking-plan', label: '金工计划' },
  { routeName: 'workshop-cutting-plan', label: '裁剪计划' },
  { routeName: 'workshop-sewing-plan', label: '车缝计划' },
  { routeName: 'workshop-assembly-plan', label: '装配计划' },
]
const config = computed(() => configs[String(route.name)] || configs['workshop-metalworking-plan'])
const activePlanName = computed(() => String(route.name || 'workshop-metalworking-plan'))
const rows = ref<ScheduleItem[]>([])
const wageStatuses = ref<Record<string, PlanWageStatus>>({})
const loading = ref(false)
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const search = ref('')
const dateRange = ref<[string, string] | []>([])
const errorMessage = ref('')
const wageStatusError = ref('')
const wageDetailVisible = ref(false)
const wageDetailSchemeId = ref<string | null>(null)
const shanghaiToday = () => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date())
let requestSequence = 0
function errorText(error: unknown) {
  if (!(error instanceof AxiosError)) return `${config.value.title}加载失败。`
  const data = error.response?.data as { error?: { message?: string } } | undefined
  return data?.error?.message || `${config.value.title}加载失败。`
}
async function load() {
  const current = ++requestSequence
  loading.value = true
  try {
    const result = await fetchScheduleItems({ category: config.value.category, page: page.value, page_size: pageSize.value, search: search.value.trim() || undefined, date_from: dateRange.value[0] || undefined, date_to: dateRange.value[1] || undefined, schedule_id: route.query.schedule_id || undefined, schedule_product_id: route.query.schedule_product_id || undefined })
    if (current !== requestSequence) return
    rows.value = result.data; total.value = result.meta.total; errorMessage.value = ''
    wageStatuses.value = {}
    if (result.data.length) {
      try {
        const statuses = await fetchPlanWageStatuses({
          schedule_product_ids: result.data.map(item => item.id).join(','),
        production_date: shanghaiToday(),
          plan_category: config.value.category,
        })
        if (current !== requestSequence) return
        wageStatuses.value = Object.fromEntries(statuses.map(item => [item.schedule_product_id, item]))
        wageStatusError.value = ''
      } catch {
        if (current !== requestSequence) return
        wageStatuses.value = {}
        wageStatusError.value = '工价状态加载失败，报工入口已停用，请刷新重试。'
      }
    }
  } catch (error) { if (current === requestSequence) { rows.value = []; total.value = 0; errorMessage.value = errorText(error) } }
  finally { if (current === requestSequence) loading.value = false }
}
function apply() { page.value = 1; void load() }
function changePlan(name: string | number) {
  const target = planTabs.find(item => item.routeName === String(name))
  if (!target || target.routeName === activePlanName.value) return
  void router.push({ name: target.routeName, query: route.query })
}
function createMaterialIssue(row: ScheduleItem) {
  void router.push({
    name: 'material-issue-new',
    query: {
      production_task_id: row.production_task_id,
      product_line_id: row.product_line_id,
      schedule_product_id: row.id,
      plan_category: config.value.category,
    },
  })
}
function openMaterialIssueRecords(row: ScheduleItem) {
  void router.push({
    name: 'material-issues',
    query: {
      production_task_id: row.production_task_id,
      product_line_id: row.product_line_id,
    },
  })
}
function openMetalProcessing(row: ScheduleItem) {
  if (config.value.category !== 'METAL' || !canViewMetalProcessing.value) return
  void router.push({ name: 'workshop-outsourcing', query: { tab: 'sources',
    production_task_id: row.production_task_id, product_line_id: row.product_line_id,
  } })
}
function openWageScheme(row: ScheduleItem) {
  const schemeId = wageStatuses.value[row.id]?.scheme_id
  if (schemeId) {
    wageDetailSchemeId.value = schemeId
    wageDetailVisible.value = true
    return
  }
  void router.push({ name: 'wage-scheme-new', query: { schedule_product_id: row.id, workshop_id: wageStatuses.value[row.id]?.workshop_id || undefined, craft_id: wageStatuses.value[row.id]?.craft_id || undefined } })
}
function openWorkReport(row: ScheduleItem) {
  void router.push({ name: 'work-report-new', query: { schedule_product_id: row.id, workshop_id: wageStatuses.value[row.id]?.workshop_id || undefined, craft_id: wageStatuses.value[row.id]?.craft_id || undefined } })
}
function openWorkReportRecords(row: ScheduleItem) {
  if (!wageStatuses.value[row.id]?.workshop_id) return
  void router.push({ name: 'work-report-days', query: { schedule_product_id: row.id, workshop_id: wageStatuses.value[row.id]?.workshop_id || undefined, craft_id: wageStatuses.value[row.id]?.craft_id || undefined } })
}
function wageStatus(row: ScheduleItem) { return wageStatuses.value[row.id] }
function wageStatusLabel(row: ScheduleItem) {
  const value = wageStatus(row)?.status
  if (!value && wageStatusError.value) return '状态加载失败'
  return ({ APPROVED: '工价已批准', PENDING_APPROVAL: '工价待审批', DRAFT: '工价草稿', RETURNED: '工价已退回', NO_EFFECTIVE_VERSION: '日期无工价', CONFLICT: '工价冲突', FORBIDDEN: '无车间权限', UNAVAILABLE: '范围异常', NOT_CREATED: '未建工价', SUPERSEDED: '旧工价' } as Record<string, string>)[value || 'NOT_CREATED']
}
function wageStatusTone(row: ScheduleItem) {
  const value = wageStatus(row)?.status
  if (!value && wageStatusError.value) return 'status-danger'
  return ({
    APPROVED: 'status-success', PENDING_APPROVAL: 'status-warning', DRAFT: 'status-neutral',
    RETURNED: 'status-danger', NO_EFFECTIVE_VERSION: 'status-warning', CONFLICT: 'status-danger',
    FORBIDDEN: 'status-neutral', UNAVAILABLE: 'status-danger', NOT_CREATED: 'status-neutral', SUPERSEDED: 'status-neutral',
  } as Record<string, string>)[value || 'NOT_CREATED']
}
function jobStatusTone(row: ScheduleItem) {
  return ({
    IN_PROGRESS: 'status-info', COMPLETED: 'status-success', PAUSED: 'status-warning', CANCELLED: 'status-danger',
  } as Record<string, string>)[wageStatus(row)?.plan_status || row.job_status] || 'status-neutral'
}
function jobStatusLabel(row: ScheduleItem) { return wageStatus(row)?.plan_status_display || row.job_status_display }
function progressLabel(row: ScheduleItem) {
  const status = wageStatus(row)
  if (!status && wageStatusError.value) return '加载失败'
  if (!status) return '—'
  return status?.progress_percent === null || status?.progress_percent === undefined
    ? '待设置工价'
    : `${status.progress_percent}%`
}
watch(() => route.name, () => { search.value = ''; dateRange.value = []; apply() })
onMounted(() => { void load() })
</script>

<template>
  <section class="schedule-page workshop-plan-list" :data-testid="`workshop-plan-${config.category.toLowerCase()}`">
    <header class="schedule-heading"><div><h1>内部计划</h1><span>{{ config.title }} · {{ total }} 条产品计划</span></div></header>
    <ElTabs class="internal-plan-tabs" :model-value="activePlanName" @tab-change="changePlan">
      <ElTabPane v-for="tab in planTabs" :key="tab.routeName" :name="tab.routeName" :label="tab.label" />
    </ElTabs>
    <div class="schedule-filter-bar plan-filter-bar"><ElInput v-model="search" :prefix-icon="Search" clearable placeholder="搜索排产单号、生产任务单号、产品" @keyup.enter="apply" @clear="apply" /><div class="plan-date-filter"><span>{{ config.date.replace('日期', '时间') }}</span><ElDatePicker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" popper-class="schedule-date-popper" @change="apply" /></div><ElButton :icon="Refresh" :loading="loading" @click="load">刷新</ElButton></div>
    <ElAlert v-if="route.query.schedule_id" class="plan-context" type="info" :closable="false" show-icon title="已从主计划带入筛选上下文"><ElButton link type="primary" @click="router.replace({ path: route.path })">清除筛选</ElButton></ElAlert>
    <ElAlert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false"><ElButton @click="load">重试</ElButton></ElAlert>
    <ElAlert v-else-if="wageStatusError" type="warning" :title="wageStatusError" show-icon :closable="false"><ElButton @click="load">重试</ElButton></ElAlert>
    <div class="schedule-table-card"><ElTable v-loading="loading" :data="rows" border row-key="id" empty-text="暂无符合条件的产品计划">
      <ElTableColumn label="生产任务单号" width="170"><template #default="{ row }"><span class="plan-text-cell">{{ row.task_number || '—' }}</span></template></ElTableColumn>
      <ElTableColumn label="排产单号" width="170"><template #default="{ row }"><span class="plan-text-cell">{{ row.schedule_number || '—' }}</span></template></ElTableColumn>
      <ElTableColumn label="产品名称" min-width="190"><template #default="{ row }"><span class="plan-text-cell">{{ row.product.product_name || '未命名产品' }}</span></template></ElTableColumn>
      <ElTableColumn label="规格" min-width="150"><template #default="{ row }"><span class="plan-text-cell">{{ row.product.specification || '—' }}</span></template></ElTableColumn>
      <ElTableColumn label="颜色" width="120"><template #default="{ row }"><span class="plan-text-cell">{{ row.product.color_name || '—' }}</span></template></ElTableColumn>
      <ElTableColumn label="排产数量" width="120"><template #default="{ row }">{{ row.planned_quantity }} {{ row.unit_name }}</template></ElTableColumn>
      <ElTableColumn label="厂内工艺" min-width="150"><template #default="{ row }"><ElTag class="plan-craft-tag" :class="`is-${config.category.toLowerCase()}`" effect="dark">{{ row.craft_names.join('、') }}</ElTag></template></ElTableColumn>
      <ElTableColumn prop="plan_date" :label="config.date" width="160" />
      <ElTableColumn label="作业状态" width="112"><template #default="{ row }"><span class="plan-status-tag" :class="jobStatusTone(row)">{{ jobStatusLabel(row) }}</span></template></ElTableColumn>
      <ElTableColumn label="完成进度" width="108" align="center"><template #default="{ row }">{{ progressLabel(row) }}</template></ElTableColumn>
      <ElTableColumn label="预计工价" width="110" align="right"><template #default="{ row }">{{ formatWageMoney(wageStatus(row)?.estimated_wage) }}</template></ElTableColumn>
      <ElTableColumn label="工价状态" width="120"><template #default="{ row }"><span class="plan-status-tag" :class="wageStatusTone(row)">{{ wageStatusLabel(row) }}</span></template></ElTableColumn>
      <ElTableColumn label="操作" width="100" fixed="right"><template #default="{ row }"><div class="plan-row-actions"><ElDropdown trigger="click"><ElButton link type="primary">更多<ElIcon class="el-icon--right"><ArrowDown /></ElIcon></ElButton><template #dropdown><ElDropdownMenu><ElDropdownItem v-if="canReceiveFinished && config.category==='ASSEMBLY'" @click="router.push({name:'assembly-finished-receipt',query:{schedule_product_id:row.id}})">成品入库</ElDropdownItem><ElDropdownItem v-if="canReceiveSemi &amp;&amp; ['METAL','SEWING'].includes(config.category)" @click="router.push({name: 'internal-semi-receipt', query: {schedule_product_id: row.id, plan_category: config.category}})">半成品入库</ElDropdownItem><ElDropdownItem v-if="canCreateMaterialIssue" @click="createMaterialIssue(row)">生产领料</ElDropdownItem><ElDropdownItem v-if="canViewMaterialIssue" @click="openMaterialIssueRecords(row)">查看领料记录</ElDropdownItem><ElDropdownItem v-if="config.category === 'METAL' && canViewMetalProcessing" data-testid="plan-metal-processing-entry" @click="openMetalProcessing(row)">金工完成登记</ElDropdownItem><ElDropdownItem v-if="canManageWageScheme && (wageStatus(row)?.scheme_id || canCreateWageScheme)" @click="openWageScheme(row)">{{ wageStatus(row)?.scheme_id ? '查看工价' : '新建工价' }}</ElDropdownItem><ElDropdownItem v-if="canCreateWorkReport" :disabled="!wageStatus(row)?.can_report" @click="openWorkReport(row)">计件报工</ElDropdownItem><ElDropdownItem v-if="canViewWorkReport" :disabled="!wageStatus(row)?.workshop_id" @click="openWorkReportRecords(row)">查看报工记录</ElDropdownItem></ElDropdownMenu></template></ElDropdown></div></template></ElTableColumn>
    </ElTable></div>
    <footer class="schedule-pagination"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="sizes, prev, pager, next" @current-change="load" @size-change="page = 1; load()" /></footer>
    <WageSchemeDetailDialog v-model="wageDetailVisible" :scheme-id="wageDetailSchemeId" />
  </section>
</template>

<style lang="scss">@use '@/styles/productionScheduling.scss';</style>
<style scoped lang="scss">
.workshop-plan-list {
  height: calc(100dvh - 92px);
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.workshop-plan-list .schedule-table-card {
  min-height: 0;
  flex: 1;
  display: flex;
  flex-direction: column;
}
.workshop-plan-list .schedule-table-card :deep(.el-table) {
  min-height: 0;
  flex: 1;
}
.workshop-plan-list .plan-text-cell {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
