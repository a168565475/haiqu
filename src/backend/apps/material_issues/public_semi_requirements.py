"""接收订单的公共半成品额度；只按 BOM 实物匹配，不追溯采购批次。"""

from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from uuid import UUID, uuid5

from django.db import transaction
from django.db.models import Sum

from apps.boms.material_flow_calculations import MaterialFlowValueError, decimal_quantity, positive_integer
from apps.boms.models import Bom, BomLine
from apps.boms.material_attributes import bom_attribute_fields
from apps.inventory.models import PublicStockBalance
from apps.inventory.public_stock_identity import build_semi_finished_identity, validate_public_identity
from apps.inventory.stock_services import InventoryStockValidationError
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft

from .models import MaterialIssueLine, OrderSemiFinishedRequirement


SEMI_REQUIREMENT_NAMESPACE = UUID("c12c9377-ddc0-47b5-a401-8b8272ec9402")
ZERO = Decimal("0")


def _error(code, detail, **meta):
    raise InventoryStockValidationError({"detail": detail}, code=code, meta=meta)


def _blocker(code, detail, *, line=None, requirement_id=None):
    return {"code": code, "detail": detail, "section_code": "SEMI",
            "bom_line_id": str(line.pk) if line else None,
            "requirement_id": str(requirement_id) if requirement_id else None}


def _identifier(task_id, product_id, component_id, craft_id):
    return uuid5(SEMI_REQUIREMENT_NAMESPACE, f"{task_id}:{product_id}:{component_id}:{craft_id}")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def public_semi_identity(requirement):
    return validate_public_identity({
        "stock_kind": "SEMI", "identity_key": requirement.identity_key,
        "identity_snapshot": requirement.identity_snapshot, "raw_material_id": None,
        "raw_bar_length_m": None, "unit_id": str(requirement.unit_id),
    })


def _legacy_history(task_id, product_id, *, exclude_issue_id=None):
    """按接收单据继承数量。此处不拿旧 BOM 重算库存实物身份。"""
    rows = MaterialIssueLine.objects.filter(
        issue__production_task_id=task_id, issue__product_line_id=product_id,
        issue__status__in=["ISSUED", "PENDING_REVIEW"], line_type="SEMI", semi_requirement__isnull=True,
    ).select_related("issue", "semi_finished_balance__bom_line", "semi_finished_balance__completed_craft", "semi_finished_balance__unit")
    history = defaultdict(lambda: {"issued": ZERO, "pending": ZERO, "issued_rows": {}, "unit_id": None})
    blockers = []
    for line in rows:
        balance = line.semi_finished_balance
        snapshot = line.conversion_snapshot
        if balance is None or not isinstance(snapshot, dict):
            blockers.append(_blocker("SEMI_LEGACY_HISTORY_UNRESOLVED", f"历史领料行 {line.pk} 缺少可核实的部位和工艺。"))
            continue
        if balance.production_task_id != task_id or balance.product_line_id != product_id:
            blockers.append(_blocker("SEMI_LEGACY_HISTORY_UNRESOLVED", f"历史领料行 {line.pk} 的接收订单与旧半成品来源不一致。"))
            continue
        try:
            component = UUID(str(snapshot.get("component_identity") or balance.bom_line.component_identity))
        except (ValueError, TypeError, AttributeError):
            blockers.append(_blocker("SEMI_LEGACY_HISTORY_UNRESOLVED", f"历史领料行 {line.pk} 部位编号不正确。"))
            continue
        requirement_id = _identifier(task_id, product_id, component, balance.completed_craft_id)
        if (component != balance.bom_line.component_identity or line.unit_id != balance.unit_id
                or line.unit_snapshot != balance.unit.unit_name):
            blockers.append(_blocker("SEMI_LEGACY_HISTORY_UNRESOLVED", f"历史领料行 {line.pk} 部位或单位存在冲突。", requirement_id=requirement_id))
            continue
        value = line.issued_quantity if line.issue.status == "ISSUED" else line.requested_quantity
        if value is None or not value.is_finite() or value <= 0 or value != value.to_integral_value():
            blockers.append(_blocker("SEMI_LEGACY_HISTORY_UNRESOLVED", f"历史领料行 {line.pk} 缺少准确的整数支／套实发数量。", requirement_id=requirement_id))
            continue
        item = history[(component, balance.completed_craft_id)]
        if item["unit_id"] is not None and item["unit_id"] != line.unit_id:
            blockers.append(_blocker("SEMI_LEGACY_HISTORY_UNRESOLVED",
                                     f"历史领料行 {line.pk} 与同部位同工艺的单位不一致。",
                                     requirement_id=requirement_id))
            continue
        item["unit_id"] = line.unit_id
        if line.issue.status == "ISSUED":
            item["issued"] += value
            item["issued_rows"][str(line.pk)] = str(value)
        elif line.issue_id != exclude_issue_id:
            item["pending"] += value
    return history, blockers


