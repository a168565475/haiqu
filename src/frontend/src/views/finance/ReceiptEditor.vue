<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { createFinanceReceipt, fetchReceiptAttachment } from '@/api/financeReceipts'
import { fetchFinanceStatement } from '@/api/financeStatements'
import type { FinanceSourceTask, FinanceStatement } from '@/types/financeStatements'
import type { Receipt, ReceiptAccountDraft, ReceiptFile, ReceiptInput, ReceiptType, ReceiptUpload } from '@/types/financeReceipts'
import ReceiptAccountLines from './ReceiptAccountLines.vue'
import ReceiptUploads from './ReceiptUploads.vue'
import ReceiptSourceSelect from './ReceiptSourceSelect.vue'
import GoodsReceiptFields from './GoodsReceiptFields.vue'
import { receiptCents, receiptMoney, receiptSum } from './receiptAmounts'

const props = defineProps<{ modelValue: boolean; receiptType: ReceiptType; initialStatementId?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [value: Receipt] }>()
const auth = useAuthStore()
const task = ref<{ id: string; task_number: string }>()
const statement = ref<FinanceStatement | null>(null)
const latest = ref<FinanceStatement>()
const accountLines = ref<ReceiptAccountDraft[]>([])
const uploads = ref<ReceiptUpload[]>([])
const uploadRef = ref<InstanceType<typeof ReceiptUploads>>()
const uploadBusy = ref(false), uploadPending = ref(false), submitting = ref(false), loading = ref(false)
const error = ref(''), uncertain = ref(false), conflict = ref(false)
const fieldErrors = ref<Record<string, string>>({})
const depositIds = ref<string[]>([]), discountAmount = ref('0.00'), pureDeposit = ref(false), goodsValid = ref(false)
const goodsSummary = ref({ settledAmount: '0.00', outstandingAfter: '—' })
const selector = ref(false), selectorMode = ref<'task' | 'statement'>('task')
const preview = ref(false), previewUrl = ref(''), previewName = ref('')
let generation = 0
let controller: AbortController | undefined
let creationKey = crypto.randomUUID()
let submittedBody: ReceiptInput | undefined
let submittedEtag = ''
let disposed = false
let previewRequest = 0
const cash = computed(() => receiptSum(accountLines.value.map(line => line.cash_amount)))
const fees = computed(() => receiptSum(accountLines.value.map(line => line.fee_amount)))
const dirty = computed(() => !!task.value || !!statement.value || accountLines.value.length > 0 || uploads.value.length > 0 || uploadPending.value || depositIds.value.length > 0 || discountAmount.value !== '0.00' || pureDeposit.value)
const disabled = computed(() => submitting.value || uncertain.value || loading.value || uploadBusy.value)
const canAdd = computed(() => auth.user?.is_superuser || auth.hasPermission('finance.add_receipt'))
const accountInputs = computed(() => accountLines.value.map(({ account_id, account_etag, cash_amount, fee_amount, received_on }) => ({ account_id, account_etag, cash_amount, fee_amount, received_on })))
const afterDeposit = computed(() => {
  const current = receiptCents(statement.value?.available_deposit_amount || '')
  const amount = receiptCents(cash.value || '')
  return current === null || amount === null ? '—' : receiptMoney(current + amount)
})
const afterBank = computed(() => {
  const current = receiptCents(statement.value?.bank_received_amount || '')
  const amount = receiptCents(cash.value || '')
  return current === null || amount === null ? '—' : receiptMoney(current + amount)
})
function message(err: unknown) { return axios.isAxiosError(err) ? err.response?.data?.error?.message || '请求结果尚未确认，请重试。' : err instanceof Error ? err.message : '请求失败，请重试。' }
function resetFunds() { hidePreview(); fieldErrors.value = {}; accountLines.value = []; uploads.value = []; uploadPending.value = false; depositIds.value = []; discountAmount.value = '0.00'; pureDeposit.value = false; error.value = ''; conflict.value = false; latest.value = undefined }
function readFieldErrors(value: unknown, path = '', result: Record<string, string> = {}) {
  if (typeof value === 'string') result[path] = value
  else if (Array.isArray(value) && value.every(item => typeof item === 'string')) result[path] = value.join('；')
  else if (value && typeof value === 'object') {
    for (const [key, item] of Object.entries(value)) readFieldErrors(item, path ? `${path}.${key}` : key, result)
  }
  return result
}
watch(accountLines, (next, previous) => {
  fieldErrors.value = Object.fromEntries(Object.entries(fieldErrors.value).filter(([path]) => {
    if (path === 'account_lines') return false
    const match = /^account_lines\.(\d+)(?:\.(\w+))?$/.exec(path)
    if (!match) return true
    const before = previous[Number(match[1])], after = next[Number(match[1])]
    if (!before || !after || before.key !== after.key || before.account_id !== after.account_id || before.account_etag !== after.account_etag) return false
    const field = match[2] as keyof ReceiptAccountDraft | undefined
    return field ? before[field] === after[field] : before === after
  }))
})
async function confirmDiscard(text: string) {
  try { await ElMessageBox.confirm(text, '确认放弃当前草稿', { confirmButtonText: '放弃并继续', cancelButtonText: '继续填写', customClass: 'finance-receipt-confirm' }); return true } catch { return false }
}
async function cleanUploads() { return (!uploads.value.length && !uploadPending.value) || await uploadRef.value?.discardAll() === true }
async function switchAllowed(confirm = dirty.value) {
  if (disabled.value) return false
  if (confirm && !await confirmDiscard('更换来源会清理当前到账、手续费、日期、订金抵扣、折让及新水单。是否继续？')) return false
  return cleanUploads()
}
function openSource(mode: 'task' | 'statement') { if (!disabled.value && (mode === 'task' || task.value)) { selectorMode.value = mode; selector.value = true } }
async function chooseTask(value: FinanceSourceTask) {
  if (value.id === task.value?.id) { selector.value = false; return }
  if (!await switchAllowed()) return
  ++generation; controller?.abort(); resetFunds(); statement.value = null; task.value = value; selector.value = false
}
async function chooseStatement(value: FinanceStatement) {
  if (value.id === statement.value?.id) { selector.value = false; return }
  if (value.production_task_id !== task.value?.id) { error.value = '所选对账单不属于当前生产任务。'; return }
  if (!await switchAllowed(!!statement.value || accountLines.value.length > 0 || uploads.value.length > 0)) return
  resetFunds(); statement.value = value; selector.value = false
}
async function setPureDeposit(value: boolean) {
  if (disabled.value || value === pureDeposit.value) return
  if (value && (accountLines.value.length || uploads.value.length || uploadPending.value)) {
    if (!await confirmDiscard('仅订金核销将移除本次到账及新水单，原订金水单继续保留。是否继续？') || !await cleanUploads()) return
    accountLines.value = []; uploads.value = []
  }
  pureDeposit.value = value
}
async function close(done?: () => void) {
  if (disabled.value || uncertain.value) { ElMessage.warning('请求尚未完成，请先核对原提交结果。'); return false }
  if (dirty.value && !await confirmDiscard('当前收款尚未保存。放弃后将清理本草稿未绑定的水单。')) return false
  if (!await cleanUploads()) return false
  ++generation; controller?.abort(); hidePreview(); if (done) done(); else emit('update:modelValue', false)
  return true
}
async function loadInitial(id: string) {
  const request = ++generation; controller?.abort(); controller = new AbortController(); loading.value = true
  try {
    const value = await fetchFinanceStatement(id, controller.signal)
    if (request !== generation || disposed) return
    if (value.status !== 'ACTIVE') throw new Error('已作废对账单不能登记收款。')
    statement.value = value; task.value = { id: value.production_task_id, task_number: value.task_number }
  } catch (err) { if (request === generation && !axios.isCancel(err)) error.value = message(err) }
  finally { if (request === generation) loading.value = false }
}
async function compareLatest() {
  if (!statement.value || disabled.value) return
  loading.value = true
  try { latest.value = await fetchFinanceStatement(statement.value.id) } catch (err) { error.value = message(err) } finally { loading.value = false }
}
function acceptLatest() {
  if (!latest.value || latest.value.status !== 'ACTIVE') return
  statement.value = latest.value; latest.value = undefined; conflict.value = false; error.value = ''
}
function validate() {
  if (!statement.value || !task.value || statement.value.production_task_id !== task.value.id) return '请选择生产任务及其一张有效对账单。'
  if (uploadPending.value) return '请先重试原上传，确认水单状态。'
  if (uploads.value.some(item => item.status !== 'UNBOUND')) return '存在待清理或不可绑定水单，请先处理。'
  for (const [index, line] of accountLines.value.entries()) {
    const amount = receiptCents(line.cash_amount)
    if (amount === null || amount <= 0n) return `第 ${index + 1} 行实际到账须大于零，最多两位小数。`
    if (receiptCents(line.fee_amount) === null) return `第 ${index + 1} 行手续费格式不正确。`
    if (!/^\d{4}-\d{2}-\d{2}$/.test(line.received_on)) return `请填写第 ${index + 1} 行到账日期。`
  }
  if ((receiptCents(cash.value || '') || 0n) > 0n && !uploads.value.length) return '有新到账必须上传水单。'
  if (props.receiptType === 'DEPOSIT') {
    if (!accountLines.value.length) return '订金必须有实际到账。'
    const after = receiptCents(afterDeposit.value), outstanding = receiptCents(statement.value.outstanding_amount)
    if (after === null || outstanding === null || after > outstanding) return '已有未用订金与本笔订金超过当前未付，请核对实际收款。'
  } else if (!goodsValid.value) return '请核对货款到账、整笔订金、折让及水单。'
  return ''
}
async function save() {
  if (submitting.value || loading.value || uploadBusy.value || !canAdd.value) return
  if (!uncertain.value) {
    error.value = validate(); if (error.value || !statement.value) return
    submittedBody = props.receiptType === 'DEPOSIT'
      ? { receipt_type: 'DEPOSIT', statement_id: statement.value.id, account_lines: structuredClone(accountInputs.value), upload_ids: uploads.value.map(item => item.id) }
      : { receipt_type: 'GOODS', statement_id: statement.value.id, account_lines: structuredClone(accountInputs.value), upload_ids: uploads.value.map(item => item.id), deposit_ids: [...depositIds.value], discount_amount: discountAmount.value }
    submittedEtag = statement.value.etag
  }
  if (!submittedBody) return
  submitting.value = true; error.value = ''; fieldErrors.value = {}; conflict.value = false
  try {
    const result = await createFinanceReceipt(submittedBody, creationKey, submittedEtag)
    uncertain.value = false; hidePreview(); emit('saved', result); emit('update:modelValue', false)
    ElMessage.success(result.status === 'VOID' ? '原提交已核实，该收款现已作废。' : '收款已保存生效。')
  } catch (err) {
    error.value = message(err)
    if (axios.isAxiosError(err)) fieldErrors.value = readFieldErrors(err.response?.data?.error?.field_errors)
    const status = axios.isAxiosError(err) ? err.response?.status : undefined
    uncertain.value = !status || status >= 500
    conflict.value = status === 409 || status === 412
    if (!uncertain.value) creationKey = crypto.randomUUID()
  } finally { submitting.value = false }
}
async function showAttachment(receiptId: string, file: ReceiptFile) {
  if (!props.modelValue || !statement.value) return
  hidePreview()
  const request = previewRequest, source = statement.value.id
  const current = () => !disposed && props.modelValue && request === previewRequest && source === statement.value?.id
  try {
    const blob = await fetchReceiptAttachment(receiptId, file.file_id)
    if (!current()) return
    previewUrl.value = URL.createObjectURL(blob); previewName.value = file.original_name; preview.value = true
  } catch (err) { if (current()) error.value = message(err) }
}
function releasePreview() { if (previewUrl.value) URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }
function hidePreview() { ++previewRequest; preview.value = false; releasePreview() }
watch(() => props.modelValue, value => {
  ++generation; controller?.abort(); hidePreview()
  loading.value = false
  if (value) {
    task.value = undefined; statement.value = null; resetFunds(); creationKey = crypto.randomUUID(); submittedBody = undefined; uncertain.value = false
    if (props.initialStatementId) void loadInitial(props.initialStatementId)
  }
}, { immediate: true })
onBeforeUnmount(() => { disposed = true; ++generation; controller?.abort(); hidePreview() })
defineExpose({ confirmLeave: () => props.modelValue ? close() : Promise.resolve(true) })
</script>

