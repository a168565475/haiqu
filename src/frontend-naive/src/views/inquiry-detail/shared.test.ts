import assert from 'node:assert/strict';
import test from 'node:test';
import type { InquirySla, InquiryWorkCalendar } from '../../typings/inquiry-detail';
import {
  currentHandlingRecords,
  formatEstimatedAmount,
  formatInquiryNumber,
  formatInquiryTime,
  handlingStageLabel,
  handlingStatusLabel,
  handlingTargetLabel,
  inquiryNextActionCopy,
  inquiryStepIndex,
  nextStepCopy,
  safeWebsite,
  slaPresentation,
  workCalendarDescription,
  workMilliseconds
} from './shared';

const hour = 3600000;
const at = (value: string) => Date.parse(`${value}+08:00`);
const calendar: InquiryWorkCalendar = {
  mode: 'ALTERNATING_WEEKS_V1',
  timezone: 'Asia/Shanghai',
  rest_saturday: '2026-10-10',
  periods: [
    [540, 720],
    [780, 1080]
  ]
};

function sla(overrides: Partial<InquirySla> = {}): InquirySla {
  return {
    id: 'sla-a',
    stage_code: 'FIRST_RESPONSE',
    is_current: true,
    policy_code: 'TEST',
    policy_name: '测试规则',
    status: 'RUNNING',
    started_at: '2026-10-16T09:00:00+08:00',
    next_deadline_at: '2026-10-16T18:00:00+08:00',
    breached_at: null,
    completed_at: null,
    work_calendar: calendar,
    target_minutes: 480,
    progress_context: {
      round_number: null,
      entry_reason: null,
      source_label: null,
      completion_reason: null,
      quotation_id: null
    },
    ...overrides
  };
}

test('步骤保留负责人派生阶段和报价阶段折叠，终止态不伪装进度', () => {
  assert.equal(inquiryStepIndex('NEW'), 0);
  assert.equal(inquiryStepIndex('NEW', true), 1);
  assert.equal(inquiryStepIndex('ANALYZING', true), 2);
  for (const status of ['QUOTING', 'QUOTED', 'FOLLOW_UP', 'QUOTE_ACCEPTED']) assert.equal(inquiryStepIndex(status), 4);
  assert.equal(inquiryStepIndex('CONVERTED'), 5);
  for (const status of ['DRAFT', 'LOST', 'CLOSED', 'CANCELLED', 'UNKNOWN']) assert.equal(inquiryStepIndex(status), -1);
});

test('金额按字符串格式化，不丢失大整数和小数精度', () => {
  assert.equal(formatInquiryNumber('9007199254740993.123400', 2), '9,007,199,254,740,993.1234');
  assert.equal(formatInquiryNumber('0', 2), '0.00');
  assert.equal(formatInquiryNumber('12.3000'), '12.3');
  assert.equal(formatInquiryNumber(25), '25');
  for (const value of [null, '', '-1', '1e3', 'NaN']) assert.equal(formatInquiryNumber(value), '—');
  assert.equal(
    formatEstimatedAmount({
      product_amount: {
        item_count: 2,
        missing_price_count: 0,
        totals: [
          { currency_code: 'USD', amount: '9007199254740993.01' },
          { currency_code: 'CNY', amount: '0' }
        ]
      }
    }),
    'USD 9,007,199,254,740,993.01 / CNY 0.00'
  );
  assert.equal(
    formatEstimatedAmount({ product_amount: { item_count: 1, missing_price_count: 1, totals: [] } }),
    '待补齐'
  );
  assert.equal(formatEstimatedAmount({ product_amount: { item_count: 0, missing_price_count: 0, totals: [] } }), '—');
});

test('网站只允许不带凭据的 HTTP/HTTPS，拒绝脚本和相对地址', () => {
  assert.equal(safeWebsite(' https://example.com/a?x=1#part '), 'https://example.com/a?x=1#part');
  assert.equal(safeWebsite('http://example.com'), 'http://example.com/');
  for (const value of [
    null,
    123,
    '',
    '/customer',
    '//example.com',
    'javascript:alert(1)',
    'data:text/html,test',
    'file:///test',
    'https://user:pass@example.com',
    'https://user@example.com'
  ]) {
    assert.equal(safeWebsite(value), '');
  }
});

test('时间固定上海时区，缺失和无效值不显示伪日期', () => {
  assert.equal(formatInquiryTime('2026-10-16T16:05:00Z'), '2026-10-17 00:05');
  assert.equal(formatInquiryTime(null), '—');
  assert.equal(formatInquiryTime('invalid'), '—');
});

test('工作计时排除午休和下班，支持反向差值；无快照保留连续时间', () => {
  const begin = at('2026-10-16T11:00:00');
  const end = at('2026-10-16T14:00:00');
  assert.equal(workMilliseconds(begin, end, calendar), 2 * hour);
  assert.equal(workMilliseconds(end, begin, calendar), -2 * hour);
  assert.equal(workMilliseconds(begin, end), 3 * hour);
  assert.equal(workMilliseconds(at('2026-10-16T12:00:00'), at('2026-10-16T13:00:00'), calendar), 0);
  assert.equal(workMilliseconds(at('2026-10-16T18:00:00'), at('2026-10-17T09:00:00'), calendar), 0);
});

test('大小周按后台休息周六基准交替，周日不计时，基准以前同样有效', () => {
  assert.equal(workMilliseconds(at('2026-10-16T17:00:00'), at('2026-10-19T10:00:00'), calendar), 10 * hour);
  assert.equal(workMilliseconds(at('2026-10-23T17:00:00'), at('2026-10-26T10:00:00'), calendar), 2 * hour);
  assert.equal(workMilliseconds(at('2026-10-03T09:00:00'), at('2026-10-03T18:00:00'), calendar), 8 * hour);
  assert.equal(workMilliseconds(at('2026-10-10T09:00:00'), at('2026-10-10T18:00:00'), calendar), 0);
  assert.equal(workMilliseconds(at('2026-10-18T09:00:00'), at('2026-10-18T18:00:00'), calendar), 0);
});

