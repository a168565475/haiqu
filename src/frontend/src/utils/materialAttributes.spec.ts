import { describe, expect, it } from 'vitest'

import { materialAttributeFields } from './materialAttributes'

describe('采购物料属性展示', () => {
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
