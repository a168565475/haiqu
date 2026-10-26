from collections import defaultdict
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.procurement.material_receipt_identity import (
    PurchaseMaterialIdentityError,
    get_purchase_material_id,
    resolve_purchase_material,
)
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductionUnit

from .models import (
    MaterialInboundLine,
    MaterialStockBalance,
    MaterialStockDirection,
    MaterialStockMovement,
    MaterialStockQuality,
    SemiFinishedStockBalance,
    SemiFinishedStockMovement,
    WarehouseType,
    WarehouseZone,
)


class InventoryStockValidationError(ValidationError):
    def __init__(self, detail, *, code, meta=None):
        self.api_error_code = code
        if meta is not None:
            self.error_meta = meta
        super().__init__(detail)


def _positive_quantity(value, field_name="quantity"):
    quantity = Decimal(value)
    if quantity <= 0:
        raise ValidationError({field_name: "数量必须大于 0。"})
    if quantity.as_tuple().exponent < -4:
        raise ValidationError({field_name: "数量最多保留 4 位小数。"})
    return quantity


def inbound_line_material(line: MaterialInboundLine):
    if line.raw_material_information_id:
        material = line.raw_material_information
        if material.archived_at is None:
            return material
        return None
    purchase_line = getattr(line, "purchase_order_line", None)
    if purchase_line is None:
        return None
    try:
        saved_id = get_purchase_material_id(purchase_line)
        frozen_ids = list(MaterialInboundLine.objects.filter(
            purchase_order_line_id=purchase_line.pk, raw_material_information__isnull=False,
        ).order_by("raw_material_information_id").values_list("raw_material_information_id", flat=True).distinct()[:2])
        if len(frozen_ids) > 1:
            return None
        if frozen_ids:
            if saved_id and saved_id != frozen_ids[0]:
                return None
            if saved_id is None:
                return RawMaterialInformation.objects.select_related("unit").filter(
                    pk=frozen_ids[0], archived_at__isnull=True, item_type="MATERIAL",
                ).first()
        return resolve_purchase_material(purchase_line)
    except PurchaseMaterialIdentityError:
        return None


def validate_inbound_stock_identity(line: MaterialInboundLine):
    if line.measurement_kind == "PIPE":
        raise InventoryStockValidationError("管材根米入库必须使用管材批次服务。", code="PIPE_SERVICE_REQUIRED")
    material = inbound_line_material(line)
    if material is None:
        raise InventoryStockValidationError(
            "入库行没有可验证的稳定原料 ID，不能记入可用库存。",
            code="MATERIAL_IDENTITY_UNRESOLVED",
        )
    source_unit = (line.source_unit_text_snapshot or "").strip()
    valid_units = {material.unit.unit_name.strip(), material.unit.unit_code.strip()}
    if source_unit not in valid_units:
        raise InventoryStockValidationError(
            f"入库单位“{source_unit or '空'}”与原料库存单位“{material.unit.unit_name}”不一致。",
            code="UNIT_MISMATCH",
        )
    if line.zone.warehouse.warehouse_type not in {WarehouseType.MATERIAL, WarehouseType.SEMI_FINISHED}:
        raise InventoryStockValidationError(
            "只有材料仓或半成品仓可以记入合格材料库存。",
            code="WAREHOUSE_SCOPE_INVALID",
        )
    return material, material.unit, line.zone


def _locked_balance(*, raw_material, unit, zone, quality=MaterialStockQuality.AVAILABLE):
    # 先锁稳定父对象，避免两个事务同时为不存在的余额行建账。
    RawMaterialInformation.objects.select_for_update().get(pk=raw_material.pk)
    WarehouseZone.objects.select_for_update().get(pk=zone.pk)
    try:
        balance, _ = MaterialStockBalance.objects.get_or_create(
            measurement_kind="OTHER",
            raw_material=raw_material,
            unit=unit,
            zone=zone,
            quality=quality,
            defaults={"quantity": Decimal("0"), "version": 1},
        )
    except IntegrityError:
        balance = MaterialStockBalance.objects.get(
            measurement_kind="OTHER",
            raw_material=raw_material,
            unit=unit,
            zone=zone,
            quality=quality,
        )
    return MaterialStockBalance.objects.select_for_update().get(pk=balance.pk)


