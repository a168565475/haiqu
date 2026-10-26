export type ProductionExpenseType = 'LOADING' | 'TRANSPORT' | 'OTHER'
export interface ProductionCostItem {
  id: string
  source_type: 'PURCHASE' | 'REPORT' | 'OUTSOURCING' | 'TUBE_OUTSOURCING' | 'EXPENSE'
  source_id: string
  number: string
  label: string
  amount: string | null
  currency: string | null
  amount_cny: string | null
  missing_reason: string | null
  href: string | null
  occurred_on: string | null
}
export interface ProductionCostCategory {
  key: 'purchase' | 'labor' | 'outsourcing' | 'other'
  label: string
  amount: string
  count: number
  missing_count: number
  items: ProductionCostItem[]
}
export interface ProductionTaskCostSummary {
  task_id: string
  currency: 'CNY'
  order_amount: string | null
  recorded_cost: string
  current_difference: string | null
  cost_ratio: string | null
  complete: boolean
  missing_count: number
  warnings: string[]
  categories: ProductionCostCategory[]
}
export interface ProductionTaskExpenseInput {
  expense_type: ProductionExpenseType
  description: string
  amount: string
  occurred_on: string
  remark: string
}
export interface ProductionTaskExpense extends ProductionTaskExpenseInput {
  id: string
  etag: string
}
export interface CreateProductionTaskExpenseInput extends ProductionTaskExpenseInput {
  client_request_id: string
}
