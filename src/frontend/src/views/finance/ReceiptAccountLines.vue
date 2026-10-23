<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { fetchReceiptAccounts } from '@/api/financeReceipts'
import type { FinanceAccount } from '@/types/financeAccounts'
import type { ReceiptAccountDraft } from '@/types/financeReceipts'

const props = defineProps<{ modelValue: ReceiptAccountDraft[]; disabled?: boolean; deposit?: boolean; fieldErrors?: Record<string, string> }>()
const emit = defineEmits<{ 'update:modelValue': [value: ReceiptAccountDraft[]] }>()
const picker = ref(false)
const rows = ref<FinanceAccount[]>([])
const q = ref('')
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const error = ref('')
let replacing = ''
let generation = 0
let controller: AbortController | undefined
let disposed = false
function fieldError(index: number, field: string) { return props.fieldErrors?.[`account_lines.${index}.${field}`] || '' }
function message(err: unknown) { return axios.isAxiosError(err) ? err.response?.data?.error?.message || '账户加载失败，请重试。' : '账户加载失败，请重试。' }
async function load() {
  const request = ++generation
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''
  try {
    const result = await fetchReceiptAccounts({ q: q.value, page: page.value, page_size: 20 }, controller.signal)
    if (request !== generation || disposed) return
    rows.value = result.data; total.value = result.meta.total
  } catch (err) {
    if (request === generation && !disposed && !axios.isCancel(err)) error.value = message(err)
  } finally { if (request === generation && !disposed) loading.value = false }
}
function open(key = '') { replacing = key; picker.value = true; page.value = 1; q.value = ''; rows.value = []; void load() }
function select(account: FinanceAccount) {
  if (props.disabled) return
  if (replacing) emit('update:modelValue', props.modelValue.map(line => line.key === replacing ? { ...line, account, account_id: account.id, account_etag: account.etag } : line))
  else emit('update:modelValue', [...props.modelValue, { key: crypto.randomUUID(), account, account_id: account.id, account_etag: account.etag, cash_amount: '', fee_amount: '0.00', received_on: '' }])
  picker.value = false
}
function change(index: number, field: 'cash_amount' | 'fee_amount' | 'received_on', value: string | null) {
  emit('update:modelValue', props.modelValue.map((line, i) => i === index ? { ...line, [field]: value || '' } : line))
}
onBeforeUnmount(() => { disposed = true; ++generation; controller?.abort() })
</script>

