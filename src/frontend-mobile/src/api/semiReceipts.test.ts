import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { SemiReceiptCategory, SemiReceiptPayload, SemiReceiptPreview } from '@/types/semiReceipts'
import { createSemiReceipt, fetchSemiReceiptPreview, findSemiReceipt } from './semiReceipts'

const request = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('@/utils/request', () => ({ apiClient: request }))
const plan = '11111111-1111-4111-8111-111111111111'
const lineId = '22222222-2222-4222-8222-222222222222'
const zoneId = '33333333-3333-4333-8333-333333333333'
const requestId = '44444444-4444-4444-8444-444444444444'
const receiptId = '55555555-5555-4555-8555-555555555555'
const result = { receipt_id: receiptId, receipt_number: 'SEMI-UNIT', status: 'PENDING', replayed: false, record_ids: [] }

function preview(category: SemiReceiptCategory): SemiReceiptPreview {
  return {
    schedule_product_id: plan, plan_category: category, etag: '"original-preview"', production_order: 'TASK-UNIT',
    product: '产品', order_quantity: '100', actor: '班组长', receipt_date: '2028-02-29', excluded: ['不适用部位'],
    zones: [{ id: zoneId, warehouse: '半成品仓', name: '一区' }],
    lines: [{ bom_line_id: lineId, component_key: 'component-one', usage: 'INTERNAL', stage: '完成',
      attributes: { part_name: '部位一', material: '原料', color: '', unit_name: category === 'METAL' ? '支' : '套' },
      required: '100.0000', received: '20.0000', can_receive: '30.0000',
      ...(category === 'METAL' ? { metal_processing: {
        basis_ready: true, blockers: [], future_blockers: [], operations: [], schemes: [], as_of: '2028-02-29',
        issued: '80', reported_minimum: '50', dispatched: '0', reserved: '0', first_output_limit: '50', current_remaining: '30', can_receive: '30',
      } } : {}),
    }],
    ...(category === 'METAL' ? { metal_processing: { blockers: [], future_blockers: [], as_of: '2028-02-29' } } : {}),
  }
}

beforeEach(() => vi.resetAllMocks())

