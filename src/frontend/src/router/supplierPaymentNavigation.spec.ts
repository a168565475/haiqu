import { describe, expect, it } from 'vitest'
import { sidebarMenuItems } from '@/config/sidebarMenu'
import { glassListRouteNames } from '@/config/glassListRoutes'
import { canOpenPage, type PageAccessReader } from './pageAccess'

const reader = (permission: string): PageAccessReader => ({
  user: { is_superuser: false },
  canReadAccessDirectory: false,
  hasPermission: value => value === permission,
})

describe('供应商付款入口', () => {
  it('使用独立菜单授权并接入列表主题', () => {
    const module = sidebarMenuItems.find(group => group.key === 'finance-management')
    expect(module?.children?.find(child => child.key === 'finance-supplier-payments')?.permission).toBe('finance.view_supplierpayment')
    expect(glassListRouteNames).toContain('finance-supplier-payments')
    expect(canOpenPage('finance-supplier-payments', reader('finance.view_supplierledger'))).toBe(false)
    expect(canOpenPage('finance-supplier-payments', reader('finance.view_supplierpayment'))).toBe(true)
    expect(canOpenPage('finance-supplier-ledger', reader('finance.view_supplierpayment'))).toBe(false)
  })
})
