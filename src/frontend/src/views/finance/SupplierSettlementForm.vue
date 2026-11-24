<script setup lang="ts">
import { computed, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { isAxiosError } from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import {
  createSupplierSettlement, fetchEligibleSupplierPayables, fetchEligibleSupplierPayments, fetchSupplierPaymentOptions,
} from '@/api/financeSupplierLedger'
import { fetchStandalonePaymentOptions, registerStandalonePayment } from '@/api/financeSupplierPayments'
import type {
  CreateSupplierOffset, CreateSupplierPayment, EligibleSupplierPayable, EligibleSupplierPayment,
  PaymentAccountOption, SupplierLedgerOption, SupplierSettlementDraft,
} from '@/types/financeSupplierLedger'
import type { SupplierPaymentApplicationContext } from '@/types/financeSupplierPayments'
import { createClientUuid } from '@/utils/clientUuid'
import { amountInCents, ledgerMoney, ledgerRequestError, ledgerToday, moneyFromCents } from './supplierLedgerDisplay'

const props = defineProps<{
  draft: SupplierSettlementDraft
  supplierId?: string
  standalone?: boolean
  application?: SupplierPaymentApplicationContext
}>()
const emit = defineEmits<{ close: []; saved: [] }>()
const paymentMode = props.draft.kind === 'payments'
const originalPayment = props.draft.kind === 'payments' ? props.draft.previous : undefined
const originalOffset = props.draft.kind === 'offsets' ? props.draft.previous : undefined
const replacesId = props.draft.previous?.id
const paymentForm = reactive<CreateSupplierPayment>({
  supplier_id: originalPayment?.supplier_id ?? props.application?.supplier_id ?? props.supplierId ?? '',
  account_id: originalPayment?.account_id ?? '',
  nature: originalPayment?.nature ?? 'GOODS',
  paid_on: originalPayment?.business_date ?? ledgerToday(),
  payee: originalPayment?.payee ?? props.application?.payee ?? '',
  amount: originalPayment?.amount ?? '',
  voucher: originalPayment?.voucher ?? '',
})
const offsetDay = ref(originalOffset?.business_date ?? ledgerToday())
const paymentId = ref('')
const suppliers = shallowRef<SupplierLedgerOption[]>([])
const accounts = shallowRef<PaymentAccountOption[]>([])
const payments = shallowRef<EligibleSupplierPayment[]>([])
const payables = shallowRef<EligibleSupplierPayable[]>([])
const allocations = ref<Record<string, string>>({})
const payment = computed(() => payments.value.find(item => item.id === paymentId.value))
const account = computed(() => accounts.value.find(item => item.id === paymentForm.account_id))
const busy = ref(false)
const uncertain = ref(false)
const loadingOptions = ref(false)
const loadingPayables = ref(false)
const error = ref('')
const refreshRequired = ref(false)
const refreshPayables = ref(0)
let seededOffset = false
let key = createClientUuid()
let submitted: { body: CreateSupplierPayment | CreateSupplierOffset; etag: string } | undefined

const allocatedCents = computed(() => Object.values(allocations.value).reduce((sum, amount) => sum + (amountInCents(amount) ?? 0n), 0n))
const allocatedText = computed(() => moneyFromCents(allocatedCents.value))

async function loadOptions() {
  error.value = ''
  refreshRequired.value = false
  loadingOptions.value = true
  try {
    if (paymentMode) {
      const result = await (props.standalone ? fetchStandalonePaymentOptions() : fetchSupplierPaymentOptions())
      suppliers.value = result.suppliers
      accounts.value = result.accounts
      if (!suppliers.value.some(item => item.id === paymentForm.supplier_id)) paymentForm.supplier_id = ''
      if (!account.value) paymentForm.account_id = ''
    } else {
      payments.value = await fetchEligibleSupplierPayments()
      if (!paymentId.value && originalOffset && !seededOffset
        && payments.value.some(item => item.id === originalOffset.payment_id)) {
        paymentId.value = originalOffset.payment_id
      } else if (!payment.value) {
        paymentId.value = ''
      } else {
        refreshPayables.value++
      }
    }
  } catch (cause) {
    error.value = ledgerRequestError(cause, '选项加载失败，请重试。')
    refreshRequired.value = true
  } finally {
    loadingOptions.value = false
  }
}

watch([paymentId, refreshPayables], async ([id], [previousId], cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  if (id !== previousId) allocations.value = {}
  payables.value = []
  loadingPayables.value = !!id
  if (!id) return
  try {
    payables.value = await fetchEligibleSupplierPayables(id, controller.signal)
    const validIds = new Set(payables.value.map(row => row.id))
    if (!seededOffset && id === originalOffset?.payment_id) {
      allocations.value = Object.fromEntries(originalOffset.allocations
        .filter(row => validIds.has(row.payable_id)).map(row => [row.payable_id, row.amount]))
    } else {
      allocations.value = Object.fromEntries(Object.entries(allocations.value).filter(([rowId]) => validIds.has(rowId)))
    }
    seededOffset = true
  } catch (cause) {
    if (controller.signal.aborted) return
    error.value = ledgerRequestError(cause, '待抵应付加载失败，请刷新选项。')
    refreshRequired.value = true
  } finally {
    if (!controller.signal.aborted) loadingPayables.value = false
  }
})

function preparePayment() {
  const payee = paymentForm.payee.trim()
  const voucher = paymentForm.voucher.trim()
  if (!paymentForm.supplier_id || !account.value || !paymentForm.paid_on || !payee || !voucher) {
    error.value = '请补全供应商、日期、账户、收款人和付款凭证编号。'
    return
  }
  const amount = paymentForm.amount.trim()
  const cents = amountInCents(amount)
  if (!cents) {
    error.value = '实付金额须大于 0，最多两位小数。'
    return
  }
  if (props.application && cents > amountInCents(props.application.remaining_amount, 22)!) {
    error.value = '实付金额不能超过申请剩余金额。'
    return
  }
  return { body: { ...paymentForm, payee, voucher, amount, replaces_id: replacesId }, etag: account.value.etag }
}

function prepareOffset() {
  if (!payment.value || !offsetDay.value) {
    error.value = '请选择付款单和抵账日期。'
    return
  }
  const rows = payables.value.filter(row => allocations.value[row.id]?.trim())
  const inputs = rows.map(row => ({ payable_id: row.id, amount: allocations.value[row.id]!.trim() }))
  if (!inputs.length || inputs.some(row => !amountInCents(row.amount))) {
    error.value = '至少填写一笔大于 0 的抵账金额，最多两位小数。'
    return
  }
  if (allocatedCents.value > amountInCents(payment.value.available_amount)!
    || rows.some(row => amountInCents(allocations.value[row.id]!.trim())! > amountInCents(row.available_amount)!)) {
    error.value = '抵账金额超出付款可用额或应付未抵额。'
    return
  }
  if (offsetDay.value < payment.value.business_date || rows.some(row => offsetDay.value < row.confirmed_date)) {
    error.value = '抵账日期不得早于付款日期或应付确认日期。'
    return
  }
  return {
    body: { payment_id: paymentId.value, offset_on: offsetDay.value, allocations: inputs, replaces_id: replacesId },
    etag: payment.value.etag,
  }
}

async function save() {
  if (busy.value || loadingOptions.value || loadingPayables.value || refreshRequired.value) return
  error.value = ''
  submitted ??= paymentMode ? preparePayment() : prepareOffset()
  if (!submitted) return
  busy.value = true
  try {
    const { body, etag } = submitted
    const result = props.standalone && 'supplier_id' in body
      ? await registerStandalonePayment({ ...body, application_id: props.application?.id }, etag, key)
      : await createSupplierSettlement(props.draft.kind, body, etag, key)
    ElMessage.success(`已保存 ${result.number}`)
    emit('saved')
  } catch (cause) {
    const status = isAxiosError(cause) ? cause.response?.status : undefined
    uncertain.value = !status || status >= 500
    refreshRequired.value = status === 409 || status === 412
    if (!uncertain.value) {
      key = createClientUuid()
      submitted = undefined
    }
    error.value = uncertain.value ? '暂时无法确认提交结果，请使用原单据重试。'
      : ledgerRequestError(cause, '保存失败，请核对输入。')
  } finally {
    busy.value = false
  }
}

function close() {
  if (!busy.value && !uncertain.value) emit('close')
}

function beforeClose(done: () => void) {
  if (!busy.value && !uncertain.value) done()
}

onMounted(loadOptions)
</script>

<template>
  <AppWindowDialog :model-value="true" :title="paymentMode ? '登记付款' : '抵账'" :width="paymentMode ? 720 : 1040"
    :min-width="290" :minimizable="false" :close-on-click-modal="false" :before-close="beforeClose" @update:model-value="close">
    <ElForm id="supplier-settlement-form" label-position="top" :disabled="busy || uncertain" v-loading="loadingOptions" @submit.prevent="save">
      <div v-if="draft.previous" class="replacement-source"><span>原单号</span><strong>{{ draft.previous.number }}</strong></div>
      <dl v-if="application" class="allocation-context">
        <div><dt>申请单号</dt><dd>{{ application.number }}</dd></div>
        <div><dt>申请剩余金额</dt><dd>{{ ledgerMoney(application.remaining_amount) }}</dd></div>
      </dl>
      <div v-if="paymentMode" class="form-grid">
        <ElFormItem label="供应商" required>
          <ElSelect v-model="paymentForm.supplier_id" filterable placeholder="选择供应商" aria-label="供应商" :disabled="!!application">
            <ElOption v-for="item in suppliers" :key="item.id" :value="item.id" :label="item.supplier_name" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="款项性质" required>
          <ElSelect v-model="paymentForm.nature" aria-label="款项性质" :disabled="!!application">
            <ElOption label="货款" value="GOODS" /><ElOption label="预付款" value="PREPAYMENT" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="实际付款日期" required>
          <ElDatePicker v-model="paymentForm.paid_on" type="date" value-format="YYYY-MM-DD" aria-label="实际付款日期" />
        </ElFormItem>
        <ElFormItem label="公司付款账户" required>
          <ElSelect v-model="paymentForm.account_id" filterable placeholder="选择公司账户" aria-label="公司付款账户">
            <ElOption v-for="item in accounts" :key="item.id" :label="`${item.name} · ${item.code}`" :value="item.id" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="收款人" required><ElInput v-model="paymentForm.payee" maxlength="255" aria-label="收款人" /></ElFormItem>
        <ElFormItem label="实付金额（元）" required><ElInput v-model="paymentForm.amount" inputmode="decimal" aria-label="实付金额" /></ElFormItem>
        <ElFormItem label="付款凭证编号" class="voucher-field" required>
          <ElInput v-model="paymentForm.voucher" maxlength="255" aria-label="付款凭证编号" placeholder="银行回单号或签收凭证标识" />
        </ElFormItem>
      </div>
      <template v-else>
        <div class="form-grid">
          <ElFormItem label="付款单号" required>
            <ElSelect v-model="paymentId" filterable placeholder="选择有可用金额的付款单" aria-label="付款单号">
              <ElOption v-for="item in payments" :key="item.id" :value="item.id" :label="`${item.number} · ${item.supplier_name}`" />
            </ElSelect>
          </ElFormItem>
          <ElFormItem label="抵账日期" required>
            <ElDatePicker v-model="offsetDay" type="date" value-format="YYYY-MM-DD" aria-label="抵账日期" />
          </ElFormItem>
        </div>
        <template v-if="payment">
          <dl class="allocation-context">
            <div><dt>供应商</dt><dd :title="payment.supplier_name">{{ payment.supplier_name }}</dd></div>
            <div><dt>款项性质</dt><dd>{{ payment.nature_display }}</dd></div>
            <div><dt>可用金额</dt><dd>{{ ledgerMoney(payment.available_amount) }}</dd></div>
            <div><dt>本次抵账</dt><dd>{{ allocatedText }}</dd></div>
          </dl>
          <section class="erp-glass-list allocation-list" aria-label="应付分配" v-loading="loadingPayables">
            <div class="erp-list-table-frame">
              <ElTable :data="payables" row-key="id" max-height="400" empty-text="暂无可抵账的应付">
                <ElTableColumn prop="number" label="应付单号" min-width="190" show-overflow-tooltip />
                <ElTableColumn prop="inbound_date" label="入库日期" width="112" />
                <ElTableColumn prop="confirmed_date" label="财务确认日期" width="132" />
                <ElTableColumn label="应付金额" width="120" align="right"><template #default="{ row }">{{ ledgerMoney(row.amount) }}</template></ElTableColumn>
                <ElTableColumn label="未抵金额" width="120" align="right"><template #default="{ row }">{{ ledgerMoney(row.available_amount) }}</template></ElTableColumn>
                <ElTableColumn label="本次抵账金额" width="160" align="right">
                  <template #default="{ row }">
                    <ElInput v-model="allocations[row.id]" inputmode="decimal" :aria-label="`${row.number} 本次抵账金额`" />
                  </template>
                </ElTableColumn>
              </ElTable>
            </div>
          </section>
        </template>
      </template>
      <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon>
        <ElButton v-if="refreshRequired" link @click="loadOptions">刷新选项</ElButton>
      </ElAlert>
    </ElForm>
    <template #footer>
      <ElButton :disabled="busy || uncertain" @click="close">取消</ElButton>
      <ElButton type="primary" native-type="submit" form="supplier-settlement-form" :loading="busy"
        :disabled="loadingOptions || loadingPayables || refreshRequired">{{ uncertain ? '重试原提交' : '保存' }}</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.form-grid {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 16px;
  .el-date-editor.el-input, .el-select { width: 100%; }
  .el-form-item { margin-bottom: 14px; }
  .voucher-field { grid-column: 1 / -1; }
}
.replacement-source { display: flex; gap: 8px; margin-bottom: 12px; white-space: nowrap; font-size: 13px; }
.allocation-context {
  display: flex; gap: 18px; margin: 0 0 12px; font-size: 13px; white-space: nowrap;
  div { display: flex; gap: 8px; min-width: 0; }
  div:not(:first-child) { flex: none; }
  dt { color: var(--erp-color-text-secondary); }
  dd { margin: 0; overflow: hidden; text-overflow: ellipsis; }
}
.allocation-list {
  height: auto; margin-bottom: 12px;
  :deep(.el-input__wrapper) { min-height: 32px; height: 32px; }
  :deep(.el-input__inner) { text-align: right; }
  :deep(.el-table .cell) { white-space: nowrap; text-overflow: ellipsis; }
  :deep(.el-table__header th.el-table__cell) { font-weight: 500; }
}
@media (max-width: 620px) {
  .form-grid { grid-template-columns: 1fr; }
  .allocation-context { flex-wrap: wrap; gap: 8px 14px; }
}
</style>
