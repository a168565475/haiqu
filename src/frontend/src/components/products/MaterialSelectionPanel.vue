<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { ElSelect, ElOption, ElPopover, type PopoverProps } from 'element-plus'
import { ArrowDown, ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
import type { Modifier } from '@popperjs/core'
import { fetchMaterialCatalog, fetchMaterialCatalogOptions, fetchMaterialCatalogs, fetchPublicMaterialOptions, materialCatalogError } from '@/api/materialCatalog'
import { fetchBomCatalogSelectionOptions } from '@/api/boms'
import { fetchSampleMaterial, fetchSampleMaterialCrafts, fetchSampleMaterialOptions, fetchSampleMaterials, fetchSamplePublicOptions } from '@/api/sampleMaterialSources'
import type { BomLineInput } from '@/types/bom'
import type { MaterialAttributeValue, MaterialCatalog, MaterialCatalogOptions, MaterialCatalogSummary, MaterialSelectionInput, PublicMaterialOptions } from '@/types/materialCatalog'
import { applyMaterialSelection, bomCatalogCategories } from './materialSelection'

const props = withDefaults(defineProps<{
  line: BomLineInput
  sectionTitle: string
  refreshKey?: number
  fixedUnit?: '根' | '米'
  presentation?: 'panel' | 'dropdown'
  source?: 'catalog' | 'sample'
}>(), { presentation: 'panel', source: 'catalog' })
const emit = defineEmits<{ maintain: []; loaded: [catalog: MaterialCatalog]; 'public-options': [options: PublicMaterialOptions | undefined] }>()
const names = ref<MaterialCatalogSummary[]>([])
const keyword = ref('')
const page = ref(1)
const pages = ref(1)
const catalog = ref<MaterialCatalog>()
const publicOptions = ref<PublicMaterialOptions>()
const publicSprayOptions = ref<PublicMaterialOptions>()
// 仅在当前选择器会话内复用；维护关闭或显式重读时失效。
const publicOptionsCache = new Map<string, PublicMaterialOptions>()
const definitions = ref<MaterialCatalogOptions>()
const loading = ref(false)
const error = ref('')
const drafts = ref<Record<string, string>>({})
const crafts = ref<Array<{ id: string; craft_type: string; code: string; name: string }>>([])
const craftId = ref('')
const dropdownOpen = ref(false)
const selectionId = useId()
const isDropdown = computed(() => props.presentation === 'dropdown')
const colorAsList = computed(() => isDropdown.value || props.source === 'sample')
const selectedName = computed(() => {
  const id = props.line.material_catalog_id
  if (!id) return ''
  if (catalog.value?.id === id) return catalog.value.name
  if (props.line.material_selection_snapshot?.catalog_id === id) return props.line.material_selection_snapshot.name
  return names.value.find(item => item.id === id)?.name || props.line.part_name || ''
})
const availableHeight: Modifier<'materialSelectionHeight', Record<string, never>> = {
  name: 'materialSelectionHeight', enabled: true, phase: 'beforeWrite', requires: ['computeStyles'],
  fn({ state }) {
    const rect = state.elements.reference.getBoundingClientRect()
    const height = state.placement.startsWith('top') ? rect.top : document.documentElement.clientHeight - rect.bottom
    Object.assign(state.styles.popper, { '--material-selection-height': `${Math.max(80, Math.min(560, height - 16))}px` })
  },
}
const dropdownProps: Partial<PopoverProps> = {
  trigger: 'click', placement: 'bottom-start', width: 'min(920px, calc(100vw - 24px))',
  teleported: true, persistent: true, showArrow: false, offset: 6, hideAfter: 0,
  fallbackPlacements: ['top-start', 'bottom-start'], popperClass: 'material-selection-popover',
  popperOptions: { modifiers: [availableHeight, { name: 'preventOverflow', options: { padding: 12 } }, { name: 'flip', options: { padding: 12 } }] },
}
let requestId = 0
let namesRequestId = 0
let disposed = false
const templateDefinition = computed(() => definitions.value?.categories.flatMap(item => item.templates).find(item => item.key === catalog.value?.template_key))
const fields = computed(() => {
  const selectedFields = (templateDefinition.value?.fields || []).filter(field =>
    (!props.fixedUnit || field.key !== 'unit') && !((isDropdown.value || props.source === 'sample') && catalog.value?.category_key === 'TUBE' && field.key === 'length') &&
    !(isDropdown.value && catalog.value?.category_key === 'PACKAGING' && ['layers', 'printing'].includes(field.key)),
  ).filter(field => props.source !== 'sample' || options(field.key).length || drafts.value[field.key] ||
    (field.key === 'section_size' && !drafts.value.shape))
  if (props.source === 'sample' && catalog.value?.category_key === 'TUBE') {
    const keys = ['shape', 'section_size', 'thickness', 'material', 'color', 'unit']
    return selectedFields.filter(field => keys.includes(field.key)).sort((left, right) => keys.indexOf(left.key) - keys.indexOf(right.key))
      .map(field => ({ ...field, label: field.key === 'shape' ? '管材类型' : field.label }))
  }
  if (!isDropdown.value) return selectedFields
  const categoryFields: Record<string, string[]> = {
    HARDWARE: ['material', 'color', 'specification', 'flow_unit', 'unit'],
    PLASTIC: ['material', 'color', 'specification', 'unit'],
    FABRIC: ['material', 'color', 'fabric_spec', 'width', 'unit'],
  }
  const keys = categoryFields[catalog.value?.category_key || '']
  return (keys ? selectedFields.filter(field => keys.includes(field.key)).sort((left, right) => keys.indexOf(left.key) - keys.indexOf(right.key)) : selectedFields)
    .map(field => ({ ...field, label: field.key === 'unit' ? (catalog.value?.category_key === 'FABRIC' ? '单位' : '本次数量单位')
      : field.key === 'specification' && catalog.value?.category_key === 'HARDWARE' ? '型号规格'
      : field.key === 'specification' && catalog.value?.category_key === 'PLASTIC' ? '规格' : field.label }))
})
const category = computed(() => bomCatalogCategories[props.sectionTitle])
const showSprayColors = computed(() => isDropdown.value && !!catalog.value?.spray_enabled && !!templateDefinition.value?.supports_spray && ['TUBE', 'HARDWARE'].includes(catalog.value?.category_key || ''))
const sprayColors = computed(() => (publicSprayOptions.value?.values || []).filter(value => value.field_key === 'color' && value.value.trim() && !['/', '-', '—'].includes(value.value.trim())).map(value => value.value))
const selectedSprayColor = computed(() => catalog.value?.category_key === 'TUBE' ? props.line.tube_coating_color : props.line.powder_coating_color)
const usesProductColors = computed(() => catalog.value?.category_key === 'FABRIC' && (publicOptions.value?.fields.some(field => field.key === 'color' && field.source === 'product-colors') ?? false))
const colorRows = computed(() => (publicOptions.value?.values || []).filter(item => item.field_key === 'color' && item.value.trim() && !['/', '-', '—'].includes(item.value.trim())))
const selectedColorRow = computed(() => {
  const saved = props.line.material_selection ?? props.line.material_selection_snapshot
  if (saved?.product_color_id) return colorRows.value.find(item => (item.product_color_id || item.id) === saved.product_color_id)
  const matches = colorRows.value.filter(item => item.value === drafts.value.color &&
    (!saved?.color_card || item.color_card === saved.color_card) && (!saved?.color_code || item.color_code === saved.color_code))
  return matches.length === 1 ? matches[0] : undefined
})
const attributeGroupCount = computed(() => fields.value.length + (showSprayColors.value ? 1 : 0))
const attributeRows = computed(() => Math.max(1, Math.ceil(attributeGroupCount.value / (attributeGroupCount.value > 6 ? 4 : 3))))
const fieldOptions = computed(() => {
  const grouped = new Map<string, string[]>()
  const shape = publicOptions.value?.values.find(value => value.field_key === 'shape' && value.value === drafts.value.shape)
  for (const item of publicOptions.value?.values || []) {
    if (!item.value.trim() || ['/', '-', '—'].includes(item.value.trim())) continue
    if (item.field_key === 'section_size' && (!shape || item.parent_id !== shape.id)) continue
    const values = grouped.get(item.field_key) || []
    if (item.field_key === 'color' && !usesProductColors.value && values.includes(item.value)) continue
    values.push(item.value)
    grouped.set(item.field_key, values)
  }
  grouped.set('unit', (publicOptions.value?.units || []).map(unit => unit.unit_name).filter(value => value.trim() && !['/', '-', '—'].includes(value.trim())))
  return grouped
})

async function loadNames(reset = false) {
  if (disposed) return
  const token = ++namesRequestId
  if (reset) page.value = 1
  try {
    const result = await (props.source === 'sample' ? fetchSampleMaterials : fetchMaterialCatalogs)({ category: category.value, q: keyword.value, page: page.value, page_size: 50 })
    if (token !== namesRequestId) return
    names.value = result.data
    pages.value = result.meta.total_pages
  } catch (issue) { if (token === namesRequestId) error.value = materialCatalogError(issue) }
}
async function pickName(id: string, preserve = false) {
  if (disposed) return
  const token = ++requestId
  loading.value = true
  error.value = ''
  catalog.value = undefined
  publicOptions.value = undefined
  publicSprayOptions.value = undefined
  emit('public-options', undefined)
  try {
    const result = await (props.source === 'sample' ? fetchSampleMaterial : fetchMaterialCatalog)(id)
    if (token !== requestId) return
    if (result.data.id !== id) throw new Error('读取的品名与当前选择不一致，请重新读取。')
    const query = { category_key: result.data.category_key, template_key: result.data.template_key }
    const cacheKey = JSON.stringify([query.category_key, query.template_key])
    const supportsSpray = definitions.value?.categories.flatMap(item => item.templates).find(item => item.key === result.data.template_key)?.supports_spray
    const [baseOptions, sprayOptions] = await Promise.all([
      publicOptionsCache.get(`${cacheKey}:BASE`) || (props.source === 'sample' ? fetchSamplePublicOptions : fetchPublicMaterialOptions)({ ...query, scope: 'BASE' }),
      supportsSpray ? publicOptionsCache.get(`${cacheKey}:SPRAY`) || (props.source === 'sample' ? fetchSamplePublicOptions : fetchPublicMaterialOptions)({ ...query, scope: 'SPRAY' }) : undefined,
    ])
    if (token !== requestId) return
    if (baseOptions.category_key !== query.category_key || baseOptions.template_key !== query.template_key || baseOptions.scope !== 'BASE' ||
      (sprayOptions && (sprayOptions.category_key !== query.category_key || sprayOptions.template_key !== query.template_key || sprayOptions.scope !== 'SPRAY'))) {
      throw new Error('公共属性与当前品名模板不一致，请重新读取。')
    }
    // 完整成功且仍为当前请求才写缓存，失败或迟到响应均不能污染后续选择。
    publicOptionsCache.set(`${cacheKey}:BASE`, baseOptions)
    if (sprayOptions) publicOptionsCache.set(`${cacheKey}:SPRAY`, sprayOptions)
    publicOptions.value = baseOptions
    publicSprayOptions.value = sprayOptions
    catalog.value = result.data
    emit('loaded', result.data)
    emit('public-options', sprayOptions)
    if (!preserve) {
      const keepTubeAttributes = isDropdown.value && category.value === 'TUBE' && result.data.category_key === 'TUBE'
      const previousSelection = props.line.material_selection ?? props.line.material_selection_snapshot
      const previousAttributes: Record<string, string> = previousSelection?.attributes || {
        material: props.line.material, shape: props.line.tube_shape,
        section_size: props.line.tube_diameter, thickness: props.line.tube_thickness,
      }
      const previousSprayColor = props.line.tube_coating_color
      drafts.value = {}
      if (keepTubeAttributes) {
        for (const key of ['material', 'color', 'shape', 'thickness']) {
          const value = previousAttributes[key]
          if (value && options(key).includes(value)) drafts.value[key] = value
        }
        // 规格候选随已保留的形状变化，不能沿用另一形状下的同名规格。
        const size = previousAttributes.section_size
        if (size && options('section_size').includes(size)) drafts.value.section_size = size
        props.line.material_selection_snapshot = undefined
      }
      craftId.value = ''
      props.line.tube_coating_color = keepTubeAttributes && supportsSpray && result.data.spray_enabled && sprayColors.value.includes(previousSprayColor) ? previousSprayColor : ''
      props.line.powder_coating_color = ''
      props.line.material_selection = {
        catalog_version: result.data.updated_at, scope: 'BASE', processing_state: category.value === 'FABRIC_SEMI' ? 'PROCESSED' : 'RAW',
        attributes: {}, ...(category.value === 'FABRIC_SEMI' ? { semi_kind: 'CUTTING' as const } : {}),
      }
      props.line.unit = ''
      syncLine()
    } else {
      const saved = props.line.material_selection ?? props.line.material_selection_snapshot
      drafts.value = { ...(saved?.attributes || {}), unit: saved?.unit_name || props.line.unit }
      if (saved && !props.line.material_selection) props.line.material_selection = {
        catalog_version: saved.catalog_version, scope: saved.scope, processing_state: saved.processing_state,
        attributes: { ...saved.attributes }, unit_id: saved.unit_id, completed_craft: saved.completed_craft, semi_kind: saved.semi_kind,
        product_color_id: saved.product_color_id, color_card: saved.color_card, color_code: saved.color_code, color_name: saved.color_name,
      }
      craftId.value = saved?.completed_craft?.id || ''
    }
  } catch (issue) { if (token === requestId) error.value = materialCatalogError(issue) }
  finally { if (token === requestId) loading.value = false }
}
function options(key: string) {
  return fieldOptions.value.get(key) || []
}
function syncLine() {
  if (!catalog.value || !props.line.material_selection) return
  const attributes = Object.fromEntries(Object.entries(drafts.value).filter(([key, value]) => key !== 'unit' && value))
  const quantityUnit = props.fixedUnit || drafts.value.unit
  const selected = publicOptions.value?.units.find(unit => unit.unit_name === quantityUnit)
  const craft = crafts.value.find(item => item.id === craftId.value)
  const selection: MaterialSelectionInput = {
    ...props.line.material_selection, catalog_version: catalog.value.updated_at, attributes,
    unit_id: selected?.id, unit_name: selected ? undefined : quantityUnit || undefined,
    ...(category.value === 'FABRIC_SEMI' ? { completed_craft: craft ? { id: craft.id, craft_type: craft.craft_type as 'INTERNAL' | 'EXTERNAL', code: craft.code } : null } : {}),
  }
  applyMaterialSelection(props.line, catalog.value, selection)
  // 公共单位可以尚未出现在该品名使用记录中，显示名称来自本次已选候选。
  props.line.unit = quantityUnit || ''
}
function choose(key: string, value: string) {
  if (loading.value || error.value || !catalog.value) return
  if (props.fixedUnit && key === 'unit') return
  if (!options(key).includes(value)) return
  if (key === 'shape' && drafts.value.shape !== value) drafts.value.section_size = ''
  if (key === 'unit' && drafts.value.unit !== value) {
    props.line.material_quantity = null
    if (props.sectionTitle === '面料类') props.line.unit_consumption = ''
  }
  drafts.value[key] = value
  if (key === 'color' && !usesProductColors.value && props.line.material_selection) {
    for (const field of ['product_color_id', 'color_card', 'color_code', 'color_name'] as const) delete props.line.material_selection[field]
  }
  syncLine()
}
function colorSelection(row: MaterialAttributeValue) {
  return { product_color_id: row.product_color_id || row.id, color_card: row.color_card || '', color_code: row.color_code || '', color_name: row.color_name || row.value }
}
function chooseColor(row: MaterialAttributeValue) {
  if (loading.value || error.value || !catalog.value || !props.line.material_selection || !colorRows.value.includes(row)) return
  drafts.value.color = row.value
  Object.assign(props.line.material_selection, colorSelection(row))
  syncLine()
}
function chooseSprayColor(value: string) {
  if (loading.value || error.value || !catalog.value?.spray_enabled || !showSprayColors.value || !sprayColors.value.includes(value)) return
  if (catalog.value.category_key === 'TUBE') props.line.tube_coating_color = value
  else props.line.powder_coating_color = value
}
function openMaintenance() {
  dropdownOpen.value = false
  emit('maintain')
}
function closeOnEscape(event: KeyboardEvent) {
  if (!isDropdown.value) return
  event.stopPropagation()
  dropdownOpen.value = false
}
async function reloadCurrent() {
  const id = props.line.material_catalog_id
  const token = ++requestId
  publicOptionsCache.clear()
  catalog.value = undefined
  publicOptions.value = undefined
  publicSprayOptions.value = undefined
  emit('public-options', undefined)
  loading.value = true
  try {
    await loadNames()
    if (!id || token !== requestId || props.line.material_catalog_id !== id) return
    await pickName(id, true)
  } finally {
    if (token === requestId) loading.value = false
  }
}
watch(() => props.refreshKey, reloadCurrent)
onBeforeUnmount(() => { disposed = true; ++requestId; ++namesRequestId })
onMounted(async () => {
  loading.value = true
  try {
    definitions.value = await (props.source === 'sample' ? fetchSampleMaterialOptions : fetchMaterialCatalogOptions)()
    if (disposed) return
    if (category.value === 'FABRIC_SEMI') crafts.value = (await (props.source === 'sample' ? fetchSampleMaterialCrafts : fetchBomCatalogSelectionOptions)()).crafts
    if (disposed) return
    await loadNames()
    if (props.line.material_catalog_id) await pickName(props.line.material_catalog_id, true)
  } catch (issue) { error.value = materialCatalogError(issue) }
  finally { loading.value = false }
})
</script>

<template>
  <div class="material-selection-field" :class="{ 'material-selection-field--dropdown': isDropdown }">
    <span v-if="isDropdown" class="material-selection-label">品名</span>
    <component :is="isDropdown ? ElPopover : 'div'" v-bind="isDropdown ? dropdownProps : {}" :visible="isDropdown ? dropdownOpen : undefined" @update:visible="dropdownOpen = $event">
      <template v-if="isDropdown" #reference>
        <button type="button" class="material-name-trigger" aria-label="品名" aria-haspopup="dialog" :aria-expanded="dropdownOpen" :class="{ 'is-empty': !selectedName, 'is-open': dropdownOpen }">
          <span>{{ selectedName || '选择品名' }}</span><ArrowDown aria-hidden="true" :class="{ 'is-reverse': dropdownOpen }" />
        </button>
      </template>
  <section class="material-selection" :class="{ 'material-selection--dropdown': isDropdown }" aria-label="品名及公共属性选择" :aria-busy="loading" @keydown.esc="closeOnEscape">
    <div v-if="error" class="selection-error" role="alert">{{ error }} <button type="button" @click="reloadCurrent">重新读取</button></div>
    <aside class="catalog-names">
      <header><strong>品名</strong><form @submit.prevent="loadNames(true)"><input v-model="keyword" class="group-input" aria-label="筛选品名" placeholder="中文/拼音/首字母，回车筛选" /></form></header>
      <div class="catalog-name-list">
        <p v-if="!names.length && !loading">暂无品名，请到分区维护配置中补充。</p>
        <button v-for="item in names" :key="item.id" type="button" class="name-option" :class="{ selected: line.material_catalog_id === item.id }" :disabled="loading" @click="pickName(item.id)">{{ item.name }}</button>
      </div>
      <nav v-if="pages > 1" class="catalog-pages" aria-label="品名分页"><button type="button" aria-label="上一页" :disabled="page <= 1" @click="page--; loadNames()"><ArrowLeft aria-hidden="true" /></button><span>{{ page }}/{{ pages }}</span><button type="button" aria-label="下一页" :disabled="page >= pages" @click="page++; loadNames()"><ArrowRight aria-hidden="true" /></button></nav>
      <button v-if="!isDropdown && source === 'catalog'" type="button" class="maintain-link" @click="openMaintenance">生产维护</button>
    </aside>
    <div v-if="catalog" class="attribute-groups" :class="{ 'attribute-groups--four-columns': attributeGroupCount > 6, 'attribute-groups--seven': attributeGroupCount === 7, 'attribute-groups--fabric-colors': usesProductColors && source !== 'sample' }" :style="{ '--material-attribute-rows': attributeRows }">
      <fieldset v-for="field in fields" :key="field.key" class="attribute-group" :class="{ 'attribute-group--color': field.key === 'color' && usesProductColors }" :disabled="loading || (field.key === 'section_size' && !drafts.shape)">
        <legend>{{ field.label === '可用单位' ? '本次数量单位' : field.label }}</legend>
        <div v-if="field.key === 'color' && usesProductColors" :class="colorAsList ? 'group-values' : 'color-table-scroll'">
          <template v-if="colorAsList">
            <label v-for="row in colorRows" :key="row.product_color_id || row.id" class="attribute-value" :class="{ selected: selectedColorRow?.id === row.id }">
              <input type="radio" :name="`${selectionId}-color`" :checked="selectedColorRow?.id === row.id" @change="chooseColor(row)" />
              <span>{{ [row.color_card, row.color_code, row.color_name || row.value].filter(value => value && !['/', '-', '—'].includes(value.trim())).join('-') }}</span>
            </label>
            <p v-if="!colorRows.length">暂无已有选项，请到分区维护配置中补充。</p>
          </template>
          <table v-else class="color-options-table" aria-label="普通颜色选择">
            <thead><tr><th scope="col" class="color-choice-column"><span class="color-choice-label">选择</span></th><th scope="col">色卡</th><th scope="col">色号</th><th scope="col">颜色</th></tr></thead>
            <tbody>
              <tr v-for="row in colorRows" :key="row.product_color_id || row.id" :class="{ selected: selectedColorRow?.id === row.id }" @click="chooseColor(row)">
                <td><input type="radio" :name="`${selectionId}-color`" :aria-label="[row.color_card, row.color_code, row.color_name || row.value].filter(Boolean).join(' / ')" :checked="selectedColorRow?.id === row.id" @change="chooseColor(row)" @click.stop /></td>
                <td>{{ row.color_card || '—' }}</td><td>{{ row.color_code || '—' }}</td><td>{{ row.color_name || row.value }}</td>
              </tr>
              <tr v-if="!colorRows.length"><td colspan="4" class="color-table-empty">暂无已有选项，请到分区维护配置中补充。</td></tr>
            </tbody>
          </table>
          <p v-if="drafts.color && !selectedColorRow" class="historical-value">{{ [line.material_selection?.color_card, line.material_selection?.color_code, drafts.color].filter(Boolean).join(' / ') }}（历史值，待重选）</p>
        </div>
        <div v-else class="group-values">
          <label v-for="value in options(field.key)" :key="value" class="attribute-value" :class="{ selected: drafts[field.key] === value }"><input type="radio" :name="`${selectionId}-${field.key}`" :checked="drafts[field.key] === value" @change="choose(field.key, value)" /><span>{{ value }}</span></label>
          <span v-if="drafts[field.key] && !options(field.key).includes(drafts[field.key]!)" class="historical-value">{{ drafts[field.key] }}（历史值，待重选）</span>
          <p v-if="field.key === 'section_size' && !drafts.shape">请先选择截面形状</p>
          <p v-else-if="!options(field.key).length">暂无已有选项，请到分区维护配置中补充。</p>
        </div>
      </fieldset>
      <fieldset v-if="showSprayColors" class="attribute-group spray-color-group" :disabled="loading || !catalog.spray_enabled">
        <legend>喷塑颜色</legend>
        <div class="group-values">
          <label v-for="value in sprayColors" :key="value" class="attribute-value" :class="{ selected: selectedSprayColor === value }"><input type="radio" :name="`${selectionId}-spray-color`" :checked="selectedSprayColor === value" @change="chooseSprayColor(value)" /><span>{{ value }}</span></label>
          <span v-if="selectedSprayColor && !sprayColors.includes(selectedSprayColor)" class="historical-value">{{ selectedSprayColor }}（历史值，待重选）</span>
          <p v-if="!catalog.spray_enabled">该品名未启用半成品</p>
          <p v-else-if="!sprayColors.length">暂无喷塑颜色，请到分区维护配置中补充。</p>
        </div>
      </fieldset>
      <label v-if="category === 'FABRIC_SEMI'" class="craft-field"><span>已完成工艺</span><ElSelect v-model="craftId" :teleported="!isDropdown" aria-label="裁片已完成工艺" placeholder="选择既有工艺" @change="syncLine"><ElOption v-for="craft in crafts" :key="craft.id" :value="craft.id" :label="craft.name" /></ElSelect></label>
    </div>
    <div v-else class="selection-empty">{{ loading ? '正在读取原料…' : '先选择已有品名，再逐项选择右侧属性。' }}</div>
    <footer v-if="isDropdown" class="selection-footer"><button type="button" class="erp-list-button erp-list-button--primary" :disabled="loading" @click="dropdownOpen = false">完成选择</button></footer>
  </section>
    </component>
  </div>
</template>

<style scoped>
.material-selection-field { min-width: 0; }
.material-selection-label { display: block; margin-bottom: 7px; color: var(--erp-color-text-secondary); font-size: 13px; }
.material-name-trigger { display: flex; align-items: center; justify-content: space-between; gap: 6px; box-sizing: border-box; width: 100%; height: 32px; min-height: 32px; padding: 0 10px; border: 0; border-radius: 5px; background: var(--erp-color-surface); box-shadow: 0 0 0 1px var(--erp-dialog-input-border, var(--erp-color-border)) inset; color: var(--erp-input-text); font-family: inherit; font-size: 13px; font-weight: 400; line-height: 18px; text-align: left; cursor: pointer; transition: box-shadow .2s; }
.material-name-trigger:hover { box-shadow: 0 0 0 1px var(--erp-dialog-input-hover-border, var(--erp-color-border-strong)) inset; }
.material-name-trigger:focus-visible, .material-name-trigger.is-open { outline: none; box-shadow: 0 0 0 1px var(--erp-dialog-input-focus-border, var(--erp-color-focus)) inset; }
.material-name-trigger > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.material-name-trigger > svg { flex-shrink: 0; width: 14px; height: 14px; color: var(--el-text-color-placeholder); transition: transform .3s; }
.material-name-trigger > svg.is-reverse { transform: rotate(180deg); }
.material-name-trigger.is-empty { color: var(--erp-input-placeholder); }
.material-selection { display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 12px; width: 100%; min-width: 0; border: 1px solid var(--erp-color-border); border-radius: 5px; color: var(--erp-color-text-primary); }
.catalog-names { padding: 12px; border-right: 1px solid var(--erp-color-border); min-width: 0; }
.catalog-names strong { display: block; margin-bottom: 8px; }
.group-input { box-sizing: border-box; width: 100%; height: 28px; padding: 0 8px; border: 1px solid var(--erp-color-border); border-radius: 5px; font: inherit; font-size: 12px; color: var(--erp-color-text-primary); background: var(--erp-input-background); }
.name-option { display: block; width: 100%; margin-top: 5px; padding: 6px 8px; text-align: left; overflow-wrap: anywhere; border: 1px solid transparent; border-radius: 5px; background: transparent; color: inherit; cursor: pointer; }
.selected { background: var(--erp-color-selected); border-color: var(--erp-color-brand); }
.attribute-groups { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; align-content: start; padding: 12px 12px 12px 0; min-width: 0; }
.craft-field { grid-column: 1 / -1; margin: 0; font-size: 12px; }
.attribute-group { min-width: 0; margin: 0; padding: 8px; border: 1px solid var(--erp-color-border); border-radius: 5px; }
.attribute-group legend { padding: 0 4px; font-size: 12px; }
.group-values { overflow: auto; display: flex; flex-direction: column; gap: 5px; margin-top: 6px; font-size: 12px; }
.attribute-value { display: flex; gap: 5px; align-items: center; min-height: 26px; border: 1px solid transparent; border-radius: 4px; padding: 0 3px; overflow-wrap: anywhere; cursor: pointer; }
.attribute-value.selected { border-color: var(--erp-color-brand); }
.historical-value { padding: 4px 3px; color: var(--erp-color-text-secondary); line-height: 18px; overflow-wrap: anywhere; }
.group-values p { margin: 2px; }
.color-table-scroll { min-height: 0; max-height: 240px; overflow: auto; margin-top: 6px; }
.color-options-table { width: 100%; border-collapse: separate; border-spacing: 0; table-layout: fixed; font-size: 12px; background: var(--erp-table-background); }
.color-options-table th, .color-options-table td { padding: 6px 4px; text-align: left; overflow-wrap: anywhere; border-bottom: 1px solid var(--erp-table-border); }
.color-options-table th { position: sticky; top: 0; z-index: 1; background: var(--erp-table-header-background); color: var(--erp-table-header-text); font-weight: 500; }
.color-options-table .color-choice-column { width: 24px; }
.color-choice-label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.color-options-table input { margin: 0; vertical-align: middle; }
.color-options-table tbody tr { cursor: pointer; }
.color-options-table tbody tr:hover { background: var(--erp-table-hover); }
.color-options-table tbody tr.selected { background: var(--erp-table-selected); }
.color-options-table .color-table-empty { cursor: default; }
.attribute-groups--fabric-colors > .attribute-group--color { grid-column: span 2; }
.maintain-link { color: var(--erp-color-brand); background: transparent; border: 0; text-align: left; padding: 5px 0; font-size: 12px; cursor: pointer; overflow-wrap: anywhere; }
.catalog-pages { display: flex; flex-shrink: 0; align-items: center; justify-content: center; gap: 8px; font-size: 12px; margin-top: 8px; white-space: nowrap; }
.catalog-pages button { display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; width: 28px; height: 28px; padding: 0; border: 1px solid var(--erp-pagination-border); border-radius: 5px; background: var(--erp-pagination-background); color: var(--erp-pagination-text); cursor: pointer; }
.catalog-pages button:disabled { opacity: .45; cursor: not-allowed; }
.catalog-pages svg { width: 12px; height: 12px; }
.selection-error { grid-column: 1 / -1; color: var(--erp-color-danger); padding: 8px; }
.selection-empty { padding: 24px 12px; font-size: 13px; }
.craft-field { display: flex; align-items: center; gap: 10px; }
.craft-field > span { flex-shrink: 0; white-space: nowrap; }
.craft-field :deep(.el-select) { flex: 1; min-width: 0; }
.material-selection--dropdown { grid-template-columns: 164px minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr) auto; gap: 0; height: min(var(--material-selection-height, 560px), calc(100vh - 24px)); border: 0; border-radius: 0; font-size: 12px; }
.material-selection--dropdown > .selection-error { grid-column: 1 / -1; grid-row: 1; }
.material-selection--dropdown > .catalog-names { display: flex; flex-direction: column; grid-column: 1; grid-row: 2; min-height: 0; overflow: hidden; padding: 10px; }
.material-selection--dropdown .catalog-names > header { flex-shrink: 0; }
.material-selection--dropdown .catalog-name-list { flex: 1; min-height: 0; overflow-y: auto; }
.material-selection--dropdown > .attribute-groups { grid-column: 2; grid-row: 2; grid-template-rows: repeat(var(--material-attribute-rows, 2), minmax(0, 1fr)); min-height: 0; overflow: hidden; padding: 10px; gap: 8px; }
.material-selection--dropdown > .attribute-groups--four-columns { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.material-selection--dropdown > .attribute-groups--seven > .attribute-group:last-of-type { grid-column: span 2; }
.material-selection--dropdown .attribute-group { display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.material-selection--dropdown .group-values { flex: 1; min-height: 0; }
.material-selection--dropdown .color-table-scroll { flex: 1; max-height: none; }
.material-selection--dropdown .attribute-groups:has(.craft-field) { grid-template-rows: repeat(var(--material-attribute-rows, 2), minmax(0, 1fr)) auto; }
.material-selection--dropdown > .selection-empty { grid-column: 2; grid-row: 2; }
.selection-footer { display: flex; grid-column: 1 / -1; grid-row: 3; align-items: center; justify-content: flex-end; padding: 8px 10px; border-top: 1px solid var(--erp-color-border); }
.selection-footer > button { min-height: 28px; height: 28px; padding: 0 12px; font-size: 12px; }
button:not(.material-name-trigger):focus-visible, input:focus-visible { outline: 2px solid var(--erp-color-brand); outline-offset: 2px; }
@media(max-width: 760px) {
  .material-selection { grid-template-columns: 150px minmax(0, 1fr); }
  .attribute-groups { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .material-selection--dropdown > .attribute-groups { grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: none; grid-auto-rows: minmax(180px, auto); overflow-y: auto; }
  .material-selection--dropdown .attribute-groups:has(.craft-field) { grid-template-rows: none; }
  .material-selection--dropdown > .attribute-groups--seven > .attribute-group:last-of-type { grid-column: auto; }
  .attribute-groups--fabric-colors > .attribute-group--color { grid-column: auto; }
}
</style>
<style>
.material-selection-popover.el-popover { box-sizing: border-box; max-width: calc(100vw - 24px); padding: 0; border: 1px solid var(--erp-color-border); border-radius: var(--erp-radius-control); background: var(--erp-dropdown-background); color: var(--erp-color-text-primary); box-shadow: var(--erp-overlay-shadow); font-family: inherit; }
</style>
