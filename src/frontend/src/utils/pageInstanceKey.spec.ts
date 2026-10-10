import { describe, expect, it } from 'vitest'
import { pageInstanceKey } from './pageInstanceKey'

describe('页面实例隔离', () => {
  const route = (name = 'customer-detail', id = 'a') => ({ name, params: { customerId: id }, path: `/customers/${id}`, fullPath: `/customers/${id}/${name}` })
  it('同一客户只读页签复用，客户、身份及编辑模式隔离', () => {
    const key = pageInstanceKey(route(), 1)
    expect(pageInstanceKey(route('customer-contacts'), 1)).toBe(key)
    expect(pageInstanceKey(route('customer-timeline'), 1)).toBe(key)
    expect(pageInstanceKey(route('customer-detail', 'b'), 1)).not.toBe(key)
    expect(pageInstanceKey(route(), 2)).not.toBe(key)
    expect(pageInstanceKey(route('customer-edit'), 1)).not.toBe(key)
    expect(pageInstanceKey(route('customer-transfer'), 1)).not.toBe(key)
  })
})
