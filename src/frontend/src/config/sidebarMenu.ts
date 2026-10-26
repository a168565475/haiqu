export interface MenuItem {
  key: string
  label: string
  to?: { name: string }
  openInNewTab?: boolean
  defaultChildKey?: string
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
    ],
  },
  {
    key: 'customer-management',
    label: '客户',
    defaultChildKey: 'customers',
    children: [
      { key: 'customers', label: '客户列表', to: { name: 'customers' }, permission: 'customers.view_customeraccount' },
      { key: 'complaints', label: '客诉管理', to: { name: 'complaints' }, permission: 'customers.view_customercomplaint' },
      { key: 'inquiries', label: '询盘管理', to: { name: 'inquiries' }, permission: 'inquiries.view_inquiry' },
      { key: 'quotations', label: '报价管理', to: { name: 'quotations' }, permission: 'quotations.view_quotation' },
      { key: 'sales-orders', label: '销售订单', to: { name: 'sales-orders' } },
      { key: 'tasks', label: '任务中心', to: { name: 'tasks' }, permission: 'workflow.view_businesstask' },
      { key: 'analytics', label: '分析中心', permission: 'customers.view_customeraccount' },
    ],
  },
  {
    key: 'sample-management',
    label: '样品',
    defaultChildKey: 'samples',
    children: [
      { key: 'samples', label: '打样申请', to: { name: 'samples' }, permission: 'samples.view_samplerequest' },
      { key: 'sample-library', label: '样品库', to: { name: 'sample-inventory' }, permission: 'samples.view_sampleinventoryline' },
    ],
  },
  {
    key: 'product-management',
    label: '产品',
    defaultChildKey: 'products',
    children: [
      { key: 'products', label: '产品信息', to: { name: 'products' }, permission: 'products.view_productinformation' },
      { key: 'product-catalog', label: '产品管理', to: { name: 'product-catalog' }, permission: 'product_catalog.view_productcatalog' },
      { key: 'raw-materials', label: '原料信息', to: { name: 'raw-materials' }, permission: 'products.view_rawmaterialinformation' },
      { key: 'material-catalog', label: '原料管理', to: { name: 'material-catalog' }, permission: 'material_catalog.view_materialcatalog' },
    ],
  },
  {
    key: 'production-management',
    label: '生产',
    defaultChildKey: 'production-tasks',
    children: [
      { key: 'production-tasks', label: '生产订单', to: { name: 'production-tasks' }, permission: 'production_tasks.view_productiontask' },
      { key: 'boms', label: 'BOM 管理', to: { name: 'boms' }, permission: 'boms.view_bom' },
    ],
  },
  {
    key: 'procurement-management',
    label: '采购',
    defaultChildKey: 'purchase-orders',
    children: [
      { key: 'purchase-orders', label: '采购订单', to: { name: 'purchase-orders' }, anyPermissions: ['procurement.view_purchaseorder', 'procurement.view_supplier'] },
      { key: 'purchase-inbounds', label: '采购入库', to: { name: 'purchase-inbounds' }, anyPermissions: ['inventory.receive_material', 'inventory.quality_confirm_material'] },
      { key: 'purchase-returns', label: '退货明细', to: { name: 'purchase-returns' }, permission: 'procurement.view_purchaseorder' },
    ],
  },
  {
    key: 'workshop-management',
    label: '车间',
    defaultChildKey: 'workshop-scheduling',
    children: [
      { key: 'workshop-scheduling', label: '计划排产', to: { name: 'workshop-scheduling' }, permission: 'production_scheduling.view_productionschedule' },
      { key: 'workshop-internal-plan', label: '内部计划', to: { name: 'workshop-metalworking-plan' }, permission: 'production_scheduling.view_productionschedule' },
      { key: 'workshop-outsourcing', label: '委外加工', to: { name: 'workshop-outsourcing' }, anyPermissions: ['outsourcing.view_outsourcingorder', 'material_issues.view_metalprocessingsource'] },
      { key: 'material-issues', label: '生产领料', to: { name: 'material-issues' }, permission: 'material_issues.view_materialissue' },
      { key: 'wage-schemes', label: '工价方案', to: { name: 'wage-schemes' }, permission: 'workshop_reporting.view_wagescheme' },
      { key: 'work-report-days', label: '报工记录', to: { name: 'work-report-days' }, allPermissions: ['workshop_reporting.view_workreport'] },
      { key: 'workshop-configuration', label: '生产配置', to: { name: 'workshop-configuration' }, permission: 'workshop_config.view_workshop' },
    ],
  },
  {
    key: 'warehouse-management',
    label: '仓库',
    defaultChildKey: 'finished-goods-inventory',
    children: [
      { key: 'finished-goods-inventory', label: '成品库存', to: { name: 'finished-goods-inventory' }, permission: 'inventory.view_finishedgoodsreceipt' },
      { key: 'material-inventory', label: '材料库存', to: { name: 'material-inventory' }, permission: 'inventory.view_materialinbound' },
    ],
  },
  {
    key: 'finance-management',
    label: '财务',
    defaultChildKey: 'finance-accounts',
    children: [
      { key: 'finance-accounts', label: '公司账户信息', to: { name: 'finance-accounts' }, permission: 'finance.view_financeaccount' },
      { key: 'finance-subjects', label: '会计科目', to: { name: 'finance-subjects' }, permission: 'finance.view_accountingsubject' },
      { key: 'finance-statements', label: '应收对账单', to: { name: 'finance-statements' }, permission: 'finance.view_receivablestatement' },
      { key: 'finance-receipts', label: '收款确认', to: { name: 'finance-receipts' }, permission: 'finance.view_receipt' },
    ],
  },
  {
    key: 'employee-management',
    label: '行政',
    defaultChildKey: 'employee-list',
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
