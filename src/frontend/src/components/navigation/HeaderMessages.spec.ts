import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, reactive } from 'vue'
import { AxiosError } from 'axios'
import HeaderMessages from './HeaderMessages.vue'
import PageContainer from '@/layouts/PageContainer.vue'
import { useAuthStore } from '@/stores/auth'
import { useNotificationsStore } from '@/stores/notifications'
import type { NotificationItem } from '@/types/notifications'

const api = vi.hoisted(() => ({ inbox: vi.fn(), count: vi.fn(), read: vi.fn(), target: vi.fn(), detail: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn(), hasRoute: vi.fn() }))
const route = reactive<{ path: string; query: { notification?: string | string[] } }>({ path: '/', query: {} })
vi.mock('vue-router', () => ({ useRouter: () => router, useRoute: () => route }))
vi.mock('@/api/notifications', async importOriginal => ({
  ...await importOriginal<typeof import('@/api/notifications')>(),
  getNotificationInbox: api.inbox, getNotificationUnreadCount: api.count,
  markNotificationRead: api.read, getNotificationTarget: api.target, getNotificationDetail: api.detail,
}))
const id = '12345678-1234-1234-1234-123456789abc'
const item: NotificationItem = { id, event_code: 'BOM_CONFIRMED', event_name: 'BOM确认', title: '演示消息', body: '演示正文',
  created_at: '2026-10-21T01:00:00Z', read_at: null, target: null, target_accessible: true, channel_status: {} }
let wrapper: ReturnType<typeof mount> | undefined
let reduced = false
function render() { wrapper = mount(HeaderMessages, { attachTo: document.body }); return wrapper }
beforeEach(() => {
  vi.useFakeTimers(); vi.resetAllMocks(); setActivePinia(createPinia()); reduced = false
  route.path = '/'; route.query = {}
  vi.stubGlobal('matchMedia', () => ({ get matches() { return reduced }, addEventListener: vi.fn(), removeEventListener: vi.fn() }))
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'employee', display_name: '员工',
    employee: null, is_superuser: false, permissions: [], data_scope: 'NONE' } })
  api.count.mockResolvedValue(2)
  api.inbox.mockResolvedValue({ data: [item], count: 1, page: 1, page_size: 10 })
  api.read.mockResolvedValue({ ...item, read_at: '2026-10-21T02:00:00Z' })
  api.detail.mockResolvedValue(item)
  api.target.mockResolvedValue({ target_key: 'bom-detail', object_id: id, route_name: 'bom-preview', params: { bomId: id } })
  router.hasRoute.mockReturnValue(true); router.push.mockResolvedValue(undefined)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; document.body.innerHTML = ''; vi.useRealTimers(); vi.unstubAllGlobals() })

