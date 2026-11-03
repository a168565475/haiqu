<script setup lang="ts">
import { ref, watch } from 'vue'
import { fetchProductCatalogSelectionOptions, productCatalogError } from '@/api/productCatalog'
import type { ProductEntryDraft, ProductCatalogSelectionOptions } from '@/types/productCatalog'

const props = defineProps<{ modelValue: ProductEntryDraft; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: ProductEntryDraft] }>()
const options = ref<ProductCatalogSelectionOptions | null>(null)
const error = ref('')
const pending: Partial<Record<'category_name' | 'unit_name', string>> = {}
function update(field: 'category_name' | 'name' | 'specification' | 'unit_name' | 'material', value: string) {
  if (props.disabled) return
  const draft = { ...props.modelValue, [field]: value, sources: { ...props.modelValue.sources, [field]: 'typed' as const } }
  if (field === 'category_name') draft.category_id = null
  if (field === 'name') draft.name_id = null
  if (field === 'unit_name') draft.unit_id = null
  if (field === 'name' || field === 'specification') { draft.item_number = ''; draft.product_code = '' }
  emit('update:modelValue', draft)
}
function remember(field: 'category_name' | 'unit_name', event: Event) {
  if (event.target instanceof HTMLInputElement) pending[field] = event.target.value
}
function commit() {
  for (const field of ['category_name', 'unit_name'] as const) {
    const value = pending[field]
    delete pending[field]
    if (value?.trim()) update(field, value.trim())
  }
}
async function loadOptions() {
  error.value = ''
  try { options.value = await fetchProductCatalogSelectionOptions() }
  catch (failure) { error.value = productCatalogError(failure) }
}
watch(() => props.disabled, disabled => { if (!disabled && !options.value) void loadOptions() }, { immediate: true })
defineExpose({ commit })
</script>
<template>
  <div class="sample-product-fields">
    <div v-if="error" role="alert">{{ error }}<ElButton :disabled="disabled" @click="loadOptions">重试选项</ElButton></div>
    <ElFormItem label="类别 *"><ElSelect :model-value="modelValue.category_name" aria-label="类别" :disabled="disabled" filterable allow-create default-first-option placeholder="选择或填写类别" @input.capture="remember('category_name', $event)" @blur="commit" @update:model-value="delete pending.category_name; update('category_name', $event)"><ElOption v-for="item in options?.categories" :key="item.id" :value="item.name" :label="item.name" /></ElSelect></ElFormItem>
    <ElFormItem label="品名 *"><ElInput :model-value="modelValue.name" aria-label="品名" :disabled="disabled" maxlength="200" placeholder="请输入品名" @update:model-value="update('name', $event)" /></ElFormItem>
    <ElFormItem label="规格 *"><ElInput :model-value="modelValue.specification" aria-label="规格" :disabled="disabled" maxlength="300" placeholder="请输入规格" @update:model-value="update('specification', $event)" /></ElFormItem>
    <ElFormItem label="单位"><ElSelect :model-value="modelValue.unit_name" aria-label="单位" :disabled="disabled" filterable allow-create default-first-option placeholder="选择或填写单位" @input.capture="remember('unit_name', $event)" @blur="commit" @update:model-value="delete pending.unit_name; update('unit_name', $event)"><ElOption v-for="item in options?.units" :key="item.id" :value="item.unit_name" :label="item.unit_name" /></ElSelect></ElFormItem>
    <ElFormItem label="材质"><ElInput :model-value="modelValue.material" aria-label="材质" :disabled="disabled" maxlength="200" placeholder="选填" @update:model-value="update('material', $event)" /></ElFormItem>
  </div>
</template>
<style scoped>
.sample-product-fields { display: contents; }
.sample-product-fields > [role='alert'] { grid-column: 1 / -1; }
.sample-product-fields :deep(.el-input), .sample-product-fields :deep(.el-select) { width: 250px; max-width: 100%; }
</style>
