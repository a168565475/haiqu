<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, Setting } from '@element-plus/icons-vue'

import WarehouseConfigurationDialogs from '@/components/inventory/WarehouseConfigurationDialogs.vue'
import { fetchMaterialInventory, fetchMaterialFilterOptions } from '@/api/inventory'
import searchIcon from '@/assets/crm-v2/search.svg'
import { router } from '@/router'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { MaterialFilterOptions, MaterialInventoryRow } from '@/types/inventory'

const auth = useAuthStore()
const route = useRoute()
const can = (permission: string) => auth.user?.is_superuser === true || auth.hasPermission(permission)
const canView = computed(() => can('inventory.view_materialinbound'))
const canReceive = computed(() => can('inventory.receive_material'))
const canReceiveTubeCoating = computed(() => can('outsourcing.confirm_return_outsourcingorder'))
const canViewReceipts = computed(() => can('inventory.view_material_receipt'))
const canConfigure = computed(() => can('inventory.view_warehouse') || can('inventory.view_warehousezone'))
const rows = ref<MaterialInventoryRow[]>([])
const options = ref<MaterialFilterOptions>({ warehouses: [], zones: [], sections: [] })
const publicStock = computed(() => options.value.stock_mode === 'PUBLIC_V2')
const loading = ref(false)
let rowsVersion = 0
let disposed = false
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const activeSection = ref('')
const warehouseConfiguration = ref<InstanceType<typeof WarehouseConfigurationDialogs> | null>(null)
const filters = reactive({ q: '', warehouseId: '', zoneId: '', processingStatus: '' })

function routeStockKind(value: unknown): 'RAW' | 'SEMI' {
  return value === 'SEMI' ? 'SEMI' : 'RAW'
}
const stockKind = ref<'RAW' | 'SEMI'>(routeStockKind(route.query.stock_kind))

const warehousesForFilter = computed(() => options.value.warehouses.filter((item) =>
  !publicStock.value || !item.warehouse_type || item.warehouse_type === (stockKind.value === 'SEMI' ? 'SEMI_FINISHED' : 'MATERIAL')))
const zonesForFilter = computed(() => options.value.zones.filter((item) =>
  warehousesForFilter.value.some((warehouse) => warehouse.id === item.warehouse)
  && (!filters.warehouseId || item.warehouse === filters.warehouseId)))
function apiMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string }; detail?: string } } })?.response
  return response?.data?.error?.message || response?.data?.detail || fallback
}
function formatQuantity(value: string | number): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—'
}
function stockQuantityText(row: MaterialInventoryRow): string {
  const quantity = formatQuantity(row.inventory_quantity)
  return row.measurement_kind === 'PIPE'
    ? `${quantity} · ${row.meter_quantity || '—'} 米 · ${row.raw_bar_length_m || '—'} 米/根`
    : quantity
}
function sectionLabel(row: MaterialInventoryRow): string {
  return stockKind.value === 'SEMI' && row.section_type === 'PROFILE' ? '管材' : row.section_title
}
function search() { page.value = 1; void loadRows() }
function reset() { Object.assign(filters, { q: '', warehouseId: '', zoneId: '', processingStatus: '' }); activeSection.value = ''; search() }
function warehouseChanged() { filters.zoneId = ''; search() }
function stockKindChanged() {
  filters.warehouseId = ''; filters.zoneId = ''; filters.processingStatus = ''; activeSection.value = ''; page.value = 1
  const query = { ...route.query }
  if (stockKind.value === 'SEMI') query.stock_kind = 'SEMI'
  else delete query.stock_kind
  void router.replace({ name: 'material-inventory', query })
  void loadRows()
}
async function loadRows() {
  const version = ++rowsVersion
  loading.value = true
  try {
    const result = await fetchMaterialInventory({
      stock_kind: stockKind.value, page: page.value, page_size: pageSize.value, q: filters.q || undefined, section_title: activeSection.value || undefined,
      processing_status: stockKind.value === 'SEMI' ? (filters.processingStatus || undefined) : undefined,
      warehouse_id: filters.warehouseId || undefined, zone_id: filters.zoneId || undefined,
    })
    if (disposed || version !== rowsVersion) return
    rows.value = result.results
    total.value = result.count
  } catch (error) { if (disposed || version !== rowsVersion) return; rows.value = []; total.value = 0; ElMessage.error(apiMessage(error, '材料库存加载失败。')) }
  finally { if (!disposed && version === rowsVersion) loading.value = false }
}
async function loadOptions() {
  try { options.value = await fetchMaterialFilterOptions() }
  catch (error) { ElMessage.error(apiMessage(error, '材料仓库配置加载失败。')) }
}
function refresh() { void Promise.all([loadRows(), loadOptions()]) }
function openConfig(kind: 'warehouse' | 'location') { void warehouseConfiguration.value?.open(kind) }
function openMaterialDetail(row: MaterialInventoryRow, tab: 'issues' | 'purchases' = 'issues') {
  if (!row.stock_item_id) { ElMessage.warning('该库存行缺少稳定原料标识，暂不能查看订单追溯。'); return }
  void router.push({ name: 'material-inventory-detail', params: { stockItemId: row.stock_item_id }, query: { tab } })
}