def legacy_pending_semi_quantities(requirements, exclude_issue_id=None):
    grouped = defaultdict(list)
    for requirement in requirements:
        grouped[(requirement.production_task_id, requirement.product_line_id)].append(requirement)
    result = {}
    for (task_id, product_id), items in grouped.items():
        history, blockers = _legacy_history(task_id, product_id, exclude_issue_id=exclude_issue_id)
        if blockers:
            _error("SEMI_LEGACY_HISTORY_UNRESOLVED", "历史半成品领用无法可靠继承。", blockers=blockers)
        for requirement in items:
            result[requirement.pk] = history[(requirement.component_identity, requirement.completed_craft_id)]["pending"]
    return result


def _semi_kind(line):
    if line.section.section_type == "PROFILE":
        return "PIPE"
    if line.section.section_type == "FABRIC" and line.section.title.strip() == "裁剪明细":
        return "CUTTING"
    if line.section.section_type == "ACCESSORY" and line.section.title.strip() == "五金件":
        return "HARDWARE"
    return None


def _net_quantity(line, order_quantity):
    kind = _semi_kind(line)
    if kind == "PIPE":
        usage = positive_integer(line.pieces_per_product, "pieces_per_product")
        quantity = positive_integer(order_quantity, "order_quantity") * usage
        basis = {"field": "pieces_per_product", "value": str(usage)}
    elif kind == "CUTTING":
        usage = positive_integer(line.cutting_sets_per_product, "cutting_sets_per_product")
        quantity = positive_integer(order_quantity, "order_quantity") * usage
        basis = {"field": "cutting_sets_per_product", "value": str(usage)}
    else:
        usage = decimal_quantity(line.unit_consumption, "unit_consumption")
        quantity = positive_integer(order_quantity, "order_quantity") * usage
        basis = {"field": "unit_consumption", "value": str(usage)}
    quantity = Decimal(positive_integer(quantity, "required_quantity"))
    return quantity, {"kind": "NET_SEMI_DEMAND", "order_quantity": str(order_quantity),
                      "usage": basis, "required_quantity": str(quantity), "extra_allowance_applied": False}


def _public_balances():
    return PublicStockBalance.objects.filter(
        stock_kind="SEMI", quality="AVAILABLE", zone__status="ACTIVE",
        zone__warehouse__status="ACTIVE", zone__warehouse__warehouse_type="SEMI_FINISHED",
        unit__status="ACTIVE", unit__archived_at__isnull=True,
    )


def _effective_issued(current, legacy):
    if current is None:
        return legacy["issued"]
    previous = current.source_snapshot
    if not isinstance(previous, dict):
        _error("SEMI_LEGACY_HISTORY_UNRESOLVED", "半成品额度缺少历史继承快照。")
    previous_rows = previous.get("legacy_issued_rows", {})
    if not isinstance(previous_rows, dict) or any(legacy["issued_rows"].get(key) != value for key, value in previous_rows.items()):
        _error("SEMI_LEGACY_HISTORY_CHANGED", "已经继承的历史实发记录发生变化，不能重算或清零额度。")
    try:
        inherited = decimal_quantity(previous.get("legacy_issued_quantity", "0"), "legacy_issued_quantity", allow_zero=True)
    except MaterialFlowValueError:
        _error("SEMI_LEGACY_HISTORY_UNRESOLVED", "历史已领继承数量格式不正确。")
    if inherited > legacy["issued"] or current.internal_issued_quantity < inherited:
        _error("SEMI_LEGACY_HISTORY_CHANGED", "历史实发数量小于已继承记录，不能减少已领额度。")
    return current.internal_issued_quantity + legacy["issued"] - inherited


