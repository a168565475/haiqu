<script setup lang="ts">
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
  <section class="material-page" data-testid="material-inventory-page">
    <div v-if="!canView" class="empty-state"><h1>无权查看材料库存</h1><p>请联系管理员开通材料库存查看权限。</p></div>
    <template v-else>
      <header class="page-heading">
        <h1>材料库存</h1><ElRadioGroup v-model="stockKind" class="stock-kind-switch" aria-label="库存性质" @change="stockKindChanged"><ElRadioButton value="RAW">原材料</ElRadioButton><ElRadioButton value="SEMI">半成品</ElRadioButton></ElRadioGroup>
        <span class="total-count">共 {{ total }} 条</span>
        <span class="heading-space" />
        <div class="head-actions">
          <ElButton :icon="Refresh" @click="refresh">刷新</ElButton>
          <ElButton v-if="stockKind === 'SEMI' &amp;&amp; (auth.user?.is_superuser || auth.hasPermission('inventory.view_internalsemifinishedreceipt'))" @click="router.push({name: 'semi-receipt-records'})">入库记录</ElButton><ElButton v-if="stockKind === 'RAW' &amp;&amp; canViewReceipts" @click="router.push({ name: 'material-inbound-details' })">入库明细</ElButton>
          <ElDropdown v-if="canConfigure">
            <ElButton :icon="Setting">配置</ElButton>
            <template #dropdown><ElDropdownMenu><ElDropdownItem @click="openConfig('warehouse')">仓库信息</ElDropdownItem><ElDropdownItem @click="openConfig('location')">库区设置</ElDropdownItem></ElDropdownMenu></template>
          </ElDropdown>
          <ElButton v-if="stockKind === 'SEMI' && canReceiveTubeCoating" type="primary" :icon="Plus" @click="router.push({ name: 'inventory-tube-return' })">喷塑入库</ElButton>
          <ElButton v-if="stockKind === 'RAW' && canReceive" type="primary" :icon="Plus" @click="router.push({ name: 'manual-material-inbound' })">材料入库</ElButton>
        </div>
      </header>

      <section class="surface filters-card" aria-label="材料库存筛选">
        <form class="filter-row" :class="{ 'filter-row--semi': stockKind === 'SEMI' }" @submit.prevent="search">
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
          <ElButton type="primary" native-type="submit">查询</ElButton>
          <ElButton @click="reset">重置</ElButton>
        </form>
      </section>

      <section class="surface inventory-table">
        <header><div><h2>材料库存明细</h2><span>{{ stockKind === 'SEMI' && publicStock ? '公共半成品按实物属性、工艺和单位汇总，不关联采购批次' : publicStock ? '原材料按实物属性和库区汇总' : '原材料按长度、材料仓和库区汇总；半成品按订单、部位和工艺区分' }}</span></div><span>共 {{ total }} 条</span></header>
        <div class="table-shell">
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
        <footer class="page-footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" layout="sizes, prev, pager, next" :total="total" :page-sizes="[20, 50, 100]" @current-change="loadRows" @size-change="page = 1; loadRows()" /></footer>
      </section>
      <WarehouseConfigurationDialogs ref="warehouseConfiguration" warehouse-type="MATERIAL" @saved="loadOptions" />
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.material-page {
  box-sizing: border-box;
  height: calc(100dvh - 92px);
  min-height: 0;
  padding: 28px 28px 26px;
  overflow-y: auto;
  background: var(--erp-page-background);
  color: token.$crm-text-primary;
  font-family: token.$crm-font-body;
}

.page-heading,
.head-actions,
.inventory-table header,
.inventory-table header > div,
.page-footer {
  display: flex;
  align-items: center;
}

.page-heading {
  height: 46px;
  gap: 24px;
}

.page-heading h1 {
  margin: 0;
  font: 700 34px/44px token.$crm-font-display;
  letter-spacing: -1px;
  white-space: nowrap;
}

.stock-kind-switch {
  --el-color-primary: #{token.$crm-primary};
}

.stock-kind-switch :deep(.el-radio-button) {
  --el-radio-button-checked-text-color: #{token.$crm-primary};
  --el-radio-button-checked-bg-color: #{token.$crm-color-selected};
  --el-radio-button-checked-border-color: #{token.$crm-primary};
}

