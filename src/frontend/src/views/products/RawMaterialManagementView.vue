<script setup lang="ts">
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
  <section class="material-catalog-page" aria-label="原料管理">
    <p v-if="!canView" class="page-message" role="alert">无权查看原料管理</p>
    <div v-else-if="optionsError" class="page-message" role="alert">{{ optionsError }} <button type="button" @click="initialize">重新加载</button></div>
    <template v-else>
      <aside class="catalog-sidebar" aria-label="品名列表">
        <MaterialCatalogSelect v-model="category" ariaLabel="原料类别" :options="categoryOptions"
          :placeholder="optionsLoading ? '加载分类中…' : '暂无分类'" :disabled="optionsLoading || navigationLocked" @change="changeCategory" />
        <div class="catalog-search"><Search aria-hidden="true" /><input v-model="search" type="search" aria-label="搜索品名" placeholder="搜索品名" :disabled="optionsLoading || navigationLocked" @input="searchNames" /></div>
        <button v-if="canAdd" type="button" class="add-name" data-testid="create-name" :disabled="!category || optionsLoading || navigationLocked" @click="startName">新增品名</button>
        <form v-if="addingName" class="new-name-form" @submit.prevent="saveName">
          <input v-model="newName" aria-label="新品名" placeholder="输入新品名" :disabled="creating" />
          <MaterialCatalogSelect v-if="templateOptions.length > 1" v-model="newTemplate" ariaLabel="品名模板"
            :options="templateOptions" placeholder="选择品名模板" :disabled="creating" />
          <div class="new-name-actions"><button type="button" class="primary-button" data-testid="save-name" :disabled="creating" @click="saveName">{{ creating ? '保存中' : '保存' }}</button><button type="button" :disabled="creating" @click="addingName = false">取消</button></div>
          <p v-if="createError" class="error-message" role="alert">{{ createError }}</p>
        </form>
        <div v-if="listError" class="error-message" role="alert">{{ listError }} <button type="button" :disabled="navigationLocked" @click="loadList()">重试</button></div>
        <nav class="material-names" data-testid="material-names" :aria-busy="listLoading">
          <button v-for="item in names" :key="item.id" type="button" :title="item.name" :data-catalog-id="item.id" :class="{ selected: selectedId === item.id }"
            :aria-current="selectedId === item.id ? 'true' : undefined" :disabled="navigationLocked || listLoading" @click="selectCatalog(item.id)">{{ item.name }}</button>
          <span v-if="!names.length && !listLoading && !optionsLoading && !listError" class="list-empty">暂无品名</span>
          <span v-if="listLoading" class="list-empty" role="status">加载中…</span>
        </nav>
        <div v-if="totalPages > 1" class="list-pagination">
          <button type="button" aria-label="上一页品名" :disabled="page <= 1 || navigationLocked || listLoading" @click="changePage(page - 1)">‹</button>
          <span>{{ page }} / {{ totalPages }}</span>
          <button type="button" aria-label="下一页品名" :disabled="page >= totalPages || navigationLocked || listLoading" @click="changePage(page + 1)">›</button>
        </div>
      </aside>
      <main class="catalog-detail" :data-catalog-id="catalog?.id" :aria-busy="detailLoading">
        <div v-if="versionWarning" class="version-warning" data-testid="version-warning" role="alert">{{ versionWarning }} <button type="button" data-testid="reload-detail" :disabled="navigationLocked || detailLoading" @click="selectCatalog(selectedId, true)">重新读取</button></div>
        <div v-if="detailError" class="error-message" role="alert">{{ detailError }} <button type="button" :disabled="navigationLocked || detailLoading" @click="selectCatalog(selectedId, true)">重试</button></div>
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
                        <template #label="{ remove, busy }"><span class="shape-label">{{ shape.value }}<button v-if="canChange" type="button" class="delete-shape" data-action="delete" :aria-label="`删除${shape.value}`" :title="`删除${shape.value}`" :disabled="editingDisabled || busy" @click="remove(shape.id)"><Delete aria-hidden="true" /></button></span></template>
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

