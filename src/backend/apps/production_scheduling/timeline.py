"""生产事件只读索引：保留来源事件身份，不复制或补造历史审计。"""
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from rest_framework import serializers

from apps.access_control.module_policy import has_permission
from apps.audit.models import AuditLog
from apps.boms.selectors import accessible_boms
from apps.boms.models import BomStatus
from apps.inventory.models import FinishedGoodsReceipt, FinishedGoodsOutbound, MaterialInbound
from apps.inventory.internal_receipt_models import InternalSemiFinishedReceipt
from apps.material_issues.models import MaterialIssueAuditEvent
from apps.material_issues.selectors import accessible_material_issues
from apps.procurement.models import PurchaseOrder, PurchaseRequest, PurchaseReturn, SupplierPurchaseSheet
from apps.production_tasks.selectors import accessible_production_tasks
from apps.production_tasks.models import ProductionTaskStatus
from apps.procurement.models import PurchaseOrderStatus
from apps.workshop_reporting.models import WageSchemeEvent
from apps.workshop_reporting.selectors import accessible_wage_schemes, accessible_work_reports, allowed_workshop_ids
from .detail_related import _read_request, _sources_for_tasks
from .selectors import accessible_production_schedules


class TimelineQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, max_length=100, default="")
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class TimelineEventSerializer(serializers.Serializer):
    id = serializers.CharField()
    kind = serializers.CharField()
    title = serializers.CharField()
    actor_name = serializers.CharField()
    occurred_at = serializers.DateTimeField()
    document_number = serializers.CharField(allow_blank=True)
    detail_path = serializers.CharField(allow_null=True)
    changes = serializers.ListField(child=serializers.DictField(child=serializers.CharField(allow_blank=True)))


class TimelineResponseSerializer(serializers.Serializer):
    data = TimelineEventSerializer(many=True)
    meta = serializers.DictField(child=serializers.IntegerField())


ACTION_LABELS = {
    "CREATED": "创建", "CREATE": "创建", "CREATED_FROM_SALES_ORDER": "由销售订单创建",
    "UPDATED": "修改", "UPDATE": "修改", "SUBMITTED": "提交", "SUBMIT": "提交",
    "CONFIRMED": "确认", "APPROVED": "审批通过", "REJECTED": "审批退回",
    "RETURNED_BY_PMC": "PMC 退回", "SCHEDULED": "完成排产", "SCHEDULE_VOIDED": "排产作废",
    "COMPLETED": "完成", "COMPLETED_EXCEPTION": "异常完成", "CANCELLED": "取消",
    "VOIDED": "作废", "DELETE": "删除", "DELETED": "删除", "STARTED": "开始生产",
    "CONFIRM_PRODUCT": "确认产品资料", "VERIFIED": "确认 BOM", "REUSE_PRODUCT_REVIEW": "复用产品审核",
    "PURCHASING": "开始采购", "DISPATCH_CONFIRMED": "确认发出", "DISPATCH_REVOKED": "撤销发出",
    "RETURN_COMPLETED": "完成回货", "CHANGE_CREATED": "发起变更", "ISSUED": "领料出库",
    "QUALITY_GENERATED": "生成退货单", "RECEIVED": "收货", "PUBLISHED": "发布",
    "WITHDRAWN": "撤回", "CLOSED": "结清", "QUALITY_CONFIRMED": "确认质检",
    "REVIEW_PRODUCT": "审核产品资料", "VERIFY": "确认", "SUBMITTED_FOR_QUALITY": "提交质检",
    "UPDATED_AFTER_CONFIRMATION": "确认后修改", "SYNC_FROM_PRODUCTION_TASK": "同步生产任务资料",
    "ARCHIVE": "归档", "ARCHIVED": "归档", "ALLOCATION_ADJUSTED": "调整分配",
    "DIRECT_GOOD_RETURN_CONFIRMED": "确认金工合格回货", "DIRECT_HANDOFF_CONFIRMED": "确认金工交接",
    "DIRECT_UNSPRAYED_RETURN_CONFIRMED": "确认未喷塑退回", "DIRECT_HANDOFF_STATE_UPDATED": "更新金工交接状态",
    "PRODUCTION_DELIVERY_DATE_UPDATED": "调整生产交货日期",
    "RAW_RETURN_CONFIRMED": "确认余料退回", "DIRECT_HANDOFF_CLOSED": "结清金工交接",
    "DIRECT_HANDOFF_PENDING_CANCELLED": "取消待交接",
}
SAFE_FIELDS = {
    "status": "状态", "record_status": "记录状态", "reason": "原因", "status_reason": "状态说明",
    "remark": "备注", "comment": "审批意见", "delivery_date": "交货日期",
    "production_date": "生产日期", "receipt_date": "入库日期", "shipment_date": "出库日期",
    "planned_start_date": "计划开始", "planned_end_date": "计划结束", "version": "版本",
}
NUMBER_FIELDS = ("task_number", "schedule_number", "bom_number", "order_number", "report_number",
                 "receipt_number", "outbound_number", "inbound_number", "scheme_number", "issue_number")
