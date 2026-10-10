import type { PageMeta } from './referenceData'

export type ProductScale = 'CUSTOM' | 'REGULAR'
export type ProductStatus = 'ACTIVE' | 'INACTIVE'
export type ProductOrderingField = 'product_number' | 'product_code' | 'product_name' | 'updated_at'
export type ProductOrdering = ProductOrderingField | `-${ProductOrderingField}`

export interface ProductInformation {
  id: string
  product_number: string
  product_type: 'FINISHED'
  product_type_label: string
  product_code: string
  category: string
  category_name: string
  product_name: string
  specification: string
  unit: string
  unit_code: string
  unit_name: string
  product_item: string
  item_number: string
  item_category_id: string
  item_category_name: string
  category_item_mismatch: boolean
  warehouse_number: string
  warehouse_name: string
  scale: ProductScale
  status: ProductStatus
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface ProductInformationInput {
  product_number: string
  product_code: string
  category: string
  product_name: string
  specification: string
  unit: string
  product_item: string
  warehouse_number: string
  warehouse_name: string
  scale: ProductScale
  status: ProductStatus
}

export interface ProductInformationQuery {
  page?: number
  page_size?: number
  q?: string
  category_id?: string
  scale?: ProductScale | ''
  status?: ProductStatus | ''
  ordering?: ProductOrdering
}

export interface ProductCategoryOption {
  id: string
  category_name: string
}

export interface ProductionUnitOption {
  id: string
  unit_code: string
  unit_name: string
}

export interface ProductItemOption {
  id: string
  item_number: string
  category_id: string
  category_name: string
}

export interface ProductOptions {
  categories: ProductCategoryOption[]
  units: ProductionUnitOption[]
  items: ProductItemOption[]
}

export interface PaginatedProducts {
  data: ProductInformation[]
  meta: PageMeta
}

export interface VersionedProduct {
  data: ProductInformation
  etag: string
}
