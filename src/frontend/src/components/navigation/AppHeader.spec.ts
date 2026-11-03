import { mount } from '@vue/test-utils'
import type { ElDropdown } from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AppHeader from './AppHeader.vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

vi.mock('vue-router', () => ({ useRouter: () => ({ replace: vi.fn() }) }))
vi.mock('./GlobalPageTabs.vue', () => ({ default: { template: '<div />' } }))
vi.mock('./HeaderMessages.vue', () => ({ default: { template: '<button data-message-toggle>消息</button>' } }))
const menuStubs = { ElIcon: true, ElDropdownItem: true, ElDropdownMenu: true }

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  useAuthStore().applyAuthResponse({ authenticated: true, user: {
    id: 1, username: 'employee', display_name: '员工', is_superuser: false,
    employee: null, permissions: [], data_scope: 'NONE',
  } })
})
afterEach(() => vi.unstubAllGlobals())

describe('用户菜单客户端边界', () => {
  it.each(['Chrome/130.0', 'wxwork/4.1.0'])('%s切换后菜单显示超级管理，返回和核验只发事件', async userAgent => {
    vi.stubGlobal('navigator', { userAgent })
    const auth = useAuthStore()
    auth.applyAuthResponse({ authenticated: false, user: null,
      account_switch: { active: true, can_return: true, identity_version: 'v2' } })
    const direct = vi.spyOn(auth, 'returnAdmin')
    const wrapper = mount(AppHeader, { global: { stubs: {
      ElIcon: true, ElDropdown: { name: 'ElDropdown', template: '<div><slot /><slot name="dropdown" /></div>' },
      ElDropdownMenu: { template: '<div><slot /></div>' }, ElDropdownItem: { template: '<div><slot /></div>' },
    } } })
    const menu = wrapper.getComponent<typeof ElDropdown>('.app-header__user-menu')
    expect(wrapper.get('[data-return-admin]').text()).toContain('超级管理')
    menu.vm.$emit('command', 'return-admin')
    expect(wrapper.emitted('return-admin')).toHaveLength(1)
    expect(direct).not.toHaveBeenCalled()
    auth.requireIdentityRevalidation()
    await wrapper.setProps({ switchError: '身份需要核验' })
    menu.vm.$emit('command', 'return-admin')
    expect(wrapper.emitted('return-admin')).toHaveLength(1)
    expect(wrapper.find('[data-verify-identity]').exists()).toBe(true)
    menu.vm.$emit('command', 'verify-identity')
    expect(wrapper.emitted('verify-identity')).toHaveLength(1)
    await wrapper.setProps({ switchBusy: true })
    menu.vm.$emit('command', 'verify-identity')
    expect(wrapper.emitted('verify-identity')).toHaveLength(1)
    wrapper.unmount()
  })

  it.each(['wxwork/4.1.0', 'WXWork/4.1.36'])('企业微信 %s 只显示当前员工，没有退出菜单', userAgent => {
    vi.stubGlobal('navigator', { userAgent })
    const wrapper = mount(AppHeader, { global: { stubs: { ...menuStubs, ElDropdown: { template: '<div><slot /></div>' } } } })
    expect(wrapper.get('[data-current-user]').text()).toBe('员工')
    expect(wrapper.find('button[aria-label="打开用户菜单"]').exists()).toBe(false)
    expect(wrapper.find('[data-theme-toggle]').exists()).toBe(true)
    expect(wrapper.find('.app-header__user-menu').exists()).toBe(false)
    wrapper.unmount()
  })
  it('普通浏览器保留用户菜单', () => {
    vi.stubGlobal('navigator', { userAgent: 'Chrome/130.0' })
    const wrapper = mount(AppHeader, { global: { stubs: {
      ...menuStubs,
      ElDropdown: { template: '<div><slot /></div>' },
    } } })
    expect(wrapper.find('button[aria-label="打开用户菜单"]').exists()).toBe(true)
    wrapper.unmount()
  })
  it.each(['Chrome/130.0', 'wxwork/4.1.0'])('%s管理员按能力有切换入口，发事件不直接写身份', async userAgent => {
    vi.stubGlobal('navigator', { userAgent })
    const auth = useAuthStore()
    auth.applyAuthResponse({ authenticated: true, user: {
      id: 1, username: 'admin', display_name: '实际管理员', is_superuser: true,
      employee: null, permissions: [], data_scope: 'ALL',
    }, account_switch: { active: false, can_return: false, identity_version: 'v1' } })
    const switchWrite = vi.spyOn(auth, 'switchAccount')
    const logout = vi.spyOn(auth, 'logout')
    const wrapper = mount(AppHeader, { global: { stubs: {
      ElIcon: true,
      ElDropdown: { name: 'ElDropdown', template: '<div><slot /><slot name="dropdown" /></div>' },
      ElDropdownMenu: { template: '<div><slot /></div>' },
      ElDropdownItem: { template: '<div><slot /></div>' },
    } } })
    expect(wrapper.get('[data-current-user]').text()).toBe('实际管理员')
    expect(wrapper.find('[data-switch-account-action]').exists()).toBe(true)
    expect(wrapper.find('[data-logout-action]').exists()).toBe(!userAgent.includes('wxwork'))
    wrapper.getComponent<typeof ElDropdown>('.app-header__user-menu').vm.$emit('command', 'switch-account')
    expect(wrapper.emitted('switch-account')).toHaveLength(1)
    expect(switchWrite).not.toHaveBeenCalled()
    if (userAgent.includes('wxwork')) {
      wrapper.getComponent<typeof ElDropdown>('.app-header__user-menu').vm.$emit('command', 'logout')
      expect(logout).not.toHaveBeenCalled()
    }
    wrapper.unmount()
  })
  it('全局flow busy期间禁止切换入口和退出命令，过期能力不能继续发切换事件', async () => {
    vi.stubGlobal('navigator', { userAgent: 'Chrome/130.0' })
    const auth = useAuthStore()
    auth.accountSwitch = { active: true, can_return: true, identity_version: 'v1' }
    const logout = vi.spyOn(auth, 'logout')
    const wrapper = mount(AppHeader, { props: { switchBusy: true }, global: { stubs: {
      ...menuStubs, ElDropdown: { name: 'ElDropdown', template: '<div><slot /></div>' },
    } } })
    const menu = wrapper.getComponent<typeof ElDropdown>('.app-header__user-menu')
    menu.vm.$emit('command', 'switch-account')
    menu.vm.$emit('command', 'logout')
    expect(wrapper.emitted('switch-account')).toBeUndefined()
    expect(logout).not.toHaveBeenCalled()
    expect((wrapper.get('button[aria-label="打开用户菜单"]').element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.setProps({ switchBusy: false })
    auth.requireIdentityRevalidation()
    menu.vm.$emit('command', 'switch-account')
    expect(wrapper.emitted('switch-account')).toBeUndefined()
    wrapper.unmount()
  })
  it('主题图标只打开选择入口，选择具体主题后才切换', async () => {
    const wrapper = mount(AppHeader, { global: { stubs: {
      ...menuStubs, ElDropdown: { name: 'ElDropdown', template: '<div><slot /></div>' },
    } } })
    const theme = useThemeStore()
    await wrapper.get('[data-theme-toggle]').trigger('click')
    expect(theme.current).toBe('blue-gray')
    const menu = wrapper.getComponent({ name: 'ElDropdown' })
    menu.vm.$emit('command', 'dark')
    expect(theme.current).toBe('dark')
    menu.vm.$emit('command', 'unknown-theme')
    expect(theme.current).toBe('dark')
    wrapper.unmount()
  })
})
