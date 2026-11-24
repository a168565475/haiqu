import assert from 'node:assert/strict';
import { afterEach, mock, test } from 'node:test';
import { fetchInquiries, fetchInquiryExport, fetchInquiryOptions } from './inquiries';

// 虚构数据仅验证外部边界，不能替代真实询盘接口与页面验收。
const customerId = '00000000-0000-4000-8000-000000000001';
const ownerId = '00000000-0000-4000-8000-000000000002';
const owner = { id: ownerId, employee_code: 'UNIT-EMP', display_name: '测试负责人' };
const inquiry = {
  id: '00000000-0000-4000-8000-000000000003', inquiry_number: 'UNIT-INQUIRY', subject: '测试需求',
  customer: { id: customerId, name: '测试客户', country_code: 'CN' },
  source: { code: 'TEST_SOURCE', display_name: '测试来源' }, owner,
  priority: 'HIGH', priority_display: '高', status: 'NEW', status_display: '待确认',
  display_stage: 'PENDING_CONFIRMATION', display_stage_label: '已分配', has_quotation: false,
  product_summary: { first_description: '测试产品', item_count: 1 },
  product_amount: { item_count: 1, missing_price_count: 0, totals: [{ currency_code: 'USD', amount: '0.00000000' }] },
  received_at: '2026-10-16T08:00:00Z',
  sla_summary: { state: 'NORMAL', next_deadline_at: '2026-10-17T08:00:00Z', remaining_seconds: 3600,
    working_time: true, stage_code: 'RESPONSE', active_count: 1 }
};
const page = { data: [inquiry], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } };
const options = {
  statuses: [{ code: 'NEW', display_name: '待确认' }], priorities: [{ code: 'HIGH', display_name: '高' }],
  sources: [{ item_code: 'TEST_SOURCE', display_name: '测试来源', sort_order: 1 }], owners: [owner], countries: ['CN']
};

function respond(body: unknown, status = 200) {
  return mock.method(globalThis, 'fetch', async (_input: RequestInfo | URL, _init?: RequestInit) =>
    Response.json(body, { status }));
}

afterEach(() => mock.restoreAll());

test('列表使用独立同源只读 GET，编码筛选并传递取消信号，不携带 Token', async () => {
  const request = respond(page);
  const signal = new AbortController().signal;
  const query = { page: 1, page_size: 50, ordering: '-received_at' as const, q: '  测试 & 产品  ',
    status: 'NEW' as const, source_code: 'TEST_SOURCE', country_code: 'CN', owner_employee_id: ownerId,
    assignment_status: 'ASSIGNED' as const, sla_state: 'RISK' as const, product_q: ' 测试 / 零件 ',
    received_from: '2026-10-01T00:00:00+08:00', received_to: '2026-10-16T23:59:59+08:00',
    has_quotation: 'false' as const, priority: 'UNSET' as const, amount_min: '0', amount_currency: 'usd' };
  const result = await fetchInquiries(query, signal);
  assert.deepEqual(result, page);
  const [url, init] = request.mock.calls[0].arguments;
  assert.equal(String(url).split('?')[0], '/erp-api/v1/inquiries/');
  assert.deepEqual(Object.fromEntries(new URL(String(url), 'http://localhost').searchParams), {
    ...Object.fromEntries(Object.entries(query).map(([key, value]) => [key, String(value)])),
    q: '测试 & 产品', product_q: '测试 / 零件', amount_currency: 'USD'
  });
  assert.equal(init?.method, 'GET');
  assert.equal(init?.credentials, 'same-origin');
  assert.equal(init?.cache, 'no-store');
  assert.equal(init?.signal, signal);
  assert.equal(init?.body, undefined);
  assert.deepEqual([...new Headers(init?.headers)], [['accept', 'application/json']]);
});

test('空筛选不发送，未知查询字段不透传到业务接口', async () => {
  const request = respond({ data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 1 } });
  const result = await Reflect.apply(fetchInquiries, undefined, [{ q: '  ', status: '', priority: '', demo: 'figma', token: 'test' }]);
  assert.equal(request.mock.calls[0].arguments[0], '/erp-api/v1/inquiries/');
  assert.equal(result.meta.total, 0);
  assert.deepEqual(result.data, []);
});

