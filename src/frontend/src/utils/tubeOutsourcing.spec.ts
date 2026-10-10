import { describe, expect, it } from 'vitest'
import type { TubeSourceRow } from '@/types/tubeOutsourcing'
import { tubeMeters, tubeQuantityError, tubeRoots, wholeTubeQuantity } from './tubeOutsourcing'

const row: TubeSourceRow = {
  component_identity: 'front', bom_line_id: 'bom-front', part_name: '前腿管', material: 'Q195',
  specification: '圆管 Φ22', thickness: '0.8', cutting_length_mm: '650', raw_color: '原料本色', spray_color: '黑色',
  order_required: '2000', stock_quantity: '420', stock_unit: '根', max_quantity: '2040',
  pieces_per_bar: '6', raw_bar_length_m: '3.95', blockers: [],
}

describe('管材外发填写边界', () => {
  it.each(['-1', '0.5', '1.0', '1e3', 'NaN', 'Infinity', '+6', '六', '9007199254740992'])('不接受非法支数 %s', input => {
    expect(wholeTubeQuantity(input)).toBeNull()
    expect(tubeQuantityError(input, row, true)).toContain('整数支数')
  })
  it.each(['', ' ', '0', '00'])('空白及零跳过 %s', input => {
    expect(tubeQuantityError(input, row, true)).toBe('')
    expect(tubeRoots(input, null)).toBe(0)
    expect(tubeMeters(input, row)).toBe('0.00')
  })
  it('支数必须整除为根，不能进位', () => {
    expect(tubeRoots('601', '6')).toBeNull()
    expect(tubeQuantityError('601', row, true)).toContain('整除')
    expect(tubeQuantityError('601', row, false)).toBe('')
  })
  it('精确换算600支为100根395米', () => {
    expect(tubeRoots('600', '6')).toBe(100)
    expect(tubeMeters('600', row)).toBe('395.00')
    expect(tubeMeters('18', { pieces_per_bar: '6', raw_bar_length_m: '0.29' })).toBe('0.87')
  })
  it('使用服务端最大额度，不重新增加备料余量', () => {
    expect(tubeQuantityError('2040', row, true)).toBe('')
    expect(tubeQuantityError('2046', row, true)).toContain('不能超量')
    expect(tubeQuantityError('6', { ...row, max_quantity: '0' }, true)).toContain('不能超量')
  })
  it('没有换算依据或业务依据不能提交正数', () => {
    expect(tubeQuantityError('600', { ...row, pieces_per_bar: null }, true)).toContain('整除')
    expect(tubeQuantityError('600', { ...row, blockers: ['金工工序未完成'] }, false)).toContain('金工工序未完成')
    expect(tubeQuantityError('', { ...row, blockers: ['金工工序未完成'] }, false)).toBe('')
  })
})
