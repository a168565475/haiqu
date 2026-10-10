import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  changeConfirmedSalesOrder,
  confirmSalesOrder,
  fetchSalesOrder,
} from '@/api/salesOrders'
import { apiClient } from '@/api/request'

vi.mock('@/api/request', () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), defaults: {} },
}))

const mockedGet = vi.mocked(apiClient.get)
const mockedPost = vi.mocked(apiClient.post)

describe('销售订单 API', () => {
  beforeEach(() => {
    mockedGet.mockReset()
    mockedPost.mockReset()
  })

  it('读取订单详情时保留 ETag', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: { id: 'so-1' } }, headers: { etag: '"so-v1"' } })

    const result = await fetchSalesOrder('so-1')

    expect(result.etag).toBe('"so-v1"')
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/sales-orders/so-1/')
  })

  it('确认后变更携带完整控制字段和 ETag', async () => {
    const payload = {
      order: { lines: [], delivery_batches: [] },
      change_reason: '客户变更交期',
      customer_facing_change: true,
      change_evidence_file_id: 'file-1',
      pmc_impact_confirmed: true,
    }
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'so-1', version_number: 2 } }, headers: { etag: '"so-v2"' } })

    const result = await changeConfirmedSalesOrder('so-1', payload as never, '"so-v1"')

    expect(result.etag).toBe('"so-v2"')
    expect(mockedPost).toHaveBeenCalledWith(
      '/api/v1/sales-orders/so-1/confirmed-change/',
      payload,
      { headers: { 'If-Match': '"so-v1"' } },
    )
  })

  it('业务员确认订单不经过价格审批接口', async () => {
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'so-1', status: 'CONFIRMED' } }, headers: { etag: '"so-v2"' } })

    await confirmSalesOrder('so-1', '"so-v1"')

    expect(mockedPost).toHaveBeenCalledWith(
      '/api/v1/sales-orders/so-1/confirm/',
      {},
      { headers: { 'If-Match': '"so-v1"' } },
    )
  })
})
