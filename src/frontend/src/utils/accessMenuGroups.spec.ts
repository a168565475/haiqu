import { describe, expect, it } from 'vitest'
import { settingsMenu, sidebarMenuItems } from '@/config/sidebarMenu'
import type { CatalogEntry } from '@/types/access'
import { accessMenuOptions, groupAccessCatalog, permissionMenu } from './accessMenuGroups'

const entry = (module: string, resource: string, code = `${module}.view_${resource}`): CatalogEntry => ({
  module, module_name: module, resource: `${module}.${resource}`, resource_name: resource,
  code, label: code, action: 'view', action_name: '查看', scopes: ['MODULE'], available: true,
  integration_stage: 5, implied_permissions: [],
})

describe('权限编辑器跟随侧栏菜单', () => {
  it('一级名称及顺序共用菜单定义，包括底部配置入口', () => {
    expect(accessMenuOptions).toEqual([...sidebarMenuItems.map(menu => ({ key: menu.key, label: menu.label })), settingsMenu])
    expect(accessMenuOptions.map(menu => menu.label)).toEqual(['工作台', '客户', '样品', '产品', '生产', '采购', '车间', '仓库', '财务', '行政', '看板', '配置'])
  })
  it('生产订单和 BOM 合并到生产，排产、委外与报工归车间', () => {
    for (const module of ['production_tasks', 'boms']) expect(permissionMenu(entry(module, 'item'))).toBe('production-management')
    for (const module of ['production_scheduling', 'material_issues', 'outsourcing', 'workshop_config', 'workshop_reporting']) {
      expect(permissionMenu(entry(module, 'item'))).toBe('workshop-management')
    }
  })
  it('库存收货、质检和入库明细统一归仓库且没有丢失/复制权限', () => {
    const catalog = [
      entry('inventory', 'materialinbound'),
      entry('inventory', 'materialinbound', 'inventory.receive_material'),
      entry('inventory', 'materialinbound', 'inventory.quality_confirm_material'),
      entry('inventory', 'materialinbound', 'inventory.view_material_receipt'),
    ]
    const original = JSON.stringify(catalog)
    const groups = groupAccessCatalog(catalog)
    expect(groups.map(group => group.module)).toEqual(['warehouse-management'])
    expect(groups[0]!.entries).toEqual(catalog)
    expect(new Set(groups.flatMap(group => group.entries.map(item => item.code))).size).toBe(catalog.length)
    expect(JSON.stringify(catalog)).toBe(original)
  })
  it('生产领料权限归仓库，金工流转权限仍归车间', () => {
    const materialIssueCodes = [
      'material_issues.add_materialissue',
      'material_issues.change_materialissue',
      'material_issues.review_materialissue',
      'material_issues.submit_materialissue',
      'material_issues.view_materialissue',
    ]
    for (const code of materialIssueCodes) expect(permissionMenu(entry('material_issues', 'materialissue', code))).toBe('warehouse-management')
    expect(permissionMenu(entry('material_issues', 'metalprocessingsource', 'material_issues.view_metalprocessingsource'))).toBe('workshop-management')
  })
  it('退货查看归仓库，退货确认和完成权限归采购', () => {
    expect(permissionMenu(entry('access_control', 'purchasereturn', 'access_control.confirm_purchasereturn'))).toBe('procurement-management')
    expect(permissionMenu(entry('access_control', 'purchasereturn', 'access_control.complete_purchasereturn'))).toBe('procurement-management')
  })
  it('委外发料、交接、入库及原料退回归仓库，单据管理和加工登记仍归车间', () => {
    const catalog = [
      entry('outsourcing', 'outsourcingorder', 'outsourcing.confirm_dispatch_outsourcingorder'),
      entry('outsourcing', 'outsourcingorder', 'outsourcing.confirm_return_outsourcingorder'),
      entry('outsourcing', 'outsourcingorder', 'outsourcing.return_raw_outsourcingorder'),
      entry('material_issues', 'metalprocessingexternalorder', 'material_issues.confirm_metalprocessingexternalreturn'),
      entry('outsourcing', 'outsourcingorder', 'outsourcing.add_outsourcingorder'),
      entry('material_issues', 'metalprocessingexternalorder', 'material_issues.confirm_metalprocessingexternalhandoff'),
      entry('material_issues', 'metalprocessingsource', 'material_issues.create_metalprocessingoriginalhandoff'),
      entry('material_issues', 'metalprocessingsource', 'material_issues.register_metalprocessingcompletion'),
    ]
    expect(catalog.map(permissionMenu)).toEqual([
      'warehouse-management', 'warehouse-management', 'warehouse-management', 'warehouse-management',
      'workshop-management', 'warehouse-management', 'warehouse-management', 'workshop-management',
    ])
    const groups = groupAccessCatalog(catalog)
    expect(groups.flatMap(group => group.entries)).toHaveLength(catalog.length)
    expect(new Set(groups.flatMap(group => group.entries.map(item => item.code))).size).toBe(catalog.length)
  })
  it('账号、组织、考勤归行政，权限管理与处理时限归配置', () => {
    expect(permissionMenu(entry('access_control', 'manage_accounts', 'access_control.manage_accounts'))).toBe('employee-management')
    expect(permissionMenu(entry('organizations', 'organizationunit'))).toBe('employee-management')
    expect(permissionMenu(entry('attendance', 'attendancemonth'))).toBe('employee-management')
    expect(permissionMenu(entry('access_control', 'manage_access'))).toBe('settings')
    expect(permissionMenu(entry('workflow', 'slapolicy'))).toBe('settings')
    expect(permissionMenu(entry('workflow', 'businesstask'))).toBe('customer-management')
  })
  it('按菜单顺序整理，未知目录保留在其他权限而非丢弃或错误归类', () => {
    const catalog = [entry('finance', 'receipt'), entry('unknown', 'record'), entry('boms', 'bom'), entry('customers', 'customeraccount')]
    const groups = groupAccessCatalog(catalog)
    expect(groups.map(group => group.moduleName)).toEqual(['客户', '生产', '财务', '其他权限'])
    expect(groups.flatMap(group => group.entries)).toHaveLength(catalog.length)
  })
})
