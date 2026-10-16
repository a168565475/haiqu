<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
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
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchCustomers(buildQuery())
    rows.value = result.data
    total.value = result.meta.total
    if (page.value > result.meta.total_pages && result.meta.total_pages > 0) {
      page.value = result.meta.total_pages
      await loadRows()
    }
  } catch (error) {
    rows.value = []
    total.value = 0
    errorMessage.value = getErrorMessage(error)
  } finally {
    loading.value = false
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

function openCustomerContacts(customerId: string) {
  void router.push({ name: 'customer-contacts', params: { customerId } })
}

function openCustomerDetail(customerId: string) {
  void router.push({ name: 'customer-detail', params: { customerId } })
}

function openCustomerEdit(customerId: string) {
  void router.push({ name: 'customer-edit', params: { customerId } })
}

function openCustomerCreate() {
  void router.push({ name: 'customer-create' })
}

function handleRowAction(command: string | number | object, row: CustomerListItem) {
  if (command === 'detail') openCustomerDetail(row.id)
  else if (command === 'edit') openCustomerEdit(row.id)
  else if (command === 'contacts') openCustomerContacts(row.id)
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
</script>

<template>
  <div
    class="customer-list-page"
    data-customer-list-page
    :style="{ '--customer-sort-icon': `url(${sortCustomerIcon})` }"
  >
    <section class="filter-panel" aria-label="筛选客户">
      <CrmPageHeader title="客户列表" :count="total" count-label="个客户" />
      <form class="filter-grid" @submit.prevent="searchCustomers">
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
            <button type="button" class="customer-search-button" aria-label="搜索客户" @click="searchCustomers">
              <img class="field-icon" :src="searchIcon" alt="" aria-hidden="true" />
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

        <div class="filter-actions">
          <ElButton data-reset-customer-filters @click="resetFilters">重置</ElButton>
          <ElButton type="primary" data-apply-customer-filters @click="searchCustomers">应用筛选</ElButton>
        </div>
      </form>
    </section>

    <section class="data-surface is-dense" aria-label="客户数据列表">
      <div class="customer-actions" data-customer-toolbar>
        <ElButton class="filter-action filter-action--create" type="primary" :icon="Plus" @click="openCustomerCreate">
          新建客户
        </ElButton>
        <ElButton class="filter-action filter-action--export" :loading="exportLoading" @click="handleExport">
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
        <div class="customer-table-frame">
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
                      <ElDropdownItem command="detail">查看详情</ElDropdownItem>
                      <ElDropdownItem v-if="canChangeCustomer && authStore.canFor('customers.change_customeraccount', row)" command="edit">编辑客户资料</ElDropdownItem>
                      <ElDropdownItem command="contacts">联系人</ElDropdownItem>
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
        <footer class="table-footer">
          <span class="table-footer__total">共 {{ total.toLocaleString() }} 条</span>
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

  </div>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/crm/mixins' as mixin;

.customer-list-page {
  min-width: 0;
  min-height: calc(100vh - 56px);
  box-sizing: border-box;
  margin: 0;
  padding: 24px;
  color: token.$crm-text-regular;
  background: token.$crm-color-page;
  font-family: token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary};
  --el-color-primary-light-3: #{token.$crm-primary-light-3};
  --el-color-primary-light-5: #{token.$crm-primary-light-5};
  --el-color-primary-light-7: #{token.$crm-primary-light-7};
  --el-color-primary-light-8: #{token.$crm-primary-light-8};
  --el-color-primary-light-9: #{token.$crm-color-selected};
  --el-color-primary-dark-2: #{token.$crm-primary-pressed};
  --el-border-color: #{token.$crm-border-default};
  --el-border-color-light: #{token.$crm-border-default};
  --el-border-color-lighter: #{token.$crm-color-subtle};
  --el-fill-color-light: #{token.$crm-color-subtle};
  --el-fill-color-lighter: #{token.$crm-color-surface};
  --el-fill-color-blank: #{token.$crm-color-elevated};
  --el-text-color-primary: #{token.$crm-text-primary};
  --el-text-color-regular: #{token.$crm-text-regular};
  --el-text-color-secondary: #{token.$crm-text-secondary};
  --el-text-color-placeholder: #{token.$crm-text-muted};
  --el-border-radius-base: #{token.$crm-radius-2};
  --el-border-radius-small: #{token.$crm-radius-1};
}

.crm-page-header { margin-bottom: token.$crm-space-4; }
.customer-list-page :deep(.el-button--primary) { border-color: token.$crm-primary; background: token.$crm-primary; }
.customer-list-page :deep(.el-button--primary:hover),
.customer-list-page :deep(.el-button--primary:focus-visible) { border-color: token.$crm-primary-hover; background: token.$crm-primary-hover; }

.filter-panel {
  margin-bottom: token.$crm-space-2;
  padding: token.$crm-space-3;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
}

.filter-grid {
  display: grid;
  grid-template-columns: minmax(220px, 1.55fr) repeat(4, minmax(120px, 0.9fr)) auto auto;
  align-items: end;
  gap: token.$crm-space-3;
}

.filter-field { display: flex; min-width: 0; flex-direction: column; gap: token.$crm-space-1; }
.filter-field > span { color: token.$crm-text-secondary; font-size: 11px; line-height: 16px; }
.filter-field :deep(.el-input), .filter-field :deep(.el-select) { width: 100%; }
.filter-field :deep(.el-input__wrapper), .filter-field :deep(.el-select__wrapper) { min-height: token.$crm-control-height; border-radius: token.$crm-radius-2; box-shadow: 0 0 0 1px token.$crm-border-strong inset; }
.filter-field :deep(.el-input__wrapper:hover), .filter-field :deep(.el-select__wrapper:hover) { box-shadow: 0 0 0 1px token.$crm-text-muted inset; }
.filter-field--more :deep(.el-button) { height: token.$crm-control-height; margin: 0; border-radius: token.$crm-radius-2; }

.filter-actions { display: flex; height: token.$crm-control-height; align-items: stretch; gap: token.$crm-space-1; }
.filter-actions :deep(.el-button) { height: token.$crm-control-height; margin: 0; border-radius: token.$crm-radius-2; }
.filter-actions :deep(.el-button--primary) { min-width: 72px; }
.filter-actions :deep(.el-button.is-text) { min-width: 48px; padding: 0 token.$crm-space-2; }

.active-filters {
  display: flex;
  min-height: 24px;
  align-items: center;
  flex-wrap: wrap;
  gap: token.$crm-space-1;
  margin-top: token.$crm-space-2;
  padding-top: token.$crm-space-2;
  border-top: 1px solid token.$crm-border-default;
}

.active-filters__label { margin-right: token.$crm-space-1; color: token.$crm-text-muted; font-size: 11px; }
.active-filters :deep(.el-tag) { height: 24px; border-color: token.$crm-border-strong; border-radius: token.$crm-radius-2; color: token.$crm-text-regular; background: token.$crm-color-elevated; }
.active-filters :deep(.el-button) { height: 24px; margin-left: token.$crm-space-1; padding: 0 token.$crm-space-2; color: token.$crm-primary-hover; }

.action-arrow { margin-left: token.$crm-space-1; }

.data-surface {
  min-width: 0;
  overflow: hidden;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-elevated;
}

.data-surface :deep(.el-table) {
  color: token.$crm-text-regular;
  font-size: 12px;
  --el-table-border-color: #{token.$crm-border-default};
  --el-table-header-bg-color: #{token.$crm-color-subtle};
  --el-table-row-hover-bg-color: #{token.$crm-color-surface};
  --el-table-current-row-bg-color: #{token.$crm-color-selected};
}

.data-surface :deep(.el-table__header th.el-table__cell) { height: 40px; padding: 0; color: token.$crm-text-secondary; background: token.$crm-color-subtle; font-size: 11px; font-weight: 600; letter-spacing: 0.02em; }
.data-surface :deep(.el-table__row td.el-table__cell) { height: token.$crm-table-row-comfortable; padding: 0; border-bottom-color: token.$crm-color-subtle; }
.data-surface.is-dense :deep(.el-table__row td.el-table__cell) { height: token.$crm-table-row-compact; }
.data-surface :deep(.el-table .cell) { padding: 0 token.$crm-space-3; line-height: 20px; }
.data-surface :deep(.el-table__fixed-right), .data-surface :deep(.el-table__fixed) { box-shadow: none; }
.data-surface :deep(.el-table__inner-wrapper::before) { display: none; }
.data-surface :deep(.el-scrollbar__bar.is-horizontal) { bottom: 2px; height: 6px; opacity: 0.55 !important; }
.data-surface :deep(.el-scrollbar__thumb) { background: token.$crm-text-muted; }

.grade-value, .owner-name, .date-value { @include mixin.text-ellipsis; display: block; }
.owner-name, .date-value { color: token.$crm-text-secondary; }
.business-value, .follow-up-value { display: flex; min-width: 0; flex-direction: column; }
.business-value strong { @include mixin.text-ellipsis; color: token.$crm-text-primary; font-size: 12px; font-weight: 600; line-height: 18px; font-variant-numeric: tabular-nums; }
.business-value span { @include mixin.text-ellipsis; color: token.$crm-text-muted; font-size: 10px; line-height: 15px; }
.follow-up-value { color: token.$crm-text-secondary; line-height: 18px; }
.follow-up-value small { color: token.$crm-danger; font-size: 10px; line-height: 14px; }
.follow-up-value.is-overdue { color: token.$crm-danger; font-weight: 500; }

.empty-state, .data-state {
  display: flex;
  min-height: 280px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  color: token.$crm-text-muted;
  text-align: center;
}

.empty-state { gap: token.$crm-space-1; }
.empty-state strong, .data-state strong { margin-top: token.$crm-space-2; color: token.$crm-text-primary; font-size: 14px; font-weight: 600; }
.empty-state p, .data-state p { margin: 0 0 token.$crm-space-3; font-size: 12px; line-height: 18px; }
.data-state--error { min-height: calc(100vh - 366px); padding: token.$crm-space-6; background: token.$crm-danger-soft; }
.data-state--error strong, .data-state--error p { color: token.$crm-danger; }

.table-footer {
  display: flex;
  min-height: 48px;
  box-sizing: border-box;
  align-items: center;
  justify-content: space-between;
  gap: token.$crm-space-4;
  padding: token.$crm-space-2 token.$crm-space-4;
  border-top: 1px solid token.$crm-border-default;
  color: token.$crm-text-muted;
  background: token.$crm-color-surface;
  font-size: 11px;
}

.table-footer :deep(.el-pagination) { --el-pagination-button-width: 28px; --el-pagination-button-height: 28px; gap: token.$crm-space-1; }
.table-footer :deep(.el-pagination button), .table-footer :deep(.el-pager li) { min-width: 28px; height: 28px; border-radius: token.$crm-radius-2; }
.table-footer :deep(.el-pager li.is-active) { color: token.$crm-text-inverse; background: token.$crm-primary; }

@media (max-width: 1280px) {
  .filter-grid { grid-template-columns: minmax(220px, 1.5fr) repeat(3, minmax(130px, 1fr)) auto; }
  .filter-field--more, .filter-actions { grid-row: 2; }
}

@media (max-width: 900px) {
  .filter-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filter-field--more, .filter-actions { grid-row: auto; }
}

@media (max-width: 768px) {
  .customer-list-page { margin: 0; padding: 16px; }
  .filter-grid { grid-template-columns: 1fr; }
  .filter-actions { justify-content: flex-end; }
}

/* 2026-10-16：独立筛选/内容卡片，保留客户表格既有样式。 */
.customer-list-page {
  display: flex;
  flex-direction: column;
  width: auto;
  height: 100%;
  min-height: 0;
  gap: 14px;
  margin: 0;
  padding: 0;
  overflow: hidden;
  color: token.$crm-text-regular;
  background: token.$crm-color-page;
}

.crm-page-header {
  flex: none;
  margin: 0 0 12px;
}

.customer-list-page :deep(.el-button) {
  height: 32px;
  min-height: 32px;
  border-color: token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  font-family: token.$crm-font-body;
  font-size: 13px;
  font-weight: 500;
}

.customer-list-page :deep(.el-button > span) {
  gap: 8px;
}

.customer-list-page :deep(.el-button:hover),
.customer-list-page :deep(.el-button:focus-visible) {
  border-color: token.$crm-border-strong;
  color: token.$crm-text-primary;
  background: token.$crm-color-subtle;
}

.customer-list-page :deep(.el-button:active) {
  border-color: token.$crm-primary;
  background: token.$crm-color-selected;
}

.customer-list-page :deep(.el-button.is-disabled) {
  border-color: token.$crm-border-default;
  color: token.$crm-text-muted;
  background: token.$crm-color-surface;
  opacity: 0.55;
}

.customer-list-page :deep(.el-button--primary),
.customer-list-page :deep(.el-button--primary:hover),
.customer-list-page :deep(.el-button--primary:focus-visible) {
  border-color: token.$crm-primary;
  color: token.$crm-text-inverse;
  background: token.$crm-primary;
}

.customer-list-page :deep(.el-button--primary:hover),
.customer-list-page :deep(.el-button--primary:focus-visible) {
  border-color: token.$crm-primary-hover;
  background: token.$crm-primary-hover;
}

.customer-list-page :deep(.el-button--primary:active) {
  border-color: token.$crm-primary-pressed;
  background: token.$crm-primary-pressed;
}

.customer-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 8px;
  margin: 0 0 12px;
}

