<script setup lang="ts">
import { compactDecimal } from '@/utils/compactDecimal'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { useRoute, useRouter } from 'vue-router'
import FinishedReceiptRecordsPanel from './FinishedReceiptRecordsPanel.vue'
import FinishedGoodsOutboundListView from './FinishedGoodsOutboundListView.vue'
import AssemblyPlanPicker from './AssemblyPlanPicker.vue'
import { fetchFinishedLocations } from '@/api/finishedReceipts'
import type { FinishedLocation } from '@/types/finishedReceipts'
import '@/styles/finishedReceipts.scss'
import ElDialog from '@/components/common/AppWindowDialog.vue'
import WarehouseConfigurationDialogs from '@/components/inventory/WarehouseConfigurationDialogs.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  fetchFinishedGoodsInventory, fetchFinishedGoodsFilterOptions,
} from '@/api/inventory'
import type { MaterialReceivingOptions } from '@/types/inventory'
import type { FinishedGoodsInventoryRow } from '@/types/inventory'

const route = useRoute()
const router = useRouter()
type StockTab = 'stock' | 'records' | 'outbounds'
function readStockTab(value: unknown): StockTab { return value === 'records' || value === 'outbounds' ? value : 'stock' }
const stockTab = ref(readStockTab(route.query.tab))
const planPickerVisible = ref(false), stockDetailVisible = ref(false), stockDetailLoading = ref(false), stockDetailError = ref('')
const stockDetailRow = ref<FinishedGoodsInventoryRow>(), stockLocations = ref<FinishedLocation[]>([])
let stockDetailSequence = 0
async function openStockDetail(row: FinishedGoodsInventoryRow) {
 const current = ++stockDetailSequence
 stockDetailVisible.value = true; stockDetailLoading.value = true; stockDetailError.value = ''; stockDetailRow.value = row; stockLocations.value = []
 try { const result = await fetchFinishedLocations(row); if (current === stockDetailSequence) stockLocations.value = result }
 catch (cause) { if (current === stockDetailSequence) stockDetailError.value = message(cause, '库位详情读取失败。') }
 finally { if (current === stockDetailSequence) stockDetailLoading.value = false }
}
function toggleStock(row: FinishedGoodsInventoryRow, checked: boolean) {
 selectedRows.value = checked ? [...selectedRows.value.filter(v => v.inventory_key !== row.inventory_key), row] : selectedRows.value.filter(v => v.inventory_key !== row.inventory_key)
}
function switchStockTab(value: StockTab) {
  if (stockTab.value === value) return
  stockTab.value = value; selectedRows.value = []
  if (value === 'stock') void loadRows()
  void router.replace({ query: { ...route.query, tab: value } })
}
watch(() => route.query.tab, value => {
  const next = readStockTab(value)
  if (stockTab.value === next) return
  stockTab.value = next; selectedRows.value = []
  if (next === 'stock') void loadRows()
})
const auth = useAuthStore()
const loading = ref(false); const errorMessage = ref(''); const rows = ref<FinishedGoodsInventoryRow[]>([])
const page = ref(1); const pageSize = ref(50); const total = ref(0); const keyword = ref(''); const warehouseFilter = ref(''); const zoneFilter = ref('')
const filterOptions = ref<MaterialReceivingOptions>({ warehouses: [], zones: [] })
const selectedRows = ref<FinishedGoodsInventoryRow[]>([])
const warehouseConfiguration = ref<InstanceType<typeof WarehouseConfigurationDialogs> | null>(null)
const canInbound = computed(() => auth.hasPermission('inventory.add_finishedgoodsreceipt'))
const canOutbound = computed(() => auth.hasPermission('inventory.add_finishedgoodsoutbound'))
const canConfigure = computed(() => auth.hasPermission('inventory.view_warehouse') || auth.hasPermission('inventory.view_warehouselocation'))
function message(error: unknown, fallback: string) { const value = error as { response?: { data?: { error?: { message?: string } }; status?: number } }; return value.response?.data?.error?.message || fallback }

