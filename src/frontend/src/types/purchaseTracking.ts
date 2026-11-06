import type { MaterialAttributeSnapshot } from './purchaseOrder'
import type { MaterialSelectionSnapshot } from './materialCatalog'

export type PurchaseTrackingTab = 'arrival' | 'coverage'
export type PurchaseTrackingRiskCode =
  | 'NEAR_DUE' | 'DUE_TODAY' | 'OVERDUE' | 'DELIVERY_UNKNOWN' | 'CLASSIFICATION_UNKNOWN'
  | 'ARRIVAL_UNKNOWN' | 'RETURN_PENDING' | 'ARRIVED' | 'OUTSIDE_WINDOW' | 'ENDED'
  | 'SCHEDULED_UNPURCHASED' | 'SCHEDULED_SHORT' | 'PENDING_PURCHASE' | 'COVERED'
  | 'DEMAND_UNKNOWN' | 'DEMAND_CHANGED'
  | 'BOM_PURCHASE_TIMEOUT' | 'PURCHASE_OVERDUE' | 'PURCHASE_DUE_TODAY' | 'PURCHASE_UPCOMING'
  | 'BOM_CONFIRMATION_UNKNOWN' | 'SCHEDULE_DATE_UNKNOWN' | 'ORDER_DELIVERY_UNKNOWN' | 'PURCHASE_RULE_UNKNOWN'

export interface PurchaseTrackingRisk {
  code: PurchaseTrackingRiskCode
  label: string
  level: 'danger' | 'warning' | 'info' | 'success'
  rank: number
}

export interface PurchaseTrackingAction {
  kind: 'view_order' | 'view_return' | 'create_group' | 'create_batch' | 'view_group' | 'view_bom'
  label: string
  path: string
}

export interface PurchaseTrackingRow {
  row_key: string
  production_task_id: string
  task_number: string
  product_line_id: string | null
  product_name: string
  material_name: string
  specification: string
  unit: string | null
  purchase_group_id: string | null
  source_bom_line_id: string | null
  source_reliable: boolean
  verification_notes: string[]
  is_history: boolean
  risks: PurchaseTrackingRisk[]
  actions: PurchaseTrackingAction[]
  action_blocked_reason: string
  evaluated_at: string
}

export interface PurchaseTrackingArrival extends PurchaseTrackingRow {
  material_selection_snapshot: MaterialSelectionSnapshot | Record<string, never>
  material_attributes_snapshot: MaterialAttributeSnapshot
  part_name: string
  material: string
  raw_material: string
  purchase_order_id: string
  purchase_order_line_id: string
  purchase_order_no: string
  batch_number: number | null
  publication_status: string
  supplier_name: string
  ordered_quantity: string | null
  received_quantity: string | null
  accepted_quantity: string | null
  pending_quality_quantity: string | null
  unreceived_quantity: string | null
  return_quantity: string | null
  return_pending: boolean
  delivery_date: string | null
  days_remaining: number | null
  ordered_root_count: string | null
  received_root_count: string | null
  unreceived_root_count: string | null
  root_count_note: string
}

export interface PurchaseTrackingCoverage extends PurchaseTrackingRow {
  bom_created_at: string | null
  bom_confirmed_at: string | null
  bom_purchase_due_at: string | null
  latest_purchase_date: string | null
  purchase_days_remaining: number | null
  material_category_key: string | null
  order_delivery_date: string | null
  material_attributes_snapshot: MaterialAttributeSnapshot
  material_selection_snapshot: MaterialSelectionSnapshot | Record<string, never>
  part_name: string
  material: string
  raw_material: string
  required_quantity: string | null
  purchased_quantity: string | null
  remaining_quantity: string | null
  scheduled: boolean
  material_inbound_date: string | null
  group_status: string
  required_root_count: string | null
  purchased_root_count: string | null
  remaining_root_count: string | null
  root_count_note: string
}

export interface PurchaseTrackingQuery {
  production_task_id?: string
  risk?: PurchaseTrackingRiskCode
  include_history?: boolean
  page?: number
  page_size?: number
  row_key?: string
}

export interface PurchaseTrackingPage<T> {
  data: T[]
  meta: { page: number; page_size: number; total: number; total_pages: number }
}

export interface PurchaseTrackingFilterOptions {
  production_tasks: { id: string; task_number: string; order_number: string }[]
}

export interface PurchaseTrackingPolicyInput {
  bom_timeout_days: number | null
  category_lead_days: Record<string, number | null>
}

export interface PurchaseTrackingPolicy extends PurchaseTrackingPolicyInput {
  categories: { key: string; label: string }[]
  etag: string
  can_manage: boolean
}
