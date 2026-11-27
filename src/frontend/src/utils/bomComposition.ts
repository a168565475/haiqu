import type { BomLineInput, BomSectionInput } from '@/types/bom'
import type { MaterialCatalog } from '@/types/materialCatalog'

export function isPartChild(piece: BomLineInput, part: BomLineInput): boolean {
  return piece.component_kind === 'CUT_PIECE' && (part.id
    ? piece.parent_part_id === part.id
    : Boolean(part.client_key && piece.parent_part_client_key === part.client_key))
}

export function componentParent(line: BomLineInput, lines: BomLineInput[]): BomLineInput | undefined {
  return line.component_kind === 'SEWN_PART' ? line
    : lines.find(part => part.component_kind === 'SEWN_PART' && isPartChild(line, part))
}

export function componentDemand(line: BomLineInput, lines: BomLineInput[], orderQuantity: string): string {
  const part = componentParent(line, lines)
  const quantity = Number(orderQuantity) * Number(part?.parts_per_product)
    * (line.component_kind === 'CUT_PIECE' ? Number(line.pieces_per_part) : 1)
  return quantity > 0 && Number.isSafeInteger(quantity) ? String(quantity) : '—'
}

export function componentKey(line: BomLineInput): string { return line.id || line.client_key || '' }

export function setComponentParent(line: BomLineInput, key: string, lines: BomLineInput[]) {
  const part = lines.find(item => item.component_kind === 'SEWN_PART' && componentKey(item) === key)
  line.parent_part_id = part?.id || null
  line.parent_part_client_key = part && !part.id ? part.client_key || null : null
}

export function componentReferenceSelection(line: BomLineInput, catalogId = line.material_catalog_id) {
  if (!catalogId || line.material_catalog_id !== catalogId) return undefined
  const pending = line.material_selection
  if (pending?.processing_state === 'PROCESSED' && !pending.completed_craft && !pending.semi_kind) return pending
  return line.material_selection_snapshot?.selection_kind === 'BOM_COMPONENT_REFERENCE' ? line.material_selection_snapshot : undefined
}

export const COMPONENT_OWN_ATTRIBUTE_KEYS = ['size', 'specification', 'model', 'process']

export function componentOwnAttributes(attributes: Record<string, string> = {}): Record<string, string> {
  return Object.fromEntries(Object.entries(attributes).filter(([key]) => COMPONENT_OWN_ATTRIBUTE_KEYS.includes(key)))
}

export function applyComponentReferenceSelection(line: BomLineInput, catalog: MaterialCatalog, attributes: Record<string, string>, updateSpecification = false) {
  line.material_catalog_id = catalog.id
  line.part_name = catalog.name
  line.material_selection = {
    catalog_version: catalog.updated_at, scope: 'BASE', processing_state: 'PROCESSED',
    attributes: componentOwnAttributes(attributes), unit_name: line.unit,
  }
  // 部位可由所选尺寸带出；裁片独立尺寸及来源关联不属于品名属性，不能被覆盖。
  if (line.component_kind === 'SEWN_PART' && updateSpecification) {
    const specification = attributes.size || attributes.specification || attributes.model
    if (specification) line.specification = specification
  }
}

export function setComponentUnit(line: BomLineInput, unit: string) {
  line.unit = unit
  const selected = line.material_selection || line.material_selection_snapshot
  if (line.material_catalog_id && selected) {
    const reference = componentReferenceSelection(line)
    line.material_selection = { catalog_version: selected.catalog_version, scope: 'BASE', processing_state: 'PROCESSED',
      attributes: { ...reference?.attributes }, unit_name: line.unit,
      ...(reference?.product_color_id ? { product_color_id: reference.product_color_id, color_card: reference.color_card,
        color_code: reference.color_code, color_name: reference.color_name } : {}) }
  }
}

