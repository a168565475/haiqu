<script setup lang="ts">
import { pipeMeters, pipeRootError } from '@/utils/pipeQuantities'
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Calendar, Refresh } from '@element-plus/icons-vue'

import { createManualMaterialReceipt, fetchManualMaterialOptions, fetchMaterialReceivingOptions } from '@/api/inventory'
import { router } from '@/router'
import { useAuthStore } from '@/stores/auth'
import type { ManualMaterialOption, ManualMaterialOptions, MaterialReceivingOptions } from '@/types/inventory'

const auth = useAuthStore()
const canReceive = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.receive_material'))
const canViewReceipts = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.view_material_receipt'))
const canViewInventory = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.view_materialinbound'))
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
    try {
      if (canViewReceipts.value) {
        await router.push({ name: 'material-inbound-details', query: { section_title: selectedMaterial.value?.category_name || '' } })
      } else {
        await router.push({ name: canViewInventory.value ? 'material-inventory' : 'purchase-inbounds' })
      }
    } catch { ElMessage.warning('材料已入库，请从菜单返回列表查看。') }
  } catch (error) { ElMessage.error(apiMessage(error, '额外材料入库失败，请核对后重试。')) }
  finally { submitting.value = false }
}

onMounted(() => { if (canReceive.value) void loadBase() })
</script>

<template>
  <section class="manual-inbound-page erp-glass-form" data-testid="manual-material-inbound-page">
    <div v-if="!canReceive" class="empty-state"><h1>无权进行材料入库</h1><p>请联系管理员开通材料入库权限。</p></div>
    <template v-else>
      <header class="page-head"><div><h1>材料入库</h1><p>额外入库 · 提交后直接计入已确认库存</p></div><ElButton :icon="Refresh" :loading="loading" @click="loadBase">刷新</ElButton></header>
      <section class="notice"><strong>额外入库</strong><span>该记录不关联采购单，也不进入品质确认；备注用于说明材料来源或调整原因。</span></section>
      <section v-loading="loading" class="form-card">
        <header><h2>入库信息</h2><span><i>*</i> 为必填项</span></header>
        <div class="form-grid">
          <label><span><i>*</i> 品类</span><ElSelect v-model="form.categoryId" filterable placeholder="请选择品类" @change="categoryChanged"><ElOption v-for="item in manualOptions.categories" :key="item.id" :value="item.id" :label="item.name" /></ElSelect></label>
          <label class="material-field"><span><i>*</i> 原料规格</span><ElSelect v-model="form.rawMaterialId" filterable remote reserve-keyword :remote-method="loadMaterials" :loading="materialsLoading" :disabled="!form.categoryId" placeholder="搜索品号、名称、规格或材质"><ElOption v-for="item in manualOptions.materials" :key="item.id" :value="item.id" :label="`${item.material_number} · ${item.material_name} · ${item.specification}`" /></ElSelect></label>
          <label><span><i>*</i> 材料仓</span><ElSelect v-model="form.warehouseId" placeholder="请选择材料仓" @change="warehouseChanged"><ElOption v-for="item in inventoryOptions.warehouses" :key="item.id" :value="item.id" :label="`${item.warehouse_number} · ${item.warehouse_name}`" /></ElSelect></label>
          <label><span><i>*</i> 库区</span><ElSelect v-model="form.zoneId" :disabled="!form.warehouseId" placeholder="请选择库区"><ElOption v-for="item in zones" :key="item.id" :value="item.id" :label="item.zone_name" /></ElSelect></label>
