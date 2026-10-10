<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ArrowDown, MoreFilled, Refresh, Search, Setting } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createQuotationDraft, deleteQuotation, exportQuotations, fetchQuotation, fetchQuotationCreationOptions, fetchQuotationOptions, fetchQuotations, fetchQuotationSummary } from '@/api/quotations'
import { fetchAllMasterDataRecords } from '@/api/referenceData'
import { createQuotationSavedView, fetchQuotationSavedViews } from '@/api/savedViews'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { QuotationCreationOption, QuotationListItem, QuotationListOptions, QuotationListQuery, QuotationSummary } from '@/types/quotation'
import type { SavedView } from '@/types/savedView'
import type { Currency } from '@/types/referenceData'

interface FilterForm {
  search: string
  display_status: string
  owner_employee_id: string
  currency_code: string
  valid_to: string
}

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
let listRequest = 0
let summaryRequest = 0
let disposed = false
const loading = ref(false)
const summaryLoading = ref(false)
const optionLoading = ref(false)
const exportLoading = ref(false)
const errorMessage = ref('')
const rows = ref<QuotationListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const selectedRows = ref<QuotationListItem[]>([])
const activeMetric = ref('all')
const summary = ref<QuotationSummary | null>(null)
const options = ref<QuotationListOptions | null>(null)
const filters = reactive<FilterForm>({ search: '', display_status: '', owner_employee_id: '', currency_code: '', valid_to: '' })
const savedViews = ref<SavedView[]>([])
const saveDialogVisible = ref(false)
const saveViewLoading = ref(false)
const savedViewName = ref('')
const compactTable = ref(false)
const moreFiltersVisible = ref(false)
const currentViewLabel = ref('全部报价')
const expiringMetricActive = ref(false)
const visibleColumns = reactive<Record<string, boolean>>({
  currency: true,
  incoterm: true,
  owner: true,
  updated: true,
  validUntil: true,
  amount: true,
})
const columnLabels: Record<string, string> = {
  currency: '币种', incoterm: '贸易条款', owner: '负责人',
  updated: '最近更新', validUntil: '有效期', amount: '报价金额',
}
const createVisible = ref(false)
const createLoading = ref(false)
const createCustomerLoading = ref(false)
const createEntityLoading = ref(false)
const createCustomers = ref<QuotationCreationOption[]>([])
const createCurrencies = ref<Currency[]>([])
const createForm = reactive({ customer_account_id: '', transaction_entity_id: '', subject: '', currency_code: '', valid_until: '' })

const canCreate = computed(() => authStore.hasPermission('quotations.add_quotation'))
const canExport = computed(() => authStore.hasPermission('quotations.export_quotation'))
const canDelete = computed(() => authStore.hasPermission('quotations.delete_quotation'))
const canViewSavedViews = computed(() => authStore.hasPermission('preferences.view_savedview'))
const canSaveView = computed(() => canViewSavedViews.value && authStore.hasPermission('preferences.add_savedview'))
const metricCards = computed(() => [
  { key: 'all', label: '全部报价', value: summary.value?.all ?? 0 },
  { key: 'draft', label: '草稿', value: summary.value?.draft ?? 0 },
  { key: 'ready', label: '待发送', value: summary.value?.ready_to_send ?? 0 },
  { key: 'sent', label: '已发送', value: summary.value?.sent ?? 0 },
  { key: 'accepted', label: '已接受', value: summary.value?.accepted ?? 0 },
  { key: 'expiring', label: '7 天内到期', value: summary.value?.expiring_within_7_days ?? 0 },
])

function buildQuery(): QuotationListQuery {
  const query: QuotationListQuery = { page: page.value, page_size: pageSize.value, ordering: '-updated_at' }
  if (filters.search.trim()) query.q = filters.search.trim()
  if (filters.display_status) query.display_status = filters.display_status
  if (filters.owner_employee_id) query.owner_employee_id = filters.owner_employee_id
  if (filters.currency_code) query.currency_code = filters.currency_code
  if (expiringMetricActive.value) {
    const today = new Date()
    const end = new Date(today)
    end.setDate(end.getDate() + 7)
    query.valid_from = toLocalDate(today)
    query.valid_to = toLocalDate(end)
  } else if (filters.valid_to) query.valid_to = filters.valid_to
  if (typeof route.query.customer_id === 'string') query.customer_id = route.query.customer_id
  return query
}

function buildSummaryQuery(): Partial<QuotationListQuery> {
  const { page: _page, page_size: _pageSize, display_status: _displayStatus, ordering: _ordering, ...query } = buildQuery()
  return query
}

function toLocalDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务后重试。'
  const detail = (error.response.data as { detail?: string; error?: { message?: string } })
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有查看报价的权限。'
  if (error.response.status >= 500) return '报价服务暂时异常，请稍后重试。'
  return detail.error?.message || detail.detail || '请求失败，请检查筛选条件。'
}

async function loadRows() {
  const request = ++listRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchQuotations(buildQuery())
    if (disposed || request !== listRequest) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (disposed || request !== listRequest) return
    rows.value = []
    total.value = 0
    errorMessage.value = getErrorMessage(error)
  } finally {
    if (!disposed && request === listRequest) loading.value = false
  }
}

