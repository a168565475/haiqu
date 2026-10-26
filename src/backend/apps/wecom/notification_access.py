"""通知对象的当前授权；事件固定对象模型，列表和投递共用业务查询边界。"""

from types import SimpleNamespace
from uuid import UUID


# 办理通知检查对应动作；知悉通知检查真实读取动作。配置角色不产生权限。
EVENT_OBJECT_PERMISSIONS = {
    "PRODUCTION_TASK_CONFIRMED": ("production_tasks.view_productiontask",),
    "BOM_CONFIRMED": ("boms.view_bom",),
    "PRODUCTION_TASK_BOMS_CONFIRMED": ("boms.view_bom",),
    "SUPPLIER_PURCHASE_SHEET_PUBLISHED": ("procurement.view_supplierpurchasesheet",),
    "MATERIAL_RECEIPT_RECORDED": ("inventory.quality_confirm_material",),
    "MATERIAL_INSPECTION_CONFIRMED": ("procurement.view_purchaseorder",),
    "PURCHASE_ORDER_COMPLETED": ("procurement.view_purchaseorder",),
    "PRODUCTION_PLAN_CREATED": ("production_scheduling.view_productionschedule",),
    "MATERIAL_ISSUE_SUBMITTED": ("material_issues.review_materialissue",),
    "SEMI_FINISHED_RECEIPT_SUBMITTED": ("inventory.view_internalsemifinishedreceipt",),
    "ASSEMBLY_FINISHED_RECEIPT_SUBMITTED": ("inventory.view_finishedgoodsreceipt",),
    "INTERNAL_SEMI_RECEIPT_CONFIRMED": ("inventory.view_internalsemifinishedreceipt",),
    "ASSEMBLY_FINISHED_RECEIPT_CONFIRMED": ("inventory.view_finishedgoodsreceipt",),
    "FINISHED_GOODS_OUTBOUND_CONFIRMED": ("inventory.view_finishedgoodsoutbound",),
    "WAGE_SCHEME_SUBMITTED": ("workshop_reporting.approve_wagescheme",),
    "WAGE_SCHEME_DECIDED": ("workshop_reporting.view_wagescheme",),
    "WORK_REPORT_SAVED": ("workshop_reporting.view_workreport",),
    "WORK_REPORT_CORRECTED": ("workshop_reporting.view_workreport",),
    "WORK_REPORT_DELETED": ("workshop_reporting.view_workreport",),
    "OUTSOURCING_LOSS_RECORDED": ("outsourcing.view_outsourcingorder",),
    "TUBE_OUTSOURCING_SHORTAGE_RECORDED": ("outsourcing.view_outsourcingorder",),
    "OUTSOURCING_ORDER_CREATED": ("outsourcing.confirm_dispatch_outsourcingorder",),
    "TUBE_OUTSOURCING_ORDER_CREATED": ("outsourcing.confirm_dispatch_outsourcingorder",),
    "SAMPLE_SUBMITTED": ("samples.review_sample_application",),
    "SAMPLE_EFFECTIVE": ("samples.complete_sample_requirements",),
    "SAMPLE_RETURNED": ("samples.add_samplerequest",),
    "SAMPLE_REQUIREMENTS_COMPLETED": ("samples.edit_sample_materials",),
    "SAMPLE_MATERIALS_SUBMITTED": ("samples.review_sample_materials",),
    "SAMPLE_MATERIAL_SHORTAGE": ("samples.view_sample_procurement",),
    "SAMPLE_MATERIALS_AVAILABLE": ("samples.edit_sample_materials",),
    "SAMPLE_MATERIAL_ISSUE_SUBMITTED": ("samples.review_sample_materials",),
    "SAMPLE_MATERIAL_ISSUED": ("access_control.metalwork_sample", "access_control.cutting_sample", "access_control.metalreport_sample", "access_control.cuttingreport_sample"),
    "SAMPLE_PRODUCTION_READY": ("access_control.metalwork_sample", "access_control.cutting_sample", "access_control.metalreport_sample", "access_control.cuttingreport_sample"),
    "SAMPLE_COMPLETED": ("samples.view_samplerequest", "samples.add_sampleinventoryreceipt"),
    "SAMPLE_INVENTORY_RECEIVED": ("samples.view_sampleinventoryline",),
}

