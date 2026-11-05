import { describe, expect, it } from 'vitest'
import {
  formatOutsourcingMoney,
  outsourcingLineAmount,
  outsourcingLineArea,
  outsourcingPriceError,
  sumOutsourcingAmounts,
  sumOutsourcingAreas,
} from './outsourcingPrices'

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
    expect(outsourcingLineAmount('600', '0.15', 'PIECE', '0.1250')).toBe('90.00')
    expect(outsourcingLineAmount('99999999999999', '0.01')).toBe('999999999999.99')
    expect(outsourcingLineAmount('12', '')).toBeNull()
    expect(sumOutsourcingAmounts(['0.10', '0.20'])).toBe('0.30')
    expect(sumOutsourcingAmounts(['1.00', null])).toBeNull()
  })
  it('按单支面积精确计算行面积和平方米金额', () => {
    expect(outsourcingLineArea('20', '0.1250')).toBe('2.5000')
    expect(outsourcingLineAmount('20', '2.50', 'SQUARE_METER', '0.1250')).toBe('6.25')
    expect(sumOutsourcingAreas(['2.5000', '1.2500'])).toBe('3.7500')
  })
  it('缺少或无效面积时不猜测平方米金额和面积合计', () => {
    expect(outsourcingLineArea('20', null)).toBeNull()
    expect(outsourcingLineArea('20', '0')).toBeNull()
    expect(outsourcingLineAmount('20', '2.50', 'SQUARE_METER')).toBeNull()
    expect(sumOutsourcingAreas(['2.5000', null])).toBeNull()
  })
  it('使用BigInt处理大整数，不丢失面积精度', () => {
    expect(outsourcingLineArea('99999999999999', '99999999999999.9999'))
      .toBe('9999999999999899990000000000.0001')
  })
  it('平方米金额使用与后端一致的ROUND_HALF_EVEN', () => {
    expect(outsourcingLineAmount('10', '1.00', 'SQUARE_METER', '0.0005')).toBe('0.00')
    expect(outsourcingLineAmount('10', '1.00', 'SQUARE_METER', '0.0015')).toBe('0.02')
    expect(outsourcingLineAmount('10', '1.00', 'SQUARE_METER', '0.0004')).toBe('0.00')
    expect(outsourcingLineAmount('10', '1.00', 'SQUARE_METER', '0.0006')).toBe('0.01')
  })
})
