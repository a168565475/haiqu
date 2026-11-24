import assert from 'node:assert/strict';
import { afterEach, mock, test } from 'node:test';
import { fetchComplaintOptions, fetchComplaints } from './complaints';

// 仅测试请求和响应边界；这些虚构记录不代表真实客诉验收。
const customerId = '00000000-0000-4000-8000-000000000001';
const typeId = '00000000-0000-4000-8000-000000000002';
const severityId = '00000000-0000-4000-8000-000000000003';
const ownerId = '00000000-0000-4000-8000-000000000004';
const complaint = {
  id: '00000000-0000-4000-8000-000000000005',
  complaint_code: 'UNIT-TEST-001',
  customer: { id: customerId, account_name: '测试客户' },
  source_order_reference: '',
  complaint_type: { id: typeId, item_code: 'QUALITY', display_name: '测试类型' },
  severity: { id: severityId, item_code: 'NORMAL', display_name: '测试等级' },
  status: 'ACCEPTED',
  status_label: '已受理',
  owner: { id: ownerId, display_name: '测试负责人' },
  sla_status: 'NORMAL',
  target_completion_at: '2026-10-30T08:00:00Z',
  updated_at: '2026-10-16T08:00:00Z'
};
const page = { data: [complaint], meta: { page: 1, page_size: 50, total: 1, total_pages: 1 } };
const options = {
  complaint_types: [complaint.complaint_type],
  severities: [complaint.severity],
  statuses: [{ value: 'ACCEPTED', label: '已受理' }],
  employees: [complaint.owner]
};

function respond(body: unknown, status = 200) {
  return mock.method(globalThis, 'fetch', async (_input: RequestInfo | URL, _init?: RequestInit) =>
    Response.json(body, { status }));
}

afterEach(() => mock.restoreAll());

test('列表通过独立同源 GET 编码全部筛选，传递取消信号且不带令牌', async () => {
  const request = respond(page);
  const controller = new AbortController();
  const result = await fetchComplaints({
    page: 1, page_size: 50, q: '质量 & A', customer_id: customerId,
    complaint_type_item_id: typeId, severity_item_id: severityId, owner_employee_id: ownerId,
    status: 'ACCEPTED', sla_status: 'NORMAL'
  }, controller.signal);

  assert.equal(result.data[0].complaint_code, 'UNIT-TEST-001');
  assert.equal(result.data[0].source_order_reference, '');
  assert.equal(result.meta.total, 1);
  const [url, init] = request.mock.calls[0].arguments;
  assert.equal(String(url).split('?')[0], '/erp-api/v1/complaints/');
  assert.deepEqual(Object.fromEntries(new URL(String(url), 'http://localhost').searchParams), {
    page: '1', page_size: '50', q: '质量 & A', customer_id: customerId,
    complaint_type_item_id: typeId, severity_item_id: severityId, owner_employee_id: ownerId,
    status: 'ACCEPTED', sla_status: 'NORMAL'
  });
  assert.equal(init?.method, 'GET');
  assert.equal(init?.credentials, 'same-origin');
  assert.equal(init?.cache, 'no-store');
  assert.equal(init?.signal, controller.signal);
  assert.equal(init?.body, undefined);
  const headers = new Headers(init?.headers);
  assert.equal(headers.get('accept'), 'application/json');
  assert.equal(headers.get('authorization'), null);
  assert.equal(headers.get('apifoxtoken'), null);
});

test('空筛选不发送，真实零结果保留正常空分页', async () => {
  const request = respond({ data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 1 } });
  const result = await fetchComplaints({ q: '  ', status: '', sla_status: '', customer_id: '' });
  assert.equal(request.mock.calls[0].arguments[0], '/erp-api/v1/complaints/');
  assert.deepEqual(result.data, []);
  assert.equal(result.meta.total, 0);
});

test('非法页码和每页条数在网络调用前失败', async () => {
  const request = respond(page);
  for (const query of [{ page: 0 }, { page: -1 }, { page: 1.5 }, { page_size: 0 }, { page_size: 101 }, { page_size: Number.NaN }]) {
    await assert.rejects(fetchComplaints(query), { name: 'ComplaintApiError', code: 'INVALID_QUERY', status: 0 });
  }
  assert.equal(request.mock.callCount(), 0);
});

test('四个 UUID 筛选均拒绝非法标识，避免触发后端 ORM 异常', async () => {
  const request = respond(page);
  for (const query of [
    { customer_id: 'bad-id' }, { complaint_type_item_id: 'bad-id' },
    { severity_item_id: 'bad-id' }, { owner_employee_id: 'bad-id' }
  ]) {
    await assert.rejects(fetchComplaints(query), { name: 'ComplaintApiError', code: 'INVALID_QUERY', status: 0 });
  }
  assert.equal(request.mock.callCount(), 0);
});

test('运行时非法枚举、多状态和非字符串查询不能越过边界', async () => {
  const request = respond(page);
  const invalidQueries: unknown[] = [
    { status: 'UNKNOWN' }, { status: 'ACCEPTED,CLOSED' }, { sla_status: 'UNKNOWN' },
    { q: 3 }, { customer_id: null }, null, []
  ];
  for (const query of invalidQueries) {
    await assert.rejects(async () => { await Reflect.apply(fetchComplaints, undefined, [query]); },
      { name: 'ComplaintApiError', code: 'INVALID_QUERY', status: 0 });
  }
  assert.equal(request.mock.callCount(), 0);
});

test('401、403、404 均保留 HTTP 状态和服务端错误信息', async () => {
  for (const status of [401, 403, 404]) {
    respond({ error: { code: 'TEST_ERROR', message: '测试错误消息' } }, status);
    await assert.rejects(fetchComplaints({}), {
      name: 'ComplaintApiError', code: 'HTTP_ERROR', status, message: '测试错误消息'
    });
    mock.restoreAll();
  }
});

