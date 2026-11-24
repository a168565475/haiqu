import assert from 'node:assert/strict';
import { afterEach, mock, test } from 'node:test';
import {
  fetchCustomerContacts, fetchCustomerDetail, fetchCustomerEntities, fetchCustomerEntityAddresses,
  fetchCustomerRecordOptions, fetchCustomerRecords, fetchCustomerSummary, fetchCustomerTimeline
} from './customer-detail';

const id = '11111111-1111-4111-8111-111111111111';
const ownerId = '22222222-2222-4222-8222-222222222222';
const at = '2026-10-16T08:00:00+08:00';
const emptyPage = { data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 1 } };
const employee = { id: ownerId, employee_code: 'TEST', display_name: '测试员工', status: 'ACTIVE' };

function customerFixture() {
  return { id, account_code: 'TEST-CUSTOMER', account_name: '测试客户', english_name: '', short_name: '',
    lifecycle_stage: 'LEAD', lifecycle_stage_display: '线索', primary_country_code: 'CN', primary_region: null,
    secondary_region: null, customer_grade: null, activity: null, primary_owner: employee, primary_website_url: '',
    last_12m_sales_amount: null, recent_order: null, last_contact_at: null, next_follow_up_at: null,
    industry: null, inquiry_keywords: '', recorded_by: null, recorded_at: null, attention_level: null,
    first_source: null, latest_source: null, customer_types: [], customer_tags: [], customer_value: null, business_snapshot: null,
    lifetime_sales_amount: null, lifetime_sales_order_count: null, last_12m_sales_order_count: null, quotation_conversion_rate: null,
    source_system: '', external_id: '', notes: '', legacy_source_data: {}, archive_reason: '', current_assignments: [],
    interested_products: [], company_contact_methods: [], archived_at: null, created_at: at, updated_at: at,
    allowed_permissions: ['customers.view_customeraccount'] };
}

function contactFixture() {
  return { id, customer: { id, account_code: 'TEST', account_name: '测试客户' }, display_name: '测试联系人', english_name: '',
    position_title: '', department_name: '', preferred_language_code: '', timezone_code: '', is_key_contact: true, is_primary_contact: true,
    status: 'ACTIVE', status_display: '在职', methods: [{ id, method_type: 'EMAIL', method_type_display: '邮箱',
      display_value: 'fixture@example.test', masked_value: 'f***@example.test', is_primary: true, is_preferred: false }],
    active_roles: [{ id, role_type: 'BUYER', role_type_display: '采购' }], last_interaction: null, open_task_count: 0,
    left_effective_date: null, marketing_opt_out: false, archived_at: null, created_at: at, updated_at: at };
}

function respond(body: unknown, status = 200, headers?: HeadersInit) {
  return mock.method(globalThis, 'fetch', async (_input: RequestInfo | URL, _init?: RequestInit) => Response.json(body, { status, headers }));
}

afterEach(() => mock.restoreAll());

test('详情保留真实空值、记录级权限和ETag；summary保持服务端数值', async () => {
  const fixture = customerFixture();
  respond({ data: fixture }, 200, { ETag: '"customer-v1"' });
  assert.deepEqual(await fetchCustomerDetail(id), { data: fixture, etag: '"customer-v1"' });
  mock.restoreAll();
  const summary = { customer: fixture, primary_owner: employee, attention_level: null,
    counts: { entities: 0, contacts: 1, open_inquiries: 0, open_quotations: 0, active_samples: 0, open_complaints: 0, open_tasks: 2, overdue_tasks: 1 } };
  respond({ data: summary });
  assert.deepEqual(await fetchCustomerSummary(id), summary);
});

test('联系人身份和后端display_value保持原样，跨客户行与损坏结构被拒绝', async () => {
  const fixture = contactFixture();
  const page = { data: [fixture], meta: { ...emptyPage.meta, total: 1 } };
  respond(page);
  assert.deepEqual(await fetchCustomerContacts(id, {}), page);
  mock.restoreAll();
  respond({ ...page, data: [{ ...fixture, customer: { ...fixture.customer, id: ownerId } }] });
  await assert.rejects(fetchCustomerContacts(id, {}), { code: 'INVALID_RESPONSE' });
  mock.restoreAll();
  respond({ ...page, data: [{ ...fixture, methods: [{}] }] });
  await assert.rejects(fetchCustomerContacts(id, {}), { code: 'INVALID_RESPONSE' });
});