@transaction.atomic
def credit_material_stock(
    *, raw_material, unit, zone, quantity, source_type, source_id, source_line_id,
    actor_employee, production_task=None, snapshot=None,
):
    from .public_stock_cutover import require_business_stock_write
    require_business_stock_write(source_type=source_type, direction="IN")
    quantity = _positive_quantity(quantity)
    existing = MaterialStockMovement.objects.filter(
        source_type=source_type,
        source_line_id=source_line_id,
        direction=MaterialStockDirection.IN,
    ).select_related("balance").first()
    if existing:
        if existing.quantity != quantity or existing.balance.raw_material_id != raw_material.pk:
            raise InventoryStockValidationError("相同入库来源已使用不同内容记账。", code="IDEMPOTENCY_CONFLICT")
        return existing

    balance = _locked_balance(raw_material=raw_material, unit=unit, zone=zone)
    before = balance.quantity
    balance.quantity = before + quantity
    balance.version += 1
    balance.save(update_fields=["quantity", "version", "updated_at"])
    return MaterialStockMovement.objects.create(
        balance=balance,
        direction=MaterialStockDirection.IN,
        quantity=quantity,
        before_quantity=before,
        after_quantity=balance.quantity,
        source_type=source_type,
        source_id=source_id,
        source_line_id=source_line_id,
        production_task=production_task,
        actor_employee=actor_employee,
        snapshot=snapshot or {},
    )


def credit_confirmed_inbound_line(*, line, actor_employee):
    from .public_stock_mode import require_document_stock_mode
    if line.measurement_kind == 'PIPE':
        from .pipe_stock_services import credit_pipe_inbound
        return credit_pipe_inbound(inbound_line_id=line.pk, actor_employee=actor_employee)
    if not MaterialStockMovement.objects.filter(source_type="MATERIAL_INBOUND", source_line_id=line.pk, direction="IN").exists():
        require_document_stock_mode(line.inbound)
    material, unit, zone = validate_inbound_stock_identity(line)
    production_task = None
    if line.purchase_order_line_id:
        production_task = line.purchase_order_line.purchase_order.production_task
    return credit_material_stock(
        raw_material=material,
        unit=unit,
        zone=zone,
        quantity=line.accepted_quantity,
        source_type="MATERIAL_INBOUND",
        source_id=line.inbound_id,
        source_line_id=line.pk,
        actor_employee=actor_employee,
        production_task=production_task,
        snapshot={
            "inbound_number": line.inbound.inbound_number,
            "material_number": material.material_number,
            "material_name": material.material_name,
            "unit": unit.unit_name,
            "zone": zone.zone_name,
        },
    )


def available_stock(raw_material_id, unit_id):
    return sum(
        (
            item.quantity
            for item in MaterialStockBalance.objects.filter(
                measurement_kind="OTHER",
                raw_material_id=raw_material_id,
                unit_id=unit_id,
                quality=MaterialStockQuality.AVAILABLE,
            )
        ),
        Decimal("0"),
    )


