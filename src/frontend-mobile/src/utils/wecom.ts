const autoLoginAttemptKey = 'mobile:wecom:auto-login-attempted'

// UA 只选择登录入口，身份及权限仍由 ERP 后端验证。
export function isWeComBrowser(userAgent = navigator.userAgent): boolean {
  return /\bwxwork\//i.test(userAgent)
}

export function resolveMobileRedirect(value: unknown): string {
  if (typeof value !== 'string') return '/'
  const target = value === '/m' ? '/' : value.startsWith('/m/') ? value.slice(2) : value
  let decoded: string
  try { decoded = decodeURIComponent(target) } catch { return '/' }
  if (!decoded.startsWith('/') || decoded.startsWith('//') || /[\\\s\u0000-\u001f\u007f]/u.test(decoded)) return '/'
  const path = decoded.split(/[?#]/, 1)[0]!.toLowerCase()
  if (path.split('/').some(part => part === '.' || part === '..')
    || ['/login', '/auth', '/api', '/admin', '/m'].some(prefix => path === prefix || path.startsWith(`${prefix}/`))) return '/'
  return target
}

export function clearWeComLoginAttempt() {
  try { window.sessionStorage.removeItem(autoLoginAttemptKey); return true }
  catch { return false }
}

export function startWeComLogin(nextPath: string): boolean {
  try { window.sessionStorage.setItem(autoLoginAttemptKey, '1') }
  catch { return false }
  const target = `/m${resolveMobileRedirect(nextPath)}`
  window.location.replace(`/api/auth/wecom/start/?next=${encodeURIComponent(target)}`)
  return true
}

export function startAutomaticWeComLogin(nextPath: string, canReturnToAdmin: boolean): boolean {
  if (canReturnToAdmin || !isWeComBrowser()) return false
  try { if (window.sessionStorage.getItem(autoLoginAttemptKey)) return false }
  catch { return false }
  return startWeComLogin(nextPath)
}
