<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox, useZIndex } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'

import {
  confirmBomProduct,
  deleteBomDraftLineImage,
  deleteBomLineImage,
  fetchBomEditorReferenceOptions,
  previewBomMaterialFlow,
  previewBomMaterialSave,
  fetchBomForEdit,
  fetchBomHardwareMaterialGroups,
  fetchBomHardwareMaterials,
  fetchBomPackagingMaterialGroups,
  fetchBomPackagingMaterials,
  fetchBomPlasticMaterialGroups,
  fetchBomPlasticMaterials,
  fetchBomSemiFinishedMaterialGroups,
  fetchBomSemiFinishedMaterials,
  saveBomDraft,
  syncBomOrderQuantity,
  uploadBomLineImages,
  uploadBomDraftLineImages,
  verifyBom,
} from '@/api/boms'
import { fetchAllProductionDataRecords } from '@/api/productionData'
import BomLineEditorDialog from '@/components/BomLineEditorDialog.vue'
import BomPrintDocument from '@/components/boms/BomPrintDocument.vue'
import BomLineImageManager from './BomLineImageManager.vue'
import BomLineEditorForm from './BomLineEditorForm.vue'
import BomMaterialSectionTables from './BomMaterialSectionTables.vue'
import BomMaterialPickerDialogs from './BomMaterialPickerDialogs.vue'
import BomProductInfoDialog from './BomProductInfoDialog.vue'
import BomProductOverview from './BomProductOverview.vue'
import BomProductConfirmationDialogs from './BomProductConfirmationDialogs.vue'
import BomMaterialCreateDialogs from './BomMaterialCreateDialogs.vue'
import BomQuantityCompareCard from './BomQuantityCompareCard.vue'
import BomSectionSidebar from './BomSectionSidebar.vue'
import { fetchProductOptions } from '@/api/products'
import type { InquiryItem } from '@/types/inquiry'
import { useAuthStore } from '@/stores/auth'
import type {
  BomAuxiliaryProductOption,
  BomDetail,
  BomDraftLineImage,
  BomEditorReferenceOptions,
  BomHardwareMaterial,
  BomLine,
  BomLineImage,
  BomLineInput,
  BomMaterialSaveOptions,
  BomPackagingMaterial,
  BomPlasticMaterial,
  BomProductColorOption,
  BomSemiFinishedMaterial,
  BomSectionInput,
} from '@/types/bom'
import type { ProductInformation, ProductInformationInput, ProductOptions } from '@/types/product'
import type { ProductColor } from '@/types/productionData'
import { createProductionDataRecord } from '@/api/productionData'
import { pipePlan } from '@/utils/materialFlow'
import { cuttingCalculation, cuttingCompatibilityValues, legacyPipeCuttingValues } from '@/utils/bomCuttingQuantities'
import { cuttingSpecificationError } from '@/utils/cuttingSpecification'
import { useBomMaterialCandidates } from './useBomMaterialCandidates'
import {
  blankLine as createBlankLine,
  createDraftKey,
  decimalDifferenceText,
  decimalFraction,
  decimalValuesEqual,
  editableLine as normalizeEditableLine,
  number,
  tubeCalculations as calculateTubeCalculations,
  withFixedSections,
} from './bomEditorHelpers'
import type {
  TubeCoatingColor,
  TubeDiameter,
  TubeMaterial,
  TubeProductName,
  TubeShape,
  TubeThickness,
} from '@/types/productionData'
import type { RawMaterialInformation, RawMaterialInput } from '@/types/rawMaterial'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const bom = ref<BomDetail | null>(null)
const activeEditorTab = ref<'product' | 'materials'>('materials')
const focusedEditorTab = ref<'product' | 'materials'>('materials')
function selectEditorTab(tab: 'product' | 'materials') {
  activeEditorTab.value = tab
  focusedEditorTab.value = tab
}
function focusEditorTab(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const tabs = Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLButtonElement>('[role="tab"]'))
  const current = tabs.indexOf(document.activeElement as HTMLButtonElement)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
  focusedEditorTab.value = next === 0 ? 'product' : 'materials'
  tabs[next]?.focus()
}
const etag = ref('')
const sections = ref<BomSectionInput[]>([])
// 旧明细删除后先记录，保存草稿时由后端根据“提交中缺失的旧明细编号”删除数据库记录。
// 新增明细没有 id，不进入此集合，删除它只会让它不被保存。
const pendingDeletedLineIds = ref(new Set<string>())
const activeSectionIndex = ref(0)
const selectedLineIndex = ref(0)
const quantityReason = ref('')
const loading = ref(true)
let bomLoadGeneration = 0
let bomLoadController: AbortController | undefined
let disposed = false
const saving = ref(false)
const syncingQuantity = ref(false)
const verifying = ref(false)
interface PendingBomSave {
  bomId: string
  etag: string
  sections: BomSectionInput[]
  options: BomMaterialSaveOptions
  snapshot: string
  showMessage: boolean
  deletedCount: number
}
const errorMessage = ref('')
const tubeOptionsLoading = ref(false)
const tubeShapes = ref<TubeShape[]>([])
const tubeProductNames = ref<TubeProductName[]>([])
const tubeMaterials = ref<TubeMaterial[]>([])
const tubeDiameters = ref<TubeDiameter[]>([])
const tubeThicknesses = ref<TubeThickness[]>([])
const tubeCoatingColors = ref<TubeCoatingColor[]>([])
const tableFullscreen = ref(false)
const automaticallyPromptedBomId = ref('')
const productConfirmVisible = ref(false)
const productConfirmCreateVisible = ref(false)
const productConfirmColorCreateVisible = ref(false)
const productConfirmLoading = ref(false)
const productConfirmOptions = ref<ProductOptions>({ categories: [], units: [], items: [] })
const productConfirmColors = ref<ProductColor[]>([])
const productConfirmCatalogError = ref('')
const productConfirmCatalogLoading = ref(false)
const productConfirmError = ref('')
const productConfirmDialog = ref<InstanceType<typeof BomProductConfirmationDialogs>>()
const productCreateInitial = ref<Partial<ProductInformationInput>>({})
const productCreateReviewDraft = ref<InquiryItem | null>(null)
const productCreateUnitCode = ref('')
const productCreateItemNumber = ref('')
const productInfoVisible = ref(false)
const productColorDraft = ref({ color_card: '', color_code: '', color_name: '' })
const lineDrawerVisible = ref(false)
const editingSectionIndex = ref(-1)
const fabricSourceLines = computed(() => sections.value.filter((section) => section.title === '面料类')
  .flatMap((section) => section.lines).filter((line) => (line.id || line.client_key) && line.unit === '米'
    && (line.id || line.part_name.trim() || line.source_inventory_material_id || line.source_fabric_material_id || line.source_fabric_specification_id)))

const editingFabricSourceKey = computed({
  get: () => editingLineDraft.value?.fabric_source_line_id || editingLineDraft.value?.fabric_source_client_key || '',
  set: (key: string) => {
    const draft = editingLineDraft.value
    if (!draft) return
    const source = fabricSourceLines.value.find((line) => (line.id || line.client_key) === key)
    draft.fabric_source_line_id = source?.id || null
    draft.fabric_source_client_key = source && !source.id ? source.client_key || null : null
    syncCuttingSourceAttributes(draft)
  },
})

function syncCuttingSourceAttributes(line: BomLineInput) {
  if (isPipeCuttingLine(line)) return
  const source = fabricSourceLines.value.find((item) => line.fabric_source_line_id
    ? item.id === line.fabric_source_line_id
    : Boolean(line.fabric_source_client_key && !item.id && item.client_key === line.fabric_source_client_key))
  line.material = source?.material || ''
  line.cutting_color = source?.fabric_color_name || source?.fabric_color_code || ''
}

const editingLineIndex = ref(-1)
const editingLineDraft = ref<BomLineInput | null>(null)
const editingLineIsNew = ref(false)
const advancingLineDrawer = ref(false)
const calculatingLine = ref(false)
let advancingLineUnlockTimer: number | undefined
const hardwareCreateVisible = ref(false)
const plasticCreateVisible = ref(false)
const packagingCreateVisible = ref(false)
const cuttingCreateVisible = ref(false)
const editorReferenceOptions = ref<BomEditorReferenceOptions | null>(null)
const editorReferenceOptionsLoading = ref(false)
const editorReferenceOptionsError = ref('')
let editorReferenceOptionsPromise: Promise<BomEditorReferenceOptions | null> | null = null
const auxiliaryPickerVisible = ref(false)
const auxiliaryCreateVisible = ref(false)
const auxiliaryPickerProductName = ref('')
const auxiliaryPickerKeyword = ref('')
const auxiliaryPickerPage = ref(1)
const auxiliaryPickerPageSize = ref(50)
const selectedAuxiliaryProducts = ref<Record<string, BomAuxiliaryProductOption>>({})
type RawMaterialTarget = 'hardware' | 'plastic' | 'packaging' | 'cutting'
const pendingRawMaterials = ref<Record<string, { target: RawMaterialTarget; payload: RawMaterialInput; candidate: BomHardwareMaterial }>>({})

function withPendingMaterials(target: RawMaterialTarget, candidates: BomHardwareMaterial[], keyword: string, materialName: string) {
  const query = keyword.trim().toLocaleLowerCase('zh-CN')
  const pending = Object.values(pendingRawMaterials.value).filter(item => item.target === target).map(item => item.candidate)
    .filter(item => (!materialName || item.material_name === materialName)
      && (!query || [item.material_number, item.material_name, item.specification, item.material, item.color_name].some(value => value.toLocaleLowerCase('zh-CN').includes(query))))
  return [...pending, ...candidates]
}

function pendingLineValues(item: BomHardwareMaterial): Partial<BomLineInput> {
  const pending = pendingRawMaterials.value[item.id]
  return pending ? { client_key: item.id, pending_raw_material: { ...pending.payload } } : {}
}
const hardwarePicker = useBomMaterialCandidates({
  label: '五金', fetchCandidates: fetchBomHardwareMaterials, fetchGroups: fetchBomHardwareMaterialGroups,
  mergeCandidates: (rows, query) => withPendingMaterials('hardware', rows, query.q || '', query.material_name || ''),
  errorMessage: apiError,
})
const {
  visible: hardwarePickerVisible, loading: hardwarePickerLoading,
  error: hardwarePickerError, groupLoading: hardwareGroupLoading,
  groupError: hardwareGroupError,
  materialName: hardwarePickerMaterialName, keyword: hardwarePickerKeyword,
  page: hardwarePickerPage, pageSize: hardwarePickerPageSize,
  total: hardwarePickerTotal, candidates: hardwareCandidates,
  selected: selectedHardware, visibleGroups: visibleHardwareGroups,
  selectedCount: selectedHardwareCount, pageAllSelected: hardwarePageAllSelected,
  pageSelectionIndeterminate: hardwarePageSelectionIndeterminate, loadCandidates: loadHardwareCandidates,
  loadGroups: loadHardwareGroups, search: searchHardwareCandidates,
  changePage: changeHardwarePage, filterGroups: filterHardwareGroups,
  clearGroupFilter: clearHardwareGroupFilter, toggleCandidate: toggleHardwareCandidate,
  toggleRow: toggleHardwareRow, rowClass: hardwarePickerRowClass,
  togglePage: toggleHardwarePage, onClosed: resetHardwarePickerState,
} = hardwarePicker

const plasticPicker = useBomMaterialCandidates({
  label: '塑料件', fetchCandidates: fetchBomPlasticMaterials, fetchGroups: fetchBomPlasticMaterialGroups,
  mergeCandidates: (rows, query) => withPendingMaterials('plastic', rows, query.q || '', query.material_name || ''),
  errorMessage: apiError,
})
const {
  visible: plasticPickerVisible, loading: plasticPickerLoading,
  error: plasticPickerError, groupLoading: plasticGroupLoading,
  groupError: plasticGroupError,
  materialName: plasticPickerMaterialName, keyword: plasticPickerKeyword,
  page: plasticPickerPage, pageSize: plasticPickerPageSize,
  total: plasticPickerTotal, candidates: plasticCandidates,
  selected: selectedPlastic, visibleGroups: visiblePlasticGroups,
  selectedCount: selectedPlasticCount, pageAllSelected: plasticPageAllSelected,
  pageSelectionIndeterminate: plasticPageSelectionIndeterminate, loadCandidates: loadPlasticCandidates,
  loadGroups: loadPlasticGroups, search: searchPlasticCandidates,
  changePage: changePlasticPage, filterGroups: filterPlasticGroups,
  clearGroupFilter: clearPlasticGroupFilter, toggleCandidate: togglePlasticCandidate,
  toggleRow: togglePlasticRow, rowClass: plasticPickerRowClass,
  togglePage: togglePlasticPage, onClosed: resetPlasticPicker,
} = plasticPicker

const packagingPicker = useBomMaterialCandidates({
  label: '包材', fetchCandidates: fetchBomPackagingMaterials, fetchGroups: fetchBomPackagingMaterialGroups,
  mergeCandidates: (rows, query) => withPendingMaterials('packaging', rows, query.q || '', query.material_name || ''),
  errorMessage: apiError,
})
const {
  visible: packagingPickerVisible, loading: packagingPickerLoading,
  error: packagingPickerError, groupLoading: packagingGroupLoading,
  groupError: packagingGroupError,
  materialName: packagingPickerMaterialName, keyword: packagingPickerKeyword,
  page: packagingPickerPage, pageSize: packagingPickerPageSize,
  total: packagingPickerTotal, candidates: packagingCandidates,
  selected: selectedPackaging, visibleGroups: visiblePackagingGroups,
  selectedCount: selectedPackagingCount, pageAllSelected: packagingPageAllSelected,
  pageSelectionIndeterminate: packagingPageSelectionIndeterminate, loadCandidates: loadPackagingCandidates,
  loadGroups: loadPackagingGroups, search: searchPackagingCandidates,
  changePage: changePackagingPage, filterGroups: filterPackagingGroups,
  clearGroupFilter: clearPackagingGroupFilter, toggleCandidate: togglePackagingCandidate,
  toggleRow: togglePackagingRow, rowClass: packagingPickerRowClass,
  togglePage: togglePackagingPage, onClosed: resetPackagingPicker,
} = packagingPicker

const cuttingPicker = useBomMaterialCandidates({
  label: '裁剪', fetchCandidates: fetchBomSemiFinishedMaterials, fetchGroups: fetchBomSemiFinishedMaterialGroups,
  mergeCandidates: (rows, query) => withPendingMaterials('cutting', rows, query.q || '', query.material_name || ''),
  errorMessage: apiError,
})
const {
  visible: cuttingPickerVisible, loading: cuttingPickerLoading,
  error: cuttingPickerError, groupLoading: cuttingGroupLoading,
  groupError: cuttingGroupError,
  materialName: cuttingPickerMaterialName, keyword: cuttingPickerKeyword,
  page: cuttingPickerPage, pageSize: cuttingPickerPageSize,
  total: cuttingPickerTotal, candidates: cuttingCandidates,
  selected: selectedCutting, visibleGroups: visibleCuttingGroups,
  selectedCount: selectedCuttingCount, pageAllSelected: cuttingPageAllSelected,
  pageSelectionIndeterminate: cuttingPageSelectionIndeterminate, loadCandidates: loadCuttingCandidates,
  loadGroups: loadCuttingGroups, search: searchCuttingCandidates,
  changePage: changeCuttingPage, filterGroups: filterCuttingGroups,
  clearGroupFilter: clearCuttingGroupFilter, toggleCandidate: toggleCuttingCandidate,
  toggleRow: toggleCuttingRow, rowClass: cuttingPickerRowClass,
  togglePage: toggleCuttingPage, onClosed: resetCuttingPicker,
} = cuttingPicker

function resetHardwarePicker() {
  if (hardwarePickerVisible.value) return
  resetHardwarePickerState()
  hardwareCreateVisible.value = false
}

const uploadingCuttingImagesLineId = ref('')
const deletingCuttingImageId = ref('')
const cleaningCuttingDraftImages = ref(false)
const initialDrawerDraftImageIds = ref<string[]>([])
const preserveDrawerDraftImagesOnClose = ref(false)
const imageManagerVisible = ref(false)
const imageManagerStandalone = ref(false)
const imageManagerZIndex = ref(0)
const { nextZIndex } = useZIndex()

