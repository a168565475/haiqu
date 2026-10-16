import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import AppHeader from './AppHeader.vue'
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
    expect(wrapper.get('[data-current-user]').text()).toContain('超级管理员')
    expect(wrapper.find('.app-header__page-title').exists()).toBe(false)
    expect(wrapper.find('[data-breadcrumb]').exists()).toBe(false)
  })

  it('始终提供品牌和主导航，顶部与正文位于独立工作区', () => {
    const wrapper = mount(ErpLayout, {
      slots: {
        sidebar: '<nav aria-label="业务导航">客户</nav>',
        header: '<span>全局页签</span>',
        default: '<section>客户列表</section>',
      },
    })

    const sidebar = wrapper.get('.erp-layout__sidebar')
    const brand = sidebar.get('img[alt="HiTree"]')
    expect(brand.attributes('width')).toBe('64')
    expect(brand.attributes('height')).toBe('72')
    expect(sidebar.get('nav').text()).toBe('客户')
    expect(wrapper.get('.erp-layout__workspace header').text()).toBe('全局页签')
    expect(wrapper.get('.erp-layout__workspace main').text()).toBe('客户列表')
  })
})
