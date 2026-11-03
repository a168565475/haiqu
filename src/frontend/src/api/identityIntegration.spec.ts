import { AxiosError, isCancel, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { shallowRef } from 'vue'
import type { Router } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import type { AuthResponse } from '@/types/auth'
import { apiClient } from './request'
import { installIdentityRequestGuard } from './identityGuard'
import { installWeComRoleGuard } from './wecomSession'

// 真实 Axios + 实际 API/store/guard 组合，网络层为内存 adapter，不是真实 Session 或安全验收。
const employeeId = '40b27c87-8111-4ef6-96a6-b2661d3d68ef'
const originalAdapter = apiClient.defaults.adapter
const disposers: Array<() => void> = []
function identity(id = 1, version = 'v1'): AuthResponse {
  return { authenticated: true, user: { id, username: id === 1 ? 'admin' : `employee${id}`,
    display_name: '组合测试', is_superuser: id === 1, employee: null, permissions: [], data_scope: 'ALL' },
  account_switch: { active: id !== 1, can_return: id !== 1, identity_version: version } }
}
function response(config: InternalAxiosRequestConfig, data: unknown): AxiosResponse {
  return { config, data, status: 200, statusText: 'OK', headers: {} }
}
function httpError(config: InternalAxiosRequestConfig, status: number, code: string) {
  return new AxiosError('组合测试失败', undefined, config, undefined,
    { ...response(config, { error: { code }, private: '旧身份内容' }), status })
}
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
function pendingAdapter() {
  const started = deferred<InternalAxiosRequestConfig>(); const result = deferred<AxiosResponse>()
  const adapter: AxiosAdapter = config => { started.resolve(config); return result.promise }
  return { started, result, adapter }
}
function setup() {
  const auth = useAuthStore(); auth.applyAuthResponse(identity())
  const conflict = vi.fn(() => auth.requireIdentityRevalidation())
  disposers.push(installIdentityRequestGuard(apiClient, () => ({
    generation: auth.identityRequestGeneration, version: auth.identityVersion, blocked: !auth.identityReady,
  }), conflict))
  const replace = vi.fn(async () => undefined)
  const router = { currentRoute: shallowRef({ name: 'customers', fullPath: '/customers' }), replace } as unknown as Router
  disposers.push(installWeComRoleGuard(router, auth))
  return { auth, conflict, replace }
}
beforeEach(() => { setActivePinia(createPinia()) })
afterEach(() => { disposers.splice(0).reverse().forEach(dispose => dispose()); apiClient.defaults.adapter = originalAdapter })

describe('身份基础层组合边界（无真实写入）', () => {
  it('同上下文/me刷新不作业务响应屏障，业务结果仍可被当前页面接受', async () => {
    const { auth } = setup(); const old = pendingAdapter()
    apiClient.defaults.adapter = config => config.url === '/api/auth/me/'
      ? Promise.resolve(response(config, identity())) : old.adapter(config)
    const request = apiClient.get('/api/v1/customers/'); const config = await old.started.promise
    const generation = auth.identityRequestGeneration
    await auth.initialize(true); expect(auth.identityRequestGeneration).toBe(generation)
    old.result.resolve(response(config, { results: ['当前上下文数据'] }))
    expect((await request).data).toEqual({ results: ['当前上下文数据'] })
  })
  it.each([[401, 'UNAUTHENTICATED'], [403, 'WECOM_ROLE_REQUIRED']] as const)('同身份/me晚于请求发出时优先于其%s副作用，但错误本身不伪装成取消', async (status, code) => {
    const { auth, replace } = setup(); const old = pendingAdapter()
    const adapter = vi.fn((config: InternalAxiosRequestConfig) => config.url === '/api/auth/me/'
      ? Promise.resolve(response(config, identity())) : old.adapter(config))
    apiClient.defaults.adapter = adapter
    const request = apiClient.get('/api/v1/customers/'); const config = await old.started.promise
    await auth.initialize(true)
    const error = httpError(config, status, code); old.result.reject(error)
    await expect(request).rejects.toBe(error)
    expect(auth.user?.id).toBe(1); expect(auth.waitingForRole).toBe(false)
    expect(adapter).toHaveBeenCalledTimes(2); expect(replace).not.toHaveBeenCalled()
  })
  it.each([[401, 'UNAUTHENTICATED'], [403, 'WECOM_ROLE_REQUIRED']] as const)('旧%s被先隔离，不清新身份、不刷新/me、不导航', async (status, code) => {
    const { auth, replace } = setup(); const old = pendingAdapter()
    const adapter = vi.fn(old.adapter); apiClient.defaults.adapter = adapter
    const request = apiClient.get('/api/v1/customers/'); const config = await old.started.promise
    auth.applyAuthResponse(identity(2, 'new-v2'))
    old.result.reject(httpError(config, status, code))
    await expect(request).rejects.toSatisfy(isCancel)
    expect(auth.user?.id).toBe(2); expect(auth.identityVersion).toBe('new-v2')
    expect(auth.waitingForRole).toBe(false); expect(replace).not.toHaveBeenCalled()
    expect(adapter).toHaveBeenCalledTimes(1)
  })
  it('当前401仍按既有企微处理清身份并导航登录', async () => {
    const { auth, replace } = setup()
    apiClient.defaults.adapter = config => Promise.reject(httpError(config, 401, 'UNAUTHENTICATED'))
    await expect(apiClient.get('/api/v1/customers/')).rejects.toBeInstanceOf(AxiosError)
    expect(auth.user).toBeNull(); expect(auth.identityVersion).toBeNull()
    expect(replace).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/customers' } })
  })
  it.each([true, false])('切换态业务401不能据此丢管理员返回凭据，/me最终确认can_return=%s，不自动返回', async retainsReturn => {
    const { auth } = setup(); auth.applyAuthResponse(identity(2, 'employee-v2'))
    const anonymous: AuthResponse = { authenticated: false, user: null,
      account_switch: { active: true, can_return: retainsReturn, identity_version: 'anonymous-v3' } }
    const adapter = vi.fn((config: InternalAxiosRequestConfig) => config.url === '/api/auth/me/'
      ? Promise.resolve(response(config, anonymous)) : Promise.reject(httpError(config, 401, 'NOT_AUTHENTICATED')))
    apiClient.defaults.adapter = adapter
    await expect(apiClient.get('/api/v1/customers/')).rejects.toSatisfy(isCancel)
    expect(auth.user).toBeNull(); expect(auth.accountSwitch?.can_return).toBe(true)
    expect(auth.identityVersion).toBe('employee-v2'); expect(auth.identityRevalidationRequired).toBe(true)
    expect(auth.canReturnAdmin).toBe(false); expect(adapter).toHaveBeenCalledTimes(1)
    await auth.initialize()
    expect(auth.user).toBeNull(); expect(auth.identityReady).toBe(true)
    expect(auth.canReturnAdmin).toBe(retainsReturn)
    expect(auth.identityVersion).toBe('anonymous-v3')
    expect(adapter.mock.calls.map(([config]) => config.url)).toEqual(['/api/v1/customers/', '/api/auth/me/'])
  })
  it('当前企微待授权错误仍单次刷新/me，且受限身份变更进入业务隔离代次', async () => {
    const { auth, replace } = setup(); const generation = auth.identityRequestGeneration
    const next = identity(); next.user!.waiting_for_role = true
    const adapter = vi.fn((config: InternalAxiosRequestConfig) => config.url === '/api/auth/me/'
      ? Promise.resolve(response(config, next)) : Promise.reject(httpError(config, 403, 'WECOM_ROLE_REQUIRED')))
    apiClient.defaults.adapter = adapter
    await expect(apiClient.get('/api/v1/customers/')).rejects.toBeInstanceOf(AxiosError)
    expect(auth.waitingForRole).toBe(true); expect(auth.identityRequestGeneration).toBeGreaterThan(generation)
    expect(adapter.mock.calls.filter(([config]) => config.url === '/api/auth/me/')).toHaveLength(1)
    expect(replace).toHaveBeenCalledWith({ name: 'waiting-role' })
  })
  it('转换结果未知封锁业务，显式/me核验后才恢复；不重放POST', async () => {
    const { auth } = setup(); const adapter = vi.fn((config: InternalAxiosRequestConfig) => {
      if (config.url === '/api/auth/switch/') return Promise.reject(new AxiosError('响应丢失', 'ERR_NETWORK', config))
      return Promise.resolve(response(config, config.url === '/api/auth/me/' ? identity(2, 'server-v2') : { ok: true }))
    })
    apiClient.defaults.adapter = adapter
    await expect(auth.switchAccount(employeeId)).rejects.toBeInstanceOf(AxiosError)
    expect(auth.identityReady).toBe(false); expect(auth.user?.id).toBe(1); expect(auth.identityVersion).toBe('v1')
    await expect(apiClient.post('/api/v1/customers/', { name: '不可发送' })).rejects.toSatisfy(isCancel)
    expect(adapter).toHaveBeenCalledTimes(1)
    await auth.initialize(); expect(auth.user?.id).toBe(2); expect(auth.identityReady).toBe(true)
    await apiClient.post('/api/v1/customers/', { name: '重新明确发起' })
    expect(adapter.mock.calls.map(([config]) => config.url)).toEqual([
      '/api/auth/switch/', '/api/auth/me/', '/api/v1/customers/',
    ])
    expect(adapter.mock.calls[2]![0].headers.get('X-Identity-Version')).toBe('server-v2')
  })
  it.each(['me', 'navigation'] as const)('企微403已进入下游拦截器并等待%s时换身份，最终错误必须净化', async stage => {
    const { auth, replace } = setup(); const me = pendingAdapter()
    const navigation = deferred<undefined>(); const navigating = deferred<undefined>()
    replace.mockImplementationOnce(() => { navigating.resolve(undefined); return navigation.promise })
    const waiting = identity(); waiting.user!.waiting_for_role = true
    apiClient.defaults.adapter = config => config.url === '/api/auth/me/'
      ? stage === 'me' ? me.adapter(config) : Promise.resolve(response(config, waiting))
      : Promise.reject(httpError(config, 403, 'WECOM_ROLE_REQUIRED'))
    const request = apiClient.get('/api/v1/customers/')
    const meConfig = stage === 'me' ? await me.started.promise : undefined
    if (stage === 'navigation') await navigating.promise
    auth.applyAuthResponse(identity(2, 'new-v2'))
    if (meConfig) me.result.resolve(response(meConfig, waiting))
    navigation.resolve(undefined)
    const error = await request.catch(error => error)
    expect(isCancel(error)).toBe(true)
    expect(error.config).toBeUndefined(); expect(error.response).toBeUndefined(); expect(error.request).toBeUndefined(); expect(error.cause).toBeUndefined()
    expect(auth.user?.id).toBe(2); expect(auth.identityVersion).toBe('new-v2'); expect(auth.waitingForRole).toBe(false)
    if (stage === 'me') expect(replace).not.toHaveBeenCalled()
  })
  it('401已清旧身份但导航仍等待时出现新身份，不交付旧401正文', async () => {
    const { auth, replace } = setup(); const navigation = deferred<undefined>(); const navigating = deferred<undefined>()
    replace.mockImplementationOnce(() => { navigating.resolve(undefined); return navigation.promise })
    apiClient.defaults.adapter = config => Promise.reject(httpError(config, 401, 'UNAUTHENTICATED'))
    const request = apiClient.get('/api/v1/customers/'); await navigating.promise
    auth.applyAuthResponse(identity(2, 'new-v2')); navigation.resolve(undefined)
    const error = await request.catch(error => error)
    expect(isCancel(error)).toBe(true); expect(error.config).toBeUndefined(); expect(error.response).toBeUndefined()
    expect(auth.user?.id).toBe(2); expect(auth.identityVersion).toBe('new-v2')
  })
  it('身份版本冲突只标待核验，不丢已知身份或自动重试、导航', async () => {
    const { auth, conflict, replace } = setup()
    const adapter = vi.fn((config: InternalAxiosRequestConfig) => Promise.reject(httpError(config, 409, 'IDENTITY_VERSION_CONFLICT')))
    apiClient.defaults.adapter = adapter
    await expect(apiClient.post('/api/v1/customers/', {})).rejects.toBeInstanceOf(AxiosError)
    expect(conflict).toHaveBeenCalledTimes(1); expect(auth.identityRevalidationRequired).toBe(true)
    expect(auth.user?.id).toBe(1); expect(auth.identityVersion).toBe('v1')
    await expect(apiClient.get('/api/v1/customers/')).rejects.toSatisfy(isCancel)
    expect(adapter).toHaveBeenCalledTimes(1); expect(replace).not.toHaveBeenCalled()
  })
  it('迟到转换成功也不能覆盖外部已核验身份，不能据前端取消推断后端回滚', async () => {
    const { auth } = setup(); const old = pendingAdapter(); apiClient.defaults.adapter = old.adapter
    const write = auth.switchAccount(employeeId); const config = await old.started.promise
    expect(config.headers.get('X-Identity-Version')).toBe('v1')
    auth.applyAuthResponse(identity(3, 'external-v3'))
    expect(auth.identityTransitionPending).toBe(true); expect(auth.identityReady).toBe(false)
    await expect(apiClient.post('/api/v1/customers/', {})).rejects.toSatisfy(isCancel)
    old.result.resolve(response(config, identity(2, 'old-v2')))
    await expect(write).rejects.toSatisfy(isCancel)
    expect(auth.user?.id).toBe(3); expect(auth.identityVersion).toBe('external-v3')
    expect(auth.identityReady).toBe(true)
  })
})
