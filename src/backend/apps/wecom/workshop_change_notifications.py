"""报工变更及委外损耗知悉；记录身份与业务操作权限分别核验。"""
import hashlib
import json

from .workshop_notifications import _register


CHANGE_EVENTS = {"WORK_REPORT_CORRECTED", "WORK_REPORT_DELETED", "OUTSOURCING_LOSS_RECORDED",
                 "TUBE_OUTSOURCING_SHORTAGE_RECORDED"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def summary(reason):
    return reason if len(reason) <= 120 else reason[:120] + "…（详见原记录）"


def deleted_version(history):
    return _digest({"report_id": str(history.report_id), "deleted_at": history.deleted_at.isoformat(),
        "snapshot": history.deletion_snapshot, "reason": history.deletion_reason})


def discrepancy_version(obj, *, tube=False):
    if tube:
        return _digest({"receipt_id": str(obj.receipt_id), "line_id": str(obj.order_line_id),
            "dispatched": obj.dispatched_quantity, "received": obj.received_quantity,
            "shortage": obj.shortage_quantity, "reason": obj.shortage_reason, "snapshot": obj.snapshot})
    return _digest({"record_id": str(obj.record_id), "allocation_id": str(obj.allocation_id),
        "kind": obj.kind, "quantity": str(obj.quantity), "unit": obj.unit_snapshot,
        "reason": obj.reason, "snapshot": obj.snapshot})


def current_change_object(code, identifier, version=None):
    if code == "WORK_REPORT_CORRECTED":
        from apps.workshop_reporting.models import WorkReport
        obj = WorkReport.objects.filter(pk=identifier).first()
        if obj is None or obj.product_line.production_task.archived_at is not None:
            return None
        current = str(obj.revision)
    elif code == "WORK_REPORT_DELETED":
        from apps.workshop_reporting.models import WorkReportHistory, WorkReport
        from apps.production_tasks.models import ProductionTaskProduct
        obj = WorkReportHistory.objects.filter(pk=identifier, deleted_at__isnull=False).first()
        if obj is None or WorkReport.objects.filter(pk=obj.report_id).exists():
            return None
        snapshot = obj.deletion_snapshot
        if (str(snapshot.get("id")) != str(obj.report_id) or not snapshot.get("workshop_id")
                or not ProductionTaskProduct.objects.filter(pk=snapshot.get("product_line_id"),
                    production_task__archived_at__isnull=True).exists()):
            return None
        current = deleted_version(obj)
    elif code == "OUTSOURCING_LOSS_RECORDED":
        from apps.outsourcing.models import OutsourcingReconciliationEntry
        obj = OutsourcingReconciliationEntry.objects.select_related("record__order__schedule__production_task").filter(
            pk=identifier, kind__in=["RAW_LOSS", "OUTPUT_SCRAP"]).first()
        if obj is None or obj.record.order.status == "CANCELLED" or obj.record.order.schedule.production_task.archived_at is not None:
            return None
        current = discrepancy_version(obj)
    elif code == "TUBE_OUTSOURCING_SHORTAGE_RECORDED":
        from apps.outsourcing.models import TubeOutsourcingReceiptLine
        from django.conf import settings
        from apps.inventory.public_stock_mode import public_flow_enabled
        if not getattr(settings, "TUBE_OUTSOURCING_ENABLED", False) or not public_flow_enabled():
            return None
        obj = TubeOutsourcingReceiptLine.objects.select_related("receipt__order__product_line__production_task").filter(
            pk=identifier, shortage_quantity__gt=0).first()
        if (obj is None or obj.receipt.order.status != "COMPLETED"
                or obj.receipt.order.product_line.production_task.archived_at is not None):
            return None
        current = discrepancy_version(obj, tube=True)
    else:
        return None
    return obj if version is None or current == str(version) else None


def report_corrected(report, actor):
    return _register("WORK_REPORT_CORRECTED", report, actor, report.report_number, report.revision,
        product_name=report.product_name_snapshot, workshop_name=report.workshop.name,
        workshop_id=str(report.workshop_id), status="已更正")


def report_deleted(history, actor):
    snapshot = history.deletion_snapshot
    return _register("WORK_REPORT_DELETED", history, actor, history.report_number, deleted_version(history),
        product_name=snapshot["product_name_snapshot"], workshop_name=snapshot["workshop_name"],
        workshop_id=snapshot["workshop_id"], reason_summary=summary(history.deletion_reason), status="已删除")


def reconciliation_losses(record, actor):
    for entry in record.entries.filter(kind__in=["RAW_LOSS", "OUTPUT_SCRAP"]).order_by("pk"):
        _register("OUTSOURCING_LOSS_RECORDED", entry, actor, record.order.order_number, discrepancy_version(entry),
            quantity=str(entry.quantity), unit=entry.unit_snapshot, kind=entry.get_kind_display(),
            reason_summary=summary(entry.reason), status="已登记")


def tube_shortages(receipt, actor):
    from apps.outsourcing.tube_kinds import output_unit
    for line in receipt.lines.filter(shortage_quantity__gt=0).order_by("pk"):
        _register("TUBE_OUTSOURCING_SHORTAGE_RECORDED", line, actor, receipt.order.order_number,
            discrepancy_version(line, tube=True), quantity=str(line.shortage_quantity),
            unit=output_unit(receipt.order.source_kind), reason_summary=summary(line.shortage_reason), status="已结束")