def inbound_batch_available_quantities(inbound_lines, *, lock_balances=False):
    """按库存流水重放批次余量；普通出库按先进先出，指定委外批次按实际来源扣减。"""
    grouped_lines = defaultdict(list)
    result = {}
    for line in inbound_lines:
        if line.measurement_kind == "PIPE":
            # 新批次直接读余额，不能把该批次根数混入旧口径的米数/FIFO回放。
            query = MaterialStockBalance.objects.filter(measurement_kind="PIPE", inbound_line=line,
                zone_id=line.zone_id, quality=MaterialStockQuality.AVAILABLE)
            if lock_balances:
                query = query.select_for_update()
            result[line.pk] = sum((row.quantity for row in query.order_by("id")), Decimal("0"))
            continue
        material = inbound_line_material(line)
        if material is None:
            result[line.pk] = Decimal("0")
            continue
        grouped_lines[(material.pk, material.unit_id, line.zone_id)].append(line)
    if not grouped_lines:
        return result

    # 延迟导入，避免 inventory 与 outsourcing 模型在应用加载阶段互相导入。
    from apps.outsourcing.models import OutsourcingDispatchLine

    stock_keys = sorted(grouped_lines, key=lambda values: tuple(str(value) for value in values))
    balance_filter = Q()
    for material_id, unit_id, zone_id in stock_keys:
        balance_filter |= Q(raw_material_id=material_id, unit_id=unit_id, zone_id=zone_id)
    balance_query = MaterialStockBalance.objects.filter(
        balance_filter,
        measurement_kind="OTHER",
        quality=MaterialStockQuality.AVAILABLE,
    ).order_by("raw_material_id", "unit_id", "zone_id", "id")
    if lock_balances:
        balance_query = balance_query.select_for_update()
    balances_by_key = defaultdict(list)
    for balance in balance_query:
        balances_by_key[(balance.raw_material_id, balance.unit_id, balance.zone_id)].append(balance)

    for material_id, unit_id, zone_id in stock_keys:
        lines = grouped_lines[(material_id, unit_id, zone_id)]
        balances = balances_by_key[(material_id, unit_id, zone_id)]
        available = {line.pk: Decimal("0") for line in lines}
        fifo_ids = [
            line.pk
            for line in sorted(
                lines,
                key=lambda item: (item.inbound.inbound_date, item.created_at, str(item.pk)),
            )
        ]
        if not balances:
            result.update(available)
            continue

        movements = list(
            MaterialStockMovement.objects.filter(balance_id__in=[item.pk for item in balances])
            .order_by("occurred_at", "created_at", "id")
        )
        dispatch_source_ids = [
            movement.source_line_id
            for movement in movements
            if movement.direction == MaterialStockDirection.OUT
            and movement.source_type == "OUTSOURCING_DISPATCH"
        ]
        dispatch_sources = {
            row.pk: row.inbound_line_id
            for row in OutsourcingDispatchLine.objects.filter(pk__in=dispatch_source_ids)
            .only("id", "inbound_line_id")
        }

        def consume_fifo(quantity):
            remaining = quantity
            for inbound_line_id in fifo_ids:
                if remaining <= 0:
                    break
                used = min(available[inbound_line_id], remaining)
                available[inbound_line_id] -= used
                remaining -= used

        for movement in movements:
            if movement.direction == MaterialStockDirection.IN:
                if movement.source_type == "MATERIAL_INBOUND" and movement.source_line_id in available:
                    available[movement.source_line_id] += movement.quantity
                elif movement.source_type == "OUTSOURCING_RAW_RETURN":
                    # 退回未用原料恢复原批次，不能只增加总余额而丢掉批次可用量。
                    source_id = str(movement.snapshot.get("inbound_line_id", ""))
                    restored_id = next((key for key in available if str(key) == source_id), None)
                    if restored_id is not None:
                        available[restored_id] += movement.quantity
                continue
            selected_inbound_line_id = dispatch_sources.get(movement.source_line_id)
            if selected_inbound_line_id in available:
                available[selected_inbound_line_id] = max(
                    Decimal("0"), available[selected_inbound_line_id] - movement.quantity
                )
            else:
                consume_fifo(movement.quantity)

        # 历史修复或未带批次的库存调整无法精确归属；只允许减少可选批次，不把无来源余额冒充为某批次。
        balance_total = sum((balance.quantity for balance in balances), Decimal("0"))
        attributed_total = sum(available.values(), Decimal("0"))
        if attributed_total > balance_total:
            consume_fifo(attributed_total - balance_total)
        result.update(available)
    return result