test('主体和地址只GET、空集合有效，保留资料完整度需要的字段', async () => {
  const entity = { id: ownerId, customer_account: id, entity_code: 'TEST-ENTITY', legal_name: '测试主体' };
  const fetchMock = respond({ data: [entity] });
  assert.deepEqual(await fetchCustomerEntities(id), [entity]);
  assert.equal(fetchMock.mock.calls[0].arguments[0], `/erp-api/v1/customers/${id}/entities/`);
  mock.restoreAll();
  const address = { id, transaction_entity: ownerId, address_code: 'TEST-ADDRESS', label: '', country_code: 'CN',
    state_province: '', city: '测试城市', postal_code: '', address_line1: '测试地址', address_line2: '',
    recipient_name: '', recipient_phone: '', is_verified: false };
  respond({ data: [address] });
  assert.deepEqual(await fetchCustomerEntityAddresses(ownerId), [address]);
  mock.restoreAll();
  respond({ data: [] });
  assert.deepEqual(await fetchCustomerEntities(id), []);
  assert.deepEqual(await fetchCustomerEntityAddresses(id), []);
});

test('真实存在的行字段按业务类型校验而不是将损坏列表当作空表', async () => {
  const quotation = { id, quotation_number: 'TEST-QUOTE', customer_account: id, customer_name: '测试客户', subject: '',
    owner: employee, display_status: 'DRAFT', display_status_label: '草稿', updated_at: at,
    current_version: { id, version_number: 1, currency_code: 'USD', total_amount: '0.00', valid_until: null } };
  const sample = { id, request_number: 'TEST-SAMPLE', customer_account: id, customer_name: '测试客户', sample_type: 'PRE_SALES',
    sample_type_display: '售前样', status: 'DRAFT', status_display: '草稿', owner: employee, item_summary: { text: '', count: 0 },
    latest_shipment: null, requested_at: at, updated_at: at };
  const order = { id, order_number: 'TEST-ORDER', customer_code: 'TEST', customer_name: '测试客户', customer_po_number: '',
    status: 'DRAFT', status_display: '草稿', source_type: 'DIRECT', source_type_display: '直接订单', currency_code: 'CNY',
    total_amount: '0.0000', salesperson: employee, next_delivery_date: null, order_date: '2026-10-16', updated_at: at };
  for (const [kind, row] of [['quotations', quotation], ['samples', sample], ['orders', order]] as const) {
    const page = { data: [row], meta: { ...emptyPage.meta, total: 1 } };
    respond(page);
    assert.deepEqual(await fetchCustomerRecords(kind, id, {}), page);
    mock.restoreAll();
    respond({ ...page, data: [{}] });
    await assert.rejects(fetchCustomerRecords(kind, id, {}), { code: 'INVALID_RESPONSE' });
    mock.restoreAll();
  }
});

test('客户UUID和分页无效时在请求前失败', async () => {
  const fetchMock = respond({});
  for (const invalid of ['', '../options', 'bad-id', 1, null]) {
    await assert.rejects(Reflect.apply(fetchCustomerDetail, null, [invalid]), { code: 'INVALID_QUERY', status: 0 });
    await assert.rejects(Reflect.apply(fetchCustomerRecords, null, ['tasks', invalid, {}]), { code: 'INVALID_QUERY' });
  }
  for (const query of [{ page: 0 }, { page_size: 101 }, { page: 1.2 }, { page_size: '20' }, null]) {
    await assert.rejects(Reflect.apply(fetchCustomerContacts, null, [id, query]), { code: 'INVALID_QUERY' });
  }
  assert.equal(fetchMock.mock.callCount(), 0);
});

