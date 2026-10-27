import { settingsMenu, sidebarMenuItems } from '@/config/sidebarMenu'
import type { CatalogEntry } from '@/types/access'

// 仅决定权限编辑器的显示归属；权限代码、可用范围与保存契约仍由后端目录定义。
export const accessMenuOptions = [...sidebarMenuItems.map(({ key, label }) => ({ key, label })), settingsMenu]
const moduleMenus: Record<string, string> = {
  customers: 'customer-management', inquiries: 'customer-management', quotations: 'customer-management',
  sales_orders: 'customer-management', crm: 'customer-management', workflow: 'customer-management', preferences: 'customer-management',
  samples: 'sample-management',
  products: 'product-management', product_catalog: 'product-management', material_catalog: 'product-management',
  production_tasks: 'production-management', boms: 'production-management',
  procurement: 'procurement-management',
  production_scheduling: 'workshop-management', material_issues: 'workshop-management', outsourcing: 'workshop-management',
  workshop_config: 'workshop-management', workshop_reporting: 'workshop-management',
  inventory: 'warehouse-management', finance: 'finance-management',
  attendance: 'employee-management', organizations: 'employee-management',
  access_control: 'settings', reference_data: 'settings', audit: 'settings',
}
const permissionMenus: Record<string, string> = {
  // 领料资源同时包含金工流转权限，只有以下领料操作归仓库；后端模块名保持不变。
  'material_issues.add_materialissue': 'warehouse-management',
  'material_issues.change_materialissue': 'warehouse-management',
  'material_issues.review_materialissue': 'warehouse-management',
  'material_issues.submit_materialissue': 'warehouse-management',
  'material_issues.view_materialissue': 'warehouse-management',
  'outsourcing.confirm_dispatch_outsourcingorder': 'warehouse-management',
  'outsourcing.confirm_return_outsourcingorder': 'warehouse-management',
  'outsourcing.return_raw_outsourcingorder': 'warehouse-management',
  'material_issues.confirm_metalprocessingexternalreturn': 'warehouse-management',
  'access_control.confirm_purchasereturn': 'procurement-management',
  'access_control.complete_purchasereturn': 'procurement-management',
  'access_control.manage_accounts': 'employee-management',
}

export function permissionMenu(entry: CatalogEntry): string {
  if (entry.resource === 'workflow.slapolicy') return 'settings'
  return permissionMenus[entry.code] || moduleMenus[entry.module] || 'unmapped'
}

export function groupAccessCatalog(catalog: CatalogEntry[]) {
  const labels = new Map(accessMenuOptions.map(menu => [menu.key, menu.label]))
  const order = new Map(accessMenuOptions.map((menu, index) => [menu.key, index]))
  const result = new Map<string, { key: string; name: string; module: string; moduleName: string; entries: CatalogEntry[] }>()
  for (const entry of catalog) {
    const menu = permissionMenu(entry)
    // 权限分组只改变权限编辑器的菜单归属，不改变后端资源和操作契约。
    const key = `${menu}:${entry.resource}`
    if (!result.has(key)) result.set(key, { key, name: entry.resource_name, module: menu, moduleName: labels.get(menu) || '其他权限', entries: [] })
    result.get(key)!.entries.push(entry)
  }
  return [...result.values()].sort((a, b) => (order.get(a.module) ?? order.size) - (order.get(b.module) ?? order.size))
}
