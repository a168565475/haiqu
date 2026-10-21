import { beforeEach, describe, expect, it, vi } from 'vitest'
import { confirmSampleMaterialIssue } from './sampleMaterialIssue'

const post = vi.hoisted(() => vi.fn())
vi.mock('./request', () => ({ apiClient: { post } }))

beforeEach(() => { post.mockReset().mockResolvedValue({ data: { data: { available: true, status: 'ISSUED' } }, headers: { etag: 'done' } }) })

describe('全部领料接口契约', () => {
  it('只提交固定请求标识，不发送数量或行明细，重试保持原请求', async () => {
    const requestId = 'e9f80e27-2537-44f8-9015-b7ab786f6561'
    const first = await confirmSampleMaterialIssue('sample-1', 'preview-v1', requestId)
    await confirmSampleMaterialIssue('sample-1', 'preview-v1', requestId)
    expect(post).toHaveBeenCalledWith('/api/v1/sample-requests/sample-1/material-issue/confirm/',
      { request_id: requestId }, { headers: { 'If-Match': 'preview-v1' }, timeout: 30_000 })
    expect(post.mock.calls[1]).toEqual(post.mock.calls[0])
    expect(first).toEqual({ data: { available: true, status: 'ISSUED' }, etag: 'done' })
  })
})
