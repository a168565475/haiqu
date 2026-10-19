<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Check, Close, Plus, Search } from '@element-plus/icons-vue'
import MaterialCatalogSelect from '@/components/products/MaterialCatalogSelect.vue'
import ProductCatalogField from '@/components/products/ProductCatalogField.vue'
import ProductCatalogRow from '@/components/products/ProductCatalogRow.vue'
import ProductCatalogError from '@/components/products/ProductCatalogError.vue'
import ProductCatalogSaveButton from '@/components/products/ProductCatalogSaveButton.vue'
import { useAuthStore } from '@/stores/auth'
import {
  createProductCatalog, createProductCatalogName, fetchProductCatalogName, fetchProductCatalogNames,
  fetchProductCatalogOptions, fetchProductCatalogs, productCatalogError, productCatalogErrorStatus, updateProductCatalogName,
} from '@/api/productCatalog'
import { productCatalogFields, type ProductCatalog, type ProductCatalogFields, type ProductCatalogName, type ProductCatalogOptions } from '@/types/productCatalog'

const auth = useAuthStore()
const canView = computed(() => auth.hasPermission('product_catalog.view_productcatalog'))
const canAdd = computed(() => auth.hasPermission('product_catalog.add_productcatalog'))
const canChange = computed(() => auth.hasPermission('product_catalog.change_productcatalog'))
const options = ref<ProductCatalogOptions>()
const category = ref('')
const search = ref('')
const names = ref<ProductCatalogName[]>([])
const selected = ref<ProductCatalogName>()
const products = ref<ProductCatalog[]>([])
const currentPage = ref(1)
const total = ref(0)
const totalPages = ref(0)
const optionsLoading = ref(false)
const namesLoading = ref(false)
const productsLoading = ref(false)
const optionsError = ref('')
const namesError = ref('')
const productsError = ref('')
const lockedRows = ref<Record<string, boolean>>({})
const addingName = ref(false)
const newName = ref('')
const nameInput = ref<HTMLInputElement>()
const nameCreateError = ref('')
const creatingName = ref(false)
const editingName = ref(false)
const nameLoading = ref(false)
const nameVersion = ref('')
const nameWarning = ref('')
const addingProduct = ref(false)
const creatingProduct = ref(false)
const productCreateError = ref('')
const draftRow = ref<HTMLTableRowElement>()
const newProduct = reactive<ProductCatalogFields>({ product_code: '', item_number: '', specification: '', unit: '', scale: '' })
const rowLocked = computed(() => Object.values(lockedRows.value).some(Boolean))
const navigationLocked = computed(() => rowLocked.value || addingName.value || editingName.value || addingProduct.value || creatingName.value || creatingProduct.value || nameLoading.value)
const categoryOptions = computed(() => options.value?.categories.map(item => ({ value: item.id, label: item.name })) ?? [])
const categoryNameCounts = computed(() => Object.fromEntries(options.value?.categories.map(item => [item.id, item.name_count]) ?? []))
const scaleOptions = computed(() => [...new Set(['', '常规', '定制', ...(options.value?.scales ?? [])])].map(value => ({ value, label: value || '未填写' })))
let namesSequence = 0
let productsSequence = 0
let initializationSequence = 0
let searchTimer: ReturnType<typeof setTimeout> | undefined
let appliedSearch = ''

