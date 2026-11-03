<script setup lang="ts">
import { computed } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import MaterialCatalogSelect from './MaterialCatalogSelect.vue'
import ProductCatalogOptionsInput from './ProductCatalogOptionsInput.vue'
import { productCatalogFields, type ProductCatalogDraftRow, type ProductCatalogFields } from '@/types/productCatalog'

const props = defineProps<{ product: ProductCatalogDraftRow; canChange: boolean; disabled?: boolean; units: string[]; scales: string[] }>()
const emit = defineEmits<{ update: [product: ProductCatalogDraftRow]; remove: [] }>()
const optionFields = [{ key: 'colors', label: '颜色', maxLength: 200 }, { key: 'materials', label: '材质', maxLength: 200 }, { key: 'thicknesses', label: '壁厚', maxLength: 80 }] as const
const unitOptions = computed(() => {
  const options = [...new Set(props.units)].filter(Boolean).map(value => ({ value, label: value, disabled: false }))
  if (props.product.unit && !options.some(option => option.value === props.product.unit)) {
    options.unshift({ value: props.product.unit, label: props.product.unit, disabled: true })
  }
  return options
})
const scaleOptions = computed(() => [...new Set(['', '常规', '定制', ...props.scales, props.product.scale])].map(value => ({ value, label: value || '未填写' })))
function updateField(key: keyof ProductCatalogFields, value: string) {
  if (props.canChange && !props.disabled) emit('update', { ...props.product, [key]: value })
}
function inputField(key: keyof ProductCatalogFields, event: Event) {
  if (event.target instanceof HTMLInputElement) updateField(key, event.target.value)
}
function updateOptions(key: 'colors' | 'materials' | 'thicknesses', values: string[]) {
  if (props.canChange && !props.disabled) emit('update', { ...props.product, [key]: values })
}
</script>

<template>
  <tr class="product-catalog-row" :class="{ 'new-product-row': !product.id }" :data-product-id="product.id" :data-draft-key="product.key" :data-new-product="!product.id ? '' : undefined">
    <td v-for="field in productCatalogFields" :key="field.key" :data-field="field.key">
      <span v-if="!canChange">{{ product[field.key] || (field.key === 'unit' ? '无单位' : '—') }}</span>
      <MaterialCatalogSelect v-else-if="field.key === 'unit' || field.key === 'scale'" :model-value="product[field.key]" :ariaLabel="field.label" :options="field.key === 'unit' ? unitOptions : scaleOptions" :placeholder="field.key === 'unit' ? '请选择单位' : '未填写'" :disabled="disabled" @update:model-value="updateField(field.key, $event)" />
      <input v-else class="erp-list-control" :value="product[field.key]" :aria-label="field.label" :maxlength="field.maxLength" :placeholder="field.label" :disabled="disabled" @input="inputField(field.key, $event)" @keydown.enter.prevent />
    </td>
    <td v-for="field in optionFields" :key="field.key" :data-field="field.key">
      <ProductCatalogOptionsInput :model-value="product[field.key]" :label="field.label" :max-length="field.maxLength" :readonly="!canChange" :disabled="disabled" @update:model-value="updateOptions(field.key, $event)" />
    </td>
    <td class="product-actions">
      <button v-if="canChange" class="erp-list-button erp-button-motion product-delete" type="button" aria-label="删除产品" title="删除产品" :disabled="disabled" @click="emit('remove')"><Delete aria-hidden="true" /></button>
    </td>
  </tr>
</template>

<style scoped>
td > input { width: 100%; min-width: 0; }
.new-product-row td { background: var(--erp-table-selected); }
.product-actions { width: 36px; }
.product-delete { width: 28px; height: 28px; min-height: 0; padding: 0; opacity: 0; pointer-events: none; }
.product-catalog-row:hover .product-delete, .product-catalog-row:focus-within .product-delete, .product-delete:focus-visible { opacity: 1; pointer-events: auto; }
svg { width: 14px; height: 14px; }
@media (hover: none) { .product-delete { opacity: 1; pointer-events: auto; } }
</style>
