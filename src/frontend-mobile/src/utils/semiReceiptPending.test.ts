import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PendingSemiReceipt, SemiReceiptCategory, SemiReceiptPreview } from '@/types/semiReceipts'
import { createSemiReceiptPending } from './semiReceiptPending'
import { formatSemiQuantity, parsePendingSemiReceipt, semiLineError, semiPreviewWhole, semiReceiptFailure, semiReceiptLines, semiReceiptScope, semiWhole } from './semiReceipts'

const plan = '11111111-1111-4111-8111-111111111111'
const otherPlan = '22222222-2222-4222-8222-222222222222'
const zoneId = '33333333-3333-4333-8333-333333333333'
const requestId = '44444444-4444-4444-8444-444444444444'
const lineId = '55555555-5555-4555-8555-555555555555'
const legacy = (planId = plan, category = 'METAL') => `internal-receipt-pending:${planId}:${category}`
const key = (planId = plan, category = 'METAL', userId = 1) => `${legacy(planId, category)}:user:${userId}`
function pending(category: SemiReceiptCategory = 'METAL'): PendingSemiReceipt {
  return { etag: '"original-preview"', payload: { request_id: requestId, schedule_product_id: plan, plan_category: category,
    zone_id: zoneId, receipt_date: '2028-02-29', remark: '原备注', lines: [{ bom_line_id: lineId, quantity: '12' }] } }
}
function preview(category: SemiReceiptCategory = 'SEWING'): SemiReceiptPreview {
  return { schedule_product_id: plan, plan_category: category, etag: '"original-preview"', receipt_date: '2028-02-29',
    production_order: 'TASK', product: '产品', order_quantity: '1000', actor: '班组长', excluded: [], zones: [],
    lines: [{ bom_line_id: lineId, component_key: 'one', usage: 'INTERNAL', stage: '完成', required: '1000', received: '8', can_receive: '2.0000',
      attributes: { part_name: '坐垫', material: '', color: '', unit_name: category === 'METAL' ? '支' : '套' } }] }
}
function cleanup() {
  for (const planId of [plan, otherPlan]) for (const category of ['METAL', 'SEWING']) {
    sessionStorage.removeItem(legacy(planId, category))
    for (const user of [1, 2]) sessionStorage.removeItem(key(planId, category, user))
  }
}
beforeEach(cleanup)
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); cleanup() })

describe('半成品原请求的Session隔离与保护', () => {
  it('按计划、金工/车缝、账号分别保存，重新打开仍使用原payload与ETag', () => {
    const identity = { userId: 1, generation: 7 }
    const store = createSemiReceiptPending(plan, 'METAL', identity, () => identity)
    const raw = JSON.stringify(pending())
    store.write(raw)
    expect(sessionStorage.getItem(key())).toBe(raw)
    expect(createSemiReceiptPending(plan, 'METAL', identity, () => identity).read()).toBe(raw)
    expect(createSemiReceiptPending(otherPlan, 'METAL', identity, () => identity).read()).toBeNull()
    expect(createSemiReceiptPending(plan, 'SEWING', identity, () => identity).read()).toBeNull()
    const other = { userId: 2, generation: 7 }
    expect(createSemiReceiptPending(plan, 'METAL', other, () => other).read()).toBeNull()
  })

  it('写入、标记冲突和消费均核对原记录，不能覆盖或误删其他提交', () => {
    const identity = { userId: 1, generation: 1 }
    const store = createSemiReceiptPending(plan, 'METAL', identity, () => identity)
    const raw = JSON.stringify(pending()), conflict = JSON.stringify({ ...pending(), conflict: true })
    store.write(raw)
    expect(() => store.write('another')).toThrow('已有待核对记录')
    store.replace(raw, conflict)
    expect(store.read()).toBe(conflict)
    for (const operation of [() => store.assertUnchanged(raw), () => store.replace(raw, 'another'), () => store.consume(raw)]) {
      expect(operation).toThrow('待核对记录已变化')
      expect(store.read()).toBe(conflict)
    }
    store.consume(conflict)
    expect(store.read()).toBeNull()
  })

  it.each(['generation', 'userId'] as const)('身份%s变化后旧页面不能读写、替换或删除原请求', field => {
    const identity = { userId: 1, generation: 1 }
    const store = createSemiReceiptPending(plan, 'METAL', identity, () => identity)
    const raw = JSON.stringify(pending())
    store.write(raw)
    identity[field]++
    expect(store.isCurrent()).toBe(false)
    for (const operation of [() => store.read(), () => store.write('other'), () => store.replace(raw, 'other'), () => store.consume(raw)]) {
      expect(operation).toThrow('身份已变化')
      expect(sessionStorage.getItem(key())).toBe(raw)
    }
  })

  it.each([null, 0, -1, 1.5, Number.POSITIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1])('无有效ERP用户ID时不可操作记录：%s', userId => {
    const identity = { userId, generation: 1 }
    const store = createSemiReceiptPending(plan, 'SEWING', identity, () => identity)
    expect(store.isCurrent()).toBe(false)
    expect(() => store.read()).toThrow('身份已变化')
  })

  it.each(['', '{legacy-broken', JSON.stringify(pending())])('历史无账号记录无论内容均原样保留并阻止新提交', raw => {
    const identity = { userId: 1, generation: 1 }
    const store = createSemiReceiptPending(plan, 'METAL', identity, () => identity)
    sessionStorage.setItem(legacy(), raw)
    expect(() => store.read()).toThrow('历史无主待核对记录')
    expect(() => store.write(JSON.stringify(pending()))).toThrow('历史无主待核对记录')
    expect(sessionStorage.getItem(legacy())).toBe(raw)
    expect(sessionStorage.getItem(key())).toBeNull()
  })

  it('存储读写或删除失败直接抛错，不能假装已经保存或清理', () => {
    const identity = { userId: 1, generation: 1 }
    const store = createSemiReceiptPending(plan, 'METAL', identity, () => identity)
    const raw = JSON.stringify(pending())
    const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('quota') })
    expect(() => store.write(raw)).toThrow('quota')
    expect(sessionStorage.getItem(key())).toBeNull()
    write.mockRestore()
    store.write(raw)
    const remove = vi.spyOn(Storage.prototype, 'removeItem').mockImplementationOnce(() => { throw new Error('denied') })
    expect(() => store.consume(raw)).toThrow('denied')
    expect(sessionStorage.getItem(key())).toBe(raw)
    remove.mockRestore()
    vi.spyOn(Storage.prototype, 'getItem').mockImplementationOnce(() => { throw new Error('read denied') })
    expect(() => store.read()).toThrow('read denied')
  })

  it('写入后必须重新读取确认，浏览器拒绝访问Session存储时停止', () => {
    const identity = { userId: 1, generation: 1 }
    const store = createSemiReceiptPending(plan, 'METAL', identity, () => identity)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => undefined)
    expect(() => store.write(JSON.stringify(pending()))).toThrow('待核对记录已变化')
    vi.stubGlobal('window', { get sessionStorage() { throw new Error('storage disabled') } })
    expect(() => store.read()).toThrow('storage disabled')
  })
})

