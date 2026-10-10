import { mount, RouterLinkStub, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import AppHeader from './AppHeader.vue'
import AppSidebar from './AppSidebar.vue'
import ErpLayout from '@/layouts/ErpLayout.vue'

const routeMock = vi.hoisted(() => ({
  name: 'tasks',
  params: {},
  meta: { activeMenu: 'tasks', headerTitle: '任务中心', breadcrumbs: [{ label: '任务中心' }] },
}))

vi.mock('vue-router', async (importOriginal) => ({
  ...await importOriginal<typeof import('vue-router')>(),
  useRoute: () => routeMock,
  useRouter: () => ({ replace: vi.fn() }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { is_superuser: true, display_name: '管理员', employee: null },
    hasPermission: () => true,
    hasAnyPermission: () => true,
  }),
}))

const popoverStub = {
  template: '<div class="popover-stub"><slot name="reference" /><slot /></div>',
}

describe('折叠侧栏交互', () => {
  it('折叠时为一级菜单提供右侧子菜单内容', () => {
    const wrapper = shallowMount(AppSidebar, {
      props: { compact: true },
      global: {
        stubs: { RouterLink: RouterLinkStub, ElPopover: popoverStub },
      },
    })

    const flyout = wrapper.get('[data-flyout-menu-key="customer-management"]')
    expect(flyout.text()).toContain('客户管理')
    expect(flyout.text()).toContain('任务中心')
    expect(wrapper.findAll('.app-sidebar__flyout').length).toBeGreaterThan(0)
  })

  it('折叠状态不再显示顶部展开侧栏按钮', async () => {
    const wrapper = mount(AppHeader, {
      props: { compact: true },
      global: {
        plugins: [ElementPlus],
        stubs: {
          RouterLink: RouterLinkStub,
          GlobalPageTabs: { template: '<nav data-global-page-tabs role="tablist" />' },
        },
      },
    })

    expect(wrapper.find('[data-sidebar-expand]').exists()).toBe(false)
    expect(wrapper.get('.app-header__context').attributes('role')).toBeUndefined()
    expect(wrapper.find('[data-global-page-tabs]').exists()).toBe(true)
    expect(wrapper.find('.app-header__page-title').exists()).toBe(false)
    expect(wrapper.find('[data-breadcrumb]').exists()).toBe(false)
  })

  it('强制展开状态覆盖窄屏默认折叠样式', () => {
    const wrapper = mount(ErpLayout, {
      props: { compactSidebar: false, sidebarExpanded: true },
    })

    expect(wrapper.classes()).toContain('erp-layout--sidebar-expanded')
  })
})
