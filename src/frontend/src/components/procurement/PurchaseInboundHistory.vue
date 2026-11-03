<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { isCancel } from 'axios'
import { ArrowRight, Refresh } from '@element-plus/icons-vue'
import { fetchPurchaseOrderReadDetail } from '@/api/purchaseOrderReadDetail'
import { useAuthStore } from '@/stores/auth'
import type { PurchaseReadInbound, PurchaseReadInboundLine } from '@/types/purchaseOrderReadDetail'
import { materialAttributeFields, materialSpecificationValue } from '@/utils/materialAttributes'
import { formatTime, purchaseQuantityText } from '@/views/procurement/purchaseOrderDetailDisplay'

const props = defineProps<{ purchaseOrderId: string; refreshKey?: number; inbounds?: PurchaseReadInbound[]; colors?: Record<string, string>; embedded?: boolean }>()
const accordionName = useId()
const auth = useAuthStore()
const records = ref<PurchaseReadInbound[]>([])
const loadedColors = ref<Record<string, string>>({})
const loading = ref(false)
const errorMessage = ref('')
const hoveredRowId = ref('')
const canRead = computed(() => auth.identityReady && (auth.user?.is_superuser === true
  || ['procurement.view_purchaseorder', 'inventory.receive_material', 'inventory.quality_confirm_material'].some(permission => auth.hasPermission(permission))))
let requestVersion = 0
let disposed = false

function quantity(line: PurchaseReadInboundLine, kind: 'received' | 'accepted' | 'return') {
  return purchaseQuantityText(line[`${kind}_quantity`], line.source_unit_text_snapshot, line.raw_bar_length_m, line[`${kind}_bar_count`])
}
function attributes(line: PurchaseReadInboundLine) {
  const fields = materialAttributeFields(line)
  const color = (props.colors ?? loadedColors.value)[line.purchase_order_line_id]
  if (color && !fields.some(field => field.key === 'color')) fields.push({ key: 'color', label: '颜色', value: color })
  return fields
}
function sortRecords(inbounds: PurchaseReadInbound[]) { return [...inbounds].sort((a, b) => b.created_at.localeCompare(a.created_at)) }
async function load() {
  const version = ++requestVersion
  records.value = []
  hoveredRowId.value = ''
  loadedColors.value = {}
  errorMessage.value = ''
  loading.value = false
  if (!canRead.value || !props.purchaseOrderId) return
  if (props.inbounds !== undefined) { records.value = sortRecords(props.inbounds); return }
  loading.value = true
  try {
    const result = await fetchPurchaseOrderReadDetail(props.purchaseOrderId)
    if (disposed || version !== requestVersion) return
    records.value = sortRecords(result.inbounds)
    loadedColors.value = Object.fromEntries(result.lines.map(line => [line.id, line.color]))
  } catch (error) {
    if (disposed || version !== requestVersion || isCancel(error)) return
    const response = (error as { response?: { status?: number; data?: { error?: { message?: string } } } }).response
    errorMessage.value = response?.status === 403 ? '当前账号无权查看该采购单的入库记录。'
      : response?.status === 404 ? '采购单不存在或不在可查看范围内。'
        : response?.data?.error?.message || '入库记录加载失败，请重试。'
  } finally {
    if (!disposed && version === requestVersion) loading.value = false
  }
}
watch([() => props.purchaseOrderId, () => props.refreshKey, () => props.inbounds, () => auth.user?.id,
  () => auth.identityGeneration, () => auth.identityRequestGeneration, canRead], () => { void load() }, { immediate: true })
onBeforeUnmount(() => { disposed = true; requestVersion++ })
</script>