test('页码、UUID、字符串、状态、优先级与筛选枚举在发请求前校验', async () => {
  const request = respond(page);
  const invalid: unknown[] = [null, [], { page: 0 }, { page: 1.5 }, { page_size: 101 }, { page_size: Number.NaN },
    { owner_employee_id: 'bad-id' }, { owner_employee_id: null }, { q: 5 }, { source_code: null },
    { country_code: [] }, { product_q: true }, { status: 'NEW,CLOSED' }, { status: 'UNKNOWN' },
    { priority: 'MED' }, { assignment_status: 'ALL' }, { sla_state: 'NORMAL' }, { has_quotation: true }];
  for (const query of invalid) {
    await assert.rejects(async () => { await Reflect.apply(fetchInquiries, undefined, [query]); },
      { name: 'InquiryApiError', code: 'INVALID_QUERY', status: 0 });
  }
  assert.equal(request.mock.callCount(), 0);
});

test('排序仅接受真实服务端支持的单个字段，不静默退回默认排序', async () => {
  const request = respond(page);
  for (const ordering of ['received_at', '-requested_due_at', 'submitted_at', '-created_at', 'updated_at']) {
    await Reflect.apply(fetchInquiries, undefined, [{ ordering }]);
  }
  assert.equal(request.mock.callCount(), 5);
  for (const ordering of ['customer', '-id', '-received_at,-id', 'UNSUPPORTED']) {
    await assert.rejects(async () => { await Reflect.apply(fetchInquiries, undefined, [{ ordering }]); },
      { code: 'INVALID_QUERY' });
  }
  assert.equal(request.mock.callCount(), 5);
});

test('金额筛选必须成对且为非负十进制字符串和三位币种，不转浮点数', async () => {
  const request = respond(page);
  for (const query of [{ amount_min: '1' }, { amount_currency: 'USD' }, { amount_min: '-1', amount_currency: 'USD' },
    { amount_min: 'NaN', amount_currency: 'USD' }, { amount_min: '1e3', amount_currency: 'USD' },
    { amount_min: '1', amount_currency: 'US1' }, { amount_min: 0, amount_currency: 'USD' }]) {
    await assert.rejects(async () => { await Reflect.apply(fetchInquiries, undefined, [query]); }, { code: 'INVALID_QUERY' });
  }
  assert.equal(request.mock.callCount(), 0);
  await fetchInquiries({ amount_min: '12345678901234567890123456789012.12345678', amount_currency: 'USD' });
  assert.equal(new URL(String(request.mock.calls[0].arguments[0]), 'http://localhost').searchParams.get('amount_min'),
    '12345678901234567890123456789012.12345678');
});

test('接收日期拒绝非法日期及反向区间，允许单边 ISO 日期筛选', async () => {
  const request = respond(page);
  for (const query of [{ received_from: 'invalid' }, { received_to: '2026-02-30T10:00:00Z' },
    { received_from: '2026-10-17T00:00:00Z', received_to: '2026-10-16T23:59:59Z' }]) {
    await assert.rejects(fetchInquiries(query), { code: 'INVALID_QUERY' });
  }
  assert.equal(request.mock.callCount(), 0);
  await fetchInquiries({ received_from: '2026-10-01T00:00:00+08:00' });
  assert.equal(request.mock.callCount(), 1);
});

test('HTTP错误保留状态与服务端消息，包括参数、登录、权限和页码错误', async () => {
  for (const status of [400, 401, 403, 404, 500]) {
    respond({ error: { code: 'TEST_ERROR', message: '测试错误消息' } }, status);
    await assert.rejects(fetchInquiries({}), { name: 'InquiryApiError', code: 'HTTP_ERROR', status, message: '测试错误消息' });
    mock.restoreAll();
  }
});

test('非JSON错误页保留HTTP状态；成功状态的非JSON明确失败', async () => {
  for (const status of [200, 401, 403, 404, 502]) {
    mock.method(globalThis, 'fetch', async () => new Response('<html>error</html>', { status }));
    await assert.rejects(fetchInquiries({}), { code: status === 200 ? 'INVALID_RESPONSE' : 'HTTP_ERROR', status });
    mock.restoreAll();
  }
});

