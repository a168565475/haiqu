<script setup lang="ts">
import { pipeRootError } from '@/utils/pipeQuantities'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Calendar, Refresh, Tickets, WarningFilled } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { createMaterialReceiving, fetchEligibleMaterialLines, fetchEligibleMaterialPurchaseOrders, fetchMaterialReceivingOptions } from '@/api/inventory'
import { useAuthStore } from '@/stores/auth'
import { router } from '@/router'
import type { EligibleMaterialLine, EligibleMaterialPurchaseOrder, MaterialReceivingOptions } from '@/types/inventory'
import { materialAttributeFields, materialSpecificationValue } from '@/utils/materialAttributes'

interface ReceivingRow {
  line: EligibleMaterialLine
  included: boolean
  receivedQuantity: string
  warehouseId: string
  zoneId: string
  remark: string
}
const auth = useAuthStore()
const route = useRoute()
const canReceive = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.receive_material'))
const canQuality = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.quality_confirm_material'))
const baseLoading = ref(false)
const linesLoading = ref(false)
const loading = computed(() => baseLoading.value || linesLoading.value)
const submitting = ref(false)
const receiptCreated = ref(false)
const locked = computed(() => loading.value || submitting.value || receiptCreated.value)
const loadError = ref('')
const purchaseOrders = ref<EligibleMaterialPurchaseOrder[]>([])
const selectedPurchaseOrderId = ref('')
const options = ref<MaterialReceivingOptions>({ warehouses: [], zones: [] })
const rows = ref<ReceivingRow[]>([])
const hoveredRowId = ref('')
const hoveredSupplierRowId = ref('')
const bulk = reactive({ warehouseId: '', zoneId: '' })
function localToday() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
}
const form = reactive({ inboundDate: localToday(), remark: '' })
const receivingDraftKey = computed(() => `material-receiving-draft:v2:${selectedPurchaseOrderId.value}`)
let linesRequest = 0
let disposed = false
const selectedOrder = computed(() => purchaseOrders.value.find((item) => item.id === selectedPurchaseOrderId.value))
const selectedRows = computed(() => rows.value.filter((row) => row.included))
const warehouseZones = (warehouseId: string) => options.value.zones.filter((zone) => zone.warehouse === warehouseId)
const bulkZones = computed(() => warehouseZones(bulk.warehouseId))
function hasZone(row: Pick<ReceivingRow, 'warehouseId' | 'zoneId'>) {
  return options.value.warehouses.some((warehouse) => warehouse.id === row.warehouseId)
    && warehouseZones(row.warehouseId).some((zone) => zone.id === row.zoneId)
}
function validQuantity(row: ReceivingRow) {
  if (row.line.raw_bar_length_m) return !pipeRootError(row.receivedQuantity) && Number(row.receivedQuantity) <= (row.line.remaining_bar_count ?? 0)
  return /^\d{1,14}(\.\d{1,4})?$/.test(row.receivedQuantity)
    && Number(row.receivedQuantity) > 0 && Number(row.receivedQuantity) <= Number(row.line.remaining_quantity)
}
function validDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const date = new Date(value + 'T00:00:00Z')
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value && value <= localToday()
}
const zoneReadyCount = computed(() => selectedRows.value.filter(hasZone).length)
const readyToSubmit = computed(() => canReceive.value && !locked.value && !loadError.value && !!selectedOrder.value && validDate(form.inboundDate)
  && selectedRows.value.length > 0 && selectedRows.value.length <= 100
  && selectedRows.value.every((row) => hasZone(row) && validQuantity(row)))
