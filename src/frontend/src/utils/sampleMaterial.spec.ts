import { describe, expect, it } from 'vitest'
import { validateSampleMaterials } from './sampleMaterial'
import type { SampleMaterialDraft } from '@/types/sampleMaterial'

const units = [{ id: 'meter', label: '米', decimalPlaces: 2 }, { id: 'piece', label: '个', decimalPlaces: 0 }]
function draft(quantity = '1.25', unitId = 'meter'): SampleMaterialDraft {
  return { lines: [{ key: 'local', category: 'hardware', rawMaterialId: 'raw', name: '圆管', specification: 'Φ25 × 1.2 mm', material: '', color: '', quantity, unitId, notes: '' }], notes: '' }
}
describe('材料需求校验与接口边界', () => {
  it('校验各分区总需求，允许按单位精度填写小数', () => {
    expect(validateSampleMaterials(draft(), units)).toBe('')
    expect(validateSampleMaterials(draft('1.25', 'piece'), units)).toContain('0 位小数')
    expect(validateSampleMaterials(draft('1.255'), units)).toContain('2 位小数')
  })
  it.each(['0', '-2', 'NaN', 'Infinity', '1e3', ''])('拒绝无效数量 %s', value => {
    expect(validateSampleMaterials(draft(value), units)).not.toBe('')
  })
  it('不将失效单位或空需求当成可提交记录', () => {
    expect(validateSampleMaterials(draft('1', 'missing'), units)).toContain('有效单位')
    expect(validateSampleMaterials({ lines: [], notes: '' }, units)).toContain('至少')
  })
  it('拒绝超过服务端数量范围的数据', () => {
    expect(validateSampleMaterials(draft('100000000000000'), units)).toContain('14 位')
    expect(validateSampleMaterials(draft('1.00001'), units)).toContain('4 位')
  })
})


describe('打样管材总米数', () => {
  it('按总米数校验、单位必须为米且必须选择原材料身份', () => {
    const input = draft('20', 'meter')
    Object.assign(input.lines[0]!, { category: 'tube', rawMaterialId: 'raw' })
    expect(validateSampleMaterials(input, units)).toBe('')
    input.lines[0]!.unitId = 'piece'
    expect(validateSampleMaterials(input, units)).toContain('单位必须是米')
    input.lines[0]!.unitId = 'meter'
    input.lines[0]!.quantity = '20'
    input.lines[0]!.rawMaterialId = ''
    expect(validateSampleMaterials(input, units)).toContain('原材料')
  })
})