<style scoped>
.material-catalog-page { display: flex; gap: 8px; height: 100%; min-height: 0; padding: 0; overflow: hidden; box-sizing: border-box; background: #f7f5f2; color: #17191c; font-size: 13px; line-height: 1.5; }
.catalog-sidebar, .catalog-detail { box-sizing: border-box; border: 1px solid #ece8e2; border-radius: 5px; background: #fcfbf9; }
.catalog-sidebar { width: 240px; flex: 0 0 240px; display: flex; flex-direction: column; gap: 8px; padding: 16px; min-height: 0; overflow-y: auto; }
button, input { font: inherit; }
button { cursor: pointer; }
button:disabled, input:disabled { cursor: not-allowed; opacity: 1; }
.catalog-sidebar > .material-catalog-select { flex-shrink: 0; }
.catalog-search input, .new-name-form input { width: 100%; height: 32px; min-height: 32px; box-sizing: border-box; border: 1px solid #ddd6c9; border-radius: 5px; padding: 0 10px; background: #fcfbf7; color: #1f1d18; }
.catalog-search { position: relative; flex-shrink: 0; }
.catalog-search svg { position: absolute; top: calc(50% - 8px); left: 10px; width: 16px; height: 16px; color: #6f6a61; pointer-events: none; }
.catalog-search input { padding-left: 34px; }
.catalog-sidebar input::placeholder { color: #968f84; opacity: 1; }
.add-name { height: 32px; min-height: 32px; border: 1px solid #ff510a; border-radius: 5px; background: transparent; color: #f04b09; font-weight: 600; }
.add-name:hover:not(:disabled) { background: #fff0e2; }
.material-names { flex: 1; min-height: 90px; overflow-y: auto; }
.material-names > button { display: block; box-sizing: border-box; width: 100%; height: 32px; min-height: 32px; padding: 4px 10px; border: 0; border-bottom: 1px solid #efede9; border-left: 4px solid transparent; border-radius: 5px; text-align: left; color: #17191c; background: transparent; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.material-names > button:hover:not(:disabled):not(.selected) { background: #f5f2ed; }
.material-names > button.selected { background: #fff0e2; border-left-color: #ff510a; border-bottom-color: transparent; color: #17191c; font-weight: 600; }
.list-empty { display: block; padding: 10px 14px; color: #85888d; }
.catalog-detail { flex: 1; min-width: 0; min-height: 0; overflow-y: auto; padding: 16px; }
h2 { font-size: 17px; line-height: 24px; font-weight: 600; margin: 0 0 12px; }
.spray-attributes { margin-top: 12px; padding-top: 12px; border-top: 1px solid #dcd8d2; }
.section-title { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; }
.section-title h2 { margin: 0; }
.spray-toggle { display: flex; align-items: center; gap: 6px; color: #17191c; cursor: pointer; }
.spray-toggle input { width: 15px; height: 15px; margin: 0; accent-color: #ff510a; }
.section-group { display: flex; align-items: flex-start; gap: 12px; margin: 12px 0; }
.section-labels { display: flex; flex: 0 0 120px; flex-direction: column; gap: 8px; padding-top: 4px; }
.section-labels > span { display: flex; align-items: center; gap: 12px; min-height: 32px; }
.section-labels > span::after { content: ''; flex: 1; border-top: 1px dashed #dadce0; }
.section-body { flex: 1; min-width: 0; max-width: 820px; }
.shape-dimensions { flex: 1; min-width: 0; padding-left: 12px; border-left: 1px solid #dcd8d2; }
.shape-dimensions :deep(.attribute-label) { width: 84px; }
.shape-dimensions :deep(.attribute-label::after) { display: none; }
.shape-heading { max-width: 100%; }
.shape-heading :deep(.attribute-label) { display: none; }
.shape-label { display: flex; align-items: center; overflow-wrap: anywhere; }
.delete-shape { display: inline-flex; align-items: center; justify-content: center; opacity: 0; pointer-events: none; flex: 0 0 32px; width: 32px; height: 32px; padding: 0; border: 0; border-radius: 5px; background: transparent; color: #55595e; }
.delete-shape svg { width: 16px; height: 16px; }
.shape-label:hover .delete-shape, .shape-label:focus-within .delete-shape { opacity: 1; pointer-events: auto; }
.dimension-hint { margin: 4px 0; line-height: 32px; color: #85888d; }
.new-name-form { display: flex; flex-direction: column; gap: 8px; padding: 4px 0; }
.new-name-actions { display: flex; gap: 8px; }
.new-name-actions button, .list-pagination button, .page-message button, .error-message button, .version-warning button { height: 32px; border: 1px solid #dadce0; border-radius: 5px; background: #fff; padding: 0 10px; color: #17191c; }
.new-name-actions .primary-button { color: #f04b09; background: #fff; border-color: #ff510a; }
.list-pagination { display: flex; align-items: center; justify-content: space-between; }
.page-message { margin: 0; padding: 10px 0; color: #85888d; }
.material-catalog-page > .page-message { padding: 24px; }
.error-message { margin: 0 0 10px; color: #b42318; }
.version-warning { margin-bottom: 14px; padding: 8px 10px; border: 1px solid #edc58b; border-radius: 5px; background: #fff7e8; color: #80551d; }
.catalog-search input:disabled, .new-name-form input:disabled, .catalog-sidebar button:disabled, .version-warning button:disabled, .error-message button:disabled { color: #6f6a61; border-color: #ddd6c9; background: #e8e1d5; }
.catalog-sidebar input:focus { border-color: #3898ec; }
button:focus-visible, input:focus-visible { outline: 2px solid #3898ec; outline-offset: 2px; }
@media (hover: none) { .delete-shape { opacity: 1; pointer-events: auto; } }
</style>
