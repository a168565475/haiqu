import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createFinishedGoodsOutbound, fetchFinishedGoodsOutbound, fetchFinishedGoodsOutbounds } from '@/api/inventory'
import { apiClient } from '@/api/request'

vi.mock('@/api/request', () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }))
const mockedGet = vi.mocked(apiClient.get)
const mockedPost = vi.mocked(apiClient.post)

describe('成品出货单 API', () => {
  beforeEach(() => { mockedGet.mockReset(); mockedPost.mockReset() })

  it('使用独立列表和详情端点', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: { items: [], total: 0 } } }).mockResolvedValueOnce({ data: { data: { id: 'out-1' } } })
    await fetchFinishedGoodsOutbounds({ q: 'SC-1', page: 1 })
    await fetchFinishedGoodsOutbound('out-1')
    expect(mockedGet).toHaveBeenNthCalledWith(1, '/api/v1/finished-goods-inventory/outbounds/', { params: { q: 'SC-1', page: 1 } })
    expect(mockedGet).toHaveBeenNthCalledWith(2, '/api/v1/finished-goods-inventory/outbounds/out-1/')
  })

  it('无图片时提交 JSON 载荷并保留出货字段', async () => {
    const payload = { production_task_number: 'SC-1', responsible_employee_id: 'emp-1', shipment_date: '2026-10-21', loading_fee: '10', other_fee: '2', items: [] }
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'out-1' } } })
    await createFinishedGoodsOutbound(payload)
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/finished-goods-inventory/outbounds/', payload)
  })

  it('多张图片使用 multipart，明细保留为 JSON，并留出扫描时间', async () => {
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'out-1' } } })
    const items = [{ receipt_id: 'receipt-1', outbound_quantity: 2 }]
    const images = [new File(['a'], 'a.png'), new File(['b'], 'b.png')]
    await createFinishedGoodsOutbound({ items, responsible_employee_id: 'employee-1', loading_fee: 0 }, images)
    const [, data, config] = mockedPost.mock.calls[0]
    expect(data).toBeInstanceOf(FormData)
    expect((data as FormData).get('items')).toBe(JSON.stringify(items))
    expect((data as FormData).getAll('loading_images')).toEqual(images)
    expect(config).toEqual({ timeout: 120000 })
  })
})
