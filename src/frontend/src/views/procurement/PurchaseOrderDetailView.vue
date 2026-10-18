<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElTooltip } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { fetchPurchaseOrderReadDetail } from '@/api/purchaseOrderReadDetail'
import { useAuthStore } from '@/stores/auth'
import { usePageTabsStore } from '@/stores/pageTabs'
import type { PurchaseOrderReadDetail } from '@/types/purchaseOrderReadDetail'
import { materialAttributeFields, materialSpecificationValue, type MaterialAttributeSource } from '@/utils/materialAttributes'
import { formatMoney, formatQuantity, formatTime, formatUnitPrice, quantityTotal } from './purchaseOrderDetailDisplay'

type Tab = 'materials' | 'inbounds' | 'returns' | 'completion'
interface Column { key: string; label: string; width: number; numeric?: boolean }
interface RecordRow { id: string; cells: Record<string, string>; status?: string; materialSource?: MaterialAttributeSource }

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const pageTabs = usePageTabsStore()
const can = (permission: string) => auth.user?.is_superuser === true || auth.hasPermission(permission)
const canRead = computed(() => ['procurement.view_purchaseorder', 'inventory.receive_material', 'inventory.quality_confirm_material'].some(can))
const canReadSheets = computed(() => auth.user?.is_superuser === true || auth.moduleCan('procurement.view_supplierpurchasesheet', 'procurement.view_purchaseorder'))
const fromInbound = computed(() => route.name === 'purchase-inbound-detail')
const order = ref<PurchaseOrderReadDetail | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const activeTab = ref<Tab>('materials')
const hoveredRowId = ref('')
let requestVersion = 0
let disposed = false

