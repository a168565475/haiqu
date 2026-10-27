<script setup lang="ts">
import { compactDecimal } from '@/utils/compactDecimal'
import { toRefs } from 'vue'
import { Delete, Edit, FullScreen } from '@element-plus/icons-vue'
import BomLineImageSummary from '@/components/BomLineImageSummary.vue'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import type { TubeCoatingColor } from '@/types/productionData'

type TubeCalculation = {
  total_consumption: string
  tube_cut_length_m: string
  branch_count: string
  suggested_purchase_meters: string
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

const props = withDefaults(defineProps<{
  activeSection: BomSectionInput
  isHardwareSection: boolean
  isPlasticSection: boolean
  isAuxiliarySection: boolean
  isFabricSection: boolean
  isPackagingSection: boolean
  isCuttingSection: boolean
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
})

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
  <ElTable v-if="activeSection.section_type === 'PROFILE'" class="erp-table-editor tube-table prototype-tube-table" :data="activeSection.lines" border empty-text="当前型材暂无用料，点击“添加材料”开始录入">
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
               <ElTableColumn prop="length_value" label="切割长度（mm）" width="100" ><template #default="{ row }">{{ compactDecimal(row.length_value) }}</template></ElTableColumn>
               <ElTableColumn prop="unit_consumption" label="单耗" width="78" ><template #default="{ row }">{{ compactDecimal(row.unit_consumption) }}</template></ElTableColumn>
               <ElTableColumn label="总需求（支）" width="110"><template #default="scope"><b>{{ tubeCalculations(scope.row).total_consumption }}</b></template></ElTableColumn>
               <ElTableColumn prop="tube_cut_piece_count" label="切割支数" width="90" />
               <ElTableColumn label="原材料长度（m）" width="105"><template #default="scope">{{ compactDecimal(tubeCalculations(scope.row).tube_cut_length_m) }}</template></ElTableColumn>
               <ElTableColumn label="采购根数" width="90"><template #default="scope"><b>{{ tubeCalculations(scope.row).branch_count }}</b></template></ElTableColumn>
               <ElTableColumn label="建议采购米数" width="115"><template #default="scope">{{ compactDecimal(tubeCalculations(scope.row).suggested_purchase_meters) }}</template></ElTableColumn>
               <ElTableColumn prop="notes" label="备注" min-width="90"><template #default="scope"><ElTooltip :content="scope.row.notes || '—'" placement="top"><span class="profile-ellipsis-value">{{ scope.row.notes || '—' }}</span></ElTooltip></template></ElTableColumn>
             </ElTable>
            <ElTable v-else-if="isHardwareSection" class="erp-table-editor hardware-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前五金件暂无数据，点击“选择数据”批量添加">
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
            <ElTable v-else-if="isPlasticSection" class="erp-table-editor plastic-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前塑料件暂无数据，点击“选择数据”批量添加">
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
            <ElTable v-else-if="isAuxiliarySection" v-loading="editorReferenceOptionsLoading" class="erp-table-editor auxiliary-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前辅料暂无数据，点击“选择辅料”批量添加">
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
            <ElTable v-else-if="isFabricSection" v-loading="editorReferenceOptionsLoading" class="erp-table-editor fabric-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前面料暂无数据，点击“添加面料”开始录入">
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
            <ElTable v-else-if="isPackagingSection" class="erp-table-editor packaging-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前包材暂无数据，点击“选择包材”批量添加">
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
            <ElTable v-else-if="isCuttingSection" class="erp-table-editor cutting-table" :data="activeSection.lines" border scrollbar-always-on empty-text="当前裁剪明细暂无数据，点击“选择裁剪”批量添加">
              <ElTableColumn width="64" fixed="left" align="center" header-align="center" class-name="control-column" label-class-name="control-column-header">
                <template #header><ElTooltip :content="tableFullscreen ? '退出全屏' : '全屏'" placement="top"><ElButton class="table-fullscreen-button" size="small" circle plain :icon="FullScreen" :aria-label="tableFullscreen ? '退出全屏' : '全屏'" @click="toggleTableFullscreen" /></ElTooltip></template>
                <template #default="scope"><div class="table-index-cell"><span class="table-row-number">{{ scope.$index + 1 }}</span><div v-if="canEdit" class="table-row-actions"><ElTooltip content="编辑当前行" placement="top"><ElButton class="row-action-button" size="small" circle link :icon="Edit" aria-label="编辑当前行" @click.stop="openLineDrawer(scope.$index)" /></ElTooltip><ElTooltip content="删除当前行" placement="top"><ElButton class="row-action-button row-delete-button" size="small" circle link type="danger" :icon="Delete" aria-label="删除当前行" @click="removeLine(scope.$index)" /></ElTooltip></div></div></template>
              </ElTableColumn>
              <ElTableColumn label="裁剪名称" min-width="125"><template #default="scope"><template v-if="cuttingQuantities(scope.row).mode !== 'legacy' && cuttingQuantities(scope.row).error"><ElTooltip placement="top-start" effect="light" popper-class="cutting-name-error-tooltip" :show-after="100" :teleported="true"><template #content><span role="alert">{{ cuttingQuantities(scope.row).error }}</span></template><span class="hardware-readonly-cell cutting-name-tooltip-anchor has-error" tabindex="0">{{ scope.row.part_name || '—' }}</span></ElTooltip></template><span v-else class="hardware-readonly-cell">{{ scope.row.part_name || '—' }}</span></template></ElTableColumn>
              <ElTableColumn label="*规格" min-width="140"><template #default="scope"><ElInput v-model="scope.row.specification" :disabled="!canEdit" maxlength="500" placeholder="必填，不能填 /" aria-label="裁剪规格" aria-required="true" /></template></ElTableColumn>
              <ElTableColumn label="裁片量（片/套）" width="125"><template #default="scope"><span v-if="legacyPipeCuttingValues(scope.row)" class="cutting-legacy-value" :title="'管材旧口径，按根/支流转；此处为开发试算展示'">{{ legacyPipeCuttingValues(scope.row)?.pieces }}</span><ElInput v-else v-model="scope.row.cutting_pieces_per_set" inputmode="numeric" :disabled="!canEdit" placeholder="待填写" aria-label="裁片量（片/套）" /></template></ElTableColumn>
              <ElTableColumn label="每成品套数（套/成品）" width="155"><template #default="scope"><span v-if="legacyPipeCuttingValues(scope.row)" class="cutting-legacy-value" :title="'管材旧口径没有该布料字段，开发试算按 1 套展示'">{{ legacyPipeCuttingValues(scope.row)?.sets }}</span><ElInput v-else v-model="scope.row.cutting_sets_per_product" inputmode="numeric" :disabled="!canEdit" placeholder="待填写" aria-label="每成品套数（套/成品）" /></template></ElTableColumn>
              <ElTableColumn label="订单裁剪套数" width="125"><template #default="scope">{{ cuttingQuantities(scope.row).orderSets || '—' }}</template></ElTableColumn>
              <ElTableColumn label="订单裁剪片数" width="125"><template #default="scope">{{ cuttingQuantities(scope.row).orderPieces || '—' }}</template></ElTableColumn>
              <ElTableColumn label="流转单位" width="100"><template #default="scope"><ElInput v-if="cuttingQuantities(scope.row).mode === 'legacy'" v-model="scope.row.unit" :disabled="!canEdit" maxlength="50" placeholder="填写单位" /><span v-else>套</span></template></ElTableColumn>
              <ElTableColumn label="图片" width="210"><template #default="scope"><BomLineImageSummary :line="scope.row" :editable="canEdit" @open="openLineImageManager(scope.$index)" /></template></ElTableColumn>
              <ElTableColumn label="备注" min-width="260"><template #default="scope"><ElInput v-model="scope.row.notes" :disabled="!canEdit" maxlength="500" placeholder="填写" /></template></ElTableColumn>
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
</template>





<style scoped lang="scss">
.table-index-cell { position: relative; display: flex; min-height: 32px; align-items: center; justify-content: center; font-variant-numeric: tabular-nums; }
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


