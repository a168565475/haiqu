import { describe, expect, it } from 'vitest'
import { issuePipePlan, issueQuantityError, issueSelectedQuantityError } from './materialIssueQuantities'
import type { MaterialRequirement } from '@/types/materialIssue'

const pipe = { line_type: 'RAW', unit: '支', max_issue_quantity: '99999999999999',
  conversion_snapshot: { kind: 'PIPE', pieces_per_bar: 6, raw_bar_length_m: '3.05' } } as MaterialRequirement
describe('生产领料计量', () => {
  it('超过BOM剩余但未超过可用库存时允许普通材料和半成品领用', () => {
    for (const line_type of ['RAW', 'SEMI'] as const) {
      const row = { requirement_id: 'one', stock_item_id: 'stock', line_type, unit: '支',
        stock_mode: 'PUBLIC_V2', max_issue_quantity: '30', order_remaining: '0',
        component_order_remaining: '0', conversion_snapshot: { kind: 'PUBLIC_SEMI', component_identity: 'part' } } as MaterialRequirement
      expect(issueSelectedQuantityError('25', row, [row], { one: '25' })).toBe('')
      expect(issueSelectedQuantityError('31', row, [row], { one: '31' })).toContain('可领上限')
    }
  })
  it('同部位不同加工状态按各自库存，合计不受BOM建议量限制', () => {
    const row = { requirement_id: 'one', stock_item_id: 'uncoated', line_type: 'SEMI', unit: '支',
      stock_mode: 'PUBLIC_V2', max_issue_quantity: '30', order_remaining: '10',
      component_order_remaining: '10', conversion_snapshot: { kind: 'PUBLIC_SEMI', component_identity: 'part' } } as MaterialRequirement
    const other = { ...row, requirement_id: 'two', stock_item_id: 'coated' }
    expect(issueSelectedQuantityError('25', row, [row, other], { one: '25', two: '25' })).toBe('')
  })
  it('不同部位共用同一实物库存时合计不超过扣占用后的可用量', () => {
    const row = { requirement_id: 'one', stock_item_id: 'shared', line_type: 'SEMI', unit: '支',
      stock_mode: 'PUBLIC_V2', max_issue_quantity: '30', conversion_snapshot: { kind: 'PUBLIC_SEMI' } } as MaterialRequirement
    const other = { ...row, requirement_id: 'two' }
    expect(issueSelectedQuantityError('20', row, [row, other], { one: '10', two: '15' })).toContain('合计申请数量')
    expect(issueSelectedQuantityError('15', row, [row, other], { one: '20', two: '15' })).toBe('')
  })
  it('不同切割支数按相同根长库存合计，其他根长独立', () => {
    const row = { ...pipe, requirement_id: 'one', stock_item_id: 'pipe', max_issue_quantity: '60' }
    const other = { ...row, requirement_id: 'two', max_issue_quantity: '40',
      conversion_snapshot: { ...row.conversion_snapshot!, pieces_per_bar: 4 } }
    expect(issueSelectedQuantityError('36', row, [row, other], { one: '36', two: '20' })).toContain('合计申请数量')
    expect(issueSelectedQuantityError('30', row, [row, other], { one: '30', two: '20' })).toBe('')
    other.conversion_snapshot.raw_bar_length_m = '4.05'
    expect(issueSelectedQuantityError('60', row, [row, other], { one: '60', two: '40' })).toBe('')
  })
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
