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
          <button v-if="!readonly" type="button" class="erp-list-button erp-button-motion delete-option" data-action="delete" :aria-label="`删除${option.label}`"
            :title="`删除${option.label}`" :disabled="disabled || saving || !!removing" @click="remove(option.id)"><Delete aria-hidden="true" /></button>
        </span>
        <form v-if="editing && !readonly" class="inline-editor" @submit.prevent="save">
          <MaterialCatalogSelect v-if="kind === 'unit'" ref="input" v-model="draft" class="inline-unit-select" :ariaLabel="`添加${label}`"
            :options="unitOptions" placeholder="选择单位" :invalid="!!error" :disabled="disabled || saving" />
          <input class="erp-list-control" v-else ref="input" v-model="draft" :aria-label="`添加${label}`" :placeholder="`输入${label}`" :aria-invalid="!!error" :disabled="disabled || saving" />
          <button type="button" class="erp-list-button erp-button-motion erp-list-button--primary save-option" :class="{ processing: saving }" data-action="save" :aria-label="saving ? '正在保存' : '保存'" :aria-busy="saving" :disabled="disabled || saving" @click="save"><span>保存</span><Loading v-if="saving" class="saving-spinner" aria-hidden="true" /></button>
          <button type="button" class="erp-list-button erp-button-motion cancel-option" aria-label="取消添加" title="取消添加" :disabled="saving" @click="editing = false; error = ''"><Close aria-hidden="true" /></button>
        </form>
        <button v-else-if="!readonly" type="button" class="erp-list-button erp-button-motion add-option" data-action="add" :disabled="disabled || !!removing" @click="startAdding">＋ {{ kind === 'shape' ? '添加形状' : kind === 'dimension' ? '添加尺寸' : '添加' }}</button>
        <span v-if="readonly && !options.length" class="empty-options">—</span>
      </div>
      <span v-if="error" class="field-error" role="alert">{{ error }}</span>
    </div>
  </div>
</template>

<style scoped>
.attribute-row { display: flex; align-items: flex-start; gap: 12px; min-height: 40px; padding: 4px 0; box-sizing: border-box; }
.attribute-label { display: flex; align-items: center; gap: 12px; width: 120px; flex-shrink: 0; min-height: 32px; line-height: 20px; color: var(--erp-color-text-primary); }
.attribute-label::after { content: ''; flex: 1; min-width: 16px; border-top: 1px dashed var(--erp-color-border); }
.attribute-content { flex: 1; min-width: 0; }
.option-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-height: 32px; }
.option-chip { position: relative; display: inline-flex; align-items: center; justify-content: center; min-width: 84px; min-height: 32px; box-sizing: border-box; padding: 3px 28px; border: 1px solid var(--erp-input-border); border-radius: var(--erp-radius-control); background: var(--erp-input-surface); color: var(--erp-input-text); max-width: 100%; overflow-wrap: anywhere; text-align: center; }
.option-chip:hover, .option-chip:focus-within { background: var(--erp-table-hover); }
.delete-option { position: absolute; right: 0; top: calc(50% - 16px); opacity: 0; pointer-events: none; width: 32px; padding: 0; }
.delete-option svg, .cancel-option svg { width: 16px; height: 16px; }
.option-chip:hover .delete-option, .option-chip:focus-within .delete-option, .delete-option:focus-visible { opacity: 1; pointer-events: auto; }
.add-option { min-width: 84px; white-space: nowrap; }
.inline-editor { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; }
.inline-editor input, .inline-unit-select { width: 160px; min-width: 0; }
.save-option { position: relative; white-space: nowrap; }
.cancel-option { width: 32px; padding: 0; }
.processing > span { visibility: hidden; }
.saving-spinner { position: absolute; left: calc(50% - 8px); top: calc(50% - 8px); width: 16px; height: 16px; animation: saving-spin 1s linear infinite; }
@keyframes saving-spin { to { transform: rotate(360deg); } }
.inline-editor [aria-invalid="true"], .inline-editor [aria-invalid="true"]:focus { border-color: var(--erp-color-danger); }
.field-error { display: block; margin-top: 4px; color: var(--erp-color-danger); line-height: 20px; }
.empty-options { color: var(--erp-color-text-secondary); }
@media (hover: none) { .delete-option { opacity: 1; pointer-events: auto; } }
@media (prefers-reduced-motion: reduce) { .saving-spinner { animation: none; } }
</style>
