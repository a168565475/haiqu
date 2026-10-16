<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { advancePurchaseReturn, fetchPurchaseReturn, fetchPurchaseReturns, fetchReturnOptions } from '@/api/purchaseReturns'
import { useAuthStore } from '@/stores/auth'
import PurchaseReturnConfirmDialog from '@/components/procurement/PurchaseReturnConfirmDialog.vue'
import type { PurchaseReturn, ReturnOptions, ReturnOrderStatus, ReturnQuery } from '@/types/purchaseReturn'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const canView = computed(() => auth.user?.is_superuser === true
  || auth.hasPermission('procurement.view_purchaseorder')
  || auth.hasPermission('inventory.receive_material')
  || auth.hasPermission('inventory.quality_confirm_material'))
const canAdvance = (row: PurchaseReturn) => auth.moduleCan(row.status === 'QUALITY_GENERATED' ? 'access_control.confirm_purchasereturn' : 'access_control.complete_purchasereturn', 'procurement.submit_purchaseorder')
const purchaseOrderId = computed(() => typeof route.query.purchase_order_id === 'string' ? route.query.purchase_order_id : '')
const returnFrom = computed(() => route.query.from === 'inbound' ? 'inbound' : route.query.from === 'orders' ? 'orders' : '')
const backLabel = computed(() => returnFrom.value === 'inbound' ? '返回采购入库' : '返回采购订单')
const filters = reactive({ q: '', supplier: '', status: '' as ReturnOrderStatus | '' })
const rows = ref<PurchaseReturn[]>([])
const options = ref<ReturnOptions>({ suppliers: [] })
const total = ref(0), page = ref(1), pageSize = ref(50)
const loading = ref(false), optionsLoading = ref(false), busyId = ref('')
const rowsError = ref(''), optionsError = ref('')
const rowsReady = ref(false)
const confirmationVisible = ref(false), confirmationSubmitting = ref(false)
const confirmationRecord = ref<PurchaseReturn | null>(null)
const confirmationAction = ref<'confirm' | 'complete' | 'view'>('confirm')
let resolveConfirmation: ((confirmed: boolean) => void) | null = null
const statuses: { value: ReturnOrderStatus; label: string }[] = [
  { value: 'QUALITY_GENERATED', label: '待确认退货' },
  { value: 'PROCUREMENT_CONFIRMED', label: '待退货完成' },
  { value: 'COMPLETED', label: '退货完成' },
]
const statusText: Record<ReturnOrderStatus, string> = { QUALITY_GENERATED: '品质生成', PROCUREMENT_CONFIRMED: '已确认退货', COMPLETED: '退货完成' }
function statusLabel(row: PurchaseReturn): string { return statusText[row.status] || '未知状态' }
let requestVersion = 0, optionsVersion = 0, disposed = false
function message(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { error?: { message?: string }; detail?: string } } })?.response?.data
  return data?.error?.message || data?.detail || fallback
}
function time(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date) : '—'
}
async function loadRows() {
  if (!canView.value || disposed) return
  const version = ++requestVersion
  const query: ReturnQuery = { q: filters.q.trim() || undefined, purchase_order_id: purchaseOrderId.value || undefined, supplier_id: filters.supplier || undefined, status: filters.status || undefined, page: page.value, page_size: pageSize.value }
  loading.value = true; rowsError.value = ''
  try {
    const list = await fetchPurchaseReturns(query)
    if (disposed || version !== requestVersion) return
    rows.value = list.data; total.value = list.meta.total; rowsReady.value = true
  } catch (error) {
    if (!disposed && version === requestVersion) { rows.value = []; total.value = 0; rowsReady.value = false; rowsError.value = message(error, '退货明细加载失败，请重试。') }
  } finally { if (!disposed && version === requestVersion) loading.value = false }
}
async function loadOptions() {
  if (!canView.value) return
  const version = ++optionsVersion
  optionsLoading.value = true; optionsError.value = ''
  try { const data = await fetchReturnOptions(); if (!disposed && version === optionsVersion) options.value = data }
  catch (error) { if (!disposed && version === optionsVersion) optionsError.value = message(error, '供应商筛选选项加载失败，请刷新重试。') }
  finally { if (!disposed && version === optionsVersion) optionsLoading.value = false }
}
function search() { if (busyId.value) return; page.value = 1; void loadRows() }
function handleSearchEnter(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  search()
}
function goBack() {
  void router.push({ name: returnFrom.value === 'inbound' ? 'purchase-inbounds' : 'purchase-orders' })
}
function answerConfirmation(confirmed: boolean) {
  if (!resolveConfirmation || confirmationSubmitting.value) return
  const resolve = resolveConfirmation
  resolveConfirmation = null
  if (confirmed) confirmationSubmitting.value = true
  else confirmationVisible.value = false
  resolve(confirmed)
}
function closeDialog() {
  if (confirmationAction.value === 'view') {
    confirmationVisible.value = false
    confirmationRecord.value = null
    return
  }
  answerConfirmation(false)
}
function viewDetails(row: PurchaseReturn) {
  if (loading.value || busyId.value) return
  confirmationAction.value = 'view'
  confirmationRecord.value = row
  confirmationVisible.value = true
}
async function advance(row: PurchaseReturn) {
  if (!canAdvance(row) || loading.value || busyId.value || !['QUALITY_GENERATED', 'PROCUREMENT_CONFIRMED'].includes(row.status)) return
  busyId.value = row.id
  const action = row.status === 'QUALITY_GENERATED' ? 'confirm' : 'complete'
  const label = action === 'confirm' ? '确认退货' : '完成退货'
  try {
    // 先读取并冻结版本；确认后使用同一版本提交，避免覆盖其他人的操作。
    const snapshot = await fetchPurchaseReturn(row.id)
    if (disposed) return
    if (snapshot.data.status !== row.status) { ElMessage.info('退货状态已更新，请查看最新记录。'); await loadRows(); return }
    if (!snapshot.etag) { ElMessage.error('未取得退货单版本，请刷新后重试。'); return }
    confirmationAction.value = action
    confirmationRecord.value = snapshot.data
    confirmationVisible.value = true
    const confirmed = await new Promise<boolean>(resolve => { resolveConfirmation = resolve })
    if (!confirmed) return
    if (disposed) return
    await advancePurchaseReturn(snapshot.data.id, action, snapshot.etag)
    if (disposed) return
    ElMessage.success(action === 'confirm' ? '已确认退货，待退货完成。' : '退货已完成。')
    page.value = 1
    await loadRows()
  } catch (error) {
    if (disposed || error === 'cancel' || error === 'close') return
    ElMessage.error(message(error, `${label}失败，请刷新后重试。`))
    await loadRows()
  } finally {
    resolveConfirmation = null
    if (!disposed) { busyId.value = ''; confirmationVisible.value = false; confirmationSubmitting.value = false }
  }
}
onMounted(() => { void loadRows(); void loadOptions() })
onBeforeUnmount(() => { disposed = true; requestVersion++; optionsVersion++; resolveConfirmation?.(false); resolveConfirmation = null })
</script>

