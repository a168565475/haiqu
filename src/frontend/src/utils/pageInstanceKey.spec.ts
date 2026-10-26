import { describe, expect, it } from 'vitest'
import { pageInstanceKey } from './pageInstanceKey'

it('行政员工页消费定位参数时保留实例，切换账号时重新创建', () => {
  const route = { name: 'employee-list', params: {}, path: '/employees', fullPath: '/employees?tab=employees&employee_id=first' }
  expect(pageInstanceKey(route, 1)).toBe(pageInstanceKey({ ...route, fullPath: '/employees' }, 1))
  expect(pageInstanceKey(route, 1)).not.toBe(pageInstanceKey(route, 2))
})

describe('页面实例隔离', () => {
  it('客诉筛选和分页复用实例，切换身份仍重新创建', () => {
    const route = { name: 'complaints', params: {}, path: '/complaints', fullPath: '/complaints?q=first' }
    expect(pageInstanceKey(route, 1)).toBe(pageInstanceKey({ ...route, fullPath: '/complaints?q=second&page=2' }, 1))
    expect(pageInstanceKey(route, 1)).not.toBe(pageInstanceKey(route, 2))
  })
  it('权限页员工定位参数变化保留页面实例，切换账号仍隔离', () => {
    const access = { name: 'access-management', params: {}, path: '/settings/access', fullPath: '/settings/access?tab=employees&employee_id=first' }
    const key = pageInstanceKey(access, 1)
    expect(pageInstanceKey({ ...access, fullPath: '/settings/access?tab=employees' }, 1)).toBe(key)
    expect(pageInstanceKey({ ...access, fullPath: '/settings/access?tab=employees&employee_id=second' }, 1)).toBe(key)
    expect(pageInstanceKey(access, 2)).not.toBe(key)
  })
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
