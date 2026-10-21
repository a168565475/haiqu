import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getNotificationInbox, getNotificationTarget, getNotificationUnreadCount, markNotificationRead, notificationInboxError } from './notifications'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('./request', () => ({ apiClient: client }))
beforeEach(() => vi.resetAllMocks())
describe('个人收件API契约（测试替身）', () => {
  it('分页传page/page_size；GET携带取消信号', async () => {
    const signal = new AbortController().signal
    const data = { data: [], count: 0, page: 2, page_size: 10 }
    client.get.mockResolvedValueOnce({ data })
    expect(await getNotificationInbox(2, signal)).toEqual(data)
    expect(client.get).toHaveBeenCalledWith('/api/v1/notifications/inbox/', { timeout: 20000, params: { page: 2, page_size: 10 }, signal })
  })
  it('未读接口精确读取计数，拒绝缺失/负数/字符串响应', async () => {
    for (const count of [0, 105]) {
      client.get.mockResolvedValueOnce({ data: { unread_count: count } })
      expect(await getNotificationUnreadCount()).toBe(count)
    }
    for (const count of [undefined, -1, '0', 0.5]) {
      client.get.mockResolvedValueOnce({ data: { unread_count: count } })
      await expect(getNotificationUnreadCount()).rejects.toThrow('响应无效')
    }
  })
  it('拒绝非法页码和损坏分页响应，错误不能变成空列表', async () => {
    await expect(getNotificationInbox(0)).rejects.toThrow('页码无效')
    expect(client.get).not.toHaveBeenCalled()
    client.get.mockResolvedValueOnce({ data: { data: [], count: 0, page: 1, page_size: 0 } })
    await expect(getNotificationInbox()).rejects.toThrow('列表响应无效')
  })
  it('POST已读使用收件ID，复用Session/CSRF客户端；目标单独GET', async () => {
    const signal = new AbortController().signal
    const item = { id: 'recipient', read_at: 'now' }
    client.post.mockResolvedValueOnce({ data: { data: item } })
    expect(await markNotificationRead('recipient', signal)).toEqual(item)
    expect(client.post).toHaveBeenCalledWith('/api/v1/notifications/inbox/recipient/read/', undefined, { timeout: 20000, signal })
    const target = { route_name: 'bom-preview' }
    client.get.mockResolvedValueOnce({ data: { data: { target } } })
    expect(await getNotificationTarget('recipient', signal)).toEqual(target)
    expect(client.get).toHaveBeenCalledWith('/api/v1/notifications/inbox/recipient/target/', { timeout: 20000, signal })
  })
  it('个人403不使用管理文案，404区分不可访问，代理错误不泄漏', () => {
    const error = (status: number) => new AxiosError('错误', undefined, undefined, undefined, { status, data: '<secret>', headers: {}, config: {} as never, statusText: 'error' })
    expect(notificationInboxError(error(403), '失败')).toContain('当前身份')
    expect(notificationInboxError(error(404), '失败')).toContain('已删除')
    expect(notificationInboxError(error(500), '加载失败')).toBe('加载失败')
  })
})
