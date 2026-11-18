<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Calendar, CopyDocument, Delete, Plus } from '@element-plus/icons-vue'
import { isCancel } from 'axios'
import type { MaterialAttributeValue, MaterialCatalog, MaterialCatalogSummary, MaterialColorSelection, MaterialFieldDefinition, PublicMaterialOptions } from '@/types/materialCatalog'
import type { MaterialReceivingOptions, MaterialTransferDirection, MaterialTransferPayload } from '@/types/inventory'
import type { SampleMaterialCategory } from '@/types/sampleMaterial'
import { createMaterialTransfer, fetchMaterialReceivingOptions } from '@/api/inventory'
import { fetchInboundMaterial, fetchInboundMaterialOptions, fetchInboundMaterials, fetchInboundPublicOptions } from '@/api/inventoryMaterialSources'
import { useAuthStore } from '@/stores/auth'
import { pipeMeters, pipeRootError } from '@/utils/pipeQuantities'
import { createClientUuid } from '@/utils/clientUuid'
import { vGlassSpotlight } from '@/directives/glassSpotlight'

interface TransferRow {
  key: string
  category: SampleMaterialCategory
  catalogId: string
  catalog?: MaterialCatalog
  publicOptions?: PublicMaterialOptions
  color: MaterialColorSelection
  selectionVersion: number
  selectionLoading: boolean
  selectionError: string
  attributes: Record<string, string>
  unitId: string
  warehouseId: string
  zoneId: string
  quantity: string
  rawLength: string
  weight: string
}

const CATEGORY_TO_CATALOG: Record<SampleMaterialCategory, string> = {
  tube: 'TUBE',
  hardware: 'HARDWARE',
  plastic: 'PLASTIC',
  accessory: 'AUXILIARY',
  fabric: 'FABRIC',
  packaging: 'PACKAGING',
}
const CATEGORY_LABELS: Record<SampleMaterialCategory, string> = {
  tube: '管材类',
  hardware: '五金件',
  plastic: '塑料件类',
  accessory: '辅料类',
  fabric: '面料类',
  packaging: '包材类',
}
const FIELD_ORDER = [
  'material', 'color', 'shape', 'section_size', 'thickness', 'length', 'fabric_spec', 'width',
  'gram_weight', 'finish', 'surface_finish', 'specification', 'size', 'thread', 'flow_unit',
  'model', 'tube_size', 'layers', 'box_type', 'bag_type', 'printing', 'process',
]
const FIELD_LABELS: Record<string, string> = {
  material: '材质', color: '颜色', shape: '截面形状', section_size: '规格', thickness: '厚度',
  length: '长度', fabric_spec: '面料规格', width: '门幅/宽度', gram_weight: '克重',
  finish: '涂层/后处理', surface_finish: '表面处理', specification: '规格描述',
  size: '尺寸', thread: '螺纹规格', flow_unit: '流转单位', model: '型号/图号',
  tube_size: '适配管材尺寸', layers: '层数', box_type: '箱子形状', bag_type: '袋型/封口方式',
  printing: '印刷版本', process: '加工做法/工艺版本',
}
const auth = useAuthStore()
const props = withDefaults(defineProps<{ initialDirection?: MaterialTransferDirection }>(), { initialDirection: 'IN' })
const emit = defineEmits<{ saved: [record: { transfer_number: string }] }>()
const canEdit = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.receive_material'))
const operatorName = computed(() => auth.user?.employee?.display_name || auth.user?.display_name || '当前登录人')
const direction = ref<MaterialTransferDirection>(props.initialDirection)
const form = reactive({ transferDate: localToday(), remark: '' })
const options = ref<MaterialReceivingOptions>({ warehouses: [], zones: [] })
const catalogOptions = ref<{ categories: { key: string; label: string; templates: { key: string; fields: MaterialFieldDefinition[] }[] }[] }>({ categories: [] })
const catalogs = reactive<Record<string, MaterialCatalogSummary[]>>({})
const catalogDetails = reactive<Record<string, MaterialCatalog>>({})
const publicOptionsCache = reactive<Record<string, PublicMaterialOptions>>({})
const categoryLoading = reactive<Record<string, boolean>>({})
const categoryRequests = new Map<string, Promise<void>>()
let sourceVersion = 0
const rows = ref<TransferRow[]>([createRow('tube')])
const sectionFilter = ref<SampleMaterialCategory>('tube')
const loading = ref(false)
const submitting = ref(false)
const blocked = ref(false)
const submitError = ref('')
const draftDisabled = computed(() => !canEdit.value || loading.value || submitting.value || blocked.value)

