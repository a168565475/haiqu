<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox, useZIndex } from 'element-plus'
import { Delete, Edit, FullScreen, Plus } from '@element-plus/icons-vue'

import {
  bomLineImageUrl,
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
import AuxiliaryReferenceCreateDialog from '@/components/AuxiliaryReferenceCreateDialog.vue'
import BomLineEditorDialog from '@/components/BomLineEditorDialog.vue'
import BomLineImageSummary from '@/components/BomLineImageSummary.vue'
import BomPrintDocument from '@/components/boms/BomPrintDocument.vue'
import BomProductImage from '@/components/boms/BomProductImage.vue'
import HardwareRawMaterialCreateDialog from '@/components/HardwareRawMaterialCreateDialog.vue'
import ProductCreateDialog from '@/components/products/ProductCreateDialog.vue'
import InquiryProductDialog from '@/components/inquiries/InquiryProductDialog.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { fetchProductOptions } from '@/api/products'
import type { InquiryItem } from '@/types/inquiry'
import PinyinFilterSelect from '@/components/production/PinyinFilterSelect.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  BomAuxiliaryProductOption,
  BomDetail,
  BomDraftLineImage,
  BomEditorReferenceOptions,
  BomHardwareMaterial,
  BomHardwareMaterialGroup,
  BomLine,
  BomLineImage,
  BomLineInput,
  BomMaterialSaveOptions,
  BomMaterialSavePreview,
  BomPackagingMaterial,
  BomPlasticMaterial,
  BomProductColorOption,
  BomSemiFinishedMaterial,
  BomSection,
  BomSectionInput,
  BomSectionType,
} from '@/types/bom'
import type { ProductInformation, ProductInformationInput, ProductOptions } from '@/types/product'
import type { ProductColor } from '@/types/productionData'
import { createProductionDataRecord } from '@/api/productionData'
import { pipePlan } from '@/utils/materialFlow'
import { cuttingCalculation, cuttingCompatibilityValues, legacyPipeCuttingValues } from '@/utils/bomCuttingQuantities'
import { matchesPinyinSearch } from '@/utils/pinyinSearch'
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
const pendingMaterialSave = ref<PendingBomSave | null>(null)
const materialSavePreview = ref<BomMaterialSavePreview | null>(null)
const materialSaveError = ref('')
const materialSaveRequiresRecheck = ref(false)
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
const productConfirmDialog = ref<InstanceType<typeof InquiryProductDialog>>()
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
  },
})

function cuttingMaterial(line: BomLineInput) {
  const ownMaterial = line.material.trim()
  if (ownMaterial && ownMaterial !== '/') return line.material
  const source = fabricSourceLines.value.find((item) => line.fabric_source_line_id
    ? item.id === line.fabric_source_line_id
    : Boolean(line.fabric_source_client_key && !item.id && item.client_key === line.fabric_source_client_key))
  const sourceMaterial = source?.material.trim()
  return sourceMaterial && sourceMaterial !== '/' ? source!.material : line.material
}

const editingLineIndex = ref(-1)
const editingLineDraft = ref<BomLineInput | null>(null)
const editingLineIsNew = ref(false)
const advancingLineDrawer = ref(false)
const calculatingLine = ref(false)
let advancingLineUnlockTimer: number | undefined
const hardwarePickerVisible = ref(false)
const hardwarePickerLoading = ref(false)
const hardwarePickerError = ref('')
const hardwareGroupLoading = ref(false)
const hardwareGroupError = ref('')
const hardwareGroups = ref<BomHardwareMaterialGroup[]>([])
const hardwareGroupFilterKeyword = ref('')
const hardwarePickerMaterialName = ref('')
const hardwarePickerKeyword = ref('')
const hardwareCreateVisible = ref(false)
const plasticCreateVisible = ref(false)
const packagingCreateVisible = ref(false)
const cuttingCreateVisible = ref(false)
const hardwarePickerPage = ref(1)
const hardwarePickerPageSize = ref(50)
const hardwarePickerTotal = ref(0)
const hardwareCandidates = ref<BomHardwareMaterial[]>([])
const selectedHardware = ref<Record<string, BomHardwareMaterial>>({})
let hardwarePickerRequestId = 0
let hardwareGroupRequestId = 0
const plasticPickerVisible = ref(false)
const plasticPickerLoading = ref(false)
const plasticPickerError = ref('')
const plasticGroupLoading = ref(false)
const plasticGroupError = ref('')
const plasticGroups = ref<BomHardwareMaterialGroup[]>([])
const plasticGroupFilterKeyword = ref('')
const plasticPickerMaterialName = ref('')
const plasticPickerKeyword = ref('')
const plasticPickerPage = ref(1)
const plasticPickerPageSize = ref(50)
const plasticPickerTotal = ref(0)
const plasticCandidates = ref<BomPlasticMaterial[]>([])
const selectedPlastic = ref<Record<string, BomPlasticMaterial>>({})
let plasticPickerRequestId = 0
let plasticGroupRequestId = 0
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
const packagingPickerVisible = ref(false)
const packagingPickerLoading = ref(false)
const packagingPickerError = ref('')
const packagingGroupLoading = ref(false)
const packagingGroupError = ref('')
const packagingGroups = ref<BomHardwareMaterialGroup[]>([])
const packagingGroupFilterKeyword = ref('')
const packagingPickerMaterialName = ref('')
const packagingPickerKeyword = ref('')
const packagingPickerPage = ref(1)
const packagingPickerPageSize = ref(50)
const packagingPickerTotal = ref(0)
const packagingCandidates = ref<BomPackagingMaterial[]>([])
const selectedPackaging = ref<Record<string, BomPackagingMaterial>>({})
let packagingPickerRequestId = 0
let packagingGroupRequestId = 0
const cuttingPickerVisible = ref(false)
const cuttingPickerLoading = ref(false)
const cuttingPickerError = ref('')
const cuttingGroupLoading = ref(false)
const cuttingGroupError = ref('')
const cuttingGroups = ref<BomHardwareMaterialGroup[]>([])
const cuttingGroupFilterKeyword = ref('')
const cuttingPickerMaterialName = ref('')
const cuttingPickerKeyword = ref('')
const cuttingPickerPage = ref(1)
const cuttingPickerPageSize = ref(50)
const cuttingPickerTotal = ref(0)
const cuttingCandidates = ref<BomSemiFinishedMaterial[]>([])
const selectedCutting = ref<Record<string, BomSemiFinishedMaterial>>({})
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
let cuttingPickerRequestId = 0
let cuttingGroupRequestId = 0
const uploadingCuttingImagesLineId = ref('')
const deletingCuttingImageId = ref('')
const cleaningCuttingDraftImages = ref(false)
const initialDrawerDraftImageIds = ref<string[]>([])
const preserveDrawerDraftImagesOnClose = ref(false)
const imageManagerVisible = ref(false)
const imageManagerStandalone = ref(false)
const imageFileInput = ref<HTMLInputElement | null>(null)
const imageManagerZIndex = ref(0)
const { nextZIndex } = useZIndex()

interface FixedSectionDefinition {
  title: string
  section_type: BomSectionType
}

const fixedSectionDefinitions: FixedSectionDefinition[] = [
  { title: '管材类', section_type: 'PROFILE' },
  { title: '五金件', section_type: 'ACCESSORY' },
  { title: '塑料件类', section_type: 'ACCESSORY' },
  { title: '辅料类', section_type: 'FABRIC' },
  { title: '面料类', section_type: 'FABRIC' },
  { title: '包材类', section_type: 'ACCESSORY' },
  { title: '裁剪明细', section_type: 'FABRIC' },
]

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
              ? '按片填写单个用量，按套流转；补齐裁片量、单个用量和每成品套数后自动计算'
              : '材质、规格以来源原材料为准；切割长度、单耗和每根切割支数填写整数'
))

function filteredMaterialGroups(groups: BomHardwareMaterialGroup[], keyword: string) {
  return groups.filter((group) => matchesPinyinSearch(group.material_name, group.pinyin_search, keyword))
}

