<script setup lang="ts">
import { computed, defineAsyncComponent, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowDown, Warning } from '@element-plus/icons-vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import MaterialSelectionPanel from '@/components/products/MaterialSelectionPanel.vue'
import BomCuttingCatalogSelect from '@/views/boms/BomCuttingCatalogSelect.vue'
import BomMaterialSectionTables from '@/views/boms/BomMaterialSectionTables.vue'
import { bomCatalogCategories, catalogOwnOptions } from '@/components/products/materialSelection'
import { fetchMaterialCatalog, fetchMaterialCatalogOptions, fetchMaterialCatalogs, materialCatalogError } from '@/api/materialCatalog'
import { previewBomTubeCalculation } from '@/api/boms'
import { fixedSectionDefinitions } from '@/views/boms/bomEditorHelpers'
import { calculateHardwareWeight, hardwareWeightKey, initializeHardwareWeight, setManualHardwareWeight } from '@/views/boms/useHardwareWeightPreview'
import { cuttingCalculation } from '@/utils/bomCuttingQuantities'
import { pipePlanForBomLine } from '@/utils/materialFlow'
import type { BomLineInput } from '@/types/bom'
import type { MaterialCatalog, MaterialCatalogSummary } from '@/types/materialCatalog'
import { applyErpMatch, applyRecognizedCatalog, buildAiBomPlans, clearTubeMetrics, copyLatestErpMatch, erpBomFieldLabels, erpColorUpdates, erpFieldValues, fabricUnitIssue, isCuttingSource, isMeterUnit, latestErpMatch, linkTaskProducts, makeAiBomDrafts, materialNameMatches, prepareFabricMeterSelection, recognizedSection, recordValue, rememberCatalog, separateReferenceLines, tubeCalculationInput, tubeCalculationKey, tubeMetricFields,
  type AiBomDraft, type AiBomLine, type AiTaskProduct } from './AiImportBomFormData'

const props = defineProps<{ result: Record<string, unknown>; modelValue: Array<Record<string, unknown>> | null; taskProducts: AiTaskProduct[]; productQuantities?: Record<string, string>; disabled?: boolean; matchingMaterials?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: Array<Record<string, unknown>>]; 'match-materials': [] }>()
const drafts = ref<AiBomDraft[]>([])
const activeIndex = ref(0)
const selectedSection = ref('管材类')
const matching = ref(false)
const matchingError = ref('')
const fullscreen = ref(false)
const reviewExpanded = ref(false)
const editingLine = ref<AiBomLine | null>(null)
const editingOriginal = ref<AiBomLine | null>(null)
const editingSection = ref('')
const fabricUnitWarning = ref('')
const ProductionDataView = defineAsyncComponent(() => import('@/views/settings/ProductionDataView.vue'))
const maintenanceVisible = ref(false)
const maintenanceView = ref<{ canClose: () => Promise<boolean> }>()
const catalogRefreshKey = ref(0)
let generation = 0
let lastEmitted = ''
let disposed = false
const calculationRequests = new WeakMap<AiBomLine, string>()
const active = computed(() => drafts.value[activeIndex.value])
const section = computed(() => active.value?.sections.find(item => item.title === selectedSection.value))
const sourceMaterials = computed(() => active.value?.sections.flatMap(item => item.lines).filter(isCuttingSource) || [])
const lineCount = (draft: AiBomDraft) => draft.pending_lines.length + draft.sections.reduce((count, item) => count + item.lines.length, 0)
const reviewLines = computed(() => {
  if (!active.value) return []
  return [
    ...active.value.sections.flatMap(item => item.lines.filter(line => line.ai_pending.length).map(line => ({ line, sectionTitle: item.title, issues: line.ai_pending, reference: false }))),
    ...active.value.pending_lines.map(line => ({ line, sectionTitle: '', issues: ['请选择 BOM 分区', ...line.ai_pending], reference: false })),
    ...(active.value.reference_lines || []).map(line => ({ line, sectionTitle: '来源说明', issues: [...line.ai_pending, line.ai_original_text], reference: true })),
  ]
})
const noOptions = () => []
const noop = () => undefined
function selectProduct() {
  selectedSection.value = active.value?.sections.find(item => item.lines.length)?.title || (active.value?.pending_lines.length ? '待选分区' : '管材类')
}

function publish() {
  lastEmitted = JSON.stringify(drafts.value)
  emit('update:modelValue', JSON.parse(lastEmitted))
}
watch(() => [props.result, props.modelValue] as const, ([result, saved]) => {
  if (saved && JSON.stringify(saved) === lastEmitted) return
  generation++
  drafts.value = makeAiBomDrafts(result, saved)
  linkTaskProducts(drafts.value, props.taskProducts)
  updateOrderQuantities()
  activeIndex.value = Math.min(activeIndex.value, Math.max(0, drafts.value.length - 1))
  const first = active.value
  selectedSection.value = first?.sections.find(item => item.lines.length)?.title || (first?.pending_lines.length ? '待选分区' : '管材类')
  publish()
  const assistantStatus = recordValue(recordValue(result.recognition_meta).erp_assistant).status
  if (!saved && drafts.value.length && !['pending', 'failed'].includes(String(assistantStatus))) void matchMaterials()
  if (saved) void restoreSourceCatalogs()
}, { immediate: true })
watch(drafts, publish, { deep: true })
watch(() => [props.taskProducts, props.productQuantities] as const, ([products]) => {
  linkTaskProducts(drafts.value, products)
  updateOrderQuantities()
}, { deep: true, immediate: true })
watch(() => drafts.value.map(draft => draft.production_task_product_id).join('|'), updateOrderQuantities)
onBeforeUnmount(() => { disposed = true; generation++ })

