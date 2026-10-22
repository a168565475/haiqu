export interface ProductionTimelineEvent {
  id: string
  kind: string
  title: string
  actor_name: string
  occurred_at: string
  document_number: string
  detail_path: string | null
  changes: Array<{ label: string; before: string; after: string }>
}
export interface ProductionTimelinePage {
  data: ProductionTimelineEvent[]
  meta: { total: number; page: number; page_size: number }
}