onBeforeUnmount(() => { disposed = true; rowsVersion++ })
watch(() => route.query.stock_kind, value => {
  const next = routeStockKind(value)
  if (next === stockKind.value) return
  stockKind.value = next; filters.warehouseId = ''; filters.zoneId = ''; filters.processingStatus = ''; activeSection.value = ''; page.value = 1
  void loadRows()
})
onMounted(() => { if (canView.value) void Promise.all([loadRows(), loadOptions()]) })
</script>

<template>
  <section class="material-page erp-glass-list" data-testid="material-inventory-page">
    <div v-if="!canView" class="empty-state"><h1>无权查看材料库存</h1><p>请联系管理员开通材料库存查看权限。</p></div>
    <template v-else>
      <section v-glass-spotlight class="erp-list-filter">
      <header class="page-heading erp-list-heading">
        <h1>材料库存</h1><ElRadioGroup v-model="stockKind" class="stock-kind-switch" aria-label="库存性质" @change="stockKindChanged"><ElRadioButton value="RAW">原材料</ElRadioButton><ElRadioButton value="SEMI">半成品</ElRadioButton></ElRadioGroup>
        <span class="total-count">共 {{ total }} 条</span>
        <span class="heading-space" />
        <div class="head-actions">
          <ElButton class="erp-button-motion" :icon="Refresh" @click="refresh">刷新</ElButton>
          <ElButton class="erp-button-motion" v-if="stockKind === 'SEMI' &amp;&amp; (auth.user?.is_superuser || auth.hasPermission('inventory.view_internalsemifinishedreceipt'))" @click="router.push({name: 'semi-receipt-records'})">入库记录</ElButton><ElButton class="erp-button-motion" v-if="stockKind === 'RAW' &amp;&amp; canViewReceipts" @click="router.push({ name: 'material-inbound-details' })">入库明细</ElButton>
          <ElDropdown v-if="canConfigure">
            <ElButton class="erp-button-motion" :icon="Setting">配置</ElButton>
            <template #dropdown><ElDropdownMenu><ElDropdownItem @click="openConfig('warehouse')">仓库信息</ElDropdownItem><ElDropdownItem @click="openConfig('location')">库区设置</ElDropdownItem></ElDropdownMenu></template>
          </ElDropdown>
          <ElButton class="erp-button-motion" v-if="stockKind === 'SEMI' && canReceiveTubeCoating" type="primary" :icon="Plus" @click="router.push({ name: 'inventory-tube-return' })">喷塑入库</ElButton>
          <ElButton class="erp-button-motion" v-if="stockKind === 'RAW' && canReceive" type="primary" :icon="Plus" @click="router.push({ name: 'manual-material-inbound' })">材料入库</ElButton>
        </div>
      </header>

      <section class="filters-card" aria-label="材料库存筛选">
        <form class="filter-row erp-list-filters" :class="{ 'filter-row--semi': stockKind === 'SEMI' }" @submit.prevent="search">
          <ElInput v-model="filters.q" class="filter-control filter-control--search" clearable aria-label="搜索原料名称、规格、拼音或首字母" placeholder="搜索原料名称、规格、拼音或首字母">
            <template #suffix><img class="field-icon" :src="searchIcon" alt="" aria-hidden="true" /></template>
          </ElInput>
          <ElSelect v-model="activeSection" class="filter-control filter-control--section" clearable aria-label="材料分类" placeholder="材料分类：全部" @change="search">
            <ElOption v-for="section in options.sections" :key="section" :value="section" :label="section" />
          </ElSelect>
          <ElSelect v-if="stockKind === 'SEMI'" v-model="filters.processingStatus" class="filter-control filter-control--status" clearable aria-label="加工状态" placeholder="加工状态：全部" @change="search">
            <ElOption value="METAL" label="未喷塑" />
            <ElOption value="POWDER_COATING" label="已喷塑" />
          </ElSelect>
          <ElSelect v-model="filters.warehouseId" class="filter-control filter-control--warehouse" clearable aria-label="材料仓" placeholder="材料仓：全部" @change="warehouseChanged"><ElOption v-for="item in warehousesForFilter" :key="item.id" :value="item.id" :label="`${item.warehouse_number} · ${item.warehouse_name}`" /></ElSelect>
          <ElSelect v-model="filters.zoneId" class="filter-control filter-control--zone" clearable aria-label="库区" placeholder="库区：全部" @change="search"><ElOption v-for="item in zonesForFilter" :key="item.id" :value="item.id" :label="item.zone_name" /></ElSelect>
          <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="reset">重置</ElButton><ElButton class="erp-button-motion" type="primary" native-type="submit">应用筛选</ElButton></div>
        </form>
      </section>

      </section>
      <section class="inventory-table erp-list-data">
        <header class="erp-list-toolbar"><div><h2>材料库存明细</h2><span>{{ stockKind === 'SEMI' && publicStock ? '公共半成品按实物属性、工艺和单位汇总，不关联采购批次' : publicStock ? '原材料按实物属性和库区汇总' : '原材料按长度、材料仓和库区汇总；半成品按订单、部位和工艺区分' }}</span></div><span>共 {{ total }} 条</span></header>
        <div class="table-shell erp-list-table-frame">
          <ElTable v-loading="loading" :data="rows" height="100%" stripe empty-text="暂无材料库存" row-key="inventory_key">
          <ElTableColumn type="index" label="序号" width="66" align="center" class-name="sequence-column" label-class-name="sequence-column" :index="(index: number) => (page - 1) * pageSize + index + 1" />
          <ElTableColumn label="材料分类" width="104"><template #default="{ row }">{{ sectionLabel(row) }}</template></ElTableColumn>
          <ElTableColumn prop="category" label="类别" width="90" />
          <ElTableColumn prop="material" label="材质" width="90" />
          <ElTableColumn prop="part_name" label="部件" min-width="120" />
          <ElTableColumn prop="color" label="颜色" width="110"><template #default="{ row }">{{ row.color || '—' }}</template></ElTableColumn>
          <ElTableColumn prop="specification" label="规格/切割长度" min-width="170" />
          <ElTableColumn v-if="stockKind === 'SEMI' && publicStock" label="厚度" width="82"><template #default="{ row }">{{ row.tube_thickness || '—' }}</template></ElTableColumn>
          <ElTableColumn label="当前库存" :min-width="stockKind === 'RAW' ? 240 : 110" align="right"><template #default="{ row }"><span class="stock-quantity" :title="stockQuantityText(row)"><b>{{ formatQuantity(row.inventory_quantity) }}</b><small v-if="row.measurement_kind === 'PIPE'"> · {{ row.meter_quantity || '—' }} 米 · {{ row.raw_bar_length_m || '—' }} 米/根</small></span></template></ElTableColumn>
          <ElTableColumn prop="unit" label="单位" width="65" align="center" />
          <ElTableColumn label="材料仓" min-width="150"><template #default="{ row }">{{ row.warehouse_name || '—' }}</template></ElTableColumn>
          <ElTableColumn label="库区" min-width="175"><template #default="{ row }">{{ row.zone_name }}</template></ElTableColumn>
          <ElTableColumn v-if="stockKind === 'RAW'" label="订单追溯" width="126" align="center"><template #default="{ row }"><ElButton link type="primary" @click="openMaterialDetail(row, 'purchases')">采购</ElButton><ElButton link type="primary" @click="openMaterialDetail(row, 'issues')">领用</ElButton></template></ElTableColumn>
          <ElTableColumn v-if="stockKind === 'SEMI' && publicStock" label="加工状态" min-width="112"><template #default="{ row }">{{ row.processing_status_label || row.completed_craft || '—' }}</template></ElTableColumn>
          <ElTableColumn v-if="stockKind === 'SEMI' && !publicStock" prop="production_task_number" label="生产单号" min-width="150" /><ElTableColumn v-if="stockKind === 'SEMI' && !publicStock" prop="product_name" label="产品" min-width="150" /><ElTableColumn prop="latest_inbound_date" label="最近入库日期" width="129" align="center" />
          </ElTable>
        </div>
        <footer class="page-footer erp-list-footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" layout="sizes, prev, pager, next" :total="total" :page-sizes="[20, 50, 100]" @current-change="loadRows" @size-change="page = 1; loadRows()" /></footer>
      </section>
      <WarehouseConfigurationDialogs ref="warehouseConfiguration" warehouse-type="MATERIAL" @saved="loadOptions" />
    </template>
  </section>
</template>

<style scoped lang="scss">
.head-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-left: auto; }
.total-count { color: var(--erp-color-text-secondary); font-size: 13px; white-space: nowrap; }
.stock-kind-switch { flex: none; }
.filter-control--search { width: min(100%, 410px); }
.filter-control--section, .filter-control--status { width: 150px; }
.filter-control--warehouse { width: 210px; }
.filter-control--zone { width: 170px; }
.field-icon { display: block; width: 16px; height: 16px; opacity: .72; }
.inventory-table header { justify-content: space-between; }
.inventory-table header > div { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; }
.inventory-table h2 { margin: 0; font-size: 16px; }
.inventory-table header span { color: var(--erp-color-text-secondary); font-size: 12px; }
.table-shell :deep(.stock-quantity) { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty-state { padding: 80px; text-align: center; color: var(--erp-color-text-secondary); }
</style>
