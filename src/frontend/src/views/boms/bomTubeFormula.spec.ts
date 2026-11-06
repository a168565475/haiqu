import { describe, expect, it } from 'vitest'
import type { BomDetail, BomLineInput } from '@/types/bom'
import { blankLine, defaultTubeSection, editableLine, manualTubeMetricError, tubeCalculations } from './bomEditorHelpers'

function line(): BomLineInput {
  return { ...blankLine('根'), tube_shape: '圆管', tube_diameter: '20', tube_thickness: '1', length_value: '500', unit_consumption: '4', tube_cut_piece_count: '10' }
}

describe('管材重量显示', () => {
  it('新建管材默认自动余量，历史行及已保存手动项不被重置', () => {
    expect(defaultTubeSection().lines[0]?.purchase_allowance_mode).toBe('AUTO')
    expect(editableLine({ ...line(), id: 'old' } as never).purchase_allowance_mode).toBeUndefined()
    expect(editableLine({ ...line(), id: 'saved', purchase_allowance_mode: 'MANUAL', purchase_allowance_rule: 'PERCENT_0_5' } as never)).toMatchObject({ purchase_allowance_mode: 'MANUAL', purchase_allowance_rule: 'PERCENT_0_5' })
  })
  it('基础根数与余量拆开显示，建议米数与长料总重使用两者合计', () => {
    const draft = { ...line(), purchase_allowance_mode: 'AUTO' as const, tube_calculation_preview: { formula_version: 'test-version',
      coating_unit_area_sqm: '0.0314', purchase_unit_weight_kg: '0.2343', long_material_unit_weight_kg: '2.3663',
    } }
    expect(tubeCalculations(draft, { order_quantity: '100', sections: [] } as unknown as BomDetail)).toMatchObject({
      base_purchase_bar_count: '40', purchase_allowance_bar_count: '5', branch_count: '45', purchase_allowance_rule: 'PLUS_5',
      suggested_purchase_meters: '227.25', long_material_total_weight_kg: '106.4835',
    })
  })
  it('编辑行修改订单数量后仍按原表余量及长料长度显示采购量', () => {
    const draft = { ...line(), length_value: '470', unit_consumption: '3', tube_cut_piece_count: '12', source_purchase_allowance_percent: '1', source_raw_bar_length_m: '5.72' }
    expect(tubeCalculations(draft, { order_quantity: '500', sections: [] } as unknown as BomDetail)).toMatchObject({
      total_consumption: '1500', branch_count: '127', tube_cut_length_m: '5.72', suggested_purchase_meters: '726.44',
    })
    expect(tubeCalculations(draft, { order_quantity: '1000', sections: [] } as unknown as BomDetail).branch_count).toBe('253')
  })
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
