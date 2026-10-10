import type { PageMeta } from './referenceData'
import type { SupplierCategory } from './supplier'

export type PurchaseOrderStatus = 'DRAFT' | 'SUBMITTED' | 'PURCHASING' | 'COMPLETED'
export type PurchaseOrderSourceType = 'PRODUCTION' | 'SAMPLE'
export type PurchaseReturnStatus = 'NONE' | 'MISSING' | 'QUALITY_GENERATED' | 'PROCUREMENT_CONFIRMED' | 'COMPLETED'
export type PurchaseInboundWorkflowStatus =
  | 'NOT_STARTED'
  | 'PENDING_RECEIPT'
  | 'PARTIAL_RECEIVED'
  | 'PENDING_QUALITY'
  | 'PENDING_PROCUREMENT_CONFIRMATION'
  | 'PENDING_RETURN'
  | 'RETURN_RECORD_MISSING'
  | 'CONFIRMED'
  | 'COMPLETED'

export interface PurchaseOrderChoice<T extends string = string> {
  value: T
  label: string
}

export interface PurchaseOrderCurrencyOption {
  id: string
  code: string
  name: string
  symbol: string
}

export interface PurchaseOrderSupplierOption {
  id: string
  supplier_number: string
  supplier_name: string
  supplier_categories: SupplierCategory[]
  supplier_type?: string
  supplier_category_labels?: string[]
}

export interface PurchaseOrderProductionTaskOption {
  source_type?: PurchaseOrderSourceType
  source_number?: string
  source_id?: string
  demand_count?: number
  summary?: string
  id: string
  task_number: string
  order_number: string
  customer_name: string
  product_count: number
  delivery_date: string
  status: string
  status_display: string
  source_status_display?: string
  can_create: boolean
  blockers: PurchaseOrderSourceBlocker[]
  products?: PurchaseOrderProductSource[]
  existing_purchase_order_id?: string | null
  existing_purchase_order_number?: string
}

export interface PurchaseOrderOptions {
  sample_requests?: Array<Omit<PurchaseOrderProductionTaskOption, 'task_number' | 'order_number'> & { source_type: 'SAMPLE'; source_number: string }>
  production_tasks: PurchaseOrderProductionTaskOption[]
  suppliers: PurchaseOrderSupplierOption[]
  currencies: PurchaseOrderCurrencyOption[]
  statuses?: PurchaseOrderChoice<PurchaseOrderStatus>[]
  default_currency_id: string | null
  created_date_presets?: PurchaseOrderChoice[]
}

export interface PurchaseOrderFilterOptions {
  production_tasks: Array<{ id: string; task_number: string; order_number: string }>
  suppliers: Array<{ id: string; supplier_number: string; supplier_name: string }>
  statuses: PurchaseOrderChoice<PurchaseOrderStatus>[]
}

export interface PurchaseOrderProductSource {
  id: string
  line_number: number
  product_number: string
  product_code: string
  item_number: string
  product_name: string
  specification: string
  color_card: string
  color_name: string
  color_code: string
  order_quantity: string
  unit_code: string
  unit_name: string
}

export interface PurchaseOrderSourceLine {
  material_attributes_snapshot?: MaterialAttributeSnapshot
  raw_bar_length_m?: string | null
  suggested_bar_count?: number | null
  suggested_purchase_meters?: string | null
  sample_line_key?: string
  sample_demand_quantity?: string
  sample_supply_quantity?: string
  bom_id?: string
  bom_number: string
  bom_status: string
  bom_status_display: string
  bom_line_id?: string
  line_number?: number
  section_type: string
  section_title: string
  category: string
  product_line_id: string
  product_line_number: number
  product_number: string
  product_name: string
  product_specification: string
  product_color: string
  material: string
  part_name: string
  specification: string
  raw_material: string
  source_bom_line_id_snapshot: string
  required_quantity: string | null
  source_quantity_field: string
  source_quantity_text: string
  source_unit_text: string
  quantity_parse_status: 'READY' | 'MISSING' | 'INVALID'
  suggested_supplier_category: SupplierCategory | null
  category_source: 'SECTION' | 'HEURISTIC' | 'UNKNOWN'
}

export interface MaterialAttributeField {
  key: string
  label: string
  value: string
}

export interface MaterialAttributeSnapshot {
  schema_version?: number
  section_type?: string
  section_title?: string
  fields?: MaterialAttributeField[]
}

export interface PurchaseOrderSourceProductionTask {
  id: string
  task_number: string
  order_number: string
  customer_name: string
  delivery_date?: string
  status: string
  status_display: string
  product_count?: number
  products?: PurchaseOrderProductSource[]
}

