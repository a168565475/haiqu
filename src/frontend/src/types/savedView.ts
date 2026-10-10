export interface SavedView {
  id: string
  module_code: string
  view_name: string
  filter_definition: Record<string, unknown>
  column_definition: string[]
  sort_definition: string[]
  is_default: boolean
  sort_order: number
  archived_at: string | null
  archive_reason: string
  created_at: string
  updated_at: string
}

export interface SavedViewCreateInput {
  module_code: 'CUSTOMER' | 'CONTACT' | 'INQUIRY' | 'QUOTATION' | 'SAMPLE_REQUEST' | 'PRODUCTION_TASK' | 'TASK'
  view_name: string
  filter_definition: Record<string, unknown>
  column_definition: string[]
  sort_definition: string[]
  sort_order?: number
}
