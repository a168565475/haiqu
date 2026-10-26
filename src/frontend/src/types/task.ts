import type { CustomerEmployeeSummary } from './customer'

export type TaskScope = 'ME' | 'CREATED_BY_ME' | 'TEAM' | 'ALL'
export type TaskStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED'
export type TaskPriority = 'LOW' | 'NORMAL' | 'HIGH' | 'URGENT'
export type TaskType = 'CUSTOMER_FOLLOW_UP' | 'COMMUNICATION_FOLLOW_UP' | 'INQUIRY_RESPONSE' | 'QUOTATION_FOLLOW_UP' | 'SAMPLE_FEEDBACK' | 'OTHER'
export type TaskSourceType = 'CUSTOMER' | 'COMMUNICATION' | 'INQUIRY' | 'QUOTATION_VERSION' | 'SAMPLE_REQUEST'

export interface TaskCreateInput {
  assignee_employee_id: string
  title: string
  description?: string
  priority?: TaskPriority
  task_type?: TaskType
  contact_id?: string | null
  due_at?: string | null
  source_type?: TaskSourceType
  source_id?: string
  checklist?: string[]
  reminder_at_list?: string[]
}

export interface TaskSummary {
  id: string
  task_number: string
  title: string
  status: TaskStatus
  status_display: string
  priority: TaskPriority
  priority_display: string
  task_type: string
  task_type_display: string
  origin_type: string
  origin_type_display: string
  work_state: string
  work_state_display: string
  display_status: string
  work_state_reason: string
  next_check_at: string | null
  due_at: string | null
  completed_at: string | null
  completion_result: string
  cancelled_at: string | null
  cancel_reason: string
  reschedule_count: number
  business_version: number
  assignee: CustomerEmployeeSummary
  created_by: CustomerEmployeeSummary | null
  contact_summary: { id: string; name: string; position: string } | null
  customer: { id: string; code: string; name: string } | null
  source: { type: string; id: string; code: string; title: string; open_url: string | null } | null
  checklist_progress: { completed: number; total: number }
  created_at: string
  updated_at: string
}

export interface TaskDetail extends TaskSummary {
  description: string
  checklist_items: Array<{ id: string; content: string; sort_order: number; is_completed: boolean; completed_at: string | null }>
  reminders: Array<{ id: string; remind_at: string; status: string; status_display: string }>
  collaborators: CustomerEmployeeSummary[]
  source_attachments: Array<{ id: string; name: string; content_type: string; size_bytes: number; preview_url: string; download_url: string }>
}

export interface TaskOptions {
  scopes: Array<{ value: TaskScope; label: string }>
  task_types: Array<{ value: string; label: string }>
  statuses: Array<{ value: TaskStatus; label: string }>
  priorities: Array<{ value: TaskPriority; label: string }>
  assignee_filters?: Array<{ id: string; code: string; name: string }>
  assignees: Array<{ id: string; code: string; name: string }>
}

export interface TaskFilters {
  scope: TaskScope
  q: string
  assignee_employee_id: string
  task_type: string
  status: string
  priority: string
  due_window: string
  source_type: string
  customer_id: string
  ordering: string
  page: number
  page_size: number
}