function localToday() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
}
function requestId() {
  return createClientUuid()
}
function createRow(category: SampleMaterialCategory): TransferRow {
  return { key: requestId(), category, catalogId: '', attributes: {}, color: {}, selectionVersion: 0, selectionLoading: false, selectionError: '', unitId: '', warehouseId: '', zoneId: '', quantity: '', rawLength: '', weight: '' }
}
function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}
function catalogKey(row: TransferRow) {
  return CATEGORY_TO_CATALOG[row.category]
}
function categoryDefinition(row: TransferRow) {
  return catalogOptions.value.categories.find(item => item.key === catalogKey(row))
}
function templateFields(row: TransferRow) {
  const definition = categoryDefinition(row)
  const template = definition?.templates.find(item => item.key === row.catalog?.template_key)
  return template?.fields.filter(field => field.kind !== 'unit') || definition?.templates.flatMap(item => item.fields).filter(field => field.kind !== 'unit') || []
}
const tableFields = computed(() => {
  const fields = new Map<string, MaterialFieldDefinition>()
  rows.value.forEach(row => rowFields(row).forEach(field => fields.set(field.key, field)))
  return [...fields.values()].sort((a, b) => {
    const ai = FIELD_ORDER.indexOf(a.key)
    const bi = FIELD_ORDER.indexOf(b.key)
    return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi)
  })
})
const firstError = computed(() => {
  const index = rows.value.findIndex(row => rowError(row))
  return index < 0 ? '' : '第 ' + (index + 1) + ' 行：' + rowError(rows.value[index]!)
})
const validationHint = computed(() => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.transferDate)) return '请填写收发日期。'
  if (form.transferDate > localToday()) return '收发日期不能晚于今天。'
  if (!form.remark.trim()) return '请填写备注。'
  return firstError.value
})
const ready = computed(() => canEdit.value && !loading.value && !submitting.value && !blocked.value
  && /^\d{4}-\d{2}-\d{2}$/.test(form.transferDate) && form.transferDate <= localToday()
  && form.remark.trim().length > 0 && !firstError.value)
const canSubmit = computed(() => canEdit.value && !loading.value && !submitting.value && !blocked.value)

