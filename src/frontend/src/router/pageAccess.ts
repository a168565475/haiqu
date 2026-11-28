import { sidebarMenuItems, type MenuItem } from '@/config/sidebarMenu'
import type { EffectiveAccess } from '@/types/access'

export interface PageAccessReader {
  user: { is_superuser: boolean; effective_access?: EffectiveAccess } | null
  canReadAccessDirectory: boolean
  hasPermission: (permission: string) => boolean
}

export function hasWorkshopOnlyPlanAccess(auth: PageAccessReader): boolean {
  if (auth.user?.is_superuser) return false
  const permission = 'production_scheduling.view_productionschedule'
  const access = auth.user?.effective_access
  const scopes = access?.actions[permission]?.scopes
  return Boolean(scopes?.length && scopes.every(scope => scope === 'WORKSHOP'))
    && !access?.legacy_sources.some(source => source.permission === permission)
    && !auth.hasPermission('production_scheduling.view_all_productionschedule')
}

export function canOpenMenu(item: MenuItem, auth: PageAccessReader): boolean {
  if (item.available === false) return false
  if (item.key === 'employee-list') return auth.canReadAccessDirectory
  if (auth.user?.is_superuser) return true
  if (item.key === 'warehouse-workbench') {
    return auth.user?.effective_access?.roles.some(role => role.code === 'WAREHOUSE_KEEPER') === true
  }
  if (item.key === 'merchandiser-workbench'
    && !auth.user?.effective_access?.roles.some(role => role.code === 'MERCHANDISER')) return false
  // 跟单关联读取不开放独立列表；兼岗的独立授权仍逐项生效。
  const relatedReadOnly = ['material-inventory', 'material-inbound-details', 'material-inbound-records', 'material-transfers', 'purchase-receipt-records', 'finished-goods-inventory', 'semi-receipt-records', 'workshop-semi-receipt-records', 'workshop-finished-receipt-records', 'material-issues', 'workshop-outsourcing', 'workshop-powder-coating', 'sewing-outsourcing-workbench'].includes(item.key)
  const canUsePermission = (permission: string) => {
    if (!auth.hasPermission(permission)) return false
    if (relatedReadOnly && permission !== 'outsourcing.manage_cutpieceprinting') {
      const access = auth.user?.effective_access
      const scopes = access?.actions[permission]?.scopes
      if (scopes?.length && scopes.every(scope => scope === 'FOLLOWED')
        && !access?.legacy_sources.some(source => source.permission === permission)) return false
    }
    return true
  }
  if (item.anyPermissions) return item.anyPermissions.some(canUsePermission)
  if (item.allPermissions) return item.allPermissions.every(canUsePermission)
  return !item.permission || canUsePermission(item.permission)
}

// 仅约束独立页面；作业中的来源选择仍由各业务API授权，不继承其来源菜单的查看权。
const pagePermissions: Record<string, string[]> = {
  'products': ['products.view_productinformation'],
  'raw-materials': ['products.view_rawmaterialinformation'],
  'purchase-order-create': ['procurement.add_purchaseorder'],
  'purchase-order-create-details': ['procurement.add_purchaseorder'],
  'purchase-order-detail': ['procurement.view_purchaseorder', 'procurement.manage_packagingpurchase'],
  'packaging-purchase-create': ['procurement.manage_packagingpurchase'],
  'workshop-metal-processing': ['material_issues.view_metalprocessingsource'],
  'cut-piece-printing-new': ['outsourcing.manage_cutpieceprinting'],
  'cut-piece-printing-detail': ['outsourcing.manage_cutpieceprinting'],
  'packaging-purchase-batch': ['procurement.manage_packagingpurchase'],
  'packaging-purchase-detail': ['procurement.manage_packagingpurchase'],
  'purchase-tracking': ['procurement.view_purchaseorder', 'procurement.manage_packagingpurchase'],
  'purchase-alerts': ['procurement.view_purchaseorder', 'procurement.manage_packagingpurchase'],
  'purchase-inbound-detail': ['inventory.receive_material', 'inventory.quality_confirm_material'],
  'material-purchase-inbound': ['inventory.receive_material'],
  'manual-material-inbound': ['inventory.receive_material'],
  'material-inbound-details': ['inventory.view_material_receipt'],
  'material-inbound-records': ['inventory.view_material_receipt'],
  // 跟单和通知仍可打开原记录页，接口按当前账号的数据范围返回单据。
  'semi-receipt-records': ['inventory.view_internalsemifinishedreceipt'],
  'material-quality-confirmation': ['inventory.quality_confirm_material'],
  'production-task-create': ['production_tasks.add_productiontask'],
  'production-task-manual-create': ['production_tasks.add_productiontask'],
  'production-task-detail': ['production_tasks.view_productiontask'],
  'production-task-edit': ['production_tasks.change_productiontask', 'access_control.edit_productionplan'],
  'bom-create': ['boms.add_bom'],
  'bom-edit': ['boms.change_bom'],
  'bom-preview': ['boms.view_bom'],
  'sample-new': ['samples.add_samplerequest'],
  'sample-detail': ['samples.view_samplerequest'],
}

const menuByRoute = new Map(sidebarMenuItems.flatMap(group => group.children ?? [group])
  .filter(item => item.to).map(item => [item.to!.name, item]))

export function canOpenPage(name: unknown, auth: PageAccessReader): boolean {
  if (typeof name !== 'string') return true
  if (auth.user?.is_superuser) return true
  const permissions = pagePermissions[name]
  if (permissions) return permissions.some(permission => auth.hasPermission(permission))
  const menu = menuByRoute.get(name)
  return !menu || canOpenMenu(menu, auth)
}