STATUS_LABELS = {"PRODUCTION_TASK": dict(ProductionTaskStatus.choices), "PURCHASE_ORDER": dict(PurchaseOrderStatus.choices),
                 "BOM": dict(BomStatus.choices), "PRODUCTION_SCHEDULE": {"ACTIVE": "有效", "VOID": "已作废"}}


def event_row(*, identity, kind, label, action, actor, at, number="", path=None, before=None, after=None):
    before, after = before or {}, after or {}
    changes = []
    for key, title in SAFE_FIELDS.items():
        old, new = before.get(key), after.get(key)
        if old == new or (old in (None, "") and new in (None, "")) or isinstance(old, (dict, list)) or isinstance(new, (dict, list)):
            continue
        if key in {"status", "record_status"}:
            labels = STATUS_LABELS.get(kind, {})
            old, new = labels.get(old, old), labels.get(new, new)
        changes.append({"label": title, "before": "" if old is None else str(old),
                        "after": "" if new is None else str(new)})
    action_label = ACTION_LABELS.get(action, action)
    if kind == "PRODUCTION_TASK":
        action_label = {"SUBMITTED": "提交 PMC 确认", "CONFIRMED": "PMC 确认"}.get(action, action_label)
    return {"id": identity, "kind": kind, "title": f"{action_label} · {label}",
            "actor_name": actor or "操作人未记录", "occurred_at": at, "document_number": number,
            "detail_path": path, "changes": changes}


