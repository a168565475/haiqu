import type { FinanceAccount } from './financeAccounts'
import type { PageMeta } from './referenceData'

export type ReceiptType = 'DEPOSIT' | 'GOODS'
export type ReceiptStatus = 'ACTIVE' | 'VOID'
export interface ReceiptAccountInput {
  account_id: string
  account_etag: string
  cash_amount: string
  fee_amount: string
  received_on: string
}
export interface ReceiptAccountDraft extends ReceiptAccountInput {
  key: string
  account: FinanceAccount
}
export interface DepositReceiptInput {
  receipt_type: 'DEPOSIT'
  statement_id: string
  account_lines: ReceiptAccountInput[]
  upload_ids: string[]
}
export interface ReceiptDepositAllocationInput {
  deposit_id: string
  amount: string
}
export interface GoodsReceiptInput {
  receipt_type: 'GOODS'
  statement_id: string
  account_lines: ReceiptAccountInput[]
  deposit_allocations: ReceiptDepositAllocationInput[]
  discount_amount: string
  upload_ids: string[]
}
export type ReceiptInput = DepositReceiptInput | GoodsReceiptInput
export interface ReceiptFile {
  file_id: string
  original_name: string
  size_bytes: number
  scan_status: 'PENDING' | 'CLEAN' | 'INFECTED' | 'FAILED' | 'SKIPPED'
  scan_label: string
}
export interface ReceiptUpload extends ReceiptFile {
  id: string
  statement_id: string
  upload_key: string
  status: 'UNBOUND' | 'BOUND' | 'DISCARD_PENDING' | 'DISCARDED'
  created_at: string
}
export interface ReceiptAccountLine extends Omit<ReceiptAccountInput, 'account_etag'> {
  id: string
  line_number: number
  account_snapshot: Pick<FinanceAccount, 'account_type' | 'code' | 'category' | 'name' | 'account_number' | 'status' | 'currency_id' | 'currency_code'>
}
export interface ReceiptAllocation {
  id: string
  deposit_receipt_id: string
  deposit_number: string
  amount: string
  is_active: boolean
}
export interface Receipt {
  id: string
  number: string
  receipt_type: ReceiptType
  status: ReceiptStatus
  statement_id: string
  statement_snapshot: {
    number: string; production_task_id: string; task_number: string
    salesperson_id: string; salesperson_code: string; salesperson_name: string
    source_order_date: string; amount: string; outstanding_before: string; outstanding_after: string
  }
  cash_amount: string
  fee_amount: string
  deposit_amount: string
  allocated_deposit_amount: string
  discount_amount: string
  settled_amount: string
  outstanding_before: string
  outstanding_after: string
  account_lines: ReceiptAccountLine[]
  attachments: ReceiptFile[]
  inherited_attachments: (ReceiptFile & { deposit_receipt_id: string; deposit_number: string })[]
  allocations: ReceiptAllocation[]
  operator: { id: string; code: string; name: string }
  created_at: string
  updated_at: string
  etag: string
  statement_etag: string
  can_void: boolean
  can_delete: boolean
  delete_block_reason: string | null
  blocked_reason: string | null
  void_reason: string
  voided_at: string | null
}
export interface ReceiptQuery { q?: string; receipt_type?: ReceiptType; status?: ReceiptStatus; statement_id?: string; page: number; page_size: number }
export interface ReceiptPage { data: Receipt[]; meta: PageMeta }
export interface ReceiptAccountPage { data: FinanceAccount[]; meta: PageMeta }
export interface ReceiptDepositOption {
  id: string; number: string; status: ReceiptStatus; received_on: string | null; created_at: string
  deposit_amount: string; available_amount: string; can_select: boolean; blocked_reason: string | null
  allocated_goods_id: string | null; allocated_goods_number: string | null; attachments: ReceiptFile[]
}
export interface ReceiptDepositPage {
  data: ReceiptDepositOption[]; meta: PageMeta; statement_etag: string
  outstanding_amount: string; available_deposit_amount: string
}

// U05 货款表单由公共窗口传入来源；金额与附件均沿用 U04 公共结构。
export interface ReceiptStatementContext {
  id: string; number: string; etag: string; task_number: string
  amount: string; outstanding_amount: string; available_deposit_amount: string
  bank_received_amount: string; settled_amount: string; discount_amount: string
}
