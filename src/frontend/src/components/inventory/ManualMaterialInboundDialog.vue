<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { isCancel } from 'axios'
import { Calendar, Plus, Refresh } from '@element-plus/icons-vue'
import { useIdentityOwnedStorage } from '@/composables/useIdentityOwnedStorage'
import { pipeMeters, pipeRootError } from '@/utils/pipeQuantities'
import SampleCatalogSelection from '@/components/samples/SampleCatalogSelection.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { sampleMaterialCategories, type SampleMaterialLine } from '@/types/sampleMaterial'
import type { MaterialCatalog } from '@/types/materialCatalog'
import type { ManualMaterialOption, ManualMaterialOptions, ManualMaterialReceivingPayload, MaterialReceivingOptions } from '@/types/inventory'
import { createManualMaterialReceipt, fetchManualMaterialOptions, fetchMaterialReceivingOptions } from '@/api/inventory'
import { useAuthStore } from '@/stores/auth'

interface InboundRow {
  key: string
  categoryId: string
  rawMaterialId: string
  warehouseId: string
  zoneId: string
  quantity: string
  rawLength: string
  weight: string
  selection: SampleMaterialLine
  loadedCatalogId: string
}
const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
const emit = defineEmits<{ close: []; saved: [] }>()
const auth = useAuthStore()
const canReceive = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.receive_material'))
const loading = ref(false), submitting = ref(false), completed = ref(false)
const manualOptions = ref<ManualMaterialOptions>({ categories: [], materials: [] })
const inventoryOptions = ref<MaterialReceivingOptions>({ warehouses: [], zones: [] })
const form = reactive({ inboundDate: localToday(), remark: '' })
const rows = ref<InboundRow[]>([createRow()])
const activeRowKey = ref('')
const activeRow = computed(() => rows.value.find(row => row.key === activeRowKey.value))
// 只挂载当前行的选料器，避免每一行重复加载完整目录。
const activeRows = computed(() => activeRow.value ? [activeRow.value] : [])
const manualRequestStorageKey = 'manual-material-inbound-request-id'
const owned = useIdentityOwnedStorage({ storage: 'session', key: manualRequestStorageKey, legacyKeys: [manualRequestStorageKey] })
const storageError = ref(''), submitError = ref('')
const pending = ref<ManualMaterialReceivingPayload | null>(null)
const rejected = ref(false)
let pendingRaw: string | null = null
const canEdit = computed(() => owned.isCurrent() && canReceive.value && !loading.value && !submitting.value && !completed.value && !pending.value && !storageError.value)

function createRequestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, character => {
    const value = Math.floor(Math.random() * 16)
    return (character === 'x' ? value : (value & 0x3) | 0x8).toString(16)
  })
}
function createRow(): InboundRow {
  const key = createRequestId()
  return { key, categoryId: '', rawMaterialId: '', warehouseId: '', zoneId: '', quantity: '', rawLength: '', weight: '', loadedCatalogId: '',
    selection: { key, category: 'tube', name: '', specification: '', material: '', color: '', quantity: '', unitId: '', unitLabel: '', notes: '' } }
}
function localToday() { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()) }
function checkStorage(): boolean {
  if (!owned.isCurrent()) { storageError.value = '身份尚未核验或已变化，请核验身份后重新打开弹窗。'; return false }
  try {
    if (owned.legacyExists()) { storageError.value = '发现历史无主待核对编号，已原样隔离保留并暂停新提交。请联系管理员人工核对，不能认领或删除后重试。'; return false }
    return !storageError.value
  } catch { storageError.value = '浏览器无法读取待核对记录，已暂停提交，请联系管理员人工核对。'; return false }
}
function restorePending() {
  if (!checkStorage()) return
  try {
    const raw = owned.read()
    if (raw === null) return
    const saved = JSON.parse(raw), payload = saved?.payload
    if (!payload || !Array.isArray(payload.items) || payload.items.length < 1 || payload.items.length > 100
      || ![payload.client_request_id, payload.inbound_date].every(value => typeof value === 'string' && value.length > 0)
      || typeof payload.remark !== 'string'
      || !payload.items.every((item: Record<string, unknown> | null) => item
        && [item.material_catalog_id || item.raw_material_id, item.zone_id].every(value => typeof value === 'string' && value.length > 0)
        && ['string', 'number'].includes(typeof (item.received_bar_count ?? item.received_quantity)))) throw Error('invalid pending')
    // 历史单行仅适配显示；原始 payload 和存储字符串不改写，重试仍使用原请求。
    pending.value = payload; pendingRaw = raw
    rows.value = pending.value!.items.map((item, index) => {
      const row = createRow()
      const selection = saved.rows?.[index]?.selection ?? (index === 0 ? saved.selection : undefined)
      if (item.material_catalog_id && selection?.material_catalog_id === item.material_catalog_id
        && sampleMaterialCategories.some(category => category.key === selection.category)) {
        row.selection = { ...row.selection, ...selection, key: row.key, material_selection: JSON.parse(JSON.stringify(item.material_selection ?? null)) }
        row.categoryId = selection.category
        row.loadedCatalogId = item.material_catalog_id
      }
      row.rawMaterialId = item.raw_material_id || ''; row.zoneId = item.zone_id
      row.quantity = String(item.received_bar_count ?? item.received_quantity ?? '')
      row.rawLength = String(item.raw_bar_length_m ?? '')
      row.weight = String(item.received_weight_kg ?? '')
      return row
    })
    form.inboundDate = payload.inbound_date; form.remark = payload.remark
  } catch { storageError.value = '本地待核对请求记录无法读取，已保留并暂停提交，请联系管理员人工核对。' }
}
function selectedMaterial(row: InboundRow): ManualMaterialOption | undefined {
  return row.selection.material_catalog_id ? {
    id: row.selection.material_catalog_id, material_number: '', material_name: row.selection.name,
    specification: row.selection.specification, material: row.selection.material, color_name: row.selection.color,
    unit_name: row.selection.unitLabel || '', category_id: row.categoryId,
    category_name: row.selection.category === 'tube' ? '管材' : '',
  } : manualOptions.value.materials.find(item => item.id === row.rawMaterialId)
}
function zonesFor(row: InboundRow) { return inventoryOptions.value.zones.filter(item => item.warehouse === row.warehouseId) }
function isPipe(row: InboundRow) { return row.selection.material_catalog_id ? row.selection.category === 'tube' : selectedMaterial(row)?.category_name === '管材' }
function rowError(row: InboundRow): string {
  if (!row.categoryId || !row.selection.material_catalog_id || !row.selection.material_selection || !row.selection.specification || !row.selection.unitLabel) return '请选择材料并补全规格和单位'
  if (isPipe(row) && row.selection.unitLabel !== '根') return '管材须按根入库'
  if (!inventoryOptions.value.warehouses.some(item => item.id === row.warehouseId) || !zonesFor(row).some(item => item.id === row.zoneId)) return '请选择材料仓和库区'
  if (isPipe(row)) return pipeRootError(row.quantity)
    || (Number(pipeMeters(row.quantity, row.rawLength)) > 0 ? '' : '请填写大于 0、最多两位小数的单根长度')
    || (/^\d{1,14}(\.\d{1,4})?$/.test(row.weight) && Number(row.weight) > 0 ? '' : '请填写实际入库重量，大于 0 且最多四位小数')
  return /^\d{1,14}(\.\d{1,4})?$/.test(row.quantity) && Number(row.quantity) > 0 ? '' : '数量须大于 0，最多四位小数'
}
const firstRowError = computed(() => {
  const index = rows.value.findIndex(row => rowError(row))
  return index < 0 ? '' : `第 ${index + 1} 行：${rowError(rows.value[index]!)}`
})
const ready = computed(() => owned.isCurrent() && !storageError.value && canReceive.value && !loading.value && !submitting.value && !completed.value
  && (!!pending.value || (rows.value.length >= 1 && rows.value.length <= 100 && !firstRowError.value
    && /^\d{4}-\d{2}-\d{2}$/.test(form.inboundDate) && form.inboundDate <= localToday() && !!form.remark.trim())))
