import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getNotificationSendRecords, notificationSendRecordsError } from './notifications'
import type { NotificationSendRecord, NotificationSendRecordQuery } from '@/types/notifications'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('./request', () => ({ apiClient: client }))
const row: NotificationSendRecord = { id: 'record-1', source: 'BUSINESS', recipient_name: '测试员工', event_code: 'BOM_CONFIRMED',
  event_name: 'BOM确认', title: 'BOM通知', body: '已确认\n请查看', status: 'ACCEPTED', error_code: '', attempt_count: 1,
  created_at: '2026-10-28T01:00:00Z', sent_at: '2026-10-28T01:00:01Z', finished_at: '2026-10-28T01:00:02Z' }
const query: NotificationSendRecordQuery = { source: 'BUSINESS', page: 1, page_size: 20 }
beforeEach(() => vi.resetAllMocks())

describe('发送记录只读API契约（测试替身）', () => {
  it('传递来源、分页、结果筛选与取消信号，不调用发送接口', async () => {
    const params = { ...query, page: 2, status: 'ACCEPTED' as const }
    const signal = new AbortController().signal
    const data = { data: [row], count: 21, page: 2, page_size: 20 }
    client.get.mockResolvedValue({ data })
    expect(await getNotificationSendRecords(params, signal)).toEqual(data)
    expect(client.get).toHaveBeenCalledWith('/api/v1/notifications/send-records/', { timeout: 20000, params, signal })
    expect(client.post).not.toHaveBeenCalled()
  })

  it.each([
    { page: 0 }, { page: 1.2 }, { page_size: 0 }, { page_size: 51 }, { source: 'UNKNOWN' }, { status: 'SUCCESS' },
    { source: 'RULE_PREVIEW', status: 'PENDING' }, { source: 'MESSAGE_TEST', status: 'SKIPPED' },
  ])('拒绝非法查询 %j，不请求接口', async override => {
    await expect(getNotificationSendRecords({ ...query, ...override } as NotificationSendRecordQuery)).rejects.toThrow('查询条件无效')
    expect(client.get).not.toHaveBeenCalled()
  })

  it.each([
    { data: null }, { count: -1 }, { page: 0 }, { page_size: 51 }, { data: [{ ...row, body: undefined }] },
    { data: [{ ...row, source: 'MESSAGE_TEST' }] }, { data: [{ ...row, status: 'DELIVERED' }] }, { data: [{ ...row, sent_at: undefined }] },
  ])('损坏响应 %j 不能显示为正常空列表', async override => {
    client.get.mockResolvedValue({ data: { data: [row], count: 1, page: 1, page_size: 20, ...override } })
    await expect(getNotificationSendRecords(query)).rejects.toThrow('响应无效')
  })

  it('保留未发送的null时间和历史空正文', async () => {
    const data = { data: [{ ...row, body: '', sent_at: null, finished_at: null }], count: 1, page: 1, page_size: 20 }
    client.get.mockResolvedValue({ data })
    expect(await getNotificationSendRecords(query)).toEqual(data)
  })

  it('权限错误使用发送记录文案，代理错误不泄露内部内容', () => {
    const error = (status: number) => new AxiosError('内部错误', undefined, undefined, undefined,
      { status, data: '<secret>', headers: {}, config: {} as never, statusText: 'error' })
    expect(notificationSendRecordsError(error(401))).toContain('重新登录')
    expect(notificationSendRecordsError(error(403))).toContain('该来源的发送记录')
    expect(notificationSendRecordsError(error(500))).toBe('发送记录加载失败，请稍后重试。')
  })
})
