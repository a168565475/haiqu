<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import {
  Plus,
  Refresh,
  Search,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'
import CustomerIdentityCell from '@/components/customers/CustomerIdentityCell.vue'
import CustomerCountryCell from '@/components/customers/CustomerCountryCell.vue'
import CrmPageHeader from '@/components/crm/CrmPageHeader.vue'
import CustomerCreateDialog from './CustomerCreateDialog.vue'
import CustomerEditDialog from './CustomerEditDialog.vue'
import exportIcon from '@/assets/crm-v2/export.svg'
import searchIcon from '@/assets/crm-v2/search.svg'
import sortCustomerIcon from '@/assets/crm-v2/sort-customer.svg'
import {
  deleteCustomer,
  exportCustomers,
  fetchCustomer,
  fetchCustomerOptions,
  fetchCustomers,
} from '@/api/customers'
import { useOptions } from '@/composables/useOptions'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { useAuthStore } from '@/stores/auth'
import { toCustomerDictionaryOptions } from '@/utils/referenceOptions'
import {
  formatCustomerGradeCell,
  formatCustomerListDate as formatDate,
  getFollowUpStatus,
  getRiskStatus,
} from './customerListPresentation'
import type {
  CustomerActivityStatus,
  CustomerListItem,
  CustomerListQuery,
  CustomerOptions,
  CustomerOrdering,
} from '@/types/customer'

interface FilterForm {
  q: string
  customer_grade: string
  country_code: string
  activity_status: '' | CustomerActivityStatus
}

const authStore = useAuthStore()
const router = useRouter()
const gradeOptions = useOptions('CUSTOMER_GRADE')
const loading = ref(false)
const optionsLoading = ref(false)
const errorMessage = ref('')
const rows = ref<CustomerListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const ordering = ref<CustomerOrdering>('-updated_at')
const options = ref<CustomerOptions | null>(null)
const exportLoading = ref(false)
const createDialogVisible = ref(false)
const editDialogVisible = ref(false)
const editingCustomerId = ref('')
let latestRowsRequest = 0

const filters = reactive<FilterForm>({
  q: '',
  customer_grade: '',
  country_code: '',
  activity_status: '',
})
// 分页和导出沿用已应用条件，避免把尚未确认的筛选草稿带入请求。
const appliedFilters = reactive<FilterForm>({ ...filters })

const canChangeCustomer = computed(() => authStore.hasPermission('customers.change_customeraccount'))
const canDeleteCustomer = computed(() => authStore.hasPermission('customers.delete_customeraccount'))

const hasActiveFilters = computed(() => Object.values(appliedFilters).some((value) => value.trim()))

function buildQuery(): CustomerListQuery {
  const query: CustomerListQuery = { page: page.value, page_size: pageSize.value, ordering: ordering.value }
  if (appliedFilters.q.trim()) query.q = appliedFilters.q.trim()
  if (appliedFilters.customer_grade) query.customer_grade = appliedFilters.customer_grade
  if (appliedFilters.country_code) query.country_code = appliedFilters.country_code
  if (appliedFilters.activity_status) query.activity_status = appliedFilters.activity_status
  return query
}

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务。'
  const status = error.response.status
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (status === 401) return '登录状态已失效，请重新登录。'
  if (status === 403) return '当前账号没有查看客户列表的权限。'
  if (status >= 500) return '后端服务暂时异常，请稍后重试。'
  return data?.error?.message || data?.detail || '请求失败，请检查输入。'
}

async function loadRows() {
  const requestId = ++latestRowsRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchCustomers(buildQuery())
    // 连续应用筛选时，只允许最新请求同步表格、总数和加载状态。
    if (requestId !== latestRowsRequest) return
    rows.value = result.data
    total.value = result.meta.total
    if (page.value > result.meta.total_pages && result.meta.total_pages > 0) {
      page.value = result.meta.total_pages
      await loadRows()
    }
  } catch (error) {
    if (requestId !== latestRowsRequest) return
    rows.value = []
    errorMessage.value = getErrorMessage(error)
  } finally {
    if (requestId === latestRowsRequest) loading.value = false
  }
}

