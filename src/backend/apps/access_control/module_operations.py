"""Stage 5 operation overrides; old independently granted codes retain compatibility."""

MODULE_OPERATIONS = (
    ('complete_purchaseorder', '完成采购订单', 'procurement', 'procurement.submit_purchaseorder'),
    ('generate_purchasesheets', '生成供应商采购单', 'procurement', 'procurement.add_purchaseorder'),
    ('cancel_productiontask', '取消生产订单', 'production_tasks', 'production_tasks.change_productiontask'),
    ('finish_productiontask', '完成生产订单', 'production_tasks', 'production_tasks.change_productiontask'),
    ('sync_bomquantity', '同步 BOM 数量', 'boms', 'boms.change_bom'),
    ('submit_samplerequest', '提交打样', 'samples', 'samples.change_samplerequest'),
    ('prepare_samplerequest', '开始准备样品', 'samples', 'samples.change_samplerequest'),
    ('financeconfirm_sample', '财务确认样品', 'samples', 'samples.decide_sample_fee'),
    ('pmcapprove_sample', 'PMC 确认样品', 'samples', 'samples.change_samplerequest'),
    ('metalwork_sample', '维护样品金工参数', 'samples', 'samples.change_samplerequest'),
    ('cutting_sample', '维护样品裁剪参数', 'samples', 'samples.change_samplerequest'),
    ('productionreport_sample', '登记样品生产进度', 'samples', 'samples.change_samplerequest'),
    ('metalreport_sample', '登记样品金工进度', 'samples', 'samples.change_samplerequest'),
    ('cuttingreport_sample', '登记样品裁剪进度', 'samples', 'samples.change_samplerequest'),
    ('complete_samplerequest', '完成样品', 'samples', 'samples.change_samplerequest'),
    ('confirm_samplerequest', '确认样品结果', 'samples', 'samples.change_samplerequest'),
    ('reject_samplerequest', '退回样品结果', 'samples', 'samples.change_samplerequest'),
    ('cancel_samplerequest', '取消样品', 'samples', 'samples.view_samplerequest'),
    ('approve_samplefee', '审批样品费用豁免', 'samples', 'samples.change_samplefeerecord'),
    ('start_businesstask', '开始任务', 'workflow', 'workflow.change_businesstask'),
    ('complete_businesstask', '完成任务', 'workflow', 'workflow.change_businesstask'),
    ('cancel_businesstask', '取消任务', 'workflow', 'workflow.change_businesstask'),
    ('reschedule_businesstask', '延期任务', 'workflow', 'workflow.change_businesstask'),
)

LEGACY_ALIASES = {f'access_control.{code}': old for code, _, _, old in MODULE_OPERATIONS}
LEGACY_ALIASES.update({
    'procurement.change_purchaseorder': 'procurement.add_purchaseorder',
    'procurement.view_purchasecontracttemplate': 'procurement.view_purchaseorder',
    'procurement.add_purchasecontracttemplate': 'procurement.view_purchaseorder',
    'procurement.change_purchasecontracttemplate': 'procurement.view_purchaseorder',
    'procurement.view_supplierpurchasesheet': 'procurement.view_purchaseorder',
    'procurement.change_supplierpurchasesheet': 'procurement.add_purchaseorder',
    'procurement.add_supplierpurchasesheet': 'procurement.add_purchaseorder',
    'procurement.publish_supplierpurchasesheet': 'procurement.submit_purchaseorder',
    'access_control.confirm_purchasereturn': 'procurement.submit_purchaseorder',
    'access_control.complete_purchasereturn': 'procurement.submit_purchaseorder',
})

