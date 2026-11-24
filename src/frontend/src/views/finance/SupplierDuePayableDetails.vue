<script setup lang="ts">
import { ref, shallowRef, watch } from 'vue'
import { isAxiosError } from 'axios'
import { fetchSupplierDuePayableDetails } from '@/api/financeSupplierPayments'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { SupplierDuePayable, SupplierPaymentPage } from '@/types/financeSupplierPayments'
import { ledgerMoney, ledgerRequestError } from './supplierLedgerDisplay'

const props = defineProps<{
  supplierId: string
  supplierName?: string
  month: string
  page: number
  pageSize: number
  canOpenPayable: boolean
}>()
const emit = defineEmits<{ close: []; page: [value: number]; pageSize: [value: number] }>()
const result = shallowRef<SupplierPaymentPage<SupplierDuePayable>>()
const loading = ref(false)
const error = ref('')
const reload = ref(0)
const amountColumns = [
  ['current_balance', '当前未抵金额', 134], ['occupied_amount', '申请占用金额', 134],
  ['requestable_amount', '可申请金额', 122],
] as const

watch(() => [props.supplierId, props.month, props.page, props.pageSize, reload.value] as const, async (_, __, cleanup) => {
  const controller = new AbortController()
  cleanup(() => controller.abort())
  error.value = ''
  loading.value = true
  try {
    const response = await fetchSupplierDuePayableDetails({
      month: props.month, supplier_id: props.supplierId, page: props.page, page_size: props.pageSize,
    }, controller.signal)
    if (!controller.signal.aborted) result.value = response
  } catch (cause) {
    if (controller.signal.aborted) return
    if (props.page > 1 && isAxiosError(cause) && cause.response?.status === 404) emit('page', props.page - 1)
    else error.value = ledgerRequestError(cause, '到期货款明细加载失败。')
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })
</script>

<template>
  <AppWindowDialog :model-value="true" :title="supplierName ? '到期货款明细 · ' + supplierName : '到期货款明细'"
    :width="1100" :min-width="340" :minimizable="false" @update:model-value="!$event && emit('close')">
    <section class="erp-glass-list due-details" aria-label="到期货款明细">
      <ElAlert v-if="error" type="error" :title="error" :closable="false">
        <ElButton link @click="reload++">重试</ElButton>
      </ElAlert>
      <div v-else v-loading="loading" class="erp-list-table-frame">
        <ElTable :data="result?.data ?? []" row-key="id" :max-height="420" empty-text="暂无到期可申请货款">
          <ElTableColumn prop="number" label="应付单号" width="164" show-overflow-tooltip>
            <template #default="{ row }">
              <RouterLink v-if="canOpenPayable" class="payable-link" :title="row.number"
                :to="{ name: 'finance-purchase-payables', query: { payable_id: row.id } }">{{ row.number }}</RouterLink>
              <span v-else>{{ row.number }}</span>
            </template>
          </ElTableColumn>
          <ElTableColumn prop="inbound_date" label="收货日期" width="121" />
          <ElTableColumn prop="receipt_month" label="货款月份" width="103" />
          <ElTableColumn prop="payment_term_months" label="账期月数" width="103">
            <template #default="{ row }">{{ row.payment_term_months }} 个月</template>
          </ElTableColumn>
          <ElTableColumn prop="due_month" label="到期月份" width="103" />
          <ElTableColumn v-for="[field, label, width] in amountColumns" :key="field" :prop="field" :label="label"
            :min-width="width" align="right" show-overflow-tooltip>
            <template #default="{ row }">{{ ledgerMoney(row[field]) }}</template>
          </ElTableColumn>
        </ElTable>
      </div>
      <footer v-if="!error && result" class="erp-list-footer">
        <span>共 {{ result.meta.total }} 条</span>
        <ElPagination :current-page="page" :page-size="pageSize" :total="result.meta.total"
          :page-sizes="[20, 50, 100]" :pager-count="5" layout="sizes, prev, pager, next"
          @update:current-page="emit('page', $event)" @update:page-size="emit('pageSize', $event)" />
      </footer>
    </section>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.due-details {
  height: auto;
  gap: 0;
  :deep(.el-table .cell) { white-space: nowrap; text-overflow: ellipsis; }
  :deep(.el-table td.is-right) { font-variant-numeric: tabular-nums; }
}
.payable-link {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
  color: var(--erp-color-brand);
  &:hover { text-decoration: underline; }
}
</style>
