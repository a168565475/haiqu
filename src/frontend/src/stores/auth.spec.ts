import { createPinia, setActivePinia } from 'pinia'
import { AxiosError, isCancel } from 'axios'
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchCurrentUser, login as requestLogin, logout as requestLogout, requestDevelopmentAutoLogin,
  switchAccount as requestSwitchAccount, returnAdmin as requestReturnAdmin } from '@/api/auth'
import { IdentityTransitionInProgressError, useAuthStore } from './auth'
import type { AuthResponse } from '@/types/auth'

vi.mock('@/api/auth', () => ({
  fetchCurrentUser: vi.fn(), login: vi.fn(), logout: vi.fn(), requestDevelopmentAutoLogin: vi.fn(),
  fetchSwitchTargets: vi.fn(), switchAccount: vi.fn(), returnAdmin: vi.fn(),
}))

const authenticated: AuthResponse = {
  authenticated: true,
  user: { id: 1, username: 'test', display_name: '测试用户', is_superuser: false, employee: null, permissions: ['customers.view_customeraccount'], data_scope: 'ALL' },
}

function deferredResponse() {
  let resolve!: (response: AuthResponse) => void
  let reject!: (error: Error) => void
  const promise = new Promise<AuthResponse>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

describe('身份变化使旧请求失效', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(fetchCurrentUser).mockReset()
    vi.mocked(requestLogin).mockReset()
    vi.mocked(requestLogout).mockReset()
  })

  it.each(['clear', 'logout', 'login', 'apply'] as const)('%s 后旧会话响应不能恢复或替换身份', async action => {
    const store = useAuthStore()
    store.applyAuthResponse(authenticated)
    const old = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(old.promise)
    const refresh = store.initialize(true)
    const next: AuthResponse = { authenticated: true, user: { ...authenticated.user!, id: 2, username: 'next' } }
    if (action === 'clear') store.clearAuthentication()
    if (action === 'logout') {
      vi.mocked(requestLogout).mockResolvedValueOnce({ authenticated: false, user: null })
      await store.logout()
    }
    if (action === 'login') {
      vi.mocked(requestLogin).mockResolvedValueOnce(next)
      await store.login({ username: 'next', password: 'test-only' })
    }
    if (action === 'apply') store.applyAuthResponse(next)
    old.resolve(authenticated)
    await refresh
    expect(store.user?.id ?? null).toBe(action === 'login' || action === 'apply' ? 2 : null)
    expect(store.checking).toBe(false)
  })

  it('旧请求收尾不清除新请求的读取状态或去重引用', async () => {
    const store = useAuthStore()
    store.applyAuthResponse(authenticated)
    const old = deferredResponse()
    const current = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const first = store.initialize(true)
    store.clearAuthentication()
    const second = store.initialize(true)
    old.resolve(authenticated)
    await first
    const checkingDuringCurrentRequest = store.checking
    const third = store.initialize(true)
    current.resolve({ authenticated: false, user: null })
    await Promise.all([second, third])
    expect(checkingDuringCurrentRequest).toBe(true)
    expect(fetchCurrentUser).toHaveBeenCalledTimes(2)
    expect(store.isAuthenticated).toBe(false)
  })

  it('旧请求失败不再向后续导航传播过期错误', async () => {
    const store = useAuthStore()
    const old = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(old.promise)
    const refresh = store.initialize()
    store.clearAuthentication()
    old.reject(new Error('旧请求断网'))
    await expect(refresh).resolves.toBeUndefined()
    expect(store.isAuthenticated).toBe(false)
  })

  it('应用身份时的内部错误不得被当作旧请求错误吞掉', async () => {
    const store = useAuthStore()
    const apply = store.applyAuthResponse.bind(store)
    const error = new Error('应用身份的内部错误')
    vi.spyOn(store, 'applyAuthResponse').mockImplementation(response => {
      apply(response)
      throw error
    })
    vi.mocked(fetchCurrentUser).mockResolvedValueOnce(authenticated)
    await expect(store.initialize()).rejects.toBe(error)
  })

  it('不同 Pinia 实例不共享身份查询', async () => {
    const firstStore = useAuthStore(createPinia())
    const secondStore = useAuthStore(createPinia())
    const firstResponse = deferredResponse()
    const secondResponse = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(firstResponse.promise).mockReturnValueOnce(secondResponse.promise)
    const first = firstStore.initialize()
    const second = secondStore.initialize()
    firstResponse.resolve(authenticated)
    secondResponse.resolve({ authenticated: true, user: { ...authenticated.user!, id: 2 } })
    await Promise.all([first, second])
    expect(firstStore.user?.id).toBe(1)
    expect(secondStore.user?.id).toBe(2)
  })

  it('退出进行中导航等待写操作，不读取仍有效的旧会话', async () => {
    const store = useAuthStore()
    store.applyAuthResponse(authenticated)
    const logoutResponse = deferredResponse()
    vi.mocked(requestLogout).mockReturnValueOnce(logoutResponse.promise)
    vi.mocked(fetchCurrentUser).mockResolvedValue(authenticated)
    const logout = store.logout()
    const navigation = store.initialize(true)
    logoutResponse.resolve({ authenticated: false, user: null })
    await Promise.all([logout, navigation])
    expect(fetchCurrentUser).not.toHaveBeenCalled()
    expect(store.isAuthenticated).toBe(false)
  })

  it('退出失败保留身份，但旧读取不能恢复核验状态', async () => {
    const store = useAuthStore()
    store.applyAuthResponse(authenticated)
    const old = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(old.promise)
    const refresh = store.initialize(true)
    vi.mocked(requestLogout).mockRejectedValueOnce(new Error('退出请求断网'))
    await expect(store.logout()).rejects.toThrow('退出请求断网')
    old.resolve(authenticated)
    await refresh
    expect(store.user?.id).toBe(1)
    expect(store.authenticationVerified).toBe(false)
  })

  it.each(['login', 'logout'] as const)('新身份导航不等待旧%s，也不接收它的迟到失败', async action => {
    const store = useAuthStore()
    store.applyAuthResponse(authenticated)
    const old = deferredResponse()
    vi.mocked(action === 'login' ? requestLogin : requestLogout).mockReturnValueOnce(old.promise)
    const oldError = new Error('旧身份写请求失败')
    const mutation = (action === 'login' ? store.login({ username: 'old', password: 'test-only' }) : store.logout())
      .catch(error => error)
    store.applyAuthResponse({ authenticated: true, user: { ...authenticated.user!, id: 2 } })
    let navigationState = 'pending'
    const navigation = store.ensureAuthentication().then(
      () => { navigationState = 'resolved' },
      () => { navigationState = 'rejected' },
    )
    await flushPromises()
    const stateBeforeOldRequestSettles = navigationState
    old.reject(oldError)
    expect(await mutation).toBe(oldError)
    await navigation
    expect(stateBeforeOldRequestSettles).toBe('resolved')
    expect(navigationState).toBe('resolved')
    expect(store.user?.id).toBe(2)
    expect(fetchCurrentUser).not.toHaveBeenCalled()
  })

  it.each([401, 500])('身份查询 HTTP %s 仅在明确未认证时清身份', async status => {
    const store = useAuthStore()
    store.applyAuthResponse(authenticated)
    const error = new AxiosError('auth response', undefined, undefined, undefined,
      { status, data: {}, headers: {}, statusText: '', config: {} as never })
    vi.mocked(fetchCurrentUser).mockRejectedValueOnce(error)
    await expect(store.initialize(true)).rejects.toBe(error)
    expect(store.isAuthenticated).toBe(status !== 401)
    expect(store.authenticationVerified).toBe(false)
  })
})

