import assert from 'node:assert/strict';
import test from 'node:test';
import { formatMoney, formatDate, getFollowUpStatus } from './shared';

test('金额区分缺失与零，保留十进制字符串精度', () => {
  assert.equal(formatMoney(null), '—');
  assert.equal(formatMoney('0.00'), 'CNY 0.00');
  assert.equal(formatMoney('1234567890123456.78'), 'CNY 1,234,567,890,123,456.78');
  assert.equal(formatMoney('invalid'), '—');
});

test('日期和跟进状态处理缺失、无效时间及日边界', () => {
  const today = new Date(2026, 9, 16, 12);
  assert.equal(formatDate(null), '—');
  assert.equal(formatDate('invalid'), '—');
  assert.equal(formatDate('2026-10-16'), '2026-10-16');
  assert.equal(getFollowUpStatus(null, today).label, '未安排');
  assert.equal(getFollowUpStatus('invalid', today).label, '未安排');
  assert.equal(getFollowUpStatus(new Date(2026, 9, 15, 23, 59, 59).toISOString(), today).label, '已逾期');
  assert.equal(getFollowUpStatus(new Date(2026, 9, 16, 23, 59, 59).toISOString(), today).label, '今日跟进');
  assert.equal(getFollowUpStatus(new Date(2026, 9, 17).toISOString(), today).label, '待跟进');
});
