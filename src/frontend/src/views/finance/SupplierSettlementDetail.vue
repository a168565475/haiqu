<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { fetchSupplierSettlement, voidSupplierSettlement } from '@/api/financeSupplierLedger'
import { fetchStandalonePayment, voidStandalonePayment } from '@/api/financeSupplierPayments'
import { useAuthStore } from '@/stores/auth'
import type { SupplierOffset, SupplierPayment, SupplierSettlementKind, SupplierSettlementDraft } from '@/types/financeSupplierLedger'
import type { SupplierPaymentRecord } from '@/types/financeSupplierPayments'
import { ledgerMoney, ledgerRequestError } from './supplierLedgerDisplay'

const props = defineProps<{ kind: SupplierSettlementKind; documentId: string; standalone?: boolean }>()
const emit = defineEmits<{
  close: []
  changed: []
  reopen: [kind: SupplierSettlementKind, id: string]
  replace: [draft: SupplierSettlementDraft]
  application: [id: string]
}>()
const auth = useAuthStore()
type PaymentDetail = SupplierPayment & Partial<Pick<SupplierPaymentRecord, 'application_id' | 'application_number'>>
const document = shallowRef<PaymentDetail | SupplierOffset>()
const etag = ref('')
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const editing = ref(false)
const reason = ref('')
const reload = ref(0)
const payment = computed(() => document.value && 'nature' in document.value ? document.value : undefined)
const linkedApplication = computed(() => {
  const record = payment.value
  return record?.application_id
    ? { id: record.application_id, number: record.application_number }
    : undefined
})
const offset = computed(() => document.value && 'allocations' in document.value ? document.value : undefined)
const kindLabel = computed(() => props.kind === 'payments' ? '付款单' : '抵账单')
const permissionResource = computed(() => props.kind === 'payments' ? 'supplierpayment' : 'supplieroffset')
const allowed = (action: 'add' | 'void') => auth.user?.is_superuser || auth.hasPermission(`finance.${action}_${permissionResource.value}`)
const canCorrect = computed(() => document.value?.status === 'ACTIVE' && allowed('void'))
const canReplace = computed(() => document.value?.status === 'VOID' && !document.value.replacement_id && allowed('add'))
const canViewPayable = computed(() => auth.user?.is_superuser || auth.hasPermission('finance.view_purchasepayable'))