// 以下使用 Mock 验证显式意图与并发编排，不替代真实 Session/CSRF/密码授权验收。
describe('冷启动上下文失效后的显式密码登录', () => {
  const credentials = { username: 'next', password: 'test-only' }
  const known: AuthResponse = { ...authenticated,
    account_switch: { active: true, can_return: true, identity_version: 'last-known-version' } }
  const next: AuthResponse = { authenticated: true,
    user: { ...authenticated.user!, id: 2, username: credentials.username } }
  const recoverable = [
    [403, 'IDENTITY_CONTEXT_INVALID'], [409, 'IDENTITY_VERSION_CONFLICT'],
  ] as const
  function httpError(status: number, code?: string) {
    return new AxiosError('bootstrap failed', undefined, undefined, undefined, {
      status, data: { error: { code } }, headers: {}, statusText: '', config: {} as never,
    })
  }
  function coldStoreWithMetadata() {
    const store = useAuthStore()
    // 模拟尚未核验的最后已知元数据，不把它伪装成 initialized/ready。
    store.$patch({ user: known.user, accountSwitch: known.account_switch })
    return store
  }
  beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks() })

  it.each(recoverable)('单独初始化 %s/%s 保留元数据并拒绝，不自动发起身份写', async (status, code) => {
    const store = coldStoreWithMetadata()
    const user = store.user; const metadata = store.accountSwitch
    const pageGeneration = store.identityGeneration; const requestGeneration = store.identityRequestGeneration
    const authenticationGeneration = store.authenticationGeneration
    const error = httpError(status, code)
    vi.mocked(fetchCurrentUser).mockRejectedValueOnce(error)
    await expect(store.initialize()).rejects.toBe(error)
    expect(store.user).toBe(user); expect(store.accountSwitch).toBe(metadata)
    expect(store.initialized).toBe(false); expect(store.identityReady).toBe(false)
    expect(store.identityRevalidationRequired).toBe(true); expect(store.checking).toBe(false)
    expect(store.authenticationVerified).toBe(false)
    expect(store.identityGeneration).toBe(pageGeneration)
    expect(store.identityRequestGeneration).toBe(requestGeneration + 1)
    expect(store.authenticationGeneration).toBe(authenticationGeneration + 1)
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
    expect(requestLogin).not.toHaveBeenCalled(); expect(requestLogout).not.toHaveBeenCalled()
    expect(requestSwitchAccount).not.toHaveBeenCalled(); expect(requestReturnAdmin).not.toHaveBeenCalled()
    expect(requestDevelopmentAutoLogin).not.toHaveBeenCalled()
  })

  it.each(recoverable)('明确密码登录可在 bootstrap %s/%s 后唯一 POST，写前不清元数据', async (status, code) => {
    const store = coldStoreWithMetadata()
    const user = store.user; const metadata = store.accountSwitch
    const bootstrap = deferredResponse(); const write = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(bootstrap.promise)
    vi.mocked(requestLogin).mockReturnValueOnce(write.promise)
    const login = store.login(credentials)
    expect(requestLogin).not.toHaveBeenCalled()
    bootstrap.reject(httpError(status, code))
    await flushPromises()
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
    expect(requestLogin).toHaveBeenCalledExactlyOnceWith(credentials)
    expect(store.user).toBe(user); expect(store.accountSwitch).toBe(metadata)
    expect(store.initialized).toBe(false); expect(store.identityReady).toBe(false)
    expect(store.identityRevalidationRequired).toBe(true); expect(store.identityTransitionPending).toBe(true)
    await expect(store.login(credentials)).rejects.toBeInstanceOf(IdentityTransitionInProgressError)
    await expect(store.logout()).rejects.toBeInstanceOf(IdentityTransitionInProgressError)
    expect(requestLogin).toHaveBeenCalledTimes(1); expect(requestLogout).not.toHaveBeenCalled()
    write.resolve(next); await login
    expect(store.user?.id).toBe(2); expect(store.accountSwitch).toBeNull()
    expect(store.initialized).toBe(true); expect(store.identityReady).toBe(true)
    expect(requestSwitchAccount).not.toHaveBeenCalled(); expect(requestReturnAdmin).not.toHaveBeenCalled()
    expect(requestDevelopmentAutoLogin).not.toHaveBeenCalled()
  })

  it.each(recoverable)('先前 bootstrap %s/%s 不缓存登录许可，后续明确登录仍核验且只发一次 POST', async (status, code) => {
    const store = useAuthStore(); const error = httpError(status, code)
    vi.mocked(fetchCurrentUser).mockRejectedValueOnce(error).mockRejectedValueOnce(error)
    await expect(store.initialize()).rejects.toBe(error)
    expect(requestLogin).not.toHaveBeenCalled()
    vi.mocked(requestLogin).mockResolvedValueOnce(next)
    await store.login(credentials)
    expect(fetchCurrentUser).toHaveBeenCalledTimes(2)
    expect(requestLogin).toHaveBeenCalledExactlyOnceWith(credentials)
    expect(store.user?.id).toBe(2); expect(store.identityReady).toBe(true)
  })

  it.each(recoverable)('guard 先推进待核验代次时仍识别原 bootstrap %s/%s', async (status, code) => {
    const store = useAuthStore(); const error = httpError(status, code)
    vi.mocked(fetchCurrentUser).mockImplementationOnce(async () => {
      store.requireIdentityRevalidation()
      throw error
    })
    vi.mocked(requestLogin).mockResolvedValueOnce(next)
    await store.login(credentials)
    expect(requestLogin).toHaveBeenCalledExactlyOnceWith(credentials)
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
    expect(store.user?.id).toBe(2); expect(store.identityReady).toBe(true)
  })

  it.each([
    [403, 'PERMISSION_DENIED', false], [403, 'CSRF_FAILED', false],
    [403, 'IDENTITY_VERSION_CONFLICT', false], [409, 'IDENTITY_CONTEXT_INVALID', false],
    [409, 'BUSINESS_CONFLICT', false], [409, 'IDENTITY_VERSION_REQUIRED', true],
    [428, 'IDENTITY_VERSION_REQUIRED', true], [428, 'IDENTITY_VERSION_CONFLICT', true],
    [503, 'IDENTITY_CONTEXT_INVALID', false], [503, 'IDENTITY_VERSION_CONFLICT', false],
    [403, undefined, false], [409, undefined, false],
  ] as const)('bootstrap %s/%s 不属于允许组合（guard=%s），保留原错误且零 POST', async (status, code, guard) => {
    const store = coldStoreWithMetadata(); const error = httpError(status, code)
    const user = store.user; const metadata = store.accountSwitch
    vi.mocked(fetchCurrentUser).mockImplementationOnce(async () => {
      if (guard) store.requireIdentityRevalidation()
      throw error
    })
    await expect(store.login(credentials)).rejects.toBe(error)
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1); expect(requestLogin).not.toHaveBeenCalled()
    expect(store.user).toBe(user); expect(store.accountSwitch).toBe(metadata)
    expect(store.initialized).toBe(false); expect(store.identityReady).toBe(false)
    expect(store.checking).toBe(false); expect(store.identityTransitionPending).toBe(false)
    expect(requestReturnAdmin).not.toHaveBeenCalled(); expect(requestDevelopmentAutoLogin).not.toHaveBeenCalled()
  })

  it.each([
    new Error('bootstrap network failure'), new AxiosError('bootstrap network failure', 'ERR_NETWORK'),
    new AxiosError('wrong payload', undefined, undefined, undefined, {
      status: 403, data: { code: 'IDENTITY_CONTEXT_INVALID' }, headers: {}, statusText: '', config: {} as never,
    }),
  ])('网络或非结构化代码不允许跳过 bootstrap：%s', async error => {
    const store = useAuthStore(); vi.mocked(fetchCurrentUser).mockRejectedValueOnce(error)
    await expect(store.login(credentials)).rejects.toBe(error)
    expect(requestLogin).not.toHaveBeenCalled(); expect(store.initialized).toBe(false)
  })

  it.each([false, true])('并发初始化与两个明确登录共享 bootstrap；guard=%s 时也仅一个 POST', async guard => {
    const store = useAuthStore(); const bootstrap = deferredResponse(); const write = deferredResponse()
    const error = httpError(409, 'IDENTITY_VERSION_CONFLICT')
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(bootstrap.promise)
    vi.mocked(requestLogin).mockReturnValueOnce(write.promise)
    const initialization = store.initialize().catch(failure => failure)
    const first = store.login(credentials)
    const second = store.login({ username: 'other', password: 'test-only' }).catch(failure => failure)
    if (guard) store.requireIdentityRevalidation()
    bootstrap.reject(error); await flushPromises()
    expect(await initialization).toBe(error)
    expect(await second).toBeInstanceOf(IdentityTransitionInProgressError)
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
    expect(requestLogin).toHaveBeenCalledExactlyOnceWith(credentials)
    write.resolve(next); await first
    expect(store.user?.id).toBe(2); expect(store.identityReady).toBe(true)
  })

  it('两个登录共享成功 bootstrap 的已应用代次，写锁仍只放行首个意图', async () => {
    const store = useAuthStore(); const bootstrap = deferredResponse(); const write = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(bootstrap.promise)
    vi.mocked(requestLogin).mockReturnValueOnce(write.promise)
    const first = store.login(credentials)
    const second = store.login({ username: 'other', password: 'test-only' }).catch(failure => failure)
    bootstrap.resolve({ authenticated: false, user: null }); await flushPromises()
    expect(await second).toBeInstanceOf(IdentityTransitionInProgressError)
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
    expect(requestLogin).toHaveBeenCalledExactlyOnceWith(credentials)
    write.resolve(next); await first
    expect(store.user?.id).toBe(2); expect(store.identityReady).toBe(true)
  })

  it.each(['success', 'failure'] as const)('外部可信身份取代尚未完成的 bootstrap，旧%s不让登录跨身份 POST', async outcome => {
    const store = useAuthStore(); const bootstrap = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(bootstrap.promise)
    const login = store.login(credentials)
    store.applyAuthResponse(known)
    const generation = store.authenticationGeneration
    if (outcome === 'success') bootstrap.resolve({ authenticated: false, user: null })
    else bootstrap.reject(httpError(403, 'IDENTITY_CONTEXT_INVALID'))
    await expect(login).rejects.toSatisfy(isCancel)
    expect(store.authenticationGeneration).toBe(generation)
    expect(store.user?.id).toBe(1); expect(store.accountSwitch).toEqual(known.account_switch)
    expect(store.initialized).toBe(true); expect(store.identityReady).toBe(true)
    expect(requestLogin).not.toHaveBeenCalled()
  })

  it.each([false, true])('bootstrap 已应用但 login 续接前有更新的可信读取（同身份=%s），旧意图取消', async sameIdentity => {
    const store = useAuthStore(); const bootstrap = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(bootstrap.promise)
    const login = store.login(credentials)
    // initialize 的成功处理先应用身份；该后注册回调在 login 续接前模拟另一次可信读取。
    const replacement = bootstrap.promise.then(() => store.applyAuthResponse(sameIdentity ? authenticated : known))
    bootstrap.resolve(authenticated)
    await expect(login).rejects.toSatisfy(isCancel); await replacement
    expect(store.user?.id).toBe(1); expect(store.initialized).toBe(true)
    expect(requestLogin).not.toHaveBeenCalled(); expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
  })

  it('精确 bootstrap 错误交付与 login 续接之间换身份，错误不能成为新身份的写许可', async () => {
    const store = useAuthStore(); const bootstrap = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(bootstrap.promise)
    const login = store.login(credentials)
    const replacement = bootstrap.promise.catch(() => store.applyAuthResponse(known))
    bootstrap.reject(httpError(403, 'IDENTITY_CONTEXT_INVALID'))
    await expect(login).rejects.toSatisfy(isCancel); await replacement
    expect(store.user?.id).toBe(1); expect(store.accountSwitch).toEqual(known.account_switch)
    expect(store.identityReady).toBe(true); expect(requestLogin).not.toHaveBeenCalled()
  })

  it.each(['before-error', 'after-error'] as const)('待核验后较新的 bootstrap 在%s接替，旧登录不抢占其在途读取', async timing => {
    const store = useAuthStore(); const bootstrap = deferredResponse(); const replacement = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(bootstrap.promise).mockReturnValueOnce(replacement.promise)
    const login = store.login(credentials)
    let current!: Promise<number | void>
    let started: Promise<unknown> | undefined
    if (timing === 'before-error') {
      store.requireIdentityRevalidation()
      current = store.initialize()
    } else {
      // 原 initialize 的错误处理会先标待核验；这里随后发起新的明确核验。
      started = bootstrap.promise.catch(() => { current = store.initialize() })
    }
    bootstrap.reject(httpError(409, 'IDENTITY_VERSION_CONFLICT'))
    await expect(login).rejects.toSatisfy(isCancel)
    await started
    expect(requestLogin).not.toHaveBeenCalled(); expect(fetchCurrentUser).toHaveBeenCalledTimes(2)
    expect(store.checking).toBe(true); expect(store.identityReady).toBe(false)
    replacement.resolve(next); await current
    expect(store.user?.id).toBe(2); expect(store.identityReady).toBe(true)
    expect(requestLogin).not.toHaveBeenCalled()
  })

  it.each(['pending', 'settled'] as const)('bootstrap 期间另一身份写已%s，旧登录意图不排队', async state => {
    const store = useAuthStore(); const bootstrap = deferredResponse(); const write = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(bootstrap.promise)
    vi.mocked(requestLogout).mockReturnValueOnce(write.promise)
    const login = store.login(credentials).catch(failure => failure)
    const logout = store.logout()
    if (state === 'settled') { write.resolve({ authenticated: false, user: null }); await logout }
    bootstrap.reject(httpError(403, 'IDENTITY_CONTEXT_INVALID'))
    expect(await login).toBeInstanceOf(IdentityTransitionInProgressError)
    expect(requestLogin).not.toHaveBeenCalled()
    if (state === 'pending') { write.resolve({ authenticated: false, user: null }); await logout }
    expect(requestLogout).toHaveBeenCalledTimes(1); expect(store.user).toBeNull()
  })

  it('bootstrap 被非写入的其他读取代次取代时不能将静默旧失败当成登录许可', async () => {
    const store = useAuthStore(); const bootstrap = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(bootstrap.promise)
    const login = store.login(credentials)
    store.invalidatePendingAuthentication()
    bootstrap.reject(httpError(403, 'IDENTITY_CONTEXT_INVALID'))
    await expect(login).rejects.toSatisfy(isCancel)
    expect(requestLogin).not.toHaveBeenCalled(); expect(store.initialized).toBe(false)
    expect(store.identityRevalidationRequired).toBe(false)
  })

  it('恢复 POST 结果未知时保留 metadata 并封锁，不自动 /me、重试或返回', async () => {
    const store = coldStoreWithMetadata(); const user = store.user; const metadata = store.accountSwitch
    const error = new AxiosError('login response lost', 'ERR_NETWORK')
    vi.mocked(fetchCurrentUser).mockRejectedValueOnce(httpError(403, 'IDENTITY_CONTEXT_INVALID'))
    vi.mocked(requestLogin).mockRejectedValueOnce(error)
    await expect(store.login(credentials)).rejects.toBe(error)
    expect(store.user).toBe(user); expect(store.accountSwitch).toBe(metadata)
    expect(store.initialized).toBe(false); expect(store.identityReady).toBe(false)
    expect(store.identityRevalidationRequired).toBe(true); expect(store.identityTransitionPending).toBe(false)
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1); expect(requestLogin).toHaveBeenCalledTimes(1)
    expect(requestReturnAdmin).not.toHaveBeenCalled(); expect(requestLogout).not.toHaveBeenCalled()
    const unavailable = httpError(503, 'IDENTITY_SESSION_UNAVAILABLE')
    vi.mocked(fetchCurrentUser).mockRejectedValueOnce(unavailable)
    await expect(store.login(credentials)).rejects.toBe(unavailable)
    expect(fetchCurrentUser).toHaveBeenCalledTimes(2); expect(requestLogin).toHaveBeenCalledTimes(1)
    vi.mocked(fetchCurrentUser).mockResolvedValueOnce(next)
    await store.initialize()
    expect(store.user?.id).toBe(2); expect(store.identityReady).toBe(true)
    expect(requestLogin).toHaveBeenCalledTimes(1); expect(requestReturnAdmin).not.toHaveBeenCalled()
  })

  it('恢复 POST 的明确拒绝原样交付，不把登录错误再当成 bootstrap 许可重试', async () => {
    const store = coldStoreWithMetadata(); const error = httpError(403, 'IDENTITY_CONTEXT_INVALID')
    vi.mocked(fetchCurrentUser).mockRejectedValueOnce(error)
    vi.mocked(requestLogin).mockRejectedValueOnce(error)
    await expect(store.login(credentials)).rejects.toBe(error)
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1); expect(requestLogin).toHaveBeenCalledTimes(1)
    expect(store.accountSwitch).toEqual(known.account_switch)
    expect(store.identityRevalidationRequired).toBe(true); expect(store.identityReady).toBe(false)
  })
})

