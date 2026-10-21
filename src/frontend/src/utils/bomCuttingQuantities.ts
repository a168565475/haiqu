import { decimalUnits } from './outsourcingQuantities'

export interface CuttingParameters {
  cutting_pieces_per_set?: string | number | null
  fabric_meters_per_piece?: string | null
  cutting_sets_per_product?: string | number | null
}

/** 管材旧口径只显示已有裁片数量，不写回布料的新参数。 */
export function legacyPipeCuttingValues(line: {
  category: string; cutting_category: string; cut_piece_quantity: string; fabric_meters_per_set?: string | null
} | null | undefined) {
  if (!line || !`${line.category || ''} ${line.cutting_category || ''}`.includes('管材')) return null
  const piecesUnits = decimalUnits(line.cut_piece_quantity)
  if (piecesUnits === null || piecesUnits <= 0n || piecesUnits % 10000n !== 0n) return null
  const pieces = piecesUnits / 10000n
  return {
    pieces: String(pieces),
    sets: '1',
  }
}

export interface CuttingCalculation {
  mode: 'legacy' | 'incomplete' | 'invalid' | 'valid'
  error: string
  piecesPerSet: string
  setsPerProduct: string
  orderSets: string
  orderPieces: string
}

const integerMaximum = 99999999999999n

function positiveInteger(value: unknown): bigint | null {
  const text = String(value ?? '').trim()
  if (!/^\d{1,14}$/.test(text)) return null
  const number = BigInt(text)
  return number > 0n && number <= integerMaximum ? number : null
}

/** 只根据每套片数和每成品套数计算订单数量，不参与面料耗米核算。 */
export function cuttingCalculation(line: CuttingParameters, orderQuantity: unknown): CuttingCalculation {
  const result: CuttingCalculation = {
    mode: 'legacy', error: '', piecesPerSet: '', setsPerProduct: '', orderSets: '', orderPieces: '',
  }
  const values = [line.cutting_pieces_per_set, line.cutting_sets_per_product]
  const filled = values.filter(value => String(value ?? '').trim() !== '').length
  if (!filled) return result
  if (filled !== 2) return { ...result, mode: 'incomplete', error: '请同时填写裁片量（片/套）和每成品套数（套/成品）。' }
  const pieces = positiveInteger(line.cutting_pieces_per_set)
  const sets = positiveInteger(line.cutting_sets_per_product)
  if (pieces === null || sets === null) return { ...result, mode: 'invalid', error: '裁片量（片/套）和每成品套数必须为正整数，且不能超过十四位。' }
  const order = decimalUnits(orderQuantity)
  if (order === null || order <= 0n || order % 10000n !== 0n) return { ...result, mode: 'invalid', error: 'BOM 订单数量须为正整数，才能计算裁剪套数和片数。' }
  const orderSets = order / 10000n * sets
  if (orderSets > integerMaximum || orderSets * pieces > integerMaximum) return { ...result, mode: 'invalid', error: '订单裁剪套数或片数超出十四位范围，请检查数量。' }
  return {
    mode: 'valid', error: '', piecesPerSet: String(pieces), setsPerProduct: String(sets),
    orderSets: String(orderSets), orderPieces: String(orderSets * pieces),
  }
}

/** 只投影片数和套数；历史米数及面料采购用量不反推、不覆盖。 */
export function cuttingCompatibilityValues(line: CuttingParameters, orderQuantity: unknown) {
  const calculation = cuttingCalculation(line, orderQuantity)
  if (calculation.mode !== 'valid') return null
  return {
    cutting_pieces_per_set: Number(calculation.piecesPerSet),
    cutting_sets_per_product: Number(calculation.setsPerProduct),
    cut_piece_quantity: calculation.piecesPerSet,
    unit: '套',
  }
}
