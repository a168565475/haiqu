import type { PageMeta } from './referenceData'
import type { SupplierPayment } from './financeSupplierLedger'

export interface SupplierPaymentRecord extends SupplierPayment {
  application_id: string | null
  application_number: string | null
}

export interface SupplierPaymentApplicationRow {
  id: string
  number: string
  applied_on: string
  supplier_id: string
  supplier_name: string
  payee: string
  amount: string
  paid_amount: string
  remaining_amount: string
  recorded_by_name: string
  withdrawn_at: string | null
}

export interface SupplierPaymentApplicationDetail extends SupplierPaymentApplicationRow {
  department_name: string
  note: string
  withdrawal_reason: string
  lines: Array<{
    payable_id: string
    payable_number: string
    inbound_date: string
    month: string
    confirmed_amount: string
    offset_amount: string
    amount: string
    released_amount: string
  }>
  payments: Array<{ id: string; number: string; business_date: string; amount: string }>
}

export type SupplierPaymentApplicationContext = Pick<SupplierPaymentApplicationRow,
  'id' | 'number' | 'supplier_id' | 'payee' | 'remaining_amount'>

export interface ApplicationPayable {
  id: string
  number: string
  inbound_date: string
  confirmed_amount: string
  offset_amount: string
  current_balance: string
  occupied_amount: string
  requestable_amount: string
  payment_term_months: number | null
  due_month: string | null
}

export interface SupplierDuePayable extends ApplicationPayable {
  receipt_month: string
}

export interface SupplierDuePayableSummary {
  supplier_id: string
  supplier_name: string
  overdue_amount: string
  current_due_amount: string
  due_total: string
}

export interface ApplicationPayableMonth {
  month: string
  current_balance: string
  occupied_amount: string
  requestable_amount: string
  payables: ApplicationPayable[]
}

export interface CreateSupplierPaymentApplication {
  supplier_id: string
  applied_on: string
  payee: string
  note: string
  lines: Array<{ payable_id: string; amount: string }>
}

export interface SupplierPaymentPage<T> {
  data: T[]
  meta: PageMeta
}
