import type {
  InquiryApiError, InquiryEmployee, InquiryListItem, InquiryOptions, InquiryPage,
  InquiryPriority, InquiryQuery, InquirySlaState, InquiryStatus
} from '../../typings/inquiry';

const inquiriesPath = '/erp-api/v1/inquiries/';
const statuses: readonly string[] = [
  'DRAFT', 'NEW', 'ANALYZING', 'READY_FOR_QUOTE', 'QUOTING', 'QUOTED',
  'FOLLOW_UP', 'QUOTE_ACCEPTED', 'CONVERTED', 'LOST', 'CLOSED', 'CANCELLED'
];
const priorities: readonly string[] = ['HIGH', 'MEDIUM', 'LOW'];
const slaStates: readonly string[] = ['NONE', 'NORMAL', 'DUE_SOON', 'BREACHED'];
const orderingFields = ['received_at', 'requested_due_at', 'submitted_at', 'created_at', 'updated_at'];

function apiError(code: InquiryApiError['code'], status: number, message: string): InquiryApiError {
  return Object.assign(new Error(message), { name: 'InquiryApiError' as const, code, status });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isUuid(value: unknown): value is string {
  return isString(value) && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return isNonNegativeInteger(value) && value > 0;
}

function isDateString(value: unknown): value is string {
  if (!isString(value) || !/^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?$/.test(value)) return false;
  const day = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isFinite(Date.parse(value)) && Number.isFinite(day.getTime()) && day.toISOString().slice(0, 10) === value.slice(0, 10);
}

function isStatus(value: unknown): value is InquiryStatus {
  return isString(value) && statuses.includes(value);
}

function isPriority(value: unknown): value is InquiryPriority {
  return isString(value) && priorities.includes(value);
}

function isSlaState(value: unknown): value is InquirySlaState {
  return isString(value) && slaStates.includes(value);
}

function isEmployee(value: unknown): value is InquiryEmployee {
  return isRecord(value) && isUuid(value.id) && isString(value.employee_code) && isString(value.display_name);
}

function isProductAmount(value: unknown): value is InquiryListItem['product_amount'] {
  return isRecord(value) && isNonNegativeInteger(value.item_count) && isNonNegativeInteger(value.missing_price_count)
    && value.missing_price_count <= value.item_count && Array.isArray(value.totals) && value.totals.every(total =>
      isRecord(total) && isString(total.currency_code) && /^[A-Z]{3}$/.test(total.currency_code)
      && isString(total.amount) && /^\d+(?:\.\d+)?$/.test(total.amount));
}

function isSlaSummary(value: unknown): value is InquiryListItem['sla_summary'] {
  return isRecord(value) && isSlaState(value.state)
    && (value.next_deadline_at === null || isDateString(value.next_deadline_at))
    && (value.remaining_seconds === null || (typeof value.remaining_seconds === 'number' && Number.isSafeInteger(value.remaining_seconds)))
    && (value.working_time === undefined || typeof value.working_time === 'boolean')
    && (value.stage_code === undefined || isString(value.stage_code))
    && (value.active_count === undefined || isNonNegativeInteger(value.active_count));
}

function isInquiry(value: unknown): value is InquiryListItem {
  return isRecord(value) && isUuid(value.id) && isString(value.inquiry_number) && isString(value.subject)
    && isRecord(value.customer) && isUuid(value.customer.id) && isString(value.customer.name) && isString(value.customer.country_code)
    && isRecord(value.source) && isString(value.source.code) && isString(value.source.display_name)
    && (value.priority === '' || isPriority(value.priority)) && isString(value.priority_display)
    && (value.owner === null || isEmployee(value.owner)) && isStatus(value.status) && isString(value.status_display)
    && isString(value.display_stage) && isString(value.display_stage_label) && typeof value.has_quotation === 'boolean'
    && isRecord(value.product_summary) && isString(value.product_summary.first_description) && isNonNegativeInteger(value.product_summary.item_count)
    && isProductAmount(value.product_amount) && isDateString(value.received_at) && isSlaSummary(value.sla_summary);
}

function isInquiryPage(value: unknown): value is InquiryPage {
  if (!isRecord(value) || !Array.isArray(value.data) || !isRecord(value.meta)) return false;
  return value.data.every(isInquiry) && isPositiveInteger(value.meta.page)
    && isPositiveInteger(value.meta.page_size) && value.meta.page_size <= 100
    && isPositiveInteger(value.meta.total_pages) && isNonNegativeInteger(value.meta.total);
}

function isInquiryOptions(value: unknown): value is InquiryOptions {
  return isRecord(value)
    && Array.isArray(value.statuses) && value.statuses.every(item => isRecord(item) && isStatus(item.code) && isString(item.display_name))
    && Array.isArray(value.priorities) && value.priorities.every(item => isRecord(item) && isPriority(item.code) && isString(item.display_name))
    && Array.isArray(value.sources) && value.sources.every(item => isRecord(item) && isString(item.item_code)
      && isString(item.display_name) && typeof item.sort_order === 'number' && Number.isSafeInteger(item.sort_order))
    && Array.isArray(value.owners) && value.owners.every(isEmployee)
    && Array.isArray(value.countries) && value.countries.every(isString);
}

function validateFilters(query: InquiryQuery): void {
  const strings = [query.q, query.source_code, query.country_code, query.product_q, query.amount_min, query.amount_currency];
  if (strings.some(value => value !== undefined && !isString(value))
    || (query.owner_employee_id !== undefined && query.owner_employee_id !== '' && !isUuid(query.owner_employee_id))) {
    throw apiError('INVALID_QUERY', 0, '询盘关键词、来源、国家、金额或负责人标识格式无效。');
  }
  const enums = [
    { value: query.status, allowed: statuses }, { value: query.priority, allowed: [...priorities, 'UNSET'] },
    { value: query.sla_state, allowed: ['NONE', 'DUE_SOON', 'BREACHED', 'RISK'] },
    { value: query.assignment_status, allowed: ['ASSIGNED', 'UNASSIGNED'] },
    { value: query.has_quotation, allowed: ['true', 'false'] },
    { value: query.ordering, allowed: orderingFields.flatMap(field => [field, `-${field}`]) }
  ];
  if (enums.some(({ value, allowed }) => value !== undefined && value !== '' && (!isString(value) || !allowed.includes(value)))) {
    throw apiError('INVALID_QUERY', 0, '询盘状态、优先级、处理时限、报价或排序条件无效。');
  }
}

function validateDateAndAmount(query: InquiryQuery): void {
  if ([query.received_from, query.received_to].some(value => value !== undefined && value !== '' && !isDateString(value))
    || (query.received_from && query.received_to && Date.parse(query.received_from) > Date.parse(query.received_to))) {
    throw apiError('INVALID_QUERY', 0, '接收日期必须有效，开始日期不能晚于结束日期。');
  }
  const amount = query.amount_min?.trim();
  const currency = query.amount_currency?.trim();
  if ((amount || currency) && (!amount || !/^\d{1,32}(?:\.\d{1,8})?$/.test(amount) || !currency || !/^[A-Za-z]{3}$/.test(currency))) {
    throw apiError('INVALID_QUERY', 0, '请同时填写非负金额和三位币种代码。');
  }
}

function inquiryQuery(query: InquiryQuery, includePagination = true): string {
  if (typeof query !== 'object' || query === null || Array.isArray(query)) {
    throw apiError('INVALID_QUERY', 0, '询盘筛选条件必须是对象。');
  }
  if ((query.page !== undefined && !isPositiveInteger(query.page))
    || (query.page_size !== undefined && (!isPositiveInteger(query.page_size) || query.page_size > 100))) {
    throw apiError('INVALID_QUERY', 0, '页码必须为正整数，每页条数须在 1 到 100 之间。');
  }
  validateFilters(query);
  validateDateAndAmount(query);
  const entries = Object.entries({
    ...(includePagination ? { page: query.page, page_size: query.page_size } : {}), ordering: query.ordering,
    q: query.q?.trim(), status: query.status, source_code: query.source_code?.trim(), country_code: query.country_code?.trim(),
    owner_employee_id: query.owner_employee_id, assignment_status: query.assignment_status, sla_state: query.sla_state,
    product_q: query.product_q?.trim(), received_from: query.received_from, received_to: query.received_to,
    has_quotation: query.has_quotation, priority: query.priority,
    amount_min: query.amount_min?.trim(), amount_currency: query.amount_currency?.trim().toUpperCase()
  }).filter(([, value]) => value !== undefined && value !== '').map(([key, value]) => [key, String(value)]);
  const search = new URLSearchParams(entries).toString();
  return search ? `?${search}` : '';
}

function httpMessage(body: unknown, status: number): string {
  if (isRecord(body) && isRecord(body.error) && isString(body.error.message)) return body.error.message;
  if (isRecord(body) && isString(body.detail)) return body.detail;
  if (status === 401) return 'ERP 登录已失效，请登录后重试。';
  if (status === 403) return '当前账号无权访问询盘数据。';
  if (status === 404) return '询盘数据或请求页码不存在，请刷新后重试。';
  return `ERP 请求失败（HTTP ${status}）。`;
}

async function requestResponse(path: string, signal?: AbortSignal, accept = 'application/json'): Promise<Response> {
  try {
    return await fetch(path, {
      method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: accept }, signal
    });
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
    throw apiError('INVALID_RESPONSE', response.status, 'ERP 返回的内容不是有效 JSON。');
  }
  if (!response.ok) throw apiError('HTTP_ERROR', response.status, httpMessage(body, response.status));
  return body;
}

