import { describe, expect, it } from 'vitest'
import { packagingQuantity } from './bomPackagingQuantity'
import { bomPreviewCell } from './bomPreview'
import { blankLine } from '@/views/boms/bomEditorHelpers'

describe('包材按装箱量计算需求', () => {
  it.each([['10', '20', '2'], ['10', '21', '3'], ['10', '0', '0'], ['10', '20.0001', '3'], ['3', '999999999999', '333333333333']])('%s个一箱，订单%s个需%s', (box, order, expected) => {
    expect(packagingQuantity(box, order)).toBe(expected)
  })
  it.each(['', '0', '-1', '1.5', 'NaN', 'Infinity'])('无效装箱量%s不产生假数量', box => {
    expect(packagingQuantity(box, '25')).toBe('')
  })
  it('预览使用当前装箱量与订单量，忽略旧单耗和旧总耗', () => {
    const line = { ...blankLine('个'), units_per_box: '10', unit_consumption: '999', total_consumption: '999' }
    const section = { title: '包材类', section_type: 'ACCESSORY' as const, lines: [line] }
    expect(bomPreviewCell(line, 'total_consumption', section, '25', [section])).toBe('3')
  })
})
