export interface MenuItem {
  key: string
  label: string
  to?: { name: string }
  openInNewTab?: boolean
  permission?: string
  anyPermissions?: string[]
  allPermissions?: string[]
  available?: boolean
  children?: MenuItem[]
}

export const sidebarMenuItems: MenuItem[] = [
  {
    key: 'workbench', label: '工作台',
    children: [
      { key: 'production-workbench', label: '生产负责人工作台', to: { name: 'production-workbench' }, permission: 'production_tasks.view_productiontask' },
      { key: 'production-overview', label: '生产总览', to: { name: 'production-overview' }, permission: 'production_tasks.view_productiontask' },
      { key: 'workshop-workbench', label: '车间主管工作台', to: { name: 'workshop-workbench' }, anyPermissions: ['production_scheduling.view_productionschedule', 'workshop_reporting.view_workreport', 'inventory.view_finishedgoodsreceipt'] },
      { key: 'purchase-workbench', label: '采购工作台', to: { name: 'purchase-workbench' }, permission: 'procurement.view_purchaseorder' },
      { key: 'sewing-outsourcing-workbench', label: '车缝外协工作台', to: { name: 'sewing-outsourcing-workbench' }, permission: 'outsourcing.view_outsourcingorder' },
      { key: 'merchandiser-workbench', label: '跟单工作台', to: { name: 'merchandiser-workbench' }, permission: 'production_tasks.view_productiontask' },
      { key: 'warehouse-workbench', label: '仓库工作台', to: { name: 'warehouse-workbench' } },
    ],
  },
  {
    key: 'customer-management',
    label: '客户',
    children: [
      { key: 'customers', label: '客户列表', to: { name: 'customers' }, permission: 'customers.view_customeraccount' },
      { key: 'complaints', label: '客诉管理', to: { name: 'complaints' }, permission: 'customers.view_customercomplaint' },
      { key: 'inquiries', label: '询盘管理', to: { name: 'inquiries' }, permission: 'inquiries.view_inquiry' },
      { key: 'quotations', label: '报价管理', to: { name: 'quotations' }, permission: 'quotations.view_quotation' },
      { key: 'sales-orders', label: '销售订单', to: { name: 'sales-orders' }, permission: 'sales_orders.view_salesorder' },
      { key: 'tasks', label: '任务中心', to: { name: 'tasks' }, permission: 'workflow.view_businesstask' },
      { key: 'analytics', label: '分析中心', permission: 'customers.view_customeraccount' },
    ],
  },
  {
    key: 'sample-management',
    label: '样品',
    children: [
      { key: 'samples', label: '打样申请', to: { name: 'samples' }, permission: 'samples.view_samplerequest' },
      { key: 'sample-library', label: '样品库', to: { name: 'sample-inventory' }, permission: 'samples.view_sampleinventoryline' },
    ],
  },
  {
    key: 'product-management',
    label: '产品',
    children: [
      { key: 'product-catalog', label: '产品管理', to: { name: 'product-catalog' }, permission: 'product_catalog.view_productcatalog' },
      { key: 'material-catalog', label: '原料管理', to: { name: 'material-catalog' }, permission: 'material_catalog.view_materialcatalog' },
    ],
  },
  {
    key: 'production-management',
    label: '生产',
    children: [
      { key: 'production-tasks', label: '生产订单', to: { name: 'production-tasks' }, permission: 'production_tasks.view_productiontask' },
      { key: 'boms', label: 'BOM 管理', to: { name: 'boms' }, permission: 'boms.view_bom' },
    ],
  },
  {
    key: 'procurement-management',
    label: '采购',
    children: [
      { key: 'purchase-orders', label: '采购需求', to: { name: 'purchase-orders' }, anyPermissions: ['procurement.view_purchaseorder', 'procurement.view_supplier'] },
      { key: 'packaging-purchases', label: '包材采购', to: { name: 'packaging-purchases' }, permission: 'procurement.manage_packagingpurchase' },
      { key: 'purchase-plans', label: '采购计划表', to: { name: 'purchase-plans' }, permission: 'procurement.view_purchaseorder' },
      { key: 'purchase-tracking', label: '采购跟踪', to: { name: 'purchase-tracking' }, anyPermissions: ['procurement.view_purchaseorder', 'procurement.manage_packagingpurchase'] },
      { key: 'purchase-alerts', label: '采购提醒', to: { name: 'purchase-alerts' }, anyPermissions: ['procurement.view_purchaseorder', 'procurement.manage_packagingpurchase'] },
      { key: 'purchase-return-records', label: '退货记录', to: { name: 'purchase-return-records' }, anyPermissions: ['access_control.confirm_purchasereturn', 'procurement.submit_purchaseorder', 'procurement.view_purchaseorder', 'procurement.manage_packagingpurchase'] },
    ],
  },
  {
    key: 'workshop-management',
    label: '车间',
    children: [
      { key: 'workshop-scheduling', label: '计划排产', to: { name: 'workshop-scheduling' }, permission: 'production_scheduling.view_productionschedule' },
      { key: 'workshop-internal-plan', label: '作业计划', to: { name: 'workshop-metalworking-plan' }, permission: 'production_scheduling.view_productionschedule' },
      { key: 'workshop-material-tracking', label: '材料跟踪', to: { name: 'workshop-material-tracking' }, permission: 'production_scheduling.view_productionschedule' },
      { key: 'workshop-outsourcing', label: '委外加工', to: { name: 'workshop-outsourcing' }, anyPermissions: ['outsourcing.view_outsourcingorder', 'material_issues.view_metalprocessingsource', 'outsourcing.manage_cutpieceprinting'] },
      { key: 'workshop-powder-coating', label: '喷塑收发', to: { name: 'workshop-powder-coating' }, anyPermissions: ['outsourcing.view_outsourcingorder', 'material_issues.view_metalprocessingsource'] },
      { key: 'workshop-outsourcing-movements', label: '外协收发', to: { name: 'workshop-outsourcing-movements' }, anyPermissions: ['outsourcing.view_outsourcingorder', 'outsourcing.manage_cutpieceprinting', 'outsourcing.confirm_dispatch_outsourcingorder', 'outsourcing.confirm_return_outsourcingorder'] },
        { key: 'workshop-sewing-tracking', label: '布面跟踪单', to: { name: 'workshop-sewing-tracking' }, anyPermissions: ['outsourcing.view_outsourcingorder', 'outsourcing.manage_cutpieceprinting'] },
      { key: 'wage-schemes', label: '工价方案', to: { name: 'wage-schemes' }, permission: 'workshop_reporting.view_wagescheme' },
      { key: 'work-report-days', label: '报工记录', to: { name: 'work-report-days' }, allPermissions: ['workshop_reporting.view_workreport'] },
      { key: 'workshop-daily-report', label: '车间日报', to: { name: 'workshop-daily-report' }, anyPermissions: ['material_issues.view_metalprocessingsource', 'workshop_reporting.view_workreport'] },
      { key: 'workshop-semi-receipt-records', label: '半成品入库记录', to: { name: 'workshop-semi-receipt-records' }, allPermissions: ['production_scheduling.view_productionschedule', 'inventory.view_internalsemifinishedreceipt'] },
      { key: 'workshop-finished-receipt-records', label: '成品入库记录', to: { name: 'workshop-finished-receipt-records' }, allPermissions: ['production_scheduling.view_productionschedule', 'inventory.view_finishedgoodsreceipt'] },
      { key: 'workshop-configuration', label: '生产配置', to: { name: 'workshop-configuration' }, anyPermissions: ['workshop_config.view_workshop', 'workshop_config.view_workshopemployee', 'workshop_config.view_operation'] },
    ],
  },
  {
    key: 'warehouse-management',
    label: '仓库',
    children: [
      { key: 'finished-goods-inventory', label: '成品库存', to: { name: 'finished-goods-inventory' }, permission: 'inventory.view_finishedgoodsreceipt' },
      { key: 'material-inventory', label: '材料库存', to: { name: 'material-inventory' }, permission: 'inventory.view_materialinbound' },
      { key: 'material-transfers', label: '材料收发', to: { name: 'material-transfers' }, permission: 'inventory.receive_material' },
      { key: 'purchase-inbounds', label: '采购入库', to: { name: 'purchase-inbounds' }, anyPermissions: ['inventory.receive_material', 'inventory.quality_confirm_material'] },
      { key: 'purchase-receipt-records', label: '入库记录', to: { name: 'purchase-receipt-records' }, anyPermissions: ['inventory.receive_material', 'inventory.quality_confirm_material', 'inventory.view_material_receipt'] },
      { key: 'purchase-returns', label: '退货明细', to: { name: 'purchase-returns' }, anyPermissions: ['inventory.receive_material', 'inventory.quality_confirm_material'] },
      { key: 'material-issues', label: '车间领料', to: { name: 'material-issues' }, permission: 'material_issues.view_materialissue' },
      { key: 'semi-receipt-records', label: '车间入库', to: { name: 'semi-receipt-records' }, permission: 'inventory.view_internalsemifinishedreceipt' },
      { key: 'warehouse-outsourcing', label: '委外管理', to: { name: 'warehouse-outsourcing' }, anyPermissions: ['outsourcing.confirm_dispatch_outsourcingorder', 'outsourcing.confirm_return_outsourcingorder', 'outsourcing.return_raw_outsourcingorder', 'material_issues.create_metalprocessingoriginalhandoff', 'material_issues.confirm_metalprocessingexternalhandoff', 'material_issues.confirm_metalprocessingexternalreturn'] },
    ],
  },
  {
    key: 'finance-management',
    label: '财务',
    children: [
      { key: 'finance-accounts', label: '公司账户信息', to: { name: 'finance-accounts' }, permission: 'finance.view_financeaccount' },
      { key: 'finance-subjects', label: '会计科目', to: { name: 'finance-subjects' }, permission: 'finance.view_accountingsubject' },
      { key: 'finance-statements', label: '应收对账单', to: { name: 'finance-statements' }, permission: 'finance.view_receivablestatement' },
      { key: 'finance-purchase-payables', label: '采购应付', to: { name: 'finance-purchase-payables' }, permission: 'finance.view_purchasepayable' },
      { key: 'finance-receipts', label: '收款确认', to: { name: 'finance-receipts' }, permission: 'finance.view_receipt' },
    ],
  },
  {
    key: 'employee-management',
    label: '行政',
    children: [
      { key: 'employee-list', label: '员工管理', to: { name: 'employee-list' } },
      { key: 'attendance', label: '考勤管理', to: { name: 'wecom-attendance' }, permission: 'attendance.view_attendance' },
    ],
  },
  {
    key: 'boards',
    label: '看板',
    children: [
      { key: 'production-line-board', label: '产线大屏', to: { name: 'production-line-board' }, openInNewTab: true },
      { key: 'warehouse-board', label: '仓库大屏', to: { name: 'warehouse-board' }, openInNewTab: true },
      { key: 'production-progress-board', label: '生产进度看板', to: { name: 'production-progress-board' }, openInNewTab: true },
      { key: 'production-board', label: '生产大屏', to: { name: 'production-board' }, openInNewTab: true },
    ],
  },
]

export const settingsMenu = { key: 'settings', label: '配置' }