const canEdit = computed(() => authStore.hasPermission('boms.change_bom'))
const canCreateProduct = computed(() => Boolean(
  authStore.user?.is_superuser
  || (
    authStore.hasPermission('products.view_productinformation')
    && authStore.hasPermission('products.add_productinformation')
  )
))
const canCreateProductColor = computed(() => authStore.user?.is_superuser || authStore.hasPermission('reference_data.add_productcolor'))
const canSync = computed(() => authStore.moduleCan('access_control.sync_bomquantity', 'boms.change_bom'))
const canVerify = computed(() => authStore.hasPermission('boms.verify_bom') && bom.value?.status !== 'VERIFIED')
const canCreateHardwareRawMaterial = computed(() => (
  authStore.user?.is_superuser === true
  || (
    authStore.hasPermission('products.view_rawmaterialinformation')
    && authStore.hasPermission('products.add_rawmaterialinformation')
  )
))
const canCreateRawMaterial = canCreateHardwareRawMaterial
const canCreateAuxiliaryReference = computed(() => (
  authStore.user?.is_superuser === true
  || ['accessoryproductname', 'accessoryspecification', 'accessorycolor', 'accessorymaterial']
    .every((name) => authStore.hasPermission(`reference_data.add_${name}`))
))
const activeSection = computed(() => sections.value[activeSectionIndex.value] || null)
const editorStatusLabel = computed(() => bom.value?.status === 'VERIFIED' ? '已确认' : '草稿')
const sectionNavigationGroups = computed(() => {
  const definitions = [
    { label: '型材', titles: ['管材类'] },
    { label: '五金', titles: ['五金件'] },
    { label: '塑料', titles: ['塑料件类'] },
    { label: '面料', titles: ['面料类'] },
    { label: '裁剪明细', titles: ['裁剪明细'] },
    { label: '辅料', titles: ['辅料类'] },
    { label: '包材', titles: ['包材类'] },
  ]
  return definitions.map((definition) => {
    const indexes = sections.value.flatMap((section, index) => definition.titles.includes(section.title) ? [index] : [])
    return {
      ...definition,
      indexes,
      count: indexes.reduce((sum, index) => sum + (sections.value[index]?.lines.length || 0), 0),
    }
  })
})
const activeNavigationLabel = computed(() => (
  sectionNavigationGroups.value.find((group) => group.indexes.includes(activeSectionIndex.value))?.label || ''
))
const isHardwareSection = computed(() => activeSection.value?.title === '五金件')
const isPlasticSection = computed(() => activeSection.value?.title === '塑料件类')
const isAuxiliarySection = computed(() => activeSection.value?.title === '辅料类')
const isFabricSection = computed(() => activeSection.value?.title === '面料类')
const isPackagingSection = computed(() => activeSection.value?.title === '包材类')
const isCuttingSection = computed(() => activeSection.value?.title === '裁剪明细')
const activePersistedSection = computed(() => {
  if (!activeSection.value?.id) return null
  return bom.value?.sections.find((section) => section.id === activeSection.value?.id) || null
})
const activeSectionCanAddLine = computed(() => activeSection.value?.section_type === 'PROFILE')
const activeSectionCanChooseData = computed(() => (
  isHardwareSection.value
  || isPlasticSection.value
  || isAuxiliarySection.value
  || isFabricSection.value
  || isPackagingSection.value
  || isCuttingSection.value
))
const quantityMismatch = computed(() => bom.value?.quantity_requires_confirmation ?? false)
const quantityMismatchDetails = computed(() => {
  const currentBom = bom.value
  if (!currentBom) return []
  const baseline = currentBom.order_quantity
  const candidates = [
    { label: '当前订单最新产品数量', value: currentBom.current_order_quantity },
    { label: 'Excel 原表数量', value: currentBom.source_quantity },
    { label: '生产批次合计数量', value: currentBom.batch_quantity },
  ]
  return candidates.flatMap((item) => {
    if (item.value === null || item.value === undefined || decimalValuesEqual(item.value, baseline)) return []
    return [{
      label: item.label,
      value: number(item.value),
      difference: decimalDifferenceText(item.value, baseline),
    }]
  })
})
const quantityMismatchMessage = computed(() => {
  const currentBom = bom.value
  if (!currentBom || !quantityMismatchDetails.value.length) return '数量存在差异，请填写确认原因。'
  const details = quantityMismatchDetails.value
    .map((item) => `${item.label}为 ${item.value}，与本 BOM 保存的订单数量相差 ${item.difference}`)
    .join('；')
  return `本 BOM 保存的订单数量为 ${number(currentBom.order_quantity)}；${details}。请填写确认原因。`
})
const materialReferenceHint = computed(() => (
  isHardwareSection.value
    ? '品名、材质、颜色、规格和单位引用“原料信息 / 五金”，喷塑颜色引用“生产维护”'
    : isPlasticSection.value
      ? '品名、材质、颜色、规格和单位引用“原料信息 / 塑料件”'
      : isAuxiliarySection.value
        ? '品名、规格、颜色、材质和单位引用“系统设置 / 生产维护 / 辅料维护”'
        : isFabricSection.value
          ? '材质、规格以来源原材料为准；门幅和色卡引用“生产维护”'
          : isPackagingSection.value
            ? '品号、品名、材质、颜色、规格和单位引用“原料信息 / 包材”'
            : isCuttingSection.value
              ? '规格必填，不能使用“/”等占位符；填写每套裁片数和每成品套数，自动计算订单套数与片数'
              : '材质、规格以来源原材料为准；切割长度、单耗和每根切割支数填写整数'
))

const auxiliaryFilteredCandidates = computed(() => {
  const keyword = auxiliaryPickerKeyword.value.trim().toLocaleLowerCase('zh-CN')
  const products = (editorReferenceOptions.value?.auxiliary_products || []).filter((item) => (
    !auxiliaryPickerProductName.value || item.product_name === auxiliaryPickerProductName.value
  ))
  if (!keyword) return products
  return products.filter((item) => [
    item.product_name,
    item.pinyin_search,
    item.unit_name,
    ...item.specifications.map((option) => option.specification_value),
    ...item.colors.map((option) => option.color_name),
  ].some((value) => String(value || '').toLocaleLowerCase('zh-CN').includes(keyword)))
})
const auxiliaryPickerTotal = computed(() => auxiliaryFilteredCandidates.value.length)
const auxiliaryCandidates = computed(() => {
  const start = (auxiliaryPickerPage.value - 1) * auxiliaryPickerPageSize.value
  return auxiliaryFilteredCandidates.value.slice(start, start + auxiliaryPickerPageSize.value)
})
const selectedAuxiliaryProductCount = computed(() => Object.keys(selectedAuxiliaryProducts.value).length)
const auxiliaryPageSelectableCandidates = computed(() => (
  auxiliaryCandidates.value.filter((item) => auxiliaryProductIsSelectable(item))
))
const auxiliaryPageSelectedCount = computed(() => (
  auxiliaryPageSelectableCandidates.value.filter((item) => selectedAuxiliaryProducts.value[item.id]).length
))
const auxiliaryPageAllSelected = computed(() => (
  auxiliaryPageSelectableCandidates.value.length > 0
  && auxiliaryPageSelectedCount.value === auxiliaryPageSelectableCandidates.value.length
))
const auxiliaryPageSelectionIndeterminate = computed(() => (
  auxiliaryPageSelectedCount.value > 0 && !auxiliaryPageAllSelected.value
))
const editingSection = computed(() => sections.value[editingSectionIndex.value] || null)
function pipeMaterialAttributeKey(line: BomLineInput) {
  return JSON.stringify([line.material.trim(), line.tube_diameter.trim(), line.tube_thickness.trim(), line.tube_shape.trim()])
}

watch(() => [lineDrawerVisible.value, editingSection.value?.section_type, editingLineDraft.value,
  editingLineDraft.value?.tube_shape, editingLineDraft.value?.material, editingLineDraft.value?.tube_diameter,
  editingLineDraft.value?.tube_thickness], () => {
  const line = editingLineDraft.value
  if (!lineDrawerVisible.value || editingSection.value?.section_type !== 'PROFILE' || !line) return
  const original = editingSection.value.lines[editingLineIndex.value]
  if (original && pipeMaterialAttributeKey(original) !== pipeMaterialAttributeKey(line)) {
    // 参数改动后不再展示旧规格；保存 BOM 时由后端按当前参数同步原料关联。
    line.specification = ''
  }
})

const drawerHasNextLine = computed(() => (
  Boolean(editingSection.value)
  && editingLineIndex.value >= 0
  && editingLineIndex.value + 1 < (editingSection.value?.lines.length || 0)
))
const drawerNextActionLabel = computed(() => (
  drawerHasNextLine.value ? '保存编辑下一条' : '保存新增下一条'
))
const lineDrawerTitle = computed(() => {
  const sectionTitle = editingSection.value?.title || '用料明细'
  return `${sectionTitle} · 第 ${editingLineIndex.value + 1} 行`
})
const editingLineCalculations = computed(() => (
  editingLineDraft.value ? tubeCalculations(editingLineDraft.value) : null
))
const editingCuttingCalculation = computed(() => editingLineDraft.value ? cuttingQuantities(editingLineDraft.value) : null)

function cuttingQuantities(line: BomLineInput) {
  return cuttingCalculation(line, bom.value?.order_quantity)
}

function isPipeCuttingLine(line: BomLineInput | null | undefined) {
  if (!line) return false
  return `${line.category || ''} ${line.cutting_category || ''}`.includes('管材')
}

function syncCuttingValues(line: BomLineInput) {
  const values = cuttingCompatibilityValues(line, bom.value?.order_quantity)
  if (values) Object.assign(line, values)
  else if (cuttingQuantities(line).mode === 'legacy') {
    line.cutting_pieces_per_set = null
    line.cutting_sets_per_product = null
  }
}

function applyVersioned(result: { data: BomDetail; etag: string }) {
  bom.value = result.data
  if (!quantityReason.value && result.data.quantity_difference_reason) {
    quantityReason.value = result.data.quantity_difference_reason
  }
  etag.value = result.etag
  sections.value = withFixedSections(result.data.sections)
  pendingDeletedLineIds.value.clear()
  activeSectionIndex.value = Math.min(activeSectionIndex.value, Math.max(0, sections.value.length - 1))
}

const productConfirmItem = computed<InquiryItem>(() => ({
  product_id: bom.value?.product_master_id || null,
  product_category_id: bom.value?.product_category_id || null,
  product_unit_id: bom.value?.product_unit_id || null,
  product_color_id: bom.value?.product_color_id || null,
  product_description: bom.value?.product_name_snapshot || '',
  specification: bom.value?.specification_snapshot || '',
  color: bom.value?.product_color_snapshot || '',
  material: bom.value?.material_snapshot || '',
  unit_code: bom.value?.product_unit_code_snapshot || bom.value?.product_unit_name || '',
  quantity: bom.value?.order_quantity || '0',
  target_unit_price: null, target_currency_code: '', expected_date: null,
  product_match_status: bom.value?.product_master_id ? 'MATCHED' : 'PENDING', notes: '',
  product_number_snapshot: bom.value?.product_number_snapshot || '',
  product_code_snapshot: bom.value?.product_code_snapshot || '',
  item_number_snapshot: bom.value?.item_number_snapshot || '',
}))

async function loadProductConfirmCatalog() {
  if (productConfirmCatalogLoading.value) return
  productConfirmCatalogLoading.value = true
  productConfirmCatalogError.value = ''
  const results = await Promise.allSettled([
    fetchProductOptions(),
    fetchAllProductionDataRecords<ProductColor>('product-colors'),
  ])
  const messages: string[] = []
  if (results[0].status === 'fulfilled') productConfirmOptions.value = results[0].value
  else messages.push(apiError(results[0].reason, '产品类别和单位加载失败，请点击重试基础资料。'))
  if (results[1].status === 'fulfilled') productConfirmColors.value = results[1].value
  else messages.push(apiError(results[1].reason, '颜色维护加载失败，请点击重试基础资料。'))
  productConfirmCatalogError.value = messages.join(' ')
  productConfirmCatalogLoading.value = false
}

function openProductConfirmDialog() {
  if (!bom.value) return
  if (!canEdit.value) { productInfoVisible.value = true; return }
  productConfirmError.value = ''
  productConfirmVisible.value = true
  void loadProductConfirmCatalog()
}

function prepareConfirmedProductCreate(item: InquiryItem) {
  productCreateReviewDraft.value = { ...item }
  productCreateInitial.value = {
    category: item.product_category_id || '', product_name: item.product_description,
    specification: item.specification, unit: item.product_unit_id || '',
    product_number: item.product_number_snapshot || '', product_code: item.product_code_snapshot || '',
  }
  productCreateUnitCode.value = item.unit_code
  productCreateItemNumber.value = item.item_number_snapshot || ''
  productConfirmCreateVisible.value = true
}

async function createProductForBom(input: ProductInformationInput): Promise<ProductInformation> {
  const item = productCreateReviewDraft.value
  if (!bom.value || !item?.product_color_id) throw new Error('请先选择系统维护中的颜色，再确认产品建档。')
  productConfirmLoading.value = true
  try {
    const result = await confirmBomProduct(bom.value.id, {
      new_product: input, product_color_id: item.product_color_id,
      color_code: productConfirmColors.value.find(color => color.id === item.product_color_id)?.color_code || '',
      material: item.material,
    }, etag.value)
    if (!result.data.product_information_confirmed) throw new Error('服务器尚未确认产品信息，请重试。')
    // 与已有产品核对保持一致，不重置物料草稿和待删除图片/行。
    bom.value = result.data
    etag.value = result.etag
    if (!result.data.product_information) throw new Error('产品核对已保存，但返回的产品资料不完整，请重新打开当前 BOM 核实。')
    return result.data.product_information
  } finally {
    productConfirmLoading.value = false
  }
}

function handleConfirmedProductCreated() {
  productConfirmCreateVisible.value = false
  productConfirmVisible.value = false
  productConfirmError.value = ''
  selectEditorTab('materials')
}

function openConfirmedColorCreate(name: string) {
  productColorDraft.value = { color_card: '', color_code: '', color_name: name }
  productConfirmColorCreateVisible.value = true
}

async function createConfirmedColor() {
  const draft = productColorDraft.value
  if (!draft.color_card.trim() || !draft.color_code.trim() || !draft.color_name.trim()) {
    ElMessage.warning('请填写色卡、色号和颜色名称。')
    return
  }
  if (productConfirmLoading.value) return
  productConfirmLoading.value = true
  try {
    const result = await createProductionDataRecord<ProductColor>('product-colors', {
      color_card: draft.color_card.trim(), color_code: draft.color_code.trim(), color_name: draft.color_name.trim(),
      status: 'ACTIVE', sort_order: 0, description: '',
    })
    productConfirmColors.value = [...productConfirmColors.value.filter(color => color.id !== result.data.id), result.data]
    productConfirmDialog.value?.applyCreatedColor(result.data)
    productConfirmColorCreateVisible.value = false
    productColorDraft.value = { color_card: '', color_code: '', color_name: '' }
    ElMessage.success('颜色已新增并选入本次核对。')
  } catch (error) {
    ElMessage.error(apiError(error, '颜色新增失败，请检查权限和重复数据。'))
  } finally {
    productConfirmLoading.value = false
  }
}

async function confirmProductInformation({ item }: { item: InquiryItem }) {
  if (!bom.value || !item.product_id || !item.product_color_id || productConfirmLoading.value) return
  productConfirmLoading.value = true
  productConfirmError.value = ''
  try {
    const result = await confirmBomProduct(
      bom.value.id,
      {
        product_id: item.product_id, product_color_id: item.product_color_id,
        color_code: productConfirmColors.value.find(color => color.id === item.product_color_id)?.color_code || bom.value.product_color_code_snapshot || '',
        material: item.material,
      },
      etag.value,
    )
    if (!result.data.product_information_confirmed) throw new Error('服务器尚未确认产品信息，请重试。')
    // 产品核对独立保存：不调用 applyVersioned，避免服务器旧物料覆盖尚未保存的编辑内容。
    bom.value = result.data
    etag.value = result.etag
    productConfirmVisible.value = false
    selectEditorTab('materials')
    ElMessage.success(result.data.status === 'VERIFIED' ? '当前 BOM 产品信息已更新，未重复回写上游。' : '产品信息已核对；确认 BOM 时再按首次规则回写上游。')
  } catch (error) {
    productConfirmError.value = apiError(error, '产品信息确认失败，当前填写内容已保留，请重试。')
  } finally {
    productConfirmLoading.value = false
  }
}

async function loadTubeOptions() {
  tubeOptionsLoading.value = true
  try {
    const [shapes, productNames, materials, diameters, thicknesses, coatingColors] = await Promise.all([
      fetchAllProductionDataRecords<TubeShape>('tube-shapes'),
      fetchAllProductionDataRecords<TubeProductName>('tube-product-names'),
      fetchAllProductionDataRecords<TubeMaterial>('tube-materials'),
      fetchAllProductionDataRecords<TubeDiameter>('tube-diameters'),
      fetchAllProductionDataRecords<TubeThickness>('tube-thicknesses'),
      fetchAllProductionDataRecords<TubeCoatingColor>('tube-coating-colors'),
    ])
    tubeShapes.value = shapes
    tubeProductNames.value = productNames
    tubeMaterials.value = materials
    tubeDiameters.value = diameters
    tubeThicknesses.value = thicknesses
    tubeCoatingColors.value = coatingColors
  } catch {
    ElMessage.warning('管材维护数据加载失败，请检查后端服务后刷新页面。')
  } finally {
    tubeOptionsLoading.value = false
  }
}

function formatHardwareColor(value: string) {
  if (!value || value === '/') return '无颜色（/）'
  return value
}

