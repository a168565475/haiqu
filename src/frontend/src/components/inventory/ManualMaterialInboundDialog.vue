<script setup lang="ts">
import { pipeMeters, pipeRootError } from '@/utils/pipeQuantities'
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Calendar, Refresh } from '@element-plus/icons-vue'

import { createManualMaterialReceipt, fetchManualMaterialOptions, fetchMaterialReceivingOptions } from '@/api/inventory'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { ManualMaterialOption, ManualMaterialOptions, MaterialReceivingOptions } from '@/types/inventory'

const emit = defineEmits<{ close: []; saved: [] }>()
const auth = useAuthStore()
const canReceive = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.receive_material'))
const loading = ref(false)
const materialsLoading = ref(false)
const submitting = ref(false)
const completed = ref(false)
const manualOptions = ref<ManualMaterialOptions>({ categories: [], materials: [] })
const inventoryOptions = ref<MaterialReceivingOptions>({ warehouses: [], zones: [] })
const form = reactive({ categoryId: '', rawMaterialId: '', warehouseId: '', zoneId: '', quantity: '', rawLength: '', inboundDate: localToday(), remark: '' })
let materialRequest = 0

const manualRequestStorageKey = 'manual-material-inbound-request-id'
function createRequestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, character => {
    const value = Math.floor(Math.random() * 16)
    return (character === 'x' ? value : (value & 0x3) | 0x8).toString(16)
  })
}
function loadRequestId(): string {
  try {
    const existing = sessionStorage.getItem(manualRequestStorageKey)
    if (existing) return existing
    const created = createRequestId()
    sessionStorage.setItem(manualRequestStorageKey, created)
    return created
  } catch { return createRequestId() }
}
let clientRequestId = loadRequestId()

function localToday() { return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date()) }
const selectedMaterial = computed<ManualMaterialOption | undefined>(() => manualOptions.value.materials.find(item => item.id === form.rawMaterialId))
const zones = computed(() => inventoryOptions.value.zones.filter(item => item.warehouse === form.warehouseId))
const isPipe = computed(() => selectedMaterial.value?.category_name === '管材')
const validQuantity = computed(() => isPipe.value ? !pipeRootError(form.quantity) && Number(pipeMeters(form.quantity, form.rawLength)) > 0 : /^\d{1,14}(\.\d{1,4})?$/.test(form.quantity) && Number(form.quantity) > 0)
const ready = computed(() => canReceive.value && !loading.value && !submitting.value && !completed.value && !!selectedMaterial.value
  && inventoryOptions.value.warehouses.some(item => item.id === form.warehouseId)
  && zones.value.some(item => item.id === form.zoneId)
  && validQuantity.value && /^\d{4}-\d{2}-\d{2}$/.test(form.inboundDate)
  && form.inboundDate <= localToday() && !!form.remark.trim())

function apiMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  const field = response?.data?.error?.field_errors ? Object.values(response.data.error.field_errors).flat()[0] : ''
  return field || response?.data?.error?.message || response?.data?.detail || fallback
}
async function loadMaterials(keyword = '') {
  const request = ++materialRequest
  materialsLoading.value = true
  try {
    const data = await fetchManualMaterialOptions({ category_id: form.categoryId || undefined, q: keyword.trim() || undefined })
    if (request !== materialRequest) return
    manualOptions.value = data
    if (form.rawMaterialId && !data.materials.some(item => item.id === form.rawMaterialId)) form.rawMaterialId = ''
  } catch (error) { if (request === materialRequest) ElMessage.error(apiMessage(error, '原料资料加载失败。')) }
  finally { if (request === materialRequest) materialsLoading.value = false }
}
async function loadBase() {
  loading.value = true
  try {
    const [warehouseData, materialData] = await Promise.all([fetchMaterialReceivingOptions(), fetchManualMaterialOptions()])
    inventoryOptions.value = warehouseData
    manualOptions.value = materialData
  } catch (error) { ElMessage.error(apiMessage(error, '额外材料入库资料加载失败。')) }
  finally { loading.value = false }
}
function categoryChanged() { form.rawMaterialId = ''; void loadMaterials() }
function warehouseChanged() { form.zoneId = zones.value.length === 1 ? zones.value[0].id : '' }
async function submit() {
  if (!ready.value) return ElMessage.warning('请完整填写原料、仓库、库区、数量、入库日期和备注。')
  submitting.value = true
  try {
    const inbound = await createManualMaterialReceipt({
      client_request_id: clientRequestId,
      inbound_date: form.inboundDate,
      remark: form.remark.trim(),
      items: [{ raw_material_id: form.rawMaterialId, zone_id: form.zoneId, ...(isPipe.value ? { received_bar_count: form.quantity, raw_bar_length_m: form.rawLength } : { received_quantity: form.quantity }) }],
    })
    completed.value = true
    ElMessage.success(`材料已入库，入库单号 ${inbound.inbound_number}`)
    try { sessionStorage.removeItem(manualRequestStorageKey) } catch { /* 已有服务端幂等保护，不影响本次成功结果。 */ }
    emit('saved')
  } catch (error) { ElMessage.error(apiMessage(error, '额外材料入库失败，请核对后重试。')) }
  finally { submitting.value = false }
}

onMounted(() => { if (canReceive.value) void loadBase() })
</script>

<template>
  <AppWindowDialog :model-value="true" title="材料入库" width="800px" class="manual-inbound-dialog"
    :close-on-click-modal="false" :close-on-press-escape="!submitting" :show-close="!submitting"
    @update:model-value="value => { if (!value && !submitting) emit('close') }">
    <ElAlert v-if="!canReceive" title="无权进行材料入库，请联系管理员开通材料入库权限。" type="warning" :closable="false" />
    <template v-else>
      <div class="inbound-intro"><p>额外入库，不关联采购单；确认后直接计入库存。</p><ElButton :icon="Refresh" :loading="loading" :disabled="submitting" @click="loadBase">刷新</ElButton></div>
      <ElForm v-loading="loading" label-position="top" :disabled="submitting || completed" class="inbound-form">
        <div class="form-grid">
          <ElFormItem label="品类" required><ElSelect v-model="form.categoryId" aria-label="品类" filterable placeholder="请选择品类" @change="categoryChanged"><ElOption v-for="item in manualOptions.categories" :key="item.id" :value="item.id" :label="item.name" /></ElSelect></ElFormItem>
          <ElFormItem label="入库日期" required><ElDatePicker v-model="form.inboundDate" aria-label="入库日期" type="date" value-format="YYYY-MM-DD" :prefix-icon="Calendar" :disabled-date="(date: Date) => new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date) > localToday()" /></ElFormItem>
          <ElFormItem label="原料规格" required class="full-row"><ElSelect v-model="form.rawMaterialId" aria-label="原料规格" filterable remote reserve-keyword :remote-method="loadMaterials" :loading="materialsLoading" :disabled="!form.categoryId" placeholder="搜索品号、名称、规格或材质"><ElOption v-for="item in manualOptions.materials" :key="item.id" :value="item.id" :label="`${item.material_number} · ${item.material_name} · ${item.specification}`" /></ElSelect></ElFormItem>
          <dl class="material-summary full-row" aria-live="polite">
            <div><dt>品号</dt><dd>{{ selectedMaterial?.material_number || '—' }}</dd></div>
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
      <ElButton v-if="canReceive" type="primary" :loading="submitting" :disabled="!ready" @click="submit">确认入库</ElButton>
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
