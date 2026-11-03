"""新材料需求沿已确认BOM保存事实建立；库存数量与制造支数分开。"""
import hashlib
import json
import uuid
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom
from apps.core.api.exceptions import Conflict
from apps.boms.material_attributes import bom_attribute_fields
from apps.inventory.catalog_stock_identity import build_catalog_stock_identity
from apps.inventory.public_bom_snapshot import freeze_bom_line
from apps.material_catalog.saved_selection import validate_saved_material
from apps.procurement.pipe_purchase import pipe_source_snapshot
from apps.procurement.services import _is_purchasable_bom_section, _source_quantity
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.reference_data.models import ProductionUnit
from .models import OrderMaterialRequirement, RequirementContribution


CATALOG_NAMESPACE = uuid.UUID("c1297992-2bc3-47f7-a62a-6b64f6f175d3")


def _json(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder, sort_keys=True))


def catalog_requirement_specs(task_id, product_id, *, lock=False):
    from .requirements import _bom_line_section_code

    boms = Bom.objects.filter(production_task_id=task_id, product_line_id=product_id, archived_at__isnull=True)
    if lock:
        boms = boms.select_for_update()
    bom = boms.order_by("-version_number", "-id").first()
    product = ProductionTaskProduct.objects.get(pk=product_id, production_task_id=task_id)
    if not bom or bom.status != "VERIFIED" or Decimal(product.quantity) != bom.order_quantity:
        return [], []  # 共同BOM门禁负责返回具体原因。
    specs, blockers = [], []
    for section in bom.sections.prefetch_related("lines").all():
        if not _is_purchasable_bom_section(section):
            continue
        for line in section.lines.all():
            if not line.material_catalog_id:
                continue
            section_code = _bom_line_section_code(line)
            try:
                selected = validate_saved_material(line.material_selection_snapshot, material_catalog_id=line.material_catalog_id)
                plan = pipe_source_snapshot(line) if section.section_type == "PROFILE" else {}
                identity = build_catalog_stock_identity(material_catalog_id=line.material_catalog_id, material_selection_snapshot=selected,
                    raw_bar_length_m=plan.get("raw_bar_length_m"))
                quantity, _, _, unit_name, status = _source_quantity(line, bom)
                if status != "READY" or quantity is None or quantity <= 0 or (not plan and unit_name != selected["unit_name"]):
                    raise ValidationError("缺少所选材料单位下的明确需求数量。")
                roots = bool(plan)
                unit_id = selected["unit_id"]
                if roots:
                    unit = ProductionUnit.objects.filter(unit_name="支", status="ACTIVE", archived_at__isnull=True).first()
                    quantity = Decimal(plan["allowance_pieces"])
                else:
                    unit = ProductionUnit.objects.filter(pk=unit_id, status="ACTIVE", archived_at__isnull=True).first()
                if unit is None:
                    raise ValidationError("需求数量单位不存在、已停用或归档。")
                snapshot = _json({**(plan if roots else {}), "kind": "PIPE" if roots else "CATALOG",
                    "material_catalog_id": str(line.material_catalog_id), "material_selection_snapshot": selected,
                    "public_identity": identity, "public_bom_snapshot": freeze_bom_line(line),
                    "bom_attributes": bom_attribute_fields(line),
                    "bom_line_id": str(line.pk), "product_line_id": str(product_id), "component_identity": str(line.component_identity),
                    "manufacturing_plan": plan, "manufacturing_issued_pieces": None,
                    "manufacturing_quantity_source": "PIPE_ALLOCATION" if roots else "UNKNOWN" if plan else "NOT_APPLICABLE",
                    "quantity_unit_id": str(unit.pk), "quantity_unit_name": "支" if roots else selected["unit_name"]})
                revision = hashlib.sha256(json.dumps({"snapshot": snapshot, "quantity": str(quantity)}, sort_keys=True).encode()).hexdigest()
                specs.append({"id": uuid.uuid5(CATALOG_NAMESPACE, f"{task_id}:{product_id}:{line.component_identity}"),
                    "line": line, "unit": unit, "quantity": quantity, "section_code": section_code,
                    "selected": selected, "snapshot": snapshot, "revision": revision})
            except (ValidationError, Conflict) as error:
                blockers.append({"code": "CATALOG_SOURCE_INVALID", "detail": str(error.detail),
                    "product_line_id": str(product_id), "bom_line_id": str(line.pk), "section_code": section_code})
    return specs, blockers


