import { describe, expect, it } from 'vitest'
import type { BomLine, BomSection } from '@/types/bom'
import { bomPreviewCell, bomPreviewColumns } from './bomPreview'

const section = (title: string, section_type: BomSection['section_type'] = 'ACCESSORY') => ({ title, section_type, lines: [] } as unknown as BomSection)
const line = (values: Partial<BomLine>) => ({ material: '', category: '', cutting_category: '', ...values } as BomLine)
const columns: Array<[string, string[]]> = [
  ['管材类', ['序号', '部件名称', '材质', '喷塑颜色', '规格', '切割长度（mm）', '单耗', '总需求（支）', '切割支数', '原材料长度（m）', '采购根数', '建议采购米数', '备注']],
  ['五金件', ['序号', '品名', '材质', '颜色', '规格', '单位', '单个用量', '单个材料重量（kg）', '喷塑颜色', '喷塑单个面积（㎡）', '备注', '图片']],
  ['塑料件类', ['序号', '品名', '材质', '颜色', '规格', '单位', '单个用量', '备注', '图片']],
  ['辅料类', ['序号', '品名', '规格', '颜色', '材质', '单位', '单个用量', '备注', '图片']],
  ['面料类', ['序号', '规格', '材质', '色卡', '颜色', '色号', '门幅', '单个用量', '裁片', '单位', '备注', '图片']],
  ['包材类', ['序号', '品名', '材质', '颜色', '规格', '单位', '箱数（多少一箱）', '单个用量', '图片']],
  ['裁剪明细', ['序号', '裁剪名称', '规格', '裁片量（片/套）', '每成品套数（套/成品）', '订单裁剪套数', '订单裁剪片数', '流转单位', '图片', '备注']],
]

