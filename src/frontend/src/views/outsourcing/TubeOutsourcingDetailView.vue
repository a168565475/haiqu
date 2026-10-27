<script setup lang="ts">
import { compactDecimal } from '@/utils/compactDecimal'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Document, Refresh } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import TubeOutsourcingDetailTable from '@/components/outsourcing/TubeOutsourcingDetailTable.vue'
import TubeOutsourcingEndedResult from '@/components/outsourcing/TubeOutsourcingEndedResult.vue'
import { cancelTubeOrder, dispatchTubeOrder, fetchTubeOrder, findTubeAction } from '@/api/tubeOutsourcing'
import { fetchTubeReceiptPreview } from '@/api/tubeReceipts'
import { useAuthStore } from '@/stores/auth'
import type { TubeCancelInput, TubeDetailLine, TubeDispatchInput, TubeOrderDetail, TubePendingAction } from '@/types/tubeOutsourcing'
import type { TubeReceipt, TubeReceiptPreview } from '@/types/tubeReceipts'
import { formatOutsourcingMoney } from '@/utils/outsourcingPrices'
import { isCuttingSource, isDirectSource, tubeSourceLabels } from '@/utils/tubeOutsourcing'
import '@/styles/tubeOutsourcingDetail.scss'

interface Column { key: string; label: string; width: number; num?: boolean }
const route = useRoute(), router = useRouter(), auth = useAuthStore()
const warehouseWorkspace = computed(() => route.meta?.outsourcingWorkspace === 'warehouse')
const warehouseArgs = computed<[true] | []>(() => warehouseWorkspace.value ? [true] : [])
const listPath = computed(() => warehouseWorkspace.value ? '/warehouse/outsourcing' : '/workshop/outsourcing')
const orderId = typeof route.params.id === 'string' ? route.params.id : ''
const detail = ref<TubeOrderDetail | null>(null)
const receipt = ref<TubeReceipt | null>(null)
const receiptPermissionEtag = ref('')
const endedPresentation = ref(true)
const loading = ref(false), saving = ref(false), readError = ref(''), readStatus = ref<number | undefined>()
const recheckError = ref(''), storageError = ref(false), pending = ref<TubePendingAction | null>(null)
const dialog = ref<'' | 'dispatch' | 'cancel' | 'basis'>(''), selectedPart = ref<TubeDetailLine | null>(null)
const today = new Date()
const dispatchDate = ref(`${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`)
const cancellationRemark = ref('')
const pendingKey = `tube-outsourcing-action:v1:${auth.user?.id || 'unknown'}:${orderId}`
let disposed = false, readSequence = 0

const labels = tubeSourceLabels
const stateLabels: Record<string, string> = { PENDING_DISPATCH: '待外发', PROCESSING: '加工中', CANCELLED: '已取消', COMPLETED: '已结束' }
const source = computed(() => detail.value?.source_kind)
const cutting = computed(() => isCuttingSource(source.value))
const direct = computed(() => isDirectSource(source.value))
const categoryName = computed(() => cutting.value ? '裁片' : '管材')
const materialName = computed(() => cutting.value ? '辅料' : '五金')
const quantityUnit = computed(() => cutting.value ? '套' : '支')
const receiptTitle = computed(() => cutting.value ? `${detail.value?.craft_name || '裁片'}入库` : '喷塑入库')
const sourceLabel = computed(() => source.value ? labels[source.value] || '—' : '—')
const state = computed(() => detail.value?.status || '')
const stateLabel = computed(() => stateLabels[state.value] || '—')
const showDetails = computed(() => Boolean(detail.value) && !loading.value && !readError.value)
const rows = computed(() => detail.value?.lines || [])
const materialRows = computed(() => detail.value?.materials || [])
const actorName = computed(() => auth.user?.employee?.display_name || auth.user?.display_name || auth.user?.username || '—')
const locked = computed(() => loading.value || saving.value || Boolean(pending.value) || storageError.value || !showDetails.value)
const hasLines = computed(() => rows.value.length > 0 && Number(detail.value?.total_quantity) > 0)
const dispatchWorkspace = computed(() => Boolean(source.value) && warehouseWorkspace.value)
const canDispatch = computed(() => dispatchWorkspace.value && !locked.value && hasLines.value && state.value === 'PENDING_DISPATCH' && detail.value?.permissions.can_dispatch === true)
const canCancel = computed(() => !warehouseWorkspace.value && !locked.value && hasLines.value && state.value === 'PENDING_DISPATCH' && detail.value?.permissions.can_cancel === true)
const canCreate = computed(() => !warehouseWorkspace.value && Boolean(auth.user?.is_superuser || auth.hasPermission('outsourcing.add_outsourcingorder')))
const canReceive = computed(() => warehouseWorkspace.value && !locked.value && state.value === 'PROCESSING'
  && receiptPermissionEtag.value === detail.value?.etag
  && Boolean(auth.user?.is_superuser || auth.hasPermission('outsourcing.confirm_return_outsourcingorder')))
