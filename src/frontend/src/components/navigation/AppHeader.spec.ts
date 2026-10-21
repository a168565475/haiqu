import { mount } from '@vue/test-utils'
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
