type Amount = string | number | null | undefined

// 与后端 Decimal 的四位 HALF_UP 保持一致，避免先按总金额换算或浮点舍入差异。
export function multiplyAmount4(left: Amount, right: Amount): string | null {
  const parts = [left, right].map(value => String(value ?? '').trim().match(/^(\d+)(?:\.(\d+))?$/))
  if (parts.some(part => !part)) return null
  const [a, b] = parts as [RegExpMatchArray, RegExpMatchArray]
  const value = BigInt(`${a[1]}${a[2] || ''}`) * BigInt(`${b[1]}${b[2] || ''}`)
  const scale = (a[2]?.length || 0) + (b[2]?.length || 0)
  const divisor = 10n ** BigInt(Math.max(scale - 4, 0))
  const rounded = scale <= 4 ? value * 10n ** BigInt(4 - scale) : value / divisor + ((value % divisor) * 2n >= divisor ? 1n : 0n)
  const digits = rounded.toString().padStart(5, '0')
  return `${digits.slice(0, -4)}.${digits.slice(-4)}`
}

export function sumAmounts4(values: Array<string | null>): string | null {
  if (values.some(value => value === null)) return null
  const total = values.reduce((sum, value) => sum + BigInt(value!.replace('.', '')), 0n)
  const digits = total.toString().padStart(5, '0')
  return `${digits.slice(0, -4)}.${digits.slice(-4)}`
}
