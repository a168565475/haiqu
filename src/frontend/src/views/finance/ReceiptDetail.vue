<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { fetchReceiptAttachment } from '@/api/financeReceipts'
import type { Receipt, ReceiptFile } from '@/types/financeReceipts'
defineProps<{ record: Receipt }>()
const preview = ref(false), url = ref(''), name = ref(''), error = ref(''), loading = ref(false)
let disposed = false
function formatDateTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString('zh-CN', { hour12: false }).replaceAll('/', '-')
}
function release() { if (url.value) URL.revokeObjectURL(url.value); url.value = '' }
async function show(receiptId: string, file: ReceiptFile) {
  loading.value = true; error.value = ''
  try {
    const blob = await fetchReceiptAttachment(receiptId, file.file_id)
    if (disposed) return
    release(); url.value = URL.createObjectURL(blob); name.value = file.original_name; preview.value = true
  } catch (err) { error.value = axios.isAxiosError(err) ? err.response?.data?.error?.message || '水单读取失败，请重试。' : '水单读取失败。' }
  finally { loading.value = false }
}
onBeforeUnmount(() => { disposed = true; release() })
</script>
<template>
  <div class="receipt-document">
    <div class="document-heading"><div><h2>{{ record.number }}</h2><p>{{ record.receipt_type === 'DEPOSIT' ? '订金' : '货款' }} · {{ formatDateTime(record.created_at) }}</p></div><el-tag :type="record.status === 'ACTIVE' ? 'success' : 'info'">{{ record.status === 'ACTIVE' ? '有效' : '已作废' }}</el-tag></div>
    <el-alert v-if="record.status === 'VOID'" :title="`作废原因：${record.void_reason}`" type="warning" :closable="false"/>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <dl class="document-facts"><div><dt>生产任务单</dt><dd>{{ record.statement_snapshot.task_number }}</dd></div><div><dt>所属对账单</dt><dd>{{ record.statement_snapshot.number }}</dd></div><div><dt>往来业务员</dt><dd>{{ record.statement_snapshot.salesperson_name || '—' }}</dd></div><div><dt>收款人</dt><dd>{{ record.operator.name || '—' }}</dd></div></dl>
    <div class="receipt-detail-workspace"><div>
      <section><h3>到账明细</h3><p v-if="!record.account_lines.length" class="note">本单仅订金核销，没有新银行到账。</p><div v-for="line in record.account_lines" :key="line.id" class="account-entry"><strong>{{ line.account_snapshot.name }}</strong><p class="note">{{ line.account_snapshot.account_type }} · {{ line.account_snapshot.category }} · {{ line.account_snapshot.code }} · {{ line.account_snapshot.currency_code }}</p><p class="full-account-number">账号 {{ line.account_snapshot.account_number }}</p><dl class="document-facts three"><div><dt>实际到账</dt><dd class="amount-value">{{ line.cash_amount }} 元</dd></div><div><dt>手续费</dt><dd class="amount-value">{{ line.fee_amount }} 元</dd></div><div><dt>到账日期</dt><dd>{{ line.received_on }}</dd></div></dl></div></section>
      <section v-if="record.allocations.length"><h3>使用的订金</h3><div v-for="allocation in record.allocations" :key="allocation.id" class="allocation-row"><span>{{ allocation.deposit_number }}</span><span>本次核销 {{ allocation.amount }} 元</span><span>{{ allocation.is_active ? '本单已使用' : '已释放' }}</span></div></section>
      <section><h3>水单</h3><p v-if="!record.attachments.length && !record.inherited_attachments.length" class="note">没有水单关联记录。</p><div v-for="file in record.attachments" :key="file.file_id" class="attachment-row"><span>{{ file.original_name }}<template v-if="['PENDING', 'INFECTED', 'FAILED'].includes(file.scan_status)"> · {{ file.scan_label }}</template></span><el-button link type="primary" :loading="loading" @click="show(record.id, file)">查看水单</el-button></div><div v-for="file in record.inherited_attachments" :key="`${file.deposit_receipt_id}-${file.file_id}`" class="attachment-row"><span>{{ file.deposit_number }} 原水单<template v-if="['PENDING', 'INFECTED', 'FAILED'].includes(file.scan_status)"> · {{ file.scan_label }}</template></span><el-button link type="primary" :loading="loading" @click="show(record.id, file)">查看原水单</el-button></div></section>
      <p class="note">生效金额不能直接修改。需要更正时，先核对作废影响，再重新登记。</p>
    </div><aside class="receipt-summary"><h3>本单金额</h3><p class="note">{{ record.status === 'VOID' ? '历史记录，不计入当前余额' : '有效收款记录' }}</p><dl class="totals"><dt>实际到账</dt><dd>{{ record.cash_amount }} 元</dd><template v-if="record.receipt_type === 'DEPOSIT'"><dt>订金金额</dt><dd>{{ record.deposit_amount }} 元</dd></template><template v-else><dt>订金抵扣</dt><dd>{{ record.allocated_deposit_amount }} 元</dd><dt>折让</dt><dd>{{ record.discount_amount }} 元</dd></template><dt class="emphasis">本单核销</dt><dd class="emphasis">{{ record.settled_amount }} 元</dd><dt>手续费（不抵债）</dt><dd>{{ record.fee_amount }} 元</dd><dt>本单登记前未付</dt><dd>{{ record.outstanding_before }} 元</dd><dt>本单登记后未付</dt><dd>{{ record.outstanding_after }} 元</dd></dl><p class="note">{{ record.receipt_type === 'DEPOSIT' ? '订金登记未减少未付，后续在本账单按需抵扣。' : '核销 = 实际到账 + 所用订金；折让不计入现金。' }}</p></aside></div>
  </div>
  <AppWindowDialog v-model="preview" :title="name" :width="900" :min-width="280" :minimizable="false" modal-class="finance-receipt-overlay" @closed="release"><img v-if="url" :src="url" :alt="name" class="receipt-slip-preview"/><template #footer><el-button @click="preview = false">关闭</el-button></template></AppWindowDialog>