watch(gradeOptions.options, (grades) => {
  if (!options.value || optionsLoading.value || gradeOptions.configVersion.value === null) return
  options.value = {
    ...options.value,
    customer_grades: toCustomerDictionaryOptions(grades),
  }
})

async function loadOptions() {
  optionsLoading.value = true
  try {
    const [legacyResult, publishedResult] = await Promise.allSettled([
      fetchCustomerOptions(),
      gradeOptions.load(),
    ])
    if (legacyResult.status === 'rejected') throw legacyResult.reason
    const legacyOptions = legacyResult.value
    if (publishedResult.status === 'fulfilled' && gradeOptions.configVersion.value !== null) {
      const grades = publishedResult.value
      options.value = {
        ...legacyOptions,
        customer_grades: toCustomerDictionaryOptions(grades),
      }
    } else {
      options.value = legacyOptions
      if (publishedResult.status === 'rejected') {
        ElMessage.warning('统一配置暂时不可用，当前页面已回退到兼容选项。')
      }
    }
  } catch (error) {
    if (!options.value) ElMessage.error(`筛选选项加载失败：${getErrorMessage(error)}`)
    else ElMessage.warning('统一配置暂时不可用，当前页面已回退到兼容选项。')
  } finally {
    optionsLoading.value = false
  }
}

function searchCustomers() {
  Object.assign(appliedFilters, filters)
  page.value = 1
  void loadRows()
}

function handleSearchEnter(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  searchCustomers()
}

function clearFilterValues() {
  Object.assign(filters, {
    q: '',
    customer_grade: '',
    country_code: '',
    activity_status: '',
  })
}

function resetFilters() {
  clearFilterValues()
  Object.assign(appliedFilters, filters)
  page.value = 1
  ordering.value = '-updated_at'
  void loadRows()
}

async function handleExport() {
  exportLoading.value = true
  try {
    const blob = await exportCustomers(buildQuery())
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `客户列表_${new Date().toISOString().slice(0, 10)}.csv`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('客户列表已导出。')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    exportLoading.value = false
  }
}

function handleSortChange(event: { prop: string; order: 'ascending' | 'descending' | null }) {
  const supported: Record<string, string> = {
    account_code: 'account_code',
    account_name: 'account_name',
    updated_at: 'updated_at',
  }
  const field = supported[event.prop]
  ordering.value = event.order && field
    ? `${event.order === 'descending' ? '-' : ''}${field}` as CustomerOrdering
    : '-updated_at'
  page.value = 1
  void loadRows()
}

function handlePageSizeChange() {
  page.value = 1
  void loadRows()
}

function formatCountry(code: string): string {
  if (!code) return '—'
  try {
    return new Intl.DisplayNames(['zh-CN'], { type: 'region' }).of(code) || code
  } catch {
    return code
  }
}

function formatCustomerGrade(itemCode?: string, fallback = ''): string {
  if (!itemCode) return '未评级'
  const grade = options.value?.customer_grades.find((item) => item.item_code === itemCode)
  const chineseName = grade?.description?.trim()
  if (chineseName) return `${itemCode}（${chineseName}）`
  return grade?.display_name || fallback || itemCode
}

function formatAmount(value: string | null | undefined, currencyCode: string): string {
  if (value === null || value === undefined || value === '') return '未录入'
  const matched = value.trim().match(/^(-?)(\d+)(?:\.(\d+))?$/)
  if (!matched) return `${currencyCode} ${value}`.trim()
  const [, sign, integer, fraction = ''] = matched
  const groupedInteger = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const normalizedFraction = fraction.replace(/0+$/, '')
  const displayValue = `${sign}${groupedInteger}${normalizedFraction ? `.${normalizedFraction}` : ''}`
  return `${currencyCode} ${displayValue}`.trim()
}

function formatBusinessValue(row: CustomerListItem): string {
  if (row.last_12m_sales_amount === null) return '—'
  return formatAmount(row.last_12m_sales_amount, 'CNY')
}

function businessValueTooltip(row: CustomerListItem): string {
  if (row.last_12m_sales_amount === null) return '近12个月暂无有效销售订单'
  return `由 ${row.last_12m_sales_order_count || 0} 张有效销售订单按汇率折算为人民币`
}

