"""正式期初导入：审阅清单只读，执行时重新取证并在维护事务内一次记账。"""

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.audit.models import AuditLog
from apps.core.audit import write_audit_log
from apps.organizations.models import Employee
from .models import PublicStockBalance, PublicStockMovement
from .public_stock_preview import OPENING_SOURCE_TYPE, _digest, _load_plan


FORMAL_OPENING_TYPE = "PUBLIC_STOCK_OPENING"
FORMAL_OPENING_ACTION = "FORMAL_OPENING_APPLIED"
FORMAL_OPENING_ID = UUID("d808bd86-3ca0-45cf-93f1-2092dbbc65e5")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class PublicStockOpeningError(ValueError):
    def __init__(self, code, message, *, report=None):
        self.code = code
        self.report = report
        super().__init__(f"{code}: {message}")


def _error(code, message):
    raise PublicStockOpeningError(code, message)


def _environment():
    from .public_stock_cutover import current_cutover_target
    return current_cutover_target()


def _actor(actor_employee):
    from .public_stock_cutover import require_cutover_operator
    actor_id = getattr(actor_employee, "pk", actor_employee)
    try:
        actor = Employee.objects.filter(pk=actor_id, status="ACTIVE", archived_at__isnull=True).first() if actor_id else None
    except (ValidationError, ValueError, TypeError):
        actor = None
    if actor is None:
        _error("ACTOR_REQUIRED", "正式期初清单需要有效且在职的操作员工。")
    return require_cutover_operator(actor)


def _file_hash(path):
    try:
        with path.open("rb") as source:
            before = path.stat()
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
            after = path.stat()
        if size == 0 or before.st_size != size or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
            _error("BACKUP_CHANGED", "备份为空，或在核验期间发生变化。")
        return digest.hexdigest(), size
    except OSError as error:
        raise PublicStockOpeningError("BACKUP_UNREADABLE", "备份文件不可读取。") from error


def _timestamp(value, name):
    try:
        parsed = parse_datetime(value) if isinstance(value, str) else None
    except (ValueError, TypeError, OverflowError):
        parsed = None
    if parsed is None or timezone.is_naive(parsed):
        _error("BACKUP_EVIDENCE_INVALID", f"{name}必须是带时区的完整时间。")
    return parsed


def _backup_evidence(evidence_path, environment):
    if not evidence_path:
        _error("BACKUP_EVIDENCE_REQUIRED", "必须提供已备份并验证可恢复的证据 JSON。")
    try:
        path = Path(evidence_path).resolve(strict=True)
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            _error("BACKUP_EVIDENCE_INVALID", "备份证据须为不超过 1 MB 的 JSON 文件。")
        raw = path.read_bytes()
        evidence = json.loads(raw.decode("utf-8-sig"))
    except (OSError, ValueError, TypeError, UnicodeError) as error:
        if isinstance(error, PublicStockOpeningError):
            raise
        raise PublicStockOpeningError("BACKUP_EVIDENCE_INVALID", "备份证据不存在或不是有效 JSON。") from error
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        _error("BACKUP_EVIDENCE_INVALID", "备份证据版本或对象格式无效。")
    if evidence.get("target") != environment:
        _error("BACKUP_TARGET_MISMATCH", "备份证据的主机、库名、集群标识必须与实际连接完全一致。")
    backup_hash = evidence.get("backup_sha256")
    if not isinstance(backup_hash, str) or not HASH_PATTERN.fullmatch(backup_hash):
        _error("BACKUP_EVIDENCE_INVALID", "备份证据缺少有效 SHA-256。")
    backup_path_value = evidence.get("backup_file")
    if not isinstance(backup_path_value, str) or not Path(backup_path_value).is_absolute():
        _error("BACKUP_EVIDENCE_INVALID", "backup_file 必须是可读取备份文件的绝对路径。")
    backup_path = Path(backup_path_value)
    if not backup_path.is_file():
        _error("BACKUP_UNREADABLE", "备份文件不存在或不是普通文件。")
    completed_at = _timestamp(evidence.get("backup_completed_at"), "backup_completed_at")
    verified_at = _timestamp(evidence.get("restore_verified_at"), "restore_verified_at")
    now = timezone.now()
    if evidence.get("restore_verified") is not True or verified_at < completed_at:
        _error("BACKUP_RESTORE_UNVERIFIED", "必须记录成功恢复验证，且验证时间不得早于备份完成时间。")
    if completed_at > now or verified_at > now:
        _error("BACKUP_TIME_INVALID", "备份和恢复验证时间不能位于未来。")
    from .public_stock_cutover import get_cutover_control
    control = get_cutover_control()
    if control is not None and completed_at < control.started_at:
        _error("BACKUP_BEFORE_MAINTENANCE", "必须使用本次进入停写后完成并验证恢复的备份。")
    actual_hash, size = _file_hash(backup_path)
    if actual_hash != backup_hash:
        _error("BACKUP_HASH_MISMATCH", "备份文件实际 SHA-256 与证据声明不一致。")
    return {"evidence_file": str(path), "evidence_sha256": hashlib.sha256(raw).hexdigest(),
            "backup_file": str(backup_path.resolve()), "backup_sha256": actual_hash, "backup_size_bytes": size,
            "backup_completed_at": completed_at.isoformat(), "restore_verified_at": verified_at.isoformat(),
            "restore_verified": True, "target": environment}


