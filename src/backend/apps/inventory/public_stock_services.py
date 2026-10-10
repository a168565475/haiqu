"""公共管材和半成品余额底层服务；本阶段不接入既有业务入口。"""

import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, connection, transaction
from django.db.models import Sum

from apps.boms.models import BomLine
from apps.organizations.models import Employee
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.products.models import RawMaterialInformation
from apps.reference_data.models import ProductionUnit

from .models import (
    MaterialStockDirection,
    MaterialStockQuality,
    PublicStockBalance,
    PublicStockMovement,
    RecordStatus,
    Warehouse,
    WarehouseType,
    WarehouseZone,
)
from .public_stock_identity import validate_public_identity
from .stock_services import InventoryStockValidationError


MAX_QUANTITY = Decimal("99999999999999.9999")
MAX_METERS = Decimal("99999999999999999999.99")
MAX_RAW_BAR_LENGTH = Decimal("9999999999999999.99")


def _invalid(message, code):
    raise InventoryStockValidationError(message, code=code)


def _quantity(value):
    if isinstance(value, (bool, float)):
        _invalid("数量必须使用整数或精确十进制数。", "QUANTITY_INVALID")
    try:
        quantity = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        _invalid("数量格式无效。", "QUANTITY_INVALID")
    if not quantity.is_finite() or quantity <= 0:
        _invalid("数量必须是大于 0 的有限数字。", "QUANTITY_INVALID")
    if quantity > MAX_QUANTITY or quantity.as_tuple().exponent < -4:
        _invalid("数量超出范围或超过 4 位小数。", "QUANTITY_INVALID")
    return quantity


def _uuid(value, field, *, optional=False):
    value = getattr(value, "pk", value)
    if value is None and optional:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        _invalid(f"{field}必须是有效且已保存的记录。", "SOURCE_INVALID")


def _database_identity(identity):
    identity = validate_public_identity(identity)
    # 冻结快照和哈希保留 JSON 字符串；仅数据库外围外键转为 UUID，避免重放误判。
    identity["unit_id"] = _uuid(identity["unit_id"], "库存单位")
    identity["raw_material_id"] = _uuid(identity["raw_material_id"], "管材原料", optional=True)
    if identity["stock_kind"] == "RAW_PIPE" and identity["raw_bar_length_m"] > MAX_RAW_BAR_LENGTH:
        _invalid("原料长度超出可保存范围，最多为 16 位整数和 2 位小数。", "PIPE_LENGTH_INVALID")
    return identity


def _validate_pipe_material(*, raw_material_id, unit_id):
    material = RawMaterialInformation.objects.select_for_update(of=("self",), no_key=True).select_related("category").filter(pk=raw_material_id).order_by("id").first()
    if (material is None or material.archived_at is not None or material.item_type != "MATERIAL"
            or material.category.category_name != "管材" or material.category.item_type != "MATERIAL"
            or material.category.status != "ACTIVE" or material.category.archived_at is not None):
        _invalid("管材原料不存在、已归档或所属类别不可用。", "MATERIAL_UNAVAILABLE")
    if material.unit_id != unit_id:
        _invalid("管材原料的现有单位与冻结库存单位不一致。", "UNIT_MISMATCH")


