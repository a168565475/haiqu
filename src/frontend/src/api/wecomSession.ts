import { isAxiosError } from 'axios'
import type { Router } from 'vue-router'
import { apiClient } from './request'
import type { useAuthStore } from '@/stores/auth'

export function installWeComRoleGuard(router: Router, auth: ReturnType<typeof useAuthStore>) {
  let refreshing: Promise<void> | null = null
  const interceptor = apiClient.interceptors.response.use(response => response, async (error: unknown) => {
    if (!isAxiosError(error) || error.response?.status !== 403 || error.response.data?.error?.code !== 'WECOM_ROLE_REQUIRED'
      || !error.config?.url?.startsWith('/api/v1/')) throw error
    if (!refreshing) {
      refreshing = (async () => {
        // 后端已确认待授权；刷新失败也保留受限身份，不恢复业务页面或伪装成已退出。
        if (auth.user) auth.user.waiting_for_role = true
        try { await auth.initialize(true) }
        catch { auth.invalidateAuthenticationCheck() }
        if (!auth.isAuthenticated) {
          if (router.currentRoute.value.name !== 'login') await router.replace({ name: 'login' })
        } else if (auth.waitingForRole && router.currentRoute.value.name !== 'waiting-role') {
          await router.replace({ name: 'waiting-role' })
        }
      })().finally(() => { refreshing = null })
    }
    await refreshing
    throw error
  })
  return () => apiClient.interceptors.response.eject(interceptor)
}
