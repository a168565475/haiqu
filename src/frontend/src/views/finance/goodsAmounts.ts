// 只做输入辅助及预览，提交后以服务端锁定记录的 Decimal 结果为准。
const maxCents = 9999999999999999999999n

export function moneyCents(value: string): bigint | null {
  if (!/^\d+(\.\d{1,2})?$/.test(value)) return null
  const [whole = '0', fraction = ''] = value.split('.')
  const significant = whole.replace(/^0+/, '') || '0'
  if (significant.length > 20) return null
  const amount = BigInt(significant) * 100n + BigInt(fraction.padEnd(2, '0'))
  return amount <= maxCents ? amount : null
}

export function moneyText(value: bigint | null): string {
  if (value === null) return '—'
  const absolute = value < 0n ? -value : value
  return `${value < 0n ? '-' : ''}${absolute / 100n}.${(absolute % 100n).toString().padStart(2, '0')}`
}

export function totalCents(values: string[]): bigint | null {
  let total = 0n
  for (const value of values) {
    const amount = moneyCents(value)
    if (amount === null) return null
    total += amount
    if (total > maxCents) return null
  }
  return total
}

export function previewGoods(outstanding: string, available: string, cash: bigint | null,
  allocated: bigint | null, discount: string) {
  const remaining = moneyCents(outstanding)
  const deposits = moneyCents(available)
  const concession = moneyCents(discount)
  if (remaining === null || deposits === null || cash === null || allocated === null || concession === null) {
    return { settled: null, after: null, availableAfter: null, error: '请填写有效金额，最多两位小数。' }
  }
  const settled = cash + allocated
  const after = remaining - settled - concession
  const availableAfter = deposits - allocated
  const error = settled <= 0n ? '本次必须有实际到账或订金抵扣。'
    : allocated > deposits ? '本次订金核销金额超过可用余额，请调整核销金额。'
    : after < 0n ? `本次核销与折让超出当前未付 ${moneyText(-after)} 元。`
    : availableAfter > after ? `已收订金与本次到账、折让超出当前未付 ${moneyText(availableAfter - after)} 元，请核对实际收款。` : ''
  return { settled, after, availableAfter, error }
}
