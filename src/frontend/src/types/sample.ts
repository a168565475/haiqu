import type { CustomerEmployeeSummary, PageMeta } from './customer'

export type SampleStatus =
  | 'DIRECTOR_REVIEW' | 'APPLICATION_RETURNED' | 'MATERIALS_PENDING'
  | 'WAREHOUSE_PENDING' | 'PROCUREMENT_PENDING' | 'MATERIALS_READY'
  | 'MATERIAL_ISSUE_PENDING' | 'MATERIAL_ISSUE_REVIEW'
  | 'DRAFT' | 'PENDING_COMPLETION' | 'PENDING' | 'PMC_REVIEW' | 'METALWORK_PENDING'
  | 'CUTTING_PENDING' | 'PRODUCTION_PENDING' | 'FINISHED' | 'PREPARING' | 'SHIPPED' | 'DELIVERED'
  | 'FEEDBACK_PENDING' | 'CONFIRMED' | 'COMPLETED' | 'REJECTED' | 'CANCELLED'

export interface SampleSelectOption {
  value: string
  label: string
}

export interface SampleCustomerOption {
  id: string
  account_code: string
  account_name: string
}

export interface SampleOwnerOption {
  id: string
  employee_code: string
  display_name: string
}

export interface SampleOptions {
  sample_types: SampleSelectOption[]
  statuses: SampleSelectOption[]
  customers: SampleCustomerOption[]
  owners: SampleOwnerOption[]
  fee_decisions: SampleSelectOption[]
  freight_bearers: SampleSelectOption[]
  fee_verification_statuses: SampleSelectOption[]
  fee_approvers: SampleOwnerOption[]
}

export interface SampleFormOptions {
  current_maker: SampleOwnerOption
  sample_types: SampleSelectOption[]
  shipping_methods: SampleSelectOption[]
  delivery_batches: SampleSelectOption[]
  repeat_options: Array<{ value: boolean; label: string }>
  tolerances: SampleSelectOption[]
  customers: SampleCustomerOption[]
  salespeople: SampleOwnerOption[]
  categories: Array<{ id: string; category_name: string }>
  color_cards: string[]
  colors: Array<{ id: string; color_card: string; color_name: string; color_code: string }>
  sampling_detail_template: SampleSamplingDetailTemplate[]
}

export interface SampleSamplingDetailTemplate {
  key: string
  type: string
  category: string
}

export interface SampleFormContext {
  reference_images?: Array<{ id: string; name: string; url: string }>
  source_type: 'inquiry' | 'quotation'
  source_id: string
  source_parent_id: string | null
  source_version_id: string | null
  source_number: string
  customer: SampleCustomerOption
  contact: { id: string; display_name: string } | null
  owner: SampleOwnerOption
  transaction_entity_id: string | null
  linked_inquiry_id?: string | null
  basic_info: {
    order_date: string | null
    sample_due_date: string | null
  }
  suggested_due_date: string | null
  sample_types: SampleSelectOption[]
  unfinished_samples: Array<{
    id: string
    number: string
    status: SampleStatus
    status_display: string
  }>
  products: Array<{
    id: string
    source_inquiry_item_id: string | null
    source_quotation_line_id: string | null
    product_name: string
    specification: string
    source_quantity: string
    source_unit_code: string
    reference_images?: Array<{ id: string; name: string; url: string }>
  }>
}

export interface SampleFormDetailInput {
  id?: string
  product_color_id: string
  color_code: string
  sample_quantity: number
  tolerance: string
  notes: string
  cutting_reported_quantity: number
  metalwork_reported_quantity: number
  cutting_completed: boolean
  metalwork_completed: boolean
}

export interface SampleReportingProductEdit {
  id?: string
  details: Array<{
    id?: string
    cutting_reported_quantity: number | null
    metalwork_reported_quantity: number | null
    cutting_completed: boolean
    metalwork_completed: boolean
  }>
}

export interface SampleProductSamplingDetailInput {
  id?: string
  client_key: string
  template_key: string
  detail_type: string
  category_label: string
  is_selected: boolean
  description: string
}

export interface SampleFormProductInput {
  id?: string
  client_key: string
  source_inquiry_item_id?: string | null
  source_quotation_line_id?: string | null
  category_id: string
  product_name: string
  specification: string
  length_cm: string | null
  armrest_width_cm: string | null
  seat_width_cm: string | null
  back_height_cm: string | null
  seat_height_cm: string | null
  details: SampleFormDetailInput[]
  sampling_details: SampleProductSamplingDetailInput[]
}

