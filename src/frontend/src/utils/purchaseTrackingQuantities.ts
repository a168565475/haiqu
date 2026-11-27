import type { PurchaseTrackingArrival, PurchaseTrackingCoverage } from '@/types/purchaseTracking'

// 仅排版十进制字符串，不使用浮点重算数量，也不把未知量补成 0。
function quantity(value: string | null, unit: string | null): string {
  if (value === null) return '—'
  if (!/^-?\d+(?:\.\d+)?$/.test(value)) return '待核对'
  const [integer = '', fraction = ''] = value.split('.')
  const decimals = fraction.replace(/0+$/, '')
  const formatted = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (decimals ? `.${decimals}` : '')
  return `${formatted} ${unit || '（单位待核对）'}`
}
export function arrivalQuantity(row: PurchaseTrackingArrival, field: 'ordered' | 'received' | 'unreceived'): string {
  if (String(row.unit || '').toUpperCase() === 'KG') {
    const weight = row[`${field}_weight_kg`]
    return quantity(weight ?? row[`${field}_quantity`], 'kg')
  }
  const useRoots = [row.ordered_root_count, row.received_root_count, row.unreceived_root_count].every(value => value !== null)
  return quantity(useRoots ? row[`${field}_root_count`] : row[`${field}_quantity`], useRoots ? '根' : row.unit)
}
export function arrivalProgressQuantity(row: PurchaseTrackingArrival, field: 'accepted' | 'pending_quality' | 'return'): string {
  if (String(row.unit || '').toUpperCase() === 'KG') {
    const weight = field === 'accepted' ? row.accepted_weight_kg : field === 'pending_quality' ? row.pending_quality_weight_kg : row.return_weight_kg
    const fallback = field === 'accepted' ? row.accepted_quantity : field === 'pending_quality' ? row.pending_quality_quantity : row.return_quantity
    return quantity(weight ?? fallback, 'kg')
  }
  const value = field === 'accepted' ? row.accepted_quantity : field === 'pending_quality' ? row.pending_quality_quantity : row.return_quantity
  return quantity(value, row.unit)
}
export function coverageQuantity(row: PurchaseTrackingCoverage, field: 'required' | 'purchased' | 'remaining'): string {
  if (String(row.unit || '').toUpperCase() === 'KG') return quantity(row[`${field}_quantity`], 'kg')
  const useRoots = [row.required_root_count, row.purchased_root_count, row.remaining_root_count].every(value => value !== null)
  return quantity(useRoots ? row[`${field}_root_count`] : row[`${field}_quantity`], useRoots ? '根' : row.unit)
}
