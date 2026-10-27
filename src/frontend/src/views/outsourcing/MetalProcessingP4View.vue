<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { Refresh, ArrowLeft, Plus, Box } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import {
  closeP4ExternalOrder, confirmP4ExternalHandoff, confirmP4GoodReturn, confirmP4OriginalGoodReturn, createP4ExternalOrder,
  createP4OriginalHandoff, createP4Rework, createP4UnsprayedReturn, fetchP4ExternalOrders,
  fetchP4Handoff, fetchP4Options, fetchP4SemiStock, fetchP4Source, fetchP4Sources, newP4RequestId,
  adjustP4ExternalAllocation, fetchP4ExternalOrder, fetchP4SourceClosurePreview, registerP4SourceCompletion, closeP4Source,
  cancelP4OriginalPending, closeP4OriginalOrder, fetchP4OriginalOrder,
} from '@/api/metalProcessingP4'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { formatOutsourcingMoney, outsourcingLineAmount, outsourcingPriceError } from '@/utils/outsourcingPrices'
import { useAuthStore } from '@/stores/auth'
import type { OutsourcingOrder } from '@/types/outsourcing'
import type { P4ExternalOrder, P4HandoffDetail, P4Options, P4OriginalGoodReturnContext, P4OriginalHandoff, P4OriginalOrderContext, P4OriginalOrderPart, P4Rework, P4SemiStock, P4Source, P4UnsprayedReturn } from '@/types/metalProcessingP4'

type DialogMode = 'handoff' | 'return' | 'original-good-return' | 'rework' | 'order' | 'new-handoff' | 'new-return' | 'close' | 'allocation' | 'source-completion' | 'source-close' | 'original-close' | 'original-cancel-pending'

const props = withDefaults(defineProps<{
  mode?: 'sources' | 'original' | 'rework'
  embedded?: boolean
  originalOrderId?: string
  externalOrderId?: string
}>(), { mode: 'sources', embedded: false, originalOrderId: '', externalOrderId: '' })
const emit = defineEmits<{ updated: [] }>()
const router = useRouter()
const relatedSources = ref<P4Source[]>([])
const orderSummary = ref<P4OriginalOrderContext | null>(null)
const summaryError = ref('')
const recordTab = ref('handoffs')
const sourceStatus = ref('ALL')
const handoffCandidates = ref<P4Source[]>([])
const candidateId = ref('')
const candidatesLoading = ref(false)
const reworkDetail = ref<P4ExternalOrder | null>(null)
const handoffDetails = ref<P4HandoffDetail[]>([])
const goodReturnRows = computed(() => Array.from(new Map(handoffDetails.value.flatMap(handoff =>
  (handoff.good_return_context?.good_returns || []).map(row => ({ ...row,
    part_name: handoff.good_return_context.part_name, factory_name: handoff.factory_name,
    key: `${handoff.good_return_context.allocation_id}:${row.id}`,
  }))).map(row => [row.key, row])).values()))
const originalHandoffs = computed(() => relatedSources.value.flatMap(item =>
  (item.original_handoffs || []).filter(row => row.original_order_id === props.originalOrderId)
    .map(row => ({ ...row, source: item, part_name: item.part_name, issue_number: item.issue_number }))))
const reworkOrigin = computed(() => relatedSources.value.flatMap(item => (item.original_handoffs || [])
  .flatMap(handoff => (handoff.unsprayed_returns || []).map(returned => ({ handoff, returned, source: item }))))
  .find(row => row.returned.id === reworkDetail.value?.original_return_id))
const sourceGroups = computed(() => props.mode === 'original' ? relatedSources.value.map(item => ({ ...item,
  original_handoffs: (item.original_handoffs || []).filter(row => row.original_order_id === props.originalOrderId),
})) : source.value ? [source.value] : [])
let openedEntryAction = ''
const sources = ref<P4Source[]>([])
const source = ref<P4Source | null>(null)
const orders = ref<P4ExternalOrder[]>([])
const selectedOrder = ref<P4ExternalOrder | null>(null)
const legacyOrders = ref<OutsourcingOrder[]>([])
const options = ref<P4Options | null>(null)
const semiStock = ref<P4SemiStock | null>(null)
const loading = ref(false)
const detailLoading = ref(false)
const error = ref('')
const search = ref('')
const dialog = ref<DialogMode | null>(null)
const saving = ref(false)
const selectedHandoff = ref<P4OriginalHandoff | null>(null)
const selectedReturn = ref<P4UnsprayedReturn | null>(null)
const selectedRework = ref<P4Rework | null>(null)
const auth = useAuthStore()
const route = useRoute()
const warehouseWorkspace = computed(() => route.meta?.outsourcingWorkspace === 'warehouse')
const warehouseArgs = computed<[true] | []>(() => warehouseWorkspace.value ? [true] : [])
const listPath = computed(() => warehouseWorkspace.value ? '/warehouse/outsourcing' : '/workshop/outsourcing')
const canViewSource = computed(() => Boolean(auth.user?.is_superuser || auth.hasPermission('material_issues.view_metalprocessingsource')))
const dialogError = ref('')
const uncertainOutcome = ref(false)
const originalGoodContext = ref<P4OriginalGoodReturnContext | null>(null)
const originalGoodLoading = ref(false)
let originalGoodRequest = 0
let listRequest = 0
let detailRequest = 0
let stockRequest = 0
let stockOrderId = ''
let pendingRequest: { signature: string; id: string; etag: string } | null = null
const contextLoading = ref(false)
const sourceContext = ref<P4Source | null>(null)
const originalOrderContext = ref<P4OriginalOrderContext | null>(null)
const returnContext = ref<P4HandoffDetail | null>(null)
const selectedPendingId = ref('')
const selectedPending = computed(() => originalOrderContext.value?.parts.find(part => part.allocation_id === selectedPendingId.value))
let contextRequest = 0
const actionPermissions: Record<DialogMode, string> = {
  handoff: 'create_metalprocessingoriginalhandoff', return: 'register_metalprocessingunsprayedreturn',
  'original-good-return': 'confirm_return_outsourcingorder',
  rework: 'register_metalprocessingrework', order: 'create_metalprocessingexternalorder',
  'new-handoff': 'confirm_metalprocessingexternalhandoff', 'new-return': 'confirm_metalprocessingexternalreturn',
  close: 'close_metalprocessingexternalorder',
  allocation: 'change_metalprocessingexternalorder',
  'source-completion': 'register_metalprocessingcompletion', 'source-close': 'close_metalprocessingsource',
  'original-close': 'complete_outsourcingorder', 'original-cancel-pending': 'change_outsourcingorder',
}
function canAct(mode: DialogMode): boolean {
  if (['original-good-return', 'new-return'].includes(mode) !== warehouseWorkspace.value) return false
  const app = ['original-good-return', 'original-close', 'original-cancel-pending'].includes(mode) ? 'outsourcing' : 'material_issues'
  return Boolean(auth.user?.is_superuser || auth.hasPermission(`${app}.${actionPermissions[mode]}`))
}
const canHandoffSource = computed(() => Boolean(source.value?.source_id && source.value.etag
  && source.value.status === 'OPEN' && source.value.available_pieces > 0))
const sourceBlockers = computed(() => Object.values(source.value?.blockers || {}).flat())

const today = () => {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
const handoffForm = ref({ originalOrderId: '', factoryId: '', pieces: '', date: today() })
const returnForm = ref({ pieces: '', receiverId: '', storage: '', date: today(), remark: '' })
const reworkForm = ref({ pieces: '', date: today() })
const orderForm = ref({ factoryId: '', craftId: '', pieces: '', unitPrice: '0' })
const newHandoffForm = ref({ pieces: '', date: today() })
const newReturnForm = ref({ pieces: '', zoneId: '', receiverId: '', date: today(), remark: '' })
const originalGoodForm = ref({ pieces: '', zoneId: '', receiverId: '', date: today(), remark: '' })
const originalGoodPreview = computed(() => {
  const pieces = positiveInteger(originalGoodForm.value.pieces)
  const context = originalGoodContext.value
  if (!context || !pieces || pieces > context.remaining_return_pieces) return null
  return { pieces, remaining: context.remaining_return_pieces - pieces }
})
const closeForm = ref({ remark: '' })
const allocationForm = ref({ pieces: '' })
const sourceCompletionForm = ref({ pieces: '', date: today() })
const sourceCloseForm = ref({ remark: '' })
const originalCloseForm = ref({ remark: '' })
const originalCancelForm = ref({ remark: '' })
const returnPreview = computed(() => {
  const pieces = positiveInteger(returnForm.value.pieces)
  if (!returnContext.value || !pieces || pieces > remainingReturnPieces(returnContext.value)) return null
  return { pieces, remaining: remainingReturnPieces(returnContext.value) - pieces }
})
const allocationPreview = computed(() => {
  const pieces = positiveInteger(allocationForm.value.pieces, 99_999_999_999_999)
  const context = selectedOrder.value?.allocation_context
  if (!context || !pieces || pieces > context.max_allocatable_pieces) return null
  return { total: context.other_allocated_pieces + pieces, remaining: context.max_allocatable_pieces - pieces }
})
const isSourceDialog = computed(() => dialog.value === 'source-completion' || dialog.value === 'source-close')
const dialogWidth = computed(() => dialog.value === 'original-close' ? 1080 : ['original-good-return', 'allocation', 'return', 'original-cancel-pending'].includes(dialog.value || '') || isSourceDialog.value ? 840 : 650)
const dialogHeight = computed(() => dialog.value === 'original-close' ? 860 : ['original-good-return', 'allocation', 'return'].includes(dialog.value || '') ? 780 : isSourceDialog.value || dialog.value === 'original-cancel-pending' ? 640 : 520)
const submitDisabled = computed(() => originalGoodLoading.value || contextLoading.value
  || (dialog.value === 'original-good-return' && (!originalGoodContext.value?.can_return || !!originalGoodContext.value?.blockers.length))
  || (dialog.value === 'allocation' && !selectedOrder.value?.allocation_context?.can_adjust)
  || (dialog.value === 'source-completion' && !sourceContext.value?.can_register)
  || (dialog.value === 'source-close' && !sourceContext.value?.can_close)
  || (dialog.value === 'return' && (!returnContext.value?.source_etag || remainingReturnPieces(returnContext.value) <= 0))
  || (dialog.value === 'original-close' && !originalOrderContext.value?.can_close)
  || (dialog.value === 'original-cancel-pending' && !selectedPending.value?.can_cancel_pending))
const showSubmit = computed(() => dialog.value !== 'original-close' || (canAct('original-close') && !['CLOSED', 'COMPLETED', 'CANCELLED'].includes(originalOrderContext.value?.original_order_status || '')))
const submitLabel = computed(() => ({ 'original-good-return': '确认合格回货', return: '确认未喷塑退回', allocation: '保存分配', 'source-completion': '确认登记', 'source-close': '填写备注并结清', 'original-close': '确认原单结清', 'original-cancel-pending': '确认取消待交接余量' } as Partial<Record<DialogMode, string>>)[dialog.value || 'handoff'] || '保存')
const dialogVisible = computed({ get: () => Boolean(dialog.value), set: (value: boolean) => { if (!value) resetDialog() } })

const sprayCrafts = computed(() => (options.value?.crafts || []).filter(item => item.outsourcing_code === 'POWDER_COATING'))
const orderFactories = computed(() => (options.value?.factories || []).filter(item => item.crafts.some(craft => craft.id === orderForm.value.craftId)))
const filteredSources = computed(() => {
  const query = search.value.trim().toLowerCase()
  return sources.value.filter(row => (sourceStatus.value === 'ALL' || row.status === sourceStatus.value)
    && (!query || [row.issue_number, row.part_name, row.component_identity].some(value => String(value || '').toLowerCase().includes(query))))
})
const entryFilters = computed(() => Object.fromEntries(['production_task_id', 'product_line_id', 'issue_id'].flatMap(key => {
  const value = route?.query?.[key]
  return typeof value === 'string' && value ? [[key, value]] : []
})))
const visibleOrders = computed(() => Object.keys(entryFilters.value).length
  ? orders.value.filter(order => sources.value.some(row => row.source_id === order.source_id)) : orders.value)
const dialogTitle = computed(() => ({
  handoff: '登记原外发交接', return: '登记未喷塑退回', rework: '登记重新加工完成', order: '创建新外发单',
  'original-good-return': '原外发单 · 登记合格回货',
  'new-handoff': '确认新外发交接', 'new-return': '登记合格回货', close: '备注结清',
  allocation: '调整新外发分配', 'source-completion': '登记加工完成', 'source-close': '金工来源 · 备注结清',
  'original-close': '原外发单 · 收尾与记录', 'original-cancel-pending': '原外发单 · 取消待交接余量',
} as Record<DialogMode, string>)[dialog.value || 'handoff'])

function errorText(value: unknown, fallback: string): string {
  if (!(value instanceof AxiosError)) return value instanceof Error ? value.message : fallback
  const data = value.response?.data as { error?: { message?: string }; detail?: string } | undefined
  return data?.error?.message || data?.detail || fallback
}

function statusText(status: P4ExternalOrder['status']): string {
  return ({ PENDING_HANDOFF: '待交接', PROCESSING: '加工中', COMPLETED: '已回齐', CLOSED: '已结清' })[status]
}
function originalStatusText(status?: string): string {
  return ({ PENDING_DISPATCH: '待交接', PROCESSING: '加工中', PARTIAL_RETURN: '部分回货', CLOSED: '已结清 · 可补登记', COMPLETED: '已回齐', CANCELLED: '已作废' } as Record<string, string>)[status || ''] || '待核对'
}

function formatDate(value: string): string { return value ? value.slice(0, 10) : '—' }
function formatTime(value: string): string {
  const date = new Date(value)
  return value && !Number.isNaN(date.getTime()) ? date.toLocaleString('zh-CN', { hour12: false }) : '—'
}
function returnBlockerText(row: P4OriginalHandoff): string {
  return Object.values(row.return_blockers || {}).flat().join('；')
}
function remainingReturnPieces(row: P4OriginalHandoff): number {
  if (['COMPLETED', 'CANCELLED'].includes(row.original_order_status || '')) return 0
  if (returnBlockerText(row)) return 0
  // 后端上限同时扣除了原单合格回货及其他交接的退回，只在旧响应缺字段时回退。
  const remaining = row.remaining_return_pieces ?? row.handoff_pieces - row.returned_unsprayed_pieces
  return Number.isSafeInteger(remaining) && remaining > 0 ? remaining : 0
}
function positiveInteger(value: string, maximum = 2147483647): number {
  if (!/^\d+$/.test(value.trim())) return 0
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) && parsed > 0 && parsed <= maximum ? parsed : 0
}
function resetDialog(): void {
  if (saving.value) return
  if (uncertainOutcome.value) {
    dialogError.value = '上次保存结果尚未确认，请点击保存重试原请求，避免重复登记。'
    return
  }
  dialog.value = null
  ++originalGoodRequest
  ++contextRequest
  originalGoodLoading.value = false
  contextLoading.value = false
  dialogError.value = ''
  pendingRequest = null
}
function beginDialog(mode: DialogMode, readOnly = false): boolean {
  if ((!readOnly && !canAct(mode)) || saving.value || uncertainOutcome.value) return false
  dialogError.value = ''
  pendingRequest = null
  dialog.value = mode
  return true
}
function writeRequest(target: string, payload: Record<string, unknown>, etag = '') {
  const signature = JSON.stringify({ mode: dialog.value, target, payload })
  if (pendingRequest && pendingRequest.signature !== signature && uncertainOutcome.value) {
    throw new Error('上次保存结果尚未确认，请恢复原内容后重试。')
  }
  if (!pendingRequest || pendingRequest.signature !== signature) {
    pendingRequest = { signature, id: newP4RequestId(), etag }
  }
  return pendingRequest
}

