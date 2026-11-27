export type WarehouseQueue = 'inbound' | 'purchase' | 'issue' | 'dispatch' | 'returns'
export type WarehousePeriod = 'month' | 'quarter' | 'year'

export interface WarehouseRow {
  id: string
  kind: string
  kind_label?: string
  task_number: string
  product: string
  number: string
  party: string
  date: string | null
  status: string
  document_count?: number
}

export interface WarehouseCard {
  available: boolean
  count: number | null
  breakdown: Partial<Record<'semi' | 'finished' | 'partial' | 'documents' | 'overdue' | 'today', number>>
  preview: WarehouseRow | null
}

export interface WarehouseOverview {
  as_of: string
  queues: Record<WarehouseQueue, WarehouseCard>
  priority: (WarehouseRow & { queue: WarehouseQueue })[]
}

export interface WarehouseReference {
  queue: WarehouseQueue
  kind: string
  id: string
}

export interface WarehouseDetail {
  row: WarehouseRow
  lines: { name: string; unit: string; required: string | null; done: string | null; remaining: string | null; party?: string; date?: string | null; basis_label?: string }[]
  movements: { date: string | null; action: string; number: string; description: string }[]
  related: WarehouseReference | null
}

export interface WarehouseActivity {
  start_date: string
  end_date: string
  counts: Record<WarehouseQueue, number | null>
  records: (WarehouseReference & { task_number: string; number: string; party: string; date: string; description: string })[]
}

export type WarehouseDrill =
  | { type: 'items'; queue: WarehouseQueue; task?: { id: string; number: string } }
  | ({ type: 'detail' } & WarehouseReference)
  | { type: 'activity'; period: WarehousePeriod; queue: WarehouseQueue | 'all' }
