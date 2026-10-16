import type { PageMeta } from './referenceData'
import type { RawMaterialInput } from './rawMaterial'

export type BomStatus = 'PENDING_CONFIRMATION' | 'VERIFIED'
export type BomCreationMethod = 'IMPORT' | 'COPY' | 'BLANK'
export type BomSectionType = 'PROFILE' | 'ACCESSORY' | 'FABRIC'

export interface BomLineImage {
  id: string
  file_id: string
  name: string
  content_type: string
  size_bytes: number
  content_url: string
  position: number
}

export interface BomDraftLineImage {
  id: string
  draft_key: string
  position: number
  name: string
  content_type: string
  size_bytes: number
  content_url: string
  expires_at: string
}

export interface BomSectionSummary {
  type: BomSectionType
  label: string
  count: number
}

export interface BomLine {
  cutting_material_original?: string | null
  cutting_pieces_per_set?: number | null
  fabric_meters_per_piece?: string | null
  cutting_sets_per_product?: number | null
  component_identity?: string
  cutting_length_mm?: number | null
  pieces_per_product?: number | null
  pieces_per_bar?: number | null
  raw_bar_length_m?: string | null
  suggested_bar_count?: number | null
  suggested_purchase_meters?: string | null
  fabric_source_line_id?: string | null
  fabric_meters_per_set?: string | null
  id: string
  line_number: number
  source_row_number: number | null
  source_serial: string
  category: string
  material: string
  part_name: string
  specification: string
  raw_material: string
  length_value: string
  unit_consumption: string
  total_consumption: string
  unit: string
  hardness: string
  original_material_length: string
  branch_count: string
  budget_quantity: string
  inventory_quantity: string
  weight_grams: string
  cut_piece_quantity: string
  purchase_consumption: string
  source_order_quantity: string
  total_purchase_quantity: string
  notes: string
  tube_shape: string
  tube_diameter: string
  tube_thickness: string
  tube_coating_color: string
  coating_unit_area_sqm: string
  purchase_unit_weight_kg: string
  tube_cut_piece_count: string
  tube_cut_length_m: string
  long_material_unit_weight_kg: string
  tube_unit_weight_kg: string
  long_material_total_weight_kg: string
  source_inventory_material_id: string | null
  source_raw_material_id: string | null
  hardware_material_number: string
  hardware_color: string
  hardware_flow_unit: string
  unit_material_weight_kg: string
  powder_coating_color: string
  powder_coating_unit_area_sqm: string
  plastic_material_number: string
  plastic_color: string
  source_packaging_material_id: string | null
  packaging_material_number: string
  packaging_color: string
  units_per_box: string
  source_cutting_material_id: string | null
  cutting_material_number: string
  cutting_item_type: string
  cutting_item_type_display: string
  cutting_category: string
  cutting_color: string
  images: BomLineImage[]
  source_accessory_product_name_id: string | null
  source_accessory_specification_id: string | null
  source_accessory_color_id: string | null
  source_accessory_material_id: string | null
  accessory_color: string
  source_fabric_material_id: string | null
  source_fabric_specification_id: string | null
  source_fabric_width_id: string | null
  source_product_color_id: string | null
  fabric_width: string
  fabric_color_card: string
  fabric_color_code: string
  fabric_color_name: string
  raw_values: Record<string, string>
  source_formulas: Record<string, string>
}

export interface BomSection {
  id: string
  line_number: number
  section_type: BomSectionType
  section_type_display: string
  title: string
  source_title_row: number | null
  source_header_row: number | null
  headers: Record<string, string>
  calculation_rows: Array<{ source_row_number: number; raw_values: Record<string, string>; source_formulas: Record<string, string> }>
  lines: BomLine[]
}

export interface Bom {
  id: string
  bom_number: string
  version_number: number
  production_task_number: string
  order_number: string
  customer_name: string
  planned_start_date: string | null
  planned_end_date: string | null
  source_sales_order_number: string | null
  is_historical_unlinked: boolean
  product_number_snapshot: string
  product_code_snapshot: string
  item_number_snapshot?: string
  product_name_snapshot: string
  specification_snapshot: string
  material_snapshot?: string
  product_master_id?: string | null
  product_category_id?: string | null
  product_unit_id?: string | null
  product_color_id?: string | null
  product_color_snapshot: string
  product_color_code_snapshot?: string
  product_color_card_snapshot?: string
  product_unit_code_snapshot?: string
  product_unit_name_snapshot?: string
  product_category_snapshot: string
  order_quantity: string
  current_order_quantity: string
  product_unit_name: string
  is_order_quantity_outdated: boolean
  is_order_product_outdated: boolean
  source_quantity: string | null
  batch_quantity: string | null
  batch_quantity_breakdown: string[]
  quantity_difference: string
  quantity_difference_reason: string
  quantity_requires_confirmation: boolean
  status: BomStatus
  status_display: string
  creation_method: BomCreationMethod
  creation_method_display: string
  section_count: number
  line_count: number
  section_summary: BomSectionSummary[]
  maintenance_match_count: number
  maintenance_unmatched_count: number
  source_original_name: string
  source_sheet_name: string
  updated_by_name: string
  confirmed_by_name: string | null
  confirmed_at: string | null
  confirmation_reason: string
  created_at: string
  updated_at: string
}