async function loadAllSources(filters: Record<string, unknown> = entryFilters.value): Promise<P4Source[]> {
  const first = await fetchP4Sources({ ...filters, ...(warehouseWorkspace.value ? { warehouse_stage: 'all' } : {}), page: 1, page_size: 100 })
  const rows = [...first.data]
  for (let page = 2; page <= first.meta.total_pages; page++) {
    rows.push(...(await fetchP4Sources({ ...filters, ...(warehouseWorkspace.value ? { warehouse_stage: 'all' } : {}), page, page_size: 100 })).data)
  }
  return rows
}

async function loadSources(): Promise<void> {
  if (saving.value || dialog.value) return
  const request = ++listRequest
  loading.value = true; error.value = ''
  try {
    if (props.mode !== 'sources') {
      await loadOrder(request)
      return
    }
    const [sourceResult, optionResult, orderResult] = await Promise.all([
      loadAllSources(), fetchP4Options(...warehouseArgs.value), props.embedded ? Promise.resolve({ data: [] }) : fetchP4ExternalOrders(),
    ])
    if (request !== listRequest) return
    sources.value = sourceResult
    options.value = optionResult
    orders.value = orderResult.data
    legacyOrders.value = optionResult.original_orders || []
    const requestedId = typeof route.query?.source_issue_line_id === 'string' ? route.query.source_issue_line_id : ''
    if (requestedId && !sources.value.some(row => row.issue_line_id === requestedId)) {
      source.value = null
      throw new Error('所选金工来源已不可访问或不在当前筛选范围，请重新选择。')
    }
    const current = sources.value.find(row => row.issue_line_id === (requestedId || source.value?.issue_line_id)) || sources.value[0]
    if (current) await selectSource(current)
    else { ++detailRequest; source.value = null }
    if (stockOrderId) await refreshSemiStock(stockOrderId)
    applyEntryAction()
  } catch (value) {
    if (request === listRequest) error.value = errorText(value, '外发材料数据加载失败，请稍后重试。')
  } finally { if (request === listRequest) loading.value = false }
}

async function loadOrder(request: number): Promise<void> {
  summaryError.value = ''; orderSummary.value = null; reworkDetail.value = null; relatedSources.value = []; handoffDetails.value = []
  const optionResult = await fetchP4Options(...warehouseArgs.value)
  if (request !== listRequest) return
  options.value = optionResult
  legacyOrders.value = optionResult.original_orders || []
  if (props.mode === 'rework') {
    if (!props.externalOrderId) throw new Error('缺少外发单编号。')
    const order = await fetchP4ExternalOrder(props.externalOrderId, ...warehouseArgs.value)
    const rows = await loadAllSources({ source_id: order.source_id })
    const details = await Promise.all(rows.map(row => fetchP4Source(row.issue_line_id, ...warehouseArgs.value)))
    if (request !== listRequest) return
    reworkDetail.value = order
    relatedSources.value = details.filter(row => row.source_id === order.source_id)
    source.value = relatedSources.value[0] || null
    orders.value = [order]
    if (stockOrderId) await refreshSemiStock(order.id)
    return
  }
  if (!props.originalOrderId) throw new Error('缺少原外发单编号。')
  const rows = await loadAllSources({ original_order_id: props.originalOrderId })
  const selectedId = typeof route.query?.source_issue_line_id === 'string' ? route.query.source_issue_line_id : ''
  const ids = [...new Set([...rows.map(row => row.issue_line_id), ...(selectedId ? [selectedId] : [])])]
  const details = await Promise.all(ids.map(id => fetchP4Source(id, ...warehouseArgs.value)))
  if (request !== listRequest) return
  relatedSources.value = details
  sources.value = details
  source.value = details.find(row => row.issue_line_id === selectedId) || details[0] || null
  const handoffResults = await Promise.allSettled(originalHandoffs.value.map(row => fetchP4Handoff(row.id, ...warehouseArgs.value)))
  if (request !== listRequest) return
  handoffDetails.value = handoffResults.flatMap(result => result.status === 'fulfilled' ? [result.value] : [])
  if (handoffResults.some(result => result.status === 'rejected')) summaryError.value = '部分交接记录未能读取，请刷新后再核对回货历史。'
  // 整单收尾比逐条来源操作权限更严格；拒绝时仍保留合法来源及其历史。
  try {
    const summary = await fetchP4OriginalOrder(props.originalOrderId, ...warehouseArgs.value)
    if (request === listRequest) orderSummary.value = summary
  } catch (value) {
    if (request === listRequest) summaryError.value = errorText(value, '当前无法查看整单收尾，只展示可访问的交接来源。')
  }
}

function applyEntryAction(): void {
  const id = typeof route.query?.rework_id === 'string' ? route.query.rework_id : ''
  if (!id || route.query?.source_action !== 'rework' || openedEntryAction === id || !source.value) return
  const rework = (source.value.original_handoffs || []).flatMap(row => row.unsprayed_returns || [])
    .flatMap(row => row.reworks || []).find(row => row.id === id)
  if (!rework) { error.value = '所选重加工记录不在当前来源中，请重新选择。'; return }
  openedEntryAction = id
  openOrder(rework)
}

function openSourceHandoff(row: P4Source): void {
  if (saving.value || dialog.value) return
  source.value = row
  openHandoff()
}

async function loadHandoffCandidates(): Promise<void> {
  if (saving.value || dialog.value) return
  candidatesLoading.value = true
  try {
    handoffCandidates.value = (await loadAllSources({})).filter(row => row.status === 'OPEN' && row.available_pieces > 0)
    if (!handoffCandidates.value.length) ElMessage.info('暂无可交接的加工件，请先登记对应领料部位的加工完成。')
  } catch (value) { error.value = errorText(value, '可交接来源加载失败。') }
  finally { candidatesLoading.value = false }
}

async function handoffCandidate(): Promise<void> {
  if (!candidateId.value || candidatesLoading.value || saving.value || dialog.value) return
  candidatesLoading.value = true
  try {
    const row = await fetchP4Source(candidateId.value, ...warehouseArgs.value)
    if (!relatedSources.value.some(item => item.issue_line_id === row.issue_line_id)) relatedSources.value.push(row)
    openSourceHandoff(row)
  } catch (value) { error.value = errorText(value, '所选来源加载失败，请重新选择。') }
  finally { candidatesLoading.value = false }
}

function openOrderSummary(): void {
  if (!props.originalOrderId) return
  void openOriginalOrder({ original_order_id: props.originalOrderId } as P4OriginalHandoff)
}

async function selectSource(row: P4Source): Promise<void> {
  if (saving.value || dialog.value) return
  const request = ++detailRequest
  detailLoading.value = true
  source.value = null
  try {
    const detail = await fetchP4Source(row.issue_line_id, ...warehouseArgs.value)
    if (request === detailRequest) source.value = detail
  } catch (value) {
    if (request === detailRequest) error.value = errorText(value, '来源详情加载失败。')
  } finally { if (request === detailRequest) detailLoading.value = false }
}

function openHandoff(): void {
  if (!canHandoffSource.value || !beginDialog('handoff')) return
  handoffForm.value = { originalOrderId: props.originalOrderId || legacyOrders.value[0]?.id || '', factoryId: options.value?.factories[0]?.id || '', pieces: '', date: today() }
}
async function openReturn(row: P4OriginalHandoff): Promise<void> {
  if (!beginDialog('return')) return
  selectedHandoff.value = row
  returnContext.value = null
  returnForm.value = { pieces: '', receiverId: options.value?.receivers[0]?.id || '', storage: '', date: today(), remark: '' }
  const request = ++contextRequest
  contextLoading.value = true
  try {
    const detail = await fetchP4Handoff(row.id, ...warehouseArgs.value)
    if (request !== contextRequest || dialog.value !== 'return') return
    returnContext.value = detail
    selectedHandoff.value = detail
    dialogError.value = returnBlockerText(detail)
    if (!detail.source_etag || remainingReturnPieces(detail) <= 0) dialogError.value ||= '该原单当前没有可退回数量，请核对最新状态。'
  } catch (value) {
    if (request === contextRequest) dialogError.value = errorText(value, '原单退回信息加载失败，请关闭弹窗后重试。')
  } finally { if (request === contextRequest) contextLoading.value = false }
}
async function openOriginalGoodReturn(row: P4OriginalHandoff): Promise<void> {
  if (!beginDialog('original-good-return')) return
  selectedHandoff.value = row
  originalGoodContext.value = null
  originalGoodForm.value = { pieces: '', zoneId: options.value?.semi_finished_zones[0]?.id || '', receiverId: options.value?.receivers[0]?.id || '', date: today(), remark: '' }
  const request = ++originalGoodRequest
  originalGoodLoading.value = true
  try {
    const detail = await fetchP4Handoff(row.id, ...warehouseArgs.value)
    if (request !== originalGoodRequest || dialog.value !== 'original-good-return') return
    if (!detail.good_return_context) throw new Error('未取得原单回货信息，请关闭弹窗后刷新重试。')
    originalGoodContext.value = detail.good_return_context
    dialogError.value = detail.good_return_context.blockers.join('；')
  } catch (value) {
    if (request === originalGoodRequest) dialogError.value = errorText(value, '原单回货信息加载失败，请关闭弹窗后重试。')
  } finally { if (request === originalGoodRequest) originalGoodLoading.value = false }
}
function openRework(row: P4UnsprayedReturn): void { if (!beginDialog('rework')) return; selectedReturn.value = row; reworkForm.value = { pieces: '', date: today() } }
function openOrder(row: P4Rework): void {
  if (!beginDialog('order')) return
  selectedRework.value = row
  orderForm.value = { factoryId: '', craftId: sprayCrafts.value[0]?.id || '', pieces: String(row.remaining_allocatable_pieces), unitPrice: '0' }
  orderForm.value.factoryId = orderFactories.value[0]?.id || ''
}
function openNewHandoff(row: P4ExternalOrder): void { if (!beginDialog('new-handoff')) return; selectedOrder.value = row; newHandoffForm.value = { pieces: String(row.allocated_pieces), date: today() } }
function openNewReturn(row: P4ExternalOrder): void { if (!['PROCESSING', 'CLOSED'].includes(row.status) || row.remaining_return_pieces <= 0 || !beginDialog('new-return')) return; selectedOrder.value = row; newReturnForm.value = { pieces: '', zoneId: options.value?.semi_finished_zones[0]?.id || '', receiverId: options.value?.receivers[0]?.id || '', date: today(), remark: '' } }
function openClose(row: P4ExternalOrder): void { if (!beginDialog('close')) return; selectedOrder.value = row; closeForm.value = { remark: '' } }

async function openAllocation(row: P4ExternalOrder): Promise<void> {
  if (!beginDialog('allocation')) return
  selectedOrder.value = null
  allocationForm.value = { pieces: '' }
  const request = ++contextRequest
  contextLoading.value = true
  try {
    const detail = await fetchP4ExternalOrder(row.id, ...warehouseArgs.value)
    if (request !== contextRequest || dialog.value !== 'allocation') return
    selectedOrder.value = detail
    allocationForm.value.pieces = String(detail.allocated_pieces)
    if (!detail.allocation_context) throw new Error('未取得分配上限，请关闭弹窗后刷新重试。')
    dialogError.value = detail.allocation_context.blockers.join('；')
  } catch (value) {
    if (request === contextRequest) dialogError.value = errorText(value, '新外发分配信息加载失败，请关闭弹窗后重试。')
  } finally { if (request === contextRequest) contextLoading.value = false }
}

async function openSourceOperation(mode: 'source-completion' | 'source-close'): Promise<void> {
  if (!source.value || !beginDialog(mode)) return
  const id = source.value.issue_line_id
  sourceContext.value = null
  sourceCompletionForm.value = { pieces: '', date: today() }
  sourceCloseForm.value = { remark: '' }
  const request = ++contextRequest
  contextLoading.value = true
  try {
    const detail = mode === 'source-close' ? await fetchP4SourceClosurePreview(id) : await fetchP4Source(id, ...warehouseArgs.value)
    if (request !== contextRequest || dialog.value !== mode) return
    sourceContext.value = detail
    if (!detail.etag || !(mode === 'source-completion' ? detail.can_register : detail.can_close)) {
      dialogError.value = Object.values(detail.blockers || {}).flat().join('；') || (detail.status === 'CLOSED' ? '该来源已结清，不能继续登记或结清。' : '当前来源不满足操作条件，请刷新核对。')
    }
  } catch (value) {
    if (request === contextRequest) dialogError.value = errorText(value, '加工来源信息加载失败，请关闭弹窗后重试。')
  } finally { if (request === contextRequest) contextLoading.value = false }
}