ACTION_OVERRIDES = {
    'ReceiptViewSet': {
        'list': 'finance.view_receipt', 'retrieve': 'finance.view_receipt',
        'create': 'finance.add_receipt', 'void': 'finance.void_receipt', 'attachment': 'finance.view_receipt',
    },
    'ReceiptUploadViewSet': {action: 'finance.add_receipt' for action in ('list', 'retrieve', 'create', 'destroy', 'content')},
    'ReceiptAccountOptionsViewSet': {'list': 'finance.add_receipt'},
    'ReceiptStatementViewSet': {'receipts': 'finance.view_receipt', 'available_deposits': 'finance.add_receipt'},
    'AccountingSubjectViewSet': {
        'list': 'finance.view_accountingsubject', 'retrieve': 'finance.view_accountingsubject',
        'create': 'finance.add_accountingsubject', 'partial_update': 'finance.change_accountingsubject',
        'destroy': 'finance.delete_accountingsubject',
    },
    'SubjectTreeViewSet': {'list': 'finance.view_accountingsubject'},
    'ReceivableStatementViewSet': {
        'list': 'finance.view_receivablestatement', 'retrieve': 'finance.view_receivablestatement',
        'create': 'finance.add_receivablestatement', 'partial_update': 'finance.change_receivablestatement',
        'void': 'finance.void_receivablestatement',
    },
    'FinanceSourceTaskViewSet': {
        action: ['finance.view_receivablestatement', 'finance.add_receivablestatement',
                 'finance.change_receivablestatement', 'finance.add_receipt'] for action in ('list', 'products')
    },
    'FinanceAccountViewSet': {
        'list': 'finance.view_financeaccount', 'retrieve': 'finance.view_financeaccount',
        'create': 'finance.add_financeaccount', 'partial_update': 'finance.change_financeaccount',
        'destroy': 'finance.delete_financeaccount',
    },
    'PurchaseRequestViewSet': {
        'list': 'procurement.view_purchaserequest', 'retrieve': 'procurement.view_purchaserequest',
        'options': 'procurement.view_purchaserequest', 'create': 'procurement.add_purchaserequest',
        'partial_update': 'procurement.change_purchaserequest', 'submit': 'access_control.submit_purchaserequest',
        'allocate': 'access_control.allocate_purchaserequest', 'cancel_allocation': 'access_control.cancel_purchaserequestallocation',
        'supplier_order_options': 'access_control.generate_supplierorder', 'generate_supplier_order': 'access_control.generate_supplierorder',
    },
    'PurchaseOrderViewSet': {'update': 'procurement.change_purchaseorder', 'partial_update': 'procurement.change_purchaseorder',
        'complete': 'access_control.complete_purchaseorder', 'generate_sheets': 'access_control.generate_purchasesheets'},
    'PurchaseReturnViewSet': {
        'confirm': 'access_control.confirm_purchasereturn',
        'complete': 'access_control.complete_purchasereturn',
    },
    'PurchaseContractTemplateViewSet': {'list': 'procurement.view_purchasecontracttemplate', 'retrieve': 'procurement.view_purchasecontracttemplate',
        'create': 'procurement.add_purchasecontracttemplate', 'update': 'procurement.change_purchasecontracttemplate', 'partial_update': 'procurement.change_purchasecontracttemplate'},
    'SupplierPurchaseSheetViewSet': {
        **{action: 'procurement.view_supplierpurchasesheet' for action in ('list', 'options', 'retrieve', 'preview_pdf', 'download_pdf', 'download_xlsx', 'batch_download', 'preview.GET', 'line_image.GET', 'seal_image.GET')},
        **{action: 'procurement.change_supplierpurchasesheet' for action in ('update', 'partial_update', 'preview.POST', 'line_image.POST', 'line_image.DELETE', 'seal_image.POST', 'seal_image.DELETE')},
        'new_version': 'procurement.add_supplierpurchasesheet', 'publish': 'procurement.publish_supplierpurchasesheet', 'batch_publish': 'procurement.publish_supplierpurchasesheet'},
    'ProductionTaskViewSet': {'cancel': 'access_control.cancel_productiontask', 'finish': 'access_control.finish_productiontask'},
    'BomViewSet': {'sync_order_quantity': 'access_control.sync_bomquantity'},
    'SampleRequestViewSet': {
        'parameter_image': ['access_control.metalwork_sample', 'access_control.cutting_sample'],
        'form': ['samples.change_samplerequest', 'samples.complete_sample_requirements', 'access_control.productionreport_sample'],
        'submit': 'access_control.submit_samplerequest', 'start_preparing': 'access_control.prepare_samplerequest',
        'finance_confirm': 'access_control.financeconfirm_sample', 'pmc_approve': 'access_control.pmcapprove_sample',
        'metalwork_parameters': 'access_control.metalwork_sample', 'cutting_parameters': 'access_control.cutting_sample',
        'production_report': 'access_control.productionreport_sample', 'complete': 'access_control.complete_samplerequest',
        'confirm': 'access_control.confirm_samplerequest', 'reject': 'access_control.reject_samplerequest', 'cancel': 'access_control.cancel_samplerequest',
        'fee_approval_approve': 'access_control.approve_samplefee', 'fee_approval_reject': 'access_control.approve_samplefee'},
    'TaskViewSet': {'start': 'access_control.start_businesstask', 'complete': 'access_control.complete_businesstask',
        'cancel': 'access_control.cancel_businesstask', 'reschedule': 'access_control.reschedule_businesstask', 'reschedule_preview': 'access_control.reschedule_businesstask'},
}