<label v-if="isPipe"><span><i>*</i> 原材料长度（米/根）</span><ElInput v-model="form.rawLength" inputmode="decimal" placeholder="保留两位小数" /><small>总米数 {{ pipeMeters(form.quantity, form.rawLength) || '—' }} 米</small></label>
          <label><span><i>*</i> {{ isPipe ? '入库根数（整数）' : '入库数量' }}</span><ElInput v-model="form.quantity" :inputmode="isPipe ? 'numeric' : 'decimal'" maxlength="19" :placeholder="isPipe ? '请输入正整数根数' : '大于 0，最多 4 位小数'"><template #append>{{ selectedMaterial?.unit_name || '单位' }}</template></ElInput></label>
          <label><span><i>*</i> 入库日期</span><ElDatePicker v-model="form.inboundDate" type="date" value-format="YYYY-MM-DD" :prefix-icon="Calendar" :disabled-date="(date: Date) => new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date) > localToday()" /></label>
        </div>

        <section class="material-summary" aria-live="polite">
          <div><span>品号</span><strong>{{ selectedMaterial?.material_number || '—' }}</strong></div>
          <div><span>原料名称</span><strong>{{ selectedMaterial?.material_name || '—' }}</strong></div>
          <div><span>规格</span><strong>{{ selectedMaterial?.specification || '—' }}</strong></div>
          <div><span>材质 / 颜色</span><strong>{{ [selectedMaterial?.material, selectedMaterial?.color_name].filter(Boolean).join(' · ') || '—' }}</strong></div>
          <div><span>单位</span><strong>{{ selectedMaterial?.unit_name || '—' }}</strong></div>
        </section>

        <label class="remark-field"><span><i>*</i> 入库备注</span><ElInput v-model="form.remark" type="textarea" :rows="3" maxlength="3000" show-word-limit placeholder="请填写额外入库的来源或原因" /></label>
      </section>
      <footer class="submit-bar"><ElButton @click="router.push({ name: 'material-inventory' })">取消</ElButton><ElButton type="primary" :loading="submitting" :disabled="!ready" @click="submit">确认入库</ElButton></footer>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;
.manual-inbound-page { box-sizing: border-box; height: auto; min-height: 0; overflow: visible; padding: 28px; background: transparent; color: token.$crm-text-primary; font: 13px/20px token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary}; --el-border-color: #{token.$crm-border-default}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-text-color-primary: #{token.$crm-text-primary}; --el-text-color-regular: #{token.$crm-text-secondary}; --el-border-radius-base: 5px; }
h1, h2, p { margin: 0; } i { color: token.$crm-danger; font-style: normal; }
.page-head, .notice, .form-card > header, .material-summary, .submit-bar { display: flex; align-items: center; }
.page-head { height: 56px; justify-content: space-between; margin-bottom: 16px; } .page-head h1 { font-size: 28px; line-height: 34px; } .page-head p { color: token.$crm-text-secondary; font-size: 12px; }
.notice { gap: 18px; height: 42px; padding: 0 16px; margin-bottom: 16px; @include detail.inset; } .notice strong { color: token.$crm-primary; } .notice span { color: token.$crm-text-secondary; }
.form-card { @include detail.surface; padding: 0 20px 22px; }
.form-card > header { height: 50px; justify-content: space-between; border-bottom: 1px solid token.$crm-border-subtle; } .form-card h2 { font-size: 16px; } .form-card header span { color: token.$crm-text-secondary; font-size: 12px; }
.form-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px 20px; padding: 22px 0; } label { display: flex; min-width: 0; flex-direction: column; gap: 7px; } label > span { font-weight: 500; } label :deep(.el-select), label :deep(.el-date-editor) { width: 100%; }
.material-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 18px; padding: 14px 16px; margin-bottom: 20px; @include detail.inset; }
.material-summary > div { display: flex; min-width: 0; flex-direction: column; gap: 2px; } .material-summary span { color: token.$crm-text-secondary; font-size: 11px; } .material-summary strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.remark-field :deep(.el-textarea__inner) { resize: vertical; }
.submit-bar { justify-content: flex-end; gap: 10px; height: 64px; } .submit-bar .el-button { width: 112px; height: 38px; margin: 0; }
.manual-inbound-page :deep(.el-input__wrapper), .manual-inbound-page :deep(.el-select__wrapper) { height: 32px; min-height: 32px; border-radius: var(--erp-radius-control); box-shadow: 0 0 0 1px var(--erp-input-border) inset; }
.empty-state { padding: 80px; text-align: center; color: token.$crm-text-secondary; }
@media (max-width: 1100px) { .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .material-summary { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
</style>
