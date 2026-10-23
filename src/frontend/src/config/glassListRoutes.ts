// 仅独立列表接入公共骨架；详情、编辑和内嵌列表保留各自布局。
export const glassListRouteNames = [
  'finance-accounts',
  'finance-subjects',
  'finance-statements',
  'finance-receipts',
  'inquiries', 'quotations', 'sales-orders', 'tasks',
  'contacts', 'complaints', 'samples', 'sample-inventory', 'sample-outbound', 'sample-loans',
  'products', 'raw-materials', 'product-catalog', 'material-catalog', 'boms',
  'suppliers', 'purchase-orders', 'purchase-inbounds', 'purchase-returns', 'supplier-purchase-sheets', 'purchase-contract-templates',
  'workshop-outsourcing', 'workshop-outsourcing-factories',
  'production-tasks', 'workshop-scheduling', 'workshop-metalworking-plan', 'workshop-cutting-plan', 'workshop-sewing-plan', 'workshop-assembly-plan',
  'material-issues', 'wage-schemes', 'work-report-days', 'finished-goods-inventory', 'finished-goods-outbounds', 'material-inventory', 'material-inbound-details', 'semi-receipt-records',
  'email-account-settings', 'number-rules', 'master-data-center', 'reference-data-settings', 'production-data', 'employee-list', 'wecom-attendance',
] as const