test('网络失败明确抛错，不能伪装成空数据', async () => {
  mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(fetchInquiries({}), { name: 'InquiryApiError', code: 'NETWORK_ERROR', status: 0 });
});

test('请求及JSON读取期间的取消保留原始AbortError', async () => {
  const abort = new DOMException('Aborted', 'AbortError');
  mock.method(globalThis, 'fetch', async () => { throw abort; });
  await assert.rejects(fetchInquiries({}), error => error === abort);
  mock.restoreAll();
  const response = new Response();
  mock.method(response, 'json', async () => { throw abort; });
  mock.method(globalThis, 'fetch', async () => response);
  await assert.rejects(fetchInquiries({}), error => error === abort);
});

test('空负责人、未设置优先级、无产品、无SLA和超时负秒数都是合法响应', async () => {
  const row = { ...inquiry, owner: null, priority: '', priority_display: '',
    product_summary: { first_description: '', item_count: 0 },
    product_amount: { item_count: 0, missing_price_count: 0, totals: [] },
    sla_summary: { state: 'NONE', next_deadline_at: null, remaining_seconds: null } };
  respond({ ...page, data: [row] });
  assert.deepEqual((await fetchInquiries({})).data[0], row);
  mock.restoreAll();
  respond({ ...page, data: [{ ...inquiry, sla_summary: { ...inquiry.sla_summary, state: 'BREACHED', remaining_seconds: -65 } }] });
  assert.equal((await fetchInquiries({})).data[0].sla_summary.remaining_seconds, -65);
});

test('所有当前主状态均可读取，金额大值和多币种原样保留', async () => {
  const statuses = ['DRAFT', 'NEW', 'ANALYZING', 'READY_FOR_QUOTE', 'QUOTING', 'QUOTED',
    'FOLLOW_UP', 'QUOTE_ACCEPTED', 'CONVERTED', 'LOST', 'CLOSED', 'CANCELLED'];
  const totals = [{ currency_code: 'USD', amount: '12345678901234567890.12345678' }, { currency_code: 'CNY', amount: '0' }];
  for (const status of statuses) {
    respond({ ...page, data: [{ ...inquiry, status, product_amount: { item_count: 2, missing_price_count: 0, totals } }] });
    assert.deepEqual((await fetchInquiries({})).data[0].product_amount.totals, totals);
    mock.restoreAll();
  }
});

test('列表关键字段、嵌套字段、枚举、SLA和十进制金额损坏时拒绝响应', async () => {
  for (const row of [{ ...inquiry, customer: null }, { ...inquiry, owner: {} }, { ...inquiry, id: 'bad-id' },
    { ...inquiry, priority: 'UNKNOWN' }, { ...inquiry, status: 'UNKNOWN' }, { ...inquiry, has_quotation: 'false' },
    { ...inquiry, source: {} }, { ...inquiry, product_summary: { item_count: -1, first_description: '' } },
    { ...inquiry, product_amount: { item_count: 1, missing_price_count: 0, totals: [{ currency_code: 'USD', amount: 10 }] } },
    { ...inquiry, product_amount: { item_count: 1, missing_price_count: 2, totals: [] } },
    { ...inquiry, sla_summary: { ...inquiry.sla_summary, state: 'RISK' } },
    { ...inquiry, sla_summary: { ...inquiry.sla_summary, remaining_seconds: '60' } },
    { ...inquiry, sla_summary: { ...inquiry.sla_summary, working_time: 'true' } },
    { ...inquiry, received_at: 'invalid-date' }]) {
    respond({ ...page, data: [row] });
    await assert.rejects(fetchInquiries({}), { code: 'INVALID_RESPONSE', status: 200 });
    mock.restoreAll();
  }
});

test('分页结构异常不能转换成正常零结果', async () => {
  for (const body of [{ ...page, data: null }, { ...page, meta: null },
    { ...page, meta: { ...page.meta, total: '1' } }, { ...page, meta: { ...page.meta, total: -1 } },
    { ...page, meta: { ...page.meta, page: 0 } }, { ...page, meta: { ...page.meta, page_size: 101 } },
    { ...page, meta: { ...page.meta, total_pages: 0 } }]) {
    respond(body);
    await assert.rejects(fetchInquiries({}), { code: 'INVALID_RESPONSE', status: 200 });
    mock.restoreAll();
  }
});