const suppliers = computed(() => [...new Map((order.value?.supplier_summary ?? []).map(item => [item.id, item])).values()])
const productLabel = computed(() => {
  const products = order.value?.product_summary ?? []
  if (products.length) return products.map(product => [product.product_name, product.color_name].filter(Boolean).join(' · ')).join('；')
  return [...new Set((order.value?.lines ?? []).map(line => line.product_name).filter(Boolean))].join('；') || '—'
})
const deliveryLabel = computed(() => {
  const dates = [...new Set((order.value?.lines ?? []).map(line => line.delivery_date).filter((date): date is string => Boolean(date)))].sort()
  if (!dates.length) return '—'
  return dates.length === 1 ? dates[0] : `${dates[0]} ～ ${dates[dates.length - 1]}`
})
const tabs = computed<{ key: Tab; label: string; count?: number }[]>(() => [
  { key: 'materials', label: '材料明细', count: order.value?.lines.length },
  { key: 'inbounds', label: '入库记录', count: order.value?.inbounds.length },
  { key: 'returns', label: '退货记录', count: order.value?.returns.length },
  { key: 'completion', label: '完成记录' },
])
const materialColumns: Column[] = [
  { key: 'index', label: '序号', width: 64 }, { key: 'name', label: '物料名称', width: 200 },
  { key: 'specification', label: '规格', width: 220 },
  { key: 'purchase', label: '采购数量', width: 152, numeric: true },
  { key: 'price', label: '单价（元）', width: 132, numeric: true }, { key: 'amount', label: '金额（元）', width: 154, numeric: true },
  { key: 'received', label: '累计到货', width: 146, numeric: true }, { key: 'accepted', label: '合格入库', width: 146, numeric: true },
  { key: 'returned', label: '退货数量', width: 146, numeric: true },
]
const sampleMaterialColumns: Column[] = [
  { key: 'index', label: '序号', width: 64 }, { key: 'name', label: '物料名称', width: 200 },
  { key: 'specification', label: '规格', width: 240 }, { key: 'material', label: '材质', width: 140 },
  { key: 'color', label: '颜色', width: 140 }, { key: 'purchase', label: '采购数量', width: 152, numeric: true },
  { key: 'price', label: '单价（元）', width: 132, numeric: true }, { key: 'amount', label: '金额（元）', width: 154, numeric: true },
  { key: 'received', label: '累计到货', width: 146, numeric: true }, { key: 'accepted', label: '合格入库', width: 146, numeric: true },
  { key: 'returned', label: '退货数量', width: 146, numeric: true },
]
const inboundColumns: Column[] = [
  { key: 'number', label: '入库单', width: 190 }, { key: 'date', label: '入库日期', width: 118 },
  { key: 'name', label: '物料名称', width: 220 },
  { key: 'specification', label: '规格', width: 180 },
  { key: 'supplier', label: '供应商', width: 180 }, { key: 'received', label: '到货数量', width: 120, numeric: true },
  { key: 'accepted', label: '合格入库', width: 120, numeric: true }, { key: 'returned', label: '退货数量', width: 120, numeric: true },
  { key: 'status', label: '入库状态', width: 114 }, { key: 'warehouse', label: '仓库位置', width: 180 },
  { key: 'receiver', label: '收货人', width: 110 }, { key: 'inspector', label: '品质确认人', width: 120 },
  { key: 'time', label: '品质确认时间', width: 164 }, { key: 'remark', label: '品质说明', width: 200 },
]
const sampleInboundColumns: Column[] = [
  { key: 'number', label: '入库单', width: 190 }, { key: 'date', label: '入库日期', width: 118 },
  { key: 'name', label: '物料名称', width: 160 }, { key: 'specification', label: '规格', width: 160 },
  { key: 'material', label: '材质', width: 100 }, { key: 'color', label: '颜色', width: 100 },
  { key: 'supplier', label: '供应商', width: 180 }, { key: 'received', label: '到货数量', width: 120, numeric: true },
  { key: 'accepted', label: '合格入库', width: 120, numeric: true }, { key: 'returned', label: '退货数量', width: 120, numeric: true },
  { key: 'status', label: '入库状态', width: 114 }, { key: 'warehouse', label: '仓库位置', width: 180 },
  { key: 'receiver', label: '收货人', width: 110 }, { key: 'inspector', label: '品质确认人', width: 120 },
  { key: 'time', label: '品质确认时间', width: 164 }, { key: 'remark', label: '品质说明', width: 200 },
]
const returnColumns: Column[] = [
  { key: 'number', label: '退货单', width: 190 }, { key: 'inbound', label: '来源入库单', width: 190 },
  { key: 'name', label: '物料名称', width: 220 },
  { key: 'specification', label: '规格', width: 180 },
  { key: 'supplier', label: '供应商', width: 180 }, { key: 'quantity', label: '退货数量', width: 120, numeric: true },
  { key: 'status', label: '退货状态', width: 130 }, { key: 'remark', label: '品质说明', width: 180 },
  { key: 'confirmedBy', label: '采购确认人', width: 120 }, { key: 'completedBy', label: '退货完成人', width: 120 },
  { key: 'time', label: '退货完成时间', width: 164 },
]
const sampleReturnColumns: Column[] = [
  { key: 'number', label: '退货单', width: 190 }, { key: 'inbound', label: '来源入库单', width: 190 },
  { key: 'name', label: '物料名称', width: 160 }, { key: 'specification', label: '规格', width: 160 },
  { key: 'material', label: '材质', width: 100 }, { key: 'color', label: '颜色', width: 100 },
  { key: 'supplier', label: '供应商', width: 180 }, { key: 'quantity', label: '退货数量', width: 120, numeric: true },
  { key: 'status', label: '退货状态', width: 130 }, { key: 'remark', label: '品质说明', width: 180 },
  { key: 'confirmedBy', label: '采购确认人', width: 120 }, { key: 'completedBy', label: '退货完成人', width: 120 },
  { key: 'time', label: '退货完成时间', width: 164 },
]
const columns = computed(() => {
  const isSample = order.value?.source_type === 'SAMPLE'
  if (activeTab.value === 'inbounds') return isSample ? sampleInboundColumns : inboundColumns
  if (activeTab.value === 'returns') return isSample ? sampleReturnColumns : returnColumns
  return isSample ? sampleMaterialColumns : materialColumns
})
const tableWidth = computed(() => columns.value.reduce((total, column) => total + column.width, 0))
const quantityWithUnit = (value: unknown, unit: string) => {
  const number = formatQuantity(value)
  return number === '—' ? number : `${number}${unit ? ` ${unit}` : ''}`
}
const rows = computed<RecordRow[]>(() => {
  if (!order.value) return []
  if (activeTab.value === 'materials') return order.value.lines.map((line, index) => ({ id: line.id, materialSource: line, cells: {
    index: String(index + 1), name: line.part_name || line.raw_material || '—', specification: order.value?.source_type === 'SAMPLE' ? (line.specification || '—') : materialSpecificationValue(line), material: line.material || '—', color: line.color || '—', purchase: quantityWithUnit(line.actual_purchase_quantity, line.source_unit_text),
    price: formatUnitPrice(line.unit_price), amount: formatMoney(line.amount), received: quantityWithUnit(line.received_quantity, line.source_unit_text),
    accepted: quantityWithUnit(line.accepted_quantity, line.source_unit_text), returned: quantityWithUnit(line.return_quantity, line.source_unit_text),
  } }))
  if (activeTab.value === 'inbounds') {
    const materials = new Map(order.value.lines.map(line => [line.id, line]))
    return order.value.inbounds.flatMap(batch => batch.lines.map(line => ({ id: line.id, status: batch.status, materialSource: line, cells: {
      number: batch.inbound_number, date: batch.inbound_date, name: line.part_name_snapshot, specification: order.value?.source_type === 'SAMPLE' ? (line.specification_snapshot || '—') : materialSpecificationValue(line), material: line.material_snapshot || '—', color: materials.get(line.purchase_order_line_id)?.color || '—', supplier: line.supplier_name_snapshot || '—',
      received: quantityWithUnit(line.received_quantity, line.source_unit_text_snapshot),
      accepted: batch.status === 'CONFIRMED' ? quantityWithUnit(line.accepted_quantity, line.source_unit_text_snapshot) : '—',
      returned: batch.status === 'CONFIRMED' ? quantityWithUnit(line.return_quantity, line.source_unit_text_snapshot) : '—',
      status: batch.status_display, warehouse: [line.warehouse_name, line.zone_name, line.location_number].filter(Boolean).join(' / ') || '—',
      receiver: batch.received_by_name || '—', inspector: batch.quality_confirmed_by_name || '—', time: formatTime(batch.quality_confirmed_at), remark: line.quality_remark || '—',
    } })))
  }
  return order.value.returns.flatMap(record => record.lines.map(line => ({ id: line.id, status: record.status, materialSource: line, cells: {
    number: record.return_number, inbound: record.inbound_number, name: line.part_name, specification: order.value?.source_type === 'SAMPLE' ? (line.specification || '—') : materialSpecificationValue(line), material: line.material || '—', color: line.color || '—', supplier: record.supplier_name || '—', quantity: quantityWithUnit(line.quantity, line.unit), status: record.status_display,
    remark: line.quality_remark || '—', confirmedBy: record.confirmed_by_name || '—', completedBy: record.completed_by_name || '—', time: formatTime(record.completed_at),
  } })))
})
const totals = computed<Record<string, string>>(() => {
  const lines = order.value?.lines ?? []
  return { index: '合计', purchase: quantityTotal(lines, lines.map(line => line.actual_purchase_quantity)),
    amount: formatMoney(order.value?.total_amount), received: quantityTotal(lines, lines.map(line => line.received_quantity)),
    accepted: quantityTotal(lines, lines.map(line => line.accepted_quantity)), returned: quantityTotal(lines, lines.map(line => line.return_quantity)) }
})
function statusTone(status: string) {
  return ['COMPLETED', 'CONFIRMED'].includes(status) ? 'success' : ['DRAFT', 'PENDING_QUALITY', 'QUALITY_GENERATED'].includes(status) ? 'warning' : 'info'
}
function backToList() { void router.push({ name: fromInbound.value ? 'purchase-inbounds' : 'purchase-orders' }) }
function openSheets() { if (order.value && canReadSheets.value) void router.push({ name: 'supplier-purchase-sheets', query: { purchase_order_id: order.value.id } }) }
function switchTab(event: KeyboardEvent, index: number) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? 3 : (index + (event.key === 'ArrowRight' ? 1 : -1) + 4) % 4
  activeTab.value = tabs.value[next]!.key
  document.getElementById(`purchase-detail-tab-${activeTab.value}`)?.focus()
}
async function load() {
  const version = ++requestVersion
  order.value = null
  errorMessage.value = ''
  loading.value = false
  if (!canRead.value) return
  loading.value = true
  try {
    const result = await fetchPurchaseOrderReadDetail(String(route.params.id || ''))
    if (disposed || version !== requestVersion) return
    order.value = result
    if (pageTabs.accountId === String(auth.user?.id)) {
      pageTabs.setTabTitle(route, fromInbound.value ? '采购入库明细' : '采购明细')
    }
  } catch (error) {
    if (disposed || version !== requestVersion) return
    const response = (error as { response?: { status?: number; data?: { error?: { message?: string } } } }).response
    errorMessage.value = response?.status === 404 ? '采购订单不存在或不在可查看范围内。' : response?.status === 403 ? '当前账号无权查看此采购订单。' : response?.data?.error?.message || (error instanceof Error ? error.message : '明细加载失败，请重试。')
  } finally {
    if (!disposed && version === requestVersion) loading.value = false
  }
}
watch([() => route.params.id, canRead, fromInbound], () => {
  activeTab.value = fromInbound.value ? 'inbounds' : 'materials'
  void load()
}, { immediate: true })
onBeforeUnmount(() => { disposed = true; requestVersion++ })
</script>

