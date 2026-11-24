import type { ComplaintListItem } from './complaint';
import type { CustomerListItem } from './customer';
import type { InquiryListItem } from './inquiry';
import type { InquiryTask } from './inquiry-detail';

export interface CustomerEmployee { id: string; employee_code: string; display_name: string; status?: string }
export interface CustomerDictionary { id: string; item_code: string; display_name: string }
export interface CustomerEffective extends CustomerDictionary { reason: string; effective_from: string; effective_to: string | null }
export interface CustomerSource extends CustomerDictionary { notes: string; effective_from: string; effective_to: string | null }
export interface CustomerAssignment {
  id: string; employee: CustomerEmployee; assignment_role: string;
  effective_from: string; effective_to: string | null; reason: string; created_at: string;
}
export interface CustomerBusinessSnapshot {
  id: string; source_type: 'MANUAL' | 'ERP'; source_type_display: string; source_reference: string;
  as_of_at: string; currency_code: string; customer_total_value: string | null;
  last_12m_order_amount: string | null; last_12m_order_count: number | null;
  quote_conversion_rate: string | null; credit_limit: string | null; credit_used: string | null;
  open_complaint_count: number | null; notes: string; entered_by: CustomerEmployee | null;
  is_current: boolean; created_at: string;
}
export interface CustomerDetail extends CustomerListItem {
  allowed_permissions?: string[];
  short_name: string;
  lifecycle_stage: 'LEAD' | 'VERIFIED' | 'OPPORTUNITY' | 'CUSTOMER' | 'LOST';
  lifecycle_stage_display: string;
  primary_website_url: string;
  industry: CustomerDictionary | null;
  inquiry_keywords: string;
  recorded_by: CustomerEmployee | null;
  recorded_at: string | null;
  attention_level: CustomerEffective | null;
  first_source: CustomerSource | null;
  latest_source: CustomerSource | null;
  customer_types: CustomerEffective[];
  customer_tags: { id: string; tag_code: string; tag_name: string; color: string }[];
  customer_value: CustomerBusinessSnapshot | null;
  business_snapshot: CustomerBusinessSnapshot | null;
  lifetime_sales_amount: string | null;
  lifetime_sales_order_count: number | null;
  last_12m_sales_order_count: number | null;
  quotation_conversion_rate: string | null;
  source_system: string;
  external_id: string;
  notes: string;
  legacy_source_data: Record<string, unknown>;
  archive_reason: string;
  current_assignments: CustomerAssignment[];
  interested_products: { id: string; product_item_id: string; item_code: string; display_name: string }[];
  company_contact_methods: { id: string; method_type: 'EMAIL' | 'PHONE' | 'SKYPE'; method_type_display: string; raw_value: string; is_primary: boolean }[];
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}
export interface CustomerSummary {
  customer: CustomerListItem;
  primary_owner: CustomerEmployee | null;
  attention_level: CustomerEffective | null;
  counts: { entities: number; contacts: number; open_inquiries: number; open_quotations: number;
    active_samples: number; open_complaints: number; open_tasks: number; overdue_tasks: number };
}
export interface CustomerContact {
  id: string;
  customer: { id: string; account_code: string; account_name: string };
  display_name: string; english_name: string; position_title: string; department_name: string;
  preferred_language_code: string; timezone_code: string; is_key_contact: boolean; is_primary_contact: boolean;
  status: 'ACTIVE' | 'INACTIVE' | 'LEFT'; status_display: string;
  methods: { id: string; method_type: 'EMAIL' | 'PHONE' | 'MOBILE' | 'WECHAT' | 'WHATSAPP' | 'OTHER';
    method_type_display: string; display_value: string; masked_value: string; is_primary: boolean; is_preferred: boolean }[];
  active_roles: { id: string; role_type: string; role_type_display: string }[];
  last_interaction: { occurred_at: string; communication_type: string | null } | null;
  open_task_count: number; left_effective_date: string | null; marketing_opt_out: boolean;
  archived_at: string | null; created_at: string; updated_at: string;
}
export interface CustomerContactQuery { page?: number; page_size?: number; q?: string; status?: CustomerContact['status'] | '' }
export interface CustomerPageMeta { page: number; page_size: number; total: number; total_pages: number }
export interface CustomerContactPage { data: CustomerContact[]; meta: CustomerPageMeta }
export interface CustomerTimelineEvent {
  id: string; event_type: string; source_type: string; source_id: string;
  title: string; summary: string; occurred_at: string; event_data: Record<string, unknown>; created_at: string;
}
export interface CustomerTimelineQuery { cursor?: string; event_type?: string; source_type?: string; occurred_from?: string; occurred_to?: string }
export interface CustomerTimelinePage {
  data: CustomerTimelineEvent[];
  meta: { next: string | null; previous: string | null; page_size: number };
}
export type CustomerTask = Pick<InquiryTask, 'id' | 'task_number' | 'title' | 'status' | 'status_display' | 'priority' | 'priority_display'
  | 'task_type' | 'task_type_display' | 'due_at' | 'assignee' | 'customer' | 'source' | 'created_at' | 'updated_at'>;