describe('页头消息组件（隔离替身）', () => {
  it('冷启动页面容器自动聚焦后，卡片链接仍保持消息面板打开', async () => {
    route.query = { notification: id }
    wrapper = mount({ components: { HeaderMessages, PageContainer },
      template: '<div><HeaderMessages /><main id="erp-main-content" tabindex="-1"><PageContainer>工作台</PageContainer></main></div>',
    }, { attachTo: document.body })
    ;(document.querySelector('#erp-main-content') as HTMLElement).scrollTo = vi.fn()
    await flushPromises()
    expect(document.querySelector('[data-linked-notification]')?.textContent).toContain(item.body)
    expect(api.read).not.toHaveBeenCalled()
  })
  it('卡片链接只读打开指定通知，点击查看业务才标记已读并复查目标', async () => {
    route.query = { notification: id }
    render(); await flushPromises()
    expect(api.detail.mock.calls[0]?.[0]).toBe(id)
    expect(document.querySelector('[data-linked-notification]')?.textContent).toContain(item.body)
    expect(api.read).not.toHaveBeenCalled()
    expect(api.target).not.toHaveBeenCalled()
    ;(document.querySelector('[data-linked-notification] button') as HTMLButtonElement).click(); await flushPromises()
    expect(api.read.mock.calls[0]?.[0]).toBe(id)
    expect(api.target.mock.calls[0]?.[0]).toBe(id)
    expect(router.push).toHaveBeenCalledWith({ name: 'bom-preview', params: { bomId: id } })
  })
  it.each(['invalid', [id, id]])('非法或重复通知参数不读取任何单条正文：%s', async notification => {
    route.query = { notification }
    render(); await flushPromises()
    expect(document.body.textContent).toContain('通知链接无效')
    expect(api.detail).not.toHaveBeenCalled()
    expect(api.read).not.toHaveBeenCalled()
  })
  it('他人或不存在通知只显示统一不可访问提示，不展示上一次正文', async () => {
    route.query = { notification: id }
    render(); await flushPromises()
    api.detail.mockRejectedValueOnce(new AxiosError('private', undefined, undefined, undefined,
      { status: 404, data: 'private', headers: {}, config: {} as never, statusText: 'Not Found' }))
    route.query = { notification: '22222222-2222-2222-2222-222222222222' }; await flushPromises()
    expect(document.body.textContent).not.toContain(item.body)
    expect(document.body.textContent).toContain('已无访问权限')
    expect(document.body.textContent).not.toContain('private')
    expect(api.read).not.toHaveBeenCalled()
  })
  it('退出账号时丢弃迟到的通知正文，无目标通知也不会触发业务请求', async () => {
    let release!: (value: NotificationItem) => void
    api.detail.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
    route.query = { notification: id }; render(); await flushPromises()
    useAuthStore().clearAuthentication(); await nextTick()
    release(item); await flushPromises()
    expect(document.body.textContent).not.toContain(item.body)
    expect(api.read).not.toHaveBeenCalled()
  })
  it('旧账号查看业务的迟到结果不能清空新账号已加载的通知', async () => {
    let release!: (value: NotificationItem) => void
    api.read.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
    route.query = { notification: id }; render(); await flushPromises()
    ;(document.querySelector('[data-linked-notification] button') as HTMLButtonElement).click(); await flushPromises()
    const auth = useAuthStore()
    api.detail.mockResolvedValueOnce({ ...item, title: '新账号消息', body: '新账号正文' })
    auth.applyAuthResponse({ authenticated: true, user: { ...auth.user!, id: 2 } })
    await flushPromises()
    expect(document.body.textContent).toContain('新账号正文')
    release({ ...item, read_at: '2026-10-21T02:00:00Z' }); await flushPromises()
    expect(document.body.textContent).toContain('新账号正文')
    expect(document.body.textContent).not.toContain('通知当前不可访问，请重新打开卡片核对。')
    expect(router.push).not.toHaveBeenCalled()
  })
  it('没有业务目标的通知只展示服务端安全正文，可返回全部消息', async () => {
    api.detail.mockResolvedValueOnce({ ...item, title: '通知内容不可访问', body: '该业务内容当前不可访问。', target_accessible: false })
    route.query = { notification: id }; render(); await flushPromises()
    expect(document.body.textContent).toContain('该业务内容当前不可访问')
    expect(document.querySelector('[data-linked-notification] button')).toBeNull()
    ;(document.querySelector('.header-message-panel__footer button') as HTMLButtonElement).click(); await flushPromises()
    expect(api.inbox).toHaveBeenCalled()
    expect(document.querySelector('[data-linked-notification]')).toBeNull()
    expect(api.read).not.toHaveBeenCalled()
  })
  it('数字角标上限99+；打开不批量已读；Escape关闭并恢复焦点', async () => {
    const view = render(); await flushPromises()
    useNotificationsStore().unread = 105; await nextTick()
    expect(view.get('.header-messages__badge').text()).toBe('99+')
    await view.get('[data-message-toggle]').trigger('click'); await flushPromises()
    expect(document.querySelector('[role="dialog"]')).not.toBeNull()
    expect(document.activeElement?.getAttribute('aria-label')).toBe('关闭消息')
    expect(api.read).not.toHaveBeenCalled()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await nextTick()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(document.activeElement).toBe(view.get('[data-message-toggle]').element)
  })
  it('只在计数增加时短暂抖动；打开或650ms后停止', async () => {
    const view = render(); await flushPromises()
    expect(view.get('[data-message-toggle]').classes()).not.toContain('is-shaking')
    api.count.mockResolvedValueOnce(3); await useNotificationsStore().refreshUnread(); await nextTick()
    expect(view.get('[data-message-toggle]').classes()).toContain('is-shaking')
    await vi.advanceTimersByTimeAsync(650)
    expect(view.get('[data-message-toggle]').classes()).not.toContain('is-shaking')
    api.count.mockResolvedValueOnce(4); await useNotificationsStore().refreshUnread(); await nextTick()
    await view.get('[data-message-toggle]').trigger('click'); await flushPromises()
    expect(view.get('[data-message-toggle]').classes()).not.toContain('is-shaking')
  })
  it('减少动态时保留角标并禁止抖动', async () => {
    reduced = true; const view = render(); await flushPromises()
    api.count.mockResolvedValueOnce(3); await useNotificationsStore().refreshUnread(); await nextTick()
    expect(view.get('.header-messages__badge').text()).toBe('3')
    expect(view.get('[data-message-toggle]').classes()).not.toContain('is-shaking')
  })
  it('空、加载和失败分别呈现；错误不伪装空态', async () => {
    let release!: (value: unknown) => void
    api.inbox.mockReturnValueOnce(new Promise(resolve => { release = resolve }))
    const view = render(); await flushPromises(); await view.get('[data-message-toggle]').trigger('click')
    expect(document.body.textContent).toContain('正在加载消息')
    release({ data: [], count: 0, page: 1, page_size: 10 }); await flushPromises()
    expect(document.body.textContent).toContain('暂无消息')
    api.inbox.mockRejectedValueOnce(new Error('失败')); await useNotificationsStore().loadPage(); await nextTick()
    expect(document.body.textContent).toContain('消息加载失败'); expect(document.body.textContent).not.toContain('暂无消息')
  })
  it('未读数量失败有可读错误标识；点击单条后才导航且关闭气泡', async () => {
    const view = render(); await flushPromises()
    useNotificationsStore().countError = '未读数更新失败'; await nextTick()
    expect(view.get('[data-message-toggle]').attributes('aria-label')).toContain('失败')
    expect(view.find('.header-messages__error-dot').exists()).toBe(true)
    await view.get('[data-message-toggle]').trigger('click'); await flushPromises()
    ;(document.querySelector('.header-message-panel__item') as HTMLButtonElement).click(); await flushPromises()
    expect(api.read.mock.calls[0]?.[0]).toBe(id)
    expect(router.push).toHaveBeenCalledWith({ name: 'bom-preview', params: { bomId: id } })
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })
  it('导航被取消保留已读结果，清楚显示导航失败；组件卸载停止轮询', async () => {
    router.push.mockResolvedValue({ type: 4 })
    const view = render(); await flushPromises(); await view.get('[data-message-toggle]').trigger('click'); await flushPromises()
    ;(document.querySelector('.header-message-panel__item') as HTMLButtonElement).click(); await flushPromises()
    expect(document.body.textContent).toContain('消息已读，页面切换未完成')
    expect(useNotificationsStore().items[0]?.read_at).toBeTruthy()
    wrapper?.unmount(); wrapper = undefined
    const calls = api.count.mock.calls.length
    await vi.advanceTimersByTimeAsync(60_000)
    expect(api.count).toHaveBeenCalledTimes(calls)
  })
})