export interface SampleRequestFormInput {
  manual_request_number: string
  customer_account_id: string
  customer_contact_id?: string | null
  owner_employee_id: string
  shipping_method: string
  order_date: string
  sample_due_date: string
  delivery_batch: string
  sample_type: string
  is_repeat_order: boolean
  submitted_on: string
  purpose: string
  source_type?: 'inquiry' | 'quotation'
  source_id?: string
  idempotency_key?: string
  products: SampleFormProductInput[]
}

export interface SampleFeeSummary {
  fee_decision: string
  fee_decision_display: string
  amount: string
  currency_code: string
  verification_status: string
  verification_status_display?: string
  decision_reason?: string
  decided_at?: string | null
  decided_by?: CustomerEmployeeSummary | null
}

export interface SampleShipmentSummary {
  status: string
  status_display: string
  tracking_number: string
  carrier_code: string
  shipped_at: string | null
  delivered_at: string | null
}

export interface SampleListItem {
  edit_capabilities?: {
    mode: 'COMPLETE' | 'FULL' | 'REPORT_ONLY' | 'READ_ONLY'
    can_full_edit: boolean
    can_report_edit: boolean
    can_complete: boolean
    can_cancel: boolean
  }
  application_actions?: { is_application: boolean; can_director_review: boolean; can_resubmit: boolean }
  material_summary?: { label: string; status: SampleStatus } | null
  id: string
  request_number: string
  intake_number?: string | null
  customer_account: string
  customer_name: string
  owner: CustomerEmployeeSummary | null
  requested_by?: CustomerEmployeeSummary | null
  status: SampleStatus
  status_display: string
  sample_type: string
  sample_type_display: string
  manual_request_number?: string | null
  shipping_method?: string
  shipping_method_display?: string
  order_date?: string | null
  sample_due_date?: string | null
  delivery_batch?: string
  delivery_batch_display?: string
  is_repeat_order?: boolean | null
  created_by?: CustomerEmployeeSummary | null
  submitted_on?: string | null
  products?: SampleListProduct[]
  etag: string
  item_summary: { text: string; count: number }
  current_fee: SampleFeeSummary | null
  latest_shipment: SampleShipmentSummary | null
  waiting_seconds?: number | null
  requested_at: string
  requested_due_at: string | null
  created_at: string
  updated_at: string
}

export interface SampleListProduct {
  id: string
  line_number: number
  category_name: string
  product_name: string
  specification: string
  color?: string
  task_sheet_file_id: string | null
  task_sheet_file_name: string
  total_sample_quantity: number
  length_cm: string | null
  armrest_width_cm: string | null
  seat_width_cm: string | null
  back_height_cm: string | null
  seat_height_cm: string | null
}

export interface SampleItemDetail {
  id: string
  line_number: number
  source_inquiry_item: string | null
  source_quotation_line: string | null
  product_description_snapshot: string
  specification_snapshot: string
  requested_quantity: string
  unit_code: string
  sample_product?: string | null
  product_color?: string | null
  color_card_snapshot?: string
  color_name_snapshot?: string
  color_code_snapshot?: string
  tolerance?: string
  sample_quantity?: number | null
  cutting_reported_quantity?: number
  metalwork_reported_quantity?: number
  cutting_completed?: boolean
  metalwork_completed?: boolean
  notes: string
}

export interface SampleProductDetail {
  id: string
  product_color_id: string | null
  color_card: string
  color_name: string
  color_code: string
  sample_quantity: number | null
  tolerance: string
  tolerance_display: string
  notes: string
  cutting_reported_quantity: number
  metalwork_reported_quantity: number
  cutting_completed: boolean
  metalwork_completed: boolean
}

export interface SampleProductSamplingDetail {
  id: string
  line_number: number
  template_key: string
  detail_type: string
  category_label: string
  is_selected: boolean
  description: string
  image_file_id: string | null
  image_file_name: string
  image_content_type: string
  image_size_bytes: number
}

export interface SampleProduct {
  id: string
  line_number: number
  source_inquiry_item_id: string | null
  source_quotation_line_id: string | null
  category_id: string | null
  category_name: string
  product_name: string
  specification: string
  task_sheet_file_id: string | null
  task_sheet_file_name: string
  task_sheet_content_type: string
  task_sheet_size_bytes: number
  length_cm: string | null
  armrest_width_cm: string | null
  seat_width_cm: string | null
  back_height_cm: string | null
  seat_height_cm: string | null
  total_sample_quantity: number
  details: SampleProductDetail[]
  sampling_details?: SampleProductSamplingDetail[]
}