def production_timeline(request, schedule):
    """各来源先按本模块查看权限和数据范围取单据，再读取其事件；不输出原始快照。"""
    task_id = schedule.production_task_id
    product_ids = [product.product_line_id for product in schedule.active_products]
    documents = {}
    rows = []

    def allowed(permission):
        return has_permission(request, permission)

    def task_allowed(permission):
        return allowed(permission) and accessible_production_tasks(
            _read_request(request, permission)).filter(pk=task_id).exists()

    def register(kind, label, queryset, number_field, path=None):
        records = list(queryset)
        documents[kind] = {str(record.pk): (label, str(getattr(record, number_field, "") or ""),
                           path(record) if path and not getattr(record, "archived_at", None) else None) for record in records}
        return records

    task_request = _read_request(request, "production_tasks.view_productiontask")
    task_visible = allowed("production_tasks.view_productiontask") and accessible_production_tasks(
        task_request).filter(pk=task_id).exists()
    if task_visible:
        register("PRODUCTION_TASK", "生产任务单", [schedule.production_task], "task_number",
                 lambda item: f"/production-tasks/{item.pk}")
    register("PRODUCTION_SCHEDULE", "排产单", accessible_production_schedules(request).filter(
        production_task_id=task_id), "schedule_number", lambda item: f"/workshop/scheduling/{item.pk}")
    if allowed("boms.view_bom"):
        register("BOM", "BOM", accessible_boms(_read_request(request, "boms.view_bom")).filter(
            production_task_id=task_id, product_line_id__in=product_ids), "bom_number",
            lambda item: f"/boms/{item.pk}/preview")
    # 采购和仓库单据以生产任务为数据范围；不能借排产权限打开这些模块。
    orders = PurchaseOrder.objects.filter(production_task_id=task_id)
    if task_allowed("procurement.view_purchaseorder"):
        register("PURCHASE_ORDER", "采购订单", orders, "order_number",
                 lambda item: f"/purchase-orders/{item.pk}/details")
    if task_allowed("procurement.view_purchaserequest"):
        register("PURCHASE_REQUEST", "采购申请", PurchaseRequest.objects.filter(production_task_id=task_id), "request_number")
    if task_allowed("procurement.view_supplierpurchasesheet"):
        register("SUPPLIER_PURCHASE_SHEET", "供应商采购表", SupplierPurchaseSheet.objects.filter(
            Q(purchase_order__in=orders) | Q(purchase_request__production_task_id=task_id)), "sheet_number",
            lambda item: f"/supplier-purchase-sheets/{item.pk}")
    if task_allowed("procurement.view_purchasereturn"):
        register("PURCHASE_RETURN", "采购退货", PurchaseReturn.objects.filter(purchase_order__in=orders), "return_number")
    if task_allowed("inventory.view_materialinbound"):
        register("MATERIAL_INBOUND", "采购入库", MaterialInbound.objects.filter(purchase_order__in=orders), "inbound_number",
                 lambda item: f"/purchase-inbound/{item.pk}/details")
    if task_allowed("inventory.view_finishedgoodsreceipt"):
        register("FINISHED_GOODS_RECEIPT", "成品入库", FinishedGoodsReceipt.objects.filter(
            production_task_product_id__in=product_ids), "receipt_number")
    if task_allowed("inventory.view_finishedgoodsoutbound"):
        register("FINISHED_GOODS_OUTBOUND", "成品出库", FinishedGoodsOutbound.objects.filter(
            lines__receipt__production_task_product_id__in=product_ids).distinct(), "outbound_number",
            lambda item: f"/inventory/finished-goods/outbounds/{item.pk}")
    originals, reworks, tubes, _ = _sources_for_tasks(request, [task_id], product_ids)
    from .timeline_metal import metal_events
    rows.extend(metal_events(request, task_id, product_ids, reworks))
    register("OUTSOURCING_ORDER", "外发单", originals, "order_number", lambda item: f"/workshop/outsourcing/{item.pk}")
    register("TUBE_OUTSOURCING_ORDER", "外发单", tubes, "order_number", lambda item: f"/workshop/outsourcing/tube/{item.pk}")
    register("METAL_PROCESSING_EXTERNAL_ORDER", "金工补加工外发", reworks, "order_number",
             lambda item: f"/workshop/outsourcing/rework/{item.pk}")
    if allowed("workshop_reporting.view_wagescheme"):
        schemes = accessible_wage_schemes(_read_request(request, "workshop_reporting.view_wagescheme"),
            permission="workshop_reporting.view_wagescheme").filter(product_line_id__in=product_ids)
        for event in WageSchemeEvent.objects.filter(scheme__in=schemes).select_related("scheme", "actor_employee"):
            rows.append(event_row(identity=f"wage:{event.pk}", kind="WAGE_SCHEME", label="工价方案",
                action=event.action, actor=event.actor_employee.display_name, at=event.created_at,
                number=event.scheme.scheme_number, path=f"/workshop/wage-schemes/{event.scheme_id}",
                after={"comment": event.comment}))
    reports = []
    if allowed("workshop_reporting.view_workreport"):
        reports = register("WORK_REPORT", "报工", accessible_work_reports(
            _read_request(request, "workshop_reporting.view_workreport"), permission="workshop_reporting.view_workreport"
        ).filter(product_line_id__in=product_ids), "report_number",
            lambda item: f"/workshop/work-reports/days/{item.production_date.isoformat()}")
    if allowed("material_issues.view_materialissue"):
        issues = accessible_material_issues(_read_request(request, "material_issues.view_materialissue")).filter(
            production_task_id=task_id, product_line_id__in=product_ids)
        for event in MaterialIssueAuditEvent.objects.filter(issue__in=issues).select_related("issue", "actor_employee"):
            rows.append(event_row(identity=f"issue:{event.pk}", kind="MATERIAL_ISSUE", label="领料单",
                action=event.action, actor=event.actor_employee.display_name, at=event.created_at,
                number=event.issue.issue_number, path=f"/workshop/material-issues/{event.issue_id}", after={"reason": event.reason}))
    if task_allowed("inventory.view_internalsemifinishedreceipt"):
        receipts = register("INTERNAL_SEMI_RECEIPT", "厂内半成品入库", InternalSemiFinishedReceipt.objects.filter(
            schedule_product__product_line_id__in=product_ids).select_related(
                "actor_employee", "submitted_by_employee", "confirmed_by_employee"), "receipt_number")
        for receipt in receipts:
            actor = receipt.submitted_by_employee or receipt.actor_employee
            rows.append(event_row(identity=f"internal:{receipt.pk}:created", kind="INTERNAL_SEMI_RECEIPT",
                label="厂内半成品入库", action="CONFIRMED" if not receipt.submitted_at and receipt.status == "CONFIRMED" else "SUBMITTED", actor=actor.display_name,
                at=receipt.submitted_at or receipt.created_at, number=receipt.receipt_number))
            if receipt.confirmed_at:
                rows.append(event_row(identity=f"internal:{receipt.pk}:confirmed", kind="INTERNAL_SEMI_RECEIPT",
                    label="厂内半成品入库", action="CONFIRMED",
                    actor=receipt.confirmed_by_employee.display_name if receipt.confirmed_by_employee else "",
                    at=receipt.confirmed_at, number=receipt.receipt_number))
    # 采购原单/采购表可以物理删除，沿保留的审计上下文恢复对象索引，不补写历史。
    if task_allowed("procurement.view_purchaseorder"):
        for event in AuditLog.objects.filter(object_type="PURCHASE_ORDER", context_type="PRODUCTION_TASK",
                                             context_id=task_id):
            key = str(event.object_id)
            if key not in documents.get("PURCHASE_ORDER", {}):
                snapshot = event.after_data or event.before_data or {}
                documents.setdefault("PURCHASE_ORDER", {})[key] = ("采购订单", str(snapshot.get("order_number", "")), None)
    if task_allowed("procurement.view_supplierpurchasesheet"):
        for event in AuditLog.objects.filter(object_type="SUPPLIER_PURCHASE_SHEET", context_type="PURCHASE_ORDER",
                                             context_id__in=list(documents.get("PURCHASE_ORDER", {}))):
            key = str(event.object_id)
            if key not in documents.get("SUPPLIER_PURCHASE_SHEET", {}):
                snapshot = event.after_data or event.before_data or {}
                documents.setdefault("SUPPLIER_PURCHASE_SHEET", {})[key] = ("供应商采购表", str(snapshot.get("sheet_number", "")), None)
    # 删除事件保留对象归属，即使原单已被删除仍可检索；仍按原模块及车间范围过滤。
    deleted_query = Q(pk__in=[])
    for kind, permission in (("WORK_REPORT", "workshop_reporting.view_workreport"),
                             ("INTERNAL_SEMI_RECEIPT", "inventory.view_internalsemifinishedreceipt"),
                             ("FINISHED_GOODS_RECEIPT", "inventory.view_finishedgoodsreceipt")):
        if allowed(permission) and (kind == "WORK_REPORT" or task_allowed(permission)):
            clause = Q(object_type=kind, action__in=["DELETE", "DELETED"],
                       before_data__product_line_id__in=[str(pk) for pk in product_ids])
            if kind == "WORK_REPORT":
                scope = allowed_workshop_ids(request, permission=permission, for_work_reports=True)
                if scope is not None:
                    clause &= Q(before_data__workshop_id__in=[str(pk) for pk in scope])
            deleted_query |= clause
    for event in AuditLog.objects.filter(deleted_query):
        before = event.before_data or {}
        label = {"WORK_REPORT": "报工", "INTERNAL_SEMI_RECEIPT": "厂内半成品入库",
                 "FINISHED_GOODS_RECEIPT": "成品入库"}[event.object_type]
        number = next((str(before[key]) for key in NUMBER_FIELDS if before.get(key)), "")
        documents.setdefault(event.object_type, {})[str(event.object_id)] = (label, number, None)
        time_key = "created_at" if event.object_type == "WORK_REPORT" else "submitted_at"
        original_time = parse_datetime(before[time_key]) if isinstance(before.get(time_key), str) else None
        if original_time and event.object_type != "FINISHED_GOODS_RECEIPT":
            rows.append(event_row(identity=f"deleted-origin:{event.pk}", kind=event.object_type, label=label,
                action="CREATED" if event.object_type == "WORK_REPORT" else "SUBMITTED",
                actor=before.get("recorder_name_snapshot", before.get("submitted_by_name", "")),
                at=original_time, number=number))
    query = Q(pk__in=[])
    for kind, records in documents.items():
        query |= Q(object_type=kind, object_id__in=list(records))
    events = list(AuditLog.objects.filter(query).order_by("occurred_at", "id"))
    created_reports = {event.object_id for event in events if event.object_type == "WORK_REPORT" and event.action == "CREATED"}
    # 新报工已有正式创建审计，删除快照只为旧记录提供真实创建时间，避免重复展示。
    audited_creations = {str(event.object_id) for event in events if event.action == "CREATED"}
    deleted_created_ids = {f"deleted-origin:{event.pk}" for event in events
                           if str(event.object_id) in audited_creations}
    rows = [row for row in rows if row["id"] not in deleted_created_ids]
    for report in reports:
        if report.pk not in created_reports:
            rows.append(event_row(identity=f"report:{report.pk}:created", kind="WORK_REPORT", label="报工",
                action="CREATED", actor=report.recorder_name_snapshot, at=report.created_at,
                number=report.report_number, path=f"/workshop/work-reports/days/{report.production_date.isoformat()}"))
    for event in events:
        label, number, path = documents[event.object_type][str(event.object_id)]
        rows.append(event_row(identity=f"audit:{event.pk}", kind=event.object_type, label=label,
            action=event.action, actor=event.actor_name_snapshot, at=event.occurred_at,
            number=number, path=path, before=event.before_data, after=event.after_data))
    return sorted(rows, key=lambda row: (row["occurred_at"], row["id"]))


def timeline_page(rows, params):
    words = params["search"].casefold().split()
    if words:
        rows = [row for row in rows if all(word in " ".join((row["title"], row["actor_name"],
            row["document_number"])).casefold() for word in words)]
    start = (params["page"] - 1) * params["page_size"]
    return {"data": rows[start:start + params["page_size"]],
            "meta": {"total": len(rows), "page": params["page"], "page_size": params["page_size"]}}