def _maintenance_snapshot():
    from .public_stock_cutover import get_cutover_control
    control = get_cutover_control()
    if control is None or control.state != "MAINTENANCE":
        _error("MAINTENANCE_REQUIRED", "正式期初必须先进入持久化维护停写状态。")
    return {"control_id": str(control.pk), "state": control.state}


def _prior_opening():
    return AuditLog.objects.filter(object_type=FORMAL_OPENING_TYPE, object_id=FORMAL_OPENING_ID,
                                   action=FORMAL_OPENING_ACTION).order_by("occurred_at", "id").first()


def _lock_opening_tables():
    # 维护锁负责业务入口停写；表锁还阻止未走业务入口的并发 SQL 修改来源和目标。
    model_names = [
        ("inventory", "MaterialStockBalance"), ("inventory", "MaterialStockMovement"),
        ("inventory", "SemiFinishedStockBalance"), ("inventory", "SemiFinishedStockMovement"),
        ("inventory", "PublicStockBalance"), ("inventory", "PublicStockMovement"),
        ("inventory", "MaterialInbound"), ("inventory", "MaterialInboundLine"),
        ("procurement", "PurchaseOrder"), ("procurement", "PurchaseOrderLine"),
        ("inventory", "Warehouse"), ("inventory", "WarehouseZone"),
        ("products", "RawMaterialInformation"), ("reference_data", "ProductCategory"),
        ("reference_data", "ProductionUnit"), ("organizations", "Employee"),
        ("production_tasks", "ProductionTask"), ("production_tasks", "ProductionTaskProduct"),
        ("boms", "BomLine"), ("boms", "BomSection"), ("boms", "Bom"),
        ("workshop_config", "Craft"), ("audit", "AuditLog"),
    ]
    table_names = sorted({apps.get_model(app, model)._meta.db_table for app, model in model_names})
    table_names = sorted(set(table_names) | {get_user_model()._meta.db_table})
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '10s'")
        cursor.execute("LOCK TABLE " + ", ".join(connection.ops.quote_name(name) for name in table_names)
                       + " IN SHARE ROW EXCLUSIVE MODE")