describe('普通ERP角色管理入口', () => {
  it('服务端确认的非 admin 超级管理员拥有管理与身份切换能力', () => {
    setActivePinia(createPinia())
    const store = useAuthStore()
    store.applyAuthResponse({ authenticated: true, account_switch: { active: false, can_return: false, identity_version: 'superuser-v1' }, user: {
      ...authenticated.user!, username: 'general_manager', is_superuser: true,
      employee: { id: 'gm', employee_code: 'GM', display_name: '总经理', status: 'ACTIVE' },
    } })
    expect(store.managementCan('access_control.manage_accounts')).toBe(true)
    expect(store.canReadAccessDirectory).toBe(true)
    expect(store.canSwitchAccount).toBe(true)
  })
  it('有效组织管理角色可读目录，但不获得账号或企微管理', () => {
    setActivePinia(createPinia())
    const store = useAuthStore()
    store.user = { ...authenticated.user!, employee: { id: 'worker', employee_code: 'WORKER', display_name: '员工', status: 'ACTIVE' },
      effective_access: { active: true, is_superuser: false, roles: [], legacy_sources: [], version: 'test',
        actions: { 'organizations.manage_organization': { scopes: ['MODULE'], sources: [{ type: 'ROLE', scope: 'MODULE' }] } } } }
    expect(store.canReadAccessDirectory).toBe(true)
    expect(store.managementCan('access_control.manage_accounts')).toBe(false)
    expect(store.managementCan('access_control.manage_wecom')).toBe(false)
    store.user.employee!.status = 'INACTIVE'
    expect(store.canReadAccessDirectory).toBe(false)
  })
})

