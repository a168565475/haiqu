export type InquiryView = 'list' | 'board'
export interface InquiryDeletionPreview {
  inquiry_number: string
  quotation_count: number
  sample_count: number
  task_count: number
  inquiry_file_link_count: number
}
export type InquirySlaState = 'NONE' | 'NORMAL' | 'DUE_SOON' | 'BREACHED'

export interface InquiryEmployee { id: string; employee_code: string; display_name: string }
export interface InquiryRow {
  id: string; inquiry_number: string; subject: string; status: string; status_display: string
  customer: { id: string; name: string; country_code: string }
  source: { code: string; display_name: string }
  product_summary: { first_description: string; item_count: number }
  product_amount?: { item_count: number; missing_price_count: number; totals: Array<{ currency_code: string; amount: string }> }
  owner: InquiryEmployee | null
  priority?: '' | 'HIGH' | 'MEDIUM' | 'LOW'
  priority_display?: string
  has_quotation?: boolean
  estimated_amount_min?: string | null
  estimated_amount_max?: string | null
  estimated_currency_code?: string
  inquiry_source: string; received_at: string; requested_due_at: string | null; submitted_at?: string | null
  etag: string; display_stage: string; display_stage_label: string
  sla_summary: { state: InquirySlaState; next_deadline_at: string | null; remaining_seconds: number | null; working_time?: boolean; stage_code?: string; active_count?: number }
  allowed_actions: {
    set_priority?: boolean
    assign: boolean
    mark_invalid: boolean
    lifecycle: boolean
    create_quotation?: boolean
    attach_contact: boolean
    respond: boolean
    confirm_requirements: boolean
    follow_up: boolean
    create_sample: boolean
    create_sales_order: boolean
  }
  suggested_owner?: { id: string; display_name: string } | null
}

export interface InquiryMetrics {
  list_counts?: { all: number; mine: number; unassigned: number }
  has_quotation?: number
  today_new: number; today_new_delta: number; quote_accepted: number; pending_order: number; due_soon: number
  quoting: number; awaiting_customer: number
  conversion: { numerator: number; denominator: number; rate: number }
}

export interface InquiryOptions {
  priorities?: Array<{ code: 'HIGH' | 'MEDIUM' | 'LOW'; display_name: string }>
  statuses: Array<{ code: string; display_name: string }>
  sources: Array<{ item_code: string; display_name: string; sort_order: number; disabled?: boolean }>
  owners: InquiryEmployee[]; countries: string[]; invalid_reason_codes: string[]
}

export interface InquiryListResult { data: InquiryRow[]; meta: { total: number; total_pages: number; page: number; page_size: number } }

export interface InquiryItem {
  id?: string
  line_number?: number
  product_description: string
  specification: string
  color: string
  material: string
  quantity: string | number
  unit_code: string
  target_unit_price: string | number | null
  target_currency_code: string
  expected_date: string | null
  product_match_status: 'PENDING' | 'MATCHED' | 'NOT_REQUIRED'
  notes: string
}

export interface InquiryFile {
  id: string
  file_id: string
  original_name: string
  content_type: string
  size_bytes: number
  scan_status: string
  file_role: string
  created_at: string
}

export interface InquiryWorkCalendar {
  mode: 'ALTERNATING_WEEKS_V1'
  timezone: 'Asia/Shanghai'
  rest_saturday: string
  periods: [number, number][]
}

export interface InquiryHandlingRule {
  stage_minutes?: Record<string, number>
  name: string
  response_minutes: number | null
  confirmation_minutes: number | null
  work_calendar: InquiryWorkCalendar | null
}

export interface InquirySla {
  progress_context?: { round_number?: number | null; entry_reason?: string | null; source_label?: string | null; completion_reason?: string | null; quotation_id?: string | null }
  work_calendar?: InquiryWorkCalendar | null
  target_minutes?: number | null
  id: string
  stage_code: string
  is_current: boolean
  policy_code: string
  policy_name: string
  status: string
  started_at: string
  next_deadline_at: string | null
  breached_at: string | null
  completed_at: string | null
}

export interface InquiryAssignmentHistory {
  id: string
  previous_owner: InquiryEmployee | null
  new_owner: InquiryEmployee | null
  assigned_at: string
  assignment_reason: string
  assignment_type: string
}

export interface InquiryDetail extends InquiryRow {
  transaction_entity: string | null
  customer_contact: string | null
  customer_contact_summary: { id: string; display_name: string; english_name: string; preferred_language_code: string } | null
  description: string
  source_system: string
  external_id: string
  customer_snapshot: Record<string, unknown>
  source_snapshot: Record<string, unknown>
  customer_language_code: string
  trade_term_code: string
  trade_term_place: string
  delivery_requirement: string
  estimated_amount_min: string | null
  estimated_amount_max: string | null
  estimated_currency_code: string
  draft_version: number
  items: InquiryItem[]
  files: InquiryFile[]
  sla: InquirySla[]
  handling_time_rule?: InquiryHandlingRule | null
  assignment_history: InquiryAssignmentHistory[]
  linked_quotations: Array<{
    id: string
    quotation_number: string
    subject: string
    status: string
    version_id: string | null
    outcome_status: string
    accepted_version_id: string | null
  }>
  linked_samples: Array<{ id: string; request_number: string; status: string; status_display: string; updated_at: string }>
  linked_sales_orders: Array<{
    id: string
    order_number: string
    status: string
    status_display: string
    is_draft: boolean
    total_amount: string
    currency_code: string
    updated_at: string
  }>
}

export interface InquiryCommunicationInput {
  communication_type: 'EMAIL' | 'PHONE' | 'MEETING' | 'VIDEO' | 'WECHAT' | 'WHATSAPP' | 'OTHER'
  content: string
  occurred_at: string
}

export interface InquiryTimelineEvent {
  id: string
  event_type: string
  source_type: string
  source_id: string
  title: string
  summary: string
  occurred_at: string
  event_data: { actor_employee_id?: string | null; [key: string]: unknown }
}

export interface InquiryDraftInput {
  transaction_entity_id?: string | null
  customer_contact_id?: string | null
  inquiry_source?: string
  subject?: string
  description?: string
  received_at?: string
  requested_due_at?: string | null
  source_system?: string
  external_id?: string
  customer_language_code?: string
  trade_term_code?: string
  trade_term_place?: string
  delivery_requirement?: string
  estimated_amount_min?: string | number | null
  estimated_amount_max?: string | number | null
  estimated_currency_code?: string
  items?: InquiryItem[]
  idempotency_key: string
}

export interface InquiryCreateInput extends InquiryDraftInput {
  customer_account_id: string
}

export interface VersionedInquiry<T = InquiryDetail> {
  data: T
  etag: string | null
}
