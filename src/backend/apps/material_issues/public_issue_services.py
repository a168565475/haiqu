"""公共库存领料事务；不读采购批次，不切换委外或历史单据入口。"""

import hashlib
import json
import uuid
from collections import defaultdict
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.db.models import Q, Sum
from rest_framework.exceptions import ValidationError

from apps.inventory.models import MaterialStockBalance, PublicStockBalance, WarehouseZone
from apps.inventory.public_stock_identity import build_pipe_stock_identity, validate_public_identity
from apps.inventory.public_bom_snapshot import freeze_bom_line
from apps.inventory.public_stock_mode import public_flow_enabled
from apps.inventory.public_stock_services import _lock_source, debit_public_stock, lock_public_stock_locations
from apps.boms.material_attributes import bom_attribute_fields, merge_bom_attribute_fields
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct

from .models import (
    MaterialIssueLine, MaterialIssuePublicStockAllocation, OrderMaterialRequirement,
    OrderSemiFinishedRequirement,
)
from .material_flow import allocation_plan, pipe_line_snapshot, pipe_specs, sync_selected_pipes
from .public_semi_requirements import (
    build_public_semi_specs, legacy_pending_semi_quantities,
    public_semi_identity, sync_public_semi_requirements,
)
from .requirements import build_requirement_specs, sync_order_requirements
from .scopes import filter_blockers_for_scope, material_section_codes_for_issue


PUBLIC_MODE = "PUBLIC_V2"
ALLOCATION_NAMESPACE = uuid.UUID("8c3bcb42-e71a-4599-916c-613bc67cd728")


def _fail(code, detail, *, lines=None):
    from .services import MaterialIssueValidationError
    raise MaterialIssueValidationError({"detail": detail, "lines": lines or []}, code=code,
                                       meta={"retryable": True, "lines": lines or []})


