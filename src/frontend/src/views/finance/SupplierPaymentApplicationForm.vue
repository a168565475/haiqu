<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import { isAxiosError } from 'axios'
import { fetchApplicationPayables, submitSupplierPaymentApplication } from '@/api/financeSupplierPayments'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { SupplierLedgerOption } from '@/types/financeSupplierLedger'
import type { ApplicationPayable, ApplicationPayableMonth, CreateSupplierPaymentApplication } from '@/types/financeSupplierPayments'
import { createClientUuid } from '@/utils/clientUuid'
import { amountInCents, ledgerMoney, ledgerRequestError, ledgerToday, moneyFromCents } from './supplierLedgerDisplay'

const props = defineProps<{
  initialSupplier: string
  suppliers: SupplierLedgerOption[]
  loadingSuppliers: boolean
  dueThroughMonth?: string
}>()
const emit = defineEmits<{ close: []; saved: [id: string] }>()
const supplier = ref(props.initialSupplier)
const date = ref(ledgerToday())
const payee = ref('')
const note = ref('')
const months = shallowRef<ApplicationPayableMonth[]>([])
const showAll = ref(!props.dueThroughMonth)
const expanded = ref<string[]>([])
const amounts = ref<Record<string, string>>({})
const loading = ref(false)
const busy = ref(false)
const uncertain = ref(false)
const refreshRequired = ref(false)
const reload = ref(0)
const error = ref('')
let submitted: { body: CreateSupplierPaymentApplication; key: string } | undefined

const chosen = (id: string) => Object.prototype.hasOwnProperty.call(amounts.value, id)
const selectable = (item: ApplicationPayable) => item.requestable_amount !== '0.00'
const monthTotal = (month: ApplicationPayableMonth) => month.payables.reduce((total, item) =>
  total + (amountInCents(amounts.value[item.id] ?? '') ?? 0n), 0n)
const total = computed(() => months.value.reduce((amount, month) => amount + monthTotal(month), 0n))

