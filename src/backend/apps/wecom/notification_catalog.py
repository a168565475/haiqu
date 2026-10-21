"""业务通知事件登记表。

事件代码、可用变量、接收范围和跳转目标均由后端登记；业务服务只能引用这里
的事件，不接受前端或调用方传入任意代码和 URL。
"""

from copy import deepcopy
import re

from .notification_access import EVENT_OBJECT_PERMISSIONS, UNAVAILABLE_EVENT_OBJECTS


RECIPIENT_SCOPES = {
    "ROLE_MEMBERS": "所选角色的合法成员",
    "WORKSHOP": "对应车间的合法成员",
    "SUBMITTER": "仅本单申请人/提交人",
}

VARIABLE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")


def _event(name, title, body, roles, scopes, required_permission, target_key, *, enabled=True, variables=None):
    required_variables = list(dict.fromkeys(VARIABLE.findall(f"{title} {body}")))
    return {
        "event_code": name,
        "display_name": title,
        "default_title": title,
        "default_body": body,
        "allowed_variables": list(variables) if variables is not None else [
            "document_no", "product_name", "quantity", "operator", "occurred_at",
            "workshop_name", "status", "submitter", "object_version",
        ],
        "required_variables": required_variables,
        "default_role_codes": list(roles),
        "supported_scopes": list(scopes),
        "required_permission": required_permission,
        "target_key": target_key,
        "enabled_by_default": enabled,
    }