<template>
  <AppWindowDialog :model-value="modelValue" :title="receiptType === 'DEPOSIT' ? '登记订金' : '登记货款'" :width="1180" :min-width="280" :minimizable="false" :before-close="close" destroy-on-close modal-class="finance-receipt-overlay" @update:model-value="emit('update:modelValue', $event)">
    <el-form label-position="top" class="receipt-editor" :disabled="disabled" @submit.prevent="save">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
      <el-alert v-if="uncertain" title="提交结果尚未确认，草稿和原提交标识已保留。请重试原提交，确认结果后再继续。" type="warning" :closable="false"/>
      <div v-loading="loading" class="receipt-source">
        <div class="source-fields"><el-form-item label="生产任务单" required><div class="source-input"><el-input :model-value="task?.task_number || ''" readonly placeholder="请选择生产任务"/><el-button :disabled="disabled" @click="openSource('task')">选择</el-button></div></el-form-item><el-form-item label="所属对账单" required><div class="source-input"><el-input :model-value="statement?.number || ''" readonly placeholder="请选择该任务的有效对账单"/><el-button :disabled="disabled || !task" @click="openSource('statement')">选择</el-button></div></el-form-item></div>
        <div class="source-meta"><span>业务员 <strong>{{ statement ? `${statement.salesperson.code} / ${statement.salesperson.name}` : '随对账单带出' }}</strong></span><span>收款人 <strong>{{ auth.user?.employee?.display_name || '当前员工' }}</strong></span><span>单号、记录时间由保存时生成</span></div>
      </div>
      <template v-if="receiptType === 'DEPOSIT'"><div class="receipt-workspace"><div class="receipt-entry"><ReceiptAccountLines v-model="accountLines" deposit :field-errors="fieldErrors" :disabled="disabled || !statement"/><p class="deposit-sync">订金合计 <strong>{{ cash || '—' }} 元</strong> = 收款金额合计 <strong>{{ cash || '—' }} 元</strong></p><ReceiptUploads ref="uploadRef" v-model="uploads" :statement-id="statement?.id || ''" :disabled="submitting || uncertain || !statement" @busy="uploadBusy = $event" @pending="uploadPending = $event"/></div><aside class="receipt-summary"><h3>订金登记结果</h3><p>订金先到账，本次不减少未付。</p><dl class="totals"><dt>对账金额</dt><dd>{{ statement?.amount || '—' }} 元</dd><dt>当前未付</dt><dd>{{ statement?.outstanding_amount || '—' }} 元</dd><dt class="emphasis">本次订金 / 到账</dt><dd class="emphasis">{{ cash || '—' }} 元</dd><dt>可用订金（登记后）</dt><dd>{{ afterDeposit }} 元</dd><dt>累计银行到账（本次后）</dt><dd>{{ afterBank }} 元</dd><dt>手续费（不抵债）</dt><dd>{{ fees || '—' }} 元</dd></dl><p>保存后增加本账单的可用订金，货款核销时整笔选择。</p></aside></div></template>
      <GoodsReceiptFields v-else :key="statement?.id || 'empty'" :statement="statement" :account-lines="accountInputs" :upload-ids="uploads.map(item => item.id)" v-model:deposit-ids="depositIds" v-model:discount-amount="discountAmount" :pure-deposit="pureDeposit" :disabled="disabled" @update:pure-deposit="setPureDeposit" @validity="goodsValid = $event" @summary="goodsSummary = $event" @preview="showAttachment" @refresh="compareLatest">
        <template #accounts><ReceiptAccountLines v-if="!pureDeposit" v-model="accountLines" :field-errors="fieldErrors" :disabled="disabled || !statement"/><p v-else class="receipt-note">仅使用本账单订金，无需新增到账账户行。</p></template>
        <template #uploads><ReceiptUploads v-show="!pureDeposit" ref="uploadRef" v-model="uploads" :statement-id="statement?.id || ''" :disabled="submitting || uncertain || !statement" @busy="uploadBusy = $event" @pending="uploadPending = $event"/><p v-if="pureDeposit" class="receipt-note">沿用所选订金的原水单，无需新上传。</p></template>
      </GoodsReceiptFields>
      <el-button v-if="conflict" :disabled="disabled" @click="compareLatest">查看最新账单并比较</el-button>
      <div v-if="latest" class="latest-statement"><strong>最新账单：{{ latest.number }} · {{ latest.status === 'ACTIVE' ? '有效' : '已作废' }}</strong><p>当前未付 {{ latest.outstanding_amount }} 元 · 可用订金 {{ latest.available_deposit_amount }} 元；当前输入保留。</p><el-button :disabled="latest.status !== 'ACTIVE'" @click="acceptLatest">已比较，使用最新版本继续核对</el-button></div>
    </el-form>
    <template #footer><div class="receipt-footer"><span>{{ receiptType === 'DEPOSIT' ? '订金' : '本次核销' }} {{ receiptType === 'DEPOSIT' ? cash || '—' : goodsSummary.settledAmount }} 元 · {{ receiptType === 'DEPOSIT' ? '登记后未付' : '核销后未付' }} <strong>{{ receiptType === 'DEPOSIT' ? statement?.outstanding_amount || '—' : goodsSummary.outstandingAfter }} 元</strong></span><el-button :disabled="disabled" @click="close()">取消</el-button><el-button type="primary" :loading="submitting" :disabled="loading || uploadBusy || !canAdd" @click="save">{{ uncertain ? '重试原提交' : '保存并生效' }}</el-button></div></template>
  </AppWindowDialog>
  <ReceiptSourceSelect v-model="selector" :mode="selectorMode" :task-id="task?.id" @task="chooseTask" @statement="chooseStatement"/>
  <AppWindowDialog :model-value="preview" :title="previewName" :width="900" :min-width="280" :minimizable="false" modal-class="finance-receipt-overlay" @update:model-value="hidePreview"><img v-if="previewUrl" :src="previewUrl" :alt="previewName" class="receipt-slip-preview"/><template #footer><el-button @click="hidePreview">关闭</el-button></template></AppWindowDialog>
