import { AxiosError } from 'axios'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { useAuthStore } from '@/stores/auth'
import { fetchCurrentUser, login as requestLogin } from './auth'
import { installWeComRoleGuard } from './wecomSession'
import type { AuthResponse } from '@/types/auth'

vi.mock('./auth', () => ({ fetchCurrentUser: vi.fn(), login: vi.fn(), logout: vi.fn() }))
let dispose: (() => void) | undefined
const originalAdapter = apiClient.defaults.adapter
beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })
afterEach(() => { dispose?.(); apiClient.defaults.adapter = originalAdapter })
async function setup() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', name: 'home', component: {} }, { path: '/auth/waiting-role', name: 'waiting-role', component: {} }, { path: '/login', name: 'login', component: {} }] })
  await router.push('/')
  const auth = useAuthStore()
  auth.applyAuthResponse({ authenticated: true, user: { id: 1, username: 'wecom1', display_name: '测试员工', is_superuser: false, employee: null, permissions: [], data_scope: 'NONE' } })
  dispose = installWeComRoleGuard(router, auth)
  apiClient.defaults.adapter = async config => { throw new AxiosError('denied', undefined, config, undefined, { status: 403, data: { error: { code: 'WECOM_ROLE_REQUIRED' } }, headers: {}, statusText: 'Forbidden', config }) }
  return { router, auth }
}