async function openOriginalOrder(row: P4OriginalHandoff): Promise<void> {
  if (!row.original_order_id || !beginDialog('original-close', true)) return
  originalOrderContext.value = null
  originalCloseForm.value = { remark: '' }
  const request = ++contextRequest
  contextLoading.value = true
  try {
    const context = await fetchP4OriginalOrder(row.original_order_id, ...warehouseArgs.value)
    if (request !== contextRequest || dialog.value !== 'original-close') return
    originalOrderContext.value = context
  } catch (value) {
    if (request === contextRequest) dialogError.value = errorText(value, '原单收尾信息加载失败，请关闭弹窗后重试。')
  } finally { if (request === contextRequest) contextLoading.value = false }
}

async function openOriginalCancel(part: P4OriginalOrderPart): Promise<void> {
  const orderId = originalOrderContext.value?.original_order_id
  if (!orderId || !part.can_cancel_pending || !beginDialog('original-cancel-pending')) return
  selectedPendingId.value = part.allocation_id
  originalCancelForm.value = { remark: '' }
  originalOrderContext.value = null
  const request = ++contextRequest
  contextLoading.value = true
  try {
    const context = await fetchP4OriginalOrder(orderId, ...warehouseArgs.value)
    if (request !== contextRequest || dialog.value !== 'original-cancel-pending') return
    originalOrderContext.value = context
    if (!selectedPending.value?.can_cancel_pending) dialogError.value = '该分配的待交接数量或状态已变化，请关闭弹窗重新核对。'
  } catch (value) {
    if (request === contextRequest) dialogError.value = errorText(value, '待交接分配加载失败，请关闭弹窗后重试。')
  } finally { if (request === contextRequest) contextLoading.value = false }
}

async function submit(): Promise<void> {
  if (!dialog.value || saving.value || originalGoodLoading.value || contextLoading.value) return
  if (!canAct(dialog.value)) { dialogError.value = '当前账号没有执行此操作的权限。'; return }
  saving.value = true; dialogError.value = ''
  let sent = false
  let saved = false
  let createdOrderId = ''
  try {
    if (dialog.value === 'original-close' && originalOrderContext.value) {
      const context = originalOrderContext.value
      if (!context.can_close || !context.etag || context.blockers.length) throw new Error(context.blockers.join('；') || '当前原单不能结清，请刷新核对。')
      const remark = originalCloseForm.value.remark.trim()
      if (!remark || remark.length > 1000) throw new Error('原单结清原因必须为 1～1000 字，不能只填空格。')
      const payload = { remark }
      const request = writeRequest(context.original_order_id, payload, context.etag)
      sent = true
      originalOrderContext.value = await closeP4OriginalOrder(context.original_order_id, { request_id: request.id, ...payload }, request.etag)
    } else if (dialog.value === 'original-cancel-pending' && originalOrderContext.value && selectedPending.value) {
      const context = originalOrderContext.value
      const part = selectedPending.value
      if (!context.etag || !part.can_cancel_pending || part.pending_handoff_pieces <= 0) throw new Error('该分配没有可取消的待交接余量，请刷新核对。')
      const remark = originalCancelForm.value.remark.trim()
      if (!remark || remark.length > 1000) throw new Error('取消待交接原因必须为 1～1000 字，不能只填空格。')
      const payload = { allocation_id: part.allocation_id, remark }
      const request = writeRequest(context.original_order_id, payload, context.etag)
      sent = true
      originalOrderContext.value = await cancelP4OriginalPending(context.original_order_id, { request_id: request.id, ...payload }, request.etag)
    } else if (dialog.value === 'source-completion' && sourceContext.value?.etag) {
      const context = sourceContext.value
      if (!context.etag || !context.can_register || context.status !== 'OPEN') throw new Error('当前来源不能继续登记加工完成，请刷新核对。')
      const pieces = positiveInteger(sourceCompletionForm.value.pieces, 99_999_999_999_999)
      if (!pieces || !sourceCompletionForm.value.date) throw new Error('请填写正整数合格完成支数和完成日期。')
      if (pieces > context.remaining_completion_pieces) throw new Error('本次完成支数超过剩余可登记数量，累计不能超过已领支数。')
      const payload = { good_pieces: pieces, completion_date: sourceCompletionForm.value.date }
      const request = writeRequest(context.issue_line_id, payload, context.etag)
      sent = true
      await registerP4SourceCompletion(context.issue_line_id, { request_id: request.id, ...payload }, request.etag)
    } else if (dialog.value === 'source-close' && sourceContext.value?.etag) {
      const context = sourceContext.value
      if (!context.etag || !context.can_close || context.status !== 'OPEN' || context.reserved_pieces > 0) throw new Error('当前来源不能结清；存在待外发占用时，请先处理交接或取消分配。')
      const remark = sourceCloseForm.value.remark.trim()
      if (!remark || remark.length > 1000) throw new Error('请填写结清备注，去除空格后为 1～1000 字。')
      const payload = { remark }
      const request = writeRequest(context.issue_line_id, payload, context.etag)
      sent = true
      await closeP4Source(context.issue_line_id, { request_id: request.id, ...payload }, request.etag)
    } else if (dialog.value === 'allocation' && selectedOrder.value) {
      const order = selectedOrder.value
      const context = order.allocation_context
      if (!context?.can_adjust || context.blockers.length || order.status !== 'PENDING_HANDOFF' || order.handoff_pieces !== 0) throw new Error(context?.blockers.join('；') || '该新外发单已交接或不可调整，请刷新核对。')
      const pieces = positiveInteger(allocationForm.value.pieces, 99_999_999_999_999)
      if (!pieces) throw new Error('调整后分配数量必须为正整数支数。')
      if (pieces > context.max_allocatable_pieces) throw new Error('调整后分配超过本单可调上限，请核对其他新单占用。')
      const payload = { allocated_pieces: pieces }
      const request = writeRequest(order.id, payload, order.etag)
      sent = true
      selectedOrder.value = await adjustP4ExternalAllocation(order.id, { request_id: request.id, ...payload }, request.etag)
    } else if (dialog.value === 'handoff' && source.value?.etag) {
      const pieces = positiveInteger(handoffForm.value.pieces)
      if (!handoffForm.value.originalOrderId || !handoffForm.value.factoryId || !pieces || !handoffForm.value.date) throw new Error('请选择原外发单、加工厂、交接日期并填写正整数交接支数。')
      if (pieces > source.value.available_pieces) throw new Error('交接支数超过当前可外发完成量。')
      const payload = { original_order_id: handoffForm.value.originalOrderId, factory_id: handoffForm.value.factoryId, handoff_pieces: pieces, handoff_date: handoffForm.value.date }
      const request = writeRequest(source.value.issue_line_id, payload, source.value.etag)
      sent = true
      source.value = await createP4OriginalHandoff(source.value.issue_line_id, { request_id: request.id, ...payload }, request.etag)
    } else if (dialog.value === 'return' && selectedHandoff.value && returnContext.value?.source_etag) {
      const context = returnContext.value
      const pieces = positiveInteger(returnForm.value.pieces)
      if (!pieces || !returnForm.value.receiverId || !returnForm.value.storage.trim() || !returnForm.value.date) throw new Error('请填写正整数退回支数、接收人、暂存位置和退回日期。')
      const blocker = returnBlockerText(selectedHandoff.value)
      if (blocker) throw new Error(blocker)
      if (pieces > remainingReturnPieces(selectedHandoff.value)) throw new Error('退回支数超过当前可退数量，请核对原单合格回货和其他退回记录。')
      if (context.original_order_status === 'CLOSED' && !returnForm.value.remark.trim()) throw new Error('原单结清后补登记未喷塑退回必须填写原因。')
      const payload = { returned_pieces: pieces, received_by_employee_id: returnForm.value.receiverId, storage_location: returnForm.value.storage.trim(), return_date: returnForm.value.date, remark: returnForm.value.remark.trim() }
      const request = writeRequest(selectedHandoff.value.id, payload, context.source_etag || '')
      sent = true
      await createP4UnsprayedReturn(selectedHandoff.value.id, { request_id: request.id, ...payload }, request.etag)
    } else if (dialog.value === 'original-good-return' && selectedHandoff.value && originalGoodContext.value) {
      const context = originalGoodContext.value
      if (context.blockers.length) throw new Error(context.blockers.join('；'))
      if (!context.can_return || !context.etag) throw new Error('当前原单不能登记合格回货，请关闭弹窗并刷新核对。')
      const pieces = positiveInteger(originalGoodForm.value.pieces)
      if (!pieces || !originalGoodForm.value.zoneId || !originalGoodForm.value.receiverId || !originalGoodForm.value.date) throw new Error('请填写正整数合格回货支数、半成品库区、接收人和回货日期。')
      if (pieces > context.remaining_return_pieces) throw new Error('合格回货支数超过当前可回数量，请核对合格回货和未喷塑退回记录。')
      if ((context.post_closure || context.original_order_status === 'CLOSED') && !originalGoodForm.value.remark.trim()) throw new Error('原单结清后补登记合格回货必须填写原因。')
      const payload = { good_pieces: pieces, zone_id: originalGoodForm.value.zoneId, received_by_employee_id: originalGoodForm.value.receiverId, return_date: originalGoodForm.value.date, remark: originalGoodForm.value.remark.trim() }
      const request = writeRequest(selectedHandoff.value.id, payload, context.etag)
      sent = true
      originalGoodContext.value = await confirmP4OriginalGoodReturn(selectedHandoff.value.id, { request_id: request.id, ...payload }, request.etag)
    } else if (dialog.value === 'rework' && selectedReturn.value) {
      const pieces = positiveInteger(reworkForm.value.pieces)
      if (!pieces || !reworkForm.value.date) throw new Error('请填写正整数重新加工完成支数和完成日期。')
      if (pieces > (selectedReturn.value.remaining_rework_pieces ?? selectedReturn.value.returned_pieces)) throw new Error('重新加工支数超过本次退回的剩余数量。')
      const payload = { completed_pieces: pieces, completion_date: reworkForm.value.date }
      const request = writeRequest(selectedReturn.value.id, payload)
      sent = true
      await createP4Rework(selectedReturn.value.id, { request_id: request.id, ...payload })
    } else if (dialog.value === 'order' && selectedRework.value) {
      const pieces = positiveInteger(orderForm.value.pieces)
      if (!orderForm.value.factoryId || !orderForm.value.craftId || !pieces) throw new Error('请选择加工厂、喷塑工艺并填写正整数新外发支数。')
      if (!orderFactories.value.some(row => row.id === orderForm.value.factoryId)) throw new Error('请选择已关联当前喷塑工艺的加工厂。')
      if (pieces > selectedRework.value.remaining_allocatable_pieces) throw new Error('新外发支数超过本次重新加工的可分配量。')
      const priceError = outsourcingPriceError(orderForm.value.unitPrice)
      if (priceError) throw new Error(priceError)
      const payload = { factory_id: orderForm.value.factoryId, craft_id: orderForm.value.craftId, allocated_pieces: pieces, unit_price: orderForm.value.unitPrice.trim() }
      const request = writeRequest(selectedRework.value.id, payload)
      sent = true
      const created = await createP4ExternalOrder(selectedRework.value.id, { request_id: request.id, ...payload })
      createdOrderId = created.id
    } else if (dialog.value === 'new-handoff' && selectedOrder.value) {
      const pieces = positiveInteger(newHandoffForm.value.pieces)
      if (!pieces || !newHandoffForm.value.date) throw new Error('请填写正整数交接支数和交接日期。')
      if (pieces !== selectedOrder.value.allocated_pieces) throw new Error('实际交接支数必须等于已保存分配支数。')
      const payload = { handoff_pieces: pieces, handoff_date: newHandoffForm.value.date }
      const request = writeRequest(selectedOrder.value.id, payload, selectedOrder.value.etag)
      sent = true
      selectedOrder.value = await confirmP4ExternalHandoff(selectedOrder.value.id, { request_id: request.id, ...payload }, request.etag)
    } else if (dialog.value === 'new-return' && selectedOrder.value) {
      if (!['PROCESSING', 'CLOSED'].includes(selectedOrder.value.status) || selectedOrder.value.remaining_return_pieces <= 0) throw new Error('当前外发单没有可登记的合格回货，请刷新核对。')
      const pieces = positiveInteger(newReturnForm.value.pieces)
      if (!pieces || !newReturnForm.value.zoneId || !newReturnForm.value.receiverId || !newReturnForm.value.date) throw new Error('请填写正整数回货支数、半成品库区、接收人和回货日期。')
      if (pieces > selectedOrder.value.remaining_return_pieces) throw new Error('合格回货支数超过当前未回数量。')
      if (selectedOrder.value.status === 'CLOSED' && !newReturnForm.value.remark.trim()) throw new Error('结清后追加回货必须填写备注。')
      const payload = { good_pieces: pieces, zone_id: newReturnForm.value.zoneId, received_by_employee_id: newReturnForm.value.receiverId, return_date: newReturnForm.value.date, remark: newReturnForm.value.remark.trim() }
      const request = writeRequest(selectedOrder.value.id, payload, selectedOrder.value.etag)
      sent = true
      selectedOrder.value = await confirmP4GoodReturn(selectedOrder.value.id, { request_id: request.id, ...payload }, request.etag)
    } else if (dialog.value === 'close' && selectedOrder.value) {
      if (!closeForm.value.remark.trim()) throw new Error('结清必须填写备注。')
      const payload = { remark: closeForm.value.remark.trim() }
      const request = writeRequest(selectedOrder.value.id, payload, selectedOrder.value.etag)
      sent = true
      selectedOrder.value = await closeP4ExternalOrder(selectedOrder.value.id, { request_id: request.id, ...payload }, request.etag)
    } else {
      throw new Error('当前操作缺少有效来源或版本，请关闭弹窗并刷新后重试。')
    }
    saved = true
    uncertainOutcome.value = false
  } catch (value) {
    const status = value instanceof AxiosError ? value.response?.status : undefined
    if (sent) {
      uncertainOutcome.value = !status || status >= 500 || status === 408
      if (!uncertainOutcome.value) pendingRequest = null
    }
    dialogError.value = errorText(value, '操作失败，请核对数量和最新单据状态。')
      + (uncertainOutcome.value ? ' 保存结果尚未确认，请点击保存重试原请求。' : '')
      + (status === 412 || status === 428 ? ' 请关闭弹窗，刷新最新数据后重试。' : '')
  } finally { saving.value = false }
  if (saved) {
    resetDialog()
    ElMessage.success('操作已保存。')
    emit('updated')
    if (createdOrderId) {
      await router.push(`${listPath.value}/rework/${encodeURIComponent(createdOrderId)}`)
      return
    }
    await loadSources()
    if (error.value) error.value = `操作已保存，但刷新失败：${error.value} 请点击刷新，勿重复登记。`
  }
}

