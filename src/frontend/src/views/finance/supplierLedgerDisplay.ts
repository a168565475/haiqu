import { isAxiosError } from 'axios'

export function ledgerToday() {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format()
}

export function ledgerMoney(value: string | null) {
  return value === null ? '—' : value.replace(/\B(?=(\d{3})+\.)/g, ',')
}

export function amountInCents(value: string, wholeDigits = 20): bigint | null {
  value = value.trim()
  if (!/^\d+(\.\d{1,2})?$/.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  if (whole!.length > wholeDigits) return null
  return BigInt(whole!) * 100n + BigInt(fraction.padEnd(2, '0'))
}

export function moneyFromCents(cents: bigint) {
  return ledgerMoney((cents / 100n).toString() + '.' + (cents % 100n).toString().padStart(2, '0'))
}

export function ledgerRequestError(cause: unknown, fallback: string) {
  if (isAxiosError(cause)) return cause.response?.data?.error?.message || fallback
  return fallback
}
