import type { RouteLocationNormalized } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { clearWeComLoginAttempt, resolveMobileRedirect, startAutomaticWeComLogin } from '@/utils/wecom'

export async function mobileAuthGuard(to: Pick<RouteLocationNormalized, 'path' | 'fullPath' | 'query'>) {
  // 恢复页不再自动授权，防止 Cookie 或配置异常导致反复回跳。
  if (to.path === '/login' || to.path === '/auth/wecom-error') return
  const auth = useAuthStore()
  const waitingPage = to.path === '/auth/waiting-role'
  const next = resolveMobileRedirect(waitingPage ? to.query.next : to.fullPath)
  try { await auth.refresh() }
  catch { return { path: '/login', query: { redirect: next, reason: 'connection' } } }
  if (auth.user) {
    clearWeComLoginAttempt()
    if (auth.user.waiting_for_role && !waitingPage) return { path: '/auth/waiting-role', query: { next } }
    if (!auth.user.waiting_for_role && waitingPage) return next
    return
  }
  if (!waitingPage && startAutomaticWeComLogin(next, Boolean(auth.accountSwitch?.can_return))) return false
  return { path: '/login', query: { redirect: next } }
}
