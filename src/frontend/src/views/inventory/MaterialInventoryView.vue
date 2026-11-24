<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'

import WarehouseConfigurationDialogs from '@/components/inventory/WarehouseConfigurationDialogs.vue'
import { fetchMaterialInventory, fetchMaterialFilterOptions } from '@/api/inventory'
import searchIcon from '@/assets/crm-v2/search.svg'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { MaterialFilterOptions, MaterialInventoryRow } from '@/types/inventory'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const can = (permission: string) => auth.user?.is_superuser === true || auth.hasPermission(permission)
const canView = computed(() => can('inventory.view_materialinbound'))
const canConfigure = computed(() => can('inventory.view_warehouse') || can('inventory.view_warehousezone'))
const rows = ref<MaterialInventoryRow[]>([])
const options = ref<MaterialFilterOptions>({ warehouses: [], zones: [], sections: [] })
const publicStock = computed(() => options.value.stock_mode === 'PUBLIC_V2')
const hasCatalogRows = computed(() => rows.value.some(row => !!row.material_catalog_id))
const loading = ref(false)
let rowsVersion = 0
let disposed = false
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const activeSection = ref('TUBE')
const warehouseConfiguration = ref<InstanceType<typeof WarehouseConfigurationDialogs> | null>(null)
const filters = reactive({ q: '', warehouseId: '', zoneId: '', processingStatus: '' })

function routeStockKind(value: unknown): 'RAW' | 'SEMI' {
  return value === 'SEMI' ? 'SEMI' : 'RAW'
}
const stockKind = ref<'RAW' | 'SEMI'>(routeStockKind(route.query.stock_kind))
const bomSections = computed(() => options.value.bom_sections?.[stockKind.value] ?? [])
const attributeFields = computed(() => bomSections.value.find(section => section.key === activeSection.value)?.fields ?? [])
const showCoatingFilter = computed(() => stockKind.value === 'SEMI' && activeSection.value === 'TUBE')
const showWeight = computed(() => stockKind.value === 'RAW' && activeSection.value === 'HARDWARE')

const warehousesForFilter = computed(() => options.value.warehouses.filter((item) =>
  !item.warehouse_type || item.warehouse_type === (stockKind.value === 'SEMI' ? 'SEMI_FINISHED' : 'MATERIAL')))
const zonesForFilter = computed(() => options.value.zones.filter((item) =>
  warehousesForFilter.value.some((warehouse) => warehouse.id === item.warehouse)
  && (!filters.warehouseId || item.warehouse === filters.warehouseId)))
function apiMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string }; detail?: string } } })?.response
  return response?.data?.error?.message || response?.data?.detail || fallback
}
function formatQuantity(value: string | number): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) : '—'
}
function stockWeightText(row: MaterialInventoryRow): string {
  const weight = row.weight_quantity_kg ?? row.weight_quantity
  if (weight != null && /^\d+(?:\.\d+)?$/.test(String(weight))) return formatQuantity(weight)
  return row.measurement_kind === 'HARDWARE_WEIGHT' ? '重量待核对' : '—'
}
function attributeText(row: MaterialInventoryRow, key: string) {
  const value = row.inventory_attributes?.[key]
  return value == null || value === '' ? '—' : value
}
function search() { page.value = 1; void loadRows() }
function reset() { Object.assign(filters, { q: '', warehouseId: '', zoneId: '', processingStatus: '' }); search() }
function warehouseChanged() { filters.zoneId = ''; search() }
function selectSection(key: string) {
  if (key === activeSection.value) return
  activeSection.value = key
  filters.processingStatus = ''
  rows.value = []
  total.value = 0
  search()
}
function resetStockKindFilters() {
  filters.warehouseId = ''
  filters.zoneId = ''
  filters.processingStatus = ''
  activeSection.value = bomSections.value[0]?.key ?? 'TUBE'
  rows.value = []
  total.value = 0
}
function stockKindChanged() {
  resetStockKindFilters()
  const query = { ...route.query }
  if (stockKind.value === 'SEMI') query.stock_kind = 'SEMI'
  else delete query.stock_kind
  void router.replace({ name: 'material-inventory', query })
  search()
}
async function loadRows() {
  const version = ++rowsVersion
  loading.value = true
  try {
    const result = await fetchMaterialInventory({
      stock_kind: stockKind.value, page: page.value, page_size: pageSize.value, q: filters.q || undefined, bom_section: activeSection.value,
      processing_status: showCoatingFilter.value ? (filters.processingStatus || undefined) : undefined,
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
function openConfig(kind: 'warehouse' | 'location') { void warehouseConfiguration.value?.open(kind) }
function openMaterialDetail(row: MaterialInventoryRow, tab: 'issues' | 'purchases' = 'issues') {
  if (!row.stock_item_id) { ElMessage.warning('该库存行缺少稳定原料标识，暂不能查看订单追溯。'); return }
  void router.push({ name: 'material-inventory-detail', params: { stockItemId: row.stock_item_id }, query: { tab, ...(row.material_catalog_id ? { identity_key: row.identity_key } : {}) } })
}

onBeforeUnmount(() => { disposed = true; rowsVersion++ })
watch(() => route.query.stock_kind, value => {
  const next = routeStockKind(value)
  if (next === stockKind.value) return
  stockKind.value = next
  resetStockKindFilters()
  search()
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
      </header>

      <section class="filters-card" aria-label="材料库存筛选">
        <form class="filter-row erp-list-filters" @submit.prevent="search">
          <ElInput v-model="filters.q" class="filter-control filter-control--search" clearable aria-label="搜索原料名称、规格、拼音或首字母" placeholder="搜索原料名称、规格、拼音或首字母">
            <template #suffix><img class="field-icon" :src="searchIcon" alt="" aria-hidden="true" /></template>
          </ElInput>
          <ElSelect v-if="showCoatingFilter" v-model="filters.processingStatus" class="filter-control filter-control--status" clearable aria-label="喷塑状态" placeholder="喷塑状态：全部" @change="search">
            <ElOption value="METAL" label="未喷塑" />
            <ElOption value="POWDER_COATING" label="已喷塑" />
          </ElSelect>
          <ElSelect v-model="filters.warehouseId" class="filter-control filter-control--warehouse" clearable aria-label="材料仓" placeholder="材料仓：全部" @change="warehouseChanged"><ElOption v-for="item in warehousesForFilter" :key="item.id" :value="item.id" :label="item.warehouse_name" /></ElSelect>
          <ElSelect v-model="filters.zoneId" class="filter-control filter-control--zone" clearable aria-label="库区" placeholder="库区：全部" @change="search"><ElOption v-for="item in zonesForFilter" :key="item.id" :value="item.id" :label="item.zone_name" /></ElSelect>
          <div class="erp-list-filter-actions">
            <ElDropdown v-if="canConfigure">
              <ElButton class="erp-button-motion" :icon="Setting">配置</ElButton>
              <template #dropdown><ElDropdownMenu><ElDropdownItem @click="openConfig('warehouse')">仓库信息</ElDropdownItem><ElDropdownItem @click="openConfig('location')">库区设置</ElDropdownItem></ElDropdownMenu></template>
            </ElDropdown>
            <ElButton class="erp-button-motion" @click="reset">重置</ElButton>
            <ElButton class="erp-button-motion" type="primary" native-type="submit">应用筛选</ElButton>
          </div>
        </form>
      </section>

      </section>
      <section class="inventory-table erp-list-data">
        <nav v-if="bomSections.length" class="stock-sections" aria-label="BOM 分区">
          <button v-for="section in bomSections" :key="section.key" type="button"
            :aria-pressed="activeSection === section.key" @click="selectSection(section.key)">{{ section.label }}</button>
        </nav>
        <div class="table-shell erp-list-table-frame">
          <ElTable :key="`${stockKind}-${activeSection}`" v-loading="loading" :data="rows" height="100%" stripe empty-text="当前分区暂无匹配库存" row-key="inventory_key">
          <ElTableColumn type="index" label="序号" width="66" align="center" class-name="sequence-column" label-class-name="sequence-column" :index="(index: number) => (page - 1) * pageSize + index + 1" />
          <ElTableColumn prop="part_name" label="材料名称" min-width="120" show-overflow-tooltip />
          <ElTableColumn v-for="field in attributeFields" :key="field.key" :label="field.label"
            :min-width="Math.max(88, field.label.length * 13 + 24)" show-overflow-tooltip>
            <template #default="{ row }">{{ attributeText(row, field.key) }}</template>
          </ElTableColumn>
          <ElTableColumn v-if="stockKind === 'SEMI'" label="加工状态" min-width="112"><template #default="{ row }">{{ row.processing_status_label || row.completed_craft || '—' }}</template></ElTableColumn>
          <ElTableColumn label="当前库存" min-width="106" align="right"><template #default="{ row }"><b>{{ formatQuantity(row.inventory_quantity) }}</b></template></ElTableColumn>
          <ElTableColumn prop="unit" label="单位" width="65" align="center" />
          <ElTableColumn v-if="showWeight" label="重量（kg）" min-width="106" align="right"><template #default="{ row }">{{ stockWeightText(row) }}</template></ElTableColumn>
          <ElTableColumn label="材料仓" min-width="150"><template #default="{ row }">{{ row.warehouse_name || '—' }}</template></ElTableColumn>
          <ElTableColumn label="库区" min-width="175"><template #default="{ row }">{{ row.zone_name }}</template></ElTableColumn>
          <ElTableColumn v-if="stockKind === 'RAW'" label="订单追溯" width="126" align="center"><template #default="{ row }"><ElButton link type="primary" @click="openMaterialDetail(row, 'purchases')">采购</ElButton><ElButton link type="primary" @click="openMaterialDetail(row, 'issues')">领用</ElButton></template></ElTableColumn>
          <ElTableColumn v-if="stockKind === 'SEMI' && hasCatalogRows" label="库存详情" width="100" align="center"><template #default="{ row }"><ElButton v-if="row.material_catalog_id" link type="primary" @click="openMaterialDetail(row, 'purchases')">查看</ElButton><span v-else>—</span></template></ElTableColumn>
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
.total-count { color: var(--erp-color-text-secondary); font-size: 13px; white-space: nowrap; }
.stock-kind-switch { flex: none; }
.filter-control--search { width: min(100%, 410px); }
.filter-control--status { width: 150px; }
.filter-control--warehouse { width: 210px; }
.filter-control--zone { width: 170px; }
.field-icon { display: block; width: 16px; height: 16px; opacity: .72; }
.stock-sections { display: flex; flex: none; flex-wrap: wrap; gap: 12px; margin-bottom: 8px; border-bottom: 1px solid var(--erp-color-border-subtle); }
.stock-sections button { min-height: 34px; padding: 0 12px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--erp-color-text-secondary); font: inherit; cursor: pointer; }
.stock-sections button:hover { background: var(--erp-color-selected); }
.stock-sections button[aria-pressed='true'] { border-bottom-color: var(--erp-color-brand); color: var(--erp-color-brand); font-weight: 600; }
.stock-sections button:focus-visible { outline: 2px solid var(--erp-color-brand); outline-offset: -2px; }
.empty-state { padding: 80px; text-align: center; color: var(--erp-color-text-secondary); }
</style>
