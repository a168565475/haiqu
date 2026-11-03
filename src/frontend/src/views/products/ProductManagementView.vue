<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Check, Delete, Plus, Search } from '@element-plus/icons-vue'
import MaterialCatalogSelect from '@/components/products/MaterialCatalogSelect.vue'
import ProductCatalogRow from '@/components/products/ProductCatalogRow.vue'
import ProductCatalogSaveButton from '@/components/products/ProductCatalogSaveButton.vue'
import { useAuthStore } from '@/stores/auth'
import { createClientUuid } from '@/utils/clientUuid'
import {
  createProductCatalogEditor, deleteProductCatalogName, fetchProductCatalogEditor,
  fetchProductCatalogNames, fetchProductCatalogOptions, productCatalogError,
  productCatalogErrorStatus, saveProductCatalogEditor,
} from '@/api/productCatalog'
import {
  productCatalogFields, type ProductCatalog, type ProductCatalogDraftRow, type ProductCatalogEditorRow,
  type ProductCatalogName, type ProductCatalogOptions, type VersionedProductCatalogEditor,
} from '@/types/productCatalog'

const auth = useAuthStore()
const canView = computed(() => auth.hasPermission('product_catalog.view_productcatalog'))
const canAdd = computed(() => auth.hasPermission('product_catalog.add_productcatalog'))
const canChange = computed(() => auth.hasPermission('product_catalog.change_productcatalog'))
const options = ref<ProductCatalogOptions>()
const category = ref('')
const categoryControlKey = ref(0)
const search = ref('')
const names = ref<ProductCatalogName[]>([])
const selected = ref<ProductCatalogName>()
const newName = ref(false)
const draftName = ref('')
const products = ref<ProductCatalogDraftRow[]>([])
const baselineName = ref('')
const baselineProducts = ref<ProductCatalogEditorRow[]>([])
const baseline = ref('')
const etag = ref('')
const currentPage = ref(1)
const optionsLoading = ref(false)
const namesLoading = ref(false)
const productsLoading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const confirming = ref(false)
const optionsError = ref('')
const namesError = ref('')
const productsError = ref('')
const saveError = ref('')
const versionWarning = ref('')
const nameInput = ref<HTMLInputElement>()
const table = ref<HTMLElement>()
const navigationLocked = computed(() => saving.value || deleting.value || confirming.value)
const editorOpen = computed(() => newName.value || !!selected.value)
const canEdit = computed(() => newName.value ? canAdd.value : canChange.value)
const editorDisabled = computed(() => navigationLocked.value || productsLoading.value || !!productsError.value)
const canCreateRow = computed(() => canAdd.value && (newName.value || canChange.value))
const categoryOptions = computed(() => (options.value?.categories ?? []).map(item => ({ value: item.id, label: item.name, count: item.name_count })))
const totalPages = computed(() => Math.max(1, Math.ceil(products.value.length / 50)))
const visibleProducts = computed(() => products.value.slice((currentPage.value - 1) * 50, currentPage.value * 50))
const hasUnsavedChanges = computed(() => editorOpen.value && (newName.value || (baseline.value !== '' && signature() !== baseline.value)))
let namesSequence = 0
let detailSequence = 0
let initSequence = 0
let searchTimer: ReturnType<typeof setTimeout> | undefined
let appliedSearch = ''