export interface SampleDetail extends SampleListItem {
  reference_image?: string | null
  director_note?: string
  transaction_entity: string | null
  transaction_entity_name: string
  customer_contact: string | null
  customer_contact_name: string
  source_inquiry: string | null
  source_inquiry_number: string
  source_quotation_version: string | null
  source_quotation_id: string | null
  source_quotation_number: string
  manual_request_number?: string | null
  requested_by_employee?: string | null
  created_by_employee?: string | null
  created_by?: CustomerEmployeeSummary | null
  shipping_method?: string
  order_date?: string | null
  sample_due_date?: string | null
  delivery_batch?: string
  is_repeat_order?: boolean | null
  submitted_on?: string | null
  purpose: string
  notes: string
  expected_shipped_at: string | null
  expected_received_at: string | null
  collaborators: CustomerEmployeeSummary[]
  items: SampleItemDetail[]
  products?: SampleProduct[]

  fee_records: SampleFeeRecord[]
  fee_approvals: SampleFeeApproval[]
  shipments: SampleShipment[]
  feedback: SampleFeedback[]
  files: SampleFileLink[]
  workflow_records?: SampleWorkflowRecord[]
  workflow_actions?: SampleWorkflowActions
  parameter_images?: SampleParameterImage[]
  sla: Array<{ id: string; status: string; due_at: string | null }>
}

export interface SampleShipmentEvent {
  id: string
  event_type: 'SHIPPED' | 'DELIVERED' | 'EXCEPTION' | 'PROGRESS'
  event_type_display: string
  source: 'MANUAL' | 'CARRIER'
  source_display: string
  event_identifier: string
  source_object_version: number
  occurred_at: string
  synchronized_at: string | null
  payload_snapshot: { shipment_status?: string; carrier_code?: string; tracking_number?: string; note?: string; material_status?: string }
  recorded_by: CustomerEmployeeSummary | null
  created_at: string
}

export interface SampleShipment {
  id: string
  status: string
  status_display: string
  carrier_code: string
  tracking_number: string
  recipient_summary: { recipient_name: string; location: string }
  shipped_by: CustomerEmployeeSummary | null
  shipped_at: string | null
  delivered_at: string | null
  fee_warning_acknowledged: boolean
  notes: string
  items: Array<{ id: string; sample_item_id: string; product_description: string; shipped_quantity: string }>
  events: SampleShipmentEvent[]
  created_at: string
  updated_at: string
}

export interface SampleShipmentCreateInput {
  items: Array<{
    sample_item_id: string
    shipped_quantity: string
  }>
  notes?: string
}

export interface SampleShipmentProgressInput {
  occurred_at: string
  material_status: string
}

export interface SampleShipInput {
  address_id: string
  contact_id: string
  carrier_code: string
  tracking_number: string
  fee_warning_acknowledged: boolean
  fee_warning_reason?: string
  notes?: string
}

export interface SampleFeedback {
  id: string
  customer_contact: string | null
  recorded_by: CustomerEmployeeSummary | null
  feedback_type: string
  feedback_type_display: string
  feedback_content: string
  occurred_at: string
  confirmation_result: 'PENDING' | 'PASSED' | 'REJECTED'
  confirmation_result_display: string
  confirmation_source: 'CUSTOMER' | 'QUALITY' | 'MANUAL'
  confirmation_source_display: string
  source_object_version: number
  rejection_reason: string
  corrective_action_request: string
  confirmed_at: string | null
  requotation_source_version: string | null
  requotation_source_label: string
  resulting_quotation_version: string | null
  resulting_quotation_id: string | null
  resulting_quotation_label: string
  requotation_created_by: CustomerEmployeeSummary | null
  requotation_created_at: string | null
  created_at: string
}

export interface SampleFeedbackCreateInput {
  customer_contact_id?: string | null
  feedback_type: 'POSITIVE' | 'NEUTRAL' | 'NEGATIVE' | 'FOLLOW_UP'
  feedback_content: string
  occurred_at: string
  confirmation_result: 'PENDING' | 'PASSED' | 'REJECTED'
  confirmation_source: 'CUSTOMER' | 'QUALITY' | 'MANUAL'
  source_object_version: number
  rejection_reason?: string
  corrective_action_request?: string
}