def build_public_semi_specs(task_id, product_id, *, exclude_issue_id=None):
    """只读构造当前接收产品的半成品需求，不因打开页面写入额度。"""
    try:
        task_id, product_id = UUID(str(task_id)), UUID(str(product_id))
        exclude_issue_id = UUID(str(exclude_issue_id)) if exclude_issue_id else None
    except (ValueError, TypeError, AttributeError):
        return [], [_blocker("PRODUCT_SCOPE_INVALID", "接收订单、产品或领料单编号格式不正确。")]
    product = ProductionTaskProduct.objects.filter(pk=product_id, production_task_id=task_id).first()
    if product is None:
        return [], [_blocker("PRODUCT_SCOPE_INVALID", "所选产品不属于当前接收订单。")]
    bom = Bom.objects.filter(product_line_id=product_id, production_task_id=task_id,
                             archived_at__isnull=True).order_by("-version_number", "-id").first()
    if bom is None or bom.status != "VERIFIED":
        return [], [_blocker("BOM_NOT_VERIFIED", "半成品领用需使用本产品最新已确认 BOM。")]
    if Decimal(product.quantity) != bom.order_quantity:
        return [], [_blocker("BOM_QUANTITY_STALE", "订单数量与已确认 BOM 不一致。")]
    lines = list(BomLine.objects.filter(section__bom=bom).select_related(
        "section", "fabric_source_line__section").order_by("section__line_number", "line_number", "id"))
    existing = list(OrderSemiFinishedRequirement.objects.filter(production_task_id=task_id, product_line_id=product_id)
                    .select_related("completed_craft", "unit"))
    current_by_id = {item.pk: item for item in existing}
    existing_pending = {item["semi_requirement_id"]: item["total"] for item in MaterialIssueLine.objects.filter(
        issue__status="PENDING_REVIEW", semi_requirement_id__in=list(current_by_id)).values("semi_requirement_id").annotate(total=Sum("requested_quantity"))}
    history, blockers = _legacy_history(task_id, product_id, exclude_issue_id=exclude_issue_id)
    # 只读公共库存的工艺/单位维度；不查来源订单，不为每一条 BOM 查询库存。
    raw_dimensions = list(_public_balances().order_by().values_list(
        "identity_snapshot__semi_kind", "identity_snapshot__completed_craft__id", "unit_id").distinct())
    # 旧领料历史即使所属工艺当前没有公共库存，也必须参与同部位额度。
    kinds_by_component = {line.component_identity: _semi_kind(line) for line in lines}
    for (component, craft_id), item in history.items():
        kind = kinds_by_component.get(component)
        if kind and item["unit_id"]:
            raw_dimensions.append((kind, str(craft_id), item["unit_id"]))
    for item in existing:
        if not isinstance(item.identity_snapshot, dict):
            blockers.append(_blocker("PUBLIC_STOCK_IDENTITY_INVALID", "已保存半成品需求的实物快照格式不正确。", requirement_id=item.pk))
            continue
        raw_dimensions.append((item.identity_snapshot.get("semi_kind"), str(item.completed_craft_id), item.unit_id))
    dimensions = set()
    for kind, craft_id, unit_id in raw_dimensions:
        if not isinstance(kind, str) or not isinstance(craft_id, str):
            blockers.append(_blocker("PUBLIC_STOCK_IDENTITY_INVALID", "公共库存种类或工艺快照格式不正确。"))
            continue
        dimensions.add((kind, craft_id, unit_id))
    craft_ids = []
    for _, craft_id, _ in dimensions:
        try:
            craft_ids.append(UUID(str(craft_id)))
        except (ValueError, TypeError, AttributeError):
            blockers.append(_blocker("PUBLIC_STOCK_IDENTITY_INVALID", "公共库存中存在无效的已完成工艺编号。"))
    crafts = Craft.objects.in_bulk(craft_ids)
    units = ProductionUnit.objects.filter(pk__in=[item[2] for item in dimensions], status="ACTIVE", archived_at__isnull=True).in_bulk()
    for item in existing:
        if item.unit_id not in units or item.completed_craft_id not in crafts:
            blockers.append(_blocker("SEMI_REQUIREMENT_CONTEXT_UNAVAILABLE", "已保存半成品需求的单位已停用，或已完成工艺不存在。", requirement_id=item.pk))
    grouped_dimensions = defaultdict(list)
    for kind, craft_id, unit_id in sorted(dimensions, key=lambda item: tuple(str(value) for value in item)):
        try:
            craft = crafts.get(UUID(str(craft_id)))
        except (ValueError, TypeError, AttributeError):
            continue
        unit = units.get(unit_id)
        if craft and unit:
            grouped_dimensions[kind].append((craft, unit))
    counts = defaultdict(int)
    for line in lines:
        counts[line.component_identity] += 1
    specs = []
    seen_specs = {}
    material_cache = {}
    for line in lines:
        kind = _semi_kind(line)
        if kind is None:
            continue
        for craft, unit in grouped_dimensions[kind]:
            requirement_id = _identifier(task_id, product_id, line.component_identity, craft.pk)
            try:
                if counts[line.component_identity] != 1:
                    _error("COMPONENT_IDENTITY_DUPLICATE", "同一 BOM 的部位编号重复，不能分配两份额度。")
                identity = build_semi_finished_identity(bom_line=line, completed_craft=craft, unit=unit,
                                                        material_cache=material_cache)
                quantity, calculation = _net_quantity(line, bom.order_quantity)
                legacy = history[(line.component_identity, craft.pk)]
                current = current_by_id.get(requirement_id)
                issued = _effective_issued(current, legacy)
                if current and (issued > 0 or existing_pending.get(requirement_id, ZERO) > 0 or legacy["pending"] > 0) and (
                        current.identity_key != identity["identity_key"] or current.identity_snapshot != identity["identity_snapshot"]):
                    _error("SOURCE_CHANGED", "该部位已有半成品领用或待审核占用，不能改换实物属性后重建额度。")
                if issued > quantity:
                    _error("REQUIREMENT_BELOW_ISSUED", "本订单半成品净需求低于历史已领数量。")
                revision_source = {"schema_version": 1, "bom_id": str(bom.pk), "bom_line_id": str(line.pk),
                    "bom_version": bom.version_number, "component_identity": str(line.component_identity),
                    "public_identity": identity, "calculation": calculation}
                source = {**revision_source, "legacy_issued_quantity": str(legacy["issued"]),
                          "legacy_issued_rows": legacy["issued_rows"]}
                if requirement_id in seen_specs:
                    if seen_specs[requirement_id] != identity["identity_key"]:
                        _error("SEMI_UNIT_AMBIGUOUS", "同一部位和工艺匹配到不同流转单位，不能生成重复额度。")
                    continue
                seen_specs[requirement_id] = identity["identity_key"]
                specs.append({"id": requirement_id, "production_task_id": task_id, "product_line_id": product_id,
                    "component_identity": line.component_identity, "bom_line": line, "bom": bom,
                    "completed_craft": craft, "unit": unit, "identity": identity, "source_snapshot": source,
                    "source_revision_hash": _hash(revision_source), "required_quantity": quantity,
                    "internal_issued_quantity": issued, "legacy_pending_quantity": legacy["pending"]})
            except (InventoryStockValidationError, MaterialFlowValueError) as error:
                blockers.append(_blocker(getattr(error, "api_error_code", getattr(error, "code", "SEMI_REQUIREMENT_INVALID")),
                                         str(error), line=line, requirement_id=requirement_id))
    components = set(counts)
    for item in existing:
        legacy = history[(item.component_identity, item.completed_craft_id)]
        if item.component_identity not in components and (item.internal_issued_quantity > 0 or legacy["issued"] > 0 or legacy["pending"] > 0):
            blockers.append(_blocker("REQUIREMENT_REMOVED_AFTER_ISSUE", "最新 BOM 删除了已有半成品领用或待审核占用的部位。", requirement_id=item.pk))
    for (component, craft_id), item in history.items():
        if component not in components and (item["issued"] > 0 or item["pending"] > 0):
            blockers.append(_blocker("SEMI_LEGACY_HISTORY_UNRESOLVED", "历史半成品领用部位无法关联到接收订单当前 BOM，不能另给新额度。"))
    return specs, blockers


