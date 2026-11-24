import assert from 'node:assert/strict';
import { afterEach, mock, test } from 'node:test';
import {
  fetchInquiryDetail, fetchInquiryFile, fetchInquiryTasks, fetchInquiryTimeline, inquiryProductImageUrl
} from './inquiry-detail';

const id = '11111111-1111-4111-8111-111111111111';
const fileId = '22222222-2222-4222-8222-222222222222';
const at = '2026-10-16T08:00:00+08:00';
const employee = { id, employee_code: 'TEST', display_name: '测试员工', status: 'ACTIVE' };
const calendar = {
  mode: 'ALTERNATING_WEEKS_V1', timezone: 'Asia/Shanghai', rest_saturday: '2026-09-05',
  periods: [[510, 720], [810, 1050]]
};

function detailFixture() {
  return {
    id, inquiry_number: 'TEST-INQUIRY', subject: '单元测试询盘', customer_account: id, customer_name: '测试客户',
    customer: { id, name: '测试客户', country_code: 'CN' }, source: { code: 'EMAIL', display_name: '邮件' },
    inquiry_source: 'EMAIL', priority: 'HIGH', priority_display: '高', owner: employee,
    product_summary: { first_description: '测试产品', item_count: 1 },
    product_amount: { item_count: 1, missing_price_count: 0, totals: [{ currency_code: 'USD', amount: '25.0000' }] },
    received_at: at, requested_due_at: null, submitted_at: at, created_at: at, updated_at: at, archived_at: null,
    status: 'ANALYZING', status_display: '需求分析中', display_stage: 'ANALYZING', display_stage_label: '需求分析中',
    has_quotation: true, has_sent_quotation: false, has_active_sample: false,
    sla_summary: { state: 'NORMAL', next_deadline_at: at, remaining_seconds: 300, working_time: true, stage_code: 'FIRST_RESPONSE', active_count: 1 },
    etag: '"inquiry-v1"', allowed_permissions: ['inquiries.view_inquiry'],
    allowed_actions: {
      assign: true, set_priority: true, mark_invalid: false, lifecycle: true, create_quotation: false,
      attach_contact: false, respond: false, confirm_requirements: true, follow_up: true, create_sample: false, create_sales_order: false
    },
    transaction_entity: null, customer_contact: id,
    customer_contact_summary: { id, display_name: '测试联系人', english_name: '', preferred_language_code: 'zh' },
    description: '<p>测试需求</p>', source_system: '', external_id: '', customer_snapshot: { label: '测试快照' }, source_snapshot: {},
    customer_language_code: 'zh', trade_term_code: 'FOB', trade_term_place: '测试地点', delivery_requirement: '',
    estimated_amount_min: '20.0000', estimated_amount_max: null, estimated_currency_code: 'USD', draft_version: 1,
    items: [{
      id, line_number: 1, product_id: null, product_category_id: null, product_category_name: '', product_unit_id: null,
      product_color_id: null, product_image_id: fileId,
      product_image: { id: fileId, original_name: 'fixture.png', content_type: 'image/png', size_bytes: 4, scan_status: 'CLEAN' },
      product_description: '测试产品', specification: '', color: '', material: '', quantity: '5.0000', unit_code: 'PCS',
      target_unit_price: '5.0000', target_currency_code: 'USD', expected_date: '2026-11-01', product_match_status: 'PENDING', notes: '',
      product_number_snapshot: '', product_code_snapshot: '', item_number_snapshot: '', customer_product_name_snapshot: '',
      customer_specification_snapshot: '', customer_unit_code_snapshot: '', customer_color_snapshot: '', customer_material_snapshot: '',
      created_at: at, updated_at: at
    }],
    files: [{ id, file_id: fileId, original_name: 'fixture.txt', content_type: 'text/plain', size_bytes: 4, scan_status: 'CLEAN', file_role: 'REFERENCE', created_at: at }],
    sla: [{
      id, stage_code: 'FIRST_RESPONSE', is_current: true, policy_code: 'TEST', policy_name: '测试规则', status: 'RUNNING',
      started_at: at, next_deadline_at: at, breached_at: null, completed_at: null, work_calendar: calendar, target_minutes: 240,
      progress_context: { round_number: 1, entry_reason: null, source_label: '测试来源', completion_reason: null, quotation_id: null }
    }],
    handling_time_rule: { name: '测试规则', response_minutes: 240, confirmation_minutes: null, work_calendar: calendar, stage_minutes: { ASSIGNMENT: 30 } },
    assignment_history: [{ id, previous_owner: null, new_owner: employee, assigned_at: at, assignment_reason: '', assignment_type: 'MANUAL' }],
    linked_quotations: [{ id, quotation_number: 'TEST-QUOTE', subject: '', status: 'DRAFT', version_id: null, outcome_status: 'OPEN', accepted_version_id: null }],
    linked_samples: [{ id, request_number: 'TEST-SAMPLE', status: 'DRAFT', status_display: '草稿', updated_at: at }],
    linked_sales_orders: [{ id, order_number: 'TEST-ORDER', status: 'DRAFT', status_display: '草稿', is_draft: true, total_amount: 25, currency_code: 'USD', updated_at: at }]
  };
}