export interface SampleRequotationOption {
  quotation_id: string
  quotation_number: string
  quotation_outcome_status: 'OPEN' | 'WON' | 'LOST' | 'CANCELLED'
  version_id: string
  version_number: number
  version_status: string
  currency_code: string
  subject: string
  updated_at: string
  is_sample_source: boolean
  target_mode: 'APPEND_VERSION' | 'CREATE_QUOTATION'
  target_label: string
}

export interface SampleRequotationCreateInput {
  source_quotation_version_id: string
  valid_until: string
  notes?: string
}

export interface SampleRequotationResult {
  quotation_id: string
  quotation_number: string
  quotation_version_id: string
  version_number: number
  created_new_quotation: boolean
  replayed: boolean
}

export interface SampleFeeRecord {
  id: string
  fee_decision: string
  fee_decision_display: string
  requested_decision: string
  amount: string
  currency_code: string
  sample_fee_amount: string
  shipping_fee_amount: string
  discount_amount: string
  payable_amount: string
  payment_terms: string
  freight_bearer: string
  payment_due_at: string | null
  account_reference: string
  approval_status: string
  approval_status_display: string
  verification_status: string
  verification_status_display: string
  decision_reason: string
  decided_by: CustomerEmployeeSummary | null
  free_confirmed_by: CustomerEmployeeSummary | null
  decided_at: string | null
  superseded_at: string | null
  created_at: string
}

export interface SampleFeeApproval {
  id: string
  approval_id: string
  status: string
  status_display: string
  approver: CustomerEmployeeSummary | null
  requested_by: CustomerEmployeeSummary | null
  request_reason: string
  decision_note: string
  submitted_at: string
  decided_at: string | null
  created_at: string
}

export interface SampleFeeCreateInput {
  fee_decision: 'PAID' | 'FREE' | 'WAIVED'
  currency_code: string
  sample_fee_amount?: string
  shipping_fee_amount?: string
  discount_amount?: string
  payment_terms?: string
  freight_bearer?: string
  payment_due_at?: string | null
  verification_status?: string
  decision_reason?: string
  free_confirmed_by_employee_id?: string | null
  approver_employee_id?: string | null
}

export interface SampleDetailUpdateInput {
  owner_employee_id?: string
  sample_type?: string
  purpose?: string
  requested_at?: string
  requested_due_at?: string | null
  expected_shipped_at?: string | null
  expected_received_at?: string | null
  collaborator_employee_ids?: string[]
  notes?: string
}

export interface SampleListResult {
  data: SampleListItem[]
  meta: PageMeta
}

export interface SampleStats {
  pending_director?: number
  pending_warehouse?: number
  pending_procurement?: number
  all: number
  pending_completion: number
  pending_payment: number
  pending_pmc: number
  pending_metalwork: number
  pending_cutting: number
  finished: number
  pending_shipment: number
  in_transit: number
  pending_feedback: number
  rejected: number
}

export interface SampleFileLink {
  id: string
  file_id: string
  original_name: string
  scan_status: string
  content_type: string
  size_bytes: number
  uploaded_by: CustomerEmployeeSummary | null
  file_role: string
  created_at: string
}

export type SampleWorkflowStage = 'MATERIALS_READY'
  | 'REQUEST_CREATED'
  | 'REQUIREMENTS_COMPLETED'
  | 'FINANCE_CONFIRMED'
  | 'PMC_APPROVED'
  | 'METALWORK_PARAMETERS'
  | 'CUTTING_PARAMETERS'
  | 'WORKFLOW_FINISHED'

export interface SampleWorkflowRecord {
  id: string
  stage: SampleWorkflowStage
  stage_display: string
  note: string
  file_id: string | null
  file_name: string
  file_content_type: string
  file_size_bytes: number
  operator: CustomerEmployeeSummary | null
  operated_at: string
}

export interface SampleParameterImage {
  id: string
  parameter_type: 'METALWORK' | 'CUTTING'
  parameter_type_display: string
  file_id: string
  file_name: string
  content_type: string
  size_bytes: number
  operator: CustomerEmployeeSummary | null
  uploaded_at: string
}

export interface SampleProductionReportItem {
  id: string
  metalwork_reported_quantity?: number
  cutting_reported_quantity?: number
  metalwork_completed?: boolean
  cutting_completed?: boolean
}

export interface SampleWorkflowActions {
  can_report_production?: boolean
  can_report_metalwork?: boolean
  can_report_cutting?: boolean
  can_finance_confirm: boolean
  can_pmc_approve: boolean
  can_upload_metalwork: boolean
  can_upload_cutting: boolean
}

