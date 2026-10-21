// 使用定点整数处理数量合计，避免小数累加误差及不同单位相加。
export function quantityValue(value: unknown): bigint | null {
  if (typeof value !== 'string' || !/^\d{1,18}(\.\d{1,4})?$/.test(value)) return null
  const [whole = '0', fraction = ''] = value.split('.')
  return BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
}

export function formatQuantity(value: unknown): string {
  const amount = quantityValue(value)
  if (amount === null) return '—'
  const fraction = (amount % 10000n).toString().padStart(4, '0').replace(/0+$/, '')
  return (amount / 10000n).toLocaleString('zh-CN') + (fraction ? `.${fraction}` : '')
}

export function quantityWithUnit(value: unknown, unit: string): string {
  const quantity = formatQuantity(value)
  return quantity === '—' ? quantity : `${quantity}${unit ? ` ${unit}` : ''}`
}

// 管材主数量直接使用已记录的根数，不能把计价米数改名为根数。
export function purchaseQuantityText(quantity: unknown, unit: string, rawBarLength: string | null | undefined, barCount: number | string | null | undefined): string {
  if (rawBarLength) return barCount === null || barCount === undefined ? '根数未记录' : quantityWithUnit(String(barCount), '根')
  return quantityWithUnit(quantity, unit)
}

export function quantityTotal(lines: { source_unit_text: string }[], values: unknown[]): string {
  if (!lines.length || new Set(lines.map(line => line.source_unit_text.trim())).size !== 1 || !lines[0]?.source_unit_text.trim()) return '—'
  const amounts = values.map(quantityValue)
  if (amounts.some(value => value === null)) return '—'
  const total = amounts.reduce<bigint>((sum, value) => sum + (value ?? 0n), 0n)
  return `${formatQuantity(`${total / 10000n}.${(total % 10000n).toString().padStart(4, '0')}`)} ${lines[0].source_unit_text}`
}

export function formatMoney(value: unknown): string {
  const amount = quantityValue(value)
  if (amount === null) return '—'
  const cents = (amount + 50n) / 100n
  return `${(cents / 100n).toLocaleString('zh-CN')}.${(cents % 100n).toString().padStart(2, '0')}`
}

export function formatUnitPrice(value: unknown): string {
  const formatted = formatQuantity(value)
  if (formatted === '—') return formatted
  const [whole, fraction = ''] = formatted.split('.')
  return `${whole}.${fraction.padEnd(2, '0')}`
}

export function formatTime(value: string | null | undefined, dateOnly = false): string {
  if (!value) return '—'
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return '—'
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    ...(dateOnly ? {} : { hour: '2-digit', minute: '2-digit' } as const),
  }).format(date)
}
