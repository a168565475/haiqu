from .hardware_stock_weights import piece_weight_change
from .models import MaterialStockBalance, MaterialStockMovement, PublicStockMovement
from .public_stock_services import debit_public_stock
from .stock_services import InventoryStockValidationError


def posted_purchase_receipt_lines(inbound):
    source = {"source_type": "MATERIAL_INBOUND", "source_id": inbound.pk, "direction": "IN"}
    credits = {entry.source_line_id: entry for entry in MaterialStockMovement.objects.filter(**source)}
    credits.update((entry.source_line_id, entry) for entry in PublicStockMovement.objects.filter(**source))
    return credits


def validate_posted_receipt_identity(line, credit):
    if credit is None or "public_stock_identity" not in credit.snapshot:
        return
    from .pipe_stock_services import pipe_error

    identity = line.calculation_snapshot.get("public_stock_identity")
    if not identity:
        raise pipe_error("PUBLIC_STOCK_IDENTITY_INCOMPLETE", "入库缺少已冻结公共库存身份，请核对原收货记录。")
    if identity != credit.snapshot["public_stock_identity"]:
        raise pipe_error("PIPE_LENGTH_MISMATCH", "已入账管材的冻结库存身份发生变化，请核对原收货记录。")


def debit_quality_return(*, return_line, receipt_credit, actor_employee):
    line = return_line.inbound_line
    quantity = line.return_bar_count if line.measurement_kind == "PIPE" else line.return_quantity
    weight = line.return_weight_kg if receipt_credit.weight_quantity is not None else None
    source = {
        "source_type": "PURCHASE_RETURN", "source_id": return_line.return_order_id, "source_line_id": return_line.pk,
        "actor_employee": actor_employee, "production_task": receipt_credit.production_task_id,
        "snapshot": {
            "inbound_line_id": str(line.pk), "inbound_number": line.inbound.inbound_number,
            "measurement_kind": (line.calculation_snapshot or {}).get("measurement_kind", line.measurement_kind),
        },
    }
    if isinstance(receipt_credit, PublicStockMovement):
        return debit_public_stock(balance_id=receipt_credit.balance_id, quantity=quantity, weight_quantity=weight, **source)

    balance = MaterialStockBalance.objects.select_for_update(of=("self",)).select_related("unit").get(pk=receipt_credit.balance_id)
    before_quantity = balance.quantity
    if quantity > before_quantity:
        raise InventoryStockValidationError("原收货库区库存不足，请先核对领用或办理退料。", code="STOCK_INSUFFICIENT")
    meters = quantity * balance.raw_bar_length_m if balance.raw_bar_length_m is not None and quantity else None
    before_meters = balance.meter_quantity if meters is not None else None
    before_weight = balance.weight_quantity
    if line.measurement_kind == "PIPE":
        after_weight = before_weight - weight if before_weight is not None and weight is not None else before_weight
    else:
        before_weight, weight, after_weight = piece_weight_change(
            before_quantity=before_quantity, before_weight=before_weight, quantity=quantity, direction="OUT",
            weight_quantity=weight, quantity_unit=balance.unit.unit_name if before_weight is not None or weight is not None else "",
        )
    if after_weight is not None and after_weight < 0:
        raise InventoryStockValidationError("原收货库区库存重量不足，请先核对领用或办理退料。", code="STOCK_INSUFFICIENT")
    balance.quantity -= quantity
    if meters is not None:
        balance.meter_quantity -= meters
    balance.weight_quantity = after_weight
    balance.version += 1
    balance.save(update_fields=["quantity", "meter_quantity", "weight_quantity", "version", "updated_at"])
    return MaterialStockMovement.objects.create(
        balance=balance, direction="OUT", quantity=quantity, before_quantity=before_quantity, after_quantity=balance.quantity,
        meter_quantity=meters, before_meter_quantity=before_meters,
        after_meter_quantity=balance.meter_quantity if meters is not None else None,
        weight_quantity=weight, before_weight_quantity=before_weight, after_weight_quantity=after_weight,
        production_task_id=source.pop("production_task"), **source,
    )
