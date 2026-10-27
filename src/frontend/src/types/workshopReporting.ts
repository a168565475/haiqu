import type { PageMeta } from './referenceData'

export type WageSchemeStatus = 'DRAFT' | 'PENDING_APPROVAL' | 'APPROVED' | 'RETURNED' | 'SUPERSEDED'
export type WageSchemeLineStatus = 'ACTIVE' | 'VOID'
export type WorkCountingMode = 'ORDER' | 'SET' | 'PIECE'

export interface ReportingOption { id: string; name: string; workshop_id?: string; plan_category?: string | null }
export interface BomDisplayOption {
  id: string
  component_identity: string
  name: string
  material: string
  specification: string
  label: string
  source_type: 'METAL' | 'CUTTING'
  pieces_per_product: number | null
  cutting_sets_per_product: number | null
  cutting_pieces_per_set: number | null
}
export interface OperationOption extends ReportingOption {
  operation_number: string
  product_name: string
  craft_id: string
  unit_id: string | null
  unit_name: string | null
}
export interface ReportingContext {
  schedule_product: null | ReportingScheduleProduct
  schedule_products: ReportingScheduleProduct[]
  workshops: ReportingOption[]
  crafts: ReportingOption[]
  operations: OperationOption[]
  bom_items: BomDisplayOption[]
  employees: ReportingOption[]
}
export interface ReportingScheduleProduct {
    id: string; product_line_id: string; production_task_id: string; task_number: string; order_number: string
    product_name: string; product_number: string; product_code?: string; product_specification: string; product_color: string
    planned_quantity: string; order_quantity: string; unit_name: string
}
export interface PlanWageStatus {
  schedule_product_id: string
  workshop_id: string | null
  craft_id: string | null
  status: WageSchemeStatus | 'NOT_CREATED' | 'NO_EFFECTIVE_VERSION' | 'UNAVAILABLE' | 'FORBIDDEN' | 'CONFLICT'
  scheme_id: string | null
  can_report: boolean
  reason: string
  estimated_wage: string | null
  progress_percent: number | null
  plan_status: 'IN_PROGRESS' | 'COMPLETED'
  plan_status_display: string
}
export interface ScheduleProgressValue {
  status: 'READY' | 'NOT_CONFIGURED' | 'NOT_APPLICABLE'
  percentage: number | null
  display: string
}
export interface ScheduleProgressStatus {
  schedule_id: string
  progress: Record<'MATERIAL' | 'METAL' | 'SEWING' | 'ASSEMBLY', ScheduleProgressValue>
  as_of_date?: string
  overall_percentage?: number | null
  stage_progress?: Record<ScheduleStageKey, ScheduleStageProgress>
  outbound_progress?: ScheduleStageProgress
  outsourcing_status?: Record<'METAL' | 'SEWING', ScheduleOutsourcingStatus>
}

export type ScheduleOutsourcingState = 'NONE' | 'WAITING' | 'IN_PROGRESS' | 'RETURNED' | 'SHORTAGE' | 'UNKNOWN'
export type ScheduleOutsourcingRisk = 'none' | 'normal' | 'attention' | 'slow' | 'urgent' | 'unknown'
export interface ScheduleOutsourcingRecord {
  id: string
  order_number: string
  craft_name: string
  factory_name: string
  quantity_unit: string
  expected_return_date: string | null
  remaining_quantity: string | null
  remaining_display: string
  state: ScheduleOutsourcingState
  risk: ScheduleOutsourcingRisk
  description: string
}
export interface ScheduleOutsourcingStatus {
  state: ScheduleOutsourcingState
  risk: ScheduleOutsourcingRisk
  description: string
  records: ScheduleOutsourcingRecord[]
}

export type ScheduleStageKey = 'METAL' | 'CUTTING' | 'SEWING' | 'ASSEMBLY'
export interface ScheduleProductStageProgress {
  received_quantity?: number | null
  order_quantity?: number | null
  outbound_quantity?: number | null
  schedule_product_id: string
  status: ScheduleProgressValue['status']
  percentage: number | null
  planned_date: string | null
}
export interface ScheduleStageProgress {
  status: ScheduleProgressValue['status']
  percentage: number | null
  products: ScheduleProductStageProgress[]
}

