import assert from 'node:assert/strict';
import test from 'node:test';
import type { CustomerContact, CustomerSummary, CustomerTask } from '../../typings/customer-detail';
import {
  buildCustomerHealthSummary,
  calculateCreditUsage,
  contactMethod,
  formatOverviewMoney,
  previewContacts,
  previewTasks,
  timelineCategory
} from './shared';

test('金额保持十进制精度，未知金额或币种不变成零', () => {
  assert.equal(formatOverviewMoney('9007199254740993.01', 'CNY'), 'CNY 9,007,199,254,740,993.01');
  assert.equal(formatOverviewMoney('-1234.50', 'USD'), 'USD -1,234.50');
  assert.equal(formatOverviewMoney(0, 'CNY'), 'CNY 0');
  assert.equal(formatOverviewMoney(null, 'CNY'), '—');
  assert.equal(formatOverviewMoney('', 'CNY'), '—');
  assert.equal(formatOverviewMoney('12.30', ''), '—');
  assert.equal(formatOverviewMoney('bad', 'USD'), '—');
});

test('信用使用率区分无数据、零额度、真实零使用和超额度', () => {
  assert.equal(calculateCreditUsage(null, null), null);
  assert.equal(calculateCreditUsage('0', '0'), null);
  assert.equal(calculateCreditUsage('100', null), null);
  assert.equal(calculateCreditUsage('100', '0'), 0);
  assert.equal(calculateCreditUsage('100', '150'), 150);
  assert.equal(calculateCreditUsage('100', '-1'), null);
});

function summary(openComplaints: number, overdueTasks: number): CustomerSummary {
  return {
    counts: { open_complaints: openComplaints, overdue_tasks: overdueTasks }
  } as CustomerSummary;
}

test('汇总未加载或失败时不能推断没有客诉及逾期任务', () => {
  const result = buildCustomerHealthSummary(null, null);
  assert.equal(result.tone, 'default');
  assert.ok(result.facts.some(fact => fact.label.includes('待确认')));
  assert.ok(!result.facts.some(fact => fact.label.includes('暂无开放')));
});

test('真实汇总风险优先展示，零风险不掩盖财务尚未接入', () => {
  const risk = buildCustomerHealthSummary(summary(2, 1), null);
  assert.equal(risk.tone, 'warning');
  assert.ok(risk.facts.some(fact => fact.meta.includes('2') && fact.meta.includes('1')));
  const noRisk = buildCustomerHealthSummary(summary(0, 0), null);
  assert.ok(noRisk.facts.some(fact => fact.label.includes('暂无开放')));
  assert.ok(noRisk.facts.some(fact => fact.label.includes('应收逾期数据未接入')));
  assert.notEqual(noRisk.label, '整体正常');
});

function contact(id: string, primary = false, key = false): CustomerContact {
  return { id, is_primary_contact: primary, is_key_contact: key, methods: [] } as unknown as CustomerContact;
}

test('联系人按主要、关键、首项依次回退且仅预览另外两人', () => {
  const list = [contact('first'), contact('key', false, true), contact('primary', true), contact('last')];
  const result = previewContacts(list);
  assert.equal(result.primary?.id, 'primary');
  assert.deepEqual(
    result.others.map(item => item.id),
    ['first', 'key']
  );
  assert.equal(previewContacts(list.filter(item => item.id !== 'primary')).primary?.id, 'key');
  assert.equal(previewContacts([list[0]!]).primary?.id, 'first');
  assert.deepEqual(previewContacts([]), { primary: null, others: [] });
});

test('联系方式只使用服务端可展示值，空值回退脱敏值且优先主要方式', () => {
  const row = contact('contact');
  row.methods = [
    { method_type: 'EMAIL', display_value: 'secondary@example.test', masked_value: '', is_primary: false },
    { method_type: 'EMAIL', display_value: '', masked_value: 'p***@example.test', is_primary: true }
  ] as CustomerContact['methods'];
  assert.equal(contactMethod(row, ['EMAIL']), 'p***@example.test');
  assert.equal(contactMethod(row, ['MOBILE', 'PHONE']), '—');
  assert.equal(contactMethod(null, ['EMAIL']), '—');
});

test('任务预览剔除终态并按截止时间排序，只取前三且不修改原数组', () => {
  const rows = [
    { id: 'done', status: 'COMPLETED', due_at: '2026-10-01T00:00:00Z' },
    { id: 'none', status: 'PENDING', due_at: null },
    { id: 'later', status: 'IN_PROGRESS', due_at: '2026-10-20T00:00:00Z' },
    { id: 'first', status: 'PENDING', due_at: '2026-10-18T00:00:00Z' },
    { id: 'middle', status: 'PENDING', due_at: '2026-10-19T00:00:00Z' }
  ] as CustomerTask[];
  assert.deepEqual(
    previewTasks(rows).map(item => item.id),
    ['first', 'middle', 'later']
  );
  assert.equal(rows[0]?.id, 'done');
});

test('互动类型识别事件及来源，未识别来源保留系统类别', () => {
  assert.equal(timelineCategory({ source_type: 'QUOTATION_VERSION', event_type: 'CREATED' }).label, '报价');
  assert.equal(timelineCategory({ source_type: 'CUSTOMER', event_type: 'COMMUNICATION_CREATED' }).label, '沟通');
  assert.equal(timelineCategory({ source_type: 'UNKNOWN', event_type: 'OTHER' }).label, '系统');
});
