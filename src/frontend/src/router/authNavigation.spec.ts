import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElMessage } from 'element-plus'
import { fetchCurrentUser } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { router } from './index'

vi.mock('@/api/auth', () => ({ fetchCurrentUser: vi.fn(), login: vi.fn(), logout: vi.fn(), getAuthErrorMessage: () => '登录失败' }))
vi.mock('element-plus', async original => ({ ...await original<typeof import('element-plus')>(), ElMessage: { error: vi.fn() } }))

let sequence = 0
beforeEach(async () => {
  setActivePinia(createPinia())
  vi.mocked(fetchCurrentUser).mockReset().mockResolvedValue({ authenticated: false, user: null })
  useAuthStore().clearAuthentication()
  await router.replace(`/login?navigation_test=${++sequence}`)
  vi.mocked(ElMessage.error).mockClear()
})

describe('身份确认失败时的导航', () => {
  it('身份已失去验证时允许停留登录页，不反跳首页形成重试循环', async () => {
    const auth = useAuthStore()
    auth.applyAuthResponse({ authenticated: true, user: { id: 1, username: 'retry', display_name: '', is_superuser: false, employee: null, permissions: [], data_scope: 'ALL' } })
    auth.invalidateAuthenticationCheck()
    vi.mocked(fetchCurrentUser).mockClear().mockRejectedValue(new Error('Network Error'))
    await router.push('/login?redirect=/complaints')
    expect(router.currentRoute.value.fullPath).toBe('/login?redirect=/complaints')
    expect(auth.isAuthenticated).toBe(true)
    expect(fetchCurrentUser).not.toHaveBeenCalled()
  })

  it.each([new Error('Network Error'), { isAxiosError: true, response: { status: 503 } }])('临时故障保留身份和当前页，允许再次尝试', async error => {
    const auth = useAuthStore()
    const response = { authenticated: true, user: { id: 1, username: 'navigation', display_name: '测试', is_superuser: false, employee: null, permissions: [], data_scope: 'ALL' as const } }
    auth.applyAuthResponse(response)
    auth.invalidateAuthenticationCheck()
    vi.mocked(fetchCurrentUser).mockRejectedValueOnce(error)
    const previousPath = router.currentRoute.value.fullPath
    await router.push('/complaints?q=retry')
    expect(auth.isAuthenticated).toBe(true)
    expect(router.currentRoute.value.fullPath).toBe(previousPath)
    expect(ElMessage.error).toHaveBeenCalledWith('暂时无法验证登录状态，请稍后重试。')
    vi.mocked(fetchCurrentUser).mockResolvedValueOnce(response)
    await router.push('/complaints?q=retry')
    expect(router.currentRoute.value.name).toBe('complaints')
  })

  it('服务端明确匿名时跳转登录并保留目标地址', async () => {
    const auth = useAuthStore()
    auth.applyAuthResponse({ authenticated: true, user: { id: 1, username: 'expired', display_name: '', is_superuser: false, employee: null, permissions: [], data_scope: 'ALL' } })
    auth.invalidateAuthenticationCheck()
    await router.push('/complaints?q=expired')
    expect(auth.isAuthenticated).toBe(false)
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/complaints?q=expired')
  })
})