function cancelSearch() {
  if (searchTimer !== undefined) { clearTimeout(searchTimer); searchTimer = undefined; search.value = appliedSearch }
}
watch(navigationLocked, locked => { if (locked) cancelSearch() })
function applyProduct(product: ProductCatalog) {
  products.value = products.value.map(item => item.id === product.id ? product : item)
}
function lockRow(id: string, active: boolean) {
  if (active) lockedRows.value[id] = true
  else delete lockedRows.value[id]
}
async function loadProducts() {
  const id = selected.value?.id
  if (!id) return
  const sequence = ++productsSequence
  productsLoading.value = true
  productsError.value = ''
  products.value = []
  try {
    const result = await fetchProductCatalogs({ name_id: id, page: currentPage.value, page_size: 50 })
    if (sequence !== productsSequence || selected.value?.id !== id) return
    products.value = result.data
    total.value = result.meta.total
    selected.value = { ...selected.value, product_count: result.meta.total }
    names.value = names.value.map(item => item.id === id ? { ...item, product_count: result.meta.total } : item)
    totalPages.value = result.meta.total_pages
    currentPage.value = result.meta.page
  } catch (issue) { if (sequence === productsSequence) productsError.value = productCatalogError(issue) }
  finally { if (sequence === productsSequence) productsLoading.value = false }
}
async function selectName(item: ProductCatalogName) {
  if (navigationLocked.value || namesLoading.value || item.id === selected.value?.id) return
  selected.value = item
  products.value = []
  currentPage.value = 1
  total.value = 0
  totalPages.value = 0
  nameVersion.value = ''
  nameWarning.value = ''
  await loadProducts()
}
async function loadNames(preferredId?: string) {
  if (!category.value) return
  const sequence = ++namesSequence
  ++productsSequence
  namesLoading.value = true
  namesError.value = ''
  selected.value = undefined
  products.value = []
  productsLoading.value = false
  productsError.value = ''
  nameVersion.value = ''
  nameWarning.value = ''
  currentPage.value = 1
  total.value = 0
  totalPages.value = 0
  try {
    const query = search.value.trim()
    const result = await fetchProductCatalogNames({ category_id: category.value, q: query })
    if (sequence !== namesSequence) return
    names.value = result
    appliedSearch = query
    selected.value = result.find(item => item.id === preferredId) ?? result[0]
    if (selected.value) await loadProducts()
  } catch (issue) { if (sequence === namesSequence) { names.value = []; namesError.value = productCatalogError(issue) } }
  finally { if (sequence === namesSequence) namesLoading.value = false }
}
async function initialize() {
  if (!canView.value) return
  const sequence = ++initializationSequence
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const result = await fetchProductCatalogOptions()
    if (sequence !== initializationSequence) return
    options.value = result
    category.value = result.categories[0]?.id ?? ''
    await loadNames()
  } catch (issue) { if (sequence === initializationSequence) optionsError.value = productCatalogError(issue) }
  finally { if (sequence === initializationSequence) optionsLoading.value = false }
}
function changeCategory() {
  if (navigationLocked.value) return
  cancelSearch()
  search.value = ''
  void loadNames()
}
function applyCatalogFilters() {
  if (navigationLocked.value || optionsLoading.value) return
  clearTimeout(searchTimer)
  searchTimer = undefined
  void loadNames()
}

function resetCatalogFilters() {
  if (navigationLocked.value || optionsLoading.value) return
  category.value = options.value?.categories[0]?.id ?? ''
  changeCategory()
}

function searchNames() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchTimer = undefined
    if (!navigationLocked.value) void loadNames()
  }, 250)
}
function changePage(page: number) {
  if (navigationLocked.value || productsLoading.value || page < 1 || page > totalPages.value) return
  currentPage.value = page
  void loadProducts()
}
async function startName() {
  if (navigationLocked.value || !canAdd.value) return
  addingName.value = true
  newName.value = ''
  nameCreateError.value = ''
  await nextTick()
  nameInput.value?.focus()
}
async function saveName() {
  if (creatingName.value || !canAdd.value) return
  if (!newName.value.trim()) { nameCreateError.value = '请输入品名。'; return }
  creatingName.value = true
  nameCreateError.value = ''
  try {
    const result = await createProductCatalogName({ category_id: category.value, name: newName.value })
    const savedCategory = options.value?.categories.find(item => item.id === result.data.category_id)
    if (savedCategory) savedCategory.name_count += 1
    addingName.value = false
    search.value = ''
    await loadNames(result.data.id)
  } catch (issue) { nameCreateError.value = productCatalogError(issue) }
  finally { creatingName.value = false }
}
async function readName() {
  if (!selected.value) return
  const id = selected.value.id
  nameLoading.value = true
  try {
    const result = await fetchProductCatalogName(id)
    if (selected.value?.id !== id) return
    selected.value = result.data
    names.value = names.value.map(item => item.id === id ? result.data : item)
    nameVersion.value = result.etag
    nameWarning.value = result.etag ? '' : '未取得品名版本，请重新读取后再保存。'
  } finally { nameLoading.value = false }
}
async function saveExistingName(value: string) {
  if (!canChange.value || !selected.value) throw new Error('没有修改品名权限，输入内容已保留。')
  if (!value.trim()) throw new Error('请输入品名。')
  if (!nameVersion.value || nameWarning.value) throw new Error('请重新读取品名后再保存。')
  try {
    const result = await updateProductCatalogName(selected.value.id, { name: value }, nameVersion.value)
    selected.value = result.data
    nameVersion.value = result.etag
    nameWarning.value = result.etag ? '' : '未取得品名版本，请重新读取后再保存。'
    names.value = names.value.map(item => item.id === result.data.id ? result.data : item)
    products.value = products.value.map(item => ({ ...item, name: result.data.name }))
  } catch (issue) {
    if ([412, 428].includes(productCatalogErrorStatus(issue) ?? 0)) nameWarning.value = productCatalogError(issue)
    throw issue
  }
}
async function reloadName() {
  try { await readName() }
  catch (issue) { nameWarning.value = productCatalogError(issue) }
}
async function startProduct() {
  if (!selected.value || navigationLocked.value || !canAdd.value) return
  Object.assign(newProduct, { product_code: '', item_number: '', specification: '', unit: '', scale: '' })
  addingProduct.value = true
  productCreateError.value = ''
  await nextTick()
  draftRow.value?.querySelector('input')?.focus()
  draftRow.value?.scrollIntoView?.({ block: 'nearest' })
}
async function saveProduct() {
  if (!selected.value || !canAdd.value || creatingProduct.value) return
  creatingProduct.value = true
  productCreateError.value = ''
  try {
    await createProductCatalog({ name_id: selected.value.id, ...newProduct })
    addingProduct.value = false
    selected.value = { ...selected.value, product_count: selected.value.product_count + 1 }
    names.value = names.value.map(item => item.id === selected.value?.id ? selected.value : item)
    currentPage.value = Math.max(1, Math.ceil((total.value + 1) / 50))
    await loadProducts()
  } catch (issue) { productCreateError.value = productCatalogError(issue) }
  finally { creatingProduct.value = false }
}
onMounted(initialize)
onBeforeUnmount(() => { ++namesSequence; ++productsSequence; ++initializationSequence; clearTimeout(searchTimer) })
</script>