async function loadSummary() {
  const request = ++summaryRequest
  summaryLoading.value = true
  try {
    const result = await fetchQuotationSummary(buildSummaryQuery())
    if (!disposed && request === summaryRequest) summary.value = result
  } catch (error) {
    if (disposed || request !== summaryRequest) return
    summary.value = null
    ElMessage.warning(`报价统计加载失败：${getErrorMessage(error)}`)
  } finally {
    if (!disposed && request === summaryRequest) summaryLoading.value = false
  }
}

async function loadSavedViews() {
  if (!canViewSavedViews.value) return
  try {
    savedViews.value = await fetchQuotationSavedViews()
  } catch (error) {
    ElMessage.warning(`保存视图加载失败：${getErrorMessage(error)}`)
  }
}

async function loadOptions() {
  optionLoading.value = true
  try {
    options.value = await fetchQuotationOptions()
  } catch (error) {
    ElMessage.warning(`报价筛选项加载失败：${getErrorMessage(error)}`)
  } finally {
    optionLoading.value = false
  }
}

function search() {
  page.value = 1
  expiringMetricActive.value = false
  activeMetric.value = filters.display_status ? 'custom' : 'all'
  void Promise.all([loadRows(), loadSummary()])
}

function reset() {
  Object.assign(filters, { search: '', display_status: '', owner_employee_id: '', currency_code: '', valid_to: '' })
  page.value = 1
  activeMetric.value = 'all'
  currentViewLabel.value = '全部报价'
  expiringMetricActive.value = false
  void Promise.all([loadRows(), loadSummary()])
}

function reloadQuotationList() {
  void loadRows()
  void loadSummary()
}

function applyMetric(key: string) {
  activeMetric.value = key
  expiringMetricActive.value = key === 'expiring'
  filters.display_status = {
    draft: 'DRAFT', ready: 'READY_TO_SEND', sent: 'SENT', accepted: 'ACCEPTED',
  }[key] || ''
  page.value = 1
  currentViewLabel.value = metricCards.value.find((item) => item.key === key)?.label || '全部报价'
  void loadRows()
}

function applyPreset(preset: 'mine-ready' | 'expiring') {
  if (preset === 'mine-ready') {
    expiringMetricActive.value = false
    activeMetric.value = 'ready'
    filters.display_status = 'READY_TO_SEND'
    filters.owner_employee_id = authStore.user?.employee?.id || ''
    currentViewLabel.value = '我的待发送'
    page.value = 1
    void Promise.all([loadRows(), loadSummary()])
    return
  }
  currentViewLabel.value = '7 天内到期'
  applyMetric('expiring')
}

function applySavedView(view: SavedView) {
  const definition = view.filter_definition
  expiringMetricActive.value = false
  activeMetric.value = 'custom'
  currentViewLabel.value = view.view_name
  Object.assign(filters, {
    search: typeof definition.q === 'string' ? definition.q : '',
    display_status: typeof definition.display_status === 'string' ? definition.display_status : '',
    owner_employee_id: typeof definition.owner_employee_id === 'string' ? definition.owner_employee_id : '',
    currency_code: typeof definition.currency_code === 'string' ? definition.currency_code : '',
    valid_to: typeof definition.valid_to === 'string' ? definition.valid_to : '',
  })
  if (typeof definition.page_size === 'number') pageSize.value = definition.page_size
  if (view.column_definition.length) {
    Object.keys(visibleColumns).forEach((key) => { visibleColumns[key] = view.column_definition.includes(key) })
  }
  page.value = 1
  void Promise.all([loadRows(), loadSummary()])
}

function currentFilterDefinition(): Record<string, unknown> {
  return Object.fromEntries(Object.entries({
    q: filters.search.trim(),
    display_status: filters.display_status,
    owner_employee_id: filters.owner_employee_id,
    currency_code: filters.currency_code,
    valid_to: filters.valid_to,
    customer_id: typeof route.query.customer_id === 'string' ? route.query.customer_id : '',
    ordering: '-updated_at',
    page_size: pageSize.value,
  }).filter(([, value]) => value !== ''))
}

async function saveCurrentView() {
  const name = savedViewName.value.trim()
  if (!name) {
    ElMessage.warning('请输入视图名称。')
    return
  }
  saveViewLoading.value = true
  try {
    await createQuotationSavedView({
      module_code: 'QUOTATION',
      view_name: name,
      filter_definition: currentFilterDefinition(),
      column_definition: Object.entries(visibleColumns).filter(([, shown]) => shown).map(([key]) => key),
      sort_definition: ['-updated_at'],
    })
    saveDialogVisible.value = false
    savedViewName.value = ''
    ElMessage.success('当前报价视图已保存。')
    await loadSavedViews()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    saveViewLoading.value = false
  }
}

function statusClass(status: string): string {
  return `status--${status.toLowerCase().replaceAll('_', '-')}`
}

function formatAmount(row: QuotationListItem): string {
  const version = row.current_version
  if (!version) return '未填写'
  return `${version.currency_code} ${Number(version.total_amount).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

function formatUpdated(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未记录'
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}`
}

