import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { confirmTubeReceipt, fetchTubeReceipt, fetchTubeReceiptCandidates, fetchTubeReceiptPreview, findTubeReceipt } from './tubeReceipts'
import type { TubeReceiptInput } from '@/types/tubeReceipts'

vi.mock('./request', () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }))
beforeEach(() => vi.resetAllMocks())

describe('D3实际接口契约', () => {
  it('待回货单使用服务端搜索、来源和页号，保留服务端总数', async () => {
    const data = { items: [{ id: '真实单' }], total: 51, page: 2, page_size: 50 }
    vi.mocked(apiClient.get).mockResolvedValue({ data: { data } })
    const params = { search: '甲厂', source_kind: 'PUBLIC_SEMI' as const, page: 2, page_size: 50 }
    expect(await fetchTubeReceiptCandidates(params)).toEqual(data)
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/tube-outsourcing-orders/receipt-candidates/', { params, timeout: 15000 })
  })
  it('预览读取唯一订单，所有目标仓库/库区/日期/经办人来自返回值', async () => {
    const data = { actor_name: '实际经办人', today: '2026-09-30', warehouses: [], zones: [] }
    vi.mocked(apiClient.get).mockResolvedValue({ data: { data } })
    expect(await fetchTubeReceiptPreview('order/1')).toEqual(data)
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/tube-outsourcing-orders/order%2F1/receipt-preview/', { timeout: 15000 })
  })
  it('整单唯一确认保留原UUID、全0的null位置和If-Match，不接分批接口', async () => {
    const payload: TubeReceiptInput = { client_request_id: 'same-uuid', receipt_date: '2026-09-30', warehouse_id: null, remark: '', lines: [{ order_line_id: 'line-1', received_quantity: '0', shortage_reason: '未收到', zone_id: null }] }
    const result = { receipt_number: '真实凭证', total_received_quantity: '0' }
    vi.mocked(apiClient.post).mockResolvedValue({ data: { data: result } })
    expect(await confirmTubeReceipt('order-1', payload, '"order:v2"')).toEqual(result)
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/tube-outsourcing-orders/order-1/confirm-receipt/', payload, { headers: { 'If-Match': '"order:v2"' }, timeout: 30000 })
  })
  it('未知请求和已结束凭证分别GET真实接口，不产生任何写入', async () => {
    const result = { receipt_number: '真实凭证' }; vi.mocked(apiClient.get).mockResolvedValue({ data: { data: result } })
    expect(await findTubeReceipt('order-1', 'same/uuid')).toEqual(result); expect(await fetchTubeReceipt('order-1')).toEqual(result)
    expect(apiClient.get).toHaveBeenNthCalledWith(1, '/api/v1/tube-outsourcing-orders/order-1/receipt-by-request/same%2Fuuid/', { timeout: 15000 })
    expect(apiClient.get).toHaveBeenNthCalledWith(2, '/api/v1/tube-outsourcing-orders/order-1/receipt/', { timeout: 15000 }); expect(apiClient.post).not.toHaveBeenCalled()
  })
  it('真实接口错误向上传递，不伪造成功或空结果', async () => {
    const error = new Error('拒绝访问'); vi.mocked(apiClient.get).mockRejectedValue(error)
    await expect(fetchTubeReceiptPreview('order-1')).rejects.toBe(error)
  })
})
