<script setup lang="ts">
import { computed, nextTick, ref, type ComponentPublicInstance } from 'vue'
import { Close, Delete } from '@element-plus/icons-vue'
import { materialCatalogError } from '@/api/materialCatalog'
import type { MaterialAttributeValue } from '@/types/materialCatalog'
import MaterialCatalogSelect from './MaterialCatalogSelect.vue'

type ColorEditor = { key: number; optionId: string; draft: MaterialAttributeValue; choice: string; error: string }
const props = defineProps<{
  label: string
  options: MaterialAttributeValue[]
  publicOptions: MaterialAttributeValue[]
  readonly: boolean
  disabled: boolean
  onSave: (color: MaterialAttributeValue) => Promise<void>
  onUpdate: (id: string, color: MaterialAttributeValue) => Promise<void>
  onRemove: (id: string) => Promise<void>
}>()
const editors = ref<ColorEditor[]>([])
const flushing = ref(false)
const removing = ref('')
const error = ref('')
let nextKey = 0
const locked = computed(() => props.disabled || props.readonly || flushing.value || !!removing.value)
const choices = computed(() => props.publicOptions.map(color => ({ value: `public:${color.id}`, label: color.color_name ?? color.value })))
const rows = computed(() => [
  ...props.options.map(option => ({ key: `option-${option.id}`, option, editor: props.readonly ? undefined : editors.value.find(editor => editor.optionId === option.id) })),
  ...(!props.readonly ? editors.value.filter(editor => !editor.optionId).map(editor => ({ key: `new-${editor.key}`, option: undefined, editor })) : []),
])

function normalize(color: MaterialAttributeValue): MaterialAttributeValue {
  const name = (color.color_name ?? color.value).trim()
  return { ...color, value: name, color_name: name, color_card: (color.color_card ?? '').trim(), color_code: (color.color_code ?? '').trim(), product_color_id: color.product_color_id ?? null }
}
function identity(color: MaterialAttributeValue) {
  const normalized = normalize(color)
  return JSON.stringify([normalized.color_card, normalized.color_code, normalized.color_name])
}
function publicLabel(value: string) {
  const color = props.publicOptions.find(item => `public:${item.id}` === value)
  return color ? `${color.color_card || '—'} / ${color.color_code || '—'} / ${color.color_name ?? color.value}` : value
}
const cardInputs = new Map<number, HTMLInputElement>()
function setCardInput(key: number, element: Element | ComponentPublicInstance | null) {
  if (element instanceof HTMLInputElement) cardInputs.set(key, element)
  else cardInputs.delete(key)
}
async function focusEditor(key: number) {
  await nextTick()
  cardInputs.get(key)?.focus()
}
async function add() {
  if (locked.value) return
  const key = ++nextKey
  editors.value.push({ key, optionId: '', choice: '', error: '', draft: {
    id: '', scope: 'BASE', field_key: 'color', parent_id: null, value: '', product_color_id: null, color_card: '', color_code: '', color_name: '',
  } })
  await focusEditor(key)
}
async function edit(option: MaterialAttributeValue) {
  if (locked.value) return
  const existing = editors.value.find(editor => editor.optionId === option.id)
  if (existing) { await focusEditor(existing.key); return }
  const key = ++nextKey
  const draft = normalize(option)
  editors.value.push({ key, optionId: option.id, draft, choice: draft.color_name || '', error: '' })
  await focusEditor(key)
}
function cancel(key: number) {
  if (!locked.value) editors.value = editors.value.filter(editor => editor.key !== key)
}
function manualChange(editor: ColorEditor) {
  editor.draft.product_color_id = null
  editor.choice = editor.draft.color_name || ''
  editor.error = ''
}
function changeColor(editor: ColorEditor, value: string) {
  if (locked.value) return
  const selected = props.publicOptions.find(item => `public:${item.id}` === value)
  if (selected) {
    const normalized = normalize(selected)
    Object.assign(editor.draft, { value: normalized.value, color_name: normalized.color_name,
      color_card: normalized.color_card, color_code: normalized.color_code, product_color_id: selected.product_color_id || selected.id })
  } else {
    Object.assign(editor.draft, { value, color_name: value, product_color_id: null })
  }
  editor.choice = value
  editor.error = ''
}
// 只有顶部统一保存收集全部输入；输入、选公共色、添加和取消都不写库。
async function flushDraft(): Promise<boolean> {
  if (!editors.value.length) return true
  if (flushing.value || props.readonly) return false
  const active = [...editors.value]
  const proposed = [...props.options.filter(option => !active.some(editor => editor.optionId === option.id)), ...active.map(editor => editor.draft)]
  for (const editor of active) {
    editor.error = !normalize(editor.draft).color_name ? '请输入颜色。'
      : proposed.filter(color => identity(color) === identity(editor.draft)).length > 1 ? '该色卡、色号和颜色组合已存在。' : ''
  }
  if (active.some(editor => editor.error)) return false
  flushing.value = true
  let valid = true
  try {
    for (const editor of active) {
      try {
        const color = normalize(editor.draft)
        if (editor.optionId) await props.onUpdate(editor.optionId, color)
        else await props.onSave(color)
        editors.value = editors.value.filter(item => item.key !== editor.key)
      } catch (issue) {
        editor.error = materialCatalogError(issue)
        valid = false
      }
    }
    return valid
  } finally { flushing.value = false }
}
function hasPendingEdit() { return !!editors.value.length || flushing.value || !!removing.value }
async function remove(id: string) {
  if (locked.value) return
  removing.value = id
  error.value = ''
  try { await props.onRemove(id) }
  catch (issue) { error.value = materialCatalogError(issue) }
  finally { removing.value = '' }
}
defineExpose({ flushDraft, hasPendingEdit })
</script>