function openHardwarePicker() {
  if (!canEdit.value || !isHardwareSection.value) return
  void hardwarePicker.open()
}

function hardwareLine(item: BomHardwareMaterial): BomLineInput {
  return {
    ...blankLine(item.unit_name || item.unit_code),
    ...pendingLineValues(item),
    category: '五金',
    part_name: item.material_name,
    material: item.material,
    specification: item.specification,
    raw_material: item.material_number,
    source_raw_material_id: pendingRawMaterials.value[item.id] ? null : item.id,
    hardware_material_number: item.material_number,
    hardware_color: item.color_name,
    hardware_flow_unit: item.flow_unit,
    unit_material_weight_kg: item.weight_kg,
  }
}

function openHardwareCreate() {
  if (!canCreateHardwareRawMaterial.value) {
    ElMessage.warning('需要“查看原料信息”和“新增原料信息”权限。')
    return
  }
  hardwareCreateVisible.value = true
}

async function stageRawMaterial(target: RawMaterialTarget, payload: RawMaterialInput, display: Pick<RawMaterialInformation, 'category_name' | 'unit_name' | 'unit_code' | 'color_name'>) {
  const candidate: BomHardwareMaterial = {
    id: createDraftKey(), material_number: payload.material_number, item_type: payload.item_type,
    item_type_display: payload.item_type === 'SEMI_FINISHED' ? '半成品' : '材料',
    material_name: payload.material_name, material: payload.material, specification: payload.specification,
    weight_kg: '', flow_unit: '', number_value: '', ...display,
  }
  pendingRawMaterials.value[candidate.id] = { target, payload: { ...payload }, candidate }
  if (target === 'hardware') {
    selectedHardware.value[candidate.id] = candidate
    hardwarePickerMaterialName.value = ''; hardwarePickerKeyword.value = ''; hardwarePickerPage.value = 1
    await loadHardwareCandidates()
  } else if (target === 'plastic') {
    selectedPlastic.value[candidate.id] = candidate
    plasticPickerMaterialName.value = ''; plasticPickerKeyword.value = ''; plasticPickerPage.value = 1
    await loadPlasticCandidates()
  } else if (target === 'packaging') {
    selectedPackaging.value[candidate.id] = candidate
    packagingPickerMaterialName.value = ''; packagingPickerKeyword.value = ''; packagingPickerPage.value = 1
    await loadPackagingCandidates()
  } else {
    selectedCutting.value[candidate.id] = candidate
    cuttingPickerMaterialName.value = ''; cuttingPickerKeyword.value = ''; cuttingPickerPage.value = 1
    await loadCuttingCandidates()
  }
  ElMessage.success('资料已暂存并选中，保存 BOM 时统一确认新增。')
}

function openRawMaterialCreate(target: 'plastic' | 'packaging' | 'cutting') {
  if (!canCreateRawMaterial.value) {
    ElMessage.warning('需要“查看原料信息”和“新增原料信息”权限。')
    return
  }
  if (target === 'plastic') plasticCreateVisible.value = true
  if (target === 'packaging') packagingCreateVisible.value = true
  if (target === 'cutting') cuttingCreateVisible.value = true
}

function appendMaterialSelection(
  picker: ReturnType<typeof useBomMaterialCandidates>,
  targetSection: BomSectionInput,
  sourceField: 'source_raw_material_id' | 'source_packaging_material_id' | 'source_cutting_material_id',
  mapLine: (item: BomHardwareMaterial) => BomLineInput,
) {
  const chosen = Object.values(picker.selected.value)
  if (!chosen.length) {
    ElMessage.warning(`请至少选择一条${picker.label}数据。`)
    return
  }
  const existingSourceIds = new Set(targetSection.lines.map(line => line.pending_raw_material ? line.client_key : line[sourceField]).filter(Boolean))
  const newLines = chosen.filter(item => !existingSourceIds.has(item.id)).map(mapLine)
  if (!newLines.length) {
    ElMessage.info(`所选${picker.label}数据已在当前分区中。`)
    return
  }
  targetSection.lines.push(...newLines)
  picker.visible.value = false
  return { newLines, skippedCount: chosen.length - newLines.length }
}

function confirmHardwareSelection() {
  const targetSection = activeSection.value
  if (!targetSection || targetSection.title !== '五金件') {
    ElMessage.error('当前五金件分区已变化，请关闭选择窗口后重试。')
    return
  }
  const selection = appendMaterialSelection(hardwarePicker, targetSection, 'source_raw_material_id', hardwareLine)
  if (!selection) return
  const { newLines, skippedCount } = selection

  ElMessage.success(`已添加 ${newLines.length} 条五金数据${skippedCount ? `，跳过 ${skippedCount} 条重复数据` : ''}。`)
}

function openPlasticPicker() {
  if (!canEdit.value || !isPlasticSection.value) return
  void plasticPicker.open()
}

function plasticLine(item: BomPlasticMaterial): BomLineInput {
  return {
    ...blankLine(item.unit_name || item.unit_code),
    ...pendingLineValues(item),
    category: '塑料件',
    part_name: item.material_name,
    material: item.material,
    specification: item.specification,
    raw_material: item.material_number,
    source_raw_material_id: pendingRawMaterials.value[item.id] ? null : item.id,
    plastic_material_number: item.material_number,
    plastic_color: item.color_name,
  }
}

function confirmPlasticSelection() {
  const targetSection = activeSection.value
  if (!targetSection || targetSection.title !== '塑料件类') {
    ElMessage.error('当前塑料件分区已变化，请关闭选择窗口后重试。')
    return
  }
  const selection = appendMaterialSelection(plasticPicker, targetSection, 'source_raw_material_id', plasticLine)
  if (!selection) return
  const { newLines, skippedCount } = selection

  ElMessage.success(`已添加 ${newLines.length} 条塑料件数据${skippedCount ? `，跳过 ${skippedCount} 条重复数据` : ''}。`)
}

function openPackagingPicker() {
  if (!canEdit.value || !isPackagingSection.value) return
  void packagingPicker.open()
}

function packagingLine(item: BomPackagingMaterial): BomLineInput {
  return {
    ...blankLine(item.unit_name || item.unit_code),
    ...pendingLineValues(item),
    category: '包材',
    part_name: item.material_name,
    material: item.material,
    specification: item.specification,
    raw_material: item.material_number,
    source_packaging_material_id: pendingRawMaterials.value[item.id] ? null : item.id,
    packaging_material_number: item.material_number,
    packaging_color: item.color_name,
    units_per_box: '',
  }
}

function confirmPackagingSelection() {
  const targetSection = activeSection.value
  if (!targetSection || targetSection.title !== '包材类') {
    ElMessage.error('当前包材分区已变化，请关闭选择窗口后重试。')
    return
  }
  const selection = appendMaterialSelection(packagingPicker, targetSection, 'source_packaging_material_id', packagingLine)
  if (!selection) return
  const { newLines, skippedCount } = selection

  ElMessage.success(`已添加 ${newLines.length} 条包材数据${skippedCount ? `，跳过 ${skippedCount} 条重复数据` : ''}，请填写箱数和单个用量。`)
}

function openCuttingPicker() {
  if (!canEdit.value || !isCuttingSection.value) return
  void cuttingPicker.open()
}

function cuttingLine(item: BomSemiFinishedMaterial): BomLineInput {
  return {
    ...blankLine('套'),
    ...pendingLineValues(item),
    cutting_pieces_per_set: null,
    fabric_meters_per_piece: null,
    cutting_sets_per_product: 1,
    category: item.category_name,
    part_name: item.material_name,
    material: item.material,
    specification: item.specification,
    raw_material: item.material_number,
    source_cutting_material_id: pendingRawMaterials.value[item.id] ? null : item.id,
    cutting_material_number: item.material_number,
    cutting_item_type: item.item_type,
    cutting_item_type_display: item.item_type_display,
    cutting_category: item.category_name,
    cutting_color: item.color_name,
    draft_key: createDraftKey(),
    draft_images: [],
  }
}

function confirmCuttingSelection() {
  const targetSection = activeSection.value
  if (!targetSection || targetSection.title !== '裁剪明细') {
    ElMessage.error('当前裁剪分区已变化，请关闭选择窗口后重试。')
    return
  }
  const selection = appendMaterialSelection(cuttingPicker, targetSection, 'source_cutting_material_id', cuttingLine)
  if (!selection) return
  const { newLines, skippedCount } = selection
  // 新增裁剪行立即打开编辑窗口，先补齐来源面料、每套片数和每成品套数。
  openLineDrawer(targetSection.lines.length - newLines.length)

  ElMessage.success(`已添加 ${newLines.length} 条裁剪数据，请补齐参数后保存 BOM${skippedCount ? `；跳过 ${skippedCount} 条重复数据` : ''}。`)
}

async function ensureEditorReferenceOptions() {
  if (editorReferenceOptions.value) return editorReferenceOptions.value
  if (editorReferenceOptionsPromise) return editorReferenceOptionsPromise
  editorReferenceOptionsLoading.value = true
  editorReferenceOptionsError.value = ''
  editorReferenceOptionsPromise = fetchBomEditorReferenceOptions()
    .then((options) => {
      editorReferenceOptions.value = options
      return options
    })
    .catch((error) => {
      editorReferenceOptionsError.value = apiError(error, '生产维护选项加载失败，请稍后重试。')
      ElMessage.error(editorReferenceOptionsError.value)
      return null
    })
    .finally(() => {
      editorReferenceOptionsLoading.value = false
      editorReferenceOptionsPromise = null
    })
  return editorReferenceOptionsPromise
}

function auxiliaryProductIsSelectable(item: BomAuxiliaryProductOption) {
  return item.specifications.length > 0 && item.colors.length > 0
}

function auxiliaryProductMaintenanceTip(item: BomAuxiliaryProductOption) {
  const missing: string[] = []
  if (!item.specifications.length) missing.push('规格')
  if (!item.colors.length) missing.push('颜色')
  if (!item.unit_name.trim()) missing.push('单位')
  if (!missing.length) return '可选择'
  if (missing.length === 1) return `待维护${missing[0]}`
  return `待维护${missing.slice(0, -1).join('、')}和${missing.at(-1)}`
}

function auxiliarySpecificationSummary(item: BomAuxiliaryProductOption) {
  return item.specifications.map((option) => option.specification_value).join('、') || '待维护'
}

function auxiliaryColorSummary(item: BomAuxiliaryProductOption) {
  return item.colors.map((option) => option.color_name).join('、') || '待维护'
}

function openAuxiliaryPicker() {
  if (!canEdit.value || !isAuxiliarySection.value) return
  auxiliaryPickerKeyword.value = ''
  auxiliaryPickerProductName.value = ''
  auxiliaryPickerPage.value = 1
  selectedAuxiliaryProducts.value = {}
  auxiliaryPickerVisible.value = true
  void ensureEditorReferenceOptions()
}

function openAuxiliaryCreate() {
  if (!canCreateAuxiliaryReference.value) {
    ElMessage.warning('需要辅料品名、规格、颜色和材质的新增权限。')
    return
  }
  auxiliaryCreateVisible.value = true
}

async function handleAuxiliaryCreated(item: BomAuxiliaryProductOption) {
  editorReferenceOptions.value = null
  const options = await ensureEditorReferenceOptions()
  const created = options?.auxiliary_products.find((option) => option.id === item.id) || item
  if (created) {
    selectedAuxiliaryProducts.value = { ...selectedAuxiliaryProducts.value, [created.id]: created }
    auxiliaryPickerProductName.value = created.id
  }
  ElMessage.success('辅料资料已新增并选中。')
}

function searchAuxiliaryCandidates() {
  auxiliaryPickerPage.value = 1
}

function changeAuxiliaryPage(page: number) {
  auxiliaryPickerPage.value = page
}

function toggleAuxiliaryCandidate(item: BomAuxiliaryProductOption, selected: boolean | string | number) {
  if (!auxiliaryProductIsSelectable(item)) return
  const next = { ...selectedAuxiliaryProducts.value }
  if (Boolean(selected)) next[item.id] = item
  else delete next[item.id]
  selectedAuxiliaryProducts.value = next
}

function toggleAuxiliaryRow(item: BomAuxiliaryProductOption) {
  if (!auxiliaryProductIsSelectable(item)) return
  toggleAuxiliaryCandidate(item, !selectedAuxiliaryProducts.value[item.id])
}

function auxiliaryPickerRowClass({ row }: { row: BomAuxiliaryProductOption }) {
  if (!auxiliaryProductIsSelectable(row)) return 'is-picker-disabled'
  return selectedAuxiliaryProducts.value[row.id] ? 'is-picker-selected' : ''
}

function toggleAuxiliaryPage(selected: boolean | string | number) {
  const next = { ...selectedAuxiliaryProducts.value }
  for (const item of auxiliaryPageSelectableCandidates.value) {
    if (Boolean(selected)) next[item.id] = item
    else delete next[item.id]
  }
  selectedAuxiliaryProducts.value = next
}

function auxiliaryLine(item: BomAuxiliaryProductOption): BomLineInput {
  const line: BomLineInput = {
    ...blankLine(item.unit_name),
    category: '辅料',
    part_name: item.product_name,
    source_accessory_product_name_id: item.id,
  }
  if (item.specifications.length === 1) setAuxiliarySpecification(line, item.specifications[0]?.id)
  if (item.colors.length === 1) setAuxiliaryColor(line, item.colors[0]?.id)
  const materials = editorReferenceOptions.value?.accessory_materials || []
  if (materials.length === 1) setAuxiliaryMaterial(line, materials[0]?.id)
  return line
}

function confirmAuxiliarySelection() {
  const targetSection = activeSection.value
  if (!targetSection || targetSection.title !== '辅料类') {
    ElMessage.error('当前辅料分区已变化，请关闭选择窗口后重试。')
    return
  }
  const chosen = Object.values(selectedAuxiliaryProducts.value)
  if (!chosen.length) {
    ElMessage.warning('请至少选择一条辅料数据。')
    return
  }
  targetSection.lines.push(...chosen.map(auxiliaryLine))
  auxiliaryPickerVisible.value = false
  const missingUnitCount = chosen.filter((item) => !item.unit_name.trim()).length
  if (missingUnitCount) {
    ElMessage.warning(`已添加 ${chosen.length} 条辅料数据，其中 ${missingUnitCount} 条单位待维护；单一候选已自动带入，其余项请继续选择。`)
  } else {
    ElMessage.success(`已添加 ${chosen.length} 条辅料数据；单一候选已自动带入，其余项请继续选择。`)
  }
}

function resetAuxiliaryPicker() {
  auxiliaryPickerKeyword.value = ''
  auxiliaryPickerProductName.value = ''
  auxiliaryPickerPage.value = 1
  selectedAuxiliaryProducts.value = {}
}

function auxiliaryProductForLine(line: BomLineInput) {
  return editorReferenceOptions.value?.auxiliary_products.find(
    (item) => item.id === line.source_accessory_product_name_id,
  )
}

interface EditorSelectOption {
  id: string
  label: string
  disabled?: boolean
}

function optionsWithDisabledSnapshot(
  options: EditorSelectOption[],
  sourceId: string | null,
  snapshot: string,
  fallbackLabel: string,
) {
  if (!sourceId || options.some((item) => item.id === sourceId)) return options
  return [{ id: sourceId, label: snapshot.trim() || fallbackLabel, disabled: true }, ...options]
}

function auxiliaryLineHasActiveProduct(line: BomLineInput) {
  return Boolean(auxiliaryProductForLine(line))
}

function auxiliarySpecifications(line: BomLineInput) {
  return auxiliaryProductForLine(line)?.specifications || []
}

function auxiliarySpecificationOptions(line: BomLineInput) {
  return optionsWithDisabledSnapshot(
    auxiliarySpecifications(line).map((item) => ({ id: item.id, label: item.specification_value })),
    line.source_accessory_specification_id,
    line.specification,
    '已停用规格',
  )
}

function auxiliaryColors(line: BomLineInput) {
  return auxiliaryProductForLine(line)?.colors || []
}

function auxiliaryColorOptions(line: BomLineInput) {
  return optionsWithDisabledSnapshot(
    auxiliaryColors(line).map((item) => ({ id: item.id, label: item.color_name })),
    line.source_accessory_color_id,
    line.accessory_color,
    '已停用颜色',
  )
}

function auxiliaryMaterialOptions(line: BomLineInput) {
  return optionsWithDisabledSnapshot(
    (editorReferenceOptions.value?.accessory_materials || []).map((item) => ({ id: item.id, label: item.material_name })),
    line.source_accessory_material_id,
    line.material,
    '已停用材质',
  )
}

function setAuxiliarySpecification(line: BomLineInput, value: string | null | undefined) {
  const option = auxiliarySpecifications(line).find((item) => item.id === value)
  line.source_accessory_specification_id = option?.id || null
  line.specification = option?.specification_value || ''
}

function setAuxiliaryColor(line: BomLineInput, value: string | null | undefined) {
  const option = auxiliaryColors(line).find((item) => item.id === value)
  line.source_accessory_color_id = option?.id || null
  line.accessory_color = option?.color_name || ''
}