const hasDispatched = computed(() => ['PROCESSING', 'COMPLETED'].includes(state.value))
const quantityLabel = computed(() => `${hasDispatched.value ? '已发' : state.value === 'CANCELLED' ? '原单' : '待发'}${quantityUnit.value}数`)
const footerLabel = computed(() => hasDispatched.value ? '已发出' : state.value === 'CANCELLED' ? '原单数量' : '待发出')
const locationLabel = computed(() => direct.value ? `${cutting.value ? '车缝' : '金工'}车间 · 已报工未入库` : [detail.value?.warehouse_name, detail.value?.zone_name].filter(Boolean).join(' / ') || '—')
const stockImpact = computed(() => {
  const pipeImpact = source.value === 'RAW_PIPE' ? '按原单整根换算，扣除原材料根数与米数。' : source.value === 'PUBLIC_SEMI' ? '按发出支数扣除公共未喷塑半成品库存。' : source.value === 'METAL' ? '计入金工已直发数量，不重复扣除原材料库存。' : source.value === 'PUBLIC_CUTTING' ? '按发出套数扣除公共裁片半成品库存。' : source.value === 'SEWING' ? '计入车缝已直发数量，不重复扣除原材料库存。' : '—'
  return `${pipeImpact}${materialRows.value.length ? `附带${materialName.value}按原单数量从各自来源库区一并扣减。` : ''}`
})
const statusNote = computed(() => state.value === 'PENDING_DISPATCH' ? '已保存待发 · 实际发出后才扣库存或登记直发' : state.value === 'PROCESSING' ? `整单已发出 · ${cutting.value ? detail.value?.craft_name || '加工' : '喷塑'}回货后一次登记入库` : state.value === 'COMPLETED' ? '整单回货已登记结束' : state.value === 'CANCELLED' ? '原单保留 · 已释放待发预留 · 未办理实际发出' : '')
const info = computed(() => [
  ['生产任务单', detail.value?.task_number], ['订单号', detail.value?.task_order_number], ['排产单号', detail.value?.schedule_number],
  ['订单量', detail.value ? `${format(detail.value.quantity)} ${detail.value.unit || ''}` : '—'], ['计划发出日', detail.value?.planned_dispatch_date], ['预计回货日', detail.value?.expected_return_date],
  ['产品名称', detail.value?.product_name], ['品号', detail.value?.product_number], ['货号', detail.value?.item_number],
  [cutting.value ? '外发工艺' : '订单喷塑色', cutting.value ? detail.value?.craft_name : detail.value?.color], ['建单日期', dateText(detail.value?.created_at)], ['建单人', detail.value?.created_by_name],
])
const commonColumns: Column[] = [
  { key: 'part_name', label: '部位', width: 100 }, { key: 'material', label: '材质', width: 75 },
  { key: 'specification', label: '规格', width: 140 }, { key: 'thickness', label: '厚度 mm', width: 85 },
  { key: 'cutting_length_mm', label: '切割长度 mm', width: 110 }, { key: 'raw_color', label: '原料颜色', width: 100 },
  { key: 'spray_color', label: '喷塑颜色', width: 90 }, { key: 'factory_name', label: '加工厂', width: 130 },
]
const columns = computed<Column[]>(() => [
  ...(cutting.value ? [
    { key: 'part_name', label: '部位', width: 100 }, { key: 'fabric_material', label: '材质', width: 90 },
    { key: 'specification', label: '规格', width: 140 }, { key: 'fabric_color', label: '颜色', width: 90 },
    { key: 'pieces_per_set', label: '每套片数', width: 90, num: true }, { key: 'completed_craft_name', label: '加工状态', width: 100 },
    { key: 'factory_name', label: '加工厂', width: 130 },
  ] : commonColumns),
  ...(source.value === 'RAW_PIPE' ? [{ key: 'pieces_per_bar', label: '切割支数 支/根', width: 115, num: true }, { key: 'raw_bar_length_m', label: '原材料长度 m/根', width: 130, num: true }] : []),
  ...(direct.value ? [{ key: 'current_reported_minimum', label: `当前最低报工（${quantityUnit.value}）`, width: 150, num: true }] : []),
  { key: 'quantity', label: `${quantityLabel.value}（${quantityUnit.value}）`, width: 130, num: true },
  ...(source.value === 'RAW_PIPE' ? [
    { key: 'stock_quantity', label: hasDispatched.value ? '已扣（根）' : state.value === 'CANCELLED' ? '原单折算（根）' : '待扣（根）', width: 105, num: true },
    { key: 'meters', label: hasDispatched.value ? '已扣（米）' : state.value === 'CANCELLED' ? '原单折算（米）' : '待扣（米）', width: 115, num: true },
  ] : []),
  { key: 'unit_price', label: `加工单价（元/${quantityUnit.value}）`, width: 145, num: true },
  { key: 'planned_amount', label: '计划金额（元）', width: 135, num: true },
])
const dispatchColumns = computed(() => columns.value.filter(column => column.key !== 'current_reported_minimum').map(column => ({ ...column, label: column.key === 'quantity' ? `发出${quantityUnit.value}数（${quantityUnit.value}）` : column.key === 'stock_quantity' ? '本次扣（根）' : column.key === 'meters' ? '本次扣（米）' : column.label })))
const materialColumns: Column[] = [
  { key: 'name', label: '材料名称', width: 150 }, { key: 'specification', label: '规格', width: 120 },
  { key: 'material', label: '材质', width: 90 }, { key: 'color', label: '颜色', width: 90 },
  { key: 'factory_name', label: '加工厂', width: 140 },
  { key: 'quantity', label: '外发数量', width: 120, num: true }, { key: 'unit', label: '单位', width: 70 },
  { key: 'warehouse_name', label: '来源仓库', width: 130 }, { key: 'zone_name', label: '来源库区', width: 120 },
]
const operationColumns = computed<Column[]>(() => [{ key: 'name', label: '必需工序', width: 270 }, { key: 'quantity', label: `有效累计报工（${quantityUnit.value}）`, width: 240, num: true }, { key: 'basis', label: '完成依据', width: 220 }])
const schemeLabel = computed(() => {
  const operations = selectedPart.value?.operations || []
  const schemes = [...new Set(operations.filter(item => item.scheme_id).map(item => `${item.scheme_number || '编号待核对'} · V${item.scheme_version ?? item.scheme_revision}`))]
  return schemes.length ? `工价方案 ${schemes.join('、')}` : '工价方案依据待核对'
})
function format(value: unknown): string {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '—'
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}
function meters(value: unknown): string { return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? compactDecimal(Number(value).toFixed(2)) : '—' }
function materialQuantity(value: unknown): string {
  return value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}