.filter-action {
  height: 32px;
  margin: 0;
  padding: 0 8px;
}

.filter-action--export {
  width: 76px;
}

.filter-action--create {
  width: 112px;
}

.button-icon,
.field-icon {
  display: block;
  width: 16px;
  height: 16px;
  flex: none;
}

.filter-panel {
  height: auto;
  min-height: 32px;
  flex: none;
  margin: 0;
  padding: 16px;
  border: 0;
  border-radius: 10px;
  background: token.$crm-color-surface;
}

.filter-grid {
  display: flex;
  height: auto;
  min-height: 32px;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 8px;
}

.filter-control {
  height: 32px;
  flex: none;
}

.filter-control--search { width: min(250px, 100%); min-width: 0; flex: none; }
.filter-control--status { width: 128px; }
.filter-control--grade { width: 120px; }
.filter-control--country { width: 140px; }

.customer-search-button {
  @include mixin.reset-button;
  display: inline-flex;
  width: 24px;
  height: 30px;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.customer-search-button:focus-visible { @include mixin.focus-ring; }

.filter-control :deep(.el-input__wrapper),
.filter-control :deep(.el-select__wrapper) {
  min-height: 32px;
  box-sizing: border-box;
  padding: 0 12px;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  box-shadow: 0 0 0 1px token.$crm-border-default inset;
}

.filter-control :deep(.el-input__wrapper:hover),
.filter-control :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px token.$crm-border-strong inset;
}

