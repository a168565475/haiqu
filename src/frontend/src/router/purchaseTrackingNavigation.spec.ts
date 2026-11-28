import { describe, expect, it } from 'vitest'
import { router } from './index'
import { canOpenPage } from './pageAccess'

describe('采购跟踪入口', () => {
  it('通知深链接归属采购菜单，保留历史定位参数和行定位', () => {
    const route = router.resolve('/purchase-tracking?tab=coverage&row_key=coverage:line-1')
    expect(route.name).toBe('purchase-tracking')
    expect(route.meta.activeMenu).toBe('purchase-tracking')
    expect(route.query.row_key).toBe('coverage:line-1')
  })
  it('采购提醒菜单进入独立采购提醒页面', () => {
    const route = router.resolve('/purchase-alerts')
    expect(route.name).toBe('purchase-alerts')
    expect(route.meta.activeMenu).toBe('purchase-alerts')
  })
  it('采购计划表使用普通采购查看权限，并支持任务号和分类直达', () => {
    const route = router.resolve('/purchase-plans?task_number=HT26170&category=FABRIC')
    expect(route.meta.activeMenu).toBe('purchase-plans')
    expect(route.query).toEqual({ task_number: 'HT26170', category: 'FABRIC' })
    const reader = (permission: string) => ({
      user: { is_superuser: false }, canReadAccessDirectory: false, hasPermission: (code: string) => code === permission,
    })
    expect(canOpenPage('purchase-plans', reader('procurement.view_purchaseorder'))).toBe(true)
    expect(canOpenPage('purchase-plans', reader('procurement.manage_packagingpurchase'))).toBe(false)
  })
  it('采购查看权允许跟踪，只有创建权不能绕过查看权', () => {
    const reader = (permissions: string[]) => ({ user: { is_superuser: false }, canReadAccessDirectory: false, hasPermission: (code: string) => permissions.includes(code) })
    expect(canOpenPage('purchase-tracking', reader([]))).toBe(false)
    expect(canOpenPage('purchase-tracking', reader(['procurement.add_purchaseorder']))).toBe(false)
    expect(canOpenPage('purchase-tracking', reader(['procurement.view_purchaseorder']))).toBe(true)
    expect(canOpenPage('purchase-alerts', reader(['procurement.view_purchaseorder']))).toBe(true)
  })
})

