import type { PageMeta } from './customer'

export type ComplaintStatus =
  | 'ACCEPTED'
  | 'RESPONSIBILITY_CONFIRMATION'
  | 'SOLUTION_PLANNING'
  | 'CUSTOMER_CONFIRMATION'
  | 'CLOSED'
  | 'CANCELLED'

export type ComplaintSlaStatus = 'NORMAL' | 'AT_RISK' | 'OVERDUE' | 'COMPLETED'

export interface ComplaintDictionaryItem {
  id: string
  item_code: string
  display_name: string
  description: string
  sort_order: number
  extra_data: Record<string, number | string>
  disabled?: boolean
}

export interface ComplaintEmployee {
  id: string
  employee_code: string
  display_name: string
}

export interface ComplaintCustomer {
  id: string
  account_code: string
  account_name: string
}

export interface ComplaintContact {
  id: string
  display_name: string
  position_title: string
}

export interface ComplaintAttachment {
  id: string
  progress_entry_id: string | null
  caption: string
  original_name: string
  content_type: string
  size_bytes: number
  preview_url: string
  created_at: string
}

export interface ComplaintProgress {
  id: string
  from_status: ComplaintStatus
  from_status_label: string
  to_status: ComplaintStatus
  to_status_label: string
  progress_note: string
  root_cause: string
  responsibility: string
  solution: string
  customer_feedback: string
  created_by: ComplaintEmployee | null
  attachments: ComplaintAttachment[]
  created_at: string
}

export interface Complaint {
  id: string
  complaint_code: string
  customer: ComplaintCustomer
  original_customer: ComplaintCustomer
  contact: ComplaintContact | null
  complaint_type: ComplaintDictionaryItem
  severity: ComplaintDictionaryItem
  title: string
  source_order_reference: string
  source_order_snapshot: Record<string, string>
  issue_description: string
  status: ComplaintStatus
  status_label: string
  owner: ComplaintEmployee
  collaborators: ComplaintEmployee[]
  created_by: ComplaintEmployee | null
  last_updated_by: ComplaintEmployee | null
  root_cause: string
  responsibility: string
  solution: string
  customer_feedback: string
  first_response_due_at: string
  target_completion_at: string
  first_responded_at: string | null
  completed_at: string | null
  cancelled_at: string | null
  sla_status: ComplaintSlaStatus
  progress_entries: ComplaintProgress[]
  attachments: ComplaintAttachment[]
  created_at: string
  updated_at: string
}

export interface ComplaintPage {
  data: Complaint[]
  meta: PageMeta
}

export interface ComplaintOptions {
  complaint_types: ComplaintDictionaryItem[]
  severities: ComplaintDictionaryItem[]
  statuses: Array<{ value: ComplaintStatus; label: string }>
  employee_filters?: ComplaintEmployee[]
  employees: ComplaintEmployee[]
}

export interface ComplaintStats {
  total: number
  open: number
  closed: number
  cancelled: number
  waiting_customer_feedback: number
  closed_this_month: number
  sla: { overdue: number; at_risk: number; normal: number }
  by_type: Array<{
    complaint_type_item_id: string
    complaint_type_item__item_code: string
    complaint_type_item__display_name: string
    count: number
  }>
  by_owner: Array<{
    owner_employee_id: string
    owner_employee__display_name: string
    count: number
  }>
}

export interface ComplaintQuery {
  q?: string
  customer_id?: string
  complaint_type_item_id?: string
  severity_item_id?: string
  status?: ComplaintStatus | ''
  owner_employee_id?: string
  sla_status?: ComplaintSlaStatus | ''
  page?: number
  page_size?: number
}

export interface ComplaintInput {
  customer_id: string
  contact_id?: string | null
  complaint_type_item_id: string
  severity_item_id: string
  title: string
  source_order_reference?: string
  source_order_snapshot?: Record<string, string>
  issue_description: string
  owner_employee_id?: string
  collaborator_employee_ids?: string[]
}

export type ComplaintUpdateInput = Partial<Omit<ComplaintInput, 'customer_id'>>

export interface ComplaintProgressInput {
  to_status: ComplaintStatus
  progress_note: string
  root_cause?: string
  responsibility?: string
  solution?: string
  customer_feedback?: string
}

export interface VersionedComplaint {
  data: Complaint
  etag: string | null
}
