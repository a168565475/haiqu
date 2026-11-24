<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import { isAxiosError } from 'axios'
import {
  fetchSupplierDuePayables, fetchSupplierPaymentApplications, fetchSupplierPaymentRecords, fetchSupplierPaymentSuppliers,
} from '@/api/financeSupplierPayments'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { useAuthStore } from '@/stores/auth'
import type { SupplierLedgerOption, SupplierSettlementDraft } from '@/types/financeSupplierLedger'
import type {
  SupplierDuePayableSummary, SupplierPaymentApplicationContext, SupplierPaymentApplicationRow, SupplierPaymentRecord,
} from '@/types/financeSupplierPayments'
import SupplierDuePayableDetails from './SupplierDuePayableDetails.vue'
import SupplierPaymentApplicationForm from './SupplierPaymentApplicationForm.vue'
import SupplierPaymentApplicationDetail from './SupplierPaymentApplicationDetail.vue'
import SupplierSettlementForm from './SupplierSettlementForm.vue'
import SupplierSettlementDetail from './SupplierSettlementDetail.vue'
import { ledgerMoney, ledgerRequestError, ledgerToday } from './supplierLedgerDisplay'

type Tab = 'applications' | 'payments' | 'due'
type Dialog =
  | { kind: 'new'; supplierId?: string; dueThroughMonth?: string }
  | { kind: 'application' | 'payment'; id: string }
  | { kind: 'register'; draft: SupplierSettlementDraft; application?: SupplierPaymentApplicationContext }

const tabs = [
  { id: 'applications', label: '付款申请' }, { id: 'payments', label: '付款记录' }, { id: 'due', label: '到期货款' },
] as const
const applicationColumns = [
  ['number', '申请单号', 188], ['applied_on', '申请日期', 112], ['supplier_name', '供应商', 216],
  ['payee', '收款抬头', 200], ['amount', '申请金额', 124], ['paid_amount', '已付金额', 124],
  ['remaining_amount', '申请剩余金额', 140], ['recorded_by_name', '经办人', 100], ['action', '操作', 84],
] as const
const paymentColumns = [
  ['number', '付款单号', 188], ['business_date', '付款日期', 112], ['supplier_name', '供应商', 216],
  ['payee', '收款人', 200], ['account_name', '付款账户', 210], ['amount', '实付金额', 124],
  ['recorded_by_name', '经办人', 100],
] as const
const dueColumns = [
  ['supplier_name', '供应商', 220], ['overdue_amount', '以前月份到期可申请', 176],
  ['current_due_amount', '本月到期可申请', 148], ['due_total', '到期可申请合计', 148], ['action', '操作', 172],
] as const
const moneyColumns = new Set(['amount', 'paid_amount', 'remaining_amount'])

const route = useRoute()
const router = useRouter()
const routeName = 'finance-supplier-payments'
const pageSizes = [20, 50, 100]
const auth = useAuthStore()
const allowed = (permission: string) => auth.identityReady && (auth.user?.is_superuser || auth.hasPermission(permission))
const canView = computed(() => allowed('finance.view_supplierpayment'))
const canApply = computed(() => allowed('finance.add_supplierpaymentapplication'))
const canRegister = computed(() => allowed('finance.add_supplierpayment'))
const canOpenPayable = computed(() => allowed('finance.view_purchasepayable'))
const currentMonth = () => ledgerToday().slice(0, 7)

function queryText(key: string) {
  const value = route.query[key]
  return typeof value === 'string' ? value : undefined
}
function queryPage(key: string) {
  const value = Number(queryText(key))
  return Number.isSafeInteger(value) && value > 0 ? value : 1
}
function querySize(key: string) {
  const value = Number(queryText(key))
  return pageSizes.includes(value) ? value : 50
}
const startsOnDue = queryText('tab') === 'due'
const tab = ref<Tab>(startsOnDue ? 'due' : 'applications')
const defaultFilters = () => ({ month: currentMonth(), supplierId: '' })
const initialDueFilters = startsOnDue
  ? { month: queryText('month') || currentMonth(), supplierId: queryText('supplier_id') || '' }
  : defaultFilters()