def _build_manifest(*, actor_employee, backup_evidence_path, lock=False):
    from .public_stock_cutover import assert_cutover_target

    environment = _environment()
    plan, candidates, _ = _load_plan(lock=lock)
    blockers = list(plan["blockers"])
    actor = None
    actor_snapshot = None
    backup = None
    maintenance = None
    for name, read in [
        ("target", assert_cutover_target), ("actor", lambda: _actor(actor_employee)),
        ("backup", lambda: _backup_evidence(backup_evidence_path, environment)),
        ("maintenance", _maintenance_snapshot),
    ]:
        try:
            value = read()
            if name == "actor":
                actor = value
                actor_snapshot = {"id": str(actor.pk), "employee_code": actor.employee_code, "display_name": actor.display_name}
            elif name == "backup":
                backup = value
            elif name == "maintenance":
                maintenance = value
        except Exception as error:
            code = getattr(error, "api_error_code", getattr(error, "code", None))
            if code is None:
                raise
            blockers.append({"code": code, "message": str(error)})
    previous = _prior_opening()
    if previous is None and (PublicStockMovement.objects.exists() or PublicStockBalance.objects.exists()):
        blockers.append({"code": "EXISTING_PUBLIC_STOCK", "message": "目标已有公共库存或隔离期初而无本正式清单审计，禁止再次导入或收编。"})
    relevant_sources = [source for source in plan["sources"]
                        if source["model"] == "SemiFinishedStockBalance" or source.get("measurement_kind") == "PIPE"]
    manifest = {
        "schema_version": 1, "operation": "PUBLIC_STOCK_FORMAL_OPENING",
        "target": environment, "actor": actor_snapshot, "backup": backup, "maintenance": maintenance,
        "source_manifest_hash": plan["source_manifest_hash"], "sources": relevant_sources,
        "groups": plan["groups"], "excluded": plan["excluded"], "zero_balances": plan["zero_balances"],
        "availability_policy": "正式期初仅写公共账；旧账数量保持原样。维护结束前禁止业务写入，新旧余额永不相加。",
    }
    manifest_hash = _digest(manifest)
    if previous is not None:
        saved = previous.after_data if isinstance(previous.after_data, dict) else {}
        if saved.get("manifest_sha256") != manifest_hash:
            blockers.append({"code": "FORMAL_MANIFEST_CHANGED", "message": "已经执行过的正式期初清单与现场重算结果不同，禁止新建另一批期初。"})
        live_ids = sorted(str(opening.pk) for _, _, _, opening in candidates if opening is not None)
        if saved.get("movement_ids") != live_ids or any(opening is None for _, _, _, opening in candidates):
            blockers.append({"code": "FORMAL_OPENING_INCOMPLETE", "message": "已审计期初流水缺失或与来源清单不一致，禁止补写掩盖差异。"})
        if any(opening is not None and opening.snapshot.get("formal_manifest_sha256") != saved.get("manifest_sha256")
               for _, _, _, opening in candidates):
            blockers.append({"code": "FORMAL_OPENING_SNAPSHOT_CHANGED", "message": "期初流水的审阅清单证据已改变。"})
        expected_balances = {(group["stock_kind"], group["identity_key"], group["zone_id"], group["quality"]): group
                             for group in plan["groups"]}
        actual_balances = list(PublicStockBalance.objects.all())
        unchanged = len(actual_balances) == len(expected_balances) and PublicStockMovement.objects.count() == len(live_ids)
        for balance in actual_balances:
            group = expected_balances.get((balance.stock_kind, balance.identity_key, str(balance.zone_id), balance.quality))
            if (group is None or balance.quantity != Decimal(group["quantity"])
                    or balance.meter_quantity != (Decimal(group["meter_quantity"]) if group["meter_quantity"] is not None else None)):
                unchanged = False
        if not unchanged:
            blockers.append({"code": "FORMAL_OPENING_LEDGER_CHANGED", "message": "维护期间公共余额或流水已偏离正式期初，禁止把差异当作成功重跑。"})
    report = {"schema_version": 1, "mode": "DRY_RUN", "read_only": True, "applied": False,
              "ready": not blockers, "environment": environment, "manifest": manifest,
              "manifest_sha256": manifest_hash, "blockers": blockers, "summary": plan["summary"],
              "created_movement_count": 0, "already_applied": previous is not None}
    report["summary"]["blocker_count"] = len(blockers)
    return report, candidates, previous, actor