function rowInput(row: ProductCatalogDraftRow): ProductCatalogEditorRow {
  return {
    ...(row.id ? { id: row.id } : {}),
    product_code: row.product_code, item_number: row.item_number, specification: row.specification,
    unit: row.unit, scale: row.scale, colors: [...row.colors], materials: [...row.materials], thicknesses: [...row.thicknesses],
  }
}
function toDraft(product: ProductCatalog): ProductCatalogDraftRow {
  return {
    key: product.id, id: product.id, product_code: product.product_code, item_number: product.item_number,
    specification: product.specification, unit: product.unit, scale: product.scale,
    colors: product.colors.map(color => color.value), materials: [...(product.materials ?? [])], thicknesses: [...(product.thicknesses ?? [])],
  }
}
function signature() { return JSON.stringify({ name: draftName.value, products: products.value.map(rowInput) }) }
function cancelSearch() { clearTimeout(searchTimer); searchTimer = undefined }
async function confirmAction(message: string, title: string, confirmButtonText: string) {
  confirming.value = true
  try {
    await ElMessageBox.confirm(message, title, { confirmButtonText, cancelButtonText: '取消', type: 'warning', closeOnClickModal: false })
    return true
  } catch (action) {
    if (action === 'cancel' || action === 'close') return false
    throw action
  } finally { confirming.value = false }
}
async function canLeave(): Promise<boolean> {
  if (navigationLocked.value) return false
  if (!hasUnsavedChanges.value) return true
  return confirmAction('当前品名有未保存的修改，是否放弃并离开？', '未保存的修改', '放弃修改')
}
function resetDetail() {
  ++detailSequence
  selected.value = undefined
  newName.value = false
  draftName.value = ''
  products.value = []
  baselineName.value = ''
  baselineProducts.value = []
  baseline.value = ''
  etag.value = ''
  currentPage.value = 1
  productsLoading.value = false
  productsError.value = ''
  saveError.value = ''
  versionWarning.value = ''
}
function checkEditor(result: VersionedProductCatalogEditor, id?: string) {
  if ((id && result.data.name.id !== id) || result.data.name.category_id !== category.value ||
      result.data.products.some(product => product.name_id !== result.data.name.id)) {
    throw new Error('返回的产品档案与当前品名不一致，请重新读取。')
  }
}
function applyEditor(result: VersionedProductCatalogEditor) {
  selected.value = { ...result.data.name }
  newName.value = false
  draftName.value = result.data.name.name
  products.value = result.data.products.map(toDraft)
  baselineName.value = draftName.value
  baselineProducts.value = products.value.map(rowInput)
  baseline.value = signature()
  etag.value = result.etag
  versionWarning.value = result.etag ? '' : '未取得品名编辑版本，请重新读取后再保存。'
  productsError.value = ''
  saveError.value = ''
  currentPage.value = Math.min(currentPage.value, totalPages.value)
  const index = names.value.findIndex(item => item.id === result.data.name.id)
  if (index >= 0) names.value[index] = { ...result.data.name }
  else names.value.push({ ...result.data.name })
}
async function loadEditor(item: ProductCatalogName) {
  const request = ++detailSequence
  selected.value = item
  draftName.value = item.name
  productsLoading.value = true
  productsError.value = ''
  try {
    const result = await fetchProductCatalogEditor(item.id)
    if (request !== detailSequence) return
    checkEditor(result, item.id)
    applyEditor(result)
  } catch (error) {
    if (request === detailSequence) productsError.value = productCatalogError(error)
  } finally { if (request === detailSequence) productsLoading.value = false }
}
async function selectName(item: ProductCatalogName) {
  if ((!newName.value && selected.value?.id === item.id) || !await canLeave()) return
  cancelSearch()
  search.value = appliedSearch
  resetDetail()
  await loadEditor(item)
}
async function loadNames(preferredId?: string) {
  const request = ++namesSequence
  const categoryId = category.value
  resetDetail()
  names.value = []
  namesError.value = ''
  namesLoading.value = true
  try {
    const result = await fetchProductCatalogNames({ category_id: categoryId, q: appliedSearch })
    if (request !== namesSequence) return
    names.value = result
    const first = result.find(item => item.id === preferredId) ?? result[0]
    if (first) await loadEditor(first)
  } catch (error) {
    if (request === namesSequence) namesError.value = productCatalogError(error)
  } finally { if (request === namesSequence) namesLoading.value = false }
}
async function initialize() {
  if (!canView.value) return
  const request = ++initSequence
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const result = await fetchProductCatalogOptions()
    if (request !== initSequence) return
    options.value = result
    category.value = result.categories[0]?.id ?? ''
    if (category.value) await loadNames()
  } catch (error) {
    if (request === initSequence) optionsError.value = productCatalogError(error)
  } finally { if (request === initSequence) optionsLoading.value = false }
}
async function changeCategory(value: string) {
  cancelSearch()
  if (value === category.value) return
  if (!await canLeave()) { categoryControlKey.value += 1; return }
  category.value = value
  search.value = ''
  appliedSearch = ''
  await loadNames()
}
async function applyCatalogFilters(reset = false) {
  cancelSearch()
  if (!await canLeave()) { search.value = appliedSearch; return }
  if (reset) search.value = ''
  appliedSearch = search.value
  await loadNames()
}
function searchNames() {
  cancelSearch()
  searchTimer = setTimeout(() => { void applyCatalogFilters() }, 250)
}
async function reloadEditor() {
  cancelSearch()
  if (!selected.value || !await canLeave()) return
  const item = selected.value
  resetDetail()
  await loadEditor(item)
}
async function retryNames() { if (await canLeave()) await loadNames() }
async function startName() {
  cancelSearch()
  if (!canAdd.value || !category.value || !await canLeave()) return
  resetDetail()
  newName.value = true
  await nextTick()
  nameInput.value?.focus()
}
async function startProduct() {
  if (!canCreateRow.value || editorDisabled.value) return
  products.value.push({ key: createClientUuid(), product_code: '', item_number: '', specification: '', unit: '', scale: '', colors: [], materials: [], thicknesses: [] })
  currentPage.value = totalPages.value
  await nextTick()
  table.value?.querySelector<HTMLElement>('[data-new-product]:last-child input')?.focus()
}
function updateProduct(row: ProductCatalogDraftRow) {
  if (!canEdit.value || editorDisabled.value) return
  const index = products.value.findIndex(item => item.key === row.key)
  if (index >= 0) products.value[index] = row
}
function removeProduct(key: string) {
  if (!canEdit.value || editorDisabled.value) return
  products.value = products.value.filter(item => item.key !== key)
  currentPage.value = Math.min(currentPage.value, totalPages.value)
}
function validationError(index: number, message: string): never {
  currentPage.value = Math.floor(index / 50) + 1
  throw new Error(`第 ${index + 1} 条产品：${message}`)
}
function changedRows() {
  const previous = new Map(baselineProducts.value.map(row => [row.id, row]))
  return products.value.flatMap((draft, index) => {
    const row = rowInput(draft)
    const old = row.id ? previous.get(row.id) : undefined
    if (old && JSON.stringify(row) === JSON.stringify(old)) return []
    for (const field of productCatalogFields) {
      if (row[field.key].length > field.maxLength && row[field.key] !== old?.[field.key]) validationError(index, `${field.label}最多 ${field.maxLength} 个字。`)
    }
    if (row.unit && row.unit !== old?.unit && !options.value?.units.includes(row.unit)) validationError(index, '请选择生产维护中已有的单位。')
    for (const [key, label] of [['colors', '颜色'], ['materials', '材质'], ['thicknesses', '壁厚']] as const) {
      if (old && JSON.stringify(row[key]) === JSON.stringify(old[key])) continue
      row[key] = row[key].map(value => value.trim())
      if (row[key].some(value => !value)) validationError(index, `请填写或删除空的${label}输入框。`)
      const maxLength = key === 'thicknesses' ? 80 : 200
      if (row[key].some(value => value.length > maxLength)) validationError(index, `${label}最多 ${maxLength} 个字。`)
      if (new Set(row[key]).size !== row[key].length) validationError(index, `${label}不能重复。`)
    }
    return old && JSON.stringify(row) === JSON.stringify(old) ? [] : [row]
  })
}
async function saveDraft() {
  cancelSearch()
  if (!canEdit.value || editorDisabled.value || !editorOpen.value) return
  saveError.value = ''
  if (!draftName.value.trim()) { saveError.value = '请输入品名。'; nameInput.value?.focus(); return }
  if (draftName.value.length > 200) { saveError.value = '品名最多 200 个字。'; return }
  if (!newName.value && (!etag.value || versionWarning.value)) {
    saveError.value = '档案版本已变化或缺失，请重新读取后再保存。'
    return
  }
  let changed: ProductCatalogEditorRow[]
  try { changed = changedRows() } catch (error) { saveError.value = productCatalogError(error); return }
  if (changed.some(row => !row.id) && !canAdd.value) { saveError.value = '没有新增产品权限。'; return }
  const remaining = new Set(products.value.flatMap(row => row.id ? [row.id] : []))
  const removed = baselineProducts.value.flatMap(row => row.id && !remaining.has(row.id) ? [row.id] : [])
  if (!newName.value && !changed.length && !removed.length && draftName.value === baselineName.value) {
    baseline.value = signature()
    return
  }
  const creating = newName.value
  const id = selected.value?.id
  saving.value = true
  try {
    const result = creating
      ? await createProductCatalogEditor({ category_id: category.value, name: draftName.value, products: changed })
      : await saveProductCatalogEditor(id!, { name: draftName.value, products: changed, delete_product_ids: removed }, etag.value)
    checkEditor(result, id)
    applyEditor(result)
    if (creating) {
      const group = options.value?.categories.find(item => item.id === category.value)
      if (group) group.name_count += 1
    }
  } catch (error) {
    saveError.value = productCatalogError(error)
    if ([412, 428].includes(productCatalogErrorStatus(error) ?? 0)) versionWarning.value = saveError.value
  } finally { saving.value = false }
}
async function deleteName(item: ProductCatalogName) {
  cancelSearch()
  if (!canChange.value || navigationLocked.value) return
  saveError.value = ''
  deleting.value = true
  let deleted = false
  try {
    const result = await fetchProductCatalogEditor(item.id)
    checkEditor(result, item.id)
    if (!result.etag) throw new Error('未取得品名编辑版本，无法删除，请重新读取。')
    const dirtyWarning = selected.value?.id === item.id && hasUnsavedChanges.value ? ' 当前未保存的修改也会放弃。' : ''
    if (!await confirmAction(`删除“${result.data.name.name}”及其全部 ${result.data.products.length} 条产品？包含所有分页。${dirtyWarning}`, '删除品名', '确认删除')) return
    await deleteProductCatalogName(item.id, result.etag)
    names.value = names.value.filter(name => name.id !== item.id)
    const group = options.value?.categories.find(group => group.id === item.category_id)
    if (group) group.name_count = Math.max(0, group.name_count - 1)
    deleted = true
  } catch (error) {
    saveError.value = productCatalogError(error)
  } finally { deleting.value = false }
  if (deleted && selected.value?.id === item.id) {
    resetDetail()
    if (names.value[0]) await loadEditor(names.value[0])
  }
}
function changePage(page: number) {
  if (!navigationLocked.value && page >= 1 && page <= totalPages.value) currentPage.value = page
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (hasUnsavedChanges.value || navigationLocked.value) { event.preventDefault(); event.returnValue = '' }
}
onBeforeRouteLeave(canLeave)
onBeforeRouteUpdate(canLeave)
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void initialize() })
onBeforeUnmount(() => {
  ++initSequence; ++namesSequence; ++detailSequence
  cancelSearch()
  window.removeEventListener('beforeunload', beforeUnload)
})
defineExpose({ canLeave })
</script>

