"""公共库存只读预检，以及固定独立 PostgreSQL 上的期初预演。"""

import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from django.db import connection, transaction

from apps.audit.models import AuditLog
from apps.core.audit import write_audit_log
from apps.organizations.models import Employee
from .models import MaterialStockBalance, MaterialStockMovement, SemiFinishedStockBalance, SemiFinishedStockMovement, PublicStockMovement
from .public_stock_identity import build_pipe_stock_identity, validate_public_identity


ISOLATED_HOST = "public-stock-postgres"
ISOLATED_SYSTEM_IDENTIFIER = "7690414046275272738"
ISOLATED_DATABASES = frozenset({"public_stock_s3_base", "public_stock_s3_rehearsal", "test_public_stock_s3", "test_public_stock_s4", "test_public_stock_s5", "public_stock_s6_base", "test_public_stock_s6", "test_public_stock_s6_tooling"})
OPENING_SOURCE_TYPE = "PUBLIC_STOCK_OPENING"
OPENING_AUDIT_ID = UUID("c89fbdb9-0f54-49c4-932b-faa0b3f07214")


class PublicStockPreviewError(ValueError):
    def __init__(self, code, message, *, report=None):
        self.code = code
        self.report = report
        super().__init__(f"{code}: {message}")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _amount(value):
    return format(Decimal(value), "f")


def assert_isolated_database():
    """名称、连接主机和真实 PostgreSQL 集群标识须全部匹配；不能只改库名放行。"""
    if connection.vendor != "postgresql" or connection.settings_dict.get("HOST") != ISOLATED_HOST:
        raise PublicStockPreviewError("ISOLATED_DATABASE_REQUIRED", "只允许指定独立 PostgreSQL 主机执行期初预演。")
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), system_identifier::text FROM pg_control_system()")
        database, identifier = cursor.fetchone()
    if database not in ISOLATED_DATABASES or identifier != ISOLATED_SYSTEM_IDENTIFIER:
        raise PublicStockPreviewError("ISOLATED_DATABASE_REQUIRED", "数据库名称或实际集群标识不符合独立预演环境。")
    return {"database": database, "system_identifier": identifier, "host": ISOLATED_HOST}


def _movement_source(row):
    return {"id": str(row.pk), "source_type": row.source_type, "source_id": str(row.source_id),
            "source_line_id": str(row.source_line_id), "direction": row.direction,
            "quantity": _amount(row.quantity), "before_quantity": _amount(row.before_quantity),
            "after_quantity": _amount(row.after_quantity), "snapshot_hash": _digest(row.snapshot),
            "occurred_at": row.occurred_at.isoformat(),
            "meter_quantity": str(getattr(row, "meter_quantity", None)) if getattr(row, "meter_quantity", None) is not None else None}


def _legacy_source(row, movements, *, semi=False):
    source = {"model": "SemiFinishedStockBalance" if semi else "MaterialStockBalance", "id": str(row.pk),
              "version": row.version, "quantity": _amount(row.quantity), "unit_id": str(row.unit_id),
              "unit_name": row.unit.unit_name, "zone_id": str(row.zone_id), "quality": row.quality,
              "movements": [_movement_source(movement) for movement in movements]}
    if semi:
        source.update({"production_task_id": str(row.production_task_id), "product_line_id": str(row.product_line_id),
                       "bom_line_id": str(row.bom_line_id), "completed_craft_id": str(row.completed_craft_id),
                       "color": row.color_snapshot})
    else:
        source.update({"raw_material_id": str(row.raw_material_id), "measurement_kind": row.measurement_kind,
                       "raw_bar_length_m": str(row.raw_bar_length_m) if row.raw_bar_length_m is not None else None,
                       "meter_quantity": _amount(row.meter_quantity) if row.meter_quantity is not None else None,
                       "inbound_line_id": str(row.inbound_line_id) if row.inbound_line_id else None})
        if row.inbound_line_id:
            line = row.inbound_line
            source.update({"inbound_id": str(line.inbound_id), "inbound_number": line.inbound.inbound_number,
                           "purchase_order_line_id": str(line.purchase_order_line_id) if line.purchase_order_line_id else None})
            if line.purchase_order_line_id:
                order = line.purchase_order_line.purchase_order
                source.update({"purchase_order_id": str(order.pk), "purchase_order_number": order.order_number})
    return source


