import type { LegacySourceData, PageMeta } from './customer'

export type ContactStatus = 'ACTIVE' | 'INACTIVE' | 'LEFT'
export type ContactMethodType = 'EMAIL' | 'PHONE' | 'MOBILE' | 'WECHAT' | 'WHATSAPP' | 'OTHER'
export type ContactRoleType = 'DECISION_MAKER' | 'BUYER' | 'TECHNICAL' | 'FINANCE' | 'LOGISTICS' | 'OTHER'

export interface ContactCustomerSummary {
  id: string
  account_code: string
  account_name: string
}

export interface ContactMethod {
  id: string
  method_type: ContactMethodType
  method_type_display: string
  display_value: string
  masked_value: string
  is_primary: boolean
  is_preferred: boolean
  verification_status: string
  archived_at: string | null
  updated_at: string
}

export interface ContactRole {
  id: string
  role_type: ContactRoleType
  role_type_display: string
}

export interface ContactListItem {
  id: string
  customer: ContactCustomerSummary
  display_name: string
  english_name: string
  position_title: string
  department_name: string
  preferred_language_code: string
  timezone_code: string
  is_key_contact: boolean
  is_primary_contact: boolean
  status: ContactStatus
  status_display: string
  methods: ContactMethod[]
  active_roles: ContactRole[]
  last_interaction: { occurred_at: string; communication_type: string } | null
  open_task_count: number
  left_effective_date: string | null
  marketing_opt_out: boolean
  archived_at: string | null
  created_at: string
  updated_at: string
}

export interface ContactDetail extends ContactListItem {
  transaction_entity: string | null
  source_contact: string | null
  notes: string
  legacy_source_data: LegacySourceData
  archive_reason: string
  marketing_opt_out_at: string | null
  marketing_opt_out_by_employee: string | null
}

export interface ContactListQuery {
  include_summary?: boolean
  q?: string
  customer_id?: string
  status?: ContactStatus | ''
  role_type?: ContactRoleType | ''
  method_type?: ContactMethodType | ''
  is_key_contact?: boolean | ''
  last_interaction?: '' | 'WITHIN_7_DAYS' | 'WITHIN_30_DAYS' | 'WITHIN_90_DAYS' | 'NEVER'
  ordering?: string
  page?: number
  page_size?: number
}

export interface ContactMethodInput {
  method_type: ContactMethodType
  raw_value: string
  is_primary?: boolean
  is_preferred?: boolean
  verification_status?: string
}

export interface ContactCreateInput {
  customer_id: string
  display_name: string
  english_name?: string
  position_title?: string
  department_name?: string
  preferred_language_code?: string
  timezone_code?: string
  is_key_contact?: boolean
  is_primary_contact?: boolean
  status?: Exclude<ContactStatus, 'LEFT'>
  notes?: string
  methods: ContactMethodInput[]
  role_types?: ContactRoleType[]
  duplicate_acknowledged?: boolean
}

export interface ContactUpdateInput {
  display_name?: string
  english_name?: string
  position_title?: string
  department_name?: string
  preferred_language_code?: string
  timezone_code?: string
  is_key_contact?: boolean
  is_primary_contact?: boolean
  status?: Exclude<ContactStatus, 'LEFT'>
  notes?: string
  methods?: ContactMethodInput[]
  role_types?: ContactRoleType[]
  duplicate_acknowledged?: boolean
}

export interface ContactOption {
  value: string
  label: string
  disabled?: boolean
}

export interface ContactOptions {
  role_options: ContactOption[]
  status_options: ContactOption[]
  language_options: ContactOption[]
  timezone_options: ContactOption[]
}

export interface ContactDuplicateSummary {
  normalized_value: string
  requires_acknowledgement: boolean
  same_customer_matches: Array<{ contact_id: string; display_name: string }>
  cross_customer_matches: Array<{
    contact_id: string
    display_name: string
    customer_id: string
    customer_name: string
  }>
  hidden_cross_customer_count: number
  cross_customer_domain_count: number
}

export interface ContactEmploymentEvent {
  id: string
  event_type: 'JOINED' | 'PROFILE_CHANGED' | 'PRIMARY_CHANGED' | 'LEFT'
  event_type_display: string
  effective_on: string
  title: string
  position_title: string
  department_name: string
  role_types: ContactRoleType[]
  is_primary_contact: boolean
  notes: string
  change_data: Record<string, unknown>
  actor_employee: { id: string; display_name: string; employee_code: string } | null
  created_at: string
}

export interface ContactEmploymentRecordInput {
  effective_on: string
  title: string
  position_title?: string
  department_name?: string
  role_types?: ContactRoleType[]
  is_primary_contact?: boolean
  notes?: string
}

export interface ContactLeaveInput {
  effective_date: string
  replacement_contact_id?: string | null
  unfinished_task_policy: 'TRANSFER_TO_OWNER' | 'KEEP_ASSIGNEE' | 'CANCEL_OPEN'
  preserve_history: true
  remove_from_marketing: boolean
  notify_stakeholders: boolean
  reason?: string
}

export interface ContactPrioritySummary {
  id: string
  display_name: string
  position_title: string
  active_roles: ContactRole[]
  last_interaction: { occurred_at: string } | null
}

export interface CustomerContactSummary {
  total: number
  active: number
  decision_maker: number
  primary: number
  left: number
  stale: number
  priority_candidates: ContactPrioritySummary[]
}

export interface ContactPage {
  data: ContactListItem[]
  meta: PageMeta
  summary?: CustomerContactSummary
}

export interface VersionedContact {
  data: ContactDetail
  etag: string | null
}

export interface ImportBatch {
  id: string
  status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'PARTIAL_FAILED' | 'FAILED'
  total_count: number
  success_count: number
  failure_count: number
  error_summary: string
  source_file: { original_name: string; size_bytes: number; scan_status: string }
}

export interface ImportRecord {
  id: string
  row_number: number
  status: string
  raw_data: Record<string, string>
  warning_messages: string[]
  error_message: string
}

export interface SavedContactView {
  id: string
  module_code: 'CONTACT'
  view_name: string
  filter_definition: Record<string, unknown>
  column_definition: string[]
  sort_definition: string[]
  is_default: boolean
  updated_at: string
}
