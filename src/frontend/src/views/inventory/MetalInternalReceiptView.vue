<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isAxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Document, Refresh } from '@element-plus/icons-vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import MetalReceiptTable from '@/components/inventory/MetalReceiptTable.vue'
import { confirmInternalReceipt, fetchMetalReceiptPreview, findInternalReceipt } from '@/api/internalReceipts'
import { useAuthStore } from '@/stores/auth'
import type { InternalReceiptResult, MetalReceiptLine, MetalReceiptPayload, MetalReceiptPreview } from '@/types/internalReceipt'
import '@/styles/metalInternalReceipt.scss'

interface ReceiptRow extends MetalReceiptLine {
  id: string; part: string; material: string; spec: string; thickness: string
  length: string; color: string; issued: string; sent: string; reserved: string; quantity: string
}
interface PendingReceipt { payload: MetalReceiptPayload; etag: string; conflict?: boolean }

const route = useRoute(), router = useRouter(), auth = useAuthStore()
const planId = typeof route.query.schedule_product_id === 'string' ? route.query.schedule_product_id : ''
// 沿用旧金工页的待核对记录键，更新页面后仍能核对原请求。
const pendingKey = `internal-receipt-pending:${planId}:METAL`
const conflictMessage = '原请求编号的保存内容与本次内容不一致，已保留原请求，请先核对入库记录。'
const preview = ref<MetalReceiptPreview | null>(null), rows = ref<ReceiptRow[]>([])
const loading = ref(true), saving = ref(false), error = ref(''), forbidden = ref(false), storageError = ref(false)
const receiptDate = ref(''), warehouseId = ref(''), zoneId = ref(''), remark = ref('')
const pending = ref<PendingReceipt | null>(null), dialog = ref(''), selectedPart = ref<ReceiptRow | null>(null)
let loadVersion = 0, disposed = false
const canReceive = computed(() => !!auth.user?.is_superuser || (auth.hasPermission('inventory.add_internalsemifinishedreceipt') && auth.hasPermission('inventory.view_internalsemifinishedreceipt')))
const pageBlockers = computed(() => preview.value?.metal_processing.blockers || [])
const futureBlockers = computed(() => preview.value?.metal_processing.future_blockers || [])
const formLocked = computed(() => loading.value || saving.value || !!pending.value || storageError.value || !canReceive.value || forbidden.value || !!error.value || !!pageBlockers.value.length || !!futureBlockers.value.length)
const showForm = computed(() => !!preview.value && !loading.value && !forbidden.value && canReceive.value)
const warehouses = computed(() => Array.from(new Map((preview.value?.zones || []).map(zone => [zone.warehouse_id, { id: zone.warehouse_id, name: zone.warehouse }])).values()))
const zones = computed(() => (preview.value?.zones || []).filter(zone => zone.warehouse_id === warehouseId.value))
const warehouseName = computed(() => warehouses.value.find(item => item.id === warehouseId.value)?.name || '—')
const zoneName = computed(() => zones.value.find(item => item.id === zoneId.value)?.name || '—')
const entered = computed(() => rows.value.filter(row => (wholeQuantity(row.quantity) || 0) > 0))
const total = computed(() => entered.value.reduce((sum, row) => sum + (wholeQuantity(row.quantity) || 0), 0))
const info = computed(() => [
  ['生产任务单号', preview.value?.production_order], ['排产单号', preview.value?.schedule_number],
  ['订单量', preview.value ? `${format(preview.value.order_quantity)} ${preview.value.product_unit}` : '—'],
  ['订单喷塑色', preview.value?.product_color], ['入库人', preview.value?.actor],
  ['产品名称', preview.value?.product], ['品号', preview.value?.product_number], ['货号', preview.value?.item_number],
  ['入库来源', '厂内金工'], ['加工状态', '未喷塑'],
])
const columns = computed(() => [
  { key: 'part', label: '部位', width: 90 }, { key: 'material', label: '材质', width: 60 },
  { key: 'spec', label: '规格', width: 120 }, { key: 'thickness', label: '厚度 mm', width: 70 },
  { key: 'length', label: '切割长度 mm', width: 100 }, { key: 'color', label: '原料颜色', width: 85 },
  { key: 'usage', label: `单耗 支/${preview.value?.product_unit || '把'}`, width: 80, num: true },
  { key: 'required', label: '订单需求', width: 90, num: true }, { key: 'issued', label: '实领投入', width: 90, num: true },
  { key: 'minimum', label: '最低报工', width: 100, num: true }, { key: 'received', label: '已入库', width: 80, num: true },
  { key: 'sent', label: '已直发', width: 80, num: true }, { key: 'reserved', label: '待发预留', width: 90, num: true },
  { key: 'available', label: '可入库', width: 90, num: true }, { key: 'quantity', label: '本次入库（支）', width: 140 },
])
const operationColumns = [{ key: 'name', label: '必需工序', width: 250 }, { key: 'quantity', label: '有效累计报工（支）', width: 240, num: true }, { key: 'basis', label: '完成依据', width: 250 }]
const confirmColumns = [
  { key: 'part', label: '部位', width: 120 }, { key: 'spec', label: '规格', width: 150 },
  { key: 'thickness', label: '厚度 mm', width: 90 }, { key: 'length', label: '切割长度 mm', width: 120 },
  { key: 'color', label: '原料颜色', width: 120 }, { key: 'available', label: '本次可入（支）', width: 120, num: true },
  { key: 'quantity', label: '本次入库（支）', width: 130, num: true },
]
const schemeNames = computed(() => selectedPart.value?.metal_processing.schemes.map(scheme => `${scheme.scheme_number} · V${scheme.version}`).join('；') || '—')
const schemeDates = computed(() => Array.from(new Set(selectedPart.value?.metal_processing.schemes.map(scheme => scheme.effective_from) || [])).join('；') || '—')

