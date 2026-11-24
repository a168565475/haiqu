import assert from 'node:assert/strict';
import test from 'node:test';
import type { ComplaintListItem } from '../../typings/complaint';
import {
  complaintCsv,
  complaintRouteQuery,
  escapeCsvCell,
  formatComplaintDate,
  getComplaintSlaText,
  normalizeComplaintQuery
} from './shared';

const dictionaryId = '12345678-1234-1234-1234-123456789abc';

test('URL 保留六项合法筛选与分页，忽略范围外参数', () => {
  const query = normalizeComplaintQuery({
    q: '  客诉关键词  ',
    complaint_type_item_id: dictionaryId,
    severity_item_id: dictionaryId,
    status: 'CUSTOMER_CONFIRMATION',
    owner_employee_id: dictionaryId,
    sla_status: 'AT_RISK',
    page: '3',
    page_size: '20',
    ordering: 'complaint_code',
    customer_id: dictionaryId
  });
  assert.deepEqual(query, {
    q: '客诉关键词',
    complaint_type_item_id: dictionaryId,
    severity_item_id: dictionaryId,
    status: 'CUSTOMER_CONFIRMATION',
    owner_employee_id: dictionaryId,
    sla_status: 'AT_RISK',
    page: 3,
    page_size: 20
  });
  assert.deepEqual(complaintRouteQuery(query), {
    q: '客诉关键词',
    complaint_type_item_id: dictionaryId,
    severity_item_id: dictionaryId,
    status: 'CUSTOMER_CONFIRMATION',
    owner_employee_id: dictionaryId,
    sla_status: 'AT_RISK',
    page: '3',
    page_size: '20'
  });
});

test('非法和重复 URL 参数不会发送给后端，分页回退到第一页每页50条', () => {
  assert.deepEqual(
    normalizeComplaintQuery({
      q: ['one', 'two'],
      complaint_type_item_id: 'bad-id',
      severity_item_id: null,
      status: 'ACCEPTED,CLOSED',
      owner_employee_id: ['bad-id'],
      sla_status: 'UNKNOWN',
      page: '1.5',
      page_size: '10'
    }),
    { page: 1, page_size: 50 }
  );
  for (const page of ['-1', '0', '1e3', 'Infinity', '9007199254740992', ['2'], null]) {
    assert.equal(normalizeComplaintQuery({ page }).page, 1);
  }
  assert.equal(normalizeComplaintQuery({ page: 4, page_size: 100 }).page, 4);
  assert.equal(normalizeComplaintQuery({ page: 4, page_size: 100 }).page_size, 100);
  assert.deepEqual(normalizeComplaintQuery({ q: '   ' }), {
    page: 1,
    page_size: 50
  });
});

test('日期保留本地日期时间，无效值显示占位', () => {
  const date = new Date(2026, 9, 16, 9, 8, 7);
  assert.equal(formatComplaintDate(date.toISOString()), '2026-10-16 09:08:07');
  assert.equal(formatComplaintDate(null), '—');
  assert.equal(formatComplaintDate('invalid'), '—');
});

test('SLA 使用后端状态，不根据浏览器时间覆盖已结束或到期状态', () => {
  const target = new Date(2026, 9, 16, 9, 8, 7).toISOString();
  assert.equal(getComplaintSlaText({ sla_status: 'NORMAL', target_completion_at: target }), '2026-10-16 09:08:07');
  assert.equal(
    getComplaintSlaText({
      sla_status: 'AT_RISK',
      target_completion_at: target
    }),
    '即将到期 · 2026-10-16 09:08:07'
  );
  assert.equal(
    getComplaintSlaText({
      sla_status: 'OVERDUE',
      target_completion_at: target
    }),
    '已超时 · 2026-10-16 09:08:07'
  );
  assert.equal(
    getComplaintSlaText({
      sla_status: 'COMPLETED',
      target_completion_at: target
    }),
    '已结束'
  );
});

test('CSV 保留逗号引号换行，阻止公式和控制字符前缀注入', () => {
  assert.equal(escapeCsvCell('客户, "名称"\n第二行'), '"客户, ""名称""\n第二行"');
  assert.equal(escapeCsvCell(null), '""');
  for (const value of ['=1+1', '+SUM(A1)', '-1+1', '@SUM(A1)', '  =1+1', '\t=1+1', '\r=1+1', '\n=1+1', '\u0000=1+1']) {
    assert.equal(escapeCsvCell(value), `"'${value}"`);
  }
  assert.equal(escapeCsvCell('编号-123'), '"编号-123"');
});

test('CSV 只导出传入当前页的九个数据字段，不泄露响应其他属性', () => {
  const row: ComplaintListItem = {
    id: dictionaryId,
    complaint_code: 'TEST-C001',
    customer: { id: dictionaryId, account_name: '=1+1' },
    source_order_reference: '',
    complaint_type: {
      id: dictionaryId,
      item_code: 'QUALITY',
      display_name: '质量'
    },
    severity: { id: dictionaryId, item_code: 'GENERAL', display_name: '一般' },
    status: 'ACCEPTED',
    status_label: '已受理',
    owner: { id: dictionaryId, display_name: '测试负责人' },
    sla_status: 'NORMAL',
    target_completion_at: '2026-10-16T00:00:00Z',
    updated_at: '2026-10-16T01:00:00Z'
  };
  const rows = [{ ...row, internal_note: '不得导出' }];
  const csv = complaintCsv(rows);
  assert.ok(
    csv.startsWith('\ufeff"客诉编号","客户","关联订单","类型","严重程度","状态","负责人","目标完成","最近更新"\r\n')
  );
  assert.equal(csv.split('\r\n').length, 2);
  assert.ok(csv.includes('"\'=1+1"'));
  assert.ok(!csv.includes('不得导出'));
  assert.ok(!csv.includes(dictionaryId));
  assert.equal(complaintCsv([]).split('\r\n').length, 1);
});
