import type { MaterialAttributeField, SupplierPurchaseSheetLine } from '@/types/purchaseOrder'

const colorKeys = new Set(['hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color'])

const text = (value: unknown): string => value == null ? '' : String(value).trim()

export function formatPurchaseSheetNumber(value: number | string | null | undefined, emptyValue = '—'): string {
  const raw = text(value)
  const match = /^([+-]?\d+)(?:\.(\d+))?$/.exec(raw)
  if (!match) return emptyValue
  const integer = match[1]!.replace(/^([+-]?)0+(?=\d)/, '$1')
  const fraction = (match[2] || '').replace(/0+$/, '')
  const result = fraction ? `${integer}.${fraction}` : integer
  return /^[+-]?0$/.test(result) ? '0' : result
}

export function purchaseSheetSourceFields(line: SupplierPurchaseSheetLine, sampleSource = false): { attributes: MaterialAttributeField[]; colors: string[] } {
  const result = { attributes: [] as MaterialAttributeField[], colors: [] as string[] }
  const seen = new Set<string>()
  const fields = line.material_attributes_snapshot?.fields
  for (const field of Array.isArray(fields) ? fields : []) {
    if (!field || typeof field !== 'object') continue
    const key = text(field.key), label = text(field.label), value = text(field.value)
    if (!label || !value || key === 'tube_coating_color' || label === '喷塑颜色') continue
    if (['part_name', 'material', 'specification'].includes(key) || ['品名', '部件名称', '材质', '规格'].includes(label)) continue
    if (!sampleSource && (colorKeys.has(key) || label === '颜色')) {
      if (!result.colors.includes(value)) result.colors.push(value)
      continue
    }
    const identity = `${label}：${value}`
    if (seen.has(identity)) continue
    seen.add(identity)
    result.attributes.push({ key, label, value })
  }
  return result
}

export function purchaseSheetLineDisplay(line: SupplierPurchaseSheetLine, sampleSource = false): { specification: string; attributes: string; color: string } {
  const fields = purchaseSheetSourceFields(line, sampleSource)
  const attributes = [
    text(line.material) && `材质：${text(line.material)}`,
    ...fields.attributes.map(field => `${field.label}：${field.value}`),
    !sampleSource && text(line.remark) && `要求：${text(line.remark)}`,
  ].filter(Boolean).join('；')
  return { specification: text(line.specification), attributes, color: sampleSource ? text(line.remark) : fields.colors.join(' / ') }
}
