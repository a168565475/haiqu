import type { OutsourcingQuantitySummary } from './unifiedOutsourcing'

export type SewingTodo = 'send' | 'working' | 'soon' | 'today' | 'overdue'
export type SewingFollow = 'late_send' | 'today_send' | 'partial'
export type SewingQueue = SewingTodo | SewingFollow | 'upcoming'
export type SewingPeriod = 'month' | 'quarter' | 'year'

export interface SewingWorkbenchOverview {
  as_of: string
  counts: Record<SewingTodo | SewingFollow, number>
  upcoming: { date: string; count: number }[]
}

export interface SewingWorkbenchActivity {
  start_date: string
  end_date: string
  dispatch_orders: number
  dispatch_factories: number
  receipt_orders: number
  receipt_factories: number
  receipt_events: number
  quantities: OutsourcingQuantitySummary[]
  factories: { id: string; name: string; order_count: number; quantities: OutsourcingQuantitySummary[] }[]
}

export interface SewingQuantityLine {
  name: string
  factory_name: string
  unit: string
  target: string
  actual: string
  remaining: string
}

export interface SewingWorkbenchOrder {
  id: string
  is_plan: boolean
  order_number: string
  task_number: string
  product_name: string
  planned_dispatch_date: string
  expected_return_date: string
  last_dispatch_date: string | null
  last_receipt_date: string | null
  factories: string[]
  materials: SewingQuantityLine[]
  parts: SewingQuantityLine[]
}
