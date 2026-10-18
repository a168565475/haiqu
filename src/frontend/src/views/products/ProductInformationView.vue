<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { Filter, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { TableInstance } from 'element-plus'

import { fetchProductOptions, fetchProducts } from '@/api/products'
import ProductInformationDrawer from '@/components/products/ProductInformationDrawer.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  ProductInformation,
  ProductOptions,
  ProductOrdering,
  ProductOrderingField,
  ProductScale,
  ProductStatus,
} from '@/types/product'

interface DrawerExposed { canLeave: () => Promise<boolean> }

const authStore = useAuthStore()
const isSuperuser = computed(() => authStore.user?.is_superuser === true)
const can = (permission: string) => isSuperuser.value || authStore.hasPermission(permission)
const canViewPage = computed(() => can('products.view_productinformation'))
const canAdd = computed(() => can('products.add_productinformation'))
const canChange = computed(() => can('products.change_productinformation'))

const products = ref<ProductInformation[]>([])
const options = ref<ProductOptions>({ categories: [], units: [], items: [] })
const loading = ref(false)
const optionsLoading = ref(false)
const loadError = ref('')
const optionsError = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref<number | null>(null)
const ordering = ref<ProductOrdering>('product_number')
const tableRef = ref<TableInstance>()
let listRequestId = 0

const filters = reactive({ keyword: '', category: '', scale: '' as ProductScale | '', status: '' as ProductStatus | '' })
const drawerVisible = ref(false)
const drawerMounted = ref(false)
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
    options.value = await fetchProductOptions()
    return true
  } catch (error) {
    optionsError.value = errorMessage(error, '筛选选项加载失败，产品列表仍可使用。')
    return false
  } finally {
    optionsLoading.value = false
  }
}

async function loadProducts(): Promise<'success' | 'stale' | 'error'> {
  const activeRequest = ++listRequestId
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetchProducts({
      page: page.value, page_size: pageSize.value, q: filters.keyword.trim() || undefined,
      category_id: filters.category || undefined, scale: filters.scale, status: filters.status, ordering: ordering.value,
    })
    if (activeRequest !== listRequestId) return 'stale'
    products.value = response.data
    total.value = response.meta.total
    return 'success'
  } catch (error) {
    if (activeRequest !== listRequestId) return 'stale'
    loadError.value = errorMessage(error, '产品信息加载失败，请重试。')
    return 'error'
  } finally {
    if (activeRequest === listRequestId) loading.value = false
  }
}

async function reloadAll(): Promise<void> { await Promise.all([loadOptions(), loadProducts()]) }
function applyFilters(): void { page.value = 1; void loadProducts() }
function resetFilters(): void {
  filters.keyword = ''; filters.category = ''; filters.scale = ''; filters.status = ''
  ordering.value = 'product_number'; page.value = 1; syncTableSort(ordering.value); void loadProducts()
}
function handleSortChange(sort: { prop: ProductOrderingField; order: 'ascending' | 'descending' | null }): void {
  if (!sort.prop || !sort.order) return
  const nextOrdering: ProductOrdering = sort.order === 'descending' ? `-${sort.prop}` : sort.prop
  if (nextOrdering === ordering.value) return
  ordering.value = nextOrdering
  page.value = 1
  void loadProducts()
}
function syncTableSort(value: ProductOrdering): void {
  const descending = value.startsWith('-')
  const field = value.replace(/^-/, '')
  void nextTick(() => {
    if (['product_number', 'product_code', 'product_name'].includes(field)) {
      tableRef.value?.sort(field, descending ? 'descending' : 'ascending')
    } else {
      tableRef.value?.clearSort()
    }
  })
}
function handleToolbarOrdering(value: ProductOrdering): void {
  ordering.value = value; page.value = 1; syncTableSort(value); void loadProducts()
}
function rememberFocus(event: MouseEvent): void { returnFocusElement.value = event.currentTarget as HTMLElement }
function openCreate(event: MouseEvent): void { rememberFocus(event); drawerMode.value = 'create'; editingId.value = ''; drawerMounted.value = true; drawerVisible.value = true }
function openEdit(row: ProductInformation, event: MouseEvent): void { rememberFocus(event); drawerMode.value = 'edit'; editingId.value = row.id; drawerMounted.value = true; drawerVisible.value = true }
async function handleSaved(): Promise<void> {
  if (await loadProducts() === 'error') ElMessage.warning('产品已保存，但列表刷新失败；请点击刷新查看最新结果。')
}
function restoreFocus(): void { void nextTick(() => returnFocusElement.value?.focus()) }
function formatWarehouse(row: ProductInformation): string {
  if (row.warehouse_number && row.warehouse_name) return `${row.warehouse_number} ${row.warehouse_name}`
  return row.warehouse_number || row.warehouse_name || '—'
}
function handlePageSizeChange(): void { page.value = 1; void loadProducts() }

