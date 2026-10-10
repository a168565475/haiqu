import type { PageMeta } from './referenceData'

export type RawMaterialItemType = 'MATERIAL' | 'SEMI_FINISHED'
export type RawMaterialBoxShape = 'HALF_COVER' | 'FULL_COVER' | 'LID_AND_BASE' | 'DISPLAY_BOX' | 'OTHER'
export type RawMaterialOrderingField =
  | 'material_number'
  | 'item_type'
  | 'category_name'
  | 'material_name'
  | 'specification'
  | 'unit_name'
  | 'color_name'
  | 'warehouse'
  | 'is_packaging_auxiliary'
  | 'box_shape'
  | 'updated_at'
export type RawMaterialOrdering = RawMaterialOrderingField | `-${RawMaterialOrderingField}`

export interface RawMaterialInformation {
  id: string
  material_number: string
  item_type: RawMaterialItemType
  item_type_label: string
  category: string
  category_name: string
  material_name: string
  specification: string
  unit: string
  unit_code: string
  unit_name: string
  color: string | null
  color_name: string
  color_label: string
  has_legacy_color: boolean
  material: string
  is_packaging_auxiliary: boolean
  box_shape: RawMaterialBoxShape | ''
  notes: string
  warehouse_number: string
  warehouse_name: string
  diameter: string
  length: string
  width: string
  thickness: string
  model_number: string
  weight_kg: string
  flow_unit: string
  number_value: string
  source_unique_check: string
  source_row_number: number | null
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface RawMaterialInput {
  material_number: string
  item_type: RawMaterialItemType
  category: string
  material_name: string
  specification: string
  unit: string
  color?: string | null
  material: string
  is_packaging_auxiliary: boolean
  box_shape: RawMaterialBoxShape | ''
  notes: string
  warehouse_number: string
  warehouse_name: string
}

export interface RawMaterialQuery {
  page?: number
  page_size?: number
  q?: string
  item_type?: RawMaterialItemType | ''
  category_id?: string
  warehouse_number?: string
  ordering?: RawMaterialOrdering
}

export interface RawMaterialCategoryOption {
  id: string
  item_type: RawMaterialItemType
  category_name: string
}

export interface RawMaterialUnitOption {
  id: string
  unit_code: string
  unit_name: string
}

export interface RawMaterialColorOption {
  id: string
  color_card: string
  color_code: string
  color_name: string
  label: string
}

export interface RawMaterialWarehouseOption {
  warehouse_number: string
  warehouse_name: string
}

export interface RawMaterialValueOption<T extends string = string> {
  value: T
  label: string
}

export interface RawMaterialOptions {
  item_types: RawMaterialValueOption<RawMaterialItemType>[]
  categories: RawMaterialCategoryOption[]
  units: RawMaterialUnitOption[]
  colors: RawMaterialColorOption[]
  warehouses: RawMaterialWarehouseOption[]
  box_shapes: RawMaterialValueOption<RawMaterialBoxShape>[]
}

export interface PaginatedRawMaterials {
  data: RawMaterialInformation[]
  meta: PageMeta
}

export interface VersionedRawMaterial {
  data: RawMaterialInformation
  etag: string
}