function rowFields(row: TransferRow) {
  return templateFields(row).filter(field => field.key !== 'unit' && field.key !== 'length')
}
function hasField(row: TransferRow, key: string) {
  return !!row.catalog && rowFields(row).some(field => field.key === key)
}
function validValue(value: string) {
  return !!value.trim() && !['/', '-', '—'].includes(value.trim())
}
function valuesFor(row: TransferRow, fieldKey: string) {
  const values = row.publicOptions?.values || []
  const shape = values.find(item => item.field_key === 'shape' && item.value === row.attributes.shape)
  return [...new Set(values.filter(item => item.scope === 'BASE' && item.field_key === fieldKey && validValue(item.value)
    && (fieldKey !== 'section_size' || (shape && item.parent_id === shape.id))).map(item => item.value))]
}
function colorRows(row: TransferRow) {
  return (row.publicOptions?.values || []).filter(item => item.scope === 'BASE' && item.field_key === 'color' && validValue(item.value))
}
function colorId(color: MaterialAttributeValue) {
  return color.product_color_id || color.id
}
function colorLabel(color: MaterialAttributeValue) {
  return [color.color_card, color.color_code, color.color_name || color.value].filter(Boolean).join(' - ')
}
function chooseColor(row: TransferRow, id: string) {
  if (draftDisabled.value) return
  setColor(row, colorRows(row).find(item => colorId(item) === id))
}
function setColor(row: TransferRow, color?: MaterialAttributeValue) {
  row.color = color ? { product_color_id: colorId(color), color_card: color.color_card || '', color_code: color.color_code || '', color_name: color.color_name || color.value } : {}
  row.attributes.color = color?.value || ''
}
function zonesFor(row: TransferRow) {
  return options.value.zones.filter(zone => zone.warehouse === row.warehouseId)
}
function unitsFor(row: TransferRow) {
  return (row.publicOptions?.units || []).filter(unit => validValue(unit.unit_name)
    && (row.category !== 'tube' || unit.unit_name === '根'))
}
function setSingleValues(row: TransferRow) {
  rowFields(row).forEach(field => {
    if (field.key === 'color' && row.category === 'fabric') {
      const colors = colorRows(row)
      if (colors.length === 1 && !row.attributes.color) setColor(row, colors[0])
      return
    }
    const values = valuesFor(row, field.key)
    if (values.length === 1 && !row.attributes[field.key]) row.attributes[field.key] = values[0]!
  })
  const units = unitsFor(row)
  if (units.length === 1 && !row.unitId) row.unitId = units[0]!.id
}
function tubeLengthMeters(row: TransferRow) {
  const meters = row.rawLength.trim()
  if (!/^\d{1,14}(\.\d{1,3})?$/.test(meters) || Number(meters) <= 0) return ''
  return Number(meters).toFixed(3).replace(/\.?0+$/, '')
}
function tubeLengthMillimeters(row: TransferRow) {
  const meters = tubeLengthMeters(row)
  if (!meters) return ''
  return (Number(meters) * 1000).toFixed(0)
}
function rowError(row: TransferRow) {
  if (row.selectionLoading) return '正在加载品名属性'
  if (row.selectionError) return row.selectionError
  if (!row.catalogId || !row.catalog) return '请选择品名'
  if (row.catalog.id !== row.catalogId || row.catalog.category_key !== catalogKey(row)) return '品名与当前分区不一致，请重选'
  if (!row.publicOptions) return '品名属性未加载，请重新选择品名'
  const fixed: Record<string, string[]> = {
    TUBE: ['material', 'shape', 'section_size', 'thickness'],
    FABRIC: ['material', 'fabric_spec', 'width', 'color'],
  }
  const identities: Record<string, string[]> = {
    HARDWARE: ['specification', 'size', 'thread'], PLASTIC: ['specification', 'model', 'size'],
    CARTON: ['size', 'model'], BAG: ['size', 'model'], PACKAGING_GENERAL: ['specification', 'model'],
    TAPE: ['specification', 'width'], COTTON: ['specification', 'thickness', 'width'], AUXILIARY_GENERAL: ['specification'],
  }
  const template = row.catalog.template_key
  if ((fixed[template] || []).some(key => !validValue(row.attributes[key] || ''))) return '请补全必要属性'
  if (row.category === 'tube' && !tubeLengthMeters(row)) return '请填写有效的单根长度（米）'
  if (identities[template] && !identities[template]!.some(key => validValue(row.attributes[key] || ''))) return '请选择实际规格、尺寸或型号'
  for (const [key, value] of Object.entries(row.attributes)) {
    if (!value.trim()) continue
    if (key === 'length') continue
    if (!hasField(row, key) || !valuesFor(row, key).includes(value)) return '所选属性已失效，请重新选择'
  }
  if (row.category === 'fabric' && !colorRows(row).some(color => colorId(color) === row.color.product_color_id && color.value === row.attributes.color
    && (color.color_card || '') === row.color.color_card && (color.color_code || '') === row.color.color_code
    && (color.color_name || color.value) === row.color.color_name)) return '请选择完整的面料颜色'
  const unit = unitsFor(row).find(item => item.id === row.unitId)
  if (!unit) return '请选择有效单位'
  if (row.catalog.base_warehouse_id && !options.value.warehouses.some(item => item.id === row.catalog!.base_warehouse_id)) return '品名默认仓库不可用，请核实配置后刷新'
  if (row.catalog.base_warehouse_id && row.warehouseId !== row.catalog.base_warehouse_id) return '品名默认仓库已变化，请刷新页面后重试'
  if (!options.value.warehouses.some(item => item.id === row.warehouseId)) return '请选择有效仓库'
  if (!row.warehouseId || !row.zoneId || !zonesFor(row).some(zone => zone.id === row.zoneId)) return '请选择仓库和库区'
  if (row.category === 'tube') {
    return pipeRootError(row.quantity)
      || (Number(pipeMeters(row.quantity, row.rawLength)) > 0 ? '' : '请填写有效的单根长度（米）')
      || (direction.value === 'OUT' || (/^\d{1,14}(\.\d{1,4})?$/.test(row.weight) && Number(row.weight) > 0) ? '' : '请填写实际入库重量')
  }
  if (['根', '支', '套'].includes(unit.unit_name) && !Number.isInteger(Number(row.quantity))) return '根、支、套的数量须为整数'
  return /^\d{1,14}(\.\d{1,4})?$/.test(row.quantity) && Number(row.quantity) > 0 ? '' : '数量须大于 0，最多四位小数'
}
function selectionFor(row: TransferRow) {
  const attributes = Object.fromEntries(Object.entries(row.attributes)
    .filter(([key, value]) => key !== 'length' && hasField(row, key) && value.trim())
    .map(([key, value]) => [key, value.trim()]))
  if (row.category === 'tube') attributes.length = tubeLengthMillimeters(row)
  return {
    catalog_version: row.catalog!.updated_at,
    scope: 'BASE' as const,
    processing_state: 'RAW' as const,
    attributes,
    ...(row.category === 'fabric' ? clone(row.color) : {}),
    unit_id: row.unitId,
  }
}
function payload(): MaterialTransferPayload {
  return {
    client_request_id: requestId(),
    direction: direction.value,
    transfer_date: form.transferDate,
    remark: form.remark.trim(),
    items: rows.value.map(row => ({
      material_catalog_id: row.catalogId,
      material_selection: selectionFor(row),
      zone_id: row.zoneId,
      ...(row.category === 'tube'
        ? { raw_bar_count: row.quantity, raw_bar_length_m: tubeLengthMeters(row), ...(direction.value === 'IN' ? { weight_quantity: row.weight } : {}) }
        : { quantity: row.quantity }),
    })),
  }
}
function apiMessage(error: unknown) {
  const response = (error as { response?: { data?: { error?: { message?: string }; detail?: string } } })?.response
  return response?.data?.error?.message || response?.data?.detail || '材料收发保存失败，请修改后重试。'
}
async function loadCategory(category: SampleMaterialCategory) {
  const key = CATEGORY_TO_CATALOG[category]
  if (catalogs[key]) return
  if (categoryRequests.has(key)) return categoryRequests.get(key)
  const version = sourceVersion
  categoryLoading[key] = true
  const request = (async () => {
    try {
      const items: MaterialCatalogSummary[] = []
      let page = 1
      let pages = 1
      do {
        const data = await fetchInboundMaterials({ category: key, page, page_size: 100 })
        if (version !== sourceVersion) return
        items.push(...data.data)
        pages = data.meta.total_pages
        page += 1
      } while (page <= pages)
      catalogs[key] = items
    } catch (error) {
      if (version === sourceVersion && !isCancel(error)) ElMessage.error(apiMessage(error))
    } finally {
      if (version === sourceVersion) {
        categoryLoading[key] = false
        categoryRequests.delete(key)
      }
    }
  })()
  categoryRequests.set(key, request)
  return request
}
async function chooseMaterial(row: TransferRow, value: string) {
  if (draftDisabled.value) return
  await loadRowMaterial(row, value)
}
async function loadRowMaterial(row: TransferRow, value: string, preserveDraft = false) {
  const version = ++row.selectionVersion
  const generation = sourceVersion
  const category = row.category
  const oldDefault = row.catalog?.base_warehouse_id
  row.catalogId = value
  row.catalog = undefined
  row.publicOptions = undefined
  row.selectionError = ''
  row.selectionLoading = !!value
  if (!preserveDraft) {
    row.attributes = {}
    row.color = {}
    row.unitId = ''
    row.warehouseId = ''
    row.zoneId = ''
    row.quantity = ''
    row.rawLength = ''
    row.weight = ''
  }
  if (!value) return
  const current = () => generation === sourceVersion && row.selectionVersion === version
    && row.catalogId === value && row.category === category && rows.value.some(item => item.key === row.key)
  try {
    const catalog = catalogDetails[value] || (await fetchInboundMaterial(value)).data
    if (!current()) return
    if (catalog.id !== value || catalog.category_key !== CATEGORY_TO_CATALOG[category]) throw new Error('品名与当前分区不一致，请重选')
    const key = catalog.category_key + ':' + catalog.template_key
    const publicData = publicOptionsCache[key] || await fetchInboundPublicOptions({ category_key: catalog.category_key, template_key: catalog.template_key, scope: 'BASE' })
    if (!current()) return
    if (publicData.category_key !== catalog.category_key || publicData.template_key !== catalog.template_key || publicData.scope !== 'BASE') throw new Error('属性与当前品名不一致，请刷新后重选')
    catalogDetails[value] = catalog
    publicOptionsCache[key] = publicData
    row.catalog = catalog
    row.publicOptions = publicData
    if (!preserveDraft) setSingleValues(row)
    const suggested = catalog.base_warehouse_id || ''
    const availableWarehouse = options.value.warehouses.some(item => item.id === suggested)
    if (suggested && (!preserveDraft || suggested !== oldDefault || row.warehouseId !== suggested || !availableWarehouse)) {
      row.warehouseId = availableWarehouse ? suggested : ''
      const zones = zonesFor(row)
      row.zoneId = zones.length === 1 ? zones[0]!.id : ''
    } else if (preserveDraft && oldDefault && !suggested) {
      row.warehouseId = ''
      row.zoneId = ''
    }
  } catch (error) {
    if (current() && !isCancel(error)) {
      row.selectionError = error instanceof Error && !(error as { response?: unknown }).response ? error.message : apiMessage(error)
      ElMessage.error(row.selectionError)
    }
  } finally {
    if (current()) row.selectionLoading = false
  }
}
function attributeChanged(row: TransferRow, fieldKey: string) {
  if (draftDisabled.value) return
  if (fieldKey === 'shape') {
    const sectionValues = valuesFor(row, 'section_size')
    if (row.attributes.section_size && !sectionValues.includes(row.attributes.section_size)) row.attributes.section_size = ''
  }
}
function warehouseChanged(row: TransferRow) {
  if (draftDisabled.value) return
  const zones = zonesFor(row)
  row.zoneId = zones.length === 1 ? zones[0]!.id : ''
}
function selectedCategory(): SampleMaterialCategory {
  return sectionFilter.value
}
function sectionChanged(value: SampleMaterialCategory) {
  if (draftDisabled.value) return
  sectionFilter.value = value
  const category = selectedCategory()
  rows.value = [createRow(category)]
  submitError.value = ''
  void loadCategory(category)
}
function addRow(category: SampleMaterialCategory = selectedCategory()) {
  if (draftDisabled.value || rows.value.length >= 100) return
  rows.value.push(createRow(category))
  void loadCategory(category)
}
function removeRow(row: TransferRow) {
  if (draftDisabled.value || rows.value.length <= 1) return
  rows.value = rows.value.filter(item => item.key !== row.key)
}
function copyRow(row: TransferRow) {
  if (draftDisabled.value || row.selectionLoading || rows.value.length >= 100) return
  const copy = createRow(row.category)
  copy.catalogId = row.catalogId
  copy.catalog = row.catalog ? clone(row.catalog) : undefined
  copy.publicOptions = row.publicOptions ? clone(row.publicOptions) : undefined
  copy.color = clone(row.color)
  copy.selectionError = row.selectionError
  copy.attributes = clone(row.attributes)
  copy.unitId = row.unitId
  copy.warehouseId = row.warehouseId
  copy.zoneId = row.zoneId
  copy.rawLength = row.rawLength
  rows.value.splice(rows.value.findIndex(item => item.key === row.key) + 1, 0, copy)
  void loadCategory(copy.category)
}
async function loadPageOptions() {
  if (!canEdit.value || loading.value || submitting.value || blocked.value) return
  loading.value = true
  sourceVersion += 1
  categoryRequests.clear()
  for (const cache of [catalogs, catalogDetails, publicOptionsCache, categoryLoading]) Object.keys(cache).forEach(key => { delete cache[key] })
  rows.value.forEach(row => { row.selectionVersion += 1 })
  try {
    const [receiving, catalogsData] = await Promise.all([fetchMaterialReceivingOptions(), fetchInboundMaterialOptions()])
    const warehouses = receiving.warehouses.filter(item => !item.warehouse_type || item.warehouse_type === 'MATERIAL')
    const ids = new Set(warehouses.map(item => item.id))
    options.value = { warehouses, zones: receiving.zones.filter(item => ids.has(item.warehouse)) }
    catalogOptions.value = catalogsData
    await Promise.all([
      ...(['tube', 'hardware', 'plastic', 'accessory', 'fabric', 'packaging'] as SampleMaterialCategory[]).map(loadCategory),
      ...rows.value.filter(row => row.catalogId).map(row => loadRowMaterial(row, row.catalogId, true)),
    ])
  } catch (error) {
    if (!isCancel(error)) ElMessage.error(apiMessage(error))
  } finally {
    loading.value = false
  }
}
async function submit() {
  if (!ready.value) {
    ElMessage.warning(validationHint.value || '请填写收发日期、备注和完整明细。')
    return
  }
  submitting.value = true
  submitError.value = ''
  const submitted = payload()
  try {
    const record = await createMaterialTransfer(submitted)
    ElMessage.success((submitted.direction === 'IN' ? '入库' : '出库') + '已保存，单号 ' + record.transfer_number)
    emit('saved', record)
    rows.value = [createRow(selectedCategory())]
    form.remark = ''
    // 保存可能补录品名使用关联并改变目录版本，下次选择必须重新读取。
    submitted.items.forEach(item => { delete catalogDetails[item.material_catalog_id] })
  } catch (error) {
    submitError.value = apiMessage(error)
    ElMessage.error(submitError.value)
    const status = (error as { response?: { status?: number } }).response?.status
    if (!status || status >= 500) blocked.value = true
  } finally {
    submitting.value = false
  }
}
onMounted(() => { void loadPageOptions() })
onBeforeUnmount(() => { sourceVersion += 1 })
</script>

