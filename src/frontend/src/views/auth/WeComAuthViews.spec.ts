import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WaitingRoleView from './WaitingRoleView.vue'
import WeComErrorView from './WeComErrorView.vue'
import { useAuthStore } from '@/stores/auth'
import { fetchCurrentUser, logout } from '@/api/auth'

const route = vi.hoisted(() => ({ query: { reason: 'STATE_INVALID' as unknown } }))
const replace = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ replace }) }))
vi.mock('@/api/auth', async original => ({ ...await original<object>(), fetchCurrentUser: vi.fn(), logout: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  setActivePinia(createPinia()); vi.clearAllMocks(); route.query.reason = 'STATE_INVALID'
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'wecom', display_name: '员工', is_superuser: false, employee: { id: 'e', employee_code: 'E1', display_name: '等待员工', status: 'ACTIVE' }, permissions: [], data_scope: 'NONE', waiting_for_role: true } })
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))
describe('企微独立认证页面', () => {
  it('等待页刷新后进入首页，未授权时保留身份', async () => {
    const auth = useAuthStore()
    vi.mocked(fetchCurrentUser).mockResolvedValueOnce({ authenticated: true, user: { ...auth.user! } }).mockResolvedValueOnce({ authenticated: true, user: { ...auth.user!, waiting_for_role: false } })
    const wrapper = mount(WaitingRoleView); wrappers.push(wrapper)
    expect(wrapper.text()).toContain('等待员工')
    await wrapper.get('[data-action="refresh-role"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('尚未分配有效角色')
    expect(replace).not.toHaveBeenCalled()
    await wrapper.get('[data-action="refresh-role"]').trigger('click'); await flushPromises()
    expect(replace).toHaveBeenCalledWith({ name: 'home' })
  })
  it('退出失败不显示成功或清除原会话', async () => {
    vi.mocked(logout).mockRejectedValue(new Error('offline'))
    const wrapper = mount(WaitingRoleView); wrappers.push(wrapper)
    await wrapper.get('[data-action="logout"]').trigger('click'); await flushPromises()
    expect(useAuthStore().isAuthenticated).toBe(true)
    expect(wrapper.text()).toContain('退出失败')
    expect(replace).not.toHaveBeenCalled()
  })
  it('错误页仅显示固定码对应文案，不回显任意查询文本', () => {
    route.query.reason = '<script>secret-value</script>'
    const wrapper = mount(WeComErrorView); wrappers.push(wrapper)
    expect(wrapper.text()).toContain('企业微信登录未完成')
    expect(wrapper.text()).not.toContain('secret-value')
    expect(wrapper.find('script').exists()).toBe(false)
  })
  it.each([
    ['STATE_INVALID', '登录请求已过期或已使用'],
    ['CONFIGURATION_ERROR', '接入配置尚未就绪'],
    ['IDENTITY_MISMATCH', '原会话未切换'],
    ['MEMBER_REJECTED', '当前成员无法使用此应用'],
    ['UPSTREAM_UNAVAILABLE', '暂时无法连接'],
    ['LOGIN_FAILED', '仍失败时联系管理员'],
  ])('公开错误码%s显示固定可操作说明', (reason, message) => {
    route.query.reason = reason
    const wrapper = mount(WeComErrorView); wrappers.push(wrapper)
    expect(wrapper.text()).toContain(message)
    expect(wrapper.find('a[href*="callback"]').exists()).toBe(false)
  })
})