watch(() => rows.value.map(row => ({ key: row.key, catalogId: row.selection.material_catalog_id, unitId: row.selection.unitId, unitLabel: row.selection.unitLabel })), (current, previous) => {
  if (pending.value) return
  const previousByKey = new Map(previous.map(row => [row.key, row]))
  for (const item of current) {
    const before = previousByKey.get(item.key)
    if (before && (before.catalogId || before.unitId || before.unitLabel)
      && (item.catalogId !== before.catalogId || item.unitId !== before.unitId || item.unitLabel !== before.unitLabel)) {
      const row = rows.value.find(row => row.key === item.key)!
      row.quantity = ''; row.rawLength = ''; row.weight = ''
    }
  }
})
function addRow() { if (canEdit.value && rows.value.length < 100) rows.value.push(createRow()) }
function removeRow(key: string) {
  if (!canEdit.value || rows.value.length <= 1) return
  rows.value = rows.value.filter(row => row.key !== key)
  if (activeRowKey.value === key) activeRowKey.value = ''
}
function categoryChanged(row: InboundRow) {
  if (!canEdit.value) return
  row.rawMaterialId = ''; row.quantity = ''; row.rawLength = ''; row.weight = ''; row.loadedCatalogId = ''; row.warehouseId = ''; row.zoneId = ''
  row.selection = { ...createRow().selection, key: row.key, category: row.categoryId as SampleMaterialLine['category'] }
  if (activeRowKey.value === row.key) activeRowKey.value = ''
}
function openSelection(row: InboundRow) { if (canEdit.value && row.categoryId) activeRowKey.value = row.key }
function updateSelection(value: SampleMaterialLine, key = activeRowKey.value) {
  if (!canEdit.value || key !== activeRowKey.value) return
  const row = rows.value.find(row => row.key === key)
  if (row) row.selection = { ...value, key }
}
function catalogLoaded(catalog: MaterialCatalog, key = activeRowKey.value) {
  const row = rows.value.find(row => row.key === key)
  if (!canEdit.value || key !== activeRowKey.value || !row || row.loadedCatalogId === catalog.id) return
  row.loadedCatalogId = catalog.id
  row.warehouseId = inventoryOptions.value.warehouses.some(item => item.id === catalog.base_warehouse_id) ? catalog.base_warehouse_id! : ''
  warehouseChanged(row)
}
function warehouseChanged(row: InboundRow) {
  if (!canEdit.value) return
  const zones = zonesFor(row)
  row.zoneId = zones.length === 1 ? zones[0]!.id : ''
}
function firstErrorText(value: unknown): string {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') {
    for (const item of Object.values(value)) {
      const message = firstErrorText(item)
      if (message) return message
    }
  }
  return ''
}
function apiMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, unknown> }; detail?: string } } })?.response
  const fields = response?.data?.error?.field_errors
  if (Array.isArray(fields?.items)) {
    for (const [index, item] of fields.items.entries()) {
      const message = firstErrorText(item)
      if (message && item && typeof item === 'object') return `第 ${index + 1} 行：${message}`
    }
  }
  return firstErrorText(fields) || response?.data?.error?.message || response?.data?.detail || fallback
}
async function loadBase() {
  if (!checkStorage() || submitting.value || loading.value) return
  loading.value = true
  try {
    owned.assertCurrent()
    const warehouseData = await fetchMaterialReceivingOptions()
    owned.assertCurrent()
    // 共用收货选项也包含半成品仓；一般入库只允许材料仓。
    const warehouses = warehouseData.warehouses.filter(item => !item.warehouse_type || item.warehouse_type === 'MATERIAL')
    const warehouseIds = new Set(warehouses.map(item => item.id))
    inventoryOptions.value = { warehouses, zones: warehouseData.zones.filter(item => warehouseIds.has(item.warehouse)) }
    if (pending.value?.items.some(item => item.raw_material_id)) {
      const options = await fetchManualMaterialOptions()
      owned.assertCurrent(); manualOptions.value = options
    }
    if (pending.value) rows.value.forEach(row => { row.warehouseId = warehouseData.zones.find(item => item.id === row.zoneId)?.warehouse || '' })
  } catch (error) { if (!isCancel(error) && owned.isCurrent()) ElMessage.error(apiMessage(error, '额外材料入库资料加载失败。')) }
  finally { if (owned.isCurrent()) loading.value = false }
}
async function submit() {
  if (!checkStorage() || submitting.value || completed.value) return
  if (!ready.value) return ElMessage.warning(firstRowError.value || '请完整填写入库日期和备注。')
  if (!pending.value) {
    try {
      if (owned.read() !== null) throw Error('existing pending')
      const payload: ManualMaterialReceivingPayload = {
        client_request_id: createRequestId(), inbound_date: form.inboundDate, remark: form.remark.trim(),
        items: rows.value.map(row => ({ material_catalog_id: row.selection.material_catalog_id!, material_selection: row.selection.material_selection!,
          zone_id: row.zoneId, ...(isPipe(row) ? { received_bar_count: row.quantity, raw_bar_length_m: row.rawLength, received_weight_kg: row.weight } : { received_quantity: row.quantity }) })),
      }
      const raw = JSON.stringify({ payload, rows: rows.value })
      owned.write(raw); pendingRaw = raw
      // 与可编辑行彻底分离，后续重放不读取表单或重新生成材料快照。
      pending.value = JSON.parse(raw).payload; activeRowKey.value = ''
    } catch { storageError.value = '无法保存原请求或已有待核对记录，本次尚未提交，请重新打开弹窗核对。'; return }
  }
  submitting.value = true; submitError.value = ''; rejected.value = false
  try {
    owned.assertCurrent()
    if (owned.read() !== pendingRaw) { storageError.value = '待核对记录已变化，请重新打开弹窗并联系管理员人工核对。'; return }
    const inbound = await createManualMaterialReceipt(pending.value!)
    owned.assertCurrent(); completed.value = true
    if (pendingRaw === null || !owned.removeIfUnchanged(pendingRaw)) { storageError.value = '入库已成功，但待核对记录已变化，已保留记录，请联系管理员人工核对。'; return }
    pending.value = null; pendingRaw = null
    ElMessage.success(`材料已入库，入库单号 ${inbound.inbound_number}`); emit('saved')
  } catch (error) {
    if (isCancel(error) || !owned.isCurrent()) return
    const status = (error as { response?: { status?: number } }).response?.status
    rejected.value = pending.value!.items.every(item => !!item.material_catalog_id) && [400, 412, 428].includes(status || 0)
    submitError.value = apiMessage(error, rejected.value ? '本次入库未提交成功，请修改被拒绝的内容后重试。' : '额外材料入库结果尚未确认，请使用原请求核对，暂勿另建单据。')
    ElMessage.error(submitError.value)
  }
  finally { if (owned.isCurrent()) submitting.value = false }
}
function editRejected() {
  if (!rejected.value || !checkStorage() || pendingRaw === null || submitting.value) return
  try {
    if (!owned.removeIfUnchanged(pendingRaw)) { storageError.value = '待核对记录已变化，请联系管理员人工核对。'; return }
    pending.value = null; pendingRaw = null; rejected.value = false; submitError.value = ''
  } catch { storageError.value = '浏览器无法更新待核对记录，已暂停修改，请联系管理员人工核对。' }
}
onMounted(() => { restorePending(); if (canReceive.value && !storageError.value) void loadBase() })
</script>