def _validate_pipe_history(row, movements):
    if not movements:
        raise PublicStockPreviewError("PIPE_HISTORY_REQUIRED", "旧管材缺少完整根数、米数流水，不能仅凭当前余额建期初。")
    line = row.inbound_line
    length = row.raw_bar_length_m
    if line is None or length is None or length <= 0:
        raise PublicStockPreviewError("PIPE_SOURCE_MISMATCH", "旧管材缺少入库来源或有效原材料长度。")
    bars, meters, inbound_count = Decimal("0"), Decimal("0"), 0
    for movement in movements:
        if (movement.direction not in {"IN", "OUT"} or movement.quantity <= 0
                or movement.quantity != movement.quantity.to_integral_value()
                or movement.before_quantity != bars or movement.before_meter_quantity != meters
                or movement.meter_quantity != movement.quantity * length):
            raise PublicStockPreviewError("PIPE_HISTORY_MISMATCH", "旧管材流水的整数根数、米数或前后数量链不一致。")
        if movement.source_type == "MATERIAL_INBOUND":
            inbound_count += 1
            frozen = movement.snapshot or {}
            if not isinstance(frozen, dict):
                raise PublicStockPreviewError("PIPE_INBOUND_HISTORY_MISMATCH", "原管材入库冻结快照不是有效对象。")
            if (movement.direction != "IN" or movement.source_id != line.inbound_id or movement.source_line_id != line.pk
                    or movement.quantity != line.accepted_bar_count or movement.meter_quantity != line.accepted_quantity
                    or frozen.get("schema_version") != 2 or frozen.get("raw_material_id") != str(row.raw_material_id)
                    or frozen.get("inbound_line_id") != str(line.pk) or frozen.get("zone_id") != str(row.zone_id)
                    or frozen.get("accepted_bar_count") != line.accepted_bar_count
                    or frozen.get("raw_bar_length_m") != str(length)):
                raise PublicStockPreviewError("PIPE_INBOUND_HISTORY_MISMATCH", "原管材入库流水与已质检根数、米数或冻结来源不一致。")
        sign = 1 if movement.direction == "IN" else -1
        bars += sign * movement.quantity
        meters += sign * movement.meter_quantity
        if (bars < 0 or meters < 0 or movement.after_quantity != bars or movement.after_meter_quantity != meters
                or meters != bars * length):
            raise PublicStockPreviewError("PIPE_HISTORY_MISMATCH", "旧管材流水的期后根数、米数不一致。")
    if inbound_count != 1 or bars != row.quantity or meters != row.meter_quantity:
        raise PublicStockPreviewError("PIPE_HISTORY_MISMATCH", "旧管材完整流水净根数、米数与当前余额不一致，或原入库流水缺失。")


def _pipe_identity(row, movements):
    if (row.quantity < 0 or row.quantity != row.quantity.to_integral_value()
            or row.raw_bar_length_m is None or row.raw_bar_length_m <= 0
            or row.meter_quantity != row.quantity * row.raw_bar_length_m):
        raise PublicStockPreviewError("PIPE_AMOUNT_MISMATCH", "旧管材根数必须为整数且米数等于根数乘原材料长度。")
    line = row.inbound_line
    if (line is None or line.measurement_kind != "PIPE" or line.inbound.status != "CONFIRMED"
            or line.raw_material_information_id != row.raw_material_id or line.raw_bar_length_m != row.raw_bar_length_m
            or line.zone_id != row.zone_id or row.raw_material.item_type != "MATERIAL"
            or row.raw_material.category.category_name != "管材" or row.unit.unit_name != "根"
            or row.raw_material.unit_id != row.unit_id):
        raise PublicStockPreviewError("PIPE_SOURCE_MISMATCH", "旧管材余额与已确认入库的稳定原料、长度、单位或库区不一致。")
    if (line.source_unit_text_snapshot != "米" or line.received_bar_count != line.accepted_bar_count + line.return_bar_count
            or line.received_quantity != line.received_bar_count * row.raw_bar_length_m
            or line.accepted_quantity != line.accepted_bar_count * row.raw_bar_length_m
            or line.return_quantity != line.return_bar_count * row.raw_bar_length_m):
        raise PublicStockPreviewError("PIPE_INBOUND_HISTORY_MISMATCH", "原管材入库质检的根数、米数和退货数量不一致。")
    _validate_pipe_history(row, movements)
    return build_pipe_stock_identity(raw_material=row.raw_material, raw_bar_length_m=row.raw_bar_length_m, unit=row.unit)


