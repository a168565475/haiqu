"""外发数量契约：原料投入与加工产出分开，预览不写库存或额度。"""
from decimal import Decimal
import hashlib

from django.db import connection

from rest_framework.exceptions import ValidationError

from apps.boms.material_flow_calculations import (
    CUTTING_USAGE_FIELDS, MaterialFlowValueError, cutting_usage_plan, decimal_quantity, fabric_output, pipe_issue,
)
from apps.boms.models import BomStatus
from apps.material_issues.pipe_requirements import pipe_source_snapshot
from apps.products.material_identity import resolve_bom_line_raw_material


def lock_request(kind, request_id):
    """请求号事务锁先于单据锁，跨订单复用也返回业务冲突，不撞唯一键。"""
    key = int.from_bytes(hashlib.sha256(f"outsourcing:{kind}:{request_id}".encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def quantity(value, field="quantity", *, integer=False, allow_zero=False):
    try:
        return decimal_quantity(value, field, places=0 if integer else 4, allow_zero=allow_zero)
    except MaterialFlowValueError as error:
        raise ValidationError({field: str(error), "code": error.code}) from error


def pipe_amount(value, snapshot):
    try:
        return pipe_issue(requested_pieces=value, pieces_per_bar=snapshot["pieces_per_bar"],
                          raw_bar_length_m=snapshot["raw_bar_length_m"])
    except MaterialFlowValueError as error:
        raise ValidationError({"quantity": str(error), "code": error.code}) from error


def processing_basis(line):
    bom = line.section.bom
    if bom.status != BomStatus.VERIFIED:
        raise ValidationError({"bom": "请先确认当前产品的最新 BOM。"})
    if line.section.title.strip() == "管材类":
        material, _ = resolve_bom_line_raw_material(line)
        if (material is None or material.item_type != "MATERIAL" or material.category.category_name != "管材"
                or material.unit.unit_name != "根"):
            raise ValidationError({"material": "管材部位须明确关联以根计量的有效原料。"})
        snapshot = pipe_source_snapshot(line, material)
        snapshot.update({"kind": "PIPE", "material_line_id": str(line.pk), "output_unit": "支", "input_unit": "支"})
        return snapshot
    if line.section.title.strip() != "裁剪明细" or not line.fabric_source_line_id:
        raise ValidationError({"fabric_source_line": "裁片须明确选择对应面料原料行。"})
    fabric = line.fabric_source_line
    material, _ = resolve_bom_line_raw_material(fabric)
    if (fabric.section.bom_id != bom.pk or fabric.section.title.strip() != "面料类"
            or material is None or material.item_type != "MATERIAL" or material.unit.unit_name != "米"):
        raise ValidationError({"fabric_source_line": "裁片必须关联同 BOM 中以米计量的有效面料原料。"})
    try:
        cutting_plan = cutting_usage_plan(**{field: getattr(line, field) for field in CUTTING_USAGE_FIELDS},
                                          order_quantity=bom.order_quantity)
    except MaterialFlowValueError as error:
        raise ValidationError({error.field: str(error), "code": error.code}) from error
    consumption = quantity(cutting_plan["fabric_meters_per_set"] if cutting_plan else line.fabric_meters_per_set,
                           "fabric_meters_per_set")
    snapshot = {"schema_version": 2, "kind": "FABRIC", "bom_id": str(bom.pk), "bom_line_id": str(line.pk),
            "component_identity": str(line.component_identity), "raw_material_id": str(material.pk),
            "material_line_id": str(fabric.pk), "fabric_meters_per_set": str(consumption),
            "output_unit": "套", "input_unit": "米"}
    if cutting_plan is not None:
        snapshot.update(cutting_plan)
    return snapshot


def input_plan(value, snapshot):
    if snapshot["kind"] == "PIPE":
        amount = pipe_amount(value, snapshot)
        return {**amount, "output_quantity": Decimal(amount["requested_pieces"]),
                "raw_quantity": Decimal(amount["bar_count"]), "remainder_meters": "0"}
    value = quantity(value, "input_quantity")
    try:
        result = fabric_output(issued_meters=value, meters_per_set=snapshot["fabric_meters_per_set"])
    except MaterialFlowValueError as error:
        raise ValidationError({"input_quantity": str(error)}) from error
    return {**result, "output_quantity": Decimal(result["expected_sets"]), "raw_quantity": value}


def normalize_product(row, line_map, unit_by_text, *, public=False):
    """来源已加锁后规范化新单；客户端产出预览必须与后端一致。"""
    allocation_map = {}
    for item in row["processing_items"]:
        line = line_map[item["bom_line_id"]]
        snapshot = processing_basis(line)
        unit = unit_by_text.get(snapshot["output_unit"])
        if unit is None:
            raise ValidationError({"unit": f"缺少有效的{snapshot['output_unit']}单位。"})
        item["processing_unit"] = unit
        item["flow_snapshot"] = snapshot
        output_total = Decimal("0")
        for allocation in item["allocations"]:
            value = allocation.get("input_quantity")
            if value is None:
                raise ValidationError({"input_quantity": "请填写本厂实际计划发出的支数或米数。"})
            plan = input_plan(value, snapshot)
            if allocation["allocated_quantity"] != plan["output_quantity"]:
                raise ValidationError({"allocated_quantity": "预计加工支数/套数与输入原料的换算结果不一致。"})
            allocation["flow_snapshot"] = {**snapshot, "remainder_meters": plan["remainder_meters"]}
            allocation_map[(line.pk, allocation["factory_id"])] = (allocation, plan)
            output_total += plan["output_quantity"]
        if item["quantity"] != output_total:
            raise ValidationError({"quantity": "加工数量必须等于各厂预计产出之和。"})
        item["required_quantity"] = Decimal(snapshot["allowance_pieces"]) if snapshot["kind"] == "PIPE" else output_total
    primary_seen = set()
    for material in row["materials"]:
        line = line_map[material["bom_line_id"]]
        key = (material["processing_bom_line_id"], material["factory_id"])
        allocation, plan = allocation_map[key]
        snapshot = allocation["flow_snapshot"]
        raw, _ = resolve_bom_line_raw_material(line)
        if raw is None or raw.item_type != "MATERIAL":
            raise ValidationError({"materials": "发出原料必须有明确且有效的库存档案。"})
        is_primary = str(line.pk) == snapshot["material_line_id"]
        if not is_primary and line.section.title.strip() not in {"五金件", "辅料类"}:
            raise ValidationError({"materials": "原料与本部位加工来源不符，不能混用其他管材或面料。"})
        entered = quantity(material["planned_issue_quantity"])
        if is_primary:
            if entered != allocation["input_quantity"]:
                raise ValidationError({"materials": "部位的原料输入必须与本厂加工分配一致。"})
            primary_seen.add(key)
            material["planned_issue_quantity"] = plan["raw_quantity"]
            material["flow_snapshot"] = snapshot
            material["planned_piece_count"] = int(entered) if snapshot["kind"] == "PIPE" else None
            material["planned_meters"] = Decimal(plan["meters"]) if snapshot["kind"] == "PIPE" else None
        else:
            if line.unit.strip() not in {raw.unit.unit_name, raw.unit.unit_code}:
                raise ValidationError({"materials": "辅料/五金须按其实际库存单位发料。"})
            material["flow_snapshot"] = {"schema_version": 2, "kind": "OTHER", "raw_material_id": str(raw.pk)}
        # 批次预选只保存计划，不占库存；确认发料时仍重新校验。
        planned_batches = material.get("planned_batches", [])
        if public and planned_batches:
            raise ValidationError({"planned_batches": "公共库存外发不关联采购批次，请按库区发料。"})
        if planned_batches:
            from .dispatch_services import batch_candidates
            candidates = {row["inbound_line_id"]: row for row in batch_candidates(material["flow_snapshot"])}
            if len({row["inbound_line_id"] for row in planned_batches}) != len(planned_batches):
                raise ValidationError({"planned_batches": "同一材料批次不能重复选择。"})
            total = Decimal("0")
            saved = []
            for batch in planned_batches:
                candidate = candidates.get(str(batch["inbound_line_id"]))
                if candidate is None:
                    raise ValidationError({"planned_batches": "预选批次身份、长度或库存状态不匹配。"})
                amount = quantity(batch["quantity"])
                if material["flow_snapshot"]["kind"] == "PIPE":
                    pipe_amount(amount, material["flow_snapshot"])
                if amount > Decimal(candidate["available_input_quantity"]):
                    raise ValidationError({"planned_batches": "预选批次可用库存不足。"})
                total += amount
                saved.append({"inbound_line_id": str(batch["inbound_line_id"]), "quantity": str(amount)})
            if total != entered:
                raise ValidationError({"planned_batches": "批次计划合计必须与本次外发数量相同。"})
            material["planned_batches_snapshot"] = saved
        required = (Decimal(snapshot["suggested_bar_count"]) if is_primary and snapshot["kind"] == "PIPE"
                    else quantity(line.unit_consumption, "unit_consumption") * line.section.bom.order_quantity)
        required = quantity(required, "reference_required_quantity")
        material.update(required_quantity=required, procurement_required_quantity=required,
                        quantity_source_field="material_flow_v2", quantity_source_text="BOM 单位与部位换算",
                        procurement_source_field="material_flow_v2", procurement_source_text="按实际原料单位",
                        procurement_unit=raw.unit.unit_name, inventory_unit=raw.unit.unit_name)
    if primary_seen != set(allocation_map):
        raise ValidationError({"materials": "每个加工厂、每个部位必须明确分配对应主原料。"})


def enrich_source_context(data, processing_lines, material_lines, product):
    from apps.material_issues.models import OrderMaterialRequirement
    from apps.material_issues.requirements import build_requirement_specs
    task, specs, _blockers, _ = build_requirement_specs(product.schedule.production_task_id)
    existing = {row.pk: row for row in OrderMaterialRequirement.objects.filter(production_task=task)}
    remaining_by_line = {}
    for spec in specs:
        old = existing.get(spec["id"])
        remaining = max(Decimal("0"), spec["required_quantity"] - (old.internal_issued_quantity + old.outsourcing_issued_quantity if old else 0))
        for contribution in spec["contributions"]:
            remaining_by_line[str(contribution["bom_line"].pk)] = remaining
    line_map = {str(line.pk): line for _, line in processing_lines + material_lines}
    for row in data["processing_items"]:
        line = line_map[row["id"]]
        try:
            snapshot = processing_basis(line)
            if snapshot["kind"] == "PIPE":
                old = next((r for r in existing.values() if r.measurement_kind == "PIPE"
                    and r.product_line_id == product.product_line_id and r.component_identity == line.component_identity), None)
                remaining = max(Decimal("0"), Decimal(snapshot["allowance_pieces"]) - (old.internal_issued_quantity + old.outsourcing_issued_quantity if old else 0))
                row["required_quantity"] = snapshot["demand_pieces"]
                row["reference_usage"] = str(snapshot["pieces_per_product"])
                row["dispatched_quantity"] = str(old.outsourcing_issued_quantity if old else 0)
            else:
                remaining = remaining_by_line.get(snapshot["material_line_id"], Decimal("0"))
                if "cutting_sets_per_product" in snapshot:
                    row["required_quantity"] = str(snapshot["required_sets"])
                    row["reference_usage"] = str(snapshot["cutting_sets_per_product"])
            row.update(conversion_snapshot=snapshot, input_unit=snapshot["input_unit"], unit=snapshot["output_unit"],
                       available_quantity=str(remaining), quantity_error="")
        except ValidationError as error:
            row.update(quantity_error=str(error.detail), available_quantity="0", conversion_snapshot=None)
    for row in data["material_items"]:
        line = line_map[row["id"]]
        if line.section.title.strip() == "管材类":
            processing = next((item for item in data["processing_items"] if item["id"] == row["id"]), None)
            if processing and processing.get("conversion_snapshot"):
                snapshot = processing["conversion_snapshot"]
                row.update(unit="支", default_issue_quantity=processing["available_quantity"],
                    reference_required_quantity=processing["available_quantity"], procurement_required_quantity=snapshot["suggested_bar_count"],
                    procurement_unit="根", conversion_snapshot=snapshot, quantity_error="")
            elif processing:
                row["quantity_error"] = processing["quantity_error"]

    from apps.inventory.public_stock_mode import public_flow_enabled
    if public_flow_enabled():
        from .public_stock_candidates import enrich_public_candidates
        enrich_public_candidates(data, line_map, product)
        return
    from .dispatch_services import batch_candidates, confirmed_batches
    from apps.inventory.stock_services import inbound_batch_available_quantities
    batches = list(confirmed_batches())
    available = inbound_batch_available_quantities(batches)
    for row in data["material_items"]:
        related = next((item.get("conversion_snapshot") for item in data["processing_items"]
                        if item.get("conversion_snapshot", {}) and item["conversion_snapshot"].get("material_line_id") == row["id"]), None)
        if related is None:
            raw, _ = resolve_bom_line_raw_material(line_map[row["id"]])
            related = {"kind": "OTHER", "raw_material_id": str(raw.pk)} if raw else None
        row["candidates"] = batch_candidates(related, batches, available) if related else []