def build_public_stock_opening_manifest(*, actor_employee=None, backup_evidence_path=None):
    """只有查询和本地证据读取，不创建停写状态、不创建期初或审计。"""
    return _build_manifest(actor_employee=actor_employee, backup_evidence_path=backup_evidence_path)[0]


def apply_public_stock_opening(*, expected_manifest_sha256, expected_target, actor_employee,
                               backup_evidence_path):
    """输入仅绑定已审清单；库存身份和数量一律从锁定的历史账现场重算。"""
    from .public_stock_cutover import allow_opening_stock_credit, assert_cutover_target, require_transition_maintenance
    from .public_stock_services import credit_public_stock

    if not isinstance(expected_manifest_sha256, str) or not HASH_PATTERN.fullmatch(expected_manifest_sha256):
        _error("EXPECTED_MANIFEST_REQUIRED", "执行需要已审阅清单的完整 SHA-256。")
    if (not isinstance(expected_target, dict) or set(expected_target) != {"host", "database", "system_identifier"}
            or not all(isinstance(value, str) and value.strip() for value in expected_target.values())):
        _error("EXPECTED_TARGET_REQUIRED", "执行需要明确的主机、库名和真实集群标识。")
    with transaction.atomic():
        require_transition_maintenance()
        environment = assert_cutover_target()
        if environment != expected_target:
            _error("TARGET_MISMATCH", "执行目标与已审阅目标不一致。")
        _lock_opening_tables()
        report, candidates, previous, actor = _build_manifest(
            actor_employee=actor_employee, backup_evidence_path=backup_evidence_path, lock=True)
        if report["manifest_sha256"] != expected_manifest_sha256:
            raise PublicStockOpeningError("MANIFEST_STALE", "现场重算清单已改变，请重新预检和审阅。", report=report)
        if not report["ready"]:
            raise PublicStockOpeningError("OPENING_BLOCKED", "期初清单存在缺失或冲突，本次没有写入。", report=report)
        if previous is not None:
            report.update({"mode": "APPLY", "read_only": False, "applied": True,
                           "opening_movement_ids": previous.after_data["movement_ids"], "audit_id": str(previous.pk)})
            return report
        movement_ids = []
        with allow_opening_stock_credit():
            for row, identity, source, _ in candidates:
                semi = identity["stock_kind"] == "SEMI"
                movement = credit_public_stock(
                    identity=identity, zone=row.zone, quality=row.quality, quantity=row.quantity,
                    source_type=OPENING_SOURCE_TYPE, source_id=row.pk, source_line_id=row.pk,
                    actor_employee=actor, production_task=row.production_task if semi else None,
                    product_line=row.product_line if semi else None, bom_line=row.bom_line if semi else None,
                    snapshot={"legacy_source": source, "opening_only": True,
                              "business_availability_enabled": False, "formal_manifest_sha256": expected_manifest_sha256},
                )
                movement_ids.append(str(movement.pk))
        movement_ids.sort()
        audit = write_audit_log(object_type=FORMAL_OPENING_TYPE, object_id=FORMAL_OPENING_ID,
                               action=FORMAL_OPENING_ACTION, actor_employee=actor,
                               after_data={"manifest_sha256": expected_manifest_sha256,
                                           "source_manifest_hash": report["manifest"]["source_manifest_hash"],
                                           "source_ids": sorted(source["id"] for source in report["manifest"]["sources"]),
                                           "target": environment, "backup": report["manifest"]["backup"],
                                           "manifest": report["manifest"], "movement_ids": movement_ids})
        report.update({"mode": "APPLY", "read_only": False, "applied": True,
                       "created_movement_count": len(movement_ids), "opening_movement_ids": movement_ids,
                       "audit_id": str(audit.pk)})
        return report
