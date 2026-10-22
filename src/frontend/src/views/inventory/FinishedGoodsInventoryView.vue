<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { useRoute, useRouter } from 'vue-router'
import FinishedReceiptRecordsPanel from './FinishedReceiptRecordsPanel.vue'
import AssemblyPlanPicker from './AssemblyPlanPicker.vue'
import { fetchFinishedLocations } from '@/api/finishedReceipts'
import type { FinishedLocation } from '@/types/finishedReceipts'
import '@/styles/finishedReceipts.scss'
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onMounted, reactive, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  fetchFinishedGoodsInventory, fetchFinishedGoodsFilterOptions, fetchLocations,
  fetchVersioned, fetchWarehouses, fetchZones, saveLocation, saveWarehouse, saveZone,
} from '@/api/inventory'
import type { MaterialReceivingOptions } from '@/types/inventory'
import type { FinishedGoodsInventoryRow, RecordStatus, Warehouse, WarehouseLocation, WarehouseType, WarehouseZone } from '@/types/inventory'

const route = useRoute()
const router = useRouter()
const stockTab = ref(route.query.tab === 'records' ? 'records' : 'stock')
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
function switchStockTab(value: string) { stockTab.value = value; selectedRows.value = []; if(value === 'stock') void loadRows() }
const auth = useAuthStore()
const loading = ref(false); const errorMessage = ref(''); const rows = ref<FinishedGoodsInventoryRow[]>([])
const page = ref(1); const pageSize = ref(50); const total = ref(0); const keyword = ref(''); const warehouseFilter = ref(''); const zoneFilter = ref('')
const filterOptions = ref<MaterialReceivingOptions>({ warehouses: [], zones: [] })
const selectedRows = ref<FinishedGoodsInventoryRow[]>([])
const warehouseVisible = ref(false); const locationVisible = ref(false)
const warehouses = ref<Warehouse[]>([]); const zones = ref<WarehouseZone[]>([]); const locations = ref<WarehouseLocation[]>([])
const configLoading = ref(false); const configKeyword = ref('')
const locationConfigTab = ref<'locations' | 'zones'>('locations')
const editVisible = ref(false); const editKind = ref<'warehouse' | 'zone' | 'location'>('warehouse'); const editId = ref<string | null>(null); const editEtag = ref(''); const editLoading = ref(false)
const warehouseForm = reactive({ warehouse_number: '', warehouse_name: '', warehouse_type: 'FINISHED' as WarehouseType, address: '', status: 'ACTIVE' as RecordStatus, responsible_person_name: '', contact_phone: '' })
const zoneForm = reactive({ warehouse: '', zone_name: '', status: 'ACTIVE' as RecordStatus })
const locationForm = reactive({ zone: '', location_number: '', capacity_box_slots: null as number | null, status: 'ACTIVE' as RecordStatus })
const canInbound = computed(() => auth.hasPermission('inventory.add_finishedgoodsreceipt'))
const canOutbound = computed(() => auth.hasPermission('inventory.add_finishedgoodsoutbound'))
const canConfigure = computed(() => auth.hasPermission('inventory.view_warehouse') || auth.hasPermission('inventory.view_warehouselocation'))
const finishedWarehouses = computed(() => warehouses.value.filter(item => item.warehouse_type === 'FINISHED'))
const finishedWarehouseIds = computed(() => new Set(finishedWarehouses.value.map(item => item.id)))
const finishedZones = computed(() => zones.value.filter(item => finishedWarehouseIds.value.has(item.warehouse)))
const finishedZoneIds = computed(() => new Set(finishedZones.value.map(item => item.id)))
const finishedLocations = computed(() => locations.value.filter(item => finishedZoneIds.value.has(item.zone)))
const configLocations = computed(() => finishedLocations.value.filter(item => !configKeyword.value || `${item.warehouse_number}${item.warehouse_name}${item.zone_name}${item.location_number}${item.unique_key}`.toLowerCase().includes(configKeyword.value.toLowerCase())))
const configWarehouses = computed(() => finishedWarehouses.value.filter(item => !configKeyword.value || `${item.warehouse_number}${item.warehouse_name}${item.address}`.toLowerCase().includes(configKeyword.value.toLowerCase())))
const configZones = computed(() => finishedZones.value.filter(item => !configKeyword.value || `${item.warehouse_number}${item.warehouse_name}${item.zone_name}`.toLowerCase().includes(configKeyword.value.toLowerCase())))

