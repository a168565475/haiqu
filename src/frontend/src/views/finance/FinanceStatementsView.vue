<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { DropdownInstance } from 'element-plus'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import FinanceStatementSourceDialog from './FinanceStatementSourceDialog.vue'
import FinanceStatementReceipts from './FinanceStatementReceipts.vue'
import { useAuthStore } from '@/stores/auth'
import { createFinanceStatement, deleteFinanceStatement, fetchFinanceSourceProducts, fetchFinanceStatement, fetchFinanceStatements, updateFinanceStatement, voidFinanceStatement } from '@/api/financeStatements'
import type { FinanceSourcePage, FinanceSourceProduct, FinanceSourceTask, FinanceStatement, FinanceStatementInput, FinanceStatementQuery } from '@/types/financeStatements'
import { displayCents, previewLineAmount } from './statementAmounts'

const auth = useAuthStore()
const can = (action: string) => auth.user?.is_superuser === true || auth.hasPermission(`finance.${action}_receivablestatement`)
const rows = ref<FinanceStatement[]>([]), total = ref(0), page = ref(1)
const search = ref(''), status = ref<'' | 'ACTIVE' | 'VOID'>(''), settlement = ref<'' | 'UNSETTLED' | 'PARTIAL' | 'SETTLED'>('')
const applied = reactive({ q: '', status: status.value, settlement_status: settlement.value })
const loading = ref(false), loaded = ref(false), forbidden = ref(false), listError = ref('')
const dialog = ref(false), mode = ref<'create' | 'edit' | 'detail'>('create'), detailLoading = ref(false)
const record = ref<FinanceStatement>(), latest = ref<FinanceStatement>(), task = ref<FinanceSourceTask>()
const selected = ref<FinanceSourceProduct[]>([]), prices = ref<Record<string, string>>({}), revision = ref(''), acknowledged = ref(false)
const customPriceIds = ref(new Set<string>())
const salespersonChanges = ref<FinanceSourcePage['salesperson_changes']>([])
const formError = ref(''), fieldErrors = ref<Record<string, string>>({}), conflict = ref(false), submitting = ref(false), uncertain = ref(false)
const original = ref(''), sourceOpen = ref(false)
const products = ref<FinanceSourceProduct[]>([]), productPage = ref(1), productTotal = ref(0)
const productLoading = ref(false), productLoaded = ref(false), productError = ref(''), sourceChanged = ref(false)
const voidOpen = ref(false), voidRecord = ref<FinanceStatement>(), voidReason = ref(''), voidError = ref(''), voidBusy = ref(false)
const deleting = ref('')
const receiptSection = ref<InstanceType<typeof FinanceStatementReceipts>>()
const draftSnapshot = () => JSON.stringify({ task: task.value?.id, selected: selected.value.map(row => [row.id, prices.value[row.id]]), revision: revision.value, acknowledged: acknowledged.value })
const selectedIds = computed(() => new Set(selected.value.map(row => row.id)))
const invalidSelected = computed(() => selected.value.filter(row => !row.selectable))
const formLocked = computed(() => submitting.value || uncertain.value || detailLoading.value || (mode.value === 'edit' && !record.value?.can_edit))
const productSelectionBlocked = computed(() => productLoading.value || !productLoaded.value || !!productError.value || sourceChanged.value)
const dirty = computed(() => dialog.value && mode.value !== 'detail' && draftSnapshot() !== original.value)
const title = computed(() => mode.value === 'detail' ? '应收对账单详情' : mode.value === 'edit' ? '编辑应收对账单' : '新增应收对账单')
const progress = (value: string) => ({ UNSETTLED: '未结清', PARTIAL: '部分结清', SETTLED: '已结清' }[value] || value)
function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).replaceAll('/', '-')
}
const linePreview = (row: FinanceSourceProduct) => {
  const value = previewLineAmount(row.quantity, prices.value[row.id] || '')
  return value === null ? '请填写有效单价' : displayCents(value)
}
const amountPreview = computed(() => {
  let sum = 0n
  for (const row of selected.value) {
    const value = previewLineAmount(row.quantity, prices.value[row.id] || '')
    if (value === null) return '请核对单价'
    sum += value
  }
  return displayCents(sum)
})
const quantities = computed(() => {
  const result = new Map<string, { name: string; quantity: bigint }>()
  for (const row of selected.value) {
    const previous = result.get(row.unit_code)
    result.set(row.unit_code, { name: row.unit_name, quantity: (previous?.quantity || 0n) + BigInt(row.quantity) })
  }
  return [...result.values()].map(row => `${row.quantity} ${row.name}`).join('；') || '尚未选择产品'
})
let listRequest = 0, detailRequest = 0, sourceRequest = 0, disposed = false
let listController: AbortController | undefined, detailController: AbortController | undefined, sourceController: AbortController | undefined
let creationKey = '', submittedBody: FinanceStatementInput | undefined
const message = (failure: unknown) => axios.isAxiosError(failure) ? failure.response?.data?.error?.message || '请求未完成，请重试。' : failure instanceof Error ? failure.message : '请求失败，请重试。'