function dateText(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
function errorText(cause: unknown, fallback: string): string {
  if (isAxiosError(cause)) {
    const body = cause.response?.data as { error?: { message?: string }; detail?: string } | undefined
    return body?.error?.message || (typeof body?.detail === 'string' ? body.detail : fallback)
  }
  return cause instanceof Error ? cause.message : fallback
}
function warn(message: string) { ElMessage.closeAll(); ElMessage.warning({ message, duration: 4500 }) }
async function loadDetail() {
  if (saving.value || pending.value || storageError.value) return
  const sequence = ++readSequence
  loading.value = true; readError.value = ''; readStatus.value = undefined
  detail.value = null; receipt.value = null; receiptPermissionEtag.value = ''
  try {
    let result: TubeOrderDetail
    let finalReceipt: TubeReceipt | null = null
    let preview: TubeReceiptPreview | null = null
    try {
      // 终态直接读取原单及最终凭证，不先查普通详情的动态最低报工。
      preview = await fetchTubeReceiptPreview(orderId, ...warehouseArgs.value)
    } catch (cause) {
      if (!isAxiosError(cause) || cause.response?.status !== 403) throw cause
      // 非终态预览需要回货权限；仅查看用户仍沿原详情的权限检查。
    }
    if (disposed || sequence !== readSequence) return
    if (preview && (!preview.order || preview.order.id !== orderId || !preview.order.etag || !Array.isArray(preview.order.lines))) throw new Error('外发单详情不完整，请重新加载。')
    if (preview?.order.status === 'COMPLETED') { result = preview.order; finalReceipt = preview.receipt }
    else {
      result = await fetchTubeOrder(orderId, ...warehouseArgs.value)
      // 两次读取之间可能完成回货，此时重新读取最终凭证。
      if (result.status === 'COMPLETED') { const completed = await fetchTubeReceiptPreview(orderId, ...warehouseArgs.value); result = completed.order; finalReceipt = completed.receipt }
    }
    if (disposed || sequence !== readSequence) return
    if (result.id !== orderId || !result.etag || !Array.isArray(result.lines)) throw new Error('外发单详情不完整，请重新加载。')
    detail.value = result; receipt.value = finalReceipt; endedPresentation.value = result.status === 'COMPLETED'; recheckError.value = ''
    receiptPermissionEtag.value = preview?.can_receive === true ? preview.etag : ''
  } catch (cause) {
    if (disposed || sequence !== readSequence) return
    readStatus.value = isAxiosError(cause) ? cause.response?.status : undefined
    readError.value = errorText(cause, '外发单读取失败，请重新加载。')
  } finally { if (!disposed && sequence === readSequence) loading.value = false }
}
function openDispatch() { if (canDispatch.value) dialog.value = 'dispatch' }
function openCancel() { if (canCancel.value) { cancellationRemark.value = ''; dialog.value = 'cancel' } }
let openedEntryAction = ''
watch(() => [showDetails.value, route.query?.action, warehouseWorkspace.value], () => {
  if (route.query?.action !== 'dispatch' || openedEntryAction || !canDispatch.value) return
  openedEntryAction = 'dispatch'
  openDispatch()
})
function openBasis(row: TubeDetailLine) { selectedPart.value = row; dialog.value = 'basis' }
function closeDialog(value: boolean) { if (!value && !saving.value) dialog.value = '' }
function beforeClose(done: () => void) { if (!saving.value) done() }
function clearPending(): boolean {
  try { localStorage.removeItem(pendingKey); pending.value = null; return true }
  catch { storageError.value = true; warn('业务结果已确认，但本地请求记录未能清理。请恢复浏览器存储后刷新页面。'); return false }
}
function applyResult(result: TubeOrderDetail) {
  const action = pending.value
  if (!action || result.id !== action.order_id || result.action?.client_request_id !== action.payload.client_request_id || result.action.kind !== action.kind
    || !(action.kind === 'DISPATCH' ? ['PROCESSING', 'COMPLETED'].includes(result.status) : result.status === 'CANCELLED') || !result.etag || !Array.isArray(result.lines)) throw new Error('操作结果不完整，请继续核对原请求。')
  detail.value = result; readError.value = ''; readStatus.value = undefined; recheckError.value = ''; dialog.value = ''
  clearPending()
  ElMessage.success({ message: action.kind === 'DISPATCH' ? '整单已按原单数量完成实际发出。' : '外发单已取消，原单保留，待发预留已释放。', duration: 5000 })
}
async function recoverPending(allowRetry = false) {
  const action = pending.value
  if (!action || saving.value || storageError.value) return
  saving.value = true
  try {
    const result = await findTubeAction(action.order_id, action.payload.client_request_id, ...warehouseArgs.value)
    if (!disposed) applyResult(result)
  } catch (cause) {
    if (disposed) return
    if (isAxiosError(cause) && cause.response?.status === 404) {
      let replaySubmitted = false
      try {
        // 原请求未登记时仍只能重放原编号、原内容、原版本；先读取真实状态及权限。
        const current = await fetchTubeOrder(action.order_id, ...warehouseArgs.value)
        if (current.id !== action.order_id || !current.etag || !Array.isArray(current.lines)) throw new Error('原单详情不完整，请继续核对原请求。')
        if (['PROCESSING', 'COMPLETED', 'CANCELLED'].includes(current.status)) {
          // 第一次404和读取终态之间，原POST可能刚提交；再次查原编号后才能归因。
          try { const confirmed = await findTubeAction(action.order_id, action.payload.client_request_id, ...warehouseArgs.value); if (!disposed) applyResult(confirmed) }
          catch (confirmationCause) {
            if (!isAxiosError(confirmationCause) || confirmationCause.response?.status !== 404) throw confirmationCause
            if (!disposed) {
              detail.value = current; readError.value = ''; readStatus.value = undefined; dialog.value = ''; recheckError.value = ''
              clearPending()
              warn('原请求未登记，单据已由其他操作处理。已按当前真实状态展示，未重复办理。')
            }
          }
          return
        }
        if (!allowRetry) { warn('原请求尚未登记。请点击“核对本次提交”，使用原请求编号继续核对。'); return }
        const allowed = action.kind === 'DISPATCH'
          ? warehouseWorkspace.value && current.permissions.can_dispatch
          : !warehouseWorkspace.value && current.permissions.can_cancel
        if (current.id !== action.order_id || current.status !== 'PENDING_DISPATCH' || current.etag !== action.etag || !allowed) {
          if (!disposed) warn('原请求尚未登记，但原单状态、版本或操作权限已变化，不能自动重试。请继续核对原请求。')
          return
        }
        replaySubmitted = true
        const result = action.kind === 'DISPATCH' ? await dispatchTubeOrder(action.order_id, action.payload as TubeDispatchInput, action.etag) : await cancelTubeOrder(action.order_id, action.payload as TubeCancelInput, action.etag)
        if (!disposed) applyResult(result)
      } catch (retryCause) {
        if (disposed) return
        const status = isAxiosError(retryCause) ? retryCause.response?.status : undefined
        const message = errorText(retryCause, '原请求结果仍未确认，请继续核对，不要重新发出或取消。')
        if (replaySubmitted && (status === 403 || status === 404)) {
          // 权限/入口拒绝重放，不证明先前在途请求未提交；再次查原编号，失败仍保留记录。
          try { const confirmed = await findTubeAction(action.order_id, action.payload.client_request_id, ...warehouseArgs.value); if (!disposed) applyResult(confirmed) }
          catch { if (!disposed) warn(`${message} 原请求结果仍需核对，已保留请求记录，未生成新操作。`) }
          return
        }
        if (replaySubmitted && status && [400, 409, 412, 428].includes(status) && clearPending()) {
          saving.value = false; dialog.value = ''
          await loadDetail()
          if (action.kind === 'DISPATCH' && [400, 409, 412, 428].includes(status)) recheckError.value = message
        }
        warn(message)
      }
    } else warn(errorText(cause, '提交结果尚未确认，请继续核对原请求，不要重复发出或取消。'))
  } finally { if (!disposed) saving.value = false }
}
async function submit(kind: 'DISPATCH' | 'CANCEL') {
  if (kind === 'DISPATCH' ? !canDispatch.value : !canCancel.value) return
  if (kind === 'DISPATCH' && !dispatchDate.value) { warn('请选择实际发出日期。'); return }
  const current = detail.value
  if (!current) return
  let action: TubePendingAction
  try {
    // 写入之前固定请求编号和版本，刷新、超时后仅查询这个编号，不重复写。
    if (localStorage.getItem(pendingKey)) { warn('另一个页面有待核对的操作，请刷新本页核对后再办理。'); return }
    const requestId = crypto.randomUUID()
    action = { order_id: orderId, kind, etag: current.etag, payload: kind === 'DISPATCH' ? { client_request_id: requestId, actual_dispatch_date: dispatchDate.value } : { client_request_id: requestId, remark: cancellationRemark.value.trim() } }
    localStorage.setItem(pendingKey, JSON.stringify(action))
  } catch { warn('浏览器无法保存请求编号，本次尚未提交。请允许本站本地存储后重试。'); return }
  pending.value = action; saving.value = true; recheckError.value = ''
  try {
    const result = kind === 'DISPATCH' ? await dispatchTubeOrder(orderId, action.payload as TubeDispatchInput, action.etag) : await cancelTubeOrder(orderId, action.payload as TubeCancelInput, action.etag)
    if (!disposed) applyResult(result)
  } catch (cause) {
    if (disposed) return
    const status = isAxiosError(cause) ? cause.response?.status : undefined
    if (status && [400, 403, 404, 409, 412, 428].includes(status)) {
      const message = errorText(cause, '操作未能办理，请刷新后核对原单。')
      if (clearPending()) {
        dialog.value = ''; saving.value = false
        await loadDetail()
        if (kind === 'DISPATCH' && [400, 409, 412, 428].includes(status)) recheckError.value = message
      }
      warn(message)
    } else {
      // 连接中断、服务器错误或登录失效不能等同于未写入，先查原请求。
      try { if (!disposed) applyResult(await findTubeAction(action.order_id, action.payload.client_request_id, ...warehouseArgs.value)) }
      catch { if (!disposed) { dialog.value = ''; warn('提交结果尚未确认，请点击“核对本次提交”，继续核对原请求，避免重复办理。') } }
    }
  } finally { if (!disposed) saving.value = false }
}
function recreate() {
  if (!detail.value || locked.value || state.value !== 'CANCELLED' || !canCreate.value) return
  void router.push({ name: 'workshop-outsourcing-tube-new', query: { ...(cutting.value ? { category: 'cutting', craft_id: detail.value.craft_id } : {}), schedule_product_id: detail.value.schedule_product_id, source_kind: detail.value.source_kind, ...(detail.value.zone_id ? { zone_id: detail.value.zone_id } : {}) } })
}
onMounted(async () => {
  if (!orderId) { readError.value = '外发单编号缺失，请返回列表重新打开。'; return }
  try {
    const raw = localStorage.getItem(pendingKey)
    if (raw) {
      const value = JSON.parse(raw) as TubePendingAction
      if (!value || value.order_id !== orderId || !['DISPATCH', 'CANCEL'].includes(value.kind) || typeof value.etag !== 'string' || !value.etag
        || !value.payload || typeof value.payload.client_request_id !== 'string' || !value.payload.client_request_id
        || (value.kind === 'DISPATCH' ? typeof (value.payload as TubeDispatchInput).actual_dispatch_date !== 'string' : typeof (value.payload as TubeCancelInput).remark !== 'string')) throw new Error('记录不完整')
      pending.value = value
    }
  } catch { storageError.value = true; readError.value = '本地待核对记录无法读取，已暂停办理。请先核对之前的操作结果。'; return }
  if (pending.value) {
    // 详情可读，动作结果仍只按已保存的原请求编号核对。
    try { detail.value = await fetchTubeOrder(orderId, ...warehouseArgs.value); endedPresentation.value = false } catch (cause) { readError.value = errorText(cause, '外发单读取失败。') }
    await recoverPending()
  } else await loadDetail()
})
onBeforeUnmount(() => { disposed = true; readSequence += 1 })
</script>

<template>
  <section class="tube-outsourcing-detail-page d4-page" :class="{ 'd4-ended-page': endedPresentation || state === 'COMPLETED' }">
    <header class="page-heading">
      <div class="title-row"><h1>{{ categoryName }}外发单</h1><span v-if="state" class="status" :class="state === 'COMPLETED' ? 'success' : state === 'PROCESSING' ? 'info' : state === 'CANCELLED' ? 'neutral' : 'warning'">{{ stateLabel }}</span><span v-if="source" class="status">{{ sourceLabel }}</span><span v-if="detail" class="d4-order-code">{{ detail.order_number }}</span></div>
      <ElButton :icon="ArrowLeft" :disabled="saving" @click="router.push(listPath)">返回列表</ElButton>
    </header>
    <ElAlert v-if="pending" type="warning" :closable="false" show-icon title="提交结果尚未确认，请核对原请求结果，避免再次发出或取消。" />
    <ElAlert v-else-if="recheckError" type="warning" :closable="false" show-icon :title="`${recheckError} 尚未发出。可刷新重核原单数量；需要改量、加工厂或库区时，取消后重新创建。`" />
    <ElAlert v-if="storageError" type="warning" :closable="false" show-icon title="本地请求记录无法安全读取或清理，已暂停新操作，请先核对原请求结果。" />
    <section v-if="showDetails && state === 'COMPLETED' && !pending && materialRows.length" class="panel d4-material-panel d4-ended-materials" :aria-label="`附带${materialName}`">
      <div class="section-heading"><h2>附带{{ materialName }} · {{ materialRows.length }} 项</h2><span class="muted">按所选加工厂随本单一起发出，不单独回货</span></div>
      <TubeOutsourcingDetailTable :columns="materialColumns" :rows="materialRows" class="d4-material-lines">
        <template #cell-quantity="{ row }">{{ materialQuantity(row.quantity) }}</template>
        <template #cell-unit="{ row }">{{ row.unit || '单位未识别' }}</template>
      </TubeOutsourcingDetailTable>
    </section>
    <TubeOutsourcingEndedResult v-if="showDetails && state === 'COMPLETED' && !pending && detail" :order="detail" :receipt="receipt" @refresh="loadDetail" />
    <template v-else-if="showDetails">
      <div class="panel d4-context"><div class="info-grid"><div v-for="[label, value] in info" :key="label" class="info-cell"><span>{{ label }}</span><strong :title="String(value || '—')">{{ value || '—' }}</strong></div></div></div>
      <div class="panel workspace d4-workspace" :class="{ 'd4-workspace--with-materials': materialRows.length > 0 }">
        <div class="section-heading d4-section-heading"><div><h2>外发明细</h2><span class="muted">{{ locationLabel }}</span></div><div class="d4-section-actions"><span class="d4-state-note muted">{{ statusNote }}</span><ElButton :icon="Refresh" :disabled="locked" @click="loadDetail">刷新</ElButton></div></div>
        <div v-if="state !== 'PENDING_DISPATCH'" class="d4-lifecycle">
          <template v-if="hasDispatched"><span class="muted">实际发出日期</span><strong>{{ detail?.actual_dispatch_date || '—' }}</strong><span class="muted">发出经办人</span><strong>{{ detail?.dispatched_by_name || '—' }}</strong></template>
          <template v-else-if="state === 'CANCELLED'"><span class="muted">取消日期</span><strong>{{ dateText(detail?.cancelled_at) }}</strong><span class="muted">取消人</span><strong>{{ detail?.cancelled_by_name || '—' }}</strong><span class="muted">取消备注</span><strong class="d4-cancellation-note" :title="detail?.cancel_remark || '—'">{{ detail?.cancel_remark || '—' }}</strong></template>
        </div>
        <TubeOutsourcingDetailTable :columns="columns" :rows="rows" class="d4-lines" :empty="`此外发单没有可办理的${categoryName}明细`">
          <template #cell-part_name="{ row }"><strong>{{ row.part_name || '—' }}</strong></template>
          <template #cell-current_reported_minimum="{ row }"><ElTooltip :content="row.basis_blockers?.join('；') || '查看该部位各必需工序的有效累计报工'" placement="top"><ElButton link :aria-label="`${row.part_name}最低报工`" @click="openBasis(row)">{{ format(row.current_reported_minimum) }}</ElButton></ElTooltip></template>
          <template #cell-quantity="{ row }"><strong class="brand">{{ format(row.quantity) }}</strong></template>
          <template #cell-pieces_per_bar="{ row }">{{ format(row.pieces_per_bar) }}</template>
          <template #cell-raw_bar_length_m="{ row }">{{ meters(row.raw_bar_length_m) }}</template>
          <template #cell-stock_quantity="{ row }">{{ format(row.stock_quantity) }}</template>
          <template #cell-meters="{ row }">{{ meters(row.meters) }}</template>
          <template #cell-unit_price="{ row }">{{ formatOutsourcingMoney(row.unit_price) }}</template>
          <template #cell-planned_amount="{ row }">{{ formatOutsourcingMoney(row.planned_amount) }}</template>
        </TubeOutsourcingDetailTable>
        <section v-if="materialRows.length" class="d4-material-panel" :aria-label="`附带${materialName}`">
          <div class="section-heading"><h2>附带{{ materialName }} · {{ materialRows.length }} 项</h2><span class="muted">按所选加工厂随本单一起发出，不单独回货</span></div>
          <TubeOutsourcingDetailTable :columns="materialColumns" :rows="materialRows" class="d4-material-lines">
            <template #cell-quantity="{ row }">{{ materialQuantity(row.quantity) }}</template>
            <template #cell-unit="{ row }">{{ row.unit || '单位未识别' }}</template>
          </TubeOutsourcingDetailTable>
        </section>
        <div class="d4-order-remark"><span class="muted">原单备注</span><p>{{ detail?.remark || '—' }}</p></div>
      </div>
    </template>
    <div v-else class="panel d4-fallback"><ElSkeleton v-if="loading" :rows="9" animated /><template v-else><ElEmpty :description="readError || '此外发单暂无可查看的详情'" /><ElButton v-if="![401, 403, 404].includes(readStatus || 0) && !pending && !storageError" :icon="Refresh" @click="loadDetail">重新加载</ElButton></template></div>
    <footer v-if="!showDetails && endedPresentation && !pending && !storageError" class="footer-bar d4-ended-footer"><div class="totals"><span>实发 <strong>—</strong> {{ quantityUnit }}</span><span>实收 <strong>—</strong> {{ quantityUnit }}</span><span>差额 <strong>—</strong> {{ quantityUnit }}</span><small>仅读取历史结果，不办理入库</small></div><ElButton type="primary" :icon="Document" disabled>查看入库凭证</ElButton></footer>
    <footer v-else-if="!(showDetails && state === 'COMPLETED' && !pending)" class="footer-bar d4-footer">
      <div>{{ footerLabel }} <strong>{{ showDetails ? format(detail?.total_quantity) : '—' }}</strong> {{ quantityUnit }} <span v-if="showDetails" class="muted"> · {{ rows.length }} 个部位<span v-if="source === 'RAW_PIPE'"> · {{ format(detail?.total_stock_quantity) }} 根 / {{ meters(detail?.total_meters) }} 米</span></span><span v-if="showDetails" class="d4-planned-amount"> · 计划加工金额 <strong>{{ formatOutsourcingMoney(detail?.planned_amount) }}</strong> 元</span><small>{{ state === 'CANCELLED' ? '已取消 · 仓库库存未扣减' : state === 'COMPLETED' ? '整单回货已登记结束' : state === 'PROCESSING' ? '已按整单数量完成发出' : stockImpact }}</small></div>
      <ElButton v-if="pending" type="primary" :loading="saving" :disabled="storageError" @click="recoverPending(true)">核对本次提交</ElButton>
      <template v-else-if="state === 'PENDING_DISPATCH'"><ElTooltip v-if="!warehouseWorkspace" :disabled="detail?.permissions.can_cancel !== false" content="当前账号没有取消权限"><span><ElButton :disabled="!canCancel" @click="openCancel">取消外发单</ElButton></span></ElTooltip><ElTooltip v-if="dispatchWorkspace" :disabled="detail?.permissions.can_dispatch !== false" content="当前账号没有实际发出权限"><span><ElButton type="primary" :disabled="!canDispatch" @click="openDispatch">确认实际发出</ElButton></span></ElTooltip></template>
      <ElButton v-else-if="state === 'PROCESSING' && warehouseWorkspace" type="primary" :disabled="!canReceive" @click="canReceive && router.push({ name: 'warehouse-outsourcing-tube-return', params: { id: orderId } })">{{ receiptTitle }}</ElButton>
      <ElButton v-else-if="state === 'CANCELLED' && !warehouseWorkspace" :disabled="locked || !hasLines || !canCreate" type="primary" @click="recreate">重新创建外发单</ElButton>
    </footer>
  </section>

  <AppWindowDialog :model-value="dialog === 'dispatch'" title="确认实际发出" :width="source === 'RAW_PIPE' ? 1480 : 1240" class="tube-outsourcing-detail-dialog" :before-close="beforeClose" :close-on-click-modal="!saving" :close-on-press-escape="!saving" @update:model-value="closeDialog">
    <div class="d4-dispatch">
      <div class="d4-dialog-context"><strong>{{ detail?.order_number || '—' }}</strong><span>{{ sourceLabel }}</span><span>{{ detail?.task_number || '—' }}</span><span>{{ detail?.product_name || '—' }}</span></div>
      <div class="field-grid d4-dispatch-fields">
        <label class="form-field required"><span>实际发出日期</span><ElDatePicker v-model="dispatchDate" :disabled="saving || Boolean(pending)" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" popper-class="schedule-date-popper tube-outsourcing-detail-date-popper" placeholder="选择日期" aria-label="实际发出日期" /></label>
        <label class="form-field"><span>发出经办人</span><ElInput :model-value="actorName" aria-label="发出经办人" readonly /></label>
        <div class="form-field d4-dispatch-location"><span>材料位置</span><strong>{{ locationLabel }}</strong></div>
      </div>
      <div class="d4-dialog-section"><h2>整单发出明细</h2><span class="muted">按原单已保存数量一次发出 · 数量只读</span></div>
      <TubeOutsourcingDetailTable :columns="dispatchColumns" :rows="rows" class="d4-dispatch-lines">
        <template #cell-part_name="{ row }"><strong>{{ row.part_name || '—' }}</strong></template>
        <template #cell-quantity="{ row }"><strong class="brand">{{ format(row.quantity) }}</strong></template>
        <template #cell-pieces_per_bar="{ row }">{{ format(row.pieces_per_bar) }}</template>
        <template #cell-raw_bar_length_m="{ row }">{{ meters(row.raw_bar_length_m) }}</template>
        <template #cell-stock_quantity="{ row }">{{ format(row.stock_quantity) }}</template>
        <template #cell-meters="{ row }">{{ meters(row.meters) }}</template>
          <template #cell-unit_price="{ row }">{{ formatOutsourcingMoney(row.unit_price) }}</template>
          <template #cell-planned_amount="{ row }">{{ formatOutsourcingMoney(row.planned_amount) }}</template>
      </TubeOutsourcingDetailTable>
      <template v-if="materialRows.length">
        <div class="d4-dialog-section"><h2>附带{{ materialName }} · {{ materialRows.length }} 项</h2><span class="muted">按所选加工厂随本单一起发出，不单独回货</span></div>
        <TubeOutsourcingDetailTable :columns="materialColumns" :rows="materialRows" class="d4-dispatch-material-lines">
          <template #cell-quantity="{ row }">{{ materialQuantity(row.quantity) }}</template>
          <template #cell-unit="{ row }">{{ row.unit || '单位未识别' }}</template>
        </TubeOutsourcingDetailTable>
      </template>
    </div>
    <template #footer><div class="d4-dispatch-footer"><div><strong>共 {{ format(detail?.total_quantity) }} {{ quantityUnit }}<span v-if="source === 'RAW_PIPE'"> · {{ format(detail?.total_stock_quantity) }} 根 / {{ meters(detail?.total_meters) }} 米</span></strong><small class="muted">{{ stockImpact }}</small></div><ElButton :disabled="saving" @click="dialog = ''">返回核对</ElButton><ElButton type="primary" :loading="saving" :disabled="!canDispatch" @click="submit('DISPATCH')">确认发出</ElButton></div></template>
  </AppWindowDialog>

  <AppWindowDialog :model-value="dialog === 'cancel'" title="取消待发外发单" :width="720" class="tube-outsourcing-detail-dialog" :before-close="beforeClose" :close-on-click-modal="!saving" :close-on-press-escape="!saving" @update:model-value="closeDialog">
    <div class="d4-cancel">
      <div class="info-grid"><div class="info-cell"><span>外发单号</span><strong :title="detail?.order_number">{{ detail?.order_number || '—' }}</strong></div><div class="info-cell"><span>当前状态</span><strong>{{ stateLabel }}</strong></div><div class="info-cell"><span>材料来源</span><strong>{{ sourceLabel }}</strong></div><div class="info-cell"><span>原单数量</span><strong>{{ format(detail?.total_quantity) }} {{ quantityUnit }} · {{ rows.length }} 个部位</strong></div></div>
      <p class="d4-cancel-text">确认后释放此单的待发预留，保留已取消原单。仓库库存不发生扣减。</p>
      <label class="form-field"><span>取消备注 <small class="muted">选填</small></span><ElInput v-model="cancellationRemark" :disabled="saving || Boolean(pending)" type="textarea" :rows="3" maxlength="2000" placeholder="填写取消原因或调整说明" aria-label="取消备注" /></label>
      <p class="d4-cancel-note muted">需要调整数量或加工厂时，取消后重新创建外发单。</p>
    </div>
    <template #footer><ElButton :disabled="saving" @click="dialog = ''">保留原单</ElButton><ElButton type="primary" :loading="saving" :disabled="!canCancel" @click="submit('CANCEL')">确认取消</ElButton></template>
  </AppWindowDialog>

  <AppWindowDialog :model-value="dialog === 'basis' && Boolean(selectedPart)" :title="`${selectedPart?.part_name || ''} · 加工完成依据`" :width="860" class="tube-outsourcing-detail-dialog" @update:model-value="closeDialog">
    <div v-if="selectedPart" class="d4-basis"><div class="d4-dialog-context"><span>生产任务 {{ detail?.task_number || '—' }}</span><span>{{ schemeLabel }}</span><span>当前核算截至 {{ selectedPart.report_as_of || '—' }}</span></div><ElAlert v-if="selectedPart.basis_blockers?.length" type="warning" :closable="false" :title="selectedPart.basis_blockers.join('；')" /><TubeOutsourcingDetailTable :columns="operationColumns" :rows="selectedPart.operations || []" row-key="work_item_id" class="d4-operation-lines" empty="暂无可用的必需工序报工依据"><template #cell-quantity="{ row }">{{ format(row.quantity) }}</template><template #cell-basis="{ row }"><span v-if="selectedPart.current_reported_minimum !== null && Number(row.quantity) === Number(selectedPart.current_reported_minimum)" class="status info">最低值</span><span v-else class="muted">已累计</span></template></TubeOutsourcingDetailTable><div class="d4-basis-result"><span>当前最低有效报工</span><strong class="brand">{{ format(selectedPart.current_reported_minimum) }}</strong><span>{{ quantityUnit }}</span><span class="muted">{{ state === 'CANCELLED' ? '原单' : hasDispatched ? '本单已发' : '本单已保存待发' }} {{ format(selectedPart.quantity) }} {{ quantityUnit }}</span></div><p class="muted">当前报工用于查看依据，不改变原单保存数量。正式发出时重新核对部位额度，{{ cutting ? '按订单需求、最低报工、已入库、已直发及待发预留检查。' : '按订单需求、实领投入、最低报工及已占用额度检查。' }}</p></div>
    <template #footer><ElButton type="primary" @click="dialog = ''">我知道了</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.d4-material-panel { display: flex; flex-direction: column; gap: 12px; min-width: 0; flex-shrink: 0; }
.d4-ended-materials { max-height: 240px; }
.d4-ended-materials > .d4-material-lines { min-height: 0; }
.d4-workspace.d4-workspace--with-materials { overflow: auto; }
.d4-workspace.d4-workspace--with-materials > .d4-lines { flex: none; }
.d4-material-panel > .section-heading { flex-wrap: wrap; }
.d4-dispatch-material-lines { max-height: 320px; }
</style>
