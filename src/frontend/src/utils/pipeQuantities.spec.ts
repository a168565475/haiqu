import { describe, expect, it } from 'vitest'
import { pipeMeters, pipeRootsFromMeters, pipeRootsFromWeight, samplePipeSuggestedWeight } from './pipeQuantities'

describe('三位长料米数', () => {
  it('按原长精确换算，保留旧两位文本', () => {
    expect(pipeMeters('3', '6.305')).toBe('18.915')
    expect(pipeMeters('3', '3.050')).toBe('9.15')
    expect(pipeMeters('3', '6.3051')).toBe('')
    expect(samplePipeSuggestedWeight('12.61', '6.305', '2.5')).toBe('5')
  })
})

describe('采购重量估算根数', () => {
  it.each([['4.1', '2.5', '2'], ['5', '2.5', '2'], ['5.0001', '2.5', '3'], ['0', '2.5', '0'], ['0.0001', '0.0001', '1']])('%s kg / %s kg每根 = %s 根', (weight, unit, roots) => {
    expect(pipeRootsFromWeight(weight, unit)).toBe(roots)
  })
  it.each(['', '0', '-1', 'NaN', '2.12345'])('标准重量%s不可用于自动估算', unit => {
    expect(pipeRootsFromWeight('4.1', unit)).toBe('')
  })
})

describe('米制采购收退精确换算', () => {
  it.each([['18.915', '6.305', '3'], ['6.7000', '3.35', '2'], ['0', '3.35', '0'], ['1', '0.001', '1000']])('%s米按原长%s精确换算%s根', (meters, length, roots) => {
    expect(pipeRootsFromMeters(meters, length)).toBe(roots)
  })
  it.each([['1', '3.35'], ['6.7001', '3.35'], ['-1', '3.35'], ['6.7', '0'], ['6.7', null], ['6.7', '3.3501'], ['6.70001', '3.35']])('非整数倍或无效参数不能取近似根数：%s/%s', (meters, length) => {
    expect(pipeRootsFromMeters(meters!, length)).toBe('')
  })
})

describe('打样米需求预算采购重量', () => {
  it.each([['12', '3.05', '2.5', '10'], ['12.0001', '6', '1.2345', '3.7035'], ['12', '6', '2.5', '5']])('缺料%s米、原长%s、单重%s预算%s kg', (meters, length, weight, expected) => {
    expect(samplePipeSuggestedWeight(meters, length, weight)).toBe(expected)
  })
  it.each([[null, '6', '2.5'], ['12', null, '2.5'], ['12', '6', null], ['12', '0', '2.5'], ['12', '6.0001', '2.5']])('参数缺失或不合法不生成零重量', (meters, length, weight) => {
    expect(samplePipeSuggestedWeight(meters, length, weight)).toBe('')
  })
})
