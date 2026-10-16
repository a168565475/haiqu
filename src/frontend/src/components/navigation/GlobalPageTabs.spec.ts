import { defineComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter, isNavigationFailure, onBeforeRouteLeave, RouterView, useRoute } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import GlobalPageTabs from './GlobalPageTabs.vue'
import { usePageTabsStore } from '@/stores/pageTabs'

const wrappers: ReturnType<typeof mount>[] = []

beforeEach(() => sessionStorage.clear())
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

async function render() {
  const state = {
    allowLeave: false,
    guardCalls: 0,
    mounts: {} as Record<string, number>,
    unmounts: {} as Record<string, number>,
  }
  const FormPage = defineComponent({
    setup() {
      const note = ref('')
      const instancePath = useRoute().fullPath
      onMounted(() => { state.mounts[instancePath] = (state.mounts[instancePath] || 0) + 1 })
      onBeforeUnmount(() => { state.unmounts[instancePath] = (state.unmounts[instancePath] || 0) + 1 })
      onBeforeRouteLeave(() => {
        state.guardCalls++
        return !note.value || state.allowLeave
      })
      return { note }
    },
    template: '<input v-model="note" aria-label="未保存内容">',
  })
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', name: 'home', component: { template: '<p>工作台</p>' }, meta: { layout: 'erp' } },
    ...Array.from({ length: 10 }, (_, index) => ({
      path: `/page/${index + 1}`, name: `test-page-${index + 1}`, component: FormPage,
      meta: { layout: 'erp' as const, breadcrumbs: [{ label: '测试页面' }] },
    })),
  ] })
  const pinia = createPinia()
  const store = usePageTabsStore(pinia)
  await router.push('/')
  await router.isReady()
  store.synchronizeAccount('account-1', 'view-page', router)
  const Host = defineComponent({
    components: { GlobalPageTabs, RouterView },
    setup() {
      const route = useRoute()
      // 与 App.vue 一致，只记录路由已经成功到达的地址。
      watch(() => route.fullPath, () => store.recordRoute(route), { immediate: true })
      return { route }
    },
    template: '<GlobalPageTabs v-if="route.meta.layout === \'erp\'" /><RouterView v-slot="{ Component, route: current }"><component :is="Component" :key="current.fullPath" /></RouterView>',
  })
  const wrapper = mount(Host, { global: { plugins: [pinia, router] } })
  wrappers.push(wrapper)
  await flushPromises()

  async function openPage(id: number) {
    const failure = await router.push(`/page/${id}`)
    await flushPromises()
    return failure
  }

  function tabElement(path: string) {
    const tab = store.tabs.find(item => item.fullPath === path)
    const element = wrapper.findAll('[data-tab-id]').find(item => item.attributes('data-tab-id') === tab?.id)
    if (!element) throw new Error(`没有找到页面选项卡：${path}`)
    return element
  }

  return { wrapper, router, store, state, openPage, tabElement }
}

describe('公共页面选项卡与真实导航保护', () => {
  it('关闭当前页被离开保护取消时，页签、地址和实例保留', async () => {
    const { wrapper, router, store, state, openPage, tabElement } = await render()
    expect(wrapper.find('[data-page-refresh]').exists()).toBe(false)
    await openPage(1)
    await openPage(2)
    await wrapper.find('input').setValue('不要丢失')
    const paths = store.tabs.map(tab => tab.fullPath)
    await tabElement('/page/2').find('[data-tab-close]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/page/2')
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(paths)
    expect(wrapper.find('input').element.value).toBe('不要丢失')
    expect(state.mounts['/page/2']).toBe(1)
    expect(state.unmounts['/page/2'] || 0).toBe(0)
    expect(store.navigating).toBe(false)
  })

  it('未保存保护取消第六页时不删除页签，确认后才移除最早普通页', async () => {
    const { wrapper, router, store, state, openPage } = await render()
    for (let id = 1; id <= 4; id++) await openPage(id)
    await wrapper.find('input').setValue('第五页未保存')
    const initialPaths = ['/', ...Array.from({ length: 4 }, (_, index) => `/page/${index + 1}`)]
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(initialPaths)
    expect(isNavigationFailure(await openPage(5))).toBe(true)
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(initialPaths)
    expect(router.currentRoute.value.fullPath).toBe('/page/4')
    expect(state.unmounts['/page/4'] || 0).toBe(0)

    state.allowLeave = true
    await openPage(5)
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(['/', '/page/2', '/page/3', '/page/4', '/page/5'])
    expect(router.currentRoute.value.fullPath).toBe('/page/5')
    expect(state.unmounts['/page/4']).toBe(1)
    expect(wrapper.findAll('[role="tab"]')).toHaveLength(5)
  })

  it('关闭后台页只移除入口，不触发当前页保护或卸载实例', async () => {
    const { wrapper, router, store, state, openPage, tabElement } = await render()
    await openPage(1)
    await openPage(2)
    await wrapper.find('input').setValue('当前页输入')
    const guardCalls = state.guardCalls
    await tabElement('/page/1').find('[data-tab-close]').trigger('click')
    await flushPromises()
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(['/', '/page/2'])
    expect(router.currentRoute.value.fullPath).toBe('/page/2')
    expect(state.guardCalls).toBe(guardCalls)
    expect(state.mounts['/page/2']).toBe(1)
    expect(state.unmounts['/page/2'] || 0).toBe(0)
    expect(wrapper.find('input').element.value).toBe('当前页输入')
  })

  it('按钮键盘事件不被页签容器阻止，容器自身支持按键打开', async () => {
    const { wrapper, router, openPage, tabElement } = await render()
    await openPage(1)
    await openPage(2)
    const closeButton = tabElement('/page/2').find('[data-tab-close]')
    for (const key of ['Enter', ' ']) {
      const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
      closeButton.element.dispatchEvent(event)
      await flushPromises()
      expect(event.defaultPrevented).toBe(false)
      expect(router.currentRoute.value.fullPath).toBe('/page/2')
    }
    // jsdom 不模拟按键生成点击；显式点击验证关闭动作没有被容器抢走。
    await closeButton.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/page/1')
    expect(wrapper.findAll('[role="tab"]')).toHaveLength(2)

    await openPage(2)
    const tabEvent = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })
    tabElement('/page/1').element.dispatchEvent(tabEvent)
    await flushPromises()
    expect(tabEvent.defaultPrevented).toBe(true)
    expect(router.currentRoute.value.fullPath).toBe('/page/1')
  })

  it('打开多页后工作台保持首位且不能关闭，返回时不改变页签顺序', async () => {
    const { wrapper, router, store, openPage, tabElement } = await render()
    for (let id = 1; id <= 5; id++) await openPage(id)
    const paths = ['/', '/page/2', '/page/3', '/page/4', '/page/5']
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(paths)
    expect(wrapper.findAll('[role="tab"]')[0]!.attributes('aria-label')).toBe('工作台')
    expect(tabElement('/').find('[data-tab-close]').exists()).toBe(false)
    expect(wrapper.findAll('[data-tab-close]')).toHaveLength(4)
    await tabElement('/').find('[data-tab-open]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/')
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(paths)
    expect(wrapper.findAll('[role="tab"]')).toHaveLength(5)
    expect(wrapper.find('[aria-selected="true"]').attributes('aria-label')).toBe('工作台')
    expect(wrapper.find('[aria-selected="true"] [data-tab-close]').exists()).toBe(false)
  })
})
