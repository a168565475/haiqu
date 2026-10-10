<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import {
  Refresh,
  Search,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'
import CustomerIdentityCell from '@/components/customers/CustomerIdentityCell.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import DataTableToolbar from '@/components/common/DataTableToolbar.vue'
import CrmPageHeader from '@/components/crm/CrmPageHeader.vue'
import bookmarkIcon from '@/assets/crm-v2/bookmark.svg'
import columnsIcon from '@/assets/crm-v2/columns.svg'
import exportIcon from '@/assets/crm-v2/export.svg'
import filterIcon from '@/assets/crm-v2/filter.svg'
import importIcon from '@/assets/crm-v2/import.svg'
import searchIcon from '@/assets/crm-v2/search.svg'
import sortCustomerIcon from '@/assets/crm-v2/sort-customer.svg'
import sortIcon from '@/assets/crm-v2/sort.svg'
import tagIcon from '@/assets/crm-v2/tag.svg'
import transferOwnerIcon from '@/assets/crm-v2/transfer-owner.svg'
import {
  bulkAddCustomerTags,
  createCustomerTransferRequest,
  deleteCustomer,
  exportCustomers,
  fetchCustomer,
  fetchCustomerOptions,
  fetchCustomers,
  fetchCustomerStats,
} from '@/api/customers'
import { createCustomerSavedView, fetchCustomerSavedViews } from '@/api/savedViews'
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
  CustomerLifecycleStage,
  CustomerListItem,
  CustomerListQuery,
  CustomerOptions,
  CustomerOrdering,
  CustomerStats,
} from '@/types/customer'
import type { SavedView } from '@/types/savedView'

interface FilterForm {
  q: string
  customer_grade: string
  country_code: string
  owner_id: string
  activity_status: '' | CustomerActivityStatus
  lifecycle_stage: '' | CustomerLifecycleStage
  customer_source: string
  customer_type: string
  customer_tag: string
}

type FilterKey = keyof FilterForm

interface ActiveFilterChip {
  key: FilterKey
  label: string
}

const authStore = useAuthStore()
const router = useRouter()
const gradeOptions = useOptions('CUSTOMER_GRADE')
const typeOptions = useOptions('CUSTOMER_TYPE')
const sourceOptions = useOptions('CUSTOMER_SOURCE')
const loading = ref(false)
const optionsLoading = ref(false)
const statsLoading = ref(false)
const errorMessage = ref('')
const rows = ref<CustomerListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const ordering = ref<CustomerOrdering>('-updated_at')
const selectedRows = ref<CustomerListItem[]>([])
const options = ref<CustomerOptions | null>(null)
const stats = ref<CustomerStats | null>(null)
const savedViews = ref<SavedView[]>([])
const activeStatKey = ref('total')
const activeViewName = ref('默认视图')
const exportLoading = ref(false)
const moreFiltersVisible = ref(false)

const filters = reactive<FilterForm>({
  q: '',
  customer_grade: '',
  country_code: '',
  owner_id: '',
  activity_status: '',
  lifecycle_stage: '',
  customer_source: '',
  customer_type: '',
  customer_tag: '',
})

const visibleColumns = reactive({
  country: true,
  grade: true,
  customerStatus: true,
  owner: true,
  value: true,
  lastOrder: true,
  lastContact: true,
  nextFollowUp: true,
  followUpStatus: true,
  risk: true,
})

const saveDialogVisible = ref(false)
const saveViewLoading = ref(false)
const savedViewName = ref('')
const transferDialogVisible = ref(false)
const transferLoading = ref(false)
const transferForm = reactive({ ownerId: '', reason: '' })
const tagDialogVisible = ref(false)
const tagLoading = ref(false)
const tagForm = reactive({ tagIds: [] as string[], reason: '' })

const selectedCount = computed(() => selectedRows.value.length)
const canSaveView = computed(
  () => authStore.hasPermission('preferences.view_savedview') && authStore.hasPermission('preferences.add_savedview'),
)
const canViewSavedViews = computed(() => authStore.hasPermission('preferences.view_savedview'))
const canTransfer = computed(() => authStore.hasPermission('customers.transfer_customer'))
const canChangeCustomer = computed(() => authStore.hasPermission('customers.change_customeraccount'))
const canDeleteCustomer = computed(() => authStore.hasPermission('customers.delete_customeraccount'))

const quickFilters = computed(() => [
  { key: 'total', label: '全部客户', value: stats.value?.total ?? 0 },
  { key: 'mine', label: '我的客户', value: stats.value?.mine ?? 0 },
  {
    key: 'today',
    label: '今日待跟进',
    value: stats.value?.today_follow_up ?? 0,
    hint: '该数据来自任务口径，客户列表接口暂不支持按任务到期日筛选。',
    metricOnly: true,
  },
  {
    key: 'highValue',
    label: '高价值客户',
    value: stats.value?.high_value ?? 0,
    hint: '后端当前口径：客户等级为 A。',
  },
  { key: 'risk', label: '风险客户', value: stats.value?.high_risk ?? 0 },
  { key: 'dormant', label: '沉睡客户', value: stats.value?.dormant ?? 0 },
])

const advancedFilterCount = computed(() => [
  filters.owner_id,
  filters.lifecycle_stage,
  filters.customer_source,
  filters.customer_type,
  filters.customer_tag,
].filter(Boolean).length)