UNAVAILABLE_EVENT_OBJECTS = {}


def plan_workshop_ids(object_id):
    """多车间计划从已保存的有效厂内工艺取关系，不相信单个上下文车间。"""
    from apps.production_scheduling.models import ProductionScheduleProductCraft

    return set(str(value) for value in ProductionScheduleProductCraft.objects.filter(
        schedule_product__schedule_id=object_id,
        schedule_product__removed_at__isnull=True, removed_at__isnull=True,
        craft_type_snapshot="INTERNAL", plan_category__in=["METAL", "ASSEMBLY", "SEWING"],
        craft__workshop_id__isnull=False,
    ).values_list("craft__workshop_id", flat=True))


def _request_for(user, employee, permission):
    # 现有 selector 从 parser_context 取得当前动作，避免借用其他动作的范围。
    view = SimpleNamespace(action="notification", action_permission_map={"notification": permission})
    return SimpleNamespace(
        user=user, employee=employee, method="GET", query_params={}, parser_context={"view": view},
    )


def _purchase_task_ids(request):
    from apps.production_tasks.selectors import accessible_production_tasks

    return accessible_production_tasks(request).filter(archived_at__isnull=True).values("pk")


def _object_queryset(event_code, request, permission):
    if event_code == "PRODUCTION_TASK_CONFIRMED":
        from apps.production_tasks.selectors import accessible_production_tasks

        return accessible_production_tasks(request).filter(archived_at__isnull=True)

    if event_code == "BOM_CONFIRMED":
        from apps.boms.selectors import accessible_boms

        return accessible_boms(request).filter(production_task__archived_at__isnull=True)

    if event_code == "PRODUCTION_TASK_BOMS_CONFIRMED":
        from apps.production_tasks.models import ProductionTask
        return ProductionTask.objects.filter(archived_at__isnull=True)

    if event_code == "SUPPLIER_PURCHASE_SHEET_PUBLISHED":
        from django.db.models import Q
        from apps.procurement.models import SupplierPurchaseSheet
        from apps.procurement.source_access import purchase_order_access

        task_ids = _purchase_task_ids(request)
        return SupplierPurchaseSheet.objects.filter(
            purchase_order_access(task_ids, request, "purchase_order__")
            | Q(purchase_request__production_task_id__in=task_ids),
            archived_at__isnull=True,
        )

    if event_code in {"MATERIAL_RECEIPT_RECORDED", "MATERIAL_INSPECTION_CONFIRMED"}:
        from apps.inventory.models import MaterialInbound
        from apps.procurement.source_access import purchase_order_access

        # 与品质批次 API 相同，生产采购和打样采购均沿实际来源检查。
        return MaterialInbound.objects.filter(
            purchase_order_access(_purchase_task_ids(request), request, "purchase_order__"),
            purchase_order__archived_at__isnull=True,
        )

    if event_code == "PURCHASE_ORDER_COMPLETED":
        from apps.procurement.selectors import active_purchase_orders
        from apps.procurement.source_access import purchase_order_access

        return active_purchase_orders().filter(purchase_order_access(_purchase_task_ids(request), request))

    if event_code == "PRODUCTION_PLAN_CREATED":
        from apps.production_scheduling.selectors import accessible_production_schedules

        return accessible_production_schedules(request).filter(
            record_status="ACTIVE", production_task__archived_at__isnull=True,
        )

    if event_code == "MATERIAL_ISSUE_SUBMITTED":
        from apps.material_issues.selectors import accessible_material_issues

        return accessible_material_issues(request)

    if event_code == "INTERNAL_SEMI_RECEIPT_CONFIRMED":
        from apps.inventory.models import InternalSemiFinishedReceipt
        from apps.production_tasks.selectors import accessible_production_tasks
        return InternalSemiFinishedReceipt.objects.filter(
            schedule_product__schedule__production_task_id__in=accessible_production_tasks(request).values("pk"))

    if event_code == "SEMI_FINISHED_RECEIPT_SUBMITTED":
        from apps.inventory.models import InternalSemiFinishedReceipt
        from apps.production_tasks.selectors import accessible_production_tasks
        return InternalSemiFinishedReceipt.objects.filter(
            schedule_product__schedule__production_task_id__in=accessible_production_tasks(request).values("pk"))

    if event_code == "ASSEMBLY_FINISHED_RECEIPT_CONFIRMED":
        from apps.inventory.selectors import receipt_batches
        return receipt_batches().filter(source_type="PRODUCTION_ORDER", assembly_source__isnull=False)

    if event_code == "ASSEMBLY_FINISHED_RECEIPT_SUBMITTED":
        from apps.inventory.selectors import receipt_batches
        return receipt_batches().filter(source_type="PRODUCTION_ORDER", assembly_source__isnull=False)

    if event_code == "FINISHED_GOODS_OUTBOUND_CONFIRMED":
        from apps.inventory.selectors import finished_goods_outbounds
        return finished_goods_outbounds()

    if event_code in {"WAGE_SCHEME_SUBMITTED", "WAGE_SCHEME_DECIDED"}:
        from apps.workshop_reporting.selectors import accessible_wage_schemes

        return accessible_wage_schemes(request, permission=permission)

    if event_code in {"WORK_REPORT_SAVED", "WORK_REPORT_CORRECTED"}:
        from apps.workshop_reporting.selectors import accessible_work_reports

        return accessible_work_reports(request, permission=permission)

    if event_code == "WORK_REPORT_DELETED":
        from apps.workshop_reporting.models import WorkReportHistory
        from apps.workshop_reporting.selectors import allowed_workshop_ids
        ids = allowed_workshop_ids(request, permission=permission, for_work_reports=True)
        rows = WorkReportHistory.objects.filter(deleted_at__isnull=False)
        return rows if ids is None else rows.filter(deletion_snapshot__workshop_id__in=[str(value) for value in ids])

    if event_code == "OUTSOURCING_LOSS_RECORDED":
        from apps.outsourcing.models import OutsourcingReconciliationEntry
        from apps.outsourcing.selectors import accessible_outsourcing_orders
        return OutsourcingReconciliationEntry.objects.filter(record__order__in=accessible_outsourcing_orders(request, permission=permission))

    if event_code == "TUBE_OUTSOURCING_SHORTAGE_RECORDED":
        from apps.outsourcing.models import TubeOutsourcingReceiptLine
        from apps.outsourcing.tube_selectors import saved_orders_for_permission
        return TubeOutsourcingReceiptLine.objects.filter(receipt__order__in=saved_orders_for_permission(request, permission))

    if event_code == "OUTSOURCING_ORDER_CREATED":
        from apps.outsourcing.selectors import accessible_outsourcing_orders

        # 此事件固定 OutsourcingOrder；管材/裁剪委外有另一模型及页面，不能猜测。
        return accessible_outsourcing_orders(request, permission=permission)

    if event_code == "TUBE_OUTSOURCING_ORDER_CREATED":
        from apps.outsourcing.tube_selectors import saved_orders_for_permission
        return saved_orders_for_permission(request, permission)

    from apps.samples.notification_events import SAMPLE_EVENTS
    if event_code in SAMPLE_EVENTS:
        from apps.samples.selectors import accessible_sample_requests
        if event_code in {"SAMPLE_MATERIAL_ISSUE_SUBMITTED", "SAMPLE_MATERIAL_ISSUED"}:
            from apps.samples.models import SampleMaterialIssue
            return SampleMaterialIssue.objects.filter(material_request__sample_request__in=accessible_sample_requests(request, permission))
        if event_code == "SAMPLE_MATERIAL_SHORTAGE":
            from apps.samples.models import SampleMaterialProcurementRequest
            return SampleMaterialProcurementRequest.objects.filter(material_request__sample_request__in=accessible_sample_requests(request, permission))
        return accessible_sample_requests(request, permission).filter(archived_at__isnull=True)

    if event_code == "SAMPLE_INVENTORY_RECEIVED":
        from apps.samples.inventory_selectors import sample_inventory_receipts_with_detail

        # 入库单可含多个样品，object_id 固定为入库单，不能当成 SampleRequest 的主键。
        return sample_inventory_receipts_with_detail()

    return None