def _json(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _lines(issue):
    return list(issue.lines.select_related(
        "issue", "requirement__raw_material__unit", "requirement__raw_material__category",
        "raw_material__unit", "unit", "semi_requirement__unit", "semi_requirement__completed_craft",
        "semi_requirement__bom_line__section__bom",
    ).order_by("line_number", "id"))


def _identity(line):
    value = line.conversion_snapshot.get("public_identity")
    return validate_public_identity(value) if value else None


def _frozen_requirement_bom(requirement):
    source = requirement.contributions.filter(is_current=True).select_related(
        "bom_line__section").order_by("-created_at", "id").first()
    if source is None:
        _fail("SOURCE_CHANGED", "管材的 BOM 部位来源已失效。")
    return freeze_bom_line(source.bom_line)


def _pool(line):
    identity = _identity(line)
    return (identity["stock_kind"], identity["identity_key"], identity["unit_id"]) if identity else (
        "OTHER", str(line.raw_material_id), str(line.unit_id),
    )


def _stock_quantity(line):
    if line.conversion_snapshot.get("kind") == "PIPE":
        return Decimal(allocation_plan(line.requested_quantity, line.conversion_snapshot)["bar_count"])
    return line.requested_quantity


def _issue_quantity(line, quantity):
    if line.conversion_snapshot.get("kind") == "PIPE":
        return quantity * Decimal(line.conversion_snapshot["pieces_per_bar"])
    return quantity


def _public_filter(identities):
    result = Q(pk__in=[])
    for identity in identities.values():
        current = Q(stock_kind=identity["stock_kind"], identity_key=identity["identity_key"],
                    unit_id=identity["unit_id"], unit__unit_name=identity["identity_snapshot"]["unit_name"])
        if identity["stock_kind"] == "RAW_PIPE":
            current &= Q(raw_material_id=identity["raw_material_id"],
                         raw_bar_length_m=identity["raw_bar_length_m"],
                         raw_material__archived_at__isnull=True, raw_material__unit_id=identity["unit_id"],
                         raw_material__item_type="MATERIAL", raw_material__category__category_name="管材",
                         raw_material__category__status="ACTIVE", raw_material__category__archived_at__isnull=True,
                         zone__warehouse__warehouse_type="MATERIAL")
        else:
            current &= Q(zone__warehouse__warehouse_type="SEMI_FINISHED")
        result |= current
    return result


def _balances(identities):
    return PublicStockBalance.objects.filter(
        _public_filter(identities), quality="AVAILABLE", zone__status="ACTIVE",
        zone__warehouse__status="ACTIVE", unit__status="ACTIVE", unit__archived_at__isnull=True,
    ).select_related("zone__warehouse", "unit").order_by("zone_id", "id")


def public_ordinary_pending_quantities(raw_material_ids, *, exclude_issue_id=None):
    """普通原料继续共用原余额，预占量应统计所有订单的新旧待审单。"""
    rows = MaterialIssueLine.objects.filter(issue__status="PENDING_REVIEW", line_type="RAW",
        requirement__measurement_kind="OTHER", raw_material_id__in=raw_material_ids)
    if exclude_issue_id:
        rows = rows.exclude(issue_id=exclude_issue_id)
    return {(row["raw_material_id"], row["unit_id"]): row["total"] for row in rows.values(
        "raw_material_id", "unit_id").annotate(total=Sum("requested_quantity"))}


def public_issue_quantity_context(issue, *, exclude_issue_id=None, lines=None, exclude_tube_order_id=None):
    """一次读取全单公共余额和待审占用，供详情逐行复用。"""
    from .services import pending_issue_quantities
    lines = lines if lines is not None else _lines(issue)
    identities = {_pool(line): _identity(line) for line in lines if _identity(line)}
    balances = list(_balances(identities)) if identities else []
    stock, by_pool = defaultdict(Decimal), defaultdict(list)
    for balance in balances:
        key = (balance.stock_kind, balance.identity_key, str(balance.unit_id))
        stock[key] += balance.quantity
        by_pool[key].append(balance)
    ordinary = {(_pool(line)) for line in lines if not _identity(line)}
    raw_filter = Q(pk__in=[])
    for _, raw_id, unit_id in ordinary:
        raw_filter |= Q(raw_material_id=raw_id, unit_id=unit_id)
    if ordinary:
        rows = MaterialStockBalance.objects.filter(
            raw_filter, measurement_kind="OTHER", quality="AVAILABLE", zone__status="ACTIVE",
            zone__warehouse__status="ACTIVE", zone__warehouse__warehouse_type="MATERIAL",
        ).values("raw_material_id", "unit_id").annotate(total=Sum("quantity"))
        for row in rows:
            stock[("OTHER", str(row["raw_material_id"]), str(row["unit_id"]))] = row["total"]
    raw_pending, _ = pending_issue_quantities(
        requirement_ids=[line.requirement_id for line in lines if line.requirement_id],
        exclude_issue_id=exclude_issue_id,
        exclude_tube_order_id=exclude_tube_order_id,
    )
    semi_requirements = {line.semi_requirement_id: line.semi_requirement for line in lines if line.semi_requirement_id}
    # 同一 BOM 部位可同时存在未喷塑、已喷塑两个公共半成品状态，
    # 订单额度按部位和单位统一计算，不能让工序各自重复拥有上限。
    all_semi_requirements = {}
    if issue.production_task_id and issue.product_line_id:
        all_semi_requirements = {
            item.pk: item for item in OrderSemiFinishedRequirement.objects.filter(
                production_task_id=issue.production_task_id,
                product_line_id=issue.product_line_id,
            )
        }
    all_semi_requirements.update(semi_requirements)
    pending_rows = MaterialIssueLine.objects.filter(issue__status="PENDING_REVIEW")
    if exclude_issue_id:
        pending_rows = pending_rows.exclude(issue_id=exclude_issue_id)
    # 共享部位额度要把同一订单、同一部位的所有工艺行一起计算，
    # 因此待审核数量不能只查当前领料单已选择的工艺行。
    semi_pending = {row["semi_requirement_id"]: row["total"] for row in pending_rows.filter(
        semi_requirement_id__in=all_semi_requirements,
    ).values("semi_requirement_id").annotate(total=Sum("requested_quantity"))}
    for key, quantity in legacy_pending_semi_quantities(list(all_semi_requirements.values()), exclude_issue_id=exclude_issue_id).items():
        semi_pending[key] = semi_pending.get(key, Decimal(0)) + quantity
    stock_pending = defaultdict(Decimal)
    if identities:
        rows = pending_rows.filter(
            issue__stock_mode=PUBLIC_MODE,
            conversion_snapshot__public_identity__identity_key__in=[identity["identity_key"] for identity in identities.values()],
        ).only("conversion_snapshot", "requested_quantity", "raw_material_id", "unit_id")
        for row in rows:
            stock_pending[_pool(row)] += _stock_quantity(row)
    if ordinary:
        for (raw_id, unit_id), quantity in public_ordinary_pending_quantities(
                [key[1] for key in ordinary], exclude_issue_id=exclude_issue_id).items():
            stock_pending[("OTHER", str(raw_id), str(unit_id))] += quantity
    from apps.inventory.tube_outsourcing_reservations import (
        tube_public_reserved_quantities, tube_raw_reserved_quantities, tube_material_reserved_quantities,
    )
    raw_scopes = {}
    for line in lines:
        if line.requirement_id and line.conversion_snapshot.get("kind") == "PIPE":
            snapshot = line.conversion_snapshot
            raw_scopes[line.requirement_id] = (
                str(line.requirement.product_line_id or snapshot.get("product_line_id", "")),
                str(line.requirement.component_identity or snapshot.get("component_identity", "")),
            )
    tube_raw = tube_raw_reserved_quantities(raw_scopes.values(), exclude_order_id=exclude_tube_order_id)
    tube_pending_raw = {key: tube_raw.get(scope, Decimal(0)) for key, scope in raw_scopes.items()}
    for key, quantity in tube_pending_raw.items():
        raw_pending[key] = raw_pending.get(key, Decimal(0)) + quantity
    reserved_by_zone = tube_public_reserved_quantities(identities.values(), exclude_order_id=exclude_tube_order_id)
    tube_pending_stock = defaultdict(Decimal)
    material_pending_raw, material_pending_zone = tube_material_reserved_quantities(
        requirement_ids=[line.requirement_id for line in lines if line.requirement_id],
        raw_material_ids=[pool[1] for pool in ordinary], exclude_order_id=exclude_tube_order_id)
    # 普通领料和旧外发也须尊重新管材单附带五金的真实预留。
    tube_pending_raw.update(material_pending_raw)
    for (raw_id, unit_id, _zone_id), quantity in material_pending_zone.items():
        tube_pending_stock[("OTHER", raw_id, unit_id)] += quantity
    for balance in balances:
        pool = (balance.stock_kind, balance.identity_key, str(balance.unit_id))
        tube_pending_stock[pool] += reserved_by_zone.get((pool, str(balance.zone_id)), Decimal(0))
    for pool, quantity in tube_pending_stock.items():
        stock_pending[pool] += quantity
    semi_component_allowances = _semi_component_allowances(
        list(all_semi_requirements.values()), semi_pending,
    )
    return {"lines": lines, "identities": identities, "stock": stock, "balances": by_pool,
            "pending_stock": stock_pending, "pending_raw": raw_pending, "pending_semi": semi_pending,
            "all_semi_requirements": all_semi_requirements,
            "semi_component_allowances": semi_component_allowances,
            "tube_pending_stock": tube_pending_stock, "tube_pending_raw": tube_pending_raw,
            "tube_reserved_by_zone": reserved_by_zone}


def _semi_component_key(requirement):
    return str(requirement.component_identity), str(requirement.unit_id)


def _semi_component_allowances(requirements, pending_by_requirement):
    """按 BOM 部位和单位合并半成品需求、已领和待审数量。"""
    result = {}
    for requirement in requirements:
        key = _semi_component_key(requirement)
        item = result.setdefault(key, {"required": Decimal(0), "issued": Decimal(0), "pending": Decimal(0)})
        # 同一部位的多个工序代表同一套/支需求，需求量取最大值，避免重复计算。
        item["required"] = max(item["required"], Decimal(requirement.required_quantity))
        item["issued"] += Decimal(requirement.internal_issued_quantity)
        item["pending"] += Decimal(pending_by_requirement.get(requirement.pk, Decimal(0)))
    return result


def public_line_quantities(line, *, exclude_issue_id=None, context=None):
    if context is None:
        issue = line.issue
        cache_key = str(exclude_issue_id or "")
        cached = getattr(issue, "_public_quantity_cache", None)
        if not cached or cached[0] != cache_key:
            cached = (cache_key, public_issue_quantity_context(issue, exclude_issue_id=exclude_issue_id))
            issue._public_quantity_cache = cached
        context = cached[1]
    semi = bool(line.semi_requirement_id)
    requirement = line.semi_requirement if semi else line.requirement
    pending = context["pending_semi" if semi else "pending_raw"].get(requirement.pk, Decimal(0))
    external = Decimal(0) if semi else requirement.outsourcing_issued_quantity
    if semi:
        component = context.get("semi_component_allowances", {}).get(_semi_component_key(requirement))
        if component is None:
            component = {"required": Decimal(requirement.required_quantity),
                         "issued": Decimal(requirement.internal_issued_quantity), "pending": pending}
        remaining = max(component["required"] - component["issued"] - component["pending"], Decimal(0))
        required_quantity = component["required"]
        issued_quantity = component["issued"]
        pending_quantity = component["pending"]
    else:
        remaining = max(requirement.required_quantity - requirement.internal_issued_quantity - external - pending, Decimal(0))
        required_quantity = requirement.required_quantity
        issued_quantity = requirement.internal_issued_quantity
        pending_quantity = pending
    pool = _pool(line)
    available = _issue_quantity(line, context["stock"][pool])
    public_pending = _issue_quantity(line, context["pending_stock"][pool])
    free = max(available - public_pending, Decimal(0))
    return {
        "required_quantity": str(required_quantity),
        "internal_issued_quantity": str(issued_quantity),
        "outsourcing_issued_quantity": str(external), "pending_issue_quantity": str(pending_quantity),
        "public_pending_quantity": str(public_pending),
        "order_remaining": str(remaining), "available_stock": str(available),
        "max_issue_quantity": str(max(min(remaining, free), Decimal(0))),
    }


def public_pipe_requirement_rows(task_id, product_id, *, exclude_issue_id=None):
    from .models import MaterialIssue
    specs, blockers = pipe_specs(task_id, product_id)
    existing = {row.pk: row for row in OrderMaterialRequirement.objects.filter(pk__in=[spec["id"] for spec in specs])}
    issue = MaterialIssue(production_task_id=task_id, product_line_id=product_id, stock_mode=PUBLIC_MODE)
    lines, by_id = [], {}
    for spec in specs:
        raw, snapshot = spec["raw_material"], spec["snapshot"]
        current = existing.get(spec["id"]) or OrderMaterialRequirement(
            id=spec["id"], production_task_id=task_id, product_line_id=product_id,
            raw_material=raw, unit=spec["unit"], required_quantity=snapshot["allowance_pieces"],
        )
        # GET 展示最新已确认 BOM 的额度，只继承已领/外发计数；不保存需求行。
        current.required_quantity = Decimal(snapshot["allowance_pieces"])
        identity = build_pipe_stock_identity(raw_material=raw, raw_bar_length_m=Decimal(snapshot["raw_bar_length_m"]), unit=raw.unit)
        line = MaterialIssueLine(issue=issue, requirement=current, raw_material=raw, unit=spec["unit"],
            requested_quantity=Decimal(snapshot["pieces_per_bar"]),
            conversion_snapshot={**snapshot, "bom_attributes": bom_attribute_fields(spec["line"]),
                "public_identity": _json(identity), "source_revision_hash": spec["revision"]})
        lines.append(line)
        by_id[current.pk] = spec
    context = public_issue_quantity_context(issue, exclude_issue_id=exclude_issue_id, lines=lines)
    rows = []
    for line in lines:
        spec, raw = by_id[line.requirement_id], line.raw_material
        rows.append({"requirement_id": str(line.requirement_id), "stock_item_id": str(raw.pk),
            "line_type": "RAW", "section_code": "PROFILE", "stock_mode": PUBLIC_MODE,
            "material_number": raw.material_number, "material_name": raw.material_name,
            "specification": raw.specification, "part_names": [spec["line"].part_name] if spec["line"].part_name else [],
             "bom_attributes": bom_attribute_fields(spec["line"]),
            "color": raw.color.color_name if raw.color_id else raw.color_snapshot, "unit": "支",
            **public_line_quantities(line, context=context),
            "warehouse_zones": list(dict.fromkeys(balance.zone.zone_name for balance in context["balances"][_pool(line)])),
            "bom_version": spec["line"].section.bom.version_number, "validation_errors": [],
            "conversion_snapshot": line.conversion_snapshot, "batch_candidates": []})
    return rows, blockers


def replace_public_issue_lines(issue, inputs):
    from .services import _material_color
    issue.lines.all().delete()
    if not inputs:
        return
    if not issue.production_task_id or not issue.product_line_id or not issue.workshop_id:
        _fail("LINE_SCOPE_INVALID", "添加领料明细前请选择订单、产品和车间。")
    ProductionTask.objects.select_for_update().get(pk=issue.production_task_id)
    allowed = material_section_codes_for_issue(issue)
    if allowed is None:
        _fail("WORKSHOP_MATERIAL_SCOPE_INVALID", "该车间暂未开放生产领料。")
    ids = {item["requirement_id"] for item in inputs}
    semi_map = sync_public_semi_requirements(issue, ids)
    raw_map, revision = {}, ""
    if ids - semi_map.keys():
        _, requirements, _, revision = sync_order_requirements(issue.production_task_id)
        requirements += sync_selected_pipes(issue, ids)
        raw_map = {item.pk: item for item in requirements}
    created, seen = [], set()
    for index, item in enumerate(inputs, 1):
        requested_id = item["requirement_id"]
        if requested_id in seen:
            _fail("DUPLICATE_LINE", "同一订单部位需求不能重复添加。")
        seen.add(requested_id)
        raw, semi = raw_map.get(requested_id), semi_map.get(requested_id)
        if raw is None and semi is None:
            _fail("SOURCE_CHANGED", f"第 {index} 行需求不存在或已失效。")
        section = "SEMI" if semi else raw.section_code
        if section not in allowed:
            _fail("WORKSHOP_MATERIAL_SCOPE_INVALID", f"第 {index} 行不属于所选车间。")
        quantity = item["requested_quantity"]
        if not quantity.is_finite() or quantity <= 0:
            _fail("QUANTITY_INVALID", "领料数量必须为大于零的有限数字。")
        if semi:
            if quantity != quantity.to_integral_value():
                _fail("INTEGER_REQUIRED", "半成品必须按整支或整套领取。")
            identity = public_semi_identity(semi)
            frozen = identity["identity_snapshot"]
            bom_attributes = bom_attribute_fields(
                semi.bom_line,
                spray_color_override=frozen.get("color") if getattr(semi.completed_craft, "outsourcing_code", "") == "POWDER_COATING" else None,
            )
            specification = (f"{frozen['tube_shape']} {frozen['tube_diameter']}×{frozen['tube_thickness']} · {frozen['cutting_length_mm']}mm"
                             if frozen.get("semi_kind") == "PIPE" else frozen.get("specification", ""))
            values = dict(
                line_type="SEMI", semi_requirement=semi, unit=semi.unit,
                material_number_snapshot="", material_name_snapshot=frozen["part_name"],
                specification_snapshot=specification,
                color_snapshot=frozen["color"], unit_snapshot=semi.unit.unit_name,
                 conversion_snapshot={"kind": "PUBLIC_SEMI", "bom_attributes": bom_attributes, "public_identity": _json(identity),
                    "source_revision_hash": semi.source_revision_hash, "component_identity": str(semi.component_identity),
                    "completed_craft": semi.completed_craft.name, "integer_required": True,
                    "raw_deducted_bar_count": "0", "raw_deducted_meters": "0.00"},
            )
        else:
            if not raw.contributions.filter(is_current=True, product_line_id=issue.product_line_id).exists():
                _fail("LINE_SCOPE_INVALID", f"第 {index} 行需求不属于所选产品。")
            material = raw.raw_material
            bom_attributes = merge_bom_attribute_fields(
                bom_attribute_fields(contribution.bom_line)
                for contribution in raw.contributions.filter(
                    is_current=True, product_line_id=issue.product_line_id
                ).select_related("bom_line__section")
            )
            snapshot = pipe_line_snapshot(raw) if raw.measurement_kind == "PIPE" else {}
            snapshot["bom_attributes"] = bom_attributes
            if raw.measurement_kind == "PIPE":
                allocation_plan(quantity, snapshot)
                snapshot["public_identity"] = _json(build_pipe_stock_identity(
                    raw_material=material, raw_bar_length_m=raw.raw_bar_length_m, unit=material.unit,
                ))
                snapshot["public_bom_snapshot"] = _frozen_requirement_bom(raw)
            values = dict(line_type="RAW", requirement=raw, raw_material=material, unit=raw.unit,
                material_number_snapshot=material.material_number, material_name_snapshot=material.material_name,
                specification_snapshot=material.specification, color_snapshot=_material_color(material),
                unit_snapshot=raw.unit.unit_name, conversion_snapshot=snapshot)
        created.append(MaterialIssueLine(issue=issue, line_number=index, requested_quantity=quantity,
                                        section_code_snapshot=section, **values))
    MaterialIssueLine.objects.bulk_create(created)
    issue.source_revision_hash = revision
    issue.save(update_fields=["source_revision_hash", "updated_at"])


def sync_public_issue_sources(issue):
    from .services import MaterialIssueConflict
    ProductionTask.objects.select_for_update().get(pk=issue.production_task_id)
    ProductionTaskProduct.objects.select_for_update().get(pk=issue.product_line_id)
    lines = _lines(issue)
    blockers, revision = [], issue.source_revision_hash
    raw_lines = [line for line in lines if line.requirement_id]
    if raw_lines:
        _, _, blockers, revision = sync_order_requirements(issue.production_task_id)
        pipes = {item.pk: item for item in sync_selected_pipes(issue, {line.requirement_id for line in raw_lines})}
        for line in raw_lines:
            if line.conversion_snapshot.get("kind") == "PIPE":
                current = pipes.get(line.requirement_id)
                if current is None or current.source_revision_hash != line.conversion_snapshot.get("source_revision_hash"):
                    raise MaterialIssueConflict("管材部位或切割参数已变化，请刷新明细。", code="SOURCE_CHANGED")
                frozen_bom = line.conversion_snapshot.get("public_bom_snapshot")
                if public_flow_enabled() and frozen_bom is None:
                    raise MaterialIssueConflict("该待审管材单缺少加工实物属性快照，请退回并刷新明细后重新提交。", code="SOURCE_CHANGED")
                if frozen_bom is not None and frozen_bom != _frozen_requirement_bom(current):
                    raise MaterialIssueConflict("管材 BOM 实物属性已变化，请刷新明细后重新领料。", code="SOURCE_CHANGED")
    semi_lines = [line for line in lines if line.semi_requirement_id]
    current_semi = sync_public_semi_requirements(issue, {line.semi_requirement_id for line in semi_lines}) if semi_lines else {}
    for line in semi_lines:
        current = current_semi.get(line.semi_requirement_id)
        if (current is None or current.source_revision_hash != line.conversion_snapshot.get("source_revision_hash")
                or public_semi_identity(current) != _identity(line)):
            raise MaterialIssueConflict("半成品 BOM 身份或订单需求已变化，请刷新明细。", code="SOURCE_CHANGED")
    return [item for item in blockers if item["code"] != "PIPE_SERVICE_REQUIRED"], revision


def _allocation_id(line_id, balance_id):
    return uuid.uuid5(ALLOCATION_NAMESPACE, f"{line_id}:{balance_id}")


def _lock_public_issue_stock(issue, lines):
    # 空池也必须能串行校验待审占用，不能只依靠已存在的余额行锁。
    pools = sorted({_pool(line) for line in lines})
    for pool in pools:
        value = int.from_bytes(hashlib.sha256(("public-issue-pool:" + ":".join(pool)).encode()).digest()[:8], "big", signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [value])
    identities = {_pool(line): _identity(line) for line in lines if _identity(line)}
    balances = list(_balances(identities)) if identities else []
    # 预先锁本单可能触及的来源事件，保持与公共记账服务相同的事件→余额锁序。
    event_ids = {_allocation_id(line.pk, balance.pk) for line in lines for balance in balances
                 if _pool(line) == (balance.stock_kind, balance.identity_key, str(balance.unit_id))}
    for event_id in sorted(event_ids, key=str):
        _lock_source({"source_type": "MATERIAL_ISSUE", "source_line_id": event_id}, "OUT")
    ordinary_raw_ids = [line.raw_material_id for line in lines if not _identity(line)]
    ordinary = MaterialStockBalance.objects.filter(measurement_kind="OTHER", raw_material_id__in=ordinary_raw_ids, quality="AVAILABLE")
    zone_ids = {balance.zone_id for balance in balances} | set(ordinary.values_list("zone_id", flat=True))
    lock_public_stock_locations(zone_ids)
    list(ordinary.select_for_update().order_by("raw_material_id", "unit_id", "zone_id", "id"))
    list(PublicStockBalance.objects.select_for_update(of=("self",)).filter(pk__in=[balance.pk for balance in balances]).order_by("id"))


def validate_public_issue(issue, *, include_pending=True, lock=False):
    lines = _lines(issue)
    if not lines:
        _fail("LINES_REQUIRED", "提交前至少选择一项领料明细。")
    if lock:
        ProductionTask.objects.select_for_update().get(pk=issue.production_task_id)
        ProductionTaskProduct.objects.select_for_update().get(pk=issue.product_line_id)
        list(OrderMaterialRequirement.objects.select_for_update().filter(
            pk__in=[line.requirement_id for line in lines if line.requirement_id]).order_by("id"))
        list(OrderSemiFinishedRequirement.objects.select_for_update().filter(
            production_task_id=issue.production_task_id, product_line_id=issue.product_line_id).order_by("id"))
        # 同一部位的不同加工状态可能占用不同公共库存池，仍须串行化该部位额度。
        component_keys = sorted({
            _semi_component_key(line.semi_requirement)
            for line in lines if line.semi_requirement_id
        })
        for component, unit_id in component_keys:
            value = int.from_bytes(hashlib.sha256(
                f"public-semi-component:{component}:{unit_id}".encode()
            ).digest()[:8], "big", signed=True)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [value])
        _lock_public_issue_stock(issue, lines)
        lines = _lines(issue)
    context = public_issue_quantity_context(issue, exclude_issue_id=issue.pk, lines=lines)
    if not include_pending:
        # 草稿可以忽略其他待审领料，但已保存外发单的真实预留不能被此参数释放。
        context["pending_stock"] = defaultdict(Decimal, context["tube_pending_stock"])
        context["pending_raw"] = dict(context["tube_pending_raw"])
        context["pending_semi"] = {}
        context["semi_component_allowances"] = _semi_component_allowances(
            list(context.get("all_semi_requirements", {}).values()), context["pending_semi"]
        )
    allowed = material_section_codes_for_issue(issue) or set()
    required_stock, errors = defaultdict(Decimal), []
    semi_requested = defaultdict(Decimal)
    semi_lines_by_component = defaultdict(list)
    for line in lines:
        requirement = line.semi_requirement if line.semi_requirement_id else line.requirement
        if line.section_code_snapshot not in allowed:
            errors.append({"line_id": str(line.pk), "code": "WORKSHOP_MATERIAL_SCOPE_INVALID", "detail": "材料不属于所选车间。"})
            continue
        if (requirement.production_task_id != issue.production_task_id
                or (line.semi_requirement_id and requirement.product_line_id != issue.product_line_id)
                or (line.requirement_id and not requirement.contributions.filter(is_current=True, product_line_id=issue.product_line_id).exists())):
            errors.append({"line_id": str(line.pk), "code": "LINE_SCOPE_INVALID", "detail": "订单需求与当前领料订单不一致。"})
            continue
        if (not line.requested_quantity.is_finite() or line.requested_quantity <= 0
                or (_identity(line) and line.requested_quantity != line.requested_quantity.to_integral_value())):
            errors.append({"line_id": str(line.pk), "code": "INTEGER_REQUIRED", "detail": "公共管材或半成品数量必须是正整数。"})
            continue
        try:
            required_stock[_pool(line)] += _stock_quantity(line)
        except ValidationError:
            errors.append({"line_id": str(line.pk), "code": "PIPE_WHOLE_BAR_REQUIRED", "detail": "管材支数必须符合整根切割数量。"})
            continue
        values = public_line_quantities(line, context=context)
        if line.semi_requirement_id:
            component_key = _semi_component_key(requirement)
            semi_requested[component_key] += line.requested_quantity
            semi_lines_by_component[component_key].append(line)
        elif line.requested_quantity > Decimal(values["order_remaining"]):
            code = "PENDING_ISSUE_CONFLICT" if Decimal(values["pending_issue_quantity"]) else "ORDER_ALLOWANCE_EXCEEDED"
            errors.append({"line_id": str(line.pk), "code": code, "detail": "申请数量超过订单扣除已领、外发及待审后的剩余额度。", **values})
    for component_key, requested in semi_requested.items():
        allowance = context.get("semi_component_allowances", {}).get(component_key)
        if allowance is None:
            continue
        remaining = max(allowance["required"] - allowance["issued"] - allowance["pending"], Decimal(0))
        if requested > remaining:
            code = "PENDING_ISSUE_CONFLICT" if allowance["pending"] else "ORDER_ALLOWANCE_EXCEEDED"
            line = semi_lines_by_component[component_key][0]
            errors.append({"line_id": str(line.pk), "code": code,
                           "detail": "同一 BOM 部位的半成品合计申请数量超过订单扣除已领和待审后的剩余额度。",
                           "required_quantity": str(allowance["required"]),
                           "internal_issued_quantity": str(allowance["issued"]),
                           "pending_issue_quantity": str(allowance["pending"]),
                           "order_remaining": str(remaining),
                           "requested_quantity": str(requested)})
    for pool, needed in required_stock.items():
        pending = context["pending_stock"][pool]
        if needed > max(context["stock"][pool] - pending, Decimal(0)):
            errors.append({"code": "PENDING_ISSUE_CONFLICT" if pending else "STOCK_INSUFFICIENT",
                           "detail": "相同物料公共库存不足，已合计本单各部位及其他待审核占用。"})
    if errors:
        _fail(errors[0]["code"], errors[0]["detail"], lines=errors)
    return context