export function changeComponentKind(line: BomLineInput, kind: 'SEWN_PART' | 'CUT_PIECE') {
  const previousKind = line.component_kind
  line.component_kind = kind
  if (kind === 'SEWN_PART') {
    line.parent_part_id = line.parent_part_client_key = null
    line.pieces_per_part = null
    line.parts_per_product = line.parts_per_product || 1
    setComponentUnit(line, !line.unit || line.unit === '片' ? '套' : line.unit)
  } else {
    line.parts_per_product = null
    line.pieces_per_part = line.pieces_per_part || 1
    setComponentUnit(line, !line.unit || (previousKind === 'SEWN_PART' && line.unit === '套') ? '片' : line.unit)
  }
  // 只有明确切换类型时清理旧套口径及原料直绑；图片、备注、档案属性和独立尺寸保留。
  line.cutting_pieces_per_set = line.cutting_sets_per_product = null
  line.fabric_meters_per_piece = line.fabric_meters_per_set = null
  line.pending_raw_material = undefined
  for (const key of Object.keys(line)) {
    if (key.startsWith('source_') && key.endsWith('_id')) (line as unknown as Record<string, unknown>)[key] = null
  }
  line.unit_consumption = line.total_consumption = line.total_purchase_quantity = line.cut_piece_quantity = ''
}

export function componentSource(line: BomLineInput, sources: BomLineInput[]) {
  return sources.find(source => componentKey(source) === (line.fabric_source_line_id || line.fabric_source_client_key))
}

type FabricSourceField = 'material' | 'specification' | 'width' | 'color' | 'color_code'

export function componentMaterialValue(line: BomLineInput, sources: BomLineInput[], field: FabricSourceField) {
  const source = line.component_kind ? componentSource(line, sources) : line
  const selection = source?.material_selection || source?.material_selection_snapshot
  const attrs = selection?.attributes
  if (field === 'material') return attrs?.material || source?.material || '—'
  if (field === 'specification') return attrs?.fabric_spec || attrs?.specification || source?.specification || '—'
  if (field === 'width') return attrs?.width || source?.fabric_width || '—'
  if (field === 'color_code') return selection?.color_code || source?.fabric_color_code || '—'
  return attrs?.color || selection?.color_name || source?.fabric_color_name || source?.accessory_color || '—'
}

export function componentLineError(line: BomLineInput, section: BomSectionInput, sections: BomSectionInput[], requireChildren = true, requireCatalog = true): string {
  if (!line.part_name.trim()) return '请填写部位或裁片名称。'
  if (requireCatalog && !line.material_catalog_id) return '请选择已有的部位或裁片档案。'
  const source = sections.filter(item => ['面料类', '辅料类'].includes(item.title)).flatMap(item => item.lines)
    .find(item => line.fabric_source_line_id ? item.id === line.fabric_source_line_id
      : Boolean(line.fabric_source_client_key && item.client_key === line.fabric_source_client_key))
  if (line.component_kind === 'SEWN_PART') {
    if (!line.unit.trim()) return '请选择部位单位。'
    if (!Number.isSafeInteger(Number(line.parts_per_product)) || Number(line.parts_per_product) <= 0) return '每产品部位数量必须为正整数。'
    if (requireChildren && !section.lines.some(piece => isPartChild(piece, line))) return '每个部位至少添加一种裁片。'
    if ((line.fabric_source_line_id || line.fabric_source_client_key) && !source) return '请选择当前 BOM 内的归属面布。'
    return ''
  }
  if (!componentParent(line, section.lines)) return '请选择当前 BOM 内的所属部位。'
  if (!Number.isSafeInteger(Number(line.pieces_per_part)) || Number(line.pieces_per_part) <= 0) return '每部位裁片数量必须为正整数。'
  if (!line.unit.trim()) return '请选择裁片单位。'
  if (!line.specification.trim() || ['/', '—', '-', '--'].includes(line.specification.trim())) return '请填写裁片的实际尺寸或规格。'
  return source ? '' : '请选择当前 BOM 内的布料或棉等裁剪原料。'
}
