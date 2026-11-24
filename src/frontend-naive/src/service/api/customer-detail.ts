import type { CustomerListItem } from '../../typings/customer';
import type {
  CustomerAddress, CustomerAssignment, CustomerBusinessSnapshot, CustomerContact, CustomerContactPage, CustomerContactQuery,
  CustomerDetail, CustomerDetailApiError, CustomerDictionary, CustomerEffective, CustomerEmployee, CustomerEntity,
  CustomerInquiry, CustomerOrder, CustomerPageMeta, CustomerQuotation, CustomerRecordKind, CustomerRecordMap,
  CustomerRecordOptions, CustomerRecordPage, CustomerRecordQuery, CustomerSample, CustomerSource, CustomerSummary,
  CustomerTask, CustomerTimelineEvent, CustomerTimelinePage, CustomerTimelineQuery
} from '../../typings/customer-detail';
import type { ComplaintListItem } from '../../typings/complaint';

const paths = { tasks: 'tasks', inquiries: 'inquiries', quotations: 'quotations', samples: 'sample-requests', orders: 'sales-orders', complaints: 'complaints' };
const statuses: Record<CustomerRecordKind, readonly string[]> = {
  tasks: ['PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'],
  inquiries: ['DRAFT', 'NEW', 'ANALYZING', 'READY_FOR_QUOTE', 'QUOTING', 'QUOTED', 'FOLLOW_UP', 'QUOTE_ACCEPTED', 'CONVERTED', 'LOST', 'CLOSED', 'CANCELLED'],
  quotations: ['DRAFT', 'LOCKED', 'READY_TO_SEND', 'SENT', 'ACCEPTED', 'EXPIRED', 'REJECTED', 'WITHDRAWN', 'SUPERSEDED'],
  samples: ['DRAFT', 'DIRECTOR_REVIEW', 'APPLICATION_RETURNED', 'MATERIALS_PENDING', 'WAREHOUSE_PENDING', 'PROCUREMENT_PENDING',
    'PROCUREMENT_IN_PROGRESS', 'MATERIALS_READY', 'MATERIAL_ISSUE_PENDING', 'MATERIAL_ISSUE_REVIEW', 'PENDING_COMPLETION', 'PENDING',
    'PMC_REVIEW', 'METALWORK_PENDING', 'CUTTING_PENDING', 'PRODUCTION_PENDING', 'FINISHED', 'PREPARING', 'SHIPPED', 'DELIVERED',
    'FEEDBACK_PENDING', 'CONFIRMED', 'COMPLETED', 'REJECTED', 'CANCELLED'],
  orders: ['DRAFT', 'CONFIRMED', 'FULFILLING', 'COMPLETED', 'PAUSED', 'CANCELLED'],
  complaints: ['ACCEPTED', 'RESPONSIBILITY_CONFIRMATION', 'SOLUTION_PLANNING', 'CUSTOMER_CONFIRMATION', 'CLOSED', 'CANCELLED']
};
const taskTypes = ['CUSTOMER_FOLLOW_UP', 'COMMUNICATION_FOLLOW_UP', 'INQUIRY_RESPONSE', 'QUOTATION_FOLLOW_UP', 'SAMPLE_FEEDBACK', 'OTHER'];
const sampleTypes = ['PRE_SALES', 'PRE_PRODUCTION', 'TESTING', 'BULK_CONFIRMATION'];

