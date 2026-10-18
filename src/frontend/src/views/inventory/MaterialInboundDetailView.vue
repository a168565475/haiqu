<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Calendar, InfoFilled, Refresh, Search } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { fetchMaterialInboundDetails, fetchMaterialFilterOptions } from '@/api/inventory'
import { router } from '@/router'
import { useAuthStore } from '@/stores/auth'
import type { MaterialInbound, MaterialInboundLine, MaterialFilterOptions } from '@/types/inventory'
import { materialAttributeFields, materialSpecificationValue } from '@/utils/materialAttributes'

interface DetailRow { inbound: MaterialInbound; line: MaterialInboundLine }
interface Filters {
  q: string; inboundDate: string; warehouseId: string; zoneId: string; sectionType: string; sectionTitle: string
  category: string; material: string; partName: string; specification: string; rawMaterial: string; unit: string; exactLine: boolean
}
const auth = useAuthStore()
const route = useRoute()
const canView = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.view_material_receipt'))
const queryText = (name: string) => typeof route.query[name] === 'string' ? route.query[name] as string : ''
const blankFilters = (): Filters => ({
  q: '', inboundDate: '', warehouseId: '', zoneId: '', sectionType: '', sectionTitle: '', category: '',
  material: '', partName: '', specification: '', rawMaterial: '', unit: '', exactLine: false,
})
const filters = reactive<Filters>({
  q: queryText('q'),
  inboundDate: '',
  warehouseId: queryText('warehouse_id'),
  zoneId: queryText('zone_id'),
  sectionType: queryText('section_type'),
  sectionTitle: queryText('section_title'),
  category: queryText('category'),
  material: queryText('material'),
  partName: queryText('part_name'),
  specification: queryText('specification'),
  rawMaterial: queryText('raw_material'),
  unit: queryText('unit'),
  exactLine: queryText('exact_line') === '1',
})
const appliedFilters = ref(blankFilters())
const loading = ref(false)
const optionsLoading = ref(false)
const rowsError = ref('')
const optionsError = ref('')
const batches = ref<MaterialInbound[]>([])
const options = ref<MaterialFilterOptions>({ warehouses: [], zones: [], sections: [] })
const hoveredRowId = ref('')
let rowsVersion = 0
let optionsVersion = 0
let disposed = false
const today = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' }).format(new Date())

