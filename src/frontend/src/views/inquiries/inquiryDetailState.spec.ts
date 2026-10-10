import { describe, expect, it } from 'vitest'
import { formatInquiryNumber, formatInquiryTime, inquiryStepIndex, nextInquiryAction, safeWebsite, slaPresentation } from './inquiryDetailState'
import type { InquirySla } from '@/types/inquiry'

describe('询盘详情真实状态', () => {
  it('草稿及终止状态不冒充首响或已转订单', () => {
    expect(inquiryStepIndex('DRAFT')).toBe(-1)
    expect(inquiryStepIndex('CANCELLED')).toBe(-1)
    expect(inquiryStepIndex('LOST')).toBe(-1)
    expect(inquiryStepIndex('FOLLOW_UP')).toBe(4)
    expect(inquiryStepIndex('CONVERTED')).toBe(5)
  })
  it('按负责人区分新询盘和已分配，报价接受保留真实状态对应的报价阶段', () => {
    expect(inquiryStepIndex('NEW', false)).toBe(0)
    expect(inquiryStepIndex('NEW', true)).toBe(1)
    expect(inquiryStepIndex('ANALYZING', true)).toBe(2)
    expect(inquiryStepIndex('READY_FOR_QUOTE', true)).toBe(3)
    expect(inquiryStepIndex('QUOTE_ACCEPTED', true)).toBe(4)
    expect(inquiryStepIndex('UNKNOWN', true)).toBe(-1)
  })
  it('已结束询盘不会被缺少联系人改成待处理', () => {
    expect(nextInquiryAction({ status: 'CONVERTED', status_display: '已转订单', customer_contact: null })).toContain('销售订单')
    expect(nextInquiryAction({ status: 'NEW', status_display: '新询盘', customer_contact: null })).toBe('先补充联系人')
  })
  it('外部网址只允许无凭据的 HTTP 地址', () => {
    for (const value of ['javascript:alert(1)', 'data:text/html,test', 'https://user:pass@example.com', null, 'not-a-url']) expect(safeWebsite(value)).toBe('')
    expect(safeWebsite('https://example.com')).toBe('https://example.com/')
  })
  it('时间固定为北京时间并容忍缺失和无效值', () => {
    expect(formatInquiryTime(null)).toBe('—')
    expect(formatInquiryTime('broken')).toBe('—')
    expect(formatInquiryTime('2026-09-10T01:00:00Z')).toContain('09:00')
  })
  it('数量和价格去除无意义尾零，不损失大数与有效小数', () => {
    expect(formatInquiryNumber('1200.0000')).toBe('1,200')
    expect(formatInquiryNumber('18.5000', 2)).toBe('18.50')
    expect(formatInquiryNumber('0.1234', 2)).toBe('0.1234')
    expect(formatInquiryNumber('9999999999999999.01', 2)).toBe('9,999,999,999,999,999.01')
    expect(formatInquiryNumber(null)).toBe('—')
  })
  const record = { status: 'RUNNING', started_at: '2026-09-10T00:00:00Z', next_deadline_at: '2026-09-10T04:00:00Z' } as InquirySla
  it('时效进度按当前截止时间计算并限制在 0 到 100', () => {
    const now = Date.parse('2026-09-10T02:00:00Z')
    expect(slaPresentation(record, now, 'ANALYZING').percentage).toBe(50)
    expect(slaPresentation(record, now + 4 * 3600000, 'ANALYZING').percentage).toBe(100)
    expect(slaPresentation(record, now + 4 * 3600000, 'ANALYZING').overdue).toBe(true)
    expect(slaPresentation({ ...record, status: 'BREACHED' }, now, 'ANALYZING').label).toBe('已超时')
  })
  it('不存在、暂停、完成和终止时不显示虚构倒计时', () => {
    for (const status of ['PAUSED', 'COMPLETED', 'CANCELLED']) expect(slaPresentation({ ...record, status }, Date.now(), 'ANALYZING').percentage).toBeNull()
    expect(slaPresentation(undefined, Date.now(), 'NEW').label).toBe('暂无时效记录')
    expect(slaPresentation(record, Date.now(), 'CONVERTED').label).toBe('当前流程已结束')
  })
})