def confirm_public_issue(issue, actor_employee):
    from .services import _debit_ordinary_line
    context = validate_public_issue(issue, lock=True)
    issued_snapshots = []
    for line in context["lines"]:
        pool, identity = _pool(line), _identity(line)
        stock_before = _issue_quantity(line, context["stock"][pool])
        if identity:
            remaining = _stock_quantity(line)
            for balance in context["balances"][pool]:
                reserved = context["tube_reserved_by_zone"].get((pool, str(balance.zone_id)), Decimal(0))
                taken = min(max(balance.quantity - reserved, Decimal(0)), remaining)
                if taken <= 0:
                    continue
                input_quantity = _issue_quantity(line, taken)
                meters = taken * balance.raw_bar_length_m if balance.stock_kind == "RAW_PIPE" else None
                allocation = MaterialIssuePublicStockAllocation.objects.create(
                    id=_allocation_id(line.pk, balance.pk), line=line, balance=balance,
                    requested_quantity=input_quantity, stock_quantity=taken, meter_quantity=meters,
                    snapshot={"warehouse_zone": f"{balance.zone.warehouse.warehouse_name} / {balance.zone.zone_name}",
                              "stock_unit": balance.unit.unit_name, "identity_key": identity["identity_key"]},
                )
                bom_line_id = line.semi_requirement.bom_line_id if line.semi_requirement_id else line.conversion_snapshot["bom_line_id"]
                movement = debit_public_stock(
                    balance_id=balance.pk, quantity=taken, source_type="MATERIAL_ISSUE", source_id=issue.pk,
                    source_line_id=allocation.pk, actor_employee=actor_employee, production_task=issue.production_task_id,
                    product_line=issue.product_line_id, bom_line=bom_line_id,
                    snapshot={"issue_number": issue.issue_number, "issue_line_id": str(line.pk),
                              "requested_quantity": str(input_quantity), "stock_quantity": str(taken),
                              "public_identity": _json(identity), "conversion": line.conversion_snapshot},
                )
                allocation.movement = movement
                allocation.snapshot.update({"before_quantity": str(movement.before_quantity), "after_quantity": str(movement.after_quantity),
                    "before_meter_quantity": str(movement.before_meter_quantity) if movement.before_meter_quantity is not None else None,
                    "after_meter_quantity": str(movement.after_meter_quantity) if movement.after_meter_quantity is not None else None})
                allocation.save(update_fields=["movement", "snapshot", "updated_at"])
                balance.quantity = movement.after_quantity
                balance.meter_quantity = movement.after_meter_quantity
                context["stock"][pool] -= taken
                remaining -= taken
                if remaining == 0:
                    break
            if remaining:
                _fail("STOCK_INSUFFICIENT", "公共库区余额已变化，本次出库全部回滚。")
            requirement = line.semi_requirement if line.semi_requirement_id else line.requirement
            requirement.internal_issued_quantity += line.requested_quantity
            requirement.save(update_fields=["internal_issued_quantity", "updated_at"])
            if line.semi_requirement_id:
                context["semi_component_allowances"][_semi_component_key(requirement)]["issued"] += line.requested_quantity
        else:
            _debit_ordinary_line(issue, line, actor_employee)
            context["stock"][pool] -= line.requested_quantity
        line.issued_quantity = line.requested_quantity
        if line.semi_requirement_id:
            line.conversion_snapshot.update({"issued_pieces" if line.unit_snapshot == "支" else "issued_sets": str(line.requested_quantity)})
        line.save(update_fields=["issued_quantity", "conversion_snapshot", "updated_at"])
        issued_snapshots.append({"line_id": str(line.pk),
            "stock_before": str(stock_before), "stock_after": str(_issue_quantity(line, context["stock"][pool])),
            **public_line_flow_data(line)})
    # 同部位多工艺混领时，各行均冻结本单全部扣减后的共享剩余额度。
    for line, snapshot in zip(context["lines"], issued_snapshots):
        snapshot.update(public_line_quantities(line, context=context))
    return issued_snapshots


