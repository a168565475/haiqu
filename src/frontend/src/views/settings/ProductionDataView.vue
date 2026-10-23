<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Delete, Edit, Plus, Refresh, Search, Upload } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  changeProductionDataStatus,
  clearProductColorImage,
  createProductionDataRecord,
  fetchAllAccessoryProductNames,
  fetchAllProductCategories,
  fetchProductionDataList,
  fetchProductionDataRecord,
  fetchProductionDataSummary,
  updateProductionDataRecord,
  uploadProductColorImage,
} from '@/api/productionData'
import { fetchAllInventoryRawMaterials } from '@/api/rawMaterials'
import { useAuthStore } from '@/stores/auth'
import type { ReferenceStatus } from '@/types/referenceData'
import type { RawMaterialInformation } from '@/types/rawMaterial'
import type {
  AccessoryProductName,
  ProductCategory,
  ProductColor,
  ProductItemType,
  ProductionDataRecord,
  ProductionDataResource,
  ProductionDataSummary,
} from '@/types/productionData'

const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })

interface CategoryDefinition {
  key:
    | 'category' | 'unit' | 'color' | 'item'
    | 'fabric-material' | 'fabric-specification' | 'fabric-width'
    | 'accessory-product-name' | 'accessory-specification' | 'accessory-color' | 'accessory-material'
    | 'tube-product-name' | 'tube-thickness' | 'tube-diameter'
    | 'tube-material' | 'tube-shape' | 'tube-coating-color'
  label: string
  title: string
  resource: ProductionDataResource
  permissionModel: string
  countKey: string
}

type MaintenanceGroupKey = 'production' | 'fabric' | 'accessory' | 'tube'

interface MaintenanceGroupDefinition {
  key: MaintenanceGroupKey
  label: string
  pendingText: string
  categories: CategoryDefinition[]
}

const productionCategories: CategoryDefinition[] = [
  { key: 'category', label: '类别维护', title: '产品类别', resource: 'product-categories', permissionModel: 'productcategory', countKey: 'product_categories' },
  { key: 'unit', label: '单位维护', title: '生产单位', resource: 'production-units', permissionModel: 'productionunit', countKey: 'production_units' },
  { key: 'color', label: '颜色维护', title: '产品颜色', resource: 'product-colors', permissionModel: 'productcolor', countKey: 'product_colors' },
  { key: 'item', label: '货号维护', title: '产品货号', resource: 'product-items', permissionModel: 'productitem', countKey: 'product_items' },
]

const fabricCategories: CategoryDefinition[] = [
  { key: 'fabric-material', label: '材质维护', title: '面料材质', resource: 'fabric-materials', permissionModel: 'fabricmaterial', countKey: 'fabric_materials' },
  { key: 'fabric-specification', label: '规格维护', title: '面料规格', resource: 'fabric-specifications', permissionModel: 'fabricspecification', countKey: 'fabric_specifications' },
  { key: 'fabric-width', label: '门幅维护', title: '面料门幅', resource: 'fabric-widths', permissionModel: 'fabricwidth', countKey: 'fabric_widths' },
]

const accessoryCategories: CategoryDefinition[] = [
  { key: 'accessory-product-name', label: '品名维护', title: '辅料品名', resource: 'accessory-product-names', permissionModel: 'accessoryproductname', countKey: 'accessory_product_names' },
  { key: 'accessory-specification', label: '规格维护', title: '辅料规格', resource: 'accessory-specifications', permissionModel: 'accessoryspecification', countKey: 'accessory_specifications' },
  { key: 'accessory-color', label: '颜色维护', title: '辅料颜色', resource: 'accessory-colors', permissionModel: 'accessorycolor', countKey: 'accessory_colors' },
  { key: 'accessory-material', label: '材质维护', title: '辅料材质', resource: 'accessory-materials', permissionModel: 'accessorymaterial', countKey: 'accessory_materials' },
]

const tubeCategories: CategoryDefinition[] = [
  { key: 'tube-product-name', label: '品名维护', title: '管材品名', resource: 'tube-product-names', permissionModel: 'tubeproductname', countKey: 'tube_product_names' },
  { key: 'tube-thickness', label: '厚度维护', title: '管材厚度', resource: 'tube-thicknesses', permissionModel: 'tubethickness', countKey: 'tube_thicknesses' },
  { key: 'tube-diameter', label: '直径维护', title: '管材直径', resource: 'tube-diameters', permissionModel: 'tubediameter', countKey: 'tube_diameters' },
  { key: 'tube-material', label: '材质维护', title: '管材材质', resource: 'tube-materials', permissionModel: 'tubematerial', countKey: 'tube_materials' },
  { key: 'tube-shape', label: '形状维护', title: '管材形状', resource: 'tube-shapes', permissionModel: 'tubeshape', countKey: 'tube_shapes' },
  { key: 'tube-coating-color', label: '喷塑颜色', title: '管材喷塑颜色', resource: 'tube-coating-colors', permissionModel: 'tubecoatingcolor', countKey: 'tube_coating_colors' },
]

const allCategories = [...productionCategories, ...fabricCategories, ...accessoryCategories, ...tubeCategories]

const maintenanceGroups: MaintenanceGroupDefinition[] = [
  { key: 'production', label: '生产维护', pendingText: '', categories: productionCategories },
  { key: 'fabric', label: '面料维护', pendingText: '', categories: fabricCategories },
  { key: 'accessory', label: '辅料维护', pendingText: '', categories: accessoryCategories },
  { key: 'tube', label: '管材维护', pendingText: '', categories: tubeCategories },
]

const itemTypeOptions: Array<{ value: ProductItemType; label: string }> = [
  { value: 'FINISHED', label: '成品' },
  { value: 'SEMI_FINISHED', label: '半成品' },
  { value: 'MATERIAL', label: '材料' },
]

