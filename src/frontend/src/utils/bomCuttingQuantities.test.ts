import { describe, expect, it } from 'vitest'
import { cuttingCalculation, cuttingCompatibilityValues } from './bomCuttingQuantities'

const chair = { cutting_pieces_per_set: '2', fabric_meters_per_piece: '0.125', cutting_sets_per_product: '1' }

describe('BOM 裁剪片、套、米换算', () => {
  it('椅面每套2片、每片0.125米，105个成品为105套210片26.25米', () => {
    expect(cuttingCalculation(chair, '105.0000')).toEqual({ mode: 'valid', error: '', piecesPerSet: '2', metersPerPiece: '0.125', setsPerProduct: '1', metersPerSet: '0.25', orderSets: '105', orderPieces: '210', totalMeters: '26.25' })
  })
  it('每成品多套独立计算，0.1米连乘不产生浮点尾数', () => {
    expect(cuttingCalculation({ cutting_pieces_per_set: 3, fabric_meters_per_piece: '0.1', cutting_sets_per_product: 2 }, 7)).toMatchObject({ metersPerSet: '0.3', orderSets: '14', orderPieces: '42', totalMeters: '4.2' })
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
  it.each(['0', '-0.1', '0.00001', '1e-4', 'NaN'])('拒绝无效或超过四位的每片耗米 %s', value => {
    expect(cuttingCalculation({ ...chair, fabric_meters_per_piece: value }, 105).mode).toBe('invalid')
  })
  it('保留万分之一米精度，并拒绝计算结果溢出', () => {
    expect(cuttingCalculation({ ...chair, fabric_meters_per_piece: '0.0001' }, 105).totalMeters).toBe('0.021')
    expect(cuttingCalculation({ ...chair, fabric_meters_per_piece: '99999999999999.9999' }, 105).mode).toBe('invalid')
  })
  it('大于32位的参数仍可精确计算，订单总套数和总片数不能超出十四位', () => {
    expect(cuttingCalculation({ ...chair, cutting_pieces_per_set: '2147483648', fabric_meters_per_piece: '0.0001' }, 1)).toMatchObject({ mode: 'valid', orderPieces: '2147483648', totalMeters: '214748.3648' })
    expect(cuttingCalculation({ ...chair, cutting_sets_per_product: '99999999999999' }, 2).mode).toBe('invalid')
    expect(cuttingCalculation({ ...chair, cutting_pieces_per_set: '99999999999999' }, 2).mode).toBe('invalid')
  })
  it.each(['', '0', '105.5', '-1', '1e3'])('订单数量 %s 不能被四舍五入成套数', value => {
    expect(cuttingCalculation(chair, value).mode).toBe('invalid')
  })
  it('兼容字段投影片/套和米/片，单位固定套，不含面料采购用量', () => {
    expect(cuttingCompatibilityValues(chair, 105)).toEqual({ cutting_pieces_per_set: 2, fabric_meters_per_piece: '0.125', cutting_sets_per_product: 1, fabric_meters_per_set: '0.25', cut_piece_quantity: '2', unit_consumption: '0.125', unit: '套' })
  })
})
