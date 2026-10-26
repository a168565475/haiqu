import { createPinia, setActivePinia } from 'pinia'
import { expect, it, vi } from 'vitest'
import { fetchCurrentUser } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { router } from './index'

vi.mock('@/api/auth', () => ({ fetchCurrentUser: vi.fn(), login: vi.fn(), logout: vi.fn(), getAuthErrorMessage: () => '登录失败' }))
vi.mock('element-plus', async original => ({ ...await original<typeof import('element-plus')>(), ElMessage: { error: vi.fn() } }))

it('首次受保护导航无法验证已有身份时落到登录页，不留空白或反复跳转', async () => {
  setActivePinia(createPinia())
  const auth = useAuthStore()
  auth.applyAuthResponse({ authenticated: true, user: { id: 1, username: 'initial', display_name: '', is_superuser: false, employee: null, permissions: [], data_scope: 'ALL' } })
  auth.invalidateAuthenticationCheck()
  vi.mocked(fetchCurrentUser).mockRejectedValue(new Error('Network Error'))
  expect(router.currentRoute.value.matched).toHaveLength(0)
  await router.push('/complaints?q=initial')
  expect(router.currentRoute.value.name).toBe('login')
  expect(router.currentRoute.value.query.redirect).toBe('/complaints?q=initial')
  expect(auth.isAuthenticated).toBe(true)
  expect(fetchCurrentUser).toHaveBeenCalledTimes(1)
})