.stock-kind-switch :deep(.el-radio-button__inner) {
  box-sizing: border-box;
  height: 32px;
  padding: 0 14px;
  border-radius: 0;
  outline: 1px solid token.$crm-border-default;
  background: token.$crm-color-surface;
  color: token.$crm-text-primary;
  font-size: 13px;
  line-height: 30px;
}

.stock-kind-switch :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-radius: token.$crm-radius-2 0 0 token.$crm-radius-2;
}

.stock-kind-switch :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-radius: 0 token.$crm-radius-2 token.$crm-radius-2 0;
}

.stock-kind-switch :deep(.el-radio-button.is-active .el-radio-button__inner) {
  outline-color: token.$crm-primary;
}

.stock-kind-switch :deep(.el-radio-button__original-radio:focus-visible + .el-radio-button__inner) {
  outline-color: token.$crm-focus;
}

.total-count {
  color: token.$crm-text-secondary;
  font-size: 13px;
  white-space: nowrap;
}

.heading-space { flex: 1; }

.head-actions {
  gap: 10px;
}

.head-actions :deep(.el-button) {
  height: 32px;
  margin-left: 0;
  border-radius: 5px;
  padding: 0 16px;
  font-size: 13px;
}

.head-actions :deep(.el-button--primary) {
  --el-button-bg-color: #{token.$crm-primary};
  --el-button-border-color: #{token.$crm-primary};
  --el-button-hover-bg-color: #{token.$crm-primary-hover};
  --el-button-hover-border-color: #{token.$crm-primary-hover};
}

.surface {
  border: 1px solid token.$crm-border-default;
  border-radius: 5px;
  background: token.$crm-color-surface;
}

.filters-card {
  box-sizing: border-box;
  height: 60px;
  padding: 13px 16px;
  margin-top: 10px;
}

.filter-row {
  display: grid;
  height: 32px;
  grid-template-columns: minmax(260px, 410px) 150px 210px 170px 82px 82px;
  gap: 14px;
  align-items: stretch;
}

.filter-row--semi {
  grid-template-columns: minmax(260px, 410px) 150px 150px 210px 170px 82px 82px;
}

.filter-control {
  width: 100%;
  height: 32px;
}

.filter-control :deep(.el-input__wrapper),
.filter-control :deep(.el-select__wrapper),
.filter-row :deep(.el-button) {
  min-height: 32px;
  border-radius: token.$crm-radius-2;
}

.filter-control :deep(.el-input__wrapper),
.filter-control :deep(.el-select__wrapper) {
  padding: 0 12px;
  background: token.$crm-color-surface;
  box-shadow: 0 0 0 1px token.$crm-border-default inset;
}

.filter-control :deep(.el-input__wrapper:hover),
.filter-control :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px token.$crm-border-strong inset;
}

.filter-control :deep(.el-input__wrapper.is-focus),
.filter-control :deep(.el-select__wrapper.is-focused) {
  box-shadow: 0 0 0 1px token.$crm-focus inset, 0 0 0 2px rgba(56, 152, 236, 0.18);
}

.filter-control :deep(.el-input__inner),
.filter-control :deep(.el-select__placeholder),
.filter-control :deep(.el-select__selected-item) {
  color: token.$crm-text-secondary;
  font-size: 12px;
  line-height: 18px;
}

.filter-control :deep(.el-input__inner::placeholder) {
  color: token.$crm-text-muted;
}

.field-icon {
  display: block;
  width: 16px;
  height: 16px;
  opacity: 0.72;
}

.filter-row :deep(.el-button) {
  height: 32px;
  margin-left: 0;
  padding: 0 16px;
  font-size: 13px;
}

.filter-row :deep(.el-button--primary) {
  --el-button-bg-color: #{token.$crm-primary};
  --el-button-border-color: #{token.$crm-primary};
  --el-button-hover-bg-color: #{token.$crm-primary-hover};
  --el-button-hover-border-color: #{token.$crm-primary-hover};
}

