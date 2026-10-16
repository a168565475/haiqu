import type { CustomerEmployeeSummary, PageMeta } from './customer'

export interface QuotationCurrentVersion {
  id: string
  version_number: number
  status: string
  currency_code: string
  total_amount: string
  valid_until: string | null
  incoterm_label: string
  updated_at: string
}

export interface QuotationListItem {
  id: string
  quotation_number: string
  customer_name: string
  owner: CustomerEmployeeSummary | null
  outcome_status: string
  outcome_status_display: string
  accepted_version: string | null
  subject: string
  current_version: QuotationCurrentVersion | null
  display_status: string
  display_status_label: string
  allowed_actions: { view: boolean; edit: boolean; create_version: boolean }
  created_at: string
  updated_at: string
}

export interface QuotationSummary {
  all: number
  draft: number
  ready_to_send: number
  sent: number
  accepted: number
  expiring_within_7_days: number
}

export interface QuotationOptionItem { value: string; label: string }

export interface QuotationListOptions {
  outcome_statuses: QuotationOptionItem[]
  display_statuses: QuotationOptionItem[]
  currencies: QuotationOptionItem[]
  owners: Array<{ id: string; employee_code: string; display_name: string }>
}

export interface QuotationListQuery {
  page: number
  page_size: number
  q?: string
  customer_id?: string
  owner_employee_id?: string
  display_status?: string
  currency_code?: string
  valid_from?: string
  valid_to?: string
  ordering?: string
}

export interface QuotationListResult {
  data: QuotationListItem[]
  meta: PageMeta
}

export interface QuotationLine {
  id: string
  lineage_id: string
  line_number: number
  product_description_snapshot: string
  specification_snapshot: string
  product_specification?: string | null
  color_snapshot?: string | null
  material_snapshot?: string
  product_number_snapshot?: string
  product_code_snapshot?: string
  item_number_snapshot?: string
  quantity: string
  unit_code: string
  source_inquiry_item?: string | null
  product_id?: string | null
  product_category_id?: string | null
  product_unit_id?: string | null
  product_color_id?: string | null
  unit_price: string | null
  discount_rate: string
  line_total: string | null
  price_status?: 'PENDING' | 'READY'
  notes: string
  packaging?: QuotationLinePackaging | null
  container_tiers?: QuotationContainerTier[]
  product_image?: { id: string; original_name: string; scan_status: string } | null
  basis_prices?: QuotationLinePrice[]
}

export interface QuotationLinePrice {
  id: string
  quotation_line_id: string
  price_basis_id: string
  unit_price: string
  surcharge_note: string
  is_manual_override: boolean
  override_reason: string
}

export interface QuotationPriceBasis {
  id: string
  label: string
  incoterm_code: string
  named_place: string
  currency_code: string
  is_default: boolean
  sort_order: number
  notes: string
  line_prices: QuotationLinePrice[]
}

export interface QuotationPriceBasisPayload {
  label: string
  incoterm_code: string
  named_place: string
  currency_code: string
  is_default: boolean
  notes?: string
  line_prices: Array<{
    quotation_line_id: string
    unit_price: string
    surcharge_note?: string
    is_manual_override?: boolean
    override_reason?: string
  }>
}

export interface QuotationLinePackaging {
  id: string
  length_cm: string
  width_cm: string
  height_cm: string
  pieces_per_carton: number
  carton_count: number
  gross_weight_kg: string | null
  net_weight_kg: string | null
  carton_cbm: string
  total_cbm: string
}

export interface QuotationContainerConfig {
  id: string
  container_type_code: string
  config_version: number
  effective_volume_cbm: string
  default_load_factor: string
}

export interface QuotationContainerTier {
  id: string
  tier_number: number
  container_config: QuotationContainerConfig | null
  container_type_code: string
  effective_volume_cbm: string
  load_factor: string
  auto_carton_count: number
  auto_quantity: string
  manual_carton_count: number | null
  override_reason: string
  final_quantity: string
  unit_price: string
}

export interface QuotationLinePayload {
  product_description_snapshot: string
  specification_snapshot?: string
  color_snapshot?: string
  material_snapshot?: string
  product_id?: string | null
  product_category_id?: string | null
  product_unit_id?: string | null
  product_color_id?: string | null
  quantity: string
  unit_code: string
  unit_price: string
  discount_rate?: string
  notes?: string
}

export interface QuotationVersionDetail extends QuotationCurrentVersion {
  quotation: string
  quotation_template: string | null
  parent_version: string | null
  status_display: string
  language_code: string
  subtotal_amount: string
  discount_amount: string
  tax_amount: string
  notes: string
  created_at: string
  issued_at: string | null
  terms_snapshot: Record<string, unknown>
  template_code: string | null
  template_name: string | null
  template_version: number | null
  template_config: Record<string, unknown> | null
  template_snapshot: {
    template_code?: string
    template_name?: string
    template_version?: number
    template_config?: Record<string, unknown>
  }
  customer_requirement_snapshot?: Record<string, unknown>
  transaction_entity_snapshot: { legal_name?: string }
  address_snapshot: Record<string, unknown>
  contact_snapshot: Record<string, unknown>
  lines: QuotationLine[]
  dispatches: QuotationDispatchRecord[]
  price_bases: QuotationPriceBasis[]
  documents: QuotationDocument[]
  payment_breakdown: {
    deposit_percent: string
    balance_percent: string
    deposit_amount: string
    balance_amount: string
  } | null
}

