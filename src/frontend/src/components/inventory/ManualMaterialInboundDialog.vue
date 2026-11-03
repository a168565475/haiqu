<script setup lang="ts">
import { pipeMeters, pipeRootError } from '@/utils/pipeQuantities'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { isCancel } from 'axios'
import { useIdentityOwnedStorage } from '@/composables/useIdentityOwnedStorage'
import { Calendar, Refresh } from '@element-plus/icons-vue'
import SampleCatalogSelection from '@/components/samples/SampleCatalogSelection.vue'
import { sampleMaterialCategories, type SampleMaterialLine } from '@/types/sampleMaterial'
import type { MaterialCatalog } from '@/types/materialCatalog'

import { createManualMaterialReceipt, fetchManualMaterialOptions, fetchMaterialReceivingOptions } from '@/api/inventory'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { ManualMaterialOption, ManualMaterialOptions, MaterialReceivingOptions } from '@/types/inventory'

const emit = defineEmits<{ close: []; saved: [] }>()
const auth = useAuthStore()
const canReceive = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.receive_material'))
const loading = ref(false)
const submitting = ref(false)
const completed = ref(false)
const manualOptions = ref<ManualMaterialOptions>({ categories: [], materials: [] })
const inventoryOptions = ref<MaterialReceivingOptions>({ warehouses: [], zones: [] })
const form = reactive({ categoryId: '', rawMaterialId: '', warehouseId: '', zoneId: '', quantity: '', rawLength: '', inboundDate: localToday(), remark: '' })
const selectionRow = ref<SampleMaterialLine>({ key: 'manual', category: 'tube', name: '', specification: '', material: '', color: '', quantity: '', unitId: '', unitLabel: '', notes: '' })
let loadedCatalogId = ''

const manualRequestStorageKey = 'manual-material-inbound-request-id'
function createRequestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, character => {
    const value = Math.floor(Math.random() * 16)
    return (character === 'x' ? value : (value & 0x3) | 0x8).toString(16)
  })
}
const owned = useIdentityOwnedStorage({ storage: 'session', key: manualRequestStorageKey, legacyKeys: [manualRequestStorageKey] })
const storageError = ref('')
const pending = ref<Record<string, unknown> | null>(null)
const rejected = ref(false)
let pendingRaw: string | null = null
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
    const saved = JSON.parse(raw)
    const payload = saved?.payload, item = payload?.items?.[0]
    if (!payload || !Array.isArray(payload.items) || payload.items.length !== 1 || !item
      || ![payload.client_request_id, payload.inbound_date, item.material_catalog_id || item.raw_material_id, item.zone_id].every(value => typeof value === 'string' && value.length > 0)
      || typeof payload.remark !== 'string'
      || !['string', 'number'].includes(typeof (item.received_bar_count ?? item.received_quantity))) throw Error('invalid pending')
    pending.value = payload; pendingRaw = raw
    if (item.material_catalog_id && saved.selection) {
      selectionRow.value = saved.selection
      form.categoryId = saved.selection.category
      loadedCatalogId = saved.selection.material_catalog_id
    }
    form.rawMaterialId = item.raw_material_id || ''
    form.zoneId = item.zone_id
    form.quantity = String(item.received_bar_count ?? item.received_quantity ?? '')
    form.rawLength = String(item.raw_bar_length_m ?? '')
    form.inboundDate = saved.payload.inbound_date; form.remark = saved.payload.remark
  } catch { storageError.value = '本地待核对请求记录无法读取，已保留并暂停提交，请联系管理员人工核对。' }
}