def _semi_identity(row, movements):
    # 当前 BOM 可能已改版，严禁通过当前 BOM 补齐旧回货没有冻结的属性。
    if not movements:
        raise PublicStockPreviewError("SEMI_SNAPSHOT_REQUIRED", "旧半成品没有可证明完整属性的冻结入出库流水。")
    identity = None
    running = Decimal("0")
    for movement in movements:
        movement_snapshot = movement.snapshot or {}
        frozen = movement_snapshot.get("public_stock_identity") if isinstance(movement_snapshot, dict) else None
        if not isinstance(frozen, dict):
            raise PublicStockPreviewError("SEMI_SNAPSHOT_REQUIRED", "旧半成品流水缺少完整冻结身份，不能读取当前 BOM 猜测合并。")
        candidate = validate_public_identity(frozen)
        snapshot = candidate["identity_snapshot"]
        if (candidate["stock_kind"] != "SEMI" or str(candidate["unit_id"]) != str(row.unit_id)
                or snapshot.get("unit_name") != row.unit.unit_name
                or snapshot.get("completed_craft", {}).get("id") != str(row.completed_craft_id)
                or snapshot.get("color", "").strip() != row.color_snapshot.strip()):
            raise PublicStockPreviewError("SEMI_SNAPSHOT_CONFLICT", "冻结身份与旧余额的工艺、颜色或单位不一致。")
        if identity is not None and identity["identity_key"] != candidate["identity_key"]:
            raise PublicStockPreviewError("SEMI_SNAPSHOT_CONFLICT", "同一旧半成品余额的历史流水冻结属性不同。")
        identity = candidate
        if (movement.quantity <= 0 or movement.quantity != movement.quantity.to_integral_value()
                or movement.before_quantity != running or movement.direction not in {"IN", "OUT"}):
            raise PublicStockPreviewError("SEMI_AMOUNT_MISMATCH", "旧半成品流水不是完整的整数支／套数量链。")
        running += movement.quantity if movement.direction == "IN" else -movement.quantity
        if running < 0 or movement.after_quantity != running:
            raise PublicStockPreviewError("SEMI_AMOUNT_MISMATCH", "旧半成品流水前后数量不一致。")
    if running != row.quantity:
        raise PublicStockPreviewError("SEMI_AMOUNT_MISMATCH", "旧半成品流水净数量与余额不一致。")
    return identity