export interface SampleListQuery {
  page: number
  page_size: number
  ordering?: string
  search?: string
  status?: string
  sample_type?: string
  owner_employee_id?: string
  customer_id?: string
  tracking_number?: string
  requested_from?: string
  requested_to?: string
}

export interface SampleCreateInput {
  customer_account_id: string
  owner_employee_id: string
  sample_type: string
  purpose: string
  requested_at: string
  items: Array<{
    product_description_snapshot: string
    requested_quantity: string
    unit_code: string
  }>
}

export interface SampleSourceLineInput {
  requested_quantity: number
}

export interface SampleFromInquiryCreateInput {
  inquiry_id: string
  sample_type: string
  purpose?: string
  sample_due_date?: string | null
  idempotency_key: string
  items: Array<SampleSourceLineInput & { source_item_id: string }>
}

export interface SampleFromQuotationCreateInput {
  quotation_version_id: string
  sample_type: string
  purpose?: string
  sample_due_date?: string | null
  idempotency_key: string
  items: Array<SampleSourceLineInput & { source_line_id: string }>
}

export interface SampleInventoryRow {
  id: string
  receipt_id: string
  receipt_number: string
  inbound_time: string
  operator_name: string
  sample_request_id: string
  sample_request_number: string
  product_category: string
  product_name: string
  specification: string
  color: string
  sampling_quantity: number
  received_quantity: number
  outbound_quantity: number
  loaned_quantity: number
  available_quantity: number
  location: string
}

export interface SampleInventoryQuery {
  page: number
  page_size: number
  ordering?: string
  q?: string
  category_name?: string
  location?: string
  inventory_status?: 'AVAILABLE' | 'DEPLETED'
}

export interface SampleInventoryResult {
  data: SampleInventoryRow[]
  meta: PageMeta
}

export interface SampleInventorySummary {
  current_available: number
  borrowed: number
  inbound_today: number
  outbound_today: number
}

export interface SampleInventoryOptions {
  product_categories: string[]
  locations: string[]
}

export interface SampleInventoryEligibleRow {
  sample_item_id: string
  sample_request_number: string
  flow_condition: string
  product_category: string
  product_name: string
  specification: string
  color: string
  sampling_quantity: number
  cumulative_received: number
  remaining_quantity: number
}

export interface SampleInventoryEligibleResult {
  data: SampleInventoryEligibleRow[]
  meta: PageMeta
}

export interface SampleFinishedGoodsOptions {
  warehouses: { id: string; warehouse_number: string; warehouse_name: string }[]
  zones: { id: string; warehouse_id: string; zone_name: string }[]
  locations: { id: string; warehouse_id: string; zone_id: string; location_number: string }[]
}

export interface SampleFinishedGoodsDestination {
  warehouse_id: string
  zone_id: string
  location_id: string
}

export interface SampleInventoryReceiptLineInput {
  sample_item_id: string
  received_quantity: number
  location: string
  expected_cumulative_received: number
}

export interface SampleInventoryReceiptCreated {
  receipt_id: string
  receipt_number: string
  submitted_by: string
  submitted_at: string
  line_count: number
}

export interface SampleInventoryReceiptDetailLine {
  id: string
  sample_item_id: string
  sample_request_id: string
  sample_request_number: string
  product_category: string
  product_name: string
  specification: string
  color: string
  sampling_quantity: number
  received_quantity: number
  cumulative_received: number
  location: string
  flow_condition: string
  source_status: string
  finished_goods_receipt_number: string
  finished_goods_warehouse: string
  finished_goods_zone: string
  finished_goods_location: string
}

export interface SampleInventoryReceiptDetail {
  receipt_id: string
  receipt_number: string
  document_type: string
  submitted_by: string
  submitted_at: string
  operation_source: string
  status: 'COMPLETED'
  status_display: string
  line_count: number
  lines: SampleInventoryReceiptDetailLine[]
}

export type SampleOutboundMethod = 'MERCHANDISER_MAIL' | 'SALESPERSON_CARRY' | 'OTHER'

export interface SampleOutboundEligibleRow {
  inventory_line_id: string
  receipt_number: string
  sample_request_number: string
  product_category: string
  product_name: string
  specification: string
  color: string
  available_quantity: number
  location: string
}

export interface SampleOutboundEligibleResult {
  data: SampleOutboundEligibleRow[]
  meta: PageMeta
}

