// 仅供表单展示和即时提示；保存后的金额以服务端 Decimal 结果为准。
export function receiptCents(value: string): bigint | null {
  if (!/^\d+(?:\.\d{1,2})?$/.test(value)) return null
  const [integer = '0', decimal = ''] = value.split('.')
  if (integer.replace(/^0+/, '').length > 20) return null
  return BigInt(integer) * 100n + BigInt(decimal.padEnd(2, '0'))
}
export function receiptMoney(value: bigint): string {
  const absolute = value < 0n ? -value : value
  return `${value < 0n ? '-' : ''}${absolute / 100n}.${String(absolute % 100n).padStart(2, '0')}`
}
export function receiptSum(values: string[]): string | null {
  let total = 0n
  for (const value of values) { const cents = receiptCents(value); if (cents === null) return null; total += cents }
  return receiptMoney(total)
}