<template>
  <section class="material-transfer-form erp-glass-list" data-testid="material-transfers-page">
    <ElAlert v-if="!canEdit" title="当前账号没有材料收发权限，请联系管理员开通材料收发权限。" type="warning" :closable="false" />
    <ElAlert v-if="blocked" title="本次请求结果尚未确认，页面已锁定。请联系管理员核对单号后再继续。" type="error" :closable="false" show-icon />
    <ElAlert v-if="submitError && !blocked" :title="submitError" type="error" :closable="false" show-icon />

    <section v-glass-spotlight class="erp-list-filter">
    <header class="transfer-header erp-list-heading">
      <div>
        <h1>材料收发</h1>
        <p>采购之外的盘点、调整和其他材料收发。</p>
      </div>
      <slot name="actions" />
    </header>
    <form class="erp-list-filters" aria-label="材料收发筛选" @submit.prevent>
        <div class="filter-field filter-date" aria-label="收发日期">
          <ElDatePicker v-model="form.transferDate" :disabled="draftDisabled" type="date" value-format="YYYY-MM-DD" :prefix-icon="Calendar" :disabled-date="(date: Date) => new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date) > localToday()" />
        </div>
        <div class="filter-field filter-direction" aria-label="收发方向">
          <ElSelect v-model="direction" :disabled="draftDisabled" data-testid="transfer-direction-filter">
            <ElOption value="IN" label="入库" />
            <ElOption value="OUT" label="出库" />
          </ElSelect>
        </div>
        <div class="filter-field filter-section" aria-label="分区">
          <ElSelect v-model="sectionFilter" data-testid="transfer-section-filter" :disabled="draftDisabled" @change="sectionChanged">
            <ElOption v-for="(label, key) in CATEGORY_LABELS" :key="key" :value="key" :label="label" />
          </ElSelect>
        </div>
        <div class="filter-field filter-operator" aria-label="操作人"><ElInput :model-value="operatorName" readonly /></div>
        <div class="filter-field filter-remark" aria-label="备注"><ElInput v-model="form.remark" :disabled="draftDisabled" maxlength="3000" placeholder="备注（必填）" /></div>
    </form>
    </section>

    <section class="table-shell erp-list-data">
      <div class="table-toolbar erp-list-toolbar">
        <span class="row-count">共 {{ rows.length }} 行</span>
        <ElButton :icon="Plus" :disabled="draftDisabled || rows.length >= 100" @click="addRow()">添加一行</ElButton>
      </div>
      <div class="erp-list-table-frame">
      <div class="transfer-table-scroll">
      <ElTable height="100%" :data="rows" class="erp-table-editor material-transfer-table" border row-key="key" empty-text="暂无材料明细，请添加一行">
        <ElTableColumn label="序号" width="52" align="center">
          <template #default="{ row }">{{ rows.findIndex(item => item.key === row.key) + 1 }}</template>
        </ElTableColumn>
        <ElTableColumn label="品名" width="190">
          <template #default="{ row }">
            <ElSelect v-model="row.catalogId" :disabled="draftDisabled" filterable clearable placeholder="选择品名" :loading="categoryLoading[catalogKey(row)] || row.selectionLoading" @visible-change="(visible: boolean) => visible && loadCategory(row.category)" @change="(value: string) => chooseMaterial(row, value)">
              <ElOption v-for="item in (catalogs[catalogKey(row)] || [])" :key="item.id" :value="item.id" :label="item.name" />
            </ElSelect>
          </template>
        </ElTableColumn>
        <ElTableColumn v-for="field in tableFields" :key="field.key" :label="field.label || FIELD_LABELS[field.key] || field.key" min-width="120">
          <template #default="{ row }">
            <span v-if="!hasField(row, field.key)">—</span>
            <ElSelect v-else-if="field.key === 'color' && row.category === 'fabric'" :model-value="row.color.product_color_id || ''" :disabled="draftDisabled || row.selectionLoading" filterable clearable placeholder="色卡 / 色号 / 颜色" @update:model-value="(id: string) => chooseColor(row, id)">
              <ElOption v-for="color in colorRows(row)" :key="colorId(color)" :value="colorId(color)" :label="colorLabel(color)" />
            </ElSelect>
            <ElSelect v-else v-model="row.attributes[field.key]" :disabled="draftDisabled || row.selectionLoading || (field.key === 'section_size' && !row.attributes.shape)" filterable clearable :placeholder="field.label || FIELD_LABELS[field.key]" @change="() => attributeChanged(row, field.key)">
              <ElOption v-for="value in valuesFor(row, field.key)" :key="value" :value="value" :label="value" />
            </ElSelect>
          </template>
        </ElTableColumn>
        <ElTableColumn label="单位" width="90">
          <template #default="{ row }">
            <ElSelect v-model="row.unitId" :disabled="draftDisabled || row.selectionLoading || !row.catalog" filterable clearable placeholder="选择单位">
              <ElOption v-for="unit in unitsFor(row)" :key="unit.id" :value="unit.id" :label="unit.unit_name" />
            </ElSelect>
          </template>
        </ElTableColumn>
        <ElTableColumn label="仓库" width="150">
          <template #default="{ row }">
            <ElSelect v-model="row.warehouseId" :disabled="draftDisabled || row.selectionLoading || !row.catalog || Boolean(row.catalog?.base_warehouse_id)" placeholder="选择仓库" @change="warehouseChanged(row)">
              <ElOption v-for="warehouse in options.warehouses" :key="warehouse.id" :value="warehouse.id" :label="warehouse.warehouse_name" />
            </ElSelect>
          </template>
        </ElTableColumn>
        <ElTableColumn label="库区" width="120">
          <template #default="{ row }">
            <ElSelect v-model="row.zoneId" :disabled="draftDisabled || row.selectionLoading || !row.warehouseId" placeholder="选择库区">
              <ElOption v-for="zone in zonesFor(row)" :key="zone.id" :value="zone.id" :label="zone.zone_name" />
            </ElSelect>
          </template>
        </ElTableColumn>
        <ElTableColumn :label="direction === 'IN' ? '入库数量' : '出库数量'" width="105">
          <template #default="{ row }"><ElInput v-model="row.quantity" :disabled="draftDisabled || row.selectionLoading" inputmode="decimal" :aria-label="`第 ${rows.findIndex(item => item.key === row.key) + 1} 行数量`" :placeholder="row.category === 'tube' ? '根数' : '数量'" /></template>
        </ElTableColumn>
        <ElTableColumn v-if="rows.some(row => row.category === 'tube')" label="管材重量（kg）" width="150">
          <template #default="{ row }">
            <ElInput v-if="row.category === 'tube' && direction === 'IN'" v-model="row.weight" :disabled="draftDisabled || row.selectionLoading" inputmode="decimal" :aria-label="`第 ${rows.findIndex(item => item.key === row.key) + 1} 行实际重量`" placeholder="实际重量" />
            <span v-else-if="row.category === 'tube'">出库按库存分摊</span><span v-else>—</span>
          </template>
        </ElTableColumn>
        <ElTableColumn v-if="rows.some(row => row.category === 'tube')" label="单根长度（米）" width="130">
          <template #default="{ row }"><ElInput v-if="row.category === 'tube'" v-model="row.rawLength" :disabled="draftDisabled || row.selectionLoading" inputmode="decimal" :aria-label="`第 ${rows.findIndex(item => item.key === row.key) + 1} 行单根长度（米）`" placeholder="米 / 根" /><span v-else>—</span></template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="80" fixed="right" align="center">
          <template #default="{ row }">
            <div class="row-actions">
              <ElButton text type="primary" :icon="CopyDocument" aria-label="复制行" :disabled="draftDisabled || row.selectionLoading || rows.length >= 100" @click="copyRow(row)" />
              <ElButton text type="danger" :icon="Delete" aria-label="删除行" :disabled="draftDisabled || rows.length <= 1" @click="removeRow(row)" />
            </div>
          </template>
        </ElTableColumn>
      </ElTable>
      </div>
      </div>
    </section>

    <footer class="transfer-footer">
      <ElButton type="primary" :loading="submitting" :disabled="!canSubmit" @click="submit">保存{{ direction === 'IN' ? '入库' : '出库' }}</ElButton>
    </footer>
  </section>