describe('路由登录身份复用与核验', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-15T00:00:00Z'))
    vi.mocked(fetchCurrentUser).mockReset().mockResolvedValue(authenticated)
    vi.mocked(requestDevelopmentAutoLogin).mockReset().mockRejectedValue(new Error('未启用开发登录'))
  })
  afterEach(() => vi.useRealTimers())

  it('登录状态核验后，跨一天的普通导航仍复用当前身份', async () => {
    const store = useAuthStore()
    await store.ensureAuthentication()
    await store.ensureAuthentication()
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(24 * 60 * 60 * 1000)
    await store.ensureAuthentication()
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
  })

  it('登录成功后的普通导航不额外读取身份', async () => {
    const store = useAuthStore()
    store.applyAuthResponse(authenticated)
    vi.advanceTimersByTime(24 * 60 * 60 * 1000)
    await store.ensureAuthentication()
    expect(fetchCurrentUser).not.toHaveBeenCalled()
  })

  it('强制刷新及主动失效仍重新核验身份', async () => {
    const store = useAuthStore()
    await store.ensureAuthentication()
    await store.initialize(true)
    store.invalidateAuthenticationVerification()
    await store.ensureAuthentication()
    expect(fetchCurrentUser).toHaveBeenCalledTimes(3)
  })

  it('清除登录后不能复用之前的核验状态', async () => {
    const store = useAuthStore()
    await store.ensureAuthentication()
    store.clearAuthentication()
    vi.mocked(fetchCurrentUser).mockResolvedValue({ authenticated: false, user: null })
    await store.ensureAuthentication()
    expect(fetchCurrentUser).toHaveBeenCalledTimes(2)
    expect(store.isAuthenticated).toBe(false)
  })

  it('退出后公开路由的普通初始化不会再次触发开发自动登录', async () => {
    const store = useAuthStore()
    store.clearAuthentication()
    vi.mocked(requestDevelopmentAutoLogin).mockResolvedValue(authenticated)
    await store.initialize()
    expect(fetchCurrentUser).not.toHaveBeenCalled()
    expect(requestDevelopmentAutoLogin).not.toHaveBeenCalled()
  })

  it('匿名初始化不尝试自动登录，即使旧开发接口可用', async () => {
    vi.mocked(fetchCurrentUser).mockResolvedValue({ authenticated: false, user: null })
    vi.mocked(requestDevelopmentAutoLogin).mockResolvedValue(authenticated)
    const store = useAuthStore()
    await store.initialize()
    expect(store.isAuthenticated).toBe(false)
    expect(requestDevelopmentAutoLogin).not.toHaveBeenCalled()
  })

  it('待授权账号保持登录，并在强制刷新后解除等待状态', async () => {
    const store = useAuthStore()
    store.applyAuthResponse({ authenticated: true, user: { ...authenticated.user!, waiting_for_role: true } })
    expect(store.isAuthenticated).toBe(true)
    expect(store.waitingForRole).toBe(true)
    await store.initialize(true)
    expect(store.isAuthenticated).toBe(true)
    expect(store.waitingForRole).toBe(false)
  })

  it('显式核验失败保持未核验，下次导航重新校验', async () => {
    const store = useAuthStore()
    await store.ensureAuthentication()
    vi.mocked(fetchCurrentUser).mockRejectedValueOnce(new Error('连接失败'))
    await expect(store.initialize(true)).rejects.toThrow('连接失败')
    await store.ensureAuthentication()
    expect(fetchCurrentUser).toHaveBeenCalledTimes(3)
  })

  it('失效后的并发导航共享一个请求，更新权限', async () => {
    const store = useAuthStore()
    await store.ensureAuthentication()
    store.invalidateAuthenticationVerification()
    let resolveRequest!: (value: AuthResponse) => void
    vi.mocked(fetchCurrentUser).mockReturnValue(new Promise(resolve => { resolveRequest = resolve }))
    const first = store.ensureAuthentication()
    const second = store.ensureAuthentication()
    resolveRequest({ ...authenticated, user: { ...authenticated.user!, permissions: [] } })
    await Promise.all([first, second])
    expect(fetchCurrentUser).toHaveBeenCalledTimes(2)
    expect(store.hasPermission('customers.view_customeraccount')).toBe(false)
  })
})


