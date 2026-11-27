import type { PurchaseTrackingArrival, PurchaseTrackingCoverage } from './purchaseTracking'

export type PurchaseTodoKey = 'unstarted' | 'shortage' | 'near_due' | 'due_today' | 'overdue'
export type PurchaseFollowKey = 'late_for_use' | 'missing_due' | 'bom_changed'
export type PurchaseWorkbenchCategory = PurchaseTodoKey | PurchaseFollowKey
export type SpendPeriod = 'month' | 'quarter' | 'year'

export interface PurchaseWorkbenchSummary {
  as_of: string
  counts: Record<PurchaseWorkbenchCategory, number | null>
  availability_reasons: Partial<Record<PurchaseWorkbenchCategory, string>>
  missing_use_date_count: number
}

export type PurchaseWorkbenchRow =
  | (PurchaseTrackingCoverage & { material_count?: number })
  | (PurchaseTrackingArrival & { material_inbound_date?: string | null })

export interface PurchaseSpendSupplier {
  supplier_id: string | null
  supplier_name: string
  supplier_category: string
  amount: string
  unpriced_count: number
  order_count: number
  line_count: number
}

export interface PurchaseSpendCurrency {
  currency: string
  amount: string
  unpriced_count: number
  order_count: number
  supplier_count: number
  line_count: number
  suppliers: PurchaseSpendSupplier[]
  trend: { month: number; amount: string; line_count: number; unpriced_count: number }[]
}

export interface PurchaseWorkbenchSpend {
  period: SpendPeriod
  start_date: string
  end_date: string
  year: number
  currencies: PurchaseSpendCurrency[]
  unknown_date_count: number
}
