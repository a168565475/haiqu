import assert from 'node:assert/strict';
import { afterEach, mock, test } from 'node:test';
import { fetchCustomerOptions, fetchCustomers, fetchErpSession } from './customers';

// 仅为 API 边界单元测试构造数据；不代表真实客户或业务验收。
const customer = {
  id: 'customer-unit-test',
  account_code: 'TEST-001',
  account_name: '边界测试客户',
  english_name: '',
  primary_country_code: 'CN',
  primary_region: { id: 'region-test', region_name: '测试区域' },
  secondary_region: null,
  customer_grade: { id: 'grade-test', item_code: 'A', display_name: 'A 类' },
  activity: { activity_status: 'INSUFFICIENT_DATA', display_name: '数据不足' },
  primary_owner: { id: 'owner-test', employee_code: 'TEST-OWNER', display_name: '测试人员' },
  last_12m_sales_amount: '0.0000',
  recent_order: {
    id: 'order-test',
    order_number: 'TEST-ORDER',
    order_date: '2026-10-16',
    status: 'DRAFT',
    status_display: '草稿',
    currency_code: 'CNY',
    total_amount: '123.4500'
  },
  last_contact_at: null,
  next_follow_up_at: '2026-10-16T08:00:00Z'
};

const page = { data: [customer], meta: { page: 1, page_size: 20, total: 1, total_pages: 1 } };

function respond(body: unknown, status = 200) {
  return mock.method(globalThis, 'fetch', async (_input: RequestInfo | URL, _init?: RequestInit) => Response.json(body, { status }));
}

afterEach(() => mock.restoreAll());

test('客户查询通过独立同源 GET 编码筛选条件，保留分页及真实零金额', async () => {
  const request = respond(page);
  const controller = new AbortController();
  const result = await fetchCustomers(
    { page: 1, page_size: 20, ordering: '-updated_at', q: '测试 & A', customer_grade: 'A', country_code: 'CN', activity_status: 'INSUFFICIENT_DATA' },
    controller.signal
  );

  assert.equal(result.data[0].last_12m_sales_amount, '0.0000');
  assert.equal(result.data[0].recent_order?.order_number, 'TEST-ORDER');
  assert.deepEqual(result.meta, { page: 1, page_size: 20, total: 1, total_pages: 1 });
  const [url, options] = request.mock.calls[0].arguments;
  assert.equal(String(url).split('?')[0], '/erp-api/v1/customers/');
  const params = new URL(String(url), 'http://localhost').searchParams;
  assert.deepEqual(Object.fromEntries(params), {
    page: '1', page_size: '20', ordering: '-updated_at', q: '测试 & A', customer_grade: 'A', country_code: 'CN', activity_status: 'INSUFFICIENT_DATA'
  });
  assert.equal(options?.method, 'GET');
  assert.equal(options?.credentials, 'same-origin');
  assert.equal(options?.cache, 'no-store');
  assert.equal(options?.signal, controller.signal);
  assert.equal(options?.body, undefined);
  const headers = new Headers(options?.headers);
  assert.equal(headers.get('accept'), 'application/json');
  assert.equal(headers.get('authorization'), null);
  assert.equal(headers.get('apifoxToken'), null);
});

test('空筛选不发送，合法空分页保留为零条结果', async () => {
  const request = respond({ data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 1 } });
  const result = await fetchCustomers({ q: '', country_code: undefined });
  assert.equal(request.mock.calls[0].arguments[0], '/erp-api/v1/customers/');
  assert.deepEqual(result.data, []);
  assert.equal(result.meta.total, 0);
});

test('未配置的客户业务字段保留 null，不伪造默认等级或金额', async () => {
  respond({ ...page, data: [{ ...customer, primary_region: null, customer_grade: null, activity: null, primary_owner: null, last_12m_sales_amount: null, recent_order: null, next_follow_up_at: null }] });
  const result = await fetchCustomers({});
  assert.equal(result.data[0].activity, null);
  assert.equal(result.data[0].last_12m_sales_amount, null);
  assert.equal(result.data[0].primary_owner, null);
});

test('无效分页在发出网络请求前失败', async () => {
  const request = respond(page);
  await assert.rejects(fetchCustomers({ page: 0 }), { name: 'ErpApiError', code: 'INVALID_QUERY', status: 0 });
  await assert.rejects(fetchCustomers({ page_size: 101 }), { name: 'ErpApiError', code: 'INVALID_QUERY', status: 0 });
  assert.equal(request.mock.callCount(), 0);
});