function setAuxiliaryMaterial(line: BomLineInput, value: string | null | undefined) {
  const option = editorReferenceOptions.value?.accessory_materials.find((item) => item.id === value)
  line.source_accessory_material_id = option?.id || null
  line.material = option?.material_name || ''
}

async function addFabricLine() {
  if (!canEdit.value || !isFabricSection.value) return
  if (!(await ensureEditorReferenceOptions())) return
  const targetSection = activeSection.value
  if (!targetSection || targetSection.title !== '面料类') {
    ElMessage.error('当前面料分区已变化，请重新点击“添加面料”。')
    return
  }
  targetSection.lines.push({ ...blankLine('米'), category: '面料', unit: '米' })
}

function fabricSpecificationOptions(line: BomLineInput) {
  return optionsWithDisabledSnapshot(
    (editorReferenceOptions.value?.fabric_specifications || []).map((item) => ({ id: item.id, label: item.specification_name })),
    line.source_fabric_specification_id,
    line.specification,
    '已停用规格',
  )
}

function fabricMaterialOptions(line: BomLineInput) {
  return optionsWithDisabledSnapshot(
    (editorReferenceOptions.value?.fabric_materials || []).map((item) => ({ id: item.id, label: item.material_name })),
    line.source_fabric_material_id,
    line.material,
    '已停用材质',
  )
}

function fabricWidthOptions(line: BomLineInput) {
  return optionsWithDisabledSnapshot(
    (editorReferenceOptions.value?.fabric_widths || []).map((item) => ({ id: item.id, label: item.width_value })),
    line.source_fabric_width_id,
    line.fabric_width,
    '已停用门幅',
  )
}

function fabricColorSnapshot(line: BomLineInput) {
  return [line.fabric_color_card, line.fabric_color_name, line.fabric_color_code].filter(Boolean).join(' / ')
}

function fabricColorOptions(line: BomLineInput) {
  return optionsWithDisabledSnapshot(
    (editorReferenceOptions.value?.product_colors || []).map((item) => ({ id: item.id, label: formatProductColor(item) })),
    line.source_product_color_id,
    fabricColorSnapshot(line),
    '已停用色卡资料',
  )
}

function setFabricSpecification(line: BomLineInput, value: string | null | undefined) {
  const option = editorReferenceOptions.value?.fabric_specifications.find((item) => item.id === value)
  line.source_fabric_specification_id = option?.id || null
  line.specification = option?.specification_name || ''
}

function setFabricMaterial(line: BomLineInput, value: string | null | undefined) {
  const option = editorReferenceOptions.value?.fabric_materials.find((item) => item.id === value)
  line.source_fabric_material_id = option?.id || null
  line.material = option?.material_name || ''
}

function setFabricWidth(line: BomLineInput, value: string | null | undefined) {
  const option = editorReferenceOptions.value?.fabric_widths.find((item) => item.id === value)
  line.source_fabric_width_id = option?.id || null
  line.fabric_width = option?.width_value || ''
}

function formatProductColor(item: BomProductColorOption) {
  return [item.color_card, item.color_name, item.color_code].filter(Boolean).join(' / ')
}

function setFabricColor(line: BomLineInput, value: string | null | undefined) {
  const option = editorReferenceOptions.value?.product_colors.find((item) => item.id === value)
  line.source_product_color_id = option?.id || null
  line.fabric_color_card = option?.color_card || ''
  line.fabric_color_code = option?.color_code || ''
  line.fabric_color_name = option?.color_name || ''
}

function apiError(error: unknown, fallback = 'BOM 请求失败，请稍后重试。') {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务。'
  if (error.response.status === 412) return '该 BOM 已被其他人修改，请刷新后再编辑。'
  if (error.response.status === 428) return '当前页面缺少版本信息，请刷新后重试。'
  if (error.response.status === 403) return '当前账号没有执行此操作的权限。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  return data.error?.message || data.detail || fallback
}

function isTemporaryBomLoadError(error: unknown) {
  if (!(error instanceof AxiosError)) return false
  if (!error.response) return true
  return [500, 502, 503, 504].includes(error.response.status)
}

function waitBeforeBomReload(attempt: number, signal: AbortSignal) {
  if (signal.aborted) return Promise.resolve(false)
  return new Promise<boolean>((resolve) => {
    const retryDelays = [0, 750, 1500, 2500]
    const cancel = () => {
      window.clearTimeout(timer)
      resolve(false)
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener('abort', cancel)
      resolve(true)
    }, retryDelays[attempt] ?? 2500)
    signal.addEventListener('abort', cancel, { once: true })
  })
}

async function fetchBomForEditWithRetry(bomId: string, signal: AbortSignal) {
  const maximumAttempts = 4
  for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
    if (signal.aborted) return
    try {
      return await fetchBomForEdit(bomId, signal)
    } catch (error) {
      if (signal.aborted) return
      if (!isTemporaryBomLoadError(error) || attempt === maximumAttempts) throw error
      if (!await waitBeforeBomReload(attempt, signal)) return
    }
  }
  throw new Error('BOM 加载重试失败。')
}

async function loadBom() {
  if (disposed) return
  const generation = ++bomLoadGeneration
  bomLoadController?.abort()
  const controller = new AbortController()
  bomLoadController = controller
  syncingQuantity.value = false
  productConfirmVisible.value = false
  productInfoVisible.value = false
  const bomId = String(route.params.bomId || '')
  const isCurrentLoad = () => !disposed && generation === bomLoadGeneration && bomId === String(route.params.bomId || '')
  if (!bomId) {
    errorMessage.value = '缺少 BOM 编号。'
    loading.value = false
    return
  }
  loading.value = true
  errorMessage.value = ''
  let shouldPromptQuantitySync = false
  try {
    const result = await fetchBomForEditWithRetry(bomId, controller.signal)
    // 取消请求不保证响应尚未到达，仍需拦住旧加载结果及其确认弹窗。
    if (!result || !isCurrentLoad()) return
    applyVersioned(result)
    shouldPromptQuantitySync = result.data.is_order_quantity_outdated || result.data.is_order_product_outdated
  } catch (error) {
    if (isCurrentLoad()) errorMessage.value = apiError(error)
    return
  } finally {
    if (isCurrentLoad()) loading.value = false
  }
  if (!isCurrentLoad()) return
  if (bom.value && !bom.value.product_information_confirmed) openProductConfirmDialog()
  if (shouldPromptQuantitySync) void requestOrderQuantitySync(true)
}

async function requestOrderQuantitySync(automatic = false) {
  const currentBom = bom.value
  if (!(currentBom?.is_order_quantity_outdated || currentBom?.is_order_product_outdated) || !canEdit.value || syncingQuantity.value) return
  const generation = bomLoadGeneration
  const currentEtag = etag.value
  const isCurrentSync = () => !disposed && generation === bomLoadGeneration && currentBom.id === String(route.params.bomId || '')
  if (!isCurrentSync()) return
  if (automatic) {
    if (automaticallyPromptedBomId.value === currentBom.id) return
    automaticallyPromptedBomId.value = currentBom.id
  }
  const versionNotice = currentBom.status === 'VERIFIED'
    ? '该 BOM 已提交；同步订单信息时会保留当前版本，并生成一个待提交的新版本。'
    : '同步后会更新产品与数量快照，管材表中的数量计算会按最新订单数量重新计算。'
  const changeSummary = currentBom.is_order_product_outdated
    ? `生产任务中的产品已由“${currentBom.product_name_snapshot}”变更，请同步后人工复核原材料明细。`
    : `生产任务订单数量已由 ${number(currentBom.order_quantity)} 变为 ${number(currentBom.current_order_quantity)}。`
  try {
    await ElMessageBox.confirm(
      `${changeSummary}${versionNotice}`,
      '订单信息不一致，是否同步？',
      {
        type: 'warning',
        confirmButtonText: '同步订单信息',
        cancelButtonText: '暂不同步',
        closeOnClickModal: false,
      },
    )
  } catch {
    return
  }

  if (!isCurrentSync()) return
  syncingQuantity.value = true
  try {
    const result = await syncBomOrderQuantity(currentBom.id, currentEtag)
    if (!isCurrentSync()) return
    const targetBomId = result.data.id
    applyVersioned(result)
    quantityReason.value = ''
    ElMessage.success('订单信息已同步，BOM 用量已按最新数量重新计算。')
    if (targetBomId !== String(route.params.bomId || '')) {
      await router.replace({ name: 'bom-edit', params: { bomId: targetBomId } })
    }
  } catch (error) {
    if (isCurrentSync()) ElMessage.error(apiError(error))
  } finally {
    if (isCurrentSync()) syncingQuantity.value = false
  }
}

function addLine() {
  if (!canEdit.value || !activeSection.value || !activeSectionCanAddLine.value) return
  activeSection.value?.lines.push(blankLine(activeSection.value?.section_type === 'PROFILE' ? '根' : ''))
  selectedLineIndex.value = Math.max(0, (activeSection.value?.lines.length || 1) - 1)
  openLineDrawer(selectedLineIndex.value)
}

function selectSection(index: number) {
  tableFullscreen.value = false
  activeSectionIndex.value = index
  selectedLineIndex.value = 0
  const selectedTitle = sections.value[index]?.title
  if (selectedTitle === '辅料类' || selectedTitle === '面料类') void ensureEditorReferenceOptions()
}

function selectNavigationGroup(indexes: number[]) {
  const targetIndex = indexes.includes(activeSectionIndex.value) ? activeSectionIndex.value : indexes[0]
  if (targetIndex !== undefined) selectSection(targetIndex)
}

function toggleTableFullscreen() {
  tableFullscreen.value = !tableFullscreen.value
}

function closeTableFullscreen(event: KeyboardEvent) {
  if (event.key === 'Escape' && !lineDrawerVisible.value) tableFullscreen.value = false
}

function normalizeTubeCutPieceCount(line: BomLineInput) {
  line.tube_cut_piece_count = String(line.tube_cut_piece_count || '').trim()
}

type CuttingDisplayImage = BomLineImage | BomDraftLineImage

function displayLineImages(line: BomLineInput): CuttingDisplayImage[] {
  return [...(line.images || []), ...(line.draft_images || [])]
}

function isDraftLineImage(image: CuttingDisplayImage): image is BomDraftLineImage {
  return 'draft_key' in image
}

function replaceLineImages(lineId: string, images: BomLineImage[]) {
  for (const section of sections.value) {
    const line = section.lines.find((item) => item.id === lineId)
    if (line) line.images = [...images]
  }
  if (editingLineDraft.value?.id === lineId) editingLineDraft.value.images = [...images]
}

function replaceDraftLineImages(draftKey: string, images: BomDraftLineImage[]) {
  for (const section of sections.value) {
    const line = section.lines.find((item) => item.draft_key === draftKey)
    if (line) line.draft_images = [...images]
  }
  if (editingLineDraft.value?.draft_key === draftKey) editingLineDraft.value.draft_images = [...images]
}

function prepareEditingLine(index: number) {
  const line = activeSection.value?.lines[index]
  if (!line) {
    ElMessage.error('未找到需要操作的用料明细，请刷新页面后重试。')
    return false
  }
  editingSectionIndex.value = activeSectionIndex.value
  editingLineIndex.value = index
  editingLineDraft.value = {
    ...line,
    images: [...(line.images || [])],
    draft_images: [...(line.draft_images || [])],
  }
  return true
}

function openLineImageManager(index?: number) {
  if (typeof index === 'number') {
    if (!canEdit.value || !prepareEditingLine(index)) return
    imageManagerStandalone.value = true
  } else if (!editingLineDraft.value) {
    ElMessage.error('未找到需要操作的用料明细，请重新打开编辑弹出层。')
    return
  } else {
    imageManagerStandalone.value = false
  }
  imageManagerZIndex.value = nextZIndex()
  imageManagerVisible.value = true
}

function imageManagerIsBusy() {
  return Boolean(uploadingCuttingImagesLineId.value || deletingCuttingImageId.value || cleaningCuttingDraftImages.value)
}

function beforeImageManagerClose(done: () => void) {
  if (imageManagerIsBusy()) {
    ElMessage.warning('图片正在处理，请完成后再关闭。')
    return
  }
  done()
}

function closeImageManager() {
  if (imageManagerIsBusy()) {
    ElMessage.warning('图片正在处理，请完成后再关闭。')
    return
  }
  imageManagerVisible.value = false
}

function openImageFilePicker() {
  // 文件选择器由 BomLineImageManager 内部触发；保留事件入口兼容旧逻辑。
}

function resetImageManager() {
  if (imageManagerStandalone.value) resetLineDrawer()
  imageManagerStandalone.value = false
}

function imageFileIsAllowed(file: File) {
  const allowedTypes = new Set(['image/jpeg', 'image/png', 'image/gif', 'image/webp'])
  const extensionAllowed = /\.(?:jpe?g|png|gif|webp)$/i.test(file.name)
  return allowedTypes.has(file.type.toLocaleLowerCase()) || (!file.type && extensionAllowed)
}

async function uploadLineImages(event: Event) {
  const input = event.currentTarget as HTMLInputElement | null
  const files = Array.from(input?.files || [])
  if (input) input.value = ''
  const line = editingLineDraft.value
  const currentBom = bom.value
  if (!files.length || !line || !editingSection.value || !currentBom) return
  if (files.some((file) => !imageFileIsAllowed(file))) {
    ElMessage.warning('仅支持 JPG、JPEG、PNG、GIF、WEBP 图片。')
    return
  }
  if (files.length > 10) {
    ElMessage.warning('单次最多上传 10 张图片，请分批选择。')
    return
  }
  const remaining = 20 - displayLineImages(line).length
  if (remaining <= 0 || files.length > remaining) {
    ElMessage.warning(`每条用料明细最多上传 20 张图片，当前还可上传 ${Math.max(remaining, 0)} 张。`)
    return
  }
  if (uploadingCuttingImagesLineId.value || deletingCuttingImageId.value || cleaningCuttingDraftImages.value) return
  if (!line.id && !line.draft_key) line.draft_key = createDraftKey()
  const uploadTarget = line.id || line.draft_key || ''
  if (!uploadTarget) {
    ElMessage.error('无法创建用料图片暂存标识，请关闭弹出层后重试。')
    return
  }
  if (!line.id) {
    const targetLine = sections.value[editingSectionIndex.value]?.lines[editingLineIndex.value]
    if (targetLine) targetLine.draft_key = uploadTarget
  }
  uploadingCuttingImagesLineId.value = uploadTarget
  try {
    const result = line.id
      ? await uploadBomLineImages(currentBom.id, line.id, files, etag.value)
      : await uploadBomDraftLineImages(currentBom.id, uploadTarget, files, etag.value)
    if (result.etag) etag.value = result.etag
    if (result.images) {
      if (line.id) replaceLineImages(line.id, result.images as BomLineImage[])
      else replaceDraftLineImages(uploadTarget, result.images as BomDraftLineImage[])
    }
    ElMessage.success(`已上传 ${files.length} 张用料图片。`)
  } catch (error) {
    ElMessage.error(apiError(error, '用料图片上传失败，请稍后重试。'))
  } finally {
    uploadingCuttingImagesLineId.value = ''
  }
}

