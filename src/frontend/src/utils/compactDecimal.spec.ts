import { describe, expect, it } from 'vitest'
import { compactDecimal } from './compactDecimal'

describe('数字显示去除小数尾零', () => {
  it.each([
    ['5.0000', '5'], ['5.5000', '5.5'], ['5.0500', '5.05'],
    ['0.0000', '0'], ['-12.3400', '-12.34'], ['5000', '5000'],
    ['0.0001', '0.0001'], ['5,000.5000', '5,000.5'],
    ['9007199254740993.0500', '9007199254740993.05'],
    ['Φ16 × 2.0 mm', 'Φ16 × 2.0 mm'], ['2026.10.20', '2026.10.20'],
  ])('%s 显示为 %s', (value, expected) => expect(compactDecimal(value)).toBe(expected))
  it('保留缺失值和占位符语义', () => {
    expect(compactDecimal(null)).toBe('—')
    expect(compactDecimal(undefined)).toBe('—')
    expect(compactDecimal('', '')).toBe('')
    expect(compactDecimal('—')).toBe('—')
  })
})
