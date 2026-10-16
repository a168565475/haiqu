<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { ArrowDown, Search, Setting } from '@element-plus/icons-vue'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import CustomerDetailListShell, { type CustomerDetailMetric } from './CustomerDetailListShell.vue'
import CustomerActivityTag from './CustomerActivityTag.vue'
import { fetchInquiries, fetchInquiryMetrics, fetchInquiryOptions } from '@/api/inquiries'
import { fetchQuotations, fetchQuotationOptions, fetchQuotationSummary } from '@/api/quotations'
import { fetchSampleOptions, fetchSamples, fetchSampleStats } from '@/api/samples'
import { fetchSalesOrderOptions, fetchSalesOrders } from '@/api/salesOrders'
import { createSavedView, fetchSavedViews } from '@/api/savedViews'
import { useAuthStore } from '@/stores/auth'
import type { CustomerDetail } from '@/types/customer'
import type { InquiryMetrics, InquiryOptions, InquiryRow } from '@/types/inquiry'
import type { QuotationListItem, QuotationListOptions, QuotationSummary } from '@/types/quotation'
import type { SampleListItem, SampleOptions, SampleStats } from '@/types/sample'
import type { SalesOrderListItem, SalesOrderOptions } from '@/types/salesOrder'
import type { SavedView, SavedViewCreateInput } from '@/types/savedView'

type RecordKind = 'inquiries' | 'quotations' | 'samples' | 'orders'
type Row = InquiryRow | QuotationListItem | SampleListItem | SalesOrderListItem

const props = defineProps<{
  kind: RecordKind
  customerId: string
  customerName: string
  salesMetrics?: Pick<
    CustomerDetail,
    'last_12m_sales_amount' | 'last_12m_sales_order_count' | 'lifetime_sales_order_count'
  >
}>()

const router = useRouter()
const auth = useAuthStore()
let listRequestId = 0
let contextRequestId = 0
const loading = ref(false)
const error = ref('')
const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const selectedRows = ref<Row[]>([])
const saveVisible = ref(false)
const saveName = ref('')
const saveLoading = ref(false)
const savedViews = ref<SavedView[]>([])
const inquiryMetrics = ref<InquiryMetrics | null>(null)
const quotationSummary = ref<QuotationSummary | null>(null)
const sampleStats = ref<SampleStats | null>(null)
const inquiryOptions = ref<InquiryOptions | null>(null)
const quotationOptions = ref<QuotationListOptions | null>(null)
const sampleOptions = ref<SampleOptions | null>(null)
const salesOrderOptions = ref<SalesOrderOptions | null>(null)
const filters = reactive({ q: '', status: '', ownerId: '', subtype: '', date: '' })

const allColumns: Record<RecordKind, Array<{ key: string; label: string }>> = {
  inquiries: [
    { key: 'subject', label: '主题' }, { key: 'product', label: '产品需求' }, { key: 'status', label: '状态' },
    { key: 'owner', label: '负责人' }, { key: 'received', label: '接收时间' }, { key: 'due', label: '期望回复' },
  ],
  quotations: [
    { key: 'subject', label: '报价主题' }, { key: 'version', label: '版本' }, { key: 'amount', label: '报价金额' },
    { key: 'status', label: '状态' }, { key: 'owner', label: '负责人' }, { key: 'updated', label: '更新时间' },
  ],
  samples: [
    { key: 'type', label: '样品类型' }, { key: 'summary', label: '样品明细' }, { key: 'status', label: '状态' },
    { key: 'shipping', label: '物流状态' }, { key: 'owner', label: '负责人' }, { key: 'requested', label: '申请时间' },
  ],
  orders: [
    { key: 'po', label: '客户 PO' }, { key: 'status', label: '状态' }, { key: 'amount', label: '订单金额' },
    { key: 'owner', label: '业务员' }, { key: 'delivery', label: '下次交付' }, { key: 'updated', label: '更新时间' },
  ],
}

