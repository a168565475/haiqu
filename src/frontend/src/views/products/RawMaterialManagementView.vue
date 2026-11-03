<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch, type ComponentPublicInstance } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Delete, Search } from '@element-plus/icons-vue'
import MaterialAttributeOptions from '@/components/products/MaterialAttributeOptions.vue'
import MaterialColorOptions from '@/components/products/MaterialColorOptions.vue'
import MaterialCatalogSelect from '@/components/products/MaterialCatalogSelect.vue'
import { useAuthStore } from '@/stores/auth'
import { createClientUuid } from '@/utils/clientUuid'
import {
  archiveMaterialCatalog, createMaterialCatalog, fetchMaterialCatalog, fetchMaterialCatalogOptions,
  fetchMaterialCatalogs, fetchPublicMaterialOptions, materialCatalogError, materialCatalogErrorStatus, saveMaterialCatalog,
} from '@/api/materialCatalog'
import type {
  MaterialAttributeValue, MaterialCatalog, MaterialCatalogDraft, MaterialCatalogOptions, MaterialCatalogSummary,
  MaterialFieldDefinition, MaterialScope, PublicMaterialOptions, VersionedMaterialCatalog,
} from '@/types/materialCatalog'

type AttributeEditor = { flushDraft: () => Promise<boolean>; hasPendingEdit: () => boolean }
const props = defineProps<{ fixedCategory?: string }>()
const emit = defineEmits<{ saved: [] }>()
const auth = useAuthStore()
const canView = computed(() => auth.hasPermission('material_catalog.view_materialcatalog'))
const canMaintainLegacyMaterial = computed(() => canView.value && auth.hasPermission('products.add_rawmaterialinformation'))
const canAdd = computed(() => auth.hasPermission('material_catalog.add_materialcatalog') || canMaintainLegacyMaterial.value)
const canChange = computed(() => auth.hasPermission('material_catalog.change_materialcatalog') || canMaintainLegacyMaterial.value)
const definitions = ref<MaterialCatalogOptions>()
const category = ref('')
const search = ref('')
const names = ref<MaterialCatalogSummary[]>([])
const page = ref(1)
const totalPages = ref(0)
const selectedId = ref('')
const catalog = ref<MaterialCatalog>()
const baseline = ref('')
const etag = ref('')
const addingName = ref(false)
const saving = ref(false)
const collecting = ref(false)
const deleting = ref(false)
const confirming = ref(false)
const optionsLoading = ref(false)
const listLoading = ref(false)
const detailLoading = ref(false)
const optionsError = ref('')
const listError = ref('')
const detailError = ref('')
const saveError = ref('')
const versionWarning = ref('')
const publicOptions = ref<Partial<Record<MaterialScope, PublicMaterialOptions>>>({})
const publicOptionsLoading = ref(false)
const publicOptionsError = ref('')
const usesPublicColorTable = computed(() => catalog.value?.category_key === 'FABRIC' &&
  publicOptions.value.BASE?.fields.some(field => field.key === 'color' && field.source === 'product-colors'))
const colorOptions = computed(() => (catalog.value?.values || []).filter(value => value.scope === 'BASE' && value.field_key === 'color'))
const publicColorOptions = computed(() => (publicOptions.value.BASE?.values || []).filter(value => value.field_key === 'color'))
const editorGeneration = ref(0)
const editors = shallowRef(new Map<string, AttributeEditor>())
const primaryWarehouseField = computed(() => catalog.value?.category_key === 'FABRIC_SEMI' ? 'semi_warehouse_id' : 'base_warehouse_id')
const warehouseOptions = computed(() => (definitions.value?.warehouses ?? []).map(row => ({ value: row.id, label: row.warehouse_name })))
const categoryDefinition = computed(() => definitions.value?.categories.find(item => item.key === category.value))
const categoryOptions = computed(() => definitions.value?.categories.map(item => ({ value: item.key, label: item.label })) ?? [])
const templateOptions = computed(() => categoryDefinition.value?.templates.map(item => ({ value: item.key, label: item.label })) ?? [])
const template = computed(() => definitions.value?.categories.find(item => item.key === catalog.value?.category_key)
  ?.templates.find(item => item.key === catalog.value?.template_key))
const baseFields = computed(() => template.value?.fields.filter(field => field.kind !== 'dimension') ?? [])
const dimensionFields = computed(() => template.value?.fields.filter(field => field.kind === 'dimension') ?? [])
const shapes = computed(() => catalog.value?.values.filter(value => value.scope === 'BASE' &&
  template.value?.fields.some(field => field.key === value.field_key && field.kind === 'shape')) ?? [])
