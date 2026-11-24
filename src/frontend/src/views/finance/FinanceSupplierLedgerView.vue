<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { ArrowDown, ArrowLeft } from '@element-plus/icons-vue'
import { isAxiosError } from 'axios'
import { fetchSupplierLedger, fetchSupplierLedgerEntries, fetchSupplierLedgerOptions } from '@/api/financeSupplierLedger'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { useAuthStore } from '@/stores/auth'
import type {
  SupplierLedgerEntry, SupplierLedgerEntryPage, SupplierLedgerOption, SupplierLedgerSummaryPage,
  SupplierSettlementDraft, SupplierSettlementKind,
} from '@/types/financeSupplierLedger'
import SupplierLedgerReceiptDialog from './SupplierLedgerReceiptDialog.vue'
import SupplierSettlementForm from './SupplierSettlementForm.vue'
import SupplierSettlementDetail from './SupplierSettlementDetail.vue'
import { ledgerMoney, ledgerToday } from './supplierLedgerDisplay'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const canView = computed(() => auth.identityReady && (auth.user?.is_superuser || auth.hasPermission('finance.view_supplierledger')))
const routeName = 'finance-supplier-ledger'
const pageSizes = [20, 50, 100]

const summaryColumns = [
  ['opening_amount', '期初未付', 110], ['current_amount', '本月应付', 110], ['paid_amount', '本月实付', 110],
  ['offset_amount', '本月抵账', 110], ['closing_amount', '期末未付', 110], ['unused_prepayment', '未抵预付款', 128],
] as const
const sourceColumns = [
  ['purchase_order_number', '采购单号', 180], ['inbound_number', '入库单号', 180],
  ['production_task_number', '生产单号', 170],
] as const
type SourceField = typeof sourceColumns[number][0]

function currentMonth() {
  return ledgerToday().slice(0, 7)
}

function queryValue(name: string) {
  const value = route.query[name]
  return typeof value === 'string' ? value : undefined
}

const appliedMonth = computed(() => queryValue('month') ?? currentMonth())
const appliedSupplier = computed(() => queryValue('supplier_id'))
const detailId = computed(() => queryValue('detail'))
const draftMonth = ref(appliedMonth.value)
const draftSupplier = ref(appliedSupplier.value)
const moreOpen = ref(false)
const inboundId = ref<string | null>(null)
const settlementDraft = shallowRef<SupplierSettlementDraft>()
const settlementDocument = shallowRef<{ kind: SupplierSettlementKind; id: string }>()
const canRegister = computed(() => auth.user?.is_superuser || auth.hasPermission('finance.add_supplierpayment'))
const canOffset = computed(() => auth.user?.is_superuser || auth.hasPermission('finance.add_supplieroffset'))
const options = shallowRef<SupplierLedgerOption[]>([])
const optionsError = ref(false)
const optionsLoading = ref(false)
const summary = shallowRef<SupplierLedgerSummaryPage>()
const detail = shallowRef<SupplierLedgerEntryPage>()
const error = ref('')
const loading = ref(false)
const reload = ref(0)
const reloadOptions = ref(0)
const narrowQuery = window.matchMedia('(max-width: 1100px)')
const narrow = ref(narrowQuery.matches)
function updateWidth(event: MediaQueryListEvent) {
  narrow.value = event.matches
  moreOpen.value = false
}
narrowQuery.addEventListener('change', updateWidth)
onBeforeUnmount(() => narrowQuery.removeEventListener('change', updateWidth))

function pageNumber(key: string) {
  const value = Number(queryValue(key))
  return Number.isSafeInteger(value) && value > 0 ? value : 1
}

function pageSize(key: string) {
  const value = Number(queryValue(key))
  return pageSizes.includes(value) ? value : 50
}

function updateQuery(change: LocationQueryRaw) {
  return router.push({ name: routeName, query: { ...route.query, ...change } })
}

function changePage(value: number) {
  void updateQuery(detailId.value ? { detail_page: value } : { page: value })
}

function changePageSize(value: number) {
  void updateQuery(detailId.value ? { detail_size: value, detail_page: undefined } : { page_size: value, page: undefined })
}

function applyFilters() {
  const month = draftMonth.value || currentMonth()
  const supplier = draftSupplier.value || undefined
  moreOpen.value = false
  if (month === appliedMonth.value && supplier === appliedSupplier.value && pageNumber('page') === 1) {
    reload.value++
  } else {
    void updateQuery({ month, supplier_id: supplier, page: undefined })
  }
}

