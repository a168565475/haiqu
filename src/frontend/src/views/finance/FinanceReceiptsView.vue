<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { DropdownInstance } from 'element-plus'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { deleteFinanceReceipt, fetchFinanceReceipt, fetchFinanceReceipts, voidFinanceReceipt } from '@/api/financeReceipts'
import type { Receipt, ReceiptQuery, ReceiptType } from '@/types/financeReceipts'
import ReceiptEditor from './ReceiptEditor.vue'
import ReceiptDetail from './ReceiptDetail.vue'

const auth = useAuthStore(), route = useRoute()
const can = (action: string) => auth.user?.is_superuser || auth.hasPermission(`finance.${action}_receipt`)
const rows = ref<Receipt[]>([]), total = ref(0), page = ref(1), pageSize = ref(20)
const q = ref(''), status = ref<'' | 'ACTIVE' | 'VOID'>(''), type = ref<'' | ReceiptType>('')
const applied = reactive({ q: '', status: '' as '' | 'ACTIVE' | 'VOID', receipt_type: '' as '' | ReceiptType })
const loading = ref(false), loaded = ref(false), forbidden = ref(false), listError = ref('')
const editor = ref(false), receiptType = ref<ReceiptType>('DEPOSIT'), initialStatementId = ref<string>()
const editorRef = ref<InstanceType<typeof ReceiptEditor>>()
const detail = ref(false), record = ref<Receipt>(), detailLoading = ref(false), detailError = ref(''), busyRow = ref('')
const rowMenus = new Map<string, DropdownInstance>()
let pendingAction: { id: string; action: string; row: Receipt } | undefined
let request = 0, detailRequest = 0
let controller: AbortController | undefined, detailController: AbortController | undefined
let disposed = false
function message(err: unknown) { return axios.isAxiosError(err) ? err.response?.data?.error?.message || '请求失败，请重试。' : err instanceof Error ? err.message : '请求失败。' }
async function load() {
  if (!can('view')) return
  const token = ++request; controller?.abort(); controller = new AbortController()
  loading.value = true; listError.value = ''
  const query: ReceiptQuery = { page: page.value, page_size: pageSize.value, q: applied.q, ...(applied.status ? { status: applied.status } : {}), ...(applied.receipt_type ? { receipt_type: applied.receipt_type } : {}) }
  try {
    const result = await fetchFinanceReceipts(query, controller.signal)
    if (token !== request || disposed) return
    rows.value = result.data; total.value = result.meta.total; page.value = result.meta.page; loaded.value = true; forbidden.value = false
  } catch (err) {
    if (token !== request || disposed || axios.isCancel(err)) return
    if (axios.isAxiosError(err) && [401, 403].includes(err.response?.status || 0)) { forbidden.value = true; rows.value = []; total.value = 0 }
    listError.value = `${loaded.value && !forbidden.value ? '刷新失败，保留上次结果。' : ''}${message(err)}`
  } finally { if (token === request && !disposed) loading.value = false }
}
function filter(reset = false) {
  if (reset) { q.value = ''; status.value = ''; type.value = '' }
  Object.assign(applied, { q: q.value.trim(), status: status.value, receipt_type: type.value }); page.value = 1; void load()
}
function create(value: ReceiptType, statementId?: string) { if (can('add')) { receiptType.value = value; initialStatementId.value = statementId; editor.value = true } }
async function openDetail(row: Receipt) {
  const token = ++detailRequest; detailController?.abort(); detailController = new AbortController()
  detail.value = true; record.value = undefined; detailLoading.value = true; detailError.value = ''
  try { const value = await fetchFinanceReceipt(row.id, detailController.signal); if (token === detailRequest && detail.value && !disposed) record.value = value }
  catch (err) { if (token === detailRequest && !axios.isCancel(err)) detailError.value = message(err) }
  finally { if (token === detailRequest) detailLoading.value = false }
}
async function voidRecord(row: Receipt) {
  if (!can('void') || !row.can_void || busyRow.value) return
  let reason: string
  try {
    const result = await ElMessageBox.prompt(`作废 ${row.number} 将撤回本单资金影响，保留历史记录。${row.receipt_type === 'GOODS' ? '本单使用的订金将恢复可用。' : '已使用订金必须先作废关联货款。'}`, '作废收款', { confirmButtonText: '确认作废', cancelButtonText: '取消', inputPlaceholder: '填写作废原因', inputValidator: value => !!value?.trim() && value.trim().length <= 500 || '请填写不超过 500 字的作废原因', customClass: 'finance-receipt-confirm' })
    reason = result.value.trim()
  } catch { return }
  busyRow.value = row.id
  try { const value = await voidFinanceReceipt(row.id, reason, row.etag); if (record.value?.id === value.id) record.value = value; ElMessage.success(value.changed ? '收款已作废。' : '收款已是作废状态。'); await load() }
  catch (err) { ElMessage.error(message(err)); if (axios.isAxiosError(err) && err.response?.status === 412) await openDetail(row) }
  finally { busyRow.value = '' }
}
async function deleteRecord(row: Receipt) {
  if (!can('delete') || row.status !== 'VOID' || busyRow.value) return
  busyRow.value = row.id
  try {
    const current = await fetchFinanceReceipt(row.id)
    if (disposed) return
    if (current.status !== 'VOID' || !current.can_delete) {
      ElMessage.warning(current.delete_block_reason || '仅可删除已作废收款；订金请先删除引用它的货款。')
      await load(); return
    }
    if (!current.etag) { ElMessage.error('未取得单据版本，请刷新后重试。'); return }
    try {
      await ElMessageBox.confirm(`确定彻底删除收款单 ${current.number}？本单记录及独占水单将一并删除，无法恢复。${current.receipt_type === 'DEPOSIT' ? '订金必须先删除引用它的货款。' : '引用的订金水单不随本单删除。'}`, '彻底删除收款单', { confirmButtonText: '彻底删除', cancelButtonText: '取消', type: 'warning', customClass: 'finance-receipt-confirm' })
    } catch { return }
    if (disposed || !can('delete')) return
    await deleteFinanceReceipt(current.id, current.etag)
    if (disposed) return
    if (record.value?.id === current.id) { ++detailRequest; detailController?.abort(); detail.value = false; record.value = undefined }
    ElMessage.success(`收款单 ${current.number} 已彻底删除。`)
    await load()
  } catch (failure) {
    if (disposed) return
    const httpStatus = axios.isAxiosError(failure) ? failure.response?.status : undefined
    if (httpStatus === 404) {
      ElMessage.warning('该收款单已不存在，正在刷新列表。')
      if (record.value?.id === row.id) { ++detailRequest; detailController?.abort(); detail.value = false; record.value = undefined }
      await load()
    } else if (httpStatus === 412) {
      ElMessage.warning('收款单已被更新，本次未删除；请核对刷新后的记录并重新确认。')
      if (detail.value && record.value?.id === row.id) await openDetail(row)
      await load()
    } else { ElMessage.error(message(failure)) }
  } finally { if (!disposed) busyRow.value = '' }
}
function command(action: string, row: Receipt) { if (!busyRow.value) pendingAction = { id: row.id, action, row } }
async function menuVisibility(visible: boolean, id: string) {
  if (visible || pendingAction?.id !== id) return
  const next = pendingAction; pendingAction = undefined; await nextTick()
  if (disposed) return
  document.querySelector<HTMLButtonElement>(`[data-receipt-menu="${id}"]`)?.focus({ preventScroll: true })
  if (next.action === 'detail') void openDetail(next.row); else if (next.action === 'delete') void deleteRecord(next.row); else void voidRecord(next.row)
}
function closeMenu(id: string) { rowMenus.get(id)?.handleClose(); document.querySelector<HTMLButtonElement>(`[data-receipt-menu="${id}"]`)?.focus({ preventScroll: true }) }
function beforeUnload(event: BeforeUnloadEvent) { if (editor.value || busyRow.value) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(async () => {
  if (busyRow.value) { ElMessage.warning('请求尚未完成，请稍候。'); return false }
  return await editorRef.value?.confirmLeave() !== false
})
onMounted(() => {
  void load(); window.addEventListener('beforeunload', beforeUnload)
  if (typeof route.query.statement_id === 'string') create(route.query.receipt_type === 'GOODS' ? 'GOODS' : 'DEPOSIT', route.query.statement_id)
})
onBeforeUnmount(() => { disposed = true; ++request; ++detailRequest; controller?.abort(); detailController?.abort(); rowMenus.clear(); window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <section class="finance-receipts erp-glass-list">
    <el-alert v-if="!can('view') || forbidden" title="没有收款查看权限，请联系授权管理员。" type="warning" :closable="false"/>
    <template v-else>
      <div class="erp-list-filter"><div class="erp-list-heading"><div class="erp-list-title-row"><h1>收款确认单</h1><span class="erp-list-count">{{ loaded ? `${total} 条收款` : '尚未加载' }}</span></div></div>
        <div class="erp-list-filters"><label>搜索 <el-input v-model="q" placeholder="收款单 / 对账单 / 生产任务" clearable @keyup.enter="filter()"/></label><label>类型 <el-select v-model="type" aria-label="收款类型筛选"><el-option label="全部类型" value=""/><el-option label="订金" value="DEPOSIT"/><el-option label="货款" value="GOODS"/></el-select></label><label>状态 <el-select v-model="status" aria-label="收款状态筛选"><el-option label="全部状态" value=""/><el-option label="有效" value="ACTIVE"/><el-option label="已作废" value="VOID"/></el-select></label><div class="erp-list-filter-actions"><el-button @click="filter(true)">重置</el-button><el-button @click="filter()">应用筛选</el-button><el-divider direction="vertical"/><el-button v-if="can('add')" type="primary" @click="create('DEPOSIT')">登记订金</el-button><el-button v-if="can('add')" @click="create('GOODS')">登记货款</el-button></div></div>
      </div>
      <div class="erp-list-data"><el-alert v-if="listError" :title="listError" type="error" :closable="false"><el-button link @click="load">重试</el-button></el-alert>
        <div v-loading="loading" class="erp-list-table-frame"><el-table :data="rows" height="100%" row-key="id" border highlight-current-row>
          <el-table-column prop="number" label="收款单号" min-width="175"/><el-table-column label="收款类型" width="85"><template #default="{ row }">{{ row.receipt_type === 'DEPOSIT' ? '订金' : '货款' }}</template></el-table-column><el-table-column prop="statement_snapshot.task_number" label="生产任务" min-width="150"/><el-table-column prop="statement_snapshot.number" label="所属对账单" min-width="175"/><el-table-column label="业务员" min-width="150"><template #default="{ row }">{{ row.statement_snapshot.salesperson_name || '—' }}</template></el-table-column><el-table-column prop="cash_amount" label="实际到账" min-width="140" align="right"/><el-table-column prop="fee_amount" label="手续费" min-width="110" align="right"/><el-table-column prop="allocated_deposit_amount" label="订金抵扣" min-width="130" align="right"/><el-table-column prop="discount_amount" label="折让" min-width="110" align="right"/><el-table-column prop="settled_amount" label="本单核销" min-width="130" align="right"/><el-table-column label="单据状态" width="90"><template #default="{ row }">{{ row.status === 'ACTIVE' ? '有效' : '已作废' }}</template></el-table-column>
          <el-table-column label="操作" width="100" fixed="right" align="center"><template #default="{ row }"><el-dropdown :ref="(el: unknown) => { if (el) rowMenus.set(row.id, el as DropdownInstance); else rowMenus.delete(row.id) }" trigger="click" popper-class="finance-receipt-popper" @command="command($event, row)" @visible-change="menuVisibility($event, row.id)"><el-button link :data-receipt-menu="row.id" :disabled="!!busyRow" @keydown.esc.stop.prevent="closeMenu(row.id)">更多<svg viewBox="0 0 12 12" aria-hidden="true" class="more-arrow"><path d="m3 4 3 3 3-3"/></svg></el-button><template #dropdown><el-dropdown-menu @keydown.esc.stop.prevent="closeMenu(row.id)"><el-dropdown-item command="detail">详情</el-dropdown-item><el-dropdown-item v-if="can('void')" command="void" divided :disabled="!row.can_void" :title="row.blocked_reason || ''"><span class="danger-action">{{ row.can_void ? '作废' : row.blocked_reason || '不可作废' }}</span></el-dropdown-item><el-dropdown-item v-if="can('delete') && row.status === 'VOID'" command="delete" divided :disabled="!row.can_delete || !!busyRow" :title="row.delete_block_reason || ''"><span class="danger-action">彻底删除</span></el-dropdown-item></el-dropdown-menu></template></el-dropdown></template></el-table-column>
          <template #empty><span v-if="loading">正在加载收款…</span><span v-else-if="listError">收款数据未能加载，请重试</span><div v-else-if="applied.q || applied.status || applied.receipt_type">没有匹配的收款 <el-button link @click="filter(true)">清除筛选</el-button></div><div v-else>暂无收款记录 <el-button v-if="can('add')" link @click="create('DEPOSIT')">登记订金</el-button></div></template>
        </el-table></div><div class="erp-list-footer"><span>金额为人民币；已作废记录可按权限彻底删除</span><el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next" @current-change="load"/></div>
      </div>
    </template>
  </section>
  <ReceiptEditor ref="editorRef" v-model="editor" :receipt-type="receiptType" :initial-statement-id="initialStatementId" @saved="load"/>
  <AppWindowDialog v-model="detail" title="收款详情" :width="1180" :min-width="280" :minimizable="false" destroy-on-close modal-class="finance-receipt-overlay"><div v-loading="detailLoading" class="receipt-detail-body"><el-alert v-if="detailError" :title="detailError" type="error" :closable="false"/><ReceiptDetail v-if="record" :record="record"/></div><template #footer><el-button @click="detail = false">关闭</el-button><el-button v-if="record && can('void') && record.can_void" type="danger" :loading="busyRow === record.id" @click="voidRecord(record)">作废</el-button><el-button v-if="record && can('delete') && record.status === 'VOID'" type="danger" :loading="busyRow === record.id" :disabled="!!busyRow || !record.can_delete" :title="record.delete_block_reason || ''" @click="deleteRecord(record)">彻底删除</el-button></template></AppWindowDialog>
</template>
<style scoped lang="scss">
.finance-receipts .erp-list-filters label:first-child .el-input{width:250px}.finance-receipts .erp-list-filters .el-select{width:120px}.finance-receipts :deep(.el-table__header .cell){font-weight:500}.finance-receipts :deep(.el-table__body .is-right .cell){font-variant-numeric:tabular-nums;font-size:13px;font-weight:600}.more-arrow{width:12px;height:12px;fill:none;stroke:currentColor;stroke-width:1.5;margin-left:4px}.receipt-detail-body{min-height:100px}
@media(max-width:900px){.finance-receipts .erp-list-heading h1{font-size:28px!important;line-height:36px!important}.finance-receipts .erp-list-footer{height:auto;flex-wrap:wrap}}
@media(max-width:600px){.finance-receipts .erp-list-heading h1{font-size:24px!important;line-height:32px!important}.finance-receipts .erp-list-filters>label{width:100%}.finance-receipts .erp-list-filters label:first-child .el-input,.finance-receipts .erp-list-filters .el-select{width:100%}.finance-receipts .erp-list-filter-actions{margin-left:0;flex-wrap:wrap}.finance-receipts :deep(.el-table-fixed-column--right){position:static!important}}
@media(max-width:600px){.finance-receipts .erp-list-filters>label{white-space:nowrap}.finance-receipts .erp-list-filter-actions{flex:1 1 100%;min-width:0;width:100%}}
@media(prefers-reduced-motion:reduce){.finance-receipts,.finance-receipts :deep(*),.finance-receipts :deep(*::before),.finance-receipts :deep(*::after){animation:none!important;transition:none!important}}
</style>
<style>.finance-receipt-popper .danger-action{color:var(--el-color-danger)}</style>
