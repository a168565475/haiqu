<script setup lang="ts">
import { setManualHardwareWeight } from './useHardwareWeightPreview'
import { compactDecimal } from '@/utils/compactDecimal'
import { packagingQuantity } from '@/utils/bomPackagingQuantity'
import { computed, onBeforeUnmount, ref, toRefs, watch } from 'vue'
import { fetchMaterialCatalog, materialCatalogError } from '@/api/materialCatalog'
import { Delete, Edit, FullScreen } from '@element-plus/icons-vue'
import BomLineImageSummary from '@/components/BomLineImageSummary.vue'
import BomCuttingCatalogSelect from './BomCuttingCatalogSelect.vue'
import { componentDemand, componentKey, componentMaterialValue, setComponentParent, setComponentUnit } from '@/utils/bomComposition'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import type { TubeCoatingColor } from '@/types/productionData'

type TubeCalculation = {
  total_consumption: string
  tube_cut_length_m: string
  branch_count: string
  base_purchase_bar_count: string
  purchase_allowance_bar_count: string
  suggested_purchase_meters: string
  suggested_purchase_weight_kg: string
}

type CuttingQuantity = {
  mode: string
  error?: string
  orderSets?: string | number | null
  orderPieces?: string | number | null
}

type LegacyPipeValues = {
  pieces: string | number
  sets: string | number
} | null

const emit = defineEmits<{
  'catalog-attribute-added': [id: string, previousVersion: string, version: string]
  'select-line': [line: BomLineInput]
}>()
const props = withDefaults(defineProps<{
  activeSection: BomSectionInput
  selectedLine?: BomLineInput
  isHardwareSection: boolean
  isPlasticSection: boolean
  isAuxiliarySection: boolean
  isFabricSection: boolean
  isPackagingSection: boolean
  isCuttingSection: boolean
  orderQuantity: string | number
  canEditCatalogAttributes?: boolean
  catalogRefreshKey?: number
  componentUnits?: Array<{ id: string; unit_name: string }>
  componentSources?: BomLineInput[]
  changeComponentType?: (line: BomLineInput, kind: 'SEWN_PART' | 'CUT_PIECE') => void
  canEdit: boolean
  tableFullscreen: boolean
  tubeOptionsLoading: boolean
  editorReferenceOptionsLoading: boolean
  tubeCoatingColors: TubeCoatingColor[]
  toggleTableFullscreen: () => void
  openLineDrawer: (index: number) => void
  removeLine: (index: number) => void
  openLineImageManager: (index: number) => void
  tubeCalculations: (line: BomLineInput) => TubeCalculation
  formatHardwareColor: (value: string) => string
  auxiliaryLineHasActiveProduct: (line: BomLineInput) => boolean
  auxiliarySpecificationOptions: (line: BomLineInput) => Array<{ id: string; label: string; disabled?: boolean }>
  setAuxiliarySpecification: (line: BomLineInput, value: string | null | undefined) => void
  auxiliaryColorOptions: (line: BomLineInput) => Array<{ id: string; label: string; disabled?: boolean }>
  setAuxiliaryColor: (line: BomLineInput, value: string | null | undefined) => void
  auxiliaryMaterialOptions: (line: BomLineInput) => Array<{ id: string; label: string; disabled?: boolean }>
  setAuxiliaryMaterial: (line: BomLineInput, value: string | null | undefined) => void
  fabricSpecificationOptions: (line: BomLineInput) => Array<{ id: string; label: string; disabled?: boolean }>
  setFabricSpecification: (line: BomLineInput, value: string | null | undefined) => void
  fabricMaterialOptions: (line: BomLineInput) => Array<{ id: string; label: string; disabled?: boolean }>
  setFabricMaterial: (line: BomLineInput, value: string | null | undefined) => void
  fabricColorSnapshot: (line: BomLineInput) => string
  fabricColorOptions: (line: BomLineInput) => Array<{ id: string; label: string; disabled?: boolean }>
  setFabricColor: (line: BomLineInput, value: string | null | undefined) => void
  fabricWidthOptions: (line: BomLineInput) => Array<{ id: string; label: string; disabled?: boolean }>
  setFabricWidth: (line: BomLineInput, value: string | null | undefined) => void
  cuttingQuantities: (line: BomLineInput) => CuttingQuantity
  legacyPipeCuttingValues: (line: BomLineInput) => LegacyPipeValues
}>(), {
  tubeCoatingColors: () => [],
  catalogRefreshKey: 0,
  componentUnits: () => [],
  componentSources: () => [],
})

