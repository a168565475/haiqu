"""采购之外的材料收发：保存单据快照并直接变更公共库存。"""

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.boms.catalog_selection import SECTION_CATEGORIES, apply_catalog_selection
from apps.boms.material_flow_calculations import MaterialFlowValueError, decimal_quantity
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.material_catalog.models import MaterialCatalog
from apps.material_catalog.public_configuration import can_contribute
from apps.procurement.pipe_purchase import pipe_meters

from .catalog_stock_identity import build_catalog_stock_identity
from .catalog_manual_receipts import lock_manual_request
from .models import (
    MaterialStockQuality,
    MaterialTransfer,
    MaterialTransferDirection,
    MaterialTransferLine,
    RecordStatus,
    WarehouseType,
    WarehouseZone,
    PublicStockBalance,
)
from .public_stock_services import (
    credit_public_stock,
    debit_public_stock,
    lock_public_stock_locations,
)
from .public_stock_cutover import stock_write_transaction


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if hasattr(value, "hex") and value.__class__.__name__ == "UUID":
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _resolve_catalog(item, *, request, versions, direction):
    catalog_id = item["material_catalog_id"]
    catalog = MaterialCatalog.objects.select_for_update().filter(
        pk=catalog_id, archived_at__isnull=True,
    ).first()
    if catalog is None:
        raise ValidationError({"items": "品名不存在或已归档。"})
    title = next((name for name, category in SECTION_CATEGORIES.items() if category == catalog.category_key), None)
    if not title or catalog.category_key == "FABRIC_SEMI":
        raise ValidationError({"items": "材料收发只能选择基础原料。"})
    selection = deepcopy(item["material_selection"])
    projection = type("SelectionProjection", (), {})()
    projection.section = type("SelectionSection", (), {"title": title, "section_type": "PROFILE" if catalog.category_key == "TUBE" else "GENERAL"})()
    projection.raw_values = {}
    apply_catalog_selection(
        projection,
        {"material_catalog_id": catalog_id, "material_selection": selection},
        old=None,
        request=request,
        persist=True,
        versions=versions,
        allow_public_creation=can_contribute(request),
        prefer_catalog_options=True,
        selection_permission="inventory.receive_material",
    )
    selected = deepcopy(projection.material_selection_snapshot)
    if selected["processing_state"] != "RAW":
        raise ValidationError({"items": "材料收发只能选择原料，不能选择加工半成品。"})
    raw_length = item.get("raw_bar_length_m")
    raw_count = item.get("raw_bar_count")
    weight = item.get("weight_quantity")
    if selected["category_key"] == "TUBE":
        if selected["unit_name"] != "根":
            raise ValidationError({"items": "管材库存单位必须为根。"})
        if raw_count is None or raw_length is None:
            raise ValidationError({"items": "管材须填写根数和单根长度。"})
        pipe_meters(raw_count, raw_length, field="raw_bar_count")
        quantity = Decimal(raw_count)
        if direction == MaterialTransferDirection.IN:
            try:
                weight = decimal_quantity(weight, "weight_quantity", max_digits=22)
            except MaterialFlowValueError as error:
                raise ValidationError({"weight_quantity": "一般管材入库须填写实际重量 KG，且为最多 4 位小数的正数。"}) from error
        elif weight is not None:
            raise ValidationError({"weight_quantity": "一般出库重量按库存实际重量分摊，无需填写。"})
    else:
        if raw_count is not None or raw_length is not None or weight is not None:
            raise ValidationError({"items": "非管材不能填写根数、单根长度或管材重量。"})
        quantity = item.get("quantity")
        if quantity is None or quantity <= 0:
            raise ValidationError({"items": "请填写大于 0 的数量。"})
        if selected["unit_name"] in {"根", "支", "套"} and quantity != quantity.to_integral_value():
            raise ValidationError({"items": "根、支、套的数量必须为整数。"})
    item["material_selection_snapshot"] = selected
    item["quantity"] = quantity
    item["raw_bar_length_m"] = raw_length if selected["category_key"] == "TUBE" else None
    item["weight_quantity"] = weight
    item["base_warehouse_id"] = catalog.base_warehouse_id
    return selected


def _same_request(existing, *, snapshot):
    return existing.request_snapshot == snapshot


def _transfer_line_snapshot(line, transfer):
    selected = line.material_selection_snapshot
    return {
        "line_key": str(line.line_key),
        "material_catalog_id": str(line.material_catalog_id),
        "material_selection_snapshot": selected,
        "quantity": str(line.quantity),
        "raw_bar_length_m": str(line.raw_bar_length_m) if line.raw_bar_length_m is not None else None,
        "weight_quantity": str(line.weight_quantity) if line.weight_quantity is not None else None,
        "zone_id": str(line.zone_id),
        "direction": transfer.direction,
    }


