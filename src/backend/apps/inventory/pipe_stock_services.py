"""管材批次库存基础；所有数量和额度变化必须处于一个事务。"""

from decimal import Decimal
import hashlib
import json
from uuid import UUID

from django.db import transaction

from apps.boms.material_flow_calculations import MaterialFlowValueError, decimal_quantity, pipe_issue, positive_integer
from apps.boms.models import BomLine
from apps.material_issues.models import OrderMaterialRequirement
from apps.material_issues.pipe_requirements import pipe_error, sync_pipe_requirement
from apps.products.models import RawMaterialInformation
from apps.production_tasks.models import ProductionTask

from .models import MaterialInbound, MaterialInboundLine, MaterialStockBalance, MaterialStockMovement, WarehouseZone
from .stock_services import inbound_line_material


def _uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise pipe_error("MATERIAL_FLOW_VALUE_INVALID", "来源编号格式无效。") from None


def _zone(zone_id):
    zone = WarehouseZone.objects.select_for_update(of=("self",)).select_related("warehouse").get(pk=zone_id)
    if zone.status != "ACTIVE" or zone.warehouse.status != "ACTIVE" or zone.warehouse.warehouse_type != "MATERIAL":
        raise pipe_error("WAREHOUSE_SCOPE_INVALID", "管材原料必须存放在有效材料仓库区。")
    return zone


@transaction.atomic
def credit_pipe_inbound(*, inbound_line_id, actor_employee):
    from .public_stock_mode import require_document_stock_mode
    from .public_stock_cutover import require_business_stock_write
    require_business_stock_write()
    hint = MaterialInboundLine.objects.select_related("inbound", "purchase_order_line__purchase_order", "purchase_order_line__bom_line", "raw_material_information").get(pk=inbound_line_id)
    if hint.inbound.stock_mode == "PUBLIC_V2" and hint.purchase_order_line_id:
        task_id = hint.purchase_order_line.purchase_order.production_task_id
        if task_id:
            # 来源父行必须先于原料和库区，和领料的锁顺序保持一致。
            ProductionTask.objects.select_for_update(of=("self",)).get(pk=task_id)
    inbound = MaterialInbound.objects.select_for_update().get(pk=hint.inbound_id)
    public_mode = inbound.stock_mode == "PUBLIC_V2"
    material = inbound_line_material(hint)
    if material is None:
        raise pipe_error("MATERIAL_IDENTITY_UNRESOLVED", "入库没有有效原料来源。")
    material = RawMaterialInformation.objects.select_for_update(of=('self',)).select_related("unit", "category").get(pk=material.pk)
    line = MaterialInboundLine.objects.select_for_update(of=("self",)).select_related("purchase_order_line__bom_line", "raw_material_information").get(pk=inbound_line_id)
    verified_material = inbound_line_material(line)
    if (verified_material is None or verified_material.pk != material.pk or line.inbound_id != inbound.pk
            or material.archived_at is not None or material.item_type != "MATERIAL" or material.unit.unit_name != "根"
            or material.category.category_name != "管材"):
        raise pipe_error("MATERIAL_IDENTITY_UNRESOLVED", "入库原料身份已变化或不是以根计量的管材。")
    if inbound.status != "CONFIRMED" or line.measurement_kind != "PIPE" or not line.raw_material_information_id:
        raise pipe_error("PIPE_INBOUND_NOT_READY", "仅已质检确认的新口径管材入库可以记账。")
    try:
        length = decimal_quantity(line.raw_bar_length_m, "raw_bar_length_m", places=2)
        bars = positive_integer(line.accepted_bar_count, "accepted_bar_count")
        received = positive_integer(line.received_bar_count, "received_bar_count")
        returned = positive_integer(line.return_bar_count, "return_bar_count", allow_zero=True)
    except MaterialFlowValueError as error:
        raise pipe_error(error.code, str(error)) from error
    if (received != bars + returned or line.received_quantity != received * length
            or line.return_quantity != returned * length or line.accepted_quantity != bars * length
            or line.source_unit_text_snapshot != "米"):
        raise pipe_error("PIPE_LENGTH_MISMATCH", "入库的根数、单根长度和米数不一致。")
    if public_mode:
        from .public_stock_services import lock_public_stock_locations
        zone = lock_public_stock_locations([line.zone_id])[line.zone_id]
        if zone.status != "ACTIVE" or zone.warehouse.status != "ACTIVE" or zone.warehouse.warehouse_type != "MATERIAL":
            raise pipe_error("WAREHOUSE_SCOPE_INVALID", "管材原料必须存放在有效材料仓库区。")
    else:
        zone = _zone(line.zone_id)
    if public_mode:
        from .models import PublicStockMovement
        from .public_stock_identity import build_pipe_stock_identity, validate_public_identity
        from .public_stock_services import credit_public_stock
        frozen = (line.calculation_snapshot or {}).get("public_stock_identity")
        if not frozen:
            raise pipe_error("PUBLIC_STOCK_IDENTITY_INCOMPLETE", "入库缺少已冻结公共库存身份，请先完成接续核验。")
        identity = validate_public_identity(frozen)
        expected = build_pipe_stock_identity(raw_material=material, raw_bar_length_m=length, unit=material.unit)
        if identity != expected:
            raise pipe_error("PIPE_LENGTH_MISMATCH", "冻结原料身份、单位或原材料长度与入库明细不一致。")
        if MaterialStockMovement.objects.filter(source_type="MATERIAL_INBOUND", source_line_id=line.pk, direction="IN").exists():
            raise pipe_error("IDEMPOTENCY_CONFLICT", "该入库已记入旧库存账，不能重复记入公共库存。")
        if not PublicStockMovement.objects.filter(source_type="MATERIAL_INBOUND", source_line_id=line.pk, direction="IN").exists():
            require_document_stock_mode(inbound)
        task = line.purchase_order_line.purchase_order.production_task if line.purchase_order_line_id else None
        return credit_public_stock(identity=identity, zone=zone, quantity=bars,
            source_type="MATERIAL_INBOUND", source_id=inbound.pk, source_line_id=line.pk,
            actor_employee=actor_employee, production_task=task,
            snapshot={"schema_version": 2, "public_stock_identity": frozen,
                      "inbound_number": inbound.inbound_number, "inbound_line_id": str(line.pk),
                      "raw_material_id": str(material.pk), "raw_bar_length_m": str(length),
                      "accepted_bar_count": bars, "accepted_meters": str(bars * length), "zone_id": str(zone.pk)})
    balance = MaterialStockBalance.objects.select_for_update().filter(measurement_kind="PIPE", inbound_line=line, zone=zone, quality="AVAILABLE").first()
    source = {"source_type": "MATERIAL_INBOUND", "source_line_id": line.pk, "direction": "IN"}
    existing = MaterialStockMovement.objects.filter(**source).first()
    snapshot = {"schema_version": 2, "raw_bar_length_m": str(length), "accepted_bar_count": bars,
                "raw_material_id": str(material.pk), "inbound_line_id": str(line.pk), "zone_id": str(zone.pk)}
    if existing:
        if not balance or existing.balance_id != balance.pk or existing.snapshot != snapshot:
            raise pipe_error("IDEMPOTENCY_CONFLICT", "同一入库来源已使用不同内容记账。")
        return existing
    require_document_stock_mode(inbound)
    if balance is None:
        balance = MaterialStockBalance.objects.create(measurement_kind="PIPE", inbound_line=line, raw_material=material,
            zone=zone, unit=material.unit, quality="AVAILABLE", raw_bar_length_m=length, quantity=0, meter_quantity=0)
    if balance.raw_bar_length_m != length or balance.raw_material_id != material.pk:
        raise pipe_error("PIPE_LENGTH_MISMATCH", "批次身份或原材料长度与已建账内容不一致。")
    before, before_meters = balance.quantity, balance.meter_quantity
    balance.quantity += bars
    balance.meter_quantity += bars * length
    balance.version += 1
    balance.save(update_fields=["quantity", "meter_quantity", "version", "updated_at"])
    return MaterialStockMovement.objects.create(balance=balance, quantity=bars, meter_quantity=bars * length,
        before_quantity=before, after_quantity=balance.quantity, before_meter_quantity=before_meters,
        after_meter_quantity=balance.meter_quantity, source_id=inbound.pk, actor_employee=actor_employee, snapshot=snapshot, **source)


