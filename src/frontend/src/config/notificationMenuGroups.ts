import { sidebarMenuItems } from './sidebarMenu'
import type { NotificationRule } from '@/types/notifications'

type NotificationMenuGroup = {
  key: string
  label: string
  rules: NotificationRule[]
}

// 与侧边栏业务菜单保持一致；材料到货、质检和生产领料由仓库负责。
const eventMenuKeys: Record<string, string> = {
  PRODUCTION_TASK_CONFIRMED: 'production-management',
  BOM_CONFIRMED: 'production-management',
  PRODUCTION_TASK_BOMS_CONFIRMED: 'production-management',
  SUPPLIER_PURCHASE_SHEET_PUBLISHED: 'procurement-management',
  MATERIAL_RECEIPT_RECORDED: 'warehouse-management',
  MATERIAL_INSPECTION_CONFIRMED: 'warehouse-management',
  PURCHASE_ORDER_COMPLETED: 'procurement-management',
  PRODUCTION_PLAN_CREATED: 'workshop-management',
  MATERIAL_ISSUE_SUBMITTED: 'warehouse-management',
  WAGE_SCHEME_SUBMITTED: 'workshop-management',
  WAGE_SCHEME_DECIDED: 'workshop-management',
  WORK_REPORT_SAVED: 'workshop-management',
  WORK_REPORT_CORRECTED: 'workshop-management',
  WORK_REPORT_DELETED: 'workshop-management',
  OUTSOURCING_LOSS_RECORDED: 'workshop-management',
  TUBE_OUTSOURCING_SHORTAGE_RECORDED: 'workshop-management',
  OUTSOURCING_ORDER_CREATED: 'warehouse-management',
  TUBE_OUTSOURCING_ORDER_CREATED: 'warehouse-management',
  SEMI_FINISHED_RECEIPT_SUBMITTED: 'warehouse-management',
  ASSEMBLY_FINISHED_RECEIPT_SUBMITTED: 'warehouse-management',
  INTERNAL_SEMI_RECEIPT_CONFIRMED: 'warehouse-management',
  ASSEMBLY_FINISHED_RECEIPT_CONFIRMED: 'warehouse-management',
  FINISHED_GOODS_OUTBOUND_CONFIRMED: 'warehouse-management',
  SAMPLE_SUBMITTED: 'sample-management',
  SAMPLE_EFFECTIVE: 'sample-management',
  SAMPLE_RETURNED: 'sample-management',
  SAMPLE_REQUIREMENTS_COMPLETED: 'sample-management',
  SAMPLE_MATERIALS_SUBMITTED: 'sample-management',
  SAMPLE_MATERIAL_SHORTAGE: 'sample-management',
  SAMPLE_MATERIALS_AVAILABLE: 'sample-management',
  SAMPLE_MATERIAL_ISSUE_SUBMITTED: 'sample-management',
  SAMPLE_MATERIAL_ISSUED: 'sample-management',
  SAMPLE_PRODUCTION_READY: 'sample-management',
  SAMPLE_COMPLETED: 'sample-management',
  SAMPLE_INVENTORY_RECEIVED: 'sample-management',
}

const menuLabels = new Map(sidebarMenuItems.map(menu => [menu.key, menu.label]))
const menuOrder = new Map(sidebarMenuItems.map((menu, index) => [menu.key, index]))

export function groupNotificationRules(rules: NotificationRule[]): NotificationMenuGroup[] {
  const groups = new Map<string, NotificationMenuGroup>()
  for (const rule of rules) {
    const key = eventMenuKeys[rule.event_code] || 'other'
    const label = menuLabels.get(key) || '其他'
    if (!groups.has(key)) groups.set(key, { key, label, rules: [] })
    groups.get(key)!.rules.push(rule)
  }
  return [...groups.values()].sort((a, b) => {
    const aOrder = menuOrder.get(a.key) ?? menuOrder.size
    const bOrder = menuOrder.get(b.key) ?? menuOrder.size
    return aOrder - bOrder
  })
}
