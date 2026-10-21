import { defineStore } from 'pinia'

import {
  fetchCurrentUser,
  login as requestLogin,
  logout as requestLogout,
} from '@/api/auth'
import type { AuthResponse, AuthUser, LoginCredentials } from '@/types/auth'

let initializationRequest: Promise<AuthResponse> | null = null
const authenticationMaxAgeMs = 30_000

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as AuthUser | null,
    initialized: false,
    checking: false,
    authenticationCheckedAt: 0,
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
      this.user = response.authenticated ? response.user : null
      this.initialized = true
      this.authenticationCheckedAt = response.authenticated ? Date.now() : 0
    },
    clearAuthentication() {
      this.user = null
      this.initialized = true
      this.invalidateAuthenticationCheck()
    },
    invalidateAuthenticationCheck() {
      this.authenticationCheckedAt = 0
    },
    async ensureFreshAuthentication() {
      const age = Date.now() - this.authenticationCheckedAt
      const fresh = this.isAuthenticated && this.authenticationCheckedAt > 0
        && age >= 0 && age < authenticationMaxAgeMs
      if (fresh && !initializationRequest) return
      await this.initialize(true)
    },
    async initialize(force = false) {
      if (this.initialized && !force) {
        return
      }
      if (initializationRequest) {
        await initializationRequest
        return
      }

      this.checking = true
      this.invalidateAuthenticationCheck()
      initializationRequest = fetchCurrentUser()
      try {
        const response = await initializationRequest
        if (response.authenticated) {
          this.applyAuthResponse(response)
          return
        }

        this.applyAuthResponse(response)
      } finally {
        this.checking = false
        initializationRequest = null
      }
    },
    async login(credentials: LoginCredentials) {
      if (!this.initialized) {
        await this.initialize()
      }
      const response = await requestLogin(credentials)
      this.applyAuthResponse(response)
    },
    async logout() {
      const response = await requestLogout()
      this.applyAuthResponse(response)
    },
  },
})