<template>
  <section class="inbound-history" :class="{ 'inbound-history--embedded': embedded }" aria-label="入库记录" :aria-busy="loading">
    <header v-if="!embedded" class="history-heading">
      <div><h2>入库批次记录</h2><span v-if="!loading && !errorMessage && canRead">共 {{ records.length }} 批</span></div>
      <ElButton :icon="Refresh" :loading="loading" :disabled="!canRead" @click="load">刷新记录</ElButton>
    </header>
    <div v-if="!canRead" class="history-state" role="status">当前账号无权查看入库记录。</div>
    <div v-else-if="errorMessage" class="history-state history-error" role="alert">{{ errorMessage }}<ElButton link @click="load">重新加载</ElButton></div>
    <div v-else-if="loading" class="history-state" role="status">正在加载入库记录…</div>
    <div v-else-if="!records.length" class="history-state">暂无入库记录，提交收货后将在这里按次显示。</div>
    <div v-else class="history-records">
      <details v-for="(record, index) in records" :key="record.id" :name="accordionName" class="history-record" @toggle="hoveredRowId = ''">
        <summary :aria-label="`查看入库记录 ${record.inbound_number}`">
          <ElIcon class="expand-icon"><ArrowRight /></ElIcon>
          <span class="summary-main" tabindex="0" aria-label="批次信息，可横向滚动">
          <strong class="batch-label">第 {{ records.length - index }} 批</strong>
          <strong>{{ record.inbound_number }}</strong>
          <span class="summary-text">到货日期 {{ formatTime(record.inbound_date, true) }}</span>
          <span class="summary-text">{{ record.lines.length }} 项材料</span>
          <span class="summary-text">收货人 {{ record.received_by_name || '—' }}</span>
          <ElTag :type="record.status === 'CONFIRMED' ? 'success' : 'warning'">{{ record.status_display }}</ElTag>
          <span class="record-metadata">
            <span><span>登记时间</span><time>{{ formatTime(record.created_at) }}</time></span>
            <span><span>品质确认人</span><span>{{ record.quality_confirmed_by_name || '—' }}</span></span>
            <span><span>品质确认时间</span><time>{{ formatTime(record.quality_confirmed_at) }}</time></span>
          </span>
          </span>
          <span class="expand-label"><span class="expand-text">展开明细</span><span class="collapse-text">收起明细</span></span>
        </summary>
        <div class="record-body">
          <div class="record-table-scroll" tabindex="0" :aria-label="`${record.inbound_number}材料明细`">
            <table class="record-table">
              <colgroup><col style="width: 220px" /><col style="width: 180px" /><col style="width: 180px" /><col v-for="kind in ['received', 'accepted', 'returned']" :key="kind" style="width: 120px" /><col style="width: 180px" /><col style="width: 200px" /></colgroup>
              <thead><tr><th>物料名称</th><th>规格</th><th>供应商</th><th class="numeric">到货数量</th><th class="numeric">合格入库</th><th class="numeric">退货数量</th><th>仓库位置</th><th>品质说明</th></tr></thead>
              <tbody>
                <tr v-for="line in record.lines" :key="line.id" @mouseenter="hoveredRowId = line.id" @mouseleave="hoveredRowId = ''">
                  <td class="material-name" :title="line.part_name_snapshot">{{ line.part_name_snapshot || '—' }}</td>
                  <td class="specification-cell"><ElTooltip placement="top" :show-after="80" :visible="hoveredRowId === line.id" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in attributes(line)" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div></div></template><span tabindex="0" @focus="hoveredRowId = line.id" @blur="hoveredRowId = ''">{{ materialSpecificationValue(line) }}</span></ElTooltip></td>
                  <td :title="line.supplier_name_snapshot">{{ line.supplier_name_snapshot || '—' }}</td>
                  <td class="numeric">{{ quantity(line, 'received') }}</td>
                  <td class="numeric">{{ record.status === 'CONFIRMED' ? quantity(line, 'accepted') : '待质检' }}</td>
                  <td class="numeric">{{ record.status === 'CONFIRMED' ? quantity(line, 'return') : '—' }}</td>
                  <td :title="[line.warehouse_name, line.zone_name, line.location_number].filter(Boolean).join(' / ')">{{ [line.warehouse_name, line.zone_name, line.location_number].filter(Boolean).join(' / ') || '—' }}</td>
                  <td :title="line.quality_remark">{{ line.quality_remark || '—' }}</td>
                </tr>
                <tr v-if="!record.lines.length"><td colspan="8" class="history-state">暂无材料明细</td></tr>
              </tbody>
            </table>
          </div>
          <p v-if="record.remark" class="record-remark"><span>本次备注</span>{{ record.remark }}</p>
        </div>
      </details>
    </div>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;