const visibleHardwareGroups = computed(() => filteredMaterialGroups(hardwareGroups.value, hardwareGroupFilterKeyword.value))
const visiblePlasticGroups = computed(() => filteredMaterialGroups(plasticGroups.value, plasticGroupFilterKeyword.value))
const visiblePackagingGroups = computed(() => filteredMaterialGroups(packagingGroups.value, packagingGroupFilterKeyword.value))
const visibleCuttingGroups = computed(() => filteredMaterialGroups(cuttingGroups.value, cuttingGroupFilterKeyword.value))
const selectedHardwareCount = computed(() => Object.keys(selectedHardware.value).length)
const hardwarePageSelectedCount = computed(() => hardwareCandidates.value.filter((item) => selectedHardware.value[item.id]).length)
const hardwarePageAllSelected = computed(() => (
  hardwareCandidates.value.length > 0 && hardwarePageSelectedCount.value === hardwareCandidates.value.length
))
const hardwarePageSelectionIndeterminate = computed(() => (
  hardwarePageSelectedCount.value > 0 && !hardwarePageAllSelected.value
))
const selectedPlasticCount = computed(() => Object.keys(selectedPlastic.value).length)
const plasticPageSelectedCount = computed(() => plasticCandidates.value.filter((item) => selectedPlastic.value[item.id]).length)
const plasticPageAllSelected = computed(() => (
  plasticCandidates.value.length > 0 && plasticPageSelectedCount.value === plasticCandidates.value.length
))
const plasticPageSelectionIndeterminate = computed(() => (
  plasticPageSelectedCount.value > 0 && !plasticPageAllSelected.value
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
const selectedPackagingCount = computed(() => Object.keys(selectedPackaging.value).length)
const packagingPageSelectedCount = computed(() => packagingCandidates.value.filter((item) => selectedPackaging.value[item.id]).length)
const packagingPageAllSelected = computed(() => (
  packagingCandidates.value.length > 0 && packagingPageSelectedCount.value === packagingCandidates.value.length
))
const packagingPageSelectionIndeterminate = computed(() => (
  packagingPageSelectedCount.value > 0 && !packagingPageAllSelected.value
))
const selectedCuttingCount = computed(() => Object.keys(selectedCutting.value).length)
const cuttingPageSelectedCount = computed(() => cuttingCandidates.value.filter((item) => selectedCutting.value[item.id]).length)
const cuttingPageAllSelected = computed(() => (
  cuttingCandidates.value.length > 0 && cuttingPageSelectedCount.value === cuttingCandidates.value.length
))
const cuttingPageSelectionIndeterminate = computed(() => (
  cuttingPageSelectedCount.value > 0 && !cuttingPageAllSelected.value
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
    line.fabric_meters_per_piece = null
    line.cutting_sets_per_product = null
  }
}

function blankLine(defaultUnit = ''): BomLineInput {
  return {
    client_key: createDraftKey(),
    category: '', material: '', part_name: '', specification: '', raw_material: '', length_value: '',
    unit_consumption: '', total_consumption: '', unit: defaultUnit, hardness: '', original_material_length: '',
    branch_count: '', budget_quantity: '', inventory_quantity: '', weight_grams: '', cut_piece_quantity: '',
    purchase_consumption: '', source_order_quantity: '', total_purchase_quantity: '', notes: '',
    tube_shape: '', tube_diameter: '', tube_thickness: '', tube_coating_color: '',
    coating_unit_area_sqm: '', purchase_unit_weight_kg: '', tube_cut_piece_count: '',
    source_inventory_material_id: null,
    source_raw_material_id: null, hardware_material_number: '', hardware_color: '', hardware_flow_unit: '',
    unit_material_weight_kg: '', powder_coating_color: '', powder_coating_unit_area_sqm: '',
    plastic_material_number: '', plastic_color: '',
    source_packaging_material_id: null, packaging_material_number: '', packaging_color: '', units_per_box: '',
    source_cutting_material_id: null, cutting_material_number: '', cutting_item_type: '',
    cutting_item_type_display: '', cutting_category: '', cutting_color: '', images: [],
    draft_key: '', draft_images: [],
    source_accessory_product_name_id: null, source_accessory_specification_id: null,
    source_accessory_color_id: null, source_accessory_material_id: null, accessory_color: '',
    source_fabric_material_id: null, source_fabric_specification_id: null,
    source_fabric_width_id: null, source_product_color_id: null, fabric_width: '',
    fabric_color_card: '', fabric_color_code: '', fabric_color_name: '',
  }
}

function editableLine(line: BomLine): BomLineInput {
  return {
    id: line.id,
    category: line.category,
    material: line.cutting_material_original ?? line.material,
    part_name: line.part_name,
    specification: line.specification,
    raw_material: line.raw_material,
    length_value: line.length_value,
    unit_consumption: line.unit_consumption,
    total_consumption: line.total_consumption,
    unit: line.unit,
    hardness: line.hardness,
    original_material_length: line.original_material_length,
    branch_count: line.branch_count,
    budget_quantity: line.budget_quantity,
    inventory_quantity: line.inventory_quantity,
    weight_grams: line.weight_grams,
    cut_piece_quantity: line.cut_piece_quantity,
    purchase_consumption: line.purchase_consumption,
    source_order_quantity: line.source_order_quantity,
    total_purchase_quantity: line.total_purchase_quantity,
    notes: line.notes,
    tube_shape: line.tube_shape,
    tube_diameter: line.tube_diameter,
    tube_thickness: line.tube_thickness,
    tube_coating_color: line.tube_coating_color,
    coating_unit_area_sqm: line.coating_unit_area_sqm,
    purchase_unit_weight_kg: line.purchase_unit_weight_kg,
    tube_cut_piece_count: line.tube_cut_piece_count,
    source_inventory_material_id: line.source_inventory_material_id || null,
    fabric_source_line_id: line.fabric_source_line_id || null,
    fabric_meters_per_set: line.fabric_meters_per_set || null,
    cutting_pieces_per_set: line.cutting_pieces_per_set ?? null,
    fabric_meters_per_piece: line.fabric_meters_per_piece ?? null,
    cutting_sets_per_product: line.cutting_sets_per_product ?? null,
    source_raw_material_id: line.source_raw_material_id || null,
    hardware_material_number: line.hardware_material_number || '',
    hardware_color: line.hardware_color || '',
    hardware_flow_unit: line.hardware_flow_unit || '',
    unit_material_weight_kg: line.unit_material_weight_kg || '',
    powder_coating_color: line.powder_coating_color || '',
    powder_coating_unit_area_sqm: line.powder_coating_unit_area_sqm || '',
    plastic_material_number: line.plastic_material_number || '',
    plastic_color: line.plastic_color || '',
    source_packaging_material_id: line.source_packaging_material_id || null,
    packaging_material_number: line.packaging_material_number || '',
    packaging_color: line.packaging_color || '',
    units_per_box: line.units_per_box || '',
    source_cutting_material_id: line.source_cutting_material_id || null,
    cutting_material_number: line.cutting_material_number || '',
    cutting_item_type: line.cutting_item_type || '',
    cutting_item_type_display: line.cutting_item_type_display || '',
    cutting_category: line.cutting_category || '',
    cutting_color: line.cutting_color || '',
    images: [...(line.images || [])],
    draft_key: '',
    draft_images: [],
    source_accessory_product_name_id: line.source_accessory_product_name_id || null,
    source_accessory_specification_id: line.source_accessory_specification_id || null,
    source_accessory_color_id: line.source_accessory_color_id || null,
    source_accessory_material_id: line.source_accessory_material_id || null,
    accessory_color: line.accessory_color || '',
    source_fabric_material_id: line.source_fabric_material_id || null,
    source_fabric_specification_id: line.source_fabric_specification_id || null,
    source_fabric_width_id: line.source_fabric_width_id || null,
    source_product_color_id: line.source_product_color_id || null,
    fabric_width: line.fabric_width || '',
    fabric_color_card: line.fabric_color_card || '',
    fabric_color_code: line.fabric_color_code || '',
    fabric_color_name: line.fabric_color_name || '',
  }
}

function editableSection(section: BomSection): BomSectionInput {
  const lines = section.lines.map((line) => {
    const editable = editableLine(line)
    if (section.section_type === 'PROFILE') {
      if (!editable.unit) editable.unit = 'PCS'
      normalizeTubeCutPieceCount(editable)
    }
    return editable
  })
  return {
    id: section.id,
    section_type: section.section_type,
    title: section.title,
    lines: lines.length || section.section_type !== 'PROFILE' ? lines : [blankLine('根')],
  }
}

function defaultTubeSection(): BomSectionInput {
  return { section_type: 'PROFILE', title: '管材类', lines: [blankLine('根')] }
}

function emptyFixedSection(definition: FixedSectionDefinition): BomSectionInput {
  return definition.section_type === 'PROFILE'
    ? defaultTubeSection()
    : { section_type: definition.section_type, title: definition.title, lines: [] }
}

function matchingFixedTitle(section: BomSectionInput, usedTitles: Set<string>) {
  if (section.section_type === 'PROFILE') return '管材类'
  const title = section.title.replace(/\s+/g, '')
  const keywordMatches = [
    { title: '裁剪明细', pattern: /裁剪|裁片/ },
    { title: '塑料件类', pattern: /塑料/ },
    { title: '包材类', pattern: /包材|包装/ },
    { title: '五金件', pattern: /五金|配件/ },
    { title: '面料类', pattern: /面料|面辅料/ },
    { title: '辅料类', pattern: /辅料/ },
  ]
  const keywordMatch = keywordMatches.find((item) => item.pattern.test(title) && !usedTitles.has(item.title))
  if (keywordMatch) return keywordMatch.title
  const candidates = section.section_type === 'FABRIC'
    ? ['面料类', '辅料类', '裁剪明细']
    : ['五金件', '塑料件类', '包材类']
  return candidates.find((candidate) => !usedTitles.has(candidate)) || section.title
}

function fixedTitleFromLine(line: BomLineInput, fallbackTitle: string) {
  if (line.source_cutting_material_id || line.cutting_material_number || /裁剪|裁片/.test(line.category)) return '裁剪明细'
  if (line.source_packaging_material_id || line.packaging_material_number || line.units_per_box || /包材|包装/.test(line.category)) return '包材类'
  if (line.hardware_material_number || /五金/.test(line.category)) return '五金件'
  if (line.plastic_material_number || /塑料/.test(line.category)) return '塑料件类'
  if (line.source_fabric_material_id || line.fabric_width || line.fabric_color_card || line.fabric_color_code || line.fabric_color_name || /面料/.test(line.category)) return '面料类'
  if (line.source_accessory_product_name_id || line.source_accessory_material_id || line.accessory_color || /辅料/.test(line.category)) return '辅料类'
  return fallbackTitle
}

function withFixedSections(sourceSections: BomSection[]) {
  const usedTitles = new Set<string>()
  const fixedOrder = new Map(fixedSectionDefinitions.map((item, index) => [item.title, index]))
  const sectionByTitle = new Map<string, BomSectionInput>()
  for (const sourceSection of sourceSections) {
    const section = editableSection(sourceSection)
    const fixedTitle = matchingFixedTitle(section, usedTitles)
    if (!fixedOrder.has(fixedTitle)) continue
    usedTitles.add(fixedTitle)
    const canonicalSection: BomSectionInput = {
      ...section,
      title: fixedTitle,
      lines: [...(sectionByTitle.get(fixedTitle)?.lines || [])],
    }
    sectionByTitle.set(fixedTitle, canonicalSection)
    for (const line of section.lines) {
      const lineTitle = fixedTitleFromLine(line, fixedTitle)
      const target = sectionByTitle.get(lineTitle)
      if (target) target.lines.push(line)
      else {
        const definition = fixedSectionDefinitions.find((item) => item.title === lineTitle)
        if (definition) sectionByTitle.set(lineTitle, { section_type: definition.section_type, title: lineTitle, lines: [line] })
      }
    }
  }
  for (const definition of fixedSectionDefinitions) {
    if (!sectionByTitle.has(definition.title)) sectionByTitle.set(definition.title, emptyFixedSection(definition))
  }
  const tubeSection = sectionByTitle.get('管材类')
  if (tubeSection && !tubeSection.lines.length) tubeSection.lines.push(blankLine('根'))
  const preserved = [...sectionByTitle.values()]
  return preserved.sort((left, right) => (
    (fixedOrder.get(left.title) ?? fixedSectionDefinitions.length)
    - (fixedOrder.get(right.title) ?? fixedSectionDefinitions.length)
  ))
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

function filterHardwareGroups(value: string) {
  hardwareGroupFilterKeyword.value = value
}

function filterPlasticGroups(value: string) {
  plasticGroupFilterKeyword.value = value
}

function filterPackagingGroups(value: string) {
  packagingGroupFilterKeyword.value = value
}

function filterCuttingGroups(value: string) {
  cuttingGroupFilterKeyword.value = value
}

function clearHardwareGroupFilter(visible: boolean) {
  if (!visible) hardwareGroupFilterKeyword.value = ''
}

function clearPlasticGroupFilter(visible: boolean) {
  if (!visible) plasticGroupFilterKeyword.value = ''
}

function clearPackagingGroupFilter(visible: boolean) {
  if (!visible) packagingGroupFilterKeyword.value = ''
}

function clearCuttingGroupFilter(visible: boolean) {
  if (!visible) cuttingGroupFilterKeyword.value = ''
}

async function loadHardwareGroups() {
  const requestId = ++hardwareGroupRequestId
  hardwareGroupLoading.value = true
  hardwareGroupError.value = ''
  try {
    hardwareGroups.value = await fetchBomHardwareMaterialGroups()
  } catch (error) {
    if (requestId !== hardwareGroupRequestId) return
    hardwareGroups.value = []
    hardwareGroupError.value = apiError(error, '五金品名分组加载失败，请稍后重试。')
  } finally {
    if (requestId === hardwareGroupRequestId) hardwareGroupLoading.value = false
  }
}

async function loadHardwareCandidates() {
  const requestId = ++hardwarePickerRequestId
  hardwarePickerLoading.value = true
  hardwarePickerError.value = ''
  try {
    const response = await fetchBomHardwareMaterials({
      page: hardwarePickerPage.value,
      page_size: hardwarePickerPageSize.value,
      q: hardwarePickerKeyword.value.trim() || undefined,
      material_name: hardwarePickerMaterialName.value || undefined,
    })
    if (requestId !== hardwarePickerRequestId) return
    hardwareCandidates.value = withPendingMaterials('hardware', response.data, hardwarePickerKeyword.value, hardwarePickerMaterialName.value)
    hardwarePickerTotal.value = response.meta.total
  } catch (error) {
    if (requestId !== hardwarePickerRequestId) return
    hardwareCandidates.value = withPendingMaterials('hardware', [], hardwarePickerKeyword.value, hardwarePickerMaterialName.value)
    hardwarePickerTotal.value = 0
    hardwarePickerError.value = apiError(error, '五金数据加载失败，请稍后重试。')
  } finally {
    if (requestId === hardwarePickerRequestId) hardwarePickerLoading.value = false
  }
}

function openHardwarePicker() {
  if (!canEdit.value || !isHardwareSection.value) return
  hardwarePickerKeyword.value = ''
  hardwarePickerMaterialName.value = ''
  hardwareGroupFilterKeyword.value = ''
  hardwarePickerPage.value = 1
  selectedHardware.value = {}
  hardwarePickerVisible.value = true
  void Promise.all([loadHardwareGroups(), loadHardwareCandidates()])
}

function searchHardwareCandidates() {
  hardwarePickerPage.value = 1
  void loadHardwareCandidates()
}

function changeHardwarePage(page: number) {
  hardwarePickerPage.value = page
  void loadHardwareCandidates()
}

function toggleHardwareCandidate(item: BomHardwareMaterial, selected: boolean | string | number) {
  const next = { ...selectedHardware.value }
  if (Boolean(selected)) next[item.id] = item
  else delete next[item.id]
  selectedHardware.value = next
}

function toggleHardwareRow(item: BomHardwareMaterial) {
  toggleHardwareCandidate(item, !selectedHardware.value[item.id])
}

function hardwarePickerRowClass({ row }: { row: BomHardwareMaterial }) {
  return selectedHardware.value[row.id] ? 'is-picker-selected' : ''
}

function toggleHardwarePage(selected: boolean | string | number) {
  const next = { ...selectedHardware.value }
  for (const item of hardwareCandidates.value) {
    if (Boolean(selected)) next[item.id] = item
    else delete next[item.id]
  }
  selectedHardware.value = next
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

function confirmHardwareSelection() {
  const targetSection = activeSection.value
  if (!targetSection || targetSection.title !== '五金件') {
    ElMessage.error('当前五金件分区已变化，请关闭选择窗口后重试。')
    return
  }
  const chosen = Object.values(selectedHardware.value)
  if (!chosen.length) {
    ElMessage.warning('请至少选择一条五金数据。')
    return
  }
  const existingSourceIds = new Set(targetSection.lines.map((line) => line.pending_raw_material ? line.client_key : line.source_raw_material_id).filter(Boolean))
  const newLines = chosen.filter((item) => !existingSourceIds.has(item.id)).map(hardwareLine)
  if (!newLines.length) {
    ElMessage.info('所选五金数据已在当前分区中。')
    return
  }
  targetSection.lines.push(...newLines)
  hardwarePickerVisible.value = false
  const skippedCount = chosen.length - newLines.length
  ElMessage.success(`已添加 ${newLines.length} 条五金数据${skippedCount ? `，跳过 ${skippedCount} 条重复数据` : ''}。`)
}

function resetHardwarePicker() {
  hardwarePickerRequestId += 1
  hardwareGroupRequestId += 1
  hardwarePickerLoading.value = false
  hardwareGroupLoading.value = false
  hardwarePickerError.value = ''
  hardwareGroupError.value = ''
  hardwareCandidates.value = []
  hardwareGroups.value = []
  hardwarePickerTotal.value = 0
  hardwarePickerMaterialName.value = ''
  hardwareGroupFilterKeyword.value = ''
  hardwareCreateVisible.value = false
  selectedHardware.value = {}
}

async function loadPlasticCandidates() {
  const requestId = ++plasticPickerRequestId
  plasticPickerLoading.value = true
  plasticPickerError.value = ''
  try {
    const response = await fetchBomPlasticMaterials({
      page: plasticPickerPage.value,
      page_size: plasticPickerPageSize.value,
      q: plasticPickerKeyword.value.trim() || undefined,
      material_name: plasticPickerMaterialName.value || undefined,
    })
    if (requestId !== plasticPickerRequestId) return
    plasticCandidates.value = withPendingMaterials('plastic', response.data, plasticPickerKeyword.value, plasticPickerMaterialName.value)
    plasticPickerTotal.value = response.meta.total
  } catch (error) {
    if (requestId !== plasticPickerRequestId) return
    plasticCandidates.value = withPendingMaterials('plastic', [], plasticPickerKeyword.value, plasticPickerMaterialName.value)
    plasticPickerTotal.value = 0
    plasticPickerError.value = apiError(error, '塑料件数据加载失败，请稍后重试。')
  } finally {
    if (requestId === plasticPickerRequestId) plasticPickerLoading.value = false
  }
}

async function loadPlasticGroups() {
  const requestId = ++plasticGroupRequestId
  plasticGroupLoading.value = true
  plasticGroupError.value = ''
  try {
    plasticGroups.value = await fetchBomPlasticMaterialGroups()
  } catch (error) {
    if (requestId !== plasticGroupRequestId) return
    plasticGroups.value = []
    plasticGroupError.value = apiError(error, '塑料件品名分组加载失败，请稍后重试。')
  } finally {
    if (requestId === plasticGroupRequestId) plasticGroupLoading.value = false
  }
}

function openPlasticPicker() {
  if (!canEdit.value || !isPlasticSection.value) return
  plasticPickerKeyword.value = ''
  plasticPickerMaterialName.value = ''
  plasticGroupFilterKeyword.value = ''
  plasticPickerPage.value = 1
  selectedPlastic.value = {}
  plasticPickerVisible.value = true
  void Promise.all([loadPlasticGroups(), loadPlasticCandidates()])
}

function searchPlasticCandidates() {
  plasticPickerPage.value = 1
  void loadPlasticCandidates()
}

function changePlasticPage(page: number) {
  plasticPickerPage.value = page
  void loadPlasticCandidates()
}

function togglePlasticCandidate(item: BomPlasticMaterial, selected: boolean | string | number) {
  const next = { ...selectedPlastic.value }
  if (Boolean(selected)) next[item.id] = item
  else delete next[item.id]
  selectedPlastic.value = next
}

function togglePlasticRow(item: BomPlasticMaterial) {
  togglePlasticCandidate(item, !selectedPlastic.value[item.id])
}

function plasticPickerRowClass({ row }: { row: BomPlasticMaterial }) {
  return selectedPlastic.value[row.id] ? 'is-picker-selected' : ''
}

function togglePlasticPage(selected: boolean | string | number) {
  const next = { ...selectedPlastic.value }
  for (const item of plasticCandidates.value) {
    if (Boolean(selected)) next[item.id] = item
    else delete next[item.id]
  }
  selectedPlastic.value = next
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
  const chosen = Object.values(selectedPlastic.value)
  if (!chosen.length) {
    ElMessage.warning('请至少选择一条塑料件数据。')
    return
  }
  const existingSourceIds = new Set(targetSection.lines.map((line) => line.pending_raw_material ? line.client_key : line.source_raw_material_id).filter(Boolean))
  const newLines = chosen.filter((item) => !existingSourceIds.has(item.id)).map(plasticLine)
  if (!newLines.length) {
    ElMessage.info('所选塑料件数据已在当前分区中。')
    return
  }
  targetSection.lines.push(...newLines)
  plasticPickerVisible.value = false
  const skippedCount = chosen.length - newLines.length
  ElMessage.success(`已添加 ${newLines.length} 条塑料件数据${skippedCount ? `，跳过 ${skippedCount} 条重复数据` : ''}。`)
}

function resetPlasticPicker() {
  plasticPickerRequestId += 1
  plasticGroupRequestId += 1
  plasticPickerLoading.value = false
  plasticGroupLoading.value = false
  plasticPickerError.value = ''
  plasticGroupError.value = ''
  plasticCandidates.value = []
  plasticGroups.value = []
  plasticPickerTotal.value = 0
  plasticPickerMaterialName.value = ''
  plasticGroupFilterKeyword.value = ''
  selectedPlastic.value = {}
}

async function loadPackagingGroups() {
  const requestId = ++packagingGroupRequestId
  packagingGroupLoading.value = true
  packagingGroupError.value = ''
  try {
    packagingGroups.value = await fetchBomPackagingMaterialGroups()
  } catch (error) {
    if (requestId !== packagingGroupRequestId) return
    packagingGroups.value = []
    packagingGroupError.value = apiError(error, '包材品名分组加载失败，请稍后重试。')
  } finally {
    if (requestId === packagingGroupRequestId) packagingGroupLoading.value = false
  }
}

async function loadPackagingCandidates() {
  const requestId = ++packagingPickerRequestId
  packagingPickerLoading.value = true
  packagingPickerError.value = ''
  try {
    const response = await fetchBomPackagingMaterials({
      page: packagingPickerPage.value,
      page_size: packagingPickerPageSize.value,
      q: packagingPickerKeyword.value.trim() || undefined,
      material_name: packagingPickerMaterialName.value || undefined,
    })
    if (requestId !== packagingPickerRequestId) return
    packagingCandidates.value = withPendingMaterials('packaging', response.data, packagingPickerKeyword.value, packagingPickerMaterialName.value)
    packagingPickerTotal.value = response.meta.total
  } catch (error) {
    if (requestId !== packagingPickerRequestId) return
    packagingCandidates.value = withPendingMaterials('packaging', [], packagingPickerKeyword.value, packagingPickerMaterialName.value)
    packagingPickerTotal.value = 0
    packagingPickerError.value = apiError(error, '包材数据加载失败，请稍后重试。')
  } finally {
    if (requestId === packagingPickerRequestId) packagingPickerLoading.value = false
  }
}

function openPackagingPicker() {
  if (!canEdit.value || !isPackagingSection.value) return
  packagingPickerMaterialName.value = ''
  packagingPickerKeyword.value = ''
  packagingGroupFilterKeyword.value = ''
  packagingPickerPage.value = 1
  selectedPackaging.value = {}
  packagingPickerVisible.value = true
  void Promise.all([loadPackagingGroups(), loadPackagingCandidates()])
}

function searchPackagingCandidates() {
  packagingPickerPage.value = 1
  void loadPackagingCandidates()
}

function changePackagingPage(page: number) {
  packagingPickerPage.value = page
  void loadPackagingCandidates()
}

function togglePackagingCandidate(item: BomPackagingMaterial, selected: boolean | string | number) {
  const next = { ...selectedPackaging.value }
  if (Boolean(selected)) next[item.id] = item
  else delete next[item.id]
  selectedPackaging.value = next
}

function togglePackagingRow(item: BomPackagingMaterial) {
  togglePackagingCandidate(item, !selectedPackaging.value[item.id])
}

function packagingPickerRowClass({ row }: { row: BomPackagingMaterial }) {
  return selectedPackaging.value[row.id] ? 'is-picker-selected' : ''
}

function togglePackagingPage(selected: boolean | string | number) {
  const next = { ...selectedPackaging.value }
  for (const item of packagingCandidates.value) {
    if (Boolean(selected)) next[item.id] = item
    else delete next[item.id]
  }
  selectedPackaging.value = next
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
  const chosen = Object.values(selectedPackaging.value)
  if (!chosen.length) {
    ElMessage.warning('请至少选择一条包材数据。')
    return
  }
  const existingSourceIds = new Set(targetSection.lines.map((line) => line.pending_raw_material ? line.client_key : line.source_packaging_material_id).filter(Boolean))
  const newLines = chosen.filter((item) => !existingSourceIds.has(item.id)).map(packagingLine)
  if (!newLines.length) {
    ElMessage.info('所选包材数据已在当前分区中。')
    return
  }
  targetSection.lines.push(...newLines)
  packagingPickerVisible.value = false
  const skippedCount = chosen.length - newLines.length
  ElMessage.success(`已添加 ${newLines.length} 条包材数据${skippedCount ? `，跳过 ${skippedCount} 条重复数据` : ''}，请填写箱数和单个用量。`)
}

function resetPackagingPicker() {
  packagingPickerRequestId += 1
  packagingGroupRequestId += 1
  packagingPickerLoading.value = false
  packagingGroupLoading.value = false
  packagingPickerError.value = ''
  packagingGroupError.value = ''
  packagingCandidates.value = []
  packagingGroups.value = []
  packagingPickerTotal.value = 0
  packagingPickerMaterialName.value = ''
  packagingPickerKeyword.value = ''
  packagingGroupFilterKeyword.value = ''
  selectedPackaging.value = {}
}

async function loadCuttingGroups() {
  const requestId = ++cuttingGroupRequestId
  cuttingGroupLoading.value = true
  cuttingGroupError.value = ''
  try {
    cuttingGroups.value = await fetchBomSemiFinishedMaterialGroups()
  } catch (error) {
    if (requestId !== cuttingGroupRequestId) return
    cuttingGroups.value = []
    cuttingGroupError.value = apiError(error, '裁剪品名分组加载失败，请稍后重试。')
  } finally {
    if (requestId === cuttingGroupRequestId) cuttingGroupLoading.value = false
  }
}

async function loadCuttingCandidates() {
  const requestId = ++cuttingPickerRequestId
  cuttingPickerLoading.value = true
  cuttingPickerError.value = ''
  try {
    const response = await fetchBomSemiFinishedMaterials({
      page: cuttingPickerPage.value,
      page_size: cuttingPickerPageSize.value,
      q: cuttingPickerKeyword.value.trim() || undefined,
      material_name: cuttingPickerMaterialName.value || undefined,
    })
    if (requestId !== cuttingPickerRequestId) return
    cuttingCandidates.value = withPendingMaterials('cutting', response.data, cuttingPickerKeyword.value, cuttingPickerMaterialName.value)
    cuttingPickerTotal.value = response.meta.total
  } catch (error) {
    if (requestId !== cuttingPickerRequestId) return
    cuttingCandidates.value = withPendingMaterials('cutting', [], cuttingPickerKeyword.value, cuttingPickerMaterialName.value)
    cuttingPickerTotal.value = 0
    cuttingPickerError.value = apiError(error, '裁剪数据加载失败，请稍后重试。')
  } finally {
    if (requestId === cuttingPickerRequestId) cuttingPickerLoading.value = false
  }
}

function openCuttingPicker() {
  if (!canEdit.value || !isCuttingSection.value) return
  cuttingPickerMaterialName.value = ''
  cuttingPickerKeyword.value = ''
  cuttingGroupFilterKeyword.value = ''
  cuttingPickerPage.value = 1
  selectedCutting.value = {}
  cuttingPickerVisible.value = true
  void Promise.all([loadCuttingGroups(), loadCuttingCandidates()])
}

function searchCuttingCandidates() {
  cuttingPickerPage.value = 1
  void loadCuttingCandidates()
}

function changeCuttingPage(page: number) {
  cuttingPickerPage.value = page
  void loadCuttingCandidates()
}

function toggleCuttingCandidate(item: BomSemiFinishedMaterial, selected: boolean | string | number) {
  const next = { ...selectedCutting.value }
  if (Boolean(selected)) next[item.id] = item
  else delete next[item.id]
  selectedCutting.value = next
}

function toggleCuttingRow(item: BomSemiFinishedMaterial) {
  toggleCuttingCandidate(item, !selectedCutting.value[item.id])
}

function cuttingPickerRowClass({ row }: { row: BomSemiFinishedMaterial }) {
  return selectedCutting.value[row.id] ? 'is-picker-selected' : ''
}

function toggleCuttingPage(selected: boolean | string | number) {
  const next = { ...selectedCutting.value }
  for (const item of cuttingCandidates.value) {
    if (Boolean(selected)) next[item.id] = item
    else delete next[item.id]
  }
  selectedCutting.value = next
}

function createDraftKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  const bytes = new Uint8Array(16)
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes)
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256)
  bytes[6] = ((bytes[6] || 0) & 0x0f) | 0x40
  bytes[8] = ((bytes[8] || 0) & 0x3f) | 0x80
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
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
  const chosen = Object.values(selectedCutting.value)
  if (!chosen.length) {
    ElMessage.warning('请至少选择一条裁剪数据。')
    return
  }
  const existingSourceIds = new Set(targetSection.lines.map((line) => line.pending_raw_material ? line.client_key : line.source_cutting_material_id).filter(Boolean))
  const newLines = chosen.filter((item) => !existingSourceIds.has(item.id)).map(cuttingLine)
  if (!newLines.length) {
    ElMessage.info('所选裁剪数据已在当前分区中。')
    return
  }
  targetSection.lines.push(...newLines)
  cuttingPickerVisible.value = false
  // 新增裁剪行立即打开编辑窗口，先补齐来源面料和三项用量，避免新增行停留在不可保存的半成品状态。
  openLineDrawer(targetSection.lines.length - newLines.length)
  const skippedCount = chosen.length - newLines.length
  ElMessage.success(`已添加 ${newLines.length} 条裁剪数据，请补齐参数后保存 BOM${skippedCount ? `；跳过 ${skippedCount} 条重复数据` : ''}。`)
}

function resetCuttingPicker() {
  cuttingPickerRequestId += 1
  cuttingGroupRequestId += 1
  cuttingPickerLoading.value = false
  cuttingGroupLoading.value = false
  cuttingPickerError.value = ''
  cuttingGroupError.value = ''
  cuttingCandidates.value = []
  cuttingGroups.value = []
  cuttingPickerTotal.value = 0
  cuttingPickerMaterialName.value = ''
  cuttingPickerKeyword.value = ''
  cuttingGroupFilterKeyword.value = ''
  selectedCutting.value = {}
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

function waitBeforeBomReload(attempt: number) {
  return new Promise<void>((resolve) => {
    const retryDelays = [0, 750, 1500, 2500]
    window.setTimeout(resolve, retryDelays[attempt] ?? 2500)
  })
}

async function fetchBomForEditWithRetry(bomId: string) {
  const maximumAttempts = 4
  for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
    try {
      return await fetchBomForEdit(bomId)
    } catch (error) {
      if (!isTemporaryBomLoadError(error) || attempt === maximumAttempts) throw error
      await waitBeforeBomReload(attempt)
    }
  }
  throw new Error('BOM 加载重试失败。')
}

async function loadBom() {
  const bomId = String(route.params.bomId || '')
  if (!bomId) {
    errorMessage.value = '缺少 BOM 编号。'
    loading.value = false
    return
  }
  loading.value = true
  errorMessage.value = ''
  let shouldPromptQuantitySync = false
  try {
    const result = await fetchBomForEditWithRetry(bomId)
    applyVersioned(result)
    shouldPromptQuantitySync = result.data.is_order_quantity_outdated || result.data.is_order_product_outdated
  } catch (error) {
    errorMessage.value = apiError(error)
  } finally {
    loading.value = false
  }
  if (bom.value && !bom.value.product_information_confirmed) openProductConfirmDialog()
  if (shouldPromptQuantitySync) void requestOrderQuantitySync(true)
}

async function requestOrderQuantitySync(automatic = false) {
  const currentBom = bom.value
  if (!(currentBom?.is_order_quantity_outdated || currentBom?.is_order_product_outdated) || !canEdit.value || syncingQuantity.value) return
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

  syncingQuantity.value = true
  try {
    const result = await syncBomOrderQuantity(currentBom.id, etag.value)
    const targetBomId = result.data.id
    applyVersioned(result)
    quantityReason.value = ''
    if (targetBomId !== String(route.params.bomId || '')) {
      await router.replace({ name: 'bom-edit', params: { bomId: targetBomId } })
    }
    ElMessage.success('订单信息已同步，BOM 用量已按最新数量重新计算。')
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    syncingQuantity.value = false
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

function sortedLineImages(line: BomLineInput) {
  return displayLineImages(line).sort((left, right) => left.position - right.position)
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
  if (!imageManagerIsBusy() && editingLineDraft.value && displayLineImages(editingLineDraft.value).length < 20) {
    imageFileInput.value?.click()
  }
}

function resetImageManager() {
  imageFileInput.value = null
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

function fileSizeText(sizeBytes: number) {
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) return '0 KB'
  if (sizeBytes < 1024 * 1024) return `${Math.max(1, Math.round(sizeBytes / 1024))} KB`
  return `${(sizeBytes / 1024 / 1024).toFixed(1)} MB`
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
    const isPipeLine = isPipeCuttingLine(line)
    const hasFabricSource = fabricSourceLines.value.some((item) => line.fabric_source_line_id
      ? item.id === line.fabric_source_line_id
      : Boolean(line.fabric_source_client_key && !item.id && item.client_key === line.fabric_source_client_key))
    if (!isPipeLine && !hasFabricSource) return `${prefix}请选择当前 BOM 中的来源面料。`
    const calculation = cuttingQuantities(line)
    if (calculation.error) return `${prefix}${calculation.error}`
    if (calculation.mode === 'legacy') {
      if (!line.id) return `${prefix}请填写裁片量（片/套）、单个用量（米/片）和每成品套数。`
      const savedLine = bom.value?.sections.flatMap(item => item.lines).find(item => item.id === line.id)
      if (savedLine && cuttingCalculation(savedLine, bom.value?.order_quantity).mode !== 'legacy') return `${prefix}已采用片/套用量，不能清空全部新参数退回旧口径。`
      const value = String(line.fabric_meters_per_set || '').trim()
      if (!/^\d{1,14}(?:\.\d{1,4})?$/.test(value) || Number(value) <= 0) return `${prefix}请保留有效的原每套耗米，或补齐三项新参数。`
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
  if (targetSection.title === '裁剪明细') syncCuttingValues(editingLineDraft.value)
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
      if (section.title === '裁剪明细') syncCuttingValues(line)
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

function materialLocationGroups(item: BomMaterialSavePreview['new_materials'][number]) {
  const groups = new Map<string, number[]>()
  for (const location of item.locations) {
    const rows = groups.get(location.section_title) || []
    if (!rows.includes(location.line_number)) rows.push(location.line_number)
    groups.set(location.section_title, rows)
  }
  return Array.from(groups, ([section, rows]) => ({ section, rows: rows.join('、') }))
}

function cancelMaterialSave() {
  if (saving.value || verifying.value) return
  pendingMaterialSave.value = null
  materialSavePreview.value = null
  materialSaveError.value = ''
  materialSaveRequiresRecheck.value = false
}

async function writeMaterialSave(pending: PendingBomSave, confirmationToken?: string) {
  try {
    const options = { ...pending.options, ...(confirmationToken ? { confirmation_token: confirmationToken } : {}) }
    const result = await saveBomDraft(pending.bomId, pending.sections, pending.etag, options)
    applyVersioned(result)
    pendingRawMaterials.value = {}
    pendingMaterialSave.value = null
    materialSavePreview.value = null
    if (pending.showMessage) ElMessage.success(pending.options.intent === 'verify'
      ? 'BOM 已提交。'
      : pending.deletedCount ? `BOM 草稿已保存，已删除 ${pending.deletedCount} 条旧明细。` : 'BOM 草稿已保存。')
    return true
  } catch (error) {
    materialSaveError.value = apiError(error)
    if ((error as { response?: { status?: number } })?.response?.status === 409) materialSaveRequiresRecheck.value = true
    ElMessage.error(materialSaveError.value)
    return false
  }
}

async function startMaterialSave(intent: 'draft' | 'verify', showMessage = true) {
  if (!bom.value || saving.value || verifying.value || pendingMaterialSave.value) return false
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
  materialSaveError.value = ''
  materialSaveRequiresRecheck.value = false
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
      materialSavePreview.value = preview
      pendingMaterialSave.value = pending
      return false
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

async function confirmMaterialSave() {
  const pending = pendingMaterialSave.value
  const token = materialSavePreview.value?.confirmation_token
  if (!pending || !token || saving.value || verifying.value || materialSaveRequiresRecheck.value) return false
  if (!materialSaveSnapshotMatches(pending)) {
    materialSaveError.value = '页面内容已变化，请返回修改后重新检查新增清单。'
    materialSaveRequiresRecheck.value = true
    return false
  }
  if (pending.options.intent === 'draft') saving.value = true
  else verifying.value = true
  materialSaveError.value = ''
  try {
    return await writeMaterialSave(pending, token)
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
  if (!bom.value || !canVerify.value || saving.value || verifying.value || pendingMaterialSave.value) return
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

function number(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(parsed) : String(value)
}

function decimalValuesEqual(leftValue: string | number, rightValue: string | number) {
  const left = decimalFraction(leftValue)
  const right = decimalFraction(rightValue)
  return Boolean(left && right && left.numerator * right.denominator === right.numerator * left.denominator)
}

function decimalDifferenceText(value: string | number, baseline: string | number) {
  const current = decimalFraction(value)
  const base = decimalFraction(baseline)
  if (!current || !base) return '—'
  const numerator = current.numerator * base.denominator - base.numerator * current.denominator
  const denominator = current.denominator * base.denominator
  const difference = halfUpFixedText(numerator, denominator, 4).replace(/\.?0+$/, '') || '0'
  return `${numerator > 0n ? '+' : ''}${number(difference)}`
}

type TubeCalculationKey =
  | 'total_consumption'
  | 'tube_cut_length_m'
  | 'suggested_purchase_meters'
  | 'branch_count'
  | 'long_material_unit_weight_kg'
  | 'tube_unit_weight_kg'
  | 'long_material_total_weight_kg'



interface DecimalFraction {
  numerator: bigint
  denominator: bigint
}

function decimalFraction(value: string | number | null | undefined): DecimalFraction | null {
  const text = String(value ?? '').trim()
  const match = text.match(/^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/)
  if (!match || (!match[2] && !match[3])) return null
  const exponent = Number(match[4] || 0)
  if (!Number.isInteger(exponent) || Math.abs(exponent) > 100) return null
  const fractionDigits = match[3] || ''
  const digits = `${match[2] || '0'}${fractionDigits}`.replace(/^0+(?=\d)/, '')
  let numerator = BigInt(digits || '0')
  let scaleDigits = fractionDigits.length - exponent
  if (scaleDigits < 0) {
    numerator *= 10n ** BigInt(-scaleDigits)
    scaleDigits = 0
  }
  if (match[1] === '-') numerator = -numerator
  return { numerator, denominator: 10n ** BigInt(scaleDigits) }
}

function halfUpFixedText(numerator: bigint, denominator: bigint, fractionDigits: number) {
  if (denominator <= 0n || fractionDigits < 0) return ''
  const negative = numerator < 0n
  const absoluteNumerator = negative ? -numerator : numerator
  const factor = 10n ** BigInt(fractionDigits)
  const scaledNumerator = absoluteNumerator * factor
  const quotient = scaledNumerator / denominator
  const remainder = scaledNumerator % denominator
  const rounded = quotient + (remainder * 2n >= denominator ? 1n : 0n)
  const whole = rounded / factor
  const fraction = fractionDigits ? `.${String(rounded % factor).padStart(fractionDigits, '0')}` : ''
  return `${negative && rounded !== 0n ? '-' : ''}${whole}${fraction}`
}

function calculationText(value: number | null, fractionDigits = 4, keepTrailingZeros = false) {
  if (value === null || !Number.isFinite(value)) return '—'
  const fraction = decimalFraction(value)
  if (!fraction) return '—'
  const text = halfUpFixedText(fraction.numerator, fraction.denominator, fractionDigits)
  return keepTrailingZeros ? text : text.replace(/\.?0+$/, '')
}

function tubeCalculations(line: BomLineInput): Record<TubeCalculationKey, string> {
  const plan = pipePlan(line.length_value, line.unit_consumption, line.tube_cut_piece_count, String(bom.value?.order_quantity || ''))
  const length = plan ? Number(plan.tube_cut_length_m) : null
  const unitWeight = plan ? Number(line.length_value) * Number(line.unit_consumption) * 0.464 / 1000 : null
  return {
    total_consumption: plan?.total_consumption || '—', tube_cut_length_m: plan?.tube_cut_length_m || '—',
    branch_count: plan?.branch_count || '—', suggested_purchase_meters: plan?.suggested_purchase_meters || '—',
    long_material_unit_weight_kg: calculationText(length === null ? null : length * 0.464),
    tube_unit_weight_kg: calculationText(unitWeight),
    long_material_total_weight_kg: calculationText(plan && length !== null ? Number(plan.branch_count) * length * 0.464 : null),
  }
}

function printPage() {
  window.print()
}

onMounted(() => {
  window.addEventListener('keydown', closeTableFullscreen)
  void loadBom()
  void loadTubeOptions()
})

onBeforeUnmount(() => {
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
      <InquiryProductDialog
        ref="productConfirmDialog"
        v-model="productConfirmVisible"
        scene="bom"
        :item="productConfirmItem"
        :context-title="`${bom.production_task_number} · ${bom.product_name_snapshot}`"
        :reviewed="bom.product_information_confirmed"
        :categories="productConfirmOptions.categories"
        :units="productConfirmOptions.units"
        :colors="productConfirmColors"
        :currencies="[]"
        :can-upload="false"
        :can-create-product="canCreateProduct"
        :can-create-color="canCreateProductColor"
        :busy="productConfirmLoading"
        :close-on-confirm="false"
        :catalog-error="productConfirmCatalogError"
        :catalog-loading="productConfirmCatalogLoading"
        :save-error="productConfirmError"
        @confirm="confirmProductInformation"
        @retry-catalog="loadProductConfirmCatalog"
        @create-product="prepareConfirmedProductCreate"
        @create-color="openConfirmedColorCreate"
      >
        <template #business>
          <div class="bom-review-context">
            <h3>本条生产任务</h3>
            <div class="bom-review-context__fields">
              <label><span>数量（只读）</span><ElInput :model-value="`${number(bom.order_quantity)} ${bom.product_unit_name}`" readonly aria-label="任务数量" /></label>
              <label><span>要求日期（只读）</span><ElInput :model-value="bom.planned_end_date || '—'" readonly aria-label="任务要求日期" /></label>
            </div>
            <h3>来源明细</h3>
            <dl>
              <div><dt>生产任务</dt><dd>{{ bom.production_task_number }}</dd></div>
              <div><dt>销售订单</dt><dd>{{ bom.source_sales_order_number || '未关联销售订单' }}</dd></div>
              <div><dt>当前 BOM</dt><dd>{{ bom.bom_number }}</dd></div>
            </dl>
            <h3>产品图片</h3>
            <p>沿用业务单据中的图片，本次核对不修改或覆盖图片。</p>
            <p class="bom-review-context__rule">{{ bom.status === 'VERIFIED' ? '当前 BOM 已确认；本次修改仅保存当前 BOM，不再次覆盖上游。' : '确认 BOM 后，按首次确认规则更新询盘、报价、销售和生产产品信息。样品、数量、价格及日期保持原值。' }}</p>
          </div>
        </template>
      </InquiryProductDialog>
      <ProductCreateDialog v-model="productConfirmCreateVisible" :initial-values="productCreateInitial" :initial-unit-code="productCreateUnitCode" :initial-item-number="productCreateItemNumber" :submit-product="createProductForBom" @created="handleConfirmedProductCreated" />
      <AppWindowDialog v-model="productConfirmColorCreateVisible" title="新增颜色" :width="520" :close-on-click-modal="false" :close-on-press-escape="!productConfirmLoading" :show-close="!productConfirmLoading">
        <ElForm label-position="top" class="bom-color-create-form">
          <ElFormItem label="色卡" required><ElInput v-model="productColorDraft.color_card" maxlength="100" placeholder="例如：A卡" /></ElFormItem>
          <ElFormItem label="色号" required><ElInput v-model="productColorDraft.color_code" maxlength="100" placeholder="例如：001" /></ElFormItem>
          <ElFormItem label="颜色名称" required><ElInput v-model="productColorDraft.color_name" maxlength="200" placeholder="例如：黑色" /></ElFormItem>
        </ElForm>
        <template #footer><ElButton :disabled="productConfirmLoading" @click="productConfirmColorCreateVisible = false">取消</ElButton><ElButton type="primary" :loading="productConfirmLoading" @click="createConfirmedColor">保存颜色</ElButton></template>
      </AppWindowDialog>
      <header class="editor-heading">
        <div>
          <div class="title-line">
            <h1>编辑BOM&nbsp; {{ bom.bom_number }}</h1>
            <span class="editor-status-tag" :class="{ verified: bom.status === 'VERIFIED' }">{{ editorStatusLabel }}</span>
          </div>
        </div>
        <div class="heading-actions">
          <ElButton @click="printPage">预览打印</ElButton>
          <ElButton v-if="canEdit" :loading="saving" :disabled="verifying || Boolean(pendingMaterialSave)" @click="persistDraft()">保存草稿</ElButton>
          <ElButton v-if="canVerify" type="primary" :loading="verifying" :disabled="saving || Boolean(pendingMaterialSave)" @click="submitVerification">确认BOM</ElButton>
        </div>
      </header>

      <nav class="bom-editor-tabs" role="tablist" aria-label="BOM 编辑内容" @keydown="focusEditorTab">
        <button id="bom-product-tab" type="button" role="tab" aria-controls="bom-product-panel" :aria-selected="activeEditorTab === 'product'" :tabindex="focusedEditorTab === 'product' ? 0 : -1" @click="selectEditorTab('product')">订单与产品</button>
        <button id="bom-material-tab" type="button" role="tab" aria-controls="bom-material-panel" :aria-selected="activeEditorTab === 'materials'" :tabindex="focusedEditorTab === 'materials' ? 0 : -1" @click="selectEditorTab('materials')">BOM 用料</button>
      </nav>
      <section v-show="activeEditorTab === 'product'" id="bom-product-panel" class="card product-card" role="tabpanel" aria-labelledby="bom-product-tab">
        <header><h2>订单与产品</h2><ElButton plain @click="openProductConfirmDialog">查看产品信息</ElButton></header>
        <div class="product-overview">
          <BomProductImage v-if="activeEditorTab === 'product'" :task-id="bom.production_task_id || ''" :product-line-id="bom.production_task_product_id || ''" />
          <div class="product-details">
            <section><h3>基本信息</h3><dl>
              <div><dt>BOM 编号</dt><dd>{{ bom.bom_number }}</dd></div>
              <div><dt>订单号</dt><dd>{{ bom.order_number || '—' }}</dd></div>
              <div><dt>产品编号</dt><dd>{{ bom.product_code_snapshot || bom.product_number_snapshot || '—' }}</dd></div>
              <div><dt>货号</dt><dd>{{ bom.item_number_snapshot || '—' }}</dd></div>
            </dl></section>
            <section><h3>产品属性</h3><dl>
              <div><dt>产品名称</dt><dd>{{ bom.product_name_snapshot }}</dd></div>
              <div><dt>产品规格</dt><dd>{{ bom.specification_snapshot || '—' }}</dd></div>
              <div><dt>单位</dt><dd>{{ bom.product_unit_name || '—' }}</dd></div>
              <div><dt>颜色</dt><dd>{{ bom.product_color_snapshot || '—' }}</dd></div>
              <div><dt>材质</dt><dd>{{ bom.material_snapshot || '—' }}</dd></div>
            </dl></section>
            <section><h3>数量信息</h3><dl>
              <div><dt>当前订单数量</dt><dd class="quantity-value">{{ number(bom.current_order_quantity) }}</dd></div>
              <div><dt>BOM 订单数量</dt><dd>{{ number(bom.order_quantity) }}</dd></div>
              <div><dt>原表数量</dt><dd>{{ number(bom.source_quantity) }}</dd></div>
              <div><dt>批次合计</dt><dd>{{ number(bom.batch_quantity) }}</dd></div>
            </dl></section>
          </div>
        </div>
      </section>

      <AppWindowDialog v-model="productInfoVisible" title="产品信息" width="640px" append-to-body destroy-on-close>
        <div class="bom-product-info-dialog">
          <p class="bom-product-info-dialog__hint">以下为当前 BOM 保存的产品信息快照。图片不随 BOM 产品确认回写。</p>
          <dl>
            <div><dt>产品 ID</dt><dd>{{ bom.product_master_id || '尚未关联产品库' }}</dd></div>
            <div><dt>产品编号</dt><dd>{{ bom.product_number_snapshot || '—' }}</dd></div>
            <div><dt>产品编码</dt><dd>{{ bom.product_code_snapshot || '—' }}</dd></div>
            <div><dt>货号</dt><dd>{{ bom.item_number_snapshot || '—' }}</dd></div>
            <div><dt>类别</dt><dd>{{ bom.product_category_snapshot || '—' }}</dd></div>
            <div><dt>产品名称</dt><dd>{{ bom.product_name_snapshot || '—' }}</dd></div>
            <div><dt>规格</dt><dd>{{ bom.specification_snapshot || '—' }}</dd></div>
            <div><dt>单位</dt><dd>{{ bom.product_unit_name || '—' }}</dd></div>
            <div><dt>颜色</dt><dd>{{ bom.product_color_snapshot || '—' }}</dd></div>
            <div><dt>材质</dt><dd>{{ bom.material_snapshot || '—' }}</dd></div>
          </dl>
        </div>
        <template #footer><ElButton @click="productInfoVisible = false">关闭</ElButton></template>
      </AppWindowDialog>

      <div v-show="activeEditorTab === 'materials'" id="bom-material-panel" role="tabpanel" aria-labelledby="bom-material-tab">
      <div class="editor-grid">
        <aside class="card section-sidebar">
          <h2>物料分类</h2>
          <div v-if="sections.length" class="section-tabs">
            <button v-for="group in sectionNavigationGroups" :key="group.label" type="button" :class="{ active: group.label === activeNavigationLabel }" :disabled="!group.indexes.length" @click="selectNavigationGroup(group.indexes)">
              <span>{{ group.label }}</span><b>{{ group.count }}</b>
            </button>
          </div>
        </aside>
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
             <ElTable v-if="activeSection.section_type === 'PROFILE'" class="tube-table prototype-tube-table" :data="activeSection.lines" border empty-text="当前型材暂无用料，点击“添加材料”开始录入">
               <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                 <template #header><ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top"><ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" /></ElTooltip></template>
                 <template #default="scope"><div class="table-index-cell"><span class="table-row-number">{{ scope.$index + 1 }}</span><div v-if="canEdit" class="table-row-actions"><ElTooltip content="编辑当前行" placement="top"><ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" /></ElTooltip><ElTooltip content="删除当前行" placement="top"><ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click.stop="removeLine(scope.$index)" /></ElTooltip></div></div></template>
               </ElTableColumn>
               <ElTableColumn prop="part_name" label="部件名称" min-width="130" />
               <ElTableColumn prop="material" label="材质" width="90" />
                <ElTableColumn label="喷塑颜色" min-width="120">
                  <template #default="scope">
                    <ElSelect v-model="scope.row.tube_coating_color" filterable clearable :value-on-clear="''" :loading="tubeOptionsLoading" :disabled="!canEdit" placeholder="选择颜色">
                      <ElOption v-for="item in tubeCoatingColors" :key="item.id" :label="item.color_name" :value="item.color_name" />
                    </ElSelect>
                  </template>
                </ElTableColumn>
               <ElTableColumn label="规格" min-width="118"><template #default="scope"><ElTooltip :content="scope.row.specification || `${scope.row.tube_diameter || '—'} × ${scope.row.tube_thickness || '—'}`" placement="top"><span class="profile-ellipsis-value">{{ scope.row.specification || `${scope.row.tube_diameter || '—'} × ${scope.row.tube_thickness || '—'}` }}</span></ElTooltip></template></ElTableColumn>
               <ElTableColumn prop="length_value" label="切割长度（mm）" width="100" />
               <ElTableColumn prop="unit_consumption" label="单耗" width="78" />
               <ElTableColumn label="总需求（支）" width="110"><template #default="scope"><b>{{ tubeCalculations(scope.row).total_consumption }}</b></template></ElTableColumn>
               <ElTableColumn prop="tube_cut_piece_count" label="切割支数" width="90" />
               <ElTableColumn label="原材料长度（m）" width="105"><template #default="scope">{{ tubeCalculations(scope.row).tube_cut_length_m }}</template></ElTableColumn>
               <ElTableColumn label="采购根数" width="90"><template #default="scope"><b>{{ tubeCalculations(scope.row).branch_count }}</b></template></ElTableColumn>
               <ElTableColumn label="建议采购米数" width="115"><template #default="scope">{{ tubeCalculations(scope.row).suggested_purchase_meters }}</template></ElTableColumn>
               <ElTableColumn prop="notes" label="备注" min-width="90"><template #default="scope"><ElTooltip :content="scope.row.notes || '—'" placement="top"><span class="profile-ellipsis-value">{{ scope.row.notes || '—' }}</span></ElTooltip></template></ElTableColumn>
             </ElTable>
            <ElTable v-else-if="isHardwareSection" class="hardware-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前五金件暂无数据，点击“选择数据”批量添加">
              <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                <template #header>
                  <ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top">
                    <ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" />
                  </ElTooltip>
                </template>
                <template #default="scope">
                  <div class="table-index-cell">
                    <span class="table-row-number">{{ scope.$index + 1 }}</span>
                    <div v-if="canEdit" class="table-row-actions">

                      <ElTooltip content="编辑当前行" placement="top">
                        <ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" />
                      </ElTooltip>
                      <ElTooltip content="删除当前行" placement="top">
                        <ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click="removeLine(scope.$index)" />
                      </ElTooltip>
                    </div>
                  </div>
                </template>
              </ElTableColumn>
              <ElTableColumn label="品名" min-width="160" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.part_name || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="材质" width="100" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.material || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="颜色" min-width="130" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ formatHardwareColor(scope.row.hardware_color) }}</span></template></ElTableColumn>
              <ElTableColumn label="规格" min-width="140" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.specification || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="单位" width="80"><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.unit || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="单个用量" width="110"><template #default="scope"><ElInput v-model="scope.row.unit_consumption" inputmode="decimal" :disabled="!canEdit" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="单个材料重量（kg）" width="170"><template #default="scope"><ElInput v-model="scope.row.unit_material_weight_kg" inputmode="decimal" :disabled="!canEdit" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="喷塑颜色" min-width="165">
                <template #default="scope">
                  <ElSelect v-model="scope.row.powder_coating_color" filterable clearable :value-on-clear="''" :loading="tubeOptionsLoading" :disabled="!canEdit" placeholder="选择颜色">
                    <ElOption v-for="item in tubeCoatingColors" :key="item.id" :label="item.color_name" :value="item.color_name" />
                  </ElSelect>
                </template>
              </ElTableColumn>
              <ElTableColumn label="喷塑单个面积（㎡）" width="175"><template #default="scope"><ElInput v-model="scope.row.powder_coating_unit_area_sqm" inputmode="decimal" :disabled="!canEdit" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="备注" min-width="170"><template #default="scope"><ElInput v-model="scope.row.notes" :disabled="!canEdit" maxlength="500" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
            </ElTable>
            <ElTable v-else-if="isPlasticSection" class="plastic-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前塑料件暂无数据，点击“选择数据”批量添加">
              <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                <template #header>
                  <ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top">
                    <ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" />
                  </ElTooltip>
                </template>
                <template #default="scope">
                  <div class="table-index-cell">
                    <span class="table-row-number">{{ scope.$index + 1 }}</span>
                    <div v-if="canEdit" class="table-row-actions">

                      <ElTooltip content="编辑当前行" placement="top">
                        <ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" />
                      </ElTooltip>
                      <ElTooltip content="删除当前行" placement="top">
                        <ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click="removeLine(scope.$index)" />
                      </ElTooltip>
                    </div>
                  </div>
                </template>
              </ElTableColumn>
              <ElTableColumn label="品名" min-width="190" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.part_name || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="材质" width="120" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.material || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="颜色" min-width="140" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ formatHardwareColor(scope.row.plastic_color) }}</span></template></ElTableColumn>
              <ElTableColumn label="规格" min-width="150" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.specification || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="单位" width="80"><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.unit || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="单个用量" width="130"><template #default="scope"><ElInput v-model="scope.row.unit_consumption" inputmode="decimal" :disabled="!canEdit" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="备注" min-width="220"><template #default="scope"><ElInput v-model="scope.row.notes" :disabled="!canEdit" maxlength="500" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
            </ElTable>
            <ElTable v-else-if="isAuxiliarySection" v-loading="editorReferenceOptionsLoading" class="auxiliary-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前辅料暂无数据，点击“选择辅料”批量添加">
              <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                <template #header>
                  <ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top">
                    <ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" />
                  </ElTooltip>
                </template>
                <template #default="scope">
                  <div class="table-index-cell">
                    <span class="table-row-number">{{ scope.$index + 1 }}</span>
                    <div v-if="canEdit" class="table-row-actions">

                      <ElTooltip content="编辑当前行" placement="top"><ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" /></ElTooltip>
                      <ElTooltip content="删除当前行" placement="top"><ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click="removeLine(scope.$index)" /></ElTooltip>
                    </div>
                  </div>
                </template>
              </ElTableColumn>
              <ElTableColumn label="品名" min-width="180" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.part_name || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="*规格" min-width="150">
                <template #default="scope">
                  <ElSelect v-if="auxiliaryLineHasActiveProduct(scope.row)" v-model="scope.row.source_accessory_specification_id" filterable :disabled="!canEdit" placeholder="选择规格" @change="setAuxiliarySpecification(scope.row, $event)"><ElOption v-for="item in auxiliarySpecificationOptions(scope.row)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect>
                  <span v-else class="hardware-readonly-cell">{{ scope.row.specification || '—' }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="*颜色" min-width="150">
                <template #default="scope">
                  <ElSelect v-if="auxiliaryLineHasActiveProduct(scope.row)" v-model="scope.row.source_accessory_color_id" filterable :disabled="!canEdit" placeholder="选择颜色" @change="setAuxiliaryColor(scope.row, $event)"><ElOption v-for="item in auxiliaryColorOptions(scope.row)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect>
                  <span v-else class="hardware-readonly-cell">{{ scope.row.accessory_color || '—' }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="*材质" min-width="140">
                <template #default="scope">
                  <ElSelect v-if="auxiliaryLineHasActiveProduct(scope.row)" v-model="scope.row.source_accessory_material_id" filterable :disabled="!canEdit" placeholder="选择材质" @change="setAuxiliaryMaterial(scope.row, $event)"><ElOption v-for="item in auxiliaryMaterialOptions(scope.row)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect>
                  <span v-else class="hardware-readonly-cell">{{ scope.row.material || '—' }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="单位" width="80"><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.unit || '待维护' }}</span></template></ElTableColumn>
              <ElTableColumn label="单个用量" width="125"><template #default="scope"><ElInput v-model="scope.row.unit_consumption" inputmode="decimal" :disabled="!canEdit" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="备注" min-width="190"><template #default="scope"><ElInput v-model="scope.row.notes" :disabled="!canEdit" maxlength="500" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
            </ElTable>
            <ElTable v-else-if="isFabricSection" v-loading="editorReferenceOptionsLoading" class="fabric-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前面料暂无数据，点击“添加面料”开始录入">
              <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                <template #header>
                  <ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top"><ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" /></ElTooltip>
                </template>
                <template #default="scope">
                  <div class="table-index-cell"><span class="table-row-number">{{ scope.$index + 1 }}</span><div v-if="canEdit" class="table-row-actions"><ElTooltip content="编辑当前行" placement="top"><ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" /></ElTooltip><ElTooltip content="删除当前行" placement="top"><ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click="removeLine(scope.$index)" /></ElTooltip></div></div>
                </template>
              </ElTableColumn>
              <ElTableColumn label="规格" min-width="140"><template #default="scope"><ElSelect v-model="scope.row.source_fabric_specification_id" filterable clearable :value-on-clear="null" :disabled="!canEdit" :placeholder="scope.row.specification || '选择规格'" @change="setFabricSpecification(scope.row, $event)"><ElOption v-for="item in fabricSpecificationOptions(scope.row)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></template></ElTableColumn>
              <ElTableColumn label="材质" min-width="130"><template #default="scope"><ElSelect v-model="scope.row.source_fabric_material_id" filterable clearable :value-on-clear="null" :disabled="!canEdit" :placeholder="scope.row.material || '选择材质'" @change="setFabricMaterial(scope.row, $event)"><ElOption v-for="item in fabricMaterialOptions(scope.row)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></template></ElTableColumn>
              <ElTableColumn label="色卡" min-width="200"><template #default="scope"><ElSelect v-model="scope.row.source_product_color_id" filterable clearable :value-on-clear="null" :disabled="!canEdit" :placeholder="fabricColorSnapshot(scope.row) || '选择色卡 / 颜色 / 色号'" @change="setFabricColor(scope.row, $event)"><ElOption v-for="item in fabricColorOptions(scope.row)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></template></ElTableColumn>
              <ElTableColumn label="颜色" min-width="120" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.fabric_color_name || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="色号" min-width="120" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.fabric_color_code || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="门幅" min-width="120"><template #default="scope"><ElSelect v-model="scope.row.source_fabric_width_id" filterable clearable :value-on-clear="null" :disabled="!canEdit" :placeholder="scope.row.fabric_width || '选择门幅'" @change="setFabricWidth(scope.row, $event)"><ElOption v-for="item in fabricWidthOptions(scope.row)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></template></ElTableColumn>
              <ElTableColumn label="单个用量" width="120"><template #default="scope"><ElInput v-model="scope.row.unit_consumption" inputmode="decimal" :disabled="!canEdit" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="裁片" min-width="150"><template #default="scope"><ElInput v-model="scope.row.part_name" :disabled="!canEdit" maxlength="300" placeholder="填写裁片" /></template></ElTableColumn>
              <ElTableColumn label="单位" width="70"><template #default><span class="hardware-readonly-cell">米</span></template></ElTableColumn>
              <ElTableColumn label="备注" min-width="170"><template #default="scope"><ElInput v-model="scope.row.notes" :disabled="!canEdit" maxlength="500" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
            </ElTable>
            <ElTable v-else-if="isPackagingSection" class="packaging-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前包材暂无数据，点击“选择包材”批量添加">
              <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                <template #header><ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top"><ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" /></ElTooltip></template>
                <template #default="scope"><div class="table-index-cell"><span class="table-row-number">{{ scope.$index + 1 }}</span><div v-if="canEdit" class="table-row-actions"><ElTooltip content="编辑当前行" placement="top"><ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" /></ElTooltip><ElTooltip content="删除当前行" placement="top"><ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click="removeLine(scope.$index)" /></ElTooltip></div></div></template>
              </ElTableColumn>
              <ElTableColumn label="品号" width="130" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.packaging_material_number || scope.row.raw_material || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="品名" min-width="165" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.part_name || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="材质" width="105" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.material || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="颜色" min-width="130" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ formatHardwareColor(scope.row.packaging_color) }}</span></template></ElTableColumn>
              <ElTableColumn label="规格" min-width="155" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.specification || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="单位" width="76"><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.unit || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="*箱数（多少一箱）" width="170"><template #default="scope"><ElInput v-model="scope.row.units_per_box" inputmode="numeric" :disabled="!canEdit" placeholder="填写正整数" /></template></ElTableColumn>
              <ElTableColumn label="*单个用量" width="125"><template #default="scope"><ElInput v-model="scope.row.unit_consumption" inputmode="decimal" :disabled="!canEdit" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
            </ElTable>
            <ElTable v-else-if="isCuttingSection" class="cutting-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前裁剪明细暂无数据，点击“选择裁剪”批量添加">
              <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                <template #header><ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top"><ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" /></ElTooltip></template>
                <template #default="scope"><div class="table-index-cell"><span class="table-row-number">{{ scope.$index + 1 }}</span><div v-if="canEdit" class="table-row-actions"><ElTooltip content="编辑当前行" placement="top"><ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" /></ElTooltip><ElTooltip content="删除当前行" placement="top"><ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click="removeLine(scope.$index)" /></ElTooltip></div></div></template>
              </ElTableColumn>
              <ElTableColumn label="裁剪名称" min-width="125"><template #default="scope"><template v-if="cuttingQuantities(scope.row).mode !== 'legacy' && cuttingQuantities(scope.row).error"><ElTooltip placement="top-start" effect="light" popper-class="cutting-name-error-tooltip" :show-after="100" :teleported="true"><template #content><span role="alert">{{ cuttingQuantities(scope.row).error }}</span></template><span class="hardware-readonly-cell cutting-name-tooltip-anchor has-error" tabindex="0">{{ scope.row.part_name || '—' }}</span></ElTooltip></template><span v-else class="hardware-readonly-cell">{{ scope.row.part_name || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="规格" min-width="140"><template #default="scope"><ElInput v-model="scope.row.specification" :disabled="!canEdit" maxlength="500" placeholder="填写规格" /></template></ElTableColumn>
              <ElTableColumn label="材质" min-width="130"><template #default="scope"><ElInput :model-value="cuttingMaterial(scope.row)" :disabled="!canEdit" maxlength="200" placeholder="填写材质" @update:model-value="scope.row.material = $event" /></template></ElTableColumn>
              <ElTableColumn label="颜色" min-width="120" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ formatHardwareColor(scope.row.cutting_color) }}</span></template></ElTableColumn>
              <ElTableColumn label="裁片量（片/套）" width="125"><template #default="scope"><span v-if="legacyPipeCuttingValues(scope.row)" class="cutting-legacy-value" :title="'管材旧口径，按根/支流转；此处为开发试算展示'">{{ legacyPipeCuttingValues(scope.row)?.pieces }}</span><ElInput v-else v-model="scope.row.cutting_pieces_per_set" inputmode="numeric" :disabled="!canEdit" placeholder="待填写" aria-label="裁片量（片/套）" /></template></ElTableColumn>
              <ElTableColumn label="单个用量（米/片）" width="140"><template #default="scope"><span v-if="legacyPipeCuttingValues(scope.row)" class="cutting-legacy-value" :title="'由旧每套耗米÷旧裁片量推算，仅用于开发试算展示'">{{ legacyPipeCuttingValues(scope.row)?.metersPerPiece }}</span><ElInput v-else v-model="scope.row.fabric_meters_per_piece" inputmode="decimal" :disabled="!canEdit" placeholder="待填写" aria-label="单个用量（米/片）" /></template></ElTableColumn>
              <ElTableColumn label="每成品套数（套/成品）" width="155"><template #default="scope"><span v-if="legacyPipeCuttingValues(scope.row)" class="cutting-legacy-value" :title="'管材旧口径没有该布料字段，开发试算按 1 套展示'">{{ legacyPipeCuttingValues(scope.row)?.sets }}</span><ElInput v-else v-model="scope.row.cutting_sets_per_product" inputmode="numeric" :disabled="!canEdit" placeholder="待填写" aria-label="每成品套数（套/成品）" /></template></ElTableColumn>
              <ElTableColumn label="每套耗米（米/套）" width="160"><template #default="scope"><template v-if="cuttingQuantities(scope.row).mode === 'legacy'"><ElInput v-model="scope.row.fabric_meters_per_set" inputmode="decimal" :disabled="!canEdit" aria-label="原每套耗米（米/套）" /></template><span v-else>{{ cuttingQuantities(scope.row).metersPerSet || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="流转单位" width="100"><template #default="scope"><ElInput v-if="cuttingQuantities(scope.row).mode === 'legacy'" v-model="scope.row.unit" :disabled="!canEdit" maxlength="50" placeholder="填写单位" /><span v-else>套</span></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
              <ElTableColumn label="备注" min-width="260"><template #default="scope"><ElInput v-model="scope.row.notes" :disabled="!canEdit" maxlength="500" placeholder="填写" /></template></ElTableColumn>
            </ElTable>
            <ElTable v-else-if="activeSection.lines.length" :data="activeSection.lines" border scrollbar-always-on>
              <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                <template #header>
                  <ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top">
                    <ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" />
                  </ElTooltip>
                </template>
                <template #default="scope">
                  <div class="table-index-cell">
                    <span class="table-row-number">{{ scope.$index + 1 }}</span>
                    <div v-if="canEdit" class="table-row-actions">

                      <ElTooltip content="编辑当前行" placement="top">
                        <ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" />
                      </ElTooltip>
                      <ElTooltip content="删除当前行" placement="top">
                        <ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click="removeLine(scope.$index)" />
                      </ElTooltip>
                    </div>
                  </div>
                </template>
              </ElTableColumn>
              <ElTableColumn label="材质" width="112"><template #default="scope"><ElInput v-model="scope.row.material" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn label="配件 / 裁片名称" min-width="170"><template #default="scope"><ElInput v-model="scope.row.part_name" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn v-if="activeSection.section_type !== 'FABRIC'" label="规格 / 厚度" min-width="145"><template #default="scope"><ElInput v-model="scope.row.specification" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn v-if="activeSection.section_type === 'FABRIC'" label="原材料" min-width="160"><template #default="scope"><ElInput v-model="scope.row.raw_material" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn v-if="activeSection.section_type === 'FABRIC'" label="裁片量" width="100"><template #default="scope"><ElInput v-model="scope.row.cut_piece_quantity" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn label="单耗" width="100"><template #default="scope"><ElInput v-model="scope.row.unit_consumption" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn label="当前需求" width="120"><template #default="scope"><ElInput v-model="scope.row.total_consumption" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn label="单位" width="90"><template #default="scope"><ElInput v-model="scope.row.unit" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn label="备注" min-width="160"><template #default="scope"><ElInput v-model="scope.row.notes" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
            </ElTable>
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

      <section class="card quantity-compare-card">
        <header><h2>数量对比与确认</h2><span>所有数量均按当前颜色产品明细范围计算</span></header>
        <div class="quantity-compare-grid">
          <label><span>订单依据数量</span><strong>{{ number(bom.order_quantity) }}</strong></label>
          <label><span>当前任务数量</span><strong>{{ number(bom.current_order_quantity) }}</strong></label>
          <label><span>Excel 原表数量</span><strong>{{ number(bom.source_quantity) }}</strong></label>
          <label class="difference"><span>数量差异</span><strong>{{ number(bom.quantity_difference) }}</strong></label>
          <label><span>生产批次数量</span><strong>{{ number(bom.batch_quantity) }}</strong></label>
          <ElInput v-if="quantityMismatch" v-model="quantityReason" maxlength="500" show-word-limit placeholder="填写数量差异确认原因" :disabled="!canVerify" />
          <div v-else class="quantity-confirmed">数量一致，无需填写差异原因</div>
          <ElButton v-if="(bom.is_order_quantity_outdated || bom.is_order_product_outdated) && canSync" type="warning" plain :loading="syncingQuantity" @click="requestOrderQuantitySync(false)">同步订单信息</ElButton>
        </div>
      </section>

      </div>
      <BomLineEditorDialog
        v-model="lineDrawerVisible"
        :title="lineDrawerTitle"
        :before-close="beforeLineDrawerClose"
        @closed="resetLineDrawer"
      >
        <div v-if="editingLineDraft" class="line-drawer-form">
          <ElAlert
            v-if="(editingSection?.title === '辅料类' || editingSection?.title === '面料类') && editorReferenceOptionsError"
            class="reference-options-error drawer-field--wide"
            type="error"
            :title="editorReferenceOptionsError"
            show-icon
            :closable="false"
          >
            <template #default><ElButton size="small" @click="ensureEditorReferenceOptions">重新加载生产维护数据</ElButton></template>
          </ElAlert>
          <template v-if="editingSection?.section_type === 'PROFILE'">
            <label class="drawer-field">
              <span>形状</span>
              <PinyinFilterSelect v-model="editingLineDraft.tube_shape" :options="tubeShapes" label-key="shape_name" :loading="tubeOptionsLoading" placeholder="选择形状" aria-label="形状" />
            </label>
            <label class="drawer-field">
              <span>品名</span>
              <PinyinFilterSelect v-model="editingLineDraft.part_name" :options="tubeProductNames" label-key="product_name" :loading="tubeOptionsLoading" placeholder="选择品名" aria-label="品名" />
            </label>
            <label class="drawer-field">
              <span>材质</span>
              <PinyinFilterSelect v-model="editingLineDraft.material" :options="tubeMaterials" label-key="material_name" :loading="tubeOptionsLoading" placeholder="选择材质" aria-label="材质" />
            </label>
            <label class="drawer-field">
              <span>规格</span>
              <ElSelect v-model="editingLineDraft.tube_diameter" filterable clearable :value-on-clear="''" :loading="tubeOptionsLoading" placeholder="选择规格" aria-label="规格">
                <ElOption v-for="item in tubeDiameters" :key="item.id" :label="item.diameter_value" :value="item.diameter_value" />
              </ElSelect>
            </label>
            <label class="drawer-field">
              <span>厚度</span>
              <ElSelect v-model="editingLineDraft.tube_thickness" filterable clearable :value-on-clear="''" :loading="tubeOptionsLoading" placeholder="选择厚度" aria-label="厚度">
                <ElOption v-for="item in tubeThicknesses" :key="item.id" :label="item.thickness_value" :value="item.thickness_value" />
              </ElSelect>
            </label>
            <label class="drawer-field"><span>切割长度（mm）</span><ElInput v-model="editingLineDraft.length_value" inputmode="numeric" placeholder="正整数毫米" aria-label="切割长度（mm）" /></label>
            <label class="drawer-field"><span>单个用量</span><ElInput v-model="editingLineDraft.unit_consumption" inputmode="decimal" placeholder="填写" aria-label="单个用量" /></label>
            <label class="drawer-field"><span>原材料单位</span><strong class="drawer-readonly-value">根</strong></label>
            <label class="drawer-field"><span>原材料长度（m）</span><strong class="drawer-readonly-value">{{ editingLineCalculations?.tube_cut_length_m }}</strong></label>
            <label class="drawer-field"><span>切割支数</span><ElInput v-model="editingLineDraft.tube_cut_piece_count" inputmode="decimal" placeholder="填写" aria-label="切割支数" @blur="normalizeTubeCutPieceCount(editingLineDraft)" /></label>
            <label class="drawer-field">
              <span>喷塑颜色</span>
              <ElSelect v-model="editingLineDraft.tube_coating_color" filterable clearable :value-on-clear="''" :loading="tubeOptionsLoading" placeholder="选择颜色" aria-label="喷塑颜色">
                <ElOption v-for="item in tubeCoatingColors" :key="item.id" :label="item.color_name" :value="item.color_name" />
              </ElSelect>
            </label>
            <label class="drawer-field"><span>喷塑单个面积（㎡）</span><ElInput v-model="editingLineDraft.coating_unit_area_sqm" inputmode="decimal" placeholder="填写" aria-label="喷塑单个面积" /></label>
            <label class="drawer-field drawer-purchase-weight-field"><span>采购单个重量（kg）</span><ElInput v-model="editingLineDraft.purchase_unit_weight_kg" inputmode="decimal" placeholder="填写" aria-label="采购单个重量" /></label>
            <div class="drawer-field drawer-image-field">
              <span>图片</span>
              <div class="drawer-image-field-value">
                <span>{{ displayLineImages(editingLineDraft).length }} / 20 张</span>
                <ElButton size="small" plain type="primary" @click="openLineImageManager()">
                  {{ displayLineImages(editingLineDraft).length ? '管理图片' : '上传图片' }}
                </ElButton>
              </div>
            </div>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="3" maxlength="500" show-word-limit aria-label="备注" /></label>

            <section v-if="editingLineCalculations" class="drawer-calculations">
              <h3>自动计算</h3>
              <div class="drawer-calculation-grid">
                <label><span>总耗</span><strong>{{ editingLineCalculations.total_consumption }}</strong></label>
                <label><span>原材料长度（m）</span><strong>{{ editingLineCalculations.tube_cut_length_m }}</strong></label>
                <label><span>采购根数</span><strong>{{ editingLineCalculations.branch_count }}</strong></label>
                <label><span>建议采购米数</span><strong>{{ editingLineCalculations.suggested_purchase_meters }}</strong></label>
                <label><span>长料单重（kg）</span><strong>{{ editingLineCalculations.long_material_unit_weight_kg }}</strong></label>
                <label><span>单重（kg）</span><strong>{{ editingLineCalculations.tube_unit_weight_kg }}</strong></label>
                <label><span>长料总重量（kg）</span><strong>{{ editingLineCalculations.long_material_total_weight_kg }}</strong></label>
              </div>
            </section>
          </template>

          <template v-else-if="editingSection?.title === '五金件'">
            <label class="drawer-field"><span>品名</span><strong class="drawer-readonly-value">{{ editingLineDraft.part_name || '—' }}</strong></label>
            <label class="drawer-field"><span>材质</span><strong class="drawer-readonly-value">{{ editingLineDraft.material || '—' }}</strong></label>
            <label class="drawer-field"><span>颜色</span><strong class="drawer-readonly-value">{{ formatHardwareColor(editingLineDraft.hardware_color) }}</strong></label>
            <label class="drawer-field"><span>规格</span><strong class="drawer-readonly-value">{{ editingLineDraft.specification || '—' }}</strong></label>
            <label class="drawer-field"><span>单位</span><strong class="drawer-readonly-value">{{ editingLineDraft.unit || '—' }}</strong></label>
            <label class="drawer-field"><span>单个用量</span><ElInput v-model="editingLineDraft.unit_consumption" inputmode="decimal" placeholder="填写" aria-label="单个用量" /></label>
            <label class="drawer-field"><span>单个材料重量（kg）</span><ElInput v-model="editingLineDraft.unit_material_weight_kg" inputmode="decimal" placeholder="填写" aria-label="单个材料重量" /></label>
            <label class="drawer-field">
              <span>喷塑颜色</span>
              <ElSelect v-model="editingLineDraft.powder_coating_color" filterable clearable :value-on-clear="''" :loading="tubeOptionsLoading" placeholder="选择颜色" aria-label="喷塑颜色">
                <ElOption v-for="item in tubeCoatingColors" :key="item.id" :label="item.color_name" :value="item.color_name" />
              </ElSelect>
            </label>
            <label class="drawer-field"><span>喷塑单个面积（㎡）</span><ElInput v-model="editingLineDraft.powder_coating_unit_area_sqm" inputmode="decimal" placeholder="填写" aria-label="喷塑单个面积" /></label>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="4" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>

          <template v-else-if="editingSection?.title === '塑料件类'">
            <label class="drawer-field"><span>品名</span><strong class="drawer-readonly-value">{{ editingLineDraft.part_name || '—' }}</strong></label>
            <label class="drawer-field"><span>材质</span><strong class="drawer-readonly-value">{{ editingLineDraft.material || '—' }}</strong></label>
            <label class="drawer-field"><span>颜色</span><strong class="drawer-readonly-value">{{ formatHardwareColor(editingLineDraft.plastic_color) }}</strong></label>
            <label class="drawer-field"><span>规格</span><strong class="drawer-readonly-value">{{ editingLineDraft.specification || '—' }}</strong></label>
            <label class="drawer-field"><span>单位</span><strong class="drawer-readonly-value">{{ editingLineDraft.unit || '—' }}</strong></label>
            <label class="drawer-field"><span>单个用量</span><ElInput v-model="editingLineDraft.unit_consumption" inputmode="decimal" placeholder="填写" aria-label="单个用量" /></label>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="4" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>

          <template v-else-if="editingSection?.title === '辅料类'">
            <label class="drawer-field"><span>品名</span><strong class="drawer-readonly-value">{{ editingLineDraft.part_name || '—' }}</strong></label>
            <label v-if="auxiliaryLineHasActiveProduct(editingLineDraft)" class="drawer-field">
              <span>*规格</span>
              <ElSelect v-model="editingLineDraft.source_accessory_specification_id" filterable placeholder="选择规格" aria-label="辅料规格" @change="setAuxiliarySpecification(editingLineDraft, $event)"><ElOption v-for="item in auxiliarySpecificationOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect>
            </label>
            <label v-else class="drawer-field"><span>*规格</span><strong class="drawer-readonly-value">{{ editingLineDraft.specification || '—' }}</strong></label>
            <label v-if="auxiliaryLineHasActiveProduct(editingLineDraft)" class="drawer-field">
              <span>*颜色</span>
              <ElSelect v-model="editingLineDraft.source_accessory_color_id" filterable placeholder="选择颜色" aria-label="辅料颜色" @change="setAuxiliaryColor(editingLineDraft, $event)"><ElOption v-for="item in auxiliaryColorOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect>
            </label>
            <label v-else class="drawer-field"><span>*颜色</span><strong class="drawer-readonly-value">{{ editingLineDraft.accessory_color || '—' }}</strong></label>
            <label v-if="auxiliaryLineHasActiveProduct(editingLineDraft)" class="drawer-field">
              <span>*材质</span>
              <ElSelect v-model="editingLineDraft.source_accessory_material_id" filterable placeholder="选择材质" aria-label="辅料材质" @change="setAuxiliaryMaterial(editingLineDraft, $event)"><ElOption v-for="item in auxiliaryMaterialOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect>
            </label>
            <label v-else class="drawer-field"><span>*材质</span><strong class="drawer-readonly-value">{{ editingLineDraft.material || '—' }}</strong></label>
            <label class="drawer-field"><span>单位</span><strong class="drawer-readonly-value">{{ editingLineDraft.unit || '待维护' }}</strong></label>
            <label class="drawer-field"><span>单个用量</span><ElInput v-model="editingLineDraft.unit_consumption" inputmode="decimal" placeholder="填写" aria-label="单个用量" /></label>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="4" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>

          <template v-else-if="editingSection?.title === '面料类'">
            <label class="drawer-field"><span>规格</span><ElSelect v-model="editingLineDraft.source_fabric_specification_id" filterable clearable :value-on-clear="null" :placeholder="editingLineDraft.specification || '选择规格'" aria-label="面料规格" @change="setFabricSpecification(editingLineDraft, $event)"><ElOption v-for="item in fabricSpecificationOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></label>
            <label class="drawer-field"><span>材质</span><ElSelect v-model="editingLineDraft.source_fabric_material_id" filterable clearable :value-on-clear="null" :placeholder="editingLineDraft.material || '选择材质'" aria-label="面料材质" @change="setFabricMaterial(editingLineDraft, $event)"><ElOption v-for="item in fabricMaterialOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></label>
            <label class="drawer-field drawer-field--wide"><span>色卡</span><ElSelect v-model="editingLineDraft.source_product_color_id" filterable clearable :value-on-clear="null" :placeholder="fabricColorSnapshot(editingLineDraft) || '选择色卡 / 颜色 / 色号'" aria-label="面料色卡颜色色号" @change="setFabricColor(editingLineDraft, $event)"><ElOption v-for="item in fabricColorOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></label>
            <label class="drawer-field"><span>颜色</span><strong class="drawer-readonly-value">{{ editingLineDraft.fabric_color_name || '—' }}</strong></label>
            <label class="drawer-field"><span>色号</span><strong class="drawer-readonly-value">{{ editingLineDraft.fabric_color_code || '—' }}</strong></label>
            <label class="drawer-field"><span>门幅</span><ElSelect v-model="editingLineDraft.source_fabric_width_id" filterable clearable :value-on-clear="null" :placeholder="editingLineDraft.fabric_width || '选择门幅'" aria-label="面料门幅" @change="setFabricWidth(editingLineDraft, $event)"><ElOption v-for="item in fabricWidthOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></label>
            <label class="drawer-field"><span>单个用量</span><ElInput v-model="editingLineDraft.unit_consumption" inputmode="decimal" placeholder="填写" aria-label="单个用量" /></label>
            <label class="drawer-field"><span>裁片</span><ElInput v-model="editingLineDraft.part_name" maxlength="300" placeholder="填写裁片" aria-label="裁片" /></label>
            <label class="drawer-field"><span>单位</span><strong class="drawer-readonly-value">米</strong></label>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="4" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>

          <template v-else-if="editingSection?.title === '包材类'">
            <label class="drawer-field"><span>品号</span><strong class="drawer-readonly-value">{{ editingLineDraft.packaging_material_number || editingLineDraft.raw_material || '—' }}</strong></label>
            <label class="drawer-field"><span>品名</span><strong class="drawer-readonly-value">{{ editingLineDraft.part_name || '—' }}</strong></label>
            <label class="drawer-field"><span>材质</span><strong class="drawer-readonly-value">{{ editingLineDraft.material || '—' }}</strong></label>
            <label class="drawer-field"><span>颜色</span><strong class="drawer-readonly-value">{{ formatHardwareColor(editingLineDraft.packaging_color) }}</strong></label>
            <label class="drawer-field"><span>规格</span><strong class="drawer-readonly-value">{{ editingLineDraft.specification || '—' }}</strong></label>
            <label class="drawer-field"><span>单位</span><strong class="drawer-readonly-value">{{ editingLineDraft.unit || '—' }}</strong></label>
            <label class="drawer-field"><span>*箱数（多少一箱）</span><ElInput v-model="editingLineDraft.units_per_box" inputmode="numeric" placeholder="填写正整数" aria-label="箱数（多少一箱）" /></label>
            <label class="drawer-field"><span>*单个用量</span><ElInput v-model="editingLineDraft.unit_consumption" inputmode="decimal" placeholder="填写" aria-label="单个用量" /></label>
          </template>

          <template v-else-if="editingSection?.title === '裁剪明细'">
            <label class="drawer-field drawer-field--wide"><span>来源面料</span><strong v-if="isPipeCuttingLine(editingLineDraft)" class="drawer-readonly-value">管材半成品 · 不关联面料</strong><template v-else><ElSelect v-model="editingFabricSourceKey" filterable placeholder="选择本 BOM 的面料" aria-label="来源面料" no-data-text="请先在面料分类添加并选择面料"><ElOption v-for="line in fabricSourceLines" :key="line.id || line.client_key" :label="`${line.part_name || '面料'} · ${line.fabric_color_name || line.material} · ${line.specification}`" :value="(line.id || line.client_key)!" /></ElSelect><small>已添加的面料可直接选择，保存 BOM 时一并保存关联。</small></template></label>
            <label class="drawer-field"><span>裁片量（片/套）</span><template v-if="legacyPipeCuttingValues(editingLineDraft)"><strong class="drawer-readonly-value cutting-legacy-value">{{ legacyPipeCuttingValues(editingLineDraft)?.pieces }}</strong></template><ElInput v-else v-model="editingLineDraft.cutting_pieces_per_set" inputmode="numeric" placeholder="每套有多少片" aria-label="裁片量（片/套）" /></label>
            <label class="drawer-field"><span>单个用量（米/片）</span><template v-if="legacyPipeCuttingValues(editingLineDraft)"><strong class="drawer-readonly-value cutting-legacy-value">{{ legacyPipeCuttingValues(editingLineDraft)?.metersPerPiece }}</strong></template><ElInput v-else v-model="editingLineDraft.fabric_meters_per_piece" inputmode="decimal" placeholder="正数，最多四位小数" aria-label="单个用量（米/片）" /></label>
            <label class="drawer-field"><span>每成品套数（套/成品）</span><template v-if="legacyPipeCuttingValues(editingLineDraft)"><strong class="drawer-readonly-value cutting-legacy-value">{{ legacyPipeCuttingValues(editingLineDraft)?.sets }}</strong></template><ElInput v-else v-model="editingLineDraft.cutting_sets_per_product" inputmode="numeric" placeholder="每个成品需要多少套" aria-label="每成品套数（套/成品）" /></label>
            <label class="drawer-field"><span>{{ editingCuttingCalculation?.mode === 'legacy' ? '原每套耗米（米/套）' : '每套耗米（米/套）' }}</span><ElInput v-if="editingCuttingCalculation?.mode === 'legacy'" v-model="editingLineDraft.fabric_meters_per_set" inputmode="decimal" aria-label="原每套耗米（米/套）" /><ElInput v-else :model-value="editingCuttingCalculation?.metersPerSet || ''" readonly placeholder="补齐后自动计算" aria-label="每套耗米（米/套）" /><small v-if="editingCuttingCalculation?.mode !== 'legacy'">裁片量 × 单个用量</small></label>
            <ElAlert v-if="editingCuttingCalculation?.error" data-testid="cutting-calculation-error" class="drawer-field--wide" type="warning" :closable="false" show-icon :title="editingCuttingCalculation.error" />
            <div class="cutting-order-calculations drawer-field--wide">
              <label class="drawer-field"><span>订单裁剪套数</span><strong data-testid="cutting-order-sets">{{ editingCuttingCalculation?.orderSets ? `${editingCuttingCalculation.orderSets} 套` : '待补充' }}</strong><small>BOM 订单 {{ number(bom?.order_quantity) }} × 每成品套数</small></label>
              <label class="drawer-field"><span>订单裁剪片数</span><strong data-testid="cutting-order-pieces">{{ editingCuttingCalculation?.orderPieces ? `${editingCuttingCalculation.orderPieces} 片` : '待补充' }}</strong><small>订单套数 × 裁片量</small></label>
              <label class="drawer-field"><span>订单耗米</span><strong data-testid="cutting-total-meters">{{ editingCuttingCalculation?.totalMeters ? `${editingCuttingCalculation.totalMeters} 米` : '待补充' }}</strong><small>订单套数 × 每套耗米</small></label>
            </div>
            <label class="drawer-field"><span>裁剪名称</span><strong class="drawer-readonly-value">{{ editingLineDraft.part_name || '—' }}</strong></label>
            <label class="drawer-field"><span>规格</span><ElInput v-model="editingLineDraft.specification" maxlength="500" placeholder="填写规格" aria-label="规格" /></label>
            <label class="drawer-field"><span>流转单位</span><ElInput v-if="editingCuttingCalculation?.mode === 'legacy'" v-model="editingLineDraft.unit" maxlength="50" placeholder="填写单位" aria-label="单位" /><strong v-else class="drawer-readonly-value">套</strong></label>
            <label class="drawer-field"><span>材质</span><ElInput :model-value="cuttingMaterial(editingLineDraft)" maxlength="200" placeholder="填写材质" aria-label="材质" @update:model-value="editingLineDraft.material = $event" /></label>
            <label class="drawer-field"><span>颜色</span><strong class="drawer-readonly-value">{{ formatHardwareColor(editingLineDraft.cutting_color) }}</strong></label>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="3" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>

          <template v-else>
            <label class="drawer-field"><span>材质</span><ElInput v-model="editingLineDraft.material" aria-label="材质" /></label>
            <label class="drawer-field"><span>配件 / 裁片名称</span><ElInput v-model="editingLineDraft.part_name" aria-label="配件或裁片名称" /></label>
            <label v-if="editingSection?.section_type !== 'FABRIC'" class="drawer-field"><span>规格 / 厚度</span><ElInput v-model="editingLineDraft.specification" aria-label="规格或厚度" /></label>
            <label v-if="editingSection?.section_type === 'FABRIC'" class="drawer-field"><span>原材料</span><ElInput v-model="editingLineDraft.raw_material" aria-label="原材料" /></label>
            <label v-if="editingSection?.section_type === 'FABRIC'" class="drawer-field"><span>裁片量</span><ElInput v-model="editingLineDraft.cut_piece_quantity" aria-label="裁片量" /></label>
            <label class="drawer-field"><span>单耗</span><ElInput v-model="editingLineDraft.unit_consumption" aria-label="单耗" /></label>
            <label class="drawer-field"><span>当前需求</span><ElInput v-model="editingLineDraft.total_consumption" aria-label="当前需求" /></label>
            <label class="drawer-field"><span>单位</span><ElInput v-model="editingLineDraft.unit" aria-label="单位" /></label>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="4" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>
          <section v-if="editingSection?.section_type !== 'PROFILE'" class="drawer-image-action drawer-field--wide">
            <div><strong>用料图片</strong><span>{{ displayLineImages(editingLineDraft).length }} / 20</span></div>
            <ElButton size="small" plain type="primary" @click="openLineImageManager()">
              {{ displayLineImages(editingLineDraft).length ? '管理图片' : '上传图片' }}
            </ElButton>
          </section>
        </div>
        <template #footer>
          <div class="line-drawer-footer">
            <ElButton :disabled="Boolean(uploadingCuttingImagesLineId || deletingCuttingImageId || cleaningCuttingDraftImages)" @click="cancelLineDrawer">取消</ElButton>
            <ElButton :loading="calculatingLine" :disabled="saving || Boolean(uploadingCuttingImagesLineId || deletingCuttingImageId || cleaningCuttingDraftImages)" @click="applyLineDrawer">应用修改</ElButton>
            <ElButton type="primary" :disabled="saving || calculatingLine || advancingLineDrawer || Boolean(uploadingCuttingImagesLineId || deletingCuttingImageId || cleaningCuttingDraftImages)" @click="saveAndEditNextLine">{{ drawerNextActionLabel }}</ElButton>
          </div>
        </template>
      </BomLineEditorDialog>

      <AppWindowDialog
        v-model="imageManagerVisible"
        class="line-image-manager-dialog"
        title="用料图片"
        width="860px"
        append-to-body
        destroy-on-close
        :z-index="imageManagerZIndex"
        :close-on-click-modal="false"
        :before-close="beforeImageManagerClose"
        @closed="resetImageManager"
      >
        <div v-if="editingLineDraft" class="line-image-manager">
          <header class="line-image-manager-toolbar">
            <div>
              <strong>{{ editingSection?.title }} · 第 {{ editingLineIndex + 1 }} 行</strong>
              <span>{{ editingLineDraft.part_name || '未填写品名' }} · {{ displayLineImages(editingLineDraft).length }} / 20 张</span>
            </div>
            <ElButton
              size="small"
              plain
              type="primary"
              :loading="Boolean(uploadingCuttingImagesLineId)"
              :disabled="imageManagerIsBusy() || displayLineImages(editingLineDraft).length >= 20"
              @click="openImageFilePicker"
            >
              {{ uploadingCuttingImagesLineId ? '上传中…' : '上传图片' }}
            </ElButton>
            <input
              ref="imageFileInput"
              class="line-image-file-input"
              type="file"
              multiple
              accept=".jpg,.jpeg,.png,.gif,.webp,image/jpeg,image/png,image/gif,image/webp"
              aria-label="上传用料图片"
              :disabled="imageManagerIsBusy() || displayLineImages(editingLineDraft).length >= 20"
              @change="uploadLineImages"
            >
          </header>
          <div v-if="displayLineImages(editingLineDraft).length" class="cutting-image-grid">
            <article v-for="image in sortedLineImages(editingLineDraft)" :key="image.id">
              <ElImage :src="bomLineImageUrl(image.content_url)" :preview-src-list="sortedLineImages(editingLineDraft).map((item) => bomLineImageUrl(item.content_url))" preview-teleported fit="cover" />
              <div><strong :title="image.name">{{ image.name }}</strong><span>{{ fileSizeText(image.size_bytes) }}</span></div>
              <ElButton type="danger" link :loading="deletingCuttingImageId === image.id" :disabled="imageManagerIsBusy()" @click="removeLineImage(image)">删除</ElButton>
            </article>
          </div>
          <ElEmpty v-else :image-size="64" description="暂无用料图片，点击右上角按钮上传" />
        </div>
        <template #footer>
          <ElButton type="primary" :disabled="imageManagerIsBusy()" @click="closeImageManager">完成</ElButton>
        </template>
      </AppWindowDialog>

      <AppWindowDialog
        v-model="hardwarePickerVisible"
        class="hardware-picker-dialog"
        title="选择五金数据"
        width="1180px"
        append-to-body
        destroy-on-close
        :close-on-click-modal="false"
        @closed="resetHardwarePicker"
      >
        <div class="hardware-picker-source">
          <strong>数据来源：原料信息 / 材料 / 五金</strong>
          <span>只显示“五金”类别，支持跨页多选；确认后写入当前 BOM，不会修改原料主数据。</span>
        </div>
        <div class="hardware-picker-toolbar hardware-picker-toolbar--hardware">
          <ElSelect
            v-model="hardwarePickerMaterialName"
            clearable
            filterable
            :value-on-clear="''"
            :loading="hardwareGroupLoading"
            placeholder="全部品名分组"
            aria-label="五金品名分组"
            :filter-method="filterHardwareGroups"
            @change="searchHardwareCandidates"
            @visible-change="clearHardwareGroupFilter"
          >
            <ElOption
              v-for="group in visibleHardwareGroups"
              :key="group.material_name"
              :label="`${group.material_name}（${group.count}）`"
              :value="group.material_name"
            />
          </ElSelect>
          <ElInput v-model="hardwarePickerKeyword" clearable maxlength="100" placeholder="搜索品号、品名、材质、颜色或规格" @keyup.enter="searchHardwareCandidates" @clear="searchHardwareCandidates" />
          <ElButton type="primary" @click="searchHardwareCandidates">查询</ElButton>
          <ElTooltip
            :disabled="canCreateHardwareRawMaterial"
            content="需要“查看原料信息”和“新增原料信息”权限"
            placement="top"
          >
            <span class="hardware-create-button-wrap">
              <ElButton
                data-testid="hardware-create-raw-material"
                :icon="Plus"
                :disabled="!canCreateHardwareRawMaterial"
                @click="openHardwareCreate"
              >
                新增五金原料
              </ElButton>
            </span>
          </ElTooltip>
        </div>
        <ElAlert v-if="hardwareGroupError" class="hardware-picker-error" type="warning" :title="hardwareGroupError" show-icon :closable="false">
          <template #default><ElButton size="small" @click="loadHardwareGroups">重新加载品名分组</ElButton></template>
        </ElAlert>
        <ElAlert v-if="hardwarePickerError" class="hardware-picker-error" type="error" :title="hardwarePickerError" show-icon :closable="false">
          <template #default><ElButton size="small" @click="loadHardwareCandidates">重新加载</ElButton></template>
        </ElAlert>
        <ElTable
          v-loading="hardwarePickerLoading"
          class="hardware-picker-table"
          :data="hardwareCandidates"
          row-key="id"
          border
          max-height="460"
          empty-text="暂无符合条件的五金数据"
          :row-class-name="hardwarePickerRowClass"
          @row-click="toggleHardwareRow"
        >
          <ElTableColumn width="52" align="center" header-align="center">
            <template #header>
              <ElCheckbox :model-value="hardwarePageAllSelected" :indeterminate="hardwarePageSelectionIndeterminate" aria-label="全选当前页五金数据" @change="toggleHardwarePage" />
            </template>
            <template #default="scope">
              <ElCheckbox :model-value="Boolean(selectedHardware[scope.row.id])" :aria-label="`选择 ${scope.row.material_name}`" @click.stop @change="toggleHardwareCandidate(scope.row, $event)" />
            </template>
          </ElTableColumn>
          <ElTableColumn prop="material_number" label="品号" width="130" show-overflow-tooltip />
          <ElTableColumn prop="material_name" label="品名" min-width="165" show-overflow-tooltip><template #default="scope"><span v-if="pendingRawMaterials[scope.row.id]" class="pending-material-label">暂存</span>{{ scope.row.material_name }}</template></ElTableColumn>
          <ElTableColumn prop="material" label="材质" width="100" show-overflow-tooltip />
          <ElTableColumn label="颜色" min-width="130" show-overflow-tooltip><template #default="scope">{{ formatHardwareColor(scope.row.color_name) }}</template></ElTableColumn>
          <ElTableColumn prop="specification" label="规格" min-width="150" show-overflow-tooltip />
          <ElTableColumn prop="unit_name" label="单位" width="76" />
          <ElTableColumn label="单个材料重量（kg）" width="160"><template #default="scope">{{ scope.row.weight_kg || '待填写' }}</template></ElTableColumn>
          <ElTableColumn label="流转单位" width="90"><template #default="scope">{{ scope.row.flow_unit || '—' }}</template></ElTableColumn>
        </ElTable>
        <div class="hardware-picker-pagination">
          <span>已选择 {{ selectedHardwareCount }} 条</span>
          <ElPagination :current-page="hardwarePickerPage" :page-size="hardwarePickerPageSize" :total="hardwarePickerTotal" layout="total, prev, pager, next" @current-change="changeHardwarePage" />
        </div>
        <template #footer>
          <div class="hardware-picker-footer">
            <span>确认后可在五金件表格中填写用量、单重和喷塑信息。</span>
            <div>
              <ElButton @click="hardwarePickerVisible = false">取消</ElButton>
              <ElButton type="primary" :disabled="!selectedHardwareCount" @click="confirmHardwareSelection">确认添加（{{ selectedHardwareCount }}）</ElButton>
            </div>
          </div>
        </template>
      </AppWindowDialog>

      <HardwareRawMaterialCreateDialog
        v-model="hardwareCreateVisible"
        category-name="五金"
        title="新增五金原料"
        subject-label="五金原料"
        :stage-material="(payload, display) => stageRawMaterial('hardware', payload, display)"
      />

      <AppWindowDialog
        v-model="plasticPickerVisible"
        class="hardware-picker-dialog"
        title="选择塑料件数据"
        width="1180px"
        append-to-body
        destroy-on-close
        :close-on-click-modal="false"
        @closed="resetPlasticPicker"
      >
        <div class="hardware-picker-source">
          <strong>数据来源：原料信息 / 材料 / 塑料件</strong>
          <span>支持搜索、分页和跨页多选；确认后只在当前 BOM 中填写用量和备注。</span>
        </div>
        <div class="hardware-picker-toolbar hardware-picker-toolbar--grouped">
          <ElSelect v-model="plasticPickerMaterialName" clearable filterable :value-on-clear="''" :loading="plasticGroupLoading" placeholder="全部品名分组" aria-label="塑料件品名分组" :filter-method="filterPlasticGroups" @change="searchPlasticCandidates" @visible-change="clearPlasticGroupFilter">
            <ElOption v-for="group in visiblePlasticGroups" :key="group.material_name" :label="`${group.material_name}（${group.count}）`" :value="group.material_name" />
          </ElSelect>
          <ElInput v-model="plasticPickerKeyword" clearable maxlength="100" placeholder="搜索品号、品名、材质、颜色或规格" @keyup.enter="searchPlasticCandidates" @clear="searchPlasticCandidates" />
          <ElButton type="primary" @click="searchPlasticCandidates">查询</ElButton>
          <ElButton :icon="Plus" :disabled="!canCreateRawMaterial" @click="openRawMaterialCreate('plastic')">新增原料</ElButton>
        </div>
        <ElAlert v-if="plasticGroupError" class="hardware-picker-error" type="warning" :title="plasticGroupError" show-icon :closable="false">
          <template #default><ElButton size="small" @click="loadPlasticGroups">重新加载品名分组</ElButton></template>
        </ElAlert>
        <ElAlert v-if="plasticPickerError" class="hardware-picker-error" type="error" :title="plasticPickerError" show-icon :closable="false">
          <template #default><ElButton size="small" @click="loadPlasticCandidates">重新加载</ElButton></template>
        </ElAlert>
        <ElTable v-loading="plasticPickerLoading" class="plastic-picker-table picker-selectable-table" :data="plasticCandidates" row-key="id" border max-height="460" empty-text="暂无符合条件的塑料件数据" :row-class-name="plasticPickerRowClass" @row-click="togglePlasticRow">
          <ElTableColumn width="52" align="center" header-align="center">
            <template #header><ElCheckbox :model-value="plasticPageAllSelected" :indeterminate="plasticPageSelectionIndeterminate" aria-label="全选当前页塑料件数据" @change="togglePlasticPage" /></template>
            <template #default="scope"><ElCheckbox :model-value="Boolean(selectedPlastic[scope.row.id])" :aria-label="`选择 ${scope.row.material_name}`" @click.stop @change="togglePlasticCandidate(scope.row, $event)" /></template>
          </ElTableColumn>
          <ElTableColumn prop="material_number" label="品号" width="145" show-overflow-tooltip />
          <ElTableColumn prop="material_name" label="品名" min-width="190" show-overflow-tooltip><template #default="scope"><span v-if="pendingRawMaterials[scope.row.id]" class="pending-material-label">暂存</span>{{ scope.row.material_name }}</template></ElTableColumn>
          <ElTableColumn prop="material" label="材质" width="120" show-overflow-tooltip />
          <ElTableColumn label="颜色" min-width="145" show-overflow-tooltip><template #default="scope">{{ formatHardwareColor(scope.row.color_name) }}</template></ElTableColumn>
          <ElTableColumn prop="specification" label="规格" min-width="170" show-overflow-tooltip />
          <ElTableColumn prop="unit_name" label="单位" width="90" />
        </ElTable>
        <div class="hardware-picker-pagination">
          <span>已选择 {{ selectedPlasticCount }} 条</span>
          <ElPagination :current-page="plasticPickerPage" :page-size="plasticPickerPageSize" :total="plasticPickerTotal" layout="total, prev, pager, next" @current-change="changePlasticPage" />
        </div>
        <template #footer>
          <div class="hardware-picker-footer">
            <span>确认后保留主数据快照，表格中只需填写单个用量和备注。</span>
            <div><ElButton @click="plasticPickerVisible = false">取消</ElButton><ElButton type="primary" :disabled="!selectedPlasticCount" @click="confirmPlasticSelection">确认添加（{{ selectedPlasticCount }}）</ElButton></div>
          </div>
        </template>
      </AppWindowDialog>

      <AppWindowDialog
        v-model="auxiliaryPickerVisible"
        class="hardware-picker-dialog"
        title="选择辅料品名"
        width="1180px"
        append-to-body
        destroy-on-close
        :close-on-click-modal="false"
        @closed="resetAuxiliaryPicker"
      >
        <div class="hardware-picker-source">
          <strong>数据来源：系统设置 / 生产维护 / 辅料维护</strong>
          <span>同一品名后续可以再次添加，以填写不同的规格、颜色或材质组合。</span>
        </div>
        <div class="hardware-picker-toolbar hardware-picker-toolbar--grouped">
          <PinyinFilterSelect v-model="auxiliaryPickerProductName" :options="editorReferenceOptions?.auxiliary_products || []" label-key="product_name" :loading="editorReferenceOptionsLoading" placeholder="全部品名分组" aria-label="辅料品名分组" @update:model-value="searchAuxiliaryCandidates" />
          <ElInput v-model="auxiliaryPickerKeyword" clearable maxlength="100" placeholder="搜索辅料品名、规格或颜色" @keyup.enter="searchAuxiliaryCandidates" @clear="searchAuxiliaryCandidates" />
          <ElButton type="primary" @click="searchAuxiliaryCandidates">查询</ElButton>
          <ElButton :icon="Plus" @click="openAuxiliaryCreate">新增辅料资料</ElButton>
        </div>
        <ElAlert v-if="editorReferenceOptionsError" class="hardware-picker-error" type="error" :title="editorReferenceOptionsError" show-icon :closable="false">
          <template #default><ElButton size="small" @click="ensureEditorReferenceOptions">重新加载</ElButton></template>
        </ElAlert>
        <ElTable v-loading="editorReferenceOptionsLoading" class="auxiliary-picker-table picker-selectable-table" :data="auxiliaryCandidates" row-key="id" border max-height="460" empty-text="暂无符合条件的辅料品名" :row-class-name="auxiliaryPickerRowClass" @row-click="toggleAuxiliaryRow">
          <ElTableColumn width="52" align="center" header-align="center">
            <template #header><ElCheckbox :model-value="auxiliaryPageAllSelected" :indeterminate="auxiliaryPageSelectionIndeterminate" aria-label="全选当前页可选辅料" @change="toggleAuxiliaryPage" /></template>
            <template #default="scope"><ElTooltip :disabled="auxiliaryProductMaintenanceTip(scope.row) === '可选择'" :content="auxiliaryProductMaintenanceTip(scope.row)" placement="right"><span><ElCheckbox :model-value="Boolean(selectedAuxiliaryProducts[scope.row.id])" :disabled="!auxiliaryProductIsSelectable(scope.row)" :aria-label="`选择 ${scope.row.product_name}`" @click.stop @change="toggleAuxiliaryCandidate(scope.row, $event)" /></span></ElTooltip></template>
          </ElTableColumn>
          <ElTableColumn prop="product_name" label="品名" min-width="180" show-overflow-tooltip />
          <ElTableColumn label="归属规格" min-width="230" show-overflow-tooltip><template #default="scope">{{ auxiliarySpecificationSummary(scope.row) }}</template></ElTableColumn>
          <ElTableColumn label="归属颜色" min-width="230" show-overflow-tooltip><template #default="scope">{{ auxiliaryColorSummary(scope.row) }}</template></ElTableColumn>
          <ElTableColumn label="单位" width="90"><template #default="scope">{{ scope.row.unit_name || '待维护' }}</template></ElTableColumn>
          <ElTableColumn label="状态" width="150" align="center"><template #default="scope"><span class="picker-status-tag" :class="auxiliaryProductMaintenanceTip(scope.row) === '可选择' ? 'is-success' : 'is-warning'">{{ auxiliaryProductMaintenanceTip(scope.row) }}</span></template></ElTableColumn>
        </ElTable>
        <div class="hardware-picker-pagination">
          <span>已选择 {{ selectedAuxiliaryProductCount }} 条</span>
          <ElPagination :current-page="auxiliaryPickerPage" :page-size="auxiliaryPickerPageSize" :total="auxiliaryPickerTotal" layout="total, prev, pager, next" @current-change="changeAuxiliaryPage" />
        </div>
        <template #footer>
          <div class="hardware-picker-footer">
            <span>缺少归属规格或颜色时不能选择；缺少单位时可添加，但需到“辅料维护”补全。</span>
            <div><ElButton @click="auxiliaryPickerVisible = false">取消</ElButton><ElButton type="primary" :disabled="!selectedAuxiliaryProductCount" @click="confirmAuxiliarySelection">确认添加（{{ selectedAuxiliaryProductCount }}）</ElButton></div>
          </div>
        </template>
      </AppWindowDialog>

      <AppWindowDialog
        v-model="packagingPickerVisible"
        class="hardware-picker-dialog"
        title="选择包材数据"
        width="1180px"
        append-to-body
        destroy-on-close
        :close-on-click-modal="false"
        @closed="resetPackagingPicker"
      >
        <div class="hardware-picker-source">
          <strong>数据来源：原料信息 / 材料 / 包材</strong>
          <span>支持品名分组、关键词、分页和跨页多选；确认后填写箱数与单个用量。</span>
        </div>
        <div class="hardware-picker-toolbar hardware-picker-toolbar--grouped">
          <ElSelect v-model="packagingPickerMaterialName" clearable filterable :value-on-clear="''" :loading="packagingGroupLoading" placeholder="全部品名分组" aria-label="包材品名分组" :filter-method="filterPackagingGroups" @change="searchPackagingCandidates" @visible-change="clearPackagingGroupFilter">
            <ElOption v-for="group in visiblePackagingGroups" :key="group.material_name" :label="`${group.material_name}（${group.count}）`" :value="group.material_name" />
          </ElSelect>
          <ElInput v-model="packagingPickerKeyword" clearable maxlength="100" placeholder="搜索品号、品名、材质、颜色或规格" @keyup.enter="searchPackagingCandidates" @clear="searchPackagingCandidates" />
          <ElButton type="primary" @click="searchPackagingCandidates">查询</ElButton>
          <ElButton :icon="Plus" :disabled="!canCreateRawMaterial" @click="openRawMaterialCreate('packaging')">新增原料</ElButton>
        </div>
        <ElAlert v-if="packagingGroupError" class="hardware-picker-error" type="warning" :title="packagingGroupError" show-icon :closable="false"><template #default><ElButton size="small" @click="loadPackagingGroups">重新加载品名分组</ElButton></template></ElAlert>
        <ElAlert v-if="packagingPickerError" class="hardware-picker-error" type="error" :title="packagingPickerError" show-icon :closable="false"><template #default><ElButton size="small" @click="loadPackagingCandidates">重新加载</ElButton></template></ElAlert>
        <ElTable v-loading="packagingPickerLoading" class="packaging-picker-table picker-selectable-table" :data="packagingCandidates" row-key="id" border max-height="460" empty-text="暂无符合条件的包材数据" :row-class-name="packagingPickerRowClass" @row-click="togglePackagingRow">
          <ElTableColumn width="52" align="center" header-align="center">
            <template #header><ElCheckbox :model-value="packagingPageAllSelected" :indeterminate="packagingPageSelectionIndeterminate" aria-label="全选当前页包材数据" @change="togglePackagingPage" /></template>
            <template #default="scope"><ElCheckbox :model-value="Boolean(selectedPackaging[scope.row.id])" :aria-label="`选择 ${scope.row.material_name}`" @click.stop @change="togglePackagingCandidate(scope.row, $event)" /></template>
          </ElTableColumn>
          <ElTableColumn prop="material_number" label="品号" width="140" show-overflow-tooltip />
          <ElTableColumn prop="material_name" label="品名" min-width="180" show-overflow-tooltip><template #default="scope"><span v-if="pendingRawMaterials[scope.row.id]" class="pending-material-label">暂存</span>{{ scope.row.material_name }}</template></ElTableColumn>
          <ElTableColumn prop="material" label="材质" width="115" show-overflow-tooltip />
          <ElTableColumn label="颜色" min-width="135" show-overflow-tooltip><template #default="scope">{{ formatHardwareColor(scope.row.color_name) }}</template></ElTableColumn>
          <ElTableColumn prop="specification" label="规格" min-width="170" show-overflow-tooltip />
          <ElTableColumn prop="unit_name" label="单位" width="86" />
        </ElTable>
        <div class="hardware-picker-pagination"><span>已选择 {{ selectedPackagingCount }} 条</span><ElPagination :current-page="packagingPickerPage" :page-size="packagingPickerPageSize" :total="packagingPickerTotal" layout="total, prev, pager, next" @current-change="changePackagingPage" /></div>
        <template #footer><div class="hardware-picker-footer"><span>每箱装数不会从规格数字自动推断，需在 BOM 中人工填写。</span><div><ElButton @click="packagingPickerVisible = false">取消</ElButton><ElButton type="primary" :disabled="!selectedPackagingCount" @click="confirmPackagingSelection">确认添加（{{ selectedPackagingCount }}）</ElButton></div></div></template>
      </AppWindowDialog>

      <AppWindowDialog
        v-model="cuttingPickerVisible"
        class="hardware-picker-dialog"
        title="选择裁剪数据"
        width="1180px"
        append-to-body
        destroy-on-close
        :close-on-click-modal="false"
        @closed="resetCuttingPicker"
      >
        <div class="hardware-picker-source">
          <strong>数据来源：原料信息 / 半成品</strong>
          <span>支持品名分组、关键词、分页和跨页多选；确认后填写裁片量、颜色、图片和备注。</span>
        </div>
        <div class="hardware-picker-toolbar hardware-picker-toolbar--grouped">
          <ElSelect v-model="cuttingPickerMaterialName" clearable filterable :value-on-clear="''" :loading="cuttingGroupLoading" placeholder="全部品名分组" aria-label="裁剪品名分组" :filter-method="filterCuttingGroups" @change="searchCuttingCandidates" @visible-change="clearCuttingGroupFilter">
            <ElOption v-for="group in visibleCuttingGroups" :key="group.material_name" :label="`${group.material_name}（${group.count}）`" :value="group.material_name" />
          </ElSelect>
          <ElInput v-model="cuttingPickerKeyword" clearable maxlength="100" placeholder="搜索品号、品名、材质、颜色或规格" @keyup.enter="searchCuttingCandidates" @clear="searchCuttingCandidates" />
          <ElButton type="primary" @click="searchCuttingCandidates">查询</ElButton>
          <ElButton :icon="Plus" :disabled="!canCreateRawMaterial" @click="openRawMaterialCreate('cutting')">新增原料</ElButton>
        </div>
        <ElAlert v-if="cuttingGroupError" class="hardware-picker-error" type="warning" :title="cuttingGroupError" show-icon :closable="false"><template #default><ElButton size="small" @click="loadCuttingGroups">重新加载品名分组</ElButton></template></ElAlert>
        <ElAlert v-if="cuttingPickerError" class="hardware-picker-error" type="error" :title="cuttingPickerError" show-icon :closable="false"><template #default><ElButton size="small" @click="loadCuttingCandidates">重新加载</ElButton></template></ElAlert>
        <ElTable v-loading="cuttingPickerLoading" class="cutting-picker-table picker-selectable-table" :data="cuttingCandidates" row-key="id" border max-height="460" empty-text="暂无符合条件的裁剪数据" :row-class-name="cuttingPickerRowClass" @row-click="toggleCuttingRow">
          <ElTableColumn width="52" align="center" header-align="center">
            <template #header><ElCheckbox :model-value="cuttingPageAllSelected" :indeterminate="cuttingPageSelectionIndeterminate" aria-label="全选当前页裁剪数据" @change="toggleCuttingPage" /></template>
            <template #default="scope"><ElCheckbox :model-value="Boolean(selectedCutting[scope.row.id])" :aria-label="`选择 ${scope.row.material_name}`" @click.stop @change="toggleCuttingCandidate(scope.row, $event)" /></template>
          </ElTableColumn>
          <ElTableColumn prop="material_number" label="品号" width="135" show-overflow-tooltip />
          <ElTableColumn prop="material_name" label="裁剪名称" min-width="175" show-overflow-tooltip><template #default="scope"><span v-if="pendingRawMaterials[scope.row.id]" class="pending-material-label">暂存</span>{{ scope.row.material_name }}</template></ElTableColumn>
          <ElTableColumn prop="category_name" label="类别" width="120" show-overflow-tooltip />
          <ElTableColumn prop="material" label="材质" width="105" show-overflow-tooltip />
          <ElTableColumn label="颜色" min-width="125" show-overflow-tooltip><template #default="scope">{{ formatHardwareColor(scope.row.color_name) }}</template></ElTableColumn>
          <ElTableColumn prop="specification" label="规格" min-width="150" show-overflow-tooltip />
          <ElTableColumn prop="unit_name" label="单位" width="80" />
        </ElTable>
        <div class="hardware-picker-pagination"><span>已选择 {{ selectedCuttingCount }} 条</span><ElPagination :current-page="cuttingPickerPage" :page-size="cuttingPickerPageSize" :total="cuttingPickerTotal" layout="total, prev, pager, next" @current-change="changeCuttingPage" /></div>
        <template #footer><div class="hardware-picker-footer"><span>确认添加后即可打开行编辑抽屉批量上传图片，无需先保存 BOM。</span><div><ElButton @click="cuttingPickerVisible = false">取消</ElButton><ElButton type="primary" :disabled="!selectedCuttingCount" @click="confirmCuttingSelection">确认添加（{{ selectedCuttingCount }}）</ElButton></div></div></template>
      </AppWindowDialog>

      <HardwareRawMaterialCreateDialog
        v-model="plasticCreateVisible"
        category-name="塑料件"
        title="新增塑料件原料"
        subject-label="塑料件原料"
        test-id="plastic-raw-material-create-dialog"
        :stage-material="(payload, display) => stageRawMaterial('plastic', payload, display)"
      />
      <HardwareRawMaterialCreateDialog
        v-model="packagingCreateVisible"
        category-name="包材"
        title="新增包材原料"
        subject-label="包材原料"
        test-id="packaging-raw-material-create-dialog"
        :stage-material="(payload, display) => stageRawMaterial('packaging', payload, display)"
      />
      <HardwareRawMaterialCreateDialog
        v-model="cuttingCreateVisible"
        item-type="SEMI_FINISHED"
        title="新增半成品原料"
        subject-label="半成品原料"
        test-id="cutting-raw-material-create-dialog"
        :stage-material="(payload, display) => stageRawMaterial('cutting', payload, display)"
      />
      <AuxiliaryReferenceCreateDialog
        v-model="auxiliaryCreateVisible"
        @created="handleAuxiliaryCreated"
      />
      <AppWindowDialog v-if="pendingMaterialSave && materialSavePreview" :model-value="true" title="确认新增原料"
        width="min(980px, calc(100vw - 32px))" append-to-body :close-on-click-modal="false"
        :close-on-press-escape="!saving && !verifying" :show-close="!saving && !verifying"
        data-testid="bom-material-save-preview" class="bom-material-save-dialog"
        @update:model-value="(visible: boolean) => { if (!visible) cancelMaterialSave() }">
        <p class="material-save-summary">以下 {{ materialSavePreview.new_materials.length }} 项资料将在确认后新增，并与本次 BOM 一起保存。已有原料将直接复用。</p>
        <p v-if="materialSaveError" role="alert" class="material-save-error">{{ materialSaveError }}</p>
        <div class="material-save-table-scroll">
          <table class="material-save-table">
            <colgroup><col style="width: 11%"><col style="width: 7%"><col style="width: 16%"><col style="width: 21%"><col style="width: 12%"><col style="width: 13%"><col style="width: 7%"><col style="width: 13%"></colgroup>
            <thead><tr><th>分区</th><th>行号</th><th>品名</th><th>规格</th><th>颜色</th><th>材质</th><th>单位</th><th>仓库</th></tr></thead>
            <tbody><tr v-for="item in materialSavePreview.new_materials" :key="item.key" data-testid="bom-material-save-preview-row">
              <td><div v-for="location in materialLocationGroups(item)" :key="location.section">{{ location.section }}</div></td>
              <td><div v-for="location in materialLocationGroups(item)" :key="location.section">{{ location.rows }}</div></td>
              <td>{{ item.material_name || '—' }}<small v-if="item.item_type === 'SEMI_FINISHED'" class="material-save-kind">半成品</small></td>
              <td>{{ item.specification || '—' }}<small v-if="item.width" class="material-save-kind">门幅 {{ item.width }}</small></td><td>{{ item.color_label || item.color_name || '—' }}</td><td>{{ item.material || '—' }}</td><td>{{ item.unit_name || '—' }}</td><td>{{ item.warehouse_name || '—' }}</td>
            </tr></tbody>
          </table>
        </div>
        <template #footer>
          <ElButton data-testid="bom-material-save-cancel" :disabled="saving || verifying" @click="cancelMaterialSave">返回修改</ElButton>
          <ElButton data-testid="bom-material-save-confirm" type="primary" :loading="saving || verifying" :disabled="materialSaveRequiresRecheck" @click="confirmMaterialSave">{{ pendingMaterialSave.options.intent === 'verify' ? '确认新增并确认BOM' : '确认新增并保存草稿' }}</ElButton>
        </template>
      </AppWindowDialog>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;
.material-save-summary { margin: 0 0 16px; color: token.$crm-text-regular; line-height: 22px; }
.material-save-error { color: token.$crm-danger; margin: 0 0 12px; }
.material-save-table-scroll { max-height: min(480px, calc(100vh - 300px)); overflow: auto; }
.material-save-table { width: 100%; table-layout: fixed; border-collapse: collapse; color: token.$crm-text-primary; font-size: 13px; }
.material-save-table th, .material-save-table td { border: 1px solid token.$crm-border-default; padding: 10px 8px; line-height: 20px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
.material-save-table th { background: token.$crm-color-subtle; color: token.$crm-text-secondary; font-weight: 500; }
.material-save-kind { display: block; color: token.$crm-text-secondary; }
.pending-material-label { margin-right: 6px; color: token.$crm-warning; font-size: 12px; }
.bom-review-context { font-size: 13px; color: token.$crm-text-regular; h3 { margin: 20px 0 12px; font-size: 13px; line-height: 20px; color: token.$crm-text-primary; &:first-child { margin-top: 0; } } p { margin: 0; line-height: 20px; } dl { margin: 0; } dl > div { margin: 0 0 12px; } dt { color: token.$crm-text-secondary; margin-bottom: 4px; } dd { margin: 0; overflow-wrap: anywhere; } }
.bom-review-context__fields { display: grid; gap: 12px; label > span { display: block; margin-bottom: 8px; color: token.$crm-text-secondary; } :deep(.el-input__wrapper) { height: 32px; min-height: 32px; box-sizing: border-box; background: token.$crm-color-subtle; } }
.bom-review-context .bom-review-context__rule { margin-top: 20px; padding-top: 16px; border-top: 1px solid token.$crm-border-default; color: token.$crm-text-secondary; }

.bom-editor-page { min-width: 0; min-height: 0; padding: 0; box-sizing: border-box; background: transparent; color: var(--erp-color-text-primary); }
.page-state { min-height: min(760px, max(0px, calc(100dvh - 130px))); }
.bom-error-state__icon { display: block; width: 72px; height: 72px; }
.bom-error-state :deep(.bom-error-state__retry) { --el-button-bg-color: var(--erp-button-primary-background); --el-button-border-color: var(--erp-button-primary-background); --el-button-text-color: var(--erp-button-primary-text); --el-button-hover-bg-color: var(--erp-button-primary-hover-background); --el-button-hover-border-color: var(--erp-button-primary-hover-background); --el-button-active-bg-color: var(--erp-button-primary-pressed-background); --el-button-active-border-color: var(--erp-button-primary-pressed-background); min-width: 96px; height: 32px; border-radius: 5px; }
.editor-heading { min-height: 82px; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
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
.product-overview { display: grid; grid-template-columns: minmax(240px, 32%) minmax(0, 1fr); align-items: start; gap: 24px; margin-top: 16px; }
.product-details { min-width: 0; }
.product-details section + section { margin-top: 16px; padding-top: 16px; border-top: 1px solid token.$crm-border-default; }
.product-details h3 { margin: 0 0 8px; font-size: 13px; font-weight: 600; line-height: 20px; }
.product-details dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 24px; margin: 0; }
.product-details dl > div { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 8px; min-width: 0; font-size: 13px; line-height: 24px; }
.product-details dt { color: token.$crm-text-secondary; }
.product-details dd { margin: 0; color: token.$crm-text-primary; overflow-wrap: anywhere; }
.product-details .quantity-value { color: token.$crm-primary; font-weight: 600; }
.bom-product-info-dialog__hint { margin: 0 0 14px; color: var(--erp-color-text-secondary); font-size: 13px; }
.bom-product-info-dialog dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 16px; margin: 0; }
.bom-product-info-dialog dl > div { min-width: 0; padding: 10px 12px; border: 1px solid var(--erp-color-border); border-radius: 6px; background: var(--erp-color-subtle); }
.bom-product-info-dialog dt { margin-bottom: 4px; color: var(--erp-color-text-secondary); font-size: 12px; }
.bom-product-info-dialog dd { margin: 0; overflow-wrap: anywhere; color: var(--erp-color-text-primary); font-size: 13px; }
.quantity-warning { display: grid; grid-template-columns: minmax(0, 1fr) 440px auto; gap: 18px; align-items: center; min-height: 62px; margin-top: 12px; padding: 8px 14px; box-sizing: border-box; border: 1px solid var(--erp-color-warning-border); border-radius: 8px; background: var(--erp-color-warning-soft); color: var(--erp-color-warning); font-size: 12px; }
.quantity-warning__summary { display: flex; min-width: 0; flex-direction: column; gap: 5px; }
.quantity-warning strong { color: var(--erp-color-warning); }
.editor-grid { display: grid; grid-template-columns: 176px minmax(0, 1fr); gap: 14px; margin-top: 14px; align-items: stretch; }
.section-sidebar { min-width: 0; padding: 14px 0; overflow: hidden; }
.section-sidebar h2 { padding: 0 16px 12px; border-bottom: 1px solid var(--erp-color-border); }
.section-sidebar .section-tabs { display: grid; min-height: 0; gap: 0; overflow: visible; border: 0; }
.section-sidebar .section-tabs button { display: flex; width: 100%; height: 46px; align-items: center; justify-content: space-between; padding: 0 16px; border: 0; border-left: 3px solid transparent; color: var(--erp-color-text-secondary); text-align: left; }
.section-sidebar .section-tabs button b { color: var(--erp-color-text-muted); font-size: 12px; font-weight: 500; }
.section-sidebar .section-tabs button.active { border-bottom: 0; border-left-color: var(--erp-color-brand); color: var(--erp-color-brand); background: var(--erp-color-selected); }
.section-sidebar .section-tabs button.active b { color: var(--erp-color-brand); }
.material-card { min-width: 0; padding: 14px 12px 12px; }
.material-heading { padding: 0 4px 12px; }
.material-heading > div:first-child { display: flex; align-items: baseline; gap: 18px; }
.material-heading span { color: var(--erp-color-text-secondary); font-size: 12px; }
.material-actions { display: flex; gap: 8px; }
.section-tabs { display: flex; align-items: center; gap: 20px; min-height: 38px; overflow-x: auto; border-bottom: 1px solid var(--erp-color-border); }
.section-tabs button { height: 38px; flex: none; padding: 0 4px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--erp-color-text-secondary); cursor: pointer; white-space: nowrap; }
.section-tabs button.active { border-bottom-color: var(--erp-color-brand); color: var(--erp-color-brand); font-weight: 700; }
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
.cutting-legacy-value { display: flex; min-height: 32px; align-items: center; padding: 0 7px; box-sizing: border-box; border: 1px solid var(--erp-input-border); border-radius: 5px; background: var(--erp-input-readonly-background); color: var(--erp-input-readonly-text); font-variant-numeric: tabular-nums; }
.calculated-cell { display: flex; min-height: 32px; align-items: center; padding: 0 8px; box-sizing: border-box; border: 1px solid var(--erp-input-border); border-radius: 5px; background: var(--erp-input-readonly-background); color: var(--erp-input-readonly-text); font-variant-numeric: tabular-nums; }
.calculation-panel { @include detail.inset; margin-top: 12px; padding: 12px; }
.calculation-panel > header { display: flex; justify-content: space-between; color: var(--erp-color-text-secondary); font-size: 12px; }
.calculation-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 10px; }
.calculation-grid article { min-height: 72px; padding: 10px; box-sizing: border-box; border: 1px solid var(--erp-color-border); border-radius: 6px; background: var(--erp-color-surface); }
.calculation-grid article strong, .calculation-grid article span { display: block; font-size: 12px; }
.calculation-grid article span { margin-top: 8px; color: var(--erp-color-brand); line-height: 20px; }
.quantity-compare-card { margin-top: 12px; padding: 14px 16px; }
.quantity-compare-card > header { display: flex; align-items: baseline; gap: 18px; }
.quantity-compare-card > header span { color: var(--erp-color-text-secondary); font-size: 12px; }
.quantity-compare-grid { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)) minmax(260px, 1.65fr) auto; align-items: stretch; margin-top: 10px; }
.quantity-compare-grid label { min-height: 64px; padding: 8px 12px; border: 1px solid var(--erp-color-border); border-right: 0; background: var(--erp-color-surface); }
.quantity-compare-grid label span, .quantity-compare-grid label strong { display: block; }
.quantity-compare-grid label span { color: var(--erp-color-text-secondary); font-size: 11px; }
.quantity-compare-grid label strong { margin-top: 8px; font-size: 18px; font-variant-numeric: tabular-nums; }
.quantity-compare-grid label.difference strong { color: var(--erp-color-warning); }
.quantity-compare-grid > .el-input, .quantity-confirmed { min-height: 64px; box-sizing: border-box; border: 1px solid var(--erp-color-border); }
.quantity-compare-grid > .el-input :deep(.el-input__wrapper) { border-radius: 0; box-shadow: none; }
.quantity-confirmed { display: flex; align-items: center; padding: 0 14px; color: var(--erp-color-success); background: var(--erp-color-success-soft); font-size: 12px; }
.quantity-compare-grid > .el-button { height: 64px; margin-left: 10px; }
.line-editor-drawer :deep(.el-drawer__header) { margin-bottom: 0; padding-bottom: 18px; border-bottom: 1px solid var(--erp-color-border); color: var(--erp-color-text-primary); font-weight: 700; }
.line-editor-drawer :deep(.el-drawer__body) { padding: 20px; }
.line-editor-drawer :deep(.el-drawer__footer) { padding: 14px 20px; border-top: 1px solid var(--erp-color-border); }
.line-drawer-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 16px; }
.drawer-field { display: block; min-width: 0; }
.drawer-field > span { display: block; margin-bottom: 7px; color: var(--erp-color-text-secondary); font-size: 13px; }
.drawer-readonly-value { display: flex; min-height: 32px; align-items: center; padding: 7px 10px; box-sizing: border-box; border: 1px solid var(--erp-input-border); border-radius: 6px; background: var(--erp-input-readonly-background); color: var(--erp-input-readonly-text); font-size: 13px; font-weight: 500; }
.drawer-field--wide, .drawer-calculations { grid-column: 1 / -1; }
.drawer-calculations { padding-top: 2px; }
.cutting-name-tooltip-anchor.has-error { color: var(--erp-color-danger); cursor: help; text-decoration: underline dotted var(--erp-color-danger); text-underline-offset: 3px; }
:global(.cutting-name-error-tooltip.el-popper.is-light) { max-width: 280px; padding: 7px 10px; border-color: var(--erp-color-danger-border); background: var(--erp-color-danger-soft); color: var(--erp-color-danger); font-size: 12px; line-height: 18px; }
:global(.cutting-name-error-tooltip.el-popper.is-light .el-popper__arrow::before) { border-color: var(--erp-color-danger-border); background: var(--erp-color-danger-soft); }
.cutting-order-calculations { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; padding: 12px; border: 1px solid var(--erp-color-border); border-radius: 5px; background: var(--erp-color-subtle); }
.cutting-order-calculations strong { display: block; color: var(--erp-color-brand); font-size: 16px; line-height: 1.5; overflow-wrap: anywhere; }
.cutting-order-calculations small { display: block; margin-top: 5px; color: var(--erp-color-text-secondary); font-size: 12px; line-height: 1.5; }
.drawer-calculations h3 { margin: 0 0 10px; color: var(--erp-color-text-primary); font-size: 14px; }
.drawer-image-field-value { display: flex; min-height: 32px; align-items: center; justify-content: space-between; gap: 12px; padding: 0 10px; box-sizing: border-box; border: 1px solid var(--erp-color-border); border-radius: 6px; background: var(--erp-color-readonly); }
.drawer-image-field-value > span { color: var(--erp-color-text-secondary); font-size: 12px; }
.drawer-calculation-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.drawer-calculation-grid label { min-width: 0; padding: 10px; border: 1px solid var(--erp-color-border); border-radius: 6px; background: var(--erp-color-readonly); }
.drawer-calculation-grid span, .drawer-calculation-grid strong { display: block; }
.drawer-calculation-grid span { color: var(--erp-color-text-secondary); font-size: 12px; }
.drawer-calculation-grid strong { margin-top: 5px; overflow: hidden; color: var(--erp-color-text-regular); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.drawer-image-action { display: flex; min-height: 48px; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 10px; box-sizing: border-box; border: 1px solid var(--erp-color-border); border-radius: 6px; background: var(--erp-color-readonly); }
.drawer-image-action > div { display: flex; align-items: center; gap: 10px; }
.drawer-image-action strong { color: var(--erp-color-text-regular); font-size: 13px; }
.drawer-image-action span { color: var(--erp-color-text-secondary); font-size: 12px; }
.line-drawer-footer { display: flex; justify-content: flex-end; gap: 8px; }
.hardware-picker-source { display: flex; justify-content: space-between; gap: 20px; padding: 10px 12px; border: 1px solid var(--erp-color-border); border-radius: 5px; background: var(--erp-color-subtle); color: var(--erp-color-text-secondary); font-size: 12px; }
.hardware-picker-source strong { color: var(--erp-color-brand-hover); }
.hardware-picker-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; margin: 14px 0 12px; }
.hardware-picker-toolbar--hardware { grid-template-columns: 240px minmax(0, 1fr) auto auto; }
.hardware-picker-toolbar--grouped { grid-template-columns: 240px minmax(0, 1fr) auto auto; }
.hardware-create-button-wrap { display: inline-flex; }
.hardware-picker-error { margin-bottom: 12px; }
.hardware-picker-table :deep(.el-table__row) { cursor: pointer; }
.hardware-picker-table :deep(.el-table__row.is-picker-selected > td.el-table__cell) { background: var(--erp-table-selected); }
.picker-selectable-table :deep(.el-table__row) { cursor: pointer; }
.picker-selectable-table :deep(.el-table__row.is-picker-selected > td.el-table__cell) { background: var(--erp-table-selected); }
.picker-selectable-table :deep(.el-table__row.is-picker-disabled) { cursor: not-allowed; }
.hardware-picker-pagination { display: flex; min-height: 42px; align-items: center; justify-content: space-between; gap: 16px; color: var(--erp-color-text-regular); font-size: 13px; }
.hardware-picker-footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.hardware-picker-footer > span { color: var(--erp-color-text-secondary); font-size: 12px; }
.hardware-picker-footer > div { display: flex; gap: 8px; }
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
.line-image-manager { min-height: 310px; }
.line-image-manager-toolbar { position: relative; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding-bottom: 14px; border-bottom: 1px solid var(--erp-color-border); }
.line-image-manager-toolbar > div { min-width: 0; }
.line-image-manager-toolbar strong, .line-image-manager-toolbar span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.line-image-manager-toolbar strong { color: var(--erp-color-text-primary); font-size: 14px; }
.line-image-manager-toolbar span { margin-top: 5px; color: var(--erp-color-text-secondary); font-size: 12px; }
.line-image-file-input { position: absolute; width: 1px; height: 1px; overflow: hidden; opacity: 0; pointer-events: none; }
.cutting-image-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.cutting-image-grid article { display: grid; grid-template-columns: 72px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 8px; border: 1px solid var(--erp-color-border); border-radius: 6px; background: var(--erp-color-surface); }
.cutting-image-grid :deep(.el-image) { width: 72px; height: 56px; border-radius: 4px; background: var(--erp-color-readonly); }
.cutting-image-grid article > div { min-width: 0; }
.cutting-image-grid article > div strong, .cutting-image-grid article > div span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cutting-image-grid article > div strong { color: var(--erp-color-text-regular); font-size: 12px; }
.cutting-image-grid article > div span { margin-top: 5px; color: var(--erp-color-text-muted); font-size: 11px; }
/* BOM-V3-03：六类导航、行选择与下方物料明细编辑。 */
.editor-heading { min-height: 88px; }
.title-line { gap: 14px; }
.title-line h1 { font-family: "Noto Serif SC", "Songti SC", serif; font-size: 28px; line-height: 40px; letter-spacing: -.3px; }
.editor-status-tag { min-width: 48px; height: 26px; display: inline-flex; align-items: center; justify-content: center; padding: 0 12px; border-radius: 4px; color: var(--erp-tag-warning-text); background: var(--erp-tag-warning-background); font-size: 12px; font-weight: 500; }
.editor-status-tag.verified { color: var(--erp-tag-success-text); background: var(--erp-tag-success-background); }
.heading-actions .el-button { min-width: 94px; }
.heading-actions :deep(.el-button--primary:not(.is-disabled)) { color: var(--erp-button-primary-text); background: var(--erp-button-primary-background); border-color: var(--erp-button-primary-border); }
.section-sidebar { padding: 10px 0; }
.section-sidebar h2 { padding: 0 16px 10px; font-size: 14px; line-height: 22px; white-space: nowrap; }
.section-sidebar .section-tabs button { width: calc(100% - 12px); height: 46px; margin: 0 6px; padding: 0 12px; font-size: 13px; }
.section-sidebar .section-tabs button:disabled { cursor: default; opacity: 1; }
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
.quantity-compare-card { margin: 10px 0 0 188px; padding: 10px 12px; }
.quantity-compare-card > header h2 { font-family: "Noto Serif SC", "Songti SC", serif; font-size: 17px; }
.quantity-compare-grid { margin-top: 7px; }
.quantity-compare-grid label, .quantity-compare-grid > .el-input, .quantity-confirmed { min-height: 58px; }
.quantity-compare-grid label strong { margin-top: 6px; font-size: 17px; }
.quantity-compare-grid > .el-button { height: 58px; }
.bom-color-create-form { display: grid; grid-template-columns: 1fr 1fr; gap: 0 14px; }
.bom-color-create-form :deep(.el-form-item:last-child) { grid-column: 1 / -1; }