export interface BomDetail extends Bom {
  source_metadata: Record<string, string>
  calculation_summary: Record<string, unknown>
  maintenance_unmatched_values: Array<{ field: string; value: string }>
  copied_from_number: string | null
  configured_field_labels: string[]
  sections: BomSection[]
  production_task_id: string
  production_task_product_id: string
  production_task_product_master_id: string | null
  production_task_customer_product_name: string
  production_task_customer_specification: string
  production_task_customer_color: string
  product_information_confirmed: boolean
  product_information_confirmed_at?: string | null
  product_information_confirmed_by_name?: string | null
  product_information?: import('./product').ProductInformation | null
}

export interface BomLineInput {
  pending_raw_material?: RawMaterialInput
  client_key?: string
  fabric_source_client_key?: string | null
  cutting_pieces_per_set?: string | number | null
  fabric_meters_per_piece?: string | null
  cutting_sets_per_product?: string | number | null
  fabric_source_line_id?: string | null
  fabric_meters_per_set?: string | null
  id?: string
  category: string
  material: string
  part_name: string
  specification: string
  raw_material: string
  length_value: string
  unit_consumption: string
  total_consumption: string
  unit: string
  hardness: string
  original_material_length: string
  branch_count: string
  budget_quantity: string
  inventory_quantity: string
  weight_grams: string
  cut_piece_quantity: string
  purchase_consumption: string
  source_order_quantity: string
  total_purchase_quantity: string
  notes: string
  tube_shape: string
  tube_diameter: string
  tube_thickness: string
  tube_coating_color: string
  coating_unit_area_sqm: string
  purchase_unit_weight_kg: string
  tube_cut_piece_count: string
  source_inventory_material_id: string | null
  source_raw_material_id: string | null
  hardware_material_number: string
  hardware_color: string
  hardware_flow_unit: string
  unit_material_weight_kg: string
  powder_coating_color: string
  powder_coating_unit_area_sqm: string
  plastic_material_number: string
  plastic_color: string
  source_packaging_material_id: string | null
  packaging_material_number: string
  packaging_color: string
  units_per_box: string
  source_cutting_material_id: string | null
  cutting_material_number: string
  cutting_item_type: string
  cutting_item_type_display: string
  cutting_category: string
  cutting_color: string
  images: BomLineImage[]
  /** 仅供编辑器在未保存裁剪行中使用，不直接提交给 BOM 接口。 */
  draft_key?: string
  /** 暂存图片由保存接口转换为正式 images。 */
  draft_images?: BomDraftLineImage[]
  source_accessory_product_name_id: string | null
  source_accessory_specification_id: string | null
  source_accessory_color_id: string | null
  source_accessory_material_id: string | null
  accessory_color: string
  source_fabric_material_id: string | null
  source_fabric_specification_id: string | null
  source_fabric_width_id: string | null
  source_product_color_id: string | null
  fabric_width: string
  fabric_color_card: string
  fabric_color_code: string
  fabric_color_name: string
}

export interface BomSectionInput {
  id?: string
  section_type: BomSectionType
  title: string
  lines: BomLineInput[]
}

export interface VersionedBom {
  data: BomDetail
  etag: string
}

export interface BomMaterialSaveOptions {
  intent: 'draft' | 'verify'
  quantity_confirmation_reason?: string
  confirmation_token?: string
}

export interface BomMaterialSavePreview {
  confirmation_token: string | null
  new_materials: Array<{
    key: string
    item_type: string
    category_name: string
    material_name: string
    specification: string
    width: string
    color_name: string
    color_label: string
    material: string
    unit_name: string
    warehouse_name: string
    locations: Array<{ section_title: string; line_number: number }>
  }>
}

export interface BomQuery {
  page?: number
  page_size?: number
  q?: string
  status?: BomStatus | ''
  product_category_id?: string
  updated_after?: string
  updated_before?: string
}

export interface PaginatedBoms { data: Bom[]; meta: PageMeta }

export interface BomHardwareMaterial {
  id: string
  material_number: string
  item_type: string
  item_type_display: string
  category_name: string
  material_name: string
  material: string
  color_name: string
  specification: string
  unit_code: string
  unit_name: string
  weight_kg: string
  flow_unit: string
  number_value: string
}

export interface BomHardwareMaterialQuery {
  page?: number
  page_size?: number
  q?: string
  material_name?: string
}

export interface BomPipeMaterialMatchQuery {
  material: string
  diameter: string
  thickness: string
  tube_shape?: string
  raw_bar_length_m?: string
}

export interface BomPipeMaterial extends BomHardwareMaterial {
  diameter: string
  thickness: string
  length: string
}