test('选项独立GET读取真实结构并传递取消信号', async () => {
  const request = respond({ data: options });
  const signal = new AbortController().signal;
  assert.deepEqual(await fetchInquiryOptions(signal), options);
  assert.equal(request.mock.calls[0].arguments[0], '/erp-api/v1/inquiries/options/');
  assert.equal(request.mock.calls[0].arguments[1]?.signal, signal);
  assert.equal(request.mock.calls[0].arguments[1]?.credentials, 'same-origin');
});

test('选项允许真实空集合，不丢弃异常选项并伪装成功', async () => {
  const empty = { statuses: [], priorities: [], sources: [], owners: [], countries: [] };
  respond({ data: empty });
  assert.deepEqual(await fetchInquiryOptions(), empty);
  mock.restoreAll();
  for (const body of [{}, { data: null }, { data: { ...options, statuses: [{ code: 'UNKNOWN', display_name: '未知' }] } },
    { data: { ...options, priorities: [{ code: 'UNSET', display_name: '未设置' }] } },
    { data: { ...options, countries: [1] } }, { data: { ...options, owners: [null] } },
    { data: { ...options, sources: [{ item_code: 'X', display_name: 'X', sort_order: '1' }] } }]) {
    respond(body);
    await assert.rejects(fetchInquiryOptions(), { code: 'INVALID_RESPONSE' });
    mock.restoreAll();
  }
});

test('全量CSV导出保留过滤排序、去除分页，仅GET且不带令牌', async () => {
  const csv = '\ufeff询盘编号,客户名称\r\nUNIT-INQUIRY,测试客户\r\n';
  const request = mock.method(globalThis, 'fetch', async (_input: RequestInfo | URL, _init?: RequestInit) =>
    new Response(csv, { headers: { 'Content-Type': 'text/csv; charset=utf-8' } }));
  const signal = new AbortController().signal;
  const blob = await fetchInquiryExport({ q: ' 测试 & ', priority: 'HIGH', ordering: '-updated_at', page: 3, page_size: 20 }, signal);
  const [url, init] = request.mock.calls[0].arguments;
  assert.equal(String(url).split('?')[0], '/erp-api/v1/inquiries/export/');
  assert.deepEqual(Object.fromEntries(new URL(String(url), 'http://localhost').searchParams),
    { q: '测试 &', priority: 'HIGH', ordering: '-updated_at' });
  assert.ok((await blob.text()).includes('UNIT-INQUIRY'));
  assert.equal(init?.signal, signal);
  assert.equal(init?.method, 'GET');
  assert.equal(init?.credentials, 'same-origin');
  assert.equal(init?.cache, 'no-store');
  assert.equal(new Headers(init?.headers).get('authorization'), null);
  assert.equal(new Headers(init?.headers).get('accept'), 'text/csv, application/json');
});

test('导出HTTP错误仍保留服务端消息，JSON或HTML不能被当作CSV', async () => {
  for (const status of [400, 401, 403, 404]) {
    respond({ error: { message: '测试导出错误' } }, status);
    await assert.rejects(fetchInquiryExport({}), { code: 'HTTP_ERROR', status, message: '测试导出错误' });
    mock.restoreAll();
  }
  for (const contentType of ['application/json', 'text/html', 'application/octet-stream']) {
    mock.method(globalThis, 'fetch', async () => new Response('{}', { headers: { 'Content-Type': contentType } }));
    await assert.rejects(fetchInquiryExport({}), { code: 'INVALID_RESPONSE', status: 200 });
    mock.restoreAll();
  }
});

test('导出网络失败和响应体取消不返回伪CSV', async () => {
  mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(fetchInquiryExport({}), { code: 'NETWORK_ERROR' });
  mock.restoreAll();
  const abort = new DOMException('Aborted', 'AbortError');
  const response = new Response('', { headers: { 'Content-Type': 'text/csv' } });
  mock.method(response, 'blob', async () => { throw abort; });
  mock.method(globalThis, 'fetch', async () => response);
  await assert.rejects(fetchInquiryExport({}), error => error === abort);
});