const visibleColumns = reactive<Record<string, boolean>>({})
const config = computed(() => ({
  inquiries: { title: '客户询盘', description: '当前客户的询盘进度、负责人及响应时效', primary: '新建询盘' },
  quotations: { title: '客户报价', description: '当前客户的报价版本、金额及确认状态', primary: '新建报价' },
  samples: { title: '客户样品', description: '当前客户的样品申请、费用、物流及反馈状态', primary: '新增样品申请' },
  orders: { title: '客户订单', description: '当前客户的真实销售订单与交付进度', primary: '刷新 ERP 快照' },
})[props.kind])

const moduleCode = computed<SavedViewCreateInput['module_code'] | ''>(() => ({
  inquiries: 'INQUIRY' as const,
  quotations: 'QUOTATION' as const,
  samples: 'SAMPLE_REQUEST' as const,
  orders: '' as const,
})[props.kind])
const canReadSavedViews = computed(() => Boolean(moduleCode.value) && auth.hasPermission('preferences.view_savedview'))
const canSaveView = computed(() => canReadSavedViews.value && auth.hasPermission('preferences.add_savedview'))
const canPrimary = computed(() => {
  if (props.kind === 'inquiries') return auth.hasPermission('inquiries.add_inquiry')
  if (props.kind === 'quotations') return auth.hasPermission('quotations.add_quotation')
  if (props.kind === 'samples') return auth.hasPermission('samples.add_samplerequest')
  return true
})
const hasColumn = (key: string) => visibleColumns[key] !== false

const statusOptions = computed(() => {
  if (props.kind === 'inquiries') return inquiryOptions.value?.statuses.map(item => ({ value: item.code, label: item.display_name })) || []
  if (props.kind === 'quotations') return quotationOptions.value?.display_statuses || []
  if (props.kind === 'samples') return sampleOptions.value?.statuses || []
  return salesOrderOptions.value?.statuses || []
})
const ownerOptions = computed(() => {
  if (props.kind === 'inquiries') return inquiryOptions.value?.owners.map(item => ({ value: item.id, label: item.display_name })) || []
  if (props.kind === 'quotations') return quotationOptions.value?.owners.map(item => ({ value: item.id, label: item.display_name })) || []
  if (props.kind === 'samples') return sampleOptions.value?.owners.map(item => ({ value: item.id, label: item.display_name })) || []
  return salesOrderOptions.value?.employees.map(item => ({ value: item.id, label: item.display_name })) || []
})
const subtypeOptions = computed(() => {
  if (props.kind === 'quotations') return quotationOptions.value?.currencies || []
  if (props.kind === 'samples') return sampleOptions.value?.sample_types || []
  if (props.kind === 'orders') return salesOrderOptions.value?.source_types || []
  return []
})

const metrics = computed<CustomerDetailMetric[]>(() => {
  if (props.kind === 'inquiries') return [
    { key: 'all', label: '全部询盘', value: total.value },
    { key: 'quoting', label: '报价中', value: inquiryMetrics.value?.quoting ?? 0 },
    { key: 'waiting', label: '待客户回复', value: inquiryMetrics.value?.awaiting_customer ?? 0 },
    { key: 'risk', label: 'SLA 风险', value: inquiryMetrics.value?.due_soon ?? 0, tone: 'danger' },
    { key: 'today', label: '今日新增', value: inquiryMetrics.value?.today_new ?? 0 },
  ]
  if (props.kind === 'quotations') return [
    { key: 'all', label: '全部报价', value: quotationSummary.value?.all ?? total.value },
    { key: 'effective', label: '有效报价', value: Math.max(0, (quotationSummary.value?.all ?? 0) - (quotationSummary.value?.draft ?? 0)) },
    { key: 'confirm', label: '待客户确认', value: quotationSummary.value?.sent ?? 0, tone: 'warning' },
    { key: 'accepted', label: '已接受', value: quotationSummary.value?.accepted ?? 0, tone: 'success' },
    { key: 'expiring', label: '7 天内到期', value: quotationSummary.value?.expiring_within_7_days ?? 0, tone: 'danger' },
  ]
  if (props.kind === 'samples') return [
    { key: 'all', label: '样品申请', value: sampleStats.value?.all ?? total.value },
    { key: 'transit', label: '运输中', value: sampleStats.value?.in_transit ?? 0 },
    { key: 'feedback', label: '待反馈', value: sampleStats.value?.pending_feedback ?? 0, tone: 'warning' },
    { key: 'fee', label: '费用待确认', value: sampleStats.value?.pending_payment ?? 0 },
    { key: 'done', label: '已完成', value: sampleStats.value?.finished ?? 0, tone: 'success' },
  ]
  const sales = props.salesMetrics
  return [
    { key: 'count', label: '近 12 个月订单', value: sales?.last_12m_sales_order_count ?? 0 },
    { key: 'sales', label: '近 12 个月销售额', value: `CNY ${formatMoney(sales?.last_12m_sales_amount)}` },
    { key: 'all', label: '全部有效订单', value: sales?.lifetime_sales_order_count ?? 0 },
    { key: 'delivery', label: '待交付', value: orderRows.value.filter(item => item.next_delivery_date).length, tone: 'warning' },
    { key: 'draft', label: '草稿', value: orderRows.value.filter(item => item.status === 'DRAFT').length },
  ]
})