function format(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: 8 }) : '—'
}
function wholeQuantity(value: string): number | null {
  const text = value.trim()
  if (!text) return 0
  const number = Number(text)
  return /^\d+$/.test(text) && Number.isSafeInteger(number) ? number : null
}
function capacity(row: ReceiptRow): number {
  const value = Number(row.metal_processing.can_receive)
  return row.metal_processing.basis_ready && Number.isSafeInteger(value) && value >= 0 ? value : 0
}
function missingReason(row: ReceiptRow): string {
  return row.metal_processing.blockers.join('；') || '加工数量依据不完整，请先核对工价方案、原料投入和报工记录。'
}
function rowDisabled(row: ReceiptRow): boolean { return formLocked.value || capacity(row) <= 0 }
function warn(message: string) { ElMessage.closeAll(); ElMessage.warning({ message, duration: 4500 }) }
function errorText(cause: unknown, fallback: string): string {
  if (isAxiosError(cause)) {
    const body = cause.response?.data as { error?: { message?: string }; detail?: string } | undefined
    if (body?.error?.message) return body.error.message
    if (typeof body?.detail === 'string') return body.detail
  }
  return cause instanceof Error && !isAxiosError(cause) ? cause.message : fallback
}
function validQuantity(row: ReceiptRow): boolean {
  const quantity = wholeQuantity(row.quantity)
  if (quantity === null) { warn(`${row.part}：请填写整数支数，不支持负数、小数或文字。`); return false }
  if (quantity > 0 && !row.metal_processing.basis_ready) { warn(`${row.part}：${missingReason(row)}`); return false }
  if (quantity > capacity(row)) { warn(`${row.part}：本次最多可入 ${format(capacity(row))} 支。`); return false }
  return true
}
function validate(): boolean {
  if (formLocked.value) return false
  for (const row of rows.value) if (!validQuantity(row)) return false
  if (!entered.value.length) { warn('请至少填写一项大于 0 的本次入库数量。'); return false }
  if (!receiptDate.value || !warehouseId.value || !zones.value.some(zone => zone.id === zoneId.value)) { warn('请选择收货日期、材料仓和库区。'); return false }
  return true
}
function openBasis(row: ReceiptRow) { selectedPart.value = row; dialog.value = 'basis' }
function confirmReceipt() {
  if (pending.value) { void save(); return }
  if (validate()) dialog.value = 'confirm'
}
function reset() { if (!formLocked.value) { rows.value.forEach(row => { row.quantity = '' }); ElMessage.closeAll() } }
function closeDialog(value: boolean) { if (!value && !saving.value) dialog.value = '' }

