<script setup lang="ts">
import { ElButton, ElInput } from 'element-plus'
import type { BomDetail } from '@/types/bom'

const props = defineProps<{
  bom: BomDetail
  quantityMismatch: boolean
  quantityReason: string
  canVerify: boolean
  syncingQuantity: boolean
  canSync: boolean
}>()

const emit = defineEmits<{
  'update:quantityReason': [value: string]
  sync: []
}>()

function number(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(parsed) : String(value)
}
</script>

<template>
  <section class="card quantity-compare-card">
    <header><h2>数量对比与确认</h2><span>所有数量均按当前颜色产品明细范围计算</span></header>
    <div class="quantity-compare-grid">
      <label><span>订单依据数量</span><strong>{{ number(props.bom.order_quantity) }}</strong></label>
      <label><span>当前任务数量</span><strong>{{ number(props.bom.current_order_quantity) }}</strong></label>
      <label><span>Excel 原表数量</span><strong>{{ number(props.bom.source_quantity) }}</strong></label>
      <label class="difference"><span>数量差异</span><strong>{{ number(props.bom.quantity_difference) }}</strong></label>
      <label><span>生产批次数量</span><strong>{{ number(props.bom.batch_quantity) }}</strong></label>
      <ElInput
        v-if="props.quantityMismatch"
        :model-value="props.quantityReason"
        maxlength="500"
        show-word-limit
        placeholder="填写数量差异确认原因"
        :disabled="!props.canVerify"
        @update:model-value="emit('update:quantityReason', $event)"
      />
      <div v-else class="quantity-confirmed">数量一致，无需填写差异原因</div>
      <ElButton v-if="(props.bom.is_order_quantity_outdated || props.bom.is_order_product_outdated) && props.canSync" type="warning" plain :loading="props.syncingQuantity" @click="emit('sync')">同步订单信息</ElButton>
    </div>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;

.quantity-compare-card { @include detail.surface; margin: 10px 0 0 188px; padding: 10px 12px; }
.quantity-compare-card > header { display: flex; align-items: baseline; gap: 18px; }
.quantity-compare-card > header h2 { margin: 0; font-size: 17px; line-height: 26px; }
.quantity-compare-card > header span { color: var(--erp-color-text-secondary); font-size: 12px; }
.quantity-compare-grid { display: grid; grid-template-columns: repeat(5, minmax(120px, 1fr)) minmax(260px, 1.65fr) auto; align-items: stretch; margin-top: 10px; }
.quantity-compare-grid label { min-height: 64px; padding: 8px 12px; border: 1px solid var(--erp-color-border); border-right: 0; background: var(--erp-color-surface); }
.quantity-compare-grid label span, .quantity-compare-grid label strong { display: block; }
.quantity-compare-grid label span { color: var(--erp-color-text-secondary); font-size: 11px; }
.quantity-compare-grid label strong { margin-top: 8px; font-size: 18px; font-variant-numeric: tabular-nums; }
.quantity-compare-grid label.difference strong { color: var(--erp-color-warning); }
.quantity-compare-grid > .el-input, .quantity-confirmed { min-height: 64px; box-sizing: border-box; border: 1px solid var(--erp-color-border); }
.quantity-compare-grid > .el-input :deep(.el-input__wrapper) { border-radius: 0; box-shadow: none; }
.quantity-confirmed { display: flex; align-items: center; padding: 0 14px; color: var(--erp-color-success); background: var(--erp-color-success-soft); font-size: 12px; }
.quantity-compare-grid > .el-button { height: 58px; margin-left: 10px; }
.quantity-compare-card > header h2 { font-family: "Noto Serif SC", "Songti SC", serif; font-size: 17px; }
.quantity-compare-grid { margin-top: 7px; }
.quantity-compare-grid label, .quantity-compare-grid > .el-input, .quantity-confirmed { min-height: 58px; }
.quantity-compare-grid label strong { margin-top: 6px; font-size: 17px; }

@media (max-width: 1400px) {
  .quantity-compare-card { margin-left: 188px; }
  .quantity-compare-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
  .quantity-compare-grid label { border-right: 1px solid var(--erp-color-border); }
  .quantity-compare-grid > .el-button { min-width: 0; margin-left: 0; }
}
</style>
