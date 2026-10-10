import { describe, expect, it } from 'vitest'
import type { InquiryRow } from '@/types/inquiry'
import { allRowsAllow, formatEstimatedAmount, formatReceived, readColumns, readListQuery, slaPresentation, priorityTone } from './inquiryListState'

describe('询盘列表状态边界', () => {
  it('保存列顺序并去重，金额筛选必须同时包含币种和合法非负小数', () => {
    expect(readColumns('["owner","country","owner","unknown"]')).toEqual(['owner', 'country'])
    expect(readListQuery({ amount_min: '10000.25', amount_currency: 'USD', sla_state: 'RISK' }).filters).toMatchObject({ amount_min: '10000.25', amount_currency: 'USD', sla_state: 'RISK' })
    for (const amount of ['-1', 'NaN', '1e5', '0.123456789']) expect(readListQuery({ amount_min: amount, amount_currency: 'USD' }).filters.amount_min).toBe('')
    expect(readListQuery({ amount_min: '10' }).filters.amount_min).toBe('')
  })
  it('优先级和转报价筛选恢复真实枚举，拒绝未知值', () => {
    expect(readListQuery({ priority: 'HIGH', has_quotation: 'true' }).filters).toMatchObject({ priority: 'HIGH', has_quotation: 'true' })
    expect(readListQuery({ priority: 'UNSET', has_quotation: 'false' }).filters).toMatchObject({ priority: 'UNSET', has_quotation: 'false' })
    expect(readListQuery({ priority: 'URGENT', has_quotation: 'yes' }).filters).toMatchObject({ priority: '', has_quotation: '' })
    expect(priorityTone('HIGH')).toBe('danger')
    expect(priorityTone('MEDIUM')).toBe('warning')
    expect(priorityTone('LOW')).toBe('neutral')
    expect(priorityTone()).toBe('neutral')
  })
  it('产品合计保留零值、大额和小数精度，按币种分别显示', () => {
    const row = { product_amount: { item_count: 2, missing_price_count: 0, totals: [{ currency_code: 'USD', amount: '1234567890123456.78000000' }, { currency_code: 'CNY', amount: '0.00000000' }] } }
    expect(formatEstimatedAmount(row)).toBe('USD 1,234,567,890,123,456.78 / CNY 0.00')
    row.product_amount.totals = [{ currency_code: 'USD', amount: '0.00000001' }]
    expect(formatEstimatedAmount(row)).toBe('USD 0.00000001')
    row.product_amount.missing_price_count = 1
    expect(formatEstimatedAmount(row)).toBe('待补齐')
    row.product_amount.item_count = 0
    expect(formatEstimatedAmount(row)).toBe('—')
    expect(formatEstimatedAmount({})).toBe('—')
  })
  it('拒绝异常金额和币种，不展示错误总额', () => {
    expect(formatEstimatedAmount({ product_amount: { item_count: 1, missing_price_count: 0, totals: [{ currency_code: 'USD', amount: 'NaN' }] } })).toBe('—')
    expect(formatEstimatedAmount({ product_amount: { item_count: 1, missing_price_count: 0, totals: [{ currency_code: '<script>', amount: '10' }] } })).toBe('—')
  })
  it('损坏的地址参数不能产生非法分页、任意排序或数组字符串', () => {
    const state = readListQuery({ page: '-2', page_size: '999', ordering: 'estimated_amount', q: ['one', 'two'], sla_state: 'NORMAL', received_from: 'invalid' })
    expect(state.page).toBe(1)
    expect(state.pageSize).toBe(50)
    expect(state.ordering).toBe('-received_at')
    expect(state.filters.q).toBe('')
    expect(state.filters.sla_state).toBe('')
    expect(state.filters.received_from).toBe('')
  })
  it('合法筛选、分页和看板地址可以恢复', () => {
    const state = readListQuery({ page: '3', page_size: '20', ordering: 'received_at', owner_employee_id: 'owner-1', assignment_status: 'UNASSIGNED', view: 'board' })
    expect(state).toMatchObject({ page: 3, pageSize: 20, ordering: 'received_at', view: 'board', filters: { owner_employee_id: 'owner-1', assignment_status: 'UNASSIGNED' } })
  })
  it('列偏好损坏时使用默认值，合法空列表和未知列分别处理', () => {
    expect(readColumns('{bad')).toHaveLength(10)
    expect(readColumns('{}')).toHaveLength(10)
    expect(readColumns('["source","unknown"]')).toEqual(['source'])
    expect(readColumns('[]')).toEqual([])
  })
  it('空选择、无版本或混选不可操作记录时禁止整批提交', () => {
    const allowed = { id: '1', etag: 'v1', allowed_actions: { assign: true, mark_invalid: true } } as InquiryRow
    const closed = { ...allowed, id: '2', allowed_actions: { ...allowed.allowed_actions, assign: false, mark_invalid: false } }
    expect(allRowsAllow([], 'assign')).toBe(false)
    expect(allRowsAllow([allowed], 'assign')).toBe(true)
    expect(allRowsAllow([allowed, closed], 'mark_invalid')).toBe(false)
    expect(allRowsAllow([{ ...allowed, etag: '' }], 'assign')).toBe(false)
  })
  it('时间统一显示北京时间，并容忍空值和非法日期', () => {
    expect(formatReceived('2026-09-10T16:05:00Z')).toEqual({ date: '2026-09-11', time: '00:05' })
    expect(formatReceived('bad')).toEqual({ date: '—', time: '' })
    expect(formatReceived('')).toEqual({ date: '—', time: '' })
  })
  it('未设置时效不伪装成正常，缺少剩余时间不伪造倒计时', () => {
    expect(slaPresentation({ state: 'NONE', remaining_seconds: null, next_deadline_at: null })).toMatchObject({ label: '—', reminder: '—' })
    expect(slaPresentation({ state: 'DUE_SOON', remaining_seconds: null, next_deadline_at: null }).label).toBe('即将超时')
    expect(slaPresentation({ state: 'BREACHED', remaining_seconds: -3660, next_deadline_at: null }).label).toBe('超时 1小时1分')
  })
})

