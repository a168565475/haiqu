"""生产管材实点根数，采购单的冻结公斤仅用于计价。"""
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP, localcontext

from django.db.models import Exists, OuterRef, Q
from rest_framework.exceptions import ValidationError

from apps.procurement.models import PurchaseOrderLine
from apps.procurement.pipe_purchase import pipe_meters
from .models import MaterialInboundLine


ROOT_RECEIPT = {"receipt_quantity_mode": "ROOTS"}


def is_root_receipt(line):
    return (getattr(line, "calculation_snapshot", None) or {}).get("receipt_quantity_mode") == "ROOTS"


def root_receipt_line_ids(lines):
    eligible = PurchaseOrderLine.objects.filter(pk__in=[line.pk for line in lines],
        purchase_order__source_type="PRODUCTION", source_unit_text__in=["KG", "kg", "千克", "公斤"],
        section_type_snapshot="PROFILE", actual_bar_count__gt=0, raw_bar_length_m__gt=0,
    ).filter(Q(material_catalog__isnull=True) | Q(material_selection_snapshot__contains={"category_key": "TUBE", "processing_state": "RAW"}))
    # 同一采购批次只采用一种收货口径。旧单的待检量也已占用公斤额度。
    old_receipts = MaterialInboundLine.objects.filter(purchase_order_line_id=OuterRef("pk")).exclude(calculation_snapshot__contains=ROOT_RECEIPT)
    return set(eligible.filter(~Exists(old_receipts)).order_by().values_list("pk", flat=True))


def root_receipt_values(purchase, item):
    if item.get("received_weight_kg") is not None or item.get("received_quantity") is not None:
        raise ValidationError({"received_bar_count": "这批管材请直接填写实收根数。"})
    roots, meters = pipe_meters(item.get("received_bar_count"), purchase.raw_bar_length_m, field="received_bar_count")
    item["received_quantity"] = meters
    return {"measurement_kind": "PIPE", "raw_bar_length_m": purchase.raw_bar_length_m,
        "received_bar_count": roots, "accepted_bar_count": roots, "return_bar_count": 0,
        "calculation_snapshot": {**purchase.calculation_snapshot, **ROOT_RECEIPT}}


def allocated_order_kg(purchase_line, roots):
    with localcontext() as context:
        context.prec = 64
        return (purchase_line.actual_purchase_quantity * roots / purchase_line.actual_bar_count).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP)


def freeze_settlement_weights(receipts, confirmed):
    accepted = Counter()
    for line in confirmed:
        if is_root_receipt(line):
            accepted[line.purchase_order_line_id] += line.accepted_bar_count
    for line in receipts:
        if is_root_receipt(line):
            previous = accepted[line.purchase_order_line_id]
            accepted[line.purchase_order_line_id] += line.accepted_bar_count
            purchase = line.purchase_order_line
            weight = allocated_order_kg(purchase, previous + line.accepted_bar_count) - allocated_order_kg(purchase, previous)
            line.calculation_snapshot = {**line.calculation_snapshot, "settlement_weight_kg": str(weight)}