<template>
  <section class="product-catalog-page erp-glass-list erp-glass-list--catalog" aria-label="产品管理">
    <p v-if="!canView" class="page-message" role="alert">无权查看产品管理</p>
    <div v-else-if="optionsError" class="page-message error-message" role="alert">{{ optionsError }} <button class="erp-list-button erp-button-motion" type="button" @click="initialize">重新加载</button></div>
    <template v-else>
      <aside v-glass-spotlight class="catalog-sidebar erp-list-filter" aria-label="产品品名">
        <MaterialCatalogSelect v-model="category" ariaLabel="产品类别" :options="categoryOptions" :placeholder="optionsLoading ? '加载类别中…' : '暂无类别'" :disabled="optionsLoading || navigationLocked" @change="changeCategory">
          <template #option="{ option, selected: isSelected }">
            <span class="material-catalog-select-option-label">{{ option.label }}</span>
            <span class="product-category-count" :data-category-count="option.value">{{ categoryNameCounts[option.value] ?? '—' }}</span>
            <span class="product-category-check" aria-hidden="true"><Check v-if="isSelected" /></span>
          </template>
        </MaterialCatalogSelect>
        <div class="catalog-search"><Search aria-hidden="true" /><input class="erp-list-control" v-model="search" type="search" aria-label="搜索品名" placeholder="搜索品名" :disabled="optionsLoading || navigationLocked" @input="searchNames" /></div>
        <div class="erp-list-filter-actions"><button class="erp-list-button erp-button-motion" type="button" :disabled="optionsLoading || navigationLocked" @click="resetCatalogFilters">重置</button><button type="button" class="erp-list-button erp-button-motion erp-list-button--primary" :disabled="optionsLoading || navigationLocked" @click="applyCatalogFilters">应用筛选</button></div>
        <button v-if="canAdd" type="button" class="erp-list-button erp-button-motion add-name" data-action="add-name" aria-label="新增品名" :disabled="!category || optionsLoading || namesLoading || navigationLocked" @click="startName"><Plus aria-hidden="true" />新增品名</button>
        <form v-if="addingName" class="name-editor" @submit.prevent="saveName">
          <input class="erp-list-control" ref="nameInput" v-model="newName" aria-label="新品名" placeholder="输入新品名" maxlength="200" :aria-invalid="!!nameCreateError" :disabled="creatingName || !canAdd" />
          <ProductCatalogSaveButton type="submit" class="small-save" data-action="save-name" label="保存" ariaLabel="保存品名" :loading="creatingName" :disabled="!canAdd" />
          <button type="button" class="erp-list-button erp-button-motion icon-button" aria-label="取消新增品名" title="取消新增品名" :disabled="creatingName" @click="addingName = false"><Close aria-hidden="true" /></button>
          <ProductCatalogError v-if="nameCreateError" :message="nameCreateError" />
        </form>
        <div v-if="namesError" class="error-message" role="alert">{{ namesError }} <button class="erp-list-button erp-button-motion" type="button" :disabled="navigationLocked" @click="loadNames()">重试</button></div>
        <nav class="product-names erp-list-catalog-nav" data-testid="product-names" aria-label="品名列表" tabindex="0" :aria-busy="namesLoading">
          <button v-for="item in names" :key="item.id" type="button" :data-name-id="item.id" :title="item.name" :class="{ selected: selected?.id === item.id }" :aria-current="selected?.id === item.id ? 'true' : undefined" :disabled="navigationLocked || namesLoading" @click="selectName(item)">
            <span class="product-name-label">{{ item.name }}</span>
            <span class="product-name-count">{{ item.product_count }}</span>
          </button>
          <p v-if="namesLoading" class="list-message" role="status">加载品名中…</p>
          <p v-else-if="!names.length && !optionsLoading && !namesError" class="list-message">{{ search ? '没有匹配品名，请调整搜索。' : '暂无品名' }}</p>
        </nav>
      </aside>
      <main class="catalog-detail erp-list-data" :class="{ 'catalog-detail--no-footer': totalPages <= 1 }" :data-name-id="selected?.id" :aria-busy="productsLoading">
        <header class="erp-list-heading"><h1>产品管理</h1></header>
        <template v-if="selected">
          <div class="detail-heading">
            <h2><ProductCatalogField :key="selected.id" :value="selected.name" label="品名" :max-length="200" :readonly="!canChange" :disabled="nameLoading || rowLocked || addingProduct || !!nameWarning" :on-start="readName" :on-save="saveExistingName" @editing="active => editingName = active" /></h2>
            <span class="product-count">{{ total }} 条产品</span>
            <button v-if="canAdd && !addingProduct" class="erp-list-button erp-list-button--primary erp-button-motion" type="button" data-action="add-product" aria-label="新增产品" :disabled="navigationLocked || productsLoading || !!productsError" @click="startProduct"><Plus aria-hidden="true" />新增产品</button>
          </div>
          <div v-if="nameWarning" class="error-message" role="alert">{{ nameWarning }} <button class="erp-list-button erp-button-motion" type="button" data-action="reload-name" :disabled="nameLoading" @click="reloadName">重新读取</button></div>
          <div v-if="productsError" class="error-message" role="alert">{{ productsError }} <button class="erp-list-button erp-button-motion" type="button" :disabled="navigationLocked || productsLoading" @click="loadProducts">重试</button></div>
          <div class="erp-list-table-frame">
          <div class="product-table-scroll erp-list-table-scroll" tabindex="0" aria-label="产品表格滚动区域">
            <table class="erp-table-editor product-table erp-list-native-table" aria-label="品名下的产品">
              <colgroup><col class="code-column" /><col class="item-column" /><col class="spec-column" /><col class="unit-column" /><col class="scale-column" /><col class="colors-column" /></colgroup>
              <thead><tr><th v-for="field in productCatalogFields" :key="field.key" scope="col">{{ field.label }}</th><th scope="col">颜色</th></tr></thead>
              <tbody>
                <ProductCatalogRow v-for="product in products" :key="product.id" :product="product" :can-change="canChange" :scales="options?.scales ?? []" @updated="applyProduct" @lock="lockRow" />
                <tr v-if="addingProduct" ref="draftRow" class="new-product-row" data-new-product>
                  <td v-for="field in productCatalogFields" :key="field.key" :data-field="field.key">
                    <MaterialCatalogSelect v-if="field.key === 'scale'" v-model="newProduct.scale" ariaLabel="新产品常规/定制" :options="scaleOptions" placeholder="未填写" :disabled="creatingProduct || !canAdd" />
                    <input class="erp-list-control" v-else v-model="newProduct[field.key]" :aria-label="`新产品${field.label}`" :maxlength="field.maxLength" :placeholder="field.label" :disabled="creatingProduct || !canAdd" @keydown.enter.prevent="saveProduct" />
                  </td>
                  <td><div class="new-product-actions"><span class="muted">无颜色</span><ProductCatalogSaveButton type="button" class="small-save" data-action="save-product" label="保存产品" ariaLabel="保存产品" :loading="creatingProduct" :disabled="!canAdd" @click="saveProduct" /><button type="button" class="erp-list-button erp-button-motion icon-button" aria-label="取消新增产品" title="取消新增产品" :disabled="creatingProduct" @click="addingProduct = false"><Close aria-hidden="true" /></button><ProductCatalogError v-if="productCreateError" :message="productCreateError" /></div></td>
                </tr>
                <tr v-if="!products.length && !addingProduct"><td colspan="6" class="table-message">{{ productsLoading ? '正在读取产品…' : productsError ? '读取产品失败，请重试。' : '暂无产品，可在上方新增。' }}</td></tr>
              </tbody>
            </table>
          </div>
          </div>
          <div v-if="totalPages > 1" class="product-pagination erp-list-footer"><span>共 {{ total }} 条 · 每页 50 条</span><div><button class="erp-list-button erp-button-motion" type="button" aria-label="上一页产品" :disabled="currentPage <= 1 || navigationLocked || productsLoading" @click="changePage(currentPage - 1)">上一页</button><span>{{ currentPage }} / {{ totalPages }}</span><button class="erp-list-button erp-button-motion" type="button" aria-label="下一页产品" :disabled="currentPage >= totalPages || navigationLocked || productsLoading" @click="changePage(currentPage + 1)">下一页</button></div></div>
        </template>
        <p v-else class="page-message">{{ optionsLoading || namesLoading ? '加载中…' : '选择或新增品名，维护产品。' }}</p>
      </main>
    </template>
  </section>