onBeforeRouteLeave(async () => !drawerVisible.value || !drawerRef.value || drawerRef.value.canLeave())
onMounted(() => { if (canViewPage.value) void reloadAll() })
</script>

<template>
  <section class="product-page erp-glass-list" data-testid="product-information-page">
    <div v-if="!canViewPage" class="state-page" data-testid="product-no-permission">
      <h1>无权查看产品信息</h1><p>请联系管理员开通“产品信息查看”权限后重试。</p>
    </div>
    <template v-else>
      <section v-glass-spotlight class="erp-list-filter">
      <header class="page-heading erp-list-heading">
        <div class="title-line"><h1>产品信息</h1><span>{{ total === null ? '— 条' : `${total} 条` }}</span></div>
      </header>

      <section class="filter-row erp-list-filters" aria-label="产品筛选">
        <ElInput v-model="filters.keyword" clearable :prefix-icon="Search" placeholder="搜索品号、产品编码、品名、规格、货号" @keyup.enter="applyFilters" />
        <ElSelect v-model="filters.category" clearable filterable placeholder="类别：全部" :loading="optionsLoading" @change="applyFilters"><ElOption v-for="item in options.categories" :key="item.id" :label="item.category_name" :value="item.id" /></ElSelect>
        <ElSelect v-model="filters.scale" clearable placeholder="规模：全部" @change="applyFilters"><ElOption label="定制" value="CUSTOM" /><ElOption label="常规" value="REGULAR" /></ElSelect>
        <ElSelect v-model="filters.status" clearable placeholder="状态：全部" @change="applyFilters"><ElOption label="正常" value="ACTIVE" /><ElOption label="废弃" value="INACTIVE" /></ElSelect>
        <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" :icon="Filter" @click="resetFilters">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="applyFilters">应用筛选</ElButton></div>
      </section>

      </section>

      <section class="list-surface erp-list-data">
        <div class="list-toolbar erp-list-toolbar">
          <div class="toolbar-leading"><ElButton v-if="canAdd" type="primary" :icon="Plus" class="erp-button-motion create-button" @click="openCreate">新增产品</ElButton><span>当前产品清单</span></div>
          <div class="toolbar-actions erp-list-filters">
            <ElSelect :model-value="ordering" aria-label="产品排序" @update:model-value="handleToolbarOrdering"><ElOption label="排序：品号升序" value="product_number" /><ElOption label="排序：品号降序" value="-product_number" /><ElOption label="排序：最近更新" value="-updated_at" /><ElOption label="排序：最早更新" value="updated_at" /></ElSelect>
            <ElButton class="erp-button-motion" :icon="Refresh" :loading="loading" @click="reloadAll">刷新</ElButton>
          </div>
        </div>
        <div v-if="optionsError" class="inline-warning" role="status"><span>{{ optionsError }}</span><ElButton link type="primary" @click="loadOptions">重试选项</ElButton></div>
        <div class="erp-list-table-frame">
        <div v-if="loadError" class="table-state" role="alert"><strong>产品信息加载失败</strong><span>{{ loadError }}</span><ElButton class="erp-button-motion" @click="loadProducts">重新加载</ElButton></div>
        <ElTable ref="tableRef" v-else v-loading="loading" :data="products" row-key="id" height="100%" class="product-table" :default-sort="{ prop: 'product_number', order: 'ascending' }" @sort-change="handleSortChange">
          <ElTableColumn prop="product_number" label="品号" width="142" sortable="custom" :sort-orders="['ascending', 'descending']" show-overflow-tooltip />
          <ElTableColumn prop="product_code" label="产品编码" width="140" sortable="custom" :sort-orders="['ascending', 'descending']" show-overflow-tooltip><template #default="{ row }">{{ row.product_code || '—' }}</template></ElTableColumn>
          <ElTableColumn prop="category_name" label="类别" width="132" show-overflow-tooltip><template #default="{ row }"><span>{{ row.category_name || '—' }}</span><ElTooltip v-if="row.category_item_mismatch" :content="`历史货号属于“${row.item_category_name}”；主动修改后必须重新匹配。`"><span class="history-dot" aria-label="历史类别货号不匹配">!</span></ElTooltip></template></ElTableColumn>
          <ElTableColumn prop="product_name" label="品名" min-width="207" sortable="custom" :sort-orders="['ascending', 'descending']" show-overflow-tooltip />
          <ElTableColumn prop="specification" label="规格" width="201" show-overflow-tooltip />
          <ElTableColumn prop="unit_name" label="单位" width="100" show-overflow-tooltip />
          <ElTableColumn prop="item_number" label="货号" width="133" show-overflow-tooltip />
          <ElTableColumn label="仓库" width="178" show-overflow-tooltip><template #default="{ row }">{{ formatWarehouse(row) }}</template></ElTableColumn>
          <ElTableColumn label="规模" width="131"><template #default="{ row }"><span :class="['warm-tag', 'scale-tag', row.scale === 'CUSTOM' ? 'is-custom' : 'is-regular', 'erp-list-tag', row.scale === 'CUSTOM' ? 'erp-list-tag--brand' : 'erp-list-tag--info']">{{ row.scale === 'CUSTOM' ? '定制' : '常规' }}</span></template></ElTableColumn>
          <ElTableColumn label="状态" width="147"><template #default="{ row }"><span :class="['warm-tag', 'status-tag', row.status === 'ACTIVE' ? 'is-active' : 'is-inactive', 'erp-list-tag', row.status === 'ACTIVE' ? 'erp-list-tag--success' : 'erp-list-tag--neutral']">{{ row.status === 'ACTIVE' ? '正常' : '废弃' }}</span></template></ElTableColumn>
          <ElTableColumn label="操作" width="123" fixed="right"><template #default="{ row }"><ElButton v-if="canChange" link class="edit-button" @click="openEdit(row, $event)">编辑</ElButton><span v-else>—</span></template></ElTableColumn>
          <template #empty><div class="empty-state"><strong>{{ filters.keyword || filters.category || filters.scale || filters.status ? '没有符合筛选条件的产品' : '暂无产品信息' }}</strong><span>{{ canAdd ? '可新建第一条产品资料。' : '请调整筛选条件后重试。' }}</span></div></template>
        </ElTable>
        </div>
        <footer class="pagination-row erp-list-footer">
          <span>{{ total === null ? '共 — 条' : `共 ${total} 条` }}</span>
          <ElPagination v-if="total !== null" v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[50, 100]" layout="sizes, prev, pager, next" @current-change="loadProducts" @size-change="handlePageSizeChange" />
        </footer>
      </section>

      <ProductInformationDrawer v-if="drawerMounted" ref="drawerRef" v-model="drawerVisible" :mode="drawerMode" :product-id="editingId || undefined" @saved="handleSaved" @closed="restoreFocus" />
    </template>
  </section>