function taskFixture() {
  return {
    id, task_number: 'TEST-TASK', title: '测试任务', status: 'PENDING', status_display: '待处理', priority: 'NORMAL', priority_display: '普通',
    task_type: 'INQUIRY_RESPONSE', task_type_display: '询盘响应', origin_type: 'SLA', origin_type_display: 'SLA',
    work_state: 'NORMAL', work_state_display: '正常', display_status: 'OVERDUE', work_state_reason: '', next_check_at: null,
    due_at: at, completed_at: null, completion_result: '', cancelled_at: null, cancel_reason: '', reschedule_count: 0, business_version: 1,
    assignee: employee, created_by: null, contact_summary: { id, name: '测试联系人', position: '' },
    customer: { id, code: 'TEST', name: '测试客户' }, source: { type: 'INQUIRY', id, code: 'TEST-INQUIRY', title: '', open_url: null },
    checklist_progress: { completed: 0, total: 1 }, created_at: at, updated_at: at
  };
}

function respond(body: unknown, status = 200, headers?: HeadersInit) {
  return mock.method(globalThis, 'fetch', async (_input: RequestInfo | URL, _init?: RequestInit) => Response.json(body, { status, headers }));
}

afterEach(() => mock.restoreAll());

test('详情保持完整只读字段和 ETag，使用同源 Session GET 并透传 signal', async () => {
  const fixture = detailFixture();
  const fetchMock = respond({ data: fixture }, 200, { ETag: fixture.etag });
  const controller = new AbortController();
  assert.deepEqual(await fetchInquiryDetail(id, controller.signal), { data: fixture, etag: fixture.etag });
  assert.deepEqual(fetchMock.mock.calls[0].arguments, [`/erp-api/v1/inquiries/${id}/`, {
    method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' }, signal: controller.signal
  }]);
});

test('未配置规则、联系人、负责人和空关联集合仍是有效详情，缺失 ETag 保留 null', async () => {
  const fixture = { ...detailFixture(), owner: null, customer_contact: null, customer_contact_summary: null,
    draft_version: 0, handling_time_rule: null, items: [], files: [], sla: [], assignment_history: [], linked_quotations: [], linked_samples: [], linked_sales_orders: [] };
  respond({ data: fixture });
  assert.deepEqual(await fetchInquiryDetail(id), { data: fixture, etag: null });
});

test('时间线 GET 固定每页20，保留分页和事件扩展数据', async () => {
  const fixture = { data: [{ id, event_type: 'INQUIRY_CREATED', source_type: 'INQUIRY', source_id: id,
    title: '测试事件', summary: '', occurred_at: at, event_data: { actor_employee_id: id, reason: '测试原因' } }],
  meta: { page: 2, page_size: 20, total: 21, total_pages: 2 } };
  const fetchMock = respond(fixture);
  assert.deepEqual(await fetchInquiryTimeline(id, 2), fixture);
  assert.equal(fetchMock.mock.calls[0].arguments[0], `/erp-api/v1/inquiries/${id}/timeline/?page=2&page_size=20`);
});

test('任务读取 data 数组并保留真实任务状态、来源和人员摘要', async () => {
  const fixture = taskFixture();
  const fetchMock = respond({ data: [fixture] });
  assert.deepEqual(await fetchInquiryTasks(id), [fixture]);
  assert.equal(fetchMock.mock.calls[0].arguments[0], `/erp-api/v1/inquiries/${id}/tasks/`);
});

