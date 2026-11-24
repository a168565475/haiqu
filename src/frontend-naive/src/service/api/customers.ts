import type {
  CustomerActivityStatus,
  CustomerCodeOption,
  CustomerDictionaryOption,
  CustomerListItem,
  CustomerListQuery,
  CustomerOptions,
  CustomerPage,
  ErpApiError
} from '../../typings/customer';

const customersPath = '/erp-api/v1/customers/';
const activityStatuses: readonly string[] = ['INSUFFICIENT_DATA', 'ACTIVE', 'FOLLOW_UP', 'HIGH_RISK', 'DORMANT'];
const orderingValues: readonly string[] = [
  'account_code', '-account_code', 'account_name', '-account_name',
  'created_at', '-created_at', 'updated_at', '-updated_at'
];

function apiError(code: ErpApiError['code'], status: number, message: string): ErpApiError {
  return Object.assign(new Error(message), { name: 'ErpApiError' as const, code, status });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isNullableString(value: unknown): value is string | null {
  return value === null || isString(value);
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0;
}

function isActivityStatus(value: unknown): value is CustomerActivityStatus {
  return isString(value) && activityStatuses.includes(value);
}

function isCodeOption(value: unknown): value is CustomerCodeOption {
  return isRecord(value) && isString(value.item_code) && isString(value.display_name);
}

function isDictionaryOption(value: unknown): value is CustomerDictionaryOption {
  return isRecord(value) && isCodeOption(value) && isString(value.id) && isString(value.description)
    && (value.disabled === undefined || typeof value.disabled === 'boolean');
}

function isRegion(value: unknown): value is CustomerListItem['primary_region'] {
  return value === null || (isRecord(value) && isString(value.id) && isString(value.region_name));
}

function isGrade(value: unknown): value is CustomerListItem['customer_grade'] {
  return value === null || (isRecord(value) && isCodeOption(value) && isString(value.id));
}

function isActivity(value: unknown): value is CustomerListItem['activity'] {
  return value === null || (isRecord(value) && isActivityStatus(value.activity_status) && isString(value.display_name));
}

function isOwner(value: unknown): value is CustomerListItem['primary_owner'] {
  return value === null || (isRecord(value) && isString(value.id)
    && isString(value.employee_code) && isString(value.display_name));
}

function isRecentOrder(value: unknown): value is CustomerListItem['recent_order'] {
  return value === null || (isRecord(value) && [
    value.id, value.order_number, value.order_date, value.status,
    value.status_display, value.currency_code, value.total_amount
  ].every(isString));
}

function isCustomer(value: unknown): value is CustomerListItem {
  if (!isRecord(value)) return false;
  return [value.id, value.account_code, value.account_name, value.english_name, value.primary_country_code].every(isString)
    && isRegion(value.primary_region) && isRegion(value.secondary_region)
    && isGrade(value.customer_grade) && isActivity(value.activity) && isOwner(value.primary_owner)
    && isNullableString(value.last_12m_sales_amount) && isRecentOrder(value.recent_order)
    && isNullableString(value.last_contact_at) && isNullableString(value.next_follow_up_at);
}

function isCustomerPage(value: unknown): value is CustomerPage {
  if (!isRecord(value) || !Array.isArray(value.data) || !isRecord(value.meta)) return false;
  return value.data.every(isCustomer) && isPositiveInteger(value.meta.page)
    && isPositiveInteger(value.meta.page_size) && isPositiveInteger(value.meta.total_pages)
    && typeof value.meta.total === 'number' && Number.isSafeInteger(value.meta.total) && value.meta.total >= 0;
}

function isCustomerOptions(value: unknown): value is CustomerOptions {
  return isRecord(value)
    && Array.isArray(value.country_options) && value.country_options.every(isDictionaryOption)
    && Array.isArray(value.customer_grades) && value.customer_grades.every(isDictionaryOption)
    && Array.isArray(value.activity_statuses) && value.activity_statuses.every(isCodeOption);
}

function customerQuery(query: CustomerListQuery): string {
  if ((query.page !== undefined && !isPositiveInteger(query.page))
    || (query.page_size !== undefined && (!isPositiveInteger(query.page_size) || query.page_size > 100))) {
    throw apiError('INVALID_QUERY', 0, '页码必须为正整数，每页条数须在 1 到 100 之间。');
  }
  if ((query.ordering !== undefined && !orderingValues.includes(query.ordering))
    || (query.activity_status !== undefined && !isActivityStatus(query.activity_status))
    || [query.q, query.customer_grade, query.country_code].some(value => value !== undefined && !isString(value))) {
    throw apiError('INVALID_QUERY', 0, '客户筛选条件格式无效。');
  }
  const entries = Object.entries({
    page: query.page, page_size: query.page_size, ordering: query.ordering, q: query.q,
    customer_grade: query.customer_grade, country_code: query.country_code, activity_status: query.activity_status
  }).filter(([, value]) => value !== undefined && value !== '').map(([key, value]) => [key, String(value)]);
  const search = new URLSearchParams(entries).toString();
  return search ? `?${search}` : '';
}

function httpMessage(body: unknown, status: number): string {
  if (isRecord(body) && isRecord(body.error) && isString(body.error.message)) return body.error.message;
  if (isRecord(body) && isString(body.detail)) return body.detail;
  if (status === 401) return 'ERP 登录已失效，请登录后重试。';
  if (status === 403) return '当前账号无权访问客户数据。';
  return `ERP 请求失败（HTTP ${status}）。`;
}

async function requestJson(path: string, signal?: AbortSignal): Promise<{ body: unknown; status: number }> {
  let response: Response;
  try {
    // ERP 只使用浏览器 Session，不复用模板请求层或携带演示站点令牌。
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

export async function fetchCustomers(query: CustomerListQuery, signal?: AbortSignal): Promise<CustomerPage> {
  const { body, status } = await requestJson(`${customersPath}${customerQuery(query)}`, signal);
  if (!isCustomerPage(body)) throw apiError('INVALID_RESPONSE', status, 'ERP 客户列表或分页数据结构异常。');
  return body;
}

export async function fetchCustomerOptions(signal?: AbortSignal): Promise<CustomerOptions> {
  const { body, status } = await requestJson(`${customersPath}options/`, signal);
  if (!isRecord(body) || !isCustomerOptions(body.data)) {
    throw apiError('INVALID_RESPONSE', status, 'ERP 客户筛选选项数据结构异常。');
  }
  return body.data;
}

export async function fetchErpSession(signal?: AbortSignal): Promise<{ authenticated: boolean }> {
  const { body, status } = await requestJson('/erp-api/auth/me/', signal);
  if (!isRecord(body) || typeof body.authenticated !== 'boolean') {
    throw apiError('INVALID_RESPONSE', status, 'ERP 登录状态数据结构异常。');
  }
  return { authenticated: body.authenticated };
}
