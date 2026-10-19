import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, expect, it } from 'vitest'

import { useAuthStore } from '@/stores/auth'
import AppSidebar from './AppSidebar.vue'

enableAutoUnmount(afterEach)

async function setup(isSuperuser: boolean, permissions: string[]) {
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.user = { id: 1, username: 'reader', display_name: '报工查看员', is_superuser: isSuperuser,
    employee: null, data_scope: 'ALL', permissions }
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { name: 'home', path: '/', component: { template: '<div />' } },
    { name: 'work-report-days', path: '/workshop/work-reports', component: { template: '<div />' } },
    { name: 'reference-data-settings', path: '/settings/reference-data', component: { template: '<div />' } },
    { name: 'theme-settings', path: '/settings/theme', component: { template: '<div />' } },
    ...['workshop-scheduling', 'workshop-metalworking-plan', 'workshop-outsourcing', 'material-issues', 'wage-schemes', 'workshop-configuration']
      .map(name => ({ name, path: `/${name}`, component: { template: '<div />' } })),
  ] })
  await router.push('/')
  await router.isReady()
  const wrapper = mount(AppSidebar, { global: { plugins: [pinia, router] } })
  return { wrapper, router }
}

it('只有报工查看权限时可打开报工记录，无需内部计划权限', async () => {
  const { wrapper, router } = await setup(false, ['workshop_reporting.view_workreport'])
  await wrapper.get('[data-menu-key="workshop-management"]').trigger('focus')
  const panel = wrapper.get('[data-sidebar-flyout]')
  expect(panel.findAll('[data-menu-key]').map(item => item.attributes('data-menu-key'))).toEqual(['work-report-days'])
  await panel.get('[data-menu-key="work-report-days"]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.name).toBe('work-report-days')
})

it('超级管理员保留报工菜单入口', async () => {
  const { wrapper } = await setup(true, [])
  await wrapper.get('[data-menu-key="workshop-management"]').trigger('focus')
  expect(wrapper.get('[data-sidebar-flyout]').find('[data-menu-key="work-report-days"]').exists()).toBe(true)
})

it('没有报工查看权限时不展示报工入口', async () => {
  const { wrapper } = await setup(false, [])
  expect(wrapper.find('[data-menu-key="workshop-management"]').exists()).toBe(false)
  expect(wrapper.find('[data-menu-key="work-report-days"]').exists()).toBe(false)
})