const allSelected = computed({
  get: () => rows.value.length > 0 && selectedRows.value.length === rows.value.length,
  set: (value: boolean) => { if (!locked.value) rows.value.forEach((row) => { row.included = value }) },
})
function apiMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  const field = response?.data?.error?.field_errors ? Object.values(response.data.error.field_errors).flat()[0] : ''
  return field || response?.data?.error?.message || response?.data?.detail || fallback
}
function formatQuantity(value: string | number): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) : '—'
}
function purchaseQuantityText(line: EligibleMaterialLine): string {
  return `${line.raw_bar_length_m ? `${line.actual_bar_count} 根 / ` : ''}${formatQuantity(line.purchased_quantity)} ${line.unit}`
}
function initialQuantity(value: string): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4, useGrouping: false }) : ''
}
function materialTitle(line: EligibleMaterialLine): string { return line.part_name || line.material || '未命名物料' }
function rowWarehouseChanged(row: ReceivingRow) {
  const zones = warehouseZones(row.warehouseId)
  row.zoneId = zones.length === 1 ? zones[0].id : ''
}
function bulkWarehouseChanged() { bulk.zoneId = bulkZones.value.length === 1 ? bulkZones.value[0].id : '' }
function applyBulkZone() {
  if (locked.value || !canReceive.value) return
  if (!hasZone(bulk)) return ElMessage.warning('请先完整选择材料仓和库区。')
  if (!selectedRows.value.length) return ElMessage.warning('请先勾选物料。')
  selectedRows.value.forEach((row) => { row.warehouseId = bulk.warehouseId; row.zoneId = bulk.zoneId })
}
async function loadBase() {
  if (locked.value || !canReceive.value) return
  baseLoading.value = true
  loadError.value = ''
  try {
    const orderId = typeof route.params.purchaseOrderId === 'string' ? route.params.purchaseOrderId : ''
    if (!orderId) throw new Error('采购单编号缺失。')
    selectedPurchaseOrderId.value = orderId
    const [optionData, orderData, lineData] = await Promise.all([
      fetchMaterialReceivingOptions(),
      fetchEligibleMaterialPurchaseOrders({ purchase_order_id: orderId }),
      fetchEligibleMaterialLines(orderId),
    ])
    if (disposed) return
    options.value = optionData
    purchaseOrders.value = orderData
    if (!selectedOrder.value) throw new Error('该采购单当前没有可入库明细。')
    if (!hasZone(bulk)) { bulk.warehouseId = ''; bulk.zoneId = '' }
    // 三项同时读取，全部就绪后再恢复草稿，避免有效库区被尚未到达的选项误清空。
    await selectOrder(true, lineData)
  } catch (error) {
    if (!disposed) loadError.value = apiMessage(error, '采购入库数据加载失败，请刷新重试。')
  } finally { baseLoading.value = false }
}
function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
async function selectOrder(preserveCurrent = false, preloadedLines?: EligibleMaterialLine[]) {
  const request = ++linesRequest
  const orderId = selectedPurchaseOrderId.value
  const currentDraft = preserveCurrent && orderId && rows.value.length ? {
    purchaseOrderId: orderId, inboundDate: form.inboundDate, remark: form.remark,
    rows: Object.fromEntries(rows.value.map((row) => [row.line.id, row])),
  } : null
  if (!currentDraft) {
    rows.value = []
    form.inboundDate = localToday()
    form.remark = ''
  }
  loadError.value = ''
  linesLoading.value = false
  if (!orderId) return
  linesLoading.value = true
  try {
    const lines = preloadedLines ?? await fetchEligibleMaterialLines(orderId)
    // 切换采购单后，迟到的旧响应不能覆盖新单据。
    if (disposed || request !== linesRequest || selectedPurchaseOrderId.value !== orderId) return
    let draft: Record<string, unknown> = currentDraft || {}
    if (!currentDraft) {
      try { draft = record(JSON.parse(localStorage.getItem(receivingDraftKey.value) || '{}')) } catch { /* 草稿不可用时仍可正常收货。 */ }
    }
    if (draft.purchaseOrderId !== orderId) draft = {}
    if (validDate(draft.inboundDate)) form.inboundDate = draft.inboundDate
    if (typeof draft.remark === 'string') form.remark = draft.remark.slice(0, 3000)
    const savedRows = record(draft.rows)
    rows.value = lines.map((line) => {
      const saved = record(savedRows[line.id])
      const row: ReceivingRow = {
        line, included: typeof saved.included === 'boolean' ? saved.included : true,
        receivedQuantity: saved.receivedQuantity === undefined ? line.raw_bar_length_m ? String(line.remaining_bar_count ?? '') : initialQuantity(line.remaining_quantity)
          : typeof saved.receivedQuantity === 'string' || typeof saved.receivedQuantity === 'number' ? String(saved.receivedQuantity) : '',
        warehouseId: typeof saved.warehouseId === 'string' ? saved.warehouseId : '',
        zoneId: typeof saved.zoneId === 'string' ? saved.zoneId : '',
        remark: typeof saved.remark === 'string' ? saved.remark.slice(0, 3000) : '',
      }
      if (!options.value.warehouses.some((warehouse) => warehouse.id === row.warehouseId)) row.warehouseId = ''
      if (!hasZone(row)) row.zoneId = ''
      return row
    })
  } catch (error) {
    if (!disposed && request === linesRequest) loadError.value = apiMessage(error, '采购明细加载失败，请刷新重试。')
  } finally { if (request === linesRequest) linesLoading.value = false }
}
function saveDraft() {
  if (locked.value || !canReceive.value) return
  if (!selectedPurchaseOrderId.value || !rows.value.length) return ElMessage.warning('请先选择有待收货明细的采购单。')
  try {
    localStorage.setItem(receivingDraftKey.value, JSON.stringify({
      purchaseOrderId: selectedPurchaseOrderId.value, inboundDate: form.inboundDate, remark: form.remark,
      rows: Object.fromEntries(rows.value.map((row) => [row.line.id, { included: row.included, receivedQuantity: row.receivedQuantity, warehouseId: row.warehouseId, zoneId: row.zoneId, remark: row.remark }])),
    }))
    ElMessage.success('收货草稿已保存在当前浏览器。')
  } catch { ElMessage.error('浏览器无法保存草稿，请检查存储空间或浏览器设置。当前填写内容仍保留。') }
}
async function submitReceiving() {
  if (locked.value || !canReceive.value) return
  if (!readyToSubmit.value) return ElMessage.warning('请核对到货日期、数量和库区；每批最多提交 100 项。')
  submitting.value = true
  try {
    await createMaterialReceiving({
      inbound_date: form.inboundDate, remark: form.remark,
      items: selectedRows.value.map((row) => ({
        purchase_order_line_id: row.line.id, zone_id: row.zoneId, expected_remaining_quantity: row.line.remaining_quantity,
        ...(row.line.raw_bar_length_m ? { received_bar_count: row.receivedQuantity, raw_bar_length_m: row.line.raw_bar_length_m } : { received_quantity: row.receivedQuantity }), remark: row.remark,
      })),
    })
    receiptCreated.value = true
  } catch (error) {
    ElMessage.error(apiMessage(error, '提交品质确认失败，请核对收货记录后重试。'))
    submitting.value = false
    return
  }
  // 收货成功后，草稿清理或跳转失败都不能再次提交同一批次。
  try { localStorage.removeItem(receivingDraftKey.value) } catch { ElMessage.warning('收货已登记，但浏览器中的旧草稿未能清理。') }
  ElMessage.success('仓库收货已登记，已转入品质确认。')
  try { await router.push({ name: canQuality.value ? 'material-quality-confirmation' : 'purchase-inbounds' }) }
  catch { ElMessage.warning('收货已登记，请从采购入库列表继续处理。') }
  finally { submitting.value = false }
}
onMounted(() => { if (canReceive.value) void loadBase() })
onBeforeUnmount(() => { disposed = true; linesRequest += 1 })
</script>

