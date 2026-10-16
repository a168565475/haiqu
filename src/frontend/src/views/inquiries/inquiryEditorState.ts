import type { InquiryItem, InquiryProductCandidate, InquiryRow } from '@/types/inquiry'
import { formatInquiryNumber } from './inquiryDetailState'

export function newInquiryKey(): string {
  if (globalThis.crypto.randomUUID) return globalThis.crypto.randomUUID()
  // 局域网 HTTP 页面没有 randomUUID，但仍提供 getRandomValues。
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6]! & 15) | 64
  bytes[8] = (bytes[8]! & 63) | 128
  const text = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('')
  return `${text.slice(0, 8)}-${text.slice(8, 12)}-${text.slice(12, 16)}-${text.slice(16, 20)}-${text.slice(20)}`
}

export function applyExistingProduct(item: InquiryItem, product: InquiryProductCandidate): InquiryItem {
  return {
    ...item,
    product_id: product.id,
    product_category_id: product.category_id,
    product_unit_id: product.unit_id,
    product_description: product.product_name,
    specification: product.specification,
    unit_code: product.unit_code,
    product_number_snapshot: product.product_number,
    product_code_snapshot: product.product_code,
    item_number_snapshot: product.item_number,
  }
}

export function invalidateProductLink(item: InquiryItem): InquiryItem {
  return {
    ...item,
    product_id: null,
    product_number_snapshot: '',
    product_code_snapshot: '',
    item_number_snapshot: '',
  }
}

export function decimalUnits(value: unknown, decimals = 4, integerDigits = 14): bigint | null {
  const text = String(value ?? '').trim()
  if (!new RegExp(`^\\d{1,${integerDigits}}(?:\\.\\d{1,${decimals}})?$`).test(text)) return null
  const [whole = '0', fraction = ''] = text.split('.')
  return BigInt(whole + fraction.padEnd(decimals, '0'))
}
function decimalString(value: bigint, decimals: number) {
  const digits = value.toString().padStart(decimals + 1, '0')
  return `${digits.slice(0, -decimals)}.${digits.slice(-decimals)}`
}
export function productAmount(items: InquiryItem[]): NonNullable<InquiryRow['product_amount']> {
  const totals = new Map<string, bigint>()
  let missing = 0
  for (const item of items) {
    const quantity = decimalUnits(item.quantity)
    const price = decimalUnits(item.target_unit_price)
    if (quantity === null || quantity <= 0n || price === null || !/^[A-Z]{3}$/.test(item.target_currency_code)) { missing++; continue }
    totals.set(item.target_currency_code, (totals.get(item.target_currency_code) ?? 0n) + quantity * price)
  }
  return { item_count: items.length, missing_price_count: missing, totals: [...totals].sort(([a], [b]) => a.localeCompare(b)).map(([currency_code, total]) => ({ currency_code, amount: decimalString(total, 8) })) }
}
export function quantitySummary(items: InquiryItem[]) {
  const totals = new Map<string, bigint>()
  for (const item of items) {
    const quantity = decimalUnits(item.quantity)
    if (quantity === null || quantity <= 0n || !item.unit_code.trim()) return '待补齐'
    totals.set(item.unit_code, (totals.get(item.unit_code) ?? 0n) + quantity)
  }
  return [...totals].map(([unit, total]) => `${formatInquiryNumber(decimalString(total, 4))} ${unit}`).join(' / ') || '—'
}
export function blankProduct(item: InquiryItem) {
  return !item.id && !item.product_description.trim() && !item.specification.trim() && !(item.color || '').trim() && !(item.material || '').trim() && !item.notes.trim() && !item.expected_date && (item.target_unit_price === null || item.target_unit_price === '') && String(item.quantity) === '1'
}
export function validateProducts(items: InquiryItem[]) {
  if (items.length > 200) return '单张询盘最多填写 200 条产品需求。'
  for (const [index, item] of items.entries()) {
    const prefix = `第 ${index + 1} 行`
    if (!item.product_description.trim()) return `${prefix}产品名称不能为空。`
    const quantity = decimalUnits(item.quantity)
    if (quantity === null || quantity <= 0n) return `${prefix}数量须大于零，最多 14 位整数和 4 位小数。`
    if (!item.unit_code.trim() || item.unit_code.length > 30) return `${prefix}单位不能为空，最多 30 个字符。`
    if (item.target_unit_price !== null && item.target_unit_price !== '') {
      if (decimalUnits(item.target_unit_price) === null) return `${prefix}目标价须为非负数，最多 14 位整数和 4 位小数。`
      if (!item.target_currency_code) return `${prefix}填写目标价后请选择币种。`
    }
  }
  return ''
}
export function validateAttachment(file: Pick<File, 'name' | 'size'>) {
  if (!/\.(pdf|xlsx|jpe?g|png)$/i.test(file.name)) return '附件仅支持 PDF、XLSX、JPG、JPEG、PNG。'
  if (!file.size || file.size > 10 * 1024 * 1024) return '附件必须大于 0 字节且不超过 10 MB。'
  return ''
}
export function validateProductImage(file: Pick<File, 'name' | 'size'>) {
  if (!/\.(jpe?g|png)$/i.test(file.name)) return '产品图片仅支持 JPG、JPEG、PNG。'
  if (!file.size || file.size > 10 * 1024 * 1024) return '产品图片必须大于 0 字节且不超过 10 MB。'
  return ''
}
