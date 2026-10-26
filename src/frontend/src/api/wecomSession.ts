import { isAxiosError, type InternalAxiosRequestConfig } from 'axios'
import type { Router } from 'vue-router'
import { apiClient } from './request'
import type { useAuthStore } from '@/stores/auth'

export function installWeComRoleGuard(router: Router, auth: ReturnType<typeof useAuthStore>) {
  let refreshing: { generation: number; request: Promise<void> } | null = null
  const requestGenerations = new WeakMap<InternalAxiosRequestConfig, number>()
  const requestInterceptor = apiClient.interceptors.request.use(config => {
    requestGenerations.set(config, auth.authenticationGeneration)
    return config
  })
  const interceptor = apiClient.interceptors.response.use(response => response, async (error: unknown) => {
    if (!isAxiosError(error) || !error.config?.url?.startsWith('/api/v1/')) throw error
    // 旧会话的迟到响应不能撤销用户随后登录得到的新身份。
    if (requestGenerations.get(error.config) !== auth.authenticationGeneration) throw error
    if (error.response?.status === 401) {
      auth.clearAuthentication()
      const currentRoute = router.currentRoute.value
      if (currentRoute.name !== 'login') {
        await router.replace({ name: 'login', query: { redirect: currentRoute.fullPath } })
      }
      throw error
    }
    if (error.response?.status !== 403 || error.response.data?.error?.code !== 'WECOM_ROLE_REQUIRED') throw error
    const generation = auth.authenticationGeneration
    if (!refreshing || refreshing.generation !== generation) {
      const request = (async () => {
        // 后端已确认待授权；刷新失败也保留受限身份，不恢复业务页面或伪装成已退出。
        if (auth.user) auth.user.waiting_for_role = true
        let appliedGeneration: number | void
        try { appliedGeneration = await auth.initialize(true) }
        catch (refreshError) {
          // 同代网络失败仍进入等待页；401已清身份时进入登录页。
          if (generation !== auth.authenticationGeneration
            && !(isAxiosError(refreshError) && refreshError.response?.status === 401 && !auth.isAuthenticated)) return
          appliedGeneration = auth.authenticationGeneration
        }
        if (appliedGeneration !== auth.authenticationGeneration) return
        if (!auth.isAuthenticated) {
          if (router.currentRoute.value.name !== 'login') await router.replace({ name: 'login' })
        } else if (auth.waitingForRole && router.currentRoute.value.name !== 'waiting-role') {
          await router.replace({ name: 'waiting-role' })
        }
      })().finally(() => {
        if (refreshing?.request === request) refreshing = null
      })
      refreshing = { generation, request }
    }
    await refreshing.request
    throw error
  })
  return () => {
    apiClient.interceptors.request.eject(requestInterceptor)
    apiClient.interceptors.response.eject(interceptor)
  }
}