const navigationLocked = computed(() => saving.value || collecting.value || deleting.value || confirming.value)
const canEdit = computed(() => addingName.value ? canAdd.value : canChange.value)
const editingDisabled = computed(() => navigationLocked.value || detailLoading.value || publicOptionsLoading.value || !!versionWarning.value || (!addingName.value && !etag.value))
const hasPendingEditors = computed(() => [...editors.value.values()].some(editor => editor.hasPendingEdit()))
const hasUnsavedChanges = computed(() => !!catalog.value && (addingName.value || hasPendingEditors.value || serializeDraft(catalog.value) !== baseline.value))
let detailSequence = 0
let listSequence = 0
let optionsSequence = 0
let publicOptionsSequence = 0
let searchTimer: ReturnType<typeof setTimeout> | undefined
let appliedSearch = ''

function draftPayload(item: MaterialCatalog): MaterialCatalogDraft {
  return {
    name: item.name, spray_enabled: item.spray_enabled,
    base_warehouse_id: item.base_warehouse_id || null, semi_warehouse_id: item.semi_warehouse_id || null,
    values: item.values.map(value => ({ ...value })),
    units: item.units.map(({ id, scope, unit_name }) => ({ id, scope, unit_name })),
  }
}
function serializeDraft(item: MaterialCatalog) {
  const payload = draftPayload(item)
  payload.values.sort((left, right) => left.id.localeCompare(right.id))
  payload.units.sort((left, right) => left.id.localeCompare(right.id))
  return JSON.stringify(payload)
}
function setEditor(key: string, instance: Element | ComponentPublicInstance | null) {
  const editor = instance as unknown as AttributeEditor | null
  if (editors.value.get(key) === editor || (!editor && !editors.value.has(key))) return
  const next = new Map(editors.value)
  if (editor) next.set(key, editor)
  else next.delete(key)
  editors.value = next
}
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
  ++publicOptionsSequence
  ++editorGeneration.value
  selectedId.value = ''
  catalog.value = undefined
  addingName.value = false
  baseline.value = ''
  etag.value = ''
  versionWarning.value = ''
  detailError.value = ''
  saveError.value = ''
  detailLoading.value = false
  publicOptions.value = {}
  publicOptionsLoading.value = false
  publicOptionsError.value = ''
}
function applyDetail(result: VersionedMaterialCatalog) {
  catalog.value = { ...result.data, values: result.data.values.map(item => ({ ...item })), units: result.data.units.map(item => ({ ...item })) }
  selectedId.value = result.data.id
  addingName.value = false
  baseline.value = serializeDraft(catalog.value)
  etag.value = result.etag
  versionWarning.value = result.etag ? '' : '未取得档案版本，请重新读取后再保存。'
  saveError.value = ''
  ++editorGeneration.value
  names.value = names.value.map(item => item.id === result.data.id ? { ...item, ...result.data } : item)
}
async function readCatalog(id: string) {
  const sequence = ++detailSequence
  selectedId.value = id
  detailLoading.value = true
  detailError.value = ''
  try {
    const result = await fetchMaterialCatalog(id)
    if (sequence === detailSequence) { applyDetail(result); await loadPublicOptions() }
  } catch (issue) {
    if (sequence === detailSequence) { detailError.value = materialCatalogError(issue); etag.value = '' }
  } finally { if (sequence === detailSequence) detailLoading.value = false }
}
async function loadPublicOptions() {
  const item = catalog.value
  if (!item) return
  const sequence = ++publicOptionsSequence
  publicOptions.value = {}
  publicOptionsLoading.value = true
  publicOptionsError.value = ''
  const query = { category_key: item.category_key, template_key: item.template_key }
  try {
    const [base, spray] = await Promise.all([
      fetchPublicMaterialOptions({ ...query, scope: 'BASE' }),
      template.value?.supports_spray ? fetchPublicMaterialOptions({ ...query, scope: 'SPRAY' }) : Promise.resolve(undefined),
    ])
    if (sequence !== publicOptionsSequence) return
    if (base.category_key !== query.category_key || base.template_key !== query.template_key || base.scope !== 'BASE' ||
      (spray && (spray.category_key !== query.category_key || spray.template_key !== query.template_key || spray.scope !== 'SPRAY'))) {
      throw new Error('公共属性与当前品名模板不一致，请重新读取。')
    }
    publicOptions.value = { BASE: base, SPRAY: spray }
  } catch (issue) {
    if (sequence === publicOptionsSequence) publicOptionsError.value = materialCatalogError(issue)
  } finally { if (sequence === publicOptionsSequence) publicOptionsLoading.value = false }
}
function publicOptionItems(field: MaterialFieldDefinition, scope: MaterialScope, parentId?: string) {
  const candidates = publicOptions.value[scope]
  if (!candidates) return []
  if (field.kind === 'unit') return candidates.units.map(unit => unit.unit_name)
  const parent = catalog.value?.values.find(value => value.id === parentId)
  const publicParent = candidates.values.find(value => value.field_key === 'shape' && value.value === parent?.value)
  return [...new Set(candidates.values.filter(value => value.field_key === field.key &&
    (field.kind !== 'dimension' || (publicParent && value.parent_id === publicParent.id))).map(value => value.value))]
}
async function selectCatalog(id: string, reload = false) {
  if (navigationLocked.value || listLoading.value || (!reload && id === selectedId.value)) return
  cancelPendingSearch()
  if (!await canLeave()) return
  if (!reload) resetDetail()
  await readCatalog(id)
}
async function loadList(preserveSelection = false) {
  if (!category.value) return
  const sequence = ++listSequence
  listLoading.value = true
  listError.value = ''
  if (!preserveSelection) resetDetail()
  try {
    const query = search.value.trim()
    const result = await fetchMaterialCatalogs({ category: category.value, q: query, page: page.value, page_size: 50 })
    if (sequence !== listSequence) return
    appliedSearch = query
    names.value = result.data
    totalPages.value = result.meta.total_pages
    listLoading.value = false
    if (!preserveSelection && result.data[0]) await readCatalog(result.data[0].id)
  } catch (issue) {
    if (sequence === listSequence) { names.value = []; listError.value = materialCatalogError(issue) }
  } finally { if (sequence === listSequence) listLoading.value = false }
}
async function initialize() {
  if (!canView.value || navigationLocked.value || !await canLeave()) return
  const sequence = ++optionsSequence
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const result = await fetchMaterialCatalogOptions()
    if (sequence !== optionsSequence) return
    definitions.value = result
    category.value = props.fixedCategory || result.categories[0]?.key || ''
    await loadList()
  } catch (issue) { if (sequence === optionsSequence) optionsError.value = materialCatalogError(issue) }
  finally { if (sequence === optionsSequence) optionsLoading.value = false }
}
async function changeCategory(nextCategory: string) {
  cancelPendingSearch()
  if (nextCategory === category.value || !await canLeave()) return
  category.value = nextCategory
  search.value = ''
  page.value = 1
  await loadList()
}
async function applyCatalogFilters() {
  if (navigationLocked.value || optionsLoading.value) return
  clearTimeout(searchTimer)
  searchTimer = undefined
  if (!await canLeave()) { search.value = appliedSearch; return }
  page.value = 1
  await loadList()
}
async function resetCatalogFilters() {
  cancelPendingSearch()
  if (optionsLoading.value || !await canLeave()) return
  category.value = props.fixedCategory || definitions.value?.categories[0]?.key || ''
  search.value = ''
  page.value = 1
  await loadList()
}
function searchNames() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { searchTimer = undefined; void applyCatalogFilters() }, 250)
}
function cancelPendingSearch() {
  clearTimeout(searchTimer)
  searchTimer = undefined
  search.value = appliedSearch
}
async function changePage(nextPage: number) {
  if (listLoading.value) return
  cancelPendingSearch()
  if (!await canLeave()) return
  page.value = nextPage
  await loadList()
}
async function reloadList() {
  cancelPendingSearch()
  if (await canLeave()) await loadList()
}
function optionItems(field: MaterialFieldDefinition, scope: MaterialScope, parentId?: string) {
  if (field.kind === 'unit') return (catalog.value?.units ?? []).filter(unit => unit.scope === scope).map(unit => ({ id: unit.id, label: unit.unit_name }))
  return (catalog.value?.values ?? []).filter(value => value.scope === scope && value.field_key === field.key &&
    (value.parent_id ?? '') === (parentId ?? '')).map(value => ({ id: value.id, label: value.value }))
}
function requireDraft() {
  if (!catalog.value || !canEdit.value || saving.value || deleting.value || !!versionWarning.value) throw new Error('当前品名不可编辑，请重新读取或检查权限。')
  return catalog.value
}
async function saveOption(field: MaterialFieldDefinition, scope: MaterialScope, value: string, parentId?: string) {
  const item = requireDraft()
  if (!value.trim()) throw new Error('请输入选项内容。')
  if (optionItems(field, scope, parentId).some(option => option.label === value.trim())) throw new Error('该选项已存在，请修改输入内容。')
  if (field.kind === 'unit') item.units.push({ id: createClientUuid(), scope, unit_id: '', unit_name: value.trim() })
  else item.values.push({ id: createClientUuid(), scope, field_key: field.key, value: value.trim(), parent_id: parentId ?? null })
}
function colorMetadata(color: MaterialAttributeValue) {
  const name = (color.color_name ?? color.value).trim()
  if (!name) throw new Error('请输入颜色。')
  return { value: name, color_name: name, color_card: (color.color_card ?? '').trim(), color_code: (color.color_code ?? '').trim(), product_color_id: color.product_color_id ?? null }
}
async function saveColorOption(color: MaterialAttributeValue) {
  const item = requireDraft()
  item.values.push({ id: createClientUuid(), scope: 'BASE', field_key: 'color', parent_id: null, ...colorMetadata(color) })
}
async function updateColorOption(optionId: string, color: MaterialAttributeValue) {
  const item = requireDraft()
  const target = item.values.find(value => value.id === optionId && value.scope === 'BASE' && value.field_key === 'color')
  if (!target) throw new Error('该颜色已移除，请重新选择。')
  Object.assign(target, colorMetadata(color))
}
async function updateOption(field: MaterialFieldDefinition, optionId: string, value: string) {
  const item = requireDraft()
  if (!value.trim()) throw new Error('请输入选项内容。')
  if (field.kind === 'unit') {
    const target = item.units.find(unit => unit.id === optionId)
    if (!target) throw new Error('该单位已移除，请重新选择。')
    if (item.units.some(unit => unit.id !== optionId && unit.scope === target.scope && unit.unit_name === value.trim())) throw new Error('该单位已存在，请修改输入内容。')
    target.unit_name = value.trim()
  } else {
    const target = item.values.find(option => option.id === optionId)
    if (!target) throw new Error('该属性已移除，请重新选择。')
    if (item.values.some(option => option.id !== optionId && option.scope === target.scope && option.field_key === target.field_key && option.parent_id === target.parent_id && option.value === value.trim())) throw new Error('该选项已存在，请修改输入内容。')
    target.value = value.trim()
  }
}
async function removeOption(field: MaterialFieldDefinition, optionId: string) {
  const item = requireDraft()
  if (field.kind === 'unit') item.units = item.units.filter(unit => unit.id !== optionId)
  else {
    if (item.values.some(value => value.parent_id === optionId) && !await confirmAction('移除形状时，其下尺寸也会从草稿中移除。是否继续？', '移除形状', '移除')) return
    item.values = item.values.filter(value => value.id !== optionId && value.parent_id !== optionId)
  }
}
async function startName() {
  if (!canAdd.value || listLoading.value || optionsLoading.value || !categoryDefinition.value) return
  cancelPendingSearch()
  if (!await canLeave()) return
  resetDetail()
  addingName.value = true
  catalog.value = {
    id: createClientUuid(), category_key: category.value, template_key: categoryDefinition.value.templates[0]?.key || '',
    name: '', spray_enabled: false, base_warehouse_id: null, semi_warehouse_id: null, values: [], units: [], updated_at: '',
  }
  await loadPublicOptions()
}
async function changeTemplate(nextTemplate: string) {
  if (!catalog.value || !addingName.value || !canAdd.value || navigationLocked.value || catalog.value.template_key === nextTemplate) return
  if ((catalog.value.values.length || catalog.value.units.length || hasPendingEditors.value) &&
    !await confirmAction('切换模板会清除当前草稿的属性和单位，是否继续？', '切换模板', '切换')) return
  catalog.value.template_key = nextTemplate
  catalog.value.values = []
  catalog.value.units = []
  catalog.value.spray_enabled = false
  ++editorGeneration.value
  await loadPublicOptions()
}
async function saveDraft() {
  if (!catalog.value || !canEdit.value || editingDisabled.value) return
  cancelPendingSearch()
  saveError.value = ''
  collecting.value = true
  try {
    let valid = true
    // 每一行都收集，后续某行出错也不丢弃前面已进入草稿的输入。
    let hiddenSprayError = false
    for (const [key, editor] of editors.value) {
      if (!await editor.flushDraft()) {
        valid = false
        if (key.startsWith('SPRAY:') && !catalog.value.spray_enabled) hiddenSprayError = true
      }
    }
    if (!valid) {
      saveError.value = hiddenSprayError ? '喷塑属性仍有未完成输入，请开启喷塑检查或取消该输入。草稿已保留。' : '请检查属性输入，草稿已保留。'
      return
    }
    if (!catalog.value.name.trim()) { saveError.value = '请输入品名。'; return }
    if (!template.value) { saveError.value = '请选择有效的品名模板。'; return }
    const payload = draftPayload(catalog.value)
    payload.name = payload.name.trim()
    const sequence = detailSequence
    const creating = addingName.value
    saving.value = true
    const result = creating
      ? await createMaterialCatalog({ ...payload, category_key: catalog.value.category_key, template_key: catalog.value.template_key })
      : await saveMaterialCatalog(selectedId.value, payload, etag.value)
    if (sequence !== detailSequence) return
    applyDetail(result)
    emit('saved')
    await loadPublicOptions()
    if (creating) { search.value = ''; page.value = 1 }
    await loadList(true)
    if (!names.value.some(item => item.id === result.data.id)) names.value.unshift(result.data)
  } catch (issue) {
    saveError.value = materialCatalogError(issue)
    if ([412, 428].includes(materialCatalogErrorStatus(issue) ?? 0)) versionWarning.value = saveError.value
  } finally { saving.value = false; collecting.value = false }
}
async function archiveName(item: MaterialCatalogSummary) {
  if (!canChange.value || navigationLocked.value || listLoading.value) return
  cancelPendingSearch()
  const isSelected = selectedId.value === item.id
  if (isSelected && !await canLeave()) return
  if (!await confirmAction(`确定删除品名“${item.name}”吗？删除后不再可选，已有单据和历史记录会保留。`, '删除品名', '删除')) return
  deleting.value = true
  try {
    const version = isSelected ? etag.value : (await fetchMaterialCatalog(item.id)).etag
    if (!version) throw new Error('未取得档案版本，请重新读取后再删除。')
    await archiveMaterialCatalog(item.id, version)
    emit('saved')
    if (names.value.length === 1 && page.value > 1) page.value -= 1
    await loadList(!isSelected)
  } catch (issue) {
    if (isSelected) {
      saveError.value = materialCatalogError(issue)
      if ([412, 428].includes(materialCatalogErrorStatus(issue) ?? 0)) versionWarning.value = saveError.value
    } else listError.value = materialCatalogError(issue)
  } finally { deleting.value = false }
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (!hasUnsavedChanges.value && !navigationLocked.value) return
  event.preventDefault()
  event.returnValue = ''
}
onBeforeRouteLeave(canLeave)
onBeforeRouteUpdate(canLeave)
watch(() => props.fixedCategory, nextCategory => {
  if (nextCategory && definitions.value && nextCategory !== category.value) void changeCategory(nextCategory)
})
onMounted(() => { window.addEventListener('beforeunload', beforeUnload); void initialize() })
onBeforeUnmount(() => {
  ++detailSequence; ++listSequence; ++optionsSequence; ++publicOptionsSequence
  clearTimeout(searchTimer)
  window.removeEventListener('beforeunload', beforeUnload)
})
defineExpose({ canLeave })
</script>