const rowSelection = {
  onRowClick: (line: BomLineInput) => emit('select-line', line),
  rowClassName: ({ row }: { row: BomLineInput }) => row === props.selectedLine ? 'current-row' : '',
}
const componentParts = computed(() => props.activeSection.lines.filter(line => line.component_kind === 'SEWN_PART'))
const hasLegacyCutting = computed(() => props.activeSection.lines.some(line => !line.component_kind))
function selectComponentSource(line: BomLineInput, key: string) {
  const source = props.componentSources.find(item => componentKey(item) === key)
  line.fabric_source_line_id = source?.id || null
  line.fabric_source_client_key = source && !source.id ? source.client_key || null : null
}
function componentSourceDetails(line: BomLineInput) {
  return ([['原料规格', 'specification'], ['材质', 'material'], ['颜色', 'color'], ['色号', 'color_code'], ['门幅', 'width']] as const)
    .map(([label, field]) => `${label}：${componentMaterialValue(line, props.componentSources, field)}`).join('；')
}

const hardwareCatalogIds = computed(() => props.isHardwareSection
  ? [...new Set(props.activeSection.lines.map(line => line.material_catalog_id).filter((id): id is string => !!id))].sort()
  : [])
const hardwareSprayEnabled = ref<Record<string, boolean>>({})
const hardwareSprayErrors = ref<Record<string, string>>({})
let hardwareSprayRequest = 0
async function loadHardwareSprayConfiguration() {
  const request = ++hardwareSprayRequest
  hardwareSprayEnabled.value = {}
  hardwareSprayErrors.value = {}
  await Promise.all(hardwareCatalogIds.value.map(async id => {
    try {
      const { data } = await fetchMaterialCatalog(id)
      if (request !== hardwareSprayRequest) return
      if (data.id !== id || data.category_key !== 'HARDWARE' || typeof data.spray_enabled !== 'boolean') {
        throw new Error('五金品名的喷塑配置不匹配，请重新读取。')
      }
      hardwareSprayEnabled.value[id] = data.spray_enabled
    } catch (error) {
      if (request === hardwareSprayRequest) hardwareSprayErrors.value[id] = materialCatalogError(error)
    }
  }))
}
watch([() => hardwareCatalogIds.value.join('|'), () => props.catalogRefreshKey], loadHardwareSprayConfiguration, { immediate: true })
onBeforeUnmount(() => { ++hardwareSprayRequest })

const {
  activeSection,
  isHardwareSection,
  isPlasticSection,
  isAuxiliarySection,
  isFabricSection,
  isPackagingSection,
  isCuttingSection,
  canEdit,
  tableFullscreen,
  tubeOptionsLoading,
  editorReferenceOptionsLoading,
  tubeCoatingColors,
  toggleTableFullscreen,
  openLineDrawer,
  removeLine,
  openLineImageManager,
  tubeCalculations,
  formatHardwareColor,
  auxiliaryLineHasActiveProduct,
  auxiliarySpecificationOptions,
  setAuxiliarySpecification,
  auxiliaryColorOptions,
  setAuxiliaryColor,
  auxiliaryMaterialOptions,
  setAuxiliaryMaterial,
  fabricSpecificationOptions,
  setFabricSpecification,
  fabricMaterialOptions,
  setFabricMaterial,
  fabricColorSnapshot,
  fabricColorOptions,
  setFabricColor,
  fabricWidthOptions,
  setFabricWidth,
  cuttingQuantities,
  legacyPipeCuttingValues,
} = toRefs(props)
</script>