@transaction.atomic
def debit_material_stock(
    *, raw_material, unit, quantity, source_type, source_id, source_line_id,
    actor_employee, production_task, snapshot=None, zone=None,
):
    from .public_stock_cutover import require_business_stock_write
    require_business_stock_write(source_type=source_type, direction="OUT")
    quantity = _positive_quantity(quantity)
    existing = list(MaterialStockMovement.objects.filter(
        source_type=source_type,
        source_line_id=source_line_id,
        direction=MaterialStockDirection.OUT,
    ).select_related("balance", "balance__zone", "balance__zone__warehouse").order_by("balance_id"))
    if existing:
        if (
            sum((movement.quantity for movement in existing), Decimal("0")) != quantity
            or any(movement.balance.raw_material_id != raw_material.pk for movement in existing)
            or (zone is not None and any(movement.balance.zone_id != zone.pk for movement in existing))
        ):
            raise InventoryStockValidationError("相同出库来源已使用不同内容记账。", code="IDEMPOTENCY_CONFLICT")
        return existing[0]

    balance_query = (
        MaterialStockBalance.objects.select_for_update()
        .select_related("zone", "zone__warehouse")
        .filter(
            raw_material=raw_material,
            measurement_kind="OTHER",
            unit=unit,
            quality=MaterialStockQuality.AVAILABLE,
            quantity__gt=0,
            zone__status="ACTIVE",
            zone__warehouse__status="ACTIVE",
        )
        .order_by("zone_id", "id")
    )
    if zone is not None:
        balance_query = balance_query.filter(zone=zone)
    balances = list(balance_query)
    from .tube_outsourcing_reservations import tube_material_reserved_quantities
    _, reserved = tube_material_reserved_quantities(raw_material_ids=[raw_material.pk])
    free = {item.pk: max(item.quantity - reserved.get(
        (str(item.raw_material_id), str(item.unit_id), str(item.zone_id)), Decimal(0)), Decimal(0))
        for item in balances}
    total = sum(free.values(), Decimal("0"))
    if total < quantity:
        raise InventoryStockValidationError(
            "合格公共可用库存不足。",
            code="STOCK_INSUFFICIENT",
            meta={"retryable": True, "available_stock": str(total)},
        )
    remaining = quantity
    movements = []
    for balance in balances:
        if remaining <= 0:
            break
        allocated = min(free[balance.pk], remaining)
        if allocated <= 0:
            continue
        before = balance.quantity
        balance.quantity = before - allocated
        balance.version += 1
        balance.save(update_fields=["quantity", "version", "updated_at"])
        movement_snapshot = {
            **(snapshot or {}),
            "warehouse": balance.zone.warehouse.warehouse_name,
            "zone": balance.zone.zone_name,
            "allocation_policy": "SPECIFIED_ZONE" if zone is not None else "ZONE_ID_ASC",
        }
        movements.append(MaterialStockMovement.objects.create(
            balance=balance,
            direction=MaterialStockDirection.OUT,
            quantity=allocated,
            before_quantity=before,
            after_quantity=balance.quantity,
            source_type=source_type,
            source_id=source_id,
            source_line_id=source_line_id,
            production_task=production_task,
            actor_employee=actor_employee,
            snapshot=movement_snapshot,
        ))
        remaining -= allocated
    return movements[0]


def _locked_semi_finished_balance(
    *, production_task, product_line, bom_line, completed_craft, color_snapshot,
    unit, zone, quality,
):
    if product_line.production_task_id != production_task.pk:
        raise InventoryStockValidationError("半成品产品不属于所选生产订单。", code="SEMI_IDENTITY_INVALID")
    expected_warehouse_type = (
        WarehouseType.SEMI_FINISHED
        if quality == MaterialStockQuality.AVAILABLE
        else WarehouseType.DEFECTIVE
    )
    if zone.warehouse.warehouse_type != expected_warehouse_type:
        raise InventoryStockValidationError(
            "合格品必须进入半成品仓，不良品必须进入不良品仓。",
            code="WAREHOUSE_SCOPE_INVALID",
        )
    # 锁稳定父对象，保证相同身份首次并发建账时不会产生重复余额。
    production_task.__class__.objects.select_for_update().get(pk=production_task.pk)
    WarehouseZone.objects.select_for_update().get(pk=zone.pk)
    identity = {
        "production_task": production_task,
        "product_line": product_line,
        "bom_line": bom_line,
        "completed_craft": completed_craft,
        "color_snapshot": (color_snapshot or "").strip(),
        "unit": unit,
        "zone": zone,
        "quality": quality,
    }
    try:
        balance, _ = SemiFinishedStockBalance.objects.get_or_create(
            **identity,
            defaults={"quantity": Decimal("0"), "version": 1},
        )
    except IntegrityError:
        balance = SemiFinishedStockBalance.objects.get(**identity)
    return SemiFinishedStockBalance.objects.select_for_update().get(pk=balance.pk)


