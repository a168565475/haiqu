import type { MaterialAttributeSnapshot, PurchaseBatchType, PurchaseOrderStatus } from './purchaseOrder'
import type { PageMeta } from './referenceData'

export type PurchaseGroupStatus = 'PENDING' | 'PURCHASING' | 'COMPLETED' | 'UNKNOWN'

export interface PurchaseGroupSourceSnapshot {
  material_catalog_id?: string | null
  material_selection_snapshot?: import('./materialCatalog').MaterialSelectionSnapshot | Record<string, never>
  bom_id: string | null
  bom_line_id: string | null
  source_bom_line_id_snapshot: string | null
  product_line_id_snapshot: string | null
  bom_number_snapshot: string
  product_number_snapshot: string
  product_code_snapshot: string
  product_name_snapshot: string
  product_specification_snapshot: string
  section_type_snapshot: string
  section_title_snapshot: string
  category_snapshot: string
  material_snapshot: string
  part_name_snapshot: string
  specification_snapshot: string
  raw_material_snapshot: string
  material_attributes_snapshot: MaterialAttributeSnapshot
  required_quantity: string | null
  source_quantity_field: string
  source_quantity_text: string
  source_unit_text: string
  quantity_parse_status: 'READY' | 'MISSING' | 'INVALID'
  raw_bar_length_m?: string | null
  suggested_bar_count?: number | null
  suggested_purchase_meters?: string | null
  calculation_snapshot: Record<string, unknown>
}

export interface PurchaseGroupProgressLine {
  id: string
  line_number: number
  source_bom_line_id_snapshot: string | null
  product_line_id_snapshot: string | null
  required_quantity: string | null
  source_unit_text: string
  source_snapshot: PurchaseGroupSourceSnapshot
  purchased_quantity: string | null
  accepted_quantity: string | null
  in_progress_quantity?: string | null
  purchased_bar_count?: string | null
  accepted_bar_count?: string | null
  in_progress_bar_count?: string | null
  /** 后端十进制百分比，不封顶；null表示来源或汇总缺口。 */
  progress_percent: string | null
  /** 使用后端原始数量判断，不能由四舍五入后的百分比推算。 */
  is_satisfied: boolean
  compatibility_issues: string[]
}

export interface PurchaseGroupProgress {
  status: PurchaseGroupStatus
  satisfied_line_count: number
  line_count: number
  lines: PurchaseGroupProgressLine[]
}

export interface PurchaseBatchSummary {
  id: string
  order_number: string
  batch_number: number
  batch_type: PurchaseBatchType
  status: PurchaseOrderStatus
  display_status?: PurchaseOrderStatus
  currency_code_snapshot: string
  total_amount: string | null
}

export interface PurchaseGroupProduct {
  product_line_id: string
  product_name: string
  specification: string
  material: string
  color_card: string
  color_name: string
  color_code: string
  order_quantity: string | null
  order_unit: string
}

export interface PurchaseGroup {
  id: string
  group_number: string
  production_task_id: string
  product_line_id_snapshot: string | null
  source_bom_id_snapshot: string | null
  production_task_number_snapshot: string
  sales_order_number_snapshot: string
  customer_name_snapshot: string
  product?: PurchaseGroupProduct | null
  order_delivery_date?: string | null
  source_revision: string
  compatibility_issues: string[]
  progress: PurchaseGroupProgress
  display_status?: PurchaseGroupStatus
  manual_completed_at?: string | null
  manual_completed_by_name?: string
  manual_completion_remark?: string
  completion?: { can_complete: boolean; blocked_reason: string }
  batches: PurchaseBatchSummary[]
  created_at: string
  updated_at: string
}

export interface PurchaseGroupQuery {
  page?: number
  page_size?: number
  production_task_id?: string
}

export interface PurchaseGroupFilterOptions {
  production_tasks: { id: string; task_number: string; order_number: string }[]
}

export interface PaginatedPurchaseGroups {
  data: PurchaseGroup[]
  meta: PageMeta
}

export interface VersionedPurchaseGroup {
  data: PurchaseGroup
  etag: string
}

export interface PurchaseGroupInput {
  production_task_id: string
  bom_id: string
  source_revision: string
}

export interface PurchaseBatchLineInput {
  purchase_group_line_id: string
  actual_purchase_quantity?: string | null
  actual_bar_count?: number | string | null
  supplier_id?: string | null
  delivery_date?: string | null
  unit_price?: string | null
  quantity_difference_reason?: string
}

export interface PurchaseBatchInput {
  /** 同一次提交重试时保留UUID，由调用方管理，API层不重建。 */
  request_id: string
  batch_type: PurchaseBatchType
  currency_id: string
  is_mailed?: boolean | null
  lines: PurchaseBatchLineInput[]
}