<template>
  <div class="color-attribute-row" data-field="BASE:color:">
    <div class="color-label">{{ label }}</div>
    <div class="color-content">
      <div class="color-table-scroll">
        <table class="color-table" :aria-label="`${label}选项`">
          <colgroup><col /><col /><col /><col v-if="!readonly" class="color-actions-column" /></colgroup>
          <thead><tr><th scope="col">色卡</th><th scope="col">色号</th><th scope="col">颜色</th><th v-if="!readonly" scope="col"><span class="visually-hidden">操作</span></th></tr></thead>
          <tbody>
            <template v-for="row in rows" :key="row.key">
              <tr v-if="row.editor" class="color-editor erp-flat-form" :data-editor-key="row.editor.key" @keydown.enter.prevent @keydown.esc.prevent="cancel(row.editor.key)">
                <td><input :ref="element => setCardInput(row.editor!.key, element)" v-model="row.editor.draft.color_card" aria-label="色卡" placeholder="可不填" autocomplete="off" :disabled="locked" @input="manualChange(row.editor)" /></td>
                <td><input v-model="row.editor.draft.color_code" aria-label="色号" placeholder="可不填" autocomplete="off" :disabled="locked" @input="manualChange(row.editor)" /></td>
                <td><MaterialCatalogSelect :model-value="row.editor.choice" :options="choices" :ariaLabel="row.editor.optionId ? '修改颜色' : '添加颜色'" placeholder="选择或输入颜色" filterable allow-create :invalid="!!row.editor.error" :disabled="locked" @update:model-value="changeColor(row.editor!, $event)"><template #option="{ option }"><span>{{ publicLabel(option.value) }}</span></template></MaterialCatalogSelect></td>
                <td><button type="button" class="erp-list-button color-action" :aria-label="row.editor.optionId ? '取消修改' : '取消添加'" :disabled="locked" @click="cancel(row.editor.key)"><Close aria-hidden="true" /></button></td>
              </tr>
              <tr v-else-if="row.option" :data-option-id="row.option.id">
                <td>{{ row.option.color_card || '—' }}</td><td>{{ row.option.color_code || '—' }}</td>
                <td><span v-if="readonly">{{ row.option.color_name ?? row.option.value }}</span><button v-else type="button" class="edit-color" data-action="edit" :aria-label="`修改${row.option.color_name ?? row.option.value}`" :disabled="locked" @click="edit(row.option)">{{ row.option.color_name ?? row.option.value }}</button></td>
                <td v-if="!readonly"><button type="button" class="erp-list-button color-action" data-action="delete" :aria-label="`删除${row.option.color_name ?? row.option.value}`" :disabled="locked" @click="remove(row.option.id)"><Delete aria-hidden="true" /></button></td>
              </tr>
              <tr v-if="row.editor?.error"><td colspan="4" class="color-error" role="alert">{{ row.editor.error }}</td></tr>
            </template>
            <tr v-if="!rows.length"><td :colspan="readonly ? 3 : 4" class="empty-colors">暂无颜色</td></tr>
          </tbody>
        </table>
      </div>
      <button v-if="!readonly" type="button" class="erp-list-button add-color" data-action="add" :disabled="locked" @click="add">＋ 添加</button>
      <p v-if="error" class="color-error" role="alert">{{ error }}</p>
    </div>
  </div>
