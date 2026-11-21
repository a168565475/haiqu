import type { PageMeta } from './referenceData'

export type PurchasePayableStatus = 'WAITING_PRICE' | 'WAITING_FINANCE_CONFIRM' | 'WAITING_PAYMENT' | 'VOID'

export interface PurchasePayablePerson {
  id: string
  code?: string
  name: string
}

export interface PurchasePayableLine {
  id?: string
  line_id: string
  inbound_line_id?: string
  material_inbound_line_id?: string
  purchase_order_line_id?: string | null
  purchase_order_number?: string
  inbound_number?: string
  supplier_number?: string
  supplier_name?: string
  material?: string
  material_snapshot?: string
  specification?: string
  specification_snapshot?: string
  part_name?: string
  part_name_snapshot?: string
  material_attributes?: Record<string, unknown>
  material_attributes_snapshot?: Record<string, unknown>
  accepted_quantity: string
  settlement_quantity?: string
  accepted_unit?: string
  source_unit_text_snapshot?: string
  accepted_bar_count?: number | null
  receipt_bar_counts?: { received: number; returned: number } | null
  received_quantity?: string | null
  return_quantity?: string | null
  received_weight_kg?: string | null
  accepted_weight_kg?: string | null
  return_weight_kg?: string | null
  reference_unit_price?: string | null
  reference_amount?: string | null
  unit_price: string | null
  price_unit?: string | null
  price_unit_text?: string
  currency_code?: string | null
  currency_code_snapshot?: string | null
  amount: string | null
  price_source: string | null
  price_confirmation_remark?: string
  price_remark?: string
  price_confirmed_by?: PurchasePayablePerson | null
  price_confirmed_by_name?: string
  price_confirmed_at: string | null
  tax_mode?: string | null
  freight_mode?: string | null
  blocked_reason?: string | null
}

export interface PurchasePayable {
  id: string
  number: string
  status: PurchasePayableStatus
  status_display?: string
  supplier?: PurchasePayablePerson | null
  supplier_number?: string
  supplier_name?: string
  supplier_number_snapshot?: string
  supplier_name_snapshot?: string
  purchase_order_id?: string | null
  purchase_order_number?: string
  purchase_order_number_snapshot?: string
  material_inbound_id?: string
  inbound_id?: string
  inbound_number?: string
  inbound_number_snapshot?: string
  inbound_date?: string
  currency_code?: string | null
  currency_code_snapshot?: string | null
  amount: string | null
  price_complete: boolean
  tax_mode: string | null
  freight_mode: string | null
  blocked_reason: string | null
  created_at: string
  updated_at: string
  confirmed_at: string | null
  confirmed_by: PurchasePayablePerson | null
  void_reason?: string
  voided_at: string | null
  etag: string
  can_price: boolean
  can_confirm: boolean
  can_void: boolean
  lines: PurchasePayableLine[]
}

export interface PurchasePayableQuery {
  q?: string
  status?: PurchasePayableStatus
  supplier_id?: string
  inbound_date_from?: string
  inbound_date_to?: string
  page: number
  page_size: number
}

export interface PurchasePayablePage {
  data: PurchasePayable[]
  meta: PageMeta
}

export interface PurchasePayablePricingInput {
  tax_mode?: string | null
  freight_mode?: string | null
  lines: Array<{
    line_id: string
    unit_price: string
    price_unit_text: string
    price_source?: string
    price_confirmed_by_name?: string
    price_remark?: string
  }>
}
