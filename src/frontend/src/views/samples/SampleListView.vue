<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'

import { deleteSample, fetchSample, fetchSampleOptions, fetchSamples } from '@/api/samples'
import CrmPageHeader from '@/components/crm/CrmPageHeader.vue'
import SampleStatusTag from '@/components/samples/SampleStatusTag.vue'
import { sampleDateBounds, sampleProductsLabel, sampleProductFieldLabel, sampleQuantityLabel } from '@/utils/samplePresentation'
import { useAuthStore } from '@/stores/auth'
import type { SampleListItem, SampleListQuery, SampleOptions } from '@/types/sample'

interface FilterForm {
  q: string
  sample_type: string
  status: string
  owner_employee_id: string
  tracking_number: string
}

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const optionLoading = ref(false)
const errorMessage = ref('')
const rows = ref<SampleListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const options = ref<SampleOptions | null>(null)
const moreFiltersVisible = ref(false)
let rowsRequest = 0
const deletingId = ref<string | null>(null)
const requestedDates = ref<[Date, Date] | null>(null)
const mutationPending = computed(() => deletingId.value !== null)
const filters = reactive<FilterForm>({
  q: '', sample_type: '', status: '', owner_employee_id: '', tracking_number: '',
})
const hasFilters = computed(() => Object.values(filters).some(Boolean) || requestedDates.value !== null || typeof route.query.customer_id === 'string')

const canCreate = computed(() => authStore.hasPermission('samples.add_samplerequest'))
const canDelete = computed(() => authStore.hasPermission('samples.delete_samplerequest'))

function buildQuery(): SampleListQuery {
  const query: SampleListQuery = { page: page.value, page_size: pageSize.value, ordering: '-requested_at', ...sampleDateBounds(requestedDates.value) }
  if (filters.q.trim()) query.search = filters.q.trim()
  if (filters.sample_type) query.sample_type = filters.sample_type
  if (filters.status) query.status = filters.status
  if (filters.owner_employee_id) query.owner_employee_id = filters.owner_employee_id
  if (filters.tracking_number.trim()) query.tracking_number = filters.tracking_number.trim()
  if (typeof route.query.customer_id === 'string') query.customer_id = route.query.customer_id
  return query
}

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务后重试。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有执行该样品操作的权限。'
  if (error.response.status === 412) return '数据已被其他人修改，请刷新列表后重试。'
  if (error.response.status === 428) return '数据版本缺失，请刷新列表后重试。'
  if (error.response.status >= 500) return '后端服务暂时异常，请稍后重试。'
  return data?.error?.message || data?.detail || '请求失败，请检查输入。'
}

async function loadRows() {
  const request = ++rowsRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchSamples(buildQuery())
    if (request !== rowsRequest) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (request !== rowsRequest) return
    rows.value = []
    total.value = 0
    errorMessage.value = getErrorMessage(error)
  } finally {
    if (request === rowsRequest) loading.value = false
  }
}

async function loadOptions() {
  optionLoading.value = true
  try {
    options.value = await fetchSampleOptions()
  } catch (error) {
    ElMessage.error(`样品选项加载失败：${getErrorMessage(error)}`)
  } finally {
    optionLoading.value = false
  }
}

function searchSamples() {
  page.value = 1
  void loadRows()
}

function handleSearchEnter(event: KeyboardEvent) {
  event.preventDefault()
  if (event.isComposing || event.keyCode === 229) return
  searchSamples()
}

function resetFilters() {
  requestedDates.value = null
  Object.assign(filters, { q: '', sample_type: '', status: '', owner_employee_id: '', tracking_number: '' })
  searchSamples()
}

function openCreate() {
  if (!canCreate.value) return
  void router.push({ name: 'sample-new' })
}

function openDetail(sampleId: string) {
  const row = rows.value.find(item => item.id === sampleId)
  const name = row?.application_actions?.is_application && !['METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING', 'FINISHED'].includes(row.status) ? row.status === 'MATERIALS_PENDING' ? 'sample-materials' : ['WAREHOUSE_PENDING', 'PROCUREMENT_PENDING', 'MATERIALS_READY'].includes(row.status) ? 'sample-warehouse-review' : 'sample-director-review' : 'sample-detail'
  void router.push({ name, params: { sampleId } })
}

function openEdit(sampleId: string) {
  const row = rows.value.find((item) => item.id === sampleId)
  if (!row || !canEditRow(row)) return
  if (row.application_actions?.can_resubmit) {
    void router.push({ path: '/samples/new', query: { editApplication: sampleId } })
    return
  }
  void router.push({ name: 'sample-edit', params: { sampleId } })
}

function canEditRow(row: SampleListItem) {
  if (row.application_actions?.is_application) return row.application_actions.can_resubmit
  if (row.edit_capabilities?.mode === 'REPORT_ONLY') return ['productionreport_sample','metalreport_sample','cuttingreport_sample'].some(code=>authStore.moduleCan('access_control.'+code,'samples.change_samplerequest',row))
  if (row.status === 'PENDING_COMPLETION') return authStore.moduleCan('samples.complete_sample_requirements', undefined, row)
  return authStore.moduleCan('samples.change_samplerequest', undefined, row) && !['FINISHED', 'CONFIRMED', 'COMPLETED', 'REJECTED', 'CANCELLED'].includes(row.status)
}

