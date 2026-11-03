import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElMessage } from 'element-plus'
import { fetchCurrentUser } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { router } from './index'

vi.mock('@/api/auth', () => ({ fetchCurrentUser: vi.fn(), login: vi.fn(), logout: vi.fn(), getAuthErrorMessage: () => '登录失败' }))
vi.mock('element-plus', async original => ({ ...await original<typeof import('element-plus')>(), ElMessage: { error: vi.fn(), warning: vi.fn() } }))

let sequence = 0
beforeEach(async () => {
  setActivePinia(createPinia())
  vi.mocked(fetchCurrentUser).mockReset().mockResolvedValue({ authenticated: false, user: null })
  useAuthStore().clearAuthentication()
  await router.replace(`/login?navigation_test=${++sequence}`)
  vi.mocked(ElMessage.error).mockClear()
})

describe('身份确认失败时的导航', () => {
  it('已登录采购可打开采购新建，但直达 BOM 页面被拒绝', async () => {
    const auth = useAuthStore()
    auth.applyAuthResponse({ authenticated: true, user: { id: 1, username: 'buyer', display_name: '采购', is_superuser: false, employee: null,
      permissions: ['procurement.view_purchaseorder', 'procurement.add_purchaseorder'], data_scope: 'ALL' } })
    await router.push('/purchase-orders/new')
    expect(router.currentRoute.value.name).toBe('purchase-order-create')
    await router.push('/boms')
    expect(router.currentRoute.value.name).toBe('home')
    expect(ElMessage.warning).toHaveBeenCalledWith('当前岗位没有此页面的访问权限。')
  })
  it.each([
    { permission: 'procurement.view_purchaseorder', allowed: '/purchase-orders/order-1/details', blocked: '/purchase-inbound/order-1/details', expected: 'purchase-order-detail' },
    { permission: 'inventory.receive_material', allowed: '/purchase-inbound/order-1/details', blocked: '/purchase-orders/order-1/details', expected: 'purchase-inbound-detail' },
    { permission: 'inventory.quality_confirm_material', allowed: '/purchase-inbound/order-1/details', blocked: '/purchase-orders/order-1/details', expected: 'purchase-inbound-detail' },
  ])('直达详情网址也按所属入口检查：$permission', async ({ permission, allowed, blocked, expected }) => {
    useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'detail-reader', display_name: '详情查看', is_superuser: false,
      employee: null, permissions: [permission], data_scope: 'ALL' } })
    await router.push(allowed)
    expect(router.currentRoute.value.name).toBe(expected)
    await router.push(blocked)
    expect(router.currentRoute.value.name).toBe('home')
    expect(ElMessage.warning).toHaveBeenCalledWith('当前岗位没有此页面的访问权限。')
  })
  it('身份已失去验证时允许停留登录页，不反跳首页形成重试循环', async () => {
    const auth = useAuthStore()
    auth.applyAuthResponse({ authenticated: true, user: { id: 1, username: 'retry', display_name: '', is_superuser: false, employee: null, permissions: [], data_scope: 'ALL' } })
    auth.invalidateAuthenticationVerification()
    vi.mocked(fetchCurrentUser).mockClear().mockRejectedValue(new Error('Network Error'))
    await router.push('/login?redirect=/complaints')
    expect(router.currentRoute.value.fullPath).toBe('/login?redirect=/complaints')
    expect(auth.isAuthenticated).toBe(true)
    expect(fetchCurrentUser).not.toHaveBeenCalled()
  })

  it.each([new Error('Network Error'), { isAxiosError: true, response: { status: 503 } }])('临时故障保留身份和当前页，允许再次尝试', async error => {
    const auth = useAuthStore()
    const response = { authenticated: true, user: { id: 1, username: 'navigation', display_name: '测试', is_superuser: false, employee: null, permissions: ['customers.view_customercomplaint'], data_scope: 'ALL' as const } }
    auth.applyAuthResponse(response)
    auth.invalidateAuthenticationVerification()
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

  it('已知登录身份被服务端判为匿名时进入干净登录页，不继承旧身份目标', async () => {
    const auth = useAuthStore()
    auth.applyAuthResponse({ authenticated: true, user: { id: 1, username: 'expired', display_name: '', is_superuser: false, employee: null, permissions: [], data_scope: 'ALL' } })
    auth.invalidateAuthenticationVerification()
    await router.push('/complaints?q=expired')
    expect(auth.isAuthenticated).toBe(false)
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.params).toEqual({})
    expect(router.currentRoute.value.query).toEqual({})
    expect(router.currentRoute.value.hash).toBe('')
  })

  it('首次匿名访问仍可保留主动打开的登录目标，不套用旧身份隔离规则', async () => {
    setActivePinia(createPinia())
    expect(useAuthStore().initialized).toBe(false)
    vi.mocked(fetchCurrentUser).mockClear()
    await router.push('/complaints?q=initial')
    expect(useAuthStore().isAuthenticated).toBe(false)
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.params).toEqual({})
    expect(router.currentRoute.value.query).toEqual({ redirect: '/complaints?q=initial' })
    expect(router.currentRoute.value.hash).toBe('')
    expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
  })
})