def _load_plan(*, lock=False):
    material_query = MaterialStockBalance.objects.select_related("raw_material__category", "raw_material__unit", "unit", "zone__warehouse", "inbound_line__inbound", "inbound_line__purchase_order_line__purchase_order").order_by("id")
    semi_query = SemiFinishedStockBalance.objects.select_related("unit", "completed_craft", "zone__warehouse", "production_task", "product_line", "bom_line").order_by("id")
    if lock:
        # 只锁预演涉及的旧余额；保留旧库存数量与版本，不做切换。
        list(MaterialStockBalance.objects.filter(measurement_kind="PIPE").order_by("id").select_for_update().values_list("id", flat=True))
        semi_query = semi_query.select_for_update(of=("self",))
    materials, semis = list(material_query), list(semi_query)
    pipe_ids = [row.pk for row in materials if row.measurement_kind == "PIPE"]
    material_moves, semi_moves = defaultdict(list), defaultdict(list)
    for movement in MaterialStockMovement.objects.filter(balance_id__in=pipe_ids).order_by("created_at", "id"):
        material_moves[movement.balance_id].append(movement)
    for movement in SemiFinishedStockMovement.objects.filter(balance_id__in=[row.pk for row in semis]).order_by("created_at", "id"):
        semi_moves[movement.balance_id].append(movement)
    existing = {str(row.source_line_id): row for row in PublicStockMovement.objects.filter(source_type=OPENING_SOURCE_TYPE).select_related("balance")}
    report = {"schema_version": 1, "mode": "DRY_RUN", "applied": False, "ready": True,
              "availability_policy": "仅独立副本预演；现行业务继续只读旧账。新旧余额禁止相加为可用库存。",
              "groups": [], "excluded": [], "zero_balances": [], "blockers": [], "sources": []}
    groups, candidates = {}, []
    for row, semi in [(row, False) for row in materials] + [(row, True) for row in semis]:
        movements = semi_moves[row.pk] if semi else material_moves[row.pk]
        source = _legacy_source(row, movements, semi=semi)
        source_id = str(row.pk)
        report["sources"].append(source)
        opening = existing.pop(source_id, None)
        if opening and (not isinstance(opening.snapshot, dict) or opening.snapshot.get("legacy_source") != source):
            report["blockers"].append({"source_id": source_id, "code": "LEGACY_SOURCE_CHANGED", "message": "该旧来源已经预演，但版本、数量或来源信息已改变。"})
            continue
        if not semi and row.measurement_kind != "PIPE":
            reason = "LEGACY_METER_PIPE_EXCLUDED" if row.raw_material.category.category_name == "管材" else "ORDINARY_MATERIAL_UNCHANGED"
            report["excluded"].append({"source_id": source_id, "reason": reason, "quantity": source["quantity"], "unit": row.unit.unit_name})
            continue
        if row.quantity == 0:
            report["zero_balances"].append({"source_id": source_id, "stock_kind": "SEMI" if semi else "RAW_PIPE", "quantity": "0", "unit": row.unit.unit_name})
            if not semi:
                try:
                    _validate_pipe_history(row, movements)
                except PublicStockPreviewError as error:
                    report["blockers"].append({"source_id": source_id, "code": error.code, "message": str(error)})
            continue
        try:
            expected_warehouse = "SEMI_FINISHED" if semi else "MATERIAL"
            if (row.zone.status != "ACTIVE" or row.zone.warehouse.status != "ACTIVE"
                    or row.zone.warehouse.warehouse_type != expected_warehouse
                    or row.unit.status != "ACTIVE" or row.unit.archived_at is not None):
                raise PublicStockPreviewError("STOCK_CONTEXT_UNAVAILABLE", "旧余额的库区、仓库类型或单位不符合本次公共库存预演条件。")
            identity = _semi_identity(row, movements) if semi else _pipe_identity(row, movements)
            identity = validate_public_identity(identity)
            if opening and (opening.balance.identity_key != identity["identity_key"]
                            or opening.balance.identity_snapshot != identity["identity_snapshot"]
                            or str(opening.balance.unit_id) != str(row.unit_id) or opening.source_id != row.pk
                            or opening.balance.zone_id != row.zone_id or opening.balance.quality != row.quality
                            or opening.quantity != row.quantity or opening.direction != "IN"):
                raise PublicStockPreviewError("OPENING_IDENTITY_CONFLICT", "已预演流水的目标身份或数量与旧来源不一致。")
            key = (identity["stock_kind"], identity["identity_key"], str(row.zone_id), row.quality)
            group = groups.setdefault(key, {"stock_kind": identity["stock_kind"], "identity_key": identity["identity_key"],
                    "identity_snapshot": identity["identity_snapshot"], "zone_id": str(row.zone_id),
                    "warehouse": row.zone.warehouse.warehouse_name, "zone": row.zone.zone_name, "quality": row.quality,
                    "unit": row.unit.unit_name, "quantity": Decimal("0"), "meter_quantity": Decimal("0") if not semi else None, "sources": []})
            group["quantity"] += row.quantity
            if not semi:
                group["meter_quantity"] += row.meter_quantity
            group["sources"].append(source)
            candidates.append((row, identity, source, opening))
        except Exception as error:
            if not isinstance(error, (PublicStockPreviewError, ValueError)) and not hasattr(error, "detail"):
                raise
            report["blockers"].append({"source_id": source_id, "code": getattr(error, "api_error_code", getattr(error, "code", "IDENTITY_INVALID")), "message": str(error)})
    for source_id in existing:
        report["blockers"].append({"source_id": source_id, "code": "LEGACY_SOURCE_MISSING", "message": "已预演的旧来源不再存在，禁止继续叠加。"})
    for key in sorted(groups):
        group = groups[key]
        group["quantity"] = _amount(group["quantity"])
        group["meter_quantity"] = _amount(group["meter_quantity"]) if group["meter_quantity"] is not None else None
        report["groups"].append(group)
    relevant_sources = [source for source in report["sources"] if source["model"] == "SemiFinishedStockBalance" or source.get("measurement_kind") == "PIPE"]
    report["source_manifest_hash"] = _digest(relevant_sources)
    previous = AuditLog.objects.filter(object_type=OPENING_SOURCE_TYPE, object_id=OPENING_AUDIT_ID, action="ISOLATED_OPENING_APPLIED").order_by("occurred_at", "id").first()
    if previous and (not isinstance(previous.after_data, dict) or previous.after_data.get("source_manifest_hash") != report["source_manifest_hash"]):
        report["blockers"].append({"code": "LEGACY_MANIFEST_CHANGED", "message": "隔离预演后旧来源清单发生变化，包括零余额；请重新建立独立副本。"})
    report["ready"] = not report["blockers"]
    report["summary"] = {"source_count": len(report["sources"]), "group_count": len(groups),
                         "opening_source_count": len(candidates), "already_applied_count": sum(item[3] is not None for item in candidates),
                         "excluded_count": len(report["excluded"]), "zero_count": len(report["zero_balances"]), "blocker_count": len(report["blockers"])}
    return report, candidates, previous


