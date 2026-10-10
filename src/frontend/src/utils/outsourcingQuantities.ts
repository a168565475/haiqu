import { pipeMeters } from './pipeQuantities'
import type { OutsourcingConversion } from '@/types/outsourcing'

export function decimalUnits(value: unknown): bigint | null {
  const text = String(value ?? '').trim()
  if (!/^\d{1,14}(?:\.\d{1,4})?$/.test(text)) return null
  const [whole = '0', fraction = ''] = text.split('.')
  return BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
}

function decimalText(value: bigint): string {
  return `${value / 10000n}.${String(value % 10000n).padStart(4, '0')}`
}

export function outsourcingPlan(value: unknown, basis?: OutsourcingConversion | null) {
  const input = decimalUnits(value)
  const invalid = { error: '请输入有效的正数，最多四位小数。', output: '', raw: '', meters: '', remainder: '' }
  if (input === null || input <= 0n || !basis) return invalid
  if (basis.kind === 'PIPE') {
    const cuts = BigInt(basis.pieces_per_bar || 0)
    if (input % 10000n || cuts <= 0n || input / 10000n % cuts) return { ...invalid, error: `本次支数须为 ${cuts} 的整数倍。` }
    const roots = input / 10000n / cuts
    return { error: '', output: String(input / 10000n), raw: String(roots), meters: pipeMeters(String(roots), basis.raw_bar_length_m), remainder: '0' }
  }
  if (basis.kind === 'FABRIC') {
    const usage = decimalUnits(basis.fabric_meters_per_set)
    if (usage === null || usage <= 0n) return { ...invalid, error: '缺少每套耗米。' }
    return { error: '', output: String(input / usage), raw: decimalText(input), meters: decimalText(input), remainder: decimalText(input % usage) }
  }
  return { error: '', output: decimalText(input), raw: decimalText(input), meters: '', remainder: '' }
}
