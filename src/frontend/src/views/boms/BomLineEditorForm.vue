<script setup lang="ts">
import { computed, ref, toRefs } from 'vue'
import MaterialSelectionPanel from '@/components/products/MaterialSelectionPanel.vue'
import BomCuttingCatalogSelect from './BomCuttingCatalogSelect.vue'
import type { MaterialCatalog, PublicMaterialOptions } from '@/types/materialCatalog'
import PinyinFilterSelect from '@/components/production/PinyinFilterSelect.vue'
import { compactDecimal } from '@/utils/compactDecimal'
import { packagingQuantity } from '@/utils/bomPackagingQuantity'
import { defaultPurchaseAllowanceRule, purchaseAllowanceOptions } from '@/utils/materialFlow'
import type { BomDetail, BomLineInput, BomSectionInput, PurchaseAllowanceRule } from '@/types/bom'

type AnyRecord = Record<string, any>
type AnyFunction = (...args: any[]) => any
type DisplayImage = AnyRecord

const props = withDefaults(defineProps<{
  catalogMode?: boolean
  catalogRefreshKey?: number
  editingSection: BomSectionInput | null
  editingLineDraft: BomLineInput | null
  editorReferenceOptionsError: string
  ensureEditorReferenceOptions: AnyFunction
  tubeShapes: AnyRecord[]
  tubeProductNames: AnyRecord[]
  tubeMaterials: AnyRecord[]
  tubeDiameters: AnyRecord[]
  tubeThicknesses: AnyRecord[]
  tubeCoatingColors: AnyRecord[]
  tubeOptionsLoading: boolean
  editingLineCalculations: AnyRecord | null
  tubeCalculationLoading?: boolean
  tubeCalculationReadonly?: boolean
  normalizeTubeCutPieceCount: AnyFunction
  displayLineImages: (line: BomLineInput) => DisplayImage[]
  openLineImageManager: AnyFunction
  formatHardwareColor: (value: string) => string
  auxiliaryLineHasActiveProduct: (line: BomLineInput) => boolean
  auxiliarySpecificationOptions: AnyFunction
  setAuxiliarySpecification: AnyFunction
  auxiliaryColorOptions: AnyFunction
  setAuxiliaryColor: AnyFunction
  auxiliaryMaterialOptions: AnyFunction
  setAuxiliaryMaterial: AnyFunction
  fabricSpecificationOptions: AnyFunction
  setFabricSpecification: AnyFunction
  fabricColorSnapshot: AnyFunction
  fabricColorOptions: AnyFunction
  setFabricColor: AnyFunction
  fabricMaterialOptions: AnyFunction
  setFabricMaterial: AnyFunction
  fabricWidthOptions: AnyFunction
  setFabricWidth: AnyFunction
  isPipeCuttingLine: (line: BomLineInput | null | undefined) => boolean
  editingFabricSourceKey: string
  fabricSourceLines: BomLineInput[]
  legacyPipeCuttingValues: AnyFunction
  editingCuttingCalculation: AnyRecord | null
  bom: BomDetail | null
  number: AnyFunction
}>(), {
  tubeShapes: () => [],
  tubeProductNames: () => [],
  tubeMaterials: () => [],
  tubeDiameters: () => [],
  tubeThicknesses: () => [],
  tubeCoatingColors: () => [],
})

const emit = defineEmits<{
  maintain: []
  'use-catalog': []
  'update:editingFabricSourceKey': [value: string]
}>()
const currentCatalog = ref<MaterialCatalog>()
const currentPublicSpray = ref<PublicMaterialOptions>()
const selectedPurchaseAllowance = computed(() => props.editingLineDraft?.purchase_allowance_mode === 'MANUAL'
  ? props.editingLineDraft.purchase_allowance_rule : props.editingLineDraft?.purchase_allowance_mode === 'AUTO' ? 'AUTO' : '')