<template>
  <section class="product-catalog-page erp-glass-list erp-glass-list--catalog" aria-label="产品管理">
    <p v-if="!canView" class="page-message">无权查看产品管理</p>
    <div v-else-if="optionsError" class="error-message" role="alert">{{ optionsError }} <button class="erp-list-button erp-button-motion" type="button" @click="initialize">重新加载</button></div>
    <template v-else>
      <aside v-glass-spotlight class="catalog-sidebar erp-list-filter" aria-label="产品品名">
        <MaterialCatalogSelect :key="categoryControlKey" :model-value="category" ariaLabel="产品类别" :options="categoryOptions" :disabled="optionsLoading || navigationLocked" @change="changeCategory">
          <template #option="{ option, selected: active }"><span class="product-name-label">{{ option.label }}</span><span class="product-category-count" :data-category-count="option.value">{{ categoryOptions.find(item => item.value === option.value)?.count ?? 0 }}</span><Check v-if="active" class="product-category-check" aria-hidden="true" /></template>
        </MaterialCatalogSelect>
        <div class="catalog-search"><Search aria-hidden="true" /><input v-model="search" class="erp-list-control" type="search" aria-label="搜索品名" placeholder="搜索品名" :disabled="optionsLoading || navigationLocked" @input="searchNames" /></div>
        <div class="erp-list-filter-actions">
          <button class="erp-list-button erp-button-motion" type="button" :disabled="optionsLoading || navigationLocked" @click="applyCatalogFilters(true)">重置</button>
          <button class="erp-list-button erp-button-motion" type="button" :disabled="optionsLoading || navigationLocked" @click="applyCatalogFilters()">应用筛选</button>
        </div>
        <button v-if="canAdd" class="erp-list-button erp-list-button--primary erp-button-motion add-name" type="button" data-action="add-name" aria-label="新增品名" :disabled="optionsLoading || namesLoading || navigationLocked || !category" @click="startName"><Plus aria-hidden="true" />新增品名</button>
        <div v-if="namesError" class="error-message" role="alert">{{ namesError }} <button class="erp-list-button erp-button-motion" type="button" :disabled="navigationLocked" @click="retryNames">重试</button></div>
        <nav class="product-names erp-list-catalog-nav" data-testid="product-names" aria-label="品名列表" tabindex="0" :aria-busy="namesLoading">
          <div v-for="item in names" :key="item.id" class="product-name-row">
            <button class="name-select" type="button" :data-name-id="item.id" :title="item.name" :class="{ selected: selected?.id === item.id }" :aria-current="selected?.id === item.id ? 'true' : undefined" :disabled="navigationLocked" @click="selectName(item)">
              <span class="product-name-label">{{ item.name }}</span><span class="product-name-count">{{ item.product_count }}</span>
            </button>
            <button v-if="canChange" class="erp-list-button erp-button-motion name-delete" type="button" :aria-label="`删除品名${item.name}`" title="删除整个品名" :disabled="navigationLocked || namesLoading || productsLoading" @click="deleteName(item)"><Delete aria-hidden="true" /></button>
          </div>
          <p v-if="namesLoading" class="list-message" role="status">加载品名中…</p>
          <p v-else-if="!names.length && !optionsLoading && !namesError" class="list-message">{{ search ? '没有匹配品名，请调整搜索。' : '暂无品名' }}</p>
        </nav>
      </aside>
      <main class="catalog-detail erp-list-data" :class="{ 'catalog-detail--no-footer': totalPages <= 1 }" :data-name-id="selected?.id" :aria-busy="productsLoading">
        <header class="erp-list-heading"><h1>产品管理</h1></header>
        <template v-if="editorOpen">
          <div class="detail-heading">
            <input ref="nameInput" v-model="draftName" class="erp-list-control name-input" aria-label="品名" placeholder="输入品名" maxlength="200" :readonly="!canEdit" :disabled="editorDisabled" @keydown.enter.prevent />
            <ProductCatalogSaveButton v-if="canEdit" type="button" data-action="save-draft" label="保存" ariaLabel="保存" :loading="saving" :disabled="editorDisabled || !!versionWarning" @click="saveDraft" />
            <span class="product-count">{{ products.length }} 条产品</span>
            <button v-if="canCreateRow" class="erp-list-button erp-list-button--primary erp-button-motion" type="button" data-action="add-product" aria-label="新增产品" :disabled="editorDisabled" @click="startProduct"><Plus aria-hidden="true" />新增产品</button>
          </div>
          <div v-if="versionWarning" class="error-message" role="alert">{{ versionWarning }} <button class="erp-list-button erp-button-motion" type="button" data-action="reload" :disabled="navigationLocked || productsLoading" @click="reloadEditor">重新读取</button></div>
          <div v-if="productsError" class="error-message" role="alert">{{ productsError }} <button class="erp-list-button erp-button-motion" type="button" :disabled="navigationLocked || productsLoading" @click="reloadEditor">重试</button></div>
          <div v-if="saveError" class="error-message" role="alert">{{ saveError }}</div>
          <div class="erp-list-table-frame">
            <div ref="table" class="product-table-scroll erp-list-table-scroll" tabindex="0" aria-label="产品表格滚动区域">
              <table class="erp-table-editor product-table erp-list-native-table" aria-label="品名下的产品">
                <colgroup><col class="code-column" /><col class="item-column" /><col class="spec-column" /><col class="unit-column" /><col class="scale-column" /><col class="options-column" /><col class="options-column" /><col class="options-column" /><col class="actions-column" /></colgroup>
                <thead><tr><th v-for="field in productCatalogFields" :key="field.key" scope="col">{{ field.label }}</th><th scope="col">颜色</th><th scope="col">材质</th><th scope="col">壁厚</th><th scope="col" aria-label="操作"></th></tr></thead>
                <tbody>
                  <ProductCatalogRow v-for="product in visibleProducts" :key="product.key" :product="product" :can-change="canEdit" :disabled="editorDisabled" :units="options?.units ?? []" :scales="options?.scales ?? []" @update="updateProduct" @remove="removeProduct(product.key)" />
                  <tr v-if="!products.length"><td colspan="9" class="table-message">{{ productsLoading ? '正在读取产品…' : productsError ? '读取产品失败，请重试。' : '暂无产品，可在上方新增。' }}</td></tr>
                </tbody>
              </table>
            </div>
          </div>
          <div v-if="totalPages > 1" class="product-pagination erp-list-footer"><span>共 {{ products.length }} 条 · 每页 50 条</span><div><button class="erp-list-button erp-button-motion" type="button" aria-label="上一页产品" :disabled="currentPage <= 1 || navigationLocked || productsLoading" @click="changePage(currentPage - 1)">上一页</button><span>{{ currentPage }} / {{ totalPages }}</span><button class="erp-list-button erp-button-motion" type="button" aria-label="下一页产品" :disabled="currentPage >= totalPages || navigationLocked || productsLoading" @click="changePage(currentPage + 1)">下一页</button></div></div>
        </template>
        <template v-else><div v-if="saveError" class="error-message" role="alert">{{ saveError }}</div><p class="page-message">{{ optionsLoading || namesLoading ? '加载中…' : '选择或新增品名，维护产品。' }}</p></template>
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
.page-message, .list-message { margin: 0; padding: 12px 0; color: var(--erp-color-text-secondary); }
.error-message { margin: 4px 0; color: var(--erp-color-danger); overflow-wrap: anywhere; }
.product-catalog-page svg { width: 16px; height: 16px; flex-shrink: 0; }
.product-name-row { position: relative; }
.product-name-row .name-select { position: relative; display: flex; gap: 8px; width: 100%; padding-right: 32px; text-align: left; white-space: normal; overflow-wrap: anywhere; }
.product-name-row .name-select.selected, .product-name-row .name-select.selected:hover { background: color-mix(in srgb, var(--erp-menu-selected-background) 88%, var(--erp-menu-accent)); color: var(--erp-menu-accent); }
.product-name-row .name-select.selected::before { content: ''; position: absolute; inset: 6px auto 6px 0; width: 3px; border-radius: 0 3px 3px 0; background: var(--erp-menu-accent); }
.product-name-label { flex: 1; min-width: 0; }
.product-name-count, .product-category-count { flex-shrink: 0; white-space: nowrap; font-weight: 400; color: var(--erp-color-text-secondary); }
.product-category-check { display: flex; flex: 0 0 16px; width: 16px; height: 16px; }
.name-delete { position: absolute; top: calc(50% - 14px); right: 2px; width: 28px; height: 28px; min-height: 0; padding: 0; opacity: 0; pointer-events: none; }
.product-name-row:hover .name-delete, .product-name-row:focus-within .name-delete, .name-delete:focus-visible { opacity: 1; pointer-events: auto; }
.detail-heading { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 12px; }
.name-input { width: min(280px, 100%); min-width: 0; }
.detail-heading > .product-count, .detail-heading > .erp-list-button { flex-shrink: 0; }
.product-count { color: var(--erp-color-text-secondary); }
.product-table { min-width: 1836px; }
.code-column, .item-column { width: 190px; }.spec-column { width: 280px; }.unit-column { width: 180px; }.scale-column { width: 180px; }.options-column { width: 260px; }.actions-column { width: 36px; }
.product-table :deep(td) { vertical-align: top; overflow-wrap: anywhere; }
.product-pagination > div { display: flex; align-items: center; gap: 10px; }
.table-message { text-align: center; vertical-align: middle; }
@media (hover: none) { .name-delete { opacity: 1; pointer-events: auto; } }
</style>
