import { describe, expect, it } from 'vitest'
import { multiplyAmount4, sumAmounts4 } from './salesCny'

describe('销售人民币金额四位规则', () => {
  it('先舍入人民币单价，再计算行金额并逐行求和', () => {
    const price = multiplyAmount4('0.33335', '1')
    expect(price).toBe('0.3334')
    expect(multiplyAmount4(price, '3')).toBe('1.0002')
    expect(sumAmounts4([multiplyAmount4(price, '3'), '0.0001'])).toBe('1.0003')
  })
  it('八位汇率和HALF_UP边界不受二进制浮点影响', () => {
    expect(multiplyAmount4('1.005', '0.01')).toBe('0.0101')
    expect(multiplyAmount4('100.1234', '7.12345678')).toBe('713.2247')
    expect(multiplyAmount4('0', '7')).toBe('0.0000')
  })
  it('缺失和无效金额不能显示为零', () => {
    expect(multiplyAmount4(null, '1')).toBeNull()
    expect(multiplyAmount4('NaN', '1')).toBeNull()
    expect(sumAmounts4(['1.0000', null])).toBeNull()
  })
})
