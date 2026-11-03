import { CanceledError, isAxiosError } from 'axios'
import { defineStore } from 'pinia'

import {
  fetchCurrentUser,
  login as requestLogin,
  logout as requestLogout,
  fetchSwitchTargets,
  switchAccount as requestSwitchAccount,
  returnAdmin as requestReturnAdmin,
} from '@/api/auth'
import type { SwitchTargetFilters, AccountSwitchState, AuthResponse, AuthUser, LoginCredentials } from '@/types/auth'

const requestsByStore = new WeakMap<object, {
  initialization: Promise<number | void> | null
  mutation: Promise<void> | null
  // 独立于读取/导航引用；applyAuthResponse 不得提前解开仍在执行的网络写互斥锁。
  writeOwner: symbol | null
  writeSequence: number
}>()

function requestsFor(store: object) {
  let requests = requestsByStore.get(store)
  if (!requests) {
    requests = { initialization: null, mutation: null, writeOwner: null, writeSequence: 0 }
    requestsByStore.set(store, requests)
  }
  return requests
}

export class IdentityTransitionInProgressError extends Error {
  constructor() { super('身份操作正在进行，请等待完成后重新操作。'); this.name = 'IdentityTransitionInProgressError' }
}

export class IdentityNotReadyError extends Error {
  constructor() { super('身份尚未核验，请先重新读取当前会话。'); this.name = 'IdentityNotReadyError' }
}

// 排序对象键，避免 /me 序列化顺序变化误清表单；权限集合也不以返回顺序作为身份变化。
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => [key, canonical(item)]))
  }
  return value
}

function identitySignature(user: AuthUser | null, accountSwitch: AccountSwitchState | null): string {
  return JSON.stringify(canonical({
    user: user && {
      id: user.id, username: user.username, superuser: user.is_superuser,
      employee: user.employee && { id: user.employee.id, status: user.employee.status },
      permissions: [...user.permissions].sort(), dataScope: user.data_scope,
      waitingForRole: user.waiting_for_role === true,
      salesAccess: user.sales_access_enabled === true, moduleAccess: user.module_access_enabled === true,
      effectiveAccess: user.effective_access,
    },
    version: accountSwitch?.identity_version ?? null,
    active: accountSwitch?.active === true,
  }))
}

function recoverableBootstrapIdentityError(error: unknown): boolean {
  if (!isAxiosError(error)) return false
  const status = error.response?.status
  const code = error.response?.data?.error?.code
  return (status === 403 && code === 'IDENTITY_CONTEXT_INVALID')
    || (status === 409 && code === 'IDENTITY_VERSION_CONFLICT')
}

