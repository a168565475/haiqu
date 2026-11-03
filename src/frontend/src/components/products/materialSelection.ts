import type { BomLineInput } from '@/types/bom'
import type { MaterialCatalog, MaterialSelectionInput } from '@/types/materialCatalog'

export const bomCatalogCategories: Record<string, string> = {
  管材类: 'TUBE', 五金件: 'HARDWARE', 塑料件类: 'PLASTIC', 辅料类: 'AUXILIARY',
  面料类: 'FABRIC', 包材类: 'PACKAGING', 裁剪明细: 'FABRIC_SEMI',
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