export interface WageSchemeLine {
  id: string
  line_number: number
  work_item_id: string
  craft_id: string
  operation_id: string
  display_name: string
  craft_name: string
  operation_name: string
  operation_number: string
  bom_component_identity: string | null
  counting_mode: WorkCountingMode
  counting_mode_display: string
  order_quantity: string | number | null
  required_quantity: string | null
  completed_quantity?: string | null
  completed_amount?: string | null
  estimated_amount?: string | null
  production_description: string
  unit_name: string
  previous_price: string | null
  revised_price: string | null
  declared_price: string
  cumulative_quantity?: string
  production_date_quantity?: string
  last_workshop_employee_id?: string | null
  status: WageSchemeLineStatus
  note: string
}

export interface WageScheme {
  id: string
  scheme_number: string
  status: WageSchemeStatus
  status_display: string
  version: number
  revision: number
  can_create_change: boolean
  parent_scheme: null | { id: string; scheme_number: string; version: number; effective_from: string; effective_to: string | null }
  product_line_id: string
  schedule_product_id: string | null
  production_task: { id: string; task_number: string; order_number: string }
  product: { name: string; number: string; specification: string }
  workshop: ReportingOption
  scope_craft: ReportingOption
  crafts: ReportingOption[]
  operation_product_name: string
  effective_from: string | null
  effective_to: string | null
  remark: string
  line_count: number
  declared_total: string
  lines: WageSchemeLine[]
  events: Array<{ id: string; action: string; action_display: string; scheme_revision: number; actor: string; comment: string; created_at: string }>
  approved_by: string | null
  approved_at: string | null
  created_by_id: string
  created_by: string
  created_at: string
  updated_at: string
}

export interface WageSchemeLineInput {
  work_item_id?: string
  bom_line_id?: string | null
  craft_id: string
  operation_id: string
  display_name: string
  counting_mode: WorkCountingMode
  production_description: string
  previous_price: string | null
  revised_price: string | null
  declared_price: string
  status: WageSchemeLineStatus
  note: string
}
export interface WageSchemeInput {
  product_line_id: string
  workshop_id: string
  schedule_product_id: string | null
  craft_ids: string[]
  operation_product_name?: string
  remark: string
  history_source_scheme_id?: string | null
  lines: WageSchemeLineInput[]
}

export interface WorkReportLine {
  id: string; line_number: number; scheme_line_id: string; work_item_id: string
  workshop_employee_id: string; employee_name: string; production_line: number | null
  display_name: string; craft_name: string; operation_name: string; unit_name: string
  quantity: string; order_quantity_snapshot: number
  cumulative_quantity: string | null; required_quantity: string | null
  unit_price: string; amount: string
}
export interface WorkReport {
  can_delete?: boolean; etag?: string
  id: string; report_number: string; production_date: string
  production_task: { id: string; task_number: string; order_number: string }
  product: { name: string; number: string }
  product_line_id: string; schedule_product_id: string; workshop: ReportingOption
  scope_craft: ReportingOption
  scheme_id: string; scheme_version: number; revision: number; recorder: string; total_amount: string
  completed_plan: boolean
  updated_by: string; line_count: number; lines: WorkReportLine[]; created_at: string; updated_at: string
}
export interface WorkReportDay {
  production_date: string; report_count: number; order_count: number; product_count: number
  employee_count: number; line_count: number; total_amount: string; last_saved_at: string
}
export interface WorkReportTaskProgress {
  status: 'READY' | 'NOT_CONFIGURED' | 'UNAVAILABLE'
  percentage: number | null
}
export interface WorkReportTaskWorkshop extends ReportingOption {
  reported_amount?: string
  progress?: WorkReportTaskProgress
}
export interface WorkReportTask {
  id: string
  task_number: string
  order_number: string
  product?: { id: string; name: string; number: string; image_url: string | null } | null
  product_count?: number
  reported_amount?: string
  progress?: WorkReportTaskProgress
  workshops: WorkReportTaskWorkshop[]
}

export interface Paginated<T> { data: T[]; meta: PageMeta }
export interface Versioned<T> { data: T; etag: string }
