import { describe, expect, it, vi } from 'vitest'
import type { ReportBusinessPayload, ReportEntry, ReportingScheme } from '@/types/reporting'
import { estimatedLineAmount, needsCompletionConfirmation, prepareReportAttempt, remainingQuantity, reportingRecordScope, reportingScope, shanghaiToday, uncertainSubmission, validateReportEntries, validProductionDate } from './reporting'

const scheme: ReportingScheme = {
  id: 'scheme', scheme_number: 'WAGE-1', status: 'APPROVED', version: 1, revision: 3,
  product_line_id: 'product', workshop: { id: 'workshop', name: '金工车间' }, scope_craft: { id: 'craft', name: '加工' },
  lines: [
    { id: 'line-a', work_item_id: 'work-a', display_name: '椅脚', operation_name: '切割', craft_name: '加工', production_description: '', unit_name: '次', required_quantity: '100.0000', cumulative_quantity: '60.0000', declared_price: '2.3450', status: 'ACTIVE' },
    { id: 'line-b', work_item_id: 'work-b', display_name: '椅脚', operation_name: '打孔', craft_name: '加工', production_description: '', unit_name: '次', required_quantity: '100.0000', cumulative_quantity: '80.0000', declared_price: '0.0050', status: 'ACTIVE' },
  ],
}
const row = (key: number, quantity: string, overrides: Partial<ReportEntry> = {}): ReportEntry => ({
  key, scheme_line_id: 'line-a', workshop_employee_id: 'worker-a', production_line: null, quantity, ...overrides,
})
const employees = new Set(['worker-a', 'worker-b'])
const validScope = { schedule_product_id: '11111111-1111-4111-8111-111111111111', workshop_id: '22222222-2222-4222-8222-222222222222', craft_id: '33333333-3333-4333-8333-333333333333', plan_category: 'METAL' }

describe('报工范围与日期', () => {
  it('拒绝缺失、多值或不合法的范围，避免落入未过滤列表', () => {
    expect(reportingScope(validScope)).toEqual(validScope)
    expect(reportingScope({ ...validScope, craft_id: undefined })).toBeNull()
    expect(reportingScope({ ...validScope, craft_id: [validScope.craft_id] })).toBeNull()
    expect(reportingScope({ ...validScope, plan_category: 'OTHER' })).toBeNull()
  })
  it('上海午夜后的默认日期不依赖运行机器时区', () => {
    expect(shanghaiToday(new Date('2026-10-30T16:01:00Z'))).toBe('2026-10-31')
    expect(validProductionDate('2026-02-29')).toBe(false)
    expect(validProductionDate('2028-02-29')).toBe(true)
  })
  it('历史记录允许省略工艺，但不将无效或多值工艺悄悄扩大为全部', () => {
    const { craft_id: _craft, ...planScope } = validScope
    expect(reportingRecordScope(planScope)).toEqual(planScope)
    expect(reportingScope(planScope)).toBeNull()
    expect(reportingRecordScope({ ...planScope, craft_id: '' })).toBeNull()
    expect(reportingRecordScope({ ...planScope, craft_id: [validScope.craft_id] })).toBeNull()
  })
})