const rows = computed<DetailRow[]>(() => {
  const selected = appliedFilters.value
  const keyword = selected.q.toLowerCase()
  // 接口按批次返回明细，仍需逐行筛选，避免同批次其他仓库/分区混入结果。
  return batches.value.flatMap(inbound => inbound.lines.map(line => ({ inbound, line }))).filter(({ inbound, line }) => {
    const searchable = [inbound.inbound_number, inbound.purchase_order_number, line.purchase_order_number_snapshot, line.part_name_snapshot, line.material_snapshot, line.raw_material_snapshot, line.supplier_name_snapshot].filter(Boolean).join(' ').toLowerCase()
    return (!keyword || searchable.includes(keyword))
      && (!selected.inboundDate || inbound.inbound_date === selected.inboundDate)
      && (!selected.warehouseId || line.warehouse_id === selected.warehouseId)
      && (!selected.zoneId || line.zone_id === selected.zoneId)
      && (!selected.exactLine || line.section_type_snapshot === selected.sectionType)
      && (selected.exactLine ? line.section_title_snapshot === selected.sectionTitle : (!selected.sectionTitle || line.section_title_snapshot === selected.sectionTitle))
      && (!selected.exactLine || line.category_snapshot === selected.category)
      && (!selected.exactLine || line.material_snapshot === selected.material)
      && (!selected.exactLine || line.part_name_snapshot === selected.partName)
      && (!selected.exactLine || line.specification_snapshot === selected.specification)
      && (!selected.exactLine || line.raw_material_snapshot === selected.rawMaterial)
      && (!selected.exactLine || line.source_unit_text_snapshot === selected.unit)
  })
})
const summary = computed(() => {
  const currentBatches = new Map(rows.value.map(row => [row.inbound.id, row.inbound]))
  const purchaseOrders = new Set(rows.value.map(({ inbound, line }) => inbound.purchase_order_id || inbound.purchase_order_number || line.purchase_order_number_snapshot).filter(Boolean))
  return { batches: currentBatches.size, details: rows.value.length, purchaseOrders: purchaseOrders.size,
    today: [...currentBatches.values()].filter(inbound => inbound.inbound_date === today()).length }
})
function apiMessage(error: unknown, fallback: string): string {
  const data = (error as { response?: { data?: { error?: { message?: string }; detail?: string } } })?.response?.data
  return data?.error?.message || data?.detail || fallback
}
function formatQuantity(value: string): string {
  if (!/^\d{1,14}(\.\d{1,4})?$/.test(value)) return '—'
  const [whole = '0', decimals = ''] = value.split('.')
  const fraction = decimals.replace(/0+$/, '')
  return BigInt(whole).toLocaleString('zh-CN') + (fraction ? '.' + fraction : '')
}
function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date) : '—'
}
function materialTitle(line: MaterialInboundLine): string { return line.part_name_snapshot || line.material_snapshot || line.raw_material_snapshot || '未命名物料' }
async function loadRows() {
  if (!canView.value) return
  const version = ++rowsVersion
  const snapshot: Filters = { ...filters, q: filters.q.trim(), inboundDate: filters.inboundDate || '', warehouseId: filters.warehouseId || '', sectionTitle: filters.sectionTitle || '' }
  loading.value = true
  rowsError.value = ''
  try {
    const data = await fetchMaterialInboundDetails({
      q: snapshot.q || undefined,
      inbound_date: snapshot.inboundDate || undefined,
      warehouse_id: snapshot.warehouseId || undefined,
      zone_id: snapshot.zoneId || undefined,
      section_type: snapshot.exactLine ? snapshot.sectionType : undefined,
      section_title: snapshot.exactLine ? snapshot.sectionTitle : (snapshot.sectionTitle || undefined),
      category: snapshot.exactLine ? snapshot.category : undefined,
      material: snapshot.exactLine ? snapshot.material : undefined,
      part_name: snapshot.exactLine ? snapshot.partName : undefined,
      specification: snapshot.exactLine ? snapshot.specification : undefined,
      raw_material: snapshot.exactLine ? snapshot.rawMaterial : undefined,
      unit: snapshot.exactLine ? snapshot.unit : undefined,
    })
    if (disposed || version !== rowsVersion) return
    batches.value = data.filter(inbound => inbound.status === 'CONFIRMED')
    appliedFilters.value = snapshot
  } catch (error) {
    if (!disposed && version === rowsVersion) { batches.value = []; appliedFilters.value = snapshot; rowsError.value = apiMessage(error, '材料入库明细加载失败，请刷新重试。') }
  } finally { if (!disposed && version === rowsVersion) loading.value = false }
}
async function loadOptions() {
  if (!canView.value) return
  const version = ++optionsVersion
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const data = await fetchMaterialFilterOptions()
    if (!disposed && version === optionsVersion) options.value = data
  } catch (error) {
    if (!disposed && version === optionsVersion) optionsError.value = apiMessage(error, '筛选选项加载失败，请刷新重试。')
  } finally { if (!disposed && version === optionsVersion) optionsLoading.value = false }
}
function reset() { Object.assign(filters, blankFilters()); void loadRows() }
async function refresh() { await Promise.all([loadRows(), loadOptions()]) }
onMounted(() => { if (canView.value) void refresh() })
onBeforeUnmount(() => { disposed = true; rowsVersion++; optionsVersion++ })
</script>

