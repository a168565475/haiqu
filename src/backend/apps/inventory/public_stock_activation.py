"""首次公共库存启用：只读核验事实，明确授权后才在独占事务中切换。"""

import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.audit.models import AuditLog
from apps.boms.models import Bom, BomLine
from apps.boms.material_flow_calculations import cutting_usage_plan, pipe_plan
from apps.material_issues.models import (MaterialIssue, MaterialIssueLine, MetalProcessingSource,
    MetalProcessingOriginalHandoff, MetalProcessingExternalOrder, OrderMaterialRequirement,
    OrderSemiFinishedRequirement)
from apps.organizations.models import Employee
from apps.outsourcing.models import (OutsourcingOrder, OutsourcingDispatch, OutsourcingDispatchLine,
    OutsourcingRawReturnLine, OutsourcingProcessingItem)
from apps.production_scheduling.models import ProductionScheduleProduct
from apps.reference_data.models import ProductionUnit
from .models import PublicStockBalance, PublicStockMovement, PublicStockCutoverControl, MaterialInbound
from .public_stock_cutover import (assert_cutover_target, current_cutover_target, lock_stock_writes,
    require_cutover_operator)
from .public_stock_identity import build_semi_finished_identity
from .public_stock_opening import FORMAL_OPENING_ACTION, FORMAL_OPENING_TYPE, FORMAL_OPENING_ID, HASH_PATTERN
from .public_stock_preview import _load_plan


OPERATION = "ACTIVATE_PUBLIC_STOCK"
ACTION = "PUBLIC_ACTIVATED"
AUDIT_TYPE = "PUBLIC_STOCK_CUTOVER"
ZERO = Decimal("0")
LOCKED_APPS = {"inventory", "material_issues", "outsourcing", "boms", "production_scheduling",
               "production_tasks", "products", "reference_data", "workshop_config", "organizations",
               "procurement", "audit", "auth"}


class PublicStockActivationError(ValueError):
    def __init__(self, code, message, *, report=None):
        self.code, self.report = code, report
        super().__init__(f"{code}: {message}")


def _fail(code, message):
    raise PublicStockActivationError(code, message)


def _json(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False, allow_nan=False))


