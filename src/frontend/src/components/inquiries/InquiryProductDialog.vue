<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import ProductImage from '@/components/products/ProductImage.vue'
import ProductCatalogSelection from '@/components/productCatalog/ProductCatalogSelection.vue'
import { inquiryProductImageUrl } from '@/api/inquiries'
import type { InquiryItem, InquiryProductSelectionOptions } from '@/types/inquiry'
import type { ProductCatalogSelectionOption, ProductEntryDraft, ProductSelectionInput } from '@/types/productCatalog'
import { emptyProductEntry } from '@/utils/productEntryDraft'
import type { ProductCategoryOption, ProductionUnitOption } from '@/types/product'
import type { ProductColor } from '@/types/productionData'
import { decimalUnits, validateProductImage, validateProducts } from '@/views/inquiries/inquiryEditorState'

type ProductDialogCurrency = { code: string; name?: string; symbol?: string }

const props = withDefaults(defineProps<{
  candidateLoader?: (categoryId: string) => Promise<InquiryProductSelectionOptions>
  embedded?: boolean
  hideEmbeddedFooter?: boolean
  hideSummary?: boolean
  groupIdentityFields?: boolean
  businessTitle?: string
  modelValue: boolean
  item: InquiryItem & { discount_rate?: string | number }
  scene?: 'inquiry' | 'quotation' | 'sales-order' | 'bom'
  contextTitle?: string
  reviewed?: boolean
  saveError?: string
  canCreateProduct?: boolean
  canCreateColor?: boolean
  imageUrl?: string
  quotationCurrency?: string
  closeOnConfirm?: boolean
  busy?: boolean
  identityDisabled?: boolean
  allowDelete?: boolean
  categories: ProductCategoryOption[]
  units: ProductionUnitOption[]
  colors: Pick<ProductColor, 'id' | 'color_name'>[]
  currencies: ProductDialogCurrency[]
  pendingImage?: File | null
  pendingRemoval?: boolean
  canUpload: boolean
  catalogError?: string
  catalogLoading?: boolean
}>(), {
  scene: 'inquiry',
  closeOnConfirm: true,
  allowDelete: false,
})
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [value: { item: InquiryItem; imageChanged: boolean; imageFile: File | null; removeImage: boolean }]
  delete: []
  'create-product': [item: InquiryItem]
  'create-color': [name: string]
  'retry-catalog': []
}>()
const draft = ref<InquiryItem & { discount_rate?: string | number }>({ ...props.item })
const catalogPicker = ref<InstanceType<typeof ProductCatalogSelection>>()
const error = ref('')
const confirmed = ref(false)
const imageInput = ref<HTMLInputElement | null>(null)
const imageFile = ref<File | null>(null), imageChanged = ref(false), removeImage = ref(false)
const preview = ref('')
const bomDraftChanged = computed(() => props.scene === 'bom' && (
  ['product_id', 'product_catalog_id', 'product_category_id', 'product_unit_id', 'product_color_id', 'product_description', 'specification', 'unit_code', 'color', 'material'] as const
).some(field => draft.value[field] !== props.item[field]) || props.scene === 'bom' && JSON.stringify(draft.value.product_selection) !== JSON.stringify(props.item.product_selection))
const requiresBomConfirmation = computed(() => props.scene === 'bom' && (!props.reviewed || bomDraftChanged.value))
const canDismiss = computed(() => !props.busy && !requiresBomConfirmation.value)
function requestVisibility(visible: boolean) {
  if (visible || canDismiss.value) emit('update:modelValue', visible)
}
const imageName = computed(() => imageFile.value?.name || (!removeImage.value ? draft.value.product_image?.original_name : '') || (!removeImage.value && draft.value.product_image_id ? '已有产品图片' : '暂无产品图片'))
const initialEntry = computed<ProductEntryDraft>(() => {
  const item = props.item
  const unit = props.units.find(row => row.id === item.product_unit_id)
  const entry = emptyProductEntry()
  return { ...entry,
    category_name: item.product_category_name || props.categories.find(row => row.id === item.product_category_id)?.category_name || '',
    name: item.product_description, item_number: item.item_number_snapshot || '', specification: item.specification,
    product_code: item.product_code_snapshot || '', unit_id: item.product_unit_id || null,
    unit_name: unit?.unit_name || item.unit_code, color_name: item.color || '', material: item.material || '',
    sources: { ...entry.sources, unit_name: item.product_unit_id ? 'selected' : 'typed' },
  }
})
function chooseCatalogProduct({ product, selection }: { product: ProductCatalogSelectionOption; selection: ProductSelectionInput }) {
  if (props.identityDisabled || props.busy) return
  draft.value = {
    ...draft.value, product_id: null, product_catalog_id: product.id || null, product_selection: { ...selection }, product_selection_snapshot: null,
    product_category_id: null, product_category_name: product.category_name, product_color_id: null,
    product_unit_id: product.unit_id, product_description: product.name, specification: product.specification,
    unit_code: product.unit_code, color: selection.draft?.color_name ?? product.colors.find(color => color.id === selection.color_id)?.value ?? '', material: selection.draft?.material ?? selection.material ?? '',
    product_number_snapshot: '', product_code_snapshot: product.product_code, item_number_snapshot: product.item_number,
    product_match_status: product.id ? 'MATCHED' : 'PENDING',
  }
  error.value = ''
}
defineExpose({ confirm })
function replacePreview(value: string) {
  if (preview.value.startsWith('blob:')) URL.revokeObjectURL(preview.value)
  preview.value = value
}
function selectImage(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const invalid = validateProductImage(file)
  if (invalid) { error.value = invalid; return }
  imageFile.value = file; imageChanged.value = true; removeImage.value = false; error.value = ''
  replacePreview(URL.createObjectURL(file))
}
function clearImage() {
  imageFile.value = null; removeImage.value = true; imageChanged.value = true
  replacePreview('')
}
function adjustQuantity(direction: number) {
  const units = decimalUnits(draft.value.quantity)
  if (units === null) return
  const next = units + BigInt(direction) * 10000n
  if (next <= 0n || next > 999999999999999999n) return
  const text = next.toString().padStart(5, '0')
  draft.value.quantity = `${text.slice(0, -4)}.${text.slice(-4)}`.replace(/\.?0+$/, '')
}
function disabledDate(date: Date) {
  const today = new Date(); today.setHours(0, 0, 0, 0)
  return date.getTime() < today.getTime()
}
function fieldError(field: string) {
  const words: Record<string, string> = { 类别: '类别', 品名: '产品名称', 规格: '规格', 单位: '单位', 数量: '数量', 目标价: '目标价', 币种: '币种', 期望日期: '日期' }
  return error.value.includes(words[field] || field) ? error.value : ''
}
function dismissPickerFirst(event: KeyboardEvent) {
  // Escape 先交给当前下拉/日期浮层，避免同时关闭整张产品表单。
  const pickerOpen = [...document.querySelectorAll<HTMLElement>('.el-select__popper, .el-picker__popper')].some(element => element.offsetParent !== null)
  if (pickerOpen) event.stopPropagation()
}
function confirm() {
  if (confirmed.value || !props.modelValue || props.busy) return
  error.value = catalogPicker.value?.validate({ final: props.scene === 'bom', preserveInitial: props.scene !== 'bom' && !!draft.value.product_id }) || ''
  if (error.value) return
  if (props.scene === 'bom') {
    emit('confirm', { item: { ...draft.value }, imageChanged: false, imageFile: null, removeImage: false })
    return
  }
  error.value = validateProducts([draft.value])
  if (props.scene === 'sales-order') {
    error.value = error.value.replace('目标价', '订单单价')
    if (!error.value && (draft.value.target_unit_price === null || String(draft.value.target_unit_price ?? '').trim() === '')) error.value = '请填写订单单价。'
  }
  const today = new Date(), localDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  if (!error.value && draft.value.expected_date && draft.value.expected_date < localDate && draft.value.expected_date !== props.item.expected_date) error.value = '新录入的期望日期不能早于今天。'
  if (error.value) return
  confirmed.value = true
  emit('confirm', { item: { ...draft.value }, imageChanged: imageChanged.value, imageFile: imageFile.value, removeImage: removeImage.value })
  if (props.closeOnConfirm !== false) emit('update:modelValue', false)
  else confirmed.value = false
}
watch(() => props.modelValue, visible => {
  if (!visible) return
  draft.value = { ...props.item, ...(props.item.product_selection ? { product_selection: { ...props.item.product_selection } } : {}) }
  error.value = ''; confirmed.value = false
  imageChanged.value = false; imageFile.value = props.pendingImage || null; removeImage.value = props.pendingRemoval || false
  replacePreview(props.scene === 'bom' ? '' : imageFile.value ? URL.createObjectURL(imageFile.value) : props.item.id && props.item.product_image_id && !removeImage.value ? `${props.imageUrl || inquiryProductImageUrl(props.item.id)}?v=${props.item.product_image_id}` : '')
}, { immediate: true })
onBeforeUnmount(() => replacePreview(''))
</script>