</template>

<style scoped lang="scss">
.product-catalog-page { grid-template-rows: minmax(0, 1fr); }
.product-catalog-page > .page-message { grid-column: 1 / -1; }
.product-catalog-page.erp-glass-list--catalog > .catalog-sidebar { display: flex; flex-direction: column; gap: 8px; min-height: 0; overflow: visible; }
.catalog-sidebar > :not(.product-names) { flex-shrink: 0; min-width: 0; }
.catalog-search { position: relative; }
.catalog-search svg { position: absolute; top: 8px; left: 10px; width: 16px; height: 16px; color: var(--erp-input-placeholder); pointer-events: none; }
.catalog-search input { width: 100%; padding-left: 34px; }
.catalog-sidebar .erp-list-filter-actions { flex-wrap: wrap; margin-left: 0; }
.product-names { flex: 1; min-width: 0; min-height: 0; overflow-x: hidden; overflow-y: auto; scrollbar-width: none; }
.product-names::-webkit-scrollbar { display: none; }
.catalog-detail { overflow: hidden; }
.catalog-detail.catalog-detail--no-footer { padding-bottom: var(--erp-space-3); }
h2 { min-width: 0; margin: 0; font-size: 17px; line-height: 24px; font-weight: 600; }
.page-message, .list-message, .list-empty { margin: 0; padding: 12px 0; color: var(--erp-color-text-secondary); }
.error-message { margin: 4px 0; color: var(--erp-color-danger); overflow-wrap: anywhere; }
.product-catalog-page svg { width: 16px; height: 16px; flex-shrink: 0; }
.name-editor, .new-product-actions { position: relative; display: flex; align-items: center; gap: 6px; }
.name-editor input { flex: 1; min-width: 0; }
.icon-button { width: 32px; padding: 0; flex-shrink: 0; }
.product-names > button { position: relative; display: flex; gap: 8px; width: 100%; text-align: left; white-space: normal; overflow-wrap: anywhere; }
.product-names > button.selected, .product-names > button.selected:hover { background: color-mix(in srgb, var(--erp-menu-selected-background) 88%, var(--erp-menu-accent)); color: var(--erp-menu-accent); }
.product-names > button.selected::before { content: ''; position: absolute; inset: 6px auto 6px 0; width: 3px; border-radius: 0 3px 3px 0; background: var(--erp-menu-accent); }
.product-name-label { flex: 1; min-width: 0; }
.product-name-count, .product-category-count { flex-shrink: 0; white-space: nowrap; font-weight: 400; color: var(--erp-color-text-secondary); }
.product-category-check { display: flex; flex: 0 0 16px; width: 16px; height: 16px; }
.detail-heading { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.detail-heading h2 { max-width: calc(100% - 110px); }
.detail-heading > .product-count, .detail-heading > .erp-list-button { flex-shrink: 0; }
.product-count, .muted { color: var(--erp-color-text-secondary); }
.product-table { min-width: 1420px; }
.code-column, .item-column { width: 190px; }.spec-column { width: 280px; }.unit-column { width: 180px; }.scale-column { width: 220px; }.colors-column { width: 360px; }
.product-table :deep(td) { vertical-align: top; overflow-wrap: anywhere; }
.new-product-row td { background: var(--erp-table-selected); }
.product-pagination > div { display: flex; align-items: center; gap: 10px; }
.table-message { text-align: center; vertical-align: middle; }
</style>