@transaction.atomic
def credit_semi_finished_stock(
    *, production_task, product_line, bom_line, completed_craft, color_snapshot,
    unit, zone, quality, quantity, source_type, source_id, source_line_id,
    actor_employee, snapshot=None,
):
    from .public_stock_cutover import require_business_stock_write
    require_business_stock_write(source_type=source_type, direction="IN")
    quantity = _positive_quantity(quantity)
    existing = SemiFinishedStockMovement.objects.filter(
        source_type=source_type,
        source_line_id=source_line_id,
        direction=MaterialStockDirection.IN,
    ).select_related("balance").first()
    if existing:
        balance = existing.balance
        if (
            existing.quantity != quantity
            or balance.production_task_id != production_task.pk
            or balance.product_line_id != product_line.pk
            or balance.bom_line_id != bom_line.pk
            or balance.completed_craft_id != completed_craft.pk
            or balance.unit_id != unit.pk
            or balance.zone_id != zone.pk
            or balance.quality != quality
            or balance.color_snapshot != (color_snapshot or "").strip()
        ):
            raise InventoryStockValidationError("相同回厂来源已使用不同内容记账。", code="IDEMPOTENCY_CONFLICT")
        return existing

    balance = _locked_semi_finished_balance(
        production_task=production_task,
        product_line=product_line,
        bom_line=bom_line,
        completed_craft=completed_craft,
        color_snapshot=color_snapshot,
        unit=unit,
        zone=zone,
        quality=quality,
    )
    before = balance.quantity
    balance.quantity = before + quantity
    balance.version += 1
    balance.save(update_fields=["quantity", "version", "updated_at"])
    return SemiFinishedStockMovement.objects.create(
        balance=balance,
        direction=MaterialStockDirection.IN,
        quantity=quantity,
        before_quantity=before,
        after_quantity=balance.quantity,
        source_type=source_type,
        source_id=source_id,
        source_line_id=source_line_id,
        actor_employee=actor_employee,
        snapshot=snapshot or {},
    )


def available_semi_finished_stock(
    *, production_task_id, product_line_id, bom_line_id, completed_craft_id,
    color_snapshot, unit_id,
):
    return sum(
        (
            item.quantity
            for item in SemiFinishedStockBalance.objects.filter(
                production_task_id=production_task_id,
                product_line_id=product_line_id,
                bom_line_id=bom_line_id,
                completed_craft_id=completed_craft_id,
                color_snapshot=(color_snapshot or "").strip(),
                unit_id=unit_id,
                quality=MaterialStockQuality.AVAILABLE,
            )
        ),
        Decimal("0"),
    )


@transaction.atomic
def debit_semi_finished_stock(
    *, balance_id, quantity, source_type, source_id, source_line_id, actor_employee, snapshot=None,
):
    from .public_stock_cutover import require_business_stock_write
    require_business_stock_write(source_type=source_type, direction="OUT")
    quantity = _positive_quantity(quantity)
    existing = SemiFinishedStockMovement.objects.filter(
        source_type=source_type,
        source_line_id=source_line_id,
        direction=MaterialStockDirection.OUT,
    ).select_related("balance").first()
    if existing:
        if existing.quantity != quantity or existing.balance_id != balance_id:
            raise InventoryStockValidationError("相同半成品出库来源已使用不同内容记账。", code="IDEMPOTENCY_CONFLICT")
        return existing
    balance = SemiFinishedStockBalance.objects.select_for_update().get(pk=balance_id)
    if balance.quality != MaterialStockQuality.AVAILABLE:
        raise InventoryStockValidationError("只有合格半成品可以领用。", code="QUALITY_NOT_AVAILABLE")
    if (
        balance.zone.status != "ACTIVE"
        or balance.zone.warehouse.status != "ACTIVE"
        or balance.zone.warehouse.warehouse_type != WarehouseType.SEMI_FINISHED
    ):
        raise InventoryStockValidationError("半成品所在库区已停用或类型不正确。", code="WAREHOUSE_SCOPE_INVALID")
    if balance.quantity < quantity:
        raise InventoryStockValidationError(
            "合格半成品库存不足。",
            code="STOCK_INSUFFICIENT",
            meta={"retryable": True, "available_stock": str(balance.quantity)},
        )
    before = balance.quantity
    balance.quantity = before - quantity
    balance.version += 1
    balance.save(update_fields=["quantity", "version", "updated_at"])
    return SemiFinishedStockMovement.objects.create(
        balance=balance,
        direction=MaterialStockDirection.OUT,
        quantity=quantity,
        before_quantity=before,
        after_quantity=balance.quantity,
        source_type=source_type,
        source_id=source_id,
        source_line_id=source_line_id,
        actor_employee=actor_employee,
        snapshot=snapshot or {},
    )