describe('金工和车缝入库API契约', () => {
  it.each(['METAL', 'SEWING'] as const)('%s读取原ERP预览，保留真实额度、库区与ETag', async category => {
    const data = preview(category)
    request.get.mockResolvedValueOnce({ data: { data } })
    const signal = new AbortController().signal
    expect(await fetchSemiReceiptPreview(plan, category, signal)).toBe(data)
    expect(request.get).toHaveBeenCalledExactlyOnceWith('/api/v1/semi-finished-receipts/preview/', {
      params: { schedule_product_id: plan, plan_category: category }, signal, timeout: 15000,
    })
  })

  it.each([
    ['缺少响应', () => undefined],
    ['计划变化', (data: SemiReceiptPreview) => ({ ...data, schedule_product_id: requestId })],
    ['类别变化', (data: SemiReceiptPreview) => ({ ...data, plan_category: 'METAL' })],
    ['缺少ETag', (data: SemiReceiptPreview) => ({ ...data, etag: '' })],
    ['无效日期', (data: SemiReceiptPreview) => ({ ...data, receipt_date: '2027-02-29' })],
    ['无效排除说明', (data: SemiReceiptPreview) => ({ ...data, excluded: [7] })],
    ['无效库区', (data: SemiReceiptPreview) => ({ ...data, zones: [{ id: 'wrong', warehouse: '仓库', name: '一区' }] })],
    ['缺少库区名称', (data: SemiReceiptPreview) => ({ ...data, zones: [{ id: zoneId, warehouse: '仓库' }] })],
    ['部位来源无效', (data: SemiReceiptPreview) => ({ ...data, lines: [{ ...data.lines[0], bom_line_id: 'wrong' }] })],
    ['单位变化', (data: SemiReceiptPreview) => ({ ...data, lines: [{ ...data.lines[0], attributes: { ...data.lines[0]!.attributes, unit_name: '米' } }] })],
    ['小数额度', (data: SemiReceiptPreview) => ({ ...data, lines: [{ ...data.lines[0], can_receive: '1.5' }] })],
    ['超出14位额度', (data: SemiReceiptPreview) => ({ ...data, lines: [{ ...data.lines[0], can_receive: '100000000000000' }] })],
    ['负数额度', (data: SemiReceiptPreview) => ({ ...data, lines: [{ ...data.lines[0], can_receive: '-1' }] })],
    ['重复部位', (data: SemiReceiptPreview) => ({ ...data, lines: [data.lines[0], data.lines[0]] })],
  ] as const)('拒绝不完整或串来源预览：%s', async (_name, change) => {
    request.get.mockResolvedValueOnce({ data: { data: change(preview('SEWING')) } })
    await expect(fetchSemiReceiptPreview(plan, 'SEWING')).rejects.toThrow('半成品入库预览不完整或来源已变化')
  })

  it.each([
    (data: SemiReceiptPreview) => ({ ...data, metal_processing: undefined }),
    (data: SemiReceiptPreview) => ({ ...data, lines: [{ ...data.lines[0], metal_processing: undefined }] }),
    (data: SemiReceiptPreview) => ({ ...data, lines: [{ ...data.lines[0], metal_processing: { ...data.lines[0]!.metal_processing, basis_ready: 'yes' } }] }),
  ])('金工必须具有当前加工数量依据，不能把旧口径预览当成新流程', async change => {
    request.get.mockResolvedValueOnce({ data: { data: change(preview('METAL')) } })
    await expect(fetchSemiReceiptPreview(plan, 'METAL')).rejects.toThrow('缺少新版金工加工数量依据')
  })

  it('保留零额度及明确的加工阻断信息，交由页面展示', async () => {
    const data = preview('METAL')
    data.lines[0]!.can_receive = '0.0000'
    data.lines[0]!.metal_processing!.basis_ready = false
    data.lines[0]!.metal_processing!.blockers = ['报工依据缺失']
    data.metal_processing!.future_blockers = ['未来日期报工']
    request.get.mockResolvedValueOnce({ data: { data } })
    expect(await fetchSemiReceiptPreview(plan, 'METAL')).toBe(data)
  })

  it.each(['METAL', 'SEWING'] as const)('%s提交原payload与原ETag，不转换旧金工number或另建请求编号', async category => {
    const payload: SemiReceiptPayload = { request_id: requestId, schedule_product_id: plan, plan_category: category,
      zone_id: zoneId, receipt_date: '2028-02-29', remark: '原提交备注', lines: [{ bom_line_id: lineId, quantity: category === 'METAL' ? 12 : '12' }] }
    Object.freeze(payload.lines[0]); Object.freeze(payload.lines); Object.freeze(payload)
    request.post.mockResolvedValueOnce({ data: { data: result } })
    expect(await createSemiReceipt(payload, '"original-preview"')).toBe(result)
    expect(request.post).toHaveBeenCalledExactlyOnceWith('/api/v1/semi-finished-receipts/', payload,
      { headers: { 'If-Match': '"original-preview"' }, timeout: 30000 })
    expect(request.post.mock.calls[0]![1]).toBe(payload)
  })

  it('按原请求编号恢复已确认原单，路径参数完整编码', async () => {
    const confirmed = { ...result, status: 'CONFIRMED', replayed: true, record_ids: [lineId] }
    request.get.mockResolvedValueOnce({ data: { data: confirmed } })
    expect(await findSemiReceipt('original/id?x=1')).toBe(confirmed)
    expect(request.get).toHaveBeenCalledExactlyOnceWith('/api/v1/semi-finished-receipts/by-request/original%2Fid%3Fx%3D1/', { timeout: 15000 })
  })

  it.each([undefined, {}, { ...result, status: 'DRAFT' }, { ...result, replayed: undefined },
    { ...result, receipt_number: '' }, { ...result, record_ids: null }, { ...result, receipt_id: 123 },
    { ...result, receipt_id: { id: receiptId } }, { ...result, record_ids: ['invalid-id'] },
  ])('拒绝错误成功响应，保持原请求可核对', async data => {
    request.get.mockResolvedValueOnce({ data: { data } })
    await expect(findSemiReceipt(requestId)).rejects.toThrow('未收到完整半成品入库结果')
  })

  it.each([403, 404, 409, 412, 428, 500])('保留HTTP %s错误响应供恢复逻辑区分，不冒充成功', async status => {
    const error = { response: { status, data: { error: { code: 'ORIGINAL_ERROR', message: '原错误' } } } }
    request.get.mockRejectedValueOnce(error)
    await expect(fetchSemiReceiptPreview(plan, 'SEWING')).rejects.toBe(error)
    request.get.mockRejectedValueOnce(error)
    await expect(findSemiReceipt(requestId)).rejects.toBe(error)
    request.post.mockRejectedValueOnce(error)
    await expect(createSemiReceipt({} as SemiReceiptPayload, '"original-preview"')).rejects.toBe(error)
  })
})