<template>
  <section class="inventory-workflow erp-glass-form" data-testid="material-purchase-inbound-page">
    <div v-if="!canReceive" class="empty-state"><h1>无权进行采购入库</h1><p>请联系管理员开通采购入库权限。</p></div>
    <template v-else>
      <header class="page-title-row">
        <div><h1>采购入库</h1><p>核对当前采购单的到货数量，并登记材料仓和库区。</p></div>
        <div class="head-actions"><ElButton :icon="Refresh" :loading="loading" :disabled="locked" @click="loadBase">刷新</ElButton><ElButton :icon="Tickets" :disabled="submitting" @click="router.push({ name: 'purchase-inbounds' })">返回列表</ElButton></div>
      </header>
      <div v-if="loadError" class="load-error" role="alert">{{ loadError }}</div>
      <section class="surface bulk-card">
        <div class="bulk-row">
          <h2>本次到货设置</h2>
          <div class="date-field"><label>到货日期</label><ElDatePicker v-model="form.inboundDate" aria-label="到货日期" type="date" value-format="YYYY-MM-DD" :prefix-icon="Calendar" :disabled="locked" :disabled-date="(date: Date) => new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date) > localToday()" /></div>
          <div class="bulk-controls">
            <ElSelect v-model="bulk.warehouseId" aria-label="批量材料仓" placeholder="选择材料仓" :disabled="locked" @change="bulkWarehouseChanged"><ElOption v-for="item in options.warehouses" :key="item.id" :label="item.warehouse_number + ' · ' + item.warehouse_name" :value="item.id" /></ElSelect>
            <ElSelect v-model="bulk.zoneId" aria-label="批量库区" placeholder="选择库区" :disabled="locked || !bulk.warehouseId"><ElOption v-for="item in bulkZones" :key="item.id" :label="item.zone_name" :value="item.id" /></ElSelect>
            <ElButton :disabled="locked || !selectedRows.length" @click="applyBulkZone">应用到已勾选</ElButton>
          </div>
        </div>
      </section>
      <section class="surface table-card">
        <div class="table-head">
          <div><h2>采购明细</h2><div v-if="selectedOrder" class="table-order-meta"><span>采购单号 <strong>{{ selectedOrder.order_number }}</strong></span><span>生产单号 <strong>{{ selectedOrder.production_task_number || '—' }}</strong></span><span>状态 <ElTag type="warning" round>{{ receiptCreated ? '已收货，待质检' : '待收货' }}</ElTag></span></div></div>
          <strong>共 {{ rows.length }} 项</strong>
        </div>
        <div v-loading="loading" class="receiving-table-scroll">
          <table class="erp-table-editor receiving-table">
            <colgroup><col v-for="(width, index) in [56, 58, 230, 190, 234, 160, 106, 156, 182, 164, 214, 124]" :key="index" :style="{ width: width / 1874 * 100 + '%' }" /></colgroup>
            <thead><tr>
              <th><ElCheckbox v-model="allSelected" aria-label="全选物料" :indeterminate="selectedRows.length > 0 && !allSelected" :disabled="locked || !rows.length" /></th>
              <th v-for="title in ['序号', '物料信息', '规格', '供应商', '采购数量', '累计已收', '本次到货数量', '材料仓', '库区', '差异说明', '状态']" :key="title" scope="col">{{ title }}</th>
            </tr></thead>
            <tbody><tr v-for="(row, index) in rows" :key="row.line.id" :data-row-id="row.line.id" @mouseenter="hoveredRowId = row.line.id" @mouseleave="hoveredRowId = ''">
              <td><ElCheckbox v-model="row.included" :aria-label="'勾选第 ' + (index + 1) + ' 项'" :disabled="locked" /></td><td>{{ index + 1 }}</td>
              <td class="material-cell"><strong>{{ materialTitle(row.line) }}</strong></td>
              <td class="specification-cell"><ElTooltip placement="top" :show-after="80" :visible="hoveredRowId === row.line.id && hoveredSupplierRowId !== row.line.id" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in materialAttributeFields(row.line)" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div></div></template><span>{{ materialSpecificationValue(row.line) }}</span></ElTooltip></td>
              <ElTooltip :content="row.line.supplier_name" placement="top" :show-after="150" :disabled="!row.line.supplier_name" :teleported="true">
                <td class="supplier-cell" @mouseenter="hoveredSupplierRowId = row.line.id" @mouseleave="hoveredSupplierRowId = ''">{{ row.line.supplier_name || '—' }}</td>
              </ElTooltip>
              <td class="purchase-quantity-cell" :title="purchaseQuantityText(row.line)">{{ purchaseQuantityText(row.line) }}</td><td class="muted">{{ formatQuantity(Number(row.line.purchased_quantity) - Number(row.line.remaining_quantity)) }}</td>
              <td><ElInput v-model="row.receivedQuantity" :aria-label="'第 ' + (index + 1) + (row.line.raw_bar_length_m ? ' 项到货根数' : ' 项到货数量')" :inputmode="row.line.raw_bar_length_m ? 'numeric' : 'decimal'" :maxlength="row.line.raw_bar_length_m ? 14 : 19" :disabled="locked" :class="{ 'invalid-field': !validQuantity(row) }" :aria-invalid="!validQuantity(row)" :title="'大于 0，不超过剩余 ' + (row.line.raw_bar_length_m ? `${row.line.remaining_bar_count ?? 0} 根` : `${row.line.remaining_quantity}，最多 4 位小数`)"><template v-if="row.line.raw_bar_length_m" #append>根</template></ElInput></td>
              <td><ElSelect v-model="row.warehouseId" :aria-label="'第 ' + (index + 1) + ' 项材料仓'" placeholder="选择材料仓" :disabled="locked" @change="rowWarehouseChanged(row)"><ElOption v-for="item in options.warehouses" :key="item.id" :label="item.warehouse_number + ' · ' + item.warehouse_name" :value="item.id" /></ElSelect></td>
              <td><ElSelect v-model="row.zoneId" :aria-label="'第 ' + (index + 1) + ' 项库区'" placeholder="选择库区" :disabled="locked || !row.warehouseId"><ElOption v-for="item in warehouseZones(row.warehouseId)" :key="item.id" :label="item.zone_name" :value="item.id" /></ElSelect></td>
              <td class="remark-cell"><ElInput v-model="row.remark" :aria-label="'第 ' + (index + 1) + ' 项差异说明'" :maxlength="3000" :disabled="locked" /></td>
              <td><ElTag :type="hasZone(row) && validQuantity(row) ? 'success' : 'warning'" round>{{ hasZone(row) && validQuantity(row) ? '已完善' : '待完善' }}</ElTag></td>
            </tr><tr v-if="!rows.length"><td colspan="12" class="table-empty">{{ loadError || (selectedOrder ? '该采购单暂无待收货明细。' : '请先选择采购单') }}</td></tr></tbody>
          </table>
        </div>
        <footer><span>已勾选 {{ selectedRows.length }} 项 · 到货数量按采购剩余数量带入</span><strong :class="{ complete: zoneReadyCount === selectedRows.length && selectedRows.length > 0 }">{{ selectedRows.length > 100 ? '每批最多提交 100 项' : '库区完成 ' + zoneReadyCount + '/' + selectedRows.length }}</strong></footer>
      </section>
      <div class="receiving-notice"><ElIcon><WarningFilled /></ElIcon><span>提交后进入“待质检”，此时不增加可用库存；品质确认后按实收数量减退货数量入库。</span></div>
      <section class="submit-bar">
        <label for="receiving-batch-remark">本批次备注（可选）</label><ElInput id="receiving-batch-remark" v-model="form.remark" placeholder="请输入备注信息…" :maxlength="3000" :disabled="locked" />
        <ElButton :disabled="locked || !rows.length" @click="saveDraft">保存草稿</ElButton>
        <ElButton type="primary" :loading="submitting" :disabled="!readyToSubmit" @click="submitReceiving">提交品质确认</ElButton>
      </section>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;