</template>

<style scoped lang="scss">
.title-line, .toolbar-leading { display: flex; align-items: center; gap: 16px; }
.title-line span { color: var(--erp-color-text-secondary); font-size: 12px; }
.filter-row > :deep(.el-input) { width: 320px; }.filter-row > :deep(.el-select) { width: 130px; }
.toolbar-actions :deep(.el-select) { width: 154px; }

.inline-warning { display: flex; align-items: center; gap: 8px; padding: 5px 16px; color: var(--erp-color-warning); font-size: 12px; }
.history-dot { width: 16px; height: 16px; display: inline-grid; margin-left: 5px; place-items: center; border-radius: 50%; color: var(--erp-color-warning); background: var(--erp-tag-warning-background); font-size: 10px; }
.table-state { min-height: 160px; flex: 1; display: grid; place-content: center; justify-items: center; gap: 10px; color: var(--erp-color-text-secondary); }
.table-state strong, .empty-state strong { color: var(--erp-color-text-primary); }.empty-state { min-height: 160px; display: grid; place-content: center; gap: 7px; color: var(--erp-color-text-secondary); }
.state-page { min-height: 420px; display: grid; place-content: center; text-align: center; }.state-page h1 { margin: 0 0 8px; }.state-page p { margin: 0; color: var(--erp-color-text-secondary); }
</style>
