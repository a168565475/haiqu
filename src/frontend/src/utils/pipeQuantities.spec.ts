import { describe, expect, it } from 'vitest'
import { pipeMeters, pipeRootError } from './pipeQuantities'

describe('管材采购与到货预览', () => {
  it('按整数根数精确计算米数，不使用浮点乘法', () => {
    expect(pipeMeters(337, '3.05')).toBe('1027.85')
    expect(pipeMeters(3, '0.10')).toBe('0.30')
    expect(pipeMeters(0, '3.05')).toBe('0.00')
  })
  it('拒绝半根、负数、非法长度与超过两位精度的长度', () => {
    for (const roots of ['1.5', '-1', 'NaN', '']) expect(pipeMeters(roots, '3.05')).toBe('')
    for (const length of ['-1', '3.051', '', 'Infinity']) expect(pipeMeters(2, length)).toBe('')
  })
  it('实际根数只要求正整数，允许与建议根数不同', () => {
    expect(pipeRootError('338')).toBe('')
    expect(pipeRootError('337')).toBe('')
    for (const roots of ['0', '1.5', '-1', '', '100000000000000']) {
      expect(pipeRootError(roots)).not.toBe('')
    }
  })
})