def event_object_accessible(event_code, object_id, user, *, role_codes=None, object_version=None, submitter_id=None,
                            permission_snapshots=None):
    """检查当前有效身份、可选历史接收角色、实际动作及对象范围。

    role_codes 仅用于重试时确认快照接收角色仍有效，不用当前规则追收新成员。
    submitter_id 仅由原提交人回执传入，允许当前超级管理员读取本人的回执。
    permission_snapshots 只由一次列表请求提供；身份、接收角色和对象检查仍逐条执行。
    未登记事件、尚无真实申请模型或不存在的对象均拒绝；数据库错误正常上抛。
    """
    if event_code not in EVENT_OBJECT_PERMISSIONS or event_code in UNAVAILABLE_EVENT_OBJECTS:
        return False
    if not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return False
    try:
        identifier = UUID(str(object_id))
    except (TypeError, ValueError, AttributeError):
        return False

    from django.contrib.auth import get_user_model
    from apps.access_control import module_policy, sales_policy
    from apps.access_control.selectors import current_assignments
    from apps.organizations.models import Employee

    # 每次查询数据库，不沿用会话里的旧 is_active 或旧权限缓存。
    current_user = get_user_model().objects.filter(pk=user.pk, is_active=True).first()
    if current_user is None:
        return False
    employee = Employee.objects.filter(
        user=current_user, status="ACTIVE", archived_at__isnull=True,
    ).first()
    if employee is None:
        return False
    from apps.samples.notification_events import SAMPLE_EVENTS, current_sample_object, sample_for_event
    if event_code in SAMPLE_EVENTS:
        if current_sample_object(event_code, identifier, object_version) is None:
            return False
        if event_code == 'SAMPLE_RETURNED' and sample_for_event(event_code, identifier)[0].requested_by_employee_id != employee.pk:
            return False
    is_superuser_submitter = current_user.is_superuser and str(employee.pk) == str(submitter_id)
    if role_codes is not None and not is_superuser_submitter and not current_assignments(employee).filter(
        role_profile__role_code__in=role_codes,
    ).exists():
        return False

    from .workshop_notifications import WORKSHOP_EVENTS, current_workshop_object
    from apps.inventory.notification_events import INVENTORY_EVENTS, current_inventory_object
    if event_code in INVENTORY_EVENTS and current_inventory_object(event_code, identifier, object_version) is None:
        return False
    from .workshop_change_notifications import CHANGE_EVENTS, current_change_object
    if event_code in CHANGE_EVENTS and current_change_object(event_code, identifier, object_version) is None:
        return False
    if event_code in WORKSHOP_EVENTS:
        obj = current_workshop_object(event_code, identifier, object_version)
        if obj is None:
            return False
        if (event_code == "MATERIAL_ISSUE_SUBMITTED"
                and obj.submitted_by_employee_id == employee.pk and not current_user.is_superuser):
            return False
        if event_code == "WAGE_SCHEME_SUBMITTED":
            submitter = obj.events.filter(action="SUBMITTED").order_by(
                "-scheme_revision", "-created_at", "-id").values_list("actor_employee_id", flat=True).first()
            if submitter == employee.pk and not current_user.is_superuser:
                return False

    bom_snapshot = None
    if event_code == "PRODUCTION_TASK_BOMS_CONFIRMED":
        from apps.boms.notification_events import current_task_bom_snapshot, snapshot_version
        bom_snapshot = current_task_bom_snapshot(identifier)
        if bom_snapshot is None or snapshot_version(bom_snapshot) != object_version:
            return False

    for permission in EVENT_OBJECT_PERMISSIONS[event_code]:
        request = _request_for(current_user, employee, permission)
        if permission_snapshots is not None and module_policy.enabled():
            if current_user.pk not in permission_snapshots:
                permission_snapshots[current_user.pk] = sales_policy.access_for(request)
            request._sales_access_snapshot = permission_snapshots[current_user.pk]
        if not module_policy.has_permission(request, permission):
            continue
        queryset = _object_queryset(event_code, request, permission)
        if queryset is not None and queryset.filter(pk=identifier).exists():
            if bom_snapshot is not None:
                from apps.boms.selectors import accessible_boms
                return accessible_boms(request).filter(pk__in=[row["bom_id"] for row in bom_snapshot]).count() == len(bom_snapshot)
            return True
    return False
