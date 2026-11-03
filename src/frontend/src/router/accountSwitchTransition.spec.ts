import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { onBeforeRouteLeave, RouterView } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { router } from './index'

const api = vi.hoisted(() => ({ me: vi.fn() }))
vi.mock('@/api/auth', () => ({ fetchCurrentUser: api.me, login: vi.fn(), logout: vi.fn(),
  fetchSwitchTargets: vi.fn(), switchAccount: vi.fn(), returnAdmin: vi.fn() }))
const response = { authenticated: true as const, user: { id: 1, username: 'admin', display_name: '管理员',
  is_superuser: true, employee: null, permissions: [], data_scope: 'ALL' },
account_switch: { active: false, can_return: false, identity_version: 'private-v1' } }
const testRouteName = '__unit03-guard-test'
let wrapper: VueWrapper | undefined
let allowLeave = true
beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks(); api.me.mockResolvedValue(response); allowLeave = true })
afterEach(async () => {
  allowLeave = true
  await router.replace({ name: 'account-switch-transition' })
  wrapper?.unmount(); wrapper = undefined
  if (router.hasRoute(testRouteName)) router.removeRoute(testRouteName)
  vi.restoreAllMocks()
})

describe('生产路由的静态身份过渡页（单元测试）', () => {
  it('未初始化/身份待核验也不自动/me或OAuth，只渲染无业务API的静态页', async () => {
    const auth = useAuthStore(); const initialize = vi.spyOn(auth, 'initialize')
    await router.replace({ name: 'account-switch-transition', query: {}, hash: '' }); await router.isReady()
    wrapper = mount(defineComponent({ render: () => h(RouterView) }), { global: { plugins: [router] } })
    await flushPromises()
    expect(initialize).not.toHaveBeenCalled(); expect(api.me).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('身份操作安全页')
    expect(wrapper.find('a').attributes('href')).toBe('/')
    expect(auth.initialized).toBe(false)
  })
  it('公开过渡页特判不绕过当前组件的正常beforeRouteLeave', async () => {
    const auth = useAuthStore(); auth.applyAuthResponse(response)
    const leave = vi.fn(() => allowLeave)
    const Form = defineComponent({ setup() { onBeforeRouteLeave(leave); return () => h('input', { value: '未保存' }) } })
    router.addRoute({ path: '/__unit03-guard-test', name: testRouteName, component: Form })
    await router.replace({ name: testRouteName })
    wrapper = mount(defineComponent({ render: () => h(RouterView) }), { global: { plugins: [router] } })
    await flushPromises(); allowLeave = false
    const failure = await router.replace({ name: 'account-switch-transition' })
    expect(failure).toBeTruthy(); expect(leave).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.name).toBe(testRouteName)
    expect(wrapper.find('input').exists()).toBe(true)
    expect(api.me).not.toHaveBeenCalled()
  })
  it('其他requiresAuth路由继续正常核验，不扩大静态页豁免', async () => {
    const auth = useAuthStore(); auth.applyAuthResponse(response); auth.invalidateAuthenticationVerification()
    router.addRoute({ path: '/__unit03-guard-test', name: testRouteName,
      component: defineComponent({ render: () => h('main') }), meta: { requiresAuth: true } })
    await router.replace({ name: testRouteName })
    expect(api.me).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.name).toBe(testRouteName)
  })
})
