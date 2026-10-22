import { describe, expect, it } from 'vitest'
import { sampleAllocationTotal, sampleShortageLines, sampleSupplyResult, validateSampleWarehouse } from './sampleWarehouse'
import type { SampleWarehouseLine } from '@/types/sampleWarehouse'
const line = (supplyQuantity: string): SampleWarehouseLine => ({ key: supplyQuantity, category: 'tube', name: '圆管', specification: 'Φ25', material: '', color: '', quantity: '12', unitId: 'meter', unitLabel: '米', notes: '', supplyQuantity })
describe('仓库可供与采购缺口', () => {
  it('管材按整根精确折算小数米数，关联合计必须和供料一致', () => {
    const selections = [{ balanceId: 'b', stockMode: 'PUBLIC_V2' as const, quantity: '3', rawBarLengthM: '6.14', materialNumber: 'M1', warehouseName: '仓', zoneName: '区', unitLabel: '根', availableQuantity: '5', meterQuantity: '30.70' }]
    expect(sampleAllocationTotal('tube', selections)).toBe('18.42')
    const demand = { ...line('18.42'), quantity: '20', inventoryAllocations: selections }
    expect(validateSampleWarehouse({ lines: [demand], notes: '' })).toBe('')
    expect(validateSampleWarehouse({ lines: [{ ...demand, supplyQuantity: '18' }], notes: '' })).toContain('查询库存勾选来源')
    expect(sampleAllocationTotal('tube', [{ ...selections[0]!, quantity: '1.5' }])).toBeNull()
  })
  it('不将空输入或无效输入当作库存为零', () => {
    expect(sampleSupplyResult('12', '')).toMatchObject({ valid: false, gap: null, result: 'pending' })
    expect(sampleSupplyResult('12', '-1')).toMatchObject({ valid: false, gap: null })
    expect(sampleSupplyResult('12', '13')).toMatchObject({ valid: false, gap: null })
    expect(sampleSupplyResult('0', '0')).toMatchObject({ valid: false })
  })
  it('精确处理小数、零缺口和全部缺料', () => {
    expect(sampleSupplyResult('0.3', '0.1')).toEqual({ valid: true, result: 'partial', gap: '0.2' })
    expect(sampleSupplyResult('12.00', '12')).toEqual({ valid: true, result: 'full', gap: '0' })
    expect(sampleSupplyResult('12', '0')).toEqual({ valid: true, result: 'none', gap: '12' })
    expect(sampleSupplyResult('10000000000000.10', '10000000000000.01')).toMatchObject({ gap: '0.09' })
    expect(sampleSupplyResult('10000000000000000.10', '10000000000000000.01')).toMatchObject({ valid: false })
  })
  it('提交前要求所有行已核对，采购清单只包含正缺口', () => {
    const draft = { lines: [line('12'), line('2'), line('0'), line('')], notes: '' }
    expect(validateSampleWarehouse(draft)).toContain('第 4 项')
    expect(sampleShortageLines(draft).map(item => item.shortageQuantity)).toEqual(['10', '12'])
    expect(validateSampleWarehouse({ ...draft, lines: draft.lines.slice(0, 3) })).toBe('')
  })
})