<template>
  <section class="purchase-detail-page erp-glass-detail" data-testid="purchase-order-detail" :aria-busy="loading">
    <header class="detail-heading">
      <div class="heading-identity"><h1>采购订单详情</h1><span v-if="order" class="detail-tag" :class="statusTone(order.status)">{{ order.status_display }}</span><span class="readonly-label">只读</span></div>
      <div class="heading-actions">
        <button v-if="order && canReadSheets && order.status !== 'DRAFT'" class="detail-button erp-list-button erp-button-motion" @click="openSheets">查看采购表</button>
        <button class="detail-button erp-list-button erp-list-button--primary erp-button-motion" @click="backToList"><ArrowLeft aria-hidden="true" />返回{{ fromInbound ? '采购入库' : '采购订单' }}</button>
      </div>
    </header>
    <div v-if="!canRead" class="detail-state" role="status">无权查看采购明细，请联系管理员开通相应权限。</div>
    <div v-else-if="loading" class="detail-state" role="status">正在加载采购明细…</div>
    <div v-else-if="errorMessage" class="detail-state error-state" role="alert"><p>{{ errorMessage }}</p><button class="detail-button erp-list-button erp-button-motion" @click="load">重新加载</button></div>
    <template v-else-if="order">
      <dl class="order-metadata">
        <div><dt>采购单号</dt><dd :title="order.order_number">{{ order.order_number }}</dd></div>
        <div><dt>采购来源</dt><dd>{{ order.source_type_display || (order.source_type === 'SAMPLE' ? '打样采购' : '生产订单') }}</dd></div>
        <div><dt>{{ order.source_type === 'SAMPLE' ? '打样单号' : '生产单号' }}</dt><dd :title="order.source_number || order.production_task_number">{{ order.source_number || order.production_task_number || '—' }}</dd></div>
        <div><dt>关联订单</dt><dd :title="order.sales_order_number">{{ order.sales_order_number || '—' }}</dd></div>
        <div><dt>产品</dt><dd :title="productLabel">{{ productLabel }}</dd></div>
        <div><dt>下单日期</dt><dd>{{ formatTime(order.created_at, true) }}</dd></div>
        <div><dt>采购交期</dt><dd :title="deliveryLabel">{{ deliveryLabel }}</dd></div>
        <div><dt>供应商</dt><dd>
          <ElTooltip v-if="suppliers.length" placement="bottom-start" effect="light" :show-after="100" popper-class="purchase-detail-suppliers-tooltip">
            <template #content><div class="supplier-tooltip-content"><strong>共 {{ suppliers.length }} 家供应商</strong><ul><li v-for="supplier in suppliers" :key="supplier.id">{{ supplier.supplier_name || '—' }}</li></ul></div></template>
            <span class="supplier-count" tabindex="0" aria-label="查看供应商完整名单" data-testid="supplier-count">共 {{ suppliers.length }} 家供应商</span>
          </ElTooltip><span v-else>未分配供应商</span>
        </dd></div>
        <div><dt>采购员</dt><dd :title="order.created_by_name">{{ order.created_by_name || '—' }}</dd></div>
        <div><dt>采购金额{{ order.currency_code && order.currency_code !== 'CNY' ? `（${order.currency_code}）` : '' }}</dt><dd class="order-amount">{{ order.total_amount === null ? '—' : `${order.currency_symbol || ''}${formatMoney(order.total_amount)}` }}</dd></div>
      </dl>
      <section class="detail-content-card">
      <nav class="detail-tabs" role="tablist" aria-label="采购明细分类">
        <button v-for="(tab, index) in tabs" :id="`purchase-detail-tab-${tab.key}`" :key="tab.key" role="tab" :aria-selected="activeTab === tab.key" :aria-controls="`purchase-detail-panel-${tab.key}`" :tabindex="activeTab === tab.key ? 0 : -1" :class="{ selected: activeTab === tab.key }" @click="activeTab = tab.key" @keydown="switchTab($event, index)">{{ tab.label }}<span v-if="tab.count !== undefined">{{ tab.count }}</span></button>
      </nav>
      <div :id="`purchase-detail-panel-${activeTab}`" role="tabpanel" :aria-labelledby="`purchase-detail-tab-${activeTab}`">
        <div v-if="activeTab === 'completion'" class="completion-record">
          <template v-if="order.completed_at"><dl><div><dt>采购状态</dt><dd><span class="detail-tag" :class="statusTone(order.status)">{{ order.status_display }}</span></dd></div><div><dt>完成人</dt><dd>{{ order.completed_by_name || '—' }}</dd></div><div><dt>完成时间</dt><dd>{{ formatTime(order.completed_at) }}</dd></div></dl><p><span>完成备注</span>{{ order.completion_remark || '—' }}</p></template>
          <p v-else class="empty-record">暂无完成记录</p>
        </div>
        <div v-else class="detail-table-scroll" tabindex="0" :aria-label="`${tabs.find(tab => tab.key === activeTab)?.label}表格`">
          <table class="detail-table" :style="{ minWidth: `${tableWidth}px` }" :data-testid="`detail-table-${activeTab}`">
            <colgroup><col v-for="column in columns" :key="column.key" :style="{ width: `${column.width}px` }" /></colgroup>
            <thead><tr><th v-for="column in columns" :key="column.key" scope="col" :class="{ numeric: column.numeric }">{{ column.key === 'price' || column.key === 'amount' ? column.label.replace('元', order.currency_code === 'CNY' ? '元' : order.currency_code || '币种未记录') : column.label }}</th></tr></thead>
            <tbody><tr v-for="row in rows" :key="row.id" @mouseenter="hoveredRowId = row.id" @mouseleave="hoveredRowId = ''"><td v-for="column in columns" :key="column.key" :class="{ numeric: column.numeric, 'material-name': column.key === 'name', 'money-cell': column.key === 'amount' }" :title="column.key === 'name' || column.key === 'specification' ? undefined : row.cells[column.key]"><ElTooltip v-if="column.key === 'specification' && order.source_type !== 'SAMPLE'" placement="top" :show-after="80" :visible="hoveredRowId === row.id" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in materialAttributeFields(row.materialSource || {})" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div></div></template><span class="cell-text">{{ row.cells[column.key] || '—' }}</span></ElTooltip><span v-else-if="column.key === 'status'" class="detail-tag" :class="statusTone(row.status || '')">{{ row.cells[column.key] }}</span><span v-else class="cell-text">{{ row.cells[column.key] || '—' }}</span></td></tr><tr v-if="!rows.length"><td :colspan="columns.length" class="empty-record">暂无{{ tabs.find(tab => tab.key === activeTab)?.label }}</td></tr></tbody>
            <tfoot v-if="activeTab === 'materials' && rows.length"><tr><td v-for="column in columns" :key="column.key" :class="{ numeric: column.numeric }" :title="['purchase', 'received', 'accepted', 'returned'].includes(column.key) && totals[column.key] === '—' ? '不同单位或缺少数量时不合计' : undefined"><span class="cell-text">{{ totals[column.key] || '—' }}</span></td></tr></tfoot>
          </table>
        </div>
      </div>
      <footer v-if="activeTab !== 'completion'" class="completion-note"><div><strong>完成备注：</strong><span>{{ order.completion_remark || '—' }}</span></div><div><strong>完成人：</strong><span>{{ order.completed_by_name || '—' }}</span><span>{{ formatTime(order.completed_at) }}</span></div></footer>
      </section>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;
