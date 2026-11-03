<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElButton, ElOption, ElSelect } from 'element-plus'
import { fetchProductCatalogSelectionOptions, productCatalogError } from '@/api/productCatalog'
import type { ProductCatalogSelectionOption, ProductCatalogSelectionOptions, ProductEntryDraft, ProductEntryField, ProductSelectionInput, ProductSelectionSnapshot } from '@/types/productCatalog'
import { copyProductEntry, emptyProductEntry, productEntryFromSnapshot } from '@/utils/productEntryDraft'

const props = defineProps<{
  catalogId: string | null
  snapshot?: ProductSelectionSnapshot | null
  selection?: ProductSelectionInput | null
  initialDraft?: Partial<ProductEntryDraft>
  units?: { id: string; unit_name: string; unit_code: string }[]
  showIdentifiers?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ selected: [value: { product: ProductCatalogSelectionOption; selection: ProductSelectionInput }]; clear: [] }>()
const options = ref<ProductCatalogSelectionOptions>()
const entry = ref<ProductEntryDraft>(emptyProductEntry())
const selectedId = ref<string | null>(props.catalogId)
const pending = ref<Partial<Record<ProductEntryField, string>>>({})
const loading = ref(false), error = ref('')
let request = 0
const fields: { key: ProductEntryField; label: string }[] = [
  { key: 'category_name', label: '类别' }, { key: 'name', label: '品名' },
  { key: 'item_number', label: '货号' }, { key: 'specification', label: '规格' },
  { key: 'product_code', label: '产品编码' }, { key: 'unit_name', label: '单位' },
  { key: 'color_name', label: '颜色' }, { key: 'material', label: '材质' },
]
const visibleFields = computed(() => fields.filter(field => props.showIdentifiers || !['item_number', 'product_code'].includes(field.key)))
const product = computed(() => options.value?.products.find(item => item.id === selectedId.value))
const names = computed(() => options.value?.names.filter(item => item.category_id === entry.value.category_id) ?? [])
const products = computed(() => options.value?.products.filter(item => item.name_id === entry.value.name_id) ?? [])
const unitOptions = computed(() => options.value?.units ?? props.units ?? [])
const readonly = computed(() => !!props.disabled)
type Option = { value: string; label: string }
function textOptions(values: string[]): Option[] { return [...new Set(values.filter(Boolean))].map(value => ({ value, label: value })) }
function fieldOptions(field: ProductEntryField): Option[] {
  if (field === 'category_name') return options.value?.categories.map(item => ({ value: item.id, label: item.name })) ?? []
  if (field === 'name') return names.value.map(item => ({ value: item.id, label: item.name }))
  if (field === 'item_number') return textOptions(products.value.map(item => item.item_number))
  if (field === 'specification') return textOptions(products.value.filter(item => !props.showIdentifiers || !entry.value.item_number || item.item_number === entry.value.item_number).map(item => item.specification))
  if (field === 'product_code') return textOptions(products.value.filter(item => (!entry.value.item_number || item.item_number === entry.value.item_number) && (!entry.value.specification || item.specification === entry.value.specification)).map(item => item.product_code))
  if (field === 'unit_name') return unitOptions.value.map(item => ({ value: item.id, label: item.unit_name }))
  if (field === 'color_name') return product.value?.colors.map(item => ({ value: item.id, label: item.value })) ?? []
  return textOptions(product.value?.materials ?? [])
}
function fieldValue(field: ProductEntryField) {
  const ids = { category_name: entry.value.category_id, name: entry.value.name_id, unit_name: entry.value.unit_id, color_name: entry.value.color_id }
  return field in ids ? ids[field as keyof typeof ids] || entry.value[field] : entry.value[field]
}
function hydrate() {
  selectedId.value = props.catalogId || null
  if (props.selection?.draft) entry.value = copyProductEntry(props.selection.draft)
  else if (props.snapshot) entry.value = productEntryFromSnapshot(props.snapshot)
  else entry.value = { ...emptyProductEntry(), ...props.initialDraft, sources: { ...emptyProductEntry().sources, ...props.initialDraft?.sources } }
  // 已保存的值以单据快照为准，加载当前候选不重写历史内容。
  if (props.selection && !props.selection.draft && product.value) bindProduct(product.value, false)
}
watch([() => props.catalogId, () => props.selection, () => props.snapshot, () => JSON.stringify(props.initialDraft)], hydrate, { immediate: true, deep: true })
async function load() {
  const current = ++request
  loading.value = true; error.value = ''
  try {
    const result = await fetchProductCatalogSelectionOptions()
    if (current !== request) return
    options.value = result
    if (!props.selection?.draft && !props.snapshot && product.value) bindProduct(product.value, false)
  } catch (failure) { if (current === request) error.value = productCatalogError(failure) }
  finally { if (current === request) loading.value = false }
}
function releaseProduct() {
  selectedId.value = null
  entry.value.color_id = null
  // 前序改了品名或规格后，不能把旧产品的隐藏编号带给新的未确认产品。
  if (!props.showIdentifiers) {
    entry.value.item_number = ''
    entry.value.product_code = ''
  }
  for (const key of ['item_number', 'specification', 'product_code', 'color_name', 'material'] as const) entry.value.sources[key] = 'typed'
}
function bindProduct(record: ProductCatalogSelectionOption, resetAttributes = true) {
  selectedId.value = record.id
  Object.assign(entry.value, { category_id: record.category_id, category_name: record.category_name, name_id: record.name_id, name: record.name,
    item_number: record.item_number, specification: record.specification, product_code: record.product_code,
    unit_id: record.unit_id, unit_name: record.unit })
  for (const key of ['category_name', 'name', 'item_number', 'specification', 'product_code'] as const) entry.value.sources[key] = 'selected'
  entry.value.sources.unit_name = record.unit_id ? 'selected' : 'typed'
  if (resetAttributes) {
    const color = record.colors.length === 1 ? record.colors[0] : undefined
    entry.value.color_id = color?.id || null; entry.value.color_name = color?.value || ''
    entry.value.material = record.materials?.length === 1 ? record.materials[0]! : ''
    entry.value.sources.color_name = color ? 'selected' : 'typed'
    entry.value.sources.material = entry.value.material ? 'selected' : 'typed'
  } else if (props.selection && !props.selection.draft) {
    const color = record.colors.find(item => item.id === props.selection?.color_id)
    entry.value.color_id = color?.id || null; entry.value.color_name = color?.value || ''
    entry.value.material = props.selection.material || ''
    entry.value.sources.color_name = color ? 'selected' : 'typed'
    entry.value.sources.material = entry.value.material ? 'selected' : 'typed'
  }
}
function publish() {
  const values = copyProductEntry(entry.value)
  const record = product.value
  const unit = unitOptions.value.find(item => item.id === values.unit_id)
  // 临时展示对象只承载文字；没有对应主档时 ID 留空，由后端草稿路径保存。
  const display: ProductCatalogSelectionOption = {
    id: selectedId.value || '', name_id: values.name_id || '', name: values.name, category_id: values.category_id || '', category_name: values.category_name,
    product_code: values.product_code, item_number: values.item_number, specification: values.specification,
    unit: values.unit_name, unit_id: values.unit_id, unit_code: unit?.unit_code || (values.unit_id && props.snapshot?.unit_id === values.unit_id ? props.snapshot.unit_code : ''),
    scale: record?.scale || props.snapshot?.scale || '', colors: record?.colors || [], materials: record?.materials || [], thicknesses: record?.thicknesses || [],
    catalog_version: record?.catalog_version || props.snapshot?.catalog_version || '', updated_at: record?.updated_at || '',
  }
  const selection: ProductSelectionInput = { draft: values, ...(selectedId.value ? { catalog_version: display.catalog_version } : {}),
    ...(props.selection?.thickness || props.snapshot?.thickness ? { thickness: props.selection?.thickness || props.snapshot?.thickness } : {}) }
  emit('selected', { product: display, selection })
}
function setField(field: ProductEntryField, raw: string, forceTyped = false) {
  if (readonly.value) return
  delete pending.value[field]
  const option = forceTyped ? undefined : fieldOptions(field).find(item => item.value === raw)
  const value = option?.label || raw || ''
  const previous = entry.value[field]
  entry.value[field] = value
  entry.value.sources[field] = option ? 'selected' : 'typed'
  if (field === 'category_name') {
    const previousId = entry.value.category_id
    entry.value.category_id = option?.value || null
    if (previousId !== entry.value.category_id || previous !== value) {
      entry.value.name_id = null; entry.value.sources.name = 'typed'; releaseProduct()
    }
  } else if (field === 'name') {
    const previousId = entry.value.name_id
    entry.value.name_id = option?.value || null
    if (previousId !== entry.value.name_id || previous !== value) releaseProduct()
  } else if (field === 'unit_name') entry.value.unit_id = option?.value || null
  else if (field === 'color_name') entry.value.color_id = option?.value || null
  else if (['item_number', 'specification', 'product_code'].includes(field)) {
    if (!option) releaseProduct()
    else {
      const matches = products.value.filter(item => field === 'product_code' ? item.product_code === value
        : field === 'item_number' ? item.item_number === value
        : item.specification === value && (!props.showIdentifiers || !entry.value.item_number || item.item_number === entry.value.item_number))
      if (matches.length === 1) bindProduct(matches[0]!, selectedId.value !== matches[0]!.id)
      else releaseProduct()
    }
  }
  publish()
}
function rememberInput(field: ProductEntryField, event: Event) {
  if (readonly.value || !(event.target instanceof HTMLInputElement)) return
  pending.value[field] = event.target.value
}
function commitPending(field: ProductEntryField) {
  const value = pending.value[field]
  if (value === undefined) return
  delete pending.value[field]
  if (value.trim()) setField(field, value.trim(), true)
}
function commit() { for (const { key } of visibleFields.value) commitPending(key) }
function validate(validation: { final?: boolean; preserveInitial?: boolean } = {}) {
  if (readonly.value) return ''
  commit()
  if (!entry.value.category_name.trim()) return '请选择或填写产品类别。'
  if (!entry.value.name.trim()) return '请选择或填写产品名称。'
  if (!selectedId.value && !entry.value.specification.trim()) return '请选择或填写产品规格。'
  if (!entry.value.unit_name.trim()) return '请选择或填写单位。'
  if (validation.final && !selectedId.value && !entry.value.item_number.trim()) return '请填写货号。'
  if (validation.final && !selectedId.value && !entry.value.product_code.trim()) return '请填写产品编码。'
  if (!validation.preserveInitial && !props.selection?.draft && !props.snapshot?.catalog_id) publish()
  return ''
}
onMounted(load)
onBeforeUnmount(() => { ++request })
defineExpose({ validate, commit })
</script>