function recentOrderTooltip(row: CustomerListItem): string {
  const order = row.recent_order
  if (!order) return '暂无有效销售订单'
  return `${order.order_number}·${order.status_display}·${formatAmount(order.total_amount, order.currency_code)}`
}

function openCustomerDetail(customerId: string) {
  void router.push({ name: 'customer-detail', params: { customerId } })
}

function openCustomerEdit(customerId: string) {
  if (!canChangeCustomer.value) return
  editingCustomerId.value = customerId
  editDialogVisible.value = true
}

function openCustomerCreate() {
  createDialogVisible.value = true
}

function handleCustomerCreated(customerId: string, continueCreating: boolean) {
  void loadRows()
  if (!continueCreating) openCustomerDetail(customerId)
}

function handleRowAction(command: string | number | object, row: CustomerListItem) {
  if (command === 'detail') openCustomerDetail(row.id)
  else if (command === 'edit') openCustomerEdit(row.id)
  else if (command === 'delete') void deleteCustomerRow(row)
}

async function deleteCustomerRow(row: CustomerListItem) {
  try {
    const current = await fetchCustomer(row.id)
    await ElMessageBox.confirm(
      `确定永久删除客户「${current.data.account_name}」吗？其联系人、询盘、报价、样品、任务及关联业务数据会一并删除，且无法恢复。`,
      '永久删除客户',
      {
        type: 'error',
        confirmButtonText: '确认永久删除',
        cancelButtonText: '取消',
        customClass: 'customer-list-message-box',
      },
    )
    const result = await deleteCustomer(row.id, current.etag || '')
    ElMessage.success(`客户已永久删除，同时删除 ${result.deleted_count} 条关联数据。`)
    await loadRows()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  }
}

onMounted(async () => {
  await Promise.all([loadOptions(), loadRows()])
})

onBeforeUnmount(() => { latestRowsRequest += 1 })
</script>