<template>
  <section class="detail-page erp-glass-list" data-testid="material-inbound-details-page">
    <div v-if="!canView" class="empty-state"><h1>无权查看入库明细</h1><p>请联系管理员开通材料入库记录查看权限。</p></div>
    <template v-else>
      <section v-glass-spotlight class="erp-list-filter">
      <header class="page-head erp-list-heading">
        <div class="title-line erp-list-title-row"><h1>材料入库明细</h1><span>共 {{ rows.length }} 条</span><span>只读记录</span></div>
        <ElButton class="erp-button-motion" @click="router.push({ name: 'material-inventory' })">返回材料库存</ElButton>
      </header>
      <section class="summary-strip erp-list-summary" aria-label="当前结果统计" :aria-busy="loading">
        <div class="erp-list-summary-item"><span>入库单</span><strong>{{ summary.batches }}</strong></div>
        <div class="erp-list-summary-item"><span>入库明细</span><strong>{{ summary.details }}</strong></div>
        <div class="erp-list-summary-item"><span>涉及采购单</span><strong>{{ summary.purchaseOrders }}</strong></div>
        <div class="erp-list-summary-item"><span>今日入库</span><strong>{{ summary.today }}</strong></div>
      </section>
      <form class="filters-row erp-list-filters" aria-label="入库记录筛选" @submit.prevent="loadRows">
        <ElInput v-model="filters.q" aria-label="搜索入库记录" :prefix-icon="Search" clearable maxlength="200" placeholder="搜索入库单号、采购单号、物料、供应商" />
        <ElDatePicker v-model="filters.inboundDate" aria-label="入库日期" type="date" value-format="YYYY-MM-DD" :prefix-icon="Calendar" placeholder="入库日期：全部" clearable />
        <ElSelect v-model="filters.warehouseId" aria-label="材料仓" :loading="optionsLoading" clearable placeholder="材料仓：全部"><ElOption v-for="item in options.warehouses" :key="item.id" :value="item.id" :label="item.warehouse_number + ' · ' + item.warehouse_name" /></ElSelect>
        <ElSelect v-model="filters.sectionTitle" aria-label="BOM分区" :loading="optionsLoading" clearable placeholder="BOM 分区：全部"><ElOption v-for="item in options.sections" :key="item" :value="item" :label="item" /></ElSelect>
        <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="reset">重置</ElButton><ElButton class="erp-button-motion" native-type="submit" type="primary" :loading="loading">应用筛选</ElButton></div>
      </form>
      </section>
      <section class="erp-list-data">
      <div class="table-toolbar erp-list-toolbar"><h2>入库追溯明细</h2><span>共 {{ rows.length }} 条</span><ElButton class="erp-button-motion" :icon="Refresh" :loading="loading || optionsLoading" @click="refresh">刷新</ElButton></div>
      <div v-if="rowsError || optionsError" class="load-error" role="alert">{{ rowsError || optionsError }}</div>
      <div v-loading="loading" class="erp-list-table-frame"><div class="detail-table-scroll erp-list-table-scroll" :aria-busy="loading" tabindex="0" aria-label="入库明细表格">
        <table class="detail-table erp-list-native-table">
          <colgroup><col v-for="(width, index) in [194,182,113,221,180,251,130,202,125,216]" :key="index" :style="{ width: width / 1814 * 100 + '%' }" /></colgroup>
          <thead><tr><th v-for="label in ['入库单','来源单据','分类','物料信息','规格','供应商','入库数量','仓库位置','操作人','操作时间']" :key="label" scope="col">{{ label }}</th></tr></thead>
          <tbody>
            <tr v-for="{ inbound, line } in rows" :key="inbound.id + ':' + line.id" @mouseenter="hoveredRowId = line.id" @mouseleave="hoveredRowId = ''">
              <td><div class="stack"><strong>{{ inbound.inbound_number }}</strong><small>{{ inbound.inbound_date || '—' }}</small></div></td>
              <td><div class="stack"><strong>{{ inbound.purchase_order_number || line.purchase_order_number_snapshot || inbound.source_type_display }}</strong><small>{{ line.production_task_number_snapshot || (inbound.source_type === 'MANUAL' ? '无采购单' : '—') }}</small></div></td>
              <td class="category-cell"><ElTag round>{{ line.section_title_snapshot || '未分类' }}</ElTag></td>
              <td><div class="stack material-cell"><strong>{{ materialTitle(line) }}</strong><small v-if="!line.purchase_order_line_id">{{ [line.raw_material_snapshot, line.specification_snapshot].filter(Boolean).join(' · ') || '—' }}</small></div></td>
              <td class="specification-cell"><ElTooltip v-if="line.purchase_order_line_id" placement="top" :show-after="80" :visible="hoveredRowId === line.id" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in materialAttributeFields(line)" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div></div></template><span>{{ materialSpecificationValue(line) }}</span></ElTooltip><span v-else>{{ line.specification_snapshot || '—' }}</span></td>
              <td class="secondary">{{ line.supplier_name_snapshot || '—' }}</td>
              <td class="quantity-cell">{{ line.measurement_kind === 'PIPE' ? `${line.accepted_bar_count} 根 / ` : '' }}{{ formatQuantity(line.accepted_quantity) }} {{ line.source_unit_text_snapshot }}<small v-if="line.measurement_kind === 'PIPE'" style="display:block">{{ line.raw_bar_length_m }} 米/根</small></td>
              <td><div class="stack warehouse-cell"><strong>{{ [line.warehouse_number, line.warehouse_name].filter(Boolean).join(' · ') || '—' }}</strong><small>{{ line.zone_name || '—' }}</small></div></td>
              <td class="secondary">{{ inbound.quality_confirmed_by_name || inbound.received_by_name || '—' }}</td>
              <td class="secondary">{{ formatTime(inbound.quality_confirmed_at || inbound.updated_at) }}</td>
            </tr>
            <tr v-if="!rows.length"><td colspan="10" class="table-empty">{{ rowsError ? '记录加载失败，请刷新重试' : loading ? '正在加载入库记录…' : '暂无符合条件的已确认入库记录' }}</td></tr>
          </tbody>
        </table>
      </div></div>
      <p class="readonly-note erp-list-footer"><ElIcon><InfoFilled /></ElIcon><span>仅展示已确认记录；采购入库显示品质合格数量，额外入库提交后直接计入库存。</span></p>
      </section>
    </template>
  </section>
