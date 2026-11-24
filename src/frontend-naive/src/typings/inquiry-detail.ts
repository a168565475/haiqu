import type { InquiryEmployee, InquiryListItem } from './inquiry';

export interface InquiryDetailEmployee extends InquiryEmployee {
  status: string;
}

export type InquiryFileScanStatus = 'PENDING' | 'CLEAN' | 'INFECTED' | 'FAILED' | 'SKIPPED';

export interface InquiryItem {
  id: string;
  line_number: number;
  product_id: string | null;
  product_category_id: string | null;
  product_category_name: string;
  product_unit_id: string | null;
  product_color_id: string | null;
  product_image_id: string | null;
  product_image: {
    id: string;
    original_name: string;
    content_type: string;
    size_bytes: number;
    scan_status: InquiryFileScanStatus;
  } | null;
  product_description: string;
  specification: string;
  color: string;
  material: string;
  quantity: string;
  unit_code: string;
  target_unit_price: string | null;
  target_currency_code: string;
  expected_date: string | null;
  product_match_status: 'PENDING' | 'MATCHED' | 'NOT_REQUIRED';
  notes: string;
  product_number_snapshot: string;
  product_code_snapshot: string;
  item_number_snapshot: string;
  customer_product_name_snapshot: string;
  customer_specification_snapshot: string;
  customer_unit_code_snapshot: string;
  customer_color_snapshot: string;
  customer_material_snapshot: string;
  created_at: string;
  updated_at: string;
}

export interface InquiryFile {
  id: string;
  file_id: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  scan_status: InquiryFileScanStatus;
  file_role: string;
  created_at: string;
}

export interface InquiryWorkCalendar {
  mode: 'ALTERNATING_WEEKS_V1';
  timezone: 'Asia/Shanghai';
  rest_saturday: string;
  periods: [number, number][];
}

export interface InquiryHandlingRule {
  name: string;
  response_minutes: number | null;
  confirmation_minutes: number | null;
  work_calendar: InquiryWorkCalendar | null;
  stage_minutes: Record<string, number>;
}

export interface InquirySla {
  id: string;
  stage_code: string;
  is_current: boolean;
  policy_code: string;
  policy_name: string;
  status: 'RUNNING' | 'MET' | 'BREACHED' | 'CANCELLED';
  started_at: string;
  next_deadline_at: string | null;
  breached_at: string | null;
  completed_at: string | null;
  work_calendar: InquiryWorkCalendar | null;
  target_minutes: number | null;
  progress_context: {
    round_number: number | null;
    entry_reason: string | null;
    source_label: string | null;
    completion_reason: string | null;
    quotation_id: string | null;
  };
}

export interface InquiryAssignmentHistory {
  id: string;
  previous_owner: InquiryDetailEmployee | null;
  new_owner: InquiryDetailEmployee | null;
  assigned_at: string;
  assignment_reason: string;
  assignment_type: string;
}

export interface InquiryDetail extends InquiryListItem {
  allowed_permissions?: string[];
  owner: InquiryDetailEmployee | null;
  customer_account: string;
  customer_name: string;
  inquiry_source: string;
  requested_due_at: string | null;
  submitted_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  has_sent_quotation: boolean;
  has_active_sample: boolean;
  etag: string;
  allowed_actions: {
    assign: boolean;
    set_priority: boolean;
    mark_invalid: boolean;
    lifecycle: boolean;
    create_quotation: boolean;
    attach_contact: boolean;
    respond: boolean;
    confirm_requirements: boolean;
    follow_up: boolean;
    create_sample: boolean;
    create_sales_order: boolean;
  };
  transaction_entity: string | null;
  customer_contact: string | null;
  customer_contact_summary: { id: string; display_name: string; english_name: string; preferred_language_code: string } | null;
  description: string;
  source_system: string;
  external_id: string;
  customer_snapshot: Record<string, unknown>;
  source_snapshot: Record<string, unknown>;
  customer_language_code: string;
  trade_term_code: string;
  trade_term_place: string;
  delivery_requirement: string;
  estimated_amount_min: string | null;
  estimated_amount_max: string | null;
  estimated_currency_code: string;
  draft_version: number;
  items: InquiryItem[];
  files: InquiryFile[];
  sla: InquirySla[];
  handling_time_rule: InquiryHandlingRule | null;
  assignment_history: InquiryAssignmentHistory[];
  linked_quotations: {
    id: string; quotation_number: string; subject: string; status: string; version_id: string | null;
    outcome_status: string; accepted_version_id: string | null;
  }[];
  linked_samples: { id: string; request_number: string; status: string; status_display: string; updated_at: string }[];
  linked_sales_orders: {
    id: string; order_number: string; status: string; status_display: string; is_draft: boolean;
    total_amount: string | number; currency_code: string; updated_at: string;
  }[];
}

export interface InquiryTimelineEvent {
  id: string;
  event_type: string;
  source_type: string;
  source_id: string;
  title: string;
  summary: string;
  occurred_at: string;
  event_data: { actor_employee_id?: string | null; [key: string]: unknown };
}

export interface InquiryTimelinePage {
  data: InquiryTimelineEvent[];
  meta: { page: number; page_size: number; total: number; total_pages: number };
}

export type InquiryTaskStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED';
export type InquiryTaskPriority = 'LOW' | 'NORMAL' | 'HIGH' | 'URGENT';
export type InquiryTaskType = 'CUSTOMER_FOLLOW_UP' | 'COMMUNICATION_FOLLOW_UP' | 'INQUIRY_RESPONSE' | 'QUOTATION_FOLLOW_UP' | 'SAMPLE_FEEDBACK' | 'OTHER';

export interface InquiryTask {
  allowed_permissions?: string[];
  id: string;
  task_number: string;
  title: string;
  status: InquiryTaskStatus;
  status_display: string;
  priority: InquiryTaskPriority;
  priority_display: string;
  task_type: InquiryTaskType;
  task_type_display: string;
  origin_type: 'MANUAL' | 'BUSINESS_EVENT' | 'AUTOMATION' | 'SLA';
  origin_type_display: string;
  work_state: 'NORMAL' | 'WAITING_CUSTOMER' | 'BLOCKED';
  work_state_display: string;
  display_status: InquiryTaskStatus | 'BLOCKED' | 'OVERDUE' | 'WAITING_CUSTOMER';
  work_state_reason: string;
  next_check_at: string | null;
  due_at: string | null;
  completed_at: string | null;
  completion_result: string;
  cancelled_at: string | null;
  cancel_reason: string;
  reschedule_count: number;
  business_version: number;
  assignee: InquiryDetailEmployee;
  created_by: InquiryDetailEmployee | null;
  contact_summary: { id: string; name: string; position: string } | null;
  customer: { id: string; code: string; name: string } | null;
  source: { type: 'CUSTOMER' | 'COMMUNICATION' | 'INQUIRY' | 'QUOTATION_VERSION' | 'SAMPLE_REQUEST'; id: string; code: string; title: string; open_url: string | null } | null;
  checklist_progress: { completed: number; total: number };
  created_at: string;
  updated_at: string;
}

export interface InquiryDetailApiError extends Error {
  name: 'InquiryDetailApiError';
  status: number;
  code: 'HTTP_ERROR' | 'NETWORK_ERROR' | 'INVALID_RESPONSE' | 'INVALID_QUERY';
}