const warehouseTypeColors: Record<WarehouseType, string> = {
  MATERIAL: 'var(--erp-tag-warning-background)',
  SEMI_FINISHED: 'var(--erp-tag-success-background)',
  DEFECTIVE: 'var(--erp-tag-info-background)',
  FINISHED: 'var(--erp-tag-brand-background)',
}
function warehouseTypeTagStyle(type: WarehouseType) { const color = warehouseTypeColors[type]; return { backgroundColor: color, borderColor: color, color: 'var(--erp-color-text-inverse)' } }
function statusTagStyle(status: RecordStatus) { const color = status === 'ACTIVE' ? 'var(--erp-tag-success-background)' : 'var(--erp-tag-neutral-background)'; return { backgroundColor: color, borderColor: color, color: 'var(--erp-color-text-inverse)' } }
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

async function openConfig(kind: 'warehouse' | 'location') {
  configKeyword.value = ''; configLoading.value = true
  if (kind === 'warehouse') warehouseVisible.value = true; else locationVisible.value = true
  try { [warehouses.value, zones.value, locations.value] = await Promise.all([fetchWarehouses(), fetchZones(), fetchLocations()]) }
  catch (error) { ElMessage.error(message(error, '配置数据加载失败。')) }
  finally { configLoading.value = false }
}
async function openEditor(kind: 'warehouse' | 'zone' | 'location', item?: Warehouse | WarehouseZone | WarehouseLocation) {
  editKind.value = kind; editId.value = item?.id || null; editEtag.value = ''
  Object.assign(warehouseForm, { warehouse_number: '', warehouse_name: '', warehouse_type: 'FINISHED', address: '', status: 'ACTIVE', responsible_person_name: '', contact_phone: '' })
  Object.assign(zoneForm, { warehouse: finishedWarehouses.value[0]?.id || '', zone_name: '', status: 'ACTIVE' })
  Object.assign(locationForm, { zone: finishedZones.value[0]?.id || '', location_number: '', capacity_box_slots: null, status: 'ACTIVE' })
  if (item) {
    const resource = kind === 'warehouse' ? `warehouses/${item.id}/` : kind === 'zone' ? `warehouse-zones/${item.id}/` : `warehouse-locations/${item.id}/`
    const versioned = await fetchVersioned<Warehouse | WarehouseZone | WarehouseLocation>(resource); editEtag.value = versioned.etag
    if (kind === 'warehouse') {
      const value = versioned.data as Warehouse
      Object.assign(warehouseForm, { warehouse_number: value.warehouse_number, warehouse_name: value.warehouse_name, warehouse_type: value.warehouse_type, address: value.address, status: value.status, responsible_person_name: value.responsible_person_name, contact_phone: value.contact_phone })
    }
    if (kind === 'zone') {
      const value = versioned.data as WarehouseZone
      Object.assign(zoneForm, { warehouse: value.warehouse, zone_name: value.zone_name, status: value.status })
    }
    if (kind === 'location') {
      const value = versioned.data as WarehouseLocation
      Object.assign(locationForm, { zone: value.zone, location_number: value.location_number, capacity_box_slots: value.capacity_box_slots, status: value.status })
    }
  }
  editVisible.value = true
}
async function submitEditor() {
  editLoading.value = true
  try {
    if (editKind.value === 'warehouse') await saveWarehouse(editId.value, warehouseForm, editEtag.value)
    else if (editKind.value === 'zone') await saveZone(editId.value, zoneForm, editEtag.value)
    else await saveLocation(editId.value, locationForm, editEtag.value)
    editVisible.value = false; ElMessage.success('保存成功。'); await openConfig(editKind.value === 'warehouse' ? 'warehouse' : 'location'); await loadOptions()
  } catch (error) { ElMessage.error(message(error, '保存失败，请检查必填项。')) } finally { editLoading.value = false }
}

