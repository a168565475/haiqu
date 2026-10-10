import hashlib
import json
import uuid
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomStatus
from apps.procurement.models import PurchaseQuantityParseStatus
from apps.procurement.services import _is_purchasable_bom_section, _source_quantity
from apps.products.material_identity import lock_bom_line_material_identities, resolve_bom_line_raw_material
from apps.products.models import RawMaterialInformation
from apps.production_tasks.models import ProductionTask

from .models import (
    MaterialIssueLineType,
    OrderMaterialRequirement,
    RequirementContribution,
)


REQUIREMENT_NAMESPACE = uuid.UUID("988256a2-1e48-4db2-9217-2c5b28464636")
SECTION_CODES = {
    "管材": "PROFILE",
    "五金": "HARDWARE",
    "塑料件": "PLASTIC",
    "辅料": "AUXILIARY",
    "面料": "FABRIC",
    "包材": "PACKAGING",
}
SECTION_TITLE_CODES = {
    "管材类": "PROFILE",
    "五金件": "HARDWARE",
    "塑料件类": "PLASTIC",
    "辅料类": "AUXILIARY",
    "面料类": "FABRIC",
    "包材类": "PACKAGING",
}


def _stable_requirement_id(task_id, raw_material_id, unit_id, line_type):
    return uuid.uuid5(REQUIREMENT_NAMESPACE, f"{task_id}:{raw_material_id}:{unit_id}:{line_type}")


def _bom_line_section_code(bom_line, source_key=""):
    title = (bom_line.section.title or "").strip()
    if title in SECTION_TITLE_CODES:
        return SECTION_TITLE_CODES[title]
    if source_key == "source_fabric_material_id":
        return "FABRIC"
    if source_key == "source_accessory_material_id":
        return "AUXILIARY"
    return None


def _blocker(code, detail, *, product_line=None, bom=None, bom_line=None, section_code=None):
    return {
        "code": code,
        "detail": detail,
        "product_line_id": str(product_line.pk) if product_line else None,
        "bom_id": str(bom.pk) if bom else None,
        "bom_line_id": str(bom_line.pk) if bom_line else None,
        "section_code": section_code,
    }