const authStore = useAuthStore()
const isSuperuser = computed(() => authStore.user?.is_superuser === true)
function can(permission: string): boolean {
  return isSuperuser.value || authStore.hasPermission(permission)
}
function permission(category: CategoryDefinition, action: 'view' | 'add' | 'change'): string {
  return `reference_data.${action}_${category.permissionModel}`
}
function canView(category: CategoryDefinition): boolean {
  return can(permission(category, 'view'))
}

function visibleGroupCategoryCount(group: MaintenanceGroupDefinition): number {
  return group.categories.filter(canView).length
}

const selectedGroupKey = ref<MaintenanceGroupKey>('production')
const selectedGroup = computed(() => maintenanceGroups.find((item) => item.key === selectedGroupKey.value) ?? maintenanceGroups[0])
const visibleCategories = computed(() => selectedGroup.value.categories.filter(canView))
const canViewPage = computed(() => allCategories.some(canView))
const selectedKey = ref<CategoryDefinition['key']>('category')
const selectedCategory = computed(() => visibleCategories.value.find((item) => item.key === selectedKey.value) ?? allCategories[0])
const hasSelectedCategory = computed(() => visibleCategories.value.some((item) => item.key === selectedKey.value))
const canAddSelected = computed(() => hasSelectedCategory.value && can(permission(selectedCategory.value, 'add')))
function canChangeStatus(row: { status: string }): boolean {
  const action = row.status === 'ACTIVE' ? 'deactivate' : 'activate'
  return authStore.user?.module_access_enabled
    ? can('access_control.' + action + '_reference_' + selectedCategory.value.permissionModel)
    : canChangeSelected.value
}
const canChangeSelected = computed(() => hasSelectedCategory.value && can(permission(selectedCategory.value, 'change')))

const summary = ref<ProductionDataSummary>({ category_counts: {} })
const records = ref<ProductionDataRecord[]>([])
const loading = ref(false)
const loadError = ref('')
const keyword = ref('')
const statusFilter = ref<ReferenceStatus | ''>('')
const itemTypeFilter = ref<ProductItemType | ''>('')
const categoryFilter = ref('')
const productNameFilter = ref('')
const imageFilter = ref<'' | 'true' | 'false'>('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
let recordsRequestId = 0

const productCategories = ref<ProductCategory[]>([])
const accessoryProductNames = ref<AccessoryProductName[]>([])
const inventoryRawMaterials = ref<RawMaterialInformation[]>([])
let inventoryRawMaterialsLoaded = false
let inventoryRawMaterialsRequest: Promise<void> | null = null
const dialogVisible = ref(false)
const saving = ref(false)
const pendingActions = ref(0)
const editingId = ref('')
const currentEtag = ref('')
const fileInputKey = ref(0)
const selectedImageFile = ref<File | null>(null)
const imagePreviewUrl = ref('')
const clearExistingImage = ref(false)

const form = reactive({
  item_type: 'FINISHED' as ProductItemType,
  category_name: '',
  unit_code: '',
  unit_name: '',
  color_card: '',
  color_code: '',
  color_name: '',
  item_number: '',
  category: '',
  inventory_raw_material: '',
  material_name: '',
  specification_name: '',
  width_value: '',
  product_name: '',
  specification_value: '',
  weight: '',
  thickness_value: '',
  diameter_value: '',
  shape_name: '',
  sort_order: 0,
  description: '',
})

const dialogTitle = computed(() => `${editingId.value ? '编辑' : '新增'}${selectedCategory.value.title}`)

function canClose(): boolean {
  if (saving.value || pendingActions.value) {
    ElMessage.warning('生产资料操作进行中，请稍候再关闭。')
    return false
  }
  if (dialogVisible.value) {
    ElMessage.warning('请先保存或取消当前生产资料编辑。')
    return false
  }
  return true
}

defineExpose({ canClose })

function errorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  const fieldErrors = response?.data?.error?.field_errors
  if (fieldErrors) {
    const first = Object.values(fieldErrors).flat()[0]
    if (first) return first
  }
  return response?.data?.error?.message || response?.data?.detail || fallback
}

function statusCode(error: unknown): number | undefined {
  return (error as { response?: { status?: number } })?.response?.status
}

async function loadSummary(): Promise<void> {
  summary.value = await fetchProductionDataSummary()
}

async function loadCategoryChoices(): Promise<void> {
  if (!can('reference_data.view_productcategory')) return
  productCategories.value = await fetchAllProductCategories()
}

async function loadAccessoryNameChoices(): Promise<void> {
  if (!can('reference_data.view_accessoryproductname')) return
  accessoryProductNames.value = await fetchAllAccessoryProductNames()
}

async function loadInventoryRawMaterialChoices(): Promise<void> {
  if (!can('products.view_rawmaterialinformation')) {
    inventoryRawMaterials.value = []
    return
  }
  if (inventoryRawMaterialsLoaded) return
  if (!inventoryRawMaterialsRequest) {
    inventoryRawMaterialsRequest = fetchAllInventoryRawMaterials()
      .then((items) => {
        inventoryRawMaterials.value = items
        inventoryRawMaterialsLoaded = true
      })
      .catch((error) => {
        ElMessage.error(errorMessage(error, '库存原料加载失败，请稍后重试。'))
      })
      .finally(() => {
        inventoryRawMaterialsRequest = null
      })
  }
  await inventoryRawMaterialsRequest
}

