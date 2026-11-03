import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createPurchaseBatch, createPurchaseGroup, fetchPurchaseGroupFilterOptions, fetchPurchaseGroups, fetchVersionedPurchaseGroup } from './purchaseGroups'
import { apiClient } from './request'
import type { PurchaseBatchInput } from '@/types/purchaseGroup'

vi.mock('./request', () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }))

const mockedGet = vi.mocked(apiClient.get)
const mockedPost = vi.mocked(apiClient.post)

function batchPayload(batchType: PurchaseBatchInput['batch_type'] = 'NORMAL'): PurchaseBatchInput {
  return {
    request_id: '309fa8e1-e55a-4b34-a328-51122c941e9a',
    batch_type: batchType,
    currency_id: 'currency-1',
    lines: [{ purchase_group_line_id: 'selected-line-2', actual_purchase_quantity: '120.0001', unit_price: '2.1234' }],
  }
}

describe('采购总单 API 契约', () => {
  beforeEach(() => {
    mockedGet.mockReset()
    mockedPost.mockReset()
  })

  it('任务筛选读取全部可见父单选项，不复用子采购单或创建选项', async () => {
    const options = { production_tasks: [{ id: 'empty-task', task_number: 'EMPTY', order_number: 'SAVED' }] }
    mockedGet.mockResolvedValueOnce({ data: { data: options } })
    expect(await fetchPurchaseGroupFilterOptions()).toEqual(options)
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/purchase-groups/filter-options/')
  })

  it('分页和任务筛选原样提交，保留超过100%的进度及UNKNOWN的null', async () => {
    const body = {
      data: [{ id: 'group-1', progress: { status: 'UNKNOWN', lines: [
        { progress_percent: '120.0001', accepted_quantity: '120.0001', is_satisfied: true },
        { progress_percent: null, accepted_quantity: null, is_satisfied: false, compatibility_issues: ['UNIT_MISSING'] },
      ] } }],
      meta: { page: 2, page_size: 20, total: 21, total_pages: 2 },
    }
    mockedGet.mockResolvedValueOnce({ data: body })

    expect(await fetchPurchaseGroups({ page: 2, page_size: 20, production_task_id: 'task-1' })).toEqual(body)
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/purchase-groups/', {
      params: { page: 2, page_size: 20, production_task_id: 'task-1' },
    })
  })

  it('详情读取父ETag并保留后端达标判断，不用四舍五入100%覆盖false', async () => {
    const group = { id: 'group-1', progress: { status: 'PURCHASING', lines: [
      { progress_percent: '100.0000', is_satisfied: false },
    ] } }
    mockedGet.mockResolvedValueOnce({ data: { data: group }, headers: { etag: '"group-v1"' } })

    const result = await fetchVersionedPurchaseGroup('group-1')

    expect(result).toEqual({ data: group, etag: '"group-v1"' })
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/purchase-groups/group-1/')
  })

  it('建立总单提交完整来源版本并接收父ETag', async () => {
    const payload = { production_task_id: 'task-1', bom_id: 'bom-1', source_revision: 'a'.repeat(64) }
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'group-1' } }, headers: { etag: '"group-v1"' } })

    expect((await createPurchaseGroup(payload)).etag).toBe('"group-v1"')
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/purchase-groups/', payload)
  })

  it.each(['NORMAL', 'SUPPLEMENT'] as const)('%s批次保留所选子集、超建议量和精度，携带父版本而接收子版本', async (batchType) => {
    const payload = batchPayload(batchType)
    mockedPost.mockResolvedValueOnce({
      data: { data: { id: 'batch-1', purchase_group_id: 'group-1', batch_type: batchType } },
      headers: { etag: '"batch-v1"' },
    })

    const result = await createPurchaseBatch('group-1', payload, '"group-v1"')

    expect(mockedPost).toHaveBeenCalledWith('/api/v1/purchase-groups/group-1/batches/', payload, {
      headers: { 'If-Match': '"group-v1"' },
    })
    expect(payload.lines).toHaveLength(1)
    expect(payload.lines[0]?.actual_purchase_quantity).toBe('120.0001')
    expect(result.data.purchase_group_id).toBe('group-1')
    expect(result.etag).toBe('"batch-v1"')
  })

  it('管材只传选择行和根数，不根据前端浮点值重算米数或改建议量', async () => {
    const payload: PurchaseBatchInput = {
      ...batchPayload(), lines: [{ purchase_group_line_id: 'pipe-line-1', actual_bar_count: '12' }],
    }
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'batch-1' } }, headers: {} })

    await createPurchaseBatch('group-1', payload, '"group-v1"')

    expect(mockedPost.mock.calls[0]?.[1]).toEqual(payload)
    expect(payload.lines[0]).not.toHaveProperty('actual_purchase_quantity')
    expect(payload.lines[0]).not.toHaveProperty('raw_bar_length_m')
  })

  it('同一次提交重试继续使用调用方保存的UUID，不另造采购批次请求', async () => {
    const payload = batchPayload()
    mockedPost.mockResolvedValue({ data: { data: { id: 'same-batch' } }, headers: { etag: '"batch-v1"' } })

    const first = await createPurchaseBatch('group-1', payload, '"group-v1"')
    const retry = await createPurchaseBatch('group-1', payload, '"group-v1"')

    expect(first.data.id).toBe(retry.data.id)
    expect(mockedPost.mock.calls.map((call) => (call[1] as PurchaseBatchInput).request_id)).toEqual([
      payload.request_id, payload.request_id,
    ])
  })

  it.each([403, 409, 412, 428])('后端%s错误原样抛出，既不伪装成功也不自动重试', async (status) => {
    const error = { response: { status, data: { error: { code: 'CONFLICT', message: '服务端错误', request_id: 'trace-1' } } } }
    mockedPost.mockRejectedValueOnce(error)

    await expect(createPurchaseBatch('group-1', batchPayload(), '"group-v1"')).rejects.toBe(error)
    expect(mockedPost).toHaveBeenCalledTimes(1)
  })

  it('缺失父ETag不伪造版本，由后端428拒绝并交调用方处理', async () => {
    const error = { response: { status: 428 } }
    mockedPost.mockRejectedValueOnce(error)

    await expect(createPurchaseBatch('group-1', batchPayload(), '')).rejects.toBe(error)
    expect(mockedPost.mock.calls[0]?.[2]).toEqual({ headers: {} })
  })
})