function editLabel(row: SampleListItem) {
  if (row.application_actions?.can_resubmit) return '补充并重提'
  return row.status === 'PENDING_COMPLETION' ? '完善需求' : '编辑需求'
}

function rowClassName({ row }: { row: SampleListItem }) {
  return typeof route.query.focus === 'string' && route.query.focus === row.id ? 'is-focused-sample' : ''
}

async function deleteSampleRow(row: SampleListItem) {
  if (!canDelete.value || mutationPending.value || loading.value) return
  deletingId.value = row.id
  try {
    const current = await fetchSample(row.id)
    if (!current.etag) { ElMessage.warning('申请缺少数据版本，请刷新后重试。'); return }
    await ElMessageBox.confirm(
      `确定永久删除样品「${current.data.request_number}」吗？其样品明细、费用、物流、反馈和关联任务会一并删除，且无法恢复。`,
      '永久删除样品',
      { type: 'error', confirmButtonText: '确认永久删除', cancelButtonText: '取消' },
    )
    const result = await deleteSample(row.id, current.etag)
    ElMessage.success(`样品已永久删除，同时删除 ${result.deleted_count} 条关联数据。`)
    await loadRows()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  } finally {
    deletingId.value = null
  }
}

onMounted(async () => {
  if (typeof route.query.status === 'string') {
    filters.status = route.query.status
  }
  await Promise.all([loadRows(), loadOptions()])
})
onBeforeUnmount(() => { rowsRequest++ })
</script>

