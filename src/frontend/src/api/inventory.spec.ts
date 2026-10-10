import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  confirmMaterialQuality,
  createMaterialReceiving,
  fetchMaterialInboundDetails,
  fetchMaterialQualityBatch,
  fetchMaterialQualityBatches,
} from '@/api/inventory'
import { apiClient } from '@/api/request'

vi.mock('@/api/request', () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }))

const mockedGet = vi.mocked(apiClient.get)
const mockedPost = vi.mocked(apiClient.post)

describe('材料采购入库 API', () => {
  beforeEach(() => { mockedGet.mockReset(); mockedPost.mockReset() })

  it('仓库收货使用独立的待质检接口', async () => {
    const payload = { inbound_date: '2026-09-09', items: [{ purchase_order_line_id: 'line-1' }] }
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'inbound-1', status: 'PENDING_QUALITY' } } })

    await createMaterialReceiving(payload)

    expect(mockedPost).toHaveBeenCalledWith('/api/v1/material-inventory/receivings/', payload)
  })

  it('品质确认接口完整传递到货快照和退货数量', async () => {
    const payload = { items: [{ line_id: 'line-1', expected_received_quantity: '10.0000', return_quantity: '1.0000', quality_remark: '表面损伤' }] }
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'inbound-1', status: 'CONFIRMED' } } })

    await confirmMaterialQuality('inbound-1', payload)

    expect(mockedPost).toHaveBeenCalledWith('/api/v1/material-inventory/quality-batches/inbound-1/confirm/', payload)
  })

  it('待检列表、单批详情和只读入库明细使用不同端点', async () => {
    mockedGet
      .mockResolvedValueOnce({ data: { data: [] } })
      .mockResolvedValueOnce({ data: { data: { id: 'inbound-1' } } })
      .mockResolvedValueOnce({ data: { data: [] } })

    await fetchMaterialQualityBatches({ q: 'CLRK' })
    await fetchMaterialQualityBatch('inbound-1')
    await fetchMaterialInboundDetails({ warehouse_id: 'warehouse-1' })

    expect(mockedGet).toHaveBeenNthCalledWith(1, '/api/v1/material-inventory/quality-batches/', { params: { q: 'CLRK' } })
    expect(mockedGet).toHaveBeenNthCalledWith(2, '/api/v1/material-inventory/quality-batches/inbound-1/')
    expect(mockedGet).toHaveBeenNthCalledWith(3, '/api/v1/material-inventory/inbound-details/', { params: { warehouse_id: 'warehouse-1' } })
  })
})