<template>
  <section class="receipt-section">
    <div class="receipt-section-heading"><div><h3>到账明细</h3><p>{{ deposit ? '订金金额与实际到账同步。' : '实际到账用于核销，手续费单独记录。' }}</p></div><el-button :disabled="disabled" @click="open()">添加账户</el-button></div>
    <p v-if="!modelValue.length" class="receipt-empty">尚未添加到账账户</p>
    <p v-if="fieldErrors?.account_lines" class="receipt-field-error" role="alert">{{ fieldErrors.account_lines }}</p>
    <div v-for="(line, index) in modelValue" :key="line.key" class="account-entry">
      <div class="account-entry-heading"><div><strong>{{ line.account.name }}</strong><el-button link type="primary" :disabled="disabled" @click="open(line.key)">更换账户</el-button><p>{{ line.account.account_type }} · {{ line.account.category }} · {{ line.account.code }} · {{ line.account.currency_code }}</p></div><el-button link type="danger" :disabled="disabled" @click="emit('update:modelValue', modelValue.filter(item => item.key !== line.key))">移除</el-button></div>
      <div class="account-number-line"><span>账号</span><strong>{{ line.account.account_number }}</strong></div>
      <p v-if="fieldError(index, 'account_id') || fieldError(index, 'account_etag') || fieldErrors?.[`account_lines.${index}`]" class="receipt-field-error" role="alert">{{ fieldError(index, 'account_id') || fieldError(index, 'account_etag') || fieldErrors?.[`account_lines.${index}`] }}</p>
      <div class="account-entry-fields">
        <el-form-item :label="deposit ? '实际到账 / 订金（元）' : '实际到账（元）'" required :error="fieldError(index, 'cash_amount')"><el-input :model-value="line.cash_amount" :aria-label="`第${index + 1}行实际到账`" :aria-invalid="!!fieldError(index, 'cash_amount')" :aria-describedby="fieldError(index, 'cash_amount') ? `${line.key}-cash-error` : undefined" inputmode="decimal" maxlength="23" :disabled="disabled" @update:model-value="change(index, 'cash_amount', $event)"/><template #error="{ error }"><div :id="`${line.key}-cash-error`" class="el-form-item__error" role="alert">{{ error }}</div></template></el-form-item>
        <el-form-item label="手续费（元）" :error="fieldError(index, 'fee_amount')"><el-input :model-value="line.fee_amount" :aria-label="`第${index + 1}行手续费`" :aria-invalid="!!fieldError(index, 'fee_amount')" :aria-describedby="fieldError(index, 'fee_amount') ? `${line.key}-fee-error` : undefined" inputmode="decimal" maxlength="23" :disabled="disabled" @update:model-value="change(index, 'fee_amount', $event)"/><template #error="{ error }"><div :id="`${line.key}-fee-error`" class="el-form-item__error" role="alert">{{ error }}</div></template></el-form-item>
        <el-form-item label="到账日期" required :error="fieldError(index, 'received_on')"><el-date-picker :model-value="line.received_on" :aria-label="`第${index + 1}行到账日期`" :aria-invalid="!!fieldError(index, 'received_on')" :aria-describedby="fieldError(index, 'received_on') ? `${line.key}-date-error` : undefined" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" :disabled="disabled" popper-class="finance-receipt-popper" @update:model-value="change(index, 'received_on', $event)"/><template #error="{ error }"><div :id="`${line.key}-date-error`" class="el-form-item__error" role="alert">{{ error }}</div></template></el-form-item>
      </div>
    </div>
  </section>
  <AppWindowDialog v-model="picker" title="选择收款账户" :width="1080" :min-width="280" :minimizable="false" destroy-on-close modal-class="finance-receipt-overlay">
    <div class="receipt-account-picker"><el-input v-model="q" placeholder="账户编码、名称、账号" aria-label="搜索收款账户" @keyup.enter="page = 1; load()"/><el-button @click="page = 1; load()">查询</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-table v-loading="loading" :data="rows" border class="receipt-picker-table">
      <el-table-column prop="code" label="编码" min-width="120"/><el-table-column prop="name" label="账户名称" min-width="180"/>
      <el-table-column prop="category" label="类别" min-width="90"/><el-table-column prop="account_number" label="完整账号" min-width="220"/>
      <el-table-column label="操作" width="80"><template #default="{ row }"><el-button link type="primary" :disabled="!!error || loading" @click="select(row)">选择</el-button></template></el-table-column>
      <template #empty>{{ error ? '账户未能加载，请重试' : loading ? '正在加载账户…' : '暂无可用的人民币账户' }}</template>
    </el-table>
    <template #footer><span class="receipt-picker-note">仅启用的人民币账户</span><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load"/><el-button @click="picker = false">关闭</el-button></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.receipt-section{container-type:inline-size}
.receipt-section-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:12px}.receipt-section h3{margin:0;font-size:15px;line-height:22px;font-weight:600}.receipt-section-heading p{margin:4px 0 0;font-size:12px;line-height:20px;color:var(--erp-color-text-secondary)}
.receipt-empty{padding:14px 16px;border-radius:5px;background:var(--erp-input-readonly-background);font-size:12px;color:var(--erp-color-text-secondary)}
.account-entry{border:1px solid var(--erp-color-border);border-radius:5px;padding:14px 16px}.account-entry+.account-entry{margin-top:12px}.account-entry-heading{display:flex;justify-content:space-between;gap:12px}.account-entry-heading strong{font-size:13px}.account-entry-heading p{margin:5px 0 0;font-size:12px;color:var(--erp-color-text-secondary)}.account-entry-heading .el-button{margin-left:12px}
.account-number-line{display:flex;gap:12px;margin:8px 0 12px;font-size:12px}.account-number-line span{color:var(--erp-color-text-secondary)}.account-number-line strong{font-size:14px;font-weight:500;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
.account-entry-fields{display:grid;grid-template-columns:1.2fr .8fr 1fr;gap:16px}.account-entry-fields :deep(.el-form-item){margin-bottom:0;min-width:0}.account-entry-fields :deep(.el-input),.account-entry-fields :deep(.el-date-editor){width:100%}.account-entry-fields :deep(.el-form-item__label){font-size:12px!important}
.account-entry-fields :deep(.el-form-item__error){position:static;line-height:18px;padding-top:4px}.receipt-field-error{color:var(--el-color-danger);font-size:12px;line-height:18px}
.receipt-account-picker{display:flex;gap:10px;margin-bottom:14px}.receipt-account-picker .el-input{max-width:300px}.receipt-picker-note{margin-right:auto;font-size:12px;color:var(--erp-color-text-secondary)}
@media(max-width:600px){.account-entry-fields{grid-template-columns:1fr}.account-entry{padding:12px}.account-entry-heading,.receipt-section-heading{flex-wrap:wrap}.account-number-line strong{font-size:13px}}
@container(max-width:600px){.account-entry-fields{grid-template-columns:1fr}.account-entry{padding:12px}.account-entry-heading,.receipt-section-heading{flex-wrap:wrap}.account-number-line strong{font-size:13px}}
</style>