EVENTS = {
    "PRODUCTION_TASK_CONFIRMED": _event(
        "PRODUCTION_TASK_CONFIRMED", "生产任务确认", "生产任务 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 确认。",
        ["TECHNICAL"], ["ROLE_MEMBERS"], "production_tasks.view_productiontask", "production-task-detail",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "object_version"),
    ),
    "BOM_CONFIRMED": _event(
        "BOM_CONFIRMED", "BOM确认", "BOM {{document_no}}（{{product_name}}，版本 {{object_version}}）已由 {{operator}} 于 {{occurred_at}} 确认。",
        ["PURCHASING"], ["ROLE_MEMBERS"], "boms.view_bom", "bom-detail",
    ),
    "PRODUCTION_TASK_BOMS_CONFIRMED": _event(
        "PRODUCTION_TASK_BOMS_CONFIRMED", "任务BOM全部确认",
        "生产任务 {{document_no}} 的 {{product_count}} 项产品明细最新BOM已全部确认，由 {{operator}} 于 {{occurred_at}} 完成。",
        ["PURCHASING"], ["ROLE_MEMBERS"], "boms.view_bom", "task-boms",
        variables=("document_no", "product_count", "operator", "occurred_at", "object_version"),
    ),
    "SUPPLIER_PURCHASE_SHEET_PUBLISHED": _event(
        "SUPPLIER_PURCHASE_SHEET_PUBLISHED", "供应商采购表发布", "供应商采购表 {{document_no}} 已发布。",
        [], ["ROLE_MEMBERS"], "procurement.view_supplierpurchasesheet", "supplier-purchase-sheet-detail", enabled=False,
    ),
    "MATERIAL_RECEIPT_RECORDED": _event(
        "MATERIAL_RECEIPT_RECORDED", "到货登记", "到货单 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 登记，等待检验。",
        ["QUALITY"], ["ROLE_MEMBERS"], "inventory.view_materialinbound", "material-inbound-detail",
        variables=("document_no", "operator", "occurred_at", "status", "object_version"),
    ),
    "MATERIAL_INSPECTION_CONFIRMED": _event(
        "MATERIAL_INSPECTION_CONFIRMED", "检验结果确认", "采购单 {{purchase_order_no}} 的到货单 {{document_no}} 检验结果：{{status}}。",
        ["PURCHASING"], ["ROLE_MEMBERS"], "inventory.view_materialinbound", "material-inbound-detail",
        variables=("document_no", "purchase_order_no", "accepted_quantity", "return_quantity",
                   "operator", "occurred_at", "status", "object_version"),
    ),
    "PURCHASE_ORDER_COMPLETED": _event(
        "PURCHASE_ORDER_COMPLETED", "采购手动完结", "采购单 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 完结。",
        ["ADMINISTRATION"], ["ROLE_MEMBERS"], "procurement.view_purchaseorder", "purchase-order-detail",
        variables=("document_no", "operator", "occurred_at", "status", "object_version"),
    ),
    "PRODUCTION_PLAN_CREATED": _event(
        "PRODUCTION_PLAN_CREATED", "作业计划创建", "作业计划 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 创建。",
        ["METAL_DIRECTOR", "ASSEMBLY_DIRECTOR", "SEWING_DIRECTOR"], ["WORKSHOP"],
        "production_scheduling.view_productionschedule", "production-plan-detail",
        variables=("document_no", "operator", "occurred_at", "object_version"),
    ),
    "MATERIAL_ISSUE_SUBMITTED": _event(
        "MATERIAL_ISSUE_SUBMITTED", "领料单提交", "领料单 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 提交。",
        ["WAREHOUSE_KEEPER"], ["ROLE_MEMBERS"], "material_issues.view_materialissue", "material-issue-detail",
        variables=("document_no", "operator", "occurred_at", "workshop_name", "product_name", "status", "object_version"),
    ),
    "SEMI_FINISHED_RECEIPT_SUBMITTED": _event(
        "SEMI_FINISHED_RECEIPT_SUBMITTED", "半成品入库申请提交", "半成品入库申请 {{document_no}} 已提交，等待仓管确认。",
        ["WAREHOUSE_KEEPER"], ["ROLE_MEMBERS"], "inventory.view_internalsemifinishedreceipt", "semi-finished-receipt-detail",
    ),
    "WAGE_SCHEME_SUBMITTED": _event(
        "WAGE_SCHEME_SUBMITTED", "工价送审", "工价方案 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 送审。",
        ["FACTORY_MANAGER"], ["ROLE_MEMBERS"], "workshop_reporting.view_wagescheme", "wage-scheme-detail",
        variables=("document_no", "operator", "occurred_at", "workshop_name", "product_name", "status", "object_version"),
    ),
    "WAGE_SCHEME_DECIDED": _event(
        "WAGE_SCHEME_DECIDED", "工价批准/退回", "工价方案 {{document_no}} 的结果为 {{status}}。",
        ["METAL_DIRECTOR", "ASSEMBLY_DIRECTOR", "SEWING_DIRECTOR"], ["WORKSHOP"],
        "workshop_reporting.view_wagescheme", "wage-scheme-detail",
        variables=("document_no", "operator", "occurred_at", "workshop_name", "product_name", "status", "object_version"),
    ),
    "WORK_REPORT_SAVED": _event(
        "WORK_REPORT_SAVED", "报工保存", "报工 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 保存。",
        ["FACTORY_MANAGER"], ["ROLE_MEMBERS"], "workshop_reporting.view_workreport", "work-report-detail",
        variables=("document_no", "operator", "occurred_at", "workshop_name", "product_name", "status", "object_version"),
    ),
    "WORK_REPORT_CORRECTED": _event(
        "WORK_REPORT_CORRECTED", "报工更正", "报工 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 更正，请查看当前明细。",
        ["FACTORY_MANAGER"], ["ROLE_MEMBERS"], "workshop_reporting.view_workreport", "work-report-detail",
        variables=("document_no", "operator", "occurred_at", "workshop_name", "product_name", "status", "object_version"),
    ),
    "WORK_REPORT_DELETED": _event(
        "WORK_REPORT_DELETED", "报工删除", "报工 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 删除。原因摘要：{{reason_summary}}。原记录已删除，本消息仅供知悉。",
        ["FACTORY_MANAGER"], ["ROLE_MEMBERS"], "workshop_reporting.view_workreport", "work-report-deletion-notice",
        variables=("document_no", "operator", "occurred_at", "workshop_name", "product_name", "reason_summary", "status", "object_version"),
    ),
    "OUTSOURCING_LOSS_RECORDED": _event(
        "OUTSOURCING_LOSS_RECORDED", "委外损耗登记", "委外单 {{document_no}} 已登记{{kind}} {{quantity}} {{unit}}，由 {{operator}} 于 {{occurred_at}} 操作。",
        ["FACTORY_MANAGER"], ["ROLE_MEMBERS"], "outsourcing.view_outsourcingorder", "outsourcing-loss-detail",
        variables=("document_no", "operator", "occurred_at", "quantity", "unit", "kind", "reason_summary", "status", "object_version"),
    ),
    "TUBE_OUTSOURCING_SHORTAGE_RECORDED": _event(
        "TUBE_OUTSOURCING_SHORTAGE_RECORDED", "管材/裁片委外少回登记", "外发单 {{document_no}} 最终回货少回 {{quantity}} {{unit}}，由 {{operator}} 于 {{occurred_at}} 登记。",
        ["FACTORY_MANAGER"], ["ROLE_MEMBERS"], "outsourcing.view_outsourcingorder", "tube-outsourcing-shortage-detail",
        variables=("document_no", "operator", "occurred_at", "quantity", "unit", "reason_summary", "status", "object_version"),
    ),
    "OUTSOURCING_ORDER_CREATED": _event(
        "OUTSOURCING_ORDER_CREATED", "待外发委外单建立", "委外单 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 建立。",
        ["WAREHOUSE_KEEPER", "METAL_DIRECTOR", "SEWING_DIRECTOR"], ["ROLE_MEMBERS", "WORKSHOP"], "outsourcing.view_outsourcingorder", "outsourcing-order-detail",
        variables=("document_no", "operator", "occurred_at", "status", "object_version"),
    ),
    "TUBE_OUTSOURCING_ORDER_CREATED": _event(
        "TUBE_OUTSOURCING_ORDER_CREATED", "管材/裁片待外发单建立",
        "外发单 {{document_no}}（来源 {{source_name}}）已由 {{operator}} 于 {{occurred_at}} 建立。",
        ["WAREHOUSE_KEEPER", "METAL_DIRECTOR", "SEWING_DIRECTOR"], ["ROLE_MEMBERS", "WORKSHOP"],
        "outsourcing.view_outsourcingorder", "tube-outsourcing-order-detail",
        variables=("document_no", "operator", "occurred_at", "source_kind", "source_name", "workshop_name", "product_name", "status", "object_version"),
    ),
    "SAMPLE_SUBMITTED": _event(
        "SAMPLE_SUBMITTED", "打样申请提交", "打样申请 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 提交。",
        ["FACTORY_MANAGER"], ["ROLE_MEMBERS", "SUBMITTER"], "samples.view_samplerequest", "sample-detail",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "submitter", "object_version"),
    ),
    "SAMPLE_EFFECTIVE": _event(
        "SAMPLE_EFFECTIVE", "打样生效待完善", "打样申请 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 生效，请完善需求。",
        ["METAL_SAMPLING"], ["ROLE_MEMBERS"], "samples.complete_sample_requirements", "sample-detail",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "submitter", "object_version"),
    ),
    "SAMPLE_RETURNED": _event(
        "SAMPLE_RETURNED", "打样申请退回", "打样申请 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 退回，请查看意见并补充重提。",
        ["SALESPERSON", "ACCOUNT_MANAGER", "ADMINISTRATION", "FACTORY_MANAGER", "GENERAL_MANAGER"], ["SUBMITTER"], "samples.add_samplerequest", "sample-detail",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "submitter", "object_version"),
    ),
    "SAMPLE_REQUIREMENTS_COMPLETED": _event(
        "SAMPLE_REQUIREMENTS_COMPLETED", "打样需求完善完成", "打样申请 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 完善，请填写材料需求或确认无需用料。",
        ["METAL_SAMPLING"], ["ROLE_MEMBERS"], "samples.edit_sample_materials", "sample-material-detail",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "submitter", "object_version"),
    ),
    "SAMPLE_MATERIALS_SUBMITTED": _event(
        "SAMPLE_MATERIALS_SUBMITTED", "打样材料需求提交", "打样申请 {{document_no}} 的材料需求已由 {{operator}} 于 {{occurred_at}} 提交，请核库。",
        ["WAREHOUSE_KEEPER"], ["ROLE_MEMBERS"], "samples.review_sample_materials", "sample-warehouse-review",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "submitter", "object_version"),
    ),
    "SAMPLE_MATERIAL_SHORTAGE": _event(
        "SAMPLE_MATERIAL_SHORTAGE", "打样材料缺料", "打样申请 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 核库，存在缺料，请按真实缺料明细采购。",
        ["PURCHASING"], ["ROLE_MEMBERS"], "samples.view_sample_procurement", "sample-material-detail",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "submitter", "object_version"),
    ),
    "SAMPLE_MATERIALS_AVAILABLE": _event(
        "SAMPLE_MATERIALS_AVAILABLE", "打样材料可申请领料", "打样申请 {{document_no}} 于 {{occurred_at}} 已有可领材料，请核对现有可供及到货明细后申请领料；不代表全部齐料或已经发料。",
        ["METAL_SAMPLING"], ["ROLE_MEMBERS"], "samples.edit_sample_materials", "sample-material-issue",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "submitter", "object_version"),
    ),
    "SAMPLE_MATERIAL_ISSUE_SUBMITTED": _event(
        "SAMPLE_MATERIAL_ISSUE_SUBMITTED", "样品领料申请", "打样申请 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 发起领料，请仓库确认实际发料。",
        ["WAREHOUSE_KEEPER"], ["ROLE_MEMBERS"], "samples.review_sample_materials", "sample-material-issue",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "submitter", "object_version"),
    ),
    "SAMPLE_MATERIAL_ISSUED": _event(
        "SAMPLE_MATERIAL_ISSUED", "样品实际发料", "打样申请 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 实际发料，请按本岗位权限维护参数或报工。未到货采购仍按原流程处理。",
        ["METAL_SAMPLING"], ["ROLE_MEMBERS"], "samples.edit_sample_materials", "sample-detail",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "submitter", "object_version"),
    ),
    "SAMPLE_PRODUCTION_READY": _event(
        "SAMPLE_PRODUCTION_READY", "打样无需用料可生产", "打样申请 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 确认无需用料，请按本岗位权限维护参数或报工。",
        ["METAL_SAMPLING"], ["ROLE_MEMBERS"], "samples.edit_sample_materials", "sample-detail",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "submitter", "object_version"),
    ),
    "SAMPLE_COMPLETED": _event(
        "SAMPLE_COMPLETED", "打样完成", "打样申请 {{document_no}} 已于 {{occurred_at}} 完成参数和两工序生产。请仓管按剩余可入库数量办理样品入库，厂长知悉。",
        ["WAREHOUSE_KEEPER", "FACTORY_MANAGER"], ["ROLE_MEMBERS"], "samples.view_samplerequest", "sample-detail",
        variables=("document_no", "product_name", "operator", "occurred_at", "status", "submitter", "object_version"),
    ),
    "SAMPLE_INVENTORY_RECEIVED": _event(
        "SAMPLE_INVENTORY_RECEIVED", "样品入库", "样品入库单 {{document_no}} 已由 {{operator}} 于 {{occurred_at}} 登记。",
        ["FACTORY_MANAGER"], ["ROLE_MEMBERS"], "samples.view_samplerequest", "sample-detail", enabled=False,
    ),
}


