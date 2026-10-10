import { defineComponent, onBeforeUnmount, onMounted, ref, type Component } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter, isNavigationFailure, onBeforeRouteLeave, RouterView } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import PageRefreshView from '@/views/PageRefreshView.vue'
import { refreshCurrentPage, resolveRefreshTarget } from './pageRefresh'

const wrappers: ReturnType<typeof mount>[] = []
const Host = defineComponent({
  components: { RouterView },
  template: '<RouterView v-slot="{ Component, route }"><component :is="Component" :key="route.fullPath" /></RouterView>',
})

function createTestRouter(formPage: Component = { template: '<p>编辑页面</p>' }) {
  return createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', name: 'home', component: { template: '<p>工作台</p>' }, meta: { layout: 'erp' } },
    { path: '/orders/:id/edit', name: 'order-edit', component: formPage, meta: { layout: 'erp' } },
    { path: '/_page-refresh', name: 'page-refresh', component: PageRefreshView, meta: { requiresAuth: true } },
    { path: '/login', name: 'login', component: { template: '<p>登录</p>' } },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: { template: '<p>不存在</p>' }, meta: { layout: 'erp' } },
  ] })
}

afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('刷新桥接目标', () => {
  it('保留已注册业务页的参数、查询与锚点', () => {
    const router = createTestRouter()
    const target = '/orders/first/edit?mode=draft#materials'
    expect(resolveRefreshTarget(router, target)).toBe(target)
    expect(resolveRefreshTarget(router, '/')).toBe('/')
  })

  it.each([undefined, null, [], ['/orders/first/edit'], '', 'orders/first/edit',
    'https://example.com', '//example.com/orders', '/\\example.com', '/orders/first/edit\n',
    '/login', '/unknown', '/_page-refresh?target=/orders/first/edit'])('无效目标 %s 回工作台', target => {
    expect(resolveRefreshTarget(createTestRouter(), target)).toBe('/')
  })

  it('解析异常回工作台', () => {
    const router = createTestRouter()
    vi.spyOn(router, 'resolve').mockImplementation(() => { throw new Error('路由解析失败') })
    expect(resolveRefreshTarget(router, '/orders/first/edit')).toBe('/')
  })
})

describe('真实路由刷新与既有离开保护', () => {
  async function renderForm() {
    const state = { mounts: 0, unmounts: 0, allowLeave: false }
    const FormPage = defineComponent({
      setup() {
        const note = ref('')
        onMounted(() => { state.mounts++ })
        onBeforeUnmount(() => { state.unmounts++ })
        onBeforeRouteLeave(() => !note.value || state.allowLeave)
        return { note }
      },
      template: '<input v-model="note" aria-label="未保存内容">',
    })
    const router = createTestRouter(FormPage)
    await router.push('/')
    await router.push('/orders/first/edit?mode=draft#materials')
    await router.isReady()
    const wrapper = mount(Host, { global: { plugins: [router] } })
    wrappers.push(wrapper)
    await flushPromises()
    return { wrapper, router, state }
  }

  it('离开保护取消时不卸载，保留输入与地址', async () => {
    const { wrapper, router, state } = await renderForm()
    await wrapper.find('input').setValue('不要丢失')
    const failure = await refreshCurrentPage(router)
    await flushPromises()
    expect(isNavigationFailure(failure)).toBe(true)
    expect(router.currentRoute.value.fullPath).toBe('/orders/first/edit?mode=draft#materials')
    expect(wrapper.find('input').element.value).toBe('不要丢失')
    expect(state).toMatchObject({ mounts: 1, unmounts: 0 })
  })

  it('确认后重建一次，清空旧输入且不增加历史', async () => {
    const { wrapper, router, state } = await renderForm()
    await wrapper.find('input').setValue('旧输入')
    state.allowLeave = true
    await refreshCurrentPage(router)
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/orders/first/edit?mode=draft#materials')
    expect(wrapper.find('input').element.value).toBe('')
    expect(state).toMatchObject({ mounts: 2, unmounts: 1 })
    router.back()
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/')
  })

  it('快速重复刷新只执行一次桥接', async () => {
    const { router, state } = await renderForm()
    await Promise.all([refreshCurrentPage(router), refreshCurrentPage(router)])
    await flushPromises()
    expect(state).toMatchObject({ mounts: 2, unmounts: 1 })
  })

  it('非业务页面不发起刷新', async () => {
    const router = createTestRouter()
    await router.push('/login')
    const replace = vi.spyOn(router, 'replace')
    await refreshCurrentPage(router)
    expect(replace).not.toHaveBeenCalled()
  })

  it('返回原页被拦截时展示返回工作台入口', async () => {
    const router = createTestRouter()
    await router.push('/_page-refresh?target=/orders/first/edit')
    router.beforeEach(to => to.name === 'order-edit' ? false : true)
    const wrapper = mount(Host, { global: { plugins: [router] } })
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('刷新未成功')
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/')
  })

  it('返回原页异常时展示错误，工作台返回失败仍可重试', async () => {
    const router = createTestRouter()
    await router.push('/_page-refresh?target=/orders/first/edit')
    const replace = vi.spyOn(router, 'replace').mockRejectedValue(new Error('加载失败'))
    const wrapper = mount(Host, { global: { plugins: [router] } })
    wrappers.push(wrapper)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('刷新失败')
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('返回工作台失败')
    expect(wrapper.find('button').attributes('disabled')).toBeUndefined()
    replace.mockRestore()
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/')
  })
})