<template>
  <div class="product-catalog-selection" :aria-busy="loading">
    <div class="selection-fields">
      <label v-for="field in visibleFields" :key="field.key">
        <span>{{ field.label }}</span>
        <ElSelect :model-value="fieldValue(field.key)" :aria-label="'产品库' + field.label" filterable allow-create clearable :disabled="readonly"
          :placeholder="'选择或输入' + field.label"
          @change="setField(field.key, $event || '')" @input.capture="rememberInput(field.key, $event)" @blur="commitPending(field.key)">
          <template #label>{{ entry[field.key] }}</template>
          <ElOption v-if="fieldValue(field.key) && !fieldOptions(field.key).some(item => item.value === fieldValue(field.key))" :value="fieldValue(field.key)" :label="entry[field.key]" />
          <ElOption v-for="item in fieldOptions(field.key)" :key="item.value" :value="item.value" :label="item.label" />
        </ElSelect>
      </label>
    </div>
    <p v-if="loading" class="selection-message" role="status">读取产品选项中…</p>
    <p v-else-if="error" class="selection-error" role="alert">{{ error }} <ElButton text :disabled="disabled" @click="load">重新读取</ElButton></p>
  </div>
</template>

<style scoped>
.selection-fields { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
label { display: block; min-width: 0; }
label > span { display: block; margin-bottom: 6px; font-size: 13px; }
.selection-fields :deep(.el-select) { width: 100%; }
.selection-message { color: var(--erp-color-text-secondary); font-size: 12px; }
.selection-error { color: var(--erp-color-danger); font-size: 12px; }
@media (max-width: 700px) { .selection-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
