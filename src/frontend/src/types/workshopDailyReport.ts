export type WorkshopDailyTable = 'metal' | 'sewing-detail' | 'sewing-orders' | 'assembly'

export interface WorkshopDailyRow {
  id: string
  task_number: string
  product_name: string
  part_name?: string
  specification?: string
  color?: string
  employee?: string
  operation?: string
  unit?: string
  order_unit?: string
  order_quantity?: string | null
  today?: string
  cumulative?: string
  remaining?: string | null
}

export interface WorkshopDailyPage {
  data: WorkshopDailyRow[]
  meta: { page: number; page_size: number; total: number; total_pages: number }
}
