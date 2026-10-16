import { beforeEach, describe, expect, it, vi } from 'vitest'

import { postTaskAction } from '@/api/tasks'
import { apiClient } from '@/api/request'

vi.mock('@/api/request', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }))
const mockedPost = vi.mocked(apiClient.post)

describe('任务中心写操作契约', () => {
  beforeEach(() => mockedPost.mockReset())

  it('单任务动作携带 If-Match 并保留新 ETag', async () => {
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'task-1' } }, headers: { etag: '"task-v4"' } })

    const result = await postTaskAction('task-1', 'complete', { note: '' }, '"task-v3"')

    expect(mockedPost).toHaveBeenCalledWith('/api/v1/tasks/task-1/complete/', { note: '' }, { headers: { 'If-Match': '"task-v3"' } })
    expect(result.etag).toBe('"task-v4"')
  })
})
