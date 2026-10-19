import { AxiosError } from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { useAuthStore } from '@/stores/auth'
import { fetchCurrentUser } from './auth'
import { installWeComRoleGuard } from './wecomSession'

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
describe('企业微信业务门禁响应', () => {
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
