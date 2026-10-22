import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchSampleWarehouseReview, saveSampleWarehouseReview } from './sampleWarehouse'
import { apiClient } from './request'
vi.mock('./request', () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }))
describe('样品仓库接口边界', () => {
  beforeEach(() => vi.clearAllMocks())
  it('读取仓库专用接口，拒绝没有版本的写入', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { data: { available: true, etag: 'v1' } } })
    expect(await fetchSampleWarehouseReview('sample')).toMatchObject({ available: true })
    await expect(saveSampleWarehouseReview({ sampleId: 'sample', etag: '', draft: { lines: [], notes: '' }, submit: true })).rejects.toThrow('版本')
  })
  it('仓库写入只发送行标识、供料数量和备注，不覆盖需求字段', async () => {
    vi.mocked(apiClient.put).mockResolvedValue({ data: { data: { available: true } } })
    await saveSampleWarehouseReview({ sampleId: 'sample', etag: 'v1', submit: true, draft: { lines: [{ key: 'k', category: 'tube', name: '圆管', specification: '25', material: '铝', color: '黑', quantity: '10', unitId: 'u', unitLabel: '米', notes: '', supplyQuantity: '3' }], notes: '仓库备注' } })
    expect(apiClient.put).toHaveBeenCalledWith('/api/v1/sample-requests/sample/warehouse-review/', { draft: { lines: [{ key: 'k', supplyQuantity: '3', inventoryAllocations: [] }], notes: '仓库备注' }, submit: true }, { headers: { 'If-Match': 'v1' } })
  })
})