async function refreshSemiStock(id: string): Promise<void> {
  const request = ++stockRequest
  semiStock.value = null
  try {
    const result = await fetchP4SemiStock(id, ...warehouseArgs.value)
    if (request === stockRequest) semiStock.value = result
  } catch (value) { if (request === stockRequest) error.value = errorText(value, '半成品库存加载失败。') }
}
async function showSemiStock(row: P4ExternalOrder): Promise<void> {
  if (saving.value || dialog.value) return
  stockOrderId = row.id
  await refreshSemiStock(row.id)
}

onMounted(() => { void loadSources() })
watch(() => [props.mode, props.originalOrderId, props.externalOrderId, warehouseWorkspace.value, route.query?.source_issue_line_id,
  route.query?.issue_id, route.query?.production_task_id, route.query?.product_line_id, route.query?.rework_id], () => { void loadSources() })
let openedWarehouseReturn = false
watch(() => [loading.value, route.query?.action, warehouseWorkspace.value], () => {
  if (loading.value || !warehouseWorkspace.value || route.query?.action !== 'return' || openedWarehouseReturn) return
  if (props.mode === 'rework' && reworkDetail.value && canAct('new-return')
    && ['PROCESSING', 'CLOSED'].includes(reworkDetail.value.status) && reworkDetail.value.remaining_return_pieces > 0) {
    openedWarehouseReturn = true
    openNewReturn(reworkDetail.value)
  } else if (props.mode === 'original' && originalHandoffs.value.length === 1 && canAct('original-good-return')) {
    openedWarehouseReturn = true
    void openOriginalGoodReturn(originalHandoffs.value[0]!)
  }
})
</script>

