<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Refresh, Search } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import TubeOutsourcingDetailTable from '@/components/outsourcing/TubeOutsourcingDetailTable.vue'
import { confirmTubeReceipt, fetchTubeReceipt, fetchTubeReceiptCandidates, fetchTubeReceiptPreview, findTubeReceipt } from '@/api/tubeReceipts'
import { useAuthStore } from '@/stores/auth'
import type { TubeDetailLine, TubeSourceKind } from '@/types/tubeOutsourcing'
import type { TubeReceipt, TubeReceiptCandidate, TubeReceiptPending, TubeReceiptPreview } from '@/types/tubeReceipts'
import '@/styles/tubeCoatingReceipt.scss'

interface Entry {
  id: string; order_line_id: string; part_name: string; material: string; specification: string; thickness: string
  cutting_length_mm: string; raw_color: string; spray_color: string; factory_id: string; factory_name: string
  dispatched_quantity: string; received: string; reason: string; zone: string; zone_name: string
}
interface Column { key: string; label: string; width: number; num?: boolean }
const auth = useAuthStore(), router = useRouter(), route = useRoute()
const entry = route.name === 'inventory-tube-return' ? 'inventory' : 'order'
const orderId = typeof route.params.id === 'string' ? route.params.id : typeof route.query.order_id === 'string' ? route.query.order_id : ''
const preview = ref<TubeReceiptPreview | null>(null), rows = ref<Entry[]>([])
const loading = ref(false), saving = ref(false), recordLoading = ref(false), readError = ref(''), readStatus = ref<number | undefined>()
const pending = ref<TubeReceiptPending | null>(null), storageError = ref(false)
const dialog = ref<'' | 'select' | 'confirm' | 'warehouse'>('')
const receiptDate = ref(''), remark = ref(''), warehouse = ref(''), pendingWarehouse = ref('')
const search = ref(''), pickerSource = ref<TubeSourceKind | ''>('')
const candidates = ref<TubeReceiptCandidate[]>([]), candidateTotal = ref(0), candidatePage = ref(0)
const candidateLoading = ref(false), candidateError = ref('')
const pendingKey = `tube-coating-receipt:v1:${auth.user?.id || 'unknown'}:${orderId}`
let disposed = false, previewSequence = 0, candidateSequence = 0
let searchTimer: ReturnType<typeof setTimeout> | undefined