async function load(preserve = true) {
  if (!planId) { error.value = '缺少金工计划，请从内部计划的产品行进入半成品入库。'; loading.value = false; return }
  if (!canReceive.value) { forbidden.value = true; loading.value = false; return }
  const version = ++loadVersion
  const quantities = new Map(rows.value.map(row => [row.bom_line_id, row.quantity]))
  loading.value = true; error.value = ''; forbidden.value = false
  try {
    const data = await fetchMetalReceiptPreview(planId)
    if (disposed || version !== loadVersion) return
    if (!data.metal_processing) throw new Error('当前环境尚未启用新版金工入库，缺少加工数量依据，暂不可办理。')
    if (data.plan_category !== 'METAL' || data.schedule_product_id !== planId || data.lines.some(line => !line.metal_processing)) throw new Error('入库接口未提供当前金工计划的完整数量依据，请刷新后重试。')
    preview.value = data
    rows.value = data.lines.map(line => ({
      ...line, id: line.bom_line_id, part: line.attributes.part_name, material: line.attributes.material,
      spec: line.specification || line.attributes.specification || '—', thickness: line.attributes.tube_thickness || '—',
      length: String(line.attributes.cutting_length_mm ?? '—'), color: line.attributes.color || '—',
      issued: line.metal_processing.issued, sent: line.metal_processing.dispatched, reserved: line.metal_processing.reserved,
      quantity: String(pending.value?.payload.lines.find(item => item.bom_line_id === line.bom_line_id)?.quantity ?? (preserve ? quantities.get(line.bom_line_id) || '' : '')),
    }))
    if (!receiptDate.value) receiptDate.value = data.receipt_date
    if (pending.value) {
      zoneId.value = pending.value.payload.zone_id
      warehouseId.value = data.zones.find(zone => zone.id === zoneId.value)?.warehouse_id || ''
    } else if (!warehouseId.value) {
      warehouseId.value = data.zones[0]?.warehouse_id || ''
      zoneId.value = data.zones[0]?.id || ''
    } else if (!data.zones.some(zone => zone.warehouse_id === warehouseId.value)) {
      warehouseId.value = ''; zoneId.value = ''
    } else if (!data.zones.some(zone => zone.id === zoneId.value && zone.warehouse_id === warehouseId.value)) zoneId.value = ''
  } catch (cause) {
    if (disposed || version !== loadVersion) return
    forbidden.value = isAxiosError(cause) && cause.response?.status === 403
    error.value = errorText(cause, '入库资料读取失败，请重试。')
  } finally { if (!disposed && version === loadVersion) loading.value = false }
}

