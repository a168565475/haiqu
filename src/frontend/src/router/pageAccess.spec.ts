import { describe, expect, it } from 'vitest'
import { sidebarMenuItems } from '@/config/sidebarMenu'
import { canOpenMenu, canOpenPage, type PageAccessReader } from './pageAccess'

function reader(permissions: string[] = [], superuser = false): PageAccessReader {
  return { user: { is_superuser: superuser }, canReadAccessDirectory: superuser, hasPermission: code => permissions.includes(code) }
}

function followedReader(permissions: string[]): PageAccessReader {
  const auth = reader(permissions)
  auth.user!.effective_access = { active: true, is_superuser: false, roles: [], legacy_sources: [], version: 'v1', actions: {} }
  for (const permission of permissions) {
    auth.user!.effective_access.actions[permission] = { scopes: ['FOLLOWED'], sources: [{ type: 'ROLE', scope: 'FOLLOWED' }] }
  }
  return auth
}

describe('岗位菜单与独立页面权限', () => {
  it('采购保留自己的退货记录，但不显示仓库菜单或进入仓库退货页', () => {
    const auth = reader([
      'procurement.view_purchaseorder', 'procurement.add_purchaseorder', 'procurement.submit_purchaseorder',
      'access_control.confirm_purchasereturn', 'access_control.complete_purchasereturn',
    ])
    const warehouse = sidebarMenuItems.find(item => item.key === 'warehouse-management')!
    expect(warehouse.children!.filter(item => canOpenMenu(item, auth))).toEqual([])
    expect(canOpenPage('purchase-returns', auth)).toBe(false)
    expect(canOpenPage('purchase-orders', auth)).toBe(true)
    expect(canOpenPage('purchase-return-records', auth)).toBe(true)
  })
  it.each(['inventory.receive_material', 'inventory.quality_confirm_material'])('仓管和品质保留仓库退货只读入口：%s', permission => {
    expect(canOpenPage('purchase-returns', reader([permission]))).toBe(true)
    expect(canOpenPage('purchase-return-records', reader([permission]))).toBe(false)
  })
  it('采购来源选择不要求任务或 BOM 独立页面权限', () => {
    const auth = reader(['procurement.add_purchaseorder'])
    expect(canOpenPage('purchase-order-create', auth)).toBe(true)
    for (const page of ['production-tasks', 'production-task-detail', 'boms', 'bom-preview', 'products', 'raw-materials', 'product-catalog', 'material-catalog']) {
      expect(canOpenPage(page, auth), page).toBe(false)
    }
    expect(canOpenPage('purchase-order-create', reader(['procurement.view_purchaseorder']))).toBe(false)
  })
  it('PMC 独立计划权限允许进入编辑页，不能创建生产任务', () => {
    const auth = reader(['production_tasks.view_productiontask', 'access_control.edit_productionplan'])
    expect(canOpenPage('production-task-edit', auth)).toBe(true)
    expect(canOpenPage('production-task-create', auth)).toBe(false)
  })
  it('仅跟单范围可读关联记录但不开放全部库存菜单', () => {
    const auth = reader(['inventory.view_materialinbound', 'inventory.view_finishedgoodsreceipt'])
    auth.user!.effective_access = { active: true, is_superuser: false, roles: [], legacy_sources: [], version: 'v1', actions: {
      'inventory.view_materialinbound': { scopes: ['FOLLOWED'], sources: [{ type: 'ROLE', scope: 'FOLLOWED' }] },
      'inventory.view_finishedgoodsreceipt': { scopes: ['FOLLOWED'], sources: [{ type: 'ROLE', scope: 'FOLLOWED' }] },
    } }
    expect(canOpenPage('material-inventory', auth)).toBe(false)
    expect(canOpenPage('finished-goods-inventory', auth)).toBe(false)
    auth.user!.effective_access.actions['inventory.view_materialinbound']!.scopes.push('MODULE')
    expect(canOpenPage('material-inventory', auth)).toBe(true)
  })
  it('仅跟单范围保留任务关联读取，不开放领料和委外独立菜单或列表', () => {
    const auth = followedReader([
      'production_tasks.view_productiontask', 'material_issues.view_materialissue',
      'outsourcing.view_outsourcingorder', 'material_issues.view_metalprocessingsource',
    ])
    for (const key of ['material-issues', 'workshop-outsourcing']) {
      const item = sidebarMenuItems.flatMap(group => group.children ?? [group]).find(item => item.key === key)!
      expect(canOpenMenu(item, auth), key).toBe(false)
      expect(canOpenPage(key, auth), key).toBe(false)
    }
    expect(canOpenPage('production-task-detail', auth)).toBe(true)
    expect(canOpenPage('material-issue-detail', auth)).toBe(true)
    expect(canOpenPage('workshop-outsourcing-detail', auth)).toBe(true)
    expect(canOpenPage('workshop-outsourcing-tube-detail', auth)).toBe(true)
  })
  it.each([
    ['material_issues.view_materialissue', 'WORKSHOP', 'material-issues'],
    ['outsourcing.view_outsourcingorder', 'MODULE', 'workshop-outsourcing'],
    ['material_issues.view_metalprocessingsource', 'CRAFT', 'workshop-outsourcing'],
  ] as const)('兼岗的独立 %s %s 授权仍可进入 %s', (permission, scope, page) => {
    const auth = followedReader(['material_issues.view_materialissue', 'outsourcing.view_outsourcingorder', 'material_issues.view_metalprocessingsource'])
    auth.user!.effective_access!.actions[permission]!.scopes.push(scope)
    auth.user!.effective_access!.actions[permission]!.sources.push({ type: 'ROLE', scope })
    expect(canOpenPage(page, auth)).toBe(true)
  })
  it('真实旧授权继续独立生效，不被跟单范围遮掉', () => {
    const auth = followedReader(['material_issues.view_materialissue'])
    auth.user!.effective_access!.legacy_sources.push({ type: 'DIRECT', permission: 'material_issues.view_materialissue' })
    expect(canOpenPage('material-issues', auth)).toBe(true)
  })
  it.each([
    { permissions: ['procurement.view_purchaseorder'], expected: [true, false, false, false] },
    { permissions: ['inventory.receive_material'], expected: [false, true, true, false] },
    { permissions: ['inventory.quality_confirm_material'], expected: [false, true, false, true] },
    { permissions: ['procurement.view_purchaseorder', 'inventory.receive_material', 'inventory.quality_confirm_material'], expected: [true, true, true, true] },
  ])('采购和仓库详情及作业入口按实际权限分开：$permissions', ({ permissions, expected }) => {
    const auth = reader(permissions)
    const pages = ['purchase-order-detail', 'purchase-inbound-detail', 'material-purchase-inbound', 'material-quality-confirmation']
    expect(pages.map(page => canOpenPage(page, auth))).toEqual(expected)
    for (const page of pages) expect(canOpenPage(page, reader([], true)), page).toBe(true)
  })
  it('本轮不改变看板入口', () => {
    for (const page of ['production-line-board', 'warehouse-board', 'production-progress-board', 'production-board']) {
      expect(canOpenPage(page, reader()), page).toBe(true)
    }
  })
  it('无销售权限不会因旧销售开关未启用而显示销售订单', () => {
    const item = sidebarMenuItems.flatMap(group => group.children ?? [group]).find(item => item.key === 'sales-orders')!
    expect(canOpenMenu(item, reader())).toBe(false)
    expect(canOpenMenu(item, reader(['sales_orders.view_salesorder']))).toBe(true)
  })
  it('生产总览跟随业务读取权，真实超级管理员可访问所有可用页面', () => {
    expect(canOpenPage('production-overview', reader())).toBe(false)
    expect(canOpenPage('production-overview', reader(['production_tasks.view_productiontask']))).toBe(true)
    expect(canOpenPage('bom-edit', reader([], true))).toBe(true)
  })
})
