import { decimalFraction } from '@/views/boms/bomEditorHelpers'

export function packagingQuantity(unitsPerBox: string, orderQuantity: string | number | undefined): string {
  const box = decimalFraction(unitsPerBox)
  const order = decimalFraction(orderQuantity)
  if (!box || box.numerator <= 0n || box.numerator % box.denominator !== 0n || !order || order.numerator < 0n) return ''
  const numerator = order.numerator * box.denominator
  const denominator = order.denominator * box.numerator
  return String((numerator + denominator - 1n) / denominator)
}
