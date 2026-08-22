import { defineStore } from 'pinia'

import {
  fetchCurrentUser,
  login as requestLogin,
  logout as requestLogout,
} from '@/api/auth'
import type { AuthResponse, AuthUser, LoginCredentials } from '@/types/auth'

let initializationRequest: Promise<AuthResponse> | null = null

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as AuthUser | null,
    initialized: false,
    checking: false,
  }),
  getters: {
    isAuthenticated: (state) => state.user !== null,
  },
  actions: {
    applyAuthResponse(response: AuthResponse) {
      this.user = response.authenticated ? response.user : null
      this.initialized = true
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
      initializationRequest = fetchCurrentUser()
      try {
        const response = await initializationRequest
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