<template>
  <ElTable v-if="activeSection.section_type === 'PROFILE'" class="erp-table-editor tube-table prototype-tube-table" v-bind="rowSelection" :data="activeSection.lines" border empty-text="当前型材暂无用料，点击“添加材料”开始录入">
               <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                 <template #header><ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top"><ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" /></ElTooltip></template>
                 <template #default="scope"><div class="table-index-cell"><span class="table-row-number">{{ scope.$index + 1 }}</span><div v-if="canEdit" class="table-row-actions"><ElTooltip content="编辑当前行" placement="top"><ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" /></ElTooltip><ElTooltip content="删除当前行" placement="top"><ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click.stop="removeLine(scope.$index)" /></ElTooltip></div></div></template>
               </ElTableColumn>
               <ElTableColumn prop="part_name" label="部件名称" min-width="130" />
               <ElTableColumn prop="material" label="材质" width="90" />
                <ElTableColumn label="喷塑颜色" min-width="120">
                  <template #default="scope">
                    <span>{{ scope.row.tube_coating_color || '—' }}</span>
                  </template>
                </ElTableColumn>
               <ElTableColumn label="规格" min-width="118"><template #default="scope"><ElTooltip :content="scope.row.specification || `${scope.row.tube_diameter || '—'} × ${scope.row.tube_thickness || '—'}`" placement="top"><span class="profile-ellipsis-value">{{ scope.row.specification || `${scope.row.tube_diameter || '—'} × ${scope.row.tube_thickness || '—'}` }}</span></ElTooltip></template></ElTableColumn>
               <ElTableColumn prop="length_value" label="切割长度（mm）" width="100" ><template #default="{ row }">{{ compactDecimal(row.length_value) }}</template></ElTableColumn>
               <ElTableColumn prop="unit_consumption" label="单耗" width="78" ><template #default="{ row }">{{ compactDecimal(row.unit_consumption) }}</template></ElTableColumn>
               <ElTableColumn label="总需求（支）" width="110"><template #default="scope"><b>{{ tubeCalculations(scope.row).total_consumption }}</b></template></ElTableColumn>
               <ElTableColumn prop="tube_cut_piece_count" label="切割支数" width="90" />
               <ElTableColumn label="原材料长度（m）" width="105"><template #default="scope">{{ compactDecimal(tubeCalculations(scope.row).tube_cut_length_m) }}</template></ElTableColumn>
               <ElTableColumn label="采购根数" width="90"><template #default="scope"><b>{{ tubeCalculations(scope.row).base_purchase_bar_count }}</b></template></ElTableColumn>
               <ElTableColumn label="采购余量（根）" width="115"><template #default="scope">{{ tubeCalculations(scope.row).purchase_allowance_bar_count }}</template></ElTableColumn>
               <ElTableColumn label="建议采购重量（kg）" width="145"><template #default="scope">{{ compactDecimal(tubeCalculations(scope.row).suggested_purchase_weight_kg) }}</template></ElTableColumn>
               <ElTableColumn prop="notes" label="备注" min-width="90"><template #default="scope"><ElTooltip :content="scope.row.notes || '—'" placement="top"><span class="profile-ellipsis-value">{{ scope.row.notes || '—' }}</span></ElTooltip></template></ElTableColumn>
               <slot name="trailing-columns" />
             </ElTable>
            <ElTable v-else-if="isHardwareSection" class="erp-table-editor hardware-table" v-bind="rowSelection" :data="activeSection.lines" border scrollbar-always-on empty-text="当前五金件暂无数据，点击“选择数据”批量添加">
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
              <ElTableColumn label="单个材料重量（kg）" width="170"><template #default="scope"><ElInput v-model="scope.row.unit_material_weight_kg" inputmode="decimal" :disabled="!canEdit" placeholder="填写" @input="setManualHardwareWeight(scope.row)" /></template></ElTableColumn>
              <ElTableColumn label="喷塑颜色" min-width="165">
                <template #default="scope">
                  <ElSelect v-if="!scope.row.material_catalog_id || hardwareSprayEnabled[scope.row.material_catalog_id] === true" v-model="scope.row.powder_coating_color" filterable clearable :value-on-clear="''" :loading="tubeOptionsLoading" :disabled="!canEdit" placeholder="选择颜色">
                    <ElOption v-for="item in tubeCoatingColors" :key="item.id" :label="item.color_name" :value="item.color_name" />
                  </ElSelect>
                  <span v-else-if="hardwareSprayErrors[scope.row.material_catalog_id]" role="alert" :title="hardwareSprayErrors[scope.row.material_catalog_id]">配置读取失败 <ElButton link @click="loadHardwareSprayConfiguration">重试</ElButton></span>
                  <span v-else-if="hardwareSprayEnabled[scope.row.material_catalog_id] === undefined">读取配置中…</span>
                  <span v-else class="hardware-readonly-cell">{{ scope.row.powder_coating_color || '—' }}</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="喷塑单个面积（㎡）" width="175"><template #default="scope"><ElInput v-model="scope.row.powder_coating_unit_area_sqm" inputmode="decimal" :disabled="!canEdit" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="备注" min-width="170"><template #default="scope"><ElInput v-model="scope.row.notes" :disabled="!canEdit" maxlength="500" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
              <slot name="trailing-columns" />
            </ElTable>
            <ElTable v-else-if="isPlasticSection" class="erp-table-editor plastic-table" v-bind="rowSelection" :data="activeSection.lines" border scrollbar-always-on empty-text="当前塑料件暂无数据，点击“选择数据”批量添加">
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
              <slot name="trailing-columns" />
            </ElTable>
            <ElTable v-else-if="isAuxiliarySection" v-loading="editorReferenceOptionsLoading" class="erp-table-editor auxiliary-table" v-bind="rowSelection" :data="activeSection.lines" border scrollbar-always-on empty-text="当前辅料暂无数据，点击“选择辅料”批量添加">
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
              <slot name="trailing-columns" />
            </ElTable>
            <ElTable v-else-if="isFabricSection" v-loading="editorReferenceOptionsLoading" class="erp-table-editor fabric-table" v-bind="rowSelection" :data="activeSection.lines" border scrollbar-always-on empty-text="当前面料暂无数据，点击“添加面料”开始录入">
              <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                <template #header>
                  <ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top"><ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" /></ElTooltip>
                </template>
                <template #default="scope">
                  <div class="table-index-cell"><span class="table-row-number">{{ scope.$index + 1 }}</span><div v-if="canEdit" class="table-row-actions"><ElTooltip content="编辑当前行" placement="top"><ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" /></ElTooltip><ElTooltip content="删除当前行" placement="top"><ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click="removeLine(scope.$index)" /></ElTooltip></div></div>
                </template>
              </ElTableColumn>
              <ElTableColumn label="规格" min-width="140"><template #default="scope"><ElSelect v-model="scope.row.source_fabric_specification_id" filterable clearable :value-on-clear="null" :disabled="!canEdit || !!scope.row.material_catalog_id" :placeholder="scope.row.specification || '选择规格'" @change="setFabricSpecification(scope.row, $event)"><ElOption v-for="item in fabricSpecificationOptions(scope.row)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></template></ElTableColumn>
              <ElTableColumn label="材质" min-width="130"><template #default="scope"><ElSelect v-model="scope.row.source_fabric_material_id" filterable clearable :value-on-clear="null" :disabled="!canEdit || !!scope.row.material_catalog_id" :placeholder="scope.row.material || '选择材质'" @change="setFabricMaterial(scope.row, $event)"><ElOption v-for="item in fabricMaterialOptions(scope.row)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></template></ElTableColumn>
              <ElTableColumn label="色卡" min-width="200"><template #default="scope"><ElSelect v-model="scope.row.source_product_color_id" filterable clearable :value-on-clear="null" :disabled="!canEdit || !!scope.row.material_catalog_id" :placeholder="fabricColorSnapshot(scope.row) || '选择色卡 / 颜色 / 色号'" @change="setFabricColor(scope.row, $event)"><ElOption v-for="item in fabricColorOptions(scope.row)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></template></ElTableColumn>
              <ElTableColumn label="颜色" min-width="120" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.fabric_color_name || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="色号" min-width="120" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.fabric_color_code || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="门幅" min-width="120"><template #default="scope"><ElSelect v-model="scope.row.source_fabric_width_id" filterable clearable :value-on-clear="null" :disabled="!canEdit || !!scope.row.material_catalog_id" :placeholder="scope.row.fabric_width || '选择门幅'" @change="setFabricWidth(scope.row, $event)"><ElOption v-for="item in fabricWidthOptions(scope.row)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></template></ElTableColumn>
              <ElTableColumn label="单耗" width="120"><template #default="scope"><ElInput v-model="scope.row.unit_consumption" inputmode="decimal" :disabled="!canEdit" placeholder="填写" aria-label="单耗" /></template></ElTableColumn>
              <ElTableColumn label="裁片" min-width="150"><template #default="scope"><ElInput v-model="scope.row.part_name" :disabled="!canEdit || !!scope.row.material_catalog_id" maxlength="300" placeholder="填写裁片" /></template></ElTableColumn>
              <ElTableColumn label="单位" width="70"><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.unit || '米' }}</span></template></ElTableColumn>
              <ElTableColumn label="备注" min-width="170"><template #default="scope"><ElInput v-model="scope.row.notes" :disabled="!canEdit" maxlength="500" placeholder="填写" /></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
              <slot name="trailing-columns" />
            </ElTable>
            <ElTable v-else-if="isPackagingSection" class="erp-table-editor packaging-table" v-bind="rowSelection" :data="activeSection.lines" border scrollbar-always-on empty-text="当前包材暂无数据，点击“选择包材”批量添加">
              <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                <template #header><ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top"><ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" /></ElTooltip></template>
                <template #default="scope"><div class="table-index-cell"><span class="table-row-number">{{ scope.$index + 1 }}</span><div v-if="canEdit" class="table-row-actions"><ElTooltip content="编辑当前行" placement="top"><ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" /></ElTooltip><ElTooltip content="删除当前行" placement="top"><ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click="removeLine(scope.$index)" /></ElTooltip></div></div></template>
              </ElTableColumn>
              <ElTableColumn label="品名" min-width="165" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.part_name || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="材质" width="105" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.material || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="颜色" min-width="130" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ formatHardwareColor(scope.row.packaging_color) }}</span></template></ElTableColumn>
              <ElTableColumn label="规格" min-width="155" show-overflow-tooltip><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.specification || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="单位" width="76"><template #default="scope"><span class="hardware-readonly-cell">{{ scope.row.unit || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="*用量（多少成品用一份）" width="190"><template #default="scope"><ElInput v-model="scope.row.units_per_box" inputmode="decimal" :disabled="!canEdit" placeholder="正数，最多 4 位小数" /></template></ElTableColumn>
              <ElTableColumn label="需求数量" width="125"><template #default="scope">{{ packagingQuantity(scope.row.units_per_box, props.orderQuantity) || '—' }}</template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
              <slot name="trailing-columns" />
            </ElTable>
            <ElTable v-else-if="isCuttingSection" class="erp-table-editor cutting-table" v-bind="rowSelection" :data="activeSection.lines" border scrollbar-always-on empty-text="当前暂无部位或裁片，点击“添加材料”选择已有品名">
              <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                <template #header><ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top"><ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" /></ElTooltip></template>
                <template #default="scope"><div class="table-index-cell"><span class="table-row-number">{{ scope.$index + 1 }}</span><div v-if="canEdit" class="table-row-actions"><ElTooltip content="编辑当前行" placement="top"><ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" /></ElTooltip><ElTooltip content="删除当前行" placement="top"><ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click="removeLine(scope.$index)" /></ElTooltip></div></div></template>
              </ElTableColumn>
              <ElTableColumn label="类型" width="110"><template #default="{ row }"><ElSelect :model-value="row.component_kind || ''" :disabled="!canEdit" placeholder="待设置" aria-label="类型" @change="changeComponentType?.(row, $event)"><ElOption label="部位" value="SEWN_PART" /><ElOption label="裁片" value="CUT_PIECE" /></ElSelect></template></ElTableColumn>
              <ElTableColumn label="品名" min-width="160"><template #default="{ row }"><BomCuttingCatalogSelect v-if="row.component_kind" :line="row" @focusin="emit('select-line', row)" :refresh-key="catalogRefreshKey" :disabled="!canEdit" :can-edit-catalog-attributes="canEditCatalogAttributes" @catalog-attribute-added="(id, previousVersion, version) => emit('catalog-attribute-added', id, previousVersion, version)" lazy /><template v-else-if="cuttingQuantities(row).mode !== 'legacy' && cuttingQuantities(row).error"><ElTooltip placement="top-start" effect="light" popper-class="cutting-name-error-tooltip" :show-after="100" :teleported="true"><template #content><span role="alert">{{ cuttingQuantities(row).error }}</span></template><span class="hardware-readonly-cell cutting-name-tooltip-anchor has-error" tabindex="0">{{ row.part_name || '—' }}</span></ElTooltip></template><span v-else class="hardware-readonly-cell">{{ row.part_name || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="所属部位" min-width="150"><template #default="{ row }"><ElSelect v-if="row.component_kind === 'CUT_PIECE'" :model-value="row.parent_part_id || row.parent_part_client_key || ''" :disabled="!canEdit" placeholder="选择部位" aria-label="所属部位" @change="setComponentParent(row, $event, activeSection.lines)"><ElOption v-for="part in componentParts" :key="componentKey(part)" :value="componentKey(part)" :label="part.part_name || '未选择品名的部位'" /></ElSelect><span v-else>—</span></template></ElTableColumn>
              <ElTableColumn label="原料资料" min-width="260"><template #default="{ row }"><div class="component-source-cell" :title="row.component_kind ? componentSourceDetails(row) : undefined"><ElSelect v-if="row.component_kind" :model-value="row.fabric_source_line_id || row.fabric_source_client_key || ''" :disabled="!canEdit" filterable :clearable="row.component_kind === 'SEWN_PART'" value-on-clear="" :placeholder="row.component_kind === 'SEWN_PART' ? '选择归属面布' : '选择布料或棉'" :aria-label="row.component_kind === 'SEWN_PART' ? '归属面布' : '来源原料'" @change="selectComponentSource(row, $event)"><ElOption v-for="source in componentSources" :key="componentKey(source)" :value="componentKey(source)" :label="`${source.part_name} · ${source.specification}`" /></ElSelect><ElTooltip v-else :content="componentSourceDetails(row)" placement="top" effect="light"><span class="component-source-summary" tabindex="0">{{ componentMaterialValue(row, componentSources, 'material') }} / {{ componentMaterialValue(row, componentSources, 'color') }} / 门幅 {{ componentMaterialValue(row, componentSources, 'width') }}</span></ElTooltip></div></template></ElTableColumn>
              <ElTableColumn label="尺寸 / 规格" min-width="160"><template #default="{ row }"><ElInput v-model="row.specification" :disabled="!canEdit" maxlength="500" :placeholder="row.component_kind === 'SEWN_PART' ? '填写部位规格' : '必填，不能填 /'" :aria-label="row.component_kind === 'SEWN_PART' ? '部位规格' : row.component_kind ? '裁片尺寸或规格' : '裁剪规格'" :aria-required="row.component_kind !== 'SEWN_PART'" /></template></ElTableColumn>
              <ElTableColumn label="单件用量" width="120"><template #default="{ row }"><ElInput v-if="row.component_kind === 'SEWN_PART'" v-model="row.parts_per_product" :disabled="!canEdit" inputmode="numeric" aria-label="每产品部位数量" title="每件成品所需的部位数量" /><ElInput v-else-if="row.component_kind === 'CUT_PIECE'" v-model="row.pieces_per_part" :disabled="!canEdit" inputmode="numeric" aria-label="每部位用量" title="每个所属部位所需的裁片用量，按所选单位计数" /><span v-else>—</span></template></ElTableColumn>
              <ElTableColumn v-if="hasLegacyCutting" label="裁片量（片/套）" width="125"><template #default="scope"><span v-if="scope.row.component_kind">—</span><span v-else-if="legacyPipeCuttingValues(scope.row)" class="cutting-legacy-value">{{ legacyPipeCuttingValues(scope.row)?.pieces }}</span><ElInput v-else v-model="scope.row.cutting_pieces_per_set" inputmode="numeric" :disabled="!canEdit" placeholder="待填写" aria-label="裁片量（片/套）" /></template></ElTableColumn>
              <ElTableColumn v-if="hasLegacyCutting" label="每成品套数（套/成品）" width="155"><template #default="scope"><span v-if="scope.row.component_kind">—</span><span v-else-if="legacyPipeCuttingValues(scope.row)" class="cutting-legacy-value">{{ legacyPipeCuttingValues(scope.row)?.sets }}</span><ElInput v-else v-model="scope.row.cutting_sets_per_product" inputmode="numeric" :disabled="!canEdit" placeholder="待填写" aria-label="每成品套数（套/成品）" /></template></ElTableColumn>
              <ElTableColumn v-if="hasLegacyCutting" label="订单裁剪套数" width="125"><template #default="{ row }">{{ row.component_kind ? '—' : cuttingQuantities(row).orderSets || '—' }}</template></ElTableColumn>
              <ElTableColumn label="订单需求" width="125"><template #default="{ row }">{{ row.component_kind ? componentDemand(row, activeSection.lines, String(orderQuantity)) : cuttingQuantities(row).orderPieces || '—' }}</template></ElTableColumn>
              <ElTableColumn label="单位" width="110"><template #default="{ row }"><ElSelect v-if="row.component_kind" :model-value="row.unit" :disabled="!canEdit" :loading="editorReferenceOptionsLoading" placeholder="选择单位" :aria-label="row.component_kind === 'SEWN_PART' ? '部位单位' : '裁片单位'" @change="setComponentUnit(row, $event)"><ElOption v-for="unit in componentUnits" :key="unit.id" :label="unit.unit_name" :value="unit.unit_name" /></ElSelect><ElInput v-else-if="cuttingQuantities(row).mode === 'legacy'" v-model="row.unit" :disabled="!canEdit" maxlength="50" placeholder="填写单位" /><span v-else>套</span></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
              <ElTableColumn label="备注" min-width="260"><template #default="scope"><ElInput v-model="scope.row.notes" :disabled="!canEdit" maxlength="500" placeholder="填写" /></template></ElTableColumn>
              <slot name="trailing-columns" />
            </ElTable>
            <ElTable class="erp-table-editor" v-else-if="activeSection.lines.length" :data="activeSection.lines" border scrollbar-always-on>
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
              <ElTableColumn label="配件 / 裁片名称" min-width="170"><template #default="scope"><ElInput v-model="scope.row.part_name" :disabled="!canEdit || !!scope.row.material_catalog_id" /></template></ElTableColumn>
              <ElTableColumn v-if="activeSection.section_type !== 'FABRIC'" label="规格 / 厚度" min-width="145"><template #default="scope"><ElInput v-model="scope.row.specification" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn v-if="activeSection.section_type === 'FABRIC'" label="原材料" min-width="160"><template #default="scope"><ElInput v-model="scope.row.raw_material" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn v-if="activeSection.section_type === 'FABRIC'" label="裁片量" width="100"><template #default="scope"><ElInput v-model="scope.row.cut_piece_quantity" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn label="单耗" width="100"><template #default="scope"><ElInput v-model="scope.row.unit_consumption" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn label="当前需求" width="120"><template #default="scope"><ElInput v-model="scope.row.total_consumption" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn label="单位" width="90"><template #default="scope"><ElInput v-model="scope.row.unit" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn label="备注" min-width="160"><template #default="scope"><ElInput v-model="scope.row.notes" :disabled="!canEdit" /></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
              <slot name="trailing-columns" />
            </ElTable>
            <div v-else class="pending-section-fields">
              <strong>{{ activeSection.title }}</strong>
              <span>该固定分区的填写字段待后续完善，本轮不套用其他分区的字段。</span>
            </div>
