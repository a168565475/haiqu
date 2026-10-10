type WageMoneyValue = string | null | undefined

interface DecimalParts {
  negative: boolean
  integer: string
  fraction: string
}

function decimalParts(value: WageMoneyValue): DecimalParts | null {
  if (value === null || value === undefined) return null
  const match = value.trim().match(/^([+-]?)(?:(\d+)(?:\.(\d*))?|\.(\d+))$/)
  if (!match) return null
  return {
    negative: match[1] === '-',
    integer: (match[2] || '0').replace(/^0+(?=\d)/, ''),
    fraction: match[3] ?? match[4] ?? '',
  }
}

function roundedThousandths(parts: DecimalParts) {
  const fractionLength = parts.fraction.length
  const magnitude = BigInt(`${parts.integer}${parts.fraction}`)
  let scaled: bigint
  if (fractionLength <= 3) {
    scaled = magnitude * (10n ** BigInt(3 - fractionLength))
  } else {
    const divisor = 10n ** BigInt(fractionLength - 3)
    scaled = magnitude / divisor
    if ((magnitude % divisor) * 2n >= divisor) scaled += 1n
  }
  return parts.negative ? -scaled : scaled
}

function displayThousandths(value: bigint) {
  const negative = value < 0n
  const digits = (negative ? -value : value).toString().padStart(4, '0')
  const integer = digits.slice(0, -3)
  const fraction = digits.slice(-3).replace(/0+$/, '')
  const amount = fraction ? `${integer}.${fraction}` : integer
  return negative && value !== 0n ? `-${amount}` : amount
}

export function formatWageMoney(value: WageMoneyValue) {
  const parts = decimalParts(value)
  return parts ? `¥${displayThousandths(roundedThousandths(parts))}` : '—'
}

export function isPlainWageMoney(value: WageMoneyValue) {
  return decimalParts(value) !== null
}

export function sumWageAmounts(values: WageMoneyValue[]) {
  const validParts = values.map(decimalParts).filter((item): item is DecimalParts => Boolean(item))
  if (!validParts.length) return '0'
  const scaleDigits = Math.max(...validParts.map(item => item.fraction.length))
  const sum = validParts.reduce((total, item) => {
    const magnitude = BigInt(`${item.integer}${item.fraction}`) * (10n ** BigInt(scaleDigits - item.fraction.length))
    return total + (item.negative ? -magnitude : magnitude)
  }, 0n)
  const negative = sum < 0n
  const absolute = negative ? -sum : sum
  const scale = 10n ** BigInt(scaleDigits)
  const integer = absolute / scale
  const fraction = scaleDigits ? (absolute % scale).toString().padStart(scaleDigits, '0') : ''
  const parts = { negative, integer: integer.toString(), fraction }
  return displayThousandths(roundedThousandths(parts))
}
