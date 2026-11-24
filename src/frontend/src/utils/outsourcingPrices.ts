import type { OutsourcingPriceUnit } from '@/types/tubeOutsourcing'

export function outsourcingPriceError(value: string): string {
  return /^\d{1,14}(?:\.\d{1,2})?$/.test(value.trim()) ? '' : '请填写非负加工单价，最多14位整数、2位小数。'
}

function priceCents(value: string): bigint | null {
  if (outsourcingPriceError(value)) return null
  const [whole = '0', fraction = ''] = value.trim().split('.')
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
}

function centsText(value: bigint): string {
  return `${value / 100n}.${String(value % 100n).padStart(2, '0')}`
}

function unitAreaTenThousandths(value: string | null | undefined): bigint | null {
  if (typeof value !== 'string' || !/^\d{1,14}(?:\.\d{1,4})?$/.test(value.trim())) return null
  const [whole = '0', fraction = ''] = value.trim().split('.')
  const area = BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
  return area > 0n ? area : null
}

function areaText(value: bigint): string {
  return `${value / 10000n}.${String(value % 10000n).padStart(4, '0')}`
}

function roundHalfEven(value: bigint, divisor: bigint): bigint {
  const quotient = value / divisor
  const remainder = value % divisor
  const doubled = remainder * 2n
  if (doubled < divisor) return quotient
  if (doubled > divisor) return quotient + 1n
  return quotient % 2n === 0n ? quotient : quotient + 1n
}

export function outsourcingLineArea(quantity: string, unitArea: string | null | undefined): string | null {
  const area = unitAreaTenThousandths(unitArea)
  return /^\d+$/.test(quantity.trim()) && area !== null
    ? areaText(BigInt(quantity.trim()) * area)
    : null
}

export function outsourcingLineAmount(
  quantity: string,
  unitPrice: string,
  priceUnit: OutsourcingPriceUnit = 'PIECE',
  unitArea?: string | null,
): string | null {
  const cents = priceCents(unitPrice)
  if (!/^\d+$/.test(quantity.trim()) || cents === null) return null
  const count = BigInt(quantity.trim())
  if (priceUnit === 'PIECE') return centsText(count * cents)
  const area = unitAreaTenThousandths(unitArea)
  return area === null ? null : centsText(roundHalfEven(count * area * cents, 10000n))
}

export function sumOutsourcingAmounts(values: Array<string | null>): string | null {
  let total = 0n
  for (const value of values) {
    if (value === null || !/^\d+(?:\.\d{1,2})?$/.test(value)) return null
    const [whole = '0', fraction = ''] = value.split('.')
    total += BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
  }
  return centsText(total)
}

export function sumOutsourcingAreas(values: Array<string | null>): string | null {
  let total = 0n
  for (const value of values) {
    if (value === null || !/^\d+(?:\.\d{1,4})?$/.test(value)) return null
    const [whole = '0', fraction = ''] = value.split('.')
    total += BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
  }
  return areaText(total)
}

export function formatOutsourcingMoney(value: unknown, missing = '未录入'): string {
  if (typeof value !== 'string' || !/^\d+(?:\.\d+)?$/.test(value)) return missing
  const [whole = '0', fraction = ''] = value.split('.')
  const decimal = fraction.replace(/0+$/, '')
  return `${BigInt(whole).toLocaleString('zh-CN')}${decimal ? `.${decimal}` : ''}`
}