def _source(*, source_type, source_id, source_line_id, actor_employee,
            production_task, product_line, bom_line, snapshot):
    if not isinstance(source_type, str) or not source_type.strip() or len(source_type.strip()) > 50:
        _invalid("来源类型不能为空，且不能超过 50 个字符。", "SOURCE_INVALID")
    if snapshot is None:
        snapshot = {}
    if not isinstance(snapshot, dict):
        _invalid("记账快照必须是对象。", "SNAPSHOT_INVALID")
    try:
        snapshot = json.loads(json.dumps(snapshot, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, OverflowError):
        _invalid("记账快照包含不可保存的值。", "SNAPSHOT_INVALID")
    return {
        "source_type": source_type.strip(),
        "source_id": _uuid(source_id, "来源单据"),
        "source_line_id": _uuid(source_line_id, "来源明细"),
        "actor_employee_id": _uuid(actor_employee, "操作员工"),
        "production_task_id": _uuid(production_task, "生产订单", optional=True),
        "product_line_id": _uuid(product_line, "订单产品", optional=True),
        "bom_line_id": _uuid(bom_line, "BOM 明细", optional=True),
        "snapshot": snapshot,
    }


def _lock_source(source, direction):
    # 事件锁先于余额锁：同一事件即使传入不同物料/库区，也不能各自成功记账。
    # 此工程使用 PostgreSQL；明确拒绝缺少事务锁保障的其他数据库。
    if connection.vendor != "postgresql":
        _invalid("公共库存记账需要 PostgreSQL 事务锁。", "DATABASE_UNSUPPORTED")
    token = f"public-stock:{source['source_type']}:{source['source_line_id']}:{direction}"
    lock_id = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])


def _validate_source_context(source):
    if not Employee.objects.filter(pk=source["actor_employee_id"]).exists():
        _invalid("操作员工不存在。", "SOURCE_INVALID")
    task_id = source["production_task_id"]
    product_id = source["product_line_id"]
    # 流水 INSERT 会对来源外键取 KEY SHARE。先按领料相同顺序锁父对象，
    # 避免入库持余额等订单、领料持订单等余额形成反序等待。
    if task_id is not None:
        task = ProductionTask.objects.select_for_update(of=("self",), no_key=True).filter(pk=task_id).order_by("id").first()
        if task is None:
            _invalid("来源生产订单不存在。", "SOURCE_INVALID")
    if product_id is not None:
        product = ProductionTaskProduct.objects.select_for_update(of=("self",), no_key=True).filter(pk=product_id).order_by("id").values("id", "production_task_id").first()
        if product is None or (task_id is not None and product["production_task_id"] != task_id):
            _invalid("来源订单产品与生产订单不一致。", "SOURCE_INVALID")
    if source["bom_line_id"] is not None:
        line = BomLine.objects.select_for_update(of=("self",), no_key=True).filter(pk=source["bom_line_id"]).order_by("id").values(
            "id", "section__bom__production_task_id", "section__bom__product_line_id",
        ).first()
        if (line is None
                or (task_id is not None and line["section__bom__production_task_id"] != task_id)
                or (product_id is not None and line["section__bom__product_line_id"] != product_id)):
            _invalid("来源 BOM 明细与订单不一致。", "SOURCE_INVALID")


def _existing_event(source, direction):
    return PublicStockMovement.objects.select_related("balance").filter(
        source_type=source["source_type"], source_line_id=source["source_line_id"], direction=direction,
    ).first()


def _check_replay(movement, *, source, quantity, balance_id=None, identity=None, zone_id=None, quality=None):
    same_source = all(
        getattr(movement, name) == source[name]
        for name in ("source_id", "production_task_id", "product_line_id", "bom_line_id", "snapshot")
    )
    same_balance = balance_id is None or movement.balance_id == balance_id
    if identity is not None:
        same_balance = same_balance and all((
            movement.balance.stock_kind == identity["stock_kind"],
            movement.balance.identity_key == identity["identity_key"],
            movement.balance.identity_snapshot == identity["identity_snapshot"],
            movement.balance.unit_id == identity["unit_id"],
            movement.balance.zone_id == zone_id,
            movement.balance.quality == quality,
        ))
    if movement.quantity != quantity or not same_source or not same_balance:
        _invalid("相同来源已使用不同数量、库存身份或来源单据记账。", "IDEMPOTENCY_CONFLICT")
    return movement