def build_requirement_specs(production_task_id, *, lock_material_identities=False):
    task = ProductionTask.objects.prefetch_related("products").get(pk=production_task_id)
    product_lines = list(task.products.all().order_by("line_number", "id"))
    latest_boms = {}
    bom_query = Bom.objects.filter(
        product_line_id__in=[item.pk for item in product_lines],
        archived_at__isnull=True,
    )
    if lock_material_identities:
        # 仓库确认以 BOM 为额度依据；先锁任务、再按稳定顺序锁 BOM，避免与 BOM 编辑并发读取混合快照。
        bom_query = bom_query.select_for_update()
    for bom in bom_query.prefetch_related("sections__lines").order_by(
        "product_line_id", "-version_number", "-id"
    ):
        latest_boms.setdefault(bom.product_line_id, bom)

    if lock_material_identities:
        lock_bom_line_material_identities(
            line
            for bom in latest_boms.values()
            for section in bom.sections.all()
            for line in section.lines.all()
        )

    revision_rows = []
    blockers = []
    contributions = []
    raw_ids = set()
    material_identity_cache = {}
    for product_line in product_lines:
        bom = latest_boms.get(product_line.pk)
        if bom is None:
            blockers.append(_blocker("BOM_MISSING", "该产品没有有效 BOM。", product_line=product_line))
            revision_rows.append({"product_line_id": str(product_line.pk), "bom": None})
            continue
        revision_rows.append(
            {
                "product_line_id": str(product_line.pk),
                "product_quantity": str(product_line.quantity),
                "bom_id": str(bom.pk),
                "version": bom.version_number,
                "status": bom.status,
                "updated_at": bom.updated_at.isoformat(),
            }
        )
        if bom.status != BomStatus.VERIFIED:
            blockers.append(
                _blocker("BOM_NOT_VERIFIED", "该产品最新 BOM 尚未确认。", product_line=product_line, bom=bom)
            )
            continue
        if Decimal(bom.order_quantity) != Decimal(product_line.quantity):
            blockers.append(
                _blocker(
                    "BOM_QUANTITY_STALE",
                    "该产品最新 BOM 数量与生产订单数量不一致，请先同步并重新确认 BOM。",
                    product_line=product_line,
                    bom=bom,
                )
            )
            continue
        for section in bom.sections.all():
            if not _is_purchasable_bom_section(section):
                continue
            for line in section.lines.all():
                if line.cutting_length_mm is not None:
                    blockers.append(_blocker("PIPE_SERVICE_REQUIRED", "新口径管材须使用按部位额度及批次出库入口。",
                                             product_line=product_line, bom=bom, bom_line=line, section_code="PROFILE"))
                    continue
                material, source_key = resolve_bom_line_raw_material(
                    line,
                    cache=material_identity_cache,
                )
                revision_rows.append(
                    {
                        "bom_line_id": str(line.pk),
                        "source_key": source_key,
                        "inventory_raw_material_id": str(material.pk) if material is not None else None,
                    }
                )
                if material is None:
                    if source_key == "source_fabric_material_id":
                        detail = "BOM 行关联的面料材质尚未关联可用的库存原料。"
                    elif source_key == "source_accessory_material_id":
                        detail = "BOM 行关联的辅料材质尚未关联可用的库存原料。"
                    elif source_key:
                        detail = "BOM 行关联的原料不存在、已归档或不是材料类型。"
                    else:
                        detail = f"BOM 行“{line.part_name or line.material}”缺少稳定原料 ID。"
                    blockers.append(
                        _blocker(
                            "MATERIAL_IDENTITY_UNRESOLVED",
                            detail,
                            product_line=product_line,
                            bom=bom,
                            bom_line=line,
                            section_code=_bom_line_section_code(line, source_key),
                        )
                    )
                    continue
                material_id = material.pk
                raw_ids.add(material_id)
                quantity, source_field, source_text, source_unit, parse_status = _source_quantity(line, bom)
                contributions.append(
                    {
                        "product_line": product_line,
                        "bom": bom,
                        "bom_line": line,
                        "raw_material_id": material_id,
                        "source_key": source_key,
                        "quantity": quantity,
                        "source_field": source_field,
                        "source_text": source_text,
                        "source_unit": (source_unit or "").strip(),
                        "parse_status": parse_status,
                    }
                )

    material_map = {
        str(item.pk): item
        for item in RawMaterialInformation.objects.select_related("category", "unit", "color")
        .filter(pk__in=raw_ids, archived_at__isnull=True)
    }
    issued_requirement_ids = list(OrderMaterialRequirement.objects.filter(
        production_task=task,
        contributions__bom_line_id__in=[item["bom_line"].pk for item in contributions],
    ).filter(
        Q(internal_issued_quantity__gt=0) | Q(outsourcing_issued_quantity__gt=0)
    ).values_list("pk", flat=True).distinct())
    issued_requirement_query = OrderMaterialRequirement.objects.filter(pk__in=issued_requirement_ids)
    if lock_material_identities:
        issued_requirements = list(issued_requirement_query.select_for_update().order_by("pk"))
    else:
        issued_requirements = list(issued_requirement_query)
    issued_requirement_ids = [item.pk for item in issued_requirements]
    issued_materials_by_bom_line = defaultdict(set)
    for bom_line_id, raw_material_id in RequirementContribution.objects.filter(
        requirement_id__in=issued_requirement_ids,
        bom_line_id__in=[item["bom_line"].pk for item in contributions],
    ).values_list("bom_line_id", "requirement__raw_material_id"):
        issued_materials_by_bom_line[bom_line_id].add(raw_material_id)

    grouped = defaultdict(list)
    for item in contributions:
        material = material_map.get(str(item["raw_material_id"]))
        if material is None:
            blockers.append(
                _blocker(
                    "MATERIAL_IDENTITY_UNRESOLVED",
                    "BOM 关联的原料不存在、已归档或不可用。",
                    product_line=item["product_line"],
                    bom=item["bom"],
                    bom_line=item["bom_line"],
                    section_code=_bom_line_section_code(item["bom_line"], item["source_key"]),
                )
            )
            continue
        issued_material_ids = issued_materials_by_bom_line.get(item["bom_line"].pk, set())
        if issued_material_ids and material.pk not in issued_material_ids:
            blockers.append(
                _blocker(
                    "MATERIAL_MAPPING_CHANGE_AFTER_ISSUE",
                    "该 BOM 行已有确认发料记录，不能直接改绑库存原料；请先完成冲销或受控迁移。",
                    product_line=item["product_line"],
                    bom=item["bom"],
                    bom_line=item["bom_line"],
                    section_code=_bom_line_section_code(item["bom_line"], item["source_key"]),
                )
            )
            continue
        if item["parse_status"] != PurchaseQuantityParseStatus.READY or item["quantity"] is None:
            blockers.append(
                _blocker(
                    "REQUIREMENT_UNRESOLVED",
                    f"BOM 行“{item['bom_line'].part_name or item['bom_line'].material}”的用量无法解析。",
                    product_line=item["product_line"],
                    bom=item["bom"],
                    bom_line=item["bom_line"],
                    section_code=_bom_line_section_code(item["bom_line"], item["source_key"]),
                )
            )
            continue
        valid_units = {material.unit.unit_name.strip(), material.unit.unit_code.strip()}
        if item["source_unit"] not in valid_units:
            blockers.append(
                _blocker(
                    "UNIT_MISMATCH",
                    f"BOM 单位“{item['source_unit'] or '空'}”与原料库存单位“{material.unit.unit_name}”不一致。",
                    product_line=item["product_line"],
                    bom=item["bom"],
                    bom_line=item["bom_line"],
                    section_code=_bom_line_section_code(item["bom_line"], item["source_key"]),
                )
            )
            continue
        line_type = (
            MaterialIssueLineType.SEMI if material.item_type == "SEMI_FINISHED" else MaterialIssueLineType.RAW
        )
        if line_type == MaterialIssueLineType.SEMI:
            blockers.append(
                _blocker(
                    "SEMI_FINISHED_STOCK_UNAVAILABLE",
                    "委外回库半成品尚未建立按任务产品、部件、完成工艺、颜色和合格状态的独立余额，当前禁止扣减原材料账替代。",
                    product_line=item["product_line"],
                    bom=item["bom"],
                    bom_line=item["bom_line"],
                    section_code="SEMI",
                )
            )
            continue
        section_code = "SEMI" if line_type == MaterialIssueLineType.SEMI else SECTION_CODES.get(
            material.category.category_name
        )
        if not section_code:
            blockers.append(
                _blocker(
                    "SECTION_UNRESOLVED",
                    f"原料类别“{material.category.category_name}”未映射到领料分类。",
                    product_line=item["product_line"],
                    bom=item["bom"],
                    bom_line=item["bom_line"],
                )
            )
            continue
        item.update({"raw_material": material, "line_type": line_type, "section_code": section_code})
        grouped[(material.pk, material.unit_id, line_type)].append(item)

    encoded = json.dumps(revision_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    revision_hash = hashlib.sha256(encoded).hexdigest()
    specs = []
    for (material_id, unit_id, line_type), items in grouped.items():
        material = items[0]["raw_material"]
        total = sum((Decimal(item["quantity"]) for item in items), Decimal("0"))
        specs.append(
            {
                "id": _stable_requirement_id(task.pk, material_id, unit_id, line_type),
                "production_task": task,
                "raw_material": material,
                "unit": material.unit,
                "line_type": line_type,
                "section_code": items[0]["section_code"],
                "required_quantity": total,
                "source_revision_hash": revision_hash,
                "contributions": items,
            }
        )
    specs.sort(key=lambda item: (item["section_code"], item["raw_material"].material_number, str(item["id"])))
    spec_ids = {item["id"] for item in specs}
    stale_issued_query = OrderMaterialRequirement.objects.filter(production_task=task, measurement_kind="OTHER").exclude(pk__in=spec_ids).filter(
        Q(internal_issued_quantity__gt=0) | Q(outsourcing_issued_quantity__gt=0)
    )
    if lock_material_identities:
        stale_issued_query = stale_issued_query.select_for_update().order_by("pk")
    for requirement in stale_issued_query:
        product_line_ids = list(
            requirement.contributions.filter(is_current=True)
            .values_list("product_line_id", flat=True)
            .distinct()
        )
        for product_line_id in product_line_ids or [None]:
            blockers.append(
                {
                    "code": "REQUIREMENT_REMOVED_AFTER_ISSUE",
                    "detail": "最新 BOM 已删除或改绑一项存在历史发料的材料；请先完成冲销或受控迁移。",
                    "product_line_id": str(product_line_id) if product_line_id else None,
                    "bom_id": None,
                    "bom_line_id": None,
                    # 跨 BOM 版本换料可能同时换分区；这是产品级历史额度冲突，不能再按旧大类过滤。
                    "section_code": None,
                }
            )
    return task, specs, blockers, revision_hash


@transaction.atomic
def sync_order_requirements(production_task_id):
    ProductionTask.objects.select_for_update().get(pk=production_task_id)
    task, specs, blockers, revision_hash = build_requirement_specs(
        production_task_id,
        lock_material_identities=True,
    )
    locked_existing = {
        item.pk: item
        for item in OrderMaterialRequirement.objects.select_for_update()
        .filter(production_task=task, measurement_kind="OTHER")
        .order_by("pk")
    }
    active_ids = []
    requirements = []
    for spec in specs:
        requirement = locked_existing.get(spec["id"])
        if requirement is None:
            requirement = OrderMaterialRequirement.objects.create(
                id=spec["id"],
                production_task=task,
                raw_material=spec["raw_material"],
                unit=spec["unit"],
                line_type=spec["line_type"],
                section_code=spec["section_code"],
                required_quantity=spec["required_quantity"],
                source_revision_hash=revision_hash,
            )
        already_issued = requirement.internal_issued_quantity + requirement.outsourcing_issued_quantity
        if spec["required_quantity"] < already_issued:
            raise ValidationError(
                {
                    "code": "REQUIREMENT_BELOW_ISSUED",
                    "detail": "最新订单需求低于已确认发料量，不能覆盖历史额度。",
                    "requirement_id": str(requirement.pk),
                }
            )
        requirement.required_quantity = spec["required_quantity"]
        requirement.section_code = spec["section_code"]
        requirement.source_revision_hash = revision_hash
        requirement.validation_errors = []
        requirement.save(
            update_fields=["required_quantity", "section_code", "source_revision_hash", "validation_errors", "updated_at"]
        )
        requirement.contributions.filter(is_current=True).exclude(source_revision_hash=revision_hash).update(is_current=False)
        for item in spec["contributions"]:
            RequirementContribution.objects.update_or_create(
                requirement=requirement,
                bom_line=item["bom_line"],
                source_revision_hash=revision_hash,
                defaults={
                    "product_line": item["product_line"],
                    "bom": item["bom"],
                    "required_quantity": item["quantity"],
                    "calculation_basis": {
                        "source_key": item["source_key"],
                        "source_field": item["source_field"],
                        "source_text": item["source_text"],
                        "source_unit": item["source_unit"],
                    },
                    "is_current": True,
                },
            )
        active_ids.append(requirement.pk)
        requirements.append(requirement)
    active_id_set = set(active_ids)
    stale_requirements = [item for key, item in locked_existing.items() if key not in active_id_set]
    for requirement in stale_requirements:
        already_issued = requirement.internal_issued_quantity + requirement.outsourcing_issued_quantity
        if already_issued <= 0:
            requirement.contributions.filter(is_current=True).update(is_current=False)
    return task, requirements, blockers, revision_hash
