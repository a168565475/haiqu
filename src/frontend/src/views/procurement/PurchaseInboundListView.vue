<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, ref } from 'vue'
import { MoreFilled, Search } from '@element-plus/icons-vue'

import { fetchProcurementInboundOrders } from '@/api/inventory'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import SupplierAmountPopover from '@/components/procurement/SupplierAmountPopover.vue'
import type { ProcurementInboundOrder, ProcurementInboundProductSummary } from '@/types/inventory'
import { formatInboundProductField } from './purchaseOrderDetailDisplay'

const auth = useAuthStore()
const router = useRouter()
const canReceive = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.receive_material'))
const canQuality = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.quality_confirm_material'))
const canView = computed(() => canReceive.value || canQuality.value)
const rows = ref<ProcurementInboundOrder[]>([])
const loading = ref(false)
const listReady = ref(false)
const loadError = ref('')
let requestId = 0
const keyword = ref('')
const workflowStatus = ref('')
const receivingStates = {
  PENDING_RECEIPT: { label: '待收货', color: 'neutral' },
  PARTIAL_RECEIVED: { label: '部分到货', color: 'brand' },
  RECEIPT_COMPLETE: { label: '已到齐', color: 'info' },
  COMPLETED: { label: '已完成', color: 'success' },
} satisfies Record<ProcurementInboundOrder['receiving_status'], { label: string; color: string }>

const filteredRows = computed(() => {
  switch (workflowStatus.value) {
    case '': return rows.value
    case 'PENDING_QUALITY': return rows.value.filter(row => row.pending_quality_count > 0)
    case 'PENDING_PROCUREMENT_CONFIRMATION': return rows.value.filter(row => row.return_status === 'QUALITY_GENERATED')
    case 'PENDING_RETURN': return rows.value.filter(row => row.return_status === 'PROCUREMENT_CONFIRMED')
    default: return rows.value.filter(row => row.receiving_status === workflowStatus.value)
  }
})

function receivingState(row: ProcurementInboundOrder) {
  return receivingStates[row.receiving_status]
}