describe('销售记录操作权限', () => {
  beforeEach(() => setActivePinia(createPinia()))
  it('全局有编辑权限仍不能编辑只有查看能力的团队记录', () => {
    const store = useAuthStore()
    store.applyAuthResponse({ authenticated: true, user: { ...authenticated.user!, sales_access_enabled: true, permissions: ['inquiries.view_inquiry', 'inquiries.change_inquiry'] } })
    const team = { allowed_permissions: ['inquiries.view_inquiry'] }
    expect(store.canFor('inquiries.view_inquiry', team)).toBe(true)
    expect(store.canFor('inquiries.change_inquiry', team)).toBe(false)
    expect(store.canFor('inquiries.change_inquiry', null)).toBe(false)
    expect(store.canFor('inquiries.change_inquiry', {})).toBe(false)
    expect(store.canFor('inquiries.change_inquiry', { allowed_permissions: ['inquiries.change_inquiry'] })).toBe(true)
  })
  it('阶段开关关闭时保留旧按钮权限判断', () => {
    const store = useAuthStore()
    store.applyAuthResponse(authenticated)
    expect(store.canFor('customers.view_customeraccount', {})).toBe(true)
    expect(store.canFor('customers.change_customeraccount', {})).toBe(false)
  })
})

describe('其他模块的操作和单条数据权限', () => {
  beforeEach(() => setActivePinia(createPinia()))
  it('启用后按独立操作判断，编辑不自动允许完成任务', () => {
    const store = useAuthStore()
    store.applyAuthResponse({ authenticated: true, user: { ...authenticated.user!, module_access_enabled: true, permissions: ['workflow.change_businesstask'] } })
    expect(store.moduleCan('access_control.complete_businesstask', 'workflow.change_businesstask')).toBe(false)
    expect(store.moduleCan('workflow.change_businesstask')).toBe(true)
  })
  it('团队查看不能借全局操作列表显示该条记录的编辑按钮', () => {
    const store = useAuthStore()
    store.applyAuthResponse({ authenticated: true, user: { ...authenticated.user!, module_access_enabled: true, permissions: ['workflow.view_businesstask', 'workflow.change_businesstask'] } })
    const record = { allowed_permissions: ['workflow.view_businesstask'] }
    expect(store.moduleCan('workflow.change_businesstask', undefined, record)).toBe(false)
    expect(store.moduleCan('workflow.view_businesstask', undefined, record)).toBe(true)
    expect(store.moduleCan('workflow.change_businesstask', undefined, null)).toBe(false)
  })
  it('未启用时保留原操作权限', () => {
    const store = useAuthStore()
    store.applyAuthResponse({ authenticated: true, user: { ...authenticated.user!, permissions: ['workflow.change_businesstask'] } })
    expect(store.moduleCan('access_control.complete_businesstask', 'workflow.change_businesstask', {})).toBe(true)
  })
})
