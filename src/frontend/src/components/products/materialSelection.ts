import type { BomLineInput } from '@/types/bom'
import type { MaterialCatalog, MaterialScope, MaterialSelectionInput, PublicMaterialOptions } from '@/types/materialCatalog'

export const bomCatalogCategories: Record<string, string> = {
  管材类: 'TUBE', 五金件: 'HARDWARE', 塑料件类: 'PLASTIC', 辅料类: 'AUXILIARY',
  面料类: 'FABRIC', 包材类: 'PACKAGING', 裁剪明细: 'FABRIC_SEMI',
}

export function catalogOwnOptions(item: MaterialCatalog, scope: MaterialScope): PublicMaterialOptions {
  return {
    category_key: item.category_key, template_key: item.template_key, scope, fields: [],
    values: item.values.filter(option => option.scope === scope && option.selectable !== false),
    units: item.units.filter(option => option.scope === scope && option.selectable !== false).map(unit => ({ id: unit.unit_id, unit_name: unit.unit_name })),
  }
}

export function inboundCatalogOptions(catalog: MaterialCatalog, shared: PublicMaterialOptions): PublicMaterialOptions {
  const own = catalogOwnOptions(catalog, shared.scope)
  const shapes = new Map(own.values.filter(row => row.field_key === 'shape').map(row => [row.value, row.id]))
  const sharedParents = new Map(shared.values.filter(row => row.field_key === 'shape').map(row => [row.id, shapes.get(row.value) || row.id]))
  // 同名截面在两份数据中有各自的 ID，合并前先对齐其规格的父级。
  const sharedValues = shared.values.map(row => row.parent_id && sharedParents.has(row.parent_id)
    ? { ...row, parent_id: sharedParents.get(row.parent_id)! } : row)
  const identities = new Set<string>()
  const values = [...own.values, ...sharedValues].filter(row => {
    const key = JSON.stringify([row.field_key, row.parent_id, row.value, row.color_card || '', row.color_code || ''])
    if (identities.has(key)) return false
    identities.add(key)
    return true
  })
  const names = new Set(own.units.map(unit => unit.unit_name))
  return { ...shared, values, units: [...own.units, ...shared.units.filter(unit => !names.has(unit.unit_name))] }
}

export function applyMaterialSelection(line: BomLineInput, catalog: MaterialCatalog, selection: MaterialSelectionInput) {
  const attrs = selection.attributes
  line.material_catalog_id = catalog.id
  line.material_selection = structuredClone(selection)
  line.pending_raw_material = undefined
  for (const key of Object.keys(line)) {
    if (key.startsWith('source_') && key.endsWith('_id')) (line as unknown as Record<string, unknown>)[key] = null
  }
  line.part_name = catalog.name
  line.material = attrs.material || ''
  line.specification = ['fabric_spec', 'specification', 'section_size', 'size', 'model', 'width'].map(key => attrs[key]).filter(Boolean).join(' / ')
  line.raw_material = ''
  line.unit = selection.unit_id ? catalog.units.find(unit => unit.unit_id === selection.unit_id)?.unit_name || line.unit : selection.unit_name || ''
  line.tube_shape = attrs.shape || ''
  line.tube_diameter = attrs.section_size || ''
  line.tube_thickness = attrs.thickness || ''
  line.fabric_width = attrs.width || ''
  line.hardware_flow_unit = attrs.flow_unit || ''
  line.fabric_color_card = selection.color_card || ''
  line.fabric_color_code = selection.color_code || ''
  line.fabric_color_name = line.hardware_color = line.plastic_color = line.accessory_color = line.packaging_color = line.cutting_color = attrs.color || ''
}
