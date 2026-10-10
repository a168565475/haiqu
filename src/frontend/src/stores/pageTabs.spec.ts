import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { defineComponent } from 'vue'

import { usePageTabsStore } from './pageTabs'

const page = defineComponent({ template: '<div />' })
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: page, meta: { layout: 'erp' } },
    ...Array.from({ length: 10 }, (_, index) => ({ path: `/page-${index}`, name: `page-${index}`, component: page, meta: { layout: 'erp' as const } })),
    { path: '/login', name: 'login', component: page },
    { path: '/_page-refresh', name: 'page-refresh', component: page },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: page, meta: { layout: 'erp' } },
  ],
})

describe('页面选项卡账户与刷新恢复', () => {
  beforeEach(() => { setActivePinia(createPinia()); sessionStorage.clear() })

  it('同一账户刷新恢复五项与原顺序，被移除的工作台不重新占位', () => {
    const store = usePageTabsStore()
    store.synchronizeAccount(1, 'view', router)
    for (let index = 0; index < 9; index++) store.recordRoute(router.resolve(`/page-${index}`))
    const paths = store.tabs.map(tab => tab.fullPath)
    expect(paths).toEqual(Array.from({ length: 5 }, (_, index) => `/page-${index + 4}`))
    setActivePinia(createPinia())
    const restored = usePageTabsStore()
    restored.synchronizeAccount(1, 'view', router)
    expect(restored.tabs.map(tab => tab.fullPath)).toEqual(paths)
  })

  it('退出、失效和账户切换清空前一账户入口', () => {
    const store = usePageTabsStore()
    store.synchronizeAccount(1, 'view', router)
    store.recordRoute(router.resolve('/page-1'))
    store.synchronizeAccount(2, 'view', router)
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(['/'])
    expect(sessionStorage.getItem('haiqu:page-tabs:v1:1')).toBeNull()
    store.recordRoute(router.resolve('/page-2'))
    store.synchronizeAccount(undefined, '', router)
    expect(store.tabs).toEqual([])
    expect(sessionStorage.getItem('haiqu:page-tabs:v1:2')).toBeNull()
  })

  it('权限变化清除旧入口，同账户重载不恢复旧权限集合', () => {
    const store = usePageTabsStore()
    store.synchronizeAccount(1, 'old', router)
    store.recordRoute(router.resolve('/page-1'))
    store.synchronizeAccount(1, 'new', router)
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(['/'])
    expect(sessionStorage.getItem('haiqu:page-tabs:v1:1')).toBeNull()
    sessionStorage.setItem('haiqu:page-tabs:v1:3', JSON.stringify({ permissionSignature: 'old', paths: ['/page-2'] }))
    store.synchronizeAccount(3, 'new', router)
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(['/'])
  })

  it('恢复时忽略外部、不存在和非业务页面，损坏内容回到工作台', () => {
    sessionStorage.setItem('haiqu:page-tabs:v1:1', JSON.stringify({ permissionSignature: 'view', paths: ['//external.test', '/missing', '/login', '/_page-refresh', 123, '/page-1'] }))
    const store = usePageTabsStore()
    store.synchronizeAccount(1, 'view', router)
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(['/page-1'])
    sessionStorage.setItem('haiqu:page-tabs:v1:2', 'broken-json')
    store.synchronizeAccount(2, 'view', router)
    expect(store.tabs.map(tab => tab.fullPath)).toEqual(['/'])
  })

  it('存储不可用时导航、自动移除和退出仍可执行', () => {
    const getter = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
    const setter = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('full') })
    const remover = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('blocked') })
    try {
      const store = usePageTabsStore()
      store.synchronizeAccount(1, 'view', router)
      for (let index = 0; index < 10; index++) store.recordRoute(router.resolve(`/page-${index}`))
      expect(store.tabs).toHaveLength(5)
      store.removeTab(store.tabs[0]!.id)
      expect(store.tabs).toHaveLength(4)
      store.clear()
      expect(store.tabs).toEqual([])
    } finally { getter.mockRestore(); setter.mockRestore(); remover.mockRestore() }
  })

  it('已读取的页面标题在重复进入时保留，未知页不会凭空增加', () => {
    const store = usePageTabsStore()
    store.synchronizeAccount(1, 'view', router)
    const route = router.resolve('/page-1')
    store.recordRoute(route)
    store.setTabTitle(route, '采购明细')
    store.recordRoute(route)
    expect(store.tabs.at(-1)?.title).toBe('采购明细')
    store.setTabTitle(router.resolve('/page-2'), '未知页面')
    expect(store.tabs).toHaveLength(2)
  })
})