test('所有关联业务始终携带customer_id并采用各模块真实过滤参数', async () => {
  const cases = [
    ['tasks', { q: '  test  ', status: 'PENDING', scope: 'TEAM', ownerId, subtype: 'INQUIRY_RESPONSE' }, 'tasks', { q: 'test', status: 'PENDING', scope: 'TEAM', assignee_employee_id: ownerId, task_type: 'INQUIRY_RESPONSE', ordering: 'due_at' }],
    ['inquiries', { q: 'test', status: 'NEW', ownerId, date: '2026-10-16' }, 'inquiries', { q: 'test', status: 'NEW', owner_employee_id: ownerId, ordering: '-received_at', received_from: '2026-10-16T00:00:00+08:00', received_to: '2026-10-16T23:59:59+08:00' }],
    ['quotations', { status: 'SENT', ownerId, subtype: 'USD', date: '2026-10-16' }, 'quotations', { display_status: 'SENT', owner_employee_id: ownerId, currency_code: 'USD', valid_to: '2026-10-16', ordering: '-updated_at' }],
    ['samples', { q: 'test', ownerId, date: '2026-10-16' }, 'sample-requests', { q: 'test', owner_employee_id: ownerId, requested_to: '2026-10-16', ordering: '-requested_at' }],
    ['orders', { q: 'test', status: 'DRAFT', subtype: 'DIRECT' }, 'sales-orders', { q: 'test', status: 'DRAFT', source_type: 'DIRECT' }],
    ['complaints', { status: 'ACCEPTED', ownerId, subtype: ownerId }, 'complaints', { status: 'ACCEPTED', owner_employee_id: ownerId, complaint_type_item_id: ownerId }]
  ] as const;
  for (const [kind, query, path, expected] of cases) {
    const fetchMock = respond(emptyPage);
    const signal = new AbortController().signal;
    assert.deepEqual(await fetchCustomerRecords(kind, id, { page: 1, page_size: 20, ...query }, signal), emptyPage);
    const [input, init] = fetchMock.mock.calls[0].arguments;
    const url = new URL(String(input), 'http://localhost');
    assert.equal(url.pathname, `/erp-api/v1/${path}/`);
    assert.deepEqual(Object.fromEntries(url.searchParams), { customer_id: id, page: '1', page_size: '20', ...expected });
    assert.deepEqual(init, { method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal });
    mock.restoreAll();
  }
});

test('非法业务种类/枚举/负责人/日期以及无效模块筛选不会被悄悄忽略', async () => {
  const fetchMock = respond(emptyPage);
  for (const [kind, query] of [
    ['invalid', {}], ['tasks', { scope: 'LEGACY' }], ['tasks', { status: 'INVALID' }],
    ['inquiries', { ownerId: '../x' }], ['inquiries', { date: '2026-02-30' }],
    ['quotations', { subtype: 'US' }], ['orders', { ownerId }], ['orders', { date: '2026-10-16' }],
    ['complaints', { subtype: 'bad-uuid' }], ['samples', { status: 'INVALID' }]
  ]) {
    await assert.rejects(Reflect.apply(fetchCustomerRecords, null, [kind, id, query]), { code: 'INVALID_QUERY' });
  }
  assert.equal(fetchMock.mock.callCount(), 0);
});

test('联系人读取当前客户的分页数据', async () => {
  const fetchMock = respond(emptyPage);
  assert.deepEqual(await fetchCustomerContacts(id, { page: 1, page_size: 20, q: '  buyer  ', status: 'ACTIVE' }), emptyPage);
  const url = new URL(String(fetchMock.mock.calls[0].arguments[0]), 'http://localhost');
  assert.equal(url.pathname, `/erp-api/v1/customers/${id}/contacts/`);
  assert.deepEqual(Object.fromEntries(url.searchParams), { page: '1', page_size: '20', q: 'buyer', status: 'ACTIVE' });
});

test('时间线把后端完整翻页链接转为游标，并只请求当前客户固定路径', async () => {
  const fixture = { data: [{ id, event_type: 'CREATED', source_type: 'CUSTOMER_ACCOUNT', source_id: id,
    title: '测试事件', summary: '', occurred_at: at, created_at: at, event_data: { actor_employee_id: ownerId } }],
  meta: { next: `http://localhost:8000/api/v1/customers/${id}/timeline/?cursor=abc%3D`, previous: null, page_size: 50 } };
  const fetchMock = respond(fixture);
  assert.deepEqual(await fetchCustomerTimeline(id, { cursor: 'abc=', event_type: 'CREATED', occurred_from: at }), {
    ...fixture, meta: { ...fixture.meta, next: 'abc=' }
  });
  const url = new URL(String(fetchMock.mock.calls[0].arguments[0]), 'http://localhost');
  assert.equal(url.pathname, `/erp-api/v1/customers/${id}/timeline/`);
  assert.deepEqual(Object.fromEntries(url.searchParams), { cursor: 'abc=', event_type: 'CREATED', occurred_from: at });
});

