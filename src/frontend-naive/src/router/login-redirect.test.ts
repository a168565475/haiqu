import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createMemoryHistory, createRouter } from 'vue-router';
import { getLoginRedirect, resolveLoginRedirect } from './login-redirect';

const routeExists = (target: string) => ['/customers', '/home', '/'].includes(target.split(/[?#]/)[0]);

test('登录保留本前端有效目标的查询参数和锚点', () => {
  assert.equal(getLoginRedirect('/customers?country=CN#list', routeExists), '/customers?country=CN#list');
  assert.equal(getLoginRedirect('/home', routeExists), '/home');
  assert.equal(getLoginRedirect('/customers?q=two%20words', routeExists), '/customers?q=two%20words');
});

test('Vue Router 守卫真实导航保留登录目标的参数和锚点', async () => {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/login', component: {} }, { path: '/customers', component: {} }]
  });
  router.beforeEach(to => to.path === '/login' ? resolveLoginRedirect(router, to.query.redirect) : undefined);
  await router.push('/login?redirect=' + encodeURIComponent('/customers?from=login-check#list'));
  assert.equal(router.currentRoute.value.fullPath, '/customers?from=login-check#list');
});

test('首次登录和异常目标默认回客户列表，不接受旧前端及外部地址', () => {
  for (const value of [undefined, null, '', ['/home', '/customers'], 'https://example.com',
    'http://127.0.0.1:8080/customers', '//example.com', '/\\example.com', '/%2f%2fexample.com',
    '/%5cexample.com', '/login', '/login/pwd-login?redirect=/login', '/LOGIN', '/missing', '/%ZZ', '/\n/customers']) {
    assert.equal(getLoginRedirect(value, routeExists), '/customers');
  }
});
