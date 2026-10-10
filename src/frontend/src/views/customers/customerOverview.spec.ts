import { describe, expect, it } from 'vitest'

import type { CustomerDetail, CustomerSummary, CustomerTimelineEvent } from '@/types/customer'

import {
  buildCustomerHealthSummary,
  calculateCreditUsage,
  formatOverviewDateTime,
  formatOverviewMoney,
  timelineCategory,
} from './customerOverview'

function makeCustomer(snapshot: CustomerDetail['business_snapshot'] = null): CustomerDetail {
  return {
    id: 'customer-1',
    account_code: 'CUS-00001',
    account_name: 'Aurora Outdoor GmbH',
    last_contact_at: null,
    business_snapshot: snapshot,
  } as CustomerDetail
}

function makeSummary(openComplaints = 0, overdueTasks = 0): CustomerSummary {
  return {
    counts: {
      entities: 0,
      contacts: 0,
      open_inquiries: 0,
      open_quotations: 0,
      active_samples: 0,
      open_complaints: openComplaints,
      open_tasks: 0,
      overdue_tasks: overdueTasks,
    },
  } as CustomerSummary
}

describe('客户 360 概览展示规则', () => {
  it('金额保留真实零值，并安全处理空值和异常值', () => {
    expect(formatOverviewMoney(0, 'USD')).toBe('USD 0')
    expect(formatOverviewMoney('128400', 'USD')).toBe('USD 128,400')
    expect(formatOverviewMoney(null, 'USD')).toBe('—')
    expect(formatOverviewMoney('not-a-number', 'USD')).toBe('—')
  })

  it('日期时间安全处理空值和异常值', () => {
    expect(formatOverviewDateTime(null)).toBe('—')
    expect(formatOverviewDateTime('not-a-date')).toBe('—')
    expect(formatOverviewDateTime('2026-09-09T08:30:00+08:00')).toMatch(/^2026-09-09\s08:30$/)
  })

  it('信用额度只在额度与已用金额都是真实有效值时计算', () => {
    const valid = makeCustomer({ credit_limit: '100000', credit_used: '38000' } as CustomerDetail['business_snapshot'])
    const missingUsed = makeCustomer({ credit_limit: '100000', credit_used: null } as CustomerDetail['business_snapshot'])
    const zeroLimit = makeCustomer({ credit_limit: '0', credit_used: '0' } as CustomerDetail['business_snapshot'])

    expect(calculateCreditUsage(valid)).toBe(38)
    expect(calculateCreditUsage(missingUsed)).toBeNull()
    expect(calculateCreditUsage(zeroLimit)).toBeNull()
  })

  it('时间线类型只根据真实事件来源分类', () => {
    expect(timelineCategory({ source_type: 'QUOTATION', event_type: 'CREATED' } as CustomerTimelineEvent)).toEqual({ label: '报价', tone: 'success' })
    expect(timelineCategory({ source_type: 'UNKNOWN', event_type: 'UNKNOWN' } as CustomerTimelineEvent)).toEqual({ label: '系统', tone: 'neutral' })
  })

  it('健康状态不把缺失财务字段误判为整体正常', () => {
    const incomplete = buildCustomerHealthSummary(makeCustomer(), makeSummary())
    const atRisk = buildCustomerHealthSummary(makeCustomer(), makeSummary(1, 2))

    expect(incomplete.label).toBe('数据待完善')
    expect(incomplete.facts[0]?.label).toBe('信用额度数据未接入')
    expect(incomplete.facts[1]?.label).toBe('应收逾期数据未接入')
    expect(atRisk.label).toBe('需关注')
    expect(atRisk.facts[3]?.meta).toBe('开放客诉 1 · 逾期任务 2')
  })
})