<template>
  <section class="return-page" data-testid="purchase-returns-page">
    <PurchaseReturnConfirmDialog :visible="confirmationVisible" :record="confirmationRecord" :submitting="confirmationSubmitting" :action="confirmationAction" @cancel="closeDialog" @confirm="answerConfirmation(true)" />
    <div v-if="!canView" class="empty-state"><h1>无权查看退货明细</h1><p>请联系管理员开通采购、仓库入库或品质确认权限。</p></div>
    <template v-else>
      <header class="page-head"><h1>{{ purchaseOrderId ? '品质与退货明细' : '退货明细' }}</h1><span>共 {{ rowsReady ? total : '—' }} 条</span><p>{{ purchaseOrderId && rows[0] ? rows[0].order_number : '品质确认退货数量后生成退货单' }}</p></header>
      <form class="filters-row" aria-label="退货查询" @submit.prevent="search">
        <ElInput v-model="filters.q" class="return-search" aria-label="搜索退货记录" title="支持退货单号、采购单号、供应商名称" clearable maxlength="200" :disabled="!!busyId" placeholder="搜索退货单号、采购单号、供应商" @keydown.enter="handleSearchEnter" @clear="search">
          <template #suffix><button type="button" class="return-search-button" aria-label="搜索退货列表" :disabled="!!busyId" @click="search"><ElIcon><Search /></ElIcon></button></template>
        </ElInput>
        <ElSelect v-model="filters.supplier" aria-label="供应商" clearable filterable :disabled="!!busyId" :loading="optionsLoading" placeholder="供应商：全部" @change="search"><ElOption v-for="supplier in options.suppliers" :key="supplier.id" :value="supplier.id" :label="supplier.supplier_name" /></ElSelect>
        <ElSelect v-model="filters.status" aria-label="退货状态" clearable :disabled="!!busyId" placeholder="退货状态：全部" @change="search"><ElOption v-for="status in statuses" :key="status.value" :value="status.value" :label="status.label" /></ElSelect>
        <div v-if="returnFrom" class="return-actions"><ElButton @click="goBack">{{ backLabel }}</ElButton></div>
      </form>
      <div v-if="rowsError" class="load-error" role="alert">{{ rowsError }} <ElButton link :disabled="!!busyId" @click="loadRows">重试列表</ElButton></div>
      <div v-if="optionsError" class="load-error" role="alert">{{ optionsError }} <ElButton link :disabled="!!busyId" @click="loadOptions">重试供应商</ElButton></div>
      <div class="table-card">
        <ElTable v-loading="loading" :data="rows" row-key="id" row-class-name="return-row" class="return-table" height="100%" aria-label="退货明细表格">
          <ElTableColumn label="退货单号" width="180" show-overflow-tooltip><template #default="{ row }"><strong class="return-number">{{ row.return_number }}</strong></template></ElTableColumn>
          <ElTableColumn label="采购单号" width="160" prop="order_number" show-overflow-tooltip><template #default="{ row }">{{ row.order_number || '—' }}</template></ElTableColumn>
          <ElTableColumn label="入库单号" width="160" prop="inbound_number" show-overflow-tooltip><template #default="{ row }">{{ row.inbound_number || '—' }}</template></ElTableColumn>
          <ElTableColumn label="生产任务单号" width="160" prop="production_task_number" show-overflow-tooltip><template #default="{ row }">{{ row.production_task_number || '—' }}</template></ElTableColumn>
          <ElTableColumn label="供应商" min-width="210" prop="supplier_name" show-overflow-tooltip><template #default="{ row }">{{ row.supplier_name || '—' }}</template></ElTableColumn>
          <ElTableColumn label="明细项数" width="90" align="center"><template #default="{ row }"><span class="secondary">{{ row.lines.length }} 项</span></template></ElTableColumn>
          <ElTableColumn label="退货状态" width="128"><template #default="{ row }"><div class="status-cell"><span class="status-badge" :class="row.status">{{ statusLabel(row) }}</span></div></template></ElTableColumn>
          <ElTableColumn label="采购确认时间" width="145" show-overflow-tooltip><template #default="{ row }"><span class="secondary">{{ time(row.confirmed_at) }}</span></template></ElTableColumn>
          <ElTableColumn label="完成时间" width="145" show-overflow-tooltip><template #default="{ row }"><span class="secondary">{{ time(row.completed_at) }}</span></template></ElTableColumn>
          <ElTableColumn label="生成信息" width="140"><template #default="{ row }"><div class="stack secondary"><span>{{ row.generated_by_name || '—' }}</span><small>{{ time(row.created_at) }}</small></div></template></ElTableColumn>
          <ElTableColumn label="操作" width="72" fixed="right" align="center" class-name="operation-column" label-class-name="operation-column">
            <template #default="{ row }"><ElButton v-if="row.status === 'COMPLETED'" @click="viewDetails(row)">查看</ElButton><ElButton v-else :disabled="!canAdvance(row) || !!busyId || loading || !['QUALITY_GENERATED', 'PROCUREMENT_CONFIRMED'].includes(row.status)" :loading="busyId === row.id" :title="canAdvance(row) ? '' : '没有此退货操作权限'" @click="advance(row)">{{ row.status === 'QUALITY_GENERATED' ? '确认' : '完成' }}</ElButton></template>
          </ElTableColumn>
          <template #empty><div class="table-empty">{{ rowsError ? '记录加载失败，请刷新重试' : loading ? '正在加载退货记录…' : '暂无符合条件的退货记录' }}</div></template>
        </ElTable>
        <footer class="table-footer"><span>共 {{ rowsReady ? total : '—' }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20,50,100]" :pager-count="5" :total="total" :disabled="loading || !!busyId" layout="sizes, prev, pager, next" @current-change="loadRows" @size-change="search" /></footer>
      </div>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.return-page {
  box-sizing: border-box; height: calc(100dvh - 92px); min-height: 0; overflow: hidden; padding: 32px 28px 18px; display: flex; flex-direction: column;
  background: token.$crm-color-page; color: token.$crm-text-primary; font: 16px/24px token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-border-color: #{token.$crm-border-default}; --el-text-color-primary: #{token.$crm-text-primary}; --el-text-color-regular: #{token.$crm-text-secondary}; --el-text-color-placeholder: #{token.$crm-text-muted}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-fill-color-light: #{token.$crm-color-subtle}; --el-border-radius-base: 5px;
}
h1,h2,p { margin: 0; } button { font: inherit; cursor: pointer; } button:disabled { cursor: not-allowed; }
.page-head { min-height: 44px; flex-shrink: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 8px 28px; margin-bottom: 14px; }
h1 { font: 700 34px/44px token.$crm-font-display; } .page-head span,.page-head p { color: token.$crm-text-secondary; }
.filters-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; flex-shrink: 0; margin-bottom: 14px; }
.filters-row .return-search { width: 250px; min-width: 250px; flex: none; }
.filters-row > .el-select { width: 180px; flex: none; }
.return-actions { display: flex; justify-content: flex-end; margin-left: auto; }
.return-actions .el-button { margin: 0; height: 32px; }
.return-search-button { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 24px; padding: 0; border: 0; background: transparent; color: token.$crm-text-secondary; }
.return-search-button:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
.return-page :deep(.el-button) { font: 16px token.$crm-font-body; border-radius: 5px; }
.filters-row :deep(.el-input__wrapper), .filters-row :deep(.el-select__wrapper) { min-height: 32px; box-sizing: border-box; border-radius: 5px; font-size: 14px; }
.filters-row :deep(.el-input__inner) { font-family: inherit; height: 30px; }
.table-card { box-sizing: border-box; flex: 1; min-height: 0; background: token.$crm-color-surface; border: 1px solid token.$crm-border-default; border-radius: 5px; overflow: hidden; display: flex; flex-direction: column; }
.return-table { min-height: 0; flex: 1; --el-table-border-color: #{token.$crm-border-subtle}; --el-table-row-hover-bg-color: #{token.$crm-color-row-hover}; --el-table-header-bg-color: #{token.$crm-color-subtle}; --el-table-tr-bg-color: #{token.$crm-color-surface}; --el-table-bg-color: #{token.$crm-color-surface}; }
.return-page .return-table :deep(.el-table__header th.el-table__cell) { height: 44px; padding: 0; color: token.$crm-text-secondary; background: token.$crm-color-subtle; border-right: 1px solid token.$crm-border-subtle; font-size: 11px; font-weight: 500; }
.return-page .return-table :deep(.el-table__body td.el-table__cell) { height: 40px; padding: 0; border-right: 1px solid token.$crm-border-subtle; color: token.$crm-text-primary; font-size: 12px; }
.return-page .return-table :deep(.cell) { padding: 0 16px; overflow: hidden; font-size: 12px; line-height: 18px; text-overflow: ellipsis; }
.return-page .return-table :deep(th .cell) { font-size: 12px; }
.return-page .return-table :deep(.el-table__inner-wrapper::before) { display: none; }
.return-number { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
.secondary,small { color: token.$crm-text-secondary; } small { font-size: 12px; line-height: 18px; }
.stack { display: flex; flex-direction: column; } .status-cell { display: flex; align-items: center; }
.status-badge { display: inline-flex; align-items: center; justify-content: center; border-radius: 999px; min-width: 88px; height: 24px; padding: 0 12px; box-sizing: border-box; color: token.$crm-text-inverse; font-size: 12px; background: token.$crm-neutral; }
.status-badge.QUALITY_GENERATED { background: token.$crm-info; } .status-badge.PROCUREMENT_CONFIRMED { background: token.$crm-primary; min-width: 110px; } .status-badge.COMPLETED { background: token.$crm-success; }
.return-page .return-table :deep(.operation-column) { border-right: 0 !important; }
.return-page .return-table :deep(.operation-column .cell) { padding-right: 4px !important; padding-left: 4px !important; overflow: visible; text-overflow: clip; }
.return-page .return-table :deep(.return-row .el-button) { width: 64px; height: 32px; padding: 0 12px; }
.return-page .return-table :deep(.return-row:has(.QUALITY_GENERATED) .el-button:not(:disabled)), .return-page .return-table :deep(.return-row:has(.PROCUREMENT_CONFIRMED) .el-button:not(:disabled)) { color: token.$crm-primary; border-color: token.$crm-primary; }
.return-page .table-footer { height: auto !important; min-height: 48px; flex-shrink: 0; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 18px !important; box-sizing: border-box; border-top: 1px solid token.$crm-border-default; color: token.$crm-text-secondary; }
.table-footer :deep(.el-pagination) { min-width: 0; max-width: 100%; flex-wrap: wrap; justify-content: flex-end; margin-left: auto; --el-pagination-button-bg-color: #{token.$crm-color-surface}; --el-pagination-button-disabled-bg-color: #{token.$crm-color-surface}; --el-pagination-button-height: 32px; --el-pagination-button-width: 38px; font-weight: 400; }
.table-footer :deep(.el-pager li),.table-footer :deep(.btn-prev),.table-footer :deep(.btn-next) { border: 1px solid token.$crm-border-default; border-radius: 5px; margin-left: 10px; }
.table-footer :deep(.el-pager li.is-active) { background: token.$crm-color-surface; color: token.$crm-primary; border-color: token.$crm-primary; }
.table-footer :deep(.el-select__wrapper) { min-height: 32px; }
.load-error { flex-shrink: 0; color: token.$crm-danger; padding: 8px 0; }
.table-empty { padding: 88px 0; text-align: center; color: token.$crm-text-muted; }
.empty-state { padding: 100px 0; text-align: center; } .empty-state p { margin-top: 20px; }
</style>

<style lang="scss">
@use '@/styles/crm/tokens' as token;
.purchase-return-confirm { background: token.$crm-color-surface; font-family: token.$crm-font-body; --el-color-primary: #{token.$crm-primary}; --el-border-color: #{token.$crm-border-default}; }
</style>