function reset() {
  draftMonth.value = currentMonth()
  draftSupplier.value = undefined
  applyFilters()
}

function openSettlement(row: SupplierLedgerEntry) {
  if (!row.document_id) return
  settlementDocument.value = { kind: row.entry_kind === 'PAYMENT' ? 'payments' : 'offsets', id: row.document_id }
}

function replaceSettlement(draft: SupplierSettlementDraft) {
  settlementDocument.value = undefined
  settlementDraft.value = draft
}

function reopenSettlement(kind: SupplierSettlementKind, id: string) {
  settlementDocument.value = { kind, id }
}

function settlementSaved() {
  settlementDraft.value = undefined
  reload.value++
  reloadOptions.value++
}

function sourceRoute(row: SupplierLedgerEntry, source: SourceField) {
  if (source === 'purchase_order_number' && row.purchase_order_id) {
    return { name: 'purchase-order-detail', params: { id: row.purchase_order_id } }
  }
  if (source === 'production_task_number' && row.production_task_id) {
    return { name: 'production-task-detail', params: { taskId: row.production_task_id } }
  }
  return null
}

watch([appliedMonth, appliedSupplier], ([month, supplier]) => {
  draftMonth.value = month
  draftSupplier.value = supplier
})

watch([canView, () => auth.identityGeneration, reloadOptions], async ([allowed], _, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  options.value = []
  optionsError.value = false
  optionsLoading.value = allowed
  if (!allowed) return
  try {
    options.value = await fetchSupplierLedgerOptions(controller.signal)
  } catch {
    if (!controller.signal.aborted) optionsError.value = true
  } finally {
    if (!controller.signal.aborted) optionsLoading.value = false
  }
}, { immediate: true })