describe('班组多人报工校验', () => {
  it('同一工序分给两名员工合法，合计不超过剩余次数', () => {
    const result = validateReportEntries(scheme, [row(1, '15'), row(2, '25', { workshop_employee_id: 'worker-b' })], employees, false)
    expect(result.rows).toEqual({})
    expect(result.error).toBe('')
    expect(result.completesPlan).toBe(false)
  })
  it('按工序合计校验，不能让每条都合法但合计超额', () => {
    const result = validateReportEntries(scheme, [row(1, '21'), row(2, '20', { workshop_employee_id: 'worker-b' })], employees, false)
    expect(result.rows[1]?.quantity).toContain('最多可报 40')
    expect(result.rows[2]?.quantity).toContain('最多可报 40')
  })
  it.each(['0', '-1', '1.5', '1e2', 'NaN', '100000000000000', ''])('拒绝不合法的完成次数 %s', (value) => {
    expect(validateReportEntries(scheme, [row(1, value)], employees, false).rows[1]?.quantity).toBeTruthy()
  })
  it('无效员工、无效工序均定位到对应行', () => {
    const result = validateReportEntries(scheme, [row(1, '1', { workshop_employee_id: 'outside', scheme_line_id: 'missing' })], employees, false)
    expect(result.rows[1]?.workshop_employee_id).toContain('本车间')
    expect(result.rows[1]?.scheme_line_id).toContain('有效工序')
  })
  it('装配必须填1至3线，非装配不能保留生产线', () => {
    expect(validateReportEntries(scheme, [row(1, '1')], employees, true).rows[1]?.production_line).toBeTruthy()
    expect(validateReportEntries(scheme, [row(1, '1', { production_line: 2 })], employees, true).rows).toEqual({})
    expect(validateReportEntries(scheme, [row(1, '1', { production_line: 2 })], employees, false).rows[1]?.production_line).toBeTruthy()
  })
  it('所有有效工序完成才触发计划完成，作废工序不参与', () => {
    const result = validateReportEntries(scheme, [row(1, '40'), row(2, '20', { scheme_line_id: 'line-b' })], employees, false)
    expect(result.completesPlan).toBe(true)
    const withVoid = { ...scheme, lines: [...scheme.lines, { ...scheme.lines[0], id: 'void', status: 'VOID' as const, required_quantity: null }] }
    expect(validateReportEntries(withVoid, [row(1, '40'), row(2, '20', { scheme_line_id: 'line-b' })], employees, false).completesPlan).toBe(true)
  })
  it('缺需完成次数不能当成零或已完成', () => {
    const invalid = { ...scheme, lines: [{ ...scheme.lines[0], required_quantity: null }] }
    expect(validateReportEntries(invalid, [row(1, '1')], employees, false).error).toContain('信息不完整')
    expect(remainingQuantity(invalid.lines[0])).toBe('—')
  })
  it('按工作项身份合并多条工价行，防止相同工序身份分开绕过上限', () => {
    const sameWorkItem = { ...scheme, lines: [scheme.lines[0], { ...scheme.lines[0], id: 'line-a-copy' }] }
    const result = validateReportEntries(sameWorkItem, [row(1, '30'), row(2, '20', { scheme_line_id: 'line-a-copy' })], employees, false)
    expect(result.rows[1]?.quantity).toContain('合计超过')
    expect(result.rows[2]?.quantity).toContain('合计超过')
  })
})

describe('金额与重试边界', () => {
  it('四位工价按每行四舍五入到分，避免浮点舍入偏差', () => {
    expect(estimatedLineAmount(scheme.lines[0], '1')).toBe('2.35')
    expect(estimatedLineAmount(scheme.lines[1], '1')).toBe('0.01')
    expect(estimatedLineAmount(scheme.lines[1], '2')).toBe('0.01')
  })
  it('相同内容重试沿用编号，明确修改内容才分配新编号', () => {
    const business: ReportBusinessPayload = { production_date: '2026-10-31', schedule_product_id: validScope.schedule_product_id, scheme_id: 'scheme', scheme_revision: 3, confirm_plan_completion: false, lines: [{ scheme_line_id: 'line-a', workshop_employee_id: 'worker-a', production_line: null, quantity: '1' }] }
    const newId = vi.fn().mockReturnValueOnce('request-a').mockReturnValueOnce('request-b')
    const initial = prepareReportAttempt(business, null, newId)
    expect(prepareReportAttempt(structuredClone(business), initial, newId).payload.client_request_id).toBe('request-a')
    expect(newId).toHaveBeenCalledTimes(1)
    expect(prepareReportAttempt({ ...business, scheme_revision: 4 }, initial, newId).payload.client_request_id).toBe('request-b')
  })
  it('网络和5xx属于结果待确认，业务4xx保留填写并允许修正', () => {
    expect(uncertainSubmission(new Error('network'))).toBe(true)
    expect(uncertainSubmission({ response: { status: 502 } })).toBe(true)
    expect(uncertainSubmission({ response: { status: 400 } })).toBe(false)
    expect(needsCompletionConfirmation({ response: { data: { error: { field_errors: { confirm_plan_completion: ['请确认'] } } } } })).toBe(true)
  })
})