.inventory-table {
  display: flex;
  height: calc(100dvh - 244px);
  min-height: 418px;
  flex-direction: column;
  overflow: hidden;
}

.inventory-table header {
  flex: 0 0 51px;
  justify-content: space-between;
  padding: 0 16px;
}

.inventory-table header > div {
  gap: 34px;
  min-width: 0;
}

.inventory-table h2 {
  margin: 0;
  font-size: 16px;
  line-height: 19px;
  white-space: nowrap;
}

.inventory-table header span {
  overflow: hidden;
  color: token.$crm-text-secondary;
  font-size: 12px;
  line-height: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-shell {
  flex: 1;
  min-height: 0;
  margin: 0;
  overflow: hidden;
}

.table-shell :deep(.el-table) {
  --el-table-border-color: #dad5ca;
  --el-table-header-bg-color: #f1ede4;
  --el-table-row-hover-bg-color: #fff6ea;
  color: token.$crm-text-primary;
  background: transparent;
  font-size: 12px;
}

.table-shell :deep(.el-table::before),
.table-shell :deep(.el-table__inner-wrapper::before) {
  background-color: #dad5ca;
}

.table-shell :deep(.el-table__header th.el-table__cell) {
  height: 44px;
  padding: 0;
  background: #f1ede4;
  color: token.$crm-text-primary;
  font-weight: 500;
}

.table-shell :deep(.el-table__body td.el-table__cell) {
  height: 58px;
  padding: 0;
  border-bottom-color: #dad5ca;
}

.table-shell :deep(.el-table__body tr:nth-child(odd) td.el-table__cell) {
  background: #fdfcf7;
}

.table-shell :deep(.el-table__body tr:nth-child(even) td.el-table__cell) {
  background: #faf9f5;
}

.table-shell :deep(.el-table .cell) {
  padding-right: 8px;
  padding-left: 8px;
  font-size: 12px;
  line-height: 18px;
}

.table-shell :deep(.stock-quantity) {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-shell :deep(.sequence-column .cell) {
  padding-right: 8px !important;
  padding-left: 8px !important;
  white-space: nowrap !important;
}

.page-footer {
  box-sizing: border-box;
  height: 48px;
  flex: 0 0 48px;
  justify-content: space-between;
  margin-top: 0;
  padding: 0 14px;
  border-top: 1px solid token.$crm-border-default;
  color: token.$crm-text-secondary;
  background: token.$crm-color-surface;
  font-size: 12px;
}

.page-footer :deep(.el-pagination) {
  --el-pagination-button-width: 38px;
  --el-pagination-button-height: 32px;
  --el-pagination-hover-color: #{token.$crm-primary};
  height: 32px;
  gap: 10px;
}

.page-footer :deep(.el-pagination__sizes) {
  width: 136px;
  margin-right: 16px;
}

.page-footer :deep(.el-pagination__sizes .el-select) {
  width: 136px;
}

.page-footer :deep(.el-pagination__sizes .el-select__wrapper) {
  min-height: 32px;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  box-shadow: 0 0 0 1px token.$crm-border-default inset;
}

.page-footer :deep(.btn-prev),
.page-footer :deep(.btn-next),
.page-footer :deep(.el-pager li) {
  min-width: 38px;
  width: 38px;
  height: 32px;
  margin: 0;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
  font-size: 13px;
  font-weight: 500;
}

.page-footer :deep(.el-pager) {
  gap: 10px;
}

.page-footer :deep(.el-pager li.is-active) {
  border-color: token.$crm-primary;
  color: token.$crm-text-primary;
  background: token.$crm-color-surface;
}

.page-footer :deep(.btn-prev:disabled),
.page-footer :deep(.btn-next:disabled) {
  color: token.$crm-text-muted;
  opacity: 0.55;
}

.empty-state {
  padding: 80px;
  text-align: center;
  color: token.$crm-text-secondary;
}

@media (max-width: 1400px) {
  .filter-row {
    grid-template-columns: minmax(260px, 1fr) 140px minmax(180px, 210px) 150px 82px 82px;
  }

  .filter-row--semi {
    grid-template-columns: minmax(260px, 1fr) 140px 140px minmax(180px, 210px) 150px 82px 82px;
  }
}
</style>
