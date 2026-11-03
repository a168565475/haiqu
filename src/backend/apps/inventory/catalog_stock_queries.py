"""按保存材料查询余额；供业务来源核库，不预留也不扣账。"""
from decimal import Decimal

from apps.material_catalog.definitions import CATEGORY_CHOICES
from apps.material_catalog.saved_selection import validate_saved_material
from apps.material_catalog.snapshots import material_identity_key

from .catalog_stock_identity import build_catalog_stock_identity
from .models import PublicStockBalance
from .public_stock_services import _database_identity, _uuid


def available_catalog_balances(*, material_catalog_id, material_selection_snapshot, zone_id=None, raw_bar_length_m=None):
    from .tube_outsourcing_reservations import reserved_quantity_for_balance

    selected = validate_saved_material(material_selection_snapshot, material_catalog_id=material_catalog_id)
    pipe = selected["category_key"] == "TUBE" and selected["processing_state"] == "RAW"
    if pipe and raw_bar_length_m is None:
        from .stock_services import InventoryStockValidationError
        if selected["unit_name"] != "根":
            raise InventoryStockValidationError("原管可用库存按根及实际批次原长查询。", code="UNIT_MISMATCH")
        identity = {"stock_kind": "CATALOG_RAW", "unit_id": selected["unit_id"]}
        identity_filter = {"identity_snapshot__material_key": material_identity_key(selected)}
    else:
        identity = _database_identity(build_catalog_stock_identity(material_catalog_id=material_catalog_id,
            material_selection_snapshot=selected, raw_bar_length_m=raw_bar_length_m))
        identity_filter = {"identity_key": identity["identity_key"]}
    query = PublicStockBalance.objects.filter(
        **identity_filter, stock_kind=identity["stock_kind"], unit_id=identity["unit_id"],
        quality="AVAILABLE", quantity__gt=0, zone__status="ACTIVE", zone__warehouse__status="ACTIVE",
        zone__warehouse__warehouse_type="MATERIAL" if identity["stock_kind"] == "CATALOG_RAW" else "SEMI_FINISHED",
        unit__status="ACTIVE", unit__archived_at__isnull=True,
    ).select_related("zone__warehouse", "unit").order_by("zone_id", "id")
    if zone_id is not None:
        query = query.filter(zone_id=_uuid(zone_id, "库区"))
    rows = []
    for balance in query:
        reserved = reserved_quantity_for_balance(balance)
        rows.append({"balance_id": str(balance.pk), "stock_kind": balance.stock_kind,
            "identity_key": balance.identity_key, "identity_snapshot": balance.identity_snapshot,
            "material_catalog_id": str(balance.material_catalog_id),
            "material_selection_snapshot": balance.identity_snapshot["material_selection_snapshot"],
            "unit_id": str(balance.unit_id), "unit_name": balance.identity_snapshot["unit_name"],
            "warehouse_id": str(balance.zone.warehouse_id), "warehouse_name": balance.zone.warehouse.warehouse_name,
            "zone_id": str(balance.zone_id), "zone_name": balance.zone.zone_name, "quality": balance.quality,
            "raw_bar_length_m": balance.raw_bar_length_m, "meter_quantity": balance.meter_quantity,
            "quantity": balance.quantity, "reserved_quantity": reserved,
            "available_quantity": max(balance.quantity - reserved, Decimal(0)), "version": balance.version})
    return rows


def catalog_stock_summary(balance):
    from django.db.models import Sum, Q
    from .models import PublicStockMovement

    selected = balance.identity_snapshot["material_selection_snapshot"]
    balances = PublicStockBalance.objects.filter(stock_kind=balance.stock_kind, identity_key=balance.identity_key,
        unit_id=balance.unit_id).select_related("zone__warehouse").order_by("zone_id", "id")
    totals = balances.aggregate(available=Sum("quantity", filter=Q(quality="AVAILABLE")), defective=Sum("quantity", filter=Q(quality="DEFECTIVE")))
    movement = PublicStockMovement.objects.filter(balance__in=balances).aggregate(
        inbound=Sum("quantity", filter=Q(direction="IN")), issued=Sum("quantity", filter=Q(direction="OUT")))
    free = available_catalog_balances(material_catalog_id=balance.material_catalog_id, material_selection_snapshot=selected,
        raw_bar_length_m=balance.raw_bar_length_m)
    return {"stock_item_id": str(balance.material_catalog_id), "material_catalog_id": str(balance.material_catalog_id),
        "identity_key": balance.identity_key, "material_selection_snapshot": selected, "stock_kind": "RAW" if balance.stock_kind == "CATALOG_RAW" else "SEMI",
        "measurement_kind": "PIPE" if balance.raw_bar_length_m else "CATALOG", "material_number": "", "material_name": selected["name"],
        "category": dict(CATEGORY_CHOICES)[selected["category_key"]],
        "specification": " / ".join(selected["attributes"].values()), "color": selected["attributes"].get("color", ""),
        "unit": selected["unit_name"], "current_quantity": str(totals["available"] or 0),
        "available_quantity": str(sum((row["available_quantity"] for row in free), Decimal(0))),
        "defective_quantity": str(totals["defective"] or 0), "cumulative_inbound_quantity": str(movement["inbound"] or 0),
        "cumulative_issued_quantity": str(movement["issued"] or 0),
        "meter_quantity": str((totals["available"] or 0) * balance.raw_bar_length_m) if balance.raw_bar_length_m else None,
        "zones": [{"zone_id": str(row.zone_id), "balance_id": str(row.pk), "warehouse_number": row.zone.warehouse.warehouse_number,
            "warehouse_name": row.zone.warehouse.warehouse_name, "zone_name": row.zone.zone_name, "quality": row.quality,
            "quantity": str(row.quantity), "inbound_line_id": None, "raw_bar_length_m": str(row.raw_bar_length_m) if row.raw_bar_length_m else None,
            "meter_quantity": str(row.meter_quantity) if row.meter_quantity is not None else None} for row in balances]}