function uncertainMutation(error: unknown): boolean {
  if (!isAxiosError(error) || !error.response) return true
  const code = error.response.data?.error?.code
  return error.response.status >= 500
    || code === 'IDENTITY_VERSION_REQUIRED' || code === 'IDENTITY_VERSION_CONFLICT'
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as AuthUser | null,
    accountSwitch: null as AccountSwitchState | null,
    // 页面/缓存只订阅成功提交的语义身份；请求代次还覆盖转换开始和身份待核验。
    identityGeneration: 0,
    identityRequestGeneration: 0,
    identityTransitionPending: false,
    identityRevalidationRequired: false,
    initialized: false,
    checking: false,
    authenticationVerified: false,
    authenticationGeneration: 0,
  }),
  getters: {
    identityVersion: (state): string | null => state.accountSwitch?.identity_version ?? null,
    identitySignature: (state): string => identitySignature(state.user, state.accountSwitch),
    // 页签可保存权限签名，但不能把内存中的身份版本写进 SessionStorage。
    identityPermissionSignature: (state): string => identitySignature(state.user, null),
    identityReady: (state): boolean => state.initialized
      && !state.identityTransitionPending && !state.identityRevalidationRequired,
    canSwitchAccount(): boolean {
      return this.identityReady && !!this.identityVersion && (
        this.user?.is_superuser === true
        || (this.accountSwitch?.active === true && this.accountSwitch.can_return))
    },
    canReturnAdmin(): boolean {
      return this.identityReady && this.accountSwitch?.can_return === true
    },
    isAuthenticated: (state) => state.user !== null,
    waitingForRole: (state) => state.user?.waiting_for_role === true,
    managementCan: (state) => (permission: string) => {
      const user = state.user
      if (user?.employee?.status !== 'ACTIVE') return false
      if (user.is_superuser) return true
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
    applyAuthResponse(response: AuthResponse, forceIdentityBoundary = false) {
      const user = response.authenticated ? response.user : null
      const accountSwitch = response.account_switch ?? null
      const changed = forceIdentityBoundary || this.identitySignature !== identitySignature(user, accountSwitch)
      if (changed) this.identityTransitionPending = true
      this.invalidatePendingAuthentication()
      // 独立保存：匿名也可能保有显式返回能力，active=false 也仍有有效版本。
      this.accountSwitch = accountSwitch
      this.user = user
      if (changed) {
        this.identityRequestGeneration += 1
        this.identityGeneration += 1
      }
      this.initialized = true
      this.authenticationVerified = response.authenticated
      this.identityRevalidationRequired = false
      // 可信外部核验可接替旧读取，但不能假定尚未 settle 的旧写已经撤回。
      this.identityTransitionPending = requestsFor(this).writeOwner !== null
    },
    clearAuthentication() {
      this.applyAuthResponse({ authenticated: false, user: null }, true)
    },
    handleUnauthenticatedBusinessResponse() {
      if (!this.accountSwitch?.can_return) {
        this.clearAuthentication()
        return
      }
      // 业务401只证明员工不可用，不证明管理员返回凭据失效；等 /me 核验，不自动返回。
      this.applyAuthResponse({ authenticated: false, user: null, account_switch: this.accountSwitch }, true)
      this.requireIdentityRevalidation()
    },
    markWaitingForRole() {
      if (!this.user || this.user.waiting_for_role) return
      this.user.waiting_for_role = true
      this.identityRequestGeneration += 1
      this.identityGeneration += 1
    },
    requireIdentityRevalidation() {
      if (this.identityRevalidationRequired) return
      this.invalidatePendingAuthentication()
      this.identityRequestGeneration += 1
      this.identityRevalidationRequired = true
      this.identityTransitionPending = false
    },
    invalidatePendingAuthentication() {
      this.authenticationGeneration += 1
      const requests = requestsFor(this)
      requests.initialization = null
      requests.mutation = null
      this.checking = false
      this.invalidateAuthenticationVerification()
    },
    invalidateAuthenticationVerification() {
      this.authenticationVerified = false
    },
    async ensureAuthentication() {
      // 普通导航复用已核验身份；只在初始化、显式失效或身份冲突后重新读取。
      // 外部核验可解除导航对旧写的等待；实际业务仍受 identityReady 门禁保护。
      const verified = this.initialized && !this.identityRevalidationRequired && this.isAuthenticated && this.authenticationVerified
      const requests = requestsFor(this)
      if (verified && !requests.initialization && !requests.mutation) return
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
      if (this.initialized && !force && !this.identityRevalidationRequired) {
        return
      }
      if (requests.initialization) {
        return requests.initialization
      }

      this.checking = true
      this.invalidateAuthenticationVerification()
      const generation = this.authenticationGeneration
      const bootstrap = !this.initialized ? {
        signature: this.identitySignature,
        requestGeneration: this.identityRequestGeneration,
        writeSequence: requests.writeSequence,
      } : null
      const request = fetchCurrentUser().then(response => {
        if (generation !== this.authenticationGeneration) return
        this.applyAuthResponse(response)
        return this.authenticationGeneration
      }, (error: unknown) => {
        // guard 可在交付当前 /me 错误前标记待核验。冷启动仍须交付原错误，
        // 否则 login 会把任意触发 guard 的 409/428 当成初始化成功而发出 POST。
        const bootstrapRevalidation = bootstrap !== null && !this.initialized
          && this.identityRevalidationRequired && this.authenticationGeneration === generation + 1
          && this.identityRequestGeneration === bootstrap.requestGeneration + 1
          && this.identitySignature === bootstrap.signature && requests.writeSequence === bootstrap.writeSequence
          && (requests.initialization === null || requests.initialization === request)
        if (generation !== this.authenticationGeneration && !bootstrapRevalidation) return
        if (isAxiosError(error) && error.response?.status === 401) this.clearAuthentication()
        else if (recoverableBootstrapIdentityError(error)) this.requireIdentityRevalidation()
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
      const requests = requestsFor(this)
      if (requests.writeOwner) throw new IdentityTransitionInProgressError()
      const sequence = requests.writeSequence
      let bootstrapCurrent = this.initialized
      if (!bootstrapCurrent) {
        const generation = this.authenticationGeneration
        const requestGeneration = this.identityRequestGeneration
        const revalidationStep = this.identityRevalidationRequired ? 0 : 1
        try {
          const appliedGeneration = await this.initialize()
          bootstrapCurrent = appliedGeneration !== undefined && appliedGeneration === this.authenticationGeneration
        } catch (error) {
          // 只有明确密码登录意图可越过这两种 /me 拒绝，服务端仍执行 Session/CSRF/密码授权。
          if (!recoverableBootstrapIdentityError(error)) throw error
          bootstrapCurrent = !this.initialized && this.identityRevalidationRequired && requests.initialization === null
            && this.authenticationGeneration === generation + revalidationStep
            && this.identityRequestGeneration === requestGeneration + revalidationStep
        }
      }
      // Bootstrap 期间若有另一身份写，不能把先前登录意图排到新身份之后执行。
      if (sequence !== requests.writeSequence) throw new IdentityTransitionInProgressError()
      // undefined 或较新读取接替了 bootstrap，都不能把原意图转交给新身份。
      if (!bootstrapCurrent) throw new CanceledError('登录期间身份上下文已变化，请重新操作。')
      await this.mutateIdentity(() => requestLogin(credentials))
    },
    async logout() {
      // 身份未知或失效员工仍允许显式退出；互斥锁不因 applyAuthResponse 提前释放。
      await this.mutateIdentity(requestLogout)
    },
    async switchAccount(employeeId: string) {
      if (requestsFor(this).writeOwner) throw new IdentityTransitionInProgressError()
      if (!this.canSwitchAccount) throw new IdentityNotReadyError()
      await this.mutateIdentity(() => requestSwitchAccount(employeeId))
    },
    async returnAdmin() {
      if (requestsFor(this).writeOwner) throw new IdentityTransitionInProgressError()
      if (!this.canReturnAdmin) throw new IdentityNotReadyError()
      await this.mutateIdentity(requestReturnAdmin)
    },
    async loadSwitchTargets(q?: string, signal?: AbortSignal, filters?: SwitchTargetFilters) {
      if (!this.canSwitchAccount) throw new IdentityNotReadyError()
      const generation = this.identityRequestGeneration
      const result = await fetchSwitchTargets(q, signal, filters)
      if (generation !== this.identityRequestGeneration) throw new CanceledError('身份上下文已变化，请重新查询。')
      if (result.identity_version !== this.identityVersion) {
        // 候选版本不是当前 user 的证明，禁止只改头、不更新身份。
        this.requireIdentityRevalidation()
        throw new CanceledError('候选列表身份版本已变化，请重新读取当前会话。')
      }
      return result
    },
    async mutateIdentity(operation: () => Promise<AuthResponse>) {
      const requests = requestsFor(this)
      if (requests.writeOwner) throw new IdentityTransitionInProgressError()
      const owner = Symbol('identity-write')
      requests.writeOwner = owner
      requests.writeSequence += 1
      this.invalidatePendingAuthentication()
      this.identityRequestGeneration += 1
      this.identityTransitionPending = true
      // 普通同身份 /me 可推进读取代次，但不能吞掉仍属当前上下文的真实写结果。
      const generation = this.identityRequestGeneration
      const version = this.identityVersion
      const current = () => generation === this.identityRequestGeneration && version === this.identityVersion
      let response: Promise<AuthResponse>
      try { response = operation() }
      catch (error) { response = Promise.reject(error) }
      const request = response.then(result => {
        if (current()) this.applyAuthResponse(result, true)
      }, (error: unknown) => {
        if (current() && uncertainMutation(error)) this.requireIdentityRevalidation()
        throw error
      }).finally(() => {
        const ownsWrite = requests.writeOwner === owner
        if (ownsWrite) requests.writeOwner = null
        if (requests.mutation === request) requests.mutation = null
        if (ownsWrite) this.identityTransitionPending = false
      })
      requests.mutation = request
      await request
    },
  },
})
