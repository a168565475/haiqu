import type {
  InquiryAssignmentHistory, InquiryDetail, InquiryDetailApiError, InquiryDetailEmployee, InquiryFile,
  InquiryHandlingRule, InquiryItem, InquirySla, InquiryTask, InquiryTimelineEvent, InquiryTimelinePage, InquiryWorkCalendar
} from '../../typings/inquiry-detail';

const inquiriesPath = '/erp-api/v1/inquiries/';
const inquiryStatuses = ['DRAFT', 'NEW', 'ANALYZING', 'READY_FOR_QUOTE', 'QUOTING', 'QUOTED', 'FOLLOW_UP', 'QUOTE_ACCEPTED', 'CONVERTED', 'LOST', 'CLOSED', 'CANCELLED'];
const scanStatuses = ['PENDING', 'CLEAN', 'INFECTED', 'FAILED', 'SKIPPED'];
const taskStatuses = ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'];

function apiError(code: InquiryDetailApiError['code'], status: number, message: string): InquiryDetailApiError {
  return Object.assign(new Error(message), { name: 'InquiryDetailApiError' as const, code, status });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function hasStrings(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.every(key => isString(value[key]));
}

function isOneOf(value: unknown, choices: readonly string[]): boolean {
  return isString(value) && choices.includes(value);
}

function isUuid(value: unknown): value is string {
  return isString(value) && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

function isNullableUuid(value: unknown): boolean {
  return value === null || isUuid(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return isNonNegativeInteger(value) && value > 0;
}

function isDecimal(value: unknown): value is string {
  return isString(value) && /^\d+(?:\.\d+)?$/.test(value) && Number.isFinite(Number(value));
}

function isCurrency(value: unknown): boolean {
  return isString(value) && /^[A-Z]{3}$/.test(value);
}

function isDate(value: unknown): value is string {
  if (!isString(value) || !/^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?$/.test(value)) return false;
  const day = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isFinite(Date.parse(value)) && Number.isFinite(day.getTime()) && day.toISOString().slice(0, 10) === value.slice(0, 10);
}

function isNullableDate(value: unknown): boolean {
  return value === null || isDate(value);
}

function hasPermissions(value: Record<string, unknown>): boolean {
  return value.allowed_permissions === undefined || (Array.isArray(value.allowed_permissions) && value.allowed_permissions.every(isString));
}

function isEmployee(value: unknown): value is InquiryDetailEmployee {
  return isRecord(value) && isUuid(value.id) && hasStrings(value, ['employee_code', 'display_name', 'status']);
}

function isProductImage(value: unknown): value is NonNullable<InquiryItem['product_image']> {
  return isRecord(value) && isUuid(value.id) && hasStrings(value, ['original_name', 'content_type'])
    && isNonNegativeInteger(value.size_bytes) && isOneOf(value.scan_status, scanStatuses);
}

function isItem(value: unknown): value is InquiryItem {
  return isRecord(value) && isUuid(value.id) && isPositiveInteger(value.line_number)
    && ['product_id', 'product_category_id', 'product_unit_id', 'product_color_id', 'product_image_id'].every(key => isNullableUuid(value[key]))
    && (value.product_image === null || isProductImage(value.product_image))
    && hasStrings(value, [
      'product_category_name', 'product_description', 'specification', 'color', 'material', 'unit_code', 'notes',
      'product_number_snapshot', 'product_code_snapshot', 'item_number_snapshot', 'customer_product_name_snapshot',
      'customer_specification_snapshot', 'customer_unit_code_snapshot', 'customer_color_snapshot', 'customer_material_snapshot'
    ])
    && isDecimal(value.quantity) && Number(value.quantity) > 0
    && (value.target_unit_price === null || isDecimal(value.target_unit_price))
    && (value.target_currency_code === '' || isCurrency(value.target_currency_code))
    && (value.expected_date === null || (isDate(value.expected_date) && value.expected_date.length === 10))
    && isOneOf(value.product_match_status, ['PENDING', 'MATCHED', 'NOT_REQUIRED'])
    && isDate(value.created_at) && isDate(value.updated_at);
}

function isFile(value: unknown): value is InquiryFile {
  return isRecord(value) && isUuid(value.file_id) && isString(value.file_role)
    && isDate(value.created_at) && isProductImage(value);
}

function isCalendar(value: unknown): value is InquiryWorkCalendar {
  if (!isRecord(value) || value.mode !== 'ALTERNATING_WEEKS_V1' || value.timezone !== 'Asia/Shanghai'
    || !isDate(value.rest_saturday) || value.rest_saturday.length !== 10
    || new Date(`${value.rest_saturday}T00:00:00Z`).getUTCDay() !== 6
    || !Array.isArray(value.periods) || value.periods.length === 0) return false;
  const periods: unknown[] = value.periods;
  return periods.every((period, index) => {
    if (!Array.isArray(period) || period.length !== 2 || !isNonNegativeInteger(period[0])
      || !isPositiveInteger(period[1]) || period[0] >= period[1] || period[1] > 1440) return false;
    const previous = periods[index - 1];
    return index === 0 || (Array.isArray(previous) && typeof previous[1] === 'number' && previous[1] <= period[0]);
  });
}

function isHandlingRule(value: unknown): value is InquiryHandlingRule {
  return isRecord(value) && isString(value.name)
    && [value.response_minutes, value.confirmation_minutes].every(minutes => minutes === null || isNonNegativeInteger(minutes))
    && (value.work_calendar === null || isCalendar(value.work_calendar))
    && isRecord(value.stage_minutes) && Object.values(value.stage_minutes).every(isNonNegativeInteger);
}

function isSla(value: unknown): value is InquirySla {
  if (!isRecord(value) || !isRecord(value.progress_context)) return false;
  const context = value.progress_context;
  return isUuid(value.id) && hasStrings(value, ['stage_code', 'policy_code', 'policy_name']) && typeof value.is_current === 'boolean'
    && isOneOf(value.status, ['RUNNING', 'MET', 'BREACHED', 'CANCELLED']) && isDate(value.started_at)
    && [value.next_deadline_at, value.breached_at, value.completed_at].every(isNullableDate)
    && (value.work_calendar === null || isCalendar(value.work_calendar))
    && (value.target_minutes === null || isNonNegativeInteger(value.target_minutes))
    && (context.round_number === null || isPositiveInteger(context.round_number))
    && [context.entry_reason, context.source_label, context.completion_reason].every(text => text === null || isString(text))
    && isNullableUuid(context.quotation_id);
}

function isAssignment(value: unknown): value is InquiryAssignmentHistory {
  return isRecord(value) && isUuid(value.id) && isDate(value.assigned_at)
    && hasStrings(value, ['assignment_reason', 'assignment_type'])
    && (value.previous_owner === null || isEmployee(value.previous_owner))
    && (value.new_owner === null || isEmployee(value.new_owner));
}

function isListSummary(value: Record<string, unknown>): boolean {
  const product = value.product_summary;
  const amount = value.product_amount;
  const sla = value.sla_summary;
  return isRecord(value.customer) && isUuid(value.customer.id) && hasStrings(value.customer, ['name', 'country_code'])
    && isRecord(value.source) && hasStrings(value.source, ['code', 'display_name'])
    && isRecord(product) && isString(product.first_description) && isNonNegativeInteger(product.item_count)
    && isRecord(amount) && isNonNegativeInteger(amount.item_count) && isNonNegativeInteger(amount.missing_price_count)
    && amount.missing_price_count <= amount.item_count && Array.isArray(amount.totals)
    && amount.totals.every(total => isRecord(total) && isCurrency(total.currency_code) && isDecimal(total.amount))
    && isRecord(sla) && isOneOf(sla.state, ['NONE', 'NORMAL', 'DUE_SOON', 'BREACHED']) && isNullableDate(sla.next_deadline_at)
    && (sla.remaining_seconds === null || (typeof sla.remaining_seconds === 'number' && Number.isSafeInteger(sla.remaining_seconds)))
    && (sla.working_time === undefined || typeof sla.working_time === 'boolean')
    && (sla.stage_code === undefined || isString(sla.stage_code))
    && (sla.active_count === undefined || isNonNegativeInteger(sla.active_count));
}

function isLinkedQuotation(value: unknown): value is InquiryDetail['linked_quotations'][number] {
  return isRecord(value) && isUuid(value.id) && hasStrings(value, ['quotation_number', 'subject', 'status', 'outcome_status'])
    && isNullableUuid(value.version_id) && isNullableUuid(value.accepted_version_id);
}

function isLinkedSample(value: unknown): value is InquiryDetail['linked_samples'][number] {
  return isRecord(value) && isUuid(value.id) && hasStrings(value, ['request_number', 'status', 'status_display']) && isDate(value.updated_at);
}

function isLinkedOrder(value: unknown): value is InquiryDetail['linked_sales_orders'][number] {
  return isRecord(value) && isUuid(value.id) && hasStrings(value, ['order_number', 'status', 'status_display'])
    && typeof value.is_draft === 'boolean' && isCurrency(value.currency_code) && isDate(value.updated_at)
    // SerializerMethodField 的 Decimal 经过 DRF JSON 编码为数值，兼容已有字符串金额响应。
    && (isDecimal(value.total_amount) || (typeof value.total_amount === 'number' && Number.isFinite(value.total_amount) && value.total_amount >= 0));
}

function isDetail(value: unknown): value is InquiryDetail {
  if (!isRecord(value) || !isRecord(value.allowed_actions)) return false;
  const actions = value.allowed_actions;
  return isUuid(value.id) && isUuid(value.customer_account) && hasPermissions(value) && isListSummary(value)
    && hasStrings(value, ['inquiry_number', 'subject', 'customer_name', 'inquiry_source', 'priority_display', 'status_display',
      'display_stage', 'display_stage_label', 'etag', 'description', 'source_system', 'external_id', 'customer_language_code',
      'trade_term_code', 'trade_term_place', 'delivery_requirement'])
    && isOneOf(value.priority, ['', 'HIGH', 'MEDIUM', 'LOW']) && isOneOf(value.status, inquiryStatuses)
    && (value.owner === null || isEmployee(value.owner))
    && [value.received_at, value.created_at, value.updated_at].every(isDate)
    && [value.requested_due_at, value.submitted_at, value.archived_at].every(isNullableDate)
    && [value.has_quotation, value.has_sent_quotation, value.has_active_sample].every(flag => typeof flag === 'boolean')
    && ['assign', 'set_priority', 'mark_invalid', 'lifecycle', 'create_quotation', 'attach_contact', 'respond',
      'confirm_requirements', 'follow_up', 'create_sample', 'create_sales_order'].every(key => typeof actions[key] === 'boolean')
    && isNullableUuid(value.transaction_entity) && isNullableUuid(value.customer_contact)
    && (value.customer_contact_summary === null || (isRecord(value.customer_contact_summary) && isUuid(value.customer_contact_summary.id)
      && hasStrings(value.customer_contact_summary, ['display_name', 'english_name', 'preferred_language_code'])))
    && isRecord(value.customer_snapshot) && isRecord(value.source_snapshot)
    && [value.estimated_amount_min, value.estimated_amount_max].every(amount => amount === null || isDecimal(amount))
    && (value.estimated_currency_code === '' || isCurrency(value.estimated_currency_code)) && isNonNegativeInteger(value.draft_version)
    && Array.isArray(value.items) && value.items.every(isItem) && Array.isArray(value.files) && value.files.every(isFile)
    && Array.isArray(value.sla) && value.sla.every(isSla)
    && (value.handling_time_rule === null || isHandlingRule(value.handling_time_rule))
    && Array.isArray(value.assignment_history) && value.assignment_history.every(isAssignment)
    && Array.isArray(value.linked_quotations) && value.linked_quotations.every(isLinkedQuotation)
    && Array.isArray(value.linked_samples) && value.linked_samples.every(isLinkedSample)
    && Array.isArray(value.linked_sales_orders) && value.linked_sales_orders.every(isLinkedOrder);
}

function isTimelineEvent(value: unknown): value is InquiryTimelineEvent {
  return isRecord(value) && isUuid(value.id) && isUuid(value.source_id)
    && hasStrings(value, ['event_type', 'source_type', 'title', 'summary']) && isDate(value.occurred_at)
    && isRecord(value.event_data) && (value.event_data.actor_employee_id === undefined || isNullableUuid(value.event_data.actor_employee_id));
}

function isTimelinePage(value: unknown): value is InquiryTimelinePage {
  if (!isRecord(value) || !Array.isArray(value.data) || !isRecord(value.meta)) return false;
  const meta = value.meta;
  return value.data.every(isTimelineEvent) && isPositiveInteger(meta.page) && meta.page_size === 20
    && isNonNegativeInteger(meta.total) && isPositiveInteger(meta.total_pages)
    && meta.total_pages === Math.max(1, Math.ceil(meta.total / meta.page_size)) && meta.page <= meta.total_pages
    && value.data.length <= Math.min(meta.page_size, meta.total);
}

function isTask(value: unknown): value is InquiryTask {
  if (!isRecord(value) || !isRecord(value.checklist_progress)) return false;
  const checklist = value.checklist_progress;
  return isUuid(value.id) && hasPermissions(value) && hasStrings(value, [
    'task_number', 'title', 'status_display', 'priority_display', 'task_type_display', 'origin_type_display',
    'work_state_display', 'work_state_reason', 'completion_result', 'cancel_reason'
  ]) && isOneOf(value.status, taskStatuses) && isOneOf(value.priority, ['LOW', 'NORMAL', 'HIGH', 'URGENT'])
    && isOneOf(value.task_type, ['CUSTOMER_FOLLOW_UP', 'COMMUNICATION_FOLLOW_UP', 'INQUIRY_RESPONSE', 'QUOTATION_FOLLOW_UP', 'SAMPLE_FEEDBACK', 'OTHER'])
    && isOneOf(value.origin_type, ['MANUAL', 'BUSINESS_EVENT', 'AUTOMATION', 'SLA'])
    && isOneOf(value.work_state, ['NORMAL', 'WAITING_CUSTOMER', 'BLOCKED'])
    && isOneOf(value.display_status, [...taskStatuses, 'BLOCKED', 'OVERDUE', 'WAITING_CUSTOMER'])
    && [value.next_check_at, value.due_at, value.completed_at, value.cancelled_at].every(isNullableDate)
    && isNonNegativeInteger(value.reschedule_count) && isPositiveInteger(value.business_version)
    && isEmployee(value.assignee) && (value.created_by === null || isEmployee(value.created_by))
    && (value.contact_summary === null || (isRecord(value.contact_summary) && isUuid(value.contact_summary.id) && hasStrings(value.contact_summary, ['name', 'position'])))
    && (value.customer === null || (isRecord(value.customer) && isUuid(value.customer.id) && hasStrings(value.customer, ['code', 'name'])))
    && (value.source === null || (isRecord(value.source) && isUuid(value.source.id) && hasStrings(value.source, ['code', 'title'])
      && isOneOf(value.source.type, ['CUSTOMER', 'COMMUNICATION', 'INQUIRY', 'QUOTATION_VERSION', 'SAMPLE_REQUEST'])
      && (value.source.open_url === null || isString(value.source.open_url))))
    && isNonNegativeInteger(checklist.completed) && isNonNegativeInteger(checklist.total) && checklist.completed <= checklist.total
    && isDate(value.created_at) && isDate(value.updated_at);
}

function inquiryPath(id: string): string {
  if (!isUuid(id)) throw apiError('INVALID_QUERY', 0, '询盘标识必须是有效的 UUID。');
  return `${inquiriesPath}${id}/`;
}

function httpMessage(body: unknown, status: number): string {
  if (isRecord(body)) {
    if (isRecord(body.error) && isString(body.error.message) && body.error.message.trim()) return body.error.message;
    if (isString(body.detail) && body.detail.trim()) return body.detail;
  }
  if (status === 401) return 'ERP 登录已失效，请重新登录。';
  if (status === 403) return '没有查看该询盘内容的权限。';
  if (status === 404) return '询盘、分页或附件不存在，或不在可查看范围内。';
  return `ERP 读取失败（HTTP ${status}），请重试。`;
}

async function requestResponse(path: string, signal?: AbortSignal, accept = 'application/json'): Promise<Response> {
  try {
    return await fetch(path, { method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: accept }, signal });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw apiError('NETWORK_ERROR', 0, '无法连接 ERP 服务，请检查网络后重试。');
  }
}

async function readJson(response: Response): Promise<unknown> {
  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    if (!response.ok) throw apiError('HTTP_ERROR', response.status, httpMessage(null, response.status));
    if (error instanceof SyntaxError) throw apiError('INVALID_RESPONSE', response.status, 'ERP 返回的内容不是有效 JSON。');
    throw apiError('NETWORK_ERROR', response.status, 'ERP 响应读取中断，请重试。');
  }
  if (!response.ok) throw apiError('HTTP_ERROR', response.status, httpMessage(body, response.status));
  return body;
}

export async function fetchInquiryDetail(id: string, signal?: AbortSignal): Promise<{ data: InquiryDetail; etag: string | null }> {
  const response = await requestResponse(inquiryPath(id), signal);
  const body = await readJson(response);
  if (!isRecord(body) || !isDetail(body.data) || body.data.id.toLowerCase() !== id.toLowerCase()) {
    throw apiError('INVALID_RESPONSE', response.status, 'ERP 询盘详情数据结构异常。');
  }
  return { data: body.data, etag: response.headers.get('etag') };
}

export async function fetchInquiryTimeline(id: string, page = 1, signal?: AbortSignal): Promise<InquiryTimelinePage> {
  const path = inquiryPath(id);
  if (!isPositiveInteger(page)) throw apiError('INVALID_QUERY', 0, '时间线页码必须是正整数。');
  const response = await requestResponse(`${path}timeline/?page=${page}&page_size=20`, signal);
  const body = await readJson(response);
  if (!isTimelinePage(body) || body.meta.page !== page) throw apiError('INVALID_RESPONSE', response.status, 'ERP 询盘时间线或分页数据结构异常。');
  return body;
}

export async function fetchInquiryTasks(id: string, signal?: AbortSignal): Promise<InquiryTask[]> {
  const response = await requestResponse(`${inquiryPath(id)}tasks/`, signal);
  const body = await readJson(response);
  if (!isRecord(body) || !Array.isArray(body.data) || !body.data.every(isTask)) {
    throw apiError('INVALID_RESPONSE', response.status, 'ERP 询盘关联任务数据结构异常。');
  }
  return body.data;
}

export async function fetchInquiryFile(id: string, fileId?: string, signal?: AbortSignal): Promise<Blob> {
  const path = inquiryPath(id);
  if (fileId !== undefined && !isUuid(fileId)) throw apiError('INVALID_QUERY', 0, '附件标识必须是有效的 UUID。');
  const suffix = fileId === undefined ? 'files-download/' : `files/${fileId}/download/`;
  // 保留 JSON 的内容协商能力，服务端错误不能被当成下载文件。
  const response = await requestResponse(`${path}${suffix}`, signal, 'application/octet-stream, application/zip, application/json');
  if (!response.ok) await readJson(response);
  const expectedType = fileId === undefined ? 'application/zip' : 'application/octet-stream';
  if (response.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== expectedType) {
    throw apiError('INVALID_RESPONSE', response.status, 'ERP 附件响应类型异常，请重试。');
  }
  try {
    return await response.blob();
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw apiError('NETWORK_ERROR', response.status, 'ERP 附件读取中断，请重试。');
  }
}

export function inquiryProductImageUrl(itemId: string): string {
  if (!isUuid(itemId)) throw apiError('INVALID_QUERY', 0, '产品明细标识必须是有效的 UUID。');
  return `/erp-api/v1/inquiry-items/${itemId}/product-image/`;
}
