import { describe, expect, it } from 'vitest'
import type { BomDetail, BomLineInput } from '@/types/bom'
import { blankLine, manualTubeMetricError, tubeCalculations } from './bomEditorHelpers'

function line(): BomLineInput {
  return { ...blankLine('根'), tube_shape: '圆管', tube_diameter: '20', tube_thickness: '1', length_value: '500', unit_consumption: '4', tube_cut_piece_count: '10' }
}

describe('管材重量显示', () => {
  it('新行尚未取得公式预览时不显示固定每米重量', () => {
    const values = tubeCalculations(line(), { order_quantity: '100', sections: [] } as unknown as BomDetail)
    expect(values.tube_unit_weight_kg).toBe('—')
    expect(values.long_material_unit_weight_kg).toBe('—')
  })

  it('使用服务端单支重量，改变单耗不把单支重量乘数量', () => {
    const draft = line()
    Object.assign(draft, { tube_calculation_preview: {
      coating_unit_area_sqm: '0.0314', purchase_unit_weight_kg: '0.2343', long_material_unit_weight_kg: '2.3663',
    } })
    const bom = { order_quantity: '100', sections: [] } as unknown as BomDetail
    expect(tubeCalculations(draft, bom).tube_unit_weight_kg).toBe('0.2343')
    draft.unit_consumption = '8'
    expect(tubeCalculations(draft, bom).tube_unit_weight_kg).toBe('0.2343')
    expect(tubeCalculations(draft, bom).long_material_total_weight_kg).toBe('189.304')
  })

  it('手填显示单支重量，不推算长料重量，数量变化不改变手填值', () => {
    const draft = { ...line(), manual_tube_metrics: true, coating_unit_area_sqm: '0.1234', purchase_unit_weight_kg: '0.5678' }
    const bom = { order_quantity: '100', sections: [] } as unknown as BomDetail
    expect(tubeCalculations(draft, bom)).toMatchObject({ tube_unit_weight_kg: '0.5678', long_material_unit_weight_kg: '—', long_material_total_weight_kg: '—' })
    draft.unit_consumption = '9'
    expect(tubeCalculations(draft, bom).tube_unit_weight_kg).toBe('0.5678')
  })

  it('手填两项必填，允许零，拒绝负数、非数和超出精度或范围的值', () => {
    const draft = { ...line(), manual_tube_metrics: true, coating_unit_area_sqm: '0', purchase_unit_weight_kg: '0.0000' }
    expect(manualTubeMetricError(draft)).toBe('')
    for (const invalid of ['', '-1', 'NaN', '0.12345', '1000000000000']) {
      expect(manualTubeMetricError({ ...draft, purchase_unit_weight_kg: invalid })).toContain('单支重量')
    }
  })
})