async function openOutbound() {
  if (!selectedRows.value.length) { ElMessage.warning('请先勾选需要出库的库存。'); return }
  if (new Set(selectedRows.value.map(row => row.task_number)).size !== 1) { ElMessage.warning('请只选择同一生产任务单的库存。'); return }
  void router.push({ name: 'finished-goods-outbound-new', query: { receipt_ids: selectedRows.value.flatMap(item => item.receipt_ids).join(',') } })
}

onMounted(() => { void Promise.all([loadRows(), loadOptions()]) })
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
    <FinishedReceiptRecordsPanel v-if="stockTab==='records'">
      <template #heading><header class="fg-heading erp-list-heading"><h1>成品库存</h1></header></template>
      <template #actions><div class="fg-heading-actions"><ElDropdown v-if="canConfigure" trigger="click" @command="openConfig"><ElButton class="erp-button-motion">仓库配置</ElButton><template #dropdown><ElDropdownMenu><ElDropdownItem command="warehouse">仓库信息</ElDropdownItem><ElDropdownItem command="location">库位信息</ElDropdownItem></ElDropdownMenu></template></ElDropdown><ElButton class="erp-button-motion" v-if="canInbound" type="primary" @click="planPickerVisible=true">成品入库</ElButton></div></template>
      <template #default>
      <nav class="fg-tabs erp-list-tabs" aria-label="成品库存视图"><button @click="switchStockTab('stock')">库存汇总</button><button class="active" @click="switchStockTab('records')">入库记录</button><button @click="router.push({name:'finished-goods-outbounds'})">出库记录</button></nav>
      </template>
    </FinishedReceiptRecordsPanel>
    <div v-else class="fg-stock-body erp-list-data">

      <div class="fg-toolbar erp-list-toolbar"><nav class="fg-tabs erp-list-tabs" aria-label="成品库存视图"><button :class="{active:stockTab==='stock'}" @click="switchStockTab('stock')">库存汇总</button><button :class="{active:stockTab==='records'}" @click="switchStockTab('records')">入库记录</button><button @click="router.push({name:'finished-goods-outbounds'})">出库记录</button></nav><div class="fg-stock-selection"><span class="fg-muted">已选 {{selectedRows.length}} 条</span><ElButton class="erp-button-motion" v-if="canOutbound" :disabled="!selectedRows.length" @click="openOutbound">批量出库</ElButton></div></div>
      <ElAlert v-if="errorMessage" :title="errorMessage" type="error" :closable="false"/>
      <section class="fg-stock-table" v-loading="loading"><div class="erp-list-table-frame"><div class="fg-table-scroll erp-list-table-scroll"><table class="fg-table erp-list-native-table erp-list-native-table--nowrap"><colgroup><col v-for="(width,i) in [50,130,80,120,160,95,165,90,95,65,105,75,90,95,135,120]" :key="i" :style="{width:width+'px'}"></colgroup><thead><tr><th class="center selection-cell"><input type="checkbox" aria-label="全选库存" :checked="rows.length>0&&selectedRows.length===rows.length" @change="selectedRows=($event.target as HTMLInputElement).checked?[...rows]:[]"></th><th v-for="name in ['生产任务单号','类别','产品编码','品名','货号','规格','颜色','当前库存','单位','仓库','库区','在库记录','占用箱位','最近入库日期','操作']" :key="name">{{name}}</th></tr></thead><tbody><tr v-for="row in rows" :key="row.inventory_key" :class="{selected:selectedRows.some(r=>r.inventory_key===row.inventory_key)}"><td class="center selection-cell"><input type="checkbox" :aria-label="'选择'+row.task_number+row.product_number+row.actual_color+row.zone_name" :checked="selectedRows.some(r=>r.inventory_key===row.inventory_key)" @change="toggleStock(row,($event.target as HTMLInputElement).checked)"></td><td>{{row.task_number||'—'}}</td><td>{{row.category||'—'}}</td><td :title="row.product_code">{{row.product_code||'—'}}</td><td :title="row.product_name">{{row.product_name}}</td><td>{{row.item_number||'—'}}</td><td :title="row.specification">{{row.specification||'—'}}</td><td>{{row.actual_color||'—'}}</td><td class="num">{{Number(row.inventory_quantity).toLocaleString()}}</td><td>{{row.unit_name}}</td><td>{{row.warehouse_name}}</td><td>{{row.zone_name}}</td><td class="num">{{row.batch_count}}</td><td class="num">{{row.occupied_box_slots??'未计算'}}</td><td>{{row.latest_inbound_time?new Date(row.latest_inbound_time).toLocaleDateString('sv-SE'):'—'}}</td><td><ElButton link type="primary" @click="openStockDetail(row)">库存详情</ElButton></td></tr></tbody></table><div class="fg-empty" v-if="!loading&&!rows.length">暂无符合条件的成品库存</div></div></div><footer class="fg-pager erp-list-footer"><span>共 {{total}} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20,50,100]" layout="sizes, prev, pager, next" @current-change="loadRows" @size-change="search"/></footer></section>
    </div>
    <AssemblyPlanPicker v-model="planPickerVisible"/>
    <ElDialog v-model="stockDetailVisible" title="成品库存 · 库位详情" :width="1180" :height="660" class="fg-window" destroy-on-close><div v-loading="stockDetailLoading"><ElAlert v-if="stockDetailError" :title="stockDetailError" type="error"/><template v-if="stockDetailRow"><div class="fg-detail-title"><b>{{stockDetailRow.product_name}}</b><span class="fg-muted">当前库存 {{stockDetailRow.inventory_quantity}} {{stockDetailRow.unit_name}}</span></div><dl class="fg-detail-fields"><div v-for="([key,value]) in [['生产任务单号',stockDetailRow.task_number],['产品编码',stockDetailRow.product_code],['货号',stockDetailRow.item_number],['类别',stockDetailRow.category],['规格',stockDetailRow.specification],['颜色',stockDetailRow.actual_color],['仓库 / 库区',stockDetailRow.warehouse_name+' / '+stockDetailRow.zone_name]]" :key="key"><dt>{{key}}</dt><dd>{{value||'—'}}</dd></div></dl><h2 class="fg-detail-heading">存放库位</h2><div class="fg-table-card"><table class="fg-table compact"><thead><tr><th>库位</th><th>当前数量</th><th>单位</th><th>占用箱位</th></tr></thead><tbody><tr v-for="l in stockLocations" :key="l.location_id"><td>{{l.location_number}}</td><td>{{l.quantity}}</td><td>{{stockDetailRow.unit_name}}</td><td>{{l.slots??'未计算'}}{{l.unknown_packaging&&l.slots!=null?'（部分未计算）':''}}</td></tr></tbody></table></div><p class="fg-helper">库存按生产任务单汇总；本详情仅显示当前任务单的存放库位。</p></template></div><template #footer><ElButton @click="stockDetailVisible=false">关闭</ElButton></template></ElDialog>
    <ElDialog v-model="warehouseVisible" title="仓库信息" width="calc(100vw - 32px)" height="calc(100vh - 32px)" destroy-on-close class="inventory-fullscreen inventory-config-dialog"><section class="fullscreen-body config-body" v-loading="configLoading"><div class="fullscreen-toolbar"><ElInput v-model="configKeyword" clearable placeholder="搜索仓库号、仓库名称或地址" /><ElButton v-if="auth.hasPermission('inventory.add_warehouse')" type="primary" :icon="Plus" @click="openEditor('warehouse')">新增仓库</ElButton></div><ElTable :data="configWarehouses" border height="100%"><ElTableColumn prop="warehouse_number" label="仓库号" min-width="110" /><ElTableColumn prop="warehouse_name" label="仓库名称" min-width="150" /><ElTableColumn prop="warehouse_type_display" label="仓库类型" min-width="120"><template #default="{ row }"><ElTag effect="dark" :style="warehouseTypeTagStyle(row.warehouse_type)">{{ row.warehouse_type_display }}</ElTag></template></ElTableColumn><ElTableColumn prop="address" label="仓库地址" min-width="150" /><ElTableColumn prop="status_display" label="仓库状态" min-width="100"><template #default="{ row }"><ElTag effect="dark" :style="statusTagStyle(row.status)">{{ row.status_display }}</ElTag></template></ElTableColumn><ElTableColumn prop="responsible_person_name" label="仓库负责人" min-width="120"><template #default="{ row }"><span class="warehouse-owner">{{ row.responsible_person_name || '—' }}</span></template></ElTableColumn><ElTableColumn prop="contact_phone" label="负责人联系电话" min-width="150" /><ElTableColumn prop="zone_count" label="库区数" min-width="90" /><ElTableColumn prop="location_count" label="库位数" min-width="90" /><ElTableColumn prop="capacity_box_slots_total" label="总箱位" min-width="100"><template #default="{ row }">{{ row.capacity_box_slots_total ?? '未设置' }}</template></ElTableColumn><ElTableColumn prop="occupied_box_slots" label="已占箱位" min-width="100" /><ElTableColumn label="操作" width="90" fixed="right"><template #default="{ row }"><ElButton v-if="auth.hasPermission('inventory.change_warehouse')" link type="primary" @click="openEditor('warehouse', row)">编辑</ElButton></template></ElTableColumn></ElTable></section></ElDialog>

    <ElDialog v-model="locationVisible" title="库位信息" width="calc(100vw - 32px)" height="calc(100vh - 32px)" destroy-on-close class="inventory-fullscreen inventory-config-dialog"><section class="fullscreen-body config-body" v-loading="configLoading"><div class="fullscreen-toolbar"><ElInput v-model="configKeyword" clearable placeholder="搜索仓库、库区、库位或唯一校验值" /><div><ElButton v-if="auth.hasPermission('inventory.add_warehousezone')" @click="openEditor('zone')">新增库区</ElButton><ElButton v-if="auth.hasPermission('inventory.add_warehouselocation')" type="primary" :icon="Plus" @click="openEditor('location')">新增库位</ElButton></div></div><ElTabs v-model="locationConfigTab"><ElTabPane label="库位列表" name="locations"><ElTable :data="configLocations" border height="100%"><ElTableColumn prop="warehouse_number" label="仓库号" min-width="100" /><ElTableColumn prop="warehouse_name" label="仓库名称" min-width="130" /><ElTableColumn prop="zone_name" label="库区" min-width="100" /><ElTableColumn prop="location_number" label="库位号" min-width="130" /><ElTableColumn prop="capacity_box_slots" label="仓库库容（箱位）" min-width="150"><template #default="{ row }">{{ row.capacity_box_slots ?? '未设置' }}</template></ElTableColumn><ElTableColumn prop="occupied_box_slots" label="已占箱位" min-width="100" /><ElTableColumn prop="remaining_box_slots" label="剩余箱位" min-width="100"><template #default="{ row }">{{ row.remaining_box_slots ?? '不限' }}</template></ElTableColumn><ElTableColumn prop="unique_key" label="库位号唯一校验" min-width="220" /><ElTableColumn prop="warehouse_type_display" label="仓库类型" min-width="120"><template #default="{ row }"><ElTag effect="dark" :style="warehouseTypeTagStyle(row.warehouse_type)">{{ row.warehouse_type_display }}</ElTag></template></ElTableColumn><ElTableColumn prop="status_display" label="状态" min-width="90"><template #default="{ row }"><ElTag effect="dark" :style="statusTagStyle(row.status)">{{ row.status_display }}</ElTag></template></ElTableColumn><ElTableColumn label="操作" width="90" fixed="right"><template #default="{ row }"><ElButton v-if="auth.hasPermission('inventory.change_warehouselocation')" link type="primary" @click="openEditor('location', row)">编辑</ElButton></template></ElTableColumn></ElTable></ElTabPane><ElTabPane label="库区列表" name="zones"><ElTable :data="configZones" border height="100%"><ElTableColumn prop="warehouse_number" label="仓库号" min-width="120" /><ElTableColumn prop="warehouse_name" label="仓库名称" min-width="180" /><ElTableColumn prop="zone_name" label="库区" min-width="160" /><ElTableColumn prop="status_display" label="状态" min-width="100"><template #default="{ row }"><ElTag effect="dark" :style="statusTagStyle(row.status)">{{ row.status_display }}</ElTag></template></ElTableColumn><ElTableColumn prop="location_count" label="库位数" min-width="100" /><ElTableColumn prop="capacity_box_slots_total" label="总箱位" min-width="120"><template #default="{ row }">{{ row.capacity_box_slots_total ?? '未设置' }}</template></ElTableColumn><ElTableColumn prop="occupied_box_slots" label="已占箱位" min-width="120" /><ElTableColumn label="操作" width="90" fixed="right"><template #default="{ row }"><ElButton v-if="auth.hasPermission('inventory.change_warehousezone')" link type="primary" @click="openEditor('zone', row)">编辑</ElButton></template></ElTableColumn></ElTable></ElTabPane></ElTabs></section></ElDialog>

    <ElDialog v-model="editVisible" :title="`${editId ? '编辑' : '新增'}${editKind === 'warehouse' ? '仓库' : editKind === 'zone' ? '库区' : '库位'}`" width="620px" append-to-body destroy-on-close><ElForm label-position="top"><template v-if="editKind === 'warehouse'"><ElFormItem label="仓库号" required><ElInput v-model="warehouseForm.warehouse_number" /></ElFormItem><ElFormItem label="仓库名称" required><ElInput v-model="warehouseForm.warehouse_name" /></ElFormItem><ElFormItem label="仓库类型" required><ElSelect v-model="warehouseForm.warehouse_type" disabled><ElOption label="成品仓" value="FINISHED" /></ElSelect></ElFormItem><ElFormItem label="仓库地址"><ElInput v-model="warehouseForm.address" /></ElFormItem><ElFormItem label="仓库负责人"><ElInput v-model="warehouseForm.responsible_person_name" /></ElFormItem><ElFormItem label="负责人联系电话"><ElInput v-model="warehouseForm.contact_phone" /></ElFormItem><ElFormItem label="状态"><ElRadioGroup v-model="warehouseForm.status"><ElRadio value="ACTIVE">正常</ElRadio><ElRadio value="DISABLED">停用</ElRadio></ElRadioGroup></ElFormItem></template><template v-else-if="editKind === 'zone'"><ElFormItem label="仓库" required><ElSelect v-model="zoneForm.warehouse"><ElOption v-for="item in finishedWarehouses" :key="item.id" :label="`${item.warehouse_number} · ${item.warehouse_name}`" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="库区" required><ElInput v-model="zoneForm.zone_name" /></ElFormItem><ElFormItem label="状态"><ElRadioGroup v-model="zoneForm.status"><ElRadio value="ACTIVE">正常</ElRadio><ElRadio value="DISABLED">停用</ElRadio></ElRadioGroup></ElFormItem></template><template v-else><ElFormItem label="库区" required><ElSelect v-model="locationForm.zone" filterable><ElOption v-for="item in finishedZones" :key="item.id" :label="`${item.warehouse_number} · ${item.zone_name}`" :value="item.id" /></ElSelect></ElFormItem><ElFormItem label="库位号" required><ElInput v-model="locationForm.location_number" /></ElFormItem><ElFormItem label="库容（箱位）"><ElInputNumber v-model="locationForm.capacity_box_slots" :min="1" /></ElFormItem><ElFormItem label="状态"><ElRadioGroup v-model="locationForm.status"><ElRadio value="ACTIVE">正常</ElRadio><ElRadio value="DISABLED">停用</ElRadio></ElRadioGroup></ElFormItem></template></ElForm><template #footer><ElButton @click="editVisible = false">取消</ElButton><ElButton type="primary" :loading="editLoading" @click="submitEditor">保存</ElButton></template></ElDialog>
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
.inventory-page{box-sizing:border-box;height:calc(100dvh - 84px);min-width:1450px;display:flex;flex-direction:column;gap:16px;padding:24px 28px 20px;background:var(--erp-page-background);color:var(--erp-color-text-primary)}.page-head,.head-actions,.toolbar,.pager,.fullscreen-toolbar{display:flex;align-items:center}.page-head{justify-content:space-between}.page-head h1,.fullscreen-toolbar h2{margin:0;font-size:28px}.page-head p,.fullscreen-toolbar p{margin:4px 0 0;color:var(--erp-color-text-secondary)}.head-actions{gap:10px}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.summary-grid article{padding:14px 18px;border:1px solid var(--erp-color-border);border-radius:10px;background:var(--erp-color-surface)}.summary-grid span{display:block;color:var(--erp-color-text-secondary);font-size:13px}.summary-grid strong{display:block;margin-top:6px;font-size:24px}.toolbar{gap:10px}.toolbar :deep(.el-input){width:390px}.toolbar :deep(.el-select){width:180px}.table-card{flex:1;min-height:0;border:1px solid var(--erp-table-grid);border-radius:10px;overflow:hidden;background:var(--erp-table-body-fill)}.pager{justify-content:space-between;color:var(--erp-color-text-secondary)}.form-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:0 18px;margin-top:18px}.span-2{grid-column:span 2}.outbound-common{display:grid;grid-template-columns:1fr 1.5fr 2fr;gap:18px;margin-top:18px}.fullscreen-body{box-sizing:border-box;height:calc(100vh - 70px);padding:0 28px 24px}.fullscreen-toolbar{justify-content:space-between;height:76px}.fullscreen-toolbar :deep(.el-input){width:430px}:global(.inventory-fullscreen .el-dialog__body){padding:0}:global(.inventory-fullscreen .el-dialog__header){margin:0;padding:18px 28px;border-bottom:1px solid var(--erp-color-border-subtle)}:deep(.el-input-number){width:100%}:deep(.el-select){width:100%}:deep(.el-cascader){width:100%}
.warehouse-owner{color:var(--erp-color-info);font-weight:600}
.fullscreen-body{height:100%;min-height:0}
:global(.app-window-dialog.inventory-fullscreen .el-dialog__body){height:auto;flex:1 1 auto;min-height:0;padding:0}
.fullscreen-body.config-body{display:flex;flex:1;flex-direction:column;gap:12px;height:auto;min-width:0;padding:12px 28px 16px}
.config-body > .fullscreen-toolbar{flex:none;flex-wrap:wrap;gap:8px 12px;height:auto;min-height:32px;margin:0}
.config-body > .fullscreen-toolbar :deep(.el-input){flex:1 1 180px;width:auto;min-width:0;max-width:430px}
.config-body > .fullscreen-toolbar > div:not(.el-input){display:flex;flex:none;gap:8px;margin-left:auto}
.config-body > .fullscreen-toolbar :deep(.el-button){flex:none}
.config-body > .fullscreen-toolbar :deep(.el-button + .el-button){margin-left:0}
.config-body > :deep(.el-table),.config-body > :deep(.el-tabs){flex:1;min-height:0;margin:0}
.config-body > :deep(.el-tabs){display:flex;flex-direction:column}
.config-body :deep(.el-tabs__header){flex:none;margin:0 0 12px}
.config-body :deep(.el-tabs__content){flex:1;min-height:0}
.config-body :deep(.el-tab-pane){height:100%;min-height:0}
:global(.app-window-dialog.inventory-config-dialog .el-dialog__body){display:flex;overflow:hidden}
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