const automaticPurchaseAllowanceLabel = computed(() => {
  const baseCount = String(props.editingLineCalculations?.base_purchase_bar_count || '')
  if (!/^\d+$/.test(baseCount)) return '自动（按采购根数选择）'
  const rule = defaultPurchaseAllowanceRule(BigInt(baseCount))
  return `自动（${purchaseAllowanceOptions.find(option => option.value === rule)?.label}）`
})
function selectPurchaseAllowance(value: PurchaseAllowanceRule | 'AUTO') {
  if (!props.editingLineDraft) return
  props.editingLineDraft.purchase_allowance_mode = value === 'AUTO' ? 'AUTO' : 'MANUAL'
  props.editingLineDraft.purchase_allowance_rule = value === 'AUTO' ? '' : value
}
const coatingOptions = computed(() => props.catalogMode ? (currentPublicSpray.value?.values || []).filter(value => value.field_key === 'color').map(value => ({ id: value.id, color_name: value.value })) : props.tubeCoatingColors)
const catalogCoatingEnabled = computed(() => !!currentCatalog.value?.spray_enabled && !!currentPublicSpray.value && currentCatalog.value.id === props.editingLineDraft?.material_catalog_id)
const coatingPlaceholder = computed(() => {
  if (props.catalogMode) {
    if (!props.editingLineDraft?.material_catalog_id) return '请先选择品名'
    if (!currentCatalog.value || currentCatalog.value.id !== props.editingLineDraft.material_catalog_id) return '品名配置未加载，请重新选择'
    if (!currentCatalog.value.spray_enabled) return '该品名未启用半成品'
    if (!currentPublicSpray.value) return '喷塑颜色未加载，请重新选择品名'
  }
  return coatingOptions.value.length ? '选择喷塑颜色' : '暂无喷塑颜色，请到维护配置新增'
})
const selectedAttributes = computed(() => props.editingLineDraft?.material_selection?.attributes ?? props.editingLineDraft?.material_selection_snapshot?.attributes)
const selectedColor = computed(() => props.editingLineDraft?.material_selection ?? props.editingLineDraft?.material_selection_snapshot)
function selectedAttribute(key: string, fallback: string): string {
  return (props.catalogMode && selectedAttributes.value ? selectedAttributes.value[key] : fallback) || '—'
}
const selectedSpecification = computed(() => {
  if (props.catalogMode && selectedAttributes.value) {
    return ['fabric_spec', 'specification', 'section_size', 'size', 'model', 'width']
      .map(key => selectedAttributes.value?.[key]).filter(Boolean).join(' / ') || '—'
  }
  return props.editingLineDraft?.specification || '—'
})
const editingFabricSourceKeyModel = computed({
  get: () => props.editingFabricSourceKey,
  set: value => emit('update:editingFabricSourceKey', value),
})

const {
  editingSection, editingLineDraft, editorReferenceOptionsError, ensureEditorReferenceOptions,
  tubeShapes, tubeProductNames, tubeMaterials, tubeDiameters, tubeThicknesses,
  tubeOptionsLoading, editingLineCalculations, normalizeTubeCutPieceCount, displayLineImages,
  openLineImageManager, formatHardwareColor, auxiliaryLineHasActiveProduct,
  auxiliarySpecificationOptions, setAuxiliarySpecification, auxiliaryColorOptions, setAuxiliaryColor,
  auxiliaryMaterialOptions, setAuxiliaryMaterial, fabricSpecificationOptions, setFabricSpecification,
  fabricColorSnapshot, fabricColorOptions, setFabricColor, fabricMaterialOptions, setFabricMaterial,
  fabricWidthOptions, setFabricWidth, isPipeCuttingLine, fabricSourceLines,
  legacyPipeCuttingValues, editingCuttingCalculation, bom, number,
} = toRefs(props)
</script>