function apiError(code: CustomerDetailApiError['code'], status: number, message: string): CustomerDetailApiError {
  return Object.assign(new Error(message), { name: 'CustomerDetailApiError' as const, code, status });
}
function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
function isString(value: unknown): value is string { return typeof value === 'string'; }
function strings(value: Record<string, unknown>, keys: readonly string[]): boolean { return keys.every(key => isString(value[key])); }
function oneOf(value: unknown, choices: readonly string[]): boolean { return isString(value) && choices.includes(value); }
function isUuid(value: unknown): value is string { return isString(value) && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value); }
function isCount(value: unknown): value is number { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0; }
function isPositive(value: unknown): value is number { return isCount(value) && value > 0; }
function isDecimal(value: unknown): value is string { return isString(value) && /^\d+(?:\.\d+)?$/.test(value) && Number.isFinite(Number(value)); }
function nullableDecimal(value: unknown): boolean { return value === null || isDecimal(value); }
function isDate(value: unknown): value is string {
  if (!isString(value) || !/^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?$/.test(value)) return false;
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isFinite(Date.parse(value)) && Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value.slice(0, 10);
}
function nullableDate(value: unknown): boolean { return value === null || isDate(value); }
function isEmployee(value: unknown): value is CustomerEmployee {
  return isRecord(value) && isUuid(value.id) && strings(value, ['employee_code', 'display_name'])
    && (value.status === undefined || isString(value.status));
}
function isDictionary(value: unknown): value is CustomerDictionary { return isRecord(value) && isUuid(value.id) && strings(value, ['item_code', 'display_name']); }
function isEffective(value: unknown): value is CustomerEffective {
  return isRecord(value) && isString(value.reason) && isDate(value.effective_from) && nullableDate(value.effective_to) && isDictionary(value);
}
function isSource(value: unknown): value is CustomerSource {
  return isRecord(value) && isString(value.notes) && isDate(value.effective_from) && nullableDate(value.effective_to) && isDictionary(value);
}
function isAssignment(value: unknown): value is CustomerAssignment {
  return isRecord(value) && isUuid(value.id) && isEmployee(value.employee) && strings(value, ['assignment_role', 'reason'])
    && isDate(value.effective_from) && nullableDate(value.effective_to) && isDate(value.created_at);
}
function isSnapshot(value: unknown): value is CustomerBusinessSnapshot {
  return isRecord(value) && isUuid(value.id) && oneOf(value.source_type, ['MANUAL', 'ERP'])
    && strings(value, ['source_type_display', 'source_reference', 'currency_code', 'notes']) && isDate(value.as_of_at)
    && [value.customer_total_value, value.last_12m_order_amount, value.quote_conversion_rate, value.credit_limit, value.credit_used].every(nullableDecimal)
    && [value.last_12m_order_count, value.open_complaint_count].every(item => item === null || isCount(item))
    && (value.entered_by === null || isEmployee(value.entered_by)) && typeof value.is_current === 'boolean' && isDate(value.created_at);
}
function isCustomerBase(value: unknown): value is CustomerListItem {
  if (!isRecord(value)) return false;
  return isUuid(value.id) && strings(value, ['account_code', 'account_name', 'english_name', 'primary_country_code'])
    && [value.primary_region, value.secondary_region].every(region => region === null || (isRecord(region) && isUuid(region.id) && isString(region.region_name)))
    && (value.customer_grade === null || isDictionary(value.customer_grade))
    && (value.activity === null || (isRecord(value.activity) && isString(value.activity.display_name)
      && oneOf(value.activity.activity_status, ['INSUFFICIENT_DATA', 'ACTIVE', 'FOLLOW_UP', 'HIGH_RISK', 'DORMANT'])))
    && (value.primary_owner === null || isEmployee(value.primary_owner)) && nullableDecimal(value.last_12m_sales_amount)
    && nullableDate(value.last_contact_at) && nullableDate(value.next_follow_up_at)
    && (value.recent_order === null || (isRecord(value.recent_order) && isUuid(value.recent_order.id)
      && strings(value.recent_order, ['order_number', 'status', 'status_display', 'currency_code'])
      && isDate(value.recent_order.order_date) && isDecimal(value.recent_order.total_amount)));
}
function isCustomer(value: unknown): value is CustomerDetail {
  if (!isRecord(value)) return false;
  return strings(value, ['short_name', 'lifecycle_stage_display', 'primary_website_url', 'inquiry_keywords', 'source_system', 'external_id', 'notes', 'archive_reason'])
    && oneOf(value.lifecycle_stage, ['LEAD', 'VERIFIED', 'OPPORTUNITY', 'CUSTOMER', 'LOST'])
    && (value.allowed_permissions === undefined || (Array.isArray(value.allowed_permissions) && value.allowed_permissions.every(isString)))
    && (value.industry === null || isDictionary(value.industry)) && (value.recorded_by === null || isEmployee(value.recorded_by)) && nullableDate(value.recorded_at)
    && (value.attention_level === null || isEffective(value.attention_level))
    && [value.first_source, value.latest_source].every(source => source === null || isSource(source))
    && Array.isArray(value.customer_types) && value.customer_types.every(isEffective)
    && Array.isArray(value.customer_tags) && value.customer_tags.every(tag => isRecord(tag) && isUuid(tag.id) && strings(tag, ['tag_code', 'tag_name', 'color']))
    && [value.customer_value, value.business_snapshot].every(snapshot => snapshot === null || isSnapshot(snapshot))
    && [value.lifetime_sales_amount, value.quotation_conversion_rate].every(nullableDecimal)
    && [value.lifetime_sales_order_count, value.last_12m_sales_order_count].every(count => count === null || isCount(count))
    && isRecord(value.legacy_source_data) && Array.isArray(value.current_assignments) && value.current_assignments.every(isAssignment)
    && Array.isArray(value.interested_products) && value.interested_products.every(item => isRecord(item) && isUuid(item.id)
      && isUuid(item.product_item_id) && strings(item, ['item_code', 'display_name']))
    && Array.isArray(value.company_contact_methods) && value.company_contact_methods.every(item => isRecord(item) && isUuid(item.id)
      && oneOf(item.method_type, ['EMAIL', 'PHONE', 'SKYPE']) && strings(item, ['method_type_display', 'raw_value']) && typeof item.is_primary === 'boolean')
    && nullableDate(value.archived_at) && isDate(value.created_at) && isDate(value.updated_at) && isCustomerBase(value);
}
function isSummary(value: unknown): value is CustomerSummary {
  if (!isRecord(value) || !isRecord(value.counts)) return false;
  const counts = value.counts;
  return isCustomerBase(value.customer) && (value.primary_owner === null || isEmployee(value.primary_owner))
    && (value.attention_level === null || isEffective(value.attention_level))
    && ['entities', 'contacts', 'open_inquiries', 'open_quotations', 'active_samples', 'open_complaints', 'open_tasks', 'overdue_tasks'].every(key => isCount(counts[key]));
}
function isContact(value: unknown): value is CustomerContact {
  return isRecord(value) && isUuid(value.id) && isRecord(value.customer) && isUuid(value.customer.id) && strings(value.customer, ['account_code', 'account_name'])
    && strings(value, ['display_name', 'english_name', 'position_title', 'department_name', 'preferred_language_code', 'timezone_code', 'status_display'])
    && oneOf(value.status, ['ACTIVE', 'INACTIVE', 'LEFT'])
    && [value.is_key_contact, value.is_primary_contact, value.marketing_opt_out].every(flag => typeof flag === 'boolean')
    && Array.isArray(value.methods) && value.methods.every(item => isRecord(item) && isUuid(item.id)
      && oneOf(item.method_type, ['EMAIL', 'PHONE', 'MOBILE', 'WECHAT', 'WHATSAPP', 'OTHER'])
      && strings(item, ['method_type_display', 'display_value', 'masked_value']) && typeof item.is_primary === 'boolean' && typeof item.is_preferred === 'boolean')
    && Array.isArray(value.active_roles) && value.active_roles.every(role => isRecord(role) && isUuid(role.id) && strings(role, ['role_type', 'role_type_display']))
    && (value.last_interaction === null || (isRecord(value.last_interaction) && isDate(value.last_interaction.occurred_at)
      && (value.last_interaction.communication_type === null || isString(value.last_interaction.communication_type))))
    && isCount(value.open_task_count) && nullableDate(value.left_effective_date) && nullableDate(value.archived_at)
    && isDate(value.created_at) && isDate(value.updated_at);
}
function isTimelineEvent(value: unknown): value is CustomerTimelineEvent {
  return isRecord(value) && isUuid(value.id) && isUuid(value.source_id) && strings(value, ['event_type', 'source_type', 'title', 'summary'])
    && isDate(value.occurred_at) && isDate(value.created_at) && isRecord(value.event_data);
}
function isMeta(value: unknown): value is CustomerPageMeta {
  return isRecord(value) && isPositive(value.page) && isPositive(value.page_size) && value.page_size <= 100
    && isCount(value.total) && isPositive(value.total_pages) && value.page <= value.total_pages
    && value.total_pages === Math.max(1, Math.ceil(value.total / value.page_size));
}
function isPage<T>(value: unknown, isRow: (row: unknown) => row is T): value is { data: T[]; meta: CustomerPageMeta } {
  return isRecord(value) && Array.isArray(value.data) && isMeta(value.meta)
    && value.data.length <= Math.min(value.meta.total, value.meta.page_size) && value.data.every(isRow);
}
function isTask(value: unknown): value is CustomerTask {
  return isRecord(value) && isUuid(value.id) && strings(value, ['task_number', 'title', 'status_display', 'priority_display', 'task_type_display'])
    && oneOf(value.status, statuses.tasks) && oneOf(value.priority, ['LOW', 'NORMAL', 'HIGH', 'URGENT']) && oneOf(value.task_type, taskTypes)
    && nullableDate(value.due_at) && isEmployee(value.assignee) && isString(value.assignee.status)
    && (value.customer === null || (isRecord(value.customer) && isUuid(value.customer.id) && strings(value.customer, ['code', 'name'])))
    && (value.source === null || (isRecord(value.source) && isUuid(value.source.id) && strings(value.source, ['code', 'title'])
      && oneOf(value.source.type, ['CUSTOMER', 'COMMUNICATION', 'INQUIRY', 'QUOTATION_VERSION', 'SAMPLE_REQUEST'])
      && (value.source.open_url === null || isString(value.source.open_url))))
    && isDate(value.created_at) && isDate(value.updated_at);
}
function isInquiry(value: unknown): value is CustomerInquiry {
  if (!isRecord(value) || !isRecord(value.sla_summary) || !isRecord(value.product_amount)) return false;
  const sla = value.sla_summary;
  const amount = value.product_amount;
  return isUuid(value.id) && strings(value, ['inquiry_number', 'subject', 'priority_display', 'status_display', 'display_stage', 'display_stage_label'])
    && isRecord(value.customer) && isUuid(value.customer.id) && strings(value.customer, ['name', 'country_code'])
    && isRecord(value.source) && strings(value.source, ['code', 'display_name']) && (value.owner === null || isEmployee(value.owner))
    && oneOf(value.priority, ['', 'HIGH', 'MEDIUM', 'LOW']) && oneOf(value.status, statuses.inquiries) && typeof value.has_quotation === 'boolean'
    && isRecord(value.product_summary) && isString(value.product_summary.first_description) && isCount(value.product_summary.item_count)
    && isCount(amount.item_count) && isCount(amount.missing_price_count) && amount.missing_price_count <= amount.item_count
    && Array.isArray(amount.totals) && amount.totals.every(total => isRecord(total) && isString(total.currency_code) && isDecimal(total.amount))
    && oneOf(sla.state, ['NONE', 'NORMAL', 'DUE_SOON', 'BREACHED']) && nullableDate(sla.next_deadline_at)
    && (sla.remaining_seconds === null || (typeof sla.remaining_seconds === 'number' && Number.isSafeInteger(sla.remaining_seconds)))
    && (sla.working_time === undefined || typeof sla.working_time === 'boolean') && (sla.stage_code === undefined || isString(sla.stage_code))
    && (sla.active_count === undefined || isCount(sla.active_count)) && isDate(value.received_at) && nullableDate(value.requested_due_at);
}
function isQuotation(value: unknown): value is CustomerQuotation {
  return isRecord(value) && isUuid(value.id) && isUuid(value.customer_account)
    && strings(value, ['quotation_number', 'customer_name', 'subject', 'display_status_label'])
    && oneOf(value.display_status, statuses.quotations) && (value.owner === null || isEmployee(value.owner)) && isDate(value.updated_at)
    && (value.current_version === null || (isRecord(value.current_version) && isUuid(value.current_version.id)
      && isPositive(value.current_version.version_number) && isString(value.current_version.currency_code)
      && isDecimal(value.current_version.total_amount) && nullableDate(value.current_version.valid_until)));
}
function isSample(value: unknown): value is CustomerSample {
  return isRecord(value) && isUuid(value.id) && isUuid(value.customer_account)
    && strings(value, ['request_number', 'customer_name', 'sample_type_display', 'status_display'])
    && oneOf(value.status, statuses.samples) && oneOf(value.sample_type, sampleTypes) && (value.owner === null || isEmployee(value.owner))
    && isRecord(value.item_summary) && isString(value.item_summary.text) && isCount(value.item_summary.count)
    && (value.latest_shipment === null || (isRecord(value.latest_shipment) && strings(value.latest_shipment, ['status', 'status_display', 'tracking_number', 'carrier_code'])
      && nullableDate(value.latest_shipment.shipped_at) && nullableDate(value.latest_shipment.delivered_at)))
    && isDate(value.requested_at) && isDate(value.updated_at);
}
function isOrder(value: unknown): value is CustomerOrder {
  return isRecord(value) && isUuid(value.id) && strings(value, ['order_number', 'customer_code', 'customer_name', 'customer_po_number', 'status_display', 'source_type_display', 'currency_code'])
    && oneOf(value.status, statuses.orders) && oneOf(value.source_type, ['QUOTATION', 'DIRECT', 'REPEAT'])
    && isDecimal(value.total_amount) && isEmployee(value.salesperson) && nullableDate(value.next_delivery_date) && isDate(value.order_date) && isDate(value.updated_at);
}
function isComplaint(value: unknown): value is ComplaintListItem {
  return isRecord(value) && isUuid(value.id) && strings(value, ['complaint_code', 'source_order_reference', 'status_label'])
    && isRecord(value.customer) && isUuid(value.customer.id) && isString(value.customer.account_name)
    && isDictionary(value.complaint_type) && isDictionary(value.severity) && oneOf(value.status, statuses.complaints)
    && isRecord(value.owner) && isUuid(value.owner.id) && isString(value.owner.display_name)
    && oneOf(value.sla_status, ['NORMAL', 'AT_RISK', 'OVERDUE', 'COMPLETED']) && isDate(value.target_completion_at) && isDate(value.updated_at);
}
function isRecordRow<K extends CustomerRecordKind>(kind: K, value: unknown, id: string): value is CustomerRecordMap[K] {
  if (kind === 'tasks') return isTask(value) && (value.customer === null || value.customer.id === id);
  if (kind === 'inquiries') return isInquiry(value) && value.customer.id === id;
  if (kind === 'quotations') return isQuotation(value) && value.customer_account === id;
  if (kind === 'samples') return isSample(value) && value.customer_account === id;
  if (kind === 'orders') return isOrder(value);
  return isComplaint(value) && value.customer.id === id;
}