<template>
  <section class="material-catalog-page erp-glass-list erp-glass-list--catalog" aria-label="原料管理">
    <p v-if="!canView" class="page-message" role="alert">无权查看原料管理</p>
    <div v-else-if="optionsError" class="page-message" role="alert">{{ optionsError }} <button class="erp-list-button erp-button-motion" type="button" @click="initialize">重新加载</button></div>
    <template v-else>
      <aside v-glass-spotlight class="catalog-sidebar erp-list-filter" aria-label="品名列表">
        <MaterialCatalogSelect :model-value="category" ariaLabel="原料类别" :options="categoryOptions"
          :placeholder="optionsLoading ? '加载分类中…' : '暂无分类'" :disabled="!!fixedCategory || optionsLoading || navigationLocked" @change="changeCategory" />
        <div class="catalog-search"><Search aria-hidden="true" /><input class="erp-list-control" v-model="search" type="search" aria-label="搜索品名" placeholder="搜索品名" :disabled="optionsLoading || navigationLocked" @input="searchNames" /></div>
        <div class="erp-list-filter-actions"><button class="erp-list-button erp-button-motion" type="button" :disabled="optionsLoading || navigationLocked" @click="resetCatalogFilters">重置</button><button type="button" class="erp-list-button erp-button-motion erp-list-button--primary" :disabled="optionsLoading || navigationLocked" @click="applyCatalogFilters">应用筛选</button></div>
        <button v-if="canAdd" type="button" class="erp-list-button erp-button-motion add-name" data-testid="create-name" :disabled="!category || optionsLoading || navigationLocked" @click="startName">新增品名</button>
        <div v-if="listError" class="error-message" role="alert">{{ listError }} <button class="erp-list-button erp-button-motion" type="button" :disabled="navigationLocked" @click="reloadList">重试</button></div>
        <nav class="material-names erp-list-catalog-nav" data-testid="material-names" aria-label="原料品名列表" tabindex="0" :aria-busy="listLoading">
          <div v-for="item in names" :key="item.id" class="material-name-row">
            <button type="button" class="material-name-button" :title="item.name" :data-catalog-id="item.id" :class="{ selected: selectedId === item.id }"
              :aria-current="selectedId === item.id ? 'true' : undefined" :disabled="navigationLocked || listLoading" @click="selectCatalog(item.id)">{{ item.name }}</button>
            <button v-if="canChange" type="button" class="delete-name" :aria-label="`删除品名${item.name}`" :title="`删除${item.name}`" :disabled="navigationLocked || listLoading" @click="archiveName(item)"><Delete aria-hidden="true" /></button>
          </div>
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
        <template v-if="catalog">
          <div class="catalog-save-row erp-flat-form">
            <input v-model="catalog.name" class="erp-list-control" :aria-label="addingName ? '新品名' : '品名'" placeholder="输入品名" :readonly="!canEdit" :disabled="editingDisabled" />
            <button v-if="canEdit" type="button" class="erp-list-button erp-list-button--primary" data-testid="save-catalog" :disabled="editingDisabled || listLoading" @click="saveDraft">{{ saving || collecting ? '保存中…' : '保存' }}</button>
          </div>
          <MaterialCatalogSelect v-if="addingName && templateOptions.length > 1" class="catalog-template" :model-value="catalog.template_key" ariaLabel="品名模板" :options="templateOptions" :disabled="!canEdit || editingDisabled" @change="changeTemplate" />
          <p v-if="saveError" class="error-message" role="alert">{{ saveError }}</p>
          <p v-if="publicOptionsError" class="error-message" role="alert">公共选项读取失败：{{ publicOptionsError }} <button type="button" class="erp-list-button" :disabled="navigationLocked || publicOptionsLoading" @click="loadPublicOptions">重试公共选项</button></p>
        </template>
        <template v-if="catalog && template">
          <section :key="`${catalog.id}:${editorGeneration}`" class="base-attributes" aria-label="品名属性">
            <div class="warehouse-row erp-flat-form"><label>{{ primaryWarehouseField === 'semi_warehouse_id' ? '半成品仓库' : '原料仓库' }}</label><MaterialCatalogSelect :model-value="catalog[primaryWarehouseField] || ''" @update:model-value="catalog[primaryWarehouseField] = $event || null" :ariaLabel="primaryWarehouseField === 'semi_warehouse_id' ? '半成品仓库' : '原料仓库'" :options="warehouseOptions" filterable clearable placeholder="选择现有仓库" :disabled="!canEdit || editingDisabled" /></div>
            <template v-for="field in baseFields" :key="field.key">
              <div v-if="field.kind === 'shape'" class="section-group">
                <div class="section-labels"><span>{{ field.label }}</span><span v-for="dimension in dimensionFields" :key="dimension.key">{{ dimension.label }}</span></div>
                <div class="section-body">
                  <div class="shape-dimensions">
                    <template v-for="dimension in dimensionFields" :key="dimension.key">
                      <MaterialAttributeOptions v-for="shape in shapes" :key="shape.id" :ref="instance => setEditor(`BASE:${dimension.key}:${shape.id}`, instance)" :data-shape-id="shape.id" :label="shape.value" :field-key="dimension.key" :kind="dimension.kind" scope="BASE" :parent-id="shape.id"
                        :options="optionItems(dimension, 'BASE', shape.id)" :public-options="publicOptionItems(dimension, 'BASE', shape.id)" :parent-options="publicOptionItems(field, 'BASE')" :available-units="[]" :readonly="!canEdit" :disabled="editingDisabled"
                        :on-save="value => saveOption(dimension, 'BASE', value, shape.id)" :on-update="(id, value) => updateOption(dimension, id, value)" :on-remove="id => removeOption(dimension, id)">
                        <template #label="{ remove, edit, busy, pending }"><span class="shape-label"><button v-if="canEdit" type="button" class="edit-shape" data-action="edit" :aria-label="`修改${shape.value}`" :disabled="editingDisabled || busy" @click="edit({ id: shape.id, label: shape.value }, field.label)">{{ shape.value }}</button><span v-else>{{ shape.value }}</span><button v-if="canEdit" type="button" class="erp-list-button erp-button-motion delete-shape" data-action="delete" :aria-label="`删除${shape.value}`" :title="`删除${shape.value}`" :disabled="editingDisabled || busy || pending" @click.stop="remove(shape.id)"><Delete aria-hidden="true" /></button></span></template>
                      </MaterialAttributeOptions>
                      <p v-if="!shapes.length" class="dimension-hint">先添加{{ field.label }}，再维护对应{{ dimension.label }}。</p>
                    </template>
                    <MaterialAttributeOptions v-show="canEdit" :ref="instance => setEditor(`BASE:${field.key}`, instance)" class="shape-heading" :label="field.label" :field-key="field.key" :kind="field.kind" scope="BASE"
                      :options="[]" :public-options="publicOptionItems(field, 'BASE')" :available-units="[]" :readonly="!canEdit" :disabled="editingDisabled"
                      :on-save="value => saveOption(field, 'BASE', value)" :on-update="(id, value) => updateOption(field, id, value)" :on-remove="id => removeOption(field, id)" />
                  </div>
                </div>
              </div>
              <MaterialColorOptions v-else-if="field.key === 'color' && usesPublicColorTable" :ref="instance => setEditor(`BASE:${field.key}`, instance)" :label="field.label"
                :options="colorOptions" :public-options="publicColorOptions" :readonly="!canEdit" :disabled="editingDisabled"
                :on-save="saveColorOption" :on-update="updateColorOption" :on-remove="id => removeOption(field, id)" />
              <MaterialAttributeOptions v-else :ref="instance => setEditor(`BASE:${field.key}`, instance)" :label="field.label" :field-key="field.key" :kind="field.kind" scope="BASE"
                :options="optionItems(field, 'BASE')" :public-options="publicOptionItems(field, 'BASE')" :available-units="[]" :readonly="!canEdit" :disabled="editingDisabled"
                :on-save="value => saveOption(field, 'BASE', value)" :on-update="(id, value) => updateOption(field, id, value)" :on-remove="id => removeOption(field, id)" />
            </template>
          </section>
          <section v-if="template.supports_spray" :key="`${catalog.id}:${editorGeneration}:spray`" class="spray-attributes" :aria-label="catalog.category_key === 'TUBE' ? '半成品属性' : '喷塑属性'">
            <div class="section-title"><h2>{{ catalog.category_key === 'TUBE' ? '半成品属性' : '喷塑属性' }}</h2><label class="spray-toggle"><input v-model="catalog.spray_enabled" type="checkbox" data-testid="spray-enabled" :disabled="!canEdit || editingDisabled" /> 喷塑</label></div>
            <div class="warehouse-row erp-flat-form"><label>半成品仓库</label><MaterialCatalogSelect :model-value="catalog.semi_warehouse_id || ''" @update:model-value="catalog.semi_warehouse_id = $event || null" ariaLabel="半成品仓库" :options="warehouseOptions" filterable clearable placeholder="选择现有仓库" :disabled="!canEdit || editingDisabled" /></div>
            <div v-show="catalog.spray_enabled">
              <MaterialAttributeOptions v-for="field in definitions?.spray_fields" :key="field.key" :ref="instance => setEditor(`SPRAY:${field.key}`, instance)" :label="field.label" :field-key="field.key" :kind="field.kind" scope="SPRAY"
                :options="optionItems(field, 'SPRAY')" :public-options="publicOptionItems(field, 'SPRAY')" :available-units="[]" :readonly="!canEdit" :disabled="editingDisabled"
                :on-save="value => saveOption(field, 'SPRAY', value)" :on-update="(id, value) => updateOption(field, id, value)" :on-remove="id => removeOption(field, id)" />
            </div>
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
.material-name-row { position: relative; flex-shrink: 0; }
.material-names .material-name-button { position: relative; display: block; width: 100%; padding-right: 36px; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.material-names .material-name-button.selected, .material-names .material-name-button.selected:hover { background: color-mix(in srgb, var(--erp-menu-selected-background) 88%, var(--erp-menu-accent)); color: var(--erp-menu-accent); }
.material-names .material-name-button.selected::before { content: ''; position: absolute; inset: 6px auto 6px 0; width: 3px; border-radius: 0 3px 3px 0; background: var(--erp-menu-accent); }
.material-names .delete-name { position: absolute; top: calc(50% - 12px); right: 6px; display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; min-height: 24px; padding: 0; opacity: 0; pointer-events: none; }
.delete-name svg { width: 14px; height: 14px; }
.material-name-row:hover .delete-name, .material-name-row:focus-within .delete-name { opacity: 1; pointer-events: auto; }
.catalog-save-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.catalog-save-row > input { width: 220px; min-width: 0; max-width: calc(100% - 72px); height: 28px; min-height: 28px; font-size: 12px; }
.catalog-save-row > button { height: 28px; min-height: 28px; padding: 0 12px; font-size: 12px; }
.catalog-template { width: 220px; margin-bottom: 8px; }
.warehouse-row { display: flex; align-items: center; gap: 12px; margin: 8px 0; font-size: 12px; }
.warehouse-row > label { flex: 0 0 120px; }
.warehouse-row :deep(.material-catalog-select) { width: 220px; max-width: 50%; }
.material-catalog-page .warehouse-row.erp-flat-form :deep(.el-select__wrapper) { height: 28px !important; min-height: 28px !important; }
.warehouse-row :deep(.el-select__selected-item), .warehouse-row :deep(.el-select__input) { font-size: 12px !important; }
.spray-attributes { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--erp-color-border); }
.section-title { display: flex; align-items: center; gap: 16px; margin-bottom: 12px; }
.spray-toggle { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.spray-toggle input { width: 15px; height: 15px; margin: 0; accent-color: var(--erp-color-brand); }
.section-group { display: flex; align-items: flex-start; gap: 12px; margin: 12px 0; }
.section-labels { display: flex; flex: 0 0 120px; flex-direction: column; gap: 8px; padding-top: 4px; }
.section-labels > span { display: flex; align-items: center; gap: 12px; min-height: 28px; }
.section-labels > span::after { content: ''; flex: 1; border-top: 2px solid var(--erp-color-border-strong); }
.section-body { flex: 1; min-width: 0; max-width: 820px; }
.shape-dimensions { flex: 1; min-width: 0; padding-left: 12px; border-left: 2px solid var(--erp-color-border-strong); }
.shape-dimensions :deep(.attribute-label) { width: 84px; }
.shape-dimensions :deep(.attribute-label::after), .shape-heading :deep(.attribute-label) { display: none; }
.shape-heading { max-width: 100%; }
.shape-label { display: flex; align-items: center; gap: 4px; overflow-wrap: anywhere; font-size: 12px; }
.edit-shape { min-height: 28px; padding: 0; border: 0; background: transparent; color: inherit; font: inherit; cursor: text; overflow-wrap: anywhere; }
.edit-shape:focus-visible { outline: 1px solid var(--erp-color-focus); outline-offset: 2px; }
.edit-shape:disabled { cursor: default; }
.delete-shape { display: inline-flex; align-items: center; justify-content: center; opacity: 0; pointer-events: none; flex: 0 0 20px; width: 20px; height: 20px; min-height: 20px; padding: 0; box-shadow: none; }
.delete-shape svg { width: 12px; height: 12px; }
.shape-label:hover .delete-shape, .shape-label:focus-within .delete-shape { opacity: 1; pointer-events: auto; }
.dimension-hint { margin: 4px 0; line-height: 32px; color: var(--erp-color-text-secondary); }
.version-warning { margin-bottom: 14px; padding: 8px 10px; border: 1px solid var(--erp-tag-warning-border); border-radius: var(--erp-radius-control); background: var(--erp-tag-warning-background); color: var(--erp-tag-warning-text); }
@media (hover: none) { .delete-shape, .material-names .delete-name { opacity: 1; pointer-events: auto; } }
</style>
