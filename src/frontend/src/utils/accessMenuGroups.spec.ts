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
  it('生产订单和 BOM 合并到生产，排产、领料、委外与报工归车间', () => {
    for (const module of ['production_tasks', 'boms']) expect(permissionMenu(entry(module, 'item'))).toBe('production-management')
    for (const module of ['production_scheduling', 'material_issues', 'outsourcing', 'workshop_config', 'workshop_reporting']) {
      expect(permissionMenu(entry(module, 'item'))).toBe('workshop-management')
    }
  })
  it('采购收货与仓库库存查看即使属于同一后端资源，也分在各自菜单且没有丢失/复制权限', () => {
    const catalog = [
      entry('inventory', 'materialinbound'),
      entry('inventory', 'materialinbound', 'inventory.receive_material'),
      entry('inventory', 'materialinbound', 'inventory.quality_confirm_material'),
      entry('inventory', 'materialinbound', 'inventory.view_material_receipt'),
    ]
    const original = JSON.stringify(catalog)
    const groups = groupAccessCatalog(catalog)
    expect(groups.map(group => group.module)).toEqual(['procurement-management', 'warehouse-management'])
    expect(groups[0]!.entries.map(item => item.code)).toEqual(['inventory.receive_material', 'inventory.quality_confirm_material', 'inventory.view_material_receipt'])
    expect(groups[1]!.entries).toEqual([catalog[0]])
    expect(new Set(groups.flatMap(group => group.entries.map(item => item.code))).size).toBe(catalog.length)
    expect(JSON.stringify(catalog)).toBe(original)
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
