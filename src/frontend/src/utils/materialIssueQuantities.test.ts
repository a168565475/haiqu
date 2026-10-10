import { describe, expect, it } from 'vitest'
import { issuePipePlan, issueQuantityError } from './materialIssueQuantities'
import type { MaterialRequirement } from '@/types/materialIssue'

const pipe = { line_type: 'RAW', unit: '支', max_issue_quantity: '99999999999999',
  conversion_snapshot: { kind: 'PIPE', pieces_per_bar: 6, raw_bar_length_m: '3.05' } } as MaterialRequirement
describe('生产领料计量', () => {
  it('逐批次支转根米并保留两位精度', () => {
    expect(issuePipePlan('600', pipe)).toEqual({ error: '', bars: '100', meters: '305.00' })
    expect(issuePipePlan('12', pipe).meters).toBe('6.10')
  })
  it('非整根和小数支不能自动取整', () => {
    for (const value of ['7', '6.5', '0', '-6', 'Infinity', '1e3']) expect(issuePipePlan(value, pipe).error).not.toBe('')
  })
  it('原材料管材必须在提交前按整根倍数校验', () => {
    expect(issueQuantityError('5', pipe)).toBe('申请支数必须为 6 的正整数倍（每根可切 6 支）。')
    expect(issueQuantityError('6', pipe)).toBe('')
  })
  it('大数量不通过浮点数计算', () => {
    expect(issuePipePlan('99999999999996', pipe).meters).toBe('50833333333331.30')
  })
  it('裁片半成品仍按正整数套领取', () => {
    const fabric = { ...pipe, line_type: 'SEMI', unit: '套', conversion_snapshot: { kind: 'SEMI' } } as MaterialRequirement
    expect(issueQuantityError('5', fabric)).toBe('')
    expect(issueQuantityError('1.5', fabric)).not.toBe('')
  })
  it('管材半成品库存十二支可领取五支，不受旧整根快照限制', () => {
    const semiPipe = { ...pipe, line_type: 'SEMI', unit: '支', max_issue_quantity: '12', conversion_snapshot: { kind: 'SEMI_PIPE', pieces_per_bar: 6, raw_bar_length_m: '3.05' } } as MaterialRequirement
    expect(issueQuantityError('5', semiPipe)).toBe('')
    expect(issueQuantityError('6', semiPipe)).toBe('')
    expect(issueQuantityError('12', semiPipe)).toBe('')
    for (const value of ['0', '-1', '5.5', '13', 'Infinity', '1e1']) {
      expect(issueQuantityError(value, semiPipe)).not.toBe('')
    }
  })
  it('管材半成品领取不依赖当前 BOM 每根切割支数或原材料长度', () => {
    const semiPipe = { ...pipe, line_type: 'SEMI', unit: '支', max_issue_quantity: '12', conversion_snapshot: { kind: 'SEMI_PIPE' } } as MaterialRequirement
    expect(issueQuantityError('5', semiPipe)).toBe('')
    expect(issueQuantityError('5', { ...semiPipe, conversion_snapshot: undefined })).toBe('')
  })
  it('已知管材半成品身份即使历史单位不是支仍只允许正整数', () => {
    for (const kind of ['SEMI_PIPE', 'SEMI_PIPE_PIECES']) {
      const semiPipe = { ...pipe, line_type: 'SEMI', unit: 'PCS', max_issue_quantity: '12', conversion_snapshot: { kind } } as MaterialRequirement
      expect(issueQuantityError('5', semiPipe)).toBe('')
      expect(issueQuantityError('5.5', semiPipe)).not.toBe('')
    }
  })
  it('普通材料保留四位小数，限制当前可领量', () => {
    const raw = { ...pipe, unit: '米', max_issue_quantity: '1.1000', conversion_snapshot: { kind: 'FABRIC' } } as MaterialRequirement
    expect(issueQuantityError('1.0001', raw)).toBe('')
    expect(issueQuantityError('1.1001', raw)).not.toBe('')
    expect(issueQuantityError('1.00001', raw)).not.toBe('')
  })
})