function localToday() { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()) }
const selectedMaterial = computed<ManualMaterialOption | undefined>(() => selectionRow.value.material_catalog_id ? {
  id: selectionRow.value.material_catalog_id, material_number: '', material_name: selectionRow.value.name,
  specification: selectionRow.value.specification, material: selectionRow.value.material, color_name: selectionRow.value.color,
  unit_name: selectionRow.value.unitLabel || '', category_id: form.categoryId,
  category_name: selectionRow.value.category === 'tube' ? '管材' : '',
} : manualOptions.value.materials.find(item => item.id === form.rawMaterialId))
const zones = computed(() => inventoryOptions.value.zones.filter(item => item.warehouse === form.warehouseId))
const isPipe = computed(() => selectedMaterial.value?.category_name === '管材')
const validQuantity = computed(() => isPipe.value ? !pipeRootError(form.quantity) && Number(pipeMeters(form.quantity, form.rawLength)) > 0 : /^\d{1,14}(\.\d{1,4})?$/.test(form.quantity) && Number(form.quantity) > 0)
const ready = computed(() => owned.isCurrent() && !storageError.value && canReceive.value && !loading.value && !submitting.value && !completed.value && (!!pending.value || (!!selectedMaterial.value
  && !!selectionRow.value.material_selection && !!selectionRow.value.specification && !!selectionRow.value.unitLabel
  && (!isPipe.value || selectedMaterial.value?.unit_name === '根')
  && inventoryOptions.value.warehouses.some(item => item.id === form.warehouseId)
  && zones.value.some(item => item.id === form.zoneId)
  && validQuantity.value && /^\d{4}-\d{2}-\d{2}$/.test(form.inboundDate)
  && form.inboundDate <= localToday() && !!form.remark.trim())))
watch(() => [selectionRow.value.unitId, selectionRow.value.unitLabel], (current, previous) => {
  if (!pending.value && previous.some(Boolean) && current.some((value, index) => value !== previous[index])) {
    form.quantity = ''; form.rawLength = ''
  }
})

function apiMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  const field = response?.data?.error?.field_errors ? Object.values(response.data.error.field_errors).flat()[0] : ''
  return field || response?.data?.error?.message || response?.data?.detail || fallback
}
async function loadBase() {
  if (!checkStorage()) return
  loading.value = true
  try {
    owned.assertCurrent()
    const warehouseData = await fetchMaterialReceivingOptions()
    owned.assertCurrent()
    inventoryOptions.value = warehouseData
    if (pending.value && !(pending.value.items as Array<Record<string, unknown>> | undefined)?.[0]?.material_catalog_id) manualOptions.value = await fetchManualMaterialOptions()
    if (pending.value) form.warehouseId = warehouseData.zones.find(item => item.id === form.zoneId)?.warehouse || ''
  } catch (error) { if (!isCancel(error) && owned.isCurrent()) ElMessage.error(apiMessage(error, '额外材料入库资料加载失败。')) }
  finally { if (owned.isCurrent()) loading.value = false }
}
function categoryChanged() {
  if (pending.value) return
  form.rawMaterialId = ''; form.quantity = ''; form.rawLength = ''; loadedCatalogId = ''
  selectionRow.value = { key: createRequestId(), category: form.categoryId as SampleMaterialLine['category'], name: '', specification: '', material: '', color: '', quantity: '', unitId: '', unitLabel: '', notes: '' }
}
function catalogLoaded(catalog: MaterialCatalog) {
  if (pending.value || loadedCatalogId === catalog.id) return
  loadedCatalogId = catalog.id
  form.warehouseId = inventoryOptions.value.warehouses.some(item => item.id === catalog.base_warehouse_id) ? catalog.base_warehouse_id! : ''
  warehouseChanged()
}
function warehouseChanged() { form.zoneId = zones.value.length === 1 ? zones.value[0].id : '' }
async function submit() {
  if (!checkStorage()) return
  if (!ready.value) return ElMessage.warning('请完整填写原料、仓库、库区、数量、入库日期和备注。')
  if (!pending.value) {
    try {
      if (owned.read() !== null) throw Error('existing pending')
      const payload = {
        client_request_id: createRequestId(), inbound_date: form.inboundDate, remark: form.remark.trim(),
        items: [{ material_catalog_id: selectionRow.value.material_catalog_id, material_selection: selectionRow.value.material_selection,
          zone_id: form.zoneId, ...(isPipe.value ? { received_bar_count: form.quantity, raw_bar_length_m: form.rawLength } : { received_quantity: form.quantity }) }],
      }
      const raw = JSON.stringify({ payload, selection: selectionRow.value }); owned.write(raw); pendingRaw = raw; pending.value = payload
    } catch { storageError.value = '无法保存原请求或已有待核对记录，本次尚未提交，请重新打开弹窗核对。'; return }
  }
  submitting.value = true
  try {
    owned.assertCurrent()
    if (owned.read() !== pendingRaw) { storageError.value = '待核对记录已变化，请重新打开弹窗并联系管理员人工核对。'; return }
    const inbound = await createManualMaterialReceipt(pending.value!)
    owned.assertCurrent()
    completed.value = true
    if (pendingRaw === null || !owned.removeIfUnchanged(pendingRaw)) { storageError.value = '入库已成功，但待核对记录已变化，已保留记录，请联系管理员人工核对。'; return }
    pending.value = null; pendingRaw = null
    ElMessage.success(`材料已入库，入库单号 ${inbound.inbound_number}`)
    emit('saved')
  } catch (error) {
    if (isCancel(error) || !owned.isCurrent()) return
    const status = (error as { response?: { status?: number } }).response?.status
    rejected.value = !!selectionRow.value.material_catalog_id && [400, 412, 428].includes(status || 0)
    ElMessage.error(apiMessage(error, '额外材料入库结果尚未确认，请使用原请求核对，暂勿另建单据。'))
  }
  finally { if (owned.isCurrent()) submitting.value = false }
}
function editRejected() {
  if (!rejected.value || !checkStorage() || pendingRaw === null || submitting.value) return
  if (!owned.removeIfUnchanged(pendingRaw)) { storageError.value = '待核对记录已变化，请联系管理员人工核对。'; return }
  pending.value = null; pendingRaw = null; rejected.value = false
}