<template>
  <div
    class="customer-list-page erp-glass-list"
    data-customer-list-page
    :style="{ '--customer-sort-icon': `url(${sortCustomerIcon})` }"
  >
    <section v-glass-spotlight class="erp-list-filter" aria-label="筛选客户">
      <CrmPageHeader class="erp-list-heading" title="客户列表" />
      <form class="erp-list-filters" @submit.prevent="searchCustomers">
        <ElInput
          v-model="filters.q"
          class="filter-control filter-control--search"
          aria-label="搜索客户名称、编号、英文名或简称"
          placeholder="搜索名称、编号等"
          clearable
          @keydown.enter="handleSearchEnter"
          @clear="searchCustomers"
        >
          <template #suffix>
            <button type="button" class="customer-search-button erp-list-search-button" aria-label="搜索客户" @click="searchCustomers">
              <img :src="searchIcon" alt="" aria-hidden="true" />
            </button>
          </template>
        </ElInput>

        <ElSelect
          v-model="filters.activity_status"
          class="filter-control filter-control--status"
          aria-label="客户状态"
          placeholder="客户状态：全部"
          clearable
          :loading="optionsLoading"
        >
            <ElOption v-for="item in options?.activity_statuses" :key="item.item_code" :label="item.display_name" :value="item.item_code" />
        </ElSelect>

        <ElSelect
          v-model="filters.customer_grade"
          class="filter-control filter-control--grade"
          aria-label="客户等级"
          placeholder="等级：全部"
          clearable
          :loading="optionsLoading"
        >
            <ElOption v-for="item in options?.customer_grades" :key="item.id" :label="formatCustomerGrade(item.item_code, item.display_name)" :value="item.item_code" />
        </ElSelect>

        <ElSelect
          v-model="filters.country_code"
          class="filter-control filter-control--country"
          aria-label="国家或地区"
          placeholder="国家/地区：全部"
          clearable
          filterable
          :loading="optionsLoading"
        >
            <ElOption v-for="item in options?.country_options" :key="item.item_code" :label="`${item.display_name}（${item.item_code}）`" :value="item.item_code" />
        </ElSelect>

        <div class="erp-list-filter-actions">
          <ElButton class="erp-button-motion" data-reset-customer-filters @click="resetFilters">重置</ElButton>
          <ElButton class="erp-button-motion" type="primary" data-apply-customer-filters @click="searchCustomers">应用筛选</ElButton>
        </div>
      </form>
    </section>

    <section class="erp-list-data" aria-label="客户数据列表">
      <div class="erp-list-toolbar" data-customer-toolbar>
        <ElButton class="filter-action filter-action--create erp-button-motion" type="primary" :icon="Plus" @click="openCustomerCreate">
          新建客户
        </ElButton>
        <ElButton class="filter-action filter-action--export erp-button-motion" :loading="exportLoading" @click="handleExport">
          <img v-if="!exportLoading" class="button-icon" :src="exportIcon" alt="" aria-hidden="true" />
          导出
        </ElButton>
      </div>
      <div v-if="errorMessage" class="data-state data-state--error" role="alert">
        <strong>客户列表加载失败</strong>
        <p>{{ errorMessage }}</p>
        <ElButton type="primary" :icon="Refresh" @click="loadRows">重新加载</ElButton>
      </div>
      <template v-else>
        <div class="erp-list-table-frame">
          <ElTable
            v-loading="loading"
            element-loading-text="正在加载客户数据…"
            :data="rows"
            row-key="id"
            table-layout="fixed"
            border
            empty-text=""
            height="100%"
            :aria-busy="loading"
            @sort-change="handleSortChange"
          >
            <ElTableColumn prop="account_name" min-width="245" sortable="custom">
              <template #header>
                <span class="sortable-header">客户名称<img :src="sortCustomerIcon" alt="" aria-hidden="true" /></span>
              </template>
              <template #default="{ row }">
                <CustomerIdentityCell :customer="row" @open="openCustomerDetail(row.id)" />
              </template>
            </ElTableColumn>
            <ElTableColumn label="国家/地区" width="115">
              <template #default="{ row }"><CustomerCountryCell :country-code="row.primary_country_code" :country-name="formatCountry(row.primary_country_code)" /></template>
            </ElTableColumn>
            <ElTableColumn label="等级" width="90">
              <template #default="{ row }"><span class="grade-value">{{ formatCustomerGradeCell(row.customer_grade?.item_code) }}</span></template>
            </ElTableColumn>
            <ElTableColumn label="客户状态" width="115">
              <template #default="{ row }"><CustomerActivityTag :activity="row.activity" /></template>
            </ElTableColumn>
            <ElTableColumn label="负责人" width="120">
              <template #default="{ row }">
                <ElTooltip :content="row.primary_owner?.display_name || '未分配'" placement="top" :show-after="300">
                  <span class="owner-name">{{ row.primary_owner?.display_name || '—' }}</span>
                </ElTooltip>
              </template>
            </ElTableColumn>
            <ElTableColumn width="160">
              <template #header>
                <span class="sortable-header">近12个月销售额<img :src="sortCustomerIcon" alt="" aria-hidden="true" /></span>
              </template>
              <template #default="{ row }">
                <ElTooltip :content="businessValueTooltip(row)" placement="top" :show-after="300">
                  <strong class="business-value">{{ formatBusinessValue(row) }}</strong>
                </ElTooltip>
              </template>
            </ElTableColumn>
            <ElTableColumn label="最近订单" width="120">
              <template #default="{ row }">
                <ElTooltip :content="recentOrderTooltip(row)" placement="top" :show-after="300">
                  <span class="date-value">{{ row.recent_order ? formatDate(row.recent_order.order_date) : '—' }}</span>
                </ElTooltip>
              </template>
            </ElTableColumn>
            <ElTableColumn label="最近联系" width="120">
              <template #default="{ row }"><span class="date-value">{{ formatDate(row.last_contact_at) }}</span></template>
            </ElTableColumn>
            <ElTableColumn label="下次跟进" width="125">
              <template #default="{ row }">
                <span class="date-value">{{ row.next_follow_up_at ? formatDate(row.next_follow_up_at) : '未安排' }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="跟进状态" width="135">
              <template #default="{ row }">
                <CustomerActivityTag
                  :label="getFollowUpStatus(row.next_follow_up_at).label"
                  :tone="getFollowUpStatus(row.next_follow_up_at).tone"
                  :title="getFollowUpStatus(row.next_follow_up_at).title"
                />
              </template>
            </ElTableColumn>
            <ElTableColumn label="风险" width="120">
              <template #default="{ row }">
                <CustomerActivityTag
                  v-if="getRiskStatus(row.activity)"
                  :label="getRiskStatus(row.activity)?.label"
                  :tone="getRiskStatus(row.activity)?.tone"
                  :title="getRiskStatus(row.activity)?.title"
                />
                <span v-else class="risk-placeholder">—</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="操作" width="80" fixed="right" align="center">
              <template #default="{ row }">
                <ElDropdown :persistent="false" trigger="click" placement="bottom-end" @command="handleRowAction($event, row)">
                  <ElButton class="row-action-button" text :aria-label="`打开 ${row.account_name} 的操作菜单`">
                    <span class="row-action-dots" aria-hidden="true"><i /><i /><i /></span>
                  </ElButton>
                  <template #dropdown>
                    <ElDropdownMenu>
                      <ElDropdownItem command="detail">详情</ElDropdownItem>
                      <ElDropdownItem v-if="canChangeCustomer && authStore.canFor('customers.change_customeraccount', row)" command="edit">编辑</ElDropdownItem>
                      <ElDropdownItem v-if="canDeleteCustomer && authStore.canFor('customers.delete_customeraccount', row)" command="delete" divided>永久删除</ElDropdownItem>
                    </ElDropdownMenu>
                  </template>
                </ElDropdown>
              </template>
            </ElTableColumn>
            <template #empty>
              <div v-if="!loading" class="empty-state">
                <ElIcon :size="24"><Search /></ElIcon>
                <strong>{{ hasActiveFilters ? '没有符合当前条件的客户' : '暂无客户数据' }}</strong>
                <p>{{ hasActiveFilters ? '可调整筛选条件后重新查询。' : '可使用“新建客户”开始建档。' }}</p>
                <ElButton v-if="hasActiveFilters" @click="resetFilters">清除筛选</ElButton>
                <ElButton v-else type="primary" @click="openCustomerCreate">新建客户</ElButton>
              </div>
            </template>
          </ElTable>
        </div>
        <footer class="erp-list-footer">
          <ElPagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[20, 50, 100]"
            :pager-count="5"
            layout="sizes, prev, pager, next"
            @current-change="loadRows"
            @size-change="handlePageSizeChange"
          />
        </footer>
      </template>
    </section>

    <CustomerCreateDialog v-model="createDialogVisible" @created="handleCustomerCreated" @open-existing="openCustomerDetail" />
    <CustomerEditDialog v-model="editDialogVisible" :customer-id="editingCustomerId" @saved="loadRows" @cancelled="loadRows" />
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/crm/mixins' as mixin;

.customer-list-page {
  display: flex;
  flex-direction: column;
  min-width: 0;
  box-sizing: border-box;
  width: auto;
  height: 100%;
  min-height: 0;
  gap: 14px;
  margin: 0;
  padding: 0;
  overflow: hidden;
  color: var(--erp-color-text-regular);
  background: transparent;
  font-family: token.$crm-font-body;
}

.customer-list-page :deep(.el-button) {
  height: 32px;
  min-height: 32px;
  border-radius: var(--erp-radius-control);
  font-family: token.$crm-font-body;
  font-size: 13px;
  font-weight: 500;
}

.customer-list-page :deep(.el-button > span) {
  gap: 8px;
}

.filter-control {
  height: 32px;
  flex: none;
}

.filter-control--search { width: min(250px, 100%); min-width: 0; }
.filter-control--status { width: 128px; }
.filter-control--grade { width: 120px; }
.filter-control--country { width: 140px; }

.customer-search-button {
  @include mixin.reset-button;
}

.customer-search-button:focus-visible {
  @include mixin.focus-ring;
}

.filter-action {
  height: 32px;
  margin: 0;
  padding: 0 8px;
}

.filter-action--export { width: 76px; }
.filter-action--create { width: 112px; }

.button-icon {
  display: block;
  width: 16px;
  height: 16px;
  flex: none;
}

.customer-list-page .erp-list-table-frame :deep(.el-table__header-wrapper th.el-table__cell),
.customer-list-page .erp-list-table-frame :deep(.el-table__header-wrapper th.el-table__cell > .cell) {
  color: var(--erp-table-header-text) !important;
  font-size: 11px;
  font-weight: 500;
  line-height: 16px;
  letter-spacing: 0;
}

.customer-list-page .erp-list-table-frame :deep(.el-table__header-wrapper th.el-table__cell > .cell) {
  padding-right: 16px;
  padding-left: 16px;
}

.customer-list-page .erp-list-table-frame :deep(.customer-identity__name),
.customer-list-page .erp-list-table-frame :deep(.customer-identity:hover .customer-identity__name) {
  color: var(--erp-table-text);
}

.customer-list-page .erp-list-table-frame :deep(.caret-wrapper) {
  display: none;
}

.customer-list-page .erp-list-table-frame :deep(.el-table__fixed-right),
.customer-list-page .erp-list-table-frame :deep(.el-table__fixed) {
  box-shadow: none;
}

.customer-list-page .erp-list-table-frame :deep(.el-scrollbar__bar.is-horizontal) {
  bottom: 2px;
  height: 6px;
  opacity: 0.45 !important;
}

.sortable-header {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
}

.sortable-header img {
  width: 10px;
  height: 14px;
  flex: none;
}

.grade-value,
.owner-name,
.date-value,
.business-value {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.grade-value {
  color: var(--erp-table-text);
  font-size: 12px;
  font-weight: 500;
  line-height: 20px;
}

.owner-name {
  color: var(--erp-table-text);
  font-size: 12px;
  font-weight: 400;
  line-height: 20px;
}

.date-value {
  color: var(--erp-table-text);
  font-size: 13px;
  line-height: 18px;
}

.business-value {
  color: var(--erp-table-text);
  font-size: 13px;
  font-weight: 700;
  line-height: 20px;
  font-variant-numeric: tabular-nums;
}

.risk-placeholder {
  color: var(--erp-table-text);
}

.row-action-button {
  min-width: 32px;
  width: 32px;
  height: 32px;
  padding: 0 !important;
  border: 0 !important;
  color: var(--erp-table-text) !important;
  background: transparent !important;
  font-size: 0 !important;
}

.customer-list-page .erp-list-table-frame :deep(.el-button.row-action-button) {
  box-shadow: none;
}

.row-action-dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.row-action-dots i {
  display: block;
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: currentColor;
}

.empty-state,
.data-state {
  display: flex;
  min-height: 0;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  text-align: center;
}

.empty-state { gap: 4px; }

.empty-state strong,
.data-state strong {
  margin-top: 8px;
  font-size: 14px;
  font-weight: 600;
}

.empty-state p,
.data-state p {
  margin: 0 0 12px;
  font-size: 12px;
  line-height: 18px;
}

.data-state--error {
  flex: 1;
  margin-bottom: 16px;
  padding: 24px;
  border-radius: token.$crm-radius-2;
  color: var(--erp-color-danger);
  background: var(--erp-color-danger-soft);
}

.erp-list-data .empty-state {
  color: var(--erp-table-text);
}

.erp-list-data .empty-state strong {
  color: var(--erp-table-text);
}

:global(.customer-list-message-box .el-button) {
  height: 32px;
  min-height: 32px;
  margin: 0;
  border-color: var(--erp-color-border);
  border-radius: token.$crm-radius-2;
  color: var(--erp-color-text-primary);
  background: var(--erp-color-surface);
  font-family: token.$crm-font-body;
  font-size: 13px;
  font-weight: 500;
}

:global(.customer-list-message-box .el-button + .el-button) {
  margin-left: 8px;
}

:global(.customer-list-message-box .el-button--primary) {
  border-color: var(--erp-button-primary-border);
  color: var(--erp-color-text-inverse);
  background: var(--erp-button-primary-surface);
}

:global(.customer-list-message-box .el-button--primary:hover),
:global(.customer-list-message-box .el-button--primary:focus-visible) {
  border-color: var(--erp-button-primary-border);
  background: var(--erp-button-primary-hover-surface);
}

:global(.customer-list-message-box) {
  border-color: var(--erp-color-border);
  border-radius: token.$crm-radius-2;
  background: var(--erp-color-surface);
  --el-color-primary: var(--erp-color-brand);
}
</style>
