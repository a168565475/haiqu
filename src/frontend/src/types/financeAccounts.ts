import type { PageMeta } from './referenceData'

export interface FinanceAccountInput {
  account_type: string
  code?: string
  category: string
  name: string
  account_number: string
  currency_id: string
  status: 'ACTIVE' | 'INACTIVE'
}

export interface FinanceAccount extends FinanceAccountInput {
  id: string
  code: string
  currency_code: string
  currency_name: string
  etag: string
  can_delete: boolean
  delete_block_reason: string | null
  created_at: string
  updated_at: string
}

export interface FinanceAccountQuery {
  q?: string
  status?: 'ACTIVE' | 'INACTIVE'
  currency?: string
  page: number
  page_size: number
}
export interface FinanceAccountPage { data: FinanceAccount[]; meta: PageMeta }