async function loadRecords(): Promise<void> {
  const requestId = ++recordsRequestId
  if (!hasSelectedCategory.value || !canView(selectedCategory.value)) {
    records.value = []
    total.value = 0
    loading.value = false
    loadError.value = ''
    return
  }
  loading.value = true
  loadError.value = ''
  const requestedCategory = selectedCategory.value
  const requestedKey = selectedKey.value
  try {
    const response = await fetchProductionDataList(requestedCategory.resource, {
      page: page.value,
      page_size: pageSize.value,
      q: keyword.value.trim() || undefined,
      status: statusFilter.value,
      item_type: requestedKey === 'category' ? itemTypeFilter.value : undefined,
      category_id: requestedKey === 'item' ? categoryFilter.value || undefined : undefined,
      product_name_id: ['accessory-specification', 'accessory-color'].includes(requestedKey)
        ? productNameFilter.value || undefined
        : undefined,
      has_image: requestedKey === 'color' && imageFilter.value ? imageFilter.value === 'true' : undefined,
    })
    if (requestId !== recordsRequestId) return
    records.value = response.data
    total.value = response.meta.total
  } catch (error) {
    if (requestId !== recordsRequestId) return
    loadError.value = errorMessage(error, '生产资料加载失败，请稍后重试。')
    records.value = []
    total.value = 0
  } finally {
    if (requestId === recordsRequestId) loading.value = false
  }
}

async function reloadAll(): Promise<void> {
  try {
    await Promise.all([loadSummary(), loadRecords(), loadCategoryChoices(), loadAccessoryNameChoices()])
  } catch (error) {
    ElMessage.error(errorMessage(error, '生产资料刷新失败。'))
  }
}

function selectCategory(key: CategoryDefinition['key']): void {
  if (selectedKey.value === key) return
  selectedKey.value = key
}

function selectGroup(key: MaintenanceGroupKey): void {
  if (selectedGroupKey.value === key) return
  selectedGroupKey.value = key
  dialogVisible.value = false
  const firstVisible = visibleCategories.value[0]
  if (firstVisible) selectedKey.value = firstVisible.key
}

function runSearch(): void {
  page.value = 1
  void loadRecords()
}

function resetFilters(): void {
  keyword.value = ''
  statusFilter.value = ''
  itemTypeFilter.value = ''
  categoryFilter.value = ''
  productNameFilter.value = ''
  imageFilter.value = ''
  page.value = 1
  void loadRecords()
}

function resetImageSelection(): void {
  if (imagePreviewUrl.value.startsWith('blob:')) URL.revokeObjectURL(imagePreviewUrl.value)
  selectedImageFile.value = null
  imagePreviewUrl.value = ''
  clearExistingImage.value = false
  fileInputKey.value += 1
}

function resetForm(): void {
  Object.assign(form, {
    item_type: 'FINISHED',
    category_name: '',
    unit_code: '',
    unit_name: '',
    color_card: '',
    color_code: '',
    color_name: '',
    item_number: '',
    category: '',
    inventory_raw_material: '',
    material_name: '',
    specification_name: '',
    width_value: '',
    product_name: '',
    specification_value: '',
    weight: '',
    thickness_value: '',
    diameter_value: '',
    shape_name: '',
    sort_order: 0,
    description: '',
  })
  resetImageSelection()
}

async function openCreate(): Promise<void> {
  resetForm()
  editingId.value = ''
  currentEtag.value = ''
  if (selectedKey.value === 'item') await loadCategoryChoices()
  if (['accessory-specification', 'accessory-color'].includes(selectedKey.value)) await loadAccessoryNameChoices()
  if (['fabric-material', 'accessory-material'].includes(selectedKey.value)) await loadInventoryRawMaterialChoices()
  dialogVisible.value = true
}

async function openEdit(row: ProductionDataRecord): Promise<void> {
  try {
    const response = await fetchProductionDataRecord(selectedCategory.value.resource, row.id)
    resetForm()
    editingId.value = row.id
    currentEtag.value = response.etag
    const data = response.data as unknown as Record<string, unknown>
    for (const key of Object.keys(form) as Array<keyof typeof form>) {
      if (data[key] !== undefined && data[key] !== null) form[key] = data[key] as never
    }
    if (selectedKey.value === 'color') imagePreviewUrl.value = (response.data as ProductColor).image_url || ''
    if (selectedKey.value === 'item') await loadCategoryChoices()
    if (['accessory-specification', 'accessory-color'].includes(selectedKey.value)) await loadAccessoryNameChoices()
    if (['fabric-material', 'accessory-material'].includes(selectedKey.value)) await loadInventoryRawMaterialChoices()
    dialogVisible.value = true
  } catch (error) {
    ElMessage.error(errorMessage(error, '记录详情加载失败。'))
  }
}

function validateForm(): string {
  if (selectedKey.value === 'category' && !form.category_name.trim()) return '请填写品号类别。'
  if (selectedKey.value === 'unit' && (!form.unit_code.trim() || !form.unit_name.trim())) return '请填写单位编号和单位名称。'
  if (selectedKey.value === 'color' && (!form.color_card.trim() || !form.color_code.trim() || !form.color_name.trim())) return '请填写色卡、色号和颜色名称。'
  if (selectedKey.value === 'item' && (!form.item_number.trim() || !form.category)) return '请填写货号并选择产品类别。'
  if (selectedKey.value === 'fabric-material' && !form.material_name.trim()) return '请填写面料材质。'
  if (selectedKey.value === 'fabric-specification' && !form.specification_name.trim()) return '请填写面料规格。'
  if (selectedKey.value === 'fabric-width' && !form.width_value.trim()) return '请填写面料门幅。'
  if (selectedKey.value === 'accessory-product-name' && (!form.product_name.trim() || !form.unit_name.trim())) return '请填写辅料品名和单位。'
  if (selectedKey.value === 'accessory-specification' && (!form.product_name || !form.specification_value.trim())) return '请选择辅料品名并填写规格。'
  if (selectedKey.value === 'accessory-color' && (!form.product_name || !form.color_name.trim())) return '请选择辅料品名并填写颜色。'
  if (selectedKey.value === 'accessory-material' && !form.material_name.trim()) return '请填写辅料材质。'
  if (selectedKey.value === 'tube-product-name' && !form.product_name.trim()) return '请填写管材品名。'
  if (selectedKey.value === 'tube-thickness' && !form.thickness_value.trim()) return '请填写管材厚度。'
  if (selectedKey.value === 'tube-diameter' && !form.diameter_value.trim()) return '请填写管材直径。'
  if (selectedKey.value === 'tube-material' && !form.material_name.trim()) return '请填写管材材质。'
  if (selectedKey.value === 'tube-shape' && !form.shape_name.trim()) return '请填写管材形状。'
  if (selectedKey.value === 'tube-coating-color' && !form.color_name.trim()) return '请填写喷塑颜色。'
  if (!Number.isInteger(Number(form.sort_order)) || Number(form.sort_order) < 0) return '排序必须是大于或等于 0 的整数。'
  return ''
}