test('绝对和相对分页链接提取唯一游标，下一次请求不跟随链接主机', async () => {
  const cursor = 'cD0yMDI2LTEwLTE2KzAwJTNBMDAlM0EwMCUyQjAwJTNBMDA=';
  for (const link of [
    `http://localhost:8000/api/v1/customers/${id}/timeline/?cursor=${cursor}`,
    `https://example.test/erp-api/v1/customers/${id}/timeline/?cursor=${cursor}&event_type=CREATED`,
    `/api/v1/customers/${id}/timeline/?cursor=${cursor}`,
    `/erp-api/v1/customers/${id}/timeline/?cursor=${cursor}`,
    `?cursor=${cursor}`
  ]) {
    const fetchMock = respond({ data: [], meta: { next: link, previous: link, page_size: 50 } });
    const result = await fetchCustomerTimeline(id);
    assert.equal(result.meta.next, cursor);
    assert.equal(result.meta.previous, cursor);
    await fetchCustomerTimeline(id, { cursor: result.meta.next ?? undefined });
    assert.equal(fetchMock.mock.callCount(), 2);
    const nextRequest = String(fetchMock.mock.calls[1].arguments[0]);
    assert.ok(nextRequest.startsWith(`/erp-api/v1/customers/${id}/timeline/?`));
    assert.equal(new URL(nextRequest, 'http://localhost').searchParams.get('cursor'), cursor);
    mock.restoreAll();
  }
});

test('无游标保持null，缺失、重复、非法游标或非当前客户分页链接明确失败', async () => {
  respond({ data: [], meta: { next: null, previous: null, page_size: 50 } });
  assert.deepEqual((await fetchCustomerTimeline(id)).meta, { next: null, previous: null, page_size: 50 });
  mock.restoreAll();
  const path = `/api/v1/customers/${id}/timeline/`;
  for (const link of ['', `${path}?page=2`, `${path}?cursor=`, `${path}?cursor=abc%3D&cursor=abc%3D`,
    `${path}?cursor=not-a-cursor`, `${path}?cursor=abc%3D#ignored`,
    `/api/v1/customers/${ownerId}/timeline/?cursor=abc%3D`, '/api/v1/tasks/?cursor=abc%3D',
    'javascript:alert(1)', 'http://[', `https://user:secret@example.test${path}?cursor=abc%3D`]) {
    for (const field of ['next', 'previous']) {
      respond({ data: [], meta: { next: null, previous: null, page_size: 50, [field]: link } });
      await assert.rejects(fetchCustomerTimeline(id), { code: 'INVALID_RESPONSE', status: 200 });
      mock.restoreAll();
    }
  }
});

test('时间线输入cursor必须是游标，不能再次把完整URL传到后端', async () => {
  const fetchMock = respond({});
  for (const cursor of [`http://localhost/api/v1/customers/${id}/timeline/?cursor=abc%3D`, 'not-a-cursor', 'abc=\n']) {
    await assert.rejects(fetchCustomerTimeline(id, { cursor }), { code: 'INVALID_QUERY', status: 0 });
  }
  assert.equal(fetchMock.mock.callCount(), 0);
});

test('时间线来源使用真实source_type，保留精确event_type且翻页不丢筛选', async () => {
  for (const source_type of ['CUSTOMER_COMMUNICATION', 'BUSINESS_TASK', 'CUSTOMER_ACCOUNT', 'QUOTATION_VERSION']) {
    const fetchMock = respond({ data: [], meta: { next: null, previous: null, page_size: 50 } });
    await fetchCustomerTimeline(id, { source_type, event_type: 'COMMUNICATION_CREATED', cursor: 'abc=', occurred_from: at });
    const url = new URL(String(fetchMock.mock.calls[0].arguments[0]), 'http://localhost');
    assert.deepEqual(Object.fromEntries(url.searchParams), { source_type, event_type: 'COMMUNICATION_CREATED', cursor: 'abc=', occurred_from: at });
    mock.restoreAll();
  }
});