export interface PurchaseOrderSourceBlocker {
  code: 'TASK_NOT_READY' | 'BOM_MISSING' | 'BOM_NOT_VERIFIED' | 'BOM_EMPTY' | 'BOM_QUANTITY_STALE' | string
  message: string
  product_name?: string
  bom_id?: string
  bom_number?: string
  product_line_id?: string
  product_line_number?: number
  product_color?: string
}

export interface PurchaseOrderBomOption {
  product_line_id: string
  product_line_number: number
  product_number: string
  product_code: string
  product_name: string
  product_color: string
  order_quantity: string
  unit_name: string
  bom_id: string | null
  bom_number: string
  bom_status: string
  bom_status_display: string
  line_count: number
  can_create: boolean
  blockers: PurchaseOrderSourceBlocker[]
}

export interface PurchaseOrderSource {
  source_type?: PurchaseOrderSourceType
  sample_request?: NonNullable<PurchaseOrderOptions['sample_requests']>[number]
  notes?: string
  can_create: boolean
  has_creatable_bom: boolean
  requires_bom_selection: boolean
  selected_bom_id: string | null
  bom_options: PurchaseOrderBomOption[]
  source_revision: string
  source_token?: string
  blockers: PurchaseOrderSourceBlocker[]
  production_task?: PurchaseOrderSourceProductionTask
  lines: PurchaseOrderSourceLine[]
  preview_lines: PurchaseOrderSourceLine[]
  default_currency_id: string | null
  existing_purchase_order_id?: string | null
  existing_purchase_order_number?: string
}

export interface PurchaseOrderLineInput {
  /** 管材采购时由采购员填写的单根长度（米）；生产 BOM 的既有管材规则仍由来源快照提供。 */
  raw_bar_length_m?: string | null
  actual_bar_count?: number | string | null
  quantity_difference_reason?: string
  bom_line_id?: string
  sample_line_key?: string
  supplier_id: string | null
  delivery_date: string | null
  actual_purchase_quantity: string | null
  unit_price: string | null
}

export interface PurchaseOrderInput {
  source_type?: PurchaseOrderSourceType
  sample_procurement_request_id?: string
  production_task_id?: string
  bom_id?: string
  source_revision: string
  currency_id: string | null
  is_mailed: boolean | null
  lines: PurchaseOrderLineInput[]
}

export interface PurchaseOrderSupplierSummary {
  id: string
  supplier_number: string
  supplier_name: string
}

export interface PurchaseOrderProductSummary {
  product_line_id: string
  product_name: string
  specification: string
  color_card: string
  color_name: string
  color_code: string
}

export interface PurchaseOrderListItem {
  source_type?: PurchaseOrderSourceType
  source_type_display?: string
  source_number?: string
  completion?: {
    can_complete: boolean
    blocked_reason: string
    inbound_status: PurchaseInboundWorkflowStatus
    inbound_status_display: string
    has_returns: boolean
    return_status: PurchaseReturnStatus
    return_status_display: string
    return_total?: number
    return_completed_count?: number
    return_pending_confirmation_count?: number
    return_pending_completion_count?: number
  }
  completed_at?: string | null
  completion_remark?: string
  id: string
  order_number: string
  production_task_id: string
  production_task_number: string
  sales_order_number: string
  is_historical_unlinked: boolean
  customer_name: string
  order_date: string
  delivery_date: string
  line_count: number
  supplier_assigned_line_count?: number
  supplier_count: number
  supplier_summary: PurchaseOrderSupplierSummary[]
  product_summary: PurchaseOrderProductSummary[]
  currency_id: string | null
  currency_code: string
  currency_symbol: string
  total_amount: string | null
  is_mailed: boolean | null
  status: PurchaseOrderStatus
  status_display: string
  created_by_name: string
  updated_by_name?: string
  created_at: string
  updated_at: string
}

export interface PurchaseOrderDetail extends PurchaseOrderListItem {
  lines: Array<PurchaseOrderSourceLine & PurchaseOrderLineInput & {
    id: string
    source_bom_line_id_snapshot: string
    amount: string | null
    supplier_number: string
    supplier_name: string
    supplier_type: string
    supplier_categories: SupplierCategory[]
  }>
}

export interface PurchaseOrderStats {
  completed?: number
  total: number
  draft: number
  submitted: number
  purchasing?: number
  mailed: number
  unmailed: number
  mailing_pending: number
  amounts: Array<{
    currency_id: string
    currency_code: string
    currency_symbol: string
    order_count: number
    total_amount: string
  }>
}

