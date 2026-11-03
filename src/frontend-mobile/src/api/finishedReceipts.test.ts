import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createFinishedReceipt, fetchFinishedReceiptOptions, fetchFinishedReceiptPreview } from './finishedReceipts'

const request = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/request', () => ({ apiClient: request }))
beforeEach(() => vi.resetAllMocks())
describe('成品入库接口契约', () => {
  it('预览按当前计划读取并保留服务端额度和ETag', async () => {
    const data = { schedule_product_id: 'plan', etag: '"one"', order_quantity: 100, maximum_receivable: 80,
      received_total: 20, remaining_receivable: 60, order_maximum: 100, reported_minimum: 80, receipt_date: '2026-11-02',
      actual_color: '', unit_name: '件', reporting_basis_ready: true, reporting_operations: [] }
    request.get.mockResolvedValueOnce({ data: { data } })
    const signal = new AbortController().signal
    expect(await fetchFinishedReceiptPreview('plan', signal)).toEqual(data)
    expect(request.get).toHaveBeenCalledWith('/api/v1/assembly-finished-receipts/preview/', { params: { schedule_product_id: 'plan' }, signal })
    request.get.mockResolvedValueOnce({ data: { data: { ...data, schedule_product_id: 'other' } } })
    await expect(fetchFinishedReceiptPreview('plan')).rejects.toThrow('入库预览不完整')
  })
  it('库位只请求按计划授权的手机接口，不请求库存总览', async () => {
    request.get.mockResolvedValueOnce({ data: { data: { warehouses: [], zones: [], locations: [] } } })
    await fetchFinishedReceiptOptions('plan')
    expect(request.get).toHaveBeenCalledWith('/api/v1/workshop-mobile/finished-receipt-options/', { params: { schedule_product_id: 'plan' }, signal: undefined })
  })
  it('只POST创建接口并传If-Match，允许原请求已被仓库确认的真实重放结果', async () => {
    const payload = { request_id: 'request', schedule_product_id: 'plan', location_id: 'location', receipt_date: '2026-11-02', received_quantity: 10, quantity_per_box: null, actual_color: '蓝色', remark: '' }
    const result = { id: 'receipt', receipt_number: 'FG-TEST', status: 'CONFIRMED', replayed: true }
    request.post.mockResolvedValueOnce({ data: { data: result } })
    expect(await createFinishedReceipt(payload, '"one"')).toEqual(result)
    expect(request.post).toHaveBeenCalledWith('/api/v1/assembly-finished-receipts/', payload, { headers: { 'If-Match': '"one"' }, timeout: 30000 })
    request.post.mockResolvedValueOnce({ data: { data: { id: 'receipt' } } })
    await expect(createFinishedReceipt(payload, '"one"')).rejects.toThrow('未收到完整入库结果')
  })
})
