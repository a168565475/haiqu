import type { ProductionTask, ProductionTaskListProduct } from '@/types/productionTask'
export function isTaskReadyForScheduling(task: Pick<ProductionTask, 'status' | 'has_confirmed_bom_product'> | null) {
  return task?.status === 'READY' && task.has_confirmed_bom_product === true
}
export function productLabels(products: ProductionTaskListProduct[]) {
  return products.map((item) => [item.customer_product_name || item.product_name || '未命名产品', item.item_number?.trim()].filter(Boolean).join(' · '))
}
export function productSpecifications(products: ProductionTaskListProduct[]) {
  return products.map((item) => `${productLabels([item])[0]}：规格 ${item.specification_display || item.customer_specification || item.specification || '—'}；颜色 ${item.customer_color || item.color_name || item.color_code || '—'}；材质 ${item.material || '—'}`).join('\n')
}
export function quantityWithUnits(products: ProductionTaskListProduct[]) {
  const groups = new Map<string, { name: string; quantity: number }>()
  for (const item of products) {
    const unitName = item.product_selection_snapshot?.unit_name || item.unit_name || item.unit_code || '单位未知'
    const key = item.unit_id || unitName
    const current = groups.get(key) || { name: unitName, quantity: 0 }
    const value = Number(item.quantity)
    if (!Number.isFinite(value)) return '数量待确认'
    current.quantity += value
    groups.set(key, current)
  }
  return [...groups.values()].map((item) => `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(item.quantity)} ${item.name}`).join(' / ') || '—'
}
export function localAmountTotal(products: ProductionTaskListProduct[]) {
  let amount = 0n
  for (const item of products) {
    const value = String(item.local_total_amount ?? '')
    if (!/^-?\d+(?:\.\d{1,4})?$/.test(value)) return '—'
    const [whole = '0', fraction = ''] = value.replace('-', '').split('.')
    amount += (BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))) * (value.startsWith('-') ? -1n : 1n)
  }
  const negative = amount < 0n
  const absolute = negative ? -amount : amount
  const fraction = absolute % 10000n
  return `${negative ? '-' : ''}${(absolute / 10000n).toLocaleString('zh-CN')}${fraction === 0n ? '' : `.${String(fraction).padStart(4, '0').replace(/0+$/, '')}`}`
}