describe('半成品待核对记录与数量边界', () => {
  it('历史金工number数量、原ETag、冲突标记和额外原字段均原样保留', () => {
    const value = { ...pending(), conflict: true, original_marker: '不重建请求' }
    value.payload.lines[0]!.quantity = 12
    const raw = JSON.stringify(value)
    const parsed = parsePendingSemiReceipt(raw, plan, 'METAL')
    expect(JSON.stringify(parsed)).toBe(raw)
    expect(typeof parsed.payload.lines[0]!.quantity).toBe('number')
    expect(parsePendingSemiReceipt(JSON.stringify(pending('SEWING')), plan, 'SEWING')).toEqual(pending('SEWING'))
  })

  it.each(['{broken', 'null', '[]', JSON.stringify({}), JSON.stringify({ ...pending(), etag: '' }),
    JSON.stringify({ ...pending(), conflict: 'yes' }),
    JSON.stringify({ ...pending(), payload: { ...pending().payload, schedule_product_id: otherPlan } }),
    JSON.stringify({ ...pending(), payload: { ...pending().payload, plan_category: 'SEWING' } }),
    JSON.stringify({ ...pending(), payload: { ...pending().payload, request_id: 'invalid' } }),
    JSON.stringify({ ...pending(), payload: { ...pending().payload, zone_id: 'invalid' } }),
    JSON.stringify({ ...pending(), payload: { ...pending().payload, receipt_date: '2027-02-29' } }),
    JSON.stringify({ ...pending(), payload: { ...pending().payload, remark: '长'.repeat(2001) } }),
    JSON.stringify({ ...pending(), payload: { ...pending().payload, lines: [] } }),
    JSON.stringify({ ...pending(), payload: { ...pending().payload, lines: [pending().payload.lines[0], pending().payload.lines[0]] } }),
    ...['0', '-1', '1.5', '1e2', '100000000000000'].map(quantity => JSON.stringify({ ...pending(), payload: { ...pending().payload, lines: [{ bom_line_id: lineId, quantity }] } })),
  ])('损坏/串来源原记录不能作为新请求释放：%s', raw => {
    sessionStorage.setItem(key(), raw)
    expect(() => parsePendingSemiReceipt(raw, plan, 'METAL')).toThrow('本地待核对记录无法读取')
    expect(sessionStorage.getItem(key())).toBe(raw)
  })

  it('车缝旧记录拒绝number数量，金工也拒绝非整数或不安全number', () => {
    for (const [category, quantity] of [['SEWING', 12], ['METAL', 1.5], ['METAL', Number.MAX_SAFE_INTEGER + 1]] as const) {
      const value = pending(category)
      value.payload.lines[0]!.quantity = quantity
      expect(() => parsePendingSemiReceipt(JSON.stringify(value), plan, category)).toThrow('本地待核对记录无法读取')
    }
  })

  it.each(['METAL', 'SEWING'] as const)('%s路由只接受单个真实计划UUID与支持类别', category => {
    expect(semiReceiptScope({ schedule_product_id: plan, plan_category: category })).toEqual({ schedule_product_id: plan, plan_category: category })
    expect(semiReceiptScope({ schedule_product_id: [plan], plan_category: category })).toBeNull()
  })
  it.each([{}, { schedule_product_id: 'invalid', plan_category: 'METAL' }, { schedule_product_id: plan, plan_category: 'CUTTING' },
    { schedule_product_id: plan, plan_category: 'ASSEMBLY' }, { schedule_product_id: plan, plan_category: ['SEWING'] },
  ])('拒绝无效或不支持的入库来源', query => { expect(semiReceiptScope(query)).toBeNull() })

  it('数量限制14位有效整数，预览只兼容零小数格式，输入不偷偷转换', () => {
    for (const value of ['1.5', '-1', '1e3', ' 1', '1 ', '', true, null, 1.5, '100000000000000']) expect(semiWhole(value)).toBeNull()
    expect(semiWhole('00099999999999999')).toBe(99999999999999n)
    expect(semiWhole('000')).toBe(0n)
    expect(semiPreviewWhole('12.0000')).toBe(12n)
    expect(semiPreviewWhole('1.5000')).toBeNull()
    expect(semiPreviewWhole(12)).toBeNull()
    expect(formatSemiQuantity('1e2', '12')).toBe('12')
    expect(formatSemiQuantity('', '12')).toBe('')
  })

  it('每行只按服务端can_receive额度核对，不能按订单数量扩大，未知部位不提交', () => {
    const data = preview()
    expect(semiLineError(data, data.lines[0]!, '3')).toContain('本次最多可入 2 套')
    expect(semiReceiptLines(data, { [lineId]: '0002', [requestId]: '999' })).toEqual([{ bom_line_id: lineId, quantity: '2' }])
    expect(() => semiReceiptLines(data, { [lineId]: '3' })).toThrow('坐垫：本次最多可入 2 套')
    expect(() => semiReceiptLines(data, { [lineId]: '0' })).toThrow('请至少填写一项大于 0')
    expect(() => semiReceiptLines(data, {})).toThrow('请至少填写一项大于 0')
  })

  it('金工加工依据缺失与未来日期阻断均不得靠填数量绕过', () => {
    const data = preview('METAL')
    expect(semiLineError(data, data.lines[0]!, '1')).toContain('加工数量依据不完整')
    expect(semiLineError(data, data.lines[0]!, '0')).toBe('')
    data.metal_processing = { as_of: '2028-02-29', blockers: ['领料不足'], future_blockers: ['未来报工'] }
    expect(() => semiReceiptLines(data, { [lineId]: '1' })).toThrow('领料不足；未来报工')
  })

  it('明细最多300项，不能产生超出原API上限的新提交或恢复记录', () => {
    const data = preview()
    data.lines = Array.from({ length: 301 }, (_, index) => ({ ...data.lines[0]!, bom_line_id: `00000000-0000-4000-8000-${index.toString(16).padStart(12, '0')}` }))
    const quantities = Object.fromEntries(data.lines.map(line => [line.bom_line_id, '1']))
    expect(() => semiReceiptLines(data, quantities)).toThrow('每次最多提交 300 项')
    const value = pending('SEWING')
    value.payload.lines = data.lines.map(line => ({ bom_line_id: line.bom_line_id, quantity: '1' }))
    expect(() => parsePendingSemiReceipt(JSON.stringify(value), plan, 'SEWING')).toThrow('本地待核对记录无法读取')
    data.lines.pop()
    expect(semiReceiptLines(data, quantities)).toHaveLength(300)
  })

  it('区分明确拒绝、恢复未知、原请求冲突和已删除，超时不释放原请求', () => {
    for (const status of [400, 403, 404, 412, 428]) expect(semiReceiptFailure({ response: { status } }, false)).toBe('rejected')
    for (const status of [400, 403, 404]) expect(semiReceiptFailure({ response: { status } }, true)).toBe('unknown')
    expect(semiReceiptFailure({ response: { status: 409, data: { error: { code: 'RECEIPT_REQUEST_DELETED' } } } }, true)).toBe('deleted')
    expect(semiReceiptFailure({ response: { status: 409, data: { error: { code: 'RECEIPT_REQUEST_CONFLICT' } } } }, false)).toBe('conflict')
    for (const error of [new Error('timeout'), { response: { status: 500 } }, null]) expect(semiReceiptFailure(error, true)).toBe('unknown')
  })
})