const inquiryRows = computed(() => rows.value as InquiryRow[])
const quotationRows = computed(() => rows.value as QuotationListItem[])
const sampleRows = computed(() => rows.value as SampleListItem[])
const orderRows = computed(() => rows.value as SalesOrderListItem[])

function resetColumns() {
  Object.keys(visibleColumns).forEach(key => delete visibleColumns[key])
  for (const item of allColumns[props.kind]) visibleColumns[item.key] = true
  try {
    const stored = JSON.parse(localStorage.getItem(`haiqu.customer-detail.${props.kind}.columns`) || '[]') as string[]
    if (stored.length) for (const item of allColumns[props.kind]) visibleColumns[item.key] = stored.includes(item.key)
  } catch { /* 损坏的本地列配置按默认列恢复。 */ }
}

function persistColumns() {
  const value = allColumns[props.kind].filter(item => visibleColumns[item.key]).map(item => item.key)
  localStorage.setItem(`haiqu.customer-detail.${props.kind}.columns`, JSON.stringify(value))
}

function errorMessage(value: unknown) {
  if (!(value instanceof AxiosError)) return '数据加载失败，请稍后重试。'
  if (!value.response) return '网络连接异常，请检查后端服务。'
  const detail = (value.response.data as { detail?: string; error?: { message?: string } })
  if (value.response.status === 403) return '当前账号没有查看此客户业务记录的权限。'
  return detail.error?.message || detail.detail || '数据加载失败，请稍后重试。'
}

function buildQuery() {
  const common: Record<string, unknown> = { customer_id: props.customerId, page: page.value, page_size: pageSize.value }
  if (filters.q.trim()) common.q = filters.q.trim()
  if (filters.status) common.status = filters.status
  if (filters.ownerId) common.owner_employee_id = filters.ownerId
  if (props.kind === 'inquiries') {
    common.ordering = '-received_at'
    if (filters.date) { common.received_from = `${filters.date}T00:00:00+08:00`; common.received_to = `${filters.date}T23:59:59+08:00` }
  } else if (props.kind === 'quotations') {
    common.ordering = '-updated_at'
    if (filters.status) { common.display_status = filters.status; delete common.status }
    if (filters.subtype) common.currency_code = filters.subtype
    if (filters.date) common.valid_to = filters.date
  } else if (props.kind === 'samples') {
    common.ordering = '-requested_at'
    if (filters.q.trim()) { common.search = common.q; delete common.q }
    if (filters.subtype) common.sample_type = filters.subtype
    if (filters.date) common.requested_to = filters.date
  } else {
    if (filters.subtype) common.source_type = filters.subtype
    delete common.owner_employee_id
  }
  return common
}