def public_semi_requirement_rows(task_id, product_id, exclude_issue_id=None):
    specs, blockers = build_public_semi_specs(task_id, product_id, exclude_issue_id=exclude_issue_id)
    ids = [item["id"] for item in specs]
    pending_query = MaterialIssueLine.objects.filter(issue__status="PENDING_REVIEW", semi_requirement_id__in=ids)
    if exclude_issue_id:
        pending_query = pending_query.exclude(issue_id=exclude_issue_id)
    pending = {item["semi_requirement_id"]: item["total"] for item in pending_query.values("semi_requirement_id").annotate(total=Sum("requested_quantity"))}
    balances = list(_public_balances().filter(identity_key__in=[item["identity"]["identity_key"] for item in specs]).select_related("unit", "zone__warehouse"))
    stock_by_key = defaultdict(lambda: {"quantity": ZERO, "zones": []})
    expected = {item["identity"]["identity_key"]: item["identity"]["identity_snapshot"] for item in specs}
    for balance in balances:
        if balance.identity_snapshot != expected[balance.identity_key] or str(balance.unit_id) != balance.identity_snapshot.get("unit_id"):
            blockers.append(_blocker("PUBLIC_STOCK_IDENTITY_CONFLICT", f"公共余额 {balance.pk} 属性与索引不一致。"))
            continue
        group = stock_by_key[balance.identity_key]
        group["quantity"] += balance.quantity
        name = f"{balance.zone.warehouse.warehouse_name} / {balance.zone.zone_name}"
        if name not in group["zones"]:
            group["zones"].append(name)
    # 公共库存占用必须统计所有接收订单，不能只扣当前订单的待审核数量。
    public_pending_query = MaterialIssueLine.objects.filter(issue__status="PENDING_REVIEW",
        semi_requirement__identity_key__in=list(expected))
    if exclude_issue_id:
        public_pending_query = public_pending_query.exclude(issue_id=exclude_issue_id)
    public_pending = {item["semi_requirement__identity_key"]: item["total"] for item in public_pending_query.values("semi_requirement__identity_key").annotate(total=Sum("requested_quantity"))}
    component_totals = defaultdict(lambda: {
        "required": ZERO, "internal_issued": ZERO, "pending": ZERO,
    })
    for spec in specs:
        key = (str(spec["component_identity"]), str(spec["unit"].pk))
        total = component_totals[key]
        # 同一 BOM 部位可能同时有金工和喷塑两个公共半成品状态，
        # 订单需求只计算一次；已领和待审则按各工艺实际占用合计。
        total["required"] = max(total["required"], spec["required_quantity"])
        total["internal_issued"] += spec["internal_issued_quantity"]
        total["pending"] += pending.get(spec["id"], ZERO) + spec["legacy_pending_quantity"]

    rows = []
    for spec in specs:
        identity = spec["identity"]
        snapshot = identity["identity_snapshot"]
        stock = stock_by_key[identity["identity_key"]]
        pending_quantity = pending.get(spec["id"], ZERO) + spec["legacy_pending_quantity"]
        stock_pending = public_pending.get(identity["identity_key"], ZERO)
        available = max(stock["quantity"] - stock_pending, ZERO)
        component_key = (str(spec["component_identity"]), str(spec["unit"].pk))
        component_total = component_totals[component_key]
        remaining = max(component_total["required"] - component_total["internal_issued"] - component_total["pending"], ZERO)
        line = spec["bom_line"]
        specification = (f"{snapshot['tube_shape']} {snapshot['tube_diameter']} × {snapshot['tube_thickness']} · {snapshot['cutting_length_mm']} mm"
                         if snapshot["semi_kind"] == "PIPE" else snapshot["specification"])
        craft_code = str(snapshot.get("completed_craft", {}).get("code") or "")
        processing_status = ("已喷塑" if craft_code == "POWDER_COATING"
                             else "未喷塑" if craft_code == "METAL" and snapshot.get("semi_kind") == "PIPE"
                             else spec["completed_craft"].name)
        bom_attributes = bom_attribute_fields(
            line,
            spray_color_override=snapshot.get("color") if craft_code == "POWDER_COATING" else None,
        )
        rows.append({"requirement_id": str(spec["id"]), "stock_item_id": identity["identity_key"],
            "line_type": "SEMI", "section_code": "SEMI", "stock_mode": "PUBLIC_V2",
            "material_number": "", "material_name": snapshot["part_name"], "part_names": [snapshot["part_name"]],
            "material": snapshot.get("material", ""), "specification": specification, "color": snapshot["color"], "unit": spec["unit"].unit_name,
             "bom_attributes": bom_attributes,
            "required_quantity": str(spec["required_quantity"]), "internal_issued_quantity": str(spec["internal_issued_quantity"]),
            "component_required_quantity": str(component_total["required"]),
            "component_internal_issued_quantity": str(component_total["internal_issued"]),
            "component_pending_issue_quantity": str(component_total["pending"]),
            "component_order_remaining": str(remaining),
            "outsourcing_issued_quantity": "0", "pending_issue_quantity": str(pending_quantity),
            "order_remaining": str(remaining), "available_stock": str(stock["quantity"]),
            "public_stock_quantity": str(stock["quantity"]), "public_pending_quantity": str(stock_pending),
            "max_issue_quantity": str(min(remaining, available)), "bom_version": spec["bom"].version_number,
            "completed_craft": spec["completed_craft"].name, "processing_status": processing_status,
            "warehouse_zone": "；".join(stock["zones"]),
            "warehouse_zones": stock["zones"], "quality": "AVAILABLE", "batch_selection": False,
            "validation_errors": [], "conversion_snapshot": {"kind": "PUBLIC_SEMI", "public_identity": identity,
                "component_identity": str(line.component_identity), "source_revision_hash": spec["source_revision_hash"],
                "completed_craft": spec["completed_craft"].name, "integer_required": True,
                "whole_bar_required": False, "raw_deducted_bar_count": "0", "raw_deducted_meters": "0.00"}})
    return rows, blockers


