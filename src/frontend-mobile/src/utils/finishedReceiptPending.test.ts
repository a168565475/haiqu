import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createFinishedReceiptPending } from './finishedReceiptPending'
import { formatReceiptQuantity, parsePendingFinishedReceipt, positiveReceiptQuantity, receiptFailureIsDefinitive } from './finishedReceipts'

const plan = '11111111-1111-4111-8111-111111111111'
const key = `assembly-receipt:${plan}:user:1`, legacy = `assembly-receipt:${plan}`
const value = { etag: '"one"', payload: { request_id: '22222222-2222-4222-8222-222222222222', schedule_product_id: plan,
  location_id: '33333333-3333-4333-8333-333333333333', receipt_date: '2028-02-29', received_quantity: 10, quantity_per_box: null, actual_color: '蓝色', remark: '' } }
function cleanup() { for (const item of [key, legacy, `assembly-receipt:${plan}:user:2`]) sessionStorage.removeItem(item) }
beforeEach(cleanup)
afterEach(() => { vi.restoreAllMocks(); cleanup() })
describe('成品入库原请求与数量边界', () => {
  it('同账号重新打开恢复原记录，记录存在或已改变时不能覆盖或误删', () => {
    const identity = { userId: 1, generation: 1 }
    const store = createFinishedReceiptPending(plan, identity, () => identity)
    store.write(JSON.stringify(value))
    const reopened = createFinishedReceiptPending(plan, identity, () => identity)
    expect(parsePendingFinishedReceipt(reopened.read()!, plan)).toEqual(value)
    expect(() => reopened.write('other')).toThrow('已有待核对记录')
    sessionStorage.setItem(key, 'changed')
    expect(() => reopened.consume(JSON.stringify(value))).toThrow('待核对记录已变化')
    expect(sessionStorage.getItem(key)).toBe('changed')
  })
  it('账号及身份代际隔离，旧身份不能读写或清除原请求', () => {
    const identity = { userId: 1, generation: 1 }
    const original = createFinishedReceiptPending(plan, identity, () => identity)
    original.write(JSON.stringify(value))
    identity.generation++
    expect(original.isCurrent()).toBe(false)
    expect(() => original.consume(JSON.stringify(value))).toThrow('身份已变化')
    identity.userId = 2
    const other = createFinishedReceiptPending(plan, identity, () => identity)
    expect(other.read()).toBeNull()
    expect(sessionStorage.getItem(key)).toBe(JSON.stringify(value))
  })
  it('历史无主记录原样保留，存储异常不降级成无请求编号发送', () => {
    const identity = { userId: 1, generation: 1 }
    const store = createFinishedReceiptPending(plan, identity, () => identity)
    sessionStorage.setItem(legacy, '')
    expect(() => store.read()).toThrow('历史无主')
    expect(sessionStorage.getItem(legacy)).toBe('')
    sessionStorage.removeItem(legacy)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('storage denied') })
    expect(() => store.write(JSON.stringify(value))).toThrow('storage denied')
    expect(sessionStorage.getItem(key)).toBeNull()
  })
  it.each(['{broken', 'null', JSON.stringify({ ...value, payload: { ...value.payload, schedule_product_id: 'another' } }),
    JSON.stringify({ ...value, payload: { ...value.payload, received_quantity: 1.5 } }),
    JSON.stringify({ ...value, payload: { ...value.payload, receipt_date: '2027-02-29' } }),
  ])('拒绝损坏或串来源的原请求：%s', raw => { expect(() => parsePendingFinishedReceipt(raw, plan)).toThrow('原提交记录无法读取') })
  it('正整数不接受科学计数、小数或安全范围之外的值，允许清空输入', () => {
    for (const invalid of ['1e3', '1.5', '-1', '0', '9007199254740992']) expect(positiveReceiptQuantity(invalid)).toBeNull()
    expect(positiveReceiptQuantity('10')).toBe(10)
    expect(formatReceiptQuantity('1e3', '10')).toBe('10')
    expect(formatReceiptQuantity('', '10')).toBe('')
  })
  it('只有明确拒绝可以释放原请求，未知或请求编号冲突必须保留', () => {
    for (const status of [400, 412, 428]) expect(receiptFailureIsDefinitive({ response: { status } })).toBe(true)
    expect(receiptFailureIsDefinitive({ response: { status: 409, data: { error: { code: 'CONFLICT' } } } })).toBe(true)
    expect(receiptFailureIsDefinitive({ response: { status: 409, data: { error: { code: 'RECEIPT_REQUEST_DELETED' } } } })).toBe(true)
    for (const error of [new Error('timeout'), { response: { status: 500 } }, { response: { status: 403 } }, { response: { status: 409, data: { error: { code: 'RECEIPT_REQUEST_CONFLICT' } } } }]) {
      expect(receiptFailureIsDefinitive(error)).toBe(false)
    }
  })
})
