import { beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { fetchOutsourcingOrder, fetchOutsourcingOptions, fetchOutsourcingReconciliation, outsourcingProductImageUrl } from './outsourcing'
import { fetchTubeOrder, findTubeAction } from './tubeOutsourcing'
import { fetchTubeReceiptPreview, findTubeReceipt } from './tubeReceipts'
import { fetchP4Options, fetchP4Source, fetchP4Handoff, fetchP4OriginalOrder, fetchP4ExternalOrder } from './metalProcessingP4'

vi.mock('./request', () => ({ apiClient: { get: vi.fn(), defaults: { baseURL: 'http://localhost:8000' } } }))
beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(apiClient.get).mockResolvedValue({ data: { data: {} }, headers: {} })
})

it('仓库产品图使用同一单据的动作读取范围', () => {
  expect(outsourcingProductImageUrl('order/1', 'file/1', true)).toBe('http://localhost:8000/api/v1/outsourcing-orders/order%2F1/product-files/file%2F1/?warehouse_stage=all')
  expect(outsourcingProductImageUrl('order/1', 'file/1')).toBe('http://localhost:8000/api/v1/outsourcing-orders/order%2F1/product-files/file%2F1/')
})

it.each([
  ['普通详情', fetchOutsourcingOrder, '/api/v1/outsourcing-orders/order%2F1/'],
  ['普通核对', fetchOutsourcingReconciliation, '/api/v1/outsourcing-orders/order%2F1/reconciliation/'],
  ['P4来源', fetchP4Source, '/api/v1/metal-processing-sources/order%2F1/'],
  ['P4交接', fetchP4Handoff, '/api/v1/metal-processing-handoffs/order%2F1/'],
  ['P4原单', fetchP4OriginalOrder, '/api/v1/metal-processing-original-orders/order%2F1/'],
  ['P4返工单', fetchP4ExternalOrder, '/api/v1/metal-processing-external-orders/order%2F1/'],
] as const)('%s的仓库读取显式传范围，原车间请求保持不变', async (_label, read, path) => {
  await read('order/1')
  expect(apiClient.get).toHaveBeenLastCalledWith(path)
  await read('order/1', true)
  expect(apiClient.get).toHaveBeenLastCalledWith(path, { params: { warehouse_stage: 'all' } })
})

it.each([
  [fetchOutsourcingOptions, '/api/v1/outsourcing-orders/options/'],
  [fetchP4Options, '/api/v1/metal-processing-sources/options/'],
] as const)('仓库选项读取带相同范围标记', async (read, path) => {
  await read(true)
  expect(apiClient.get).toHaveBeenLastCalledWith(path, { params: { warehouse_stage: 'all' } })
})

it('管材详情、入库预览及原请求回查带仓库范围，保留超时配置', async () => {
  await fetchTubeOrder('order/1', true)
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/order%2F1/', { timeout: 15000, params: { warehouse_stage: 'all' } })
  await fetchTubeReceiptPreview('order/1', true)
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/order%2F1/receipt-preview/', { timeout: 15000, params: { warehouse_stage: 'all' } })
  await findTubeAction('order/1', 'request/1', true)
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/order%2F1/action-by-request/request%2F1/', { timeout: 15000, params: { warehouse_stage: 'all' } })
  await findTubeReceipt('order/1', 'request/1', true)
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/order%2F1/receipt-by-request/request%2F1/', { timeout: 15000, params: { warehouse_stage: 'all' } })
})
