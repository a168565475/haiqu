import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import AppHeader from './AppHeader.vue'
import ErpLayout from '@/layouts/ErpLayout.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  notificationApi.count.mockReset().mockResolvedValue(0)
  notificationApi.inbox.mockReset().mockResolvedValue({ data: [], count: 0, page: 1, page_size: 10 })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
})
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })

const routeMock = vi.hoisted(() => ({
  name: 'tasks',
  path: '/tasks',
  fullPath: '/tasks',
  params: {},
  query: {},
  meta: { activeMenu: 'tasks', headerTitle: '任务中心', breadcrumbs: [{ label: '任务中心' }] },
}))
const accountActions = vi.hoisted(() => ({ logout: vi.fn(), replace: vi.fn() }))
const notificationApi = vi.hoisted(() => ({ count: vi.fn(), inbox: vi.fn() }))

vi.mock('@/api/notifications', async importOriginal => ({
  ...await importOriginal<typeof import('@/api/notifications')>(),
  getNotificationUnreadCount: notificationApi.count,
  getNotificationInbox: notificationApi.inbox,
}))

vi.mock('vue-router', async (importOriginal) => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRoute: () => routeMock,
  useRouter: () => ({ replace: accountActions.replace }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { is_superuser: true, display_name: '管理员', employee: null },
    hasPermission: () => true,
    hasAnyPermission: () => true,
    logout: accountActions.logout,
  }),
}))

describe('常驻主栏的页面外壳', () => {
  it('顶部保留全局页签与账号入口，不显示展开侧栏按钮', () => {
    const wrapper = mount(AppHeader, {
      global: {
        plugins: [ElementPlus],
        stubs: {
          GlobalPageTabs: { template: '<nav data-global-page-tabs role="tablist" />' },
        },
      },
    })

    expect(wrapper.find('[data-sidebar-expand]').exists()).toBe(false)
    expect(wrapper.get('.app-header__context').attributes('role')).toBeUndefined()
    expect(wrapper.find('[data-global-page-tabs]').exists()).toBe(true)
    expect(wrapper.get('img[alt="HiTree"]').attributes('src')).toContain('hitree-header-logo')
    expect(wrapper.get('[data-current-user]').text()).toContain('超级管理员')
    expect(wrapper.find('.app-header__page-title').exists()).toBe(false)
    expect(wrapper.find('[data-breadcrumb]').exists()).toBe(false)
    expect(wrapper.find('.app-header__search-shell, .app-header__icon-action, .app-header__avatar').exists()).toBe(false)
    wrapper.unmount()
  })

  it('精简后账号菜单仍可退出，提交期间禁止重复退出', async () => {
    accountActions.logout.mockReset()
    accountActions.replace.mockReset()
    let finish!: () => void
    accountActions.logout.mockReturnValueOnce(new Promise<void>(resolve => { finish = resolve }))
    const wrapper = mount(AppHeader, {
      global: { plugins: [ElementPlus], stubs: { GlobalPageTabs: true } },
    })
    try {
      const menu = wrapper.findAllComponents({ name: 'ElDropdown' }).find(item => item.classes().includes('app-header__user-menu'))!
      menu.vm.$emit('command', 'logout')
      menu.vm.$emit('command', 'logout')
      await flushPromises()
      expect(accountActions.logout).toHaveBeenCalledTimes(1)
      expect(wrapper.get('[data-current-user]').attributes('disabled')).toBeDefined()
      finish()
      await flushPromises()
      expect(accountActions.replace).toHaveBeenCalledWith({ name: 'login' })
      expect(wrapper.get('[data-current-user]').attributes('disabled')).toBeUndefined()
    } finally { wrapper.unmount() }
  })

  it('消息气泡保持非模态语义，Escape关闭后焦点返回消息按钮', async () => {
    const wrapper = mount(AppHeader, {
      attachTo: document.body,
      global: { plugins: [ElementPlus], stubs: { GlobalPageTabs: true } },
    })
    try {
      await flushPromises()
      const trigger = wrapper.get('[data-message-toggle]')
      expect(trigger.attributes('aria-haspopup')).toBe('dialog')
      await trigger.trigger('click')
      await flushPromises()
      const panel = document.getElementById(trigger.attributes('aria-controls')!)!
      expect(panel.getAttribute('role')).toBe('dialog')
      expect(panel.getAttribute('aria-modal')).toBe('false')
      expect(document.getElementById(panel.getAttribute('aria-labelledby')!)?.textContent).toBe('消息')
      expect(trigger.attributes('aria-expanded')).toBe('true')
      expect(document.activeElement?.getAttribute('aria-label')).toBe('关闭消息')
      const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
      document.dispatchEvent(escape)
      await flushPromises()
      expect(escape.defaultPrevented).toBe(true)
      expect(document.getElementById('header-message-panel')).toBeNull()
      expect(trigger.attributes('aria-expanded')).toBe('false')
      expect(document.activeElement).toBe(trigger.element)
    } finally { wrapper.unmount() }
  })

  it('消息气泡允许焦点移到外部，关闭时不抢回外部焦点', async () => {
    const outside = document.createElement('button')
    outside.textContent = '页面其他操作'
    document.body.append(outside)
    const wrapper = mount(AppHeader, {
      attachTo: document.body,
      global: { plugins: [ElementPlus], stubs: { GlobalPageTabs: true } },
    })
    try {
      await flushPromises()
      const trigger = wrapper.get('[data-message-toggle]')
      await trigger.trigger('click')
      await flushPromises()
      expect(document.getElementById('header-message-panel')).not.toBeNull()
      outside.focus()
      await flushPromises()
      expect(document.getElementById('header-message-panel')).toBeNull()
      expect(trigger.attributes('aria-expanded')).toBe('false')
      expect(document.activeElement).toBe(outside)
    } finally { wrapper.unmount(); outside.remove() }
  })

  it('全宽顶部独立于下方侧栏和正文，侧栏不重复放品牌', () => {
    const wrapper = mount(ErpLayout, {
      slots: {
        sidebar: '<nav aria-label="业务导航">客户</nav>',
        header: '<span>全局页签</span>',
        default: '<section>客户列表</section>',
      },
    })

    const sidebar = wrapper.get('.erp-layout__sidebar')
    expect(sidebar.find('img[alt="HiTree"]').exists()).toBe(false)
    expect(sidebar.get('nav').text()).toBe('客户')
    expect(wrapper.get('.erp-layout > header').text()).toBe('全局页签')
    expect(wrapper.find('.erp-layout__body .erp-layout__sidebar').exists()).toBe(true)
    expect(wrapper.get('.erp-layout__workspace main').text()).toBe('客户列表')
  })
})
