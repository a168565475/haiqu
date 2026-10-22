<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowDown, Filter, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchReportingContext, fetchWageSchemes } from '@/api/workshopReporting'
import { useAuthStore } from '@/stores/auth'
import type { WageScheme } from '@/types/workshopReporting'
import { formatWageMoney } from '@/utils/wageMoney'
import WageSchemeDetailDialog from './WageSchemeDetailDialog.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const canSubmit = computed(() => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.submit_wagescheme'))
const canCreate = computed(() => auth.user?.is_superuser || (
  auth.hasPermission('workshop_reporting.add_wagescheme') && canSubmit.value
))
const canChange = computed(() => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.change_wagescheme'))
const canApprove = computed(() => auth.user?.is_superuser || auth.hasPermission('workshop_reporting.approve_wagescheme'))
const rows = ref<WageScheme[]>([])
const loading = ref(false)
const errorMessage = ref('')
const search = ref('')
const workshopId = ref('')
const status = ref('')
const schemeTypeFilter = ref('')
const ordering = ref('-updated_at')
const updatedRangeDraft = ref<[string, string] | null>(null)
const updatedRangeApplied = ref<[string, string] | null>(null)
const moreFilterVisible = ref(false)
const workshopOptions = ref<Array<{ id: string; name: string }>>([])
const filterOptionsLoading = ref(false)
const filterOptionsError = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
let requestSequence = 0
const detailSchemeId = ref(typeof route.query.detail === 'string' ? route.query.detail : null)
const detailVisible = computed({
  get: () => Boolean(detailSchemeId.value),
  set: value => { if (!value) closeDetail() },
})
const statusClass = (value: string) => ({ APPROVED: 'is-success', PENDING_APPROVAL: 'is-warning', RETURNED: 'is-danger', DRAFT: 'is-neutral', SUPERSEDED: 'is-neutral' }[value] || 'is-neutral')
const statusText = (row: WageScheme) => row.status === 'PENDING_APPROVAL' ? '待厂长审批' : row.status_display
const schemeType = (row: WageScheme) => row.parent_scheme ? '变更' : '新增'
const productText = (row: WageScheme) => [row.product.number, row.product.name, row.product.specification].filter(Boolean).join(' · ')
const formatDateTime = (value: string) => value ? value.replace('T', ' ').slice(0, 16) : '—'
const errorText = (error: unknown) => (error as { response?: { data?: { error?: { message?: string } } } })?.response?.data?.error?.message || '工价方案加载失败。'
async function load() {
  const current = ++requestSequence
  loading.value = true
  try {
    const result = await fetchWageSchemes({
      page: page.value,
      page_size: pageSize.value,
      search: search.value.trim() || undefined,
      workshop_id: workshopId.value || undefined,
      status: status.value || undefined,
      scheme_type: schemeTypeFilter.value || undefined,
      updated_from: updatedRangeApplied.value?.[0] || undefined,
      updated_to: updatedRangeApplied.value?.[1] || undefined,
      ordering: ordering.value,
    })
    if (current !== requestSequence) return
    rows.value = result.data; total.value = result.meta.total; errorMessage.value = ''
  } catch (error) {
    if (current !== requestSequence) return
    rows.value = []; total.value = 0; errorMessage.value = errorText(error)
  }
  finally { if (current === requestSequence) loading.value = false }
}
function apply() { page.value = 1; void load() }
async function loadFilterOptions() {
  filterOptionsLoading.value = true
  try {
    const context = await fetchReportingContext()
    workshopOptions.value = context.workshops.map(item => ({ id: item.id, name: item.name }))
    filterOptionsError.value = ''
  } catch (error) {
    workshopOptions.value = []
    filterOptionsError.value = errorText(error)
  } finally {
    filterOptionsLoading.value = false
  }
}
function resetFilters() {
  search.value = ''
  workshopId.value = ''
  status.value = ''
  schemeTypeFilter.value = ''
  updatedRangeDraft.value = null
  updatedRangeApplied.value = null
  ordering.value = '-updated_at'
  moreFilterVisible.value = false
  apply()
}
function applyMoreFilters() {
  updatedRangeApplied.value = updatedRangeDraft.value ? [...updatedRangeDraft.value] : null
  moreFilterVisible.value = false
  apply()
}
function openDetail(schemeId: string) {
  detailSchemeId.value = schemeId
  void router.replace({ query: { ...route.query, detail: schemeId } })
}
function canProcess(row: WageScheme) {
  if (row.status === 'PENDING_APPROVAL') return canApprove.value
  return ['DRAFT', 'RETURNED'].includes(row.status) && canSubmit.value
}
function closeDetail() {
  detailSchemeId.value = null
  if (!route.query.detail) return
  const query = { ...route.query }
  delete query.detail
  void router.replace({ query })
}
watch(() => route.query.detail, value => {
  detailSchemeId.value = typeof value === 'string' ? value : null
})
watch(moreFilterVisible, visible => {
  if (visible) updatedRangeDraft.value = updatedRangeApplied.value ? [...updatedRangeApplied.value] : null
})
onMounted(() => { void loadFilterOptions(); void load() })
</script>

<template>
  <section class="wr-page erp-glass-list" data-testid="wage-scheme-list">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="wr-heading erp-list-heading"><div class="wr-heading__title erp-list-title-row"><h1>工价方案</h1><span class="wr-heading__meta erp-list-count">共 {{ total }} 份</span></div></header>
    <section class="wr-toolbar wr-wage-filter-toolbar erp-list-filters" aria-label="工价方案筛选">
      <ElInput v-model="search" :prefix-icon="Search" clearable placeholder="搜索方案号、订单号或产品" @keyup.enter="apply" @clear="apply" />
      <ElSelect v-model="workshopId" data-testid="wage-workshop-filter" :loading="filterOptionsLoading" clearable placeholder="车间：全部" @change="apply"><ElOption v-for="item in workshopOptions" :key="item.id" :label="item.name" :value="item.id" /></ElSelect>
      <ElSelect v-model="status" data-testid="wage-status-filter" clearable placeholder="审批状态：全部" @change="apply"><ElOption label="草稿" value="DRAFT" /><ElOption label="待厂长审批" value="PENDING_APPROVAL" /><ElOption label="已批准" value="APPROVED" /><ElOption label="已退回" value="RETURNED" /><ElOption label="已替代" value="SUPERSEDED" /></ElSelect>
      <ElSelect v-model="schemeTypeFilter" data-testid="wage-type-filter" clearable placeholder="类型：全部" @change="apply"><ElOption label="新增" value="NEW" /><ElOption label="变更" value="CHANGE" /></ElSelect>
      <ElPopover v-model:visible="moreFilterVisible" placement="bottom-end" :width="360" trigger="click" popper-class="erp-list-filter-popover">
        <template #reference><ElButton class="erp-button-motion" :icon="Filter">更多筛选<ElIcon class="wr-more-filter__arrow"><ArrowDown /></ElIcon></ElButton></template>
        <div class="wr-more-filter-panel"><strong>更多筛选</strong><label><span>更新日期</span><ElDatePicker v-model="updatedRangeDraft" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" clearable /></label><div><ElButton class="erp-button-motion" @click="resetFilters">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="applyMoreFilters">应用筛选</ElButton></div></div>
      </ElPopover>
      <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="resetFilters">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="apply">应用筛选</ElButton></div>
    </section>
    <ElAlert v-if="filterOptionsError" class="wr-filter-alert" type="warning" show-icon :closable="false" title="车间筛选选项加载失败，列表仍可正常查看。"><ElButton class="erp-button-motion" @click="loadFilterOptions">重试</ElButton></ElAlert>
    </section>
    <section class="wr-list-card erp-list-data" aria-label="工价方案记录">
      <header class="wr-list-card__header erp-list-toolbar erp-list-filters"><strong>工价方案记录</strong><ElButton class="erp-button-motion" v-if="canCreate" type="primary" :icon="Plus" @click="router.push({ name: 'wage-scheme-new' })">新增工价方案</ElButton><div><ElSelect v-model="ordering" data-testid="wage-ordering" class="wr-ordering-select" aria-label="列表排序" @change="apply"><ElOption label="更新时间 ↓" value="-updated_at" /><ElOption label="更新时间 ↑" value="updated_at" /><ElOption label="方案编号 ↓" value="-scheme_number" /><ElOption label="方案编号 ↑" value="scheme_number" /></ElSelect><ElButton class="erp-button-motion" :icon="Refresh" :loading="loading" @click="load">刷新</ElButton></div></header>
      <ElAlert v-if="errorMessage" class="wr-list-error" type="error" show-icon :closable="false" :title="errorMessage"><ElButton class="erp-button-motion" @click="load">重试</ElButton></ElAlert>
      <div v-else class="erp-list-table-frame"><ElTable height="100%" v-loading="loading" :data="rows" border row-key="id" empty-text="暂无工价方案">
      <ElTableColumn prop="scheme_number" label="方案编号" min-width="130" show-overflow-tooltip />
      <ElTableColumn prop="production_task.task_number" label="生产任务单" min-width="120" show-overflow-tooltip />
      <ElTableColumn label="产品信息" min-width="180" show-overflow-tooltip><template #default="{ row }">{{ productText(row) }}</template></ElTableColumn>
      <ElTableColumn prop="workshop.name" label="所属车间" min-width="85" show-overflow-tooltip />
      <ElTableColumn label="所属工艺" min-width="90" show-overflow-tooltip><template #default="{ row }">{{ row.crafts.map((item: { name: string }) => item.name).join('、') || '—' }}</template></ElTableColumn>
      <ElTableColumn label="类型" width="60"><template #default="{ row }">{{ schemeType(row) }}</template></ElTableColumn>
      <ElTableColumn label="工价合计" width="90" align="right" class-name="wr-money"><template #default="{ row }">{{ formatWageMoney(row.declared_total) }}</template></ElTableColumn>
      <ElTableColumn label="审批状态" width="120" align="center"><template #default="{ row }"><span class="wr-status-tag" :class="['erp-list-tag', statusClass(row.status).replace('is-', 'erp-list-tag--')]">{{ statusText(row) }}</span></template></ElTableColumn>
      <ElTableColumn label="更新日期" width="160" class-name="wr-updated-at"><template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template></ElTableColumn>
      <ElTableColumn label="操作" width="130" fixed="right"><template #default="{ row }"><ElButton link type="primary" @click="openDetail(row.id)">查看</ElButton><ElButton v-if="canProcess(row)" link type="primary" @click="router.push({ name: 'wage-scheme-detail', params: { schemeId: row.id } })">处理</ElButton><ElButton v-if="row.can_create_change && canChange && canSubmit" link type="primary" @click="router.push({ name: 'wage-scheme-change', params: { schemeId: row.id } })">变更</ElButton></template></ElTableColumn>
      </ElTable></div>
      <footer v-if="!errorMessage" class="wr-pagination erp-list-footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="sizes, prev, pager, next" @current-change="load" @size-change="page = 1; load()" /></footer>
    </section>
    <WageSchemeDetailDialog v-model="detailVisible" :scheme-id="detailSchemeId" />
  </section>
</template>

<style lang="scss">@use '@/styles/workshopReporting.scss';</style>

<style scoped lang="scss">
.wr-status-tag.erp-list-tag { white-space: nowrap; }
:deep(.wr-updated-at .cell) { white-space: nowrap; }
.wr-wage-filter-toolbar > :deep(.el-input) { width: min(100%, 380px); }
.wr-wage-filter-toolbar > :deep(.el-select) { width: 186px; }
.wr-list-card__header > div { display: flex; align-items: center; gap: 8px; margin-left: auto; }
</style>
