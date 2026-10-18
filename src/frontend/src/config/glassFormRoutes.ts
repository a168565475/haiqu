// 明确接入已核对的表单页；工作区滚动仍由各页面的布局负责。
export const glassFormRouteNames = [
  'inquiry-create', 'inquiry-edit',
  'sales-order-create', 'sales-order-edit', 'quotation-edit',
  'production-task-create', 'production-task-manual-create', 'production-task-edit',
  'bom-create', 'bom-edit',
  'purchase-order-create', 'purchase-order-create-details', 'purchase-order-confirm',
  'supplier-purchase-sheet-editor',
  'manual-material-inbound', 'material-purchase-inbound', 'material-quality-confirmation',
  'material-issue-new', 'material-issue-edit',
  'workshop-scheduling-new', 'workshop-scheduling-edit',
  'wage-scheme-new', 'wage-scheme-change', 'work-report-new', 'work-report-edit',
  'workshop-outsourcing-new', 'workshop-outsourcing-tube-new',
  'sample-new', 'sample-edit', 'sample-director-review', 'sample-materials',
  'sample-warehouse-review', 'sample-material-issue', 'sample-material-issue-confirm',
] as const
