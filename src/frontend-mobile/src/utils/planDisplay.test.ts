import { describe, expect, it } from 'vitest'
import { displayQuantity, progressLabel } from './planDisplay'
import type { MobilePlan } from '@/types/mobilePlan'

describe('计划信息口径', () => {
  it('保留大数量及小数，不经过浮点丢失精度', () => {
    expect(displayQuantity('1234567891234567.1200')).toBe('1234567891234567.12')
    expect(displayQuantity('0.0000')).toBe('0')
    expect(displayQuantity(null)).toBe('—')
  })
  it('没有权限的进度不会显示为零', () => {
    expect(progressLabel({ progress: null } as MobilePlan)).toBe('进度不可查看')
    expect(progressLabel({ progress: { status: 'NOT_CONFIGURED', percentage: null } } as MobilePlan)).toBe('待配置工序')
    expect(progressLabel({ progress: { status: 'READY', percentage: 0 } } as MobilePlan)).toBe('0%')
  })
})
