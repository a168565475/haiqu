import { describe, expect, it } from 'vitest'

import { materialAttributeFields } from './materialAttributes'

describe('采购物料属性展示', () => {
  it('普通颜色快照按色卡色号颜色展示，不输出内部颜色ID', () => {
    const selected = { schema_version: 1, name: '布料', template_key: 'FABRIC', unit_name: '米',
      product_color_id: 'color-id', color_card: 'A色卡', color_code: '102', color_name: '米白', attributes: { color: '米白' } }
    expect(materialAttributeFields({ material_selection_snapshot: selected as never })).toEqual([
      { key: 'part_name', label: '品名', value: '布料' }, { key: 'color_card', label: '色卡', value: 'A色卡' },
      { key: 'color_code', label: '色号', value: '102' }, { key: 'color', label: '颜色', value: '米白' }, { key: 'unit', label: '数量单位', value: '米' },
    ])
  })
  it('新材料显示保存选择的完整属性和单位，不回退到旧投影', () => {
    const selected = { schema_version: 1, name: '保存的管材', template_key: 'TUBE', unit_name: '公斤',
      attributes: { material: '铁', shape: '圆管', section_size: '20', thickness: '1', length: '6000' } }
    const fields = materialAttributeFields({ material_selection_snapshot: selected as never, material: '过时投影' })
    expect(fields).toContainEqual({ key: 'section_size', label: '规格', value: '20' })
    expect(fields).toContainEqual({ key: 'thickness', label: '厚度', value: '1' })
    expect(fields).toContainEqual({ key: 'unit', label: '数量单位', value: '公斤' })
    expect(fields.some(field => field.value === '过时投影')).toBe(false)
  })
  it('不显示喷塑颜色', () => {
    const fields = materialAttributeFields({
      material_attributes_snapshot: {
        fields: [
          { key: 'specification', label: '规格', value: 'Φ22' },
          { key: 'tube_coating_color', label: '喷塑颜色', value: '黑色' },
        ],
      },
    })

    expect(fields).toEqual([{ key: 'specification', label: '规格', value: 'Φ22' }])
  })
})