function deferredResponse() {
  let resolve!: (response: AuthResponse) => void
  let reject!: (error: Error) => void
  const promise = new Promise<AuthResponse>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

describe('企业微信业务门禁响应', () => {
  it('新身份的403独立刷新，旧刷新收尾不清除新身份的并发去重', async () => {
    const { router, auth } = await setup()
    const initialize = vi.spyOn(auth, 'initialize')
    const old = deferredResponse()
    const current = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const first = apiClient.get('/api/v1/customers/').catch(error => error)
    await flushPromises()
    auth.applyAuthResponse({ authenticated: true, user: { ...auth.user!, id: 2, waiting_for_role: false } })
    const nextUser = { ...auth.user!, waiting_for_role: true }
    const second = apiClient.get('/api/v1/products/').catch(error => error)
    await flushPromises()
    const callsBeforeOldRequestSettles = vi.mocked(fetchCurrentUser).mock.calls.length
    const waitingBeforeOldRequestSettles = auth.waitingForRole
    old.resolve({ authenticated: true, user: { ...nextUser, id: 1 } })
    await first
    const third = apiClient.get('/api/v1/orders/').catch(error => error)
    await flushPromises()
    const initializeCalls = initialize.mock.calls.length
    current.resolve({ authenticated: true, user: nextUser })
    await Promise.all([second, third])
    expect(callsBeforeOldRequestSettles).toBe(2)
    expect(waitingBeforeOldRequestSettles).toBe(true)
    expect(initializeCalls).toBe(2)
    expect(auth.user?.id).toBe(2)
    expect(router.currentRoute.value.name).toBe('waiting-role')
  })

  it.each([
    { waiting: false, failed: false, nextId: 2 }, { waiting: true, failed: false, nextId: 2 },
    { waiting: false, failed: true, nextId: 2 }, { waiting: true, failed: true, nextId: 2 },
    { waiting: true, failed: false, nextId: 1 },
  ])('旧角色刷新结果 $failed 不导航新身份（waiting=$waiting，账号=$nextId）', async ({ waiting, failed, nextId }) => {
    const { router, auth } = await setup()
    const old = deferredResponse()
    vi.mocked(fetchCurrentUser).mockReturnValueOnce(old.promise)
    const first = apiClient.get('/api/v1/customers/').catch(error => error)
    await flushPromises()
    auth.applyAuthResponse({ authenticated: true, user: { ...auth.user!, id: nextId, waiting_for_role: waiting } })
    const checkedAt = auth.authenticationCheckedAt
    if (failed) old.reject(new Error('旧身份刷新失败'))
    else old.resolve({ authenticated: true, user: { ...auth.user!, id: 1, waiting_for_role: true } })
    await first
    expect(auth.user?.id).toBe(nextId)
    expect(auth.waitingForRole).toBe(waiting)
    expect(auth.authenticationCheckedAt).toBe(checkedAt)
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('角色刷新等待的旧登录失败，不使新身份验证时间失效或触发导航', async () => {
    const { router, auth } = await setup()
    const oldLogin = deferredResponse()
    vi.mocked(requestLogin).mockReturnValueOnce(oldLogin.promise)
    const login = auth.login({ username: 'old', password: 'test-only' }).catch(error => error)
    const request = apiClient.get('/api/v1/customers/').catch(error => error)
    await flushPromises()
    auth.applyAuthResponse({ authenticated: true, user: { ...auth.user!, id: 2, waiting_for_role: true } })
    const checkedAt = auth.authenticationCheckedAt
    oldLogin.reject(new Error('旧登录失败'))
    await Promise.all([login, request])
    expect(auth.user?.id).toBe(2)
    expect(auth.authenticationCheckedAt).toBe(checkedAt)
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('业务接口明确401清除身份并保留登录返回地址', async () => {
    const { router, auth } = await setup()
    apiClient.defaults.adapter = async config => { throw new AxiosError('expired', undefined, config, undefined, { status: 401, data: { error: { code: 'AUTHENTICATION_REQUIRED' } }, headers: {}, statusText: 'Unauthorized', config }) }
    await expect(apiClient.get('/api/v1/customers/')).rejects.toBeInstanceOf(AxiosError)
    expect(auth.isAuthenticated).toBe(false)
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/')
    expect(fetchCurrentUser).not.toHaveBeenCalled()
  })

  it.each([0, 500])('业务请求网络或服务错误%s不清除身份', async status => {
    const { router, auth } = await setup()
    apiClient.defaults.adapter = async config => { throw new AxiosError('unavailable', undefined, config, undefined,
      status ? { status, data: {}, headers: {}, statusText: '', config } : undefined) }
    await expect(apiClient.get('/api/v1/customers/')).rejects.toBeInstanceOf(AxiosError)
    expect(auth.isAuthenticated).toBe(true)
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('登录接口401不被业务失效处理改写', async () => {
    const { router, auth } = await setup()
    apiClient.defaults.adapter = async config => { throw new AxiosError('invalid credentials', undefined, config, undefined, { status: 401, data: {}, headers: {}, statusText: 'Unauthorized', config }) }
    await expect(apiClient.post('/api/auth/login/', {})).rejects.toBeInstanceOf(AxiosError)
    expect(auth.isAuthenticated).toBe(true)
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('旧身份发出的请求迟到401不能清除后来登录的账号', async () => {
    const { router, auth } = await setup()
    let rejectOld!: () => void
    let started!: () => void
    const requestStarted = new Promise<void>(resolve => { started = resolve })
    apiClient.defaults.adapter = config => new Promise((_resolve, reject) => {
      rejectOld = () => reject(new AxiosError('old session expired', undefined, config, undefined, { status: 401, data: { error: { code: 'AUTHENTICATION_REQUIRED' } }, headers: {}, statusText: 'Unauthorized', config }))
      started()
    })
    const request = apiClient.get('/api/v1/customers/')
    await requestStarted
    auth.applyAuthResponse({ authenticated: true, user: { ...auth.user!, id: 2, username: 'new-account' } })
    rejectOld()
    await expect(request).rejects.toBeInstanceOf(AxiosError)
    expect(auth.user?.id).toBe(2)
    expect(router.currentRoute.value.name).toBe('home')
  })

  it('业务403并发响应只刷新一次会话，保留账号并进入等待页', async () => {
    const { router, auth } = await setup()
    vi.mocked(fetchCurrentUser).mockResolvedValue({ authenticated: true, user: { ...auth.user!, waiting_for_role: true } })
    await Promise.allSettled([apiClient.get('/api/v1/customers/'), apiClient.get('/api/v1/products/')])
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
    expect(auth.isAuthenticated).toBe(true)
    expect(router.currentRoute.value.name).toBe('waiting-role')
  })
  it('会话刷新网络失败仍保留身份在等待页重试', async () => {
    const { router, auth } = await setup()
    vi.mocked(fetchCurrentUser).mockRejectedValue(new Error('offline'))
    await expect(apiClient.get('/api/v1/customers/')).rejects.toBeInstanceOf(AxiosError)
    expect(auth.isAuthenticated).toBe(true)
    expect(auth.waitingForRole).toBe(true)
    expect(router.currentRoute.value.name).toBe('waiting-role')
  })
  it('角色刷新收到当前会话401时清除身份并进入登录页', async () => {
    const { router, auth } = await setup()
    vi.mocked(fetchCurrentUser).mockRejectedValueOnce(new AxiosError('expired', undefined, undefined, undefined,
      { status: 401, data: {}, headers: {}, statusText: 'Unauthorized', config: {} as never }))
    await expect(apiClient.get('/api/v1/customers/')).rejects.toBeInstanceOf(AxiosError)
    expect(auth.isAuthenticated).toBe(false)
    expect(router.currentRoute.value.name).toBe('login')
  })
  it('认证接口自身拒绝不会递归触发刷新', async () => {
    const { router } = await setup()
    await expect(apiClient.get('/api/auth/me/')).rejects.toBeInstanceOf(AxiosError)
    expect(fetchCurrentUser).not.toHaveBeenCalled()
    expect(router.currentRoute.value.name).toBe('home')
  })
  it('普通业务权限403不改变旧账号或导航', async () => {
    const { router, auth } = await setup()
    apiClient.defaults.adapter = async config => { throw new AxiosError('denied', undefined, config, undefined, { status: 403, data: { error: { code: 'PERMISSION_DENIED' } }, headers: {}, statusText: 'Forbidden', config }) }
    await expect(apiClient.get('/api/v1/customers/')).rejects.toBeInstanceOf(AxiosError)
    expect(fetchCurrentUser).not.toHaveBeenCalled()
    expect(auth.waitingForRole).toBe(false)
    expect(router.currentRoute.value.name).toBe('home')
  })
  it('管理员已补充角色时以最新会话为准，不重新进入等待', async () => {
    const { router, auth } = await setup()
    vi.mocked(fetchCurrentUser).mockResolvedValue({ authenticated: true, user: { ...auth.user!, waiting_for_role: false } })
    await expect(apiClient.get('/api/v1/customers/')).rejects.toBeInstanceOf(AxiosError)
    expect(auth.waitingForRole).toBe(false)
    expect(router.currentRoute.value.name).toBe('home')
  })
})