def get_event(event_code):
    try:
        event = deepcopy(EVENTS[event_code])
    except KeyError:
        raise ValueError(f"未登记的通知事件：{event_code}") from None
    event["required_permissions"] = list(EVENT_OBJECT_PERMISSIONS[event_code])
    event["required_permission"] = next(iter(event["required_permissions"]), "")
    return event


def all_events():
    return [get_event(code) for code in EVENTS]


def target_for(event_code, object_id):
    event = get_event(event_code)
    if not object_id or event_code in UNAVAILABLE_EVENT_OBJECTS or event_code == "WORK_REPORT_DELETED":
        return None
    routes = {
        "PRODUCTION_TASK_CONFIRMED": ("production-task-detail", "taskId"),
        "BOM_CONFIRMED": ("bom-preview", "bomId"),
        "PRODUCTION_TASK_BOMS_CONFIRMED": ("boms", None),
        "SUPPLIER_PURCHASE_SHEET_PUBLISHED": ("supplier-purchase-sheet-editor", "id"),
        "MATERIAL_RECEIPT_RECORDED": ("material-quality-confirmation", None),
        "MATERIAL_INSPECTION_CONFIRMED": ("purchase-order-detail", "id"),
        "PURCHASE_ORDER_COMPLETED": ("purchase-order-detail", "id"),
        "PRODUCTION_PLAN_CREATED": ("workshop-scheduling-detail", "scheduleId"),
        "MATERIAL_ISSUE_SUBMITTED": ("material-issue-detail", "issueId"),
        "WAGE_SCHEME_SUBMITTED": ("wage-scheme-detail", "schemeId"),
        "WAGE_SCHEME_DECIDED": ("wage-scheme-detail", "schemeId"),
        "WORK_REPORT_SAVED": ("work-report-day-detail", "productionDate"),
        "WORK_REPORT_CORRECTED": ("work-report-day-detail", "productionDate"),
        "OUTSOURCING_LOSS_RECORDED": ("workshop-outsourcing-detail", "orderId"),
        "TUBE_OUTSOURCING_SHORTAGE_RECORDED": ("workshop-outsourcing-tube-detail", "orderId"),
        "OUTSOURCING_ORDER_CREATED": ("workshop-outsourcing-detail", "orderId"),
        "TUBE_OUTSOURCING_ORDER_CREATED": ("workshop-outsourcing-tube-detail", "orderId"),
        "SAMPLE_SUBMITTED": ("sample-detail", "sampleId"),
        "SAMPLE_EFFECTIVE": ("sample-detail", "sampleId"),
        "SAMPLE_RETURNED": ("sample-detail", "sampleId"),
        "SAMPLE_REQUIREMENTS_COMPLETED": ("sample-material-detail", "sampleId"),
        "SAMPLE_MATERIALS_SUBMITTED": ("sample-warehouse-review", "sampleId"),
        "SAMPLE_MATERIAL_SHORTAGE": ("sample-material-detail", "sampleId"),
        "SAMPLE_MATERIALS_AVAILABLE": ("sample-material-issue", "sampleId"),
        "SAMPLE_MATERIAL_ISSUE_SUBMITTED": ("sample-material-issue-confirm", "sampleId"),
        "SAMPLE_MATERIAL_ISSUED": ("sample-detail", "sampleId"),
        "SAMPLE_PRODUCTION_READY": ("sample-detail", "sampleId"),
        "SAMPLE_COMPLETED": ("sample-detail", "sampleId"),
        "SAMPLE_INVENTORY_RECEIVED": ("sample-inventory-receipt-detail", "receiptId"),
    }
    name, parameter = routes[event_code]
    value = object_id
    if event_code == "MATERIAL_INSPECTION_CONFIRMED":
        from apps.inventory.models import MaterialInbound
        value = MaterialInbound.objects.filter(pk=object_id).values_list("purchase_order_id", flat=True).first()
    elif event_code in {"WORK_REPORT_SAVED", "WORK_REPORT_CORRECTED"}:
        from apps.workshop_reporting.models import WorkReport
        value = WorkReport.objects.filter(pk=object_id).values_list("production_date", flat=True).first()
    elif event_code == "OUTSOURCING_LOSS_RECORDED":
        from apps.outsourcing.models import OutsourcingReconciliationEntry
        value = OutsourcingReconciliationEntry.objects.filter(pk=object_id).values_list("record__order_id", flat=True).first()
    elif event_code == "TUBE_OUTSOURCING_SHORTAGE_RECORDED":
        from apps.outsourcing.models import TubeOutsourcingReceiptLine
        value = TubeOutsourcingReceiptLine.objects.filter(pk=object_id).values_list("receipt__order_id", flat=True).first()
    elif event_code in {"SAMPLE_MATERIAL_SHORTAGE", "SAMPLE_MATERIAL_ISSUE_SUBMITTED", "SAMPLE_MATERIAL_ISSUED"}:
        from apps.samples.notification_events import sample_for_event
        sample, _ = sample_for_event(event_code, object_id)
        value = sample.pk if sample else None
    if value is None:
        return None
    return {"target_key": event["target_key"], "object_id": str(object_id),
            "route_name": name, "params": {parameter: str(value)} if parameter else {}}
