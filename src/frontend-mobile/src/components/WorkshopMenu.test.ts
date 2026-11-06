import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { Popup } from 'vant'
import WorkPage from './WorkPage.vue'
import WorkshopMenu from './WorkshopMenu.vue'
import ProductionSectionTabs from './ProductionSectionTabs.vue'

const permission = vi.hoisted(() => vi.fn())
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: permission }) }))
let wrapper: VueWrapper | undefined
function makeRouter() {
  return createRouter({ history: createMemoryHistory(), routes: ['/', '/production-report', '/production-receipt', '/configuration', '/issue-records'].map(path => ({ path, component: { template: '<div />' } })) })
}
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  permission.mockReturnValue(true)
})
afterEach(() => {
  wrapper?.unmount(); wrapper = undefined
  // Vant 导航栏会延后测量高度，在测试窗口销毁前完成这些回调。
  vi.runOnlyPendingTimers()
  vi.useRealTimers()
})

describe('手机侧栏与模块入口', () => {
  it('首页显示菜单，按指定顺序展开，选择模块后关闭并跳转', async () => {
    const router = makeRouter()
    await router.push('/')
    wrapper = mount(WorkPage, { props: { title: '生产领料', home: true, section: 'issue' }, attachTo: document.body, global: { plugins: [router] } })
    expect(wrapper.get('header').isVisible()).toBe(true)
    const trigger = wrapper.get('[aria-label="展开侧边菜单"]')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await trigger.trigger('click')
    await flushPromises()
    const menu = wrapper.getComponent(WorkshopMenu)
    expect(menu.getComponent(Popup).props('show')).toBe(true)
    const drawer = new DOMWrapper(document.body).get('#workshop-navigation')
    expect(drawer.findAll('.menu-entry').map(entry => entry.text())).toEqual(['生产领料', '生产报工', '生产入库', '车间配置'])
    expect(drawer.get('[aria-current="page"]').text()).toBe('生产领料')
    await drawer.findAll('.menu-entry')[1]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/production-report')
    expect(menu.getComponent(Popup).props('show')).toBe(false)
    await wrapper.setProps({ section: 'report' })
    expect(drawer.get('[aria-current="page"]').text()).toBe('生产报工')
    await trigger.trigger('click')
    await drawer.findAll('.menu-entry')[2]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/production-receipt')
    expect(menu.getComponent(Popup).props('show')).toBe(false)
    await wrapper.setProps({ section: 'receipt' })
    expect(drawer.get('[aria-current="page"]').text()).toBe('生产入库')
  })
  it('配置仍按已有权限显示，关闭按钮和 Escape 都能收起菜单', async () => {
    permission.mockReturnValue(false)
    const router = makeRouter()
    wrapper = mount(WorkshopMenu, { props: { active: 'report' }, attachTo: document.body, global: { plugins: [router] } })
    await wrapper.get('.menu-trigger').trigger('click')
    await flushPromises()
    const drawer = new DOMWrapper(document.body).get('#workshop-navigation')
    expect(drawer.findAll('.menu-entry').map(entry => entry.text())).toEqual(['生产领料', '生产报工', '生产入库'])
    await drawer.get('.menu-close').trigger('click')
    expect(wrapper.getComponent(Popup).props('show')).toBe(false)
    await wrapper.get('.menu-trigger').trigger('click')
    await flushPromises()
    await drawer.trigger('keydown', { key: 'Escape' })
    expect(wrapper.getComponent(Popup).props('show')).toBe(false)
  })
  it('各模块记录页签使用独立入口，报工先进入计划选择', async () => {
    const router = makeRouter()
    await router.push('/')
    wrapper = mount(ProductionSectionTabs, { props: { section: 'issue', records: false }, global: { plugins: [router] } })
    await wrapper.findAll('a')[1]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/issue-records')
    await wrapper.setProps({ section: 'report', records: true })
    await wrapper.findAll('a')[1]!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/production-report?view=records')
    expect(wrapper.get('[aria-current="page"]').text()).toBe('报工记录')
  })
})
