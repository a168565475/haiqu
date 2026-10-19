<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { isAxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { createTubeOrder, fetchTubeOptions, fetchTubeSource, findTubeOrder } from '@/api/tubeOutsourcing'
import { useAuthStore } from '@/stores/auth'
import type { TubeOptions, TubeOrderInput, TubeOrderResult, TubeSourceContext, TubeSourceKind, TubeSourceRow } from '@/types/tubeOutsourcing'
import { tubeMeters, tubeQuantityError, tubeRoots, wholeTubeQuantity } from '@/utils/tubeOutsourcing'
import '@/styles/tubeOutsourcing.scss'

interface Entry extends TubeSourceRow { quantity: string; factoryId: string }
interface Column { key: string; label: string; width: number; num?: boolean }
type ChangeKind = 'task' | 'product' | 'source' | 'warehouse' | 'zone'

const auth = useAuthStore(), router = useRouter(), route = useRoute()
const options = ref<TubeOptions | null>(null), context = ref<TubeSourceContext | null>(null)
const taskId = ref(''), productId = ref(''), source = ref<TubeSourceKind>('RAW_PIPE')
const warehouseId = ref(''), zoneId = ref(''), rows = ref<Entry[]>([])
const today = new Date()
const sendDate = ref(`${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`)
const returnDate = ref(''), remark = ref('')
const loading = ref(false), sourceLoading = ref(false), saving = ref(false), error = ref('')
const sourceHint = ref('')
const dialog = ref<'' | 'change' | 'confirm'>('')
const pendingChange = ref<{ kind: ChangeKind; value: string } | null>(null)
const pending = ref<TubeOrderInput | null>(null), storageError = ref(false)
const pendingKey = `tube-outsourcing-pending:v1:${auth.user?.id || 'unknown'}`
let sourceRequest = 0
let disposed = false

const labels: Record<TubeSourceKind, string> = { RAW_PIPE: '原材料', PUBLIC_SEMI: '未喷塑半成品', METAL: '未入库半成品' }
const task = computed(() => options.value?.tasks.find(item => item.id === taskId.value))
const products = computed(() => task.value?.products || [])
const product = computed(() => products.value.find(item => item.id === productId.value))
const factories = computed(() => context.value?.factories || options.value?.factories || [])
const eligibleZones = computed(() => (options.value?.zones || []).filter(item => item.warehouse_type === (source.value === 'PUBLIC_SEMI' ? 'SEMI_FINISHED' : 'MATERIAL')))
const warehouses = computed(() => [...new Map(eligibleZones.value.map(item => [item.warehouse_id, { id: item.warehouse_id, name: item.warehouse_name }])).values()])
const zones = computed(() => eligibleZones.value.filter(item => item.warehouse_id === warehouseId.value))
const canCreate = computed(() => Boolean(auth.user?.is_superuser || auth.hasPermission('outsourcing.add_outsourcingorder')))
const locked = computed(() => loading.value || sourceLoading.value || saving.value || Boolean(pending.value) || storageError.value)
const entered = computed(() => rows.value.filter(row => (wholeTubeQuantity(row.quantity) || 0) > 0))
const total = computed(() => entered.value.reduce((sum, row) => sum + (wholeTubeQuantity(row.quantity) || 0), 0))
const factoryCount = computed(() => new Set(entered.value.map(row => row.factoryId).filter(Boolean)).size)
const emptyMessage = computed(() => {
  if (loading.value || sourceLoading.value) return '正在加载管材及额度…'
  if (error.value) return error.value
  if (!taskId.value) return '请先选择生产任务单，再选择产品'
  if (!productId.value) return '请选择本次外发的一个产品'
  if (source.value !== 'METAL' && !zoneId.value) return '请选择来源仓库和库区'
  return context.value?.blockers.join('；') || '该产品暂无可外发的管材部位'
})
const columns = computed<Column[]>(() => [
  { key: 'part_name', label: '部位', width: 85 }, { key: 'material', label: '材质', width: 58 },
  { key: 'specification', label: '规格', width: 104 }, { key: 'thickness', label: '厚度 mm', width: 72 },
  { key: 'cutting_length_mm', label: '切割长度 mm', width: 96 }, { key: 'raw_color', label: '原料颜色', width: 83 },
  { key: 'order_required', label: '订单需求（支）', width: 102, num: true },
  ...(source.value === 'METAL' ? [] : [{ key: 'stock_quantity', label: source.value === 'RAW_PIPE' ? '库存（根）' : '库存（支）', width: 85, num: true }]),
  { key: 'max_quantity', label: '最多可发（支）', width: 108, num: true },
  ...(source.value === 'RAW_PIPE' ? [{ key: 'pieces_per_bar', label: '每根切割（支）', width: 104, num: true }, { key: 'raw_bar_length_m', label: '原材长度（米）', width: 108, num: true }] : []),
  { key: 'quantity', label: '本次外发（支）', width: 124 },
  ...(source.value === 'RAW_PIPE' ? [{ key: 'roots', label: '扣除（根）', width: 82, num: true }, { key: 'meters', label: '扣除（米）', width: 99, num: true }] : []),
  { key: 'factory', label: '加工厂', width: 160 }, { key: 'spray_color', label: '喷塑颜色', width: 85 },
])
const tableWidth = computed(() => columns.value.reduce((sum, column) => sum + column.width, 0))
const number = (value: unknown) => value === null || value === undefined || value === '' ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
const warn = (message: string) => ElMessage.warning({ message, grouping: true, duration: 4000 })
const factoryName = (id: string) => factories.value.find(item => item.id === id)?.name || '—'
const rowDisabled = (row: Entry) => locked.value || !canCreate.value || !context.value?.ready || !(wholeTubeQuantity(row.max_quantity) || 0) || row.blockers.length > 0
function cellText(row: Entry, key: string): string {
  if (key === 'raw_bar_length_m') return row.raw_bar_length_m === null ? '—' : Number(row.raw_bar_length_m).toFixed(2)
  if (['order_required', 'stock_quantity', 'pieces_per_bar'].includes(key)) return number(row[key as keyof Entry])
  return String(row[key as keyof Entry] ?? '—')
}
function errorText(cause: unknown, fallback: string): string {
  if (!isAxiosError(cause)) return cause instanceof Error ? cause.message : fallback
  const body = cause.response?.data as { error?: { message?: string }; detail?: string } | undefined
  return body?.error?.message || body?.detail || fallback
}
function selectDefaultZone() {
  const selectedZone = eligibleZones.value.find(item => item.id === zoneId.value)
  if (selectedZone) warehouseId.value = selectedZone.warehouse_id
  if (!warehouses.value.some(item => item.id === warehouseId.value)) warehouseId.value = warehouses.value[0]?.id || ''
  if (!zones.value.some(item => item.id === zoneId.value)) zoneId.value = zones.value[0]?.id || ''
}
function hasAvailableQuantity(value: TubeSourceContext): boolean {
  return value.rows.some(row => (wholeTubeQuantity(row.max_quantity) || 0) > 0)
}
function sourceZoneCandidates(): string[] {
  if (source.value !== 'PUBLIC_SEMI') return zoneId.value ? [zoneId.value] : []
  const zoneIds = eligibleZones.value.map(item => item.id)
  const preferred = zoneIds.includes(zoneId.value) ? [zoneId.value] : []
  return [...new Set([...preferred, ...zoneIds])]
}
function clearRows() { rows.value.forEach(row => { row.quantity = ''; row.factoryId = '' }) }

async function loadSource(preserve = true) {
  const request = ++sourceRequest
  const scheduleId = product.value?.schedule_product_id
  if (!scheduleId || (source.value !== 'METAL' && !zoneId.value)) {
    context.value = null; rows.value = []; sourceHint.value = ''; sourceLoading.value = false
    return
  }
  sourceLoading.value = true; error.value = ''
  const previous = new Map(rows.value.map(row => [row.component_identity, row]))
  try {
    const candidates = sourceZoneCandidates()
    let selected: { zoneId: string; result: TubeSourceContext } | null = null
    let firstResult: { zoneId: string; result: TubeSourceContext } | null = null
    let lastCause: unknown = null
    for (const candidate of candidates) {
      if (request !== sourceRequest || disposed) return
      try {
        const result = await fetchTubeSource({ schedule_product_id: scheduleId, source_kind: source.value, ...(source.value === 'METAL' ? {} : { zone_id: candidate }) })
        firstResult ||= { zoneId: candidate, result }
        if (source.value !== 'PUBLIC_SEMI' || hasAvailableQuantity(result)) {
          selected = { zoneId: candidate, result }
          break
        }
      } catch (cause) {
        lastCause = cause
      }
    }
    if (!selected) selected = firstResult
    if (!selected) throw lastCause || new Error('未找到可用来源库区。')
    if (request !== sourceRequest || disposed) return
    if (source.value !== 'METAL' && selected.zoneId !== zoneId.value) {
      zoneId.value = selected.zoneId
      warehouseId.value = eligibleZones.value.find(item => item.id === selected!.zoneId)?.warehouse_id || ''
    }
    context.value = selected.result
    sourceHint.value = source.value === 'PUBLIC_SEMI' && !hasAvailableQuantity(selected.result)
      ? '当前半成品库各库区可用数量均为 0 支，请确认半成品已入库到正确库区。'
      : ''
    rows.value = selected.result.rows.map(row => ({ ...row, quantity: preserve ? previous.get(row.component_identity)?.quantity || '' : '', factoryId: preserve ? previous.get(row.component_identity)?.factoryId || '' : '' }))
  } catch (cause) {
    if (request !== sourceRequest || disposed) return
    context.value = null; sourceHint.value = ''
    error.value = errorText(cause, '管材及额度加载失败，请重新加载。')
  } finally { if (request === sourceRequest && !disposed) sourceLoading.value = false }
}
async function applyChange() {
  const change = pendingChange.value
  if (!change || locked.value) return
  dialog.value = ''; pendingChange.value = null
  if (change.kind === 'task') { taskId.value = change.value; productId.value = '' }
  if (change.kind === 'product') productId.value = change.value
  if (change.kind === 'source') { source.value = change.value as TubeSourceKind; warehouseId.value = ''; zoneId.value = ''; selectDefaultZone() }
  if (change.kind === 'warehouse') { warehouseId.value = change.value; zoneId.value = zones.value[0]?.id || '' }
  if (change.kind === 'zone') zoneId.value = change.value
  rows.value = []; context.value = null
  await loadSource(false)
}
function requestChange(kind: ChangeKind, raw: unknown) {
  if (locked.value) return
  const value = typeof raw === 'string' ? raw : ''
  const current = { task: taskId.value, product: productId.value, source: source.value, warehouse: warehouseId.value, zone: zoneId.value }
  if (current[kind] === value) return
  pendingChange.value = { kind, value }
  if (rows.value.some(row => row.quantity.trim() !== '' || row.factoryId)) dialog.value = 'change'
  else void applyChange()
}
function validate(): boolean {
  if (!canCreate.value) { warn('当前账号没有新建外发单权限。'); return false }
  if (!context.value?.ready || !product.value) { warn(context.value?.blockers.join('；') || emptyMessage.value); return false }
  if (!sendDate.value || !returnDate.value) { warn('请填写计划发出日期和预计回货日期。'); return false }
  if (returnDate.value < sendDate.value) { warn('预计回货日期不能早于计划发出日期。'); return false }
  if (source.value !== 'METAL' && (!warehouseId.value || !zoneId.value)) { warn('请选择来源仓库和库区。'); return false }
  for (const row of rows.value) {
    const issue = tubeQuantityError(row.quantity, row, source.value === 'RAW_PIPE')
    if (issue) { warn(issue); return false }
    if ((wholeTubeQuantity(row.quantity) || 0) > 0 && !factories.value.some(factory => factory.id === row.factoryId)) { warn(`${row.part_name}：请选择一家加工厂。`); return false }
  }
  if (!entered.value.length) { warn('请至少填写一项大于0的外发数量。'); return false }
  return true
}
function checkDispatch() { if (!locked.value && validate()) dialog.value = 'confirm' }
function clearPending() {
  pending.value = null
  try { localStorage.removeItem(pendingKey) } catch { storageError.value = true; warn('单据状态已确认，但本地请求记录未能清理。请恢复浏览器存储后刷新页面。') }
}
async function saved(result: TubeOrderResult) {
  if (!result.id || !result.order_number || result.client_request_id !== pending.value?.client_request_id) throw new Error('保存结果不完整，请核对本次提交。')
  clearPending(); dialog.value = ''; clearRows()
  ElMessage.success({ message: `已保存外发单 ${result.order_number}，数量已预留。`, duration: 6000 })
  if (!storageError.value) await router.push({ name: 'workshop-outsourcing-tube-detail', params: { id: result.id } })
}
async function postPending() {
  if (!pending.value) return
  try { await saved(await createTubeOrder(pending.value)) }
  catch (cause) {
    const status = isAxiosError(cause) ? cause.response?.status : undefined
    if (status && [400, 403, 404, 412, 428].includes(status)) {
      clearPending(); dialog.value = ''
      const needsRefresh = status === 412 || status === 428
      if (needsRefresh) await loadSource(true)
      const message = errorText(cause, '未能保存，请检查填写内容。')
        + (needsRefresh ? context.value ? ' 已刷新额度，请重新核对后保存。' : ' 请刷新额度后重新核对。' : '')
      if (status === 403 || status === 404) error.value = message
      warn(message)
      return
    }
    // 超时不能视为失败：先按原编号查询，期间禁止修改及生成新请求。
    await recoverPending(false)
  }
}
async function recoverPending(allowRetry: boolean) {
  if (!pending.value) return
  try { await saved(await findTubeOrder(pending.value.client_request_id)) }
  catch (cause) {
    if (isAxiosError(cause) && cause.response?.status === 404 && allowRetry) {
      await postPending()
      return
    }
    error.value = '提交结果尚未确认，填写内容已锁定。请点击“核对本次提交”，继续使用原请求编号核对，避免重复建单。'
    warn(error.value)
  }
}
async function save() {
  if (saving.value || storageError.value) return
  if (!pending.value) {
    if (!validate() || !context.value || !product.value) return
    try {
      if (localStorage.getItem(pendingKey)) { warn('另一个页面有待核对的提交，请刷新本页核对后再新建。'); return }
    } catch { warn('浏览器无法读取待核对请求，本次尚未提交。请允许本站本地存储后重试。'); return }
    const payload: TubeOrderInput = {
      client_request_id: crypto.randomUUID(), source_revision: context.value.source_revision,
      schedule_product_id: product.value.schedule_product_id, source_kind: source.value,
      zone_id: source.value === 'METAL' ? null : zoneId.value,
      planned_dispatch_date: sendDate.value, expected_return_date: returnDate.value, remark: remark.value.trim(),
      lines: entered.value.map(row => ({ component_identity: row.component_identity, quantity: String(wholeTubeQuantity(row.quantity)), factory_id: row.factoryId })),
    }
    try { localStorage.setItem(pendingKey, JSON.stringify(payload)) }
    catch { warn('浏览器无法保存请求编号，本次尚未提交。请允许本站本地存储后重试。'); return }
    pending.value = payload
    saving.value = true; error.value = ''
    try { await postPending() } finally { saving.value = false }
  } else {
    saving.value = true; error.value = ''
    try { await recoverPending(true) } finally { saving.value = false }
  }
}
async function initialize() {
  loading.value = true; error.value = ''
  try {
    options.value = await fetchTubeOptions()
    if (!pending.value && typeof route.query.source_kind === 'string' && ['RAW_PIPE', 'PUBLIC_SEMI', 'METAL'].includes(route.query.source_kind)) source.value = route.query.source_kind as TubeSourceKind
    if (!pending.value && typeof route.query.zone_id === 'string') zoneId.value = route.query.zone_id
    if (!pending.value && !options.value.source_kinds.some(item => item.value === source.value)) source.value = options.value.source_kinds[0]?.value || 'RAW_PIPE'
    const scheduleId = pending.value?.schedule_product_id || (typeof route.query.schedule_product_id === 'string' ? route.query.schedule_product_id : '')
    for (const item of options.value.tasks) {
      const found = item.products.find(candidate => candidate.schedule_product_id === scheduleId)
      if (found) { taskId.value = item.id; productId.value = found.id; break }
    }
    selectDefaultZone()
    await loadSource(false)
    if (pending.value) {
      for (const row of rows.value) {
        const line = pending.value.lines.find(item => item.component_identity === row.component_identity)
        if (line) { row.quantity = line.quantity; row.factoryId = line.factory_id }
      }
    }
  } catch (cause) { error.value = errorText(cause, '外发基础选项加载失败，请重新加载。') }
  finally { loading.value = false }
}
onMounted(async () => {
  try {
    const raw = localStorage.getItem(pendingKey)
    if (raw) {
      const value = JSON.parse(raw) as TubeOrderInput
      const textFields = [value?.client_request_id, value?.source_revision, value?.schedule_product_id, value?.planned_dispatch_date, value?.expected_return_date]
      if (!textFields.every(item => typeof item === 'string' && item.length > 0)
        || typeof value?.remark !== 'string'
        || (value.zone_id !== null && typeof value.zone_id !== 'string')
        || !Array.isArray(value.lines) || !value.lines.length
        || !value.lines.every(line => line && typeof line.component_identity === 'string' && typeof line.factory_id === 'string' && typeof line.quantity === 'string' && (wholeTubeQuantity(line.quantity) || 0) > 0)
        || !['METAL', 'PUBLIC_SEMI', 'RAW_PIPE'].includes(value.source_kind)) throw new Error('记录不完整')
      pending.value = value; source.value = value.source_kind; zoneId.value = value.zone_id || ''
      sendDate.value = value.planned_dispatch_date; returnDate.value = value.expected_return_date; remark.value = value.remark
    }
  } catch { storageError.value = true; error.value = '本地待核对请求记录无法读取，已暂停新建。请先确认之前的提交结果。'; return }
  await initialize()
  if (pending.value) { saving.value = true; try { await recoverPending(false) } finally { saving.value = false } }
})
onBeforeUnmount(() => { disposed = true; sourceRequest += 1 })
</script>

<template>
  <section class="tube-outsourcing-page erp-glass-form">
    <header class="page-heading"><div class="title-row"><h1>新建管材外发单</h1><span class="status">{{ labels[source] }}</span></div><span class="muted">一个产品 · 每个部位一家加工厂</span></header>
    <ElAlert v-if="!canCreate" title="当前账号没有新建外发单权限。" type="warning" :closable="false" show-icon />
    <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon><ElButton v-if="!pending && !storageError" link @click="initialize">重新加载</ElButton></ElAlert>
    <section class="panel">
      <div class="field-grid">
        <label class="form-field required"><span>生产任务单</span><ElSelect :model-value="taskId" :disabled="locked || !canCreate" :loading="loading" @update:model-value="requestChange('task', $event)" filterable clearable aria-label="生产任务单" placeholder="先选择生产任务单" no-data-text="暂无可用喷塑排产任务"><ElOption v-for="item in options?.tasks || []" :key="item.id" :label="item.task_number" :value="item.id" /></ElSelect></label>
        <label class="form-field required"><span>产品</span><ElSelect :model-value="productId" @update:model-value="requestChange('product', $event)" :disabled="!taskId || locked || !canCreate" filterable clearable aria-label="产品" placeholder="再选择一个产品"><ElOption v-for="item in products" :key="item.id" :label="`${item.product_number} · ${item.product_name}`" :value="item.id" /></ElSelect></label>
        <label class="form-field required"><span>材料来源</span><ElSelect :model-value="source" :disabled="locked || !canCreate" @update:model-value="requestChange('source', $event)" aria-label="材料来源"><ElOption v-for="item in options?.source_kinds || []" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></label>
        <label class="form-field"><span>关联排产</span><ElInput :model-value="product ? product.schedule_number || '暂无可用排产' : '选择产品后自动关联'" readonly /></label>
        <label class="form-field required"><span>计划发出日期</span><ElDatePicker v-model="sendDate" :disabled="locked || !canCreate" aria-label="计划发出日期" type="date" format="YYYY-MM-DD" value-format="YYYY-MM-DD" placeholder="选择日期" /></label>
        <label class="form-field required"><span>预计回货日期</span><ElDatePicker v-model="returnDate" :disabled="locked || !canCreate" aria-label="预计回货日期" type="date" format="YYYY-MM-DD" value-format="YYYY-MM-DD" placeholder="选择日期" /></label>
        <template v-if="source !== 'METAL'">
          <label class="form-field required"><span>来源仓库</span><ElSelect :model-value="warehouseId" :disabled="locked || !canCreate" @update:model-value="requestChange('warehouse', $event)" aria-label="来源仓库" placeholder="选择来源仓库"><ElOption v-for="item in warehouses" :key="item.id" :label="item.name" :value="item.id" /></ElSelect></label>
          <label class="form-field required"><span>库区</span><ElSelect :model-value="zoneId" :disabled="locked || !canCreate" @update:model-value="requestChange('zone', $event)" aria-label="库区" placeholder="选择库区"><ElOption v-for="item in zones" :key="item.id" :label="item.name" :value="item.id" /></ElSelect></label>
        </template>
        <template v-else><label class="form-field"><span>金工来源计划</span><ElInput :model-value="product?.schedule_number || '—'" readonly /></label><label class="form-field"><span>数量单位</span><ElInput model-value="已加工短管 · 支" disabled /></label></template>
      </div>
      <div class="dispatch-context info-grid"><div class="info-cell"><span>订单号</span><b>{{ context?.order_number || task?.order_number || '—' }}</b></div><div class="info-cell"><span>品号</span><b>{{ product?.product_number || '—' }}</b></div><div class="info-cell"><span>货号</span><b>{{ product?.item_number || '—' }}</b></div><div class="info-cell"><span>订单量</span><b>{{ product ? `${number(product.quantity)} ${product.unit}` : '—' }}</b></div><div class="info-cell"><span>外发工艺</span><b>{{ context?.craft_name || '喷塑' }}</b></div></div>
    </section>
    <section class="panel workspace" v-loading="sourceLoading">
      <div class="section-heading"><div><h2>外发管材</h2><span class="muted">按产品BOM带出部位，填写数量并选择一家加工厂；空白或0不外发</span></div><ElButton :icon="Refresh" :disabled="locked || !product" @click="loadSource(true)">刷新额度</ElButton></div>
      <div v-if="context?.blockers.length" class="notice warning">{{ context.blockers.join('；') }}</div>
      <div v-if="sourceHint" class="notice warning">{{ sourceHint }}</div>
      <div class="tube-table-wrap"><table class="erp-table-editor tube-table" :style="{ minWidth: `${tableWidth}px` }"><colgroup><col v-for="column in columns" :key="column.key" :style="{ width: `${column.width}px` }" /></colgroup><thead><tr><th v-for="column in columns" :key="column.key" :class="{ num: column.num }">{{ column.label }}</th></tr></thead><tbody>
        <tr v-for="row in rows" :key="row.component_identity"><td v-for="column in columns" :key="column.key" :class="{ num: column.num }" :title="column.key === 'max_quantity' && row.blockers.length ? row.blockers.join('；') : undefined">
          <ElInput v-if="column.key === 'quantity'" v-model="row.quantity" :aria-label="`${row.part_name}外发支数`" inputmode="numeric" :disabled="rowDisabled(row)" :placeholder="Number(row.max_quantity) ? '0' : '暂无可发'"><template v-if="Number(row.max_quantity)" #suffix>支</template></ElInput>
          <ElSelect v-else-if="column.key === 'factory'" v-model="row.factoryId" :aria-label="`${row.part_name}加工厂`" :disabled="rowDisabled(row)" filterable clearable placeholder="选择加工厂"><ElOption v-for="factory in factories" :key="factory.id" :label="factory.name" :value="factory.id" /></ElSelect>
          <b v-else-if="column.key === 'max_quantity'" :class="Number(row.max_quantity) ? 'brand' : 'muted'">{{ number(row.max_quantity) }}</b>
          <b v-else-if="column.key === 'roots'" :class="tubeRoots(row.quantity, row.pieces_per_bar) === null ? 'brand' : ''">{{ tubeRoots(row.quantity, row.pieces_per_bar) === null ? '须整根' : number(tubeRoots(row.quantity, row.pieces_per_bar)) }}</b>
          <template v-else-if="column.key === 'meters'">{{ tubeMeters(row.quantity, row) ?? '—' }}</template>
          <span v-else class="cell-text" :title="cellText(row, column.key)">{{ cellText(row, column.key) }}</span>
        </td></tr><tr v-if="!rows.length"><td :colspan="columns.length" class="empty-cell">{{ emptyMessage }}</td></tr>
      </tbody></table></div>
      <label class="form-field"><span>外发备注 <span class="muted">选填</span></span><ElInput v-model="remark" :disabled="locked || !canCreate" type="textarea" :rows="2" :maxlength="2000" placeholder="填写加工、交接或送货说明" /></label>
    </section>
    <footer class="footer-bar"><div>本单计划外发 <strong>{{ number(total) }}</strong> 支<small>保存后预留数量，实物尚未发出；确认发出时才交接或扣库。</small></div><ElButton :disabled="saving" @click="router.push({ name: 'workshop-outsourcing' })">返回</ElButton><ElButton :disabled="locked" @click="clearRows">重填</ElButton><ElButton type="primary" :loading="saving" :disabled="storageError || (!pending && (locked || !canCreate))" @click="pending ? save() : checkDispatch()">{{ pending ? '核对本次提交' : '保存外发单' }}</ElButton></footer>
  </section>
  <AppWindowDialog :model-value="dialog === 'change'" @update:model-value="dialog = ''; pendingChange = null" modal-class="tube-outsourcing-dialog" title="更换来源信息" :width="700"><p>更换后将清空当前填写的外发数量和加工厂，并重新核对管材及额度。</p><p>更换生产任务单还需要重新选择产品。本次尚未保存，不会改变库存。</p><template #footer><ElButton @click="dialog = ''; pendingChange = null">保留当前填写</ElButton><ElButton type="primary" @click="applyChange">确认更换</ElButton></template></AppWindowDialog>
  <AppWindowDialog :model-value="dialog === 'confirm'" @update:model-value="dialog = ''" modal-class="tube-outsourcing-dialog" title="核对并保存管材外发单" :width="1050" :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving"><div class="info-grid"><div class="info-cell"><span>生产任务单</span><b>{{ task?.task_number }}</b></div><div class="info-cell"><span>产品</span><b>{{ product?.product_name }}</b></div><div class="info-cell"><span>材料来源</span><b>{{ labels[source] }}</b></div></div>
    <div class="tube-table-wrap"><table class="tube-table confirm-table"><colgroup><col style="width:160px" /><col style="width:200px" /><col style="width:160px" /><template v-if="source === 'RAW_PIPE'"><col style="width:150px" /><col style="width:170px" /></template></colgroup><thead><tr><th>部位</th><th>加工厂</th><th class="num">本次外发（支）</th><template v-if="source === 'RAW_PIPE'"><th class="num">扣除（根）</th><th class="num">扣除（米）</th></template></tr></thead><tbody><tr v-for="row in entered" :key="row.component_identity"><td>{{ row.part_name }}</td><td>{{ factoryName(row.factoryId) }}</td><td class="num">{{ number(row.quantity) }}</td><template v-if="source === 'RAW_PIPE'"><td class="num">{{ number(tubeRoots(row.quantity, row.pieces_per_bar)) }}</td><td class="num">{{ tubeMeters(row.quantity, row) }}</td></template></tr></tbody></table></div>
    <p>本次 {{ entered.length }} 个部位、{{ factoryCount }} 家加工厂，共 <b>{{ number(total) }} 支</b>。每个部位只对应一家加工厂。</p><div class="notice">保存后预留上述数量，实物尚未发出；请在外发单详情确认发出。<br />本单所有部位、所有厂家须统一一次登记回货并结束。</div><template #footer><ElButton :disabled="saving" @click="dialog = ''">返回检查</ElButton><ElButton type="primary" :loading="saving" @click="save">{{ pending ? '核对本次提交' : '确认保存' }}</ElButton></template>
  </AppWindowDialog>
</template>