</template>
<style scoped lang="scss">
.receipt-document{color:var(--erp-color-text-primary)}.document-heading{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid var(--erp-color-border);padding-bottom:12px;align-items:flex-start}.document-heading h2{margin:0;font-size:22px;line-height:30px;overflow-wrap:anywhere}.document-heading p{margin:4px 0 0}.document-heading p,.note,dt{font-size:12px;line-height:20px;color:var(--erp-color-text-secondary)}.document-facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px 24px;margin:12px 0 20px}.document-facts.three{grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:0}.document-facts dd{margin:4px 0 0;font-size:13px;line-height:22px;overflow-wrap:anywhere}.document-facts .amount-value{font-weight:600;font-variant-numeric:tabular-nums}.receipt-detail-workspace{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:28px}.receipt-detail-workspace h3{margin:0 0 12px;font-size:15px;line-height:22px}.receipt-detail-workspace section+section{margin-top:20px;padding-top:20px;border-top:1px solid var(--erp-color-border)}.account-entry{border:1px solid var(--erp-color-border);border-radius:5px;padding:14px 16px;font-size:13px}.account-entry+.account-entry{margin-top:12px}.full-account-number{font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.allocation-row,.attachment-row{display:flex;gap:16px;align-items:center;justify-content:space-between;font-size:13px;padding:10px 0;flex-wrap:wrap}.attachment-row>span{overflow-wrap:anywhere;min-width:0}.receipt-summary{border-left:1px solid var(--erp-color-border);padding-left:24px}.totals{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;margin:18px 0;font-size:12px}.totals dd{margin:0;text-align:right;white-space:nowrap;font-size:13px;font-weight:600;font-variant-numeric:tabular-nums}.totals .emphasis{font-weight:600;color:var(--erp-menu-accent);padding:14px 0;border-block:1px solid var(--erp-color-border)}.receipt-slip-preview{display:block;max-width:100%;height:auto;margin:auto}
@media(max-width:1100px){.receipt-detail-workspace{grid-template-columns:1fr}.receipt-summary{padding:20px 0 0;border-left:0;border-top:1px solid var(--erp-color-border)}}@media(max-width:800px){.document-facts{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.document-facts,.document-facts.three{grid-template-columns:1fr}.document-heading h2{font-size:17px}}
</style>