test('无任务和空时间线不是错误', async () => {
  respond({ data: [] });
  assert.deepEqual(await fetchInquiryTasks(id), []);
  mock.restoreAll();
  const page = { data: [], meta: { page: 1, page_size: 20, total: 0, total_pages: 1 } };
  respond(page);
  assert.deepEqual(await fetchInquiryTimeline(id), page);
});

for (const status of [401, 403, 404, 400, 500]) {
  test(`所有读取保留 HTTP ${status} 和服务端错误消息`, async () => {
    respond({ error: { code: 'TEST_ERROR', message: '测试错误消息' } }, status);
    for (const read of [() => fetchInquiryDetail(id), () => fetchInquiryTimeline(id), () => fetchInquiryTasks(id), () => fetchInquiryFile(id, fileId)]) {
      await assert.rejects(read, { name: 'InquiryDetailApiError', code: 'HTTP_ERROR', status, message: '测试错误消息' });
    }
  });
}

test('HTML 错误页保留 HTTP 状态，200 非JSON明确失败', async () => {
  mock.method(globalThis, 'fetch', async () => new Response('<html>error</html>', { status: 403 }));
  await assert.rejects(fetchInquiryDetail(id), { code: 'HTTP_ERROR', status: 403 });
  mock.restoreAll();
  mock.method(globalThis, 'fetch', async () => new Response('<html>ok</html>'));
  await assert.rejects(fetchInquiryDetail(id), { code: 'INVALID_RESPONSE', status: 200 });
});

test('网络断开和 JSON 流读取失败明确报网络错误', async () => {
  mock.method(globalThis, 'fetch', async () => { throw new TypeError('offline'); });
  await assert.rejects(fetchInquiryDetail(id), { code: 'NETWORK_ERROR', status: 0 });
  mock.restoreAll();
  const response = Response.json({});
  mock.method(response, 'json', async () => { throw new TypeError('body disconnected'); });
  mock.method(globalThis, 'fetch', async () => response);
  await assert.rejects(fetchInquiryTasks(id), { code: 'NETWORK_ERROR', status: 200 });
});

test('请求取消和读取取消原样抛出 AbortError', async () => {
  const abort = new DOMException('cancelled', 'AbortError');
  mock.method(globalThis, 'fetch', async () => { throw abort; });
  await assert.rejects(fetchInquiryDetail(id), error => error === abort);
  mock.restoreAll();
  const response = Response.json({});
  mock.method(response, 'json', async () => { throw abort; });
  mock.method(globalThis, 'fetch', async () => response);
  await assert.rejects(fetchInquiryTimeline(id), error => error === abort);
});

test('不合法 UUID、路径注入和分页在发请求前被拒绝', async () => {
  const fetchMock = respond({});
  for (const badId of ['', '../options', `${id}/tasks`, 'not-a-uuid', undefined, 1]) {
    await assert.rejects(Reflect.apply(fetchInquiryDetail, null, [badId]), { code: 'INVALID_QUERY', status: 0 });
    await assert.rejects(Reflect.apply(fetchInquiryTasks, null, [badId]), { code: 'INVALID_QUERY' });
    assert.throws(() => Reflect.apply(inquiryProductImageUrl, null, [badId]), { code: 'INVALID_QUERY' });
  }
  for (const page of [0, -1, 1.5, NaN, Infinity, '2', null]) {
    await assert.rejects(Reflect.apply(fetchInquiryTimeline, null, [id, page]), { code: 'INVALID_QUERY' });
  }
  for (const badFile of ['', '../download', null, 1]) {
    await assert.rejects(Reflect.apply(fetchInquiryFile, null, [id, badFile]), { code: 'INVALID_QUERY' });
  }
  assert.equal(fetchMock.mock.callCount(), 0);
});