.filter-control :deep(.el-input__wrapper.is-focus),
.filter-control :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1px token.$crm-focus inset, 0 0 0 2px rgba(56, 152, 236, 0.18);
}

.filter-control :deep(.el-input__inner),
.filter-control :deep(.el-select__placeholder),
.filter-control :deep(.el-select__selected-item) {
  color: token.$crm-text-secondary;
  font-size: 12px;
  line-height: 18px;
}

.filter-control :deep(.el-input__inner::placeholder) {
  color: token.$crm-text-muted;
}

.filter-actions {
  flex: none;
  margin-left: auto;
  gap: 8px;
}

.data-surface {
  display: flex;
  width: 100%;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  margin: 0;
  padding: 16px 16px 0;
  border: 0;
  border-radius: 10px;
  background: token.$crm-color-surface;
}

/* 外围四边只由此容器绘制，表格保留内部网格。 */
.customer-table-frame {
  min-height: 0;
  flex: 1;
  overflow: hidden;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
}

.customer-table-frame :deep(.el-table::before),
.customer-table-frame :deep(.el-table::after),
.customer-table-frame :deep(.el-table__inner-wrapper::before),
.customer-table-frame :deep(.el-table__inner-wrapper::after),
.customer-table-frame :deep(.el-table__border-left-patch),
.customer-table-frame :deep(.el-table__border-right-patch),
.customer-table-frame :deep(.el-table__border-bottom-patch) {
  display: none;
}

