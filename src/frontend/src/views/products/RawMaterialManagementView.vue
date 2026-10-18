<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Delete, Search } from '@element-plus/icons-vue'
import MaterialAttributeOptions from '@/components/products/MaterialAttributeOptions.vue'
import MaterialCatalogSelect from '@/components/products/MaterialCatalogSelect.vue'
import { useAuthStore } from '@/stores/auth'
import {
  addMaterialAllowedUnit, addMaterialAttributeValue, createMaterialCatalog, deleteMaterialAllowedUnit,
  deleteMaterialAttributeValue, fetchMaterialCatalog, fetchMaterialCatalogOptions, fetchMaterialCatalogs,
  materialCatalogError, materialCatalogErrorStatus, updateMaterialCatalog,
} from '@/api/materialCatalog'
import type {
  MaterialCatalog, MaterialCatalogOptions, MaterialCatalogSummary, MaterialFieldDefinition,
  MaterialScope, VersionedMaterialCatalog,
} from '@/types/materialCatalog'

const auth = useAuthStore()
const canView = computed(() => auth.hasPermission('material_catalog.view_materialcatalog'))
const canAdd = computed(() => auth.hasPermission('material_catalog.add_materialcatalog'))
const canChange = computed(() => auth.hasPermission('material_catalog.change_materialcatalog'))
const definitions = ref<MaterialCatalogOptions>()
const category = ref('')
const search = ref('')
const names = ref<MaterialCatalogSummary[]>([])
const page = ref(1)
const totalPages = ref(0)
const selectedId = ref('')
const catalog = ref<MaterialCatalog>()
const etag = ref('')
const optionsLoading = ref(false)
const listLoading = ref(false)
const detailLoading = ref(false)
const optionsError = ref('')
const listError = ref('')
const detailError = ref('')
const versionWarning = ref('')
const sprayError = ref('')
const pendingWrites = ref(0)
const creating = ref(false)
const addingName = ref(false)
const newName = ref('')
const newTemplate = ref('')
const createError = ref('')
const categoryDefinition = computed(() => definitions.value?.categories.find(item => item.key === category.value))
const categoryOptions = computed(() => definitions.value?.categories.map(item => ({ value: item.key, label: item.label })) ?? [])
const templateOptions = computed(() => categoryDefinition.value?.templates.map(item => ({ value: item.key, label: item.label })) ?? [])
const template = computed(() => definitions.value?.categories.find(item => item.key === catalog.value?.category_key)
  ?.templates.find(item => item.key === catalog.value?.template_key))
const baseFields = computed(() => template.value?.fields.filter(field => field.kind !== 'dimension') ?? [])
const dimensionFields = computed(() => template.value?.fields.filter(field => field.kind === 'dimension') ?? [])
const shapes = computed(() => catalog.value?.values.filter(value => value.scope === 'BASE' &&
  template.value?.fields.some(field => field.key === value.field_key && field.kind === 'shape')) ?? [])
const navigationLocked = computed(() => pendingWrites.value > 0 || creating.value)
const editingDisabled = computed(() => detailLoading.value || !!versionWarning.value || !etag.value)
let detailSequence = 0
let listSequence = 0
let optionsSequence = 0
let writeQueue: Promise<void> = Promise.resolve()
let searchTimer: ReturnType<typeof setTimeout> | undefined
let appliedSearch = ''

