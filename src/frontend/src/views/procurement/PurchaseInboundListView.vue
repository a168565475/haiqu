<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { MoreFilled, Refresh, Search } from '@element-plus/icons-vue'

import { fetchProcurementInboundOrders } from '@/api/inventory'
import { router } from '@/router'
import { useAuthStore } from '@/stores/auth'
import type { ProcurementInboundOrder } from '@/types/inventory'

const auth = useAuthStore()
const canReceive = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.receive_material'))
const canQuality = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.quality_confirm_material'))
const canView = computed(() => canReceive.value || canQuality.value)
const rows = ref<ProcurementInboundOrder[]>([])
const loading = ref(false)
const listReady = ref(false)
const loadError = ref('')
let requestId = 0
const keyword = ref('')
const appliedKeyword = ref('')
const workflowStatus = ref('')

const filteredRows = computed(() => workflowStatus.value
  ? rows.value.filter(row => row.workflow_status === workflowStatus.value)
  : rows.value)
const summary = computed(() => ({
  orders: rows.value.length,
  pendingReceipt: rows.value.filter(canOpenReceiving).length,
  pendingQuality: rows.value.reduce((total, row) => total + row.pending_quality_count, 0),
  pendingProcurement: rows.value.filter(row => row.workflow_status === 'PENDING_PROCUREMENT_CONFIRMATION').length,
}))

function apiMessage(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { error?: { message?: string }; detail?: string } } })?.response?.data
  return data?.error?.message || data?.detail || fallback
}
function formatQuantity(value: string): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) : '—'
}
function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
    : '—'
}
async function loadRows() {
  if (!canView.value) return
  const currentRequestId = ++requestId
  loading.value = true
  loadError.value = ''
  const nextKeyword = keyword.value.trim()
  try {
    const result = await fetchProcurementInboundOrders({ q: nextKeyword || undefined })
    if (currentRequestId !== requestId) return
    rows.value = result
    appliedKeyword.value = nextKeyword
    listReady.value = true
  } catch (error) {
    if (currentRequestId !== requestId) return
    rows.value = []
    listReady.value = false
    loadError.value = apiMessage(error, '采购入库列表加载失败，请重试。')
  } finally {
    if (currentRequestId === requestId) loading.value = false
  }
}
function reset() { keyword.value = ''; workflowStatus.value = ''; void loadRows() }
function hasOpenReturn(row: ProcurementInboundOrder): boolean {
  return row.return_status === 'QUALITY_GENERATED' || row.return_status === 'PROCUREMENT_CONFIRMED'
}
function canOpenReceiving(row: ProcurementInboundOrder): boolean {
  return canReceive.value && row.workflow_status !== 'COMPLETED' && row.remaining_line_count > 0 && !hasOpenReturn(row)
}
function canOpenQuality(row: ProcurementInboundOrder): boolean {
  return row.workflow_status !== 'COMPLETED' && canQuality.value && row.pending_quality_count > 0
}
function canOpenReturns(row: ProcurementInboundOrder): boolean {
  return row.workflow_status !== 'COMPLETED' && Boolean(returnActionLabel(row))
}
function hasRowActions(row: ProcurementInboundOrder): boolean {
  return row.workflow_status !== 'COMPLETED' && canView.value
}
function openDetails(row: ProcurementInboundOrder) {
  void router.push({ name: 'purchase-inbound-detail', params: { id: row.id } })
}
function receivingActionLabel(row: ProcurementInboundOrder): string {
  return Number(row.received_quantity) > 0 ? '再次入库' : '办理入库'
}
function displayOrderNumber(row: ProcurementInboundOrder): string {
  return (row.source_type === 'SAMPLE' ? row.source_number : row.sales_order_number) || '—'
}
function returnActionLabel(row: ProcurementInboundOrder): string {
  if (row.return_status === 'QUALITY_GENERATED') return '查看品质情况'
  if (row.return_status === 'PROCUREMENT_CONFIRMED' || row.return_status === 'COMPLETED') return '查看退货明细'
  return ''
}
function openReturns(row: ProcurementInboundOrder) {
  if (!returnActionLabel(row)) return
  void router.push({ name: 'purchase-returns', query: { purchase_order_id: row.id, from: 'inbound' } })
}
function openReceiving(row: ProcurementInboundOrder) {
  if (!canOpenReceiving(row)) return
  void router.push({ name: 'material-purchase-inbound', params: { purchaseOrderId: row.id } })
}
function rowClicked(row: ProcurementInboundOrder) {
  if (row.workflow_status === 'COMPLETED') openDetails(row)
  else openReceiving(row)
}

onMounted(() => { if (canView.value) void loadRows() })
</script>