<template>
  <section class="sample-list-page erp-glass-list" aria-label="打样申请列表" data-figma-node="1897:18624">
    <section v-glass-spotlight class="erp-list-filter">
    <CrmPageHeader class="erp-list-heading" title="打样申请" :count="total" count-label="份申请" />

    <div class="filters erp-list-filters" role="search" aria-label="打样申请筛选">
      <ElInput
        v-model="filters.q"
        class="search-input"
        aria-label="搜索申请编号、客户、样品名称"
        title="支持申请编号、客户名称、样品名称、用途、备注或快递单号"
        clearable
        placeholder="搜索申请编号、客户、样品名称"
        @keydown.enter="handleSearchEnter"
        @clear="searchSamples"
      >
        <template #suffix><button type="button" class="sample-search-button erp-list-search-button" aria-label="搜索打样申请列表" @click="searchSamples"><ElIcon><Search /></ElIcon></button></template>
      </ElInput>
      <ElSelect v-model="filters.status" class="status-filter" aria-label="当前环节" clearable placeholder="当前环节：全部" :loading="optionLoading" @change="searchSamples"><ElOption v-for="item in options?.statuses" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
      <ElSelect v-model="filters.sample_type" class="type-filter" aria-label="样品类型" clearable placeholder="样品类型：全部" :loading="optionLoading" @change="searchSamples"><ElOption v-for="item in options?.sample_types" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
      <ElSelect v-model="filters.owner_employee_id" class="owner-filter" aria-label="业务员" clearable filterable placeholder="业务员：全部" :loading="optionLoading" @change="searchSamples"><ElOption v-for="item in options?.owners" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect>
      <ElPopover popper-class="erp-list-filter-popover" v-model:visible="moreFiltersVisible" trigger="click" placement="bottom-end" :width="340" :teleported="false">
        <template #reference><ElButton class="erp-button-motion more-filters">更多筛选</ElButton></template>
        <ElForm label-position="top" @submit.prevent="() => { searchSamples(); moreFiltersVisible = false }">
          <ElFormItem label="申请日期"><ElDatePicker v-model="requestedDates" class="requested-dates" type="daterange" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" format="YYYY-MM-DD" :teleported="false" /></ElFormItem>
          <ElFormItem label="快递单号"><ElInput v-model="filters.tracking_number" clearable placeholder="输入快递单号" /></ElFormItem>
          <div class="popover-actions"><ElButton class="erp-button-motion" @click="resetFilters">重置</ElButton><ElButton class="erp-button-motion" type="primary" native-type="submit">应用筛选</ElButton></div>
        </ElForm>
      </ElPopover>
      <div class="erp-list-filter-actions"><ElButton class="erp-button-motion reset-button" @click="resetFilters">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="searchSamples">应用筛选</ElButton></div>

    </div>

    </section>

    <div class="table-card erp-list-data">
      <div class="erp-list-toolbar">      <div class="sample-actions"><ElButton v-if="canCreate" class="erp-button-motion create-button" type="primary" @click="openCreate">申请打样</ElButton></div></div>
      <div class="erp-list-table-frame">
      <div v-if="errorMessage" class="data-state" role="alert"><strong>{{ errorMessage }}</strong><ElButton class="erp-button-motion" @click="loadRows">重新加载</ElButton></div>
      <ElTable v-else v-loading="loading" class="sample-table" :data="rows" row-key="id" height="100%" :row-class-name="rowClassName">
        <ElTableColumn label="申请编号" width="156"><template #default="{ row }"><button class="sample-link" :title="row.request_number" @click="openDetail(row.id)">{{ row.request_number }}</button></template></ElTableColumn>
        <ElTableColumn label="提交日期" width="100"><template #default="{ row }">{{ row.submitted_on || (row.status === 'DRAFT' ? '未提交' : '—') }}</template></ElTableColumn>
        <ElTableColumn prop="customer_name" label="客户" min-width="180" show-overflow-tooltip class-name="customer-cell" />
        <ElTableColumn label="样品名称" min-width="170" show-overflow-tooltip><template #default="{ row }"><span :title="sampleProductsLabel(row)">{{ sampleProductsLabel(row) }}</span></template></ElTableColumn>
        <ElTableColumn label="规格" min-width="180" show-overflow-tooltip><template #default="{ row }"><span :title="sampleProductFieldLabel(row, 'specification')">{{ sampleProductFieldLabel(row, 'specification') }}</span></template></ElTableColumn>
        <ElTableColumn label="颜色" width="150" show-overflow-tooltip><template #default="{ row }"><span :title="sampleProductFieldLabel(row, 'color')">{{ sampleProductFieldLabel(row, 'color') }}</span></template></ElTableColumn>
        <ElTableColumn label="数量" width="78"><template #default="{ row }">{{ sampleQuantityLabel(row) }}</template></ElTableColumn>
        <ElTableColumn prop="sample_type_display" label="类型" width="90" show-overflow-tooltip />
        <ElTableColumn label="业务员" width="88" show-overflow-tooltip><template #default="{ row }">{{ row.owner?.display_name || '—' }}</template></ElTableColumn>
        <ElTableColumn label="期望完成" width="110"><template #default="{ row }">{{ row.requested_due_at?.slice(0, 10) || row.sample_due_date || '—' }}</template></ElTableColumn>
        <ElTableColumn label="当前环节" width="128"><template #default="{ row }"><SampleStatusTag :status="row.status" :label="row.status_display" /></template></ElTableColumn>
        <ElTableColumn label="材料情况" width="120"><template #default="{ row }"><SampleStatusTag v-if="row.material_summary" :status="row.material_summary.status" :label="row.material_summary.label" /><span v-else class="muted">—</span></template></ElTableColumn>
        <ElTableColumn label="操作" width="72" align="center" fixed="right"><template #default="{ row }"><div class="row-actions"><ElDropdown :persistent="false" trigger="click"><ElButton link>更多</ElButton><template #dropdown><ElDropdownMenu><ElDropdownItem @click="openDetail(row.id)">查看</ElDropdownItem><ElDropdownItem v-if="row.application_actions?.is_application" @click="router.push({ name: 'sample-material-detail', params: { sampleId: row.id } })">查看用料需求</ElDropdownItem><ElDropdownItem v-if="row.status === 'MATERIAL_ISSUE_PENDING' && authStore.moduleCan('samples.edit_sample_materials', undefined, row)" @click="router.push({ name: 'sample-material-issue', params: { sampleId: row.id } })">发起样品领料</ElDropdownItem><ElDropdownItem v-if="row.status === 'MATERIAL_ISSUE_REVIEW' && authStore.moduleCan('samples.review_sample_materials', undefined, row)" @click="router.push({ name: 'sample-material-issue-confirm', params: { sampleId: row.id } })">确认实际领料</ElDropdownItem><ElDropdownItem :disabled="!canEditRow(row) || mutationPending" @click="openEdit(row.id)">{{ editLabel(row) }}</ElDropdownItem><ElDropdownItem v-if="canDelete && authStore.moduleCan('samples.delete_samplerequest', undefined, row)" :disabled="mutationPending || loading" divided @click="deleteSampleRow(row)">永久删除</ElDropdownItem></ElDropdownMenu></template></ElDropdown></div></template></ElTableColumn>
        <template #empty><div class="data-state"><strong>{{ loading ? '正在加载打样申请…' : hasFilters ? '没有符合条件的打样申请' : '暂无打样申请' }}</strong><template v-if="!loading"><p>{{ hasFilters ? '调整筛选条件后重试。' : '创建第一份打样申请，开始跟进样品。' }}</p><ElButton class="erp-button-motion" v-if="hasFilters" @click="resetFilters">重置筛选</ElButton><ElButton class="erp-button-motion" v-else-if="canCreate" type="primary" @click="openCreate">申请打样</ElButton></template></div></template>
      </ElTable>
      </div>
      <footer class="table-footer erp-list-footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :disabled="loading" background layout="sizes, prev, pager, next" :pager-count="5" :page-sizes="[20, 50, 100]" :total="total" @current-change="loadRows" @size-change="() => { page = 1; void loadRows() }" /></footer>
    </div>

  </section>
</template>

<style scoped lang="scss" src="./sampleList.scss"></style>
