"""单元03已确认职责基线；新模块须同步模板及覆盖测试，禁止任意接口自动放行。"""
from .catalog import PERMISSION_CODES, scopes_for

PENDING = {
    'MERCHANDISER': '职责待确认：建议确认仅生产进度读取还是参与计划，不推定销售职责。',
    'PMC': '职责待确认：建议确认计划只读/调整；生产确认已明确由行政办理。',
    'OUTSOURCING': '职责待确认：建议明确制单、对账、完结及工艺范围，已建单发料和入库由仓库办理。',
    'COATING_MATERIALS': '职责待确认：建议明确喷塑收发对应旧交接或新库存来源，不直接扩大库存写权。',
    'SALESPERSON': '明确暂不启用：销售业务本期不开通。',
    'ACCOUNT_MANAGER': '明确暂不启用：销售业务本期不开通。',
}
DIRECTORS = {'METAL_DIRECTOR': '金工车间', 'ASSEMBLY_DIRECTOR': '装配车间', 'SEWING_DIRECTOR': '车缝车间'}


def module_rows(*codes):
    return [{'permission': code, 'scope': 'MODULE'} for code in codes]


def full_permissions():
    # 取登记白名单；个人保存视图仍为OWN，销售为ALL，其余按目录最大合法范围。
    return [{'permission': code, 'scope': 'ALL' if 'ALL' in scopes_for(code) else
             'MODULE' if 'MODULE' in scopes_for(code) else 'OWN'} for code in PERMISSION_CODES]


