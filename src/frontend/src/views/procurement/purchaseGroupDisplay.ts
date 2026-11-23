import type { PurchaseGroup, PurchaseGroupProduct, PurchaseGroupSourceSnapshot } from '@/types/purchaseGroup'
import { materialAttributeFields } from '@/utils/materialAttributes'

export function groupProductSummary(group: PurchaseGroup) {
  const products = group.products?.length ? group.products : group.product ? [group.product] : []
  const column = (value: (product: PurchaseGroupProduct) => string, empty = '—') =>
    products.map(product => value(product) || empty).join('\n') || empty
  return {
    name: column(product => product.product_name, '来源待核对'),
    specification: column(product => product.specification),
    color: column(product => [product.color_card, product.color_name, product.color_code].filter(Boolean).join(' / ')),
    material: column(product => product.material),
    quantity: column(product => product.order_quantity ? [product.order_quantity, product.order_unit].filter(Boolean).join(' ') : ''),
  }
}

export function purchaseFabricColor(snapshot: PurchaseGroupSourceSnapshot): string {
  if (snapshot.material_selection_snapshot?.category_key !== 'FABRIC' && snapshot.section_type_snapshot !== 'FABRIC') return ''
  return materialAttributeFields(snapshot).filter(field => ['色卡', '颜色', '色号'].includes(field.label))
    .map(field => field.value).join(' / ')
}

export function purchaseGroupBatchCount(group: PurchaseGroup): number {
  return new Set(group.batches.map(batch => batch.batch_number)).size
}
