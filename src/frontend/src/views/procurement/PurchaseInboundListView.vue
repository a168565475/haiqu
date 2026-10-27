<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, ref } from 'vue'
import { MoreFilled, Search } from '@element-plus/icons-vue'

import { fetchProcurementInboundOrders } from '@/api/inventory'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import SupplierAmountPopover from '@/components/procurement/SupplierAmountPopover.vue'
import type { ProcurementInboundOrder, ProcurementInboundProductSummary } from '@/types/inventory'

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

const filteredRows = computed(() => workflowStatus.value
  ? rows.value.filter(row => row.workflow_status === workflowStatus.value)
  : rows.value)

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
function displayProductField(row: ProcurementInboundOrder, field: keyof ProcurementInboundProductSummary): string {
  return row.product_summary?.map(product => product[field]?.trim() || '—').join('、') || '—'
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
  <section class="inbound-list-page erp-glass-list" data-testid="purchase-inbound-list-page">
    <div v-if="!canView" class="empty-state"><h1>无权查看采购入库</h1><p>请联系管理员开通仓库入库或品质确认权限。</p></div>
    <template v-else>
      <section v-glass-spotlight class="erp-list-filter">
      <header class="page-head erp-list-heading">
        <div><h1>采购入库</h1><p>采购订单 · 仓库入库与品质进度</p></div>
      </header>

      <form class="filters erp-list-filters" @submit.prevent="loadRows">
        <ElInput v-model="keyword" class="inbound-search" aria-label="搜索采购入库" clearable maxlength="200" placeholder="搜索采购单、来源单等" title="支持采购单、生产单、销售单、打样单或供应商名称" @keydown.enter="handleSearchEnter" @clear="loadRows">
          <template #suffix><button type="button" class="erp-list-search-button" aria-label="搜索采购入库列表" @click="loadRows"><ElIcon><Search /></ElIcon></button></template>
        </ElInput>
        <ElSelect v-model="workflowStatus" clearable aria-label="采购入库状态" placeholder="入库状态：全部">
          <ElOption label="等待入库" value="PENDING_RECEIPT" />
          <ElOption label="部分入库" value="PARTIAL_RECEIVED" />
          <ElOption label="待品质确认" value="PENDING_QUALITY" />
          <ElOption label="等待确认退货" value="PENDING_PROCUREMENT_CONFIRMATION" />
          <ElOption label="等待退货完成" value="PENDING_RETURN" />
          <ElOption label="已完成" value="COMPLETED" />
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
          <ElTableColumn label="采购单" min-width="174" show-overflow-tooltip><template #default="{ row }"><strong class="purchase-number">{{ row.order_number }}</strong></template></ElTableColumn>
          <ElTableColumn label="来源单号" min-width="126" show-overflow-tooltip><template #default="{ row }">{{ row.source_number || '—' }}</template></ElTableColumn>
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
          <ElTableColumn label="待入库" width="92" align="center"><template #default="{ row }">{{ row.remaining_line_count }} 项</template></ElTableColumn>
          <ElTableColumn label="累计到货" width="116" align="right"><template #default="{ row }">{{ formatQuantity(row.received_quantity) }}</template></ElTableColumn>
          <ElTableColumn label="当前状态" width="124" align="center"><template #default="{ row }"><span class="status-badge erp-list-tag" :class="[`status-${row.workflow_status}`, row.workflow_status === 'COMPLETED' ? 'erp-list-tag--success' : row.workflow_status === 'PARTIAL_RECEIVED' ? 'erp-list-tag--brand' : row.workflow_status === 'PENDING_QUALITY' ? 'erp-list-tag--warning' : row.workflow_status === 'PENDING_PROCUREMENT_CONFIRMATION' ? 'erp-list-tag--danger' : row.workflow_status === 'PENDING_RETURN' ? 'erp-list-tag--info' : 'erp-list-tag--neutral']">{{ row.workflow_status_display }}</span></template></ElTableColumn>
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
.purchase-number { font-size: 12px; font-weight: 600; }
.muted { color: var(--erp-table-text); font-size: 12px; }
.more-action { display: inline-flex; align-items: center; justify-content: center; }
.row-more-button { width: 36px; height: 32px; margin: 0; color: var(--erp-table-text); }
.purchase-table :deep(.el-table__row) { cursor: pointer; }
.status-badge { min-width: 88px; }
.empty-state { padding: 80px; text-align: center; color: var(--erp-color-text-secondary); }
</style>
