<script setup lang="ts">
import { isAxiosError } from 'axios'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { Button as VanButton, Loading as VanLoading, showConfirmDialog } from 'vant'
import 'vant/es/button/style'
import 'vant/es/dialog/style'
import 'vant/es/loading/style'
import WageOptionPicker from '@/components/WageOptionPicker.vue'
import WorkPage from '@/components/WorkPage.vue'
import { createWageSchemeChange, fetchWageForm, fetchWageScheme, saveWageScheme, submitWageScheme } from '@/api/wageSchemes'
import { useAuthStore } from '@/stores/auth'
import type { SavedWageScheme, VersionedWageScheme, WageBomOption, WageFormOptions, WageLineInput, WageOperation, WageSchemeInput, WageTarget } from '@/types/wageSchemes'
import { errorMessage } from '@/utils/errors'
import { displayQuantity } from '@/utils/planDisplay'

type WageRow = Omit<WageLineInput, 'craft_id' | 'bom_line_id'> & { key: number; bom_line_id: string; operation_name?: string }
const pricePattern = /^(?:[0-9]{1,14}(?:\.[0-9]{1,4})?|\.[0-9]{1,4})$/

const props = defineProps<{ target: WageTarget }>()
const emit = defineEmits<{ back: [refresh: boolean]; submitted: [scheme: SavedWageScheme] }>()
const auth = useAuthStore()
const options = shallowRef<WageFormOptions>()
const saved = shallowRef<VersionedWageScheme | null>(null)
const changeSource = shallowRef<VersionedWageScheme | null>(null)
const productName = ref('')
const remark = ref('')
const rows = ref<WageRow[]>([])
const editingRowKey = ref<number>()
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
const submitError = ref('')
const rowError = ref<{ key: number; message: string }>()
const checkNewScheme = ref(false)
let checkSavedScheme = false
let baseline = ''
let nextKey = 0
let readRequest: AbortController | undefined

const bom = computed(() => options.value?.bom_options ?? null)
const productNames = computed(() => [...new Set(
  options.value?.operations.map(operation => operation.product_name).filter(Boolean) ?? [],
)])
const operations = computed(() => {
  const form = options.value
  if (!form) return []
  return form.requires_product_name
    ? form.operations.filter(operation => operation.product_name === productName.value)
    : form.operations
})
const productChoices = computed(() => productNames.value.map(name => ({ value: name, label: name })))
const partChoices = computed(() => bom.value?.map(part => ({
  value: part.id, label: part.problem ? `${part.name}（资料待补）` : part.name,
})) ?? [])
const operationChoices = computed(() => operations.value.map(operation => ({ value: operation.id, label: operation.name })))
const isChange = computed(() => Boolean(changeSource.value || saved.value?.data.parent_scheme))
const formTitle = computed(() => isChange.value || props.target.scheme?.can_change || props.target.scheme?.is_change
  ? '变更工价' : props.target.scheme ? '填写工价' : '新建工价')
const existingStatus = computed(() => {
  const scheme = options.value?.target.scheme
  return scheme && !scheme.can_edit && !scheme.can_change ? scheme.status_display : ''
})
const ready = computed(() => options.value && !existingStatus.value)
const locked = computed(() => saving.value || (
  saved.value !== null && !auth.hasPermission('workshop_reporting.change_wagescheme')
))
const missingSetup = computed(() => {
  if (!options.value || isChange.value) return ''
  if (bom.value && !bom.value.some(item => item.required_quantity !== null)) {
    return bom.value[0]?.problem || '这个产品还没有可选部位，请联系负责人完善资料'
  }
  if (!options.value.operations.length || options.value.requires_product_name && !productNames.value.length) {
    return '当前工艺没有可用工序，请先维护工序资料'
  }
  return ''
})

function formSnapshot() {
  return JSON.stringify([productName.value, remark.value, rows.value])
}