export interface PurchaseOrderQuery {
  return_status?: PurchaseReturnStatus | ''
  page?: number
  page_size?: number
  q?: string
  production_task_id?: string
  supplier_id?: string
  status?: PurchaseOrderStatus | ''
  is_mailed?: boolean | ''
  delivery_from?: string
  delivery_to?: string
  created_after?: string
  ordering?: string
}

export interface PaginatedPurchaseOrders {
  data: PurchaseOrderListItem[]
  meta: PageMeta
}

export interface VersionedPurchaseOrder {
  data: PurchaseOrderDetail
  etag: string
}

export type SupplierPurchaseSheetStatus = 'DRAFT' | 'PUBLISHED'

export interface PurchaseSheetTemplateOption {
  id: string
  template_code: string
  template_name: string
  supplier_categories: SupplierCategory[]
  version_id: string
  version_number: number
  version_name: string
}

export interface PurchaseSheetSupplierGroup {
  supplier_id: string
  supplier_number: string
  supplier_name: string
  supplier_categories: SupplierCategory[]
  line_count: number
  total_amount: string
  recommended_template_version_id: string | null
}

export interface PurchaseSheetOptions {
  purchase_order: PurchaseOrderDetail
  suppliers: PurchaseSheetSupplierGroup[]
  templates: PurchaseSheetTemplateOption[]
  existing_sheet_count: number
}

export interface PurchaseSheetParty {
  name: string
  address: string
  contact: string
  phone: string
}

export interface SupplierPurchaseSheetLine {
  measurement_kind?: string
  raw_bar_length_m?: string
  actual_bar_count?: number
  actual_purchase_meters?: string
  source_purchase_order_line_id: string
  product_name: string
  product_specification: string
  part_name: string
  specification: string
  material: string
  quantity: string
  unit: string
  unit_price: string
  amount: string
  delivery_date: string
  remark: string
}

export interface SupplierPurchaseSheetContent {
  title: string
  sheet_number: string
  purchase_date: string
  order: {
    source_type?: PurchaseOrderSourceType
    source_number?: string
    sales_order_number: string
    production_task_number: string
    purchase_request_number?: string
  }
  buyer: PurchaseSheetParty
  seller: PurchaseSheetParty
  settlement_mode: 'NORMAL' | 'ACTUAL_WEIGHT'
  tax_rate: string
  freight_bearer: string
  remark: string
  payment_and_delivery: string
  quality_standards: string[]
  delivery_handover: string
  special_instructions: string
  dispute_resolution: string
  effectiveness: string
  show_image: boolean
  seal_status: 'NOT_UPLOADED' | 'UPLOADED'
  lines: SupplierPurchaseSheetLine[]
  total_amount: string | null
}

export interface SupplierPurchaseSheet {
  id: string
  series_id: string
  purchase_order_id: string | null
  purchase_order_number: string | null
  purchase_request_id: string | null
  purchase_request_number: string | null
  production_task_number: string | null
  sales_order_number: string
  is_historical_unlinked: boolean
  supplier_id: string
  supplier_number_snapshot: string
  supplier_name_snapshot: string
  supplier_phone_snapshot: string
  sheet_number: string
  version_number: number
  procurement_batch_number: string
  is_current: boolean
  template_version_id: string
  template_id: string
  template_name: string
  template_version_number: number
  template_version_name: string
  status: SupplierPurchaseSheetStatus
  status_display: string
  content_snapshot: SupplierPurchaseSheetContent
  line_images: Array<{
    source_purchase_order_line_id: string
    image_file_id: string
    original_name: string
  }>
  seal_image: {
    image_file_id: string
    original_name: string
  } | null
  total_amount: string | null
  pdf_ready: boolean
  published_at: string | null
  updated_by_name: string
  created_at: string
  updated_at: string
}

export interface PaginatedSupplierPurchaseSheets {
  data: SupplierPurchaseSheet[]
  meta: PageMeta
}

export interface VersionedSupplierPurchaseSheet {
  data: SupplierPurchaseSheet
  etag: string
}

export interface PurchaseContractTemplateVersion {
  id: string
  version_number: number
  version_name: string
  content_config: Record<string, unknown>
  change_summary: string
  created_by_name: string
  created_at: string
}

export interface PurchaseContractTemplate {
  id: string
  template_code: string
  template_name: string
  supplier_categories: SupplierCategory[]
  status: 'ACTIVE' | 'INACTIVE'
  status_display: string
  current_version_number: number
  current_version: PurchaseContractTemplateVersion | null
  versions: PurchaseContractTemplateVersion[]
  updated_by_name: string
  created_at: string
  updated_at: string
}