const filtersByView = reactive({
  payments: { draft: defaultFilters(), applied: defaultFilters() },
  due: { draft: { ...initialDueFilters }, applied: initialDueFilters },
})
const filters = computed(() => tab.value === 'due' ? filtersByView.due : filtersByView.payments)
const applied = computed(() => filters.value.applied)
const dateLabels: Record<Tab, string> = { applications: '申请月份', payments: '付款月份', due: '目标月份' }
const dateLabel = computed(() => dateLabels[tab.value])
const pagination = reactive({
  applications: { page: 1, size: 50 }, payments: { page: 1, size: 50 },
  due: { page: startsOnDue ? queryPage('page') : 1, size: startsOnDue ? querySize('page_size') : 50 },
})
const paging = computed(() => pagination[tab.value])
const total = ref(0)
const applications = shallowRef<SupplierPaymentApplicationRow[]>([])
const payments = shallowRef<SupplierPaymentRecord[]>([])
const duePayables = shallowRef<SupplierDuePayableSummary[]>([])
const suppliers = shallowRef<SupplierLedgerOption[]>([])
const rowsLoading = ref(false)
const supplierLoading = ref(false)
const rowsError = ref('')
const supplierError = ref('')
const dialog = shallowRef<Dialog>()
const moreOpen = ref(false)
const reloadRows = ref(0)
const reloadSuppliers = ref(0)
const dueDetailId = computed(() => route.name === routeName && tab.value === 'due' ? queryText('detail') : undefined)
const dueDetailName = computed(() => suppliers.value.find(item => item.id === dueDetailId.value)?.supplier_name
  ?? duePayables.value.find(item => item.supplier_id === dueDetailId.value)?.supplier_name)

const narrowQuery = window.matchMedia('(max-width: 1100px)')
const narrow = ref(narrowQuery.matches)
function updateNarrow(event: MediaQueryListEvent) {
  narrow.value = event.matches
  moreOpen.value = false
}
narrowQuery.addEventListener('change', updateNarrow)
onBeforeUnmount(() => narrowQuery.removeEventListener('change', updateNarrow))

watch([canView, reloadSuppliers], async ([visible], _, cleanup) => {
  if (!visible) return
  const controller = new AbortController()
  cleanup(() => controller.abort())
  supplierLoading.value = true
  supplierError.value = ''
  try {
    const options = await fetchSupplierPaymentSuppliers(controller.signal)
    if (!controller.signal.aborted) suppliers.value = options
  } catch (cause) {
    if (!controller.signal.aborted) supplierError.value = ledgerRequestError(cause, '供应商选项加载失败。')
  } finally {
    if (!controller.signal.aborted) supplierLoading.value = false
  }
}, { immediate: true })

watch([canView, tab, applied, () => paging.value.page, () => paging.value.size, reloadRows],
  async ([visible, current, filters, page, size], _, cleanup) => {
    if (!visible) return
    const controller = new AbortController()
    cleanup(() => controller.abort())
    rowsError.value = ''
    rowsLoading.value = true
    const query = { month: filters.month, supplier_id: filters.supplierId || undefined, page, page_size: size }
    try {
      if (current === 'applications') {
        const result = await fetchSupplierPaymentApplications(query, controller.signal)
        if (controller.signal.aborted) return
        applications.value = result.data
        total.value = result.meta.total
      } else if (current === 'payments') {
        const result = await fetchSupplierPaymentRecords(query, controller.signal)
        if (controller.signal.aborted) return
        payments.value = result.data
        total.value = result.meta.total
      } else {
        const result = await fetchSupplierDuePayables(query, controller.signal)
        if (controller.signal.aborted) return
        duePayables.value = result.data
        total.value = result.meta.total
      }
    } catch (cause) {
      if (controller.signal.aborted) return
      if (page > 1 && isAxiosError(cause) && cause.response?.status === 404) paging.value.page = page - 1
      else rowsError.value = ledgerRequestError(cause, '付款列表加载失败。')
    } finally {
      if (!controller.signal.aborted) rowsLoading.value = false
    }
  }, { immediate: true })