<template>
  <section class="inbound-list-page" data-testid="purchase-inbound-list-page">
    <div v-if="!canView" class="empty-state"><h1>无权查看采购入库</h1><p>请联系管理员开通仓库入库或品质确认权限。</p></div>
    <template v-else>
      <header class="page-head">
        <div><h1>采购入库</h1><p>采购订单 · 仓库入库与品质进度</p></div>
      </header>

      <section class="summary-strip" aria-label="采购入库统计">
        <div><span>采购订单</span><strong>{{ listReady ? summary.orders : '—' }}</strong></div>
        <div><span>可办理入库</span><strong>{{ listReady ? summary.pendingReceipt : '—' }}</strong></div>
        <div><span>待品质确认</span><strong>{{ listReady ? summary.pendingQuality : '—' }}</strong></div>
        <div><span>等待确认退货</span><strong>{{ listReady ? summary.pendingProcurement : '—' }}</strong></div>
      </section>

      <form class="filters" @submit.prevent="loadRows">
        <ElInput v-model="keyword" :prefix-icon="Search" clearable maxlength="200" placeholder="搜索采购单、生产单、订单或供应商" />
        <ElSelect v-model="workflowStatus" clearable placeholder="入库状态：全部">
          <ElOption label="等待入库" value="PENDING_RECEIPT" />
          <ElOption label="部分入库" value="PARTIAL_RECEIVED" />
          <ElOption label="待品质确认" value="PENDING_QUALITY" />
          <ElOption label="等待确认退货" value="PENDING_PROCUREMENT_CONFIRMATION" />
          <ElOption label="等待退货完成" value="PENDING_RETURN" />
          <ElOption label="已完成" value="COMPLETED" />
        </ElSelect>
        <ElButton type="primary" native-type="submit">查询</ElButton>
        <ElButton @click="reset">重置</ElButton>
      </form>

      <ElAlert v-if="loadError" type="error" :title="loadError" :closable="false" show-icon>
        <ElButton link @click="loadRows">重新加载</ElButton>
      </ElAlert>
      <header class="list-toolbar">
        <div class="list-toolbar__title"><h2>采购入库列表</h2><span>按当前状态办理入库、品质或退货确认</span></div>
        <div class="list-toolbar__actions"><span>共 {{ listReady ? filteredRows.length : '—' }} 条</span><ElButton :icon="Refresh" :loading="loading" @click="loadRows">刷新</ElButton></div>
      </header>
      <section class="list-card" aria-label="采购入库列表">
        <ElTable v-loading="loading" :data="filteredRows" height="100%" class="purchase-table" row-key="id" :empty-text="loadError ? '采购入库列表加载失败' : loading ? '正在加载采购入库…' : '暂无采购入库订单'" @row-click="rowClicked">
          <ElTableColumn label="采购单" min-width="174"><template #default="{ row }"><div class="stack"><strong>{{ row.order_number }}</strong><small>{{ row.source_number || '—' }}</small></div></template></ElTableColumn>
          <ElTableColumn label="订单编号" min-width="150"><template #default="{ row }">{{ displayOrderNumber(row) }}</template></ElTableColumn>
          <ElTableColumn label="供应商" min-width="210"><template #default="{ row }">{{ row.supplier_names.join('、') || '—' }}</template></ElTableColumn>
          <ElTableColumn label="采购明细" width="100" align="center"><template #default="{ row }">{{ row.line_count }} 项</template></ElTableColumn>
          <ElTableColumn label="待入库" width="92" align="center"><template #default="{ row }">{{ row.remaining_line_count }} 项</template></ElTableColumn>
          <ElTableColumn label="累计到货" width="116" align="right"><template #default="{ row }">{{ formatQuantity(row.received_quantity) }}</template></ElTableColumn>
          <ElTableColumn label="当前状态" width="124" align="center"><template #default="{ row }"><span class="status-badge" :class="`status-${row.workflow_status}`">{{ row.workflow_status_display }}</span></template></ElTableColumn>
          <ElTableColumn label="更新时间" width="150"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></ElTableColumn>
          <ElTableColumn label="操作" width="72" fixed="right" align="center"><template #default="{ row }">
            <span v-if="hasRowActions(row)" class="more-action" @click.stop>
              <ElDropdown trigger="click" placement="bottom-end">
                <ElButton link class="row-more-button" :icon="MoreFilled" :aria-label="`${row.order_number}的更多操作`" />
                <template #dropdown><ElDropdownMenu>
                  <ElDropdownItem @click="openDetails(row)">查看明细</ElDropdownItem>
                  <ElDropdownItem v-if="canOpenReceiving(row)" @click="openReceiving(row)">{{ receivingActionLabel(row) }}</ElDropdownItem>
                  <ElDropdownItem v-if="canOpenQuality(row)" @click="router.push({ name: 'material-quality-confirmation' })">品质确认</ElDropdownItem>
                  <ElDropdownItem v-if="canOpenReturns(row)" @click="openReturns(row)">{{ returnActionLabel(row) }}</ElDropdownItem>
                </ElDropdownMenu></template>
              </ElDropdown>
            </span>
            <span v-else class="muted">—</span>
          </template></ElTableColumn>
        </ElTable>
        <footer class="list-card__footer"><span>共 {{ listReady ? filteredRows.length : '—' }} 条</span></footer>
      </section>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.inbound-list-page { box-sizing: border-box; width: 100%; height: calc(100dvh - 92px); min-width: 0; min-height: 0; overflow: hidden; padding: 28px 28px 18px; display: flex; flex-direction: column; background: token.$crm-color-page; color: token.$crm-text-primary; font: 13px/20px token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-border-color: #{token.$crm-border-default}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-fill-color-light: #{token.$crm-color-subtle}; --el-text-color-primary: #{token.$crm-text-primary}; --el-text-color-regular: #{token.$crm-text-secondary}; --el-border-radius-base: 5px; }
h1, h2, p { margin: 0; }
.page-head, .summary-strip, .summary-strip > div, .filters, .list-toolbar, .list-toolbar__title, .list-toolbar__actions { display: flex; align-items: center; }
.page-head { height: 56px; justify-content: space-between; margin-bottom: 16px; }
.page-head h1 { font-size: 28px; line-height: 34px; } .page-head p { color: token.$crm-text-secondary; font-size: 12px; }
.summary-strip { height: 46px; gap: 64px; padding: 0 26px; margin-bottom: 16px; border: 1px solid token.$crm-border-subtle; border-radius: token.$crm-radius-2; background: token.$crm-color-subtle; }
.summary-strip > div { gap: 8px; color: token.$crm-text-secondary; } .summary-strip strong { color: token.$crm-text-primary; font-size: 13px; }
.filters { height: 32px; gap: 12px; margin-bottom: 0; } .filters > .el-input { width: min(430px, 40vw); } .filters > .el-select { width: 190px; } .filters > .el-button { height: 32px; margin: 0; }
.list-toolbar { box-sizing: border-box; height: 38px; flex: 0 0 38px; justify-content: space-between; margin-top: 10px; }
.list-toolbar__title { gap: 22px; min-width: 0; } .list-toolbar h2 { margin: 0; color: token.$crm-text-secondary; font-size: 14px; font-weight: 400; } .list-toolbar span { color: token.$crm-text-secondary; font-size: 12px; }
.list-toolbar__actions { gap: 14px; } .list-toolbar__actions .el-button { width: 96px; height: 32px; margin: 0; }
.list-card { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; margin-top: 14px; outline: 1px solid token.$crm-border-default; outline-offset: -1px; border-radius: 5px; background: token.$crm-color-surface; }
.purchase-table { min-height: 0; flex: 1; --el-table-border-color: #{token.$crm-border-subtle}; --el-table-row-hover-bg-color: #{token.$crm-color-row-hover}; --el-table-header-bg-color: #{token.$crm-color-subtle}; --el-table-tr-bg-color: #{token.$crm-color-surface}; --el-table-bg-color: #{token.$crm-color-surface}; }
.stack { min-width: 0; display: flex; flex-direction: column; gap: 0; line-height: 18px; } .stack strong { overflow: hidden; font-size: 12px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; } .stack small, .muted { overflow: hidden; color: token.$crm-text-secondary; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.more-action { display: inline-flex; align-items: center; justify-content: center; }
.row-more-button { width: 36px; height: 32px; margin: 0; color: token.$crm-text-secondary; }
.inbound-list-page .purchase-table :deep(.el-table__header th.el-table__cell) { height: 44px; padding: 0; color: token.$crm-text-secondary; background: token.$crm-color-subtle; border-right: 1px solid token.$crm-border-subtle; font-size: 11px; font-weight: 500; }
.inbound-list-page .purchase-table :deep(.el-table__body td.el-table__cell) { height: 40px; padding: 0; border-right: 1px solid token.$crm-border-subtle; color: token.$crm-text-primary; font-size: 12px; cursor: pointer; }
.inbound-list-page .purchase-table :deep(.cell) { padding: 0 16px; overflow: hidden; font-size: 12px; line-height: 18px; text-overflow: ellipsis; }
.inbound-list-page .purchase-table :deep(.el-table__inner-wrapper::before) { display: none; }
.status-badge { box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; min-width: 88px; height: 24px; padding: 0 8px; border-radius: 999px; color: token.$crm-text-inverse; background: token.$crm-neutral; font: 500 12px/18px token.$crm-font-body; white-space: nowrap; }
.status-PARTIAL_RECEIVED { background: token.$crm-primary; } .status-PENDING_QUALITY { background: token.$crm-warning; } .status-PENDING_PROCUREMENT_CONFIRMATION { background: token.$crm-danger; } .status-PENDING_RETURN { background: token.$crm-info; } .status-COMPLETED { background: token.$crm-success; }
.inbound-list-page :deep(.el-input__wrapper), .inbound-list-page :deep(.el-select__wrapper) { min-height: 32px; border-radius: 5px; }
.list-card__footer { box-sizing: border-box; height: 70px; flex: 0 0 70px; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; border-top: 1px solid token.$crm-border-subtle; color: token.$crm-text-secondary; font-size: 12px; }
.empty-state { padding: 80px; text-align: center; color: token.$crm-text-secondary; }
</style>