function normalizedPayload(): Record<string, unknown> {
  const common = { sort_order: Number(form.sort_order), description: form.description.trim() }
  if (selectedKey.value === 'category') return { ...common, item_type: form.item_type, category_name: form.category_name.trim() }
  if (selectedKey.value === 'unit') return { ...common, unit_code: form.unit_code.trim(), unit_name: form.unit_name.trim() }
  if (selectedKey.value === 'color') {
    return { ...common, color_card: form.color_card.trim(), color_code: form.color_code.trim(), color_name: form.color_name.trim() }
  }
  if (selectedKey.value === 'item') return { ...common, item_number: form.item_number.trim(), category: form.category }
  if (selectedKey.value === 'fabric-material') {
    return {
      ...common,
      material_name: form.material_name.trim(),
      inventory_raw_material: form.inventory_raw_material || null,
    }
  }
  if (selectedKey.value === 'fabric-specification') return { ...common, specification_name: form.specification_name.trim() }
  if (selectedKey.value === 'fabric-width') return { ...common, width_value: form.width_value.trim() }
  if (selectedKey.value === 'accessory-product-name') {
    return { ...common, product_name: form.product_name.trim(), unit_name: form.unit_name.trim() }
  }
  if (selectedKey.value === 'accessory-specification') {
    return {
      ...common,
      product_name: form.product_name,
      specification_value: form.specification_value.trim(),
      weight: form.weight.trim(),
    }
  }
  if (selectedKey.value === 'accessory-color') {
    return { ...common, product_name: form.product_name, color_name: form.color_name.trim() }
  }
  if (selectedKey.value === 'accessory-material') {
    return {
      ...common,
      material_name: form.material_name.trim(),
      inventory_raw_material: form.inventory_raw_material || null,
    }
  }
  if (selectedKey.value === 'tube-product-name') return { ...common, product_name: form.product_name.trim() }
  if (selectedKey.value === 'tube-thickness') return { ...common, thickness_value: form.thickness_value.trim() }
  if (selectedKey.value === 'tube-diameter') return { ...common, diameter_value: form.diameter_value.trim() }
  if (selectedKey.value === 'tube-material') return { ...common, material_name: form.material_name.trim() }
  if (selectedKey.value === 'tube-shape') return { ...common, shape_name: form.shape_name.trim() }
  return { ...common, color_name: form.color_name.trim() }
}

async function saveRecord(): Promise<void> {
  const validationMessage = validateForm()
  if (validationMessage) {
    ElMessage.warning(validationMessage)
    return
  }
  saving.value = true
  try {
    const saved = editingId.value
      ? await updateProductionDataRecord(selectedCategory.value.resource, editingId.value, normalizedPayload(), currentEtag.value)
      : await createProductionDataRecord(selectedCategory.value.resource, normalizedPayload())
    let savedEtag = saved.etag
    const savedId = saved.data.id
    if (selectedKey.value === 'color' && clearExistingImage.value && editingId.value) {
      const cleared = await clearProductColorImage(savedId, savedEtag)
      savedEtag = cleared.etag
    }
    if (selectedKey.value === 'color' && selectedImageFile.value) {
      try {
        await uploadProductColorImage(savedId, selectedImageFile.value, savedEtag)
      } catch (error) {
        editingId.value = savedId
        currentEtag.value = savedEtag
        ElMessage.warning(errorMessage(error, '资料已保存，但图片上传失败，请修正后重试。'))
        await Promise.all([loadSummary(), loadRecords()])
        return
      }
    }
    ElMessage.success(editingId.value ? '保存成功' : '新增成功')
    dialogVisible.value = false
    await Promise.all([loadSummary(), loadRecords(), loadCategoryChoices(), loadAccessoryNameChoices()])
  } catch (error) {
    if (statusCode(error) === 412) {
      ElMessage.warning('记录已被其他用户修改，请关闭窗口后重新打开。')
    } else {
      ElMessage.error(errorMessage(error, '保存失败，请检查填写内容。'))
    }
  } finally {
    saving.value = false
  }
}

function chooseImage(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const allowed = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
  if (!allowed.includes(file.type)) {
    ElMessage.warning('仅支持 JPG、PNG、GIF 或 WebP 图片。')
    input.value = ''
    return
  }
  if (file.size <= 0 || file.size > 5 * 1024 * 1024) {
    ElMessage.warning('图片必须大于 0 字节且不超过 5MB。')
    input.value = ''
    return
  }
  if (imagePreviewUrl.value.startsWith('blob:')) URL.revokeObjectURL(imagePreviewUrl.value)
  selectedImageFile.value = file
  imagePreviewUrl.value = URL.createObjectURL(file)
  clearExistingImage.value = false
}

function markImageForClear(): void {
  if (imagePreviewUrl.value.startsWith('blob:')) URL.revokeObjectURL(imagePreviewUrl.value)
  selectedImageFile.value = null
  imagePreviewUrl.value = ''
  clearExistingImage.value = true
  fileInputKey.value += 1
}

