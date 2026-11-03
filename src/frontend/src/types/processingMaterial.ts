import type { MaterialSelectionSnapshot } from './materialCatalog'

export interface ProcessingMaterialPair {
  input_material_catalog_id?: string | null
  output_material_catalog_id?: string | null
  input_material_selection_snapshot?: MaterialSelectionSnapshot | Record<string, never> | null
  output_material_selection_snapshot?: MaterialSelectionSnapshot | Record<string, never> | null
}
