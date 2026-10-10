import { decimalUnits } from './outsourcingQuantities'

export interface CuttingParameters {
  cutting_pieces_per_set?: string | number | null
  fabric_meters_per_piece?: string | null
  cutting_sets_per_product?: string | number | null
}

export interface CuttingCalculation {
  mode: 'legacy' | 'incomplete' | 'invalid' | 'valid'
  error: string
  piecesPerSet: string
  metersPerPiece: string
  setsPerProduct: string
  metersPerSet: string
  orderSets: string
  orderPieces: string
  totalMeters: string
}

const integerMaximum = 99999999999999n
const decimalMaximum = 999999999999999999n

function positiveInteger(value: unknown): bigint | null {
  const text = String(value ?? '').trim()
  if (!/^\d{1,14}$/.test(text)) return null
  const number = BigInt(text)
  return number > 0n && number <= integerMaximum ? number : null
}

function decimalText(value: bigint): string {
  const fraction = String(value % 10000n).padStart(4, '0').replace(/0+$/, '')
  return `${value / 10000n}${fraction ? `.${fraction}` : ''}`
}

/** 所有米数均以万分之一米的整数计算，不用浮点数相乘。 */
export function cuttingCalculation(line: CuttingParameters, orderQuantity: unknown): CuttingCalculation {
  const result: CuttingCalculation = {
    mode: 'legacy', error: '', piecesPerSet: '', metersPerPiece: '', setsPerProduct: '',
    metersPerSet: '', orderSets: '', orderPieces: '', totalMeters: '',
  }
  const values = [line.cutting_pieces_per_set, line.fabric_meters_per_piece, line.cutting_sets_per_product]
  const filled = values.filter(value => String(value ?? '').trim() !== '').length
  if (!filled) return result
  if (filled !== 3) return { ...result, mode: 'incomplete', error: '请同时填写裁片量（片/套）、单个用量（米/片）和每成品套数（套/成品）。' }
  const pieces = positiveInteger(line.cutting_pieces_per_set)
  const sets = positiveInteger(line.cutting_sets_per_product)
  if (pieces === null || sets === null) return { ...result, mode: 'invalid', error: '裁片量（片/套）和每成品套数必须为正整数，且不能超过十四位。' }
  const meters = decimalUnits(line.fabric_meters_per_piece)
  if (meters === null || meters <= 0n) return { ...result, mode: 'invalid', error: '单个用量（米/片）必须为正数，最多四位小数、十四位整数。' }
  const order = decimalUnits(orderQuantity)
  if (order === null || order <= 0n || order % 10000n !== 0n) return { ...result, mode: 'invalid', error: 'BOM 订单数量须为正整数，才能计算裁剪套数和片数。' }
  const metersPerSet = pieces * meters
  const orderSets = order / 10000n * sets
  const totalMeters = orderSets * metersPerSet
  if (orderSets > integerMaximum || orderSets * pieces > integerMaximum) return { ...result, mode: 'invalid', error: '订单裁剪套数或片数超出十四位范围，请检查数量。' }
  if (metersPerSet > decimalMaximum || totalMeters > decimalMaximum) return { ...result, mode: 'invalid', error: '裁剪耗米计算结果超出范围，请检查片数、单个用量和订单数量。' }
  return {
    mode: 'valid', error: '', piecesPerSet: String(pieces), metersPerPiece: decimalText(meters), setsPerProduct: String(sets),
    metersPerSet: decimalText(metersPerSet), orderSets: String(orderSets), orderPieces: String(orderSets * pieces), totalMeters: decimalText(totalMeters),
  }
}

/** 只投影已经补齐的新参数；旧记录的原每套耗米和旧裁片量不反推、不覆盖。 */
export function cuttingCompatibilityValues(line: CuttingParameters, orderQuantity: unknown) {
  const calculation = cuttingCalculation(line, orderQuantity)
  if (calculation.mode !== 'valid') return null
  return {
    cutting_pieces_per_set: Number(calculation.piecesPerSet),
    fabric_meters_per_piece: calculation.metersPerPiece,
    cutting_sets_per_product: Number(calculation.setsPerProduct),
    fabric_meters_per_set: calculation.metersPerSet,
    cut_piece_quantity: calculation.piecesPerSet,
    unit_consumption: calculation.metersPerPiece,
    unit: '套',
  }
}
