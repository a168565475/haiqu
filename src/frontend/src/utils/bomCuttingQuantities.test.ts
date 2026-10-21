import { describe, expect, it } from 'vitest'
import { cuttingCalculation, cuttingCompatibilityValues } from './bomCuttingQuantities'

const chair = { cutting_pieces_per_set: '2', cutting_sets_per_product: '1' }

describe('BOM 裁剪片与套换算', () => {
  it('无需填写米数，105个成品每套2片即105套210片', () => {
    expect(cuttingCalculation(chair, '105.0000')).toEqual({ mode: 'valid', error: '', piecesPerSet: '2', setsPerProduct: '1', orderSets: '105', orderPieces: '210' })
  })
  it('每成品多套独立计算', () => {
    expect(cuttingCalculation({ cutting_pieces_per_set: 3, cutting_sets_per_product: 2 }, 7)).toMatchObject({ orderSets: '14', orderPieces: '42' })
  })
  it('旧每套耗米及旧裁片量不反推新字段，也不产生兼容投影', () => {
    const old = { fabric_meters_per_set: '0.125', cut_piece_quantity: '2', unit_consumption: '', cutting_pieces_per_set: null, fabric_meters_per_piece: null, cutting_sets_per_product: null }
    expect(cuttingCalculation(old, 105).mode).toBe('legacy')
    expect(cuttingCompatibilityValues(old, 105)).toBeNull()
    expect(old.fabric_meters_per_set).toBe('0.125')
    expect(old.cut_piece_quantity).toBe('2')
  })
  it('仅填每成品默认一套不能保存为新口径', () => {
    expect(cuttingCalculation({ cutting_sets_per_product: 1 }, 105).mode).toBe('incomplete')
  })
  it.each(['0', '-1', '1.5', '1e2', '100000000000000'])('拒绝无效的片数／套数 %s', value => {
    expect(cuttingCalculation({ ...chair, cutting_pieces_per_set: value }, 105).mode).toBe('invalid')
    expect(cuttingCalculation({ ...chair, cutting_sets_per_product: value }, 105).mode).toBe('invalid')
  })
  it.each([null, '', '0', '-0.1', '0.00001', '1e-4', 'NaN'])('历史米数 %s 不再参与裁剪数量核算', value => {
    expect(cuttingCalculation({ ...chair, fabric_meters_per_piece: value }, 105)).toEqual(cuttingCalculation(chair, 105))
  })
  it('大于32位的参数仍可精确计算，订单总套数和总片数不能超出十四位', () => {
    expect(cuttingCalculation({ ...chair, cutting_pieces_per_set: '2147483648' }, 1)).toMatchObject({ mode: 'valid', orderPieces: '2147483648' })
    expect(cuttingCalculation({ ...chair, cutting_sets_per_product: '99999999999999' }, 2).mode).toBe('invalid')
    expect(cuttingCalculation({ ...chair, cutting_pieces_per_set: '99999999999999' }, 2).mode).toBe('invalid')
  })
  it.each(['', '0', '105.5', '-1', '1e3'])('订单数量 %s 不能被四舍五入成套数', value => {
    expect(cuttingCalculation(chair, value).mode).toBe('invalid')
  })
  it('兼容字段只投影片数和套数，不写入任何耗米和面料采购用量', () => {
    expect(cuttingCompatibilityValues(chair, 105)).toEqual({ cutting_pieces_per_set: 2, cutting_sets_per_product: 1, cut_piece_quantity: '2', unit: '套' })
  })
})