function updateDueQuery(change: LocationQueryRaw = {}) {
  if (route.name !== routeName) return
  const { month, supplierId } = filtersByView.due.applied
  void router.replace({ query: {
    ...route.query, tab: 'due', month, supplier_id: supplierId || undefined,
    page: pagination.due.page, page_size: pagination.due.size, ...change,
  } })
}

watch([tab, applied, () => pagination.due.page, () => pagination.due.size], ([current]) => {
  if (current === 'due') updateDueQuery()
})

function selectTab(next: Tab) {
  if (tab.value === 'due' && next !== 'due' && route.name === routeName) {
    void router.replace({ query: {
      ...route.query, tab: undefined, month: undefined, supplier_id: undefined, page: undefined, page_size: undefined,
      detail: undefined, detail_page: undefined, detail_size: undefined,
    } })
  }
  tab.value = next
  moreOpen.value = false
}

function applyFilters() {
  filters.value.applied = { ...filters.value.draft, month: filters.value.draft.month || currentMonth() }
  if (tab.value === 'due') pagination.due.page = 1
  else {
    pagination.applications.page = 1
    pagination.payments.page = 1
  }
  moreOpen.value = false
}
function reset() {
  filters.value.draft = defaultFilters()
  applyFilters()
}
function openDueApplication(supplierId: string) {
  dialog.value = { kind: 'new', supplierId, dueThroughMonth: applied.value.month }
}
function openApplication(id: string) { dialog.value = { kind: 'application', id } }
function openPayment(id: string) { dialog.value = { kind: 'payment', id } }
function register(application?: SupplierPaymentApplicationContext) {
  dialog.value = { kind: 'register', draft: { kind: 'payments' }, application }
}
function closeRegistration() {
  const selected = dialog.value
  if (selected?.kind === 'register' && selected.application) openApplication(selected.application.id)
  else dialog.value = undefined
}
function onApplicationSaved(id: string) {
  reloadRows.value++
  openApplication(id)
}
function onPaymentSaved() {
  reloadRows.value++
  closeRegistration()
}
</script>