<template>
  <component :is="embedded ? 'section' : AppWindowDialog" :model-value="modelValue" :title="embedded ? undefined : scene === 'bom' ? '核对产品信息' : scene === 'quotation' ? (item.id || item.product_description ? '编辑报价产品' : '添加报价产品') : scene === 'sales-order' ? (item.id || item.product_description ? '编辑销售订单产品' : '添加销售订单产品') : (item.id || item.product_description ? '编辑询盘产品' : '添加询盘产品')" :width="1160" class="inquiry-product-window" :close-on-click-modal="false" :close-on-press-escape="canDismiss" :show-close="canDismiss" :minimizable="canDismiss" @update:model-value="requestVisibility">
    <div class="product-entry" @keydown.esc="dismissPickerFirst">
      <div v-if="!hideSummary" class="entry-summary"><div><strong>{{ scene === 'bom' ? (contextTitle || '当前 BOM 产品明细') : scene === 'quotation' ? '报价产品明细' : scene === 'sales-order' ? '销售订单产品明细' : '询盘产品明细' }}</strong><p>{{ scene === 'bom' ? '已进入物料编辑页；核对当前产品，保留正在填写的物料' : scene === 'quotation' ? '产品身份沿用共用选择器；报价单价、折扣和备注单独保存' : scene === 'sales-order' ? '产品身份沿用共用选择器；订单数量、单价和交付要求单独保存' : '产品逐项选择或填写；本单数量、价格和日期单独保存' }}</p></div><span class="entry-tag" :class="{ linked: (draft.product_id || draft.product_catalog_id) && !bomDraftChanged }">{{ scene === 'bom' && bomDraftChanged ? '待保存' : scene === 'bom' && reviewed ? '已核对' : draft.product_id || draft.product_catalog_id ? '已关联' : '未关联' }}</span></div>
      <div class="entry-columns">
        <section class="identity-zone" aria-label="产品身份" :inert="identityDisabled || busy ? true : undefined">
          <ProductCatalogSelection ref="catalogPicker" :catalog-id="draft.product_catalog_id || null" :selection="draft.product_selection" :snapshot="draft.product_selection_snapshot" :initial-draft="initialEntry" :units="units" :show-identifiers="scene === 'bom'" :disabled="identityDisabled || busy" @selected="chooseCatalogProduct" />
        </section>
        <aside class="business-zone" :aria-label="businessTitle || (scene === 'bom' ? '本条生产任务与来源' : scene === 'sales-order' ? '本次销售订单内容' : scene === 'quotation' ? '本次报价内容' : '本次询盘要求')">
          <slot v-if="scene === 'bom'" name="business"/>
          <template v-else>
          <h3>{{ businessTitle || (scene === 'quotation' ? '本次报价内容' : scene === 'sales-order' ? '本次销售订单内容' : '本次询盘要求') }}</h3><div class="business-fields">
            <label :data-error="fieldError('数量')"><span><i>*</i> 数量</span><div class="quantity-control"><button type="button" aria-label="减少数量" @click="adjustQuantity(-1)">−</button><el-input v-model="draft.quantity" aria-label="数量" :aria-invalid="!!fieldError('数量')" inputmode="decimal" maxlength="19"/><button type="button" aria-label="增加数量" @click="adjustQuantity(1)">+</button></div></label>
            <template v-if="scene === 'quotation'"><label><span><i>*</i> 报价单价</span><el-input v-model="draft.target_unit_price" aria-label="报价单价" inputmode="decimal" maxlength="19" placeholder="请输入正式报价单价"/></label><label><span>折扣率</span><el-input v-model="draft.discount_rate" aria-label="折扣率" inputmode="decimal" maxlength="8" placeholder="0"/></label><label><span>报价币种</span><el-input :model-value="quotationCurrency || '—'" aria-label="报价币种" disabled/></label></template>
            <template v-else-if="scene === 'sales-order'"><label :data-error="fieldError('订单单价')"><span><i>*</i> 订单单价</span><el-input v-model="draft.target_unit_price" aria-label="订单单价" :aria-invalid="!!fieldError('订单单价')" inputmode="decimal" maxlength="19" placeholder="请输入订单单价"/></label><label><span>订单币种</span><el-input :model-value="quotationCurrency || '—'" aria-label="订单币种" disabled/></label></template>
            <template v-else><label :data-error="fieldError('目标价')"><span>目标价</span><el-input v-model="draft.target_unit_price" aria-label="目标价" :aria-invalid="!!fieldError('目标价')" inputmode="decimal" maxlength="19" placeholder="待填写"/></label><label :data-error="fieldError('币种')"><span>币种</span><el-select v-model="draft.target_currency_code" aria-label="币种" :aria-invalid="!!fieldError('币种')" filterable clearable placeholder="币种"><el-option v-if="draft.target_currency_code && !currencies.some(row => row.code === draft.target_currency_code)" :value="draft.target_currency_code" :label="draft.target_currency_code" disabled/><el-option v-for="currency in currencies" :key="currency.code" :value="currency.code" :label="currency.code"/></el-select></label><label :data-error="fieldError('期望日期')"><span>期望日期</span><el-date-picker v-model="draft.expected_date" aria-label="期望日期" :aria-invalid="!!fieldError('期望日期')" type="date" value-format="YYYY-MM-DD" :disabled-date="disabledDate" placeholder="可选"/></label></template>
          </div>
          <h3 class="image-heading">产品图片 <small>单张主图</small></h3><div class="image-row"><ProductImage :src="preview" :name="imageName" large/><div class="image-note"><strong :title="imageName">{{ imageName }}</strong><p>JPG / JPEG / PNG，最大 10 MB</p><el-button :disabled="!canUpload" @click="imageInput?.click()">{{ preview ? '更换图片' : '选择图片' }}</el-button><el-button v-if="preview" link type="primary" :disabled="!canUpload" @click="clearImage">移除</el-button></div></div><input ref="imageInput" class="image-input" type="file" accept="image/jpeg,image/png" aria-label="上传产品图片" @change="selectImage"/>
          </template>
        </aside>
      </div>
      <p v-if="requiresBomConfirmation" class="bom-confirmation-hint" role="status">请先确认本次产品信息，确认成功后才能关闭窗口。</p>
      <p v-if="saveError" class="entry-error" role="alert">{{ saveError }}</p>
      <p v-if="error" class="entry-error" role="alert">{{ error }}</p>
      <slot name="before-actions" />
      <div v-if="embedded && !hideEmbeddedFooter" class="entry-footer"><small>人民币价格；可继续添加多条产品。</small><el-button type="primary" :loading="busy" @click="confirm">{{ item.product_description ? '保存产品信息' : '添加产品' }}</el-button></div>
    </div>
    <template #footer><div class="entry-footer"><small>{{ scene === 'bom' ? '本次只保存核对内容；最终确认 BOM 后才写入产品管理。' : scene === 'sales-order' ? '切换产品保留订单数量、单价和图片；交付批次与产品要求在订单页维护。' : '切换产品保留数量、价格、日期和图片。' }}</small><div><el-button v-if="allowDelete" type="danger" text :disabled="busy" @click="emit('delete')">删除</el-button><el-button :disabled="!canDismiss" @click="requestVisibility(false)">取消</el-button><el-button type="primary" :loading="busy" @click="confirm">{{ scene === 'bom' ? '保存本次产品核对' : item.id || item.product_description ? '保存产品信息' : scene === 'sales-order' ? '添加到销售订单' : '添加到当前单据' }}</el-button></div></div></template>
  </component>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.product-entry { font-family: token.$crm-font-body; font-size: 13px; color: token.$crm-text-primary; }