test('无效工作日历或时间返回不可计算，不回退成真实业务时长', () => {
  const begin = at('2026-10-16T09:00:00');
  const end = at('2026-10-16T18:00:00');
  assert.ok(Number.isNaN(workMilliseconds(NaN, end, calendar)));
  assert.ok(Number.isNaN(workMilliseconds(begin, end, { ...calendar, rest_saturday: '2026-10-11' })));
  assert.ok(
    Number.isNaN(
      workMilliseconds(begin, end, {
        ...calendar,
        periods: [
          [540, 780],
          [720, 1080]
        ]
      })
    )
  );
  assert.ok(
    Number.isNaN(
      workMilliseconds(begin, end, {
        ...calendar,
        periods: [
          [540, 540],
          [780, 1080]
        ]
      })
    )
  );
  assert.ok(Number.isNaN(workMilliseconds(begin, end, { ...calendar, periods: [[540, 720]] })));
  assert.ok(Number.isNaN(workMilliseconds(begin, begin + 36601 * 86400000, calendar)));
});

test('并行计时只取当前记录，按截止时间和ID稳定排序，不改原数组', () => {
  const records = [
    sla({ id: 'z', next_deadline_at: null }),
    sla({ id: 'b', next_deadline_at: '2026-10-16T11:00:00+08:00' }),
    sla({ id: 'history', is_current: false, next_deadline_at: '2026-10-16T08:00:00+08:00' }),
    sla({ id: 'a', next_deadline_at: '2026-10-16T11:00:00+08:00' })
  ];
  assert.deepEqual(
    currentHandlingRecords(records).map(record => record.id),
    ['a', 'b', 'z']
  );
  assert.deepEqual(
    records.map(record => record.id),
    ['z', 'b', 'history', 'a']
  );
});

test('SLA剩余时间和进度按工作日历计算，暂停午休，超时进度最多100%', () => {
  const record = sla();
  assert.deepEqual(slaPresentation(record, at('2026-10-16T12:30:00'), 'NEW'), {
    label: '剩余 5 小时 0 分钟（工作时间）',
    percentage: 37.5,
    overdue: false
  });
  assert.deepEqual(slaPresentation(record, at('2026-10-17T10:00:00'), 'NEW'), {
    label: '已超时 1 小时 0 分钟（工作时间）',
    percentage: 100,
    overdue: true
  });
  assert.equal(slaPresentation(record, at('2026-10-16T08:00:00'), 'NEW').percentage, 0);
});

test('已结束、暂停、缺截止和后台BREACHED状态显示保留原语义', () => {
  const now = at('2026-10-16T10:00:00');
  assert.deepEqual(slaPresentation(sla(), now, 'CONVERTED'), {
    label: '当前流程已结束',
    percentage: null,
    overdue: false
  });
  assert.equal(slaPresentation(undefined, now, 'DRAFT').label, '暂无时效记录');
  assert.equal(slaPresentation(sla({ status: 'BREACHED' }), now, 'NEW').label, '已超时');
  assert.equal(
    slaPresentation(sla({ status: 'BREACHED', completed_at: '2026-10-16T19:00:00+08:00' }), now, 'NEW').label,
    '超时完成'
  );
  assert.equal(handlingStatusLabel('PAUSED'), '已暂停');
  assert.equal(slaPresentation(sla({ next_deadline_at: null }), now, 'NEW').label, '未设置截止时间');
  assert.equal(slaPresentation(sla({ status: 'BREACHED', next_deadline_at: null }), now, 'NEW').overdue, true);
  assert.equal(handlingStatusLabel('RUNNING', null, '2026-10-16T09:00:00+08:00', now), '已超时');
});

test('阶段名称、目标和日历描述保留技术计时口径', () => {
  assert.equal(handlingStageLabel('QUOTE_DELIVERY'), '完成并发送报价');
  assert.equal(handlingStageLabel('UNKNOWN'), '处理阶段');
  assert.equal(handlingTargetLabel(0), '未启用');
  assert.equal(handlingTargetLabel(30), '30 分钟');
  assert.equal(handlingTargetLabel(90), '1.5 个工作小时');
  assert.equal(workCalendarDescription(calendar), '工作时段：09:00—12:00、13:00—18:00，每天 8 小时。');
  assert.equal(workCalendarDescription({ ...calendar, periods: [] }), '工作日历不完整');
});

test('下一步只生成说明，保留联系人、负责人、SLA阶段及有效订单优先级', () => {
  const detail = {
    status: 'QUOTING' as const,
    status_display: '报价中',
    customer_contact: null,
    owner: null,
    linked_sales_orders: []
  };
  assert.equal(inquiryNextActionCopy(detail).title, '先补充联系人');
  assert.equal(inquiryNextActionCopy({ ...detail, customer_contact: 'contact-id' }).title, '完成询盘分配');
  assert.equal(nextStepCopy(detail, sla({ stage_code: 'QUOTE_DELIVERY' })).title, '完成并发送报价');
  assert.equal(
    nextStepCopy({ ...detail, linked_sales_orders: [{ status: 'CONFIRMED' }] }, sla()).title,
    '在销售订单中继续处理'
  );
  assert.equal(
    nextStepCopy({ ...detail, linked_sales_orders: [{ status: 'CANCELLED' }] }, sla()).title,
    '先补充联系人'
  );
});
