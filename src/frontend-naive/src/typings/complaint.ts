export type ComplaintStatus =
  | 'ACCEPTED'
  | 'RESPONSIBILITY_CONFIRMATION'
  | 'SOLUTION_PLANNING'
  | 'CUSTOMER_CONFIRMATION'
  | 'CLOSED'
  | 'CANCELLED';

export type ComplaintSlaStatus = 'NORMAL' | 'AT_RISK' | 'OVERDUE' | 'COMPLETED';

export interface ComplaintDictionaryOption {
  id: string;
  item_code: string;
  display_name: string;
}

export interface ComplaintEmployee {
  id: string;
  display_name: string;
}

export interface ComplaintListItem {
  id: string;
  complaint_code: string;
  customer: { id: string; account_name: string };
  source_order_reference: string;
  complaint_type: ComplaintDictionaryOption;
  severity: ComplaintDictionaryOption;
  status: ComplaintStatus;
  status_label: string;
  owner: ComplaintEmployee;
  sla_status: ComplaintSlaStatus;
  target_completion_at: string;
  updated_at: string;
}

export interface ComplaintQuery {
  q?: string;
  customer_id?: string;
  complaint_type_item_id?: string;
  severity_item_id?: string;
  owner_employee_id?: string;
  status?: ComplaintStatus | '';
  sla_status?: ComplaintSlaStatus | '';
  page?: number;
  page_size?: number;
}

export interface ComplaintPage {
  data: ComplaintListItem[];
  meta: { page: number; page_size: number; total: number; total_pages: number };
}

export interface ComplaintOptions {
  complaint_types: ComplaintDictionaryOption[];
  severities: ComplaintDictionaryOption[];
  statuses: { value: ComplaintStatus; label: string }[];
  employees: ComplaintEmployee[];
}

export interface ComplaintApiError extends Error {
  name: 'ComplaintApiError';
  status: number;
  code: 'HTTP_ERROR' | 'NETWORK_ERROR' | 'INVALID_RESPONSE' | 'INVALID_QUERY';
}
