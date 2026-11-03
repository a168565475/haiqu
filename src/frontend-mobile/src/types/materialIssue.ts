export type MaterialIssueStatus = 'DRAFT' | 'PENDING_REVIEW' | 'RETURNED' | 'ISSUED'
export type MaterialIssueStockMode = 'LEGACY' | 'PUBLIC_V2'
export interface NamedOption { id: string; name: string }
export interface MaterialIssueProduct {
  id: string; product_number: string; product_name: string; specification: string
  specification_display?: string; color: string; quantity?: string; unit?: string
}
export interface MaterialIssueOptions {
  production_tasks: { id: string; task_number: string; order_number: string }[]
  workshops: NamedOption[]
  recipients: (NamedOption & { workshop_id: string })[]
}
export interface MaterialAttribute { key: string; label: string; value: string }
export interface MaterialRequirement {
  requirement_id: string; stock_item_id: string; stock_mode?: MaterialIssueStockMode
  line_type: 'RAW' | 'SEMI'; section_code: string; material_number: string; material_name: string
  specification: string; color: string; material?: string; unit: string; part_names?: string[]
  required_quantity: string; internal_issued_quantity: string; outsourcing_issued_quantity: string
  pending_issue_quantity?: string; order_remaining: string; available_stock: string; max_issue_quantity: string
  validation_errors: string[]; warehouse_zones?: string[]; warehouse_zone?: string; completed_craft?: string
  processing_status?: string; bom_attributes?: MaterialAttribute[]
  material_selection_snapshot?: {
    schema_version?: number; name?: string; unit_name?: string; template_key?: string
    attributes?: Record<string, string>; color_card?: string; color_code?: string
  }
  conversion_snapshot?: {
    kind: string; pieces_per_bar?: number; raw_bar_length_m?: string; part_name?: string
    integer_required?: boolean; physical_issued_quantity?: string
  }
  semi_balance_allocations?: { balance_id: string; max_issue_quantity: string }[]
}
export interface MaterialIssueLine extends Omit<MaterialRequirement, 'stock_item_id' | 'validation_errors'> {
  id: string; requested_quantity: string; issued_quantity: string | null
  bar_count?: string; meters?: string
  public_stock_allocations?: {
    id: string; warehouse_zone: string; stock_quantity: string; stock_unit: string; meter_quantity: string | null
  }[]
}
export interface MaterialIssue {
  id: string; issue_number: string; status: MaterialIssueStatus; status_display: string; version: number
  stock_mode?: MaterialIssueStockMode
  production_task: { id: string; task_number: string; order_number: string } | null
  product: MaterialIssueProduct | null; workshop: NamedOption | null
  recipient: { id: string | null; name: string } | null; created_by: NamedOption
  issue_at: string | null; remark: string; line_count: number; lines: MaterialIssueLine[]
  submitted_at: string | null; issued_at: string | null; created_at: string; updated_at: string
  audit_events: { id: string; action: string; action_display: string; reason: string; created_at: string; actor: NamedOption }[]
}
export interface MaterialRequirementResponse {
  source_revision_hash: string; items: MaterialRequirement[]
  blockers: { code: string; detail?: string; section_code?: string | null }[]
}
export interface IssueWriteLine { requirement_id: string; requested_quantity: string }
export interface IssueWritePayload {
  production_task_id: string; product_line_id: string; workshop_id: string
  recipient_workshop_employee_id: string; issue_at: string; remark: string; lines: IssueWriteLine[]
  schedule_product_id?: string; plan_category?: string; client_request_id?: string
}
export interface VersionedIssue { data: MaterialIssue; etag: string }
export interface MaterialIssuePage {
  data: MaterialIssue[]; meta: { page: number; page_size: number; total: number; total_pages: number }
}