const labels: Record<TubeSourceKind, string> = { RAW_PIPE: '原材料', PUBLIC_SEMI: '未喷塑半成品', METAL: '未入库半成品' }
const sourceOptions = Object.entries(labels) as Array<[TubeSourceKind, string]>
const order = computed(() => preview.value?.order || null)
const receipt = computed(() => preview.value?.receipt || null)
const sourceLabel = computed(() => order.value ? labels[order.value.source_kind] || '—' : '—')
const isEnded = computed(() => order.value?.status === 'COMPLETED' && Boolean(receipt.value))
const inapplicable = computed(() => Boolean(order.value) && !['PROCESSING', 'COMPLETED'].includes(order.value!.status))
const showDetails = computed(() => Boolean(preview.value) && !loading.value && !readError.value && !inapplicable.value)
const hasPermission = computed(() => Boolean(auth.user?.is_superuser || auth.hasPermission('outsourcing.confirm_return_outsourcingorder')))
const formLocked = computed(() => loading.value || saving.value || Boolean(pending.value) || storageError.value || !showDetails.value)
const canEdit = computed(() => !formLocked.value && !isEnded.value && order.value?.status === 'PROCESSING' && preview.value?.can_receive === true && rows.value.length > 0)
const warehouses = computed(() => preview.value?.warehouses || [])
const zones = computed(() => (preview.value?.zones || []).filter(zone => zone.warehouse_id === warehouse.value))
const warehouseLabel = computed(() => receipt.value?.warehouse_name || warehouses.value.find(item => item.id === warehouse.value)?.name || '—')
const actorName = computed(() => receipt.value?.actor_name || preview.value?.actor_name || '—')
const hasInvalidQuantity = computed(() => rows.value.some(row => receivedValue(row) === null))
const totalSent = computed(() => rows.value.reduce((sum, row) => sum + Number(row.dispatched_quantity || 0), 0))
const totalReceived = computed(() => rows.value.reduce((sum, row) => sum + (receivedValue(row) || 0), 0))
const totalDifference = computed(() => totalSent.value - totalReceived.value)
const positiveRows = computed(() => rows.value.filter(row => (receivedValue(row) || 0) > 0))
const info = computed<Array<[string, unknown]>>(() => [
  ['生产任务单', order.value?.task_number], ['订单号', order.value?.task_order_number], ['排产单号', order.value?.schedule_number],
  ['订单量', order.value ? `${format(order.value.quantity)} ${order.value.unit || ''}` : '—'], ['实际发出日', order.value?.actual_dispatch_date], ['预计回货日', order.value?.expected_return_date],
  ['产品名称', order.value?.product_name], ['品号', order.value?.product_number], ['货号', order.value?.item_number],
  ['材料来源', sourceLabel.value], ['加工厂', `${new Set(rows.value.map(row => row.factory_id)).size} 家`], ['入库状态', '已喷塑'],
])
const columns: Column[] = [
  { key: 'part_name', label: '部位', width: 95 }, { key: 'material', label: '材质', width: 65 }, { key: 'specification', label: '规格', width: 125 },
  { key: 'thickness', label: '厚度 mm', width: 75 }, { key: 'cutting_length_mm', label: '切割长度 mm', width: 98 },
  { key: 'raw_color', label: '原料颜色', width: 85 }, { key: 'spray_color', label: '喷塑颜色', width: 80 }, { key: 'factory_name', label: '加工厂', width: 120 },
  { key: 'dispatched_quantity', label: '实发（支）', width: 90, num: true }, { key: 'received', label: '实收（支）', width: 125, num: true },
  { key: 'difference', label: '差额（支）', width: 85, num: true }, { key: 'reason', label: '差额原因', width: 230 }, { key: 'zone', label: '入库库区', width: 150 },
]
const pickerColumns: Column[] = [
  { key: 'order_number', label: '外发单号', width: 210 }, { key: 'source_label', label: '材料来源', width: 160 }, { key: 'task_number', label: '生产任务单', width: 190 },
  { key: 'product_name', label: '产品名称', width: 190 }, { key: 'factory_names', label: '加工厂', width: 250 },
  { key: 'total_quantity', label: '实发（支）', width: 100, num: true }, { key: 'actual_dispatch_date', label: '实际发出日', width: 130 },
  { key: 'status', label: '状态', width: 85 }, { key: 'action', label: '操作', width: 125 },
]
function format(value: unknown): string { return value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN') }
function receivedValue(row: Entry): number | null {
  const text = row.received.trim()
  if (!text) return 0
  if (!/^\d+$/.test(text)) return null
  const value = Number(text), sent = Number(row.dispatched_quantity)
  return Number.isSafeInteger(value) && Number.isSafeInteger(sent) && value >= 0 && value <= sent ? value : null
}
function difference(row: Entry): number | null { const value = receivedValue(row); return value === null ? null : Number(row.dispatched_quantity) - value }
function zoneLabel(row: Entry): string { return (receivedValue(row) || 0) > 0 ? isEnded.value ? row.zone_name || '—' : zones.value.find(item => item.id === row.zone)?.name || '—' : '—' }
function warn(message: string) { ElMessage.closeAll(); ElMessage.warning({ message, duration: 4500 }) }
function errorText(cause: unknown, fallback: string): string {
  if (isAxiosError(cause)) {
    const body = cause.response?.data as { error?: { message?: string }; detail?: string } | undefined
    return body?.error?.message || (typeof body?.detail === 'string' ? body.detail : fallback)
  }
  return cause instanceof Error ? cause.message : fallback
}
function rowFromOrder(line: TubeDetailLine): Entry {
  return { id: line.id, order_line_id: line.id, part_name: line.part_name, material: line.material, specification: line.specification, thickness: line.thickness,
    cutting_length_mm: line.cutting_length_mm, raw_color: line.raw_color, spray_color: line.spray_color, factory_id: line.factory_id, factory_name: line.factory_name,
    dispatched_quantity: line.quantity, received: '', reason: '', zone: '', zone_name: '' }
}
function useReceipt(result: TubeReceipt) {
  if (!preview.value || result.order_id !== orderId || result.status !== 'COMPLETED' || !result.id || !result.receipt_number || !result.etag || !Array.isArray(result.lines)) throw new Error('回货结果不完整，请继续核对原请求。')
  preview.value = { ...preview.value, order: { ...preview.value.order, status: 'COMPLETED', etag: result.etag }, etag: result.etag, can_receive: false, receipt: result }
  rows.value = result.lines.map(line => ({ id: line.id, order_line_id: line.order_line_id, part_name: line.part_name, material: line.material, specification: line.specification, thickness: line.thickness,
    cutting_length_mm: line.cutting_length_mm, raw_color: line.raw_color, spray_color: line.spray_color, factory_id: line.factory_id, factory_name: line.factory_name,
    dispatched_quantity: line.dispatched_quantity, received: line.received_quantity, reason: line.shortage_reason, zone: line.zone_id || '', zone_name: line.zone_name }))
  receiptDate.value = result.receipt_date; warehouse.value = result.warehouse_id || ''; remark.value = result.remark
}
function usePreview(result: TubeReceiptPreview, preserve = true) {
  if (result.order?.id !== orderId || !result.etag || !Array.isArray(result.order.lines) || !Array.isArray(result.warehouses) || !Array.isArray(result.zones)) throw new Error('外发单及收货依据不完整，请重新加载。')
  if (result.order.lines.some(line => !line.id || !/^\d+$/.test(line.quantity) || !Number.isSafeInteger(Number(line.quantity)) || Number(line.quantity) <= 0)) throw new Error('原单实发数量不完整，请重新加载，不能据此办理回货。')
  if (result.order.status === 'COMPLETED' && !result.receipt) throw new Error('单据已结束但最终回货凭证缺失，请核对原请求或重新加载。')
  const previous = new Map(rows.value.map(row => [row.order_line_id, row]))
  preview.value = result
  if (result.receipt) { useReceipt(result.receipt); return }
  rows.value = result.order.lines.map(line => {
    const row = rowFromOrder(line), old = preserve ? previous.get(line.id) : undefined
    return old ? { ...row, received: old.received, reason: old.reason, zone: old.zone } : row
  })
  if (!preserve || !receiptDate.value) receiptDate.value = result.today
  if (!preserve) { warehouse.value = ''; remark.value = '' }
}
async function loadPreview(preserve = true) {
  if (!orderId || saving.value || pending.value || storageError.value) return
  const sequence = ++previewSequence
  loading.value = true; readError.value = ''; readStatus.value = undefined
  try {
    const result = await fetchTubeReceiptPreview(orderId)
    if (!disposed && sequence === previewSequence) usePreview(result, preserve)
  } catch (cause) {
    if (!disposed && sequence === previewSequence) { readStatus.value = isAxiosError(cause) ? cause.response?.status : undefined; readError.value = errorText(cause, '外发单读取失败，请重新加载。') }
  } finally { if (!disposed && sequence === previewSequence) loading.value = false }
}
async function loadCandidates(reset = false) {
  if (!hasPermission.value || saving.value || pending.value || storageError.value || (candidateLoading.value && !reset)) return
  if (reset) { candidates.value = []; candidatePage.value = 0; candidateTotal.value = 0 }
  if (!reset && candidatePage.value && candidates.value.length >= candidateTotal.value) return
  const sequence = ++candidateSequence, page = candidatePage.value + 1
  candidateLoading.value = true; candidateError.value = ''
  try {
    const result = await fetchTubeReceiptCandidates({ search: search.value.trim(), ...(pickerSource.value ? { source_kind: pickerSource.value } : {}), page, page_size: 50 })
    if (disposed || sequence !== candidateSequence) return
    if (!Array.isArray(result.items) || result.page !== page || !Number.isSafeInteger(result.total) || result.total < 0 || (!result.items.length && result.total > candidates.value.length)) throw new Error('待回货列表不完整，请重试。')
    candidates.value = [...new Map([...candidates.value, ...result.items].map(item => [item.id, item])).values()]
    candidatePage.value = result.page; candidateTotal.value = result.total
  } catch (cause) { if (!disposed && sequence === candidateSequence) candidateError.value = errorText(cause, '待回货列表读取失败，请重试。') }
  finally { if (!disposed && sequence === candidateSequence) candidateLoading.value = false }
}
function candidateScrolled(event: Event) {
  const element = event.target as HTMLElement
  if (element.scrollTop + element.clientHeight >= element.scrollHeight - 60) void loadCandidates(false)
}
function openPicker() { if (!saving.value && !pending.value && !storageError.value && hasPermission.value) { dialog.value = 'select'; void loadCandidates(true) } }
function selectOrder(item: TubeReceiptCandidate) {
  if (pending.value || saving.value || storageError.value || !candidates.value.some(candidate => candidate.id === item.id)) return
  dialog.value = ''
  void router.replace({ name: 'inventory-tube-return', query: { order_id: item.id } })
}
watch([search, pickerSource], () => {
  if (dialog.value !== 'select') return
  if (searchTimer) clearTimeout(searchTimer)
  candidateSequence += 1; candidateLoading.value = false; candidates.value = []; candidatePage.value = 0; candidateTotal.value = 0
  searchTimer = setTimeout(() => { if (!disposed && dialog.value === 'select') void loadCandidates(true) }, 300)
})
function validateQuantity(row: Entry): boolean {
  if (receivedValue(row) === null) { warn(`${row.part_name}：实收须为0至${format(row.dispatched_quantity)}的整数，空白按0支处理。`); return false }
  return true
}
function onReceivedChange(row: Entry) { if ((receivedValue(row) || 0) > 0 && !row.zone && zones.value.length) row.zone = zones.value[0]!.id }
function requestWarehouseChange(raw: unknown) {
  if (!canEdit.value || typeof raw !== 'string' || raw === warehouse.value) return
  if (!warehouses.value.some(item => item.id === raw)) return
  if (warehouse.value && rows.value.some(row => row.zone)) { pendingWarehouse.value = raw; dialog.value = 'warehouse'; return }
  warehouse.value = raw; rows.value.forEach(row => { row.zone = '' })
}
function confirmWarehouseChange() {
  if (!canEdit.value || !warehouses.value.some(item => item.id === pendingWarehouse.value)) return
  warehouse.value = pendingWarehouse.value; rows.value.forEach(row => { row.zone = '' })
  pendingWarehouse.value = ''; dialog.value = ''
}
function validateReceipt(): boolean {
  if (!canEdit.value) { warn(preview.value?.blockers.join('；') || '当前外发单不能办理整单喷塑入库。'); return false }
  for (const row of rows.value) {
    if (!validateQuantity(row)) return false
    if ((difference(row) || 0) > 0 && !row.reason.trim()) { warn(`${row.part_name}：少回${format(difference(row))}支，请填写差额原因。`); return false }
  }
  if (!receiptDate.value) { warn('请选择收货日期。'); return false }
  if (positiveRows.value.length && !warehouses.value.some(item => item.id === warehouse.value)) { warn('请选择有实收明细的入库仓库。'); return false }
  for (const row of positiveRows.value) { if (!zones.value.some(zone => zone.id === row.zone)) { warn(`${row.part_name}：请选择当前仓库下的入库库区。`); return false } }
  return true
}
function openConfirm() { if (validateReceipt()) dialog.value = 'confirm' }
function closeDialog(value: boolean) { if (!value && !saving.value) { dialog.value = ''; pendingWarehouse.value = '' } }
function beforeClose(done: () => void) { if (!saving.value) done() }
function clearPending(): boolean {
  try { localStorage.removeItem(pendingKey); pending.value = null; return true }
  catch { storageError.value = true; warn('回货结果已确认，但本地请求记录未能清理。请恢复浏览器存储后刷新页面。'); return false }
}
function confirmResult(result: TubeReceipt) {
  const request = pending.value
  if (!request || result.client_request_id !== request.payload.client_request_id || result.order_id !== request.order_id
    || !Array.isArray(result.lines) || result.lines.length !== request.payload.lines.length
    || !request.payload.lines.every(line => result.lines.some(item => item.order_line_id === line.order_line_id && item.received_quantity === line.received_quantity))) throw new Error('原请求回货结果不完整，请继续核对。')
  useReceipt(result); clearPending(); dialog.value = ''; readError.value = ''; readStatus.value = undefined
  ElMessage.success({ message: Number(result.total_received_quantity) > 0 ? `已登记 ${result.receipt_number}，整单已入库并结束。` : `已登记 ${result.receipt_number}，整单0回货已结束，未增加库存。`, duration: 5000 })
}
async function completeRequest(result: TubeReceipt) {
  // 刷新时原单读取可能失败；原请求已确认也必须补齐真实订单依据再展示结果。
  if (!preview.value) {
    const current = await fetchTubeReceiptPreview(orderId)
    if (disposed) return
    usePreview(current, true)
  }
  confirmResult(result)
}
async function handleRejection(cause: unknown) {
  const message = errorText(cause, '回货未能办理，请刷新原单后重新核对。')
  if (clearPending()) { saving.value = false; dialog.value = ''; await loadPreview(true) }
  warn(message)
}
async function recoverPending(allowRetry = false) {
  const request = pending.value
  if (!request || saving.value || storageError.value) return
  saving.value = true
  try { const result = await findTubeReceipt(orderId, request.payload.client_request_id); if (!disposed) await completeRequest(result) }
  catch (cause) {
    if (disposed) return
    if (!isAxiosError(cause) || cause.response?.status !== 404) { warn(errorText(cause, '原请求结果仍需核对，请勿重复办理。')); return }
    let replaySubmitted = false
    try {
      const current = await fetchTubeReceiptPreview(orderId)
      if (current.order?.id !== orderId || !current.etag) throw new Error('原单依据不完整，请继续核对原请求。')
      if (current.receipt && current.order.status === 'COMPLETED') {
        // 原POST可能在首次404后刚提交，先二次核对原编号，避免误认为其他操作。
        try { const confirmed = await findTubeReceipt(orderId, request.payload.client_request_id); if (!disposed) { usePreview(current, true); confirmResult(confirmed) } }
        catch (confirmationCause) {
          if (!isAxiosError(confirmationCause) || confirmationCause.response?.status !== 404) throw confirmationCause
          if (!disposed) { usePreview(current, true); clearPending(); dialog.value = ''; readError.value = ''; warn('原请求未登记，此单已由其他操作完成回货。已展示当前真实结果，未重复办理。') }
        }
        return
      }
      if (!allowRetry) { warn('原请求尚未登记。请点击“核对本次提交”，继续使用原请求编号核对。'); return }
      if (current.order.status !== 'PROCESSING' || !current.can_receive || current.etag !== request.etag) { warn('原单状态、版本或操作权限已变化，不能自动重试。请继续核对原请求。'); return }
      replaySubmitted = true
      const result = await confirmTubeReceipt(orderId, request.payload, request.etag)
      if (!disposed) { usePreview(current, true); confirmResult(result) }
    } catch (retryCause) {
      if (disposed) return
      const status = isAxiosError(retryCause) ? retryCause.response?.status : undefined
      if (replaySubmitted && (status === 403 || status === 404)) {
        try { const confirmed = await findTubeReceipt(orderId, request.payload.client_request_id); if (!disposed) confirmResult(confirmed) }
        catch { if (!disposed) warn('原请求结果仍需核对，已保留原请求记录，未生成新操作。') }
      } else if (replaySubmitted && status && [400, 409, 412, 428].includes(status)) await handleRejection(retryCause)
      else warn(errorText(retryCause, '原请求结果仍需核对，请勿重复办理。'))
    }
  } finally { if (!disposed) saving.value = false }
}
async function finishReceipt() {
  if (!validateReceipt() || saving.value) return
  const current = preview.value
  if (!current) return
  let request: TubeReceiptPending
  try {
    if (localStorage.getItem(pendingKey)) { warn('另一个页面有待核对的回货请求，请刷新本页先核对原请求。'); return }
    request = { order_id: orderId, etag: current.etag, payload: { client_request_id: crypto.randomUUID(), receipt_date: receiptDate.value,
      warehouse_id: positiveRows.value.length ? warehouse.value : null, remark: remark.value.trim(),
      lines: rows.value.map(row => ({ order_line_id: row.order_line_id, received_quantity: String(receivedValue(row)), shortage_reason: (difference(row) || 0) > 0 ? row.reason.trim() : '', zone_id: (receivedValue(row) || 0) > 0 ? row.zone : null })) } }
    localStorage.setItem(pendingKey, JSON.stringify(request))
  } catch { warn('浏览器无法保存请求编号，本次尚未提交。请允许本站本地存储后重试。'); return }
  pending.value = request; saving.value = true
  try { const result = await confirmTubeReceipt(orderId, request.payload, request.etag); if (!disposed) confirmResult(result) }
  catch (cause) {
    if (disposed) return
    const status = isAxiosError(cause) ? cause.response?.status : undefined
    if (status && [400, 403, 404, 409, 412, 428].includes(status)) await handleRejection(cause)
    else {
      try { const result = await findTubeReceipt(orderId, request.payload.client_request_id); if (!disposed) confirmResult(result) }
      catch { if (!disposed) { dialog.value = ''; warn('提交结果尚未确认，请点击“核对本次提交”，使用原请求编号核对，避免重复入库或结束。') } }
    }
  } finally { if (!disposed) saving.value = false }
}
async function showReceipt() {
  if (!isEnded.value || pending.value || recordLoading.value || saving.value) return
  recordLoading.value = true
  try { const result = await fetchTubeReceipt(orderId); if (!disposed) { useReceipt(result); document.getElementById('d3-receipt-result')?.scrollIntoView({ block: 'nearest' }) } }
  catch (cause) { if (!disposed) warn(errorText(cause, '本次回货记录读取失败，请重试。')) }
  finally { if (!disposed) recordLoading.value = false }
}
function returnToSource() {
  if (saving.value || pending.value) return
  void router.push(entry === 'order' ? { name: 'workshop-outsourcing-tube-detail', params: { id: orderId } } : { name: 'material-inventory', query: { stock_kind: 'SEMI' } })
}
function restoreRequest(request: TubeReceiptPending) {
  const saved = request.payload
  receiptDate.value = saved.receipt_date; warehouse.value = saved.warehouse_id || ''; remark.value = saved.remark
  for (const row of rows.value) { const line = saved.lines.find(item => item.order_line_id === row.order_line_id); if (line) { row.received = line.received_quantity; row.reason = line.shortage_reason; row.zone = line.zone_id || '' } }
}
onMounted(async () => {
  if (!orderId) return
  try {
    const raw = localStorage.getItem(pendingKey)
    if (raw) {
      const value = JSON.parse(raw) as TubeReceiptPending, payload = value?.payload
      if (value?.order_id !== orderId || typeof value?.etag !== 'string' || !value.etag || !payload || typeof payload.client_request_id !== 'string' || !payload.client_request_id
        || typeof payload.receipt_date !== 'string' || !payload.receipt_date || typeof payload.remark !== 'string'
        || (payload.warehouse_id !== null && typeof payload.warehouse_id !== 'string') || !Array.isArray(payload.lines) || !payload.lines.length
        || !payload.lines.every(line => line && typeof line.order_line_id === 'string' && typeof line.received_quantity === 'string' && /^\d+$/.test(line.received_quantity)
          && typeof line.shortage_reason === 'string' && (line.zone_id === null || typeof line.zone_id === 'string'))) throw new Error('记录不完整')
      pending.value = value
    }
  } catch { storageError.value = true; readError.value = '本地待核对请求无法读取，已暂停办理。请先核对之前的回货结果。'; return }
  if (pending.value) {
    loading.value = true
    try { const result = await fetchTubeReceiptPreview(orderId); if (!disposed) { usePreview(result, false); if (!result.receipt) restoreRequest(pending.value!) } }
    catch (cause) { if (!disposed) readError.value = errorText(cause, '外发单读取失败，请核对原请求。') }
    finally { if (!disposed) loading.value = false }
    if (!disposed) await recoverPending(false)
  } else await loadPreview(false)
})
onBeforeUnmount(() => { disposed = true; previewSequence += 1; candidateSequence += 1; if (searchTimer) clearTimeout(searchTimer) })
</script>

<template>
  <section class="tube-coating-receipt-page d3-page">
    <header class="page-heading">
      <div class="title-row"><h1>喷塑入库</h1><span class="status">外发入库</span><template v-if="order"><span class="status" :class="isEnded ? 'success' : inapplicable ? 'neutral' : 'info'">{{ isEnded ? '已结束' : order.status === 'PENDING_DISPATCH' ? '待外发' : order.status === 'CANCELLED' ? '已取消' : '加工中' }}</span><span class="d3-order-code">{{ order.order_number }}</span></template></div>
      <div class="actions"><ElButton v-if="entry === 'inventory' && !isEnded" :disabled="saving || Boolean(pending) || storageError || !hasPermission" @click="openPicker">选择外发单</ElButton><ElButton :icon="ArrowLeft" :disabled="saving || Boolean(pending)" @click="returnToSource">{{ entry === 'order' ? '返回外发单' : '返回半成品' }}</ElButton></div>
    </header>
    <ElAlert v-if="pending && !showDetails" title="提交结果尚未确认，请核对本次原请求结果，避免重复入库或结束。当前填写内容已锁定。" type="warning" :closable="false" show-icon />
    <ElAlert v-if="storageError" title="本地请求记录无法安全读取或清理，已暂停新操作，请先核对原请求结果。" type="warning" :closable="false" show-icon />
    <template v-if="showDetails">
      <div class="panel d3-context"><div class="info-grid"><div v-for="[label, value] in info" :key="label" class="info-cell"><span>{{ label }}</span><strong :title="String(value || '—')">{{ value || '—' }}</strong></div></div></div>
      <ElAlert v-if="pending" title="提交结果尚未确认，请核对本次原请求结果，避免重复入库或结束。当前填写内容已锁定。" type="warning" :closable="false" show-icon />
      <div id="d3-receipt-result" class="panel workspace d3-workspace">
        <div class="section-heading d3-section-heading"><div><h2>{{ isEnded ? '整单回货结果' : '整单实际回货' }}</h2><span class="muted">{{ isEnded ? '已喷塑 · 本单已登记结束' : '按实物逐部位填写 · 空白或0按未回货登记' }}</span></div><ElButton v-if="!isEnded" :icon="Refresh" :disabled="formLocked" @click="loadPreview(true)">刷新原单</ElButton></div>
        <div v-if="preview?.blockers.length && !isEnded" class="notice warning">{{ preview.blockers.join('；') }}</div>
        <div class="field-grid d3-receipt-fields">
          <label class="form-field required"><span>收货日期</span><ElDatePicker v-model="receiptDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" popper-class="schedule-date-popper tube-coating-date-popper" placeholder="选择日期" aria-label="收货日期" :disabled="!canEdit" /></label>
          <label class="form-field" :class="{ required: positiveRows.length > 0 }"><span>入库仓库 <small v-if="!positiveRows.length" class="muted">无实收可不选</small></span><ElSelect :model-value="warehouse" :disabled="!canEdit" placeholder="选择目标仓库" aria-label="入库仓库" popper-class="tube-coating-select-popper" @update:model-value="requestWarehouseChange"><ElOption v-for="item in warehouses" :key="item.id" :value="item.id" :label="item.name" /><ElOption v-if="receipt?.warehouse_id && !warehouses.some(item => item.id === receipt?.warehouse_id)" :value="receipt.warehouse_id" :label="receipt.warehouse_name" /></ElSelect></label>
          <label class="form-field"><span>入库经办人</span><ElInput :model-value="actorName" readonly aria-label="入库经办人" /></label>
          <label class="form-field"><span>入库状态</span><ElInput model-value="已喷塑" readonly aria-label="入库状态" /></label>
        </div>
        <TubeOutsourcingDetailTable :columns="columns" :rows="rows" class="d3-lines" empty="此外发单没有可办理的实发管材明细">
          <template #cell-part_name="{ row }"><strong>{{ row.part_name }}</strong></template>
          <template #cell-dispatched_quantity="{ row }">{{ format(row.dispatched_quantity) }}</template>
          <template #cell-received="{ row }"><strong v-if="!canEdit" class="brand">{{ receivedValue(row) === null ? '—' : format(receivedValue(row)) }}</strong><ElInput v-else v-model="row.received" inputmode="numeric" :aria-label="`${row.part_name}实收支数`" placeholder="0或空白" @input="onReceivedChange(row)" @blur="validateQuantity(row)"><template #suffix>支</template></ElInput></template>
          <template #cell-difference="{ row }"><strong :class="{ brand: (difference(row) || 0) > 0 }">{{ difference(row) === null ? '—' : format(difference(row)) }}</strong></template>
          <template #cell-reason="{ row }"><span v-if="!canEdit" class="cell-text" :title="(difference(row) || 0) > 0 ? row.reason : '—'">{{ (difference(row) || 0) > 0 ? row.reason : '—' }}</span><ElInput v-else v-model="row.reason" class="reason" :disabled="difference(row) === 0" :aria-label="`${row.part_name}差额原因`" :placeholder="difference(row) === 0 ? '全回，无需填写' : '少回须填写原因'" maxlength="2000" /></template>
          <template #cell-zone="{ row }"><span v-if="!canEdit">{{ zoneLabel(row) }}</span><ElSelect v-else v-model="row.zone" :disabled="!(receivedValue(row) || 0) || !warehouse" :placeholder="(receivedValue(row) || 0) > 0 ? '选择库区' : '不入库'" :aria-label="`${row.part_name}入库库区`" popper-class="tube-coating-select-popper"><ElOption v-for="zone in zones" :key="zone.id" :value="zone.id" :label="zone.name" /></ElSelect></template>
        </TubeOutsourcingDetailTable>
        <label class="form-field d3-remark"><span>入库备注 <small class="muted">选填</small></span><ElInput v-model="remark" type="textarea" :rows="2" :readonly="!canEdit" maxlength="2000" placeholder="填写本次收货或存放说明" aria-label="入库备注" /></label>
      </div>
    </template>
    <div v-else class="panel d3-fallback">
      <ElSkeleton v-if="loading" :rows="9" animated />
      <template v-else><ElEmpty :description="!orderId ? hasPermission ? '请先选择加工中且未登记整单回货的外发单' : '当前账号没有办理喷塑入库的权限' : readError || (order?.status === 'CANCELLED' ? '此外发单已取消，不能办理喷塑入库' : order?.status === 'PENDING_DISPATCH' ? '此外发单尚未实际发出，不能办理喷塑入库' : '暂无可办理的回货明细')" /><ElButton v-if="!orderId" type="primary" :disabled="!hasPermission || Boolean(pending) || storageError" @click="openPicker">选择外发单</ElButton><ElButton v-else-if="readError && ![401, 403, 404].includes(readStatus || 0) && !pending && !storageError" :icon="Refresh" @click="loadPreview(true)">重新加载</ElButton></template>
    </div>
    <footer class="footer-bar d3-footer">
      <div class="d3-footer-total"><span>实发 <strong>{{ showDetails ? format(totalSent) : '—' }}</strong> 支</span><span>实收 <strong>{{ showDetails && !hasInvalidQuantity ? format(totalReceived) : '—' }}</strong> 支</span><span>差额 <strong>{{ showDetails && !hasInvalidQuantity ? format(totalDifference) : '—' }}</strong> 支</span><small v-if="isEnded" :title="receipt?.receipt_number">已结束 · {{ positiveRows.length ? `${positiveRows.length}个部位已入已喷塑公共库存` : '整单实收0支，未增加库存' }}</small></div>
      <ElButton v-if="pending" type="primary" :loading="saving" :disabled="storageError" @click="recoverPending(true)">核对本次提交</ElButton>
      <ElButton v-else-if="isEnded" :loading="recordLoading" @click="showReceipt">查看入库记录</ElButton>
      <ElButton v-else type="primary" :disabled="!canEdit" @click="openConfirm">{{ !hasInvalidQuantity && totalReceived === 0 ? '确认整单结束' : '确认整单入库' }}</ElButton>
    </footer>
  </section>

  <AppWindowDialog :model-value="dialog === 'confirm'" :title="totalReceived ? '确认喷塑入库并结束外发单' : '确认整单0回货并结束外发单'" :width="1640" class="tube-coating-receipt-dialog" :before-close="beforeClose" :close-on-click-modal="!saving" :close-on-press-escape="!saving" @update:model-value="closeDialog">
    <div class="d3-confirm">
      <div class="info-grid d3-confirm-context"><div class="info-cell"><span>外发单号</span><strong>{{ order?.order_number || '—' }}</strong></div><div class="info-cell"><span>生产任务单</span><strong>{{ order?.task_number || '—' }}</strong></div><div class="info-cell"><span>产品名称</span><strong>{{ order?.product_name || '—' }}</strong></div><div class="info-cell"><span>材料来源</span><strong>{{ sourceLabel }}</strong></div><div class="info-cell"><span>收货日期</span><strong>{{ receiptDate }}</strong></div><div class="info-cell"><span>经办人</span><strong>{{ actorName }}</strong></div><div class="info-cell"><span>目标仓库</span><strong>{{ totalReceived ? warehouseLabel : '无实收，不增加库存' }}</strong></div><div class="info-cell"><span>入库状态</span><strong>已喷塑</strong></div></div>
      <TubeOutsourcingDetailTable :columns="columns" :rows="rows" class="d3-confirm-lines">
        <template #cell-part_name="{ row }"><strong>{{ row.part_name }}</strong></template>
        <template #cell-dispatched_quantity="{ row }">{{ format(row.dispatched_quantity) }}</template>
        <template #cell-received="{ row }"><strong class="brand">{{ format(receivedValue(row)) }}</strong></template>
        <template #cell-difference="{ row }"><strong :class="{ brand: (difference(row) || 0) > 0 }">{{ format(difference(row)) }}</strong></template>
        <template #cell-reason="{ row }"><span class="cell-text" :title="row.reason">{{ (difference(row) || 0) > 0 ? row.reason : '—' }}</span></template>
        <template #cell-zone="{ row }">{{ zoneLabel(row) }}</template>
      </TubeOutsourcingDetailTable>
      <div class="d3-confirm-remark"><span class="muted">入库备注</span><p>{{ remark || '—' }}</p></div>
      <div class="notice warning d3-once-note"><strong>整单只登记一次。</strong> {{ totalReceived ? '仅实收大于0的部位按对应库区增加已喷塑公共库存。' : '本次实收全部为0，仅保存回货结果，不增加库存。' }}全部部位（含0支）共同结束，差额及原因保留；确认后不能追加回货或修改本次结果。</div>
    </div>
    <template #footer><div class="d3-confirm-footer"><div><span>实发 <strong>{{ format(totalSent) }}</strong> 支</span><span>实收 <strong>{{ format(totalReceived) }}</strong> 支</span><span>差额 <strong>{{ format(totalDifference) }}</strong> 支</span></div><ElButton :disabled="saving" @click="dialog = ''">返回核对</ElButton><ElButton type="primary" :loading="saving" :disabled="!canEdit" @click="finishReceipt">{{ totalReceived ? '确认入库并结束' : '确认结束' }}</ElButton></div></template>
  </AppWindowDialog>

  <AppWindowDialog :model-value="dialog === 'select'" title="选择喷塑待回货外发单" :width="1600" class="tube-coating-receipt-dialog" @update:model-value="closeDialog">
    <div class="d3-select-order"><div class="filterbar d3-picker-filter"><ElInput v-model="search" :prefix-icon="Search" placeholder="搜索外发单号、生产任务单、产品、加工厂" aria-label="搜索外发单" /><ElSelect v-model="pickerSource" clearable placeholder="全部材料来源" aria-label="筛选材料来源" popper-class="tube-coating-select-popper"><ElOption v-for="[value, label] in sourceOptions" :key="value" :value="value" :label="label" /></ElSelect><span class="spacer" /><span class="muted">加工中 · 已实际发出 · 尚未登记整单回货</span><ElButton :icon="Refresh" :disabled="candidateLoading" @click="loadCandidates(true)">刷新</ElButton></div>
      <ElAlert v-if="candidateError" :title="candidateError" type="error" :closable="false" show-icon><ElButton link :disabled="candidateLoading" @click="loadCandidates(candidatePage === 0)">重试</ElButton></ElAlert>
      <TubeOutsourcingDetailTable :columns="pickerColumns" :rows="candidates" class="d3-picker-lines" :empty="candidateLoading ? '正在加载待回货外发单…' : '暂无符合条件的待回货外发单'" @scroll="candidateScrolled"><template #cell-source_label="{ row }">{{ labels[row.source_kind] }}</template><template #cell-factory_names="{ row }"><span class="cell-text" :title="row.factory_names.join('、')">{{ row.factory_names.join('、') }}</span></template><template #cell-total_quantity="{ row }">{{ format(row.total_quantity) }}</template><template #cell-status><span class="status info">加工中</span></template><template #cell-action="{ row }"><ElButton link :aria-label="`选择${row.order_number}`" @click="selectOrder(row)">选择并办理</ElButton></template></TubeOutsourcingDetailTable>
      <div v-if="candidateLoading && candidates.length" class="d3-picker-loading muted">正在加载下一页…</div>
    </div><template #footer><ElButton @click="dialog = ''">关闭</ElButton></template>
  </AppWindowDialog>

  <AppWindowDialog :model-value="dialog === 'warehouse'" title="切换目标仓库" :width="620" class="tube-coating-receipt-dialog" @update:model-value="closeDialog">
    <div class="d3-warehouse-confirm"><p>切换至<strong>{{ warehouses.find(item => item.id === pendingWarehouse)?.name }}</strong>后，各部位需要重新选择新仓库下的库区。</p><p class="muted">已填写的实收支数、差额原因和备注全部保留。</p></div><template #footer><ElButton @click="dialog = ''; pendingWarehouse = ''">保留原仓库</ElButton><ElButton type="primary" @click="confirmWarehouseChange">切换仓库</ElButton></template>
  </AppWindowDialog>
</template>
