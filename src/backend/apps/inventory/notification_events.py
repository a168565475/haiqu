"""库存成功知悉：原单身份与不可变入出库事实，不以剩余库存判断历史成功。"""
import hashlib
import json

from django.core.serializers.json import DjangoJSONEncoder

from .models import InternalSemiFinishedReceipt, FinishedGoodsReceipt, FinishedGoodsOutbound


INVENTORY_EVENTS = {"SEMI_FINISHED_RECEIPT_SUBMITTED", "INTERNAL_SEMI_RECEIPT_CONFIRMED",
                    "ASSEMBLY_FINISHED_RECEIPT_SUBMITTED", "ASSEMBLY_FINISHED_RECEIPT_CONFIRMED",
                    "FINISHED_GOODS_OUTBOUND_CONFIRMED"}


def inventory_event_submitter_id(code, obj):
    if code in {"SEMI_FINISHED_RECEIPT_SUBMITTED", "INTERNAL_SEMI_RECEIPT_CONFIRMED"}:
        return str(obj.actor_employee_id)
    if code in {"ASSEMBLY_FINISHED_RECEIPT_SUBMITTED", "ASSEMBLY_FINISHED_RECEIPT_CONFIRMED"}:
        return str(obj.received_by_employee_id)
    return None


def _snapshot(code, obj):
    if code in {"SEMI_FINISHED_RECEIPT_SUBMITTED", "INTERNAL_SEMI_RECEIPT_CONFIRMED"}:
        return {"number": obj.receipt_number, "request": str(obj.request_id), "payload": obj.request_payload_hash,
            "source": obj.source_revision_hash, "plan": str(obj.schedule_product_id), "craft": str(obj.completed_craft_id),
            "category": obj.plan_category, "date": str(obj.receipt_date), "zone": str(obj.zone_id),
            "actor": str(obj.actor_employee_id), "snapshot": obj.source_snapshot,
            "lines": list(obj.lines.order_by("pk").values("id", "bom_line_id", "quantity", "unit_id",
                "stock_movement_id", "stock_movement__quantity", "stock_movement__source_id"))}
    if code in {"ASSEMBLY_FINISHED_RECEIPT_SUBMITTED", "ASSEMBLY_FINISHED_RECEIPT_CONFIRMED"}:
        source = obj.assembly_source
        return {"number": obj.receipt_number, "product": str(obj.production_task_product_id),
            "source_type": obj.source_type, "unit": str(obj.unit_id), "quantity": obj.received_quantity,
            "location": str(obj.location_id), "color": obj.actual_color, "name": obj.product_name_snapshot,
            "actor": str(obj.received_by_employee_id), "received_at": obj.received_at.isoformat(),
            "request": str(source.request_id), "payload": source.payload_hash, "source": source.snapshot,
            "date": str(source.receipt_date)}
    return {"number": obj.outbound_number, "actor": str(obj.outbound_by_employee_id),
        "outbound_at": obj.outbound_at.isoformat(),
        "lines": list(obj.lines.order_by("pk").values("id", "receipt_id", "outbound_quantity",
            "before_quantity", "after_quantity"))}


def inventory_event_version(code, obj):
    return hashlib.sha256(json.dumps(_snapshot(code, obj), cls=DjangoJSONEncoder, sort_keys=True,
        ensure_ascii=False).encode()).hexdigest()


def current_inventory_object(code, identifier, version=None):
    if code in {"SEMI_FINISHED_RECEIPT_SUBMITTED", "INTERNAL_SEMI_RECEIPT_CONFIRMED"}:
        obj = InternalSemiFinishedReceipt.objects.filter(pk=identifier).first()
        if obj is None:
            return None
        status = getattr(obj, "status", None)
        if status and ((code.endswith("SUBMITTED") and status not in {"PENDING", "SUBMITTED"})
                       or (code.endswith("CONFIRMED") and status != "CONFIRMED")):
            return None
        if code == "INTERNAL_SEMI_RECEIPT_CONFIRMED" and (not obj.lines.exists() or obj.lines.exclude(
            stock_movement__direction="IN", stock_movement__balance__stock_kind="SEMI",
            stock_movement__source_type="INTERNAL_SEMI_RECEIPT", stock_movement__source_id=obj.pk,
        ).exists()):
            return None
    elif code in {"ASSEMBLY_FINISHED_RECEIPT_SUBMITTED", "ASSEMBLY_FINISHED_RECEIPT_CONFIRMED"}:
        obj = FinishedGoodsReceipt.objects.select_related("assembly_source").filter(pk=identifier,
            source_type="PRODUCTION_ORDER", assembly_source__isnull=False).first()
        if obj is None or (getattr(obj, "status", None) and
                           ((code.endswith("SUBMITTED") and obj.status not in {"PENDING", "SUBMITTED"})
                            or (code.endswith("CONFIRMED") and obj.status != "CONFIRMED"))):
            return None
    elif code == "FINISHED_GOODS_OUTBOUND_CONFIRMED":
        obj = FinishedGoodsOutbound.objects.filter(pk=identifier).first()
        if obj is None or not obj.lines.exists():
            return None
    else:
        return None
    return obj if version is None or inventory_event_version(code, obj) == str(version) else None