export interface CustomerEntity { id: string; customer_account: string; entity_code: string; legal_name: string }
export interface CustomerAddress {
  id: string; transaction_entity: string; address_code: string; label: string; country_code: string;
  state_province: string; city: string; postal_code: string; address_line1: string; address_line2: string;
  recipient_name: string; recipient_phone: string; is_verified: boolean;
}
export type CustomerInquiry = InquiryListItem & { requested_due_at: string | null };
export interface CustomerQuotation {
  id: string; quotation_number: string; customer_account: string; customer_name: string; subject: string;
  owner: CustomerEmployee | null; display_status: string; display_status_label: string; updated_at: string;
  current_version: { id: string; version_number: number; currency_code: string; total_amount: string; valid_until: string | null } | null;
}
export interface CustomerSample {
  id: string; request_number: string; customer_account: string; customer_name: string;
  sample_type: string; sample_type_display: string; status: string; status_display: string;
  owner: CustomerEmployee | null; item_summary: { text: string; count: number };
  latest_shipment: { status: string; status_display: string; tracking_number: string; carrier_code: string; shipped_at: string | null; delivered_at: string | null } | null;
  requested_at: string; updated_at: string;
}
export interface CustomerOrder {
  id: string; order_number: string; customer_code: string; customer_name: string; customer_po_number: string;
  status: 'DRAFT' | 'CONFIRMED' | 'FULFILLING' | 'COMPLETED' | 'PAUSED' | 'CANCELLED'; status_display: string;
  source_type: 'QUOTATION' | 'DIRECT' | 'REPEAT'; source_type_display: string;
  currency_code: string; total_amount: string; salesperson: CustomerEmployee;
  next_delivery_date: string | null; order_date: string; updated_at: string;
}
export interface CustomerRecordMap {
  tasks: CustomerTask; inquiries: CustomerInquiry; quotations: CustomerQuotation;
  samples: CustomerSample; orders: CustomerOrder; complaints: ComplaintListItem;
}
export type CustomerRecordKind = keyof CustomerRecordMap;
export type CustomerRecordRow = CustomerRecordMap[CustomerRecordKind];
export interface CustomerRecordQuery {
  page?: number; page_size?: number; q?: string; status?: string; ownerId?: string; subtype?: string; date?: string;
  scope?: 'ALL' | 'TEAM' | 'ME';
}
export interface CustomerRecordPage<K extends CustomerRecordKind = CustomerRecordKind> { data: CustomerRecordMap[K][]; meta: CustomerPageMeta }
export interface CustomerRecordOptions {
  statuses: { label: string; value: string }[];
  owners: { label: string; value: string }[];
  subtypes: { label: string; value: string }[];
}
export interface CustomerDetailApiError extends Error {
  name: 'CustomerDetailApiError'; status: number;
  code: 'HTTP_ERROR' | 'NETWORK_ERROR' | 'INVALID_RESPONSE' | 'INVALID_QUERY';
}
