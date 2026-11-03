export interface ProductCatalogName {
  id: string
  category_id: string
  category_name: string
  name: string
  product_count: number
  updated_at: string
}
export interface ProductCatalogFields {
  product_code: string
  item_number: string
  specification: string
  unit: string
  scale: string
}
export interface ProductCatalog extends ProductCatalogFields {
  id: string
  name_id: string
  name: string
  category_id: string
  category_name: string
  colors: { id: string; value: string }[]
  materials?: string[]
  thicknesses?: string[]
  updated_at: string
  created_at?: string
  source?: null | { filename: string; sha256: string; sheet: string; row: number; raw_fields: Record<string, unknown> }
}
export interface ProductCatalogOptions {
  categories: { id: string; name: string; name_count: number }[]
  units: string[]
  scales: string[]
}
export interface ProductCatalogQuery { name_id?: string; category_id?: string; q?: string; page?: number; page_size?: number }
export interface ProductCatalogList {
  data: ProductCatalog[]
  meta: { page: number; page_size: number; total: number; total_pages: number }
}
export interface VersionedProductCatalog { data: ProductCatalog; etag: string }
export interface VersionedProductCatalogName { data: ProductCatalogName; etag: string }
export interface ProductCatalogInput extends ProductCatalogFields { name_id: string }
export interface ProductCatalogNameInput { category_id: string; name: string }
export interface ProductCatalogEditorRow extends ProductCatalogFields {
  id?: string
  colors: string[]
  materials: string[]
  thicknesses: string[]
}
export interface ProductCatalogDraftRow extends ProductCatalogEditorRow { key: string }
export interface ProductCatalogEditor { name: ProductCatalogName; products: ProductCatalog[] }
export interface VersionedProductCatalogEditor { data: ProductCatalogEditor; etag: string }
export interface ProductCatalogEditorInput {
  name: string
  products: ProductCatalogEditorRow[]
  delete_product_ids: string[]
}
export interface ProductCatalogEditorCreateInput {
  category_id: string
  name: string
  products: ProductCatalogEditorRow[]
}
export type ProductEntryField = 'category_name' | 'name' | 'item_number' | 'specification' | 'product_code' | 'unit_name' | 'color_name' | 'material'
export interface ProductEntryDraft {
  category_id: string | null
  category_name: string
  name_id: string | null
  name: string
  item_number: string
  specification: string
  product_code: string
  unit_id: string | null
  unit_name: string
  color_id: string | null
  color_name: string
  material: string
  sources: Record<ProductEntryField, 'selected' | 'typed'>
}
export interface ProductSelectionInput {
  catalog_version?: string
  color_id?: string | null
  material?: string
  thickness?: string
  draft?: ProductEntryDraft
}
export interface ProductSelectionSnapshot {
  version: number
  catalog_id: string | null
  catalog_version: string
  name_id: string | null
  name: string
  category_id: string | null
  category_name: string
  product_code: string
  item_number: string
  specification: string
  scale: string
  unit_id: string | null
  unit_name: string
  unit_code: string
  color_id: string | null
  color_name: string
  material: string
  thickness: string
  entry_state?: 'draft' | 'confirmed'
  entry_draft?: ProductEntryDraft
}
export interface ProductCatalogSelectionOption extends ProductCatalog {
  catalog_version: string
  unit_id: string | null
  unit_code: string
}
export interface ProductCatalogSelectionOptions {
  categories: { id: string; name: string }[]
  names: { id: string; category_id: string; name: string }[]
  products: ProductCatalogSelectionOption[]
  units?: { id: string; unit_name: string; unit_code: string }[]
}
export const productCatalogFields: { key: keyof ProductCatalogFields; label: string; maxLength: number }[] = [
  { key: 'product_code', label: '产品编码', maxLength: 100 },
  { key: 'item_number', label: '货号', maxLength: 100 },
  { key: 'specification', label: '规格', maxLength: 300 },
  { key: 'unit', label: '单位', maxLength: 80 },
  { key: 'scale', label: '常规/定制', maxLength: 100 },
]