.customer-table-frame :deep(tr > .el-table__cell:last-child) {
  border-right: 0;
}

.customer-table-frame :deep(.el-table__body tr:last-child > td.el-table__cell) {
  border-bottom: 0;
}

.data-surface :deep(.el-table) {
  color: token.$crm-text-regular;
  background: token.$crm-color-surface;
  font-family: token.$crm-font-body;
  font-size: 12px;
  --el-table-border-color: #{token.$crm-border-subtle};
  --el-table-header-bg-color: #{token.$crm-color-subtle};
  --el-table-row-hover-bg-color: #{token.$crm-color-row-hover};
  --el-table-current-row-bg-color: #{token.$crm-color-selected};
}

.data-surface :deep(.el-table__header th.el-table__cell) {
  height: token.$crm-table-header-height;
  padding: 0;
  border-bottom-color: token.$crm-border-subtle;
  color: token.$crm-text-secondary;
  background: token.$crm-color-subtle;
  font-size: 11px;
  font-weight: 500;
  line-height: 16px;
  letter-spacing: 0;
}

.data-surface :deep(.el-table__header .cell) {
  color: token.$crm-text-secondary;
  font-size: 11px;
  font-weight: 500;
  line-height: 16px;
}

.data-surface :deep(.el-table__row td.el-table__cell) {
  height: token.$crm-table-row-comfortable;
  padding: 0;
  border-bottom-color: token.$crm-border-subtle;
  background: token.$crm-color-surface;
}

