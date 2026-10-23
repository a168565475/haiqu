import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, expect, it } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import AppSidebar from './AppSidebar.vue'

enableAutoUnmount(afterEach)
async function setup(permissions: string[]) {
  const pinia = createPinia()
  useAuthStore(pinia).user = { id: 1, username: 'isolated_finance', display_name: '隔离财务', is_superuser: false, employee: null, data_scope: 'ALL', permissions }
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', name: 'home', component: { template: '<div/>' } },
    { path: '/settings', name: 'system-settings', component: { template: '<div/>' } },
    { path: '/finance/accounts', name: 'finance-accounts', component: { template: '<div/>' }, meta: { activeMenu: 'finance-accounts' } },
  ] })
  await router.push('/'); await router.isReady()
  return { router, wrapper: mount(AppSidebar, { global: { plugins: [pinia, router] } }) }
}
it('只有账户查看权时财务入口仅开放公司账户，点击后持续选中', async () => {
  const {wrapper,router} = await setup(['finance.view_financeaccount'])
  await wrapper.get('[data-menu-key="finance-management"]').trigger('focus')
  const panel = wrapper.get('[data-sidebar-flyout]')
  expect(panel.findAll('[data-menu-key]').map(item=>item.attributes('data-menu-key'))).toEqual(['finance-accounts'])
  expect(panel.find('[data-confirmed-secondary-sidebar-icon="finance-accounts"]').exists()).toBe(true)
  await panel.get('[data-menu-key="finance-accounts"]').trigger('click'); await flushPromises()
  expect(router.currentRoute.value.name).toBe('finance-accounts')
  expect(wrapper.get('[data-menu-key="finance-management"]').classes()).toContain('is-active')
})
it('无财务查看权时隐藏整个财务入口', async () => {
  const {wrapper} = await setup(['finance.add_financeaccount'])
  expect(wrapper.find('[data-menu-key="finance-management"]').exists()).toBe(false)
})