function unusedOperations(part: string) {
  const used = rows.value.filter(row => row.bom_line_id === part).map(row => row.operation_id)
  return operations.value.filter(operation => !used.includes(operation.id))
}

function openRow(key: number, scroll = true) {
  editingRowKey.value = key
  if (scroll) void nextTick(() => document.getElementById(`wage-row-${key}`)?.scrollIntoView({ block: 'nearest' }))
}

function addRow(part = '', scroll = false) {
  const bomLine = part || (bom.value?.length === 1 && bom.value[0]!.required_quantity !== null ? bom.value[0]!.id : '')
  const candidates = bomLine ? unusedOperations(bomLine) : operations.value
  const key = ++nextKey
  rows.value.push({
    key, bom_line_id: bomLine, operation_id: candidates.length === 1 ? candidates[0]!.id : '',
    display_name: '', declared_price: '', previous_price: null, revised_price: null,
    production_description: '', status: 'ACTIVE', note: '',
  })
  openRow(key, scroll)
}

function removeRow(key: number) {
  rows.value = rows.value.filter(row => row.key !== key)
  if (rowError.value?.key === key) rowError.value = undefined
  editingRowKey.value = rows.value.find(row => rowProblem(row))?.key
}

function existingRow(line: SavedWageScheme['lines'][number], form: WageFormOptions): WageRow {
  let part = form.bom_options?.find(item => item.identity === line.bom_component_identity)
  if (isChange.value && !line.bom_component_identity && form.bom_options) {
    const matches = form.bom_options.filter(item => item.name === line.display_name.trim())
    if (matches.length === 1) part = matches[0]
  }
  return {
    key: ++nextKey, bom_line_id: part?.id ?? '', work_item_id: line.work_item_id, counting_mode: line.counting_mode,
    operation_id: line.operation_id, operation_name: line.operation_name, display_name: line.display_name,
    declared_price: isChange.value ? displayQuantity(line.declared_price) : line.declared_price,
    previous_price: changeSource.value ? line.declared_price : line.previous_price,
    revised_price: changeSource.value ? null : line.revised_price, status: line.status,
    production_description: line.production_description, note: line.note,
  }
}

async function load() {
  const current = new AbortController()
  readRequest?.abort()
  readRequest = current
  loading.value = true
  loadError.value = ''
  try {
    const form = await fetchWageForm(props.target, current.signal)
    if (current.signal.aborted) return
    options.value = form
    const scheme = form.target.scheme
    if (scheme && !scheme.can_edit && !scheme.can_change) return
    if (scheme) {
      const record = await fetchWageScheme(scheme.id, current.signal)
      if (current.signal.aborted) return
      if (scheme.can_change && record.data.status === 'APPROVED' && record.data.can_create_change) changeSource.value = record
      else if (scheme.can_edit && (record.data.status === 'DRAFT' || record.data.status === 'RETURNED')) saved.value = record
      else {
        emit('back', true)
        return
      }
      productName.value = record.data.operation_product_name
      remark.value = record.data.remark
      rows.value = record.data.lines.map(line => existingRow(line, form))
    } else {
      productName.value = form.requires_product_name && productNames.value.length === 1 ? productNames.value[0]! : ''
    }
    if (!isChange.value) {
      if (rows.value.length) editingRowKey.value = rows.value.find(row => rowProblem(row))?.key
      else addRow()
    }
    baseline = formSnapshot()
  } catch (error) {
    if (!current.signal.aborted) loadError.value = errorMessage(error, '工价表单加载失败，请重试')
  } finally {
    if (readRequest === current) loading.value = false
  }
}

async function confirmChange(message: string, confirmButtonText: string) {
  try {
    await showConfirmDialog({ message, confirmButtonText })
    return true
  } catch {
    return false
  }
}

async function changeProductName(name: string) {
  if (productName.value && (saved.value || formSnapshot() !== baseline)
    && !await confirmChange('更换工序品名后，需要重新填写已录入的工价。', '更换')) return
  productName.value = name
  rows.value = []
  rowError.value = undefined
  addRow()
}

