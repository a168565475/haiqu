import { beforeEach, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { correctTubePlanRecord, dispatchTubePlan, fetchTubeOptions, fetchTubeSource, findTubePlanRecordCorrection, receiveTubePlan, updateTubePlanQuantity } from './tubeOutsourcing'

vi.mock('./request', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }))
beforeEach(() => { vi.resetAllMocks(); vi.mocked(apiClient.get).mockResolvedValue({ data: { data: {} } }) })

it('计划数量编辑只提交原明细数量并携带父单版本', async () => {
  const detail = { id: 'plan-1', is_plan: true, etag: 'v2' }
  const payload = { lines: [{ order_line_id: 'line-1', quantity: '2100' }] }
  vi.mocked(apiClient.patch).mockResolvedValue({ data: { data: detail } })
  expect(await updateTubePlanQuantity('plan/1', payload, 'v1')).toEqual(detail)
  expect(apiClient.patch).toHaveBeenCalledWith('/api/v1/tube-outsourcing-orders/plan%2F1/plan-quantity/', payload, { timeout: 30000, headers: { 'If-Match': 'v1' } })
})

it('管材选项保留原请求，裁片选项显式选择同接口类别', async () => {
  await fetchTubeOptions()
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/options/')
  await fetchTubeOptions('cutting')
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/options/', { params: { category: 'cutting' } })
})

it('裁片直发来源按工艺查询，同请求不伪造主库区', async () => {
  const params = { schedule_product_id: 'schedule-1', source_kind: 'SEWING' as const, craft_id: 'embroidery-1' }
  await fetchTubeSource(params)
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/source-context/', { params, timeout: 15000 })
})

it('分次外发与独立入库均提交原请求编号和If-Match版本', async () => {
  const detail = { id: 'plan-1', is_plan: true, etag: 'v2' }
  vi.mocked(apiClient.post).mockResolvedValue({ data: { data: detail } })
  const dispatch = { client_request_id: 'request-1', source_kind: 'METAL' as const, zone_id: null, actual_dispatch_date: '2026-10-29', remark: '', lines: [{ component_identity: 'part-1', quantity: '200', factory_id: 'factory-1', unit_price: '1.20' }] }
  expect(await dispatchTubePlan('plan-1', dispatch, 'v1')).toEqual(detail)
  expect(apiClient.post).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/plan-1/plan-dispatch/', dispatch, { timeout: 30000, headers: { 'If-Match': 'v1' } })
  const receipt = { client_request_id: 'request-2', receipt_date: '2026-10-29', warehouse_id: 'warehouse-1', remark: '', lines: [{ order_line_id: 'line-1', received_quantity: '200', zone_id: 'zone-1' }] }
  expect(await receiveTubePlan('plan-1', receipt, 'v2')).toEqual(detail)
  expect(apiClient.post).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/plan-1/plan-receipt/', receipt, { timeout: 30000, headers: { 'If-Match': 'v2' } })
})

it('记录更正使用父If-Match与原参数，按新请求编号查询独立回执', async () => {
  const detail = { id: 'plan-1', is_plan: true, etag: 'v3' }
  vi.mocked(apiClient.post).mockResolvedValue({ data: { data: detail } })
  const payload = { client_request_id: 'correction-1', record_kind: 'RECEIPT' as const, record_id: 'receipt-1', operation: 'DELETE' as const }
  expect(await correctTubePlanRecord('plan/1', payload, 'v2')).toEqual(detail)
  expect(apiClient.post).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/plan%2F1/plan-record-correction/', payload, { timeout: 30000, headers: { 'If-Match': 'v2' } })
  await findTubePlanRecordCorrection('plan/1', 'request/1', true)
  expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/tube-outsourcing-orders/plan%2F1/plan-record-correction-by-request/request%2F1/', { timeout: 15000, params: { warehouse_stage: 'all' } })
})
