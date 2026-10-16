import type { ProductionTask, ProductionTaskProduct } from '@/types/productionTask'
export function isTaskReadyForScheduling(task: Pick<ProductionTask, 'status' | 'bom_status' | 'purchase_status'> | null) {
  return task?.status === 'READY' && task.bom_status === 'VERIFIED' && task.purchase_status === 'ORDER_COMPLETED'
}
export function productLabels(products: ProductionTaskProduct[]) {
  return products.map((item) => [item.customer_product_name || item.product_name || '未命名产品', item.item_number?.trim()].filter(Boolean).join(' · '))
}
export function productSpecifications(products: ProductionTaskProduct[]) {
  return products.map((item) => `${productLabels([item])[0]}：规格 ${item.specification_display || item.customer_specification || item.specification || '—'}；颜色 ${item.customer_color || item.color_name || item.color_code || '—'}；材质 ${item.material || '—'}`).join('\n')
}
export function quantityWithUnits(products: ProductionTaskProduct[]) {
  const groups = new Map<string, { name: string; quantity: number }>()
  for (const item of products) {
    const key = item.unit_id || item.unit_name || 'UNKNOWN'
    const current = groups.get(key) || { name: item.unit_name || item.unit_code || '单位未知', quantity: 0 }
    const value = Number(item.quantity)
    if (!Number.isFinite(value)) return '数量待确认'
    current.quantity += value
    groups.set(key, current)
  }
  return [...groups.values()].map((item) => `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(item.quantity)} ${item.name}`).join(' / ') || '—'
}
export function localAmountTotal(products: ProductionTaskProduct[]) {
  let amount = 0n
  for (const item of products) {
    const value = String(item.local_total_amount ?? '')
    if (!/^-?\d+(?:\.\d{1,4})?$/.test(value)) return '—'
    const [whole = '0', fraction = ''] = value.replace('-', '').split('.')
    amount += (BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))) * (value.startsWith('-') ? -1n : 1n)
  }
  const negative = amount < 0n
  const absolute = negative ? -amount : amount
  return `${negative ? '-' : ''}${(absolute / 10000n).toLocaleString('zh-CN')}.${String(absolute % 10000n).padStart(4, '0')}`
}
