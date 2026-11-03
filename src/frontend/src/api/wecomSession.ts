import { CanceledError, isAxiosError, type InternalAxiosRequestConfig } from 'axios'
import type { Router } from 'vue-router'
import { apiClient } from './request'
import type { useAuthStore } from '@/stores/auth'

export function installWeComRoleGuard(router: Router, auth: ReturnType<typeof useAuthStore>) {
  let refreshing: { generation: number; request: Promise<void> } | null = null
  const requestGenerations = new WeakMap<InternalAxiosRequestConfig, {
    authentication: number; identity: number; version: string | null
  }>()
  const requestInterceptor = apiClient.interceptors.request.use(config => {
    requestGenerations.set(config, {
      authentication: auth.authenticationGeneration, identity: auth.identityRequestGeneration, version: auth.identityVersion,
    })
    return config
  })
  const interceptor = apiClient.interceptors.response.use(response => response, async (error: unknown) => {
    if (!isAxiosError(error) || !error.config?.url?.startsWith('/api/v1/')) throw error
    const context = requestGenerations.get(error.config)
    try {
      // 较新的 /me 仍优先于更早请求的错误副作用；同身份业务结果本身不失效。
      if (context?.authentication !== auth.authenticationGeneration) throw error
      if (error.response?.status === 401) {
        auth.handleUnauthenticatedBusinessResponse()
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
          auth.markWaitingForRole()
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
    } finally {
      // 前置 transport guard 之后，这里还会 await /me 或导航；交付前必须再核校。
      // 当前401/待授权自身引起身份边界时，也不把旧页面的 response/config 暴露出去。
      if (context && (context.identity !== auth.identityRequestGeneration || context.version !== auth.identityVersion)) {
        throw new CanceledError('Identity request context is no longer usable')
      }
    }
  })
  return () => {
    apiClient.interceptors.request.eject(requestInterceptor)
    apiClient.interceptors.response.eject(interceptor)
  }
}