async function changeStatus(row: ProductionDataRecord): Promise<void> {
  const targetAction = row.status === 'ACTIVE' ? 'deactivate' : 'activate'
  const label = targetAction === 'deactivate' ? '停用' : '启用'
  pendingActions.value++
  try {
    const detail = await fetchProductionDataRecord(selectedCategory.value.resource, row.id)
    const result = await ElMessageBox.prompt(`请输入${label}原因`, `${label}${selectedCategory.value.title}`, {
      inputValidator: (value) => Boolean(value.trim()) || '原因不能为空',
      confirmButtonText: `确认${label}`,
    })
    await changeProductionDataStatus(selectedCategory.value.resource, row.id, targetAction, detail.etag, result.value.trim())
    ElMessage.success(`${label}成功`)
    await Promise.all([loadSummary(), loadRecords(), loadCategoryChoices(), loadAccessoryNameChoices()])
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorMessage(error, `${label}失败。`))
  } finally {
    pendingActions.value--
  }
}

watch([selectedGroupKey, selectedKey], () => {
  keyword.value = ''
  statusFilter.value = ''
  itemTypeFilter.value = ''
  categoryFilter.value = ''
  productNameFilter.value = ''
  imageFilter.value = ''
  page.value = 1
  void loadRecords()
})

onMounted(async () => {
  if (!canViewPage.value) return
  const firstGroup = maintenanceGroups.find((group) => group.categories.some(canView))
  if (firstGroup) selectedGroupKey.value = firstGroup.key
  const firstVisible = firstGroup?.categories.find(canView)
  if (firstVisible && !canView(selectedCategory.value)) selectedKey.value = firstVisible.key
  await reloadAll()
})

onBeforeUnmount(() => {
  if (imagePreviewUrl.value.startsWith('blob:')) URL.revokeObjectURL(imagePreviewUrl.value)
})
</script>