function requireId(id: string): void {
  if (!isUuid(id)) throw apiError('INVALID_QUERY', 0, '客户或关联对象标识必须是有效的 UUID。');
}
function customerPath(id: string, suffix = ''): string { requireId(id); return `/erp-api/v1/customers/${id}/${suffix}`; }
function requireKind(kind: CustomerRecordKind): void {
  if (!oneOf(kind, Object.keys(paths))) throw apiError('INVALID_QUERY', 0, '客户关联业务类型无效。');
}
function pageParams(query: CustomerContactQuery | CustomerRecordQuery): URLSearchParams {
  if (typeof query !== 'object' || query === null || Array.isArray(query)
    || !isPositive(query.page ?? 1) || !isPositive(query.page_size ?? 20) || (query.page_size ?? 20) > 100
    || (query.q !== undefined && !isString(query.q)) || (query.status !== undefined && !isString(query.status))) {
    throw apiError('INVALID_QUERY', 0, '分页、关键词或状态参数格式无效。');
  }
  const params = new URLSearchParams({ page: String(query.page ?? 1), page_size: String(query.page_size ?? 20) });
  if (query.q?.trim()) params.set('q', query.q.trim());
  if (query.status) params.set('status', query.status);
  return params;
}
function recordParams(kind: CustomerRecordKind, id: string, query: CustomerRecordQuery): URLSearchParams {
  requireKind(kind); requireId(id);
  const page = pageParams(query);
  const params = new URLSearchParams({ customer_id: id, ...Object.fromEntries(page) });
  if ([query.ownerId, query.subtype, query.date, query.scope].some(value => value !== undefined && !isString(value))
    || (query.status && !statuses[kind].includes(query.status)) || (query.ownerId && !isUuid(query.ownerId))
    || (query.date && (!isDate(query.date) || query.date.length !== 10))) throw apiError('INVALID_QUERY', 0, '业务状态、负责人或日期筛选无效。');
  if (query.date && !['inquiries', 'quotations', 'samples'].includes(kind)) throw apiError('INVALID_QUERY', 0, '此业务接口不支持日期筛选。');
  if (query.scope && kind !== 'tasks') throw apiError('INVALID_QUERY', 0, '只有任务接口支持任务范围筛选。');
  if (query.ownerId) {
    if (kind === 'orders') throw apiError('INVALID_QUERY', 0, '销售订单接口不支持负责人筛选。');
    params.set(kind === 'tasks' ? 'assignee_employee_id' : 'owner_employee_id', query.ownerId);
  }
  if (kind === 'tasks') {
    const scope = query.scope || 'ME';
    if (!oneOf(scope, ['ALL', 'TEAM', 'ME'])) throw apiError('INVALID_QUERY', 0, '任务范围无效。');
    params.set('scope', scope);
    params.set('ordering', 'due_at');
  }
  if (kind === 'inquiries') {
    params.set('ordering', '-received_at');
    if (query.date) { params.set('received_from', `${query.date}T00:00:00+08:00`); params.set('received_to', `${query.date}T23:59:59+08:00`); }
  }
  if (kind === 'quotations') {
    params.set('ordering', '-updated_at');
    if (query.status) { params.delete('status'); params.set('display_status', query.status); }
    if (query.date) params.set('valid_to', query.date);
  }
  if (kind === 'samples') {
    params.set('ordering', '-requested_at');
    if (query.date) params.set('requested_to', query.date);
  }
  if (query.subtype) {
    const subtype = query.subtype;
    if (kind === 'tasks' && oneOf(subtype, taskTypes)) params.set('task_type', subtype);
    else if (kind === 'quotations' && /^[A-Z]{3}$/.test(subtype)) params.set('currency_code', subtype);
    else if (kind === 'samples' && oneOf(subtype, sampleTypes)) params.set('sample_type', subtype);
    else if (kind === 'orders' && oneOf(subtype, ['QUOTATION', 'DIRECT', 'REPEAT'])) params.set('source_type', subtype);
    else if (kind === 'complaints' && isUuid(subtype)) params.set('complaint_type_item_id', subtype);
    else throw apiError('INVALID_QUERY', 0, '业务类型筛选无效。');
  }
  return params;
}
function isTimelineCursor(value: string): boolean {
  return value.length > 0 && value.length % 4 === 0
    && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value);
}
function timelineCursorFromLink(link: string | null, id: string, status: number): string | null {
  if (link === null) return null;
  const path = customerPath(id, 'timeline/');
  let url: URL;
  try { url = new URL(link, `http://erp.invalid${path}`); }
  catch { throw invalidResponse(status); }
  const cursors = url.searchParams.getAll('cursor');
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.hash
    || ![path, path.replace('/erp-api/', '/api/')].includes(url.pathname)
    || cursors.length !== 1 || !isTimelineCursor(cursors[0])) throw invalidResponse(status);
  return cursors[0];
}
function timelineParams(query: CustomerTimelineQuery): URLSearchParams {
  if (typeof query !== 'object' || query === null || Array.isArray(query)
    || [query.cursor, query.event_type, query.source_type, query.occurred_from, query.occurred_to].some(value => value !== undefined && !isString(value))
    || (query.cursor && !isTimelineCursor(query.cursor))
    || (query.event_type && query.event_type.length > 80)
    || (query.source_type && (query.source_type.length > 80 || !/^[A-Z0-9][A-Z0-9._-]*$/.test(query.source_type)))
    || [query.occurred_from, query.occurred_to].some(value => value && !isDate(value))
    || (query.occurred_from && query.occurred_to && Date.parse(query.occurred_from) > Date.parse(query.occurred_to))) {
    throw apiError('INVALID_QUERY', 0, '时间线筛选参数格式无效。');
  }
  const params = new URLSearchParams();
  for (const key of ['cursor', 'event_type', 'source_type', 'occurred_from', 'occurred_to'] as const) if (query[key]) params.set(key, query[key]);
  return params;
}
function httpMessage(body: unknown, status: number): string {
  if (isRecord(body)) {
    if (isRecord(body.error) && isString(body.error.message) && body.error.message.trim()) return body.error.message;
    if (isString(body.detail) && body.detail.trim()) return body.detail;
  }
  if (status === 401) return 'ERP 登录已失效，请重新登录。';
  if (status === 403) return '当前账号没有查看此客户资料或业务记录的权限。';
  if (status === 404) return '客户、业务记录或分页不存在，或不在可查看范围内。';
  return `ERP 读取失败（HTTP ${status}），请重试。`;
}
async function requestJson(path: string, signal?: AbortSignal): Promise<{ body: unknown; response: Response }> {
  let response: Response;
  try { response = await fetch(path, { method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal }); }
  catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw apiError('NETWORK_ERROR', 0, '无法连接 ERP 服务，请检查网络后重试。');
  }
  let body: unknown;
  try { body = await response.json(); }
  catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    if (!response.ok) throw apiError('HTTP_ERROR', response.status, httpMessage(null, response.status));
    if (error instanceof SyntaxError) throw apiError('INVALID_RESPONSE', response.status, 'ERP 返回的内容不是有效 JSON。');
    throw apiError('NETWORK_ERROR', response.status, 'ERP 响应读取中断，请重试。');
  }
  if (!response.ok) throw apiError('HTTP_ERROR', response.status, httpMessage(body, response.status));
  return { body, response };
}
function invalidResponse(status: number): CustomerDetailApiError { return apiError('INVALID_RESPONSE', status, 'ERP 客户资料或关联业务数据结构异常。'); }

