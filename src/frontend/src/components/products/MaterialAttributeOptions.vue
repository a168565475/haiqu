<script setup lang="ts">
import { computed, nextTick, ref, type ComponentPublicInstance } from 'vue'
import { Close, Delete } from '@element-plus/icons-vue'
import { materialCatalogError } from '@/api/materialCatalog'
import type { MaterialFieldDefinition, MaterialScope } from '@/types/materialCatalog'
import MaterialCatalogSelect from './MaterialCatalogSelect.vue'

type AttributeOption = { id: string; label: string; value?: string }
type EditorEntry = {
  key: number
  optionId: string
  option?: AttributeOption
  label: string
  draft: string
  error: string
}
const props = defineProps<{
  label: string
  fieldKey: string
  kind: MaterialFieldDefinition['kind']
  scope: MaterialScope
  parentId?: string
  options: AttributeOption[]
  availableUnits: { id: string; unit_name: string }[]
  publicOptions?: string[]
  parentOptions?: string[]
  readonly: boolean
  disabled: boolean
  onSave: (value: string) => Promise<void>
  onUpdate: (id: string, value: string) => Promise<void>
  onRemove: (id: string) => Promise<void>
}>()
const editors = ref<EditorEntry[]>([])
const error = ref('')
const saving = ref(false)
const removing = ref('')
const inputs = new Map<number, { focus: () => void }>()
let nextEditorKey = 0
const displayedItems = computed(() => {
  const items: { key: string; option?: AttributeOption; editor?: EditorEntry }[] = []
  // 形状由尺寸行的 label 插槽触发编辑，不在该行的尺寸 options 中。
  for (const editor of editors.value) {
    if (editor.optionId && !props.options.some(option => option.id === editor.optionId)) {
      items.push({ key: `editor-${editor.key}`, option: editor.option, editor })
    }
  }
  for (const option of props.options) {
    const editor = editors.value.find(item => item.optionId === option.id)
    items.push({ key: editor ? `editor-${editor.key}` : `option-${option.id}`, option, editor })
  }
  for (const editor of editors.value) {
    if (!editor.optionId) items.push({ key: `editor-${editor.key}`, editor })
  }
  return items
})
function setInput(key: number, element: Element | ComponentPublicInstance | null) {
  if (element) inputs.set(key, element as unknown as { focus: () => void })
  else inputs.delete(key)
}
function optionsForEditor(editor: EditorEntry) {
  const values = editor.optionId && !props.options.some(option => option.id === editor.optionId)
    ? props.parentOptions : props.publicOptions
  return (values ?? []).map(value => ({ value, label: value }))
}
async function focusEditor(key: number) {
  await nextTick()
  inputs.get(key)?.focus()
}
async function startAdding() {
  if (saving.value || removing.value || props.disabled || props.readonly) return
  const key = ++nextEditorKey
  editors.value.push({ key, optionId: '', label: props.label, draft: '', error: '' })
  await focusEditor(key)
}
async function startEditing(option: AttributeOption, label = props.label) {
  if (saving.value || removing.value || props.disabled || props.readonly) return
  const existing = editors.value.find(editor => editor.optionId === option.id)
  if (existing) { await focusEditor(existing.key); return }
  const key = ++nextEditorKey
  editors.value.push({ key, optionId: option.id, option: { ...option }, label, draft: option.label, error: '' })
  await focusEditor(key)
}
function cancel(key: number) {
  if (saving.value || props.disabled || props.readonly) return
  editors.value = editors.value.filter(editor => editor.key !== key)
}
// 只有顶部保存调用本方法；添加、回车和失焦均不收集或提交输入。
async function flushDraft(): Promise<boolean> {
  if (!editors.value.length) return true
  if (saving.value || props.readonly) return false
  const active = [...editors.value]
  const regularEditors = active.filter(editor => !editor.optionId || props.options.some(option => option.id === editor.optionId))
  const proposedValues = [
    ...props.options.filter(option => !active.some(editor => editor.optionId === option.id)).map(option => option.label.trim()),
    ...regularEditors.map(editor => editor.draft.trim()),
  ]
  for (const editor of active) {
    const value = editor.draft.trim()
    editor.error = !value ? (props.kind === 'unit' ? '请输入可用单位。' : '请输入选项内容。') : ''
    if (value && regularEditors.includes(editor) && proposedValues.filter(item => item === value).length > 1) {
      editor.error = '该选项已存在，请修改输入内容。'
    }
  }
  if (active.some(editor => editor.error)) return false
  saving.value = true
  let valid = true
  try {
    for (const editor of active) {
      try {
        if (editor.optionId) await props.onUpdate(editor.optionId, editor.draft.trim())
        else await props.onSave(editor.draft.trim())
        editors.value = editors.value.filter(item => item.key !== editor.key)
      } catch (issue) {
        editor.error = materialCatalogError(issue)
        valid = false
      }
    }
    return valid
  } finally { saving.value = false }
}
function hasPendingEdit() { return !!editors.value.length || saving.value || !!removing.value }
async function remove(id: string) {
  if (removing.value || saving.value || props.disabled || props.readonly || (id === props.parentId && editors.value.length)) return
  error.value = ''
  removing.value = id
  try { await props.onRemove(id) }
  catch (issue) { error.value = materialCatalogError(issue) }
  finally { removing.value = '' }
}
defineExpose({ flushDraft, hasPendingEdit })
</script>

