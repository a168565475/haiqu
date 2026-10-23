<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { DropdownInstance } from 'element-plus'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { fetchFinanceStatementReceipts } from '@/api/financeStatements'
import { deleteFinanceReceipt, fetchFinanceReceipt } from '@/api/financeReceipts'
import type { FinanceStatement } from '@/types/financeStatements'
import type { Receipt, ReceiptType } from '@/types/financeReceipts'
import ReceiptEditor from './ReceiptEditor.vue'
import ReceiptDetail from './ReceiptDetail.vue'

const props = defineProps<{ statement: FinanceStatement }>()
const emit = defineEmits<{ changed: [] }>()
const auth = useAuthStore()
const can = (action: string) => auth.user?.is_superuser === true || auth.hasPermission(`finance.${action}_receipt`)
const rows = ref<Receipt[]>([]), page = ref(1), total = ref(0), loading = ref(false), error = ref('')
const editorOpen = ref(false), receiptType = ref<ReceiptType>('DEPOSIT'), editor = ref<InstanceType<typeof ReceiptEditor>>()
const detailOpen = ref(false), detail = ref<Receipt>(), detailLoading = ref(false), detailError = ref('')
const deleting = ref('')
const menus = new Map<string, DropdownInstance>()
let pending: { id: string; action: string; row: Receipt } | undefined
let disposed = false, context = 0
let request = 0, detailRequest = 0
let controller: AbortController | undefined, detailController: AbortController | undefined
const message = (failure: unknown) => axios.isAxiosError(failure) ? failure.response?.data?.error?.message || '收款记录读取失败，请重试。' : failure instanceof Error ? failure.message : '收款记录读取失败。'
async function load() {
  if (!can('view')) return
  const token = ++request; controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''
  try {
    const result = await fetchFinanceStatementReceipts(props.statement.id, page.value, controller.signal)
    if (token !== request) return
    rows.value = result.data; total.value = result.meta.total; page.value = result.meta.page
  } catch (failure) { if (token === request && !axios.isCancel(failure)) error.value = `${rows.value.length ? '刷新失败，保留上次记录。' : ''}${message(failure)}` }
  finally { if (token === request) loading.value = false }
}
function register(type: ReceiptType) {
  if (!can('add') || props.statement.status !== 'ACTIVE') return
  receiptType.value = type; editorOpen.value = true
}
async function showDetail(row: Receipt) {
  if (!can('view')) return
  const token = ++detailRequest; detailController?.abort(); detailController = new AbortController()
  detailOpen.value = true; detail.value = undefined; detailError.value = ''; detailLoading.value = true
  try { const result = await fetchFinanceReceipt(row.id, detailController.signal); if (token === detailRequest) detail.value = result }
  catch (failure) { if (token === detailRequest && !axios.isCancel(failure)) detailError.value = message(failure) }
  finally { if (token === detailRequest) detailLoading.value = false }
}
function closeDetail() { ++detailRequest; detailController?.abort(); detailLoading.value = false }
function saved() { void load(); emit('changed') }
async function deleteRecord(row: Receipt) {
  if (!can('delete') || row.status !== 'VOID' || deleting.value) return
  const statementId = props.statement.id
  const token = context
  const isCurrent = () => !disposed && context === token && props.statement.id === statementId
  deleting.value = row.id
  try {
    const current = await fetchFinanceReceipt(row.id)
    if (!isCurrent()) return
    if (current.status !== 'VOID' || !current.can_delete) {
      ElMessage.warning(current.delete_block_reason || '仅可删除已作废收款；订金请先删除引用它的货款。')
      await load(); return
    }
    if (!current.etag) { ElMessage.error('未取得单据版本，请刷新后重试。'); return }
    try {
      await ElMessageBox.confirm(`确定彻底删除收款单 ${current.number}？本单记录及独占水单将一并删除，无法恢复。${current.receipt_type === 'DEPOSIT' ? '订金必须先删除引用它的货款。' : '引用的订金水单不随本单删除。'}`, '彻底删除收款单', { confirmButtonText: '彻底删除', cancelButtonText: '取消', type: 'warning', customClass: 'finance-receipt-confirm' })
    } catch { return }
    if (!isCurrent() || !can('delete')) return
    await deleteFinanceReceipt(current.id, current.etag)
    if (!isCurrent()) return
    if (detail.value?.id === current.id) { closeDetail(); detailOpen.value = false; detail.value = undefined }
    ElMessage.success(`收款单 ${current.number} 已彻底删除。`)
    await load()
    if (isCurrent()) emit('changed')
  } catch (failure) {
    if (!isCurrent()) return
    const httpStatus = axios.isAxiosError(failure) ? failure.response?.status : undefined
    if (httpStatus === 404) {
      ElMessage.warning('该收款单已不存在，正在刷新收款历史。')
      if (detail.value?.id === row.id) { closeDetail(); detailOpen.value = false; detail.value = undefined }
      await load()
      if (isCurrent()) emit('changed')
    } else if (httpStatus === 412) {
      ElMessage.warning('收款单已被更新，本次未删除；请核对刷新后的记录并重新确认。')
      if (detailOpen.value && detail.value?.id === row.id) await showDetail(row)
      await load()
    } else { ElMessage.error(message(failure)) }
  } finally { if (!disposed) deleting.value = '' }
}
function command(action: string, row: Receipt) {
  if (deleting.value) return
  pending = { id: row.id, action, row }; menus.get(row.id)?.handleClose()
}
async function menuVisibility(visible: boolean, id: string) {
  if (visible || pending?.id !== id) return
  const next = pending; pending = undefined; await nextTick()
  if (disposed) return
  document.querySelector<HTMLButtonElement>(`[data-history-menu="${id}"]`)?.focus({ preventScroll: true })
  if (next.action === 'delete') void deleteRecord(next.row); else void showDetail(next.row)
}
function closeMenu(id: string) { menus.get(id)?.handleClose(); document.querySelector<HTMLButtonElement>(`[data-history-menu="${id}"]`)?.focus({ preventScroll: true }) }
async function confirmLeave() {
  if (deleting.value) { ElMessage.warning('删除请求尚未完成，请稍候。'); return false }
  return editorOpen.value ? await editor.value?.confirmLeave() ?? false : true
}
function beforeUnload(event: BeforeUnloadEvent) { if (editorOpen.value || deleting.value) { event.preventDefault(); event.returnValue = '' } }
watch(() => props.statement.id, () => { ++context; closeDetail(); detailOpen.value = false; detail.value = undefined; pending = undefined; rows.value = []; total.value = 0; page.value = 1; void load() }, { immediate: true })
window.addEventListener('beforeunload', beforeUnload)
onBeforeUnmount(() => { disposed = true; ++request; ++detailRequest; controller?.abort(); detailController?.abort(); menus.clear(); pending = undefined; window.removeEventListener('beforeunload', beforeUnload) })
defineExpose({ confirmLeave })
</script>

