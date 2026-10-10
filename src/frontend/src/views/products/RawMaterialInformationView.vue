<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { Filter, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { TableInstance } from 'element-plus'

import { fetchRawMaterialOptions, fetchRawMaterials } from '@/api/rawMaterials'
import RawMaterialInformationDrawer from '@/components/products/RawMaterialInformationDrawer.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  RawMaterialInformation,
  RawMaterialItemType,
  RawMaterialOptions,
  RawMaterialOrdering,
  RawMaterialOrderingField,
} from '@/types/rawMaterial'

interface DrawerExposed { canLeave: () => Promise<boolean> }

const authStore = useAuthStore()
const isSuperuser = computed(() => authStore.user?.is_superuser === true)
const can = (permission: string) => isSuperuser.value || authStore.hasPermission(permission)
const canViewPage = computed(() => can('products.view_rawmaterialinformation'))
const canAdd = computed(() => can('products.add_rawmaterialinformation'))
const canChange = computed(() => can('products.change_rawmaterialinformation'))

const rawMaterials = ref<RawMaterialInformation[]>([])
const options = ref<RawMaterialOptions>({ item_types: [], categories: [], units: [], colors: [], warehouses: [], box_shapes: [] })
const loading = ref(false)
const optionsLoading = ref(false)
const loadError = ref('')
const optionsError = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref<number | null>(null)
const ordering = ref<RawMaterialOrdering>('material_number')
const selectedRows = ref<RawMaterialInformation[]>([])
const tableRef = ref<TableInstance>()
let listRequestId = 0

const filters = reactive({ keyword: '', itemType: '' as RawMaterialItemType | '', category: '', warehouseNumber: '' })
const filterCategories = computed(() => filters.itemType ? options.value.categories.filter((item) => item.item_type === filters.itemType) : options.value.categories)
const boxShapeLabels = computed<Record<string, string>>(() => Object.fromEntries(options.value.box_shapes.map((item) => [item.value, item.label])))
const drawerMounted = ref(false)
const drawerVisible = ref(false)
const drawerMode = ref<'create' | 'edit'>('create')
const editingId = ref('')
const drawerRef = ref<DrawerExposed>()
const returnFocusElement = ref<HTMLElement | null>(null)

function errorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  const first = response?.data?.error?.field_errors ? Object.values(response.data.error.field_errors).flat()[0] : ''
  return first || response?.data?.error?.message || response?.data?.detail || fallback
}

async function loadOptions(): Promise<boolean> {
  optionsLoading.value = true
  optionsError.value = ''
  try {
    options.value = await fetchRawMaterialOptions()
    return true
  } catch (error) {
    optionsError.value = errorMessage(error, '筛选选项加载失败，原料列表仍可使用。')
    return false
  } finally {
    optionsLoading.value = false
  }
}

async function loadRawMaterials(): Promise<'success' | 'stale' | 'error'> {
  const activeRequest = ++listRequestId
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetchRawMaterials({
      page: page.value, page_size: pageSize.value, q: filters.keyword.trim() || undefined,
      item_type: filters.itemType, category_id: filters.category || undefined,
      warehouse_number: filters.warehouseNumber || undefined, ordering: ordering.value,
    })
    if (activeRequest !== listRequestId) return 'stale'
    rawMaterials.value = response.data
    total.value = response.meta.total
    selectedRows.value = []
    await nextTick()
    tableRef.value?.clearSelection()
    return 'success'
  } catch (error) {
    if (activeRequest !== listRequestId) return 'stale'
    loadError.value = errorMessage(error, '原料信息加载失败，请重试。')
    return 'error'
  } finally {
    if (activeRequest === listRequestId) loading.value = false
  }
}