test('时间线来源边界拒绝非字符串、无效编码及超过80字符', async () => {
  const fetchMock = respond({});
  for (const source_type of [1, null, [], 'CUSTOMER ACCOUNT', 'customer_account', 'A'.repeat(81)]) {
    await assert.rejects(Reflect.apply(fetchCustomerTimeline, null, [id, { source_type }]), { code: 'INVALID_QUERY', status: 0 });
  }
  assert.equal(fetchMock.mock.callCount(), 0);
});

test('各模块options真实字段规范化为label/value，订单没有无效负责人筛选', async () => {
  const option = { value: 'CODE', label: '测试选项' };
  const cases = [
    ['tasks', { statuses: [option], assignees: [{ id: ownerId, name: '测试员工' }], task_types: [option] }, { statuses: [option], owners: [{ value: ownerId, label: '测试员工' }], subtypes: [option] }],
    ['inquiries', { statuses: [{ code: 'NEW', display_name: '待确认' }], owners: [{ id: ownerId, display_name: '测试员工' }] }, { statuses: [{ value: 'NEW', label: '待确认' }], owners: [{ value: ownerId, label: '测试员工' }], subtypes: [] }],
    ['quotations', { display_statuses: [option], owners: [], currencies: [option] }, { statuses: [option], owners: [], subtypes: [option] }],
    ['samples', { statuses: [option], owners: [], sample_types: [option] }, { statuses: [option], owners: [], subtypes: [option] }],
    ['orders', { statuses: [option], employees: [{ id: ownerId, display_name: '测试员工' }], source_types: [option] }, { statuses: [option], owners: [], subtypes: [option] }],
    ['complaints', { statuses: [option], employees: [], complaint_types: [{ id: ownerId, display_name: '测试客诉类型' }] }, { statuses: [option], owners: [], subtypes: [{ value: ownerId, label: '测试客诉类型' }] }]
  ] as const;
  for (const [kind, payload, expected] of cases) {
    const fetchMock = respond({ data: payload });
    assert.deepEqual(await fetchCustomerRecordOptions(kind), expected);
    assert.match(String(fetchMock.mock.calls[0].arguments[0]), /\/options\/$/);
    mock.restoreAll();
  }
});

for (const status of [401, 403, 404, 500]) {
  test(`HTTP ${status}不伪装空数据且保留服务端消息`, async () => {
    respond({ error: { message: '测试错误' } }, status);
    for (const read of [() => fetchCustomerDetail(id), () => fetchCustomerSummary(id), () => fetchCustomerContacts(id, {}),
      () => fetchCustomerTimeline(id, {}), () => fetchCustomerRecords('tasks', id, {}), () => fetchCustomerRecordOptions('orders'),
      () => fetchCustomerEntities(id), () => fetchCustomerEntityAddresses(id)]) {
      await assert.rejects(read, { name: 'CustomerDetailApiError', code: 'HTTP_ERROR', status, message: '测试错误' });
    }
  });
}

test('非JSON、缺失data或错误分页结构明确失败', async () => {
  mock.method(globalThis, 'fetch', async () => new Response('<html>login</html>'));
  await assert.rejects(fetchCustomerDetail(id), { code: 'INVALID_RESPONSE', status: 200 });
  mock.restoreAll();
  respond({ data: [], meta: { page: 0, page_size: 20, total: 0, total_pages: 1 } });
  await assert.rejects(fetchCustomerRecords('orders', id, {}), { code: 'INVALID_RESPONSE' });
  mock.restoreAll();
  respond({});
  await assert.rejects(fetchCustomerSummary(id), { code: 'INVALID_RESPONSE' });
  await assert.rejects(fetchCustomerRecordOptions('samples'), { code: 'INVALID_RESPONSE' });
});

test('网络中断明确失败，AbortError保持原样', async () => {
  mock.method(globalThis, 'fetch', async () => { throw new TypeError('offline'); });
  await assert.rejects(fetchCustomerTimeline(id, {}), { code: 'NETWORK_ERROR', status: 0 });
  mock.restoreAll();
  const abort = new DOMException('cancelled', 'AbortError');
  mock.method(globalThis, 'fetch', async () => { throw abort; });
  await assert.rejects(fetchCustomerContacts(id, {}), error => error === abort);
});