<template>
  <section class="erp-glass-list supplier-payment-page" aria-label="供应商付款">
    <section v-glass-spotlight class="erp-list-filter payment-filter">
      <div class="erp-list-heading"><h1>供应商付款</h1></div>
      <form class="erp-list-filters" aria-label="供应商付款筛选" @submit.prevent="applyFilters">
        <label class="payment-month">
          <span>{{ dateLabel }}</span>
          <ElDatePicker v-model="filters.draft.month" type="month" value-format="YYYY-MM" format="YYYY年MM月"
            :clearable="false" :aria-label="dateLabel" />
        </label>
        <ElSelect v-if="!narrow" v-model="filters.draft.supplierId" class="payment-supplier" placeholder="供应商：全部"
          aria-label="筛选供应商" clearable filterable :loading="supplierLoading">
          <ElOption v-for="item in suppliers" :key="item.id" :label="item.supplier_name" :value="item.id" />
        </ElSelect>
        <ElPopover v-else v-model:visible="moreOpen" placement="bottom-start" :width="268" trigger="click"
          popper-class="erp-list-filter-popover">
          <template #reference>
            <ElButton class="erp-button-motion">更多筛选{{ filters.draft.supplierId ? '（1）' : '' }}<ElIcon><ArrowDown /></ElIcon></ElButton>
          </template>
          <ElSelect v-model="filters.draft.supplierId" aria-label="筛选供应商" placeholder="供应商：全部" clearable filterable :loading="supplierLoading">
            <ElOption v-for="item in suppliers" :key="item.id" :label="item.supplier_name" :value="item.id" />
          </ElSelect>
        </ElPopover>
        <div class="erp-list-filter-actions">
          <ElButton class="erp-button-motion" @click="reset">重置</ElButton>
          <ElButton class="erp-button-motion" type="primary" native-type="submit">应用筛选</ElButton>
        </div>
      </form>
    </section>

    <section class="erp-list-data">
      <ElAlert v-if="auth.identityReady && !canView" title="无权查看供应商付款。" type="error" :closable="false" />
      <template v-if="canView">
        <div class="erp-list-toolbar">
          <div class="erp-list-tabs" role="group" aria-label="付款页签">
            <button v-for="item in tabs" :key="item.id" type="button" :aria-pressed="tab === item.id"
              :class="{ 'is-active': tab === item.id }" @click="selectTab(item.id)">{{ item.label }}</button>
          </div>
          <ElButton v-if="tab === 'applications' && canApply" class="erp-button-motion main-action" type="primary"
            @click="dialog = { kind: 'new' }">新建申请</ElButton>
          <ElButton v-if="tab === 'payments' && canRegister" class="erp-button-motion main-action" type="primary"
            @click="register()">登记付款</ElButton>
        </div>

        <ElAlert v-if="supplierError" class="list-alert" :title="supplierError" type="error" :closable="false">
          <ElButton link @click="reloadSuppliers++">重试</ElButton>
        </ElAlert>
        <ElAlert v-if="rowsError" class="list-alert" :title="rowsError" type="error" :closable="false">
          <ElButton link @click="reloadRows++">重试</ElButton>
        </ElAlert>
        <div v-else v-loading="rowsLoading" class="erp-list-table-frame"
          :aria-label="tab === 'due' ? '到期货款清单' : tab === 'applications' ? '申请列表' : '实付列表'">
          <ElTable v-if="tab === 'applications'" class="payment-list-table" :data="applications" row-key="id" height="100%"
            scrollbar-always-on empty-text="暂无付款申请">
            <ElTableColumn v-for="[field, label, width] in applicationColumns" :key="field" :prop="field" :label="label"
              :min-width="width" :align="moneyColumns.has(field) ? 'right' : 'left'" show-overflow-tooltip>
              <template v-if="field === 'action'" #default="{ row }">
                <button class="record-link" type="button" :aria-label="'查看 ' + row.number" @click="openApplication(row.id)">查看</button>
              </template>
              <template v-else-if="moneyColumns.has(field)" #default="{ row }">{{ ledgerMoney(row[field]) }}</template>
            </ElTableColumn>
          </ElTable>
          <ElTable v-else-if="tab === 'payments'" class="payment-list-table" :data="payments" row-key="id" height="100%"
            scrollbar-always-on empty-text="暂无付款记录">
            <ElTableColumn v-for="[field, label, width] in paymentColumns" :key="field" :prop="field" :label="label"
              :min-width="width" :align="moneyColumns.has(field) ? 'right' : 'left'" show-overflow-tooltip>
              <template v-if="field === 'number'" #default="{ row }">
                <button class="record-link" type="button" :class="{ corrected: row.status === 'VOID' }"
                  :aria-label="row.status === 'VOID' ? row.number + ' 已更正' : undefined"
                  :title="row.status === 'VOID' ? '已更正' : undefined" @click="openPayment(row.id)">{{ row.number }}</button>
              </template>
              <template v-else-if="field === 'amount'" #default="{ row }">{{ ledgerMoney(row.amount) }}</template>
            </ElTableColumn>
          </ElTable>
          <ElTable v-else class="payment-list-table" :data="duePayables" row-key="supplier_id" height="100%"
            empty-text="暂无到期可申请货款">
            <ElTableColumn v-for="[field, label, width] in dueColumns" :key="field" :prop="field" :label="label"
              :min-width="width" :align="field === 'supplier_name' || field === 'action' ? 'left' : 'right'" show-overflow-tooltip>
              <template v-if="field === 'action'" #default="{ row }">
                <div class="due-actions">
                  <button type="button" class="record-link" :aria-label="'查看明细 ' + row.supplier_name"
                    @click="updateDueQuery({ detail: row.supplier_id, detail_page: undefined, detail_size: undefined })">查看明细</button>
                  <button v-if="canApply" type="button" class="record-link" :aria-label="'申请付款 ' + row.supplier_name"
                    @click="openDueApplication(row.supplier_id)">申请付款</button>
                </div>
              </template>
              <template v-else-if="field !== 'supplier_name'" #default="{ row }">{{ ledgerMoney(row[field]) }}</template>
            </ElTableColumn>
          </ElTable>
        </div>
        <footer v-if="!rowsError" class="erp-list-footer">
          <span>共 {{ total }} 条</span>
          <ElPagination v-model:current-page="paging.page" v-model:page-size="paging.size" :total="total"
            :page-sizes="pageSizes" :pager-count="5" layout="sizes, prev, pager, next" @size-change="paging.page = 1" />
        </footer>
      </template>
    </section>

    <SupplierDuePayableDetails v-if="canView && dueDetailId" :supplier-id="dueDetailId" :supplier-name="dueDetailName"
      :month="applied.month" :page="queryPage('detail_page')" :page-size="querySize('detail_size')" :can-open-payable="canOpenPayable"
      @page="page => updateDueQuery({ detail_page: page })"
      @page-size="detail_size => updateDueQuery({ detail_size, detail_page: undefined })"
      @close="updateDueQuery({ detail: undefined, detail_page: undefined, detail_size: undefined })" />
    <SupplierPaymentApplicationForm v-if="dialog?.kind === 'new'" :initial-supplier="dialog.supplierId ?? applied.supplierId"
      :due-through-month="dialog.dueThroughMonth" :suppliers="suppliers"
      :loading-suppliers="supplierLoading" @close="dialog = undefined" @saved="onApplicationSaved" />
    <SupplierPaymentApplicationDetail v-if="dialog?.kind === 'application'" :application-id="dialog.id"
      @close="dialog = undefined" @register="register" @payment="openPayment" @changed="reloadRows++" />
    <SupplierSettlementForm v-if="dialog?.kind === 'register'" :draft="dialog.draft" :application="dialog.application"
      :supplier-id="applied.supplierId" standalone @close="closeRegistration" @saved="onPaymentSaved" />
    <SupplierSettlementDetail v-if="dialog?.kind === 'payment'" kind="payments" :document-id="dialog.id" standalone
      @close="dialog = undefined" @changed="reloadRows++" @reopen="(_, id) => openPayment(id)" @application="openApplication"
      @replace="draft => dialog = { kind: 'register', draft }" />
  </section>