let inventorySequence = 0
async function loadRows() {
  const current = ++inventorySequence
  loading.value = true; errorMessage.value = ''; selectedRows.value = []
  try { const result = await fetchFinishedGoodsInventory({ exclude_sample: true, page: page.value, page_size: pageSize.value, q: keyword.value || undefined, warehouse_id: warehouseFilter.value || undefined, zone_id: zoneFilter.value || undefined }); if (current === inventorySequence) { rows.value = result.results; total.value = result.count } }
  catch (error) { if (current === inventorySequence) { rows.value = []; total.value = 0; errorMessage.value = message(error, '成品库存加载失败，请重试。') } }
  finally { if (current === inventorySequence) loading.value = false }
}
async function loadOptions() { try { filterOptions.value = await fetchFinishedGoodsFilterOptions() } catch (error) { ElMessage.error(message(error, '库存筛选选项加载失败，请刷新重试。')) } }
function search() { page.value = 1; void loadRows() }
function changeWarehouseFilter() { zoneFilter.value = ''; search() }

function openConfig(kind: 'warehouse' | 'location') { void warehouseConfiguration.value?.open(kind) }

async function openOutbound() {
  if (!selectedRows.value.length) { ElMessage.warning('请先勾选需要出库的库存。'); return }
  if (new Set(selectedRows.value.map(row => row.task_number)).size !== 1) { ElMessage.warning('请只选择同一生产任务单的库存。'); return }
  void router.push({ name: 'finished-goods-outbound-new', query: { receipt_ids: selectedRows.value.flatMap(item => item.receipt_ids).join(',') } })
}

onMounted(() => { if (stockTab.value === 'stock') void loadRows(); void loadOptions() })
</script>

