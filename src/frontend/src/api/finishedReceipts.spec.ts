import { expect, it, vi } from 'vitest'
import type { FinishedGoodsInventoryRow } from '@/types/inventory'
import { fetchFinishedLocations } from './finishedReceipts'

const get = vi.hoisted(() => vi.fn())
vi.mock('./request', () => ({ apiClient: { get } }))

it('库位详情携带与库存汇总一致的样品排除参数', async () => {
  get.mockResolvedValue({ data: { data: { items: [] } } })
  const row = { product_id: 'product', unit_id: 'unit', zone_id: 'zone', product_number: 'P001',
    product_code: '', product_name: '成品', item_number: 'I001', category: '', specification: '', actual_color: '黑色' } as FinishedGoodsInventoryRow
  expect(await fetchFinishedLocations(row)).toEqual([])
  expect(get).toHaveBeenCalledWith('/api/v1/finished-goods-records/locations/', expect.objectContaining({
    params: expect.objectContaining({ exclude_sample: true, product_id: 'product', zone_id: 'zone' }),
  }))
})