async function removeLineImage(image: CuttingDisplayImage) {
  const line = editingLineDraft.value
  const currentBom = bom.value
  if (!line || !currentBom || deletingCuttingImageId.value || uploadingCuttingImagesLineId.value || cleaningCuttingDraftImages.value) return
  try {
    await ElMessageBox.confirm(`确定删除图片“${image.name}”吗？`, '删除用料图片', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  deletingCuttingImageId.value = image.id
  try {
    if (isDraftLineImage(image)) {
      const result = await deleteBomDraftLineImage(currentBom.id, image.id, etag.value)
      if (result.etag) etag.value = result.etag
      replaceDraftLineImages(image.draft_key, (line.draft_images || []).filter((item) => item.id !== image.id))
    } else {
      if (!line.id) throw new Error('未保存用料行不能包含正式图片。')
      const result = await deleteBomLineImage(currentBom.id, line.id, image.id, etag.value)
      if (result.etag) etag.value = result.etag
      replaceLineImages(line.id, result.images || (line.images || []).filter((item) => item.id !== image.id))
    }
    ElMessage.success('用料图片已删除。')
  } catch (error) {
    ElMessage.error(apiError(error, '用料图片删除失败，请稍后重试。'))
  } finally {
    deletingCuttingImageId.value = ''
  }
}

async function cleanupDraftImages(images: BomDraftLineImage[]) {
  const currentBom = bom.value
  if (!currentBom || !images.length) return [] as string[]
  const failedIds: string[] = []
  cleaningCuttingDraftImages.value = true
  try {
    for (const image of images) {
      deletingCuttingImageId.value = image.id
      try {
        const result = await deleteBomDraftLineImage(currentBom.id, image.id, etag.value)
        if (result.etag) etag.value = result.etag
      } catch {
        failedIds.push(image.id)
      } finally {
        deletingCuttingImageId.value = ''
      }
    }
  } finally {
    cleaningCuttingDraftImages.value = false
  }
  return failedIds
}

function openLineDrawer(index: number) {
  if (!canEdit.value || !activeSection.value) return
  if (!prepareEditingLine(index) || !editingLineDraft.value) return
  const line = activeSection.value.lines[index]
  initialDrawerDraftImageIds.value = (line.draft_images || []).map((image) => image.id)
  preserveDrawerDraftImagesOnClose.value = false
  if (activeSection.value.section_type === 'PROFILE') normalizeTubeCutPieceCount(editingLineDraft.value)
  if (activeSection.value.title === '辅料类' || activeSection.value.title === '面料类') {
    void ensureEditorReferenceOptions()
  }
  editingLineIsNew.value = false
  lineDrawerVisible.value = true
}

async function discardDrawerSessionDraftImages() {
  const line = editingLineDraft.value
  if (!preserveDrawerDraftImagesOnClose.value && line && !line.id && line.draft_key) {
    const initialIds = new Set(initialDrawerDraftImageIds.value)
    const addedImages = (line.draft_images || []).filter((image) => !initialIds.has(image.id))
    if (addedImages.length) {
      const failedIds = new Set(await cleanupDraftImages(addedImages))
      const keptImages = (line.draft_images || []).filter((image) => initialIds.has(image.id))
      replaceDraftLineImages(line.draft_key, keptImages)
      if (failedIds.size) ElMessage.warning('部分暂存图片未能立即清理，系统会在过期后自动回收。')
    }
  }
}

async function beforeLineDrawerClose(done: () => void) {
  if (uploadingCuttingImagesLineId.value || deletingCuttingImageId.value || cleaningCuttingDraftImages.value) {
    ElMessage.warning('图片正在处理，请完成后再关闭。')
    return
  }
  await discardDrawerSessionDraftImages()
  done()
}

async function cancelLineDrawer() {
  if (uploadingCuttingImagesLineId.value || deletingCuttingImageId.value || cleaningCuttingDraftImages.value) {
    ElMessage.warning('图片正在处理，请完成后再取消。')
    return
  }
  await discardDrawerSessionDraftImages()
  lineDrawerVisible.value = false
}

function resetLineDrawer() {
  if (advancingLineUnlockTimer !== undefined) window.clearTimeout(advancingLineUnlockTimer)
  advancingLineUnlockTimer = undefined
  advancingLineDrawer.value = false
  editingSectionIndex.value = -1
  editingLineIndex.value = -1
  editingLineDraft.value = null
  editingLineIsNew.value = false
  initialDrawerDraftImageIds.value = []
  preserveDrawerDraftImagesOnClose.value = false
}

function configuredLineError(section: BomSectionInput, line: BomLineInput, lineIndex: number) {
  const prefix = `“${section.title}”第 ${lineIndex + 1} 行`
  if (section.title === '塑料件类' && !line.id && !line.source_raw_material_id && !line.pending_raw_material) {
    return `${prefix}请先通过“选择数据”添加塑料件资料。`
  }
  if (section.title === '辅料类') {
    const isConfiguredLine = Boolean(line.source_accessory_product_name_id)
    if (!line.id && !isConfiguredLine) return `${prefix}请先通过“选择辅料”添加辅料品名。`
    if (isConfiguredLine && !line.source_accessory_specification_id) return `${prefix}请选择规格。`
    if (isConfiguredLine && !line.source_accessory_color_id) return `${prefix}请选择颜色。`
    if (isConfiguredLine && !line.source_accessory_material_id) return `${prefix}请选择材质。`
  }
  if (section.title === '包材类' && !line.id && !line.source_packaging_material_id && !line.pending_raw_material) {
    return `${prefix}请先通过“选择包材”添加包材资料。`
  }
  if (section.title === '裁剪明细' && !line.id && !line.source_cutting_material_id && !line.pending_raw_material) {
    return `${prefix}请先通过“选择裁剪”添加半成品资料。`
  }
  return ''
}

function lineFieldError(section: BomSectionInput, line: BomLineInput, lineIndex: number) {
  const prefix = `“${section.title}”第 ${lineIndex + 1} 行`
  if (section.section_type === 'PROFILE' && !pipePlan(line.length_value, line.unit_consumption, line.tube_cut_piece_count, String(bom.value?.order_quantity || ''))) {
    return `${prefix}的切割长度、单耗和每根切割支数必须为正整数，且计算结果不能超出范围。`
  }
  if (section.title === '裁剪明细') {
    const specificationError = cuttingSpecificationError(line.specification)
    if (specificationError) return `${prefix}${specificationError}`
    const isPipeLine = isPipeCuttingLine(line)
    const hasFabricSource = fabricSourceLines.value.some((item) => line.fabric_source_line_id
      ? item.id === line.fabric_source_line_id
      : Boolean(line.fabric_source_client_key && !item.id && item.client_key === line.fabric_source_client_key))
    if (!isPipeLine && !hasFabricSource) return `${prefix}请选择当前 BOM 中的来源面料。`
    const calculation = cuttingQuantities(line)
    if (calculation.error) return `${prefix}${calculation.error}`
    if (calculation.mode === 'legacy') {
      if (!line.id) return `${prefix}请填写裁片量（片/套）和每成品套数。`
      const savedLine = bom.value?.sections.flatMap(item => item.lines).find(item => item.id === line.id)
      if (savedLine && cuttingCalculation(savedLine, bom.value?.order_quantity).mode !== 'legacy') return `${prefix}已采用片/套用量，不能清空全部新参数退回旧口径。`
    }
  }
  const configuredError = configuredLineError(section, line, lineIndex)
  if (configuredError) return configuredError
  if (section.title === '五金件') {
    const weightText = String(line.unit_material_weight_kg || '').trim()
    const weight = decimalFraction(weightText)
    if (weightText && (!weight || weight.numerator < 0n)) {
      return `${prefix}的单个材料重量必须是大于或等于 0 的数字。`
    }
    if (String(line.hardware_flow_unit || '').trim().toUpperCase() === 'KG' && (!weight || weight.numerator <= 0n)) {
      return `${prefix}按重量流转，请填写大于 0 的单个材料重量（kg）。`
    }
    const coatingAreaText = String(line.powder_coating_unit_area_sqm || '').trim()
    const coatingArea = decimalFraction(coatingAreaText)
    if (coatingAreaText && (!coatingArea || coatingArea.numerator < 0n)) {
      return `${prefix}的喷塑单个面积必须是大于或等于 0 的数字。`
    }
  }
  if (section.title === '包材类') {
    const unitsPerBox = decimalFraction(line.units_per_box)
    if (!unitsPerBox || unitsPerBox.numerator <= 0n || unitsPerBox.numerator % unitsPerBox.denominator !== 0n) {
      return `${prefix}的箱数（多少一箱）必须是正整数。`
    }
    const unitConsumption = decimalFraction(line.unit_consumption)
    if (!unitConsumption || unitConsumption.numerator <= 0n) return `${prefix}的单个用量必须是大于 0 的数字。`
  }
  if (section.title === '裁剪明细' && cuttingQuantities(line).mode === 'legacy') {
    const quantityText = String(line.cut_piece_quantity || '').trim()
    const quantity = decimalFraction(quantityText)
    if (quantityText && (!quantity || quantity.numerator < 0n)) {
      return `${prefix}的裁片量必须是大于或等于 0 的数字。`
    }
  }
  return ''
}

async function commitLineDrawer() {
  if (calculatingLine.value) return null
  const targetSection = sections.value[editingSectionIndex.value]
  if (!editingLineDraft.value || !targetSection) {
    ElMessage.error('当前用料明细已不存在，请关闭弹出层后刷新页面。')
    return null
  }
  if (!String(editingLineDraft.value.part_name ?? '').trim()) {
    ElMessage.warning(`“${targetSection.title}”第 ${editingLineIndex.value + 1} 行的品名不能为空。`)
    return null
  }
  const fieldError = lineFieldError(targetSection, editingLineDraft.value, editingLineIndex.value)
  if (fieldError) {
    ElMessage.warning(fieldError)
    return null
  }
  if (targetSection.section_type === 'PROFILE' || targetSection.title === '面料类') {
    const draftSnapshot = JSON.stringify(editingLineDraft.value)
    calculatingLine.value = true
    try {
      const line = editingLineDraft.value
      await previewBomMaterialFlow(targetSection.section_type === 'PROFILE'
        ? { kind: 'PIPE', order_quantity: String(bom.value?.order_quantity || ''), cutting_length_mm: line.length_value, pieces_per_product: line.unit_consumption, pieces_per_bar: line.tube_cut_piece_count }
        : { kind: 'FABRIC', order_quantity: String(bom.value?.order_quantity || ''), unit_consumption: line.unit_consumption })
      if (!lineDrawerVisible.value || line !== editingLineDraft.value || draftSnapshot !== JSON.stringify(editingLineDraft.value)) {
        ElMessage.warning('核算期间内容已变化，请重新应用修改。')
        return null
      }
    } catch (error) {
      ElMessage.error(apiError(error, '数量核算失败，请重试。'))
      return null
    } finally {
      calculatingLine.value = false
    }
  }
  if (targetSection.title === '面料类') editingLineDraft.value.unit = '米'
  if (targetSection.title === '裁剪明细') {
    syncCuttingValues(editingLineDraft.value)
    syncCuttingSourceAttributes(editingLineDraft.value)
  }
  if (targetSection.section_type === 'PROFILE') normalizeTubeCutPieceCount(editingLineDraft.value)
  if (editingLineIsNew.value) {
    if (editingLineIndex.value < 0 || editingLineIndex.value > targetSection.lines.length) {
      ElMessage.error('新增用料的位置已变化，请关闭弹出层后重试。')
      return null
    }
    targetSection.lines.splice(editingLineIndex.value, 0, { ...editingLineDraft.value })
    editingLineIsNew.value = false
  } else {
    const targetLine = targetSection.lines[editingLineIndex.value]
    if (!targetLine) {
      ElMessage.error('当前用料明细已不存在，请关闭弹出层后刷新页面。')
      return null
    }
    Object.assign(targetLine, editingLineDraft.value)
  }
  return { section: targetSection, lineIndex: editingLineIndex.value }
}

async function applyLineDrawer() {
  if (!await commitLineDrawer()) return
  preserveDrawerDraftImagesOnClose.value = true
  lineDrawerVisible.value = false
  ElMessage.success('当前行修改已应用，请记得保存 BOM 草稿。')
}

function followingLineDraft(section: BomSectionInput, current: BomLineInput): BomLineInput {
  if (section.section_type === 'PROFILE') {
    return {
      ...blankLine('根'),
      tube_shape: current.tube_shape,
      material: current.material,
      tube_diameter: current.tube_diameter,
      tube_thickness: current.tube_thickness,
      tube_coating_color: current.tube_coating_color,
      unit: current.unit || 'PCS',
    }
  }

  const next: BomLineInput = {
    ...current,
    id: undefined,
    client_key: createDraftKey(),
    length_value: '',
    unit_consumption: '',
    total_consumption: '',
    branch_count: '',
    budget_quantity: '',
    inventory_quantity: '',
    weight_grams: '',
    cut_piece_quantity: '',
    purchase_consumption: '',
    source_order_quantity: '',
    total_purchase_quantity: '',
    notes: '',
    coating_unit_area_sqm: '',
    purchase_unit_weight_kg: '',
    tube_cut_piece_count: '',
    powder_coating_color: '',
    powder_coating_unit_area_sqm: '',
    units_per_box: '',
    cutting_color: '',
    images: [],
    draft_key: '',
    draft_images: [],
  }
  if (section.title === '面料类') next.part_name = ''
  if (section.title === '裁剪明细') {
    next.unit = '套'
    next.cutting_pieces_per_set = null
    next.fabric_meters_per_piece = null
    next.cutting_sets_per_product = 1
    next.fabric_meters_per_set = null
  }
  return next
}

async function saveAndEditNextLine() {
  const draft = editingLineDraft.value
  const currentSection = editingSection.value
  if (!draft || !currentSection) return
  if (advancingLineDrawer.value) return
  advancingLineDrawer.value = true
  try {
    const inheritedValues = currentSection.section_type === 'PROFILE' ? {
      tube_shape: draft.tube_shape,
      material: draft.material,
      tube_diameter: draft.tube_diameter,
      tube_thickness: draft.tube_thickness,
      tube_coating_color: draft.tube_coating_color,
      unit: draft.unit || 'PCS',
    } : null
    const committed = await commitLineDrawer()
    if (!committed) return
    const nextLineIndex = committed.lineIndex + 1
    const nextLine = committed.section.lines[nextLineIndex]
    const nextDraft: BomLineInput = nextLine
      ? {
          ...nextLine,
          images: [...(nextLine.images || [])],
          draft_images: [...(nextLine.draft_images || [])],
        }
      : followingLineDraft(committed.section, draft)
    if (nextLine && inheritedValues) {
      if (!nextDraft.tube_shape) nextDraft.tube_shape = inheritedValues.tube_shape
      if (!nextDraft.material) nextDraft.material = inheritedValues.material
      if (!nextDraft.tube_diameter) nextDraft.tube_diameter = inheritedValues.tube_diameter
      if (!nextDraft.tube_thickness) nextDraft.tube_thickness = inheritedValues.tube_thickness
      if (!nextDraft.tube_coating_color) nextDraft.tube_coating_color = inheritedValues.tube_coating_color
      if (!nextDraft.unit) nextDraft.unit = inheritedValues.unit
      normalizeTubeCutPieceCount(nextDraft)
    }
    editingLineDraft.value = nextDraft
    initialDrawerDraftImageIds.value = (nextDraft.draft_images || []).map((image) => image.id)
    editingLineIsNew.value = !nextLine
    editingLineIndex.value = nextLineIndex
    if (committed.section.title === '辅料类' || committed.section.title === '面料类') void ensureEditorReferenceOptions()
    ElMessage.success(nextLine
      ? '当前行已应用，已进入下一条；完成后请点击顶部“保存草稿”。'
      : '当前行已应用，已新增下一条；完成后请点击顶部“保存草稿”。')
  } finally {
    if (advancingLineUnlockTimer !== undefined) window.clearTimeout(advancingLineUnlockTimer)
    advancingLineUnlockTimer = window.setTimeout(() => {
      advancingLineDrawer.value = false
      advancingLineUnlockTimer = undefined
    }, 600)
  }
}

async function removeLine(index: number) {
  if (!canEdit.value || !activeSection.value) return
  const targetSection = activeSection.value
  const targetLine = targetSection.lines[index]
  if (!targetLine) return
  if (uploadingCuttingImagesLineId.value || deletingCuttingImageId.value || cleaningCuttingDraftImages.value) {
    ElMessage.warning('图片正在处理，请完成后再删除当前行。')
    return
  }
  try {
    await ElMessageBox.confirm('确定删除这条用料明细吗？', '删除用料', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
    const failedIds = !targetLine.id ? await cleanupDraftImages(targetLine.draft_images || []) : []
    if (targetLine.id) pendingDeletedLineIds.value.add(targetLine.id)
    const currentIndex = targetSection.lines.indexOf(targetLine)
    if (currentIndex >= 0) targetSection.lines.splice(currentIndex, 1)
    selectedLineIndex.value = Math.min(selectedLineIndex.value, Math.max(0, targetSection.lines.length - 1))
    ElMessage.success(targetLine.id
      ? '该明细已标记删除，点击“保存草稿”后将从数据库删除。'
      : '新增明细已移除，保存时不会写入数据库。')
    if (failedIds.length) ElMessage.warning('当前行已删除；部分暂存图片未能立即清理，系统会在过期后自动回收。')
  } catch {
    // 用户取消删除时不做处理。
  }
}

function validateLines() {
  for (const section of sections.value) {
    if (!section.title.trim()) {
      ElMessage.warning('用料分区名称不能为空。')
      return false
    }
    const emptyIndex = section.lines.findIndex((line) => !String(line.part_name ?? '').trim())
    if (emptyIndex >= 0) {
      activeSectionIndex.value = sections.value.indexOf(section)
      ElMessage.warning(`“${section.title}”第 ${emptyIndex + 1} 行的配件或裁片名称不能为空。`)
      return false
    }
    for (const [index, line] of section.lines.entries()) {
      const fieldError = lineFieldError(section, line, index)
      if (fieldError) {
        activeSectionIndex.value = sections.value.indexOf(section)
        ElMessage.warning(fieldError)
        return false
      }
      if (section.title === '面料类') line.unit = '米'
      if (section.title === '裁剪明细') {
        syncCuttingValues(line)
        syncCuttingSourceAttributes(line)
      }
    }
  }
  return true
}

async function persistDraft(showMessage = true) {
  return startMaterialSave('draft', showMessage)
}

function materialSaveSnapshotMatches(pending: PendingBomSave) {
  return bom.value?.id === pending.bomId && etag.value === pending.etag
    && JSON.stringify(sections.value) === pending.snapshot
    && (pending.options.intent !== 'verify' || quantityReason.value.trim() === pending.options.quantity_confirmation_reason)
}

async function writeMaterialSave(pending: PendingBomSave, confirmationToken?: string) {
  try {
    const options = { ...pending.options, ...(confirmationToken ? { confirmation_token: confirmationToken } : {}) }
    const result = await saveBomDraft(pending.bomId, pending.sections, pending.etag, options)
    applyVersioned(result)
    pendingRawMaterials.value = {}
    if (pending.showMessage) ElMessage.success(pending.options.intent === 'verify'
      ? 'BOM 已提交。'
      : pending.deletedCount ? `BOM 草稿已保存，已删除 ${pending.deletedCount} 条旧明细。` : 'BOM 草稿已保存。')
    return true
  } catch (error) {
    ElMessage.error(apiError(error))
    return false
  }
}

async function startMaterialSave(intent: 'draft' | 'verify', showMessage = true) {
  if (!bom.value || saving.value || verifying.value) return false
  if (intent === 'draft' ? !canEdit.value : !canVerify.value) return false
  for (const section of sections.value) {
    if (section.section_type === 'PROFILE') section.lines.forEach(normalizeTubeCutPieceCount)
  }
  if (!validateLines()) return false
  if (!etag.value) {
    ElMessage.error('当前页面缺少版本信息，请刷新后重试。')
    return false
  }
  const snapshot = JSON.stringify(sections.value)
  const pending: PendingBomSave = {
    bomId: bom.value.id, etag: etag.value, sections: JSON.parse(snapshot), snapshot, showMessage,
    deletedCount: pendingDeletedLineIds.value.size,
    options: { intent, ...(intent === 'verify' ? { quantity_confirmation_reason: quantityReason.value.trim() } : {}) },
  }
  if (intent === 'draft') saving.value = true
  else verifying.value = true
  try {
    const preview = await previewBomMaterialSave(pending.bomId, pending.sections, pending.etag, pending.options)
    if (!materialSaveSnapshotMatches(pending)) {
      ElMessage.warning('预检期间内容已变化，请重新保存以检查最新内容。')
      return false
    }
    if (preview.new_materials.length) {
      if (!preview.confirmation_token) throw new Error('原料新增清单缺少确认凭据，请重新检查。')
      return await writeMaterialSave(pending, preview.confirmation_token)
    }
    return await writeMaterialSave(pending)
  } catch (error) {
    ElMessage.error(apiError(error))
    return false
  } finally {
    saving.value = false
    verifying.value = false
  }
}

async function submitVerification() {
  if (bom.value && !bom.value.product_information_confirmed) {
    ElMessage.warning('请先核对本条产品信息，再确认 BOM。')
    openProductConfirmDialog()
    return
  }
  if (!bom.value || !canVerify.value || saving.value || verifying.value) return
  if (!sections.value.some((section) => section.lines.length)) {
    ElMessage.warning('至少添加一条用料明细后才能提交。')
    return
  }
  if (quantityMismatch.value && !quantityReason.value.trim()) {
    ElMessage.warning({ message: quantityMismatchMessage.value, duration: 8000, showClose: true })
    return
  }
  if (canEdit.value) {
    await startMaterialSave('verify')
    return
  }
  if (!etag.value) {
    ElMessage.error('当前页面缺少版本信息，请刷新后重试。')
    return
  }
  verifying.value = true
  try {
    applyVersioned(await verifyBom(bom.value.id, quantityReason.value.trim(), etag.value))
    ElMessage.success('BOM 已提交。')
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    verifying.value = false
  }
}

function tubeCalculations(line: BomLineInput) {
  return calculateTubeCalculations(line, bom.value)
}

function blankLine(defaultUnit = ''): BomLineInput {
  return createBlankLine(defaultUnit)
}

function editableLine(line: BomLine): BomLineInput {
  return normalizeEditableLine(line)
}
// 保留原编辑器实例上的转换入口；实现本身已集中到辅助模块。
void editableLine

function printPage() {
  window.print()
}

watch(() => route.params.bomId, () => { void loadBom() })

onMounted(() => {
  window.addEventListener('keydown', closeTableFullscreen)
  void loadBom()
  void loadTubeOptions()
})

onBeforeUnmount(() => {
  disposed = true
  bomLoadGeneration += 1
  bomLoadController?.abort()
  if (advancingLineUnlockTimer !== undefined) window.clearTimeout(advancingLineUnlockTimer)
  window.removeEventListener('keydown', closeTableFullscreen)
})

</script>

<template>
  <section v-loading="saving || verifying" class="bom-editor-page erp-glass-form" aria-label="BOM 编辑">
    <BomPrintDocument v-if="bom && !loading && !errorMessage" :bom="bom" :sections="sections" />
    <div v-if="loading" class="page-state" v-loading="true" />
    <ElResult v-else-if="errorMessage" class="bom-error-state" role="alert" title="BOM 加载失败" :sub-title="errorMessage">
      <template #icon>
        <svg class="bom-error-state__icon" viewBox="0 0 72 72" fill="none" aria-hidden="true" focusable="false">
          <rect x="3" y="3" width="66" height="66" rx="18" fill="var(--erp-color-selected)" />
          <path d="M22 15h21l9 9v29a4 4 0 0 1-4 4H26a4 4 0 0 1-4-4V19a4 4 0 0 1 4-4Z" fill="var(--erp-color-surface)" stroke="var(--erp-color-brand)" stroke-width="2" />
          <path d="M43 15v9h9" stroke="var(--erp-color-brand)" stroke-width="2" stroke-linejoin="round" />
          <rect x="28" y="30" width="4" height="4" rx="1" fill="var(--erp-color-brand)" />
          <path d="M37 32h10" stroke="var(--erp-color-text-secondary)" stroke-width="2" stroke-linecap="round" />
          <rect x="28" y="39" width="4" height="4" rx="1" fill="var(--erp-color-brand)" />
          <path d="M37 41h10" stroke="var(--erp-color-text-secondary)" stroke-width="2" stroke-linecap="round" />
          <rect x="28" y="48" width="4" height="4" rx="1" fill="var(--erp-color-brand)" />
          <path d="M37 50h7" stroke="var(--erp-color-text-secondary)" stroke-width="2" stroke-linecap="round" />
          <circle cx="52" cy="52" r="11" fill="var(--erp-color-danger)" stroke="var(--erp-color-selected)" stroke-width="3" />
          <path d="M52 47v5" stroke="var(--erp-color-text-inverse)" stroke-width="2" stroke-linecap="round" />
          <circle cx="52" cy="56" r="1.2" fill="var(--erp-color-text-inverse)" />
        </svg>
      </template>
      <template #extra><ElButton class="bom-error-state__retry" type="primary" @click="loadBom">重新加载</ElButton></template>
    </ElResult>
    <template v-else-if="bom">
      <BomProductConfirmationDialogs
        ref="productConfirmDialog"
        v-model="productConfirmVisible"
        v-model:create-product-visible="productConfirmCreateVisible"
        v-model:create-color-visible="productConfirmColorCreateVisible"
        :bom="bom"
        :product-confirm-item="productConfirmItem"
        :product-confirm-options="productConfirmOptions"
        :product-confirm-colors="productConfirmColors"
        :can-create-product="canCreateProduct"
        :can-create-product-color="canCreateProductColor"
        :product-confirm-loading="productConfirmLoading"
        :product-confirm-catalog-error="productConfirmCatalogError"
        :product-confirm-catalog-loading="productConfirmCatalogLoading"
        :product-confirm-error="productConfirmError"
        :product-create-initial="productCreateInitial"
        :product-create-unit-code="productCreateUnitCode"
        :product-create-item-number="productCreateItemNumber"
        :product-color-draft="productColorDraft"
        :format-number="number"
        :submit-product="createProductForBom"
        @confirm="confirmProductInformation"
        @retry-catalog="loadProductConfirmCatalog"
        @create-product="prepareConfirmedProductCreate"
        @create-color="openConfirmedColorCreate"
        @created="handleConfirmedProductCreated"
        @save-color="createConfirmedColor"
      />
      <header class="editor-heading">
        <div>
          <div class="title-line">
            <h1>编辑BOM&nbsp; {{ bom.bom_number }}</h1>
            <span class="editor-status-tag" :class="{ verified: bom.status === 'VERIFIED' }">{{ editorStatusLabel }}</span>
          </div>
        </div>
        <div class="heading-actions">
          <ElButton @click="printPage">预览打印</ElButton>
          <ElButton v-if="canEdit" :loading="saving" :disabled="verifying" @click="persistDraft()">保存草稿</ElButton>
          <ElButton v-if="canVerify" type="primary" :loading="verifying" :disabled="saving" @click="submitVerification">确认BOM</ElButton>
        </div>
      </header>

      <nav class="bom-editor-tabs" role="tablist" aria-label="BOM 编辑内容" @keydown="focusEditorTab">
        <button id="bom-product-tab" type="button" role="tab" aria-controls="bom-product-panel" :aria-selected="activeEditorTab === 'product'" :tabindex="focusedEditorTab === 'product' ? 0 : -1" @click="selectEditorTab('product')">订单与产品</button>
        <button id="bom-material-tab" type="button" role="tab" aria-controls="bom-material-panel" :aria-selected="activeEditorTab === 'materials'" :tabindex="focusedEditorTab === 'materials' ? 0 : -1" @click="selectEditorTab('materials')">BOM 用料</button>
      </nav>
      <section v-show="activeEditorTab === 'product'" id="bom-product-panel" class="card product-card" role="tabpanel" aria-labelledby="bom-product-tab">
        <header><h2>订单与产品</h2><ElButton plain @click="openProductConfirmDialog">查看产品信息</ElButton></header>
        <BomProductOverview v-if="activeEditorTab === 'product'" :bom="bom" />
      </section>

      <BomProductInfoDialog v-model="productInfoVisible" :bom="bom" />

      <div v-show="activeEditorTab === 'materials'" id="bom-material-panel" role="tabpanel" aria-labelledby="bom-material-tab">
      <div class="editor-grid">
        <BomSectionSidebar
          :groups="sectionNavigationGroups"
          :active-label="activeNavigationLabel"
          :has-sections="sections.length > 0"
          @select="selectNavigationGroup"
        />
        <main class="card material-card">
          <header class="material-heading">
            <div><h2>{{ activeSection?.title || '用料明细' }}</h2><span>{{ activeSection?.lines.length || 0 }} 行 · {{ materialReferenceHint }}</span></div>
            <div v-if="canEdit && (activeSectionCanAddLine || activeSectionCanChooseData)" class="material-actions">
              <ElButton v-if="activeSectionCanAddLine" type="primary" @click="addLine">添加材料</ElButton>
              <ElButton v-if="isHardwareSection" type="primary" @click="openHardwarePicker">选择数据</ElButton>
              <ElButton v-if="isPlasticSection" type="primary" @click="openPlasticPicker">选择数据</ElButton>
              <ElButton v-if="isAuxiliarySection" type="primary" @click="openAuxiliaryPicker">选择辅料</ElButton>
              <ElButton v-if="isFabricSection" type="primary" :loading="editorReferenceOptionsLoading" @click="addFabricLine">添加面料</ElButton>
              <ElButton v-if="isPackagingSection" type="primary" @click="openPackagingPicker">选择包材</ElButton>
              <ElButton v-if="isCuttingSection" type="primary" @click="openCuttingPicker">选择裁剪</ElButton>
            </div>
          </header>

          <div v-if="activeSection" class="section-editor" :class="{ 'is-table-fullscreen': tableFullscreen }">
            <ElAlert v-if="(isAuxiliarySection || isFabricSection) && editorReferenceOptionsError" class="reference-options-error" type="error" :title="editorReferenceOptionsError" show-icon :closable="false">
              <template #default><ElButton size="small" @click="ensureEditorReferenceOptions">重新加载生产维护数据</ElButton></template>
            </ElAlert>
            <BomMaterialSectionTables
              v-if="activeSection.section_type === 'PROFILE' || isHardwareSection || isPlasticSection || isAuxiliarySection || isFabricSection || isPackagingSection || isCuttingSection || activeSection.lines.length"
              :active-section="activeSection"
              :is-hardware-section="isHardwareSection"
              :is-plastic-section="isPlasticSection"
              :is-auxiliary-section="isAuxiliarySection"
              :is-fabric-section="isFabricSection"
              :is-packaging-section="isPackagingSection"
              :is-cutting-section="isCuttingSection"
              :can-edit="canEdit"
              :table-fullscreen="tableFullscreen"
              :tube-options-loading="tubeOptionsLoading"
              :editor-reference-options-loading="editorReferenceOptionsLoading"
              :tube-coating-colors="tubeCoatingColors"
              :toggle-table-fullscreen="toggleTableFullscreen"
              :open-line-drawer="openLineDrawer"
              :remove-line="removeLine"
              :open-line-image-manager="openLineImageManager"
              :tube-calculations="tubeCalculations"
              :format-hardware-color="formatHardwareColor"
              :auxiliary-line-has-active-product="auxiliaryLineHasActiveProduct"
              :auxiliary-specification-options="auxiliarySpecificationOptions"
              :set-auxiliary-specification="setAuxiliarySpecification"
              :auxiliary-color-options="auxiliaryColorOptions"
              :set-auxiliary-color="setAuxiliaryColor"
              :auxiliary-material-options="auxiliaryMaterialOptions"
              :set-auxiliary-material="setAuxiliaryMaterial"
              :fabric-specification-options="fabricSpecificationOptions"
              :set-fabric-specification="setFabricSpecification"
              :fabric-material-options="fabricMaterialOptions"
              :set-fabric-material="setFabricMaterial"
              :fabric-color-snapshot="fabricColorSnapshot"
              :fabric-color-options="fabricColorOptions"
              :set-fabric-color="setFabricColor"
              :fabric-width-options="fabricWidthOptions"
              :set-fabric-width="setFabricWidth"
              :cutting-quantities="cuttingQuantities"
              :legacy-pipe-cutting-values="legacyPipeCuttingValues"
            />
            <div v-else class="pending-section-fields">
              <strong>{{ activeSection.title }}</strong>
              <span>该固定分区的填写字段待后续完善，本轮不套用其他分区的字段。</span>
            </div>
            <div v-if="tableFullscreen && canEdit && (activeSectionCanAddLine || activeSectionCanChooseData)" class="fullscreen-table-actions">
              <ElButton v-if="activeSectionCanAddLine" type="primary" :icon="Plus" @click="addLine">添加材料</ElButton>
              <ElButton v-if="isHardwareSection" type="primary" :icon="Plus" @click="openHardwarePicker">选择数据</ElButton>
              <ElButton v-if="isPlasticSection" type="primary" :icon="Plus" @click="openPlasticPicker">选择数据</ElButton>
              <ElButton v-if="isAuxiliarySection" type="primary" :icon="Plus" @click="openAuxiliaryPicker">选择辅料</ElButton>
              <ElButton v-if="isFabricSection" type="primary" :icon="Plus" :loading="editorReferenceOptionsLoading" @click="addFabricLine">添加面料</ElButton>
              <ElButton v-if="isPackagingSection" type="primary" :icon="Plus" @click="openPackagingPicker">选择包材</ElButton>
              <ElButton v-if="isCuttingSection" type="primary" :icon="Plus" @click="openCuttingPicker">选择裁剪</ElButton>
            </div>
          </div>
          <ElEmpty v-else description="固定用料分区加载失败，请刷新页面" :image-size="72" />

          <section v-if="activeSection?.section_type !== 'PROFILE' && activePersistedSection?.calculation_rows.length" class="calculation-panel">
            <header><strong>计算字段（已展开）</strong><span>保留 Excel 原始计算及汇总行</span></header>
            <div class="calculation-grid">
              <article v-for="row in activePersistedSection.calculation_rows.slice(0, 3)" :key="row.source_row_number">
                <strong>原表第 {{ row.source_row_number }} 行</strong>
                <span>{{ Object.values(row.raw_values).filter(Boolean).slice(0, 4).join(' · ') || '已保留计算公式' }}</span>
              </article>
            </div>
          </section>
        </main>

      </div>

      <BomQuantityCompareCard
        :bom="bom"
        :quantity-mismatch="quantityMismatch"
        v-model:quantity-reason="quantityReason"
        :can-verify="canVerify"
        :syncing-quantity="syncingQuantity"
        :can-sync="canSync"
        @sync="requestOrderQuantitySync(false)"
      />

      </div>
      <BomLineEditorDialog
        v-model="lineDrawerVisible"
        :title="lineDrawerTitle"
        :before-close="beforeLineDrawerClose"
        @closed="resetLineDrawer"
      >
        <BomLineEditorForm
          v-model:editing-fabric-source-key="editingFabricSourceKey"
          :editing-section="editingSection"
          :editing-line-draft="editingLineDraft"
          :editor-reference-options-error="editorReferenceOptionsError"
          :ensure-editor-reference-options="ensureEditorReferenceOptions"
          :tube-shapes="tubeShapes"
          :tube-product-names="tubeProductNames"
          :tube-materials="tubeMaterials"
          :tube-diameters="tubeDiameters"
          :tube-thicknesses="tubeThicknesses"
          :tube-coating-colors="tubeCoatingColors"
          :tube-options-loading="tubeOptionsLoading"
          :editing-line-calculations="editingLineCalculations"
          :normalize-tube-cut-piece-count="normalizeTubeCutPieceCount"
          :display-line-images="displayLineImages"
          :open-line-image-manager="openLineImageManager"
          :format-hardware-color="formatHardwareColor"
          :auxiliary-line-has-active-product="auxiliaryLineHasActiveProduct"
          :auxiliary-specification-options="auxiliarySpecificationOptions"
          :set-auxiliary-specification="setAuxiliarySpecification"
          :auxiliary-color-options="auxiliaryColorOptions"
          :set-auxiliary-color="setAuxiliaryColor"
          :auxiliary-material-options="auxiliaryMaterialOptions"
          :set-auxiliary-material="setAuxiliaryMaterial"
          :fabric-specification-options="fabricSpecificationOptions"
          :set-fabric-specification="setFabricSpecification"
          :fabric-color-snapshot="fabricColorSnapshot"
          :fabric-color-options="fabricColorOptions"
          :set-fabric-color="setFabricColor"
          :fabric-material-options="fabricMaterialOptions"
          :set-fabric-material="setFabricMaterial"
          :fabric-width-options="fabricWidthOptions"
          :set-fabric-width="setFabricWidth"
          :is-pipe-cutting-line="isPipeCuttingLine"
          :fabric-source-lines="fabricSourceLines"
          :legacy-pipe-cutting-values="legacyPipeCuttingValues"
          :editing-cutting-calculation="editingCuttingCalculation"
          :bom="bom"
          :number="number"
        />        <template #footer>
          <div class="line-drawer-footer">
            <ElButton :disabled="Boolean(uploadingCuttingImagesLineId || deletingCuttingImageId || cleaningCuttingDraftImages)" @click="cancelLineDrawer">取消</ElButton>
            <ElButton :loading="calculatingLine" :disabled="saving || Boolean(uploadingCuttingImagesLineId || deletingCuttingImageId || cleaningCuttingDraftImages)" @click="applyLineDrawer">应用修改</ElButton>
            <ElButton type="primary" :disabled="saving || calculatingLine || advancingLineDrawer || Boolean(uploadingCuttingImagesLineId || deletingCuttingImageId || cleaningCuttingDraftImages)" @click="saveAndEditNextLine">{{ drawerNextActionLabel }}</ElButton>
          </div>
        </template>
      </BomLineEditorDialog>

      <BomLineImageManager
        v-model="imageManagerVisible"
        :line="editingLineDraft"
        :section-title="editingSection?.title || ''"
        :line-index="editingLineIndex"
        :can-edit="canEdit"
        :busy="imageManagerIsBusy()"
        :uploading="Boolean(uploadingCuttingImagesLineId)"
        :deleting-image-id="deletingCuttingImageId"
        :z-index="imageManagerZIndex"
        :before-close="beforeImageManagerClose"
        @upload="uploadLineImages"
        @remove="removeLineImage"
        @open-file-picker="openImageFilePicker"
        @close="closeImageManager"
        @closed="resetImageManager"
      />

      <BomMaterialPickerDialogs
        v-model:hardware-picker-visible="hardwarePickerVisible"
        v-model:hardware-picker-material-name="hardwarePickerMaterialName"
        v-model:hardware-picker-keyword="hardwarePickerKeyword"
        :hardware-group-loading="hardwareGroupLoading"
        :hardware-picker-loading="hardwarePickerLoading"
        :hardware-group-error="hardwareGroupError"
        :hardware-picker-error="hardwarePickerError"
        :visible-hardware-groups="visibleHardwareGroups"
        :hardware-candidates="hardwareCandidates"
        :selected-hardware="selectedHardware"
        :hardware-picker-page="hardwarePickerPage"
        :hardware-picker-page-size="hardwarePickerPageSize"
        :hardware-picker-total="hardwarePickerTotal"
        :selected-hardware-count="selectedHardwareCount"
        :hardware-page-all-selected="hardwarePageAllSelected"
        :hardware-page-selection-indeterminate="hardwarePageSelectionIndeterminate"
        :can-create-hardware-raw-material="canCreateHardwareRawMaterial"
        :reset-hardware-picker="resetHardwarePicker"
        v-model:plastic-picker-visible="plasticPickerVisible"
        v-model:plastic-picker-material-name="plasticPickerMaterialName"
        v-model:plastic-picker-keyword="plasticPickerKeyword"
        :plastic-group-loading="plasticGroupLoading"
        :plastic-picker-loading="plasticPickerLoading"
        :plastic-group-error="plasticGroupError"
        :plastic-picker-error="plasticPickerError"
        :visible-plastic-groups="visiblePlasticGroups"
        :plastic-candidates="plasticCandidates"
        :selected-plastic="selectedPlastic"
        :plastic-picker-page="plasticPickerPage"
        :plastic-picker-page-size="plasticPickerPageSize"
        :plastic-picker-total="plasticPickerTotal"
        :selected-plastic-count="selectedPlasticCount"
        :plastic-page-all-selected="plasticPageAllSelected"
        :plastic-page-selection-indeterminate="plasticPageSelectionIndeterminate"
        :can-create-raw-material="canCreateRawMaterial"
        :reset-plastic-picker="resetPlasticPicker"
        v-model:auxiliary-picker-visible="auxiliaryPickerVisible"
        v-model:auxiliary-picker-product-name="auxiliaryPickerProductName"
        v-model:auxiliary-picker-keyword="auxiliaryPickerKeyword"
        :auxiliary-candidates="auxiliaryCandidates"
        :selected-auxiliary-products="selectedAuxiliaryProducts"
        :auxiliary-picker-page="auxiliaryPickerPage"
        :auxiliary-picker-page-size="auxiliaryPickerPageSize"
        :auxiliary-picker-total="auxiliaryPickerTotal"
        :selected-auxiliary-product-count="selectedAuxiliaryProductCount"
        :auxiliary-page-all-selected="auxiliaryPageAllSelected"
        :auxiliary-page-selection-indeterminate="auxiliaryPageSelectionIndeterminate"
        :editor-reference-options="editorReferenceOptions"
        :editor-reference-options-loading="editorReferenceOptionsLoading"
        :editor-reference-options-error="editorReferenceOptionsError"
        :reset-auxiliary-picker="resetAuxiliaryPicker"
        v-model:packaging-picker-visible="packagingPickerVisible"
        v-model:packaging-picker-material-name="packagingPickerMaterialName"
        v-model:packaging-picker-keyword="packagingPickerKeyword"
        :packaging-group-loading="packagingGroupLoading"
        :packaging-picker-loading="packagingPickerLoading"
        :packaging-group-error="packagingGroupError"
        :packaging-picker-error="packagingPickerError"
        :visible-packaging-groups="visiblePackagingGroups"
        :packaging-candidates="packagingCandidates"
        :selected-packaging="selectedPackaging"
        :packaging-picker-page="packagingPickerPage"
        :packaging-picker-page-size="packagingPickerPageSize"
        :packaging-picker-total="packagingPickerTotal"
        :selected-packaging-count="selectedPackagingCount"
        :packaging-page-all-selected="packagingPageAllSelected"
        :packaging-page-selection-indeterminate="packagingPageSelectionIndeterminate"
        :reset-packaging-picker="resetPackagingPicker"
        v-model:cutting-picker-visible="cuttingPickerVisible"
        v-model:cutting-picker-material-name="cuttingPickerMaterialName"
        v-model:cutting-picker-keyword="cuttingPickerKeyword"
        :cutting-group-loading="cuttingGroupLoading"
        :cutting-picker-loading="cuttingPickerLoading"
        :cutting-group-error="cuttingGroupError"
        :cutting-picker-error="cuttingPickerError"
        :visible-cutting-groups="visibleCuttingGroups"
        :cutting-candidates="cuttingCandidates"
        :selected-cutting="selectedCutting"
        :cutting-picker-page="cuttingPickerPage"
        :cutting-picker-page-size="cuttingPickerPageSize"
        :cutting-picker-total="cuttingPickerTotal"
        :selected-cutting-count="selectedCuttingCount"
        :cutting-page-all-selected="cuttingPageAllSelected"
        :cutting-page-selection-indeterminate="cuttingPageSelectionIndeterminate"
        :reset-cutting-picker="resetCuttingPicker"
        :pending-raw-materials="pendingRawMaterials"
        :format-hardware-color="formatHardwareColor"
        :filter-hardware-groups="filterHardwareGroups"
        :search-hardware-candidates="searchHardwareCandidates"
        :clear-hardware-group-filter="clearHardwareGroupFilter"
        :load-hardware-groups="loadHardwareGroups"
        :load-hardware-candidates="loadHardwareCandidates"
        :toggle-hardware-row="toggleHardwareRow"
        :hardware-picker-row-class="hardwarePickerRowClass"
        :toggle-hardware-page="toggleHardwarePage"
        :toggle-hardware-candidate="toggleHardwareCandidate"
        :change-hardware-page="changeHardwarePage"
        :open-hardware-create="openHardwareCreate"
        :confirm-hardware-selection="confirmHardwareSelection"
        :filter-plastic-groups="filterPlasticGroups"
        :search-plastic-candidates="searchPlasticCandidates"
        :clear-plastic-group-filter="clearPlasticGroupFilter"
        :load-plastic-groups="loadPlasticGroups"
        :load-plastic-candidates="loadPlasticCandidates"
        :toggle-plastic-row="togglePlasticRow"
        :plastic-picker-row-class="plasticPickerRowClass"
        :toggle-plastic-page="togglePlasticPage"
        :toggle-plastic-candidate="togglePlasticCandidate"
        :change-plastic-page="changePlasticPage"
        :open-raw-material-create="openRawMaterialCreate"
        :confirm-plastic-selection="confirmPlasticSelection"
        :search-auxiliary-candidates="searchAuxiliaryCandidates"
        :ensure-editor-reference-options="ensureEditorReferenceOptions"
        :toggle-auxiliary-row="toggleAuxiliaryRow"
        :auxiliary-picker-row-class="auxiliaryPickerRowClass"
        :toggle-auxiliary-page="toggleAuxiliaryPage"
        :toggle-auxiliary-candidate="toggleAuxiliaryCandidate"
        :change-auxiliary-page="changeAuxiliaryPage"
        :open-auxiliary-create="openAuxiliaryCreate"
        :confirm-auxiliary-selection="confirmAuxiliarySelection"
        :auxiliary-product-maintenance-tip="auxiliaryProductMaintenanceTip"
        :auxiliary-product-is-selectable="auxiliaryProductIsSelectable"
        :auxiliary-specification-summary="auxiliarySpecificationSummary"
        :auxiliary-color-summary="auxiliaryColorSummary"
        :filter-packaging-groups="filterPackagingGroups"
        :search-packaging-candidates="searchPackagingCandidates"
        :clear-packaging-group-filter="clearPackagingGroupFilter"
        :load-packaging-groups="loadPackagingGroups"
        :load-packaging-candidates="loadPackagingCandidates"
        :toggle-packaging-row="togglePackagingRow"
        :packaging-picker-row-class="packagingPickerRowClass"
        :toggle-packaging-page="togglePackagingPage"
        :toggle-packaging-candidate="togglePackagingCandidate"
        :change-packaging-page="changePackagingPage"
        :confirm-packaging-selection="confirmPackagingSelection"
        :filter-cutting-groups="filterCuttingGroups"
        :search-cutting-candidates="searchCuttingCandidates"
        :clear-cutting-group-filter="clearCuttingGroupFilter"
        :load-cutting-groups="loadCuttingGroups"
        :load-cutting-candidates="loadCuttingCandidates"
        :toggle-cutting-row="toggleCuttingRow"
        :cutting-picker-row-class="cuttingPickerRowClass"
        :toggle-cutting-page="toggleCuttingPage"
        :toggle-cutting-candidate="toggleCuttingCandidate"
        :change-cutting-page="changeCuttingPage"
        :confirm-cutting-selection="confirmCuttingSelection"
      />

      <BomMaterialCreateDialogs
        v-model:hardware-create-visible="hardwareCreateVisible"
        v-model:plastic-create-visible="plasticCreateVisible"
        v-model:packaging-create-visible="packagingCreateVisible"
        v-model:cutting-create-visible="cuttingCreateVisible"
        v-model:auxiliary-create-visible="auxiliaryCreateVisible"
        :stage-raw-material="stageRawMaterial"
        :handle-auxiliary-created="handleAuxiliaryCreated"
      />
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;
.bom-editor-page { min-width: 0; min-height: 0; padding: 0; box-sizing: border-box; background: transparent; color: var(--erp-color-text-primary); }
.page-state { min-height: min(760px, max(0px, calc(100dvh - 130px))); }
.bom-error-state__icon { display: block; width: 72px; height: 72px; }
.bom-error-state :deep(.bom-error-state__retry) { --el-button-bg-color: var(--erp-button-primary-background); --el-button-border-color: var(--erp-button-primary-background); --el-button-text-color: var(--erp-button-primary-text); --el-button-hover-bg-color: var(--erp-button-primary-hover-background); --el-button-hover-border-color: var(--erp-button-primary-hover-background); --el-button-active-bg-color: var(--erp-button-primary-pressed-background); --el-button-active-border-color: var(--erp-button-primary-pressed-background); min-width: 96px; height: 32px; border-radius: 5px; }
.editor-heading { min-height: 44px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px 24px; margin-bottom: 14px; }
.editor-breadcrumb { margin-bottom: 4px; color: var(--erp-color-text-secondary); font-size: 12px; }
.title-line { display: flex; align-items: center; gap: 14px; }
.title-line h1 { margin: 0; font-size: 26px; line-height: 38px; }
.heading-actions { display: flex; gap: 8px; }
.card { @include detail.surface; }
.product-card { display: block; padding: 16px; }
.product-card > header, .material-heading, .check-card > header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.card h2 { margin: 0; font-size: 17px; line-height: 26px; }
.product-card > header span { color: var(--erp-color-brand); font-size: 12px; }
.bom-editor-tabs { display: flex; gap: 24px; margin-bottom: 16px; }
.bom-editor-tabs button { height: 32px; padding: 0 4px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: token.$crm-text-secondary; font: inherit; font-size: 13px; line-height: 20px; cursor: pointer; }
.bom-editor-tabs button:hover { background: token.$crm-color-subtle; }
.bom-editor-tabs button[aria-selected='true'] { border-bottom-color: token.$crm-primary; color: token.$crm-primary; font-weight: 600; }
.bom-editor-tabs button:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
.quantity-warning { display: grid; grid-template-columns: minmax(0, 1fr) 440px auto; gap: 18px; align-items: center; min-height: 62px; margin-top: 12px; padding: 8px 14px; box-sizing: border-box; border: 1px solid var(--erp-color-warning-border); border-radius: 8px; background: var(--erp-color-warning-soft); color: var(--erp-color-warning); font-size: 12px; }
.quantity-warning__summary { display: flex; min-width: 0; flex-direction: column; gap: 5px; }
.quantity-warning strong { color: var(--erp-color-warning); }
.editor-grid { display: grid; grid-template-columns: 176px minmax(0, 1fr); gap: 14px; margin-top: 14px; align-items: stretch; }
.material-card { min-width: 0; padding: 14px 12px 12px; }
.material-heading { padding: 0 4px 12px; }
.material-heading > div:first-child { display: flex; align-items: baseline; gap: 18px; }
.material-heading span { color: var(--erp-color-text-secondary); font-size: 12px; }
.material-actions { display: flex; gap: 8px; }
.section-editor { min-width: 0; }
.section-editor.is-table-fullscreen { position: fixed; z-index: 1900; inset: 0; padding: 16px; overflow: auto; box-sizing: border-box; background: var(--erp-color-subtle); }
.reference-options-error { margin: 10px 0; }
.table-index-cell { position: relative; display: flex; min-height: 32px; align-items: center; justify-content: center; font-variant-numeric: tabular-nums; }
.table-row-actions { position: absolute; inset: 0; display: none; align-items: center; justify-content: center; gap: 2px; }
.section-editor :deep(.el-table__row:hover) .table-row-number { display: none; }
.section-editor :deep(.el-table__row:hover) .table-row-actions { display: flex; }
.table-fullscreen-button { width: 28px; min-width: 28px; height: 28px; padding: 0; }
.row-action-button { width: 28px; min-width: 28px; height: 28px; padding: 0; }
.row-action-button :deep(.el-icon) { font-size: 16px; }
.row-delete-button { margin-left: 0; }
.fullscreen-table-actions { display: flex; justify-content: flex-start; margin-top: 14px; }
.pending-section-fields { display: flex; min-height: 180px; align-items: center; justify-content: center; flex-direction: column; gap: 10px; border: 1px solid var(--erp-color-border); border-top: 0; background: var(--erp-color-subtle); color: var(--erp-color-text-secondary); }
.pending-section-fields strong { color: var(--erp-color-text-primary); font-size: 15px; }
.section-editor :deep(.el-table) { --el-table-bg-color: var(--erp-table-background); --el-table-tr-bg-color: var(--erp-table-background); --el-table-header-bg-color: var(--erp-table-header-background); --el-table-border-color: var(--erp-table-border); --el-table-row-hover-bg-color: var(--erp-table-hover); }
.section-editor :deep(.el-table__body td.el-table__cell) { background: var(--el-table-tr-bg-color); }
.section-editor :deep(.el-table__body tr.hover-row > td.el-table__cell), .section-editor :deep(.el-table__body tr:hover > td.el-table__cell) { background: var(--el-table-row-hover-bg-color); }
.section-editor :deep(.el-table .cell) { padding: 0 5px !important; }
.section-editor :deep(.control-column .cell), .section-editor :deep(.control-column-header .cell) { padding: 0 !important; text-align: center; }
.profile-ellipsis-value { display: block; width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.section-editor :deep(.el-table__body-wrapper .el-scrollbar__view) { padding-bottom: 22px; box-sizing: border-box; }
.section-editor :deep(.el-select) { width: 100%; }
.section-editor :deep(.el-input__wrapper), .section-editor :deep(.el-select__wrapper) { padding: 1px 7px; border-radius: 5px; background: var(--erp-input-background); box-shadow: 0 0 0 1px var(--erp-input-border) inset; }
.section-editor :deep(.el-input__wrapper:hover), .section-editor :deep(.el-input__wrapper.is-focus), .section-editor :deep(.el-select__wrapper:hover), .section-editor :deep(.el-select__wrapper.is-focused) { background: var(--erp-input-background); box-shadow: 0 0 0 1px var(--erp-input-focus-border) inset; }
.section-editor :deep(.el-input__inner::placeholder), .section-editor :deep(.el-select__placeholder) { color: var(--erp-input-placeholder); }
.hardware-readonly-cell { display: flex; min-height: 32px; align-items: center; padding: 0 7px; overflow: hidden; box-sizing: border-box; color: var(--erp-input-readonly-text); text-overflow: ellipsis; white-space: nowrap; }
.calculated-cell { display: flex; min-height: 32px; align-items: center; padding: 0 8px; box-sizing: border-box; border: 1px solid var(--erp-input-border); border-radius: 5px; background: var(--erp-input-readonly-background); color: var(--erp-input-readonly-text); font-variant-numeric: tabular-nums; }
.calculation-panel { @include detail.inset; margin-top: 12px; padding: 12px; }
.calculation-panel > header { display: flex; justify-content: space-between; color: var(--erp-color-text-secondary); font-size: 12px; }
.calculation-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 10px; }
.calculation-grid article { min-height: 72px; padding: 10px; box-sizing: border-box; border: 1px solid var(--erp-color-border); border-radius: 6px; background: var(--erp-color-surface); }
.calculation-grid article strong, .calculation-grid article span { display: block; font-size: 12px; }
.calculation-grid article span { margin-top: 8px; color: var(--erp-color-brand); line-height: 20px; }
.line-editor-drawer :deep(.el-drawer__header) { margin-bottom: 0; padding-bottom: 18px; border-bottom: 1px solid var(--erp-color-border); color: var(--erp-color-text-primary); font-weight: 700; }
.line-editor-drawer :deep(.el-drawer__body) { padding: 20px; }
.line-editor-drawer :deep(.el-drawer__footer) { padding: 14px 20px; border-top: 1px solid var(--erp-color-border); }
.cutting-name-tooltip-anchor.has-error { color: var(--erp-color-danger); cursor: help; text-decoration: underline dotted var(--erp-color-danger); text-underline-offset: 3px; }
:global(.cutting-name-error-tooltip.el-popper.is-light) { max-width: 280px; padding: 7px 10px; border-color: var(--erp-color-danger-border); background: var(--erp-color-danger-soft); color: var(--erp-color-danger); font-size: 12px; line-height: 18px; }
:global(.cutting-name-error-tooltip.el-popper.is-light .el-popper__arrow::before) { border-color: var(--erp-color-danger-border); background: var(--erp-color-danger-soft); }
.line-drawer-footer { display: flex; justify-content: flex-end; gap: 8px; }
.picker-status-tag { min-width: 56px; height: 24px; display: inline-flex; align-items: center; justify-content: center; padding: 0 8px; box-sizing: border-box; border: 0; border-radius: 999px; color: var(--erp-tag-success-text); font-family: "Noto Sans SC", sans-serif; font-size: 12px; line-height: 18px; font-weight: 500; white-space: nowrap; }
.picker-status-tag.is-success { background: var(--erp-tag-success-background); }
.picker-status-tag.is-warning { background: var(--erp-tag-warning-background); }
:global(.hardware-picker-dialog) { --el-color-primary: var(--erp-color-brand); --el-color-primary-light-3: var(--erp-color-brand-light-3); --el-color-primary-light-5: var(--erp-color-brand-light-5); --el-color-primary-light-7: var(--erp-color-brand-light-7); --el-color-primary-light-9: var(--erp-color-selected); overflow: hidden; border: 1px solid var(--erp-color-border); border-radius: 5px; background: var(--erp-color-surface); box-shadow: 0 18px 48px color-mix(in srgb, var(--erp-shadow-color) 18%, transparent); }
:global(.hardware-picker-dialog .el-dialog__header) { min-height: 56px; display: flex; align-items: center; margin: 0; padding: 0 20px; box-sizing: border-box; border-bottom: 1px solid var(--erp-color-border); background: var(--erp-color-surface); }
:global(.hardware-picker-dialog .el-dialog__title) { color: var(--erp-color-text-primary); font-family: "Noto Serif SC", "Songti SC", serif; font-size: 20px; line-height: 30px; font-weight: 700; }
:global(.hardware-picker-dialog .el-dialog__headerbtn) { top: 12px; right: 16px; width: 32px; height: 32px; }
:global(.hardware-picker-dialog .el-dialog__body) { padding: 14px 20px 8px; background: var(--erp-color-surface); }
:global(.hardware-picker-dialog .el-dialog__footer) { padding: 12px 20px 16px; border-top: 1px solid var(--erp-color-border); background: var(--erp-color-surface); }
:global(.hardware-picker-dialog .el-input__wrapper), :global(.hardware-picker-dialog .el-select__wrapper) { min-height: 32px; border-radius: 5px; background: var(--erp-input-background); box-shadow: 0 0 0 1px var(--erp-input-border) inset; }
:global(.hardware-picker-dialog .el-input__wrapper.is-focus), :global(.hardware-picker-dialog .el-select__wrapper.is-focused) { box-shadow: 0 0 0 1px var(--erp-input-focus-border) inset; }
:global(.hardware-picker-dialog .el-button) { min-height: 32px; border-radius: 5px; font-weight: 500; }
:global(.hardware-picker-dialog .el-button:not(.el-button--primary):not(.is-disabled)) { color: var(--erp-button-secondary-text); background: var(--erp-button-secondary-background); border-color: var(--erp-button-secondary-border); }
:global(.hardware-picker-dialog .el-button--primary:not(.is-disabled)) { color: var(--erp-button-primary-text); background: var(--erp-button-primary-background); border-color: var(--erp-button-primary-border); }
:global(.hardware-picker-dialog .el-table) { --el-table-header-bg-color: var(--erp-table-header-background); --el-table-border-color: var(--erp-table-border); --el-table-row-hover-bg-color: var(--erp-table-hover); color: var(--erp-table-text); }
:global(.hardware-picker-dialog .el-table th.el-table__cell) { height: 44px; color: var(--erp-table-header-text); font-weight: 500; }
:global(.hardware-picker-dialog .el-table td.el-table__cell) { height: 52px; background: var(--erp-table-background); }
:global(.hardware-picker-dialog .el-checkbox__inner) { border-color: var(--erp-color-border-strong); border-radius: 3px; }
:global(.hardware-picker-dialog .el-checkbox__input.is-checked .el-checkbox__inner), :global(.hardware-picker-dialog .el-checkbox__input.is-indeterminate .el-checkbox__inner) { background: var(--erp-color-brand); border-color: var(--erp-color-brand); }
:global(.hardware-picker-dialog .el-checkbox__inner::after) { top: 50%; left: 50%; translate: -50% -50%; transform-origin: center; transform: rotate(45deg) scaleY(0); }
:global(.hardware-picker-dialog .el-checkbox__input.is-checked .el-checkbox__inner::after) { border-color: var(--erp-color-text-inverse); transform: rotate(45deg) scaleY(1); }
:global(.hardware-picker-dialog .el-checkbox__input.is-indeterminate .el-checkbox__inner::before) { top: 50%; right: auto; left: 50%; width: 8px; background: var(--erp-color-text-inverse); border-color: var(--erp-color-text-inverse); translate: -50% -50%; transform: none; }
:global(.bom-reference-create-dialog) { --el-color-primary: var(--erp-color-brand); --el-color-primary-light-3: var(--erp-color-brand-light-3); --el-color-primary-light-5: var(--erp-color-brand-light-5); --el-color-primary-light-7: var(--erp-color-brand-light-7); --el-color-primary-light-9: var(--erp-color-selected); overflow: hidden; border: 1px solid var(--erp-color-border); border-radius: 5px; background: var(--erp-color-surface); box-shadow: 0 18px 48px color-mix(in srgb, var(--erp-shadow-color) 18%, transparent); }
:global(.bom-reference-create-dialog .el-dialog__header) { min-height: 56px; display: flex; align-items: center; margin: 0; padding: 0 20px; box-sizing: border-box; border-bottom: 1px solid var(--erp-color-border); background: var(--erp-color-surface); }
:global(.bom-reference-create-dialog .el-dialog__title) { color: var(--erp-color-text-primary); font-family: "Noto Serif SC", "Songti SC", serif; font-size: 20px; line-height: 30px; font-weight: 700; }
:global(.bom-reference-create-dialog .el-dialog__headerbtn) { top: 12px; right: 16px; width: 32px; height: 32px; }
:global(.bom-reference-create-dialog .el-dialog__body) { padding: 14px 20px 8px; background: var(--erp-color-surface); }
:global(.bom-reference-create-dialog .el-dialog__footer) { padding: 12px 20px 16px; border-top: 1px solid var(--erp-color-border); background: var(--erp-color-surface); }
:global(.bom-reference-create-dialog .el-alert--info.is-light) { color: var(--erp-color-text-secondary); border: 1px solid var(--erp-color-border); background: var(--erp-color-subtle); }
:global(.bom-reference-create-dialog .el-alert--info.is-light .el-alert__icon) { color: var(--erp-color-warning); }
:global(.bom-reference-create-dialog .el-form-item__label) { color: var(--erp-color-text-regular); font-weight: 500; }
:global(.bom-reference-create-dialog .el-input__wrapper), :global(.bom-reference-create-dialog .el-select__wrapper), :global(.bom-reference-create-dialog .el-textarea__inner) { border-radius: 5px; background: var(--erp-input-background); box-shadow: 0 0 0 1px var(--erp-input-border) inset; }
:global(.bom-reference-create-dialog .el-input__wrapper.is-focus), :global(.bom-reference-create-dialog .el-select__wrapper.is-focused), :global(.bom-reference-create-dialog .el-textarea__inner:focus) { box-shadow: 0 0 0 1px var(--erp-input-focus-border) inset; }
:global(.bom-reference-create-dialog .el-input.is-disabled .el-input__wrapper) { background: var(--erp-input-disabled-background); box-shadow: 0 0 0 1px var(--erp-input-border) inset; }
:global(.bom-reference-create-dialog .el-button) { min-height: 32px; border-radius: 5px; font-weight: 500; transition: none; }
:global(.bom-reference-create-dialog .el-button:not(.el-button--primary):not(.is-disabled)) { color: var(--erp-button-secondary-text); background: var(--erp-button-secondary-background); border-color: var(--erp-button-secondary-border); }
:global(.bom-reference-create-dialog .el-button--primary:not(.is-disabled)) { --el-button-bg-color: var(--erp-button-primary-background); --el-button-border-color: var(--erp-button-primary-background); --el-button-text-color: var(--erp-button-primary-text); color: var(--erp-button-primary-text) !important; background-color: var(--erp-button-primary-background) !important; border-color: var(--erp-button-primary-border) !important; }
/* BOM-V3-03：六类导航、行选择与下方物料明细编辑。 */
.title-line { gap: 14px; }
.title-line h1 { font-family: "Noto Serif SC", "Songti SC", serif; font-size: 28px; line-height: 40px; letter-spacing: -.3px; }
.editor-status-tag { min-width: 48px; height: 26px; display: inline-flex; align-items: center; justify-content: center; padding: 0 12px; border-radius: 4px; color: var(--erp-tag-warning-text); background: var(--erp-tag-warning-background); font-size: 12px; font-weight: 500; }
.editor-status-tag.verified { color: var(--erp-tag-success-text); background: var(--erp-tag-success-background); }
.heading-actions .el-button { min-width: 94px; }
.heading-actions :deep(.el-button--primary:not(.is-disabled)) { color: var(--erp-button-primary-text); background: var(--erp-button-primary-background); border-color: var(--erp-button-primary-border); }
.material-card { padding: 10px; }
.material-heading { padding: 0 2px 8px; }
.material-heading > div:first-child { gap: 12px; }
.material-heading h2 { font-family: "Noto Serif SC", "Songti SC", serif; font-size: 18px; }
.material-actions .el-button { min-height: 30px; color: var(--erp-button-secondary-text); background: var(--erp-button-secondary-background); border-color: var(--erp-button-secondary-border); }
.prototype-tube-table { --el-table-header-bg-color: var(--erp-table-header-background); --el-table-border-color: var(--erp-table-border); --el-table-row-hover-bg-color: var(--erp-table-hover); }
.prototype-tube-table :deep(th.el-table__cell), .prototype-tube-table :deep(td.el-table__cell) { height: 42px; padding: 0; font-size: 12px; }
.prototype-tube-table :deep(.el-table__body td.el-table__cell) { background: var(--erp-table-background); }
.material-detail-panel { @include detail.inset; margin-top: 10px; padding: 10px 12px 8px; }
.material-detail-panel > header { display: flex; align-items: center; gap: 18px; height: 28px; }
.material-detail-panel h3 { margin: 0; font-family: "Noto Serif SC", "Songti SC", serif; font-size: 17px; }
.material-detail-panel > header > span { color: var(--erp-color-text-secondary); font-size: 12px; }
.material-detail-panel > header > .el-button { margin-left: auto; }
.material-detail-body { display: grid; grid-template-columns: minmax(0, 1fr) 172px; gap: 12px; margin-top: 8px; }
.material-fields { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 9px; }
.material-fields label { min-width: 0; }
.material-fields label > span:first-child { display: block; margin-bottom: 5px; color: var(--erp-color-text-secondary); font-size: 11px; }
.material-fields :deep(.el-input__wrapper), .material-fields :deep(.el-select__wrapper) { min-height: 30px; padding: 1px 7px; border-radius: 3px; }
.compound-field { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
.readonly-field strong { height: 30px; display: flex; align-items: center; padding: 0 8px; box-sizing: border-box; border: 1px solid var(--erp-input-border); border-radius: 3px; color: var(--erp-input-readonly-text); background: var(--erp-input-readonly-background); font-size: 12px; font-weight: 400; }
.notes-field { grid-column: span 3; }
.calculation-result { @include detail.inset; padding: 8px 12px; }
.calculation-result h4 { margin: 0 0 9px; font-size: 12px; }
.calculation-result span, .calculation-result strong { display: block; }
.calculation-result span { margin-top: 7px; color: var(--erp-color-text-secondary); font-size: 11px; }
.calculation-result strong { margin-top: 3px; font-family: "Noto Serif SC", "Songti SC", serif; font-size: 18px; }
.material-detail-panel > p { margin: 7px 0 0; color: var(--erp-color-text-secondary); font-size: 11px; }
.bom-color-create-form { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }
.bom-color-create-form :deep(.el-form-item:last-child) { grid-column: 1 / -1; }

@media (max-width: 1400px) {
  .editor-grid { grid-template-columns: 176px minmax(0, 1fr); }
  .material-fields { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>

<style lang="scss">
.bom-line-editor-dialog .el-dialog__body { overflow-y: auto; }
.bom-line-editor-dialog .line-drawer-form { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px 16px; }
.bom-line-editor-dialog .drawer-field--wide, .bom-line-editor-dialog .drawer-calculations { grid-column: 1 / -1; }
.bom-line-editor-dialog .drawer-readonly-value { background: var(--erp-input-readonly-background); border-color: var(--erp-input-border); color: var(--erp-input-readonly-text); }
.bom-line-editor-dialog .drawer-field small { color: var(--erp-color-text-secondary); line-height: 1.5; }
.bom-line-editor-dialog .drawer-calculation-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.bom-line-editor-dialog .drawer-calculation-grid label { background: var(--erp-color-subtle); border-color: var(--erp-color-border); }
.bom-line-editor-dialog .drawer-calculation-grid label span, .bom-line-editor-dialog .drawer-calculation-grid label strong { color: var(--erp-color-text-regular); }
.bom-line-editor-dialog .app-window-dialog__footer { padding: 6px 24px 8px; }
</style>