function currentLine(line: AiBomLine) {
  return !disposed && (editingLine.value === line || drafts.value.some(draft => draft.sections.some(section => section.lines.includes(line))))
}
function syncTubeQuantityIssues(line: AiBomLine) {
  const missing = (['length_value', 'unit_consumption', 'tube_cut_piece_count'] as const)
    .filter(key => !line[key]?.trim()).map(key => erpBomFieldLabels[key])
  const pending = line.ai_pending.filter(item => !item.startsWith('管材用量：'))
  if (missing.length) pending.push(`管材用量：${missing.join('、')}待补，采购数量暂不能计算。`)
  if (pending.length !== line.ai_pending.length || pending.some((item, index) => item !== line.ai_pending[index])) line.ai_pending = pending
}
async function refreshTubeMetrics(line: AiBomLine) {
  syncTubeQuantityIssues(line)
  const key = tubeCalculationKey(line)
  if (line.ai_tube_formula_key === key && line.tube_calculation_preview || calculationRequests.get(line) === key) return
  clearTubeMetrics(line)
  const input = tubeCalculationInput(line)
  if (![input.tube_shape, input.tube_diameter, input.tube_thickness, input.length_value].every(value => value?.trim())) {
    line.ai_pending = [...line.ai_pending.filter(item => !item.startsWith('管材公式：')), '管材公式：形状、规格、厚度或切割长度待补']
    return
  }
  calculationRequests.set(line, key)
  try {
    const result = await previewBomTubeCalculation(input)
    if (!currentLine(line) || tubeCalculationKey(line) !== key) return
    for (const field of tubeMetricFields) line[field] = result[field]
    line.tube_calculation_preview = result
    line.expected_tube_formula_version = result.formula_version
    line.recalculate_tube_metrics = true
    line.ai_tube_formula_key = key
    line.ai_pending = line.ai_pending.filter(item => !item.startsWith('管材公式：'))
  } catch (error) {
    if (currentLine(line) && tubeCalculationKey(line) === key) line.ai_pending = [...line.ai_pending.filter(item => !item.startsWith('管材公式：')), `管材公式：${materialCatalogError(error)}`]
  } finally {
    if (calculationRequests.get(line) === key) calculationRequests.delete(line)
  }
}
async function refreshHardwareWeight(line: AiBomLine) {
  const sourceWeight = recordValue(erpFieldValues(line.ai_source.erp_fields).unit_material_weight_kg)
  if (['CONFLICT', 'UNREADABLE'].includes(String(sourceWeight.status))) return
  initializeHardwareWeight(line)
  if (line.hardware_weight_mode !== 'AUTO') {
    line.ai_pending = line.ai_pending.filter(item => !item.startsWith('五金重量：'))
    if (!line.unit_material_weight_kg.trim()) line.ai_pending.push('五金重量：单件重量待补，当前材料没有可直接使用的计算条件。')
    return
  }
  const key = hardwareWeightKey(line)
  if (calculationRequests.get(line) === key) return
  calculationRequests.set(line, key)
  try {
    if (await calculateHardwareWeight(line, () => currentLine(line))) line.ai_pending = line.ai_pending.filter(item => !item.startsWith('五金重量：'))
  } catch (error) {
    if (currentLine(line) && hardwareWeightKey(line) === key) line.ai_pending = [...line.ai_pending.filter(item => !item.startsWith('五金重量：')), `五金重量：${materialCatalogError(error)}`]
  } finally {
    if (calculationRequests.get(line) === key) calculationRequests.delete(line)
  }
}
function refreshCalculations() {
  for (const draft of drafts.value) for (const section of draft.sections) for (const line of section.lines) {
    if (section.title === '管材类') void refreshTubeMetrics(line)
    if (section.title === '五金件') void refreshHardwareWeight(line)
  }
}
watch(() => drafts.value.map(draft => draft.sections.map(section => [section.title, section.lines.map(line => [line.client_key, tubeCalculationKey(line), line.unit_consumption, line.part_name, line.material, line.specification, line.hardware_weight_mode, line.unit_material_weight_kg])])), refreshCalculations, { deep: true, immediate: true })
watch(() => editingLine.value && [editingSection.value, tubeCalculationKey(editingLine.value), editingLine.value.unit_consumption, editingLine.value.material, editingLine.value.specification], () => {
  if (editingLine.value && editingSection.value === '管材类') void refreshTubeMetrics(editingLine.value)
  if (editingLine.value && editingSection.value === '五金件') void refreshHardwareWeight(editingLine.value)
}, { deep: true })

async function restoreSourceCatalogs() {
  const token = generation
  for (const draft of drafts.value) {
    const sourceKeys = new Set(draft.sections.find(section => section.title === '裁剪明细')?.lines.map(line => line.fabric_source_client_key))
    for (const line of draft.sections.flatMap(section => section.lines)) {
      if (!sourceKeys.has(line.client_key) || !line.material_catalog_id || isCuttingSource(line)) continue
      try {
        const { data } = await fetchMaterialCatalog(line.material_catalog_id)
        if (token !== generation || !currentLine(line) || line.material_catalog_id !== data.id) return
        rememberCatalog(line, data)
      } catch (error) {
        if (token === generation && currentLine(line)) line.ai_pending = [...line.ai_pending.filter(item => !item.startsWith('来源原料：')), `来源原料：${materialCatalogError(error)}`]
      }
    }
  }
}

