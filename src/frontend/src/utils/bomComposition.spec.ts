import { describe, expect, it } from 'vitest'
import type { BomLineInput, BomSectionInput } from '@/types/bom'
import type { MaterialCatalog } from '@/types/materialCatalog'
import { blankLine, editableLine } from '@/views/boms/bomEditorHelpers'
import { applyComponentReferenceSelection, changeComponentKind, componentDemand, componentLineError, componentMaterialValue, componentOwnAttributes, isPartChild, setComponentUnit } from './bomComposition'
import { bomPreviewCell, bomPreviewColumns } from './bomPreview'

function fixture() {
  const part: BomLineInput = { ...blankLine('个'), material_catalog_id: 'part-catalog', component_kind: 'SEWN_PART', parts_per_product: 2, part_name: '外袋' }
  const source = { ...blankLine('米'), part_name: '棉', specification: '厚 5mm' }
  const piece: BomLineInput = { ...blankLine('片'), material_catalog_id: 'piece-catalog', component_kind: 'CUT_PIECE', parent_part_client_key: part.client_key,
    pieces_per_part: 3, part_name: '衬棉', specification: '20×30cm', fabric_source_client_key: source.client_key }
  const cutting: BomSectionInput = { title: '裁剪明细', section_type: 'FABRIC', lines: [part, piece] }
  const auxiliary: BomSectionInput = { title: '辅料类', section_type: 'FABRIC', lines: [source] }
  return { part, piece, source, cutting, sections: [cutting, auxiliary] }
}
describe('BOM 动态部位与裁片', () => {
  const catalog: MaterialCatalog = { id: 'reference', name: '椅面', updated_at: 'v2', category_key: 'FABRIC_SEMI', template_key: 'FABRIC_SEMI',
    spray_enabled: false, base_warehouse_id: null, semi_warehouse_id: null, values: [], units: [] }
  it.each([
    [{ size: '50×60cm', specification: '成品规格', model: 'M1' }, '50×60cm'],
    [{ specification: '成品规格', model: 'M1' }, '成品规格'],
    [{ model: 'M1' }, 'M1'],
    [{ fabric_spec: '600D', width: '150cm' }, '手填成品尺寸'],
  ])('部位只按 size、specification、model 带出尺寸，不把原料规格或门幅当尺寸', (attributes, expected) => {
    const { part } = fixture()
    part.specification = '手填成品尺寸'
    applyComponentReferenceSelection(part, catalog, attributes as Record<string, string>, true)
    expect(part.specification).toBe(expected)
    expect(part.material_selection).toMatchObject({ catalog_version: 'v2', scope: 'BASE', processing_state: 'PROCESSED', attributes: componentOwnAttributes(attributes as Record<string, string>), unit_name: '个' })
    applyComponentReferenceSelection(part, catalog, { size: '属性尺寸', color: '蓝色' })
    expect(part.specification).toBe(expected)
  })
  it('修改裁片属性只写品名引用，不覆盖尺寸、原料、父关系、片数和备注图片', () => {
    const { piece } = fixture()
    piece.unit = '套'
    piece.notes = '原备注'
    piece.images = [{ id: 'image' }] as never
    const before = structuredClone(piece)
    applyComponentReferenceSelection(piece, catalog, { size: '属性尺寸', material: '涤纶' }, true)
    expect(piece).toMatchObject({ specification: before.specification, parent_part_client_key: before.parent_part_client_key,
      fabric_source_client_key: before.fabric_source_client_key, pieces_per_part: before.pieces_per_part, notes: before.notes, images: before.images, unit: '套' })
    expect(piece.material_selection?.unit_name).toBe('套')
    expect(piece.material_selection?.completed_craft).toBeUndefined()
    expect(piece.material_selection?.semi_kind).toBeUndefined()
    expect(piece.material_selection?.attributes).toEqual({ size: '属性尺寸' })
  })
  it('部位直接读取已选归属面布，不借用子裁片来源或旧自身布料属性', () => {
    const { part, piece, source, cutting, sections } = fixture()
    part.material = '错误部位材质'
    part.material_selection = { catalog_version: 'v1', scope: 'BASE', processing_state: 'PROCESSED', attributes: { material: '错误材质', color: '错误颜色' } }
    const blueSource = { ...blankLine('米'), id: 'blue-source', part_name: '蓝布', material: '涤纶', specification: '600D', fabric_color_name: '蓝色', fabric_color_code: 'B1', fabric_width: '150cm' }
    expect(componentMaterialValue(part, [source, blueSource], 'material')).toBe('—')
    expect(componentLineError(part, cutting, sections)).toBe('')
    part.fabric_source_line_id = blueSource.id
    expect(componentMaterialValue(part, [source, blueSource], 'material')).toBe('涤纶')
    expect(componentMaterialValue(part, [source, blueSource], 'color')).toBe('蓝色')
    expect(componentMaterialValue(part, [source, blueSource], 'specification')).toBe('600D')
    expect(piece.fabric_source_client_key).toBe(source.client_key)
    expect(componentLineError(part, cutting, sections)).toContain('归属面布')
    sections[1]!.lines.push(blueSource)
    expect(componentLineError(part, cutting, sections)).toBe('')
    expect(part.material_selection.attributes).toEqual({ material: '错误材质', color: '错误颜色' })
  })
  it('明确切换类型只清理不适用关联和旧耗料口径，保留档案、尺寸、属性及备注', () => {
    const { piece, source } = fixture()
    piece.notes = '保留备注'
    piece.material_selection = { catalog_version: 'v1', scope: 'BASE', processing_state: 'PROCESSED', attributes: { material: '棉' }, unit_name: '片', semi_kind: 'CUTTING', completed_craft: { id: 'cut', code: 'CUTTING', craft_type: 'INTERNAL' } }
    changeComponentKind(piece, 'SEWN_PART')
    expect(piece.unit).toBe('片')
    expect(piece).toMatchObject({ material_catalog_id: 'piece-catalog', specification: '20×30cm', notes: '保留备注', pieces_per_part: null, parts_per_product: 1, parent_part_client_key: null, fabric_source_client_key: source.client_key })
    setComponentUnit(piece, '个')
    expect(piece.material_selection).toEqual({ catalog_version: 'v1', scope: 'BASE', processing_state: 'PROCESSED', attributes: {}, unit_name: '个' })
    changeComponentKind(piece, 'CUT_PIECE')
    expect(piece.fabric_source_client_key).toBe(source.client_key)
    expect(piece.unit).toBe('个')
    expect(piece.material_selection?.unit_name).toBe('个')
  })
  it('新裁片仅空单位默认片，修改单位同步引用快照且用量不做换算', () => {
    const fresh = blankLine()
    changeComponentKind(fresh, 'CUT_PIECE')
    expect(fresh.unit).toBe('片')
    const { piece, cutting } = fixture()
    piece.material_selection_snapshot = { selection_kind: 'BOM_COMPONENT_REFERENCE', catalog_id: piece.material_catalog_id,
      catalog_version: 'v1', scope: 'BASE', processing_state: 'PROCESSED', attributes: { size: '20×30cm' }, unit_name: '片' } as never
    const snapshot = structuredClone(piece.material_selection_snapshot)
    setComponentUnit(piece, '套')
    expect(piece.unit).toBe('套')
    expect(piece.material_selection).toMatchObject({ attributes: { size: '20×30cm' }, unit_name: '套' })
    expect(piece.material_selection_snapshot).toEqual(snapshot)
    expect(piece.pieces_per_part).toBe(3)
    expect(componentDemand(piece, cutting.lines, '10')).toBe('60')
  })
  it('引用原料属性显示但不覆盖裁片独立尺寸，新增父可先应用再补子片', () => {
    const { part, piece, source, cutting, sections } = fixture()
    expect(componentMaterialValue(piece, [source], 'specification')).toBe('厚 5mm')
    expect(piece.specification).toBe('20×30cm')
    cutting.lines = [part]
    expect(componentLineError(part, cutting, sections, false)).toBe('')
    expect(componentLineError(part, cutting, sections)).toContain('至少添加')
    part.material_catalog_id = null
    expect(componentLineError(part, cutting, sections, false)).toContain('已有的部位或裁片档案')
  })
  it('按父部位用量和子片数组合计算片数，部位保留自己的单位', () => {
    const { part, piece, cutting } = fixture()
    expect(componentDemand(part, cutting.lines, '10')).toBe('20')
    expect(componentDemand(piece, cutting.lines, '10')).toBe('60')
    part.parts_per_product = 1; piece.pieces_per_part = 5
    expect(componentDemand(piece, cutting.lines, '10')).toBe('50')
  })
  it('同名部位仍以身份关联，不按名称猜测父子', () => {
    const { part, piece } = fixture()
    expect(isPartChild(piece, part)).toBe(true)
    expect(isPartChild(piece, { ...part, client_key: 'other' })).toBe(false)
  })
  it('棉原料可引用本单辅料且尺寸独立', () => {
    const { part, piece, cutting, sections } = fixture()
    expect(componentLineError(part, cutting, sections)).toBe('')
    expect(componentLineError(piece, cutting, sections)).toBe('')
    expect(piece.specification).toBe('20×30cm')
    piece.fabric_source_client_key = 'missing'
    expect(componentLineError(piece, cutting, sections)).toContain('请选择当前 BOM')
  })
  it('裁片可选套但用量仍需正整数，缺单位或父被删除不能悄悄保存', () => {
    const { piece, cutting, sections } = fixture()
    piece.pieces_per_part = 0
    expect(componentLineError(piece, cutting, sections)).toContain('正整数')
    piece.pieces_per_part = 1; piece.unit = '套'
    expect(componentLineError(piece, cutting, sections)).toBe('')
    piece.pieces_per_part = 1.5
    expect(componentLineError(piece, cutting, sections)).toContain('正整数')
    piece.pieces_per_part = 1; piece.unit = ''
    expect(componentLineError(piece, cutting, sections)).toContain('请选择裁片单位')
    piece.unit = '片'; cutting.lines.shift()
    expect(componentLineError(piece, cutting, sections)).toContain('所属部位')
  })
  it('预览和打印显示父部位、裁片来源、数量与各自单位', () => {
    const { part, piece, cutting, sections } = fixture()
    expect(bomPreviewColumns(cutting).map(item => item.label)).toContain('每部位用量')
    expect(bomPreviewCell(piece, 'parent_part_name', cutting, '10', sections)).toBe('外袋')
    expect(bomPreviewCell(piece, 'component_demand', cutting, '10', sections)).toBe('60')
    expect(bomPreviewCell(piece, 'composition_source', cutting, '10', sections)).toBe('棉 厚 5mm')
    piece.unit = '套'
    expect(bomPreviewCell(piece, 'unit', cutting, '10', sections)).toBe('套')
    expect(bomPreviewCell(part, 'unit', cutting, '10', sections)).toBe('个')
  })
  it('重开编辑时保留服务端父子关系及独立需求参数', () => {
    const { piece } = fixture()
    const editable = editableLine({ ...piece, id: 'piece', parent_part_id: 'part', pieces_per_part: 3 } as never)
    expect(editable).toMatchObject({ component_kind: 'CUT_PIECE', parent_part_id: 'part', pieces_per_part: 3, unit: '片' })
  })
})
