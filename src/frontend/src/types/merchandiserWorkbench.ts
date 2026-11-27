export type MerchandiserTodo = 'need' | 'soon' | 'late' | 'owing' | 'past'
export type MerchandiserFollow = 'unsent' | 'returns' | 'ordinary'
export type MerchandiserCategory = MerchandiserTodo | MerchandiserFollow | 'day' | 'period_tasks' | 'period_purchases' | 'supplier'
export type MerchandiserPeriod = 'month' | 'quarter' | 'year'

export interface MerchandiserOverview {
  as_of: string
  counts: Record<MerchandiserTodo | MerchandiserFollow, number | null>
  upcoming: { date: string; count: number }[]
}

export interface MerchandiserAmount {
  currency: string
  amount: string
}

export interface MerchandiserSupplier {
  id: string
  name: string
  order_count: number
  unpriced_count: number
  amounts: MerchandiserAmount[]
}

export interface MerchandiserActivity {
  start_date: string
  end_date: string
  as_of: string
  task_count: number
  purchase_order_count: number | null
  supplier_count: number | null
  amounts: MerchandiserAmount[]
  suppliers: MerchandiserSupplier[]
  unpriced_count: number
  undated_count: number
  unknown_supplier_count: number
}

export interface MerchandiserItemsQuery {
  category: MerchandiserCategory
  date?: string
  period?: MerchandiserPeriod
  supplier_id?: string
}

export interface MerchandiserSelection extends MerchandiserItemsQuery {
  title: string
  unit: string
}

export interface MerchandiserItems {
  data: {
    columns: { key: string; label: string }[]
    rows: { task_id: string; task_number: string; cells: Record<string, string> }[]
  }
  meta: { total: number; page: number; page_size: number; total_pages: number }
}
