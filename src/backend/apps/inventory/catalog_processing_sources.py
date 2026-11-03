"""新目录根制管材的实际领料凭证；不读取当前目录或库存余额补算投入。"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from uuid import UUID

from rest_framework.exceptions import ValidationError

from apps.boms.material_flow_calculations import pipe_issue
from apps.material_catalog.saved_selection import validate_saved_material

from .public_bom_snapshot import _hydrate_line
from .public_stock_identity import validate_public_identity


MAX_PIECES = 99_999_999_999_999


def _whole_quantity(value):
    quantity = Decimal(str(value))
    if (not quantity.is_finite() or not 0 < quantity <= MAX_PIECES
            or quantity != quantity.to_integral_value()):
        raise ValueError("实际支数或根数必须是正整数")
    return quantity


def freeze_catalog_pipe_source(line):
    """仅接受已出库的目录 RAW 根制管材，返回金工首次产出的冻结投入依据。"""
    try:
        return _freeze_catalog_pipe_source(line)
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation, ValidationError) as exc:
        raise ValidationError({
            "source": "新目录管材的领料冻结资料或实际出库凭证缺失、不一致，不能登记首次入库；请核对原领料明细。",
        }) from exc


def _freeze_catalog_pipe_source(line):
    issue, snapshot, requirement = line.issue, line.conversion_snapshot, line.requirement
    if (issue.status != "ISSUED" or issue.stock_mode != "PUBLIC_V2" or line.line_type != "RAW"
            or not line.material_catalog_id or line.raw_material_id is not None
            or snapshot["kind"] != "PIPE" or snapshot["manufacturing_quantity_source"] != "PIPE_ALLOCATION"):
        raise ValueError("来源不是已出库的目录根制管材")
    selected = validate_saved_material(line.material_selection_snapshot, material_catalog_id=line.material_catalog_id)
    identity = validate_public_identity(snapshot["public_identity"])
    if (selected["category_key"] != "TUBE" or selected["template_key"] != "TUBE"
            or selected["processing_state"] != "RAW" or selected["unit_name"] != "根"
            or identity["stock_kind"] != "CATALOG_RAW" or identity["unit_id"] != selected["unit_id"]
            or identity["identity_snapshot"]["material_selection_snapshot"] != selected
            or snapshot["material_selection_snapshot"] != selected
            or str(snapshot["material_catalog_id"]) != str(line.material_catalog_id)
            or line.material_name_snapshot != selected["name"]):
        raise ValueError("领料保存材料与冻结输入身份不一致")
    if (not issue.production_task_id or not issue.product_line_id or not issue.workshop_id or not requirement
            or issue.product_line.production_task_id != issue.production_task_id
            or requirement.production_task_id != issue.production_task_id
            or requirement.product_line_id != issue.product_line_id
            or requirement.measurement_kind != "CATALOG" or requirement.line_type != "RAW"
            or requirement.material_catalog_id != line.material_catalog_id or requirement.raw_material_id is not None
            or str(requirement.component_identity) != snapshot["component_identity"]
            or str(issue.product_line_id) != snapshot["product_line_id"]):
        raise ValueError("领料任务、产品或部位不一致")
    for key in ("component_identity", "product_line_id", "bom_line_id", "bom_id", "quantity_unit_id"):
        UUID(str(snapshot[key]))
    if (not snapshot["source_revision_hash"] or line.unit_snapshot != "支"
            or snapshot["quantity_unit_name"] != "支" or str(line.unit_id) != snapshot["quantity_unit_id"]):
        raise ValueError("领料冻结版本或制造支数单位缺失")
    pieces = _whole_quantity(line.issued_quantity)
    bars = _whole_quantity(snapshot["physical_issued_quantity"])
    pieces_per_bar = _whole_quantity(snapshot["pieces_per_bar"])
    length = identity["raw_bar_length_m"]
    if Decimal(str(snapshot["raw_bar_length_m"])) != length:
        raise ValueError("BOM 匹配原长与实际出库原长不一致")
    actual = pipe_issue(requested_pieces=pieces, pieces_per_bar=pieces_per_bar,
                        raw_bar_length_m=length)
    if (_whole_quantity(snapshot["manufacturing_issued_pieces"]) != pieces
            or actual["bar_count"] != bars):
        raise ValueError("实际支数、根数与冻结切割依据不一致")
    plan = snapshot["manufacturing_plan"]
    for key in ("bom_id", "bom_line_id", "component_identity", "material_catalog_id",
                "material_selection_snapshot", "cutting_length_mm", "pieces_per_product",
                "pieces_per_bar", "raw_bar_length_m"):
        if plan[key] != snapshot[key]:
            raise ValueError("制造依据与领料冻结快照不一致")
    cutting_length = Decimal(str(snapshot["cutting_length_mm"]))
    if not cutting_length.is_finite() or cutting_length <= 0:
        raise ValueError("冻结切割长度无效")
    _whole_quantity(snapshot["pieces_per_product"])
    frozen_bom = snapshot["public_bom_snapshot"]
    if (not isinstance(frozen_bom, dict) or set(frozen_bom) != {"schema_version", "line", "fabric_source_line"}
            or type(frozen_bom["schema_version"]) is not int or frozen_bom["schema_version"] != 1
            or frozen_bom["fabric_source_line"] is not None):
        raise ValueError("缺少管材 BOM 实物属性快照")
    bom_line = _hydrate_line(frozen_bom["line"])
    if (bom_line.pk != snapshot["bom_line_id"] or bom_line.section.bom_id != snapshot["bom_id"]
            or bom_line.section.section_type != "PROFILE"
            or bom_line.material_catalog_id != str(line.material_catalog_id)
            or bom_line.material_selection_snapshot != selected
            or Decimal(str(bom_line.cutting_length_mm)) != cutting_length):
        raise ValueError("BOM 实物属性与冻结投入来源不一致")
    origins = [event for event in issue.audit_events.all() if event.action == "CREATED"]
    if len(origins) != 1 or origins[0].snapshot["plan_source"]["plan_category"] != "METAL":
        raise ValueError("缺少金工领料创建凭证")
    plan_source = origins[0].snapshot["plan_source"]
    UUID(str(plan_source["schedule_id"]))
    UUID(str(plan_source["schedule_product_id"]))

    # U3 在真实 OUT 流水保存后才回填这两个结果字段；其余冻结内容必须逐项相等。
    movement_conversion = deepcopy(snapshot)
    movement_conversion.pop("physical_issued_quantity")
    movement_conversion["manufacturing_issued_pieces"] = None
    movement_conversion["public_identity"] = identity
    allocations = list(line.public_stock_allocations.all())
    if (not allocations or sum(row.requested_quantity for row in allocations) != pieces
            or sum(row.stock_quantity for row in allocations) != bars):
        raise ValueError("缺少与实际领料支数、根数一致的出库分配")
    frozen_allocations, issued_meters = [], Decimal(0)
    for row in sorted(allocations, key=lambda item: str(item.pk)):
        movement, balance = row.movement, row.balance
        row_bars, row_pieces = _whole_quantity(row.stock_quantity), _whole_quantity(row.requested_quantity)
        if (row.line_id != line.pk or row.stock_kind_snapshot != "CATALOG_RAW"
                or row_pieces != row_bars * pieces_per_bar or row.meter_quantity != row_bars * length
                or row.snapshot["identity_key"] != identity["identity_key"] or row.snapshot["stock_unit"] != "根"
                or balance.stock_kind != "CATALOG_RAW" or balance.identity_key != identity["identity_key"]
                or balance.material_catalog_id != line.material_catalog_id or str(balance.unit_id) != selected["unit_id"]
                or balance.raw_material_id is not None or balance.raw_bar_length_m != length
                or Decimal(str(balance.identity_snapshot["raw_bar_length_m"])) != length):
            raise ValueError("公共库存实物身份、实际原长或支根米分配不一致")
        if movement is None:
            raise ValueError("缺少真实公共库存 OUT 流水")
        saved_conversion = deepcopy(movement.snapshot["conversion"])
        saved_conversion["public_identity"] = validate_public_identity(saved_conversion["public_identity"])
        # 同实物池可能保留首单的目录名称、版本和展示文字；不把余额快照当成本单选料快照。
        if (movement.balance_id != row.balance_id or movement.direction != "OUT"
                or movement.stock_kind_snapshot != "CATALOG_RAW" or movement.source_type != "MATERIAL_ISSUE"
                or movement.source_id != issue.pk or movement.source_line_id != row.pk
                or movement.production_task_id != issue.production_task_id or movement.product_line_id != issue.product_line_id
                or str(movement.bom_line_id) != snapshot["bom_line_id"] or movement.quantity != row_bars
                or movement.after_quantity != movement.before_quantity - movement.quantity
                or movement.before_quantity < movement.quantity or movement.after_quantity < 0
                or movement.meter_quantity != row.meter_quantity
                or movement.before_meter_quantity != movement.before_quantity * length
                or movement.after_meter_quantity != movement.after_quantity * length
                or movement.after_meter_quantity != movement.before_meter_quantity - movement.meter_quantity
                or movement.snapshot["issue_line_id"] != str(line.pk)
                or movement.snapshot["issue_number"] != issue.issue_number
                or Decimal(movement.snapshot["requested_quantity"]) != row_pieces
                or Decimal(movement.snapshot["stock_quantity"]) != row_bars
                or validate_public_identity(movement.snapshot["public_identity"]) != identity
                or saved_conversion != movement_conversion
                or Decimal(row.snapshot["before_quantity"]) != movement.before_quantity
                or Decimal(row.snapshot["after_quantity"]) != movement.after_quantity
                or Decimal(row.snapshot["before_meter_quantity"]) != movement.before_meter_quantity
                or Decimal(row.snapshot["after_meter_quantity"]) != movement.after_meter_quantity):
            raise ValueError("真实公共库存 OUT 流水与领料凭证不一致")
        issued_meters += row.meter_quantity
        frozen_allocations.append({
            "allocation_id": str(row.pk), "balance_id": str(row.balance_id), "movement_id": str(movement.pk),
            "pieces": int(row_pieces), "bar_count": int(row_bars), "raw_bar_length_m": format(length, ".2f"),
            "meter_quantity": format(row.meter_quantity, ".2f"),
            "meters": format(row.meter_quantity, ".2f"), "snapshot": deepcopy(row.snapshot),
        })
    if issued_meters != Decimal(actual["meters"]):
        raise ValueError("实际出库米数合计与根数、原长不一致")
    return {
        "schema_version": 2, "stock_mode": "PUBLIC_V2",
        "issue_line_id": str(line.pk), "issue_id": str(issue.pk), "issue_number": issue.issue_number,
        "production_task_id": str(issue.production_task_id), "product_line_id": str(issue.product_line_id),
        "workshop_id": str(issue.workshop_id), "component_identity": snapshot["component_identity"],
        "material_catalog_id": str(line.material_catalog_id), "material_number": line.material_number_snapshot,
        "part_name": bom_line.part_name, "issued_pieces": int(pieces), "bar_count": int(bars),
        "raw_bar_length_m": format(length, ".2f"), "meters": format(issued_meters, ".2f"),
        "conversion_snapshot": deepcopy(snapshot),
        "input_material_selection_snapshot": selected, "public_bom_snapshot": deepcopy(frozen_bom),
        "plan_source": deepcopy(plan_source), "batches": [],
        "allocations": frozen_allocations, "public_stock_allocations": frozen_allocations,
    }
