import { AxiosError, isCancel } from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/auth'
import type { AuthResponse } from '@/types/auth'
import { IdentityNotReadyError, IdentityTransitionInProgressError, useAuthStore } from './auth'

vi.mock('@/api/auth', () => ({
  fetchCurrentUser: vi.fn(), login: vi.fn(), logout: vi.fn(),
  fetchSwitchTargets: vi.fn(), switchAccount: vi.fn(), returnAdmin: vi.fn(),
}))
const employeeId = 'afc1c3f1-7411-411c-8039-2b7063c663ab'
const anonymous: AuthResponse = { authenticated: false, user: null }
function identity(id = 1, version = 'opaque:root', active = false): AuthResponse {
  return { authenticated: true, user: {
    id, username: id === 1 ? 'admin' : `employee${id}`, display_name: '单元测试身份',
    is_superuser: id === 1, employee: null, permissions: ['b', 'a'], data_scope: 'ALL',
  }, account_switch: { active, can_return: active, identity_version: version } }
}
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
function httpError(status: number, code = 'VALIDATION_ERROR') {
  return new AxiosError('测试失败', undefined, undefined, undefined, {
    status, statusText: '', data: { error: { code } }, headers: {}, config: {} as never,
  })
}
beforeEach(() => { vi.resetAllMocks(); setActivePinia(createPinia()) })