</template>

<style scoped lang="scss">
.title-line { display: flex; align-items: baseline; flex-wrap: wrap; gap: 24px; }
.title-line span, .table-toolbar > span { color: var(--erp-color-text-secondary); font-size: 12px; }
.page-head > .el-button { margin-left: auto; }
.filters-row > :deep(.el-input) { width: min(100%, 380px); }
.filters-row > :deep(.el-select), .filters-row > :deep(.el-date-editor) { width: 190px; }
.table-toolbar h2 { margin: 0 auto 0 0; font-size: 16px; }
.detail-table { min-width: 1400px; }
.stack { display: flex; flex-direction: column; gap: 2px; }
.stack small, .secondary { color: var(--erp-table-text); font-size: 11px; line-height: 16px; }
.stack strong { font-size: 12px; line-height: 18px; }
.detail-table .specification-cell, .detail-table .specification-cell > span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.detail-table .specification-cell > span { display: block; }
.detail-table .quantity-cell { font-weight: 700; text-align: right; }
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: var(--erp-color-text-muted); min-width: 42px; }
.readonly-note { margin: 0; justify-content: flex-start; }
.load-error { flex: none; padding: 6px 0; color: var(--erp-color-danger); font-size: 12px; }
.empty-state { padding: 80px; text-align: center; color: var(--erp-color-text-secondary); }
</style>
