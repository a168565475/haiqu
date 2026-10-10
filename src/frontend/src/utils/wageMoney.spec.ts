import { describe, expect, it } from 'vitest'

import { formatWageMoney, isPlainWageMoney, sumWageAmounts } from './wageMoney'

describe('工价金额格式化', () => {
  it('按十进制精确四舍五入到最多三位并去掉末尾零', () => {
    expect(formatWageMoney('0.6000')).toBe('¥0.6')
    expect(formatWageMoney('1.2345')).toBe('¥1.235')
    expect(formatWageMoney('99999999999999.9999')).toBe('¥100000000000000')
  })

  it('空值和非法值显示占位符', () => {
    expect(formatWageMoney(null)).toBe('—')
    expect(formatWageMoney('')).toBe('—')
    expect(formatWageMoney('1.2.3')).toBe('—')
  })

  it('合计使用十进制精确求和后再统一取三位', () => {
    expect(sumWageAmounts(['0.1000', '0.2000', '0.3000'])).toBe('0.6')
    expect(sumWageAmounts(['1.2344', '0.0001'])).toBe('1.235')
  })

  it('兼容后端可接受的省略整数或小数写法', () => {
    expect(formatWageMoney('.5')).toBe('¥0.5')
    expect(formatWageMoney('1.')).toBe('¥1')
    expect(sumWageAmounts(['.5', '1.'])).toBe('1.5')
  })

  it('界面金额只接受普通十进制，不接受科学计数法', () => {
    expect(isPlainWageMoney('1e1')).toBe(false)
    expect(isPlainWageMoney('1E-1')).toBe(false)
    expect(isPlainWageMoney('.5')).toBe(true)
    expect(isPlainWageMoney('1.')).toBe(true)
  })
})