function partFor(row: WageRow) {
  return bom.value?.find(item => item.id === row.bom_line_id)
}

function operationFor(row: WageRow) {
  return operations.value.find(item => item.id === row.operation_id)
}

function rowTitle(row: WageRow) {
  const part = (!isChange.value && partFor(row)?.name) || row.display_name.trim()
  const operation = isChange.value ? row.operation_name : operationFor(row)?.name
  return part && operation && part !== operation ? `${part} · ${operation}` : operation || part || '待填工序'
}

function requiredQuantity(row: WageRow) {
  const quantity = bom.value ? partFor(row)?.required_quantity : options.value?.order_quantity
  return quantity?.replace(/(\.\d*?[1-9])0+$|\.0+$/, '$1')
}

function rowProblem(row: WageRow, part: WageBomOption | undefined = partFor(row), operation: WageOperation | undefined = operationFor(row)) {
  if (bom.value && !part) return isChange.value ? '原部位在当前产品资料中找不到，请联系负责人核对' : '请选择要做的部位'
  if (part?.required_quantity === null) return part.problem
  if (!operation) return isChange.value ? '原工序已不可用，请联系负责人核对' : '请选择工序'
  const price = row.declared_price.trim()
  if (!price) return '请填写每次工价'
  if (!pricePattern.test(price)) return '工价请填 0 或正数，最多四位小数'
  if ([row.previous_price, row.revised_price].some(value => value?.trim() && !pricePattern.test(value.trim()))) {
    return '补充信息里的工价请填 0 或正数，最多四位小数'
  }
  return ''
}

function showRowProblem(row: WageRow, message: string) {
  rowError.value = { key: row.key, message }
  openRow(row.key)
}

function addNextRow(part = '') {
  rowError.value = undefined
  submitError.value = ''
  for (const row of rows.value) {
    const message = rowProblem(row)
    if (message) {
      showRowProblem(row, message)
      return
    }
  }
  addRow(part, true)
}

function collectInput(): WageSchemeInput | null {
  const form = options.value!
  const { target } = form
  if (form.requires_product_name && !productNames.value.includes(productName.value)) {
    submitError.value = isChange.value ? '原方案的工序品名已不可用，请联系负责人核对' : '请选择工序品名'
    return null
  }
  if (!rows.value.some(row => row.status === 'ACTIVE')) {
    submitError.value = '请先填写一道工序的工价'
    return null
  }
  const lines: WageLineInput[] = []
  const seen = new Set<string>()
  for (const row of rows.value) {
    const part = partFor(row)
    const operation = operationFor(row)
    const display = part?.name || row.display_name.trim() || operation?.name || ''
    const identity = JSON.stringify([operation?.id, part?.id || display.toLowerCase()])
    const message = rowProblem(row, part, operation) || (seen.has(identity) ? '这个部位的这道工序已填写' : '')
    if (message) {
      showRowProblem(row, message)
      return null
    }
    seen.add(identity)
    lines.push({
      craft_id: target.craft_id, bom_line_id: part?.id ?? null, operation_id: row.operation_id,
      ...(isChange.value ? { work_item_id: row.work_item_id, counting_mode: row.counting_mode } : {}),
      display_name: display, declared_price: row.declared_price.trim(), status: row.status,
      previous_price: row.previous_price?.trim() || null, revised_price: row.revised_price?.trim() || null,
      production_description: row.production_description.trim(), note: row.note.trim(),
    })
  }
  return {
    schedule_product_id: target.schedule_product_id, product_line_id: target.product_line_id,
    workshop_id: target.workshop_id, craft_ids: [target.craft_id],
    ...(form.requires_product_name ? { operation_product_name: productName.value } : {}),
    remark: remark.value.trim(), lines,
  }
}