</template>

<style scoped lang="scss">
.receipt-editor{container-type:inline-size}
.receipt-editor{color:var(--erp-color-text-primary)}.receipt-editor>.el-alert{margin-bottom:12px}.receipt-source{border-bottom:1px solid var(--erp-color-border);padding-bottom:16px}.source-fields{display:grid;grid-template-columns:1fr 1fr;gap:20px}.source-fields :deep(.el-form-item){margin-bottom:10px;min-width:0}.source-input{display:flex;width:100%;gap:8px}.source-meta{display:flex;gap:12px 24px;flex-wrap:wrap;font-size:12px;line-height:20px;color:var(--erp-color-text-secondary)}.source-meta strong{margin-left:8px;font-weight:500;color:var(--erp-color-text-primary)}
.receipt-workspace{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:28px;padding-top:20px;align-items:start}.receipt-entry{min-width:0}.receipt-summary{position:sticky;top:0;border-left:1px solid var(--erp-color-border);padding-left:24px;min-width:0}.receipt-summary h3{margin:0;font-size:15px;line-height:22px;font-weight:600}.receipt-summary p,.deposit-sync,.receipt-note{font-size:12px;line-height:20px;color:var(--erp-color-text-secondary)}.deposit-sync strong{color:var(--erp-color-text-primary)}.totals{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px 12px;margin:18px 0;font-size:12px;line-height:20px}.totals dt{color:var(--erp-color-text-secondary)}.totals dd{margin:0;text-align:right;font-size:13px;font-weight:500;white-space:nowrap;font-variant-numeric:tabular-nums}.totals .emphasis{padding:14px 0;border-block:1px solid var(--erp-color-border);margin:4px 0;color:var(--erp-menu-accent);font-weight:600}.totals dd.emphasis{font-size:20px}
.receipt-footer{display:flex;gap:8px;align-items:center;flex-wrap:wrap;width:100%;font-size:12px;color:var(--erp-color-text-secondary)}.receipt-footer>span{margin-right:auto}.receipt-footer .el-button{margin:0}.receipt-footer strong{color:var(--erp-menu-accent)}.latest-statement{margin-top:16px;padding-top:16px;border-top:1px solid var(--erp-color-border);font-size:13px}.receipt-slip-preview{display:block;max-width:100%;height:auto;margin:auto}
@media(max-width:1100px){.receipt-workspace{grid-template-columns:1fr}.receipt-summary{position:static;padding:20px 0 0;border-left:0;border-top:1px solid var(--erp-color-border)}}
@media(max-width:600px){.source-fields{grid-template-columns:1fr;gap:0}.source-meta{display:grid;gap:6px}.receipt-footer>span{flex-basis:100%}.totals{grid-template-columns:minmax(0,1fr) auto}}
@container(max-width:900px){.receipt-workspace{grid-template-columns:1fr}.receipt-summary{position:static;padding:20px 0 0;border-left:0;border-top:1px solid var(--erp-color-border)}}
@container(max-width:600px){.source-fields{grid-template-columns:1fr;gap:0}.source-meta{display:grid;gap:6px}}
</style>
<style>
@media(prefers-reduced-motion:reduce){.finance-receipt-overlay *,.finance-receipt-overlay *::before,.finance-receipt-overlay *::after,.finance-receipt-popper *,.finance-receipt-confirm *{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
</style>