async function loadList() {
  if (!can('view')) return
  const token = ++listRequest; listController?.abort(); listController = new AbortController()
  loading.value = true; listError.value = ''
  const query: FinanceStatementQuery = { page: page.value, page_size: 20, q: applied.q,
    ...(applied.status ? { status: applied.status } : {}), ...(applied.settlement_status ? { settlement_status: applied.settlement_status } : {}) }
  try {
    const response = await fetchFinanceStatements(query, listController.signal)
    if (token !== listRequest || disposed) return
    rows.value = response.data; total.value = response.meta.total; page.value = response.meta.page; loaded.value = true; forbidden.value = false
  } catch (failure) {
    if (token !== listRequest || disposed || axios.isCancel(failure)) return
    forbidden.value = axios.isAxiosError(failure) && [401, 403].includes(failure.response?.status || 0)
    if (forbidden.value) { rows.value = []; total.value = 0 }
    listError.value = `${loaded.value && !forbidden.value ? '刷新失败，保留上次结果。' : ''}${message(failure)}`
  } finally { if (token === listRequest && !disposed) loading.value = false }
}
function filter(reset = false) {
  if (reset) { search.value = ''; status.value = ''; settlement.value = '' }
  Object.assign(applied, { q: search.value.trim(), status: status.value, settlement_status: settlement.value }); page.value = 1; void loadList()
}
function sourceFromRecord(value: FinanceStatement) {
  task.value = { id: value.production_task_id, task_number: value.task_number, source_order_date: value.source_order_date, salesperson: value.salesperson, status: '' }
  selected.value = value.lines.map(line => ({ ...line, id: line.production_task_product_id, selectable: true, reason: null, error_code: null, occupied_statement_number: value.number }))
  prices.value = Object.fromEntries(value.lines.map(line => [line.production_task_product_id, line.unit_price])); revision.value = value.source_revision
  customPriceIds.value = new Set(value.lines.map(line => line.production_task_product_id))
}
async function openEditor(action: 'create' | 'edit' | 'detail', row?: FinanceStatement) {
  if (!can(action === 'create' ? 'add' : action === 'edit' ? 'change' : 'view')) return
  ++sourceRequest; sourceController?.abort(); sourceOpen.value = false
  products.value = []; productPage.value = 1; productTotal.value = 0; productLoading.value = false; productLoaded.value = false; productError.value = ''; sourceChanged.value = false
  mode.value = action; record.value = undefined; latest.value = undefined; task.value = undefined; selected.value = []; prices.value = {}; revision.value = ''
  customPriceIds.value.clear()
  acknowledged.value = false; salespersonChanges.value = []; formError.value = ''; fieldErrors.value = {}; conflict.value = false; uncertain.value = false
  creationKey = crypto.randomUUID(); submittedBody = undefined; original.value = draftSnapshot(); dialog.value = true
  const token = ++detailRequest; detailController?.abort(); detailController = new AbortController(); detailLoading.value = !!row
  if (!row) return
  try {
    const response = await fetchFinanceStatement(row.id, detailController.signal)
    if (token !== detailRequest || !dialog.value || disposed) return
    record.value = response; sourceFromRecord(response); original.value = draftSnapshot()
    if (action === 'edit' && !response.can_edit) formError.value = response.blocked_reason || '当前对账单不可编辑。'
    if (action === 'edit') {
      await loadProducts(1)
      if (token === detailRequest && dialog.value && !disposed) original.value = draftSnapshot()
    }
  } catch (failure) { if (token === detailRequest && !disposed && !axios.isCancel(failure)) formError.value = message(failure) }
  finally { if (token === detailRequest && !disposed) detailLoading.value = false }
}
async function confirmLeave() {
  if (receiptSection.value && !await receiptSection.value.confirmLeave()) return false
  if (submitting.value || uncertain.value || voidBusy.value || deleting.value) { ElMessage.warning('提交结果尚未确认，请先完成当前请求。'); return false }
  if (!dirty.value && !(voidOpen.value && voidReason.value.trim())) return true
  try { await ElMessageBox.confirm('有未保存的内容，确定放弃？', '离开未保存表单', { confirmButtonText: '放弃修改', cancelButtonText: '继续填写', customClass: 'finance-statement-confirm' }); return true }
  catch { return false }
}
async function refreshAfterReceipt() {
  if (record.value) await openEditor('detail', record.value)
  await loadList()
}
async function closeDialog(done?: () => void) {
  if (!await confirmLeave()) return
  ++detailRequest; ++sourceRequest; detailController?.abort(); sourceController?.abort(); detailLoading.value = false; sourceOpen.value = false
  if (done) done(); else dialog.value = false
}
async function chooseTask(value: FinanceSourceTask) {
  if (value.id === task.value?.id || formLocked.value) return
  const editorToken = detailRequest, previousTask = task.value?.id
  if (task.value) {
    try { await ElMessageBox.confirm('更换生产任务将清除已选产品、调整单价及归属确认。确定更换？', '更换生产任务', { confirmButtonText: '更换并重新选择', cancelButtonText: '保留当前任务', customClass: 'finance-statement-confirm' }) }
    catch { return }
  }
  if (disposed || !dialog.value || editorToken !== detailRequest || previousTask !== task.value?.id) return
  ++sourceRequest; sourceController?.abort()
  task.value = value; selected.value = []; prices.value = {}; revision.value = ''; acknowledged.value = false
  customPriceIds.value.clear()
  products.value = []; productPage.value = 1; productTotal.value = 0; productLoaded.value = false; productError.value = ''; sourceChanged.value = false
  salespersonChanges.value = []; formError.value = ''; fieldErrors.value = {}; conflict.value = false
  await loadProducts(1)
}
async function loadProducts(requestedPage = productPage.value, acceptChanged = false) {
  if (!task.value || mode.value === 'detail' || submitting.value || uncertain.value) return
  const taskId = task.value.id, token = ++sourceRequest
  sourceController?.abort(); sourceController = new AbortController()
  const signal = sourceController.signal
  const isCurrent = () => token === sourceRequest && task.value?.id === taskId && dialog.value && !disposed
  productLoading.value = true; productError.value = ''
  try {
    const query = { page: requestedPage, page_size: 20, editing_statement_id: record.value?.id }
    const response = await fetchFinanceSourceProducts(taskId, query, signal)
    if (!isCurrent()) return
    if (revision.value && revision.value !== response.source_revision && !acceptChanged) {
      sourceChanged.value = true; productError.value = '生产来源已变化，已选行及调整单价已保留。请重新载入并核对后再保存。'; return
    }
    const currentRows = new Map(response.data.map(row => [row.id, row]))
    // 接受新来源版本时核对所有已选行，避免跨页选择仍使用旧数量或已移除的产品。
    if (acceptChanged && selected.value.length) {
      for (let number = 1; number <= response.meta.total_pages; number++) {
        if (number === response.meta.page) continue
        const other = await fetchFinanceSourceProducts(taskId, { ...query, page: number }, signal)
        if (!isCurrent()) return
        if (other.source_revision !== response.source_revision) {
          sourceChanged.value = true; productError.value = '载入期间生产来源再次变化，当前选择和单价已保留，请重试。'; return
        }
        for (const row of other.data) currentRows.set(row.id, row)
      }
    }
    selected.value = selected.value.map(row => currentRows.get(row.id) || (acceptChanged ? { ...row, selectable: false, reason: '该产品已从生产任务移除，请取消选择。' } : row))
    for (const row of currentRows.values()) {
      if (!selectedIds.value.has(row.id) && !customPriceIds.value.has(row.id)) prices.value[row.id] = row.reference_unit_price_cny ?? ''
      else prices.value[row.id] ??= row.reference_unit_price_cny ?? ''
    }
    products.value = response.data; productTotal.value = response.meta.total; productPage.value = response.meta.page
    if (record.value?.production_task_id !== taskId) { task.value = response.task; salespersonChanges.value = response.salesperson_changes }
    if (revision.value !== response.source_revision) acknowledged.value = false
    revision.value = response.source_revision; sourceChanged.value = false; productLoaded.value = true
  } catch (failure) {
    if (isCurrent() && !axios.isCancel(failure)) productError.value = `${productLoaded.value ? '刷新失败，保留上次产品及选择。' : ''}${message(failure)}`
  } finally { if (isCurrent()) productLoading.value = false }
}
function toggleProduct(row: FinanceSourceProduct, checked: boolean) {
  if (formLocked.value || productLoading.value) return
  if (checked) {
    if (!row.selectable || productSelectionBlocked.value || selectedIds.value.has(row.id)) return
    selected.value = [...selected.value, row]
  } else selected.value = selected.value.filter(item => item.id !== row.id)
  fieldErrors.value = {}
}
const priceError = (row: FinanceSourceProduct) => fieldErrors.value[`lines.${selected.value.findIndex(item => item.id === row.id)}.unit_price`]
async function save() {
  if (submitting.value || detailLoading.value || !task.value || (mode.value === 'edit' && !record.value?.can_edit)) return
  if (!uncertain.value && (productSelectionBlocked.value || invalidSelected.value.length)) return
  if (!can(mode.value === 'create' ? 'add' : 'change')) return
  formError.value = ''; fieldErrors.value = {}
  if (!uncertain.value) {
    if (!selected.value.length) { formError.value = '请选择至少一条完整产品行。'; return }
    selected.value.forEach((row, index) => { if (previewLineAmount(row.quantity, prices.value[row.id] || '') === null) fieldErrors.value[`lines.${index}.unit_price`] = '请填写大于零、最多4位小数的单价。' })
    if (Object.keys(fieldErrors.value).length) { formError.value = '请核对标记的单价。'; return }
    if (amountPreview.value === '0.00') { formError.value = '逐行舍入后的对账总额须大于零，请核对单价。'; return }
    submittedBody = { production_task_id: task.value.id, source_revision: revision.value, acknowledge_salesperson_change: acknowledged.value,
      lines: selected.value.map(row => ({ production_task_product_id: row.id, unit_price: prices.value[row.id]! })) }
  }
  submitting.value = true
  try {
    const result = mode.value === 'create' ? await createFinanceStatement(submittedBody!, creationKey) : await updateFinanceStatement(record.value!.id, submittedBody!, record.value!.etag)
    uncertain.value = false; record.value = result; original.value = draftSnapshot(); dialog.value = false; ElMessage.success('对账单已保存'); await loadList()
  } catch (failure) {
    const httpStatus = axios.isAxiosError(failure) ? failure.response?.status : undefined
    formError.value = message(failure); uncertain.value = mode.value === 'create' && (!httpStatus || httpStatus >= 500)
    if (!uncertain.value) creationKey = crypto.randomUUID()
    conflict.value = [409, 412].includes(httpStatus || 0)
    if (axios.isAxiosError(failure)) {
      const body = failure.response?.data?.error
      fieldErrors.value = Object.fromEntries(Object.entries(body?.field_errors || {}).map(([key, val]) => [key, Array.isArray(val) ? val.join('；') : String(val)]))
      if (body?.code === 'SALESPERSON_CONFIRMATION_REQUIRED') salespersonChanges.value = body.meta?.previous_statements || []
    }
  } finally { submitting.value = false }
}
async function compareLatest() {
  if (!record.value) { await loadProducts(); return }
  if (detailLoading.value) return
  const id = record.value.id, token = ++detailRequest
  detailController?.abort(); detailController = new AbortController(); detailLoading.value = true
  try {
    const response = await fetchFinanceStatement(id, detailController.signal)
    if (token === detailRequest && dialog.value && record.value?.id === id && !disposed) latest.value = response
  } catch (failure) {
    if (token === detailRequest && !disposed && !axios.isCancel(failure)) formError.value = message(failure)
  } finally { if (token === detailRequest && !disposed) detailLoading.value = false }
}
function acceptLatest() {
  if (!record.value || !latest.value) return
  record.value = { ...record.value, etag: latest.value.etag, can_edit: latest.value.can_edit, blocked_reason: latest.value.blocked_reason }
  latest.value = undefined; conflict.value = false; formError.value = '最新版本已比较，当前输入保留。请刷新产品并核对来源与金额。'
}
async function startVoid(row: FinanceStatement) {
  if (!can('void')) return
  voidReason.value = ''; voidError.value = ''; voidRecord.value = undefined; voidOpen.value = true; voidBusy.value = true
  try { voidRecord.value = await fetchFinanceStatement(row.id) } catch (failure) { voidError.value = message(failure) }
  finally { voidBusy.value = false }
}
async function closeVoid(done?: () => void) { if (await confirmLeave()) { if (done) done(); else voidOpen.value = false } }
async function submitVoid() {
  if (voidBusy.value || !voidRecord.value || !can('void')) return
  if (!voidReason.value.trim()) { voidError.value = '请填写作废原因。'; return }
  voidBusy.value = true; voidError.value = ''
  try { await voidFinanceStatement(voidRecord.value.id, voidReason.value.trim(), voidRecord.value.etag); voidOpen.value = false; voidReason.value = ''; ElMessage.success('对账单已作废，历史保留'); await loadList() }
  catch (failure) { voidError.value = message(failure) }
  finally { voidBusy.value = false }
}
async function deleteRecord(row: FinanceStatement) {
  if (!can('delete') || row.status !== 'VOID' || deleting.value || voidBusy.value || submitting.value) return
  deleting.value = row.id
  try {
    const current = await fetchFinanceStatement(row.id)
    if (disposed) return
    if (current.status !== 'VOID' || !current.can_delete) {
      ElMessage.warning(current.delete_block_reason || '仅可删除已作废且没有关联收款的对账单，请先删除关联收款。')
      await loadList(); return
    }
    if (!current.etag) { ElMessage.error('未取得单据版本，请刷新后重试。'); return }
    try {
      await ElMessageBox.confirm(`确定彻底删除对账单 ${current.number}？删除后无法恢复。必须先删除全部关联收款；订金须先删除引用它的货款。`, '彻底删除对账单', { confirmButtonText: '彻底删除', cancelButtonText: '取消', type: 'warning', customClass: 'finance-statement-confirm' })
    } catch { return }
    if (disposed || !can('delete')) return
    await deleteFinanceStatement(current.id, current.etag)
    if (disposed) return
    if (record.value?.id === current.id) { ++detailRequest; detailController?.abort(); dialog.value = false; record.value = undefined }
    ElMessage.success(`对账单 ${current.number} 已彻底删除。`)
    await loadList()
  } catch (failure) {
    if (disposed) return
    const httpStatus = axios.isAxiosError(failure) ? failure.response?.status : undefined
    if (httpStatus === 404) {
      ElMessage.warning('该对账单已不存在，正在刷新列表。')
      if (record.value?.id === row.id) { ++detailRequest; detailController?.abort(); dialog.value = false; record.value = undefined }
      await loadList()
    } else if (httpStatus === 412) {
      ElMessage.warning('对账单已被更新，本次未删除；请核对刷新后的记录并重新确认。')
      if (dialog.value && mode.value === 'detail' && record.value?.id === row.id) await openEditor('detail', row)
      await loadList()
    } else { ElMessage.error(message(failure)) }
  } finally { if (!disposed) deleting.value = '' }
}
const menus = new Map<string, DropdownInstance>()
let pending: { id: string; run: () => void } | undefined
function command(action: string, row: FinanceStatement) {
  if (deleting.value) return
  pending = { id: row.id, run: () => { if (action === 'delete') void deleteRecord(row); else if (action === 'void') void startVoid(row); else void openEditor(action === 'edit' ? 'edit' : 'detail', row) } }
  menus.get(row.id)?.handleClose()
}
async function menuVisibility(visible: boolean, id: string) {
  if (visible || pending?.id !== id) return
  const run = pending.run; pending = undefined; await nextTick()
  if (disposed) return
  document.querySelector<HTMLButtonElement>(`[data-statement-menu="${id}"]`)?.focus({ preventScroll: true }); run()
}
function closeMenu(id: string) { menus.get(id)?.handleClose(); document.querySelector<HTMLButtonElement>(`[data-statement-menu="${id}"]`)?.focus({ preventScroll: true }) }
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value || submitting.value || uncertain.value || deleting.value || (voidOpen.value && voidReason.value)) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(confirmLeave)
onMounted(() => { void loadList(); window.addEventListener('beforeunload', beforeUnload) })
onBeforeUnmount(() => { disposed = true; ++listRequest; ++detailRequest; ++sourceRequest; listController?.abort(); detailController?.abort(); sourceController?.abort(); menus.clear(); pending = undefined; window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <section class="finance-statements erp-glass-list">
    <el-alert v-if="!can('view') || forbidden" title="没有应收对账单查看权限，请联系授权管理员。" type="warning" :closable="false"/>
    <template v-else>
      <div class="erp-list-filter"><div class="erp-list-heading"><div class="erp-list-title-row"><h1>应收对账单</h1><span class="erp-list-count">{{loaded ? `${total} 张对账单` : '尚未加载'}}</span></div></div>
        <div class="erp-list-filters">
          <label>搜索 <el-input v-model="search" placeholder="对账单 / 任务号 / 业务员" clearable @keyup.enter="filter()"/></label>
          <label>状态 <el-select v-model="status" aria-label="单据状态" placeholder="全部状态"><el-option label="全部状态" value=""/><el-option label="有效" value="ACTIVE"/><el-option label="已作废" value="VOID"/></el-select></label>
          <label>结算 <el-select v-model="settlement" aria-label="结算进度" placeholder="全部进度"><el-option label="全部进度" value=""/><el-option label="未结清" value="UNSETTLED"/><el-option label="部分结清" value="PARTIAL"/><el-option label="已结清" value="SETTLED"/></el-select></label>
          <div class="erp-list-filter-actions"><el-button @click="filter(true)">重置</el-button><el-button @click="filter()">应用筛选</el-button><el-divider direction="vertical"/><el-button v-if="can('add')" type="primary" @click="openEditor('create')">新增对账单</el-button></div>
        </div>
      </div>
      <div class="erp-list-data"><div class="erp-list-toolbar"><el-button :loading="loading" @click="loadList">刷新</el-button></div>
        <el-alert v-if="listError" :title="listError" type="error" :closable="false"><el-button link @click="loadList">重试</el-button></el-alert>
        <div v-loading="loading" class="erp-list-table-frame" :aria-busy="loading"><el-table :data="rows" row-key="id" border height="100%">
          <el-table-column prop="number" label="对账单号" min-width="185"/><el-table-column prop="task_number" label="生产任务单" min-width="170"/>
          <el-table-column label="业务员" min-width="160"><template #default="{row}">{{row.salesperson.name}}</template></el-table-column>
          <el-table-column prop="source_order_date" label="来源日期" width="120"/>
          <el-table-column v-for="column in [{key:'amount',label:'对账金额（元）'},{key:'settled_amount',label:'已核销'},{key:'discount_amount',label:'有效折让'},{key:'outstanding_amount',label:'未付'},{key:'available_deposit_amount',label:'可用订金'}]" :key="column.key" :prop="column.key" :label="column.label" min-width="190" align="right" class-name="finance-money"/>
          <el-table-column label="结算进度" width="110"><template #default="{row}">{{row.status === 'VOID' ? '已作废' : progress(row.settlement_status)}}</template></el-table-column>
          <el-table-column label="单据状态" width="100"><template #default="{row}"><el-tag :type="row.status === 'VOID' ? 'info' : 'success'">{{row.status === 'VOID' ? '已作废' : '有效'}}</el-tag></template></el-table-column>
          <el-table-column label="操作" fixed="right" width="100" align="center"><template #default="{row}"><el-dropdown :ref="(el: unknown) => { if (el) menus.set(row.id, el as DropdownInstance); else menus.delete(row.id) }" trigger="click" placement="bottom-end" popper-class="finance-statement-popper" @command="command($event, row)" @visible-change="menuVisibility($event, row.id)"><el-button link :data-statement-menu="row.id" :disabled="!!deleting" @keydown.esc.stop.prevent="closeMenu(row.id)">更多<svg viewBox="0 0 12 12" aria-hidden="true" class="more-arrow"><path d="m3 4 3 3 3-3"/></svg></el-button><template #dropdown><el-dropdown-menu @keydown.esc.stop.prevent="closeMenu(row.id)"><el-dropdown-item command="detail">详情</el-dropdown-item><el-dropdown-item v-if="can('change')" command="edit" :disabled="!row.can_edit" :title="row.blocked_reason || ''">{{row.can_edit ? '编辑' : row.blocked_reason}}</el-dropdown-item><el-dropdown-item v-if="can('void')" command="void" divided :disabled="!row.can_void" :title="row.blocked_reason || ''"><span class="danger-action">{{row.can_void ? '作废' : '不可作废'}}</span></el-dropdown-item><el-dropdown-item v-if="can('delete') && row.status === 'VOID'" command="delete" divided :disabled="!row.can_delete || !!deleting" :title="row.delete_block_reason || ''"><span class="danger-action">彻底删除</span></el-dropdown-item></el-dropdown-menu></template></el-dropdown></template></el-table-column>
          <template #empty><span v-if="loading">正在加载对账单…</span><span v-else-if="listError">对账数据尚未成功加载</span><div v-else-if="applied.q || applied.status || applied.settlement_status">没有匹配的对账单 <el-button link @click="filter(true)">清除筛选</el-button></div><div v-else>暂无应收对账单 <el-button v-if="can('add')" link @click="openEditor('create')">新增对账单</el-button></div></template>
        </el-table></div>
        <div class="erp-list-footer"><span>金额单位：元</span><el-pagination v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next" @current-change="loadList"/></div>
      </div>
    </template>
  </section>
  <AppWindowDialog v-model="dialog" :title="title" :width="1360" :min-width="280" :minimizable="false" :before-close="closeDialog" destroy-on-close modal-class="finance-statement-overlay">
    <div v-loading="detailLoading" class="statement-dialog">
      <el-alert v-if="formError" :title="formError" type="error" :closable="false"/>
      <el-alert v-if="uncertain" title="提交结果尚未确认。请重试原提交核实结果，当前内容不会重复创建。" type="warning" :closable="false"/>
      <template v-if="mode === 'detail' && record">
        <div class="document-heading"><div><h2>{{record.number}}</h2><p>应收对账单 · {{record.operator.name}} · {{formatDateTime(record.created_at)}}</p></div><el-tag :type="record.status === 'VOID' ? 'info' : 'success'">{{record.status === 'VOID' ? '已作废' : '有效'}}</el-tag></div>
        <dl class="document-facts"><div><dt>生产任务单</dt><dd>{{record.task_number}}</dd></div><div><dt>业务员</dt><dd>{{record.salesperson.name}}</dd></div><div><dt>来源日期</dt><dd>{{record.source_order_date}}</dd></div></dl>
        <el-alert v-if="record.status === 'VOID'" :title="`已作废：${record.void_reason}；历史明细保留，占用已释放。`" type="info" :closable="false"/>
        <el-alert v-else-if="record.blocked_reason" :title="record.blocked_reason" type="info" :closable="false"/>
      </template>
      <el-form v-else-if="mode !== 'detail'" label-position="top" class="form-grid" :disabled="formLocked">
        <el-form-item label="生产任务单" required :error="fieldErrors.production_task_id"><el-input class="task-selector" :model-value="task?.task_number || ''" readonly><template #append><el-button @click="sourceOpen = true">选择</el-button></template></el-input></el-form-item>
        <el-form-item label="来源单据日期"><el-input :model-value="task?.source_order_date || ''" readonly/></el-form-item>
        <el-form-item label="业务员"><el-input :model-value="task?.salesperson.name || ''" readonly/></el-form-item>
      </el-form>
      <el-alert v-if="mode !== 'detail' && salespersonChanges.length" title="当前任务业务员与既有对账快照不同。新建或更换来源将使用当前业务员，历史归属不变。" type="warning" :closable="false"><el-checkbox v-model="acknowledged" :disabled="submitting || uncertain">我已核对，按当前业务员继续</el-checkbox></el-alert>
      <el-alert v-if="mode !== 'detail' && productError" :title="productError" type="error" :closable="false"><el-button :disabled="productLoading || formLocked" @click="loadProducts(sourceChanged ? 1 : productPage, sourceChanged)">{{sourceChanged ? '重新载入并核对' : '重试'}}</el-button></el-alert>
      <el-alert v-if="mode !== 'detail' && invalidSelected.length" :title="`已选产品中有 ${invalidSelected.length} 行已失效，请取消后再保存。`" type="warning" :closable="false"><div v-for="row in invalidSelected" :key="row.id">{{row.product_name_snapshot}}：{{row.reason || '当前不可选'}} <el-button link :disabled="formLocked || productLoading" :aria-label="`取消失效产品${row.product_name_snapshot}`" @click="toggleProduct(row, false)">取消选择</el-button></div></el-alert>
      <div v-loading="productLoading" class="embedded-table statement-products erp-glass-list" :aria-busy="productLoading"><div class="erp-list-table-frame"><el-table :data="mode === 'detail' ? selected : products" border row-key="id">
        <el-table-column v-if="mode !== 'detail'" label="选择" width="48" align="center"><template #default="{row}"><el-checkbox :model-value="selectedIds.has(row.id)" :disabled="formLocked || productLoading || (!selectedIds.has(row.id) && (!row.selectable || productSelectionBlocked))" :aria-label="`选择产品${row.product_name_snapshot}`" @change="toggleProduct(row, !!$event)"/></template></el-table-column>
        <el-table-column label="生产任务单" min-width="116" show-overflow-tooltip><template #default>{{task?.task_number}}</template></el-table-column>
        <el-table-column prop="item_number_snapshot" label="货号" min-width="80" show-overflow-tooltip/><el-table-column label="品名" min-width="100" show-overflow-tooltip><template #default="{row}"><span>{{row.product_name_snapshot}}</span><small v-if="mode !== 'detail' && !row.selectable" class="product-block-reason">{{row.reason || '当前不可选'}}</small></template></el-table-column><el-table-column prop="specification_snapshot" label="规格" min-width="120" show-overflow-tooltip/>
        <el-table-column prop="unit_name" label="单位" width="52"/><el-table-column prop="quantity" label="完整数量" min-width="84" align="right"/>
        <el-table-column prop="reference_unit_price_cny" label="参考单价" min-width="110" align="right"/>
        <el-table-column label="对账单价" min-width="116" align="right"><template #default="{row,$index}"><span v-if="mode === 'detail'">{{prices[row.id]}}</span><div v-else><el-input v-model="prices[row.id]" :disabled="formLocked || productLoading || !selectedIds.has(row.id)" :aria-label="`第${$index + 1}行对账单价`" inputmode="decimal" @update:model-value="customPriceIds.add(row.id)"/><small v-if="priceError(row)" class="field-error">{{priceError(row)}}</small></div></template></el-table-column>
        <el-table-column label="金额（元）" min-width="128" align="right"><template #default="{row,$index}">{{mode === 'detail' ? record?.lines[$index]?.amount : linePreview(row)}}</template></el-table-column>
        <template #empty>{{mode === 'detail' ? '没有已保存产品行' : productLoading ? '正在加载任务产品…' : productError ? '产品尚未成功加载' : !task ? '请先选择生产任务单' : '该任务没有产品明细'}}</template>
      </el-table></div></div>
      <div v-if="mode !== 'detail' && task" class="product-footer"><span>已选 {{selected.length}} 行</span><el-button link :disabled="formLocked || productLoading || sourceChanged" @click="loadProducts()">刷新产品</el-button><el-pagination v-if="productTotal > 20" :current-page="productPage" :total="productTotal" :page-size="20" :disabled="formLocked || productLoading || sourceChanged" layout="prev, pager, next" @current-change="loadProducts($event)"/></div>
      <div class="statement-summary"><span>数量合计：{{quantities}}</span><strong>对账金额：{{mode === 'detail' ? record?.amount : amountPreview}} 元</strong></div>
      <dl v-if="mode === 'detail' && record" class="document-facts"><div v-for="column in [{key:'settled_amount',label:'已核销'},{key:'discount_amount',label:'有效折让'},{key:'outstanding_amount',label:'未付'},{key:'available_deposit_amount',label:'可用订金'},{key:'bank_received_amount',label:'累计银行到账'}]" :key="column.key"><dt>{{column.label}}</dt><dd>{{record[column.key as keyof FinanceStatement]}} 元</dd></div></dl>
      <FinanceStatementReceipts v-if="mode === 'detail' && record" ref="receiptSection" :statement="record" @changed="refreshAfterReceipt"/>
      <el-button v-if="mode !== 'detail' && conflict" @click="compareLatest">查看最新版本并比较</el-button>
      <div v-if="latest" class="latest-version"><strong>服务器最新：{{latest.number}} / {{latest.task_number}} / {{latest.salesperson.name}} / {{latest.amount}} 元</strong><p>{{latest.blocked_reason || '当前输入已保留，请核对来源与金额。'}}</p><el-button :disabled="!latest.can_edit" @click="acceptLatest">已比较，保留输入继续修改</el-button></div>
    </div>
    <template #footer><el-button :disabled="submitting || uncertain" @click="closeDialog()">{{mode === 'detail' ? '关闭' : '取消'}}</el-button><el-button v-if="mode !== 'detail'" type="primary" :loading="submitting" :disabled="detailLoading || !task || (mode === 'edit' && !record?.can_edit) || (!uncertain && (productSelectionBlocked || !selected.length || !!invalidSelected.length))" @click="save">{{uncertain ? '重试原提交' : '保存对账单'}}</el-button></template>
  </AppWindowDialog>
  <FinanceStatementSourceDialog v-model="sourceOpen" @task="chooseTask"/>
  <AppWindowDialog v-model="voidOpen" title="作废对账单" :width="620" :min-width="280" :minimizable="false" :before-close="closeVoid" modal-class="finance-statement-overlay">
    <div class="statement-dialog"><h3>{{voidRecord?.number || '读取对账单…'}}</h3><el-alert title="仅无有效收款时可作废；释放产品行占用，保留历史记录。" type="warning" :closable="false"/><el-alert v-if="voidRecord?.blocked_reason" :title="voidRecord.blocked_reason" type="warning" :closable="false"/><el-alert v-if="voidError" :title="voidError" type="error" :closable="false"/><el-form label-position="top"><el-form-item label="作废原因" required><el-input v-model="voidReason" aria-label="作废原因" type="textarea" :rows="3" maxlength="500" show-word-limit :disabled="voidBusy"/></el-form-item></el-form></div>
    <template #footer><el-button :disabled="voidBusy" @click="closeVoid()">取消</el-button><el-button type="danger" :loading="voidBusy" :disabled="!voidRecord?.can_void" @click="submitVoid">确认作废</el-button></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.more-arrow { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.5; margin-left: 4px; }
.finance-statements .erp-list-filters label:first-child .el-input { width: 260px; }.finance-statements .erp-list-filters .el-select { width: 130px; }
.erp-list-toolbar { color: var(--erp-color-text-secondary); gap: 12px; }.erp-list-toolbar > .el-button { margin-left: auto; }
.finance-statements :deep(.el-table__header .cell) { font-weight: 500; }.finance-statements :deep(.finance-money .cell) { font-variant-numeric: tabular-nums; font-size: 13px; font-weight: 600; white-space: nowrap; }
.statement-dialog { display: grid; gap: 16px; min-width: 0; color: var(--erp-color-text-primary); }.form-grid, .document-facts { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 16px 20px; }.form-grid .el-form-item { margin-bottom: 0; min-width: 0; }
.form-grid { grid-template-columns: minmax(0,280px) repeat(2,minmax(0,200px)); }
/* 弹窗全局强制 5px 圆角；组合控件的拼接处需局部取消右侧圆角。 */
.statement-dialog .form-grid .task-selector.el-input :deep(.el-input__wrapper) { border-top-right-radius: 0 !important; border-bottom-right-radius: 0 !important; }
.statement-dialog .task-selector :deep(.el-input-group__append) { border-radius: 0 5px 5px 0; box-shadow: 0 1px 0 0 var(--erp-dialog-input-border) inset, 0 -1px 0 0 var(--erp-dialog-input-border) inset, -1px 0 0 0 var(--erp-dialog-input-border) inset; }
.statement-dialog .task-selector :deep(.el-input-group__append .el-button) { border-radius: 0 5px 5px 0; box-shadow: none; }
.document-heading, .statement-summary { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }dt, .document-heading p { color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
.product-footer { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 12px; color: var(--erp-color-text-secondary); }.product-footer .el-pagination { margin-left: auto; }.product-block-reason { display: block; white-space: normal; overflow-wrap: anywhere; color: var(--el-color-warning); font-size: 12px; line-height: 18px; }
.embedded-table { min-height: 0; }.embedded-table .erp-list-table-frame { flex: none; border-radius: 8px; }
.statement-products :deep(.el-table .cell) { padding: 0 8px; }
.document-heading { justify-content: space-between; align-items: flex-start; border-bottom: 1px solid var(--erp-color-border); padding-bottom: 16px; }.document-heading h2 { margin: 0; font-size: 22px; line-height: 30px; overflow-wrap: anywhere; }.document-heading p { margin: 6px 0 0; }
.document-facts { margin: 0; }.document-facts dd { margin: 4px 0 0; font-size: 14px; line-height: 24px; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.statement-summary { justify-content: space-between; padding: 14px 0; border-bottom: 1px solid var(--erp-color-border); font-size: 13px; }.statement-summary strong { font-size: 18px; color: var(--erp-menu-accent); overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }.field-error { color: var(--el-color-danger); }.latest-version { padding-top: 16px; border-top: 1px solid var(--erp-color-border); overflow-wrap: anywhere; }
@media (max-width: 900px) { .form-grid { grid-template-columns: repeat(2,minmax(0,280px)); }.document-facts { grid-template-columns: repeat(2,minmax(0,1fr)); }.finance-statements .erp-list-heading h1 { font-size: 28px !important; line-height: 36px !important; }.finance-statements .erp-list-footer { height: auto; flex-wrap: wrap; } }
@media (max-width: 600px) { .form-grid, .document-facts { grid-template-columns: minmax(0,1fr); }.finance-statements .erp-list-heading h1 { font-size: 24px !important; line-height: 32px !important; }.finance-statements .erp-list-filters > label { width: 100%; white-space: nowrap; }.finance-statements .erp-list-filters label:first-child .el-input, .finance-statements .erp-list-filters .el-select { width: 100%; }.finance-statements .erp-list-filter-actions, .finance-statements .erp-list-toolbar { flex-wrap: wrap; margin-left: 0; }.finance-statements .erp-list-filter-actions { flex: 1 1 100%; min-width: 0; width: 100%; }.finance-statements :deep(.el-table-fixed-column--right) { position: static !important; } }
@media (prefers-reduced-motion: reduce) { .finance-statements, .statement-dialog { &, :deep(*), :deep(*::before), :deep(*::after) { animation: none !important; transition: none !important; } } }
</style>
<style>
.finance-statement-popper .danger-action { color: var(--el-color-danger); }
@media (prefers-reduced-motion: reduce) { .finance-statement-popper, .finance-statement-popper *, .finance-statement-confirm, .finance-statement-confirm *, .finance-statement-overlay, .finance-statement-overlay * { animation: none !important; transition: none !important; } }
</style>