.inbound-history { @include detail.surface; margin-top: 20px; overflow: hidden; color: var(--erp-color-text-primary); }
.inbound-history--embedded { margin-top: 0; border: 0; border-radius: 0; background: transparent; box-shadow: none; backdrop-filter: none; }
.batch-label { color: var(--el-color-primary); }
.history-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 20px; border-bottom: 1px solid var(--erp-table-grid); }
.history-heading > div { display: flex; align-items: center; gap: 14px; }
.history-heading h2 { margin: 0; font-size: 16px; font-weight: 700; }
.history-heading span, .history-state { color: var(--erp-color-text-secondary); font-size: 13px; }
.history-state { padding: 28px 20px; text-align: center; }
.history-error { color: var(--el-color-danger); }
.history-records { display: grid; gap: 0; padding: 0; }
.history-record { @include detail.inset; min-width: 0; overflow: hidden; border-radius: 0; }
.history-record + .history-record { border-top: 0; }
.history-record:first-child { border-top-left-radius: var(--erp-radius-control); border-top-right-radius: var(--erp-radius-control); }
.history-record:last-child { border-bottom-left-radius: var(--erp-radius-control); border-bottom-right-radius: var(--erp-radius-control); }
.history-record summary { display: flex; align-items: center; gap: 20px; padding: 14px 16px; cursor: pointer; list-style: none; font-size: 13px; }
.summary-main { display: flex; flex: 1; min-width: 0; align-items: center; gap: 20px; overflow-x: auto; white-space: nowrap; scrollbar-width: thin; }
.summary-main > * { flex-shrink: 0; }
.history-record[open] summary { border-bottom: 1px solid var(--erp-table-grid); }
.history-record summary::-webkit-details-marker { display: none; }
.history-record summary:hover { background: var(--erp-table-hover); }
.history-record summary:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: -2px; }
.summary-text, .expand-label { color: var(--erp-color-text-secondary); }
.summary-main > strong { font-weight: 600; }
.summary-main :deep(.el-tag) { color: var(--erp-color-text-inverse); }
.summary-main :deep(.el-tag__content) { color: inherit; }
.expand-icon { flex-shrink: 0; transition: transform .15s; }
.history-record[open] .expand-icon { transform: rotate(90deg); }
.expand-label { flex-shrink: 0; white-space: nowrap; }
.collapse-text, .history-record[open] .expand-text { display: none; }
.history-record[open] .collapse-text { display: inline; }
.record-body { padding: 0; }
.record-metadata { display: flex; gap: 20px; font-size: 12px; }
.record-metadata > span { display: flex; gap: 8px; }
.record-metadata > span > span:first-child, .record-remark > span { color: var(--erp-color-text-secondary); }
.record-table-scroll { max-width: 100%; overflow-x: auto; background: var(--erp-table-body-fill); }
.record-table { width: 100%; min-width: 1320px; border-collapse: separate; border-spacing: 0; table-layout: fixed; }
.record-table th, .record-table td { box-sizing: border-box; padding: 0 16px; border-right: 1px solid var(--erp-table-grid); border-bottom: 1px solid var(--erp-table-grid); text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.record-table th:last-child, .record-table td:last-child { border-right: 0; }
.record-table tbody tr:last-child td { border-bottom: 0; }
.record-table thead tr, .record-table th { height: 44px; }
.record-table th { font-size: 11px; line-height: 16px; font-weight: 500; background: var(--erp-table-header-fill); color: var(--erp-table-header-text); }
.record-table tbody tr, .record-table td { height: 40px; }
.record-table td { font-size: 12px; line-height: 18px; color: var(--erp-table-text); }
.record-table td.material-name { font-size: 13px; line-height: 20px; font-weight: 500; }
.record-table tbody tr:hover { background: var(--erp-color-hover); }
.record-table .numeric { text-align: right; white-space: nowrap; }
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: var(--erp-color-text-secondary); min-width: 42px; }
.record-remark { display: flex; gap: 12px; margin: 0; padding: 12px 16px; border-top: 1px solid var(--erp-table-grid); font-size: 13px; white-space: pre-wrap; overflow-wrap: anywhere; }
.record-remark > span { flex-shrink: 0; }
</style>