.entry-summary { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid token.$crm-border-default; padding-bottom: 12px; strong { font-size: 13px; font-weight: 600; } p { margin: 4px 0 0; color: token.$crm-text-secondary; font-size: 11px; } }
.entry-tag { height: 24px; min-width: 56px; justify-content: center; padding: 0 8px; display: inline-flex; align-items: center; border-radius: 999px; color: token.$crm-text-inverse; background: token.$crm-warning; font-size: 12px; font-weight: 500; &.linked { background: token.$crm-success; } }
.entry-columns { display: grid; grid-template-columns: minmax(0,1fr) minmax(240px,.65fr); gap: 14px; margin-top: 14px; }
.identity-zone { min-width: 0; padding-right: 14px; border-right: 1px solid token.$crm-border-default; }
small { color: token.$crm-text-secondary; font-size: 11px; font-weight: 400; } i { color: token.$crm-danger; font-style: normal; }
.identity-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.identity-fields + .identity-fields { margin-top: 14px; }
label { position: relative; min-width: 0; display: block; > span { display: block; margin-bottom: 8px; font-size: 13px; line-height: 20px; } }
label[data-error]:not([data-error='']) { :deep(.el-input__wrapper), :deep(.el-select__wrapper) { box-shadow: 0 0 0 1px token.$crm-danger inset; } &::after { content: attr(data-error); position: absolute; z-index: 3; left: 0; top: calc(100% + 4px); width: max-content; max-width: 280px; border: 1px solid token.$crm-danger; border-radius: 5px; padding: 8px 12px; color: token.$crm-danger; background: token.$crm-color-surface; box-shadow: 0 6px 16px color-mix(in srgb, var(--erp-shadow-color) 10%, transparent); font-size: 12px; line-height: 18px; } }
.identity-fields label:last-child[data-error]::after, .business-fields label:nth-child(even)[data-error]::after { left: auto; right: 0; }
.product-entry :deep(.el-input__wrapper), .product-entry :deep(.el-select__wrapper) { height: 32px; min-height: 32px; border-radius: 8px; box-sizing: border-box; font-size: 13px; }
.product-entry :deep(.el-input__inner) { height: 30px; font-size: 13px; }
.product-entry :deep(.el-input__wrapper.is-focus), .product-entry :deep(.el-select__wrapper.is-focused) { box-shadow: 0 0 0 1px token.$crm-focus inset; }
.product-entry :deep(.el-select) { width: 100%; }
.product-entry :deep(.el-date-editor) { width: 100%; height: 32px; }
.picked, .manual-note { margin: 12px 0 16px; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.business-zone { min-width: 0; h3 { font-size: 13px; font-weight: 600; margin: 0 0 16px; line-height: 20px; } }
.business-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.quantity-control { display: flex; align-items: stretch; box-sizing: border-box; width: 100%; height: 32px; overflow: hidden; border: 1px solid token.$crm-border-default; border-radius: 8px; background: token.$crm-color-surface; :deep(.el-input) { flex: 1; min-width: 0; height: 30px; } :deep(.el-input:not(.el-textarea) .el-input__wrapper) { box-sizing: border-box; height: 30px !important; min-height: 30px !important; padding: 0 !important; border: 0 !important; border-radius: 0 !important; box-shadow: none !important; background: transparent !important; } :deep(.el-input__inner) { height: 30px; line-height: 30px; text-align: center; } button { width: 32px; height: 30px; flex: 0 0 32px; align-self: center; padding: 0; border: 0; background: transparent; color: token.$crm-text-primary; cursor: pointer; &:focus-visible { outline: 2px solid token.$crm-focus; } } }
.business-zone .image-heading { display: flex; justify-content: space-between; margin: 16px 0 12px; }
.image-row { display: flex; gap: 12px; align-items: center; }
.image-note { min-width: 0; strong { display: block; font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } p { margin: 4px 0 8px; color: token.$crm-text-secondary; font-size: 11px; } :deep(.el-button) { margin: 0; } }
.image-input { display: none; }
.entry-error, .link-note { margin: 16px 0 0; padding: 12px; border: 1px solid token.$crm-danger-border; background: token.$crm-danger-soft; border-radius: 5px; color: token.$crm-danger; font-size: 12px; }
.link-note { color: token.$crm-text-primary; border-color: token.$crm-warning-border; background: token.$crm-warning-soft; }
.bom-confirmation-hint { margin: 16px 0 0; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.entry-error > .el-button { margin-left: 12px; }
.entry-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; > div { display: flex; gap: 8px; } :deep(.el-button) { margin: 0; } }
@media (max-width: 1000px) { .entry-columns { grid-template-columns: 1fr; } .identity-zone { border-right: 0; padding-right: 0; } }
@container (max-width:740px) { .entry-columns { grid-template-columns:minmax(0,1fr); } .identity-zone { border-right:0; padding-right:0; } }
@container (max-width:500px) { .identity-fields { grid-template-columns:minmax(0,1fr); } }
</style>

<style lang="scss">
@use '@/styles/crm/tokens' as token;
// 窗口通过 Teleport 放到 body，外壳样式只限定当前弹窗的类名。
.inquiry-product-window.app-window-dialog {
  .app-window-dialog__body { padding: 16px; }
  .app-window-dialog__footer { padding: 12px 24px; border-top: 1px solid token.$crm-border-default; }
  container-type: inline-size
}
</style>
