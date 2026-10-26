from django.contrib.auth.models import Permission
from rest_framework.exceptions import ValidationError

from .catalog_codes import PERMISSION_CODES as BASE_PERMISSION_CODES
from .catalog_extras import EXTRA_OPERATIONS
from .presentation import presentation

# 已有全局读取码供全权限角色使用；普通车间角色继续使用资源范围。
FULL_DATA_CODES = (
    'boms.view_all_bom', 'customers.view_all_customer',
    'production_tasks.view_all_productiontask', 'production_scheduling.view_all_productionschedule',
    'material_issues.view_all_materialissue', 'outsourcing.view_all_outsourcingfactory',
    'outsourcing.view_all_outsourcingorder', 'samples.view_all_samplerequest',
    'workshop_reporting.view_all_wagescheme', 'workshop_reporting.view_all_workreport',
    'workshop_config.view_workshop', 'samples.view_sample_procurement', 'customers.manage_customer_access',
)

PERMISSION_CODES = tuple(sorted(set(BASE_PERMISSION_CODES) | set(FULL_DATA_CODES) | {'organizations.manage_organization', 'workshop_reporting.delete_workreport', 'procurement.add_supplierpurchasesheet', 'procurement.change_supplierpurchasesheet',
    'preferences.view_savedview', 'preferences.add_savedview', 'preferences.change_savedview',
    'production_tasks.view_productiontaskcost', 'production_tasks.manage_productiontaskexpense'} | {f"access_control.{code}" for code, _, _ in EXTRA_OPERATIONS}))

SALES_APPS = {"customers", "inquiries", "quotations", "sales_orders", "crm"}
MODULE_NAMES = {
    "finance": "财务管理",
    "access_control": "账号与授权管理",
    "organizations": "部门与组织",
    "attendance": "考勤管理",
    "customers": "客户与联系人", "inquiries": "询盘", "quotations": "报价",
    "sales_orders": "销售订单", "crm": "沟通与客户动态", "samples": "样品",
    "products": "产品与原料", "boms": "BOM", "production_tasks": "生产订单",
    "production_scheduling": "计划排产", "material_issues": "领料与金工流转",
    "procurement": "采购与供应商", "inventory": "库存与仓库", "outsourcing": "外协",
    "workshop_config": "车间配置", "workshop_reporting": "工价与报工",
    "workflow": "任务与审批", "reference_data": "基础配置", "audit": "审计",
    "preferences": "个人保存视图", "material_catalog": "原料管理", "product_catalog": "产品管理",
}
EXTRA_MODULES = {f"access_control.{code}": module for code, _label, module in EXTRA_OPERATIONS}
# Existing import/export implementations use dedicated codes. Their grants follow
# create/view respectively; overwrites still need change + object scope at use sites.
IMPLIED = {
    "quotations.view_quotation": ("quotations.export_quotation",),
    "customers.add_customercontact": ("customers.import_customercontact",),
}


def module_for(code):
    return EXTRA_MODULES.get(code, code.split(".", 1)[0])


def scopes_for(code):
    from .resource_scopes import configured, scope_kind
    if configured() and scope_kind(code):
        if code.startswith('outsourcing.') and 'outsourcingorder' in code:
            return ('MODULE', 'CRAFT', 'WORKSHOP', 'STOCK')
        return ('MODULE', scope_kind(code))
    if module_for(code) == 'preferences':
        return ('OWN',)
    if 'businesstask' in code and module_for(code) == 'workflow':
        return ('OWN', 'TEAM', 'ALL')
    if module_for(code) == 'samples' and not any(part in code for part in ('inventory', 'procurement')):
        return ('OWN', 'TEAM', 'ALL', 'MODULE')
    # Templates/tags are shared configuration even when owned by a sales app.
    if module_for(code) in SALES_APPS and not any(x in code for x in ("template", "customertag", "containerconfig")):
        return ("OWN", "TEAM", "ALL")
    return ("MODULE",)


def permission_code(permission):
    return f"{permission.content_type.app_label}.{permission.codename}"


def permission_map():
    codes = set(PERMISSION_CODES) | {p for values in IMPLIED.values() for p in values}
    return {permission_code(p): p for p in Permission.objects.select_related("content_type")
            if permission_code(p) in codes}


def catalog():
    permissions = permission_map()
    return [{
        "code": code, "module": module_for(code),
        "module_name": MODULE_NAMES[module_for(code)],
        **presentation(code, permissions.get(code), module_for(code)),
        "scopes": scopes_for(code), "available": code in permissions,
        "integration_stage": 4 if module_for(code) in SALES_APPS else 5,
        "implied_permissions": list(IMPLIED.get(code, ())),
    } for code in PERMISSION_CODES]


def validate_grants(rows):
    permissions = permission_map()
    seen = set()
    result = []
    for row in rows:
        code, scope = row["permission"], row["scope"]
        if code not in PERMISSION_CODES or code not in permissions:
            raise ValidationError({"grants": f"未开放的业务权限：{code}"})
        if scope not in scopes_for(code):
            raise ValidationError({"grants": f"{code} 不支持范围 {scope}"})
        if (code, scope) in seen:
            raise ValidationError({"grants": "同一权限与范围不可重复。"})
        seen.add((code, scope))
        result.append((permissions[code], scope))
    return result


def projected_permission_ids(grants):
    permissions = permission_map()
    ids = set()
    for permission, _scope in grants:
        ids.add(permission.pk)
        for code in IMPLIED.get(permission_code(permission), ()):
            if code not in permissions:
                raise ValidationError({"grants": f"缺少关联权限 {code}，请先完成迁移。"})
            ids.add(permissions[code].pk)
    return ids
