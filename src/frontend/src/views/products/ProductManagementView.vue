<script setup lang="ts">
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
  <section class="product-catalog-page" aria-label="产品管理">
    <p v-if="!canView" class="page-message" role="alert">无权查看产品管理</p>
    <div v-else-if="optionsError" class="page-message error-message" role="alert">{{ optionsError }} <button type="button" @click="initialize">重新加载</button></div>
    <template v-else>
      <aside class="catalog-sidebar" aria-label="产品品名">
        <MaterialCatalogSelect v-model="category" ariaLabel="产品类别" :options="categoryOptions" :placeholder="optionsLoading ? '加载类别中…' : '暂无类别'" :disabled="optionsLoading || navigationLocked" @change="changeCategory">
          <template #option="{ option, selected: isSelected }">
            <span class="material-catalog-select-option-label">{{ option.label }}</span>
            <span class="product-category-count" :data-category-count="option.value">{{ categoryNameCounts[option.value] ?? '—' }}</span>
            <span class="product-category-check" aria-hidden="true"><Check v-if="isSelected" /></span>
          </template>
        </MaterialCatalogSelect>
        <div class="catalog-search"><Search aria-hidden="true" /><input v-model="search" type="search" aria-label="搜索品名" placeholder="搜索品名" :disabled="optionsLoading || navigationLocked" @input="searchNames" /></div>
        <button v-if="canAdd" type="button" class="add-name" data-action="add-name" aria-label="新增品名" :disabled="!category || optionsLoading || namesLoading || navigationLocked" @click="startName"><Plus aria-hidden="true" />新增品名</button>
        <form v-if="addingName" class="name-editor" @submit.prevent="saveName">
          <input ref="nameInput" v-model="newName" aria-label="新品名" placeholder="输入新品名" maxlength="200" :aria-invalid="!!nameCreateError" :disabled="creatingName || !canAdd" />
          <ProductCatalogSaveButton type="submit" class="small-save" data-action="save-name" label="保存" ariaLabel="保存品名" :loading="creatingName" :disabled="!canAdd" />
          <button type="button" class="icon-button" aria-label="取消新增品名" title="取消新增品名" :disabled="creatingName" @click="addingName = false"><Close aria-hidden="true" /></button>
          <ProductCatalogError v-if="nameCreateError" :message="nameCreateError" />
        </form>
        <div v-if="namesError" class="error-message" role="alert">{{ namesError }} <button type="button" :disabled="navigationLocked" @click="loadNames()">重试</button></div>
        <nav class="product-names" data-testid="product-names" aria-label="品名列表" :aria-busy="namesLoading">
          <button v-for="item in names" :key="item.id" type="button" :data-name-id="item.id" :title="item.name" :class="{ selected: selected?.id === item.id }" :aria-current="selected?.id === item.id ? 'true' : undefined" :disabled="navigationLocked || namesLoading" @click="selectName(item)">
            <span class="product-name-label">{{ item.name }}</span>
            <span class="product-name-count">{{ item.product_count }}</span>
          </button>
          <p v-if="namesLoading" class="list-message" role="status">加载品名中…</p>
          <p v-else-if="!names.length && !optionsLoading && !namesError" class="list-message">{{ search ? '没有匹配品名，请调整搜索。' : '暂无品名' }}</p>
        </nav>
      </aside>
      <main class="catalog-detail" :data-name-id="selected?.id" :aria-busy="productsLoading">
        <template v-if="selected">
          <div class="detail-heading">
            <h2><ProductCatalogField :key="selected.id" :value="selected.name" label="品名" :max-length="200" :readonly="!canChange" :disabled="nameLoading || rowLocked || addingProduct || !!nameWarning" :on-start="readName" :on-save="saveExistingName" @editing="active => editingName = active" /></h2>
            <span class="product-count">{{ total }} 条产品</span>
          </div>
          <div v-if="nameWarning" class="error-message" role="alert">{{ nameWarning }} <button type="button" data-action="reload-name" :disabled="nameLoading" @click="reloadName">重新读取</button></div>
          <div v-if="productsError" class="error-message" role="alert">{{ productsError }} <button type="button" :disabled="navigationLocked || productsLoading" @click="loadProducts">重试</button></div>
          <div class="product-table-scroll" tabindex="0" aria-label="产品表格滚动区域">
            <table class="product-table" aria-label="品名下的产品">
              <colgroup><col class="code-column" /><col class="item-column" /><col class="spec-column" /><col class="unit-column" /><col class="scale-column" /><col class="colors-column" /></colgroup>
              <thead><tr><th v-for="field in productCatalogFields" :key="field.key" scope="col">{{ field.label }}</th><th scope="col">颜色</th></tr></thead>
              <tbody>
                <ProductCatalogRow v-for="product in products" :key="product.id" :product="product" :can-change="canChange" :scales="options?.scales ?? []" @updated="applyProduct" @lock="lockRow" />
                <tr v-if="addingProduct" ref="draftRow" class="new-product-row" data-new-product>
                  <td v-for="field in productCatalogFields" :key="field.key" :data-field="field.key">
                    <MaterialCatalogSelect v-if="field.key === 'scale'" v-model="newProduct.scale" ariaLabel="新产品常规/定制" :options="scaleOptions" placeholder="未填写" :disabled="creatingProduct || !canAdd" />
                    <input v-else v-model="newProduct[field.key]" :aria-label="`新产品${field.label}`" :maxlength="field.maxLength" :placeholder="field.label" :disabled="creatingProduct || !canAdd" @keydown.enter.prevent="saveProduct" />
                  </td>
                  <td><div class="new-product-actions"><span class="muted">无颜色</span><ProductCatalogSaveButton type="button" class="small-save" data-action="save-product" label="保存产品" ariaLabel="保存产品" :loading="creatingProduct" :disabled="!canAdd" @click="saveProduct" /><button type="button" class="icon-button" aria-label="取消新增产品" title="取消新增产品" :disabled="creatingProduct" @click="addingProduct = false"><Close aria-hidden="true" /></button><ProductCatalogError v-if="productCreateError" :message="productCreateError" /></div></td>
                </tr>
                <tr v-if="!products.length && !addingProduct"><td colspan="6" class="table-message">{{ productsLoading ? '正在读取产品…' : productsError ? '读取产品失败，请重试。' : '暂无产品，可在下方新增。' }}</td></tr>
              </tbody>
            </table>
            <div v-if="canAdd && !addingProduct" class="add-product-row"><button type="button" data-action="add-product" aria-label="新增产品" :disabled="navigationLocked || productsLoading || !!productsError" @click="startProduct"><Plus aria-hidden="true" />新增产品</button></div>
          </div>
          <div v-if="totalPages > 1" class="product-pagination"><span>共 {{ total }} 条 · 每页 50 条</span><div><button type="button" aria-label="上一页产品" :disabled="currentPage <= 1 || navigationLocked || productsLoading" @click="changePage(currentPage - 1)">上一页</button><span>{{ currentPage }} / {{ totalPages }}</span><button type="button" aria-label="下一页产品" :disabled="currentPage >= totalPages || navigationLocked || productsLoading" @click="changePage(currentPage + 1)">下一页</button></div></div>
        </template>
        <p v-else class="page-message">{{ optionsLoading || namesLoading ? '加载中…' : '选择或新增品名，维护产品。' }}</p>
      </main>
    </template>
  </section>