</template>





<style scoped lang="scss">
.table-index-cell { position: relative; display: flex; min-height: 32px; align-items: center; justify-content: center; font-variant-numeric: tabular-nums; }
.component-source-cell { min-width: 0; }
.component-source-summary { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
.table-row-actions { position: absolute; inset: 0; display: none; align-items: center; justify-content: center; gap: 2px; }
:deep(.el-table__row:hover) .table-row-number { display: none; }
:deep(.el-table__row:hover) .table-row-actions { display: flex; }
.table-fullscreen-button { width: 28px; min-width: 28px; height: 28px; padding: 0; }
.row-action-button { width: 28px; min-width: 28px; height: 28px; padding: 0; }
.row-action-button :deep(.el-icon) { font-size: 16px; }
.row-delete-button { margin-left: 0; }
.pending-section-fields { display: flex; min-height: 180px; align-items: center; justify-content: center; flex-direction: column; gap: 10px; border: 1px solid var(--erp-color-border); border-top: 0; background: var(--erp-color-subtle); color: var(--erp-color-text-secondary); }
.pending-section-fields strong { color: var(--erp-color-text-primary); font-size: 15px; }
.prototype-tube-table { --el-table-header-bg-color: var(--erp-table-header-background); --el-table-border-color: var(--erp-table-border); --el-table-row-hover-bg-color: var(--erp-table-hover); }
.prototype-tube-table :deep(th.el-table__cell), .prototype-tube-table :deep(td.el-table__cell) { height: 42px; padding: 0; font-size: 12px; }
.prototype-tube-table :deep(.el-table__body td.el-table__cell) { background: var(--erp-table-background); }
.profile-ellipsis-value { display: block; width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hardware-readonly-cell { display: flex; min-height: 32px; align-items: center; padding: 0 7px; overflow: hidden; box-sizing: border-box; color: var(--erp-input-readonly-text); text-overflow: ellipsis; white-space: nowrap; }
.cutting-legacy-value { display: flex; min-height: 32px; align-items: center; padding: 0 7px; box-sizing: border-box; border: 1px solid var(--erp-input-border); border-radius: 5px; background: var(--erp-input-readonly-background); color: var(--erp-input-readonly-text); font-variant-numeric: tabular-nums; }
:deep(.erp-table-editor) { --el-table-bg-color: var(--erp-table-background); --el-table-tr-bg-color: var(--erp-table-background); --el-table-header-bg-color: var(--erp-table-header-background); --el-table-border-color: var(--erp-table-border); --el-table-row-hover-bg-color: var(--erp-table-hover); }
:deep(.erp-table-editor .cell) { padding: 0 5px !important; }
:deep(.erp-table-editor .control-column .cell), :deep(.erp-table-editor .control-column-header .cell) { padding: 0 !important; text-align: center; }
:deep(.erp-table-editor .el-table__body-wrapper .el-scrollbar__view) { padding-bottom: 22px; box-sizing: border-box; }
:deep(.erp-table-editor .el-select) { width: 100%; }
:deep(.erp-table-editor .el-input__wrapper), :deep(.erp-table-editor .el-select__wrapper) { padding: 1px 7px; border-radius: 5px; background: var(--erp-input-background); box-shadow: 0 0 0 1px var(--erp-input-border) inset; }
:deep(.erp-table-editor .el-input__wrapper:hover), :deep(.erp-table-editor .el-input__wrapper.is-focus), :deep(.erp-table-editor .el-select__wrapper:hover), :deep(.erp-table-editor .el-select__wrapper.is-focused) { background: var(--erp-input-background); box-shadow: 0 0 0 1px var(--erp-input-focus-border) inset; }
:deep(.erp-table-editor .el-input__inner::placeholder), :deep(.erp-table-editor .el-select__placeholder) { color: var(--erp-input-placeholder); }
</style>


