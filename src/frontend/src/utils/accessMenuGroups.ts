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
  'inventory.receive_material': 'procurement-management',
  'inventory.quality_confirm_material': 'procurement-management',
  'inventory.view_material_receipt': 'procurement-management',
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
    // 同一后端资源可包含不同菜单的操作，例如采购收货与仓库库存查看。
    const key = `${menu}:${entry.resource}`
    if (!result.has(key)) result.set(key, { key, name: entry.resource_name, module: menu, moduleName: labels.get(menu) || '其他权限', entries: [] })
    result.get(key)!.entries.push(entry)
  }
  return [...result.values()].sort((a, b) => (order.get(a.module) ?? order.size) - (order.get(b.module) ?? order.size))
}