def preview_public_stock(*, apply_isolated=False, actor_employee=None):
    """默认只有 SELECT；显式隔离预演成功前不会写任何数据。"""
    if not apply_isolated:
        return _load_plan()[0]
    with transaction.atomic():
        environment = assert_isolated_database()
        if (actor_employee is None or actor_employee.pk is None
                or not Employee.objects.filter(pk=actor_employee.pk, archived_at__isnull=True, status="ACTIVE").exists()):
            raise PublicStockPreviewError("ACTOR_REQUIRED", "隔离预演必须提供可审计的现有操作员工。")
        # 序列化期初预演，涵盖零余额清单和首次并发建账。
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [2026092803])
        report, candidates, previous = _load_plan(lock=True)
        if not report["ready"]:
            raise PublicStockPreviewError("PREVIEW_BLOCKED", "预检存在缺失或冲突，整个预演不写入。", report=report)
        from .public_stock_services import credit_public_stock
        movement_ids = []
        for row, identity, source, opening in candidates:
            if opening is not None:
                movement_ids.append(str(opening.pk))
                continue
            movement = credit_public_stock(identity=identity, zone=row.zone, quality=row.quality, quantity=row.quantity,
                source_type=OPENING_SOURCE_TYPE, source_id=row.pk, source_line_id=row.pk,
                actor_employee=actor_employee, production_task=row.production_task if identity["stock_kind"] == "SEMI" else None,
                product_line=row.product_line if identity["stock_kind"] == "SEMI" else None,
                bom_line=row.bom_line if identity["stock_kind"] == "SEMI" else None,
                snapshot={"legacy_source": source, "opening_only": True, "business_availability_enabled": False})
            movement_ids.append(str(movement.pk))
        if previous is None:
            write_audit_log(object_type=OPENING_SOURCE_TYPE, object_id=OPENING_AUDIT_ID, action="ISOLATED_OPENING_APPLIED",
                actor_employee=actor_employee, after_data={"source_manifest_hash": report["source_manifest_hash"],
                    "sources": [source for source in report["sources"] if source["model"] == "SemiFinishedStockBalance" or source.get("measurement_kind") == "PIPE"],
                    "movement_ids": movement_ids, "environment": environment,
                    "business_availability_enabled": False})
        report.update({"mode": "APPLY_ISOLATED", "applied": True, "environment": environment, "opening_movement_ids": movement_ids})
        return report