<template>
        <div v-if="editingLineDraft">
          <ElButton v-if="!catalogMode" size="small" @click="emit('use-catalog')">从新原料选择</ElButton>
          <div class="line-drawer-form" :style="{ marginTop: catalogMode ? '0' : '16px' }">
          <label v-if="editingSection?.title === '裁剪明细'" class="drawer-field"><span>来源面料</span><strong v-if="isPipeCuttingLine(editingLineDraft)" class="drawer-readonly-value">管材半成品 · 不关联面料</strong><template v-else><ElSelect v-model="editingFabricSourceKeyModel" filterable placeholder="选择本 BOM 的面料" aria-label="来源面料" no-data-text="请先在面料分类添加并选择面料"><ElOption v-for="line in fabricSourceLines" :key="line.id || line.client_key" :label="`${line.part_name || '面料'} · ${line.fabric_color_name || line.material} · ${line.specification}`" :value="(line.id || line.client_key)!" /></ElSelect><small v-if="!catalogMode">材质和颜色自动使用来源面料，保存 BOM 时一并保存关联。</small></template></label>
          <label v-if="catalogMode && editingSection?.title === '裁剪明细'" class="drawer-field"><span>品名</span><BomCuttingCatalogSelect :key="editingLineDraft.client_key || editingLineDraft.id" :line="editingLineDraft" :refresh-key="catalogRefreshKey" /></label>
          <MaterialSelectionPanel v-else-if="catalogMode && editingSection" :key="editingLineDraft.client_key || editingLineDraft.id" presentation="dropdown" :line="editingLineDraft" :section-title="editingSection.title" :refresh-key="catalogRefreshKey" :fixed-unit="editingSection.section_type === 'PROFILE' ? '根' : editingSection.title === '面料类' ? '米' : undefined" @maintain="emit('maintain')" @loaded="currentCatalog = $event" @public-options="currentPublicSpray = $event" />
          <ElAlert
            v-if="!catalogMode && (editingSection?.title === '辅料类' || editingSection?.title === '面料类') && editorReferenceOptionsError"
            class="reference-options-error drawer-field--wide"
            type="error"
            :title="editorReferenceOptionsError"
            show-icon
            :closable="false"
          >
            <template #default><ElButton size="small" @click="ensureEditorReferenceOptions">重新加载生产维护数据</ElButton></template>
          </ElAlert>
          <template v-if="editingSection?.section_type === 'PROFILE'">
            <template v-if="!catalogMode">
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
            </template>
            <template v-else>
              <label class="drawer-field"><span>材质</span><strong class="drawer-readonly-value">{{ selectedAttribute('material', editingLineDraft.material) }}</strong></label>
              <label class="drawer-field"><span>形状</span><strong class="drawer-readonly-value">{{ selectedAttribute('shape', editingLineDraft.tube_shape) }}</strong></label>
              <label class="drawer-field"><span>规格</span><strong class="drawer-readonly-value">{{ selectedAttribute('section_size', editingLineDraft.tube_diameter) }}</strong></label>
              <label class="drawer-field"><span>厚度</span><strong class="drawer-readonly-value">{{ selectedAttribute('thickness', editingLineDraft.tube_thickness) }}</strong></label>
              <label class="drawer-field"><span>颜色</span><strong class="drawer-readonly-value">{{ selectedAttribute('color', '') }}</strong></label>
            </template>
            <label class="drawer-field">
              <span>喷塑颜色</span>
              <strong v-if="catalogMode" class="drawer-readonly-value">{{ editingLineDraft.tube_coating_color || '—' }}</strong>
              <ElSelect v-else v-model="editingLineDraft.tube_coating_color" filterable clearable :value-on-clear="''" :loading="tubeOptionsLoading" :placeholder="coatingPlaceholder" no-data-text="暂无喷塑颜色，请到分区的维护配置新增" aria-label="喷塑颜色">
                <ElOption v-for="item in coatingOptions" :key="item.id" :label="item.color_name" :value="item.color_name" />
              </ElSelect>
            </label>
            <label class="drawer-field">
              <span>采购余量</span>
              <ElSelect :model-value="selectedPurchaseAllowance" :placeholder="editingLineDraft.purchase_allowance_mode ? '填写切割参数后自动选择' : '沿用已保存规则'" aria-label="采购余量" @change="selectPurchaseAllowance">
                <ElOption value="AUTO" :label="automaticPurchaseAllowanceLabel" />
                <ElOption v-for="option in purchaseAllowanceOptions" :key="option.value" :value="option.value" :label="option.label" />
              </ElSelect>
            </label>
            <div class="pipe-quantity-row">
              <label class="drawer-field"><span>切割长度（mm）</span><ElInput v-model="editingLineDraft.length_value" inputmode="numeric" placeholder="正整数毫米" aria-label="切割长度（mm）" /></label>
              <label class="drawer-field"><span>切割支数</span><ElInput v-model="editingLineDraft.tube_cut_piece_count" inputmode="decimal" placeholder="填写" aria-label="切割支数" @blur="normalizeTubeCutPieceCount(editingLineDraft)" /></label>
              <label class="drawer-field"><span>单个用量</span><ElInput v-model="editingLineDraft.unit_consumption" inputmode="decimal" placeholder="填写" aria-label="单个用量" /></label>
            </div>
            <label class="drawer-field"><span>原材料单位</span><strong class="drawer-readonly-value">根</strong></label>
            <label class="drawer-field"><span>原材料长度（m）</span><strong class="drawer-readonly-value">{{ editingLineCalculations?.tube_cut_length_m }}</strong></label>
            <label class="drawer-field"><span>喷塑单支面积（㎡）</span><ElInput v-model="editingLineDraft.coating_unit_area_sqm" inputmode="decimal" :readonly="tubeCalculationReadonly" :placeholder="tubeCalculationReadonly ? (tubeCalculationLoading ? '计算中…' : '按生产维护公式计算') : '填写'" aria-label="喷塑单支面积" /></label>
            <label class="drawer-field drawer-purchase-weight-field"><span>单支重量（kg）</span><ElInput v-model="editingLineDraft.purchase_unit_weight_kg" inputmode="decimal" :readonly="tubeCalculationReadonly" :placeholder="tubeCalculationReadonly ? (tubeCalculationLoading ? '计算中…' : '按生产维护公式计算') : '填写'" aria-label="单支重量" /></label>
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
                <label><span>原材料长度（m）</span><strong>{{ compactDecimal(editingLineCalculations.tube_cut_length_m) }}</strong></label>
                <label><span>采购根数</span><strong>{{ editingLineCalculations.base_purchase_bar_count }}</strong></label>
                <label><span>采购余量（根）</span><strong>{{ editingLineCalculations.purchase_allowance_bar_count }}</strong></label>
                <label><span>建议采购根数</span><strong>{{ editingLineCalculations.branch_count }}</strong></label>
                <label><span>建议采购米数</span><strong>{{ compactDecimal(editingLineCalculations.suggested_purchase_meters) }}</strong></label>
                <label><span>长料单重（kg）</span><strong>{{ editingLineCalculations.long_material_unit_weight_kg }}</strong></label>
                <label><span>单支重量（kg）</span><strong>{{ editingLineCalculations.tube_unit_weight_kg }}</strong></label>
                <label><span>长料总重量（kg）</span><strong>{{ editingLineCalculations.long_material_total_weight_kg }}</strong></label>
              </div>
            </section>
          </template>

          <template v-else-if="editingSection?.title === '五金件'">
            <label v-if="!catalogMode" class="drawer-field"><span>品名</span><strong class="drawer-readonly-value">{{ editingLineDraft.part_name || '—' }}</strong></label>
            <label class="drawer-field"><span>材质</span><strong class="drawer-readonly-value">{{ selectedAttribute('material', editingLineDraft.material) }}</strong></label>
            <label class="drawer-field"><span>颜色</span><strong class="drawer-readonly-value">{{ catalogMode ? selectedAttribute('color', editingLineDraft.hardware_color) : formatHardwareColor(editingLineDraft.hardware_color) }}</strong></label>
            <label class="drawer-field"><span>规格</span><strong class="drawer-readonly-value">{{ selectedSpecification }}</strong></label>
            <label class="drawer-field"><span>单位</span><strong class="drawer-readonly-value">{{ editingLineDraft.unit || '—' }}</strong></label>
            <label class="drawer-field"><span>单个用量</span><ElInput v-model="editingLineDraft.unit_consumption" inputmode="decimal" placeholder="填写" aria-label="单个用量" /></label>
            <label class="drawer-field"><span>单个材料重量（kg）</span><ElInput v-model="editingLineDraft.unit_material_weight_kg" inputmode="decimal" placeholder="填写" aria-label="单个材料重量" /></label>
            <label v-if="!catalogMode || catalogCoatingEnabled" class="drawer-field">
              <span>喷塑颜色</span>
              <ElSelect v-model="editingLineDraft.powder_coating_color" :disabled="catalogMode && !catalogCoatingEnabled" clearable :value-on-clear="''" :loading="tubeOptionsLoading" :placeholder="coatingPlaceholder" no-data-text="暂无喷塑颜色，请到分区的维护配置新增" aria-label="喷塑颜色">
                <ElOption v-for="item in coatingOptions" :key="item.id" :label="item.color_name" :value="item.color_name" />
              </ElSelect>
            </label>
            <label class="drawer-field"><span>喷塑单个面积（㎡）</span><ElInput v-model="editingLineDraft.powder_coating_unit_area_sqm" inputmode="decimal" placeholder="填写" aria-label="喷塑单个面积" /></label>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="4" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>

          <template v-else-if="editingSection?.title === '塑料件类'">
            <label v-if="!catalogMode" class="drawer-field"><span>品名</span><strong class="drawer-readonly-value">{{ editingLineDraft.part_name || '—' }}</strong></label>
            <label class="drawer-field"><span>材质</span><strong class="drawer-readonly-value">{{ selectedAttribute('material', editingLineDraft.material) }}</strong></label>
            <label class="drawer-field"><span>颜色</span><strong class="drawer-readonly-value">{{ catalogMode ? selectedAttribute('color', editingLineDraft.plastic_color) : formatHardwareColor(editingLineDraft.plastic_color) }}</strong></label>
            <label class="drawer-field"><span>规格</span><strong class="drawer-readonly-value">{{ selectedSpecification }}</strong></label>
            <label class="drawer-field"><span>单位</span><strong class="drawer-readonly-value">{{ editingLineDraft.unit || '—' }}</strong></label>
            <label class="drawer-field"><span>单个用量</span><ElInput v-model="editingLineDraft.unit_consumption" inputmode="decimal" placeholder="填写" aria-label="单个用量" /></label>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="4" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>

          <template v-else-if="editingSection?.title === '辅料类'">
            <label v-if="!catalogMode" class="drawer-field"><span>品名</span><strong class="drawer-readonly-value">{{ editingLineDraft.part_name || '—' }}</strong></label>
            <label v-if="!catalogMode && auxiliaryLineHasActiveProduct(editingLineDraft)" class="drawer-field">
              <span>*规格</span>
              <ElSelect v-model="editingLineDraft.source_accessory_specification_id" filterable placeholder="选择规格" aria-label="辅料规格" @change="setAuxiliarySpecification(editingLineDraft, $event)"><ElOption v-for="item in auxiliarySpecificationOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect>
            </label>
            <label v-else class="drawer-field"><span>*规格</span><strong class="drawer-readonly-value">{{ selectedSpecification }}</strong></label>
            <label v-if="!catalogMode && auxiliaryLineHasActiveProduct(editingLineDraft)" class="drawer-field">
              <span>*颜色</span>
              <ElSelect v-model="editingLineDraft.source_accessory_color_id" filterable placeholder="选择颜色" aria-label="辅料颜色" @change="setAuxiliaryColor(editingLineDraft, $event)"><ElOption v-for="item in auxiliaryColorOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect>
            </label>
            <label v-else class="drawer-field"><span>*颜色</span><strong class="drawer-readonly-value">{{ selectedAttribute('color', editingLineDraft.accessory_color) }}</strong></label>
            <label v-if="!catalogMode && auxiliaryLineHasActiveProduct(editingLineDraft)" class="drawer-field">
              <span>*材质</span>
              <ElSelect v-model="editingLineDraft.source_accessory_material_id" filterable placeholder="选择材质" aria-label="辅料材质" @change="setAuxiliaryMaterial(editingLineDraft, $event)"><ElOption v-for="item in auxiliaryMaterialOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect>
            </label>
            <label v-else class="drawer-field"><span>*材质</span><strong class="drawer-readonly-value">{{ selectedAttribute('material', editingLineDraft.material) }}</strong></label>
            <label class="drawer-field"><span>单位</span><strong class="drawer-readonly-value">{{ editingLineDraft.unit || '待维护' }}</strong></label>
            <label class="drawer-field"><span>单个用量</span><ElInput v-model="editingLineDraft.unit_consumption" inputmode="decimal" placeholder="填写" aria-label="单个用量" /></label>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="4" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>

          <template v-else-if="editingSection?.title === '面料类'">
            <label class="drawer-field"><span>规格</span><strong v-if="catalogMode" class="drawer-readonly-value">{{ selectedSpecification }}</strong><ElSelect v-else v-model="editingLineDraft.source_fabric_specification_id" filterable clearable :value-on-clear="null" :placeholder="editingLineDraft.specification || '选择规格'" aria-label="面料规格" @change="setFabricSpecification(editingLineDraft, $event)"><ElOption v-for="item in fabricSpecificationOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></label>
            <label class="drawer-field"><span>材质</span><strong v-if="catalogMode" class="drawer-readonly-value">{{ selectedAttribute('material', editingLineDraft.material) }}</strong><ElSelect v-else v-model="editingLineDraft.source_fabric_material_id" filterable clearable :value-on-clear="null" :placeholder="editingLineDraft.material || '选择材质'" aria-label="面料材质" @change="setFabricMaterial(editingLineDraft, $event)"><ElOption v-for="item in fabricMaterialOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></label>
            <label v-if="!catalogMode" class="drawer-field drawer-field--wide"><span>色卡</span><ElSelect v-model="editingLineDraft.source_product_color_id" filterable clearable :value-on-clear="null" :placeholder="fabricColorSnapshot(editingLineDraft) || '选择色卡 / 颜色 / 色号'" aria-label="面料色卡颜色色号" @change="setFabricColor(editingLineDraft, $event)"><ElOption v-for="item in fabricColorOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></label>
            <label v-if="catalogMode" class="drawer-field"><span>色卡</span><strong class="drawer-readonly-value">{{ (selectedColor?.color_card ?? editingLineDraft.fabric_color_card) || '—' }}</strong></label>
            <label class="drawer-field"><span>色号</span><strong class="drawer-readonly-value">{{ (catalogMode ? selectedColor?.color_code ?? editingLineDraft.fabric_color_code : editingLineDraft.fabric_color_code) || '—' }}</strong></label>
            <label class="drawer-field"><span>颜色</span><strong class="drawer-readonly-value">{{ selectedAttribute('color', editingLineDraft.fabric_color_name) }}</strong></label>
            <label class="drawer-field"><span>门幅</span><strong v-if="catalogMode" class="drawer-readonly-value">{{ selectedAttribute('width', editingLineDraft.fabric_width) }}</strong><ElSelect v-else v-model="editingLineDraft.source_fabric_width_id" filterable clearable :value-on-clear="null" :placeholder="editingLineDraft.fabric_width || '选择门幅'" aria-label="面料门幅" @change="setFabricWidth(editingLineDraft, $event)"><ElOption v-for="item in fabricWidthOptions(editingLineDraft)" :key="item.id" :label="item.label" :value="item.id" :disabled="item.disabled" /></ElSelect></label>
            <label class="drawer-field"><span>单耗</span><ElInput v-model="editingLineDraft.unit_consumption" inputmode="decimal" placeholder="填写" aria-label="单耗" /></label>
            <label v-if="!catalogMode" class="drawer-field"><span>裁片</span><ElInput v-model="editingLineDraft.part_name" maxlength="300" placeholder="填写裁片" aria-label="裁片" /></label>
            <label class="drawer-field"><span>单位</span><strong class="drawer-readonly-value">{{ editingLineDraft.unit || '米' }}</strong></label>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="4" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>

          <template v-else-if="editingSection?.title === '包材类'">
            <label v-if="!catalogMode" class="drawer-field"><span>品名</span><strong class="drawer-readonly-value">{{ editingLineDraft.part_name || '—' }}</strong></label>
            <label class="drawer-field"><span>材质</span><strong class="drawer-readonly-value">{{ selectedAttribute('material', editingLineDraft.material) }}</strong></label>
            <label class="drawer-field"><span>颜色</span><strong class="drawer-readonly-value">{{ catalogMode ? selectedAttribute('color', editingLineDraft.packaging_color) : formatHardwareColor(editingLineDraft.packaging_color) }}</strong></label>
            <label class="drawer-field"><span>规格</span><strong class="drawer-readonly-value">{{ selectedSpecification }}</strong></label>
            <label class="drawer-field"><span>单位</span><strong class="drawer-readonly-value">{{ editingLineDraft.unit || '—' }}</strong></label>
            <label class="drawer-field"><span>*用量（多少成品用一份）</span><ElInput v-model="editingLineDraft.units_per_box" inputmode="numeric" placeholder="填写正整数" aria-label="用量（多少成品用一份）" /></label>
            <label class="drawer-field"><span>需求数量</span><strong class="drawer-readonly-value">{{ packagingQuantity(editingLineDraft.units_per_box, bom?.order_quantity) || '待填写' }}</strong></label>
          </template>

          <template v-else-if="editingSection?.title === '裁剪明细'">
            <label class="drawer-field"><span>裁片量（片/套）</span><template v-if="legacyPipeCuttingValues(editingLineDraft)"><strong class="drawer-readonly-value cutting-legacy-value">{{ legacyPipeCuttingValues(editingLineDraft)?.pieces }}</strong></template><ElTooltip v-else content="请填写裁片量（片/套）。" :disabled="Boolean(String(editingLineDraft.cutting_pieces_per_set ?? '').trim())" :trigger="['hover', 'focus']" placement="top-start" effect="light" popper-class="cutting-name-error-tooltip"><ElInput v-model="editingLineDraft.cutting_pieces_per_set" inputmode="numeric" placeholder="每套有多少片" aria-label="裁片量（片/套）" /></ElTooltip></label>
            <label class="drawer-field"><span>每成品套数（套/成品）</span><template v-if="legacyPipeCuttingValues(editingLineDraft)"><strong class="drawer-readonly-value cutting-legacy-value">{{ legacyPipeCuttingValues(editingLineDraft)?.sets }}</strong></template><ElTooltip v-else content="请填写每成品套数（套/成品）。" :disabled="Boolean(String(editingLineDraft.cutting_sets_per_product ?? '').trim())" :trigger="['hover', 'focus']" placement="top-start" effect="light" popper-class="cutting-name-error-tooltip"><ElInput v-model="editingLineDraft.cutting_sets_per_product" inputmode="numeric" placeholder="每个成品需要多少套" aria-label="每成品套数（套/成品）" /></ElTooltip></label>
            <label v-if="!catalogMode" class="drawer-field"><span>裁剪名称</span><strong class="drawer-readonly-value">{{ editingLineDraft.part_name || '—' }}</strong></label>
            <label class="drawer-field"><span>{{ isPipeCuttingLine(editingLineDraft) ? '*规格' : '面料规格' }}</span><ElInput v-if="!catalogMode && isPipeCuttingLine(editingLineDraft)" v-model="editingLineDraft.specification" maxlength="500" placeholder="填写实际尺寸或明确型号" aria-label="规格" aria-required="true" /><strong v-else class="drawer-readonly-value">{{ editingLineDraft.specification || '待选择来源面料' }}</strong></label>
            <ElAlert v-if="editingCuttingCalculation?.error && editingCuttingCalculation.mode !== 'incomplete'" data-testid="cutting-calculation-error" class="drawer-field--wide" type="warning" :closable="false" show-icon :title="editingCuttingCalculation.error" />
            <div class="cutting-order-calculations drawer-field--wide">
              <label class="drawer-field"><span>订单裁剪套数</span><strong data-testid="cutting-order-sets">{{ editingCuttingCalculation?.orderSets ? `${editingCuttingCalculation.orderSets} 套` : '待补充' }}</strong><small>BOM 订单 {{ number(bom?.order_quantity) }} × 每成品套数</small></label>
              <label class="drawer-field"><span>订单裁剪片数</span><strong data-testid="cutting-order-pieces">{{ editingCuttingCalculation?.orderPieces ? `${editingCuttingCalculation.orderPieces} 片` : '待补充' }}</strong><small>订单套数 × 裁片量</small></label>
            </div>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="3" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>

          <template v-else>
            <label class="drawer-field"><span>材质</span><strong v-if="catalogMode" class="drawer-readonly-value">{{ selectedAttribute('material', editingLineDraft.material) }}</strong><ElInput v-else v-model="editingLineDraft.material" aria-label="材质" /></label>
            <label v-if="!catalogMode" class="drawer-field"><span>配件 / 裁片名称</span><ElInput v-model="editingLineDraft.part_name" aria-label="配件或裁片名称" /></label>
            <label v-if="editingSection?.section_type !== 'FABRIC'" class="drawer-field"><span>规格 / 厚度</span><strong v-if="catalogMode" class="drawer-readonly-value">{{ selectedSpecification }}</strong><ElInput v-else v-model="editingLineDraft.specification" aria-label="规格或厚度" /></label>
            <label v-if="editingSection?.section_type === 'FABRIC'" class="drawer-field"><span>原材料</span><ElInput v-model="editingLineDraft.raw_material" aria-label="原材料" /></label>
            <label v-if="editingSection?.section_type === 'FABRIC'" class="drawer-field"><span>裁片量</span><ElInput v-model="editingLineDraft.cut_piece_quantity" aria-label="裁片量" /></label>
            <label class="drawer-field"><span>单耗</span><ElInput v-model="editingLineDraft.unit_consumption" aria-label="单耗" /></label>
            <label class="drawer-field"><span>当前需求</span><ElInput v-model="editingLineDraft.total_consumption" aria-label="当前需求" /></label>
            <label class="drawer-field"><span>单位</span><strong v-if="catalogMode" class="drawer-readonly-value">{{ editingLineDraft.unit || '待选择' }}</strong><ElInput v-else v-model="editingLineDraft.unit" aria-label="单位" /></label>
            <label class="drawer-field drawer-field--wide"><span>备注</span><ElInput v-model="editingLineDraft.notes" type="textarea" :rows="4" maxlength="500" show-word-limit aria-label="备注" /></label>
          </template>
          <section v-if="editingSection?.section_type !== 'PROFILE'" class="drawer-image-action drawer-field--wide">
            <div><strong>用料图片</strong><span>{{ displayLineImages(editingLineDraft).length }} / 20</span></div>
            <ElButton size="small" plain type="primary" @click="openLineImageManager()">
              {{ displayLineImages(editingLineDraft).length ? '管理图片' : '上传图片' }}
            </ElButton>
          </section>
          </div>
        </div>