def digest(value):
    return hashlib.sha256(json.dumps(_json(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _block(blockers, code, message, **context):
    blockers.append({"code": code, "message": message, **_json(context)})


def _capture(blockers, function, **context):
    try:
        return function()
    except Exception as error:
        code = getattr(error, "api_error_code", getattr(error, "code", None))
        if code is None and not isinstance(error, (ValueError, TypeError, AttributeError)) and not hasattr(error, "detail"):
            raise
        _block(blockers, code or "ACTIVATION_FACT_INVALID", str(error), **context)
        return None


def _actor(value):
    try:
        actor = Employee.objects.filter(pk=getattr(value, "pk", value)).first() if value else None
    except (DjangoValidationError, ValueError, TypeError):
        actor = None
    return require_cutover_operator(actor)


def _load_evidence(path, label):
    if not path:
        _fail("EVIDENCE_REQUIRED", f"缺少{label}。")
    try:
        source = Path(path).resolve(strict=True)
        if not source.is_file() or source.stat().st_size > 1024 * 1024:
            _fail("EVIDENCE_INVALID", f"{label}须为不超过 1 MB 的 JSON 文件。")
        data = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PublicStockActivationError("EVIDENCE_INVALID", f"不能读取{label}。") from error
    if not isinstance(data, dict):
        _fail("EVIDENCE_INVALID", f"{label}必须是 JSON 对象。")
    return data


def _confirmed(evidence, operation, target, control):
    if (evidence.get("schema_version") != 1 or evidence.get("operation") != operation
            or evidence.get("confirmed") is not True or evidence.get("target") != target
            or evidence.get("control_id") != str(control.pk)):
        _fail("AUTHORIZATION_INVALID", "确认凭证的操作、目标或本次维护会话不一致。")
    if any(not isinstance(evidence.get(key), str) or not evidence[key].strip()
           for key in ("confirmed_by", "confirmation_text", "confirmed_at")):
        _fail("AUTHORIZATION_INVALID", "确认凭证必须保留具名确认人、明确原话和确认时间。")
    try:
        at = parse_datetime(evidence["confirmed_at"])
    except (ValueError, TypeError):
        at = None
    if at is None or timezone.is_naive(at) or at < control.started_at or at > timezone.now():
        _fail("AUTHORIZATION_INVALID", "确认时间必须在本次维护开始之后，且不能位于未来。")


def legacy_plan_snapshot(issue):
    """保留旧计划的确认需覆盖当前单头、逐行内容和审批历史。"""
    header = MaterialIssue.objects.filter(pk=issue.pk).values().get()
    rows = list(issue.lines.order_by("id").values())
    approvals = list(issue.audit_events.order_by("id").values())
    return {"id": str(issue.pk), "number": issue.issue_number, "status": issue.status,
            "version": issue.version, "stock_mode": issue.stock_mode,
            "snapshot_sha256": digest({"header": header, "lines": rows, "approvals": approvals})}


def _legacy_plans(blockers, *, retention_path, target, control):
    plans = list(MaterialIssue.objects.filter(stock_mode="LEGACY", status__in=["DRAFT", "RETURNED", "PENDING_REVIEW"])
                 .order_by("id"))
    retained = []
    for issue in plans:
        row = legacy_plan_snapshot(issue)
        if issue.status == "PENDING_REVIEW":
            _block(blockers, "LEGACY_PENDING_REVIEW", "旧领料待审占用尚未处理。", **row)
        else:
            if issue.lines.filter(issued_quantity__isnull=False).exists():
                _block(blockers, "LEGACY_PLAN_HAS_ISSUE", "未执行计划存在实发记录，须核清状态。", **row)
            retained.append(row)
    evidence = None
    if retained:
        def check_retention():
            value = _load_evidence(retention_path, "保留旧草稿及退回单的确认清单")
            if control is None:
                _fail("MAINTENANCE_REQUIRED", "保留计划凭证须绑定本次维护。")
            _confirmed(value, "RETAIN_LEGACY_UNISSUED_PLANS", target, control)
            expected = [{"id": row["id"], "snapshot_sha256": row["snapshot_sha256"]} for row in retained]
            if value.get("plans") != expected:
                _fail("LEGACY_PLAN_REVIEW_STALE", "确认清单须精确覆盖全部旧草稿/退回单的当前内容与审批摘要。")
            return value
        evidence = _capture(blockers, check_retention)
    elif retention_path:
        _block(blockers, "LEGACY_PLAN_REVIEW_UNEXPECTED", "现场已无待保留计划，请移除过时确认清单。")
    return {"retained_plans": retained, "retention_confirmation": evidence,
            "retention_policy": "保留旧单及审批历史待重建，不迁移或再次提交旧单；草稿仍可编辑，编辑不授予旧账出库权限。"}


def _legacy_transit(blockers):
    from apps.material_issues.legacy_public_transition import trusted_handoff_transition
    from apps.material_issues.p4_services import _allocation_for_handoff, original_handoff_totals
    result = {"handoffs": [], "sources": [], "orders": []}
    for row in MaterialInbound.objects.filter(stock_mode="LEGACY", status="PENDING_QUALITY").order_by("id"):
        _block(blockers, "LEGACY_PENDING_QUALITY", "旧入库待质检尚未处理。", id=row.pk)
    handoffs = list(MetalProcessingOriginalHandoff.objects.filter(original_order__stock_mode="LEGACY")
        .select_related("source__issue_line__issue", "original_order").order_by("id"))
    source_totals, order_ids = defaultdict(int), set()
    for handoff in handoffs:
        totals = _capture(blockers, lambda: original_handoff_totals(_allocation_for_handoff(handoff)), handoff_id=handoff.pk)
        if totals is None:
            continue
        if (totals["returned_pieces"] + totals["returned_unsprayed_pieces"] > totals["handoff_pieces"]
                or totals["handoff_pieces"] < handoff.handoff_pieces):
            _block(blockers, "LEGACY_HANDOFF_TOTAL_CONFLICT", "旧交接及回货累计数量不一致。", handoff_id=handoff.pk)
            continue
        if totals["returned_pieces"] == totals["handoff_pieces"] and not totals["returned_unsprayed_pieces"]:
            source_totals[handoff.source_id] += handoff.handoff_pieces
            order_ids.add(handoff.original_order_id)
            result["handoffs"].append({"id": str(handoff.pk), "settled": True, "transition_id": None, "totals": _json(totals)})
            continue
        if totals["returned_unsprayed_pieces"]:
            _block(blockers, "LEGACY_UNSPRAYED_REMAINDER_REVIEW", "旧未喷塑退回及再加工须单独核清，不能当作合格回货。", handoff_id=handoff.pk)
        transition = _capture(blockers, lambda: trusted_handoff_transition(handoff), handoff_id=handoff.pk)
        if transition is None:
            _block(blockers, "LEGACY_HANDOFF_NOT_ADOPTED", "旧实际交接缺少可信接续凭证。", handoff_id=handoff.pk)
            continue
        source_totals[handoff.source_id] += handoff.handoff_pieces
        order_ids.add(handoff.original_order_id)
        result["handoffs"].append({"id": str(handoff.pk), "transition_id": str(transition.pk),
            "transition_sha256": digest({"identity": transition.public_identity, "evidence": transition.evidence,
                "quantity": transition.quantity_snapshot, "manifest": transition.manifest_hash}), "totals": _json(totals)})
    for line in MaterialIssueLine.objects.filter(issue__stock_mode="LEGACY", issue__status="ISSUED",
            line_type="RAW", conversion_snapshot__kind="PIPE").order_by("id"):
        source = MetalProcessingSource.objects.filter(issue_line=line).first()
        if source is None:
            _block(blockers, "LEGACY_PROCESSING_SOURCE_MISSING", "旧已领管材缺少加工来源。", line_id=line.pk)
            continue
        row = {"id": str(source.pk), "version": source.version, "source_hash": source.source_hash,
            "issued": source.issued_pieces, "completed": source.completed_pieces,
            "reserved": source.reserved_pieces, "dispatched": source.dispatched_pieces,
            "trusted_handoff_pieces": source_totals[source.pk]}
        result["sources"].append(row)
        if not (source.reserved_pieces == 0 and source.issued_pieces == source.completed_pieces
                == source.dispatched_pieces == source_totals[source.pk]):
            _block(blockers, "LEGACY_PROCESSING_REMAINDER_UNRESOLVED", "旧已领来源仍有未交接或未获可信接续的在制数量。", **row)
    for order in OutsourcingOrder.objects.filter(stock_mode="LEGACY").exclude(status="CANCELLED").order_by("id"):
        dispatched = OutsourcingDispatch.objects.filter(order=order).exists()
        has_handoffs = any(row.original_order_id == order.pk for row in handoffs)
        row = {"id": str(order.pk), "number": order.order_number, "status": order.status,
               "version": order.version, "has_dispatch": dispatched, "has_handoffs": has_handoffs}
        result["orders"].append(row)
        if order.status != "COMPLETED" and not dispatched and not has_handoffs:
            _block(blockers, "LEGACY_UNDISPATCHED_PLAN", "旧未发出外发计划须按确认方案处置。", **row)
        elif dispatched and order.status != "COMPLETED":
            _block(blockers, "LEGACY_DISPATCH_TRANSITION_UNSUPPORTED", "旧直接发料在途尚无受支持的接续凭证。", **row)
        elif has_handoffs and order.pk not in order_ids:
            _block(blockers, "LEGACY_ORDER_NOT_ADOPTED", "旧交接外发单未被可信接续完整覆盖。", **row)
    for order in MetalProcessingExternalOrder.objects.filter(stock_mode="LEGACY").filter(
            ~Q(status="COMPLETED") | Q(handoff_pieces__gt=F("returned_good_pieces"))).order_by("id"):
        _block(blockers, "LEGACY_REWORK_UNRESOLVED", "旧再加工外发仍需单独核实接续。", id=order.pk, status=order.status)
    return result


def _opening(blockers):
    plan, candidates, _ = _load_plan()
    blockers.extend(plan["blockers"])
    audits = list(AuditLog.objects.filter(object_type=FORMAL_OPENING_TYPE, object_id=FORMAL_OPENING_ID,
        action=FORMAL_OPENING_ACTION).order_by("id"))
    if len(audits) != 1:
        _block(blockers, "FORMAL_OPENING_REQUIRED", "必须存在唯一正式期初审计，不能收编隔离预演。")
        return {"source_manifest_hash": plan["source_manifest_hash"], "summary": plan["summary"]}
    audit = audits[0]
    saved = audit.after_data if isinstance(audit.after_data, dict) else {}
    original = saved.get("manifest")
    moves = list(PublicStockMovement.objects.order_by("id"))
    ids = [str(row.pk) for row in moves]
    if (not isinstance(original, dict) or digest(original) != saved.get("manifest_sha256")
            or saved.get("source_manifest_hash") != plan["source_manifest_hash"]
            or saved.get("movement_ids") != ids
            or any(row[3] is None for row in candidates)):
        _block(blockers, "FORMAL_OPENING_CHANGED", "正式期初审计、来源或完整流水清单不一致。")
    for move in moves:
        if (move.source_type != FORMAL_OPENING_TYPE or move.direction != "IN"
                or move.snapshot.get("formal_manifest_sha256") != saved.get("manifest_sha256")):
            _block(blockers, "PUBLIC_BUSINESS_BEFORE_ACTIVATION", "公共账存在非本正式期初流水，不能首次启用。", movement_id=move.pk)
    running = defaultdict(lambda: {"quantity": ZERO, "meters": ZERO})
    for move in sorted(moves, key=lambda value: (value.created_at, str(value.pk))):
        current = running[move.balance_id]
        if move.before_quantity != current["quantity"] or move.after_quantity != current["quantity"] + move.quantity:
            _block(blockers, "FORMAL_OPENING_LEDGER_CHAIN", "期初流水的数量前后链不连续。", movement_id=move.pk)
        current["quantity"] = move.after_quantity
        if move.meter_quantity is not None:
            if (move.before_meter_quantity != current["meters"]
                    or move.after_meter_quantity != current["meters"] + move.meter_quantity):
                _block(blockers, "FORMAL_OPENING_LEDGER_CHAIN", "期初流水的米数前后链不连续。", movement_id=move.pk)
            current["meters"] = move.after_meter_quantity
    expected = {(g["stock_kind"], g["identity_key"], g["zone_id"], g["quality"]): g for g in plan["groups"]}
    balances = list(PublicStockBalance.objects.order_by("id"))
    actual = {(b.stock_kind, b.identity_key, str(b.zone_id), b.quality): b for b in balances}
    if expected.keys() != actual.keys():
        _block(blockers, "FORMAL_OPENING_BALANCES_CHANGED", "公共余额分组与正式期初来源不一致。")
    for key, balance in actual.items():
        group = expected.get(key)
        tail = running[balance.pk]
        if tail["quantity"] != balance.quantity or (balance.stock_kind == "RAW_PIPE" and tail["meters"] != balance.meter_quantity):
            _block(blockers, "FORMAL_OPENING_LEDGER_TAIL", "正式期初流水尾数与实际余额不一致。", balance_id=balance.pk)
        for move in [row for row in moves if row.balance_id == balance.pk]:
            if balance.stock_kind == "RAW_PIPE":
                if (move.meter_quantity is None or move.before_meter_quantity is None or move.after_meter_quantity is None
                        or move.meter_quantity != move.quantity * balance.raw_bar_length_m):
                    _block(blockers, "FORMAL_OPENING_METER_INVALID", "根米期初流水缺米数或与整根长度不符。", movement_id=move.pk)
            elif any(value is not None for value in (move.meter_quantity, move.before_meter_quantity, move.after_meter_quantity)):
                _block(blockers, "FORMAL_OPENING_METER_INVALID", "半成品期初流水不能附带原料米数。", movement_id=move.pk)
        if (group is None or balance.quantity != Decimal(group["quantity"])
                or balance.identity_snapshot != group["identity_snapshot"]
                or balance.meter_quantity != (Decimal(group["meter_quantity"]) if group["meter_quantity"] is not None else None)):
            _block(blockers, "FORMAL_OPENING_BALANCES_CHANGED", "公共余额数量、米数或冻结身份与期初不一致。", balance_id=balance.pk)
    return {"audit_id": str(audit.pk), "audit_sha256": digest(saved), "source_manifest_hash": plan["source_manifest_hash"],
            "balances_sha256": digest(list(PublicStockBalance.objects.order_by("id").values())),
            "movements_sha256": digest(list(PublicStockMovement.objects.order_by("id").values())),
            "summary": plan["summary"], "groups": plan["groups"]}


def _active_boms(blockers):
    from apps.material_issues.public_semi_requirements import _semi_kind, _net_quantity
    from apps.material_issues.pipe_requirements import pipe_source_snapshot
    from apps.products.material_identity import resolve_bom_line_raw_material, resolve_cutting_fabric_material
    from apps.inventory.public_bom_snapshot import freeze_bom_line
    schedules = list(ProductionScheduleProduct.objects.filter(schedule__record_status="ACTIVE", removed_at__isnull=True)
        .select_related("schedule__production_task", "product_line").prefetch_related("crafts__craft").order_by("id"))
    units = {unit.unit_name: unit for unit in ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True)}
    result, pipe_limits = [], {}
    for scheduled in schedules:
        product, task = scheduled.product_line, scheduled.schedule.production_task
        item = {"schedule_product_id": str(scheduled.pk), "schedule_id": str(scheduled.schedule_id),
            "schedule_version": scheduled.schedule.version, "product_id": str(product.pk), "task_id": str(task.pk),
            "quantity": product.quantity, "planned_quantity": scheduled.planned_quantity,
            "source_quantity": scheduled.source_quantity_snapshot, "crafts": [], "lines": []}
        result.append(item)
        if (product.production_task_id != task.pk or task.archived_at is not None
                or scheduled.source_quantity_snapshot != product.quantity or scheduled.planned_quantity > product.quantity):
            _block(blockers, "ACTIVE_SCHEDULE_STALE", "有效排产的产品、订单或数量与现场不一致。", product_id=product.pk)
        crafts = []
        for link in scheduled.crafts.all():
            if link.removed_at is not None:
                continue
            craft = link.craft
            item["crafts"].append({"id": str(craft.pk), "link_id": str(link.pk), "type": craft.craft_type,
                "code": craft.outsourcing_code if craft.craft_type == "EXTERNAL" else craft.plan_category,
                "snapshot_type": link.craft_type_snapshot, "plan_category": link.plan_category})
            if craft.status != "ACTIVE" or link.craft_type_snapshot != craft.craft_type or (
                    craft.craft_type == "INTERNAL" and link.plan_category != craft.plan_category):
                _block(blockers, "ACTIVE_CRAFT_CONFLICT", "有效排产工艺已停用或与冻结类型/类别冲突。", craft_id=craft.pk, product_id=product.pk)
            crafts.append(craft)
        if not crafts:
            _block(blockers, "ACTIVE_CRAFT_REQUIRED", "有效排产没有有效工艺。", product_id=product.pk)
        bom = Bom.objects.filter(production_task=task, product_line=product, archived_at__isnull=True).order_by("-version_number", "-id").first()
        if bom is None or bom.status != "VERIFIED" or bom.order_quantity != product.quantity:
            _block(blockers, "ACTIVE_BOM_NOT_READY", "有效排产须使用最新已核实、数量相符的 BOM。", product_id=product.pk)
            continue
        item["bom"] = {"id": str(bom.pk), "number": bom.bom_number, "version": bom.version_number,
                       "updated_at": bom.updated_at, "quantity": bom.order_quantity}
        lines = list(BomLine.objects.filter(section__bom=bom).select_related("section__bom", "fabric_source_line__section").order_by("id"))
        if not lines:
            _block(blockers, "ACTIVE_BOM_EMPTY", "有效排产的已核实 BOM 实际没有明细行。", bom_id=bom.pk)
        counts = Counter(line.component_identity for line in lines)
        for line in lines:
            kind = _semi_kind(line)
            if kind != "PIPE" and (line.section.title.strip() == "管材类" or line.cutting_length_mm is not None):
                _block(blockers, "BOM_SECTION_CONFLICT", "管材行的分区类型与管材用途冲突。", bom_line_id=line.pk)
            if counts[line.component_identity] > 1:
                _block(blockers, "COMPONENT_IDENTITY_DUPLICATE", "有效 BOM 存在重复部位标识。", bom_line_id=line.pk)
            entry = {"id": str(line.pk), "kind": kind,
                "snapshot": _capture(blockers, lambda: freeze_bom_line(line), bom_line_id=line.pk), "identities": []}
            item["lines"].append(entry)
            if kind == "PIPE":
                def check_pipe():
                    raw, _ = resolve_bom_line_raw_material(line)
                    piece_unit = units.get("支")
                    if piece_unit is None:
                        _fail("PIPE_UNIT_INVALID", "有效管材部位必须存在已启用、未归档的支单位。")
                    if (raw is None or raw.item_type != "MATERIAL" or raw.category.category_name != "管材"
                            or raw.unit.unit_name != "根" or raw.archived_at is not None
                            or raw.unit.status != "ACTIVE" or raw.unit.archived_at is not None
                            or raw.category.status != "ACTIVE" or raw.category.archived_at is not None):
                        _fail("PIPE_MATERIAL_INVALID", "有效管材部位须关联根制管材原料。")
                    value = pipe_source_snapshot(line, raw)
                    recomputed = pipe_plan(cutting_length_mm=line.cutting_length_mm, pieces_per_product=line.pieces_per_product,
                        pieces_per_bar=line.pieces_per_bar, order_quantity=bom.order_quantity)
                    if line.raw_bar_length_m != Decimal(recomputed["raw_bar_length_m"]):
                        _fail("PIPE_LENGTH_CONFLICT", "管材保存的原料长度与切割参数计算不符。")
                    pipe_limits[(task.pk, product.pk, line.component_identity)] = {"limit": Decimal(recomputed["allowance_pieces"]),
                        "raw_material_id": raw.pk, "unit_id": piece_unit.pk,
                        "pieces_per_bar": line.pieces_per_bar, "raw_bar_length_m": line.raw_bar_length_m,
                        "cutting_length_mm": line.cutting_length_mm}
                    return value
                entry["usage"] = _capture(blockers, check_pipe, bom_line_id=line.pk)
                matching = [craft for craft in crafts if craft.craft_type == "EXTERNAL" and craft.outsourcing_code == "POWDER_COATING"]
                unit = units.get("支")
            elif kind == "CUTTING":
                def check_cutting():
                    raw, mapping_error = resolve_cutting_fabric_material(line)
                    if (mapping_error or raw is None or raw.item_type != "MATERIAL" or raw.category.category_name != "面料"
                            or raw.unit.unit_name != "米" or raw.archived_at is not None
                            or raw.unit.status != "ACTIVE" or raw.unit.archived_at is not None
                            or raw.category.status != "ACTIVE" or raw.category.archived_at is not None):
                        _fail("CUTTING_MATERIAL_INVALID", "裁片来源须明确映射有效的米制面料原料档案。")
                    value = cutting_usage_plan(cutting_pieces_per_set=line.cutting_pieces_per_set,
                        fabric_meters_per_piece=line.fabric_meters_per_piece, cutting_sets_per_product=line.cutting_sets_per_product,
                        order_quantity=bom.order_quantity)
                    if value is None:
                        _fail("CUTTING_USAGE_REQUIRED", "有效裁片须填写每套片数、每片米数、每成品套数。")
                    if line.fabric_meters_per_set != Decimal(value["fabric_meters_per_set"]):
                        _fail("CUTTING_USAGE_CONFLICT", "裁片每套耗米与新用量字段不一致。")
                    value["resolved_fabric_material"] = {"id": str(raw.pk), "unit_id": str(raw.unit_id),
                        "category_id": str(raw.category_id), "source_bom_line_id": str(line.fabric_source_line_id)}
                    return value
                entry["usage"] = _capture(blockers, check_cutting, bom_line_id=line.pk)
                matching = [craft for craft in crafts if (craft.outsourcing_code if craft.craft_type == "EXTERNAL" else craft.plan_category)
                            in {"CUTTING", "SEWING", "SCREEN_PRINTING"}]
                unit = units.get("套")
            elif kind == "HARDWARE":
                selected = set(OutsourcingProcessingItem.objects.filter(bom_line=line)
                    .exclude(order_product__order__status="CANCELLED").values_list("order_product__order__craft_id", flat=True))
                matching = [craft for craft in crafts if craft.pk in selected]
                unit = units.get((line.raw_values or {}).get("hardware_flow_unit") or line.unit)
            else:
                continue
            for craft in matching:
                def check_identity():
                    if unit is None:
                        _fail("ACTIVE_UNIT_REQUIRED", "所选半成品工艺缺少有效流转单位。")
                    identity = build_semi_finished_identity(bom_line=line, completed_craft=craft, unit=unit)
                    net_quantity, net_basis = _net_quantity(line, bom.order_quantity)
                    entry["net_quantity"], entry["net_basis"] = str(net_quantity), net_basis
                    return identity
                identity = _capture(blockers, check_identity, bom_line_id=line.pk, craft_id=craft.pk)
                if identity:
                    entry["identities"].append(identity)
    return _json(result), pipe_limits


def _quotas(blockers, pipe_limits, active_products):
    from apps.material_issues.public_semi_requirements import build_public_semi_specs
    result = []
    requirements = list(OrderMaterialRequirement.objects.order_by("id"))
    for row in requirements:
        issued = MaterialIssueLine.objects.filter(requirement=row, issue__status="ISSUED").aggregate(total=Sum("issued_quantity"))["total"] or ZERO
        pending = MaterialIssueLine.objects.filter(requirement=row, issue__status="PENDING_REVIEW").aggregate(total=Sum("requested_quantity"))["total"] or ZERO
        external = ZERO
        for dispatched in OutsourcingDispatchLine.objects.filter(requirement=row).order_by("id"):
            amount = Decimal(dispatched.issued_piece_count) if row.measurement_kind == "PIPE" and dispatched.issued_piece_count is not None else dispatched.issued_quantity
            returns = OutsourcingRawReturnLine.objects.filter(dispatch_line=dispatched).aggregate(
                total=Sum("piece_quantity_equivalent" if row.measurement_kind == "PIPE" else "quantity"))["total"] or ZERO
            external += amount - returns
        pipe = pipe_limits.get((row.production_task_id, row.product_line_id, row.component_identity))
        limit = pipe["limit"] if pipe else row.required_quantity
        item = {"id": str(row.pk), "required": str(row.required_quantity), "current_limit": str(limit),
            "internal": str(row.internal_issued_quantity), "external": str(row.outsourcing_issued_quantity),
            "actual_internal": str(issued), "actual_external": str(external), "pending": str(pending),
            "source_revision_hash": row.source_revision_hash}
        result.append(item)
        if row.internal_issued_quantity != issued or row.outsourcing_issued_quantity != external:
            _block(blockers, "QUOTA_HISTORY_MISMATCH", "已领/外发计数与实际历史不符，禁止重建额度掩盖差异。", **item)
        if issued + external + pending > limit or external < 0:
            _block(blockers, "QUOTA_EXCEEDED", "当前用量和待审占用超出有效需求额度。", **item)
        if row.measurement_kind == "PIPE" and issued + external > 0:
            current = list(row.contributions.filter(is_current=True).order_by("id").values(
                "bom_id", "bom_line_id", "product_line_id", "source_revision_hash", "calculation_basis"))
            item["contributions"] = _json(current)
            if not current:
                _block(blockers, "QUOTA_SOURCE_MISSING", "已有消耗的管材额度缺少当前部位来源。", requirement_id=row.pk)
            for source in current:
                basis = source["calculation_basis"]
                valid = isinstance(basis, dict)
                if valid:
                    # 与 pipe_source_snapshot 的既有摘要算法完全相同，不能只校验其中一个参数。
                    basis_hash = hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()
                    valid = (basis_hash == source["source_revision_hash"] == row.source_revision_hash
                        and basis.get("bom_id") == str(source["bom_id"])
                        and basis.get("bom_line_id") == str(source["bom_line_id"])
                        and basis.get("product_line_id") == str(row.product_line_id) == str(source["product_line_id"])
                        and basis.get("component_identity") == str(row.component_identity)
                        and basis.get("raw_material_id") == str(row.raw_material_id)
                        and basis.get("pieces_per_bar") == row.pieces_per_bar
                        and str(basis.get("raw_bar_length_m")) == format(row.raw_bar_length_m, ".2f"))
                if not valid:
                    _block(blockers, "QUOTA_SOURCE_EVIDENCE_CHANGED", "已耗管材的完整计算凭证、原料/部位引用或摘要不一致。", requirement_id=row.pk)
            if str(row.product_line_id) in active_products:
                if pipe is None or (row.raw_material_id != pipe["raw_material_id"] or row.unit_id != pipe["unit_id"]
                        or row.pieces_per_bar != pipe["pieces_per_bar"] or row.raw_bar_length_m != pipe["raw_bar_length_m"]
                        or any(not isinstance(source["calculation_basis"], dict)
                               or source["calculation_basis"].get("cutting_length_mm") != pipe["cutting_length_mm"] for source in current)):
                    _block(blockers, "QUOTA_USED_COMPONENT_CHANGED", "有效排产的已耗管材部位被删除或更换了原料/切割参数。", requirement_id=row.pk)
        if row.measurement_kind == "OTHER" and row.section_code == "PROFILE" and issued + external > 0:
            active_tasks = {str(key[0]) for key in pipe_limits}
            if str(row.production_task_id) in active_tasks:
                _block(blockers, "QUOTA_OLD_PIPE_UNRESOLVED", "订单仍有旧口径管材耗用，不能再创建部位新额度。", requirement_id=row.pk)
    semi = []
    scopes = set(OrderSemiFinishedRequirement.objects.values_list("production_task_id", "product_line_id"))
    scopes.update(MaterialIssueLine.objects.filter(line_type="SEMI", issue__status__in=["ISSUED", "PENDING_REVIEW"])
        .values_list("issue__production_task_id", "issue__product_line_id"))
    for task_id, product_id in sorted(scopes, key=lambda value: tuple(map(str, value))):
        specs, errors = build_public_semi_specs(task_id, product_id)
        blockers.extend({"code": error["code"], "message": error["detail"], "task_id": str(task_id),
                         "product_id": str(product_id)} for error in errors)
        semi.extend({"id": str(row["id"]), "required": str(row["required_quantity"]),
            "issued": str(row["internal_issued_quantity"]), "source": row["source_snapshot"]} for row in specs)
    return {"raw": result, "semi": _json(semi)}


def _build_manifest(*, actor_employee=None, backup_evidence_path=None, retention_evidence_path=None):
    from .public_stock_activation_backup import validate_activation_backup
    blockers = []
    target = current_cutover_target()
    _capture(blockers, lambda: assert_cutover_target(target))
    control = PublicStockCutoverControl.objects.filter(key="PUBLIC_STOCK").first()
    actor = _capture(blockers, lambda: _actor(actor_employee))
    if control is None or control.state != "MAINTENANCE":
        _block(blockers, "MAINTENANCE_REQUIRED", "首次启用必须处于持久维护状态。")
    if getattr(settings, "PUBLIC_STOCK_FLOW_ENABLED", False) or getattr(settings, "PUBLIC_STOCK_ISSUES_ENABLED", False):
        _block(blockers, "TRIAL_SWITCH_ENABLED", "正式启用前须关闭隔离预演开关，不能以配置绕过启用凭证。")
    for model in (MaterialIssue, MaterialInbound, OutsourcingOrder, MetalProcessingExternalOrder):
        if model.objects.filter(stock_mode="PUBLIC_V2").exists():
            _block(blockers, "PUBLIC_DOCUMENT_BEFORE_ACTIVATION", "现场已存在预演公共单据，不能当作未启用的正式现场。", model=model.__name__)
    backup = _capture(blockers, lambda: validate_activation_backup(backup_evidence_path, target=target, control=control)) if control else None
    boms, limits = _active_boms(blockers)
    manifest = {"schema_version": 1, "operation": OPERATION, "target": target,
        "actor": {"id": str(actor.pk), "employee_code": actor.employee_code} if actor else None,
        "maintenance": {"control_id": str(control.pk), "started_at": control.started_at.isoformat(), "state": control.state} if control else None,
        "backup": backup, "active_schedule_products": boms,
        "opening": _opening(blockers), "legacy_transit": _legacy_transit(blockers),
        "legacy_plans": _legacy_plans(blockers, retention_path=retention_evidence_path, target=target, control=control),
        "quotas": _quotas(blockers, limits, {row["product_id"] for row in boms})}
    manifest = _json(manifest)
    blockers.sort(key=lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True))
    # 阻断项同样参与摘要，避免事实不完整的旧预检被用于后续启用。
    manifest["blockers"] = blockers
    return {"schema_version": 1, "operation": OPERATION, "mode": "DRY_RUN", "read_only": True,
        "applied": False, "ready": not blockers, "authorization_required": True,
        "manifest": manifest, "manifest_sha256": digest(manifest), "blockers": blockers,
        "summary": {"active_schedule_product_count": len(boms), "blocker_count": len(blockers)}}


def build_public_stock_activation_manifest(**kwargs):
    """顶层只读一致快照；不能嵌入已读取过现场的写事务冒充只读检查。"""
    if connection.in_atomic_block:
        _fail("READ_ONLY_TRANSACTION_REQUIRED", "请在独立顶层只读事务运行启用预检。")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return _build_manifest(**kwargs)


def _lock_fact_tables():
    names = sorted({model._meta.db_table for model in apps.get_models()
                    if model._meta.app_label in LOCKED_APPS and model._meta.managed and not model._meta.proxy})
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '10s'")
        cursor.execute("LOCK TABLE " + ", ".join(connection.ops.quote_name(name) for name in names)
                       + " IN SHARE ROW EXCLUSIVE MODE")


def apply_public_stock_activation(*, actor_employee, expected_target, expected_manifest_sha256,
        expected_control_id, request_id, authorization_path, backup_evidence_path, retention_evidence_path=None):
    if connection.in_atomic_block:
        _fail("ACTIVATION_TOP_LEVEL_REQUIRED", "启用必须在独立顶层事务执行，不能沿用已有事务的旧快照。")
    if (not isinstance(expected_target, dict) or set(expected_target) != {"host", "database", "system_identifier"}
            or not all(isinstance(value, str) and value.strip() for value in expected_target.values())):
        _fail("EXPECTED_TARGET_REQUIRED", "启用须明确提供主机、数据库和真实实例标识。")
    if not isinstance(expected_manifest_sha256, str) or not HASH_PATTERN.fullmatch(expected_manifest_sha256):
        _fail("EXPECTED_MANIFEST_REQUIRED", "执行须提供已审阅清单的完整 SHA-256。")
    try:
        request_id, expected_control_id = UUID(str(request_id)), UUID(str(expected_control_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise PublicStockActivationError("REQUEST_INVALID", "请求 ID 和维护会话 ID 必须有效。") from error
    authorization = _load_evidence(authorization_path, "明确启用授权凭证")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        lock_stock_writes(exclusive=True)
        _lock_fact_tables()
        target = assert_cutover_target(expected_target)
        actor = _actor(actor_employee)
        control = PublicStockCutoverControl.objects.select_for_update().filter(key="PUBLIC_STOCK").first()
        if control is None or control.pk != expected_control_id:
            _fail("MAINTENANCE_SESSION_CHANGED", "启用目标的维护会话与已审阅会话不一致。")
        _confirmed(authorization, OPERATION, target, control)
        if (authorization.get("manifest_sha256") != expected_manifest_sha256
                or authorization.get("request_id") != str(request_id)
                or authorization.get("actor_employee_id") != str(actor.pk)):
            _fail("AUTHORIZATION_INVALID", "明确授权须绑定本请求、操作管理员及已审阅清单摘要。")
        request_hash = digest({"request_id": str(request_id), "authorization": authorization,
            "target": target, "actor_id": str(actor.pk), "manifest_sha256": expected_manifest_sha256,
            "control_id": str(control.pk), "backup_evidence_path": str(Path(backup_evidence_path).resolve()),
            "retention_evidence_path": str(Path(retention_evidence_path).resolve()) if retention_evidence_path else None})
        prior = list(AuditLog.objects.filter(object_type=AUDIT_TYPE, object_id=control.pk, action=ACTION).order_by("id"))
        if prior:
            saved = prior[0].after_data
            if (len(prior) != 1 or control.state != "PUBLIC" or control.activation_manifest_sha256 != expected_manifest_sha256
                    or saved.get("request_id") != str(request_id) or saved.get("request_hash") != request_hash):
                _fail("ACTIVATION_REQUEST_CONFLICT", "已启用状态与请求或授权内容冲突，不能覆盖原凭证。")
            return {"applied": True, "replayed": True, "state": "PUBLIC", "audit_id": str(prior[0].pk),
                    "manifest_sha256": expected_manifest_sha256, "business_writes": 0}
        if control.state != "MAINTENANCE" or control.activated_at is not None or control.activation_manifest_sha256:
            _fail("ACTIVATION_STATE_INVALID", "维护状态或历史启用字段异常，不能首次启用。")
        report = _build_manifest(actor_employee=actor, backup_evidence_path=backup_evidence_path,
                                 retention_evidence_path=retention_evidence_path)
        if report["manifest_sha256"] != expected_manifest_sha256:
            raise PublicStockActivationError("ACTIVATION_MANIFEST_STALE", "现场事实已变化，请重新只读预检和审阅。", report=report)
        if not report["ready"]:
            raise PublicStockActivationError("ACTIVATION_BLOCKED", "启用清单仍有阻断项，保持维护状态。", report=report)
        control.state, control.activated_at, control.activated_by = "PUBLIC", timezone.now(), actor
        control.activation_manifest_sha256 = expected_manifest_sha256
        control.save(update_fields=["state", "activated_at", "activated_by", "activation_manifest_sha256", "updated_at"])
        audit = AuditLog.objects.create(actor_employee=actor, actor_employee_code_snapshot=actor.employee_code,
            actor_name_snapshot=actor.display_name, object_type=AUDIT_TYPE, object_id=control.pk, action=ACTION,
            occurred_at=control.activated_at, after_data={"state": "PUBLIC", "request_id": str(request_id),
                "request_hash": request_hash, "authorization": authorization, "manifest": report["manifest"],
                "manifest_sha256": expected_manifest_sha256})
        return {"applied": True, "replayed": False, "state": "PUBLIC", "audit_id": str(audit.pk),
                "manifest_sha256": expected_manifest_sha256, "business_writes": 0}