export interface SampleOutboundCreateLineInput {
  inventory_line_id: string
  outbound_quantity: number
  outbound_method: SampleOutboundMethod
  courier_company: string
  tracking_number: string
  remark: string
  expected_available_quantity: number
}

export interface SampleOutboundCreated {
  outbound_id: string
  outbound_number: string
  operated_by: string
  operated_at: string
  line_count: number
}

export interface SampleOutboundDetailLine {
  id: string
  inventory_line_id: string
  receipt_id: string
  receipt_number: string
  sample_request_id: string
  sample_request_number: string
  product_name: string
  specification: string
  color: string
  outbound_quantity: number
  outbound_method: SampleOutboundMethod
  outbound_method_display: string
  courier_company: string
  tracking_number: string
  remark: string
}

export interface SampleOutboundDetail {
  outbound_id: string
  outbound_number: string
  document_type: string
  submitted_by: string
  submitted_at: string
  operation_source: string
  status: 'COMPLETED'
  status_display: string
  line_count: number
  lines: SampleOutboundDetailLine[]
}

export interface SampleOutboundRow {
  id: string
  outbound_id: string
  outbound_number: string
  operator_name: string
  operated_at: string
  sample_request_id: string
  sample_request_number: string
  product_category: string
  product_name: string
  specification: string
  color: string
  outbound_quantity: number
  outbound_method: SampleOutboundMethod
  outbound_method_display: string
  courier_company: string
  tracking_number: string
  remark: string
}

export interface SampleOutboundQuery {
  page: number
  page_size: number
  ordering?: string
  q?: string
  outbound_method?: SampleOutboundMethod
  category_name?: string
  operated_period?: 'TODAY' | 'THIS_MONTH' | 'LAST_30_DAYS'
}

export interface SampleOutboundResult {
  data: SampleOutboundRow[]
  meta: PageMeta
}

export interface SampleOutboundSummary {
  outbound_today: number
  outbound_this_month: number
  mailed: number
  salesperson_carried: number
}

export interface SampleOutboundMethodOption {
  value: SampleOutboundMethod
  label: string
}

export interface SampleOutboundOptions {
  outbound_methods: SampleOutboundMethodOption[]
  product_categories: string[]
}

export interface SampleLoanEligibleRow {
  inventory_line_id: string
  receipt_number: string
  sample_request_number: string
  product_category: string
  product_name: string
  specification: string
  color: string
  available_quantity: number
  location: string
}

export interface SampleLoanEligibleResult {
  data: SampleLoanEligibleRow[]
  meta: PageMeta
}

export interface SampleLoanCreateLineInput {
  inventory_line_id: string
  loan_quantity: number
  borrower_name: string
  purpose_note: string
  expected_available_quantity: number
}

export interface SampleLoanCreated {
  loan_id: string
  loan_number: string
  operated_by: string
  operated_at: string
  line_count: number
}

export interface SampleLoanDetailLine {
  id: string
  inventory_line_id: string
  receipt_id: string
  receipt_number: string
  sample_request_id: string
  sample_request_number: string
  product_name: string
  specification: string
  color: string
  loan_quantity: number
  borrower_name: string
  purpose_note: string
  inventory_impact: string
}

export interface SampleLoanDetail {
  loan_id: string
  loan_number: string
  document_type: string
  submitted_by: string
  submitted_at: string
  operation_source: string
  status: 'ACTIVE'
  status_display: string
  inventory_status_display: string
  line_count: number
  lines: SampleLoanDetailLine[]
}

export interface SampleLoanRow {
  id: string
  loan_id: string
  loan_number: string
  operator_name: string
  operated_at: string
  sample_request_id: string
  sample_request_number: string
  product_category: string
  product_name: string
  specification: string
  color: string
  loan_quantity: number
  borrower_name: string
  purpose_note: string
}

export interface SampleLoanQuery {
  page: number
  page_size: number
  ordering?: string
  q?: string
  borrower_name?: string
  category_name?: string
  operated_period?: 'TODAY' | 'THIS_MONTH' | 'LAST_30_DAYS'
}

export interface SampleLoanResult {
  data: SampleLoanRow[]
  meta: PageMeta
}

export interface SampleLoanSummary {
  active_documents: number
  cumulative_borrowed: number
  customer_confirmation: number
  showroom_or_photo: number
}

export interface SampleLoanOptions {
  borrower_names: string[]
  product_categories: string[]
}