function applyDetail(result: VersionedMaterialCatalog) {
  catalog.value = result.data
  etag.value = result.etag
  versionWarning.value = result.etag ? '' : '未取得档案版本，请重新读取后再保存。'
  names.value = names.value.map(item => item.id === result.data.id ? { ...item, ...result.data } : item)
}
async function selectCatalog(id: string, reload = false) {
  if (navigationLocked.value || listLoading.value || (!reload && id === selectedId.value)) return
  const sequence = ++detailSequence
  selectedId.value = id
  if (!reload) { catalog.value = undefined; etag.value = ''; versionWarning.value = ''; sprayError.value = '' }
  detailLoading.value = true
  detailError.value = ''
  try {
    const result = await fetchMaterialCatalog(id)
    if (sequence === detailSequence) applyDetail(result)
  } catch (issue) {
    if (sequence === detailSequence) {
      detailError.value = materialCatalogError(issue)
      etag.value = ''
    }
  } finally { if (sequence === detailSequence) detailLoading.value = false }
}
async function loadList(preserveSelection = false) {
  if (!category.value) return
  const sequence = ++listSequence
  listLoading.value = true
  listError.value = ''
  if (!preserveSelection) {
    ++detailSequence
    selectedId.value = ''
    catalog.value = undefined
    etag.value = ''
    detailLoading.value = false
    detailError.value = ''
    versionWarning.value = ''
  }
  try {
    const query = search.value.trim()
    const result = await fetchMaterialCatalogs({ category: category.value, q: query, page: page.value, page_size: 50 })
    if (sequence !== listSequence) return
    appliedSearch = query
    names.value = result.data
    totalPages.value = result.meta.total_pages
    listLoading.value = false
    if (!preserveSelection && result.data[0]) await selectCatalog(result.data[0].id)
  } catch (issue) {
    if (sequence === listSequence) { names.value = []; listError.value = materialCatalogError(issue) }
  } finally { if (sequence === listSequence) listLoading.value = false }
}
async function initialize() {
  if (!canView.value) return
  const sequence = ++optionsSequence
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const result = await fetchMaterialCatalogOptions()
    if (sequence !== optionsSequence) return
    definitions.value = result
    category.value = result.categories[0]?.key ?? ''
    await loadList()
  } catch (issue) { if (sequence === optionsSequence) optionsError.value = materialCatalogError(issue) }
  finally { if (sequence === optionsSequence) optionsLoading.value = false }
}
function changeCategory() {
  if (navigationLocked.value) return
  clearTimeout(searchTimer)
  searchTimer = undefined
  search.value = ''
  page.value = 1
  addingName.value = false
  void loadList()
}
function applyCatalogFilters() {
  if (navigationLocked.value || optionsLoading.value) return
  clearTimeout(searchTimer)
  searchTimer = undefined
  page.value = 1
  void loadList()
}

function resetCatalogFilters() {
  if (navigationLocked.value || optionsLoading.value) return
  category.value = definitions.value?.categories[0]?.key ?? ''
  changeCategory()
}

function searchNames() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchTimer = undefined
    if (navigationLocked.value) return
    page.value = 1
    void loadList()
  }, 250)
}
function cancelPendingSearch() {
  if (searchTimer === undefined) return
  clearTimeout(searchTimer)
  searchTimer = undefined
  // 写入优先保留当前档案和草稿；取消未执行的筛选时同步恢复列表对应的搜索词。
  search.value = appliedSearch
}
function changePage(nextPage: number) {
  if (navigationLocked.value || listLoading.value) return
  page.value = nextPage
  void loadList()
}