onMounted(() => { restorePending(); if (canReceive.value && !storageError.value) void loadBase() })
</script>

<template>
  <AppWindowDialog :model-value="true" title="材料入库" width="800px" class="manual-inbound-dialog"
    :close-on-click-modal="false" :close-on-press-escape="!submitting" :show-close="!submitting"
    @update:model-value="value => { if (!value && !submitting) emit('close') }">
    <ElAlert v-if="!canReceive" title="无权进行材料入库，请联系管理员开通材料入库权限。" type="warning" :closable="false" />
    <template v-else>
      <ElAlert v-if="storageError" :title="storageError" type="error" :closable="false" show-icon />
      <ElAlert v-else-if="pending" title="原提交结果尚待核对，已锁定原始内容；再次确认只会使用同一请求编号与原始数据。" type="warning" :closable="false" show-icon />
      <ElButton v-if="rejected" :disabled="submitting" @click="editRejected">修改被拒绝的内容</ElButton>
      <div class="inbound-intro"><p>额外入库，不关联采购单；确认后直接计入库存。</p><ElButton :icon="Refresh" :loading="loading" :disabled="submitting" @click="loadBase">刷新</ElButton></div>
      <ElForm v-loading="loading" label-position="top" :disabled="submitting || completed || !!pending || !!storageError || !owned.isCurrent()" class="inbound-form">
        <div class="form-grid">
          <ElFormItem label="品类" required><ElSelect v-model="form.categoryId" aria-label="品类" filterable placeholder="请选择品类" @change="categoryChanged"><ElOption v-for="item in sampleMaterialCategories" :key="item.key" :value="item.key" :label="item.label" /></ElSelect></ElFormItem>
          <ElFormItem label="入库日期" required><ElDatePicker v-model="form.inboundDate" aria-label="入库日期" type="date" value-format="YYYY-MM-DD" :prefix-icon="Calendar" :disabled-date="(date: Date) => new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date) > localToday()" /></ElFormItem>
          <div v-if="form.categoryId && !pending" class="full-row"><SampleCatalogSelection :key="selectionRow.key" v-model="selectionRow" :disabled="submitting || completed || !!storageError" @loaded="catalogLoaded" /></div>
          <dl class="material-summary full-row" aria-live="polite">
            
            <div><dt>原料名称</dt><dd>{{ selectedMaterial?.material_name || '—' }}</dd></div>
            <div><dt>规格</dt><dd>{{ selectedMaterial?.specification || '—' }}</dd></div>
            <div><dt>材质</dt><dd>{{ selectedMaterial?.material || '—' }}</dd></div>
            <div><dt>颜色</dt><dd>{{ selectedMaterial?.color_name || '—' }}</dd></div>
            <div><dt>单位</dt><dd>{{ selectedMaterial?.unit_name || '—' }}</dd></div>
          </dl>
          <ElFormItem label="材料仓" required><ElSelect v-model="form.warehouseId" aria-label="材料仓" placeholder="请选择材料仓" @change="warehouseChanged"><ElOption v-for="item in inventoryOptions.warehouses" :key="item.id" :value="item.id" :label="`${item.warehouse_number} · ${item.warehouse_name}`" /></ElSelect></ElFormItem>
          <ElFormItem label="库区" required><ElSelect v-model="form.zoneId" aria-label="库区" :disabled="!form.warehouseId" placeholder="请选择库区"><ElOption v-for="item in zones" :key="item.id" :value="item.id" :label="item.zone_name" /></ElSelect></ElFormItem>
          <ElFormItem :label="isPipe ? '入库根数' : '入库数量'" required><ElInput v-model="form.quantity" :aria-label="isPipe ? '入库根数' : '入库数量'" :inputmode="isPipe ? 'numeric' : 'decimal'" maxlength="19" :placeholder="isPipe ? '请输入正整数根数' : '大于 0，最多 4 位小数'"><template #append>{{ isPipe ? '根' : selectedMaterial?.unit_name || '单位' }}</template></ElInput></ElFormItem>
          <ElFormItem v-if="isPipe" label="单根长度" required><ElInput v-model="form.rawLength" aria-label="单根长度" inputmode="decimal" placeholder="保留两位小数"><template #append>米/根</template></ElInput></ElFormItem>
          <p v-if="isPipe" class="meter-summary full-row">入库总米数 <strong>{{ pipeMeters(form.quantity, form.rawLength) || '—' }}</strong> 米</p>
          <ElFormItem label="入库备注" required class="full-row"><ElInput v-model="form.remark" aria-label="入库备注" type="textarea" :rows="2" maxlength="3000" show-word-limit placeholder="请填写额外入库的真实来源或原因" /></ElFormItem>
        </div>
      </ElForm>
    </template>
    <template #footer>
      <ElButton :disabled="submitting" @click="emit('close')">取消</ElButton>
      <ElButton v-if="canReceive" type="primary" :loading="submitting" :disabled="!ready" @click="submit">{{ pending ? '核对本次提交' : '确认入库' }}</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.inbound-intro { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.inbound-intro p { margin: 0; color: var(--erp-color-text-secondary); font-size: 13px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 16px; }
.full-row { grid-column: 1 / -1; }
.inbound-form :deep(.el-form-item) { min-width: 0; margin-bottom: 12px; }
.inbound-form :deep(.el-form-item:last-child) { margin-bottom: 0; }
.inbound-form :deep(.el-form-item__label) { height: auto; line-height: 20px; margin-bottom: 0; padding-bottom: 4px; }
.inbound-form :deep(.el-select), .inbound-form :deep(.el-date-editor) { width: 100%; }
.inbound-form :deep(.el-input-group__append) { width: 60px; box-sizing: border-box; padding: 0; }
.material-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px 16px; margin: 0 0 12px; padding: 10px 16px; border-radius: var(--erp-radius-control); background: var(--erp-color-subtle); }
.material-summary div { min-width: 0; }
.material-summary dt { color: var(--erp-color-text-secondary); font-size: 12px; line-height: 16px; }
.material-summary dd { margin: 2px 0 0; font-size: 13px; line-height: 18px; overflow-wrap: anywhere; }
.meter-summary { margin: 0 0 12px; color: var(--erp-color-text-secondary); font-size: 13px; }
.meter-summary strong { margin: 0 6px; color: var(--erp-color-brand); }
@media (max-width: 600px) { .form-grid { grid-template-columns: minmax(0, 1fr); } .material-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>


