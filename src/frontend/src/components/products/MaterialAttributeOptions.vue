<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { Close, Delete, Loading } from '@element-plus/icons-vue'
import { materialCatalogError } from '@/api/materialCatalog'
import type { MaterialFieldDefinition, MaterialScope } from '@/types/materialCatalog'
import MaterialCatalogSelect from './MaterialCatalogSelect.vue'

const props = defineProps<{
  label: string
  fieldKey: string
  kind: MaterialFieldDefinition['kind']
  scope: MaterialScope
  parentId?: string
  options: { id: string; label: string }[]
  availableUnits: { id: string; unit_name: string }[]
  readonly: boolean
  disabled: boolean
  onSave: (value: string) => Promise<void>
  onRemove: (id: string) => Promise<void>
}>()
const editing = ref(false)
const draft = ref('')
const error = ref('')
const saving = ref(false)
const removing = ref('')
const input = ref<HTMLInputElement | InstanceType<typeof MaterialCatalogSelect>>()
const unitOptions = computed(() => props.availableUnits.map(unit => ({ value: unit.id, label: unit.unit_name })))
async function startAdding() {
  editing.value = true
  error.value = ''
  await nextTick()
  input.value?.focus()
}
async function save() {
  if (saving.value || props.disabled || props.readonly) return
  if (!draft.value.trim()) { error.value = props.kind === 'unit' ? '请选择可用单位。' : '请输入选项内容。'; return }
  error.value = ''
  saving.value = true
  try {
    await props.onSave(draft.value.trim())
    draft.value = ''
    editing.value = false
  } catch (issue) { error.value = materialCatalogError(issue) }
  finally { saving.value = false }
}
async function remove(id: string) {
  if (removing.value || saving.value || props.disabled || props.readonly) return
  error.value = ''
  removing.value = id
  try { await props.onRemove(id) }
  catch (issue) { error.value = materialCatalogError(issue) }
  finally { removing.value = '' }
}
</script>

<template>
  <div class="attribute-row" :data-field="`${scope}:${fieldKey}:${parentId || ''}`">
    <div class="attribute-label"><slot name="label" :remove="remove" :busy="saving || !!removing">{{ label }}</slot></div>
    <div class="attribute-content">
      <div class="option-line">
        <span v-for="option in options" :key="option.id" class="option-chip">
          <span class="option-label">{{ option.label }}</span>
          <button v-if="!readonly" type="button" class="delete-option" data-action="delete" :aria-label="`删除${option.label}`"
            :title="`删除${option.label}`" :disabled="disabled || saving || !!removing" @click="remove(option.id)"><Delete aria-hidden="true" /></button>
        </span>
        <form v-if="editing && !readonly" class="inline-editor" @submit.prevent="save">
          <MaterialCatalogSelect v-if="kind === 'unit'" ref="input" v-model="draft" class="inline-unit-select" :ariaLabel="`添加${label}`"
            :options="unitOptions" placeholder="选择单位" :invalid="!!error" :disabled="disabled || saving" />
          <input v-else ref="input" v-model="draft" :aria-label="`添加${label}`" :placeholder="`输入${label}`" :aria-invalid="!!error" :disabled="disabled || saving" />
          <button type="button" class="save-option" :class="{ processing: saving }" data-action="save" :aria-label="saving ? '正在保存' : '保存'" :aria-busy="saving" :disabled="disabled || saving" @click="save"><span>保存</span><Loading v-if="saving" class="saving-spinner" aria-hidden="true" /></button>
          <button type="button" class="cancel-option" aria-label="取消添加" title="取消添加" :disabled="saving" @click="editing = false; error = ''"><Close aria-hidden="true" /></button>
        </form>
        <button v-else-if="!readonly" type="button" class="add-option" data-action="add" :disabled="disabled || !!removing" @click="startAdding">＋ {{ kind === 'shape' ? '添加形状' : kind === 'dimension' ? '添加尺寸' : '添加' }}</button>
        <span v-if="readonly && !options.length" class="empty-options">—</span>
      </div>
      <span v-if="error" class="field-error" role="alert">{{ error }}</span>
    </div>
  </div>
