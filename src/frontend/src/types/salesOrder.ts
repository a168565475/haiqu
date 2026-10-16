import type { PageMeta } from './customer'

export type SalesOrderSource = 'QUOTATION' | 'DIRECT' | 'REPEAT'
export type SalesOrderStatus = 'DRAFT' | 'CONFIRMED' | 'FULFILLING' | 'COMPLETED' | 'PAUSED' | 'CANCELLED'

export interface SelectOption { value: string; label: string }
export interface EmployeeOption { id: string; employee_code: string; display_name: string }
export interface SalesOrderCustomer { id: string; account_code: string; account_name: string }
export interface SalesOrderEntity { id: string; customer_account_id: string; entity_code: string; legal_name: string }
export interface SalesOrderAddress {
  id: string
  transaction_entity_id: string
  address_code: string
  label: string
  country_code: string
  state_province: string
  city: string
  postal_code: string
  address_line1: string
  address_line2: string
  recipient_name: string
  recipient_phone: string
  is_verified: boolean
}
export interface SalesOrderSellerTemplate {
  id: string
  template_code: string
  template_name: string
  template_version: number
  template_config: Record<string, unknown>
}
export interface SalesOrderProduct {
  id: string
  product_number: string
  product_code: string
  item_number?: string
  unit_id?: string
  product_name: string
  specification: string
  unit_code: string
  unit_name?: string
  category_id?: string
  category_name?: string
}
export interface AcceptedQuotationVersion {
  id: string
  quotation_id: string
  quotation_number: string
  version_number: number
  customer_account_id: string
  customer_name: string
  currency_code: string
}
export interface SalesOrderOptions {
  source_types: SelectOption[]
  statuses: SelectOption[]
  confirmation_methods: SelectOption[]
  customers: SalesOrderCustomer[]
  transaction_entities: SalesOrderEntity[]
  buyer_addresses: SalesOrderAddress[]
  employees: EmployeeOption[]
  products: SalesOrderProduct[]
  currencies: Array<{ id: string; code: string; name: string; symbol: string }>
  accepted_quotation_versions: AcceptedQuotationVersion[]
  seller_template: SalesOrderSellerTemplate | null
}

export interface QuotationOrderLineOption {
  id: string
  line_number: number
  product_description: string
  specification: string
  specification_display?: string
  color: string
  product_id: string | null
  product_category_id: string | null
  product_unit_id: string | null
  product_color_id: string | null
  product_image_id: string | null
  product_number: string
  product_code: string
  item_number: string
  material: string
  quantity: string
  converted_quantity: string
  reserved_quantity: string
  remaining_quantity: string
  unit_code: string
  quoted_unit_price: string | null
  suggested_product_id: string | null
  suggested_product: SalesOrderProduct | null
  product_mapping_status: 'MATCHED' | 'AMBIGUOUS' | 'UNMATCHED'
  product_mapping_candidate_count: number
}
export interface QuotationOrderContext {
  quotation_id: string
  quotation_number: string
  quotation_version_id: string
  version_number: number
  customer_account_id: string
  customer_name: string
  transaction_entity_id: string | null
  salesperson_id: string
  currency_code: string
  buyer_snapshot: Record<string, unknown>
  buyer_address_id: string | null
  buyer_address_snapshot: Record<string, unknown>
  seller_snapshot: Record<string, unknown>
  seller_template_id: string | null
  terms_snapshot: Record<string, unknown>
  customer_requirement_snapshot: Record<string, unknown>
  lines: QuotationOrderLineOption[]
}