</template>

<style scoped lang="scss">
.product-catalog-page { display: flex; gap: 8px; height: 100%; min-height: 0; padding: 0; overflow: hidden; box-sizing: border-box; background: #f6f3ec; color: #1f1d18; font-size: 13px; line-height: 20px; }
.catalog-sidebar, .catalog-detail { box-sizing: border-box; border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7; }
.catalog-sidebar { width: 240px; flex: 0 0 240px; display: flex; flex-direction: column; gap: 8px; padding: 16px; min-height: 0; overflow: hidden; }
.catalog-sidebar > :not(.product-names) { flex-shrink: 0; }
button, input { font: inherit; }
button { display: inline-flex; align-items: center; justify-content: center; gap: 4px; box-sizing: border-box; height: 32px; min-height: 32px; padding: 0 10px; border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7; color: #1f1d18; cursor: pointer; }
button:hover:not(:disabled):not([aria-busy='true']) { background: #f0eadf; border-color: #c9c0b2; }
button:active:not(:disabled):not([aria-busy='true']) { background: #e8e1d5; border-color: #c9c0b2; }
input { box-sizing: border-box; height: 32px; width: 100%; min-width: 0; padding: 0 10px; border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7; color: #1f1d18; }
input::placeholder { color: #968f84; opacity: 1; }
input:focus { border-color: #3898ec; }
input[aria-invalid='true'] { border-color: #b53333; }
button:disabled, input:disabled { opacity: 1; cursor: not-allowed; color: #6f6a61; background: #e8e1d5; border-color: #ddd6c9; }
button:focus-visible, input:focus-visible, .product-table-scroll:focus-visible { outline: 2px solid #3898ec; outline-offset: 2px; }
svg { width: 16px; height: 16px; flex-shrink: 0; }
.catalog-search { position: relative; }
.catalog-search svg { position: absolute; top: 8px; left: 10px; color: #6f6a61; pointer-events: none; }
.catalog-search input { padding-left: 34px; }
.add-name, .small-save { color: #c84e28; border-color: #c84e28; }
.small-save { flex-shrink: 0; padding: 0 8px; }
.name-editor { position: relative; display: flex; align-items: center; gap: 6px; }
.name-editor input { flex: 1; }
.icon-button { width: 32px; padding: 0; flex-shrink: 0; border-color: transparent; background: transparent; color: #6f6a61; }
.product-names { flex: 1; min-height: 0; overflow-y: auto; padding: 4px; }
.product-names > button { display: flex; gap: 8px; width: 100%; height: auto; min-height: 32px; padding: 4px 10px; text-align: left; border: 0; border-left: 4px solid transparent; border-bottom: 1px solid #ddd6c9; white-space: normal; overflow-wrap: anywhere; background: transparent; }
.product-name-label { flex: 1; min-width: 0; }
.product-name-count, .product-category-count { flex-shrink: 0; white-space: nowrap; font-weight: 400; color: #6f6a61; }
.product-category-check { display: flex; flex: 0 0 16px; width: 16px; height: 16px; }
.product-names > button.selected { border-left-color: #c84e28; border-bottom-color: transparent; background: #fff4e6; color: #c84e28; font-weight: 600; }
.product-names > button:hover:not(:disabled):not(.selected) { background: #fff6ea; border-left-color: transparent; border-bottom-color: #ddd6c9; }
.product-names > button.selected:hover:not(:disabled), .product-names > button.selected:active:not(:disabled) { background: #fff4e6; border-left-color: #c84e28; border-bottom-color: transparent; }
.product-names > button:disabled { color: #6f6a61; background: #e8e1d5; border-left-color: transparent; border-bottom-color: #ddd6c9; }
.product-names > button.selected:disabled { border-left-color: #6f6a61; }
.catalog-detail { display: flex; flex-direction: column; flex: 1; min-width: 0; min-height: 0; padding: 16px; overflow: hidden; }
.detail-heading { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
h2 { min-width: 0; max-width: calc(100% - 110px); margin: 0; font-size: 17px; line-height: 24px; font-weight: 600; }
h2 :deep(button), h2 :deep(input), h2 :deep(.catalog-save-button) { font-size: 13px; line-height: 20px; }
.product-count, .muted { color: #6f6a61; }
.product-table-scroll { min-height: 0; overflow: auto; padding: 4px; }
.product-table { width: 100%; min-width: 1420px; border-collapse: separate; border-spacing: 0; table-layout: fixed; border: 1px solid #ddd6c9; border-radius: 5px; }
.code-column, .item-column { width: 190px; }
.spec-column { width: 280px; }
.unit-column { width: 180px; }
.scale-column { width: 220px; }
.colors-column { width: 360px; }
th { height: 44px; box-sizing: border-box; padding: 0 16px; text-align: left; background: #f0eadf; color: #6f6a61; font-size: 12px; line-height: 18px; font-weight: 500; border-bottom: 1px solid #ddd6c9; }
th:first-child { border-top-left-radius: 4px; }
th:last-child { border-top-right-radius: 4px; }
tbody :deep(td) { height: 34px; box-sizing: border-box; padding: 0 16px; vertical-align: top; border-bottom: 1px solid #ddd6c9; overflow-wrap: anywhere; }
tbody :deep(tr:last-child td) { border-bottom: 0; }
tbody :deep(tr:hover td) { background: #fff6ea; }
.new-product-row td { background: #fff4e6; }
.new-product-actions { position: relative; display: flex; align-items: center; gap: 6px; }
.add-product-row { margin-top: 8px; padding: 4px 0; position: sticky; left: 0; width: max-content; }
.product-pagination { display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; min-height: 48px; gap: 8px; }
.product-pagination > div { display: flex; align-items: center; gap: 10px; }
.table-message { color: #6f6a61; text-align: center; height: 80px; vertical-align: middle; }
.page-message, .list-message { margin: 0; padding: 12px 0; color: #6f6a61; }
.product-catalog-page > .page-message { padding: 16px; }
.error-message { margin: 4px 0; color: #b53333; overflow-wrap: anywhere; }
</style>
