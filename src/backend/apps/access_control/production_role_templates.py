"""2026-11-02确认的角色目标；精确启用使用configure_confirmed_roles。"""
from .catalog import PERMISSION_CODES, scopes_for
from .role_policy import FOLLOWED_PERMISSIONS
from .superuser_services import SUPERUSER_ROLE_CODES

PENDING = {
    'SALESPERSON': '已确认35项规划，销售实施暂缓；保留现有授权。',
    'ACCOUNT_MANAGER': '尚未规划，销售实施暂缓；保留现有授权。',
}
DIRECTORS = {'METAL_DIRECTOR': '金工车间', 'ASSEMBLY_DIRECTOR': '装配车间', 'SEWING_DIRECTOR': '车缝车间'}
GROUP_ONLY_ROLES = (
    'ROLE_A0D541A3E36E414890125AB40D10DCF4', 'ROLE_2993D2B2A09045BC9CE667142051C15C',
    'ROLE_92229791A0E04A9C8067ED7D2AC2ED77', 'ROLE_5EE76DEC357247968ECC1B252B68DD1C',
)
TASK_READ = ('production_tasks.view_productiontask', 'production_tasks.view_productiontaskcost')
TASK_EDIT = ('production_tasks.add_productiontask', 'production_tasks.change_productiontask',
             'production_tasks.submit_productiontask', 'production_tasks.confirm_productiontask')
SCHEDULE_EDIT = ('production_scheduling.view_productionschedule', 'production_scheduling.add_productionschedule',
                 'production_scheduling.change_productionschedule', 'production_scheduling.void_productionschedule')
BOM_EDIT = ('boms.view_bom', 'boms.add_bom', 'boms.change_bom', 'boms.verify_bom', 'access_control.sync_bomquantity')
STOCK_READ = ('inventory.view_materialstockbalance', 'inventory.view_semifinishedstockbalance',
              'inventory.view_materialinbound', 'inventory.view_material_receipt',
              'inventory.view_internalsemifinishedreceipt', 'inventory.view_finishedgoodsreceipt',
              'inventory.view_finishedgoodsoutbound')


def module_rows(*codes):
    return [{'permission': code, 'scope': 'MODULE'} for code in codes]


def full_permissions():
    return [{'permission': code, 'scope': 'ALL' if 'ALL' in scopes_for(code) else
             'MODULE' if 'MODULE' in scopes_for(code) else 'OWN'} for code in PERMISSION_CODES]


def scoped_rows(codes, scope, ids):
    return [{'permission': code, 'scope': scope, 'resource_ids': sorted(str(pk) for pk in ids)} for code in codes]


