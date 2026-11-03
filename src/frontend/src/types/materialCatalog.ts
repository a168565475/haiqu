import type { PageMeta, ReferenceStatus } from './referenceData'

export interface MaterialColorSelection {
  product_color_id?: string | null
  color_card?: string
  color_code?: string
  color_name?: string
}

export interface MaterialSelectionInput extends MaterialColorSelection {
  catalog_version: string
  scope: MaterialScope
  processing_state: 'RAW' | 'PROCESSED'
  attributes: Record<string, string>
  unit_id?: string
  unit_name?: string
  completed_craft?: { id: string; craft_type: 'INTERNAL' | 'EXTERNAL'; code: string } | null
  semi_kind?: 'PIPE' | 'CUTTING' | 'HARDWARE' | null
}
export interface MaterialSelectionSnapshot extends MaterialSelectionInput {
  schema_version: 1
  catalog_id: string
  category_key: string
  template_key: string
  name: string
  unit_id: string
  unit_name: string
  processing_stage: string
  display_name: string
}

export type MaterialScope = 'BASE' | 'SPRAY'
export interface MaterialFieldDefinition {
  key: string
  label: string
  kind: 'text' | 'shape' | 'dimension' | 'unit'
}
export interface MaterialTemplateDefinition {
  key: string
  label: string
  supports_spray: boolean
  fields: MaterialFieldDefinition[]
}
export interface MaterialCategoryDefinition {
  key: string
  label: string
  templates: MaterialTemplateDefinition[]
}
export interface MaterialCatalogOptions {
  categories: MaterialCategoryDefinition[]
  spray_fields: MaterialFieldDefinition[]
  units: { id: string; unit_name: string }[]
  warehouses: { id: string; warehouse_number: string; warehouse_name: string; warehouse_type: string }[]
}
export interface PublicMaterialFieldDefinition extends MaterialFieldDefinition {
  source: string
  manage_url: string
}
export interface PublicMaterialTemplateDefinition extends Omit<MaterialTemplateDefinition, 'fields'> {
  fields: PublicMaterialFieldDefinition[]
}
export interface PublicMaterialFields {
  categories: (Omit<MaterialCategoryDefinition, 'templates'> & { templates: PublicMaterialTemplateDefinition[] })[]
  spray_fields: PublicMaterialFieldDefinition[]
}
export interface PublicMaterialOptionsQuery {
  category_key: string
  template_key: string
  scope: MaterialScope
}
export interface PublicMaterialOptions extends PublicMaterialOptionsQuery {
  values: MaterialAttributeValue[]
  units: { id: string; unit_name: string }[]
  fields: PublicMaterialFieldDefinition[]
}
export interface PublicTubeOptions {
  shapes: { id: string; shape_name: string }[]
  diameters: { id: string; diameter_value: string }[]
}
export type PublicMaterialResource = 'material-attribute-values' | 'tube-shape-dimensions'
interface PublicMaterialRecordBase {
  id: string
  status: ReferenceStatus
  sort_order: number
  description: string
  updated_at: string
  archived_at: string | null
}
export interface PublicMaterialValue extends PublicMaterialRecordBase, PublicMaterialOptionsQuery {
  field_key: string
  value: string
  source_kind?: 'SPECIFICATION' | 'PUBLIC'
  editable?: boolean
  source_count?: number
}
export interface PublicTubeShapeDimension extends PublicMaterialRecordBase {
  shape: string
  shape_name: string
  diameter: string
  diameter_value: string
}
export type PublicMaterialRecord = PublicMaterialValue | PublicTubeShapeDimension
export interface PublicMaterialRecordsQuery {
  category_key?: string
  template_key?: string
  scope?: MaterialScope
  field_key?: string
  shape?: string
  q?: string
  status?: ReferenceStatus
  page?: number
  page_size?: number
}
export interface PublicMaterialRecords<T extends PublicMaterialRecord = PublicMaterialRecord> { data: T[]; meta: PageMeta }
export interface VersionedPublicMaterialRecord<T extends PublicMaterialRecord = PublicMaterialRecord> { data: T; etag: string }
export type PublicMaterialRecordInput = (
  (PublicMaterialOptionsQuery & { field_key: string; value: string }) | { shape: string; diameter: string }
) & { description?: string; sort_order?: number }
export interface PublicMaterialRecordPatch { value?: string; description?: string; sort_order?: number }
export interface MaterialCatalogSummary {
  id: string
  category_key: string
  template_key: string
  name: string
  spray_enabled: boolean
  updated_at: string
}
export interface MaterialAttributeValue extends MaterialColorSelection {
  id: string
  scope: MaterialScope
  field_key: string
  value: string
  parent_id: string | null
}
export interface MaterialAllowedUnit {
  id: string
  scope: MaterialScope
  unit_id: string
  unit_name: string
}
export interface MaterialCatalog extends MaterialCatalogSummary {
  base_warehouse_id: string | null
  semi_warehouse_id: string | null
  values: MaterialAttributeValue[]
  units: MaterialAllowedUnit[]
}
export interface VersionedMaterialCatalog { data: MaterialCatalog; etag: string }
export interface MaterialCatalogQuery { category?: string; q?: string; page?: number; page_size?: number }
export interface MaterialCatalogList {
  data: MaterialCatalogSummary[]
  meta: { page: number; page_size: number; total: number; total_pages: number }
}
export interface MaterialCatalogDraft {
  name: string
  spray_enabled: boolean
  base_warehouse_id: string | null
  semi_warehouse_id: string | null
  values: MaterialAttributeValue[]
  units: { id: string; scope: MaterialScope; unit_name: string }[]
}
export interface MaterialCatalogInput extends Partial<Omit<MaterialCatalogDraft, 'name'>> {
  name: string
  category_key: string
  template_key: string
}
export interface MaterialAttributeInput { scope: MaterialScope; field_key: string; value: string; parent_id?: string | null }
export type MaterialUnitSelection = { unit_id: string; unit_name?: never } | { unit_name: string; unit_id?: never }
export type MaterialUnitInput = MaterialUnitSelection & { scope: MaterialScope }
export interface MaterialCatalogPatch { spray_enabled?: boolean; base_warehouse_id?: string | null; semi_warehouse_id?: string | null }
