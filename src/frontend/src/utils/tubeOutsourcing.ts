import type { TubeSourceRow } from '@/types/tubeOutsourcing'

export function wholeTubeQuantity(value: string): number | null {
  const text = value.trim()
  if (!/^\d+$/.test(text)) return null
  const result = Number(text)
  return Number.isSafeInteger(result) ? result : null
}

export function tubeRoots(quantity: string, piecesPerBar: string | null): number | null {
  if (!quantity.trim()) return 0
  const pieces = wholeTubeQuantity(quantity)
  if (pieces === 0) return 0
  const perBar = wholeTubeQuantity(piecesPerBar || '')
  if (pieces === null || !perBar || pieces % perBar !== 0) return null
  return pieces / perBar
}

export function tubeMeters(quantity: string, row: Pick<TubeSourceRow, 'pieces_per_bar' | 'raw_bar_length_m'>): string | null {
  const roots = tubeRoots(quantity, row.pieces_per_bar)
  if (roots === 0) return '0.00'
  const length = row.raw_bar_length_m || ''
  if (roots === null || !/^\d+(?:\.\d{1,2})?$/.test(length)) return null
  const [whole = '0', fraction = ''] = length.split('.')
  const cents = (BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))) * BigInt(roots)
  return `${cents / 100n}.${String(cents % 100n).padStart(2, '0')}`
}

export function tubeQuantityError(quantity: string, row: TubeSourceRow, raw: boolean): string {
  if (!quantity.trim()) return ''
  const pieces = wholeTubeQuantity(quantity)
  if (pieces === null) return `${row.part_name}：请填写整数支数，不支持负数、小数或文字。`
  if (!pieces) return ''
  if (row.blockers.length) return `${row.part_name}：${row.blockers.join('；')}`
  if (raw && (tubeRoots(quantity, row.pieces_per_bar) === null || tubeMeters(quantity, row) === null)) {
    return `${row.part_name}：每根切${row.pieces_per_bar || '—'}支，填写支数须能整除为根，请填写每根切割支数的整数倍。`
  }
  const maximum = wholeTubeQuantity(row.max_quantity)
  if (maximum === null || pieces > maximum) return `${row.part_name}：本次最多可发${row.max_quantity}支，不能超量。`
  return ''
}