describe('BOM 预览按编辑分区展示', () => {
  it.each(columns)('%s 保留独立字段顺序，省去原料编号', (title, labels) => {
    const result = bomPreviewColumns(section(title, title === '管材类' ? 'PROFILE' : 'ACCESSORY'))
    expect(result.map(column => column.label)).toEqual(labels)
    expect(result.some(column => /material_number|raw_material|source_serial|material_code/.test(column.key))).toBe(false)
  })

  it('新管材按净需求及 BOM 数量计算，与编辑一致，不读失效的历史结果', () => {
    const row = line({ length_value: '530', unit_consumption: '2', tube_cut_piece_count: '5', total_consumption: '999', branch_count: '999', tube_cut_length_m: '999', suggested_purchase_meters: '999' })
    const part = section('管材类', 'PROFILE')
    const value = (key: string) => bomPreviewCell(row, key, part, '5000.0000', [])
    expect([value('total_consumption'), value('tube_cut_length_m'), value('branch_count'), value('suggested_purchase_meters')]).toEqual(['10000', '2.70', '2000', '5400.00'])
    expect(bomPreviewCell({ ...row, tube_cut_piece_count: '' }, 'branch_count', part, '5000', [])).toBe('—')
  })

  it.each([undefined, 2, 3])('已保存管材按版本 %s 预览，未标记旧行保留 1%% 余量', version => {
    const row = line({
      length_value: '530', unit_consumption: '2', tube_cut_piece_count: '5',
      cutting_length_mm: 530, pieces_per_product: 2, pieces_per_bar: 5,
      raw_values: version === undefined ? {} : { pipe_plan_version: String(version) },
    })
    const before = structuredClone(row)
    const value = (key: string) => bomPreviewCell(row, key, section('管材类', 'PROFILE'), '5000', [])
    expect([value('branch_count'), value('suggested_purchase_meters')]).toEqual(
      version === 3 ? ['2000', '5400.00'] : ['2020', '5454.00'],
    )
    expect(row).toEqual(before)
  })

  it('编辑旧行参数后按新规则预览，不改写已保存旧行的计算基准', () => {
    const saved = line({
      length_value: '530', unit_consumption: '2', tube_cut_piece_count: '5',
      cutting_length_mm: 530, pieces_per_product: 2, pieces_per_bar: 5, raw_values: {},
    })
    const before = structuredClone(saved)
    const edited = { ...saved, length_value: '531' }
    const value = (key: string) => bomPreviewCell(edited, key, section('管材类', 'PROFILE'), '5000', [], saved)
    expect([value('branch_count'), value('tube_cut_length_m'), value('suggested_purchase_meters')]).toEqual(['2000', '2.71', '5420.00'])
    expect(saved).toEqual(before)
  })

  it('空名称不以原料编号代替；颜色与零值按实际字段展示', () => {
    const row = line({ part_name: '', raw_material: 'SECRET-CODE', hardware_color: '/', unit_material_weight_kg: '0' })
    expect(bomPreviewCell(row, 'part_name', section('五金件'), '1', [])).toBe('—')
    expect(bomPreviewCell(row, 'hardware_color', section('五金件'), '1', [])).toBe('无颜色（/）')
    expect(bomPreviewCell(row, 'unit_material_weight_kg', section('五金件'), '1', [])).toBe('0')
  })

  it('面料单位和色卡、包材箱数使用各自字段', () => {
    const fabric = line({ unit: '套', fabric_color_card: '色卡A', fabric_color_name: '蓝色', fabric_color_code: '#2' })
    expect(bomPreviewCell(fabric, 'unit', section('面料类'), '1', [])).toBe('米')
    expect(bomPreviewCell(fabric, 'fabric_color_card', section('面料类'), '1', [])).toBe('色卡A / 蓝色 / #2')
    expect(bomPreviewCell(line({ units_per_box: '4', unit_consumption: '1' }), 'units_per_box', section('包材类'), '1', [])).toBe('4')
  })

  it('裁剪只按片套计算订单数量，不依赖历史米数', () => {
    const row = line({ material: '/', cutting_pieces_per_set: 3, cutting_sets_per_product: 2, fabric_source_line_id: 'fabric-1' })
    const fabric = { ...section('面料类'), lines: [line({ id: 'fabric-1', material: 'PE', unit: '米' })] }
    const value = (key: string) => bomPreviewCell(row, key, section('裁剪明细'), '10', [fabric])
    expect([value('cutting_pieces_per_set'), value('cutting_sets_per_product'), value('order_cutting_sets'), value('order_cutting_pieces'), value('unit')]).toEqual(['3', '2', '20', '60', '套'])
    expect(bomPreviewCell({ ...row, cutting_sets_per_product: null }, 'order_cutting_pieces', section('裁剪明细'), '10', [])).toBe('—')
    expect(bomPreviewCell({ ...row, material: '服务端补齐值', cutting_material_original: '手填材质' }, 'material', section('裁剪明细'), '10', [fabric])).toBe('手填材质')
    const unsavedFabric = { ...section('面料类'), lines: [{ ...line({ material: '新增面料', unit: '米' }), client_key: 'local-fabric' }] }
    expect(bomPreviewCell({ ...row, fabric_source_line_id: null, fabric_source_client_key: 'local-fabric' }, 'material', section('裁剪明细'), '10', [unsavedFabric])).toBe('新增面料')
  })

  it('管材旧裁剪只读试算与编辑一致，普通旧裁剪不反推新参数', () => {
    const row = line({ category: '管材', cut_piece_quantity: '3', fabric_meters_per_set: '2', unit: '根' })
    const value = (item: BomLine, key: string) => bomPreviewCell(item, key, section('裁剪明细'), '10', [])
    expect([value(row, 'cutting_pieces_per_set'), value(row, 'cutting_sets_per_product'), value(row, 'unit')]).toEqual(['3', '1', '根'])
    expect(value({ ...row, category: '布面' }, 'cutting_pieces_per_set')).toBe('—')
    expect(value(row, 'order_cutting_pieces')).toBe('—')
    expect(row).not.toHaveProperty('cutting_pieces_per_set')
  })
})
