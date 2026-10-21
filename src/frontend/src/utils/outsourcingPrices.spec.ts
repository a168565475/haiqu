import { describe, expect, it } from 'vitest'
import { formatOutsourcingMoney, outsourcingLineAmount, outsourcingPriceError, sumOutsourcingAmounts } from './outsourcingPrices'

describe('外发加工价格', () => {
  it('保留真实0、去尾零，并将未录入价格与0区分', () => {
    expect(formatOutsourcingMoney('0.00')).toBe('0')
    expect(formatOutsourcingMoney('12.5000')).toBe('12.5')
    expect(formatOutsourcingMoney(null)).toBe('未录入')
    expect(formatOutsourcingMoney(undefined, '—')).toBe('—')
    expect(formatOutsourcingMoney('10000000000000.01')).toBe('10,000,000,000,000.01')
  })
  it('单价允许非负两位小数，不接受空值、指数、负数和超精度', () => {
    for (const value of ['0', '2', '2.50']) expect(outsourcingPriceError(value)).toBe('')
    for (const value of ['', '-1', '1e2', '2.501', '100000000000000']) expect(outsourcingPriceError(value)).not.toBe('')
  })
  it('按外发支数精确计算金额，缺价不被当成0合计', () => {
    expect(outsourcingLineAmount('600', '0.15')).toBe('90.00')
    expect(outsourcingLineAmount('99999999999999', '0.01')).toBe('999999999999.99')
    expect(outsourcingLineAmount('12', '')).toBeNull()
    expect(sumOutsourcingAmounts(['0.10', '0.20'])).toBe('0.30')
    expect(sumOutsourcingAmounts(['1.00', null])).toBeNull()
  })
})