async function loadRows() {
  const request = ++listRequestId
  loading.value = true
  error.value = ''
  selectedRows.value = []
  try {
    const query = buildQuery()
    if (props.kind === 'inquiries') {
      const result = await fetchInquiries(query)
      if (request !== listRequestId) return
      rows.value = result.data; total.value = result.meta.total
    } else if (props.kind === 'quotations') {
      const result = await fetchQuotations(query as unknown as Parameters<typeof fetchQuotations>[0])
      if (request !== listRequestId) return
      rows.value = result.data; total.value = result.meta.total
    } else if (props.kind === 'samples') {
      const result = await fetchSamples(query as unknown as Parameters<typeof fetchSamples>[0])
      if (request !== listRequestId) return
      rows.value = result.data; total.value = result.meta.total
    } else {
      const result = await fetchSalesOrders(query)
      if (request !== listRequestId) return
      rows.value = result.data; total.value = result.meta.total
    }
  } catch (value) {
    if (request !== listRequestId) return
    rows.value = []; total.value = 0; error.value = errorMessage(value)
  } finally {
    if (request === listRequestId) loading.value = false
  }
}

async function loadContext() {
  const request = ++contextRequestId
  inquiryMetrics.value = null; quotationSummary.value = null; sampleStats.value = null
  const query = { customer_id: props.customerId }
  const tasks: Promise<unknown>[] = []
  if (props.kind === 'inquiries') tasks.push(
    fetchInquiryOptions(query).then(value => { if (request !== contextRequestId) return; inquiryOptions.value = value }),
    fetchInquiryMetrics(query).then(value => { if (request !== contextRequestId) return; inquiryMetrics.value = value }),
  )
  if (props.kind === 'quotations') tasks.push(
    fetchQuotationOptions().then(value => { if (request !== contextRequestId) return; quotationOptions.value = value }),
    fetchQuotationSummary(query).then(value => { if (request !== contextRequestId) return; quotationSummary.value = value }),
  )
  if (props.kind === 'samples') tasks.push(
    fetchSampleOptions().then(value => { if (request !== contextRequestId) return; sampleOptions.value = value }),
    fetchSampleStats(query).then(value => { if (request !== contextRequestId) return; sampleStats.value = value }),
  )
  if (props.kind === 'orders') tasks.push(fetchSalesOrderOptions().then(value => { if (request !== contextRequestId) return; salesOrderOptions.value = value }))
  if (canReadSavedViews.value && moduleCode.value) tasks.push(fetchSavedViews(moduleCode.value).then(value => { if (request !== contextRequestId) return; savedViews.value = value }))
  const results = await Promise.allSettled(tasks)
  if (request !== contextRequestId) return
  if (results.some(item => item.status === 'rejected')) ElMessage.warning('部分筛选项或统计数据暂时不可用，列表数据不受影响。')
}

async function refreshAll() { await Promise.all([loadRows(), loadContext()]) }
function search() { page.value = 1; void loadRows() }
function reset() { Object.assign(filters, { q: '', status: '', ownerId: '', subtype: '', date: '' }); page.value = 1; void loadRows() }
function updatePage(value: number) { page.value = value; void loadRows() }
function updatePageSize(value: number) { pageSize.value = value; page.value = 1; void loadRows() }

function handlePrimary() {
  if (props.kind === 'orders') { void refreshAll(); return }
  if (props.kind === 'inquiries') { void router.push({ name: 'inquiry-create', query: { customer_id: props.customerId } }); return }
  if (props.kind === 'quotations') { void router.push({ name: 'quotations', query: { customer_id: props.customerId, create: '1' } }); return }
  void router.push({ name: 'sample-new', query: { customer_id: props.customerId } })
}

function openRow(row: Row) {
  if (props.kind === 'inquiries') void router.push({ name: 'inquiry-detail', params: { inquiryId: row.id } })
  if (props.kind === 'quotations') void router.push({ name: 'quotation-edit', params: { quotationId: row.id } })
  if (props.kind === 'samples') void router.push({ name: 'sample-detail', params: { sampleId: row.id } })
  if (props.kind === 'orders') void router.push({ name: 'sales-order-detail', params: { orderId: row.id } })
}

function currentFilterDefinition() {
  const query = buildQuery()
  delete query.page
  if (props.kind === 'samples' && query.search) { query.q = query.search; delete query.search }
  return query
}