export interface QuotationTemplate {
  id: string
  template_code: string
  template_name: string
  template_version: number
  requires_approval: boolean
  template_config: Record<string, unknown>
}

export interface QuotationTemplateSellerProfile {
  company_name: string
  contact_person: string
  phone: string
  fax: string
  skype: string
  qq: string
  wechat: string
  whatsapp: string
  address: string
  email: string
  facebook: string
  website: string
}

export interface QuotationDocument {
  id: string
  file_id: string
  original_name: string
  content_type: string
  size_bytes: number
  document_type: string
  is_formal: boolean
  snapshot_hash: string
}

export interface QuotationDispatchRecord {
  id: string
  channel: string
  dispatched_at: string
  is_simulated: boolean
  recipient_snapshot?: Record<string, unknown>
  price_basis_id?: string | null
  evidence_file_id?: string | null
  external_reference?: string
  notes?: string
}

export type QuotationEmailAttemptStatus = 'PROCESSING' | 'ACCEPTED' | 'FAILED' | 'UNCERTAIN'

export interface QuotationEmailDispatchAttempt {
  id: string
  quotation_version_id: string
  price_basis_id: string
  quotation_document_id: string
  idempotency_key: string
  status: QuotationEmailAttemptStatus
  status_display: string
  recipient: string
  cc_snapshot: string[]
  subject: string
  body_html: string
  recipient_snapshot: Record<string, unknown>
  attachment_snapshot: {
    document_id?: string
    business_file_id?: string
    filename?: string
    content_type?: string
    size_bytes?: number
    content_hash?: string
  }
  follow_up_due_at: string | null
  error_message: string
  dispatch_record_id: string | null
  requested_by: CustomerEmployeeSummary | null
  resolved_by: CustomerEmployeeSummary | null
  resolved_at: string | null
  resolution_note: string
  created_at: string
  updated_at: string
}

export interface QuotationAcceptance {
  id: string
  quotation_version_id: string
  price_basis_id: string
  customer_contact_id: string | null
  accepted_at: string
  source: 'EMAIL' | 'PHONE' | 'MEETING' | 'OTHER'
  note: string
}

export interface QuotationVersionDiffChange {
  section: string
  field: string
  before: string
  after: string
}

export interface QuotationVersionDiff {
  base_version: string | null
  compare_version: string
  changes: QuotationVersionDiffChange[]
}

export interface QuotationDetail extends QuotationListItem {
  customer_account: string
  transaction_entity: string
  source_inquiry: string | null
  source_inquiry_number?: string | null
  versions: Array<Omit<QuotationVersionDetail, 'lines' | 'terms_snapshot' | 'notes'>>
  acceptance?: QuotationAcceptance | null
}

export interface VersionResponse { data: QuotationVersionDetail; etag: string }
export interface QuotationEmailDispatchResponse extends VersionResponse { emailAttempt: QuotationEmailDispatchAttempt }
export interface QuotationResponse { data: QuotationDetail; etag: string }
export interface QuotationTemplateResponse { data: QuotationTemplate; etag: string }

export interface QuotationCreatePayload {
  customer_account_id: string
  transaction_entity_id: string
  owner_employee_id: string
  subject: string
  source_inquiry_id?: string | null
}

export interface QuotationCreationOption {
  id: string
  account_code: string
  account_name: string
  entities: Array<{ id: string; entity_code: string; legal_name: string }>
}

export interface InquiryQuotationContext {
  inquiry: { id: string; inquiry_number: string; subject: string; status: string; status_label: string; customer_id: string; customer_name: string; owner_name: string; items: Array<{ id: string; product_description: string; specification: string; quantity: string; unit_code: string; target_currency_code: string }> }
  preflight: Array<{ code: string; label: string; passed: boolean }>
  entities: Array<{ id: string; entity_code: string; legal_name: string; registration_country_code: string }>
  requires_entity: boolean
  can_create_entity: boolean
  default_subject: string
  default_currency_code: string
  existing_quotations: Array<{ id: string; quotation_number: string; subject: string; status: string }>
  allowed: { create_quote: boolean }
}

export interface InquiryQuotationCreatePayload {
  inquiry_id: string
  transaction_entity_id?: string | null
  transaction_entity?: { legal_name: string; registration_country_code: string }
  subject: string
  currency_code: string
  due_at: string
  idempotency_key: string
  create_another?: boolean
}

export interface QuotationPriceHistoryRecord {
  quotation_id: string
  version_id: string
  date: string
  version_number: number
  customer_id: string
  customer_name: string
  product: string
  container_types: string[]
  quantity: string
  unit_code: string
  unit_price: string
  currency_code: string
  incoterm: string
  status: string
  status_label: string
}

export interface QuotationPriceHistory {
  source_label: string
  calculation_warning: string
  unit_codes: string[]
  filters: { customers: QuotationOptionItem[]; products: QuotationOptionItem[]; container_types: QuotationOptionItem[]; currencies: QuotationOptionItem[]; periods: Array<{ value: number; label: string }> }
  metrics: { latest_quote_price: string | null; minimum_quote_price: string | null; average_quote_price: string | null; price_volatility_percent: string | null }
  series: Array<{ name: string; points: Array<{ date: string; unit_price: string }> }>
  records: QuotationPriceHistoryRecord[]
}