// 各行共享主档版本：排队时不捕获旧 ETag，实际执行时读取上一写入返回的新版本。
function write(action: (id: string, version: string) => Promise<VersionedMaterialCatalog>): Promise<void> {
  const id = selectedId.value
  const sequence = detailSequence
  cancelPendingSearch()
  pendingWrites.value += 1
  const result = writeQueue.then(async () => {
    if (!canChange.value || selectedId.value !== id || sequence !== detailSequence || !catalog.value) {
      throw new Error('当前档案已切换或无修改权限，请重新读取。')
    }
    if (versionWarning.value || !etag.value) throw new Error('请重新读取档案后再保存。')
    try {
      const response = await action(id, etag.value)
      if (selectedId.value === id && sequence === detailSequence) applyDetail(response)
    } catch (issue) {
      if ([412, 428].includes(materialCatalogErrorStatus(issue) ?? 0)) versionWarning.value = materialCatalogError(issue)
      throw issue
    }
  }).finally(() => { pendingWrites.value -= 1 })
  // 保留原请求的拒绝结果给行内错误提示，仅恢复队列以允许用户处理错误后重试。
  writeQueue = result.catch(() => undefined)
  return result
}
function optionItems(field: MaterialFieldDefinition, scope: MaterialScope, parentId?: string) {
  if (field.kind === 'unit') return (catalog.value?.units ?? []).filter(unit => unit.scope === scope).map(unit => ({ id: unit.id, label: unit.unit_name }))
  return (catalog.value?.values ?? []).filter(value => value.scope === scope && value.field_key === field.key &&
    (value.parent_id ?? '') === (parentId ?? '')).map(value => ({ id: value.id, label: value.value }))
}
function saveOption(field: MaterialFieldDefinition, scope: MaterialScope, value: string, parentId?: string) {
  return write((id, version) => field.kind === 'unit'
    ? addMaterialAllowedUnit(id, { scope, unit_id: value }, version)
    : addMaterialAttributeValue(id, { scope, field_key: field.key, value, parent_id: parentId ?? null }, version))
}
function removeOption(field: MaterialFieldDefinition, optionId: string) {
  return write((id, version) => field.kind === 'unit'
    ? deleteMaterialAllowedUnit(id, optionId, version) : deleteMaterialAttributeValue(id, optionId, version))
}
async function toggleSpray(event: Event) {
  const checkbox = event.target as HTMLInputElement
  const enabled = checkbox.checked
  checkbox.checked = catalog.value?.spray_enabled ?? false
  if (!canChange.value || editingDisabled.value || navigationLocked.value) return
  sprayError.value = ''
  try { await write((id, version) => updateMaterialCatalog(id, { spray_enabled: enabled }, version)) }
  catch (issue) { sprayError.value = materialCatalogError(issue) }
}
function startName() {
  addingName.value = true
  newName.value = ''
  createError.value = ''
  newTemplate.value = categoryDefinition.value?.templates.length === 1 ? categoryDefinition.value.templates[0]!.key : ''
}
async function saveName() {
  if (!canAdd.value || navigationLocked.value) return
  if (!newName.value.trim()) { createError.value = '请输入品名。'; return }
  if (!categoryDefinition.value?.templates.some(item => item.key === newTemplate.value)) { createError.value = '请选择品名模板。'; return }
  cancelPendingSearch()
  creating.value = true
  createError.value = ''
  try {
    const result = await createMaterialCatalog({ name: newName.value.trim(), category_key: category.value, template_key: newTemplate.value })
    ++detailSequence
    selectedId.value = result.data.id
    applyDetail(result)
    detailError.value = ''
    detailLoading.value = false
    addingName.value = false
    search.value = ''
    page.value = 1
    await loadList(true)
    if (!names.value.some(item => item.id === result.data.id)) names.value.unshift(result.data)
  } catch (issue) { createError.value = materialCatalogError(issue) }
  finally { creating.value = false }
}
onMounted(initialize)
onBeforeUnmount(() => { ++detailSequence; ++listSequence; ++optionsSequence; clearTimeout(searchTimer) })
</script>