<template>
  <section class="p4-page" :class="{ 'p4-embedded': embedded, 'p4-detail-surface': mode !== 'sources' || embedded }" data-testid="metal-processing-p4-page">
    <header v-if="!embedded" class="p4-heading">
      <div class="heading-title"><ElButton text :icon="ArrowLeft" @click="router.push(listPath)">{{ warehouseWorkspace ? '返回委外管理' : '返回委外加工' }}</ElButton><div><h1>{{ mode === 'sources' ? '待外发材料' : '外发单详情' }}</h1><p>{{ mode === 'sources' ? '加工完成登记、外发交接及历史记录' : mode === 'rework' ? '重加工件 · 按支交接和回货' : '金工加工件 · 原外发单' }}</p></div></div>
      <ElButton :icon="Refresh" :loading="loading" :disabled="saving || !!dialog" @click="loadSources">刷新</ElButton>
    </header>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon class="p4-alert" />
    <div v-if="embedded && mode === 'sources'" class="source-toolbar"><span>选择领料部位办理加工完成和外发；已交接、已结清的历史来源仍可查询。</span><ElButton :icon="Refresh" :loading="loading" :disabled="saving || !!dialog" @click="loadSources">刷新</ElButton></div>
    <ElAlert v-if="mode === 'sources' && route.query?.source_action === 'rework'" title="请在所选来源的“退回与重加工”记录中登记完成数量，或选择已有完成记录创建新外发单。" type="info" :closable="false" class="p4-alert" />
    <div v-if="mode === 'sources'" class="p4-layout">
      <aside class="p4-panel p4-source-panel">
        <div class="panel-title"><strong>金工来源</strong><span>{{ filteredSources.length }} 条</span></div>
        <ElInput v-model="search" clearable placeholder="搜索领料单、部位、身份" class="p4-search" />
        <ElSelect v-model="sourceStatus" class="source-status" aria-label="来源状态"><ElOption label="全部来源（含历史）" value="ALL" /><ElOption label="进行中" value="OPEN" /><ElOption label="已结清" value="CLOSED" /></ElSelect>
        <div v-loading="loading" class="source-list">
          <button v-for="row in filteredSources" :key="row.issue_line_id" class="source-item" :class="{ active: source?.issue_line_id === row.issue_line_id }" @click="selectSource(row)">
            <div><strong>{{ row.part_name || '未命名部位' }}</strong><span>{{ row.issue_number }}</span></div>
            <small>{{ row.component_identity }} · {{ row.issued_pieces }} 支</small>
            <div class="source-progress"><span>{{ row.completed_pieces }}/{{ row.issued_pieces }} 支完成</span><span>{{ row.status === 'CLOSED' ? '已结清' : '进行中' }}</span></div>
          </button>
          <ElEmpty v-if="!filteredSources.length && !loading" description="暂无已出库金工管材来源，请先完成领料出库" />
        </div>
      </aside>

      <main v-loading="detailLoading" class="p4-panel p4-detail-panel">
        <template v-if="source">
          <div class="detail-top"><div><span class="eyebrow">来源领料 {{ source.issue_number }}</span><h2>{{ source.part_name || '管材部位' }}</h2><p>{{ source.component_identity }} · 原料 {{ source.bar_count ?? '—' }} 根 / {{ source.meters ?? '—' }} 米</p></div><div class="source-actions"><ElTag :type="source.status === 'CLOSED' ? 'info' : 'success'">{{ source.status === 'CLOSED' ? '已结清' : source.status === 'OPEN' ? '进行中' : '来源异常' }}</ElTag><ElButton v-if="canAct('source-completion')" data-testid="source-completion-button" :disabled="!source.can_register || loading || detailLoading" @click="openSourceOperation('source-completion')">登记加工完成</ElButton><ElButton v-if="canAct('source-close')" data-testid="source-close-button" :disabled="!source.can_close || loading || detailLoading" @click="openSourceOperation('source-close')">来源备注结清</ElButton><ElButton v-if="canAct('handoff')" type="primary" :icon="Plus" :disabled="!canHandoffSource || loading" @click="openHandoff">登记原外发</ElButton></div></div>
          <div class="metric-grid source-metrics" data-testid="source-summary"><div><span>已领支数</span><strong>{{ source.issued_pieces ?? '—' }}</strong></div><div><span>完成加工</span><strong>{{ source.completed_pieces ?? '—' }}</strong></div><div><span>已交接</span><strong>{{ source.dispatched_pieces ?? '—' }}</strong></div><div><span>待外发占用</span><strong>{{ source.reserved_pieces ?? '—' }}</strong></div><div><span>可继续外发</span><strong class="accent">{{ source.available_pieces ?? '—' }}</strong></div></div>
          <ElAlert v-for="blocker in sourceBlockers" :key="blocker" :title="blocker" type="warning" :closable="false" />

          <section class="flow-section" data-testid="source-processing-history">
            <div class="section-title"><h3>加工完成登记记录</h3><span>按本条领料部位登记，原料不重复扣库</span></div>
            <ElTable :data="source.completions || []" border empty-text="暂无加工完成登记" max-height="192"><ElTableColumn prop="completion_date" label="完成日期" width="130" /><ElTableColumn prop="good_pieces" label="合格完成支数" width="130" /><ElTableColumn prop="actor_name" label="操作人" min-width="100" /><ElTableColumn label="登记时间" min-width="180"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></ElTableColumn></ElTable>
            <div v-if="source.closure" class="source-closure-record" data-testid="source-closure-history"><strong>来源结清记录</strong><p>结清时未完成 {{ source.closure.quantities.unfinished_pieces }} 支，完成未交接 {{ source.closure.quantities.unallocated_pieces }} 支；差额保留。</p><p class="preserve-lines">{{ source.closure.remark }}</p><small>{{ source.closure.actor_name }} · {{ formatTime(source.closure.created_at) }}</small><p>来源已停止登记和继续外发；已交接的原外发单可继续登记回货。</p></div>
          </section>

          <section class="flow-section"><div class="section-title"><h3>原外发交接</h3><span>交接的是已完成的管材支数</span></div><ElTable class="scroll-actions-table" :data="source.original_handoffs || []" border empty-text="还没有原外发交接记录"><ElTableColumn prop="factory_name" label="加工厂" min-width="150" /><ElTableColumn prop="original_order_number" label="原外发单" min-width="150" /><ElTableColumn prop="handoff_pieces" label="交接支数" width="100" /><ElTableColumn prop="returned_unsprayed_pieces" label="已退回" width="100" /><ElTableColumn prop="handoff_date" label="交接日期" width="120" /><ElTableColumn label="原单状态" width="150"><template #default="{ row }">{{ originalStatusText(row.original_order_status) }}</template></ElTableColumn><ElTableColumn label="操作" width="320" fixed="right"><template #default="{ row }"><ElButton v-if="canAct('original-good-return')" data-testid="original-good-return-button" link type="primary" :disabled="['COMPLETED', 'CANCELLED'].includes(row.original_order_status || '')" @click="openOriginalGoodReturn(row)">登记合格回货</ElButton><ElButton v-if="canAct('return')" link type="primary" :disabled="remainingReturnPieces(row) <= 0 || !source.etag" :title="returnBlockerText(row)" data-testid="original-unsprayed-return-button" @click="openReturn(row)">登记退回</ElButton><ElButton link type="primary" @click="router.push({ path: `${listPath}/${row.original_order_id}`, query: { view: 'metal' } })">查看详情</ElButton><ElButton data-testid="original-order-context-button" link type="primary" @click="openOriginalOrder(row)">原单收尾</ElButton></template></ElTableColumn></ElTable></section>

          <section v-for="handoff in source.original_handoffs || []" :key="handoff.id" class="flow-section nested-section"><div class="section-title"><h3>{{ handoff.factory_name || '加工厂' }} · 退回与重加工</h3><span>{{ handoff.handoff_pieces }} 支交接，已退 {{ handoff.returned_unsprayed_pieces }} 支</span></div><div v-for="returned in handoff.unsprayed_returns || []" :key="returned.id" class="return-card"><div><strong>退回 {{ returned.returned_pieces }} 支</strong><small>{{ returned.storage_location }} · {{ formatDate(returned.return_date) }}</small></div><ElButton v-if="canAct('rework') && (returned.remaining_rework_pieces ?? returned.returned_pieces) > 0" size="small" @click="openRework(returned)">登记重加工</ElButton><span v-else-if="(returned.remaining_rework_pieces ?? returned.returned_pieces) === 0" class="done-text">已完成重加工</span><div v-for="rework in returned.reworks || []" :key="rework.id" class="rework-line"><span>重加工完成 {{ rework.completed_pieces }} 支，可新外发 {{ rework.remaining_allocatable_pieces }} 支</span><ElButton v-for="id in rework.external_order_ids" :key="id" link type="primary" @click="router.push(`${listPath}/rework/${id}`)">查看关联外发单</ElButton><ElButton v-if="canAct('order') && rework.remaining_allocatable_pieces > 0" size="small" type="primary" @click="openOrder(rework)">创建新外发</ElButton></div></div><ElEmpty v-if="!(handoff.unsprayed_returns || []).length" description="尚未登记未喷塑退回" :image-size="48" /></section>
        </template>
        <ElEmpty v-else description="请从左侧选择金工来源" />
      </main>
    </div>

    <section v-if="mode === 'sources' && !embedded" class="p4-panel orders-panel"><div class="panel-title"><div><strong>新外发单</strong><span>重新加工完成后重新建立，和原外发单分开</span></div><ElTag type="info">{{ visibleOrders.length }} 条</ElTag></div><ElTable :data="visibleOrders" border empty-text="暂无新外发单"><ElTableColumn type="expand"><template #default="{ row }"><div class="allocation-history" data-testid="allocation-history"><div class="section-title"><h3>分配修改记录</h3><span>{{ row.order_number }} · 已交接后不可调整</span></div><ElTable :data="row.allocation_history || []" border empty-text="暂无分配修改记录"><ElTableColumn prop="before_pieces" label="修改前（支）" width="150" /><ElTableColumn prop="after_pieces" label="修改后（支）" width="150" /><ElTableColumn prop="actor_name" label="操作人" min-width="100" /><ElTableColumn label="修改时间" min-width="180"><template #default="{ row: history }">{{ formatTime(history.created_at) }}</template></ElTableColumn></ElTable></div></template></ElTableColumn><ElTableColumn prop="order_number" label="新外发单号" width="190" /><ElTableColumn prop="factory_name" label="加工厂" width="150" /><ElTableColumn prop="craft_name" label="工艺" width="100" /><ElTableColumn prop="allocated_pieces" label="分配支数" width="100" /><ElTableColumn prop="handoff_pieces" label="已交接" width="100" /><ElTableColumn prop="returned_good_pieces" label="合格回货" width="100" /><ElTableColumn label="状态" width="100"><template #default="{ row }"><ElTag :type="row.status === 'COMPLETED' ? 'success' : row.status === 'CLOSED' ? 'info' : 'warning'">{{ statusText(row.status) }}</ElTag></template></ElTableColumn><ElTableColumn label="操作" min-width="400"><template #default="{ row }"><ElButton v-if="canAct('allocation')" data-testid="allocation-button" size="small" :disabled="row.status !== 'PENDING_HANDOFF' || row.handoff_pieces !== 0 || row.allocation_context?.can_adjust === false" @click="openAllocation(row)">{{ row.status === 'PENDING_HANDOFF' && row.handoff_pieces === 0 ? '调整分配' : '调整已锁定' }}</ElButton><ElButton v-if="canAct('new-handoff') && row.status === 'PENDING_HANDOFF'" size="small" type="primary" @click="openNewHandoff(row)">确认交接</ElButton><ElButton v-if="canAct('new-return') && (row.status === 'PROCESSING' || row.status === 'CLOSED') && row.remaining_return_pieces > 0" size="small" @click="openNewReturn(row)">登记合格回货</ElButton><ElButton v-if="canAct('close') && row.status === 'PROCESSING'" size="small" @click="openClose(row)">备注结清</ElButton><ElButton size="small" :icon="Box" @click="showSemiStock(row)">看半成品库存</ElButton></template></ElTableColumn></ElTable></section>

    <section v-if="mode === 'original'" v-loading="loading" class="unified-order-section" data-testid="unified-original-operations">
      <div class="order-operation-heading"><div><h2>{{ orderSummary?.original_order_number || originalHandoffs[0]?.original_order_number || '原外发单' }}</h2><span>材料来源：{{ originalHandoffs.length ? '金工加工件' : '待选择 · 金工来源已预选，交接后确认' }}</span></div><div class="source-actions"><ElButton :icon="Refresh" :loading="loading" :disabled="saving || !!dialog" @click="loadSources">刷新</ElButton><ElButton :disabled="loading || !!dialog" @click="openOrderSummary">收尾与记录</ElButton></div></div>
      <ElAlert v-if="summaryError" :title="summaryError" type="warning" :closable="false" class="p4-alert" />
      <div v-if="orderSummary" class="metric-grid original-unified-metrics" data-testid="unified-original-summary"><div><span>计划外发</span><strong>{{ orderSummary.totals.planned_pieces }} 支</strong></div><div><span>实际交接</span><strong>{{ orderSummary.totals.handoff_pieces }} 支</strong></div><div><span>合格回货</span><strong>{{ orderSummary.totals.returned_good_pieces }} 支</strong></div><div><span>未喷塑退回</span><strong>{{ orderSummary.totals.returned_unsprayed_pieces }} 支</strong></div><div><span>当前待回</span><strong class="accent">{{ orderSummary.totals.remaining_return_pieces }} 支</strong></div></div>
      <p class="original-good-note">交接的是金工已领料并完成加工的支数；原料不重复扣库，合格回货进入半成品仓。</p>
      <section class="p4-panel unified-record-card"><ElTabs v-model="recordTab">
        <ElTabPane label="外发明细" name="handoffs"><ElTable :data="originalHandoffs" border empty-text="尚无实际交接记录"><ElTableColumn prop="part_name" label="部位" min-width="140" /><ElTableColumn prop="issue_number" label="来源领料" min-width="170" /><ElTableColumn prop="factory_name" label="加工厂" min-width="140" /><ElTableColumn prop="handoff_pieces" label="交接（支）" width="112" /><ElTableColumn prop="handoff_date" label="交接日期" width="120" /><ElTableColumn label="操作" min-width="310"><template #default="{ row }"><ElButton v-if="canAct('original-good-return')" link type="primary" :disabled="['COMPLETED', 'CANCELLED'].includes(row.original_order_status || '')" @click="openOriginalGoodReturn(row)">{{ row.original_order_status === 'CLOSED' ? '补登记合格回货' : '登记合格回货' }}</ElButton><ElButton v-if="canAct('return')" link type="primary" :disabled="remainingReturnPieces(row) <= 0 || !row.source.etag" @click="openReturn(row)">{{ row.original_order_status === 'CLOSED' ? '补登记未喷塑退回' : '登记未喷塑退回' }}</ElButton></template></ElTableColumn></ElTable>
          <details v-if="orderSummary" class="plan-quantity-review"><summary>计划与数量核对 <span>{{ originalStatusText(orderSummary.original_order_status) }} · 各部位独立核算</span></summary><ElTable :data="orderSummary.parts" border><ElTableColumn prop="part_name" label="部位" min-width="150" /><ElTableColumn prop="factory_name" label="加工厂" min-width="150" /><ElTableColumn prop="planned_pieces" label="计划（支）" width="112" /><ElTableColumn prop="handoff_pieces" label="实交（支）" width="112" /><ElTableColumn prop="returned_good_pieces" label="合格回货（支）" width="130" /><ElTableColumn prop="returned_unsprayed_pieces" label="未喷塑退回（支）" width="145" /><ElTableColumn prop="remaining_return_pieces" label="待回（支）" width="112" /><ElTableColumn prop="pending_handoff_pieces" label="待交接（支）" width="120" /></ElTable></details>
          <div class="section-title related-source-title"><h3>继续交接</h3><span>从真实来源选择可用加工件</span></div><div v-if="canAct('handoff') && !['CLOSED','COMPLETED','CANCELLED'].includes(orderSummary?.original_order_status || '')" class="source-handoff-row"><ElButton :loading="candidatesLoading" @click="loadHandoffCandidates">选择其他金工来源</ElButton><ElSelect v-if="handoffCandidates.length" v-model="candidateId" filterable placeholder="选择领料单 / 部位" style="width:380px"><ElOption v-for="item in handoffCandidates" :key="item.issue_line_id" :value="item.issue_line_id" :label="`${item.issue_number} / ${item.part_name} · ${item.available_pieces} 支`" /></ElSelect><ElButton v-if="candidateId" type="primary" :loading="candidatesLoading" @click="handoffCandidate">登记所选来源交接</ElButton></div><div v-for="item in relatedSources" :key="item.issue_line_id" class="source-handoff-row"><span>{{ item.part_name }} · {{ item.issue_number }}</span><span>可外发 {{ item.available_pieces }} 支</span><ElButton v-if="canAct('handoff')" :disabled="item.status !== 'OPEN' || item.available_pieces <= 0 || !item.etag || ['CLOSED','COMPLETED','CANCELLED'].includes(orderSummary?.original_order_status || '')" @click="openSourceHandoff(item)">登记交接</ElButton><ElButton v-if="canViewSource" link type="primary" @click="router.push({ path: '/workshop/outsourcing', query: { tab: 'sources', source_issue_line_id: item.issue_line_id } })">查看来源</ElButton></div><ElEmpty v-if="!relatedSources.length && !loading" description="未找到可访问的金工来源，请从待外发材料选择真实来源" :image-size="64" />
        </ElTabPane>
        <ElTabPane label="回货记录" name="returns"><ElTable :data="goodReturnRows" border empty-text="暂无可查看的合格回货记录"><ElTableColumn prop="return_number" label="回货单号" min-width="170" /><ElTableColumn prop="part_name" label="部位" min-width="130" /><ElTableColumn prop="factory_name" label="加工厂" min-width="140" /><ElTableColumn prop="good_pieces" label="合格（支）" width="110" /><ElTableColumn prop="return_date" label="回货日期" width="120" /><ElTableColumn prop="zone_name" label="半成品库区" min-width="140" /><ElTableColumn prop="received_by_employee_name" label="接收人" width="100" /><ElTableColumn prop="remark" label="备注" min-width="180" /></ElTable></ElTabPane>
        <ElTabPane label="退回与重加工" name="rework"><template v-for="item in sourceGroups" :key="item.issue_line_id"><section v-for="handoff in item.original_handoffs" :key="handoff.id" class="flow-section"><div class="section-title"><h3>{{ item.part_name }} · {{ handoff.factory_name }}</h3><span>已退回 {{ handoff.returned_unsprayed_pieces }} 支</span></div><div v-for="returned in handoff.unsprayed_returns || []" :key="returned.id" class="return-card"><div><strong>未喷塑退回 {{ returned.returned_pieces }} 支</strong><small>{{ formatDate(returned.return_date) }} · {{ returned.storage_location }} · {{ returned.remark || '无备注' }}</small></div><ElButton v-if="canAct('rework') && (returned.remaining_rework_pieces ?? returned.returned_pieces) > 0" @click="openRework(returned)">登记重加工</ElButton><div v-for="rework in returned.reworks || []" :key="rework.id" class="rework-line"><span>完成 {{ rework.completed_pieces }} 支 · 可新外发 {{ rework.remaining_allocatable_pieces }} 支</span><div><ElButton v-for="id in rework.external_order_ids" :key="id" link type="primary" @click="router.push(`${listPath}/rework/${id}`)">查看关联外发单</ElButton><ElButton v-if="canAct('order') && rework.remaining_allocatable_pieces > 0" type="primary" @click="openOrder(rework)">创建新外发</ElButton></div></div></div><ElEmpty v-if="!handoff.unsprayed_returns?.length" description="暂无未喷塑退回记录" :image-size="48" /></section></template><ElEmpty v-if="!originalHandoffs.length" description="暂无退回与重加工记录" :image-size="64" /></ElTabPane>
        <ElTabPane label="操作记录" name="closure"><div v-if="orderSummary?.closure" class="source-closure-record"><strong>原单已备注结清，差额 {{ orderSummary.closure.quantity_snapshot.totals.remaining_return_pieces }} 支</strong><p class="preserve-lines">{{ orderSummary.closure.remark }}</p><small>{{ orderSummary.closure.actor_name }} · {{ formatTime(orderSummary.closure.created_at) }}</small></div><p v-else class="original-good-note">尚未备注结清。待交接余量取消、结清差额与历史记录可在“收尾与记录”中核对。</p><ElTable :data="orderSummary?.post_closure_returns || []" border empty-text="暂无结清后补登记"><ElTableColumn prop="part_name" label="部位" min-width="150" /><ElTableColumn label="类型" width="145"><template #default="{ row }">{{ row.kind === 'GOOD' ? '合格补回' : '未喷塑补退' }}</template></ElTableColumn><ElTableColumn prop="pieces" label="数量（支）" width="112" /><ElTableColumn prop="remark" label="原因" min-width="180" /><ElTableColumn prop="actor_name" label="操作人" width="112" /><ElTableColumn label="登记时间" min-width="180"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></ElTableColumn></ElTable></ElTabPane>
      </ElTabs></section>
    </section>

    <section v-if="mode === 'rework'" v-loading="loading" class="unified-order-section" data-testid="unified-rework-detail">
      <template v-if="reworkDetail"><div class="order-operation-heading"><div><h2>{{ reworkDetail.order_number }}</h2><span>材料来源：重加工件 · {{ statusText(reworkDetail.status) }}</span></div><div class="source-actions"><ElButton v-if="canAct('allocation') && reworkDetail.status === 'PENDING_HANDOFF'" data-testid="rework-allocation-button" @click="openAllocation(reworkDetail)">调整分配</ElButton><ElButton v-if="canAct('new-handoff') && reworkDetail.status === 'PENDING_HANDOFF'" type="primary" @click="openNewHandoff(reworkDetail)">确认交接</ElButton><ElButton v-if="canAct('new-return') && ['PROCESSING','CLOSED'].includes(reworkDetail.status) && reworkDetail.remaining_return_pieces > 0" type="primary" @click="openNewReturn(reworkDetail)">{{ reworkDetail.status === 'CLOSED' ? '补登记合格回货' : '登记合格回货' }}</ElButton><ElButton v-if="canAct('close') && reworkDetail.status === 'PROCESSING'" @click="openClose(reworkDetail)">备注结清</ElButton><ElButton :icon="Box" @click="showSemiStock(reworkDetail)">看半成品库存</ElButton></div></div>
        <div class="p4-panel unified-record-card rework-identity"><div><span>加工厂</span><strong>{{ reworkDetail.factory_name }}</strong></div><div><span>工艺</span><strong>{{ reworkDetail.craft_name }}</strong></div><div><span>来源领料 / 部位</span><strong>{{ source?.issue_number || '—' }} / {{ source?.part_name || '—' }}</strong></div><div><span>交货日期</span><strong>—</strong></div><div><span>原外发单</span><ElButton v-if="reworkOrigin" link type="primary" @click="router.push({ path: `${listPath}/${reworkOrigin.handoff.original_order_id}`, query: { view: 'metal' } })">{{ reworkOrigin.handoff.original_order_number || '查看原外发单' }}</ElButton><strong v-else>未取得来源关联</strong></div><div><span>原退回</span><strong>{{ reworkOrigin ? `${reworkOrigin.returned.returned_pieces} 支 · ${formatDate(reworkOrigin.returned.return_date)}` : '—' }}</strong></div></div>
        <div class="metric-grid"><div><span>计划分配</span><strong>{{ reworkDetail.allocated_pieces }} 支</strong></div><div><span>实际交接</span><strong>{{ reworkDetail.handoff_pieces }} 支</strong></div><div><span>合格回货</span><strong>{{ reworkDetail.returned_good_pieces }} 支</strong></div><div><span>当前待回</span><strong class="accent">{{ reworkDetail.remaining_return_pieces }} 支</strong></div></div>
        <div class="p4-panel rework-identity" data-testid="rework-pricing"><div><span>加工单价</span><strong>{{ formatOutsourcingMoney(reworkDetail.unit_price) }}<template v-if="reworkDetail.unit_price != null"> 元/支</template></strong></div><div><span>计划加工金额</span><strong>{{ formatOutsourcingMoney(reworkDetail.planned_amount) }}<template v-if="reworkDetail.planned_amount != null"> 元</template></strong></div></div>
        <p class="original-good-note">重加工件交接不再扣减原料。回货只接收合格半成品；结清后的补登记保留原差额和原因。</p>
        <section class="p4-panel unified-record-card"><ElTabs v-model="recordTab"><ElTabPane label="交接与回货" name="handoffs"><div class="section-title"><h3>交接记录</h3><span>{{ reworkDetail.handoff ? `${formatDate(reworkDetail.handoff.handoff_date)} · ${reworkDetail.handoff.handoff_pieces} 支` : '尚未实际交接' }}</span></div><ElTable :data="reworkDetail.good_returns" border empty-text="暂无合格回货"><ElTableColumn prop="return_number" label="回货单号" min-width="180" /><ElTableColumn prop="return_date" label="回货日期" width="130" /><ElTableColumn prop="good_pieces" label="合格（支）" width="120" /><ElTableColumn label="半成品库区" min-width="160"><template #default="{ row }">{{ options?.semi_finished_zones.find(zone => zone.id === row.zone_id)?.name || '未取得库区名称' }}</template></ElTableColumn><ElTableColumn label="类型" width="140"><template #default="{ row }">{{ row.post_closure ? '结清后补回' : '正常回货' }}</template></ElTableColumn><ElTableColumn prop="remark" label="备注" min-width="200" /></ElTable></ElTabPane><ElTabPane label="分配修改记录" name="allocation"><ElTable :data="reworkDetail.allocation_history || []" border empty-text="暂无分配修改记录"><ElTableColumn prop="before_pieces" label="修改前（支）" width="160" /><ElTableColumn prop="after_pieces" label="修改后（支）" width="160" /><ElTableColumn prop="actor_name" label="操作人" min-width="130" /><ElTableColumn label="修改时间" min-width="200"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></ElTableColumn></ElTable></ElTabPane><ElTabPane label="结清记录" name="closure"><div v-if="reworkDetail.closure" class="source-closure-record"><p class="preserve-lines">{{ reworkDetail.closure.remark }}</p><small>{{ formatTime(reworkDetail.closure.created_at) }}</small><p>结清时剩余 {{ reworkDetail.closure.quantity_snapshot.difference_pieces ?? '—' }} 支，历史差额保留。</p></div><ElEmpty v-else description="尚未备注结清" :image-size="64" /></ElTabPane></ElTabs></section>
      </template><ElEmpty v-else-if="!loading && !error" description="未找到可访问的外发单" />
    </section>

    <section v-if="semiStock" class="p4-panel stock-panel"><div class="panel-title"><div><strong>半成品库存</strong><span>{{ semiStock.part_name }} · 不按批次，按统一库区汇总</span></div><ElTag type="success">{{ semiStock.available_pieces }} 支</ElTag></div><ElTable :data="semiStock.zones" border><ElTableColumn prop="zone_name" label="库区" /><ElTableColumn prop="available_pieces" label="可用支数" width="130" /><ElTableColumn label="领用方式" width="160"><template #default>按正整数支领取</template></ElTableColumn></ElTable></section>

    <AppWindowDialog v-model="dialogVisible" :class="{ 'p4-detail-dialog': mode !== 'sources' || embedded }" :title="dialogTitle" :width="dialogWidth" :height="dialogHeight" destroy-on-close :close-on-click-modal="false" :show-close="!saving && !uncertainOutcome" :close-on-press-escape="!saving && !uncertainOutcome"><ElAlert v-if="dialogError" :title="dialogError" type="error" :closable="false" show-icon class="p4-alert" /><ElForm label-width="120px" class="p4-form" :disabled="saving || uncertainOutcome || originalGoodLoading || contextLoading"><template v-if="dialog === 'handoff'"><ElFormItem label="原外发单"><ElSelect v-model="handoffForm.originalOrderId" filterable :disabled="mode === 'original'"><ElOption v-for="row in legacyOrders" :key="row.id" :value="row.id" :label="row.order_number" /></ElSelect></ElFormItem><ElFormItem label="加工厂"><ElSelect v-model="handoffForm.factoryId" filterable><ElOption v-for="row in options?.factories || []" :key="row.id" :value="row.id" :label="row.name" /></ElSelect></ElFormItem><ElFormItem label="交接支数"><ElInput v-model="handoffForm.pieces" inputmode="numeric" /></ElFormItem><ElFormItem label="交接日期"><ElDatePicker v-model="handoffForm.date" type="date" value-format="YYYY-MM-DD" /></ElFormItem></template><template v-else-if="dialog === 'return'">
        <div v-loading="contextLoading" data-testid="original-unsprayed-return-dialog" class="original-return-dialog">
          <template v-if="returnContext">
            <div class="original-good-identity"><div><span>原外发单 / 加工厂</span><strong>{{ returnContext.original_order_number }} · {{ returnContext.factory_name }}</strong></div><div><span>当前状态 / 本次可退</span><strong>{{ originalStatusText(returnContext.original_order_status) }} / {{ remainingReturnPieces(returnContext) }} 支</strong></div></div>
            <p v-if="returnContext.original_order_status === 'CLOSED'" class="operation-note" data-testid="unsprayed-post-closure-note">原单已备注结清，本次补登记原因必填。只登记金工暂存，与合格回货共用本部位剩余额度。</p>
            <div v-if="returnContext.original_order_closure" class="compact-closure" data-testid="unsprayed-closure-snapshot"><strong>结清时差额 {{ returnContext.original_order_closure.quantity_snapshot.totals.remaining_return_pieces }} 支，历史快照保留</strong><p>{{ returnContext.original_order_closure.remark }}</p><small>{{ returnContext.original_order_closure.actor_name }} · {{ formatTime(returnContext.original_order_closure.created_at) }}</small></div>
            <div class="original-good-fields return-fields"><ElFormItem label="退回支数" required><ElInput v-model="returnForm.pieces" data-testid="unsprayed-pieces" inputmode="numeric"><template #append>支</template></ElInput></ElFormItem><ElFormItem label="接收人" required><ElSelect v-model="returnForm.receiverId"><ElOption v-for="row in options?.receivers || []" :key="row.id" :value="row.id" :label="row.name" /></ElSelect></ElFormItem><ElFormItem label="暂存位置" required><ElInput v-model="returnForm.storage" data-testid="unsprayed-storage" placeholder="例如：金工车间暂存架" /></ElFormItem><ElFormItem label="退回日期" required><ElDatePicker v-model="returnForm.date" type="date" value-format="YYYY-MM-DD" /></ElFormItem></div>
            <ElFormItem :label="returnContext.original_order_status === 'CLOSED' ? '补登记原因' : '备注'" :required="returnContext.original_order_status === 'CLOSED'"><ElInput v-model="returnForm.remark" data-testid="unsprayed-reason" type="textarea" :rows="2" /></ElFormItem>
            <div class="original-good-preview" data-testid="unsprayed-return-preview"><div><span>金工暂存增加</span><strong>{{ returnPreview?.pieces ?? '—' }} 支</strong></div><div><span>本次登记后可继续退</span><strong>{{ returnPreview?.remaining ?? '—' }} 支</strong></div><div><span>原材料扣减</span><strong>0 根 / 0.00 米</strong></div></div>
            <p class="original-good-note">未喷塑退回不进入合格半成品库存、不恢复原料；后续按实际重新加工完成数量建立新外发单。</p>
          </template><ElEmpty v-else-if="!contextLoading" description="退回信息加载失败，请关闭弹窗后重试" :image-size="64" />
        </div>
      </template>
      <template v-else-if="dialog === 'original-close'">
        <div v-loading="contextLoading" class="original-order-dialog" data-testid="original-order-dialog">
          <template v-if="originalOrderContext">
            <div class="original-order-heading"><div><span>原外发单 · 按各部位实际交接核对</span><h3>{{ originalOrderContext.original_order_number }}</h3></div><ElTag :type="originalOrderContext.original_order_status === 'COMPLETED' ? 'success' : 'info'" data-testid="original-order-status">{{ originalStatusText(originalOrderContext.original_order_status) }}</ElTag></div>
            <div class="metric-grid" data-testid="original-order-summary"><div><span>实际交接</span><strong>{{ originalOrderContext.totals.handoff_pieces }} 支</strong></div><div><span>合格回货</span><strong>{{ originalOrderContext.totals.returned_good_pieces }} 支</strong></div><div><span>未喷塑退回</span><strong>{{ originalOrderContext.totals.returned_unsprayed_pieces }} 支</strong></div><div><span>当前剩余</span><strong class="accent">{{ originalOrderContext.totals.remaining_return_pieces }} 支</strong></div></div>
            <ElAlert v-for="blocker in originalOrderContext.blockers" :key="blocker" :title="blocker" type="warning" :closable="false" class="p4-alert" />
            <section data-testid="original-order-parts"><div class="section-title"><h3>各部位数量</h3><span>各部位独立核算，不能互相抵数</span></div><ElTable :data="originalOrderContext.parts" border empty-text="暂无原单分配明细" max-height="238"><ElTableColumn label="产品 / 部位" min-width="160"><template #default="{ row }"><strong>{{ row.part_name }}</strong><small class="part-subtitle">{{ row.product_number }} {{ row.product_name }}</small><small class="part-subtitle">{{ row.specification }}</small></template></ElTableColumn><ElTableColumn prop="factory_name" label="加工厂" min-width="110" /><ElTableColumn prop="handoff_pieces" label="实交" width="74" /><ElTableColumn prop="returned_good_pieces" label="合格回货" width="90" /><ElTableColumn prop="returned_unsprayed_pieces" label="未喷塑退回" width="102" /><ElTableColumn prop="remaining_return_pieces" label="剩余" width="74" /><ElTableColumn prop="pending_handoff_pieces" label="待交接" width="84" /><ElTableColumn label="操作" width="140"><template #default="{ row }"><ElButton v-if="canAct('original-cancel-pending')" data-testid="original-cancel-pending-button" link type="primary" :disabled="!row.can_cancel_pending" @click="openOriginalCancel(row)">取消待交接余量</ElButton><span v-else>—</span></template></ElTableColumn></ElTable></section>
            <p class="original-good-note" data-testid="original-order-pending-summary">待交接 {{ originalOrderContext.totals.pending_handoff_pieces }} 支。原单有正数实交、每个部位剩余为 0 且无待交接分配时自动完成。</p>
            <template v-if="originalOrderContext.closure">
              <section class="closure-snapshot-section" data-testid="original-closure-snapshot"><div class="section-title"><h3>结清时快照</h3><span>历史留存，后续补登记不改写</span></div><p>{{ originalOrderContext.closure.actor_name }} · {{ formatTime(originalOrderContext.closure.created_at) }}</p><ElTable :data="originalOrderContext.closure.quantity_snapshot.parts" border max-height="174"><ElTableColumn prop="part_name" label="部位" min-width="140" /><ElTableColumn prop="factory_name" label="加工厂" min-width="120" /><ElTableColumn prop="handoff_pieces" label="实交" width="100" /><ElTableColumn prop="returned_good_pieces" label="合格回货" width="110" /><ElTableColumn prop="returned_unsprayed_pieces" label="未喷塑退回" width="120" /><ElTableColumn prop="remaining_return_pieces" label="结清差额" width="110" /></ElTable><p class="preserve-lines">结清差额合计 {{ originalOrderContext.closure.quantity_snapshot.totals.remaining_return_pieces }} 支。备注：{{ originalOrderContext.closure.remark }}</p></section>
              <section class="flow-section" data-testid="original-post-closure-history"><div class="section-title"><h3>结清后补登记</h3><span>原结清记录保留，两类补登记共用部位剩余额度</span></div><ElTable :data="originalOrderContext.post_closure_returns" border empty-text="暂无结清后补登记" max-height="185"><ElTableColumn label="登记类型" width="115"><template #default="{ row }">{{ row.kind === 'GOOD' ? '合格补回' : '未喷塑补退' }}</template></ElTableColumn><ElTableColumn prop="part_name" label="部位" min-width="100" /><ElTableColumn prop="pieces" label="支数" width="74" /><ElTableColumn prop="remark" label="原因" min-width="180" /><ElTableColumn prop="actor_name" label="操作人" width="100" /><ElTableColumn label="登记时间" min-width="175"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></ElTableColumn></ElTable></section>
            </template>
            <ElFormItem v-else-if="!['COMPLETED', 'CANCELLED'].includes(originalOrderContext.original_order_status) && canAct('original-close')" label="结清备注" required class="original-close-field"><ElInput v-model="originalCloseForm.remark" data-testid="original-close-reason" type="textarea" :rows="3" maxlength="1000" show-word-limit placeholder="核对各部位差额后填写原因；结清保留实际数字和差额" /></ElFormItem>
            <section v-if="originalOrderContext.pending_cancellations?.length" class="flow-section" data-testid="original-pending-cancellation-history"><div class="section-title"><h3>待交接余量取消记录</h3><span>原计划保留，仅取消未交部分</span></div><ElTable :data="originalOrderContext.pending_cancellations" border max-height="170"><ElTableColumn prop="part_name" label="部位" min-width="120" /><ElTableColumn prop="cancelled_pieces" label="取消支数" width="100" /><ElTableColumn prop="remark" label="原因" min-width="180" /><ElTableColumn prop="actor_name" label="操作人" width="100" /><ElTableColumn label="操作时间" min-width="175"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></ElTableColumn></ElTable></section>
            <p class="operation-note">本页只处理原单实物流转。合格回货入半成品仓，未喷塑退回登记金工暂存；均不再次扣减或恢复原料，不连带结束金工来源、采购或生产任务，不产生费用或付款。</p>
          </template><ElEmpty v-else-if="!contextLoading" description="原单信息加载失败，请关闭弹窗后重试" :image-size="64" />
        </div>
      </template>
      <template v-else-if="dialog === 'original-cancel-pending'">
        <div v-loading="contextLoading" data-testid="original-cancel-pending-dialog">
          <template v-if="originalOrderContext && selectedPending">
            <div class="original-good-identity"><div><span>原外发单</span><strong>{{ originalOrderContext.original_order_number }}</strong></div><div><span>部位 / 加工厂</span><strong>{{ selectedPending.part_name }} / {{ selectedPending.factory_name }}</strong></div></div>
            <div class="metric-grid pending-cancel-summary" data-testid="original-cancel-pending-summary"><div><span>原计划</span><strong>{{ selectedPending.planned_pieces }} 支</strong></div><div><span>已实际交接</span><strong>{{ selectedPending.handoff_pieces }} 支</strong></div><div><span>本次取消待交</span><strong>{{ selectedPending.pending_handoff_pieces }} 支</strong></div><div><span>取消后有效计划</span><strong>{{ selectedPending.effective_planned_pieces - selectedPending.pending_handoff_pieces }} 支</strong></div></div>
            <ElFormItem label="取消原因" required><ElInput v-model="originalCancelForm.remark" data-testid="original-cancel-pending-reason" type="textarea" :rows="4" maxlength="1000" show-word-limit placeholder="说明该部位剩余计划不再交接的原因" /></ElFormItem>
            <p class="operation-note">仅取消该行当前全部待交接余量，已交接数量不可撤销；原计划及取消记录保留，不改变库存。取消后，若各部位已回齐且没有待交接分配，原单自动完成。</p>
          </template><ElEmpty v-else-if="!contextLoading" description="待交接分配已变化，请关闭弹窗重新核对" :image-size="64" />
        </div>
      </template>
      <template v-else-if="isSourceDialog">
        <div v-loading="contextLoading" class="source-operation-dialog" :data-testid="dialog === 'source-completion' ? 'source-completion-dialog' : 'source-close-dialog'">
          <template v-if="sourceContext">
            <div class="original-good-identity"><div><span>部位 / 来源领料</span><strong>{{ sourceContext.part_name }} · {{ sourceContext.issue_number }}</strong></div><div><span>原材料追溯</span><strong>{{ sourceContext.issued_pieces ?? '—' }} 支 → {{ sourceContext.bar_count ?? '—' }} 根 / {{ sourceContext.meters ?? '—' }} 米</strong></div></div>
            <template v-if="dialog === 'source-completion'">
              <div class="metric-grid two-metrics" data-testid="source-completion-summary"><div><span>累计合格完成</span><strong>{{ sourceContext.completed_pieces ?? '—' }} 支</strong></div><div><span>本次最多可登记</span><strong>{{ sourceContext.remaining_completion_pieces ?? '—' }} 支</strong></div></div>
              <div class="original-good-fields"><ElFormItem label="本次合格完成" required><ElInput v-model="sourceCompletionForm.pieces" data-testid="source-completion-pieces" inputmode="numeric" placeholder="填写正整数"><template #append>支</template></ElInput></ElFormItem><ElFormItem label="完成日期" required><ElDatePicker v-model="sourceCompletionForm.date" data-testid="source-completion-date" type="date" value-format="YYYY-MM-DD" /></ElFormItem></div>
              <p class="operation-note">只登记实际合格完成支数；累计不能超过已领 {{ sourceContext.issued_pieces ?? '—' }} 支。本次不入半成品仓，也不产生报工计薪或报废记录。</p>
            </template>
            <template v-else>
              <div class="metric-grid source-metrics" data-testid="source-close-summary"><div><span>已领</span><strong>{{ sourceContext.issued_pieces ?? '—' }}</strong></div><div><span>已完成</span><strong>{{ sourceContext.completed_pieces ?? '—' }}</strong></div><div><span>已交接</span><strong>{{ sourceContext.dispatched_pieces ?? '—' }}</strong></div><div><span>待外发占用</span><strong>{{ sourceContext.reserved_pieces ?? '—' }}</strong></div><div><span>当前可外发</span><strong>{{ sourceContext.available_pieces ?? '—' }}</strong></div></div>
              <div class="source-close-difference" data-testid="source-close-difference">未完成 <strong>{{ sourceContext.unfinished_pieces ?? '—' }} 支</strong><span>完成未交接 <strong>{{ sourceContext.unallocated_pieces ?? '—' }} 支</strong></span><small>差额保留，不计为报废</small></div>
              <ElFormItem label="结清备注" required><ElInput v-model="sourceCloseForm.remark" data-testid="source-close-remark" type="textarea" :rows="4" maxlength="1000" show-word-limit placeholder="说明该来源停止加工及交接的原因，实际数量和差额保留" /></ElFormItem>
              <p class="operation-note">仅结清当前金工来源，之后停止登记和继续外发；已交接的原外发单继续回货。原实际数量与库存不变。</p>
            </template>
          </template>
          <ElEmpty v-else-if="!contextLoading" description="来源加载失败，请关闭弹窗后重试" :image-size="64" />
        </div>
      </template>
      <template v-else-if="dialog === 'allocation'">
        <div v-loading="contextLoading" data-testid="allocation-dialog" class="allocation-dialog">
          <template v-if="selectedOrder?.allocation_context">
            <div class="original-good-identity"><div><span>新外发单 / 状态</span><strong>{{ selectedOrder.order_number }} / {{ statusText(selectedOrder.status) }}</strong></div><div><span>来源 / 部位</span><strong>{{ selectedOrder.allocation_context.issue_number || '—' }} / {{ selectedOrder.allocation_context.part_name || '—' }}</strong></div><div><span>加工厂</span><strong>{{ selectedOrder.factory_name }}</strong></div><div><span>喷塑工艺</span><strong>{{ selectedOrder.craft_name }}</strong></div></div>
            <div class="metric-grid allocation-metrics" data-testid="allocation-summary"><div><span>本单原分配</span><strong>{{ selectedOrder.allocated_pieces }} 支</strong></div><div><span>其他新单已分配</span><strong>{{ selectedOrder.allocation_context.other_allocated_pieces }} 支</strong></div><div><span>本单可调上限</span><strong class="accent">{{ selectedOrder.allocation_context.max_allocatable_pieces }} 支</strong></div></div>
            <ElFormItem label="调整后分配数量" required><ElInput v-model="allocationForm.pieces" data-testid="allocation-pieces" inputmode="numeric" placeholder="填写正整数"><template #append>支</template></ElInput><small class="form-tip">重新加工完成 {{ selectedOrder.allocation_context.rework_completed_pieces }} 支，扣除其他单占用后，本单最多 {{ selectedOrder.allocation_context.max_allocatable_pieces }} 支。</small></ElFormItem>
            <div class="original-good-preview" data-testid="allocation-preview"><div><span>本单调整</span><strong>{{ selectedOrder.allocated_pieces }} → {{ allocationPreview ? allocationForm.pieces : '—' }} 支</strong></div><div><span>调整后总分配</span><strong>{{ allocationPreview?.total ?? '—' }} 支</strong></div><div><span>重新加工剩余可分配</span><strong>{{ allocationPreview?.remaining ?? '—' }} 支</strong></div></div>
            <p class="operation-note">只调整本单分配数量并保留修改记录；来源、加工厂和工艺不变，不增加原来源完成量，不扣原料或半成品库存。交接时按最终保存数量执行。</p>
            <section data-testid="allocation-dialog-history"><div class="section-title"><h3>分配修改记录</h3><span>保留修改前后数量、操作人和时间</span></div><ElTable :data="selectedOrder.allocation_history || []" border empty-text="暂无分配修改记录" max-height="164"><ElTableColumn prop="before_pieces" label="修改前（支）" width="128" /><ElTableColumn prop="after_pieces" label="修改后（支）" width="128" /><ElTableColumn prop="actor_name" label="操作人" min-width="100" /><ElTableColumn label="修改时间" min-width="180"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></ElTableColumn></ElTable></section>
          </template>
          <ElEmpty v-else-if="!contextLoading" description="分配信息加载失败，请关闭弹窗后重试" :image-size="64" />
        </div>
      </template><template v-else-if="dialog === 'original-good-return'">
        <div v-loading="originalGoodLoading" data-testid="original-good-return-dialog" class="original-good-dialog">
          <template v-if="originalGoodContext">
            <div class="original-good-identity"><div><span>原外发单</span><strong>{{ originalGoodContext.original_order_number }}</strong></div><div><span>对应部位 / 加工厂</span><strong>{{ originalGoodContext.part_name }} · {{ originalGoodContext.factory_name }}</strong></div></div>
            <p class="original-good-note">按本单实际交接数量核对回货额度；仅接收合格半成品，原材料不重复扣库。</p>
            <p v-if="originalGoodContext.post_closure || originalGoodContext.original_order_status === 'CLOSED'" class="operation-note" data-testid="good-post-closure-note">原单已备注结清，本次补登记原因必填；和未喷塑退回共用本部位剩余额度。</p>
            <div v-if="originalGoodContext.closure" class="compact-closure" data-testid="good-closure-snapshot"><strong>结清时差额 {{ originalGoodContext.closure.quantity_snapshot.totals.remaining_return_pieces }} 支，历史快照保留</strong><p>{{ originalGoodContext.closure.remark }}</p><small>{{ originalGoodContext.closure.actor_name }} · {{ formatTime(originalGoodContext.closure.created_at) }}</small></div>
            <div class="metric-grid original-good-summary" data-testid="original-good-return-summary"><div><span>实际交接</span><strong>{{ originalGoodContext.handoff_pieces }} <small>支</small></strong></div><div><span>已合格回货</span><strong>{{ originalGoodContext.returned_good_pieces }} <small>支</small></strong></div><div><span>未喷塑退回</span><strong>{{ originalGoodContext.returned_unsprayed_pieces }} <small>支</small></strong></div><div><span>本次可回</span><strong class="accent">{{ originalGoodContext.remaining_return_pieces }} <small>支</small></strong></div></div>
            <div class="original-good-fields">
              <ElFormItem label="本次合格回货" required><ElInput v-model="originalGoodForm.pieces" data-testid="original-good-pieces" inputmode="numeric" placeholder="填写正整数"><template #append>支</template></ElInput></ElFormItem>
              <ElFormItem label="半成品库区" required><ElSelect v-model="originalGoodForm.zoneId"><ElOption v-for="row in options?.semi_finished_zones || []" :key="row.id" :value="row.id" :label="row.name" /></ElSelect></ElFormItem>
              <ElFormItem label="接收人" required><ElSelect v-model="originalGoodForm.receiverId"><ElOption v-for="row in options?.receivers || []" :key="row.id" :value="row.id" :label="row.name" /></ElSelect></ElFormItem>
              <ElFormItem label="回货日期" required><ElDatePicker v-model="originalGoodForm.date" type="date" value-format="YYYY-MM-DD" /></ElFormItem>
            </div>
            <ElFormItem :label="originalGoodContext.post_closure || originalGoodContext.original_order_status === 'CLOSED' ? '补登记原因' : '备注'" :required="originalGoodContext.post_closure || originalGoodContext.original_order_status === 'CLOSED'"><ElInput v-model="originalGoodForm.remark" data-testid="original-good-reason" type="textarea" :rows="2" :placeholder="originalGoodContext.post_closure || originalGoodContext.original_order_status === 'CLOSED' ? '填写结清后补回原因，原结清记录保持不变' : '选填，例如送货说明'" /></ElFormItem>
            <div class="original-good-preview" data-testid="original-good-return-preview"><div><span>本次入半成品</span><strong>{{ originalGoodPreview?.pieces ?? '—' }} 支</strong></div><div><span>回货后可继续回</span><strong>{{ originalGoodPreview?.remaining ?? '—' }} 支</strong></div><div><span>原材料扣除</span><strong>0 根 / 0.00 米</strong></div></div>
            <p class="original-good-note">交接后，原单的旧原料发料、编辑和取消入口锁定；本次回货不变更原来的完成加工量。</p>
            <section data-testid="original-good-return-history" class="original-good-history"><div class="section-title"><h3>合格回货记录</h3><span>累计 {{ originalGoodContext.returned_good_pieces }} 支</span></div><ElTable :data="originalGoodContext.good_returns" border empty-text="暂无合格回货记录" max-height="166"><ElTableColumn prop="return_date" label="回货日期" width="116" /><ElTableColumn label="类型" width="105"><template #default="{ row }">{{ row.post_closure ? '结清后补回' : '正常回货' }}</template></ElTableColumn><ElTableColumn prop="good_pieces" label="合格支数" width="90" /><ElTableColumn prop="zone_name" label="半成品库区" min-width="120" /><ElTableColumn prop="received_by_employee_name" label="接收人" width="100" /><ElTableColumn prop="remark" label="备注" min-width="130" /></ElTable></section>
          </template>
          <ElEmpty v-else-if="!originalGoodLoading" description="暂无法登记，请关闭弹窗后重试" :image-size="64" />
        </div>
      </template><template v-else-if="dialog === 'rework'"><ElFormItem label="重新加工完成"><ElInput v-model="reworkForm.pieces" inputmode="numeric" /><small class="form-tip">不能超过本次未喷塑退回剩余支数。</small></ElFormItem><ElFormItem label="完成日期"><ElDatePicker v-model="reworkForm.date" type="date" value-format="YYYY-MM-DD" /></ElFormItem></template><template v-else-if="dialog === 'order'"><ElFormItem label="加工厂"><ElSelect v-model="orderForm.factoryId" filterable><ElOption v-for="row in orderFactories" :key="row.id" :value="row.id" :label="row.name" /></ElSelect></ElFormItem><ElFormItem label="喷塑工艺"><ElSelect v-model="orderForm.craftId" @change="orderForm.factoryId = orderFactories[0]?.id || ''"><ElOption v-for="row in sprayCrafts" :key="row.id" :value="row.id" :label="row.name" /></ElSelect></ElFormItem><ElFormItem label="新外发支数"><ElInput v-model="orderForm.pieces" inputmode="numeric" /></ElFormItem><ElFormItem label="加工单价"><ElInput v-model="orderForm.unitPrice" aria-label="重加工外发单价" inputmode="decimal"><template #suffix>元/支</template></ElInput></ElFormItem><ElFormItem label="计划加工金额"><span>{{ formatOutsourcingMoney(outsourcingLineAmount(orderForm.pieces, orderForm.unitPrice)) }} 元</span></ElFormItem></template><template v-else-if="dialog === 'new-handoff'"><ElFormItem label="实际交接支数"><ElInput v-model="newHandoffForm.pieces" inputmode="numeric" /></ElFormItem><ElFormItem label="交接日期"><ElDatePicker v-model="newHandoffForm.date" type="date" value-format="YYYY-MM-DD" /></ElFormItem></template><template v-else-if="dialog === 'new-return'"><ElFormItem label="合格回货支数"><ElInput v-model="newReturnForm.pieces" inputmode="numeric" /></ElFormItem><ElFormItem label="半成品库区"><ElSelect v-model="newReturnForm.zoneId"><ElOption v-for="row in options?.semi_finished_zones || []" :key="row.id" :value="row.id" :label="row.name" /></ElSelect></ElFormItem><ElFormItem label="接收人"><ElSelect v-model="newReturnForm.receiverId"><ElOption v-for="row in options?.receivers || []" :key="row.id" :value="row.id" :label="row.name" /></ElSelect></ElFormItem><ElFormItem label="回货日期"><ElDatePicker v-model="newReturnForm.date" type="date" value-format="YYYY-MM-DD" /></ElFormItem><ElFormItem label="备注" :required="selectedOrder?.status === 'CLOSED'"><ElInput v-model="newReturnForm.remark" type="textarea" /></ElFormItem></template><template v-else-if="dialog === 'close'"><ElFormItem label="结清备注"><ElInput v-model="closeForm.remark" type="textarea" :rows="5" placeholder="说明未回齐差额或结清原因" /></ElFormItem></template></ElForm><template #footer><ElButton :disabled="saving || uncertainOutcome" @click="resetDialog">取消</ElButton><ElButton v-if="showSubmit" data-testid="p4-dialog-submit" type="primary" :loading="saving" :disabled="submitDisabled" @click="submit">{{ submitLabel }}</ElButton></template></AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;

