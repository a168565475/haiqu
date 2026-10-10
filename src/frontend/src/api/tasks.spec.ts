import { beforeEach, describe, expect, it, vi } from 'vitest'

import { bulkComplete, bulkReassign, postTaskAction, previewBulkComplete, previewBulkReassign } from '@/api/tasks'
import { apiClient } from '@/api/request'

vi.mock('@/api/request', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
const mockedPost = vi.mocked(apiClient.post)

describe('任务中心写操作契约', () => {
  beforeEach(() => mockedPost.mockReset())

  it('批量完成预检和执行使用调用方传入的同一幂等键', async () => {
    const items = [{ id: 'task-1', version: 3 }]
    const eventId = 'b0d425fc-9ebf-49d1-8358-c1c9ae8b8df1'
    mockedPost
      .mockResolvedValueOnce({ data: { data: { action: 'COMPLETE', task_count: 1, customer_count: 1, overdue_count: 0, scheduled_reminder_count: 1 } } })
      .mockResolvedValueOnce({ data: { data: { action: 'COMPLETE', event_id: eventId, task_ids: ['task-1'], count: 1 } } })

    await previewBulkComplete(items, eventId)
    await bulkComplete(items, '已完成跟进', eventId)

    expect(mockedPost).toHaveBeenNthCalledWith(1, '/api/v1/tasks/bulk-complete/preview/', { items, event_id: eventId })
    expect(mockedPost).toHaveBeenNthCalledWith(2, '/api/v1/tasks/bulk-complete/', { items, reason: '已完成跟进', event_id: eventId })
  })

  it('批量转交预检和执行同时携带负责人、版本与同一幂等键', async () => {
    const items = [{ id: 'task-2', version: 7 }]
    const eventId = 'd3b64d20-152b-43d7-b9a5-8fbb868410a4'
    mockedPost
      .mockResolvedValueOnce({ data: { data: { action: 'REASSIGN', task_count: 1, customer_count: 1, overdue_count: 1, scheduled_reminder_count: 0 } } })
      .mockResolvedValueOnce({ data: { data: { action: 'REASSIGN', event_id: eventId, task_ids: ['task-2'], count: 1 } } })

    await previewBulkReassign(items, 'employee-2', eventId)
    await bulkReassign(items, 'employee-2', '工作交接', eventId)

    expect(mockedPost).toHaveBeenNthCalledWith(1, '/api/v1/tasks/bulk-reassign/preview/', { items, assignee_employee_id: 'employee-2', event_id: eventId })
    expect(mockedPost).toHaveBeenNthCalledWith(2, '/api/v1/tasks/bulk-reassign/', { items, assignee_employee_id: 'employee-2', reason: '工作交接', event_id: eventId })
  })

  it('单任务动作携带 If-Match 并保留新 ETag', async () => {
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'task-1' } }, headers: { etag: '"task-v4"' } })

    const result = await postTaskAction('task-1', 'complete', { note: '' }, '"task-v3"')

    expect(mockedPost).toHaveBeenCalledWith('/api/v1/tasks/task-1/complete/', { note: '' }, { headers: { 'If-Match': '"task-v3"' } })
    expect(result.etag).toBe('"task-v4"')
  })
})