function updateOrderQuantities() {
  for (const draft of drafts.value) {
    const product = props.taskProducts.find(item => item.id === draft.production_task_product_id)
    if (product) draft.order_quantity = product.quantity ?? ''
    else if (props.productQuantities && Object.hasOwn(props.productQuantities, draft.product_key)) draft.order_quantity = props.productQuantities[draft.product_key] ?? ''
  }
}
function cancelMatching() {
  generation++
  matching.value = false
}
function chooseSection(draft: AiBomDraft, line: AiBomLine, title: string) {
  cancelMatching()
  moveLine(draft, line, title)
}

function moveLine(draft: AiBomDraft, line: AiBomLine, title: string) {
  const target = draft.sections.find(item => item.title === title)
  if (target?.lines.includes(line)) return
  for (const current of draft.sections) current.lines = current.lines.filter(item => item !== line)
  draft.pending_lines = draft.pending_lines.filter(item => item !== line)
  draft.reference_lines = draft.reference_lines?.filter(item => item !== line)
  if (target) target.lines.push(line)
  else draft.pending_lines.push(line)
}

function applyLatestMatches(result: Record<string, unknown> = props.result) {
  cancelMatching()
  for (const draft of drafts.value) {
    const lines = [...draft.pending_lines, ...draft.sections.flatMap(section => section.lines), ...(draft.reference_lines || [])]
    for (const line of lines) {
      if (editingOriginal.value === line || !copyLatestErpMatch(line, result, draft.product_key)) continue
      const title = applyErpMatch(line)
      if (title) moveLine(draft, line, title)
      else if (draft.reference_lines?.includes(line) && recordValue(line.ai_source.erp_match).status !== 'REFERENCE') moveLine(draft, line, recognizedSection(line.ai_source))
    }
    separateReferenceLines(draft)
  }
  refreshCalculations()
  void restoreSourceCatalogs()
  publish()
}

function requestMaterialMatch() {
  if (props.disabled || props.matchingMaterials || matching.value) return
  const candidates = drafts.value.flatMap(draft => [...draft.pending_lines, ...draft.sections.flatMap(section => section.lines), ...(draft.reference_lines || [])]
    .map(line => ({ line, match: latestErpMatch(props.result, draft.product_key, line.ai_line_key) })))
  const pending = candidates.filter(({ line }) => !line.material_catalog_id && !line.material_selection)
  const hasNewSuggestions = candidates.some(({ line, match }) => match && (Object.keys(erpColorUpdates(line, match)).length
    || !line.material_catalog_id && !line.material_selection && !(line.ai_reference_override && match.status === 'REFERENCE')
      && JSON.stringify(match) !== JSON.stringify(recordValue(line.ai_source.erp_match))))
  if (hasNewSuggestions) {
    applyLatestMatches()
    return
  }
  if (pending.some(({ match }) => !match || ['PARTIAL', 'NOT_FOUND', 'CONFLICT'].includes(String(match.status)))) emit('match-materials')
}

async function matchMaterials() {
  const token = ++generation
  matching.value = true
  matchingError.value = ''
  const names = new Map<string, Promise<MaterialCatalogSummary[]>>()
  const catalogDetails = new Map<string, ReturnType<typeof fetchMaterialCatalog>>()
  let definitions: ReturnType<typeof fetchMaterialCatalogOptions> | undefined
  const findName = (name: string, category: string) => {
    const key = `${category}/${name}`
    if (!names.has(key)) names.set(key, (async () => {
      const rows: MaterialCatalogSummary[] = []
      let pages = 1
      for (let page = 1; page <= pages; page++) {
        const response = await fetchMaterialCatalogs({ category, q: name, page, page_size: 100 })
        rows.push(...response.data)
        pages = response.meta.total_pages
      }
      return rows.filter(item => item.category_key === category && materialNameMatches(item.name, name))
    })())
    return names.get(key)!
  }
  try {
    for (const draft of drafts.value) {
      const lines = [...draft.pending_lines, ...draft.sections.flatMap(item => item.lines)]
      for (const line of lines) {
        if (token !== generation) return
        if (line.material_catalog_id || line.material_selection || !line.part_name || editingOriginal.value === line) continue
        const matchStatus = recordValue(line.ai_source.erp_match).status
        if (matchStatus && !(matchStatus === 'REFERENCE' && line.ai_reference_override)) {
          const title = applyErpMatch(line)
          if (title) moveLine(draft, line, title)
          continue
        }
        const title = draft.sections.find(section => section.lines.includes(line))?.title || ''
        const category = bomCatalogCategories[title]
        if (!category) {
          line.ai_pending = [...line.ai_pending.filter(item => !item.startsWith('ERP材料：')), 'ERP材料：请先核对材料分区，再对应同类材料。']
          continue
        }
        const candidates = await findName(line.part_name, category)
        if (token !== generation) return
        if (candidates.length !== 1) {
          line.ai_pending = [...line.ai_pending.filter(item => !item.startsWith('ERP材料：')), `ERP材料：${candidates.length ? '存在多个同名材料，请选择' : '未找到同名材料，请选择'}`]
          continue
        }
        const candidate = candidates[0]!
        if (!catalogDetails.has(candidate.id)) catalogDetails.set(candidate.id, fetchMaterialCatalog(candidate.id))
        const detail = catalogDetails.get(candidate.id)!
        definitions ??= fetchMaterialCatalogOptions()
        const [{ data: catalog }, templates] = await Promise.all([detail, definitions])
        if (token !== generation || editingOriginal.value === line) return
        if (catalog.category_key !== category) continue
        const template = templates.categories.find(item => item.key === category)?.templates.find(item => item.key === catalog.template_key)
        if (!template) throw new Error('品名的属性模板未加载，请重新读取。')
        const applied = applyRecognizedCatalog(line, catalog, { ...catalogOwnOptions(catalog, 'BASE'), fields: template.fields })
        if (applied) moveLine(draft, line, title)
        const unitIssue = catalog.category_key === 'FABRIC' ? fabricUnitIssue(line) : ''
        line.ai_pending = [...line.ai_pending.filter(item => !item.startsWith('ERP材料：')), ...(applied ? [] : [`ERP材料：${unitIssue || '品名已找到，具体属性和单位待选择'}`])]
      }
      separateReferenceLines(draft)
    }
    if (selectedSection.value === '待选分区' && !active.value?.pending_lines.length) selectedSection.value = active.value?.sections.find(item => item.lines.length)?.title || '管材类'
  } catch (error) {
    if (token === generation) matchingError.value = materialCatalogError(error)
  } finally {
    if (token === generation) {
      matching.value = false
      refreshCalculations()
      void restoreSourceCatalogs()
    }
  }
}