<template>
  <section class="finished-stock-page erp-glass-list">
    <section v-if="stockTab==='stock'" v-glass-spotlight class="erp-list-filter">
    <header class="fg-heading erp-list-heading"><h1>成品库存</h1><span class="fg-muted" v-if="stockTab==='stock'">共 {{ total }} 条库存记录</span></header>
      <section class="fg-filters erp-list-filters">
        <template v-if="stockTab==='stock'"><ElInput v-model="keyword" clearable placeholder="搜索生产任务单号、品号、品名、货号、规格或颜色" @keyup.enter="search" @clear="search"/><ElSelect v-model="warehouseFilter" clearable placeholder="全部仓库" @change="changeWarehouseFilter"><ElOption v-for="item in filterOptions.warehouses" :key="item.id" :value="item.id" :label="item.warehouse_name"/></ElSelect><ElSelect v-model="zoneFilter" clearable placeholder="全部库区" @change="search"><ElOption v-for="item in filterOptions.zones.filter(z=>!warehouseFilter||z.warehouse===warehouseFilter)" :key="item.id" :value="item.id" :label="item.zone_name"/></ElSelect><div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="keyword=''; warehouseFilter=''; zoneFilter=''; search()">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="search">应用筛选</ElButton></div></template>
        <div class="fg-heading-actions"><ElDropdown v-if="canConfigure" trigger="click" @command="openConfig"><ElButton class="erp-button-motion">仓库配置</ElButton><template #dropdown><ElDropdownMenu><ElDropdownItem command="warehouse">仓库信息</ElDropdownItem><ElDropdownItem command="location">库位信息</ElDropdownItem></ElDropdownMenu></template></ElDropdown><ElButton class="erp-button-motion" v-if="canInbound" type="primary" @click="planPickerVisible=true">成品入库</ElButton></div>
      </section>
    </section>
    <FinishedReceiptRecordsPanel v-if="stockTab==='records'" :key="String(route.query.schedule_product_id || '') + ':' + String(route.query.product_line_id || '')">
      <template #heading><header class="fg-heading erp-list-heading"><h1>成品库存</h1></header></template>
      <template #actions><div class="fg-heading-actions"><ElDropdown v-if="canConfigure" trigger="click" @command="openConfig"><ElButton class="erp-button-motion">仓库配置</ElButton><template #dropdown><ElDropdownMenu><ElDropdownItem command="warehouse">仓库信息</ElDropdownItem><ElDropdownItem command="location">库位信息</ElDropdownItem></ElDropdownMenu></template></ElDropdown><ElButton class="erp-button-motion" v-if="canInbound" type="primary" @click="planPickerVisible=true">成品入库</ElButton></div></template>
      <template #default>
      <nav class="fg-tabs erp-list-tabs" aria-label="成品库存视图"><button @click="switchStockTab('stock')">库存汇总</button><button class="active" @click="switchStockTab('records')">入库记录</button><button @click="switchStockTab('outbounds')">出库记录</button></nav>
      </template>
    </FinishedReceiptRecordsPanel>
    <FinishedGoodsOutboundListView v-else-if="stockTab==='outbounds'" @select-stock="switchStockTab('stock')">
      <nav class="fg-tabs erp-list-tabs" aria-label="成品库存视图"><button @click="switchStockTab('stock')">库存汇总</button><button @click="switchStockTab('records')">入库记录</button><button class="active" @click="switchStockTab('outbounds')">出库记录</button></nav>
    </FinishedGoodsOutboundListView>
    <div v-else class="fg-stock-body erp-list-data">

      <div class="fg-toolbar erp-list-toolbar"><nav class="fg-tabs erp-list-tabs" aria-label="成品库存视图"><button class="active" @click="switchStockTab('stock')">库存汇总</button><button @click="switchStockTab('records')">入库记录</button><button @click="switchStockTab('outbounds')">出库记录</button></nav><div class="fg-stock-selection"><span class="fg-muted">已选 {{selectedRows.length}} 条</span><ElButton class="erp-button-motion" v-if="canOutbound" :disabled="!selectedRows.length" @click="openOutbound">批量出库</ElButton></div></div>
      <ElAlert v-if="errorMessage" :title="errorMessage" type="error" :closable="false"/>
      <section class="fg-stock-table" v-loading="loading"><div class="erp-list-table-frame"><div class="fg-table-scroll erp-list-table-scroll"><table class="fg-table erp-list-native-table erp-list-native-table--nowrap"><colgroup><col v-for="(width,i) in [50,130,80,120,160,95,165,90,95,65,105,75,90,95,135,120]" :key="i" :style="{width:width+'px'}"></colgroup><thead><tr><th class="center selection-cell"><input type="checkbox" aria-label="全选库存" :checked="rows.length>0&&selectedRows.length===rows.length" @change="selectedRows=($event.target as HTMLInputElement).checked?[...rows]:[]"></th><th v-for="name in ['生产任务单号','类别','产品编码','品名','货号','规格','颜色','当前库存','单位','仓库','库区','在库记录','占用箱位','最近入库日期','操作']" :key="name">{{name}}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.inventory_key" :class="{selected:selectedRows.some(r=>r.inventory_key===row.inventory_key)}"><td class="center selection-cell"><input type="checkbox" :aria-label="'选择'+row.task_number+row.product_number+row.actual_color+row.zone_name" :checked="selectedRows.some(r=>r.inventory_key===row.inventory_key)" @change="toggleStock(row,($event.target as HTMLInputElement).checked)"></td><td>{{row.task_number||'—'}}</td><td>{{row.category||'—'}}</td><td :title="row.product_code">{{row.product_code||'—'}}</td><td :title="row.product_name">{{row.product_name}}</td><td>{{row.item_number||'—'}}</td><td :title="row.specification">{{row.specification||'—'}}</td><td>{{row.actual_color||'—'}}</td><td class="num">{{Number(row.inventory_quantity).toLocaleString()}}</td><td>{{row.unit_name}}</td><td>{{row.warehouse_name}}</td><td>{{row.zone_name}}</td><td class="num">{{row.batch_count}}</td><td class="num">{{row.occupied_box_slots??'未计算'}}</td><td>{{row.latest_inbound_time?new Date(row.latest_inbound_time).toLocaleDateString('sv-SE'):'—'}}</td><td><ElButton link type="primary" @click="openStockDetail(row)">库存详情</ElButton></td></tr></tbody></table><div class="fg-empty" v-if="!loading&&!rows.length">暂无符合条件的成品库存</div></div></div><footer class="fg-pager erp-list-footer"><span>共 {{total}} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20,50,100]" layout="sizes, prev, pager, next" @current-change="loadRows" @size-change="search"/></footer></section>
    </div>
    <AssemblyPlanPicker v-model="planPickerVisible"/>
    <ElDialog v-model="stockDetailVisible" title="成品库存 · 库位详情" :width="1180" :height="660" class="fg-window" destroy-on-close><div v-loading="stockDetailLoading"><ElAlert v-if="stockDetailError" :title="stockDetailError" type="error"/><template v-if="stockDetailRow"><div class="fg-detail-title"><b>{{stockDetailRow.product_name}}</b><span class="fg-muted">当前库存 {{ compactDecimal(stockDetailRow.inventory_quantity) }} {{stockDetailRow.unit_name}}</span></div><dl class="fg-detail-fields"><div v-for="([key,value]) in [['生产任务单号',stockDetailRow.task_number],['产品编码',stockDetailRow.product_code],['货号',stockDetailRow.item_number],['类别',stockDetailRow.category],['规格',stockDetailRow.specification],['颜色',stockDetailRow.actual_color],['仓库 / 库区',stockDetailRow.warehouse_name+' / '+stockDetailRow.zone_name]]" :key="key"><dt>{{key}}</dt><dd>{{value||'—'}}</dd></div></dl><h2 class="fg-detail-heading">存放库位</h2><div class="fg-table-card"><table class="fg-table compact"><thead><tr><th>库位</th><th>当前数量</th><th>单位</th><th>占用箱位</th></tr></thead><tbody><tr v-for="l in stockLocations" :key="l.location_id"><td>{{l.location_number}}</td><td>{{ compactDecimal(l.quantity) }}</td><td>{{stockDetailRow.unit_name}}</td><td>{{l.slots??'未计算'}}{{l.unknown_packaging&&l.slots!=null?'（部分未计算）':''}}</td></tr></tbody></table></div><p class="fg-helper">库存按生产任务单汇总；本详情仅显示当前任务单的存放库位。</p></template></div><template #footer><ElButton @click="stockDetailVisible=false">关闭</ElButton></template></ElDialog>
    <WarehouseConfigurationDialogs ref="warehouseConfiguration" warehouse-type="FINISHED" @saved="loadOptions" />
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/crm/tokens' as token;
.finished-stock-page > .fg-stock-body > .fg-table-card > .fg-table-scroll > .fg-table {
  > thead > tr > th:last-child { position: sticky; right: 0; z-index: 3; background: var(--erp-table-header-fill); }
  > tbody > tr > td:last-child { position: sticky; right: 0; z-index: 2; background: var(--erp-table-body-fill); }
  > tbody > tr:hover > td:last-child { background: var(--erp-color-hover); }
  > tbody > tr.selected > td:last-child { background: var(--erp-color-selected); }
}
.inventory-page{box-sizing:border-box;height:calc(100dvh - 84px);min-width:1450px;display:flex;flex-direction:column;gap:16px;padding:24px 28px 20px;background:var(--erp-page-background);color:var(--erp-color-text-primary)}.page-head,.head-actions,.toolbar,.pager{display:flex;align-items:center}.page-head{justify-content:space-between}.page-head h1{margin:0;font-size:28px}.page-head p{margin:4px 0 0;color:var(--erp-color-text-secondary)}.head-actions{gap:10px}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.summary-grid article{padding:14px 18px;border:1px solid var(--erp-color-border);border-radius:10px;background:var(--erp-color-surface)}.summary-grid span{display:block;color:var(--erp-color-text-secondary);font-size:13px}.summary-grid strong{display:block;margin-top:6px;font-size:24px}.toolbar{gap:10px}.toolbar :deep(.el-input){width:390px}.toolbar :deep(.el-select){width:180px}.table-card{flex:1;min-height:0;border:1px solid var(--erp-table-grid);border-radius:10px;overflow:hidden;background:var(--erp-table-body-fill)}.pager{justify-content:space-between;color:var(--erp-color-text-secondary)}.form-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:0 18px;margin-top:18px}.span-2{grid-column:span 2}.outbound-common{display:grid;grid-template-columns:1fr 1.5fr 2fr;gap:18px;margin-top:18px}:deep(.el-input-number){width:100%}:deep(.el-select){width:100%}:deep(.el-cascader){width:100%}
</style>

<style scoped lang="scss">
.fg-filters > :deep(.el-input) { width: 200px; min-width: 200px; max-width: 410px; flex: 1 1 200px; }
.fg-filters > :deep(.el-select) { width: 160px; flex: 0 0 160px; }
.fg-filters .erp-list-filter-actions { margin-left: 0; }
.fg-heading-actions { margin-left: auto; flex: none; flex-wrap: nowrap; gap: 8px; }
.fg-stock-selection { display: flex; align-items: center; gap: 8px; margin-left: auto; }
@media (max-width: 1500px) {
  .fg-filters > :deep(.el-select) { width: 128px; flex-basis: 128px; }
}
.fg-table.erp-list-native-table { min-width: 1620px; }
.fg-stock-table .fg-table .selection-cell { padding: 0; text-overflow: clip; vertical-align: middle; }
.selection-cell input[type='checkbox'] { display: block; width: 14px; height: 14px; margin: 0 auto; }
.fg-stock-table { display: flex; flex: 1; flex-direction: column; min-height: 0; }
</style>
