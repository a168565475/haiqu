<script setup lang="ts">
import { computed } from 'vue'
import type { PurchaseGroupSourceSnapshot } from '@/types/purchaseGroup'
import { compactDecimal } from '@/utils/compactDecimal'

const props = defineProps<{
  contributions: NonNullable<PurchaseGroupSourceSnapshot['source_contributions']>
}>()

const products = computed(() => {
  const totals = new Map<string, { label: string; unit: string; quantity: bigint }>()
  for (const part of props.contributions) {
    const row = totals.get(part.product_line_id) ?? {
      label: [part.product_name, part.product_color].filter(Boolean).join(' · '), unit: part.source_unit_text, quantity: 0n,
    }
    // 采购需求存四位小数，同一产品多个部位用到的相同物料要合计展示。
    const [whole, fraction = ''] = part.required_quantity.split('.')
    row.quantity += BigInt(whole + fraction.padEnd(4, '0'))
    totals.set(part.product_line_id, row)
  }
  return Array.from(totals, ([id, row]) => ({ id, ...row,
    displayQuantity: compactDecimal(`${row.quantity / 10000n}.${String(row.quantity % 10000n).padStart(4, '0')}`),
  }))
})
</script>

<template>
  <ElPopover trigger="click" placement="bottom-end" :width="300" :persistent="false">
    <template #reference><button type="button" class="quantity-source-trigger" aria-label="查看各产品的 BOM 建议量"><slot /></button></template>
    <strong>各产品的 BOM 建议量</strong>
    <div v-for="product in products" :key="product.id" class="quantity-source-row">
      <span>{{ product.label }}</span>
      <span>{{ product.displayQuantity }} {{ product.unit }}</span>
    </div>
  </ElPopover>
</template>

<style scoped>
.quantity-source-trigger { appearance: none; border: 0; background: none; padding: 0; font: inherit; color: var(--erp-color-brand); text-decoration: underline dotted; text-underline-offset: 3px; cursor: pointer; }
.quantity-source-row { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-top: 6px; }
.quantity-source-row > span:last-child { white-space: nowrap; }
</style>