async function saveView() {
  if (!canSaveView.value) return
  if (!saveName.value.trim() || !moduleCode.value) { ElMessage.warning('请输入视图名称。'); return }
  saveLoading.value = true
  try {
    await createSavedView({
      module_code: moduleCode.value,
      view_name: saveName.value.trim(),
      filter_definition: currentFilterDefinition(),
      column_definition: allColumns[props.kind].filter(item => visibleColumns[item.key]).map(item => item.key),
      sort_definition: [String(buildQuery().ordering || '-updated_at')],
    })
    saveVisible.value = false; saveName.value = ''; ElMessage.success('视图已保存。')
    savedViews.value = await fetchSavedViews(moduleCode.value)
  } catch (value) { ElMessage.error(errorMessage(value)) } finally { saveLoading.value = false }
}

function applySavedView(view: SavedView) {
  const value = view.filter_definition
  filters.q = String(value.q || '')
  filters.status = String(value.status || value.display_status || '')
  filters.ownerId = String(value.owner_employee_id || '')
  filters.subtype = String(value.currency_code || value.sample_type || '')
  filters.date = String(value.valid_to || value.requested_to || '').slice(0, 10)
  if (typeof value.page_size === 'number') pageSize.value = value.page_size
  if (view.column_definition.length) for (const item of allColumns[props.kind]) visibleColumns[item.key] = view.column_definition.includes(item.key)
  page.value = 1; void loadRows()
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}

function formatMoney(value: string | null | undefined) {
  const number = Number(value || 0)
  return Number.isFinite(number) ? new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(number) : '0'
}

function statusTone(status: string): 'success' | 'info' | 'warning' | 'danger' | 'neutral' {
  const success = ['ACCEPTED', 'COMPLETED', 'FINISHED', 'DELIVERED', 'CONFIRMED']
  const danger = ['REJECTED', 'CANCELLED', 'LOST', 'OVERDUE']
  const warning = ['PENDING', 'DRAFT', 'QUOTING', 'SENT', 'FULFILLING']
  if (success.includes(status)) return 'success'
  if (danger.includes(status)) return 'danger'
  if (warning.includes(status)) return 'warning'
  return status ? 'info' : 'neutral'
}

watch(() => [props.kind, props.customerId], () => {
  rows.value = []; total.value = 0; selectedRows.value = []
  Object.assign(filters, { q: '', status: '', ownerId: '', subtype: '', date: '' })
  page.value = 1; resetColumns(); void refreshAll()
})
onBeforeUnmount(() => { listRequestId++; contextRequestId++ })
onMounted(() => { resetColumns(); void refreshAll() })
</script>