watch([() => props.kind, () => props.documentId, reload], async ([kind, id], _, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  document.value = undefined
  editing.value = false
  reason.value = ''
  error.value = ''
  loading.value = true
  try {
    const result = props.standalone && kind === 'payments'
      ? await fetchStandalonePayment(id, controller.signal)
      : await fetchSupplierSettlement(kind, id, controller.signal)
    document.value = result.record
    etag.value = result.etag
  } catch (cause) {
    if (!controller.signal.aborted) error.value = ledgerRequestError(cause, '单据加载失败，请重试。')
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

async function correct() {
  if (!canCorrect.value || busy.value) return
  if (!reason.value.trim()) {
    error.value = '请填写更正原因。'
    return
  }
  busy.value = true
  error.value = ''
  try {
    document.value = props.standalone && props.kind === 'payments'
      ? await voidStandalonePayment(props.documentId, reason.value.trim(), etag.value)
      : await voidSupplierSettlement(props.kind, props.documentId, reason.value.trim(), etag.value)
    editing.value = false
    emit('changed')
  } catch (cause) {
    error.value = ledgerRequestError(cause, '更正提交未确认，请刷新单据核对。')
  } finally {
    busy.value = false
  }
}

function replace() {
  if (payment.value) emit('replace', { kind: 'payments', previous: payment.value })
  else if (offset.value) emit('replace', { kind: 'offsets', previous: offset.value })
}
</script>

<template>
  <AppWindowDialog :model-value="true" :title="document ? `${kindLabel} ${document.number}` : kindLabel"
    :width="760" :min-width="290" :minimizable="false" :close-on-click-modal="!busy" :close-on-press-escape="!busy"
    :show-close="!busy" @update:model-value="emit('close')">
    <section v-loading="loading" class="settlement-document">
      <ElAlert v-if="error" :title="error" type="error" :closable="false">
        <ElButton link :disabled="busy" @click="reload++">刷新单据</ElButton>
      </ElAlert>
      <dl v-if="document" class="document-fields">
        <dt>供应商</dt><dd :title="document.supplier_name">{{ document.supplier_name }}</dd>
        <dt>{{ standalone ? '实际付款日期' : '业务日期' }}</dt><dd>{{ document.business_date }}</dd>
        <dt>状态</dt><dd>{{ document.status_display }}</dd>
        <dt>经办人</dt><dd>{{ document.recorded_by_name }}</dd>
        <template v-if="payment">
          <dt>款项性质</dt><dd>{{ payment.nature_display }}</dd>
          <dt>公司付款账户</dt><dd :title="payment.account_name">{{ payment.account_name }}</dd>
          <dt>收款人</dt><dd :title="payment.payee">{{ payment.payee }}</dd>
          <dt>付款凭证编号</dt><dd :title="payment.voucher">{{ payment.voucher }}</dd>
          <dt>实付金额（元）</dt><dd>{{ ledgerMoney(payment.amount) }}</dd>
          <template v-if="linkedApplication">
            <dt>关联付款申请</dt>
            <dd><ElButton link type="primary" @click="emit('application', linkedApplication.id)">{{ linkedApplication.number }}</ElButton></dd>
          </template>
          <template v-if="payment.status === 'ACTIVE'">
            <dt>可用金额（元）</dt><dd>{{ ledgerMoney(payment.available_amount) }}</dd>
          </template>
        </template>
        <template v-if="offset">
          <dt>付款单号</dt><dd><ElButton link type="primary" @click="emit('reopen', 'payments', offset.payment_id)">{{ offset.payment_number }}</ElButton></dd>
        </template>
        <template v-if="document.voided_at">
          <dt>更正时间</dt><dd>{{ new Date(document.voided_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) }}</dd>
          <dt>更正经办人</dt><dd>{{ document.voided_by_name }}</dd>
          <dt>更正原因</dt><dd :title="document.void_reason">{{ document.void_reason }}</dd>
        </template>
        <template v-if="document.replaces_id">
          <dt>原单号</dt><dd><ElButton link type="primary" @click="emit('reopen', kind, document.replaces_id!)">{{ document.replaces_number }}</ElButton></dd>
        </template>
        <template v-if="document.replacement_id">
          <dt>重新登记单号</dt><dd><ElButton link type="primary" @click="emit('reopen', kind, document.replacement_id!)">{{ document.replacement_number }}</ElButton></dd>
        </template>
      </dl>
      <div v-if="offset" class="erp-glass-list document-table">
        <div class="erp-list-table-frame">
          <ElTable :data="offset.allocations" row-key="payable_id" max-height="360">
            <ElTableColumn label="应付单号" min-width="190" show-overflow-tooltip>
              <template #default="{ row }">
                <RouterLink v-if="canViewPayable" :to="{ name: 'finance-purchase-payables', query: { payable_id: row.payable_id } }"
                  @click="emit('close')">{{ row.payable_number }}</RouterLink>
                <span v-else>{{ row.payable_number }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="本次抵账金额" width="160" align="right">
              <template #default="{ row }">{{ ledgerMoney(row.amount) }}</template>
            </ElTableColumn>
          </ElTable>
        </div>
      </div>
      <ElForm v-if="editing" id="supplier-settlement-correction" label-position="top" @submit.prevent="correct">
        <ElFormItem label="更正原因" required>
          <ElInput v-model="reason" :disabled="busy" maxlength="500" aria-label="更正原因" />
        </ElFormItem>
      </ElForm>
    </section>
    <template #footer>
      <ElButton :disabled="busy" @click="emit('close')">关闭</ElButton>
      <ElButton v-if="canReplace" type="primary" @click="replace">{{ kind === 'payments' ? '重新登记' : '重新抵账' }}</ElButton>
      <ElButton v-if="canCorrect && !editing" @click="editing = true">更正</ElButton>
      <ElButton v-if="editing" type="danger" native-type="submit" :loading="busy" form="supplier-settlement-correction">确认更正</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.settlement-document { min-height: 48px; }
.document-fields {
  display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 10px 16px; margin: 0 0 14px; font-size: 13px;
  dt { color: var(--erp-color-text-secondary); }
  dd { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
.document-table { height: auto; margin-bottom: 14px; }
.document-table :deep(.el-table .cell) { white-space: nowrap; }
.document-table :deep(.el-table__header th.el-table__cell) { font-weight: 500; }
.el-alert { margin-bottom: 12px; }
</style>
