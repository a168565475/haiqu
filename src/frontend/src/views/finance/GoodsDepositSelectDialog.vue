<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { fetchFinanceAvailableDeposits } from '@/api/financeReceipts'
import type { ReceiptDepositOption, ReceiptFile, ReceiptStatementContext } from '@/types/financeReceipts'
import { moneyCents, moneyText, totalCents } from './goodsAmounts'

const props = defineProps<{ modelValue: boolean; statement: ReceiptStatementContext; selected: ReceiptDepositOption[]; selectionEtag: string; maximumAmount: string }>()
const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  confirm: [value: ReceiptDepositOption[]]
  preview: [receiptId: string, file: ReceiptFile]
  stale: []
}>()
const rows = ref<ReceiptDepositOption[]>([])
const draft = ref<ReceiptDepositOption[]>([])
const q = ref('')
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const error = ref('')
const stale = ref(false)
const verifiedIds = ref(new Set<string>())
let generation = 0
let controller: AbortController | undefined
const selectedTotal = computed(() => totalCents(draft.value.map(row => row.available_amount)))
const selectionError = computed(() => {
  if (draft.value.some(row => reason(row))) return '已选订金的状态已变化，请移除不可用订金后重新确认。'
  if (draft.value.some(row => !verifiedIds.value.has(row.id))) return '请查看已选订金所在页，核对最新余额后确认。'
  return ''
})
function reason(row: ReceiptDepositOption) {
  if (!row.can_select || row.status !== 'ACTIVE') return row.blocked_reason || '该订金不可用'
  const amount = moneyCents(row.available_amount)
  if (amount === null || amount <= 0n) return '该订金暂无可用余额'
  return ''
}
function toggle(row: ReceiptDepositOption, selected: boolean) {
  if (loading.value || error.value || stale.value) return
  if (selected && reason(row)) return
  draft.value = selected ? [...draft.value.filter(item => item.id !== row.id), row] : draft.value.filter(item => item.id !== row.id)
}
async function load() {
  const current = ++generation
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''
  try {
    const result = await fetchFinanceAvailableDeposits(props.statement.id,
      { q: q.value.trim(), page: page.value, page_size: 20, include_unavailable: true }, controller.signal)
    if (current !== generation || !props.modelValue) return
    rows.value = result.data; total.value = result.meta.total
    stale.value = result.statement_etag !== props.statement.etag
    if (stale.value) { emit('stale'); return }
    result.data.forEach(row => verifiedIds.value.add(row.id))
    // 回填最新可用余额，主表保留已输入金额并重新校验，不静默减少核销额。
    draft.value = draft.value.map(item => {
      const fresh = result.data.find(row => row.id === item.id)
      return fresh || item
    })
  } catch (err) {
    if (current === generation && !axios.isCancel(err)) {
      error.value = axios.isAxiosError(err) ? err.response?.data?.error?.message || '订金未能加载，请重试。' : '订金未能加载，请重试。'
    }
  } finally { if (current === generation) loading.value = false }
}
watch(() => [props.modelValue, props.statement.id, props.statement.etag] as const, ([open]) => {
  ++generation; controller?.abort()
  if (!open) { loading.value = false; return }
  q.value = ''; page.value = 1; rows.value = []; draft.value = [...props.selected]; stale.value = false
  verifiedIds.value = new Set(props.selectionEtag === props.statement.etag ? props.selected.map(row => row.id) : [])
  void load()
}, { immediate: true })
onBeforeUnmount(() => { ++generation; controller?.abort() })
function confirm() {
  if (loading.value || error.value || stale.value || selectionError.value) return
  emit('confirm', [...draft.value]); emit('update:modelValue', false)
}
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="选择订金" :width="1080" :min-width="280" :minimizable="false" destroy-on-close class="goods-deposit-dialog" @update:model-value="emit('update:modelValue', $event)">
    <p class="selection-note">仅 {{ statement.number }} 的订金；选入后填写本次核销金额，未用余额保留。本次最多可抵扣 {{ maximumAmount }} 元。</p>
    <div class="selection-search"><el-input v-model="q" aria-label="搜索订金收款单号" placeholder="订金收款单号" clearable @keyup.enter="page = 1; load()"/><el-button :loading="loading" @click="page = 1; load()">查询</el-button><el-button :disabled="loading" @click="load">刷新</el-button></div>
    <el-alert v-if="stale" title="账单资金已有变化。请关闭选单，刷新账单余额并比较当前输入后重新选择。" type="warning" :closable="false"/>
    <el-alert v-if="error" :title="rows.length ? `${error} 当前仍显示上次结果，不能确认选择。` : error" type="error" :closable="false"/>
    <div class="erp-glass-list goods-deposit-table"><div class="erp-list-table-frame">
      <el-table :data="rows" border v-loading="loading" :aria-busy="loading">
        <el-table-column label="选择" width="68" align="center"><template #default="{ row }"><el-checkbox :model-value="draft.some(item => item.id === row.id)" :disabled="loading || !!error || stale || (!draft.some(item => item.id === row.id) && !!reason(row))" :aria-label="`选择订金${row.number}`" @change="toggle(row, !!$event)"/></template></el-table-column>
        <el-table-column prop="number" label="原订金收款单" min-width="156"/>
        <el-table-column prop="received_on" label="到账日期" min-width="156"/>
        <el-table-column prop="deposit_amount" label="原收款（元）" min-width="156" align="right"/>
        <el-table-column prop="available_amount" label="未用金额（元）" min-width="156" align="right"/>
        <el-table-column label="状态 / 不可选原因" min-width="156"><template #default="{ row }">{{ reason(row) || '可选择' }}</template></el-table-column>
        <el-table-column label="原水单" min-width="156"><template #default="{ row }"><el-button v-for="file in row.attachments" :key="file.file_id" link type="primary" :title="file.original_name" @click="emit('preview', row.id, file)">{{ file.original_name }}</el-button><span v-if="!row.attachments.length">无水单记录</span></template></el-table-column>
        <template #empty>{{ error ? '加载失败，请重试' : loading ? '正在加载订金…' : q ? '没有匹配的订金收款单' : '本对账单暂无订金' }}</template>
      </el-table>
    </div></div>
    <p v-if="selectionError" class="selection-error" role="alert">{{ selectionError }}</p>
    <div class="selection-footer"><span>已选 {{ draft.length }} 笔 · 可用余额 {{ moneyText(selectedTotal) }} 元</span><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" :disabled="loading" @current-change="load"/></div>
    <template #footer><el-button @click="emit('update:modelValue', false)">取消</el-button><el-button type="primary" :disabled="loading || !!error || stale || !!selectionError" @click="confirm">确认选择</el-button></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