function clearPending(): boolean {
  try { sessionStorage.removeItem(pendingKey); pending.value = null; return true }
  catch { storageError.value = true; error.value = '浏览器无法更新待核对请求记录，请先确认本次入库结果，暂勿再次提交。'; return false }
}
async function saved(result: InternalReceiptResult) {
  const cleared = clearPending()
  dialog.value = ''; ElMessage.success({ message: `入库成功，单号：${result.receipt_number}`, duration: 4500 })
  if (cleared) { rows.value.forEach(row => { row.quantity = '' }); await load(false) }
}
async function postPending(recovering = false) {
  const original = pending.value
  if (!original) return
  try { await saved(await confirmInternalReceipt(original.payload, original.etag)) }
  catch (cause) {
    const status = isAxiosError(cause) ? cause.response?.status : undefined
    if (status === 409) {
      dialog.value = ''
      original.conflict = true
      try { sessionStorage.setItem(pendingKey, JSON.stringify(original)) }
      catch { storageError.value = true }
      error.value = conflictMessage
      warn(error.value)
      return
    }
    // 原请求结果不明时，权限或参数校验可先于幂等回查拒绝，不能据此抹掉原请求。
    if (recovering && status && [400, 403, 404].includes(status)) {
      dialog.value = ''
      error.value = `原提交结果仍待核对：${errorText(cause, '暂时无法核对原入库请求。')}`
      warn(error.value)
      return
    }
    if (status && [400, 403, 404, 412, 428].includes(status)) {
      if (!clearPending()) return
      dialog.value = ''
      if (status === 412 || status === 428) {
        await load(true)
        warn('数量依据已变化，已重新读取当前额度，请重新核对后确认入库。')
      } else {
        const message = errorText(cause, '未能入库，请检查填写内容。')
        if (status === 403 || status === 404) { error.value = message; forbidden.value = status === 403 }
        warn(message)
      }
      return
    }
    // 网络中断和超时不能当作未保存，先按原请求编号回查，不自动重复写入。
    dialog.value = ''; await recoverPending(false)
  }
}
async function recoverPending(allowRetry: boolean) {
  if (!pending.value) return
  if (pending.value.conflict) { error.value = conflictMessage; return }
  try { await saved(await findInternalReceipt(pending.value.payload.request_id)) }
  catch (cause) {
    if (allowRetry && isAxiosError(cause) && cause.response?.status === 404) { await postPending(true); return }
    error.value = ''
    warn(errorText(cause, '提交结果尚未确认，请点击“核对本次提交”，避免重复入库。'))
  }
}
async function save() {
  if (saving.value || storageError.value || !canReceive.value) return
  if (pending.value?.conflict) { warn(conflictMessage); return }
  if (!pending.value) {
    if (!validate() || !preview.value) return
    try {
      if (sessionStorage.getItem(pendingKey)) { warn('已有待核对请求，请刷新本页核对原提交结果。'); return }
      const original: PendingReceipt = {
        etag: preview.value.etag,
        payload: {
          request_id: crypto.randomUUID(), schedule_product_id: planId, plan_category: 'METAL', zone_id: zoneId.value,
          receipt_date: receiptDate.value, remark: remark.value.trim(),
          lines: entered.value.map(row => ({ bom_line_id: row.bom_line_id, quantity: String(wholeQuantity(row.quantity)) })),
        },
      }
      sessionStorage.setItem(pendingKey, JSON.stringify(original)); pending.value = original
    } catch { warn('浏览器无法保存请求编号，本次尚未提交。请允许本站会话存储后重试。'); return }
    saving.value = true; error.value = ''
    try { await postPending() } finally { saving.value = false }
  } else {
    saving.value = true; error.value = ''
    try { await recoverPending(true) } finally { saving.value = false }
  }
}
onMounted(async () => {
  try {
    const text = sessionStorage.getItem(pendingKey)
    if (text) {
      const original = JSON.parse(text) as PendingReceipt
      const payload = original?.payload
      if (!original || typeof original.etag !== 'string' || !original.etag || !payload
        || payload.schedule_product_id !== planId || payload.plan_category !== 'METAL'
        || ![payload.request_id, payload.zone_id, payload.receipt_date].every(value => typeof value === 'string' && value.length > 0)
        || typeof payload.remark !== 'string' || !Array.isArray(payload.lines) || !payload.lines.length
        || !payload.lines.every(line => typeof line.bom_line_id === 'string' && (
          typeof line.quantity === 'string' ? (wholeQuantity(line.quantity) || 0) > 0
            : typeof line.quantity === 'number' && Number.isSafeInteger(line.quantity) && line.quantity > 0
        ))) throw new Error('待核对记录不完整')
      pending.value = original; receiptDate.value = payload.receipt_date; zoneId.value = payload.zone_id; remark.value = payload.remark
    }
  } catch { storageError.value = true; loading.value = false; error.value = '本地待核对请求记录无法读取，已暂停新入库。请先核对之前的提交结果。'; return }
  await load(false)
  if (pending.value && canReceive.value) { saving.value = true; try { await recoverPending(false) } finally { saving.value = false } }
})
onBeforeUnmount(() => { disposed = true; loadVersion += 1 })
</script>