@stock_write_transaction
def create_material_transfer(*, client_request_id, direction, transfer_date, remark, items, actor_employee, request):
    if direction not in MaterialTransferDirection.values:
        raise ValidationError({"direction": "收发方向无效。"})
    if transfer_date > timezone.localdate():
        raise ValidationError({"transfer_date": "收发日期不能晚于今天。"})
    if not str(remark or "").strip():
        raise ValidationError({"remark": "请填写收发备注。"})
    if not items or len(items) > 100:
        raise ValidationError({"items": "至少填写 1 行，最多 100 行。"})

    raw_items = [_json_value(dict(item)) for item in items]
    request_snapshot = _json_value({
        "direction": direction,
        "transfer_date": transfer_date,
        "remark": str(remark).strip(),
        "items": raw_items,
    })
    # 与手工入库复用请求锁；先锁再查，重试不能在目录锁等待后再次创建单据。
    lock_manual_request(client_request_id)
    existing = MaterialTransfer.objects.filter(client_request_id=client_request_id).first()
    if existing:
        if not _same_request(existing, snapshot=request_snapshot):
            raise Conflict("同一提交标识不能用于不同的材料收发内容。")
        return existing

    versions = {}
    prepared = [dict(item) for item in items]
    # 表格行序由用户决定，目录锁统一排序，避免两个批次反向选料时互相等待。
    catalog_ids = {item["material_catalog_id"] for item in prepared}
    list(MaterialCatalog.objects.select_for_update().filter(pk__in=catalog_ids).order_by("id"))
    for item in prepared:
        _resolve_catalog(item, request=request, versions=versions, direction=direction)

    zone_ids = sorted({item["zone_id"] for item in prepared}, key=str)
    lock_public_stock_locations(zone_ids)
    zones = list(WarehouseZone.objects.select_for_update().select_related("warehouse").filter(pk__in=zone_ids).order_by("id"))
    if len(zones) != len(zone_ids):
        raise ValidationError({"items": "部分库区不存在，请刷新后重新选择。"})
    zones_by_id = {zone.pk: zone for zone in zones}
    for item in prepared:
        zone = zones_by_id[item["zone_id"]]
        if zone.status != RecordStatus.ACTIVE or zone.warehouse.status != RecordStatus.ACTIVE:
            raise Conflict("所选仓库或库区已停用，请刷新后重新选择。")
        if zone.warehouse.warehouse_type != WarehouseType.MATERIAL:
            raise Conflict("材料收发只能使用材料仓库区。")
        if item["base_warehouse_id"] and zone.warehouse_id != item["base_warehouse_id"]:
            raise Conflict("所选库区不属于该品名配置的默认材料仓，请刷新后重新选择。")

    transfer = MaterialTransfer.objects.create(
        transfer_number=next_business_number("MATERIAL_TRANSFER", business_date=transfer_date),
        client_request_id=client_request_id,
        request_snapshot=request_snapshot,
        direction=direction,
        transfer_date=transfer_date,
        remark=str(remark).strip(),
        operated_by_employee=actor_employee,
    )

    created = []
    for item in prepared:
        line = MaterialTransferLine.objects.create(
            transfer=transfer,
            material_catalog_id=item["material_catalog_id"],
            material_selection_snapshot=item["material_selection_snapshot"],
            zone=zones_by_id[item["zone_id"]],
            quantity=item["quantity"],
            raw_bar_length_m=item.get("raw_bar_length_m"),
            weight_quantity=item.get("weight_quantity"),
        )
        created.append(line)

    for line in created:
        selected = line.material_selection_snapshot
        identity = build_catalog_stock_identity(
            material_catalog_id=line.material_catalog_id,
            material_selection_snapshot=selected,
            raw_bar_length_m=line.raw_bar_length_m,
        )
        snapshot = {
            "transfer_number": transfer.transfer_number,
            "transfer_date": str(transfer.transfer_date),
            "remark": transfer.remark,
            "material_catalog_id": str(line.material_catalog_id),
            "material_selection_snapshot": selected,
            "warehouse": line.zone.warehouse.warehouse_name,
            "zone": line.zone.zone_name,
            "weight_quantity": str(line.weight_quantity) if line.weight_quantity is not None else None,
        }
        if direction == MaterialTransferDirection.IN:
            credit_public_stock(
                identity=identity, zone=line.zone, quantity=line.quantity,
                source_type="MATERIAL_TRANSFER", source_id=transfer.pk, source_line_id=line.line_key,
                actor_employee=actor_employee, snapshot=snapshot,
                weight_quantity=line.weight_quantity,
            )
        else:
            balance = PublicStockBalance.objects.filter(
                stock_kind=identity["stock_kind"], identity_key=identity["identity_key"],
                unit_id=identity["unit_id"], zone=line.zone, quality=MaterialStockQuality.AVAILABLE,
            ).first()
            if balance is None:
                raise ValidationError({"items": "所选材料在该库区没有可用库存。"})
            movement = debit_public_stock(
                balance_id=balance.pk, quantity=line.quantity,
                source_type="MATERIAL_TRANSFER", source_id=transfer.pk, source_line_id=line.line_key,
                actor_employee=actor_employee, snapshot=snapshot,
            )
            line.weight_quantity = movement.weight_quantity
            line.save(update_fields=["weight_quantity", "updated_at"])

    write_audit_log(
        object_type="MATERIAL_TRANSFER",
        object_id=transfer.pk,
        action="GENERAL_TRANSFER_CONFIRMED",
        actor_employee=actor_employee,
        after_data={
            "transfer_number": transfer.transfer_number,
            "direction": transfer.direction,
            "transfer_date": str(transfer.transfer_date),
            "line_count": len(created),
            "remark": transfer.remark,
        },
        request=request,
    )
    return transfer


def serialize_material_transfer(transfer):
    return {
        "id": str(transfer.pk),
        "transfer_number": transfer.transfer_number,
        "direction": transfer.direction,
        "direction_display": MaterialTransferDirection(transfer.direction).label,
        "transfer_date": str(transfer.transfer_date),
        "remark": transfer.remark,
        "operated_by_name": transfer.operated_by_employee.display_name,
        "created_at": transfer.created_at,
        "lines": [
            {
                **_transfer_line_snapshot(line, transfer),
                "catalog_name": line.material_selection_snapshot.get("name", ""),
                "unit_name": line.material_selection_snapshot.get("unit_name", ""),
                "zone_name": line.zone.zone_name,
                "warehouse_name": line.zone.warehouse.warehouse_name,
            }
            for line in transfer.lines.select_related("zone__warehouse").all()
        ],
    }
