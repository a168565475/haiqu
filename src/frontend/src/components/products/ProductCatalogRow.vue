<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { Close, Delete, Plus } from '@element-plus/icons-vue'
import ProductCatalogField from './ProductCatalogField.vue'
import ProductCatalogError from './ProductCatalogError.vue'
import ProductCatalogSaveButton from './ProductCatalogSaveButton.vue'
import {
  addProductCatalogColor, deleteProductCatalogColor, fetchProductCatalog, productCatalogError,
  productCatalogErrorStatus, updateProductCatalog,
} from '@/api/productCatalog'
import { productCatalogFields, type ProductCatalog, type ProductCatalogFields, type VersionedProductCatalog } from '@/types/productCatalog'

const props = defineProps<{ product: ProductCatalog; canChange: boolean; scales: string[] }>()
const emit = defineEmits<{ updated: [product: ProductCatalog]; lock: [id: string, active: boolean] }>()
const item = ref(props.product)
const etag = ref('')
const warning = ref('')
const readError = ref('')
const loading = ref(false)
const pending = ref(0)
const editors = ref(0)
const addingColor = ref(false)
const colorDraft = ref('')
const colorError = ref('')
const savingColor = ref(false)
const colorInput = ref<HTMLInputElement>()
let writeQueue: Promise<void> = Promise.resolve()
let readPromise: Promise<void> | undefined
let alive = true
const blocked = computed(() => loading.value || pending.value > 0 || !!warning.value)
const scaleOptions = computed(() => [...new Set(['', '常规', '定制', ...props.scales, item.value.scale])].map(value => ({ value, label: value || '未填写' })))
watch(() => props.product, value => { item.value = value })
watch(() => loading.value || pending.value > 0 || editors.value > 0 || addingColor.value,
  value => emit('lock', props.product.id, value))
function apply(result: VersionedProductCatalog) {
  if (!alive) return
  item.value = result.data
  etag.value = result.etag
  warning.value = result.etag ? '' : '未取得产品版本，请重新读取后再保存。'
  emit('updated', result.data)
}
async function reload() {
  if (readPromise) return readPromise
  loading.value = true
  readError.value = ''
  readPromise = (async () => {
    try { apply(await fetchProductCatalog(props.product.id)) }
    catch (issue) { readError.value = productCatalogError(issue); etag.value = ''; throw issue }
    finally { loading.value = false; readPromise = undefined }
  })()
  return readPromise
}
async function ensureVersion() {
  if (!etag.value && !warning.value) await reload()
  if (!etag.value || warning.value) throw new Error(warning.value || '请重新读取产品后再保存。')
}
function write(action: (version: string) => Promise<VersionedProductCatalog>) {
  pending.value += 1
  const task = writeQueue.then(async () => {
    if (!props.canChange || !alive) throw new Error('没有修改权限，输入内容已保留。')
    await ensureVersion()
    try { apply(await action(etag.value)) }
    catch (issue) {
      if ([412, 428].includes(productCatalogErrorStatus(issue) ?? 0)) warning.value = productCatalogError(issue)
      throw issue
    }
  }).finally(() => { pending.value -= 1 })
  // 同一产品的字段与颜色串行使用最新版本；错误仍交回各输入位置显示。
  writeQueue = task.catch(() => undefined)
  return task
}
function saveField(key: keyof ProductCatalogFields, value: string) {
  return write(version => updateProductCatalog(item.value.id, { [key]: value }, version))
}
async function startColor() {
  if (!props.canChange || blocked.value) return
  addingColor.value = true
  colorError.value = ''
  try { await ensureVersion() }
  catch (issue) { colorError.value = productCatalogError(issue) }
  await nextTick()
  colorInput.value?.focus()
}
async function saveColor() {
  if (!props.canChange || blocked.value || savingColor.value) return
  if (!colorDraft.value.trim()) { colorError.value = '请输入颜色。'; return }
  savingColor.value = true
  colorError.value = ''
  try {
    await write(version => addProductCatalogColor(item.value.id, { value: colorDraft.value.trim() }, version))
    addingColor.value = false
    colorDraft.value = ''
  } catch (issue) { colorError.value = productCatalogError(issue) }
  finally { savingColor.value = false }
}
async function removeColor(id: string) {
  if (!props.canChange || blocked.value) return
  colorError.value = ''
  try { await write(version => deleteProductCatalogColor(item.value.id, id, version)) }
  catch (issue) { colorError.value = productCatalogError(issue) }
}
async function retryRead() { try { await reload() } catch (issue) { readError.value = productCatalogError(issue) } }
onBeforeUnmount(() => { alive = false; emit('lock', props.product.id, false) })
</script>