</template>

<style scoped>
.attribute-row { display: flex; align-items: flex-start; gap: 12px; min-height: 40px; padding: 4px 0; box-sizing: border-box; }
.attribute-label { display: flex; align-items: center; gap: 12px; width: 120px; flex-shrink: 0; min-height: 32px; line-height: 20px; color: #17191c; }
.attribute-label::after { content: ''; flex: 1; min-width: 16px; border-top: 1px dashed #dadce0; }
.attribute-content { flex: 1; min-width: 0; }
.option-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-height: 32px; }
.option-chip { position: relative; display: inline-flex; align-items: center; justify-content: center; min-width: 84px; min-height: 32px; box-sizing: border-box; padding: 3px 28px; border: 1px solid #dadce0; border-radius: 5px; background: #fff; color: #17191c; max-width: 100%; overflow-wrap: anywhere; text-align: center; }
.option-chip:hover, .option-chip:focus-within { background: #f8f5f0; }
button, input { font: inherit; }
button { cursor: pointer; }
button:disabled { cursor: not-allowed; }
.delete-option { position: absolute; right: 0; top: calc(50% - 16px); display: inline-flex; align-items: center; justify-content: center; opacity: 0; pointer-events: none; width: 32px; height: 32px; padding: 0; border: 0; border-radius: 5px; background: transparent; color: #55595e; }
.delete-option svg, .cancel-option svg { width: 16px; height: 16px; }
.option-chip:hover .delete-option, .option-chip:focus-within .delete-option { opacity: 1; pointer-events: auto; }
.delete-option:focus-visible { opacity: 1; pointer-events: auto; }
.add-option { height: 32px; min-width: 84px; border: 1px solid #ece5dc; border-radius: 5px; padding: 0 12px; background: #f8f5f0; color: #17191c; white-space: nowrap; }
.add-option:hover:not(:disabled) { color: #f04b09; border-color: #ff510a; }
.inline-editor { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; }
.inline-editor input { box-sizing: border-box; width: 160px; min-width: 0; height: 32px; border: 1px solid #ddd6c9; border-radius: 5px; padding: 0 10px; background: #fcfbf7; color: #1f1d18; }
.inline-unit-select { width: 160px; min-width: 0; }
.inline-editor input::placeholder { color: #968f84; opacity: 1; }
.save-option { position: relative; height: 32px; padding: 0 12px; border: 1px solid #ff510a; border-radius: 5px; background: #fff; color: #f04b09; white-space: nowrap; }
.save-option:hover:not(:disabled) { background: #fff0e2; }
.save-option:active:not(:disabled) { background: #ffe3cc; }
.cancel-option { display: inline-flex; align-items: center; justify-content: center; border: 0; border-radius: 5px; background: none; width: 32px; height: 32px; padding: 0; color: #55595e; }
.add-option:disabled, .save-option:disabled, .inline-editor input:disabled { opacity: 1; color: #6f6a61; border-color: #ddd6c9; background: #e8e1d5; }
.delete-option:disabled, .cancel-option:disabled { color: #6f6a61; }
.save-option.processing:disabled { color: #f04b09; background: #fff0e2; border-color: #ff510a; }
.processing > span { visibility: hidden; }
.saving-spinner { position: absolute; left: calc(50% - 8px); top: calc(50% - 8px); width: 16px; height: 16px; animation: saving-spin 1s linear infinite; }
@keyframes saving-spin { to { transform: rotate(360deg); } }
.inline-editor input:focus { border-color: #3898ec; }
.inline-editor [aria-invalid="true"], .inline-editor [aria-invalid="true"]:focus { border-color: #b53333; }
.field-error { display: block; margin-top: 4px; color: #b42318; line-height: 20px; }
.empty-options { color: #85888d; }
button:focus-visible, input:focus-visible { outline: 2px solid #3898ec; outline-offset: 2px; }
@media (hover: none) { .delete-option { opacity: 1; pointer-events: auto; } }
</style>
