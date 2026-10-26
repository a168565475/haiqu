import { isAxiosError } from 'axios'
import { defineStore } from 'pinia'

import {
  fetchCurrentUser,
  login as requestLogin,
  logout as requestLogout,
} from '@/api/auth'
import type { AuthResponse, AuthUser, LoginCredentials } from '@/types/auth'

const authenticationMaxAgeMs = 30_000
const requestsByStore = new WeakMap<object, {
  initialization: Promise<number | void> | null
  mutation: Promise<void> | null
}>()

function requestsFor(store: object) {
  let requests = requestsByStore.get(store)
  if (!requests) {
    requests = { initialization: null, mutation: null }
    requestsByStore.set(store, requests)
  }
  return requests
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as AuthUser | null,
    initialized: false,
    checking: false,
    authenticationCheckedAt: 0,
    authenticationGeneration: 0,
  }),
  getters: {
    isAuthenticated: (state) => state.user !== null,
    waitingForRole: (state) => state.user?.waiting_for_role === true,
    managementCan: (state) => (permission: string) => {
      const user = state.user
      if (user?.employee?.status !== 'ACTIVE') return false
      if (user.is_superuser && user.username === 'admin') return true
      const access = user.effective_access
      return access?.active === true && access.actions[permission]?.sources.some(
        source => source.type === 'ROLE' && source.scope === 'MODULE',
      ) === true
    },
    canReadAccessDirectory(): boolean {
      return ['organizations.manage_organization', 'access_control.manage_access',
        'access_control.manage_accounts', 'access_control.manage_wecom'].some(code => this.managementCan(code))
    },
    hasPermission: (state) => (permission: string) => {
      return state.user?.permissions.includes(permission) ?? false
    },
    canFor: (state) => (permission: string, record: unknown) => {
      if (!state.user?.sales_access_enabled) return state.user?.permissions.includes(permission) ?? false
      if (!record || typeof record !== 'object') return false
      const permissions = (record as { allowed_permissions?: string[] }).allowed_permissions
      return permissions?.includes(permission) ?? false
    },
    moduleCan: (state) => (permission: string, legacy = permission, record?: unknown) => {
      if (!state.user?.module_access_enabled) return state.user?.permissions.includes(legacy) ?? false
      if (record !== undefined) {
        if (!record || typeof record !== 'object') return false
        return (record as { allowed_permissions?: string[] }).allowed_permissions?.includes(permission) ?? false
      }
      return state.user.permissions.includes(permission)
    },
    hasAnyPermission: (state) => (permissions: string[]) => {
      return permissions.some((permission) => state.user?.permissions.includes(permission))
    },
  },
  actions: {
    applyAuthResponse(response: AuthResponse) {
      this.invalidatePendingAuthentication()
      this.user = response.authenticated ? response.user : null
      this.initialized = true
      this.authenticationCheckedAt = response.authenticated ? Date.now() : 0
    },
    clearAuthentication() {
      this.applyAuthResponse({ authenticated: false, user: null })
    },
    invalidatePendingAuthentication() {
      this.authenticationGeneration += 1
      const requests = requestsFor(this)
      requests.initialization = null
      requests.mutation = null
      this.checking = false
      this.invalidateAuthenticationCheck()
    },
    invalidateAuthenticationCheck() {
      this.authenticationCheckedAt = 0
    },
    async ensureFreshAuthentication() {
      const age = Date.now() - this.authenticationCheckedAt
      const fresh = this.isAuthenticated && this.authenticationCheckedAt > 0
        && age >= 0 && age < authenticationMaxAgeMs
      const requests = requestsFor(this)
      if (fresh && !requests.initialization && !requests.mutation) return
      await this.initialize(true)
    },
    // 返回本次读取实际应用的身份代次；过期结果不返回代次。
    async initialize(force = false): Promise<number | void> {
      const requests = requestsFor(this)
      // 登录或退出尚未完成时，读取会话可能仍拿到写操作之前的身份。
      if (requests.mutation) {
        await requests.mutation
        return
      }
      if (this.initialized && !force) {
        return
      }
      if (requests.initialization) {
        return requests.initialization
      }

      this.checking = true
      this.invalidateAuthenticationCheck()
      const generation = this.authenticationGeneration
      const request = fetchCurrentUser().then(response => {
        if (generation !== this.authenticationGeneration) return
        this.applyAuthResponse(response)
        return this.authenticationGeneration
      }, (error: unknown) => {
        if (generation !== this.authenticationGeneration) return
        if (isAxiosError(error) && error.response?.status === 401) this.clearAuthentication()
        throw error
      }).finally(() => {
        if (requests.initialization !== request) return
        this.checking = false
        requests.initialization = null
      })
      requests.initialization = request
      return request
    },
    async login(credentials: LoginCredentials) {
      if (!this.initialized) {
        await this.initialize()
      }
      this.invalidatePendingAuthentication()
      const generation = this.authenticationGeneration
      const requests = requestsFor(this)
      const request = requestLogin(credentials).then(response => {
        if (generation === this.authenticationGeneration) this.applyAuthResponse(response)
      }).finally(() => {
        if (requests.mutation === request) requests.mutation = null
      })
      requests.mutation = request
      await request
    },
    async logout() {
      this.invalidatePendingAuthentication()
      const generation = this.authenticationGeneration
      const requests = requestsFor(this)
      const request = requestLogout().then(response => {
        if (generation === this.authenticationGeneration) this.applyAuthResponse(response)
      }).finally(() => {
        if (requests.mutation === request) requests.mutation = null
      })
      requests.mutation = request
      await request
    },
  },
})
