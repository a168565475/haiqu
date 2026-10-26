import { describe, expect, it } from 'vitest'
import type { SupplierPurchaseSheetLine } from '@/types/purchaseOrder'
import { formatPurchaseSheetNumber, purchaseSheetLineDisplay } from './purchaseSheetLineDisplay'

const line = {
  part_name: '半通', specification: '16', material: 'PE', remark: '', section_title: '塑料件类',
  material_attributes_snapshot: { fields: [
    { key: 'part_name', label: '品名', value: '半通' },
    { key: 'material', label: '材质', value: 'PE' },
    { key: 'plastic_color', label: '颜色', value: '黑色' },
    { key: 'specification', label: '规格', value: '16' },
  ] },
} as SupplierPurchaseSheetLine

describe('采购表规格和颜色分列', () => {
  it('塑料件规格不重复，材质和颜色正确归列', () => {
    expect(purchaseSheetLineDisplay(line)).toEqual({ specification: '16', attributes: '材质：PE', color: '黑色' })
  })
  it('尊重合同修改值和清空值，不从冻结BOM回填旧规格材质', () => {
    expect(purchaseSheetLineDisplay({ ...line, specification: '18', material: 'PP', remark: '无毛刺' })).toEqual({ specification: '18', attributes: '材质：PP；要求：无毛刺', color: '黑色' })
    expect(purchaseSheetLineDisplay({ ...line, specification: '', material: '' }).specification).toBe('')
  })
  it('面料属性保留门幅色卡色号，颜色列只显示颜色', () => {
    const fabric = { ...line, specification: '600D', material: '涤纶', material_attributes_snapshot: { fields: [
      { key: 'fabric_width', label: '门幅', value: '150cm' },
      { key: 'fabric_color_card', label: '色卡', value: 'C1' },
      { key: 'fabric_color_name', label: '颜色', value: '蓝色' },
      { key: 'fabric_color_code', label: '色号', value: 'B1' },
    ] } } as SupplierPurchaseSheetLine
    expect(purchaseSheetLineDisplay(fabric)).toEqual({ specification: '600D', attributes: '材质：涤纶；门幅：150cm；色卡：C1；色号：B1', color: '蓝色' })
  })
  it('管材属性保留，过滤重复字段及不属于采购的喷塑颜色', () => {
    const pipe = { ...line, material_attributes_snapshot: { fields: [
      { key: 'tube_diameter', label: '直径', value: '16' },
      { key: 'tube_thickness', label: '厚度', value: '0.8' },
      { key: 'tube_thickness', label: '厚度', value: '0.8' },
      { key: 'tube_coating_color', label: '喷塑颜色', value: '红色' },
    ] } } as SupplierPurchaseSheetLine
    expect(purchaseSheetLineDisplay(pipe)).toEqual({ specification: '16', attributes: '材质：PE；直径：16；厚度：0.8', color: '' })
  })
  it('旧数据无颜色快照时不把材质当成颜色', () => {
    expect(purchaseSheetLineDisplay({ ...line, material_attributes_snapshot: undefined })).toEqual({ specification: '16', attributes: '材质：PE', color: '' })
  })
  it('样品材质要求放物料属性，原remark颜色保留在颜色列', () => {
    expect(purchaseSheetLineDisplay({ ...line, remark: '深蓝色' }, true)).toEqual({ specification: '16', attributes: '材质：PE；颜色：黑色', color: '深蓝色' })
  })
})

describe('采购表数字仅去除无意义尾零', () => {
  it.each([['48.0000', '48'], ['21.6000', '21.6'], ['0.4500', '0.45'], ['0.0000', '0'], ['0.0001', '0.0001'], ['9007199254740993.1200', '9007199254740993.12'], ['-0.0000', '0']])('%s 显示为 %s，保留有效小数精度', (input, expected) => {
    expect(formatPurchaseSheetNumber(input)).toBe(expected)
  })
  it('空值和非数字不假装为0', () => {
    expect(formatPurchaseSheetNumber(null)).toBe('—')
    expect(formatPurchaseSheetNumber('invalid')).toBe('—')
    expect(formatPurchaseSheetNumber('', '')).toBe('')
  })
})
