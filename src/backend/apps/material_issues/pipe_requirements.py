"""S3 管材部位额度基础，业务入口在 S6/S7 接入。"""

import hashlib
import json
import uuid
from decimal import Decimal

from django.db import transaction
from rest_framework.exceptions import ValidationError

from apps.boms.material_flow_calculations import MaterialFlowValueError, pipe_plan_for_line
from apps.boms.models import Bom, BomLine, BomStatus
from apps.products.material_identity import lock_bom_line_material_identities, resolve_bom_line_raw_material
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.reference_data.models import ProductionUnit

from .models import OrderMaterialRequirement, RequirementContribution


PIPE_NAMESPACE = uuid.UUID("1538e9b3-f2fb-4f02-a2c8-b2c2ab077c1d")


def pipe_error(code, detail):
    error = ValidationError({"code": code, "detail": detail})
    error.api_error_code = code
    return error


def pipe_source_snapshot(line, raw_material):
    try:
        result = pipe_plan_for_line(line)
    except MaterialFlowValueError as error:
        raise pipe_error(error.code, str(error)) from error
    if (line.raw_bar_length_m != Decimal(result["raw_bar_length_m"])
            or line.suggested_bar_count != result["suggested_bar_count"]
            or line.suggested_purchase_meters != Decimal(result["suggested_purchase_meters"])):
        raise pipe_error("SOURCE_REVISION_CHANGED", "管材计算字段与当前 BOM 参数不一致，请先重新确认 BOM。")
    result.update({"bom_id": str(line.section.bom_id), "bom_line_id": str(line.pk),
                   "component_identity": str(line.component_identity), "raw_material_id": str(raw_material.pk),
                   "product_line_id": str(line.section.bom.product_line_id)})
    return result


@transaction.atomic
def sync_pipe_requirement(bom_line_id):
    """每产品每部位一份额度。锁父对象后建账，版本变更不重置历史已发量。"""
    hint = BomLine.objects.select_related("section__bom").get(pk=bom_line_id)
    task = ProductionTask.objects.select_for_update().get(pk=hint.section.bom.production_task_id)
    product = ProductionTaskProduct.objects.select_for_update().get(pk=hint.section.bom.product_line_id)
    boms = list(Bom.objects.select_for_update().filter(product_line=product, archived_at__isnull=True).order_by("-version_number", "-id"))
    if not boms or boms[0].pk != hint.section.bom_id or boms[0].status != BomStatus.VERIFIED:
        raise pipe_error("BOM_NOT_VERIFIED", "只能使用该产品最新已确认 BOM。")
    bom = boms[0]
    if product.production_task_id != task.pk or Decimal(product.quantity) != bom.order_quantity:
        raise pipe_error("SOURCE_REVISION_CHANGED", "订单产品及 BOM 数量不一致。")
    line = BomLine.objects.select_for_update(of=("self",)).select_related("section__bom").get(pk=bom_line_id)
    if line.section.bom_id != bom.pk:
        raise pipe_error("SOURCE_REVISION_CHANGED", "BOM 行来源已变化。")
    if BomLine.objects.filter(section__bom=bom, component_identity=line.component_identity).exclude(pk=line.pk).exists():
        raise pipe_error("COMPONENT_IDENTITY_DUPLICATE", "同一 BOM 中部位编号重复。")
    lock_bom_line_material_identities([line])
    material, _ = resolve_bom_line_raw_material(line)
    if (material is None or material.item_type != "MATERIAL" or material.category.category_name != "管材"
            or material.unit.unit_name != "根"):
        raise pipe_error("MATERIAL_IDENTITY_UNRESOLVED", "管材原料必须关联有效的管材档案，库存单位为根。")
    unit = ProductionUnit.objects.filter(unit_name="支", archived_at__isnull=True, status="ACTIVE").first()
    if unit is None:
        raise pipe_error("UNIT_MISSING", "请先配置有效的支单位。")
    snapshot = pipe_source_snapshot(line, material)
    revision = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    requirement_id = uuid.uuid5(PIPE_NAMESPACE, f"{task.pk}:{product.pk}:{line.component_identity}")
    existing = list(OrderMaterialRequirement.objects.select_for_update().filter(production_task=task).order_by("pk"))
    current_components = set(BomLine.objects.filter(section__bom=bom).values_list("component_identity", flat=True))
    for item in existing:
        used = item.internal_issued_quantity + item.outsourcing_issued_quantity
        if used and ((item.measurement_kind == "PIPE" and item.product_line_id == product.pk and item.component_identity not in current_components)
                     or (item.measurement_kind == "OTHER" and item.section_code == "PROFILE")):
            raise pipe_error("SOURCE_REVISION_CHANGED", "存在无法继承的历史发料部位或旧口径额度，不能再建一份新额度。")
    requirement = next((item for item in existing if item.pk == requirement_id), None)
    if requirement:
        used = requirement.internal_issued_quantity + requirement.outsourcing_issued_quantity
        old_snapshot = requirement.contributions.filter(is_current=True).values_list("calculation_basis", flat=True).first()
        changed = (requirement.raw_material_id != material.pk or requirement.unit_id != unit.pk
                   or requirement.pieces_per_bar != line.pieces_per_bar or requirement.raw_bar_length_m != line.raw_bar_length_m
                   or (old_snapshot and old_snapshot.get("cutting_length_mm") != snapshot["cutting_length_mm"]))
        if used and changed:
            raise pipe_error("SOURCE_REVISION_CHANGED", "已有领用后不能更换原料或切割参数。")
        if used > snapshot["allowance_pieces"]:
            raise pipe_error("REQUIREMENT_BELOW_ISSUED", "新额度低于已确认领用数量。")
    else:
        requirement = OrderMaterialRequirement(id=requirement_id, production_task=task)
    requirement.measurement_kind = "PIPE"
    requirement.product_line = product
    requirement.component_identity = line.component_identity
    requirement.raw_material = material
    requirement.unit = unit
    requirement.line_type = "RAW"
    requirement.section_code = "PROFILE"
    requirement.pieces_per_bar = line.pieces_per_bar
    requirement.raw_bar_length_m = line.raw_bar_length_m
    requirement.required_quantity = snapshot["allowance_pieces"]
    requirement.source_revision_hash = revision
    requirement.save()
    requirement.contributions.filter(is_current=True).exclude(source_revision_hash=revision).update(is_current=False)
    RequirementContribution.objects.update_or_create(requirement=requirement, bom_line=line, source_revision_hash=revision,
        defaults={"product_line": product, "bom": bom, "required_quantity": snapshot["allowance_pieces"],
                  "calculation_basis": snapshot, "is_current": True})
    return requirement
