import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from './auth'
import { useNotificationsStore } from './notifications'
import type { NotificationItem } from '@/types/notifications'

const api = vi.hoisted(() => ({ inbox: vi.fn(), count: vi.fn(), read: vi.fn(), target: vi.fn() }))
vi.mock('@/api/notifications', async importOriginal => ({
  ...await importOriginal<typeof import('@/api/notifications')>(),
  getNotificationInbox: api.inbox, getNotificationUnreadCount: api.count,
  markNotificationRead: api.read, getNotificationTarget: api.target,
}))
const id = '12345678-1234-1234-1234-123456789abc'
const item: NotificationItem = { id, event_code: 'BOM_CONFIRMED', event_name: 'BOM确认', title: '测试消息', body: '测试正文',
  created_at: '2026-10-21T01:00:00Z', read_at: null, target: null, target_accessible: true, channel_status: {} }
const target = { target_key: 'bom-detail', object_id: id, route_name: 'bom-preview', params: { bomId: id } }
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); await nextTick() }
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((accept, decline) => { resolve = accept; reject = decline })
  return { promise, resolve, reject }
}
function login(userId = 1) {
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: userId, username: `employee${userId}`, display_name: '员工',
    employee: null, is_superuser: false, permissions: [], data_scope: 'NONE' } })
}
function httpError(status: number) {
  return new AxiosError('失败', undefined, undefined, undefined, { status, data: {}, headers: {}, statusText: 'error', config: {} as never })
}
beforeEach(() => {
  vi.useFakeTimers(); vi.resetAllMocks(); setActivePinia(createPinia()); login()
  api.count.mockResolvedValue(2)
  api.inbox.mockResolvedValue({ data: [item], count: 21, page: 1, page_size: 10 })
  api.read.mockResolvedValue({ ...item, read_at: '2026-10-21T02:00:00Z' })
  api.target.mockResolvedValue(target)
})
afterEach(() => { useNotificationsStore().stop(); vi.useRealTimers() })