<template>
  <section class="statement-receipts">
    <div class="history-heading"><h3>收款历史</h3><div v-if="can('add') && statement.status === 'ACTIVE'" class="history-actions"><el-button @click="register('DEPOSIT')">登记订金</el-button><el-button type="primary" @click="register('GOODS')">登记货款</el-button></div></div>
    <p v-if="!can('view')">没有收款查看权限。</p>
    <template v-else>
      <el-alert v-if="error" :title="error" type="error" :closable="false"><el-button link @click="load">重试</el-button></el-alert>
      <div v-loading="loading" class="erp-glass-list"><div class="erp-list-table-frame"><el-table :data="rows" border row-key="id">
        <el-table-column prop="number" label="收款单号" min-width="185"/><el-table-column label="类型" width="80"><template #default="{ row }">{{ row.receipt_type === 'DEPOSIT' ? '订金' : '货款' }}</template></el-table-column>
        <el-table-column prop="cash_amount" label="实际到账（元）" min-width="190" align="right"/><el-table-column prop="settled_amount" label="本单核销（元）" min-width="190" align="right"/><el-table-column prop="discount_amount" label="折让（元）" min-width="190" align="right"/>
        <el-table-column label="状态" width="90"><template #default="{ row }">{{ row.status === 'ACTIVE' ? '有效' : '已作废' }}</template></el-table-column>
        <el-table-column label="收款人" min-width="160"><template #default="{ row }">{{ row.operator.code }} / {{ row.operator.name }}</template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="{ row }"><el-dropdown :ref="(el: unknown) => { if (el) menus.set(row.id, el as DropdownInstance); else menus.delete(row.id) }" trigger="click" popper-class="finance-receipt-popper" @command="command($event, row)" @visible-change="menuVisibility($event, row.id)"><el-button link :data-history-menu="row.id" :disabled="!!deleting" @keydown.esc.stop.prevent="closeMenu(row.id)">更多<svg viewBox="0 0 12 12" aria-hidden="true" class="more-arrow"><path d="m3 4 3 3 3-3"/></svg></el-button><template #dropdown><el-dropdown-menu @keydown.esc.stop.prevent="closeMenu(row.id)"><el-dropdown-item command="detail">详情</el-dropdown-item><el-dropdown-item v-if="can('delete') && row.status === 'VOID'" command="delete" divided :disabled="!row.can_delete || !!deleting" :title="row.delete_block_reason || ''"><span class="danger-action">彻底删除</span></el-dropdown-item></el-dropdown-menu></template></el-dropdown></template></el-table-column>
        <template #empty>{{ loading ? '正在读取收款历史…' : error ? '收款历史尚未成功加载' : '尚无收款记录' }}</template>
      </el-table></div></div>
      <div class="history-footer"><span>含有效及作废记录；作废记录不计入当前余额。</span><el-pagination v-if="total > 20" v-model:current-page="page" :total="total" :page-size="20" layout="prev, pager, next" @current-change="load"/></div>
    </template>
  </section>
  <ReceiptEditor ref="editor" v-model="editorOpen" :receipt-type="receiptType" :initial-statement-id="statement.id" @saved="saved"/>
  <AppWindowDialog v-model="detailOpen" title="收款确认单详情" :width="1180" :min-width="280" :minimizable="false" destroy-on-close modal-class="finance-statement-overlay" @close="closeDetail">
    <div v-loading="detailLoading" class="history-detail"><el-alert v-if="detailError" :title="detailError" type="error" :closable="false"/><ReceiptDetail v-if="detail" :record="detail"/></div>
    <template #footer><el-button @click="detailOpen = false">关闭</el-button><el-button v-if="detail && can('delete') && detail.status === 'VOID'" type="danger" :loading="deleting === detail.id" :disabled="!!deleting || !detail.can_delete" :title="detail.delete_block_reason || ''" @click="deleteRecord(detail)">彻底删除</el-button></template>
  </AppWindowDialog>
</template>
<style scoped lang="scss">
.more-arrow{width:12px;height:12px;fill:none;stroke:currentColor;stroke-width:1.5;margin-left:4px}.danger-action{color:var(--el-color-danger)}
.statement-receipts{border-top:1px solid var(--erp-color-border);padding-top:20px;min-width:0}.history-heading,.history-actions,.history-footer{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.history-heading{justify-content:space-between;margin-bottom:12px}.history-heading h3{margin:0;font-size:15px;line-height:22px}.history-actions .el-button+.el-button{margin-left:0}.history-footer{justify-content:space-between;margin-top:12px;font-size:12px;line-height:20px;color:var(--erp-color-text-secondary)}.statement-receipts .erp-list-table-frame{flex:none}.history-detail{min-height:100px}.statement-receipts :deep(.cell){font-variant-numeric:tabular-nums}
</style>
