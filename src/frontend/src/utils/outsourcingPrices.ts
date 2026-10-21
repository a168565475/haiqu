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

export function outsourcingLineAmount(quantity: string, unitPrice: string): string | null {
  const cents = priceCents(unitPrice)
  return /^\d+$/.test(quantity.trim()) && cents !== null ? centsText(BigInt(quantity.trim()) * cents) : null
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

export function formatOutsourcingMoney(value: unknown, missing = '未录入'): string {
  if (typeof value !== 'string' || !/^\d+(?:\.\d+)?$/.test(value)) return missing
  const [whole = '0', fraction = ''] = value.split('.')
  const decimal = fraction.replace(/0+$/, '')
  return `${BigInt(whole).toLocaleString('zh-CN')}${decimal ? `.${decimal}` : ''}`
}