<template>
  <AppWindowDialog :model-value="true" title="材料入库" width="1400px" class="manual-inbound-dialog"
    :embedded="props.embedded" :with-header="!props.embedded" :minimizable="!props.embedded"
    :close-on-click-modal="false" :close-on-press-escape="!submitting && !activeRow" :show-close="!submitting"
    @update:model-value="value => { if (!value && !submitting) emit('close') }">
    <header v-if="props.embedded" class="embedded-inbound-heading">
      <div><h1>一般入库</h1><p>填写入库时间和备注后，批量选择材料并保存。</p></div>
    </header>
    <ElAlert v-if="!canReceive" title="无权进行材料入库，请联系管理员开通材料入库权限。" type="warning" :closable="false" />
    <template v-else>
      <ElAlert v-if="storageError" :title="storageError" type="error" :closable="false" show-icon />
      <ElAlert v-else-if="pending" :title="rejected ? '本次提交被明确拒绝，可修改后重新提交。' : '原提交结果尚待核对，已锁定整单内容；再次确认只会使用同一请求编号与原始数据。'" type="warning" :closable="false" show-icon />
      <ElAlert v-if="submitError" :title="submitError" type="error" :closable="false" show-icon />
      <ElButton v-if="rejected" :disabled="submitting" @click="editRejected">修改被拒绝的内容</ElButton>
      <div class="inbound-intro"><p>额外入库，不关联采购单；所有明细一次提交到同一张入库单。</p><ElButton :icon="Refresh" :loading="loading" :disabled="submitting" @click="loadBase">刷新</ElButton></div>
      <ElForm v-loading="loading" label-position="top" :disabled="!canEdit" class="inbound-form">
        <div class="receipt-fields">
          <ElFormItem label="入库日期" required><ElDatePicker v-model="form.inboundDate" aria-label="入库日期" type="date" value-format="YYYY-MM-DD" :prefix-icon="Calendar" :disabled-date="(date: Date) => new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date) > localToday()" /></ElFormItem>
          <ElFormItem label="入库备注" required><ElInput v-model="form.remark" aria-label="入库备注" maxlength="3000" placeholder="请填写额外入库的真实来源或原因" /></ElFormItem>
        </div>
        <div class="inbound-table-scroll">
          <table class="inbound-table" aria-label="材料入库明细">
            <colgroup><col style="width: 44px"><col style="width: 122px"><col style="width: 250px"><col style="width: 80px"><col style="width: 160px"><col style="width: 130px"><col style="width: 126px"><col style="width: 150px"><col style="width: 174px"><col style="width: 60px"></colgroup>
            <thead><tr><th>序号</th><th>品类 *</th><th>材料及规格 *</th><th>单位</th><th>材料仓 *</th><th>库区 *</th><th>入库数量 *</th><th>管材实收重量（kg）*</th><th>管材单根原长</th><th>操作</th></tr></thead>
            <tbody><tr v-for="(row, index) in rows" :key="row.key" :data-row-key="row.key">
              <td>{{ index + 1 }}</td>
              <td><ElSelect v-model="row.categoryId" :aria-label="`第${index + 1}行品类`" placeholder="请选择" @change="categoryChanged(row)"><ElOption v-for="item in sampleMaterialCategories" :key="item.key" :value="item.key" :label="item.label" /></ElSelect></td>
              <td><div class="row-material"><strong>{{ selectedMaterial(row)?.material_name || '尚未选择材料' }}</strong><span v-if="selectedMaterial(row)">{{ [selectedMaterial(row)?.specification, selectedMaterial(row)?.material, selectedMaterial(row)?.color_name].filter(Boolean).join(' · ') }}</span><ElButton link type="primary" :disabled="!row.categoryId || !canEdit" :aria-label="`第${index + 1}行选择材料`" @click="openSelection(row)">{{ selectedMaterial(row) ? '更换 / 修改规格' : '选择材料' }}</ElButton></div></td>
              <td>{{ isPipe(row) ? '根 / kg' : selectedMaterial(row)?.unit_name || '—' }}</td>
              <td><ElSelect v-model="row.warehouseId" :aria-label="`第${index + 1}行材料仓`" placeholder="请选择" @change="warehouseChanged(row)"><ElOption v-for="item in inventoryOptions.warehouses" :key="item.id" :value="item.id" :label="item.warehouse_name" /></ElSelect></td>
              <td><ElSelect v-model="row.zoneId" :aria-label="`第${index + 1}行库区`" :disabled="!row.warehouseId || !canEdit" placeholder="请选择"><ElOption v-for="item in zonesFor(row)" :key="item.id" :value="item.id" :label="item.zone_name" /></ElSelect></td>
              <td><ElInput v-model="row.quantity" :aria-label="`第${index + 1}行${isPipe(row) ? '入库根数' : '入库数量'}`" :inputmode="isPipe(row) ? 'numeric' : 'decimal'" maxlength="19" :placeholder="isPipe(row) ? '正整数根数' : '大于 0'" /></td>
              <td><ElInput v-if="isPipe(row)" v-model="row.weight" :aria-label="`第${index + 1}行实收重量`" inputmode="decimal" maxlength="19" placeholder="实际公斤数" /><span v-else>—</span></td>
              <td><ElInput v-if="isPipe(row)" v-model="row.rawLength" :aria-label="`第${index + 1}行单根长度`" inputmode="decimal" maxlength="17" placeholder="最多两位小数"><template #append>米/根</template></ElInput><span v-else>—</span></td>
              <td><ElButton link type="danger" :disabled="rows.length <= 1 || !canEdit" :aria-label="`删除第${index + 1}行`" @click="removeRow(row.key)">删除</ElButton></td>
            </tr></tbody>
          </table>
        </div>
        <div class="inbound-table-actions"><ElButton :icon="Plus" :disabled="!canEdit || rows.length >= 100" @click="addRow">添加一行</ElButton><span>{{ rows.length }} / 100 条</span><span v-if="!pending && firstRowError" class="row-validation">{{ firstRowError }}</span></div>
      </ElForm>
    </template>
    <template #footer>
      <ElButton :disabled="submitting" @click="emit('close')">取消</ElButton>
      <ElButton v-if="canReceive" type="primary" :loading="submitting" :disabled="!ready" @click="submit">{{ pending ? '核对本次提交' : '确认入库' }}</ElButton>
    </template>
  </AppWindowDialog>
  <AppWindowDialog v-for="row in activeRows" :key="row.key" :model-value="true" :title="`选择材料 · 第 ${rows.indexOf(row) + 1} 行`" width="1000px" :close-on-click-modal="false" @update:model-value="value => { if (!value) activeRowKey = '' }">
    <SampleCatalogSelection source="inventory" :model-value="row.selection" :disabled="!canEdit" @update:model-value="value => updateSelection(value, row.key)" @loaded="catalog => catalogLoaded(catalog, row.key)" />
    <template #footer><ElButton type="primary" @click="activeRowKey = ''">完成选料</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.embedded-inbound-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.embedded-inbound-heading h1 { margin: 0; color: var(--erp-color-text-primary); font-size: 22px; }