async function exportList() {
  if (!canExport.value) return
  exportLoading.value = true
  try {
    const blob = await exportQuotations(buildQuery())
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `报价列表_${new Date().toISOString().slice(0, 10)}.xlsx`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('报价列表已导出。')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    exportLoading.value = false
  }
}

function openDetail(row: QuotationListItem) {
  void router.push({ name: 'quotation-edit', params: { quotationId: row.id } })
}

function openPreview(row: QuotationListItem) {
  void router.push({ name: 'quotation-preview', params: { quotationId: row.id } })
}

async function deleteQuotationRow(row: QuotationListItem) {
  try {
    const current = await fetchQuotation(row.id)
    await ElMessageBox.confirm(
      `确定永久删除报价「${current.data.quotation_number}」吗？其全部版本、明细、关联样品和任务会一并删除，且无法恢复。`,
      '永久删除报价',
      { type: 'error', confirmButtonText: '确认永久删除', cancelButtonText: '取消' },
    )
    const result = await deleteQuotation(row.id, current.etag)
    ElMessage.success(`报价已永久删除，同时删除 ${result.deleted_count} 条关联数据。`)
    await Promise.all([loadRows(), loadSummary()])
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  }
}

function openVersions(row: QuotationListItem) {
  void router.push({ name: 'quotation-versions', params: { quotationId: row.id } })
}

function openCreate() {
  if (!canCreate.value) return
  if (!authStore.user?.employee) {
    ElMessage.error('当前账号未绑定有效员工档案，不能创建报价。')
    return
  }
  const presetCustomerId = typeof route.query.customer_id === 'string' ? route.query.customer_id : ''
  Object.assign(createForm, { customer_account_id: presetCustomerId, transaction_entity_id: '', subject: '', currency_code: '', valid_until: '' })
  createVisible.value = true
  void Promise.all([loadCreateCustomers(), loadCreateCurrencies()]).then(() => {
    if (createForm.customer_account_id) void loadCreateEntities()
  })
}

async function loadCreateCustomers() {
  createCustomerLoading.value = true
  try {
    createCustomers.value = await fetchQuotationCreationOptions()
  } catch (error) {
    ElMessage.error(`可建报价客户加载失败：${getErrorMessage(error)}`)
  } finally {
    createCustomerLoading.value = false
  }
}

async function loadCreateCurrencies() {
  try {
    createCurrencies.value = await fetchAllMasterDataRecords<Currency>('currencies', { status: 'ACTIVE' })
  } catch (error) {
    ElMessage.error(`可用币种加载失败：${getErrorMessage(error)}`)
  }
}

async function loadCreateEntities() {
  createForm.transaction_entity_id = ''
  if (!createForm.customer_account_id) return
  createEntityLoading.value = true
  try {
    const selected = createCustomers.value.find((customer) => customer.id === createForm.customer_account_id)
    if (!selected) throw new Error('未找到可创建报价的客户。')
    if (selected.entities.length === 1) createForm.transaction_entity_id = selected.entities[0].id
  } catch (error) {
    ElMessage.error(`客户交易主体加载失败：${getErrorMessage(error)}`)
  } finally {
    createEntityLoading.value = false
  }
}

async function submitCreate() {
  const employee = authStore.user?.employee
  if (!employee) return
  if (!createForm.customer_account_id || !createForm.transaction_entity_id || !createForm.subject.trim() || !createForm.currency_code.trim()) {
    ElMessage.warning('请填写客户、交易主体、报价主题和币种。')
    return
  }
  createLoading.value = true
  try {
    const quotation = await createQuotationDraft({
      customer_account_id: createForm.customer_account_id,
      transaction_entity_id: createForm.transaction_entity_id,
      owner_employee_id: employee.id,
      subject: createForm.subject.trim(),
      currency_code: createForm.currency_code.trim().toUpperCase(),
      valid_until: createForm.valid_until || null,
    })
    createVisible.value = false
    ElMessage.success('报价草稿已创建。')
    await router.push({ name: 'quotation-edit', params: { quotationId: quotation.data.id } })
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    createLoading.value = false
  }
}

onBeforeUnmount(() => { disposed = true; listRequest++; summaryRequest++ })
onMounted(async () => {
  await Promise.all([loadRows(), loadSummary(), loadOptions()])
  await loadSavedViews()
  if (route.query.create === '1') openCreate()
})
</script>

