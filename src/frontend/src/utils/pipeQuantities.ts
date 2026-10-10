/** 根米预览用整数运算；最终数量仍由后端重新计算。 */
export function pipeMeters(roots: string | number | null | undefined, length: string | null | undefined): string {
  const count = String(roots ?? '').trim()
  if (!/^\d{1,14}$/.test(count) || !/^\d{1,14}(?:\.\d{1,2})?$/.test(length || '')) return ''
  const [whole = '0', fraction = ''] = length!.split('.')
  const total = BigInt(count) * (BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0')))
  return `${total / 100n}.${String(total % 100n).padStart(2, '0')}`
}

export function pipeRootError(roots: unknown): string {
  if (!/^\d{1,14}$/.test(String(roots ?? '')) || BigInt(String(roots)) <= 0n) return '管材根数必须为正整数。'
  return ''
}