.embedded-inbound-heading p { margin: 6px 0 0; color: var(--erp-color-text-secondary); font-size: 13px; }
.inbound-intro, .inbound-table-actions { display: flex; align-items: center; gap: 12px; }
.inbound-intro { justify-content: space-between; margin: 12px 0; }
.inbound-intro p, .inbound-table-actions { margin: 0; color: var(--erp-color-text-secondary); font-size: 13px; }
.receipt-fields { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 16px; }
.inbound-form :deep(.el-form-item) { min-width: 0; margin-bottom: 12px; }
.inbound-form :deep(.el-select), .inbound-form :deep(.el-date-editor) { width: 100%; }
.inbound-table-scroll { overflow: auto; border: 1px solid var(--erp-color-border); border-radius: var(--erp-radius-control); }
.inbound-table { border-collapse: separate; border-spacing: 0; width: 100%; min-width: 1396px; table-layout: fixed; font-size: 13px; }
.inbound-table th, .inbound-table td { padding: 8px; text-align: left; vertical-align: middle; border-bottom: 1px solid var(--erp-color-border); overflow-wrap: anywhere; }
.inbound-table th { position: sticky; top: 0; z-index: 1; background: var(--erp-color-subtle); color: var(--erp-color-text-secondary); font-weight: 500; white-space: nowrap; }
.inbound-table tbody tr:last-child td { border-bottom: 0; }
.row-material { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; }
.row-material strong { font-weight: 500; }
.row-material span { color: var(--erp-color-text-secondary); font-size: 12px; }
.inbound-table :deep(.el-input-group__append) { padding: 0 6px; }
.inbound-table-actions { flex-wrap: wrap; margin-top: 12px; }
.row-validation { margin-left: auto; }
@media (max-width: 600px) { .receipt-fields { grid-template-columns: minmax(0, 1fr); gap: 0; } }
</style>