<template>
  <div class="attribute-row" :data-field="`${scope}:${fieldKey}:${parentId || ''}`">
    <div class="attribute-label"><slot name="label" :remove="remove" :edit="startEditing" :busy="saving || !!removing" :pending="!!editors.length">{{ label }}</slot></div>
    <div class="attribute-content">
      <div class="option-line">
        <template v-for="item in displayedItems" :key="item.key">
          <div v-if="item.editor && !readonly" class="editor-field" :data-editor-key="item.editor.key">
            <form class="inline-editor erp-flat-form" @submit.prevent @keydown.esc.prevent="cancel(item.editor.key)">
              <MaterialCatalogSelect :ref="element => setInput(item.editor!.key, element)" v-model="item.editor.draft" class="inline-public-select" :ariaLabel="`${item.editor.optionId ? '修改' : '添加'}${item.editor.label}`"
                :options="optionsForEditor(item.editor)" filterable allow-create :placeholder="`选择或输入${item.editor.label}`" :invalid="!!item.editor.error" :disabled="disabled || saving" />
              <button type="button" class="erp-list-button erp-button-motion cancel-option" :aria-label="item.editor.optionId ? '取消修改' : '取消添加'" :title="item.editor.optionId ? '取消修改' : '取消添加'" :disabled="disabled || saving" @click="cancel(item.editor.key)"><Close aria-hidden="true" /></button>
            </form>
            <span v-if="item.editor.error" class="field-error" role="alert">{{ item.editor.error }}</span>
          </div>
          <span v-else-if="item.option" class="option-chip" :data-option-id="item.option.id">
            <span v-if="readonly" class="option-label">{{ item.option.label }}</span>
            <button v-else type="button" class="option-label edit-option" data-action="edit" :aria-label="`修改${item.option.label}`" :title="`修改${item.option.label}`" :disabled="disabled || saving || !!removing" @click="startEditing(item.option)">{{ item.option.label }}</button>
            <button v-if="!readonly" type="button" class="erp-list-button erp-button-motion delete-option" data-action="delete" :aria-label="`删除${item.option.label}`"
              :title="`删除${item.option.label}`" :disabled="disabled || saving || !!removing" @click.stop="remove(item.option.id)"><Delete aria-hidden="true" /></button>
          </span>
        </template>
        <button v-if="!readonly" type="button" class="erp-list-button erp-button-motion add-option" data-action="add" :disabled="disabled || saving || !!removing" @click="startAdding">＋ {{ kind === 'shape' ? '添加形状' : kind === 'dimension' ? '添加尺寸' : '添加' }}</button>
        <span v-if="readonly && !options.length" class="empty-options">—</span>
      </div>
      <span v-if="error" class="field-error" role="alert">{{ error }}</span>
    </div>
  </div>
</template>
<style scoped>
.attribute-row { display: flex; align-items: flex-start; gap: 12px; min-height: 36px; padding: 4px 0; box-sizing: border-box; }
.attribute-label { display: flex; align-items: center; gap: 12px; width: 120px; flex-shrink: 0; min-height: 28px; line-height: 18px; color: var(--erp-color-text-primary); }
.attribute-label::after { content: ''; flex: 1; min-width: 16px; border-top: 2px solid var(--erp-color-border-strong); }
.attribute-content { flex: 1; min-width: 0; }
.option-line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; min-height: 28px; }
.option-chip { position: relative; display: inline-flex; align-items: center; justify-content: center; min-width: 68px; min-height: 28px; box-sizing: border-box; border: 1px solid var(--erp-color-border); border-radius: 5px; background: var(--erp-color-surface); color: var(--erp-input-text); max-width: 100%; overflow-wrap: anywhere; text-align: center; font-size: 12px; line-height: 18px; }
.option-label { display: block; box-sizing: border-box; width: 100%; min-height: 26px; padding: 4px 24px 4px 8px; font: inherit; }
.edit-option { border: 0; border-radius: inherit; background: transparent; color: inherit; cursor: text; overflow-wrap: anywhere; }
.edit-option:focus-visible { outline: 1px solid var(--erp-color-focus); outline-offset: -1px; }
.edit-option:disabled { cursor: default; }
.option-chip:hover, .option-chip:focus-within { background: var(--erp-table-hover); }
.delete-option { position: absolute; right: 3px; top: calc(50% - 10px); opacity: 0; pointer-events: none; width: 20px; height: 20px; min-height: 20px; padding: 0; box-shadow: none; }
.delete-option svg { width: 12px; height: 12px; }
.cancel-option svg { width: 14px; height: 14px; }
.option-chip:hover .delete-option, .option-chip:focus-within .delete-option, .delete-option:focus-visible { opacity: 1; pointer-events: auto; }
.add-option { min-width: 68px; white-space: nowrap; height: 28px; padding: 0 8px; font-size: 12px; }
.editor-field { display: inline-flex; flex-direction: column; max-width: 100%; }
.inline-editor { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; }
.inline-editor:has(.is-invalid) { --erp-dialog-input-border: var(--erp-color-danger); --erp-dialog-input-hover-border: var(--erp-color-danger); --erp-dialog-input-focus-border: var(--erp-color-danger); }
.inline-public-select { width: 132px; min-width: 0; }
.attribute-row .inline-editor.erp-flat-form :deep(.el-select__wrapper) { height: 28px !important; min-height: 28px !important; padding: 0 8px !important; }
.attribute-row .inline-editor.erp-flat-form :deep(.el-select__selected-item), .attribute-row .inline-editor.erp-flat-form :deep(.el-select__input) { font-size: 12px !important; }
.cancel-option { width: 24px; height: 28px; padding: 0; }
.inline-editor [aria-invalid="true"], .inline-editor [aria-invalid="true"]:focus { border-color: var(--erp-color-danger); }
.field-error { display: block; margin-top: 4px; color: var(--erp-color-danger); line-height: 20px; }
.empty-options { color: var(--erp-color-text-secondary); }
@media (hover: none) { .delete-option { opacity: 1; pointer-events: auto; } }
</style>
