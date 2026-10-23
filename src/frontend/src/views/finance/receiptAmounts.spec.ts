import { describe, expect, it } from 'vitest'
import { receiptCents, receiptMoney, receiptSum } from './receiptAmounts'

describe('收款金额与服务端有效位数一致', () => {
  it('多个前导零不占用20位有效整数精度', () => {
    expect(receiptCents('00000000000000000000001.00')).toBe(100n)
    expect(receiptCents('00000000000000000000000.00')).toBe(0n)
    expect(receiptCents('00099999999999999999999.99')).toBe(9999999999999999999999n)
    expect(receiptSum(['00000000000000000000001.00', '0.01'])).toBe('1.01')
  })
  it('拒绝越界、负值、指数和超过两位小数，不用浮点舍入', () => {
    for (const value of ['100000000000000000000', '000100000000000000000000', '-1', '1e2', 'NaN', '1.001', '']) expect(receiptCents(value)).toBeNull()
    expect(receiptMoney(receiptCents('99999999999999999999.99')!)).toBe('99999999999999999999.99')
  })
})