async function submit() {
  if (saving.value || !ready.value || missingSetup.value) return
  submitError.value = ''
  rowError.value = undefined
  const input = collectInput()
  if (!input) return
  saving.value = true
  let creating = false
  try {
    if (checkNewScheme.value) {
      const latest = (await fetchWageForm(props.target)).target.scheme
      const canRetry = changeSource.value ? latest?.id === changeSource.value.data.id && latest.can_change : !latest
      if (!canRetry) throw new Error('这道工艺已有其他工价版本，请返回列表继续处理最新方案')
      checkNewScheme.value = false
    }
    if (saved.value && checkSavedScheme) {
      const latest = await fetchWageScheme(saved.value.data.id)
      if (latest.data.status !== 'DRAFT' && latest.data.status !== 'RETURNED') {
        emit('submitted', latest.data)
        return
      }
      if (latest.etag !== saved.value.etag) throw new Error('工价方案已更新，请返回查询结果核对后继续')
      checkSavedScheme = false
    }
    if (!saved.value || formSnapshot() !== baseline) {
      creating = !saved.value
      checkSavedScheme = !creating
      saved.value = creating && changeSource.value
        ? await createWageSchemeChange(changeSource.value, input)
        : await saveWageScheme(input, saved.value)
      creating = false
      baseline = formSnapshot()
    }
    checkSavedScheme = true
    emit('submitted', await submitWageScheme(saved.value))
  } catch (error) {
    if (creating && (!isAxiosError(error) || !error.response || error.response.status === 409 || error.response.status >= 500)) {
      checkNewScheme.value = true
    }
    submitError.value = errorMessage(error, '提交失败，已保留填写内容')
  } finally {
    saving.value = false
  }
}

async function allowLeave() {
  if (saving.value) return false
  return !ready.value || formSnapshot() === baseline || confirmChange('当前修改尚未保存，确定返回？', '返回')
}

async function back() {
  if (await allowLeave()) emit('back', Boolean(saved.value || existingStatus.value || checkNewScheme.value))
}

onMounted(load)
onBeforeUnmount(() => readRequest?.abort())
onBeforeRouteLeave(allowLeave)
</script>