export async function fetchInquiries(query: InquiryQuery, signal?: AbortSignal): Promise<InquiryPage> {
  const response = await requestResponse(`${inquiriesPath}${inquiryQuery(query)}`, signal);
  const body = await readJson(response);
  if (!isInquiryPage(body)) throw apiError('INVALID_RESPONSE', response.status, 'ERP 询盘列表或分页数据结构异常。');
  return body;
}

export async function fetchInquiryOptions(signal?: AbortSignal): Promise<InquiryOptions> {
  const response = await requestResponse(`${inquiriesPath}options/`, signal);
  const body = await readJson(response);
  if (!isRecord(body) || !isInquiryOptions(body.data)) {
    throw apiError('INVALID_RESPONSE', response.status, 'ERP 询盘筛选选项数据结构异常。');
  }
  return body.data;
}

export async function fetchInquiryExport(query: InquiryQuery, signal?: AbortSignal): Promise<Blob> {
  // DRF 使用 JSON 渲染器完成内容协商，导出视图随后返回 CSV HttpResponse。
  const response = await requestResponse(`${inquiriesPath}export/${inquiryQuery(query, false)}`, signal, 'text/csv, application/json');
  if (!response.ok) await readJson(response);
  if (response.headers.get('content-type')?.split(';')[0].trim().toLowerCase() !== 'text/csv') {
    throw apiError('INVALID_RESPONSE', response.status, 'ERP 导出响应不是 CSV 文件，请重试。');
  }
  try {
    return await response.blob();
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw apiError('NETWORK_ERROR', response.status, 'ERP 导出文件读取失败，请重试。');
  }
}
