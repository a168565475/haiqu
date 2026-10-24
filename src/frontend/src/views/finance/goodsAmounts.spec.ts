import { describe, expect, it } from 'vitest'
import { moneyCents, moneyText, previewGoods, totalCents } from './goodsAmounts'

describe('货款整数分预览', () => {
  it('M05 现金、订金、折让分开', () => {
    expect(previewGoods('1000.00', '200.00', 50000n, 20000n, '20.00')).toEqual({ settled: 70000n, after: 28000n, availableAfter: 0n, error: '' })
  })
  it('M08 纯订金与零资金边界', () => {
    expect(previewGoods('300.00', '300.00', 0n, 30000n, '0.00').after).toBe(0n)
    expect(previewGoods('300.00', '300.00', 0n, 0n, '20.00').error).toContain('实际到账或订金')
  })
  it('部分核销只减本次金额，未用余额继续保留', () => {
    expect(previewGoods('1000.00', '200.00', 50000n, 8001n, '20.00')).toEqual({ settled: 58001n, after: 39999n, availableAfter: 11999n, error: '' })
    expect(previewGoods('200.00', '200.00', 0n, 1n, '0.00')).toEqual({ settled: 1n, after: 19999n, availableAfter: 19999n, error: '' })
  })
  it('M10/M11 不截断超额或留下无处使用的订金', () => {
    expect(previewGoods('50000.00', '30000.00', 0n, 3000001n, '0.00').error).toBe('本次订金核销金额超过可用余额，请调整核销金额。')
    expect(previewGoods('100.00', '0.00', 8000n, 0n, '30.00').error).toContain('10.00')
    expect(previewGoods('1000.00', '300.00', 80000n, 0n, '0.00').error).toContain('100.00')
    expect(previewGoods('1000.00', '300.00', 80000n, 30000n, '0.00').after).toBe(-10000n)
  })
  it('大金额与一分钱不经过浮点', () => {
    expect(moneyCents('99999999999999999999.99')).toBe(9999999999999999999999n)
    expect(moneyText(9999999999999999999999n)).toBe('99999999999999999999.99')
    expect(moneyText(-1n)).toBe('-0.01')
    expect(totalCents(['0.10', '0.20'])).toBe(30n)
  })
  it('前导零与公共收款输入一致且不放宽金额边界', () => {
    expect(moneyCents('01.00')).toBe(100n)
    expect(moneyCents('00.00')).toBe(0n)
    expect(moneyCents('0000000000000000000001.00')).toBe(100n)
    expect(moneyCents('099999999999999999999.99')).toBe(9999999999999999999999n)
    expect(moneyCents('0100000000000000000000.00')).toBeNull()
    expect(moneyCents('-01.00')).toBeNull()
    expect(moneyCents('01.001')).toBeNull()
    expect(totalCents(['01.00', '00.00'])).toBe(100n)
    expect(previewGoods('1000.00', '200.00', totalCents(['0500.00']), 20000n, '020.00').after).toBe(28000n)
  })
  it('错误输入和超范围不显示成零', () => {
    for (const text of ['', '-1', '1e2', 'NaN', '0.001', '100000000000000000000.00']) expect(moneyCents(text)).toBeNull()
    expect(totalCents(['99999999999999999999.99', '0.01'])).toBeNull()
    expect(moneyText(null)).toBe('—')
    expect(previewGoods('100', '0', null, 0n, '0').after).toBeNull()
  })
})
