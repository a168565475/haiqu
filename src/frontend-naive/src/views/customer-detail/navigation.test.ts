import assert from 'node:assert/strict';
import test from 'node:test';
import { customerListQuery, customerListReturnPath, customerListRouteQuery, customerTab } from './navigation';

test('客户返回目标仅允许本站客户列表并保留查询与锚点', () => {
  assert.equal(customerListReturnPath('/customers?page=2&q=A#list'), '/customers?page=2&q=A#list');
  for (const value of [
    'http://127.0.0.1:8080/customers',
    '//example.com/customers',
    '/customers/123',
    '/inquiries',
    '/customers%0a',
    '/customers?q=%5c',
    '/customers?q=%',
    undefined,
    ['/customers']
  ]) {
    assert.equal(customerListReturnPath(value), '/customers');
  }
});

test('客户列表往返保留支持的筛选分页并清除重复及非法参数', () => {
  const query = {
    page: '2',
    page_size: '20',
    ordering: 'account_name',
    q: ' Acme ',
    country_code: 'US',
    customer_grade: 'A',
    activity_status: 'ACTIVE'
  };
  assert.deepEqual(customerListRouteQuery(customerListQuery(query)), { ...query, q: 'Acme' });
  assert.deepEqual(
    customerListQuery({
      page: '-1',
      page_size: '9999',
      ordering: 'random',
      q: ['one', 'two'],
      activity_status: 'BAD',
      token: 'unused'
    }),
    { page: 1, page_size: 10, ordering: '-updated_at' }
  );
  assert.equal(customerTab('contacts'), 'contacts');
  assert.equal(customerTab(['contacts']), 'overview');
  assert.equal(customerTab('edit'), 'overview');
});
