"""旧金工在途件接续：只保存证据，不更改旧单、原出库或当前库存。"""

import copy
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.auth import active_employee_for
from apps.inventory.public_bom_snapshot import build_output_identity, freeze_bom_line
from apps.inventory.public_stock_identity import validate_public_identity
from apps.organizations.models import Employee
from apps.outsourcing.models import OutsourcingDispatch, OutsourcingOrder, OutsourcingReturnLine
from apps.outsourcing.selectors import accessible_outsourcing_orders
from apps.reference_data.models import TubeCoatingColor

from .models import (
    MaterialIssue, MaterialIssueLine, MetalProcessingExternalOrder,
    MetalProcessingOriginalHandoff, MetalProcessingSource, OriginalHandoffPublicTransition,
)
from .processing_selectors import digest, frozen_source, processing_lines


def evidence_digest(value):
    return hashlib.sha256(json.dumps(value, cls=DjangoJSONEncoder, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _fail(message):
    raise ValidationError({"transition": message})


def _require_actor(actor):
    current = Employee.objects.select_related("user").filter(pk=getattr(actor, "pk", None)).first()
    if (current is None or active_employee_for(current.user) is None
            or not current.user.has_perm("material_issues.apply_originalhandoffpublictransition")):
        raise PermissionDenied("仅有效员工且具有旧单接续权限才能执行维护期接续。")
    return current


def _manifest_candidates(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        _fail("接续清单格式或版本无效。")
    candidates = manifest.get("candidates")
    if not isinstance(candidates, list) or not candidates or any(not isinstance(row, dict) for row in candidates):
        _fail("接续清单必须包含完整候选明细。")
    if manifest.get("candidate_manifest_sha256") != evidence_digest(candidates):
        _fail("候选清单摘要不符。")
    ids = [row.get("original_handoff_id") for row in candidates]
    try:
        for value in [manifest["order_id"], manifest["issue_id"], *ids]:
            UUID(str(value))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValidationError({"transition": "清单单据或交接编号无效。"}) from exc
    if len(set(ids)) != len(ids) or manifest.get("candidate_count") != len(ids):
        _fail("清单重复交接或明细总数不符。")
    if (manifest.get("color_is_newly_selected_not_historical_evidence") is not True
            or not str(manifest.get("user_instruction", "")).strip()
            or not str(manifest.get("authorization_scope", "")).strip()):
        _fail("必须保留颜色为本次授权补充值的声明、原指令及适用范围。")
    return candidates


def _historical_pipe_attributes(row):
    """比较结构字段，不从自由规格文字推导管形或壁厚。"""
    fields = ("category", "part_name", "material", "specification", "unit", "hardness",
              "cutting_length_mm", "pieces_per_bar", "raw_bar_length_m", "component_identity")
    raw_fields = ("tube_shape", "tube_diameter", "tube_thickness")
    if (not isinstance(row, dict) or any(key not in row for key in fields)
            or not isinstance(row.get("raw_values"), dict)
            or any(not str(row["raw_values"].get(key) or "").strip() for key in raw_fields)):
        _fail("历史变更缺少完整管材结构属性，无法证明原实物身份。")
    return {**{key: row[key] for key in fields},
            "raw_values": {key: row["raw_values"][key] for key in raw_fields}}


def _supplemental_confirmation(manifest, candidates):
    """本次补证单独留痕；它不能改写历史或扩大原清单范围。"""
    confirmation = manifest.get("supplemental_confirmation")
    if confirmation is None:
        if "supplemental_confirmation_sha256" in manifest:
            _fail("补充确认摘要缺少对应凭证。")
        return None
    fields = {"schema_version", "confirmation_id", "recorded_at", "confirmed_on", "confirmed",
              "user_answer", "question", "statement", "confirms_current_physical_attributes_not_historical_fact",
              "scope", "items"}
    if (not isinstance(confirmation, dict) or set(confirmation) != fields
            or type(confirmation.get("schema_version")) is not int or confirmation["schema_version"] != 1
            or confirmation.get("confirmed") is not True or confirmation.get("user_answer") != "A"
            or confirmation.get("confirms_current_physical_attributes_not_historical_fact") is not True
            or not isinstance(confirmation.get("question"), str) or not confirmation["question"].strip()
            or not isinstance(confirmation.get("statement"), str)
            or not confirmation["statement"].startswith("本次补充确认，不宣称旧审计完整")):
        _fail("补充确认必须保留明确同意、原问题及本次补证而非历史事实的声明。")
    if manifest.get("supplemental_confirmation_sha256") != evidence_digest(confirmation):
        _fail("补充确认凭证摘要不符。")
    try:
        UUID(confirmation["confirmation_id"])
        recorded_at = datetime.fromisoformat(confirmation["recorded_at"])
        confirmed_on = date.fromisoformat(confirmation["confirmed_on"])
        if (timezone.is_naive(recorded_at) or recorded_at > timezone.now()
                or confirmed_on > timezone.localtime(recorded_at).date()
                or confirmation["confirmed_on"] != confirmed_on.isoformat()):
            _fail("补充确认记录时间、确认日期或时区无效。")
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError({"transition": "补充确认编号、记录时间或确认日期无效。"}) from exc
    if confirmation["scope"] != {key: manifest[key] for key in ("issue_id", "order_id", "candidate_manifest_sha256")}:
        _fail("补充确认只能用于其绑定的领料单、原外发单及完整候选摘要。")
    expected = {}
    try:
        for candidate in candidates:
            frozen_line = candidate["frozen_candidate"]["line"]
            raw = frozen_line["raw_values"]
            expected[candidate["original_handoff_id"]] = {
                "original_handoff_id": candidate["original_handoff_id"], "source_id": candidate["source_id"],
                "issued_bom_line_id": candidate["bom_line_id"],
                "cutting_length_mm": frozen_line["cutting_length_mm"], "material": frozen_line["material"],
                **{key: raw[key] for key in ("tube_shape", "tube_diameter", "tube_thickness")}}
    except (KeyError, TypeError) as exc:
        raise ValidationError({"transition": "补充确认对应的候选实物属性不完整。"}) from exc
    items = confirmation["items"]
    if not isinstance(items, list) or len(items) != len(expected):
        _fail("补充确认必须逐项覆盖全部候选，不得缺项或增加交接。")
    seen = set()
    for item in items:
        handoff_id = item.get("original_handoff_id") if isinstance(item, dict) else None
        if (not isinstance(handoff_id, str) or handoff_id in seen or handoff_id not in expected
                or evidence_digest(item) != evidence_digest(expected[handoff_id])):
            _fail("补充确认存在重复、越界或不匹配的交接、部位、切割长度或实物属性。")
        seen.add(handoff_id)
    return confirmation


def _summary_only_bom_update(audit):
    """仅识别现有 BOM 编辑日志的汇总结构；未知或含部位属性的日志仍拒绝。"""
    allowed = {"status", "section_count", "line_count", "sections"}
    section_fields = {"id", "section_type", "title", "line_count"}
    if audit.object_type != "BOM" or audit.action != "UPDATE":
        return False
    for value in (audit.before_data, audit.after_data):
        if not isinstance(value, dict) or "line_count" not in value or not set(value).issubset(allowed):
            return False
        sections = value.get("sections", [])
        if not isinstance(sections, list) or any(not isinstance(row, dict) or not set(row).issubset(section_fields) for row in sections):
            return False
    return True


def _bind_historical_identity(line, historical, audit, conversion, confirmation=None, candidate=None):
    """原几何摘要不等于实物版本；同时核对审计连续性和实际出库批次。"""
    attributes = _historical_pipe_attributes(historical)
    # 管材旧 source_revision_hash 只覆盖 pipe_plan + 原料/部位 ID，不能证明材质未变。
    revision_snapshot = {key: value for key, value in conversion.items()
                         if key not in {"kind", "part_name", "source_revision_hash"}}
    if digest(revision_snapshot) != conversion["source_revision_hash"]:
        _fail("原领料换算版本摘要与冻结参数不一致。")
    later_audits = AuditLog.objects.filter(
        Q(object_type="BOM", object_id=conversion["bom_id"])
        | Q(object_id=conversion["bom_line_id"]),
        occurred_at__gte=audit.occurred_at, occurred_at__lte=line.issue.issued_at,
    ).exclude(pk=audit.pk).order_by("occurred_at", "id")
    chain, gaps = [], []
    if confirmation is not None and date.fromisoformat(confirmation["confirmed_on"]) < timezone.localtime(line.issue.issued_at).date():
        _fail("本次补充确认日期不能早于原领料日期。")
    for later in later_audits:
        before, after = later.before_data, later.after_data
        # 仅此已知操作只写状态；其他未知动作或只存统计的 UPDATE 一律不能证明行未改。
        if (later.action == "VERIFY" and isinstance(before, dict) and isinstance(after, dict)
                and set(before).issubset({"status"})
                and set(after).issubset({"status", "quantity_confirmation_reason"})):
            chain.append({"id": str(later.pk), "action": later.action, "occurred_at": later.occurred_at.isoformat(),
                          "before_data": before, "after_data": after})
            continue
        rows = after.get("lines") if isinstance(after, dict) else None
        matches = [row for row in rows if isinstance(row, dict) and str(row.get("id")) == conversion["bom_line_id"]] if isinstance(rows, list) else []
        if len(matches) != 1:
            if confirmation is not None and _summary_only_bom_update(later):
                gap = {"id": str(later.pk), "object_type": later.object_type, "object_id": str(later.object_id),
                       "action": later.action, "occurred_at": later.occurred_at.isoformat(),
                       "before_data": before, "after_data": after, "continuity_proven": False,
                       "resolution": "CURRENT_USER_PHYSICAL_CONFIRMATION_ONLY"}
                gaps.append(gap)
                chain.append(gap)
                continue
            _fail(f"历史凭证到原领料之间存在不能核验部位属性的变更 {later.pk}，不能唯一证明原实物身份。")
        if _historical_pipe_attributes(matches[0]) != attributes:
            _fail(f"领料前该部位实物属性已经变化（审计 {later.pk}），不能沿用较早历史身份。")
        before_rows = before.get("lines") if isinstance(before, dict) else None
        before_matches = [row for row in before_rows if isinstance(row, dict) and str(row.get("id")) == conversion["bom_line_id"]] if isinstance(before_rows, list) else []
        if any(_historical_pipe_attributes(row) != attributes for row in before_matches):
            _fail(f"领料前该部位实物属性已经变化（审计 {later.pk}），不能以补证覆盖完整冲突凭证。")
        chain.append({"id": str(later.pk), "action": later.action, "occurred_at": later.occurred_at.isoformat(),
                      "line": matches[0], "line_hash": evidence_digest(matches[0])})

    batches = list(line.batch_allocations.select_related("inbound_line").order_by("id"))
    batch_evidence = []
    physical_fields = ("category", "material", "part_name", "specification")
    for batch in batches:
        inbound = batch.inbound_line
        frozen_attributes = {key: getattr(inbound, key + "_snapshot") for key in physical_fields}
        if (inbound.created_at > line.issue.issued_at
                or any(not value or value != historical[key] for key, value in frozen_attributes.items())):
            _fail("历史 BOM 属性与实际领用批次的原入库冻结材质、部位或规格不一致，不能接续。")
        receipt = inbound.calculation_snapshot
        if (not isinstance(receipt, dict)
                or any(str(receipt.get(key)) != str(conversion[key]) for key in (
                    "bom_id", "bom_line_id", "component_identity", "raw_material_id", "cutting_length_mm", "pieces_per_bar", "raw_bar_length_m"))
                or (inbound.raw_material_information_id and str(inbound.raw_material_information_id) != conversion["raw_material_id"])):
            _fail("原实际入库批次的冻结原料和部位换算不能与领料唯一对应。")
        batch_evidence.append({"allocation_id": str(batch.pk), "inbound_line_id": str(inbound.pk),
            "inbound_id": str(inbound.inbound_id), "frozen_attributes": frozen_attributes,
            "calculation_snapshot": receipt, "raw_material_information_id": str(inbound.raw_material_information_id) if inbound.raw_material_information_id else None})
    if not batch_evidence:
        _fail("缺少原实际领用批次的物理身份证据。")
    result = {"method": "CURRENT_PHYSICAL_CONFIRMATION_AND_ISSUED_BATCHES" if gaps else "UNCHANGED_HISTORICAL_LINE_AND_ISSUED_BATCHES", "source_revision_hash": conversion["source_revision_hash"],
            "revision_proves_geometry_only": True, "historical_attributes": attributes,
            "audits_until_issue": chain, "actual_issued_batches": batch_evidence}
    if confirmation is not None:
        result.update(historical_continuity_proven=not gaps, unresolved_historical_gaps=gaps,
            supplemental_confirmation=copy.deepcopy(confirmation), supplemental_confirmation_sha256=evidence_digest(confirmation),
            confirmed_item=next(item for item in confirmation["items"] if item["original_handoff_id"] == candidate["original_handoff_id"]))
    return result


def _verify_candidate(candidate, manifest, handoff, color, confirmation=None):
    from .p4_services import _allocation_for_handoff, original_handoff_totals

    source, order = handoff.source, handoff.original_order
    line = source.issue_line
    frozen = frozen_source(line)
    conversion = frozen["conversion_snapshot"]
    if (line.issue.stock_mode != "LEGACY" or order.stock_mode != "LEGACY"
            or str(order.pk) != manifest["order_id"] or str(line.issue_id) != manifest["issue_id"]
            or order.order_number != manifest.get("order_number")):
        _fail("接续只接受清单内同一旧领料单及旧原外发单。")
    expected = {"issue_line_id": str(line.pk), "source_id": str(source.pk),
        "source_hash": source.source_hash, "bom_line_id": conversion["bom_line_id"],
        "component_identity": conversion["component_identity"],
        "material_number": line.material_number_snapshot,
        "original_handoff_snapshot_hash": evidence_digest(handoff.snapshot),
        "original_conversion_hash": evidence_digest(conversion),
        "issued_pieces": source.issued_pieces, "completed_pieces": source.completed_pieces,
        "handoff_pieces": handoff.handoff_pieces, "original_deducted_roots": frozen["bar_count"],
        "original_deducted_meters": frozen["meters"]}
    if any(candidate.get(key) != value for key, value in expected.items()):
        _fail("领料、交接数量或证据摘要已变化，必须重新预检。")
    if (source.source_hash != digest(frozen) or source.source_snapshot != frozen
            or handoff.snapshot.get("source") != frozen
            or source.issued_pieces != frozen["issued_pieces"]):
        _fail("原领料冻结来源与加工、直接交接证据不一致。")
    all_handed = source.original_handoffs.aggregate(total=Sum("handoff_pieces"))["total"] or 0
    if (all_handed != source.dispatched_pieces or source.reserved_pieces != 0
            or not 0 < source.dispatched_pieces <= source.completed_pieces <= source.issued_pieces):
        _fail("已领、完成、预留及实际交接数量不守恒，不能接续。")
    if order.status not in {"PENDING_DISPATCH", "PROCESSING", "PARTIAL_RETURN", "CLOSED"}:
        _fail("已完成或取消的原外发单不能接续。")
    if order.status == "CLOSED":
        from .original_order_services import original_closure_data
        if original_closure_data(order) is None:
            _fail("已结清原单缺少结清证据。")
    if OutsourcingDispatch.objects.filter(order=order).exists():
        _fail("原外发单混有原料发料，不能按直接交接接续。")
    if MetalProcessingExternalOrder.objects.filter(source=source).exists():
        _fail("来源已存在旧再外发单，须单独核验其在途数量后再接续。")
    allocation = _allocation_for_handoff(handoff)
    item = allocation.processing_item
    if str(item.pk) != candidate.get("processing_item_id") or item.unit_snapshot != "支" or item.unit_id != line.unit_id:
        _fail("原外发部位或按支单位与领料不一致。")
    from .original_order_services import cancelled_pending_pieces
    totals = original_handoff_totals(allocation)
    if (totals["handoff_pieces"] > allocation.allocated_quantity - cancelled_pending_pieces(allocation)
            or totals["returned_pieces"] + totals["returned_unsprayed_pieces"] >= totals["handoff_pieces"]):
        _fail("原订单交接额度不符或已无在途可接续数量。")
    returned = list(OutsourcingReturnLine.objects.filter(allocation=allocation))
    if any(row.quality != "AVAILABLE" or row.returned_quantity != row.returned_quantity.to_integral_value() for row in returned):
        _fail("既有回货包含不良或非整数件，不能按合格支数接续。")
    try:
        audit = AuditLog.objects.get(pk=candidate["historical_audit_id"], object_type="BOM", object_id=conversion["bom_id"])
        path = re.fullmatch(r"after\.lines\[(\d+)\]", candidate["historical_line_path"])
        if path is None:
            _fail("历史审计行路径无效。")
        historical = audit.after_data["lines"][int(path.group(1))]
        if (line.issue.issued_at is None or audit.occurred_at > line.issue.issued_at
                or str(historical["id"]) != conversion["bom_line_id"]
                or evidence_digest(historical) != candidate["historical_line_hash"]):
            _fail("历史审计必须早于领料，且精确对应原部位和冻结摘要。")
        for key in ("cutting_length_mm", "pieces_per_bar", "raw_bar_length_m", "component_identity"):
            if str(historical[key]) != str(conversion[key]):
                _fail("历史审计换算字段与原领料冻结值不一致。")
        identity_binding = _bind_historical_identity(line, historical, audit, conversion, confirmation, candidate)
        raw = copy.deepcopy(historical["raw_values"])
        if (raw.get("tube_coating_color") != candidate.get("historical_color")
                or candidate.get("selected_color") != color.color_name
                or not str(candidate.get("color_origin", "")).strip()):
            _fail("原历史颜色或本次颜色授权证据不一致。")
        raw["tube_coating_color"] = color.color_name
        historical_line = SimpleNamespace(pk=conversion["bom_line_id"],
            section=SimpleNamespace(section_type="PROFILE", title="型材", bom_id=conversion["bom_id"]),
            **{key: historical[key] for key in ("category", "part_name", "material", "specification", "unit", "hardness", "cutting_length_mm")},
            cutting_pieces_per_set=None, raw_values=raw)
        frozen_candidate = freeze_bom_line(historical_line)
        if frozen_candidate != candidate["frozen_candidate"]:
            _fail("候选实物属性不能脱离历史审计及本次颜色授权。")
        if (order.craft_code_snapshot != "POWDER_COATING" or order.craft.craft_type != "EXTERNAL"
                or order.craft.outsourcing_code != "POWDER_COATING"):
            _fail("原单冻结工艺不是喷塑。")
        identity = build_output_identity(frozen_candidate, order.craft, item.unit)
        if validate_public_identity(candidate["candidate_output_identity"]) != identity:
            _fail("公共产物身份与经核验的历史属性不一致。")
    except (AuditLog.DoesNotExist, KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValidationError({"transition": "缺少可核验的历史审计、原属性或颜色证据。"}) from exc
    evidence = {"historical_audit": {"id": str(audit.pk), "object_type": audit.object_type,
        "object_id": str(audit.object_id), "action": audit.action, "occurred_at": audit.occurred_at.isoformat(),
        "before_data": audit.before_data, "after_data": audit.after_data},
        "historical_line": historical, "historical_identity_binding": identity_binding, "candidate": candidate,
        "color_authorization": {key: manifest[key] for key in ("selected_color", "user_instruction", "authorization_scope", "color_is_newly_selected_not_historical_evidence")},
        "original_source": frozen, "original_handoff_snapshot": handoff.snapshot}
    quantity = {**{key: int(value) for key, value in totals.items()}, "source_version": source.version, "order_version": order.version,
        "order_status": order.status, "allocation_id": str(allocation.pk),
        "allocation_quantity": str(allocation.allocated_quantity), "handoff_pieces_this_record": handoff.handoff_pieces,
        "remaining_pieces": int(totals["handoff_pieces"] - totals["returned_pieces"] - totals["returned_unsprayed_pieces"])}
    return {"handoff": handoff, "identity": identity, "evidence": evidence, "quantity": quantity}


def _plan(manifest):
    candidates = _manifest_candidates(manifest)
    confirmation = _supplemental_confirmation(manifest, candidates)
    color_data = manifest.get("selected_color", {})
    color = TubeCoatingColor.objects.filter(pk=color_data.get("id"), color_name=color_data.get("name"), status="ACTIVE", archived_at__isnull=True).first()
    if color is None:
        _fail("授权喷塑色不存在、已停用或已归档。")
    records = list(MetalProcessingOriginalHandoff.objects.filter(pk__in=[row["original_handoff_id"] for row in candidates]).select_related(
        "source__issue_line__issue", "source__issue_line__unit", "original_order__schedule", "original_order__craft", "factory").order_by("id"))
    if len(records) != len(candidates):
        _fail("清单中有不存在的直接交接。")
    indexed = {row["original_handoff_id"]: row for row in candidates}
    checked = [_verify_candidate(indexed[str(row.pk)], manifest, row, color, confirmation) for row in records]
    from .p4_services import _allocation_handoffs, _allocation_for_handoff
    for row in records:
        peers = set(str(value) for value in _allocation_handoffs(_allocation_for_handoff(row)).values_list("id", flat=True))
        if not peers.issubset(indexed):
            _fail("同一加工分配的全部交接必须一次核验接续，不能混用新旧身份。")
    # 同一批已领原料可分多次交接；根米属于唯一领料来源，不能随交接次数重复累计。
    unique_sources = {str(row["handoff"].source_id): row["evidence"]["original_source"] for row in checked}
    if (sum(row["handoff"].handoff_pieces for row in checked) != manifest.get("handoff_total_pieces")
            or sum(source["bar_count"] for source in unique_sources.values()) != manifest.get("original_deducted_roots")
            or sum(Decimal(source["meters"]) for source in unique_sources.values()) != Decimal(str(manifest.get("original_deducted_meters")))):
        _fail("清单支、根、米合计与原实际出库证据不符。")
    if len({row["identity"]["identity_key"] for row in checked}) != manifest.get("unique_identity_count"):
        _fail("不同实物身份数与清单不符。")
    receipt = {"schema_version": 1, "read_only": True, "inventory_effect": "NONE", "stock_writes": 0,
        "candidate_manifest_hash": evidence_digest(manifest), "candidate_count": len(checked),
        "records": [{"original_handoff_id": str(row["handoff"].pk), "public_identity": row["identity"],
            "quantity_snapshot": row["quantity"], "source_hash": row["handoff"].source.source_hash,
            "historical_identity_binding_hash": evidence_digest(row["evidence"]["historical_identity_binding"]),
            "handoff_snapshot_hash": evidence_digest(row["handoff"].snapshot)} for row in checked]}
    receipt["manifest_hash"] = evidence_digest(receipt)
    return receipt, checked


def preview_legacy_public_transition(manifest):
    """严格只读；返回同时覆盖候选、旧证据和当前剩余量的应用摘要。"""
    return _plan(manifest)[0]


@transaction.atomic
def apply_legacy_public_transition(*, manifest, actor, request_id, expected_manifest_hash, request=None):
    from apps.inventory.public_stock_cutover import require_cutover_operator, require_transition_maintenance
    require_transition_maintenance()
    actor = _require_actor(require_cutover_operator(actor))
    try:
        request_id = UUID(str(request_id))
    except (TypeError, ValueError) as exc:
        raise ValidationError({"request_id": "必须提供有效请求标识。"}) from exc
    candidates = _manifest_candidates(manifest)
    _supplemental_confirmation(manifest, candidates)
    request = request or SimpleNamespace(user=actor.user, META={}, request_id=str(request_id))
    if getattr(request, "user", None) != actor.user:
        raise PermissionDenied("请求用户与接续操作员工不一致。")
    ids = sorted(row["original_handoff_id"] for row in candidates)
    request_hash = evidence_digest({"manifest": manifest, "expected_manifest_hash": expected_manifest_hash, "actor_id": str(actor.pk)})
    existing = list(OriginalHandoffPublicTransition.objects.filter(request_id=request_id).order_by("original_handoff_id"))
    if existing:
        if (any(row.request_payload_hash != request_hash for row in existing)
                or sorted(str(row.original_handoff_id) for row in existing) != ids):
            raise Conflict("接续请求标识已用于其他清单、摘要或操作员工。")
        if (not accessible_outsourcing_orders(request).filter(pk=manifest["order_id"]).exists()
                or not processing_lines(request).filter(issue_id=manifest["issue_id"]).exists()):
            raise PermissionDenied("当前员工已无权查看原接续来源。")
        return {"applied": True, "replayed": True, "stock_writes": 0, "transition_ids": [str(row.pk) for row in existing]}
    # 与 P3/P4 原回货保持领料单 → 明细 → 来源 → 原外发单 → 交接锁顺序。
    hints = list(MetalProcessingOriginalHandoff.objects.filter(pk__in=ids).values("source_id", "source__issue_line_id", "source__issue_line__issue_id", "original_order_id"))
    for model, key in ((MaterialIssue, "source__issue_line__issue_id"), (MaterialIssueLine, "source__issue_line_id"),
                       (MetalProcessingSource, "source_id"), (OutsourcingOrder, "original_order_id")):
        list(model.objects.select_for_update().filter(pk__in={row[key] for row in hints}).order_by("id"))
    list(MetalProcessingOriginalHandoff.objects.select_for_update().filter(pk__in=ids).order_by("id"))
    if OriginalHandoffPublicTransition.objects.filter(original_handoff_id__in=ids).exists():
        raise Conflict("清单中的交接已接续，不能用新请求重复采纳。")
    if (processing_lines(request).filter(pk__in={row["source__issue_line_id"] for row in hints}).count() != len({row["source__issue_line_id"] for row in hints})
            or accessible_outsourcing_orders(request).filter(pk=manifest["order_id"]).count() != 1):
        raise PermissionDenied("清单包含当前员工不可见的领料或外发来源。")
    receipt, checked = _plan(manifest)
    if not expected_manifest_hash or expected_manifest_hash != receipt["manifest_hash"]:
        raise Conflict("预检摘要与当前证据、版本或回货剩余量不符，请重新只读预检。")
    transitions = []
    for row in checked:
        handoff = row["handoff"]
        record = OriginalHandoffPublicTransition.objects.create(original_handoff=handoff,
            source_hash=handoff.source.source_hash, handoff_snapshot_hash=evidence_digest(handoff.snapshot),
            manifest_hash=receipt["manifest_hash"], public_identity=row["identity"], evidence=row["evidence"],
            quantity_snapshot=row["quantity"], actor_employee=actor, request_id=request_id, request_payload_hash=request_hash)
        audit_request = SimpleNamespace(request_id=str(request_id), META=getattr(request, "META", {}))
        write_audit_log(object_type="METAL_HANDOFF_PUBLIC_TRANSITION", object_id=record.pk,
            context_type="OUTSOURCING_ORDER", context_id=handoff.original_order_id, action="ADOPTED",
            actor_employee=actor, after_data={"manifest_hash": receipt["manifest_hash"],
                "original_handoff_id": str(handoff.pk), "public_identity": row["identity"],
                "quantity_snapshot": row["quantity"], "inventory_effect": "NONE"}, request=audit_request)
        transitions.append(str(record.pk))
    return {"applied": True, "replayed": False, "stock_writes": 0, "manifest_hash": receipt["manifest_hash"], "transition_ids": transitions}


def trusted_handoff_transition(handoff):
    """每次使用都核验旧冻结证据；绝不从当前 BOM 补属性。"""
    transition = OriginalHandoffPublicTransition.objects.filter(original_handoff_id=handoff.pk).first()
    if transition is None:
        return None
    source = handoff.source
    if (handoff.original_order.stock_mode != "LEGACY" or source.issue_line.issue.stock_mode != "LEGACY"
            or transition.source_hash != source.source_hash
            or source.source_hash != digest(frozen_source(source.issue_line))
            or source.source_snapshot != transition.evidence.get("original_source")
            or transition.handoff_snapshot_hash != evidence_digest(handoff.snapshot)
            or transition.evidence.get("original_handoff_snapshot") != handoff.snapshot
            or transition.quantity_snapshot.get("handoff_pieces_this_record") != handoff.handoff_pieces):
        raise Conflict("已接续交接的原冻结证据已变化，禁止回货入库。")
    identity = validate_public_identity(transition.public_identity)
    if identity != transition.evidence.get("candidate", {}).get("candidate_output_identity"):
        raise Conflict("接续身份与保存的授权证据不一致。")
    return transition


def require_original_handoff_mode(order, handoffs):
    from apps.inventory.public_stock_mode import require_document_stock_mode, require_transition_stock_mode
    transitions = [trusted_handoff_transition(row) for row in handoffs]
    if any(transitions):
        if not transitions or not all(transitions) or order.stock_mode != "LEGACY":
            raise Conflict("同一分配存在未接续交接，不能合并回公共库存。")
        return require_transition_stock_mode()
    return require_document_stock_mode(order)