def lock_public_stock_locations(zone_ids):
    """按仓库、库区的固定父子顺序锁定，阻止校验后被停用或移仓。"""
    if zone_ids is None or isinstance(zone_ids, (str, bytes)):
        _invalid("库区编号必须按列表提供。", "ZONE_UNAVAILABLE")
    try:
        normalized = sorted({_uuid(value, "库区") for value in zone_ids}, key=str)
    except TypeError:
        _invalid("库区编号必须按列表提供。", "ZONE_UNAVAILABLE")
    if not normalized:
        return {}
    hints = dict(WarehouseZone.objects.filter(pk__in=normalized).order_by("id").values_list("id", "warehouse_id"))
    if len(hints) != len(normalized):
        _invalid("部分库区不存在，请刷新后重新选择。", "ZONE_UNAVAILABLE")
    warehouse_ids = sorted(set(hints.values()), key=str)
    warehouses = list(Warehouse.objects.select_for_update(of=("self",), no_key=True).filter(
        pk__in=warehouse_ids).order_by("id"))
    if len(warehouses) != len(warehouse_ids):
        _invalid("库区所属仓库不存在，请先核对仓库配置。", "ZONE_UNAVAILABLE")
    zones = list(WarehouseZone.objects.select_for_update(of=("self",), no_key=True).select_related("warehouse").filter(
        pk__in=normalized).order_by("id"))
    if len(zones) != len(normalized) or any(row.warehouse_id != hints[row.pk] for row in zones):
        _invalid("库区或所属仓库已变化，请刷新后重试。", "STOCK_LOCATION_CHANGED")
    return {row.pk: row for row in zones}


def _validate_location(*, zone_id, stock_kind, quality):
    if quality not in MaterialStockQuality.values:
        _invalid("库存品质无效。", "QUALITY_INVALID")
    zone = lock_public_stock_locations([zone_id])[zone_id]
    if zone.status != RecordStatus.ACTIVE or zone.warehouse.status != RecordStatus.ACTIVE:
        _invalid("库区或仓库不存在或已停用。", "ZONE_UNAVAILABLE")
    expected = WarehouseType.MATERIAL if stock_kind == "RAW_PIPE" else WarehouseType.SEMI_FINISHED
    if zone.warehouse.warehouse_type != expected:
        _invalid("原材料管材须存放材料仓，半成品须存放半成品仓。", "WAREHOUSE_SCOPE_INVALID")
    return zone


def _validate_unit_and_quantity(*, unit_id, stock_kind, quantity, expected_unit_name):
    unit = ProductionUnit.objects.filter(pk=unit_id, status="ACTIVE", archived_at__isnull=True).first()
    if unit is None:
        _invalid("库存单位不存在或已停用。", "UNIT_UNAVAILABLE")
    name = unit.unit_name.strip()
    if name != expected_unit_name:
        _invalid("现有单位名称与冻结库存身份不一致，不能改变原库存的计量含义。", "UNIT_MISMATCH")
    if stock_kind == "RAW_PIPE" and name != "根":
        _invalid("原料管材公共余额必须按根计量。", "UNIT_MISMATCH")
    # 本期公共管材和半成品均为离散实物，和数据库整数约束保持一致。
    if quantity != quantity.to_integral_value():
        _invalid("公共库存按根、支、套等实物数量计量，必须为整数。", "WHOLE_QUANTITY_REQUIRED")


def _balance_lookup(identity, zone_id, quality):
    return {
        "stock_kind": identity["stock_kind"], "identity_key": identity["identity_key"],
        "unit_id": identity["unit_id"], "zone_id": zone_id, "quality": quality,
    }


def _locked_balance(identity, zone_id, quality):
    lookup = _balance_lookup(identity, zone_id, quality)
    balance = PublicStockBalance.objects.select_for_update(of=("self",)).filter(**lookup).order_by("id").first()
    if balance is None:
        try:
            # 唯一约束竞争只回滚这个保存点，外层记账事务仍可继续取锁。
            with transaction.atomic():
                balance = PublicStockBalance.objects.create(
                    **lookup, identity_snapshot=identity["identity_snapshot"],
                    raw_material_id=identity["raw_material_id"], raw_bar_length_m=identity["raw_bar_length_m"],
                    quantity=0, meter_quantity=Decimal("0.00") if identity["stock_kind"] == "RAW_PIPE" else None,
                    version=1,
                )
        except IntegrityError:
            balance = PublicStockBalance.objects.select_for_update(of=("self",)).order_by("id").get(**lookup)
    if any((
        balance.identity_snapshot != identity["identity_snapshot"],
        balance.raw_material_id != identity["raw_material_id"],
        balance.raw_bar_length_m != identity["raw_bar_length_m"],
    )):
        _invalid("公共库存身份与已保存的快照不一致。", "IDENTITY_CONFLICT")
    return balance