</template>

<style scoped lang="scss">
.material-transfer-form { height: 100%; min-height: 0; color: var(--erp-color-text-primary); }
.transfer-header { display: flex; align-items: center; justify-content: space-between; }
.transfer-header { margin-bottom: 0; }
.transfer-header p { margin: 5px 0 0; color: var(--erp-color-text-secondary); font-size: 13px; }
.row-count, .filter-count { color: var(--erp-color-text-secondary); font-size: 12px; }
.table-toolbar { justify-content: space-between; }
.material-transfer-form .erp-list-filters { align-items: center; }
.filter-field { display: flex; min-width: 0; flex: 0 0 auto; align-items: center; }
.filter-field :deep(.el-input), .filter-field :deep(.el-select), .filter-field :deep(.el-date-editor) { width: 100%; }
.filter-date { width: 150px; }
.filter-direction, .filter-section { width: 130px; }
.filter-operator { width: 150px; }
.filter-remark { width: 240px; }
.table-shell { min-height: 0; flex: 1; overflow: hidden; }
.transfer-table-scroll { min-width: 0; min-height: 0; flex: 1; overflow: auto; }
.material-transfer-table { min-height: 0; flex: 1; width: 100%; --el-table-border-color: var(--erp-table-border, var(--erp-color-border)); --el-table-header-bg-color: var(--erp-table-header-background, #f6f8fb); --el-table-row-hover-bg-color: var(--erp-table-hover, #f7fbff); --el-table-text-color: var(--erp-color-text-primary); --el-table-header-text-color: var(--erp-table-header-text, var(--erp-color-text-secondary)); }
.material-transfer-table :deep(.el-table__header-wrapper th) { height: 38px; padding: 0 8px; font-weight: 500; white-space: nowrap; }
.material-transfer-table :deep(.el-table__body-wrapper td) { height: 40px; padding: 4px 6px; white-space: nowrap; }
.material-transfer-table :deep(.cell) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.material-transfer-table :deep(.el-input), .material-transfer-table :deep(.el-select) { width: 100%; }
.material-transfer-table :deep(.el-input__wrapper), .material-transfer-table :deep(.el-select__wrapper) { min-height: 32px; padding: 1px 9px; box-shadow: 0 0 0 1px var(--erp-input-border, var(--erp-color-border)) inset; }
.material-transfer-table :deep(.el-button.is-text) { padding: 4px; }
.row-actions { display: inline-flex; align-items: center; gap: 2px; }
.transfer-footer { display: flex; align-items: center; justify-content: flex-end; padding-top: 12px; }
@media (max-width: 1280px) { .filter-remark { width: 200px; } }
@media (max-width: 980px) { .filter-field { flex-basis: calc(33.333% - 8px); } .filter-remark { width: auto; } }
</style>