def public_line_flow_data(line):
    allocations = []
    for record in line.public_stock_allocations.all():
        allocations.append({"id": str(record.pk), "balance_id": str(record.balance_id),
            "requested_quantity": str(record.requested_quantity), "stock_quantity": str(record.stock_quantity),
            "meter_quantity": str(record.meter_quantity) if record.meter_quantity is not None else None,
            **record.snapshot})
    is_pipe = line.conversion_snapshot.get("kind") == "PIPE"
    if is_pipe:
        plan = allocation_plan(line.requested_quantity, line.conversion_snapshot)
        bars, meters = str(plan["bar_count"]), str(plan["meters"])
    else:
        bars, meters = "0", "0.00"
    return {"conversion_snapshot": line.conversion_snapshot, "batch_allocations": [],
            "public_stock_allocations": allocations, "bar_count": bars, "meters": meters}


def preview_public_issue(issue):
    from .services import _validate_relations
    errors, context = [], None
    try:
        _validate_relations(issue, require_complete=True)
        context = validate_public_issue(issue)
    except ValidationError as error:
        errors.extend(getattr(error, "error_meta", {}).get("lines", []) or [
            {"code": getattr(error, "api_error_code", "VALIDATION_ERROR"), "detail": str(error.detail)}])
    if context is None:
        context = public_issue_quantity_context(issue, exclude_issue_id=issue.pk)
    if issue.status != "PENDING_REVIEW":
        errors.append({"code": "INVALID_STATE", "detail": "只有待审核领料单可以确认出库。"})
    if any(line.requirement_id for line in context["lines"]):
        _, _, blockers, revision = build_requirement_specs(issue.production_task_id)
        errors.extend(filter_blockers_for_scope([row for row in blockers if row["code"] != "PIPE_SERVICE_REQUIRED"],
            product_line_id=issue.product_line_id, section_codes=material_section_codes_for_issue(issue) or ()))
        if revision != issue.source_revision_hash:
            errors.append({"code": "SOURCE_CHANGED", "detail": "BOM 来源已变化。"})
        specs, _ = pipe_specs(issue.production_task_id, issue.product_line_id)
        current = {row["id"]: row for row in specs}
        for line in context["lines"]:
            if line.conversion_snapshot.get("kind") == "PIPE" and (
                line.requirement_id not in current or current[line.requirement_id]["revision"] != line.conversion_snapshot.get("source_revision_hash")):
                errors.append({"code": "SOURCE_CHANGED", "detail": "管材切割来源已变化。"})
    if any(line.semi_requirement_id for line in context["lines"]):
        specs, blockers = build_public_semi_specs(issue.production_task_id, issue.product_line_id)
        selected_ids = {str(line.semi_requirement_id) for line in context["lines"] if line.semi_requirement_id}
        errors.extend(row for row in blockers if not row.get("requirement_id") or str(row["requirement_id"]) in selected_ids)
        current = {row["id"]: row for row in specs}
        for line in context["lines"]:
            if line.semi_requirement_id and (line.semi_requirement_id not in current or
                current[line.semi_requirement_id]["source_revision_hash"] != line.conversion_snapshot.get("source_revision_hash")):
                errors.append({"code": "SOURCE_CHANGED", "detail": "半成品订单需求来源已变化。"})
    from apps.production_scheduling.models import ProductionScheduleProduct, ProductionScheduleProductCraft
    event = issue.audit_events.filter(action="CREATED").order_by("created_at", "id").first()
    source = event.snapshot.get("plan_source") if event else None
    if source:
        plan = ProductionScheduleProduct.objects.filter(pk=source.get("schedule_product_id"), removed_at__isnull=True,
            schedule__record_status="ACTIVE", schedule__production_task_id=issue.production_task_id,
            product_line_id=issue.product_line_id).first()
        if not plan or not ProductionScheduleProductCraft.objects.filter(schedule_product=plan, removed_at__isnull=True,
                craft_type_snapshot="INTERNAL", plan_category=source.get("plan_category")).exists():
            errors.append({"code": "SOURCE_CHANGED", "detail": "作业计划来源已失效。"})
    rows = [{"line_id": str(line.pk), "requirement_id": str(line.semi_requirement_id or line.requirement_id),
             **public_line_quantities(line, context=context), **public_line_flow_data(line),
             "validation_errors": [error["code"] for error in errors]} for line in context["lines"]]
    return {"can_confirm": bool(rows) and not errors, "lines": rows, "errors": errors}