@transaction.atomic
def sync_public_semi_requirements(issue, requested_ids):
    """写操作锁接收订单与当前 BOM，保留已领历史；忽略同单 RAW 的需求 ID。"""
    if not requested_ids:
        return {}
    task_id, product_id = issue.production_task_id, issue.product_line_id
    ProductionTask.objects.select_for_update().get(pk=task_id)
    ProductionTaskProduct.objects.select_for_update().get(pk=product_id, production_task_id=task_id)
    boms = list(Bom.objects.select_for_update().filter(product_line_id=product_id, archived_at__isnull=True).order_by("id"))
    if boms:
        current_bom = max(boms, key=lambda item: (item.version_number, str(item.pk)))
        # 回货允许只带 bom_line 来源；在公共库存池锁之前锁定明细，
        # 保持与回货的 BOM 明细→余额顺序一致，避免领料之后再补取外键父锁。
        list(BomLine.objects.select_for_update(of=("self",)).filter(section__bom=current_bom).order_by("id"))
    existing = {item.pk: item for item in OrderSemiFinishedRequirement.objects.select_for_update().filter(
        production_task_id=task_id, product_line_id=product_id).order_by("pk")}
    try:
        requested_ids = {UUID(str(value)) for value in requested_ids}
    except (ValueError, TypeError, AttributeError):
        _error("SEMI_REQUIREMENT_INVALID", "半成品需求编号格式不正确。")
    specs, blockers = build_public_semi_specs(task_id, product_id, exclude_issue_id=issue.pk)
    selected = [item for item in specs if item["id"] in requested_ids]
    selected_components = {(item["component_identity"], item["unit"].pk) for item in selected}
    component_specs = [item for item in specs
                       if (item["component_identity"], item["unit"].pk) in selected_components]
    related_bom_line_ids = {str(item["bom_line"].pk) for item in component_specs}
    failed_ids = {item["requirement_id"] for item in blockers if item["requirement_id"]}
    relevant = bool(selected or set(existing) & requested_ids or {str(value) for value in requested_ids} & failed_ids)
    relevant_blockers = [item for item in blockers if item["requirement_id"] is None
        or item["code"].startswith("SEMI_LEGACY_") or item["code"] == "REQUIREMENT_REMOVED_AFTER_ISSUE"
        or item["requirement_id"] in {str(value) for value in requested_ids}
        or item.get("bom_line_id") in related_bom_line_ids]
    if relevant and relevant_blockers:
        _error(relevant_blockers[0]["code"], "本订单半成品需求存在未解决的来源或历史冲突。", blockers=relevant_blockers)
    result = {}
    # 一次同步同部位的所有工艺，避免另一状态保留旧需求或遗漏历史已领。
    # 返回值仍只包含本次用户选择的需求行。
    for spec in component_specs:
        current = existing.get(spec["id"]) or OrderSemiFinishedRequirement(id=spec["id"], production_task_id=task_id, product_line_id=product_id)
        for field in ("component_identity", "bom_line", "completed_craft", "unit", "required_quantity", "internal_issued_quantity", "source_snapshot", "source_revision_hash"):
            setattr(current, field, spec[field])
        current.identity_key = spec["identity"]["identity_key"]
        current.identity_snapshot = spec["identity"]["identity_snapshot"]
        current.save()
        if current.pk in requested_ids:
            result[current.pk] = current
    return result