function openLine(line: AiBomLine, title: string) {
  if (props.disabled || props.matchingMaterials) return
  cancelMatching()
  editingOriginal.value = line
  editingLine.value = JSON.parse(JSON.stringify(line))
  editingSection.value = title
  fabricUnitWarning.value = title === '面料类' ? fabricUnitIssue(line) : ''
}
function changeEditingSection() {
  if (!editingLine.value) return
  editingLine.value.material_catalog_id = undefined
  editingLine.value.material_selection = undefined
  editingLine.value.material_selection_snapshot = undefined
  editingLine.value.ai_catalog = undefined
  editingLine.value.fabric_source_client_key = null
  fabricUnitWarning.value = editingSection.value === '面料类' ? fabricUnitIssue(editingLine.value) : ''
  if (editingSection.value !== '裁剪明细') {
    delete editingLine.value.cutting_pieces_per_set
    delete editingLine.value.cutting_sets_per_product
  }
}
function onMaterialLoaded(catalog?: MaterialCatalog) {
  if (catalog && editingLine.value) rememberCatalog(editingLine.value, catalog)
  if (editingSection.value === '面料类' && editingLine.value) fabricUnitWarning.value = prepareFabricMeterSelection(editingLine.value)
}
async function beforeMaintenanceClose(done: () => void) {
  if (!maintenanceView.value || await maintenanceView.value.canClose()) done()
}
function saveLine() {
  if (!active.value || !editingOriginal.value || !editingLine.value) return
  const original = editingOriginal.value
  const wasReference = active.value.reference_lines?.includes(original)
  Object.assign(original, editingLine.value)
  if (wasReference && editingSection.value) {
    original.ai_reference_override = true
    original.ai_pending = original.ai_pending.filter(item => !item.startsWith('ERP对应：'))
  }
  if (original.material_catalog_id && original.material_selection) original.ai_pending = original.ai_pending.filter(item => !item.startsWith('ERP材料：'))
  if (!wasReference || editingSection.value) moveLine(active.value, original, editingSection.value)
  selectedSection.value = editingSection.value || '待选分区'
  editingLine.value = null
  editingOriginal.value = null
}
function removeEditingLine() {
  if (!active.value || !editingOriginal.value) return
  for (const item of active.value.sections) item.lines = item.lines.filter(line => line !== editingOriginal.value)
  active.value.pending_lines = active.value.pending_lines.filter(line => line !== editingOriginal.value)
  active.value.reference_lines = active.value.reference_lines?.filter(line => line !== editingOriginal.value)
  editingLine.value = null
  editingOriginal.value = null
}