<template>
  <section class="quotation-list-page" aria-label="报价列表">
    <header class="quotation-list-page__heading">
      <div class="quotation-list-page__title"><h1>报价列表</h1><span>{{ total }} 份报价</span></div>
      <div class="quotation-list-page__heading-actions">
        <ElButton :loading="exportLoading" :disabled="!canExport" @click="exportList">导出</ElButton>
        <ElButton v-if="canCreate" type="primary" @click="openCreate">＋ 新建报价</ElButton>
      </div>
    </header>

    <div v-loading="summaryLoading" class="quotation-metrics" aria-label="报价统计">
      <button v-for="card in metricCards" :key="card.key" class="quotation-metric" :class="{ 'is-active': activeMetric === card.key }" @click="applyMetric(card.key)">
        <span class="quotation-metric__label">{{ card.label }}</span>
        <b class="quotation-metric__value">{{ card.value }}</b>
      </button>
    </div>

    <section class="quotation-filter">
      <ElForm class="quotation-filter__grid" @submit.prevent="search">
        <ElFormItem><ElInput v-model="filters.search" :prefix-icon="Search" placeholder="搜索客户名称、报价编号" clearable @keyup.enter="search" /></ElFormItem>
        <ElFormItem><ElSelect v-model="filters.display_status" placeholder="报价状态：全部" clearable :loading="optionLoading" @change="expiringMetricActive = false"><ElOption v-for="item in options?.display_statuses" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
        <ElFormItem><ElSelect v-model="filters.owner_employee_id" placeholder="负责人：全部" clearable :loading="optionLoading"><ElOption v-for="item in options?.owners" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem><ElSelect v-model="filters.currency_code" placeholder="币种：全部" clearable :loading="optionLoading"><ElOption v-for="item in options?.currencies" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
        <div class="quotation-filter__actions"><ElButton @click="moreFiltersVisible = !moreFiltersVisible">更多筛选</ElButton><ElButton @click="reset">重置</ElButton></div>
      </ElForm>
      <div v-if="moreFiltersVisible" class="quotation-filter__more">
        <ElDatePicker v-model="filters.valid_to" type="date" value-format="YYYY-MM-DD" placeholder="有效期截至" @change="expiringMetricActive = false" />
        <ElButton type="primary" @click="search">查询</ElButton>
      </div>
    </section>

    <div class="quotation-toolbar">
      <div>
        <span>已选择 {{ selectedRows.length }} 项</span>
        <ElDropdown trigger="click">
          <ElButton>当前视图：{{ currentViewLabel }} <ElIcon><ArrowDown /></ElIcon></ElButton>
          <template #dropdown><ElDropdownMenu><ElDropdownItem @click="reset">全部报价</ElDropdownItem><ElDropdownItem @click="applyPreset('mine-ready')">我的待发送</ElDropdownItem><ElDropdownItem @click="applyPreset('expiring')">7 天内到期</ElDropdownItem><ElDropdownItem v-for="view in savedViews" :key="view.id" @click="applySavedView(view)">{{ view.view_name }}</ElDropdownItem></ElDropdownMenu></template>
        </ElDropdown>
      </div>
      <div>
        <ElButton>最近更新 ↓</ElButton>
        <ElDropdown trigger="click" :hide-on-click="false">
          <ElButton :icon="Setting">列设置</ElButton>
          <template #dropdown>
            <ElDropdownMenu class="quotation-column-menu">
              <ElDropdownItem v-for="(_shown, key) in visibleColumns" :key="key">
                <ElCheckbox v-model="visibleColumns[key]">{{ columnLabels[key] }}</ElCheckbox>
              </ElDropdownItem>
            </ElDropdownMenu>
          </template>
        </ElDropdown>
        <ElButton v-if="canSaveView" @click="saveDialogVisible = true">保存视图</ElButton>
        <ElButton :icon="Refresh" aria-label="刷新报价列表" @click="reloadQuotationList">刷新</ElButton>
      </div>
    </div>

    <ElAlert v-if="errorMessage" class="quotation-error" type="error" :title="errorMessage" :closable="false" show-icon><template #default><ElButton link @click="reloadQuotationList">重新加载</ElButton></template></ElAlert>

    <ElCard class="quotation-table-card" shadow="never">
      <ElTable v-loading="loading" :class="{ 'is-compact': compactTable }" :data="rows" :empty-text="errorMessage ? '报价列表加载失败' : '暂无报价，可点击右上角新建报价。'" @selection-change="(value: QuotationListItem[]) => { selectedRows = value }">
        <ElTableColumn type="selection" width="44" />
        <ElTableColumn prop="quotation_number" label="报价编号" width="190"><template #default="{ row }"><button class="quotation-link" @click="openDetail(row)">{{ row.quotation_number }}</button></template></ElTableColumn>
        <ElTableColumn prop="customer_name" label="客户名称" min-width="308" show-overflow-tooltip />
        <ElTableColumn label="版本" width="64"><template #default="{ row }">{{ row.current_version ? `V${row.current_version.version_number}` : '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="visibleColumns.currency" label="币种" width="74"><template #default="{ row }">{{ row.current_version?.currency_code || '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="visibleColumns.incoterm" label="贸易条款" width="124" show-overflow-tooltip><template #default="{ row }">{{ row.current_version?.incoterm_label || '未填写' }}</template></ElTableColumn>
        <ElTableColumn v-if="visibleColumns.owner" label="负责人" width="92"><template #default="{ row }">{{ row.owner?.display_name || '未分配' }}</template></ElTableColumn>
        <ElTableColumn v-if="visibleColumns.updated" label="最近更新" width="156"><template #default="{ row }">{{ formatUpdated(row.current_version?.updated_at || row.updated_at) }}</template></ElTableColumn>
        <ElTableColumn v-if="visibleColumns.validUntil" label="有效期" width="156"><template #default="{ row }">{{ row.current_version?.valid_until || '未填写' }}</template></ElTableColumn>
        <ElTableColumn v-if="visibleColumns.amount" label="报价金额" width="180" align="right"><template #default="{ row }"><b>{{ formatAmount(row) }}</b></template></ElTableColumn>
        <ElTableColumn label="状态" width="126"><template #default="{ row }"><span class="quotation-status" :class="statusClass(row.display_status)">{{ row.display_status_label }}</span></template></ElTableColumn>
        <ElTableColumn label="操作" width="120" align="center"><template #default="{ row }"><ElDropdown :persistent="false" trigger="click"><button class="row-more" aria-label="报价操作"><ElIcon><MoreFilled /></ElIcon></button><template #dropdown><ElDropdownMenu><ElDropdownItem @click="openPreview(row)">预览报价</ElDropdownItem><ElDropdownItem :disabled="!row.allowed_actions.edit" @click="openDetail(row)">编辑报价</ElDropdownItem><ElDropdownItem @click="openVersions(row)">版本记录</ElDropdownItem><ElDropdownItem v-if="canDelete && authStore.canFor('quotations.delete_quotation', row)" divided @click="deleteQuotationRow(row)">永久删除</ElDropdownItem></ElDropdownMenu></template></ElDropdown></template></ElTableColumn>
        <template #empty>
          <ElEmpty :description="errorMessage ? '报价列表加载失败' : '暂无报价'" :image-size="72">
            <ElButton v-if="!errorMessage && canCreate" type="primary" @click="openCreate">新建报价</ElButton>
            <ElButton v-else-if="errorMessage" @click="reloadQuotationList">重新加载</ElButton>
          </ElEmpty>
        </template>
      </ElTable>
      <div class="quotation-table-card__footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" background layout="sizes, prev, pager, next" :page-sizes="[20, 50, 100]" :total="total" @current-change="() => { void loadRows() }" @size-change="() => { page = 1; void loadRows() }" /></div>
    </ElCard>
    <AppWindowDialog v-model="saveDialogVisible" title="保存当前视图" :width="420" :height="240" :close-on-click-modal="false">
      <ElForm label-position="top"><ElFormItem label="视图名称" required><ElInput v-model="savedViewName" maxlength="50" show-word-limit placeholder="例如：本月待发送报价" /></ElFormItem></ElForm>
      <template #footer><ElButton @click="saveDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="saveViewLoading" @click="saveCurrentView">保存</ElButton></template>
    </AppWindowDialog>
    <AppWindowDialog v-model="createVisible" class="quotation-create-dialog" title="新建报价" :width="840" :height="680" :close-on-click-modal="false">
      <p class="quotation-create-form__lead">创建草稿后，继续填写产品明细和价格。</p>
      <ElForm label-position="top" class="quotation-create-form">
        <ElFormItem label="* 客户"><ElSelect v-model="createForm.customer_account_id" filterable :loading="createCustomerLoading" placeholder="搜索或选择客户" @change="loadCreateEntities"><ElOption v-for="customer in createCustomers" :key="customer.id" :label="customer.account_name" :value="customer.id" /></ElSelect></ElFormItem>
        <ElFormItem label="* 交易主体"><ElSelect v-model="createForm.transaction_entity_id" :loading="createEntityLoading" :disabled="!createForm.customer_account_id" placeholder="请先选择客户"><ElOption v-for="entity in createCustomers.find((customer) => customer.id === createForm.customer_account_id)?.entities || []" :key="entity.id" :label="entity.legal_name" :value="entity.id" /></ElSelect><small>选择该客户下用于报价的公司抬头。</small></ElFormItem>
        <ElFormItem label="* 报价主题"><ElInput v-model="createForm.subject" maxlength="250" placeholder="例如：户外折叠椅报价" /></ElFormItem>
        <div class="quotation-create-form__row"><ElFormItem label="* 币种"><ElSelect v-model="createForm.currency_code" filterable placeholder="请选择币种"><ElOption v-for="item in createCurrencies" :key="item.code" :label="`${item.code} · ${item.chinese_name || item.english_name}`" :value="item.code" /></ElSelect></ElFormItem><ElFormItem label="报价有效期　可选"><ElDatePicker v-model="createForm.valid_until" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" /><small>可不填；填写时不能早于今天。</small></ElFormItem></div>
      </ElForm>
      <template #footer><ElButton @click="createVisible = false">取消</ElButton><ElButton class="quotation-create-form__submit" :loading="createLoading" @click="submitCreate">创建草稿</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
