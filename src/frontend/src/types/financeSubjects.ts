import type { PageMeta } from './referenceData'

export interface FinanceSubjectInput {
  parent_id: string | null
  level: number
  name: string
  status: 'ACTIVE' | 'INACTIVE'
}
export interface FinanceSubject extends FinanceSubjectInput {
  id: string
  full_path: string
  path_names: string[]
  effective_status: 'ACTIVE' | 'INACTIVE'
  blocked_by_ancestor: string | null
  child_count: number
  affected_path_count: number
  can_delete: boolean
  delete_block_reason: string | null
  etag: string
  created_at: string
  updated_at: string
}
export interface FinanceSubjectQuery {
  q?: string
  level?: number
  parent_id?: string
  status?: 'ACTIVE' | 'INACTIVE'
  page: number
  page_size: number
}
export interface FinanceSubjectPage { data: FinanceSubject[]; meta: PageMeta }
