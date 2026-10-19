import type { BomLine, BomLineInput, BomSectionInput } from '@/types/bom'
import { cuttingCalculation, legacyPipeCuttingValues } from './bomCuttingQuantities'
import { pipePlan } from './materialFlow'

export interface BomPreviewColumn { key: string; label: string; width: number }
export type BomPreviewLine = BomLineInput & Pick<Partial<BomLine>, 'cutting_material_original'>
export type BomPreviewSection = Omit<BomSectionInput, 'lines'> & { lines: BomPreviewLine[] }
const column = (key: string, label: string, width = 110): BomPreviewColumn => ({ key, label, width })
const serial = column('line_number', '序号', 54)
const name = column('part_name', '品名', 140)
const material = column('material', '材质', 100)
const specification = column('specification', '规格', 160)
const unit = column('unit', '单位', 70)
const consumption = column('unit_consumption', '单个用量', 100)
const notes = column('notes', '备注', 170)
const images = column('images', '图片', 210)

/** 各分区遵循编辑页的字段与顺序；原料身份编号不属于预览列。 */
export function bomPreviewColumns(section: BomPreviewSection): BomPreviewColumn[] {
  if (section.section_type === 'PROFILE') return [
    serial, column('part_name', '部件名称', 140), material, column('tube_coating_color', '喷塑颜色'), specification,
    column('length_value', '切割长度（mm）', 120), column('unit_consumption', '单耗', 80),
    column('total_consumption', '总需求（支）'), column('tube_cut_piece_count', '切割支数', 90),
    column('tube_cut_length_m', '原材料长度（m）', 130), column('branch_count', '采购根数', 90),
    column('suggested_purchase_meters', '建议采购米数', 120), notes,
  ]
  if (/五金/.test(section.title)) return [
    serial, name, material, column('hardware_color', '颜色'), specification, unit, consumption,
    column('unit_material_weight_kg', '单个材料重量（kg）', 145), column('powder_coating_color', '喷塑颜色'),
    column('powder_coating_unit_area_sqm', '喷塑单个面积（㎡）', 150), notes, images,
  ]
  if (/塑料/.test(section.title)) return [serial, name, material, column('plastic_color', '颜色'), specification, unit, consumption, notes, images]
  if (/面料/.test(section.title)) return [
    serial, specification, material, column('fabric_color_card', '色卡', 180), column('fabric_color_name', '颜色'),
    column('fabric_color_code', '色号', 90), column('fabric_width', '门幅', 80), consumption,
    column('part_name', '裁片', 120), unit, notes, images,
  ]
  if (/辅料/.test(section.title)) return [serial, name, specification, column('accessory_color', '颜色'), material, unit, consumption, notes, images]
  if (/包材|包装/.test(section.title)) return [serial, name, material, column('packaging_color', '颜色'), specification, unit, column('units_per_box', '箱数（多少一箱）', 140), consumption, images]
  if (/裁剪|裁片/.test(section.title)) return [
    serial, column('part_name', '裁剪名称', 140), specification, material, column('cutting_color', '颜色'),
    column('cutting_pieces_per_set', '裁片量（片/套）', 130), column('fabric_meters_per_piece', '单个用量（米/片）', 145),
    column('cutting_sets_per_product', '每成品套数（套/成品）', 160), column('fabric_meters_per_set', '每套耗米（米/套）', 150),
    column('unit', '流转单位', 100), images, notes,
  ]
  return [serial, material, name, specification, consumption, column('total_consumption', '当前需求'), unit, notes, images]
}

function text(value: unknown) {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

export function bomPreviewCell(line: BomPreviewLine, key: string, section: BomPreviewSection, orderQuantity: string, sections: BomPreviewSection[]): string {
  if (section.section_type === 'PROFILE') {
    if (['total_consumption', 'tube_cut_length_m', 'branch_count', 'suggested_purchase_meters'].includes(key)) {
      const plan = pipePlan(line.length_value || '', line.unit_consumption || '', line.tube_cut_piece_count || '', orderQuantity)
      return plan ? plan[key as keyof typeof plan] : '—'
    }
    if (key === 'specification') return line.specification || `${line.tube_diameter || '—'} × ${line.tube_thickness || '—'}`
  }
  if (['hardware_color', 'plastic_color', 'packaging_color', 'cutting_color'].includes(key)) {
    const color = line[key as keyof BomPreviewLine]
    return !color || color === '/' ? '无颜色（/）' : String(color)
  }
  if (/面料/.test(section.title)) {
    if (key === 'unit') return '米'
    if (key === 'fabric_color_card') return text([line.fabric_color_card, line.fabric_color_name, line.fabric_color_code].filter(Boolean).join(' / '))
  }
  if (/裁剪|裁片/.test(section.title)) {
    const calculation = cuttingCalculation(line, orderQuantity)
    const legacy = legacyPipeCuttingValues(line)
    if (legacy) {
      if (key === 'cutting_pieces_per_set') return legacy.pieces
      if (key === 'fabric_meters_per_piece') return legacy.metersPerPiece
      if (key === 'cutting_sets_per_product') return legacy.sets
    }
    if (key === 'fabric_meters_per_set') return text(calculation.mode === 'legacy' ? line.fabric_meters_per_set : calculation.metersPerSet)
    if (key === 'unit') return calculation.mode === 'legacy' ? text(line.unit) : '套'
    if (key === 'material') {
      const ownMaterial = line.cutting_material_original ?? line.material
      if (ownMaterial?.trim() && ownMaterial.trim() !== '/') return ownMaterial
      const source = sections.filter(item => item.title === '面料类').flatMap(item => item.lines)
        .find(item => item.unit === '米' && (line.fabric_source_line_id
          ? item.id === line.fabric_source_line_id
          : Boolean(line.fabric_source_client_key && !item.id && item.client_key === line.fabric_source_client_key)))
      if (source?.material?.trim() && source.material.trim() !== '/') return source.material
      return text(ownMaterial)
    }
  }
  return text(line[key as keyof BomPreviewLine])
}