def templates(workshops, coating_craft_ids=()):
    # 暂缓销售角色保留占位；精确配置命令明确跳过，不能据空列表清权。
    result = {code: [] for code in (*PENDING, *GROUP_ONLY_ROLES)}
    result.update({code: full_permissions() for code in SUPERUSER_ROLE_CODES})
    finance = module_rows(*(f'finance.{action}_{resource}' for resource in ('financeaccount', 'accountingsubject')
                            for action in ('view', 'add', 'change', 'delete')))
    finance += module_rows(*(f'finance.{action}_receivablestatement' for action in ('view', 'add', 'change', 'void', 'delete')))
    finance += module_rows(*(f'finance.{action}_receipt' for action in ('view', 'add', 'void', 'delete')))
    finance += module_rows(*TASK_READ, 'production_tasks.manage_productiontaskexpense')
    result.update({code: list(finance) for code in ('FINANCE', 'CASHIER')})
    result['ADMINISTRATION'] = module_rows(*TASK_READ, *TASK_EDIT, *SCHEDULE_EDIT,
                                         'attendance.view_attendance')
    product_maintenance = [code for code in PERMISSION_CODES
                           if code.split('.')[0] in {'products', 'product_catalog', 'material_catalog'}
                           and code.split('.')[1].startswith(('view_', 'add_', 'change_'))]
    reference_resources = {
        'dictionarytype', 'referencedictionary', 'unit', 'productcategory', 'productionunit', 'productcolor',
        'productitem', 'fabricmaterial', 'fabricspecification', 'fabricwidth', 'tubeproductname', 'tubethickness',
        'tubediameter', 'tubematerial', 'tubeshape', 'tubecoatingcolor', 'accessoryproductname',
        'accessoryspecification', 'accessorycolor', 'accessorymaterial',
    }
    reference_maintenance = [code for code in PERMISSION_CODES if code.startswith('reference_data.')
                             and code.split('.')[1].split('_', 1)[0] in {'view', 'add', 'change'}
                             and code.split('.')[1].split('_', 1)[1] in reference_resources]
    result['TECHNICAL'] = module_rows(*TASK_READ, *TASK_EDIT, *BOM_EDIT,
                                     *product_maintenance, *reference_maintenance)
    result['PURCHASING'] = module_rows(
        'procurement.view_purchaseorder', 'procurement.add_purchaseorder', 'procurement.change_purchaseorder',
        'procurement.delete_purchaseorder', 'procurement.submit_purchaseorder', 'access_control.complete_purchaseorder',
        'access_control.generate_purchasesheets', 'procurement.view_supplier', 'procurement.add_supplier',
        'procurement.change_supplier', 'procurement.view_supplierpurchasesheet', 'procurement.change_supplierpurchasesheet',
        'procurement.add_supplierpurchasesheet', 'procurement.publish_supplierpurchasesheet',
        'procurement.view_purchasecontracttemplate', 'procurement.view_purchaserequest',
        'procurement.add_purchaserequest', 'procurement.change_purchaserequest',
        'access_control.submit_purchaserequest', 'access_control.allocate_purchaserequest',
        'access_control.cancel_purchaserequestallocation', 'access_control.generate_supplierorder',
        'access_control.confirm_purchasereturn', 'access_control.complete_purchasereturn',
        'samples.view_sample_procurement')
    result['QUALITY'] = module_rows('inventory.quality_confirm_material', 'inventory.view_material_receipt',
                                   'inventory.view_materialstockbalance', 'inventory.view_materialinbound')
    result['WAREHOUSE_KEEPER'] = module_rows(
        *STOCK_READ, 'inventory.receive_material', 'inventory.view_warehouse', 'inventory.view_warehousezone',
        'inventory.view_warehouselocation', 'inventory.confirm_internalsemifinishedreceipt',
        'inventory.delete_internalsemifinishedreceipt', 'inventory.confirm_finishedgoodsreceipt',
        'inventory.delete_finishedgoodsreceipt', 'inventory.add_finishedgoodsoutbound',
        'material_issues.view_materialissue', 'material_issues.review_materialissue',
        'samples.view_samplerequest', 'samples.review_sample_materials', 'samples.view_sampleinventoryline',
        'samples.view_sampleinventoryoutboundline', 'samples.view_sampleinventoryloanline',
        'samples.add_sampleinventoryreceipt', 'samples.add_sampleinventoryoutbound', 'samples.add_sampleinventoryloan',
        'outsourcing.confirm_dispatch_outsourcingorder', 'outsourcing.confirm_return_outsourcingorder',
        'material_issues.create_metalprocessingoriginalhandoff',
        'material_issues.confirm_metalprocessingexternalhandoff', 'material_issues.confirm_metalprocessingexternalreturn')
    for role, workshop in DIRECTORS.items():
        ids = [str(workshops[workshop])]
        result[role] = scoped_rows((
            'production_scheduling.view_productionschedule', 'material_issues.view_materialissue',
            'material_issues.add_materialissue', 'material_issues.change_materialissue', 'material_issues.submit_materialissue',
            'workshop_reporting.view_wagescheme', 'workshop_reporting.add_wagescheme',
            'workshop_reporting.change_wagescheme', 'workshop_reporting.submit_wagescheme',
            'workshop_reporting.view_workreport', 'workshop_reporting.add_workreport',
            'workshop_reporting.change_workreport', 'workshop_reporting.delete_workreport'), 'WORKSHOP', ids)
        receipt = 'finishedgoodsreceipt' if role == 'ASSEMBLY_DIRECTOR' else 'internalsemifinishedreceipt'
        result[role] += scoped_rows((f'inventory.{action}_{receipt}' for action in ('view', 'add', 'delete')), 'WORKSHOP', ids)
    for role, parameter, report in (
        ('METAL_SAMPLING', 'metalwork', 'metalreport'), ('FABRIC_SAMPLING', 'cutting', 'cuttingreport'),
    ):
        result[role] = module_rows('samples.view_samplerequest', 'samples.edit_sample_materials',
            'samples.complete_sample_requirements', f'access_control.{parameter}_sample', f'access_control.{report}_sample')
    result['PMC'] = module_rows(*TASK_READ, *SCHEDULE_EDIT, *STOCK_READ, 'access_control.edit_productionplan',
        'production_tasks.submit_productiontask', 'production_tasks.confirm_productiontask',
        'production_tasks.start_productiontask', 'production_tasks.delete_productiontask',
        'access_control.cancel_productiontask', 'access_control.finish_productiontask',
        'boms.view_bom', 'procurement.view_purchaseorder', 'workshop_reporting.view_workreport')
    result['MERCHANDISER'] = [{'permission': code, 'scope': 'FOLLOWED'} for code in FOLLOWED_PERMISSIONS]
    result['OUTSOURCING'] = module_rows('outsourcing.view_outsourcingorder', 'outsourcing.add_outsourcingorder',
        'outsourcing.cancel_outsourcingorder', 'outsourcing.reconcile_outsourcingorder',
        'outsourcing.complete_outsourcingorder', 'outsourcing.view_outsourcingfactory',
        'outsourcing.add_outsourcingfactory', 'outsourcing.change_outsourcingfactory', 'outsourcing.disable_outsourcingfactory')
    result['COATING_MATERIALS'] = scoped_rows((
        'outsourcing.view_outsourcingorder', 'outsourcing.confirm_dispatch_outsourcingorder',
        'outsourcing.confirm_return_outsourcingorder', 'material_issues.view_metalprocessingsource',
        'material_issues.create_metalprocessingoriginalhandoff', 'material_issues.confirm_metalprocessingexternalhandoff',
        'material_issues.confirm_metalprocessingexternalreturn', 'material_issues.register_metalprocessingunsprayedreturn',
    ), 'CRAFT', coating_craft_ids)
    # 厂长取确认的工厂动作并集；采购和财务仅加入读取，不能复用全目录。
    factory_codes = {row['permission'] for role in ('WAREHOUSE_KEEPER', *DIRECTORS) for row in result[role]}
    factory_codes.update((*TASK_READ, *TASK_EDIT, *SCHEDULE_EDIT, *BOM_EDIT,
        'access_control.cancel_productiontask', 'access_control.pause_productiontask', 'access_control.resume_productiontask',
        'workshop_reporting.approve_wagescheme', 'samples.review_sample_application',
        'outsourcing.view_outsourcingorder', 'outsourcing.add_outsourcingorder', 'outsourcing.change_outsourcingorder',
        'outsourcing.cancel_outsourcingorder', 'material_issues.view_metalprocessingsource', 'procurement.view_purchaseorder',
        'procurement.view_supplierpurchasesheet', 'finance.view_financeaccount', 'finance.view_accountingsubject',
        'finance.view_receivablestatement', 'finance.view_receipt'))
    result['FACTORY_MANAGER'] = module_rows(*sorted(factory_codes))
    return {role: sorted({(row['permission'], row['scope']): row for row in rows}.values(),
                         key=lambda row: (row['permission'], row['scope'])) for role, rows in result.items()}
