export type InquiryStatus =
  | 'DRAFT' | 'NEW' | 'ANALYZING' | 'READY_FOR_QUOTE' | 'QUOTING' | 'QUOTED'
  | 'FOLLOW_UP' | 'QUOTE_ACCEPTED' | 'CONVERTED' | 'LOST' | 'CLOSED' | 'CANCELLED';

export type InquiryPriority = 'HIGH' | 'MEDIUM' | 'LOW';
export type InquirySlaState = 'NONE' | 'NORMAL' | 'DUE_SOON' | 'BREACHED';
export type InquiryOrderingField = 'received_at' | 'requested_due_at' | 'submitted_at' | 'created_at' | 'updated_at';
export type InquiryOrdering = InquiryOrderingField | `-${InquiryOrderingField}`;

export interface InquiryEmployee {
  id: string;
  employee_code: string;
  display_name: string;
}

export interface InquiryListItem {
  id: string;
  inquiry_number: string;
  subject: string;
  customer: { id: string; name: string; country_code: string };
  source: { code: string; display_name: string };
  priority: InquiryPriority | '';
  priority_display: string;
  owner: InquiryEmployee | null;
  product_summary: { first_description: string; item_count: number };
  product_amount: {
    item_count: number;
    missing_price_count: number;
    totals: { currency_code: string; amount: string }[];
  };
  received_at: string;
  status: InquiryStatus;
  status_display: string;
  display_stage: string;
  display_stage_label: string;
  has_quotation: boolean;
  sla_summary: {
    state: InquirySlaState;
    next_deadline_at: string | null;
    remaining_seconds: number | null;
    working_time?: boolean;
    stage_code?: string;
    active_count?: number;
  };
}

export interface InquiryQuery {
  q?: string;
  status?: InquiryStatus | '';
  source_code?: string;
  country_code?: string;
  owner_employee_id?: string;
  assignment_status?: 'ASSIGNED' | 'UNASSIGNED' | '';
  sla_state?: Exclude<InquirySlaState, 'NORMAL'> | 'RISK' | '';
  product_q?: string;
  received_from?: string;
  received_to?: string;
  has_quotation?: 'true' | 'false' | '';
  priority?: InquiryPriority | 'UNSET' | '';
  amount_min?: string;
  amount_currency?: string;
  page?: number;
  page_size?: number;
  ordering?: InquiryOrdering | '';
}

export interface InquiryPage {
  data: InquiryListItem[];
  meta: { page: number; page_size: number; total: number; total_pages: number };
}

export interface InquiryOptions {
  statuses: { code: InquiryStatus; display_name: string }[];
  priorities: { code: InquiryPriority; display_name: string }[];
  sources: { item_code: string; display_name: string; sort_order: number }[];
  owners: InquiryEmployee[];
  countries: string[];
}

export interface InquiryApiError extends Error {
  name: 'InquiryApiError';
  status: number;
  code: 'HTTP_ERROR' | 'NETWORK_ERROR' | 'INVALID_RESPONSE' | 'INVALID_QUERY';
}
