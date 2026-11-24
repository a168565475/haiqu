import assert from 'node:assert/strict';
import { afterEach, mock, test } from 'node:test';
import { fetchErpUserSession, loginErp, logoutErp } from './erp-auth';

// 认证边界单测仅使用虚构数据，不执行真实登录。
const anonymous = { authenticated: false, user: null };
const session = {
  authenticated: true,
  user: {
    id: 42,
    username: 'unit-test-user',
    display_name: '测试员工',
    is_superuser: false,
    employee: { id: 'employee-test', employee_code: 'TEST-001', display_name: '测试员工', status: 'ACTIVE' },
    permissions: ['customers.view_customeraccount'],
    data_scope: 'ASSIGNED_AND_GRANTED',
    sales_access_enabled: true,
    module_access_enabled: false,
    effective_access: {
      active: true,
      is_superuser: false,
      roles: [{ id: 'role-test', name: '测试角色', code: 'TEST' }],
      actions: { 'customers.view_customeraccount': { scopes: ['OWN'], sources: [{ type: 'ROLE', role_id: 'role-test', scope: 'OWN' }] } },
      legacy_sources: [],
      business_scope_enforcement: 'PARTIAL',
      version: 'test-version'
    }
  }
};
const originalDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
const csrfToken = 'a'.repeat(32);

function setCookie(cookie: string) {
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { cookie } });
}

function respondSequence(...responses: Response[]) {
  let next = 0;
  return mock.method(globalThis, 'fetch', async (_input: RequestInfo | URL, _init?: RequestInit) => {
    const response = responses[next];
    next += 1;
    assert.ok(response, '认证请求次数超过测试预期');
    return response;
  });
}

afterEach(() => {
  mock.restoreAll();
  if (originalDocument) Object.defineProperty(globalThis, 'document', originalDocument);
  else Reflect.deleteProperty(globalThis, 'document');
});

test('会话 GET 返回真实用户字段并仅携带同源 Cookie', async () => {
  const request = respondSequence(Response.json(session));
  const result = await fetchErpUserSession();
  assert.equal(result.authenticated, true);
  assert.equal(result.user?.id, 42);
  assert.deepEqual(result.user?.permissions, ['customers.view_customeraccount']);
  assert.equal(result.user?.employee?.employee_code, 'TEST-001');
  assert.equal(result.user?.effective_access?.actions['customers.view_customeraccount'].scopes[0], 'OWN');
  const [url, options] = request.mock.calls[0].arguments;
  assert.equal(url, '/erp-api/auth/me/');
  assert.equal(options?.method, 'GET');
  assert.equal(options?.credentials, 'same-origin');
  assert.equal(options?.cache, 'no-store');
  assert.equal(options?.body, undefined);
  assert.equal(new Headers(options?.headers).get('authorization'), null);
});

test('匿名会话是正常未登录结果', async () => {
  respondSequence(Response.json(anonymous));
  assert.deepEqual(await fetchErpUserSession(), { authenticated: false, user: null });
});

test('登录先建立 CSRF，再发送完整用户名和未修剪的密码', async () => {
  setCookie('unrelated_cookie=value');
  const request = mock.method(globalThis, 'fetch', async (input: RequestInfo | URL, _init?: RequestInit) => {
    if (input === '/erp-api/auth/me/') {
      setCookie(`unrelated_cookie=value; csrftoken=${csrfToken}`);
      return Response.json(anonymous);
    }
    return Response.json(session);
  });
  const result = await loginErp('  unit-test-user  ', ' unit-test-password ');
  assert.equal(result.authenticated, true);
  assert.equal(request.mock.callCount(), 2);
  assert.equal(request.mock.calls[0].arguments[0], '/erp-api/auth/me/');
  const [url, options] = request.mock.calls[1].arguments;
  assert.equal(url, '/erp-api/auth/login/');
  assert.equal(options?.method, 'POST');
  assert.equal(options?.credentials, 'same-origin');
  assert.equal(options?.cache, 'no-store');
  const headers = new Headers(options?.headers);
  assert.equal(headers.get('x-csrftoken'), csrfToken);
  assert.equal(headers.get('content-type'), 'application/json');
  assert.equal(headers.get('authorization'), null);
  assert.equal(headers.get('apifoxtoken'), null);
  assert.deepEqual(JSON.parse(String(options?.body)), { username: 'unit-test-user', password: ' unit-test-password ' });
});

test('登录读取精确 Cookie 名称且不复用旧 CSRF', async () => {
  setCookie(`oldcsrftoken=${'b'.repeat(32)}; csrftoken=${'c'.repeat(32)}`);
  const request = mock.method(globalThis, 'fetch', async (input: RequestInfo | URL, _init?: RequestInit) => {
    if (input === '/erp-api/auth/me/') {
      setCookie(`oldcsrftoken=${'b'.repeat(32)}; csrftoken=${csrfToken}`);
      return Response.json(anonymous);
    }
    return Response.json(session);
  });
  await loginErp('unit-test-user', 'unit-test-password');
  assert.equal(new Headers(request.mock.calls[1].arguments[1]?.headers).get('x-csrftoken'), csrfToken);
});

test('空用户名和超长密码在发出请求前失败', async () => {
  const request = respondSequence();
  await assert.rejects(loginErp('  ', 'unit-test-password'), { name: 'ErpAuthError', code: 'INVALID_CREDENTIALS', status: 0 });
  await assert.rejects(loginErp('unit-test-user', 'x'.repeat(129)), { name: 'ErpAuthError', code: 'INVALID_CREDENTIALS', status: 0 });
  assert.equal(request.mock.callCount(), 0);
});