<template>
  <WorkPage class="wage-form-page" :title="target.task_number" :subtitle="formTitle" home section="wages">
    <template #header-action><button type="button" class="action-link wage-back" :disabled="saving" @click="back">返回</button></template>
    <div class="wage-editor">
      <section class="section-card wage-summary">
        <h2>{{ target.product_name }}</h2>
        <p v-if="target.product_number || target.product_specification || target.product_color" class="muted">
          {{ [target.product_number, target.product_specification, target.product_color].filter(Boolean).join(' · ') }}
        </p>
        <p>{{ target.workshop_name }} · {{ target.craft_name }}</p>
      </section>
      <VanLoading v-if="loading" class="wage-loading" vertical>正在读取工序与部位</VanLoading>
      <section v-else-if="loadError" class="error-panel" role="alert">
        <p>{{ loadError }}</p>
        <VanButton plain size="small" @click="load">重试</VanButton>
      </section>
      <p v-else-if="existingStatus" class="section-card" role="status">当前方案 · {{ existingStatus }}</p>
      <p v-else-if="missingSetup" class="error-panel" role="alert">{{ missingSetup }}</p>
      <div v-else-if="isChange" class="wage-lines">
        <article v-for="row in rows" :id="`wage-row-${row.key}`" :key="row.key" class="section-card wage-line wage-change-line">
          <h3>{{ rowTitle(row) }}</h3>
          <p class="muted">原工价 {{ row.previous_price === null ? '—' : `${displayQuantity(row.previous_price)} 元/次` }}</p>
          <label v-if="row.status === 'ACTIVE'" class="wage-inline-field wage-price">
            <span>新工价</span>
            <span class="wage-money-input">
              <input v-model="row.declared_price" inputmode="decimal" placeholder="输入新工价" :disabled="locked" @input="rowError = undefined">
              <small>元/次</small>
            </span>
          </label>
          <p v-else class="muted">已作废</p>
          <p v-if="rowError?.key === row.key" class="wage-error" role="alert">{{ rowError.message }}</p>
        </article>
      </div>
      <template v-else-if="options">
        <WageOptionPicker v-if="options.requires_product_name && (productNames.length > 1 || !productNames.includes(productName))"
          class="section-card wage-product-choice" label="工序品名" :model-value="productName" :choices="productChoices" :disabled="locked"
          @update:model-value="changeProductName" />
        <div v-if="!options.requires_product_name || productName" class="wage-lines">
          <article v-for="(row, index) in rows" :id="`wage-row-${row.key}`" :key="row.key" class="wage-line">
            <div v-if="editingRowKey === row.key" class="section-card wage-line-edit" @input="rowError = undefined">
              <div class="wage-line-heading">
                <h3>填写第 {{ index + 1 }} 道工序</h3>
                <button v-if="rows.length > 1 || saved" type="button" class="action-link" :disabled="locked" @click="removeRow(row.key)">删除这道</button>
              </div>
              <WageOptionPicker v-if="bom && (bom.length !== 1 || !row.bom_line_id)" class="wage-line-choice"
                label="部位" :model-value="row.bom_line_id" :choices="partChoices" :disabled="locked"
                @update:model-value="value => { row.bom_line_id = value; rowError = undefined }" />
              <div v-else-if="partFor(row)" class="wage-inline-field wage-fixed-part">
                <span>部位</span>
                <strong>{{ partFor(row)?.name }}</strong>
              </div>
              <WageOptionPicker class="wage-line-choice" label="工序" :model-value="row.operation_id" :choices="operationChoices" :disabled="locked"
                @update:model-value="value => { row.operation_id = value; rowError = undefined }" />
              <label class="wage-inline-field wage-price">
                <span>每次工价</span>
                <span class="wage-money-input">
                  <input v-model="row.declared_price" inputmode="decimal" placeholder="输入金额" :disabled="locked">
                  <small>元/次</small>
                </span>
              </label>
              <p v-if="requiredQuantity(row)" class="muted wage-quantity">
                需做 {{ requiredQuantity(row) }} {{ operationFor(row)?.unit || '次' }}
              </p>
              <p v-if="row.status === 'VOID'" class="muted">这道工序已作废</p>
              <p v-if="rowError?.key === row.key" class="wage-error" role="alert">{{ rowError.message }}</p>
              <p v-else-if="partFor(row)?.problem" class="wage-error">{{ partFor(row)?.problem }}</p>
              <button v-if="row.bom_line_id && row.operation_id && unusedOperations(row.bom_line_id).length" type="button" class="action-link wage-same-part" :disabled="locked" @click="addNextRow(row.bom_line_id)">
                同部位再加一道
              </button>
              <details class="wage-more">
                <summary>补充信息（选填）</summary>
                <div class="wage-optional">
                  <label v-if="!bom" class="wage-field"><span>部位名称</span><input v-model="row.display_name" maxlength="200" :disabled="locked"></label>
                  <label class="wage-field"><span>怎么做</span><input v-model="row.production_description" maxlength="500" :disabled="locked"></label>
                  <label class="wage-field"><span>以往工价</span><input v-model="row.previous_price" inputmode="decimal" :disabled="locked"></label>
                  <label class="wage-field"><span>修改工价</span><input v-model="row.revised_price" inputmode="decimal" :disabled="locked"></label>
                  <label class="wage-field"><span>这道工序的备注</span><input v-model="row.note" maxlength="500" :disabled="locked"></label>
                </div>
              </details>
            </div>
            <button v-else type="button" class="wage-line-brief" :disabled="saving" @click="openRow(row.key)">
              <strong>{{ rowTitle(row) }}</strong>
              <span class="wage-line-amount">
                {{ row.status === 'VOID' ? '已作废' : pricePattern.test(row.declared_price.trim()) ? `${row.declared_price.trim()} 元/次` : '待填工价' }}
              </span>
              <span class="wage-brief-action">{{ locked ? '查看' : '修改' }}</span>
            </button>
          </article>
          <VanButton class="wage-add-row" block plain type="primary" :disabled="locked" @click="addNextRow()">
            {{ rows.length ? '再加一道工序' : '添加工序' }}
          </VanButton>
          <details class="section-card wage-more">
            <summary>方案备注</summary>
            <textarea v-model="remark" aria-label="方案备注" maxlength="2000" rows="3" :disabled="locked" />
          </details>
        </div>
      </template>
      <p v-if="submitError" class="error-panel" role="alert">{{ submitError }}</p>
    </div>
    <template v-if="ready && !loading && !loadError && !missingSetup" #footer>
      <VanButton block type="primary" :loading="saving" @click="submit">
        {{ checkNewScheme ? '核对并重试提交' : '提交厂长审批' }}
      </VanButton>
    </template>
  </WorkPage>