async function reloadAll(): Promise<void> { await Promise.all([loadOptions(), loadRawMaterials()]) }
function applyFilters(): void { page.value = 1; void loadRawMaterials() }
function changeItemType(): void {
  const selected = options.value.categories.find((item) => item.id === filters.category)
  if (selected && selected.item_type !== filters.itemType) filters.category = ''
  applyFilters()
}
function resetFilters(): void {
  filters.keyword = ''; filters.itemType = ''; filters.category = ''; filters.warehouseNumber = ''
  ordering.value = 'material_number'; page.value = 1; syncTableSort(ordering.value); void loadRawMaterials()
}
function handleSortChange(sort: { prop: RawMaterialOrderingField; order: 'ascending' | 'descending' | null }): void {
  if (!sort.prop || !sort.order) return
  const nextOrdering: RawMaterialOrdering = sort.order === 'descending' ? `-${sort.prop}` : sort.prop
  if (nextOrdering === ordering.value) return
  ordering.value = nextOrdering
  page.value = 1
  void loadRawMaterials()
}
function syncTableSort(value: RawMaterialOrdering): void {
  const descending = value.startsWith('-')
  const field = value.replace(/^-/, '')
  const sortableFields = [
    'material_number', 'item_type', 'category_name', 'material_name', 'specification',
    'unit_name', 'color_name', 'warehouse', 'is_packaging_auxiliary', 'box_shape',
  ]
  void nextTick(() => {
    if (sortableFields.includes(field)) tableRef.value?.sort(field, descending ? 'descending' : 'ascending')
    else tableRef.value?.clearSort()
  })
}
function handleToolbarOrdering(value: RawMaterialOrdering): void {
  ordering.value = value; page.value = 1; syncTableSort(value); void loadRawMaterials()
}
function rememberFocus(event: MouseEvent): void { returnFocusElement.value = event.currentTarget as HTMLElement }
function openCreate(event: MouseEvent): void { rememberFocus(event); drawerMounted.value = true; drawerMode.value = 'create'; editingId.value = ''; drawerVisible.value = true }
function openEdit(row: RawMaterialInformation, event: MouseEvent): void { rememberFocus(event); drawerMounted.value = true; drawerMode.value = 'edit'; editingId.value = row.id; drawerVisible.value = true }
async function handleSaved(): Promise<void> {
  if (await loadRawMaterials() === 'error') ElMessage.warning('原料已保存，但列表刷新失败；请点击刷新查看最新结果。')
}
function restoreFocus(): void { void nextTick(() => returnFocusElement.value?.focus()) }
function handlePageSizeChange(): void { page.value = 1; void loadRawMaterials() }
function formatColor(row: RawMaterialInformation): string { return !row.color_name || row.color_name === '/' ? '无颜色（/）' : row.color_name }
function packagingValue(row: RawMaterialInformation): string { return row.item_type === 'MATERIAL' && row.category_name === '包材' ? (row.is_packaging_auxiliary ? '是' : '否') : '—' }
function boxShapeValue(row: RawMaterialInformation): string { return row.item_type === 'MATERIAL' && row.category_name === '包材' ? (boxShapeLabels.value[row.box_shape] || '—') : '—' }

onBeforeRouteLeave(async () => !drawerVisible.value || !drawerRef.value || drawerRef.value.canLeave())
onBeforeUnmount(() => { listRequestId++ })
onMounted(() => { if (canViewPage.value) void reloadAll() })
</script>

