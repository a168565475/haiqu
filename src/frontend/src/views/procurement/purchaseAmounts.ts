export function decimalParts(value: string): { digits: bigint; scale: number } | null {
  const matched = /^(\d+)(?:\.(\d+))?$/.exec(value.trim())
  if (!matched) return null
  const fraction = matched[2] || ''
  return { digits: BigInt(`${matched[1] || '0'}${fraction}`), scale: fraction.length }
}

export function scaledProduct(quantity: string, price: string): bigint | null {
  const left = decimalParts(quantity)
  const right = decimalParts(price)
  if (!left || !right) return null
  const raw = left.digits * right.digits
  const rawScale = left.scale + right.scale
  if (rawScale === 4) return raw
  if (rawScale < 4) return raw * 10n ** BigInt(4 - rawScale)
  const divisor = 10n ** BigInt(rawScale - 4)
  return (raw + divisor / 2n) / divisor
}

export function formatScaled(value: bigint): string {
  const cents = (value + 50n) / 100n
  const whole = (cents / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${whole}.${(cents % 100n).toString().padStart(2, '0')}`
}