watch([
  appliedMonth, appliedSupplier, detailId, () => route.query.page, () => route.query.page_size,
  () => route.query.detail_page, () => route.query.detail_size, canView, () => auth.identityGeneration, reload,
], async ([month, supplier, id, , , , , allowed], _, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  error.value = ''
  inboundId.value = null
  summary.value = undefined
  detail.value = undefined
  loading.value = allowed
  if (!allowed) return
  try {
    if (id) {
      detail.value = await fetchSupplierLedgerEntries({
        month, supplier_id: id, page: pageNumber('detail_page'), page_size: pageSize('detail_size'),
      }, controller.signal)
    } else {
      summary.value = await fetchSupplierLedger({
        month, supplier_id: supplier, page: pageNumber('page'), page_size: pageSize('page_size'),
      }, controller.signal)
    }
  } catch (cause) {
    if (controller.signal.aborted) return
    const status = isAxiosError(cause) ? cause.response?.status : undefined
    error.value = status === 403 ? '无权查看供应商往来明细。'
      : status === 404 ? '该供应商或页码没有可查看的记录。'
        : '供应商往来明细加载失败，请重试。'
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })
</script>

<template>
  <section class="erp-glass-list supplier-ledger" aria-label="供应商往来明细">
    <section v-glass-spotlight class="erp-list-filter ledger-top">
      <div class="erp-list-heading"><h1>供应商往来明细</h1></div>
      <div v-if="detailId" class="erp-list-filters detail-context">
        <time :datetime="appliedMonth">{{ appliedMonth.replace('-', '年') }}月</time>
        <span class="detail-supplier" :title="detail?.meta.supplier_name">{{ detail?.meta.supplier_name }}</span>
        <div class="erp-list-filter-actions">
          <ElButton :icon="ArrowLeft" class="erp-button-motion"
            @click="updateQuery({ detail: undefined, detail_page: undefined, detail_size: undefined })">返回列表</ElButton>
        </div>
      </div>
      <form v-else class="erp-list-filters" aria-label="往来明细筛选" @submit.prevent="applyFilters">
        <ElDatePicker v-model="draftMonth" class="month-filter" type="month" value-format="YYYY-MM" format="YYYY年MM月"
          :clearable="false" aria-label="月份" />
        <ElSelect v-if="!narrow" v-model="draftSupplier" class="supplier-filter" clearable filterable
          :loading="optionsLoading" placeholder="供应商：全部" aria-label="供应商">
          <ElOption v-for="item in options" :key="item.id" :value="item.id" :label="item.supplier_name" />
        </ElSelect>
        <ElPopover v-else v-model:visible="moreOpen" placement="bottom-start" :width="278" trigger="click"
          popper-class="erp-list-filter-popover">
          <template #reference>
            <ElButton class="erp-button-motion">更多筛选{{ draftSupplier ? '（1）' : '' }}<ElIcon><ArrowDown /></ElIcon></ElButton>
          </template>
          <ElSelect v-model="draftSupplier" clearable filterable :loading="optionsLoading" placeholder="供应商：全部" aria-label="供应商">
            <ElOption v-for="item in options" :key="item.id" :value="item.id" :label="item.supplier_name" />
          </ElSelect>
        </ElPopover>
        <div class="erp-list-filter-actions">
          <ElButton class="erp-button-motion" @click="reset">重置</ElButton>
          <ElButton class="erp-button-motion" type="primary" native-type="submit">应用筛选</ElButton>
        </div>
      </form>
    </section>

    <section class="erp-list-data">
      <div v-if="!detailId && canView && (canRegister || canOffset)" class="erp-list-toolbar">
        <ElButton v-if="canRegister" type="primary" class="erp-button-motion" @click="settlementDraft = { kind: 'payments' }">登记付款</ElButton>
        <ElButton v-if="canOffset" :type="canRegister ? 'default' : 'primary'" class="erp-button-motion"
          @click="settlementDraft = { kind: 'offsets' }">抵账</ElButton>
      </div>
      <ElAlert v-if="optionsError && !detailId" title="供应商选项加载失败。" type="warning" :closable="false">
        <ElButton link @click="reloadOptions++">重试</ElButton>
      </ElAlert>
      <ElAlert v-if="error || !canView" :title="error || '无权查看供应商往来明细。'" type="error" :closable="false">
        <ElButton v-if="canView" link @click="reload++">重试</ElButton>
      </ElAlert>
      <template v-else>
        <div v-loading="loading" class="erp-list-table-frame">
          <ElTable v-if="!detailId" class="supplier-ledger-table" :data="summary?.data ?? []" height="100%"
            row-key="supplier_id" scrollbar-always-on :empty-text="loading ? ' ' : '暂无往来记录'" aria-label="供应商月度汇总">
            <ElTableColumn label="供应商" min-width="252" show-overflow-tooltip>
              <template #default="{ row }">
                <RouterLink class="ledger-link" :title="row.supplier_name"
                  :to="{ name: routeName, query: { ...route.query, detail: row.supplier_id } }">{{ row.supplier_name }}</RouterLink>
              </template>
            </ElTableColumn>
            <ElTableColumn v-for="[field, label, width] in summaryColumns" :key="label" :label="label" :min-width="width"
              align="right" show-overflow-tooltip>
              <template #default="{ row }">{{ ledgerMoney(row[field]) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="pending_count" label="待核价笔数" min-width="102" align="right" />
          </ElTable>
          <ElTable v-else class="supplier-ledger-table" :data="detail?.data ?? []" height="100%" row-key="id" scrollbar-always-on
            :empty-text="loading ? ' ' : '当月暂无逐笔记录'" aria-label="当月逐笔明细">
            <ElTableColumn prop="business_date" label="业务日期" width="110" />
            <ElTableColumn prop="type_display" label="类型" width="92" />
            <ElTableColumn label="状态" width="124">
              <template #default="{ row }">
                <span class="erp-list-tag ledger-status" :class="row.status === 'ACTIVE' || row.confirmed_date ? 'erp-list-tag--success' : 'erp-list-tag--warning'">
                  {{ row.status_display }}
                </span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="业务单号" width="194" show-overflow-tooltip>
              <template #default="{ row }">
                <RouterLink v-if="row.payable_id" class="ledger-link" :title="row.number"
                  :to="{ name: 'finance-purchase-payables', query: { payable_id: row.payable_id } }">{{ row.number }}</RouterLink>
                <button v-else-if="row.document_id" type="button" class="ledger-link" :title="row.number"
                  @click="openSettlement(row)">{{ row.number }}</button>
                <span v-else>{{ row.number }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="本笔应付" width="112" align="right" show-overflow-tooltip>
              <template #default="{ row }">{{ ledgerMoney(row.amount) }}</template>
            </ElTableColumn>
            <ElTableColumn label="本笔实付" width="112" align="right" show-overflow-tooltip>
              <template #default="{ row }">{{ ledgerMoney(row.paid_amount) }}</template>
            </ElTableColumn>
            <ElTableColumn label="本笔抵账" width="112" align="right" show-overflow-tooltip>
              <template #default="{ row }">{{ ledgerMoney(row.offset_amount) }}</template>
            </ElTableColumn>
            <ElTableColumn label="入库日期" width="110"><template #default="{ row }">{{ row.inbound_date ?? '—' }}</template></ElTableColumn>
            <ElTableColumn label="财务确认日期" width="124">
              <template #default="{ row }"><span :title="row.confirmed_by">{{ row.confirmed_date || '—' }}</span></template>
            </ElTableColumn>
            <ElTableColumn v-for="[field, label, width] in sourceColumns" :key="field" :label="label" :width="width" show-overflow-tooltip>
              <template #default="{ row }">
                <RouterLink v-if="sourceRoute(row, field)" class="ledger-link" :title="row[field]"
                  :to="sourceRoute(row, field)!">{{ row[field] }}</RouterLink>
                <button v-else-if="field === 'inbound_number' && row.inbound_id" type="button" class="ledger-link"
                  :title="row[field]" @click="inboundId = row.inbound_id">{{ row[field] }}</button>
                <span v-else>{{ row[field] || '—' }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="材料名称" width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ row.material || '—' }}</template>
            </ElTableColumn>
            <ElTableColumn label="规格" width="200" show-overflow-tooltip>
              <template #default="{ row }">{{ row.specification || '—' }}</template>
            </ElTableColumn>
            <ElTableColumn label="结算数量" width="112" align="right" show-overflow-tooltip>
              <template #default="{ row }">{{ row.quantity ?? '—' }}</template>
            </ElTableColumn>
            <ElTableColumn label="计价单位" width="90" show-overflow-tooltip>
              <template #default="{ row }">{{ row.unit || '—' }}</template>
            </ElTableColumn>
            <ElTableColumn label="核定单价" width="112" align="right" show-overflow-tooltip>
              <template #default="{ row }">{{ row.unit_price ?? '—' }}</template>
            </ElTableColumn>
          </ElTable>
        </div>
        <footer v-if="detail?.meta || summary?.meta" class="erp-list-footer">
          <span>共 {{ (detail?.meta ?? summary?.meta)?.total }} 条</span>
          <ElPagination :current-page="detailId ? pageNumber('detail_page') : pageNumber('page')"
            :page-size="detailId ? pageSize('detail_size') : pageSize('page_size')"
            :total="(detail?.meta ?? summary?.meta)?.total" :page-sizes="pageSizes" :pager-count="5"
            layout="sizes, prev, pager, next"
            @update:current-page="changePage" @update:page-size="changePageSize" />
        </footer>
      </template>
    </section>
    <SupplierLedgerReceiptDialog v-if="inboundId" :inbound-id="inboundId" @close="inboundId = null" />
    <SupplierSettlementForm v-if="settlementDraft" :draft="settlementDraft" :supplier-id="appliedSupplier"
      @close="settlementDraft = undefined" @saved="settlementSaved" />
    <SupplierSettlementDetail v-if="settlementDocument" :kind="settlementDocument.kind" :document-id="settlementDocument.id"
      @close="settlementDocument = undefined" @changed="reload++" @replace="replaceSettlement"
      @reopen="reopenSettlement" />
  </section>
</template>

<style scoped lang="scss">
.supplier-ledger {
  .ledger-top { display: flex; align-items: center; gap: 20px; white-space: nowrap; }
  .ledger-top .erp-list-heading { flex: none; margin: 0; }
  .ledger-top .erp-list-filters { flex: 1; flex-wrap: nowrap; }
  .month-filter { width: 150px; }
  .supplier-filter { width: 228px; }
  .detail-context { gap: 14px; font-size: 13px; }
  .detail-supplier { overflow: hidden; text-overflow: ellipsis; }
  .ledger-status { display: inline-flex; align-items: center; height: 24px; padding: 0 8px; border-radius: 5px; }
  .el-alert + .erp-list-table-frame { margin-top: 8px; }
}
.ledger-link {
  display: inline-block; max-width: 100%; padding: 0; border: 0; background: none;
  color: var(--erp-color-brand); font: inherit; text-align: left; text-decoration: none; vertical-align: middle;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer;
  &:hover { text-decoration: underline; }
}
.supplier-ledger-table.el-table {
  :deep(.cell) { white-space: nowrap; text-overflow: ellipsis; }
  :deep(.el-table__header th.el-table__cell) { font-weight: 500; }
  :deep(td.is-right) { font-variant-numeric: tabular-nums; }
  &:not(.el-table--scrollable-x) :deep(.el-scrollbar__bar.is-horizontal),
  &:not(.el-table--scrollable-y) :deep(.el-scrollbar__bar.is-vertical) { display: none; }
}
@media (max-width: 900px) {
  .supplier-ledger .ledger-top { gap: 10px; }
  .supplier-ledger .ledger-top h1 { font-size: 22px !important; }
}
</style>