<template>
  <section class="material-catalog-page erp-glass-list erp-glass-list--catalog" aria-label="原料管理">
    <p v-if="!canView" class="page-message" role="alert">无权查看原料管理</p>
    <div v-else-if="optionsError" class="page-message" role="alert">{{ optionsError }} <button class="erp-list-button erp-button-motion" type="button" @click="initialize">重新加载</button></div>
    <template v-else>
      <aside v-glass-spotlight class="catalog-sidebar erp-list-filter" aria-label="品名列表">
        <MaterialCatalogSelect v-model="category" ariaLabel="原料类别" :options="categoryOptions"
          :placeholder="optionsLoading ? '加载分类中…' : '暂无分类'" :disabled="optionsLoading || navigationLocked" @change="changeCategory" />
        <div class="catalog-search"><Search aria-hidden="true" /><input class="erp-list-control" v-model="search" type="search" aria-label="搜索品名" placeholder="搜索品名" :disabled="optionsLoading || navigationLocked" @input="searchNames" /></div>
        <div class="erp-list-filter-actions"><button class="erp-list-button erp-button-motion" type="button" :disabled="optionsLoading || navigationLocked" @click="resetCatalogFilters">重置</button><button type="button" class="erp-list-button erp-button-motion erp-list-button--primary" :disabled="optionsLoading || navigationLocked" @click="applyCatalogFilters">应用筛选</button></div>
        <button v-if="canAdd" type="button" class="erp-list-button erp-button-motion add-name" data-testid="create-name" :disabled="!category || optionsLoading || navigationLocked" @click="startName">新增品名</button>
        <form v-if="addingName" class="new-name-form" @submit.prevent="saveName">
          <input class="erp-list-control" v-model="newName" aria-label="新品名" placeholder="输入新品名" :disabled="creating" />
          <MaterialCatalogSelect v-if="templateOptions.length > 1" v-model="newTemplate" ariaLabel="品名模板"
            :options="templateOptions" placeholder="选择品名模板" :disabled="creating" />
          <div class="new-name-actions"><button type="button" class="erp-list-button erp-button-motion erp-list-button--primary primary-button" data-testid="save-name" :disabled="creating" @click="saveName">{{ creating ? '保存中' : '保存' }}</button><button class="erp-list-button erp-button-motion" type="button" :disabled="creating" @click="addingName = false">取消</button></div>
          <p v-if="createError" class="error-message" role="alert">{{ createError }}</p>
        </form>
        <div v-if="listError" class="error-message" role="alert">{{ listError }} <button class="erp-list-button erp-button-motion" type="button" :disabled="navigationLocked" @click="loadList()">重试</button></div>
        <nav class="material-names erp-list-catalog-nav" data-testid="material-names" aria-label="原料品名列表" tabindex="0" :aria-busy="listLoading">
          <button v-for="item in names" :key="item.id" type="button" :title="item.name" :data-catalog-id="item.id" :class="{ selected: selectedId === item.id }"
            :aria-current="selectedId === item.id ? 'true' : undefined" :disabled="navigationLocked || listLoading" @click="selectCatalog(item.id)">{{ item.name }}</button>
          <span v-if="!names.length && !listLoading && !optionsLoading && !listError" class="list-empty">暂无品名</span>
          <span v-if="listLoading" class="list-empty" role="status">加载中…</span>
        </nav>
        <div v-if="totalPages > 1" class="list-pagination erp-list-footer">
          <button class="erp-list-button erp-button-motion" type="button" aria-label="上一页品名" :disabled="page <= 1 || navigationLocked || listLoading" @click="changePage(page - 1)">‹</button>
          <span>{{ page }} / {{ totalPages }}</span>
          <button class="erp-list-button erp-button-motion" type="button" aria-label="下一页品名" :disabled="page >= totalPages || navigationLocked || listLoading" @click="changePage(page + 1)">›</button>
        </div>
      </aside>
      <main class="catalog-detail erp-list-data" :data-catalog-id="catalog?.id" :aria-busy="detailLoading">
        <header class="erp-list-heading"><h1>原料管理</h1></header>
        <div v-if="versionWarning" class="version-warning" data-testid="version-warning" role="alert">{{ versionWarning }} <button class="erp-list-button erp-button-motion" type="button" data-testid="reload-detail" :disabled="navigationLocked || detailLoading" @click="selectCatalog(selectedId, true)">重新读取</button></div>
        <div v-if="detailError" class="error-message" role="alert">{{ detailError }} <button class="erp-list-button erp-button-motion" type="button" :disabled="navigationLocked || detailLoading" @click="selectCatalog(selectedId, true)">重试</button></div>
        <p v-if="detailLoading && !catalog" class="page-message" role="status">正在读取属性…</p>
        <template v-if="catalog && template">
          <section :key="catalog.id" class="base-attributes" aria-label="基本属性">
            <h2>基本属性</h2>
            <template v-for="field in baseFields" :key="field.key">
              <div v-if="field.kind === 'shape'" class="section-group">
                <div class="section-labels"><span>{{ field.label }}</span><span v-for="dimension in dimensionFields" :key="dimension.key">{{ dimension.label }}</span></div>
                <div class="section-body">
                  <div class="shape-dimensions">
                    <template v-for="dimension in dimensionFields" :key="dimension.key">
                      <MaterialAttributeOptions v-for="shape in shapes" :key="shape.id" :data-shape-id="shape.id" :label="shape.value" :field-key="dimension.key" :kind="dimension.kind" scope="BASE" :parent-id="shape.id"
                        :options="optionItems(dimension, 'BASE', shape.id)" :available-units="[]" :readonly="!canChange" :disabled="editingDisabled"
                        :on-save="value => saveOption(dimension, 'BASE', value, shape.id)" :on-remove="id => removeOption(dimension, id)">
                        <template #label="{ remove, busy }"><span class="shape-label">{{ shape.value }}<button v-if="canChange" type="button" class="erp-list-button erp-button-motion delete-shape" data-action="delete" :aria-label="`删除${shape.value}`" :title="`删除${shape.value}`" :disabled="editingDisabled || busy" @click="remove(shape.id)"><Delete aria-hidden="true" /></button></span></template>
                      </MaterialAttributeOptions>
                      <p v-if="!shapes.length" class="dimension-hint">先添加{{ field.label }}，再维护对应{{ dimension.label }}。</p>
                    </template>
                    <MaterialAttributeOptions v-show="canChange" class="shape-heading" :label="field.label" :field-key="field.key" :kind="field.kind" scope="BASE"
                      :options="[]" :available-units="[]" :readonly="!canChange" :disabled="editingDisabled"
                      :on-save="value => saveOption(field, 'BASE', value)" :on-remove="id => removeOption(field, id)" />
                  </div>
                </div>
              </div>
              <MaterialAttributeOptions v-else :label="field.label" :field-key="field.key" :kind="field.kind" scope="BASE"
                :options="optionItems(field, 'BASE')" :available-units="definitions?.units ?? []" :readonly="!canChange" :disabled="editingDisabled"
                :on-save="value => saveOption(field, 'BASE', value)" :on-remove="id => removeOption(field, id)" />
            </template>
          </section>
          <section v-if="template.supports_spray" :key="`${catalog.id}:spray`" class="spray-attributes" aria-label="喷塑属性">
            <div class="section-title"><h2>喷塑属性</h2><label class="spray-toggle"><input type="checkbox" data-testid="spray-enabled" :checked="catalog.spray_enabled" :disabled="!canChange || editingDisabled || navigationLocked" @change="toggleSpray" /> 喷塑</label></div>
            <p v-if="sprayError" class="error-message" role="alert">{{ sprayError }}</p>
            <template v-if="catalog.spray_enabled">
              <MaterialAttributeOptions v-for="field in definitions?.spray_fields" :key="field.key" :label="field.label" :field-key="field.key" :kind="field.kind" scope="SPRAY"
                :options="optionItems(field, 'SPRAY')" :available-units="definitions?.units ?? []" :readonly="!canChange" :disabled="editingDisabled"
                :on-save="value => saveOption(field, 'SPRAY', value)" :on-remove="id => removeOption(field, id)" />
            </template>
          </section>
        </template>
        <p v-else-if="catalog && !template" class="error-message" role="alert">找不到该品名的属性模板，请刷新分类定义。</p>
        <p v-else-if="!detailLoading && !detailError" class="page-message">{{ optionsLoading || listLoading ? '加载中…' : '选择或新增品名，维护属性选项。' }}</p>
      </main>
    </template>
  </section>
