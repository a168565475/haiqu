import type { PageMeta } from './referenceData'

export interface SupplierLedgerOption {
  id: string
  supplier_name: string
  supplier_number: string
}

export interface SupplierLedgerQuery {
  month: string
  supplier_id?: string
  page: number
  page_size: number
}

export interface SupplierLedgerSummary {
  supplier_id: string
  supplier_name: string
  supplier_number: string
  opening_amount: string
  current_amount: string
  paid_amount: string
  offset_amount: string
  closing_amount: string
  unused_prepayment: string
  pending_count: number
}

export interface SupplierLedgerEntry {
  id: string
  entry_kind: 'PAYABLE' | 'PAYMENT' | 'OFFSET'
  type_display: string
  business_date: string
  document_id: string | null
  payable_id: string | null
  number: string
  status: string
  status_display: string
  amount: string | null
  paid_amount: string | null
  offset_amount: string | null
  inbound_date: string | null
  confirmed_date: string | null
  confirmed_by: string
  purchase_order_id: string | null
  purchase_order_number: string
  inbound_id: string | null
  inbound_number: string
  production_task_id: string | null
  production_task_number: string
  material: string
  specification: string
  quantity: string | null
  unit: string
  unit_price: string | null
}

export interface SupplierLedgerSummaryPage {
  data: SupplierLedgerSummary[]
  meta: PageMeta
}

export interface SupplierLedgerEntryPage {
  data: SupplierLedgerEntry[]
  meta: PageMeta & { supplier_name: string }
}

export type SupplierPaymentNature = 'GOODS' | 'PREPAYMENT'
export type SupplierSettlementKind = 'payments' | 'offsets'

interface SupplierSettlementDocument {
  id: string
  number: string
  business_date: string
  status: 'ACTIVE' | 'VOID'
  status_display: string
  supplier_name: string
  recorded_by_name: string
  voided_by_name: string | null
  voided_at: string | null
  void_reason: string
  replaces_id: string | null
  replaces_number: string | null
  replacement_id: string | null
  replacement_number: string | null
}

export interface SupplierPayment extends SupplierSettlementDocument {
  supplier_id: string
  account_id: string
  account_name: string
  nature: SupplierPaymentNature
  nature_display: string
  payee: string
  amount: string
  available_amount: string
  voucher: string
}

export interface SupplierOffset extends SupplierSettlementDocument {
  payment_id: string
  payment_number: string
  allocations: Array<{ payable_id: string; payable_number: string; amount: string }>
}

export type SupplierSettlementDraft =
  | { kind: 'payments'; previous?: SupplierPayment }
  | { kind: 'offsets'; previous?: SupplierOffset }

export interface PaymentAccountOption { id: string; name: string; code: string; etag: string }
export interface SupplierPaymentOptions { suppliers: SupplierLedgerOption[]; accounts: PaymentAccountOption[] }
export interface EligibleSupplierPayment {
  id: string
  number: string
  business_date: string
  supplier_id: string
  supplier_name: string
  nature_display: string
  available_amount: string
  etag: string
}
export interface EligibleSupplierPayable {
  id: string
  number: string
  inbound_date: string
  confirmed_date: string
  amount: string
  available_amount: string
}

export interface CreateSupplierPayment {
  supplier_id: string
  account_id: string
  nature: SupplierPaymentNature
  paid_on: string
  payee: string
  amount: string
  voucher: string
  replaces_id?: string
}

export interface CreateSupplierOffset {
  payment_id: string
  offset_on: string
  allocations: Array<{ payable_id: string; amount: string }>
  replaces_id?: string
}