.quotation-list-page { min-width: 0; color: #1f2329; }
.quotation-list-page__heading, .quotation-list-page__title, .quotation-list-page__heading-actions, .quotation-toolbar, .quotation-toolbar > div, .quotation-filter__saved, .quotation-table-card__footer { display: flex; align-items: center; }
.quotation-list-page__heading { min-height: 64px; justify-content: space-between; margin-bottom: 20px; }
.quotation-list-page__title { gap: 48px; }.quotation-list-page__title h1 { margin: 0; font-size: 28px; font-weight: 700; line-height: 40px; }.quotation-list-page__title span { color: #646a73; font-size: 13px; }.quotation-list-page__heading-actions { gap: 12px; }.quotation-list-page__heading-actions :deep(.el-button) { height: 32px; min-width: 72px; }
.quotation-metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; margin-bottom: 24px; }.quotation-metric { height: 68px; display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; border: 1px solid #e4e4e7; border-radius: 8px; color: #1f2329; background: #fff; cursor: pointer; text-align: left; }.quotation-metric.is-active { border-color: #18181b; box-shadow: 0 0 0 1px #18181b inset; }.quotation-metric span { display: grid; gap: 5px; }.quotation-metric small { color: #52525b; font-size: 13px; }.quotation-metric strong { font-size: 20px; line-height: 20px; }.quotation-metric .el-icon { width: 32px; height: 32px; padding: 7px; border-radius: 8px; color: #52525b; background: #f7f7f8; }.quotation-metric.is-active .el-icon { color: #fff; background: #18181b; }
.quotation-filter, .quotation-table-card { overflow: hidden; border-radius: 8px; background: #fff; }.quotation-filter { height: 112px; box-sizing: border-box; margin-bottom: 16px; border: 0; box-shadow: 0 4px 12px rgb(0 0 0 / 6%); }.quotation-filter :deep(.el-card__body) { height: 100%; box-sizing: border-box; background: #fff; }.quotation-filter__grid { display: grid; grid-template-columns: 260px repeat(4, minmax(140px, 1fr)) auto; gap: 12px; align-items: end; }.quotation-filter__grid :deep(.el-form-item) { display: block; min-width: 0; margin: 0; }.quotation-filter__grid :deep(.el-form-item__label) { height: 18px; padding: 0 0 4px; color: #52525b; font-size: 12px; line-height: 14px; }.quotation-filter__grid :deep(.el-form-item__content), .quotation-filter__grid :deep(.el-select), .quotation-filter__grid :deep(.el-date-editor) { width: 100%; }.quotation-filter__actions { display: flex; align-items: center; gap: 8px; height: 32px; }.quotation-filter__actions :deep(.el-button) { height: 32px; margin: 0; }.quotation-filter__saved { flex-wrap: nowrap; gap: 4px; min-height: 24px; margin-top: 8px; overflow-x: auto; overflow-y: hidden; color: #71717a; font-size: 12px; white-space: nowrap; }.quotation-filter__saved :deep(.el-button) { height: 24px; flex: none; margin: 0; padding: 0 8px; color: #52525b; background: #f7f7f8; }.quotation-filter__saved :deep(.el-button--primary) { color: #1f2329; background: transparent; }.quotation-filter__permission-note { margin-left: 4px; color: #8f959e; }
.quotation-toolbar { justify-content: space-between; min-height: 40px; margin-bottom: 5px; }.quotation-toolbar > div { gap: 8px; }.quotation-toolbar span { margin-right: 8px; color: #646a73; font-size: 13px; }.quotation-toolbar :deep(.el-button) { height: 32px; margin: 0; }.quotation-error { margin-bottom: 12px; }
.quotation-table-card { min-height: calc(100vh - 456px); border: 1px solid #e4e4e7; box-shadow: none; }.quotation-table-card :deep(.el-card__body), .quotation-table-card :deep(.el-table), .quotation-table-card :deep(.el-table__inner-wrapper) { background: #fff; }.quotation-table-card :deep(.el-card__body) { padding: 0; }.quotation-table-card :deep(.el-table__header th.el-table__cell) { height: 44px; padding-top: 0; padding-bottom: 0; color: #1f2329; background: #f7f7f8; }.quotation-table-card :deep(.el-table__body td.el-table__cell) { height: 48px; padding-top: 0; padding-bottom: 0; background: #fff; }.quotation-table-card :deep(.el-table__row:hover > td.el-table__cell) { background: #fafafa; }.quotation-link { max-width: 100%; overflow: hidden; padding: 0; border: 0; color: #3f3f46; background: transparent; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }.quotation-link:hover { color: #18181b; text-decoration: underline; }.quotation-status { display: inline-flex; align-items: center; height: 24px; padding: 0 12px; border-radius: 4px; font-size: 12px; white-space: nowrap; }.status--draft, .status--locked, .status--superseded { color: #646a73; background: #f2f3f5; }.status--ready-to-send, .status--expired { color: #dc7609; background: #fffcf0; }.status--sent { color: #0973dc; background: #f0f8ff; }.status--accepted { color: #18a058; background: #ecf8f1; }.status--rejected, .status--withdrawn { color: #f04438; background: #fef0f0; }.quotation-table-card :deep(.el-dropdown) { margin-left: 8px; }.quotation-table-card :deep(.el-button--small) { min-width: 52px; color: #3f3f46; border-color: #d4d4d8; }
.quotation-table-card :deep(.el-table.is-compact .el-table__body td.el-table__cell) { height: 40px; }
.quotation-table-card__footer { justify-content: space-between; min-height: 56px; padding: 10px 16px; border-top: 1px solid #e4e4e7; color: #52525b; font-size: 13px; }.quotation-table-card__footer :deep(.el-pager li.is-active) { color: #fff; background: #18181b; }
.quotation-filter :deep(.el-card__body) { padding: 8px 16px 6px; }
.quotation-create-form { margin-top:16px; }.quotation-create-form :deep(.el-select),.quotation-create-form :deep(.el-date-editor) { width:100%; }.quotation-create-form__row { display:grid; grid-template-columns:120px 1fr; gap:12px; }.quotation-create-form__submit { color:#fff!important; border-color:#18181b!important; background:#18181b!important; }
@media (max-width: 1150px) { .quotation-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }.quotation-filter__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.quotation-filter__actions { grid-column: span 3; }.quotation-list-page__title { gap: 20px; } }
@media (max-width: 900px) { .quotation-list-page__heading, .quotation-toolbar, .quotation-table-card__footer { align-items: flex-start; flex-direction: column; gap: 10px; }.quotation-list-page__heading-actions { align-self: flex-end; }.quotation-filter__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.quotation-filter__actions { grid-column: span 2; }.quotation-table-card :deep(.el-table) { width: max-content; min-width: 100%; } }
@media (max-width: 600px) { .quotation-metrics, .quotation-filter__grid { grid-template-columns: 1fr; }.quotation-filter__actions { grid-column: auto; }.quotation-list-page__title { align-items: flex-start; flex-direction: column; gap: 2px; }.quotation-list-page__title h1 { font-size: 24px; }.quotation-toolbar > div { flex-wrap: wrap; }.quotation-list-page__heading-actions { align-self: stretch; }.quotation-list-page__heading-actions :deep(.el-button) { flex: 1; } }

/* QUO-V2-01 报价列表 / 1920 · 已确认方向 */
.quotation-list-page {
  --quotation-accent: #c84e28;
  height: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  color: #1f1d18;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
}
.quotation-list-page__heading { height: 48px; min-height: 48px; flex: none; margin: 0; }
.quotation-list-page__title { align-items: baseline; gap: 48px; }
.quotation-list-page__title h1 { font-family: 'Noto Serif SC', 'STSong', serif; font-size: 36px; font-weight: 600; line-height: 48px; }
.quotation-list-page__title span { color: #6f6a61; font-size: 12px; }
.quotation-list-page__heading-actions { gap: 12px; }
.quotation-list-page__heading-actions :deep(.el-button) { width: 110px; height: 36px; margin: 0; border-color: #ddd6c9; border-radius: 5px; background: #fcfbf7; }
.quotation-list-page__heading-actions :deep(.el-button--primary) { width: 140px; color: #faf8f2; border-color: var(--quotation-accent); background: var(--quotation-accent); }
.quotation-metrics { height: 48px; flex: none; grid-template-columns: repeat(6, minmax(124px, 1fr)); gap: 0; margin: 0; overflow-x: auto; overflow-y: hidden; background: #efe8dd; scrollbar-width: none; }
.quotation-metrics::-webkit-scrollbar { display: none; }
.quotation-metric { position: relative; height: 48px; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 1px; padding: 0 10px; border: 0; border-radius: 0; color: #6f6a61; background: transparent; box-shadow: none; cursor: pointer; font-size: 12px; line-height: 18px; text-align: center; white-space: nowrap; }
.quotation-metric__label,.quotation-metric__value { display: block; }
.quotation-metric__value { color: #1f1d18; font-size: 14px; font-weight: 500; line-height: 18px; }
.quotation-metric.is-active { color: #1f1d18; border: 0; background: transparent; box-shadow: none; font-weight: 600; }
.quotation-metric.is-active::after { position: absolute; right: 0; bottom: 0; left: 0; height: 4px; background: var(--quotation-accent); content: ''; }
.quotation-filter { position: relative; height: auto; flex: none; margin: 16px 0 0; overflow: visible; border: 0; border-radius: 0; background: transparent; box-shadow: none; }
.quotation-filter__grid { grid-template-columns: minmax(320px, 410px) 160px 142px 176px 224px; align-items: center; gap: 14px; }
.quotation-filter__grid :deep(.el-form-item) { min-width: 0; margin: 0; }
.quotation-filter__grid :deep(.el-form-item__content),.quotation-filter__grid :deep(.el-select) { width: 100%; }
.quotation-filter :deep(.el-input__wrapper),.quotation-filter :deep(.el-select__wrapper) { min-height: 38px; border-radius: 5px; background: #fcfbf7; box-shadow: 0 0 0 1px #ddd6c9 inset; }
.quotation-filter__actions { height: 38px; display: grid; grid-template-columns: 130px 80px; gap: 14px; }
.quotation-filter__actions :deep(.el-button) { height: 38px; margin: 0; border-color: #ddd6c9; border-radius: 5px; color: #1f1d18; background: #fcfbf7; }
.quotation-filter__more { position: absolute; z-index: 8; top: 46px; right: 94px; width: 360px; display: flex; gap: 10px; padding: 14px; border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7; box-shadow: 0 10px 24px rgba(31,29,24,.12); }
.quotation-filter__more :deep(.el-date-editor) { width: 230px; }
.quotation-filter__more :deep(.el-button--primary) { border-color: var(--quotation-accent); background: var(--quotation-accent); }
.quotation-toolbar { height: 72px; min-height: 72px; flex: none; margin: 0; }
.quotation-toolbar > div { gap: 12px; }
.quotation-toolbar span { margin-right: 14px; color: #6f6a61; font-size: 12px; }
.quotation-toolbar :deep(.el-button) { height: 36px; margin: 0; border-color: #ddd6c9; border-radius: 5px; color: #1f1d18; background: #fcfbf7; }
.quotation-toolbar > div:first-child :deep(.el-button) { width: 224px; justify-content: space-between; color: #6f6a61; }
.quotation-toolbar > div:last-child :deep(.el-button) { min-width: 104px; }
.quotation-table-card { min-height: 0; flex: 1; display: flex; overflow: hidden; border: 0; border-radius: 5px; background: #fcfbf7; box-shadow: none; }
.quotation-table-card :deep(.el-card__body) { min-height: 0; flex: 1; display: flex; flex-direction: column; padding: 0; background: #fcfbf7; }
.quotation-table-card :deep(.el-table) { --el-table-border-color: #eae4da; --el-table-header-bg-color: #efe8dd; --el-table-row-hover-bg-color: #f8f3eb; flex: 1; color: #1f1d18; background: #fcfbf7; }
.quotation-table-card :deep(.el-table__inner-wrapper::before) { display: none; }
.quotation-table-card :deep(.el-table__header th.el-table__cell) { height: 44px; padding: 0; color: #6f6a61; background: #efe8dd; font-size: 12px; font-weight: 500; }
.quotation-table-card :deep(.el-table__body td.el-table__cell) { height: 52px; padding: 0; background: #fcfbf7; font-size: 12px; }
.quotation-table-card :deep(.cell) { padding-right: 16px; padding-left: 16px; }
.quotation-table-card :deep(.el-table-column--selection .cell) { padding-right: 9px; padding-left: 9px; }
.quotation-link { color: var(--quotation-accent); }
.quotation-link:hover { color: var(--quotation-accent); }
.quotation-status { min-width: 72px; height: 24px; justify-content: center; padding: 0 8px; border-radius: 999px; }
.status--draft,.status--locked,.status--superseded { color: #5e5d59; background: #f0eee6; }
.status--ready-to-send { color: #b8781e; background: #faeedb; }
.status--sent { color: #3898ec; background: #e6f3fd; }
.status--accepted { color: #4f7d4b; background: #e8f0e2; }
.status--expired,.status--rejected,.status--withdrawn { color: #b8442c; background: #f7e5e4; }
.row-more { width: 32px; height: 32px; display: inline-grid; place-items: center; padding: 0; border: 0; color: #1f1d18; background: transparent; cursor: pointer; }
.row-more .el-icon { font-size: 17px; }
.quotation-table-card__footer { height: 52px; min-height: 52px; flex: none; padding: 0 16px; border-top: 1px solid #eae4da; color: #6f6a61; font-size: 12px; }
.quotation-table-card__footer :deep(.el-pagination) { --el-pagination-hover-color: var(--quotation-accent); }
.quotation-table-card__footer :deep(.el-select__wrapper),.quotation-table-card__footer :deep(.btn-prev),.quotation-table-card__footer :deep(.btn-next),.quotation-table-card__footer :deep(.el-pager li) { height: 36px; border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7; }
.quotation-table-card__footer :deep(.el-pager li.is-active) { color: #1f1d18; border-color: var(--quotation-accent); background: #fcfbf7; }
.quotation-create-form { margin-top: 24px; }
.quotation-create-form__lead { margin: -8px 0 0; color: #6f6a61; font-size: 14px; }
.quotation-create-form :deep(.el-form-item) { margin-bottom: 22px; }
.quotation-create-form :deep(.el-form-item__label) { padding-bottom: 8px; color: #1f1d18; font-size: 14px; font-weight: 600; }
.quotation-create-form :deep(.el-select),.quotation-create-form :deep(.el-date-editor) { width: 100%; }
.quotation-create-form :deep(.el-input__wrapper),.quotation-create-form :deep(.el-select__wrapper) { height: 32px; min-height: 32px; border-radius: 4px; background: #fcfbf7; box-shadow: 0 0 0 1px #ddd6c9 inset; }
.quotation-create-form small { display: block; margin-top: 7px; color: #6f6a61; font-size: 12px; }
.quotation-create-form__row { grid-template-columns: 1fr 1fr; gap: 32px; }
:global(.quotation-create-dialog) { border-radius: 6px; background: #fcfbf7; }
:global(.quotation-create-dialog .el-dialog__header) { margin: 0; padding: 32px 44px 0; }
:global(.quotation-create-dialog .el-dialog__title) { font-family: 'Noto Serif SC', 'STSong', serif; font-size: 30px; font-weight: 600; }
:global(.quotation-create-dialog .el-dialog__body) { padding: 14px 44px 10px; }
:global(.quotation-create-dialog .el-dialog__footer) { margin: 0 44px; padding: 20px 0 24px; border-top: 1px solid #ddd6c9; }
:global(.quotation-create-dialog .el-dialog__footer .el-button) { width: 108px; height: 44px; border-radius: 4px; }
:global(.quotation-create-dialog .quotation-create-form__submit) { width: 140px!important; color: #fff!important; border-color: #c84e28!important; background: #c84e28!important; }
.quotation-list-page { container-type: inline-size; }
@container (max-width: 1077px) {
  .quotation-filter__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .quotation-filter__actions { grid-column: span 2; }
}
@container (max-width: 700px) {
  .quotation-filter__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .quotation-filter__actions { grid-column: span 2; }
}
@container (max-width: 450px) {
  .quotation-filter__grid { grid-template-columns: minmax(0, 1fr); }
  .quotation-filter__actions { grid-column: auto; }
}
</style>
