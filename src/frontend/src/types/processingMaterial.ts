import type { MaterialSelectionSnapshot } from './materialCatalog'

export interface ComponentSourceMaterial {
  source_bom_line_id: string
  name: string
  material: string
  color: string
  color_code: string
  fabric_spec: string
  width: string
  unit: string
}

export interface ProcessingMaterialPair {
  component_source_materials?: ComponentSourceMaterial[]
  component_material_selection_snapshot?: MaterialSelectionSnapshot | Record<string, never> | null
  input_material_catalog_id?: string | null
  output_material_catalog_id?: string | null
  input_material_selection_snapshot?: MaterialSelectionSnapshot | Record<string, never> | null
  output_material_selection_snapshot?: MaterialSelectionSnapshot | Record<string, never> | null
}
