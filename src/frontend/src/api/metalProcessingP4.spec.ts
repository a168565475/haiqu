import { beforeEach, expect, it, vi } from 'vitest'

import { adjustP4ExternalAllocation, cancelP4OriginalPending, closeP4OriginalOrder, closeP4Source, confirmP4OriginalGoodReturn, createP4UnsprayedReturn, fetchP4ExternalOrder, fetchP4Handoff, fetchP4Options, fetchP4OriginalOrder, fetchP4SourceClosurePreview, registerP4SourceCompletion } from './metalProcessingP4'

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('./request', () => ({ apiClient: client }))

beforeEach(() => vi.resetAllMocks())

it('退回接口携带来源 If-Match 并原样保留幂等请求标识', async () => {
  const payload = {
    request_id: 'retry-request', returned_pieces: 6, received_by_employee_id: 'employee',
    storage_location: '金工暂存架', return_date: '2026-09-23', remark: '',
  }
  client.post.mockResolvedValue({ data: { data: { id: 'return-1' } } })
  await createP4UnsprayedReturn('handoff-1', payload, '"source-version"')
  expect(client.post).toHaveBeenCalledWith(
    '/api/v1/metal-processing-handoffs/handoff-1/returns/', payload,
    { headers: { 'If-Match': '"source-version"' } },
  )
})

it('P4 选项使用本模块权限接口', async () => {
  client.get.mockResolvedValue({ data: { data: { original_orders: [] } } })
  expect(await fetchP4Options()).toEqual({ original_orders: [] })
  expect(client.get).toHaveBeenCalledWith('/api/v1/metal-processing-sources/options/')
})

it('原单合格回货读取上下文并用独立版本和请求标识提交', async () => {
  const context = { etag: '"original-return-2"', remaining_return_pieces: 14 }
  client.get.mockResolvedValue({ data: { data: { good_return_context: context } } })
  expect((await fetchP4Handoff('handoff/1')).good_return_context).toEqual(context)
  expect(client.get).toHaveBeenCalledWith('/api/v1/metal-processing-handoffs/handoff%2F1/')
  const payload = { request_id: 'same-request', good_pieces: 10, zone_id: 'zone', received_by_employee_id: 'employee', return_date: '2026-09-23', remark: '' }
  client.post.mockResolvedValue({ data: { data: context } })
  expect(await confirmP4OriginalGoodReturn('handoff/1', payload, '"original-return-1"')).toEqual(context)
  expect(client.post).toHaveBeenCalledWith('/api/v1/metal-processing-handoffs/handoff%2F1/good-returns/', payload, { headers: { 'If-Match': '"original-return-1"' } })
})

it('新外发调整使用本单最新版本，仅提交支数与请求标识', async () => {
  const order = { allocated_pieces: 8, etag: '"order-2"', allocation_context: { max_allocatable_pieces: 12 } }
  client.get.mockResolvedValue({ data: { data: order } })
  expect(await fetchP4ExternalOrder('order/1')).toEqual(order)
  expect(client.get).toHaveBeenCalledWith('/api/v1/metal-processing-external-orders/order%2F1/')
  const payload = { request_id: 'same-request', allocated_pieces: 10 }
  client.post.mockResolvedValue({ data: { data: { ...order, allocated_pieces: 10 } } })
  await adjustP4ExternalAllocation('order/1', payload, order.etag)
  expect(client.post).toHaveBeenCalledWith('/api/v1/metal-processing-external-orders/order%2F1/allocation/', payload, { headers: { 'If-Match': '"order-2"' } })
})

it('原始完成与来源结清使用各自接口和同来源版本', async () => {
  const source = { etag: '"source-2"' }
  client.get.mockResolvedValue({ data: { data: source } })
  expect(await fetchP4SourceClosurePreview('line/1')).toEqual(source)
  expect(client.get).toHaveBeenCalledWith('/api/v1/metal-processing-sources/line%2F1/closure-preview/')
  client.post.mockResolvedValue({ data: { data: source } })
  const completed = { request_id: 'completion', good_pieces: 10, completion_date: '2026-09-23' }
  await registerP4SourceCompletion('line/1', completed, '"source-1"')
  expect(client.post).toHaveBeenLastCalledWith('/api/v1/metal-processing-sources/line%2F1/completions/', completed, { headers: { 'If-Match': '"source-1"' } })
  const closed = { request_id: 'closure', remark: '本条来源加工已结束' }
  await closeP4Source('line/1', closed, '"source-2"')
  expect(client.post).toHaveBeenLastCalledWith('/api/v1/metal-processing-sources/line%2F1/close/', closed, { headers: { 'If-Match': '"source-2"' } })
})

it('原单收尾使用整单上下文版本，与金工来源及重加工新单接口分开', async () => {
  const context = { etag: '"original-1"', original_order_id: 'original/1' }
  client.get.mockResolvedValue({ data: { data: context } })
  expect(await fetchP4OriginalOrder('original/1')).toEqual(context)
  expect(client.get).toHaveBeenCalledWith('/api/v1/metal-processing-original-orders/original%2F1/')
  const payload = { request_id: 'close-request', remark: '保留差额结束本单' }
  client.post.mockResolvedValue({ data: { data: context } })
  await closeP4OriginalOrder('original/1', payload, context.etag)
  expect(client.post).toHaveBeenLastCalledWith('/api/v1/metal-processing-original-orders/original%2F1/close/', payload, { headers: { 'If-Match': '"original-1"' } })
})

it('取消原单待交余量只提交分配标识和原因，数量交由后端核定', async () => {
  const payload = { request_id: 'cancel-request', allocation_id: 'allocation-1', remark: '剩余计划取消' }
  client.post.mockResolvedValue({ data: { data: {} } })
  await cancelP4OriginalPending('original-1', payload, '"original-2"')
  expect(client.post).toHaveBeenCalledWith('/api/v1/metal-processing-original-orders/original-1/cancel-pending/', payload, { headers: { 'If-Match': '"original-2"' } })
})