function apiMessage(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { error?: { message?: string }; detail?: string } } })?.response?.data
  return data?.error?.message || data?.detail || fallback
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
function handleSearchEnter(event: KeyboardEvent) {
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  void loadRows()
}
function hasOpenReturn(row: ProcurementInboundOrder): boolean {
  return row.return_status === 'QUALITY_GENERATED' || row.return_status === 'PROCUREMENT_CONFIRMED'
}
function canOpenReceiving(row: ProcurementInboundOrder): boolean {
  return canReceive.value && row.workflow_status !== 'COMPLETED' && row.remaining_line_count > 0 && !hasOpenReturn(row)
}
function canOpenReturns(row: ProcurementInboundOrder): boolean {
  return row.workflow_status !== 'COMPLETED' && Boolean(returnActionLabel(row))
}
function openDetails(row: ProcurementInboundOrder) {
  void router.push({ name: 'purchase-inbound-detail', params: { id: row.id } })
}
function receivingActionLabel(row: ProcurementInboundOrder): string {
  return row.pending_quality_count || row.confirmed_batch_count || Number(row.received_quantity) > 0 ? '再次入库' : '办理入库'
}
function receiptProgress(row: ProcurementInboundOrder): number | null {
  const value = row.receipt_progress_percent
  if (value == null || value.trim() === '') return null
  const percent = Number(value)
  return Number.isFinite(percent) && percent >= 0 && percent <= 100 ? percent : null
}
function displayProductField(row: ProcurementInboundOrder, field: keyof Omit<ProcurementInboundProductSummary, 'product_line_id'>): string {
  return formatInboundProductField(row.product_summary ?? [], field)
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
function openReceiving(row: ProcurementInboundOrder, section?: string) {
  if (!canOpenReceiving(row)) return
  void router.push({ name: 'material-purchase-inbound', params: { purchaseOrderId: row.id },
    ...(section ? { query: { material_section: section } } : {}) })
}
function rowClicked(row: ProcurementInboundOrder) {
  if (row.source_type !== 'SAMPLE' || row.workflow_status === 'COMPLETED') openDetails(row)
  else openReceiving(row)
}

onMounted(() => { if (canView.value) void loadRows() })
</script>

<template>
  <section class="inbound-list-page erp-glass-list" data-testid="purchase-inbound-list-page">
    <div v-if="!canView" class="empty-state"><h1>无权查看采购入库</h1><p>请联系管理员开通仓库入库或品质确认权限。</p></div>
    <template v-else>
      <section v-glass-spotlight class="erp-list-filter">
      <header class="page-head erp-list-heading">
        <div><h1>采购入库</h1><p>采购订单 · 仓库入库与品质进度</p></div>
      </header>

      <form class="filters erp-list-filters" @submit.prevent="loadRows">
        <ElInput v-model="keyword" class="inbound-search" aria-label="搜索采购入库" clearable maxlength="200" placeholder="生产任务单号 / 采购单号" title="支持生产任务单号、采购单号、销售单、打样单或供应商名称" @keydown.enter="handleSearchEnter" @clear="loadRows">
          <template #suffix><button type="button" class="erp-list-search-button" aria-label="搜索采购入库列表" @click="loadRows"><ElIcon><Search /></ElIcon></button></template>
        </ElInput>
        <ElSelect v-model="workflowStatus" clearable aria-label="采购入库状态" placeholder="入库状态：全部">
          <ElOption v-for="(state, value) in receivingStates" :key="value" :label="state.label" :value="value" />
          <ElOption label="有待质检批次" value="PENDING_QUALITY" />
          <ElOption label="等待确认退货" value="PENDING_PROCUREMENT_CONFIRMATION" />
          <ElOption label="等待退货完成" value="PENDING_RETURN" />
        </ElSelect>
        <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="reset">重置</ElButton><ElButton class="erp-button-motion" type="primary" native-type="submit">应用筛选</ElButton></div>
      </form>
      </section>

      <ElAlert v-if="loadError" type="error" :title="loadError" :closable="false" show-icon>
        <ElButton link @click="loadRows">重新加载</ElButton>
      </ElAlert>
      <section class="list-card erp-list-data" aria-label="采购入库列表">
        <div class="erp-list-table-frame">
        <ElTable v-loading="loading" :data="filteredRows" height="100%" class="purchase-table" row-key="id" :empty-text="loadError ? '采购入库列表加载失败' : loading ? '正在加载采购入库…' : '暂无采购入库订单'" @row-click="rowClicked">
          <ElTableColumn label="生产任务/打样单号" min-width="150" show-overflow-tooltip><template #default="{ row }"><strong>{{ (row.source_type === 'SAMPLE' ? row.source_number : row.production_task_number) || '—' }}</strong></template></ElTableColumn>
          <ElTableColumn label="采购单号" min-width="174" show-overflow-tooltip><template #default="{ row }"><span class="purchase-number">{{ row.order_number }}</span></template></ElTableColumn>
          <ElTableColumn label="采购批次" width="96"><template #default="{ row }">{{ row.batch_number ? `第 ${row.batch_number} 批` : '—' }}</template></ElTableColumn>
          <ElTableColumn label="品名" min-width="150" show-overflow-tooltip><template #default="{ row }">{{ displayProductField(row, 'product_name') }}</template></ElTableColumn>
          <ElTableColumn label="货号" min-width="110" show-overflow-tooltip><template #default="{ row }">{{ displayProductField(row, 'item_number') }}</template></ElTableColumn>
          <ElTableColumn label="规格" min-width="148" show-overflow-tooltip><template #default="{ row }">{{ displayProductField(row, 'specification') }}</template></ElTableColumn>
          <ElTableColumn label="颜色" min-width="110" show-overflow-tooltip><template #default="{ row }">{{ displayProductField(row, 'color_name') }}</template></ElTableColumn>
          <ElTableColumn label="材质" min-width="100" show-overflow-tooltip><template #default="{ row }">{{ displayProductField(row, 'material') }}</template></ElTableColumn>
          <ElTableColumn label="供应商" min-width="210"><template #default="{ row }">
            <SupplierAmountPopover v-if="row.supplier_summary?.length" :suppliers="row.supplier_summary" :currency="row.currency_code" />
            <span v-else>{{ row.supplier_names.length > 1 ? `共 ${row.supplier_names.length} 家供应商` : row.supplier_names[0] || '—' }}</span>
          </template></ElTableColumn>
          <ElTableColumn label="采购明细" width="100" align="center"><template #default="{ row }">{{ row.line_count }} 项</template></ElTableColumn>
          <ElTableColumn label="待收项数" width="92" align="center"><template #default="{ row }"><span data-testid="remaining-receipt-lines">{{ row.remaining_line_count }} 项</span></template></ElTableColumn>
          <ElTableColumn label="到货进度" width="160"><template #default="{ row }"><div v-if="receiptProgress(row) !== null" class="receipt-progress" data-testid="receipt-progress"><ElProgress :percentage="receiptProgress(row) ?? 0" :show-text="false" :stroke-width="10" :status="receiptProgress(row) === 100 ? 'success' : undefined" :aria-label="`到货进度 ${receiptProgress(row)}%`" /><span>{{ receiptProgress(row) }}%</span></div><span v-else class="muted" data-testid="receipt-progress-unknown">待核对</span></template></ElTableColumn>
          <ElTableColumn label="收货状态" width="132" align="center"><template #default="{ row }">
            <span class="status-badge erp-list-tag" :class="`erp-list-tag--${receivingState(row).color}`" data-testid="receiving-status">{{ receivingState(row).label }}</span>
            <small v-if="row.return_status === 'QUALITY_GENERATED'" class="return-note">等待确认退货</small>
            <small v-else-if="row.return_status === 'PROCUREMENT_CONFIRMED'" class="return-note">等待退货完成</small>
          </template></ElTableColumn>
          <ElTableColumn label="待质检" width="88" align="center"><template #default="{ row }">
            <span data-testid="pending-quality-batches" :class="row.pending_quality_count > 0 ? 'erp-list-tag erp-list-tag--warning' : 'muted'">{{ row.pending_quality_count > 0 ? `${row.pending_quality_count} 批` : '—' }}</span>
          </template></ElTableColumn>
          <ElTableColumn label="更新时间" width="150"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></ElTableColumn>
          <ElTableColumn label="操作" width="72" fixed="right" align="center"><template #default="{ row }">
            <span class="more-action" @click.stop>
              <ElDropdown :persistent="false" trigger="click" placement="bottom-end">
                <ElButton link class="row-more-button" :icon="MoreFilled" :aria-label="`${row.order_number}的更多操作`" />
                <template #dropdown><ElDropdownMenu>
                  <ElDropdownItem @click="openDetails(row)">查看详情</ElDropdownItem>
                  <template v-if="canOpenReceiving(row)">
                    <ElDropdownItem v-if="row.source_type === 'SAMPLE'" @click="openReceiving(row)">{{ receivingActionLabel(row) }}</ElDropdownItem>
                    <ElDropdownItem v-for="section in row.receiving_sections" :key="section.id" @click="openReceiving(row, section.id)">{{ section.name }}入库</ElDropdownItem>
                  </template>
                  <ElDropdownItem v-if="canOpenReturns(row)" @click="openReturns(row)">{{ returnActionLabel(row) }}</ElDropdownItem>
                </ElDropdownMenu></template>
              </ElDropdown>
            </span>
          </template></ElTableColumn>
        </ElTable>
        </div>
        <footer class="list-card__footer erp-list-footer"><span>共 {{ listReady ? filteredRows.length : '—' }} 条</span></footer>
      </section>
    </template>
  </section>
</template>

<style scoped lang="scss">
.page-head p { margin: 2px 0 0; color: var(--erp-color-text-secondary); font-size: 12px; }
.filters > .inbound-search { width: min(250px, 100%); flex: none; }
.filters > .el-select { width: 190px; flex: none; }
.purchase-number { font-size: 12px; }
.receipt-progress { display: grid; grid-template-columns: 80px 44px; align-items: center; gap: 8px; }
.receipt-progress > span { text-align: right; font-variant-numeric: tabular-nums; }
.muted { color: var(--erp-table-text); font-size: 12px; }
.more-action { display: inline-flex; align-items: center; justify-content: center; }
.row-more-button { width: 36px; height: 32px; margin: 0; color: var(--erp-table-text); }
.purchase-table :deep(.el-table__row) { cursor: pointer; }
.status-badge { min-width: 88px; }
.return-note { display: block; color: var(--erp-color-text-secondary); }
.empty-state { padding: 80px; text-align: center; color: var(--erp-color-text-secondary); }
</style>