.p4-embedded { min-height:0; padding:0!important; background:transparent!important; }
.source-toolbar,.order-operation-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:16px; }
.source-toolbar>span { color:var(--erp-color-text-secondary); font-size:13px; }.source-status { width:100%; margin-bottom:14px; }
.order-operation-heading h2 { margin:0 0 6px; font-size:20px; }.order-operation-heading>div>span { font-size:13px; color:var(--erp-color-text-secondary); }
.unified-order-section { min-width:0; }.metric-grid.original-unified-metrics { grid-template-columns:repeat(5,minmax(0,1fr)); }.unified-record-card { padding:18px; margin:16px 0; min-width:0; }
.plan-quantity-review { margin-top:14px; border:1px solid var(--erp-color-border); border-radius:6px; background:var(--erp-color-subtle); }.plan-quantity-review summary { cursor:pointer; padding:12px 14px; font-size:13px; font-weight:600; }.plan-quantity-review summary span { margin-left:14px; color:var(--erp-color-text-secondary); font-weight:400; font-size:12px; }.plan-quantity-review[open] summary { border-bottom:1px solid var(--erp-color-border-subtle); }.related-source-title { margin-top:22px; }.source-handoff-row { display:flex; gap:16px; align-items:center; flex-wrap:wrap; border-top:1px solid var(--erp-color-border-subtle); padding:12px 0; font-size:13px; }.source-handoff-row>span:first-child { flex:1; min-width:220px; }
.rework-identity { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:20px; }.rework-identity span { display:block; color:var(--erp-color-text-secondary); font-size:12px; margin-bottom:7px; }.rework-identity strong { font-size:14px; }
.unified-record-card :deep(.el-table__cell) { padding:8px 0; }.unified-record-card :deep(.el-table th.el-table__cell) { height:44px; }.unified-record-card :deep(.el-tabs__item) { font-size:14px; }
@media (max-width:1200px) { .metric-grid.original-unified-metrics { grid-template-columns:repeat(3,minmax(0,1fr)); }.order-operation-heading { flex-wrap:wrap; }.rework-identity { grid-template-columns:repeat(2,minmax(0,1fr)); } }
.p4-page { min-height:100%; padding:24px 28px 36px; background:var(--erp-page-background); color:var(--erp-color-text-primary); }
.p4-heading { display:flex; justify-content:space-between; align-items:center; margin-bottom:18px; }.heading-title { display:flex; align-items:flex-start; gap:16px; }.heading-title h1 { margin:0; font-size:25px; }.heading-title p { margin:6px 0 0; color:var(--erp-color-text-secondary); }.heading-title .el-button { margin-top:2px; }
.p4-alert { margin-bottom:14px; }.p4-layout { display:grid; grid-template-columns:330px minmax(0,1fr); gap:16px; align-items:start; }.p4-panel { background:var(--erp-color-surface); border:1px solid var(--erp-color-border); border-radius:8px; box-shadow:0 5px 18px color-mix(in srgb, var(--erp-shadow-color) 5%, transparent); }.p4-source-panel { min-height:610px; padding:14px; }.p4-detail-panel { min-height:610px; padding:20px; }.panel-title,.section-title { display:flex; align-items:center; justify-content:space-between; gap:12px; }.panel-title strong { font-size:16px; }.panel-title span,.section-title span { color:var(--erp-color-text-secondary); font-size:12px; }.p4-search { margin:14px 0; }.source-list { display:flex; flex-direction:column; gap:8px; max-height:520px; overflow:auto; }.source-item { border:1px solid var(--erp-color-border); border-radius:6px; padding:11px 12px; background:var(--erp-color-surface); text-align:left; cursor:pointer; }.source-item:hover,.source-item.active { border-color:var(--erp-color-brand); background:var(--erp-color-selected); }.source-item div:first-child { display:flex; justify-content:space-between; gap:8px; }.source-item small { display:block; color:var(--erp-color-text-secondary); margin:5px 0 9px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }.source-item span,.source-progress { color:var(--erp-color-text-secondary); font-size:12px; }.source-progress { display:flex; justify-content:space-between; }.detail-top { display:flex; justify-content:space-between; align-items:flex-start; }.eyebrow { color:var(--erp-color-text-secondary); font-size:12px; }.detail-top h2 { margin:5px 0; font-size:22px; }.detail-top p { margin:0 0 18px; color:var(--erp-color-text-secondary); }.metric-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:18px; }.metric-grid div { border:1px solid var(--erp-color-border); border-radius:6px; padding:12px 14px; background:var(--erp-color-subtle); }.metric-grid span { display:block; color:var(--erp-color-text-secondary); font-size:12px; }.metric-grid strong { display:block; margin-top:6px; font-size:22px; }.metric-grid .accent { color:var(--erp-color-brand); }.flow-section { margin-top:18px; padding-top:16px; border-top:1px solid var(--erp-color-border-subtle); }.section-title { margin-bottom:10px; }.section-title h3 { margin:0; font-size:15px; }.nested-section { background:var(--erp-color-subtle); padding:14px; border:1px solid var(--erp-color-border); border-radius:6px; }.return-card { display:grid; grid-template-columns:1fr auto; gap:8px 16px; align-items:center; padding:10px 0; border-top:1px dashed var(--erp-color-border-subtle); }.return-card:first-of-type { border-top:0; }.return-card small { display:block; margin-top:4px; color:var(--erp-color-text-secondary); }.rework-line { grid-column:1 / -1; display:flex; justify-content:space-between; padding:8px 10px; background:var(--erp-color-subtle); color:var(--erp-color-text-regular); font-size:12px; }.done-text { color:var(--erp-color-success); font-size:12px; }.orders-panel,.stock-panel { margin-top:16px; padding:18px; }.orders-panel .panel-title>div,.stock-panel .panel-title>div { display:flex; align-items:baseline; gap:14px; }.p4-form { padding:8px 12px; }.p4-form .el-select,.p4-form .el-input,.p4-form .el-date-editor { width:100%; }.form-tip { display:block; color:var(--erp-color-text-secondary); margin-top:5px; }
.original-good-dialog { min-height:220px; }.original-good-identity { display:grid; grid-template-columns:1fr 1fr; gap:16px; padding:12px 14px; background:var(--erp-color-subtle); border:1px solid var(--erp-color-border); border-radius:6px; }.original-good-identity span { display:block; color:var(--erp-color-text-secondary); font-size:12px; margin-bottom:6px; }.original-good-identity strong { font-size:14px; }.original-good-note { margin:10px 0 14px; color:var(--erp-color-text-secondary); font-size:12px; line-height:1.6; }.original-good-summary { margin:0 0 18px; }.original-good-summary div { padding:10px 12px; }.original-good-summary strong { font-size:21px; }.original-good-summary small { font-size:12px; font-weight:400; }.original-good-fields { display:grid; grid-template-columns:1fr 1fr; gap:0 16px; }.original-good-preview { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; padding:13px 16px; background:var(--erp-color-success-soft); border:1px solid var(--erp-color-success-border); border-radius:6px; }.original-good-preview span { display:block; font-size:12px; color:var(--erp-color-text-secondary); }.original-good-preview strong { display:block; margin-top:6px; color:var(--erp-color-success); font-size:17px; }.original-good-history { margin-top:16px; }.original-good-dialog .original-good-summary { grid-template-columns:repeat(4,1fr); }
.source-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; align-items:center; gap:8px; max-width:470px; }.source-actions .el-button { margin:0; }.source-metrics { grid-template-columns:repeat(5,minmax(0,1fr)); }.source-closure-record { margin-top:12px; padding:14px; background:var(--erp-color-subtle); border:1px solid var(--erp-color-border); border-radius:6px; font-size:13px; line-height:1.6; }.source-closure-record p { margin:6px 0; }.source-closure-record small { color:var(--erp-color-text-secondary); }.preserve-lines { white-space:pre-wrap; overflow-wrap:anywhere; }.source-operation-dialog,.allocation-dialog { min-height:220px; }.source-operation-dialog .metric-grid,.allocation-dialog .metric-grid { margin-top:18px; }.source-operation-dialog .two-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }.source-operation-dialog .source-metrics strong { font-size:20px; }.source-operation-dialog .source-metrics div { padding:12px 10px; }.source-close-difference { display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:12px 14px; margin-bottom:18px; background:var(--erp-color-warning-soft); border:1px solid var(--erp-color-warning-border); border-radius:5px; color:var(--erp-color-warning); }.source-close-difference span { margin-left:12px; }.source-close-difference small { margin-left:auto; }.operation-note { margin:16px 0; padding:10px 12px; border-left:3px solid var(--erp-color-success-border); background:var(--erp-color-success-soft); font-size:12px; line-height:1.8; color:var(--erp-color-success); }.allocation-metrics { grid-template-columns:repeat(3,minmax(0,1fr)); }.allocation-history { padding:14px 24px; }.allocation-dialog .form-tip { width:100%; }.allocation-dialog :deep(.el-form-item__label) { white-space:nowrap; }.source-operation-dialog :deep(.el-textarea__inner) { padding-bottom:26px; }
.original-order-dialog { min-height:240px; }.original-order-heading { display:flex; align-items:center; justify-content:space-between; padding:12px 14px; margin-bottom:14px; background:var(--erp-color-subtle); border:1px solid var(--erp-color-border); border-radius:6px; }.original-order-heading span { font-size:12px; color:var(--erp-color-text-secondary); }.original-order-heading h3 { margin:5px 0 0; font-size:19px; }.part-subtitle { display:block; color:var(--erp-color-text-secondary); line-height:1.5; margin-top:3px; }.original-close-field { margin-top:18px; }.closure-snapshot-section,.compact-closure { margin:14px 0; padding:12px 14px; border:1px solid var(--erp-color-border); border-radius:6px; background:var(--erp-color-subtle); }.closure-snapshot-section p,.compact-closure p { margin:7px 0; font-size:12px; line-height:1.6; overflow-wrap:anywhere; }.compact-closure strong { font-size:13px; }.compact-closure small { font-size:12px; color:var(--erp-color-text-secondary); }.original-return-dialog { min-height:220px; }.return-fields,.pending-cancel-summary { margin-top:18px; }.original-order-dialog :deep(.el-textarea__inner),[data-testid="original-cancel-pending-dialog"] :deep(.el-textarea__inner) { padding-bottom:26px; }
@media (max-width:1200px) { .p4-layout { grid-template-columns:260px minmax(0,1fr); }.metric-grid { grid-template-columns:repeat(2,1fr); } }
@media (max-width:1400px) { .detail-top { flex-wrap:wrap; }.source-actions { justify-content:flex-start; max-width:none; margin-bottom:16px; }.source-metrics { grid-template-columns:repeat(5,minmax(0,1fr)); }.source-metrics div { padding:10px 8px; }.source-metrics strong { font-size:20px; } }
@media (max-width:640px) { .metric-grid.original-unified-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }.original-good-fields,.original-good-identity { grid-template-columns:1fr; }.source-operation-dialog .source-metrics { grid-template-columns:repeat(3,minmax(0,1fr)); }.source-close-difference span { margin-left:0; }.source-close-difference small { margin-left:0; } }

// 普通外发内嵌与返工详情使用玻璃；独立加工工作区维持原布局。
.p4-page.p4-detail-surface {
  min-width: 0;
  min-height: 0;
  background: transparent;
  .p4-panel { @include detail.surface; }
  .p4-panel .p4-panel,
  .metric-grid > div,
  .nested-section,
  .plan-quantity-review,
  .source-closure-record,
  .closure-snapshot-section,
  .compact-closure { @include detail.inset; }
  .unified-record-card { margin-block: 14px; }
  .p4-layout { gap: 14px; }
  .order-operation-heading, .detail-top { flex-wrap: wrap; gap: 14px; }
}
.p4-detail-dialog {
  .original-order-heading,
  .original-good-identity,
  .closure-snapshot-section,
  .compact-closure,
  .metric-grid > div { @include detail.inset; }
}
@media (max-width: 900px) {
  .p4-page.p4-detail-surface {
    .p4-layout { grid-template-columns: minmax(0, 1fr); }
    .p4-source-panel, .p4-detail-panel { min-height: 0; }
    .source-metrics, .metric-grid.original-unified-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .section-title, .panel-title { flex-wrap: wrap; }
  }
}
</style>