def templates(workshops):
    result = {code: [] for code in PENDING}
    result.update({code: module_rows(*(f'finance.{action}_{resource}' for resource in ('financeaccount', 'accountingsubject') for action in ('view', 'add', 'change', 'delete')))
                   for code in ('FINANCE', 'CASHIER')})
    for code in ('FINANCE', 'CASHIER'):
        result[code].extend(module_rows(*(f'finance.{action}_receivablestatement' for action in ('view', 'add', 'change', 'void', 'delete'))))
        result[code].extend(module_rows(*(f'finance.{action}_receipt' for action in ('view', 'add', 'void', 'delete'))))
    result.update({code: full_permissions() for code in ('FACTORY_MANAGER', 'GENERAL_MANAGER')})
    result['ADMINISTRATION'] = module_rows(
        'production_tasks.view_productiontask', 'production_tasks.add_productiontask',
        'production_tasks.change_productiontask', 'production_tasks.submit_productiontask',
        'production_tasks.confirm_productiontask', 'production_scheduling.view_productionschedule',
        'production_scheduling.add_productionschedule', 'production_scheduling.change_productionschedule',
        'attendance.view_attendance', 'procurement.view_purchaseorder')
    result['TECHNICAL'] = module_rows('boms.view_bom', 'boms.add_bom', 'boms.change_bom', 'boms.verify_bom',
        'products.view_productinformation', 'products.view_rawmaterialinformation',
        'product_catalog.view_productcatalog', 'material_catalog.view_materialcatalog',
        'production_tasks.view_productiontask')
    result['PURCHASING'] = module_rows(
        'procurement.view_purchaseorder', 'procurement.add_purchaseorder', 'procurement.change_purchaseorder',
        'procurement.submit_purchaseorder', 'access_control.complete_purchaseorder',
        'access_control.generate_purchasesheets', 'procurement.view_supplier',
        'procurement.view_supplierpurchasesheet', 'procurement.change_supplierpurchasesheet',
        'procurement.add_supplierpurchasesheet', 'procurement.publish_supplierpurchasesheet',
        'procurement.view_purchasecontracttemplate', 'procurement.view_purchaserequest',
        'procurement.add_purchaserequest', 'procurement.change_purchaserequest',
        'access_control.submit_purchaserequest', 'access_control.allocate_purchaserequest',
        'access_control.cancel_purchaserequestallocation', 'access_control.generate_supplierorder',
        'access_control.confirm_purchasereturn', 'access_control.complete_purchasereturn',
        'samples.view_sample_procurement', 'products.view_rawmaterialinformation', 'material_catalog.view_materialcatalog',
        'boms.view_bom')
    result['QUALITY'] = module_rows('inventory.quality_confirm_material')
    result['WAREHOUSE_KEEPER'] = module_rows(
        'inventory.receive_material', 'inventory.view_materialinbound', 'inventory.view_material_receipt',
        'inventory.view_materialstockbalance', 'inventory.view_semifinishedstockbalance',
        'inventory.view_warehouse', 'inventory.view_warehousezone', 'inventory.view_warehouselocation',
        'inventory.view_internalsemifinishedreceipt', 'inventory.confirm_internalsemifinishedreceipt',
        'inventory.delete_internalsemifinishedreceipt',
        'inventory.view_finishedgoodsreceipt', 'inventory.confirm_finishedgoodsreceipt',
        'inventory.delete_finishedgoodsreceipt',
        'material_issues.view_materialissue', 'material_issues.review_materialissue',
        'samples.view_samplerequest', 'samples.review_sample_materials',
        'samples.view_sampleinventoryline', 'samples.add_sampleinventoryreceipt',
        'outsourcing.confirm_dispatch_outsourcingorder', 'outsourcing.confirm_return_outsourcingorder',
        'material_issues.create_metalprocessingoriginalhandoff',
        'material_issues.confirm_metalprocessingexternalhandoff', 'material_issues.confirm_metalprocessingexternalreturn')
    result['WAREHOUSE_KEEPER'] += [{'permission': code, 'scope': 'STOCK'} for code in (
        'outsourcing.view_outsourcingorder',)]
    for role, workshop in DIRECTORS.items():
        ids = [str(workshops[workshop])]
        result[role] = [{'permission': code, 'scope': 'WORKSHOP', 'resource_ids': ids} for code in (
            'production_scheduling.view_productionschedule', 'material_issues.view_materialissue',
            'material_issues.add_materialissue', 'material_issues.change_materialissue', 'material_issues.submit_materialissue',
            'workshop_reporting.view_wagescheme', 'workshop_reporting.add_wagescheme',
            'workshop_reporting.change_wagescheme', 'workshop_reporting.submit_wagescheme',
            'workshop_reporting.view_workreport', 'workshop_reporting.add_workreport', 'workshop_reporting.change_workreport')]
        if role in {'METAL_DIRECTOR', 'SEWING_DIRECTOR'}:
            result[role] += module_rows('inventory.view_internalsemifinishedreceipt', 'inventory.add_internalsemifinishedreceipt',
                                       'inventory.delete_internalsemifinishedreceipt')
        if role == 'ASSEMBLY_DIRECTOR':
            result[role] += module_rows('inventory.view_finishedgoodsreceipt', 'inventory.add_finishedgoodsreceipt',
                                       'inventory.delete_finishedgoodsreceipt')
        if role != 'ASSEMBLY_DIRECTOR':
            result[role] += [{'permission': code, 'scope': 'WORKSHOP', 'resource_ids': ids} for code in (
                'outsourcing.view_outsourcingorder',)]
    for role, parameter, report in (
        ('METAL_SAMPLING', 'metalwork', 'metalreport'), ('FABRIC_SAMPLING', 'cutting', 'cuttingreport'),
    ):
        result[role] = module_rows('samples.view_samplerequest', 'samples.edit_sample_materials',
            'samples.complete_sample_requirements')
        if role == 'METAL_SAMPLING':
            result[role] += module_rows(f'access_control.{parameter}_sample', f'access_control.{report}_sample')
        # 布面打样与现有CUTTING动作的对应关系等待本轮明确确认。
    return {role: sorted(rows, key=lambda row: (row['permission'], row['scope'])) for role, rows in result.items()}
