import { describe, expect, it } from 'vitest'

import type { CustomerActivitySummary } from '@/types/customer'

import {
  formatCustomerGradeCell,
  formatCustomerListDate,
  getFollowUpStatus,
  getRiskStatus,
} from './customerListPresentation'

describe('客户列表展示规则', () => {
  it('格式化客户等级并为缺失数据保留占位符', () => {
    expect(formatCustomerGradeCell('A')).toBe('A级')
    expect(formatCustomerGradeCell('VIP')).toBe('VIP')
    expect(formatCustomerGradeCell()).toBe('—')
  })

  it('格式化日期并安全处理空值与异常值', () => {
    expect(formatCustomerListDate('2026-09-09T08:00:00+08:00')).toBe('2026-09-09')
    expect(formatCustomerListDate(null)).toBe('—')
    expect(formatCustomerListDate('not-a-date')).toBe('—')
  })

  it('只根据真实下次跟进日期派生跟进状态', () => {
    const now = new Date('2026-09-09T12:00:00+08:00')

    expect(getFollowUpStatus(null, now)).toEqual({ label: '未安排', tone: 'neutral' })
    expect(getFollowUpStatus('not-a-date', now)).toEqual({
      label: '未安排',
      tone: 'neutral',
      title: '跟进时间格式异常',
    })
    expect(getFollowUpStatus('2026-09-08T12:00:00+08:00', now)).toEqual({ label: '已逾期', tone: 'danger' })
    expect(getFollowUpStatus('2026-09-09T18:00:00+08:00', now)).toEqual({ label: '今日跟进', tone: 'warning' })
    expect(getFollowUpStatus('2026-09-10T09:00:00+08:00', now)).toEqual({ label: '待跟进', tone: 'warning' })
  })

  it('仅对后端明确标记为高风险的客户展示风险标签', () => {
    const highRiskActivity = {
      id: 'activity-1',
      activity_status: 'HIGH_RISK',
      display_name: '高风险',
      source_type: 'SYSTEM',
      reason: '存在逾期任务',
      formula_version: 'v1',
      effective_from: '2026-09-08T00:00:00Z',
      effective_to: null,
    } as CustomerActivitySummary
    const activeActivity = { ...highRiskActivity, activity_status: 'ACTIVE' } as CustomerActivitySummary

    expect(getRiskStatus(highRiskActivity)).toEqual({
      label: '高风险',
      tone: 'danger',
      title: '存在逾期任务',
    })
    expect(getRiskStatus(activeActivity)).toBeNull()
    expect(getRiskStatus(null)).toBeNull()
  })
})
