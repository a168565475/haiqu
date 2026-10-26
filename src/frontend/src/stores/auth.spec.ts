import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchCurrentUser, login as requestLogin, logout as requestLogout, requestDevelopmentAutoLogin } from '@/api/auth'
import { useAuthStore } from './auth'
import type { AuthResponse } from '@/types/auth'

vi.mock('@/api/auth', () => ({
  fetchCurrentUser: vi.fn(), login: vi.fn(), logout: vi.fn(), requestDevelopmentAutoLogin: vi.fn(),
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

  it('退出失败保留身份，但旧读取不能重新确认验证时间', async () => {
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
    expect(store.authenticationCheckedAt).toBe(0)
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
    const navigation = store.ensureFreshAuthentication().then(
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
    expect(store.authenticationCheckedAt).toBe(0)
  })
})

describe('普通ERP角色管理入口', () => {
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

describe('路由登录状态刷新', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-15T00:00:00Z'))
    vi.mocked(fetchCurrentUser).mockReset().mockResolvedValue(authenticated)
    vi.mocked(requestDevelopmentAutoLogin).mockReset().mockRejectedValue(new Error('未启用开发登录'))
  })
  afterEach(() => vi.useRealTimers())

  it('短时间连续导航复用已验证状态，30秒后重新确认', async () => {
    const store = useAuthStore()
    await store.ensureFreshAuthentication()
    await store.ensureFreshAuthentication()
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(30000)
    await store.ensureFreshAuthentication()
    expect(fetchCurrentUser).toHaveBeenCalledTimes(2)
  })

  it('强制刷新及主动失效绕过有效期', async () => {
    const store = useAuthStore()
    await store.ensureFreshAuthentication()
    await store.initialize(true)
    store.invalidateAuthenticationCheck()
    await store.ensureFreshAuthentication()
    expect(fetchCurrentUser).toHaveBeenCalledTimes(3)
  })

  it('清除登录后不能复用之前的验证时间', async () => {
    const store = useAuthStore()
    await store.ensureFreshAuthentication()
    store.clearAuthentication()
    vi.mocked(fetchCurrentUser).mockResolvedValue({ authenticated: false, user: null })
    await store.ensureFreshAuthentication()
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

  it('刷新失败不续期，下次导航重新校验', async () => {
    const store = useAuthStore()
    await store.ensureFreshAuthentication()
    vi.mocked(fetchCurrentUser).mockRejectedValueOnce(new Error('连接失败'))
    await expect(store.initialize(true)).rejects.toThrow('连接失败')
    await store.ensureFreshAuthentication()
    expect(fetchCurrentUser).toHaveBeenCalledTimes(3)
  })

  it('失效后的并发导航共享一个请求，更新权限', async () => {
    const store = useAuthStore()
    await store.ensureFreshAuthentication()
    store.invalidateAuthenticationCheck()
    let resolveRequest!: (value: AuthResponse) => void
    vi.mocked(fetchCurrentUser).mockReturnValue(new Promise(resolve => { resolveRequest = resolve }))
    const first = store.ensureFreshAuthentication()
    const second = store.ensureFreshAuthentication()
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
