import { describe, expect, it } from 'vitest'
import type { BomLine } from '@/types/bom'
import { pipePlan, pipePlanForBomLine } from './materialFlow'

describe('管材 BOM 换算', () => {
  it.each([
    ['499', 'PLUS_5', '5', '504'], ['500', 'PLUS_5', '5', '505'],
    ['501', 'PLUS_8', '8', '509'], ['1000', 'PLUS_8', '8', '1008'],
    ['1001', 'PERCENT_1', '11', '1012'], ['5000', 'PERCENT_1', '50', '5050'],
    ['5001', 'PERCENT_1', '51', '5052'],
  ])('自动采购余量按基础根数 %s 选档，边界归前档', (quantity, rule, allowance, total) => {
    expect(pipePlan('500', '1', '1', quantity, 4, { purchase_allowance_mode: 'AUTO' })).toMatchObject({
      base_purchase_bar_count: quantity, purchase_allowance_rule: rule, purchase_allowance_bar_count: allowance, branch_count: total,
    })
  })
  it('手动选择可跨默认档，按基础整根数计算且来源余量不重复叠加', () => {
    const source = { purchase_allowance_mode: 'MANUAL' as const, purchase_allowance_rule: 'PERCENT_0_5' as const, source_purchase_allowance_percent: '1' }
    expect(pipePlan('500', '1', '3', '3001', 4, source)).toMatchObject({
      base_purchase_bar_count: '1001', purchase_allowance_bar_count: '6', branch_count: '1007', suggested_purchase_meters: '1560.85',
    })
    expect(pipePlan('500', '1', '1', '5001', 4, { ...source, purchase_allowance_rule: 'PLUS_5' })?.branch_count).toBe('5006')
    expect(pipePlan('500', '1', '1', '1', 4, { ...source, purchase_allowance_rule: 'NONE' })?.branch_count).toBe('1')
    expect(pipePlan('500', '1', '1', '500', 4, { purchase_allowance_mode: 'MANUAL' })).toBeNull()
  })
  it('保存的新模式在回显和数量变化后沿用手动项，旧行显式选择才应用新规则', () => {
    const saved: Partial<BomLine> = { cutting_length_mm: 500, pieces_per_product: 1, pieces_per_bar: 1, raw_values: { pipe_plan_version: '4', purchase_allowance_mode: 'MANUAL', purchase_allowance_rule: 'PERCENT_0_5' } }
    const input = { length_value: '500', unit_consumption: '1', tube_cut_piece_count: '1' }
    expect(pipePlanForBomLine(input, '500', saved)).toMatchObject({ branch_count: '503', purchase_allowance_rule: 'PERCENT_0_5' })
    expect(pipePlanForBomLine(input, '1000', saved)).toMatchObject({ branch_count: '1005', purchase_allowance_rule: 'PERCENT_0_5' })
    const legacy = { ...saved, raw_values: {} }
    expect(pipePlanForBomLine(input, '500', legacy)?.branch_count).toBe('505')
    expect(pipePlanForBomLine({ ...input, purchase_allowance_mode: 'MANUAL', purchase_allowance_rule: 'PLUS_8' }, '500', legacy)).toMatchObject({ base_purchase_bar_count: '500', branch_count: '508' })
    expect(pipePlanForBomLine({ ...input, unit_consumption: '2' }, '500', { ...saved, raw_values: { pipe_plan_version: '4' } })).toMatchObject({ base_purchase_bar_count: '1000', branch_count: '1008', purchase_allowance_rule: 'PLUS_8' })
  })
  it('新计算不加余量，每根长度及采购根数仍向上取整', () => {
    expect(pipePlan('500', '2', '6', '1000')).toEqual({ total_consumption: '2000', branch_count: '334', tube_cut_length_m: '3.05', suggested_purchase_meters: '1018.70' })
    expect(pipePlan('500', '2', '5', '2000')?.branch_count).toBe('800')
    expect(pipePlan('501', '2', '6', '1000')?.tube_cut_length_m).toBe('3.06')
  })
  it('旧版本原样保留1%计算，旧行参数改变才使用新规则', () => {
    expect(pipePlan('500', '2', '6', '1000', 2)?.branch_count).toBe('337')
    const saved: Partial<BomLine> = { cutting_length_mm: 500, pieces_per_product: 2, pieces_per_bar: 5, raw_values: {} }
    const input = { length_value: '500', unit_consumption: '2', tube_cut_piece_count: '5' }
    expect(pipePlanForBomLine(input, '2000', saved)?.branch_count).toBe('808')
    expect(pipePlanForBomLine({ ...input, length_value: '500.0', tube_cut_piece_count: '5.000' }, '2000', saved)?.branch_count).toBe('808')
    expect(pipePlanForBomLine({ ...input, length_value: '501' }, '2000', saved)?.branch_count).toBe('800')
    expect(pipePlanForBomLine(input, '2000', { ...saved, raw_values: { pipe_plan_version: '3' } })?.branch_count).toBe('800')
    expect(pipePlanForBomLine(input, '2000', { ...saved, raw_values: { pipe_plan_version: '9' } })).toBeNull()
    expect(saved.raw_values).toEqual({})
  })
  it('小数毫米、半支、负数、空值和越界不产生误导性预览', () => {
    for (const value of ['', '0', '-1', 'NaN', 'Infinity', '1.1', '999999999999999']) expect(pipePlan(value, '2', '6', '1000')).toBeNull()
    expect(pipePlan('500', '2', '6.5', '1000')).toBeNull()
    expect(pipePlan('500', '2', '6', '1000.0000')?.branch_count).toBe('334')
  })
  it('原表余量只影响采购根数，原表长料长度用于采购米数', () => {
    const input = { length_value: '470', unit_consumption: '3', tube_cut_piece_count: '12', source_purchase_allowance_percent: '1', source_raw_bar_length_m: '5.72' }
    expect(pipePlanForBomLine(input, '500')).toEqual({ total_consumption: '1500', branch_count: '127', tube_cut_length_m: '5.72', suggested_purchase_meters: '726.44' })
    expect(pipePlanForBomLine(input, '1000')?.branch_count).toBe('253')
    expect(pipePlanForBomLine({ ...input, unit_consumption: '4' }, '500')?.branch_count).toBe('169')
    expect(pipePlanForBomLine({ ...input, length_value: '480' }, '500')).toBeNull()
  })
  it('来源精度边界与后端一致，明确的零余量覆盖旧规则，空串撤销来源覆盖', () => {
    const input = { length_value: '500', unit_consumption: '2', tube_cut_piece_count: '6', source_purchase_allowance_percent: '0', source_raw_bar_length_m: '3.1000' }
    const saved = { cutting_length_mm: 500, pieces_per_product: 2, pieces_per_bar: 6, raw_values: { source_purchase_allowance_percent: '1', source_raw_bar_length_m: '3.10' } }
    expect(pipePlanForBomLine(input, '1000', saved)?.branch_count).toBe('334')
    expect(pipePlanForBomLine({ ...input, source_purchase_allowance_percent: '0.0001' }, '3')?.branch_count).toBe('2')
    expect(pipePlanForBomLine({ ...input, source_purchase_allowance_percent: '100' }, '3')?.branch_count).toBe('2')
    expect(pipePlanForBomLine({ ...input, source_purchase_allowance_percent: '', source_raw_bar_length_m: '' }, '1000', saved)).toMatchObject({ branch_count: '337', tube_cut_length_m: '3.05' })
    for (const value of ['-1', '101', 'NaN', 'Infinity', '1.00001']) {
      expect(pipePlanForBomLine({ ...input, source_purchase_allowance_percent: value }, '1000')).toBeNull()
    }
    for (const value of ['0', '-1', 'NaN', '3.101', '2.99', '10000000000000000']) {
      expect(pipePlanForBomLine({ ...input, source_raw_bar_length_m: value }, '1000')).toBeNull()
    }
  })
})
