export type DirectorWorkshop = 'METAL' | 'SEWING' | 'ASSEMBLY'
export type DirectorPeriod = 'month' | 'quarter' | 'year'
export type DirectorCategory = 'working' | 'late' | 'today' | 'planned' | 'day' | 'week'

export interface DirectorQuantity {
  target: string | null
  done: string | null
  remaining: string | null
  unit: string
  reason: string
}

export interface DirectorJob {
  id: string
  task_id: string
  task_number: string
  schedule_number: string
  product_name: string
  craft_name: string
  category: string
  stage: 'working' | 'planned' | 'completed' | 'unknown'
  due_date: string
  days_remaining: number
  latest_date: string | null
  latest_operation: string
  quantity: DirectorQuantity
}

export interface DirectorOverview {
  as_of: string
  workshop: DirectorWorkshop
  workshops: DirectorWorkshop[]
  counts: Record<'working' | 'late' | 'today' | 'planned', number | null>
  upcoming: { date: string; count: number }[]
  jobs: DirectorJob[]
}

export interface DirectorRecord {
  id: string
  date: string
  number: string
  task_number: string
  product_name: string
  name: string
  quantity: string | null
  unit: string
  job_id: string | null
}

export interface DirectorActivity {
  start_date: string
  end_date: string
  task_count: number
  record_count: number
  day_count: number
  quantities: { unit: string; quantity: string }[]
  records: DirectorRecord[]
  available: boolean
}

export interface DirectorDetail {
  job: DirectorJob
  operations: (DirectorQuantity & { name: string })[]
  reports: DirectorRecord[] | null
  receipts: DirectorRecord[] | null
}

export interface DirectorPage<T> {
  data: T
  meta: { total: number; page: number; page_size: number; total_pages: number }
}

export type DirectorSelection =
  | { kind: 'items'; category: DirectorCategory; title: string; date?: string }
  | { kind: 'detail'; id: string }
  | { kind: 'records'; period: DirectorPeriod; title: string }