.inventory-workflow { box-sizing: border-box; height: auto; min-height: 0; overflow: visible; padding: 28px 28px 14px; background: transparent; color: token.$crm-text-primary; font: 13px/20px token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-text-color-primary: #{token.$crm-text-primary}; --el-text-color-regular: #{token.$crm-text-secondary}; --el-text-color-placeholder: #{token.$crm-text-muted}; --el-border-color: #{token.$crm-border-default}; --el-border-color-light: #{token.$crm-border-subtle}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-fill-color-light: #{token.$crm-color-subtle}; --el-border-radius-base: 5px;
}
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: var(--erp-color-text-secondary); min-width: 42px; }
.page-title-row, .head-actions, .table-head, .bulk-row, .date-field, .bulk-controls, .submit-bar { display: flex; align-items: center; }
h1, h2, p { margin: 0; } h2 { font-size: 16px; line-height: 22px; font-weight: 700; }
.page-title-row { height: 54px; justify-content: space-between; margin-bottom: 10px; }
h1 { font: 700 34px/44px token.$crm-font-display; letter-spacing: -1px; }
.page-title-row p { color: token.$crm-text-secondary; line-height: 18px; }
.surface { @include detail.surface; }
.head-actions { gap: 10px; } .head-actions > .el-button { height: 32px; margin: 0; }
.load-error { box-sizing: border-box; min-height: 40px; padding: 9px 16px; margin-bottom: 12px; border: 1px solid token.$crm-danger; border-radius: 5px; background: token.$crm-danger-soft; color: token.$crm-danger; }
.bulk-card { box-sizing: border-box; height: 60px; padding: 13px 21px; margin-bottom: 14px; }
.bulk-row { height: 32px; gap: 20px; }
.date-field { gap: 10px; } .date-field label { white-space: nowrap; color: token.$crm-text-secondary; }
.date-field :deep(.el-date-editor) { width: 190px; height: 32px; }
.bulk-controls { gap: 10px; height: 32px; }
.bulk-controls > .el-select:first-child { width: 180px; }
.bulk-controls > .el-select:nth-child(2) { width: 150px; }
.bulk-controls > .el-button { width: 140px; }
.table-card { box-sizing: border-box; height: calc(100dvh - 356px); min-height: 370px; display: flex; flex-direction: column; overflow: hidden; margin-bottom: 16px; }
.table-head { flex: 0 0 51px; justify-content: space-between; padding: 0 21px; border-bottom: 1px solid token.$crm-border-subtle; }
.table-head > div { display: flex; gap: 22px; align-items: center; min-width: 0; }
.table-order-meta { display: flex; align-items: center; gap: 24px; min-width: 0; color: token.$crm-text-secondary; font-size: 12px; }
.table-order-meta span { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.table-order-meta strong { color: token.$crm-text-primary; font-weight: 500; }
.table-head > strong { margin-right: 16px; font-size: 13px; white-space: nowrap; }
.receiving-table-scroll { flex: 1; min-height: 0; overflow: auto; }
.receiving-table { width: 100%; min-width: 1684px; border-collapse: separate; border-spacing: 0; table-layout: fixed; }
.receiving-table th, .receiving-table td { box-sizing: border-box; padding: 4px 8px; border-right: 1px solid var(--erp-table-grid); border-bottom: 1px solid var(--erp-table-grid); text-align: center; overflow-wrap: anywhere; }
.receiving-table th { height: 44px; position: sticky; top: 0; z-index: 2; background: var(--erp-table-header-fill); font-size: 12px; font-weight: 500; color: var(--erp-table-header-text); }
.receiving-table td { height: 58px; } .receiving-table th:last-child, .receiving-table td:last-child { border-right: 0; }
.receiving-table .purchase-quantity-cell { white-space: nowrap; overflow: hidden; overflow-wrap: normal; text-overflow: ellipsis; }
.receiving-table th:first-child, .receiving-table td:first-child { padding: 0; vertical-align: middle; }
.receiving-table th:first-child :deep(.el-checkbox), .receiving-table td:first-child :deep(.el-checkbox) { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; margin: 0; }
.receiving-table .material-cell { text-align: left; padding: 4px 18px; } .material-cell strong, .material-cell small { display: block; font-weight: 400; } .material-cell small { font-size: 13px; color: token.$crm-text-secondary; }
.receiving-table .specification-cell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.receiving-table .specification-cell > span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.receiving-table .supplier-cell { font-size: 13px; color: var(--erp-table-text); white-space: nowrap; overflow: hidden; overflow-wrap: normal; text-overflow: ellipsis; } .muted { color: token.$crm-text-secondary; } .receiving-table .remark-cell { padding: 4px 16px; }
.table-empty { height: 230px !important; color: token.$crm-text-secondary; }
.table-card footer { box-sizing: border-box; flex: 0 0 44px; display: flex; align-items: center; justify-content: space-between; padding: 0 21px; color: token.$crm-text-secondary; border-top: 1px solid token.$crm-border-subtle; }
.table-card footer strong { font-weight: 400; color: token.$crm-warning; } .table-card footer .complete { color: token.$crm-success; }
.receiving-notice { box-sizing: border-box; display: flex; align-items: center; gap: 14px; height: 40px; padding: 0 20px; margin-bottom: 10px; border: 1px solid token.$crm-border-default; border-radius: 5px; background: token.$crm-warning-soft; color: token.$crm-warning; }
.receiving-notice .el-icon { font-size: 18px; flex-shrink: 0; }
.submit-bar { height: 32px; gap: 20px; } .submit-bar label { flex: 0 0 144px; white-space: nowrap; } .submit-bar > .el-input { flex: 1; min-width: 0; }
.submit-bar > .el-button { width: 140px; height: 32px; margin: 0; } .submit-bar > .el-button--primary { width: 160px; }
.inventory-workflow :deep(.el-button) { height: 32px; font-size: 13px; border-radius: 5px; font-family: inherit; }
.inventory-workflow :deep(.el-input__wrapper), .inventory-workflow :deep(.el-select__wrapper) { box-sizing: border-box; height: 32px; min-height: 32px; border-radius: var(--erp-radius-control); font-size: 13px; background: var(--erp-input-surface); color: token.$crm-text-secondary; box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset; }
.inventory-workflow :deep(.el-input__wrapper.is-focus), .inventory-workflow :deep(.el-select__wrapper.is-focused) { box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }
.inventory-workflow :deep(.el-input__inner) { color: token.$crm-text-secondary; font-family: inherit; height: 30px; }
.inventory-workflow :deep(.el-select__selected-item) { color: token.$crm-text-secondary; }
.submit-bar :deep(.el-input__wrapper) { min-height: 32px; }
.inventory-workflow :deep(.el-tag) { height: 24px; min-width: 64px; padding: 0 10px; border: 0; font-size: 11px; font-family: inherit; }
.inventory-workflow :deep(.el-tag--success) { background: var(--erp-tag-success-background); color: var(--erp-color-text-inverse); }
.inventory-workflow :deep(.el-tag--warning) { background: var(--erp-tag-warning-background); color: var(--erp-color-text-inverse); }
.inventory-workflow :deep(.el-checkbox__inner) { width: 14px; height: 14px; border-radius: 2px; }
.inventory-workflow :deep(.invalid-field .el-input__wrapper) { box-shadow: 0 0 0 1px token.$crm-danger inset; }
.empty-state { padding: 80px; text-align: center; color: token.$crm-text-secondary; }
</style>