@media (max-width: 1400px) {
  .product-details dl { grid-template-columns: 1fr; }
  .editor-grid { grid-template-columns: 176px minmax(0, 1fr); }
  .quantity-compare-card { margin-left: 188px; }
  .quantity-compare-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .quantity-compare-grid label { border-right: 1px solid var(--erp-color-border); }
  .quantity-compare-grid > .el-button { min-width: 0; margin-left: 0; }
  .material-fields { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
</style>

<style lang="scss">
.bom-line-editor-dialog .el-dialog__body { max-height: 68vh; overflow-y: auto; }
.bom-line-editor-dialog .line-drawer-form { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px 16px; }
.bom-line-editor-dialog .drawer-field--wide, .bom-line-editor-dialog .drawer-calculations { grid-column: 1 / -1; }
.bom-line-editor-dialog .drawer-readonly-value { background: var(--erp-input-readonly-background); border-color: var(--erp-input-border); color: var(--erp-input-readonly-text); }
.bom-line-editor-dialog .drawer-field small { color: var(--erp-color-text-secondary); line-height: 1.5; }
.bom-line-editor-dialog .drawer-calculation-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.bom-line-editor-dialog .drawer-calculation-grid label { background: var(--erp-color-subtle); border-color: var(--erp-color-border); }
.bom-line-editor-dialog .drawer-calculation-grid label span, .bom-line-editor-dialog .drawer-calculation-grid label strong { color: var(--erp-color-text-regular); }
.bom-line-editor-dialog .app-window-dialog__footer { padding: 6px 24px 8px; }
</style>