@transaction.atomic
def sync_catalog_requirements(issue, ids):
    ProductionTask.objects.select_for_update().get(pk=issue.production_task_id)
    ProductionTaskProduct.objects.select_for_update().get(pk=issue.product_line_id)
    specs, _ = catalog_requirement_specs(issue.production_task_id, issue.product_line_id, lock=True)
    existing = {row.pk: row for row in OrderMaterialRequirement.objects.select_for_update().filter(
        production_task_id=issue.production_task_id, product_line_id=issue.product_line_id, measurement_kind="CATALOG").order_by("id")}
    result = []
    for spec in specs:
        if spec["id"] not in ids:
            continue
        requirement = existing.get(spec["id"])
        if requirement and requirement.internal_issued_quantity + requirement.outsourcing_issued_quantity > 0:
            old = requirement.conversion_snapshot
            new = spec["snapshot"]
            if (old.get("public_identity", {}).get("identity_key") != new["public_identity"]["identity_key"]
                    or old.get("quantity_unit_id") != new["quantity_unit_id"]
                    or any(old.get("manufacturing_plan", {}).get(key) != new["manufacturing_plan"].get(key)
                           for key in ("cutting_length_mm", "pieces_per_product", "pieces_per_bar", "raw_bar_length_m"))):
                raise ValidationError({"code": "SOURCE_CHANGED", "detail": "已有实际发料后不能覆盖材料单位或制造参数。"})
        if requirement is None:
            requirement = OrderMaterialRequirement(id=spec["id"], production_task_id=issue.production_task_id,
                product_line_id=issue.product_line_id, component_identity=spec["line"].component_identity,
                measurement_kind="CATALOG", line_type="RAW")
        requirement.material_catalog_id = spec["line"].material_catalog_id
        requirement.material_selection_snapshot = spec["selected"]
        requirement.conversion_snapshot = spec["snapshot"]
        requirement.raw_material_id = None
        requirement.unit = spec["unit"]
        requirement.section_code = spec["section_code"]
        requirement.required_quantity = spec["quantity"]
        requirement.source_revision_hash = spec["revision"]
        requirement.save()
        requirement.contributions.filter(is_current=True).exclude(source_revision_hash=spec["revision"]).update(is_current=False)
        RequirementContribution.objects.update_or_create(requirement=requirement, bom_line=spec["line"], source_revision_hash=spec["revision"],
            defaults={"product_line_id": issue.product_line_id, "bom": spec["line"].section.bom,
                "required_quantity": spec["quantity"], "calculation_basis": spec["snapshot"], "is_current": True})
        result.append(requirement)
    return result


def catalog_issue_line_values(requirement):
    selected = requirement.material_selection_snapshot
    attrs = selected["attributes"]
    return dict(line_type="RAW", requirement=requirement, raw_material=None, unit=requirement.unit,
        material_catalog_id=requirement.material_catalog_id, material_selection_snapshot=selected,
        material_number_snapshot="", material_name_snapshot=selected["name"],
        specification_snapshot=" / ".join(attrs.values())[:300], color_snapshot=attrs.get("color", "")[:200],
        unit_snapshot=requirement.conversion_snapshot["quantity_unit_name"],
        conversion_snapshot={**requirement.conversion_snapshot, "source_revision_hash": requirement.source_revision_hash})


def catalog_requirement_rows(task_id, product_id, *, exclude_issue_id=None):
    from .models import MaterialIssue, MaterialIssueLine
    from .public_issue_services import _pool, public_issue_quantity_context, public_line_quantities

    specs, blockers = catalog_requirement_specs(task_id, product_id)
    existing = {row.pk: row for row in OrderMaterialRequirement.objects.filter(pk__in=[spec["id"] for spec in specs])}
    issue = MaterialIssue(production_task_id=task_id, product_line_id=product_id, stock_mode="PUBLIC_V2")
    lines, rows = [], []
    for spec in specs:
        current = existing.get(spec["id"]) or OrderMaterialRequirement(id=spec["id"], production_task_id=task_id,
            product_line_id=product_id, component_identity=spec["line"].component_identity, measurement_kind="CATALOG", line_type="RAW")
        current.material_catalog_id = spec["line"].material_catalog_id
        current.material_selection_snapshot = spec["selected"]
        current.conversion_snapshot = spec["snapshot"]
        current.source_revision_hash = spec["revision"]
        current.unit = spec["unit"]
        current.required_quantity = spec["quantity"]
        line = MaterialIssueLine(issue=issue, requested_quantity=1, section_code_snapshot=spec["section_code"], **catalog_issue_line_values(current))
        lines.append(line)
    context = public_issue_quantity_context(issue, lines=lines, exclude_issue_id=exclude_issue_id)
    for line in lines:
        rows.append({"requirement_id": str(line.requirement_id), "stock_item_id": str(line.material_catalog_id),
            "material_catalog_id": str(line.material_catalog_id), "material_selection_snapshot": line.material_selection_snapshot,
            "line_type": "RAW", "section_code": line.section_code_snapshot, "material_number": "",
            "material_name": line.material_name_snapshot, "specification": line.specification_snapshot,
            "color": line.color_snapshot, "unit": line.unit_snapshot, "part_names": [line.material_name_snapshot],
            "bom_attributes": line.conversion_snapshot["bom_attributes"],
            "conversion_snapshot": line.conversion_snapshot, "batch_candidates": [], "validation_errors": [],
            "warehouse_zones": list(dict.fromkeys(f"{balance.zone.warehouse.warehouse_name} / {balance.zone.zone_name}"
                for balance in context["balances"].get(_pool(line), []))),
            **public_line_quantities(line, context=context, limit_to_order=False)})
    return rows, blockers