test('401 和 403 保留 HTTP 状态与后端错误信息', async () => {
  for (const status of [401, 403]) {
    respond({ error: { code: 'PERMISSION_DENIED', message: '测试权限不足' } }, status);
    await assert.rejects(fetchCustomers({}), { name: 'ErpApiError', code: 'HTTP_ERROR', status, message: '测试权限不足' });
    mock.restoreAll();
  }
});

test('JSON 之外的网关错误也保留 HTTP 失败状态', async () => {
  mock.method(globalThis, 'fetch', async () => new Response('<html>Bad gateway</html>', { status: 502 }));
  await assert.rejects(fetchCustomers({}), { name: 'ErpApiError', code: 'HTTP_ERROR', status: 502 });
});

test('网络失败被标记为网络错误，不返回空列表', async () => {
  mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(fetchCustomers({}), { name: 'ErpApiError', code: 'NETWORK_ERROR', status: 0 });
});

test('请求取消保持 AbortError，允许页面忽略旧查询', async () => {
  const abort = new DOMException('Aborted', 'AbortError');
  mock.method(globalThis, 'fetch', async () => { throw abort; });
  await assert.rejects(fetchCustomers({}), error => error === abort);
});

test('HTTP 200 非 JSON 不被误判为成功', async () => {
  mock.method(globalThis, 'fetch', async () => new Response('<html>Login</html>'));
  await assert.rejects(fetchCustomers({}), { name: 'ErpApiError', code: 'INVALID_RESPONSE', status: 200 });
});

test('损坏列表、分页及嵌套字段不被静默丢弃', async () => {
  const malformed = [
    { data: null, meta: page.meta },
    { data: [], meta: { ...page.meta, total: '1' } },
    { data: [{ ...customer, account_name: 123 }], meta: page.meta },
    { data: [{ ...customer, activity: { activity_status: 'UNKNOWN', display_name: '未知' } }], meta: page.meta },
    { data: [{ ...customer, recent_order: {} }], meta: page.meta }
  ];
  for (const body of malformed) {
    respond(body);
    await assert.rejects(fetchCustomers({}), { name: 'ErpApiError', code: 'INVALID_RESPONSE', status: 200 });
    mock.restoreAll();
  }
});

test('筛选选项读取真实 data 信封中的三个选项集合', async () => {
  const request = respond({ data: {
    country_options: [{ id: 'country-test', item_code: 'CN', display_name: '中国', description: 'China' }],
    customer_grades: [{ id: 'grade-test', item_code: 'A', display_name: 'A 类', description: '' }],
    activity_statuses: [{ item_code: 'ACTIVE', display_name: '活跃' }]
  } });
  const result = await fetchCustomerOptions();
  assert.equal(request.mock.calls[0].arguments[0], '/erp-api/v1/customers/options/');
  assert.equal(result.country_options[0].item_code, 'CN');
  assert.equal(result.customer_grades[0].display_name, 'A 类');
  assert.equal(result.activity_statuses[0].item_code, 'ACTIVE');
});

test('缺少或损坏筛选选项时明确报错', async () => {
  respond({ data: { country_options: [], customer_grades: [], activity_statuses: [{ item_code: 'ACTIVE' }] } });
  await assert.rejects(fetchCustomerOptions(), { name: 'ErpApiError', code: 'INVALID_RESPONSE', status: 200 });
});

test('会话仅通过 GET 检查 ERP 登录态，未登录不等于网络失败', async () => {
  const request = respond({ authenticated: false, user: null });
  assert.deepEqual(await fetchErpSession(), { authenticated: false });
  assert.equal(request.mock.calls[0].arguments[0], '/erp-api/auth/me/');
  assert.equal(request.mock.calls[0].arguments[1]?.method, 'GET');
});

test('会话验证失败及损坏登录态不会被转换为已登录', async () => {
  respond({ error: { message: '测试登录失效' } }, 401);
  await assert.rejects(fetchErpSession(), { name: 'ErpApiError', code: 'HTTP_ERROR', status: 401 });
  mock.restoreAll();
  respond({ authenticated: 'false' });
  await assert.rejects(fetchErpSession(), { name: 'ErpApiError', code: 'INVALID_RESPONSE', status: 200 });
});