watch([supplier, reload, showAll], async ([id, , all], previous, cleanup) => {
  if (id !== previous?.[0]) {
    payee.value = props.suppliers.find(item => item.id === id)?.supplier_name ?? ''
    expanded.value = []
    amounts.value = {}
  }
  const controller = new AbortController()
  cleanup(() => controller.abort())
  error.value = ''
  refreshRequired.value = false
  loading.value = !!id
  if (!id) {
    months.value = []
    return
  }
  try {
    const result = await fetchApplicationPayables(id, controller.signal, all ? undefined : props.dueThroughMonth)
    if (controller.signal.aborted) return
    const validIds = new Set(result.flatMap(month => month.payables.filter(selectable).map(item => item.id)))
    amounts.value = Object.fromEntries(Object.entries(amounts.value).filter(([key]) => validIds.has(key)))
    months.value = result
  } catch (cause) {
    if (controller.signal.aborted) return
    months.value = []
    refreshRequired.value = true
    error.value = ledgerRequestError(cause, '可申请应付加载失败。')
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}, { immediate: true })

function selectPayable(item: ApplicationPayable, checked: boolean) {
  if (!refreshRequired.value) error.value = ''
  if (!checked) delete amounts.value[item.id]
  else if (selectable(item) && !chosen(item.id)) amounts.value[item.id] = item.requestable_amount
}
function toggleMonth(month: string) {
  expanded.value = expanded.value.includes(month)
    ? expanded.value.filter(value => value !== month)
    : [...expanded.value, month]
}
function prepareApplication() {
  const title = payee.value.trim()
  if (!supplier.value || !date.value || !title) {
    error.value = '请填写供应商、申请日期和收款抬头。'
    return
  }
  const payables = months.value.flatMap(month => month.payables).filter(item => chosen(item.id))
  if (!payables.length) {
    error.value = '请选择采购应付并填写申请金额。'
    return
  }
  for (const item of payables) {
    const amount = amountInCents(amounts.value[item.id]!)
    if (!amount || amount > amountInCents(item.requestable_amount)!) {
      error.value = item.number + ' 的申请金额须大于 0 且不超过可申请额，最多两位小数。'
      return
    }
  }
  return {
    supplier_id: supplier.value, applied_on: date.value, payee: title, note: note.value.trim(),
    lines: payables.map(item => ({ payable_id: item.id, amount: amounts.value[item.id]!.trim() })),
  }
}
async function submit() {
  if (busy.value || loading.value || refreshRequired.value) return
  error.value = ''
  if (!submitted) {
    const body = prepareApplication()
    if (!body) return
    submitted = { body, key: createClientUuid() }
  }
  busy.value = true
  try {
    const result = await submitSupplierPaymentApplication(submitted.body, submitted.key)
    ElMessage.success('已提交 ' + result.number)
    emit('saved', result.id)
  } catch (cause) {
    const status = isAxiosError(cause) ? cause.response?.status : undefined
    uncertain.value = !status || status >= 500
    refreshRequired.value = status === 409
    if (!uncertain.value) submitted = undefined
    error.value = uncertain.value ? '暂时无法确认结果，请使用原申请重试。' : ledgerRequestError(cause, '申请提交失败。')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AppWindowDialog :model-value="true" title="新建付款申请" :width="1100" :min-width="360"
    :close-on-click-modal="false" :close-on-press-escape="!busy && !uncertain" :show-close="!busy && !uncertain"
    @update:model-value="!busy && !uncertain && emit('close')">
    <ElForm id="supplier-payment-application" label-position="top" :disabled="busy || uncertain" @submit.prevent="submit">
      <div class="application-fields">
        <ElFormItem label="供应商" required>
          <ElSelect v-model="supplier" filterable placeholder="选择供应商" aria-label="申请供应商" :loading="loadingSuppliers">
            <ElOption v-for="item in suppliers" :key="item.id" :label="item.supplier_name" :value="item.id" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="申请日期" required>
          <ElDatePicker v-model="date" value-format="YYYY-MM-DD" aria-label="申请日期" />
        </ElFormItem>
        <ElFormItem label="收款抬头" required><ElInput v-model="payee" maxlength="255" aria-label="收款抬头" /></ElFormItem>
        <ElFormItem label="付款说明"><ElInput v-model="note" maxlength="500" aria-label="付款说明" /></ElFormItem>
      </div>

      <section v-if="supplier && (loading || months.length || !error)" v-loading="loading" class="erp-glass-list selection-section" aria-label="按货款月选款">
        <div v-if="dueThroughMonth" class="erp-list-tabs selection-tabs" role="group" aria-label="选款范围">
          <button type="button" :class="{ 'is-active': !showAll }" :aria-pressed="!showAll" :disabled="busy || uncertain"
            @click="showAll = false">截至 {{ dueThroughMonth }} 到期</button>
          <button type="button" :class="{ 'is-active': showAll }" :aria-pressed="showAll" :disabled="busy || uncertain"
            @click="showAll = true">全部可选欠款</button>
        </div>
        <div class="erp-list-table-frame">
          <div class="erp-list-table-scroll">
            <table class="erp-list-native-table erp-list-native-table--nowrap month-table" aria-label="货款月份">
              <colgroup>
                <col style="width: 52px"><col style="width: 166px"><col style="width: 138px">
                <col style="width: 154px"><col style="width: 140px"><col style="width: 146px">
              </colgroup>
              <thead><tr>
                <th class="center" scope="col" aria-label="勾选"></th><th scope="col">货款月份</th>
                <th class="num" scope="col">当前未抵金额</th><th class="num" scope="col">其他申请已占用金额</th>
                <th class="num" scope="col">本次可申请金额</th><th class="num" scope="col">本次申请金额</th>
              </tr></thead>
              <tbody>
                <template v-for="month in months" :key="month.month">
                  <tr class="month-row" :class="{ 'is-selected': month.payables.some(item => chosen(item.id)) }">
                    <td class="center">
                      <ElCheckbox :model-value="month.requestable_amount !== '0.00' && month.payables.filter(selectable).every(item => chosen(item.id))"
                        :indeterminate="month.payables.some(item => chosen(item.id)) && !month.payables.filter(selectable).every(item => chosen(item.id))"
                        :disabled="month.requestable_amount === '0.00'" :aria-label="'勾选 ' + month.month"
                        @change="(checked: unknown) => month.payables.forEach(item => selectPayable(item, !!checked))" />
                    </td>
                    <td>
                      <button type="button" class="month-toggle" :aria-expanded="expanded.includes(month.month)" @click="toggleMonth(month.month)">
                        <ElIcon><ArrowDown v-if="expanded.includes(month.month)" /><ArrowRight v-else /></ElIcon>{{ month.month }}
                      </button>
                    </td>
                    <td class="num">{{ ledgerMoney(month.current_balance) }}</td>
                    <td class="num">{{ ledgerMoney(month.occupied_amount) }}</td>
                    <td class="num">{{ ledgerMoney(month.requestable_amount) }}</td>
                    <td class="num">{{ moneyFromCents(monthTotal(month)) }}</td>
                  </tr>
                  <tr v-if="expanded.includes(month.month)" class="source-row"><td colspan="6">
                    <div class="erp-list-table-frame">
                      <div class="erp-list-table-scroll">
                        <table class="erp-list-native-table erp-list-native-table--nowrap source-table"
                          :aria-label="month.month + ' 采购应付明细'">
                          <colgroup>
                            <col style="width: 48px"><col style="width: 168px"><col style="width: 105px"><col style="width: 123px">
                            <col style="width: 96px"><col style="width: 102px">
                            <col style="width: 104px"><col style="width: 114px"><col style="width: 122px"><col style="width: 144px">
                          </colgroup>
                          <thead><tr>
                            <th class="center" scope="col" aria-label="勾选"></th><th scope="col">采购应付单号</th><th scope="col">入库日期</th>
                            <th class="num" scope="col">已确认应付金额</th><th scope="col">账期月数</th><th scope="col">到期月份</th>
                            <th class="num" scope="col">已抵金额</th>
                            <th class="num" scope="col">尚未抵账金额</th><th class="num" scope="col">本次可申请金额</th>
                            <th class="num" scope="col">本次申请金额</th>
                          </tr></thead>
                          <tbody>
                            <tr v-for="item in month.payables" :key="item.id" :class="{ 'is-selected': chosen(item.id) }">
                              <td class="center">
                                <ElCheckbox :model-value="chosen(item.id)" :disabled="!selectable(item)" :aria-label="'勾选 ' + item.number"
                                  @change="(checked: unknown) => selectPayable(item, !!checked)" />
                              </td>
                              <td :title="item.number">{{ item.number }}</td><td>{{ item.inbound_date }}</td>
                              <td class="num">{{ ledgerMoney(item.confirmed_amount) }}</td>
                              <td>{{ item.payment_term_months ? item.payment_term_months + ' 个月' : '待确认' }}</td>
                              <td>{{ item.due_month ?? '—' }}</td><td class="num">{{ ledgerMoney(item.offset_amount) }}</td>
                              <td class="num">{{ ledgerMoney(item.current_balance) }}</td><td class="num">{{ ledgerMoney(item.requestable_amount) }}</td>
                              <td><ElInput v-model="amounts[item.id]" inputmode="decimal" :disabled="!chosen(item.id)" placeholder="0.00"
                                :aria-label="item.number + ' 本次申请金额'" @input="!refreshRequired && (error = '')" /></td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </td></tr>
                </template>
                <tr v-if="!loading && !months.length"><td class="empty" colspan="6">该供应商暂无可申请应付</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
      <ElAlert v-if="error" class="application-error" :title="error" type="error" :closable="false">
        <ElButton v-if="refreshRequired" link @click="reload++">刷新可申请额</ElButton>
      </ElAlert>
    </ElForm>
    <template #footer>
      <div class="application-actions">
        <span>申请合计（元） <strong>{{ moneyFromCents(total) }}</strong></span>
        <ElButton :disabled="busy || uncertain" @click="emit('close')">取消</ElButton>
        <ElButton type="primary" native-type="submit" form="supplier-payment-application" :loading="busy"
          :disabled="loading || loadingSuppliers || refreshRequired">{{ uncertain ? '重试原申请' : '提交申请' }}</ElButton>
      </div>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.application-fields {
  display: grid; grid-template-columns: minmax(0, 1.2fr) 145px minmax(0, 1.15fr) minmax(0, 1fr); gap: 0 12px;
  :deep(.el-date-editor), :deep(.el-select) { width: 100%; }
  :deep(.el-form-item__label) { white-space: nowrap; }
}
.selection-section {
  height: auto; gap: 8px;
  .selection-tabs { flex-wrap: nowrap; white-space: nowrap; }
  .month-table { min-width: 796px; }
  .source-table { min-width: 1126px; }
  .center { padding: 0 4px; }
  th, td { white-space: nowrap; }
  .source-row > td { height: auto; padding: 8px; background: var(--erp-table-background); border-right: 0; }
  .source-table :deep(.el-input__inner) { text-align: right; }
  .source-table :deep(.el-input__wrapper) { height: 32px; min-height: 32px; }
  .month-toggle {
    display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 4px;
    border: 0; background: none; color: var(--erp-color-brand); font: inherit; cursor: pointer; white-space: nowrap;
  }
}
.application-actions {
  display: flex; align-items: center; gap: 10px; white-space: nowrap;
  span { margin-right: auto; }
  strong { margin-left: 8px; font-variant-numeric: tabular-nums; }
  :deep(.el-button + .el-button) { margin-left: 0; }
}
.application-error { margin-top: 12px; }
@media (max-width: 700px) {
  .application-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
