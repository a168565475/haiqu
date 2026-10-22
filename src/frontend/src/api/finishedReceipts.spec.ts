import { expect, it, vi } from 'vitest'
import type { FinishedGoodsInventoryRow } from '@/types/inventory'
import { confirmAssemblyReceiptRecord, deleteAssemblyReceiptRecord, fetchFinishedLocations } from './finishedReceipts'

const get = vi.hoisted(() => vi.fn())
const post = vi.hoisted(() => vi.fn())
const remove = vi.hoisted(() => vi.fn())
vi.mock('./request', () => ({ apiClient: { get, post, delete: remove } }))

it('库位详情携带与库存汇总一致的样品排除参数', async () => {
  get.mockResolvedValue({ data: { data: { items: [] } } })
  const row = { product_id: 'product', unit_id: 'unit', zone_id: 'zone', product_number: 'P001',
    product_code: '', product_name: '成品', item_number: 'I001', category: '', specification: '', actual_color: '黑色' } as FinishedGoodsInventoryRow
  expect(await fetchFinishedLocations(row)).toEqual([])
  expect(get).toHaveBeenCalledWith('/api/v1/finished-goods-records/locations/', expect.objectContaining({
    params: expect.objectContaining({ exclude_sample: true, product_id: 'product', zone_id: 'zone' }),
  }))
})

it('仓管确认成品待入库记录使用独立确认动作', async () => {
  post.mockResolvedValue({ data: { data: { id: 'receipt-1', receipt_number: 'CPRK-001', status: 'CONFIRMED', replayed: false } } })
  await expect(confirmAssemblyReceiptRecord('receipt-1')).resolves.toMatchObject({ status: 'CONFIRMED' })
  expect(post).toHaveBeenCalledWith('/api/v1/assembly-finished-receipts/receipt-1/confirm/', undefined, { timeout: 30000 })
})

it('删除装配待入库记录携带If-Match并接受204空响应', async () => {
  remove.mockResolvedValue({ status: 204 })
  await expect(deleteAssemblyReceiptRecord('receipt-1', '"v1"')).resolves.toBeUndefined()
  expect(remove).toHaveBeenCalledWith('/api/v1/assembly-finished-receipts/receipt-1/', { headers: { 'If-Match': '"v1"' }, timeout: 30000 })
})