const editingFields = computed(() => {
  const fields: Record<string, string[]> = {
    管材类: ['length_value', 'unit_consumption', 'tube_cut_piece_count', 'source_raw_bar_length_m', 'tube_coating_color'],
    五金件: ['unit_consumption', 'unit_material_weight_kg', 'powder_coating_color', 'powder_coating_unit_area_sqm'],
    塑料件类: ['unit_consumption'], 辅料类: ['unit_consumption'], 面料类: ['unit_consumption'],
    包材类: ['units_per_box'], 裁剪明细: ['specification', 'cutting_pieces_per_set', 'cutting_sets_per_product'],
  }
  return fields[editingSection.value] || []
})
const moreEditingFields = computed(() => {
  const fields = ['source_purchase_allowance_percent', 'coating_unit_area_sqm', 'purchase_unit_weight_kg', 'long_material_unit_weight_kg',
    'unit_material_weight_kg', 'powder_coating_unit_area_sqm', 'hardness', 'raw_material', 'original_material_length']
  const source = erpFieldValues(editingOriginal.value?.ai_source.erp_fields)
  const current = editingOriginal.value as unknown as Record<string, unknown> | null
  return fields.filter(key => !editingFields.value.includes(key) &&
    (isFormulaField(key) || String(current?.[key] ?? '').trim() !== '' || String(recordValue(source[key]).value ?? '').trim() !== ''))
})
function lineField(key: string): string { return String((editingLine.value as unknown as Record<string, unknown> | null)?.[key] || '') }
function setLineField(key: string, value: string) {
  if (!editingLine.value) return
  ;(editingLine.value as unknown as Record<string, unknown>)[key] = value
  if (key === 'unit_material_weight_kg') setManualHardwareWeight(editingLine.value)
  if (key === 'unit_consumption' && editingSection.value === '面料类' && isMeterUnit(editingLine.value.unit)) {
    editingLine.value.ai_pending = editingLine.value.ai_pending.filter(item => !item.startsWith('面料单位：'))
    fabricUnitWarning.value = ''
  }
}
function isFormulaField(key: string) { return editingSection.value === '管材类' && tubeMetricFields.includes(key as typeof tubeMetricFields[number]) }

function tubeQuantities(line: BomLineInput) {
  const plan = pipePlanForBomLine(line, active.value?.order_quantity || '')
  // 旧计划的branch_count可能已含原表百分比余量；用同一公式拆分显示，不改原用量。
  const base = plan?.base_purchase_bar_count ?? (plan ? pipePlanForBomLine({ ...line, source_purchase_allowance_percent: '0' }, active.value?.order_quantity || '')?.branch_count : undefined)
  const allowance = plan?.purchase_allowance_bar_count ?? (plan && base ? String(BigInt(plan.branch_count) - BigInt(base)) : undefined)
  return { total_consumption: plan?.total_consumption || '—', tube_cut_length_m: line.source_raw_bar_length_m?.trim() || plan?.tube_cut_length_m || '—',
    branch_count: plan?.branch_count || '—', base_purchase_bar_count: base || '—',
    purchase_allowance_bar_count: allowance || '—', suggested_purchase_meters: plan?.suggested_purchase_meters || '—', suggested_purchase_weight_kg: '—' }
}
const tableProps = computed(() => ({
  isHardwareSection: selectedSection.value === '五金件', isPlasticSection: selectedSection.value === '塑料件类',
  isAuxiliarySection: selectedSection.value === '辅料类', isFabricSection: selectedSection.value === '面料类',
  isPackagingSection: selectedSection.value === '包材类', isCuttingSection: selectedSection.value === '裁剪明细',
  orderQuantity: active.value?.order_quantity || '', canEdit: false, tableFullscreen: fullscreen.value,
  tubeOptionsLoading: false, editorReferenceOptionsLoading: false, tubeCoatingColors: [],
  toggleTableFullscreen: () => { fullscreen.value = !fullscreen.value }, openLineDrawer: noop, removeLine: noop, openLineImageManager: noop,
  tubeCalculations: tubeQuantities, formatHardwareColor: (value: string) => value || '—', auxiliaryLineHasActiveProduct: () => false,
  auxiliarySpecificationOptions: noOptions, setAuxiliarySpecification: noop, auxiliaryColorOptions: noOptions, setAuxiliaryColor: noop,
  auxiliaryMaterialOptions: noOptions, setAuxiliaryMaterial: noop, fabricSpecificationOptions: noOptions, setFabricSpecification: noop,
  fabricMaterialOptions: noOptions, setFabricMaterial: noop, fabricColorSnapshot: (line: BomLineInput) => [line.fabric_color_card, line.fabric_color_code, line.fabric_color_name].filter(Boolean).join(' / '),
  fabricColorOptions: noOptions, setFabricColor: noop, fabricWidthOptions: noOptions, setFabricWidth: noop,
  cuttingQuantities: (line: BomLineInput) => cuttingCalculation(line, active.value?.order_quantity), legacyPipeCuttingValues: () => null,
}))
function buildPlans() { return buildAiBomPlans(drafts.value, props.taskProducts) }
defineExpose({ buildPlans, applyLatestMatches })
</script>