describe('身份转换编排（Mock 单元测试，非真实切换验收）', () => {
  it('同身份同版本刷新只变认证读取代次，不改变业务或页面身份代次', async () => {
    const store = useAuthStore(); store.applyAuthResponse(identity())
    const before = [store.identityGeneration, store.identityRequestGeneration]
    const authenticationGeneration = store.authenticationGeneration
    const same = identity(); same.user!.permissions.reverse(); same.user!.display_name = '仅显示名更新'
    vi.mocked(api.fetchCurrentUser).mockResolvedValueOnce(same)
    await store.initialize(true)
    expect([store.identityGeneration, store.identityRequestGeneration]).toEqual(before)
    expect(store.authenticationGeneration).toBeGreaterThan(authenticationGeneration)
    expect(store.user?.display_name).toBe('仅显示名更新')
  })
  it('权限、员工状态或版本真实变化都会改变页面身份代次', () => {
    const store = useAuthStore(); store.applyAuthResponse(identity(2, 'v1', true))
    let generation = store.identityGeneration
    const permissionChange = identity(2, 'v1', true); permissionChange.user!.permissions = []
    store.applyAuthResponse(permissionChange); expect(store.identityGeneration).toBe(++generation)
    const employeeChange = { ...permissionChange, user: { ...permissionChange.user!,
      employee: { id: employeeId, employee_code: 'E2', display_name: '员工', status: 'INACTIVE' } } }
    store.applyAuthResponse(employeeChange); expect(store.identityGeneration).toBe(++generation)
    store.applyAuthResponse({ ...employeeChange, account_switch: { ...employeeChange.account_switch!, identity_version: 'v2' } })
    expect(store.identityGeneration).toBe(++generation)
  })
  it('成功切换、同员工重切、返回均更新版本；返回后active=false仍保留版本', async () => {
    const store = useAuthStore(); store.applyAuthResponse(identity())
    vi.mocked(api.switchAccount).mockResolvedValueOnce(identity(2, 'v2', true)).mockResolvedValueOnce(identity(2, 'v3', true))
    vi.mocked(api.returnAdmin).mockResolvedValueOnce(identity(1, 'v4', false))
    const first = store.identityGeneration
    await store.switchAccount(employeeId); expect(store.identityVersion).toBe('v2')
    await store.switchAccount(employeeId); expect(store.identityGeneration).toBe(first + 2)
    expect(store.identityVersion).toBe('v3')
    await store.returnAdmin(); expect(store.user?.username).toBe('admin')
    expect(store.identityVersion).toBe('v4'); expect(store.accountSwitch?.active).toBe(false)
    expect(store.canReturnAdmin).toBe(false); expect(store.canSwitchAccount).toBe(true)
    expect(api.switchAccount).toHaveBeenCalledTimes(2); expect(api.returnAdmin).toHaveBeenCalledTimes(1)
  })
  it('匿名但有返回能力不丢状态，绝不自动恢复管理员', async () => {
    const store = useAuthStore()
    store.applyAuthResponse({ ...anonymous, account_switch: { active: true, can_return: true, identity_version: 'anon-flow' } })
    expect(store.user).toBeNull(); expect(store.canReturnAdmin).toBe(true)
    expect(store.identityVersion).toBe('anon-flow'); expect(api.returnAdmin).not.toHaveBeenCalled()
    vi.mocked(api.returnAdmin).mockResolvedValueOnce(identity(1, 'returned'))
    await store.returnAdmin(); expect(store.identityVersion).toBe('returned')
  })
  it.each(['switch', 'return', 'login', 'logout'] as const)('切换进行中拒绝并发%s，不排队执行', async action => {
    const store = useAuthStore(); store.applyAuthResponse(identity(2, 'v1', true))
    const write = deferred<AuthResponse>(); vi.mocked(api.switchAccount).mockReturnValueOnce(write.promise)
    const first = store.switchAccount(employeeId)
    const second = action === 'switch' ? store.switchAccount(employeeId) : action === 'return' ? store.returnAdmin()
      : action === 'login' ? store.login({ username: 'x', password: 'test-only' }) : store.logout()
    await expect(second).rejects.toBeInstanceOf(IdentityTransitionInProgressError)
    expect(store.identityTransitionPending).toBe(true); expect(store.identityReady).toBe(false)
    write.resolve(identity(3, 'v2', true)); await first
    expect(api.switchAccount).toHaveBeenCalledTimes(1)
    expect(api.returnAdmin).not.toHaveBeenCalled(); expect(api.login).not.toHaveBeenCalled(); expect(api.logout).not.toHaveBeenCalled()
    expect(store.identityReady).toBe(true)
  })
  it('外部apply可使导航不等待旧写，但不会提前释放真实写锁', async () => {
    const store = useAuthStore(); store.applyAuthResponse(identity())
    const old = deferred<AuthResponse>(); vi.mocked(api.switchAccount).mockReturnValueOnce(old.promise)
    const write = store.switchAccount(employeeId)
    store.applyAuthResponse(identity(3, 'external', true))
    await store.ensureAuthentication()
    await expect(store.logout()).rejects.toBeInstanceOf(IdentityTransitionInProgressError)
    old.resolve(identity(2, 'old', true)); await write
    expect(store.identityVersion).toBe('external'); expect(store.user?.id).toBe(3)
  })
  it.each(['success', 'network'] as const)('同签名外部/me接替读取后，尚未settle写的%s仍按请求上下文归属处理', async outcome => {
    const store = useAuthStore(); store.applyAuthResponse(identity())
    const old = deferred<AuthResponse>(); vi.mocked(api.switchAccount).mockReturnValueOnce(old.promise)
    const write = store.switchAccount(employeeId)
    store.applyAuthResponse(identity())
    expect(store.identityTransitionPending).toBe(true); expect(store.identityReady).toBe(false)
    await store.ensureAuthentication(); expect(api.fetchCurrentUser).not.toHaveBeenCalled()
    if (outcome === 'success') {
      old.resolve(identity(2, 'committed-v2', true)); await write
      expect(store.user?.id).toBe(2); expect(store.identityVersion).toBe('committed-v2'); expect(store.identityReady).toBe(true)
    } else {
      const error = new Error('响应丢失'); old.reject(error); await expect(write).rejects.toBe(error)
      expect(store.identityVersion).toBe('opaque:root'); expect(store.identityRevalidationRequired).toBe(true)
    }
  })
  it.each(['success', '401', 'network'] as const)('旧/me的%s晚于转换不能污染当前身份或返回能力', async outcome => {
    const store = useAuthStore(); store.applyAuthResponse(identity())
    const old = deferred<AuthResponse>(); vi.mocked(api.fetchCurrentUser).mockReturnValueOnce(old.promise)
    const refresh = store.initialize(true)
    vi.mocked(api.switchAccount).mockResolvedValueOnce(identity(2, 'new', true))
    await store.switchAccount(employeeId)
    if (outcome === 'success') old.resolve(anonymous)
    else old.reject(outcome === '401' ? httpError(401) : new Error('旧连接断开'))
    await expect(refresh).resolves.toBeUndefined()
    expect(store.user?.id).toBe(2); expect(store.identityVersion).toBe('new'); expect(store.canReturnAdmin).toBe(true)
  })
  it('导航在转换中等待唯一写入而不额外发/me', async () => {
    const store = useAuthStore(); store.applyAuthResponse(identity())
    const write = deferred<AuthResponse>(); vi.mocked(api.switchAccount).mockReturnValueOnce(write.promise)
    const transition = store.switchAccount(employeeId); const navigation = store.ensureAuthentication()
    expect(api.fetchCurrentUser).not.toHaveBeenCalled()
    write.resolve(identity(2, 'next', true)); await Promise.all([transition, navigation])
    expect(store.identityReady).toBe(true); expect(api.fetchCurrentUser).not.toHaveBeenCalled()
  })
  it.each([400, 403, 404])('明确%s失败保留旧身份和页面代次，但旧请求代次已失效', async status => {
    const store = useAuthStore(); store.applyAuthResponse(identity())
    const pageGeneration = store.identityGeneration; const requestGeneration = store.identityRequestGeneration
    const error = httpError(status); vi.mocked(api.switchAccount).mockRejectedValueOnce(error)
    await expect(store.switchAccount(employeeId)).rejects.toBe(error)
    expect(store.user?.id).toBe(1); expect(store.identityVersion).toBe('opaque:root')
    expect(store.identityGeneration).toBe(pageGeneration)
    expect(store.identityRequestGeneration).toBeGreaterThan(requestGeneration)
    expect(store.identityReady).toBe(true); expect(store.authenticationVerified).toBe(false)
  })
  it.each(['network', '503', '409', '428'] as const)('%s转换结果不确定时封锁业务，只有/me成功才能重新解锁', async kind => {
    const store = useAuthStore(); store.applyAuthResponse(identity())
    const error = kind === 'network' ? new Error('响应丢失') : httpError(Number(kind), kind === '409'
      ? 'IDENTITY_VERSION_CONFLICT' : kind === '428' ? 'IDENTITY_VERSION_REQUIRED' : 'IDENTITY_SESSION_UNAVAILABLE')
    vi.mocked(api.switchAccount).mockRejectedValueOnce(error)
    await expect(store.switchAccount(employeeId)).rejects.toBe(error)
    expect(store.user?.id).toBe(1); expect(store.identityVersion).toBe('opaque:root')
    expect(store.identityRevalidationRequired).toBe(true); expect(store.identityReady).toBe(false)
    await expect(store.switchAccount(employeeId)).rejects.toBeInstanceOf(IdentityNotReadyError)
    expect(api.switchAccount).toHaveBeenCalledTimes(1); expect(api.fetchCurrentUser).not.toHaveBeenCalled()
    vi.mocked(api.fetchCurrentUser).mockResolvedValueOnce(identity(2, 'server-current', true))
    await store.initialize()
    expect(store.identityReady).toBe(true); expect(store.identityVersion).toBe('server-current')
  })
  it('候选列表版本不同不单独覆盖版本；旧列表回包也不能归入新身份', async () => {
    const store = useAuthStore(); store.applyAuthResponse(identity())
    vi.mocked(api.fetchSwitchTargets).mockResolvedValueOnce({ results: [], identity_version: 'different' })
    await expect(store.loadSwitchTargets('q')).rejects.toSatisfy(isCancel)
    expect(store.identityVersion).toBe('opaque:root'); expect(store.identityRevalidationRequired).toBe(true)
    store.applyAuthResponse(identity())
    const old = deferred<Awaited<ReturnType<typeof api.fetchSwitchTargets>>>()
    vi.mocked(api.fetchSwitchTargets).mockReturnValueOnce(old.promise)
    const request = store.loadSwitchTargets(); store.applyAuthResponse(identity(2, 'new', true))
    old.resolve({ results: [], identity_version: 'opaque:root' })
    await expect(request).rejects.toSatisfy(isCancel); expect(store.identityVersion).toBe('new')
  })
  it('独立Pinia不共享转换锁；退出和普通重登录清旧流程版本', async () => {
    const one = useAuthStore(); one.applyAuthResponse(identity())
    const pending = deferred<AuthResponse>(); vi.mocked(api.switchAccount).mockReturnValueOnce(pending.promise)
    const first = one.switchAccount(employeeId)
    const two = useAuthStore(createPinia()); two.applyAuthResponse(identity(2, 'v2', true))
    vi.mocked(api.logout).mockResolvedValueOnce(anonymous); await two.logout()
    expect(two.identityVersion).toBeNull(); expect(one.identityTransitionPending).toBe(true)
    vi.mocked(api.login).mockResolvedValueOnce({ authenticated: true, user: identity(3).user })
    await two.login({ username: 'plain', password: 'test-only' }); expect(two.accountSwitch).toBeNull()
    pending.resolve(identity(2, 'v3', true)); await first
    expect(one.identityVersion).toBe('v3'); expect(two.identityVersion).toBeNull()
  })
})
