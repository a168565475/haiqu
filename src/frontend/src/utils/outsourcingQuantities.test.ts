import { describe, expect, it } from 'vitest'
import { decimalUnits, outsourcingPlan } from './outsourcingQuantities'
import type { OutsourcingConversion } from '@/types/outsourcing'

const pipe: OutsourcingConversion = { schema_version: 2, kind: 'PIPE', pieces_per_bar: 6, raw_bar_length_m: '3.05' }
const fabric: OutsourcingConversion = { schema_version: 2, kind: 'FABRIC', fabric_meters_per_set: '1.5' }

describe('外发数量与库存计量', () => {
  it('402 支精确扣除 67 根与 204.35 米', () => {
    expect(outsourcingPlan('402', pipe)).toMatchObject({ error: '', output: '402', raw: '67', meters: '204.35' })
  })
  it.each(['400', '6.1', '0', '-6', 'NaN'])('拒绝非整根或无效管材输入 %s', value => {
    expect(outsourcingPlan(value, pipe).error).not.toBe('')
  })
  it('面料分离整数套数和余米', () => {
    expect(outsourcingPlan('100', fabric)).toMatchObject({ output: '66', remainder: '1.0000', raw: '100.0000' })
    expect(outsourcingPlan('1', fabric)).toMatchObject({ output: '0', remainder: '1.0000' })
  })
  it('小数计算精确并拒绝超精度和科学计数法', () => {
    expect(outsourcingPlan('0.3', { schema_version: 2, kind: 'FABRIC', fabric_meters_per_set: '0.1' })).toMatchObject({ output: '3', remainder: '0.0000' })
    for (const value of ['1e3', '0.00001', '-1', '']) expect(decimalUnits(value)).toBeNull()
  })
})