test('非 JSON 网关错误保留 HTTP 状态', async () => {
  mock.method(globalThis, 'fetch', async () => new Response('<html>Bad gateway</html>', { status: 502 }));
  await assert.rejects(fetchComplaints({}), { name: 'ComplaintApiError', code: 'HTTP_ERROR', status: 502 });
});

test('网络失败明确报错而不是返回空列表', async () => {
  mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(fetchComplaints({}), { name: 'ComplaintApiError', code: 'NETWORK_ERROR', status: 0 });
});

test('网络请求取消保留原始 AbortError', async () => {
  const abort = new DOMException('Aborted', 'AbortError');
  mock.method(globalThis, 'fetch', async () => { throw abort; });
  await assert.rejects(fetchComplaints({}), error => error === abort);
});

test('读取响应体期间的取消也保留原始 AbortError', async () => {
  const abort = new DOMException('Aborted', 'AbortError');
  const response = new Response();
  mock.method(response, 'json', async () => { throw abort; });
  mock.method(globalThis, 'fetch', async () => response);
  await assert.rejects(fetchComplaints({}), error => error === abort);
});

test('HTTP 200 非 JSON 不被误判为有效列表', async () => {
  mock.method(globalThis, 'fetch', async () => new Response('<html>Login</html>'));
  await assert.rejects(fetchComplaints({}), { name: 'ComplaintApiError', code: 'INVALID_RESPONSE', status: 200 });
});

test('缺失或损坏列表字段和业务枚举不会被静默丢弃', async () => {
  for (const row of [
    { ...complaint, customer: null }, { ...complaint, owner: null },
    { ...complaint, complaint_code: 123 }, { ...complaint, status: 'UNKNOWN' },
    { ...complaint, sla_status: 'UNKNOWN' }, { ...complaint, severity: {} },
    { ...complaint, complaint_type: null }, { ...complaint, updated_at: null },
    { ...complaint, target_completion_at: 123 }
  ]) {
    respond({ ...page, data: [row] });
    await assert.rejects(fetchComplaints({}), { name: 'ComplaintApiError', code: 'INVALID_RESPONSE', status: 200 });
    mock.restoreAll();
  }
});

test('损坏分页信息不能转换成零结果', async () => {
  for (const body of [
    { ...page, data: null }, { ...page, meta: null },
    { ...page, meta: { ...page.meta, total: '1' } },
    { ...page, meta: { ...page.meta, total: -1 } },
    { ...page, meta: { ...page.meta, page: 0 } },
    { ...page, meta: { ...page.meta, page_size: 101 } },
    { ...page, meta: { ...page.meta, total_pages: 0 } }
  ]) {
    respond(body);
    await assert.rejects(fetchComplaints({}), { name: 'ComplaintApiError', code: 'INVALID_RESPONSE', status: 200 });
    mock.restoreAll();
  }
});

test('六个客诉状态和四种 SLA 状态均按服务端枚举读取', async () => {
  const statuses = ['ACCEPTED', 'RESPONSIBILITY_CONFIRMATION', 'SOLUTION_PLANNING', 'CUSTOMER_CONFIRMATION', 'CLOSED', 'CANCELLED'];
  for (const status of statuses) {
    respond({ ...page, data: [{ ...complaint, status }] });
    assert.equal((await fetchComplaints({})).data[0].status, status);
    mock.restoreAll();
  }
  for (const sla_status of ['NORMAL', 'AT_RISK', 'OVERDUE', 'COMPLETED']) {
    respond({ ...page, data: [{ ...complaint, sla_status }] });
    assert.equal((await fetchComplaints({})).data[0].sla_status, sla_status);
    mock.restoreAll();
  }
});

test('选项读取 data 信封中的字典、状态和员工并传递 signal', async () => {
  const request = respond({ data: options });
  const controller = new AbortController();
  const result = await fetchComplaintOptions(controller.signal);
  assert.equal(request.mock.calls[0].arguments[0], '/erp-api/v1/complaints/options/');
  assert.equal(request.mock.calls[0].arguments[1]?.signal, controller.signal);
  assert.equal(request.mock.calls[0].arguments[1]?.method, 'GET');
  assert.equal(result.complaint_types[0].id, typeId);
  assert.equal(result.severities[0].id, severityId);
  assert.deepEqual(result.statuses, [{ value: 'ACCEPTED', label: '已受理' }]);
  assert.equal(result.employees[0].id, ownerId);
});

test('尚未发布的空选项集合是合法结果，不添加虚构默认选项', async () => {
  respond({ data: { complaint_types: [], severities: [], statuses: [], employees: [] } });
  assert.deepEqual(await fetchComplaintOptions(), { complaint_types: [], severities: [], statuses: [], employees: [] });
});

test('选项缺失、非法 UUID 或损坏枚举时明确报错', async () => {
  for (const data of [
    { ...options, complaint_types: null }, { ...options, employees: [{ id: 'bad-id', display_name: '测试' }] },
    { ...options, statuses: [{ value: 'UNKNOWN', label: '未知' }] },
    { ...options, severities: [{ id: severityId, item_code: 'NORMAL' }] }
  ]) {
    respond({ data });
    await assert.rejects(fetchComplaintOptions(), { name: 'ComplaintApiError', code: 'INVALID_RESPONSE', status: 200 });
    mock.restoreAll();
  }
});

test('选项接口权限失败保留错误而不伪造空选项', async () => {
  respond({ detail: '测试无权访问' }, 403);
  await assert.rejects(fetchComplaintOptions(), {
    name: 'ComplaintApiError', code: 'HTTP_ERROR', status: 403, message: '测试无权访问'
  });
});