const activeFilterChips = computed<ActiveFilterChip[]>(() => {
  const chips: ActiveFilterChip[] = []
  if (filters.q.trim()) chips.push({ key: 'q', label: `关键词：${filters.q.trim()}` })
  if (filters.activity_status) {
    chips.push({
      key: 'activity_status',
      label: `状态：${findCodeLabel(options.value?.activity_statuses, filters.activity_status)}`,
    })
  }
  if (filters.customer_grade) {
    chips.push({ key: 'customer_grade', label: `等级：${formatCustomerGrade(filters.customer_grade)}` })
  }
  if (filters.country_code) {
    chips.push({ key: 'country_code', label: `国家/地区：${formatCountry(filters.country_code)}` })
  }
  if (filters.owner_id) {
    const owner = options.value?.owner_options.find((item) => item.id === filters.owner_id)
    chips.push({ key: 'owner_id', label: `负责人：${owner?.display_name || filters.owner_id}` })
  }
  if (filters.lifecycle_stage) {
    chips.push({
      key: 'lifecycle_stage',
      label: `生命周期：${findCodeLabel(options.value?.lifecycle_stages, filters.lifecycle_stage)}`,
    })
  }
  if (filters.customer_source) {
    chips.push({
      key: 'customer_source',
      label: `来源：${findCodeLabel(options.value?.customer_sources, filters.customer_source)}`,
    })
  }
  if (filters.customer_type) {
    chips.push({
      key: 'customer_type',
      label: `类型：${findCodeLabel(options.value?.customer_types, filters.customer_type)}`,
    })
  }
  if (filters.customer_tag) {
    const tag = options.value?.customer_tags.find((item) => item.tag_code === filters.customer_tag)
    chips.push({ key: 'customer_tag', label: `标签：${tag?.tag_name || filters.customer_tag}` })
  }
  return chips
})