</template>
<style scoped lang="scss">
.line-drawer-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 16px; }
.drawer-field { display: block; min-width: 0; }
.drawer-field > span { display: block; margin-bottom: 7px; color: var(--erp-color-text-secondary); font-size: 13px; }
.drawer-readonly-value { display: flex; min-height: 32px; align-items: center; padding: 7px 10px; box-sizing: border-box; border: 1px solid var(--erp-input-border); border-radius: 6px; background: var(--erp-input-readonly-background); color: var(--erp-input-readonly-text); font-size: 13px; font-weight: 500; }
.drawer-field--wide, .drawer-calculations { grid-column: 1 / -1; }
.pipe-quantity-row { display: contents; }
.pipe-quantity-row > .drawer-field:first-child { grid-column-start: 1; }
.drawer-calculations { padding-top: 2px; }
.cutting-order-calculations { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; padding: 12px; border: 1px solid var(--erp-color-border); border-radius: 5px; background: var(--erp-color-subtle); }
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
.cutting-legacy-value { display: flex; min-height: 32px; align-items: center; padding: 0 7px; box-sizing: border-box; border: 1px solid var(--erp-input-border); border-radius: 5px; background: var(--erp-input-readonly-background); color: var(--erp-input-readonly-text); font-variant-numeric: tabular-nums; }
</style>
