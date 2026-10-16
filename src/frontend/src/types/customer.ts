export type CustomerLifecycleStage =
  | 'LEAD'
  | 'VERIFIED'
  | 'OPPORTUNITY'
  | 'CUSTOMER'
  | 'LOST'

export type CustomerActivityStatus =
  | 'INSUFFICIENT_DATA'
  | 'ACTIVE'
  | 'FOLLOW_UP'
  | 'HIGH_RISK'
  | 'DORMANT'

export type CustomerActivitySource = 'MANUAL' | 'SYSTEM'
export type CustomerBusinessSnapshotSource = 'MANUAL' | 'ERP'
export type CustomerContactMethodType =
  | 'EMAIL'
  | 'PHONE'
  | 'MOBILE'
  | 'WECHAT'
  | 'WHATSAPP'
  | 'OTHER'

export type CustomerOrdering =
  | 'account_code'
  | '-account_code'
  | 'account_name'
  | '-account_name'
  | 'created_at'
  | '-created_at'
  | 'updated_at'
  | '-updated_at'

export type ArchivedFilter = 'false' | 'true' | 'all'
export type DecimalInput = string | number

export interface ApiDataResponse<T> {
  data: T
}

export interface PageMeta {
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface PaginatedResponse<T> {
  data: T[]
  meta: PageMeta
}

export interface CursorMeta {
  next: string | null
  previous: string | null
  page_size: number
}

export interface CursorPaginatedResponse<T> {
  data: T[]
  meta: CursorMeta
}

export interface VersionedCustomer<T> {
  data: T
  etag: string | null
}

export interface ApiErrorEnvelope {
  error: {
    code: string
    message: string
    field_errors?: Record<string, string[]>
    request_id?: string
  }
}

export interface CustomerEmployeeSummary {
  id: string
  employee_code: string
  display_name: string
  status: string
}

export interface CustomerOwnerOption {
  id: string
  employee_code: string
  display_name: string
  email: string
}

export interface CustomerCodeOption {
  item_code: string
  display_name: string
}

export interface CustomerDictionaryOption extends CustomerCodeOption {
  id: string
  description: string
  disabled?: boolean
}

export interface CustomerRegionOption {
  id: string
  legacy_selector_code: string
  legacy_tree_code: string
  region_name: string
  parent_id?: string
  country_code?: string
}

export interface CustomerRegionSummary {
  id: string
  legacy_selector_code: string
  legacy_tree_code: string
  region_name: string
  level: 1 | 2
}

export interface CustomerProfileDictionarySummary {
  id: string
  item_code: string
  display_name: string
}

export interface CustomerInterestedProduct {
  id: string
  product_item_id: string
  item_code: string
  display_name: string
}

export interface CustomerCompanyContactMethod {
  id: string
  method_type: 'EMAIL' | 'PHONE' | 'SKYPE'
  method_type_display: string
  raw_value: string
  is_primary: boolean
}

export interface CustomerTagOption {
  id: string
  tag_code: string
  tag_name: string
  color: string
}

export interface CustomerTagCreateInput {
  tag_name: string
  color?: string
}

export interface CustomerEffectiveSummary {
  id: string
  item_code: string
  display_name: string
  reason: string
  effective_from: string
  effective_to: string | null
}

export interface CustomerSourceSummary {
  id: string
  item_code: string
  display_name: string
  notes: string
  effective_from: string
  effective_to: string | null
}

export interface CustomerTagSummary {
  id: string
  tag_code: string
  tag_name: string
  color: string
}

export interface CustomerActivitySummary {
  id: string
  activity_status: CustomerActivityStatus
  display_name: string
  source_type: CustomerActivitySource
  reason: string
  formula_version: string
  effective_from: string
  effective_to: string | null
}

export interface CustomerAssignment {
  id: string
  employee: CustomerEmployeeSummary
  assignment_role: string
  effective_from: string
  effective_to: string | null
  reason: string
  created_at: string
}

export interface CustomerBusinessSnapshot {
  id: string
  source_type: CustomerBusinessSnapshotSource
  source_type_display: string
  source_reference: string
  as_of_at: string
  currency_code: string
  customer_total_value: string | null
  last_12m_order_amount: string | null
  last_12m_order_count: number | null
  quote_conversion_rate: string | null
  credit_limit: string | null
  credit_used: string | null
  open_complaint_count: number | null
  notes: string
  entered_by: CustomerEmployeeSummary
  is_current: boolean
  created_at: string
}

export interface CustomerListItem {
  id: string
  account_code: string
  account_name: string
  english_name: string
  short_name: string
  lifecycle_stage: CustomerLifecycleStage
  lifecycle_stage_display: string
  primary_country_code: string
  primary_region: CustomerRegionSummary | null
  secondary_region: CustomerRegionSummary | null
  industry: CustomerProfileDictionarySummary | null
  inquiry_keywords: string
  recorded_by: CustomerEmployeeSummary | null
  recorded_at: string | null
  primary_owner: CustomerEmployeeSummary | null
  attention_level: CustomerEffectiveSummary | null
  customer_grade: CustomerEffectiveSummary | null
  first_source: CustomerSourceSummary | null
  latest_source: CustomerSourceSummary | null
  customer_types: CustomerEffectiveSummary[]
  customer_tags: CustomerTagSummary[]
  activity: CustomerActivitySummary | null
  last_contact_at: string | null
  next_follow_up_at: string | null
  customer_value: CustomerBusinessSnapshot | null
  lifetime_sales_amount: string | null
  lifetime_sales_order_count: number | null
  last_12m_sales_amount: string | null
  last_12m_sales_order_count: number | null
  quotation_conversion_rate: string | null
  recent_order: CustomerRecentOrder | null
  archived_at: string | null
  created_at: string
  updated_at: string
}

export interface CustomerRecentOrder {
  id: string
  order_number: string
  order_date: string
  status: string
  status_display: string
  currency_code: string
  total_amount: string
}

export interface CustomerDetail extends CustomerListItem {
  primary_website_url: string
  source_system: string
  external_id: string
  notes: string
  legacy_source_data: LegacySourceData
  archive_reason: string
  current_assignments: CustomerAssignment[]
  business_snapshot: CustomerBusinessSnapshot | null
  interested_products: CustomerInterestedProduct[]
  company_contact_methods: CustomerCompanyContactMethod[]
}

export interface LegacySourceData {
  source_system?: string
  source_row?: number
  fields?: Record<string, string | number | boolean | null>
}

export interface CustomerListQuery {
  q?: string
  lifecycle_stage?: CustomerLifecycleStage
  country_code?: string
  owner_id?: string
  organization_id?: string
  attention_level?: string
  customer_grade?: string
  customer_source?: string
  customer_type?: string
  customer_tag?: string
  activity_status?: CustomerActivityStatus
  updated_from?: string
  updated_to?: string
  archived?: ArchivedFilter
  ordering?: CustomerOrdering
  page?: number
  page_size?: number
}

export interface CustomerOptionsQuery {
  q?: string
}

export interface CustomerOptions {
  lifecycle_stages: CustomerCodeOption[]
  activity_statuses: CustomerCodeOption[]
  customer_grades: CustomerDictionaryOption[]
  customer_types: CustomerDictionaryOption[]
  customer_sources: CustomerDictionaryOption[]
  industries: CustomerDictionaryOption[]
  interested_products: CustomerDictionaryOption[]
  primary_regions: CustomerRegionOption[]
  secondary_regions: CustomerRegionOption[]
  customer_tags: CustomerTagOption[]
  owner_options: CustomerOwnerOption[]
  country_options: CustomerDictionaryOption[]
}

export interface CustomerStats {
  total: number
  mine: number
  today_follow_up: number
  high_value: number
  high_risk: number
  dormant: number
  high_value_definition: 'CURRENT_GRADE_A'
}

export interface CustomerTransferInput {
  customer_id: string
  to_employee_id: string
  reason: string
}

interface CustomerDuplicateCheckBase {
  country_code?: string
  exclude_customer_id?: string
}

export type CustomerDuplicateCheckQuery = CustomerDuplicateCheckBase &
  (
    | { name: string; website?: string }
    | { name?: string; website: string }
  )

export interface CustomerDuplicateMatch {
  customer_id: string
  account_code: string
  account_name: string
  primary_country_code: string
  primary_website_url: string
  lifecycle_stage: CustomerLifecycleStage
  match_score: number
  match_level: 'HIGH' | 'MEDIUM'
  matched_fields: Array<'NAME' | 'WEBSITE' | 'COUNTRY'>
}

export interface CustomerDuplicateCheckResult {
  has_high_risk_match: boolean
  recommended_action: 'REVIEW_BEFORE_CREATE' | 'CREATE_ALLOWED'
  matches: CustomerDuplicateMatch[]
}

export interface CustomerCreateInput {
  account_name: string
  primary_country_code: string
  primary_region_id?: string | null
  secondary_region_id?: string | null
  customer_source_item_id: string
  english_name?: string
  short_name?: string
  lifecycle_stage?: CustomerLifecycleStage
  primary_website_url?: string
  customer_grade_item_id?: string | null
  customer_type_item_ids?: string[]
  customer_tag_ids?: string[]
  industry_item_id?: string | null
  interested_product_item_ids?: string[]
  inquiry_keywords?: string
  primary_owner_employee_id?: string
  contact_name?: string
  contact_method_type?: CustomerContactMethodType
  contact_method_value?: string
  source_system?: string
  external_id?: string
  notes?: string
}

export type CustomerUpdateInput = Partial<
  Pick<
    CustomerCreateInput,
    | 'account_name'
    | 'english_name'
    | 'short_name'
    | 'lifecycle_stage'
    | 'primary_country_code'
    | 'primary_region_id'
    | 'secondary_region_id'
    | 'primary_website_url'
    | 'inquiry_keywords'
    | 'industry_item_id'
    | 'interested_product_item_ids'
    | 'source_system'
    | 'external_id'
    | 'notes'
  >
>

export interface CustomerSummaryCounts {
  entities: number
  contacts: number
  open_inquiries: number
  open_quotations: number
  active_samples: number
  open_complaints: number
  open_tasks: number
  overdue_tasks: number
}

export interface CustomerSummary {
  customer: CustomerListItem
  primary_owner: Omit<CustomerEmployeeSummary, 'status'> | null
  attention_level: CustomerEffectiveSummary | null
  counts: CustomerSummaryCounts
}

export interface CustomerTimelineEvent {
  id: string
  event_type: string
  source_type: string
  source_id: string
  title: string
  summary: string
  occurred_at: string
  event_data: Record<string, unknown>
  created_at: string
}

export interface CustomerTimelineQuery {
  event_type?: string
  source_type?: string
  occurred_from?: string
  occurred_to?: string
  cursor?: string
  page_size?: number
}

export interface CustomerGradeChangeInput {
  grade_item_id: string
  reason: string
}

export interface CustomerSourceChangeInput {
  source_item_id: string
  notes?: string
}

export interface CustomerActivityChangeInput {
  activity_status: CustomerActivityStatus
  reason: string
}

export interface CustomerClassificationChangeInput {
  customer_type_item_ids?: string[]
  customer_tag_ids?: string[]
  reason: string
}

export interface CustomerClassificationResult {
  customer_types: CustomerEffectiveSummary[]
  customer_tags: CustomerTagSummary[]
}

export interface CustomerBusinessSnapshotInput {
  as_of_at: string
  currency_code: string
  source_reference?: string
  customer_total_value?: DecimalInput | null
  last_12m_order_amount?: DecimalInput | null
  last_12m_order_count?: number | null
  quote_conversion_rate?: DecimalInput | null
  credit_limit?: DecimalInput | null
  credit_used?: DecimalInput | null
  open_complaint_count?: number | null
  notes?: string
}

export interface CustomerEntity {
  id: string
  customer_account: string
  entity_code: string
  entity_type: string
  entity_type_display: string
  legal_name: string
  english_legal_name: string
  registration_country_code: string
  registration_number: string
  tax_country_code: string
  tax_identifier: string
  notes: string
  archived_at: string | null
  created_at: string
  updated_at: string
}

export interface CustomerEntityInput {
  entity_code: string
  entity_type: string
  legal_name: string
  english_legal_name?: string
  registration_country_code: string
  registration_number?: string
  tax_country_code?: string
  tax_identifier?: string
  notes?: string
}

export interface CustomerAddress {
  id: string
  transaction_entity: string
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
  archived_at: string | null
  created_at: string
  updated_at: string
}

export type CustomerAddressInput = Pick<
  CustomerAddress,
  | 'address_code'
  | 'label'
  | 'country_code'
  | 'state_province'
  | 'city'
  | 'postal_code'
  | 'address_line1'
  | 'address_line2'
  | 'recipient_name'
  | 'recipient_phone'
  | 'is_verified'
>

export interface CustomerTransferRequest {
  id: string
  customer: { id: string; account_code: string; account_name: string }
  from_employee: CustomerEmployeeSummary
  to_employee: CustomerEmployeeSummary
  requested_by: CustomerEmployeeSummary | null
  decided_by: CustomerEmployeeSummary | null
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'CANCELLED'
  request_reason: string
  decision_note: string
  submitted_at: string
  decided_at: string | null
  created_at: string
  updated_at: string
}

export interface CustomerDuplicateCandidate {
  id: string
  etag: string
  customer: { id: string; account_code: string; account_name: string; archived_at: string | null }
  confidence_score: string
  matched_fields: Record<string, unknown>
  decision: string
  created_at: string
  updated_at: string
}

export interface CustomerDuplicateCase {
  id: string
  reviewer: CustomerEmployeeSummary | null
  status: string
  matching_strategy_version: string
  notes: string
  candidates: CustomerDuplicateCandidate[]
  created_at: string
  updated_at: string
}

export interface CustomerMergePreview {
  case_id: string
  survivor_customer_id: string
  source_customer_ids: string[]
  resolved_fields: Record<string, unknown>
  move_counts: Record<string, number>
  warnings: string[]
}