<template>
  <CustomerDetailListShell
    :title="config.title"
    :description="config.description"
    :metrics="metrics"
    :primary-label="config.primary"
    :primary-disabled="!canPrimary"
    :primary-in-toolbar="props.kind !== 'orders'"
    :loading="loading"
    :error="error"
    :selected-count="selectedRows.length"
    :total="total"
    :page="page"
    :page-size="pageSize"
    :save-view-enabled="canSaveView"
    @primary="handlePrimary"
    @refresh="refreshAll"
    @save-view="saveVisible = true"
    @update-page="updatePage"
    @update-page-size="updatePageSize"
  >
    <template #filters>
      <div class="customer-record-filters">
        <ElInput v-model="filters.q" class="customer-record-filters__search" clearable :prefix-icon="Search" :placeholder="`搜索${config.title.replace('客户', '')}编号、主题、产品`" @keyup.enter="search" />
        <ElSelect v-model="filters.status" clearable placeholder="状态：全部">
          <ElOption v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
        </ElSelect>
        <ElSelect v-if="props.kind !== 'orders'" v-model="filters.ownerId" clearable filterable placeholder="负责人：全部">
          <ElOption v-for="item in ownerOptions" :key="item.value" :label="item.label" :value="item.value" />
        </ElSelect>
        <ElSelect v-if="props.kind !== 'inquiries'" v-model="filters.subtype" clearable :placeholder="props.kind === 'quotations' ? '币种：全部' : props.kind === 'samples' ? '样品类型：全部' : '订单来源：全部'">
          <ElOption v-for="item in subtypeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </ElSelect>
        <ElDatePicker v-if="props.kind !== 'orders'" v-model="filters.date" type="date" value-format="YYYY-MM-DD" :placeholder="props.kind === 'quotations' ? '有效期至' : props.kind === 'samples' ? '申请日期至' : '接收日期'" />
        <ElButton type="primary" @click="search">查询</ElButton>
        <ElButton @click="reset">重置</ElButton>
      </div>
    </template>

    <template #saved-views>
      <ElDropdown v-if="savedViews.length" trigger="click" @command="applySavedView">
        <ElButton>已存视图 <ElIcon><ArrowDown /></ElIcon></ElButton>
        <template #dropdown><ElDropdownMenu><ElDropdownItem v-for="view in savedViews" :key="view.id" :command="view">{{ view.view_name }}</ElDropdownItem></ElDropdownMenu></template>
      </ElDropdown>
    </template>

    <template #column-settings>
      <ElPopover placement="bottom-end" trigger="click" :width="180">
        <template #reference><ElButton :icon="Setting">列设置</ElButton></template>
        <div class="customer-record-columns">
          <ElCheckbox v-for="item in allColumns[props.kind]" :key="item.key" v-model="visibleColumns[item.key]" @change="persistColumns">{{ item.label }}</ElCheckbox>
        </div>
      </ElPopover>
    </template>

    <template #table>
      <ElTable class="scroll-actions-table" v-if="props.kind === 'inquiries'" :data="inquiryRows" row-key="id" border empty-text="当前客户暂无询盘" @selection-change="selectedRows = $event">
        <ElTableColumn type="selection" width="48" /><ElTableColumn prop="inquiry_number" label="询盘编号" width="150" />
        <ElTableColumn v-if="hasColumn('subject')" prop="subject" label="主题" min-width="230" show-overflow-tooltip />
        <ElTableColumn v-if="hasColumn('product')" label="产品需求" min-width="210" show-overflow-tooltip><template #default="{ row }">{{ row.product_summary?.first_description || '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('status')" label="状态" width="120"><template #default="{ row }"><CustomerActivityTag :label="row.status_display" :tone="statusTone(row.status)" /></template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('owner')" label="负责人" width="130"><template #default="{ row }">{{ row.owner?.display_name || '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('received')" label="接收时间" width="130"><template #default="{ row }">{{ formatDate(row.received_at) }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('due')" label="期望回复" width="130"><template #default="{ row }">{{ formatDate(row.requested_due_at) }}</template></ElTableColumn>
        <ElTableColumn label="操作" width="92" fixed="right"><template #default="{ row }"><ElButton link type="primary" @click="openRow(row)">查看</ElButton></template></ElTableColumn>
      </ElTable>

      <ElTable class="scroll-actions-table" v-else-if="props.kind === 'quotations'" :data="quotationRows" row-key="id" border empty-text="当前客户暂无报价" @selection-change="selectedRows = $event">
        <ElTableColumn type="selection" width="48" /><ElTableColumn prop="quotation_number" label="报价编号" width="150" />
        <ElTableColumn v-if="hasColumn('subject')" prop="subject" label="报价主题" min-width="250" show-overflow-tooltip />
        <ElTableColumn v-if="hasColumn('version')" label="版本" width="88"><template #default="{ row }">{{ row.current_version ? `V${row.current_version.version_number}` : '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('amount')" label="报价金额" width="160"><template #default="{ row }">{{ row.current_version ? `${row.current_version.currency_code} ${formatMoney(row.current_version.total_amount)}` : '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('status')" label="状态" width="120"><template #default="{ row }"><CustomerActivityTag :label="row.display_status_label" :tone="statusTone(row.display_status)" /></template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('owner')" label="负责人" width="130"><template #default="{ row }">{{ row.owner?.display_name || '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('updated')" label="更新时间" width="130"><template #default="{ row }">{{ formatDate(row.updated_at) }}</template></ElTableColumn>
        <ElTableColumn label="操作" width="92" fixed="right"><template #default="{ row }"><ElButton link type="primary" @click="openRow(row)">查看</ElButton></template></ElTableColumn>
      </ElTable>

      <ElTable class="scroll-actions-table" v-else-if="props.kind === 'samples'" :data="sampleRows" row-key="id" border empty-text="当前客户暂无样品申请" @selection-change="selectedRows = $event">
        <ElTableColumn type="selection" width="48" /><ElTableColumn prop="request_number" label="样品编号" width="150" />
        <ElTableColumn v-if="hasColumn('type')" prop="sample_type_display" label="样品类型" width="126" />
        <ElTableColumn v-if="hasColumn('summary')" label="样品明细" min-width="260" show-overflow-tooltip><template #default="{ row }">{{ row.item_summary?.text || '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('status')" label="状态" width="120"><template #default="{ row }"><CustomerActivityTag :label="row.status_display" :tone="statusTone(row.status)" /></template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('shipping')" label="物流状态" width="130"><template #default="{ row }">{{ row.latest_shipment?.status_display || '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('owner')" label="负责人" width="130"><template #default="{ row }">{{ row.owner?.display_name || '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('requested')" label="申请时间" width="130"><template #default="{ row }">{{ formatDate(row.requested_at) }}</template></ElTableColumn>
        <ElTableColumn label="操作" width="92" fixed="right"><template #default="{ row }"><ElButton link type="primary" @click="openRow(row)">查看</ElButton></template></ElTableColumn>
      </ElTable>

      <ElTable class="scroll-actions-table" v-else :data="orderRows" row-key="id" border empty-text="当前客户暂无销售订单" @selection-change="selectedRows = $event">
        <ElTableColumn type="selection" width="48" /><ElTableColumn prop="order_number" label="订单编号" width="160" />
        <ElTableColumn v-if="hasColumn('po')" prop="customer_po_number" label="客户 PO" min-width="190" show-overflow-tooltip />
        <ElTableColumn v-if="hasColumn('status')" label="状态" width="120"><template #default="{ row }"><CustomerActivityTag :label="row.status_display" :tone="statusTone(row.status)" /></template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('amount')" label="订单金额" width="165"><template #default="{ row }">{{ row.currency_code }} {{ formatMoney(row.total_amount) }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('owner')" label="业务员" width="130"><template #default="{ row }">{{ row.salesperson?.display_name || '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('delivery')" label="下次交付" width="130"><template #default="{ row }">{{ formatDate(row.next_delivery_date) }}</template></ElTableColumn>
        <ElTableColumn v-if="hasColumn('updated')" label="更新时间" width="130"><template #default="{ row }">{{ formatDate(row.updated_at) }}</template></ElTableColumn>
        <ElTableColumn label="操作" width="92" fixed="right"><template #default="{ row }"><ElButton link type="primary" @click="openRow(row)">查看</ElButton></template></ElTableColumn>
      </ElTable>
    </template>
  </CustomerDetailListShell>

  <AppWindowDialog v-model="saveVisible" :class="{ 'customer-detail-dialog': props.kind === 'inquiries' }" title="保存当前视图" :width="420" :height="240">
    <ElInput v-model="saveName" maxlength="100" show-word-limit placeholder="输入视图名称" @keyup.enter="saveView" />
    <template #footer><ElButton @click="saveVisible = false">取消</ElButton><ElButton type="primary" :loading="saveLoading" @click="saveView">保存</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.customer-record-filters {
  display: flex;
  align-items: center;
  gap: 10px;
}

.customer-record-filters__search { width: 330px; }
.customer-record-filters :deep(.el-select) { width: 160px; }
.customer-record-filters :deep(.el-date-editor) { width: 180px; }
.customer-record-filters :deep(.el-button) { width: 76px; height: 36px; margin: 0; border-radius: token.$crm-radius-2; }
.customer-record-columns { display: flex; flex-direction: column; gap: 8px; }
.customer-record-columns :deep(.el-checkbox) { margin-right: 0; }

@media (max-width: 1599px) {
  .customer-record-filters { min-width: 1180px; }
  .customer-record-filters__search { width: 280px; }
  :deep(.customer-detail-list-shell__filters) { overflow-x: auto; }
}
</style>