</template>

<style scoped>
.color-attribute-row { display: flex; align-items: flex-start; gap: 12px; padding: 4px 0; font-size: 12px; }
.color-label { display: flex; align-items: center; gap: 12px; width: 120px; flex-shrink: 0; min-height: 28px; line-height: 18px; }
.color-label::after { content: ''; flex: 1; min-width: 16px; border-top: 2px solid var(--erp-color-border-strong); }
.color-content { flex: 1; min-width: 0; }
.color-table-scroll { max-height: 240px; overflow: auto; border: 1px solid var(--erp-table-border); border-radius: 5px; }
.color-table { width: 100%; min-width: 380px; border-collapse: separate; border-spacing: 0; table-layout: fixed; color: var(--erp-color-text-primary); background: var(--erp-table-background); }
.color-table th, .color-table td { height: 32px; box-sizing: border-box; padding: 4px 8px; text-align: left; overflow-wrap: anywhere; border-bottom: 1px solid var(--erp-table-border); }
.color-table th { position: sticky; top: 0; z-index: 1; background: var(--erp-table-header-background); color: var(--erp-table-header-text); font-weight: 500; }
.color-table tbody tr:last-child > td { border-bottom: 0; }
.color-actions-column { width: 40px; }
.color-table tbody tr:hover { background: var(--erp-table-hover); }
.color-table .color-editor > td { padding: 3px 5px; }
.color-editor input { box-sizing: border-box; width: 100%; min-width: 0; height: 28px; padding: 0 8px; border: 1px solid var(--erp-input-border); border-radius: 5px; background: var(--erp-input-background); color: var(--erp-input-text); font: inherit; }
.color-editor.erp-flat-form :deep(.el-select__wrapper) { height: 28px !important; min-height: 28px !important; padding: 0 8px !important; }
.color-editor :deep(.el-select__selected-item), .color-editor :deep(.el-select__input) { font-size: 12px !important; }
.color-action { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; min-height: 24px; padding: 0; }
.color-action svg { width: 13px; height: 13px; }
.color-action[data-action="delete"] { opacity: 0; }
.color-table tbody tr:hover .color-action[data-action="delete"], .color-table tbody tr:focus-within .color-action[data-action="delete"] { opacity: 1; }
.edit-color { width: 100%; padding: 0; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: text; overflow-wrap: anywhere; }
.add-color { margin-top: 6px; height: 28px; min-height: 28px; padding: 0 8px; font-size: 12px; }
.color-error { margin: 4px 0 0; color: var(--erp-color-danger); line-height: 18px; }
.empty-colors { color: var(--erp-color-text-secondary); }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
</style>