test('详情核心字段、枚举、金额、日期和嵌套关联的损坏不能当作成功', async () => {
  const base = detailFixture();
  const invalid = [
    {}, { ...base, id: fileId }, { ...base, status: 'UNKNOWN' }, { ...base, owner: {} },
    { ...base, received_at: '2026-02-30' }, { ...base, allowed_actions: {} }, { ...base, files: {} },
    { ...base, files: [{ ...base.files[0], scan_status: 'UNKNOWN' }] },
    { ...base, items: [{ ...base.items[0], quantity: 'NaN' }] },
    { ...base, items: [{ ...base.items[0], product_match_status: 'UNKNOWN' }] },
    { ...base, items: [{ ...base.items[0], product_image: {} }] },
    { ...base, sla: [{ ...base.sla[0], status: 'UNKNOWN' }] },
    { ...base, sla: [{ ...base.sla[0], progress_context: [] }] },
    { ...base, handling_time_rule: { ...base.handling_time_rule, work_calendar: { ...calendar, periods: [[720, 510]] } } },
    { ...base, handling_time_rule: { ...base.handling_time_rule, stage_minutes: { FIRST_RESPONSE: '240' } } },
    { ...base, assignment_history: [{ ...base.assignment_history[0], new_owner: {} }] },
    { ...base, linked_quotations: [{}] }, { ...base, linked_samples: [{}] },
    { ...base, linked_sales_orders: [{ ...base.linked_sales_orders[0], total_amount: 'NaN' }] }
  ];
  for (const fixture of invalid) {
    respond({ data: fixture });
    await assert.rejects(fetchInquiryDetail(id), { code: 'INVALID_RESPONSE', status: 200 });
    mock.restoreAll();
  }
});

test('任务枚举和结构、时间线事件/分页损坏均明确失败', async () => {
  const task = taskFixture();
  for (const fixture of [null, {}, [{ ...task, task_type: 'UNKNOWN' }], [{ ...task, status: 'UNKNOWN' }], [{ ...task, assignee: null }], [{ ...task, checklist_progress: { completed: 2, total: 1 } }]]) {
    respond({ data: fixture });
    await assert.rejects(fetchInquiryTasks(id), { code: 'INVALID_RESPONSE' });
    mock.restoreAll();
  }
  for (const fixture of [{ data: [], meta: null }, { data: [], meta: { page: 0, page_size: 20, total: 0, total_pages: 1 } },
    { data: [{}], meta: { page: 1, page_size: 20, total: 1, total_pages: 1 } }]) {
    respond(fixture);
    await assert.rejects(fetchInquiryTimeline(id), { code: 'INVALID_RESPONSE' });
    mock.restoreAll();
  }
});

test('单文件和打包附件使用真实 GET 路径、Session和正确类型，不创建下载文件', async () => {
  for (const [file, path, type] of [[fileId, `files/${fileId}/download/`, 'application/octet-stream'], [undefined, 'files-download/', 'application/zip']] as const) {
    const fetchMock = mock.method(globalThis, 'fetch', async (_input: RequestInfo | URL, _init?: RequestInit) => new Response('fixture', { headers: { 'Content-Type': type } }));
    const signal = new AbortController().signal;
    assert.equal(await (await fetchInquiryFile(id, file, signal)).text(), 'fixture');
    assert.deepEqual(fetchMock.mock.calls[0].arguments, [`/erp-api/v1/inquiries/${id}/${path}`, {
      method: 'GET', credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/octet-stream, application/zip, application/json' }, signal
    }]);
    mock.restoreAll();
  }
});

test('成功状态的 JSON/HTML 不得作为附件，文件流中断和取消保持错误', async () => {
  respond({ error: { message: 'not a file' } });
  await assert.rejects(fetchInquiryFile(id), { code: 'INVALID_RESPONSE', status: 200 });
  mock.restoreAll();
  const response = new Response('fixture', { headers: { 'Content-Type': 'application/zip' } });
  const blobMock = mock.method(response, 'blob', async () => { throw new TypeError('disconnected'); });
  mock.method(globalThis, 'fetch', async () => response);
  await assert.rejects(fetchInquiryFile(id), { code: 'NETWORK_ERROR', status: 200 });
  const abort = new DOMException('cancelled', 'AbortError');
  blobMock.mock.mockImplementation(async () => { throw abort; });
  await assert.rejects(fetchInquiryFile(id), error => error === abort);
});

test('产品图片地址只接受明细UUID且固定同源ERP路径', () => {
  assert.equal(inquiryProductImageUrl(id), `/erp-api/v1/inquiry-items/${id}/product-image/`);
});
