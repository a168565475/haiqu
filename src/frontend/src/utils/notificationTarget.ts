import type { NotificationTarget } from '@/types/notifications'

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
// 和后端固定事件登记表对应；target_key 是语义标识，不能当作路由名。
const routes: Record<string, [string, string?]> = {
  PRODUCTION_TASK_CONFIRMED: ['production-task-detail', 'taskId'],
  BOM_CONFIRMED: ['bom-preview', 'bomId'],
  PRODUCTION_TASK_BOMS_CONFIRMED: ['boms'],
  SUPPLIER_PURCHASE_SHEET_PUBLISHED: ['supplier-purchase-sheet-editor', 'id'],
  MATERIAL_RECEIPT_RECORDED: ['material-quality-confirmation'],
  MATERIAL_INSPECTION_CONFIRMED: ['purchase-order-detail', 'id'],
  PURCHASE_ORDER_COMPLETED: ['purchase-order-detail', 'id'],
  PRODUCTION_PLAN_CREATED: ['workshop-scheduling-detail', 'scheduleId'],
  MATERIAL_ISSUE_SUBMITTED: ['material-issue-detail', 'issueId'],
  INTERNAL_SEMI_RECEIPT_CONFIRMED: ['semi-receipt-records'],
  SEMI_FINISHED_RECEIPT_SUBMITTED: ['semi-receipt-records'],
  ASSEMBLY_FINISHED_RECEIPT_SUBMITTED: ['finished-goods-inventory'],
  ASSEMBLY_FINISHED_RECEIPT_CONFIRMED: ['finished-goods-inventory'],
  FINISHED_GOODS_OUTBOUND_CONFIRMED: ['finished-goods-outbound-detail', 'outboundId'],
  WAGE_SCHEME_SUBMITTED: ['wage-scheme-detail', 'schemeId'],
  WAGE_SCHEME_DECIDED: ['wage-scheme-detail', 'schemeId'],
  WORK_REPORT_SAVED: ['work-report-day-detail', 'productionDate'],
  WORK_REPORT_CORRECTED: ['work-report-day-detail', 'productionDate'],
  OUTSOURCING_LOSS_RECORDED: ['workshop-outsourcing-detail', 'orderId'],
  TUBE_OUTSOURCING_SHORTAGE_RECORDED: ['workshop-outsourcing-tube-detail', 'id'],
  OUTSOURCING_ORDER_CREATED: ['warehouse-outsourcing-detail', 'orderId'],
  TUBE_OUTSOURCING_ORDER_CREATED: ['warehouse-outsourcing-tube-detail', 'id'],
  SAMPLE_SUBMITTED: ['sample-detail', 'sampleId'],
  SAMPLE_EFFECTIVE: ['sample-detail', 'sampleId'],
  SAMPLE_RETURNED: ['sample-detail', 'sampleId'],
  SAMPLE_REQUIREMENTS_COMPLETED: ['sample-material-detail', 'sampleId'],
  SAMPLE_MATERIALS_SUBMITTED: ['sample-warehouse-review', 'sampleId'],
  SAMPLE_MATERIAL_SHORTAGE: ['sample-material-detail', 'sampleId'],
  SAMPLE_MATERIALS_AVAILABLE: ['sample-material-issue', 'sampleId'],
  SAMPLE_MATERIAL_ISSUE_SUBMITTED: ['sample-material-issue-confirm', 'sampleId'],
  SAMPLE_MATERIAL_ISSUED: ['sample-detail', 'sampleId'],
  SAMPLE_PRODUCTION_READY: ['sample-detail', 'sampleId'],
  SAMPLE_COMPLETED: ['sample-detail', 'sampleId'],
  SAMPLE_INVENTORY_RECEIVED: ['sample-inventory-receipt-detail', 'receiptId'],
}

// 已保存的旧通知保留原目标；管材车间直交的新通知也继续进入车间详情。
const compatibleRoutes: Record<string, string> = {
  OUTSOURCING_ORDER_CREATED: 'workshop-outsourcing-detail',
  TUBE_OUTSOURCING_ORDER_CREATED: 'workshop-outsourcing-tube-detail',
}

export function notificationRoute(eventCode: string, target: NotificationTarget): { name: string; params: Record<string, string>; query?: Record<string, string> } {
  const allowed = Object.hasOwn(routes, eventCode) ? routes[eventCode] : undefined
  const compatibleRoute = Object.hasOwn(compatibleRoutes, eventCode) ? compatibleRoutes[eventCode] : undefined
  if (!allowed || !target || typeof target.object_id !== 'string' || !uuid.test(target.object_id)
    || (target.route_name !== allowed[0] && (!compatibleRoute || target.route_name !== compatibleRoute))
    || !target.params || typeof target.params !== 'object' || Array.isArray(target.params)
    || Object.hasOwn(target, 'query')) {
    throw new Error('通知跳转目标不受支持，请刷新消息。')
  }
  const parameter = allowed[1]
  const keys = Object.keys(target.params)
  if (!parameter) {
    if (keys.length) throw new Error('通知跳转参数无效。')
    // 只由此已登记事件构造现有记录页签；后端/消息输入不支持任意query。
    if (['SEMI_FINISHED_RECEIPT_SUBMITTED', 'ASSEMBLY_FINISHED_RECEIPT_SUBMITTED', 'ASSEMBLY_FINISHED_RECEIPT_CONFIRMED'].includes(eventCode)) return { name: allowed[0], params: {}, query: { tab: 'records' } }
    return { name: allowed[0], params: {} }
  }
  // 旧管材通知误用了 orderId，真实详情路由参数为 id；仅兼容这两个已登记事件。
  const legacyTubeParameter = ['TUBE_OUTSOURCING_ORDER_CREATED', 'TUBE_OUTSOURCING_SHORTAGE_RECORDED'].includes(eventCode)
    && target.route_name === 'workshop-outsourcing-tube-detail' && keys.length === 1 && keys[0] === 'orderId'
  const value = target.params[legacyTubeParameter ? 'orderId' : parameter]
  const valid = parameter === 'productionDate'
    ? typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
      && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
    : typeof value === 'string' && uuid.test(value)
  if (keys.length !== 1 || !valid) throw new Error('通知跳转参数无效。')
  const name = eventCode === 'TUBE_OUTSOURCING_ORDER_CREATED' && target.route_name === compatibleRoute
    ? target.route_name : allowed[0]
  return { name, params: { [parameter]: value! } }
}
