import type { PageMeta } from './referenceData'
import type { ProductionTaskStatus } from './productionTask'
import type { ScheduleProgressStatus } from './workshopReporting'

export type ScheduleStatus = 'ACTIVE' | 'VOID'
export type CraftType = 'INTERNAL' | 'EXTERNAL'
export type PlanCategory = 'METAL' | 'CUTTING' | 'SEWING' | 'ASSEMBLY'

export interface ScheduleCraftOption {
  id: string
  name: string
  craft_type: CraftType
  craft_type_display: string
  plan_category: PlanCategory | null
  workshop_name: string | null
}

export interface ScheduleOptions {
  crafts: ScheduleCraftOption[]
  plan_categories: Array<{ value: PlanCategory; label: string }>
  customers: Array<{ id: string; name: string; code: string }>
}

export interface ScheduleTaskProduct {
  id: string
  product_id: string
  line_number: number
  product_number: string
  product_code: string
  item_number: string
  product_name: string
  specification: string
  specification_display?: string
  material?: string
  color_name: string
  color_code: string
  quantity: number
  unit_id: string
  unit_name: string
  image_file_id: string | null
  bom_status: 'NOT_CREATED' | 'PENDING_CONFIRMATION' | 'VERIFIED'
  bom_status_display: string
  purchase_status: string
  purchase_status_display: string
  dimensions?: { expanded: string | null; folded: string | null; source: string | null } | null
}

export interface ScheduleTaskProductSummary {
  id: string
  item_number: string
  product_name: string
  specification: string
  specification_display?: string
  material?: string
  color_name: string
  quantity: number
  unit_name: string
  image_file_id: string | null
}

export interface ScheduleTaskCandidate {
  id: string
  task_number: string
  order_number: string
  sales_order_number: string | null
  customer_id: string
  customer_name: string
  order_date: string
  delivery_date: string
  salesperson_name: string
  follower_names: string[]
  planned_start_date: string | null
  planned_end_date: string | null
  status: 'READY' | 'IN_PRODUCTION'
  status_display: string
  product_count: number
  selectable: boolean
  unselectable_reason: string
  existing_schedule_id: string | null
  source_revision_hash: string
  scheduling_ready?: boolean
  scheduling_blockers?: string[]
  product_summaries: ScheduleTaskProductSummary[]
  products?: ScheduleTaskProduct[]
}

export interface ScheduleProduct {
  id: string
  product_line_id: string
  line_number: number
  planned_quantity: number
  source_quantity: number
  unit_id: string
  unit_name: string
  image_file_id: string | null
  product: Record<string, string | null>
  material_inbound_date: string
  metal_return_date: string
  sewing_return_date: string
  finished_inbound_date: string
  crafts: Array<{ id: string; name: string; craft_type: CraftType; plan_category: PlanCategory | null; is_active: boolean }>
}

export interface ProductionSchedule {
  id: string
  schedule_number: string
  production_task_id: string
  record_status: ScheduleStatus
  record_status_display: string
  version: number
  source: Record<string, any>
  list_amounts?: { estimated_wage: string | null; reported_amount: string | null } | null
  factory_follower_names?: string[]
  source_revision_hash: string
  source_current_status: string
  source_current_status_display: string
  source_is_archived: boolean
  products: ScheduleProduct[]
  date_ranges: Record<string, { from: string | null; to: string | null }>
  created_by: { id: string; name: string }
  updated_by: { id: string; name: string }
  created_at: string
  updated_at: string
  void_reason: string
  voided_at: string | null
  audit_timeline: Array<{ id: string; action: string; actor_name: string; occurred_at: string; after: Record<string, any> }>
}

export interface ScheduleWriteItem {
  product_line_id: string
  planned_quantity: number
  material_inbound_date: string
  metal_return_date: string
  sewing_return_date: string
  finished_inbound_date: string
  craft_ids: string[]
}

export interface ScheduleCreateInput {
  production_task_id: string
  source_revision_hash: string
  client_request_id: string
  items: ScheduleWriteItem[]
}

export interface ScheduleBatchCreateInput {
  schedules: ScheduleCreateInput[]
}

export interface ScheduleUpdateInput {
  source_revision_hash: string
  items: ScheduleWriteItem[]
}

export interface ScheduleCompletionPreview {
  schedule_id: string
  schedule_number: string
  schedule_etag: string
  task: { id: string; task_number: string; status: string; status_display: string; etag: string }
  progress: ScheduleProgressStatus['progress']
  products: Array<{
    schedule_product_id: string
    product_name: string
    specification: string
    color: string
    material: string
    required_quantity: number
    received_quantity: number
    unit_name: string
  }>
  sales_order: {
    id: string | null
    order_number: string | null
    status: string | null
    status_display: string | null
    etag: string | null
    can_sync: boolean
    reason: string
  }
}

export interface CompleteScheduleInput {
  task_etag: string
  reason: string
  sales_order_etag?: string
}

export interface CompleteScheduleResult {
  schedule_id: string
  production_task_id: string
  production_task_status: string
  production_sync: { before_status: string; after_status: string }
  progress: Record<string, { status: string; percentage: number | null; display: string }>
  sales_sync: {
    status: 'COMPLETED' | 'SKIPPED' | 'NOT_APPLICABLE' | 'ALREADY_COMPLETED'
    reason: string
    before_status: string | null
    after_status: string | null
  }
}

export interface ScheduleItem {
  id: string
  schedule_id: string
  product_line_id: string
  schedule_number: string
  production_task_id: string
  task_number: string
  sales_order_number: string | null
  customer_name: string
  customer_id: string
  product: Record<string, string | null>
  planned_quantity: number
  unit_name: string
  image_file_id: string | null
  plan_date: string
  craft_names: string[]
  line_number: number
  job_status: 'IN_PROGRESS' | 'COMPLETED' | 'PAUSED' | 'CANCELLED'
  production_task_status: ProductionTaskStatus
  job_status_display: string
}

export interface Paginated<T> { data: T[]; meta: PageMeta }
export interface VersionedSchedule { data: ProductionSchedule; etag: string }
export interface BatchCreatedSchedules { data: ProductionSchedule[] }