export interface BomPipeMaterialMatches {
  candidates: BomPipeMaterial[]
  automatic_source_id: string | null
  reason: 'unique' | 'multiple' | 'no_match' | 'incomplete' | 'needs_review'
}

export interface BomHardwareMaterialGroup {
  material_name: string
  count: number
  pinyin_search: string
}

export interface PaginatedBomHardwareMaterials {
  data: BomHardwareMaterial[]
  meta: PageMeta
}

export interface BomPlasticMaterial {
  id: string
  material_number: string
  item_type: string
  item_type_display: string
  category_name: string
  material_name: string
  material: string
  color_name: string
  specification: string
  unit_code: string
  unit_name: string
  weight_kg: string
  flow_unit: string
  number_value: string
}
export interface BomPlasticMaterialQuery {
  page?: number
  page_size?: number
  q?: string
  material_name?: string
}

export interface PaginatedBomPlasticMaterials {
  data: BomPlasticMaterial[]
  meta: PageMeta
}

export interface BomPackagingMaterial extends BomPlasticMaterial {}

export interface BomSemiFinishedMaterial extends BomPlasticMaterial {}

export interface BomMaterialPickerQuery {
  page?: number
  page_size?: number
  q?: string
  material_name?: string
}

export interface PaginatedBomPackagingMaterials {
  data: BomPackagingMaterial[]
  meta: PageMeta
}

export interface PaginatedBomSemiFinishedMaterials {
  data: BomSemiFinishedMaterial[]
  meta: PageMeta
}

export interface BomAuxiliarySpecificationOption {
  id: string
  specification_value: string
}

export interface BomAuxiliaryColorOption {
  id: string
  color_name: string
}

export interface BomAuxiliaryProductOption {
  id: string
  product_name: string
  pinyin_search: string
  unit_name: string
  specifications: BomAuxiliarySpecificationOption[]
  colors: BomAuxiliaryColorOption[]
}

export interface BomAccessoryMaterialOption {
  id: string
  material_name: string
}

export interface BomFabricMaterialOption {
  id: string
  material_name: string
}

export interface BomFabricSpecificationOption {
  id: string
  specification_name: string
}

export interface BomFabricWidthOption {
  id: string
  width_value: string
}

export interface BomProductColorOption {
  id: string
  color_card: string
  color_code: string
  color_name: string
}

export interface BomEditorReferenceOptions {
  auxiliary_products: BomAuxiliaryProductOption[]
  accessory_materials: BomAccessoryMaterialOption[]
  fabric_materials: BomFabricMaterialOption[]
  fabric_specifications: BomFabricSpecificationOption[]
  fabric_widths: BomFabricWidthOption[]
  product_colors: BomProductColorOption[]
}

export interface BomProductionTaskProduct {
  id: string
  production_task_id: string
  task_etag: string
  task_number: string
  order_number: string
  customer_name: string
  task_currency_id: string
  task_currency_code: string
  task_status: string
  task_status_display: string
  product_id: string | null
  product_number: string
  product_code: string
  product_name: string
  specification: string
  order_quantity: string | number
  source_delivery_batch_line_id: string | null
  batch_quantity: string | number | null
  delivery_date: string
  planned_start_date: string | null
  planned_end_date: string | null
  existing_bom_count: number
}

export type BomFilterOptions = Pick<BomOptions, 'product_categories'>

export interface BomOptions {
  production_task_products: BomProductionTaskProduct[]
  products: import('./productionTask').ProductOption[]
  currencies: import('./productionTask').CurrencyOption[]
  units: import('./productionTask').UnitOption[]
  colors: import('./productionTask').ColorOption[]
  detail_template: import('./productionTask').ProductionTaskDetailTemplate[]
  history_boms: Bom[]
  product_categories: Array<{ id: string; category_name: string }>
  creation_methods: Array<{ value: BomCreationMethod; label: string }>
  configured_field_labels: string[]
  updated_date_presets: Array<{ value: string; label: string }>
}

export interface BomWorkbookPreview {
  file_name: string
  sheet_name: string
  sheet_number: number
  metadata: Record<string, string>
  section_count: number
  line_count: number
  preview_limit: number
  preview_row_count: number
  has_more_preview_rows: boolean
  sections: Array<{
    section_type: BomSectionType
    title: string
    line_count: number
    preview_rows: Array<{
      line_number: number
      source_row_number: number | null
      material_category: string
      material_code: string
      material_name: string
      specification: string
      unit: string
      unit_consumption: string
      section: string
      notes: string
    }>
  }>
  calculation_summary: { calculation_row_count: number; formula_column_count: number; formula_columns: string[] }
  maintenance: {
    configured_field_labels: string[]
    matched_count: number
    unmatched_count: number
    unmatched_values: Array<{ field: string; value: string }>
  }
  identity_errors: string[]
  quantity: {
    order_quantity: string
    source_quantity: string | null
    batch_quantity: string | null
    difference: string
    requires_confirmation: boolean
  }
}