<template>
  <tr class="product-catalog-row" :data-product-id="item.id" :aria-busy="loading || pending > 0">
    <td v-for="field in productCatalogFields" :key="field.key" :data-field="field.key">
      <ProductCatalogField :value="item[field.key]" :label="field.label" :max-length="field.maxLength" :empty-text="field.key === 'unit' ? '无单位' : field.key === 'scale' ? '未填写' : '—'"
        :options="field.key === 'scale' ? scaleOptions : undefined" :readonly="!canChange" :disabled="blocked"
        :on-start="ensureVersion" :on-save="value => saveField(field.key, value)" @editing="active => editors += active ? 1 : -1" />
    </td>
    <td data-field="colors">
      <div class="product-colors">
        <span v-for="color in item.colors" :key="color.id" class="product-color" :data-color-id="color.id">
          <span>{{ color.value }}</span>
          <button v-if="canChange" type="button" class="color-delete icon-button" :aria-label="`删除颜色${color.value}`" :title="`删除颜色${color.value}`" :disabled="blocked" @click="removeColor(color.id)"><Delete aria-hidden="true" /></button>
        </span>
        <span v-if="!item.colors.length" class="no-colors">尚未维护颜色</span>
        <form v-if="addingColor" class="color-editor" @submit.prevent="saveColor">
          <input ref="colorInput" v-model="colorDraft" aria-label="新颜色" placeholder="输入颜色" maxlength="200" :aria-invalid="!!colorError" :disabled="blocked || savingColor || !canChange" />
          <ProductCatalogSaveButton type="submit" class="small-save" data-action="save-color" label="保存" ariaLabel="保存颜色" :loading="savingColor" :disabled="blocked || !canChange" />
          <button type="button" class="icon-button" aria-label="取消添加颜色" title="取消添加颜色" :disabled="savingColor" @click="addingColor = false; colorError = ''"><Close aria-hidden="true" /></button>
        </form>
        <button v-else-if="canChange" type="button" class="add-color" data-action="add-color" aria-label="添加颜色" :disabled="blocked" @click="startColor"><Plus aria-hidden="true" />颜色</button>
        <ProductCatalogError v-if="colorError" :message="colorError" />
      </div>
      <div v-if="warning || readError" class="version-warning" role="alert">{{ warning || readError }}<button type="button" data-action="reload" :disabled="loading || pending > 0" @click="retryRead">重新读取</button></div>
    </td>
  </tr>
</template>

<style scoped lang="scss">
.product-colors { position: relative; display: flex; align-items: center; flex-wrap: wrap; gap: 8px; min-height: 32px; }
.product-color { position: relative; display: inline-flex; align-items: center; min-height: 32px; max-width: 100%; box-sizing: border-box; padding: 3px 34px 3px 10px; border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7; white-space: pre-wrap; overflow-wrap: anywhere; }
.product-color:hover, .product-color:focus-within { background: #fff6ea; }
button, input { font: inherit; }
button { display: inline-flex; align-items: center; justify-content: center; gap: 4px; flex-shrink: 0; box-sizing: border-box; height: 32px; padding: 0 8px; border: 1px solid #ddd6c9; border-radius: 5px; color: #1f1d18; background: #fcfbf7; cursor: pointer; }
button:hover:not(:disabled):not([aria-busy='true']) { background: #f0eadf; border-color: #c9c0b2; }
button:active:not(:disabled):not([aria-busy='true']) { background: #e8e1d5; border-color: #c9c0b2; }
svg { width: 16px; height: 16px; }
.icon-button { width: 32px; padding: 0; border-color: transparent; background: transparent; color: #6f6a61; }
.color-delete { position: absolute; right: 0; top: calc(50% - 16px); opacity: 0; pointer-events: none; }
.product-color:hover .color-delete, .product-color:focus-within .color-delete, .color-delete:focus-visible { opacity: 1; pointer-events: auto; }
.color-editor { display: flex; align-items: center; gap: 6px; max-width: 100%; }
.color-editor input { box-sizing: border-box; height: 32px; width: 150px; min-width: 0; padding: 0 10px; border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7; color: #1f1d18; }
.color-editor input:focus { border-color: #3898ec; }
.color-editor input[aria-invalid='true'] { border-color: #b53333; }
.color-editor input::placeholder, .no-colors { color: #968f84; }
.small-save { min-width: 48px; color: #c84e28; border-color: #c84e28; }
button:disabled, input:disabled { opacity: 1; cursor: not-allowed; color: #6f6a61; background: #e8e1d5; border-color: #ddd6c9; }
button:focus-visible, input:focus-visible { outline: 2px solid #3898ec; outline-offset: 2px; }
.version-warning { margin: 6px 0 0; color: #b53333; font-size: 12px; line-height: 18px; overflow-wrap: anywhere; }
.version-warning button { margin: 4px 0 0 6px; }
@media (hover: none) { .color-delete { opacity: 1; pointer-events: auto; } }
</style>
