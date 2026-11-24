import assert from 'node:assert/strict';
import test from 'node:test';
import {
  formatInquiryAmount,
  formatInquiryReceived,
  inquiryDateRangeQuery,
  inquiryRouteQuery,
  inquirySlaPresentation,
  inquiryStatusType,
  normalizeInquiryQuery,
  parseInquiryAmountFilter
} from './shared';

const employeeId = '12345678-1234-1234-1234-123456789abc';

test('URL 保留原列表十四项筛选和四种排序，不启用看板或详情参数', () => {
  const query = normalizeInquiryQuery({
    q: '  询盘词  ',
    status: 'QUOTED',
    source_code: 'WEB',
    country_code: 'CN',
    owner_employee_id: employeeId,
    assignment_status: 'ASSIGNED',
    sla_state: 'RISK',
    product_q: '  产品词 ',
    received_from: '2026-10-01T00:00:00+08:00',
    received_to: '2026-10-16T23:59:59.999999+08:00',
    has_quotation: 'true',
    priority: 'UNSET',
    amount_min: '0',
    amount_currency: 'USD',
    page: '2',
    page_size: '20',
    ordering: 'requested_due_at',
    view: 'board',
    customer_id: employeeId
  });
  assert.deepEqual(query, {
    q: '询盘词',
    status: 'QUOTED',
    source_code: 'WEB',
    country_code: 'CN',
    owner_employee_id: employeeId,
    assignment_status: 'ASSIGNED',
    sla_state: 'RISK',
    product_q: '产品词',
    received_from: '2026-10-01T00:00:00+08:00',
    received_to: '2026-10-16T23:59:59.999999+08:00',
    has_quotation: 'true',
    priority: 'UNSET',
    amount_min: '0',
    amount_currency: 'USD',
    page: 2,
    page_size: 20,
    ordering: 'requested_due_at'
  });
  assert.equal(inquiryRouteQuery(query).page, '2');
  assert.equal(inquiryRouteQuery(query).has_quotation, 'true');
  for (const ordering of ['-received_at', 'received_at', 'requested_due_at', '-updated_at']) {
    assert.equal(normalizeInquiryQuery({ ordering }).ordering, ordering);
  }
});

test('非法或重复参数清除，金额必须成对，分页和排序回退原列表默认值', () => {
  assert.deepEqual(
    normalizeInquiryQuery({
      q: ['one', 'two'],
      status: 'UNKNOWN',
      owner_employee_id: 'invalid',
      assignment_status: 'ANY',
      sla_state: 'NORMAL',
      has_quotation: true,
      priority: 'URGENT',
      amount_min: '1e2',
      amount_currency: 'USD',
      received_from: '2026-02-30T00:00:00+08:00',
      received_to: 'bad-date',
      page: '-1',
      page_size: '10',
      ordering: '-subject'
    }),
    { page: 1, page_size: 50, ordering: '-received_at' }
  );
  for (const page of ['0', '1.5', '1e3', '9007199254740992', ['2']]) {
    assert.equal(normalizeInquiryQuery({ page }).page, 1);
  }
  assert.equal(normalizeInquiryQuery({ amount_min: '1' }).amount_min, undefined);
  assert.equal(normalizeInquiryQuery({ amount_currency: 'USD' }).amount_currency, undefined);
  assert.equal(normalizeInquiryQuery({ page_size: 100 }).page_size, 100);
});

test('金额筛选兼容原输入格式，零和高精度保持字符串，不接受负数或指数', () => {
  assert.deepEqual(parseInquiryAmountFilter(' usd 10,000.123400 以上 '), {
    amount_currency: 'USD',
    amount_min: '10000.123400'
  });
  assert.deepEqual(parseInquiryAmountFilter('USD 0'), { amount_currency: 'USD', amount_min: '0' });
  assert.deepEqual(parseInquiryAmountFilter(' '), {});
  for (const text of ['USD -1', 'USD 1e3', '100', 'USD 1.123456789', 'US 100']) {
    assert.throws(() => parseInquiryAmountFilter(text), /请输入币种和非负金额/);
  }
});

test('日期范围按上海时区整日生成，闰日和反向日期有明确校验', () => {
  assert.deepEqual(inquiryDateRangeQuery(['2026-10-01', '2026-10-16']), {
    received_from: '2026-10-01T00:00:00+08:00',
    received_to: '2026-10-16T23:59:59.999999+08:00'
  });
  assert.deepEqual(inquiryDateRangeQuery(null), {});
  assert.equal(inquiryDateRangeQuery(['2024-02-29', '2024-02-29']).received_from, '2024-02-29T00:00:00+08:00');
  assert.throws(() => inquiryDateRangeQuery(['2026-02-30', '2026-03-01']), /日期/);
  assert.throws(() => inquiryDateRangeQuery(['2026-10-16', '2026-10-01']), /日期/);
});

test('接收时间固定上海时区，不随浏览器时区漂移', () => {
  assert.deepEqual(formatInquiryReceived('2026-10-16T16:01:00Z'), { date: '2026-10-17', time: '00:01' });
  assert.deepEqual(formatInquiryReceived('invalid'), { date: '—', time: '' });
});

test('预估金额来自产品汇总，保留多币种与大数精度，缺价明确显示', () => {
  assert.equal(
    formatInquiryAmount({
      item_count: 2,
      missing_price_count: 0,
      totals: [
        { currency_code: 'USD', amount: '9007199254740993.123400' },
        { currency_code: 'CNY', amount: '0.000000' }
      ]
    }),
    'USD 9,007,199,254,740,993.1234 / CNY 0.00'
  );
  assert.equal(formatInquiryAmount({ item_count: 1, missing_price_count: 1, totals: [] }), '待补齐');
  assert.equal(formatInquiryAmount({ item_count: 0, missing_price_count: 0, totals: [] }), '—');
  assert.equal(formatInquiryAmount(undefined), '—');
  assert.equal(
    formatInquiryAmount({ item_count: 1, missing_price_count: 0, totals: [{ currency_code: 'USD', amount: 'NaN' }] }),
    '—'
  );
});

test('时限使用服务端状态和剩余秒数，不以浏览器时钟推导业务状态', () => {
  assert.deepEqual(inquirySlaPresentation({ state: 'NONE', remaining_seconds: null }), {
    label: '—',
    reminder: '—',
    type: 'default'
  });
  assert.deepEqual(inquirySlaPresentation({ state: 'BREACHED', remaining_seconds: -61 }), {
    label: '超时 2分钟',
    reminder: '已超时',
    type: 'error'
  });
  assert.deepEqual(inquirySlaPresentation({ state: 'DUE_SOON', remaining_seconds: null }), {
    label: '即将超时',
    reminder: '即将超时',
    type: 'warning'
  });
  assert.equal(inquirySlaPresentation({ state: 'NORMAL', remaining_seconds: 90061 }).label, '剩余 1天1小时');
  assert.equal(inquiryStatusType('QUOTE_ACCEPTED'), 'success');
  assert.equal(inquiryStatusType('CANCELLED'), 'error');
  assert.equal(inquiryStatusType('CLOSED'), 'default');
});
