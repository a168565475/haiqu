import type { ErpAccessScope, ErpAuthError, ErpEffectiveAccess, ErpSession, ErpUser } from '../../typings/erp-auth';

function authError(code: ErpAuthError['code'], status: number, message: string): ErpAuthError {
  return Object.assign(new Error(message), { name: 'ErpAuthError' as const, code, status });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isAccessScope(value: unknown): value is ErpAccessScope {
  return isString(value) && ['OWN', 'TEAM', 'ALL', 'MODULE', 'WORKSHOP', 'CRAFT'].includes(value);
}

function isAccessSource(value: unknown): boolean {
  return isRecord(value) && isString(value.type)
    && (value.role_id === undefined || isString(value.role_id))
    && (value.scope === undefined || isAccessScope(value.scope))
    && (value.resource_ids === undefined || isStringArray(value.resource_ids));
}

function isLegacySource(value: unknown): boolean {
  return isRecord(value) && isString(value.type) && isString(value.permission)
    && (value.name === undefined || isString(value.name))
    && (value.role_id === undefined || isString(value.role_id))
    && (value.group_id === undefined || (typeof value.group_id === 'number' && Number.isSafeInteger(value.group_id)));
}

function isEffectiveAccess(value: unknown): value is ErpEffectiveAccess {
  if (!isRecord(value) || !isRecord(value.actions)) return false;
  const validActions = Object.values(value.actions).every(action => isRecord(action)
    && Array.isArray(action.scopes) && action.scopes.every(isAccessScope)
    && Array.isArray(action.sources) && action.sources.every(isAccessSource));
  return typeof value.active === 'boolean' && typeof value.is_superuser === 'boolean'
    && Array.isArray(value.roles) && value.roles.every(role => isRecord(role)
      && [role.id, role.name, role.code].every(isString))
    && validActions && Array.isArray(value.legacy_sources) && value.legacy_sources.every(isLegacySource)
    && isString(value.business_scope_enforcement) && ['ENABLED', 'PARTIAL', 'DISABLED'].includes(value.business_scope_enforcement)
    && isString(value.version);
}

function isEmployee(value: unknown): value is ErpUser['employee'] {
  return value === null || (isRecord(value)
    && [value.id, value.employee_code, value.display_name, value.status].every(isString));
}

function isUser(value: unknown): value is ErpUser {
  return isRecord(value) && typeof value.id === 'number' && Number.isSafeInteger(value.id) && value.id > 0
    && isString(value.username) && isString(value.display_name) && typeof value.is_superuser === 'boolean'
    && isEmployee(value.employee) && isStringArray(value.permissions)
    && isString(value.data_scope) && ['ALL', 'ASSIGNED_AND_GRANTED', 'NONE'].includes(value.data_scope)
    && (value.sales_access_enabled === undefined || typeof value.sales_access_enabled === 'boolean')
    && (value.module_access_enabled === undefined || typeof value.module_access_enabled === 'boolean')
    && (value.effective_access === undefined || isEffectiveAccess(value.effective_access));
}

function isSession(value: unknown): value is ErpSession {
  return isRecord(value) && ((value.authenticated === true && isUser(value.user))
    || (value.authenticated === false && value.user === null));
}

function responseMessage(body: unknown, status: number): string {
  if (isRecord(body)) {
    if (isString(body.detail) && body.detail) return body.detail;
    if (isRecord(body.error) && isString(body.error.message) && body.error.message) return body.error.message;
    const fieldError = Object.values(body).find(value => isStringArray(value) && Boolean(value[0]));
    if (isStringArray(fieldError)) return fieldError[0];
  }
  if (status === 403) return 'ERP 会话或 CSRF 校验失败，请刷新页面后重试。';
  if (status === 401) return 'ERP 登录状态已失效，请重新登录。';
  return `ERP 认证请求失败（HTTP ${status}）。`;
}

async function readResponse(response: Response): Promise<ErpSession> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    if (!response.ok) throw authError('HTTP_ERROR', response.status, responseMessage(null, response.status));
    throw authError('INVALID_RESPONSE', response.status, 'ERP 认证接口返回的内容不是有效 JSON。');
  }
  if (!response.ok) throw authError('HTTP_ERROR', response.status, responseMessage(body, response.status));
  if (!isSession(body)) throw authError('INVALID_RESPONSE', response.status, 'ERP 返回的登录状态或用户资料结构异常。');
  return body;
}

async function requestSession(endpoint: 'me/' | 'login/' | 'logout/', options: RequestInit): Promise<ErpSession> {
  let response: Response;
  try {
    response = await fetch(`/erp-api/auth/${endpoint}`, {
      ...options,
      credentials: 'same-origin',
      mode: 'same-origin',
      cache: 'no-store',
      redirect: 'error'
    });
  } catch {
    throw authError('NETWORK_ERROR', 0, '无法连接 ERP 认证服务，请检查网络后重试。');
  }
  return readResponse(response);
}

function csrfCookie(): string {
  if (typeof document === 'undefined') throw authError('CSRF_ERROR', 0, '当前环境无法读取 ERP CSRF Cookie。');
  const cookie = document.cookie.split(';').map(value => value.trim()).find(value => value.startsWith('csrftoken='));
  let token: string;
  try {
    token = decodeURIComponent(cookie?.slice('csrftoken='.length) ?? '');
  } catch {
    throw authError('CSRF_ERROR', 0, 'ERP CSRF Cookie 格式异常，请刷新页面后重试。');
  }
  if (!/^(?:[a-zA-Z0-9]{32}|[a-zA-Z0-9]{64})$/.test(token)) {
    throw authError('CSRF_ERROR', 0, '未能获取有效的 ERP CSRF Cookie，请刷新页面后重试。');
  }
  return token;
}

async function csrfHeaders(): Promise<Record<string, string>> {
  // Django 登录会轮换 CSRF，每次写认证状态前获取当前 Cookie，不缓存令牌。
  await fetchErpUserSession();
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRFToken': csrfCookie() };
}

export async function fetchErpUserSession(): Promise<ErpSession> {
  return requestSession('me/', { method: 'GET', headers: { Accept: 'application/json' } });
}

export async function loginErp(username: string, password: string): Promise<ErpSession> {
  if (!isString(username) || !username.trim() || username.trim().length > 150
    || !isString(password) || password.length === 0 || password.length > 128) {
    throw authError('INVALID_CREDENTIALS', 0, '请输入有效的用户名和密码；用户名最多 150 字符，密码最多 128 字符。');
  }
  const headers = await csrfHeaders();
  const session = await requestSession('login/', {
    method: 'POST', headers, body: JSON.stringify({ username: username.trim(), password })
  });
  if (!session.authenticated) throw authError('INVALID_RESPONSE', 200, 'ERP 未确认登录成功，请重试。');
  return session;
}

export async function logoutErp(): Promise<void> {
  const headers = await csrfHeaders();
  const session = await requestSession('logout/', { method: 'POST', headers });
  if (session.authenticated) throw authError('INVALID_RESPONSE', 200, 'ERP 未确认退出成功，请重试。');
}