<template>
  <Teleport to="body" :disabled="!fullscreen">
  <section class="ai-bom-form" :class="{ 'is-fullscreen': fullscreen }" :inert="disabled || matchingMaterials">
    <div class="bom-heading">
      <div class="bom-title"><h2>BOM 资料</h2><span v-if="active" class="quiet-count">{{ lineCount(active) }} 行</span><el-button v-if="fullscreen" class="fullscreen-exit" link @click="fullscreen = false">退出全屏</el-button></div>
      <div v-if="active" class="heading-actions">
        <label class="current-product"><span>当前产品</span><el-select v-model="activeIndex" aria-label="当前 BOM 产品" @change="selectProduct"><el-option v-for="(draft, index) in drafts" :key="`${draft.product_key}-${index}`" :value="index" :label="`${draft.product_label} · ${lineCount(draft)} 项`" /></el-select></label>
        <el-button class="review-toggle" link :aria-expanded="reviewExpanded" @click="reviewExpanded = !reviewExpanded">待核对内容<span v-if="reviewLines.length">（{{ reviewLines.length }}）</span><el-icon :class="{ expanded: reviewExpanded }"><ArrowDown /></el-icon></el-button>
      </div>
    </div>
    <el-alert v-if="matchingError" :title="matchingError" type="error" :closable="false" />
    <el-empty v-if="!drafts.length" description="本次没有识别出 BOM 资料" />
    <template v-else-if="active">
      <div v-if="reviewExpanded" class="review-content" aria-label="BOM待核对内容">
        <p v-if="!reviewLines.length" class="review-empty">当前产品没有待核对材料。</p>
        <ul v-else><li v-for="(item, index) in reviewLines" :key="`${item.line.client_key}-${index}`"><el-button link type="primary" @click="selectedSection = item.reference ? '待选分区' : item.sectionTitle || '待选分区'; openLine(item.line, item.reference ? '' : item.sectionTitle)">{{ item.line.part_name || '未命名材料' }}</el-button><span class="review-section">{{ item.sectionTitle || '待选分区' }}</span><span>{{ item.issues.join('；') }}</span></li></ul>
      </div>
      <div class="bom-layout">
        <nav class="section-nav" aria-label="BOM材料分区"><h3>物料分类</h3><button v-for="item in active.sections" :key="item.title" type="button" :class="{ active: selectedSection === item.title }" :aria-current="selectedSection === item.title ? 'true' : undefined" @click="selectedSection = item.title"><span>{{ item.title }}</span><small>{{ item.lines.length }}</small></button><button type="button" :class="{ active: selectedSection === '待选分区' }" :aria-current="selectedSection === '待选分区' ? 'true' : undefined" @click="selectedSection = '待选分区'"><span>待选分区</span><small>{{ active.pending_lines.length }}</small></button></nav>
        <div class="section-table">
          <div class="material-heading"><strong>{{ selectedSection }}</strong><span>订单数量：{{ active.order_quantity || '待确认' }}</span><el-button link :loading="matching || matchingMaterials" :disabled="disabled || matchingMaterials" @click="requestMaterialMatch">对应 ERP 材料</el-button></div>
          <BomMaterialSectionTables v-if="section" :active-section="section" v-bind="tableProps">
            <template #trailing-columns><el-table-column label="原始识别内容" width="360" fixed="right"><template #default="scope"><div class="source-cell"><el-button link type="primary" @click="openLine(scope.row, section!.title)">调整材料</el-button><el-input v-model="scope.row.ai_original_text" type="textarea" @update:model-value="cancelMatching" :rows="1" resize="none" aria-label="原始识别内容" /><el-tooltip v-if="scope.row.ai_pending.length" :content="scope.row.ai_pending.join('；')" placement="top"><el-button class="pending-indicator" link :icon="Warning" :aria-label="`${scope.row.part_name || '当前材料'}：${scope.row.ai_pending.join('；')}`" @click="reviewExpanded = true" /></el-tooltip></div></template></el-table-column></template>
          </BomMaterialSectionTables>
          <el-table v-else :data="active.pending_lines" border empty-text="没有待选分区的材料"><el-table-column prop="part_name" label="品名" min-width="150" /><el-table-column prop="material" label="材质" min-width="100" /><el-table-column prop="specification" label="规格" min-width="160" /><el-table-column label="分区" width="160"><template #default="scope"><el-select placeholder="选择分区" :model-value="''" @change="chooseSection(active!, scope.row, $event)"><el-option v-for="item in fixedSectionDefinitions" :key="item.title" :label="item.title" :value="item.title" /></el-select></template></el-table-column><el-table-column label="原始识别内容" width="360" fixed="right"><template #default="scope"><div class="source-cell"><el-button link type="primary" @click="openLine(scope.row, '')">调整材料</el-button><el-input v-model="scope.row.ai_original_text" type="textarea" @update:model-value="cancelMatching" :rows="1" resize="none" aria-label="原始识别内容" /></div></template></el-table-column></el-table>
          <div class="product-link"><label>对应任务产品<el-select v-model="active.production_task_product_id" clearable placeholder="创建任务后选择对应产品" :disabled="!taskProducts.length" aria-label="BOM对应任务产品"><el-option v-for="product in taskProducts" :key="product.id" :value="product.id" :label="[product.product_name_snapshot || product.client_key || product.id, product.specification_snapshot].filter(Boolean).join(' · ')" /></el-select></label><span>当前显示 {{ selectedSection }} · {{ section ? section.lines.length : active.pending_lines.length }} 行</span></div>
        </div>
      </div>
    </template>
    <el-dialog :model-value="!!editingLine" title="调整 BOM 材料" width="min(920px, 94vw)" destroy-on-close @close="editingLine = null; editingOriginal = null">
      <template v-if="editingLine"><el-form label-position="top"><el-form-item label="BOM 分区"><el-select v-model="editingSection" placeholder="选择分区" @change="changeEditingSection"><el-option v-for="item in fixedSectionDefinitions" :key="item.title" :label="item.title" :value="item.title" /></el-select></el-form-item>
        <template v-if="editingSection === '裁剪明细'"><el-form-item label="来源原材料"><el-select v-model="editingLine.fabric_source_client_key" clearable placeholder="选择本 BOM 中的米制面料或棉类原料"><el-option v-for="material in sourceMaterials" :key="material.client_key" :value="material.client_key!" :label="`${material.part_name} · ${material.specification}`" /></el-select></el-form-item><el-form-item label="裁片品名"><BomCuttingCatalogSelect :line="editingLine" :refresh-key="catalogRefreshKey" /></el-form-item></template>
        <MaterialSelectionPanel v-else-if="editingSection" :key="editingSection" :line="editingLine" :section-title="editingSection" presentation="panel" :catalog-only="true" :refresh-key="catalogRefreshKey" @loaded="onMaterialLoaded" @maintain="maintenanceVisible = true" :fixed-unit="editingSection === '管材类' ? '根' : editingSection === '面料类' ? '米' : undefined" />
        <el-alert v-if="fabricUnitWarning" :title="fabricUnitWarning" type="warning" :closable="false" /><div class="line-fields"><el-form-item v-for="key in editingFields" :key="key" :label="editingSection === '面料类' && key === 'unit_consumption' ? '单耗（米 / 成品）' : erpBomFieldLabels[key]"><el-input :model-value="lineField(key)" :aria-label="erpBomFieldLabels[key]" @update:model-value="setLineField(key, $event)" /><small v-if="key === 'source_raw_bar_length_m'" class="field-hint">最多 3 位小数；原表值保留在原始识别内容中。</small></el-form-item></div><details v-if="moreEditingFields.length" class="more-fields"><summary>更多字段（{{ moreEditingFields.length }}）</summary><div class="line-fields"><el-form-item v-for="key in moreEditingFields" :key="key" :label="erpBomFieldLabels[key]"><el-input :model-value="lineField(key)" :aria-label="erpBomFieldLabels[key]" :readonly="isFormulaField(key)" @update:model-value="setLineField(key, $event)" /></el-form-item></div></details>
        <el-form-item label="备注"><el-input v-model="editingLine.notes" type="textarea" :rows="2" /></el-form-item><el-form-item label="原始识别内容"><el-input v-model="editingLine.ai_original_text" type="textarea" :rows="5" /></el-form-item>
      </el-form></template>
      <template #footer><el-button type="danger" plain @click="removeEditingLine">移除此行</el-button><el-button @click="editingLine = null; editingOriginal = null">取消</el-button><el-button type="primary" @click="saveLine">保留调整</el-button></template>
    </el-dialog>
    <AppWindowDialog v-model="maintenanceVisible" title="生产维护" :width="1100" height="80vh" fullscreen edge-to-edge destroy-on-close :close-on-click-modal="false" :before-close="beforeMaintenanceClose" @closed="catalogRefreshKey++">
      <ProductionDataView v-if="maintenanceVisible" ref="maintenanceView" embedded :initial-category="bomCatalogCategories[editingSection] || ''" />
    </AppWindowDialog>
  </section>
  </Teleport>