def _record(*, balance, quantity, direction, source):
    before = balance.quantity
    after = before + quantity if direction == MaterialStockDirection.IN else before - quantity
    if after < 0:
        _invalid("公共库存不足，本次未扣减。", "STOCK_INSUFFICIENT")
    if after > MAX_QUANTITY:
        _invalid("公共库存余额超出数量范围。", "QUANTITY_OVERFLOW")
    before_meters = balance.meter_quantity
    movement_meters = None
    after_meters = None
    if balance.stock_kind == "RAW_PIPE":
        if before_meters != before * balance.raw_bar_length_m:
            _invalid("管材根数和米数不一致，不能继续记账。", "PIPE_BALANCE_INVALID")
        movement_meters = quantity * balance.raw_bar_length_m
        after_meters = after * balance.raw_bar_length_m
        if after_meters > MAX_METERS:
            _invalid("管材米数超出余额范围。", "QUANTITY_OVERFLOW")
    balance.quantity = after
    balance.meter_quantity = after_meters
    balance.version += 1
    balance.save(update_fields=["quantity", "meter_quantity", "version", "updated_at"])
    return PublicStockMovement.objects.create(
        balance=balance, direction=direction, quantity=quantity,
        before_quantity=before, after_quantity=after,
        meter_quantity=movement_meters, before_meter_quantity=before_meters, after_meter_quantity=after_meters,
        **source,
    )


@transaction.atomic
def credit_public_stock(*, identity, zone, quantity, source_type, source_id, source_line_id,
                        actor_employee, quality=MaterialStockQuality.AVAILABLE, production_task=None,
                        product_line=None, bom_line=None, snapshot=None):
    from .public_stock_cutover import require_business_stock_write
    require_business_stock_write(source_type=source_type, direction="IN")
    identity = _database_identity(identity)
    quantity = _quantity(quantity)
    zone_id = _uuid(zone, "库区")
    source = _source(source_type=source_type, source_id=source_id, source_line_id=source_line_id,
                     actor_employee=actor_employee, production_task=production_task,
                     product_line=product_line, bom_line=bom_line, snapshot=snapshot)
    _lock_source(source, MaterialStockDirection.IN)
    existing = _existing_event(source, MaterialStockDirection.IN)
    if existing:
        return _check_replay(existing, source=source, quantity=quantity, identity=identity,
                             zone_id=zone_id, quality=quality)
    _validate_source_context(source)
    from .internal_receipt_limits import validate_combined_output
    validate_combined_output(source=source, identity=identity, quantity=quantity, quality=quality)
    if identity["stock_kind"] == "RAW_PIPE":
        _validate_pipe_material(raw_material_id=identity["raw_material_id"], unit_id=identity["unit_id"])
    _validate_location(zone_id=zone_id, stock_kind=identity["stock_kind"], quality=quality)
    _validate_unit_and_quantity(unit_id=identity["unit_id"], stock_kind=identity["stock_kind"], quantity=quantity,
                                expected_unit_name=identity["identity_snapshot"]["unit_name"])
    balance = _locked_balance(identity, zone_id, quality)
    return _record(balance=balance, quantity=quantity, direction=MaterialStockDirection.IN, source=source)


