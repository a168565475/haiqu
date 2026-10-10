import type { PageMeta, ReferenceStatus } from './referenceData'

export type ProductItemType = 'FINISHED' | 'SEMI_FINISHED' | 'MATERIAL'

export type ProductionDataResource =
  | 'product-categories'
  | 'production-units'
  | 'product-colors'
  | 'product-items'
  | 'fabric-materials'
  | 'fabric-specifications'
  | 'fabric-widths'
  | 'tube-product-names'
  | 'tube-thicknesses'
  | 'tube-diameters'
  | 'tube-materials'
  | 'tube-shapes'
  | 'tube-coating-colors'
  | 'accessory-product-names'
  | 'accessory-specifications'
  | 'accessory-colors'
  | 'accessory-materials'

export interface ProductionRecordBase {
  id: string
  status: ReferenceStatus
  sort_order: number
  description: string
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface ProductCategory extends ProductionRecordBase {
  item_type: ProductItemType
  item_type_label: string
  category_name: string
  reference_count: number
}

export interface ProductionUnit extends ProductionRecordBase {
  unit_code: string
  unit_name: string
}

export interface ProductColor extends ProductionRecordBase {
  color_card: string
  color_code: string
  color_name: string
  image_url: string | null
  has_image: boolean
}

export interface ProductItem extends ProductionRecordBase {
  item_number: string
  category: string
  category_name: string
  item_type: ProductItemType
  item_type_label: string
  legacy_data_id: string | null
}

export interface FabricMaterial extends ProductionRecordBase {
  material_name: string
  inventory_raw_material: string | null
  inventory_material_number: string | null
  inventory_material_name: string | null
  inventory_material_unit: string | null
}

export interface FabricSpecification extends ProductionRecordBase {
  specification_name: string
}

export interface FabricWidth extends ProductionRecordBase {
  width_value: string
}

export interface TubeProductName extends ProductionRecordBase {
  product_name: string
  pinyin_search: string
}

export interface TubeThickness extends ProductionRecordBase {
  thickness_value: string
}

export interface TubeDiameter extends ProductionRecordBase {
  diameter_value: string
}

export interface TubeMaterial extends ProductionRecordBase {
  material_name: string
  pinyin_search: string
}

export interface TubeShape extends ProductionRecordBase {
  shape_name: string
  pinyin_search: string
}

export interface TubeCoatingColor extends ProductionRecordBase {
  color_name: string
}

export interface AccessoryProductName extends ProductionRecordBase {
  product_name: string
  unit_name: string
}

export interface AccessorySpecification extends ProductionRecordBase {
  product_name: string
  product_name_label: string
  unit_name: string
  specification_value: string
  weight: string
}

export interface AccessoryColor extends ProductionRecordBase {
  product_name: string
  product_name_label: string
  unit_name: string
  color_name: string
}

export interface AccessoryMaterial extends ProductionRecordBase {
  material_name: string
  inventory_raw_material: string | null
  inventory_material_number: string | null
  inventory_material_name: string | null
  inventory_material_unit: string | null
}

export type ProductionDataRecord =
  | ProductCategory
  | ProductionUnit
  | ProductColor
  | ProductItem
  | FabricMaterial
  | FabricSpecification
  | FabricWidth
  | TubeProductName
  | TubeThickness
  | TubeDiameter
  | TubeMaterial
  | TubeShape
  | TubeCoatingColor
  | AccessoryProductName
  | AccessorySpecification
  | AccessoryColor
  | AccessoryMaterial
export type ProductionDataInput = Record<string, unknown>

export interface ProductionDataSummary {
  category_counts: Record<string, number>
}

export interface ProductionDataQuery {
  page?: number
  page_size?: number
  q?: string
  status?: ReferenceStatus | ''
  item_type?: ProductItemType | ''
  category_id?: string
  product_name_id?: string
  has_image?: boolean
}

export interface PaginatedProductionData<T> {
  data: T[]
  meta: PageMeta
}

export interface VersionedProductionData<T> {
  data: T
  etag: string
}
