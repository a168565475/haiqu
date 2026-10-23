<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ReceiptAccountInput, ReceiptDepositOption, ReceiptFile, ReceiptStatementContext } from '@/types/financeReceipts'
import GoodsDepositSelectDialog from './GoodsDepositSelectDialog.vue'
import { moneyCents, moneyText, previewGoods, totalCents } from './goodsAmounts'

const props = defineProps<{
  statement: ReceiptStatementContext | null
  accountLines: ReceiptAccountInput[]
  uploadIds: string[]
  depositIds: string[]
  discountAmount: string
  pureDeposit: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{
  'update:depositIds': [value: string[]]
  'update:discountAmount': [value: string]
  'update:pureDeposit': [value: boolean]
  validity: [valid: boolean]
  summary: [value: { settledAmount: string; outstandingAfter: string }]
  change: []
  preview: [receiptId: string, file: ReceiptFile]
  refresh: []
}>()
const picker = ref(false)
const touched = ref(false)
const stale = ref(false)
const selectionEtag = ref('')
const selected = ref<ReceiptDepositOption[]>([])
const current = computed(() => selected.value.filter(row => props.depositIds.includes(row.id)))
const cash = computed(() => totalCents(props.accountLines.map(line => line.cash_amount)))
const fees = computed(() => totalCents(props.accountLines.map(line => line.fee_amount)))
const allocated = computed(() => current.value.length === props.depositIds.length ? totalCents(current.value.map(row => row.available_amount)) : null)
const result = computed(() => props.statement ? previewGoods(props.statement.outstanding_amount, props.statement.available_deposit_amount,
  cash.value, allocated.value, props.discountAmount) : null)
const maximum = computed(() => {
  const outstanding = moneyCents(props.statement?.outstanding_amount || '')
  const discount = moneyCents(props.discountAmount)
  if (outstanding === null || discount === null || cash.value === null) return '0.00'
  const value = outstanding - cash.value - discount
  return moneyText(value > 0n ? value : 0n)
})
const bankAfter = computed(() => {
  const bank = moneyCents(props.statement?.bank_received_amount || '')
  return bank === null || cash.value === null ? null : bank + cash.value
})
const needsReconfirm = computed(() => props.depositIds.length > 0 && selectionEtag.value !== props.statement?.etag)
const valid = computed(() => !!props.statement && !!result.value && !result.value.error && !stale.value &&
  !needsReconfirm.value &&
  fees.value !== null && (props.pureDeposit ? props.accountLines.length === 0 && props.uploadIds.length === 0 : true) &&
  (cash.value === 0n || props.uploadIds.length > 0))
watch(valid, value => emit('validity', value), { immediate: true })
watch(result, value => emit('summary', { settledAmount: moneyText(value?.settled ?? null), outstandingAfter: moneyText(value?.after ?? null) }), { immediate: true })
watch(() => props.statement?.id, () => { selected.value = []; stale.value = false; touched.value = false; picker.value = false })
watch(() => props.statement?.etag, () => { stale.value = false })
function confirm(rows: ReceiptDepositOption[]) {
  selected.value = rows; touched.value = true; selectionEtag.value = props.statement?.etag || ''
  emit('update:depositIds', rows.map(row => row.id)); emit('change')
}
function remove(id: string) {
  emit('update:depositIds', props.depositIds.filter(value => value !== id)); touched.value = true; emit('change')
}
function discountChanged(value: string) { emit('update:discountAmount', value); touched.value = true; emit('change') }
</script>

<template>
  <div class="goods-workspace">
    <div class="goods-entry">
      <div class="pure-option"><el-checkbox :model-value="pureDeposit" :disabled="disabled || !statement" @change="emit('update:pureDeposit', !!$event)">仅订金核销，无新到账</el-checkbox></div>
      <slot name="accounts"/>
      <section class="goods-section">
        <div class="goods-section-heading"><div><h3>订金抵扣</h3><p>仅本对账单，整笔使用 · 当前可用 {{ statement?.available_deposit_amount || '—' }} 元</p></div><el-button :disabled="disabled || !statement || stale" @click="picker = true">选择订金</el-button></div>
        <p v-if="!current.length" class="goods-empty">{{ pureDeposit ? '请选择本对账单的整笔订金。' : '未选择订金，本次仅按实际到账核销。' }}</p>
        <div v-for="row in current" :key="row.id" class="goods-allocation">
          <div><strong>{{ row.number }}</strong><span>{{ row.received_on || '到账日期缺失' }} · 原收款 {{ row.deposit_amount }} 元 · 未用 {{ row.available_amount }} 元</span></div>
          <strong>{{ row.available_amount }} 元</strong>
          <el-button v-for="file in row.attachments" :key="file.file_id" link type="primary" @click="emit('preview', row.id, file)">原水单</el-button>
          <el-button link :disabled="disabled" @click="remove(row.id)">移除</el-button>
        </div>
      </section>
      <slot name="uploads"/>
    </div>
    <aside class="goods-summary" aria-label="本次核销结果">
      <h3>本次核销结果</h3><p>到账与订金抵扣计入核销；折让单列。</p>
      <el-form-item class="discount-entry" label="本次折让（元）" :error="touched && moneyCents(discountAmount) === null ? '请输入最多两位小数的非负金额' : ''"><el-input :model-value="discountAmount" aria-label="本次折让（元）" inputmode="decimal" maxlength="23" :disabled="disabled || !statement" @update:model-value="discountChanged"/></el-form-item>
      <dl class="goods-totals">
        <dt>对账金额</dt><dd>{{ statement?.amount || '—' }}<small> 元</small></dd>
        <dt>当前有效折让</dt><dd>{{ statement?.discount_amount || '—' }}<small> 元</small></dd>
        <dt>当前已核销</dt><dd>{{ statement?.settled_amount || '—' }}<small> 元</small></dd>
        <dt>当前未付</dt><dd>{{ statement?.outstanding_amount || '—' }}<small> 元</small></dd>
        <dt class="divider">本次实际到账</dt><dd class="divider">{{ moneyText(cash) }}<small> 元</small></dd>
        <dt>本次订金抵扣</dt><dd>{{ moneyText(allocated) }}<small> 元</small></dd>
        <dt>本次折让</dt><dd>{{ moneyText(moneyCents(discountAmount)) }}<small> 元</small></dd>
        <dt>本次核销</dt><dd>{{ moneyText(result?.settled ?? null) }}<small> 元</small></dd>
        <dt class="emphasis">核销后未付</dt><dd class="emphasis" :class="{ negative: result?.after !== null && result?.after !== undefined && result.after < 0n }">{{ moneyText(result?.after ?? null) }}<small> 元</small></dd>
        <dt class="divider">可用订金（核销后）</dt><dd class="divider">{{ moneyText(result?.availableAfter ?? null) }}<small> 元</small></dd>
        <dt>累计银行到账（本次后）</dt><dd>{{ moneyText(bankAfter) }}<small> 元</small></dd>
        <dt>本次手续费（不抵债）</dt><dd>{{ moneyText(fees) }}<small> 元</small></dd>
      </dl>
      <p class="summary-note">核销后未付不能为负；未用订金也不能超过剩余未付。最终金额以保存时核对的余额为准。</p>
      <el-alert v-if="stale" title="账单资金已变化，当前输入已保留。请刷新并比较余额。" type="warning" :closable="false"><el-button :disabled="disabled" @click="emit('refresh')">刷新账单余额</el-button></el-alert>
      <p v-else-if="needsReconfirm" class="amount-error" role="alert">账单余额已刷新，请打开“选择订金”重新确认整笔抵扣。</p>
      <p v-if="touched && result?.error" class="amount-error" role="alert">{{ result.error }}</p>
    </aside>
  </div>
  <GoodsDepositSelectDialog v-if="statement" v-model="picker" :statement="statement" :selected="current" :maximum-amount="maximum" @confirm="confirm" @preview="(id, file) => emit('preview', id, file)" @stale="stale = true"/>
</template>

<style scoped lang="scss">
.goods-workspace{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:28px;padding-top:20px;align-items:start}.goods-entry{min-width:0}.pure-option{margin:0 0 10px}.goods-section{border-top:1px solid var(--erp-color-border);margin-top:20px;padding-top:20px}.goods-section-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:12px}.goods-section h3,.goods-summary h3{margin:0;font-size:15px;line-height:22px;font-weight:600}.goods-section-heading p,.goods-summary>p{margin:4px 0 0;font-size:12px;line-height:20px;color:var(--erp-color-text-secondary)}.goods-empty{padding:14px 16px;border-radius:5px;background:var(--erp-input-readonly-background);font-size:12px;line-height:20px;color:var(--erp-color-text-secondary)}
.goods-allocation{display:flex;align-items:center;gap:12px;padding:14px 0;border-bottom:1px solid var(--erp-color-border);font-size:13px}.goods-allocation>div{flex:1;min-width:0}.goods-allocation>div strong{display:block;font-size:12px;overflow-wrap:anywhere}.goods-allocation>div span{display:block;margin-top:5px;font-size:12px;color:var(--erp-color-text-secondary)}.goods-allocation>.el-button{margin-left:0}.goods-allocation>strong{font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.goods-summary{position:sticky;top:0;min-width:0;border-left:1px solid var(--erp-color-border);padding-left:24px}.goods-totals{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px 12px;margin:18px 0 0;font-size:12px;line-height:20px}.goods-totals dt{color:var(--erp-color-text-secondary)}.goods-totals dd{margin:0;text-align:right;font-variant-numeric:tabular-nums;font-size:13px;font-weight:500;overflow-wrap:anywhere;min-width:0;max-width:175px}.goods-totals small{font-size:11px;font-weight:400}.goods-totals .divider{border-top:1px solid var(--erp-color-border);padding-top:14px;margin-top:4px}.goods-totals .emphasis{font-weight:600;color:var(--erp-menu-accent);padding:14px 0;border-block:1px solid var(--erp-color-border);margin:4px 0}.goods-totals dd.emphasis{font-size:20px}.goods-totals .negative,.amount-error{color:var(--el-color-danger)}.discount-entry{margin:16px 0 0;display:flex;align-items:center}.discount-entry :deep(.el-form-item__label){font-size:12px}.discount-entry :deep(.el-form-item__content){min-width:0}.summary-note{font-size:11px!important;line-height:19px!important;margin-top:16px!important}.amount-error{font-size:12px;line-height:20px}
@media(max-width:1100px){.goods-workspace{grid-template-columns:1fr}.goods-summary{position:static;padding:20px 0 0;border-left:0;border-top:1px solid var(--erp-color-border)}}
@media(max-width:600px){.goods-section-heading,.goods-allocation{flex-wrap:wrap}.goods-allocation>div{flex-basis:100%}.goods-totals{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.goods-totals dd{max-width:none}}
@container(max-width:1000px){.goods-workspace{grid-template-columns:1fr}.goods-summary{position:static;padding:20px 0 0;border-left:0;border-top:1px solid var(--erp-color-border)}}
@container(max-width:600px){.goods-section-heading,.goods-allocation{flex-wrap:wrap}.goods-allocation>div{flex-basis:100%}.goods-totals{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.goods-totals dd{max-width:none}}
@media(prefers-reduced-motion:reduce){:deep(*),:deep(*::before),:deep(*::after){transition:none!important;animation:none!important;scroll-behavior:auto!important}}
</style>
