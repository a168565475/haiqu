<script setup lang="ts">
import type { SupplierAmountItem } from '@/types/purchaseOrder'

withDefaults(defineProps<{
  suppliers: SupplierAmountItem[]
  currency?: string
  label?: string
  amountTitle?: string
}>(), { currency: '', label: '', amountTitle: '本单采购金额' })

function amountText(value: string | null, currency: string): string {
  const parts = /^(\d+)(?:\.(\d{1,4}))?$/.exec(value?.trim() || '')
  if (!parts) return '待核价'
  // 金额保留后端十进制字符串，避免大额采购转成浮点数后丢失精度。
  const whole = parts[1]!.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const fraction = (parts[2] || '').replace(/0+$/, '').padEnd(2, '0')
  const amount = `${whole}.${fraction}`
  return `${currency === 'CNY' ? '¥' : currency ? `${currency} ` : ''}${amount}`
}
</script>

<template>
  <ElPopover v-if="suppliers.length" placement="bottom" :width="420" trigger="hover" :show-after="150">
    <template #reference>
      <button type="button" class="supplier-summary-trigger" @click.stop>{{ label || (suppliers.length > 1 ? `共 ${suppliers.length} 家供应商` : suppliers[0]?.supplier_name || '—') }}</button>
    </template>
    <div class="supplier-popover-heading"><strong>供应商</strong><span>{{ amountTitle }}</span></div>
    <div class="supplier-popover-list" tabindex="0" :aria-label="`供应商${amountTitle}明细`">
      <div v-for="(supplier, index) in suppliers" :key="index" class="supplier-popover-row">
        <span>{{ supplier.supplier_name }}</span><strong>{{ amountText(supplier.total_amount, currency) }}</strong>
      </div>
    </div>
  </ElPopover>
  <span v-else>{{ label || '—' }}</span>
</template>

<style scoped lang="scss">
.supplier-summary-trigger { display: block; width: 100%; max-width: 100%; padding: 0; border: 0; background: transparent; color: var(--erp-color-brand); font: inherit; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
.supplier-summary-trigger:focus-visible { outline: 2px solid var(--erp-color-brand); outline-offset: 2px; }
.supplier-popover-heading, .supplier-popover-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px; align-items: start; }
.supplier-popover-heading { padding-bottom: 8px; border-bottom: 1px solid var(--erp-color-border); color: var(--erp-color-text-secondary); font-size: 12px; }
.supplier-popover-list { max-height: min(360px, 50vh); overflow-y: auto; }
.supplier-popover-row { padding: 9px 0; border-bottom: 1px solid var(--erp-color-border-subtle); font-size: 13px; line-height: 20px; }
.supplier-popover-row:last-child { border-bottom: 0; }
.supplier-popover-row > span { overflow-wrap: anywhere; }
.supplier-popover-row > strong { white-space: nowrap; color: var(--erp-color-brand); font-weight: 600; font-variant-numeric: tabular-nums; }
</style>