</template>

<style scoped lang="scss">
.material-catalog-page { grid-template-rows: minmax(0, 1fr); }
.material-catalog-page > .page-message { grid-column: 1 / -1; }
.material-catalog-page.erp-glass-list--catalog > .catalog-sidebar { display: flex; flex-direction: column; gap: 8px; min-height: 0; overflow: visible; }
.catalog-sidebar > :not(.material-names) { flex-shrink: 0; min-width: 0; }
.catalog-search { position: relative; }
.catalog-search svg { position: absolute; top: 8px; left: 10px; width: 16px; height: 16px; color: var(--erp-input-placeholder); pointer-events: none; }
.catalog-search input { width: 100%; padding-left: 34px; }
.catalog-sidebar .erp-list-filter-actions { flex-wrap: wrap; margin-left: 0; }
.material-names { flex: 1; min-width: 0; min-height: 0; overflow-x: hidden; overflow-y: auto; scrollbar-width: none; }
.material-names::-webkit-scrollbar { display: none; }
.catalog-detail { overflow: hidden; }
h2 { min-width: 0; margin: 0; font-size: 17px; line-height: 24px; font-weight: 600; }
.page-message, .list-message, .list-empty { margin: 0; padding: 12px 0; color: var(--erp-color-text-secondary); }
.error-message { margin: 4px 0; color: var(--erp-color-danger); overflow-wrap: anywhere; }
.catalog-detail { overflow-y: auto; }
.material-names > button { position: relative; display: block; width: 100%; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.material-names > button.selected, .material-names > button.selected:hover { background: color-mix(in srgb, var(--erp-menu-selected-background) 88%, var(--erp-menu-accent)); color: var(--erp-menu-accent); }
.material-names > button.selected::before { content: ''; position: absolute; inset: 6px auto 6px 0; width: 3px; border-radius: 0 3px 3px 0; background: var(--erp-menu-accent); }
.spray-attributes { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--erp-color-border); }
.section-title { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; }
.base-attributes > h2 { margin-bottom: 12px; }
.spray-toggle { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.spray-toggle input { width: 15px; height: 15px; margin: 0; accent-color: var(--erp-color-brand); }
.section-group { display: flex; align-items: flex-start; gap: 12px; margin: 12px 0; }
.section-labels { display: flex; flex: 0 0 120px; flex-direction: column; gap: 8px; padding-top: 4px; }
.section-labels > span { display: flex; align-items: center; gap: 12px; min-height: 32px; }
.section-labels > span::after { content: ''; flex: 1; border-top: 1px dashed var(--erp-color-border); }
.section-body { flex: 1; min-width: 0; max-width: 820px; }
.shape-dimensions { flex: 1; min-width: 0; padding-left: 12px; border-left: 1px solid var(--erp-color-border); }
.shape-dimensions :deep(.attribute-label) { width: 84px; }
.shape-dimensions :deep(.attribute-label::after), .shape-heading :deep(.attribute-label) { display: none; }
.shape-heading { max-width: 100%; }
.shape-label { display: flex; align-items: center; overflow-wrap: anywhere; }
.delete-shape { display: inline-flex; align-items: center; justify-content: center; opacity: 0; pointer-events: none; flex: 0 0 32px; width: 32px; padding: 0; }
.delete-shape svg { width: 16px; height: 16px; }
.shape-label:hover .delete-shape, .shape-label:focus-within .delete-shape { opacity: 1; pointer-events: auto; }
.dimension-hint { margin: 4px 0; line-height: 32px; color: var(--erp-color-text-secondary); }
.new-name-form { display: flex; flex-direction: column; gap: 8px; padding: 4px 0; }
.new-name-actions { display: flex; gap: 8px; }
.version-warning { margin-bottom: 14px; padding: 8px 10px; border: 1px solid var(--erp-tag-warning-border); border-radius: var(--erp-radius-control); background: var(--erp-tag-warning-background); color: var(--erp-tag-warning-text); }
@media (hover: none) { .delete-shape { opacity: 1; pointer-events: auto; } }
</style>
