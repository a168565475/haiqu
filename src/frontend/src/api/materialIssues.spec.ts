import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))

vi.mock('./request', () => ({ apiClient: request }))

import {
  confirmMaterialIssue,
  createMaterialIssue,
  fetchMaterialIssue,
  fetchMaterialRequirements,
  previewMaterialIssue,
  submitMaterialIssue,
  updateMaterialIssue,
} from './materialIssues'

const response = { data: { data: { id: 'issue-1' } }, headers: { etag: '"issue-1"' } }

beforeEach(() => {
  vi.clearAllMocks()
  request.get.mockResolvedValue(response)
  request.post.mockResolvedValue(response)
  request.patch.mockResolvedValue(response)
})

describe('生产领料耗时接口', () => {
  it('已加载领料单读取需求带issue_id，新建请求不带旧单口径', async () => {
    await fetchMaterialRequirements('task-1', 'product-1', 'workshop-1', 'issue-1', 'ASSEMBLY')
    await fetchMaterialRequirements('task-2', 'product-2', 'workshop-1', undefined, 'CUTTING')
    expect(request.get).toHaveBeenNthCalledWith(1, '/api/v1/material-issues/requirements/', {
      params: { production_task_id: 'task-1', product_line_id: 'product-1', workshop_id: 'workshop-1', issue_id: 'issue-1', plan_category: 'ASSEMBLY' }, timeout: 15000,
    })
    expect(request.get).toHaveBeenNthCalledWith(2, '/api/v1/material-issues/requirements/', {
      params: { production_task_id: 'task-2', product_line_id: 'product-2', workshop_id: 'workshop-1', plan_category: 'CUTTING' }, timeout: 15000,
    })
  })

  it('创建、更新和提交审核不使用全局五秒超时', async () => {
    await createMaterialIssue({ lines: [] })
    await updateMaterialIssue('issue-1', { lines: [] }, '"issue-1"')
    await submitMaterialIssue('issue-1', '"issue-1"')

    expect(request.post).toHaveBeenNthCalledWith(1, '/api/v1/material-issues/', { lines: [] }, { timeout: 30000 })
    expect(request.patch).toHaveBeenCalledWith('/api/v1/material-issues/issue-1/', { lines: [] }, {
      headers: { 'If-Match': '"issue-1"' }, timeout: 30000,
    })
    expect(request.post).toHaveBeenNthCalledWith(2, '/api/v1/material-issues/issue-1/submit/', {}, {
      headers: { 'If-Match': '"issue-1"' }, timeout: 30000,
    })
  })

  it('提交后详情加载使用独立十五秒超时', async () => {
    await fetchMaterialIssue('issue-1')
    expect(request.get).toHaveBeenCalledWith('/api/v1/material-issues/issue-1/', { timeout: 15000 })
  })

  it('出库预检和确认不使用全局五秒超时', async () => {
    await previewMaterialIssue('issue-1')
    await confirmMaterialIssue('issue-1', 'request-1', '"issue-1"')

    expect(request.post).toHaveBeenNthCalledWith(1, '/api/v1/material-issues/issue-1/preview-issue/', {}, {
      timeout: 15000,
    })
    expect(request.post).toHaveBeenNthCalledWith(2, '/api/v1/material-issues/issue-1/confirm-issue/', {
      request_id: 'request-1',
    }, {
      headers: { 'If-Match': '"issue-1"' }, timeout: 30000,
    })
  })
})