<template>
  <section class="production-page system-settings-theme erp-glass-list" data-testid="production-data-page">
    <div v-if="!canViewPage" class="state-page">
      <h1>无生产资料权限</h1>
      <p>当前账号无法查看生产维护，请联系管理员分配相应权限。</p>
    </div>

    <template v-else>
      <section v-glass-spotlight class="erp-list-filter">
      <header v-if="!props.embedded || !hasSelectedCategory" class="page-heading erp-list-heading">
        <div v-if="!props.embedded">
          <h1>生产维护</h1>
        </div>
        <div v-if="!hasSelectedCategory" class="page-heading__actions">
          <el-button class="erp-button-motion" :icon="Refresh" @click="reloadAll">刷新</el-button>
          <el-button class="erp-button-motion" v-if="canAddSelected" type="primary" :icon="Plus" @click="openCreate">新增{{ selectedCategory.title }}</el-button>
        </div>
      </header>

      <div class="metric-grid erp-list-tabs">
        <button
          v-for="item in maintenanceGroups"
          :key="item.key"
          type="button"
          :class="['metric-card', { active: selectedGroupKey === item.key }]"
          @click="selectGroup(item.key)"
        >
          <span>{{ item.label }}</span>
          <small>{{ item.categories.length ? `${visibleGroupCategoryCount(item)} 个设置项` : '待导入' }}</small>
        </button>
      </div>

          <div v-if="hasSelectedCategory" class="filter-row erp-list-filters">
            <el-input v-model="keyword" clearable :prefix-icon="Search" placeholder="搜索当前资料" @keyup.enter="runSearch" />
            <el-select v-model="statusFilter" clearable placeholder="全部状态">
              <el-option label="启用" value="ACTIVE" />
              <el-option label="停用" value="INACTIVE" />
            </el-select>
            <el-select v-if="selectedKey === 'category'" v-model="itemTypeFilter" clearable placeholder="全部品号类型">
              <el-option v-for="item in itemTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
            <el-select v-if="selectedKey === 'item'" v-model="categoryFilter" clearable filterable placeholder="全部产品类别">
              <el-option v-for="item in productCategories" :key="item.id" :label="item.category_name" :value="item.id" />
            </el-select>
            <el-select
              v-if="['accessory-specification', 'accessory-color'].includes(selectedKey)"
              v-model="productNameFilter"
              clearable
              filterable
              placeholder="全部辅料品名"
            >
              <el-option v-for="item in accessoryProductNames" :key="item.id" :label="item.product_name" :value="item.id" />
            </el-select>
            <el-select v-if="selectedKey === 'color'" v-model="imageFilter" clearable placeholder="全部图片状态">
              <el-option label="已有图片" value="true" />
              <el-option label="暂无图片" value="false" />
            </el-select>
            <div class="erp-list-filter-actions"><el-button class="erp-button-motion" @click="resetFilters">重置</el-button><el-button class="erp-button-motion" type="primary" @click="runSearch">应用筛选</el-button></div>
          </div>

      </section>
      <div class="content-layout">
        <aside class="category-panel erp-list-filter erp-list-catalog-nav">
          <h2>{{ selectedGroup.label }}</h2>
          <button
            v-for="item in visibleCategories"
            :key="item.key"
            type="button"
            :class="{ active: selectedKey === item.key }"
            @click="selectCategory(item.key)"
          >
            <span>{{ item.label }}</span>
            <em>{{ summary.category_counts[item.countKey] || 0 }}</em>
          </button>
          <p v-if="visibleCategories.length === 0" class="category-panel__empty">设置项待导入</p>
        </aside>

        <main v-if="hasSelectedCategory" class="data-card erp-list-data">
          <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon class="load-error" />

          <div class="table-heading erp-list-toolbar">
        <div class="page-heading__actions">
          <el-button class="erp-button-motion" :icon="Refresh" @click="reloadAll">刷新</el-button>
          <el-button class="erp-button-motion" v-if="canAddSelected" type="primary" :icon="Plus" @click="openCreate">新增{{ selectedCategory.title }}</el-button>
        </div>
            <div><h2>{{ selectedCategory.label }}</h2><span>共 {{ total }} 条</span></div>
          </div>

          <div class="erp-list-table-frame"><el-table v-loading="loading" :data="records" height="100%" row-key="id" class="production-table">
            <template v-if="selectedKey === 'category'">
              <el-table-column prop="item_type_label" label="品号类型" width="130" />
              <el-table-column prop="category_name" label="品号类别" min-width="220" />
              <el-table-column prop="reference_count" label="货号引用" width="100" />
            </template>
            <template v-else-if="selectedKey === 'unit'">
              <el-table-column prop="unit_code" label="单位编号" width="150" />
              <el-table-column prop="unit_name" label="单位名称" min-width="220" />
            </template>
            <template v-else-if="selectedKey === 'color'">
              <el-table-column label="图片" width="92">
                <template #default="scope">
                  <el-image
                    v-if="(scope.row as ProductColor).image_url"
                    class="color-thumb"
                    :src="(scope.row as ProductColor).image_url || ''"
                    :preview-src-list="[(scope.row as ProductColor).image_url || '']"
                    preview-teleported
                    fit="cover"
                  />
                  <span v-else class="empty-image">暂无</span>
                </template>
              </el-table-column>
              <el-table-column prop="color_card" label="色卡" min-width="130" show-overflow-tooltip />
              <el-table-column prop="color_code" label="色号" min-width="150" show-overflow-tooltip />
              <el-table-column prop="color_name" label="颜色名称" min-width="260" show-overflow-tooltip />
            </template>
            <template v-else-if="selectedKey === 'item'">
              <el-table-column prop="item_number" label="货号" width="170" />
              <el-table-column prop="category_name" label="产品类别" min-width="200" />
              <el-table-column prop="item_type_label" label="品号类型" width="120" />
            </template>
            <template v-else-if="selectedKey === 'fabric-material'">
              <el-table-column prop="material_name" label="材质" min-width="180" />
              <el-table-column label="库存原料" min-width="320" show-overflow-tooltip>
                <template #default="scope">
                  <span v-if="scope.row.inventory_raw_material">
                    {{ scope.row.inventory_material_number }}｜{{ scope.row.inventory_material_name }}（{{ scope.row.inventory_material_unit }}）
                  </span>
                  <span v-else class="mapping-missing">未关联，领料时将阻断</span>
                </template>
              </el-table-column>
            </template>
            <template v-else-if="selectedKey === 'fabric-specification'">
              <el-table-column prop="specification_name" label="规格" min-width="320" />
            </template>
            <template v-else-if="selectedKey === 'fabric-width'">
              <el-table-column prop="width_value" label="门幅" min-width="320" />
            </template>
            <template v-else-if="selectedKey === 'accessory-product-name'">
              <el-table-column prop="product_name" label="品名" min-width="260" />
              <el-table-column label="单位" width="120">
                <template #default="scope">{{ scope.row.unit_name || '待维护' }}</template>
              </el-table-column>
            </template>
            <template v-else-if="selectedKey === 'accessory-specification'">
              <el-table-column prop="product_name_label" label="品名" min-width="180" />
              <el-table-column prop="specification_value" label="规格" min-width="260" show-overflow-tooltip />
              <el-table-column prop="weight" label="克重" width="120" />
            </template>
            <template v-else-if="selectedKey === 'accessory-color'">
              <el-table-column prop="product_name_label" label="品名" min-width="200" />
              <el-table-column prop="color_name" label="颜色" min-width="260" show-overflow-tooltip />
            </template>
            <template v-else-if="selectedKey === 'accessory-material'">
              <el-table-column prop="material_name" label="材质" min-width="180" />
              <el-table-column label="库存原料" min-width="320" show-overflow-tooltip>
                <template #default="scope">
                  <span v-if="scope.row.inventory_raw_material">
                    {{ scope.row.inventory_material_number }}｜{{ scope.row.inventory_material_name }}（{{ scope.row.inventory_material_unit }}）
                  </span>
                  <span v-else class="mapping-missing">未关联，领料时将阻断</span>
                </template>
              </el-table-column>
            </template>
            <template v-else-if="selectedKey === 'tube-product-name'">
              <el-table-column prop="product_name" label="品名" min-width="320" />
            </template>
            <template v-else-if="selectedKey === 'tube-thickness'">
              <el-table-column prop="thickness_value" label="厚度" min-width="320" />
            </template>
            <template v-else-if="selectedKey === 'tube-diameter'">
              <el-table-column prop="diameter_value" label="直径" min-width="320" />
            </template>
            <template v-else-if="selectedKey === 'tube-material'">
              <el-table-column prop="material_name" label="材质" min-width="320" />
            </template>
            <template v-else-if="selectedKey === 'tube-shape'">
              <el-table-column prop="shape_name" label="形状" min-width="320" />
            </template>
            <template v-else-if="selectedKey === 'tube-coating-color'">
              <el-table-column prop="color_name" label="喷塑颜色" min-width="320" />
            </template>

            <el-table-column label="状态" width="90">
              <template #default="scope">
                <el-tag class="settings-tag erp-list-tag" :class="scope.row.status === 'ACTIVE' ? 'erp-list-tag--success' : 'erp-list-tag--neutral'" :type="scope.row.status === 'ACTIVE' ? 'success' : 'info'" effect="light">
                  {{ scope.row.status === 'ACTIVE' ? '启用' : '停用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="sort_order" label="排序" width="82" />
            <el-table-column label="操作" width="150" fixed="right">
              <template #default="scope">
                <el-button v-if="canChangeSelected" link :icon="Edit" @click="openEdit(scope.row)">编辑</el-button>
                <el-button v-if="canChangeStatus(scope.row)" link @click="changeStatus(scope.row)">
                  {{ scope.row.status === 'ACTIVE' ? '停用' : '启用' }}
                </el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="暂无生产资料" /></template>
          </el-table></div>

          <footer v-if="total > pageSize" class="erp-list-footer"><el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[20, 50, 100]"
            layout="total, sizes, prev, pager, next"
            @current-change="loadRecords"
            @size-change="page = 1; loadRecords()"
          /></footer>
        </main>
        <main v-else class="data-card pending-card erp-list-data">
          <el-empty :description="selectedGroup.pendingText">
            <p>请提供对应维护表格及字段规则后再导入，当前未创建虚构数据。</p>
          </el-empty>
        </main>
      </div>

      <el-dialog
        v-model="dialogVisible"
        :title="dialogTitle"
        width="min(680px, 92vw)"
        draggable
        destroy-on-close
        :close-on-click-modal="!saving"
        class="production-dialog system-settings-dialog"
      >
        <el-form label-position="top" class="production-form">
          <template v-if="selectedKey === 'category'">
            <el-form-item label="品号类型" required>
              <el-select v-model="form.item_type">
                <el-option v-for="item in itemTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="品号类别" required><el-input v-model="form.category_name" maxlength="150" /></el-form-item>
          </template>
          <template v-else-if="selectedKey === 'unit'">
            <div class="form-grid">
              <el-form-item label="单位编号" required><el-input v-model="form.unit_code" maxlength="20" placeholder="例如：01" /></el-form-item>
              <el-form-item label="单位名称" required><el-input v-model="form.unit_name" maxlength="80" /></el-form-item>
            </div>
          </template>
          <template v-else-if="selectedKey === 'color'">
            <div class="form-grid">
              <el-form-item label="色卡" required><el-input v-model="form.color_card" maxlength="100" /></el-form-item>
              <el-form-item label="色号" required><el-input v-model="form.color_code" maxlength="100" /></el-form-item>
            </div>
            <el-form-item label="颜色名称" required><el-input v-model="form.color_name" maxlength="200" /></el-form-item>
            <el-form-item label="颜色图片">
              <div class="image-editor">
                <el-image v-if="imagePreviewUrl" :src="imagePreviewUrl" fit="contain" class="image-preview" />
                <div v-else class="image-placeholder">暂无图片</div>
                <div class="image-actions">
                  <label class="file-button">
                    <el-icon><Upload /></el-icon>选择图片
                    <input :key="fileInputKey" type="file" accept="image/jpeg,image/png,image/gif,image/webp" @change="chooseImage" />
                  </label>
                  <el-button v-if="imagePreviewUrl" :icon="Delete" @click="markImageForClear">清除图片</el-button>
                  <small>支持 JPG、PNG、GIF、WebP，最大 5MB；上传后按当前文件策略校验。</small>
                </div>
              </div>
            </el-form-item>
          </template>
          <template v-else-if="selectedKey === 'item'">
            <el-form-item label="产品类别" required>
              <el-select v-model="form.category" filterable placeholder="请选择启用中的类别">
                <el-option v-for="item in productCategories" :key="item.id" :label="`${item.category_name}（${item.item_type_label}）`" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="货号" required><el-input v-model="form.item_number" maxlength="100" /></el-form-item>
          </template>
          <template v-else-if="selectedKey === 'fabric-material'">
            <el-form-item label="材质" required><el-input v-model="form.material_name" maxlength="150" /></el-form-item>
            <el-form-item label="库存原料">
              <el-select
                v-model="form.inventory_raw_material"
                filterable
                clearable
                :no-data-text="can('products.view_rawmaterialinformation') ? '暂无可用材料原料' : '无原料信息查看权限'"
                placeholder="请选择明确对应的库存原料"
              >
                <el-option
                  v-for="item in inventoryRawMaterials"
                  :key="item.id"
                  :label="`${item.material_number}｜${item.material_name}｜${item.specification}（${item.unit_name}）`"
                  :value="item.id"
                />
              </el-select>
              <small class="mapping-hint">不按名称自动匹配；未关联时，相关 BOM 会在领料和委外发料前安全阻断。</small>
            </el-form-item>
          </template>
          <template v-else-if="selectedKey === 'fabric-specification'">
            <el-form-item label="规格" required><el-input v-model="form.specification_name" maxlength="150" /></el-form-item>
          </template>
          <template v-else-if="selectedKey === 'fabric-width'">
            <el-form-item label="门幅" required><el-input v-model="form.width_value" maxlength="50" placeholder="例如：1.7" /></el-form-item>
          </template>
          <template v-else-if="selectedKey === 'accessory-product-name'">
            <div class="form-grid">
              <el-form-item label="品名" required><el-input v-model="form.product_name" maxlength="200" /></el-form-item>
              <el-form-item label="单位" required><el-input v-model="form.unit_name" maxlength="50" placeholder="例如：个、米、PCS" /></el-form-item>
            </div>
          </template>
          <template v-else-if="selectedKey === 'accessory-specification'">
            <el-form-item label="品名" required>
              <el-select v-model="form.product_name" filterable placeholder="请选择启用中的辅料品名">
                <el-option
                  v-for="item in accessoryProductNames"
                  :key="item.id"
                  :label="`${item.product_name}${item.unit_name ? `（${item.unit_name}）` : '（单位待维护）'}`"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
            <div class="form-grid">
              <el-form-item label="规格" required><el-input v-model="form.specification_value" maxlength="300" /></el-form-item>
              <el-form-item label="克重"><el-input v-model="form.weight" maxlength="100" /></el-form-item>
            </div>
          </template>
          <template v-else-if="selectedKey === 'accessory-color'">
            <el-form-item label="品名" required>
              <el-select v-model="form.product_name" filterable placeholder="请选择启用中的辅料品名">
                <el-option
                  v-for="item in accessoryProductNames"
                  :key="item.id"
                  :label="`${item.product_name}${item.unit_name ? `（${item.unit_name}）` : '（单位待维护）'}`"
                  :value="item.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="颜色" required><el-input v-model="form.color_name" maxlength="200" /></el-form-item>
          </template>
          <template v-else-if="selectedKey === 'accessory-material'">
            <el-form-item label="材质" required><el-input v-model="form.material_name" maxlength="150" /></el-form-item>
            <el-form-item label="库存原料">
              <el-select
                v-model="form.inventory_raw_material"
                filterable
                clearable
                :no-data-text="can('products.view_rawmaterialinformation') ? '暂无可用材料原料' : '无原料信息查看权限'"
                placeholder="请选择明确对应的库存原料"
              >
                <el-option
                  v-for="item in inventoryRawMaterials"
                  :key="item.id"
                  :label="`${item.material_number}｜${item.material_name}｜${item.specification}（${item.unit_name}）`"
                  :value="item.id"
                />
              </el-select>
              <small class="mapping-hint">不按名称自动匹配；未关联时，相关 BOM 会在领料和委外发料前安全阻断。</small>
            </el-form-item>
          </template>
          <template v-else-if="selectedKey === 'tube-product-name'">
            <el-form-item label="品名" required><el-input v-model="form.product_name" maxlength="200" /></el-form-item>
          </template>
          <template v-else-if="selectedKey === 'tube-thickness'">
            <el-form-item label="厚度" required><el-input v-model="form.thickness_value" maxlength="50" placeholder="例如：1.2" /></el-form-item>
          </template>
          <template v-else-if="selectedKey === 'tube-diameter'">
            <el-form-item label="直径" required><el-input v-model="form.diameter_value" maxlength="50" placeholder="例如：25*15" /></el-form-item>
          </template>
          <template v-else-if="selectedKey === 'tube-material'">
            <el-form-item label="材质" required><el-input v-model="form.material_name" maxlength="150" /></el-form-item>
          </template>
          <template v-else-if="selectedKey === 'tube-shape'">
            <el-form-item label="形状" required><el-input v-model="form.shape_name" maxlength="150" /></el-form-item>
          </template>
          <template v-else-if="selectedKey === 'tube-coating-color'">
            <el-form-item label="喷塑颜色" required><el-input v-model="form.color_name" maxlength="200" /></el-form-item>
          </template>
          <div class="form-grid form-grid--footer">
            <el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0" :max="999999" /></el-form-item>
            <el-form-item label="说明"><el-input v-model="form.description" maxlength="500" /></el-form-item>
          </div>
        </el-form>
        <p class="dialog-hint">可拖动标题移动窗口；拖动右下角调整窗口大小。</p>
        <template #footer>
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="saveRecord">保存</el-button>
        </template>
      </el-dialog>
    </template>
  </section>
</template>

<style scoped lang="scss">
.page-heading__actions { display: flex; flex-wrap: wrap; gap: 8px; }
.metric-grid { margin-bottom: 10px; }
.metric-card small { margin-left: 8px; }
.content-layout { display: grid; flex: 1; min-height: 0; grid-template-columns: 220px minmax(0, 1fr); gap: 14px; }
.category-panel { min-height: 0; overflow-y: auto; }
.category-panel h2 { margin: 2px 12px 10px; color: var(--erp-color-text-secondary); font-size: 13px; font-weight: 500; }
.category-panel button { display: flex; width: 100%; align-items: center; justify-content: space-between; font-size: 13px; }
.category-panel em { font-size: 12px; font-style: normal; }
.category-panel__empty { margin: 8px 12px; color: var(--erp-color-text-secondary); font-size: 13px; line-height: 1.6; }
.pending-card { justify-content: center; }
.pending-card p { margin: 0; color: var(--erp-color-text-secondary); font-size: 13px; }
.filter-row > :deep(.el-input) { width: min(320px, 100%); }
.filter-row > :deep(.el-select) { width: 160px; }
.load-error { margin-bottom: 10px; }
.table-heading > div:last-child { display: flex; align-items: baseline; gap: 8px; margin-left: auto; }
.table-heading h2 { margin: 0; font-size: 14px; }
.table-heading span { color: var(--erp-color-text-secondary); font-size: 13px; }
.color-thumb { width: 52px; height: 42px; border: 1px solid var(--erp-color-border); border-radius: 5px; cursor: zoom-in; }
.empty-image { color: var(--erp-color-text-secondary); font-size: 12px; }
.mapping-missing { color: var(--erp-color-warning); }
.state-page { flex: 1; min-height: 0; display: grid; place-content: center; text-align: center; }
.state-page h1 { margin: 0 0 8px; }
.state-page p { color: var(--erp-color-text-secondary); }
.production-form :deep(.el-select), .production-form :deep(.el-input-number) { width: 100%; }
.mapping-hint { display: block; margin-top: 6px; color: var(--erp-color-text-muted); line-height: 1.5; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.form-grid--footer { align-items: start; }
.image-editor { display: flex; width: 100%; gap: 16px; align-items: flex-start; }
.image-preview, .image-placeholder { width: 180px; height: 125px; flex: none; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-subtle); }
.image-placeholder { display: grid; place-items: center; color: var(--erp-color-text-muted); }
.image-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.image-actions small { width: 100%; color: var(--erp-color-text-muted); line-height: 1.5; }
.file-button { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border: 1px solid var(--erp-button-secondary-border); border-radius: 4px; background: var(--erp-button-secondary-background); cursor: pointer; }
.file-button input { display: none; }
.dialog-hint { margin: 2px 0 0; color: var(--erp-color-text-muted); font-size: 12px; }

@media (max-width: 900px) { .content-layout { grid-template-columns: 1fr; grid-template-rows: auto minmax(0, 1fr); } .category-panel { flex-direction: row; overflow-x: auto; } .category-panel h2 { display: none; } .category-panel button { flex: none; width: auto; min-width: 130px; } }
@media (max-width: 640px) { .form-grid { grid-template-columns: 1fr; gap: 0; } .image-editor { flex-direction: column; } .image-preview, .image-placeholder { width: 100%; } }
</style>