function buildQuery(): CustomerListQuery {
  const query: CustomerListQuery = { page: page.value, page_size: pageSize.value, ordering: ordering.value }
  if (filters.q.trim()) query.q = filters.q.trim()
  if (filters.customer_grade) query.customer_grade = filters.customer_grade
  if (filters.country_code) query.country_code = filters.country_code
  if (filters.owner_id) query.owner_id = filters.owner_id
  if (filters.activity_status) query.activity_status = filters.activity_status
  if (filters.lifecycle_stage) query.lifecycle_stage = filters.lifecycle_stage
  if (filters.customer_source) query.customer_source = filters.customer_source
  if (filters.customer_type) query.customer_type = filters.customer_type
  if (filters.customer_tag) query.customer_tag = filters.customer_tag
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

watch([gradeOptions.options, typeOptions.options, sourceOptions.options], ([grades, types, sources]) => {
  if (!options.value || optionsLoading.value || gradeOptions.configVersion.value === null) return
  options.value = {
    ...options.value,
    customer_grades: toCustomerDictionaryOptions(grades),
    customer_types: toCustomerDictionaryOptions(types),
    customer_sources: toCustomerDictionaryOptions(sources),
  }
})

async function loadOptions() {
  optionsLoading.value = true
  try {
    const [legacyResult, publishedResult] = await Promise.allSettled([
      fetchCustomerOptions(),
      Promise.all([gradeOptions.load(), typeOptions.load(), sourceOptions.load()]),
    ])
    if (legacyResult.status === 'rejected') throw legacyResult.reason
    const legacyOptions = legacyResult.value
    if (publishedResult.status === 'fulfilled' && gradeOptions.configVersion.value !== null) {
      const [grades, types, sources] = publishedResult.value
      options.value = {
        ...legacyOptions,
        customer_grades: toCustomerDictionaryOptions(grades),
        customer_types: toCustomerDictionaryOptions(types),
        customer_sources: toCustomerDictionaryOptions(sources),
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

async function loadStats() {
  statsLoading.value = true
  try {
    stats.value = await fetchCustomerStats()
  } catch (error) {
    ElMessage.error(`统计加载失败：${getErrorMessage(error)}`)
  } finally {
    statsLoading.value = false
  }
}

async function loadSavedViews() {
  if (!canViewSavedViews.value) return
  try {
    savedViews.value = await fetchCustomerSavedViews()
  } catch (error) {
    ElMessage.warning(`保存视图加载失败：${getErrorMessage(error)}`)
  }
}

async function refreshAll() {
  await Promise.all([loadRows(), loadStats()])
}

function searchCustomers() {
  page.value = 1
  void loadRows()
}

function clearFilterValues() {
  Object.assign(filters, {
    q: '',
    customer_grade: '',
    country_code: '',
    owner_id: '',
    activity_status: '',
    lifecycle_stage: '',
    customer_source: '',
    customer_type: '',
    customer_tag: '',
  })
}

function resetFilters() {
  activeStatKey.value = 'total'
  activeViewName.value = '默认视图'
  moreFiltersVisible.value = false
  clearFilterValues()
  page.value = 1
  ordering.value = '-updated_at'
  void loadRows()
}

function applyAdvancedFilters() {
  moreFiltersVisible.value = false
  searchCustomers()
}

function applyQuickFilter(key: string) {
  if (key === 'today') {
    ElMessage.info('今日待跟进使用任务统计口径；当前客户列表接口不支持按任务到期日筛选。')
    return
  }
  activeStatKey.value = key
  activeViewName.value = '默认视图'
  filters.owner_id = ''
  filters.customer_grade = ''
  filters.activity_status = ''
  if (key === 'mine') filters.owner_id = authStore.user?.employee?.id || ''
  else if (key === 'highValue') filters.customer_grade = 'A'
  else if (key === 'risk') filters.activity_status = 'HIGH_RISK'
  else if (key === 'dormant') filters.activity_status = 'DORMANT'
  else clearFilterValues()
  searchCustomers()
}

function applySavedView(view: SavedView) {
  const definition = view.filter_definition
  Object.assign(filters, {
    q: typeof definition.q === 'string' ? definition.q : '',
    customer_grade: typeof definition.customer_grade === 'string' ? definition.customer_grade : '',
    country_code: typeof definition.country_code === 'string' ? definition.country_code : '',
    owner_id: typeof definition.owner_id === 'string' ? definition.owner_id : '',
    activity_status: typeof definition.activity_status === 'string' ? definition.activity_status : '',
    lifecycle_stage: typeof definition.lifecycle_stage === 'string' ? definition.lifecycle_stage : '',
    customer_source: typeof definition.customer_source === 'string' ? definition.customer_source : '',
    customer_type: typeof definition.customer_type === 'string' ? definition.customer_type : '',
    customer_tag: typeof definition.customer_tag === 'string' ? definition.customer_tag : '',
  })
  if (typeof definition.page_size === 'number') pageSize.value = definition.page_size
  if (view.sort_definition[0]) ordering.value = view.sort_definition[0] as CustomerOrdering
  activeViewName.value = view.view_name
  activeStatKey.value = 'total'
  page.value = 1
  void loadRows()
}

function applySavedViewById(command: string | number | object) {
  const view = savedViews.value.find((item) => item.id === command)
  if (view) applySavedView(view)
}

function openSaveViewDialog() {
  if (!canSaveView.value) {
    ElMessage.warning('当前账号没有保存客户视图的权限。')
    return
  }
  saveDialogVisible.value = true
}

async function saveCurrentView() {
  const name = savedViewName.value.trim()
  if (!name) {
    ElMessage.warning('请输入视图名称。')
    return
  }
  const filterDefinition = Object.fromEntries(
    Object.entries(buildQuery()).filter(([key, value]) => key !== 'page' && value !== '' && value !== undefined),
  )
  saveViewLoading.value = true
  try {
    await createCustomerSavedView({
      module_code: 'CUSTOMER',
      view_name: name,
      filter_definition: filterDefinition,
      column_definition: Object.entries(visibleColumns).filter(([, shown]) => shown).map(([key]) => key),
      sort_definition: [ordering.value],
    })
    saveDialogVisible.value = false
    savedViewName.value = ''
    ElMessage.success('当前客户筛选视图已保存。')
    await loadSavedViews()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    saveViewLoading.value = false
  }
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

function handleUnavailableImport() {
  ElMessage.info('客户导入功能尚未开放。')
}

function openTransferDialog() {
  if (!selectedCount.value) return
  transferForm.ownerId = ''
  transferForm.reason = ''
  transferDialogVisible.value = true
}

async function submitTransfers() {
  if (!transferForm.ownerId || transferForm.reason.trim().length < 2) {
    ElMessage.warning('请选择新负责人并填写至少 2 个字的转移原因。')
    return
  }
  await ElMessageBox.confirm(
    `将为 ${selectedCount.value} 个客户提交转移申请，提交后仍需审批。是否继续？`,
    '确认批量转移',
    { type: 'warning', customClass: 'customer-list-message-box' },
  )
  transferLoading.value = true
  try {
    const results = await Promise.allSettled(
      selectedRows.value.map((row) => createCustomerTransferRequest({
        customer_id: row.id,
        to_employee_id: transferForm.ownerId,
        reason: transferForm.reason.trim(),
      })),
    )
    const successCount = results.filter((result) => result.status === 'fulfilled').length
    const failedCount = results.length - successCount
    transferDialogVisible.value = false
    ElMessage[failedCount ? 'warning' : 'success'](`已提交 ${successCount} 项，失败 ${failedCount} 项。`)
  } finally {
    transferLoading.value = false
  }
}

function openTagDialog() {
  if (!selectedCount.value) return
  tagForm.tagIds = []
  tagForm.reason = ''
  tagDialogVisible.value = true
}

async function submitTags() {
  if (!tagForm.tagIds.length || tagForm.reason.trim().length < 2) {
    ElMessage.warning('请选择标签并填写至少 2 个字的操作原因。')
    return
  }
  tagLoading.value = true
  try {
    const result = await bulkAddCustomerTags({
      customer_ids: selectedRows.value.map((row) => row.id),
      customer_tag_ids: tagForm.tagIds,
      reason: tagForm.reason.trim(),
    })
    tagDialogVisible.value = false
    ElMessage.success(`已更新 ${result.updated_count} 个客户。`)
    await loadRows()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    tagLoading.value = false
  }
}

function handleSelectionChange(selection: CustomerListItem[]) {
  selectedRows.value = selection
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

function applyOrdering(command: string | number | object) {
  if (typeof command !== 'string') return
  ordering.value = command as CustomerOrdering
  page.value = 1
  void loadRows()
}

function handlePageSizeChange() {
  page.value = 1
  void loadRows()
}

function findCodeLabel(
  items: Array<{ item_code: string; display_name: string }> | undefined,
  code: string,
): string {
  return items?.find((item) => item.item_code === code)?.display_name || code
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
    await refreshAll()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  }
}

onMounted(async () => {
  await Promise.all([loadOptions(), loadRows(), loadStats(), loadSavedViews()])
})
</script>

<template>
  <div
    class="customer-list-page"
    data-customer-list-page
    :style="{ '--customer-sort-icon': `url(${sortCustomerIcon})` }"
  >
    <CrmPageHeader title="客户列表" :count="stats?.total ?? total" count-label="个客户">
      <template #actions>
        <ElButton class="header-action header-action--import" @click="handleUnavailableImport">
          <img class="button-icon" :src="importIcon" alt="" aria-hidden="true" />
          导入
        </ElButton>
        <ElButton class="header-action header-action--export" :loading="exportLoading" @click="handleExport">
          <img class="button-icon" :src="exportIcon" alt="" aria-hidden="true" />
          导出
        </ElButton>
        <ElButton class="header-action header-action--create" type="primary" @click="openCustomerCreate">
          <span class="button-plus" aria-hidden="true">＋</span>
          新建客户
        </ElButton>
      </template>
    </CrmPageHeader>

    <section class="quick-filter-strip" :aria-busy="statsLoading" aria-label="客户快捷筛选">
      <button
        v-for="item in quickFilters"
        :key="item.key"
        type="button"
        class="quick-filter"
        :class="{ 'is-active': activeStatKey === item.key, 'is-metric-only': item.metricOnly }"
        :aria-pressed="activeStatKey === item.key"
        :title="item.hint"
        :disabled="statsLoading"
        @click="applyQuickFilter(item.key)"
      >
        <span>{{ item.label }}</span>
        <strong>{{ item.value.toLocaleString() }}</strong>
      </button>
    </section>

    <section class="filter-panel" aria-label="筛选客户">
      <form class="filter-grid" @submit.prevent="searchCustomers">
        <ElInput
          v-model="filters.q"
          class="filter-control filter-control--search"
          aria-label="搜索客户名称、编号、联系人、邮箱或电话"
          placeholder="搜索客户名称、编号、联系人、邮箱、电话"
          clearable
        >
          <template #suffix><img class="field-icon" :src="searchIcon" alt="" aria-hidden="true" /></template>
        </ElInput>

        <ElSelect
          v-model="filters.activity_status"
          class="filter-control filter-control--status"
          aria-label="客户状态"
          placeholder="客户状态：全部"
          clearable
          :loading="optionsLoading"
          @change="searchCustomers"
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
          @change="searchCustomers"
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
          @change="searchCustomers"
        >
            <ElOption v-for="item in options?.country_options" :key="item.item_code" :label="`${item.display_name}（${item.item_code}）`" :value="item.item_code" />
        </ElSelect>

        <ElPopover
          v-model:visible="moreFiltersVisible"
          placement="bottom-end"
          trigger="click"
          :width="430"
          :teleported="false"
          popper-class="customer-list-filter-popper"
        >
          <template #reference>
            <ElButton class="filter-more-button">
              <img class="button-icon" :src="filterIcon" alt="" aria-hidden="true" />
              更多筛选
              <span v-if="advancedFilterCount" class="filter-count">{{ advancedFilterCount }}</span>
            </ElButton>
          </template>
          <div v-if="moreFiltersVisible" class="advanced-filter-grid">
            <label class="advanced-filter-field">
              <span>负责人</span>
              <ElSelect v-model="filters.owner_id" placeholder="全部负责人" clearable filterable :loading="optionsLoading">
                <ElOption v-for="owner in options?.owner_options" :key="owner.id" :label="owner.display_name" :value="owner.id" />
              </ElSelect>
            </label>
            <label class="advanced-filter-field">
              <span>生命周期</span>
              <ElSelect v-model="filters.lifecycle_stage" placeholder="全部阶段" clearable>
                <ElOption v-for="item in options?.lifecycle_stages" :key="item.item_code" :label="item.display_name" :value="item.item_code" />
              </ElSelect>
            </label>
            <label class="advanced-filter-field">
              <span>客户来源</span>
              <ElSelect v-model="filters.customer_source" placeholder="全部来源" clearable filterable>
                <ElOption v-for="item in options?.customer_sources" :key="item.id" :label="item.display_name" :value="item.item_code" />
              </ElSelect>
            </label>
            <label class="advanced-filter-field">
              <span>客户类型</span>
              <ElSelect v-model="filters.customer_type" placeholder="全部类型" clearable filterable>
                <ElOption v-for="item in options?.customer_types" :key="item.id" :label="item.display_name" :value="item.item_code" />
              </ElSelect>
            </label>
            <label class="advanced-filter-field advanced-filter-field--wide">
              <span>客户标签</span>
              <ElSelect v-model="filters.customer_tag" placeholder="全部标签" clearable filterable>
                <ElOption v-for="tag in options?.customer_tags" :key="tag.id" :label="tag.tag_name" :value="tag.tag_code" />
              </ElSelect>
            </label>
            <div class="advanced-filter-actions">
              <ElButton @click="resetFilters">重置</ElButton>
              <ElButton type="primary" @click="applyAdvancedFilters">应用筛选</ElButton>
            </div>
          </div>
        </ElPopover>
      </form>
    </section>

    <DataTableToolbar class="is-compact" :selected-count="selectedCount">
      <template #selection>
        <ElButton class="toolbar-button toolbar-button--transfer" :disabled="!selectedCount || !canTransfer" @click="openTransferDialog">
          <img class="button-icon" :src="transferOwnerIcon" alt="" aria-hidden="true" />
          批量转移负责人
        </ElButton>
        <ElButton class="toolbar-button toolbar-button--tag" :disabled="!selectedCount || !canChangeCustomer" @click="openTagDialog">
          <img class="button-icon" :src="tagIcon" alt="" aria-hidden="true" />
          添加标签
        </ElButton>
      </template>
      <template #actions>
        <ElDropdown trigger="click" placement="bottom-end" @command="applyOrdering">
          <ElButton class="toolbar-button toolbar-button--sort">
            <img class="button-icon" :src="sortIcon" alt="" aria-hidden="true" />
            排序
          </ElButton>
          <template #dropdown>
            <ElDropdownMenu>
              <ElDropdownItem command="-updated_at">最近更新</ElDropdownItem>
              <ElDropdownItem command="account_name">客户名称升序</ElDropdownItem>
              <ElDropdownItem command="-account_name">客户名称降序</ElDropdownItem>
              <ElDropdownItem command="account_code">客户编号升序</ElDropdownItem>
            </ElDropdownMenu>
          </template>
        </ElDropdown>

        <ElPopover placement="bottom-end" trigger="click" :width="196" :teleported="false">
          <template #reference>
            <ElButton class="toolbar-button toolbar-button--columns">
              <img class="button-icon" :src="columnsIcon" alt="" aria-hidden="true" />
              列设置
            </ElButton>
          </template>
          <div class="column-options">
            <ElCheckbox v-model="visibleColumns.country">国家/地区</ElCheckbox>
            <ElCheckbox v-model="visibleColumns.grade">等级</ElCheckbox>
            <ElCheckbox v-model="visibleColumns.customerStatus">客户状态</ElCheckbox>
            <ElCheckbox v-model="visibleColumns.owner">负责人</ElCheckbox>
            <ElCheckbox v-model="visibleColumns.value">近12个月销售额</ElCheckbox>
            <ElCheckbox v-model="visibleColumns.lastOrder">最近订单</ElCheckbox>
            <ElCheckbox v-model="visibleColumns.lastContact">最近联系</ElCheckbox>
            <ElCheckbox v-model="visibleColumns.nextFollowUp">下次跟进</ElCheckbox>
            <ElCheckbox v-model="visibleColumns.followUpStatus">跟进状态</ElCheckbox>
            <ElCheckbox v-model="visibleColumns.risk">风险</ElCheckbox>
          </div>
        </ElPopover>

        <ElDropdown
          class="saved-view-control"
          split-button
          trigger="click"
          placement="bottom-end"
          :disabled="!canSaveView && !canViewSavedViews"
          @click="openSaveViewDialog"
          @command="applySavedViewById"
        >
          <img class="button-icon" :src="bookmarkIcon" alt="" aria-hidden="true" />
          保存视图
          <template #dropdown>
            <ElDropdownMenu>
              <ElDropdownItem v-if="!savedViews.length" disabled>暂无保存视图</ElDropdownItem>
              <ElDropdownItem v-for="view in savedViews" :key="view.id" :command="view.id">
                {{ view.view_name }}
              </ElDropdownItem>
            </ElDropdownMenu>
          </template>
        </ElDropdown>

        <ElButton class="toolbar-button toolbar-button--refresh" aria-label="刷新客户列表" title="刷新" @click="refreshAll">
          ↻
        </ElButton>
      </template>
    </DataTableToolbar>

    <section class="data-surface is-dense" aria-label="客户数据列表">
      <div v-if="errorMessage" class="data-state data-state--error" role="alert">
        <strong>客户列表加载失败</strong>
        <p>{{ errorMessage }}</p>
        <ElButton type="primary" :icon="Refresh" @click="refreshAll">重新加载</ElButton>
      </div>
      <template v-else>
        <ElTable
          v-loading="loading"
          element-loading-text="正在加载客户数据…"
          :data="rows"
          row-key="id"
          table-layout="fixed"
          border
          empty-text=""
          height="calc(100% - 48px)"
          :aria-busy="loading"
          @selection-change="handleSelectionChange"
          @sort-change="handleSortChange"
        >
          <ElTableColumn type="selection" width="50" fixed="left" />
          <ElTableColumn prop="account_name" min-width="245" sortable="custom">
            <template #header>
              <span class="sortable-header">客户名称 / 编号<img :src="sortCustomerIcon" alt="" aria-hidden="true" /></span>
            </template>
            <template #default="{ row }">
              <CustomerIdentityCell :customer="row" @open="openCustomerDetail(row.id)" />
            </template>
          </ElTableColumn>
          <ElTableColumn v-if="visibleColumns.country" label="国家/地区" width="115">
            <template #default="{ row }"><span class="country-value">{{ formatCountry(row.primary_country_code) }}</span></template>
          </ElTableColumn>
          <ElTableColumn v-if="visibleColumns.grade" label="等级" width="90">
            <template #default="{ row }"><span class="grade-value">{{ formatCustomerGradeCell(row.customer_grade?.item_code) }}</span></template>
          </ElTableColumn>
          <ElTableColumn v-if="visibleColumns.customerStatus" label="客户状态" width="115">
            <template #default="{ row }"><CustomerActivityTag :activity="row.activity" /></template>
          </ElTableColumn>
          <ElTableColumn v-if="visibleColumns.owner" label="负责人" width="120">
            <template #default="{ row }">
              <ElTooltip :content="row.primary_owner?.display_name || '未分配'" placement="top" :show-after="300">
                <span class="owner-name">{{ row.primary_owner?.display_name || '—' }}</span>
              </ElTooltip>
            </template>
          </ElTableColumn>
          <ElTableColumn v-if="visibleColumns.value" width="160">
            <template #header>
              <span class="sortable-header">近12个月销售额<img :src="sortCustomerIcon" alt="" aria-hidden="true" /></span>
            </template>
            <template #default="{ row }">
              <ElTooltip :content="businessValueTooltip(row)" placement="top" :show-after="300">
                <strong class="business-value">{{ formatBusinessValue(row) }}</strong>
              </ElTooltip>
            </template>
          </ElTableColumn>
          <ElTableColumn v-if="visibleColumns.lastOrder" label="最近订单" width="120">
            <template #default="{ row }">
              <ElTooltip :content="recentOrderTooltip(row)" placement="top" :show-after="300">
                <span class="date-value">{{ row.recent_order ? formatDate(row.recent_order.order_date) : '—' }}</span>
              </ElTooltip>
            </template>
          </ElTableColumn>
          <ElTableColumn v-if="visibleColumns.lastContact" label="最近联系" width="120">
            <template #default="{ row }"><span class="date-value">{{ formatDate(row.last_contact_at) }}</span></template>
          </ElTableColumn>
          <ElTableColumn v-if="visibleColumns.nextFollowUp" label="下次跟进" width="125">
            <template #default="{ row }">
              <span class="date-value">{{ row.next_follow_up_at ? formatDate(row.next_follow_up_at) : '未安排' }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn v-if="visibleColumns.followUpStatus" label="跟进状态" width="135">
            <template #default="{ row }">
              <CustomerActivityTag
                :label="getFollowUpStatus(row.next_follow_up_at).label"
                :tone="getFollowUpStatus(row.next_follow_up_at).tone"
                :title="getFollowUpStatus(row.next_follow_up_at).title"
              />
            </template>
          </ElTableColumn>
          <ElTableColumn v-if="visibleColumns.risk" label="风险" width="120">
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
              <strong>{{ activeFilterChips.length ? '没有符合当前条件的客户' : '暂无客户数据' }}</strong>
              <p>{{ activeFilterChips.length ? '可调整筛选条件后重新查询。' : '可使用“新建客户”开始建档。' }}</p>
              <ElButton v-if="activeFilterChips.length" @click="resetFilters">清除筛选</ElButton>
              <ElButton v-else type="primary" @click="openCustomerCreate">新建客户</ElButton>
            </div>
          </template>
        </ElTable>
        <footer class="table-footer">
          <span class="table-footer__total">共 {{ total.toLocaleString() }} 条</span>
          <ElPagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[20, 50, 100]"
            layout="sizes, prev, pager, next"
            @current-change="loadRows"
            @size-change="handlePageSizeChange"
          />
        </footer>
      </template>
    </section>

    <AppWindowDialog v-model="saveDialogVisible" class="customer-list-dialog" title="保存当前视图" :width="420" :height="260">
      <ElForm label-position="top">
        <ElFormItem label="视图名称" required><ElInput v-model="savedViewName" maxlength="50" show-word-limit /></ElFormItem>
      </ElForm>
      <template #footer><ElButton @click="saveDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="saveViewLoading" @click="saveCurrentView">保存</ElButton></template>
    </AppWindowDialog>

    <AppWindowDialog v-model="transferDialogVisible" class="customer-list-dialog" title="批量转移客户" :width="480" :height="410">
      <ElAlert title="该操作提交转移申请，不会绕过审批直接修改负责人。" type="warning" show-icon :closable="false" />
      <ElForm label-position="top" class="dialog-form">
        <ElFormItem label="新负责人" required>
          <ElSelect v-model="transferForm.ownerId" filterable placeholder="选择有效员工"><ElOption v-for="owner in options?.owner_options" :key="owner.id" :label="owner.display_name" :value="owner.id" /></ElSelect>
        </ElFormItem>
        <ElFormItem label="转移原因" required><ElInput v-model="transferForm.reason" type="textarea" maxlength="500" show-word-limit /></ElFormItem>
      </ElForm>
      <template #footer><ElButton @click="transferDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="transferLoading" @click="submitTransfers">提交申请</ElButton></template>
    </AppWindowDialog>

    <AppWindowDialog v-model="tagDialogVisible" class="customer-list-dialog" title="批量添加标签" :width="480" :height="370">
      <ElForm label-position="top">
        <ElFormItem label="客户标签" required>
          <ElSelect v-model="tagForm.tagIds" multiple filterable placeholder="选择一个或多个标签"><ElOption v-for="tag in options?.customer_tags" :key="tag.id" :label="tag.tag_name" :value="tag.id" /></ElSelect>
        </ElFormItem>
        <ElFormItem label="操作原因" required><ElInput v-model="tagForm.reason" type="textarea" maxlength="500" show-word-limit /></ElFormItem>
      </ElForm>
      <template #footer><ElButton @click="tagDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="tagLoading" @click="submitTags">添加标签</ElButton></template>
    </AppWindowDialog>

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

.quick-filter-strip {
  display: flex;
  min-height: 48px;
  margin-bottom: token.$crm-space-3;
  overflow-x: auto;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  scrollbar-width: thin;
}

.quick-filter {
  @include mixin.reset-button;
  position: relative;
  display: inline-flex;
  min-width: 132px;
  flex: 1 0 auto;
  align-items: baseline;
  justify-content: center;
  gap: token.$crm-space-2;
  padding: 0 token.$crm-space-4;
  border-right: 1px solid token.$crm-border-default;
  color: token.$crm-text-secondary;
  cursor: pointer;
  font-size: 12px;
  line-height: 18px;
  transition: color 120ms ease, background-color 120ms ease;
}

.quick-filter:last-child { border-right: 0; }
.quick-filter:hover { color: token.$crm-text-primary; background: token.$crm-color-subtle; }
.quick-filter:focus-visible { z-index: 1; outline: none; box-shadow: 0 0 0 2px token.$crm-focus inset; }
.quick-filter::after { position: absolute; right: 12px; bottom: -1px; left: 12px; height: 2px; background: transparent; content: ''; }
.quick-filter.is-active { color: token.$crm-text-primary; background: token.$crm-color-selected; }
.quick-filter.is-active::after { background: token.$crm-primary; }
.quick-filter strong { color: token.$crm-text-primary; font-size: 16px; font-weight: 600; line-height: 24px; font-variant-numeric: tabular-nums; }
.quick-filter small { position: absolute; top: 3px; right: 5px; color: token.$crm-text-muted; font-size: 9px; line-height: 12px; }
.quick-filter:disabled { cursor: wait; opacity: 0.6; }

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

.filter-count {
  display: inline-flex;
  min-width: 18px;
  height: 18px;
  align-items: center;
  justify-content: center;
  margin-left: token.$crm-space-1;
  border-radius: token.$crm-radius-pill;
  color: token.$crm-primary-hover;
  background: token.$crm-color-selected;
  font-size: 10px;
  font-weight: 600;
}

.advanced-filter-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: token.$crm-space-3; }
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

.data-table-toolbar { margin-bottom: token.$crm-space-2; }
.column-options { display: flex; flex-direction: column; gap: 2px; }
.column-options :deep(.el-checkbox) { height: 30px; margin: 0; }
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
.dialog-form { margin-top: token.$crm-space-4; }

@media (max-width: 1280px) {
  .filter-grid { grid-template-columns: minmax(220px, 1.5fr) repeat(3, minmax(130px, 1fr)) auto; }
  .filter-field--more, .filter-actions { grid-row: 2; }
}

@media (max-width: 900px) {
  .filter-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .filter-field--more, .filter-actions { grid-row: auto; }
  .table-footer { align-items: flex-start; flex-direction: column; }
}

@media (max-width: 768px) {
  .customer-list-page { margin: 0; padding: 16px; }
  .filter-grid, .advanced-filter-grid { grid-template-columns: 1fr; }
  .filter-actions { justify-content: flex-end; }
}

/* CUS-V2-01 / Figma 1525:360 */
.customer-list-page {
  width: auto;
  height: calc(100dvh - 92px);
  min-height: calc(100dvh - 92px);
  margin: 0;
  padding: 22px 28px 18px;
  overflow: hidden;
  color: token.$crm-text-regular;
  background: token.$crm-color-page;
}

.crm-page-header {
  margin: 0;
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

.header-action {
  height: 32px;
  padding: 0 16px;
}

.header-action--import,
.header-action--export {
  width: 110px;
}

.header-action--create {
  width: 140px;
}

.button-icon,
.field-icon {
  display: block;
  width: 16px;
  height: 16px;
  flex: none;
}

.button-plus {
  font-size: 18px;
  font-weight: 400;
  line-height: 18px;
}

.quick-filter-strip {
  width: 100%;
  height: 42px;
  min-height: 42px;
  margin: 2px 0 0;
  overflow: hidden;
  border-color: token.$crm-border-subtle;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-subtle;
}

.quick-filter {
  min-width: 0;
  height: 42px;
  flex: none;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 0 12px;
  border-right: 0;
  color: token.$crm-text-secondary;
  background: transparent;
  font-size: 13px;
  font-weight: 500;
  line-height: 20px;
}

.quick-filter:nth-child(1) { width: 140px; }
.quick-filter:nth-child(2) { width: 150px; }
.quick-filter:nth-child(3) { width: 170px; }
.quick-filter:nth-child(4) { width: 140px; }
.quick-filter:nth-child(5) { width: 150px; }
.quick-filter:nth-child(6) { width: 150px; }

.quick-filter:hover {
  color: token.$crm-text-primary;
  background: rgba(255, 255, 255, 0.28);
}

.quick-filter.is-active {
  color: token.$crm-text-primary;
  background: transparent;
}

.quick-filter::after {
  right: 0;
  bottom: 0;
  left: 0;
  height: 4px;
}

.quick-filter strong {
  color: token.$crm-text-secondary;
  font-size: 12px;
  font-weight: 500;
  line-height: 20px;
}

.quick-filter.is-active strong {
  color: token.$crm-primary;
}

.filter-panel {
  height: 32px;
  margin: 12px 0 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.filter-grid {
  display: flex;
  height: 32px;
  align-items: stretch;
  gap: 10px;
}

.filter-control {
  height: 32px;
  flex: none;
}

.filter-control--search { width: 410px; }
.filter-control--status { width: 160px; }
.filter-control--grade { width: 142px; }
.filter-control--country { width: 176px; }

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

.filter-more-button {
  width: 130px;
  height: 32px !important;
  margin: 0 !important;
  padding: 0 12px !important;
}

.filter-count {
  min-width: 18px;
  height: 18px;
  margin-left: 0;
  color: token.$crm-primary;
  background: token.$crm-color-selected;
}

.advanced-filter-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.advanced-filter-field {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
  color: token.$crm-text-secondary;
  font-size: 12px;
}

.advanced-filter-field--wide,
.advanced-filter-actions {
  grid-column: 1 / -1;
}

.advanced-filter-field :deep(.el-select) {
  width: 100%;
}

.advanced-filter-field :deep(.el-select__wrapper) {
  min-height: 32px;
  border-radius: token.$crm-radius-2;
}

.advanced-filter-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding-top: 2px;
}

.data-table-toolbar {
  height: 32px;
  margin-top: 10px;
  margin-bottom: 0;
}

.data-table-toolbar :deep(.data-table-toolbar__selection),
.data-table-toolbar :deep(.data-table-toolbar__actions) {
  height: 32px;
}

.toolbar-button {
  height: 32px;
  margin: 0 !important;
  padding: 0 16px !important;
}

.toolbar-button--transfer { width: 172px; }
.toolbar-button--tag { width: 116px; }
.toolbar-button--sort { width: 90px; }
.toolbar-button--columns { width: 104px; }
.toolbar-button--refresh {
  width: 48px;
  padding: 0 !important;
  font-size: 20px !important;
  font-weight: 400 !important;
}

.saved-view-control {
  width: 144px;
  height: 32px;
}

.saved-view-control :deep(.el-button-group) {
  width: 144px;
  height: 32px;
  display: flex;
}

.saved-view-control :deep(.el-button-group > .el-button:first-child) {
  width: 110px;
  height: 32px;
  flex: none;
  padding: 0 12px;
}

.saved-view-control :deep(.el-button-group > .el-button:last-child) {
  width: 34px;
  height: 32px;
  flex: none;
  padding: 0;
  border-left-color: token.$crm-border-default;
}

.column-options {
  gap: 2px;
}

.data-surface {
  width: 100%;
  height: calc(100dvh - 294px);
  min-height: 420px;
  margin-top: 14px;
  border-color: token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
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

.data-surface :deep(.el-table-column--selection .cell) {
  padding: 0 16px;
}

.data-surface :deep(.el-checkbox__inner) {
  width: 14px;
  height: 14px;
  border-color: token.$crm-border-default;
  border-radius: 2px;
  background: token.$crm-color-surface;
}

.data-surface :deep(.el-checkbox__input.is-checked .el-checkbox__inner),
.data-surface :deep(.el-checkbox__input.is-indeterminate .el-checkbox__inner) {
  border-color: token.$crm-primary;
  background: token.$crm-primary;
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

.country-value,
.grade-value,
.owner-name,
.date-value,
.business-value {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.country-value {
  color: token.$crm-text-secondary;
  font-size: 12px;
  font-weight: 400;
  line-height: 20px;
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
  min-height: 100%;
}

.table-footer {
  width: 100%;
  height: 44px;
  min-height: 44px;
  align-items: center;
  padding: 0 14px;
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
  height: 32px;
  gap: 8px;
  --el-pagination-button-width: 38px;
  --el-pagination-button-height: 32px;
}

.table-footer :deep(.el-pagination__sizes) {
  width: 136px;
  margin-right: 16px;
}

.table-footer :deep(.el-pagination__sizes .el-select) {
  width: 136px;
}

.table-footer :deep(.el-pagination__sizes .el-select__wrapper) {
  min-height: 32px;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  box-shadow: 0 0 0 1px token.$crm-border-default inset;
}

.table-footer :deep(.btn-prev),
.table-footer :deep(.btn-next),
.table-footer :deep(.el-pager li) {
  min-width: 38px;
  width: 38px;
  height: 32px;
  margin: 0;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  font-size: 13px;
  font-weight: 500;
}

.table-footer :deep(.el-pager) {
  gap: 8px;
}

.table-footer :deep(.el-pager li.is-active) {
  border-color: token.$crm-primary;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
}

.table-footer :deep(.btn-prev:disabled),
.table-footer :deep(.btn-next:disabled) {
  color: token.$crm-text-muted;
  background: token.$crm-color-surface;
  opacity: 0.55;
}

@media (max-width: 1440px) and (min-width: 769px) {
  .customer-list-page {
    margin: 0;
    padding: 22px 24px 18px;
  }

  .data-surface {
    height: calc(100dvh - 294px);
  }
}

:global(.customer-list-dialog) {
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  --el-color-primary: #{token.$crm-primary};
  --el-border-color: #{token.$crm-border-default};
  --el-text-color-primary: #{token.$crm-text-primary};
  --el-text-color-regular: #{token.$crm-text-regular};
  --el-text-color-placeholder: #{token.$crm-text-muted};
}

:global(.customer-list-dialog .el-dialog__header) {
  box-sizing: border-box;
  height: 44px;
  min-height: 44px;
  margin: 0;
  padding: 0 104px 0 16px;
  border-bottom: 1px solid token.$crm-border-subtle;
}

:global(.customer-list-dialog .el-dialog__title) {
  color: token.$crm-text-primary;
  font-family: token.$crm-font-display;
  font-size: 16px;
  font-weight: 600;
  line-height: 22px;
}

:global(.customer-list-dialog .el-dialog__body) {
  padding: 20px 24px;
}

:global(.customer-list-dialog .el-dialog__footer) {
  padding: 12px 24px 20px;
  border-top: 1px solid token.$crm-border-subtle;
}

:global(.customer-list-dialog .el-input__wrapper),
:global(.customer-list-dialog .el-select__wrapper) {
  min-height: 32px;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  box-shadow: 0 0 0 1px token.$crm-border-default inset;
}

:global(.customer-list-dialog .el-input__wrapper:hover),
:global(.customer-list-dialog .el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px token.$crm-border-strong inset;
}

:global(.customer-list-dialog .el-input__wrapper.is-focus),
:global(.customer-list-dialog .el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1px token.$crm-focus inset, 0 0 0 2px rgba(56, 152, 236, 0.18);
}

:global(.customer-list-dialog .el-textarea__inner) {
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  box-shadow: 0 0 0 1px token.$crm-border-default inset;
}

:global(.customer-list-dialog .el-form-item__label) {
  color: token.$crm-text-secondary;
}

:global(.customer-list-dialog .el-button),
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

:global(.customer-list-dialog .el-button + .el-button),
:global(.customer-list-message-box .el-button + .el-button) {
  margin-left: 8px;
}

:global(.customer-list-dialog .el-button--primary),
:global(.customer-list-message-box .el-button--primary) {
  border-color: token.$crm-primary;
  color: token.$crm-text-inverse;
  background: token.$crm-primary;
}

:global(.customer-list-dialog .el-button--primary:hover),
:global(.customer-list-dialog .el-button--primary:focus-visible),
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