<template>
  <section class="raw-page" data-testid="raw-material-information-page">
    <div v-if="!canViewPage" class="state-page" data-testid="raw-material-no-permission"><h1>无权查看原料信息</h1><p>请联系管理员开通“原料信息查看”权限后重试。</p></div>
    <template v-else>
      <header class="page-heading">
        <div class="title-line"><h1>原料信息</h1><span>{{ total === null ? '— 条' : `${total} 条` }}</span></div>
        <ElButton v-if="canAdd" type="primary" :icon="Plus" class="create-button" @click="openCreate">新增原料</ElButton>
      </header>

      <section class="filter-row" aria-label="原料筛选">
        <ElInput v-model="filters.keyword" clearable :prefix-icon="Search" placeholder="搜索品号、品名、规格、颜色" @keyup.enter="applyFilters" />
        <ElSelect v-model="filters.itemType" clearable placeholder="类型：全部" @change="changeItemType"><ElOption v-for="item in options.item_types" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
        <ElSelect v-model="filters.category" clearable filterable placeholder="类别：全部" :loading="optionsLoading" @change="applyFilters"><ElOption v-for="item in filterCategories" :key="item.id" :label="item.category_name" :value="item.id" /></ElSelect>
        <ElSelect v-model="filters.warehouseNumber" clearable filterable placeholder="仓库：全部" :loading="optionsLoading" @change="applyFilters"><ElOption v-for="item in options.warehouses" :key="`${item.warehouse_number}\u0000${item.warehouse_name}`" :label="`${item.warehouse_number} / ${item.warehouse_name}`" :value="item.warehouse_number" /></ElSelect>
        <ElButton :icon="Filter" @click="resetFilters">重置筛选</ElButton>
      </section>

      <section class="list-surface">
        <div class="list-toolbar">
          <span>已选 {{ selectedRows.length }} 项</span>
          <div class="toolbar-actions">
            <ElSelect :model-value="ordering" aria-label="原料排序" @update:model-value="handleToolbarOrdering"><ElOption label="排序：品号升序" value="material_number" /><ElOption label="排序：品号降序" value="-material_number" /><ElOption label="排序：最近更新" value="-updated_at" /><ElOption label="排序：最早更新" value="updated_at" /></ElSelect>
            <ElButton :icon="Refresh" :loading="loading" @click="reloadAll">刷新</ElButton>
          </div>
        </div>
        <div v-if="optionsError" class="inline-warning" role="status"><span>{{ optionsError }}</span><ElButton link type="primary" @click="loadOptions">重试选项</ElButton></div>
        <div v-if="loadError" class="table-state" role="alert"><strong>原料信息加载失败</strong><span>{{ loadError }}</span><ElButton @click="loadRawMaterials">重新加载</ElButton></div>
        <ElTable ref="tableRef" v-else v-loading="loading" :data="rawMaterials" row-key="id" height="100%" class="raw-table" :default-sort="{ prop: 'material_number', order: 'ascending' }" @selection-change="selectedRows = $event" @sort-change="handleSortChange">
          <ElTableColumn type="selection" width="56" />
          <ElTableColumn prop="material_number" label="品号" width="126" sortable="custom" :sort-orders="['ascending', 'descending']" show-overflow-tooltip />
          <ElTableColumn prop="item_type" label="类型" width="114" align="center" header-align="center" sortable="custom" :sort-orders="['ascending', 'descending']"><template #default="{ row }"><span :class="['strong-tag', row.item_type === 'MATERIAL' ? 'is-material' : 'is-semi']">{{ row.item_type_label }}</span></template></ElTableColumn>
          <ElTableColumn prop="category_name" label="类别" width="125" sortable="custom" :sort-orders="['ascending', 'descending']" show-overflow-tooltip><template #default="{ row }"><ElTooltip :content="row.category_name" :disabled="row.category_name.length < 7"><span class="strong-tag is-category">{{ row.category_name }}</span></ElTooltip></template></ElTableColumn>
          <ElTableColumn prop="material_name" label="品名" min-width="202" sortable="custom" :sort-orders="['ascending', 'descending']" show-overflow-tooltip />
          <ElTableColumn prop="specification" label="规格" width="238" sortable="custom" :sort-orders="['ascending', 'descending']" show-overflow-tooltip />
          <ElTableColumn prop="unit_name" label="单位" width="102" sortable="custom" :sort-orders="['ascending', 'descending']" show-overflow-tooltip />
          <ElTableColumn prop="color_name" label="颜色" width="124" sortable="custom" :sort-orders="['ascending', 'descending']" show-overflow-tooltip><template #default="{ row }">{{ formatColor(row) }}</template></ElTableColumn>
          <ElTableColumn prop="warehouse" label="仓库" width="155" sortable="custom" :sort-orders="['ascending', 'descending']" show-overflow-tooltip><template #default="{ row }"><span class="warehouse-cell"><b>{{ row.warehouse_number || '—' }}</b><small>{{ row.warehouse_name || '—' }}</small></span></template></ElTableColumn>
          <ElTableColumn prop="is_packaging_auxiliary" label="包材辅料" width="136" sortable="custom" :sort-orders="['ascending', 'descending']"><template #default="{ row }">{{ packagingValue(row) }}</template></ElTableColumn>
          <ElTableColumn prop="box_shape" label="箱子形状" width="126" sortable="custom" :sort-orders="['ascending', 'descending']"><template #default="{ row }">{{ boxShapeValue(row) }}</template></ElTableColumn>
          <ElTableColumn label="操作" width="130" fixed="right"><template #default="{ row }"><ElButton v-if="canChange" link class="edit-button" @click="openEdit(row, $event)">编辑</ElButton><span v-else>—</span></template></ElTableColumn>
          <template #empty><div class="empty-state"><strong>{{ filters.keyword || filters.itemType || filters.category || filters.warehouseNumber ? '没有符合筛选条件的原料' : '暂无原料信息' }}</strong><span>{{ canAdd ? '可新建第一条原料资料。' : '请调整筛选条件后重试。' }}</span></div></template>
        </ElTable>
        <footer class="pagination-row"><span>{{ total === null ? '共 — 条' : `共 ${total} 条` }}</span><ElPagination v-if="total !== null" v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[50, 100]" layout="sizes, prev, pager, next" @current-change="loadRawMaterials" @size-change="handlePageSizeChange" /></footer>
      </section>

      <RawMaterialInformationDrawer v-if="drawerMounted" ref="drawerRef" v-model="drawerVisible" :mode="drawerMode" :material-id="editingId || undefined" @saved="handleSaved" @closed="restoreFocus" />
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.raw-page { height: 100%; min-width: 0; min-height: 0; margin: 2px 4px 0; display: flex; flex-direction: column; color: token.$crm-text-primary; font-family: token.$crm-font-body; overflow: hidden; }
.page-heading, .title-line, .filter-row, .list-toolbar, .toolbar-actions, .pagination-row { display: flex; align-items: center; }
.page-heading { min-height: 48px; justify-content: space-between; }.title-line { gap: 28px; transform: translateY(6px); }.title-line h1 { margin: 0; font: 700 34px/46px token.$crm-font-display; letter-spacing: -.5px; }.title-line span { color: token.$crm-text-secondary; font-size: 12px; }
.create-button { width: 140px; height: 46px; border-radius: token.$crm-radius-2; border-color: token.$crm-primary; background: token.$crm-primary; }
.filter-row { min-height: 56px; gap: 14px; margin-top: 16px; padding: 8px 0; }.filter-row > * { transform: translateY(-3px); }.filter-row > :deep(.el-input) { width: 218px; }.filter-row > :deep(.el-select) { width: 142px; }.filter-row > :deep(.el-select:nth-of-type(3)) { width: 176px; }.filter-row > :deep(.el-button) { height: 38px; }
.filter-row :deep(.el-input__wrapper), .filter-row :deep(.el-select__wrapper) { min-height: 38px; border-radius: token.$crm-radius-2; box-shadow: 0 0 0 1px token.$crm-border-default inset; }
.list-surface { min-height: 0; flex: 1; display: flex; flex-direction: column; margin-top: 10px; border: 1px solid token.$crm-border-subtle; border-radius: token.$crm-radius-2; background: token.$crm-color-surface; overflow: hidden; }
.list-toolbar { min-height: 64px; justify-content: space-between; padding: 0 10px 0 16px; border-bottom: 1px solid token.$crm-border-subtle; color: token.$crm-text-secondary; font-size: 12px; }.toolbar-actions { gap: 10px; }.toolbar-actions :deep(.el-select) { width: 160px; }.toolbar-actions :deep(.el-select__wrapper), .toolbar-actions :deep(.el-button) { min-height: 38px; border-radius: token.$crm-radius-2; }
.inline-warning { display: flex; align-items: center; gap: 8px; padding: 5px 16px; color: token.$crm-warning; font-size: 12px; background: token.$crm-warning-soft; }
.raw-table { min-height: 0; flex: 1; margin-top: 9px; --el-table-border-color: #{token.$crm-border-subtle}; --el-table-header-bg-color: #{token.$crm-color-subtle}; --el-table-row-hover-bg-color: #{token.$crm-color-row-hover}; --el-table-current-row-bg-color: #{token.$crm-color-selected}; --el-table-tr-bg-color: #{token.$crm-color-surface}; color: token.$crm-text-regular; font-size: 12px; }
.raw-table :deep(th.el-table__cell) { height: 44px; padding: 0; color: token.$crm-text-secondary; font-size: 11px; font-weight: 500; }.raw-table :deep(td.el-table__cell) { height: 53px; padding: 0; }.raw-table :deep(.cell) { padding: 0 16px; }.raw-table :deep(.el-checkbox__inner) { width: 14px; height: 14px; }
.strong-tag { max-width: 100%; min-width: 56px; height: 24px; display: inline-flex; align-items: center; justify-content: center; padding: 0 8px; border-radius: token.$crm-radius-pill; color: #faf9f5; font-size: 12px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.strong-tag.is-material { background: token.$crm-info; }.strong-tag.is-semi { background: #c96442; }.strong-tag.is-category { background: token.$crm-neutral; }
.warehouse-cell { display: flex; flex-direction: column; line-height: 17px; }.warehouse-cell b { font-weight: 500; }.warehouse-cell small { color: token.$crm-text-secondary; font-size: 11px; }.edit-button { color: token.$crm-primary; }
.pagination-row { min-height: 63px; justify-content: space-between; padding: 0 10px 0 16px; border-top: 1px solid token.$crm-border-subtle; color: token.$crm-text-secondary; font-size: 12px; }.pagination-row :deep(.el-pagination) { margin: 0; }.pagination-row :deep(.el-select__wrapper), .pagination-row :deep(.btn-prev), .pagination-row :deep(.btn-next), .pagination-row :deep(.el-pager li) { min-height: 36px; border: 1px solid token.$crm-border-subtle; border-radius: token.$crm-radius-2; background: token.$crm-color-surface; }.pagination-row :deep(.el-pager li.is-active) { border-color: token.$crm-primary; color: token.$crm-primary; }
.table-state { min-height: 300px; flex: 1; display: grid; place-content: center; justify-items: center; gap: 10px; color: token.$crm-text-secondary; }.table-state strong, .empty-state strong { color: token.$crm-text-primary; }.empty-state { min-height: 260px; display: grid; place-content: center; gap: 7px; color: token.$crm-text-secondary; }
.state-page { min-height: 420px; display: grid; place-content: center; text-align: center; }.state-page h1 { margin: 0 0 8px; font-family: token.$crm-font-display; }.state-page p { margin: 0; color: token.$crm-text-secondary; }
</style>
