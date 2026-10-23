export type MaterialIssueStatus = 'DRAFT' | 'PENDING_REVIEW' | 'RETURNED' | 'ISSUED'
export type MaterialIssueLineType = 'RAW' | 'SEMI'
export type MaterialIssueStockMode = 'LEGACY' | 'PUBLIC_V2'
import type { BomAttributeField } from './bomAttributes'

export interface NamedOption { id: string; name: string }
export interface MaterialIssueTaskOption {
  id: string; task_number: string; order_number: string; customer_name: string; status: string
}
export interface MaterialIssueOptions {
  production_tasks: MaterialIssueTaskOption[]
  workshops: NamedOption[]
  recipients: (NamedOption & { workshop_id: string })[]
}
export interface MaterialIssueProduct {
  id: string; line_number?: number; product_number: string; product_name: string
  specification: string; color: string; quantity?: string; unit?: string; image_file_id: string | null
  specification_display?: string; material?: string
}
export interface MaterialRequirement {
  bom_attributes?: BomAttributeField[]
  stock_mode?: MaterialIssueStockMode
  stock_before?: string | null
  stock_after?: string | null
  public_stock_allocations?: MaterialIssuePublicAllocation[]
  conversion_snapshot?: {
    kind: string; part_name?: string; pieces_per_bar?: number; raw_bar_length_m?: string
    whole_bar_required?: boolean; integer_required?: boolean; issued_pieces?: number | string
    raw_deducted_bar_count?: string; raw_deducted_meters?: string
    component_identity?: string
  }
  semi_balance_allocations?: Array<{ balance_id: string; available_stock: string; pending_issue_quantity?: string; max_issue_quantity: string }>
  batch_candidates?: MaterialIssueBatch[]
  batch_allocations?: MaterialIssueBatch[]
  bar_count?: string; meters?: string
  requirement_id: string; stock_item_id: string; line_type: MaterialIssueLineType; section_code: string
  material_number: string; material_name: string; material?: string; part_names?: string[]; specification: string; color: string; unit: string
  required_quantity: string; internal_issued_quantity: string; outsourcing_issued_quantity: string
  pending_issue_quantity?: string
  order_remaining: string; available_stock: string; max_issue_quantity: string; bom_version: number
  warehouse_zones?: string[]
  validation_errors: string[]
  completed_craft?: string; processing_status?: string; warehouse_zone?: string; quality?: 'AVAILABLE' | 'DEFECTIVE'
  component_required_quantity?: string; component_internal_issued_quantity?: string
  component_pending_issue_quantity?: string; component_order_remaining?: string
}
export interface MaterialIssuePublicAllocation {
  id: string; balance_id: string; warehouse_zone: string
  requested_quantity: string; stock_quantity: string; stock_unit: string
  meter_quantity: string | null
  before_quantity: string; after_quantity: string
  before_meter_quantity: string | null; after_meter_quantity: string | null
}
export interface MaterialIssueBatch {
  inbound_line_id: string; inbound_number?: string; warehouse_name?: string; zone_name?: string
  raw_bar_length_m?: string; available_quantity?: string; available_meters?: string
  requested_pieces?: string; bar_count?: string; meters?: string; after_bar_count?: string; after_meters?: string
}
export interface MaterialIssueLine extends Omit<MaterialRequirement, 'requirement_id' | 'stock_item_id' | 'bom_version' | 'validation_errors'> {
  id: string; line_number: number; requirement_id: string; raw_material_id: string | null
  semi_finished_balance_id?: string
  requested_quantity: string; issued_quantity: string | null
}
export interface MaterialIssueEvent {
  id: string; action: string; action_display: string; issue_version: number
  actor: NamedOption; reason: string; created_at: string
}
export interface MaterialIssue {
  stock_mode?: MaterialIssueStockMode
  id: string; issue_number: string; status: MaterialIssueStatus; status_display: string; version: number
  production_task: (MaterialIssueTaskOption & { customer_name: string }) | null
  product: MaterialIssueProduct | null; workshop: NamedOption | null; recipient: { id: string | null; name: string } | null
  issue_at: string | null; remark: string; source_revision_hash: string; line_count: number
  lines: MaterialIssueLine[]; audit_events: MaterialIssueEvent[]
  created_by: NamedOption; submitted_at: string | null; issued_at: string | null; issued_by: NamedOption | null
  created_at: string; updated_at: string
}
export interface MaterialIssuePreviewLine extends Partial<MaterialIssueLine> {
  line_id?: string
}
export interface MaterialIssuePreview {
  can_confirm: boolean
  lines: MaterialIssuePreviewLine[]
  errors?: { code: string; detail: string }[]
}
export interface PaginatedMaterialIssues {
  data: MaterialIssue[]
  meta: { page: number; page_size: number; total: number; total_pages: number }
}
export interface MaterialRequirementBlocker { code: string; detail?: string; section_code?: string | null }
export interface MaterialRequirementResponse { source_revision_hash: string; items: MaterialRequirement[]; blockers: MaterialRequirementBlocker[] }
