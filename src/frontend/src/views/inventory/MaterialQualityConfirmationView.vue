<script setup lang="ts">
import { pipeMeters } from '@/utils/pipeQuantities'
import { computed, onMounted, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Calendar, Refresh, WarningFilled } from '@element-plus/icons-vue'
import { confirmMaterialQuality, fetchMaterialQualityBatch, fetchMaterialQualityBatches } from '@/api/inventory'
import { router } from '@/router'
import { useAuthStore } from '@/stores/auth'
import type { MaterialInbound, MaterialInboundLine } from '@/types/inventory'
import { materialAttributeFields, materialSpecificationValue } from '@/utils/materialAttributes'

interface QualityRow { line: MaterialInboundLine; included: boolean; returnQuantity: string; qualityRemark: string }
const auth = useAuthStore()
const canConfirm = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.quality_confirm_material'))
const canViewInventory = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.view_materialinbound'))
const batches = ref<MaterialInbound[]>([])
const selectedBatchId = ref('')
const batch = ref<MaterialInbound | null>(null)
const rows = ref<QualityRow[]>([])
const hoveredRowId = ref('')
const loading = ref(false)
const confirming = ref(false)
const confirmed = ref(false)
const loadError = ref('')
const bulk = reactive({ returnQuantity: '0', remark: '' })
let requestVersion = 0
let disposed = false
let dialogOpen = false
const qualityDate = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())
const locked = computed(() => loading.value || confirming.value || confirmed.value || !canConfirm.value)
const selectedRows = computed(() => rows.value.filter(row => row.included))
const allSelected = computed({
  get: () => rows.value.length > 0 && selectedRows.value.length === rows.value.length,
  set: (value: boolean) => { if (!locked.value) rows.value.forEach(row => { row.included = value }) },
})
// 用整数单位表示万分之一，保持接口支持的 4 位小数精度。
function scaled(value: string): bigint | null {
  if (!/^\d{1,14}(\.\d{1,4})?$/.test(value)) return null
  const [whole = '0', fraction = ''] = value.split('.')
  return BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
}
function receivedInput(row: QualityRow): string { return row.line.measurement_kind === 'PIPE' ? String(row.line.received_bar_count ?? '') : row.line.received_quantity }
function validRow(row: QualityRow): boolean {
  if (row.line.measurement_kind === 'PIPE' && !/^\d{1,14}$/.test(row.returnQuantity)) return false
  const returned = scaled(row.returnQuantity), received = scaled(receivedInput(row))
  return returned !== null && received !== null && received > 0n && returned <= received && row.qualityRemark.length <= 3000
}
const completeCount = computed(() => rows.value.filter(validRow).length)
const returnCount = computed(() => rows.value.filter(row => validRow(row) && scaled(row.returnQuantity)! > 0n).length)
const allComplete = computed(() => rows.value.length > 0 && rows.value.length <= 100 && completeCount.value === rows.value.length)
const canSubmit = computed(() => !locked.value && !loadError.value && batch.value?.status === 'PENDING_QUALITY' && allComplete.value)
function formatScaled(value: bigint): string {
  const whole = (value / 10000n).toLocaleString('zh-CN')
  const fraction = (value % 10000n).toString().padStart(4, '0').replace(/0+$/, '')
  return whole + (fraction ? '.' + fraction : '')
}
function formatQuantity(value: string): string { const number = scaled(value); return number === null ? '—' : formatScaled(number) }
function accepted(row: QualityRow): string { return validRow(row) ? formatScaled(scaled(receivedInput(row))! - scaled(row.returnQuantity)!) : '—' }
function receivedQuantityText(line: MaterialInboundLine): string {
  return `${line.measurement_kind === 'PIPE' ? `${line.received_bar_count ?? '—'} 根 / ` : ''}${formatQuantity(line.received_quantity)} ${line.source_unit_text_snapshot}`
}
function acceptedQuantityText(row: QualityRow): string {
  const quantity = accepted(row)
  if (row.line.measurement_kind !== 'PIPE') return quantity
  const meters = validRow(row) ? pipeMeters(String(Number(row.line.received_bar_count) - Number(row.returnQuantity)), row.line.raw_bar_length_m) : ''
  return `${quantity} 根 / ${meters || '—'} 米`
}
function status(row: QualityRow): string {
  if (!validRow(row)) return '待完善'
  if (scaled(row.returnQuantity) === 0n) return '合格'
  return scaled(row.returnQuantity) === scaled(receivedInput(row)) ? '全部退货' : '部分退货'
}
function materialTitle(line: MaterialInboundLine): string { return line.part_name_snapshot || line.material_snapshot || '未命名物料' }
function apiMessage(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { error?: { message?: string }; detail?: string } } })?.response?.data
  return data?.error?.message || data?.detail || fallback
}
function draftKey(id: string) { return `material-quality-draft:v2:${id}` }
function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {} }
function readDraft(id: string): Record<string, unknown> {
  try { return record(JSON.parse(localStorage.getItem(draftKey(id)) || '{}')) } catch { return {} }
}
async function loadBatches() {
  if (confirming.value || confirmed.value) return
  const version = ++requestVersion
  loading.value = true
  loadError.value = ''
  try {
    const data = await fetchMaterialQualityBatches()
    if (disposed || version !== requestVersion) return
    batches.value = data.filter(item => item.status === 'PENDING_QUALITY')
    const id = batches.value.some(item => item.id === selectedBatchId.value) ? selectedBatchId.value : batches.value[0]?.id || ''
    const preserve = id === batch.value?.id
    selectedBatchId.value = id
    // 列表已经返回完整批次，直接使用本次响应，省去首个批次的重复读取。
    await selectBatch(preserve, batches.value.find(item => item.id === id))
  } catch (error) {
    if (!disposed && version === requestVersion) { loadError.value = apiMessage(error, '待质检批次加载失败，请刷新重试。'); loading.value = false }
  }
}
async function selectBatch(preserve = false, loadedBatch?: MaterialInbound) {
  if (confirming.value || confirmed.value) return
  const version = ++requestVersion, id = selectedBatchId.value
  const previous = preserve ? new Map(rows.value.map(row => [row.line.id, row])) : new Map<string, QualityRow>()
  if (!preserve) { batch.value = null; rows.value = [] }
  loadError.value = ''
  loading.value = Boolean(id)
  if (!id) return
  try {
    const data = loadedBatch?.id === id ? loadedBatch : await fetchMaterialQualityBatch(id)
    if (disposed || version !== requestVersion) return
    const draft = readDraft(id)
    batch.value = data
    rows.value = data.lines.map(line => {
      const saved = previous.get(line.id) || record(draft[line.id])
      return { line, included: typeof saved.included === 'boolean' ? saved.included : true,
        returnQuantity: typeof saved.returnQuantity === 'string' || typeof saved.returnQuantity === 'number' ? String(saved.returnQuantity) : line.measurement_kind === 'PIPE' ? String(line.return_bar_count ?? 0) : line.return_quantity || '0.00',
        qualityRemark: typeof saved.qualityRemark === 'string' ? saved.qualityRemark : line.quality_remark || '' }
    })
    if (data.status !== 'PENDING_QUALITY') loadError.value = '此批次已完成品质确认，请刷新选择其他批次。'
  } catch (error) {
    if (!disposed && version === requestVersion) loadError.value = apiMessage(error, '待质检明细加载失败，请刷新重试。')
  } finally { if (!disposed && version === requestVersion) loading.value = false }
}
function applyBulk() {
  if (locked.value || loadError.value) return
  if (!selectedRows.value.length) return ElMessage.warning('请先勾选需要批量设置的明细。')
  const quantity = scaled(bulk.returnQuantity)
  if (quantity === null || selectedRows.value.some(row => row.line.measurement_kind === 'PIPE' && !/^\d{1,14}$/.test(bulk.returnQuantity)) || bulk.remark.length > 3000 || selectedRows.value.some(row => { const received = scaled(receivedInput(row)); return received === null || quantity > received })) return ElMessage.warning('退货数量须为非负数，最多 4 位小数，且不能大于任一勾选明细的到货数量。')
  selectedRows.value.forEach(row => { row.returnQuantity = bulk.returnQuantity; if (bulk.remark) row.qualityRemark = bulk.remark })
}
function saveDraft() {
  if (!batch.value || locked.value) return
  try {
    localStorage.setItem(draftKey(batch.value.id), JSON.stringify(Object.fromEntries(rows.value.map(row => [row.line.id, { returnQuantity: row.returnQuantity, qualityRemark: row.qualityRemark }]))))
    ElMessage.success('质检草稿已保存在当前浏览器。')
  } catch { ElMessage.error('浏览器无法保存草稿，填写内容仍保留在页面中。') }
}
async function confirmInbound() {
  if (!canSubmit.value || !batch.value) return
  const id = batch.value.id
  // 勾选只控制批量设置；接口要求提交整个批次，并冻结确认框打开前的内容。
  const payload = { items: rows.value.map(row => ({ line_id: row.line.id, expected_received_quantity: row.line.received_quantity, ...(row.line.measurement_kind === 'PIPE' ? { return_bar_count: row.returnQuantity } : { return_quantity: row.returnQuantity }), quality_remark: row.qualityRemark })) }
  confirming.value = true
  try {
    dialogOpen = true
    try {
      await ElMessageBox.confirm(`确认本批次全部 ${payload.items.length} 项质检结果并入库？合格数量将计入库存，有退货的明细将自动生成退货单。`, '确认并入库', {
        type: 'warning',
        confirmButtonText: '确认并入库',
        cancelButtonText: '取消',
        customClass: 'quality-confirm-dialog',
        confirmButtonClass: 'quality-confirm-dialog__confirm',
        cancelButtonClass: 'quality-confirm-dialog__cancel',
      })
    } catch { return } finally { dialogOpen = false }
    if (disposed || !canConfirm.value) return
    await confirmMaterialQuality(id, payload)
    confirmed.value = true
    try { localStorage.removeItem(draftKey(id)) } catch { ElMessage.warning('入库已成功，但本地草稿未能清除。') }
    if (disposed) return
    ElMessage.success('品质确认完成，合格数量已计入库存，有退货的明细已生成退货单。')
    try { await router.push({ name: canViewInventory.value ? 'material-inventory' : 'purchase-inbounds' }) }
    catch { ElMessage.warning('入库已成功，请从采购入库列表继续。') }
  } catch (error) {
    if (!disposed) {
      ElMessage.error(apiMessage(error, '品质确认失败，填写内容已保留。'))
      if ((error as { response?: { status?: number } })?.response?.status === 409) loadError.value = '批次数据已变化，请刷新后重新核对。'
    }
  } finally { confirming.value = false }
}
onMounted(() => { if (canConfirm.value) void loadBatches() })
onBeforeUnmount(() => { disposed = true; requestVersion++; if (dialogOpen) ElMessageBox.close() })
</script>

