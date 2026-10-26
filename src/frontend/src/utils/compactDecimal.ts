// 只用于显示：不经过 Number 转换，不改变精度、计算或提交值。
export function compactDecimal(value: string | number | null | undefined, empty = '—'): string {
  if (value === null || value === undefined || value === '') return empty
  const text = String(value)
  const match = /^([+-]?(?:\d+|\d{1,3}(?:,\d{3})+))\.(\d+)$/.exec(text)
  if (!match) return text
  const fraction = match[2]!.replace(/0+$/, '')
  return fraction ? `${match[1]}.${fraction}` : match[1]!
}
