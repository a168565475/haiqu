import type {
  ComplaintApiError,
  ComplaintDictionaryOption,
  ComplaintEmployee,
  ComplaintListItem,
  ComplaintOptions,
  ComplaintPage,
  ComplaintQuery,
  ComplaintSlaStatus,
  ComplaintStatus
} from '../../typings/complaint';

const complaintsPath = '/erp-api/v1/complaints/';
const complaintStatuses: readonly string[] = [
  'ACCEPTED', 'RESPONSIBILITY_CONFIRMATION', 'SOLUTION_PLANNING', 'CUSTOMER_CONFIRMATION', 'CLOSED', 'CANCELLED'
];
const slaStatuses: readonly string[] = ['NORMAL', 'AT_RISK', 'OVERDUE', 'COMPLETED'];

function apiError(code: ComplaintApiError['code'], status: number, message: string): ComplaintApiError {
  return Object.assign(new Error(message), { name: 'ComplaintApiError' as const, code, status });
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

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

function isStatus(value: unknown): value is ComplaintStatus {
  return isString(value) && complaintStatuses.includes(value);
}

function isSlaStatus(value: unknown): value is ComplaintSlaStatus {
  return isString(value) && slaStatuses.includes(value);
}

function isDictionaryOption(value: unknown): value is ComplaintDictionaryOption {
  return isRecord(value) && isUuid(value.id) && isString(value.item_code) && isString(value.display_name);
}

function isEmployee(value: unknown): value is ComplaintEmployee {
  return isRecord(value) && isUuid(value.id) && isString(value.display_name);
}

function isComplaint(value: unknown): value is ComplaintListItem {
  return isRecord(value) && isUuid(value.id) && isString(value.complaint_code)
    && isRecord(value.customer) && isUuid(value.customer.id) && isString(value.customer.account_name)
    && isString(value.source_order_reference) && isDictionaryOption(value.complaint_type)
    && isDictionaryOption(value.severity) && isStatus(value.status) && isString(value.status_label)
    && isEmployee(value.owner) && isSlaStatus(value.sla_status)
    && isString(value.target_completion_at) && isString(value.updated_at);
}

function isComplaintPage(value: unknown): value is ComplaintPage {
  if (!isRecord(value) || !Array.isArray(value.data) || !isRecord(value.meta)) return false;
  return value.data.every(isComplaint) && isPositiveInteger(value.meta.page)
    && isPositiveInteger(value.meta.page_size) && value.meta.page_size <= 100
    && isPositiveInteger(value.meta.total_pages) && typeof value.meta.total === 'number'
    && Number.isSafeInteger(value.meta.total) && value.meta.total >= 0;
}

function isComplaintOptions(value: unknown): value is ComplaintOptions {
  return isRecord(value)
    && Array.isArray(value.complaint_types) && value.complaint_types.every(isDictionaryOption)
    && Array.isArray(value.severities) && value.severities.every(isDictionaryOption)
    && Array.isArray(value.employees) && value.employees.every(isEmployee)
    && Array.isArray(value.statuses) && value.statuses.every(option =>
      isRecord(option) && isStatus(option.value) && isString(option.label));
}

function complaintQuery(query: ComplaintQuery): string {
  if (!isRecord(query)) throw apiError('INVALID_QUERY', 0, '客诉筛选条件必须是对象。');
  if ((query.page !== undefined && !isPositiveInteger(query.page))
    || (query.page_size !== undefined && (!isPositiveInteger(query.page_size) || query.page_size > 100))) {
    throw apiError('INVALID_QUERY', 0, '页码必须为正整数，每页条数须在 1 到 100 之间。');
  }
  const ids = [query.customer_id, query.complaint_type_item_id, query.severity_item_id, query.owner_employee_id];
  if (ids.some(value => value !== undefined && value !== '' && !isUuid(value))) {
    throw apiError('INVALID_QUERY', 0, '客户、客诉类型、等级或负责人标识格式无效。');
  }
  if ((query.q !== undefined && !isString(query.q))
    || (query.status !== undefined && query.status !== '' && !isStatus(query.status))
    || (query.sla_status !== undefined && query.sla_status !== '' && !isSlaStatus(query.sla_status))) {
    throw apiError('INVALID_QUERY', 0, '客诉关键词、处理状态或 SLA 筛选格式无效。');
  }
  const entries = Object.entries({
    page: query.page, page_size: query.page_size, q: query.q?.trim(), customer_id: query.customer_id,
    complaint_type_item_id: query.complaint_type_item_id, severity_item_id: query.severity_item_id,
    owner_employee_id: query.owner_employee_id, status: query.status, sla_status: query.sla_status
  }).filter(([, value]) => value !== undefined && value !== '').map(([key, value]) => [key, String(value)]);
  const search = new URLSearchParams(entries).toString();
  return search ? `?${search}` : '';
}

function httpMessage(body: unknown, status: number): string {
  if (isRecord(body) && isRecord(body.error) && isString(body.error.message)) return body.error.message;
  if (isRecord(body) && isString(body.detail)) return body.detail;
  if (status === 401) return 'ERP 登录已失效，请登录后重试。';
  if (status === 403) return '当前账号无权访问客诉数据。';
  if (status === 404) return '客诉数据或请求页码不存在，请刷新后重试。';
  return `ERP 请求失败（HTTP ${status}）。`;
}

async function requestJson(path: string, signal?: AbortSignal): Promise<{ body: unknown; status: number }> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    throw apiError('NETWORK_ERROR', 0, '无法连接 ERP 服务，请检查网络后重试。');
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error;
    if (!response.ok) throw apiError('HTTP_ERROR', response.status, httpMessage(null, response.status));
    throw apiError('INVALID_RESPONSE', response.status, 'ERP 返回的内容不是有效 JSON。');
  }
  if (!response.ok) throw apiError('HTTP_ERROR', response.status, httpMessage(body, response.status));
  return { body, status: response.status };
}

export async function fetchComplaints(query: ComplaintQuery, signal?: AbortSignal): Promise<ComplaintPage> {
  const { body, status } = await requestJson(`${complaintsPath}${complaintQuery(query)}`, signal);
  if (!isComplaintPage(body)) throw apiError('INVALID_RESPONSE', status, 'ERP 客诉列表或分页数据结构异常。');
  return body;
}

export async function fetchComplaintOptions(signal?: AbortSignal): Promise<ComplaintOptions> {
  const { body, status } = await requestJson(`${complaintsPath}options/`, signal);
  if (!isRecord(body) || !isComplaintOptions(body.data)) {
    throw apiError('INVALID_RESPONSE', status, 'ERP 客诉筛选选项数据结构异常。');
  }
  return body.data;
}