<template>
  <section class="inventory-workflow quality-page" data-testid="material-quality-confirmation-page">
    <div v-if="!canConfirm" class="empty-state"><h1>无权进行品质确认</h1><p>请联系管理员开通材料品质确认权限。</p></div>
    <template v-else>
      <header class="page-title-row"><div><h1>品质确认</h1><p>核对仓库到货，填写退货数量并确认合格入库数量。</p></div><ElButton :icon="Refresh" :disabled="locked" @click="loadBatches">刷新</ElButton></header>
      <div v-if="loadError" class="load-error" role="alert">{{ loadError }}</div>
      <section class="surface bulk-card">
        <div class="bulk-row"><h2>本次质检设置</h2><div class="date-field"><label>质检日期</label><ElInput :model-value="qualityDate" :prefix-icon="Calendar" disabled aria-label="质检日期" /></div><div class="bulk-controls"><label for="bulk-return">退货数量</label><ElInput id="bulk-return" v-model="bulk.returnQuantity" :disabled="locked" maxlength="19" inputmode="decimal" aria-label="批量退货数量" /><ElInput v-model="bulk.remark" :disabled="locked" maxlength="3000" placeholder="批量质检说明（可选）" aria-label="批量质检说明" /><ElButton :disabled="locked || !!loadError" @click="applyBulk">应用到已勾选</ElButton></div></div>
      </section>
      <section class="surface table-card">
        <div class="table-head"><div><h2>品质确认明细</h2><div class="table-order-meta"><template v-if="batch"><span>入库单号 <strong>{{ batch.inbound_number }}</strong></span><span>采购单号 <strong>{{ batch.purchase_order_number || '—' }}</strong></span><span>生产单号 <strong>{{ batch.lines[0]?.production_task_number_snapshot || '—' }}</strong></span><span>状态 <ElTag type="warning" round>待质检</ElTag></span></template><span class="batch-selector"><label>批次</label><ElSelect v-model="selectedBatchId" aria-label="选择待质检批次" filterable :disabled="locked" :loading="loading" placeholder="入库单号 / 采购单号 / 供应商" @change="selectBatch()"><ElOption v-for="item in batches" :key="item.id" :value="item.id" :label="`${item.inbound_number} · ${item.purchase_order_number || '—'} · ${item.lines[0]?.supplier_name_snapshot || '—'}`" /></ElSelect></span></div></div><strong>共 {{ rows.length }} 项</strong></div>
        <div v-loading="loading" class="quality-table-scroll">
          <table class="quality-table"><colgroup><col v-for="(width, index) in [56,56,232,190,200,160,144,170,150,126,220,120]" :key="index" :style="{ width: width / 1824 * 100 + '%' }" /></colgroup>
            <thead><tr><th><ElCheckbox v-model="allSelected" aria-label="全选明细" :disabled="locked" :indeterminate="selectedRows.length > 0 && !allSelected" /></th><th>序号</th><th>物料信息</th><th>规格</th><th>供应商</th><th>到货数量</th><th>退货数量</th><th>合格入库数量</th><th>材料仓</th><th>库区</th><th>退货/质检说明</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="(row, index) in rows" :key="row.line.id" @mouseenter="hoveredRowId = row.line.id" @mouseleave="hoveredRowId = ''">
                <td><ElCheckbox v-model="row.included" :aria-label="`勾选第 ${index + 1} 项`" :disabled="locked" /></td><td class="muted">{{ index + 1 }}</td>
                <td class="material-cell"><strong>{{ materialTitle(row.line) }}</strong></td>
                <td class="specification-cell"><ElTooltip placement="top" :show-after="80" :visible="hoveredRowId === row.line.id" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in materialAttributeFields(row.line)" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div></div></template><span>{{ materialSpecificationValue(row.line) }}</span></ElTooltip></td>
                <td class="supplier-cell">{{ row.line.supplier_name_snapshot || '—' }}</td>
                <td class="quantity-cell" :title="receivedQuantityText(row.line)">{{ receivedQuantityText(row.line) }}</td>
                <td><ElInput v-model="row.returnQuantity" :aria-label="`第 ${index + 1} 项退货${row.line.measurement_kind === 'PIPE' ? '根数' : '数量'}`" :aria-invalid="!validRow(row)" :class="{ 'invalid-field': !validRow(row) }" :disabled="locked" :maxlength="row.line.measurement_kind === 'PIPE' ? 14 : 19" :inputmode="row.line.measurement_kind === 'PIPE' ? 'numeric' : 'decimal'"><template v-if="row.line.measurement_kind === 'PIPE'" #append>根</template></ElInput></td>
                <td class="quantity-cell success-text" :title="acceptedQuantityText(row)"><b>{{ acceptedQuantityText(row) }}</b></td>
                <td class="muted">{{ row.line.warehouse_number }} · {{ row.line.warehouse_name }}</td><td class="muted">{{ row.line.zone_name }}</td>
                <td class="remark-cell"><ElInput v-model="row.qualityRemark" :aria-label="`第 ${index + 1} 项质检说明`" :disabled="locked" maxlength="3000" placeholder="质检说明（可选）" /></td>
                <td><ElTag :type="!validRow(row) ? 'warning' : status(row) === '合格' ? 'success' : 'danger'" round>{{ status(row) }}</ElTag></td>
              </tr>
              <tr v-if="!rows.length"><td colspan="12" class="table-empty">{{ loadError || (loading ? '正在加载…' : '暂无待质检明细') }}</td></tr>
            </tbody>
          </table>
        </div>
        <footer><span>已勾选 {{ selectedRows.length }} 项 · {{ returnCount }} 项有退货</span><strong :class="{ complete: allComplete }">{{ allComplete ? `全部 ${rows.length} 项填写完整` : `已完成 ${completeCount} / ${rows.length} 项，请检查退货数量` }}</strong></footer>
      </section>
      <footer class="submit-bar"><div class="submit-notice"><ElIcon><WarningFilled /></ElIcon><span>确认后合格数量计入库存；有退货的明细自动生成退货单，在采购管理 → 退货明细中处理。</span></div><ElButton :disabled="locked || !batch" @click="saveDraft">保存质检草稿</ElButton><ElButton type="primary" :loading="confirming" :disabled="!canSubmit" @click="confirmInbound">确认并入库</ElButton></footer>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.inventory-workflow { box-sizing: border-box; height: calc(100dvh - 92px); min-height: 0; overflow-y: auto; padding: 28px 28px 16px; background: token.$crm-color-page; color: token.$crm-text-primary; font: 13px/20px token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-text-color-primary: #{token.$crm-text-primary}; --el-text-color-regular: #{token.$crm-text-secondary}; --el-text-color-placeholder: #{token.$crm-text-muted}; --el-border-color: #{token.$crm-border-default}; --el-border-color-light: #{token.$crm-border-subtle}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-fill-color-light: #{token.$crm-color-subtle}; --el-border-radius-base: 5px;
}
.page-title-row, .table-head, .bulk-row, .date-field, .bulk-controls, .submit-bar { display: flex; align-items: center; }
h1, h2, p { margin: 0; } h2 { font-size: 16px; line-height: 22px; font-weight: 700; white-space: nowrap; }
.page-title-row { height: 54px; justify-content: space-between; margin-bottom: 10px; }
h1 { font: 700 34px/44px token.$crm-font-display; letter-spacing: -1px; }
.page-title-row p { color: token.$crm-text-secondary; line-height: 18px; }
.page-title-row > .el-button { width: 104px; height: 32px; }
.surface { border: 1px solid token.$crm-border-default; border-radius: 5px; background: token.$crm-color-surface; }
.load-error { box-sizing: border-box; min-height: 40px; padding: 9px 16px; margin-bottom: 12px; border: 1px solid token.$crm-danger; border-radius: 5px; background: token.$crm-danger-soft; color: token.$crm-danger; }
.bulk-card { box-sizing: border-box; height: 60px; padding: 13px 21px; margin-bottom: 12px; }
.bulk-row { height: 32px; gap: 20px; }
.date-field { gap: 10px; margin-left: auto; }
.date-field label, .bulk-controls label { color: token.$crm-text-secondary; white-space: nowrap; }
.date-field > .el-input { width: 170px; }
.date-field :deep(.el-input__wrapper) { background: token.$crm-color-subtle; }
.date-field :deep(.el-input__inner) { -webkit-text-fill-color: token.$crm-text-secondary; }
.bulk-controls { height: 32px; gap: 10px; }
.bulk-controls > .el-input:nth-child(2) { width: 120px; }
.bulk-controls > .el-input:nth-child(3) { width: 280px; }
.bulk-controls > .el-button { width: 140px; }
.table-card { box-sizing: border-box; height: calc(100dvh - 306px); min-height: 370px; display: flex; flex-direction: column; overflow: hidden; margin-bottom: 12px; }
.table-head { flex: 0 0 51px; justify-content: space-between; padding: 0 21px; border-bottom: 1px solid token.$crm-border-subtle; }
.table-head > div { display: flex; gap: 22px; align-items: center; min-width: 0; }
.table-order-meta { display: flex; align-items: center; gap: 24px; min-width: 0; color: token.$crm-text-secondary; font-size: 12px; }
.table-order-meta span { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.table-order-meta strong { color: token.$crm-text-primary; font-weight: 500; }
.table-order-meta .batch-selector { gap: 8px; }
.batch-selector > .el-select { width: 320px; }
.table-head > strong { margin-right: 16px; font-size: 13px; white-space: nowrap; }
.quality-table-scroll { flex: 1; min-height: 0; overflow: auto; }
.quality-table { width: 100%; min-width: 1634px; border-collapse: separate; border-spacing: 0; table-layout: fixed; }
.quality-table th, .quality-table td { box-sizing: border-box; padding: 4px 8px; border-right: 1px solid token.$crm-border-subtle; border-bottom: 1px solid token.$crm-border-subtle; text-align: center; overflow-wrap: anywhere; }
.quality-table th { height: 44px; position: sticky; top: 0; z-index: 2; background: token.$crm-color-surface; font-size: 12px; font-weight: 500; color: token.$crm-text-secondary; }
.quality-table td { height: 58px; } .quality-table th:last-child, .quality-table td:last-child { border-right: 0; }
.quality-table .quantity-cell { white-space: nowrap; overflow: hidden; overflow-wrap: normal; text-overflow: ellipsis; }
.quality-table th:first-child, .quality-table td:first-child { padding: 0; vertical-align: middle; }
.quality-table th:first-child :deep(.el-checkbox), .quality-table td:first-child :deep(.el-checkbox) { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; margin: 0; }
.quality-table .material-cell { text-align: left; padding: 4px 18px; } .material-cell strong, .material-cell small { display: block; font-weight: 400; } .material-cell small { font-size: 13px; color: token.$crm-text-secondary; }
.quality-table .specification-cell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.quality-table .specification-cell > span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: #b9c0cc; min-width: 42px; }
.supplier-cell { font-size: 13px; color: token.$crm-text-secondary; } .muted { color: token.$crm-text-secondary; } .quality-table .remark-cell { padding: 4px 13px; }
.quality-table td:nth-child(7) { padding: 4px 11px; }
.success-text { color: token.$crm-success; }
.table-empty { height: 230px !important; color: token.$crm-text-secondary; }
.table-card footer { box-sizing: border-box; flex: 0 0 44px; display: flex; align-items: center; justify-content: space-between; padding: 0 21px; color: token.$crm-text-secondary; border-top: 1px solid token.$crm-border-subtle; }
.table-card footer strong { font-weight: 400; color: token.$crm-warning; } .table-card footer .complete { color: token.$crm-success; }
.submit-bar { height: 32px; gap: 20px; }
.submit-notice { display: flex; flex: 1; min-width: 0; align-items: center; gap: 10px; color: token.$crm-warning; }
.submit-notice .el-icon { flex: 0 0 auto; font-size: 18px; }
.submit-notice span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.submit-bar > .el-button { width: 140px; height: 32px; margin: 0; }
.submit-bar > .el-button--primary { width: 160px; }
.inventory-workflow :deep(.el-button) { height: 32px; font-size: 13px; border-radius: 5px; font-family: inherit; }
.inventory-workflow :deep(.el-input__wrapper), .inventory-workflow :deep(.el-select__wrapper) { box-sizing: border-box; border-radius: 3px; min-height: 32px; font-size: 13px; background: token.$crm-color-surface; color: token.$crm-text-secondary; }
.inventory-workflow :deep(.el-input__inner) { color: token.$crm-text-secondary; font-family: inherit; height: 30px; }
.inventory-workflow :deep(.el-select__selected-item) { color: token.$crm-text-secondary; }
.inventory-workflow :deep(.el-tag) { height: 24px; min-width: 64px; padding: 0 10px; border: 0; font-size: 11px; font-family: inherit; }
.inventory-workflow :deep(.el-tag--success) { background: token.$crm-success-soft; color: token.$crm-success; }
.inventory-workflow :deep(.el-tag--warning) { background: token.$crm-warning-soft; color: token.$crm-warning; }
.inventory-workflow :deep(.el-checkbox__inner) { width: 14px; height: 14px; border-radius: 2px; }
.inventory-workflow :deep(.invalid-field .el-input__wrapper) { box-shadow: 0 0 0 1px token.$crm-danger inset; }
.quality-table :deep(.el-tag) { width: 80px; }
.quality-page :deep(.el-tag--danger) { color: token.$crm-danger; background: token.$crm-danger-soft; }
.empty-state { padding: 80px; text-align: center; color: token.$crm-text-secondary; }
:global(.quality-confirm-dialog .el-message-box__btns) { gap: 12px; }
:global(.quality-confirm-dialog .el-message-box__btns .el-button) { min-width: 80px; height: 32px; margin: 0; border-radius: 5px; font: 500 13px/20px token.$crm-font-body; }
:global(.quality-confirm-dialog .quality-confirm-dialog__confirm) { border-color: token.$crm-primary !important; background: token.$crm-primary !important; color: token.$crm-text-inverse !important; }
:global(.quality-confirm-dialog .quality-confirm-dialog__confirm:hover) { border-color: token.$crm-primary-hover !important; background: token.$crm-primary-hover !important; }

@media (max-width: 1400px) {
  .bulk-row { gap: 12px; }
  .date-field { margin-left: 0; }
  .bulk-controls > .el-input:nth-child(3) { width: 190px; }
  .table-order-meta { gap: 8px; }
  .batch-selector > .el-select { width: 200px; }
}
</style>
