import { describe, expect, it } from 'vitest'

import { materialAttributeFields, materialSpecificationValue } from './materialAttributes'

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

describe('采购物料规格列', () => {
  it.each([
    ['TUBE', { section_size: '20×20', thickness: '1.5', material: 'Q235' }, '20×20'],
    ['FABRIC', { fabric_spec: '600D', width: '150 cm', material: '涤纶' }, '600D'],
    ['HARDWARE', { specification: 'M6', size: '30 mm', material: '钢' }, 'M6'],
  ])('有目录规格时只显示 %s 的规格', (template_key, attributes, expected) => {
    const snapshot = { schema_version: 1, name: '材料名称', template_key, attributes }
    expect(materialSpecificationValue({ part_name: snapshot.name, specification: '旧投影', material_selection_snapshot: snapshot as never })).toBe(expected)
  })

  it('目录没有明确规格时，用尺寸和材质代替 BOM 拼出的规格', () => {
    const snapshot = { schema_version: 1, name: '连接件', template_key: 'PLASTIC',
      attributes: { size: '30×20 mm', material: '尼龙' } }
    expect(materialSpecificationValue({ specification: '30×20 mm', material_selection_snapshot: snapshot as never })).toBe('尺寸 30×20 mm / 材质 尼龙')
  })

  it('保留与品名不同的旧单规格和目录未投影的独立规格', () => {
    const snapshot = { schema_version: 1, name: '扣件', template_key: 'HARDWARE', attributes: { material: '不锈钢' } }
    expect(materialSpecificationValue({ part_name_snapshot: '扣件', specification_snapshot: 'M8×12', material_snapshot: '不锈钢' })).toBe('M8×12')
    expect(materialSpecificationValue({ specification: 'M8×12', material_selection_snapshot: snapshot as never })).toBe('M8×12')
  })

  it('排除同名的历史规格，再用历史尺寸和材质', () => {
    const source = { part_name_snapshot: '扣件', specification_snapshot: ' 扣件 ', material_snapshot: '尼龙',
      material_attributes_snapshot: { fields: [
        { key: 'specification', label: '规格', value: '扣件' }, { key: 'size', label: '尺寸', value: '30 mm' },
      ] } }
    expect(materialSpecificationValue(source)).toBe('尺寸 30 mm / 材质 尼龙')
    expect(materialSpecificationValue({ material_name: '扣件', specification: '扣件' })).toBe('—')
  })
})
