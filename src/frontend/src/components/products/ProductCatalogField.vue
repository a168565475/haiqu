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
      <input v-else ref="input" v-model="draft" :aria-label="label" :maxlength="maxLength" :aria-invalid="!!error" :disabled="loading || disabled || readonly" />
      <ProductCatalogSaveButton class="field-save" type="submit" data-action="save" label="保存" :ariaLabel="`保存${label}`" :loading="loading" :disabled="disabled || readonly" />
      <button class="field-icon" type="button" :aria-label="`取消编辑${label}`" :title="`取消编辑${label}`" :disabled="loading" @click="cancel"><Close aria-hidden="true" /></button>
    </form>
    <div v-else class="product-field-display">
      <span class="field-value" :class="{ empty: !value }">{{ value || emptyText }}</span>
      <button v-if="!readonly" class="field-icon field-edit" type="button" data-action="edit" :aria-label="`编辑${label}`" :title="`编辑${label}`" :disabled="disabled" @click="start"><EditPen aria-hidden="true" /></button>
    </div>
    <ProductCatalogError v-if="error" :message="error" />
  </div>
</template>

<style scoped lang="scss">
.product-field { position: relative; min-width: 0; }
.product-field-display, .product-field-editor { display: flex; align-items: center; gap: 6px; min-height: 32px; }
.field-value { flex: 1; min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.empty { color: #968f84; }
button, input { font: inherit; }
button { flex-shrink: 0; height: 32px; border: 1px solid #ddd6c9; border-radius: 5px; cursor: pointer; }
input { box-sizing: border-box; width: 100%; min-width: 0; height: 32px; padding: 0 10px; border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7; color: #1f1d18; }
input:focus { border-color: #3898ec; }
input[aria-invalid='true'] { border-color: #b53333; }
.product-field-editor > .material-catalog-select { flex: 1; min-width: 80px; }
.field-icon { display: inline-flex; align-items: center; justify-content: center; width: 32px; padding: 0; border-color: transparent; background: transparent; color: #6f6a61; }
.field-icon:hover:not(:disabled) { background: #f0eadf; border-color: #c9c0b2; }
.field-icon:active:not(:disabled) { background: #e8e1d5; border-color: #c9c0b2; }
.field-edit { opacity: 0; }
.product-field-display:hover .field-edit, .product-field-display:focus-within .field-edit { opacity: 1; }
.field-save { min-width: 48px; padding: 0 8px; background: #fcfbf7; color: #c84e28; border-color: #c84e28; }
.field-save:hover:not(:disabled):not([aria-busy='true']) { background: #f0eadf; border-color: #c9c0b2; }
.field-save:active:not(:disabled):not([aria-busy='true']) { background: #e8e1d5; border-color: #c9c0b2; }
svg { width: 16px; height: 16px; }
button:disabled, input:disabled { opacity: 1; cursor: not-allowed; color: #6f6a61; background: #e8e1d5; border-color: #ddd6c9; }
button:focus-visible, input:focus-visible { outline: 2px solid #3898ec; outline-offset: 2px; }
@media (hover: none) { .field-edit { opacity: 1; } }
</style>