</template>

<style scoped lang="scss">
.ai-bom-form { min-width: 0; }
.bom-heading { display: flex; min-height: 44px; flex-shrink: 0; align-items: center; justify-content: space-between; gap: 12px; }
.bom-title, .heading-actions { display: flex; align-items: center; gap: 12px; }
h2 { margin: 0; font-size: 18px; line-height: 26px; font-weight: 650; }
.quiet-count, .current-product > span, .product-link, .material-heading > span { color: var(--erp-color-text-muted); font-size: 12px; }
.current-product { display: flex; align-items: center; gap: 10px; }
.current-product .el-select { width: 220px; }
.review-toggle { font-size: 12px; }
.review-toggle .el-icon { margin-left: 6px; transition: transform .16s ease; }
.review-toggle .el-icon.expanded { transform: rotate(180deg); }
.review-content { margin-bottom: 14px; padding: 10px 14px; border-radius: 5px; background: var(--erp-glass-inner-background); font-size: 12px; line-height: 20px; }
.review-content ul { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.review-content li { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px; }
.review-content li > span:last-child { flex: 1; min-width: 180px; }
.review-content .el-button { font-size: 12px; }
.review-section, .review-empty { color: var(--erp-color-text-muted); }
.review-empty { margin: 0; }
.product-link { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 20px; padding-top: 8px; }
.product-link label { display: flex; align-items: center; gap: 10px; }
.product-link .el-select { width: 280px; max-width: 60vw; }
.bom-layout { display: grid; height: clamp(300px, calc(100dvh - 730px), 520px); grid-template-columns: 146px minmax(0, 1fr); gap: 14px; align-items: stretch; }
.section-nav { display: flex; min-height: 0; overflow: auto; flex-direction: column; padding-bottom: 6px; border-radius: 8px; background: var(--erp-glass-background); }
.section-nav h3 { height: 36px; flex-shrink: 0; box-sizing: border-box; margin: 0 0 6px; padding: 0 14px; border-bottom: 1px solid var(--erp-color-border); font-size: 13px; line-height: 36px; font-weight: 600; }
.section-nav button { display: flex; width: calc(100% - 12px); height: 46px; flex-shrink: 0; align-items: center; justify-content: space-between; margin: 0 6px; padding: 0 10px; border: 0; border-left: 3px solid transparent; border-radius: 0; background: transparent; color: var(--erp-color-text-secondary); cursor: pointer; font: inherit; font-size: 13px; white-space: nowrap; }
.section-nav button:hover { background: var(--erp-color-hover); }
.section-nav button.active { border-left-color: var(--erp-navigation-accent); color: var(--erp-navigation-accent); background: var(--erp-color-selected); font-weight: 600; }
.section-nav button:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: -2px; }
.section-nav small { color: var(--erp-color-text-muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.section-nav button.active small { color: inherit; }
.section-table { display: flex; min-width: 0; min-height: 0; flex-direction: column; }
.material-heading { display: flex; height: 36px; flex-shrink: 0; align-items: center; gap: 14px; padding: 0 2px; }
.material-heading strong { font-size: 13px; font-weight: 600; }
.material-heading > .el-button { margin-left: auto; font-size: 12px; }
.section-table :deep(.el-table) { flex: 1; min-height: 0; max-width: 100%; border-radius: 5px; --el-table-header-bg-color: var(--erp-table-header-fill); --el-table-header-text-color: var(--erp-table-header-text); --el-table-bg-color: var(--erp-table-body-fill); --el-table-tr-bg-color: var(--erp-table-body-fill); --el-table-text-color: var(--erp-table-text); --el-table-border-color: var(--erp-table-grid); --el-table-row-hover-bg-color: var(--erp-table-hover); }
.section-table :deep(.el-table__inner-wrapper), .section-table :deep(.el-table__body-wrapper) { min-height: 0; }
.section-table :deep(.pending-section-fields) { flex: 1; min-height: 0; }
.product-link { flex-shrink: 0; }
.section-table :deep(.el-table th.el-table__cell) { height: 44px; padding: 0; font-size: 12px; font-weight: 500; }
.section-table :deep(.el-table td.el-table__cell) { height: 34px; padding: 0; font-size: 12px; }
.section-table :deep(.el-table .cell) { padding: 0 16px !important; font-size: 12px; line-height: 18px; }
.section-table :deep(.el-table .control-column .cell), .section-table :deep(.el-table .control-column-header .cell) { padding: 0 !important; }
.section-table :deep(.prototype-tube-table .el-table__body td.el-table__cell) { background: var(--erp-table-body-fill); }
.section-table :deep(.el-table .el-table__body tr:hover > td.el-table__cell), .section-table :deep(.el-table .el-table__body tr.hover-row > td.el-table__cell) { background: var(--erp-table-hover); }
.section-table :deep(.el-table .el-table__body-wrapper .el-scrollbar__view) { padding-bottom: 0; }
.section-table :deep(.el-table .el-input__wrapper), .section-table :deep(.el-table .el-select__wrapper) { min-height: 28px; padding: 0 6px; border-radius: 5px; background: transparent; box-shadow: none; font-size: 12px; }
.section-table :deep(.el-table .el-input__inner) { height: 28px; color: var(--erp-table-text); font-size: 12px; }
.section-table :deep(.el-table .el-select__selected-item), .section-table :deep(.el-table .hardware-readonly-cell) { padding: 0; color: var(--erp-table-text); font-size: 12px; }
.section-table :deep(.el-table .el-input:not(.is-disabled) .el-input__wrapper:hover), .section-table :deep(.el-table .el-input__wrapper.is-focus), .section-table :deep(.el-table .el-select__wrapper:not(.is-disabled):hover), .section-table :deep(.el-table .el-select__wrapper.is-focused) { background: var(--erp-input-background); box-shadow: 0 0 0 1px var(--erp-input-focus-border) inset; }
.section-table :deep(.el-table__row:hover .table-row-number) { display: inline; }
.source-cell { display: flex; min-width: 0; height: 32px; align-items: center; gap: 8px; }
.source-cell > .el-button { flex-shrink: 0; margin: 0; font-size: 12px; }
.source-cell > .el-textarea { flex: 1; min-width: 0; }
.source-cell :deep(.el-textarea__inner) { min-height: 28px !important; height: 28px; padding: 4px 6px !important; border-radius: 5px; background: transparent !important; box-shadow: none !important; color: var(--erp-table-text); font-size: 12px !important; line-height: 20px; }
.source-cell :deep(.el-textarea__inner:hover), .source-cell :deep(.el-textarea__inner:focus) { background: var(--erp-input-background) !important; box-shadow: 0 0 0 1px var(--erp-input-focus-border) inset !important; }
.source-cell > .pending-indicator { color: var(--erp-color-warning); }
.line-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); column-gap: 18px; margin-top: 18px; }
.field-hint { color: var(--erp-color-text-secondary); font-size: 12px; line-height: 1.5; }
.more-fields { margin-bottom: 18px; }
.more-fields summary { cursor: pointer; color: var(--el-color-primary); }
.is-fullscreen { display: flex; position: fixed; inset: 16px; z-index: 1200; min-height: 0; overflow: auto; flex-direction: column; padding: 24px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-table-background); }
.is-fullscreen .bom-layout { flex: 1; height: auto; min-height: 0; max-height: none; }
.is-fullscreen .review-content { flex-shrink: 0; max-height: 30vh; overflow: auto; }
@media (max-width: 760px) { .bom-heading { align-items: flex-start; flex-wrap: wrap; padding: 8px 0; } .heading-actions { flex-wrap: wrap; } .bom-layout { height: auto; grid-template-columns: minmax(0, 1fr); } .section-nav { flex-direction: row; flex-wrap: wrap; padding: 0; } .section-nav h3 { width: 100%; margin-bottom: 0; } .section-nav button { width: auto; gap: 8px; margin: 0; padding: 0 12px; } .section-table { height: clamp(300px, calc(100dvh - 250px), 520px); } .line-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
