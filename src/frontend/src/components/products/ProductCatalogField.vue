<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue'
import { Close, EditPen } from '@element-plus/icons-vue'
import MaterialCatalogSelect from './MaterialCatalogSelect.vue'
import ProductCatalogError from './ProductCatalogError.vue'
import ProductCatalogSaveButton from './ProductCatalogSaveButton.vue'
import { productCatalogError } from '@/api/productCatalog'

const props = withDefaults(defineProps<{
  value: string
  label: string
  emptyText?: string
  readonly?: boolean
  disabled?: boolean
  options?: { value: string; label: string }[]
  maxLength?: number
  onStart?: () => Promise<void>
  onSave: (value: string) => Promise<void>
}>(), { emptyText: '—', readonly: false, disabled: false })
const emit = defineEmits<{ editing: [active: boolean] }>()
const editing = ref(false)
const loading = ref(false)
const draft = ref('')
const error = ref('')
const input = ref<HTMLInputElement | InstanceType<typeof MaterialCatalogSelect>>()
async function start() {
  if (loading.value || props.disabled || props.readonly) return
  editing.value = true
  emit('editing', true)
  loading.value = true
  error.value = ''
  draft.value = props.value
  try {
    await props.onStart?.()
    await nextTick()
    draft.value = props.value
  } catch (issue) { error.value = productCatalogError(issue) }
  finally { loading.value = false; await nextTick(); input.value?.focus() }
}
function cancel() { editing.value = false; error.value = ''; emit('editing', false) }
async function save() {
  if (loading.value || props.disabled || props.readonly) return
  loading.value = true
  error.value = ''
  try { await props.onSave(draft.value); cancel() }
  catch (issue) { error.value = productCatalogError(issue) }
  finally { loading.value = false }
}
onBeforeUnmount(() => { if (editing.value) emit('editing', false) })
</script>

<template>
  <div class="product-field">
    <form v-if="editing" class="product-field-editor" @submit.prevent="save">
      <MaterialCatalogSelect v-if="options" ref="input" v-model="draft" :options="options" :ariaLabel="label" placeholder="未填写" :invalid="!!error" :disabled="loading || disabled || readonly" />
      <input class="erp-list-control" v-else ref="input" v-model="draft" :aria-label="label" :maxlength="maxLength" :aria-invalid="!!error" :disabled="loading || disabled || readonly" />
      <ProductCatalogSaveButton class="field-save" type="submit" data-action="save" label="保存" :ariaLabel="`保存${label}`" :loading="loading" :disabled="disabled || readonly" />
      <button class="erp-list-button erp-button-motion field-icon" type="button" :aria-label="`取消编辑${label}`" :title="`取消编辑${label}`" :disabled="loading" @click="cancel"><Close aria-hidden="true" /></button>
    </form>
    <div v-else class="product-field-display">
      <span class="field-value" :class="{ empty: !value }">{{ value || emptyText }}</span>
      <button v-if="!readonly" class="erp-list-button erp-button-motion field-icon field-edit" type="button" data-action="edit" :aria-label="`编辑${label}`" :title="`编辑${label}`" :disabled="disabled" @click="start"><EditPen aria-hidden="true" /></button>
    </div>
    <ProductCatalogError v-if="error" :message="error" />
  </div>
</template>

<style scoped lang="scss">
.product-field { position: relative; min-width: 0; }
.product-field-display, .product-field-editor { display: flex; align-items: center; gap: 6px; min-height: 32px; }
.field-value { flex: 1; min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.empty { color: var(--erp-color-text-secondary); }
button { flex-shrink: 0; }
input { width: 100%; min-width: 0; }
input[aria-invalid='true'] { border-color: var(--erp-color-danger); }
.product-field-editor > .material-catalog-select { flex: 1; min-width: 80px; }
.field-icon { width: 32px; padding: 0; }
.field-edit { opacity: 0; }
.product-field-display:hover .field-edit, .product-field-display:focus-within .field-edit { opacity: 1; }
.field-save { min-width: 48px; padding: 0 8px; }
svg { width: 16px; height: 16px; }
@media (hover: none) { .field-edit { opacity: 1; } }
</style>
