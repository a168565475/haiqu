import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/utils/request'
import { submitMaterialIssue, updateMaterialIssue } from './materialIssues'
import type { IssueWritePayload } from '@/types/materialIssue'

vi.mock('@/utils/request', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }))
beforeEach(() => vi.resetAllMocks())
const response = (status: string) => ({ data: { data: { id: 'issue-1', status } }, headers: { etag: '"v2"' } })

describe('手机领料提交结果核对', () => {
  it('写请求必须带If-Match，缺失时不发送', async () => {
    await expect(submitMaterialIssue('issue-1', '')).rejects.toThrow('版本信息缺失')
    await expect(updateMaterialIssue('issue-1', {} as IssueWritePayload, '')).rejects.toThrow('版本信息缺失')
    expect(apiClient.post).not.toHaveBeenCalled()
    expect(apiClient.patch).not.toHaveBeenCalled()
  })
  it('超时但原单已待审核时返回真实状态，不再写入', async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error('timeout'))
    vi.mocked(apiClient.get).mockResolvedValue(response('PENDING_REVIEW'))
    const reconcile = vi.fn()
    const result = await submitMaterialIssue('issue-1', '"v1"', reconcile)
    expect(result.data.status).toBe('PENDING_REVIEW')
    expect(apiClient.post).toHaveBeenCalledTimes(1)
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/material-issues/issue-1/submit/', {}, expect.objectContaining({ headers: { 'If-Match': '"v1"' } }))
    expect(reconcile).toHaveBeenCalledWith(expect.objectContaining({ etag: '"v2"' }))
  })
  it('仍是草稿时保留原错误和最新版本，不报成功', async () => {
    const failure = new Error('库存不足')
    vi.mocked(apiClient.post).mockRejectedValue(failure)
    vi.mocked(apiClient.get).mockResolvedValue(response('DRAFT'))
    const reconcile = vi.fn()
    await expect(submitMaterialIssue('issue-1', '"v1"', reconcile)).rejects.toBe(failure)
    expect(reconcile).toHaveBeenCalledWith(expect.objectContaining({ etag: '"v2"' }))
  })
  it('核对也失败时保留提交错误，不假定成功', async () => {
    const failure = new Error('提交结果未知')
    vi.mocked(apiClient.post).mockRejectedValue(failure)
    vi.mocked(apiClient.get).mockRejectedValue(new Error('网络未恢复'))
    await expect(submitMaterialIssue('issue-1', '"v1"')).rejects.toBe(failure)
    expect(apiClient.post).toHaveBeenCalledTimes(1)
  })
})
