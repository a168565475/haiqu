import type { PageMeta } from './referenceData'

export interface FinancePerson { id: string; code: string; name: string }
export interface FinanceSourceTask {
  id: string; task_number: string; source_order_date: string; status: string; salesperson: FinancePerson
  readonly task_order_date: string; readonly task_delivery_date: string
}
export interface FinanceSourceProduct {
  id: string; item_number_snapshot: string; product_number_snapshot: string; product_code_snapshot: string
  product_name_snapshot: string; specification_snapshot: string; quantity: string; unit_code: string; unit_name: string
  reference_unit_price_cny: string | null; selectable: boolean; reason: string | null; error_code: string | null
  occupied_statement_number: string | null
}
export interface FinanceSourcePage {
  data: FinanceSourceProduct[]; meta: PageMeta; source_revision: string; task: FinanceSourceTask
  salesperson_changes: Array<{ id: string; number: string; salesperson_code_snapshot: string; salesperson_name_snapshot: string }>
}
export interface FinanceStatementLine {
  id: string; production_task_product_id: string; line_number: number; statement_revision: number
  item_number_snapshot: string; product_number_snapshot: string; product_code_snapshot: string
  product_name_snapshot: string; specification_snapshot: string; quantity: string; unit_code: string; unit_name: string
  reference_unit_price_cny: string; unit_price: string; amount: string
}
export interface FinanceStatement {
  id: string; number: string; production_task_id: string; task_number: string; source_order_date: string
  readonly task_order_date: string; readonly task_delivery_date: string
  salesperson: FinancePerson; operator: FinancePerson; created_at: string; updated_at: string
  source_revision: string; statement_revision: number; status: 'ACTIVE' | 'VOID'; amount: string
  settled_amount: string; discount_amount: string; outstanding_amount: string; available_deposit_amount: string; bank_received_amount: string
  settlement_status: 'UNSETTLED' | 'PARTIAL' | 'SETTLED'; can_edit: boolean; can_void: boolean; blocked_reason: string | null
  can_delete: boolean; delete_block_reason: string | null
  etag: string; lines: FinanceStatementLine[]; quantity_totals: Array<{ unit_code: string; unit_name: string; quantity: string }>
  void_reason: string; voided_at: string | null
}
export interface FinanceStatementInput {
  production_task_id: string; source_revision: string; acknowledge_salesperson_change: boolean
  lines: Array<{ production_task_product_id: string; unit_price: string }>
}
export interface FinanceStatementQuery {
  q?: string; task_id?: string; salesperson_id?: string; status?: 'ACTIVE' | 'VOID'
  settlement_status?: 'UNSETTLED' | 'PARTIAL' | 'SETTLED'; page: number; page_size: number
}
export interface FinanceStatementPage { data: FinanceStatement[]; meta: PageMeta }
export interface FinanceSourceTaskPage { data: FinanceSourceTask[]; meta: PageMeta }