def _register(code, obj, actor, document_no, occurred_at, **facts):
    from apps.wecom.notification_services import register_business_event
    return register_business_event(event_code=code, idempotency_key=f"{code}:{obj.pk}",
        object_type=obj._meta.label, object_id=obj.pk, object_version=inventory_event_version(code, obj),
        context={"document_no": document_no, "operator": actor.display_name,
            "occurred_at": occurred_at.isoformat(), "status": "已入库" if code != "FINISHED_GOODS_OUTBOUND_CONFIRMED" else "已出库",
            **facts})


def _confirmation_facts(receipt, actor, occurred_at, *, submitter_id=None, confirmed_by=None, confirmed_at=None):
    """统一登记提交人及仓库确认事实，兼容当前直接确认和后续待确认单据。"""
    original_submitter = submitter_id or getattr(receipt, "actor_employee_id", None) or getattr(receipt, "received_by_employee_id", None)
    submitter = getattr(receipt, "actor_employee", None)
    if submitter is None and getattr(receipt, "received_by_employee_id", None):
        submitter = getattr(receipt, "received_by_employee", None)
    confirmer = actor
    if getattr(receipt, "confirmed_by_employee_id", None):
        confirmer = getattr(receipt, "confirmed_by_employee", None) or actor
    confirmer_name = confirmed_by or getattr(confirmer, "display_name", "")
    confirmation_time = confirmed_at or getattr(receipt, "confirmed_at", None) or occurred_at
    return {
        "submitter_id": str(original_submitter or actor.pk),
        "submitter": getattr(submitter, "display_name", ""),
        "confirmed_by": confirmer_name,
        "confirmed_at": confirmation_time.isoformat() if hasattr(confirmation_time, "isoformat") else str(confirmation_time),
    }


def internal_receipt_submitted(receipt, actor):
    return _register("SEMI_FINISHED_RECEIPT_SUBMITTED", receipt, actor, receipt.receipt_number, receipt.created_at,
        product_name=receipt.source_snapshot.get("product", ""), receipt_date=str(receipt.receipt_date),
        status="待仓库确认")


def assembly_receipt_submitted(receipt, actor):
    return _register("ASSEMBLY_FINISHED_RECEIPT_SUBMITTED", receipt, actor, receipt.receipt_number, receipt.received_at,
        product_name=receipt.product_name_snapshot, receipt_date=str(receipt.assembly_source.receipt_date),
        quantity=str(receipt.received_quantity), unit=receipt.unit.unit_name, status="待仓库确认")


def internal_receipt_confirmed(receipt, actor, *, submitter_id=None, confirmed_by=None, confirmed_at=None):
    occurred_at = getattr(receipt, "confirmed_at", None) or receipt.created_at
    return _register("INTERNAL_SEMI_RECEIPT_CONFIRMED", receipt, actor, receipt.receipt_number, occurred_at,
        product_name=receipt.source_snapshot.get("product", ""), receipt_date=str(receipt.receipt_date),
        **_confirmation_facts(receipt, actor, occurred_at, submitter_id=submitter_id,
                              confirmed_by=confirmed_by, confirmed_at=confirmed_at))


def assembly_receipt_confirmed(receipt, actor, *, submitter_id=None, confirmed_by=None, confirmed_at=None):
    occurred_at = getattr(receipt, "confirmed_at", None) or receipt.received_at
    return _register("ASSEMBLY_FINISHED_RECEIPT_CONFIRMED", receipt, actor, receipt.receipt_number, occurred_at,
        product_name=receipt.product_name_snapshot, receipt_date=str(receipt.assembly_source.receipt_date),
        quantity=str(receipt.received_quantity), unit=receipt.unit.unit_name,
        **_confirmation_facts(receipt, actor, occurred_at, submitter_id=submitter_id,
                              confirmed_by=confirmed_by, confirmed_at=confirmed_at))


def finished_outbound_confirmed(outbound, actor):
    return _register("FINISHED_GOODS_OUTBOUND_CONFIRMED", outbound, actor, outbound.outbound_number, outbound.outbound_at)
