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
}
export interface MaterialCatalogSummary {
  id: string
  category_key: string
  template_key: string
  name: string
  spray_enabled: boolean
  updated_at: string
}
export interface MaterialAttributeValue {
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
  values: MaterialAttributeValue[]
  units: MaterialAllowedUnit[]
}
export interface VersionedMaterialCatalog { data: MaterialCatalog; etag: string }
export interface MaterialCatalogQuery { category?: string; q?: string; page?: number; page_size?: number }
export interface MaterialCatalogList {
  data: MaterialCatalogSummary[]
  meta: { page: number; page_size: number; total: number; total_pages: number }
}
export interface MaterialCatalogInput { name: string; category_key: string; template_key: string }
export interface MaterialAttributeInput { scope: MaterialScope; field_key: string; value: string; parent_id?: string | null }
export interface MaterialUnitInput { scope: MaterialScope; unit_id: string }