@transaction.atomic
def debit_public_stock(*, balance_id, quantity, source_type, source_id, source_line_id,
                       actor_employee, production_task=None, product_line=None, bom_line=None, snapshot=None):
    from .public_stock_cutover import require_business_stock_write
    require_business_stock_write(source_type=source_type, direction="OUT")
    balance_id = _uuid(balance_id, "公共库存")
    quantity = _quantity(quantity)
    source = _source(source_type=source_type, source_id=source_id, source_line_id=source_line_id,
                     actor_employee=actor_employee, production_task=production_task,
                     product_line=product_line, bom_line=bom_line, snapshot=snapshot)
    _lock_source(source, MaterialStockDirection.OUT)
    existing = _existing_event(source, MaterialStockDirection.OUT)
    if existing:
        return _check_replay(existing, source=source, quantity=quantity, balance_id=balance_id)
    _validate_source_context(source)
    hint = PublicStockBalance.objects.filter(pk=balance_id).values("zone_id", "stock_kind", "quality", "raw_material_id", "unit_id").first()
    if hint is None:
        _invalid("公共库存记录不存在。", "STOCK_NOT_FOUND")
    if hint["stock_kind"] == "RAW_PIPE":
        _validate_pipe_material(raw_material_id=hint["raw_material_id"], unit_id=hint["unit_id"])
    _validate_location(zone_id=hint["zone_id"], stock_kind=hint["stock_kind"], quality=hint["quality"])
    balance = PublicStockBalance.objects.select_for_update(of=("self",)).filter(pk=balance_id).order_by("id").first()
    if balance is None:
        _invalid("公共库存记录不存在。", "STOCK_NOT_FOUND")
    if any(getattr(balance, name) != value for name, value in hint.items()):
        _invalid("公共库存所在库区或实物身份已变化，请刷新后重试。", "STOCK_LOCATION_CHANGED")
    if balance.quality != MaterialStockQuality.AVAILABLE:
        _invalid("只有合格库存可以领用。", "QUALITY_UNAVAILABLE")
    _validate_unit_and_quantity(unit_id=balance.unit_id, stock_kind=balance.stock_kind, quantity=quantity,
                                expected_unit_name=balance.identity_snapshot["unit_name"])
    from .tube_outsourcing_reservations import reserved_quantity_for_balance
    reserved = reserved_quantity_for_balance(balance)
    if reserved and quantity > max(balance.quantity - reserved, Decimal(0)):
        _invalid("本库区库存已被待发管材外发单预留，不能占用已预留数量。", "TUBE_OUTSOURCING_STOCK_RESERVED")
    return _record(balance=balance, quantity=quantity, direction=MaterialStockDirection.OUT, source=source)


def available_public_stock(*, identity, zone_id=None, quality=MaterialStockQuality.AVAILABLE):
    """仅返回新公共余额；不会拼接或再累加旧批次/订单余额。"""
    identity = _database_identity(identity)
    if quality not in MaterialStockQuality.values:
        _invalid("库存品质无效。", "QUALITY_INVALID")
    filters = {
        "stock_kind": identity["stock_kind"], "identity_key": identity["identity_key"],
        "unit_id": identity["unit_id"], "quality": quality,
        "zone__status": RecordStatus.ACTIVE, "zone__warehouse__status": RecordStatus.ACTIVE,
        "zone__warehouse__warehouse_type": (
            WarehouseType.MATERIAL if identity["stock_kind"] == "RAW_PIPE" else WarehouseType.SEMI_FINISHED
        ),
        "unit__status": "ACTIVE", "unit__archived_at__isnull": True,
        "unit__unit_name": identity["identity_snapshot"]["unit_name"],
    }
    if identity["stock_kind"] == "RAW_PIPE":
        filters.update({
            "raw_material__archived_at__isnull": True, "raw_material__item_type": "MATERIAL",
            "raw_material__unit_id": identity["unit_id"],
            "raw_material__category__category_name": "管材", "raw_material__category__item_type": "MATERIAL",
            "raw_material__category__status": "ACTIVE", "raw_material__category__archived_at__isnull": True,
        })
    if zone_id is not None:
        filters["zone_id"] = _uuid(zone_id, "库区")
    return PublicStockBalance.objects.filter(**filters).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
