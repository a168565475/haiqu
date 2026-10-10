import { beforeEach, describe, expect, it, vi } from 'vitest'

import { updateComplaint, updateComplaintProgress, uploadComplaintImage } from '@/api/complaints'
import { apiClient } from '@/api/request'

vi.mock('@/api/request', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), defaults: {} } }))
const mockedPost = vi.mocked(apiClient.post)
const mockedPatch = vi.mocked(apiClient.patch)

describe('客诉写操作契约', () => {
  beforeEach(() => { mockedPost.mockReset(); mockedPatch.mockReset() })

  it('编辑携带 If-Match 并返回新 ETag', async () => {
    mockedPatch.mockResolvedValueOnce({ data: { data: { id: 'complaint-1' } }, headers: { etag: '"complaint-v2"' } })

    const result = await updateComplaint('complaint-1', { title: '更新后的客诉' }, '"complaint-v1"')

    expect(mockedPatch).toHaveBeenCalledWith('/api/v1/complaints/complaint-1/', { title: '更新后的客诉' }, { headers: { 'If-Match': '"complaint-v1"' } })
    expect(result.etag).toBe('"complaint-v2"')
  })

  it('更新进展保留进展编号，供失败图片重试时复用', async () => {
    mockedPost.mockResolvedValueOnce({
      data: { data: { id: 'complaint-1', status: 'SOLUTION_PLANNING' } },
      headers: { etag: '"complaint-v3"', 'complaint-progress-id': 'progress-9' },
    })

    const result = await updateComplaintProgress('complaint-1', {
      to_status: 'SOLUTION_PLANNING', progress_note: '方案已完成内部评审',
    }, '"complaint-v2"')

    expect(mockedPost).toHaveBeenCalledWith('/api/v1/complaints/complaint-1/progress/', {
      to_status: 'SOLUTION_PLANNING', progress_note: '方案已完成内部评审',
    }, { headers: { 'If-Match': '"complaint-v2"' } })
    expect(result.progressId).toBe('progress-9')
  })

  it('图片补传携带原进展编号，不重复提交状态推进', async () => {
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'attachment-1' } } })
    const file = new File(['image'], 'evidence.png', { type: 'image/png' })

    await uploadComplaintImage('complaint-1', file, 'progress-9', '现场证据')

    const [url, body, config] = mockedPost.mock.calls[0]!
    expect(url).toBe('/api/v1/complaints/complaint-1/attachments/')
    expect(body).toBeInstanceOf(FormData)
    expect((body as FormData).get('file')).toBe(file)
    expect((body as FormData).get('progress_id')).toBe('progress-9')
    expect((body as FormData).get('caption')).toBe('现场证据')
    expect(config).toEqual({ timeout: 120_000 })
  })
})
