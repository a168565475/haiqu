<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { fetchSupplierPaymentApplication, withdrawSupplierPaymentApplication } from '@/api/financeSupplierPayments'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { SupplierPaymentApplicationContext, SupplierPaymentApplicationDetail } from '@/types/financeSupplierPayments'
import { ledgerMoney, ledgerRequestError } from './supplierLedgerDisplay'

const props = defineProps<{ applicationId: string }>()
const emit = defineEmits<{ close: []; register: [application: SupplierPaymentApplicationContext]; payment: [id: string]; changed: [] }>()
const auth = useAuthStore()
const application = shallowRef<SupplierPaymentApplicationDetail>()
const etag = ref('')
const reload = ref(0)
const loading = ref(false)
const busy = ref(false)
const editing = ref(false)
const reason = ref('')
const error = ref('')
const actionable = computed(() => !!application.value && !application.value.withdrawn_at && application.value.remaining_amount !== '0.00')
const allowed = (permission: string) => auth.identityReady && (auth.user?.is_superuser || auth.hasPermission(permission))
const canWithdraw = computed(() => actionable.value && allowed('finance.withdraw_supplierpaymentapplication'))
const canRegister = computed(() => actionable.value && allowed('finance.add_supplierpayment'))
const fields = computed(() => {
  const row = application.value
  if (!row) return []
  return [
    ['申请单号', row.number], ['申请日期', row.applied_on], ['供应商', row.supplier_name], ['收款抬头', row.payee],
    ['申请部门', row.department_name || '—'], ['经办人', row.recorded_by_name],
    ['申请金额', ledgerMoney(row.amount)], ['已付金额', ledgerMoney(row.paid_amount)],
    ['申请剩余金额', ledgerMoney(row.remaining_amount)], ['付款说明', row.note || '—'],
    ...(row.withdrawn_at ? [['撤回时间', new Date(row.withdrawn_at).toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai', hour12: false,
    })], ['撤回原因', row.withdrawal_reason]] : []),
  ]
})

watch([() => props.applicationId, reload], async ([id], _, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  loading.value = true
  error.value = ''
  editing.value = false
  reason.value = ''
  try {
    const result = await fetchSupplierPaymentApplication(id, controller.signal)
    if (controller.signal.aborted) return
    application.value = result.record
    etag.value = result.etag
  } catch (cause) {
    if (!controller.signal.aborted) {
      application.value = undefined
      error.value = ledgerRequestError(cause, '付款申请加载失败。')
    }
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

async function withdraw() {
  if (busy.value || !canWithdraw.value) return
  if (!reason.value.trim()) {
    error.value = '请填写撤回原因。'
    return
  }
  busy.value = true
  error.value = ''
  try {
    const result = await withdrawSupplierPaymentApplication(props.applicationId, reason.value.trim(), etag.value)
    application.value = result.record
    etag.value = result.etag
    editing.value = false
    emit('changed')
  } catch (cause) {
    error.value = ledgerRequestError(cause, '撤回结果未确认，请刷新单据核对。')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AppWindowDialog :model-value="true" title="付款申请详情" :width="900" :min-width="360"
    :show-close="!busy" :close-on-press-escape="!busy" :close-on-click-modal="!busy" @update:model-value="emit('close')">
    <div class="application-detail" v-loading="loading">
      <ElAlert v-if="error" class="detail-alert" :title="error" type="error" :closable="false">
        <ElButton link :disabled="busy" @click="reload++">刷新单据</ElButton>
      </ElAlert>
      <template v-if="application">
        <dl class="document-fields">
          <div v-for="[label, value] in fields" :key="label"><dt>{{ label }}</dt><dd :title="value">{{ value }}</dd></div>
        </dl>
        <section class="erp-glass-list detail-tables">
          <div class="erp-list-table-frame">
            <ElTable :data="application.lines" row-key="payable_id" aria-label="申请选款明细" max-height="330">
              <ElTableColumn prop="month" label="货款月份" min-width="102" />
              <ElTableColumn prop="payable_number" label="采购应付单号" min-width="168" show-overflow-tooltip />
              <ElTableColumn prop="inbound_date" label="入库日期" min-width="106" />
              <ElTableColumn label="已确认应付金额" min-width="120" align="right">
                <template #default="{ row }">{{ ledgerMoney(row.confirmed_amount) }}</template>
              </ElTableColumn>
              <ElTableColumn label="申请时已抵金额" min-width="120" align="right">
                <template #default="{ row }">{{ ledgerMoney(row.offset_amount) }}</template>
              </ElTableColumn>
              <ElTableColumn label="本次申请金额" min-width="125" align="right">
                <template #default="{ row }">{{ ledgerMoney(row.amount) }}</template>
              </ElTableColumn>
              <ElTableColumn v-if="application.withdrawn_at" label="撤回金额" min-width="110" align="right">
                <template #default="{ row }">{{ ledgerMoney(row.released_amount) }}</template>
              </ElTableColumn>
            </ElTable>
          </div>
          <div v-if="application.payments.length" class="erp-list-table-frame">
            <ElTable :data="application.payments" row-key="id" aria-label="关联付款" max-height="260">
              <ElTableColumn label="付款单号" min-width="195">
                <template #default="{ row }"><ElButton link type="primary" @click="emit('payment', row.id)">{{ row.number }}</ElButton></template>
              </ElTableColumn>
              <ElTableColumn prop="business_date" label="实际付款日期" min-width="130" />
              <ElTableColumn label="本申请对应实付金额" min-width="166" align="right">
                <template #default="{ row }">{{ ledgerMoney(row.amount) }}</template>
              </ElTableColumn>
            </ElTable>
          </div>
        </section>
        <ElForm v-if="editing" id="supplier-payment-application-withdraw" label-position="top" @submit.prevent="withdraw">
          <ElFormItem label="撤回原因" required>
            <ElInput v-model="reason" maxlength="500" :disabled="busy" aria-label="撤回原因" />
          </ElFormItem>
        </ElForm>
      </template>
    </div>
    <template #footer>
      <ElButton :disabled="busy" @click="emit('close')">关闭</ElButton>
      <ElButton v-if="canWithdraw && !editing" :disabled="loading" @click="editing = true">撤回未执行金额</ElButton>
      <ElButton v-if="canRegister && application && !editing" type="primary" :disabled="loading" @click="emit('register', application)">登记付款</ElButton>
      <ElButton v-if="editing" type="danger" native-type="submit" :loading="busy"
        form="supplier-payment-application-withdraw">确认撤回</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.application-detail { min-height: 48px; }
.detail-alert { margin-bottom: 12px; }
.document-fields {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 18px;
  margin: 0 0 14px; font-size: 13px;
  div { display: flex; gap: 10px; align-items: center; min-width: 0; }
  dt { flex: none; color: var(--erp-color-text-secondary); }
  dd { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
}
.detail-tables {
  height: auto; margin-bottom: 12px;
  :deep(.el-table .cell) { white-space: nowrap; text-overflow: ellipsis; }
  :deep(.el-table__header th.el-table__cell) { font-weight: 500; }
}
</style>