</template>

<style scoped>
.wage-form-page.has-footer :deep(.work-content) { padding-bottom: calc(88px + env(safe-area-inset-bottom)); }
.wage-form-page :deep(.work-heading h1) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wage-editor, .wage-lines, .wage-line-edit, .wage-optional { display: grid; gap: 10px; min-width: 0; }
.wage-summary, .wage-line { overflow-wrap: anywhere; }
.wage-summary { padding-block: 12px; }
.wage-summary h2 { margin: 0 0 6px; font-size: 17px; }
.wage-editor p { margin: 0; }
.wage-summary p + p { margin-top: 4px; }
.wage-loading { padding: 26px 0; }
.wage-line { min-width: 0; scroll-margin: 72px 0 88px; }
.wage-change-line { display: grid; gap: 5px; padding-block: 12px; }
.wage-change-line h3 { margin: 0; font-size: 16px; }
.wage-line-edit { border: 1px solid var(--mobile-border); padding-block: 12px; }
.wage-line-heading { min-height: 36px; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.wage-line-heading h3 { margin: 0; font-size: 17px; }
.wage-line-heading .action-link { flex: none; }
.wage-line-brief {
  width: 100%; min-height: 54px; display: grid; grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--mobile-border);
  border-radius: 10px; background: var(--mobile-surface); text-align: left; color: inherit; font: inherit; cursor: pointer;
}
.wage-line-amount { max-width: min(32vw, 11rem); text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; }
.wage-brief-action { color: var(--mobile-primary); font-size: 14px; white-space: nowrap; }
.wage-inline-field { display: grid; grid-template-columns: 4.25em minmax(0, 1fr); align-items: center; gap: 8px; min-width: 0; }
.wage-inline-field > span:first-child { font-weight: 600; }
.wage-fixed-part { min-height: 28px; }
.wage-product-choice { padding-block: 4px; }
.wage-line-choice { border-bottom: 1px solid var(--mobile-border); }
.wage-field { display: grid; gap: 5px; font-weight: 600; min-width: 0; }
.wage-field input, .wage-price input, .wage-more textarea {
  min-width: 0; width: 100%; min-height: 44px; border: 1px solid var(--mobile-border); border-radius: 8px;
  padding: 8px 10px; background: var(--mobile-surface); color: inherit; font: inherit; font-size: 16px;
}
.wage-money-input { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: center; }
.wage-price input { border-color: var(--mobile-primary); font-variant-numeric: tabular-nums; }
.wage-money-input small, .wage-quantity { color: var(--mobile-muted); font-size: 14px; }
.wage-more summary { min-height: 44px; align-content: center; cursor: pointer; color: var(--mobile-muted); }
.wage-more textarea { margin-top: 6px; resize: vertical; }
.wage-same-part { justify-self: start; padding-inline: 0; }
.wage-error { color: #a32b2b; font-size: 14px; }
</style>