export interface PriceException {
  id: string
  requested_unit_price: string
  quoted_unit_price_snapshot: string
  reason: string
  status: 'PENDING' | 'APPROVED' | 'REJECTED'
  status_display: string
  requested_by: EmployeeOption | null
  decided_by: EmployeeOption | null
  decided_at: string | null
  decision_note: string
}
export interface SalesOrderLine {
  id: string
  line_number: number
  source_quotation_line_id: string | null
  product_id: string | null
  product_category_id?: string | null
  product_unit_id?: string | null
  product_color_id?: string | null
  product_image_id?: string | null
  customer_product_name_snapshot: string
  customer_specification_snapshot: string
  customer_color_snapshot: string
  product_number_snapshot: string
  product_code_snapshot: string
  product_name_snapshot: string
  specification_snapshot: string
  item_number_snapshot: string
  material_snapshot: string
  unit_code_snapshot: string
  quantity: string
  quoted_quantity_snapshot: string | null
  quoted_unit_price: string | null
  unit_price: string
  line_total: string
  unit_price_cny?: string | null
  line_total_cny?: string | null
  specification_display?: string
  price_difference: string
  price_difference_rate: string | null
  lower_price_reason: string
  quality_requirements: string
  packaging_requirements: string
  shipping_mark_requirements: string
  price_exceptions: PriceException[]
}
export interface ProductionSummary {
  status: string
  status_display: string
  planned_quantity: string
  good_quantity: string
  gap_quantity: string
  orders: Array<{
    id: string
    task_number: string
    status: string
    status_display: string
    planned_start_date: string | null
    planned_end_date: string | null
    actual_good_quantity: string
  }>
}
export interface ProcurementSummary {
  bom_confirmed: boolean
  request_progress: string
  key_material_eta: string | null
  risk: string
}
export interface SalesOrderBatchLine {
  id: string
  sales_order_line_id: string
  product_name: string
  product_number: string
  unit_code: string
  quantity: string
  allocated_quantity: string
  maximum_quantity: string
  remaining_quantity: string
}
export interface SalesOrderDeliveryBatch {
  id: string
  line_number: number
  batch_number: string
  planned_delivery_date: string
  status: 'ACTIVE' | 'CANCELLED'
  status_display: string
  cancellation_reason: string
  notes: string
  lines: SalesOrderBatchLine[]
  production_summary: ProductionSummary
  procurement_summary: ProcurementSummary
}
export interface CollaborationEvent {
  id: string
  delivery_batch_id: string | null
  event_type: string
  event_type_display: string
  source_type_display: string
  status: string
  status_display: string
  title: string
  note: string
  quantity: string | null
  occurred_at: string
  evidence_file_id: string | null
  evidence_file_name: string | null
  recorded_by: EmployeeOption | null
}
export interface SalesOrderListItem {
  id: string
  order_number: string
  version_number: number
  source_type: SalesOrderSource
  source_type_display: string
  status: SalesOrderStatus
  status_display: string
  customer_code: string
  customer_name: string
  customer_po_number: string
  contract_number: string
  order_date: string
  currency_code: string
  total_amount: string
  total_amount_cny?: string | null
  salesperson: EmployeeOption
  merchandiser: EmployeeOption | null
  has_remaining_production_capacity?: boolean
  line_count: number
  delivery_batch_count: number
  next_delivery_date: string | null
  confirmed_at: string | null
  updated_at: string
}
export interface SalesOrder extends SalesOrderListItem {
  source_quotation_version_id: string | null
  source_quotation_number: string | null
  transaction_entity_id: string | null
  transaction_entity_name: string | null
  buyer_address_id: string | null
  buyer_address_snapshot: Record<string, unknown>
  direct_order_reason: string
  exchange_rate: string
  exchange_rate_record_id?: string | null
  exchange_rate_snapshot?: SalesOrderExchangeRateSnapshot | null
  incoterm_code: string
  payment_terms: string
  deposit_required: boolean
  includes_tax: boolean
  tax_basis: string
  order_tolerance_percent: string
  preproduction_sample_required: boolean
  buyer_snapshot: Record<string, unknown>
  seller_snapshot: Record<string, unknown>
  terms_snapshot: Record<string, unknown>
  customer_requirement_snapshot: Record<string, unknown>
  confirmation_method: string
  confirmation_method_display: string
  customer_confirmer: string
  customer_confirmed_at: string | null
  confirmation_summary: string
  lines: SalesOrderLine[]
  delivery_batches: SalesOrderDeliveryBatch[]
  evidence: Array<{ id: string; file_id: string; file_name: string; evidence_type: string; caption: string }>
  collaboration_events: CollaborationEvent[]
  versions: Array<{
    id: string
    version_number: number
    snapshot: Record<string, unknown>
    change_reason: string
    confirmed_by: EmployeeOption | null
    confirmed_at: string | null
    change_control: Record<string, unknown>
  }>
  has_production_orders: boolean
}
export interface PaginatedSalesOrders { data: SalesOrderListItem[]; meta: PageMeta }
export interface VersionedSalesOrder { data: SalesOrder; etag: string }

export interface SalesOrderLineInput {
  client_key: string
  source_quotation_line_id: string | null
  product_id: string | null
  /** 规格下拉的内部选择值，不提交给后端。 */
  product_selection_id?: string | null
  customer_product_name_snapshot: string
  customer_specification_snapshot: string
  specification_display?: string
  customer_color_snapshot: string
  product_category_id?: string | null
  product_unit_id?: string | null
  product_color_id?: string | null
  product_image_id?: string | null
  unit_code?: string
  material?: string
  product_number_snapshot?: string
  product_code_snapshot?: string
  item_number_snapshot?: string
  product_name_input?: string
  quantity: string
  unit_price: string
  lower_price_reason: string
  quality_requirements: string
  packaging_requirements: string
  shipping_mark_requirements: string
}
export interface SalesOrderBatchInput {
  client_key?: string
  planned_delivery_date: string
  notes: string
  lines: Array<{ sales_order_line_client_key: string; quantity: string }>
}

export interface ConfirmedSalesOrderChangeInput {
  order: SalesOrderInput
  change_reason: string
  customer_facing_change: boolean
  change_evidence_file_id: string | null
  pmc_impact_confirmed: boolean
}
export interface SalesOrderInput {
  source_type: SalesOrderSource
  source_quotation_version_id: string | null
  customer_account_id: string
  transaction_entity_id: string | null
  buyer_address_id: string | null
  salesperson_id: string
  merchandiser_id: string | null
  customer_po_number: string
  contract_number: string
  order_date: string
  direct_order_reason: string
  currency_code: string
  exchange_rate: string
  exchange_rate_record_id?: string | null
  incoterm_code: string
  payment_terms: string
  deposit_required: boolean
  includes_tax: boolean
  tax_basis: string
  order_tolerance_percent: string
  preproduction_sample_required: boolean
  buyer_snapshot: Record<string, unknown>
  buyer_address_snapshot: Record<string, unknown>
  seller_snapshot: Record<string, unknown>
  terms_snapshot: Record<string, unknown>
  customer_requirement_snapshot: Record<string, unknown>
  confirmation_method: string
  customer_confirmer: string
  customer_confirmed_at: string | null
  confirmation_summary: string
  evidence_file_ids: string[]
  lines: SalesOrderLineInput[]
  delivery_batches: SalesOrderBatchInput[]
}

export interface SalesOrderExchangeRateSnapshot {
  record_id: string | null
  base_currency_code: string
  quote_currency_code: string
  rate: string
  effective_date: string
  source_name: string
  source_version: string
  captured_at?: string
  capture_reason?: string
}
export interface SalesOrderExchangeRatePreview {
  exchange_rate_record_id: string | null
  exchange_rate: string
  exchange_rate_snapshot: SalesOrderExchangeRateSnapshot
}