<template>
  <section class="metal-receipt-page d1-page">
    <header class="page-heading"><div class="title-row"><h1>半成品入库</h1><span class="status info">厂内金工</span></div><ElButton :icon="Document" :disabled="saving" @click="router.push({ name: 'semi-receipt-records' })">入库记录</ElButton></header>
    <ElAlert v-if="futureBlockers.length" type="warning" :closable="false" show-icon :title="futureBlockers.join('；')" />
    <ElAlert v-else-if="pageBlockers.length" type="warning" :closable="false" show-icon :title="pageBlockers.join('；')" />
    <ElAlert v-if="pending" type="warning" :closable="false" show-icon title="提交结果尚未确认，请点击“核对本次提交”，避免重复入库。" />
    <ElAlert v-if="error && (preview || storageError)" type="error" :closable="false" show-icon :title="error"><ElButton v-if="!pending && !storageError" link @click="load(true)">重新加载</ElButton></ElAlert>
    <template v-if="showForm">
      <div class="panel d1-context"><div class="info-grid"><div v-for="[label, value] in info" :key="label" class="info-cell"><span>{{ label }}</span><strong :class="{ brand: label === '加工状态' }" :title="value || '—'">{{ value || '—' }}</strong></div></div></div>
      <div class="panel workspace d1-workspace">
        <div class="section-heading"><div><h2>本次入库</h2><span class="muted">填写数量即可办理 · 数量单位：支</span></div><ElButton :icon="Refresh" :disabled="saving || !!pending || loading || storageError" @click="load(true)">刷新</ElButton></div>
        <div class="field-grid d1-fields">
          <label class="form-field required"><span>收货日期</span><ElDatePicker v-model="receiptDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" popper-class="schedule-date-popper" placeholder="选择日期" aria-label="收货日期" :disabled="formLocked" /></label>
          <label class="form-field required"><span>材料仓</span><ElSelect v-model="warehouseId" aria-label="材料仓" :disabled="formLocked" @change="zoneId = ''"><ElOption v-for="item in warehouses" :key="item.id" :value="item.id" :label="item.name" /></ElSelect></label>
          <label class="form-field required"><span>库区</span><ElSelect v-model="zoneId" aria-label="库区" placeholder="请选择库区" :disabled="formLocked"><ElOption v-for="item in zones" :key="item.id" :value="item.id" :label="item.name" /></ElSelect></label>
          <label class="form-field"><span>加工状态</span><ElInput model-value="未喷塑" aria-label="加工状态" disabled /></label>
        </div>
        <MetalReceiptTable :columns="columns" :rows="rows" class="d1-lines" empty="此金工计划暂无管材明细">
          <template #cell-part="{ row }"><strong>{{ row.part }}</strong></template>
          <template #cell-usage="{ row }">{{ format(row.usage) }}</template>
          <template #cell-required="{ row }">{{ format(row.required) }}</template>
          <template #cell-issued="{ row }">{{ format(row.issued) }}</template>
          <template #cell-minimum="{ row }"><ElTooltip :content="row.metal_processing.basis_ready ? '点击查看必需工序和可入库数量依据' : missingReason(row)" placement="top"><ElButton link :aria-label="`${row.part}最低报工`" @click="openBasis(row)">{{ row.metal_processing.basis_ready ? format(row.metal_processing.reported_minimum) : '— 查看原因' }}</ElButton></ElTooltip></template>
          <template #cell-received="{ row }">{{ format(row.received) }}</template>
          <template #cell-sent="{ row }">{{ format(row.sent) }}</template>
          <template #cell-reserved="{ row }">{{ format(row.reserved) }}</template>
          <template #cell-available="{ row }"><strong :class="capacity(row) > 0 ? 'brand' : 'muted'">{{ row.metal_processing.basis_ready ? format(capacity(row)) : '—' }}</strong></template>
          <template #cell-quantity="{ row }"><ElInput v-model="row.quantity" :aria-label="`${row.part}本次入库`" inputmode="numeric" :placeholder="!row.metal_processing.basis_ready ? '依据不完整' : capacity(row) ? '填写数量' : '暂无可入'" :disabled="rowDisabled(row)" @blur="validQuantity(row)"><template v-if="!rowDisabled(row)" #suffix><span class="d1-unit">支</span></template></ElInput></template>
        </MetalReceiptTable>
        <label class="form-field d1-remark"><span>入库备注 <small class="muted">选填</small></span><ElInput v-model="remark" type="textarea" :rows="3" maxlength="2000" :disabled="formLocked" placeholder="填写本次收货或存放说明" aria-label="入库备注" /></label>
      </div>
    </template>
    <div v-else class="panel d1-fallback">
      <ElSkeleton v-if="loading" :rows="9" animated />
      <ElEmpty v-else-if="forbidden || !canReceive" description="当前账号没有半成品入库权限，请联系管理员" />
      <template v-else><ElEmpty :description="error || '入库资料读取失败，请重试'" /><ElButton v-if="!storageError" :icon="Refresh" @click="load(true)">重新加载</ElButton></template>
    </div>
    <footer class="footer-bar"><div>本次入库 <strong>{{ showForm ? format(total) : '—' }}</strong> 支 <span v-if="showForm" class="muted"> · {{ entered.length }} 个部位</span><small>确认后增加未喷塑公共半成品库存</small></div><ElButton :icon="ArrowLeft" :disabled="saving" @click="router.back()">返回</ElButton><ElButton :icon="Refresh" :disabled="formLocked" @click="reset">重填</ElButton><ElButton type="primary" :loading="saving" :disabled="storageError || saving || !canReceive || (!pending && formLocked)" @click="confirmReceipt">{{ pending ? '核对本次提交' : '确认入库' }}</ElButton></footer>
  </section>

  <AppWindowDialog :model-value="dialog === 'basis'" :title="`${selectedPart?.part || ''} · 加工完成依据`" :width="960" modal-class="metal-receipt-dialog" @update:model-value="closeDialog">
    <div v-if="selectedPart" class="d1-basis">
      <ElAlert v-if="!selectedPart.metal_processing.basis_ready" type="warning" :closable="false" show-icon :title="missingReason(selectedPart)" />
      <template v-else>
        <div class="info-grid d1-basis-info"><div class="info-cell"><span>已批准方案</span><strong :title="schemeNames">{{ schemeNames }}</strong></div><div class="info-cell"><span>生效日期</span><strong :title="schemeDates">{{ schemeDates }}</strong></div><div class="info-cell"><span>核算截至</span><strong>{{ selectedPart.metal_processing.as_of }}</strong></div></div>
        <MetalReceiptTable :columns="operationColumns" :rows="selectedPart.metal_processing.operations" row-key="operation_id" class="d1-operations"><template #cell-quantity="{ row }">{{ format(row.quantity) }}</template><template #cell-basis="{ row }"><span v-if="Number(row.quantity) === Number(selectedPart.metal_processing.reported_minimum)" class="status info">{{ Number(row.quantity) === 0 ? '尚未报工 · 最低值' : '最低值' }}</span><span v-else class="muted">已累计</span></template></MetalReceiptTable>
        <p class="muted d1-basis-note">按本生产任务产品的同一部位、同一工序，累计不同人员和日期的有效报工。</p>
        <div class="d1-cap-grid"><div><span>订单净需求</span><strong>{{ format(selectedPart.required) }} <small>支</small></strong></div><div><span>实领投入</span><strong>{{ format(selectedPart.issued) }} <small>支</small></strong></div><div><span>最低报工</span><strong>{{ format(selectedPart.metal_processing.reported_minimum) }} <small>支</small></strong></div><div><span>三项取小 · 首次产出上限</span><strong>{{ format(selectedPart.metal_processing.first_output_limit) }} <small>支</small></strong></div></div>
        <div class="d1-cap-grid d1-occupied"><div><span>减：已首次入库</span><strong>{{ format(selectedPart.received) }} <small>支</small></strong></div><div><span>减：已直接发出</span><strong>{{ format(selectedPart.sent) }} <small>支</small></strong></div><div><span>减：有效待发预留</span><strong>{{ format(selectedPart.reserved) }} <small>支</small></strong></div><div><span>本次最多可入</span><strong class="brand">{{ format(capacity(selectedPart)) }} <small>支</small></strong></div></div>
        <ElAlert v-if="selectedPart.metal_processing.future_blockers.length" class="d1-future-note" type="warning" :closable="false" show-icon :title="selectedPart.metal_processing.future_blockers.join('；')" />
        <p class="muted d1-basis-note">入库与加工件直接外发共用该部位额度；半成品后续领走或外发，不恢复首次产出额度。</p>
      </template>
    </div>
    <template #footer><ElButton type="primary" @click="dialog = ''">我知道了</ElButton></template>
  </AppWindowDialog>

  <AppWindowDialog :model-value="dialog === 'confirm'" title="确认半成品入库" :width="1120" modal-class="metal-receipt-dialog" :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving" @update:model-value="closeDialog">
    <div class="d1-confirm">
      <div class="info-grid"><div class="info-cell"><span>收货日期</span><strong>{{ receiptDate }}</strong></div><div class="info-cell"><span>材料仓</span><strong>{{ warehouseName }}</strong></div><div class="info-cell"><span>库区</span><strong>{{ zoneName }}</strong></div><div class="info-cell"><span>生产任务单号</span><strong>{{ preview?.production_order }}</strong></div><div class="info-cell"><span>产品</span><strong>{{ preview?.product }}</strong></div><div class="info-cell"><span>加工状态</span><strong>未喷塑</strong></div></div>
      <MetalReceiptTable :columns="confirmColumns" :rows="entered" class="d1-confirm-lines"><template #cell-available="{ row }">{{ format(capacity(row)) }}</template><template #cell-quantity="{ row }"><strong class="brand">{{ format(row.quantity) }}</strong></template></MetalReceiptTable>
      <p v-if="remark" class="d1-confirm-remark"><span class="muted">入库备注：</span>{{ remark }}</p>
      <div class="d1-confirm-total">本次入库 <strong class="brand">{{ format(total) }}</strong> 支 · {{ entered.length }} 个部位</div>
      <p class="muted d1-basis-note">确认后增加未喷塑公共半成品库存，已领原料不重复扣减。</p>
    </div>
    <template #footer><ElButton :disabled="saving" @click="dialog = ''">返回修改</ElButton><ElButton type="primary" :loading="saving" @click="save">确认入库</ElButton></template>
  </AppWindowDialog>
</template>
