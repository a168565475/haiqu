import type { PlanCategory } from './productionScheduling'

export interface ScheduleInternalPlan {
  category: PlanCategory
  craft_id: string
  craft_name: string
  workshop_id: string | null
  workshop_name: string
  plan_date: string | null
  milestone: string
  planned_quantity: string
  unit_name: string
  estimated_wage: string | null
  reported_amount: string | null
  estimated_amount_status: string
  reported_amount_status: string
  progress_percent: number | null
  plan_status: string
  plan_status_display: string
  wage_status: string
  reason: string
  scheme_id: string | null
  can_view_wage: boolean
  can_view_reports: boolean
}

export interface ScheduleOutsourcingRecord {
  id: string
  order_id: string
  order_kind: 'REGULAR' | 'TUBE' | 'P4'
  order_number: string
  craft_name: string
  part_name: string
  factory_name: string
  planned_quantity: string | null
  quantity_unit: string
  dispatched_quantity: string | null
  dispatched_unit: string | null
  received_quantity: string | null
  received_unit: string | null
  shortage_quantity: string | null
  unit_price: string | null
  price_unit: string
  planned_amount: string | null
  expected_return_date: string | null
  status: string
  status_display: string
  detail_access: string
  reason: string
}

export type ScheduleOutsourcingQuantityField = 'planned_quantity' | 'dispatched_quantity' | 'received_quantity' | 'shortage_quantity'

export interface ScheduleOutsourcingOrderSummary extends Omit<ScheduleOutsourcingRecord, 'part_name'> {
  record_count: number
  shortage_unit: string | null
  quantity_notes: Record<ScheduleOutsourcingQuantityField, string>
  unit_price_status: 'READY' | 'MULTIPLE' | 'UNKNOWN'
  unit_price_note: string
  planned_amount_note: string
}

export interface ScheduleMaterialIssueRecord {
  id: string
  issue_number: string
  workshop_name: string
  recipient_name: string
  line_count: number
  issue_at: string | null
  issued_at: string | null
  status: string
  status_display: string
}

export interface ScheduleProductExecution {
  schedule_product_id: string
  internal_plans: ScheduleInternalPlan[]
  estimated_wage: string | null
  reported_amount: string | null
  estimated_amount_status: string
  reported_amount_status: string
  outsourcing: { allowed: boolean; records: ScheduleOutsourcingRecord[]; planned_amount: string | null }
  material_issues: { allowed: boolean; records: ScheduleMaterialIssueRecord[] }
}

export interface ScheduleExecutionSummary {
  schedule_id: string
  products: ScheduleProductExecution[]
  totals: {
    estimated_wage: string | null
    reported_amount: string | null
    outsourcing_planned_amount: string | null
    complete_scope: boolean
    reason: string
  }
}
