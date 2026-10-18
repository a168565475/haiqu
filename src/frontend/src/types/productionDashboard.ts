export type ProductionDashboardRole = 'owner' | 'executive' | 'workshop'
export type ProductionDashboardSectionState = 'READY' | 'EMPTY' | 'FORBIDDEN' | 'UNKNOWN'
export type ProductionDashboardCategory = 'METAL' | 'SEWING' | 'ASSEMBLY'
export type ProductionDashboardStatus = 'ALL' | 'PENDING_VALIDATION' | 'READY' | 'IN_PRODUCTION' | 'PAUSED' | 'COMPLETED'
export type ProductionDashboardFocus = 'ALL' | 'OVERDUE' | 'DUE_SOON' | 'UNSCHEDULED'

export interface ProductionDashboardQuery {
  q?: string
  days?: 3 | 7
  status?: ProductionDashboardStatus
  focus?: ProductionDashboardFocus
  workshop?: ProductionDashboardCategory
  production_date?: string
  task_date?: string | null
  task_page?: number
}

export interface ProductionDashboardSection<T> {
  state: ProductionDashboardSectionState
  reason: string
  data: T | null
}

export interface ProductionDashboardProgress {
  state: string
  percent: number | null
  label: string
}

export interface ProductionDashboardQuantity { quantity: string; unit: string; name?: string; product_line_id?: string | null }
export interface ProductionDashboardProduct {
  id: string
  name: string
  quantity: string
  unit: string
}

export interface ProductionDashboardTask {
  id: string
  task_number: string
  customer_name: string
  delivery_date: string | null
  days_to_due: number | null
  status: string
  status_display: string
  priority: string
  products: ProductionDashboardProduct[]
  schedule_id: string | null
  stages: { metal: ProductionDashboardProgress; sewing: ProductionDashboardProgress; assembly: ProductionDashboardProgress }
  href: string
}

export interface ProductionDashboardTasks {
  counts: { total: number; overdue: number; due_soon: number; unscheduled: number | null; completed: number; paused: number }
  status_distribution: { status: string; label: string; count: number }[]
  due_series: { date: string; count: number }[]
  items: ProductionDashboardTask[]
  total: number
  truncated: boolean
}

export interface ProductionDashboardOutsourcingItem {
  id: string
  row_key: string
  order_number: string
  delivery_date: string | null
  status: string
  status_display: string
  factory_names: string[]
  quantities: ProductionDashboardQuantity[]
  receipt_state: string
  href: string
}

export interface ProductionDashboardOutsourcing {
  pending_count: number
  overdue_count: number
  items: ProductionDashboardOutsourcingItem[]
  total: number
  truncated: boolean
}

export interface ProductionDashboardReceiptGap {
  state: 'READY' | 'UNKNOWN'
  product_line_id: string
  task_number: string
  name: string
  unit: string
  required: string
  received: string | null
  remaining: string | null
  href: string
}

export interface ProductionDashboardReceipt {
  id: string
  number: string
  date: string
  name: string
  quantity: string
  unit: string
  href: string
}

export interface ProductionDashboardReceipts {
  pending_state: 'READY' | 'EMPTY' | 'FORBIDDEN' | 'UNKNOWN'
  today_count: number
  today_quantities: ProductionDashboardQuantity[]
  pending_products: ProductionDashboardReceiptGap[]
  items: ProductionDashboardReceipt[]
  total: number
  truncated: boolean
}

export interface ProductionDashboardJob {
  key: string
  schedule_id: string
  task_number: string
  name: string
  craft_name: string
  unit: string
  plan_date: string | null
  status: string
  required: string | null
  cumulative: string | null
  today: string | null
  remaining: string | null
  progress: ProductionDashboardProgress
  href: string
}

export interface ProductionDashboardWorkshop {
  category: ProductionDashboardCategory
  plan_count: number
  items: ProductionDashboardJob[]
  total: number
  truncated: boolean
}

export interface ProductionDashboardReport {
  id: string
  number: string
  task_number: string
  workshop_name: string
  production_date: string
  lines: { operation: string; quantity: string; unit: string }[]
  href: string
}

export interface ProductionDashboardReports {
  date: string
  report_count: number
  employee_count: number
  items: ProductionDashboardReport[]
  total: number
  truncated: boolean
}

export interface ProductionDashboardPayload {
  generated_at: string
  filters: Required<ProductionDashboardQuery>
  sections: {
    tasks: ProductionDashboardSection<ProductionDashboardTasks>
    outsourcing: ProductionDashboardSection<ProductionDashboardOutsourcing>
    receipts: ProductionDashboardSection<ProductionDashboardReceipts>
    workshop: ProductionDashboardSection<ProductionDashboardWorkshop>
    reports: ProductionDashboardSection<ProductionDashboardReports>
  }
}
