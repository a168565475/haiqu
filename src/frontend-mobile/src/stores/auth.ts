import { defineStore } from 'pinia'
import { isAxiosError } from 'axios'
import { ref } from 'vue'
import { apiClient, setRequestIdentity } from '@/utils/request'

export interface MobileUser {
  id: number; display_name: string; username: string; is_superuser: boolean
  employee: { id: string; display_name: string } | null
  permissions: string[]; waiting_for_role?: boolean
}
interface AuthResponse {
  authenticated: boolean; user: MobileUser | null
  account_switch?: { identity_version: string; active: boolean; can_return: boolean }
}

export const useAuthStore = defineStore('mobile-auth', () => {
  const user = ref<MobileUser | null>(null)
  const accountSwitch = ref<AuthResponse['account_switch'] | null>(null)
  const generation = ref(0)
  let refreshedAt = 0
  let refreshPromise: Promise<void> | null = null
  let identityVersion: string | null = null

  function accept(data: AuthResponse) {
    const nextUser = data.authenticated ? data.user : null
    const nextVersion = data.account_switch?.identity_version || null
    const changed = user.value?.id !== nextUser?.id || identityVersion !== nextVersion
    if (changed) generation.value += 1
    user.value = nextUser
    accountSwitch.value = data.account_switch || null
    identityVersion = nextVersion
    setRequestIdentity(nextVersion, changed)
    refreshedAt = Date.now()
  }
  function clear() {
    user.value = null
    accountSwitch.value = null
    refreshedAt = 0
    generation.value += 1
    identityVersion = null
    setRequestIdentity(null, true)
  }
  function hasPermission(permission: string) {
    return Boolean(user.value?.is_superuser || user.value?.permissions.includes(permission))
  }
  async function refresh(force = false) {
    if (!force && refreshedAt && Date.now() - refreshedAt < 15000) return
    if (refreshPromise) return refreshPromise
    refreshPromise = apiClient.get<AuthResponse>('/api/auth/me/').then(({ data }) => accept(data))
    try { await refreshPromise } finally { refreshPromise = null }
  }
  async function login(username: string, password: string) {
    try { await refresh(true) }
    catch (error) {
      const status = isAxiosError(error) ? error.response?.status : undefined
      const code = isAxiosError(error) ? error.response?.data?.error?.code : undefined
      // 与桌面端一致：明确的身份失效不能阻断用户主动密码登录；CSRF 仍由后端校验。
      if (!(status === 403 && code === 'IDENTITY_CONTEXT_INVALID')
        && !(status === 409 && code === 'IDENTITY_VERSION_CONFLICT')) throw error
      clear()
    }
    const { data } = await apiClient.post<AuthResponse>('/api/auth/login/', { username, password })
    accept(data)
  }
  async function logout() {
    await apiClient.post('/api/auth/logout/', {})
    clear()
  }
  function expire() { refreshedAt = 0 }
  return { user, accountSwitch, generation, hasPermission, refresh, login, logout, clear, expire }
})