.purchase-detail-page { color: token.$crm-text-primary; font-family: token.$crm-font-body; font-size: 13px; min-width: 0; container-type: inline-size; background: transparent; }
.detail-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; min-height: 46px; margin-bottom: 14px; }
.heading-identity, .heading-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; }
.detail-heading h1 { margin: 0; font: 700 36px/44px token.$crm-font-body; }
.readonly-label { color: token.$crm-text-secondary; }
.detail-button { white-space: nowrap; }
.detail-button svg { width: 16px; height: 16px; }
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: var(--erp-color-text-secondary); min-width: 42px; }
.detail-button:focus-visible, .supplier-count:focus-visible, .detail-tabs button:focus-visible, .detail-table-scroll:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
.detail-tag { display: inline-flex; align-items: center; justify-content: center; box-sizing: border-box; min-width: 56px; height: 24px; padding: 0 8px; border: 0; border-radius: 999px; color: var(--erp-color-text-inverse); background: var(--erp-tag-neutral-background); font: 500 12px/18px token.$crm-font-body; white-space: nowrap; }
.detail-tag.success { background: var(--erp-tag-success-background); } .detail-tag.warning { background: var(--erp-tag-warning-background); } .detail-tag.info { background: var(--erp-tag-info-background); }
.order-metadata { @include detail.surface; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin: 0 0 14px; padding: 16px; }
.order-metadata > div { min-width: 0; }
dt { color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; }
.order-metadata dd { margin: 4px 0 0; overflow-wrap: anywhere; font-size: 13px; line-height: 20px; }
.detail-content-card { @include detail.surface; padding: 14px 16px 16px; }
.supplier-count { cursor: help; border-bottom: 1px dashed token.$crm-border-strong; }
.order-metadata .order-amount { color: token.$crm-primary; font-weight: 600; }
.detail-tabs { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; min-height: 46px; border-bottom: 1px solid token.$crm-border-subtle; margin-bottom: 14px; }
.detail-tabs button { position: relative; height: 32px; padding: 0 16px; border: 0; background: transparent; color: token.$crm-text-primary; font: 500 13px/18px token.$crm-font-body; cursor: pointer; }
.detail-tabs button span { margin-left: 8px; font-size: 12px; }
.detail-tabs button.selected { color: token.$crm-primary; }
.detail-tabs button.selected::after { content: ''; position: absolute; height: 2px; background: token.$crm-primary; bottom: 0; left: 16px; right: 16px; }
.detail-table-scroll { max-width: 100%; overflow-x: auto; border: 1px solid var(--erp-table-grid); border-radius: var(--erp-radius-control); background: var(--erp-table-body-fill); }
.detail-table { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; }
.detail-table th, .detail-table td { box-sizing: border-box; padding: 0 16px; text-align: left; border-right: 1px solid var(--erp-table-grid); border-bottom: 1px solid var(--erp-table-grid); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.detail-table th:last-child, .detail-table td:last-child { border-right: 0; }
.detail-table thead tr, .detail-table th { height: 44px; }
.detail-table th { color: var(--erp-table-header-text); background: var(--erp-table-header-fill); font-size: 11px; font-weight: 500; line-height: 16px; }
.detail-table tbody tr, .detail-table tfoot tr, .detail-table td { height: 40px; }
.detail-table td { color: var(--erp-table-text); font-size: 12px; line-height: 18px; }
.cell-text { display: block; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.detail-table td.material-name { font-size: 13px; line-height: 20px; font-weight: 500; color: var(--erp-table-text); }
.detail-table td.money-cell, .detail-table tfoot td { font-size: 13px; font-weight: 600; color: var(--erp-table-text); }
.detail-table tfoot td:nth-child(8) { color: var(--erp-table-text); }
.detail-table .numeric { text-align: right; }
.detail-table tbody tr:hover { background: var(--erp-color-hover); }
.detail-table tfoot tr:last-child td, .detail-table:not(:has(tfoot)) tbody tr:last-child td { border-bottom: 0; }
.detail-table .empty-record { text-align: center; color: token.$crm-text-muted; }
.completion-note { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: 14px; min-height: 40px; box-sizing: border-box; padding-top: 14px; margin-top: 14px; border-top: 1px solid token.$crm-border-subtle; line-height: 20px; }
.completion-note > div { display: flex; gap: 8px; min-width: 0; }
.completion-note > div:first-child { flex: 1; overflow-wrap: anywhere; }
.completion-note strong { flex-shrink: 0; font-weight: 500; }
.completion-record { @include detail.inset; padding: 16px; }
.completion-record dl { display: grid; grid-template-columns: 1fr 1fr 2fr; margin: 0; gap: 16px; }
.completion-record dd { margin: 8px 0 0; }
.completion-record p:not(.empty-record) { display: flex; gap: 24px; margin: 16px 0 0; padding-top: 16px; border-top: 1px solid token.$crm-border-default; white-space: pre-wrap; overflow-wrap: anywhere; }
.completion-record p > span { flex-shrink: 0; color: token.$crm-text-secondary; }
.detail-state { @include detail.surface; padding: 32px; text-align: center; color: token.$crm-text-secondary; }
.error-state { color: token.$crm-danger; } .empty-record { text-align: center; color: token.$crm-text-secondary; }
.supplier-tooltip-content { max-width: 460px; max-height: 320px; overflow: auto; font: 12px/22px token.$crm-font-body; color: token.$crm-text-primary; }
.supplier-tooltip-content ul { margin: 6px 0 0; padding: 0 0 0 18px; } .supplier-tooltip-content li { overflow-wrap: anywhere; }
:global(.purchase-detail-suppliers-tooltip.el-popper) { border: 1px solid var(--erp-color-border); border-radius: var(--erp-radius-control); background: var(--erp-color-surface); padding: 10px 14px; }
@container (max-width: 1000px) { .order-metadata { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@container (max-width: 650px) { .order-metadata { grid-template-columns: repeat(2, minmax(0, 1fr)); } .completion-record dl { grid-template-columns: minmax(0, 1fr); } }
@container (max-width: 420px) { .order-metadata { grid-template-columns: minmax(0, 1fr); } }
</style>
