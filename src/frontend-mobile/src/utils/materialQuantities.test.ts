import { describe, expect, it } from 'vitest'
import type { MaterialIssueLine, MaterialRequirement } from '@/types/materialIssue'
import { buildIssueLines, decimalUnits, pipePlan, quantityError, quantityText, restoreIssueQuantities, selectedQuantityError } from './materialQuantities'

const ordinary = { requirement_id: 'one', stock_item_id: 'stock', material_name: '面料', line_type: 'RAW', unit: '米', max_issue_quantity: '30', stock_mode: 'PUBLIC_V2' } as MaterialRequirement
const pipe = { ...ordinary, unit: '支', conversion_snapshot: { kind: 'PIPE', pieces_per_bar: 6, raw_bar_length_m: '3.05' }, max_issue_quantity: '99999999999999' } as MaterialRequirement

describe('手机领料数量和分配', () => {
  it('拒绝指数、负数和超过四位小数，保持大数精度', () => {
    for (const input of ['1e3', '-1', 'Infinity', '1.00001', '']) expect(decimalUnits(input)).toBeNull()
    expect(decimalUnits('99999999999999.9999')).toBe(999999999999999999n)
    expect(quantityText('1000.0000')).toBe('1000')
  })
  it('空白和零行不提交，其余行允许部分领取', () => {
    const rows = [ordinary, { ...ordinary, requirement_id: 'two' }, { ...ordinary, requirement_id: 'three' }]
    expect(buildIssueLines(rows, { one: '', two: '0.0000', three: '1.25' })).toEqual([{ requirement_id: 'three', requested_quantity: '1.25' }])
  })
  it('BOM建议量不是领料上限，当前合格库存仍是上限', () => {
    const row = { ...ordinary, order_remaining: '0', max_issue_quantity: '30' }
    expect(quantityError('25', row)).toBe('')
    expect(quantityError('30.0001', row)).toContain('可领上限')
  })
  it('同一实物库存的多行合计不能超库存', () => {
    const other = { ...ordinary, requirement_id: 'two' }
    expect(selectedQuantityError('20', ordinary, [ordinary, other], { one: '20', two: '15' })).toContain('合计申请数量')
    expect(selectedQuantityError('15', ordinary, [ordinary, other], { one: '20', two: '15' })).toBe('')
  })
  it('原管按整根切支，米数不经过浮点运算', () => {
    expect(pipePlan('12', pipe)).toEqual({ error: '', bars: '2', meters: '6.10' })
    expect(pipePlan('99999999999996', pipe).meters).toBe('50833333333331.30')
    expect(quantityError('7', pipe)).toContain('正整数倍')
    expect(quantityError('6.5', pipe)).toContain('正整数倍')
  })
  it('同根长不同切支数合计根数，异长库存独立', () => {
    const first = { ...pipe, max_issue_quantity: '60' }
    const second = { ...first, requirement_id: 'two', max_issue_quantity: '40', conversion_snapshot: { ...pipe.conversion_snapshot!, pieces_per_bar: 4 } }
    expect(selectedQuantityError('36', first, [first, second], { one: '36', two: '20' })).toContain('合计')
    expect(selectedQuantityError('30', first, [first, second], { one: '30', two: '20' })).toBe('')
    second.conversion_snapshot.raw_bar_length_m = '4.05'
    expect(selectedQuantityError('60', first, [first, second], { one: '60', two: '40' })).toBe('')
  })
  it('管材半成品可领单支，不套用原管整根规则；支/套必须整数', () => {
    const semi = { ...pipe, line_type: 'SEMI', max_issue_quantity: '12' } as MaterialRequirement
    expect(quantityError('5', semi)).toBe('')
    expect(quantityError('5.5', semi)).toContain('正整数')
    expect(quantityError('1.5', { ...semi, unit: '套', conversion_snapshot: undefined })).toContain('正整数')
    expect(quantityError('1.5', { ...semi, unit: 'PCS', conversion_snapshot: { kind: 'SEMI_PIPE' } })).toContain('正整数')
  })
  it('PUBLIC_V2需求ID保留，不被历史半成品余额拆分', () => {
    const row = { ...ordinary, line_type: 'SEMI', semi_balance_allocations: [{ balance_id: 'legacy', max_issue_quantity: '10' }] } as MaterialRequirement
    expect(buildIssueLines([row], { one: '5' })).toEqual([{ requirement_id: 'one', requested_quantity: '5' }])
  })
  it('LEGACY半成品按各余额可领量拆分且不静默截断', () => {
    const row = { ...ordinary, stock_mode: 'LEGACY', line_type: 'SEMI', unit: '支', semi_balance_allocations: [
      { balance_id: 'balance-a', max_issue_quantity: '3' }, { balance_id: 'balance-b', max_issue_quantity: '4' },
    ] } as MaterialRequirement
    expect(buildIssueLines([row], { one: '5' })).toEqual([
      { requirement_id: 'balance-a', requested_quantity: '3' }, { requirement_id: 'balance-b', requested_quantity: '2' },
    ])
    expect(() => buildIssueLines([row], { one: '8' })).toThrow('可分配库存不足')
  })
  it('编辑还原多个历史余额为一行；缺失原明细阻断保存', () => {
    const row = { ...ordinary, stock_mode: 'LEGACY', line_type: 'SEMI', semi_balance_allocations: [
      { balance_id: 'balance-a', max_issue_quantity: '3' }, { balance_id: 'balance-b', max_issue_quantity: '4' },
    ] } as MaterialRequirement
    const lines = [{ requirement_id: 'balance-a', requested_quantity: '2' }, { requirement_id: 'balance-b', requested_quantity: '3' }] as MaterialIssueLine[]
    expect(restoreIssueQuantities(lines, [row])).toEqual({ one: '5' })
    expect(() => restoreIssueQuantities(lines, [])).toThrow('避免丢失明细')
  })
})
