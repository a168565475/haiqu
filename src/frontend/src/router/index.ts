import { createRouter, createWebHistory } from 'vue-router'
import { ElMessage } from 'element-plus'
import { startWeComLoginIfNeeded, wecomRouteRedirect } from './wecomGuard'

import { useAuthStore } from '@/stores/auth'
import LoginView from '@/views/LoginView.vue'

const WorkbenchLandingView = () => import('@/views/workbench/WorkbenchLandingView.vue')
const NotFoundView = () => import('@/views/NotFoundView.vue')
const PurchaseReturnListView = () => import('@/views/procurement/PurchaseReturnListView.vue')
const CustomerListView = () => import('@/views/customers/CustomerListView.vue')
const CustomerDetailView = () => import('@/views/customers/CustomerDetailView.vue')
const CustomerCreateView = () => import('@/views/customers/CustomerCreateView.vue')
const CustomerEditView = () => import('@/views/customers/CustomerEditView.vue')
const CustomerDuplicateCenterView = () => import('@/views/customers/CustomerDuplicateCenterView.vue')
const ContactListView = () => import('@/views/contacts/ContactListView.vue')
const InquiryListView = () => import('@/views/inquiries/InquiryListView.vue')
const InquiryEditorView = () => import('@/views/inquiries/InquiryEditorView.vue')
const InquiryDetailView = () => import('@/views/inquiries/InquiryDetailView.vue')
const SampleListView = () => import('@/views/samples/SampleListView.vue')
const SampleDetailView = () => import('@/views/samples/SampleDetailView.vue')
const SampleApplicationCreateView = () => import('@/views/samples/SampleApplicationCreateView.vue')
const SampleDirectorReviewView = () => import('@/views/samples/SampleDirectorReviewView.vue')
const SampleMaterialDetailView = () => import('@/views/samples/SampleMaterialDetailView.vue')
const SampleWarehouseReviewView = () => import('@/views/samples/SampleWarehouseReviewView.vue')
const SampleMaterialIssueView = () => import('@/views/samples/SampleMaterialIssueView.vue')
const SampleFeeView = () => import('@/views/samples/SampleFeeView.vue')
const SampleFulfillmentView = () => import('@/views/samples/SampleFulfillmentView.vue')
const SampleInventoryView = () => import('@/views/samples/SampleInventoryView.vue')
const SampleInventoryReceiptDetailView = () => import('@/views/samples/SampleInventoryReceiptDetailView.vue')
const SampleOutboundView = () => import('@/views/samples/SampleOutboundView.vue')
const SampleOutboundDetailView = () => import('@/views/samples/SampleOutboundDetailView.vue')
const SampleLoanView = () => import('@/views/samples/SampleLoanView.vue')
const SampleLoanDetailView = () => import('@/views/samples/SampleLoanDetailView.vue')
const BomListView = () => import('@/views/boms/BomListView.vue')
const BomCreateView = () => import('@/views/boms/BomCreateView.vue')
const BomEditorView = () => import('@/views/boms/BomEditorView.vue')
const BomPreviewView = () => import('@/views/boms/BomPreviewView.vue')
const ProductionTaskListView = () => import('@/views/production/ProductionTaskListView.vue')
const ProductionTaskCreateView = () => import('@/views/production/ProductionTaskCreateView.vue')
const ProductionTaskDetailView = () => import('@/views/production/ProductionTaskDetailView.vue')
const ProductionTaskEditView = () => import('@/views/production/ProductionTaskEditView.vue')
const QuotationListView = () => import('@/views/quotations/QuotationListView.vue')
const QuotationEditorView = () => import('@/views/quotations/QuotationEditorView.vue')
const QuotationPackagingView = () => import('@/views/quotations/QuotationPackagingView.vue')
const QuotationPreviewView = () => import('@/views/quotations/QuotationPreviewView.vue')
const QuotationVersionDiffView = () => import('@/views/quotations/QuotationVersionDiffView.vue')
const QuotationPriceHistoryView = () => import('@/views/quotations/QuotationPriceHistoryView.vue')
const SalesOrderListView = () => import('@/views/salesOrders/SalesOrderListView.vue')
const SalesOrderEditorView = () => import('@/views/salesOrders/SalesOrderEditorView.vue')
const SalesOrderDetailView = () => import('@/views/salesOrders/SalesOrderDetailView.vue')
const TaskCenterView = () => import('@/views/tasks/TaskCenterView.vue')
const TaskDetailView = () => import('@/views/tasks/TaskDetailView.vue')
const ComplaintListView = () => import('@/views/complaints/ComplaintListView.vue')
const ComplaintDetailView = () => import('@/views/complaints/ComplaintDetailView.vue')
const ReferenceDataSettingsView = () => import('@/views/settings/ReferenceDataSettingsView.vue')
const AccessManagementView = () => import('@/views/settings/AccessManagementView.vue')
const MasterDataCenterView = () => import('@/views/settings/MasterDataCenterView.vue')
const NumberRulesView = () => import('@/views/settings/NumberRulesView.vue')
const InquiryHandlingSettingsView = () => import('@/views/settings/InquiryHandlingSettingsView.vue')
const EmailAccountSettingsView = () => import('@/views/settings/EmailAccountSettingsView.vue')
const ProductionDataView = () => import('@/views/settings/ProductionDataView.vue')
const ThemeSettingsView = () => import('@/views/settings/ThemeSettingsView.vue')
const ProductInformationView = () => import('@/views/products/ProductInformationView.vue')
const RawMaterialInformationView = () => import('@/views/products/RawMaterialInformationView.vue')
const RawMaterialManagementView = () => import('@/views/products/RawMaterialManagementView.vue')
const ProductManagementView = () => import('@/views/products/ProductManagementView.vue')
const SupplierListView = () => import('@/views/procurement/SupplierListView.vue')
const PurchaseOrderListView = () => import('@/views/procurement/PurchaseOrderListView.vue')
const PurchaseOrderFormView = () => import('@/views/procurement/PurchaseOrderFormView.vue')
const PurchaseOrderConfirmView = () => import('@/views/procurement/PurchaseOrderConfirmView.vue')
const PurchaseOrderDetailView = () => import('@/views/procurement/PurchaseOrderDetailView.vue')
const PurchaseSheetTemplateSelectView = () => import('@/views/procurement/PurchaseSheetTemplateSelectView.vue')
const SupplierPurchaseSheetListView = () => import('@/views/procurement/SupplierPurchaseSheetListView.vue')
const SupplierPurchaseSheetEditorView = () => import('@/views/procurement/SupplierPurchaseSheetEditorView.vue')
const PurchaseContractTemplateListView = () => import('@/views/procurement/PurchaseContractTemplateListView.vue')
const FinishedGoodsInventoryView = () => import('@/views/inventory/FinishedGoodsInventoryView.vue')
const FinishedGoodsOutboundFormView = () => import('@/views/inventory/FinishedGoodsOutboundFormView.vue')
const FinishedGoodsOutboundDetailView = () => import('@/views/inventory/FinishedGoodsOutboundDetailView.vue')
const MaterialInventoryView = () => import('@/views/inventory/MaterialInventoryView.vue')
const MaterialInventoryDetailView = () => import('@/views/inventory/MaterialInventoryDetailView.vue')
const MaterialPurchaseInboundView = () => import('@/views/inventory/MaterialPurchaseInboundView.vue')
const ManualMaterialInboundView = () => import('@/views/inventory/ManualMaterialInboundView.vue')
const MaterialQualityConfirmationView = () => import('@/views/inventory/MaterialQualityConfirmationView.vue')
const MaterialInboundDetailView = () => import('@/views/inventory/MaterialInboundDetailView.vue')
const PurchaseInboundListView = () => import('@/views/procurement/PurchaseInboundListView.vue')
const WorkshopConfigurationView = () => import('@/views/workshop/WorkshopConfigurationView.vue')
const ProductionSchedulingDetailView = () => import('@/views/workshop/ProductionSchedulingDetailView.vue')
const ProductionSchedulingFormView = () => import('@/views/workshop/ProductionSchedulingFormView.vue')
const ProductionSchedulingListView = () => import('@/views/workshop/ProductionSchedulingListView.vue')
const WorkshopPlanListView = () => import('@/views/workshop/WorkshopPlanListView.vue')
const MaterialIssueListView = () => import('@/views/workshop/material-issues/MaterialIssueListView.vue')
const MaterialIssueFormView = () => import('@/views/workshop/material-issues/MaterialIssueFormView.vue')
const MaterialIssueDetailView = () => import('@/views/workshop/material-issues/MaterialIssueDetailView.vue')
const WageSchemeListView = () => import('@/views/workshop/wage-schemes/WageSchemeListView.vue')
const WageSchemeFormView = () => import('@/views/workshop/wage-schemes/WageSchemeFormView.vue')
const WageSchemeDetailView = () => import('@/views/workshop/wage-schemes/WageSchemeDetailView.vue')
const WorkReportFormView = () => import('@/views/workshop/work-reports/WorkReportFormView.vue')
const WorkReportDayListView = () => import('@/views/workshop/work-reports/WorkReportDayListView.vue')
const WorkReportDayDetailView = () => import('@/views/workshop/work-reports/WorkReportDayDetailView.vue')
const FactoryDetailView = () => import('@/views/outsourcing/FactoryDetailView.vue')
const FactoryListView = () => import('@/views/outsourcing/FactoryListView.vue')
const OutsourcingOrderDetailView = () => import('@/views/outsourcing/OutsourcingOrderDetailView.vue')
const OutsourcingOrderListView = () => import('@/views/outsourcing/OutsourcingOrderListView.vue')
const OutsourcingReworkDetailView = () => import('@/views/outsourcing/OutsourcingReworkDetailView.vue')

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/auth/waiting-role',
      name: 'waiting-role',
      component: () => import('@/views/auth/WaitingRoleView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/auth/wecom-error',
      name: 'wecom-error',
      component: () => import('@/views/auth/WeComErrorView.vue'),
    },
    {
      path: '/settings/wecom',
      name: 'wecom-settings',
      component: () => import('@/views/settings/WeComSettingsView.vue'),
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'settings', headerTitle: '系统配置 / 企业微信管理', breadcrumbs: [{ label: '系统配置', to: '/settings' }, { label: '企业微信管理' }], pageWidth: 'fluid' },
    },
    {
      path: '/settings/notifications',
      name: 'notification-rules',
      component: () => import('@/views/settings/NotificationRulesView.vue'),
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'settings', headerTitle: '系统配置 / 通知规则', breadcrumbs: [{ label: '系统配置', to: '/settings' }, { label: '通知规则' }], pageWidth: 'fluid' },
    },
    {
      path: '/employees',
      name: 'employee-list',
      component: () => import('@/views/employees/EmployeeListView.vue'),
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'employee-list', headerTitle: '行政 / 员工管理', breadcrumbs: [{ label: '行政' }, { label: '员工管理' }], pageWidth: 'fluid' },
    },
    {
      path: '/attendance/wecom',
      name: 'wecom-attendance',
      component: () => import('@/views/attendance/WeComAttendanceView.vue'),
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'attendance', headerTitle: '行政 / 考勤管理', breadcrumbs: [{ label: '行政' }, { label: '考勤管理' }], pageWidth: 'fluid' },
    },
    {
      path: '/boards/production-line',
      name: 'production-line-board',
      component: () => import('@/views/boards/ProductionLineBoardView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/boards/warehouse',
      name: 'warehouse-board',
      component: () => import('@/views/boards/WarehouseBoardView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/boards/production-progress',
      name: 'production-progress-board',
      component: () => import('@/views/boards/ProductionProgressBoardView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/boards/production',
      name: 'production-board',
      component: () => import('@/views/boards/ProductionBoardView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/inventory/finished-goods/receive', name: 'assembly-finished-receipt',
      component: () => import('@/views/inventory/AssemblyFinishedReceiptView.vue'),
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'workshop-internal-plan', headerTitle: '生产车间 / 内部计划 / 成品入库', breadcrumbs: [{label:'生产车间'},{label:'内部计划',to:'/workshop/plans/assembly'},{label:'成品入库'}], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/inventory/semi-finished/receive', name: 'internal-semi-receipt',
      component: () => import('@/views/inventory/InternalSemiReceiptEntryView.vue'),
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'material-inventory', headerTitle: '生产车间 / 内部计划 / 半成品入库', breadcrumbs: [{label:'生产车间'},{label:'内部计划',to:'/workshop/plans/metalworking'},{label:'半成品入库'}], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/inventory/semi-finished/outbounds', name: 'semi-outbound-records',
      component: () => import('@/views/inventory/SemiReceiptRecordsView.vue'),
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'material-inventory', headerTitle: '仓库管理 / 半成品出库记录', breadcrumbs: [{label:'仓库管理'},{label:'半成品出库记录'}], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/inventory/semi-finished/receipts', name: 'semi-receipt-records',
      component: () => import('@/views/inventory/SemiReceiptRecordsView.vue'),
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'material-inventory', headerTitle: '仓库管理 / 半成品入库记录', breadcrumbs: [{label:'仓库管理'},{label:'材料库存',to:'/inventory/materials'},{label:'半成品入库记录'}], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/inventory/semi-finished/tube-return', name: 'inventory-tube-return',
      redirect: to => {
        const { order_id: orderId, ...query } = to.query
        return typeof orderId === 'string' && orderId.trim()
          ? { name: 'warehouse-outsourcing-tube-return', params: { id: orderId }, query }
          : { name: 'warehouse-outsourcing' }
      },
    },
    {
      path: '/login',
      name: 'login',
      component: LoginView,
    },
    {
      path: '/',
      name: 'home',
      component: WorkbenchLandingView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workbench',
        headerTitle: '工作台',
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workbench/manager',
      name: 'manager-workbench',
      redirect: { name: 'home' },
    },
    {
      path: '/workbench/sales',
      name: 'sales-workbench',
      redirect: { name: 'home' },
    },
    {
      path: '/workbench/production',
      name: 'production-workbench',
      component: () => import('@/views/workbench/production/ProductionDashboardView.vue'),
      props: { role: 'owner' },
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'production-workbench',
        headerTitle: '生产负责人工作台', pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/workbench/production-overview',
      name: 'production-overview',
      component: () => import('@/views/workbench/production/ProductionDashboardView.vue'),
      props: { role: 'executive' },
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'production-overview',
        headerTitle: '生产总览', pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/workbench/workshop',
      name: 'workshop-workbench',
      component: () => import('@/views/workbench/production/ProductionDashboardView.vue'),
      props: { role: 'workshop' },
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'workshop-workbench',
        headerTitle: '车间主管工作台', pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/customers',
      name: 'customers',
      component: CustomerListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'customers',
        headerTitle: '客户管理',
        breadcrumbs: [{ label: '客户管理' }, { label: '客户列表' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/customers/new',
      name: 'customer-create',
      component: CustomerCreateView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'customers',
        headerTitle: '客户管理',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '新建客户' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/customers/duplicates',
      name: 'customer-duplicates',
      component: CustomerDuplicateCenterView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'customers',
        headerTitle: '重复客户中心',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '重复客户中心' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/customers/:customerId/inquiries',
      name: 'customer-inquiries',
      component: CustomerDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'customers', headerTitle: '客户管理',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '客户详情' }, { label: '询盘' }], pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/customers/:customerId/quotations',
      name: 'customer-quotations',
      component: CustomerDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'customers', headerTitle: '客户管理',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '客户详情' }, { label: '报价' }], pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/customers/:customerId/samples',
      name: 'customer-samples',
      component: CustomerDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'customers', headerTitle: '客户管理',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '客户详情' }, { label: '样品' }], pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/customers/:customerId/orders',
      name: 'customer-orders',
      component: CustomerDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'customers', headerTitle: '客户管理',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '客户详情' }, { label: '订单' }], pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/customers/:customerId',
      name: 'customer-detail',
      component: CustomerDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'customers', headerTitle: '客户管理',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '客户详情' }], pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/customers/:customerId/edit',
      name: 'customer-edit',
      component: CustomerEditView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'customers', headerTitle: '客户管理',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '编辑客户' }], pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/contacts',
      name: 'contacts',
      component: ContactListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'customers',
        headerTitle: '客户管理',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '联系人' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/customers/:customerId/contacts',
      name: 'customer-contacts',
      redirect: to => ({ name: 'customer-detail', params: { customerId: to.params.customerId }, query: to.query, hash: '#customer-contacts' }),
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'customers',
        headerTitle: '客户管理',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '客户详情' }, { label: '联系人' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/customers/:customerId/timeline',
      name: 'customer-timeline',
      component: CustomerDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'customers', headerTitle: '客户时间线',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '客户详情' }, { label: '时间轴' }], pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/customers/:customerId/tasks',
      name: 'customer-tasks',
      component: CustomerDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'customers', headerTitle: '客户任务',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '客户详情' }, { label: '任务' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/customers/:customerId/complaints',
      name: 'customer-complaints',
      component: CustomerDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'customers', headerTitle: '客户客诉',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '客户详情' }, { label: '客诉' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/customers/:customerId/transfer',
      name: 'customer-transfer',
      component: CustomerDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'customers', headerTitle: '客户转移',
        breadcrumbs: [{ label: '客户管理', to: '/customers' }, { label: '客户转移' }], pageWidth: 'fluid',
      },
    },
    {
      path: '/complaints',
      name: 'complaints',
      component: ComplaintListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'complaints',
        headerTitle: '客诉管理',
        pageWidth: 'fluid',
      },
    },
    {
      path: '/complaints/:complaintId',
      name: 'complaint-detail',
      component: ComplaintDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'complaints',
        headerTitle: '客诉详情',
        pageWidth: 'fluid',
      },
    },
    {
      path: '/inquiries',
      name: 'inquiries',
      component: InquiryListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'inquiries',
        headerTitle: '询盘管理',
        breadcrumbs: [{ label: '客户管理' }, { label: '询盘管理' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/inquiries/new',
      name: 'inquiry-create',
      component: InquiryEditorView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'inquiries',
        headerTitle: '新建询盘',
        flushPage: true,
        breadcrumbs: [{ label: '询盘管理', to: '/inquiries' }, { label: '新建询盘' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/inquiries/:inquiryId/edit',
      name: 'inquiry-edit',
      component: InquiryEditorView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'inquiries',
        headerTitle: '编辑询盘',
        flushPage: true,
        breadcrumbs: [{ label: '询盘管理', to: '/inquiries' }, { label: '编辑询盘' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/inquiries/:inquiryId',
      name: 'inquiry-detail',
      component: InquiryDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'inquiries',
        headerTitle: '询盘详情',
        flushPage: true,
        breadcrumbs: [{ label: '询盘管理', to: '/inquiries' }, { label: '询盘详情' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/quotations/price-history',
      name: 'quotation-price-history',
      component: QuotationPriceHistoryView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'quotations',
        headerTitle: '历史价格趋势',
        breadcrumbs: [{ label: '客户管理' }, { label: '报价管理', to: '/quotations' }, { label: '历史价格' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/quotations/:quotationId/versions',
      name: 'quotation-versions',
      component: QuotationVersionDiffView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'quotations',
        headerTitle: '报价版本树与差异',
        breadcrumbs: [{ label: '报价管理', to: '/quotations' }, { label: '版本记录与差异比较' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/quotations/:quotationId/preview',
      name: 'quotation-preview',
      component: QuotationPreviewView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'quotations',
        headerTitle: '报价管理',
        breadcrumbs: [{ label: '客户管理' }, { label: '报价管理', to: '/quotations' }, { label: '报价预览' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/quotations/:quotationId/packaging/:lineId',
      name: 'quotation-packaging',
      component: QuotationPackagingView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'quotations',
        headerTitle: '报价管理',
        breadcrumbs: [{ label: '客户管理' }, { label: '报价管理', to: '/quotations' }, { label: '包装配置' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/boms',
      name: 'boms',
      component: BomListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'boms',
        headerTitle: '生产管理 / BOM 管理',
        breadcrumbs: [{ label: '生产管理' }, { label: 'BOM 管理' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/sales-orders',
      name: 'sales-orders',
      component: SalesOrderListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'sales-orders',
        headerTitle: '销售管理 / 销售订单',
        breadcrumbs: [{ label: '销售管理' }, { label: '销售订单' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/sales-orders/new',
      name: 'sales-order-create',
      component: SalesOrderEditorView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'sales-orders', headerTitle: '销售管理 / 销售订单',
        breadcrumbs: [{ label: '销售管理' }, { label: '销售订单', to: '/sales-orders' }, { label: '新建' }], pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/sales-orders/:orderId/edit',
      name: 'sales-order-edit',
      component: SalesOrderEditorView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'sales-orders', headerTitle: '销售管理 / 销售订单',
        breadcrumbs: [{ label: '销售管理' }, { label: '销售订单', to: '/sales-orders' }, { label: '编辑草稿' }], pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/sales-orders/:orderId',
      name: 'sales-order-detail',
      component: SalesOrderDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'sales-orders', headerTitle: '销售管理 / 销售订单',
        breadcrumbs: [{ label: '销售管理' }, { label: '销售订单', to: '/sales-orders' }, { label: '订单协同' }], pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/boms/new',
      name: 'bom-create',
      component: BomCreateView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'boms',
        headerTitle: '生产管理 / BOM管理 / 新建BOM',
        breadcrumbs: [{ label: '生产管理' }, { label: 'BOM管理', to: '/boms' }, { label: '新建BOM' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/boms/:bomId/preview',
      name: 'bom-preview',
      component: BomPreviewView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'boms',
        headerTitle: '生产管理 / BOM 管理',
        breadcrumbs: [{ label: '生产管理' }, { label: 'BOM 管理', to: '/boms' }, { label: 'BOM 预览' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/boms/:bomId/edit',
      name: 'bom-edit',
      component: BomEditorView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'boms',
        headerTitle: '生产管理 / BOM 管理',
        breadcrumbs: [{ label: '生产管理' }, { label: 'BOM 管理', to: '/boms' }, { label: '编辑 BOM' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/production-tasks',
      name: 'production-tasks',
      component: ProductionTaskListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'production-tasks',
        headerTitle: '生产管理 / 生产订单',
        breadcrumbs: [{ label: '生产管理' }, { label: '生产订单' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/production-tasks/new',
      name: 'production-task-create',
      component: ProductionTaskCreateView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'production-tasks',
        headerTitle: '生产管理 / 生产订单',
        breadcrumbs: [{ label: '生产管理' }, { label: '生产订单', to: '/production-tasks' }, { label: '新增生产任务单' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/production-tasks/new/manual',
      name: 'production-task-manual-create',
      component: ProductionTaskCreateView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'production-tasks',
        headerTitle: '生产管理 / 生产任务单',
        breadcrumbs: [{ label: '生产管理' }, { label: '生产任务单', to: '/production-tasks' }, { label: '手动创建生产任务单' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/production-tasks/:taskId/edit',
      name: 'production-task-edit',
      component: ProductionTaskEditView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'production-tasks',
        headerTitle: '生产管理 / 生产订单',
        breadcrumbs: [{ label: '生产管理' }, { label: '生产订单', to: '/production-tasks' }, { label: '编辑生产任务单' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/production-tasks/:taskId',
      name: 'production-task-detail',
      component: ProductionTaskDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'production-tasks',
        headerTitle: '生产管理 / 生产订单',
        breadcrumbs: [{ label: '生产管理' }, { label: '生产订单', to: '/production-tasks' }, { label: '生产任务单详情' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/samples',
      name: 'samples',
      component: SampleListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'samples',
        headerTitle: '样品管理 / 打样申请',
        breadcrumbs: [{ label: '样品管理' }, { label: '打样申请' }],
        flushPage: true,
        pageWidth: 'fluid',
      },
    },
    {
      path: '/samples/request/new',
      name: 'sample-request-new',
      redirect: to => ({ name: 'sample-new', query: to.query }),
    },
    {
      path: '/samples/new',
      name: 'sample-new',
      component: SampleApplicationCreateView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'samples',
        headerTitle: '样品跟进 / 创建打样申请',
        breadcrumbs: [{ label: '样品跟进', to: '/samples' }, { label: '创建打样申请' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/samples/inventory',
      name: 'sample-inventory',
      component: SampleInventoryView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'sample-library',
        headerTitle: '样品管理',
        pageWidth: 'fluid',
      },
    },
    {
      path: '/samples/inventory/receipts/:receiptId',
      name: 'sample-inventory-receipt-detail',
      component: SampleInventoryReceiptDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'sample-library',
        headerTitle: '样品管理',
        pageWidth: 'fluid',
      },
    },
    {
      path: '/samples/outbound',
      name: 'sample-outbound',
      component: SampleOutboundView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'sample-library',
        headerTitle: '样品管理',
        pageWidth: 'fluid',
      },
    },
    {
      path: '/samples/outbound/documents/:outboundId',
      name: 'sample-outbound-detail',
      component: SampleOutboundDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'sample-library',
        headerTitle: '样品管理',
        pageWidth: 'fluid',
      },
    },
    {
      path: '/samples/loans',
      name: 'sample-loans',
      component: SampleLoanView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'sample-library',
        headerTitle: '样品管理',
        pageWidth: 'fluid',
      },
    },
    {
      path: '/samples/loans/documents/:loanId',
      name: 'sample-loan-detail',
      component: SampleLoanDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'sample-library',
        headerTitle: '样品管理',
        pageWidth: 'fluid',
      },
    },
    {
      path: '/samples/:sampleId/warehouse-review',
      name: 'sample-warehouse-review',
      component: SampleWarehouseReviewView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'samples',
        headerTitle: '样品跟进 / 仓库核对材料',
        breadcrumbs: [{ label: '样品跟进', to: '/samples' }, { label: '仓库核对材料' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/samples/:sampleId/material-issue',
      name: 'sample-material-issue',
      component: SampleMaterialIssueView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'samples',
        headerTitle: '样品跟进 / 发起样品领料',
        breadcrumbs: [{ label: '样品跟进', to: '/samples' }, { label: '发起样品领料' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/samples/:sampleId/material-issue/confirm',
      name: 'sample-material-issue-confirm',
      component: SampleMaterialIssueView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'samples',
        headerTitle: '样品跟进 / 确认样品领料',
        breadcrumbs: [{ label: '样品跟进', to: '/samples' }, { label: '确认样品领料' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/samples/:sampleId/materials/detail',
      name: 'sample-material-detail',
      component: SampleMaterialDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'samples',
        headerTitle: '样品跟进 / 用料需求详情',
        breadcrumbs: [{ label: '样品跟进', to: '/samples' }, { label: '用料需求详情' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/samples/:sampleId/materials',
      name: 'sample-materials',
      redirect: to => ({ name: 'sample-edit', params: to.params, query: { ...to.query, tab: 'materials' } }),
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'samples',
        headerTitle: '样品跟进 / 填写材料需求',
        breadcrumbs: [{ label: '样品跟进', to: '/samples' }, { label: '填写材料需求' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/samples/:sampleId/director-review',
      name: 'sample-director-review',
      component: SampleDirectorReviewView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'samples',
        headerTitle: '样品跟进 / 厂长确认打样申请',
        breadcrumbs: [{ label: '样品跟进', to: '/samples' }, { label: '厂长确认打样申请' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/samples/:sampleId/edit',
      name: 'sample-edit',
      component: () => import('@/views/samples/SampleEditorView.vue'),
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'samples', headerTitle: '样品跟进 / 编辑打样需求',
        breadcrumbs: [{ label: '样品跟进', to: '/samples' }, { label: '编辑打样需求' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/samples/:sampleId',
      name: 'sample-detail',
      component: SampleDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'samples',
        headerTitle: '样品流程',
        breadcrumbs: [{ label: '样品跟进', to: '/samples' }, { label: '打样申请详情' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/samples/:sampleId/fees',
      name: 'sample-fees',
      component: SampleFeeView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'samples',
        headerTitle: '样品费用处理',
        pageWidth: 'fluid',
      },
    },
    {
      path: '/samples/:sampleId/fulfillment',
      name: 'sample-fulfillment',
      component: SampleFulfillmentView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'samples',
        headerTitle: '样品管理',
        pageWidth: 'fluid',
      },
    },
    {
      path: '/quotations',
      name: 'quotations',
      component: QuotationListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'quotations',
        headerTitle: '报价管理',
        breadcrumbs: [{ label: '客户管理' }, { label: '报价管理' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/quotations/:quotationId/edit',
      name: 'quotation-edit',
      component: QuotationEditorView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'quotations',
        headerTitle: '报价管理',
        breadcrumbs: [{ label: '客户管理' }, { label: '报价管理', to: '/quotations' }, { label: '编辑报价' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/tasks',
      name: 'tasks',
      component: TaskCenterView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'tasks',
        headerTitle: '任务中心',
        breadcrumbs: [{ label: '任务中心' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/tasks/:taskId',
      name: 'task-detail',
      component: TaskDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'tasks',
        headerTitle: '任务详情',
        breadcrumbs: [{ label: '任务中心', to: '/tasks' }, { label: '任务详情' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/products',
      name: 'products',
      component: ProductInformationView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'products',
        headerTitle: '产品管理',
        breadcrumbs: [{ label: '产品管理' }, { label: '产品信息' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/raw-materials',
      name: 'raw-materials',
      component: RawMaterialInformationView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'raw-materials',
        headerTitle: '产品管理',
        breadcrumbs: [{ label: '产品管理' }, { label: '原料信息' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/material-catalog',
      name: 'material-catalog',
      component: RawMaterialManagementView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'material-catalog',
        headerTitle: '产品管理',
        breadcrumbs: [{ label: '产品管理' }, { label: '原料管理' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/product-catalog',
      name: 'product-catalog',
      component: ProductManagementView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'product-catalog',
        headerTitle: '产品管理',
        breadcrumbs: [{ label: '产品管理' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/workshop/configuration',
      name: 'workshop-configuration',
      component: WorkshopConfigurationView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-configuration',
        headerTitle: '生产车间 / 生产配置',
        breadcrumbs: [{ label: '生产车间' }, { label: '生产配置' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/scheduling',
      name: 'workshop-scheduling',
      component: ProductionSchedulingListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-scheduling',
        headerTitle: '生产车间 / 计划排产',
        planTitle: '计划排产',
        breadcrumbs: [{ label: '生产车间' }, { label: '计划排产' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/plans/metalworking',
      name: 'workshop-metalworking-plan',
      component: WorkshopPlanListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-internal-plan',
        headerTitle: '生产车间 / 内部计划',
        planTitle: '内部计划',
        breadcrumbs: [{ label: '生产车间' }, { label: '内部计划' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/plans/cutting',
      name: 'workshop-cutting-plan',
      component: WorkshopPlanListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-internal-plan',
        headerTitle: '生产车间 / 内部计划',
        planTitle: '内部计划',
        breadcrumbs: [{ label: '生产车间' }, { label: '内部计划' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/plans/sewing',
      name: 'workshop-sewing-plan',
      component: WorkshopPlanListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-internal-plan',
        headerTitle: '生产车间 / 内部计划',
        planTitle: '内部计划',
        breadcrumbs: [{ label: '生产车间' }, { label: '内部计划' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/plans/assembly',
      name: 'workshop-assembly-plan',
      component: WorkshopPlanListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-internal-plan',
        headerTitle: '生产车间 / 内部计划',
        planTitle: '内部计划',
        breadcrumbs: [{ label: '生产车间' }, { label: '内部计划' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/wage-schemes',
      name: 'wage-schemes',
      component: WageSchemeListView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'wage-schemes', headerTitle: '生产车间 / 工价方案', breadcrumbs: [{ label: '生产车间' }, { label: '工价方案' }], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/workshop/wage-schemes/new',
      name: 'wage-scheme-new',
      component: WageSchemeFormView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'wage-schemes', headerTitle: '生产车间 / 工价方案 / 新增工价方案', breadcrumbs: [{ label: '生产车间' }, { label: '工价方案', to: '/workshop/wage-schemes' }, { label: '新增工价方案' }], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/workshop/wage-schemes/:schemeId/change',
      name: 'wage-scheme-change',
      component: WageSchemeFormView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'wage-schemes', headerTitle: '生产车间 / 工价方案 / 变更工价方案', breadcrumbs: [{ label: '生产车间' }, { label: '工价方案', to: '/workshop/wage-schemes' }, { label: '变更工价方案' }], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/workshop/wage-schemes/:schemeId',
      name: 'wage-scheme-detail',
      component: WageSchemeDetailView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'wage-schemes', headerTitle: '生产车间 / 工价方案 / 详情', breadcrumbs: [{ label: '生产车间' }, { label: '工价方案', to: '/workshop/wage-schemes' }, { label: '详情' }], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/workshop/work-reports',
      name: 'work-report-days',
      component: WorkReportDayListView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'work-report-days', headerTitle: '生产车间 / 报工记录', breadcrumbs: [{ label: '生产车间' }, { label: '报工记录' }], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/workshop/work-reports/new',
      name: 'work-report-new',
      component: WorkReportFormView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'work-report-days', headerTitle: '生产车间 / 报工记录 / 新增', breadcrumbs: [{ label: '生产车间' }, { label: '报工记录', to: '/workshop/work-reports' }, { label: '新增' }], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/workshop/work-reports/:reportId/edit',
      name: 'work-report-edit',
      component: WorkReportFormView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'work-report-days', headerTitle: '生产车间 / 报工记录 / 编辑', breadcrumbs: [{ label: '生产车间' }, { label: '报工记录', to: '/workshop/work-reports' }, { label: '编辑' }], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/workshop/work-reports/days/:productionDate',
      name: 'work-report-day-detail',
      component: WorkReportDayDetailView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'work-report-days', headerTitle: '生产车间 / 报工记录 / 日期明细', breadcrumbs: [{ label: '生产车间' }, { label: '报工记录', to: '/workshop/work-reports' }, { label: '日期明细' }], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/workshop/material-issues',
      name: 'material-issues',
      component: MaterialIssueListView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'material-issues',
        headerTitle: '仓库管理 / 生产领料', breadcrumbs: [{ label: '仓库管理' }, { label: '生产领料' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/workshop/material-issues/new',
      name: 'material-issue-new',
      component: MaterialIssueFormView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'material-issues',
        headerTitle: '仓库管理 / 生产领料 / 新增', breadcrumbs: [{ label: '仓库管理' }, { label: '生产领料', to: '/workshop/material-issues' }, { label: '新增' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/workshop/material-issues/:issueId/edit',
      name: 'material-issue-edit',
      component: MaterialIssueFormView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'material-issues',
        headerTitle: '仓库管理 / 生产领料 / 修改', breadcrumbs: [{ label: '仓库管理' }, { label: '生产领料', to: '/workshop/material-issues' }, { label: '修改' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/workshop/material-issues/:issueId',
      name: 'material-issue-detail',
      component: MaterialIssueDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'material-issues',
        headerTitle: '仓库管理 / 生产领料 / 领料单详情', breadcrumbs: [{ label: '仓库管理' }, { label: '生产领料', to: '/workshop/material-issues' }, { label: '领料单详情' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/inventory/finished-goods',
      name: 'finished-goods-inventory',
      component: FinishedGoodsInventoryView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'finished-goods-inventory',
        headerTitle: '仓库管理 / 成品库存',
        breadcrumbs: [{ label: '仓库管理' }, { label: '成品库存' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/inventory/finished-goods/outbound/new',
      name: 'finished-goods-outbound-new',
      component: FinishedGoodsOutboundFormView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'finished-goods-inventory', headerTitle: '仓库管理 / 成品库存 / 新建出库', breadcrumbs: [{ label: '仓库管理' }, { label: '成品库存', to: '/inventory/finished-goods' }, { label: '新建出库' }], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/inventory/finished-goods/outbounds',
      name: 'finished-goods-outbounds',
      redirect: to => ({ name: 'finished-goods-inventory', query: { ...to.query, tab: 'outbounds' } }),
    },
    {
      path: '/inventory/finished-goods/outbounds/:outboundId',
      name: 'finished-goods-outbound-detail',
      component: FinishedGoodsOutboundDetailView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'finished-goods-inventory', headerTitle: '仓库管理 / 成品库存 / 出货单详情', breadcrumbs: [{ label: '仓库管理' }, { label: '成品库存', to: '/inventory/finished-goods' }, { label: '出货单详情' }], pageWidth: 'fluid', flushPage: true },
    },
    {
      path: '/inventory/materials',
      name: 'material-inventory',
      component: MaterialInventoryView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'material-inventory',
        headerTitle: '仓库管理 / 材料库存',
        breadcrumbs: [{ label: '仓库管理' }, { label: '材料库存' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/purchase-inbound',
      name: 'purchase-inbounds',
      component: PurchaseInboundListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-inbounds',
        headerTitle: '仓库管理 / 采购入库',
        breadcrumbs: [{ label: '仓库管理' }, { label: '采购入库' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/inventory/materials/:stockItemId',
      name: 'material-inventory-detail',
      component: MaterialInventoryDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'material-inventory',
        headerTitle: '仓库管理 / 材料库存 / 订单追溯', breadcrumbs: [{ label: '仓库管理' }, { label: '材料库存', to: '/inventory/materials' }, { label: '订单追溯' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/warehouse/outsourcing',
      name: 'warehouse-outsourcing',
      component: OutsourcingOrderListView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'warehouse-outsourcing', outsourcingWorkspace: 'warehouse',
        headerTitle: '仓库 / 委外管理', breadcrumbs: [{ label: '仓库' }, { label: '委外管理' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/warehouse/outsourcing/tube/:id', name: 'warehouse-outsourcing-tube-detail',
      component: () => import('@/views/outsourcing/TubeOutsourcingDetailView.vue'),
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'warehouse-outsourcing', outsourcingWorkspace: 'warehouse',
        headerTitle: '仓库 / 委外管理 / 外发单',
        breadcrumbs: [{ label: '仓库' }, { label: '委外管理', to: '/warehouse/outsourcing' }, { label: '外发单' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/warehouse/outsourcing/tube/:id/return', name: 'warehouse-outsourcing-tube-return',
      component: () => import('@/views/inventory/TubeCoatingReceiptView.vue'),
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'warehouse-outsourcing', outsourcingWorkspace: 'warehouse',
        headerTitle: '仓库 / 委外管理 / 外发回货入库',
        breadcrumbs: [{ label: '仓库' }, { label: '委外管理', to: '/warehouse/outsourcing' }, { label: '外发回货入库' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/warehouse/outsourcing/rework/:orderId', name: 'warehouse-outsourcing-rework-detail',
      component: OutsourcingReworkDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'warehouse-outsourcing', outsourcingWorkspace: 'warehouse',
        headerTitle: '仓库 / 委外管理 / 外发单详情',
        breadcrumbs: [{ label: '仓库' }, { label: '委外管理', to: '/warehouse/outsourcing' }, { label: '外发单详情' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/warehouse/outsourcing/:orderId', name: 'warehouse-outsourcing-detail',
      component: OutsourcingOrderDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'warehouse-outsourcing', outsourcingWorkspace: 'warehouse',
        headerTitle: '仓库 / 委外管理 / 外发单详情',
        breadcrumbs: [{ label: '仓库' }, { label: '委外管理', to: '/warehouse/outsourcing' }, { label: '外发单详情' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/workshop/outsourcing',
      name: 'workshop-outsourcing',
      component: OutsourcingOrderListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-outsourcing',
        headerTitle: '生产车间 / 委外加工',
        breadcrumbs: [{ label: '生产车间' }, { label: '委外加工' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/outsourcing/tube/new',
      name: 'workshop-outsourcing-tube-new',
      component: () => import('@/views/outsourcing/TubeOutsourcingFormView.vue'),
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'workshop-outsourcing',
        headerTitle: '生产车间 / 委外加工 / 新建外发单',
        breadcrumbs: [{ label: '生产车间' }, { label: '委外加工', to: '/workshop/outsourcing' }, { label: '新建外发单' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/workshop/outsourcing/tube/:id',
      name: 'workshop-outsourcing-tube-detail',
      component: () => import('@/views/outsourcing/TubeOutsourcingDetailView.vue'),
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'workshop-outsourcing',
        headerTitle: '生产车间 / 委外加工 / 外发单',
        breadcrumbs: [{ label: '生产车间' }, { label: '委外加工', to: '/workshop/outsourcing' }, { label: '外发单' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/workshop/outsourcing/tube/:id/return', name: 'workshop-outsourcing-tube-return',
      redirect: to => ({ name: 'warehouse-outsourcing-tube-return', params: { id: to.params.id }, query: to.query }),
    },
    {
      path: '/workshop/outsourcing/new',
      redirect: { name: 'workshop-outsourcing' },
    },
    {
      path: '/workshop/outsourcing/metal-processing',
      name: 'workshop-outsourcing-metal-processing',
      redirect: to => ({ name: 'workshop-outsourcing', query: { ...to.query, tab: 'sources' } }),
    },
    {
      path: '/workshop/outsourcing/rework/:orderId',
      name: 'workshop-outsourcing-rework-detail',
      component: OutsourcingReworkDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-outsourcing',
        headerTitle: '生产车间 / 委外加工 / 外发单详情',
        breadcrumbs: [{ label: '生产车间' }, { label: '委外加工', to: '/workshop/outsourcing' }, { label: '外发单详情' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/outsourcing/:orderId',
      name: 'workshop-outsourcing-detail',
      component: OutsourcingOrderDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-outsourcing',
        headerTitle: '生产车间 / 委外加工 / 外发单详情',
        breadcrumbs: [{ label: '生产车间' }, { label: '委外加工', to: '/workshop/outsourcing' }, { label: '外发单详情' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/outsourcing/factories',
      name: 'workshop-outsourcing-factories',
      component: FactoryListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-outsourcing',
        headerTitle: '生产车间 / 委外加工 / 加工厂管理',
        breadcrumbs: [{ label: '生产车间' }, { label: '委外加工' }, { label: '加工厂管理' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/outsourcing/factories/:factoryId',
      name: 'workshop-outsourcing-factory-detail',
      component: FactoryDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-outsourcing',
        headerTitle: '生产车间 / 委外加工 / 加工厂详情',
        breadcrumbs: [{ label: '生产车间' }, { label: '委外加工' }, { label: '加工厂详情' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/scheduling/new',
      name: 'workshop-scheduling-new',
      component: ProductionSchedulingFormView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-scheduling',
        headerTitle: '生产车间 / 新增排产',
        breadcrumbs: [{ label: '生产车间' }, { label: '计划排产' }, { label: '新增排产' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/scheduling/:scheduleId/edit',
      name: 'workshop-scheduling-edit',
      component: ProductionSchedulingFormView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-scheduling',
        headerTitle: '生产车间 / 编辑排产',
        breadcrumbs: [{ label: '生产车间' }, { label: '计划排产' }, { label: '编辑排产' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/workshop/scheduling/:scheduleId',
      name: 'workshop-scheduling-detail',
      component: ProductionSchedulingDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'workshop-scheduling',
        headerTitle: '生产车间 / 排产详情',
        breadcrumbs: [{ label: '生产车间' }, { label: '计划排产' }, { label: '排产详情' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/purchase-inbound/order/:purchaseOrderId',
      name: 'material-purchase-inbound',
      component: MaterialPurchaseInboundView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-inbounds',
        headerTitle: '仓库管理 / 采购入库 / 仓库收货',
        breadcrumbs: [{ label: '仓库管理' }, { label: '采购入库', to: '/purchase-inbound' }, { label: '仓库收货' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/purchase-inbound/quality',
      name: 'material-quality-confirmation',
      component: MaterialQualityConfirmationView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-inbounds',
        headerTitle: '仓库管理 / 采购入库 / 品质确认',
        breadcrumbs: [{ label: '仓库管理' }, { label: '采购入库', to: '/purchase-inbound' }, { label: '品质确认' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/purchase-returns',
      name: 'purchase-returns',
      component: PurchaseReturnListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-returns',
        headerTitle: '仓库管理 / 退货明细',
        breadcrumbs: [{ label: '仓库管理' }, { label: '退货明细' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/purchase-return-records',
      name: 'purchase-return-records',
      component: PurchaseReturnListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-return-records',
        headerTitle: '采购管理 / 退货记录',
        breadcrumbs: [{ label: '采购管理' }, { label: '退货记录' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/inventory/materials/inbound',
      name: 'manual-material-inbound',
      component: ManualMaterialInboundView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'material-inventory',
        headerTitle: '仓库管理 / 材料库存 / 材料入库',
        breadcrumbs: [{ label: '仓库管理' }, { label: '材料库存', to: '/inventory/materials' }, { label: '材料入库' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/inventory/material-inbounds',
      name: 'material-inbound-details',
      component: MaterialInboundDetailView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'material-inventory',
        headerTitle: '仓库管理 / 入库明细',
        breadcrumbs: [{ label: '仓库管理' }, { label: '入库明细' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/purchase-orders',
      name: 'purchase-orders',
      component: PurchaseOrderListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 采购订单',
        breadcrumbs: [{ label: '采购管理' }, { label: '采购订单' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/purchase-orders/new',
      name: 'purchase-order-create',
      component: PurchaseOrderFormView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 采购订单',
        breadcrumbs: [{ label: '采购管理' }, { label: '采购订单', to: '/purchase-orders' }, { label: '新建' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/purchase-orders/new/details',
      name: 'purchase-order-create-details',
      component: PurchaseOrderFormView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 采购订单',
        breadcrumbs: [{ label: '采购管理' }, { label: '采购订单', to: '/purchase-orders' }, { label: '填写明细' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/purchase-orders/:id/details',
      name: 'purchase-order-detail',
      component: PurchaseOrderDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 采购订单 / 查看明细',
        breadcrumbs: [{ label: '采购管理' }, { label: '采购订单', to: '/purchase-orders' }, { label: '查看明细' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/purchase-inbound/:id/details',
      name: 'purchase-inbound-detail',
      component: PurchaseOrderDetailView,
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'purchase-inbounds',
        headerTitle: '仓库管理 / 采购入库 / 查看明细',
        breadcrumbs: [{ label: '仓库管理' }, { label: '采购入库', to: '/purchase-inbound' }, { label: '查看明细' }],
        pageWidth: 'fluid', flushPage: true,
      },
    },
    {
      path: '/purchase-orders/:id/confirm',
      name: 'purchase-order-confirm',
      component: PurchaseOrderConfirmView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 采购订单',
        breadcrumbs: [{ label: '采购管理' }, { label: '采购订单', to: '/purchase-orders' }, { label: '确认' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/purchase-orders/:id/templates',
      name: 'purchase-sheet-template-select',
      component: PurchaseSheetTemplateSelectView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 采购订单',
        breadcrumbs: [{ label: '采购管理' }, { label: '采购订单', to: '/purchase-orders' }, { label: '选择模板' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/supplier-purchase-sheets',
      name: 'supplier-purchase-sheets',
      component: SupplierPurchaseSheetListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
          activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 供应商采购表',
        breadcrumbs: [{ label: '采购管理' }, { label: '采购订单', to: '/purchase-orders' }, { label: '供应商采购表' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/supplier-purchase-sheets/:id',
      name: 'supplier-purchase-sheet-editor',
      component: SupplierPurchaseSheetEditorView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
          activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 供应商采购表',
        breadcrumbs: [{ label: '采购管理' }, { label: '采购订单', to: '/purchase-orders' }, { label: '供应商采购表', to: '/supplier-purchase-sheets' }, { label: '编辑' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/purchase-contract-templates',
      name: 'purchase-contract-templates',
      component: PurchaseContractTemplateListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 采购合同模板',
        breadcrumbs: [{ label: '采购管理' }, { label: '采购合同模板' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/suppliers',
      name: 'suppliers',
      component: SupplierListView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 采购订单 / 供应商管理',
        breadcrumbs: [{ label: '采购管理' }, { label: '采购订单', to: '/purchase-orders' }, { label: '供应商管理' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/suppliers/new',
      name: 'supplier-create',
      redirect: { name: 'suppliers', query: { create: '1' } },
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 供应商',
        breadcrumbs: [{ label: '采购管理' }, { label: '供应商', to: '/suppliers' }, { label: '新建供应商' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/suppliers/:supplierId/edit',
      name: 'supplier-edit',
      redirect: to => ({ name: 'suppliers', query: { edit: String(to.params.supplierId) } }),
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'purchase-orders',
        headerTitle: '采购管理 / 供应商',
        breadcrumbs: [{ label: '采购管理' }, { label: '供应商', to: '/suppliers' }, { label: '编辑供应商' }],
        pageWidth: 'fluid',
        flushPage: true,
      },
    },
    {
      path: '/settings',
      name: 'system-settings',
      component: () => import('@/views/settings/SystemSettingsView.vue'),
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'settings', headerTitle: '系统配置', breadcrumbs: [{ label: '系统配置' }], pageWidth: 'fluid' },
    },
    {
      path: '/settings/email-accounts',
      name: 'email-account-settings',
      component: EmailAccountSettingsView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'settings',
        headerTitle: '系统配置',
        breadcrumbs: [{ label: '系统配置' }, { label: '邮件账户' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/settings/reference-data',
      name: 'reference-data-settings',
      component: ReferenceDataSettingsView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'settings',
        headerTitle: '系统配置',
        breadcrumbs: [{ label: '系统配置' }, { label: '字典与业务参数' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/settings/theme',
      name: 'theme-settings',
      component: ThemeSettingsView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'settings',
        headerTitle: '系统设置',
        breadcrumbs: [{ label: '系统设置' }, { label: '界面主题' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/settings/access',
      name: 'access-management',
      component: AccessManagementView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'settings', headerTitle: '系统配置 / 权限管理', breadcrumbs: [{label:'系统配置',to:'/settings'},{label:'权限管理'}], pageWidth:'fluid', fitViewport:true },
    },
    {
      path: '/settings/master-data',
      name: 'master-data-center',
      component: MasterDataCenterView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'settings',
        headerTitle: '系统配置',
        breadcrumbs: [{ label: '系统配置' }, { label: '基础资料中心' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/settings/production-data',
      name: 'production-data',
      component: ProductionDataView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'settings',
        headerTitle: '系统配置',
        breadcrumbs: [{ label: '系统配置' }, { label: '生产维护' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/settings/inquiry-handling-time',
      name: 'inquiry-handling-settings',
      component: InquiryHandlingSettingsView,
      meta: { requiresAuth: true, layout: 'erp', activeMenu: 'settings', headerTitle: '系统设置 / 询盘处理时限', breadcrumbs: [{label:'系统设置',to:'/settings'},{label:'询盘处理时限'}], pageWidth:'fluid' },
    },
    {
      path: '/finance/accounts',
      name: 'finance-accounts',
      component: () => import('@/views/finance/FinanceAccountsView.vue'),
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'finance-accounts', headerTitle: '财务管理',
        breadcrumbs: [{ label: '财务管理' }, { label: '公司账户信息' }], pageWidth: 'fluid',
      },
    },
    {
      path: '/finance/subjects',
      name: 'finance-subjects',
      component: () => import('@/views/finance/FinanceSubjectsView.vue'),
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'finance-subjects', headerTitle: '财务管理',
        breadcrumbs: [{ label: '财务管理' }, { label: '会计科目' }], pageWidth: 'fluid',
      },
    },
    {
      path: '/finance/statements',
      name: 'finance-statements',
      component: () => import('@/views/finance/FinanceStatementsView.vue'),
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'finance-statements', headerTitle: '财务管理',
        breadcrumbs: [{ label: '财务管理' }, { label: '应收对账单' }], pageWidth: 'fluid',
      },
    },
    {
      path: '/finance/receipts',
      name: 'finance-receipts',
      component: () => import('@/views/finance/FinanceReceiptsView.vue'),
      meta: {
        requiresAuth: true, layout: 'erp', activeMenu: 'finance-receipts', headerTitle: '财务管理',
        breadcrumbs: [{ label: '财务管理' }, { label: '收款确认' }], pageWidth: 'fluid',
      },
    },
    {
      path: '/settings/number-rules',
      name: 'number-rules',
      component: NumberRulesView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        activeMenu: 'settings',
        headerTitle: '系统配置',
        breadcrumbs: [{ label: '系统配置' }, { label: '编号规则' }],
        pageWidth: 'fluid',
      },
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: NotFoundView,
      meta: {
        requiresAuth: true,
        layout: 'erp',
        headerTitle: '页面不存在',
        breadcrumbs: [{ label: '工作台', to: '/' }, { label: '页面不存在' }],
        pageWidth: 'contained',
      },
    },
  ],
})

router.beforeEach(async (to, from) => {
  if (to.name === 'internal-semi-receipt') {
    to.meta.activeMenu = to.query.plan_category === 'METAL' ? 'workshop-internal-plan' : 'material-inventory'
  }
  const authStore = useAuthStore()

  try {
    if (to.meta.requiresAuth) await authStore.ensureFreshAuthentication()
    else await authStore.initialize()
  } catch {
    if (authStore.isAuthenticated && authStore.waitingForRole) {
      return to.name === 'waiting-role' || to.name === 'wecom-error' ? true : { name: 'waiting-role' }
    }
    if (to.meta.requiresAuth) {
      if (authStore.isAuthenticated) {
        ElMessage.error('暂时无法验证登录状态，请稍后重试。')
        if (from.matched.length) return false
      }
      return { name: 'login', query: { redirect: to.fullPath } }
    }
    return true
  }

  if (startWeComLoginIfNeeded(to.name, to.meta.requiresAuth === true, authStore.isAuthenticated, to.fullPath)) return false

  const wecomRedirect = wecomRouteRedirect(to.name, authStore.isAuthenticated, authStore.waitingForRole)
  if (wecomRedirect) return wecomRedirect

  if (to.name === 'login' && authStore.isAuthenticated && authStore.authenticationCheckedAt > 0) {
    return { name: 'home' }
  }

  if (to.meta.requiresAuth && !authStore.isAuthenticated) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  if (to.name === 'home') {
    if (authStore.hasPermission('production_tasks.view_productiontask')) {
      return { name: 'production-overview' }
    }
    if (authStore.user?.is_superuser || authStore.hasAnyPermission([
      'production_scheduling.view_productionschedule',
      'workshop_reporting.view_workreport',
      'inventory.view_finishedgoodsreceipt',
    ])) {
      return { name: 'workshop-workbench' }
    }
  }

  return true
})
