const autoLoginAttemptKey = 'wecom:auto-login-attempted'

export function startWeComLoginIfNeeded(name: unknown, requiresAuth: boolean, authenticated: boolean): boolean {
  if (authenticated || name === 'login' || name === 'wecom-error') {
    try { window.sessionStorage.removeItem(autoLoginAttemptKey) }
    catch { return false }
    return false
  }
  // UA 只选择登录入口；成员身份及权限仍由后端 OAuth 校验。
  if (!requiresAuth || name === 'waiting-role' || !/\bwxwork\//i.test(navigator.userAgent)) return false
  try {
    // 回跳后 Cookie 异常仍匿名时只尝试一次，防止整页授权循环；不保存身份或凭据。
    if (window.sessionStorage.getItem(autoLoginAttemptKey)) return false
    window.sessionStorage.setItem(autoLoginAttemptKey, '1')
  } catch {
    // 浏览器禁用会话存储时保留密码入口，不能发起无法防循环的自动授权。
    return false
  }
  window.location.replace('/api/auth/wecom/start/')
  return true
}

export function wecomRouteRedirect(name: unknown, authenticated: boolean, waiting: boolean) {
  if (!authenticated || name === 'wecom-error') return
  if (waiting && name !== 'waiting-role') return { name: 'waiting-role' }
  if (!waiting && name === 'waiting-role') return { name: 'home' }
}