:global(.goods-deposit-dialog.el-dialog > .app-window-dialog__body){padding-top:12px;padding-bottom:12px}
.goods-deposit-dialog .selection-note{margin:0}
.goods-deposit-dialog .selection-search{margin:12px 0}
.selection-search>.el-button{margin-left:0}
.goods-deposit-table :deep(.el-button>span){display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.selection-note{font-size:12px;line-height:20px;color:var(--erp-color-text-secondary);overflow-wrap:anywhere}.selection-search{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.selection-search .el-input{width:260px;max-width:100%}.selection-footer{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:12px;font-size:12px}.selection-error{color:var(--el-color-danger);font-size:12px;line-height:20px}
.goods-deposit-table{min-width:0;margin-top:12px}.goods-deposit-table :deep(th.el-table__cell){height:38px;padding-block:0}.goods-deposit-table :deep(td.el-table__cell){height:40px;padding-block:0}.goods-deposit-table :deep(.cell){padding-inline:16px;line-height:18px;font-size:12px}.goods-deposit-table :deep(.is-right .cell){font-size:13px;font-weight:600;white-space:nowrap}.goods-deposit-table :deep(.el-button){max-width:100%;overflow:hidden;text-overflow:ellipsis}
.goods-deposit-table{height:auto;display:block}.goods-deposit-table .erp-list-table-frame{display:block;flex:none}.goods-deposit-table :deep(.el-table){width:100%;height:auto}
@media(prefers-reduced-motion:reduce){:deep(*),:deep(*::before),:deep(*::after){transition:none!important;animation:none!important;scroll-behavior:auto!important}}
</style>