@transaction.atomic
def issue_pipe_material(*, bom_line_id, allocations, source_type, source_id, source_revision_hash, actor_employee):
    """外发与厂内领料共用底座；allocations逐批次输入支数，失败整单回滚。

    source_line_id 必须是业务分配行的稳定编号，重试时保持不变。
    上层负责权限和业务单状态；此处不提供可直接调用的HTTP入口。
    """
    from .public_stock_cutover import require_business_stock_write
    require_business_stock_write()
    if source_type not in {"MATERIAL_ISSUE", "OUTSOURCING_DISPATCH"}:
        raise pipe_error("MATERIAL_FLOW_VALUE_INVALID", "不支持的管材发料来源。")
    source_id = _uuid(source_id)
    if not isinstance(allocations, list) or not allocations or len(allocations) > 1000:
        raise pipe_error("MATERIAL_FLOW_VALUE_INVALID", "请提供有效的批次分配。")
    normalized = []
    try:
        for row in allocations:
            normalized.append({"inbound_line_id": str(_uuid(row["inbound_line_id"])),
                "source_line_id": str(_uuid(row["source_line_id"])),
                "requested_pieces": positive_integer(row["requested_pieces"], "requested_pieces")})
    except (KeyError, TypeError, MaterialFlowValueError) as error:
        raise pipe_error(getattr(error, "code", "MATERIAL_FLOW_VALUE_INVALID"), "批次分配格式或支数无效。") from error
    if len({row["source_line_id"] for row in normalized}) != len(normalized) or len({row["inbound_line_id"] for row in normalized}) != len(normalized):
        raise pipe_error("DUPLICATE_ALLOCATION", "同一部位的批次或分配行重复，请合并数量。")
    normalized.sort(key=lambda row: row["inbound_line_id"])
    request_payload = {"bom_line_id": str(_uuid(bom_line_id)), "allocations": normalized,
                       "source_type": source_type, "source_id": str(source_id), "revision": source_revision_hash}
    payload_hash = hashlib.sha256(json.dumps(request_payload, sort_keys=True).encode()).hexdigest()
    hint = BomLine.objects.select_related("section__bom").get(pk=bom_line_id)
    ProductionTask.objects.select_for_update().get(pk=hint.section.bom.production_task_id)
    # 重试先检查已成功的原请求，不因后来BOM修订而把原成功结果变成失败。
    existing = list(MaterialStockMovement.objects.filter(source_type=source_type,
        source_line_id__in=[row["source_line_id"] for row in normalized], direction="OUT").order_by("source_line_id"))
    if existing:
        if len(existing) != len(normalized) or any(item.source_id != source_id or item.snapshot.get("request_payload_hash") != payload_hash for item in existing):
            raise pipe_error("IDEMPOTENCY_CONFLICT", "同一发料来源已使用不同内容记账。")
        return existing
    requirement = sync_pipe_requirement(bom_line_id)
    if source_revision_hash != requirement.source_revision_hash:
        raise pipe_error("SOURCE_REVISION_CHANGED", "BOM来源已变化，请刷新后重新提交。")
    amounts = []
    for row in normalized:
        try:
            amounts.append(pipe_issue(requested_pieces=row["requested_pieces"], pieces_per_bar=requirement.pieces_per_bar,
                                      raw_bar_length_m=requirement.raw_bar_length_m))
        except MaterialFlowValueError as error:
            raise pipe_error(error.code, str(error)) from error
    total_pieces = sum(row["requested_pieces"] for row in normalized)
    remaining = requirement.required_quantity - requirement.internal_issued_quantity - requirement.outsourcing_issued_quantity
    if total_pieces > remaining:
        raise pipe_error("ORDER_ALLOWANCE_EXCEEDED", "外发与厂内领料累计超过该部位剩余额度。")
    lines = list(MaterialInboundLine.objects.select_for_update().filter(pk__in=[row["inbound_line_id"] for row in normalized]).order_by("id"))
    if len(lines) != len(normalized):
        raise pipe_error("PIPE_BATCH_MISSING", "所选批次不存在。")
    for zone_id in sorted({line.zone_id for line in lines}, key=str):
        _zone(zone_id)
    balances = list(MaterialStockBalance.objects.select_for_update().filter(measurement_kind="PIPE", quality="AVAILABLE",
        inbound_line_id__in=[line.pk for line in lines]).order_by("id"))
    balance_map = {str(item.inbound_line_id): item for item in balances}
    line_map = {str(line.pk): line for line in lines}
    for row, amount in zip(normalized, amounts):
        balance = balance_map.get(row["inbound_line_id"])
        line = line_map[row["inbound_line_id"]]
        if balance is None or balance.quantity < amount["bar_count"]:
            raise pipe_error("STOCK_INSUFFICIENT", "所选管材批次的整根库存不足。")
        if (balance.raw_material_id != requirement.raw_material_id or balance.raw_bar_length_m != requirement.raw_bar_length_m
                or balance.zone_id != line.zone_id or line.measurement_kind != "PIPE"
                or line.raw_bar_length_m != balance.raw_bar_length_m):
            raise pipe_error("PIPE_LENGTH_MISMATCH", "所选批次与部位原料或单根长度不符。")
    movements = []
    for row, amount in zip(normalized, amounts):
        balance = balance_map[row["inbound_line_id"]]
        before, before_meters = balance.quantity, balance.meter_quantity
        meters = Decimal(amount["meters"])
        balance.quantity -= amount["bar_count"]
        balance.meter_quantity -= meters
        balance.version += 1
        balance.save(update_fields=["quantity", "meter_quantity", "version", "updated_at"])
        movements.append(MaterialStockMovement.objects.create(balance=balance, direction="OUT", quantity=amount["bar_count"],
            meter_quantity=meters, before_quantity=before, after_quantity=balance.quantity,
            before_meter_quantity=before_meters, after_meter_quantity=balance.meter_quantity,
            source_type=source_type, source_id=source_id, source_line_id=row["source_line_id"], production_task=requirement.production_task,
            actor_employee=actor_employee, snapshot={"schema_version": 2, "request_payload_hash": payload_hash,
                "requirement_id": str(requirement.pk), "component_identity": str(requirement.component_identity),
                "source_revision_hash": requirement.source_revision_hash, "requested_pieces": row["requested_pieces"],
                "pieces_per_bar": requirement.pieces_per_bar, "raw_bar_length_m": str(requirement.raw_bar_length_m),
                "inbound_line_id": row["inbound_line_id"]}))
    field = "internal_issued_quantity" if source_type == "MATERIAL_ISSUE" else "outsourcing_issued_quantity"
    setattr(requirement, field, getattr(requirement, field) + total_pieces)
    requirement.save(update_fields=[field, "updated_at"])
    return movements
