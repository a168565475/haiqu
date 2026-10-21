import { describe, expect, it } from 'vitest'
import type { BomLine } from '@/types/bom'
import { pipePlan, pipePlanForBomLine } from './materialFlow'

describe('管材 BOM 换算', () => {
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
})
