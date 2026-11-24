import assert from 'node:assert/strict';
import { test } from 'node:test';
import { inquiryListReturnPath } from './navigation';

test('详情返回原列表并保留筛选分页', () => {
  assert.equal(
    inquiryListReturnPath('/inquiries?q=two%20words&page=2&page_size=20'),
    '/inquiries?q=two%20words&page=2&page_size=20'
  );
  assert.equal(inquiryListReturnPath('/inquiries'), '/inquiries');
});

test('返回地址拒绝外站、旧前端、其他页面和畸形输入', () => {
  for (const value of [
    undefined,
    null,
    [],
    '/customers',
    '//example.com/inquiries',
    'http://127.0.0.1:8080/inquiries',
    '/inquiries/123',
    '/%ZZ',
    '/inquiries\\evil',
    '/inquiries\n',
    '/%2finquiries'
  ]) {
    assert.equal(inquiryListReturnPath(value), '/inquiries');
  }
});