.data-surface :deep(.el-table__body .cell) {
  color: token.$crm-text-primary;
  font-size: 12px;
  font-weight: 400;
  line-height: 18px;
}

.data-surface.is-dense :deep(.el-table__row td.el-table__cell) {
  height: 40px;
}

.data-surface :deep(.el-table__row:hover td.el-table__cell),
.data-surface :deep(.el-table__row.current-row td.el-table__cell) {
  background: token.$crm-color-row-hover;
}

.data-surface :deep(.el-table .cell) {
  padding: 0 16px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.data-surface :deep(.caret-wrapper) {
  display: none;
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
  color: token.$crm-text-primary;
  font-size: 12px;
  font-weight: 500;
  line-height: 20px;
}

.owner-name {
  color: token.$crm-text-primary;
  font-size: 12px;
  font-weight: 400;
  line-height: 20px;
}

.date-value {
  color: token.$crm-text-regular;
  font-size: 13px;
  line-height: 18px;
}

.business-value {
  color: token.$crm-text-primary;
  font-size: 13px;
  font-weight: 700;
  line-height: 20px;
  font-variant-numeric: tabular-nums;
}

.risk-placeholder {
  color: token.$crm-text-muted;
}

.row-action-button {
  min-width: 32px;
  width: 32px;
  height: 32px;
  padding: 0 !important;
  border: 0 !important;
  color: token.$crm-text-secondary !important;
  background: transparent !important;
  font-size: 0 !important;
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

.data-surface :deep(.el-table__fixed-right),
.data-surface :deep(.el-table__fixed) {
  box-shadow: none;
}

.data-surface :deep(.el-scrollbar__bar.is-horizontal) {
  bottom: 2px;
  height: 6px;
  opacity: 0.45 !important;
}

.empty-state,
.data-state {
  min-height: 0;
}

.data-state {
  flex: 1;
  margin-bottom: 16px;
  border-radius: token.$crm-radius-2;
}

.table-footer {
  width: 100%;
  height: 40px;
  min-height: 40px;
  flex: none;
  align-items: center;
  padding: 0;
  border-top: 0;
  color: token.$crm-text-secondary;
  background: token.$crm-color-surface;
  font-size: 12px;
}

.table-footer__total {
  padding-bottom: 0;
  line-height: 18px;
  white-space: nowrap;
}

.table-footer :deep(.el-pagination) {
  height: 28px;
  gap: 6px;
  --el-pagination-button-width: 28px;
  --el-pagination-button-height: 28px;
}

.table-footer :deep(.el-pagination__sizes) {
  width: 112px;
  margin-right: 2px;
}

.table-footer :deep(.el-pagination__sizes .el-select) {
  width: 112px;
}

.table-footer :deep(.el-pagination__sizes .el-select__wrapper) {
  height: 28px;
  min-height: 28px;
  padding: 0 8px;
  font-size: 12px;
  line-height: 18px;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  box-shadow: 0 0 0 1px token.$crm-border-default inset;
}

.table-footer :deep(.btn-prev),
.table-footer :deep(.btn-next),
.table-footer :deep(.el-pager li) {
  min-width: 28px;
  width: auto;
  height: 28px;
  line-height: 18px;
  margin: 0;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  font-size: 12px;
  font-weight: 500;
}

.table-footer :deep(.el-pager) {
  gap: 6px;
}

.table-footer :deep(.el-pager li.is-active) {
  border-color: token.$crm-primary;
  color: token.$crm-primary;
  background: token.$crm-color-selected;
}

.table-footer :deep(.btn-prev:disabled),
.table-footer :deep(.btn-next:disabled) {
  color: token.$crm-text-muted;
  background: token.$crm-color-surface;
  opacity: 0.55;
}

:global(.customer-list-message-box .el-button) {
  height: 32px;
  min-height: 32px;
  margin: 0;
  border-color: token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  font-family: token.$crm-font-body;
  font-size: 13px;
  font-weight: 500;
}

:global(.customer-list-message-box .el-button + .el-button) {
  margin-left: 8px;
}

:global(.customer-list-message-box .el-button--primary) {
  border-color: token.$crm-primary;
  color: token.$crm-text-inverse;
  background: token.$crm-primary;
}

:global(.customer-list-message-box .el-button--primary:hover),
:global(.customer-list-message-box .el-button--primary:focus-visible) {
  border-color: token.$crm-primary-hover;
  background: token.$crm-primary-hover;
}

:global(.customer-list-message-box) {
  border-color: token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  --el-color-primary: #{token.$crm-primary};
}
</style>