</template>

<style scoped lang="scss">
.supplier-payment-page {
  .payment-filter { display: flex; align-items: center; gap: 20px; white-space: nowrap; }
  .payment-filter .erp-list-heading { flex: none; margin: 0; }
  .erp-list-filters { flex: 1; flex-wrap: nowrap; }
  .payment-month :deep(.el-date-editor) { width: 140px; }
  .payment-supplier { width: 232px; }
  .erp-list-toolbar, .erp-list-tabs { flex-wrap: nowrap; white-space: nowrap; }
  .erp-list-toolbar .main-action { margin-left: auto; }
  .list-alert { margin-bottom: 8px; }
  .due-actions { display: inline-flex; gap: 12px; white-space: nowrap; }
  .due-actions .record-link { height: 32px; }
  :deep(.el-table .cell) { white-space: nowrap; text-overflow: ellipsis; }
  :deep(.el-table__header th.el-table__cell) { font-weight: 500; }
  :deep(.el-table td.is-right) { font-variant-numeric: tabular-nums; }
  :deep(.el-table:not(.el-table--scrollable-x) .el-scrollbar__bar.is-horizontal),
  :deep(.el-table:not(.el-table--scrollable-y) .el-scrollbar__bar.is-vertical) { display: none; }
}
.record-link {
  display: inline-block; max-width: 100%; padding: 0; border: 0; background: none;
  color: var(--erp-color-brand); font: inherit; text-align: left; vertical-align: middle;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer;
  &:hover { text-decoration: underline; }
  &.corrected { color: var(--erp-color-text-secondary); text-decoration: line-through; }
}
@media (max-width: 900px) {
  .supplier-payment-page .payment-filter { gap: 10px; }
  .supplier-payment-page .payment-filter h1 { font-size: 22px !important; }
}
</style>