export async function fetchCustomerDetail(id: string, signal?: AbortSignal): Promise<{ data: CustomerDetail; etag: string | null }> {
  const { body, response } = await requestJson(customerPath(id), signal);
  if (!isRecord(body) || !isCustomer(body.data) || body.data.id !== id) throw invalidResponse(response.status);
  return { data: body.data, etag: response.headers.get('etag') };
}
export async function fetchCustomerSummary(id: string, signal?: AbortSignal): Promise<CustomerSummary> {
  const { body, response } = await requestJson(customerPath(id, 'summary/'), signal);
  if (!isRecord(body) || !isSummary(body.data) || body.data.customer.id !== id) throw invalidResponse(response.status);
  return body.data;
}
export async function fetchCustomerContacts(id: string, query: CustomerContactQuery = {}, signal?: AbortSignal): Promise<CustomerContactPage> {
  const path = customerPath(id, 'contacts/');
  const params = pageParams(query);
  if (query.status && !oneOf(query.status, ['ACTIVE', 'INACTIVE', 'LEFT'])) throw apiError('INVALID_QUERY', 0, '联系人状态无效。');
  const { body, response } = await requestJson(`${path}?${params}`, signal);
  if (!isPage(body, isContact) || body.meta.page !== (query.page ?? 1) || body.meta.page_size !== (query.page_size ?? 20)
    || body.data.some(row => row.customer.id !== id)) throw invalidResponse(response.status);
  return body;
}
export async function fetchCustomerTimeline(id: string, query: CustomerTimelineQuery = {}, signal?: AbortSignal): Promise<CustomerTimelinePage> {
  const path = customerPath(id, 'timeline/');
  const params = timelineParams(query);
  const { body, response } = await requestJson(`${path}${params.size ? `?${params}` : ''}`, signal);
  if (!isRecord(body) || !Array.isArray(body.data) || !body.data.every(isTimelineEvent) || !isRecord(body.meta)
    || !isPositive(body.meta.page_size) || body.meta.page_size > 100
    || !(body.meta.next === null || isString(body.meta.next))
    || !(body.meta.previous === null || isString(body.meta.previous))) throw invalidResponse(response.status);
  // DRF 返回完整链接，页面只接收游标；后续请求仍由当前客户固定路径构造。
  return { data: body.data, meta: {
    next: timelineCursorFromLink(body.meta.next, id, response.status),
    previous: timelineCursorFromLink(body.meta.previous, id, response.status),
    page_size: body.meta.page_size
  } };
}
export async function fetchCustomerEntities(id: string, signal?: AbortSignal): Promise<CustomerEntity[]> {
  const { body, response } = await requestJson(customerPath(id, 'entities/'), signal);
  if (!isRecord(body) || !Array.isArray(body.data) || !body.data.every((value): value is CustomerEntity => isRecord(value)
    && isUuid(value.id) && value.customer_account === id && strings(value, ['entity_code', 'legal_name']))) throw invalidResponse(response.status);
  return body.data;
}
export async function fetchCustomerEntityAddresses(entityId: string, signal?: AbortSignal): Promise<CustomerAddress[]> {
  requireId(entityId);
  const { body, response } = await requestJson(`/erp-api/v1/customer-entities/${entityId}/addresses/`, signal);
  if (!isRecord(body) || !Array.isArray(body.data) || !body.data.every((value): value is CustomerAddress => isRecord(value)
    && isUuid(value.id) && value.transaction_entity === entityId && strings(value, ['address_code', 'label', 'country_code',
      'state_province', 'city', 'postal_code', 'address_line1', 'address_line2', 'recipient_name', 'recipient_phone'])
    && typeof value.is_verified === 'boolean')) throw invalidResponse(response.status);
  return body.data;
}
export async function fetchCustomerRecords<K extends CustomerRecordKind>(kind: K, id: string, query: CustomerRecordQuery = {}, signal?: AbortSignal): Promise<CustomerRecordPage<K>> {
  const params = recordParams(kind, id, query);
  const { body, response } = await requestJson(`/erp-api/v1/${paths[kind]}/?${params}`, signal);
  if (!isPage(body, (row): row is CustomerRecordMap[K] => isRecordRow(kind, row, id))
    || body.meta.page !== (query.page ?? 1) || body.meta.page_size !== (query.page_size ?? 20)) throw invalidResponse(response.status);
  return body;
}
function optionRows(value: unknown, valueKey: string, labelKey: string): CustomerRecordOptions['statuses'] | null {
  if (!Array.isArray(value)) return null;
  const result: CustomerRecordOptions['statuses'] = [];
  for (const row of value) {
    if (!isRecord(row)) return null;
    const optionValue = row[valueKey];
    const label = row[labelKey];
    if (!isString(optionValue) || !isString(label) || (valueKey === 'id' && !isUuid(optionValue))) return null;
    result.push({ value: optionValue, label });
  }
  return result;
}
export async function fetchCustomerRecordOptions(kind: CustomerRecordKind, signal?: AbortSignal): Promise<CustomerRecordOptions> {
  requireKind(kind);
  const { body, response } = await requestJson(`/erp-api/v1/${paths[kind]}/options/`, signal);
  if (!isRecord(body) || !isRecord(body.data)) throw invalidResponse(response.status);
  const data = body.data;
  const statusOptions = kind === 'inquiries' ? optionRows(data.statuses, 'code', 'display_name')
    : optionRows(kind === 'quotations' ? data.display_statuses : data.statuses, 'value', 'label');
  const owners = kind === 'orders' ? [] : kind === 'tasks' ? optionRows(data.assignees, 'id', 'name')
    : optionRows(kind === 'complaints' ? data.employees : data.owners, 'id', 'display_name');
  const subtypeKey = { tasks: 'task_types', inquiries: '', quotations: 'currencies', samples: 'sample_types', orders: 'source_types', complaints: 'complaint_types' }[kind];
  const subtypes = !subtypeKey ? [] : kind === 'complaints' ? optionRows(data[subtypeKey], 'id', 'display_name') : optionRows(data[subtypeKey], 'value', 'label');
  if (!statusOptions || !owners || !subtypes) throw invalidResponse(response.status);
  return { statuses: statusOptions, owners, subtypes };
}
