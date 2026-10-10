import type { CustomerListItem } from '@/types/customer'

export type WorkbenchMode = 'SALES' | 'MANAGER'
export type DataOrigin = 'LIVE' | 'DEMO'
export type WorkbenchLoadState = 'LOADING' | 'READY' | 'EMPTY' | 'ERROR' | 'FORBIDDEN'

export interface DashboardCounts {
  customers: number
  open_inquiries: number
  open_quotations: number
  active_sample_requests: number
  open_tasks: number
  overdue_tasks: number
}

export interface DashboardCustomerSummary {
  id: string
  account_code: string
  account_name: string
  updated_at: string
}

export interface DashboardOwnerDistribution {
  employee_id: string
  employee__employee_code: string
  employee__display_name: string
  customer_count: number
}

export interface WorkbenchDashboardPayload {
  counts: DashboardCounts
  recent_customers: DashboardCustomerSummary[]
  due_inquiries: Array<Record<string, unknown>>
  expiring_quotation_versions: Array<Record<string, unknown>>
  sample_queue: Array<Record<string, unknown>>
  owner_distribution?: DashboardOwnerDistribution[]
}

export interface TaskSource {
  type: 'CUSTOMER' | 'COMMUNICATION' | 'INQUIRY' | 'QUOTATION_VERSION' | 'SAMPLE_REQUEST'
  id: string
}

export interface WorkbenchTask {
  id: string
  title: string
  status: 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED'
  status_display: string
  priority: 'LOW' | 'NORMAL' | 'HIGH' | 'URGENT'
  priority_display: string
  due_at: string
  completed_at: string | null
  assignee: { id: string; employee_code: string; display_name: string } | null
  source: TaskSource | null
  source_label?: string
  created_at: string
  updated_at: string
}

export interface WorkbenchMetric {
  key: string
  label: string
  value: string
  note: string
  tone: 'neutral' | 'danger' | 'warning' | 'success'
  origin: DataOrigin
}

export interface WorkbenchRiskItem {
  id: string
  customer: string
  reason: string
  level: '高风险' | '需跟进' | '关注'
  lastFollowUp: string
  source?: CustomerListItem
}

export interface SalesFunnelItem {
  label: string
  value: string
  ratio: number
  color: string
}

export interface MilestoneItem {
  title: string
  customer: string
  date: string
  status: string
}

export interface TeamPerformanceItem {
  rank: number
  name: string
  amount: string
  margin: string
  inquiries: number
  followUp: string
  status: string
  tone: 'success' | 'neutral' | 'warning' | 'danger'
}

export interface TeamLoadItem {
  name: string
  current: number
  overdue: number
  ratio: number
  tone: 'normal' | 'warning' | 'danger'
}

export interface SlaItem {
  label: string
  value: string
  note: string
  badge: string
  tone: 'success' | 'warning' | 'danger' | 'neutral'
}
