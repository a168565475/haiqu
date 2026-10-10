import type { OutsourcingQuantitySummary, UnifiedOutsourcingOrder } from '@/types/unifiedOutsourcing'

function quantityText(amounts: OutsourcingQuantitySummary[] | undefined): string {
  if (!amounts?.length) return '—'
  return amounts.map(amount => {
    if (amount.quantity === null || amount.quantity === undefined || String(amount.quantity).trim() === '') return '—'
    const value = Number(amount.quantity)
    return Number.isFinite(value) && value >= 0 ? `${value.toLocaleString('zh-CN', { maximumFractionDigits: 4 })} ${amount.unit}` : '—'
  }).join(' / ')
}

export function unifiedQuantityText(row: UnifiedOutsourcingOrder, field: 'sent' | 'received' | 'shortage'): string {
  const tube = row.record_type === 'TUBE'
  if (field === 'sent') {
    if (!row.dispatched_quantities.length) return '未发出'
    return quantityText(row.dispatched_quantities)
  }
  if (field === 'shortage') return tube && row.receipt_state === 'RECORDED' ? quantityText(row.shortage_quantities) : '—'
  if (!tube) return row.returned_quantities.length ? quantityText(row.returned_quantities) : '未回货'
  if (row.receipt_state === 'RECORDED') return quantityText(row.returned_quantities)
  if (row.receipt_state === 'NOT_RECEIVED' && row.status !== 'CANCELLED' && row.status !== 'COMPLETED') return '未回货'
  return '—'
}

export function unifiedProductAttribute(row: UnifiedOutsourcingOrder, field: 'product_number' | 'item_number' | 'color_name'): string {
  if (row.product_count > 1) return '多款'
  return row.product[field] || '—'
}