test('没有可用 CSRF 时阻止提交登录密码', async () => {
  for (const cookie of ['', 'oldcsrftoken=irrelevant', 'csrftoken=%ZZ']) {
    setCookie(cookie);
    const request = respondSequence(Response.json(anonymous));
    await assert.rejects(loginErp('unit-test-user', 'unit-test-password'), { name: 'ErpAuthError', code: 'CSRF_ERROR', status: 0 });
    assert.equal(request.mock.callCount(), 1);
    mock.restoreAll();
  }
});

test('错误密码保留后端 400 信息', async () => {
  setCookie(`csrftoken=${csrfToken}`);
  respondSequence(Response.json(anonymous), Response.json({ detail: '用户名或密码错误' }, { status: 400 }));
  await assert.rejects(loginErp('unit-test-user', 'wrong-unit-test-password'), {
    name: 'ErpAuthError', code: 'HTTP_ERROR', status: 400, message: '用户名或密码错误'
  });
});

test('登录字段错误保留可读提示', async () => {
  setCookie(`csrftoken=${csrfToken}`);
  respondSequence(Response.json(anonymous), Response.json({ username: ['用户名无效'] }, { status: 400 }));
  await assert.rejects(loginErp('unit-test-user', 'unit-test-password'), { name: 'ErpAuthError', status: 400, message: '用户名无效' });
});

test('CSRF 403 即使返回 HTML 也不能视为登录成功', async () => {
  setCookie(`csrftoken=${csrfToken}`);
  respondSequence(Response.json(anonymous), new Response('<html>CSRF verification failed</html>', { status: 403 }));
  await assert.rejects(loginErp('unit-test-user', 'unit-test-password'), { name: 'ErpAuthError', code: 'HTTP_ERROR', status: 403 });
});

test('会话预检查失败时不提交登录凭据', async () => {
  const request = respondSequence(Response.json({ detail: '服务不可用' }, { status: 503 }));
  await assert.rejects(loginErp('unit-test-user', 'unit-test-password'), { name: 'ErpAuthError', status: 503 });
  assert.equal(request.mock.callCount(), 1);
});

test('网络失败和 HTTP 200 非 JSON 明确报错', async () => {
  mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch'); });
  await assert.rejects(fetchErpUserSession(), { name: 'ErpAuthError', code: 'NETWORK_ERROR', status: 0 });
  mock.restoreAll();
  respondSequence(new Response('<html>not JSON</html>'));
  await assert.rejects(fetchErpUserSession(), { name: 'ErpAuthError', code: 'INVALID_RESPONSE', status: 200 });
});

test('损坏用户、权限及不一致认证状态不会变成有效会话', async () => {
  const malformed = [
    { authenticated: true, user: null },
    { authenticated: false, user: session.user },
    { ...session, user: { ...session.user, id: '42' } },
    { ...session, user: { ...session.user, permissions: ['valid', 3] } },
    { ...session, user: { ...session.user, employee: {} } },
    { ...session, user: { ...session.user, effective_access: { ...session.user.effective_access, actions: [] } } }
  ];
  for (const body of malformed) {
    respondSequence(Response.json(body));
    await assert.rejects(fetchErpUserSession(), { name: 'ErpAuthError', code: 'INVALID_RESPONSE', status: 200 });
    mock.restoreAll();
  }
});

test('登录响应仍是匿名时必须报告失败', async () => {
  setCookie(`csrftoken=${csrfToken}`);
  respondSequence(Response.json(anonymous), Response.json(anonymous));
  await assert.rejects(loginErp('unit-test-user', 'unit-test-password'), { name: 'ErpAuthError', code: 'INVALID_RESPONSE', status: 200 });
});

test('退出先获取当前 CSRF，只在服务器确认匿名后成功', async () => {
  setCookie(`csrftoken=${csrfToken}`);
  const request = respondSequence(Response.json(session), Response.json(anonymous));
  assert.equal(await logoutErp(), undefined);
  assert.equal(request.mock.callCount(), 2);
  assert.equal(request.mock.calls[0].arguments[0], '/erp-api/auth/me/');
  const [url, options] = request.mock.calls[1].arguments;
  assert.equal(url, '/erp-api/auth/logout/');
  assert.equal(options?.method, 'POST');
  assert.equal(options?.credentials, 'same-origin');
  assert.equal(options?.cache, 'no-store');
  assert.equal(new Headers(options?.headers).get('x-csrftoken'), csrfToken);
  assert.equal(new Headers(options?.headers).get('authorization'), null);
});

test('退出响应仍已登录时明确失败，不能只清空本地状态', async () => {
  setCookie(`csrftoken=${csrfToken}`);
  respondSequence(Response.json(session), Response.json(session));
  await assert.rejects(logoutErp(), { name: 'ErpAuthError', code: 'INVALID_RESPONSE', status: 200 });
});

test('退出 CSRF 和网络失败都向调用方报告', async () => {
  setCookie('');
  const request = respondSequence(Response.json(session));
  await assert.rejects(logoutErp(), { name: 'ErpAuthError', code: 'CSRF_ERROR', status: 0 });
  assert.equal(request.mock.callCount(), 1);
  mock.restoreAll();
  setCookie(`csrftoken=${csrfToken}`);
  mock.method(globalThis, 'fetch', async (input: RequestInfo | URL) => {
    if (input === '/erp-api/auth/me/') return Response.json(session);
    throw new TypeError('Failed to fetch');
  });
  await assert.rejects(logoutErp(), { name: 'ErpAuthError', code: 'NETWORK_ERROR', status: 0 });
});
