import type { ExtractedField, ImportPayload, ProductionTaskImport } from '@/types/productionTaskImport'
export const importHeaderFields = [
  ['task_number', 'task_number_suggestion', '任务编号'], ['order_date', 'order_date', '下单日期'],
  ['delivery_date', 'delivery_date', '交期'], ['salesperson_id', 'salesperson_text', '业务员'],
  ['follower_ids', 'followers_text', '生产跟单员'], ['includes_tax', 'includes_tax', '是否含税'],
  ['tax_rate', 'tax_rate', '税率'], ['order_tolerance_percent', 'order_tolerance_percent', '订单误差'],
  ['is_repeat_order', 'is_repeat_order', '是否返单'], ['preproduction_sample_required', 'preproduction_sample_required', '产前样'],
  ['delivery_method', 'delivery_method', '交货方式'],
] as const
export const importProductFields = [
  ['customer_product_name', 'product_name', '产品名称'], ['customer_specification', 'specification', '规格'],
  ['customer_color', 'color', '颜色'], ['material', 'material', '材质'], ['quantity', 'quantity', '数量'],
  ['unit_id', 'unit_text', '单位'], ['unit_price', 'unit_price_cny', '人民币单价'],
  ['special_requirements', 'production_requirements', '生产要求'], ['packaging_method', 'packaging_requirements', '包装要求'],
] as const
export function importedText(field?: ExtractedField): string { return field?.status === 'EXTRACTED' && typeof field.value === 'string' ? field.value : '' }
export function importedBoolean(field?: ExtractedField): boolean { return field?.status === 'EXTRACTED' && field.value === true }
export function reviewRows(record: ProductionTaskImport, payload: ImportPayload) {
  const rows = importHeaderFields.map(([target, source, label]) => ({
    key: target as string, label: label as string, source: record.extraction.fields?.[source], value: payload[target],
  }))
  for (const [index, product] of (record.extraction.products || []).entries()) {
    const current = payload.products.find(row => row.client_key === product.line_key)
    for (const [target, source, label] of importProductFields) rows.push({
      key: `products.${product.line_key}.${target}`, label: `产品 ${index + 1} · ${label}`,
      source: product.fields[source], value: current?.[target] ?? '',
    })
  }
  return rows
}