describe('个人消息状态（测试替身，不是真实验收）', () => {
  it('首次计数不作为新消息；后续增加才发到达信号，30秒轮询且不重叠', async () => {
    const store = useNotificationsStore(); store.start(); await flush()
    expect(store.unread).toBe(2); expect(store.arrival).toBe(0)
    api.count.mockResolvedValue(3)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(store.arrival).toBe(1); expect(store.unread).toBe(3)
    let resolve!: (n: number) => void
    api.count.mockReturnValue(new Promise<number>(r => { resolve = r }))
    await vi.advanceTimersByTimeAsync(30_000)
    const calls = api.count.mock.calls.length
    await vi.advanceTimersByTimeAsync(90_000); void store.refreshUnread()
    expect(api.count).toHaveBeenCalledTimes(calls)
    resolve(3); await flush()
  })
  it('打开不批量已读，分页沿用服务端页码；关闭仍轮询未读', async () => {
    const store = useNotificationsStore(); store.start(); await flush(); await store.open()
    expect(api.read).not.toHaveBeenCalled()
    api.inbox.mockResolvedValueOnce({ data: [], count: 21, page: 2, page_size: 10 })
    await store.loadPage(2); expect(store.page).toBe(2)
    store.close(); const calls = api.inbox.mock.calls.length
    await vi.advanceTimersByTimeAsync(30_000)
    expect(api.inbox).toHaveBeenCalledTimes(calls)
  })
  it('请求失败保留未知或旧计数，不能伪装零条；重试可恢复', async () => {
    const store = useNotificationsStore()
    api.count.mockRejectedValueOnce(new Error('网络失败'))
    await store.refreshUnread(); expect(store.unread).toBeNull(); expect(store.countError).toContain('失败')
    await store.refreshUnread(); expect(store.unread).toBe(2)
    api.count.mockRejectedValueOnce(new Error('网络失败'))
    await store.refreshUnread(); expect(store.unread).toBe(2); expect(store.countError).toContain('过期')
  })
  it('换账号清空并忽略旧返回；新账号继续轮询', async () => {
    const store = useNotificationsStore()
    let resolve!: (n: number) => void
    api.count.mockReturnValueOnce(new Promise<number>(r => { resolve = r }))
    store.start(); await store.loadPage(); expect(store.items).toHaveLength(1)
    login(2); await flush(); expect(store.items).toEqual([]); expect(store.unread).toBe(2)
    resolve(99); await flush(); expect(store.unread).toBe(2)
  })
  it('退出清空消息、关闭面板、停止定时请求并忽略已读迟到响应', async () => {
    const store = useNotificationsStore(); store.start(); await flush(); await store.open()
    let resolve!: (row: NotificationItem) => void
    api.read.mockReturnValueOnce(new Promise<NotificationItem>(r => { resolve = r }))
    const pending = store.readAndResolve(item)
    useAuthStore().clearAuthentication()
    resolve({ ...item, read_at: 'read' }); await pending
    expect(store.items).toEqual([]); expect(store.unread).toBeNull(); expect(store.opened).toBe(false)
    expect(api.target).not.toHaveBeenCalled()
    const calls = api.count.mock.calls.length
    await vi.advanceTimersByTimeAsync(120_000); expect(api.count).toHaveBeenCalledTimes(calls)
  })
  it.each([401, 403])('%s清掉正文且停止轮询，不显示规则管理错误', async status => {
    const store = useNotificationsStore(); store.start(); await flush(); await store.open()
    api.count.mockRejectedValueOnce(httpError(status))
    await vi.advanceTimersByTimeAsync(30_000)
    expect(store.items).toEqual([]); expect(store.unread).toBeNull(); expect(store.blocked).toBe(true)
    expect(store.countError).not.toContain('规则管理')
    const calls = api.count.mock.calls.length
    await vi.advanceTimersByTimeAsync(120_000); expect(api.count).toHaveBeenCalledTimes(calls)
  })
  it('必须已读成功后重新请求目标，用收件ID；忽略列表中的目标', async () => {
    const store = useNotificationsStore(); await store.open()
    expect(await store.readAndResolve(item)).toEqual({ name: 'bom-preview', params: { bomId: id } })
    expect(api.read.mock.calls[0]?.[0]).toBe(id); expect(api.target.mock.calls[0]?.[0]).toBe(id)
    expect(api.read.mock.invocationCallOrder[0]).toBeLessThan(api.target.mock.invocationCallOrder[0]!)
    expect(store.items[0]?.read_at).toBeTruthy()
  })
  it('未读计数仍等待时已返回目标；计数到达后采用服务端数量而非本地减一', async () => {
    const store = useNotificationsStore(); await store.open()
    const count = deferred<number>()
    api.count.mockReturnValueOnce(count.promise)
    const resolved = vi.fn()
    const pending = store.readAndResolve(item).then(resolved)
    try {
      await flush()
      expect(api.target).toHaveBeenCalledWith(id, expect.any(AbortSignal))
      expect(resolved).toHaveBeenCalledWith({ name: 'bom-preview', params: { bomId: id } })
      expect(store.items[0]?.read_at).toBeTruthy()
      expect(store.countLoading).toBe(true)
      expect(store.unread).toBe(2)
      count.resolve(7); await flush()
      expect(store.unread).toBe(7)
      expect(store.countError).toBe('')
    } finally { count.resolve(7); await pending }
  })
  it('已读后的计数网络失败显示计数错误，目标仍能独立返回', async () => {
    const store = useNotificationsStore(); await store.open()
    const count = deferred<number>(); const destination = deferred<typeof target>()
    api.count.mockReturnValueOnce(count.promise); api.target.mockReturnValueOnce(destination.promise)
    const pending = store.readAndResolve(item)
    try {
      await flush()
      count.reject(new Error('网络失败')); await flush()
      expect(store.countError).toContain('失败')
      expect(store.unread).toBe(2); expect(store.blocked).toBe(false)
      expect(api.target).toHaveBeenCalledWith(id, expect.any(AbortSignal))
      destination.resolve(target)
      expect(await pending).toEqual({ name: 'bom-preview', params: { bomId: id } })
      expect(store.actionError).toBe('')
    } finally { count.resolve(2); destination.resolve(target); await pending }
  })
  it.each([401, 403])('计数先返回%s时清空并阻断，迟到的目标不得产生跳转', async status => {
    const store = useNotificationsStore(); await store.open()
    const count = deferred<number>(); const destination = deferred<typeof target>()
    api.count.mockReturnValueOnce(count.promise); api.target.mockReturnValueOnce(destination.promise)
    const pending = store.readAndResolve(item)
    try {
      await flush()
      expect(api.target).toHaveBeenCalledWith(id, expect.any(AbortSignal))
      count.reject(httpError(status)); await flush()
      expect(store.items).toEqual([]); expect(store.unread).toBeNull()
      expect(store.blocked).toBe(true); expect(store.opened).toBe(false)
      expect(store.countError).not.toBe('')
      destination.resolve(target)
      expect(await pending).toBeNull()
      expect(store.actionId).toBe('')
    } finally { count.resolve(2); destination.resolve(target); await pending }
  })
  it('计数仍等待时换账号，旧目标和旧计数都不能污染新账号', async () => {
    const store = useNotificationsStore(); await store.open()
    const count = deferred<number>(); const destination = deferred<typeof target>()
    api.count.mockReturnValueOnce(count.promise); api.target.mockReturnValueOnce(destination.promise)
    const pending = store.readAndResolve(item)
    try {
      await flush()
      expect(api.target).toHaveBeenCalledWith(id, expect.any(AbortSignal))
      login(2); await flush()
      expect(store.items).toEqual([]); expect(store.unread).toBeNull()
      api.count.mockResolvedValueOnce(5)
      await store.refreshUnread(); expect(store.unread).toBe(5)
      destination.resolve(target)
      expect(await pending).toBeNull()
      count.resolve(99); await flush()
      expect(store.items).toEqual([]); expect(store.unread).toBe(5)
      expect(store.countError).toBe(''); expect(store.blocked).toBe(false)
    } finally { count.resolve(99); destination.resolve(target); await pending }
  })
  it('标记已读失败不跳转；目标404不撤销已读并清除正文', async () => {
    const store = useNotificationsStore(); await store.open()
    api.read.mockRejectedValueOnce(new Error('POST失败'))
    expect(await store.readAndResolve(item)).toBeNull(); expect(api.target).not.toHaveBeenCalled()
    expect(store.actionError).toContain('标记已读失败')
    api.target.mockRejectedValueOnce(httpError(404))
    expect(await store.readAndResolve(item)).toBeNull(); expect(store.items[0]?.read_at).toBeTruthy()
    expect(store.items[0]?.body).not.toBe(item.body); expect(store.items[0]?.target_accessible).toBe(false)
  })
  it('失权列表项仍可标已读；不因不可访问标志跳过服务端重查', async () => {
    const store = useNotificationsStore(); api.target.mockRejectedValueOnce(httpError(404))
    await store.readAndResolve({ ...item, target_accessible: false })
    expect(api.read).toHaveBeenCalled(); expect(api.target).toHaveBeenCalled()
  })
  it('删除知悉按服务端历史权限标已读，保留正文且不请求伪造目标', async () => {
    const store = useNotificationsStore(); await store.open()
    const deleted = { ...item, event_code: 'WORK_REPORT_DELETED', body: '原记录已删除，仅供知悉。',
      read_at: '2026-10-21T02:00:00Z', target: null, target_accessible: false }
    api.read.mockResolvedValueOnce(deleted)
    expect(await store.readAndResolve({ ...deleted, read_at: null })).toBeNull()
    expect(api.read).toHaveBeenCalledWith(id, expect.any(AbortSignal))
    expect(api.target).not.toHaveBeenCalled()
    expect(store.items[0]?.body).toBe(deleted.body)
    expect(store.actionError).toBe('')
    expect(store.actionId).toBe('')
  })
})
