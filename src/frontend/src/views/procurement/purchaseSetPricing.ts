import type { PurchaseOrderSourceLine, PurchaseSetPricing } from '@/types/purchaseOrder'
import type { PurchaseGroup } from '@/types/purchaseGroup'
import { compactDecimal } from '@/utils/compactDecimal'
import { formatScaled, scaledProduct } from './purchaseAmounts'

export interface SetPricingLine extends Pick<PurchaseOrderSourceLine, 'part_name' | 'material' | 'raw_material' | 'specification' | 'source_unit_text'> {
  purchase_group_line_id?: string | null
  set_pricing?: PurchaseSetPricing | null
  supplier_id: string | null
  delivery_date: string | null
}

export interface SetPricingChange {
  anchorId: string
  pricing: PurchaseSetPricing | null
  members: string[]
  supplierId: string | null
  deliveryDate: string
}

export function orderSetQuantity(group: PurchaseGroup | null): string {
  const products = group?.products?.length ? group.products : group?.product ? [group.product] : []
  let total = 0
  for (const product of products) {
    const quantity = compactDecimal(product.order_quantity, '')
    if (!/^[1-9]\d{0,13}$/.test(quantity)) return ''
    total += Number(quantity)
    if (total >= 1e14) return ''
  }
  return total ? String(total) : ''
}

export function applySetPricing(lines: SetPricingLine[], change: SetPricingChange) {
  const members = new Set(change.members)
  for (const line of lines) {
    if (line.purchase_group_line_id && members.has(line.purchase_group_line_id) && change.pricing) {
      line.set_pricing = change.pricing
      line.supplier_id = change.supplierId
      line.delivery_date = change.deliveryDate
    } else if (line.set_pricing?.anchor_id === change.anchorId) {
      line.set_pricing = null
    }
  }
}

export function syncSetTerm(lines: SetPricingLine[], source: SetPricingLine, field: 'supplier_id' | 'delivery_date') {
  if (!source.set_pricing) return
  for (const line of lines) {
    if (line.set_pricing?.anchor_id === source.set_pricing.anchor_id) line[field] = source[field]
  }
}

export function setPriceText(line: Pick<SetPricingLine, 'set_pricing' | 'purchase_group_line_id'>) {
  const pricing = line.set_pricing
  if (!pricing) return ''
  return pricing.anchor_id === line.purchase_group_line_id
    ? `${pricing.quantity} 套 × ${compactDecimal(pricing.unit_price)} 元/套`
    : '已含套价'
}

export function setAmount(quantity: number, price: string) {
  if (!Number.isSafeInteger(quantity) || quantity < 1) return '—'
  const scaled = scaledProduct(String(quantity), price)
  return scaled === null ? '—' : formatScaled(scaled)
}

export function isBlankOrZeroPurchaseValue(value: string | null): boolean {
  const text = value?.trim()
  return !text || /^0+(?:\.0{1,4})?$/.test(text)
}

export function isExplicitZeroPrice(price: string) {
  return /^0+(?:\.0{1,4})?$/.test(price.trim())
}
