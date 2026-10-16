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
export const productCatalogFields: { key: keyof ProductCatalogFields; label: string; maxLength: number }[] = [
  { key: 'product_code', label: '产品编码', maxLength: 100 },
  { key: 'item_number', label: '货号', maxLength: 100 },
  { key: 'specification', label: '规格', maxLength: 300 },
  { key: 'unit', label: '单位', maxLength: 80 },
  { key: 'scale', label: '常规/定制', maxLength: 100 },
]
